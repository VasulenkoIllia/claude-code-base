#!/bin/bash
# rollback.sh: put the managed live paths back to an earlier state.
#
#   bash scripts/rollback.sh <tag> [--dry-run]                reinstall an earlier tag: install.sh with a snapshot first
#   bash scripts/rollback.sh --to-snapshot <dir> [--dry-run]  restore from a snapshot folder (install.sh or snapshot.sh)
#                                                            (--snapshot <dir> means the same)
# <tag> is an emergency path, so it runs install.sh with --force-drift (drifted live files are listed and kept in
# the snapshot, not a reason to stop) and --verify-advisory (verify failures of the old tag under newer tools only
# warn; the hook tests after the hooks step still stop it). If it still fails, use the newest pre-install snapshot:
#   bash ~/claude-backups/setup-snapshots/<time>-pre-install-<tag>/restore.sh [--apply]
# --to-snapshot prints the plan (restore.sh dry run), takes a fresh snapshot of the current state so the rollback
# itself can be undone, then runs <dir>/restore.sh --apply, which checks every restored path (MATCH/DIFF).
# Nothing is deleted: replaced live items are moved into the snapshot folders. Git ignore lines are merged.
# Destinations: CLAUDE_HOME, HOME_AGENTS, GIT_EXCLUDES, BIN_DIR, SNAPSHOT_ROOT (see scripts/lib.sh).
# Afterwards restart open Claude sessions (Desktop and CLI).
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$HERE/lib.sh"

usage() { sed -n '2,16p' "$0"; }

SNAPDIR=""; DRY=0; TAG=""; PASS=()
while [ $# -gt 0 ]; do
  case $1 in
    --to-snapshot | --snapshot) [ $# -ge 2 ] || { echo "rollback.sh: $1 needs a folder" >&2; exit 2; }; SNAPDIR=$2; shift ;;
    --dry-run) DRY=1; PASS+=("$1") ;;
    -h | --help) usage; exit 0 ;;
    --label | --ref | --record-only) echo "rollback.sh: $1 is not a rollback option" >&2; exit 2 ;;
    -*) PASS+=("$1") ;;
    *) [ -z "$TAG" ] || { echo "rollback.sh: two tags given: $TAG and $1" >&2; exit 2; }; TAG=$1 ;;
  esac
  shift
done

# ---------- rollback to a tag = install of that tag ----------
if [ -z "$SNAPDIR" ]; then
  [ -n "$TAG" ] || { usage >&2; exit 2; }
  exec bash "$HERE/install.sh" "$TAG" --label "rollback-to-$TAG" --force-drift --verify-advisory ${PASS[@]+"${PASS[@]}"}
fi

# ---------- rollback to a snapshot folder ----------
[ -z "$TAG" ] || { echo "rollback.sh: give a tag or --to-snapshot, not both" >&2; exit 2; }
for o in ${PASS[@]+"${PASS[@]}"}; do
  [ "$o" = --dry-run ] || { echo "rollback.sh: $o does not apply to --to-snapshot" >&2; exit 2; }
done
[ -d "$SNAPDIR" ] || die "not a folder: $SNAPDIR"
SNAPDIR=$(cd "$SNAPDIR" && pwd)
[ -f "$SNAPDIR/items.tsv" ] && [ -f "$SNAPDIR/restore.sh" ] && [ -d "$SNAPDIR/files" ] ||
  die "$SNAPDIR is not a setup snapshot (needs items.tsv, restore.sh, files/)"
need_jq
assert_not_mixed

W=$(mktemp -d "${TMPDIR:-/tmp}/setup-rollback.XXXXXX")
cleanup() { release_lock; case $W in */setup-rollback.*) rm -rf -- "$W" ;; esac; }
trap cleanup EXIT

# The snapshot must belong to these destinations (a sandbox snapshot never restores into live, and back)
awk -F'\t' '!/^#/ && NF >= 4' "$SNAPDIR/items.tsv" >"$W/snap-items"
while IFS=$'\t' read -r kind key path _; do
  [ "$(key_path "$key")" = "$path" ] || die "snapshot path $path ($kind) is not where $key points now ($(key_path "$key")); wrong destinations?"
done <"$W/snap-items"

MAN=$(manifest_path)
: >"$W/extras"
if [ -f "$MAN" ] && manifest_ok "$MAN"; then
  manifest_items "$MAN" | awk -F'\t' 'NR == FNR {s[$2] = 1; next} !($2 in s) {print $2}' "$W/snap-items" - >"$W/extras"
fi

echo "rollback to snapshot: $SNAPDIR"
[ ! -f "$SNAPDIR/info.txt" ] || sed -n '1,4p' "$SNAPDIR/info.txt" | sed 's/^/  /'
echo "plan (restore.sh dry run):"
bash "$SNAPDIR/restore.sh" | sed 's/^/  /'
if [ -s "$W/extras" ]; then
  echo "managed now but unknown to this snapshot (left as they are; use rollback.sh <tag> to retire them):"
  while IFS= read -r key; do echo "  $(show_path "$key")"; done <"$W/extras"
fi
if [ "$DRY" = 1 ]; then echo "dry run: nothing written"; exit 0; fi

assert_snapshot_root_ok
take_lock
{
  awk -F'\t' '{print $1 "\t" $2}' "$W/snap-items"
  if [ -f "$MAN" ] && manifest_ok "$MAN"; then manifest_items "$MAN" | awk -F'\t' '{print $1 "\t" $2}'; fi
  printf 'meta\t%s\n' "$MANIFEST_KEY"
} | awk -F'\t' '!seen[$2]++' >"$W/list"
PRE=$(make_snapshot "$W/list" "pre-rollback")
echo "snapshot of the current state: $PRE"
bash "$SNAPDIR/restore.sh" --apply | sed 's/^/  /'
release_lock

if [ -f "$MAN" ] && manifest_ok "$MAN"; then
  drift_scan "$MAN" "$W/final"
  echo "live = $(manifest_field "$MAN" ref), drift $(wc -l <"$W/final" | tr -d ' ')"
  while IFS=$'\t' read -r reason key; do printf '  %-24s %s\n' "$reason" "$(show_path "$key")"; done <"$W/final"
else
  echo "live = no install manifest (the state before the first recorded install)"
fi
echo "undo this rollback: bash \"$HERE/rollback.sh\" --to-snapshot \"$PRE\""
if destinations_are_live; then echo "next: restart open Claude sessions (Desktop and CLI)"; fi
