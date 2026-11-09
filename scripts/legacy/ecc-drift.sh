#!/bin/bash
# Read-only: show how installed ECC skills/agents drifted from upstream since the pin in ~/.claude/ECC-PIN.md
ECC=~/ai-stack/everything-claude-code
PIN=$(awk '/^pin:/{print $2}' ~/.claude/ECC-PIN.md)
git -C "$ECC" fetch -q origin || { echo "fetch failed"; exit 1; }
echo "ECC pin $PIN -> origin/main $(git -C "$ECC" rev-parse --short origin/main) ($(git -C "$ECC" show origin/main:VERSION 2>/dev/null))"
for d in ~/.claude/skills/*/; do s=$(basename "$d")
  git -C "$ECC" cat-file -e "origin/main:skills/$s/SKILL.md" 2>/dev/null || continue
  st=$(git -C "$ECC" diff --shortstat "$PIN" origin/main -- "skills/$s"); [ -n "$st" ] && echo "skill $s:$st"
done
for f in ~/.claude/agents/*.md; do a=$(basename "$f" .md)
  git -C "$ECC" cat-file -e "origin/main:agents/$a.md" 2>/dev/null || continue
  st=$(git -C "$ECC" diff --shortstat "$PIN" origin/main -- "agents/$a.md"); [ -n "$st" ] && echo "agent $a:$st"
done
echo "check done"
