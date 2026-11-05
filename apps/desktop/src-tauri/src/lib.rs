//! Theseus for Mac: hosts the Theseus engine so everything it starts runs under ONE app's macOS permissions.
//!
//! The app is the "responsible process" for what it launches: Claude Code's Remote Control server, the cheap change checks, and the
//! morning/nightly/sync runs. You grant Full Disk Access, Calendars, Reminders and Notes to Theseus.app once, and all of them inherit
//! it, which is what Terminal did for command-line runs. The engine (rules, tools, workflows) is unchanged and lives in the workspace
//! (~/Theseus or $THESEUS_HOME). The app only reads and writes config.json to take over hosting.

use serde::Serialize;
use serde_json::Value;
use std::fs::{self, OpenOptions};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};
use tauri::image::Image;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Emitter, Manager, RunEvent, State, WindowEvent};

const PY: &str = "/usr/bin/python3";
const DEFAULT_JOB_MINUTES: u64 = 45;

#[derive(Clone, Serialize, Default)]
struct Status {
    workspace: String,
    claude: String,
    hosting: bool,          // config says the app hosts Remote Control and the schedule
    paused: bool,
    remote: String,         // human-readable state of the Remote Control server
    remote_state: String,   // off | starting | running | waiting | error
    last_check: String,     // last change-check result
    job_running: Option<String>,
    last_job: String,
    last_job_output: String,
    last_answer: String,    // the latest answer to something asked in the window; later syncs don't replace it
    auto_host: bool,        // moves everything into the app by itself once it can
    can_host: bool,         // has the permissions it needs to
    app_version: String,
    engine_version: String, // what's installed in the workspace; empty if it's too old to say
}

struct Remote {
    child: Child,
    _stdin: ChildStdin, // held open: the server quits on "end of input"
    started: Instant,
}

struct Shared {
    ws: PathBuf,
    claude: Option<PathBuf>,
    paused: AtomicBool,
    quitting: AtomicBool,
    remote: Mutex<Option<Remote>>,
    status: Mutex<Status>,
    master: Mutex<()>, // one save of the list at a time
}

type S = Arc<Shared>;

// ---------- helpers ----------

fn home() -> PathBuf {
    PathBuf::from(std::env::var("HOME").unwrap_or_else(|_| "/Users/Shared".into()))
}

/// Finder starts apps without your shell's settings, so the installer leaves the workspace's location here.
fn workspace() -> PathBuf {
    if let Ok(p) = std::env::var("THESEUS_HOME") {
        return PathBuf::from(p);
    }
    fs::read_to_string(home().join("Library/Application Support/Theseus/workspace"))
        .ok()
        .map(|t| PathBuf::from(t.trim()))
        .filter(|p| p.join("config.json").exists())
        .unwrap_or_else(|| home().join("Theseus"))
}

/// Whole or not at all: a crash leaves the old file or the new one.
fn write_atomic(path: &Path, text: &str) -> Result<(), String> {
    let name = path.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default();
    let tmp = path.with_file_name(format!(".{name}.{}.tmp", std::process::id()));
    fs::write(&tmp, text).map_err(|e| e.to_string())?;
    fs::rename(&tmp, path).map_err(|e| {
        let _ = fs::remove_file(&tmp);
        e.to_string()
    })
}

/// /usr/bin/python3 is a stub that pops up a dialog until Apple's developer tools are installed.
fn has_dev_tools() -> bool {
    Command::new("/usr/bin/xcode-select").arg("-p").output().map(|o| o.status.success()).unwrap_or(false)
}

fn engine_version(ws: &Path) -> String {
    fs::read_to_string(ws.join("engine/VERSION")).map(|t| t.trim().to_string()).unwrap_or_default()
}

fn find_claude() -> Option<PathBuf> {
    let h = home();
    [h.join(".local/bin/claude"), PathBuf::from("/opt/homebrew/bin/claude"), PathBuf::from("/usr/local/bin/claude")]
        .into_iter()
        .find(|p| p.exists())
}

fn config(ws: &Path) -> Value {
    fs::read_to_string(ws.join("config.json")).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or(Value::Null)
}

fn hosting(cfg: &Value) -> bool {
    cfg["remote_control"]["host"].as_str() == Some("app") || cfg["scheduler_host"].as_str() == Some("app")
}

fn local_now() -> (String, u32) {
    // (YYYY-MM-DD, minutes since midnight), using the system clock and time zone.
    let out = Command::new("/bin/date").arg("+%F %H %M").output().ok();
    let s = out.map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string()).unwrap_or_default();
    let parts: Vec<&str> = s.split_whitespace().collect();
    if parts.len() == 3 {
        let m = parts[1].parse::<u32>().unwrap_or(0) * 60 + parts[2].parse::<u32>().unwrap_or(0);
        (parts[0].to_string(), m)
    } else {
        (String::new(), 0)
    }
}

fn log(ws: &Path, file: &str, msg: &str) {
    let _ = fs::create_dir_all(ws.join("logs"));
    if let Ok(mut f) = OpenOptions::new().create(true).append(true).open(ws.join("logs").join(file)) {
        use std::io::Write;
        let (d, m) = local_now();
        let _ = writeln!(f, "{} {:02}:{:02} {}", d, m / 60, m % 60, msg);
    }
}

fn path_env() -> String {
    format!("/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:{}/.local/bin", home().display())
}

fn log_tail(p: &Path) -> String {
    let t = fs::read_to_string(p).unwrap_or_default();
    t.chars().rev().take(600).collect::<Vec<_>>().into_iter().rev().collect()
}

fn set<F: FnOnce(&mut Status)>(s: &S, f: F) {
    if let Ok(mut st) = s.status.lock() {
        f(&mut st);
    }
}

