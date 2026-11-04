import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

type Status = {
  workspace: string;
  claude: string;
  hosting: boolean;
  paused: boolean;
  remote: string;
  last_check: string;
  job_running: string | null;
  last_job: string;
  last_job_output: string;
  runs_today: string[];
};
type Check = { name: string; ok: boolean; detail: string };
type Tab = "today" | "services" | "permissions";

const PANES: [string, string][] = [
  ["files", "Full Disk Access"],
  ["calendars", "Calendars"],
  ["reminders", "Reminders"],
  ["automation", "Automation (Notes)"],
];

export default function App() {
  const [tab, setTab] = useState<Tab>("today");
  const [status, setStatus] = useState<Status | null>(null);
  const [today, setToday] = useState("");
  const [checks, setChecks] = useState<Check[] | null>(null);
  const [msg, setMsg] = useState("");

  const refresh = async () => {
    setStatus(await invoke<Status>("get_status"));
    setToday(await invoke<string>("read_today"));
  };
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, []);

  const act = async (fn: () => Promise<unknown>) => {
    try {
      const r = await fn();
      setMsg(typeof r === "string" ? r : "Done.");
    } catch (e) {
      setMsg(String(e));
    }
    refresh();
  };

  return (
    <div className="app">
      <header>
        <h1>Theseus</h1>
        <nav>
          {(["today", "services", "permissions"] as Tab[]).map((t) => (
            <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>
              {t[0].toUpperCase() + t.slice(1)}
            </button>
          ))}
        </nav>
      </header>

      {msg && <p className="msg" onClick={() => setMsg("")}>{msg}</p>}

      {tab === "today" && (
        <section>
          <div className="row">
            <button disabled={!!status?.job_running} onClick={() => act(() => invoke("run_now", { kind: "status" }))}>
              {status?.job_running ? `Running ${status.job_running}…` : "Run status now"}
            </button>
          </div>
          <pre className="today">{today}</pre>
        </section>
      )}

      {tab === "services" && status && (
        <section>
          {!status.hosting && (
            <div className="card warn">
              <p>
                Theseus.app isn't hosting yet. Remote Control and the schedule still run from Terminal and background jobs.
                Take over once you've granted permissions (Permissions tab).
              </p>
              <button onClick={() => act(() => invoke<string>("take_over"))}>Take over hosting</button>
            </div>
          )}
          <dl>
            <dt>Remote Control</dt><dd>{status.remote || "…"}</dd>
            <dt>Last change check</dt><dd>{status.last_check || "none yet"}</dd>
            <dt>Last run</dt><dd>{status.last_job || "none yet"}</dd>
            <dt>Runs today</dt><dd>{status.runs_today.length ? status.runs_today.join(", ") : "none"}</dd>
            <dt>Workspace</dt><dd>{status.workspace}</dd>
            <dt>Claude Code</dt><dd>{status.claude}</dd>
          </dl>
          <div className="row">
            <button onClick={() => act(() => invoke("set_paused", { paused: !status.paused }))}>
              {status.paused ? "Resume" : "Pause"} checks and Remote Control
            </button>
            <button onClick={() => act(() => invoke("run_now", { kind: "sync" }))}>Sync now</button>
            {status.hosting && (
              <button className="quiet" onClick={() => act(() => invoke<string>("hand_back"))}>Hand back to Terminal</button>
            )}
          </div>
          {status.last_job_output && <pre className="out">{status.last_job_output}</pre>}
        </section>
      )}

      {tab === "permissions" && (
        <section>
          <p>
            Grant these to <b>Theseus</b> in System Settings. Everything Theseus starts (Remote Control, checks, briefings) uses
            them.
          </p>
          <div className="row">
            {PANES.map(([p, label]) => (
              <button key={p} onClick={() => invoke("open_privacy", { pane: p })}>{label}…</button>
            ))}
          </div>
          <button onClick={async () => setChecks(await invoke<Check[]>("check_permissions"))}>Check access</button>
          {checks && (
            <ul className="checks">
              {checks.map((c) => (
                <li key={c.name} className={c.ok ? "ok" : "bad"}>
                  <b>{c.ok ? "✓" : "✗"} {c.name}</b>
                  <pre>{c.detail}</pre>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
