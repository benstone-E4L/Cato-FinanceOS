//! Sidecar management for the bundled Cato daemon executable.
//!
//! Spawns the Tauri-bundled `cato` executable and monitors its health. Release
//! startup never searches PATH for Python or another interpreter.
//! Gracefully shuts down on app exit.

use std::collections::BTreeMap;
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
        self.refresh_ports_from_disk();

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
        let sidecar_env = Self::load_env_file();

        // Clear any stale PID file through the same bundled executable.
        log::info!("Clearing any stale Cato daemon state...");
        let _ = Self::sidecar_command(app)?.arg("stop").output().await;
        sleep(Duration::from_millis(500)).await;

        log::info!("Starting Tauri-bundled Cato daemon: start --channel webchat");

        let mut cmd = Self::sidecar_command(app)?.args(["start", "--channel", "webchat"]);

        for (key, value) in &sidecar_env {
            if std::env::var_os(key).is_none() {
                cmd = cmd.env(key, value);
            }
        }

        let (receiver, child) = cmd
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

            self.refresh_ports_from_disk();
            let url = format!("http://127.0.0.1:{}/health", self.http_port);
            match client.get(&url).timeout(Duration::from_secs(2)).send().await {
                Ok(resp) if resp.status().is_success() => return Ok(()),
                _ => {}
            }

            sleep(Duration::from_millis(500)).await;
        }
    }

    fn refresh_ports_from_disk(&mut self) {
        let Some(port_path) = Self::port_file_path() else {
            return;
        };

        let Ok(raw_port) = std::fs::read_to_string(&port_path) else {
            return;
        };

        let Ok(http_port) = raw_port.trim().parse::<u16>() else {
            log::warn!("Invalid port file contents in {}", port_path.display());
            return;
        };

        self.http_port = http_port;
        // Desktop chat and coding-agent traffic both ride the aiohttp /ws surface.
        self.ws_port = http_port;
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

    /// Load supplemental environment variables from the standard Cato .env locations.
    /// Existing process env vars always win over values from disk.
    fn load_env_file() -> BTreeMap<String, String> {
        for env_path in Self::env_file_candidates() {
            if !env_path.exists() {
                continue;
            }

            match std::fs::read_to_string(&env_path) {
                Ok(contents) => {
                    let parsed = Self::parse_dotenv(&contents);
                    if !parsed.is_empty() {
                        log::info!("Loaded sidecar environment from {}", env_path.display());
                        return parsed;
                    }
                }
                Err(err) => {
                    log::warn!("Failed to read {}: {}", env_path.display(), err);
                }
            }
        }

        BTreeMap::new()
    }

    fn env_file_candidates() -> Vec<PathBuf> {
        let mut candidates = Vec::new();

        if let Ok(path) = std::env::var("CATO_ENV_FILE") {
            let path = PathBuf::from(path);
            if path.is_absolute() {
                candidates.push(path);
            } else if let Ok(cwd) = std::env::current_dir() {
                candidates.push(cwd.join(path));
            }
        }

        if let Some(data_dir) = Self::cato_data_dir() {
            candidates.push(data_dir.join(".env"));
        }

        if let Some(base_dir) = Self::current_exe_base_dir() {
            candidates.push(base_dir.join(".env"));
        }

        if let Ok(cwd) = std::env::current_dir() {
            candidates.push(cwd.join(".env"));
        }

        candidates
    }

    fn parse_dotenv(contents: &str) -> BTreeMap<String, String> {
        let mut out = BTreeMap::new();

        for raw_line in contents.lines() {
            let line = raw_line.trim();
            if line.is_empty() || line.starts_with('#') {
                continue;
            }

            let line = line.strip_prefix("export ").unwrap_or(line);
            let Some((key, value)) = line.split_once('=') else {
                continue;
            };

            let key = key.trim();
            if key.is_empty() {
                continue;
            }

            let value = value.trim();
            let value = if value.len() >= 2
                && ((value.starts_with('"') && value.ends_with('"'))
                    || (value.starts_with('\'') && value.ends_with('\'')))
            {
                value[1..value.len() - 1].to_string()
            } else {
                value.to_string()
            };

            out.insert(key.to_string(), value);
        }

        out
    }

    fn cato_data_dir() -> Option<PathBuf> {
        if cfg!(windows) {
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
        if let Some(mut child) = self.child.take() {
            let _ = child.kill();
        }
    }
}
