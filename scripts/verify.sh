#!/bin/bash
# verify.sh: offline checks for the Claude setup base (plan 4.6 and 4.8, step 1). Takes some 4.5 minutes (270 s on
# 10.11.2026), most of it the hook tests of check 8 (test-all.sh, some 200 s).
#
#   bash scripts/verify.sh          check this repo: the files git would commit (tracked + untracked, not ignored)
#   bash scripts/verify.sh <dir>    check another tree, e.g. the staging dir install.sh unpacked from a tag
#
# Exit 0: all checks green. Exit 1: at least one check failed. Exit 2: bad usage or a missing tool.
#
# Read-only for the tree under test. Hook tests, gitleaks and the pre-commit simulation run on a
# temporary copy that is deleted on exit. Secret values are never printed: gitleaks runs with
# --redact and only file:line and the rule name are shown; the regex sweep prints the same.
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
case "${1:-}" in
  -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
  -*) echo "unknown option: $1" >&2; exit 2 ;;
esac
[ $# -le 1 ] || { echo "usage: bash scripts/verify.sh [dir]" >&2; exit 2; }
TARGET=${1:-$REPO}
[ -d "$TARGET" ] || { echo "not a directory: $TARGET" >&2; exit 2; }
TARGET=$(cd "$TARGET" && pwd -P)   # physical path: git reports /private/tmp, not /tmp

for tool in jq shellcheck gitleaks python3 git tar; do
  command -v "$tool" >/dev/null 2>&1 || { echo "verify: required tool not found: $tool" >&2; exit 2; }
done

# Limits and known exceptions -------------------------------------------------------------------
CLAUDE_MD_MAX=9900           # bytes, ≈3 550 tokens of the English text (≈2.8 B/token, measured 14.10), docs/adr/ADR-002-claude-md-budget.md
SKILL_DESC_MAX=500           # characters of description + when_to_use: the base's own limit (the skill listing cuts at 1 536, and the whole listing at 1% of the model's window), ADR-002
SKILL_BODY_MAX=24000         # bytes of the SKILL.md of an own skill (skills/own): it is read whole on every call, ADR-002
SKILL_LINES_MAX=500          # lines of the SKILL.md of an own skill; the detail goes to a file next to it
SKILL_EXTERNAL="graphify"    # skills outside the base (README, «Не керує»): allowed as skillOverrides keys, never in skills:
RULE_MAX=2000                # bytes per path-scoped rule file (B2); ≈810 tokens of the English text (2.47 B/token, 14.10)
RULES_TOTAL_MAX=15000        # bytes for all rule files together (B2 8500; B2.1 adds deps.md; B4 adds clean-code.md; unchanged at the language stage 14.10; 12 500 -> 13 000 on 03.11 for the move to pnpm in deps.md, owner's decision; 13 000 -> 15 000 on 13.11 for python.md, the Python parity of the audit plan, decisions Б13-Б16; ADR-002)
RULE_GROUPS="own"
RULE_PRIORITY_LINE="The project takes precedence. New and changed code only: don't rewrite or audit existing code, name a noticed violation in one line."

# Accepted ShellCheck codes, per file. These hooks were imported unchanged from the live state in
# Phase A, so they cannot be edited without a release. Drop an entry when its file is next changed.
#   bash-guard.sh SC1087: false positive. "$A[[:blank:]]" concatenates a regex fragment, not an array index.
#   bash-guard.sh SC2164: `cd "$cwd"` without `|| exit` inside $( ) for the develop-branch ask check.
sc_accepted() {
  case "$1" in
    hooks/bash-guard.sh) printf 'SC1087,SC2164' ;;
    *) printf '' ;;
  esac
}

# Output helpers ---------------------------------------------------------------------------------
FAILS=0; CHECKS=0
ok()     { CHECKS=$((CHECKS + 1)); printf '  ok    %s\n' "$*"; }
fail()   { CHECKS=$((CHECKS + 1)); FAILS=$((FAILS + 1)); printf '  FAIL  %s\n' "$*"; }
detail() { printf '          %s\n' "$*"; }
details() { local line; while IFS= read -r line; do detail "$line"; done; }

# Stage the tree under test into a temp dir ------------------------------------------------------
WORK=$(mktemp -d "${TMPDIR:-/tmp}/ecc-verify.XXXXXX")
cleanup() { case "$WORK" in */ecc-verify.*) rm -rf "$WORK" ;; esac; }
trap cleanup EXIT
STAGE="$WORK/stage"
mkdir "$STAGE"

if [ -e "$TARGET/.git" ] && [ "$(git -C "$TARGET" rev-parse --show-toplevel 2>/dev/null)" = "$TARGET" ]; then
  MODE="git worktree, tracked + untracked, not ignored"
  git -C "$TARGET" ls-files -z -co --exclude-standard \
    | while IFS= read -r -d '' f; do
        if [ -e "$TARGET/$f" ] || [ -L "$TARGET/$f" ]; then printf '%s\0' "$f"; fi
      done \
    | (cd "$TARGET" && tar -cf - --null -T -) | (cd "$STAGE" && tar -xpf -)
else
  MODE="plain directory, every file"
  (cd "$TARGET" && tar -cf - --exclude ./.git .) | (cd "$STAGE" && tar -xpf -)
fi
NFILES=$(find "$STAGE" -type f | wc -l | tr -d ' ')
echo "verify: $TARGET"
echo "        $NFILES files ($MODE)"

cd "$STAGE"

# 1. Required files ------------------------------------------------------------------------------
missing=""
# Every file install.sh maps to a live path must be here: a managed file left out of a commit would
# otherwise drop out of the base without any message.
for f in .gitleaks.toml global/CLAUDE.global.md global/settings.json global/home-agents.md \
         global/git-excludes hooks/test-all.sh vendor/ecc/ECC-PIN.md vendor/items.tsv \
         scripts/legacy/ecc-drift.sh tools/time-register.py tools/time_register/__init__.py tools/claude-metrics.py \
         tools/claude_metrics/__init__.py; do
  [ -f "$f" ] || missing="$missing $f"
done
if [ -z "$missing" ]; then ok "layout: required files present"; else fail "layout: missing:$missing"; fi

# 2. No symlinks (install copies files; a link could point into a live path) ---------------------
links=$(find . -type l | sed 's#^\./##')
if [ -z "$links" ]; then ok "no symlinks"; else fail "symlinks found"; printf '%s\n' "$links" | details; fi

