//! Starts the local Onyx Lite stack and Ollama, then returns the URL to load.
//!
//! The webview still renders the Onyx app. This module only supervises the
//! processes that app needs when the machine is offline.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::Duration;

use serde_json::Value;

pub const DEFAULT_LOCAL_MODEL: &str = "qwen3:8b";
/// Local GLM model pulled beside the chat default. Qwen stays the default.
/// GLM 4.7 Flash is about 19 GB and does not fit a 16 GB machine.
pub const EXTRA_LOCAL_MODELS: &[&str] = &["glm4:latest"];
pub const OLLAMA_API_BASE_FROM_CONTAINER: &str = "http://host.docker.internal:11434";
const OLLAMA_TAGS_URL: &str = "http://127.0.0.1:11434/api/tags";
const OLLAMA_PULL_URL: &str = "http://127.0.0.1:11434/api/pull";
const AIRGAP_KEY: &str = "ONYX_AIRGAPPED";
const TELEMETRY_KEY: &str = "DISABLE_TELEMETRY";
const SEED_BASE_KEY: &str = "ONYX_SEED_OLLAMA_API_BASE";
const SEED_MODEL_KEY: &str = "ONYX_SEED_OLLAMA_MODEL";
const SEED_EXTRA_MODELS_KEY: &str = "ONYX_SEED_OLLAMA_EXTRA_MODELS";
const MCP_KEY: &str = "MCP_SERVER_ENABLED";
const DEFAULT_HOST_PORT: u16 = 3000;
const DOCKER_START_WAIT: Duration = Duration::from_secs(120);
const DOCKER_POLL_INTERVAL: Duration = Duration::from_secs(2);
const DOCKER_INFO_TIMEOUT: Duration = Duration::from_secs(5);
const DOCKER_DESKTOP_INSTALL_PAGE: &str =
    "https://docs.docker.com/desktop/setup/install/windows-install/";
const OLLAMA_DMG_URL: &str = "https://ollama.com/download/Ollama.dmg";
const OLLAMA_LINUX_INSTALL_URL: &str = "https://ollama.com/install.sh";
const OLLAMA_DOWNLOAD_PAGE: &str = "https://ollama.com/download";
const UV_INSTALL_URL: &str = "https://astral.sh/uv/install.sh";
const CONFIGURE_OLLAMA_PY: &str = include_str!("configure_ollama.py");

/// Which machine the desktop is supervising. Tests pass this in. Launch uses
/// [`current_docker_host`].
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum DockerHost {
    Macos,
    Linux,
    Windows,
}

const fn current_docker_host() -> DockerHost {
    if cfg!(target_os = "macos") {
        DockerHost::Macos
    } else if cfg!(target_os = "windows") {
        DockerHost::Windows
    } else {
        DockerHost::Linux
    }
}

/// One process invocation. The program name is looked up on `PATH` unless it
/// is already a path.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct CommandPlan {
    program: &'static str,
    args: &'static [&'static str],
}

const fn daemon_start_command(host: DockerHost) -> CommandPlan {
    match host {
        DockerHost::Macos => CommandPlan {
            program: "open",
            args: &["-a", "Docker"],
        },
        DockerHost::Linux => CommandPlan {
            program: "systemctl",
            args: &["start", "docker"],
        },
        DockerHost::Windows => CommandPlan {
            program: "Docker Desktop.exe",
            args: &[],
        },
    }
}

/// Non-interactive. A password prompt cannot appear in the app window, so
/// sudo fails at once when a password is required.
const fn linux_sudo_daemon_start() -> CommandPlan {
    CommandPlan {
        program: "sudo",
        args: &["-n", "systemctl", "start", "docker"],
    }
}

const fn brew_install_docker() -> CommandPlan {
    CommandPlan {
        program: "brew",
        args: &["install", "--cask", "docker"],
    }
}

const fn brew_install_ollama() -> CommandPlan {
    CommandPlan {
        program: "brew",
        args: &["install", "ollama"],
    }
}

const fn winget_install_ollama() -> CommandPlan {
    CommandPlan {
        program: "winget",
        args: &[
            "install",
            "-e",
            "--id",
            "Ollama.Ollama",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ],
    }
}

const fn winget_install_docker() -> CommandPlan {
    CommandPlan {
        program: "winget",
        args: &[
            "install",
            "-e",
            "--id",
            "Docker.DockerDesktop",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ],
    }
}

fn docker_dmg_url(arch: &str) -> &'static str {
    match arch {
        "aarch64" | "arm64" => "https://desktop.docker.com/mac/main/arm64/Docker.dmg",
        _ => "https://desktop.docker.com/mac/main/amd64/Docker.dmg",
    }
}

fn curl_download_args(url: &str, dest: &Path) -> Vec<String> {
    vec![
        "-fsSL".to_string(),
        "-o".to_string(),
        dest.to_string_lossy().into_owned(),
        url.to_string(),
    ]
}

fn hdiutil_attach_args(dmg: &Path, mount: &Path) -> Vec<String> {
    vec![
        "attach".to_string(),
        dmg.to_string_lossy().into_owned(),
        "-nobrowse".to_string(),
        "-mountpoint".to_string(),
        mount.to_string_lossy().into_owned(),
    ]
}

fn hdiutil_detach_args(mount: &Path) -> Vec<String> {
    vec!["detach".to_string(), mount.to_string_lossy().into_owned()]
}

fn copy_docker_app_script(source: &Path, dest: &Path) -> String {
    format!(
        "do shell script \"ditto '{}' '{}'\" with administrator privileges",
        source.display(),
        dest.display()
    )
}

fn windows_docker_desktop_exe(program_files: &Path) -> PathBuf {
    program_files
        .join("Docker")
        .join("Docker")
        .join("Docker Desktop.exe")
}

pub fn offline_deployment_dir(config_dir: &Path) -> PathBuf {
    config_dir.join("offline")
}

pub fn deployment_env_path(deployment_root: &Path) -> PathBuf {
    deployment_root.join("deployment").join(".env")
}

/// Model names accepted from config. Rejects anything a process argument
/// could misread as a flag or a second token.
pub fn valid_model_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 128
        && name
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '.' | ':' | '-'))
        && !name.starts_with('-')
}

pub fn executable_file_name(name: &str) -> String {
    if cfg!(windows) && !name.to_ascii_lowercase().ends_with(".exe") {
        format!("{name}.exe")
    } else {
        name.to_string()
    }
}

pub fn resolve_executable(name: &str, path_env: &str, extra_dirs: &[PathBuf]) -> Option<PathBuf> {
    let file_name = executable_file_name(name);
    for dir in std::env::split_paths(path_env) {
        let candidate = dir.join(&file_name);
        if candidate.is_file() {
            return Some(candidate);
        }
    }
    for dir in extra_dirs {
        let candidate = dir.join(&file_name);
        if candidate.is_file() {
            return Some(candidate);
        }
    }
    None
}

