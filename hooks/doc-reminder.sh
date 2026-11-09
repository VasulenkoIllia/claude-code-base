#!/bin/bash
# PostToolUse|PostToolUseFailure Bash: after a git commit with code and no docs, doc-reminder.py reminds the model of
# the docs. Only adds context, never blocks: always exit 0. A call whose command runs no git commit leaves here,
# before python starts (almost every call; most of them before jq too).
# shim_log <what> [cap]: one line, no data, when jq or python cannot run (missing, killed: the 4 s alarm is 142, does
# not compile, an odd output) or python broke before its own log, so doctor.sh shows a dead hook; and ShapeDrift
# <fields> when an input field the hook reads came with another type or not at all (a Claude Code update changed the
# input?): the hook then goes on as before. No line once the log is over cap bytes (64000); ShapeDrift comes with every
# commit while the input stays odd, so it stops at DRIFT_CAP and leaves room for the line of a hook that dies later
DRIFT_CAP=32000
shim_log() {
  local log=${DOC_REMINDER_ERRLOG:-$HOME/.claude/logs/doc-reminder.err}
  [ "$(wc -c 2>/dev/null <"$log" | tr -d ' ')" -gt "${2:-64000}" ] 2>/dev/null ||
    { mkdir -p "$(dirname "$log")" && date -u "+%Y-%m-%dT%H:%M:%SZ $1" >>"$log"; } 2>/dev/null
}
input=$(cat)
[ -n "$input" ] || { shim_log 'ShapeDrift input' "$DRIFT_CAP"; exit 0; }
[[ $input == *git* && $input == *commit* ]] || exit 0
# three parts: the fields of an unknown shape on the first line, maybe none (tool_input only for Bash; duration_ms only
# when it is there), the command, then "end" ($(...) drops trailing newlines: without it a cut output looks whole)
out=$(printf '%s' "$input" | /usr/bin/jq -r '
  def bad($k; $t): if (.[$k] | type) == $t then empty else $k end;
  def odd($k; $t): if has($k) and (.[$k] | type) != $t then $k else empty end;
  if type != "object" then "input\n\nend" else
  ([bad("hook_event_name"; "string"), bad("tool_name"; "string"),
    (if .tool_name != "Bash" then empty
     elif (.tool_input | type) != "object" then "tool_input"
     else .tool_input | bad("command"; "string") | "tool_input." + . end),
    bad("cwd"; "string"), bad("transcript_path"; "string"), odd("duration_ms"; "number")] | join(" "))
  + "\n" + ([.tool_input | objects | .command | strings][0] // "") + "\nend" end' 2>/dev/null); rc=$?
# jq-1.7.1: 5 is input that is not JSON, or a runtime error of the filter (valid input, checked with jq empty: a dead
# hook); any other code (usage, does not compile, missing, killed) is a dead hook
case $rc in
  0) ;;
  5) printf '%s' "$input" | /usr/bin/jq empty 2>/dev/null && { shim_log "JqExit 5"; exit 0; }
     shim_log 'ShapeDrift input' "$DRIFT_CAP"; exit 0 ;;
  *) shim_log "JqExit $rc"; exit 0 ;;
esac
# the three parts, and a closed set of field names on the first line: anything else is a broken jq
F='^((input|hook_event_name|tool_name|tool_input(\.command)?|cwd|transcript_path|duration_ms)( |$))*$'
[[ $out == *$'\n'*$'\nend' ]] || { shim_log JqOutput; exit 0; }
out=${out%$'\nend'}
drift=${out%%$'\n'*}
cmd=${out#*$'\n'}
[[ $drift =~ $F ]] || { shim_log JqOutput; exit 0; }
[ -z "$drift" ] || shim_log "ShapeDrift $drift" "$DRIFT_CAP"
cmd=${cmd//\\$'\n'/ }   # a backslash-newline continuation is one line for the shell
# git [-c x=y | -C dir]... commit, as r_commit in bash-guard.sh
W='("[^"]*"|'"'"'[^'"'"']*'"'"'|[^[:space:];&|"'"'"'])+'
G="git([[:blank:]]+-[cC][[:blank:]]+$W)*[[:blank:]]+commit([[:space:];&|)]|$)"
[[ $cmd =~ $G ]] || exit 0
py=/opt/homebrew/bin/python3
[ -x "$py" ] || py=/usr/bin/python3
printf '%s' "$input" 2>/dev/null | "$py" -I "$(dirname "$0")/doc-reminder.py"
rc=${PIPESTATUS[1]}
[ "$rc" = 0 ] || shim_log "ShimExit $rc"
exit 0
