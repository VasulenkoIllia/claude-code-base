#!/bin/bash
# shellcheck disable=SC2154,SC2034,SC2016   # D, H and f come from extra-tests.sh, which sources this file
# push-allow.sh, the PermissionRequest hook of 11.11.2026: it answers "allow" only for a push of a feature branch to
# origin with nothing else in the call that needs the owner; any other input gets no answer, so the prompt stays. On
# temporary repos under $D, never on real projects.
PD="$D/push"; PR="$PD/repo"; PH="$PD/hooks"
ALLOW='{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow"}}}'
export PUSH_ALLOW_ERRLOG="$PD/errors.log"
mkdir -p "$PD/plain" "$PH" "$PR/app" "$PR/-" || { echo "FAIL no folders for the push tests"; f=1; }
pgit(){ /usr/bin/git -c user.name=t -c user.email=t@example.com -c core.hooksPath=/dev/null "$@" >/dev/null 2>&1; }
prepo(){   # prepo <folder>: a repo with origin, the branches of the cases and origin/HEAD at develop
  pgit init -q -b main "$1" && pgit -C "$1" commit -q --allow-empty -m init && pgit -C "$1" remote add origin "$PD/origin.git" &&
    for b in master prod production develop development dev staging stage release deploy live trunk feat/login fix-1 both stash \
        refs/heads/main we@ird; do
      pgit -C "$1" branch "$b" || return 1
    done &&
    pgit -C "$1" tag v1 && pgit -C "$1" tag both && pgit -C "$1" update-ref refs/stash HEAD &&
    pgit -C "$1" update-ref refs/remotes/origin/trunk HEAD &&
    pgit -C "$1" symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/trunk && pgit -C "$1" checkout -q feat/login
}
pgit init -q --bare "$PD/origin.git" && prepo "$PR" || { echo "FAIL no repo for the push tests"; f=1; }
pa_in(){ printf '%s' "$2" | /usr/bin/jq -Rs --arg c "$1" --arg m "${3:-default}" \
  '{session_id:"t",hook_event_name:"PermissionRequest",permission_mode:$m,tool_name:"Bash",tool_input:{command:.},cwd:$c}'; }
pa_run(){ PATH=$D/bin:/usr/bin:/bin "${PA_HOOKS:-$H}/push-allow.sh" 2>/dev/null; }
pa_is(){   # pa_is allow|pass <label>, with the output of the hook in $out and its exit code in $rc
  local got=pass; [ "$out" = "$ALLOW" ] && got=allow
  [ "$rc" -eq 0 ] && [ "$got" = "$1" ] && { [ "$got" = allow ] || [ -z "$out" ]; } || { echo "FAIL push-allow expected $1, got $got (exit $rc, output ${#out} chars): $2"; f=1; }
}
pa(){ out=$(pa_in "${PA_CWD:-$PR}" "$2" "${PA_MODE:-}" | pa_run); rc=$?; pa_is "$1" "$2"; }

# the push alone, with its flags, a filter after it, and from a subfolder or after a cd to the repo
for c in 'git push origin feat/login' 'git push -u origin feat/login' 'git push --set-upstream origin fix-1' 'git push -q origin fix-1' \
    'git push origin -u feat/login' 'git push origin feat/login 2>&1 | tail -5' 'git push -u origin feat/login 2>&1 | grep -v "^remote:" | head -20' \
    'git push origin feat/login >/dev/null 2>&1' 'git push "origin" '"'feat/login'" 'cd ./app && git push origin feat/login' \
    "cd $PR && git push origin feat/login" 'git push origin feat/login &' 'git push --progress -v origin feat/login'; do
  pa allow "$c"