// ---------- Remote Control ----------

fn stop_remote(s: &S) {
    if let Ok(mut r) = s.remote.lock() {
        if let Some(mut rem) = r.take() {
            let _ = rem.child.kill();
            let _ = rem.child.wait();
        }
    }
}

fn remote_loop(s: S) {
    let mut wait_until = Instant::now();
    loop {
        if s.quitting.load(Ordering::SeqCst) {
            stop_remote(&s);
            return;
        }
        let cfg = config(&s.ws);
        let wanted = cfg["remote_control"]["host"].as_str() == Some("app")
            && cfg["remote_control"]["enabled"].as_bool() != Some(false)
            && !s.paused.load(Ordering::SeqCst);
        if !wanted {
            stop_remote(&s);
            let why = if s.paused.load(Ordering::SeqCst) { "paused" } else { "not hosted by the app (see Settings → Take over)" };
            set(&s, |st| st.remote = why.into());
            thread::sleep(Duration::from_secs(10));
            continue;
        }
        let Some(claude) = s.claude.clone() else {
            set(&s, |st| st.remote = "Claude Code not found (install it, then reopen Theseus)".into());
            thread::sleep(Duration::from_secs(30));
            continue;
        };
        let name = cfg["remote_control"]["name"].as_str().unwrap_or("Theseus").to_string();
        // Look at the current server without holding the lock across the decisions below.
        let current = {
            let mut g = s.remote.lock().unwrap();
            g.as_mut().map(|rem| (rem.child.try_wait().map(|o| o.map(|c| c.to_string())), rem.started.elapsed()))
        };
        match current {
            None if Instant::now() >= wait_until => {
                let logf = OpenOptions::new().create(true).append(true).open(s.ws.join("logs/remote-control.log"));
                let (out, err) = match logf.and_then(|f| f.try_clone().map(|g| (f, g))) {
                    Ok((f, g)) => (Stdio::from(f), Stdio::from(g)),
                    Err(_) => (Stdio::null(), Stdio::null()),
                };
                // `script` gives the server a terminal; the piped stdin stays open for as long as we hold it.
                let spawned = Command::new("/usr/bin/script")
                    .args(["-q", "/dev/null"])
                    .arg(&claude)
                    .args(["remote-control", "--name", &name])
                    .current_dir(&s.ws)
                    .env("PATH", path_env())
                    .stdin(Stdio::piped())
                    .stdout(out)
                    .stderr(err)
                    .spawn();
                match spawned {
                    Ok(mut c) => {
                        let stdin = c.stdin.take().expect("piped stdin");
                        log(&s.ws, "remote-control.log", &format!("Theseus.app started Remote Control \"{}\"", name));
                        *s.remote.lock().unwrap() = Some(Remote { child: c, _stdin: stdin, started: Instant::now() });
                        set(&s, |st| { st.remote = "Starting…".into(); st.remote_state = "starting".into(); });
                    }
                    Err(e) => {
                        set(&s, |st| { st.remote = format!("Couldn't start: {e}"); st.remote_state = "error".into(); });
                        wait_until = Instant::now() + Duration::from_secs(60);
                    }
                }
            }
            None => {}
            Some((Ok(Some(code)), up)) => {
                let quick = up < Duration::from_secs(20);
                *s.remote.lock().unwrap() = None;
                let backoff = if quick { 60 } else { 5 };
                log(&s.ws, "remote-control.log", &format!("Remote Control exited ({code}); retrying in {backoff}s"));
                let tail = log_tail(&s.ws.join("logs/remote-control.log"));
                set(&s, |st| {
                    if !quick {
                        st.remote = "Restarting…".into();
                        st.remote_state = "starting".into();
                    } else if tail.contains("served by a terminal") {
                        st.remote = "Waiting for the previous server to let go of this folder. This can take a few minutes, and it retries by itself.".into();
                        st.remote_state = "waiting".into();
                    } else if tail.contains("served by the Claude app") {
                        st.remote = "The Claude desktop app is serving this folder too, and only one can. Turn Remote Control off for this folder there, and this retries by itself.".into();
                        st.remote_state = "waiting".into();
                    } else {
                        st.remote = "Couldn't start. It retries by itself; the details are in logs/remote-control.log.".into();
                        st.remote_state = "error".into();
                    }
                });
                wait_until = Instant::now() + Duration::from_secs(backoff);
            }
            Some((Ok(None), up)) if up >= Duration::from_secs(20) => set(&s, |st| { st.remote = "Your Mac is reachable from the Claude app's Code tab.".into(); st.remote_state = "running".into(); }),
            Some((Ok(None), _)) => {}
            Some((Err(e), _)) => set(&s, |st| { st.remote = format!("Unknown: {e}"); st.remote_state = "error".into(); }),
        }
        thread::sleep(Duration::from_secs(5));
    }
}

// ---------- jobs (sync, morning, nightly, status) ----------

/// The same words launchd's jobs use (engine/scheduled/prompts.json), so a run doesn't depend on which host started it.
fn prompt_for(ws: &Path, kind: &str, reason: &str) -> String {
    if kind == "ask" {
        return format!(
            "The user asked this in the Theseus app: \"{reason}\". Answer briefly and follow engine/RULES.md. If it's something to do or remember, add it to the list. Never send anything. This run can't ask follow-up questions, so make the sensible choice and say what you did."
        );
    }
    let prompts: Value = fs::read_to_string(ws.join("engine/scheduled/prompts.json")).ok().and_then(|t| serde_json::from_str(&t).ok()).unwrap_or(Value::Null);
    let base = prompts[kind].as_str().map(str::to_string).unwrap_or_else(|| format!("Run exactly as defined in engine/workflows/{kind}.md."));
    let extra = if reason.is_empty() { String::new() } else { format!(" Reason for this run: {reason}.") };
    format!("{base}{extra} {}", prompts["unattended"].as_str().unwrap_or("This is an unattended run: never wait for input."))
}

