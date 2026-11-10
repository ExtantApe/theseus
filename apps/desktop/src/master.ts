/**
 * The master list, data/master.md, as data. Every change in the app is a pure function from text to text, so the list view, the
 * Markdown view and undo all work on the same thing, and lines the app doesn't understand stay exactly as they were.
 */
export type Chip = { kind: 'category' | 'due' | 'size' | 'impact' | 'reminder' | 'repeat' | 'skylight' | 'link' | 'done' | 'note'; text: string }
export type Item = { kind: 'item'; key: string; done: boolean; title: string; id: string | null; chips: Chip[]; repeating: boolean; doneForNow: boolean; line: string; children: string[] }
export type TextBlock = { kind: 'text'; line: string }
export type Section = { key: string; heading: string; title: string; blocks: (Item | TextBlock)[] }
export type Doc = { head: string[]; sections: Section[] }

const ITEM = /^- \[( |x|X)\] (.*)$/
const SEP = ' · '
const IMPACT = /^impact:(high|low)\*?$/

/** Section title without its leading emoji or its ": explanation". */
export function sectionTitle(heading: string) {
  return heading.replace(/^##\s*/, '').replace(/^[^\p{L}\p{N}]+/u, '').split(':')[0].trim()
}
export const sectionKey = (heading: string) => sectionTitle(heading).toLowerCase()

function chipsOf(parts: string[]): { chips: Chip[]; id: string | null; doneForNow: boolean; repeating: boolean } {
  const chips: Chip[] = []
  let id: string | null = null
  let doneForNow = false
  let repeating = false
  for (const raw of parts) {
    const seg = raw.trim()
    if (seg.startsWith('id:')) id = seg.slice(3)
    else if (seg.startsWith('was:')) continue // where a done item came from, for reopening
    else if (seg.startsWith('#')) chips.push({ kind: 'category', text: seg.slice(1) })
    else if (/^due\b/.test(seg)) chips.push({ kind: 'due', text: seg.slice(3).trim() })
    else if (/^~\d/.test(seg)) chips.push({ kind: 'size', text: seg.slice(1) })
    else if (IMPACT.test(seg)) chips.push({ kind: 'impact', text: seg.slice(7) }) // "high", or "high*" when the user set it
    else if (/^done for now\b/.test(seg)) doneForNow = true
    else if (/^done\b/.test(seg)) chips.push({ kind: 'done', text: seg.slice(4).trim() })
    else if (seg.startsWith('↻')) { repeating = true; chips.push({ kind: 'repeat', text: seg.slice(1).trim() }) }
    else if (seg.startsWith('↗')) chips.push({ kind: 'link', text: seg.slice(1).trim() })
    else {
      // "⏰ 🏠" can share a segment.
      const rest = seg.replace(/⏰/g, () => { chips.push({ kind: 'reminder', text: '' }); return '' }).replace(/🏠/g, () => { chips.push({ kind: 'skylight', text: '' }); return '' }).trim()
      if (rest) chips.push({ kind: 'note', text: rest })
    }
  }
  return { chips, id, doneForNow, repeating }
}

function parseItem(line: string, children: string[], occurrence = 1): Item {
  const m = line.match(ITEM)!
  const [title, ...rest] = m[2].split(SEP)
  const { chips, id, doneForNow, repeating } = chipsOf(rest)
  // Items the engine hasn't given an id yet are known by title. Two with the same title stay two different items.
  const named = `title:${title.trim()}`
  return { kind: 'item', key: id ?? (occurrence > 1 ? `${named}#${occurrence}` : named), done: m[1] !== ' ', title: title.trim(), id, chips, repeating, doneForNow, line, children }
}

export function parse(md: string): Doc {
  const lines = md.split('\n')
  const doc: Doc = { head: [], sections: [] }
  let cur: Section | null = null
  const seen = new Map<string, number>()
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (line.startsWith('## ')) {
      cur = { key: sectionKey(line), heading: line, title: sectionTitle(line), blocks: [] }
      doc.sections.push(cur)
    } else if (!cur) {
      doc.head.push(line)
    } else if (ITEM.test(line)) {
      const children: string[] = []
      while (i + 1 < lines.length && /^\s+\S/.test(lines[i + 1])) children.push(lines[++i])
      const title = line.match(ITEM)![2].split(SEP)[0].trim()
      seen.set(title, (seen.get(title) ?? 0) + 1)
      cur.blocks.push(parseItem(line, children, seen.get(title)))
    } else {
      cur.blocks.push({ kind: 'text', line })
    }
  }
  return doc
}

