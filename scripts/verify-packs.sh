# verify-packs.sh: checks 22-25 of scripts/verify.sh, the packs library (split off for size). Sourced by verify.sh in
# the root of the tree under test: it uses ok, fail and details and the staged copy STAGE of that script.

# 22. The packs library (ADR-007), all of it optional: a tree without packs/ (a tag up to v2026.11.32, the public
# version) passes. With packs/: scripts/catalog.py --check (the generated catalog equals a fresh generation; names and
# layout, frontmatter and budget of every pack: own code, as claude plugin validate does not look at these),
# managed_items of scripts/lib.sh takes every pack as an item of its own and the catalog as three files, and
# settings.json registers the catalog `library` at ~/.claude/packs. With tools/claude-pack.py: it is a managed item, and
# the ask rules on its enable and on edits of ~/.claude/packs are in settings.json (in auto mode the only prompt on
# the way to an enabled pack). With packs/ and the tool: the advisor skill skills/own/library-advisor is there (gate 9
# of catalog.py keeps the domains in its description equal to the packs; without the skill nothing proposes a pack),
# and settings.json allows `claude-pack suggest`, the read-only first step of the advisor, without a prompt
packprobs=""; packwarn=""; packnote="no packs/ in this tree (the library is optional)"
mkt=$(jq -r '.extraKnownMarketplaces.library.source | select(.source == "directory") | .path // empty' global/settings.json 2>/dev/null || true)
items=""
if [ -f scripts/lib.sh ]; then
  # shellcheck disable=SC2016  # the inner shell expands $1
  items=$(bash -c '. "$1/scripts/lib.sh" && managed_items "$1"' _ "$STAGE" 2>&1) || packprobs="$packprobs [managed_items: $(printf '%s\n' "$items" | tail -n 1)]"
fi
if [ -d packs ]; then
  [ -x tools/claude-pack.py ] || packprobs="$packprobs [packs/ without an executable tools/claude-pack.py: nothing would enable a pack]"
  if [ ! -f scripts/catalog.py ]; then
    packprobs="$packprobs [packs/ without scripts/catalog.py]"
  elif cout=$(python3 -I scripts/catalog.py --check . 2>&1); then
    # details are for a catalog that fails only; its warnings (evals of a pilot pack that did not run) get lines of their own
    packnote=$(printf '%s\n' "$cout" | tail -n 1); packwarn=$(printf '%s\n' "$cout" | grep '^WARN: ' || true); cout=""
  else
    packprobs="$packprobs [catalog.py --check, below]"
  fi
  npacks=$(find packs -mindepth 1 -maxdepth 1 -type d ! -name .claude-plugin | wc -l | tr -d ' ')
  ndirs=$(printf '%s\n' "$items" | awk -F '\t' '$2 == "dir" && index($4, "CLAUDE_HOME/packs/") == 1' | wc -l | tr -d ' ')
  nfiles=$(printf '%s\n' "$items" | awk -F '\t' '$2 == "file" && index($4, "CLAUDE_HOME/packs/") == 1' | wc -l | tr -d ' ')
  if [ "$npacks" != "$ndirs" ] || [ "$nfiles" != 3 ]; then
    packprobs="$packprobs [managed_items: $ndirs pack item(s) for $npacks pack folder(s), $nfiles catalog file(s) of 3]"
  fi
  # shellcheck disable=SC2088  # the text of the settings key, which Claude Code expands
  [ "$mkt" = '~/.claude/packs' ] || packprobs="$packprobs [settings.json does not register the catalog library at ~/.claude/packs]"
elif [ -n "$mkt" ]; then
  packprobs="$packprobs [settings.json registers the catalog library, the tree has no packs/]"
