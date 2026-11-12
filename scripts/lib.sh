# shellcheck shell=bash
# shellcheck disable=SC2016  # jq programs are single-quoted on purpose
# lib.sh: shared paths and helpers for install.sh, snapshot.sh, rollback.sh, doctor.sh.
# Sourced, never run. Works with macOS /bin/bash 3.2 (no associative arrays, no mapfile).
#
# Destinations (defaults = live paths; override them for sandbox tests):
#   CLAUDE_HOME   (~/.claude)            HOME_AGENTS (~/AGENTS.md)
#   GIT_EXCLUDES  (~/.config/git/ignore) BIN_DIR     (~/bin)
#   SNAPSHOT_ROOT (~/claude-backups/setup-snapshots)
# Either all four destinations are live or none is: a mixed set is refused. Non-live (sandbox) destinations
# and a sandbox SNAPSHOT_ROOT must sit under /private/tmp or /private/var/folders (the system temp folders),
# so a typo can never point a sandbox run at the home folder, a project or this repo. With live
# destinations SNAPSHOT_ROOT must be the default one. Paths are compared case-insensitively (APFS).
#
# The managed list is derived from the repo layout (managed_items), not from a hand-kept list:
#   global/CLAUDE.global.md      -> CLAUDE_HOME/CLAUDE.md
#   global/settings.json         -> CLAUDE_HOME/settings.json   (written last)
#   global/home-agents.md        -> HOME_AGENTS
#   global/git-excludes          -> GIT_EXCLUDES                (lines merged, file never overwritten)
#   vendor/ecc/ECC-PIN.md        -> CLAUDE_HOME/ECC-PIN.md
#   scripts/legacy/ecc-drift.sh  -> BIN_DIR/ecc-drift.sh
#   tools/time-register.py       -> BIN_DIR/claude-time
#   tools/time_register/         -> BIN_DIR/time_register/      (the package claude-time imports; claude-metrics
#                                                                takes its prompt rule from it)
#   tools/claude-metrics.py      -> BIN_DIR/claude-metrics
#   tools/claude_metrics/        -> BIN_DIR/claude_metrics/     (the package claude-metrics imports)
#   tools/claude-pack.py         -> BIN_DIR/claude-pack         (optional: the packs library, ADR-007)
#   packs/<pack>/                -> CLAUDE_HOME/packs/<pack>/   (optional: one item per pack)
#   packs/.claude-plugin/marketplace.json, packs/catalog.json, packs/CATALOG.md
#                                -> CLAUDE_HOME/packs/...       (the generated catalog; required once packs/ is there)
#   hooks/<file>                 -> CLAUDE_HOME/hooks/<file>
#   skills/<group>/<name>/       -> CLAUDE_HOME/skills/<name>/
#   agents/<group>/<name>.md     -> CLAUDE_HOME/agents/<name>.md
#   rules/<group>/<name>.md      -> CLAUDE_HOME/rules/<name>.md
# Never managed: skills/graphify, skills/synced, plugins/ (Claude Code keeps its records of the catalog and of the
# packs there), state/ (claude-pack's journal packs.jsonl), ~/.claude.json, projects/, project files.
# Install state: CLAUDE_HOME/.setup-manifest.json (sha256 + mode of every managed file; the git ignore lines
# of the base, and the subset the base itself added to the live file: only those are ever removed again).

die() { echo "ERROR: $*" >&2; exit 1; }
warn() { echo "WARN: $*" >&2; }

SETUP_REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

: "${HOME:?HOME is not set}"
CLAUDE_HOME=${CLAUDE_HOME:-$HOME/.claude}
HOME_AGENTS=${HOME_AGENTS:-$HOME/AGENTS.md}
GIT_EXCLUDES=${GIT_EXCLUDES:-$HOME/.config/git/ignore}
BIN_DIR=${BIN_DIR:-$HOME/bin}
SNAPSHOT_ROOT=${SNAPSHOT_ROOT:-$HOME/claude-backups/setup-snapshots}

