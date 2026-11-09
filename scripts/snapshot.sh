#!/bin/bash
# snapshot.sh: copy every managed live path into SNAPSHOT_ROOT/<time>-<label>/ with a restore script.
#
#   bash scripts/snapshot.sh [label]             take a snapshot (default label: manual)
#   bash scripts/snapshot.sh --dry-run [label]   list what would be copied; write nothing
#
# Managed paths = the items in ~/.claude/.setup-manifest.json, plus the items the repo working tree manages
# (so a snapshot taken before an install also records what that install would add), plus the manifest itself.
# SNAPSHOT_ROOT defaults to ~/claude-backups/setup-snapshots (folders 700). A snapshot holds files/<key> (modes
# kept), items.tsv, info.txt and restore.sh. Restore: bash <dir>/restore.sh (dry run), then --apply;
# or bash scripts/rollback.sh --to-snapshot <dir>. Live paths are only read.
# Destinations: CLAUDE_HOME, HOME_AGENTS, GIT_EXCLUDES, BIN_DIR, SNAPSHOT_ROOT (see scripts/lib.sh).
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$HERE/lib.sh"

DRY=0; LABEL=manual
while [ $# -gt 0 ]; do
  case $1 in
    --dry-run) DRY=1 ;;
    -h | --help) sed -n '2,12p' "$0"; exit 0 ;;
    -*) echo "snapshot.sh: unknown option: $1" >&2; exit 2 ;;
    *) LABEL=$1 ;;
  esac
  shift
done

need_jq
assert_not_mixed
assert_snapshot_root_ok
W=$(mktemp -d "${TMPDIR:-/tmp}/setup-snapshot.XXXXXX")
trap 'case $W in */setup-snapshot.*) rm -rf -- "$W" ;; esac' EXIT

MAN=$(manifest_path)
PREV=""
if [ -e "$MAN" ]; then
  if manifest_ok "$MAN"; then PREV=$MAN; else warn "unreadable manifest $MAN: it is copied, but its items are not used"; fi
fi
if ! (managed_items "$SETUP_REPO" >"$W/items.tsv") 2>"$W/err"; then
  warn "the repo layout could not be read ($(tr '\n' ' ' <"$W/err")); using the manifest items only"
  : >"$W/items.tsv"
fi
snapshot_list "$W/items.tsv" "$PREV" >"$W/list"
[ "$(wc -l <"$W/list" | tr -d ' ')" -gt 1 ] || die "no managed items found (no manifest and no repo layout)"
if [ -d "$CLAUDE_HOME/.setup-lock" ]; then warn "an install or rollback may be running ($CLAUDE_HOME/.setup-lock exists)"; fi

if [ "$DRY" = 1 ]; then
  echo "dry run: a snapshot would copy these paths into $SNAPSHOT_ROOT/<time>-$LABEL/ (nothing written)"
  while IFS=$'\t' read -r kind key; do
    p=$(key_path "$key")
    if [ -e "$p" ] || [ -L "$p" ]; then st=copy; else st=absent; fi
    printf '  %-6s %-5s %s\n' "$st" "$kind" "$(show_path "$key")"
  done <"$W/list"
  exit 0
fi

DIR=$(make_snapshot "$W/list" "$LABEL")
present=$(awk -F'\t' '!/^#/ && $4 == 1' "$DIR/items.tsv" | wc -l | tr -d ' ')
absent=$(awk -F'\t' '!/^#/ && $4 == 0' "$DIR/items.tsv" | wc -l | tr -d ' ')
echo "snapshot: $DIR"
echo "  $present path(s) copied, $absent recorded as absent (a restore moves them away if they appear later)"
echo "  restore (dry run): bash \"$DIR/restore.sh\""
echo "  restore (apply):   bash \"$DIR/restore.sh\" --apply"
