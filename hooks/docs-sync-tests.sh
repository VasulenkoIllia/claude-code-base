#!/bin/bash
# docs-sync tests on temporary git fixtures (never on real projects or ~/project-docs): a docs repo with a bare origin,
# projects with docs/ in .gitignore, _internal/ in .git/info/exclude and STATUS of .claude/state, a worktree, a husky
# folder. Real commits and pushes: git itself runs the hooks from the keys connect writes. A made-up token goes through
# the real gitleaks that docs-sync runs before a commit and a push. The env keys of a session are cleared for the
# fixtures; one commit brings them back, with a git config of color.ui=always and a -diff attribute, to show the scan
# depends on none of them. The project commits have their own author, the docs repo takes the owner's from the fixture
# git config.
# Run: bash hooks/docs-sync-tests.sh -> expects "SYNC OK". SYNC_TESTS_SHOW=1 also prints what each command said.
H=$(cd "$(dirname "$0")" && pwd); f=0
T=$(mktemp -d "${TMPDIR:-/tmp}/docs-sync-tests.XXXXXX") || exit 1
trap 'chmod -R u+rwx "$T" 2>/dev/null; rm -rf "$T" 2>/dev/null || { sleep 1; rm -rf "$T"; }' EXIT   # a push may end late
T=$(cd "$T" && pwd -P)   # the physical path, as git prints it
unset GIT_CONFIG_COUNT GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE DOCS_SYNC_LOCK_WAIT_S DOCS_SYNC_SCAN_S DOCS_SYNC_ALARM_S CLAUDE_HOME
printf '[user]\n\tname = Docs Owner\n\temail = owner@example.com\n' >"$T/gitconfig"
cp "$T/gitconfig" "$T/gitconfig-color" && printf '[color]\n\tui = always\n\tdiff = always\n[core]\n\tbigFileThreshold = 10\n' >>"$T/gitconfig-color"
export GIT_CONFIG_GLOBAL="$T/gitconfig" GIT_CONFIG_NOSYSTEM=1 XDG_CONFIG_HOME="$T/xdg" GIT_AUTHOR_NAME='Proj Author' \
  GIT_AUTHOR_EMAIL=proj@work.example GIT_COMMITTER_NAME='Proj Author' GIT_COMMITTER_EMAIL=proj@work.example \
  BASH_GUARD_ERRLOG="$T/bash-guard.err"
export DOCS_SYNC_REPO="$T/docs-repo" DOCS_SYNC_PROJECTS="$T/projects" DOCS_SYNC_ERRLOG="$T/err.log" DOCS_SYNC_MAX_FILE_B=4096
DR=$DOCS_SYNC_REPO DS="$H/docs-sync.sh" P="$T/projects/proj" WT="$T/wt" LOG=$DOCS_SYNC_ERRLOG
bad() { echo "FAIL docs-sync $*"; f=1; }
run() { out=$("$@" 2>&1); rc=$?; [ -z "$SYNC_TESTS_SHOW" ] || printf '%s\n' "$out" >&2; }   # out: stdout and stderr
has() { [[ $out == *"$1"* ]] || bad "$2: no [$1] in: $out"; }
subj() { git -C "$DR" log -1 --format=%s; }
count() { git -C "$DR" rev-list --count HEAD; }
put() { mkdir -p "$(dirname "$1")" && printf '%s\n' "${2:-$RANDOM $1}" >"$1"; }
code() { put "$1/src/app.ts"; git -C "$1" add src/app.ts; }   # a code change staged in a project
pc() { code "$P"; run git -C "$P" commit -q -m "$1"; }       # a commit of code only in P: the docs stay outside git
same() { cmp -s "$P/$1" "$DR/proj/$1"; }
pushed() { local i; for i in $(seq 1 50); do
  [ "$(git -C "$DR" rev-parse HEAD)" = "$(git --git-dir="$T/origin.git" rev-parse -q --verify main)" ] && return 0
  sleep 0.2; done; return 1; }
mirror() { (cd "$DR/proj" && find . -type f | sed 's#^\./##' | LC_ALL=C sort | tr '\n' ' '); }
rnd() { head -c 4096 /dev/urandom | LC_ALL=C tr -dc "$1" | head -c "$2"; }
hold() {   # hold <lock file> <flag file>: a process that holds the flock until it is killed
  python3 -I -c 'import fcntl, os, sys, time
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT); fcntl.flock(fd, fcntl.LOCK_EX); open(sys.argv[2], "w").close(); time.sleep(30)' \
    "$1" "$2" & holder=$!
  local i; for i in $(seq 1 50); do [ -f "$2" ] && break; sleep 0.1; done; }