pub fn default_search_dirs() -> Vec<PathBuf> {
    let mut dirs = vec![
        PathBuf::from("/usr/local/bin"),
        PathBuf::from("/opt/homebrew/bin"),
        PathBuf::from("/usr/bin"),
        PathBuf::from("/Applications/Docker.app/Contents/Resources/bin"),
        PathBuf::from("/Applications/Ollama.app/Contents/Resources"),
        PathBuf::from("/Applications/Ollama.app/Contents/MacOS"),
    ];
    if let Some(home) = directories::UserDirs::new() {
        let home = home.home_dir();
        dirs.push(home.join(".local").join("bin"));
        dirs.push(home.join(".ollama").join("bin"));
    }
    #[cfg(windows)]
    {
        if let Ok(local) = std::env::var("LOCALAPPDATA") {
            let local = PathBuf::from(local);
            dirs.push(local.join("Programs").join("Ollama"));
            dirs.push(local.join("Microsoft").join("WindowsApps"));
        }
        if let Ok(program_files) = std::env::var("ProgramFiles") {
            dirs.push(
                PathBuf::from(program_files)
                    .join("Docker")
                    .join("Docker")
                    .join("resources")
                    .join("bin"),
            );
        }
    }
    dirs
}

pub fn augmented_path(extra_dirs: &[PathBuf], current: &str) -> String {
    let mut parts = extra_dirs.to_vec();
    parts.extend(std::env::split_paths(current));
    std::env::join_paths(parts).map_or_else(
        |_| current.to_string(),
        |joined| joined.to_string_lossy().into_owned(),
    )
}

pub fn env_value(content: &str, key: &str) -> Option<String> {
    let prefix = format!("{key}=");
    for line in content.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with('#') {
            continue;
        }
        if let Some(value) = trimmed.strip_prefix(&prefix) {
            return Some(
                value
                    .trim()
                    .trim_matches('"')
                    .trim_matches('\'')
                    .to_string(),
            );
        }
    }
    None
}

pub fn upsert_env(content: &str, key: &str, value: &str) -> String {
    let prefix = format!("{key}=");
    let assignment = format!("{key}={value}");
    let mut found = false;
    let mut lines = Vec::new();
    for line in content.lines() {
        let trimmed = line.trim_start();
        if !trimmed.starts_with('#') && trimmed.starts_with(&prefix) {
            lines.push(assignment.clone());
            found = true;
        } else {
            lines.push(line.to_string());
        }
    }
    if !found {
        lines.push(assignment);
    }
    let mut out = lines.join("\n");
    out.push('\n');
    out
}

pub fn apply_offline_env(content: &str, model: &str) -> String {
    let with_airgap = upsert_env(content, AIRGAP_KEY, "true");
    let with_telemetry = upsert_env(&with_airgap, TELEMETRY_KEY, "true");
    let with_base = upsert_env(
        &with_telemetry,
        SEED_BASE_KEY,
        OLLAMA_API_BASE_FROM_CONTAINER,
    );
    let with_model = upsert_env(&with_base, SEED_MODEL_KEY, model);
    let with_extras = upsert_env(
        &with_model,
        SEED_EXTRA_MODELS_KEY,
        &extra_models_env_value(),
    );
    // The released nginx files do not include the MCP templates. Leave MCP off
    // so nginx can start.
    upsert_env(&with_extras, MCP_KEY, "false")
}

fn extra_models_env_value() -> String {
    EXTRA_LOCAL_MODELS.join(",")
}

pub fn offline_env_ready(content: &str, model: &str) -> bool {
    env_value(content, AIRGAP_KEY).as_deref() == Some("true")
        && env_value(content, TELEMETRY_KEY).as_deref() == Some("true")
        && env_value(content, SEED_BASE_KEY).as_deref() == Some(OLLAMA_API_BASE_FROM_CONTAINER)
        && env_value(content, SEED_MODEL_KEY).as_deref() == Some(model)
        && env_value(content, SEED_EXTRA_MODELS_KEY).as_deref()
            == Some(extra_models_env_value().as_str())
        && env_value(content, MCP_KEY).as_deref() == Some("false")
}

pub fn host_port_from_env(content: &str) -> u16 {
    env_value(content, "HOST_PORT")
        .and_then(|value| value.parse::<u16>().ok())
        .filter(|port| *port != 0)
        .unwrap_or(DEFAULT_HOST_PORT)
}

pub fn local_server_url(port: u16) -> String {
    format!("http://127.0.0.1:{port}")
}

pub fn deploy_install_args(dir: &Path, offline: bool, force: bool) -> Vec<String> {
    let mut args = vec![
        "deploy".to_string(),
        "install".to_string(),
        "--lite".to_string(),
        "--no-prompt".to_string(),
        "--project".to_string(),
        "onyx-desktop".to_string(),
        "--dir".to_string(),
        dir.to_string_lossy().into_owned(),
    ];
    if offline {
        args.push("--offline".to_string());
    }
    if force {
        args.push("--force".to_string());
    }
    args
}

pub fn model_is_served(tags_body: &str, model: &str) -> bool {
    let Ok(value) = serde_json::from_str::<Value>(tags_body) else {
        return false;
    };
    value
        .get("models")
        .and_then(Value::as_array)
        .is_some_and(|models| {
            models
                .iter()
                .any(|entry| entry.get("name").and_then(Value::as_str) == Some(model))
        })
}

struct Tools {
    /// Missing on Linux until `onyx-cli deploy install` installs Engine.
    docker: Option<PathBuf>,
    ollama: PathBuf,
    onyx_cli: PathBuf,
    path_env: String,
}

fn require_tool(
    name: &str,
    path_env: &str,
    extra_dirs: &[PathBuf],
    missing: &str,
) -> Result<PathBuf, String> {
    resolve_executable(name, path_env, extra_dirs).ok_or_else(|| missing.to_string())
}

fn resolve_tools() -> Result<Tools, String> {
    let path_env = std::env::var("PATH").unwrap_or_default();
    let extra = default_search_dirs();
    let docker = resolve_executable("docker", &path_env, &extra);
    let ollama = require_tool(
        "ollama",
        &path_env,
        &extra,
        "Ollama is not installed. Install it from https://ollama.com and try again.",
    )?;
    let onyx_cli = require_tool(
        "onyx-cli",
        &path_env,
        &extra,
        "onyx-cli is not installed. Install it with `uv tool install onyx-cli` and try again.",
    )?;
    let mut path_dirs = Vec::new();
    if let Some(docker) = &docker {
        if let Some(parent) = docker.parent() {
            path_dirs.push(parent.to_path_buf());
        }
    }
    if let Some(parent) = ollama.parent() {
        path_dirs.push(parent.to_path_buf());
    }
    if let Some(parent) = onyx_cli.parent() {
        path_dirs.push(parent.to_path_buf());
    }
    path_dirs.extend(extra);
    Ok(Tools {
        docker,
        ollama,
        onyx_cli,
        path_env: augmented_path(&path_dirs, &path_env),
    })
}

fn tail(text: &str) -> String {
    const MAX: usize = 600;
    let trimmed = text.trim();
    if trimmed.chars().count() <= MAX {
        return trimmed.to_string();
    }
    let start = trimmed.chars().count() - MAX;
    trimmed.chars().skip(start).collect()
}

