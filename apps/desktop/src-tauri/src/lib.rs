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
use tauri::{AppHandle, Manager, RunEvent, State, WindowEvent};

const PY: &str = "/usr/bin/python3";

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
    runs_today: Vec<String>,
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
    ran: Mutex<Vec<String>>, // keys of scheduled runs already done ("2026-11-03 05:50 morning")
}

type S = Arc<Shared>;

// ---------- helpers ----------

fn home() -> PathBuf {
    PathBuf::from(std::env::var("HOME").unwrap_or_else(|_| "/Users/Shared".into()))
}

fn workspace() -> PathBuf {
    std::env::var("THESEUS_HOME").map(PathBuf::from).unwrap_or_else(|_| home().join("Theseus"))
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

fn hhmm_to_min(s: &str) -> Option<u32> {
    let (h, m) = s.split_once(':')?;
    Some(h.parse::<u32>().ok()? * 60 + m.parse::<u32>().ok()?)
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

fn prompt_for(kind: &str, reason: &str) -> String {
    if kind == "ask" {
        return format!(
            "The user asked this in the Theseus app: \"{reason}\". Answer briefly and follow engine/RULES.md. If it's something to do or remember, add it to the list. Never send anything. This run can't ask follow-up questions, so make the sensible choice and say what you did."
        );
    }
    let wf = match kind {
        "morning" => "engine/workflows/morning.md",
        "nightly" => "engine/workflows/nightly.md",
        "status" => "engine/workflows/status.md",
        _ => "engine/workflows/sync.md",
    };
    let extra = if reason.is_empty() { String::new() } else { format!(" Reason for this run: {reason}.") };
    format!("Run exactly as defined in {wf}.{extra} This is an unattended run started by Theseus.app: never wait for input.")
}

fn run_job(s: &S, kind: &str, reason: &str) -> Result<(), String> {
    {
        let st = s.status.lock().unwrap();
        if let Some(j) = &st.job_running {
            return Err(format!("{j} is already running"));
        }
    }
    let claude = s.claude.clone().ok_or("Claude Code not found")?;
    let (d, m) = local_now();
    let stamp = format!("{}_{:02}{:02}", d, m / 60, m % 60);
    let out_path = s.ws.join(format!("logs/app-{kind}-{stamp}.out"));
    let out = fs::File::create(&out_path).map_err(|e| e.to_string())?;
    let err = out.try_clone().map_err(|e| e.to_string())?;
    let mut child = Command::new(&claude)
        .args(["-p", &prompt_for(kind, reason), "--output-format", "text"])
        .current_dir(&s.ws)
        .env("PATH", path_env())
        .stdin(Stdio::null())
        .stdout(out)
        .stderr(err)
        .spawn()
        .map_err(|e| e.to_string())?;
    set(s, |st| st.job_running = Some(kind.to_string()));
    let s2 = s.clone();
    let kind = kind.to_string();
    thread::spawn(move || {
        let code = child.wait().map(|c| c.to_string()).unwrap_or_else(|e| e.to_string());
        let text = fs::read_to_string(&out_path).unwrap_or_default();
        let (d, m) = local_now();
        set(&s2, |st| {
            st.job_running = None;
            st.last_job = format!("{kind} at {}:{:02} ({code})", m / 60, m % 60);
            st.last_job_output = text.chars().rev().take(4000).collect::<String>().chars().rev().collect();
            st.runs_today.push(format!("{d} {:02}:{:02} {kind}", m / 60, m % 60));
        });
    });
    Ok(())
}

fn schedule_loop(s: S) {
    let mut last_check = Instant::now() - Duration::from_secs(3600);
    loop {
        if s.quitting.load(Ordering::SeqCst) {
            return;
        }
        thread::sleep(Duration::from_secs(20));
        let cfg = config(&s.ws);
        if cfg["scheduler_host"].as_str() != Some("app") || s.paused.load(Ordering::SeqCst) {
            continue;
        }
        let (today, now) = local_now();

        // Morning and nightly runs, from the engine's own per-day schedule.
        let plan = Command::new(PY).arg("engine/tools/schedule.py").current_dir(&s.ws).output().ok()
            .and_then(|o| serde_json::from_slice::<Value>(&o.stdout).ok());
        if let Some(day) = plan.as_ref().and_then(|p| p["days"].get(0)) {
            for (kind, key) in [("morning", "morning_run"), ("nightly", "nightly_run")] {
                if let Some(at) = day[key].as_str().and_then(hhmm_to_min) {
                    let run_key = format!("{today} {at} {kind}");
                    let due = now >= at && now < at + 15;
                    let done = s.ran.lock().unwrap().contains(&run_key);
                    if due && !done && run_job(&s, kind, "scheduled").is_ok() {
                        s.ran.lock().unwrap().push(run_key);
                        log(&s.ws, "app.log", &format!("started {kind} run"));
                    }
                }
            }
        }

        // Cheap change checks: Claude only runs when something changed (changes.py decides, with its own cooldown and quiet hours).
        let every = cfg["checks"]["every_minutes"].as_u64().unwrap_or(5).max(1);
        let checks_on = cfg["checks"]["enabled"].as_bool().unwrap_or(false);
        if checks_on && last_check.elapsed() >= Duration::from_secs(every * 60) {
            last_check = Instant::now();
            if let Ok(o) = Command::new(PY).arg("engine/tools/changes.py").current_dir(&s.ws).output() {
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
/// replays the edit on the new text. The write is atomic, and an hourly copy goes in data/archive.
#[tauri::command(async)]
fn write_master(text: String, base: String, s: State<'_, S>) -> Result<(), String> {
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
    fs::rename(&tmp, &path).map_err(|e| e.to_string())
}

/// What the person did, for the next sync: it completes things elsewhere and treats moves as their own ranking (RULES §3).
#[tauri::command(async)]
fn log_edit(event: Value, s: State<'_, S>) -> Result<(), String> {
    use std::io::Write;
    let (d, m) = local_now();
    let mut e = event;
    e["time"] = Value::from(format!("{d} {:02}:{:02}", m / 60, m % 60));
    let mut f = OpenOptions::new().create(true).append(true).open(s.ws.join("data/app-edits.jsonl")).map_err(|e| e.to_string())?;
    writeln!(f, "{e}").map_err(|e| e.to_string())
}

/// Update the phone's copy of the list. If the person edited that note, the tool refuses and the next run folds their edits in.
#[tauri::command(async)]
fn publish_master(s: State<'_, S>) -> Result<(), String> {
    let o = Command::new(PY).args(["engine/tools/notes.py", "master-publish"]).current_dir(&s.ws).env("PATH", path_env()).output().map_err(|e| e.to_string())?;
    if o.status.success() { Ok(()) } else { Err(String::from_utf8_lossy(&o.stderr).trim().chars().take(200).collect()) }
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

const JOBS: [&str; 6] = ["remote", "morning", "nightly", "sync", "check", "channel"];

fn uid() -> String {
    Command::new("/usr/bin/id").arg("-u").output().map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string()).unwrap_or_default()
}

fn set_hosts(ws: &Path, remote: &str, scheduler: &str) -> Result<(), String> {
    let mut cfg = config(ws);
    if !cfg.is_object() {
        return Err("config.json not found in the workspace".into());
    }
    cfg["remote_control"]["host"] = Value::from(remote);
    cfg["scheduler_host"] = Value::from(scheduler);
    fs::write(ws.join("config.json"), serde_json::to_string_pretty(&cfg).unwrap()).map_err(|e| e.to_string())
}

/// Move hosting from Terminal/launchd to the app. The old jobs stop first, so the app doesn't start a server only to have it killed.
#[tauri::command(async)]
fn take_over(s: State<'_, S>) -> Result<String, String> {
    let ws = &s.ws;
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
    let _ = Command::new("/usr/bin/pkill").args(["-f", "Theseus Remote.command"]).output();
    let _ = Command::new("/usr/bin/pkill").args(["-f", "remote-control --name"]).output();
    set_hosts(ws, "app", "app")?;
    set(&s, |st| {
        st.remote = "Waiting for the previous server to let go of this folder. This can take a few minutes, and it retries by itself.".into();
        st.remote_state = "waiting".into();
    });
    log(ws, "app.log", &format!("took over hosting; launch agents set aside: {moved:?}"));
    Ok("Theseus now runs everything. Remote Control may take a few minutes to come back while the old server lets go.".into())
}

/// Give hosting back: the background jobs and the Terminal window return right away, so nothing is left unattended.
#[tauri::command(async)]
fn hand_back(s: State<'_, S>) -> Result<String, String> {
    let ws = &s.ws;
    set_hosts(ws, "terminal", "launchd")?;
    stop_remote(&s);
    let uid = uid();
    let la = home().join("Library/LaunchAgents");
    let aside = ws.join("data/archive/launchagents");
    let mut back = vec![];
    for job in JOBS {
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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let shared: S = Arc::new(Shared {
        ws: workspace(),
        claude: find_claude(),
        paused: AtomicBool::new(false),
        quitting: AtomicBool::new(false),
        remote: Mutex::new(None),
        status: Mutex::new(Status::default()),
        ran: Mutex::new(vec![]),
    });
    let _ = fs::create_dir_all(shared.ws.join("logs"));
    set(&shared, |st| {
        st.workspace = shared.ws.display().to_string();
        st.claude = shared.claude.as_ref().map(|p| p.display().to_string()).unwrap_or_else(|| "not found".into());
    });

    tauri::Builder::default()
        .manage(shared.clone())
        .invoke_handler(tauri::generate_handler![
            get_status, read_today, read_master, write_master, log_edit, publish_master, run_now, set_paused, recent_runs, read_run, schedule, permissions, request_permission, open_privacy, take_over, hand_back
        ])
        .setup(move |app| {
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);

            // Open on the very first launch, so a new user isn't left with only a menu bar icon.
            let seen = shared.ws.join("logs/.app-opened");
            if !seen.exists() {
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
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while starting Theseus")
        .run(|handle, event| {
            // Opening the app again (Finder, Spotlight) brings the window back.
            if let RunEvent::Reopen { .. } = event {
                if let Some(w) = handle.get_webview_window("main") {
                    let _ = w.show();
                    let _ = w.set_focus();
                }
            }
        });
}