closed() {   # closed <command>: its stdout and stderr go to a pipe nobody reads (git commit ... | head -1); its exit code
  python3 -I -c 'import os, subprocess, sys
r, w = os.pipe(); os.close(r); sys.exit(subprocess.run(sys.argv[1:], stdout=w, stderr=w).returncode)' "$@"; }

mkdir -p "$P" && git init -q -b main "$P" && printf 'docs/\n' >"$P/.gitignore" && printf '_internal/\n' >>"$P/.git/info/exclude"
code "$P" && git -C "$P" add .gitignore && git -C "$P" commit -q -m init || bad 'fixture: project'
for x in docs/STATUS.md docs/guide.md docs/sub/a.md docs/.hidden.md docs/node_modules/m.md docs/graphify-out/g.json \
  docs/key.pem docs/id_ed25519 _internal/plan.md .claude/state/STATUS.md .claude/state/notes.md .claude/state/inbox/file.txt
do put "$P/$x"; done
head -c 5000 /dev/zero >"$P/docs/big.bin" && ln -s ../src/app.ts "$P/docs/link.md"

# init (git 2.54 or newer; again after an init that stopped before its commit), a dry run, connect
mkdir -p "$T/oldgit" && printf '#!/bin/sh\n[ "$3" = version ] && { echo "git version 2.40.1"; exit 0; }\nexec %s "$@"\n' \
  "$(command -v git)" >"$T/oldgit/git" && chmod +x "$T/oldgit/git"
PATH="$T/oldgit:$PATH" run "$DS" init
[ "$rc" = 1 ] && has 'runs no hook from .git/config: 2.54 or newer is needed' 'init: old git' && [ ! -e "$DR" ] || bad "init: old git: rc $rc"
mkdir -p "$T/leaks" && printf '#!/bin/sh\nexit 2\n' >"$T/leaks/gitleaks" && chmod +x "$T/leaks/gitleaks"
PATH="$T/leaks:$PATH" run "$DS" init
[ "$rc" = 1 ] && has 'gitleaks exit 2: no verdict, so nothing goes on' 'init: no verdict' && [ -d "$DR/.git" ] || bad "init: no verdict: rc $rc"
run "$DS" init; [ "$rc" = 0 ] || bad "init after a stop: rc $rc: $out"
for x in README.md .gitignore registry.tsv REGISTRY.md; do [ -f "$DR/$x" ] || bad "init: no $x"; done
[ -z "$(git -C "$DR" config --get-regexp '^hook\.')" ] || bad 'init: hook keys in the docs repo: docs-sync scans by itself'
[ "$(subj)" = 'документація проєктів: старт' ] && [ -z "$(git -C "$DR" status --porcelain)" ] || bad "init: subject $(subj)"
run "$DS" init; [ "$rc" = 1 ] && has 'is a repo already' 'init twice' || bad "init twice: rc $rc"
git init -q --bare "$T/origin.git" && git -C "$DR" remote add origin "$T/origin.git" || bad 'fixture: origin'
n=$(count); run "$DS" connect --dry-run "$P"; [ "$rc" = 0 ] || bad "dry run: rc $rc: $out"
for w in 'dry run, nothing written: proj to' 'docs/ 3 files' 'over 0 MB 1' '_internal/ 1 files' '.claude/state/STATUS*.md 1 files'; do
  has "$w" "dry run: $w"; done
[ "$(count)" = "$n" ] && [ ! -e "$DR/proj" ] && [ -z "$(git -C "$P" config --get-regexp '^hook\.')" ] || bad 'dry run: wrote'
run "$DS" connect "$P"; [ "$rc" = 0 ] || bad "connect: rc $rc: $out"
has 'proj: 5 copied, 0 deleted to' connect; has 'not copied, over 0 MB: docs/big.bin' 'connect: a big file'
[ "$(git -C "$P" config --get-all hook.docs-sync.event)" = post-commit ] || bad 'connect: post-commit key'
[ "$(git -C "$P" config --get-all hook.docs-sync-push.event)" = pre-push ] || bad 'connect: pre-push key'
cmd_pc=$(git -C "$P" config --get hook.docs-sync.command); cmd_pp=$(git -C "$P" config --get hook.docs-sync-push.command)
[[ $cmd_pc == *"$H/docs-sync.sh"* && $cmd_pp == *'cat >/dev/null'* ]] || bad "connect: commands [$cmd_pc] [$cmd_pp]"
want='.claude/state/STATUS.md _internal/plan.md docs/STATUS.md docs/guide.md docs/sub/a.md '
[ "$(mirror)" = "$want" ] || bad "connect: mirror [$(mirror)]"
[ "$(subj)" = 'proj: підключено, перший знімок' ] || bad "connect: subject $(subj)"
grep -q "^proj	$P	mirror	.*	понад 0 МБ не скопійовано: 1$" "$DR/registry.tsv" && grep -q '^| proj | дзеркало |' "$DR/REGISTRY.md" ||
  bad 'connect: registry'
pushed || bad 'connect: no background push'

# post-commit: the forms of a commit, the author, a deletion, a worktree, husky
put "$P/docs/guide.md" v2; pc 'code 1'; [ "$rc" = 0 ] || bad "post-commit: rc $rc"; has 'docs-sync: proj: 1 copied, 0 deleted to' post-commit
[ "$(subj)" = "proj: документи після $(git -C "$P" rev-parse --short HEAD)" ] || bad "post-commit: subject $(subj)"
[ "$(git -C "$DR" log -1 --format='%an <%ae>')" = 'Docs Owner <owner@example.com>' ] || bad "post-commit: the author $(git -C "$DR" log -1 --format='%an <%ae>')"
same docs/guide.md || bad 'post-commit: the copy differs'
[ "$(git -C "$P" log -1 --format=%s)" = 'code 1' ] && [ -z "$(git -C "$P" ls-files docs)" ] || bad 'post-commit: the project changed'
n=$(count); pc 'code 2'; [ "$(count)" = "$n" ] && [ -z "$out" ] || bad "no docs change: $n -> $(count) commits, out [$out]"
put "$P/docs/guide.md" v3; put "$P/src/app.ts"; run git -C "$P" commit -q -a -m 'code -a'
same docs/guide.md && [ "$(git -C "$P" log -1 --format=%s)" = 'code -a' ] || bad "commit -a: $out"
put "$P/docs/guide.md" v4; put "$P/src/app.ts"; run git -C "$P" commit -q -m 'code path' src/app.ts
same docs/guide.md && [ -z "$(git -C "$DR" status --porcelain)" ] || bad "commit <path>: $out"
rm "$P/docs/sub/a.md"; pc 'code del'; [ ! -e "$DR/proj/docs/sub" ] && has '0 copied, 1 deleted' deletion || bad 'deletion: the copy stays'
git -C "$P" worktree add -q -b feat "$WT" && put "$WT/docs/guide.md" draft && put "$P/docs/STATUS.md" main-status &&
  code "$WT" && run git -C "$WT" commit -q -m 'in worktree'
same docs/STATUS.md && same docs/guide.md || bad "worktree: the main folder's docs not mirrored: $out"
mkdir -p "$P/.husky" && printf '#!/bin/sh\n: >"%s"\n' "$T/husky.ran" >"$P/.husky/post-commit" && chmod +x "$P/.husky/post-commit"
git -C "$P" config core.hooksPath .husky; put "$P/docs/guide.md" v5; pc 'husky'
[ -f "$T/husky.ran" ] && same docs/guide.md || bad "husky: $out"; git -C "$P" config --unset core.hooksPath

# a file that became a folder and back, a read-only copy, a name that changed case, a file that fails (also with a
# stderr nobody reads, and an odd name), a changed source that cannot be read, a file grown over the cap, files
# gitleaks does not read
put "$P/docs/x" file; pc 'x file'; rm "$P/docs/x"; put "$P/docs/x/a.md"; pc 'x folder'
[ -f "$DR/proj/docs/x/a.md" ] && [[ $out != *'not mirrored'* ]] || bad "a file became a folder: $out"
rm -r "$P/docs/x"; put "$P/docs/x" file-again; pc 'x file again'
[ -f "$DR/proj/docs/x" ] && same docs/x || bad "a folder became a file: $out"
chmod 444 "$DR/proj/docs/x"; put "$P/docs/x" v2; pc 'read-only copy'; same docs/x || bad "a read-only copy: $out"
mv "$P/docs/guide.md" "$P/docs/Guide.md"; pc 'case'
for x in "$DR"/proj/docs/*; do echo "${x##*/}"; done | grep -qx Guide.md && cmp -s "$P/docs/Guide.md" "$DR/proj/docs/Guide.md" ||
  bad "a name that changed case: $out"   # the names as the folder holds them: on APFS -e finds any case