# Absolute paths without a trailing slash (restore.sh and the manifest store absolute paths).
# "." and ".." components are refused: they could climb out of a sandbox folder that does not exist yet.
abs_path() {
  local p=${1%/}
  [ -n "$p" ] || p=/
  while :; do case $p in ./*) p=${p#./} ;; *) break ;; esac; done
  case /$p/ in */../* | */./*) die "path must not contain . or .. components: $1" ;; esac
  case $p in /*) printf '%s\n' "$p" ;; *) printf '%s/%s\n' "$PWD" "$p" ;; esac
}
CLAUDE_HOME=$(abs_path "$CLAUDE_HOME") || exit 1
HOME_AGENTS=$(abs_path "$HOME_AGENTS") || exit 1
GIT_EXCLUDES=$(abs_path "$GIT_EXCLUDES") || exit 1
BIN_DIR=$(abs_path "$BIN_DIR") || exit 1
SNAPSHOT_ROOT=$(abs_path "$SNAPSHOT_ROOT") || exit 1

MANIFEST_KEY=CLAUDE_HOME/.setup-manifest.json
UNMANAGED_SKILLS="graphify synced"
JQ=$(command -v jq || true)
LOCK_HELD=""

need_jq() { [ -n "$JQ" ] || die "jq is required (macOS ships /usr/bin/jq)"; }
need_tools() {
  local t
  for t in "$@"; do command -v "$t" >/dev/null 2>&1 || die "required tool not found: $t"; done
}

# ---------- paths ----------

# key = ROOT or ROOT/rel, e.g. CLAUDE_HOME/hooks/bash-guard.sh, HOME_AGENTS, GIT_EXCLUDES
key_path() {
  local key=$1 root rel base
  root=${key%%/*}
  rel=""
  [ "$root" = "$key" ] || rel=${key#*/}
  case $root in
    CLAUDE_HOME) base=$CLAUDE_HOME ;;
    HOME_AGENTS) base=$HOME_AGENTS ;;
    GIT_EXCLUDES) base=$GIT_EXCLUDES ;;
    BIN_DIR) base=$BIN_DIR ;;
    *) die "unknown destination root in key: $key" ;;
  esac
  case $rel in */../* | ../* | */.. | ..) die "key escapes its root: $key" ;; esac
  if [ -n "$rel" ]; then printf '%s/%s\n' "$base" "$rel"; else printf '%s\n' "$base"; fi
}

# Physical path without requiring the path to exist: the nearest existing ancestor is resolved
# (symlinks included), the components below it are appended as they are.
canon() {
  local p=$1 rest=""
  while [ ! -d "$p" ]; do
    rest="/$(basename "$p")$rest"
    p=$(dirname "$p")
  done
  p=$(cd "$p" && pwd -P)
  [ "$p" != / ] || p=""
  printf '%s%s\n' "$p" "$rest"
}

lower() { printf '%s\n' "$1" | tr '[:upper:]' '[:lower:]'; }

# same_place <a> <b>: one location (compared case-insensitively like APFS, or the same existing inode)
same_place() {
  [ "$(lower "$(canon "$1")")" = "$(lower "$(canon "$2")")" ] && return 0
  [ -e "$1" ] && [ -e "$2" ] && [ "$(stat -f '%d:%i' "$1")" = "$(stat -f '%d:%i' "$2")" ]
}

# inside_place <path> <root>: path is root or below it (case-insensitive)
inside_place() {
  local a b
  a=$(lower "$(canon "$1")"); b=$(lower "$(canon "$2")")
  case "$a/" in "$b/"*) return 0 ;; esac
  same_place "$1" "$2"
}

# in_temp_area <path>: strictly below the system temp folders (where every sandbox must live)
in_temp_area() {
  case "$(canon "$1")/" in /private/tmp/?* | /private/var/folders/?*) return 0 ;; esac
  return 1
}

# The account's real home folder, even when HOME is overridden
real_home() {
  local h
  h=$(dscl . -read "/Users/$(id -un)" NFSHomeDirectory 2>/dev/null | awk '{print $2}') || true
  [ -n "$h" ] || h=$HOME
  printf '%s\n' "$h"
}

# live_count: how many of the four destinations are the real live locations (0..4)
live_count() {
  local h n=0
  h=$(real_home)
  if inside_place "$CLAUDE_HOME" "$h/.claude"; then n=$((n + 1)); fi
  if same_place "$HOME_AGENTS" "$h/AGENTS.md"; then n=$((n + 1)); fi
  if same_place "$GIT_EXCLUDES" "$h/.config/git/ignore"; then n=$((n + 1)); fi
  if same_place "$BIN_DIR" "$h/bin"; then n=$((n + 1)); fi
  echo "$n"
}

destinations_are_live() { [ "$(live_count)" = 4 ]; }

# Die unless every (non-live) destination sits in a system temp folder
assert_temp_destinations() {
  local d
  for d in "$CLAUDE_HOME" "$HOME_AGENTS" "$GIT_EXCLUDES" "$BIN_DIR"; do
    in_temp_area "$d" || die "sandbox destination $d is not under /private/tmp or /private/var/folders (\$TMPDIR): sandbox runs only write there"
  done
}

# Die when some destinations are live and some are not (a half-sandbox could write live files),
# and when a sandbox set points anywhere outside the temp folders (home folder, a project, this repo)
assert_not_mixed() {
  local n; n=$(live_count)
  [ "$n" = 0 ] || [ "$n" = 4 ] || die "destinations are mixed ($n of 4 live): set all of CLAUDE_HOME, HOME_AGENTS, GIT_EXCLUDES, BIN_DIR to sandbox paths, or none"
  [ "$n" = 4 ] || assert_temp_destinations
}

# Die unless every destination is outside the real live locations (sandbox/test runs)
assert_sandbox_destinations() {
  [ "$(live_count)" = 0 ] || die "$1 needs sandbox destinations: set CLAUDE_HOME, HOME_AGENTS, GIT_EXCLUDES and BIN_DIR to non-live paths"
  assert_temp_destinations
}

