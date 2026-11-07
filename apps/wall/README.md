# Wall display

Your list on a TV or monitor, from a Raspberry Pi. Your Mac sends the Pi a filtered snapshot, and the Pi draws it. No Claude is involved.

**This hasn't run on a real Pi yet.** The screen and the delivery path are tested, but `pi/install.sh` isn't.

The design, including what's still to come, is in [docs/design/wall-display.md](../../docs/design/wall-display.md).

| Folder | What's in it |
|---|---|
| `display/` | The screen. Plain HTML, CSS and JavaScript with no dependencies |
| `pi/` | `receive.py` (the only thing the Mac's key can run), `serve.py` (serves the page on the Pi only), `power.py` (sleeps and wakes the TV with your active hours) and `install.sh` |
| `prototype/` | The drag-and-drop builder prototype and a mockup of the screen's states. Not used by anything yet, and the tasks in them are invented |
| `e2e.mjs` | The screen in a real browser: `node apps/wall/e2e.mjs` |

## Connecting a Pi

You'll need a Pi 4 or 5 with Pi OS Lite (64-bit), on the same network as your Mac. Either model works the same way. Use the HDMI port next to the power connector.

1. Write the card with Raspberry Pi Imager. Set the hostname to `theseus-wall`, and add your Wi-Fi and your Mac's SSH public key.
2. Start the Pi, and check this logs in without a password:

   ```bash
   ssh theseus-wall.local
   ```

3. Connect it. Add `--user <name>` if your Pi username isn't your Mac username:

   ```bash
   theseus wall setup theseus-wall.local
   ```

To see exactly what your screen gets, with or without a Pi:

```bash
theseus wall show
```

## Active hours

The screen sleeps outside its active hours. They follow your wake and bed times until you set your own:

```bash
theseus wall hours 6am 12am
```

Outside them the page goes black, and the Pi asks the TV to go to standby. Some TVs need HDMI-CEC turned on in their settings, and if yours doesn't respond, the screen just stays black. `theseus wall hours always` keeps it on.

## Changing views

`theseus wall view board` changes the view. Until the builder arrives, layouts can be edited by hand in `data/wall-views.json` in your workspace, using a 24 by 14 grid. To start that file from the defaults, run `theseus wall view sectors`.
