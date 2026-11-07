/*
 * The screen. It reads wall.json from this Pi and draws it. It can't change your list, and it reaches nothing beyond this Pi.
 * Everything from the snapshot goes in through textContent, because titles can come from outside sources.
 */
'use strict'
const SCHEMA = 1
const STALE_MINUTES = 15
const POLL_MS = 10000
const SIZES = { S: 2.6, M: 3.2, L: 4.2, XL: 5.6 }
const TOP_SIZES = { S: 3.2, M: 4.2, L: 5.4, XL: 7, XXL: 13 }
const CLOCK_SIZES = { S: 7, M: 11, L: 15, XL: 30 }
const MINS = { top: [4, 2], list: [3, 2], sectors: [4, 2], due: [3, 2], counts: [3, 1], clock: [3, 2], note: [2, 1], status: [3, 1] }
const ICONS = {
  compass: 'M21.5 12A9.5 9.5 0 1 1 2.5 12A9.5 9.5 0 1 1 21.5 12Z M12 4.9L15.3 12L12 19.1L8.7 12Z',
  lock: 'M6 11h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1Z M8 11V7a4 4 0 0 1 8 0v4',
  away: 'M3 3l18 18 M8.5 5.6A6 6 0 0 1 17.6 10h.9a3.5 3.5 0 0 1 2 6.4 M5.6 8.1A6 6 0 0 0 6 20h11.5',
}

// For tests and checking layouts: ?now=2026-11-05T08:42:00 fixes the clock.
const FIXED_NOW = new URLSearchParams(location.search).get('now')
const now = () => (FIXED_NOW ? new Date(FIXED_NOW) : new Date())

function el(tag, cls, ...kids) {
  const e = document.createElement(tag)
  if (cls) e.className = cls
  e.append(...kids)
  return e
}
function icon(name) {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
  s.setAttribute('viewBox', '0 0 24 24')
  s.setAttribute('class', 'icon')
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path')
  p.setAttribute('d', ICONS[name])
  s.append(p)
  return s
}
function clockParts(d) {
  return [`${d.getHours() % 12 || 12}:${String(d.getMinutes()).padStart(2, '0')}`, d.getHours() < 12 ? 'am' : 'pm']
}
const longDate = (d) => d.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })

// Worked out here, from this screen's clock, so "Due today" is still true tomorrow if the Mac has been asleep.
function dueDays(i) {
  if (!i.due_date) return null
  const n = now()
  return Math.round((new Date(`${i.due_date}T00:00`) - new Date(n.getFullYear(), n.getMonth(), n.getDate())) / 86400000)
}
function dueLabel(i) {
  const d = dueDays(i)
  if (d === null) return i.due
  if (d === 0) return 'Due today'
  if (d > 0) return i.due
  return `Was due ${d >= -6 ? new Date(`${i.due_date}T00:00`).toLocaleDateString('en-US', { weekday: 'short' }) : (i.due || i.due_date)}`
}
const isLate = (i) => { const d = dueDays(i); return d !== null && d < 0 }

function itemsOf(snap, key) { return (snap.sections[key] && snap.sections[key].items) || [] }
function titleOf(snap, key) { return (snap.sections[key] && snap.sections[key].title) || key }
function pickTasks(snap, o) {
  const key = String(o.section || 'now').toLowerCase()
  let tasks = itemsOf(snap, key)
  const first = tasks[0]
  if (o.sector && o.sector !== 'All') tasks = tasks.filter((x) => x.category === o.sector)
  return o.skipTop ? tasks.filter((x) => x !== first) : tasks
}

function rowsFor(tasks, o, u) {
  const list = el('ol', 'rows')
  list.style.fontSize = `${(SIZES[o.size] || SIZES.M) * u}px`
  for (const i of tasks) {
    const row = el('li', 'row', el('span', 'r', o.rank === false ? '' : String(i.number)), el('span', 't', i.title))
    if (o.due !== false && (i.due || i.due_date)) row.append(el('span', isLate(i) ? 'd late' : 'd', dueLabel(i)))
    list.append(row)
  }
  return list
}
// Shows what fits, and says how many didn't. Text never shrinks past the size chosen for it.
function fitRows(card, list, alsoHidden) {
  const total = list.children.length + alsoHidden
  const extra = el('div', 'extra')
  const say = () => { extra.textContent = `${total - list.children.length} more` }
  if (alsoHidden) { say(); card.append(extra) }
  while (list.children.length > 1 && list.scrollHeight > list.clientHeight + 1) {
    list.lastChild.remove()
    if (!extra.parentNode) card.append(extra)
    say()
  }
}

