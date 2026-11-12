#!/bin/bash
# doctor.sh: read-only check that the managed live state equals the installed tag.
#
#   bash scripts/doctor.sh --live [--skip-tests]
#
# Prints "live = <tag>, drift N" and every drifted path: a managed file changed, missing or with another mode,
# an extra file inside a managed skill folder, a missing git ignore line (settings.json is compared as normalized
# JSON). Also: the hook tests (test-all.sh on the live hooks; it only feeds them sample input), whether the tag
# still points at the installed commit, the error logs of dup-guard, doc-reminder, session-hint, bash-guard, push-allow and
# node-std (internal errors apart from ShapeDrift: hook input of an unknown shape), whether Claude Code delivered session-hint's hints in the
# sessions of the last DELIVERY_DAYS days, hook failures of those days (tests/hint-delivered.py --doctor), project CLAUDE.md
# and AGENTS.md over STATE_MAX_KB in PROJECTS_DIR (default ~/WebstormProjects) and the docs there (a STATUS over STATUS_MAX_KB,
# a big journal or .md, a README or a doc of an area behind the code, active projects with no instructions, card, «З чого
# почати» or STATUS or with big memory files, the old template), the Node standard of the
# projects there and when versions.json is due (the stack line: node_std.py of the live skill), the docs repo of docs-sync
# and its error log (docs-sync.sh report: the registry, the connected projects, folders not in it, the push), the packs
# library when there is one (its catalog, the projects that enable a pack, what Claude Code still records of a catalog that is gone), the unmanaged
# items the base never touches, and whether the scan inside a commit works: real commits in a throwaway repo (scripts/commit-scan-probe.sh).
# Writes nothing outside a temporary folder. One call over the network: gh about the origin of the docs repo (up to
# DOCS_GH_SECS, 15 s; also with --skip-tests). Destinations: CLAUDE_HOME, HOME_AGENTS, GIT_EXCLUDES, BIN_DIR (see scripts/lib.sh).
# Exit: 0 drift 0 and hook tests OK | 1 drift or failing hook tests | 2 no or unreadable manifest; a WARN never
# changes it
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$HERE/lib.sh"

DELIVERY_DAYS=7   # owner's decision 27.10: sessions started in the last 7 days, not before the last install (hook failures: whatever the install)
DRIFT_RE='^[^ ]+ ShapeDrift( |$)'   # an error-log line of a hook input field with another type or missing
STATE_MAX_KB=30   # owner's decision 30.10: over this a project's instruction or state file costs every session
PROJECTS_DIR=${PROJECTS_DIR:-$HOME/WebstormProjects}

TESTS=1
while [ $# -gt 0 ]; do
  case $1 in
    --live) ;;
    --skip-tests) TESTS=0 ;;
    -h | --help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "doctor.sh: unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done
need_jq
W=$(mktemp -d "${TMPDIR:-/tmp}/setup-doctor.XXXXXX")
trap 'case $W in */setup-doctor.*) rm -rf -- "$W" ;; esac' EXIT

MAN=$(manifest_path)
if [ ! -e "$MAN" ]; then
  echo "live = unknown: no install manifest at $(show_path "$MANIFEST_KEY")"
  echo "  record the current state once it equals a tag: bash scripts/install.sh <tag> --record-only"
  exit 2
fi
manifest_ok "$MAN" || { echo "live = unknown: $MAN is not a readable schema-1 manifest"; exit 2; }

REF=$(manifest_field "$MAN" ref)
COMMIT=$(manifest_field "$MAN" commit)
rc=0
drift_scan "$MAN" "$W/drift"
N=$(wc -l <"$W/drift" | tr -d ' ')
echo "live = $REF, drift $N"
while IFS=$'\t' read -r reason key; do printf '  %-24s %s\n' "$reason" "$(show_path "$key")"; done <"$W/drift"
[ "$N" = 0 ] || rc=1

nitems=$("$JQ" '.items | length' "$MAN")
nfiles=$("$JQ" '.files | length' "$MAN")
nlines=$("$JQ" '[.merge_lines[]? | length] | add // 0' "$MAN")
nowned=$("$JQ" '[.merge_owned[]? | length] | add // 0' "$MAN")
echo "  manifest: $(show_path "$MANIFEST_KEY") (installed $(manifest_field "$MAN" installed_at), $(manifest_field "$MAN" how))"
echo "  managed:  $nitems items, $nfiles files, $nlines git ignore lines ($nowned added by the base; only those can be removed)"
for root in CLAUDE_HOME HOME_AGENTS GIT_EXCLUDES BIN_DIR; do
  # shellcheck disable=SC2016  # jq program
  rec=$("$JQ" -r --arg r "$root" '.roots[$r] // ""' "$MAN")
  now=$(key_path "$root")
  [ -z "$rec" ] || [ "$rec" = "$now" ] || echo "  WARN: manifest was written for $root=$rec, checking $now"
done

# Does the tag still point at the installed commit?
if [ "$REF" != WORKTREE ] && [ "$COMMIT" != - ] && command -v git >/dev/null 2>&1 &&
  git -C "$SETUP_REPO" rev-parse --git-dir >/dev/null 2>&1; then
  if tc=$(git -C "$SETUP_REPO" rev-parse -q --verify "refs/tags/$REF^{commit}" 2>/dev/null); then
    if [ "$tc" = "$COMMIT" ]; then echo "  tag:      $REF = commit ${COMMIT:0:12} in the repo"
    else echo "  WARN: tag $REF now points at ${tc:0:12}, the manifest has ${COMMIT:0:12}"; fi
  else
    echo "  WARN: tag $REF not found in $SETUP_REPO"
  fi