mv "$P/docs/Guide.md" "$P/docs/guide.md"; pc 'case back'
mkdir -p "$P/docs/ro" && put "$P/docs/ro/one.md"; pc 'ro one'; chmod 555 "$DR/proj/docs/ro"
put "$P/docs/ro/two.md"; put "$P/docs/guide.md" v-ro; pc 'ro two'
has '1 files not copied or deleted: docs/ro/two.md (EACCES)' 'a file that fails' && same docs/guide.md || bad "a failed file stopped the rest: $out"
put "$P/docs/guide.md" v-pipe; code "$P"; closed git -C "$P" commit -q -m 'closed stderr'; rc=$?
[ "$rc" = 0 ] && same docs/guide.md && ! grep -qE ' (Error|ShimExit) ' "$LOG" || bad "a closed stderr: rc $rc: $(tail -n 2 "$LOG")"
[ "$(grep -c ' SyncError proj: 1 files not copied or deleted: docs/ro/two.md (EACCES)$' "$LOG")" = 1 ] || bad 'a failed file: not one log line'
put "$P/docs/ro/n"$'\e[1m\nx.md'; pc 'odd name'; chmod 755 "$DR/proj/docs/ro"
[[ $out != *$'\e'* ]] && has 'files not copied or deleted: docs/ro/n [1m x.md (EACCES), docs/ro/two.md' 'an odd name' || bad "an odd name: $out"
pc 'ro again'; same docs/ro/two.md || bad "a failed file: not copied the next time: $out"
put "$P/docs/guide.md" v-locked; chmod 000 "$P/docs/guide.md"; pc 'unreadable source'; chmod 644 "$P/docs/guide.md"
has '1 files not copied or deleted: docs/guide.md (EACCES)' 'an unreadable source' &&
  git -C "$DR" cat-file -e HEAD:proj/docs/guide.md 2>/dev/null || bad "an unreadable source: its last copy went: $out"
put "$P/docs/grow.md" small; pc 'grow small'; head -c 5000 /dev/zero >"$P/docs/grow.md"; put "$P/docs/guide.md" v-grow; pc 'grow big'
[ "$(cat "$DR/proj/docs/grow.md")" = small ] && has 'over 0 MB, not copied: 2' 'grown over the cap' || bad "grown over the cap: $out"
printf 'png\n' >"$P/docs/pic.png"; pc 'a picture'
has 'not scanned: 1 (png 1)' 'not scanned' && grep -q '	без скану: 1 (png 1); понад 0 МБ не скопійовано: 2$' "$DR/registry.tsv" ||
  bad "not scanned: $out"
printf 'a\0b\n' >"$P/docs/nul.md"; put "$P/docs/yarn.lock"; pc 'binary to git, a lock file'
has 'not scanned: 2 (md 1, lock 1)' 'binary to git' && grep -q '	без скану: 3 (md 1, png 1, lock 1); понад' "$DR/registry.tsv" ||
  bad "binary to git, a lock file: $out"

