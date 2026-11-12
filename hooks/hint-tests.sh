#!/bin/bash
# session-hint tests: hook stdin JSON only (no repo, no network); stubs for a jq that is missing, killed, failing
# (exit 1, 2, 3, 5), printing an odd verdict or field name or spied on. DRIFT=<fields> before fires or quiet: the case
# must leave exactly the error-log line "ShapeDrift <fields>"; without it no line at all.
# Run: bash hooks/hint-tests.sh -> expects "HINT OK". HINT_TESTS_SHOW=1 also prints every hook output.
H=$(cd "$(dirname "$0")" && pwd); f=0
T=$(mktemp -d "${TMPDIR:-/tmp}/hint-tests.XXXXXX") || exit 1
trap 'rm -rf "$T"' EXIT
export SESSION_HINT_ERRLOG="$T/err.log"   # never the live ~/.claude/logs
unset SESSION_HINT_DEBUG
NEXT="don't start it here: end this turn with a new-session card and a short brief (app: start_session, or \
hand_off_to_session for work in progress; CLI: update the STATUS checkpoint and suggest a new session). Same task: continue."
PUSHED="session-hint: push done. If the next step is a different task or feature (not CI, a deploy or a fix of this \
push), $NEXT"
COMPACTED="session-hint: the context was just compacted. Відповідай українською, також wrap_up, плани, квізи. If the next \
step is a different task or feature, $NEXT"
OPENED="session-hint: PR opened. Start one background call, not a poll: \`gh pr checks <number> --watch\` with \
run_in_background (the app wakes you only on failures, not on green). When it ends green, say in one line what gets \
merged into which branch and run \`gh pr merge\` right away: its permission prompt is the user's merge decision, so no \
question and no reply buttons before it (in a session that shows no permission prompts, ask before the merge instead)."

# bash_inp <event> <command> [output] [jq filter]: PostToolUse-shaped stdin JSON; start_inp <source> [jq filter]
bash_inp() { /usr/bin/jq -nc --arg e "$1" --arg c "$2" --arg o "${3-}" \
  '{session_id:"hint-tests",transcript_path:"/x/s.jsonl",cwd:"/tmp",permission_mode:"default",hook_event_name:$e,
    tool_name:"Bash",tool_input:{command:$c},tool_response:{stdout:$o,stderr:"",interrupted:false},
    tool_use_id:"toolu_hint_tests",duration_ms:900}' | /usr/bin/jq -c "${4:-.}"; }
start_inp() { /usr/bin/jq -nc --arg s "$1" '{session_id:"hint-tests",transcript_path:"/x/s.jsonl",cwd:"/tmp",
  hook_event_name:"SessionStart",source:$s,model:"claude-opus-5-5"}' | /usr/bin/jq -c "${2:-.}"; }
size() { if [ -f "$1" ]; then wc -c <"$1" | tr -d ' '; else echo 0; fi; }
# run <json> [hook]: the hook with debug on; logged: the error-log lines it added
run() {
  local before; before=$(size "$SESSION_HINT_ERRLOG")
  out=$(printf '%s' "$1" | SESSION_HINT_DEBUG=1 /bin/bash "${2:-$H/session-hint.sh}" 2>"$T/why"); rc=$?
  [ -z "$HINT_TESTS_SHOW" ] || printf '%s\n' "$out" >&2
  logged=$(tail -c +$((before + 1)) "$SESSION_HINT_ERRLOG" 2>/dev/null)
}
# log_ok <case>: the run logged nothing, or with DRIFT set the one line "<UTC time> ShapeDrift $DRIFT"
log_ok() {
  local want=${DRIFT:+ShapeDrift $DRIFT}
  [ "${logged#????-??-??T??:??:??Z }" = "$want" ] && [[ $logged != *$'\n'* ]] &&
    { [ -z "$want" ] || [[ $logged == ????-??-??T??:??:??Z\ * ]]; } ||
    { echo "FAIL session-hint $1: error log: want '${want:-nothing}', got '$logged'"; f=1; }
}
# fires <case> <json> <event> <text>: exactly one JSON line, only additionalContext for that event, the exact text
fires() {
  run "$2"; log_ok "$1"
  [ "$rc" -eq 0 ] && [ ! -s "$T/why" ] && [ "$(printf '%s\n' "$out" | wc -l | tr -d ' ')" = 1 ] &&
    [ "$(printf '%s' "$out" | wc -c | tr -d ' ')" -le 1000 ] && printf '%s' "$out" | /usr/bin/jq -e --arg e "$3" --arg t "$4" \
    'keys == ["hookSpecificOutput"] and (.hookSpecificOutput | keys) == ["additionalContext", "hookEventName"]
     and .hookSpecificOutput.hookEventName == $e and .hookSpecificOutput.additionalContext == $t' >/dev/null 2>&1 ||
    { echo "FAIL session-hint $1: expected the $3 hint, rc=$rc, out '${out:0:120}', debug '$(head -c 120 "$T/why")'"; f=1; }
}
# quiet <case> <json> <reason>: silence, rc 0, and the debug line names the reason
quiet() {
  run "$2"; log_ok "$1"
  [ "$rc" -eq 0 ] && [ -z "$out" ] && [ "$(tail -n 1 "$T/why")" = "session-hint: $3" ] ||
    { echo "FAIL session-hint $1: expected silence for '$3', rc=$rc, out '${out:0:80}', got '$(tail -n 1 "$T/why")'"; f=1; }
}
P=PostToolUse; OK_OUT=$'To github.com:o/r.git\n   1a2b3c4..5d6e7f8  main -> main'
PR_OUT=https://github.com/o/r/pull/12

