#!/bin/bash
# PostToolUse Bash and SessionStart compact: after a git push that ran, and after every compaction, the model gets one
# line of additionalContext: if the next step is a different task, end the turn with a new-session card instead of
# continuing here; after a compaction also the owner's language. After a gh pr create that opened a PR: wait for CI in
# the background, since the app wakes a session only on red, never on green, and on green run gh pr merge at once: its
# permission prompt (the ask rule in settings.json) is the owner's decision, a button before it was a second
# confirmation of the same step (owner's decision 11.11.2026).
# Only adds context, never blocks: always exit 0. Silent for a subagent (agent_id in the input: only the main session
# can start one), a dry run and a push whose output says it failed (git push 2>&1 | tail exits 0). As in bash-guard,
# git push in the text of a command (a heredoc, echo, grep, a commit message) counts too. A Bash call without "push" or
# "pr create" (almost every call) leaves here before jq starts. SESSION_HINT_DEBUG=1: the reason for silence on stderr.
# shim_log <what> [cap]: one line, no data, when jq fails (missing, killed, does not compile, a runtime error on valid
# JSON, an odd verdict), so doctor.sh shows a dead hook; and ShapeDrift <fields> when an input field the hook reads
# came with another type or not at all (a Claude Code update changed the input?): the hook then goes on as before. No
# line once the log is over cap bytes (64000); ShapeDrift comes with every call while the input stays odd, so it stops
# at DRIFT_CAP and leaves room for the line of a hook that dies later
DRIFT_CAP=32000
shim_log() {
  local log=${SESSION_HINT_ERRLOG:-$HOME/.claude/logs/session-hint.err}
  [ "$(wc -c 2>/dev/null <"$log" | tr -d ' ')" -gt "${2:-64000}" ] 2>/dev/null ||
    { mkdir -p "$(dirname "$log")" && date -u "+%Y-%m-%dT%H:%M:%SZ $1" >>"$log"; } 2>/dev/null
}
quiet() { [ -z "$SESSION_HINT_DEBUG" ] || echo "session-hint: $1" >&2; exit 0; }
emit() {
  printf '{"hookSpecificOutput":{"hookEventName":"%s","additionalContext":"session-hint: %s"}}\n' "$1" "$2"
  exit 0
}
# hint <event> <what happened> <what the next step is not>: the line, the same for the app and the CLI
hint() {
  local next="If the next step is a different task or feature$3, don't start it here: end this turn with a new-session"
  next+=" card and a short brief (app: start_session, or hand_off_to_session for work in progress; CLI: update the"
  next+=" STATUS checkpoint and suggest a new session). Same task: continue."
  emit "$1" "$2 $next"
}
export LC_ALL=C   # [[:space:]] and [[:blank:]] mean ASCII only, as in tests/hint_common.py, whatever the user's locale
input=$(cat)
[ -n "$input" ] || { shim_log 'ShapeDrift input' "$DRIFT_CAP"; quiet 'empty input'; }
[[ $input == *push* || $input == *'pr create'* || $input == *SessionStart* ]] ||
  quiet 'no push, pr create or SessionStart in the input'
