# Sourced by the run scripts after they cd into the workspace.
# Which Claude Code login Theseus runs on: config.json → claude_config_dir, if it's set. Otherwise Claude Code's default (~/.claude).
CLAUDE_LOGIN_DIR="$(/usr/bin/python3 -c 'import json, os; print(os.path.expanduser((json.load(open("config.json")).get("claude_config_dir") or "").strip()))' 2>/dev/null || true)"
if [[ -n "$CLAUDE_LOGIN_DIR" ]]; then export CLAUDE_CONFIG_DIR="$CLAUDE_LOGIN_DIR"; fi