# 3. JSON validity -------------------------------------------------------------------------------
bad=""; n=0
while IFS= read -r -d '' f; do
  n=$((n + 1))
  jq empty "$f" >/dev/null 2>&1 || bad="$bad ${f#./}"
done < <(find . -type f -name '*.json' -print0)
if [ -f global/settings.json ] && ! jq -e 'type == "object"' global/settings.json >/dev/null 2>&1; then
  bad="$bad global/settings.json(not-an-object)"
fi
if [ -z "$bad" ]; then ok "json: $n files parse"; else fail "json: invalid:$bad"; fi

# 4. desktopSessionCleanupPeriodDays must never come back (SAFETY-CHECK 6) ------------------------
hits=$(find . -type f -name '*.json' -exec grep -l 'desktopSessionCleanupPeriodDays' {} + 2>/dev/null | sed 's#^\./##' || true)
if [ -z "$hits" ]; then ok "settings: no desktopSessionCleanupPeriodDays key"
else fail "settings: desktopSessionCleanupPeriodDays found (it deletes desktop session history)"; printf '%s\n' "$hits" | details; fi

# 5. Hooks referenced in settings.json exist in hooks/ and are executable ------------------------
if [ -f global/settings.json ]; then
  probs=""; n=0
  while IFS= read -r cmd; do
    [ -n "$cmd" ] || continue
    n=$((n + 1))
    if [[ $cmd =~ \.claude/hooks/([A-Za-z0-9._-]+) ]]; then
      h=${BASH_REMATCH[1]}
      if [ ! -f "hooks/$h" ]; then probs="$probs hooks/$h(missing)"
      elif [ ! -x "hooks/$h" ]; then probs="$probs hooks/$h(not-executable)"; fi
    else
      probs="$probs [command outside ~/.claude/hooks: ${cmd%% *}]"
    fi
  done < <(jq -r '(.hooks // {}) | to_entries[] | .value[]? | .hooks[]? | .command // empty' global/settings.json)
  # and the other way: every hook script in hooks/ (not a test suite) is wired in settings.json, commit-leaks.sh in its env,
  # as git runs that one. Not docs-sync.sh: git runs it from the .git/config of each project that docs-sync.sh connect
  # connected, never from settings.json
  cmds=$(jq -r '(.hooks // {}) | to_entries[] | .value[]? | .hooks[]? | .command // empty' global/settings.json
         jq -r '(.env // {}) | to_entries[] | select(.key | startswith("GIT_CONFIG_")) | .value' global/settings.json)
  scan=$(bash scripts/commit-scan-probe.sh global/settings.json "$PWD/hooks" 2>&1) ||
    probs="$probs commit-scan(${scan:-no GIT_CONFIG keys in the env of settings.json})"
  for f in hooks/*.sh; do
    h=${f#hooks/}
    case $h in test-*.sh | *-tests.sh | docs-sync.sh) continue ;; esac
    grep -qF "/.claude/hooks/$h" <<<"$cmds" || probs="$probs hooks/$h(not in settings.json)"
  done
  # session-hint runs after a compaction and after a Bash call: a typo in a matcher or an event leaves it dead
  for w in 'SessionStart compact' 'PostToolUse Bash'; do
    jq -e --arg e "${w% *}" --arg m "${w#* }" '[.hooks[$e][]? | select(.matcher == $m) | .hooks[]?.command | strings]
      | any(endswith("/.claude/hooks/session-hint.sh"))' global/settings.json >/dev/null 2>&1 ||
      probs="$probs session-hint(not on $w)"
  done
  # node-std speaks at a session start: a matcher there would leave it dead for the other sources
  jq -e '[.hooks.SessionStart[]? | select(.matcher == null) | .hooks[]?.command | strings]
    | any(endswith("/.claude/hooks/node-std.sh"))' global/settings.json >/dev/null 2>&1 ||
    probs="$probs node-std(not on SessionStart without a matcher)"
  if [ -z "$probs" ]; then ok "settings: $n hook commands -> files in hooks/, executable; every hook script is wired; session-hint on SessionStart compact and PostToolUse Bash; node-std on SessionStart; the env of settings.json stops a commit with a made-up token"
  else fail "settings: hook problems:$probs"; fi
fi

# 6. bash -n and shellcheck on every shell script ------------------------------------------------
SH_FILES=()
while IFS= read -r -d '' f; do SH_FILES+=("${f#./}"); done < <(
  find hooks scripts tests -type f \( -name '*.sh' -o -path 'scripts/git-hooks/*' \) -print0 2>/dev/null | sort -z)
synerr=""; scout="$WORK/shellcheck.txt"; : > "$scout"
for f in ${SH_FILES[@]+"${SH_FILES[@]}"}; do
  bash -n "$f" 2>/dev/null || synerr="$synerr $f"
  args=(-S warning -f gcc)
  [ "$(head -c 2 "$f")" = '#!' ] || args+=(--shell=bash)
  acc=$(sc_accepted "$f")
  [ -z "$acc" ] || args+=(-e "$acc")
  shellcheck "${args[@]}" "$f" >> "$scout" 2>&1 || true
done
if [ -z "$synerr" ]; then ok "bash -n: ${#SH_FILES[@]} scripts"; else fail "bash -n: syntax errors in:$synerr"; fi
if [ ! -s "$scout" ]; then ok "shellcheck -S warning: ${#SH_FILES[@]} scripts clean"
else fail "shellcheck -S warning: $(wc -l < "$scout" | tr -d ' ') findings"; details < "$scout"; fi

# 7. Python syntax (compiled in memory, nothing written) ------------------------------------------
# Python helpers are written to $WORK first: bash 3.2 misparses quotes in a heredoc inside $( ).
cat > "$WORK/pysyntax.py" <<'PY'
import os, sys
bad, n = [], 0
for d, dirs, files in os.walk(sys.argv[1]):
    dirs[:] = [x for x in dirs if x not in ('.git', '__pycache__')]
    for name in files:
        if name.endswith('.py'):
            n += 1
            p = os.path.join(d, name)
            try:
                with open(p, encoding='utf-8') as fh:
                    compile(fh.read(), p, 'exec')
            except (SyntaxError, UnicodeDecodeError, ValueError) as e:
                bad.append('%s: %s' % (p[2:], type(e).__name__))
print(n)
for b in bad:
    print(b)
sys.exit(1 if bad else 0)
PY
pyout=$(python3 -I "$WORK/pysyntax.py" .) && pyrc=0 || pyrc=$?
if [ "$pyrc" -eq 0 ]; then ok "python syntax: $(printf '%s\n' "$pyout" | head -1) files"
else fail "python syntax errors"; printf '%s\n' "$pyout" | tail -n +2 | details; fi

# 8. Hook tests run against the copies under test, never against ~/.claude ------------------------
hard=$(grep -nE '^[^#]*\.claude/hooks/' hooks/*.sh 2>/dev/null || true)
if [ -n "$hard" ]; then
  fail "hook tests: hooks/ hardcodes ~/.claude/hooks, so tests would not test these copies"
  printf '%s\n' "$hard" | cut -d: -f1,2 | details
elif [ -f hooks/test-all.sh ]; then
  if tout=$(bash "$STAGE/hooks/test-all.sh" 2>&1); then trc=0; else trc=$?; fi
  nok=$(printf '%s\n' "$tout" | grep -cE '^(ALL|EXTRA|DIRS|DUP|DOCS|HINT|SYNC|NODE) OK$' || true)
  if [ "$trc" -eq 0 ] && [ "$nok" -eq 9 ] && printf '%s\n' "$tout" | grep -qx 'DUP OK' &&
    printf '%s\n' "$tout" | grep -qx 'DOCS OK' && printf '%s\n' "$tout" | grep -qx 'HINT OK' &&
    printf '%s\n' "$tout" | grep -qx 'DIRS OK' && printf '%s\n' "$tout" | grep -qx 'SYNC OK' &&
    printf '%s\n' "$tout" | grep -qx 'NODE OK'; then
    ok "hook tests: test-all.sh on these copies -> $(printf '%s\n' "$tout" | grep -E '^(ALL|EXTRA|DIRS|DUP|DOCS|HINT|SYNC|NODE) OK$' | paste -sd ',' - | sed 's/,/, /g')"
  else
    fail "hook tests: test-all.sh exit $trc, $nok of 9 OK lines (details: bash hooks/test-all.sh)"
    # test cases contain token-shaped fixtures: show only the verdict part
    printf '%s\n' "$tout" | grep -E '^FAIL' | sed -E 's/^(FAIL[^:]*):.*/\1/' | head -20 | details
  fi
