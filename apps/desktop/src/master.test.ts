import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { test } from 'node:test'

import { addItem, complete, editTitle, findItem, findSection, items, moveItem, parse, reopen, sectionTitle, serialize, dropEmoji } from './master.ts'

const MD = `# ★ Master List
_Updated Tue 11/3 6:02am · 2 NOW_

## 🔥 NOW
- [ ] Renew license · #Biz · due Fri 11/7 · ~15m · ⏰ 🏠 · id:t0001
  - asked by Sam
  - link
- [ ] Book dentist · #Home · id:t0002

## 💬 COMMUNICATIONS
- [ ] Reply to Sam · #Friends · id:t0003

## ⏭ NEXT: queued for the next ~2 weeks
- [ ] Water plants · #Home · ↻ every Monday · due Mon 11/9 · ⏰ · id:t0004
some note the user wrote

## ⏳ WAITING ON

## ✅ DONE
- [x] Old thing · #Home · done 11/1 · id:t0005
`
const on = new Date(2026, 10, 3)
const titles = (md: string, k: string) => items(findSection(parse(md), k)).map((i) => i.title)

test('reading and writing changes nothing', () => {
  assert.equal(serialize(parse(MD)), MD)
})

test('the real master list survives a round trip, if there is one on this Mac', () => {
  const p = `${process.env.HOME}/Theseus/data/master.md`
  if (!existsSync(p)) return
  const real = readFileSync(p, 'utf8')
  assert.ok(serialize(parse(real)) === real, 'round trip changed the file')
})

test('reads an item into parts', () => {
  const it = findItem(parse(MD), 't0001')!.item
  assert.equal(it.title, 'Renew license')
  assert.deepEqual(it.chips.map((c) => c.kind), ['category', 'due', 'size', 'reminder', 'skylight'])
  assert.equal(it.children.length, 2)
})

test('headings lose their emoji and explanation', () => {
  assert.equal(sectionTitle('## ⏭ NEXT: queued for the next ~2 weeks'), 'NEXT')
})

test('move within a section keeps context lines with the item', () => {
  const md = moveItem(MD, 't0002', 'now', 't0001')
  assert.deepEqual(titles(md, 'now'), ['Book dentist', 'Renew license'])
  assert.deepEqual(findItem(parse(md), 't0001')!.item.children, ['  - asked by Sam', '  - link'])
})

test('move across sections, to the end, ahead of the blank line', () => {
  const md = moveItem(MD, 't0002', 'communications', null)
  assert.deepEqual(titles(md, 'communications'), ['Reply to Sam', 'Book dentist'])
  assert.deepEqual(titles(md, 'now'), ['Renew license'])
  assert.match(md, /Book dentist · #Home · id:t0002\n\n## ⏭ NEXT/)
})

test('move to an empty section', () => {
  assert.deepEqual(titles(moveItem(MD, 't0002', 'waiting on', null), 'waiting on'), ['Book dentist'])
})

test('complete goes to the top of Done with the date before the id', () => {
  const md = complete(MD, 't0001', on)
  assert.equal(titles(md, 'done')[0], 'Renew license')
  assert.match(md, /- \[x\] Renew license · #Biz · due Fri 11\/7 · ~15m · ⏰ 🏠 · done 11\/3 · id:t0001\n  - asked by Sam/)
  assert.deepEqual(titles(md, 'now'), ['Book dentist'])
})

test('reopen undoes complete, back in the named section', () => {
  const md = reopen(complete(MD, 't0002', on), 't0002', 'now')
  assert.equal(titles(md, 'now')[0], 'Book dentist')
  assert.ok(!findItem(parse(md), 't0002')!.item.done)
  assert.doesNotMatch(md, /Book dentist.*done/)
})

test('a repeating item stays where it is, done for now', () => {
  const md = complete(MD, 't0004', on)
  const hit = findItem(parse(md), 't0004')!
  assert.equal(hit.section.key, 'next')
  assert.ok(hit.item.doneForNow && !hit.item.done)
  assert.equal(serialize(parse(reopen(md, 't0004'))), MD)
})

test('editing a title leaves everything else alone', () => {
  assert.match(editTitle(MD, 't0002', 'Book the dentist'), /- \[ \] Book the dentist · #Home · id:t0002/)
  assert.equal(editTitle(MD, 't0002', '   '), MD)
  assert.match(editTitle(MD, 't0002', 'a · b'), /- \[ \] a - b · #Home · id:t0002/)
})

test('adding uses #Inbox and no id', () => {
  const md = addItem(MD, 'now', 'Call the vet')
  assert.match(md, /- \[ \] Call the vet · #Inbox\n\n## 💬/)
  assert.equal(findItem(parse(md), 'title:Call the vet')!.section.key, 'now')
})

test('lines the app does not understand stay put', () => {
  assert.match(moveItem(MD, 't0002', 'done', null), /some note the user wrote/)
})

test('unknown items and sections change nothing', () => {
  assert.equal(moveItem(MD, 'nope', 'now', null), MD)
  assert.equal(moveItem(MD, 't0001', 'nope', null), MD)
  assert.equal(complete(MD, 'nope', on), MD)
})

test('emoji come off for display; numbers, check marks and arrows stay', () => {
  assert.equal(dropEmoji('🧹 NOW has 11'), 'NOW has 11')
  assert.equal(dropEmoji('⚠️ 3 files'), '3 files')
  assert.equal(dropEmoji('Lunch ⏰ with Sam 🏠'), 'Lunch with Sam')
  assert.equal(dropEmoji('✓ done → next'), '✓ done → next')
})
