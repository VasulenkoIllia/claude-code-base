#!/bin/bash
# docs-sync: mirrors the docs a project keeps outside git into the docs repo (docs_sync.py says what and how). git runs
# "docs-sync.sh hook post-commit|pre-push" from hook.docs-sync.* and hook.docs-sync-push.* in the .git/config of a
# connected project; the owner runs the other commands (init, connect, disconnect, register, sync, push, report).
# A hook never stops a commit or a push (a pre-push hook with any other code stops the push): always exit 0, also when
# the reader of stderr is gone (git push 2>&1 | head -1: the echo below would end the shim with 141). python missing
# (127), killed (the alarm: 142) or broken before its own log: one line, no data, in the error log
py=/opt/homebrew/bin/python3
[ -x "$py" ] || py=/usr/bin/python3
[ "$1" = hook ] || exec "$py" -I "$(dirname "$0")/docs_sync.py" "$@"
trap '' PIPE
[ "$2" != pre-push ] || cat >/dev/null   # the refs git writes to a pre-push hook: read them all
"$py" -I "$(dirname "$0")/docs_sync.py" "$@" </dev/null
rc=$?
if [ "$rc" != 0 ]; then
  log=${DOCS_SYNC_ERRLOG:-$HOME/.claude/logs/docs-sync.err}
  [ "$(wc -c 2>/dev/null <"$log" | tr -d ' ')" -gt 64000 ] 2>/dev/null ||
    { mkdir -p "$(dirname "$log")" && date -u "+%Y-%m-%dT%H:%M:%SZ ShimExit $rc" >>"$log"; } 2>/dev/null
  case $rc in 127) why='python3 missing' ;; 142) why='over 60 s' ;; *) why="exit $rc" ;; esac
  t='~'   # bash 3.2 keeps the backslash of ${log/#$HOME/\~}
  echo "docs-sync: the docs are not mirrored ($why; the error log ${log/#$HOME/$t})" >&2
fi
exit 0
