// The screen in a real browser, from the real files, served the way the Pi serves them. Run: node apps/wall/e2e.mjs
// WALL_BROWSER=webkit picks another engine (CI only installs that one). SHOTS=<folder> saves pictures to look at.
import { spawn } from 'node:child_process'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import playwright from 'playwright'

const here = dirname(fileURLToPath(import.meta.url))
const run = mkdtempSync(join(tmpdir(), 'theseus-wall-e2e-'))
const port = 18737 + Math.floor(Math.random() * 500)
const server = spawn('/usr/bin/python3', [join(here, 'pi/serve.py')], { env: { ...process.env, THESEUS_WALL_RUN: run, THESEUS_WALL_PORT: String(port) }, stdio: 'ignore' })
const base = `http://127.0.0.1:${port}/`
const NOW = '2026-11-05T08:42:00'
const shots = process.env.SHOTS

const titles = ['Renew the business license', 'Send the signed lease back', 'Draft the budget memo', 'Book flights for the reunion', 'Pay the quarterly estimate', 'Order furnace filters', 'Schedule the annual checkup', 'Call about the gutter estimate', 'Pick a date for the car service', 'Sign the permission slip', 'Edit episode twelve', 'Move savings to the new account', 'Reply to the vendor proposal']
const sectors = ['Work', 'Home', 'Work', 'Family', 'Money', 'Home', 'Health', 'Home', 'Car', 'Family', 'Podcast', 'Money', 'Work']
const due = { 0: ['Thu 11/5', '2026-11-05'], 1: ['Tue 11/3', '2026-11-03'], 3: ['Fri 11/6', '2026-11-06'], 8: ['11/14', '2026-11-14'] }
const items = (n, start = 0, cat = sectors, names = titles) => Array.from({ length: n }, (_, i) => ({ number: start + i + 1, title: names[i % names.length] + (i >= names.length ? ` ${i}` : ''), category: cat[i % cat.length], due: due[i]?.[0] ?? null, due_date: due[i]?.[1] ?? null }))
const tile = (type, x, y, w, h, opts = {}) => ({ type, x, y, w, h, opts })
const counted = { sections: ['next', 'waiting on'] }
const status = tile('status', 0, 13, 12, 1)
const views = [
  { name: 'Sectors', when: null, layouts: { landscape: [tile('top', 0, 0, 17, 3, { section: 'now', size: 'XL' }), tile('clock', 17, 0, 7, 3, { date: true, size: 'M' }), tile('sectors', 0, 3, 24, 10, { section: 'now', skipTop: true, size: 'M' }), status, tile('counts', 12, 13, 12, 1, counted)] } },
  { name: 'Ranked', when: null, layouts: { landscape: [tile('list', 0, 0, 16, 13, { section: 'now', size: 'L' }), tile('clock', 16, 0, 8, 4, { date: true, size: 'L' }), tile('counts', 16, 4, 8, 4, counted), tile('due', 16, 8, 8, 5, { days: 14, size: 'M' }), status] } },
  { name: 'One thing', when: null, layouts: { landscape: [tile('clock', 0, 0, 24, 3, { date: true, size: 'M' }), tile('top', 0, 3, 24, 8, { section: 'now', size: 'XXL' }), tile('counts', 0, 11, 24, 2, counted), status] } },
  { name: 'Board', when: null, layouts: { landscape: [tile('list', 0, 0, 8, 13, { section: 'now', size: 'S' }), tile('list', 8, 0, 8, 13, { section: 'next', size: 'S' }), tile('list', 16, 0, 8, 13, { section: 'later', size: 'S' }), status, tile('counts', 12, 13, 12, 1, { sections: ['waiting on'] })] } },
  { name: 'Clock', when: null, layouts: { landscape: [tile('clock', 0, 2, 24, 7, { date: true, size: 'XL' }), tile('top', 3, 9, 18, 3, { section: 'now', size: 'L' }), status] } },
]
const snapshot = (over = {}, now = 13) => ({
  schema: 1, generated_at: `${NOW.slice(0, 16)}:00`, mode: 'titles', display: { on: '07:00', off: '23:00' }, views, change: { mode: 'fixed', active: 'Sectors' },
  sections: {
    now: { title: 'Now', open: now + 1, kept_private: 1, more: 0, items: items(now) },
    next: { title: 'Next', open: 8, items: items(8, 13) },
    later: { title: 'Later', open: 5, items: items(5, 21) },
    'waiting on': { title: 'Waiting On', open: 3 },
  },
  ...over,
})
const put = (snap) => writeFileSync(join(run, 'wall.json'), JSON.stringify(snap))
let failed = 0
const check = (name, pass, more = '') => { console.log(`${pass ? 'ok  ' : 'FAIL'} ${name} ${more}`); if (!pass) failed++ }