/// One run at a time across the app, the schedule and the theseus command. engine/scheduled/run-job.sh honors the same file.
struct JobLock(PathBuf);

impl JobLock {
    fn take(ws: &Path) -> Option<JobLock> {
        let path = ws.join("data/.job.lock");
        for _ in 0..2 {
            match OpenOptions::new().write(true).create_new(true).open(&path) {
                Ok(mut f) => {
                    use std::io::Write;
                    let _ = write!(f, "{}", std::process::id());
                    return Some(JobLock(path));
                }
                Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
                    if !job_lock_is_stale(&path) {
                        return None;
                    }
                    let _ = fs::remove_file(&path);
                }
                Err(_) => return None,
            }
        }
        None
    }
}

impl Drop for JobLock {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

/// Its holder has gone. An empty file is someone mid-way through taking it, unless it's been empty for a while.
fn job_lock_is_stale(path: &Path) -> bool {
    let holder = fs::read_to_string(path).unwrap_or_default();
    let holder = holder.trim();
    if holder.is_empty() {
        return fs::metadata(path).and_then(|m| m.modified()).ok().and_then(|t| t.elapsed().ok()).is_some_and(|age| age > Duration::from_secs(60));
    }
    !Command::new("/bin/kill").args(["-0", holder]).stderr(Stdio::null()).status().map(|c| c.success()).unwrap_or(false)
}

fn run_job(s: &S, kind: &str, reason: &str) -> Result<(), String> {
    let claude = s.claude.clone().ok_or("Claude Code not found")?;
    {
        // Claiming the slot is one step, so two threads can't both start a run.
        let mut st = s.status.lock().unwrap();
        if let Some(j) = &st.job_running {
            return Err(format!("{j} is already running"));
        }
        st.job_running = Some(kind.to_string());
    }
    let Some(job_lock) = JobLock::take(&s.ws) else {
        set(s, |st| st.job_running = None);
        return Err("Theseus is already running a job from the command line. Try again when it's done.".into());
    };
    let (d, m) = local_now();
    let stamp = format!("{}_{:02}{:02}", d, m / 60, m % 60);
    let out_path = s.ws.join(format!("logs/app-{kind}-{stamp}.out"));
    let files = fs::File::create(&out_path).and_then(|o| o.try_clone().map(|e| (o, e)));
    let (out, err) = match files {
        Ok(f) => f,
        Err(e) => {
            set(s, |st| st.job_running = None);
            return Err(e.to_string());
        }
    };
    let s2 = s.clone();
    let kind = kind.to_string();
    let reason = reason.to_string();
    thread::spawn(move || {
        let _job_lock = job_lock; // released however this run ends
        if kind != "ask" {
            let _ = Command::new("/bin/bash").arg("engine/scheduled/before-run.sh").current_dir(&s2.ws).env("THESEUS_HOME", &s2.ws).env("PATH", path_env()).output();
        }
        let limit = config(&s2.ws)["job_time_limit_minutes"].as_u64().unwrap_or(DEFAULT_JOB_MINUTES).max(1);
        let spawned = Command::new(&claude)
            .args(["-p", &prompt_for(&s2.ws, &kind, &reason), "--output-format", "text"])
            .current_dir(&s2.ws)
            .env("PATH", path_env())
            .env("THESEUS_HOME", &s2.ws)
            .stdin(Stdio::null())
            .stdout(out)
            .stderr(err)
            .spawn();
        let mut child = match spawned {
            Ok(c) => c,
            Err(e) => {
                // It never ran, so it mustn't count as having run.
                let _ = fs::remove_file(&out_path);
                log(&s2.ws, "app.log", &format!("couldn't start {kind}: {e}"));
                set(&s2, |st| { st.job_running = None; st.last_job = format!("{kind} couldn't start: {e}"); });
                return;
            }
        };
        let started = Instant::now();
        let outcome = loop {
            match child.try_wait() {
                Ok(Some(status)) => break (status.success(), status.to_string()),
                Ok(None) if s2.quitting.load(Ordering::SeqCst) => {
                    let _ = child.kill();
                    let _ = child.wait();
                    break (false, "stopped: Theseus is quitting".to_string());
                }
                Ok(None) if started.elapsed() > Duration::from_secs(limit * 60) => {
                    // One hung run must not hold up every later one.
                    let _ = child.kill();
                    let _ = child.wait();
                    log(&s2.ws, "app.log", &format!("stopped {kind} after {limit} minutes"));
                    break (false, format!("stopped after {limit} minutes"));
                }
                Ok(None) => thread::sleep(Duration::from_secs(2)),
                Err(e) => break (false, e.to_string()),
            }
        };
        // The changes this run was for count as handled only now that it has finished. If it failed, they wait for the next one.
        if outcome.0 && kind == "sync" {
            let _ = Command::new(PY).args(["engine/tools/changes.py", "--ack"]).current_dir(&s2.ws).env("THESEUS_HOME", &s2.ws).output();
        }
        let text = fs::read_to_string(&out_path).unwrap_or_default();
        let (_, m) = local_now();
        set(&s2, |st| {
            st.job_running = None;
            st.last_job = format!("{kind} at {}:{:02} ({})", m / 60, m % 60, outcome.1);
            st.last_job_output = text.chars().rev().take(4000).collect::<String>().chars().rev().collect();
            if kind == "ask" {
                st.last_answer = st.last_job_output.clone();
            }
        });
    });
    Ok(())
}

/// Enough to run unattended: without these, briefings would come out empty. Notes can't be checked without a dialog, so its first use asks.
fn can_host(s: &S) -> bool {
    if s.claude.is_none() || !has_dev_tools() || !s.ws.join("config.json").exists() || fs::File::open(home().join("Library/Messages/chat.db")).is_err() {
        return false;
    }
    let ek = Command::new(s.ws.join("bin/ek")).arg("status").current_dir(&s.ws).output().ok().and_then(|o| serde_json::from_slice::<Value>(&o.stdout).ok());
    ek.map(|v| v["calendars"].as_str() == Some("ok") && v["reminders"].as_str() == Some("ok")).unwrap_or(false)
}

fn schedule_loop(s: S) {
    let mut last_check = Instant::now() - Duration::from_secs(3600);
    let mut first = true;
    loop {
        if s.quitting.load(Ordering::SeqCst) {
            return;
        }
        if !first {
            thread::sleep(Duration::from_secs(30));
        }
        first = false;

        // Opening the app is all it takes: once it has its permissions, it moves everything in by itself, unless you've handed back.
        let cfg = config(&s.ws);
        let auto = cfg["auto_host"].as_bool() != Some(false);
        let hosted = hosting(&cfg);
        let able = hosted || can_host(&s);
        set(&s, |st| { st.auto_host = auto; st.can_host = able; });
        if !hosted && auto && able {
            match take_over_now(&s) {
                Ok(_) => log(&s.ws, "app.log", "moved everything into the app by itself"),
                Err(e) => log(&s.ws, "app.log", &format!("couldn't move everything into the app: {e}")),
            }
            continue;
        }
        let cfg = config(&s.ws);
        if cfg["scheduler_host"].as_str() != Some("app") || s.paused.load(Ordering::SeqCst) || !has_dev_tools() {
            continue;
        }

        // Morning and nightly runs. The engine decides what's due, including a run missed while the Mac slept, and logs show what already ran.
        // If something else is running, it's still due next time round.
        let due = Command::new(PY).args(["engine/tools/schedule.py", "due"]).current_dir(&s.ws).env("THESEUS_HOME", &s.ws).output().ok()
            .and_then(|o| serde_json::from_slice::<Value>(&o.stdout).ok());
        if let Some(kind) = due.as_ref().and_then(|d| d["due"].as_str()) {
            if run_job(&s, kind, "scheduled").is_ok() {
                log(&s.ws, "app.log", &format!("started {kind} run"));
            }
        }

        // Cheap change checks: Claude only runs when something changed (changes.py decides, with its own cooldown and quiet hours).
        let every = cfg["checks"]["every_minutes"].as_u64().unwrap_or(5).max(1);
        let checks_on = cfg["checks"]["enabled"].as_bool().unwrap_or(false);
        let busy = s.status.lock().unwrap().job_running.is_some();
        if checks_on && !busy && last_check.elapsed() >= Duration::from_secs(every * 60) {
            last_check = Instant::now();
            if let Ok(o) = Command::new(PY).arg("engine/tools/changes.py").current_dir(&s.ws).env("THESEUS_HOME", &s.ws).output() {
                let reason = String::from_utf8_lossy(&o.stdout).trim().to_string();
                let (_, m) = local_now();
                set(&s, |st| st.last_check = format!("{}:{:02} {}", m / 60, m % 60, reason));
                log(&s.ws, "checks.log", &reason);
                if o.status.code() == Some(0) {
                    let _ = run_job(&s, "sync", &reason);
                }
            }
        }
    }
}

// ---------- commands for the window ----------

#[tauri::command]
fn get_status(s: State<'_, S>) -> Status {
    let mut st = s.status.lock().unwrap().clone();
    st.paused = s.paused.load(Ordering::SeqCst);
    st.hosting = hosting(&config(&s.ws));
    st.app_version = env!("CARGO_PKG_VERSION").to_string();
    st.engine_version = engine_version(&s.ws);
    st
}

#[tauri::command]
fn read_today(s: State<'_, S>) -> String {
    fs::read_to_string(s.ws.join("data/today.md")).unwrap_or_default()
}

#[tauri::command]
fn run_now(kind: String, text: Option<String>, s: State<'_, S>) -> Result<(), String> {
    run_job(&s, &kind, text.as_deref().unwrap_or("started from Theseus.app"))
}

// ---------- the master list ----------

fn master_path(ws: &Path) -> PathBuf {
    ws.join("data/master.md")
}

#[tauri::command(async)]
fn read_master(s: State<'_, S>) -> String {
    fs::read_to_string(master_path(&s.ws)).unwrap_or_default()
}

/// Auto-save. `base` is the text this edit started from: if the file changed since (a sync ran), nothing is written and the window
/// replays the edit on the new text. The write is atomic, and an hourly copy goes in data/archive. What the person did goes to the next
/// sync only once it's saved, so the log can't claim something the list doesn't show: it completes things elsewhere and treats moves as
/// their own ranking (RULES §3).
#[tauri::command(async)]
fn write_master(text: String, base: String, events: Vec<Value>, s: State<'_, S>) -> Result<(), String> {
    use std::io::Write;
    let _one_at_a_time = s.master.lock().unwrap();
    let path = master_path(&s.ws);
    let disk = fs::read_to_string(&path).unwrap_or_default();
    if disk != base {
        return Err("conflict".into());
    }
    if disk == text {
        return Ok(());
    }
    let (d, m) = local_now();
    let archive = s.ws.join("data/archive");
    let _ = fs::create_dir_all(&archive);
    let backup = archive.join(format!("master-app-{d}-{:02}.md", m / 60));
    if !backup.exists() {
        let _ = fs::write(&backup, &disk);
    }
    let tmp = s.ws.join("data/.master.md.tmp");
    fs::write(&tmp, &text).map_err(|e| e.to_string())?;
    // Last look, right before the swap. Claude Code's own edits are refused if the file changed since it read it, which covers the other direction.
    if fs::read_to_string(&path).unwrap_or_default() != disk {
        let _ = fs::remove_file(&tmp);
        return Err("conflict".into());
    }
    fs::rename(&tmp, &path).map_err(|e| e.to_string())?;
    if !events.is_empty() {
        let mut f = OpenOptions::new().create(true).append(true).open(s.ws.join("data/app-edits.jsonl")).map_err(|e| e.to_string())?;
        for mut e in events {
            e["time"] = Value::from(format!("{d} {:02}:{:02}", m / 60, m % 60));
            writeln!(f, "{e}").map_err(|e| e.to_string())?;
        }
    }
    Ok(())
}

/// Typing lost to a sync that landed at the same moment: kept in a file, so nothing is lost and nothing overwrites what the sync did.
#[tauri::command(async)]
fn save_conflict(text: String, s: State<'_, S>) -> Result<String, String> {
    let (d, m) = local_now();
    let archive = s.ws.join("data/archive");
    fs::create_dir_all(&archive).map_err(|e| e.to_string())?;
    let name = format!("master-conflict-{d}-{:02}{:02}.md", m / 60, m % 60);
    fs::write(archive.join(&name), text).map_err(|e| e.to_string())?;
    Ok(format!("data/archive/{name}"))
}

/// Update the phone's copy of the list. If the person edited that note, the tool refuses and the next run folds their edits in.
#[tauri::command(async)]
fn publish_master(s: State<'_, S>) -> Result<String, String> {
    let o = Command::new(PY).args(["engine/tools/notes.py", "master-publish"]).current_dir(&s.ws).env("PATH", path_env()).env("THESEUS_HOME", &s.ws).output().map_err(|e| e.to_string())?;
    if o.status.success() {
        return Ok(String::new());
    }
    if o.status.code() == Some(4) {
        return Ok("You edited the list note in Notes. The next sync folds that in, then updates the note.".into());
    }
    Err(String::from_utf8_lossy(&o.stderr).trim().chars().take(200).collect())
}

#[derive(Serialize)]
struct Run {
    file: String,
    kind: String,
    when: String,
    bytes: u64,
}

/// Recent runs from the logs, whichever host ran them.
#[tauri::command(async)]
fn recent_runs(s: State<'_, S>) -> Vec<Run> {
    let mut out = vec![];
    if let Ok(dir) = fs::read_dir(s.ws.join("logs")) {
        for e in dir.flatten() {
            let f = e.file_name().to_string_lossy().to_string();
            let Some(stem) = f.strip_suffix(".out") else { continue };
            let stem = stem.strip_prefix("app-").unwrap_or(stem);
            let Some((kind, when)) = stem.split_once('-') else { continue };
            let bytes = e.metadata().map(|m| m.len()).unwrap_or(0);
            if bytes > 0 {
                out.push(Run { file: f.clone(), kind: kind.to_string(), when: when.replace('_', " "), bytes });
            }
        }
    }
    out.sort_by(|a, b| b.when.cmp(&a.when));
    out.truncate(25);
    out
}

#[tauri::command(async)]
fn read_run(file: String, s: State<'_, S>) -> Result<String, String> {
    if file.contains('/') || !file.ends_with(".out") {
        return Err("Not a run log.".into());
    }
    fs::read_to_string(s.ws.join("logs").join(file)).map_err(|e| e.to_string())
}

/// When the next briefings are due, from the engine's schedule.
#[tauri::command(async)]
fn schedule(s: State<'_, S>) -> Value {
    Command::new(PY).arg("engine/tools/schedule.py").current_dir(&s.ws).output().ok()
        .and_then(|o| serde_json::from_slice(&o.stdout).ok()).unwrap_or(Value::Null)
}

/// Thread notes, read-only: taking them stays on the command line, when the user asks.
#[tauri::command(async)]
fn thread_notes(s: State<'_, S>) -> Vec<Value> {
    let mut out: Vec<Value> = fs::read_dir(s.ws.join("data/thread-notes")).into_iter().flatten().flatten().filter_map(|e| {
        let path = e.path();
        if path.extension()? != "json" || !path.with_extension("md").exists() {
            return None;
        }
        let led: Value = serde_json::from_str(&fs::read_to_string(&path).ok()?).ok()?;
        Some(serde_json::json!({
            "id": path.file_stem()?.to_str()?,
            "label": led["label"],
            "last_updated": led["last_updated"],
            "last_checked": led["last_checked"],
            "seen": led["seen"].as_array().map_or(0, |a| a.len()),
        }))
    }).collect();
    out.sort_by(|a, b| b["last_checked"].as_str().cmp(&a["last_checked"].as_str()));
    out
}

#[tauri::command(async)]
fn read_thread_note(id: String, s: State<'_, S>) -> Result<String, String> {
    if id.is_empty() || !id.chars().all(|c| c.is_ascii_hexdigit()) {
        return Err("Not a thread note.".into());
    }
    fs::read_to_string(s.ws.join("data/thread-notes").join(format!("{id}.md"))).map_err(|e| e.to_string())
}

#[tauri::command(async)]
fn read_commands(s: State<'_, S>) -> String {
    fs::read_to_string(s.ws.join("engine/commands.txt")).unwrap_or_default()
}

#[tauri::command]
fn set_paused(paused: bool, s: State<'_, S>) {
    s.paused.store(paused, Ordering::SeqCst);
}

#[derive(Serialize)]
struct Permission {
    id: String,
    name: String,
    why: String,
    state: String, // ok | ask | denied | unknown
    detail: String,
}

fn perm(id: &str, name: &str, why: &str, state: &str, detail: &str) -> Permission {
    Permission { id: id.into(), name: name.into(), why: why.into(), state: state.into(), detail: detail.into() }
}

/// Where each permission stands. Nothing here shows a macOS dialog.
#[tauri::command(async)]
fn permissions(s: State<'_, S>) -> Vec<Permission> {
    let mut out = vec![];
    let dev = has_dev_tools();
    if !dev {
        out.push(perm("tools", "Apple's command line tools", "Theseus's tools need them. In Terminal, run: xcode-select --install", "denied", ""));
    }
    let fda = fs::File::open(home().join("Library/Messages/chat.db")).is_ok();
    out.push(perm("files", "Full Disk Access", "To read your texts and Mail. You add Theseus to this list yourself; macOS never asks.", if fda { "ok" } else { "denied" }, ""));
    let ek = Command::new(s.ws.join("bin/ek")).arg("status").current_dir(&s.ws).output().ok()
        .and_then(|o| serde_json::from_slice::<Value>(&o.stdout).ok());
    for (id, name, why) in [
        ("calendars", "Calendars", "To build your agenda and add events you ask for."),
        ("reminders", "Reminders", "To keep your reminders in sync with your list."),
    ] {
        match ek.as_ref().and_then(|v| v[id].as_str()) {
            Some(st) => out.push(perm(id, name, why, st, "")),
            None => out.push(perm(id, name, why, "unknown", "Update the engine first: run ./install.sh --update from your copy of Theseus.")),
        }
    }
    out.push(perm("notes", "Notes", "To read your inbox folder and keep your Today and Master List notes current.", "unknown", ""));
    out.push(perm(
        "claude",
        "Claude Code",
        "Theseus runs on your own Claude Code account.",
        if s.claude.is_some() { "ok" } else { "denied" },
        &s.claude.as_ref().map(|p| p.display().to_string()).unwrap_or("Not found. Install Claude Code, then reopen this app.".into()),
    ));
    out
}

/// Make macOS show the dialog. It waits for your answer, up to two minutes, so it never runs on the window's thread.
#[tauri::command(async)]
fn request_permission(id: String, s: State<'_, S>) -> Result<String, String> {
    let (cmd, args): (PathBuf, Vec<&str>) = match id.as_str() {
        "calendars" | "reminders" => (s.ws.join("bin/ek"), vec!["access"]),
        "notes" => (PathBuf::from(PY), vec!["engine/tools/notes.py", "inbox"]),
        _ => return Err("macOS doesn't offer a dialog for this one.".into()),
    };
    let o = Command::new(cmd).args(args).current_dir(&s.ws).env("PATH", path_env()).output().map_err(|e| e.to_string())?;
    if o.status.success() {
        Ok(String::from_utf8_lossy(&o.stdout).chars().take(200).collect())
    } else {
        Err(String::from_utf8_lossy(&o.stderr).trim().chars().take(300).collect())
    }
}

#[tauri::command]
fn open_privacy(pane: String) {
    let anchor = match pane.as_str() {
        "files" => "Privacy_AllFiles",
        "calendars" => "Privacy_Calendars",
        "reminders" => "Privacy_Reminders",
        "automation" => "Privacy_Automation",
        "logins" => {
            let _ = Command::new("/usr/bin/open").arg("x-apple.systempreferences:com.apple.LoginItems-Settings.extension").spawn();
            return;
        }
        _ => "Privacy",
    };
    let _ = Command::new("/usr/bin/open").arg(format!("x-apple.systempreferences:com.apple.preference.security?{anchor}")).spawn();
}

// The jobs the app replaces. The iMessage channel isn't one of them: it keeps running under launchd.
const JOBS: [&str; 5] = ["remote", "morning", "nightly", "sync", "check"];
const WATCHDOG: &str = "com.theseus.watchdog";

fn quit_flag() -> PathBuf {
    // /tmp empties on restart, so quitting Theseus lasts until the next restart or until you open it again.
    PathBuf::from(format!("/tmp/theseus-quit-{}", uid()))
}

fn app_bundle() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    exe.ancestors().find(|p| p.extension().map(|e| e == "app").unwrap_or(false)).map(Path::to_path_buf)
}

