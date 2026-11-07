#!/bin/bash
# Makes leak-check run automatically before every commit. The hook finds the checkout it's committing in, so worktrees are checked too.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS="$(git -C "$ROOT" rev-parse --git-common-dir)/hooks"
mkdir -p "$HOOKS"
printf '#!/bin/bash\n# Blocks commits that contain private terms.\nexec bash "$(git rev-parse --show-toplevel)/scripts/leak-check.sh" --staged\n' > "$HOOKS/pre-commit"
chmod +x "$HOOKS/pre-commit" && echo "pre-commit leak-check installed"
