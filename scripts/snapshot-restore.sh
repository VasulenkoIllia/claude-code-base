#!/bin/bash
# restore.sh: put the managed paths back exactly as they were when this snapshot was taken.
# This file is copied into every snapshot by scripts/snapshot.sh / install.sh and works on its own
# (no repo needed). It only touches the paths listed in items.tsv next to it.
#
#   bash restore.sh           dry run: print the plan, change nothing
#   bash restore.sh --apply   restore, then compare every restored path with the snapshot (MATCH/DIFF)
#
# Nothing is deleted: every live file or folder it replaces or removes is moved/copied into
# <snapshot>/displaced-<time>/ first. ~/.config/git/ignore is merged, never overwritten: lines that
# appeared after the snapshot are kept unless the base added them itself (manifest merge_owned; install.sh
# adds the lines of a failed install through RESTORE_EXTRA_LINES, a "key TAB line" file).
# Order: items that existed at snapshot time, then settings.json, then removal of items that did not
# exist then (a hook that settings.json names is never missing while it still names it), then the manifest.
set -euo pipefail

SNAP=$(cd "$(dirname "$0")" && pwd)
ITEMS="$SNAP/items.tsv"
APPLY=0
case "${1:-}" in
  "") ;;
  --apply) APPLY=1 ;;
  -h | --help) sed -n '2,14p' "$0"; exit 0 ;;
  *) echo "unknown argument: $1 (use --apply or nothing)" >&2; exit 2 ;;
esac
[ -f "$ITEMS" ] || { echo "ERROR: $ITEMS not found" >&2; exit 1; }
JQ=$(command -v jq || true)

has_line() { grep -Fxq -- "$1" "$2" 2>/dev/null; }
mode_of() { stat -f '%Lp' "$1"; }

# same <a> <b>: identical content and identical modes (files and folders)
same() {
  local a=$1 b=$2 f
  if [ -L "$a" ] || [ -L "$b" ]; then
    [ -L "$a" ] && [ -L "$b" ] && [ "$(readlink "$a")" = "$(readlink "$b")" ]; return
  fi
  if [ -d "$a" ]; then
    [ -d "$b" ] || return 1
    diff -r -q "$a" "$b" >/dev/null 2>&1 || return 1
    while IFS= read -r -d '' f; do
      [ "$(mode_of "$a/$f")" = "$(mode_of "$b/$f")" ] || return 1
    done < <(cd "$a" && find . -print0)
    return 0
  fi
  [ -f "$a" ] && [ -f "$b" ] && cmp -s "$a" "$b" && [ "$(mode_of "$a")" = "$(mode_of "$b")" ]
}

# Lines in <key> that the base added itself, per the current install manifest (merge_owned; an older
# manifest without it: merge_lines), plus RESTORE_EXTRA_LINES. Empty without jq/manifest.
managed_lines() {
  local key=$1
  if [ -n "${RESTORE_EXTRA_LINES:-}" ] && [ -f "$RESTORE_EXTRA_LINES" ]; then
    awk -F'\t' -v k="$key" '$1 == k {sub(/^[^\t]*\t/, ""); print}' "$RESTORE_EXTRA_LINES"
  fi
  [ -n "$JQ" ] && [ -n "$MAN_LIVE" ] && [ -f "$MAN_LIVE" ] || return 0
  # shellcheck disable=SC2016  # jq program
  "$JQ" -r --arg k "$key" 'if has("merge_owned") then .merge_owned[$k][]? else .merge_lines[$k][]? end' "$MAN_LIVE" 2>/dev/null || true
}

