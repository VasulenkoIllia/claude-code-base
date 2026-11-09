#!/bin/bash
# install.sh: install one tagged release of this base into the live paths (plan 4.6, 4.7).
#
#   bash scripts/install.sh <tag> --dry-run      verify gates, drift check and the change plan; writes nothing
#   bash scripts/install.sh <tag>                snapshot, install, write ~/.claude/.setup-manifest.json
#   bash scripts/install.sh <tag> --record-only  only write the manifest, after checking live == tag (step A7)
#
# Options:
#   --ref <ref>       same as the positional tag. WORKTREE = the working tree (tracked + untracked, not ignored)
#   --allow-untagged  accept WORKTREE or a commit that is not a tag; refused unless all destinations are sandbox
#   --sandbox         all destinations must be non-live; no snapshot (replaced files go to CLAUDE_HOME/.setup-replaced/)
#   --skip-verify     do not run scripts/verify.sh on the staged tree (only with --sandbox)
#   --force-drift     continue although managed live files changed since the last install, or a new base item
#                     would replace an unmanaged live item of the same name (they go to the snapshot). Not needed for
#                     a live settings.json with the JSON and mode of <tag>: that is no drift, and it is not rewritten
#   --verify-advisory verify failures only warn (rollback.sh only: an older tag must stay installable after a
#                     ShellCheck or gitleaks upgrade); the hook tests after the hooks step still stop the install
#   --label <text>    snapshot label (rollback.sh passes rollback-to-<tag>)
# Destinations: CLAUDE_HOME, HOME_AGENTS, GIT_EXCLUDES, BIN_DIR, SNAPSHOT_ROOT (see scripts/lib.sh).
#
# Only managed items are touched (scripts/lib.sh, managed_items). Nothing is deleted: every replaced or retired
# live item is moved or copied into <snapshot>/replaced/. ~/.config/git/ignore is merged line by line, never
# overwritten; only lines the base added itself are ever removed. Order: hooks (then test-all.sh), agents,
# skills, rules, docs, git ignore, bin, settings.json, retired items, then the manifest. If anything fails after the
# snapshot, the snapshot is restored automatically (its restore.sh); the manifest keeps the previous tag.
# Exit: 0 ok | 1 error (live restored from the snapshot when writes had started) | 2 usage
#       3 drift or live != ref (nothing written) | 4 verify failed (nothing written)
#       5 hook tests failed after the hooks step (previous hooks put back, nothing else written)
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$HERE/lib.sh"

usage() { sed -n '2,28p' "$0"; }
usage_die() { echo "install.sh: $*" >&2; echo "help: bash scripts/install.sh --help" >&2; exit 2; }

REF=""; DRY=0; RECORD=0; SANDBOX=0; UNTAGGED=0; SKIP_VERIFY=0; FORCE_DRIFT=0; LABEL=""; VERIFY_ADVISORY=0
set_ref() {
  case $1 in "" | -*) usage_die "bad ref: '$1'" ;; esac
  [ -z "$REF" ] || [ "$REF" = "$1" ] || usage_die "two refs given: $REF and $1"
  REF=$1
}
while [ $# -gt 0 ]; do
  case $1 in
    --dry-run) DRY=1 ;;
    --record-only) RECORD=1 ;;
    --sandbox) SANDBOX=1 ;;
    --allow-untagged) UNTAGGED=1 ;;
    --skip-verify) SKIP_VERIFY=1 ;;
    --force-drift) FORCE_DRIFT=1 ;;
    --verify-advisory) VERIFY_ADVISORY=1 ;;
    --ref) [ $# -ge 2 ] || usage_die "--ref needs a value"; set_ref "$2"; shift ;;
    --ref=*) set_ref "${1#--ref=}" ;;
    --label) [ $# -ge 2 ] || usage_die "--label needs a value"; LABEL=$2; shift ;;
    -h | --help) usage; exit 0 ;;
    -*) usage_die "unknown option: $1" ;;
    *) set_ref "$1" ;;
  esac
  shift
