#!/bin/bash
# SessionStart: put the Node version from .nvmrc first on PATH for Bash tool calls
[ -f .nvmrc ] && [ -n "$CLAUDE_ENV_FILE" ] || exit 0
export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh" --no-use >/dev/null 2>&1 || exit 0
n=$(nvm which "$(cat .nvmrc)" 2>/dev/null) || exit 0
[ -x "$n" ] && echo "export PATH=\"$(dirname "$n"):\$PATH\"" >> "$CLAUDE_ENV_FILE"
exit 0
