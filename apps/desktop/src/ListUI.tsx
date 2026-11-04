import { type KeyboardEvent, useCallback, useEffect, useRef, useState } from 'react'

import { addItem, type Chip, complete, dropEmoji, editTitle, findItem, type Item, items, moveItem, parse, reopen, type Section } from './master'
import { Icon, type IconName } from './ui/Icon'
import { startRowDrag } from './ui/useDrag'
import type { Master } from './useMaster'

export const GRACE_MS = 3000

const SECTION_ICONS: Record<string, IconName> = { now: 'flame', communications: 'message', next: 'skipForward', later: 'calendar', eventually: 'lightbulb', 'figure out': 'puzzle', 'waiting on': 'hourglass', projects: 'folder', done: 'circleCheck' }
export const sectionIcon = (key: string): IconName => SECTION_ICONS[key] ?? 'list'
export function sectionName(key: string, title: string) {
  if (key === 'communications') return 'Communication'
  return title.charAt(0).toUpperCase() + title.slice(1).toLowerCase()
}

/** Everything that acts on the list, shared by Today and List, so a check started on one survives moving to the other. */
export function useListActions(m: Master) {
  const [waiting, setWaiting] = useState<Set<string>>(new Set())
  const [toast, setToast] = useState('')
  const timers = useRef(new Map<string, number>())
  const toastTimer = useRef(0)
  const say = useCallback((t: string) => {
    setToast(t)
    window.clearTimeout(toastTimer.current)
    toastTimer.current = window.setTimeout(() => setToast(''), 6000)
  }, [])

  const toggle = useCallback((it: Item) => {
    const id = it.key
    if (timers.current.has(id)) {
      // A second click inside the grace period: nothing happened.
      window.clearTimeout(timers.current.get(id))
      timers.current.delete(id)
      setWaiting((w) => { const n = new Set(w); n.delete(id); return n })
      return
    }
    if (it.done || it.doneForNow) {
      m.apply((md) => reopen(md, id), { action: 'reopen', id: it.id, title: it.title })
      return
    }
    setWaiting((w) => new Set(w).add(id))
    timers.current.set(id, window.setTimeout(() => {
      timers.current.delete(id)
      setWaiting((w) => { const n = new Set(w); n.delete(id); return n })
      m.apply((md) => complete(md, id), { action: 'complete', id: it.id, title: it.title, repeating: it.repeating })
      say(it.repeating ? `${dropEmoji(it.title)}: done for now` : `${dropEmoji(it.title)} moved to Done`)
    }, GRACE_MS))
  }, [m, say])

  const move = useCallback((id: string, to: string, before: string | null) => {
    m.apply((md) => moveItem(md, id, to, before), (was) => {
      const hit = findItem(parse(was), id)
      return { action: 'move', id: hit?.item.id, title: hit?.item.title, from: hit?.section.key, to, above: before }
    })
  }, [m])

  return { waiting, toast, clearToast: () => setToast(''), toggle, move }
}
export type ListActions = ReturnType<typeof useListActions>

function ChipView({ c }: { c: Chip }) {
  const icon: Partial<Record<Chip['kind'], IconName>> = { due: 'clock', reminder: 'bell', repeat: 'repeat', skylight: 'house', link: 'link', done: 'check' }
  const label: Partial<Record<Chip['kind'], string>> = { reminder: 'Has a reminder', skylight: 'On Skylight' }
  const name = icon[c.kind]
  return (
    <span className={`chip chip-${c.kind}`} title={label[c.kind]}>
      {name && <Icon name={name} size={12} />}
      {c.text && <span>{dropEmoji(c.text)}</span>}
    </span>
  )
}