done
[ -n "$REF" ] || usage_die "which tag? e.g. bash scripts/install.sh v2026.10.0 --dry-run"
[ "$REF" != WORKTREE ] || [ "$UNTAGGED" = 1 ] || usage_die "--ref WORKTREE needs --allow-untagged"
[ "$SKIP_VERIFY" = 0 ] || [ "$SANDBOX" = 1 ] || usage_die "--skip-verify is only allowed with --sandbox"
case $VERIFY_ADVISORY:$LABEL in 0:* | 1:rollback-to-*) ;; *) usage_die "--verify-advisory is only for rollback.sh" ;; esac

need_jq
need_tools git tar shasum
assert_not_mixed
[ "$UNTAGGED" = 0 ] || assert_sandbox_destinations "--allow-untagged"
[ "$SANDBOX" = 0 ] || assert_sandbox_destinations "--sandbox"
[ "$SANDBOX" = 1 ] || assert_snapshot_root_ok

WORK=$(mktemp -d "${TMPDIR:-/tmp}/setup-install.XXXXXX")
APPLYING=0; SNAP=""; DSP=""
# On any exit while live files are being written (an error, set -e, a signal), put the snapshot back.
cleanup() {
  local rc=$?
  if [ "$APPLYING" = 1 ]; then
    APPLYING=0
    if [ -n "$SNAP" ] && [ -f "$SNAP/restore.sh" ]; then
      echo "install: failed while applying (exit $rc); restoring the snapshot $SNAP" >&2
      # lines this install added to the git ignore count as base lines, so the restore drops them again
      if RESTORE_EXTRA_LINES="$WORK/owned.tsv" bash "$SNAP/restore.sh" --apply >&2 </dev/null; then
        echo "install: live is back to the state before this install; the manifest still records ${PREV_REF:-nothing}" >&2
      else
        echo "AUTO-RESTORE FAILED. Run in Terminal: bash \"$SNAP/restore.sh\" --apply" >&2
      fi
    else
      echo "install: failed while applying (sandbox run, no snapshot); replaced files are in ${DSP:-?}" >&2
    fi
  fi
  release_lock
  case $WORK in */setup-install.*) rm -rf -- "$WORK" ;; esac
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP
STAGE="$WORK/stage"
mkdir "$STAGE"

# ---------- 1. stage the ref ----------
COMMIT=""
if [ "$REF" = WORKTREE ]; then
  [ "$(git -C "$SETUP_REPO" rev-parse --show-toplevel 2>/dev/null)" = "$SETUP_REPO" ] || die "$SETUP_REPO is not a git worktree"
  (
    cd "$SETUP_REPO"
    git ls-files -z -co --exclude-standard |
      while IFS= read -r -d '' f; do if [ -e "$f" ] || [ -L "$f" ]; then printf '%s\0' "$f"; fi; done |
      tar -cf - --null -T -
  ) | tar -xpf - -C "$STAGE"
  REF_DESC="WORKTREE (working tree of the repo, uncommitted)"
else
  if git -C "$SETUP_REPO" rev-parse -q --verify "refs/tags/$REF" >/dev/null 2>&1; then
    COMMIT=$(git -C "$SETUP_REPO" rev-parse -q --verify "refs/tags/$REF^{commit}")
  else
    [ "$UNTAGGED" = 1 ] || die "$REF is not a tag: install.sh installs tags only (sandbox tests: --allow-untagged)"
    COMMIT=$(git -C "$SETUP_REPO" rev-parse -q --verify "$REF^{commit}" 2>/dev/null) || die "unknown ref: $REF"
  fi
  git -C "$SETUP_REPO" archive --format=tar "$COMMIT" | tar -xpf - -C "$STAGE"
  REF_DESC="$REF (commit ${COMMIT:0:12})"
fi
echo "ref:          $REF_DESC"
echo "destinations: $(describe_destinations)"

# ---------- 2. verify gates on the staged tree ----------
if [ "$SKIP_VERIFY" = 1 ]; then
  echo "verify:       skipped (--skip-verify, sandbox only)"
