#!/bin/bash
# project-doctor.sh: read-only health report for project folders (plan 4.6, step A8).
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash scripts/project-doctor.sh <dir> [<dir>...]   the given project folders
  bash scripts/project-doctor.sh --all              every folder in $PROJECTS_DIR (default ~/WebstormProjects)

Prints three tables (git and instruction files; Node and environment; flags) and a summary.
Read-only: every git call is 'git --no-optional-locks' (status never rewrites the index),
no network, no file contents or values are printed (only states, sizes, counts and flags).
The one file written is a temp CLAUDE_ENV_FILE for the repo copy of hooks/nvm-env.sh
(in $TMPDIR), removed on exit.

Env overrides:
  PROJECTS_DIR  folder scanned by --all            (~/WebstormProjects)
  CLAUDE_HOME   for skill/agent name clashes, memory (~/.claude)
  VIS_CACHE     visibility cache                   (local/repo-visibility.tsv: name TAB PUBLIC|PRIVATE TAB date)
EOF
}

REPO=$(cd "$(dirname "$0")/.." && pwd)
PROJECTS_DIR=${PROJECTS_DIR:-$HOME/WebstormProjects}
CLAUDE_HOME=${CLAUDE_HOME:-$HOME/.claude}
VIS_CACHE=${VIS_CACHE:-$REPO/local/repo-visibility.tsv}
NVM_HOOK=$REPO/hooks/nvm-env.sh
NODE_STD=$REPO/skills/own/new-project/node_std.py   # the Node standard of the repo's versions.json
BIG=15360       # bytes; the limit of the global rule for a project instruction file («rules and facts only, ~15 KB»); doctor.sh warns from twice that
MEM_FILE=5120   # bytes; the limit of the global rule for a memory file (≤5 KB); doctor.sh warns about them in an active project
MEM_INDEX=10    # lines; MEMORY.md budget (plan 5.2)
export GIT_OPTIONAL_LOCKS=0 GIT_TERMINAL_PROMPT=0

