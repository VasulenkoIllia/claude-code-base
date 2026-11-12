#!/bin/bash
# import-live.sh: copy the live, base-managed Claude setup into this repo.
# Live paths are only read; only files inside this repo are written.
#
#   bash scripts/import-live.sh --dry-run   show what would change in the repo, write nothing
#   bash scripts/import-live.sh             copy live -> repo (managed items only)
#   bash scripts/import-live.sh --check     compare every live/repo pair; exit 1 on any difference
#
# Live source locations can be overridden (sandbox tests):
#   CLAUDE_HOME (~/.claude)  HOME_AGENTS (~/AGENTS.md)  GIT_EXCLUDES (~/.config/git/ignore)  BIN_DIR (~/bin)
# Never imported: skills/graphify, skills/synced, plugins/, ~/.claude.json, projects/ (memory), project files.
#
# Repo edits are never lost: once the repo has a commit, a pair whose repo path has uncommitted changes
# (git status) is refused; every repo copy that an import replaces is first kept in
# local/import-replaced/<time>/<path> (gitignored).
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
CLAUDE_HOME=${CLAUDE_HOME:-$HOME/.claude}
HOME_AGENTS=${HOME_AGENTS:-$HOME/AGENTS.md}
GIT_EXCLUDES=${GIT_EXCLUDES:-$HOME/.config/git/ignore}
BIN_DIR=${BIN_DIR:-$HOME/bin}

MODE=import
case "${1:-}" in
  "") ;;
  --dry-run) MODE=dry ;;
  --check) MODE=check ;;
  -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
  *) echo "unknown argument: $1 (use --dry-run, --check or no argument)" >&2; exit 2 ;;