else
  V=""
  if [ -f "$STAGE/scripts/verify.sh" ]; then V="$STAGE/scripts/verify.sh"
  elif [ -f "$SETUP_REPO/scripts/verify.sh" ]; then V="$SETUP_REPO/scripts/verify.sh"; fi
  VRC=0
  if [ -z "$V" ]; then
    warn "no scripts/verify.sh in $REF or in the repo: verify gates not run"
  elif bash "$V" "$STAGE" >"$WORK/verify.log" 2>&1 </dev/null; then
    echo "verify:       OK ($(tail -n 1 "$WORK/verify.log"))"
  else
    VRC=$?
  fi
  if [ "$VRC" != 0 ]; then
    cat "$WORK/verify.log" >&2
    if [ "$VRC" = 2 ]; then what="could not run (a required tool is missing, see above)"; else what="failed"; fi
    if [ "$VERIFY_ADVISORY" = 1 ]; then
      warn "verify $what on $REF_DESC; continuing because this is a rollback (--verify-advisory)."
      warn "this tag passed verify when it was released; the hook tests after the hooks step still apply"
    else
      echo "install: verify $what on $REF_DESC; nothing was written" >&2
      exit 4
    fi
  fi
fi

# ---------- 3. managed items, expected state ----------
managed_items "$STAGE" >"$WORK/items.tsv"
# invalid-json on both sides would compare as equal, so this ref must not give that value
[ "$(json_sha "$STAGE/global/settings.json")" != invalid-json ] && "$JQ" -e 'type == "object"' "$STAGE/global/settings.json" >/dev/null 2>&1 ||
  die "global/settings.json in $REF is not a JSON object"

MAN=$(manifest_path)
PREV=""; PREV_REF=""
if [ -e "$MAN" ] || [ -L "$MAN" ]; then
  manifest_ok "$MAN" || die "cannot read $MAN (not a schema-1 manifest); move it aside first"
  PREV=$MAN
  PREV_REF=$(manifest_field "$MAN" ref)
fi

: >"$WORK/expected.tsv"
: >"$WORK/lines.tsv"
: >"$WORK/owned.tsv"
while IFS=$'\t' read -r _ kind src key; do
  if [ "$kind" = merge ]; then
    p=$(key_path "$key")
    [ ! -L "$p" ] || die "$p is a symlink: the git ignore merge only writes regular files"
    awk -v k="$key" 'length($0) > 0 {print k "\t" $0}' "$STAGE/$src" >>"$WORK/lines.tsv"
    owned_lines "$PREV" "$key" "$STAGE/$src" "$p" >>"$WORK/owned.tsv"
  else
    tree_state "$STAGE" "$kind" "$src" "$key" >>"$WORK/expected.tsv"
  fi
done <"$WORK/items.tsv"

# live_vs_ref all|existing [items.tsv]: differences between live and the staged ref ("reason TAB key").
# existing = only items that exist live, and "missing" files or lines do not count (install only adds them).
live_vs_ref() {
  local how=$1 items=${2:-$WORK/items.tsv} kind src key p
  while IFS=$'\t' read -r _ kind src key; do
    p=$(key_path "$key")
    if [ "$kind" = merge ]; then
      if [ ! -f "$p" ]; then
        if [ "$how" = all ]; then printf 'missing\t%s\n' "$key"; fi
      elif [ "$how" = all ]; then
        missing_lines "$STAGE/$src" "$p" | while IFS= read -r line; do printf 'missing line "%s"\t%s\n' "$line" "$key"; done
      fi
      continue
    fi
    item_block "$WORK/expected.tsv" "$kind" "$key" >"$WORK/e"
    live_state "$kind" "$key" >"$WORK/l.raw"
    item_block "$WORK/l.raw" "$kind" "$key" >"$WORK/l"
    if [ "$how" = existing ]; then
      [ -s "$WORK/l" ] || continue
      compare_blocks "$WORK/e" "$WORK/l" | awk -F'\t' '$1 != "missing"'
    else
      compare_blocks "$WORK/e" "$WORK/l"
    fi
  done <"$items"
}

# json_sha of live settings.json now ("absent" when there is none): an app write during the install is caught
SETTINGS_KEY=CLAUDE_HOME/settings.json
live_settings_sha() {
  local p; p=$(key_path "$SETTINGS_KEY")
  if [ -f "$p" ]; then json_sha "$p"; else echo absent; fi
}
SETTINGS_SHA0=$(live_settings_sha)

# Live settings.json has the JSON and the mode of this ref. Positive check: no line on either side is not a match
settings_match_ref() {
  item_block "$WORK/expected.tsv" json "$SETTINGS_KEY" >"$WORK/e"
  live_state json "$SETTINGS_KEY" >"$WORK/l.raw"
  item_block "$WORK/l.raw" json "$SETTINGS_KEY" >"$WORK/l"
  [ -s "$WORK/e" ] && cmp -s "$WORK/e" "$WORK/l"
}

