#!/bin/bash
# doc-reminder tests on temporary git fixtures (never on real projects): a repo with docs/ in .gitignore and its
# worktree, _internal/ in .git/info/exclude, docs in git, a repo without reflog, an empty repo, a symlinked docs/,
# a docs/ with more files than the hook walks; stubs for a broken git, a jq that is missing, does not compile, fails at
# runtime or prints an odd field line, and a dying python. DRIFT=<fields> before fires or quiet: the case must leave
# exactly the error-log line "ShapeDrift <fields>"; without it no line at all.
# Run: bash hooks/doc-tests.sh -> expects "DOCS OK". DOC_TESTS_SHOW=1 also prints every hook output.
H=$(cd "$(dirname "$0")" && pwd); f=0
T=$(mktemp -d "${TMPDIR:-/tmp}/doc-tests.XXXXXX") || exit 1
trap 'chmod -R u+rwx "$T" 2>/dev/null; rm -rf "$T"' EXIT
T=$(cd "$T" && pwd -P)   # the physical path, as git rev-parse --show-toplevel prints it
export DOC_REMINDER_ERRLOG="$T/err.log"   # never the live ~/.claude/logs
unset DOC_REMINDER_NOW DOC_REMINDER_LOCAL DOC_REMINDER_DOCS_MTIME DOC_REMINDER_GIT DOC_REMINDER_DEBUG NOW
PY=/opt/homebrew/bin/python3; [ -x "$PY" ] || PY=/usr/bin/python3   # as the shim picks it
# Synthetic clock: git takes reflog times from GIT_COMMITTER_DATE, so commits lie 1000 s apart and each case sees
# only its own commits; the hook's "now" is the last tick + 1 s (NOW=<epoch> before a case sets another one).
TS=1780000000
tick() { TS=$((TS + 1000)); }
# fixture git: no global or system config (templates, hooks, signing), fixed identity, the synthetic clock
fg() { GIT_COMMITTER_DATE="@$TS" GIT_AUTHOR_DATE="@$TS" GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 \
  git -c user.name=Fixture -c user.email=fixture@example.com -c commit.gpgsign=false -c init.defaultBranch=main "$@"; }
# commit <repo> <file>...: write each file (folders made) and commit them quietly at the next tick
commit() { local r=$1 p; shift; tick; for p in "$@"; do mkdir -p "$(dirname "$r/$p")"; echo "$RANDOM $p" >>"$r/$p"; done
  fg -C "$r" add -- "$@" && fg -C "$r" commit -q -m "change $*" || { echo "FAIL doc-reminder: fixture commit in $r"; f=1; }; }
old() { touch -t 202601010000 "$@"; }   # an mtime before the session started

TR="$T/session.jsonl"; : >"$TR"; touch -t 202605010000 "$TR"   # macOS moves the birth time back with the mtime
# the usual session started after every fixture commit, so each commit is its first; TR started before them all
TN="$T/now.jsonl"; : >"$TN"
at() { date -r "$1" +%Y%m%d%H%M.%S; }   # touch -t of an epoch
R="$T/proj"; WT="$T/wt"; I="$T/free"; D="$T/plain"; N="$T/nolog"; E="$T/empty"; S="$T/linked"; M="$T/many"
mkdir -p "$R" "$I" "$D" "$N" "$E" "$S" "$M/docs" "$T/shared-docs"
fg -C "$R" init -q && printf 'docs/\n' >"$R/.gitignore" && commit "$R" .gitignore README.md src/app.ts
mkdir -p "$R/docs/sub" && echo status >"$R/docs/STATUS.md" && echo note >"$R/docs/sub/ui.md"
old "$R/docs/STATUS.md" "$R/docs/sub/ui.md"
tick; fg -C "$R" worktree add -q -b feat "$WT" 2>/dev/null || { echo "FAIL doc-reminder: fixture worktree"; f=1; }
fg -C "$I" init -q && commit "$I" README.md lib/main.py && printf '_internal/\n' >>"$I/.git/info/exclude"
mkdir -p "$I/_internal" && echo plan >"$I/_internal/plan.md" && old "$I/_internal/plan.md"
fg -C "$D" init -q && commit "$D" README.md docs/guide.md api/server.ts
fg -C "$N" init -q && fg -C "$N" config core.logAllRefUpdates false && commit "$N" main.go
fg -C "$E" init -q
echo d >"$T/shared-docs/d.md" && ln -s "$T/shared-docs" "$S/docs" && fg -C "$S" init -q && printf 'docs\n' >"$S/.gitignore" &&
  commit "$S" .gitignore
fg -C "$M" init -q && printf 'docs/\n' >"$M/.gitignore" && commit "$M" .gitignore &&
  (cd "$M/docs" && touch f{1..5001}.md && old f{1..5001}.md) || { echo "FAIL doc-reminder: fixture many"; f=1; }

# inp <event> <cwd> <command> [duration_ms|null] [transcript]: hook stdin JSON
inp() { /usr/bin/jq -n --arg e "$1" --arg c "$2" --arg cmd "$3" --argjson d "${4:-3000}" --arg t "${5-$TN}" \
  '{session_id:"doc-tests",transcript_path:$t,cwd:$c,hook_event_name:$e,tool_name:"Bash",tool_input:{command:$cmd},
    tool_response:{stdout:"",stderr:"",interrupted:false},tool_use_id:"toolu_doc_tests"}
   + (if $d == null then {} else {duration_ms:$d} end)'; }