fn xml_escape(s: &str) -> String {
    s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;")
}

/// Hosting means briefings stop if the app does, so a small launch agent opens it at login and reopens it if it crashes. Quitting from the
/// menu is respected. Development builds have no bundle, so they don't get one.
fn install_watchdog(ws: &Path) {
    let Some(app) = app_bundle() else { return };
    let path = home().join("Library/LaunchAgents").join(format!("{WATCHDOG}.plist"));
    let script = format!("pgrep -xq theseus || [ -e {} ] || open -g -j {}", quit_flag().display(), shell_quote(&app.display().to_string()));
    let plist = format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>{WATCHDOG}</string>
<key>ProgramArguments</key><array><string>/bin/sh</string><string>-c</string><string>{}</string></array>
<key>RunAtLoad</key><true/>
<key>StartInterval</key><integer>300</integer>
</dict></plist>
"#,
        xml_escape(&script)
    );
    if fs::read_to_string(&path).map(|t| t == plist).unwrap_or(false) {
        return;
    }
    let _ = fs::create_dir_all(path.parent().unwrap());
    let domain = format!("gui/{}", uid());
    let _ = Command::new("/bin/launchctl").args(["bootout", &domain, path.to_str().unwrap_or("")]).output();
    if fs::write(&path, plist).is_ok() {
        let _ = Command::new("/bin/launchctl").args(["bootstrap", &domain, path.to_str().unwrap_or("")]).output();
        log(ws, "app.log", "installed the launch agent that keeps Theseus open");
    }
}

