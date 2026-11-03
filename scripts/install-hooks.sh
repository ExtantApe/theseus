#!/bin/bash
# Makes leak-check run automatically before every commit.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT/.git/hooks"
printf '#!/bin/bash\nexec "%s/scripts/leak-check.sh" --staged\n' "$ROOT" > "$ROOT/.git/hooks/pre-commit"
chmod +x "$ROOT/.git/hooks/pre-commit" && echo "pre-commit leak-check installed"
