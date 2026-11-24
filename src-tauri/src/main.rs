#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

#[cfg(target_os = "macos")]
mod desktop {
    use std::{
        error::Error,
        fs::{self, OpenOptions},
        io::{BufRead, BufReader, Read, Write},
        net::TcpStream,
        os::unix::process::CommandExt,
        path::PathBuf,
        process::{Child, Command, Stdio},
        sync::Mutex,
        time::{Duration, Instant},
    };

    use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

    struct Backend(Child);

    impl Drop for Backend {
        fn drop(&mut self) {
            // The child creates its own process group for the backend and workers.
            unsafe { libc::kill(-(self.0.id() as i32), libc::SIGTERM); }
            let deadline = Instant::now() + Duration::from_secs(3);
            while Instant::now() < deadline {
                if matches!(self.0.try_wait(), Ok(Some(_))) { break; }
                std::thread::sleep(Duration::from_millis(40));
            }
            unsafe { libc::kill(-(self.0.id() as i32), libc::SIGKILL); }
            let _ = self.0.wait();
        }
    }

    fn healthy(port: u16, token: &str) -> bool {
        let address = std::net::SocketAddr::from(([127, 0, 0, 1], port));
        let timeout = Duration::from_millis(500);
        let Ok(mut stream) = TcpStream::connect_timeout(&address, timeout) else { return false; };
        if stream.set_read_timeout(Some(timeout)).is_err()
            || stream.set_write_timeout(Some(timeout)).is_err()
        { return false; }
        let request = format!("GET /api/v1/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAuthorization: Bearer {token}\r\nConnection: close\r\n\r\n");
        let mut prefix = [0; 12];
        stream.write_all(request.as_bytes()).is_ok()
            && stream.read_exact(&mut prefix).is_ok()
            && &prefix == b"HTTP/1.1 200"
    }

    fn start(app: &mut tauri::App) -> Result<(), Box<dyn Error>> {
        let home = app.path().home_dir()?;
        let key = "FasterQwen3TTSStudio";
        let root = home.join("Library/Application Support").join(key);
        let cache = home.join("Library/Caches").join(key);
        let logs = home.join("Library/Logs").join(key);
        for directory in [&root, &cache, &logs, &root.join("runtime")] {
            fs::create_dir_all(directory)?;
        }
        let log_path = logs.join("backend.log");
        if fs::metadata(&log_path).map(|m| m.len() > 2_000_000).unwrap_or(false) {
            fs::rename(&log_path, logs.join("backend.previous.log"))?;
        }
        let log = OpenOptions::new().create(true).append(true).open(log_path)?;
        let resources: PathBuf = app.path().resource_dir()?.join("studio");
        let runtime = resources.join("python");
        let mut backend = Backend(Command::new(runtime.join("bin/python3.12"))
            .arg("-B").args(["-m", "backend.main", "--root"]).arg(&root)
            .arg("--logs").arg(&logs).arg("--cache").arg(&cache).arg("--web").arg(resources.join("web"))
            .arg("--parent").arg(std::process::id().to_string())
            .current_dir(&resources)
            .env_clear()
            .env("HOME", &root)
            .env("PATH", "/usr/bin:/bin")
            .env("TMPDIR", root.join("runtime"))
            .env("HF_HOME", cache.join("huggingface"))
            .env("HF_HUB_CACHE", cache.join("huggingface/hub"))
            .env("HF_HUB_OFFLINE", "1")
            .env("HF_HUB_DISABLE_TELEMETRY", "1")
            .env("DO_NOT_TRACK", "1")
            .env("XDG_CACHE_HOME", &cache)
            .env("TORCH_HOME", cache.join("torch"))
            .env("UV_CACHE_DIR", cache.join("uv"))
            .env("PYTHONPYCACHEPREFIX", cache.join("pycache"))
            .env("GGML_BACKEND", "MTL0")
            .stdin(Stdio::null()).stdout(Stdio::piped()).stderr(log)
            .process_group(0).spawn()?);

        let stdout = backend.0.stdout.take().ok_or("Missing backend startup pipe")?;
        let (tx, rx) = std::sync::mpsc::channel();
        std::thread::spawn(move || {
            let mut reader = BufReader::new(stdout);
            let mut line = String::new();
            if reader.read_line(&mut line).is_ok() {
                let _ = tx.send(line);
            }
            let _ = std::io::copy(&mut reader, &mut std::io::sink());
        });
        let line = rx.recv_timeout(Duration::from_secs(20))?;
        let (port, token) = line.trim().split_once(' ').ok_or("Invalid backend startup response")?;
        let port: u16 = port.parse()?;
        let deadline = Instant::now() + Duration::from_secs(10);
        while !healthy(port, token) {
            if Instant::now() >= deadline { return Err("Backend health check timed out".into()); }
            std::thread::sleep(Duration::from_millis(100));
        }
        let url = format!("http://127.0.0.1:{port}/").parse()?;
        WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
            .title("Faster Qwen3-TTS Studio")
            .inner_size(1120.0, 760.0)
            .min_inner_size(750.0, 560.0)
            .on_navigation(move |url| {
                url.scheme() == "http" && url.host_str() == Some("127.0.0.1")
                    && url.port() == Some(port)
            })
            .build()?;
        app.manage(Mutex::new(Some(backend)));
        Ok(())
    }

    pub fn run() {
        let app = tauri::Builder::default()
            .plugin(tauri_plugin_single_instance::init(|app, _, _| {
                if let Some(window) = app.get_webview_window("main") { let _ = window.set_focus(); }
            }))
            .setup(start)
            .build(tauri::generate_context!())
            .unwrap_or_else(|error| {
                eprintln!("Studio startup failed: {error}");
                if std::env::var_os("STUDIO_SMOKE_TEST").is_none() {
                    let _ = Command::new("/usr/bin/osascript").args(["-e",
                        "display alert \"Faster Qwen3-TTS Studio 无法启动\" message \"请检查 ~/Library/Logs/FasterQwen3TTSStudio/backend.log\" as critical"])
                        .status();
                }
                std::process::exit(1);
            });
        app.run(|handle, event| {
            match event {
                RunEvent::Ready if std::env::var_os("STUDIO_SMOKE_TEST").is_some() => {
                    println!("Studio shell and backend healthy");
                    handle.exit(0);
                }
                RunEvent::Exit => {
                    handle.state::<Mutex<Option<Backend>>>().lock().unwrap().take();
                }
                _ => {}
            }
        });
    }
}

fn main() {
    #[cfg(target_os = "macos")]
    desktop::run();
    #[cfg(not(target_os = "macos"))]
    eprintln!("Use the Windows web development mode.");
}