# pre-push (also with a stderr nobody reads); a push with no hook file and 3000 refs; a broken python; no docs repo:
# commit and push go on
git init -q --bare "$T/proj-origin.git" && git -C "$P" remote add origin "$T/proj-origin.git"
put "$P/docs/guide.md" v6; run git -C "$P" push -q origin main; [ "$rc" = 0 ] || bad "pre-push: rc $rc: $out"
[ "$(subj)" = "proj: документи перед пушем $(git -C "$P" rev-parse --short HEAD)" ] || bad "pre-push: subject $(subj)"
pc 'to push'; put "$P/docs/guide.md" v6-pipe; closed git -C "$P" push -q origin main; rc=$?
[ "$rc" = 0 ] && [ "$(git --git-dir="$T/proj-origin.git" rev-parse main)" = "$(git -C "$P" rev-parse HEAD)" ] && same docs/guide.md &&
  ! grep -qE ' (Error|ShimExit) ' "$LOG" || bad "pre-push, a closed stderr: rc $rc: $(tail -n 2 "$LOG")"
git -C "$P" config hook.docs-sync.command "${cmd_pc//$H\/docs-sync.sh/$T/missing.sh}"
git -C "$P" config hook.docs-sync-push.command "${cmd_pp//$H\/docs-sync.sh/$T/missing.sh}"
sha=$(git -C "$P" rev-parse HEAD); for i in $(seq 1 3000); do echo "create refs/tags/t$i $sha"; done | git -C "$P" update-ref --stdin
pc 'no hook file'; [ "$rc" = 0 ] && has 'the docs are not mirrored (no hook file)' 'no hook file: commit' || bad 'no hook file: commit rc'
run git -C "$P" push -q origin main --tags
[ "$rc" = 0 ] && [ "$out" = 'docs-sync: the docs are not mirrored (no hook file)' ] || bad "no hook file: a push of 3000 refs: rc $rc: $out"
mkdir -p "$T/broken" && cp "$DS" "$T/broken/docs-sync.sh" && printf 'import sys\nsys.exit(3)\n' >"$T/broken/docs_sync.py"
git -C "$P" config hook.docs-sync.command "${cmd_pc//$H\/docs-sync.sh/$T/broken/docs-sync.sh}"
git -C "$P" config hook.docs-sync-push.command "${cmd_pp//$H\/docs-sync.sh/$T/broken/docs-sync.sh}"
HOME="$T/home" DOCS_SYNC_ERRLOG="$T/home/shim.err" pc 'broken'
[ "$rc" = 0 ] && [ "$out" = 'docs-sync: the docs are not mirrored (exit 3; the error log ~/shim.err)' ] || bad "broken python: commit: $out"
run git -C "$P" push -q origin main; [ "$rc" = 0 ] || bad "broken python: push rc $rc"
grep -q 'ShimExit 3$' "$T/home/shim.err" && grep -q 'ShimExit 3$' "$LOG" || bad 'broken python: no ShimExit line'
git -C "$P" config hook.docs-sync.command "$cmd_pc"; git -C "$P" config hook.docs-sync-push.command "$cmd_pp"
code "$P"; DOCS_SYNC_REPO="$T/none" run git -C "$P" commit -q -m 'no docs repo'
[ "$rc" = 0 ] && has 'no docs repo at' 'no docs repo: commit' || bad 'no docs repo: commit rc'
DOCS_SYNC_REPO="$T/none" run git -C "$P" push -q origin main
[ "$rc" = 0 ] && has 'no docs repo at' 'no docs repo: push' || bad "no docs repo: push rc $rc"

# a busy docs repo; a secret, also with a session's keys that would switch a hook off and a git config that would
# blind the scan; gitleaks with no verdict or no answer in time; a hook over its time; a source emptied, mostly deleted
# or no longer a source; a blank line in the registry
hold "$DR/.git/docs-sync.lock" "$T/locked"
put "$P/docs/guide.md" v7; code "$P"; DOCS_SYNC_LOCK_WAIT_S=0.5 run git -C "$P" commit -q -m 'busy'
kill "$holder"; wait "$holder" 2>/dev/null
[ "$rc" = 0 ] && has 'the docs repo is busy over 0.5 s' 'busy' && [ "$(git -C "$P" log -1 --format=%s)" = busy ] || bad 'busy: the commit'
run "$DS" sync "$P"; [ "$rc" = 0 ] && has 'proj: 1 copied, 0 deleted to' 'sync after busy' && same docs/guide.md || bad "sync: rc $rc"
tok="gh""p_$(rnd 'a-zA-Z0-9' 36)"; n=$(count); put "$P/docs/leak.md" "token = \"$tok\""
mkdir -p "$T/xdg/git" && printf '*.md -diff\n' >"$T/xdg/git/attributes" && git -C "$DR" config color.ui always
GIT_CONFIG_GLOBAL="$T/gitconfig-color" GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0=hook.commit-leaks.event GIT_CONFIG_VALUE_0=pre-commit \
  GIT_CONFIG_KEY_1=hook.commit-leaks.command GIT_CONFIG_VALUE_1=true pc 'secret'   # a session's hook that passes all
rm "$T/xdg/git/attributes"; git -C "$DR" config --unset color.ui
[ "$rc" = 0 ] && has 'gitleaks found a secret in proj/docs/leak.md:1 (github-pat): remove it in the project' secret &&
  [ "$(count)" = "$n" ] || bad "secret: landed: $out"