fi

# 9. Skill and agent frontmatter; no argument placeholders in skills; preloads (B5) --------------
# An agent's skills: list preloads skills, but Claude Code silently skips (debug log only) a name it
# cannot find, a skill with disable-model-invocation, and a skill hidden by skillOverrides
# (user-invocable-only, off). A skill with paths: is not loaded until a matching file is touched, and a hidden
# one never is. skillOverrides values: on, name-only, user-invocable-only, off.
cat > "$WORK/frontmatter.py" <<'PY'
import ast, json, os, re, sys
root, desc_max = sys.argv[1], int(sys.argv[2])
external, body_max, lines_max = set(sys.argv[3].split()), int(sys.argv[4]), int(sys.argv[5])
NAME = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')
ARGS = re.compile(r'\$(?:[0-9]|ARGUMENTS)')
SKILL_GROUPS, AGENT_GROUPS = ('vendor-ecc', 'own'), ('vendor-ecc', 'vendor-anthropic', 'own')
HIDDEN = ('user-invocable-only', 'off')
OVERRIDE_VALUES = ('on', 'name-only') + HIDDEN
fails, seen = [], {}
skill_fm, preloads = {}, []   # skill name -> frontmatter; (agent file, skill name) per skills: entry

def parse(path):
    with open(path, encoding='utf-8') as fh:
        text = fh.read()
    lines = text.split('\n')
    if not lines or lines[0].rstrip('\r') != '---':
        return None, text
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip('\r') == '---'), None)
    if end is None:
        return None, text
    fm, key = {}, None
    for line in lines[1:end]:
        m = re.match(r'^([A-Za-z0-9_-]+):(.*)$', line)
        if m:
            key = m.group(1)
            fm[key] = m.group(2).strip()
        elif key and line[:1] in (' ', '\t'):
            fm[key] = (fm[key] + ' ' + line.strip()).strip()
    return fm, text

def value(fm, key):
    v = re.sub(r'^[>|][-+]?\s*', '', fm.get(key, '').strip())
    if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
        v = v[1:-1]
    return v.strip()

def items(fm, key):
    # YAML list as parse() joins it ("- a - b"), flow list "[a, b]" or comma-separated string "a, b"
    v = fm.get(key, '').strip()
    if v.startswith('['):
        parts = v.strip('[]').split(',')
    elif v.startswith('-'):
        parts = re.split(r'(?:^|\s)-\s+', v)
    else:
        parts = v.split(',')
    return [p.strip().strip('"\'') for p in parts if p.strip().strip('"\'')]

def lint(kind, rel, expected, text_check):
    fm, text = parse(os.path.join(root, rel))
    if fm is None:
        fails.append('%s: no frontmatter block (--- ... ---) at the top' % rel)
        return None
    name, desc = value(fm, 'name'), value(fm, 'description')
    if not name:
        fails.append('%s: name missing' % rel)
    elif name != expected:
        fails.append('%s: name "%s" differs from %s "%s"' % (rel, name, 'folder' if kind == 'skill' else 'file name', expected))
    elif not NAME.match(name):
        fails.append('%s: name "%s" is not lowercase letters, digits and hyphens (max 64)' % (rel, name))
    if not desc:
        fails.append('%s: description missing' % rel)
    elif kind == 'skill':
        wtu = value(fm, 'when_to_use')
        listed = len(desc) + (len(wtu) + 1 if wtu else 0)
        if listed > desc_max:
            fails.append('%s: description + when_to_use %d chars, max %d' % (rel, listed, desc_max))
        size, nlines = len(text.encode('utf-8')), len(text.splitlines())
        if rel.startswith('skills/own/') and (size > body_max or nlines > lines_max):
            fails.append('%s: %d B, %d lines; an own skill holds at most %d B and %d lines (move the detail to a file '
                         'next to it)' % (rel, size, nlines, body_max, lines_max))
    if text_check:
        for no, line in enumerate(text.split('\n'), 1):
            if ARGS.search(line):
                fails.append('%s:%d: literal $0-$9 or $ARGUMENTS (Claude Code substitutes these in skills)' % (rel, no))
    key = (kind, expected)
    if key in seen:
        fails.append('%s: duplicate %s name, also %s' % (rel, kind, seen[key]))
    seen[key] = rel
    return fm