# Live destinations keep snapshots only in the default folder (a SNAPSHOT_ROOT left over from a sandbox
# test would put the only copy of the live state into a temp folder); sandbox destinations never use it.
assert_snapshot_root_ok() {
  local def
  def="$(real_home)/claude-backups/setup-snapshots"
  if destinations_are_live; then
    same_place "$SNAPSHOT_ROOT" "$def" ||
      die "SNAPSHOT_ROOT=$SNAPSHOT_ROOT but the destinations are live: sandbox variables missing? Live runs keep snapshots in $def (unset SNAPSHOT_ROOT)"
    return 0
  fi
  ! same_place "$SNAPSHOT_ROOT" "$def" ||
    die "sandbox destinations with the default SNAPSHOT_ROOT: set SNAPSHOT_ROOT to a sandbox folder (or use --sandbox)"
  in_temp_area "$SNAPSHOT_ROOT" ||
    die "sandbox SNAPSHOT_ROOT $SNAPSHOT_ROOT is not under /private/tmp or /private/var/folders (\$TMPDIR)"
}

# show_path <key>: short display form: ~/... for live destinations, the key itself for a sandbox
DEST_LIVE=""
show_path() {
  local p h
  if [ -z "$DEST_LIVE" ]; then if destinations_are_live; then DEST_LIVE=1; else DEST_LIVE=0; fi; fi
  if [ "$DEST_LIVE" = 1 ]; then
    p=$(key_path "$1"); h=$(real_home)
    case $p in "$h"/*) printf '%s/%s\n' "~" "${p#"$h"/}" ;; *) printf '%s\n' "$p" ;; esac
  else
    printf '%s\n' "$1"
  fi
}

describe_destinations() {
  if destinations_are_live; then echo "live (~/.claude, ~/AGENTS.md, ~/.config/git/ignore, ~/bin)"
  else echo "sandbox (CLAUDE_HOME=$CLAUDE_HOME)"; fi
}

# ---------- lock ----------

# The lock folder holds the owner's pid; a lock whose process is gone (crash, kill -9) is taken over.
take_lock() {
  local l="$CLAUDE_HOME/.setup-lock" pid
  mkdir -p "$CLAUDE_HOME"
  if ! mkdir "$l" 2>/dev/null; then
    pid=$(cat "$l/pid" 2>/dev/null || true)
    case $pid in
      "" | *[!0-9]*) die "another install/rollback holds $l (if none is running: rm -f \"$l/pid\"; rmdir \"$l\")" ;;
    esac
    if kill -0 "$pid" 2>/dev/null; then die "another install/rollback (pid $pid) holds $l"; fi
    warn "taking over the stale lock $l (pid $pid is not running)"
  fi
  echo "$$" >"$l/pid"
  LOCK_HELD=$l
}
release_lock() {
  if [ -n "$LOCK_HELD" ]; then
    rm -f "$LOCK_HELD/pid"
    rmdir "$LOCK_HELD" 2>/dev/null || true
    LOCK_HELD=""
  fi
}

# ---------- file facts ----------

sha_of() { shasum -a 256 <"$1" | cut -c1-64; }
mode_of() { stat -f '%Lp' "$1"; }

# jq skips a byte order mark and NUL bytes after the value. JSON allows neither, so here such a file is invalid
json_sha() {
  local out
  if [ "$(head -c 3 "$1")" != $'\xef\xbb\xbf' ] && LC_ALL=C tr -d '\000' <"$1" | cmp -s - "$1" &&
    out=$("$JQ" -S -c . <"$1" 2>/dev/null) && [ -n "$out" ]; then
    printf '%s\n' "$out" | shasum -a 256 | cut -c1-64
  else
    echo invalid-json
  fi
}

# Mode policy for an installed file (git keeps only the exec bit, so modes are decided here)
policy_mode() {
  local key=$1 exec=$2
  case $key in
    CLAUDE_HOME/hooks/*) if [ "$exec" = 1 ]; then echo 700; else echo 600; fi ;;
    CLAUDE_HOME/CLAUDE.md | CLAUDE_HOME/settings.json | "$MANIFEST_KEY") echo 600 ;;
    *) if [ "$exec" = 1 ]; then echo 755; else echo 644; fi ;;
  esac
}

is_exec() { if [ -x "$1" ]; then echo 1; else echo 0; fi; }

# ---------- managed list (from the repo layout) ----------

valid_name() { case $1 in "" | .* | *[!A-Za-z0-9._-]*) return 1 ;; *) return 0 ;; esac; }

regular_file_or_die() {
  if [ ! -f "$1" ] || [ -L "$1" ]; then die "$2 must be a regular file"; fi
}

# managed_items <tree>: one line per item: phase TAB kind TAB src(rel to tree) TAB key
# kinds: file, dir (whole folder), merge (line merge), json (validated, written last)
# phases: 1 hooks, 2 agents, 3 skills, 4 rules, 5 docs, 6 git excludes, 7 bin, 8 packs and their catalog, 9 settings,
# (10 retired items, set by install.sh: retired hooks and packs go only after settings.json no longer names them)
PACK_CATALOG_FILES=".claude-plugin/marketplace.json catalog.json CATALOG.md"
managed_items() {
  local t=$1 f n g names="" dup
  for f in global/CLAUDE.global.md global/settings.json global/home-agents.md global/git-excludes \
    vendor/ecc/ECC-PIN.md scripts/legacy/ecc-drift.sh tools/time-register.py tools/claude-metrics.py; do
    regular_file_or_die "$t/$f" "$f"
  done
  if [ -d "$t/hooks" ]; then
    for f in "$t"/hooks/*; do
      [ -e "$f" ] || [ -L "$f" ] || continue
      n=$(basename "$f")
      valid_name "$n" || die "bad hook file name: hooks/$n"
      regular_file_or_die "$f" "hooks/$n"
      printf '1\tfile\thooks/%s\tCLAUDE_HOME/hooks/%s\n' "$n" "$n"
    done
  fi
  for g in "$t"/agents/*/; do
    [ -d "$g" ] || continue
    g=$(basename "$g")
    for f in "$t/agents/$g"/*.md; do
      [ -e "$f" ] || [ -L "$f" ] || continue
      n=$(basename "$f" .md)
      valid_name "$n" || die "bad agent file name: agents/$g/$n.md"
      regular_file_or_die "$f" "agents/$g/$n.md"
      case " $names " in *" agent:$n "*) die "agent name used twice: $n" ;; esac
      names="$names agent:$n"
      printf '2\tfile\tagents/%s/%s.md\tCLAUDE_HOME/agents/%s.md\n' "$g" "$n" "$n"
    done
  done
  for g in "$t"/skills/*/; do
    [ -d "$g" ] || continue
    g=$(basename "$g")
    for f in "$t/skills/$g"/*/; do
      [ -d "$f" ] || continue
      n=$(basename "$f")
      valid_name "$n" || die "bad skill folder name: skills/$g/$n"
      [ ! -L "$t/skills/$g/$n" ] || die "skills/$g/$n must not be a symlink"
      [ -f "$t/skills/$g/$n/SKILL.md" ] || die "skills/$g/$n has no SKILL.md"
      for dup in $UNMANAGED_SKILLS; do
        [ "$n" != "$dup" ] || die "skills/$g/$n: name '$n' is reserved for an unmanaged live skill"
      done
      case " $names " in *" skill:$n "*) die "skill name used twice: $n" ;; esac
      names="$names skill:$n"
      [ -z "$(find "$t/skills/$g/$n" -type l -print -quit)" ] || die "skills/$g/$n contains a symlink"
      printf '3\tdir\tskills/%s/%s\tCLAUDE_HOME/skills/%s\n' "$g" "$n" "$n"
    done
  done
  for g in "$t"/rules/*/; do
    [ -d "$g" ] || continue
    g=$(basename "$g")
    for f in "$t/rules/$g"/*.md; do
      [ -e "$f" ] || [ -L "$f" ] || continue
      n=$(basename "$f" .md)
      valid_name "$n" || die "bad rule file name: rules/$g/$n.md"
      regular_file_or_die "$f" "rules/$g/$n.md"
      case " $names " in *" rule:$n "*) die "rule name used twice: $n" ;; esac
      names="$names rule:$n"
      printf '4\tfile\trules/%s/%s.md\tCLAUDE_HOME/rules/%s.md\n' "$g" "$n" "$n"
    done
  done
  printf '5\tfile\tglobal/CLAUDE.global.md\tCLAUDE_HOME/CLAUDE.md\n'
  printf '5\tfile\tvendor/ecc/ECC-PIN.md\tCLAUDE_HOME/ECC-PIN.md\n'
  printf '5\tfile\tglobal/home-agents.md\tHOME_AGENTS\n'
  printf '6\tmerge\tglobal/git-excludes\tGIT_EXCLUDES\n'
  # optional, so this lib.sh still installs (rolls back to) tags made before a package existed (claude_metrics:
  # v2026.10.17 and older, time_register: v2026.10.23 and older); verify.sh requires both in the tree under test.
  # Before the commands: a new command that imports its package never runs without it
  for n in claude_metrics time_register; do
    if [ -e "$t/tools/$n" ] || [ -L "$t/tools/$n" ]; then
      if [ ! -d "$t/tools/$n" ] || [ -L "$t/tools/$n" ]; then die "tools/$n must be a folder"; fi
      [ -z "$(find "$t/tools/$n" -type l -print -quit)" ] || die "tools/$n contains a symlink"
      printf '7\tdir\ttools/%s\tBIN_DIR/%s\n' "$n" "$n"
    fi
  done
  printf '7\tfile\tscripts/legacy/ecc-drift.sh\tBIN_DIR/ecc-drift.sh\n'
  printf '7\tfile\ttools/time-register.py\tBIN_DIR/claude-time\n'
  printf '7\tfile\ttools/claude-metrics.py\tBIN_DIR/claude-metrics\n'
  # the packs library (ADR-007), all of it optional: tags up to v2026.11.32 and the public tree have none, and this
  # lib.sh still installs them (rolls back to them). One dir item per pack, so a pack that comes or goes is a plan
  # item of its own; the generated catalog as file items. Phase 8: in place before settings.json names the catalog,
  # retired only after it no longer does
  if [ -e "$t/tools/claude-pack.py" ] || [ -L "$t/tools/claude-pack.py" ]; then
    regular_file_or_die "$t/tools/claude-pack.py" tools/claude-pack.py
    printf '7\tfile\ttools/claude-pack.py\tBIN_DIR/claude-pack\n'
  fi
  if [ -e "$t/packs" ] || [ -L "$t/packs" ]; then
    if [ ! -d "$t/packs" ] || [ -L "$t/packs" ]; then die "packs must be a folder"; fi
    for f in "$t"/packs/*/; do
      [ -d "$f" ] || continue
      n=$(basename "$f")
      valid_name "$n" || die "bad pack folder name: packs/$n"
      [ ! -L "$t/packs/$n" ] || die "packs/$n must not be a symlink"
      regular_file_or_die "$t/packs/$n/.claude-plugin/plugin.json" "packs/$n/.claude-plugin/plugin.json"
      [ -z "$(find "$t/packs/$n" -type l -print -quit)" ] || die "packs/$n contains a symlink"
      printf '8\tdir\tpacks/%s\tCLAUDE_HOME/packs/%s\n' "$n" "$n"
    done
    for f in $PACK_CATALOG_FILES; do
      regular_file_or_die "$t/packs/$f" "packs/$f"
      printf '8\tfile\tpacks/%s\tCLAUDE_HOME/packs/%s\n' "$f" "$f"
    done
  fi
  printf '9\tjson\tglobal/settings.json\tCLAUDE_HOME/settings.json\n'
}