esac
[ $# -le 1 ] || { echo "too many arguments" >&2; exit 2; }

HOOKS=(bash-guard.sh secret-guard.sh nvm-env.sh test-hooks.sh extra-tests.sh secret-tests.sh test-all.sh)
ECC_SKILLS=(database-migrations docker-patterns security-review)
ECC_AGENTS=(architect code-reviewer database-reviewer react-reviewer security-reviewer typescript-reviewer)
ANTHROPIC_AGENTS=(silent-failure-hunter)
UNMANAGED_SKILLS=(graphify synced)

# One pair per line: <live source> TAB <repo destination, relative to REPO>
pairs() {
  local x
  printf '%s\t%s\n' "$CLAUDE_HOME/CLAUDE.md" global/CLAUDE.global.md
  printf '%s\t%s\n' "$CLAUDE_HOME/settings.json" global/settings.json
  printf '%s\t%s\n' "$HOME_AGENTS" global/home-agents.md
  printf '%s\t%s\n' "$GIT_EXCLUDES" global/git-excludes
  printf '%s\t%s\n' "$CLAUDE_HOME/ECC-PIN.md" vendor/ecc/ECC-PIN.md
  printf '%s\t%s\n' "$BIN_DIR/ecc-drift.sh" scripts/legacy/ecc-drift.sh
  for x in "${HOOKS[@]}"; do printf '%s\t%s\n' "$CLAUDE_HOME/hooks/$x" "hooks/$x"; done
  for x in "${ECC_SKILLS[@]}"; do printf '%s\t%s\n' "$CLAUDE_HOME/skills/$x" "skills/vendor-ecc/$x"; done
  for x in "${ECC_AGENTS[@]}"; do printf '%s\t%s\n' "$CLAUDE_HOME/agents/$x.md" "agents/vendor-ecc/$x.md"; done
  for x in "${ANTHROPIC_AGENTS[@]}"; do printf '%s\t%s\n' "$CLAUDE_HOME/agents/$x.md" "agents/vendor-anthropic/$x.md"; done
}

in_list() {
  local needle=$1 x; shift
  for x in "$@"; do [ "$x" = "$needle" ] && return 0; done
  return 1
}

xbit() { if [ -x "$1" ]; then echo x; else echo -; fi; }

# 0 when both sides have the same content, the same file list and the same user-executable bits
same() {
  local src=$1 dst=$2 f
  [ -e "$dst" ] || return 1
  if [ -d "$src" ]; then
    [ -d "$dst" ] || return 1
    diff -r -q "$src" "$dst" >/dev/null 2>&1 || return 1
    while IFS= read -r -d '' f; do
      [ "$(xbit "$src/$f")" = "$(xbit "$dst/$f")" ] || return 1
    done < <(cd "$src" && find . -type f -print0)
  else
    [ -f "$dst" ] || return 1
    cmp -s "$src" "$dst" || return 1
    [ "$(xbit "$src")" = "$(xbit "$dst")" ] || return 1
  fi
  return 0
}

WORK=$(mktemp -d "${TMPDIR:-/tmp}/import-live.XXXXXX")
trap 'case $WORK in */import-live.*) rm -rf -- "$WORK" ;; esac' EXIT   # temp copies only, never repo files
BKP="$REPO/local/import-replaced/$(date +%Y%m%d-%H%M%S)"
HAS_HEAD=0
if git -C "$REPO" rev-parse -q --verify HEAD >/dev/null 2>&1; then HAS_HEAD=1; fi

# 0 when <rel> has uncommitted changes in the repo (only checked once the repo has a commit)
uncommitted() { [ "$HAS_HEAD" = 1 ] && [ -n "$(git -C "$REPO" status --porcelain -- "$1" 2>/dev/null)" ]; }

# copy_pair <src> <dst> <rel>: the replaced repo copy is moved/copied to $BKP/<rel> first
copy_pair() {
  local src=$1 dst=$2 rel=$3 tmp
  mkdir -p "$(dirname "$dst")"
  if [ -e "$dst" ]; then mkdir -p "$(dirname "$BKP/$rel")"; fi
  if [ -d "$src" ]; then
    tmp=$(mktemp -d "$WORK/item.XXXXXX")
    cp -pRX "$src/." "$tmp/"
    chmod "$(stat -f '%Lp' "$src")" "$tmp"
    if [ -e "$dst" ]; then mv "$dst" "$BKP/$rel"; fi
    mv "$tmp" "$dst"
  else
    if [ -e "$dst" ]; then cp -pX "$dst" "$BKP/$rel"; fi
    cp -pX "$src" "$dst.import-tmp"
    mv "$dst.import-tmp" "$dst"
  fi
}

# 1. Every live source must exist and contain no symlinks (copies must be plain files)
missing=0
while IFS=$'\t' read -r src _; do
  if [ ! -e "$src" ]; then echo "missing live source: $src" >&2; missing=1; continue; fi
  if [ -L "$src" ] || [ -n "$(find "$src" -type l -print -quit)" ]; then
    echo "symlink in live source (not supported): $src" >&2; missing=1
  fi
done < <(pairs)
[ "$missing" = 0 ] || exit 1

# 2. Report live items in managed folders that the base does not know about (never imported)
for p in "$CLAUDE_HOME/hooks"/*; do
  [ -e "$p" ] || continue
  in_list "$(basename "$p")" "${HOOKS[@]}" || echo "note: unmanaged live hook file: $p"
done
for p in "$CLAUDE_HOME/skills"/*; do
  [ -e "$p" ] || continue
  n=$(basename "$p")
  in_list "$n" "${ECC_SKILLS[@]}" "${UNMANAGED_SKILLS[@]}" || echo "note: unmanaged live skill: $p"
done
for p in "$CLAUDE_HOME/agents"/*; do
  [ -e "$p" ] || continue
  n=$(basename "$p" .md)
  in_list "$n" "${ECC_AGENTS[@]}" "${ANTHROPIC_AGENTS[@]}" || echo "note: unmanaged live agent: $p"
done

# 3. vendor/ecc/items.tsv (when present) must list exactly the vendored skills and agents
rc=0
ITEMS="$REPO/vendor/ecc/items.tsv"
if [ -f "$ITEMS" ]; then
  want=$(printf '%s\n' "${ECC_SKILLS[@]}" "${ECC_AGENTS[@]}" "${ANTHROPIC_AGENTS[@]}" | LC_ALL=C sort)
  have=$(awk -F'\t' 'NR > 1 && $1 != "" {print $1}' "$ITEMS" | LC_ALL=C sort)
  if [ "$want" != "$have" ]; then
    echo "DIFF vendor/ecc/items.tsv names do not match the vendored item list" >&2
    rc=1
  fi
fi

# 4. Compare, plan or copy every pair
n_same=0; n_new=0; n_changed=0
while IFS=$'\t' read -r src rel; do
  dst="$REPO/$rel"
  if same "$src" "$dst"; then
    n_same=$((n_same + 1))
    [ "$MODE" = check ] && echo "OK    $rel"
    continue
  fi
  if [ -e "$dst" ]; then state=changed; n_changed=$((n_changed + 1)); else state=new; n_new=$((n_new + 1)); fi
  if [ "$MODE" != check ] && uncommitted "$rel"; then
    echo "REFUSED $rel: uncommitted changes in the repo; commit or move them first" >&2
    rc=1
    continue
  fi
  case "$MODE" in
    check)
      echo "DIFF  $rel ($state)"
      [ -d "$src" ] && [ -d "$dst" ] && diff -r -q "$src" "$dst" | sed 's/^/      /' || true
      rc=1 ;;
    dry) echo "would copy ($state): $src -> $rel" ;;
    import) copy_pair "$src" "$dst" "$rel"; echo "copied ($state): $rel" ;;
  esac
done < <(pairs)

total=$((n_same + n_new + n_changed))
case "$MODE" in
  check) echo "check: $total pairs, $n_same identical, $((n_new + n_changed)) different" ;;
  dry) echo "dry run: $total pairs, $n_same identical, $n_new new, $n_changed changed; nothing written" ;;
  import)
    echo "import: $total pairs, $n_same already identical, $n_new new, $n_changed updated"
    if [ -d "$BKP" ]; then echo "replaced repo copies kept in ${BKP#"$REPO"/}/"; fi ;;
esac
exit "$rc"
