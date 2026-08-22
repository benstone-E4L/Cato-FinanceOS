//! Sidecar management for the bundled Cato daemon executable.
//!
//! Spawns the Tauri-bundled `cato` executable and monitors its health. Release
//! startup never searches PATH for Python or another interpreter.
//! Gracefully shuts down on app exit.

use std::path::PathBuf;
use tauri::{AppHandle, Manager};
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
    fn health_matches_expected_build(health: &serde_json::Value, expected_sha: &str) -> bool {
        matches!(
            health.get("status").and_then(|value| value.as_str()),
            Some("ok" | "degraded")
        )
            && (expected_sha == "development"
                || health.get("source_sha").and_then(|value| value.as_str())
                    == Some(expected_sha))
    }

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

    /// Return true only when the daemon health endpoint identifies the same
    /// source revision embedded in this desktop build.
    async fn check_http_health(&self) -> bool {
        let url = format!("http://127.0.0.1:{}/health", self.http_port);
        let client = reqwest::Client::new();
        let response = match client
            .get(&url)
            .timeout(std::time::Duration::from_millis(800))
            .send()
            .await
        {
            Ok(response) if response.status().is_success() => response,
            _ => return false,
        };
        let health: serde_json::Value = match response.json().await {
            Ok(health) => health,
            Err(_) => return false,
        };
        Self::health_matches_expected_build(&health, super::NATIVE_BUILD_SHA)
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

        // Clear any stale PID file WITHOUT unpacking the 378 MB PyInstaller
        // sidecar a second time (measured ~46s of pure unpack cost on this
        // build, before the daemon even starts). See
        // `clear_stale_daemon_state` below for exactly what this reproduces
        // and why it is safe to do natively.
        log::info!("Clearing any stale Cato daemon state...");
        Self::clear_stale_daemon_state().await;

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

    /// Reproduce `cato stop`'s state-clearing effect for the pre-launch path
    /// without spawning the bundled PyInstaller sidecar. `cato stop`
    /// (cato/cli.py::cmd_stop, backed by cato/platform.py::terminate_pid /
    /// `_run_taskkill`) does exactly two things: (1) if `cato.pid` names a
    /// still-live process, tree-kill it — on Windows that is itself just a
    /// shell-out to the native `taskkill` utility, since SIGTERM is not
    /// deliverable there, so nothing is lost by doing that shell-out here
    /// instead of inside the sidecar — and only then (2) delete the stale
    /// `cato.pid` / `cato.port` files. Both are reproduced here directly.
    /// Deleting the files without confirming the process actually exited
    /// would recreate exactly the double-daemon-on-one-hash-chained-ledger
    /// risk `cato stop` exists to avoid, so this waits for confirmed exit
    /// via `terminate_pid` (below) before touching them; the untouched,
    /// independent duplicate-start gates in `cato start` (PID-file check,
    /// then a live `/health` probe on the configured port) remain the real
    /// backstop either way.
    ///
    /// Known gap, shared with the Python it mirrors: neither this nor
    /// `cato/platform.py::terminate_pid` confirms the PID still belongs to
    /// a Cato process before signalling it, so an OS PID reuse after an
    /// unclean exit could in theory hit an unrelated process. Not fixed
    /// here — see the reasoning in the task report; this file has no
    /// existing constant for the bundled sidecar's expected image name to
    /// check against (that lives only in `tauri.conf.json`, out of scope
    /// for this change and about to move under the follow-on --onedir
    /// bundling task), and the Python source of truth for this behaviour
    /// carries the identical gap today.
    async fn clear_stale_daemon_state() {
        let Some(data_dir) = Self::cato_data_dir() else {
            return;
        };
        let pid_path = data_dir.join("cato.pid");
        let port_path = data_dir.join("cato.port");

        if !pid_path.exists() {
            // No pid file recorded at all -- matches `_read_live_pid`'s own
            // `not _PID_FILE.exists(): return None` no-op path, which does
            // not touch the port file either.
            return;
        }

        let pid: u32 = match std::fs::read_to_string(&pid_path) {
            Ok(raw) => match raw.trim().parse::<u32>() {
                Ok(pid) => pid,
                Err(_) => {
                    // Unparseable content. `_read_live_pid`'s
                    // `except (OSError, ValueError)` catches this the same
                    // way it catches an unreadable file, immediately below:
                    // delete both files: there is no pid to signal.
                    let _ = std::fs::remove_file(&pid_path);
                    let _ = std::fs::remove_file(&port_path);
                    return;
                }
            },
            Err(_) => {
                // File exists but could not be read (e.g. a permission
                // error). `_read_live_pid` treats this the same as bad
                // content -- unlink both, return None -- not the same as
                // "not running", which only applies when the file is
                // absent (handled above).
                let _ = std::fs::remove_file(&pid_path);
                let _ = std::fs::remove_file(&port_path);
                return;
            }
        };

        if !Self::terminate_pid(pid).await {
            log::warn!(
                "Cato daemon pid {} did not exit after a stop request; leaving \
                 cato.pid/cato.port in place so the duplicate-start guard still sees it.",
                pid
            );
            return;
        }

        let _ = std::fs::remove_file(&pid_path);
        let _ = std::fs::remove_file(&port_path);
    }

    /// Terminate `pid` and wait for it to actually exit. Mirrors
    /// `cato/platform.py::terminate_pid` exactly: a *graceful* stop request
    /// first, escalating to a forced kill only if the process is still
    /// alive at the halfway point of a 10-second timeout — the same
    /// timeout, halfway-escalation point, and true "confirmed gone" return
    /// contract the Python uses. Returns true once the process is
    /// confirmed gone (or was never alive to begin with).
    async fn terminate_pid(pid: u32) -> bool {
        if !Self::pid_alive(pid).await {
            return true;
        }

        let timeout = Duration::from_secs(10);
        let poll_interval = Duration::from_millis(200);
        let now = tokio::time::Instant::now();
        let deadline = now + timeout;
        let graceful_deadline = now + timeout / 2;

        Self::send_stop_signal(pid, false).await;

        let mut escalated = false;
        while tokio::time::Instant::now() < deadline {
            if !Self::pid_alive(pid).await {
                return true;
            }
            if !escalated && tokio::time::Instant::now() >= graceful_deadline {
                escalated = true;
                Self::send_stop_signal(pid, true).await;
            }
            sleep(poll_interval).await;
        }

        !Self::pid_alive(pid).await
    }

    /// Send one stop signal to `pid`: graceful (`force = false`) or forced
    /// (`force = true`). Windows has no deliverable SIGTERM, so both cases
    /// shell out to `taskkill` there — the same native utility the Python
    /// CLI itself calls for exactly this (`cato/platform.py::_run_taskkill`)
    /// — never the sidecar. Elsewhere, `kill -TERM` then `kill -KILL`.
    /// Bounded by a 10s timeout on the subprocess call itself, mirroring
    /// `_run_taskkill`'s `subprocess.run(..., timeout=10)` /
    /// `SubprocessError` catch: a hung OS command must not silently blow
    /// past `terminate_pid`'s own advertised 10-second contract above.
    async fn send_stop_signal(pid: u32, force: bool) {
        let attempt = if cfg!(windows) {
            let mut args: Vec<String> = vec!["/T".into(), "/PID".into(), pid.to_string()];
            if force {
                args.insert(0, "/F".into());
            }
            tokio::time::timeout(
                Duration::from_secs(10),
                tokio::process::Command::new("taskkill").args(&args).output(),
            )
            .await
        } else {
            let signal = if force { "-KILL" } else { "-TERM" };
            tokio::time::timeout(
                Duration::from_secs(10),
                tokio::process::Command::new("kill")
                    .args([signal, &pid.to_string()])
                    .output(),
            )
            .await
        };
        // Best-effort either way -- the caller (`terminate_pid`) confirms
        // the real outcome itself by polling `pid_alive`, not by trusting
        // this call's exit status.
        let _ = attempt;
    }

    /// Native liveness probe for `pid`, without adding a process-inspection
    /// crate for this one narrow use. Mirrors `cato/platform.py::pid_alive`
    /// field for field: the `pid <= 0` guard (a `u32` cannot be negative,
    /// so only the `0` case — Windows' System Idle Process / POSIX's swapper
    /// — remains and is checked explicitly), the Windows ctypes-failure
    /// fail-closed stance, and the POSIX `ProcessLookupError` /
    /// `PermissionError` / zombie split (see `posix_pid_alive` below for how
    /// that split is reproduced without a crate).
    async fn pid_alive(pid: u32) -> bool {
        if pid == 0 {
            return false;
        }
        if cfg!(windows) {
            Self::win_pid_alive(pid).await
        } else {
            Self::posix_pid_alive(pid).await
        }
    }

    /// Windows liveness probe via `tasklist`. Matches on the *quoted PID
    /// field* of CSV output (`/FO CSV`), not a raw whole-line substring —
    /// a plain `line.contains(pid.to_string())` can false-positive against
    /// the memory-usage or session-number columns (e.g. a mem-usage value
    /// like "12,345 K" contains the digits of an unrelated pid "345", and a
    /// single-digit session number can equal a single-digit pid). Anchoring
    /// on `,"<pid>",` (or `,"<pid>"` at line end) requires the value to
    /// appear as its own comma-delimited field, not merely as a digit
    /// sequence anywhere in the row.
    async fn win_pid_alive(pid: u32) -> bool {
        let output = match tokio::process::Command::new("tasklist")
            .args(["/FI", &format!("PID eq {pid}"), "/NH", "/FO", "CSV"])
            .output()
            .await
        {
            Ok(output) => output,
            Err(_) => return true, // fail closed, mirrors the ctypes-failure path
        };
        let stdout = String::from_utf8_lossy(&output.stdout);
        let mid = format!(",\"{pid}\",");
        let end = format!(",\"{pid}\"");
        stdout
            .lines()
            .any(|line| {
                let line = line.trim_end();
                line.contains(&mid) || line.ends_with(&end)
            })
    }

    /// POSIX liveness probe. `kill -0`'s process exit status alone cannot
    /// distinguish "genuinely gone" (`ESRCH`, Python's `ProcessLookupError`)
    /// from "exists but not ours to signal" (`EPERM`, Python's
    /// `PermissionError`) — both come back as a non-zero exit code from the
    /// external `kill(1)` binary, unlike `os.kill`'s Python-level exception
    /// types.
    ///
    /// Correctness boundary, stated plainly rather than claimed as
    /// universal: this disambiguates the two cases — exactly finding 5's
    /// requirement — ONLY on Linux, via `/proc/<pid>` existence (visible
    /// for a process regardless of which user owns it on a normal,
    /// non-`hidepid`-hardened mount; the same procfs surface
    /// `posix_is_zombie` below already depends on). No bundled target ships
    /// for any other POSIX platform today (the only artifact built is
    /// `x86_64-pc-windows-msvc`, which never reaches this function at all),
    /// but `tauri.conf.json` declares `"targets": "all"`, so this must not
    /// silently misbehave if a macOS/BSD build is ever produced. Neither
    /// has a procfs, so on anything other than Linux a `kill -0` failure is
    /// left ambiguous — EPERM and ESRCH are indistinguishable there without
    /// a process-inspection crate — and is answered by failing CLOSED
    /// (reporting alive) rather than guessing dead, which is the one
    /// property finding 5 actually requires (never let a live daemon we
    /// merely couldn't identify get treated as absent). So:
    ///   - `kill -0` succeeds -> exists and permitted -> Python's
    ///     no-exception path -> still zombie-checked before calling it alive.
    ///   - `kill -0` fails, target is Linux, `/proc/<pid>` exists -> exists,
    ///     not ours (EPERM-equivalent) -> Python's `PermissionError` branch
    ///     -> true, no zombie check, matching Python exactly.
    ///   - `kill -0` fails, target is Linux, `/proc/<pid>` is absent ->
    ///     genuinely gone (ESRCH-equivalent) -> Python's
    ///     `ProcessLookupError` branch -> false, matching Python exactly.
    ///   - `kill -0` fails, target is NOT Linux -> cannot distinguish EPERM
    ///     from ESRCH at all -> true (fail closed; correct in the sense of
    ///     "never wrongly reports dead", not in the sense of ever reporting
    ///     a genuinely-gone process as gone).
    /// Python's residual bare `except OSError: return False` (some other,
    /// rarer errno) has no distinct branch here on any target; on Linux it
    /// collapses into the `/proc/<pid>` check, an accurate approximation
    /// for that already-rare tail case rather than an exact port of it.
    async fn posix_pid_alive(pid: u32) -> bool {
        let permitted = match tokio::process::Command::new("kill")
            .args(["-0", &pid.to_string()])
            .output()
            .await
        {
            Ok(output) => output.status.success(),
            Err(_) => return true, // fail closed: could not even run the probe
        };

        if !permitted {
            if cfg!(target_os = "linux") {
                return std::path::Path::new(&format!("/proc/{pid}")).is_dir();
            }
            // No procfs on this target to tell EPERM from ESRCH — fail
            // closed rather than silently answering "dead" (see doc above).
            return true;
        }

        !Self::posix_is_zombie(pid)
    }

    /// Mirrors `cato/platform.py::_posix_is_zombie`: true when
    /// `/proc/<pid>/stat` exists but the process state field is `Z`. A
    /// plain file read, not a process-inspection crate.
    fn posix_is_zombie(pid: u32) -> bool {
        let Ok(data) = std::fs::read_to_string(format!("/proc/{pid}/stat")) else {
            return false;
        };
        // Format: "pid (comm) state ..." — comm may itself contain
        // spaces/parens, so state is read relative to the LAST ')'.
        let Some(rparen) = data.rfind(')') else {
            return false;
        };
        matches!(data.get(rparen + 2..rparen + 3), Some("Z"))
    }

    /// Poll the health endpoint until the daemon is ready.
    async fn wait_for_health(
        &mut self,
        timeout_secs: u64,
    ) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
        let deadline = tokio::time::Instant::now() + Duration::from_secs(timeout_secs);

        loop {
            if tokio::time::Instant::now() >= deadline {
                return Err("Cato daemon health check timed out".into());
            }

            if self.refresh_ports_from_disk() && self.check_http_health().await {
                return Ok(());
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
        Ok(app.shell().command(Self::bundled_executable_path(app)?))
    }

    /// Absolute path to the real daemon executable inside the staged onedir
    /// bundle.
    ///
    /// The daemon used to be an `externalBin` resolved by name through
    /// `shell().sidecar("cato")`. It is now a PyInstaller **onedir** bundle,
    /// because a onefile build re-extracts its whole archive to a temp
    /// directory on every launch — measured at 46.273s just to print
    /// `--version`, against 2.895s warm for onedir. `externalBin` takes a
    /// single file and a onedir build is a directory, so the bundle ships as a
    /// Tauri resource and the executable is resolved by path instead of by
    /// name.
    ///
    /// The directory name is fixed (not target-triple-suffixed) because
    /// `tauri.conf.json` is static JSON with no per-target substitution; the
    /// triple that `externalBin` used to append lives in neither path now.
    fn bundled_executable_path(app: &AppHandle) -> Result<PathBuf, String> {
        let resource_dir = app.path().resource_dir().map_err(|error| {
            format!("Cannot resolve the app resource directory: {error}. Reinstall the desktop app.")
        })?;
        let executable = resource_dir
            .join("cato-sidecar")
            .join(if cfg!(windows) { "cato.exe" } else { "cato" });
        if !executable.is_file() {
            return Err(format!(
                "Bundled Cato executable is unavailable at {}. Reinstall the desktop app.",
                executable.display()
            ));
        }
        Ok(executable)
    }
}

#[cfg(test)]
mod tests {
    use super::SidecarManager;
    use serde_json::json;

    #[test]
    fn health_requires_status_and_exact_embedded_revision() {
        let expected = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        assert!(SidecarManager::health_matches_expected_build(
            &json!({"status": "ok", "source_sha": expected}),
            expected,
        ));
        assert!(SidecarManager::health_matches_expected_build(
            &json!({"status": "degraded", "source_sha": expected}),
            expected,
        ));
        assert!(!SidecarManager::health_matches_expected_build(
            &json!({"status": "ok", "source_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}),
            expected,
        ));
        assert!(!SidecarManager::health_matches_expected_build(
            &json!({"status": "error", "source_sha": expected}),
            expected,
        ));
    }
}

impl Drop for SidecarManager {
    fn drop(&mut self) {
        if let Some(child) = self.child.take() {
            let _ = child.kill();
        }
    }
}