function drawClock(body, o, u) {
  const n = now()
  const [time, ampm] = clockParts(n)
  const size = CLOCK_SIZES[o.size] || CLOCK_SIZES.L
  const clock = el('div', 'clock', time, el('small', '', ampm))
  const box = el('div', 'plain', clock)
  clock.style.fontSize = `${size * u}px`
  let date = null
  if (o.date) {
    date = el('div', 'date', longDate(n))
    date.style.fontSize = `${Math.max(2.8, size * 0.24) * u}px`
    box.append(date)
  }
  body.append(box)
  for (let s = 0.92; s > 0.15 && (box.scrollHeight > body.clientHeight + 1 || box.scrollWidth > body.clientWidth + 1); s *= 0.92) {
    clock.style.fontSize = `${size * s * u}px`
    if (date) date.style.fontSize = `${Math.max(1.8, size * s * 0.24) * u}px`
  }
}
function drawTop(body, snap, o, u) {
  const key = String(o.section || 'now').toLowerCase()
  const first = itemsOf(snap, key)[0]
  const box = el('div', 'top')
  if (first) {
    const title = el('div', 'tt', first.title)
    title.style.fontSize = `${(TOP_SIZES[o.size] || TOP_SIZES.XL) * u}px`
    const meta = el('div', 'm')
    if (first.due || first.due_date) meta.append(el('span', isLate(first) ? 'late' : '', dueLabel(first)))
    if (first.category) meta.append(el('span', '', first.category))
    box.append(el('div', 'num', String(first.number)), title, meta)
    body.append(box)
    // The top task always reads whole: it comes down until it fits the space it has.
    const size = TOP_SIZES[o.size] || TOP_SIZES.XL
    for (let s = 0.92; s > 0.25 && title.scrollHeight > title.clientHeight + 1; s *= 0.92) title.style.fontSize = `${size * s * u}px`
    return
  } else {
    const none = el('div', 'tt', `Nothing left in ${titleOf(snap, key)}.`)
    none.style.fontSize = `${(TOP_SIZES[o.size] || TOP_SIZES.XL) * u}px`
    box.append(none)
  }
  body.append(box)
}
function drawList(body, snap, o, u) {
  const key = String(o.section || 'now').toLowerCase()
  const tasks = pickTasks(snap, o)
  const name = o.label || (o.sector && o.sector !== 'All' ? o.sector : titleOf(snap, key))
  const sent = snap.sections[key] || {}
  const total = tasks.length + (o.sector && o.sector !== 'All' ? 0 : sent.more || 0)
  const list = rowsFor(tasks, o, u)
  const card = el('div', 'card', el('div', 'label', name, el('i', '', String(total))))
  if (tasks.length) card.append(list)
  else card.append(el('div', 'extra', 'Nothing here right now.'))
  body.append(card)
  if (tasks.length) fitRows(card, list, total - tasks.length)
}
function drawSectors(body, snap, o, u) {
  const groups = new Map()
  for (const i of pickTasks(snap, o)) {
    const name = i.category || 'Other'
    if (!groups.has(name)) groups.set(name, [])
    groups.get(name).push(i)
  }
  const all = [...groups]
  const box = el('div', 'sectors')
  const most = Math.max(1, Math.floor(body.clientWidth / (34 * u)))
  const fewest = Math.min(most, all.length, 3)
  body.append(box)
  const card = ([name, tasks], cap) => {
    const c = el('section', 'sector', el('div', 'label', name, el('i', '', String(tasks.length))), rowsFor(tasks.slice(0, cap), o, u))
    if (tasks.length > cap) c.append(el('div', 'extra', `${tasks.length - cap} more`))
    return c
  }
  const fits = () => box.scrollWidth <= box.clientWidth + 1 && box.scrollHeight <= box.clientHeight + 1
  // Everything fits if it can. If not, each sector gives up its lowest-ranked tasks evenly, and the lowest-ranked sectors go last of all.
  const tallest = Math.max(1, ...all.map((g) => g[1].length))
  let best = { cap: 0, columns: most }
  // Wider cards read better, so the fewest columns that show everything win.
  for (let columns = fewest; columns <= most && best.cap < tallest; columns++) {
    box.style.columns = String(columns)
    for (let cap = tallest; cap > best.cap; cap--) {
      box.replaceChildren(...all.map((g) => card(g, cap)))
      if (fits()) { best = { cap, columns }; break }
    }
  }
  box.style.columns = String(best.columns)
  if (best.cap) return box.replaceChildren(...all.map((g) => card(g, best.cap)))
  let keep = all.length
  while (keep > 1 && !fits()) box.replaceChildren(...all.slice(0, --keep).map((g) => card(g, 1)))
}
function drawDue(body, snap, o, u) {
  const seen = new Set()
  const tasks = Object.values(snap.sections).flatMap((s) => s.items || [])
    .filter((i) => dueDays(i) !== null && dueDays(i) <= (o.days || 14) && !seen.has(i.number) && seen.add(i.number))
    .sort((a, b) => dueDays(a) - dueDays(b))
  const list = rowsFor(tasks, { ...o, rank: true, due: true }, u)
  const card = el('div', 'card', el('div', 'label', o.label || 'Coming due', el('i', '', String(tasks.length))))
  if (tasks.length) card.append(list)
  else card.append(el('div', 'extra', 'Nothing with a date coming up.'))
  body.append(card)
  if (tasks.length) fitRows(card, list, 0)
}
function drawCounts(body, snap, o, u) {
  const keys = (o.sections || []).map((s) => String(s).toLowerCase()).filter((k) => snap.sections[k])
  const wide = body.clientWidth > body.clientHeight * 2.4
  if (wide) {
    const row = el('div', body.clientHeight > 7 * u ? 'counts-row big' : 'counts-row')
    for (const k of keys) row.append(el('span', '', titleOf(snap, k), el('b', '', String(snap.sections[k].open))))
    body.append(row)
    return
  }
  const rows = el('div', '')
  for (const k of keys) rows.append(el('div', 'count', titleOf(snap, k), el('b', '', String(snap.sections[k].open))))
  body.append(el('div', 'card', rows))
}
function drawStatus(body, snap) {
  const [t, ampm] = clockParts(new Date(snap.generated_at))
  const stale = (now() - new Date(snap.generated_at)) / 60000 > STALE_MINUTES
  const kept = Object.values(snap.sections).reduce((n, s) => n + (s.kept_private || 0), 0)
  const parts = [el('span', stale ? 'dot away' : 'dot'), stale ? `Last update ${t} ${ampm}` : `Up to date · ${t} ${ampm}`]
  if (kept) parts.push(` · ${kept} kept private`)
  body.append(el('div', 'status', ...parts))
}
function drawNote(body, o, u) {
  const n = el('div', 'note', String(o.text || ''))
  n.style.fontSize = `${(SIZES[o.size] || SIZES.L) * u}px`
  body.append(el('div', 'plain', n))
}
function draw(body, tile, snap, u) {
  const o = tile.opts || {}
  body.replaceChildren()
  if (tile.type === 'clock') drawClock(body, o, u)
  else if (tile.type === 'top') drawTop(body, snap, o, u)
  else if (tile.type === 'list') drawList(body, snap, o, u)
  else if (tile.type === 'sectors') drawSectors(body, snap, o, u)
  else if (tile.type === 'due') drawDue(body, snap, o, u)
  else if (tile.type === 'counts') drawCounts(body, snap, o, u)
  else if (tile.type === 'note') drawNote(body, o, u)
  else if (tile.type === 'status') drawStatus(body, snap)
}