[[ $out != *"$tok"* ]] && ! grep -qF "$tok" "$LOG" && [ ! -e "$DR/.git/docs-sync-scan.json" ] || bad 'secret: the value in an output, the log or a report'
run "$DS" report; has 'entries not committed in the docs repo' 'report: a refused commit'
rm "$P/docs/leak.md"; pc 'secret gone'; [ "$(count)" = "$n" ] && [ -z "$(git -C "$DR" status --porcelain)" ] || bad 'secret gone'
put "$P/docs/guide.md" v-gl; PATH="$T/leaks:$PATH" pc 'gitleaks broken'
has 'gitleaks exit 2: no verdict, so nothing goes on' 'gitleaks broken' && [ "$(count)" = "$n" ] || bad "gitleaks broken: $out"
printf '#!/bin/sh\nexec sleep 5\n' >"$T/leaks/gitleaks"; DOCS_SYNC_SCAN_S=0.5 PATH="$T/leaks:$PATH" pc 'gitleaks slow'
has 'the secret scan took over 0.5 s, so nothing goes on' 'gitleaks slow' && [ "$(count)" = "$n" ] || bad "gitleaks slow: $out"
DOCS_SYNC_ALARM_S=1 DOCS_SYNC_SCAN_S=10 PATH="$T/leaks:$PATH" pc 'hook slow'
has 'the hook took over 1 s' 'the alarm' && [ "$(count)" = "$n" ] && grep -q ' SyncError proj: the hook took over 1 s$' "$LOG" &&
  [ ! -e "$DR/.git/index.lock" ] || bad "the alarm: $out"
pc 'gitleaks back'; same docs/guide.md && [ "$(count)" = $((n + 1)) ] || bad "gitleaks back: $out"
mv "$P/_internal/plan.md" "$T/plan.md"; pc 'empty _internal'
has 'proj/_internal: 1 of 1 copied files are gone from the source, nothing copied or deleted there' 'empty source'
[ -f "$DR/proj/_internal/plan.md" ] && grep -q ' Kept proj/_internal' "$LOG" || bad 'empty source: the copy or the log line'
pc 'empty again'; [ "$(grep -c ' Kept proj/_internal' "$LOG")" = 1 ] || bad 'Kept: a log line on each sync'
rmdir "$P/_internal"; pc 'no _internal'
has "proj/_internal: no longer a source (gone, in git, a link or a repo of its own), its copy stays (not a file in the project's HEAD: _internal/plan.md) in" 'no longer a source'
[ -f "$DR/proj/_internal/plan.md" ] && grep -q ' Kept proj/_internal: no longer a source' "$LOG" || bad 'no longer a source: the copy or the log line'
mkdir "$P/_internal" && mv "$T/plan.md" "$P/_internal/plan.md"
for i in $(seq 1 30); do put "$P/docs/many/m$i.md"; done; pc many; rm "$P"/docs/many/m{1..25}.md; pc 'many gone'
has 'proj/docs: 25 of ' 'mass deletion'; [ -f "$DR/proj/docs/many/m1.md" ] || bad 'mass deletion: copies went'
run "$DS" sync "$P"; [ ! -e "$DR/proj/docs/many/m1.md" ] && [ -f "$DR/proj/docs/many/m30.md" ] || bad "sync by hand: $out"
printf '\n' >>"$DR/registry.tsv"; put "$P/docs/guide.md" v-blank; pc 'a blank line'; same docs/guide.md || bad "a blank registry line: $out"
# a doc with a name in Cyrillic, from a commit made in a Ukrainian locale: mirrored as before (docs-sync runs its git in
# the C locale, and git takes a path as bytes)
put "$P/docs/нотатки/план.md"; LC_ALL=uk_UA.UTF-8 pc 'a name in Cyrillic'
has 'proj: 1 copied, 0 deleted to' 'a name in Cyrillic: the hook' && same 'docs/нотатки/план.md' &&
  [ -n "$(git -C "$DR" ls-files 'proj/docs/нотатки/план.md')" ] || bad "a name in Cyrillic: $out"

# a push that failed is tried again by the next commit; push by hand says git's reason; a commit by hand with a secret
# does not go out, also with a git config that would blind the scan
pushed || bad 'push: the earlier pushes did not land'
git -C "$DR" remote set-url origin "$T/gone.git"; put "$P/docs/guide.md" v-off; pc 'origin gone'
for i in $(seq 1 50); do grep -q ' PushFailed git push rc=' "$LOG" && break; sleep 0.2; done
grep -q ' PushFailed git push rc=[0-9]* (no repo)$' "$LOG" || bad "push: no PushFailed line: $(tail -n 1 "$LOG")"
run "$DS" push; [ "$rc" = 1 ] && has 'git push rc=128 (no repo): ' 'push by hand: a dead origin' &&
  has 'does not appear to be a git repository' 'push by hand: the reason' || bad "push by hand: rc $rc: $out"
# a git with a translation (Homebrew's; Apple's has none): in a locale other than C its words are not English. docs-sync
# asks git in the C locale, so the class and the reason of a failed push read the same. The stand-in asks the real git
# in the C locale and rewrites its words itself: the block reads the same where git has a translation of its own. A push
# by hand: in a hook git puts its own folder first in PATH, so the stand-in is not the git a hook runs
mkdir -p "$T/ukgit" && cat >"$T/ukgit/git" <<EOF && chmod +x "$T/ukgit/git"
#!/bin/bash
case \${LC_ALL:-\${LC_MESSAGES:-\${LANG:-C}}} in C | POSIX) exec "$(command -v git)" "\$@" ;; esac
{ LC_ALL=C "$(command -v git)" "\$@" 2>&1 >&3 3>&- | sed -e 's/^fatal: /збій: /' -e 's/does not appear to be a git repository/не схоже на сховище git/' \\
  -e 's/Could not read from remote repository/не вдалося прочитати з віддаленого сховища/' >&2 3>&-; exit "\${PIPESTATUS[0]}"; } 3>&1