fi

if [ "$TESTS" = 1 ]; then
  if run_hook_tests "$CLAUDE_HOME/hooks" "$W/tests" </dev/null; then
    echo "  hooks:    test-all.sh: $(tr '\n' ' ' <"$W/tests" | sed 's/ *$//')"
  else
    echo "  hooks:    test-all.sh FAILED:"; sed 's/^/    /' "$W/tests"; rc=1
  fi
fi

# dup-guard, doc-reminder and session-hint never block and stay silent on an internal error; bash-guard then asks
# as before, also about text that does not run, and with a dead jq about every command. Each leaves a line in its error
# log. doc-reminder, session-hint and bash-guard also log ShapeDrift for an input field they read that came with another
# type or not at all, and go on as before; with no command to read bash-guard asks. push-allow (PermissionRequest) on
# an error or an input of another shape answers nothing: the permission prompt of a push comes as before
if [ -d "$CLAUDE_HOME/logs" ] && [ ! -w "$CLAUDE_HOME/logs" ]; then
  echo "  WARN: $(show_path CLAUDE_HOME/logs) is not writable: dup-guard, doc-reminder, session-hint, bash-guard, push-allow and docs-sync cannot log their errors"
fi
for h in dup-guard:"no duplicates" doc-reminder:"nothing to remind" session-hint:"no hint" \
    bash-guard:"an ask about text that does not run, with a dead jq about every command" \
    push-allow:"a permission prompt for every push to a feature branch" \
    node-std:"no upgrade proposal"; do
  name=${h%%:*}; ERRLOG="$CLAUDE_HOME/logs/$name.err"
  if [ -e "$ERRLOG" ] && [ ! -w "$ERRLOG" ]; then
    echo "  WARN: $(show_path "CLAUDE_HOME/logs/$name.err") is not writable: $name cannot log its errors"
  fi
  [ -s "$ERRLOG" ] || continue
  if [ ! -r "$ERRLOG" ]; then echo "  WARN: $(show_path "CLAUDE_HOME/logs/$name.err") is not readable: its lines are not shown"; continue; fi
  older=""; [ ! -e "$ERRLOG.1" ] || older=", older lines are in $name.err.1"
  drift=$(grep -cE "$DRIFT_RE" "$ERRLOG" || true)
  errors=$(($(grep -c '' "$ERRLOG" || true) - drift))
  if [ "$errors" -gt 0 ]; then
    echo "  WARN: $name internal errors: $errors in $(show_path "CLAUDE_HOME/logs/$name.err"), last: $(grep -vE "$DRIFT_RE" "$ERRLOG" | tail -n 1 | cut -c1-120)"
    echo "        (a dead hook reads as \"${h#*:}\"; the line names the cause: HookError git (try /usr/bin/git --version), ShimExit or ShimOutput (python3), JqExit or JqOutput (jq), HookExit (bash-guard stopped and asked, most often a failed fork: the process limit ran out; this line has no date, the time is in the line of hook failures), TimeLimit (a command too long for bash-guard or staged text too long for gitleaks: it asked, the hook is fine; with \"in commit-leaks\": the commit was refused), GitleaksExit (no verdict on the secrets of a commit, it asked; with \"in commit-leaks\": the commit went on with a line in its output; 127: no gitleaks on PATH or in /opt/homebrew/bin); node-std: ImportError or ModuleNotFoundError skill (no skill new-project), JSONDecodeError skill (its versions.json), PermissionError state (~/.claude/state), LockBusy state, TimeLimit (over 5 s), the project gets the line in a later session; after the fix delete the file$older)"
  fi
  if [ "$drift" -gt 0 ]; then
    echo "  WARN: $name input of an unknown shape: $drift in $(show_path "CLAUDE_HOME/logs/$name.err"), last: $(grep -E "$DRIFT_RE" "$ERRLOG" | tail -n 1 | cut -c1-120)"
    echo "        (ShapeDrift names the input fields: did a Claude Code update change the hook input? Compare with docs/compat.md, fix the hook and its tests; after the fix delete the file$older)"
  fi
done

# commit-leaks: git takes it from the env of settings.json and a commit that lands says nothing about it, so a dead scan shows
# nowhere else. Real commits with that env, on the live hook; no keys, no line
if scan=$(bash "$HERE/commit-scan-probe.sh" "$CLAUDE_HOME/settings.json" 2>&1); then scanrc=0; else scanrc=$?; fi
case $scanrc in
  0) echo "  commit scan: OK, a commit with a made-up token stops" ;;
  2) ;;
  *) echo "  WARN: commit scan: $scan" ;;
esac