fn command_failure(action: &str, output: &str) -> String {
    let detail = tail(output);
    if detail.is_empty() {
        action.to_string()
    } else {
        format!("{action}\n{detail}")
    }
}

fn run_captured(program: &Path, args: &[String], path_env: &str) -> Result<(bool, String), String> {
    let output = Command::new(program)
        .args(args)
        .env("PATH", path_env)
        .output()
        .map_err(|error| format!("Could not run {}: {error}", program.display()))?;
    let mut combined = String::from_utf8_lossy(&output.stdout).into_owned();
    let stderr = String::from_utf8_lossy(&output.stderr);
    if !stderr.is_empty() {
        if !combined.is_empty() {
            combined.push('\n');
        }
        combined.push_str(&stderr);
    }
    Ok((output.status.success(), combined))
}

fn run_captured_stdin(
    program: &Path,
    args: &[String],
    path_env: &str,
    stdin_text: &str,
) -> Result<(bool, String), String> {
    use std::io::Write;
    let mut child = Command::new(program)
        .args(args)
        .env("PATH", path_env)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| format!("Could not run {}: {error}", program.display()))?;
    if let Some(mut stdin) = child.stdin.take() {
        stdin
            .write_all(stdin_text.as_bytes())
            .map_err(|error| format!("Could not write to {}: {error}", program.display()))?;
    }
    let output = child
        .wait_with_output()
        .map_err(|error| format!("Could not run {}: {error}", program.display()))?;
    let mut combined = String::from_utf8_lossy(&output.stdout).into_owned();
    let stderr = String::from_utf8_lossy(&output.stderr);
    if !stderr.is_empty() {
        if !combined.is_empty() {
            combined.push('\n');
        }
        combined.push_str(&stderr);
    }
    Ok((output.status.success(), combined))
}

fn spawn_ollama(program: &Path, path_env: &str) -> Result<(), String> {
    let mut command = Command::new(program);
    command
        .arg("serve")
        .env("OLLAMA_HOST", "0.0.0.0:11434")
        .env("PATH", path_env)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const DETACHED_PROCESS: u32 = 0x0000_0008;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(DETACHED_PROCESS | CREATE_NO_WINDOW);
    }
    command
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("Could not start Ollama: {error}"))
}

async fn http_text(url: &str, timeout: Duration) -> Result<String, String> {
    let client = reqwest::Client::builder()
        .timeout(timeout)
        .build()
        .map_err(|error| format!("Failed to build HTTP client: {error}"))?;
    let response = client
        .get(url)
        .send()
        .await
        .map_err(|error| error.to_string())?;
    if !response.status().is_success() {
        return Err(format!("{url} returned {}", response.status()));
    }
    response
        .text()
        .await
        .map_err(|error| format!("Failed to read {url}: {error}"))
}

async fn ollama_tags() -> Result<String, String> {
    http_text(OLLAMA_TAGS_URL, Duration::from_secs(3)).await
}

fn run_plan(plan: &CommandPlan, path_env: &str) -> Result<(bool, String), String> {
    let args = plan
        .args
        .iter()
        .map(|arg| (*arg).to_string())
        .collect::<Vec<_>>();
    run_captured(Path::new(plan.program), &args, path_env)
}

fn run_captured_timeout(
    program: &Path,
    args: &[String],
    path_env: &str,
    timeout: Duration,
) -> Result<(bool, String), String> {
    use std::io::Read;
    let mut child = Command::new(program)
        .args(args)
        .env("PATH", path_env)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| format!("Could not run {}: {error}", program.display()))?;
    let started = std::time::Instant::now();
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if started.elapsed() > timeout => {
                let _ = child.kill();
                let _ = child.wait();
                return Ok((false, "timed out".to_string()));
            }
            Ok(None) => std::thread::sleep(Duration::from_millis(200)),
            Err(error) => return Err(format!("Could not check {}: {error}", program.display())),
        }
    };
    let mut combined = String::new();
    if let Some(mut stdout) = child.stdout.take() {
        let _ = stdout.read_to_string(&mut combined);
    }
    if let Some(mut stderr) = child.stderr.take() {
        let mut err = String::new();
        let _ = stderr.read_to_string(&mut err);
        if !err.is_empty() {
            if !combined.is_empty() {
                combined.push('\n');
            }
            combined.push_str(&err);
        }
    }
    Ok((status.success(), combined))
}

fn spawn_detached(program: &Path, args: &[String], path_env: &str) -> Result<(), String> {
    let mut command = Command::new(program);
    command
        .args(args)
        .env("PATH", path_env)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const DETACHED_PROCESS: u32 = 0x0000_0008;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(DETACHED_PROCESS | CREATE_NO_WINDOW);
    }
    command
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("Could not start {}: {error}", program.display()))
}

fn refresh_docker(tools: &mut Tools) {
    let path_env = std::env::var("PATH").unwrap_or_else(|_| tools.path_env.clone());
    tools.docker = resolve_executable("docker", &path_env, &default_search_dirs());
}

fn docker_app_present() -> bool {
    match current_docker_host() {
        DockerHost::Macos => Path::new("/Applications/Docker.app").is_dir(),
        DockerHost::Windows => {
            let program_files =
                std::env::var("ProgramFiles").unwrap_or_else(|_| r"C:\Program Files".to_string());
            windows_docker_desktop_exe(Path::new(&program_files)).is_file()
        }
        DockerHost::Linux => false,
    }
}

async fn docker_info_succeeds(docker: &Path, path_env: &str) -> Result<bool, String> {
    let docker = docker.to_path_buf();
    let path_env = path_env.to_string();
    let (ok, _) = tokio::task::spawn_blocking(move || {
        run_captured_timeout(
            &docker,
            &["info".to_string()],
            &path_env,
            DOCKER_INFO_TIMEOUT,
        )
    })
    .await
    .map_err(|error| format!("Docker check failed: {error}"))??;
    Ok(ok)
}

async fn run_plan_async(plan: CommandPlan, path_env: &str) -> Result<(bool, String), String> {
    let path_env = path_env.to_string();
    tokio::task::spawn_blocking(move || run_plan(&plan, &path_env))
        .await
        .map_err(|error| format!("Could not run {}: {error}", plan.program))?
}

fn docker_not_installed_message() -> String {
    "Docker is not installed. Install Docker Desktop, then try again.".to_string()
}

async fn install_missing_docker(path_env: &str, on_progress: &impl Fn(&str)) -> Result<(), String> {
    match current_docker_host() {
        DockerHost::Linux => Ok(()),
        DockerHost::Macos => install_docker_macos(path_env, on_progress).await,
        DockerHost::Windows => install_docker_windows(path_env).await,
    }
}

async fn install_docker_macos(path_env: &str, on_progress: &impl Fn(&str)) -> Result<(), String> {
    let extra = default_search_dirs();
    if let Some(brew) = resolve_executable("brew", path_env, &extra) {
        on_progress("Installing Docker with Homebrew.");
        let plan = brew_install_docker();
        let args = plan
            .args
            .iter()
            .map(|arg| (*arg).to_string())
            .collect::<Vec<_>>();
        let path_env = path_env.to_string();
        let (ok, output) =
            tokio::task::spawn_blocking(move || run_captured(&brew, &args, &path_env))
                .await
                .map_err(|error| format!("Could not install Docker: {error}"))??;
        if ok {
            return Ok(());
        }
        return Err(command_failure(
            "Could not install Docker with Homebrew.",
            &output,
        ));
    }
    on_progress("Downloading Docker Desktop.");
    install_docker_dmg(path_env).await
}