// Nothing drawn runs past its space, and nothing runs off the screen.
const spills = (p) => p.evaluate(() => {
  const bad = []
  for (const body of document.querySelectorAll('.body')) if (body.scrollHeight > body.clientHeight + 2 || body.scrollWidth > body.clientWidth + 2) bad.push(`spills: ${body.parentElement.dataset.type}`)
  for (const t of document.querySelectorAll('.top .tt')) if (t.scrollHeight > t.clientHeight + 2) bad.push(`top task cut off: ${t.textContent}`)
  for (const t of document.querySelectorAll('.tile, .whole > *, .corner')) { const r = t.getBoundingClientRect(); if (r.right > innerWidth + 1 || r.bottom > innerHeight + 1 || r.left < -1 || r.top < -1) bad.push(`off screen: ${t.className}`) }
  return bad
})

try {
  for (let i = 0; i < 40; i++) { try { await fetch(base); break } catch { await new Promise((r) => setTimeout(r, 100)) } }
  const browser = await playwright[process.env.WALL_BROWSER || 'chromium'].launch()
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } })
  const errors = []
  page.on('pageerror', (e) => errors.push(e.message))
  page.on('requestfailed', (r) => errors.push(`failed: ${r.url()}`))
  const outside = []
  page.on('request', (r) => { if (!r.url().startsWith(base)) outside.push(r.url()) })
  const open = async (snap, { now = NOW, size } = {}) => {
    if (snap) put(snap); else rmSync(join(run, 'wall.json'), { force: true })
    if (size) await page.setViewportSize(size)
    await page.goto(`${base}?now=${now}`)
    await page.waitForFunction(() => document.getElementById('inner').children.length > 0 || document.getElementById('stage').classList.contains('dark'))
  }
  const shot = (name) => shots ? page.screenshot({ path: join(shots, `${name}.png`) }) : null

  await open(null)
  check('no snapshot says Waiting', (await page.textContent('#inner')).includes('Waiting for your Mac'))
  await shot('waiting')

  for (const size of [{ width: 1920, height: 1080 }, { width: 1280, height: 720 }, { width: 3840, height: 2160 }, { width: 1080, height: 1920 }]) {
    for (const v of views) {
      await open(snapshot({ change: { mode: 'fixed', active: v.name } }), { size })
      const bad = await spills(page)
      check(`${v.name} at ${size.width}x${size.height} fits`, bad.length === 0, bad.join('; '))
      if (size.width === 1920 || size.width === 1080) await shot(`${v.name.replace(' ', '-').toLowerCase()}-${size.width}`)
    }
  }
  await page.setViewportSize({ width: 1920, height: 1080 })

  await open(snapshot())
  const text = await page.textContent('#inner')
  check('top task is shown', text.includes('Renew the business license'))
  check('sectors are grouped', (await page.$$eval('.sector .label', (l) => l.map((x) => x.firstChild.textContent))).join() === 'Home,Work,Family,Money,Health,Car,Podcast', (await page.$$eval('.sector .label', (l) => l.map((x) => x.firstChild.textContent))).join())
  check('the top task is not repeated', (await page.$$eval('.sector .t', (t) => t.map((x) => x.textContent))).every((t) => t !== 'Renew the business license'))
  check('every task keeps its number', (await page.$$eval('.sector .row', (r) => r.map((x) => [x.querySelector('.r').textContent, x.querySelector('.t').textContent]))).every(([n, t]) => titles[Number(n) - 1] === t))
  check('Due today comes from the screen clock', text.includes('Due today'))
  check('a missed date reads gently, in amber', await page.$eval('.d.late', (e) => e.textContent === 'Was due Tue'))
  check('counts show', text.includes('Waiting On') && text.includes('kept private'))
  check('a section with no titles still counts', (await page.textContent('[data-type=counts]')).includes('3'))

  await open(snapshot(), { now: '2026-11-06T08:42:00' })
  check("yesterday's Due today has moved on", (await page.textContent('#inner')).includes('Was due Thu'))
  check('an old list says so', (await page.textContent('.stale-note')).includes('This list is from 24 hours ago'))
  check('and the status line stops saying it\'s up to date', !(await page.textContent('#inner')).includes('Up to date') && (await page.textContent('#inner')).includes('Last update'))
  await shot('stale')

  await open(snapshot(), { now: `${NOW.slice(0, 11)}08:50:00` })
  check('a few minutes old is fine', (await page.locator('.stale-note').count()) === 0)
  await open(snapshot(), { now: `${NOW.slice(0, 11)}09:00:00` })
  check('18 minutes old is marked', (await page.locator('.stale-note').count()) === 1)
  await open(snapshot(), { now: `${NOW.slice(0, 11)}23:30:00` })
  check('after bed the screen goes dark', await page.evaluate(() => document.getElementById('stage').classList.contains('dark') && !document.getElementById('inner').children.length))

  for (const [time, dark] of [['05:59', true], ['06:00', false], ['23:59', false], ['00:00', true], ['00:30', true]]) {
    await open(snapshot({ generated_at: `2026-11-05T${time}:00`, display: { on: '06:00', off: '00:00' } }), { now: `2026-11-05T${time}:00` })
    check(`active hours crossing midnight at ${time}`, await page.evaluate(() => document.getElementById('stage').classList.contains('dark')) === dark)
  }
  await open(snapshot({ display: null }), { now: '2026-11-05T03:00:00' })
  check('no hours means it stays on', !(await page.evaluate(() => document.getElementById('stage').classList.contains('dark'))))

  const busy = snapshot({}, 40)
  busy.sections.now.items = items(40, 0, ['Work', 'Home', 'Family', 'Money', 'Health', 'Car', 'Podcast', 'Garden', 'School', 'Travel'], ['An example task with a typical length'])
  busy.sections.now.open = 47; busy.sections.now.more = 6
  await open(busy)
  check('a very long list still fits', (await spills(page)).length === 0, (await spills(page)).join('; '))
  await shot('busy')
  await open({ ...busy, change: { mode: 'fixed', active: 'Ranked' } })
  check('a list says how many it left out', /\d+ more/.test(await page.textContent('[data-type=list]')))

  const hostile = snapshot()
  hostile.sections.now.items[0].title = '<img src=x onerror="window.__pwned=1"><script>window.__pwned=1</script>'
  hostile.sections.now.items[1].category = '<b onmouseover="window.__pwned=1">x</b>'
  hostile.sections.now.items[1].due = '<i>x</i>'
  await open(hostile)
  check('titles stay text', await page.evaluate(() => !window.__pwned && !document.querySelector('#inner img, #inner script, #inner b[onmouseover], #inner i:not(.label i)')))

  const few = snapshot()
  few.sections.now.items = few.sections.now.items.slice(0, 3).map((i) => ({ ...i, category: 'Home' }))
  few.sections.now.open = 3
  await open(few)
  check('a short list gets wide cards, with nothing cut off', await page.evaluate(() => [...document.querySelectorAll('.sector .t')].every((t) => t.scrollHeight <= t.clientHeight + 1) && document.querySelector('.sector').getBoundingClientRect().width > innerWidth * 0.5))

  const empty = snapshot()
  empty.sections.now = { title: 'Now', open: 0, more: 0, kept_private: 0, items: [] }
  await open(empty)
  check('an empty Now says so', (await page.textContent('#inner')).includes('Nothing left in Now'))
  check('and nothing spills', (await spills(page)).length === 0)
  await shot('clear')

  await open({ schema: 1, generated_at: `${NOW.slice(0, 16)}:00`, mode: 'counts', display: null, sections: { now: { title: 'Now', open: 14, due_today: 1, was_due: 1 }, next: { title: 'Next', open: 42 }, 'waiting on': { title: 'Waiting On', open: 1 } } })
  const counts = await page.textContent('#inner')
  check('counts mode shows numbers', counts.includes('14') && counts.includes('in Now') && counts.includes('1 due today') && counts.includes('42'))
  await shot('counts')

  await open({ ...snapshot(), schema: 2 })
  check('a newer format shows Waiting, not a guess', (await page.textContent('#inner')).includes('Waiting for your Mac'))
  const odd = snapshot(); odd.views = [{ name: 'x', layouts: { landscape: [tile('mystery', 0, 0, 2, 2)] } }]
  await open(odd)
  check('an unknown piece shows Waiting, not a guess', (await page.textContent('#inner')).includes('Waiting for your Mac'))

  await open(snapshot({ change: { mode: 'schedule' }, views: [{ ...views[1], when: { from: '08:00', to: '09:00' } }, views[0]] }))
  check('a timed view shows during its time', (await page.locator('[data-type=list]').count()) === 1)
  await open(snapshot({ change: { mode: 'schedule' }, views: [{ ...views[1], when: { from: '22:00', to: '07:00' } }, views[0]] }))
  check('and not outside it', (await page.locator('[data-type=sectors]').count()) === 1)

  // A whole night on one open page, with the clock fast-forwarded: nothing reloads, and no new delivery arrives.
  const night = await browser.newPage({ viewport: { width: 1920, height: 1080 } })
  await night.clock.install({ time: new Date('2026-11-05T23:50:00') })
  put(snapshot({ generated_at: '2026-11-05T23:49:00', display: { on: '06:00', off: '00:00' } }))
  await night.goto(base)
  await night.clock.runFor(11000)
  await night.waitForSelector('.tile')
  const dark = () => night.evaluate(() => document.getElementById('stage').classList.contains('dark'))
  check('an open page is on at 11:50pm', !(await dark()))
  check('with Due today for today', (await night.textContent('#inner')).includes('Was due Tue'))
  await night.clock.fastForward('11:00')
  await night.clock.runFor(11000)
  check('it goes dark at midnight by itself', await dark())
  check('with nothing on screen', (await night.locator('#inner > *').count()) === 0)
  await night.clock.fastForward('05:50:00')
  await night.clock.runFor(11000)
  check('it stays dark through the night', await dark())
  await night.clock.fastForward('10:00')
  await night.clock.runFor(11000)
  check('it comes back at 6am by itself', !(await dark()))
  const morning = await night.textContent('#inner')
  check('and the list is back, with its age shown', morning.includes('Renew the business license') && morning.includes('This list is from 6 hours ago'), morning.slice(-90))
  check('yesterday\'s Due today has moved on', morning.includes('Was due Thu'))
  check('the clock on screen moved', (await night.textContent('.clock')).includes('6:'))
  const after = snapshot({ generated_at: '2026-11-06T06:01:00', display: { on: '06:00', off: '00:00' } })
  after.sections.now.items[0].title = 'Fresh from the Mac'
  put(after)
  await night.clock.runFor(11000)
  await night.waitForFunction(() => document.querySelector('.top .tt')?.textContent === 'Fresh from the Mac', null, { timeout: 8000 })
  check('when the Mac wakes, the morning delivery shows and the age note goes', (await night.locator('.stale-note').count()) === 0)
  rmSync(join(run, 'wall.json'))
  await night.clock.runFor(11000)
  await night.waitForFunction(() => document.getElementById('inner').textContent.includes('Waiting for your Mac'), null, { timeout: 8000 })
  check('a list cleared while the page is open goes back to Waiting', true)
  await night.close()

  // The server going away while the page is open: the last list stays up.
  put(snapshot())
  await open(snapshot())
  await page.route('**/wall.json*', (r) => r.abort())
  await page.waitForTimeout(11000)
  check('if the page server stops answering, the last list stays up', (await page.textContent('#inner')).includes('Renew the business license'))
  await page.unroute('**/wall.json*')

  // A fresh delivery appears by itself.
  await open(snapshot())
  const fresh = snapshot(); fresh.sections.now.items[0].title = 'A brand new top task'
  put(fresh)
  await page.waitForFunction(() => document.querySelector('.top .tt')?.textContent === 'A brand new top task', null, { timeout: 15000 })
  check('a new delivery shows without a reload', true)

  const realErrors = errors.filter((e) => !e.includes('wall.json'))
  check('no page errors', realErrors.length === 0, realErrors.join(' | '))
  check('it reached nothing beyond this Pi', outside.length === 0, outside.join(' '))
  await browser.close()
} catch (e) {
  console.error(e)
  failed++
} finally {
  server.kill()
  rmSync(run, { recursive: true, force: true })
}
console.log(failed ? `${failed} FAILED` : 'all passed')
process.exit(failed ? 1 : 0)