# session-hint delivery in live sessions (tests/hint-delivered.py reads the transcripts): one line and WARNs; exit 0
# to 2 is its verdict, but only with the delivery line first (python itself exits 1 or 2 on a broken script). The same
# run prints the line of hook failures, a WARN when there are any: a hook that fails never blocks, so nothing else shows it
if command -v python3 >/dev/null 2>&1; then
  if dout=$(python3 -I "$SETUP_REPO/tests/hint-delivered.py" --doctor --days "$DELIVERY_DAYS" --claude-home "$CLAUDE_HOME" </dev/null 2>&1); then drc=0; else drc=$?; fi
  if [ "$drc" -le 2 ] && [[ $dout == delivery:* ]]; then printf '%s\n' "$dout" | sed 's/^/  /'
  else echo "  WARN: delivery: tests/hint-delivered.py broke (exit $drc), last line: $(printf '%s\n' "$dout" | tail -n 1 | cut -c1-120)"; fi
else
  echo "  WARN: delivery and hook failures: not checked, no python3"
fi

# Project files read at the start of a session: only their sizes; a line that says how many were read, so a wrong
# PROJECTS_DIR does not pass for small files; a WARN for each one over the limit or unreadable, and the rule once
seen=0; big=0
for f in "$PROJECTS_DIR"/*/CLAUDE.md "$PROJECTS_DIR"/*/AGENTS.md "$PROJECTS_DIR"/*/STATUS.md \
    "$PROJECTS_DIR"/*/docs/STATUS.md "$PROJECTS_DIR"/*/.claude/state/STATUS.md; do
  [ -e "$f" ] || [ -L "$f" ] || continue
  seen=$((seen + 1))
  if [ ! -f "$f" ] || [ ! -r "$f" ] || ! bytes=$(wc -c 2>/dev/null <"$f" | tr -d ' '); then   # a FIFO would hang wc
    echo "  WARN: project file not readable: ${f#"$PROJECTS_DIR"/}"; continue
  fi
  case $f in */STATUS.md) continue ;; esac   # the size of a STATUS has its own, lower limit: STATUS_MAX_KB below
  [ "$bytes" -gt $((STATE_MAX_KB * 1024)) ] || continue
  big=$((big + 1))
  echo "  WARN: project file over $STATE_MAX_KB KB: ${f#"$PROJECTS_DIR"/}: $(((bytes + 1023) / 1024)) KB"
done
if [ "$seen" -eq 0 ]; then
  echo "  WARN: project files not checked: no CLAUDE.md, AGENTS.md or STATUS in the folders of $PROJECTS_DIR"
else
  echo "  projects: $seen CLAUDE.md, AGENTS.md and STATUS files read in $PROJECTS_DIR, CLAUDE.md and AGENTS.md over $STATE_MAX_KB KB: $big"
fi
if [ "$big" -gt 0 ]; then
  echo "        (instruction files hold rules and facts, ~15 KB, no log)"
fi

