//! Sidecar management for the bundled Cato daemon executable.
//!
//! Spawns the Tauri-bundled `cato` executable and monitors its health. Release
//! startup never searches PATH for Python or another interpreter.
//! Gracefully shuts down on app exit.

use std::path::PathBuf;
use tauri::AppHandle;
use tauri_plugin_shell::{
    process::{Command, CommandChild, CommandEvent},
    ShellExt,
};
use tokio::time::{sleep, Duration};

/// Manages the Cato daemon sidecar process.
pub struct SidecarManager {
    child: Option<CommandChild>,
    http_port: u16,
    ws_port: u16,
}

impl SidecarManager {
    pub fn new(http_port: u16, ws_port: u16) -> Self {
        Self {
            child: None,
            http_port,
            ws_port,
        }
    }

    pub fn http_port(&self) -> u16 {
        self.http_port
    }

    pub fn ws_port(&self) -> u16 {
        self.ws_port
    }

    pub fn daemon_token() -> Option<String> {
        let token_path = Self::cato_data_dir()?.join("daemon.token");
        std::fs::read_to_string(token_path)
            .ok()
            .map(|token| token.trim().to_string())
            .filter(|token| !token.is_empty())
    }

    /// Check if the daemon is running — either as a child process we spawned,
    /// or as an externally-started daemon already listening on the HTTP port.
    ///
    /// This handles the case where the user started `cato start` manually before
    /// opening the desktop app: the child is None, but the daemon health route
    /// is still responding on the discovered HTTP port.
    pub async fn is_running(&mut self) -> bool {
        // A generic HTTP 200 on the constructor's fallback port does not prove
        // Cato identity. Only a Cato-owned lifecycle marker may select the
        // endpoint used for health acceptance.
        if !self.refresh_ports_from_disk() {
            return false;
        }

        // The shell plugin owns process observation. Health is the runtime
        // contract whether this manager spawned the process or it was already
        // running externally.
        self.check_http_health().await
    }

    /// Return true if the daemon health endpoint responds with HTTP 200.
    async fn check_http_health(&self) -> bool {
        let url = format!("http://127.0.0.1:{}/health", self.http_port);
        let client = reqwest::Client::new();
        matches!(
            client.get(&url).timeout(std::time::Duration::from_millis(800)).send().await,
            Ok(resp) if resp.status().is_success()
        )
    }

    /// Start the Cato daemon as a bundled child process.
    pub async fn start(
        &mut self,
        app: &AppHandle,
    ) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
        // Check if already running (handle crashed state)
        if self.is_running().await {
            return Ok(());
        }

        // A previous child may have exited without a healthy daemon. Drop its
        // handle before replacing it; `kill` is safe to call after exit.
        if let Some(child) = self.child.take() {
            let _ = child.kill();
        }

        // The launch password is a one-child handoff, not retained desktop
        // state. Capture it once, remove it from the long-lived GUI process,
        // and inject it only into the daemon start command below. The stop
        // command never receives it.
        let vault_password = std::env::var_os("CATO_VAULT_PASSWORD");
        if vault_password.is_some() {
            std::env::remove_var("CATO_VAULT_PASSWORD");
        }

        // Clear any stale PID file through the same bundled executable.
        log::info!("Clearing any stale Cato daemon state...");
        let _ = Self::sidecar_command(app)?.arg("stop").output().await;
        sleep(Duration::from_millis(500)).await;

        log::info!("Starting Tauri-bundled Cato daemon: start --channel webchat");

        let mut start_command =
            Self::sidecar_command(app)?.args(["start", "--channel", "webchat"]);
        if let Some(password) = vault_password {
            start_command = start_command.env("CATO_VAULT_PASSWORD", password);
        }

        let (receiver, child) = start_command
            .spawn()
            .map_err(|e| format!("Failed to spawn Tauri-bundled Cato daemon: {e}"))?;
        Self::spawn_log_drain(receiver);

        self.child = Some(child);

        // Wait for the daemon to become healthy. Cold Python starts can take
        // longer on Windows when optional ML/MCP modules are imported.
        self.wait_for_health(120).await?;

