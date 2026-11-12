#!/bin/bash
# PermissionRequest Bash: answers the permission prompt of a push of a feature branch with "allow", so that
# git push origin <feature branch> runs with no click (owner's decision 11.11.2026). Every other prompt stays as it
# is: push-allow.py must print "allow" (what it needs is in its docstring), and bash-guard must have nothing to say
# about the same call (exit 0, no output), because the answer of this hook covers the whole call, an ask of
# bash-guard too. A silent hook, a broken one and one past its timeout leave the prompt to the user. Always exit 0.
input=$(cat)
[[ $input == *push* ]] || exit 0
here=$(dirname "$0")
note(){   # note <line>: one line in the log that doctor reads, no data of the command; the log stops at 64 KB
  local log=${PUSH_ALLOW_ERRLOG:-$HOME/.claude/logs/push-allow.err}
  [ "$(wc -c <"$log" 2>/dev/null | tr -d ' ')" -gt 64000 ] 2>/dev/null ||
    { mkdir -p "$(dirname "$log")" && printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" >>"$log"; } 2>/dev/null
}
py=/opt/homebrew/bin/python3
[ -x "$py" ] || py=/usr/bin/python3
out=$(printf '%s' "$input" 2>/dev/null | "$py" -I "$here/push-allow.py"; exit "${PIPESTATUS[1]}")
rc=$?
if [ "$rc" != 0 ]; then   # 3: the script names what it met (an input of another shape, an exception, git with no
  # answer); else python is missing, was killed (4 s alarm: 142) or broke before that
  what="ShimExit $rc"; named='^(ShapeDrift|Error) [A-Za-z0-9_. ]+$'
  out=${out%%$'\n'*}; [[ $rc != 3 || ! ${out:0:120} =~ $named ]] || what=${out:0:120}
  note "$what"; exit 0
fi
case $out in
  allow) ;;
  pass) exit 0 ;;
  *) note ShimOutput; exit 0 ;;   # neither word: a script of another version
esac
said=$(printf '%s' "$input" 2>/dev/null | "$here/bash-guard.sh" 2>&1; exit "${PIPESTATUS[1]}")
rc=$?
[ "$rc" = 0 ] || [ "$rc" = 2 ] || note "GuardExit $rc"   # 2 is its block; any other code is a bash-guard that broke
[ "$rc" = 0 ] && [ -z "$said" ] || exit 0
printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}'
exit 0
