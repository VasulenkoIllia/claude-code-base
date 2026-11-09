#!/bin/bash
# plan.sh: the change plan of a tag, which is install.sh <tag> --dry-run: verify gates, drift check, the plan; writes nothing.
#
#   bash scripts/plan.sh <tag>
#
# A name of its own: the ask rule of .claude/settings.json stays on install.sh for the real install, and the dry-run of a
# release no longer waits for the owner (owner's decision 01.11). One word only, so no option of install.sh gets through.
# Exit: as install.sh: 0 ok, 1 error, 2 usage, 3 drift, 4 verify failed.
set -euo pipefail

[ $# -eq 1 ] || { echo "usage: bash scripts/plan.sh <tag>" >&2; exit 2; }
case $1 in "" | -*) echo "plan.sh: bad ref: '$1'" >&2; exit 2 ;; esac
exec bash "$(dirname "$0")/install.sh" "$1" --dry-run