fn remove_watchdog() {
    let path = home().join("Library/LaunchAgents").join(format!("{WATCHDOG}.plist"));
    let _ = Command::new("/bin/launchctl").args(["bootout", &format!("gui/{}", uid()), path.to_str().unwrap_or("")]).output();
    let _ = fs::remove_file(path);
}

fn shell_quote(s: &str) -> String {
    format!("'{}'", s.replace('\'', "'\\''"))
}

/// Stop the Remote Control server serving this workspace, and only that one: other projects on this Mac have their own.
fn stop_old_servers(ws: &Path) {
    let _ = Command::new("/usr/bin/pkill").args(["-f", "Theseus Remote.command"]).output();
    let Ok(o) = Command::new("/usr/bin/pgrep").args(["-f", "remote-control --name"]).output() else { return };
    for pid in String::from_utf8_lossy(&o.stdout).split_whitespace() {
        let Ok(l) = Command::new("/usr/sbin/lsof").args(["-a", "-d", "cwd", "-p", pid, "-Fn"]).output() else { continue };
        let here = format!("n{}", ws.display());
        if String::from_utf8_lossy(&l.stdout).lines().any(|line| line == here) {
            let _ = Command::new("/bin/kill").arg(pid).output();
        }
    }
}

fn uid() -> String {
    Command::new("/usr/bin/id").arg("-u").output().map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string()).unwrap_or_default()
}