size() { if [ -f "$1" ]; then wc -c <"$1" | tr -d ' '; else echo 0; fi; }
# run <json>: through the shim; logged: the error-log lines it added
run() {
  local before; before=$(size "$DOC_REMINDER_ERRLOG")
  out=$(printf '%s' "$1" | DOC_REMINDER_NOW=${NOW:-$((TS + 1))} "$H/doc-reminder.sh"); rc=$?
  [ -z "$DOC_TESTS_SHOW" ] || printf '%s\n' "$out" >&2
  logged=$(tail -c +$((before + 1)) "$DOC_REMINDER_ERRLOG" 2>/dev/null)
}
# log_ok <case>: the run logged nothing, or with DRIFT set the one line "<UTC time> ShapeDrift $DRIFT"
log_ok() {
  local want=${DRIFT:+ShapeDrift $DRIFT}
  [ "${logged#????-??-??T??:??:??Z }" = "$want" ] && [[ $logged != *$'\n'* ]] &&
    { [ -z "$want" ] || [[ $logged == ????-??-??T??:??:??Z\ * ]]; } ||
    { echo "FAIL doc-reminder $1: error log: want '${want:-nothing}', got '$logged'"; f=1; }
}
valid() {   # the only output shape: additionalContext for the same event, starts with "doc-reminder:", <= 1200 B
  [ "$rc" -eq 0 ] && [ "$(printf '%s' "$out" | wc -c | tr -d ' ')" -le 1200 ] && printf '%s' "$out" | /usr/bin/jq -e --arg e "$1" \
    'keys == ["hookSpecificOutput"] and (.hookSpecificOutput | keys) == ["additionalContext", "hookEventName"]
     and .hookSpecificOutput.hookEventName == $e and (.hookSpecificOutput.additionalContext | startswith("doc-reminder: "))' >/dev/null 2>&1
}
# fires <case> <json> [text | !text]...: a valid reminder that has every text and none of the !texts
fires() {
  local name=$1 ev s; ev=$(printf '%s' "$2" | /usr/bin/jq -r .hook_event_name); run "$2"; log_ok "$name"; shift 2
  valid "$ev" || { echo "FAIL doc-reminder $name: expected a reminder, rc=$rc, $(printf '%s' "$out" | wc -c | tr -d ' ') B"; f=1; return; }
  for s in "$@"; do
    case $s in
      '!'*) [[ $out != *"${s#!}"* ]] || { echo "FAIL doc-reminder $name: has '${s#!}'"; f=1; } ;;
      *) [[ $out == *"$s"* ]] || { echo "FAIL doc-reminder $name: no '$s'"; f=1; } ;;
    esac
  done
}
# quiet <case> <json> [reason]: silence; with a reason, the hook's debug line names it
quiet() {
  DOC_REMINDER_DEBUG=1 run "$2" 2>"$T/why"; log_ok "$1"
  [ "$rc" -eq 0 ] && [ -z "$out" ] || { echo "FAIL doc-reminder $1: expected silence, rc=$rc"; f=1; return; }
  [ -z "$3" ] || grep -q "^doc-reminder: $3" "$T/why" ||
    { echo "FAIL doc-reminder $1: expected '$3', got '$(tail -n 1 "$T/why")'"; f=1; }
}
# errcase <case> <log line end> <shim> <json> [VAR=value]...: silence, rc 0 and exactly one new error-log line that
# ends so
errcase() {
  local name=$1 end=$2 shim=$3 json=$4 before new; shift 4; before=$(size "$DOC_REMINDER_ERRLOG")
  out=$(printf '%s' "$json" | env "$@" DOC_REMINDER_NOW=$((TS + 1)) /bin/bash "$shim"); rc=$?
  new=$(tail -c +$((before + 1)) "$DOC_REMINDER_ERRLOG" 2>/dev/null)
  [ "$rc" -eq 0 ] && [ -z "$out" ] && [ -n "$new" ] && [[ $new != *$'\n'* && $new == *"$end" ]] ||
    { echo "FAIL doc-reminder $name: expected silence and one error-log line ending '$end', rc=$rc, log '$new'"; f=1; }
}
P=PostToolUse; C='git add -A && git commit -q -m "feat: x"'; TWO=1001000   # ms: the last two ticks

# code without docs, the docs outside git untouched in this session -> reminder
commit "$R" src/a.ts
fires gitignored-docs "$(inp $P "$R" "$C")" 'changes 1 file (src/a.ts) and no docs' "$R/docs/" \
  'did not change in this session' 'AskUserQuestion' 'before a push or deploy' '!copies in this worktree' '!cp back'