def skill_overrides():
    p = os.path.join(root, 'global', 'settings.json')
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        fails.append('global/settings.json: unreadable (%s), skillOverrides not checked' % type(e).__name__)
        return {}
    so = data.get('skillOverrides', {}) if isinstance(data, dict) else {}
    if not isinstance(so, dict):
        fails.append('global/settings.json: skillOverrides is not an object')
        return {}
    return so

def check_preloads():
    so = skill_overrides()
    for rel, name in preloads:
        fm = skill_fm.get(name)
        if fm is None:
            fails.append('%s: skills: "%s", which is not a skill of the base (skills/vendor-ecc, skills/own)' % (rel, name))
            continue
        if items(fm, 'paths'):
            fails.append('%s: skills: "%s", which has paths: (not loaded until a matching file is touched)' % (rel, name))
        if value(fm, 'disable-model-invocation').lower() == 'true':
            fails.append('%s: skills: "%s", which sets disable-model-invocation (preload skips it)' % (rel, name))
        if so.get(name) in HIDDEN:
            fails.append('%s: skills: "%s", but skillOverrides hides it as "%s" (preload skips it; use "name-only")' % (rel, name, so[name]))
    for key in sorted(so):
        if key not in skill_fm and key not in external:
            fails.append('global/settings.json: skillOverrides key "%s" is no skill of the base and not in SKILL_EXTERNAL' % key)
        if so[key] not in OVERRIDE_VALUES:
            fails.append('global/settings.json: skillOverrides "%s": value "%s" is not one of %s' % (key, so[key], ', '.join(OVERRIDE_VALUES)))
        elif so[key] in HIDDEN and key in skill_fm and items(skill_fm[key], 'paths'):
            fails.append('global/settings.json: skillOverrides hides "%s" as "%s", but it has paths: (the conditional skill never shows)' % (key, so[key]))

def check_metrics():
    # claude-metrics counts preloads and path-scoped skills by PRELOAD and CONDITIONAL (tools/claude_metrics/patterns.py):
    # same as frontmatter
    p = os.path.join(root, 'tools', 'claude_metrics', 'patterns.py')
    if not os.path.isfile(p):
        return
    try:
        with open(p, encoding='utf-8') as fh:
            consts = {n.targets[0].id: ast.literal_eval(n.value) for n in ast.parse(fh.read()).body
                      if isinstance(n, ast.Assign) and len(n.targets) == 1
                      and getattr(n.targets[0], 'id', '') in ('PRELOAD', 'CONDITIONAL')}
    except (OSError, SyntaxError, ValueError) as e:
        fails.append('tools/claude_metrics/patterns.py: PRELOAD and CONDITIONAL must be literals (%s)' % type(e).__name__)
        return
    pre = {(os.path.basename(rel)[:-3], name) for rel, name in preloads}
    cond = {n for n, fm in skill_fm.items() if items(fm, 'paths')}
    if set(consts.get('PRELOAD', {}).items()) != pre:
        fails.append('tools/claude_metrics/patterns.py: PRELOAD %s differs from the agents\' skills: %s' % (sorted(consts.get('PRELOAD', {}).items()), sorted(pre)))
    if set(consts.get('CONDITIONAL', ())) != cond:
        fails.append('tools/claude_metrics/patterns.py: CONDITIONAL %s differs from the skills with paths: %s' % (sorted(consts.get('CONDITIONAL', ())), sorted(cond)))

counts = {'skill': 0, 'agent': 0}
for top, groups, kind in (('skills', SKILL_GROUPS, 'skill'), ('agents', AGENT_GROUPS, 'agent')):
    base = os.path.join(root, top)
    if not os.path.isdir(base):
        continue
    for group in sorted(os.listdir(base)):
        gpath = os.path.join(base, group)
        if group == '.DS_Store':
            continue
        if not os.path.isdir(gpath) or group not in groups:
            fails.append('%s/%s: unexpected entry (allowed groups: %s)' % (top, group, ', '.join(groups)))
            continue
        for entry in sorted(os.listdir(gpath)):
            if entry in ('.gitkeep', '.DS_Store'):
                continue
            rel = '%s/%s/%s' % (top, group, entry)
            if kind == 'skill':
                if not os.path.isdir(os.path.join(gpath, entry)):
                    fails.append('%s: a skill must be a folder with SKILL.md' % rel)
                elif not os.path.isfile(os.path.join(gpath, entry, 'SKILL.md')):
                    fails.append('%s: SKILL.md missing' % rel)
                else:
                    counts['skill'] += 1
                    fm = lint('skill', rel + '/SKILL.md', entry, True)
                    if fm is not None:
                        skill_fm[entry] = fm
            else:
                if not entry.endswith('.md') or not os.path.isfile(os.path.join(gpath, entry)):
                    fails.append('%s: an agent must be a .md file' % rel)
                else:
                    counts['agent'] += 1
                    fm = lint('agent', rel, entry[:-3], False)
                    if fm is not None:
                        preloads.extend((rel, s) for s in items(fm, 'skills'))
check_preloads()
check_metrics()
print('%d skills, %d agents, %d preload(s)' % (counts['skill'], counts['agent'], len(preloads)))
for f in fails:
    print(f)
sys.exit(1 if fails else 0)
PY
fmout=$(python3 -I "$WORK/frontmatter.py" . "$SKILL_DESC_MAX" "$SKILL_EXTERNAL" "$SKILL_BODY_MAX" "$SKILL_LINES_MAX") && fmrc=0 || fmrc=$?
if [ "$fmrc" -eq 0 ]; then ok "frontmatter: $(printf '%s\n' "$fmout" | head -1): name + description (+ when_to_use <= $SKILL_DESC_MAX), SKILL.md of an own skill <= $SKILL_BODY_MAX B and $SKILL_LINES_MAX lines, no \$N/\$ARGUMENTS in SKILL.md, preloads visible, skillOverrides keys and values valid, no hidden conditional skill, metrics lists match"
else fail "frontmatter: $(printf '%s\n' "$fmout" | tail -n +2 | wc -l | tr -d ' ') problems"; printf '%s\n' "$fmout" | tail -n +2 | details; fi

