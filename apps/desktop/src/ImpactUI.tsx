import { useCallback, useEffect, useMemo, useState } from 'react'

import { buckets, type Candidate, dayKey, type DayState, focus, freshDay, NO_CATEGORY, slots, type Level } from './focus'
import type { ListActions } from './ListUI'
import { dropEmoji, findItem, type Item, setCategory, setImpact } from './master'
import { Icon } from './ui/Icon'
import { startRowDrag } from './ui/useDrag'
import type { Master } from './useMaster'

/** Small view settings that only this window needs. Nothing here is the list itself, which stays in data/master.md. */
function useStored<T>(key: string, initial: T) {
  const [v, setV] = useState<T>(() => {
    try { const s = localStorage.getItem(key); return s ? (JSON.parse(s) as T) : initial } catch { return initial }
  })
  const set = useCallback((next: T | ((old: T) => T)) => {
    setV((old) => {
      const value = typeof next === 'function' ? (next as (o: T) => T)(old) : next
      try { localStorage.setItem(key, JSON.stringify(value)) } catch { /* it's only a convenience */ }
      return value
    })
  }, [key])
  return [v, set] as const
}

const GROUP = 'impact:'
const label = (cat: string) => (cat === NO_CATEGORY ? 'No category' : cat)

function ImpactPicker({ c, m }: { c: Candidate; m: Master }) {
  const pick = (level: Level) => {
    // Clicking your own choice again takes it off, so Claude can suggest one again.
    const next = c.mine && c.impact === level ? null : level
    m.apply((md) => setImpact(md, c.item.key, next))
  }
  const suggested = c.impact !== null && !c.mine
  return (
    <span className={`impact ${suggested ? 'suggested' : ''}`} role="group" aria-label={`Impact of ${c.item.title}${suggested ? ', suggested by Claude' : ''}`} data-no-drag>
      {(['high', 'low'] as const).map((l) => (
        <button key={l} aria-pressed={c.impact === l} title={suggested && c.impact === l ? 'Suggested by Claude. Click to make it yours.' : c.mine && c.impact === l ? 'Your rating. Click again to take it off.' : `Rate ${l} impact`} onClick={() => pick(l)}>
          {l === 'high' ? 'High' : 'Low'}
        </button>
      ))}
    </span>
  )
}

function Meta({ c }: { c: Candidate }) {
  const due = c.item.chips.find((x) => x.kind === 'due')
  const size = c.item.chips.find((x) => x.kind === 'size')
  return (
    <span className="impact-meta muted small">
      {size ? <span title="Effort, from the size estimate">{size.text}{c.effort ? ` · ${c.effort} effort` : ''}</span> : <span title="No size estimate yet, so effort is unknown">effort ?</span>}
      {due && <span><Icon name="clock" size={11} /> {dropEmoji(due.text)}</span>}
    </span>
  )
}

function OpenRow({ c, at, cat, cats, m, a, onCheck, onMove, inFocus }: {
  c: Candidate; at: number; cat: string; cats: string[]; m: Master; a: ListActions
  onCheck: (c: Candidate, at: number) => void; onMove: (c: Candidate, to: string) => void; inFocus?: boolean
}) {
  const inGrace = a.waiting.has(c.item.key)
  return (
    <div
      className={`task impact-row ${inGrace ? 'grace' : ''}`}
      data-drag-id={inFocus ? undefined : c.item.key}
      onPointerDown={inFocus ? undefined : (e) => startRowDrag(e, c.item.key, dropEmoji(c.item.title), (t) => onMove(c, t.group === `${GROUP}${cat}` ? `before:${t.before ?? ''}` : t.group.slice(GROUP.length)))}
    >
      {!inFocus && <span className="grip" aria-hidden="true"><Icon name="grip" size={14} /></span>}
      <button className={`check ${inGrace ? 'on' : ''}`} role="checkbox" aria-checked={inGrace} aria-label={`${inGrace ? 'Uncheck' : 'Check off'} ${c.item.title}`} onClick={() => onCheck(c, at)}>
        {inGrace && <Icon name="check" size={12} strokeWidth={2.5} />}
      </button>
      <div className="task-body">
        <div className="task-line">
          <span className="task-title">{dropEmoji(c.item.title)}</span>
          {inFocus && <span className="chip chip-category">{label(cat)}</span>}
        </div>
        <div className="impact-line">
          <ImpactPicker c={c} m={m} />
          <Meta c={c} />
        </div>
      </div>
      {!inFocus && !inGrace && (
        <select className="move-to" aria-label={`Move ${c.item.title}`} value="" data-no-drag onChange={(e) => { if (e.target.value) onMove(c, e.target.value) }}>
          <option value="">Move…</option>
          <option value="up">Up</option>
          <option value="down">Down</option>
          <optgroup label="To project">
            {cats.filter((x) => x !== cat && x !== NO_CATEGORY).map((x) => <option key={x} value={x}>{x}</option>)}
          </optgroup>
        </select>
      )}
      {inGrace && <button className="btn quiet undo-now" onClick={() => onCheck(c, at)}>Undo</button>}
    </div>
  )
}