# ---------- 4. drift ----------
if [ "$RECORD" = 1 ]; then
  live_vs_ref all >"$WORK/drift.tsv"
elif [ -n "$PREV" ]; then
  drift_scan "$PREV" "$WORK/drift.tsv"
  # The app or CLI changed settings.json and this ref has the same content: installing it loses nothing, so no drift.
  # Owner's decision 31.10: only this file and only "changed"; every other path and reason still stops
  if has_line "$(printf 'changed\t%s' "$SETTINGS_KEY")" "$WORK/drift.tsv" && settings_match_ref; then
    awk -F'\t' -v k="$SETTINGS_KEY" '!($1 == "changed" && $2 == k)' "$WORK/drift.tsv" >"$WORK/drift.kept"
    mv "$WORK/drift.kept" "$WORK/drift.tsv"
    echo "settings.json changed since the last install ($PREV_REF), same content as $REF: not drift, not rewritten"
  fi
  # items new in this ref whose name an unmanaged live item already uses (e.g. an own skill): never silently replaced
  manifest_items "$PREV" | cut -f2 >"$WORK/prev-keys"
  awk -F'\t' 'FILENAME == ARGV[1] {k[$1] = 1; next} !($4 in k)' "$WORK/prev-keys" "$WORK/items.tsv" >"$WORK/items-new.tsv"
  live_vs_ref existing "$WORK/items-new.tsv" | awk -F'\t' '{print "unmanaged, taken over: " $1 "\t" $2}' >>"$WORK/drift.tsv"
else
  live_vs_ref existing >"$WORK/drift.tsv"
fi
DRIFT=0
if [ -s "$WORK/drift.tsv" ]; then
  DRIFT=1
  n=$(wc -l <"$WORK/drift.tsv" | tr -d ' ')
  if [ "$RECORD" = 1 ]; then echo "live != $REF: $n difference(s) (record-only needs live == ref):"
  elif [ -n "$PREV" ]; then echo "drift: $n live path(s) changed since the last install ($PREV_REF) or about to be taken over:"
  else echo "no install manifest yet, and $n live path(s) differ from $REF:"; fi
  while IFS=$'\t' read -r reason key; do printf '  %-24s %s\n' "$reason" "$(show_path "$key")"; done <"$WORK/drift.tsv"
fi

HOW=install
[ "$RECORD" = 0 ] || HOW=record-only
[ "$SANDBOX" = 0 ] || HOW="$HOW --sandbox"
write_manifest "$WORK/manifest.new" "$REF" "$COMMIT" "$HOW" "$WORK/items.tsv" "$WORK/expected.tsv" "$WORK/lines.tsv" \
  "$WORK/owned.tsv"
MAN_WRITE=1
if [ -n "$PREV" ] && manifests_equal "$PREV" "$WORK/manifest.new"; then MAN_WRITE=0; fi

DSP=""
start_writes() {
  take_lock
  if [ "$SANDBOX" = 1 ]; then
    DSP="$CLAUDE_HOME/.setup-replaced/$(date +%Y%m%d-%H%M%S)-$$"
    echo "snapshot:     none (--sandbox); replaced files go to $DSP"
  else
    SNAP=$(make_snapshot "$1" "$2")
    DSP="$SNAP/replaced"
    echo "snapshot:     $SNAP"
  fi
}

final_report() {
  local n
  drift_scan "$MAN" "$WORK/final.tsv"
  n=$(wc -l <"$WORK/final.tsv" | tr -d ' ')
  echo "live = $REF, drift $n"
  if [ "$n" != 0 ]; then
    while IFS=$'\t' read -r reason key; do printf '  %-24s %s\n' "$reason" "$(show_path "$key")"; done <"$WORK/final.tsv"
    return 1
  fi
}