# ---------- state lines: key TAB sha256 TAB mode TAB json_sha256|- ----------

# State of the tree copy of one item, with policy modes (what live must look like after install)
tree_state() {
  local tree=$1 kind=$2 src=$3 key=$4 p f rel js
  p="$tree/$src"
  case $kind in
    file | json)
      js=-
      if [ "$kind" = json ]; then js=$(json_sha "$p"); fi
      printf '%s\t%s\t%s\t%s\n' "$key" "$(sha_of "$p")" "$(policy_mode "$key" "$(is_exec "$p")")" "$js" ;;
    dir)
      while IFS= read -r -d '' f; do
        rel=${f#"$p"/}
        printf '%s\t%s\t%s\t-\n' "$key/$rel" "$(sha_of "$f")" "$(policy_mode "$key/$rel" "$(is_exec "$f")")"
      done < <(find "$p" -type f ! -name .DS_Store -print0) ;;
    merge) ;;
  esac
}

# State of the live copy of one item (missing files print nothing; symlinks print sha "symlink")
live_state() {
  local kind=$1 key=$2 p f rel js
  p=$(key_path "$key")
  case $kind in
    file | json | meta)
      if [ -L "$p" ]; then
        printf '%s\tsymlink\t-\t-\n' "$key"
      elif [ -f "$p" ]; then
        js=-
        if [ "$kind" = json ]; then js=$(json_sha "$p"); fi
        printf '%s\t%s\t%s\t%s\n' "$key" "$(sha_of "$p")" "$(mode_of "$p")" "$js"
      elif [ -e "$p" ]; then
        printf '%s\tnot-a-file\t-\t-\n' "$key"
      fi ;;
    dir)
      if [ -L "$p" ]; then
        printf '%s\tsymlink\t-\t-\n' "$key"
      elif [ -d "$p" ]; then
        while IFS= read -r -d '' f; do
          rel=${f#"$p"/}
          if [ -L "$f" ]; then
            printf '%s\tsymlink\t-\t-\n' "$key/$rel"
          else
            printf '%s\t%s\t%s\t-\n' "$key/$rel" "$(sha_of "$f")" "$(mode_of "$f")"
          fi
        done < <(find "$p" \( -type f -o -type l \) ! -name .DS_Store -print0)
      elif [ -e "$p" ]; then
        printf '%s\tnot-a-dir\t-\t-\n' "$key"
      fi ;;
    merge) ;;
  esac
}