async fn install_docker_dmg(path_env: &str) -> Result<(), String> {
    let root = std::env::temp_dir().join(format!("onyx-docker-{}", std::process::id()));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(&root)
        .map_err(|error| format!("Could not create a temp directory: {error}"))?;
    let dmg = root.join("Docker.dmg");
    let mount = root.join("mount");
    fs::create_dir_all(&mount)
        .map_err(|error| format!("Could not create a mount directory: {error}"))?;
    let url = docker_dmg_url(std::env::consts::ARCH);
    let curl_args = curl_download_args(url, &dmg);
    let path_for_curl = path_env.to_string();
    let (ok, output) = tokio::task::spawn_blocking(move || {
        run_captured(Path::new("curl"), &curl_args, &path_for_curl)
    })
    .await
    .map_err(|error| format!("Could not download Docker: {error}"))??;
    if !ok {
        let _ = fs::remove_dir_all(&root);
        return Err(command_failure(
            "Could not download Docker Desktop.",
            &output,
        ));
    }
    let attach_args = hdiutil_attach_args(&dmg, &mount);
    let path_for_attach = path_env.to_string();
    let (ok, output) = tokio::task::spawn_blocking(move || {
        run_captured(Path::new("hdiutil"), &attach_args, &path_for_attach)
    })
    .await
    .map_err(|error| format!("Could not open the Docker installer: {error}"))??;
    if !ok {
        let _ = fs::remove_dir_all(&root);
        return Err(command_failure(
            "Could not open the Docker installer.",
            &output,
        ));
    }
    let script = copy_docker_app_script(
        &mount.join("Docker.app"),
        Path::new("/Applications/Docker.app"),
    );
    let path_for_copy = path_env.to_string();
    let copy_result = tokio::task::spawn_blocking(move || {
        run_captured(
            Path::new("osascript"),
            &["-e".to_string(), script],
            &path_for_copy,
        )
    })
    .await;
    let detach_args = hdiutil_detach_args(&mount);
    let path_for_detach = path_env.to_string();
    let _ = tokio::task::spawn_blocking(move || {
        run_captured(Path::new("hdiutil"), &detach_args, &path_for_detach)
    })
    .await;
    let _ = fs::remove_dir_all(&root);
    let (ok, output) = copy_result.map_err(|error| format!("Could not copy Docker: {error}"))??;
    if ok {
        Ok(())
    } else {
        Err(command_failure(
            "Could not install Docker Desktop. An admin password is required.",
            &output,
        ))
    }
}

async fn install_docker_windows(path_env: &str) -> Result<(), String> {
    let extra = default_search_dirs();
    let Some(winget) = resolve_executable("winget", path_env, &extra) else {
        let opened = crate::window::open_in_default_browser(DOCKER_DESKTOP_INSTALL_PAGE);
        if opened {
            return Err(
                "Docker Desktop is not installed. The install page was opened. \
                 Install it, then try again."
                    .to_string(),
            );
        }
        return Err(docker_not_installed_message());
    };
    let plan = winget_install_docker();
    let args = plan
        .args
        .iter()
        .map(|arg| (*arg).to_string())
        .collect::<Vec<_>>();
    let path_env = path_env.to_string();
    let (ok, output) = tokio::task::spawn_blocking(move || run_captured(&winget, &args, &path_env))
        .await
        .map_err(|error| format!("Could not install Docker: {error}"))??;
    if ok {
        Ok(())
    } else {
        Err(command_failure(
            "Could not install Docker Desktop.",
            &output,
        ))
    }
}

fn tool_present(name: &str, path_env: &str) -> bool {
    resolve_executable(name, path_env, &default_search_dirs()).is_some()
}

fn search_path() -> String {
    augmented_path(
        &default_search_dirs(),
        &std::env::var("PATH").unwrap_or_default(),
    )
}

async fn run_resolved(
    program: PathBuf,
    args: Vec<String>,
    path_env: String,
) -> Result<(bool, String), String> {
    let display = program.display().to_string();
    tokio::task::spawn_blocking(move || run_captured(&program, &args, &path_env))
        .await
        .map_err(|error| format!("Could not run {display}: {error}"))?
}

async fn install_with_brew(
    formula_args: &'static [&'static str],
    path_env: &str,
    failure: &str,
) -> Result<bool, String> {
    let Some(brew) = resolve_executable("brew", path_env, &default_search_dirs()) else {
        return Ok(false);
    };
    let args = formula_args.iter().map(|arg| (*arg).to_string()).collect();
    let (ok, output) = run_resolved(brew, args, path_env.to_string()).await?;
    if ok {
        Ok(true)
    } else {
        Err(command_failure(failure, &output))
    }
}

async fn download_file(url: &str, dest: &Path, path_env: &str) -> Result<(), String> {
    let args = curl_download_args(url, dest);
    let path_env = path_env.to_string();
    let (ok, output) = run_resolved(PathBuf::from("curl"), args, path_env).await?;
    if ok {
        Ok(())
    } else {
        Err(command_failure(
            "Could not download the installer.",
            &output,
        ))
    }
}

async fn install_ollama_dmg(path_env: &str) -> Result<(), String> {
    let root = std::env::temp_dir().join(format!("onyx-ollama-{}", std::process::id()));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(&root)
        .map_err(|error| format!("Could not create a temp directory: {error}"))?;
    let dmg = root.join("Ollama.dmg");
    let mount = root.join("mount");
    fs::create_dir_all(&mount)
        .map_err(|error| format!("Could not create a mount directory: {error}"))?;
    if let Err(error) = download_file(OLLAMA_DMG_URL, &dmg, path_env).await {
        let _ = fs::remove_dir_all(&root);
        return Err(error);
    }
    let attach_args = hdiutil_attach_args(&dmg, &mount);
    let (ok, output) =
        run_resolved(PathBuf::from("hdiutil"), attach_args, path_env.to_string()).await?;
    if !ok {
        let _ = fs::remove_dir_all(&root);
        return Err(command_failure(
            "Could not open the Ollama installer.",
            &output,
        ));
    }
    let script = copy_docker_app_script(
        &mount.join("Ollama.app"),
        Path::new("/Applications/Ollama.app"),
    );
    let copy_result = run_resolved(
        PathBuf::from("osascript"),
        vec!["-e".to_string(), script],
        path_env.to_string(),
    )
    .await;
    let detach_args = hdiutil_detach_args(&mount);
    let _ = run_resolved(PathBuf::from("hdiutil"), detach_args, path_env.to_string()).await;
    let _ = fs::remove_dir_all(&root);
    let (ok, output) = copy_result?;
    if ok {
        Ok(())
    } else {
        Err(command_failure(
            "Could not install Ollama. An admin password is required.",
            &output,
        ))
    }
}

