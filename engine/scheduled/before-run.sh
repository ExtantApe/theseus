#!/bin/bash
# What every scheduled run needs first, whichever host starts it (Theseus.app or launchd): helper apps open, old logs and backups gone.
set -u
WS="${THESEUS_HOME:-$HOME/Theseus}"
cd "$WS" || exit 1
mkdir -p logs briefings cache
chmod 700 "$WS"   # your list, logs and copies are yours alone
tmutil isexcluded cache 2>/dev/null | grep -q Excluded || tmutil addexclusion cache 2>/dev/null   # copies don't belong in backups
# config.json → "ensure_apps": ["Claude", "Mail"]. Apple Mail is added automatically when email_source is "apple_mail".
/usr/bin/python3 - "$WS/config.json" <<'PY' | while IFS= read -r app; do
import json, sys
try:
    c = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
apps = list(c.get("ensure_apps", []))
if c.get("email_source") == "apple_mail" and "Mail" not in apps:
    apps.append("Mail")
print("\n".join(apps))
PY
  [[ -z "$app" ]] && continue
  if ! pgrep -xq "$app"; then
    open -g -j -a "$app" 2>/dev/null && echo "$(date) opened $app" >> logs/apps.log
    sleep 20   # give it a moment to launch (e.g. Mail fetching new mail)
  fi
done
find logs -type f ! -name '.*' -mtime +30 -delete 2>/dev/null
find data/archive -name 'master-app-*.md' -mtime +14 -delete 2>/dev/null
find data/archive -name 'master-conflict-*.md' -mtime +30 -delete 2>/dev/null
exit 0