const shape = () => (innerWidth >= innerHeight ? 'landscape' : 'portrait')
const grid = (s) => (s === 'landscape' ? { cols: 24, rows: 14 } : { cols: 14, rows: 24 })
/** A view with no portrait layout stacks its landscape pieces in order. */
function layoutOf(view) {
  const s = shape()
  if (view.layouts[s]) return view.layouts[s]
  const from = view.layouts.landscape || view.layouts.portrait || []
  const order = [...from].sort((a, b) => a.y - b.y || a.x - b.x)
  const { cols, rows } = grid(s)
  const room = rows / (order.reduce((n, x) => n + x.h, 0) || 1)
  let y = 0
  const placed = []
  for (const x of order) {
    const h = Math.max((MINS[x.type] || [1, 1])[1], Math.floor(x.h * room))
    if (y + h > rows) break
    placed.push({ ...x, x: 0, y, w: cols, h })
    y += h
  }
  return placed
}

const minutesOf = (hhmm) => { const [h, m] = String(hhmm).split(':').map(Number); return h * 60 + m }
function inWindow(from, to, t) {
  const a = minutesOf(from)
  const b = minutesOf(to)
  return a <= b ? t >= a && t < b : t >= a || t < b
}
function viewFor(snap) {
  const views = snap.views || []
  const change = snap.change || {}
  const n = now()
  const t = n.getHours() * 60 + n.getMinutes()
  const named = views.find((v) => v.name === change.active)
  if (change.mode === 'fixed') return named || views[0]
  const timed = views.find((v) => v.when && inWindow(v.when.from, v.when.to, t))
  if (timed) return timed
  const free = views.filter((v) => !v.when)
  if (!free.length) return named || views[0]
  if (change.mode === 'rotate') return free[Math.floor(n.getTime() / ((change.minutes || 5) * 60000)) % free.length]
  return free[0]
}