async fn install_ollama(path_env: &str, on_progress: &impl Fn(&str)) -> Result<(), String> {
    match current_docker_host() {
        DockerHost::Macos | DockerHost::Linux => {
            if tool_present("brew", path_env) {
                on_progress("Installing Ollama with Homebrew.");
                let installed = install_with_brew(
                    brew_install_ollama().args,
                    path_env,
                    "Could not install Ollama with Homebrew.",
                )
                .await?;
                if installed {
                    return Ok(());
                }
            }
            if current_docker_host() == DockerHost::Linux {
                on_progress("Installing Ollama.");
                let root = std::env::temp_dir().join(format!("onyx-ollama-{}", std::process::id()));
                let _ = fs::remove_dir_all(&root);
                fs::create_dir_all(&root)
                    .map_err(|error| format!("Could not create a temp directory: {error}"))?;
                let script = root.join("install.sh");
                download_file(OLLAMA_LINUX_INSTALL_URL, &script, path_env).await?;
                let (ok, output) = run_resolved(
                    PathBuf::from("sh"),
                    vec![script.to_string_lossy().into_owned()],
                    path_env.to_string(),
                )
                .await?;
                let _ = fs::remove_dir_all(&root);
                if ok {
                    Ok(())
                } else {
                    Err(command_failure("Could not install Ollama.", &output))
                }
            } else {
                on_progress("Downloading Ollama.");
                install_ollama_dmg(path_env).await
            }
        }
        DockerHost::Windows => {
            let Some(winget) = resolve_executable("winget", path_env, &default_search_dirs())
            else {
                let _ = crate::window::open_in_default_browser(OLLAMA_DOWNLOAD_PAGE);
                return Err(
                    "Ollama is not installed. The install page was opened. Install it, then try again."
                        .to_string(),
                );
            };
            on_progress("Installing Ollama.");
            let args = winget_install_ollama()
                .args
                .iter()
                .map(|arg| (*arg).to_string())
                .collect();
            let (ok, output) = run_resolved(winget, args, path_env.to_string()).await?;
            if ok {
                Ok(())
            } else {
                Err(command_failure("Could not install Ollama.", &output))
            }
        }
    }
}

async fn install_uv(path_env: &str) -> Result<(), String> {
    if current_docker_host() == DockerHost::Windows {
        let (ok, output) = run_resolved(
            PathBuf::from("powershell"),
            vec![
                "-NoProfile".to_string(),
                "-ExecutionPolicy".to_string(),
                "Bypass".to_string(),
                "-Command".to_string(),
                "irm https://astral.sh/uv/install.ps1 | iex".to_string(),
            ],
            path_env.to_string(),
        )
        .await?;
        return if ok {
            Ok(())
        } else {
            Err(command_failure("Could not install uv.", &output))
        };
    }
    let root = std::env::temp_dir().join(format!("onyx-uv-{}", std::process::id()));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(&root)
        .map_err(|error| format!("Could not create a temp directory: {error}"))?;
    let script = root.join("install.sh");
    download_file(UV_INSTALL_URL, &script, path_env).await?;
    let (ok, output) = run_resolved(
        PathBuf::from("sh"),
        vec![script.to_string_lossy().into_owned()],
        path_env.to_string(),
    )
    .await?;
    let _ = fs::remove_dir_all(&root);
    if ok {
        Ok(())
    } else {
        Err(command_failure("Could not install uv.", &output))
    }
}

async fn install_onyx_cli(path_env: &str, on_progress: &impl Fn(&str)) -> Result<(), String> {
    if !tool_present("uv", path_env) {
        on_progress("Installing uv.");
        install_uv(path_env).await?;
    }
    let Some(uv) = resolve_executable("uv", path_env, &default_search_dirs()) else {
        return Err("uv was installed but the app could not find it. Try again.".to_string());
    };
    on_progress("Installing the Onyx CLI.");
    let (ok, output) = run_resolved(
        uv,
        vec![
            "tool".to_string(),
            "install".to_string(),
            "onyx-cli".to_string(),
        ],
        path_env.to_string(),
    )
    .await?;
    if ok {
        Ok(())
    } else {
        Err(command_failure("Could not install onyx-cli.", &output))
    }
}

async fn ensure_host_tools(on_progress: &impl Fn(&str)) -> Result<(), String> {
    let path_env = search_path();
    if !tool_present("ollama", &path_env) {
        on_progress("Installing Ollama. This can take a few minutes.");
        install_ollama(&path_env, on_progress).await?;
        if !tool_present("ollama", &search_path()) {
            return Err(
                "Ollama was installed but the app could not find it. Try again.".to_string(),
            );
        }
    }
    if !tool_present("onyx-cli", &path_env) {
        install_onyx_cli(&path_env, on_progress).await?;
        if !tool_present("onyx-cli", &search_path()) {
            return Err(
                "onyx-cli was installed but the app could not find it. Try again.".to_string(),
            );
        }
    }
    Ok(())
}

fn api_container_id(docker: &Path, path_env: &str) -> Result<String, String> {
    let (ok, output) = run_captured(
        docker,
        &[
            "ps".to_string(),
            "-q".to_string(),
            "--filter".to_string(),
            "label=com.docker.compose.project=onyx-desktop".to_string(),
            "--filter".to_string(),
            "label=com.docker.compose.service=api_server".to_string(),
        ],
        path_env,
    )?;
    if !ok {
        return Err(command_failure("Could not find the Onyx API.", &output));
    }
    output
        .lines()
        .next()
        .map(str::trim)
        .filter(|id| !id.is_empty())
        .map(str::to_string)
        .ok_or_else(|| "The Onyx API container is not running.".to_string())
}

async fn configure_local_models(tools: &Tools, on_progress: &impl Fn(&str)) -> Result<(), String> {
    on_progress("Connecting Qwen and GLM.");
    let Some(docker) = tools.docker.clone() else {
        return Err("Docker is not available.".to_string());
    };
    let path_env = tools.path_env.clone();
    let container = tokio::task::spawn_blocking(move || api_container_id(&docker, &path_env))
        .await
        .map_err(|error| format!("Could not find the Onyx API: {error}"))??;
    let docker = tools
        .docker
        .clone()
        .ok_or_else(|| "Docker is not available.".to_string())?;
    let path_env = tools.path_env.clone();
    let (ok, output) = tokio::task::spawn_blocking(move || {
        run_captured_stdin(
            &docker,
            &[
                "exec".to_string(),
                "-i".to_string(),
                container,
                "python".to_string(),
                "-".to_string(),
            ],
            &path_env,
            CONFIGURE_OLLAMA_PY,
        )
    })
    .await
    .map_err(|error| format!("Could not connect the models: {error}"))??;
    if ok {
        Ok(())
    } else {
        Err(command_failure(
            "Onyx started, but Qwen and GLM were not connected.",
            &output,
        ))
    }
}

