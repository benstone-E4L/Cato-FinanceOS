use std::{env, fs, path::PathBuf};

fn ensure_sidecar_placeholder() {
    let Ok(target) = env::var("TARGET") else {
        return;
    };

    let Ok(manifest_dir) = env::var("CARGO_MANIFEST_DIR") else {
        return;
    };

    let binaries_dir = PathBuf::from(manifest_dir).join("binaries");
    let mut placeholder = binaries_dir.join(format!("cato-{target}"));
    if target.contains("windows") {
        placeholder.set_extension("exe");
    }

    if placeholder.exists() {
        return;
    }

    if let Err(err) = fs::create_dir_all(&binaries_dir) {
        panic!("failed to create sidecar placeholder dir: {err}");
    }

    let stub = b"placeholder sidecar stub; desktop/scripts/stage_sidecar.py replaces this during tauri build\n";
    if let Err(err) = fs::write(&placeholder, stub) {
        panic!("failed to create sidecar placeholder {}: {err}", placeholder.display());
    }
}

fn main() {
    ensure_sidecar_placeholder();
    tauri_build::build()
}