EOF
LC_ALL=uk_UA.UTF-8 run "$T/ukgit/git" -C "$T/none" status; has 'збій: ' 'fixture: a translated git'
LC_ALL=uk_UA.UTF-8 PATH="$T/ukgit:$PATH" run "$DS" push
[ "$rc" = 1 ] && has 'git push rc=128 (no repo): ' 'a translated git: the class of a failed push' &&
  has 'does not appear to be a git repository' 'a translated git: the reason' || bad "a translated git: push by hand: rc $rc: $out"
git -C "$DR" remote set-url origin "$T/origin.git"; pc 'no docs change'; pushed || bad 'push: not tried again by the next commit'
run "$DS" push; [ "$rc" = 0 ] && has 'the docs repo is up to date with origin' 'push by hand: up to date' || bad "push: $out"
printf 'token = "%s"\n' "$tok" >"$DR/by-hand.md" && git -C "$DR" add by-hand.md && git -C "$DR" commit -q -m 'by hand'
git -C "$DR" config color.ui always; GIT_CONFIG_GLOBAL="$T/gitconfig-color" run "$DS" push; git -C "$DR" config --unset color.ui
[ "$rc" = 1 ] && has 'gitleaks found a secret in by-hand.md:1 (github-pat, ' 'push: a secret by hand' || bad "push scan: rc $rc: $out"
[[ $out != *"$tok"* ]] && [ "$(git --git-dir="$T/origin.git" rev-parse main)" != "$(git -C "$DR" rev-parse HEAD)" ] ||
  bad 'push scan: the secret went out or was printed'
git -C "$DR" reset -q --hard HEAD~1

# docs moved into git (a part first: the error names the copy that stays and why), keys of a folder not in the
# registry, disconnect, register, the CLI
P2="$T/projects/p2"; git init -q -b main "$P2" && put "$P2/docs/a.md" && code "$P2" && git -C "$P2" commit -q -m init
run "$DS" connect "$P2"; [ "$rc" = 0 ] || bad "connect p2: $out"
: >"$P2/.git/config.lock"; run "$DS" disconnect "$P2"; rm -f "$P2/.git/config.lock"
[ "$rc" = 1 ] && has 'p2: the hook keys are still there' 'disconnect: a config lock' || bad "disconnect: a config lock: rc $rc: $out"
put "$P2/docs/b.md"; git -C "$P2" add docs/a.md; run git -C "$P2" commit -q -m 'a part of docs into git'
has "); p2/docs: no longer a source (gone, in git, a link or a repo of its own), its copy stays (not a file in the project's HEAD: docs/b.md)" 'a part in git: the error'
[ -f "$DR/p2/docs/a.md" ] || bad "a part in git: the copy went: $out"
git -C "$P2" add docs/b.md; run git -C "$P2" commit -q -m 'docs into git'
has "p2/docs: in the project's git now, its copy is gone from" 'docs into git'; [ ! -e "$DR/p2/docs" ] || bad 'docs into git: the copy stays'
code "$P2"; run git -C "$P2" commit -q -m 'nothing outside git'
has 'p2: no docs outside git to mirror (all in git? docs-sync.sh disconnect' 'nothing outside git'
[[ $out != *'its copy stays'* ]] || bad "nothing outside git: a copy named: $out"
P3="$T/projects/p3"; git init -q -b main "$P3" && put "$P3/docs/a.md" && git -C "$P3" config hook.docs-sync.event post-commit &&
  git -C "$P3" config hook.docs-sync.command "$cmd_pc" && code "$P3" && run git -C "$P3" commit -q -m one
has 'p3 is not connected in' 'keys of a folder not in the registry'
run "$DS" disconnect "$P"; [ "$rc" = 0 ] && [ -z "$(git -C "$P" config --get-regexp '^hook\.docs-sync')" ] || bad "disconnect: $out"
grep -q "^proj	$P	off	" "$DR/registry.tsv" && grep -q '^| proj | вимкнено |' "$DR/REGISTRY.md" || bad 'disconnect: registry'
n=$(count); put "$P/docs/guide.md" v9; pc 'after disconnect'
[ -z "$out" ] && [ "$(count)" = "$n" ] && [ -f "$DR/proj/docs/guide.md" ] || bad "after disconnect: $out"
Q="$T/projects/q"; git init -q -b main "$Q" && put "$Q/docs/d.md" && git -C "$Q" add docs && git -C "$Q" commit -q -m q
E="$T/projects/e"; git init -q -b main "$E" && put "$E/README.md" && git -C "$E" add README.md && git -C "$E" commit -q -m e &&
  git init -q -b main "$E/_internal" && git -C "$E/_internal" remote add origin git@github.com:Owner/e-archive.git
N="$T/projects/n"; put "$N/docs/n.md"; O="$T/projects/o"; git init -q -b main "$O" && put "$O/docs/o.md"
run "$DS" register "$Q"; has 'q in the registry: у git, docs/ in git' 'register: in git'
run "$DS" register "$E"; has 'e in the registry: власний репо, _internal/ (own repo github.com/Owner/e-archive)' 'register: own repo'
run "$DS" register "$N"; has 'n in the registry: без git, docs/' 'register: no git'
run "$DS" register "$O"; has 'connect it to mirror the docs' 'register: outside git'
run "$DS" register "$P2"; [ "$rc" = 1 ] && has 'is connected' 'register: connected' || bad 'register a connected one: rc'
run "$DS" connect "$T/missing"; [ "$rc" = 1 ] && has 'no such folder' 'connect: missing' || bad 'connect missing: rc'
run "$DS" connect "$N"; [ "$rc" = 1 ] && has 'no git here' 'connect: no git' || bad 'connect no git: rc'
run "$DS" sync "$O"; [ "$rc" = 1 ] && has 'o is not connected' 'sync: not connected' || bad 'sync not connected: rc'
W="$T/projects/w$(printf '\342\200\250')x"; git init -q -b main "$W" && put "$W/docs/w.md"; run "$DS" connect "$W"; rm -rf "$W"
[ "$rc" = 1 ] && has 'a control or line separator character' 'connect: a line separator in the name' || bad "line separator: $out"
DOCS_SYNC_REPO='' HOME="$T/home" run "$DS" register "$Q"
[ "$rc" = 1 ] && has 'this copy is not the installed one' 'not the installed copy' && [ ! -e "$T/home/project-docs" ] ||
  bad "not the installed copy: rc $rc: $out"