# a push that ran -> the push hint, whatever the form of the command
fires plain "$(bash_inp $P 'git push')" $P "$PUSHED"
fires remote-branch "$(bash_inp $P 'git push origin main' "$OK_OUT")" $P "$PUSHED"
fires set-upstream-tail "$(bash_inp $P 'git push -u origin feat/x 2>&1 | tail -3' "$OK_OUT")" $P "$PUSHED"
fires quiet-push "$(bash_inp $P 'cd "/p a" && git push -q')" $P "$PUSHED"
fires git-C "$(bash_inp $P "git -C '/path with space' push --tags")" $P "$PUSHED"
fires git-c "$(bash_inp $P 'git -c http.lowSpeedLimit=1 -C repo push origin HEAD')" $P "$PUSHED"
fires after-commit "$(bash_inp $P 'git add a.ts && git commit -qm "x" && git push')" $P "$PUSHED"
fires continuation "$(bash_inp $P $'git \\\n  push origin main')" $P "$PUSHED"
fires up-to-date "$(bash_inp $P 'git push' 'Everything up-to-date')" $P "$PUSHED"
fires two-pushes-one-hint "$(bash_inp $P 'git push && git -C ../kit push')" $P "$PUSHED"
fires dry-run-elsewhere "$(bash_inp $P 'git push; git log -n 1')" $P "$PUSHED"
fires fatal-mid-line "$(bash_inp $P 'git push' 'remote: note: fatal: is only a word here')" $P "$PUSHED"
fires flags-not-dry-run "$(bash_inp $P 'git push -o ci.skip -u origin feat-n')" $P "$PUSHED"
fires push-option-n "$(bash_inp $P 'git push -on origin main')" $P "$PUSHED"   # -o takes a value: n is the option
# as in bash-guard, git push in the text of a command counts too (a known false hint; tighten only on purpose)
fires text-mention "$(bash_inp $P $'cat >>notes.md <<\'EOF\'\nthen git push -u origin x\nEOF')" $P "$PUSHED"
# gh pr create whose output shows a new PR -> the PR hint, also with a push in the same command; a merge in the same
# command leaves no decision: as if there were no gh pr create
fires pr-created "$(bash_inp $P 'gh pr create --fill' "$PR_OUT")" $P "$OPENED"
fires pr-repo-flags "$(bash_inp $P 'gh -R o/r --repo "o/r" pr create --title x' "$PR_OUT")" $P "$OPENED"
fires pr-after-push "$(bash_inp $P 'git push -u origin x && gh pr create --fill' "$OK_OUT"$'\n'"$PR_OUT")" $P "$OPENED"
fires pr-in-stderr "$(bash_inp $P 'gh pr create --fill' '' ".tool_response.stderr = \"$PR_OUT\"")" $P "$OPENED"
fires pr-body-heredoc "$(bash_inp $P $'gh pr create --title x --body "$(cat <<\'EOF\'\nbody\nEOF\n)"' "$PR_OUT")" $P "$OPENED"
fires pr-and-merge-pushed "$(bash_inp $P 'git push && gh pr create --fill && gh pr merge --squash' "$PR_OUT")" $P "$PUSHED"
quiet pr-and-merge "$(bash_inp $P 'gh pr create --fill; gh pr merge 12' "$PR_OUT")" 'no git push in the command'
quiet pr-no-url "$(bash_inp $P 'gh pr create --web' 'Opening github.com/o/r/compare/x in your browser.')" \
  'no git push in the command'
