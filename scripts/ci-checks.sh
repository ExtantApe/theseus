#!/bin/bash
# What CI checks beyond building the app. Run it locally too.
set -euo pipefail
cd "$(dirname "$0")/.."
bash scripts/leak-check.sh
for f in install.sh engine/install.sh engine/scheduled/*.sh scripts/*.sh; do bash -n "$f"; done
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 - <<'PY'
import glob, json
for f in glob.glob("engine/tools/*.py"):
    compile(open(f).read(), f, "exec")
for f in ["engine/templates/config.json", "engine/templates/settings.json", ".claude-plugin/plugin.json", ".claude-plugin/marketplace.json"]:
    json.load(open(f))
PY
swiftc -typecheck engine/tools/ek.swift
cmp <(sed '/^SRC=/d' install.sh) <(sed '/^SRC=/d' engine/install.sh) || { echo "install.sh and engine/install.sh differ"; exit 1; }
echo "✅ checks passed"