DOCS_SYNC_REPO='' HOME="$T/home" run "$DS" push
[ "$rc" = 1 ] && has 'this copy is not the installed one' 'not the installed copy: push' || bad "not the installed copy: push: rc $rc: $out"
run "$DS" bogus; [ "$rc" = 2 ] && has 'usage: docs-sync.sh' 'usage' || bad 'usage: rc'

# report (doctor.sh): a folder gone, keys missing or of another form, keys left in a folder not connected, docs long
# after the last sync, candidates, commits not on origin, locks left; a registry missing or not in UTF-8
pushed || bad 'report: the earlier pushes did not land'
P4="$T/projects/p4"; git init -q -b main "$P4" && put "$P4/docs/a.md" && code "$P4" && git -C "$P4" commit -q -m init
P5="$T/projects/p5"; git init -q -b main "$P5" && put "$P5/docs/a.md"
GIT_COMMITTER_DATE="@$(($(date +%s) - 2 * 86400))" "$DS" connect "$P4" >/dev/null && "$DS" connect "$P5" >/dev/null || bad 'report: fixtures'
put "$P4/docs/a.md" newer; rm -rf "$P5"; git -C "$P2" config --remove-section hook.docs-sync
git -C "$P4" config hook.docs-sync-push.command true; git -C "$P" config hook.docs-sync.event post-commit
S="$T/projects/s"; git init -q -b main "$S" && put "$S/docs/s.md" && code "$S" &&
  GIT_COMMITTER_DATE="@$(($(date +%s) - 90 * 86400))" git -C "$S" commit -q -m old && touch -t 202601010000 "$S/docs/s.md"
U="$T/projects/u"; git init -q -b main "$U" && put "$U/docs/u.md" && git -C "$U" add docs && git -C "$U" commit -q -m u
pushed || bad 'report: no push before the cut'
git -C "$DR" remote set-url origin "$T/gone.git"
GIT_COMMITTER_DATE="@$(($(date +%s) - 3600))" "$DS" register "$U" >/dev/null   # a commit an hour old, its push fails
touch "$DR/.git/index.lock" "$DR/.git/HEAD.lock"; run "$DS" report; rm -f "$DR/.git/index.lock" "$DR/.git/HEAD.lock"
for w in 'a connected folder is gone: p5' 'hook keys missing in a connected project: p2' \
  'hook keys of another form or another copy of docs-sync: p4' 'hook keys in folders not connected: proj' \
  'docs changed over a day after the last sync: p4 (2 days ago)' 'active in 60 days, not in the registry: p3' \
  'no work in 60 days, docs not in the registry: s' '1 commits not on origin, the oldest 60 min ago' \
  '.git/index.lock is left' '.git/HEAD.lock is left'; do
  has "  WARN: docs repo: $w" "report: $w"; done
[[ $out != *'entries not committed'* ]] || bad "report: a clean docs repo has entries not committed: $out"
[[ $out =~ (^|$'\n')"  docs repo: $DR, $T/gone, mirror 3, in the registry 9, last commit "[^,]+", not on origin "[1-9] ]] ||
  bad "report: summary line: $out"
mv "$DR/registry.tsv" "$T/registry.tsv"; run "$DS" report; mv "$T/registry.tsv" "$DR/registry.tsv"
[ "$rc" = 1 ] && has 'registry.tsv is missing in' 'report: no registry.tsv' || bad "report: no registry.tsv: rc $rc: $out"
cp "$DR/registry.tsv" "$T/registry.tsv"; printf '\377\n' >>"$DR/registry.tsv"; run "$DS" report; cp "$T/registry.tsv" "$DR/registry.tsv"
[ "$rc" = 1 ] && has 'registry.tsv is not UTF-8' 'report: not UTF-8' || bad "report: not UTF-8: rc $rc: $out"
DOCS_SYNC_REPO="$T/none" run "$DS" report; [ "$out" = "  WARN: docs repo: not set up at $T/none (docs-sync.sh init, then connect the projects)" ] ||
  bad "report: not set up: $out"
DOCS_SYNC_REPO="$T/dr2" "$DS" init >/dev/null; DOCS_SYNC_REPO="$T/dr2" run "$DS" report; has 'WARN: docs repo: no remote origin' 'report: no origin'