# Project docs (owner's decisions 03.11.2026 and 11.11.2026), WARNs only. Lines of their own: an .md over MD_MAX_KB
# outside an archive path, a README last changed over README_LAG_DAYS days and README_LAG_COMMITS commits before HEAD, a
# project with commits or sessions in ACTIVE_DAYS days and no instruction file or no card («## Розмір»), the old template.
# One "docs state" line per project, its items joined with "; ": a STATUS over STATUS_MAX_KB (bytes, not lines: a line may
# hold kilobytes; the item names an archive file under its folder, a path there with "status" and the word "archive", or
# none); and only in an active project, where a session pays for it: a working journal over JOURNAL_MAX_KB outside an
# archive path and a doc of an area (deploy, schema, API, integrations) behind the code of that area, by the README's
# limits (both: scripts/docs_state.py, with the names of hooks/doc_reminder_lib.py), no STATUS at all, memory files over
# MEM_FILE_MAX_KB (the state belongs in STATUS), a card with no «З чого почати». A worktree folder (a .git file) holds copies and a link may lead
# anywhere: both are skipped; the base itself needs no card. A repo git cannot read gets its own WARN, so it does not
# pass for "nothing found" (an unreadable file: the section above)
STATUS_MAX_KB=8 JOURNAL_MAX_KB=40 MD_MAX_KB=200 README_LAG_DAYS=21 README_LAG_COMMITS=10 AREA_WINDOW_DAYS=180
ACTIVE_DAYS=30 MEM_FILE_MAX_KB=5
OLD_TEMPLATE='Project Agent Operating Standard'
DOCS_STATE="$HERE/docs_state.py" DOC_LIB="$SETUP_REPO/hooks"
TIME_RE='"timestamp": *"[0-9T:.-]*Z"'   # the time of a transcript record
# git of the project: never the caller's repo (a git hook exports GIT_DIR, and -C does not override it) and never one
# above PROJECTS_DIR (a broken .git sends git looking upwards)
pg() {
  env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE -u GIT_OBJECT_DIRECTORY -u GIT_ALTERNATE_OBJECT_DIRECTORIES \
    -u GIT_COMMON_DIR -u GIT_PREFIX GIT_CEILING_DIRECTORIES="$PROJECTS_DIR" git --no-optional-locks -C "$d" "$@" 2>/dev/null
}
archived() {   # <path>: has the word archive, archives or archived (not "archiver")
  case "/$(lower "$1" | tr '._-' '///')/" in */archive/* | */archives/* | */archived/*) return 0 ;; esac
  return 1
}
status_archive() {   # <STATUS path in the project>: the archive path in the project, or nothing
  local dir=$d depth=1 p
  [ "$1" = STATUS.md ] || { dir=$d/$(dirname "$1"); depth=3; }
  while IFS= read -r p; do
    ! archived "${p#"$dir"/}" || { printf '%s' "${p#"$d"/}"; return; }
  done < <(find "$dir" -maxdepth "$depth" \( -name node_modules -o -name .git \) -prune -o -type f -iname '*status*' -print 2>/dev/null | sort)
}
readme_behind() {   # the WARN of a tracked root README last changed long and many commits before HEAD; 1: git failed
  local r rd head n lag
  r=$(pg ls-files -- ':(glob,icase)readme*' | { grep -ixE 'readme(\.[a-z]+)*' || true; } | sed -n 1p) || return 1
  [ -n "$r" ] || return 0
  rd=$(pg log -1 --format='%H %ct' -- "$r") || return 1
  [ -n "$rd" ] || return 0
  head=$(pg log -1 --format=%ct HEAD) && n=$(pg rev-list --count "${rd%% *}..HEAD") || return 1
  lag=$(((head - ${rd#* }) / 86400))
  [ "$lag" -gt "$README_LAG_DAYS" ] && [ "$n" -ge "$README_LAG_COMMITS" ] || return 0
  nreadme=$((nreadme + 1))
  echo "  WARN: README behind the code: $name/$r: last changed $lag days and $n commits before HEAD"
}
# Transcripts of the project and its .claude/worktrees (folders named as Claude Code names them) whose last record with a
# time is newer than ACTIVE_DAYS days: the file time alone says nothing, Claude Code appends records with no time to old
# sessions. The last 64 KB hold that time unless a big record ends the file: then the whole file. Prints "<sessions>
# <transcripts with no time>"
since=$(date -u -v-"$ACTIVE_DAYS"d +%Y%m%d%H%M%S)
sessions() {
  local enc f t n=0 none=0
  enc=$(printf '%s' "$d" | sed 's/[^A-Za-z0-9]/-/g')
  while IFS= read -r f; do
    t=$(tail -c 65536 "$f" 2>/dev/null | grep -ao "$TIME_RE" | tail -n 1) ||
      t=$(grep -ao "$TIME_RE" "$f" 2>/dev/null | tail -n 1) || { none=$((none + 1)); continue; }
    t=${t//[!0-9]/}
    [ "${#t}" -ge 14 ] && [ "${t:0:14}" -gt "$since" ] && n=$((n + 1))
  done < <(find "$CLAUDE_HOME/projects/$enc" "$CLAUDE_HOME/projects/$enc--claude-worktrees-"* -maxdepth 1 -type f \
    -name '*.jsonl' -size +0c -mtime -"$ACTIVE_DAYS" 2>/dev/null)
  echo "$n $none"
}
git_failed() { ngit=$((ngit + 1)); gitfail="${gitfail:+$gitfail, }$name"; }
item() { items="${items:+$items; }$1"; }
memory_big() {   # how many memory files of the project are over MEM_FILE_MAX_KB
  local m
  m="$CLAUDE_HOME/projects/$(printf '%s' "$d" | sed 's/[^A-Za-z0-9]/-/g')/memory"
  [ -d "$m" ] || { echo 0; return; }
  { find "$m" -type f -size +"$((MEM_FILE_MAX_KB * 1024))"c 2>/dev/null || true; } | grep -c '' || true
}
state_check=1
if ! command -v python3 >/dev/null 2>&1; then
  echo "  WARN: journals and area docs: not checked, no python3"; state_check=0
elif [ ! -f "$DOCS_STATE" ] || [ ! -f "$DOC_LIB/doc_reminder_lib.py" ]; then
  echo "  journals and area docs: not checked, no scripts/docs_state.py or hooks/doc_reminder_lib.py in $SETUP_REPO"; state_check=0
fi
dseen=0 nskip=0 nstatus=0 njournal=0 narea=0 nmd=0 nreadme=0 nbare=0 ncard=0 nnostatus=0 nmem=0 nstart=0 old=0
old_active="" ngit=0 gitfail="" notime=0 statefail=""
for d in "$PROJECTS_DIR"/*/; do
  d=${d%/}
  [ -d "$d" ] || continue
  if [ -L "$d" ] || [ -f "$d/.git" ]; then nskip=$((nskip + 1)); continue; fi
  name=${d#"$PROJECTS_DIR"/}; dseen=$((dseen + 1)); items="" has_status=0
  for s in STATUS.md docs/STATUS.md .claude/state/STATUS.md; do
    [ -f "$d/$s" ] || continue
    has_status=1
    b=$(stat -L -f %z "$d/$s" 2>/dev/null) || continue   # the size needs no read access; -L: of the file a link leads to
    [ "$b" -gt $((STATUS_MAX_KB * 1024)) ] || continue
    nstatus=$((nstatus + 1)); a=$(status_archive "$s")
    item "STATUS $s $(((b + 1023) / 1024)) KB (archive: ${a:-none})"
  done
  # one find for both sizes: an .md over MD_MAX_KB is a WARN of its own, a smaller one over JOURNAL_MAX_KB may be a journal
  cand=""
  while IFS= read -r f; do
    rel=${f#"$d"/}
    ! archived "$rel" || continue
    b=$(stat -f %z "$f" 2>/dev/null) || continue
    if [ "$b" -gt $((MD_MAX_KB * 1024)) ]; then
      nmd=$((nmd + 1)); echo "  WARN: md file over $MD_MAX_KB KB: $name/$rel: $(((b + 1023) / 1024)) KB"
    else
      cand="$cand$rel"$'\n'
    fi
  done < <(find "$d" \( -name node_modules -o -name .git -o -name dist -o -name build -o -name .next -o -name vendor \
    -o -path '*/.claude/worktrees' \) -prune -o -type f -name '*.md' -size +"$JOURNAL_MAX_KB"k -print 2>/dev/null | sort)
  nc=0
  if [ -d "$d/.git" ]; then   # a repo with no commit yet (HEAD names a branch that is not there) is no failure
    if ! pg rev-parse --git-dir >/dev/null; then
      git_failed
    elif pg rev-parse -q --verify HEAD >/dev/null; then
      { readme_behind && nc=$(pg rev-list --count --since="$ACTIVE_DAYS.days" HEAD); } || { nc=0; git_failed; }
    elif ! pg symbolic-ref -q HEAD >/dev/null; then   # a branch file that is empty or broken
      git_failed
    fi
  fi
  inst=0 card=0 start=0 tmpl=0 base=0 ns=0
  for f in CLAUDE.md AGENTS.md CLAUDE.local.md .claude/CLAUDE.md; do
    [ -f "$d/$f" ] || continue
    inst=1
    [ -r "$d/$f" ] || continue
    ! grep -q '^## Розмір' "$d/$f" 2>/dev/null || card=1
    ! grep -q '^## З чого почати' "$d/$f" 2>/dev/null || start=1
    ! grep -qF "$OLD_TEMPLATE" "$d/$f" 2>/dev/null || tmpl=1
  done
  if [ "$d" -ef "$SETUP_REPO" ]; then base=1; fi
  # The sessions are read unless a commit already makes the project active and no line names their count
  if [ "$nc" -eq 0 ] || [ "$tmpl" = 1 ] || { [ "$inst$card" != 11 ] && [ "$base" = 0 ]; }; then
    ns=$(sessions); notime=$((notime + ${ns#* })); ns=${ns%% *}
  fi
  if [ "$tmpl" = 1 ]; then
    old=$((old + 1)); [ $((nc + ns)) -eq 0 ] || old_active="${old_active:+$old_active, }$name"
  fi
  if [ $((nc + ns)) -gt 0 ]; then   # an active project: what its sessions read and what they start from
    if [ "$state_check" = 1 ]; then
      if sout=$(printf '%s' "$cand" | python3 -I "$DOCS_STATE" "$DOC_LIB" "$d" "$README_LAG_DAYS" "$README_LAG_COMMITS" \
        "$AREA_WINDOW_DAYS" 2>/dev/null); then
        while IFS=$'\t' read -r kind a1 a2 a3 a4; do
          case $kind in
            journal)
              b=$(stat -f %z "$d/$a1" 2>/dev/null) || continue
              njournal=$((njournal + 1)); item "journal $a1 $(((b + 1023) / 1024)) KB" ;;
            area) narea=$((narea + 1)); item "$a1 doc $a2 behind its area by $a3 commits and $a4 days" ;;
          esac
        done <<<"$sout"
      else
        statefail="${statefail:+$statefail, }$name"
      fi
    fi
    if [ "$base" = 1 ]; then :
    elif [ "$inst" = 0 ]; then
      nbare=$((nbare + 1)); echo "  WARN: no instruction file in an active project: $name ($nc commits, $ns sessions in $ACTIVE_DAYS days)"
    elif [ "$card" = 0 ]; then
      ncard=$((ncard + 1)); echo "  WARN: no card («## Розмір») in an active project: $name ($nc commits, $ns sessions in $ACTIVE_DAYS days)"
    elif [ "$start" = 0 ]; then
      nstart=$((nstart + 1)); item "no «З чого почати» in the card"
    fi
    if [ "$has_status" = 0 ]; then nnostatus=$((nnostatus + 1)); item "no STATUS"; fi
    nmembig=$(memory_big)
    if [ "$nmembig" -gt 0 ]; then nmem=$((nmem + 1)); item "$nmembig memory files over $MEM_FILE_MAX_KB KB"; fi
  fi
  [ -z "$items" ] || echo "  WARN: docs state: $name: $items"
done
if [ "$old" -gt 0 ]; then
  echo "  WARN: old template («${OLD_TEMPLATE}») in $old projects; of them active in $ACTIVE_DAYS days: ${old_active:-none}"
fi
if [ -n "$gitfail" ]; then
  echo "  WARN: git cannot read the repo (README and commits not checked; git -C <folder> status says why): $gitfail"
fi
if [ "$notime" -gt 0 ]; then
  echo "  WARN: transcripts of $ACTIVE_DAYS days with no record time (a new Claude Code format?): $notime, their sessions not counted"
fi
if [ -n "$statefail" ]; then
  echo "  WARN: journals and area docs not checked, scripts/docs_state.py failed (run it on the folder to see why): $statefail"
fi
echo "  docs: $dseen project folders, skipped $nskip (link, worktree copy); STATUS over $STATUS_MAX_KB KB $nstatus, journals over $JOURNAL_MAX_KB KB $njournal, area docs behind $narea, md over $MD_MAX_KB KB $nmd, README behind $nreadme, active without instructions $nbare, without a card $ncard, without «З чого почати» $nstart, without STATUS $nnostatus, with memory files over $MEM_FILE_MAX_KB KB $nmem, old template $old, git failed $ngit"
if [ $((nstatus + njournal + narea + nmd + nreadme + nbare + ncard + nstart + nnostatus + nmem + old)) -gt 0 ]; then
  echo "        (each project in its own session: STATUS keeps the state on top, up to 6 KB, history goes to STATUS-archive.md next to it; a journal keeps its current part, the rest goes to an archive file; README and the doc of an area follow the code; the state lives in STATUS, not in memory: a memory file holds one durable fact, up to $MEM_FILE_MAX_KB KB; the card starts with «З чого почати»: where STATUS is, the docs index, the commands; an active project gets instructions and a card from /new-project; the old template goes)"
fi

# The Node standard of the projects (owner's decisions 03.11.2026), WARNs only: node_std.py of the live skill reads its
# versions.json and the project folders (a link and a worktree copy aside) and prints the stack line with counts, then
# the projects out of support or within 6 months of it, those behind, versions.json checked over 35 days ago, a newer
# LTS line two weeks old. Its own exit 1 or a missing line is a WARN, never the exit of doctor
NODE_STD="$CLAUDE_HOME/skills/new-project/node_std.py"
if [ ! -f "$NODE_STD" ]; then
  echo "  stack: not checked, no $(show_path CLAUDE_HOME/skills/new-project/node_std.py) (a tag before v2026.11.19)"
elif [ ! -d "$PROJECTS_DIR" ]; then
  echo "  stack: not checked, no folder $PROJECTS_DIR"
elif ! command -v python3 >/dev/null 2>&1; then
  echo "  WARN: stack: not checked, no python3"
else
  if sout=$(python3 -I "$NODE_STD" --doctor "$PROJECTS_DIR" </dev/null 2>&1); then src=0; else src=$?; fi
  if [ "$src" = 0 ] && [[ $sout == '  stack: '* ]]; then printf '%s\n' "$sout"
  else echo "  WARN: stack: node_std.py failed (exit $src): $(printf '%s\n' "$sout" | tail -n 1 | cut -c1-160)"; fi
fi

# The docs repo of docs-sync (owner's decision 03.11.2026), read only: docs-sync.sh report prints its WARNs and the
# summary line. Its git hooks never stop a commit or a push: a failure is a line in the output of that commit and one
# in the error log, shown here also when docs-sync is gone (a rollback), as the hook keys of its projects stay
ERRLOG="$CLAUDE_HOME/logs/docs-sync.err"
DOCS_REPO=${DOCS_SYNC_REPO:-$HOME/project-docs}
if [ -f "$CLAUDE_HOME/hooks/docs_sync.py" ]; then
  if dsync=$(DOCS_SYNC_PROJECTS=$PROJECTS_DIR bash "$CLAUDE_HOME/hooks/docs-sync.sh" report 2>&1); then dsrc=0; else dsrc=$?; fi
  if [ "$dsrc" = 0 ]; then
    printf '%s\n' "$dsync"
  else
    echo "  WARN: docs repo: the report failed (exit $dsrc): $(printf '%s\n' "$dsync" | tail -n 1 | cut -c1-160)"
  fi
elif [ -d "$DOCS_REPO/.git" ]; then
  t='~'
  echo "  WARN: docs repo: ${DOCS_REPO/#$HOME/$t} is there, docs-sync is not installed: each commit of a connected project prints a line (install the base again, or git config --remove-section hook.docs-sync and hook.docs-sync-push in those projects)"
fi
# The origin of the docs repo must be a private GitHub repo: docs-sync pushes the docs of client projects there in the
# background with no ask, and nothing else looks at its visibility after init (owner's decision 11.11.2026). One read-only
# call of gh for each repo a push goes to (every pushurl, else the url), as in scripts/git-hooks/pre-push; any answer but
# PRIVATE, or none in DOCS_GH_SECS, is a WARN. Neither the URL (it may hold a token) nor the name of the repo is printed
DOCS_GH_SECS=${DOCS_GH_SECS:-15}   # the variable: tests only
docs_origin_line(){   # docs_origin_line <repo>: the line of its origin; nothing with no repo there or no origin
  local urls url slug slugs="" vis
  [ -d "$1/.git" ] || return 0
  # where git push origin sends: every pushurl, else the url
  urls=$(git -C "$1" remote get-url --push --all origin 2>/dev/null) || return 0
  while IFS= read -r url; do
    case $url in
      git@github.com:*) slug=${url#git@github.com:} ;;
      ssh://git@github.com/*) slug=${url#ssh://git@github.com/} ;;
      https://github.com/*) slug=${url#https://github.com/} ;;
      *) slug= ;;
    esac
    slug=${slug%/}; slug=${slug%.git}
    if ! [[ $slug =~ ^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$ ]]; then
      echo "  WARN: docs repo origin: not a GitHub repo, its privacy is not checked: docs-sync pushes the docs of client projects there with no ask"
      return 0
    fi
    case " $slugs " in *" $slug "*) ;; *) slugs="$slugs $slug" ;; esac
  done <<<"$urls"
  if ! command -v gh >/dev/null 2>&1; then
    echo "  WARN: docs repo origin: privacy not checked, no gh"
    return 0
  fi
  for slug in $slugs; do
    if command -v gtimeout >/dev/null 2>&1; then
      vis=$(gtimeout "$DOCS_GH_SECS" gh repo view "github.com/$slug" --json visibility -q .visibility 2>/dev/null) || vis=
    else   # the alarm stays over the exec and ends a gh that waits
      vis=$(/usr/bin/perl -e 'alarm shift; exec @ARGV' "$DOCS_GH_SECS" gh repo view "github.com/$slug" --json visibility -q .visibility 2>/dev/null) || vis=
    fi
    case $vis in
      PRIVATE) ;;
      PUBLIC | INTERNAL)
        echo "  WARN: docs repo origin: GitHub says $vis, not PRIVATE: docs-sync pushes the docs of client projects there in the background with no ask (make the repo private, or stop the push: git -C <docs repo> remote remove origin)"
        return 0 ;;
      *)
        echo "  WARN: docs repo origin: privacy not checked (no answer of gh in $DOCS_GH_SECS s: gh, the network or the sign-in)"
        return 0 ;;
    esac
  done
  echo "  docs repo origin: PRIVATE on GitHub"
}
docs_origin_line "$DOCS_REPO"
if [ -e "$ERRLOG" ] && [ ! -w "$ERRLOG" ]; then
  echo "  WARN: $(show_path CLAUDE_HOME/logs/docs-sync.err) is not writable: docs-sync cannot log its errors"