function whole(...kids) { return el('div', 'whole', ...kids) }
function waiting() {
  return whole(el('div', 'glyph', icon('compass')), el('h1', '', 'Waiting for your Mac.'),
    el('p', '', "Your list will appear within a few minutes of your Mac waking up. If it doesn't, run this in Terminal on your Mac:"),
    el('div', '', el('code', '', 'theseus wall status')))
}
function corner() {
  const n = now()
  const [t, ampm] = clockParts(n)
  const box = el('div', 'corner', el('div', 'clock', t, el('small', '', ampm)), el('div', 'date', longDate(n)))
  box.firstChild.style.fontSize = `calc(12 * var(--u))`
  box.lastChild.style.fontSize = `calc(3.2 * var(--u))`
  return box
}
function counts(snap) {
  const entries = Object.values(snap.sections)
  const keys = Object.keys(snap.sections)
  const main = snap.sections.now || entries[0]
  const chips = []
  if (main && main.due_today) chips.push(el('span', 'chip', `${main.due_today} due today`))
  if (main && main.was_due) chips.push(el('span', 'chip late', `${main.was_due} past its date`))
  const behind = el('div', 'behind', ...keys.filter((k) => snap.sections[k] !== main).map((k) => el('span', '', snap.sections[k].title, el('b', '', String(snap.sections[k].open)))))
  return whole(el('div', 'big-n', String(main ? main.open : 0)), el('div', 'big-of', `in ${main ? main.title : 'your list'}`), el('div', 'chips', ...chips), behind)
}

let latest = null
let drawnKey = null
function render() {
  const stage = document.getElementById('stage')
  const inner = document.getElementById('inner')
  const unit = shape() === 'landscape' ? innerHeight / 100 : innerWidth * 0.0113
  document.documentElement.style.setProperty('--u', `${unit}px`)

  const n = now()
  const d = latest && latest.display
  const dark = !!(d && d.on && d.off && !inWindow(d.on, d.off, n.getHours() * 60 + n.getMinutes()))
  const ageMinutes = latest ? (n - new Date(latest.generated_at)) / 60000 : 0
  const stale = !!latest && ageMinutes > STALE_MINUTES
  const view = latest && latest.mode === 'titles' ? viewFor(latest) : null
  const key = JSON.stringify([latest, view && view.name, dark, stale, n.getHours(), n.getMinutes(), n.toDateString(), innerWidth, innerHeight])
  if (key === drawnKey) return
  drawnKey = key

  stage.classList.toggle('dark', dark)
  stage.classList.toggle('is-stale', stale)
  inner.replaceChildren()
  if (dark) return
  if (!latest) return inner.append(waiting(), corner())
  if (latest.mode === 'counts') {
    inner.append(counts(latest), corner())
  } else if (view) {
    const { cols, rows } = grid(shape())
    for (const tile of layoutOf(view)) {
      const node = el('div', tile.type === 'clock' ? 'tile keep' : 'tile', el('div', 'body'))
      node.dataset.type = tile.type
      node.style.left = `${tile.x / cols * 100}%`
      node.style.top = `${tile.y / rows * 100}%`
      node.style.width = `${tile.w / cols * 100}%`
      node.style.height = `${tile.h / rows * 100}%`
      inner.append(node)
      draw(node.firstChild, tile, latest, unit)
    }
  } else return inner.append(waiting(), corner())
  if (stale) {
    const hours = Math.floor(ageMinutes / 60)
    const age = ageMinutes < 60 ? `${Math.round(ageMinutes)} min` : `${hours} hour${hours === 1 ? '' : 's'}`
    inner.append(el('div', 'stale-note', icon('away'), `This list is from ${age} ago. Your Mac may be asleep.`))
  }
}

function usable(snap) {
  // A newer format than this screen knows, or a piece it can't draw, shows Waiting rather than a guess.
  if (!snap || snap.schema !== SCHEMA || !snap.sections) return false
  return (snap.views || []).every((v) => Object.values(v.layouts || {}).every((l) => (l || []).every((t) => t.type in MINS)))
}
async function poll() {
  try {
    const r = await fetch('wall.json', { cache: 'no-store' })
    if (r.status === 404) latest = null
    else if (r.ok) { const snap = await r.json(); latest = usable(snap) ? snap : null }
  } catch { /* keep showing the last list; its age says the rest */ }
  render()
}
addEventListener('resize', render)
poll()
setInterval(poll, POLL_MS)
setInterval(render, 5000)