# 9a. Negative fixtures for check 9: a clean synthetic tree must pass, and each copy with one defect
# must fail with exactly one problem, the expected one. Catches a check that stopped catching.
cat > "$WORK/frontmatter-fixtures.py" <<'PY'
import json, os, sys
out, desc_max, body_max, lines_max = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
PRE = '---\nname: fx-pre\ndescription: Fixture skill an agent preloads.\n%s---\n%s'
COND = '---\nname: fx-cond\ndescription: Fixture conditional skill.\nwhen_to_use: %s\npaths:\n  - "**/*.fx"\n---\nBody.\n'
AGENT = '---\nname: fx-agent\ndescription: Fixture agent.\ntools: Read\n%s---\nBody.\n'
CLEAN = {'pre': '', 'wtu': 'When a .fx file changes.', 'skills': 'skills:\n  - fx-pre\n', 'body': 'Body.\n',
         'overrides': {'fx-pre': 'name-only', 'fx-ext': 'user-invocable-only'}}
CASES = [  # (case, change to CLEAN, text the one failure must contain)
    ('clean', {}, ''),
    ('unknown-skill', {'skills': 'skills: [fx-pre, fx-missing]\n'}, '"fx-missing", which is not a skill of the base'),
    ('conditional-skill', {'skills': 'skills:\n  - fx-pre\n  - fx-cond\n'}, '"fx-cond", which has paths:'),
    ('model-invocation-off', {'pre': 'disable-model-invocation: true\n'}, 'sets disable-model-invocation'),
    ('override-user-only', {'overrides': {'fx-pre': 'user-invocable-only'}}, 'hides it as "user-invocable-only"'),
    ('override-off', {'overrides': {'fx-pre': 'off'}}, 'hides it as "off"'),
    ('override-unknown-key', {'overrides': dict(CLEAN['overrides'], **{'fx-gone': 'off'})}, 'key "fx-gone" is no skill'),
    ('override-bad-value', {'overrides': dict(CLEAN['overrides'], **{'fx-pre': 'name_only'})}, 'value "name_only" is not one of'),
    ('conditional-hidden', {'overrides': dict(CLEAN['overrides'], **{'fx-cond': 'user-invocable-only'})}, 'hides "fx-cond" as'),
    ('long-when-to-use', {'wtu': 'x' * desc_max}, 'description + when_to_use'),
    ('description-one-over', {'wtu': 'x' * (desc_max - len('Fixture conditional skill.'))}, 'description + when_to_use %d chars' % (desc_max + 1)),
    ('own-skill-bytes', {'body': 'x' * body_max + '\n'}, 'an own skill holds at most'),
    ('own-skill-lines', {'body': 'x\n' * lines_max}, 'an own skill holds at most'),
]
def write(rel, text):
    p = os.path.join(out, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as fh:
        fh.write(text)
for case, change, want in CASES:
    c = dict(CLEAN, **change)
    write(case + '/skills/own/fx-pre/SKILL.md', PRE % (c['pre'], c['body']))
    write(case + '/skills/own/fx-cond/SKILL.md', COND % c['wtu'])
    write(case + '/agents/own/fx-agent.md', AGENT % c['skills'])
    write(case + '/global/settings.json', json.dumps({'skillOverrides': c['overrides']}))
print('\n'.join('%s\t%s' % (case, want) for case, _, want in CASES))   # only after every tree is written
PY
fxbad=""; fxn=0
while IFS=$'\t' read -r fxcase fxwant; do
  fxout=$(python3 -I "$WORK/frontmatter.py" "$WORK/fixtures/$fxcase" "$SKILL_DESC_MAX" "fx-ext" "$SKILL_BODY_MAX" "$SKILL_LINES_MAX") && fxrc=0 || fxrc=$?
  fxprobs=$(printf '%s\n' "$fxout" | tail -n +2 | grep -c . || true)
  if [ "$fxcase" = clean ]; then
    [ "$fxrc" -eq 0 ] || fxbad="$fxbad clean(exit $fxrc)"
  else
    fxn=$((fxn + 1))
    if [ "$fxrc" -eq 0 ] || [ "$fxprobs" -ne 1 ] || ! printf '%s\n' "$fxout" | grep -qF -- "$fxwant"; then
      fxbad="$fxbad $fxcase(exit $fxrc, $fxprobs problems)"
    fi
  fi
done < <(python3 -I "$WORK/frontmatter-fixtures.py" "$WORK/fixtures" "$SKILL_DESC_MAX" "$SKILL_BODY_MAX" "$SKILL_LINES_MAX")
if [ -z "$fxbad" ] && [ "$fxn" -gt 0 ]; then ok "frontmatter fixtures: clean tree passes, $fxn broken copies each fail with their one problem"
else fail "frontmatter fixtures: check 9 misjudged:${fxbad:- no fixtures generated}"; fi

# 9b. vendor/items.tsv: where every vendored file came from (one format for the core and for the packs, ADR-007):
# every file under skills/vendor-* and agents/vendor-* has a line with its class, source, pin and license, a patched
# file names its patch, a verbatim one has the sha256 of the source. The rules: scripts/vendor_items.py (split off
# for size), run in the tree under test
if [ -f vendor/items.tsv ]; then
  if vout=$(python3 -I "$REPO/scripts/vendor_items.py" 2>&1); then
    ok "vendor: items.tsv: $(printf '%s\n' "$vout" | head -1); every vendored file has its source, pin and class"
  else
    fail "vendor: items.tsv differs from skills/vendor-*, agents/vendor-* or vendor/*/patches"
    printf '%s\n' "$vout" | tail -n +2 | details
  fi
fi

# 10. Global CLAUDE.md budget (ADR-002) ----------------------------------------------------------
if [ -f global/CLAUDE.global.md ]; then
  bytes=$(wc -c < global/CLAUDE.global.md | tr -d ' ')
  lines=$(wc -l < global/CLAUDE.global.md | tr -d ' ')
  if [ "$bytes" -le "$CLAUDE_MD_MAX" ]; then
    ok "CLAUDE.global.md: $bytes B, $lines lines (max $CLAUDE_MD_MAX B, headroom $((CLAUDE_MD_MAX - bytes)) B)"
  else
    fail "CLAUDE.global.md: $bytes B, $lines lines, over the $CLAUDE_MD_MAX B budget by $((bytes - CLAUDE_MD_MAX)) B"
  fi
fi

# 10b. Path-scoped rules (rules/<group>/<name>.md -> ~/.claude/rules/<name>.md) ------------------
# A rule without a valid paths: list loads every session, so it would bypass the CLAUDE.md budget.
if [ -d rules ]; then
  if out=$(python3 -I - "$RULE_MAX" "$RULES_TOTAL_MAX" "$RULE_GROUPS" "$RULE_PRIORITY_LINE" <<'PY'
import os, re, sys
rule_max, total_max = int(sys.argv[1]), int(sys.argv[2])
groups, prio = sys.argv[3].split(), sys.argv[4]
NAME = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')
fails, total, n = [], 0, 0
for g in sorted(os.listdir('rules')):
    if g == '.DS_Store':
        continue
    gp = os.path.join('rules', g)
    if not os.path.isdir(gp) or g not in groups:
        fails.append('rules/%s: unexpected entry (allowed groups: %s)' % (g, ', '.join(groups)))
        continue
    for e in sorted(os.listdir(gp)):
        if e in ('.gitkeep', '.DS_Store'):
            continue
        rel = 'rules/%s/%s' % (g, e)
        p = os.path.join(gp, e)
        if not e.endswith('.md') or not os.path.isfile(p):
            fails.append('%s: a rule must be a .md file' % rel); continue
        if not NAME.match(e[:-3]):
            fails.append('%s: name must be lowercase letters, digits and hyphens' % rel)
        raw = open(p, 'rb').read(); size = len(raw); total += size; n += 1
        if size > rule_max:
            fails.append('%s: %d B, max %d B' % (rel, size, rule_max))
        t = raw.decode('utf-8')
        m = re.match(r'---\n(.*?)\n---\n(.*)', t, re.S)
        if not m:
            fails.append('%s: YAML frontmatter missing (--- ... ---)' % rel); continue
        fm, body = m.group(1), m.group(2)
        lines = fm.split('\n')
        if not lines or lines[0].strip() != 'paths:':
            fails.append('%s: frontmatter must start with "paths:" as a YAML list' % rel); continue
        globs = []
        for l in lines[1:]:
            mm = re.match(r'^  - "([^"]+)"$', l)
            if not mm:
                fails.append('%s: frontmatter line %r is not  - "<glob>"' % (rel, l)); break
            globs.append(mm.group(1))
        if not globs:
            fails.append('%s: paths list is empty' % rel)
        first = next((l for l in body.split('\n') if l.strip()), '')
        if first.strip() != prio:
            fails.append('%s: first body line must be the project-priority line' % rel)
if total > total_max:
    fails.append('rules: %d B in total, max %d B' % (total, total_max))
print('%d rule(s), %d B' % (n, total))
for f in fails:
    print(f)
sys.exit(1 if fails else 0)
PY
  ); then ok "rules: $(printf '%s\n' "$out" | head -1) (each <= $RULE_MAX B, total <= $RULES_TOTAL_MAX B, paths: list, priority line)"
  else fail "rules: frontmatter, size or priority line"; printf '%s\n' "$out" | details; fi
fi

# 11. Instruction files only at the root (checked on the full tree, ignored files included) -------
# Claude reads any CLAUDE.md / AGENTS.md it meets as real instructions; templates use *.tmpl names.
inst="$WORK/instruction-files.txt"; : > "$inst"
find "$TARGET" -path "$TARGET/.git" -prune -o \( -type f -o -type l \) \
     \( -iname CLAUDE.md -o -iname AGENTS.md -o -iname CLAUDE.local.md \) -print \
  | while IFS= read -r p; do
      case "$p" in
        "$TARGET/CLAUDE.md"|"$TARGET/CLAUDE.local.md") ;;
        *) printf '%s\n' "${p#"$TARGET"/}" >> "$inst" ;;
      esac
    done
