// The real window against a pretend backend: real mouse drags, real timers, no real data. Run: pnpm --filter theseus-desktop e2e (after a build).
import { webkit } from 'playwright'; import http from 'http'; import fs from 'fs'; import os from 'os';
const DIST=new URL('../dist',import.meta.url).pathname, OUT=process.env.E2E_SHOTS||fs.mkdtempSync(os.tmpdir()+'/theseus-e2e-');
const MASTER=`# ★ Master List
_Updated Tue 11/3 6:02am_

## 🔥 NOW
- [ ] Renew the car registration · #Home · due Fri 11/6 · ~15m · ⏰ · id:t0001
  - The DMV site is fastest
- [ ] Gather documents for the accountant · #Money · id:t0002
- [ ] Book the dentist · #Home · ⏰ 🏠 · id:t0003

## 💬 COMMUNICATIONS
- [ ] Reply to Sam about Saturday · #Friends · id:t0004
- [ ] Call Priya back · #Family · id:t0005

## ⏭ NEXT: queued
- [ ] Water the plants · #Home · ↻ every Monday · due Mon 11/9 · ⏰ · id:t0006

## 💭 EVENTUALLY
- [ ] Learn the banjo · #Fun · id:t0007

## ✅ DONE
- [x] Old thing · #Home · done 11/1 · id:t0008
`;
const TODAY=`# 📌 Today · Tue Nov 3
_Updated 7:57pm · reads back your edits next run_
🧹 NOW has 9 items.

## ⚠️ Needs attention
⚠️ Alarms Shortcut isn't set up.

## 🔥 NOW
☐ stale copy

## 💬 Waiting on you
New texts: Alex (3 unread) · Taylor

## 📅 Agenda
🌙 Tonight: nothing left.
Wed 11/4: 9:00 All Hands

## ⏭ Up next
**Tomorrow:** the registration.
`;
let file=MASTER, writes=0, publishes=0; const log=[], conflicts=[];
const st={workspace:'~/Theseus',claude:'~/.local/bin/claude',hosting:true,paused:false,remote:'ok',remote_state:'running',last_check:'',job_running:null,last_job:'',last_job_output:'',last_answer:'',app_version:'0.5.1',engine_version:'0.5.1',auto_host:true,can_host:true};
const H={thread_notes:()=>[{id:'abc123',label:'Sam Rivera',last_updated:'2026-11-01 09:00:00',last_checked:'2026-11-05 10:00:00',seen:120}],read_thread_note:()=>'# Sam Rivera\nShort replies.',read_commands:()=>'THESEUS COMMANDS\n  /next  the best thing to do now',get_status:()=>st,read_today:()=>TODAY,read_master:()=>file,write_master:(a)=>{if(a.base!==file)throw 'conflict';file=a.text;writes++;log.push(...a.events);return null},save_conflict:(a)=>{conflicts.push(a.text);return 'data/archive/master-conflict-x.md'},publish_master:()=>{publishes++;return ''},run_now:()=>null,recent_runs:()=>[],schedule:()=>({days:[{}]}),permissions:()=>[]};
const srv=http.createServer((q,r)=>{if(q.url==='/invoke'){let b='';q.on('data',d=>b+=d);q.on('end',()=>{const{cmd,args}=JSON.parse(b);try{r.end(JSON.stringify(H[cmd]?H[cmd](args):null))}catch(e){r.writeHead(500);r.end(String(e))}});return}
 const f=DIST+(q.url==='/'?'/index.html':q.url);if(!fs.existsSync(f)){r.writeHead(404);return r.end()}r.writeHead(200,{'content-type':f.endsWith('.js')?'text/javascript':f.endsWith('.css')?'text/css':f.endsWith('.svg')?'image/svg+xml':'text/html'});r.end(fs.readFileSync(f))}).listen(0);