DIRS=()
case "${1:-}" in
  "") usage >&2; exit 2 ;;
  -h|--help) usage; exit 0 ;;
  --all)
    [ $# -eq 1 ] || { echo "--all takes no other arguments" >&2; exit 2; }
    for d in "$PROJECTS_DIR"/*/; do
      if [ -d "$d" ]; then DIRS+=("${d%/}"); fi
    done ;;
  -*) echo "unknown option: $1" >&2; exit 2 ;;
  *)
    for d in "$@"; do
      [ -d "$d" ] || { echo "not a directory: $d" >&2; exit 2; }
      DIRS+=("$(cd "$d" && pwd)")
    done ;;
esac
[ ${#DIRS[@]} -gt 0 ] || { echo "no project folders found" >&2; exit 2; }
[ -f "$NVM_HOOK" ] || { echo "missing $NVM_HOOK" >&2; exit 1; }

TMPD=$(mktemp -d "${TMPDIR:-/tmp}/project-doctor.XXXXXX")
trap 'rm -f "$TMPD/env" "$TMPD/t1" "$TMPD/t2" "$TMPD/t3"; rmdir "$TMPD" 2>/dev/null || true' EXIT
ENVF=$TMPD/env T1=$TMPD/t1 T2=$TMPD/t2 T3=$TMPD/t3

# JSON and Dockerfile shape; counts only, never values. Prints one tab-separated line.
read -r -d '' PY <<'EOF' || true
import json, os, re, sys
d = sys.argv[1]
SECRET = re.compile(r"""
    (?:api[_-]?key|access[_-]?key|secret|token|passw(?:or)?d|pwd|auth[_-]?key|private[_-]?key|credentials?)
      ["']?\s*[=:]\s*["']?[^\s"'$<{(][^\s"']{5,}
  | bearer\s+[a-z0-9._~+/-]{16,}
  | basic\s+[a-z0-9+/]{12,}={0,2}
  | \b(?:sk|rk)-[a-z0-9_-]{16,}
  | \bgh[pousr]_[a-z0-9]{20,} | \bgithub_pat_[a-z0-9_]{20,} | \bglpat-[a-z0-9_-]{20,}
  | \bxox[abposr]-[a-z0-9-]{10,} | \bAKIA[0-9A-Z]{16}\b | \bAIza[0-9a-z_-]{30,} | \bya29\.[0-9a-z_-]{20,}
  | \beyJ[a-z0-9_-]{10,}\.[a-z0-9_-]{10,}
  | \b\d{8,10}:AA[a-z0-9_-]{30,}
  | [a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@
""", re.I | re.X)
# same definition as ~/claude-backups/2026-10-11/scrub-allow.py, so counts match its dry-run
SCRUB = re.compile(r"://[^/\s:@]+:[^@\s]+@|cookie|authorization|bearer\s|passw(or)?d|pgpassword|api[_-]?key=|token=|secret=|[\w.+-]+@[\w-]+\.[\w.]+:[A-Za-z0-9]{16,}|\bsk-|ghp_|\d{8,10}:AA", re.I)
LONG = re.compile(r"(?<![A-Za-z0-9])(?=[A-Za-z0-9]*[0-9])(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{32,}(?![A-Za-z0-9])")
ABS = re.compile(r"(?<![\w.~-])/(?:Users|private|tmp|var)/[^\s\"';:&|()<>]+")

def strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from strings(v)

def load(rel):
    """(state, data): state is '-', EMPTY, INVALID, UNREADABLE or OK."""
    p = os.path.join(d, rel)
    if not os.path.isfile(p):
        return "-", None
    try:
        with open(p, encoding="utf-8") as f:
            raw = f.read()
    except (OSError, UnicodeDecodeError):
        return "UNREADABLE", None
    if not raw.strip():
        return "EMPTY", None
    try:
        data = json.loads(raw)
    except ValueError:
        return "INVALID", None
    return ("OK", data) if isinstance(data, dict) else ("INVALID", None)

def secrets(data):
    return sum(1 for t in strings(data) if SECRET.search(t) or SCRUB.search(t) or LONG.search(t))

def settings(rel):
    st, data = load(rel)
    if st != "OK":
        return st, 0
    perms = data.get("permissions") if isinstance(data.get("permissions"), dict) else {}
    def n(k):
        v = perms.get(k)
        return len(v) if isinstance(v, list) else 0
    tok = "a%d/k%d/d%d" % (n("allow"), n("ask"), n("deny"))
    env = data.get("env")
    if isinstance(env, dict) and env:
        tok += "/e%d" % len(env)
    other = [k for k in data if k not in ("permissions", "env", "$schema")]
    if other:
        tok += "/o%d" % len(other)
    return tok, secrets(data)

def clean(s, n):
    return re.sub(r"[^0-9A-Za-z.<>=^~|*_+-]", "", s)[:n] or "-"

out = []
for rel in (".claude/settings.local.json", ".claude/settings.json"):
    out.extend(settings(rel))

# package.json: engines.node (short spec + minimum major) and packageManager name
eng, eng_major, pm = "-", "-", "-"
st, data = load("package.json")
if st in ("INVALID", "UNREADABLE"):
    eng = "pkg-" + st
elif st == "OK":
    e = data.get("engines")
    v = e.get("node") if isinstance(e, dict) else None
    if isinstance(v, str) and v.strip():
        eng = clean(v.replace(" ", ""), 14)
        s = v.strip()
        m = re.search(r"\d+", s)
        if m and "||" not in s and not s.startswith("<"):
            eng_major = m.group(0)
    p = data.get("packageManager")
    if isinstance(p, str) and p.strip():
        pm = clean(p.split("@")[0], 8)
out += [eng, eng_major, pm]

# .claude/launch.json: configurations, how many mention nvm, dead absolute paths, secret-like strings
st, data = load(".claude/launch.json")
if st == "OK":
    cfgs = data.get("configurations") if isinstance(data.get("configurations"), list) else []
    nvm = sum(1 for c in cfgs if "nvm" in json.dumps(c))
    dead = set()
    for t in strings(data):
        for m in ABS.finditer(t):
            path = m.group(0).rstrip(".,")
            if not os.path.exists(path):
                dead.add(path)
    out += ["%dc/%dnvm" % (len(cfgs), nvm), str(len(dead)), str(secrets(data))]
else:
    out += [st, "0", "0"]

# Dockerfile at the root: major of the first 'FROM node:NN'
dock = "-"
p = os.path.join(d, "Dockerfile")
if os.path.isfile(p):
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            raw = f.read()
        if not raw.strip():
            dock = "EMPTY"
        else:
            m = re.search(r"^\s*FROM\s+(?:--platform=\S+\s+)?(?:[\w.-]+/)*node:(\d+)", raw, re.I | re.M)
            dock = m.group(1) if m else "other"
    except OSError:
        dock = "UNREADABLE"
out.append(dock)
print("\t".join(str(x) for x in out))
EOF

D="" ISGIT=0 FLAGS=""
g() { git --no-optional-locks -C "$D" "$@"; }
flag() { FLAGS="${FLAGS:+$FLAGS,}$1"; }
fsize() { stat -L -f %z "$1" 2>/dev/null || echo 0; }
nfiles() { { find "$1" -type f "${@:2}" 2>/dev/null || true; } | wc -l | tr -d ' '; }

hsize() {
  local b=$1
  if [ "$b" -lt 1024 ]; then printf '%sB' "$b"
  elif [ "$b" -lt 10240 ]; then awk -v b="$b" 'BEGIN { printf "%.1fK", b / 1024 }'
  else printf '%sK' $(((b + 512) / 1024)); fi
}

# T tracked, U untracked (shows in git status), I ignored, F exists (no git), - absent
pstate() {
  local rel=$1 q=$1
  if [ ! -e "$D/$rel" ]; then echo -; return 0; fi
  if [ "$ISGIT" != 1 ]; then echo F; return 0; fi
  if [ -d "$D/$rel" ]; then q="$rel/"; fi
  if [ -n "$(g ls-files -- "$rel" 2>/dev/null || true)" ]; then echo T
  elif g check-ignore -q -- "$q" 2>/dev/null; then echo I
  else echo U; fi
}

# Sets TOK to state+size of an instruction file and adds its flags (no subshell, so FLAGS survives).
TOK=-
instr() {
  local rel=$1 st f sz
  st=$(pstate "$rel")
  TOK=-
  if [ "$st" = - ]; then return 0; fi
  f="$D/$rel"
  sz=$(fsize "$f")
  if ! grep -q '[^[:space:]]' "$f" 2>/dev/null; then flag "EMPTY:$rel"; fi
  if [ "$sz" -gt "$BIG" ]; then flag "BIG:$rel"; fi
  if grep -q 'Project Agent Operating Standard' "$f" 2>/dev/null; then flag "GENERIC:$rel"; fi
  if [ "$st" = U ]; then flag "VISIBLE:$rel"; fi
  TOK="$st$(hsize "$sz")"
}

imports_agents() { grep -Eq '(^|[[:space:]])@(\./)?AGENTS\.md([[:space:]]|$)' "$1" 2>/dev/null; }

# First CLAUDE.md / CLAUDE.local.md / .claude/CLAUDE.md above the project (the global ~/.claude/CLAUDE.md does not count).
anc_claude() {
  local p f
  p=$(dirname "$1")
  while :; do
    for f in CLAUDE.md CLAUDE.local.md .claude/CLAUDE.md; do
      if [ "${p%/}/$f" = "$HOME/.claude/CLAUDE.md" ]; then continue; fi
      if [ -e "${p%/}/$f" ]; then echo "${p%/}/$f"; return 0; fi
    done
    if [ "$p" = / ]; then return 0; fi
    p=$(dirname "$p")
  done
}

anc_agents() {
  local p n=0
  p=$(dirname "$1")
  while :; do
    if [ -f "${p%/}/AGENTS.md" ]; then n=$((n + 1)); fi
    if [ "$p" = / ]; then break; fi
    p=$(dirname "$p")
  done
  echo "$n"
}

vis_lookup() {
  [ -f "$VIS_CACHE" ] || return 0
  awk -F'\t' -v n="$1" '$1 == n { print tolower($2); exit }' "$VIS_CACHE"
}

# Shell default Node (sessions without .nvmrc, or when the .nvmrc version is missing, run this one).
NODE_DEFAULT=$(bash -c 'export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh" --no-use >/dev/null 2>&1 && nvm version default' 2>/dev/null || true)
case "$NODE_DEFAULT" in v[0-9]*) ;; *) NODE_DEFAULT="" ;; esac
major() { local v=${1#v}; v=${v%%.*}; case "$v" in ''|*[!0-9]*) echo "" ;; *) echo "$v" ;; esac; }

N=0 NGIT=0 NDIRTY=0 NNOTLOADED=0 NGENERIC=0 NVISIBLE=0 NNODE=0 NMISMATCH=0 NSTD=0 NSETBAD=0 NSECRET=0 NMEM=0
row() {
  D=$1 FLAGS=""
  local name git=no branch=- dev=- vis=- dirty=- top
  name=$(basename "$D")
  ISGIT=0
  if top=$(g rev-parse --show-toplevel 2>/dev/null); then
    ISGIT=1
    if [ "$top" != "$D" ]; then git=sub; elif [ -f "$D/.git" ]; then git=wt; else git=yes; fi
    branch=$(g symbolic-ref --short -q HEAD 2>/dev/null || echo "@$(g rev-parse --short HEAD 2>/dev/null || echo none)")
    branch=$(printf '%s' "$branch" | cut -c1-24)
    local refs x hit
    refs=$(g for-each-ref --format='%(refname)' refs/heads refs/remotes 2>/dev/null || true)
    for x in dev develop; do
      hit=""
      if grep -qx "refs/heads/$x" <<< "$refs"; then hit=$x
      elif grep -qE "^refs/remotes/[^/]+/$x\$" <<< "$refs"; then hit="$x(r)"; fi
      if [ -n "$hit" ]; then
        if [ "$dev" = - ]; then dev=$hit; else dev="$dev+$hit"; fi
      fi
    done
    if [ -z "$(g remote 2>/dev/null || true)" ]; then vis=local
    else vis=$(vis_lookup "$name"); vis=${vis:-unknown}; fi
    if dirty=$(g status --porcelain 2>/dev/null | wc -l | tr -d ' '); then
      if [ "$dirty" -gt 0 ]; then NDIRTY=$((NDIRTY + 1)); fi
    else dirty=ERR; flag GIT-STATUS-ERR; fi
    NGIT=$((NGIT + 1))
  fi

  # --- Instruction files and what loads (plan 5.1: AGENTS.md loads only when no CLAUDE file exists here or above).
  local c cc cl a rules=- anc ptr=- agents=- has_claude=0 imp=0 f nr ship
  instr CLAUDE.md; c=$TOK
  instr .claude/CLAUDE.md; cc=$TOK
  instr CLAUDE.local.md; cl=$TOK
  instr AGENTS.md; a=$TOK
  if [ -d "$D/.claude/rules" ]; then
    nr=$(nfiles "$D/.claude/rules" -name '*.md')
    rules="$(pstate .claude/rules)$nr"
    case $rules in U*) flag "VISIBLE:.claude/rules" ;; esac
  fi
  for f in CLAUDE.md .claude/CLAUDE.md CLAUDE.local.md; do
    if [ -e "$D/$f" ]; then
      has_claude=1
      if imports_agents "$D/$f"; then imp=1; fi
    fi
  done
  anc=$(anc_claude "$D")
  if [ -n "$anc" ]; then has_claude=1; flag "ANCESTOR-CLAUDE"; fi
  if [ "$a" != - ]; then
    if [ "$has_claude" = 0 ]; then agents=loads
    elif [ "$imp" = 1 ]; then agents=@import
    else agents=NOT-LOADED; flag AGENTS-NOT-LOADED; NNOTLOADED=$((NNOTLOADED + 1)); fi
  elif [ "$imp" = 1 ]; then
    flag "IMPORT-MISSING:AGENTS.md"
  fi
  # Nested instruction files (load when Claude touches files in that folder); depth <= 4, build/vendor dirs skipped.
  local nested=0 p
  while IFS= read -r p; do
    case "$p" in
      "$D/CLAUDE.md"|"$D/AGENTS.md"|"$D/CLAUDE.local.md"|"$D/.claude/CLAUDE.md") ;;
      *) nested=$((nested + 1)) ;;
    esac
  done < <(find "$D" -maxdepth 4 \( -name node_modules -o -name .git -o -name dist -o -name build -o -name .next \
    -o -name vendor -o -path "$D/.claude/worktrees" \) -prune -o -type f \
    \( -name CLAUDE.md -o -name AGENTS.md -o -name CLAUDE.local.md \) -print 2>/dev/null || true)
  if [ "$nested" -gt 0 ]; then flag "NESTED:$nested"; fi
  if [ "$(anc_agents "$D")" -gt 0 ]; then
    if [ "$has_claude" = 0 ]; then ptr=y; else ptr=n; fi
  fi
  ship=$(pstate .claude/ship.md)
  if [ "$ship" = U ]; then flag "VISIBLE:.claude/ship.md"; fi
  if [ "$ship" = T ] && [ "$vis" = public ]; then flag "SHIP-TRACKED-PUBLIC"; fi

  # --- Node: what the repo copy of hooks/nvm-env.sh puts on PATH (SessionStart runs it in the project folder).
  local nvmrc=- node=- inst=- line bin eff
  eff=$NODE_DEFAULT
  if [ -f "$D/.nvmrc" ]; then
    nvmrc=$(tr -d '[:space:]' < "$D/.nvmrc" | tr -cd 'A-Za-z0-9._/*-' | cut -c1-14)
    nvmrc=${nvmrc:-EMPTY}
    : > "$ENVF"
    (cd "$D" && CLAUDE_ENV_FILE="$ENVF" bash "$NVM_HOOK" < /dev/null > /dev/null 2>&1) || true
    line=$(grep -m 1 '^export PATH="' "$ENVF" || true)
    if [ -n "$line" ]; then
      bin=${line#export PATH=\"}; bin=${bin%%:\$PATH\"}
      node=$(basename "$(dirname "$bin")")
      eff=$node
      if [ -x "$bin/node" ]; then inst=y; else inst=n; flag NODE-MISSING; NNODE=$((NNODE + 1)); fi
    else
      node="NONE>dflt"
      if [ -s "$HOME/.nvm/nvm.sh" ]; then inst=n; else inst=no-nvm; fi
      flag NODE-MISSING; NNODE=$((NNODE + 1))
    fi
  elif [ -n "$NODE_DEFAULT" ]; then
    node=dflt
  fi

  # --- Settings shape (counts only), engines.node, packageManager, launch.json, Dockerfile.
  local js lt=ERR lsec=0 pt=ERR psec=0 eng=- emaj=- pmf=- launch=ERR ldead=0 lsec2=0 dock=- st pm emj
  js=$(python3 -I -c "$PY" "$D" 2>/dev/null || printf 'ERR\t0\tERR\t0\t-\t-\t-\tERR\t0\t0\t-')
  IFS=$'\t' read -r lt lsec pt psec eng emaj pmf launch ldead lsec2 dock <<< "$js" || true
  lsec=${lsec:-0} psec=${psec:-0} ldead=${ldead:-0} lsec2=${lsec2:-0} emaj=${emaj:--} dock=${dock:--}
  if [ "$lt" != - ]; then
    st=$(pstate .claude/settings.local.json)
    if [ "$st" = T ]; then flag "LOCAL-SETTINGS-TRACKED"; fi
    case $lt in EMPTY|INVALID|UNREADABLE|ERR) flag "SETTINGS.LOCAL:$lt"; NSETBAD=$((NSETBAD + 1)) ;; esac
    lt="$st:$lt"
  fi
  if [ "$pt" != - ]; then
    st=$(pstate .claude/settings.json)
    case $pt in EMPTY|INVALID|UNREADABLE|ERR) flag "SETTINGS:$pt"; NSETBAD=$((NSETBAD + 1)) ;; esac
    pt="$st:$pt"
  fi
  if [ $((lsec + psec)) -gt 0 ]; then flag "SECRET-LIKE:$((lsec + psec))"; fi
  case $launch in
    -) ;;
    EMPTY|INVALID|UNREADABLE|ERR) flag "LAUNCH:$launch" ;;
    *)
      if [ "$ldead" -gt 0 ]; then flag "LAUNCH-DEAD-PATH:$ldead"; fi
      if [ "$lsec2" -gt 0 ]; then flag "LAUNCH-SECRET-LIKE:$lsec2"; fi ;;
  esac
  if [ $((lsec + psec + lsec2)) -gt 0 ]; then NSECRET=$((NSECRET + 1)); fi

  # package manager: packageManager field, else lockfiles (several lockfiles are flagged)
  local locks="" lf
  for lf in pnpm-lock.yaml:pnpm yarn.lock:yarn package-lock.json:npm bun.lockb:bun bun.lock:bun; do
    if [ -f "$D/${lf%%:*}" ]; then
      case "+$locks+" in *"+${lf##*:}+"*) ;; *) locks="${locks:+$locks+}${lf##*:}" ;; esac
    fi
  done
  if [ "$pmf" != - ]; then pm=$pmf; elif [ -n "$locks" ]; then pm=$locks; elif [ -f "$D/package.json" ]; then pm="?"; else pm=-; fi
  case $locks in *+*) flag "LOCKFILES:$locks" ;; esac

  # Node mismatches: effective Node (hook result or shell default) vs engines minimum and Dockerfile FROM node:NN
  emj=$(major "$eff")
  if [ -n "$emj" ]; then
    if [ "$emaj" != - ] && [ "$emj" -lt "$emaj" ]; then flag "NODE<ENGINES:$emj<$emaj"; fi
    case $dock in
      ''|*[!0-9]*) ;;
      *) if [ "$emj" != "$dock" ]; then flag "NODE!=DOCKER:$emj/$dock"; fi ;;
    esac
  fi
  case ",$FLAGS," in *,NODE\<ENGINES:*|*,NODE!=DOCKER:*) NMISMATCH=$((NMISMATCH + 1)) ;; esac

  # --- The Node standard (node_std.py: the oldest Node of .nvmrc, Docker and CI; the package manager)
  local std
  if std=$(python3 -I "$NODE_STD" --flags "$D" < /dev/null 2>/dev/null); then
    if [ -n "$std" ]; then flag "$std"; fi
  else flag NODE-STD-ERR; fi
  case ",$FLAGS," in *,NODE-EOL:*|*,NODE\<STD:*) NSTD=$((NSTD + 1)) ;; esac

  # --- docs/: tracked files there mean STATUS/inbox notes must go to .claude/state/ instead.
  local docs=- nd
  if [ -d "$D/docs" ]; then
    if [ "$ISGIT" = 1 ]; then
      nd=$(g ls-files -- docs 2>/dev/null | wc -l | tr -d ' ' || true)
      if [ "${nd:-0}" -gt 0 ]; then docs="T$nd"; else docs=$(pstate docs); fi
    else docs=F; fi
  fi

  # --- STATUS: 'status:' from .claude/ship.md, else docs/STATUS.md, .claude/state/STATUS.md, STATUS.md; state and age.
  local status=- srel="" sloc sst age now
  if [ -f "$D/.claude/ship.md" ]; then
    srel=$(sed -n 's/^status:[[:space:]]*//p' "$D/.claude/ship.md" 2>/dev/null | head -n 1 | tr -d '\r' || true)
    case $srel in /*|*..*) srel="" ;; esac
    if [ -n "$srel" ] && [ ! -f "$D/$srel" ]; then flag "SHIP-STATUS-MISSING"; srel=""; fi
  fi
  if [ -n "$srel" ]; then sloc=ship
  else
    for sloc in docs/STATUS.md .claude/state/STATUS.md STATUS.md; do
      if [ -f "$D/$sloc" ]; then srel=$sloc; break; fi
    done
    case $srel in docs/*) sloc=docs ;; .claude/*) sloc=state ;; STATUS.md) sloc=root ;; esac
  fi
  if [ -n "$srel" ]; then
    sst=$(pstate "$srel")
    now=$(date +%s)
    age=$(( (now - $(stat -L -f %m "$D/$srel" 2>/dev/null || echo "$now")) / 86400 ))
    status="$sloc:$sst:${age}d"
    if [ "$sst" = U ]; then flag "VISIBLE:$srel"; fi
    if [ "$sst" = T ] && [ "$vis" = public ]; then flag "STATUS-TRACKED-PUBLIC"; fi
  fi

  # --- Memory (~/.claude/projects/<path with every non-alphanumeric char as '-'>/memory): sizes only.
  local mdir mem=- mn mb mbig ml
  mdir="$CLAUDE_HOME/projects/$(printf '%s' "$D" | sed 's/[^A-Za-z0-9]/-/g')/memory"
  if [ -d "$mdir" ]; then
    mn=$(nfiles "$mdir")
    mb=$({ find "$mdir" -type f -exec stat -f %z {} + 2>/dev/null || true; } | awk '{ s += $1 } END { print s + 0 }')
    mbig=$(nfiles "$mdir" -size +"$MEM_FILE"c)
    mem="${mn}f/$(hsize "$mb")"
    if [ "$mbig" -gt 0 ]; then flag "MEM-FILE>5K:$mbig"; fi
    if [ -f "$mdir/MEMORY.md" ]; then
      ml=$(wc -l < "$mdir/MEMORY.md" | tr -d ' ')
      if [ "$ml" -gt 200 ] || [ "$(fsize "$mdir/MEMORY.md")" -gt 25600 ]; then flag "MEM-INDEX-TRUNCATED:${ml}L"
      elif [ "$ml" -gt "$MEM_INDEX" ]; then flag "MEM-INDEX:${ml}L"; fi
    fi
    case ",$FLAGS," in *,MEM-*) NMEM=$((NMEM + 1)) ;; esac
  fi

  # --- Name clashes with global skills (global wins) and agents (project wins).
  local s n
  for s in "$D"/.claude/skills/*/; do
    [ -d "$s" ] || continue
    n=$(basename "$s")
    if [ -e "$CLAUDE_HOME/skills/$n" ]; then flag "SKILL-SHADOWED:$n"; fi
  done
  for s in "$D"/.claude/agents/*.md; do
    [ -f "$s" ] || continue
    n=$(basename "$s" .md)
    if [ -e "$CLAUDE_HOME/agents/$n.md" ]; then flag "AGENT-OVERRIDES:$n"; fi
  done

  case ",$FLAGS," in *,GENERIC:*) NGENERIC=$((NGENERIC + 1)) ;; esac
  case ",$FLAGS," in *,VISIBLE:*) NVISIBLE=$((NVISIBLE + 1)) ;; esac
  N=$((N + 1))
  printf '%s\t' "$name" "$git" "$branch" "$dev" "$vis" "$dirty" "$c" "$cc" "$cl" "$a" "$rules" "$agents" "$ptr" >> "$T1"
  printf '%s\n' "$ship" >> "$T1"
  printf '%s\t' "$name" "$nvmrc" "$node" "$inst" "$eng" "$dock" "$pm" "$launch" "$docs" "$status" "$mem" "$lt" >> "$T2"
  printf '%s\n' "$pt" >> "$T2"
  if [ -n "$FLAGS" ]; then printf '%s\t%s\n' "$name" "$FLAGS" >> "$T3"; fi
}

nvm_installed=""
for v in "$HOME"/.nvm/versions/node/*/; do
  if [ -d "$v" ]; then nvm_installed="$nvm_installed $(basename "$v")"; fi
done
vis_note="no cache (local/repo-visibility.tsv missing)"
if [ -f "$VIS_CACHE" ]; then
  vis_note="cache $(basename "$VIS_CACHE"), checked $(awk -F'\t' '!/^#/ && NF >= 3 { print $3; exit }' "$VIS_CACHE")"
fi

printf '%s\t' PROJECT GIT BRANCH DEV VIS DIRTY CLAUDE.md .c/CLAUDE.md CLAUDE.local AGENTS.md RULES A.load ptr > "$T1"
printf '%s\n' ship >> "$T1"
printf '%s\t' PROJECT .nvmrc node inst engines docker pm launch docs status memory settings.local > "$T2"
printf '%s\n' settings >> "$T2"
printf '%s\t%s\n' PROJECT FLAGS > "$T3"
for d in "${DIRS[@]}"; do row "$d"; done

cat <<EOF
# project-doctor $(date '+%F %H:%M') | dirs: ${#DIRS[@]} | hook: repo hooks/nvm-env.sh sha256:$(shasum -a 256 "$NVM_HOOK" | cut -c1-12)
# Node: shell default (dflt) ${NODE_DEFAULT:-unknown} | installed:${nvm_installed:- none} | standard: $(jq -r '"Node \(.node), pnpm \(.pnpm)"' "$REPO/skills/own/new-project/versions.json" 2>/dev/null || echo unknown) (repo versions.json)
# visibility: $vis_note; local = no remote; unknown = remote not in cache
# loading rule: AGENTS.md (the project's and the ~/AGENTS.md pointer) loads only when no CLAUDE.md,
#   .claude/CLAUDE.md or CLAUDE.local.md exists in the project or above; with one, only an @AGENTS.md import loads it
#
# == 1. git and instruction files ==
# GIT: yes | wt (worktree) | sub (inside another repo) | no; DEV: dev/develop branch, (r) = remote only; DIRTY: git status --porcelain lines
# file columns: T tracked, U untracked (shows in git status), I ignored, F exists (no git), - absent; then size
# A.load: loads | @import (via a CLAUDE file) | NOT-LOADED (a CLAUDE file disables it) | - (no AGENTS.md)
# ptr: ~/AGENTS.md loads y/n; RULES: state + number of .claude/rules/*.md; ship: .claude/ship.md state
EOF
column -t -s $'\t' < "$T1"
cat <<EOF
#
# == 2. Node and environment ==
# node: what the repo copy of nvm-env.sh puts on PATH; dflt = no .nvmrc, shell default; NONE>dflt = .nvmrc version not installed
# inst: binary present; engines: package.json engines.node; docker: first 'FROM node:NN' in ./Dockerfile
# pm: packageManager or lockfiles; launch: .claude/launch.json configurations / how many mention nvm
# docs: Tn = n tracked files under docs/ (notes then go to .claude/state/); status: where STATUS is : state : age
# memory: files / size in ~/.claude/projects/<dir>/memory; settings*: <state>:a<allow>/k<ask>/d<deny>[/e<env>][/o<other keys>]
EOF
column -t -s $'\t' < "$T2"
cat <<EOF
#
# == 3. flags (only folders with at least one) ==
# GENERIC: old 'Project Agent Operating Standard' copy; BIG: > 15 KB; EMPTY; VISIBLE: untracked and not ignored;
# AGENTS-NOT-LOADED; ANCESTOR-CLAUDE; NESTED:n (CLAUDE.md/AGENTS.md below the root, depth <= 4);
# NODE-MISSING; NODE<ENGINES / NODE!=DOCKER (effective Node major vs engines minimum / Dockerfile);
# the standard (node_std.py, oldest Node of .nvmrc, Docker and CI): NODE-EOL:n (out of support or within 6 months of it),
#   NODE<STD:n<std, NODE-UNPINNED (no Node major pinned), NODE-UNKNOWN (a place not read, a .nvmrc of lts/*),
#   PM!=STD:<manager>, PNPM<STD:<pnpm><std>; NODE-STD-ERR (node_std.py failed or ran over 10 s);
# SECRET-LIKE:n, LAUNCH-SECRET-LIKE:n (strings that look like credentials; values never printed); LAUNCH-DEAD-PATH:n;
# SETTINGS*/LAUNCH: EMPTY|INVALID; LOCKFILES; MEM-FILE>5K:n, MEM-INDEX:nL (> 10 lines), MEM-INDEX-TRUNCATED;
# SKILL-SHADOWED (global skill wins), AGENT-OVERRIDES (project agent wins); *-TRACKED-PUBLIC
EOF
column -t -s $'\t' < "$T3"
cat <<EOF
#
# summary: $N folders, $NGIT git; dirty: $NDIRTY; AGENTS-NOT-LOADED: $NNOTLOADED; GENERIC: $NGENERIC; VISIBLE: $NVISIBLE;
#          NODE-MISSING: $NNODE; Node mismatch: $NMISMATCH; behind the Node standard: $NSTD; bad settings files: $NSETBAD;
#          with secret-like entries: $NSECRET; memory over budget: $NMEM
EOF