if [ ! -s "$inst" ]; then ok "instruction files: none besides the root CLAUDE.md"
else fail "instruction files outside the root (rename to *.tmpl or move)"; details < "$inst"; fi

# 12. gitleaks on the tree, with .gitleaks.toml ----------------------------------------------------
# Policy for .gitleaks.toml, parsed as TOML (not grepped): [extend] is exactly useDefault = true; no
# own [[rules]] and no old [allowlist]; [[allowlists]] entries hold only `description` and `paths`;
# every path is an anchored literal ^hooks/<name>$ (letters, digits, _ - | ( ) and \. only) that
# matches an existing hooks/*test*.sh file. Prints "PATH<TAB>regex" per entry, "ERR<TAB>text" per problem.
cat > "$WORK/gitleaks-policy.py" <<'PY'
import os, re, sys
try:
    import tomllib
except ImportError:
    print('ERR\tpython3 >= 3.11 needed to parse .gitleaks.toml (tomllib)')
    sys.exit(1)
try:
    with open('.gitleaks.toml', 'rb') as fh:
        cfg = tomllib.load(fh)
except (OSError, tomllib.TOMLDecodeError) as e:
    print('ERR\t.gitleaks.toml does not parse: %s' % type(e).__name__)
    sys.exit(1)
errs, out = [], []
for key in cfg:
    if key not in ('title', 'description', 'extend', 'allowlists'):
        errs.append('top-level "%s" not allowed (no own rules, no old [allowlist])' % key)
if cfg.get('extend') != {'useDefault': True}:
    errs.append('[extend] must be exactly useDefault = true (default rules on, none disabled)')
SAFE = re.compile(r'^\^hooks/(?:[A-Za-z0-9_|()-]|\\\.)+\$$')
hook_files = sorted('hooks/' + f for f in os.listdir('hooks')) if os.path.isdir('hooks') else []
allowlists = cfg.get('allowlists', [])
if not isinstance(allowlists, list):
    errs.append('allowlists must be [[allowlists]] tables')
    allowlists = []
for i, al in enumerate(allowlists, 1):
    if not isinstance(al, dict):
        errs.append('allowlists #%d is not a table' % i)
        continue
    extra = sorted(set(al) - {'description', 'paths'})
    if extra:
        errs.append('allowlists #%d: only description and paths allowed, found %s' % (i, ', '.join(extra)))
    for p in al.get('paths', []):
        if not isinstance(p, str) or not SAFE.match(p):
            errs.append('allowlists #%d: path %r is not an anchored literal ^hooks/<name>$' % (i, p))
            continue
        hits = [f for f in hook_files if re.search(p, f)]
        if not hits:
            errs.append('allowlists #%d: path %s matches no file in hooks/' % (i, p))
        for f in hits:
            if not re.match(r'^hooks/[^/]*test[^/]*\.sh$', f):
                errs.append('allowlists #%d: path %s matches %s, which is not a hook test file' % (i, p, f))
        out.append(p)