fn set_hosts(ws: &Path, remote: &str, scheduler: &str, auto: bool) -> Result<(), String> {
    let mut cfg = config(ws);
    if !cfg.is_object() {
        return Err("config.json not found in the workspace".into());
    }
    cfg["remote_control"]["host"] = Value::from(remote);
    cfg["scheduler_host"] = Value::from(scheduler);
    cfg["auto_host"] = Value::from(auto);
    write_atomic(&ws.join("config.json"), &(serde_json::to_string_pretty(&cfg).map_err(|e| e.to_string())? + "\n"))
}

/// Move hosting from Terminal/launchd to the app. The config changes first: from then on the old jobs do nothing even if they run, so a
/// failure further down can't leave you with nothing running or with both running.
#[tauri::command(async)]
fn take_over(s: State<'_, S>) -> Result<String, String> {
    take_over_now(&s)
}

fn take_over_now(s: &S) -> Result<String, String> {
    let ws = &s.ws;
    set_hosts(ws, "app", "app", true)?;
    let uid = uid();
    let la = home().join("Library/LaunchAgents");
    let aside = ws.join("data/archive/launchagents");
    let _ = fs::create_dir_all(&aside);
    let mut moved = vec![];
    for job in JOBS {
        let p = la.join(format!("com.theseus.{job}.plist"));
        if p.exists() {
            let _ = Command::new("/bin/launchctl").args(["bootout", &format!("gui/{uid}"), p.to_str().unwrap_or("")]).output();
            if fs::rename(&p, aside.join(p.file_name().unwrap())).is_ok() {
                moved.push(job);
            }
        }
    }
    stop_old_servers(ws);
    install_watchdog(ws);
    set(s, |st| {
        st.remote = "Waiting for the previous server to let go of this folder. This can take a few minutes, and it retries by itself.".into();
        st.remote_state = "waiting".into();
    });
    log(ws, "app.log", &format!("took over hosting; launch agents set aside: {moved:?}"));
    Ok("Theseus now runs everything, and reopens itself at login or after a crash. Remote Control may take a few minutes to come back while the old server lets go.".into())
}