# a folder that moved: its commit says how to take the row over, connect there does; commands at the same time keep
# every row
git -C "$DR" remote set-url origin "$T/origin.git"
MV="$T/projects/mv"; git init -q -b main "$MV" && put "$MV/docs/m.md" && "$DS" connect "$MV" >/dev/null || bad 'moved: connect'
mkdir -p "$T/elsewhere" && mv "$MV" "$T/elsewhere/mv"; code "$T/elsewhere/mv"; run git -C "$T/elsewhere/mv" commit -q -m 'moved'
has "mv is not connected in $DR (moved here? docs-sync.sh connect $T/elsewhere/mv takes the row over)" 'moved: the hint'
run "$DS" connect "$T/elsewhere/mv"
[ "$rc" = 0 ] && grep -q "^mv	$T/elsewhere/mv	mirror	" "$DR/registry.tsv" || bad "moved: connect at the new place: rc $rc: $out"
put "$T/elsewhere/mv/docs/m.md" moved; code "$T/elsewhere/mv"; run git -C "$T/elsewhere/mv" commit -q -m 'moved and connected'
cmp -s "$T/elsewhere/mv/docs/m.md" "$DR/mv/docs/m.md" || bad "moved: no mirror from the new place: $out"
A1="$T/projects/a1"; A2="$T/projects/a2"; put "$A1/docs/a.md"; put "$A2/docs/b.md"; hold "$DR/.git/docs-sync.lock" "$T/locked2"
"$DS" register "$A1" >"$T/r1.out" 2>&1 & r1=$!; "$DS" register "$A2" >"$T/r2.out" 2>&1 & r2=$!
sleep 0.5; kill "$holder"; wait "$holder" 2>/dev/null; wait "$r1"; rc1=$?; wait "$r2"; rc2=$?
[ "$rc1$rc2" = 00 ] && grep -q '^a1	' "$DR/registry.tsv" && grep -q '^a2	' "$DR/registry.tsv" ||
  bad "registers at the same time: a row lost: $rc1 $rc2 $(cat "$T/r1.out" "$T/r2.out")"

# docs that went into git: connected before the first commit (as /new-project does), the commit that takes docs/ into
# git drops its copy in one line and the row says so, the next commit is silent; a part of a folder in git keeps its
# copy and says so, the copy of .claude/state goes with its STATUS committed; a file of the source not in HEAD and a
# doc that is a link in HEAD keep the copy too
G="$T/projects/g"; git init -q -b main "$G" && put "$G/docs/a.md" && put "$G/docs/sub/b.md" && put "$G/.claude/state/STATUS.md"
run "$DS" connect "$G"; [ "$rc" = 0 ] && [ -f "$DR/g/docs/sub/b.md" ] || bad "into git: connect with no commit: rc $rc: $out"
git -C "$G" add docs && code "$G" && run git -C "$G" commit -q -m first
has "g/docs: in the project's git now, its copy is gone from" 'into git: the line'; has 'g: 0 copied, 2 deleted to' 'into git: the commit'
[ ! -e "$DR/g/docs" ] && [ -f "$DR/g/.claude/state/STATUS.md" ] || bad "into git: the copies: $(cd "$DR/g" && find . -type f)"
grep -q "^g	$G	mirror	.claude/state/STATUS\*.md, docs/ in git	" "$DR/registry.tsv" || bad "into git: the row: $(grep '^g	' "$DR/registry.tsv")"
code "$G"; run git -C "$G" commit -q -m second; [ -z "$out" ] || bad "into git: the next commit is not silent: $out"
K="$T/projects/k"; git init -q -b main "$K" && put "$K/docs/a.md" && put "$K/docs/b.md" && put "$K/_internal/n.md" &&
  put "$K/.claude/state/STATUS.md" && code "$K" && git -C "$K" commit -q -m init
run "$DS" connect "$K"; [ "$rc" = 0 ] || bad "a part in git: connect: rc $rc: $out"
git -C "$K" add docs/a.md .claude/state/STATUS.md && code "$K" && run git -C "$K" commit -q -m part
has "k/docs: no longer a source (gone, in git, a link or a repo of its own), its copy stays (not a file in the project's HEAD: docs/b.md) in" 'a part in git: docs'
has "k/.claude/state: in the project's git now, its copy is gone from" 'STATUS into git'
[ -f "$DR/k/docs/b.md" ] && [ -f "$DR/k/_internal/n.md" ] && [ ! -e "$DR/k/.claude" ] || bad "a part in git: the copies: $out"
J="$T/projects/j"; git init -q -b main "$J" && put "$J/docs/a.md" && put "$J/_internal/n.md" && code "$J" && git -C "$J" commit -q -m init
run "$DS" connect "$J"; put "$J/docs/new.md"; git -C "$J" add docs/a.md && code "$J" && run git -C "$J" commit -q -m 'a, not new'
has "j/docs: no longer a source (gone, in git, a link or a repo of its own), its copy stays (not a file in the project's HEAD: docs/new.md) in" 'a file of the source not in HEAD'
[ -f "$DR/j/docs/a.md" ] || bad "a file of the source not in HEAD: the copy went: $out"
L="$T/projects/l"; git init -q -b main "$L" && put "$L/docs/a.md" && put "$L/_internal/n.md" && code "$L" && git -C "$L" commit -q -m init
run "$DS" connect "$L"; rm "$L/docs/a.md" && ln -s ../src/app.ts "$L/docs/a.md" && git -C "$L" add docs && code "$L" &&
  run git -C "$L" commit -q -m 'a link in git'
has "l/docs: no longer a source (gone, in git, a link or a repo of its own), its copy stays (not a file in the project's HEAD: docs/a.md) in" 'a link in HEAD'
[ -f "$DR/l/docs/a.md" ] || bad "a link in HEAD: the copy went: $out"
pushed || bad 'the last pushes did not land'
bad_lines=$(grep -vcE '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z (SyncError|Kept|PushFailed|ShimExit|Error) ' "$LOG")
[ "$bad_lines" = 0 ] || bad "error log: $bad_lines lines of another shape"
[ $f -eq 0 ] && echo "SYNC OK"; exit $f
