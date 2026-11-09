#!/bin/bash
# Is the scan inside a commit alive? It runs from the env of settings.json, and a commit that lands says nothing about it. So
# real commits in a throwaway repo, with those keys and that command: a clean one has to land, one with a made-up token has to
# stop on the text of commit-leaks.sh. A typo in the command stops every commit of every project; a typo in a key or a path,
# a hook file with no x bit, no rules or no gitleaks leave the scan off.
#   bash scripts/commit-scan-probe.sh <settings.json> [<hooks folder>]
# The folder stands in for the path in the command: verify.sh checks the hook of the repo, doctor.sh passes none and checks live.
# Exit: 0 it works | 1 what is wrong, on stdout | 2 no such file, or no GIT_CONFIG keys in its env
set -uo pipefail

SETTINGS=$1; HOOKS=${2:-}
# as in step 14 of verify.sh: a repo of the caller is never touched, also from a git hook
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_COMMON_DIR GIT_PREFIX \
      GITLEAKS_CONFIG GITLEAKS_CONFIG_TOML
[ -e "$SETTINGS" ] || exit 2
keys=$(jq -r '(.env // {}) | to_entries[] | select(.key | startswith("GIT_CONFIG_")) | "\(.key)=\(.value)"' "$SETTINGS" 2>&1) ||
  { echo "the env of settings.json does not read: ${keys%%$'\n'*}"; exit 1; }
[ -n "$keys" ] || exit 2
[ -z "$HOOKS" ] || keys=$(sed "s#[^ =]*/\.claude/hooks/#'$HOOKS/'#g" <<<"$keys")
gitenv=()
while IFS= read -r kv; do gitenv+=("$kv"); done <<<"$keys"

W=$(mktemp -d "${TMPDIR:-/tmp}/commit-scan.XXXXXX") || { echo "no temporary folder"; exit 1; }
trap 'case $W in */commit-scan.*) rm -rf -- "$W" ;; esac' EXIT
commit=(env "${gitenv[@]}" BASH_GUARD_ERRLOG="$W/err" git -C "$W/r" -c user.name=probe -c user.email=probe@example.com commit -q -m probe)
git init -q "$W/r" || { echo "git init failed"; exit 1; }

printf 'hello\n' >"$W/r/a.txt"; git -C "$W/r" add a.txt
out=$("${commit[@]}" 2>&1) || { echo "a clean commit stops: ${out%%$'\n'*}"; exit 1; }

tok=$(head -c 512 /dev/urandom | LC_ALL=C tr -dc 'a-zA-Z0-9' | head -c 36)   # a git hook ignores SIGPIPE: tr on all of urandom never ends
printf 'token = "ghp_%s"\n' "$tok" >"$W/r/b.txt"; git -C "$W/r" add b.txt
if out=$("${commit[@]}" 2>&1); then
  echo "a commit with a made-up token lands: ${out:-no word from the scan (a key of the env, or git before 2.54?)}"
  exit 1
fi
[[ $out == *'BLOCKED by commit-leaks: gitleaks found a secret'* ]] ||
  { echo "a commit with a made-up token stops, not on the scan: ${out%%$'\n'*}"; exit 1; }