export function serialize(doc: Doc) {
  const out = [...doc.head]
  for (const s of doc.sections) {
    out.push(s.heading)
    for (const b of s.blocks) {
      out.push(b.line)
      if (b.kind === 'item') out.push(...b.children)
    }
  }
  return out.join('\n')
}

export const items = (s: Section | undefined) => (s ? s.blocks.filter((b): b is Item => b.kind === 'item') : [])
export const findSection = (doc: Doc, key: string) => doc.sections.find((s) => s.key === key)

// The engine treats section names as the user's own, so the app finds these by what they're for, not one exact word.
export const isDoneKey = (key: string) => /^(done|completed?|finished)\b/.test(key)
export const doneSection = (doc: Doc) => doc.sections.find((s) => isDoneKey(s.key))
export const commsSection = (doc: Doc) => doc.sections.find((s) => /^(comm|messages?\b|replies\b|people\b)/.test(s.key))
/** The section at the top of the day: NOW, or if it's been renamed, the first one that isn't Communication or Done. */
export const nowSection = (doc: Doc) => findSection(doc, 'now') ?? doc.sections.find((s) => !isDoneKey(s.key) && s !== commsSection(doc))
export function findItem(doc: Doc, key: string) {
  for (const s of doc.sections) {
    const it = items(s).find((i) => i.key === key)
    if (it) return { section: s, item: it }
  }
  return null
}

function take(doc: Doc, key: string) {
  const hit = findItem(doc, key)
  if (!hit) return null
  hit.section.blocks.splice(hit.section.blocks.indexOf(hit.item), 1)
  return hit
}

/** Goes before `before`, or after the section's last item, ahead of any trailing blank lines. */
function place(section: Section, item: Item, before: string | null) {
  if (before) {
    const at = section.blocks.findIndex((b) => b.kind === 'item' && b.key === before)
    if (at >= 0) return void section.blocks.splice(at, 0, item)
  }
  let at = section.blocks.length
  while (at > 0 && section.blocks[at - 1].kind === 'text' && !(section.blocks[at - 1] as TextBlock).line.trim()) at--
  section.blocks.splice(at, 0, item)
}

function placeTop(section: Section, item: Item) {
  const first = section.blocks.findIndex((b) => b.kind === 'item')
  if (first >= 0) section.blocks.splice(first, 0, item)
  else place(section, item, null)
}

function setLine(item: Item, fn: (mark: string, parts: string[]) => [string, string[]]) {
  const m = item.line.match(ITEM)!
  const [mark, parts] = fn(m[1], m[2].split(SEP))
  const next = parseItem(`- [${mark}] ${parts.join(SEP)}`, item.children)
  const key = item.key
  Object.assign(item, next, { key }) // still the same item to anything holding on to it
}

/** Add a segment just before the id, where the engine keeps its notes. */
function withSegment(parts: string[], seg: string) {
  const at = parts.findIndex((p) => p.trim().startsWith('id:'))
  return at < 0 ? [...parts, seg] : [...parts.slice(0, at), seg, ...parts.slice(at)]
}

const today = (d: Date) => `${d.getMonth() + 1}/${d.getDate()}`

export function moveItem(md: string, key: string, toSection: string, before: string | null) {
  const doc = parse(md)
  const to = findSection(doc, toSection)
  if (!to || key === before) return md
  const hit = take(doc, key)
  if (!hit) return md
  place(to, hit.item, before)
  return serialize(doc)
}

/** Check it off. A repeating item stays put, marked done for now, because the engine advances it to its next date. */
export function complete(md: string, key: string, on = new Date()) {
  const doc = parse(md)
  const hit = findItem(doc, key)
  if (!hit) return md
  if (hit.item.repeating) {
    setLine(hit.item, (mark, parts) => [mark, withSegment(parts, `done for now ${today(on)}`)])
    return serialize(doc)
  }
  const from = hit.section.key
  let done = doneSection(doc)
  if (!done) {
    done = { key: 'done', heading: '## ✅ DONE', title: 'DONE', blocks: [] }
    doc.sections.push(done)
  }
  hit.section.blocks.splice(hit.section.blocks.indexOf(hit.item), 1)
  setLine(hit.item, (_, parts) => ['x', withSegment(withSegment(parts, `done ${today(on)}`), `was:${from.replace(/ /g, '-')}`)])
  placeTop(done, hit.item)
  return serialize(doc)
}