commit "$R" src/b.ts src/c.ts src/d.ts src/e.ts
fires four-files "$(inp $P "$R" "$C")" 'changes 4 files (src/b.ts, src/c.ts, src/d.ts, +1)'
touch "$R/docs/.DS_Store"; commit "$R" src/f.ts
fires hidden-file-is-no-edit "$(inp $P "$R" "$C")" "$R/docs/"
touch "$R/docs/STATUS.md"; commit "$R" src/f2.ts
fires checkpoint-is-no-edit "$(inp $P "$R" "$C")" "$R/docs/" 'did not change in this session'
old "$R/docs/STATUS.md"
# the docs outside git changed in this session (mtime after the transcript's birth) -> silence
touch "$R/docs/sub/ui.md"; commit "$R" src/g.ts
quiet local-docs-changed "$(inp $P "$R" "$C")" 'local docs changed in this session'
DOC_REMINDER_LOCAL=unchanged fires override-unchanged "$(inp $P "$R" "$C")" "$R/docs/"
old "$R/docs/sub/ui.md"
DOC_REMINDER_LOCAL=changed quiet override-changed "$(inp $P "$R" "$C")" 'local docs changed in this session'
# in a session that started before these commits (TR) the docs count after the later of its start and the previous
# commit, and a run of commits with no docs change gets one reminder, at its first commit
ins() { inp "$1" "$2" "$3" 3000 "$TR"; }   # the input of the session that started before them
commit "$R" src/r1.ts; touch -t "$(at $((TS + 500)))" "$R/docs/sub/ui.md"; commit "$R" src/r2.ts
quiet docs-after-previous-commit "$(ins $P "$R" "$C")" 'local docs changed in this session since the previous commit'
commit "$R" src/r3.ts
fires docs-before-previous-commit "$(ins $P "$R" "$C")" "$R/docs/" 'did not change in this session since the previous commit'
commit "$R" src/r4.ts
quiet run-reminded-once "$(ins $P "$R" "$C")" 'no docs change since the reminder earlier in this run'
commit "$R" src/r5.ts
quiet run-still-reminded "$(ins $P "$R" "$C")" 'no docs change since the reminder earlier in this run'
touch "$R/docs/sub/ui.md"; commit "$R" src/r6.ts
quiet docs-changed-again "$(ins $P "$R" "$C")" 'local docs changed in this session since the previous commit'
old "$R/docs/sub/ui.md"
# replay: the newest docs change of the session from the transcript, against dm1 (TS - 1000) and r6 (TS - 2000); the
# docs on disk changed just now, so a case that ignored the variable would see "changed"
commit "$R" src/dm1.ts; commit "$R" src/dm2.ts; touch "$R/docs/sub/ui.md"
DOC_REMINDER_DOCS_MTIME=$((TS - 1000)) quiet docs-mtime-at-previous "$(ins $P "$R" "$C")" 'local docs changed in this session'
DOC_REMINDER_DOCS_MTIME=$((TS - 1001)) fires docs-mtime-before-previous "$(ins $P "$R" "$C")" \
  'did not change in this session since the previous commit'
DOC_REMINDER_DOCS_MTIME=$((TS - 2000)) fires docs-mtime-at-parent "$(ins $P "$R" "$C")" \
  'did not change in this session since the previous commit'
DOC_REMINDER_DOCS_MTIME=$((TS - 2001)) quiet docs-mtime-repeat "$(ins $P "$R" "$C")" 'no docs change since the reminder'
DOC_REMINDER_DOCS_MTIME=0 quiet docs-mtime-none-repeat "$(ins $P "$R" "$C")" 'no docs change since the reminder'
DOC_REMINDER_DOCS_MTIME=0 fires docs-mtime-none-first "$(inp $P "$R" "$C")" "$R/docs/" 'did not change in this session'
DOC_REMINDER_DOCS_MTIME=x fires docs-mtime-odd "$(inp $P "$R" "$C")" 'could not be checked for this session'
old "$R/docs/sub/ui.md"
# the run looks only at commits that had the reminder: one with docs in git does not count, so the next code commit
# gets it (TM: a session that started after the commits above)
TM="$T/mid.jsonl"; : >"$TM"; touch -t "$(at $((TS + 500)))" "$TM"
commit "$R" src/rd1.ts README.md; quiet run-docs-in-git "$(inp $P "$R" "$C" 3000 "$TM")" 'docs in the commit'
commit "$R" src/rd2.ts
fires run-after-docs-in-git "$(inp $P "$R" "$C" 3000 "$TM")" "$R/docs/" 'did not change in this session since the previous commit'
commit "$R" src/rd3.ts
quiet run-after-reminder "$(inp $P "$R" "$C" 3000 "$TM")" 'no docs change since the reminder earlier in this run'
# a call with two commits looks before the older one (TM2: a session that started after rd3)
TM2="$T/mid2.jsonl"; : >"$TM2"; touch -t "$(at $((TS + 500)))" "$TM2"
commit "$R" src/tc1.ts; commit "$R" src/tc2.ts
fires two-commits-first-in-run "$(inp $P "$R" "$C" $TWO "$TM2")" 'change 2 files (src/tc2.ts, src/tc1.ts)'
# a commit with no code (a lock file) had no reminder either (TM4: a session that started after tc2)
TM4="$T/mid4.jsonl"; : >"$TM4"; touch -t "$(at $((TS + 500)))" "$TM4"
commit "$R" package-lock.json; quiet run-no-code "$(inp $P "$R" "$C" 3000 "$TM4")" 'no code in the commit'
commit "$R" src/nc.ts; fires run-after-no-code "$(inp $P "$R" "$C" 3000 "$TM4")" 'changes 1 file (src/nc.ts)'
# two repos in one call: silence only when each had the reminder in this run; here only $R did (TM5: after nc)
TM5="$T/mid5.jsonl"; : >"$TM5"; touch -t "$(at $((TS + 500)))" "$TM5"
commit "$R" src/two1.ts; commit "$R" src/two2.ts; commit "$I" lib/two.py
fires two-repos-one-reminded "$(inp $P "$T" "cd \"$R\" && git commit -qm x && git -C '$I' commit -qm y" $TWO "$TM5")" \
  'lib/two.py' 'src/two2.ts' "$I/_internal/"
# a root commit has no previous commit: the session start alone
F="$T/fresh"; mkdir -p "$F/docs" && echo a >"$F/docs/a.md" && touch -t 202605100000 "$F/docs/a.md" && fg -C "$F" init -q &&
  printf 'docs/\n' >"$F/.gitignore" || { echo "FAIL doc-reminder: fixture fresh"; f=1; }
