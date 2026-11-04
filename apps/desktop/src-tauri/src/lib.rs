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
                        set(&s, |st| st.remote = "starting…".into());
                    }
                    Err(e) => {
                        set(&s, |st| st.remote = format!("couldn't start: {e}"));
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
                set(&s, |st| {
                    st.remote = if quick {
                        "couldn't start: another copy (Terminal window or Claude desktop app) may be serving this folder".into()
                    } else {
                        "restarting…".into()
                    }
                });
                wait_until = Instant::now() + Duration::from_secs(backoff);
            }
            Some((Ok(None), up)) => set(&s, |st| st.remote = format!("running ({} min)", up.as_secs() / 60)),
            Some((Err(e), _)) => set(&s, |st| st.remote = format!("unknown: {e}")),
        }
        thread::sleep(Duration::from_secs(5));
    }
}

// ---------- jobs (sync, morning, nightly, status) ----------

fn prompt_for(kind: &str, reason: &str) -> String {
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
    fs::read_to_string(s.ws.join("data/today.md")).unwrap_or_else(|_| "No Today note yet. Run a status check.".into())
}

#[tauri::command]
fn run_now(kind: String, s: State<'_, S>) -> Result<(), String> {
    run_job(&s, &kind, "started from Theseus.app")
}

#[tauri::command]
fn set_paused(paused: bool, s: State<'_, S>) {
    s.paused.store(paused, Ordering::SeqCst);
}

#[derive(Serialize)]
struct Check {
    name: String,
    ok: bool,
    detail: String,
}

#[tauri::command]
fn check_permissions(s: State<'_, S>) -> Vec<Check> {
    let ws = &s.ws;
    let run = |cmd: &str, args: &[&str]| -> (bool, String) {
        match Command::new(cmd).args(args).current_dir(ws).env("PATH", path_env()).output() {
            Ok(o) => {
                let text = format!("{}{}", String::from_utf8_lossy(&o.stdout), String::from_utf8_lossy(&o.stderr));
                (o.status.success(), text.lines().take(6).collect::<Vec<_>>().join("\n"))
            }
            Err(e) => (false, e.to_string()),
        }
    };
    let mut out = vec![];
    let (ok, d) = run(PY, &["engine/tools/imsg.py", "--fresh", "doctor"]);
    out.push(Check { name: "Texts & Contacts (Full Disk Access)".into(), ok: ok && !d.contains("saved copy"), detail: d });
    let (ok, d) = run(ws.join("bin/ek").to_str().unwrap_or("bin/ek"), &["access"]);
    out.push(Check { name: "Calendars & Reminders".into(), ok: ok && !d.contains("false"), detail: d });
    let (ok, d) = run(PY, &["engine/tools/notes.py", "inbox"]);
    out.push(Check { name: "Notes (Automation)".into(), ok, detail: d.chars().take(300).collect() });
    out.push(Check {
        name: "Claude Code".into(),
        ok: s.claude.is_some(),
        detail: s.claude.as_ref().map(|p| p.display().to_string()).unwrap_or("not found: install Claude Code".into()),
    });
    out
}

#[tauri::command]
fn open_privacy(pane: String) {
    let anchor = match pane.as_str() {
        "files" => "Privacy_AllFiles",
        "calendars" => "Privacy_Calendars",
        "reminders" => "Privacy_Reminders",
        "automation" => "Privacy_Automation",
        _ => "Privacy",
    };
    let _ = Command::new("/usr/bin/open").arg(format!("x-apple.systempreferences:com.apple.preference.security?{anchor}")).spawn();
}

/// Move hosting from Terminal/launchd to the app: set the config, stop the old jobs, and put their launch agents aside (reversibly).
#[tauri::command]
fn take_over(s: State<'_, S>) -> Result<String, String> {
    let ws = &s.ws;
    let mut cfg = config(ws);
    if !cfg.is_object() {
        return Err("config.json not found in the workspace".into());
    }
    cfg["remote_control"]["host"] = Value::from("app");
    cfg["scheduler_host"] = Value::from("app");
    fs::write(ws.join("config.json"), serde_json::to_string_pretty(&cfg).unwrap()).map_err(|e| e.to_string())?;

    let uid = Command::new("/usr/bin/id").arg("-u").output().map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string()).unwrap_or_default();
    let la = home().join("Library/LaunchAgents");
    let aside = ws.join("data/archive/launchagents");
    let _ = fs::create_dir_all(&aside);
    let mut moved = vec![];
    for job in ["remote", "morning", "nightly", "sync", "check", "channel"] {
        let p = la.join(format!("com.theseus.{job}.plist"));
        if p.exists() {
            let _ = Command::new("/bin/launchctl").args(["bootout", &format!("gui/{uid}"), p.to_str().unwrap_or("")]).output();
            if fs::rename(&p, aside.join(p.file_name().unwrap())).is_ok() {
                moved.push(job);
            }
        }
    }
    // Stop a Remote Control server still running in a Terminal window (and the loop that restarts it).
    let _ = Command::new("/usr/bin/pkill").args(["-f", "Theseus Remote.command"]).output();
    let _ = Command::new("/usr/bin/pkill").args(["-f", "remote-control --name"]).output();
    log(ws, "app.log", &format!("took over hosting; launch agents set aside: {moved:?}"));
    Ok(format!(
        "Theseus.app now hosts Remote Control and the schedule. Old background jobs set aside: {}. You can close the Terminal window.",
        if moved.is_empty() { "none".into() } else { moved.join(", ") }
    ))
}

/// Give hosting back to Terminal/launchd (the launch agents come back on the next `engine/install.sh --schedule`).
#[tauri::command]
fn hand_back(s: State<'_, S>) -> Result<String, String> {
    let ws = &s.ws;
    let mut cfg = config(ws);
    cfg["remote_control"]["host"] = Value::from("terminal");
    cfg["scheduler_host"] = Value::from("launchd");
    fs::write(ws.join("config.json"), serde_json::to_string_pretty(&cfg).unwrap()).map_err(|e| e.to_string())?;
    stop_remote(&s);
    Ok("Hosting handed back. Run `bash ~/Theseus/engine/install.sh --schedule` in Terminal to restore the background jobs.".into())
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
            get_status, read_today, run_now, set_paused, check_permissions, open_privacy, take_over, hand_back
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
                    format!("Remote: {}", st.remote)
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