function DoneRow({ item, a, onReopen }: { item: Item | null; a: ListActions; onReopen: () => void }) {
  if (!item) return null
  return (
    <div className="task impact-row is-done">
      <button className="check on" role="checkbox" aria-checked aria-label={`Uncheck ${item.title}`} onClick={() => { onReopen(); a.toggle(item) }}>
        <Icon name="check" size={12} strokeWidth={2.5} />
      </button>
      <div className="task-body">
        <div className="task-line"><span className="task-title">{dropEmoji(item.title)}</span><span className="chip chip-done"><Icon name="check" size={12} />Completed</span></div>
      </div>
    </div>
  )
}

/**
 * Another way to see the same list: one bucket per category, its best five first by impact and effort, and Focus in front with the top
 * item of every bucket. Checking off, rating impact and moving to another category change data/master.md like everything else in the app.
 * The order you drag here is this view's own, and doesn't change the List view.
 */
export function ImpactView({ m, a }: { m: Master; a: ListActions }) {
  const [order, setOrder] = useStored<Record<string, string[]>>('theseus.impact.order', {})
  const [hidden, setHidden] = useStored<string[]>('theseus.impact.hidden', [])
  const [pinned, setPinned] = useStored<string[]>('theseus.impact.pinned', [])
  const [day, setDay] = useStored<DayState>('theseus.impact.day', freshDay(new Date()))
  const [now, setNow] = useState(() => new Date())
  useEffect(() => { const t = window.setInterval(() => setNow(new Date()), 60_000); return () => window.clearInterval(t) }, [])
  const today = day.day === dayKey(now) ? day : freshDay(now)

  const all = useMemo(() => (m.doc ? buckets(m.doc, order) : new Map<string, Candidate[]>()), [m.doc, order])
  const cats = useMemo(() => {
    const list = [...all.keys()]
    return [...list.filter((c) => pinned.includes(c)).sort((x, y) => pinned.indexOf(x) - pinned.indexOf(y)), ...list.filter((c) => !pinned.includes(c))]
  }, [all, pinned])
  const shown = cats.filter((c) => !hidden.includes(c))
  const top = useMemo(() => focus(new Map(shown.map((c) => [c, all.get(c)!])), now), [all, shown, now])
  const find = useCallback((key: string) => (m.doc ? findItem(m.doc, key)?.item ?? null : null), [m.doc])

  const update = (fn: (d: DayState) => DayState) => setDay(() => fn(day.day === dayKey(now) ? day : freshDay(now)))
  const onCheck = (cat: string) => (c: Candidate, at: number) => {
    const key = c.item.key
    if (a.waiting.has(key)) update((d) => ({ ...d, done: { ...d.done, [cat]: (d.done[cat] ?? []).filter((f) => f.key !== key) } }))
    else update((d) => ({ ...d, done: { ...d.done, [cat]: [...(d.done[cat] ?? []).filter((f) => f.key !== key), { key, at }] } }))
    a.toggle(c.item)
  }
  const onReopen = (cat: string, key: string) => update((d) => ({ ...d, done: { ...d.done, [cat]: (d.done[cat] ?? []).filter((f) => f.key !== key) } }))
  const addNext = (cat: string) => update((d) => ({ ...d, added: { ...d.added, [cat]: (d.added[cat] ?? 0) + 1 } }))

  const onMove = (cat: string, visible: string[]) => (c: Candidate, to: string) => {
    const key = c.item.key
    let next: string[] | null = null
    const rest = visible.filter((k) => k !== key)
    if (to === 'up' || to === 'down') {
      const i = visible.indexOf(key)
      const j = to === 'up' ? i - 1 : i + 1
      if (i < 0 || j < 0 || j >= visible.length) return
      next = [...visible]
      ;[next[i], next[j]] = [next[j], next[i]]
    } else if (to.startsWith('before:')) {
      const before = to.slice(7)
      const at = before ? rest.indexOf(before) : rest.length
      next = [...rest.slice(0, at < 0 ? rest.length : at), key, ...rest.slice(at < 0 ? rest.length : at)]
    } else {
      // Another bucket: the item's category changes, everywhere.
      m.apply((md) => setCategory(md, key, to))
      setOrder((o) => ({ ...o, [cat]: (o[cat] ?? []).filter((k) => k !== key) }))
      return
    }
    setOrder((o) => ({ ...o, [cat]: next! }))
  }

  if (!m.doc) return null
  return (
    <div className="impact-board">
      <div className="card block impact-focus">
        <div className="block-head"><Icon name="flame" className="block-icon" /><span className="block-name">Focus</span><span className="muted num small">{top.length}</span></div>
        <div className="impact-hint muted small">The top item from each project, most imperative first.</div>
        {top.map((c) => <OpenRow key={c.item.key} c={c} at={0} cat={c.category} cats={cats} m={m} a={a} onCheck={onCheck(c.category)} onMove={() => {}} inFocus />)}
        {top.length === 0 && <div className="block-empty muted small">Nothing open.</div>}
      </div>
      {shown.map((cat) => {
        const list = all.get(cat)!
        const openKeys = new Set(list.map((c) => c.item.key))
        const finished = (today.done[cat] ?? []).filter((f) => !openKeys.has(f.key) && find(f.key)?.done)
        const { rows, next } = slots(list, finished, Math.min(today.added[cat] ?? 0, finished.length), find)
        const visible = rows.flatMap((r) => (r.kind === 'open' ? [r.c.item.key] : []))
        const move = onMove(cat, visible)
        let at = -1
        return (
          <div key={cat} className="card block" data-drop-group={`${GROUP}${cat}`}>
            <div className="block-head">
              <Icon name="tag" className="block-icon" />
              <span className="block-name">{label(cat)}</span>
              <span className="muted num small">{list.length}</span>
              <span className="grow" />
              {order[cat]?.length ? <button className="btn quiet tiny" onClick={() => setOrder((o) => { const n = { ...o }; delete n[cat]; return n })} title="Go back to the impact and effort order">Reset order</button> : null}
              <button className="btn quiet tiny" aria-pressed={pinned.includes(cat)} onClick={() => setPinned((p) => (p.includes(cat) ? p.filter((x) => x !== cat) : [...p, cat]))}>{pinned.includes(cat) ? 'Unpin' : 'Pin'}</button>
              <button className="btn quiet tiny" onClick={() => setHidden((h) => [...h, cat])}>Hide</button>
            </div>
            {rows.map((r) => {
              at++
              return r.kind === 'open'
                ? <OpenRow key={r.c.item.key} c={r.c} at={at} cat={cat} cats={cats} m={m} a={a} onCheck={onCheck(cat)} onMove={move} />
                : <DoneRow key={`done:${r.key}`} item={r.item} a={a} onReopen={() => onReopen(cat, r.key)} />
            })}
            {next && (
              <div className="impact-next">
                <span className="muted small">Add the next one?</span>
                <span className="grow">{dropEmoji(next.item.title)}</span>
                <button className="btn tiny" onClick={() => addNext(cat)}>Add</button>
              </div>
            )}
            {list.length > visible.length && <div className="impact-more muted small">{list.length - visible.length} more in {label(cat)}</div>}
          </div>
        )
      })}
      {hidden.length > 0 && (
        <div className="impact-hidden muted small">
          Hidden: {hidden.map((h) => <button key={h} className="btn quiet tiny" onClick={() => setHidden((x) => x.filter((y) => y !== h))}>Show {label(h)}</button>)}
        </div>
      )}
    </div>
  )
}
