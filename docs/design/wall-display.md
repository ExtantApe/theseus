# Wall display: your list on a TV or monitor, arranged your way

**Status:** the display is built and waiting for its first run on a real Pi. The builder page is a prototype, not yet part of the app. Decision record: [ADR 0008](../adr/0008-wall-display-sends-to-a-pi.md).

| File | What it is | How to try it |
|---|---|---|
| [wall-builder-prototype.html](../../apps/wall/prototype/wall-builder-prototype.html) | The builder as a prototype: drag, resize, make views, set active hours, undo | Open it in a browser |
| [wall-display-mockup.html](../../apps/wall/prototype/wall-display-mockup.html) | The screen's states | Open it in a browser and press 1 to 6 |

## What exists today

| Part | State |
|---|---|
| `theseus wall` on the Mac, the filter, delivery, the background job | Built, and tested against a simulated Pi. See [how it's tested](#how-its-tested) |
| The screen (`apps/wall/display`) | Built and tested in Chromium and WebKit, in landscape and portrait, from 720p to 4K |
| Active hours | Built: `theseus wall hours 6am 12am`. The page goes black outside them, and the TV is asked to sleep. **TV sleep hasn't been tried on a real TV** |
| The Pi kit (`apps/wall/pi`) | Built, and installs on simulated Debian bookworm and trixie. **It has never run on a real Pi** |
| The builder page in the Mac app | Not built. Views can be edited by hand in `data/wall-views.json`, and `theseus wall view <name>` switches between them |
| App-hosted delivery and finding a Pi on the network | Not built. Delivery runs from a launch agent, and setup takes a host name |

## The idea

Look up and see what matters, arranged how you like.

Your Mac holds the list and all the decisions. The Pi only draws the screen. It can't change your list, can't reach your Mac, and has no Claude on it.

```
 YOUR MAC                                                 RASPBERRY PI
 data/master.md ──────┐                                   ┌─> the screen
 data/wall-views.json ┴─> wall.py ─> wall.json ─ ssh ─> receive.py
                          filters    the only thing       checks it, and
                          + scrubs   that ever leaves     keeps it in memory
                          no Claude
```

## What this has to get right

| Need | How the design meets it |
|---|---|
| Readable in a glance | A large top task, then the rest in large type sized from the screen height |
| Doesn't use Claude | Reads `master.md` directly, like `theseus next` |
| Not one more thing to manage (manifesto 2) | Starter views work on day one, and nothing needs doing on the Pi after setup |
| Nothing goes out or moves without you | The Pi only receives. There's no path from it back to your list |
| When in doubt, it doesn't happen | Sections and titles are shown only if you allowed them. A failed check means no title |
| Tells the truth | The screen says how old the list is, and marks it when it may be out of date |
| Never makes you feel behind | No red and no "OVERDUE". A missed date reads "Was due Tue" in amber |

## Views you build yourself

Editing will happen on the Mac, in a Wall page in Theseus.app. The TV has no mouse or keyboard, and doesn't need one.

- **Drag and resize** any piece on a grid (24 by 14 in landscape, 14 by 24 in portrait). Pieces can't overlap: dropped on another piece, one goes back and says why.
- **As many views as you like.** Add, duplicate, rename and remove them.
- **Saved as you go**, with undo and redo, like the list. Layouts live in your workspace at `data/wall-views.json`.
- **Portrait starts for you.** A view's portrait layout begins as its landscape pieces stacked in order, and is its own from then on.
- **Nothing to set up unless you want to.** Starter views work on day one.

**Pieces:** Top task · Task list · One sector · All sectors · Coming due · Counts · Clock · Text · Status line.

**Making your own:** set a piece up the way you like (say, Home tasks from Next, large text, no dates), then choose **Save as my piece**. It joins your palette under Yours.

**Starter views:** a new screen starts with Sectors, Ranked, One thing, Board and Clock. The prototype adds Coming due and Home as examples.

**Which view shows:** by time of day, taking turns every few minutes, or staying on one (the default). `theseus wall view <name>` changes it from your Mac, or your phone through Remote Control.

**Pieces fit honestly.** Text stays at the size you picked. What doesn't fit becomes "5 more". In All sectors, each sector gives up its lowest-ranked tasks evenly, so a busy list still shows every sector for as long as it can.

### Active hours

The screen has working hours, set with the views in the builder, or with `theseus wall hours 6am 12am`. They can cross midnight.

- **Inside them,** the screen shows your views.
- **Outside them,** the page goes black and the Pi asks the TV to go to standby over HDMI. In the morning it asks the TV to wake.
- **It only acts when the hours change over.** If you switch the TV on at 2am, it isn't turned straight back off.
- **A monitor that ignores HDMI commands** just shows black.
- **If you never set them,** they follow your wake time and bed time from your schedule. `theseus wall hours always` keeps the screen on.

The Pi's clock has to be right for this and for "Due today", so setup gives the Pi your Mac's time zone.

### Sectors

"Sector" means your existing `#categories`. Every open item already has exactly one. Sectors appear in the order of their highest-ranked task, and each task keeps its own small number, so your priority order stays readable. Grouping shows the shape of your day; it doesn't replace the ranking.

### Custom pieces are settings, not code

Pieces you make combine what the built-in pieces can do. There's no plug-in system, because outside code would be running beside your list. New piece types get added to Theseus itself.

## The screen's states

| State | What shows | When |
|---|---|---|
| Views | Your list, as you arranged it | Normal, once you've allowed titles |
| Counts | "14 in Now", due today, past its date. No titles or sectors | The default until you choose |
| Out of date | Everything dimmed, with an amber note: "This list is from 6 hours ago. Your Mac may be asleep." | No word from the Mac for 15 minutes |
| All clear | "Nothing left in Now." | NOW is empty |
| Waiting | "Waiting for your Mac", with the command to check | After a restart, until the first delivery, or if it gets something it doesn't understand |
| Dark | Black, and the TV asked to sleep | Outside active hours |

The out-of-date note is drawn by the screen itself, so no layout can leave it out.

Design rules:

- **Dark, using the family colors.** The tokens match `ui/family.css`. A cream screen would light up the room.
- **Amber only means a status**, following the brand rule. It marks a missed date or an old list, nothing else.
- **No motion.** A view always looks the same, so you know where to look. Taking turns between views is something you choose.
- **Line icons, no emoji.** Titles get the same emoji clean-up as the app.
- **Inset from the edges** so TV overscan can't crop it.
- **Inter, from the Pi's own fonts** (`fonts-inter`), so nothing is downloaded by the page.

## The extension interface

### The snapshot: `wall.json`

Anything that can read this file can be a display, such as a MagicMirror module or a phone widget. Other displays can ignore `views`.

```json
{
  "schema": 1,
  "generated_at": "2026-11-05T08:41:00-08:00",
  "mode": "titles",
  "sections": {
    "now": {
      "title": "Now",
      "open": 14,
      "more": 0,
      "kept_private": 1,
      "items": [
        { "number": 8, "title": "Call about the gutter estimate", "due": "11/12", "due_date": "2026-11-12", "category": "Home" }
      ]
    },
    "waiting on": { "title": "Waiting On", "open": 3 }
  },
  "views": [ { "name": "Sectors", "when": null, "layouts": { "landscape": [ { "type": "top", "x": 0, "y": 0, "w": 17, "h": 3, "opts": { "section": "now", "size": "XL" } } ], "portrait": null } } ],
  "change": { "mode": "fixed", "minutes": 5, "active": "Sectors" },
  "display": { "on": "06:00", "off": "00:00" }
}
```

- **Only what your views use.** If no view shows Later, its titles never reach the Pi.
- **Counts mode sends no titles or views at all.** The Pi can't leak what it never received.
- **The Pi never gets ids, notes, links or reminder details.**
- **Dates are worked out on the display** from `due_date`, so "Due today" stays true while the Mac sleeps.
- **Numbers are each task's current position**, unique across everything sent. They show your order, and they aren't stored anywhere.
- **Unknown piece types and newer schemas** show the Waiting state, not a guess.

### The command: `theseus wall`

| Command | What it does |
|---|---|
| `theseus wall show` | Prints exactly what the screen would get. Works with no Pi |
| `theseus wall setup <host>` | Connects a Pi, once |
| `theseus wall titles on\|off` | Shows or hides titles |
| `theseus wall view <name>` | Changes the view |
| `theseus wall hours <from> <to>` | Sets active hours, like `6am 12am` or `06:00 00:00`. `hours always` keeps the screen on |
| `theseus wall status` | Last delivery, and anything that failed |
| `theseus wall push` | Sends now if something changed |
| `theseus wall off` | Clears the screen and stops everything |

### Settings

```json
"wall": { "enabled": false, "host": "theseus-wall.local", "titles": false, "private_categories": [] }
```

That's in `config.json`. Views, how they change and active hours live in `data/wall-views.json`, because the builder edits them together. If `wall` is missing or `enabled` is false, nothing runs.

## What can reach the wall

One function in `engine/tools/wall.py` decides, and each rule has a test that tries to break it.

1. **It reads `data/master.md` and nothing else.** Not `today.md`, which holds texts, email and who's waiting on you.
2. **Only sections your views use** are sent.
3. **Communications and DONE can never appear**, even if a layout file is edited by hand to ask for them.
4. **Items in a `private_categories` category** are left out, and counted as "kept private".
5. **A title that looks like an email, phone number or web address** is left out in the same way.
6. **Titles stay off until you choose.** Setup asks: "Who can see this screen?" "Just me" turns them on. "Other people too" keeps counts.

This is a conscious change from APP-PLAN's earlier "wall-safe by default", which meant no titles at all. Waiting On titles often name people, so the starter views only count that section. The builder should say so if you add its titles to a view.

## How it gets there

**The Mac sends to the Pi over SSH.** The earlier plan had the Mac serving a page, but sending is better in three ways:

- **The Mac opens no port.** Nothing on your network can ask it for your list.
- **The last list stays up.** The Pi keeps what it last received when the Mac sleeps.
- **The traffic is encrypted, using tools already on both machines.**

| Step | Detail |
|---|---|
| When | A launch agent runs `wall.py push` every 30 seconds. It moves into the app when the builder does |
| What's sent | The snapshot if it changed, and every 5 minutes regardless. That heartbeat is how the screen tells "nothing changed" from "the Mac is asleep" |
| Latency | A check-off reaches the wall in about 30 seconds, whoever made it: the app, Terminal or a sync |
| Key | A dedicated key in `.wall/` in your workspace, limited on the Pi with `restrict,command="…/receive.py"`. It can deliver or clear, and it can't open a shell |
| Host check | The Pi's host key is pinned at setup, so a device pretending to be the Pi later gets nothing |
| Failure | The screen's age note shows it, and `theseus wall status` says why |

## Hardware

- **A Raspberry Pi 4 or 5, either one.** Nothing is specific to a model: the same 64-bit Pi OS Lite, the same packages, and the same kit. A Pi 4 with 2 GB should be enough for one browser page, though that's untested.
- **Use the HDMI port next to the power connector.** Both models have two, and that one is HDMI 0.
- **Power:** the Pi's own supply, not the TV's USB port.

## On the Pi

Pi OS Lite and no desktop.

| Part | What it does |
|---|---|
| `receive.py` | Takes a snapshot up to 256 KB, checks shape, piece types, grid bounds and hours, and swaps the file in whole |
| `serve.py` | Serves the page and the snapshot on `127.0.0.1` only |
| Screen | `cage` running Chromium fullscreen, with a strict content policy, so the page can't load anything from anywhere. Text only ever goes in as text |
| `power.py` | Runs once a minute, and asks the TV to sleep or wake when active hours change over |

- The list stays in RAM (`/run`), so a stolen or unplugged Pi holds no list. The screen shows Waiting until the Mac next delivers.
- Security updates install themselves, password login is off, and the page and its server are reachable only from the Pi itself.

### Setup

1. Write Pi OS Lite (64-bit) with Raspberry Pi Imager. Set the hostname to `theseus-wall`, and add your Wi-Fi and your Mac's SSH public key.
2. Plug it into the TV and run `theseus wall setup theseus-wall.local`. This installs the kit from your workspace, creates the limited key, pins the host key, sets the time zone and sends a first snapshot.
3. It asks one question: **"Who can see this screen?"**

The Mac app later gets a Display card with the same steps. It would find the Pi on your network and show a code on the TV to confirm, because anything on your Wi-Fi could claim to be a display. Step 1 stays manual.

## Where the code goes

```
engine/tools/wall.py          snapshot, filter, delivery, setup
engine/tools/cli.py           `theseus wall`
apps/wall/display/            the screen: one renderer, for the Pi now and the app's builder later
apps/wall/pi/                 receive.py, serve.py, power.py, install.sh
apps/wall/prototype/          the builder prototype and the screen mockup
apps/wall/e2e.mjs             the screen in a real browser
tests/test_engine.py          the promise tests
apps/desktop/src/Wall.tsx     later: the builder page, on the app's Setup tab until a display is connected
```

`install.sh` copies `apps/wall/display` and `apps/wall/pi` to `wall/` in your workspace, so `theseus wall setup` can hand them to a Pi. One renderer means the builder's picture and the TV's picture can't drift apart.

## How it's tested

| Command | What it covers | What's real, and what isn't |
|---|---|---|
| `python3 tests/test_engine.py` | The filter's promises, the commands, the settings, the launch agent file | Real code, with a stand-in for `ssh` and for HDMI commands |
| `node apps/wall/e2e.mjs` | Every view at four sizes, every state, active hours, a whole night on an open page with a fast-forwarded clock, hostile titles | Real browsers and the real `serve.py`. The snapshots are written directly |
| `python3 apps/wall/sim/test_connection.py` | First connect, updates, the Pi hung or off, a reboot, bad data, a changed identity, active hours, the kiosk, turning it off. On a Mac, also the real launchd job | The Mac-side code, `ssh`, a real TCP connection, an SSH server, Linux users, `sudo`, the real `install.sh` and packages, systemd, Chromium and cage are all real. **Docker stands in for the Pi, a headless output for HDMI, and a recording script for `cec-ctl`** |

### What only a real Pi and TV can show

- Whether Chromium and cage work on a Pi's GPU and HDMI output, at your TV's resolution, and whether the page fills the screen. On simulated trixie it does. On simulated bookworm, whose older cage is confused by a headless output, the page filled only a corner, so bookworm is unproven.
- Whether your TV obeys the sleep and wake commands. Only the commands sent have been checked, against the `cec-ctl` manual.
- Whether the text is readable from where you sit, and how the screen looks in your room.
- Whether a Pi 4 or 5 keeps up. All testing ran on an Apple silicon Mac.
- Wi-Fi drops, `.local` names on your network, and real power cuts. A stopped, paused and restarted container is the nearest thing tested.
- Differences between Pi OS and plain Debian, and Raspberry Pi Imager's setup, which the simulated image only imitates.
- The Mac asleep for real. It's simulated by moving the screen's clock forward and by delivery stopping.

## Build order

| Phase | Scope | Done when |
|---|---|---|
| **1. Snapshot** (built) | `wall.py`, `theseus wall show`, tests | You can read the exact output on your Mac |
| **2. Screen** (built) | The shared renderer, reading a snapshot | It runs in any browser with real data |
| **3. Pi kit** (built, not yet run on a Pi) | `receive.py`, services, `setup`, the background job, active hours | The list is on your TV, survives a restart, and sleeps on time |
| **4. One week of use** | Live with it | You use it, and it hasn't needed attention |
| **5. Builder** | The Wall page in the app with active hours beside the views, delivery from the app, finding a Pi on the network | You rearrange a view and the TV follows |

## Known risks

- **The Pi installer hasn't met a real Pi.** It runs on simulated Debian bookworm and trixie, which already caught bugs that would have blanked the screen, but Pi OS and real graphics may still differ.
- **TV sleep varies.** HDMI-CEC support differs by TV, and some need it turned on in their settings. If it does nothing, the screen is still black.
- **macOS Local Network permission.** macOS 15 and later restrict apps reaching devices on your network, and the app's `Info.plist` has no `NSLocalNetworkUsageDescription` yet. It'll need one when delivery moves into the app. A one-off check on macOS 15 found a launch agent could reach a local device with `ssh`, so the current background job should work, and `theseus wall status` will say if it doesn't.
- **Less to manage, never more (manifesto 2).** Drag-and-drop views are a new thing to fiddle with. The starter views have to be good enough that the builder stays optional, and the week of use is the real test.
- **OLED burn-in** with fixed layouts: active hours help. On an OLED, the layout should also shift slightly every few minutes.