for p in out:
    print('PATH\t' + p)
for e in errs:
    print('ERR\t' + e)
sys.exit(1 if errs else 0)
PY
glcfg_ok=1; allow_re=""
if [ ! -f .gitleaks.toml ]; then
  fail "gitleaks: .gitleaks.toml missing"; glcfg_ok=0
else
  glpol=$(python3 -I "$WORK/gitleaks-policy.py") && glprc=0 || glprc=$?
  allow_re=$(printf '%s\n' "$glpol" | awk -F '\t' '$1 == "PATH" { print $2 }' | paste -sd '|' -)
  if [ "$glprc" -eq 0 ]; then
    ok "gitleaks config: useDefault = true, allowlist = $(printf '%s\n' "$glpol" | awk -F '\t' '$1 == "PATH"' | wc -l | tr -d ' ') hook test path(s) only"
  else
    fail "gitleaks config: .gitleaks.toml breaks the policy (keep the allowlist narrow)"
    printf '%s\n' "$glpol" | awk -F '\t' '$1 == "ERR" { print $2 }' | details
    glcfg_ok=0; allow_re=""
  fi
fi
if [ "$glcfg_ok" -eq 1 ]; then
  # `gitleaks dir` is the gitleaks >= 8.19 form of the old `gitleaks detect --no-git`
  if (gitleaks dir . -c .gitleaks.toml --redact --no-banner --exit-code 1 \
        -f json -r "$WORK/gitleaks-dir.json" >"$WORK/gitleaks-dir.log" 2>&1); then glrc=0; else glrc=$?; fi
  if [ "$glrc" -eq 0 ]; then ok "gitleaks dir: no leaks (default rules + .gitleaks.toml)"
  elif [ "$glrc" -eq 1 ] && [ -s "$WORK/gitleaks-dir.json" ]; then
    fail "gitleaks dir: leaks found (values redacted)"
    jq -r '.[] | "\(.File):\(.StartLine) \(.RuleID)"' "$WORK/gitleaks-dir.json" | sort | details
  else
    fail "gitleaks dir: error (exit $glrc)"; grep -iE 'error|fatal' "$WORK/gitleaks-dir.log" | head -5 | details || true
  fi
fi

# 13. Secrets regex sweep: second net, prints file:line and rule only -----------------------------
# Paths allowlisted in .gitleaks.toml (the hook test fixtures, $allow_re from check 12) are skipped
# here as well, but only when that config passed the policy above.
sweep_rules() {
  cat <<'RULES'
private-key	-----BEGIN ([A-Z0-9]+ )*PRIVATE KEY-----
aws-access-key	(^|[^A-Z0-9])(AKIA|ASIA)[0-9A-Z]{16}([^A-Z0-9]|$)
github-token	gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}
sk-api-key	(^|[^A-Za-z0-9_-])sk-(ant-|proj-|or-)?[A-Za-z0-9_-]{20,}
slack-token	xox[abposr]-[A-Za-z0-9-]{10,}
google-api-key	AIza[0-9A-Za-z_-]{35}
google-oauth	GOCSPX-[A-Za-z0-9_-]{20,}|ya29\.[A-Za-z0-9_-]{30,}
stripe-key	[rs]k_live_[A-Za-z0-9]{20,}|whsec_[A-Za-z0-9]{20,}
telegram-bot-token	(^|[^A-Za-z0-9])[0-9]{8,12}:AA[A-Za-z0-9_-]{30,}
jwt	eyJ[A-Za-z0-9_-]{15,}\.eyJ[A-Za-z0-9_-]{15,}\.
vendor-token	npm_[A-Za-z0-9]{36}|glpat-[A-Za-z0-9_-]{20}|dckr_pat_[A-Za-z0-9_-]{20,}|hf_[A-Za-z0-9]{34}|sbp_[a-f0-9]{40}|ntn_[A-Za-z0-9]{40,}|gsk_[A-Za-z0-9]{40,}|sb_secret_[A-Za-z0-9_-]{20,}
bearer-token	[Bb]earer[[:space:]]+[A-Za-z0-9._~+/=-]{24,}
url-credentials	[A-Za-z][A-Za-z0-9+.-]*://[^/[:space:]:@"'<>]+:[^/[:space:]@"'<>$]{3,}@
RULES
}
# Passwords in URLs that are documentation placeholders, not secrets.
URL_PLACEHOLDER=':(postgres|pass|password|passwd|pwd|secret|changeme|change_me|example|test|dev|admin|root|user|x+|\*+|\.\.\.)@$'
sweep="$WORK/sweep.txt"; : > "$sweep"
sweep_rules | while IFS=$'\t' read -r rule re; do
  [ -n "$rule" ] || continue
  # -o keeps only the match in the pipe; cut drops it before anything is printed
  grep -rnoIE -e "$re" . 2>/dev/null \
    | { if [ "$rule" = url-credentials ]; then grep -viE "$URL_PLACEHOLDER" || true; else cat; fi; } \
    | cut -d: -f1,2 | sed 's#^\./##' \
    | while IFS= read -r loc; do
        if [ -n "$allow_re" ] && printf '%s\n' "${loc%:*}" | grep -qE "$allow_re"; then continue; fi
        printf '%s %s\n' "$loc" "$rule"
      done >> "$sweep" || true
done
if [ ! -s "$sweep" ]; then ok "secret sweep: $(sweep_rules | grep -c .) patterns, no hits outside the allowlisted fixtures"
else fail "secret sweep: $(sort -u "$sweep" | wc -l | tr -d ' ') hits (values not shown)"; sort -u "$sweep" | details; fi