commit "$F" .gitignore src/x.ts
quiet root-commit-docs-in-session "$(ins $P "$F" "$C")" 'local docs changed in this session since the previous commit'
# docs in the commit, or no code -> silence; a code file named like a doc is code
commit "$R" src/h.ts README.md; quiet with-readme "$(inp $P "$R" "$C")" 'docs in the commit'
commit "$R" src/j.ts notes/k.md; quiet with-md "$(inp $P "$R" "$C")" 'docs in the commit'
commit "$R" package-lock.json assets/logo.png; quiet lockfile-and-media "$(inp $P "$R" "$C")" 'no code in the commit'
commit "$R" src/ChangelogModal.tsx lib/readme-parser.ts
fires named-like-docs "$(inp $P "$R" "$C")" 'changes 2 files (lib/readme-parser.ts, src/ChangelogModal.tsx)'
# the working log is no docs, in the commit and outside git: STATUS, progress, plans, decisions, CHANGELOG, dated
# notes, _work/ and archives (owner's decision 03.11.2026); the reminder says so
commit "$R" lib/i.ts CHANGELOG.md
fires changelog-is-log "$(inp $P "$R" "$C")" 'changes 1 file (lib/i.ts)' 'the working log is no docs' '!CHANGELOG.md'
commit "$D" api/lg.ts docs/decisions.md; fires decisions-is-log "$(inp $P "$D" "$C")" 'changes 1 file (api/lg.ts)'
commit "$D" api/dn.ts docs/upgrade-2026-10-31.md; fires dated-note-is-log "$(inp $P "$D" "$C")" 'api/dn.ts'
commit "$D" api/ld.ts docs/dev-plan.md docs/guide.md; quiet log-and-doc "$(inp $P "$D" "$C")" 'docs in the commit'
commit "$D" docs/STATUS.md CHANGELOG.md; quiet only-log "$(inp $P "$D" "$C")" 'no code in the commit'
for p in docs/progress.md docs/sub/14-stage1-plan.md docs/_work/draft.md docs/archive/old.md; do
  mkdir -p "$(dirname "$R/$p")" && echo log >>"$R/$p"
done
commit "$R" src/lo.ts
fires local-log-is-no-edit "$(inp $P "$R" "$C")" 'the docs outside git (the log aside) did not change in this session'
touch "$R/docs/sub/ui.md"; commit "$R" src/lo2.ts
quiet local-doc-with-log "$(inp $P "$R" "$C")" 'local docs changed in this session'
old "$R/docs/sub/ui.md"
# a code commit with only the log had the reminder, so the run goes on silent (TM6: a session that started after lo2)
TM6="$T/mid6.jsonl"; : >"$TM6"; touch -t "$(at $((TS + 500)))" "$TM6"
commit "$R" src/lg1.ts CHANGELOG.md; fires run-log-in-commit "$(inp $P "$R" "$C" 3000 "$TM6")" 'src/lg1.ts'
commit "$R" src/lg2.ts
quiet run-after-log-reminder "$(inp $P "$R" "$C" 3000 "$TM6")" 'no docs change since the reminder earlier in this run'
# the areas a commit touches name their docs: README for env and commands, the repo's own deploy doc by its name, what
# a doc is when the repo has none
commit "$D" docs/deployment.md docs/archive/deploy-old.md
commit "$D" Dockerfile .env.example
fires area-env-deploy "$(inp $P "$D" "$C")" 'it touches env, deploy: check README.md, docs/deployment.md' '!deploy-old'
commit "$D" prisma/schema.prisma; fires area-no-doc "$(inp $P "$D" "$C")" 'it touches schema: check the data model doc'
commit "$D" src/util.ts; fires area-none "$(inp $P "$D" "$C")" '!it touches'
# which commits belong to this call: the reflog window (duration_ms before now, plus 5 s)
commit "$R" src/l.ts
NOW=$((TS + 120)) quiet commit-before-the-call "$(inp $P "$R" "$C" 100000)" 'no commit in the window'
fires no-duration "$(inp $P "$R" "$C" null)" 'changes 1 file (src/l.ts)'
for v in -5 1e12; do   # no number of ms in range: 600 s back, as without a duration
  NOW=$((TS + 120)) fires "odd-duration $v" "$(inp $P "$R" "$C" "$v")" 'changes 1 file (src/l.ts)'
done
for v in '"3000"' true; do   # not a number: 600 s back too, and a ShapeDrift line
  NOW=$((TS + 120)) DRIFT=duration_ms fires "odd-duration $v" "$(inp $P "$R" "$C" "$v")" 'changes 1 file (src/l.ts)'
