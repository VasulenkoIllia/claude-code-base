#!/bin/bash
# git pre-commit, from hook.commit-leaks.* in the env of settings.json: it runs in Claude sessions only, before the hook of a
# project, which stays as it is and runs after a refusal too. bash-guard looks before the call, at the index of the folder of the call: a git add in the
# same command, commit -a, a commit from a subfolder or in another repo go past it. Here git has built the index this commit
# takes and stands at the top of its worktree, so a project's .gitleaks.toml counts wherever the commit starts.
# A secret or no time: exit 1, no commit. No gitleaks or any other code is no verdict: a line for the model, one in the log,
# and the commit goes on, as bash-guard asks the owner about the same failure before the call
LEAKS_SECS=${BASH_GUARD_LEAKS_SECS:-10}   # a git hook has no timeout: a stuck gitleaks would hold the whole Bash call
LEAKS_CODE=17   # as in bash-guard: gitleaks exits with 1 on a broken config or a failed fork as well
LOG_CAP=32000   # bytes: a line comes with every commit while gitleaks is gone
SECONDS=0
refuse(){
  echo "BLOCKED by commit-leaks: $1. Hand this command to the user or take a different approach; don't work around the block with a variant of the command." >&2
  exit 1
}
log_line(){   # log_line <label>: into the log of bash-guard, which doctor shows
  local log=${BASH_GUARD_ERRLOG:-$HOME/.claude/logs/bash-guard.err}
  [ "$(wc -c 2>/dev/null <"$log" | tr -d ' ')" -gt "$LOG_CAP" ] 2>/dev/null ||
    { mkdir -p "$(dirname "$log")" && date -u "+%Y-%m-%dT%H:%M:%SZ $1 in commit-leaks" >>"$log"; } 2>/dev/null
}
no_verdict(){
  log_line "$1"
  echo "commit-leaks: secrets in this commit are not checked ($1; log ~/.claude/logs/bash-guard.err)" >&2
  exit 0
}
gl=$(command -v gitleaks)   # a session may start with the bare PATH of the app; a relative one would be the repo's own
[[ $gl == /* && -x $gl ]] || gl=/opt/homebrew/bin/gitleaks
[ -x "$gl" ] || no_verdict 'GitleaksExit 127'
rules=()   # the rules of the base unless the project has its own
[ -f .gitleaks.toml ] || rules=(--config "$(dirname "$0")/commit-leaks.toml")
"$gl" git --pre-commit --staged --redact --no-banner --exit-code "$LEAKS_CODE" "${rules[@]}" >/dev/null 2>&1 &
pid=$!
# as in bash-guard: KILL, it may ignore TERM; TERM stops the timer and its sleep once gitleaks has ended
( trap 'kill $!; trap - EXIT; exit' TERM; trap 'kill -9 "$pid"' EXIT; /bin/sleep "$LEAKS_SECS" & wait $! ) >/dev/null 2>&1 &
timer=$!
wait "$pid" 2>/dev/null; rc=$?
{ kill "$timer"; wait "$timer"; } 2>/dev/null
[ "$rc" = 0 ] && exit 0
[ "$rc" = "$LEAKS_CODE" ] && refuse "gitleaks found a secret in what this commit takes (check: gitleaks git --pre-commit --staged --redact)"
if [ "$SECONDS" -ge "$LEAKS_SECS" ]; then
  log_line 'TimeLimit'
  refuse "the secret scan of this commit took over $LEAKS_SECS s"
fi
no_verdict "GitleaksExit $rc"