quiet pr-dry-run "$(bash_inp $P 'gh pr create --dry-run' 'Would have created a Pull Request with:')" \
  'no git push in the command'
quiet pr-exists "$(bash_inp $P 'gh pr create --fill 2>&1 | tail -2' \
  $'a pull request for branch "x" into branch "main" already exists:\nhttps://github.com/o/r/pull/5')" \
  'no git push in the command'
quiet pr-other-gh "$(bash_inp $P 'gh pr view 12' "$PR_OUT")" 'no push, pr create or SessionStart in the input'
quiet pr-not-gh "$(bash_inp $P 'echo pr create' "$PR_OUT")" 'no git push in the command'
quiet pr-new-link "$(bash_inp $P 'gh pr create --web' 'remote:   https://github.com/o/r/pull/new/x')" 'no git push in the command'
quiet pr-longer-word "$(bash_inp $P 'gh pr created --fill' "$PR_OUT")" 'no git push in the command'
fires pr-merge-longer-word "$(bash_inp $P 'gh pr create --fill; gh pr merged' "$PR_OUT")" $P "$OPENED"
quiet pr-failed "$(bash_inp $P 'gh pr create --fill | cat' 'fatal: not a repository')" 'push failed'
quiet pr-subagent "$(bash_inp $P 'gh pr create --fill' "$PR_OUT" '.agent_id = "a1"')" 'subagent'
quiet pr-failure-event "$(bash_inp PostToolUseFailure 'gh pr create --fill' "$PR_OUT")" 'other event, tool or input'
quiet pr-empty-command "$(bash_inp $P '' 'pr create https://github.com/o/r/pull/1')" 'empty command'
# a compaction in the main session -> the compaction hint
fires compaction "$(start_inp compact)" SessionStart "$COMPACTED"
fires compaction-no-agent-type "$(start_inp compact '.agent_type = ""')" SessionStart "$COMPACTED"

# no push that ran: a dry run, a failed push inside a command that exits 0, other commands, a subagent
quiet dry-run "$(bash_inp $P 'git push --dry-run origin main')" 'dry run'
quiet dry-run-n "$(bash_inp $P 'git -C repo push -n')" 'dry run'
quiet dry-run-group "$(bash_inp $P 'git push -nv origin && git push -un origin main')" 'dry run'
quiet failed-refs "$(bash_inp $P 'git push 2>&1 | tail -3' 'error: failed to push some refs to x')" 'push failed'
quiet rejected "$(bash_inp $P 'git push' ' ! [rejected]        main -> main (fetch first)')" 'push failed'
quiet remote-rejected "$(bash_inp $P 'git push' ' ! [remote rejected] b -> b (refusing)')" 'push failed'
quiet fatal "$(bash_inp $P 'git push | cat' $'Everything\nfatal: The current branch x has no upstream branch.')" 'push failed'
quiet fatal-in-stderr "$(bash_inp $P 'git push' '' '.tool_response.stderr = "fatal: unable to access"')" 'push failed'
quiet stash-push "$(bash_inp $P 'git stash push -m wip')" 'no git push in the command'
quiet docker-push "$(bash_inp $P 'docker push img:1 && npm run push')" 'no git push in the command'
quiet push-word "$(bash_inp $P 'git log --grep=push; git pushx')" 'no git push in the command'
# in any locale only ASCII spaces count, as in tests/hint_common.py and in the shell itself: an em space ends neither
# "push" nor the -n flag
EM=$'\xe2\x80\x83'
LC_ALL=en_US.UTF-8 quiet utf8-em-space "$(bash_inp $P "git push${EM}origin")" 'no git push in the command'
LC_ALL=en_US.UTF-8 fires utf8-em-space-flag "$(bash_inp $P "git push -n${EM}x")" $P "$PUSHED"
quiet subagent "$(bash_inp $P 'git push' "$OK_OUT" '.agent_id = "a1b2c3" | .agent_type = "general-purpose"')" 'subagent'
quiet subagent-compaction "$(start_inp compact '.agent_id = "a1b2c3"')" 'subagent'
quiet failure-event "$(bash_inp PostToolUseFailure 'git push')" 'other event, tool or input'
quiet pre-tool-use "$(bash_inp PreToolUse 'git push')" 'other event, tool or input'
quiet other-tool "$(bash_inp $P 'git push' '' '.tool_name = "Monitor"')" 'other event, tool or input'
for s in startup resume clear fork; do quiet "source-$s" "$(start_inp $s)" 'other source'; done
quiet no-push-at-all "$(bash_inp $P 'ls -la' 'a.ts')" 'no push, pr create or SessionStart in the input'
DRIFT=input quiet empty '' 'empty input'
quiet empty-command "$(bash_inp $P '' 'push')" 'empty command'