done
commit "$R" src/m.ts; commit "$R" src/n.ts
fires two-commits "$(inp $P "$R" "$C" $TWO)" 'commits ' 'change 2 files (src/n.ts, src/m.ts)'
commit "$R" src/o.ts; commit "$R" docs-site/p.md
quiet code-then-docs "$(inp $P "$R" "$C" $TWO)" 'docs in the commit'
NOW=$((TS - 999)) fires later-commit-not-in-window "$(inp $P "$R" "$C")" 'changes 1 file (src/o.ts)'
commit "$R" src/am.ts; tick; echo x >>"$R/src/am2.ts"
fg -C "$R" add src/am2.ts && fg -C "$R" commit -q --amend --no-edit || { echo "FAIL doc-reminder: fixture amend"; f=1; }
fires amend "$(inp $P "$R" 'git commit -q --amend --no-edit')" 'changes 2 files (src/am.ts, src/am2.ts)'
# where the commit ran: cd and git -C targets, cwd outside git
commit "$R" src/q.ts
fires cd-target "$(inp $P "$T" "cd \"$R\" && git commit -q -m x")" "$R/docs/"
fires git-C "$(inp $P "$T" "git -C '$R' commit -q -m x")" 'src/q.ts'
HOME=$T fires cd-tilde "$(inp $P / 'cd ~/proj && git commit -qm x')" 'src/q.ts'
HOME=$R fires cd-home "$(inp $P / 'cd "$HOME" && git commit -qm x')" 'src/q.ts'
quiet no-repo "$(inp $P "$T" 'git commit -q -m x')" 'no commit in the window'
fires failure-event "$(inp PostToolUseFailure "$R" "$C && npm test")" 'src/q.ts'
commit "$R" src/ml.ts
fires multi-line "$(inp $P "$R" $'git add -A\ngit commit -q -m x')" 'src/ml.ts'
commit "$R" src/cont.ts
fires continuation "$(inp $P "$R" $'git add -A && git \\\n  commit -q -m x')" 'src/cont.ts'
# a check that cannot be made says so: no session start, an unreadable folder, a symlink, too many files
fires no-transcript "$(inp $P "$R" "$C" 3000 "$T/missing.jsonl")" "$R/docs/" 'could not be checked for this session'
mkdir -p "$R/docs/locked" && chmod 000 "$R/docs/locked"
fires walk-error "$(inp $P "$R" "$C")" "$R/docs/" 'could not be checked'
chmod 755 "$R/docs/locked"
commit "$S" app/s.ts
fires symlink-docs "$(inp $P "$S" "$C")" "$S/docs/" 'could not be checked'
# a folder not walked in full keeps one reminder per run (TM3: a session that started after s.ts)
TM3="$T/mid3.jsonl"; : >"$TM3"; touch -t "$(at $((TS + 500)))" "$TM3"
commit "$S" app/s2.ts; fires symlink-run-first "$(inp $P "$S" "$C" 3000 "$TM3")" 'could not be checked'
commit "$S" app/s3.ts; quiet symlink-run-after "$(inp $P "$S" "$C" 3000 "$TM3")" 'no docs change since the reminder'
commit "$M" src/m.ts
fires walk-limit "$(inp $P "$M" "$C")" "$M/docs/" 'could not be checked'
# worktree: the docs exist only in the main folder; copies in the worktree are drafts
commit "$WT" src/wt.ts
fires worktree "$(inp $P "$WT" "$C")" 'src/wt.ts' "$R/docs/" 'in the main folder; copies in this worktree do not count' \
  'cp back if the main file is unchanged'
mkdir -p "$WT/docs" && echo draft >"$WT/docs/ui.md" && echo checkpoint >"$WT/docs/STATUS.md"; commit "$WT" src/wt2.ts
fires worktree-copy-is-no-edit "$(inp $P "$WT" "$C")" "$R/docs/" "!$WT/docs/"
touch "$R/docs/sub/ui.md"; commit "$WT" src/wt3.ts
quiet worktree-main-docs-changed "$(inp $P "$WT" "$C")" 'local docs changed in this session'
old "$R/docs/sub/ui.md"
# _internal/ in .git/info/exclude; docs in git (no docs outside git); no reflog; a root commit; a merge
commit "$I" lib/util.py
fires internal-excluded "$(inp $P "$I" "$C")" "$I/_internal/" '!/docs/'
commit "$D" api/routes.ts
fires docs-in-git "$(inp $P "$D" "$C")" 'api/routes.ts' '!outside git'
commit "$N" cmd/run.go
fires no-reflog "$(inp $P "$N" "$C")" 'cmd/run.go'
commit "$E" main.rs
fires root-commit "$(inp $P "$E" "$C")" 'main.rs'
tick; fg -C "$D" checkout -q -b side && commit "$D" api/side.ts && tick && fg -C "$D" checkout -q main &&
  commit "$D" api/main2.ts && tick && fg -C "$D" merge -q --no-ff -m merge side >/dev/null 2>&1 ||
  { echo "FAIL doc-reminder: fixture merge"; f=1; }
quiet merge-is-no-commit "$(inp $P "$D" 'git merge --no-ff side && git commit -q -m x')" 'no commit in the window'
tick; fg -C "$D" checkout -q side || { echo "FAIL doc-reminder: fixture checkout"; f=1; }
quiet checkout-is-no-commit "$(inp $P "$D" 'git checkout side; git commit -q -m x')" 'no commit in the window'
commit "$D" api/z.ts __tests__/z.test.ts e2e/a.spec.ts
fires tests-listed-last "$(inp $P "$D" "$C")" 'changes 3 files (api/z.ts, __tests__/z.test.ts, e2e/a.spec.ts)'
# the verdict is per repo: a docs commit in cwd's repo does not cover code committed elsewhere with git -C
commit "$D" README.md; commit "$I" lib/x.py
fires per-repo "$(inp $P "$D" "git -C '$I' commit -q -m x" $TWO)" 'changes 1 file (lib/x.py)' "$I/_internal/"
# long paths and many files: still one valid JSON <= 1200 B
L=$(printf 'very-long-folder-name-%.0s' 1 2 3 4 5 6 7 8)
commit "$R" "$L/a.ts" "$L/b.ts" "$L/c.ts" "$L/d.ts"
fires long-paths "$(inp $P "$R" "$C")" '…' 'changes 4 files'
# 2-byte characters in long paths and a long project folder: the paths get shorter, the instruction stays whole
U=$(printf 'дуже-довга-тека-%.0s' 1 2 3 4 5 6 7 8); LR="$T/$(printf 'проєкт-з-довгою-назвою-%.0s' 1 2 3 4 5 6)"
mkdir -p "$LR/docs" && fg -C "$LR" init -q && printf 'docs/\n' >"$LR/.gitignore" && echo s >"$LR/docs/s.md" && old "$LR/docs/s.md"
commit "$LR" .gitignore && tick && fg -C "$LR" worktree add -q -b long "$LR-wt" 2>/dev/null
commit "$LR-wt" "$U/а.ts" "$U/б.ts" "$U/в.ts" "$U/г.ts"
fires long-utf8-paths "$(inp $P "$LR-wt" "$C")" 'changes 4 files' 'in the main folder; copies in this worktree do not count' \
  'ask the user now via AskUserQuestion; with the OK: copy into the worktree, Edit, cp back if the main file is unchanged (Bash cp is not blocked).'
