import { invoke } from '@tauri-apps/api/core'
import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { inlineParts } from './inline'
import { Block, ListTools, useListActions, type ListActions } from './ListUI'
import { commsSection, dropEmoji, nowSection } from './master'
import { Icon, type IconName } from './ui/Icon'
import { useMaster, type Master } from './useMaster'

type Tab = 'today' | 'list' | 'activity' | 'setup'
type Status = {
  workspace: string
  claude: string
  hosting: boolean
  paused: boolean
  remote: string
  remote_state: string
  last_check: string
  job_running: string | null
  last_job: string
  last_job_output: string
  last_answer: string
  auto_host: boolean
  can_host: boolean
  app_version: string
  engine_version: string
}
type Run = { file: string; kind: string; when: string; bytes: number }
type ThreadNote = { id: string; label: string; last_updated: string | null; last_checked: string | null; seen: number }
type Permission = { id: string; name: string; why: string; state: 'ok' | 'ask' | 'denied' | 'unknown'; detail: string }
type Section = { title: string; lines: string[] }

const NAV: [Tab, string, IconName][] = [
  ['today', 'Today', 'today'],
  ['list', 'List', 'plans'],
  ['activity', 'Activity', 'activity'],
  ['setup', 'Setup', 'setup'],
]
const JOB_WORDS: Record<string, string> = { status: 'Refreshing', sync: 'Syncing', morning: 'Morning briefing', nightly: 'Evening prep', ask: 'Thinking' }

