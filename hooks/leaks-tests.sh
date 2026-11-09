#!/bin/bash
# shellcheck disable=SC2154,SC2034   # D, H, f, leakcase and the gitleaks stubs come from extra-tests.sh, which sources this file
# commit-leaks.sh in real commits: git itself runs it from the env of a session, in toy repos. The rules of commit-leaks.toml
# with the real gitleaks, on values made up here, so that no token stands in this file
CD=$D/commit-leaks; mkdir "$CD"; n=0
GL_REAL=$(PATH=$PATH:/opt/homebrew/bin command -v gitleaks)
[ -x "$GL_REAL" ] || { echo "FAIL no gitleaks for the tests of commit-leaks"; f=1; }
REALP=$(dirname "$GL_REAL"):/usr/bin:/bin
rnd(){ head -c 4096 /dev/urandom | LC_ALL=C tr -dc "$1" | head -c "$2"; }   # a git hook ignores SIGPIPE: tr on all of urandom never ends
# The generic rule skips a value with a stop word in it (add, cafe, sql) or with an entropy under 3.5, and a test would fail
# at random: letters that make no word, and hex of 64 with each digit as often as the next
WORDLESS=0-9BDFGJKQVWXYZbdfgjkqvwxyz
pat="gh""p_$(rnd 'a-zA-Z0-9' 36)"; val=$(rnd "$WORDLESS" 40)
hex64=$(for i in 1 2 3 4 5; do printf 0123456789bcdf; done | fold -w1 | sort -R | tr -d '\n' | head -c 64)
key="const NP_API_KEY = \"$val\""
SECRET="token = \"$pat\""
FOUND='BLOCKED by commit-leaks: gitleaks found a secret in what this commit takes'
set_hook(){ leak_env=(GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0=hook.commit-leaks.event GIT_CONFIG_VALUE_0=pre-commit
                      GIT_CONFIG_KEY_1=hook.commit-leaks.command "GIT_CONFIG_VALUE_1=$1"); }
set_hook "'$H/commit-leaks.sh'"   # quoted: the folder of the repo has blanks, and the value goes through sh
clrepo(){   # a new repo with one commit, in $r
  n=$((n + 1)); r=$CD/r$n; mkdir -p "$r/src"
  git init -q -b feat "$r"; git -C "$r" config user.name T; git -C "$r" config user.email t@example.com
  printf 'hello\n' >"$r/a.txt"; printf 'x\n' >"$r/src/b.txt"; git -C "$r" add .; git -C "$r" commit -q -m init
}
staged(){ clrepo; printf '%s\n' "${1:-text}" >"$r/c.txt"; git -C "$r" add c.txt; }   # staged [text]: a repo with c.txt in the index
clcase(){   # clcase <landed|refused> <a part of the output, empty: no output> <PATH> <command> [folder, $r if none]
  local before after got
  rm -f "${CL_LOG:-$D/in.log}" 2>/dev/null
  before=$(git -C "$r" rev-list --count HEAD)
  out=$(cd "${5:-$r}" && env "${leak_env[@]}" BASH_GUARD_ERRLOG="${CL_LOG:-$D/in.log}" PATH="$3" /bin/bash -c "$4" 2>&1)
  after=$(git -C "$r" rev-list --count HEAD)
  if [ "$after" -gt "$before" ]; then got=landed; else got=refused; fi
  [ "$got" = "$1" ] || { echo "FAIL expected $1 got $got: $4 in $3: $out"; f=1; }
  if [ -n "$2" ]; then [[ $out == *"$2"* ]] || { echo "FAIL expected [$2]: $4: $out"; f=1; }
  else [ -z "$out" ] || { echo "FAIL a text: $4: $out"; f=1; }; fi
  [[ $out != *"$pat"* && $out != *"$val"* ]] || { echo "FAIL a value in the output: $4"; f=1; }
}
line_is(){ [ "$(sed 's/^[^ ]* //' "$D/in.log" 2>/dev/null)" = "$1" ] || { echo "FAIL expected the line [$1], got [$(cat "$D/in.log" 2>/dev/null)]"; f=1; }; }
# the forms bash-guard does not see
clrepo; printf '%s\n' "$SECRET" >"$r/c.txt"
clcase refused "$FOUND" "$REALP" 'git add c.txt && git commit -q -m x'
[ "$out" = "$FOUND (check: gitleaks git --pre-commit --staged --redact). Hand this command to the user or take a different approach; don't work around the block with a variant of the command." ] ||
  { echo "FAIL the text of the block: $out"; f=1; }