async fn start_docker_daemon(path_env: &str) -> Result<(), String> {
    match current_docker_host() {
        DockerHost::Macos => {
            let (ok, output) =
                run_plan_async(daemon_start_command(DockerHost::Macos), path_env).await?;
            if ok {
                Ok(())
            } else {
                Err(command_failure("Could not start Docker Desktop.", &output))
            }
        }
        DockerHost::Linux => {
            let first = run_plan_async(daemon_start_command(DockerHost::Linux), path_env).await;
            if matches!(first, Ok((true, _))) {
                return Ok(());
            }
            let first_output = match first {
                Ok((_, output)) => output,
                Err(error) => error,
            };
            let detail = match run_plan_async(linux_sudo_daemon_start(), path_env).await {
                Ok((true, _)) => return Ok(()),
                Ok((false, output)) => format!("{first_output}\n{output}"),
                Err(error) => format!("{first_output}\n{error}"),
            };
            Err(command_failure(
                "Docker is not running. Start Docker, then try again.",
                &detail,
            ))
        }
        DockerHost::Windows => {
            let program_files =
                std::env::var("ProgramFiles").unwrap_or_else(|_| r"C:\Program Files".to_string());
            let exe = windows_docker_desktop_exe(Path::new(&program_files));
            if !exe.is_file() {
                return Err(docker_not_installed_message());
            }
            let path_env = path_env.to_string();
            tokio::task::spawn_blocking(move || spawn_detached(&exe, &[], &path_env))
                .await
                .map_err(|error| format!("Could not start Docker Desktop: {error}"))?
        }
    }
}

async fn poll_docker_ready(path_env: &str) -> Result<PathBuf, String> {
    let deadline = std::time::Instant::now() + DOCKER_START_WAIT;
    loop {
        let lookup_path = std::env::var("PATH").unwrap_or_else(|_| path_env.to_string());
        if let Some(docker) = resolve_executable("docker", &lookup_path, &default_search_dirs()) {
            if docker_info_succeeds(&docker, path_env).await? {
                return Ok(docker);
            }
        }
        if std::time::Instant::now() >= deadline {
            break;
        }
        tokio::time::sleep(DOCKER_POLL_INTERVAL).await;
    }
    Err("Docker did not start. Start Docker, then try again.".to_string())
}

async fn ensure_docker(tools: &mut Tools, on_progress: &impl Fn(&str)) -> Result<(), String> {
    if tools.docker.is_none() && current_docker_host() == DockerHost::Linux {
        // `onyx-cli deploy install` installs Docker Engine and starts it.
        return Ok(());
    }
    if tools.docker.is_none() && !docker_app_present() {
        on_progress("Installing Docker.");
        install_missing_docker(&tools.path_env, on_progress).await?;
        refresh_docker(tools);
    }
    if let Some(docker) = &tools.docker {
        if docker_info_succeeds(docker, &tools.path_env).await? {
            return Ok(());
        }
    }
    on_progress("Starting Docker.");
    start_docker_daemon(&tools.path_env).await?;
    tools.docker = Some(poll_docker_ready(&tools.path_env).await?);
    if let Some(parent) = tools.docker.as_ref().and_then(|docker| docker.parent()) {
        tools.path_env = augmented_path(&[parent.to_path_buf()], &tools.path_env);
    }
    Ok(())
}

async fn ensure_ollama(tools: &Tools) -> Result<(), String> {
    if ollama_tags().await.is_ok() {
        return Ok(());
    }
    let ollama = tools.ollama.clone();
    let path_env = tools.path_env.clone();
    tokio::task::spawn_blocking(move || spawn_ollama(&ollama, &path_env))
        .await
        .map_err(|error| format!("Could not start Ollama: {error}"))??;
    for _ in 0..20 {
        tokio::time::sleep(Duration::from_secs(1)).await;
        if ollama_tags().await.is_ok() {
            return Ok(());
        }
    }
    Err("Ollama did not start on port 11434.".to_string())
}

enum PullLine {
    Status(String),
    Error(String),
}

fn format_bytes(bytes: u64) -> String {
    const KIB: u64 = 1024;
    const MIB: u64 = KIB * 1024;
    const GIB: u64 = MIB * 1024;
    if bytes >= GIB {
        let tenths = bytes / (GIB / 10);
        format!("{}.{} GB", tenths / 10, tenths % 10)
    } else if bytes >= MIB {
        format!("{} MB", bytes / MIB)
    } else {
        format!("{} KB", bytes / KIB)
    }
}

fn format_remaining(elapsed: Duration, completed: u64, total: u64) -> Option<String> {
    if completed == 0 || total <= completed || elapsed.as_secs() < 5 {
        return None;
    }
    let remaining_secs = elapsed.as_secs().saturating_mul(total - completed) / completed;
    if remaining_secs < 45 {
        return Some("Less than a minute left.".to_string());
    }
    let minutes = remaining_secs.saturating_add(30) / 60;
    if minutes == 1 {
        Some("About 1 minute left.".to_string())
    } else {
        Some(format!("About {minutes} minutes left."))
    }
}

/// Turns one Ollama `/api/pull` JSON line into status text. Lines that are
/// not JSON are ignored.
fn interpret_pull_line(model: &str, line: &str, elapsed: Duration) -> Option<PullLine> {
    let value: Value = serde_json::from_str(line.trim()).ok()?;
    if let Some(error) = value.get("error").and_then(Value::as_str) {
        return Some(PullLine::Error(error.to_string()));
    }
    let completed = value.get("completed").and_then(Value::as_u64);
    let total = value.get("total").and_then(Value::as_u64);
    if let (Some(done), Some(total_bytes)) = (completed, total) {
        if total_bytes > 0 {
            let pct = done.saturating_mul(100) / total_bytes;
            let mut message = format!(
                "Downloading {model}. {} of {} ({pct}%).",
                format_bytes(done),
                format_bytes(total_bytes)
            );
            if let Some(left) = format_remaining(elapsed, done, total_bytes) {
                message.push(' ');
                message.push_str(&left);
            }
            return Some(PullLine::Status(message));
        }
    }
    let status = value.get("status").and_then(Value::as_str).unwrap_or("");
    let detail = if status.eq_ignore_ascii_case("success")
        || status.to_ascii_lowercase().contains("verifying")
    {
        "Checking the file."
    } else if status.to_ascii_lowercase().contains("writing") {
        "Saving the model."
    } else {
        "This can take several minutes."
    };
    Some(PullLine::Status(format!("Downloading {model}. {detail}")))
}