/** Turns the Today note's markdown into parts the screen can lay out. */
function parseToday(md: string) {
  const title = dropEmoji(md.match(/^# (.*)$/m)?.[1] ?? '').replace(/^[^\p{L}\p{N}]+/u, '')
  const updated = md.match(/^_(Updated[^·_]*)/m)?.[1]?.trim() ?? ''
  const sections: Section[] = []
  let cur: Section | null = null
  const lead: string[] = []
  for (const line of md.split('\n')) {
    if (line.startsWith('# ') || /^_Updated/.test(line)) continue
    if (line.startsWith('## ')) {
      cur = { title: line.slice(3).replace(/^[^\p{L}\p{N}]+/u, ''), lines: [] }
      sections.push(cur)
    } else if (line.trim()) {
      ;(cur ? cur.lines : lead).push(dropEmoji(line.trim()))
    }
  }
  return { title, updated, lead, sections }
}

/** **bold**, `code` and _italic_, safely, as React nodes. */
function inline(text: string): ReactNode {
  return inlineParts(text).map((p, i) => {
    if (p.kind === 'bold') return <b key={i}>{p.text}</b>
    if (p.kind === 'code') return <code key={i}>{p.text}</code>
    if (p.kind === 'italic') return <i key={i}>{p.text}</i>
    return p.text
  })
}

const TODAY_ICONS: [RegExp, IconName][] = [[/agenda/i, 'calendar'], [/due|remind|chore/i, 'bell'], [/up next/i, 'skipForward'], [/tomorrow/i, 'moon'], [/film/i, 'film'], [/waiting/i, 'message'], [/needs you/i, 'info']]
const todayIcon = (title: string): IconName => TODAY_ICONS.find(([re]) => re.test(title))?.[1] ?? 'list'

const isTodo = (l: string) => l.startsWith('☐')
const noTodo = (l: string) => l.replace(/^☐\s*/, '')

export default function App() {
  const [tab, setTab] = useState<Tab>('today')
  const [status, setStatus] = useState<Status | null>(null)
  const master = useMaster()
  const actions = useListActions(master)
  const refresh = useCallback(() => invoke<Status>('get_status').then(setStatus).catch(() => {}), [])
  useEffect(() => {
    void refresh()
    const t = setInterval(refresh, 3000)
    return () => clearInterval(t)
  }, [refresh])

  const foot = !status
    ? null
    : status.job_running
      ? { cls: 'warn', text: `${JOB_WORDS[status.job_running] ?? 'Working'}…` }
      : status.paused
        ? { cls: '', text: 'Paused' }
        : status.hosting
          ? status.remote_state === 'running'
            ? { cls: 'ok', text: 'Running' }
            : status.remote_state === 'error'
              ? { cls: 'bad', text: 'Needs a look' }
              : { cls: 'warn', text: 'Starting…' }
          : { cls: '', text: 'Running from Terminal' }

  return (
    <div className="shell">
      <aside className="side">
        <div className="brand"><img src="/icon.svg" alt="" />Theseus</div>
        <nav className="nav">
          {NAV.map(([t, label, icon]) => (
            <button key={t} aria-current={tab === t ? 'page' : undefined} onClick={() => setTab(t)}>
              <Icon name={icon} />
              {label}
            </button>
          ))}
        </nav>
        {foot && <div className="side-foot"><span className={`pill ${foot.cls}`}><span className="dot" />{foot.text}</span></div>}
      </aside>
      <div className="main">
        {status && status.engine_version !== status.app_version && (
          <div className="page version-note">
            <div className="notice"><Icon name="alert" /><div>This is Theseus {status.app_version}, but your workspace has engine {status.engine_version || 'from before 0.5'}. Update it so they match: in your copy of Theseus, run <code>./install.sh --update</code>.</div></div>
          </div>
        )}
        {status && !status.hosting && status.auto_host && !status.can_host && tab !== 'setup' && (
          <div className="page version-note">
            <div className="notice"><Icon name="info" /><div className="grow">Theseus runs by itself once it has its permissions.</div><button className="btn" onClick={() => setTab('setup')}>Open Setup</button></div>
          </div>
        )}
        {tab === 'today' && <Today status={status} onChange={refresh} m={master} a={actions} />}
        {tab === 'list' && <ListPage m={master} a={actions} />}
        {tab === 'activity' && <Activity status={status} onChange={refresh} onSetup={() => setTab('setup')} />}
        {tab === 'setup' && <Setup status={status} onChange={refresh} />}
      </div>
      {actions.toast && (
        <div className="toast" role="status">
          <span>{actions.toast}</span>
          {master.canUndo && <button onClick={() => { master.undo(); actions.clearToast() }}>Undo</button>}
        </div>
      )}
    </div>
  )
}

function ListPage({ m, a }: { m: Master; a: ListActions }) {
  const [raw, setRaw] = useState(() => {
    try { return localStorage.getItem('theseus.listView') === 'markdown' } catch { return false }
  })
  const choose = (v: boolean) => {
    setRaw(v)
    try { localStorage.setItem('theseus.listView', v ? 'markdown' : 'list') } catch { /* it's only a convenience */ }
  }
  const closedAtFirst = new Set(['eventually', 'done', 'projects', 'figure out'])
  return (
    <div className="page">
      <div className="head">
        <div className="grow">
          <h1>List</h1>
          <div className="sub">Drag to reorder. Double-click to rename. Everything saves as you go.</div>
        </div>
        <ListTools m={m} />
        <div className="segmented" role="group" aria-label="View">
          <button aria-pressed={!raw} onClick={() => choose(false)}><Icon name="list" />List</button>
          <button aria-pressed={raw} onClick={() => choose(true)}><Icon name="code" />Markdown</button>
        </div>
      </div>
      {m.notice && <div className="notice"><Icon name="info" /><div className="grow">{m.notice}</div><button className="btn quiet icon" style={{ height: 22, width: 22 }} aria-label="Dismiss" onClick={m.clearNotice}><Icon name="close" size={14} /></button></div>}
      {m.text === '' && <div className="card empty"><Icon name="plans" size={28} /><h2>No list yet</h2><div>Run <code>/migrate</code> in Claude Code to build it from your reminders and notes.</div></div>}
      {raw && m.text !== null && (
        <textarea className="md-editor" spellCheck={false} aria-label="Master list as Markdown" value={m.text} onChange={(e) => m.type(e.target.value)} />
      )}
      {!raw && m.doc?.sections.map((s) => <Block key={s.key} section={s} m={m} a={a} collapsible defaultOpen={!closedAtFirst.has(s.key)} />)}
    </div>
  )
}

function Today({ status, onChange, m, a }: { status: Status | null; onChange: () => void; m: Master; a: ListActions }) {
  const [md, setMd] = useState<string | null>(null)
  const [text, setText] = useState('')
  const [asked, setAsked] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [showAttention, setShowAttention] = useState(false)
  const [answered, setAnswered] = useState(false)
  const running = status?.job_running ?? null
  const was = useRef<string | null>(null)
  const load = useCallback(() => invoke<string>('read_today').then(setMd), [])
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (was.current && !running) {
      void load()
      if (was.current === 'ask') setAnswered(true)
    }
    was.current = running
  }, [running, load])

  const today = useMemo(() => parseToday(md ?? ''), [md])
  const run = (kind: string, words?: string) => {
    setError('')
    invoke('run_now', { kind, text: words }).then(onChange).catch((e) => setError(String(e)))
  }
  const ask = (q: string) => {
    if (!q.trim()) return
    setAsked(q.trim())
    setAnswered(false)
    setText('')
    run('ask', q.trim())
  }

  const attention = today.sections.find((s) => /attention/i.test(s.title))
  const now = today.sections.find((s) => /^now\b/i.test(s.title))
  const waitingOn = today.sections.find((s) => /waiting on you/i.test(s.title))
  const rest = today.sections.filter((s) => s !== attention && s !== now && s !== waitingOn && !/^jot/i.test(s.title) && s.lines.length)
  const liveNow = m.doc ? nowSection(m.doc) : undefined
  const liveComms = m.doc ? commsSection(m.doc) : undefined

  return (
    <div className="page">
      <div className="head">
        <div className="grow">
          <h1>{today.title || 'Today'}</h1>
          {today.updated && <div className="sub">{today.updated}</div>}
        </div>
        <ListTools m={m} />
        <button className="btn" disabled={!!running} onClick={() => run('status')}>
          <Icon name="refresh" className={running === 'status' ? 'spin' : undefined} />
          {running === 'status' ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      <form className="ask" onSubmit={(e) => { e.preventDefault(); ask(text) }}>
        <input type="text" value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask Theseus, or tell it something to remember" aria-label="Ask Theseus" />
        <button className="btn" type="button" disabled={!!running} onClick={() => ask("I've got a few minutes. What's next?")}>What's next?</button>
        <button className="btn primary icon" disabled={!!running || !text.trim()} aria-label="Send"><Icon name="send" /></button>
      </form>

      {error && <div className="notice bad"><Icon name="alert" /><div>{error}</div></div>}

      {asked && (
        <div className="card">
          <div className="card-title">{asked}</div>
          {answered
            ? <div className="answer">{inline(status?.last_answer.trim() ?? '')}</div>
            : <div className="answer muted">Thinking…</div>}
        </div>
      )}

      {md === '' && (
        <div className="card empty">
          <Icon name="today" size={28} />
          <h2>No Today note yet</h2>
          <div>Refresh to gather your texts, email, calendar and reminders.</div>
        </div>
      )}

      {attention && attention.lines.length > 0 && (
        <div className="card">
          <button className="item click" onClick={() => setShowAttention(!showAttention)} aria-expanded={showAttention}>
            <span style={{ color: 'var(--warn)', display: 'flex' }}><Icon name="alert" /></span>
            <span className="grow">{attention.lines.length === 1 ? '1 thing needs attention' : `${attention.lines.length} things need attention`}</span>
            <Icon name="chevron" className={`chev ${showAttention ? 'open' : ''}`} />
          </button>
          {showAttention && <div className="lines selectable">{attention.lines.map((l, i) => <div key={i}>{inline(l)}</div>)}</div>}
        </div>
      )}

      {m.notice && <div className="notice"><Icon name="info" /><div className="grow">{m.notice}</div><button className="btn quiet icon" style={{ height: 22, width: 22 }} aria-label="Dismiss" onClick={m.clearNotice}><Icon name="close" size={14} /></button></div>}

      {liveNow ? <Block section={liveNow} m={m} a={a} /> : now && (
        <div className="card">
          <div className="card-title">Now</div>
          <ol className="now selectable">
            {now.lines.filter(isTodo).map((l, i) => <li key={i}><span className="rank">{i + 1}</span><span className="text">{inline(noTodo(l))}</span></li>)}
          </ol>
        </div>
      )}

      {liveComms && (
        <Block section={liveComms} m={m} a={a} footer={waitingOn && waitingOn.lines.length > 0 && (
          <div className="also selectable">{waitingOn.lines.map((l, i) => <div key={i}>{inline(l)}</div>)}</div>
        )} />
      )}
      {!liveComms && waitingOn && (
        <div className="card"><div className="block-head"><Icon name="message" className="block-icon" /><span className="block-name">Communication</span></div><div className="lines selectable">{waitingOn.lines.map((l, i) => <div key={i}>{inline(l)}</div>)}</div></div>
      )}

      {today.lead.length > 0 && <div className="muted small">{today.lead.map((l, i) => <div key={i}>{inline(l)}</div>)}</div>}

      {rest.length > 0 && (
        <div className="sections">
          {[0, 1].map((col) => (
            <div className="column" key={col}>
              {rest.filter((_, i) => i % 2 === col).map((s) => (
                <div className="card" key={s.title}>
                  <div className="block-head"><Icon name={todayIcon(s.title)} className="block-icon" /><span className="block-name">{s.title}</span></div>
                  <div className="lines selectable">
                    {s.lines.map((l, i) => isTodo(l) ? <div className="todo" key={i}>{inline(noTodo(l))}</div> : <div key={i}>{inline(l)}</div>)}
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function twelve(hhmm?: string) {
  if (!hhmm) return '—'
  const [h, m] = hhmm.split(':').map(Number)
  return `${h % 12 || 12}:${String(m).padStart(2, '0')} ${h < 12 ? 'am' : 'pm'}`
}

function Activity({ status, onChange, onSetup }: { status: Status | null; onChange: () => void; onSetup: () => void }) {
  const [runs, setRuns] = useState<Run[]>([])
  const [plan, setPlan] = useState<{ days?: { morning_run?: string; nightly_run?: string }[] } | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [output, setOutput] = useState('')
  const [notes, setNotes] = useState<ThreadNote[]>([])
  const [openNote, setOpenNote] = useState<string | null>(null)
  const [noteText, setNoteText] = useState('')
  useEffect(() => {
    invoke<ThreadNote[]>('thread_notes').then(setNotes)
    invoke<Run[]>('recent_runs').then(setRuns)
    invoke<typeof plan>('schedule').then(setPlan)
  }, [status?.last_job])
  const show = (f: string) => {
    if (open === f) return setOpen(null)
    setOpen(f)
    setOutput('')
    invoke<string>('read_run', { file: f }).then(setOutput)
  }
  const showNote = (id: string) => {
    if (openNote === id) return setOpenNote(null)
    setOpenNote(id)
    setNoteText('')
    invoke<string>('read_thread_note', { id }).then(setNoteText)
  }
  if (!status) return null
  const pill = !status.hosting ? ['', 'From Terminal'] : status.remote_state === 'running' ? ['ok', 'Connected'] : status.remote_state === 'error' ? ['bad', 'Not connected'] : ['warn', 'Starting']
  return (
    <div className="page">
      <div className="head">
        <div className="grow">
          <h1>Activity</h1>
          <div className="sub">What Theseus is doing, and what it did last.</div>
        </div>
        {status.hosting && (
          <button className="btn" onClick={() => invoke('set_paused', { paused: !status.paused }).then(onChange)}>
            <Icon name={status.paused ? 'play' : 'pause'} />{status.paused ? 'Resume' : 'Pause'}
          </button>
        )}
        <button className="btn" disabled={!!status.job_running} onClick={() => invoke('run_now', { kind: 'sync' }).then(onChange)}>
          <Icon name="refresh" className={status.job_running === 'sync' ? 'spin' : undefined} />Sync now
        </button>
      </div>

      {!status.hosting && (
        <div className="notice">
          <Icon name="info" />
          <div className="grow">{status.auto_host ? 'Your Terminal window and background jobs are running things for now. Theseus moves them here by itself once it has its permissions.' : 'Your Terminal window and background jobs are running things, because you handed back. You can move them here again in Setup.'}</div>
          <button className="btn" onClick={onSetup}>Open Setup</button>
        </div>
      )}

      <div className="card">
        <div className="item">
          <Icon name="phone" />
          <div className="grow"><div className="title">Remote Control</div><div className="muted small">{status.hosting ? status.remote || 'Starting…' : 'Your Mac is reachable from the Claude app while the Terminal window stays open.'}</div></div>
          <span className={`pill ${pill[0]}`}><span className="dot" />{pill[1]}</span>
        </div>
        <div className="item">
          <Icon name="clock" />
          <div className="grow"><div className="title">Briefings</div><div className="muted small">Morning at {twelve(plan?.days?.[0]?.morning_run)}, evening prep at {twelve(plan?.days?.[0]?.nightly_run)}</div></div>
        </div>
        {status.hosting && status.last_check && (
          <div className="item">
            <Icon name="activity" />
            <div className="grow"><div className="title">Last check</div><div className="muted small">{status.last_check}</div></div>
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-title">Recent runs</div>
        {runs.length === 0 && <div className="item muted">Nothing has run yet.</div>}
        {runs.map((r) => (
          <div key={r.file}>
            <button className="item click" onClick={() => show(r.file)} aria-expanded={open === r.file}>
              <Icon name="chevron" className={`chev ${open === r.file ? 'open' : ''}`} />
              <span className="grow title" style={{ textTransform: 'capitalize' }}>{r.kind}</span>
              <span className="muted small num">{r.when}</span>
            </button>
            {open === r.file && <pre className="run-out">{output || 'Loading…'}</pre>}
          </div>
        ))}
      </div>

      {notes.length > 0 && (
        <div className="card">
          <div className="card-title">Thread notes</div>
          {notes.map((n) => (
            <div key={n.id}>
              <button className="item click" onClick={() => showNote(n.id)} aria-expanded={openNote === n.id}>
                <Icon name="chevron" className={`chev ${openNote === n.id ? 'open' : ''}`} />
                <span className="grow title">{n.label}</span>
                <span className="muted small num">Updated {n.last_updated ?? 'never'} · checked {n.last_checked ?? 'never'}</span>
              </button>
              {openNote === n.id && <pre className="run-out">{noteText || 'Loading…'}</pre>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Setup({ status, onChange }: { status: Status | null; onChange: () => void }) {
  const [perms, setPerms] = useState<Permission[] | null>(null)
  const [waiting, setWaiting] = useState<string | null>(null)
  const [tested, setTested] = useState<Record<string, boolean>>({})
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [commands, setCommands] = useState<string | null>(null)
  const toggleCommands = () => {
    if (commands !== null) return setCommands(null)
    setCommands('')
    invoke<string>('read_commands').then(setCommands)
  }
  const load = useCallback(() => invoke<Permission[]>('permissions').then(setPerms), [])
  useEffect(() => {
    void load()
    // Come back from System Settings and the list is already right.
    window.addEventListener('focus', load)
    return () => window.removeEventListener('focus', load)
  }, [load])

  const request = async (id: string) => {
    setWaiting(id)
    setError('')
    try {
      await invoke('request_permission', { id })
      if (id === 'notes') setTested((t) => ({ ...t, notes: true }))
    } catch (e) {
      setError(String(e))
    }
    setWaiting(null)
    void load()
  }
  const open = (pane: string) => invoke('open_privacy', { pane })
  const host = async (cmd: 'take_over' | 'hand_back') => {
    setBusy(true)
    setError('')
    try {
      setMsg(await invoke<string>(cmd))
    } catch (e) {
      setError(String(e))
    }
    setBusy(false)
    setConfirming(false)
    onChange()
  }

  const stateOf = (p: Permission) => (tested[p.id] ? 'ok' : p.state)
  const blocking = perms?.filter((p) => stateOf(p) === 'denied' || stateOf(p) === 'ask').length ?? 0

  return (
    <div className="page">
      <div className="head"><div className="grow"><h1>Setup</h1><div className="sub">Permissions, and where Theseus runs.</div></div></div>
      {error && <div className="notice bad"><Icon name="alert" /><div>{error}</div></div>}
      {msg && <div className="notice"><Icon name="info" /><div>{msg}</div></div>}

      <div className="card">
        <div className="card-title">Permissions</div>
        {!perms && <div className="item muted">Checking…</div>}
        {perms?.map((p) => {
          const st = stateOf(p)
          return (
            <div className="item perm" key={p.id}>
              <div className="grow">
                <div className="title">{p.name}</div>
                <div className="muted small">{waiting === p.id ? 'Look for the macOS dialog and choose Allow.' : p.detail || p.why}</div>
                {st === 'denied' && (p.id === 'calendars' || p.id === 'reminders') && <div className="small" style={{ color: 'var(--warn)', marginTop: 3 }}>It's turned off. Open Settings and switch Theseus on in the list.</div>}
                {st === 'denied' && p.id === 'files' && <div className="small" style={{ color: 'var(--warn)', marginTop: 3 }}>Open Settings, click +, and choose Theseus in Applications. Then reopen Theseus.</div>}
              </div>
              {st === 'ok' && <span className="pill ok state"><Icon name="check" size={12} />{p.id === 'claude' ? 'Found' : 'Allowed'}</span>}
              {st === 'ask' && <button className="btn primary state" disabled={!!waiting} onClick={() => request(p.id)}>{waiting === p.id ? 'Waiting…' : 'Allow…'}</button>}
              {st === 'unknown' && p.id === 'notes' && <button className="btn state" disabled={!!waiting} onClick={() => request('notes')}>{waiting === 'notes' ? 'Waiting…' : 'Allow…'}</button>}
              {st === 'denied' && p.id !== 'claude' && <button className="btn state" onClick={() => open(p.id)}><Icon name="open" />Open Settings</button>}
            </div>
          )
        })}
      </div>

      {status && (
        <div className="card">
          <div className="card-title">Where Theseus runs</div>
          <div className="item perm">
            <div className="grow">
              <div className="title">{status.hosting ? 'In this app' : 'In Terminal and background jobs'}</div>
              <div className="muted small">
                {status.hosting
                  ? 'Remote Control, checks and briefings all run from here, so keep this app open. It lives in your menu bar.'
                  : status.auto_host
                    ? 'Once the permissions above are allowed, Theseus moves everything here by itself, within a minute. You don\'t need Claude or Terminal open. Nothing is deleted, and you can switch back.'
                    : 'You handed back, so this stays in Terminal until you move it here again. Nothing is deleted.'}
              </div>
              {!status.hosting && blocking > 0 && <div className="small" style={{ color: 'var(--warn)', marginTop: 3 }}>Allow the permissions above first, or briefings won't be able to read everything.</div>}
            </div>
            {confirming ? (
              <div className="row state">
                <button className="btn" onClick={() => setConfirming(false)}>Cancel</button>
                <button className="btn primary" disabled={busy} onClick={() => host(status.hosting ? 'hand_back' : 'take_over')}>{busy ? 'Switching…' : status.hosting ? 'Yes, hand back' : 'Yes, move here'}</button>
              </div>
            ) : (
              <button className={`btn state ${status.hosting ? '' : 'primary'}`} onClick={() => setConfirming(true)}>{status.hosting ? 'Hand back to Terminal…' : 'Run from this app…'}</button>
            )}
          </div>
          <div className="item perm">
            <div className="grow"><div className="title">Opening by itself</div><div className="muted small">{status.hosting ? 'Theseus opens at login and reopens after a crash. If you quit it from the menu bar, it stays closed until you open it or restart your Mac.' : 'Once it runs from this app, Theseus opens at login and reopens after a crash.'}</div></div>
          </div>
        </div>
      )}

      <div className="card">
        <button className="item click" onClick={toggleCommands} aria-expanded={commands !== null}>
          <Icon name="chevron" className={`chev ${commands !== null ? 'open' : ''}`} />
          <span className="grow title">Commands</span>
          <span className="muted small">Every command, at a glance</span>
        </button>
        {commands !== null && <pre className="run-out selectable">{commands || 'Loading…'}</pre>}
      </div>

      {status && <div className="muted small selectable">Workspace {status.workspace} · Claude Code {status.claude}</div>}
    </div>
  )
}