fi
if [ -s "$ERRLOG" ] && [ ! -r "$ERRLOG" ]; then
  echo "  WARN: $(show_path CLAUDE_HOME/logs/docs-sync.err) is not readable: its lines are not shown"
elif [ -s "$ERRLOG" ]; then
  older=""; [ ! -e "$ERRLOG.1" ] || older=", older lines are in docs-sync.err.1"
  classes=$(awk '{n[$2]++} END {for (c in n) print c, n[c]}' "$ERRLOG" | LC_ALL=C sort | paste -sd, - | sed 's/,/, /g')
  echo "  WARN: docs-sync: $(grep -c '' "$ERRLOG" || true) lines in $(show_path CLAUDE_HOME/logs/docs-sync.err) ($classes), last: $(tail -n 1 "$ERRLOG" | LC_ALL=C tr -d '\000-\037\177' | cut -c1-120)"
  echo "        (SyncError: a sync stopped or files were not copied or deleted, the line says why: a secret with its file and line, no verdict or no time of gitleaks, a busy docs repo, a git or the hook too slow; Kept: a source emptied, mostly deleted or no longer a source, its copy stays (docs-sync.sh sync <folder> applies the first two); PushFailed: a push in the background, by class: auth (gh auth status, the access to the repo), network (the next commit tries again), rejected (other commits on origin: git -C ~/project-docs pull --rebase origin main), no repo (the URL of origin), other (docs-sync.sh push says more), or the scan that stopped it; ShimExit: python3 (127 missing, 142 over 60 s); Error: a fault in docs-sync. The next commit or push of the project syncs and pushes again; after the fix delete the file$older)"