# Lines of a state file that belong to one item, as "key TAB compare-value TAB mode", sorted.
# settings.json compares as normalized JSON (jq -S -c .): key order and spacing are not content; the rest as bytes
item_block() {
  local file=$1 kind=$2 key=$3
  awk -F'\t' -v k="$key" -v kind="$kind" '
    (kind == "dir" ? (index($1, k "/") == 1 || $1 == k) : $1 == k) {
      v = $2; if (kind == "json" && $4 != "-" && $4 != "") v = $4
      print $1 "\t" v "\t" $3
    }' "$file" | LC_ALL=C sort
}

# compare_blocks <expected> <actual>: print "reason TAB key" for every difference
compare_blocks() {
  awk -F'\t' '
    FILENAME == ARGV[1] { e[$1] = $2; em[$1] = $3; next }
    { a[$1] = $2; am[$1] = $3 }
    END {
      for (k in e) {
        if (!(k in a)) print "missing\t" k
        else if (a[k] == "symlink" || a[k] == "not-a-file" || a[k] == "not-a-dir") print a[k] "\t" k
        else if (e[k] != a[k]) print "changed\t" k
        else if (em[k] != am[k]) print "mode " am[k] " (want " em[k] ")\t" k
      }
      for (k in a) if (!(k in e)) print ((a[k] == "symlink" || a[k] ~ /^not-a-/) ? a[k] : "extra") "\t" k
    }' "$1" "$2" | LC_ALL=C sort -t "$(printf '\t')" -k2
}

