import assert from 'node:assert/strict'
import { test } from 'node:test'

import { buckets, candidates, daysUntil, effortOf, focus, NO_CATEGORY, sizeMinutes, slots, tierOf, TOP } from './focus.ts'
import { findItem, items, parse, findSection, setCategory, setImpact } from './master.ts'

const MD = `# ★ Master List

## 🔥 NOW
- [ ] Big important · #Biz · ~3h · impact:high · id:t1
- [ ] Quick important · #Biz · ~15m · impact:high* · id:t2
- [ ] Quick minor · #Biz · ~10m · impact:low · id:t3
- [ ] Unrated · #Biz · id:t4
- [ ] Home thing · #Home · due 11/4 · ~20m · impact:low · id:t5

## 💬 COMMUNICATIONS
- [ ] Reply to a friend · #Friends · impact:high · id:t6

## ⏭ NEXT
- [ ] Big minor · #Biz · ~2h · impact:low · id:t7
- [ ] Biz six · #Biz · ~15m · id:t8
- [ ] Biz seven · #Biz · ~15m · id:t9
- [ ] No category at all · id:t10
- [ ] Repeating · #Home · ↻ every Monday · done for now 11/2 · id:t11

## ⏳ WAITING ON
- [ ] Waiting thing · #Biz · impact:high · id:t12

## ✅ DONE
- [x] Old · #Biz · done 11/1 · id:t13
`
const today = new Date(2026, 10, 3)
const keys = (list: { item: { key: string } }[]) => list.map((c) => c.item.key)

test('sizes become minutes, and half an hour is the line between low and high effort', () => {
  assert.equal(sizeMinutes('15m'), 15)
  assert.equal(sizeMinutes('~2h?'), 120)
  assert.equal(sizeMinutes('1.5h'), 90)
  assert.equal(sizeMinutes('1d'), 480)
  assert.equal(sizeMinutes('soon'), null)
  assert.equal(effortOf(30), 'low')
  assert.equal(effortOf(45), 'high')
  assert.equal(effortOf(null), null)
})

test('the order is low effort/high impact, high/high, low/low, high/low, and unrated last', () => {
  const order = [tierOf('high', 'low'), tierOf('high', 'high'), tierOf('low', 'low'), tierOf('low', 'high'), tierOf(null, 'low')]
  assert.deepEqual([...order].sort((a, b) => a - b), order)
  assert.ok(tierOf('high', null) < tierOf('high', 'high'))
})

test('waiting, done and done-for-now items are not candidates', () => {
  const ks = keys(candidates(parse(MD)))
  for (const k of ['t11', 't12', 't13']) assert.ok(!ks.includes(k), k)
})

test('a bucket is a category, sorted by impact and effort, then list order', () => {
  const b = buckets(parse(MD))
  assert.deepEqual(keys(b.get('Biz')!), ['t2', 't1', 't3', 't7', 't8', 't9', 't4'])
  assert.deepEqual(keys(b.get(NO_CATEGORY)!), ['t10'])
  assert.equal([...b.keys()].at(-1), NO_CATEGORY)
})

test('what the user arranged by dragging comes first, in that order', () => {
  const b = buckets(parse(MD), { Biz: ['t4', 't3'] })
  assert.deepEqual(keys(b.get('Biz')!).slice(0, 3), ['t4', 't3', 't2'])
})

test('the user’s own rating is marked as theirs', () => {
  const c = candidates(parse(MD))
  assert.equal(c.find((x) => x.item.key === 't2')!.mine, true)
  assert.equal(c.find((x) => x.item.key === 't1')!.mine, false)
})

test('focus takes each bucket’s top item and ranks them: impact, then urgency, then section', () => {
  const f = focus(buckets(parse(MD)), today)
  assert.deepEqual(keys(f), ['t2', 't6', 't5', 't10'])
})

test('due dates count from today, across a new year too', () => {
  assert.equal(daysUntil('Fri 11/7', today), 4)
  assert.equal(daysUntil('11/1', today), -2)
  assert.equal(daysUntil('1/2', new Date(2026, 11, 30)), 3)
  assert.equal(daysUntil('someday', today), null)
})

test('a bucket shows five; one finished here stays in place and the next waits to be asked for', () => {
  const list = buckets(parse(MD)).get('Biz')!
  const find = () => null
  let s = slots(list, [], 0, find)
  assert.equal(s.rows.length, TOP)
  assert.equal(s.next, null)
  const rest = list.filter((c) => c.item.key !== 't1')
  s = slots(rest, [{ key: 't1', at: 1 }], 0, find)
  assert.deepEqual(s.rows.map((r) => (r.kind === 'done' ? `done:${r.key}` : r.c.item.key)), ['t2', 'done:t1', 't3', 't7', 't8'])
  assert.equal(s.next?.item.key, 't9')
  s = slots(rest, [{ key: 't1', at: 1 }], 1, find)
  assert.deepEqual(s.rows.map((r) => (r.kind === 'done' ? `done:${r.key}` : r.c.item.key)), ['t2', 'done:t1', 't3', 't7', 't8', 't9'])
  assert.equal(s.next, null)
})

test('setting impact marks it as the user’s, replaces any old rating, and can be taken off', () => {
  let md = setImpact(MD, 't1', 'low')
  const line = findItem(parse(md), 't1')!.item.line
  assert.match(line, /impact:low\* · id:t1$/)
  assert.doesNotMatch(line, /impact:high/)
  md = setImpact(md, 't1', null)
  assert.doesNotMatch(findItem(parse(md), 't1')!.item.line, /impact:/)
  assert.equal(setImpact(MD, 'nope', 'high'), MD)
})

test('moving to another category changes only the category, and adds one if there was none', () => {
  let md = setCategory(MD, 't3', 'Home')
  assert.equal(findItem(parse(md), 't3')!.item.line, '- [ ] Quick minor · #Home · ~10m · impact:low · id:t3')
  assert.deepEqual(items(findSection(parse(md), 'now')).map((i) => i.key), ['t1', 't2', 't3', 't4', 't5'])
  md = setCategory(md, 't10', '#Biz')
  assert.equal(findItem(parse(md), 't10')!.item.line, '- [ ] No category at all · #Biz · id:t10')
  assert.equal(setCategory(MD, 't3', '  '), MD)
})