done
PA_CWD="$PD/plain" pa allow "cd $PR && git push origin feat/login"
PA_CWD="$PD/plain" pa allow "cd ../repo/app; git push -u origin fix-1 2>&1 | tail -3"
PA_MODE=acceptEdits pa allow 'git push origin feat/login'; PA_MODE=auto pa allow 'git push origin feat/login'
# with what usually stands next to it: status, add, commit with a message, a PR
for c in 'git status --short && git push origin feat/login' 'git add -A && git commit -m "fix: x" && git push -u origin feat/login' \
    'git add src/*.ts README.md && git commit -qm "x; make all && ./run.sh | wc > out.txt" && git push origin feat/login' \
    $'git add . && git commit -m "$(cat <<\'EOF\'\nfix: the login form\n\nIt runs `nothing`, $(nothing) and ssh host too.\nEOF\n)" && git push origin feat/login' \
    'git commit -am x; git push origin feat/login; git log --oneline -3 | cat' 'git fetch origin && git diff --stat origin/develop...HEAD && git push origin feat/login' \
    'git diff --stat HEAD~1 -- src/a.ts app/..b && git show --no-color --stat HEAD:README.md | head -n 5; git push origin feat/login' \
    'git commit -m "say \"$USER\" and ${HOME} for \$5" && git push origin feat/login | tail -n +2' \
    'git push origin feat/login; gh pr view --json statusCheckRollup --jq ".statusCheckRollup[0].state"' \
    'git push -u origin feat/login && gh pr create --title "feat: login" --body "what and why" --base develop' \
    $'git push origin feat/login && gh pr create --draft -t x -b "$(cat <<\'EOF\'\n## Summary\n- a\nEOF\n)"' \
    'git push origin feat/login; gh pr view --json url -q .url; gh pr checks 12 --watch' 'echo "push $(git rev-parse --short HEAD)"; git push origin feat/login' \
    'git branch --show-current; git rev-parse --abbrev-ref HEAD; git push origin fix-1; echo done' 'if git diff --quiet; then echo clean; fi; git push origin feat/login' \
    'git push origin feat/login || echo "push failed"' 'git commit --allow-empty -m retry && git push origin feat/login && true' \
    'for i in 1 2; do echo "$i"; done; git push origin feat/login' 'git commit --message=x && git push origin feat/login' \
    'git push origin feat/login 2>&1 | grep -vE "^(remote|To)" | tail -n 5 | cut -c 1-200 | tr -d "\r" | wc -l' \
    'git push origin feat/login | grep -i -e error -e denied -A 2 | head -3 | cat' $'cat <<\'EOF\'\nnotes: $(nothing)\nEOF\ngit push origin feat/login' \
    'git commit -m "fix: $(git rev-parse --short HEAD) costs \$5, {a,b} and * for $USER" && git push origin feat/login' \
    "git commit -m 'it costs \$5 {x,y} *' -m fix\\ it && git push origin feat/login" \
    'git push origin feat/login && gh pr create -t "feat: {a,b} $(git branch --show-current)" -b "x * y"'; do
  pa allow "$c"
done
# another push: no branch, a protected one, the default branch of origin, a tag, a refspec, flags that send more
for c in 'git push' 'git push origin' 'git push -u origin' 'git push origin main' 'git push origin master' 'git push origin prod' 'git push origin production' \
    'git push origin HEAD' 'git push origin Master' 'git push origin develop' 'git push origin dev' 'git push origin staging' 'git push origin release' \
    'git push origin Develop' 'git push origin development' 'git push origin stage' 'git push origin deploy' 'git push origin live' \
    'git push origin trunk' 'git push origin v1' 'git push origin both' 'git push origin stash' \
    'git push origin nosuch' 'git push upstream feat/login' 'git push . feat/login' 'git push origin feat/login:main' 'git push origin +feat/login' \
    'git push origin :feat/login' 'git push origin refs/heads/feat/login' 'git push origin refs/heads/main' 'git push origin feat/login fix-1' 'git push origin HEAD:feat/login' \
    'git push origin feat/login..fix-1' 'git push origin @' 'git push origin we@ird' 'git push --force origin feat/login' 'git push -f origin feat/login' \
    'git push --force-with-lease origin feat/login' 'git push --tags origin feat/login' 'git push --follow-tags origin feat/login' \
    'git push --delete origin feat/login' 'git push -d origin feat/login' 'git push --mirror origin' 'git push --all origin' 'git push --no-verify origin feat/login' \
    'git push --atomic origin feat/login' 'git push -uq origin feat/login' 'git push --push-option=ci.skip origin feat/login' 'git push --repo=x origin feat/login' \
    'git push -- origin feat/login' 'git push origin "feat/login "' 'git push origin feat/log*' 'git push origin {feat/login,main}'; do
  pa pass "$c"
