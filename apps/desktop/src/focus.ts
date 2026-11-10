/**
 * The impact view: one bucket per category, best first by impact and effort, and a Focus column with each bucket's top item.
 * Impact is the item's own `impact:` field. Effort comes from its size estimate (`~15m`), so there's nothing extra to keep up.
 * Pure functions over the parsed list, so the screen and the tests see the same order.
 */
import { type Doc, type Item, isDoneKey, items } from './master.ts'

export type Level = 'high' | 'low' | null
export type Candidate = { item: Item; section: string; sectionIndex: number; index: number; category: string; impact: Level; mine: boolean; effort: Level; minutes: number | null; tier: number }

export const TOP = 5
export const NO_CATEGORY = 'Uncategorized'
const LEFT_OUT = /^(waiting|projects?\b)/

/** Minutes from a size estimate like "15m", "1h", "~2h?", "1.5h" or "1d". null when there's none or it can't be read. */
export function sizeMinutes(text: string): number | null {
  const m = text.replace(/^~/, '').match(/^(\d+(?:\.\d+)?)\s*(m|min|mins|h|hr|hrs|d|day|days)\b/i)
  if (!m) return null
  const n = Number(m[1])
  const unit = m[2].toLowerCase()
  return unit.startsWith('d') ? n * 8 * 60 : unit.startsWith('h') ? n * 60 : n
}

/** Half an hour or less is low effort. Anything bigger is high. */
export const effortOf = (minutes: number | null): Level => (minutes === null ? null : minutes <= 30 ? 'low' : 'high')

export function impactOf(it: Item): { impact: Level; mine: boolean } {
  const chip = it.chips.find((c) => c.kind === 'impact')
  if (!chip) return { impact: null, mine: false }
  return { impact: chip.text.startsWith('high') ? 'high' : 'low', mine: chip.text.endsWith('*') }
}

/**
 * Low effort and high impact first, then high/high, low/low and high effort/low impact. Rated items come before unrated ones, and an
 * item missing only its size sits between the two effort levels of its impact.
 */
export function tierOf(impact: Level, effort: Level) {
  const i = impact === 'high' ? 0 : impact === 'low' ? 1 : 2
  const e = effort === 'low' ? 0 : effort === null ? 1 : 2
  return i * 3 + e
}

export const categoryOf = (it: Item) => it.chips.find((c) => c.kind === 'category')?.text ?? NO_CATEGORY

/** Every open item that could be worked on, with what the view needs to rank it. Waiting On, Projects and Done are left out. */
export function candidates(doc: Doc): Candidate[] {
  const out: Candidate[] = []
  let index = 0
  doc.sections.forEach((s, sectionIndex) => {
    if (isDoneKey(s.key) || LEFT_OUT.test(s.key)) return
    for (const item of items(s)) {
      if (item.done || item.doneForNow) continue
      const { impact, mine } = impactOf(item)
      const size = item.chips.find((c) => c.kind === 'size')
      const minutes = size ? sizeMinutes(size.text) : null
      const effort = effortOf(minutes)
      out.push({ item, section: s.key, sectionIndex, index: index++, category: categoryOf(item), impact, mine, effort, minutes, tier: tierOf(impact, effort) })
    }
  })
  return out
}

/**
 * Each category's candidates, best first. `order` is what the user arranged by dragging in this view: those keys come first, in that order,
 * and everything else follows by tier and then by its place in the list.
 */
export function buckets(doc: Doc, order: Record<string, string[]> = {}): Map<string, Candidate[]> {
  const by = new Map<string, Candidate[]>()
  for (const c of candidates(doc)) {
    const list = by.get(c.category) ?? []
    list.push(c)
    by.set(c.category, list)
  }
  for (const [cat, list] of by) {
    const placed = order[cat] ?? []
    const at = (c: Candidate) => { const i = placed.indexOf(c.item.key); return i < 0 ? Infinity : i }
    list.sort((a, b) => at(a) - at(b) || a.tier - b.tier || a.index - b.index)
  }
  return new Map([...by].sort(([a, x], [b, y]) => (a === NO_CATEGORY ? 1 : b === NO_CATEGORY ? -1 : x[0].index - y[0].index || a.localeCompare(b))))
}

/** Days from `today` to a due chip like "Fri 11/7" or "11/14". Past dates are negative. The year is whichever puts it nearest today. */
export function daysUntil(due: string, today: Date): number | null {
  const m = due.match(/(\d{1,2})\/(\d{1,2})(?:\/(\d{2,4}))?/)
  if (!m) return null
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  const day = (y: number) => Math.round((new Date(y, Number(m[1]) - 1, Number(m[2])).getTime() - start.getTime()) / 86_400_000)
  if (m[3]) return day(m[3].length === 2 ? 2000 + Number(m[3]) : Number(m[3]))
  const y = today.getFullYear()
  return [day(y - 1), day(y), day(y + 1)].reduce((a, b) => (Math.abs(b) < Math.abs(a) ? b : a))
}

/** Overdue or due within 2 days, then within a week, then anything later or undated. */
export function urgencyOf(c: Candidate, today: Date) {
  const due = c.item.chips.find((x) => x.kind === 'due')
  const d = due ? daysUntil(due.text, today) : null
  return d === null ? 2 : d <= 2 ? 0 : d <= 7 ? 1 : 2
}

/**
 * Focus: the top item of every bucket, ranked against each other. High impact comes first, then what can't wait (urgency), then where
 * the list already puts it (Now before Next), then the smaller job, then list order. Low and unrated impact count the same here, so an
 * unrated item never jumps ahead of something known and due tomorrow.
 */
export function focus(all: Map<string, Candidate[]>, today: Date): Candidate[] {
  const imp = (c: Candidate) => (c.impact === 'high' ? 0 : 1)
  const eff = (c: Candidate) => (c.effort === 'low' ? 0 : c.effort === null ? 1 : 2)
  return [...all.values()].map((list) => list[0]).filter(Boolean)
    .sort((a, b) => imp(a) - imp(b) || urgencyOf(a, today) - urgencyOf(b, today) || a.sectionIndex - b.sectionIndex || eff(a) - eff(b) || a.index - b.index)
}

/** What the view remembers for one day: items finished here, and where they were, and how many replacements were asked for. */
export type DayState = { day: string; done: Record<string, { key: string; at: number }[]>; added: Record<string, number> }
export const dayKey = (d: Date) => `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`
export const freshDay = (d: Date): DayState => ({ day: dayKey(d), done: {}, added: {} })

export type Slot = { kind: 'open'; c: Candidate } | { kind: 'done'; key: string; item: Item | null }

/**
 * The rows a bucket shows today. Finishing an item here leaves it in its place, marked done, and doesn't pull the next one up by itself.
 * The user asks for a replacement ("Add the next one?"), and it joins at the bottom. Items finished elsewhere just drop out and
 * the next one moves up, because nothing here was promised about them.
 */
export function slots(list: Candidate[], finished: { key: string; at: number }[], added: number, find: (key: string) => Item | null) {
  const room = Math.max(0, TOP - finished.length + added)
  const open = list.slice(0, room)
  const rows: Slot[] = open.map((c) => ({ kind: 'open', c }))
  for (const f of [...finished].sort((a, b) => a.at - b.at)) rows.splice(Math.min(f.at, rows.length), 0, { kind: 'done', key: f.key, item: find(f.key) })
  const next = finished.length > added ? list[room] ?? null : null
  return { rows, next }
}