const url=`http://127.0.0.1:${srv.address().port}/`;const b=await webkit.launch();const p=await b.newPage({viewport:{width:1040,height:800},colorScheme:'light'});const errs=[];p.on('pageerror',e=>errs.push(String(e)));
await p.addInitScript(()=>{const cbs={};let n=1;window.__listeners={};window.__TAURI_EVENT_PLUGIN_INTERNALS__={unregisterListener:()=>{}};window.__TAURI_INTERNALS__={transformCallback:(cb)=>{const id=n++;cbs[id]=cb;return id},invoke:async(cmd,args)=>{if(cmd==='plugin:event|listen'){(window.__listeners[args.event]??=[]).push(cbs[args.handler]);return n++}if(cmd.startsWith('plugin:'))return null;const r=await fetch('/invoke',{method:'POST',body:JSON.stringify({cmd,args})});if(!r.ok)throw await r.text();return r.json()}};window.__emit=(e)=>(window.__listeners[e]||[]).forEach((f)=>f&&f({event:e,payload:null}))});
const ok=(n,c)=>{console.log((c?'PASS ':'FAIL ')+n);if(!c)process.exitCode=1};
const nowOrder=()=>[...file.split('## 💬')[0].matchAll(/^- \[.\] (.*?) ·/gm)].map(m=>m[1]);
const sleep=(ms)=>p.waitForTimeout(ms);
const drag=async(fromText,toLoc,dy=2)=>{const a=await p.locator('[data-drag-id]',{hasText:fromText}).boundingBox();const t=await toLoc.boundingBox();await p.mouse.move(a.x+200,a.y+a.height/2);await p.mouse.down();await p.mouse.move(a.x+205,a.y+a.height/2+8,{steps:3});await p.mouse.move(t.x+200,t.y+dy,{steps:8});await p.waitForTimeout(60);await p.mouse.up();};
await p.goto(url);await p.waitForSelector('text=Renew the car registration');
await p.screenshot({path:OUT+'/today.png'});
const body=await p.innerText('body');ok('no emoji on screen',!/[\u{1F000}-\u{1FAFF}\u{2600}-\u{26FF}\u{23E9}-\u{23FA}\u{2B50}]/u.test(body));
ok('Communication has its own block',await p.isVisible('.block-name:text("Communication")'));ok('its items are live',await p.isVisible('text=Reply to Sam about Saturday'));ok('waiting-on lines join it',await p.locator('.block',{hasText:'Communication'}).locator('text=New texts').isVisible());ok('stale Today copy of Now not shown',!(await p.isVisible('text=stale copy')));
const rowOf=(t)=>p.locator('[data-drag-id]',{hasText:t});
// grace period
await rowOf('Book the dentist').locator('.check').click();await sleep(200);ok('checks at once',await rowOf('Book the dentist').locator('.check.on').isVisible());ok('shows a countdown',await rowOf('Book the dentist').locator('.grace-bar').isVisible());await p.screenshot({path:OUT+'/grace.png'});
await sleep(1200);await rowOf('Book the dentist').locator('.check').click();await sleep(2600);ok('unchecking in time changes nothing',file===MASTER&&writes===0);ok('and is really unchecked',!(await rowOf('Book the dentist').locator('.check.on').isVisible()));
await rowOf('Gather documents').locator('.check').click();await sleep(1000);ok('still in place at 1s',file===MASTER);await sleep(2700);ok('moves to Done after the wait',/## ✅ DONE\n- \[x\] Gather documents for the accountant · #Money · done \d+\/\d+ · was:now · id:t0002/.test(file));ok('log says complete',log.at(-1)?.action==='complete'&&log.at(-1)?.id==='t0002');ok('offers undo',await p.isVisible('.toast >> text=moved to Done'));await p.screenshot({path:OUT+'/done-toast.png'});
await p.click('.toast button');await sleep(700);ok('undo restores the file exactly',file===MASTER);ok('log records the undo',log.at(-1)?.action==='undo'&&log.at(-1)?.of?.id==='t0002');
await p.keyboard.press('Meta+Shift+z');await sleep(700);ok('⇧⌘Z redoes',/- \[x\] Gather documents/.test(file));await p.keyboard.press('Meta+z');await sleep(700);ok('⌘Z undoes',file===MASTER);
// repeating
// drag
await drag('Book the dentist',rowOf('Renew the car registration'));await sleep(700);ok('drag reorders within Now',nowOrder()[0]==='Book the dentist');ok('saved automatically',await p.isVisible('.save-state:has-text("Saved")'));ok('log says move',log.at(-1)?.action==='move'&&log.at(-1)?.from==='now'&&log.at(-1)?.to==='now');ok('notes stay with their item',/Renew the car registration[^\n]*\n  - The DMV site/.test(file));
await drag('Renew the car',rowOf('Call Priya back'));await sleep(700);ok('drag across blocks',/## 💬 COMMUNICATIONS\n- \[ \] Reply to Sam[^\n]*\n- \[ \] Renew the car[^\n]*\n  - The DMV site is fastest\n- \[ \] Call Priya/.test(file));ok('log says from now to communications',log.at(-1)?.from==='now'&&log.at(-1)?.to==='communications');
await p.keyboard.press('Meta+z');await sleep(600);await p.keyboard.press('Meta+z');await sleep(700);ok('undo walks back through drags',file===MASTER);
// escape cancels
{const a=await rowOf('Book the dentist').boundingBox();await p.mouse.move(a.x+200,a.y+10);await p.mouse.down();await p.mouse.move(a.x+200,a.y+60,{steps:4});await p.keyboard.press('Escape');await p.mouse.up();await sleep(500);ok('Escape cancels a drag',file===MASTER);}
// keyboard
await rowOf('Book the dentist').focus();await p.keyboard.press('Alt+ArrowUp');await sleep(600);ok('⌥↑ moves it up',nowOrder()[1]==='Book the dentist');await p.keyboard.press('Meta+z');await sleep(600);
// rename and add
await p.locator('.task-title',{hasText:'Book the dentist'}).dblclick();await p.fill('.task-line input','Book the dentist for the kids');await p.keyboard.press('Enter');await sleep(600);ok('rename keeps the rest of the line',file.includes('- [ ] Book the dentist for the kids · #Home · ⏰ 🏠 · id:t0003'));
await p.locator('.block',{hasText:'Communication'}).locator('.add').click();await p.keyboard.type('Text Jordan');await p.keyboard.press('Enter');await sleep(600);ok('add goes in that block',/Call Priya back[^\n]*\n- \[ \] Text Jordan · #Inbox\n/.test(file));await p.keyboard.press('Escape');
// a sync lands while a change is unsaved
{const a=await rowOf('Reply to Sam').locator('.check');const before=file;file=file.replace('## ⏭ NEXT: queued\n','## ⏭ NEXT: queued\n- [ ] Added by sync · #Home · id:t0100\n');await drag('Book the dentist',rowOf('Renew the car registration'));await sleep(900);ok('edit during a sync: both survive',file.includes('Added by sync')&&nowOrder()[0].startsWith('Book the dentist'));ok('says what happened',await p.isVisible('text=Your change is kept'));await p.screenshot({path:OUT+'/conflict.png'});}
await p.click('.notice button');
// sync while idle
{file=file.replace('Learn the banjo','Learn the mandolin');await sleep(3400);await p.click('nav >> text=List');await p.locator('.block-head',{hasText:'Eventually'}).click();ok('picks up a sync',await p.isVisible('text=Learn the mandolin'));ok('undo can\'t reach back past it',await p.locator('button[aria-label=Undo]').isDisabled());await p.screenshot({path:OUT+'/list.png'});}
// repeating
await rowOf('Water the plants').locator('.check').click();await sleep(3800);ok('repeating stays in place',/## ⏭ NEXT: queued\n- \[ \] Added by sync[^\n]*\n- \[ \] Water the plants · #Home · ↻ every Monday · due Mon 11\/9 · ⏰ · done for now \d+\/\d+ · id:t0006/.test(file));ok('shows done for now',await rowOf('Water the plants').locator('text=Done for now').isVisible());ok('log flags repeating',log.at(-1)?.repeating===true);await rowOf('Water the plants').locator('.check').click();await sleep(600);ok('reopen clears it',!file.includes('done for now'));
// markdown
await p.click('text=Markdown');await p.waitForSelector('textarea');ok('Markdown shows the file',(await p.inputValue('textarea'))===file);const keep=file;await p.click('textarea');await p.keyboard.press('Meta+ArrowUp');await p.keyboard.type('Hello ');await sleep(700);ok('typing saves itself',file.startsWith('Hello '));await p.screenshot({path:OUT+'/markdown.png'});await sleep(900);await p.keyboard.press('Meta+z');await sleep(700);ok('undo in Markdown',file===keep);
await sleep(100);ok('no page errors',errs.length===0);if(errs.length)console.log(errs.slice(0,3));
await sleep(10200);ok('phone note updated after a pause',publishes>0);
// from the 2026-11 review ----------------------------------------------------
const seenBefore=log.length;
await p.click('nav >> text=List');await p.click('.segmented >> text=List');await p.waitForSelector('[data-drag-id]');
// a check-off reopened goes back where it came from
await rowOf('Call Priya').locator('.check').click();await sleep(3800);ok('checked off',/- \[x\] Call Priya back[^\n]*was:communications/.test(file));
await p.keyboard.press('Meta+z');await sleep(600);
await p.locator('.block-head',{hasText:'Done'}).click().catch(()=>{});
// nothing is logged until it's saved
{const before=log.length;await rowOf('Reply to Sam').locator('.check').click();await sleep(100);ok('countdown logs nothing yet',log.length===before);await p.evaluate(()=>window.__emit('commit-now'));await sleep(500);ok('closing the window finishes a countdown',/- \[x\] Reply to Sam/.test(file));ok('and logs it with the save',log.at(-1)?.action==='complete');await p.keyboard.press('Meta+z');await sleep(600);}
// a drag released outside the window can't stay stuck
{const a=await rowOf('Reply to Sam').boundingBox();await p.mouse.move(a.x+200,a.y+10);await p.mouse.down();await p.mouse.move(a.x+200,a.y+50,{steps:4});ok('dragging shows',await p.locator('.drag-ghost').count()===1);await p.mouse.up();await sleep(100);await p.mouse.down();await p.mouse.up();ok('ghost goes away',await p.locator('.drag-ghost').count()===0);
 await p.mouse.move(a.x+200,a.y+10);await p.mouse.down();await p.mouse.move(a.x+200,a.y+50,{steps:4});await p.evaluate(()=>window.dispatchEvent(new Event('blur')));await sleep(100);ok('losing the window ends a drag',await p.locator('.drag-ghost').count()===0);await p.mouse.up();await sleep(300);}
// completing in the Markdown view reaches the next sync
await p.click('text=Markdown');await p.waitForSelector('textarea');
{const before=log.length;await p.fill('textarea',file.replace('- [ ] Reply to Sam','- [x] Reply to Sam'));await sleep(800);ok('Markdown completion is logged',log.slice(before).some(e=>e.action==='complete'&&e.title.startsWith('Reply to Sam')));}
// typing that collides with a sync: nothing lost, and undo can't overwrite the sync
{await p.locator('textarea').press('End');file=file+'\nfrom the sync\n';const mine=(await p.inputValue('textarea'))+'typed';await p.fill('textarea',mine);await sleep(900);ok('sync wins the file',file.includes('from the sync')&&!file.includes('typed'));ok('your typing is kept in a file',conflicts.at(-1)===mine);ok('says where',await p.isVisible('text=master-conflict'));await p.keyboard.press('Meta+z');await sleep(600);ok('undo does not overwrite the sync',file.includes('from the sync'));}
await p.locator('.notice button').first().click();
// renamed sections keep working
await p.click('.segmented >> text=List');await p.click('nav >> text=Today');{const renamed=file.replace('## 🔥 NOW','## 🔥 Today First');file=renamed;await sleep(3400);ok('renaming NOW keeps its block',await p.isVisible('.block-name:text("Today first")'));}
// an answer stays when a later run finishes
st.last_answer='Here is your answer';st.last_job_output='sync output';await p.fill('.ask input','what next');await p.keyboard.press('Enter');st.job_running='ask';await sleep(3300);st.job_running=null;await sleep(3300);ok('shows the answer, not the last job',await p.isVisible('text=Here is your answer'));
// version check
st.engine_version='0.4.0';await sleep(3300);ok('warns when the engine is out of date',await p.isVisible('text=install.sh --update'));st.engine_version='0.5.1';
await p.click('nav button:has-text("Activity")');await p.waitForSelector('text=Sam Rivera');ok('Activity lists thread notes with both marks',await p.isVisible('text=checked 2026-11-05 10:00:00'));await p.click('button:has-text("Sam Rivera")');await p.waitForSelector('text=Short replies.');ok('a thread note opens',await p.isVisible('text=Short replies.'));
await p.click('nav button:has-text("Setup")');await p.click('button:has-text("Commands")');await p.waitForSelector('text=THESEUS COMMANDS');ok('Setup shows the command list',await p.isVisible('text=THESEUS COMMANDS'));
await sleep(100);ok('still no page errors',errs.length===0);if(errs.length)console.log(errs.slice(0,3));
// the impact view ------------------------------------------------------------
{const IMPACT=`# ★ Master List

## 🔥 NOW
- [ ] Big important · #Biz · ~3h · impact:high · id:t1
- [ ] Quick important · #Biz · ~15m · impact:high · id:t2
- [ ] Quick minor · #Biz · ~10m · impact:low · id:t3
- [ ] Unrated · #Biz · id:t4
- [ ] Home thing · #Home · due 11/4 · ~20m · impact:low · id:t5

## ⏭ NEXT
- [ ] Big minor · #Biz · ~2h · impact:low · id:t7
- [ ] Biz six · #Biz · ~15m · id:t8
- [ ] Biz seven · #Biz · ~15m · id:t9
- [ ] Biz eight · #Biz · ~15m · id:t13
- [ ] Biz nine · #Biz · ~15m · id:t14
- [ ] Home two · #Home · ~1h · id:t10

## ⏳ WAITING ON
- [ ] Waiting thing · #Biz · impact:high · id:t12

## ✅ DONE
`;
 await p.evaluate(()=>localStorage.clear());file=IMPACT;await sleep(3400);
 await p.click('nav >> text=List');await p.click('.segmented >> text=Impact');await p.waitForSelector('.impact-board');
 const bucket=(c)=>p.locator('[data-drop-group="impact:'+c+'"]');const titles=async(c)=>(await bucket(c).locator('.task-title').allInnerTexts());
 ok('impact: a bucket per category, five at most, easiest wins first',JSON.stringify(await titles('Biz'))===JSON.stringify(['Quick important','Big important','Quick minor','Big minor','Biz six']));
 ok('impact: waiting items are left out',!(await p.locator('.impact-board').innerText()).includes('Waiting thing'));
 ok('impact: focus holds each bucket\'s top item',JSON.stringify(await p.locator('.impact-focus .task-title').allInnerTexts())===JSON.stringify(['Quick important','Home thing']));
 ok('impact: opening the view changes nothing',file===IMPACT);
 await p.screenshot({path:OUT+'/impact.png'});
 await bucket('Biz').locator('[data-drag-id="t8"] .impact button:has-text("High")').click();await sleep(700);ok('impact: one click rates it and marks it yours',file.includes('- [ ] Biz six · #Biz · ~15m · impact:high* · id:t8'));
 await bucket('Biz').locator('[data-drag-id="t8"] .impact button:has-text("High")').click();await sleep(700);ok('impact: clicking your rating again takes it off',file.includes('- [ ] Biz six · #Biz · ~15m · id:t8'));
 {const before=file;await bucket('Biz').locator('[data-drag-id="t1"] select.move-to').selectOption('up');await sleep(500);ok('impact: Move up reorders the bucket',(await titles('Biz'))[0]==='Big important');ok('impact: and leaves the list file alone',file===before);
  await bucket('Biz').locator('button:has-text("Reset order")').click();await sleep(300);ok('impact: reset goes back to impact order',(await titles('Biz'))[0]==='Quick important');}
 {const before=file;await drag('Biz six',bucket('Biz').locator('[data-drag-id="t2"]'));await sleep(500);ok('impact: drag within a bucket reorders the view only',(await titles('Biz'))[0]==='Biz six'&&file===before);await bucket('Biz').locator('button:has-text("Reset order")').click();await sleep(300);}
 await bucket('Biz').locator('[data-drag-id="t3"] select.move-to').selectOption('Home');await sleep(700);ok('impact: Move to project changes the category',file.includes('- [ ] Quick minor · #Home · ~10m · impact:low · id:t3'));ok('impact: and it shows in that bucket',(await titles('Home')).includes('Quick minor'));
 await drag('Big minor',bucket('Home').locator('[data-drag-id="t5"]'));await sleep(700);ok('impact: dragging to another bucket changes the category',file.includes('- [ ] Big minor · #Home · ~2h · impact:low · id:t7'));
 await bucket('Biz').locator('[data-drag-id="t1"] .check').click();await sleep(3900);ok('impact: checked off goes to Done in the file',/- \[x\] Big important · #Biz[^\n]*done \d+\/\d+/.test(file));
 ok('impact: it stays in its place, marked completed',(await titles('Biz'))[1]==='Big important'&&await bucket('Biz').locator('text=Completed').isVisible());
 ok('impact: the next one waits to be asked for',(await titles('Biz')).length===5&&await bucket('Biz').locator('text=Add the next one?').isVisible());
 await p.screenshot({path:OUT+'/impact-completed.png'});
 await bucket('Biz').locator('.impact-next button:has-text("Add")').click();await sleep(300);ok('impact: Add puts it at the bottom',(await titles('Biz')).length===6&&!(await bucket('Biz').locator('text=Add the next one?').isVisible()));
 await bucket('Biz').locator('.is-done .check').click();await sleep(700);ok('impact: unchecking reopens it',/- \[ \] Big important · #Biz/.test(file));
 await p.click('.segmented >> text=List');await p.waitForSelector('[data-drag-id="t2"]');ok('impact: the List view is still there',await p.isVisible('[data-drag-id="t2"]'));ok('impact: ratings show as a chip there',await p.locator('[data-drag-id="t2"] .chip-impact').isVisible());
 await sleep(100);ok('impact: no page errors',errs.length===0);if(errs.length)console.log(errs.slice(0,3));}
await b.close();srv.close();

