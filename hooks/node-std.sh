#!/bin/bash
# SessionStart: node-std.py tells the model once per project and Node standard that the project's Node is behind the
# base's standard, so that it proposes the upgrade as a task of its own (~/.claude/skills/new-project/upgrade.md). Only
# adds context, never blocks: always exit 0. Input without "SessionStart" leaves here, before python starts.
# shim_log <what>: one line, no data, when python cannot run (missing, killed: the 5 s alarm is its own, a kill by the
# hook timeout is 143) or broke before its own log, so doctor.sh shows a dead hook. No line once the log is over 64000 B
shim_log() {
  local log=${NODE_STD_ERRLOG:-$HOME/.claude/logs/node-std.err}
  [ "$(wc -c 2>/dev/null <"$log" | tr -d ' ')" -gt 64000 ] 2>/dev/null ||
    { mkdir -p "$(dirname "$log")" && date -u "+%Y-%m-%dT%H:%M:%SZ $1" >>"$log"; } 2>/dev/null
}
input=$(cat)
[[ $input == *SessionStart* ]] || exit 0
py=/opt/homebrew/bin/python3
[ -x "$py" ] || py=/usr/bin/python3
printf '%s' "$input" 2>/dev/null | "$py" -I "$(dirname "$0")/node-std.py"
rc=${PIPESTATUS[1]}
[ "$rc" = 0 ] || shim_log "ShimExit $rc"
exit 0