/// Give hosting back: the background jobs and the Terminal window return right away, so nothing is left unattended.
#[tauri::command(async)]
fn hand_back(s: State<'_, S>) -> Result<String, String> {
    let ws = &s.ws;
    set_hosts(ws, "terminal", "launchd", false)?;
    stop_remote(&s);
    remove_watchdog();
    let uid = uid();
    let la = home().join("Library/LaunchAgents");
    let aside = ws.join("data/archive/launchagents");
    let mut back = vec![];
    // "channel" too: an earlier version set it aside along with the rest.
    for job in JOBS.iter().copied().chain(["channel"]) {
        let name = format!("com.theseus.{job}.plist");
        let from = aside.join(&name);
        let to = la.join(&name);
        if from.exists() && !to.exists() && fs::rename(&from, &to).is_ok() {
            let _ = Command::new("/bin/launchctl").args(["bootstrap", &format!("gui/{uid}"), to.to_str().unwrap_or("")]).output();
            back.push(job);
        }
    }
    set(&s, |st| { st.remote = "Running from Terminal.".into(); st.remote_state = "off".into(); });
    log(ws, "app.log", &format!("handed hosting back; launch agents restored: {back:?}"));
    Ok("Handed back. The background jobs and the Terminal window are running again.".into())
}

// ---------- app ----------