# ---------- record-only: just the manifest ----------
if [ "$RECORD" = 1 ]; then
  if [ "$DRIFT" = 1 ]; then echo "record-only: refused, nothing written" >&2; exit 3; fi
  echo "live == $REF: every managed file matches (content and mode), all git ignore lines present"
  if [ "$MAN_WRITE" = 0 ]; then echo "manifest already records $REF; nothing to write"; final_report; exit 0; fi
  if [ "$DRY" = 1 ]; then echo "dry run: would write $MAN (ref $REF); nothing written"; exit 0; fi
  if [ -n "$PREV" ]; then
    printf 'meta\t%s\n' "$MANIFEST_KEY" >"$WORK/snap.list"
    start_writes "$WORK/snap.list" "${LABEL:-pre-record-$REF}"
  else
    take_lock
    DSP="$CLAUDE_HOME/.setup-replaced/unused"
  fi
  install_file "$WORK/manifest.new" "$MAN" 600 "$MANIFEST_KEY" "$DSP"
  echo "wrote $MAN"
  final_report
  exit 0
fi

# ---------- 5. plan ----------
# retired items: in the last manifest, not in this ref. Phase 10 = after settings.json (phase 9), so a retired
# hook file is only moved away once settings.json no longer names it.
: >"$WORK/retired.tsv"
if [ -n "$PREV" ]; then
  manifest_items "$PREV" |
    awk -F'\t' 'FILENAME == ARGV[1] {have[$4] = 1; next} !($2 in have) {print "10\t" $1 "\t" $3 "\t" $2}' "$WORK/items.tsv" - \
      >"$WORK/retired.tsv"
fi

item_status() {
  local kind=$1 key=$2 p n
  p=$(key_path "$key")
  if [ ! -e "$p" ] && [ ! -L "$p" ]; then printf 'new\t\n'; return 0; fi
  item_block "$WORK/expected.tsv" "$kind" "$key" >"$WORK/e"
  live_state "$kind" "$key" >"$WORK/l.raw"
  item_block "$WORK/l.raw" "$kind" "$key" >"$WORK/l"
  compare_blocks "$WORK/e" "$WORK/l" >"$WORK/c"
  if [ ! -s "$WORK/c" ]; then printf 'same\t\n'; return 0; fi
  n=$(wc -l <"$WORK/c" | tr -d ' ')
  if grep -qv '^mode ' "$WORK/c"; then printf 'update\t%s file(s) differ\n' "$n"; else printf 'mode\t%s file mode(s)\n' "$n"; fi
}

: >"$WORK/plan.tsv"
i=0
while IFS=$'\t' read -r phase kind src key; do
  i=$((i + 1))
  p=$(key_path "$key")
  if [ "$phase" = 10 ]; then
    if [ -e "$p" ] || [ -L "$p" ]; then printf '%s\t%s\t%s\t%s\tretire\tno longer in %s\n' "$phase" "$kind" "$src" "$key" "$REF"; fi
    continue
  fi
  if [ "$kind" = merge ]; then
    # retired lines: only lines the base added itself (merge_owned) and this ref no longer has
    : >"$WORK/retired-lines.$i"
    if [ -n "$PREV" ]; then
      manifest_owned "$PREV" "$key" | while IFS= read -r line; do
        has_line "$line" "$STAGE/$src" || printf '%s\n' "$line"
      done >"$WORK/retired-lines.$i"
    fi
    cur=""
    [ ! -f "$p" ] || cur=$p
    merge_excludes "$cur" "$STAGE/$src" "$WORK/retired-lines.$i" "$WORK/merged.$i"
    if [ -n "$cur" ] && cmp -s "$WORK/merged.$i" "$cur"; then
      printf '%s\t%s\t%s\t%s\tsame\t%s\n' "$phase" "$kind" "$src" "$key" "$i"
    else
      add=0; ret=0
      if [ -z "$cur" ]; then add=$(awk 'length($0) > 0' "$STAGE/$src" | wc -l | tr -d ' ')
      else add=$(missing_lines "$STAGE/$src" "$cur" | wc -l | tr -d ' '); fi
      [ -z "$cur" ] || ret=$(awk 'NR == FNR {if (length($0)) r[$0] = 1; next} ($0 in r)' "$WORK/retired-lines.$i" "$cur" | wc -l | tr -d ' ')
      if [ -z "$cur" ]; then st=new; else st=merge; fi
      printf '%s\t%s\t%s\t%s\t%s\t%s\t+%s line(s), -%s retired line(s), other lines kept\n' \
        "$phase" "$kind" "$src" "$key" "$st" "$i" "$add" "$ret"
    fi
    continue
  fi
  IFS=$'\t' read -r st detail < <(item_status "$kind" "$key")
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$phase" "$kind" "$src" "$key" "$st" "$detail"
done < <(cat "$WORK/items.tsv" "$WORK/retired.tsv" | LC_ALL=C sort -t "$(printf '\t')" -k1,1n -s) >"$WORK/plan.tsv"