# ---------- git excludes: merge lines, never overwrite ----------

has_line() { grep -Fxq -- "$1" "$2" 2>/dev/null; }

# merge_excludes <current|""> <source> <retired-lines-file> <out>: writes the merged file to <out>.
# Keeps every current line (user/app lines included) in place, except retired base lines, then
# appends source lines that are missing. A missing current file becomes a byte copy of the source.
merge_excludes() {
  local cur=$1 src=$2 retired=$3 out=$4 line
  if [ -z "$cur" ] || [ ! -f "$cur" ]; then cp "$src" "$out"; return 0; fi
  : >"$out"
  while IFS= read -r line || [ -n "$line" ]; do
    if [ -n "$line" ] && has_line "$line" "$retired" && ! has_line "$line" "$src"; then continue; fi
    printf '%s\n' "$line" >>"$out"
  done <"$cur"
  while IFS= read -r line || [ -n "$line" ]; do
    [ -n "$line" ] || continue
    has_line "$line" "$out" || printf '%s\n' "$line" >>"$out"
  done <"$src"
  # keep the original bytes when nothing changed (e.g. a file without a final newline)
  if [ "$(cat "$out")" = "$(cat "$cur")" ]; then cp "$cur" "$out"; fi
}

# Source lines that are missing from a file (blank lines ignored)
missing_lines() {
  local lines=$1 file=$2 line
  while IFS= read -r line || [ -n "$line" ]; do
    [ -n "$line" ] || continue
    has_line "$line" "$file" || printf '%s\n' "$line"
  done <"$lines"
}

# owned_lines <prev-manifest|""> <key> <source> <live-file>: "key TAB line" for the base lines the base itself
# added to the live file: lines it owned before that are still in the source, plus source lines missing live
# now (this install adds them). A line that was in the live file before the base wrote it (a user or app line,
# e.g. every line present when step A7 recorded the baseline) is never owned, so no tag ever removes it.
owned_lines() {
  local man=$1 key=$2 src=$3 live=$4 line
  {
    if [ -n "$man" ]; then
      manifest_owned "$man" "$key" | while IFS= read -r line; do
        if [ -n "$line" ] && has_line "$line" "$src"; then printf '%s\n' "$line"; fi
      done
    fi
    if [ -f "$live" ]; then missing_lines "$src" "$live"; else awk 'length($0) > 0' "$src"; fi
  } | awk -v k="$key" '!seen[$0]++ {print k "\t" $0}'
}

# ---------- manifest ----------

manifest_path() { key_path "$MANIFEST_KEY"; }

# manifest_ok <file>: 0 when it is a manifest this code understands
manifest_ok() { "$JQ" -e '.schema == 1 and (.items | type == "array") and (.files | type == "object")' "$1" >/dev/null 2>&1; }

# kind TAB key TAB src
manifest_items() { "$JQ" -r '.items[] | [.kind, .key, (.src // "-")] | @tsv' "$1"; }
# key TAB sha TAB mode TAB json_sha|-
manifest_files() { "$JQ" -r '.files | to_entries[] | [.key, .value.sha256, .value.mode, (.value.json_sha256 // "-")] | @tsv' "$1"; }
manifest_lines() { "$JQ" -r --arg k "$2" '.merge_lines[$k][]?' "$1"; }
# Lines the base added itself (only these are ever removed); manifests without merge_owned own nothing
manifest_owned() { "$JQ" -r --arg k "$2" '.merge_owned[$k][]?' "$1"; }
manifest_field() { "$JQ" -r --arg f "$2" '.[$f] // "-"' "$1"; }

# write_manifest <out> <ref> <commit> <how> <items.tsv(phase kind src key)> <state.tsv> <lines.tsv(key TAB line)>
#                <owned.tsv(key TAB line)>
write_manifest() {
  local out=$1 ref=$2 commit=$3 how=$4 items=$5 state=$6 lines=$7 owned=$8
  "$JQ" -n --arg ref "$ref" --arg commit "$commit" --arg how "$how" --arg repo "$SETUP_REPO" \
    --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg ch "$CLAUDE_HOME" --arg ha "$HOME_AGENTS" --arg ge "$GIT_EXCLUDES" --arg bd "$BIN_DIR" \
    --rawfile items "$items" --rawfile state "$state" --rawfile lines "$lines" --rawfile owned "$owned" '
    def rows($s): $s | split("\n") | map(select(length > 0) | split("\t"));
    def bykey($s): rows($s) | group_by(.[0]) | map({key: .[0][0], value: map(.[1:] | join("\t"))}) | from_entries;
    {
      schema: 1, ref: $ref, commit: (if $commit == "" then null else $commit end),
      installed_at: $at, how: $how, repo: $repo,
      roots: {CLAUDE_HOME: $ch, HOME_AGENTS: $ha, GIT_EXCLUDES: $ge, BIN_DIR: $bd},
      items: (rows($items) | map({kind: .[1], key: .[3], src: .[2]})),
      files: (rows($state) | map({key: .[0], value: ({sha256: .[1], mode: .[2]}
                + (if .[3] != "-" then {json_sha256: .[3]} else {} end))}) | from_entries),
      merge_lines: bykey($lines),
      merge_owned: bykey($owned)
    }' >"$out"
}