done
# git that is not plain git push, a word the hook cannot read, two pushes, a push that is not at the top level
for c in "git -C $PR push origin feat/login" 'git -c push.default=matching push origin feat/login' '/usr/bin/git push origin feat/login' '\git push origin feat/login' \
    'command git push origin feat/login' 'env X=1 git push origin feat/login' 'X=1 git push origin feat/login' 'GIT_DIR=/tmp/x git push origin feat/login' \
    'git push origin "$(git branch --show-current)"' 'git push origin $BRANCH' 'B=feat/login; git push origin $B' 'git push $REMOTE feat/login' \
    'git push origin feat/login && git push origin fix-1' 'git push origin feat/login; git push origin main' '(git push origin feat/login)' \
    'if true; then git push origin feat/login; fi' '{ git push origin feat/login; }' 'f() { git push origin feat/login; }; f' 'echo "$(git push origin feat/login)"' \
    'for b in feat/login; do git push origin $b; done' 'while true; do git push origin feat/login; done' 'git push origin feat/login `date`' \
    'eval "git push origin feat/login"' 'bash -c "git push origin feat/login"' 'xargs git push origin feat/login' 'time git push origin feat/login; date'; do
  pa pass "$c"
done
# a command off the list next to the push, or one of the list with a word it may not take
for c in 'git push origin feat/login; ssh host uptime' 'git push origin feat/login && gh pr merge 5 --squash' 'git push origin feat/login; rm -rf dist' \
    'npm test && git push origin feat/login' 'git push origin feat/login; curl -s https://example.com' 'git push origin feat/login | tee push.log' \
    'git push origin feat/login | sh' 'git push origin feat/login > push.log' 'git push origin feat/login 2> err.log' 'echo x > note.txt; git push origin feat/login' \
    'git push origin feat/login >& push.log' 'git push origin feat/login && gh pr merge 5' 'git add $FILES && git push origin feat/login' \
    'cd app app && git push origin feat/login' 'git push origin feat/login 2>&1 | grep -v "$SKIP" | tail -n "$N"' \
    'cd app && git push origin feat/login' 'git push origin feat/login | tail -f' 'git push origin feat/login | grep -f pats KEY' \
    'git push origin feat/login; gh pr view --json body -q env' 'git push origin feat/login; gh pr checks --jq ".[] | $ENV"' \
    'git push origin feat/login; gh pr view -q ".url, env.HOME"' 'gh pr create --base $BASE --title x --body y && git push origin feat/login' \
    'git push origin feat/login < /dev/null' 'cat note.txt; git push origin feat/login' 'tail -5 note.txt; git push origin feat/login' \
    'git push origin feat/login | grep -f `x`' 'git checkout -b new && git push origin feat/login' 'git merge develop && git push origin feat/login' \
    'git reset --hard HEAD~1; git push origin feat/login' 'git tag v2 && git push origin feat/login' 'git branch -D fix-1; git push origin feat/login' \
    'git branch new; git push origin feat/login' 'git remote set-url origin https://example.com/x.git; git push origin feat/login' \
    'git config remote.origin.push refs/heads/feat/login:refs/heads/main; git push origin feat/login' 'git log --output=x.txt -1; git push origin feat/login' \
    'git diff --no-index /dev/null note.txt; git push origin feat/login' 'git diff --ext-diff; git push origin feat/login' 'git fetch origin feat/login:main; git push origin feat/login' \
    'git fetch --upload-pack=x origin; git push origin feat/login' 'git add --chmod=+x a.sh; git push origin feat/login' 'git add $(x); git push origin feat/login' \
    'git commit --amend -m x && git push origin feat/login' 'git commit --no-verify -m x && git push origin feat/login' 'git commit -nm x && git push origin feat/login' \
    'git commit -F msg.txt && git push origin feat/login' 'git commit --author="A <a@example.com>" -m x && git push origin feat/login' \
    'git commit -m "$(ssh host cat x)" && git push origin feat/login' 'git push origin feat/login; echo "$(curl -s https://example.com)"' \
    'git push origin feat/login && gh pr create -R other/repo --fill' 'git push origin feat/login && gh pr create --repo other/repo --fill' \
    'git push origin feat/login && gh pr create --body-file body.md --title x' 'git push origin feat/login && gh pr create --web' 'git push origin feat/login; gh pr' \
    'git push origin feat/login; gh repo edit --visibility public' 'git push origin feat/login && gh pr view 5 --json url --template "$(x)"' \
    'git push origin feat/login; gh pr create --base "$(x)"' 'git push origin feat/login; gh api repos/x/y' 'printf -v x y; git push origin feat/login' \
    'git push origin feat/login; cd -' 'cd - && git push origin feat/login' 'cd /nonexistent-push-tests; git push origin feat/login' 'cd app | cat; git push origin feat/login' \
    'git status; cd app && git push origin feat/login' '{ cd app; }; git push origin feat/login' \
    'cd $X && git push origin feat/login' '(cd app); cd app app; git push origin feat/login' $'cat <<EOF\n$(ssh host)\nEOF\ngit push origin feat/login' \
    $'git commit -m "$(cat <<EOF\nx\nEOF\n)" && git push origin feat/login' $'git commit -m "$(cat - <<\'EOF\'\nx\nEOF\n)" && git push origin feat/login'; do
  pa pass "$c"