# 14. The commit gate bash-guard applies: gitleaks git --pre-commit --staged ---------------------
# Same command bash-guard runs before `git commit` (config found on its own from the cwd), in a
# throwaway repo built from the staged copy. Git env vars are cleared so that a caller's repo
# (e.g. when run from a git hook) is never touched.
if [ "$glcfg_ok" -eq 1 ]; then
  if ( unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES \
             GIT_COMMON_DIR GIT_PREFIX GITLEAKS_CONFIG GITLEAKS_CONFIG_TOML
       git init -q -b main . >/dev/null 2>&1 && git add -A . >/dev/null 2>&1 \
         && gitleaks git --pre-commit --staged --redact --no-banner --exit-code 1 \
              -f json -r "$WORK/gitleaks-pre.json" >"$WORK/gitleaks-pre.log" 2>&1 ); then
    ok "commit gate: gitleaks git --pre-commit --staged passes from the repo root"
  else
    fail "commit gate: gitleaks git --pre-commit --staged would block the commit (values redacted)"
    if [ -s "$WORK/gitleaks-pre.json" ]; then
      jq -r '.[] | "\(.File):\(.StartLine) \(.RuleID)"' "$WORK/gitleaks-pre.json" | sort | details
    fi
  fi
fi

# 15. New-project standard (skills/own/new-project): every type x db renders and matches the rules ---
# Offline: placeholders, exact pinned versions, Node and Postgres images, .gitignore and .dockerignore,
# no published port in production compose, card fields, target guard; no __pycache__ left in the skill folder,
# which install copies as it is. The online gate (npm, Docker) is tests/new-project-test.sh.
if [ ! -f skills/own/new-project/scaffold.py ]; then
  fail "new-project standard: skills/own/new-project/scaffold.py is missing"
elif npout=$(python3 -I skills/own/new-project/scaffold.py --self-check 2>&1) \
    && [ -z "$(find skills/own/new-project -name __pycache__ -print -quit)" ]; then
  ok "new-project standard: $(printf '%s\n' "$npout" | head -1) render and match the rules"
else
  fail "new-project standard: scaffold.py --self-check (or a __pycache__ in skills/own/new-project)"
  printf '%s\n' "$npout" | details
fi

# 16. claude-metrics: the command line finds its package (tools/claude_metrics), writes no bytecode, and the
# cost per pushed commit holds on made-up transcripts and git repos (tests/metrics-test.py, offline, temp folder)
if ! cmout=$(python3 -I tools/claude-metrics.py --help 2>&1) || [ -n "$(find tools -name __pycache__ -print -quit)" ]; then
  fail "claude-metrics: tools/claude-metrics.py --help (or a __pycache__ under tools/)"; printf '%s\n' "$cmout" | details
elif [ ! -f tests/metrics-test.py ]; then
  fail "claude-metrics: tests/metrics-test.py is missing"
elif cmout=$(python3 -I tests/metrics-test.py 2>&1); then
  ok "claude-metrics: package imports, $(printf '%s\n' "$cmout" | tail -1)"
else
  fail "claude-metrics: tests/metrics-test.py"; printf '%s\n' "$cmout" | details
fi

# 17. claude-time: the command line finds its package (tools/time_register), writes no bytecode, and the register
# holds on made-up transcripts (tests/time-register-test.py; the split in chunks, --add --stage and --split-done
# --rows, in tests/time-register-stage-test.py; offline, temp folders under /private/tmp); --prompts with --add or
# --write writes nothing, which the allow rule for --prompts relies on
if ! trout=$(python3 -I tools/time-register.py --help 2>&1) || [ -n "$(find tools -name __pycache__ -print -quit)" ]; then
  fail "claude-time: tools/time-register.py --help (or a __pycache__ under tools/)"; printf '%s\n' "$trout" | details
elif [ ! -f tests/time-register-test.py ] || [ ! -f tests/time-register-stage-test.py ]; then
  fail "claude-time: tests/time-register-test.py or tests/time-register-stage-test.py is missing"
elif ! trout=$(python3 -I tests/time-register-test.py 2>&1); then
  fail "claude-time: tests/time-register-test.py"; printf '%s\n' "$trout" | details
elif stout=$(python3 -I tests/time-register-stage-test.py 2>&1); then
  ok "claude-time: package imports, $(printf '%s\n' "$trout" | tail -1); $(printf '%s\n' "$stout" | tail -1)"
else
  fail "claude-time: tests/time-register-stage-test.py"; printf '%s\n' "$stout" | details
fi

# 18. session-hint delivery check (tests/hint-delivered.py) as a command on made-up transcripts in a temp HOME
# (tests/hint-delivered-test.py, offline): every outcome, report line and exit code; on live transcripts it runs after
# install and in the canary
if hdout=$(python3 -I tests/hint-delivered-test.py 2>&1); then
  ok "session-hint: $(printf '%s\n' "$hdout" | tail -1)"
else
  fail "session-hint: tests/hint-delivered-test.py"; printf '%s\n' "$hdout" | details
fi

# 19. doctor.sh in a sandbox (tests/doctor-test.py, offline): its delivery line and line of hook failures
# (tests/hint-delivered.py --doctor on made-up transcripts), the WARNs of the hooks' error logs (internal errors apart
# from ShapeDrift) and an exit code that no WARN changes
if dtout=$(python3 -I tests/doctor-test.py 2>&1); then
  ok "doctor: $(printf '%s\n' "$dtout" | tail -1)"
else
  fail "doctor: tests/doctor-test.py"; printf '%s\n' "$dtout" | details
fi
# 20. the gate of tests/hook-replay.py on made-up results (tests/hook-replay-test.py, offline): an ask that goes away
# with no class or a line in the bash-guard error log fails it
if rgout=$(python3 -I tests/hook-replay-test.py 2>&1); then
  ok "$(printf '%s\n' "$rgout" | tail -1)"
else
  fail "hook-replay: tests/hook-replay-test.py"; printf '%s\n' "$rgout" | details
fi

# 21. the texts of session-hint equal TEXT in tests/hint_common.py (tests/hint-text-test.py): the delivery check after
# install reads a text that drifted as a hint not delivered, and that means a rollback
if htout=$(python3 -I tests/hint-text-test.py 2>&1); then
  ok "$(printf '%s\n' "$htout" | tail -1)"
else
  fail "session-hint texts: tests/hint-text-test.py"; printf '%s\n' "$htout" | details
fi

# 22-24. The packs library (ADR-007), all of it optional: packs and catalog against the installer and the settings,
# catalog.py and claude-pack on made-up packs and projects. Split off for size: scripts/verify-packs.sh, sourced here
. "$REPO/scripts/verify-packs.sh"

echo "verify: $CHECKS checks, $FAILS failed"
[ "$FAILS" -eq 0 ]