# the first line: the fields of an unknown shape (a Bash call's in PostToolUse only), maybe none; the verdict on the
# second; for a push candidate the command follows it
out=$(printf '%s' "$input" | /usr/bin/jq -r '
  def bad($k; $t): if (.[$k] | type) == $t then empty else $k end;
  if type != "object" then "input\nnot an object" else
  ([bad("hook_event_name"; "string"),
    (if .agent_id != null and (.agent_id | type) != "string" then "agent_id" else empty end),
    (if .hook_event_name == "SessionStart" then bad("source"; "string")
     elif .hook_event_name != "PostToolUse" then empty
     else bad("tool_name"; "string"),
       (if .tool_name != "Bash" then empty
        elif (.tool_input | type) != "object" then "tool_input"
        else .tool_input | bad("command"; "string") | "tool_input." + . end),
       (if .tool_name != "Bash" then empty
        elif (.tool_response | type) != "object" then "tool_response"
        else .tool_response | (bad("stdout"; "string"), bad("stderr"; "string")) | "tool_response." + . end) end)]
   | join(" ")) + "\n" +
  (if (.agent_id // "") != "" then "subagent"
  elif .hook_event_name == "SessionStart" then (if .source == "compact" then "compact" else "other source" end)
  elif .hook_event_name != "PostToolUse" or .tool_name != "Bash" or ([.tool_input | objects | .command | strings]
    | length) == 0 then "other event, tool or input"
  else ([.tool_response | objects | .stdout, .stderr | strings] | join("\n")) as $o
    | if $o | test("failed to push some refs|\\[(remote )?rejected\\]|(^|\n)fatal: ") then "push failed"
      elif ($o | test("/pull/[0-9]+")) and ($o | contains("already exists") | not) then "opened\n" + .tool_input.command
      else "command\n" + .tool_input.command end end) end' 2>/dev/null); rc=$?
# jq-1.7.1: 5 is input that is not JSON, or a runtime error of the filter (valid input, checked with jq empty: a dead
# hook); 2 (usage, system), 3 (does not compile), 1, 4, 6.. and 126+ (missing, killed) are a dead hook
case $rc in
  0) ;;
  5) printf '%s' "$input" | /usr/bin/jq empty 2>/dev/null && { shim_log "JqExit 5"; exit 0; }
     shim_log 'ShapeDrift input' "$DRIFT_CAP"; quiet 'not json' ;;
  *) shim_log "JqExit $rc"; exit 0 ;;
esac
# a closed set of field names on the first line, as of verdicts below: anything else is a broken jq
F='^((input|hook_event_name|agent_id|source|tool_name|tool_input(\.command)?|tool_response(\.stdout|\.stderr)?)( |$))*$'
drift=${out%%$'\n'*}
[[ $out == *$'\n'* && $drift =~ $F ]] || { shim_log JqOutput; exit 0; }
out=${out#*$'\n'}
[ -z "$drift" ] || shim_log "ShapeDrift $drift" "$DRIFT_CAP"
case $out in   # a closed set of verdicts: anything else (empty, cut, two verdicts) is a broken jq
  compact) hint SessionStart 'the context was just compacted. Відповідай українською, також wrap_up, плани, квізи.' '' ;;
  'not an object' | subagent | 'other source' | 'other event, tool or input' | 'push failed') quiet "$out" ;;
  command | opened) quiet 'empty command' ;;   # $(...) drops the newline after the verdict when the command is empty
  command$'\n'* | opened$'\n'*) ;;
  *) shim_log JqOutput; exit 0 ;;
esac
verdict=${out%%$'\n'*}
cmd=${out#*$'\n'}
cmd=${cmd//\\$'\n'/ }   # a backslash-newline continuation is one line for the shell
# git [-c x=y | -C dir]... push, as r_force in bash-guard.sh; not a dry run: --dry-run, or -n alone or in a group of
# flags without a value (-nv, -un)
W='("[^"]*"|'"'"'[^'"'"']*'"'"'|[^[:space:];&|"'"'"'])+'
G="git([[:blank:]]+-[cC][[:blank:]]+$W)*[[:blank:]]+push"
E='([[:space:];&|)]|$)'
# gh [-R repo]... pr create whose output shows a new PR; with gh pr merge in the same command no decision is left
R="gh([[:blank:]]+(-R|--repo)[[:blank:]]+$W)*[[:blank:]]+pr "
if [ "$verdict" = opened ] && [[ $cmd =~ ${R}create$E ]] && ! [[ $cmd =~ ${R}merge$E ]]; then
  pr="PR opened. Start one background call, not a poll: \`gh pr checks <number> --watch\` with run_in_background (the"
  pr+=" app wakes you only on failures, not on green). When it ends green, say in one line what gets merged into which"
  pr+=" branch and run \`gh pr merge\` right away: its permission prompt is the user's merge decision, so no question"
  pr+=" and no reply buttons before it (in a session that shows no permission prompts, ask before the merge instead)."
  emit PostToolUse "$pr"
fi
[[ $cmd =~ $G$E ]] || quiet 'no git push in the command'
[[ $cmd =~ $G([[:blank:]]+$W)*[[:blank:]]+(--dry-run|-[fuvqd46]*n[fuvqd46]*)$E ]] && quiet 'dry run'
hint PostToolUse 'push done.' ' (not CI, a deploy or a fix of this push)'