async fn pull_model(model: &str, on_progress: &impl Fn(&str)) -> Result<(), String> {
    on_progress(&format!(
        "Downloading {model}. This can take several minutes."
    ));
    let client = reqwest::Client::builder()
        .build()
        .map_err(|error| format!("Failed to build HTTP client: {error}"))?;
    let mut response = client
        .post(OLLAMA_PULL_URL)
        .header("content-type", "application/json")
        .body(format!(r#"{{"name":"{model}","stream":true}}"#))
        .send()
        .await
        .map_err(|error| format!("Could not download {model}: {error}"))?;
    if !response.status().is_success() {
        return Err(format!(
            "Could not download {model}. Ollama returned {}.",
            response.status()
        ));
    }
    let started = std::time::Instant::now();
    let mut pending = String::new();
    let mut last = String::new();
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|error| format!("Could not download {model}: {error}"))?
    {
        pending.push_str(&String::from_utf8_lossy(&chunk));
        while let Some(newline) = pending.find('\n') {
            let line = pending[..newline].trim().to_string();
            pending.drain(..=newline);
            apply_pull_line(model, &line, started.elapsed(), &mut last, on_progress)?;
        }
    }
    apply_pull_line(
        model,
        pending.trim(),
        started.elapsed(),
        &mut last,
        on_progress,
    )?;
    Ok(())
}

fn apply_pull_line(
    model: &str,
    line: &str,
    elapsed: Duration,
    last: &mut String,
    on_progress: &impl Fn(&str),
) -> Result<(), String> {
    if line.is_empty() {
        return Ok(());
    }
    match interpret_pull_line(model, line, elapsed) {
        Some(PullLine::Error(error)) => Err(format!("Could not download {model}. {error}")),
        Some(PullLine::Status(message)) => {
            if message != *last {
                on_progress(&message);
                *last = message;
            }
            Ok(())
        }
        None => Ok(()),
    }
}

async fn ensure_model(
    _tools: &Tools,
    model: &str,
    on_progress: &impl Fn(&str),
) -> Result<(), String> {
    if let Ok(body) = ollama_tags().await {
        if model_is_served(&body, model) {
            return Ok(());
        }
    }
    pull_model(model, on_progress).await?;
    match ollama_tags().await {
        Ok(body) if model_is_served(&body, model) => Ok(()),
        _ => Err(format!(
            "{model} is not available in Ollama after the download."
        )),
    }
}

fn read_env_file(path: &Path) -> Result<String, String> {
    fs::read_to_string(path).map_err(|error| format!("Could not read {}: {error}", path.display()))
}

fn write_env_file(path: &Path, content: &str) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("Could not create {}: {error}", parent.display()))?;
    }
    fs::write(path, content)
        .map_err(|error| format!("Could not write {}: {error}", path.display()))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = fs::set_permissions(path, fs::Permissions::from_mode(0o600));
    }
    Ok(())
}

async fn install_stack(
    tools: &Tools,
    deployment_root: &Path,
    offline: bool,
    force: bool,
) -> Result<(), String> {
    let args = deploy_install_args(deployment_root, offline, force);
    let (ok, output) = tokio::task::spawn_blocking({
        let cli = tools.onyx_cli.clone();
        let path_env = tools.path_env.clone();
        move || run_captured(&cli, &args, &path_env)
    })
    .await
    .map_err(|error| format!("Could not start Onyx: {error}"))??;
    if ok {
        Ok(())
    } else {
        Err(command_failure(
            "Onyx did not start. Check Docker and try again.",
            &output,
        ))
    }
}

fn install_needs_download(output: &str) -> bool {
    output.contains("image(s) missing") || output.contains("without --offline")
}

async fn install_or_download(
    tools: &Tools,
    deployment_root: &Path,
    offline: bool,
    force: bool,
    on_progress: &impl Fn(&str),
) -> Result<(), String> {
    match install_stack(tools, deployment_root, offline, force).await {
        Ok(()) => Ok(()),
        Err(error) if offline && install_needs_download(&error) => {
            on_progress("Downloading Onyx images. This can take about 10 minutes.");
            install_stack(tools, deployment_root, false, force).await
        }
        Err(error) => Err(error),
    }
}

async fn version_is_up(base_url: &str) -> bool {
    let url = format!("{}/api/version", base_url.trim_end_matches('/'));
    http_text(&url, Duration::from_secs(5)).await.is_ok()
}

async fn ensure_deployment(
    tools: &Tools,
    deployment_root: &Path,
    model: &str,
    on_progress: &impl Fn(&str),
) -> Result<String, String> {
    let env_path = deployment_env_path(deployment_root);
    if !env_path.is_file() {
        on_progress("Downloading Onyx images. This can take about 10 minutes.");
        install_stack(tools, deployment_root, false, false).await?;
    }
    if !env_path.is_file() {
        return Err("Onyx install finished without a deployment env file. Try again.".to_string());
    }
    let current = read_env_file(&env_path)?;
    let mut patched = false;
    if !offline_env_ready(&current, model) {
        on_progress("Applying offline settings.");
        write_env_file(&env_path, &apply_offline_env(&current, model))?;
        patched = true;
    }
    let env_after = read_env_file(&env_path)?;
    let url = local_server_url(host_port_from_env(&env_after));
    if patched {
        on_progress("Restarting Onyx with offline settings.");
        install_or_download(tools, deployment_root, true, true, on_progress).await?;
    } else if !version_is_up(&url).await {
        on_progress("Starting Onyx.");
        install_or_download(tools, deployment_root, true, false, on_progress).await?;
    }
    Ok(url)
}

async fn wait_until_healthy(base_url: &str) -> Result<(), String> {
    for _ in 0..90 {
        if version_is_up(base_url).await {
            return Ok(());
        }
        tokio::time::sleep(Duration::from_secs(2)).await;
    }
    Err(format!("Onyx did not become ready at {base_url}."))
}

