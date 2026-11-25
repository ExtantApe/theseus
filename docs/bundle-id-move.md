# Bundle identifier move: Theseus

Decided D280 (owner, 2026-11-23): apps under the ExtantApe org use `com.extantape.<name>`. Theseus moves from `io.github.mgilardi.theseus` to `com.extantape.theseus` in its next release. Task K724. This overrides the old line that kept the personal-account io.github IDs. The shared self-signed certificate does not change.

## Every place the identifier is used

| Where | Old | What happens |
| --- | --- | --- |
| `apps/desktop/src-tauri/tauri.conf.json` `identifier` | `io.github.mgilardi.theseus` | Changed. A test checks it matches `NEW_ID` in `id_move.rs`. |
| Web view storage, `~/Library/WebKit/<id>` | old id | Copied once. It holds the list view choice, open/closed sections and the Impact view's saved state (`localStorage`). They are conveniences, so a failed copy only resets them. |
| `~/Library/Application Support/<id>` | old id | Copied once if it exists. Theseus itself writes nothing there today (Tauri only creates it on demand), so usually there is nothing to copy. |
| `~/Library/Caches/<id>`, `~/Library/HTTPStorages/<id>`, `~/Library/Preferences/<id>.plist`, `~/Library/Saved Application State/<id>.savedState` | old id | Not copied. macOS rebuilds them. Window position resets once. |
| Workspace `~/Theseus` (`$THESEUS_HOME`), pointer `~/Library/Application Support/Theseus/workspace`, `logs/`, `data/` | named for the product | Nothing to do. These never used the identifier. |
| Launch agents `com.theseus.*` (watchdog, remote, morning, nightly, sync, check, grant, channel, skylight-sync, wall) | own labels | Nothing to do. They are not the bundle id. The watchdog opens the app by its path, so it keeps working. |
| Keychain: service `Theseus Skylight` (`engine/tools/skylight_sync.py`) | a name, not the id | Nothing to do. No Keychain item, service or access group uses the bundle id, so no Keychain copy is needed. The old item is untouched either way. |
| CI (`.github/workflows`) | no mention | Nothing to do. |
| `scripts/leak-allow.txt` | lists the old id | Kept on purpose: the old id still appears in `id_move.rs`, this plan and the changelog, and the leak check refuses it elsewhere. |

## The migration (`apps/desktop/src-tauri/src/id_move.rs`)

Runs at the start of `run()`, before any window exists. For each of the two folders above: if the old one exists and the new one is missing or empty, copy it to a temporary sibling and rename it into place, so a half copy never looks like real data. It never overwrites a new folder that has something in it, never deletes or changes the old folder, and skips symbolic links. When nothing failed it writes `~/Library/Application Support/com.extantape.theseus/id-move.json`, and later launches do nothing. If a copy fails (say a file can't be read), no record is written and the app tries again next launch. The result goes to `logs/app.log` in plain words, with no file contents.

## What users grant again

macOS ties privacy permissions to the app's identifier, so the new Theseus starts with none. After updating, open Theseus, go to the Setup tab and use its buttons, or open **System Settings > Privacy & Security** and add Theseus under:

1. **Full Disk Access** (texts and Mail). You add it yourself with the plus button.
2. **Calendars**
3. **Reminders**
4. **Automation** (the Notes entry under Theseus)
5. **Contacts**

The old Theseus entries stay in those lists and do nothing. They can be removed with the minus button. Terminal and Claude Code keep their own permissions, which don't change.

Not sure: whether the Login Items list shows the watchdog as a new item. Check on a real Mac before release.

## Tested and not tested

Tested: the migration with made-up home folders (copies once, never overwrites, leaves the old data, missing old folder, empty new folder, unreadable file then retry, symbolic links, config matches). Not tested: a real Tauri build and launch, real WebKit storage carrying over, and the permission prompts on a real Mac.