# an input field the hook reads with another type or missing: one ShapeDrift line names it, and the hook goes on as
# before (the push hint when the command still shows)
DRIFT='tool_response.stdout tool_response.stderr' \
  fires odd-response "$(bash_inp $P 'git push' '' '.tool_response = {stdout: 5, stderr: null}')" $P "$PUSHED"
DRIFT=tool_response fires string-response "$(bash_inp $P 'git push' '' '.tool_response = "fatal: text"')" $P "$PUSHED"
DRIFT=tool_response fires no-tool-response "$(bash_inp $P 'git push' '' 'del(.tool_response)')" $P "$PUSHED"
DRIFT=tool_response.stderr fires no-stderr "$(bash_inp $P 'git push' '' 'del(.tool_response.stderr)')" $P "$PUSHED"
DRIFT=tool_input.command quiet command-number "$(bash_inp $P 'git push' 'push' '.tool_input.command = 5')" \
  'other event, tool or input'
DRIFT=tool_input quiet no-tool-input "$(bash_inp $P 'git push' 'push' 'del(.tool_input)')" 'other event, tool or input'
DRIFT=tool_input quiet tool-input-string "$(bash_inp $P 'git push' 'push' '.tool_input = "git push"')" \
  'other event, tool or input'
DRIFT=hook_event_name quiet event-number "$(bash_inp $P 'git push' '' '.hook_event_name = 5')" 'other event, tool or input'
DRIFT=hook_event_name quiet no-event "$(bash_inp $P 'git push' '' 'del(.hook_event_name)')" 'other event, tool or input'
DRIFT=tool_name quiet no-tool-name "$(bash_inp $P 'git push' '' 'del(.tool_name)')" 'other event, tool or input'
DRIFT=agent_id quiet agent-id-number "$(bash_inp $P 'git push' '' '.agent_id = 7')" 'subagent'
DRIFT='tool_input tool_response' quiet subagent-drift \
  "$(bash_inp $P 'git push' '' '.toolInput = .tool_input | del(.tool_input, .tool_response) | .agent_id = "a1"')" 'subagent'
DRIFT=source quiet no-source "$(start_inp compact 'del(.source)')" 'other source'
DRIFT=source quiet source-number "$(start_inp compact '.source = 1')" 'other source'
DRIFT=input quiet not-json 'push, but not json' 'not json'
DRIFT=input quiet array '["push"]' 'not an object'
DRIFT=input quiet string '"SessionStart"' 'not an object'
# no drift: new fields, a null agent_id, the result of a background call, PostToolUseFailure (it has no tool_response),
# another tool with another input
fires new-fields "$(bash_inp $P 'git push' '' '.effort = {level: "high"} | .tool_response.backgroundTaskId = "b1"
  | .tool_response.noOutputExpected = false')" $P "$PUSHED"
fires agent-id-null "$(bash_inp $P 'git push' '' '.agent_id = null')" $P "$PUSHED"
quiet failure-no-response "$(bash_inp PostToolUseFailure 'git push' '' 'del(.tool_response) | .error = "Exit code 1"
  | .is_interrupt = false')" 'other event, tool or input'
quiet other-tool-input "$(bash_inp $P 'git push' '' '.tool_name = "Monitor" | .tool_input = "git push"
  | del(.tool_response)')" 'other event, tool or input'
fires compaction-new-fields "$(start_inp compact '.session_title = "x" | .agent_type = "main"')" SessionStart "$COMPACTED"

# hook_with_jq <dir> <stub body>: $T/<dir>/session-hint.sh runs the stub $T/<dir>/jq in place of /usr/bin/jq
hook_with_jq() {
  mkdir -p "$T/$1"; printf '#!/bin/bash\n%s\n' "$2" >"$T/$1/jq"; chmod +x "$T/$1/jq"
  sed "s#/usr/bin/jq#$T/$1/jq#" "$H/session-hint.sh" >"$T/$1/session-hint.sh"
}

# jq starts only for input with push or SessionStart, once
hook_with_jq spy "echo x >>'$T/jq-calls'; exec /usr/bin/jq \"\$@\""
run "$(bash_inp $P 'npm test' 'ok')" "$T/spy/session-hint.sh"; log_ok spy-no-push
[ ! -s "$T/jq-calls" ] || { echo "FAIL session-hint: jq started for a call without push"; f=1; }
run "$(bash_inp $P 'git push')" "$T/spy/session-hint.sh"; log_ok spy-push
[ "$(size "$T/jq-calls")" = 2 ] && [ -n "$out" ] || { echo "FAIL session-hint: not one jq call for a push"; f=1; }