        log::info!("Cato daemon is healthy on port {}", self.http_port);
        Ok(())
    }

    /// Stop the Cato daemon gracefully.
    pub async fn stop(&mut self, app: &AppHandle) {
        if let Some(child) = self.child.take() {
            log::info!("Stopping Cato daemon...");

            // Try graceful shutdown via the bundled daemon executable.
            match Self::sidecar_command(app) {
                Ok(command) => {
                    let _ = command.arg("stop").output().await;
                }
                Err(message) => log::error!("{}", message),
            }

            sleep(Duration::from_millis(500)).await;
            // CommandChild::kill consumes the opaque Tauri child handle and
            // is harmless if the graceful `stop` command already exited it.
            let _ = child.kill();
        }
    }

    /// Poll the health endpoint until the daemon is ready.
    async fn wait_for_health(
        &mut self,
        timeout_secs: u64,
    ) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
        let client = reqwest::Client::new();
        let deadline = tokio::time::Instant::now() + Duration::from_secs(timeout_secs);

        loop {
            if tokio::time::Instant::now() >= deadline {
                return Err("Cato daemon health check timed out".into());
            }

            if self.refresh_ports_from_disk() {
                let url = format!("http://127.0.0.1:{}/health", self.http_port);
                match client.get(&url).timeout(Duration::from_secs(2)).send().await {
                    Ok(resp) if resp.status().is_success() => return Ok(()),
                    _ => {}
                }
            }

            sleep(Duration::from_millis(500)).await;
        }
    }

    fn refresh_ports_from_disk(&mut self) -> bool {
        let Some(port_path) = Self::port_file_path() else {
            return false;
        };

        let Ok(raw_port) = std::fs::read_to_string(&port_path) else {
            return false;
        };

        let Ok(http_port) = raw_port.trim().parse::<u16>() else {
            log::warn!("Invalid port file contents in {}", port_path.display());
            return false;
        };

        self.http_port = http_port;
        // Desktop chat and coding-agent traffic both ride the aiohttp /ws surface.
        self.ws_port = http_port;
        true
    }

    fn spawn_log_drain(mut receiver: tauri::async_runtime::Receiver<CommandEvent>) {
        tauri::async_runtime::spawn(async move {
            while let Some(event) = receiver.recv().await {
                match event {
                    CommandEvent::Stdout(bytes) => {
                        let line = String::from_utf8_lossy(&bytes);
                        if !line.trim().is_empty() {
                            log::info!("[cato] {}", line.trim());
                        }
                    }
                    CommandEvent::Stderr(bytes) => {
                        let line = String::from_utf8_lossy(&bytes);
                        if !line.trim().is_empty() {
                            log::warn!("[cato] {}", line.trim());
                        }
                    }
                    CommandEvent::Error(message) => log::error!("[cato] {}", message),
                    CommandEvent::Terminated(payload) => {
                        log::info!("Cato daemon process terminated: {:?}", payload.code);
                    }
                    _ => {}
                }
            }
        });
    }

    fn cato_data_dir() -> Option<PathBuf> {
        if cfg!(windows) {
            // Python's canonical get_data_dir() uses APPDATA on Windows. Honor
            // the same absolute launch-profile path so the desktop and daemon
            // cannot split token/port/vault state across different profiles.
            // Normal Windows launches preserve existing behavior because
            // APPDATA is the OS roaming-app-data known folder.
            if let Some(appdata) = std::env::var_os("APPDATA") {
                let appdata = PathBuf::from(appdata);
                if appdata.is_absolute() {
                    return Some(appdata.join("cato"));
                }
            }
            dirs::config_dir().map(|dir| dir.join("cato"))
        } else {
            dirs::home_dir().map(|dir| dir.join(".cato"))
        }
    }

    fn port_file_path() -> Option<PathBuf> {
        Self::cato_data_dir().map(|dir| dir.join("cato.port"))
    }

    /// Resolve the configured external binary through Tauri's canonical
    /// sidecar API. The name is the configured filename, never an installed
    /// path guess or a PATH lookup.
    fn sidecar_command(app: &AppHandle) -> Result<Command, String> {
        app.shell().sidecar("cato").map_err(|error| {
            format!(
                "Bundled Cato executable is unavailable: {error}. Reinstall the desktop app."
            )
        })
    }
}

impl Drop for SidecarManager {
    fn drop(&mut self) {
        if let Some(child) = self.child.take() {
            let _ = child.kill();
        }
    }
}