/// Anything still waiting in the window (a check-off in its countdown, an unsaved edit) gets done now.
fn settle_window(app: &AppHandle) {
    let _ = app.emit("commit-now", ());
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let shared: S = Arc::new(Shared {
        ws: workspace(),
        claude: find_claude(),
        paused: AtomicBool::new(false),
        quitting: AtomicBool::new(false),
        remote: Mutex::new(None),
        status: Mutex::new(Status::default()),
        master: Mutex::new(()),
    });
    let _ = fs::create_dir_all(shared.ws.join("logs"));
    set(&shared, |st| {
        st.workspace = shared.ws.display().to_string();
        st.claude = shared.claude.as_ref().map(|p| p.display().to_string()).unwrap_or_else(|| "not found".into());
    });

    let on_exit = shared.clone();
    tauri::Builder::default()
        .manage(shared.clone())
        .invoke_handler(tauri::generate_handler![
            get_status, read_today, read_master, write_master, save_conflict, publish_master, run_now, set_paused, recent_runs, read_run, schedule, thread_notes, read_thread_note, read_commands, permissions, request_permission, open_privacy, take_over, hand_back
        ])
        .setup(move |app| {
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);

            // Open on the very first launch, so a new user isn't left with only a menu bar icon.
            // Opening the app undoes "Quit": from here on, the watchdog looks after it again.
            let _ = fs::remove_file(quit_flag());
            if hosting(&config(&shared.ws)) {
                install_watchdog(&shared.ws);
            }

            // Open on the first launch, and whenever it can't run yet, so nobody is left with only a menu bar icon.
            let seen = shared.ws.join("logs/.app-opened");
            let cfg = config(&shared.ws);
            let needs_setup = !hosting(&cfg) && cfg["auto_host"].as_bool() != Some(false) && !can_host(&shared);
            if !seen.exists() || needs_setup {
                let _ = fs::write(&seen, "");
                if let Some(w) = app.get_webview_window("main") {
                    let _ = w.show();
                    let _ = w.set_focus();
                }
            }

            let status_item = MenuItem::with_id(app, "status", "Theseus: starting…", false, None::<&str>)?;
            let open = MenuItem::with_id(app, "open", "Open Theseus", true, None::<&str>)?;
            let run_status = MenuItem::with_id(app, "run_status", "Run status now", true, None::<&str>)?;
            let pause = MenuItem::with_id(app, "pause", "Pause checks and Remote Control", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit Theseus", true, None::<&str>)?;
            let sep = PredefinedMenuItem::separator(app)?;
            let menu = Menu::with_items(app, &[&status_item, &sep, &open, &run_status, &pause, &quit])?;

            let s_menu = shared.clone();
            let pause_item = pause.clone();
            TrayIconBuilder::with_id("theseus")
                .icon(Image::from_bytes(include_bytes!("../icons/tray.png"))?)
                .icon_as_template(true)
                .tooltip("Theseus")
                .menu(&menu)
                .show_menu_on_left_click(true)
                .on_menu_event(move |app: &AppHandle, event| match event.id.as_ref() {
                    "open" => {
                        if let Some(w) = app.get_webview_window("main") {
                            let _ = w.show();
                            let _ = w.set_focus();
                        }
                    }
                    "run_status" => {
                        let _ = run_job(&s_menu, "status", "started from the menu bar");
                    }
                    "pause" => {
                        let now = !s_menu.paused.load(Ordering::SeqCst);
                        s_menu.paused.store(now, Ordering::SeqCst);
                        let _ = pause_item.set_text(if now { "Resume checks and Remote Control" } else { "Pause checks and Remote Control" });
                    }
                    "quit" => {
                        let _ = fs::write(quit_flag(), "");
                        settle_window(app);
                        thread::sleep(Duration::from_millis(600));
                        s_menu.quitting.store(true, Ordering::SeqCst);
                        stop_remote(&s_menu);
                        app.exit(0);
                    }
                    _ => {}
                })
                .build(app)?;

            // Keep the menu bar status line fresh.
            let s_tick = shared.clone();
            thread::spawn(move || loop {
                if s_tick.quitting.load(Ordering::SeqCst) {
                    return;
                }
                let st = s_tick.status.lock().unwrap().clone();
                let line = if s_tick.paused.load(Ordering::SeqCst) {
                    "Theseus: paused".to_string()
                } else if let Some(j) = st.job_running {
                    format!("Theseus: running {j}…")
                } else {
                    match st.remote_state.as_str() {
                        "running" => "Theseus: running".to_string(),
                        "waiting" | "starting" => "Theseus: starting Remote Control…".to_string(),
                        "error" => "Theseus: Remote Control needs a look".to_string(),
                        _ => "Theseus".to_string(),
                    }
                };
                let _ = status_item.set_text(line);
                thread::sleep(Duration::from_secs(5));
            });

            let s_remote = shared.clone();
            thread::spawn(move || remote_loop(s_remote));
            let s_sched = shared.clone();
            thread::spawn(move || schedule_loop(s_sched));
            Ok(())
        })
        .on_window_event(|window, event| {
            // Closing the window just hides it; Theseus keeps running in the menu bar.
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                settle_window(window.app_handle());
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while starting Theseus")
        .run(move |handle, event| match event {
            // Opening the app again (Finder, Spotlight) brings the window back.
            RunEvent::Reopen { .. } => {
                if let Some(w) = handle.get_webview_window("main") {
                    let _ = w.show();
                    let _ = w.set_focus();
                }
            }
            // Any way out, including logging out: don't leave the server behind.
            RunEvent::Exit => {
                on_exit.quitting.store(true, Ordering::SeqCst);
                stop_remote(&on_exit);
            }
            _ => {}
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn job_lock_is_one_at_a_time_and_ignores_the_dead() {
        let ws = std::env::temp_dir().join(format!("theseus-lock-{}", std::process::id()));
        fs::create_dir_all(ws.join("data")).unwrap();
        let lock = ws.join("data/.job.lock");

        let first = JobLock::take(&ws).expect("free");
        assert!(JobLock::take(&ws).is_none(), "held by a live process");
        drop(first);
        assert!(!lock.exists(), "released");

        let mut gone = Command::new("/usr/bin/true").spawn().unwrap();
        let pid = gone.id();
        gone.wait().unwrap();
        fs::write(&lock, pid.to_string()).unwrap();
        assert!(JobLock::take(&ws).is_some(), "its holder has gone");

        fs::write(&lock, "").unwrap();
        assert!(JobLock::take(&ws).is_none(), "someone is mid-way through taking it");
        let _ = fs::remove_dir_all(&ws);
    }
}