done
CDPATH=/var pa pass 'cd app && git push origin feat/login'; CDPATH=/var pa allow 'cd ./app && git push origin feat/login'
# the folder of the push: no repo, a repo with no origin, and a cd to another repo counts as that repo
PA_CWD="$PD/plain" pa pass 'git push origin feat/login'
PA_CWD="$PD/plain" pa pass "cd $PR; cd ..; git push origin feat/login"
PA_CWD=/nonexistent-push-tests pa pass 'git push origin feat/login'
pgit init -q -b main "$PD/lone" && pgit -C "$PD/lone" commit -q --allow-empty -m init && pgit -C "$PD/lone" branch feat/login
PA_CWD="$PD/lone" pa pass 'git push origin feat/login'
PA_CWD="$PD/lone" pa allow "cd $PR && git push origin feat/login"
PA_CWD="$PR" pa pass "cd $PD/lone && git push origin feat/login"
# a filter after a pipe that names a file to read: the answer would cover the prompt for a file outside the project
for c in 'cat note.txt' 'cat -n /etc/hosts' 'tail -5 note.txt' 'head -n 3 /etc/hosts' 'grep -r KEY' 'grep KEY note.txt' 'grep -f pats' \
    'grep -e KEY note.txt' 'grep -c' 'grep -e' 'grep --include=x KEY' 'wc -l note.txt' 'wc --files0-from=x' 'cut -d= -f1 note.txt' 'tail -n 2 -- x'; do
  pa pass "git push origin feat/login | $c"