/** Back to the section it was checked off from, if that's still there; otherwise the top of the day. */
export function reopen(md: string, key: string) {
  const doc = parse(md)
  const hit = findItem(doc, key)
  if (!hit) return md
  const clear = (parts: string[]) => parts.filter((p) => !/^(done\b|was:)/.test(p.trim()))
  const was = hit.item.line.split(SEP).map((p) => p.trim()).find((p) => p.startsWith('was:'))?.slice(4).replace(/-/g, ' ')
  if (hit.item.doneForNow) {
    setLine(hit.item, (mark, parts) => [mark, clear(parts)])
    return serialize(doc)
  }
  hit.section.blocks.splice(hit.section.blocks.indexOf(hit.item), 1)
  setLine(hit.item, (_, parts) => [' ', clear(parts)])
  placeTop((was ? findSection(doc, was) : undefined) ?? nowSection(doc) ?? hit.section, hit.item)
  return serialize(doc)
}

export function editTitle(md: string, key: string, title: string) {
  const clean = title.replace(/\s*·\s*/g, ' - ').replace(/\n/g, ' ').trim()
  if (!clean) return md
  const doc = parse(md)
  const hit = findItem(doc, key)
  if (!hit) return md
  setLine(hit.item, (mark, parts) => [mark, [clean, ...parts.slice(1)]])
  return serialize(doc)
}

/**
 * The user's own impact rating, written `impact:high*`: the star means the user chose it, so Claude never changes it.
 * null takes the rating off, and then Claude may suggest one again.
 */
export function setImpact(md: string, key: string, level: 'high' | 'low' | null) {
  const doc = parse(md)
  const hit = findItem(doc, key)
  if (!hit) return md
  setLine(hit.item, (mark, parts) => {
    const rest = parts.filter((p, i) => i === 0 || !IMPACT.test(p.trim()))
    return [mark, level ? withSegment(rest, `impact:${level}*`) : rest]
  })
  return serialize(doc)
}

/** Moves an item to another category. Its place in the list stays the same. */
export function setCategory(md: string, key: string, category: string) {
  const clean = category.replace(/^#/, '').replace(/[^\p{L}\p{N}_-]/gu, '')
  const doc = parse(md)
  const hit = findItem(doc, key)
  if (!clean || !hit) return md
  setLine(hit.item, (mark, parts) => {
    const at = parts.findIndex((p, i) => i > 0 && p.trim().startsWith('#'))
    if (at < 0) return [mark, [parts[0], `#${clean}`, ...parts.slice(1)]]
    return [mark, parts.map((p, i) => (i === at ? `#${clean}` : p))]
  })
  return serialize(doc)
}

/** A new item has no id or a real category yet; the next sync gives it both. */
export function addItem(md: string, sectionK: string, title: string) {
  const clean = title.replace(/\s*·\s*/g, ' - ').replace(/\n/g, ' ').trim()
  const doc = parse(md)
  const s = findSection(doc, sectionK)
  if (!clean || !s) return md
  place(s, parseItem(`- [ ] ${clean} · #Inbox`, []), null)
  return serialize(doc)
}

/**
 * What changed between two versions of the list, for the Markdown view: typing there is the same as doing it in the list, so the next sync
 * has to hear about it. Order within a section isn't reported, because typing doesn't say which of two lines moved.
 */
export function diffEvents(before: string, after: string) {
  const index = (md: string) => {
    const m = new Map<string, { item: Item; section: string }>()
    for (const s of parse(md).sections) for (const it of items(s)) m.set(it.key, { item: it, section: s.key })
    return m
  }
  const was = index(before)
  const now = index(after)
  const events: Record<string, unknown>[] = []
  for (const [key, { item, section }] of now) {
    const old = was.get(key)
    if (!old) {
      events.push({ action: 'add', id: item.id, title: item.title, to: section })
      continue
    }
    const finished = (i: Item) => i.done || i.doneForNow
    if (!finished(old.item) && finished(item)) events.push({ action: 'complete', id: item.id, title: item.title, repeating: item.repeating })
    else if (finished(old.item) && !finished(item)) events.push({ action: 'reopen', id: item.id, title: item.title })
    if (old.section !== section && !isDoneKey(section) && !isDoneKey(old.section)) events.push({ action: 'move', id: item.id, title: item.title, from: old.section, to: section })
    if (old.item.title !== item.title) events.push({ action: 'edit', id: item.id, title: item.title, was: old.item.title })
  }
  for (const [key, { item }] of was) if (!now.has(key)) events.push({ action: 'remove', id: item.id, title: item.title })
  return events
}

/** Emoji are for the phone note, where icons aren't possible. On screen, icons do that job. Check marks and arrows stay. */
export const dropEmoji = (s: string) =>
  s.replace(/[\u{1F000}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{2712}\u{2715}-\u{27BF}\u{2B50}\u{23E9}-\u{23FA}\u{231A}\u{231B}][\u{FE0F}\u{200D}]*/gu, '').replace(/\s{2,}/g, ' ').trim()
