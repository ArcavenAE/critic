//! A throwaway Dolt server on a random localhost port, in a temp dir, under a
//! scratch HOME, and a config that points the binary at it. If `dolt` is not
//! installed the tests fail with a message saying so; they never skip.

#![allow(dead_code)]

use serde_json::Value;
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Output, Stdio};
use std::time::{Duration, Instant};

pub struct Env {
    child: Child,
    pub port: u16,
    pub dir: tempfile::TempDir,
    pub runtime: PathBuf,
    pub config: PathBuf,
}

fn find_dolt() -> PathBuf {
    let path = std::env::var_os("PATH").unwrap_or_default();
    for d in std::env::split_paths(&path) {
        let p = d.join("dolt");
        if p.is_file() {
            return p;
        }
    }
    panic!("dolt is not installed or not on PATH: the store tests need it and do not skip (CI installs a pinned dolt)");
}

impl Env {
    pub fn start() -> Env {
        let dolt = find_dolt();
        let dir = tempfile::tempdir().unwrap();
        let home = dir.path().join("home");
        let data = dir.path().join("data");
        let runtime = dir.path().join("runtime");
        for d in [&home, &data, &runtime] {
            std::fs::create_dir_all(d).unwrap();
        }
        let port = TcpListener::bind("127.0.0.1:0")
            .unwrap()
            .local_addr()
            .unwrap()
            .port();
        for (k, v) in [
            ("user.name", "critic-test"),
            ("user.email", "critic-test@example.invalid"),
        ] {
            let st = Command::new(&dolt)
                .args(["config", "--global", "--add", k, v])
                .env("HOME", &home)
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .status()
                .unwrap();
            assert!(st.success(), "dolt config failed");
        }
        let log = std::fs::File::create(dir.path().join("dolt.log")).unwrap();
        let child = Command::new(&dolt)
            .args([
                "sql-server",
                "-H",
                "127.0.0.1",
                "-P",
                &port.to_string(),
                "--data-dir",
            ])
            .arg(&data)
            .env("HOME", &home)
            .stdout(log.try_clone().unwrap())
            .stderr(log)
            .spawn()
            .expect("start dolt sql-server");
        let config = dir.path().join("config.toml");
        let mut env = Env {
            child,
            port,
            dir,
            runtime,
            config,
        };
        env.write_config("host_classes = [\"probe-host\"]\n", true);
        env.wait_ready();
        let out = env.critic(&["db", "migrate"]);
        assert!(
            out.status.success(),
            "migrate failed: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        env
    }

    /// Write the config. With `with_server` the dolt_url and runtime_root are added to `extra`.
    pub fn write_config(&mut self, extra: &str, with_server: bool) {
        let mut text = String::new();
        if with_server {
            text.push_str(&format!(
                "runtime_root = {:?}\n[dolt_url]\nhost = \"127.0.0.1\"\nport = {}\nuser = \"root\"\n",
                self.runtime.display().to_string(),
                self.port
            ));
            // top-level keys must precede tables
            text = format!("{extra}{text}");
        } else {
            text.push_str(extra);
        }
        std::fs::write(&self.config, text).unwrap();
    }

    fn wait_ready(&self) {
        let start = Instant::now();
        loop {
            let opts = mysql::OptsBuilder::new()
                .ip_or_hostname(Some("127.0.0.1"))
                .tcp_port(self.port)
                .user(Some("root"));
            if mysql::Conn::new(opts).is_ok() {
                return;
            }
            if start.elapsed() > Duration::from_secs(60) {
                let log =
                    std::fs::read_to_string(self.dir.path().join("dolt.log")).unwrap_or_default();
                panic!("dolt did not come up on port {}: {log}", self.port);
            }
            std::thread::sleep(Duration::from_millis(150));
        }
    }

    pub fn critic(&self, args: &[&str]) -> Output {
        Command::new(env!("CARGO_BIN_EXE_critic"))
            .arg("--config")
            .arg(&self.config)
            .args(args)
            .env("CRITIC_RECORDED_BY", "test")
            .output()
            .unwrap()
    }

    pub fn json(&self, args: &[&str]) -> Value {
        let mut a = vec!["--json"];
        a.extend_from_slice(args);
        let out = self.critic(&a);
        assert!(
            out.status.success(),
            "{:?} failed: {}",
            args,
            String::from_utf8_lossy(&out.stderr)
        );
        serde_json::from_slice(&out.stdout).expect("json output")
    }

    /// Write a run file under the temp dir and register it.
    pub fn register(&self, body: &str) -> Output {
        let f = self.dir.path().join(format!(
            "run-{}.yaml",
            std::process::id() as u128 + rand_suffix()
        ));
        std::fs::write(&f, body).unwrap();
        self.critic(&["run", "register", f.to_str().unwrap()])
    }

    pub fn register_ok(&self, body: &str) {
        let out = self.register(body);
        assert!(out.status.success(), "register failed: {}", text(&out));
    }

    pub fn run_ids(&self) -> Vec<String> {
        self.json(&["run", "list"])
            .as_array()
            .unwrap()
            .iter()
            .map(|r| r["id"].as_str().unwrap().to_string())
            .collect()
    }

    pub fn store(&self) -> critic_core::store::DoltStore {
        let cfg = critic_core::config::Config::load(Some(&self.config)).unwrap();
        critic_core::store::DoltStore::connect(&cfg).unwrap()
    }

    pub fn runtime_file(&self, name: &str, content: &str) -> String {
        let p = self.runtime.join(name);
        std::fs::create_dir_all(p.parent().unwrap()).unwrap();
        std::fs::write(&p, content).unwrap();
        p.display().to_string()
    }
}

fn rand_suffix() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos()
}

impl Drop for Env {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

pub fn text(o: &Output) -> String {
    format!(
        "{}{}",
        String::from_utf8_lossy(&o.stdout),
        String::from_utf8_lossy(&o.stderr)
    )
}

pub fn fixture(name: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures")
        .join(name)
}