# render() alone: names that JSON escapes to 6 B a character lose the paths, the counts and the instruction stay
"$PY" -I -B - "$H/doc-reminder.py" <<'EOF' || { echo "FAIL doc-reminder control-chars: over 1200 B or cut"; f=1; }
import importlib.util
import sys
spec = importlib.util.spec_from_file_location('doc_reminder', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
x = '\x01' * 60
out = m.render('PostToolUseFailure', ['0' * 40] * 3, [x + '/' + x] * 9, ['/' + x + '/docs'] * 3, True, 'unknown')
hint = (['env', 'commands', 'deploy', 'schema', 'API', 'integrations'], [(x + '/' + x, n) for n in (
    'README', 'the deploy doc', 'the data model doc', 'the API doc', 'the integrations doc')])
out2 = m.render('PostToolUseFailure', ['0' * 40] * 3, [x + '/' + x] * 9, ['/' + x + '/docs'] * 3, True, 'unknown', hint)
sys.exit(0 if len(out.encode('utf-8')) <= 1200 and 'change 9 files and no docs' in out and 'not blocked).' in out
         and len(out2.encode('utf-8')) <= 1200 and 'not blocked).' in out2
         and 'integrations: check README, the deploy doc, the data model doc, the API doc;' in out2 else 1)
EOF
# the log rule on names of the 60 days of sessions and of the review; the doc names past the scan limit of docs/ and
# with an unreadable folder; a hint that fails: the reminder goes without it and the error log names the step
"$PY" -I -B - "$H/doc-reminder.py" "$T/lib-cases" <<'EOF' || { echo "FAIL doc-reminder lib-rules"; f=1; }
import importlib.util
import os
import sys
spec = importlib.util.spec_from_file_location('doc_reminder', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
lib, root = m.lib, sys.argv[2]
LOG = ('docs/STATUS.md', 'docs/STATUS-archive.md', 'docs/STATUS.before-fix.md', 'docs/decisions.head.md',
       'docs/00-decisions.md', 'docs/dev-plan.md', 'docs/activity-log.md', 'docs/SPEC-journal.md', 'docs/WAVE-1.main.md',
       'docs/13-open-questions.md', 'docs/upgrade-2026-10-31.md', 'docs/_work/x.md', 'docs/archive/x.md',
       'CHANGELOG.md', 'docs/progress.json', 'docs/TRACKER.md')
DOC = ('docs/status-codes.md', 'docs/decision-engine.md', 'docs/archive-policy.md', 'README.md', 'README.uk.md',
       'docs/api.v2.md', 'docs/notes/x.md', 'docs/guide.md')
bad = ['log? ' + p for p in LOG if not lib.is_log(p)] + ['doc? ' + p for p in DOC if lib.is_log(p)]
if not lib.about('docs/data_model.md', ('schema', 'database', 'data-model')):
    bad.append('about data_model.md')
for p in ['docs/n%03d.md' % i for i in range(600)] + ['_internal/deployment.md', '_internal/locked/schema.md']:
    os.makedirs(os.path.dirname(os.path.join(root, p)), exist_ok=True)
    open(os.path.join(root, p), 'w').close()
os.chmod(os.path.join(root, '_internal/locked'), 0)
try:
    hint = lib.area_hint(['Dockerfile', 'prisma/schema.prisma'], [root])
finally:
    os.chmod(os.path.join(root, '_internal/locked'), 0o755)
if hint != (['deploy', 'schema'], [('_internal/deployment.md', 'the deploy doc'), ('', 'the data model doc')]):
    bad.append('area_hint %r' % (hint,))
log = os.path.join(root, 'err.log')
os.environ['DOC_REMINDER_ERRLOG'] = log


def boom(*_):
    raise OSError('x')


lib.area_hint = boom
if m.hint_of(['Dockerfile'], [root]) is not None or not open(log).read().endswith(' HookError area hint OSError\n'):
    bad.append('hint_of on an error')
if bad:
    print('\n'.join(bad))
sys.exit(1 if bad else 0)
EOF

# odd input and other calls: silence, no error-log line; git never starts for a call without git commit
printf '#!/bin/bash\necho "$*" >>"%s"\nexec git "$@"\n' "$T/git-calls" >"$T/git-spy"; chmod +x "$T/git-spy"
DOC_REMINDER_GIT="$T/git-spy" quiet no-commit-command "$(inp $P "$R" 'git log -1 --format=commit')"
[ ! -s "$T/git-calls" ] || { echo "FAIL doc-reminder: git started for a call without git commit"; f=1; }
NOW=$((TS + 500)) quiet commit-only-in-text "$(inp $P "$R" 'echo "use git log, not git commit -m"; grep -n commit README.md')" \
  'no commit in the window'
quiet not-json 'not json'
quiet edit-tool "$(inp $P "$R" "$C" | /usr/bin/jq -c '.tool_name = "Edit"')" 'other event, tool or input'
quiet pre-tool-use "$(inp PreToolUse "$R" "$C")" 'other event, tool or input'
quiet command-number "$(inp $P "$R" "$C" | /usr/bin/jq -c '.tool_input.command = 5')"
quiet relative-cwd "$(inp $P proj 'git commit -q -m x')" 'no commit in the window'
head -c 16000100 /dev/zero | tr '\0' x >"$T/big.txt"
quiet big-input "$(inp $P "$R" "$C" | /usr/bin/jq -c --rawfile s "$T/big.txt" '.tool_response.stdout = $s')" 'input too big'
# an input field the hook reads with another type or missing: one ShapeDrift line names it, and the hook goes on as
# before (with no command it stops in the shim)
J() { inp $P "$R" "$C" | /usr/bin/jq -c "$1"; }   # J <jq filter>: the usual input changed by the filter
DRIFT=tool_input quiet renamed-tool-input "$(J '.toolInput = .tool_input | del(.tool_input)')"
DRIFT=tool_input quiet tool-input-string "$(J '.tool_input = "git commit -m x"')"
DRIFT=tool_input.command quiet command-array "$(J '.tool_input.command = ["git", "commit"]')"
DRIFT=hook_event_name quiet event-number "$(J '.hook_event_name = 5')" 'other event, tool or input'
DRIFT=tool_name quiet no-tool-name "$(J 'del(.tool_name)')" 'other event, tool or input'
DRIFT=cwd quiet cwd-number "$(J '.cwd = 5')" 'no commit in the window'
DRIFT='cwd duration_ms' quiet two-fields "$(J '.cwd = null | .duration_ms = "1"')" 'no commit in the window'
DRIFT=input quiet not-an-object '["git commit -m x"]'
DRIFT=input quiet commit-not-json 'git commit, but not json'
commit "$R" src/tp.ts
DRIFT=transcript_path fires transcript-number "$(J '.transcript_path = 5')" 'src/tp.ts' 'could not be checked'
DRIFT='cwd transcript_path' quiet no-cwd-transcript "$(J 'del(.cwd, .transcript_path)')" 'no commit in the window'
DRIFT=input quiet empty-input ''
# no drift: another tool with another input, new fields, PostToolUseFailure with no tool_response (no duration_ms:
# no-duration above)
quiet other-tool-input "$(J '.tool_name = "Monitor" | .tool_input = "git commit -m x"')"
commit "$R" src/nf.ts
fires new-fields "$(J '.effort = {level: "high"} | .permission_mode = "default" | .tool_response.noOutputExpected = false')" \
  'src/nf.ts'
commit "$R" src/fr.ts
fires failure-no-response "$(inp PostToolUseFailure "$R" "$C && npm test" |
  /usr/bin/jq -c 'del(.tool_response) | .error = "Exit code 1" | .is_interrupt = false')" 'src/fr.ts'
# a broken git or repo: silence, but a line in the error log that names the step
printf '#!/bin/bash\nexit 3\n' >"$T/git-broken"
printf '#!/bin/bash\necho "fatal: bad config line 1 in file .git/config" >&2\nexit 128\n' >"$T/git-fatal"
printf '#!/bin/bash\nexec sleep 2\n' >"$T/git-slow"; chmod +x "$T/git-broken" "$T/git-fatal" "$T/git-slow"
printf '#!/bin/bash\nfor a; do [ "$a" != log ] || exit 3; done\nexec git "$@"\n' >"$T/git-nolog"; chmod +x "$T/git-nolog"
# macOS checks a new executable on its first run, 0.05-2.0 s, and a later run from any process takes 3-4 ms: that
# first run stays out of the hook's 1.0 s git timer. Not git-slow: there the timeout is the result
"$T/git-broken"; "$T/git-fatal" 2>/dev/null; "$T/git-nolog" --version >/dev/null
errcase broken-git ' HookError git rev-parse rc=3' "$H/doc-reminder.sh" "$(inp $P "$R" "$C")" DOC_REMINDER_GIT="$T/git-broken"
errcase fatal-128 ' HookError git rev-parse rc=128' "$H/doc-reminder.sh" "$(inp $P "$R" "$C")" DOC_REMINDER_GIT="$T/git-fatal"
errcase git-timeout ' HookError git rev-parse timeout' "$H/doc-reminder.sh" "$(inp $P "$R" "$C")" DOC_REMINDER_GIT="$T/git-slow"
commit "$R" src/gl.ts   # the history of the run: git log
errcase git-log-fails ' HookError git log rc=3' "$H/doc-reminder.sh" "$(inp $P "$R" "$C")" DOC_REMINDER_GIT="$T/git-nolog"
chmod 000 "$R/.git/logs/HEAD"
errcase unreadable-reflog ' HookError reflog PermissionError' "$H/doc-reminder.sh" "$(inp $P "$R" "$C")"
chmod 644 "$R/.git/logs/HEAD"
# python that dies (exit 3) or a missing jq: the shim logs it and still exits 0
B="$T/dead-python"; mkdir -p "$B"; cp "$H/doc-reminder.sh" "$B/"; printf 'import sys\nsys.exit(3)\n' >"$B/doc-reminder.py"
errcase shim-exit ' ShimExit 3' "$B/doc-reminder.sh" "$(inp $P "$R" "$C")"
# the hook without its lib (a partial copy): one error-log line that names it, no traceback, exit 0
NL="$T/no-lib"; mkdir -p "$NL"; cp "$H/doc-reminder.sh" "$H/doc-reminder.py" "$NL/"
errcase lib-missing ' HookError lib ModuleNotFoundError' "$NL/doc-reminder.sh" "$(inp $P "$R" "$C")"
inp $P "$R" "$C" | DOC_REMINDER_NOW=$((TS + 1)) /bin/bash "$NL/doc-reminder.sh" >/dev/null 2>"$T/no-lib.err"
[ ! -s "$T/no-lib.err" ] || { echo "FAIL doc-reminder lib-missing: stderr $(head -c 200 "$T/no-lib.err")"; f=1; }
NJ="$T/no-jq"; mkdir -p "$NJ"; sed 's#/usr/bin/jq#/nonexistent/jq#' "$H/doc-reminder.sh" >"$NJ/doc-reminder.sh"
errcase jq-missing ' JqExit 127' "$NJ/doc-reminder.sh" "$(inp $P "$R" "$C")"
# jq_stub <dir> <stub body>: $T/<dir>/doc-reminder.sh runs the stub in place of /usr/bin/jq; a jq that does not compile,
# fails at runtime on valid JSON or prints a field name not in the set is a dead hook too
jq_stub() { mkdir -p "$T/$1"; printf '#!/bin/bash\n%s\n' "$2" >"$T/$1/jq"; chmod +x "$T/$1/jq"
  sed "s#/usr/bin/jq#$T/$1/jq#" "$H/doc-reminder.sh" >"$T/$1/doc-reminder.sh"; }
jq_stub exit-1 "cat >/dev/null; printf '\ngit commit -m x\nend\n'; exit 1"   # a plausible output does not outweigh the status
errcase jq-exit-1 ' JqExit 1' "$T/exit-1/doc-reminder.sh" "$(inp $P "$R" "$C")"
jq_stub cut "cat >/dev/null; printf 'tool_input\n'"   # the field line and nothing after it
errcase jq-cut ' JqOutput' "$T/cut/doc-reminder.sh" "$(inp $P "$R" "$C")"
jq_stub silent 'cat >/dev/null'   # exit 0 and no output
errcase jq-silent ' JqOutput' "$T/silent/doc-reminder.sh" "$(inp $P "$R" "$C")"
jq_stub usage 'cat >/dev/null; exit 2'
errcase jq-usage ' JqExit 2' "$T/usage/doc-reminder.sh" "$(inp $P "$R" "$C")"
jq_stub no-compile 'cat >/dev/null; exit 3'
errcase jq-no-compile ' JqExit 3' "$T/no-compile/doc-reminder.sh" "$(inp $P "$R" "$C")"
jq_stub runtime '[ "$1" = empty ] && exec /usr/bin/jq "$@"; cat >/dev/null; exit 5'   # the input is JSON
errcase jq-runtime ' JqExit 5' "$T/runtime/doc-reminder.sh" "$(inp $P "$R" "$C")"
jq_stub odd-field "cat >/dev/null; printf 'tool_inputs\ngit commit -m x\nend\n'"
errcase jq-odd-field ' JqOutput' "$T/odd-field/doc-reminder.sh" "$(inp $P "$R" "$C")"
# the default log path, the one doctor.sh reads, for python and for the shim
inp $P "$R" "$C" | env -u DOC_REMINDER_ERRLOG HOME="$T/home" DOC_REMINDER_GIT="$T/git-broken" "$H/doc-reminder.sh"
inp $P "$R" "$C" | env -u DOC_REMINDER_ERRLOG HOME="$T/home" /bin/bash "$B/doc-reminder.sh"
grep -q ' HookError git rev-parse rc=3$' "$T/home/.claude/logs/doc-reminder.err" 2>/dev/null &&
  grep -q ' ShimExit 3$' "$T/home/.claude/logs/doc-reminder.err" ||
  { echo "FAIL doc-reminder default-log-path: not both lines in ~/.claude/logs/doc-reminder.err"; f=1; }
# a full log (over 64 KB) moves to .1 and starts again with the new line
head -c 64100 /dev/zero | tr '\0' x >"$DOC_REMINDER_ERRLOG"
inp $P "$R" "$C" | DOC_REMINDER_GIT="$T/git-broken" "$H/doc-reminder.sh"
[ "$(size "$DOC_REMINDER_ERRLOG.1")" = 64100 ] && [ "$(wc -l <"$DOC_REMINDER_ERRLOG" | tr -d ' ')" = 1 ] ||
  { echo "FAIL doc-reminder error-log-rotate: .1 $(size "$DOC_REMINDER_ERRLOG.1") B, log $(size "$DOC_REMINDER_ERRLOG") B"; f=1; }
# over DRIFT_CAP (32000 B) no more ShapeDrift lines, but a shim that dies still gets its line
head -c 32100 /dev/zero | tr '\0' x >"$DOC_REMINDER_ERRLOG"
inp $P "$R" "$C" | /usr/bin/jq -c '.cwd = 5' | DOC_REMINDER_NOW=$((TS + 1)) "$H/doc-reminder.sh" >/dev/null
printf 'git commit, but not json' | "$H/doc-reminder.sh"
printf '' | "$H/doc-reminder.sh"
[ "$(size "$DOC_REMINDER_ERRLOG")" = 32100 ] || { echo "FAIL doc-reminder drift-cap: $(size "$DOC_REMINDER_ERRLOG") B"; f=1; }
inp $P "$R" "$C" | /bin/bash "$NJ/doc-reminder.sh"
tail -n 1 "$DOC_REMINDER_ERRLOG" | grep -q ' JqExit 127$' || { echo "FAIL doc-reminder drift-cap: no JqExit line after it"; f=1; }
# the shim adds nothing to a full log (python moves it to .1, the shim does not)
head -c 64100 /dev/zero | tr '\0' x >"$DOC_REMINDER_ERRLOG"
inp $P "$R" "$C" | /bin/bash "$NJ/doc-reminder.sh"
[ "$(size "$DOC_REMINDER_ERRLOG")" = 64100 ] || { echo "FAIL doc-reminder shim-full-log: $(size "$DOC_REMINDER_ERRLOG") B"; f=1; }

[ $f -eq 0 ] && echo "DOCS OK"; exit $f