done
# text that zsh runs where the reader sees a variable: ${(e)x}, a glob of $~x, arithmetic over the word of a for list
for c in "for x in '\$(touch \$HOME/pwned)'; do echo \${(e)x}; done" 'echo ${(e)x}' 'echo "${(e)x}"' 'echo ${~x}' 'echo $~x' 'echo ${x:-y}' \
    'echo ${#x}' 'echo ${x[1]}' "echo \${(e)\${:-'\$(date)'}}" 'echo $((x))' 'echo "$((1 + 1))"' 'echo $[x]' 'echo $=x' 'echo $^x' 'echo $+x' \
    "for x in 'a[\$(date)]'; do echo \"\$x\"; done" 'for x in $(git diff --name-only); do echo "$x"; done' 'for x in *; do echo "$x"; done' \
    'git commit -m "${(e)x}"' 'git commit -m "sum $((1 + 1))"' 'echo *(e:"date":)'; do
  pa pass "$c; git push origin feat/login"
done
# a heredoc that the ) of its $(...) ends for the shell: the reader would take the lines after it for its text
for c in $'git commit --allow-empty -m "$(cat <<\'EOF\')"\ngit push origin main\nEOF\ngit push origin feat/login' \
    $'echo "$(cat <<\'EOF\')"\nssh host uptime\nEOF\ngit push origin feat/login' $'cat <<\'E OF\'\nx\nE OF\ngit push origin feat/login' \
    $'git push origin feat/login; cat <<\'EOF\'\nno delimiter line'; do
  pa pass "$c"
done
# git diff of two files outside the repo prints them, and the $(...) of a message would send that to origin
for c in 'git diff /dev/null ~/.npmrc' 'git diff /dev/null /etc/hosts' 'git diff ../a ../b' 'git diff app/../../x y' 'git diff --no-ind a b' \
    'git log --outp=x.txt -1' 'git diff --ext' 'git show --output-directory=x' 'git diff -- /etc/hosts /etc/passwd' 'git diff ..'; do
  pa pass "git commit --allow-empty -m \"\$($c)\" && git push origin feat/login"
  pa pass "$c; git push origin feat/login"
done
# a word of free text that the shell would split into more words, an option among them
for c in 'git commit -m {x,--amend}' 'git commit -m $(echo x --amend)' 'git commit -m $MSG' 'git commit -m x*' 'git commit -m "x"$(echo y --amend)' \
    "git commit -m 'x'{,--amend}" 'git add {-f,secret.txt} && git commit -m x' 'git add "{a,b}" && git commit -m x' \
    'git commit -m \"$(echo x --amend)\"' \
    'gh pr create --title {x,--repo,o/r} --body y' 'gh pr create -t $(echo x -R o/r) -b y' 'gh pr view -q $Q'; do
  pa pass "$c && git push origin feat/login"
done
# a cd that may not have run, or that a function replaces: the push would go from the folder of the session
for c in "false && cd $PR; git push origin feat/login" "cd $PR & git push origin feat/login" "cd() { true; }; cd $PR && git push origin feat/login" \
    "cd() { }; cd $PR && git push origin feat/login" "cd $PR | git push origin feat/login" \
    "echo x; cd $PR && git push origin feat/login" "if false; then cd $PR; fi; git push origin feat/login"; do
  PA_CWD="$PD/lone" pa pass "$c"
done
# a setting of the repo that sends the push elsewhere or adds tags; with the setting gone the same push passes
for s in 'remote.origin.push refs/heads/feat/login:refs/heads/main' 'remote.origin.mirror true' 'push.followTags true'; do
  # shellcheck disable=SC2086   # a key and its value
  pgit -C "$PR" config $s; pa pass 'git push origin feat/login'; pgit -C "$PR" config --unset "${s%% *}"; pa allow 'git push origin feat/login'