CHANGES=$(awk -F'\t' '$5 != "same"' "$WORK/plan.tsv" | wc -l | tr -d ' ')
SAME=$(awk -F'\t' '$5 == "same"' "$WORK/plan.tsv" | wc -l | tr -d ' ')
echo "plan:         $CHANGES item(s) to change, $SAME unchanged"
while IFS=$'\t' read -r _ kind _ key st x y; do
  [ "$st" != same ] || continue
  if [ "$kind" = merge ]; then x=$y; fi
  if [ -n "$x" ]; then printf '  %-7s %s  (%s)\n' "$st" "$(show_path "$key")" "$x"
  else printf '  %-7s %s\n' "$st" "$(show_path "$key")"; fi
done <"$WORK/plan.tsv"
if [ "$MAN_WRITE" = 1 ]; then printf '  %-7s %s  (ref %s)\n' manifest "$(show_path "$MANIFEST_KEY")" "$REF"; fi

if [ "$DRY" = 1 ]; then
  if [ "$DRIFT" = 1 ] && [ "$FORCE_DRIFT" = 0 ]; then
    echo "dry run: nothing written; a real run would stop on the drift above (exit 3) unless --force-drift"
    exit 3
  fi
  echo "dry run: nothing written"
  exit 0
fi
if [ "$DRIFT" = 1 ] && [ "$FORCE_DRIFT" = 0 ]; then
  echo "install: stopped, nothing written. Live files differ from what the base last installed." >&2
  if grep -q '^unmanaged, taken over' "$WORK/drift.tsv"; then
    echo "  'unmanaged, taken over': an own live item has the name of a new base item. Rename yours first," >&2
    echo "  or rerun with --force-drift (yours is then kept in the snapshot under replaced/)." >&2
  fi
  case $LABEL in
    rollback-to-*) ;;
    *)
      if grep -qv '^unmanaged, taken over' "$WORK/drift.tsv"; then
        echo "  Keep intended live edits: bash scripts/import-live.sh --dry-run, then import, review, commit, tag, install." >&2
      fi ;;
  esac
  echo "  Drop them: rerun with --force-drift (the changed files are kept in the snapshot)." >&2
  exit 3
fi
[ "$DRIFT" = 0 ] || warn "--force-drift: the drifted live files above are replaced; copies stay in the snapshot"
if [ "$CHANGES" = 0 ] && [ "$MAN_WRITE" = 0 ]; then
  echo "nothing to do"
  final_report
  exit 0
fi

# ---------- 6. snapshot, then apply ----------
snapshot_list "$WORK/items.tsv" "$PREV" >"$WORK/snap.list"
start_writes "$WORK/snap.list" "${LABEL:-pre-install-$REF}"
APPLYING=1   # from here on, any failure restores the snapshot (cleanup)

apply_item() {
  local kind=$1 src=$2 key=$3 st=$4 x=$5 p tmp
  p=$(key_path "$key")
  case $st in
    same) return 0 ;;
    retire) displace_move "$p" "$key" "$DSP" ;;
    *)
      case $kind in
        file) install_file "$STAGE/$src" "$p" "$(policy_mode "$key" "$(is_exec "$STAGE/$src")")" "$key" "$DSP" ;;
        json)
          "$JQ" -e 'type == "object"' "$STAGE/$src" >/dev/null || die "$src is not valid JSON"
          if [ "$(live_settings_sha)" != "$SETTINGS_SHA0" ]; then
            # the app (or someone) wrote settings.json after the drift check: keep that version, stop, restore
            mkdir -p "$DSP/CLAUDE_HOME"
            if [ -e "$p" ]; then cp -pX "$p" "$DSP/CLAUDE_HOME/settings.json.changed-during-install"; fi
            die "settings.json changed while installing (the app wrote it?). That version is kept at $DSP/CLAUDE_HOME/settings.json.changed-during-install; run the install again"
          fi
          install_file "$STAGE/$src" "$p" "$(policy_mode "$key" 0)" "$key" "$DSP" ;;
        dir) install_dir "$STAGE/$src" "$p" "$key" "$DSP" ;;
        merge)
          # merge again from the file as it is now: keeps a line the app added since the plan
          if [ -f "$p" ]; then merge_excludes "$p" "$STAGE/$src" "$WORK/retired-lines.$x" "$WORK/merged.$x"; fi
          mkdir -p "$(dirname "$p")"
          tmp="$(dirname "$p")/.$(basename "$p").setup-tmp.$$"
          cp "$WORK/merged.$x" "$tmp"
          if [ -f "$p" ]; then chmod "$(mode_of "$p")" "$tmp"; displace_copy "$p" "$key" "$DSP"; else chmod 644 "$tmp"; fi
          mv -f "$tmp" "$p" ;;
      esac ;;
  esac
  printf '  %-7s %s\n' "$st" "$(show_path "$key")"
}