fi
if [ -f tools/claude-pack.py ]; then
  printf '%s\n' "$items" | grep -q "$(printf '\t')BIN_DIR/claude-pack\$" || packprobs="$packprobs [tools/claude-pack.py is no managed item]"
  for r in 'Bash(*claude-pack*enable*)' 'Edit(~/.claude/packs/**)' 'Write(~/.claude/packs/**)'; do
    jq -e --arg r "$r" '(.permissions.ask // []) | index($r) != null' global/settings.json >/dev/null 2>&1 ||
      packprobs="$packprobs [no ask rule $r in settings.json]"
  done
  packnote="$packnote; claude-pack is managed, its enable and edits of ~/.claude/packs ask"
  if [ -d packs ]; then
    if [ -f skills/own/library-advisor/SKILL.md ]; then packnote="$packnote; the advisor names the domains of the packs"
    else packprobs="$packprobs [packs/ and claude-pack without skills/own/library-advisor/SKILL.md: nothing proposes a pack]"; fi
    # shellcheck disable=SC2088  # the text of the settings rule, which Claude Code expands
    for r in 'Bash(~/bin/claude-pack suggest)' 'Bash(~/bin/claude-pack suggest:*)'; do
      jq -e --arg r "$r" '(.permissions.allow // []) | index($r) != null' global/settings.json >/dev/null 2>&1 ||
        packprobs="$packprobs [no allow rule $r in settings.json: the advisor would ask on its read-only step]"
    done
  fi
fi
if [ -z "$packprobs" ]; then ok "packs and catalog: $packnote"; if [ -n "$packwarn" ]; then printf '%s\n' "$packwarn" | details; fi
else fail "packs and catalog:$packprobs"; if [ -n "${cout:-}" ]; then printf '%s\n' "$cout" | details; fi; fi

# 23. catalog.py on made-up packs (tests/catalog-test.py, offline, a temp folder): a clean pack generates the catalog
# and passes --check, a stale or hand-edited catalog fails it, and every defect the gates name fails with its one problem
if [ -f scripts/catalog.py ]; then
  if [ ! -f tests/catalog-test.py ]; then
    fail "catalog: tests/catalog-test.py is missing"
  elif ctout=$(python3 -I tests/catalog-test.py 2>&1); then
    ok "$(printf '%s\n' "$ctout" | tail -1)"
  else
    fail "catalog: tests/catalog-test.py"; printf '%s\n' "$ctout" | details
  fi
fi

# 24. claude-pack on a made-up home, catalog and project folders (tests/claude-pack-test.py, offline): list, info and
# suggest only read (suggest on five project folders: three need a pack, two need none); enable and disable write the
# one key and a journal line, keep the rest of the file, refuse what they must
if [ -f tools/claude-pack.py ]; then
  if ! cpout=$(python3 -I tools/claude-pack.py --help 2>&1) || [ -n "$(find tools -name __pycache__ -print -quit)" ]; then
    fail "claude-pack: tools/claude-pack.py --help (or a __pycache__ under tools/)"; printf '%s\n' "$cpout" | details
  elif [ ! -f tests/claude-pack-test.py ]; then
    fail "claude-pack: tests/claude-pack-test.py is missing"
  elif cpout=$(python3 -I tests/claude-pack-test.py 2>&1); then
    ok "$(printf '%s\n' "$cpout" | tail -1)"
  else
    fail "claude-pack: tests/claude-pack-test.py"; printf '%s\n' "$cpout" | details
  fi
fi

# 25. The packs column of project-doctor.sh on a made-up home and project folders (tests/project-doctor-pack-test.py,
# offline): with a catalog the column, the flags PACK?<pack>, PACK-UNREAD, PACK-SKIPPED and PACK-ERR and the count; with
# no catalog (the public version) no word of the packs
if [ -f tools/claude-pack.py ] && [ -f scripts/project-doctor.sh ]; then
  if [ ! -f tests/project-doctor-pack-test.py ]; then
    fail "project-doctor: tests/project-doctor-pack-test.py is missing"
  elif pdout=$(python3 -I tests/project-doctor-pack-test.py 2>&1); then
    ok "$(printf '%s\n' "$pdout" | tail -1)"
  else
    fail "project-doctor: tests/project-doctor-pack-test.py"; printf '%s\n' "$pdout" | details
  fi
fi