[ ! -e "$D/in.log" ] || { echo "FAIL a finding is no failure: $(cat "$D/in.log")"; f=1; }
clrepo; printf 'text\n' >"$r/c.txt"; clcase landed '' "$REALP" 'git add c.txt && git commit -q -m x'
[ ! -e "$D/in.log" ] || { echo "FAIL a line for a clean commit: $(cat "$D/in.log")"; f=1; }
clrepo; printf '%s\n' "$SECRET" >"$r/a.txt"; clcase refused "$FOUND" "$REALP" 'git commit -qam x'
clrepo; printf '%s\n' "$SECRET" >"$r/a.txt"; clcase refused "$FOUND" "$REALP" 'git commit -q -m x a.txt'
staged "$SECRET"; printf 'clean\n' >"$r/a.txt"; clcase landed '' "$REALP" 'git commit -q -m x a.txt'   # what it takes, not all that is staged
staged "$SECRET"; clcase refused "$FOUND" "$REALP" 'git commit -q -m x' "$r/src"
staged "$SECRET"; clcase refused "$FOUND" "$REALP" "git -C '$r' commit -q -m x" "$CD"
staged "$SECRET"; clcase refused "$FOUND" "$REALP" "cd '$r' && git commit -q -m x" "$CD"
staged "$SECRET"; clcase refused "$FOUND" "$REALP" "git commit -q --amend -m y"
staged "$SECRET"; clcase refused "$FOUND" "$REALP" 'sh -c "git commit -q -m x"'
# the hooks of a project stay
staged; printf '#!/bin/bash\n: >"$(git rev-parse --git-dir)/own-ran"\n' >"$r/.git/hooks/pre-commit"; chmod +x "$r/.git/hooks/pre-commit"
clcase landed '' "$REALP" 'git commit -q -m x'
[ -e "$r/.git/own-ran" ] || { echo "FAIL the hook of a project did not run"; f=1; }
staged; printf '#!/bin/bash\necho own says no >&2; exit 1\n' >"$r/.git/hooks/pre-commit"; chmod +x "$r/.git/hooks/pre-commit"
clcase refused 'own says no' "$REALP" 'git commit -q -m x'
staged; mkdir "$r/.hk"; printf '#!/bin/bash\n: >"$(git rev-parse --git-dir)/own-ran"\n' >"$r/.hk/pre-commit"; chmod +x "$r/.hk/pre-commit"
git -C "$r" config core.hooksPath .hk
clcase landed '' "$REALP" 'git commit -q -m x'
[ -e "$r/.git/own-ran" ] || { echo "FAIL a local core.hooksPath lost its hook"; f=1; }
# the rules: the generic rule keeps out of tests, mocks and sha256 values, and only that rule
ruled(){   # ruled <landed|refused> <path> <text of the file>
  local text=""
  clrepo; mkdir -p "$r/$(dirname "$2")"; printf '%s\n' "$3" >"$r/$2"
  [ "$1" = landed ] || text=$FOUND
  clcase "$1" "$text" "$REALP" "git add '$2' && git commit -q -m x"
}
ruled refused server/config.ts "$key"
ruled refused deploy/prod.env "DB_PASSWORD=$(rnd "$WORDLESS" 30)"
ruled refused server/a.ts "const API_TOKEN = \"${hex64:0:63}\""   # no sha256: one digit short
ruled refused server/a.ts "const API_TOKEN = \"${hex64}0\""
ruled refused server/contest/a.ts "$key"   # no folder of tests, only its name ends so
ruled refused server/latest.ts "$key"
ruled refused server/mock.ts "$key"
ruled refused server/config.test.json "$key"   # only code files: .test.js ends there
ruled landed server/config.test.ts "$key"
ruled landed server/config.spec.js "$key"
ruled landed server/__tests__/a.ts "$key"
ruled landed tests/a.ts "$key"
ruled landed server/test/a.ts "$key"
ruled landed src/data/mock/auth.ts "$key"
ruled landed src/mocks/auth.ts "$key"
ruled landed __mocks__/a.ts "$key"
ruled landed fixtures/a.ts "$key"
ruled landed kit-files.json "{\"auth-token-layout.tsx\": \"$hex64\"}"
ruled refused server/x.test.ts "const t = \"$pat\""   # a token of a known format counts there too
ruled refused tests/a.py "t = \"$pat\""
ruled refused src/mocks/a.ts "const t = \"$pat\""
# a project's own config wins, wherever the commit starts; a broken one is no verdict
staged "$SECRET"; printf "[extend]\nuseDefault = true\n[allowlist]\npaths = ['''c\\\\.txt''']\n" >"$r/.gitleaks.toml"
clcase landed '' "$REALP" 'git commit -q -m x' "$r/src"
staged; printf '%s\n' "$key" >"$r/a.test.ts"; printf '[extend]\nuseDefault = true\n' >"$r/.gitleaks.toml"; git -C "$r" add a.test.ts
clcase refused "$FOUND" "$REALP" 'git commit -q -m x'   # not the rules of the base
staged; printf 'not toml [' >"$r/.gitleaks.toml"
clcase landed 'commit-leaks: secrets in this commit are not checked (GitleaksExit 1; log ~/.claude/logs/bash-guard.err)' "$REALP" 'git commit -q -m x'
line_is 'GitleaksExit 1 in commit-leaks'
# bash-guard reads the index before the call with the same rules
mkdir "$D/gl-real"; ln -s "$GL_REAL" "$D/gl-real/gitleaks"
staged; printf '%s\n' "$key" >"$r/a.test.ts"; git -C "$r" add a.test.ts; leakcase 0 '' gl-real '' "$r"
staged; printf '%s\n' "$key" >"$r/config.ts"; git -C "$r" add config.ts; leakcase 2 '' gl-real '' "$r"
staged; printf '%s\n' "$key" >"$r/a.test.ts"; printf '[extend]\nuseDefault = true\n' >"$r/.gitleaks.toml"; git -C "$r" add a.test.ts
leakcase 2 '' gl-real '' "$r"
# the words of gitleaks, the folder, a secret from a stub
staged; rm -f "$D/gl.args"; clcase landed '' "$D/gl-args:/usr/bin:/bin" 'git commit -q -m x' "$r/src"
[ "$(cat "$D/gl.args")" = "$r"$'\ngit --pre-commit --staged --redact --no-banner --exit-code 17 --config '"$H/commit-leaks.toml" ] ||
  { echo "FAIL the folder or the words of gitleaks: $(cat "$D/gl.args")"; f=1; }