export function Row({ it, section, m, a, siblings }: { it: Item; section: Section; m: Master; a: ListActions; siblings: Item[] }) {
  const [editing, setEditing] = useState(false)
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState('')
  const inGrace = a.waiting.has(it.key)
  const checked = it.done || it.doneForNow || inGrace
  const startEdit = () => { setDraft(it.title); setEditing(true) }
  const commit = () => {
    setEditing(false)
    if (draft.trim() && draft.trim() !== it.title) m.apply((md) => editTitle(md, it.key, draft), { action: 'edit', id: it.id, title: draft.trim(), was: it.title })
  }
  const keys = (e: KeyboardEvent) => {
    if (editing || e.target !== e.currentTarget) return
    const at = siblings.indexOf(it)
    if (e.key === 'Enter') { e.preventDefault(); startEdit() }
    else if (e.altKey && e.key === 'ArrowUp' && at > 0) { e.preventDefault(); a.move(it.key, section.key, siblings[at - 1].key) }
    else if (e.altKey && e.key === 'ArrowDown' && at < siblings.length - 1) { e.preventDefault(); a.move(it.key, section.key, siblings[at + 2]?.key ?? null) }
  }
  return (
    <div
      className={`task ${inGrace ? 'grace' : ''} ${it.done ? 'is-done' : ''}`}
      data-drag-id={it.key}
      tabIndex={0}
      onKeyDown={keys}
      onPointerDown={(e) => { if (!editing) startRowDrag(e, it.key, dropEmoji(it.title), (t) => a.move(it.key, t.group, t.before)) }}
    >
      <span className="grip" aria-hidden="true"><Icon name="grip" size={14} /></span>
      <button className={`check ${checked ? 'on' : ''}`} role="checkbox" aria-checked={checked} aria-label={`${checked ? 'Uncheck' : 'Check off'} ${it.title}`} onClick={() => a.toggle(it)}>
        {checked && <Icon name="check" size={12} strokeWidth={2.5} />}
      </button>
      <div className="task-body">
        <div className="task-line">
          {editing
            ? <input type="text" autoFocus value={draft} aria-label="Edit item" onChange={(e) => setDraft(e.target.value)} onBlur={commit} onKeyDown={(e) => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') setEditing(false) }} />
            : <span className="task-title" onDoubleClick={startEdit}>{dropEmoji(it.title)}</span>}
          {!editing && it.chips.map((c, i) => <ChipView key={i} c={c} />)}
          {it.doneForNow && <span className="chip chip-done"><Icon name="check" size={12} />Done for now</span>}
        </div>
        {open && <div className="task-notes selectable">{it.children.map((c, i) => <div key={i}>{dropEmoji(c.replace(/^\s*-\s*/, ''))}</div>)}</div>}
        {inGrace && <div className="grace-bar" style={{ animationDuration: `${GRACE_MS}ms` }} />}
      </div>
      {inGrace && <button className="btn quiet undo-now" onClick={() => a.toggle(it)}>Undo</button>}
      {!inGrace && it.children.length > 0 && (
        <button className="btn quiet icon task-more" aria-expanded={open} aria-label={open ? 'Hide notes' : 'Show notes'} onClick={() => setOpen(!open)}>
          <Icon name="chevron" className={`chev ${open ? 'open' : ''}`} />
        </button>
      )}
    </div>
  )
}

function AddRow({ section, m }: { section: Section; m: Master }) {
  const [on, setOn] = useState(false)
  const [v, setV] = useState('')
  const submit = () => {
    if (v.trim()) m.apply((md) => addItem(md, section.key, v), { action: 'add', title: v.trim(), to: section.key })
    setV('')
  }
  if (!on) return <button className="add" onClick={() => setOn(true)}><Icon name="plus" size={14} />Add</button>
  return (
    <div className="add-input">
      <input type="text" autoFocus value={v} placeholder="New item" aria-label={`Add to ${section.title}`} onChange={(e) => setV(e.target.value)} onBlur={() => { submit(); setOn(false) }} onKeyDown={(e) => { if (e.key === 'Enter') submit(); if (e.key === 'Escape') { setV(''); setOn(false) } }} />
    </div>
  )
}

/** One section of the list as a block: a header, its rows, and somewhere to add. */
export function Block({ section, m, a, footer, collapsible, defaultOpen = true, name }: { section: Section; m: Master; a: ListActions; footer?: React.ReactNode; collapsible?: boolean; defaultOpen?: boolean; name?: string }) {
  const storeKey = `theseus.open.${section.key}`
  const [open, setOpen] = useState(() => {
    try { return (localStorage.getItem(storeKey) ?? (defaultOpen ? '1' : '0')) === '1' } catch { return defaultOpen }
  })
  useEffect(() => { try { localStorage.setItem(storeKey, open ? '1' : '0') } catch { /* it's only a convenience */ } }, [open, storeKey])
  const list = items(section)
  const isOpen = !collapsible || open
  const head = (
    <>
      <Icon name={sectionIcon(section.key)} className="block-icon" />
      <span className="block-name">{name ?? sectionName(section.key, section.title)}</span>
      <span className="muted num small">{list.length}</span>
    </>
  )
  return (
    <div className="card block" data-drop-group={section.key}>
      {collapsible
        ? <button className="block-head click" aria-expanded={open} onClick={() => setOpen(!open)}>{head}<span className="grow" /><Icon name="chevron" className={`chev ${open ? 'open' : ''}`} /></button>
        : <div className="block-head">{head}</div>}
      {isOpen && (
        <>
          {list.map((it) => <Row key={it.key} it={it} section={section} m={m} a={a} siblings={list} />)}
          {list.length === 0 && <div className="block-empty muted small">Nothing here. Drag something in, or add it.</div>}
          {section.key !== 'done' && <AddRow section={section} m={m} />}
          {footer}
        </>
      )}
    </div>
  )
}

/** Undo, redo and whether it's saved. The same on every screen that edits the list. */
export function ListTools({ m }: { m: Master }) {
  return (
    <div className="row list-tools">
      <span className="muted small save-state">
        {m.save === 'saved' && <><Icon name="check" size={12} />Saved</>}
        {m.save === 'saving' && 'Saving…'}
        {m.save === 'error' && <span style={{ color: 'var(--bad)' }}>Not saved</span>}
      </span>
      <button className="btn icon" disabled={!m.canUndo} onClick={m.undo} aria-label="Undo" data-tip="Undo (⌘Z)"><Icon name="undo" /></button>
      <button className="btn icon" disabled={!m.canRedo} onClick={m.redo} aria-label="Redo" data-tip="Redo (⇧⌘Z)"><Icon name="redo" /></button>
    </div>
  )
}