fi

# The packs library (ADR-007), read only. Silent when the base has no catalog and Claude Code keeps no record of one
# (a tag before the library, the public version). With a catalog: one line with its packs, whether Claude Code has
# registered it, and the projects of PROJECTS_DIR that enable a pack (enabledPlugins in .claude/settings.local.json;
# a link and a worktree copy aside). WARNs: a pack that a project enables and the catalog does not have (a rollback
# took it: the session starts without it and says nothing, only `claude plugin list` does); a settings.local.json
# that does not read; a catalog.json that does not read (then the projects are not looked at); with a catalog, a
# record file of Claude Code that does not read; and, with no catalog installed, the records Claude Code keeps of it in
# ~/.claude/plugins: no install or rollback touches those files, the records are harmless and stay until removed by
# hand. A key of a project's settings that is not a pack name is not printed (the file may come with a cloned repo)
LIB=library
CAT="$CLAUDE_HOME/packs/catalog.json"
PLUG="$CLAUDE_HOME/plugins"
rec_cat=false rec_packs=0 rec_bad=""
if [ -e "$PLUG/known_marketplaces.json" ]; then
  # jq -n with input: an empty file (a write cut short) is an error as well, not "no record"
  rec_cat=$("$JQ" -n -r --arg c "$LIB" 'input | has($c)' "$PLUG/known_marketplaces.json" 2>/dev/null) || { rec_cat=unknown; rec_bad=known_marketplaces.json; }