staged; clcase refused "$FOUND" "$D/gl-17:/usr/bin:/bin" 'git commit -q -m x'
# no verdict: the commit goes on with a line, as bash-guard has asked; no time stops it
staged; clcase landed 'commit-leaks: secrets in this commit are not checked (GitleaksExit 2; log ~/.claude/logs/bash-guard.err)' "$D/gl-2:/usr/bin:/bin" 'git commit -q -m x'
line_is 'GitleaksExit 2 in commit-leaks'
staged; clcase landed 'GitleaksExit 1;' "$D/gl-1:/usr/bin:/bin" 'git commit -q -m x'
staged; clcase landed 'GitleaksExit 137;' "$D/gl-kill:/usr/bin:/bin" 'git commit -q -m x'   # killed before its time: no TimeLimit
line_is 'GitleaksExit 137 in commit-leaks'
staged; rm -f "$D/gl.pid"; SECONDS=0
BASH_GUARD_LEAKS_SECS=2 clcase refused "BLOCKED by commit-leaks: the secret scan of this commit took over 2 s. Hand this command" "$D/gl-hang:/usr/bin:/bin" 'git commit -q -m x'
[ $SECONDS -lt 7 ] || { echo "FAIL gitleaks held the commit past its limit: $SECONDS s"; f=1; }
line_is 'TimeLimit in commit-leaks'
[ -s "$D/gl.pid" ] || { echo "FAIL gitleaks did not start"; f=1; }
kill -0 "$(cat "$D/gl.pid" 2>/dev/null)" 2>/dev/null && { echo "FAIL gitleaks lives past its time"; f=1; kill -9 "$(cat "$D/gl.pid")"; }
staged; SECONDS=0; BASH_GUARD_LEAKS_SECS=2 clcase refused 'took over 2 s' "$D/gl-child:/usr/bin:/bin" 'git commit -q -m x'
[ $SECONDS -lt 7 ] || { echo "FAIL a child of gitleaks held the commit: $SECONDS s"; f=1; }
staged; SECONDS=0   # a hook killed in the middle of a scan: what it leaves holds none of its output
out=$(cd "$r" && { BASH_GUARD_ERRLOG="$D/in.log" BASH_GUARD_LEAKS_SECS=12 PATH="$D/gl-hang:/usr/bin:/bin" "$H/commit-leaks.sh" 2>&1 & p=$!; /bin/sleep 1; kill -9 $p; } 2>/dev/null)
[ $SECONDS -lt 8 ] || { echo "FAIL a killed hook leaves its output held: $SECONDS s"; f=1; }
glstub gl-short '/bin/sleep 0.3'   # not at once: a TERM that comes as sleep starts is lost, and it stays till its time
s=$((1000 + RANDOM % 8000)); staged; BASH_GUARD_LEAKS_SECS=$s clcase landed '' "$D/gl-short:/usr/bin:/bin" 'git commit -q -m x'
for i in 1 2 3 4 5; do pgrep -f "^/bin/sleep $s\$" >/dev/null || break; /bin/sleep 0.2; done   # a sleep with TERM may still be dying
pgrep -f "^/bin/sleep $s\$" >/dev/null && { echo "FAIL the timer of gitleaks stays"; f=1; pkill -f "^/bin/sleep $s\$"; }
# where gitleaks is looked for: PATH, then the folder of brew, here a folder of the tests
mkdir "$D/cl-copy" "$D/cl-brew"; sed "s#/opt/homebrew/bin#$D/cl-brew#" "$H/commit-leaks.sh" >"$D/cl-copy/commit-leaks.sh"
chmod +x "$D/cl-copy/commit-leaks.sh"; cp "$H/commit-leaks.toml" "$D/cl-copy/"
set_hook "$D/cl-copy/commit-leaks.sh"
staged; clcase landed 'commit-leaks: secrets in this commit are not checked (GitleaksExit 127; log ~/.claude/logs/bash-guard.err)' /usr/bin:/bin 'git commit -q -m x'
line_is 'GitleaksExit 127 in commit-leaks'
cp "$D/gl-17/gitleaks" "$D/cl-brew/gitleaks"
staged; clcase refused "$FOUND" /usr/bin:/bin 'git commit -q -m x'
staged; printf '#!/bin/bash\nexit 0\n' >"$r/gitleaks"; chmod +x "$r/gitleaks"   # a relative PATH would be the repo's own
clcase refused "$FOUND" .:/usr/bin:/bin 'git commit -q -m x'
rm "$D/cl-brew/gitleaks"; printf 'text\n' >"$D/cl-brew/gitleaks"; chmod 644 "$D/cl-brew/gitleaks"   # there, but it does not run
staged; clcase landed 'GitleaksExit 127;' /usr/bin:/bin 'git commit -q -m x'
# the log: it stops at its cap, and one that cannot be written costs only the line
head -c 32001 /dev/zero | tr '\0' x >"$D/cap.log"; staged
env "${leak_env[@]}" BASH_GUARD_ERRLOG="$D/cap.log" PATH=/usr/bin:/bin git -C "$r" commit -q -m x >/dev/null 2>&1
[ "$(wc -c <"$D/cap.log" | tr -d ' ')" = 32001 ] || { echo "FAIL a line past the cap of the log"; f=1; }
CL_LOG=/dev/null/x; staged; clcase landed 'GitleaksExit 127;' /usr/bin:/bin 'git commit -q -m x'; unset CL_LOG
[[ $out != */dev/null* ]] || { echo "FAIL the error of a log in the output: $out"; f=1; }
staged; env -u BASH_GUARD_ERRLOG "${leak_env[@]}" HOME="$D/cl-home" PATH=/usr/bin:/bin git -C "$r" commit -q -m x >/dev/null 2>&1   # the log doctor reads
[ -s "$D/cl-home/.claude/logs/bash-guard.err" ] || { echo "FAIL the line is not in the log of bash-guard"; f=1; }
grep -q 'LEAKS_SECS=${BASH_GUARD_LEAKS_SECS:-10}' "$H/commit-leaks.sh" || { echo "FAIL the limit of a commit is not 10 s"; f=1; }
# the form of settings.json: a file that is gone costs no commit, and says so
GONE='commit-leaks: secrets in this commit are not checked (no hook file)'
set_hook "test -x $D/cl-gone/commit-leaks.sh && exec $D/cl-gone/commit-leaks.sh; echo '$GONE' >&2"
staged; clcase landed "$GONE" "$REALP" 'git commit -q -m x'
set_hook "test -x $D/cl-real/commit-leaks.sh && exec $D/cl-real/commit-leaks.sh; echo '$GONE' >&2"
mkdir "$D/cl-real"; cp "$H/commit-leaks.sh" "$H/commit-leaks.toml" "$D/cl-real/"; chmod +x "$D/cl-real/commit-leaks.sh"
staged "$SECRET"; clcase refused "$FOUND" "$REALP" 'git commit -q -m x'
rm "$D/cl-real/commit-leaks.toml"   # no rules, no verdict
staged "$SECRET"; clcase landed 'GitleaksExit 1;' "$REALP" 'git commit -q -m x'