# Same install content (ignores installed_at and how): 0 when equal
manifests_equal() {
  [ "$("$JQ" -S -c 'del(.installed_at, .how)' "$1")" = "$("$JQ" -S -c 'del(.installed_at, .how)' "$2")" ]
}

# drift_scan <manifest> <out>: "reason TAB key" for every live difference from the manifest.
# settings.json is compared as normalized JSON; git excludes only need their managed lines.
drift_scan() {
  local man=$1 out=$2 w kind key p
  w=$(mktemp -d "${TMPDIR:-/tmp}/setup-drift.XXXXXX")
  : >"$out"
  manifest_files "$man" >"$w/files"
  while IFS=$'\t' read -r kind key _; do
    case $kind in
      merge)
        p=$(key_path "$key")
        manifest_lines "$man" "$key" >"$w/lines"
        if [ ! -f "$p" ]; then
          if [ -s "$w/lines" ]; then printf 'missing\t%s\n' "$key" >>"$out"; fi
        else
          missing_lines "$w/lines" "$p" | while IFS= read -r line; do
            printf 'missing line "%s"\t%s\n' "$line" "$key"
          done >>"$out"
        fi ;;
      *)
        item_block "$w/files" "$kind" "$key" >"$w/exp"
        live_state "$kind" "$key" >"$w/live.raw"
        item_block "$w/live.raw" "$kind" "$key" >"$w/live"
        compare_blocks "$w/exp" "$w/live" >>"$out" ;;
    esac
  done < <(manifest_items "$man")
  rm -rf -- "$w"
}

# ---------- copies that never delete live content ----------

# displace_move <path> <key> <dir>: move a live item into <dir>/<key>
displace_move() {
  local p=$1 key=$2 dir=$3
  mkdir -p "$(dirname "$dir/$key")"
  if [ -e "$dir/$key" ] || [ -L "$dir/$key" ]; then
    mv "$p" "$dir/$key.$(date +%s).$$"
  else
    mv "$p" "$dir/$key"
  fi
}
# displace_copy <path> <key> <dir>: copy a live file into <dir>/<key> (the first copy wins)
displace_copy() {
  local p=$1 key=$2 dir=$3
  mkdir -p "$(dirname "$dir/$key")"
  [ -e "$dir/$key" ] || [ -L "$dir/$key" ] || cp -pRPX "$p" "$dir/$key"
}

# install_file <src> <dest> <mode> <key> <displaced-dir>: atomic rename over the old file;
# the old file is copied (a folder or symlink in its place is moved) to <displaced-dir> first.
install_file() {
  local src=$1 dest=$2 mode=$3 key=$4 dsp=$5 tmp
  mkdir -p "$(dirname "$dest")"
  tmp="$(dirname "$dest")/.$(basename "$dest").setup-tmp.$$"
  cp -X "$src" "$tmp"
  chmod "$mode" "$tmp"
  if [ -d "$dest" ] && [ ! -L "$dest" ]; then
    displace_move "$dest" "$key" "$dsp"
  elif [ -e "$dest" ] || [ -L "$dest" ]; then
    displace_copy "$dest" "$key" "$dsp"
  fi
  mv -f "$tmp" "$dest"
}