fi
if [ -e "$PLUG/installed_plugins.json" ]; then
  rec_packs=$("$JQ" -n -r --arg s "@$LIB" '[(input.plugins // {}) | keys[] | select(endswith($s))] | length' "$PLUG/installed_plugins.json" 2>/dev/null) ||
    { rec_packs=0; rec_bad="${rec_bad:+$rec_bad, }installed_plugins.json"; }
fi
lib_names="" lib_state=none
if [ -f "$CAT" ]; then
  if lib_names=$("$JQ" -r --arg c "$LIB" 'if .schema == 1 and .catalog == $c then .packs[].name else error("another catalog") end' "$CAT" 2>/dev/null); then
    lib_state=ok
  else
    lib_state=broken
    echo "  WARN: library: $(show_path CLAUDE_HOME/packs/catalog.json) does not read as the catalog $LIB: claude-pack cannot list or enable packs (install the base again)"
  fi
  [ -z "$rec_bad" ] || echo "  WARN: library: $rec_bad in $(show_path CLAUDE_HOME/plugins) does not read: what Claude Code records of the catalog is not known"
elif [ "$rec_cat" = true ] || [ "$rec_packs" -gt 0 ]; then
  lib_state=gone
  echo "  WARN: library: no catalog in $(show_path CLAUDE_HOME/packs), but $(show_path CLAUDE_HOME/plugins) still names it (known_marketplaces.json: the catalog $LIB $([ "$rec_cat" = true ] && echo yes || echo no); installed_plugins.json: $rec_packs record(s) of its packs): left by a rollback to a tag without the library, harmless; no install touches these files, remove the records by hand if they are in the way"