echo "applying:"
HOOKS_CHANGED=0
while IFS=$'\t' read -r phase kind src key st x _; do
  [ "$phase" = 1 ] || continue
  apply_item "$kind" "$src" "$key" "$st" "$x"
  [ "$st" = same ] || HOOKS_CHANGED=1
done <"$WORK/plan.tsv"

if [ "$HOOKS_CHANGED" = 1 ]; then
  # the staged tree too: a hook may need a skill of this tag, and the skills come after this step
  if run_hook_tests "$CLAUDE_HOME/hooks" "$WORK/hook-tests.log" "$STAGE" </dev/null; then
    echo "hook tests:   $(tr '\n' ' ' <"$WORK/hook-tests.log" | sed 's/ *$//')"
  else
    cat "$WORK/hook-tests.log" >&2
    echo "install: hook tests failed on the installed hooks; putting the previous hooks back" >&2
    # the previous hook goes back by copy + rename (no moment without a hook file); a new hook is moved away
    while IFS=$'\t' read -r phase _ _ key st _; do
      [ "$phase" = 1 ] && [ "$st" != same ] || continue
      p=$(key_path "$key")
      mkdir -p "$DSP/failed-hooks"
      if [ -e "$DSP/$key" ]; then
        cp -pX "$p" "$DSP/failed-hooks/$(basename "$p")"
        tmp="$(dirname "$p")/.$(basename "$p").setup-restore.$$"
        cp -pX "$DSP/$key" "$tmp"
        mv -f "$tmp" "$p"
      else
        mv "$p" "$DSP/failed-hooks/$(basename "$p")"
      fi
    done <"$WORK/plan.tsv"
    APPLYING=0
    echo "install: stopped after the hooks step; nothing else written; the manifest still records ${PREV_REF:-nothing}" >&2
    exit 5
  fi
fi

while IFS=$'\t' read -r phase kind src key st x _; do
  [ "$phase" != 1 ] || continue
  apply_item "$kind" "$src" "$key" "$st" "$x"
done <"$WORK/plan.tsv"

# ---------- 7. check, manifest ----------
live_vs_ref all >"$WORK/post.tsv"
for f in "$WORK"/retired-lines.*; do
  [ -s "$f" ] || continue
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    if has_line "$line" "$GIT_EXCLUDES"; then printf 'retired line still present "%s"\tGIT_EXCLUDES\n' "$line" >>"$WORK/post.tsv"; fi
  done <"$f"
done
if [ -s "$WORK/post.tsv" ]; then
  while IFS=$'\t' read -r reason key; do printf '  %-24s %s\n' "$reason" "$(show_path "$key")" >&2; done <"$WORK/post.tsv"
  die "live does not match $REF after install; the manifest was not written. Snapshot: ${SNAP:-none (sandbox)}"
fi
if [ "$MAN_WRITE" = 1 ]; then install_file "$WORK/manifest.new" "$MAN" 600 "$MANIFEST_KEY" "$DSP"; fi
APPLYING=0
final_report
[ ! -d "$DSP" ] || echo "replaced:     $DSP"
if destinations_are_live; then
  echo "next: restart open Claude sessions (Desktop and CLI), run the canary prompts; bash scripts/doctor.sh --live"
fi
