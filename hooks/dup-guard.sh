#!/bin/bash
# PostToolUse Edit|Write|MultiEdit: dup-guard.py notes new JS/TS helpers that already exist in the repo.
# Only adds context, never blocks: always exit 0. Other file types leave here, before python starts (~40% of edits).
input=$(cat)
re='"file_path"[[:space:]]*:[[:space:]]*"([^"]*)"'
if [[ $input =~ $re ]]; then
  case ${BASH_REMATCH[1]} in
    *.ts | *.tsx | *.js | *.jsx | *.mjs | *.cjs) ;;
    *) exit 0 ;;
  esac
fi
py=/opt/homebrew/bin/python3
[ -x "$py" ] || py=/usr/bin/python3
printf '%s' "$input" 2>/dev/null | "$py" -I "$(dirname "$0")/dup-guard.py"
rc=${PIPESTATUS[1]}
if [ "$rc" != 0 ]; then   # python missing, killed (4 s alarm: 142) or broken before its own log: one line, no data
  log=${DUP_GUARD_ERRLOG:-$HOME/.claude/logs/dup-guard.err}
  [ "$(wc -c <"$log" 2>/dev/null | tr -d ' ')" -gt 64000 ] 2>/dev/null ||
    { mkdir -p "$(dirname "$log")" && date -u "+%Y-%m-%dT%H:%M:%SZ ShimExit $rc" >>"$log"; } 2>/dev/null
fi
exit 0