done
pgit -C "$PR" config remote.origin.mirror false; pgit -C "$PR" config push.followTags false; pa allow 'git push origin feat/login'
pgit -C "$PR" config remote.origin.pushurl "$PD/other.git"; pa pass 'git push origin feat/login'; pgit -C "$PR" config --unset remote.origin.pushurl
pgit -C "$PR" symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/fix-1 2>/dev/null; pgit -C "$PR" update-ref refs/remotes/origin/fix-1 HEAD
pa pass 'git push origin fix-1'; pa allow 'git push origin trunk'; pa allow 'git push origin feat/login'
# origin names no default branch here: nothing says that the branch is not it
pgit -C "$PR" symbolic-ref -d refs/remotes/origin/HEAD; pa pass 'git push origin fix-1'; pa pass 'git push origin feat/login'
pgit -C "$PR" symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/trunk; pa allow 'git push origin fix-1'
# a bare repo and the .git folder of a repo have branches too, and hooks/ that a push runs
pgit clone -q --bare "$PR" "$PD/bare.git" &&
  pgit -C "$PD/bare.git" symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/trunk || { echo "FAIL no bare repo for the push tests"; f=1; }
PA_CWD="$PD/bare.git" pa pass 'git push origin feat/login'; pa pass "cd $PD/bare.git && git push origin feat/login"
PA_CWD="$PR/.git" pa pass 'git push origin feat/login'; pa pass 'cd ./.git && git push origin feat/login'
# the mode, a subagent, another tool or event: no answer
for m in plan bypassPermissions dontAsk ''; do PA_MODE=${m:-none} pa pass 'git push origin feat/login'; done
pa_other(){ out=$(pa_in "$PR" 'git push origin feat/login' | /usr/bin/jq -c "$1" | pa_run); rc=$?; pa_is pass "input changed by $1"; }
pa_other '.agent_id = "a1"'; pa_other '.tool_name = "Monitor"'; pa_other '.hook_event_name = "PreToolUse"'
pa_other '.tool_input.dangerouslyDisableSandbox = true'; pa_other '.tool_input.command = "echo a\u0000b; git push origin feat/login"'
pa_other '.tool_name = "mcp__terminal__run_in_terminal"'
out=$(printf '%s' '{"tool_name":"Bash","tool_input":{"command":"ls"}}' | pa_run); rc=$?; pa_is pass 'a command with no push'
# bash-guard has the last word: its block of this very call (a commit with an AI name) and its ask (a commit on main
# of a repo with develop) leave the prompt
pa pass 'git commit -m "x" -m "Co-Authored-By: Claude <noreply@anthropic.com>" && git push origin feat/login'
pgit -C "$PR" checkout -q main; pa pass 'git commit -m x && git push origin feat/login'; pa allow 'git push origin feat/login'
pgit -C "$PR" checkout -q feat/login; pa allow 'git commit -m x && git push origin feat/login'
[ ! -s "$PUSH_ALLOW_ERRLOG" ] || { echo "FAIL push-allow logged on the cases above: $(head -1 "$PUSH_ALLOW_ERRLOG")"; f=1; }
# the same with a bash-guard that is silent, asks, blocks, breaks or only warns: allow needs exit 0 and no output
cp "$H/push-allow.sh" "$H/push-allow.py" "$H/bash_guard_shell.py" "$H/bash_guard_words.py" "$PH/" || { echo "FAIL no copy of push-allow"; f=1; }
pguard(){ printf '#!/bin/bash\ncat >/dev/null\n%s\n' "$1" >"$PH/bash-guard.sh" && chmod +x "$PH/bash-guard.sh"; }
pguard 'exit 0'; PA_HOOKS=$PH pa allow 'git push origin feat/login'
pguard 'echo "{\"hookSpecificOutput\":{\"permissionDecision\":\"ask\"}}"; exit 0'; PA_HOOKS=$PH pa pass 'git push origin feat/login'
pguard 'echo "BLOCKED by bash-guard: x" >&2; exit 2'; PA_HOOKS=$PH pa pass 'git push origin feat/login'
[ ! -s "$PUSH_ALLOW_ERRLOG" ] || { echo "FAIL push-allow logged an ask or a block of bash-guard: $(head -1 "$PUSH_ALLOW_ERRLOG")"; f=1; }
pguard 'exit 1'; PA_HOOKS=$PH pa pass 'git push origin feat/login'
pguard 'echo warning >&2; exit 0'; PA_HOOKS=$PH pa pass 'git push origin feat/login'
rm -f "$PH/bash-guard.sh"; PA_HOOKS=$PH pa pass 'git push origin feat/login'
[ "$(grep -cE ' GuardExit (1|127)$' "$PUSH_ALLOW_ERRLOG" 2>/dev/null)" = 2 ] && [ "$(wc -l <"$PUSH_ALLOW_ERRLOG" | tr -d ' ')" = 2 ] ||
  { echo "FAIL push-allow: expected the 2 GuardExit lines of a bash-guard that broke: $(tr '\n' '|' <"$PUSH_ALLOW_ERRLOG" 2>/dev/null)"; f=1; }