/// Pull the model if needed, start Onyx Lite, and return the local URL.
///
/// Later launches skip the download when the images, the model, and a healthy
/// server are already on this machine.
pub async fn run_offline_stack(
    deployment_root: &Path,
    model: &str,
    on_progress: impl Fn(&str) + Send + Sync,
) -> Result<String, String> {
    if !valid_model_name(model) {
        return Err(
            "The local model name is not valid. Use letters, numbers, and . _ : -.".to_string(),
        );
    }
    on_progress("Checking Docker and Ollama.");
    ensure_host_tools(&on_progress).await?;
    let mut tools = resolve_tools()?;
    ensure_docker(&mut tools, &on_progress).await?;
    on_progress("Starting Ollama.");
    ensure_ollama(&tools).await?;
    ensure_model(&tools, model, &on_progress).await?;
    for extra in EXTRA_LOCAL_MODELS {
        if *extra == model || !valid_model_name(extra) {
            continue;
        }
        ensure_model(&tools, extra, &on_progress).await?;
    }
    let url = ensure_deployment(&tools, deployment_root, model, &on_progress).await?;
    on_progress("Waiting for Onyx.");
    wait_until_healthy(&url).await?;
    configure_local_models(&tools, &on_progress).await?;
    Ok(url)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn env_round_trip_sets_offline_keys_only() {
        let patched = apply_offline_env("IMAGE_TAG=v1\nHOST_PORT=3000\n", "qwen3:8b");
        assert!(offline_env_ready(&patched, "qwen3:8b"));
        assert_eq!(env_value(&patched, "HOST_PORT").as_deref(), Some("3000"));
        assert!(!patched.contains("NEXT_PUBLIC_GTM"));
        assert!(!patched.contains("WEB_SEARCH"));
        assert_eq!(host_port_from_env(&patched), 3000);
        assert_eq!(local_server_url(3000), "http://127.0.0.1:3000");
    }

    #[test]
    fn upsert_replaces_an_existing_assignment() {
        let patched = upsert_env("ONYX_AIRGAPPED=false\n", AIRGAP_KEY, "true");
        assert_eq!(env_value(&patched, AIRGAP_KEY).as_deref(), Some("true"));
        assert_eq!(patched.matches("ONYX_AIRGAPPED=").count(), 1);
    }

    #[test]
    fn install_args_add_offline_and_force() {
        let dir = Path::new("onyx-offline");
        let args = deploy_install_args(dir, true, true);
        assert_eq!(
            args,
            vec![
                "deploy",
                "install",
                "--lite",
                "--no-prompt",
                "--project",
                "onyx-desktop",
                "--dir",
                "onyx-offline",
                "--offline",
                "--force",
            ]
        );
    }

    #[test]
    fn tags_body_detects_the_chosen_model() {
        let body = r#"{"models":[{"name":"qwen3:8b"},{"name":"llama3.1:8b"}]}"#;
        assert!(model_is_served(body, "qwen3:8b"));
        assert!(!model_is_served(body, "missing:latest"));
        assert!(!model_is_served("not json", "qwen3:8b"));
    }

    #[test]
    fn model_names_reject_flags() {
        assert!(valid_model_name("qwen3:8b"));
        assert!(!valid_model_name("-v"));
        assert!(!valid_model_name("qwen 3"));
        assert!(!valid_model_name(""));
    }

    #[test]
    #[allow(clippy::unwrap_used)]
    fn resolve_executable_checks_path_then_extra_dirs() {
        let root = std::env::temp_dir().join(format!("onyx-offline-bin-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        let path_dir = root.join("path");
        let extra_dir = root.join("extra");
        fs::create_dir_all(&path_dir).unwrap();
        fs::create_dir_all(&extra_dir).unwrap();
        let path_bin = path_dir.join(executable_file_name("onyx-cli"));
        let extra_bin = extra_dir.join(executable_file_name("ollama"));
        fs::write(&path_bin, b"").unwrap();
        fs::write(&extra_bin, b"").unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = fs::set_permissions(&path_bin, fs::Permissions::from_mode(0o755));
            let _ = fs::set_permissions(&extra_bin, fs::Permissions::from_mode(0o755));
        }

        let path_env = path_dir.to_string_lossy().into_owned();
        assert_eq!(
            resolve_executable("onyx-cli", &path_env, &[extra_dir.clone()]).as_deref(),
            Some(path_bin.as_path())
        );
        assert_eq!(
            resolve_executable("ollama", &path_env, &[extra_dir]).as_deref(),
            Some(extra_bin.as_path())
        );
        assert!(resolve_executable("docker", &path_env, &[]).is_none());
        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn missing_port_falls_back_to_3000() {
        assert_eq!(host_port_from_env("IMAGE_TAG=v1\n"), 3000);
        assert_eq!(host_port_from_env("HOST_PORT=0\n"), 3000);
        assert_eq!(host_port_from_env("HOST_PORT=\"8080\"\n"), 8080);
    }

    #[test]
    fn daemon_start_commands_match_each_os() {
        assert_eq!(daemon_start_command(DockerHost::Macos).program, "open");
        assert_eq!(
            daemon_start_command(DockerHost::Macos).args,
            &["-a", "Docker"]
        );
        assert_eq!(daemon_start_command(DockerHost::Linux).program, "systemctl");
        assert_eq!(
            daemon_start_command(DockerHost::Linux).args,
            &["start", "docker"]
        );
        assert_eq!(
            linux_sudo_daemon_start().args,
            &["-n", "systemctl", "start", "docker"]
        );
        assert_eq!(
            daemon_start_command(DockerHost::Windows).program,
            "Docker Desktop.exe"
        );
        assert!(daemon_start_command(DockerHost::Windows).args.is_empty());
    }

    #[test]
    fn install_commands_match_each_os() {
        assert_eq!(brew_install_docker().args, &["install", "--cask", "docker"]);
        assert_eq!(brew_install_ollama().args, &["install", "ollama"]);
        assert_eq!(winget_install_ollama().args[3], "Ollama.Ollama");
        assert!(CONFIGURE_OLLAMA_PY.contains("ONYX_SEED_OLLAMA_MODEL"));
        assert!(CONFIGURE_OLLAMA_PY.contains("supports_chat"));
        assert_eq!(
            winget_install_docker().args,
            &[
                "install",
                "-e",
                "--id",
                "Docker.DockerDesktop",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ]
        );
        assert!(docker_dmg_url("aarch64").contains("/arm64/"));
        assert!(docker_dmg_url("x86_64").contains("/amd64/"));
        let dmg = Path::new("/tmp/Docker.dmg");
        let mount = Path::new("/tmp/docker-mount");
        assert_eq!(
            curl_download_args(docker_dmg_url("arm64"), dmg),
            vec![
                "-fsSL",
                "-o",
                "/tmp/Docker.dmg",
                "https://desktop.docker.com/mac/main/arm64/Docker.dmg",
            ]
        );
        assert_eq!(
            hdiutil_attach_args(dmg, mount),
            vec![
                "attach",
                "/tmp/Docker.dmg",
                "-nobrowse",
                "-mountpoint",
                "/tmp/docker-mount",
            ]
        );
        assert_eq!(
            hdiutil_detach_args(mount),
            vec!["detach", "/tmp/docker-mount"]
        );
        let script = copy_docker_app_script(
            &mount.join("Docker.app"),
            Path::new("/Applications/Docker.app"),
        );
        assert!(script.contains("ditto"));
        assert!(script.contains("administrator privileges"));
        let program_files = Path::new("Program Files");
        assert_eq!(
            windows_docker_desktop_exe(program_files),
            program_files
                .join("Docker")
                .join("Docker")
                .join("Docker Desktop.exe")
        );
    }

    #[test]
    fn missing_images_need_a_download() {
        let output = "Error: 3 image(s) missing — re-run without --offline to fetch them";
        assert!(install_needs_download(output));
        assert!(!install_needs_download("Docker is not running"));
    }

    #[test]
    fn pull_line_reports_size_and_time_left() {
        let line = r#"{"status":"pulling","total":5242880000,"completed":2621440000}"#;
        let parsed = interpret_pull_line("qwen3:8b", line, Duration::from_secs(60));
        let message = match parsed {
            Some(PullLine::Status(message)) => message,
            _ => String::new(),
        };
        assert!(message.contains("Downloading qwen3:8b."));
        assert!(message.contains("50%"));
        assert!(message.contains("About 1 minute left."));
    }

    #[test]
    fn pull_line_without_sizes_says_several_minutes() {
        let line = r#"{"status":"pulling manifest"}"#;
        let parsed = interpret_pull_line("qwen3:8b", line, Duration::from_secs(1));
        let message = match parsed {
            Some(PullLine::Status(message)) => message,
            _ => String::new(),
        };
        assert!(message.contains("This can take several minutes."));
    }

    #[test]
    fn pull_line_ignores_plain_text_and_surfaces_errors() {
        assert!(interpret_pull_line("qwen3:8b", "not json", Duration::from_secs(1)).is_none());
        let parsed = interpret_pull_line(
            "qwen3:8b",
            r#"{"error":"model not found"}"#,
            Duration::from_secs(1),
        );
        let error = match parsed {
            Some(PullLine::Error(error)) => error,
            _ => String::new(),
        };
        assert_eq!(error, "model not found");
    }
}