# jq missing, killed, failing (usage, does not compile, a runtime error on valid JSON) or printing an odd verdict:
# silence, rc 0 and a line in the error log; the default log path; a full log takes no more
errcase() {   # errcase <case> <log line end> <hook copy>: exactly one new error-log line, ending so
  local before new; before=$(size "$SESSION_HINT_ERRLOG")
  out=$(bash_inp $P 'git push' | /bin/bash "$3"); rc=$?
  new=$(tail -c +$((before + 1)) "$SESSION_HINT_ERRLOG" 2>/dev/null)
  [ "$rc" -eq 0 ] && [ -z "$out" ] && [ -n "$new" ] && [[ $new != *$'\n'* && $new == *"$2" ]] ||
    { echo "FAIL session-hint $1: expected silence and one error-log line ending '$2', rc=$rc, log '$new'"; f=1; }
}
mkdir -p "$T/nojq"; sed 's#/usr/bin/jq#/nonexistent/jq#' "$H/session-hint.sh" >"$T/nojq/session-hint.sh"
errcase jq-missing ' JqExit 127' "$T/nojq/session-hint.sh"
hook_with_jq killed 'kill -9 $$'
errcase jq-killed ' JqExit 137' "$T/killed/session-hint.sh"
hook_with_jq exit-1 'cat >/dev/null; echo compact; exit 1'   # a plausible verdict does not outweigh the status
errcase jq-exit-1 ' JqExit 1' "$T/exit-1/session-hint.sh"
hook_with_jq usage 'cat >/dev/null; exit 2'
errcase jq-usage ' JqExit 2' "$T/usage/session-hint.sh"
hook_with_jq no-compile 'cat >/dev/null; exit 3'
errcase jq-no-compile ' JqExit 3' "$T/no-compile/session-hint.sh"
hook_with_jq runtime '[ "$1" = empty ] && exec /usr/bin/jq "$@"; cat >/dev/null; exit 5'   # the input is JSON
errcase jq-runtime ' JqExit 5' "$T/runtime/session-hint.sh"
hook_with_jq odd-verdict "cat >/dev/null; printf '\ncomma\n'"   # an empty field line, then a verdict not in the set
errcase jq-odd-verdict ' JqOutput' "$T/odd-verdict/session-hint.sh"
hook_with_jq no-verdict "cat >/dev/null; printf 'tool_input\n'"   # the field line and nothing after it
errcase jq-no-verdict ' JqOutput' "$T/no-verdict/session-hint.sh"
hook_with_jq odd-field "cat >/dev/null; printf 'tool_inputs\ncompact\n'"   # a field name not in the set: no hint
errcase jq-odd-field ' JqOutput' "$T/odd-field/session-hint.sh"
bash_inp $P 'git push' | env -u SESSION_HINT_ERRLOG HOME="$T/home" /bin/bash "$T/nojq/session-hint.sh"
grep -q ' JqExit 127$' "$T/home/.claude/logs/session-hint.err" 2>/dev/null ||
  { echo "FAIL session-hint default-log-path: no line in ~/.claude/logs/session-hint.err"; f=1; }
# over DRIFT_CAP (32000 B) no more ShapeDrift lines, but a hook that dies still gets its line
head -c 32100 /dev/zero | tr '\0' x >"$SESSION_HINT_ERRLOG"
bash_inp $P 'git push' '' 'del(.tool_response)' | /bin/bash "$H/session-hint.sh" >/dev/null
printf 'push, but not json' | /bin/bash "$H/session-hint.sh"
printf '' | /bin/bash "$H/session-hint.sh"
[ "$(size "$SESSION_HINT_ERRLOG")" = 32100 ] || { echo "FAIL session-hint drift-cap: $(size "$SESSION_HINT_ERRLOG") B"; f=1; }
bash_inp $P 'git push' | /bin/bash "$T/nojq/session-hint.sh"
tail -n 1 "$SESSION_HINT_ERRLOG" | grep -q ' JqExit 127$' || { echo "FAIL session-hint drift-cap: no JqExit line after it"; f=1; }
head -c 64100 /dev/zero | tr '\0' x >"$SESSION_HINT_ERRLOG"
bash_inp $P 'git push' | /bin/bash "$T/nojq/session-hint.sh"
[ "$(size "$SESSION_HINT_ERRLOG")" = 64100 ] || { echo "FAIL session-hint full-log: $(size "$SESSION_HINT_ERRLOG") B"; f=1; }

[ $f -eq 0 ] && echo "HINT OK"; exit $f