fi
if [ "$lib_state" = ok ] || [ "$lib_state" = gone ]; then
  : >"$W/lib-on"; lib_unread=""
  for f in "$PROJECTS_DIR"/*/.claude/settings.local.json; do
    [ -f "$f" ] || continue
    d=${f%/.claude/settings.local.json}
    if [ -L "$d" ] || [ -f "$d/.git" ]; then continue; fi
    if on=$("$JQ" -r --arg s "@$LIB" '(.enabledPlugins // {}) | to_entries[] | select(.value == true and (.key | test("^[a-z0-9][a-z0-9-]{0,63}" + $s + "\\z"))) | .key | rtrimstr($s)' "$f" 2>/dev/null); then
      while IFS= read -r pk; do
        [ -z "$pk" ] || printf '%s\t%s\n' "$pk" "${d#"$PROJECTS_DIR"/}" >>"$W/lib-on"
      done <<<"$on"
    else
      lib_unread="${lib_unread:+$lib_unread, }${d#"$PROJECTS_DIR"/}"
    fi
  done
  [ -z "$lib_unread" ] || echo "  WARN: library: .claude/settings.local.json does not read as JSON, its packs are not known: $lib_unread"
  # pack TAB projects joined with ", ", for the packs of the catalog (known) and for the others (lost)
  awk -F'\t' 'NR == FNR { if (length($0)) have[$0] = 1; next }
    { n[$1]++; p[$1] = (p[$1] == "" ? "" : p[$1] ", ") $2 }
    END { for (k in n) print ((k in have) ? "known" : "lost") "\t" k "\t" n[k] "\t" p[k] }' \
    <(printf '%s\n' "$lib_names") "$W/lib-on" | LC_ALL=C sort >"$W/lib-use"
  while IFS=$'\t' read -r kind pk n projects; do
    [ "$kind" = lost ] || continue
    # with no catalog the rollback took claude-pack away as well: the way out is the key itself
    lib_fix="set enabledPlugins[\"$pk@$LIB\"] to false in their .claude/settings.local.json"
    # shellcheck disable=SC2088  # text for the reader, not a path to expand
    [ "$lib_state" != ok ] || lib_fix="~/bin/claude-pack disable $pk there"
    echo "  WARN: library: pack $pk is enabled in $n project(s) ($projects), the catalog has no such pack: their sessions start without it and say nothing ($lib_fix, or install a tag that has the pack)"
  done <"$W/lib-use"
  if [ "$lib_state" = ok ]; then
    npk=$(printf '%s\n' "$lib_names" | grep -c . || true)
    names=$(printf '%s\n' "$lib_names" | paste -sd, - | sed 's/,/, /g')
    used=$(awk -F'\t' '$1 == "known" { printf "%s%s in %s (%s)", sep, $2, $3, $4; sep = "; " }' "$W/lib-use")
    case $rec_cat in true) reg=yes ;; unknown) reg="not known" ;; *) reg="not yet (a session registers the catalog on its own)" ;; esac
    echo "  library: $npk pack(s) in $(show_path CLAUDE_HOME/packs)${names:+ ($names)}; registered by Claude Code: $reg; enabled: ${used:-in no project of $PROJECTS_DIR}"
  fi
fi

# Unmanaged items next to managed ones (never touched by install/rollback)
manifest_items "$MAN" | cut -f2 >"$W/keys"
un=""
for p in "$CLAUDE_HOME"/skills/* "$CLAUDE_HOME"/agents/* "$CLAUDE_HOME"/rules/* "$CLAUDE_HOME"/hooks/* "$CLAUDE_HOME"/packs/*; do
  [ -e "$p" ] || [ -L "$p" ] || continue
  key="CLAUDE_HOME/${p#"$CLAUDE_HOME"/}"
  grep -Fxq -- "$key" "$W/keys" || un="$un ${key#CLAUDE_HOME/}"
done
echo "  unmanaged (never touched):${un:- none}"
if [ -d "$CLAUDE_HOME/.setup-lock" ]; then
  echo "  WARN: $CLAUDE_HOME/.setup-lock exists (pid $(cat "$CLAUDE_HOME/.setup-lock/pid" 2>/dev/null || echo '?'): an install is running, or a stale lock that the next install takes over)"
fi
if [ -d "$CLAUDE_HOME/.setup-staging" ]; then echo "  WARN: $CLAUDE_HOME/.setup-staging exists (left by an interrupted install; safe to move away)"; fi
exit "$rc"