# an input of another shape and a broken script: no answer, one line in the log
pguard 'exit 0'
out=$(pa_in "$PR" 'git push origin feat/login' | /usr/bin/jq -c 'del(.cwd) | .permission_mode = 5' | PA_HOOKS=$PH pa_run); rc=$?; pa_is pass 'an input with no cwd'
grep -qE '^[0-9TZ:-]+ ShapeDrift cwd permission_mode$' "$PUSH_ALLOW_ERRLOG" 2>/dev/null || { echo "FAIL push-allow: no ShapeDrift line for an input with no cwd"; f=1; }
out=$(printf 'not json with a push' | PA_HOOKS=$PH pa_run); rc=$?; pa_is pass 'an input that is no JSON'
grep -q ' Error JSONDecodeError$' "$PUSH_ALLOW_ERRLOG" 2>/dev/null || { echo "FAIL push-allow: no Error line for an input that is no JSON"; f=1; }
# git that gives no answer in time: the name of it in the log, not a silent pass
printf '#!/bin/bash\nexec /bin/sleep 5\n' >"$PD/slowgit" && chmod +x "$PD/slowgit" && mkdir -p "$PD/slowbin" && ln -sf "$PD/slowgit" "$PD/slowbin/git"
out=$(pa_in "$PR" 'git push origin feat/login' | PATH=$PD/slowbin:$D/bin:/usr/bin:/bin "$PH/push-allow.sh" 2>/dev/null); rc=$?; pa_is pass 'git with no answer'
grep -q ' Error GitSilent$' "$PUSH_ALLOW_ERRLOG" 2>/dev/null || { echo "FAIL push-allow: no Error GitSilent line for a git that hangs"; f=1; }
printf 'raise SystemExit("allow")\n' >"$PH/push-allow.py"; PA_HOOKS=$PH pa pass 'git push origin feat/login'
printf 'print("allow")\nraise SystemExit(7)\n' >"$PH/push-allow.py"; PA_HOOKS=$PH pa pass 'git push origin feat/login'
printf 'print("Error x; rm")\nraise SystemExit(3)\n' >"$PH/push-allow.py"; PA_HOOKS=$PH pa pass 'git push origin feat/login'
[ "$(grep -c ' ShimExit ' "$PUSH_ALLOW_ERRLOG" 2>/dev/null)" = 3 ] && grep -q ' ShimExit 7$' "$PUSH_ALLOW_ERRLOG" && grep -q ' ShimExit 3$' "$PUSH_ALLOW_ERRLOG" ||
  { echo "FAIL push-allow: expected 3 ShimExit lines in the log, with 1, 7 and 3: $(tr '\n' '|' <"$PUSH_ALLOW_ERRLOG" 2>/dev/null)"; f=1; }
printf 'print("allow ")\nprint("x")\n' >"$PH/push-allow.py"; PA_HOOKS=$PH pa pass 'git push origin feat/login'
grep -q ' ShimOutput$' "$PUSH_ALLOW_ERRLOG" 2>/dev/null || { echo "FAIL push-allow: no ShimOutput line for an answer that is neither word"; f=1; }