# install_dir <src-dir> <dest> <key> <displaced-dir>: the new copy is built in CLAUDE_HOME/.setup-staging,
# the old folder is moved (not deleted) to <displaced-dir>, then the new one is renamed in.
install_dir() {
  local src=$1 dest=$2 key=$3 dsp=$4 stg tmp f
  stg="$CLAUDE_HOME/.setup-staging"
  mkdir -p "$stg" "$(dirname "$dest")"
  tmp=$(mktemp -d "$stg/item.XXXXXX")
  cp -pRX "$src/." "$tmp/"
  find "$tmp" -type d -exec chmod 755 {} +
  while IFS= read -r -d '' f; do
    chmod "$(policy_mode "$key/${f#"$tmp"/}" "$(is_exec "$f")")" "$f"
  done < <(find "$tmp" -type f -print0)
  if [ -e "$dest" ] || [ -L "$dest" ]; then displace_move "$dest" "$key" "$dsp"; fi
  mv "$tmp" "$dest"
  rmdir "$stg" 2>/dev/null || true
}

# ---------- snapshots ----------

# snapshot_list <items.tsv(phase kind src key)|""> <manifest|"">: unique "kind TAB key" lines for
# every item the new tree or the current manifest manages, plus the manifest itself (meta)
snapshot_list() {
  {
    if [ -n "$1" ]; then awk -F'\t' '{print $2 "\t" $4}' "$1"; fi
    if [ -n "$2" ]; then manifest_items "$2" | awk -F'\t' '{print $1 "\t" $2}'; fi
  } | awk -F'\t' '!seen[$2]++'
  printf 'meta\t%s\n' "$MANIFEST_KEY"
}

# make_snapshot <list(kind TAB key)> <label>: copy every listed live item that exists into
# SNAPSHOT_ROOT/<ts>-<label>/files/<key>, write items.tsv + restore.sh + info.txt, print the folder.
make_snapshot() {
  local list=$1 label=$2 ts dir kind key p present n=0
  [ -f "$SETUP_REPO/scripts/snapshot-restore.sh" ] || die "missing scripts/snapshot-restore.sh"
  label=$(printf '%s' "$label" | tr -c 'A-Za-z0-9._-' '-')
  ts=$(date +%Y%m%d-%H%M%S)
  mkdir -p "$SNAPSHOT_ROOT"
  chmod 700 "$SNAPSHOT_ROOT" 2>/dev/null || true
  dir="$SNAPSHOT_ROOT/$ts-$label"
  while ! mkdir "$dir" 2>/dev/null; do n=$((n + 1)); dir="$SNAPSHOT_ROOT/$ts-$label-$n"; done
  chmod 700 "$dir"
  mkdir -p "$dir/files"
  printf '# kind\tkey\tpath\tpresent\n' >"$dir/items.tsv"
  while IFS=$'\t' read -r kind key; do
    [ -n "$key" ] || continue
    p=$(key_path "$key")
    present=0
    if [ -e "$p" ] || [ -L "$p" ]; then
      mkdir -p "$(dirname "$dir/files/$key")"
      cp -pRPX "$p" "$dir/files/$key"
      if [ -d "$p" ] && [ ! -L "$p" ]; then
        diff -r -q "$p" "$dir/files/$key" >/dev/null || die "snapshot copy differs: $p"
      elif [ -f "$p" ] && [ ! -L "$p" ]; then
        cmp -s "$p" "$dir/files/$key" || die "snapshot copy differs: $p"
      fi
      present=1
    fi
    printf '%s\t%s\t%s\t%s\n' "$kind" "$key" "$p" "$present" >>"$dir/items.tsv"
  done <"$list"
  cp "$SETUP_REPO/scripts/snapshot-restore.sh" "$dir/restore.sh"
  chmod 700 "$dir/restore.sh"
  {
    echo "created: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "label: $label"
    echo "repo: $SETUP_REPO"
    echo "destinations: $(describe_destinations)"
    if [ -f "$(manifest_path)" ]; then echo "live ref at snapshot: $("$JQ" -r '.ref // "?"' "$(manifest_path)" 2>/dev/null)"; fi
    echo "restore (dry run): bash \"$dir/restore.sh\""
    echo "restore (apply):   bash \"$dir/restore.sh\" --apply"
    echo "or:                bash \"$SETUP_REPO/scripts/rollback.sh\" --to-snapshot \"$dir\""
  } >"$dir/info.txt"
  printf '%s\n' "$dir"
}

# ---------- hook tests ----------

# run_hook_tests <hooks-dir> <log> [<stage>]: 0 when test-all.sh passes (or does not exist). Its exit code alone is not
# enough: test-all.sh pipes secret-tests.sh through grep, which hides that suite's exit code. So: exit 0, no
# FAIL line, all three "ALL OK"/"EXTRA OK" lines, "DUP OK" when this test-all.sh runs dup-tests.sh (from
# v2026.10.9), "DOCS OK" when it runs doc-tests.sh (from v2026.10.33), "HINT OK" when it runs hint-tests.sh (from
# v2026.10.34), "DIRS OK" when it runs dirs-tests.sh (from v2026.10.36), "SYNC OK" when it runs
# docs-sync-tests.sh (from v2026.11.14) and "NODE OK" when it runs node-std-tests.sh (from v2026.11.19). Not "when the
# suite exists": a rollback to an older tag retires it only after the hook tests. <stage> (install.sh): the staged
# tree of the tag, given to the tests as SETUP_STAGE: they run after the hooks step, before the skills of the tag are
# in place, and node-std-tests.sh takes the skill new-project from there (v2026.11.19 stopped on this, exit 5).
run_hook_tests() {
  local h=$1 log=$2 stage=${3:-} n
  if [ ! -f "$h/test-all.sh" ]; then echo "no test-all.sh" >"$log"; return 0; fi
  SETUP_STAGE=$stage bash "$h/test-all.sh" >"$log" 2>&1 || return 1
  if grep -q '^FAIL' "$log"; then return 1; fi
  n=$(grep -cE '^(ALL|EXTRA) OK$' "$log" 2>/dev/null) || true
  [ "${n:-0}" -ge 3 ] || return 1
  { ! grep -q 'dup-tests\.sh' "$h/test-all.sh" || grep -qx 'DUP OK' "$log"; } &&
    { ! grep -q 'doc-tests\.sh' "$h/test-all.sh" || grep -qx 'DOCS OK' "$log"; } &&
    { ! grep -q 'hint-tests\.sh' "$h/test-all.sh" || grep -qx 'HINT OK' "$log"; } &&
    { ! grep -q 'dirs-tests\.sh' "$h/test-all.sh" || grep -qx 'DIRS OK' "$log"; } &&
    { ! grep -q 'docs-sync-tests\.sh' "$h/test-all.sh" || grep -qx 'SYNC OK' "$log"; } &&
    { ! grep -q 'node-std-tests\.sh' "$h/test-all.sh" || grep -qx 'NODE OK' "$log"; }
}