# merged_excludes <snapshot-copy|""> <current|""> <key> <out>:
# snapshot content + current lines that are neither in the snapshot nor managed by the base
merged_excludes() {
  local snapf=$1 cur=$2 key=$3 out=$4 line
  managed_lines "$key" >"$WORK/managed"
  if [ -n "$snapf" ]; then cp "$snapf" "$out"; else : >"$out"; fi
  [ -n "$cur" ] && [ -f "$cur" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    [ -n "$line" ] || continue
    has_line "$line" "$out" && continue
    has_line "$line" "$WORK/managed" && continue
    if [ -s "$out" ] && [ "$(tail -c 1 "$out" | od -An -c | tr -d ' ')" != '\n' ]; then printf '\n' >>"$out"; fi
    printf '%s\n' "$line" >>"$out"
  done <"$cur"
}

WORK=$(mktemp -d "${TMPDIR:-/tmp}/setup-restore.XXXXXX")
trap 'rm -rf -- "$WORK"' EXIT
DSP="$SNAP/displaced-$(date +%Y%m%d-%H%M%S)"
MAN_LIVE=""

# Order: items present at snapshot time, settings.json (json), items absent then (removed), the manifest (meta)
{
  awk -F'\t' '!/^#/ && $1 != "json" && $1 != "meta" && $4 == 1' "$ITEMS"
  awk -F'\t' '!/^#/ && $1 == "json"' "$ITEMS"
  awk -F'\t' '!/^#/ && $1 != "json" && $1 != "meta" && $4 != 1' "$ITEMS"
  awk -F'\t' '!/^#/ && $1 == "meta"' "$ITEMS"
} >"$WORK/order"
MAN_LIVE=$(awk -F'\t' '$1 == "meta" {print $3; exit}' "$WORK/order")

# 1. Check the snapshot is complete before touching anything
while IFS=$'\t' read -r kind key path present; do
  if [ "$present" = 1 ] && [ ! -e "$SNAP/files/$key" ] && [ ! -L "$SNAP/files/$key" ]; then
    echo "ERROR: snapshot copy missing for $key ($SNAP/files/$key)" >&2; exit 1
  fi
  case $path in /*) ;; *) echo "ERROR: path in items.tsv is not absolute: $path" >&2; exit 1 ;; esac
  : "$kind"
done <"$WORK/order"

# 2. Plan / apply
changes=0
while IFS=$'\t' read -r kind key path present; do
  copy="$SNAP/files/$key"
  if [ "$kind" = merge ]; then
    if [ "$present" = 1 ]; then merged_excludes "$copy" "$path" "$key" "$WORK/merged"
    else merged_excludes "" "$path" "$key" "$WORK/merged"; fi
    if [ -f "$path" ] && cmp -s "$WORK/merged" "$path"; then echo "same      $path"; continue; fi
    if [ "$present" = 0 ] && [ ! -s "$WORK/merged" ]; then
      [ -e "$path" ] || { echo "same      $path (absent)"; continue; }
      echo "remove    $path (did not exist at snapshot time; moved to displaced)"
    else
      echo "merge     $path (snapshot lines + lines added since that the base does not manage)"
    fi
    changes=$((changes + 1))
    [ "$APPLY" = 1 ] || continue
    mkdir -p "$(dirname "$DSP/$key")"
    if [ "$present" = 0 ] && [ ! -s "$WORK/merged" ]; then mv "$path" "$DSP/$key"; continue; fi
    [ ! -e "$path" ] || cp -pX "$path" "$DSP/$key"
    mkdir -p "$(dirname "$path")"
    tmp="$(dirname "$path")/.$(basename "$path").restore-tmp.$$"
    if [ "$present" = 1 ] && cmp -s "$WORK/merged" "$copy"; then
      cp -pX "$copy" "$tmp"   # nothing to keep from later: the snapshot file itself (mode and mtime too)
    else
      cp "$WORK/merged" "$tmp"
      if [ -e "$path" ]; then chmod "$(mode_of "$path")" "$tmp"; elif [ "$present" = 1 ]; then chmod "$(mode_of "$copy")" "$tmp"; fi
    fi
    mv -f "$tmp" "$path"
    continue
  fi
  if [ "$present" = 1 ]; then
    if { [ -e "$path" ] || [ -L "$path" ]; } && same "$copy" "$path"; then echo "same      $path"; continue; fi
    if [ -e "$path" ] || [ -L "$path" ]; then echo "restore   $path"; else echo "recreate  $path"; fi
  else
    [ -e "$path" ] || [ -L "$path" ] || { echo "same      $path (absent)"; continue; }
    echo "remove    $path (did not exist at snapshot time; moved to displaced)"
  fi
  changes=$((changes + 1))
  [ "$APPLY" = 1 ] || continue
  mkdir -p "$(dirname "$DSP/$key")"
  if [ "$present" = 0 ]; then mv "$path" "$DSP/$key"; continue; fi
  mkdir -p "$(dirname "$path")"
  if [ -d "$copy" ] && [ ! -L "$copy" ]; then
    tmp="$(dirname "$path")/.$(basename "$path").restore-tmp.$$"
    cp -pRPX "$copy" "$tmp"
    if [ -e "$path" ] || [ -L "$path" ]; then mv "$path" "$DSP/$key"; fi
    mv "$tmp" "$path"
  else
    tmp="$(dirname "$path")/.$(basename "$path").restore-tmp.$$"
    cp -pRPX "$copy" "$tmp"
    if [ -e "$path" ] || [ -L "$path" ]; then cp -pRPX "$path" "$DSP/$key"; fi
    if [ -d "$path" ] && [ ! -L "$path" ]; then mv "$path" "$DSP/$key.dir"; fi
    mv -f "$tmp" "$path"
  fi
done <"$WORK/order"

if [ "$APPLY" = 0 ]; then
  echo "dry run: $changes change(s) planned; nothing written. Apply: bash \"$0\" --apply"
  exit 0
fi

# 3. Verify: every path equals the snapshot again
bad=0
while IFS=$'\t' read -r kind key path present; do
  copy="$SNAP/files/$key"
  if [ "$kind" = merge ]; then
    ok=1
    if [ "$present" = 1 ]; then
      while IFS= read -r line || [ -n "$line" ]; do
        [ -n "$line" ] || continue
        has_line "$line" "$path" || ok=0
      done <"$copy"
      if [ "$ok" = 1 ] && cmp -s "$copy" "$path"; then echo "MATCH  $path"
      elif [ "$ok" = 1 ]; then echo "MATCH  $path (snapshot lines present; later non-base lines kept)"
      else echo "DIFF   $path"; bad=1; fi
    else
      echo "MATCH  $path (kept only lines the base does not manage)"
    fi
    continue
  fi
  if [ "$present" = 1 ]; then
    if same "$copy" "$path"; then echo "MATCH  $path"; else echo "DIFF   $path"; bad=1; fi
  else
    if [ -e "$path" ] || [ -L "$path" ]; then echo "DIFF   $path (should be absent)"; bad=1; else echo "MATCH  $path (absent)"; fi
  fi
done <"$WORK/order"
if [ -d "$DSP" ]; then echo "replaced live items were moved to: $DSP"; fi
if [ "$bad" = 0 ]; then echo "restore: OK, $changes change(s)"; else echo "restore: DIFF found" >&2; exit 1; fi
