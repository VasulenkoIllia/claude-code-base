#!/bin/bash
# dup-guard tests on temporary fixtures (a git repo and a project outside git); never on real projects.
# Run: bash hooks/dup-tests.sh -> expects "DUP OK". DUP_TESTS_SHOW=1 also prints every hook output.
H=$(cd "$(dirname "$0")" && pwd); f=0
T=$(mktemp -d "${TMPDIR:-/tmp}/dup-tests.XXXXXX") || exit 1
trap 'rm -rf "$T"' EXIT
export DUP_GUARD_ALLOW_TMP=1   # the fixtures live under $TMPDIR, which the hook skips by default
export DUP_GUARD_ERRLOG="$T/err.log"   # never the live ~/.claude/logs
PY=/opt/homebrew/bin/python3; [ -x "$PY" ] || PY=/usr/bin/python3
R="$T/repo"; N="$T/nogit"; I="$T/in"
mkdir -p "$I" "$R/server/lib" "$R/server/modules/users" "$R/server/modules/clients" "$R/server/modules/tasks" \
  "$R/server/modules/files" "$R/server/modules/vault" "$R/server/utils" "$R/src/shared/lib" "$R/src/__tests__" \
  "$R/tmp"

# ---------------------------------------------------------------- git fixture
echo '{"name":"fx","private":true}' > "$R/package.json"
echo 'tmp/' > "$R/.gitignore"
cat > "$R/server/lib/fields.ts" <<'EOF'
import { z } from 'zod';

// Shared zod field builders.
export const requiredId = (label: string) =>
  z.string({ message: label }).uuid(label);

export const trimmed = (max: number, required: string) =>
  z.string({ message: required }).trim().min(1, required).max(max, `Too long (${max})`);
EOF
cat > "$R/server/modules/users/users.schemas.ts" <<'EOF'
import { z } from 'zod';

const trimmed = (max: number, required: string) =>
  z.string({ message: required }).trim().min(1, required).max(max, `Too long (${max})`);

export const userSchema = z.object({ name: trimmed(80, 'Name required') });
EOF
cat > "$R/src/shared/lib/format.ts" <<'EOF'
export function isoDay(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
EOF
cat > "$R/server/modules/clients/clients.service.ts" <<'EOF'
const isoDay = (d: Date) => d.toISOString().slice(0, 10);

export class ClientsService {
  today() {
    return isoDay(new Date());
  }
}
EOF
cat > "$R/server/modules/tasks/tasks.service.ts" <<'EOF'
export function ownerNames(tasks: { owner: { name: string } }[]) {
  const nameOf = (u: { name: string }) => u.name.trim().toLowerCase();
  return tasks.map((t) => nameOf(t.owner));
}
EOF
for m in files vault; do
  cat > "$R/server/modules/$m/$m.names.ts" <<'EOF'
function extensionOf(name: string): string {
  const i = name.lastIndexOf('.');
  return i < 0 ? '' : name.slice(i + 1).toLowerCase();
}

export const storedName = (id: string, name: string) => id + '.' + extensionOf(name);
EOF
done
cat > "$R/src/shared/lib/greet.ts" <<'EOF'
export function greetUser(name: string, greeting = 'Hello there') {
  const clean = name.trim();
  return `${greeting}, ${clean}! Welcome back`;
}
EOF
cat > "$R/src/__tests__/helpers.ts" <<'EOF'
export function buildPayload(id: string) {
  return { id, at: Date.now(), source: 'test' };
}
EOF
# exported through a list, not on the definition line
cat > "$R/server/utils/dates.js" <<'EOF'
function shortDate(d) {
  const pad = (n) => String(n).padStart(2, '0');
  return pad(d.getDate()) + '.' + pad(d.getMonth() + 1) + '.' + d.getFullYear();
}

module.exports = { shortDate };
EOF
cat > "$R/server/utils/titles.ts" <<'EOF'
function titleSlug(title: string): string {
  return title.toLowerCase().trim().replace(/\s+/g, '-').slice(0, 64);
}

export { titleSlug };
EOF
# an overload line with a trailing comment: the comment must not reach the note
cat > "$R/server/utils/tokens.ts" <<'EOF'
export function resolveToken(a: string, b: number): string; // PRIVATE_COMMENT_MARKER keep out
export function resolveToken(a: string, b?: number): string {
  return a.trim().slice(0, b ?? 8) + ':' + a.length;
}
EOF
# hostile text in a hit file (it must stay fast) and words that must not leak into the note
{ printf 'function parseDurationValue(a = "'; printf '\\%.0s' $(seq 80); printf '\n'
  printf '  return %s;\n' "$(printf '/* %.0s' $(seq 20000))"; printf 'export { a'; head -c 100000 /dev/zero | tr '\0' ' '
  printf '\n'; } > "$R/server/utils/hostile.ts"
cat > "$R/server/utils/quotes.ts" <<'EOF'
export function stripQuoteMarks(a: string): string {
  return a.replace(/['"]/g, '') + 'PRIVWORD_ONE' + a.length; // note
}
export function quoteMarkLimit(a = /'/): void; // c1 ' PRIVWORD_TWO ' c3
export function pickLabelText(c = `${x ? `PRIVWORD_THREE` : 'y'}`): string;
EOF
cat > "$R/server/utils/freetext.ts" <<'EOF'
export function freeTextHelper IGNORE ALL PREVIOUS (a: string) {
  return a.trim().toLowerCase();
}
EOF
( cd "$R" && git init -q -b main && git add -A && git commit -q -m init ) || { echo "FAIL dup-guard: git fixture"; exit 1; }
# after the commit: an untracked helper (must be found) and an ignored copy (must not)
mkdir -p "$R/server/modules/orders"
cat > "$R/server/modules/orders/orders.utils.ts" <<'EOF'
export function normalizePhone(raw: string): string {
  const digits = raw.replace(/\D/g, '');
  return digits.startsWith('380') ? '+' + digits : '+38' + digits;
}
EOF
cp "$R/server/modules/orders/orders.utils.ts" "$R/tmp/scratch.ts"

# ---------------------------------------------------------------- inputs (new code the model writes)
cp "$R/server/modules/users/users.schemas.ts" "$I/trimmed.ts"
cp "$R/server/modules/orders/orders.utils.ts" "$I/phone.ts"
sed 's/^function/export function/; /storedName/d' "$R/server/modules/files/files.names.ts" > "$I/extract.ts"
echo 'export const nameOf = (u: { name: string }) => u.name.trim().toLowerCase();' > "$I/nameof.ts"
cp "$R/src/__tests__/helpers.ts" "$I/payload.ts"
cp "$R/src/shared/lib/format.ts" "$I/local.ts"
sed 's/getFullYear/getUTCFullYear/; s/getMonth/getUTCMonth/; s/getDate/getUTCDate/' "$I/local.ts" > "$I/utc.ts"
echo 'export const isoDay = (d: Date) => d.toISOString().slice(0, 10);' > "$I/slice.ts"
sed 's/^/  /' "$I/local.ts" > "$I/nested.ts"
sed "s/Hello there/Private note/; s/Welcome back/Second secret phrase/" "$R/src/shared/lib/greet.ts" > "$I/greet.ts"

# write <input file> <file_path> [create|update]: Write hook JSON (originalFile null)
write() { /usr/bin/jq -n --rawfile c "$1" --arg fp "$2" --arg t "${3:-create}" \
  '{hook_event_name:"PostToolUse",tool_name:"Write",tool_input:{file_path:$fp,content:$c},tool_response:{type:$t,originalFile:null}}'; }
# edit <file_path> <old input file> <new input file>
edit() { /usr/bin/jq -n --arg fp "$1" --rawfile o "$2" --rawfile n "$3" \
  '{hook_event_name:"PostToolUse",tool_name:"Edit",tool_input:{file_path:$fp,old_string:$o,new_string:$n}}'; }
size() { if [ -f "$1" ]; then wc -c <"$1" | tr -d ' '; else echo 0; fi; }
# run <json>: through the shim; an internal error (a new error-log line) fails every case that uses it
run() {
  local before; before=$(size "$DUP_GUARD_ERRLOG")
  out=$(printf '%s' "$1" | "$H/dup-guard.sh"); rc=$?; [ -z "$DUP_TESTS_SHOW" ] || printf '%s\n' "$out" >&2
  [ "$(size "$DUP_GUARD_ERRLOG")" = "$before" ] || { echo "FAIL dup-guard: internal error logged: $(tail -n 1 "$DUP_GUARD_ERRLOG")"; f=1; }
}
valid() {   # the only output shape: PostToolUse additionalContext that starts with "dup-guard:", <= 1200 B
  [ "$rc" -eq 0 ] && [ "$(printf '%s' "$out" | wc -c | tr -d ' ')" -le 1200 ] && printf '%s' "$out" | /usr/bin/jq -e \
    'keys == ["hookSpecificOutput"] and .hookSpecificOutput.hookEventName == "PostToolUse"
     and (.hookSpecificOutput.additionalContext | startswith("dup-guard:"))' >/dev/null 2>&1
}
# fires <case> <json> [text | !text]...: a valid note that has every text and none of the !texts
fires() {
  local name=$1 s; run "$2"; shift 2
  valid || { echo "FAIL dup-guard $name: expected a note, rc=$rc, $(printf '%s' "$out" | wc -c | tr -d ' ') B"; f=1; return; }
  for s in "$@"; do
    case $s in
      '!'*) [[ $out != *"${s#!}"* ]] || { echo "FAIL dup-guard $name: has '${s#!}'"; f=1; } ;;
      *) [[ $out == *"$s"* ]] || { echo "FAIL dup-guard $name: no '$s'"; f=1; } ;;
    esac
  done
}
quiet() { run "$2"; [ "$rc" -eq 0 ] && [ -z "$out" ] || { echo "FAIL dup-guard $1: expected silence, rc=$rc"; f=1; }; }
S="$R/server/modules"

# positives (wording: facts only, no "unused", literals masked)
fires trimmed "$(write "$I/trimmed.ts" "$S/products/products.schemas.ts")" 'server/lib/fields.ts:7 ' \
  'server/modules/users/users.schemas.ts:3 ' 'not exported' '!Too long' '!Name required' '!other part'
fires untracked "$(write "$I/phone.ts" "$S/clients/phone.ts")" 'server/modules/orders/orders.utils.ts:1 ' '!tmp/'
fires extraction "$(write "$I/extract.ts" "$R/server/lib/files.ts")" 'files/files.names.ts:1 ' \
  'vault/vault.names.ts:1 ' 'the listed copies stay in place for now' '!unused'
fires edit-adds "$(edit "$S/products/products.schemas.ts" /dev/null "$I/trimmed.ts")" 'server/lib/fields.ts:7 '
fires literals "$(write "$I/greet.ts" "$R/src/pages/home.tsx")" "greeting = '…'" '!Hello' '!Private' '!Welcome' \
  '!secret phrase'
# date trap: a helper from the other part is always marked, a getUTC* change is named
fires date-utc "$(write "$I/utc.ts" "$S/reports/reports.service.ts")" 'src/shared/lib/format.ts:1 ' \
  'other part: src/' 'getFullYear→getUTCFullYear'
fires date-local "$(write "$I/local.ts" "$S/reports/reports.service.ts")" 'src/shared/lib/format.ts:1 ' \
  'other part: src/'
fires date-slice-front "$(write "$I/slice.ts" "$R/src/modules/report/day.tsx")" \
  'server/modules/clients/clients.service.ts:1 ' 'not exported' 'other part: server/' '!format.ts'
fires date-slice-server "$(write "$I/slice.ts" "$S/reports/day.ts")" 'clients/clients.service.ts:1 ' \
  '!format.ts' '!other part'
# export through module.exports / export { }: not "not exported"; comments stay out of the signature
fires export-cjs "$(write "$R/server/utils/dates.js" "$R/src/api/dates.js")" 'server/utils/dates.js:1 ' \
  '!not exported'
fires export-list "$(write "$R/server/utils/titles.ts" "$R/src/api/titles.ts")" 'server/utils/titles.ts:1 ' \
  '!not exported'
fires comment-sig "$(write "$R/server/utils/tokens.ts" "$R/src/api/token.ts")" 'server/utils/tokens.ts:1 ' \
  'resolveToken(a: string, b: number): string;`' '!PRIVATE_COMMENT' '!keep out'
# literal words never leak: a /'"/ regex before a string, a quote in a regex before a comment, a nested template,
# free text after the name
sed 's/PRIVWORD_ONE/zzz_other/' "$R/server/utils/quotes.ts" > "$I/quotes.ts"
fires leaks "$(write "$I/quotes.ts" "$R/src/api/quotes.ts")" 'server/utils/quotes.ts:5 ' '!PRIVWORD'
fires free-text "$(write "$R/server/utils/freetext.ts" "$R/src/api/freetext.ts")" '`export function freeTextHelper …`' \
  '!IGNORE' '!PREVIOUS'
# hostile hit file: exponential and quadratic regex inputs end quickly
printf 'export function parseDurationValue(a = 1) {\n  return a;\n}\n' > "$I/hostile.ts"
t0=$("$PY" -I -c 'import time; print(int(time.time() * 1000))')
run "$(write "$I/hostile.ts" "$R/src/api/hostile.ts")"
ms=$(( $("$PY" -I -c 'import time; print(int(time.time() * 1000))') - t0 ))
[ "$rc" -eq 0 ] && [ "$ms" -lt 2000 ] || { echo "FAIL dup-guard hostile: rc=$rc, $ms ms (limit 2000)"; f=1; }
# "new file" only for a created file: an Edit of an existing shared file gets the plain tail
fires extraction-edit "$(edit "$R/server/lib/fields.ts" /dev/null "$I/extract.ts")" 'files/files.names.ts:1 ' \
  '!shared folder'

# negatives
quiet nested-hit "$(write "$I/nameof.ts" "$S/chat/chat.ts")"
quiet nested-new "$(edit "$S/reports/reports.service.ts" /dev/null "$I/nested.ts")"
quiet hit-in-tests "$(write "$I/payload.ts" "$R/src/api/payload.ts")"
quiet write-to-test "$(write "$I/local.ts" "$R/src/api/format.test.ts")"
quiet edit-existing "$(edit "$R/server/lib/fields.ts" "$I/trimmed.ts" "$I/trimmed.ts")"
quiet update-null-original "$(write "$I/trimmed.ts" "$S/users/users.schemas.ts" update)"
quiet claude-dir "$(write "$I/trimmed.ts" "$R/.claude/x.ts")"
quiet not-js "$(write "$I/trimmed.ts" "$S/users/notes.md")"
DUP_GUARD_ALLOW_TMP='' quiet tmp-skipped "$(write "$I/trimmed.ts" "$S/products/products.schemas.ts")"

# message size: many names with many copies stay <= 1200 B (valid() checks the size)
for k in 1 2 3 4; do
  d="$S/a-rather-long-module-name-for-the-size-test-$k/with/some/nested/folders/and/even/more/nested/folders/x"
  mkdir -p "$d"
  for n in alphaHelperValue betaHelperValue gammaHelperValue deltaHelperValue epsilonHelperValue; do
    printf 'function %s(input: string, limit: number): string {\n  return input.trim().slice(0, limit);\n}\n' "$n"
  done > "$d/copies.ts"
done
cp "$d/copies.ts" "$I/many.ts"
fires size "$(write "$I/many.ts" "$S/size/size.ts")" ' more)'

# fail open: odd input never breaks the call. dup-guard.py itself (not the shim, which always exits 0) must exit 0
# with empty stdout and stderr and log nothing; each input carries a real duplicate, so a missing guard shows up
silent() {
  local before; before=$(size "$DUP_GUARD_ERRLOG")
  out=$(printf '%s' "$2" 2>/dev/null | "$PY" -I "$H/dup-guard.py" 2>"$T/stderr"); rc=$?   # big input: EPIPE
  [ "$rc" -eq 0 ] && [ -z "$out" ] && [ ! -s "$T/stderr" ] && [ "$(size "$DUP_GUARD_ERRLOG")" = "$before" ] ||
    { echo "FAIL dup-guard $1: expected silence, rc=$rc, stderr $(size "$T/stderr") B, error log $before -> $(size "$DUP_GUARD_ERRLOG") B"; f=1; }
}
TRIM=$(/usr/bin/jq -Rs . <"$I/trimmed.ts")   # the duplicate as a JSON string
silent empty ''
silent not-json 'not json'
silent array '[]'
silent path-number '{"tool_name":"Write","tool_input":{"file_path":123,"content":'"$TRIM"'}}'
silent input-list '{"tool_name":"Write","tool_input":["'"$S"'/p/p.ts"]}'
silent no-such-dir "$(write "$I/trimmed.ts" /nonexistent/dir/x.ts)"
silent other-tool '{"tool_name":"Read","tool_input":{"file_path":"'"$S"'/p/p.ts","content":'"$TRIM"'}}'
{ cat "$I/trimmed.ts"; head -c 500000 /dev/zero | tr '\0' ' '; } > "$I/big500k.ts"
silent big-500k "$(write "$I/big500k.ts" "$S/products/products.schemas.ts")"
{ cat "$I/trimmed.ts"; head -c 3000000 /dev/zero | tr '\0' ' '; } > "$I/big3mb.ts"
silent big-3mb "$(write "$I/big3mb.ts" "$S/products/products.schemas.ts")"
# odd but usable input still gets its note: invalid UTF-8 in a comment, junk entries in a MultiEdit
printf '// note BADBYTES\n' > "$I/utf.ts"; cat "$I/trimmed.ts" >> "$I/utf.ts"
fires bad-utf8 "$(write "$I/utf.ts" "$S/products/products.schemas.ts" | LC_ALL=C sed "s/BADBYTES/$(printf '\377\376')/")" \
  'server/lib/fields.ts:7 '
fires multiedit-junk '{"tool_name":"MultiEdit","tool_input":{"file_path":"'"$S"'/m/m.ts","edits":[1,null,"x",{"old_string":"","new_string":'"$TRIM"'}]}}' \
  'server/lib/fields.ts:7 '
# an internal error (git cannot read the tree) stays silent for the session and leaves one line in the error log
before=$(size "$DUP_GUARD_ERRLOG")
out=$(write "$I/trimmed.ts" "$S/products/products.schemas.ts" | DUP_GUARD_TREE=deadbeef0 "$PY" -I "$H/dup-guard.py" 2>"$T/stderr"); rc=$?
[ "$rc" -eq 0 ] && [ -z "$out" ] && [ ! -s "$T/stderr" ] && [ "$(size "$DUP_GUARD_ERRLOG")" -gt "$before" ] &&
  tail -n 1 "$DUP_GUARD_ERRLOG" | grep -Eq '^[0-9T:-]+Z HookError git grep rc=[0-9]+ *$' ||
  { echo "FAIL dup-guard error-log: rc=$rc, stderr $(size "$T/stderr") B, log $(tail -n 1 "$DUP_GUARD_ERRLOG" 2>/dev/null)"; f=1; }
# a full log (over 64 KB) moves to .1 and starts again with the new line
head -c 64100 /dev/zero | tr '\0' x > "$DUP_GUARD_ERRLOG"
write "$I/trimmed.ts" "$S/products/products.schemas.ts" | DUP_GUARD_TREE=deadbeef0 "$PY" -I "$H/dup-guard.py" 2>/dev/null
[ "$(size "$DUP_GUARD_ERRLOG.1")" = 64100 ] && [ "$(wc -l <"$DUP_GUARD_ERRLOG" | tr -d ' ')" = 1 ] ||
  { echo "FAIL dup-guard error-log-rotate: .1 $(size "$DUP_GUARD_ERRLOG.1") B, log $(size "$DUP_GUARD_ERRLOG") B"; f=1; }
# a missing dup_guard_lib.py (broken install) is logged too, not only silent
B="$T/broken-hook"; mkdir -p "$B"; cp "$H/dup-guard.py" "$B/"
before=$(size "$DUP_GUARD_ERRLOG")
out=$(write "$I/trimmed.ts" "$S/products/products.schemas.ts" | "$PY" -I "$B/dup-guard.py" 2>"$T/stderr"); rc=$?
[ "$rc" -eq 0 ] && [ -z "$out" ] && [ ! -s "$T/stderr" ] && tail -n 1 "$DUP_GUARD_ERRLOG" | grep -q ' ModuleNotFoundError' &&
  [ "$(size "$DUP_GUARD_ERRLOG")" -gt "$before" ] ||
  { echo "FAIL dup-guard missing-lib: rc=$rc, stderr $(size "$T/stderr") B, log $(tail -n 1 "$DUP_GUARD_ERRLOG" 2>/dev/null)"; f=1; }
silent content-number '{"tool_name":"Write","tool_input":{"file_path":"'"$S"'/p/p.ts","content":123}}'
# a broken git (rc 1 with stderr, as xcrun after a macOS update) is an internal error, not "no repo"
printf '#!/bin/bash\necho "xcrun: error: invalid active developer path" >&2\nexit 1\n' > "$T/git-stub"; chmod +x "$T/git-stub"
# macOS checks a new executable on its first run, 0.05-2.0 s, and a later run from any process takes 3-4 ms: that
# first run stays out of the hook's 1.0 s git timer
"$T/git-stub" 2>/dev/null
before=$(size "$DUP_GUARD_ERRLOG")
out=$(write "$I/trimmed.ts" "$S/products/products.schemas.ts" | DUP_GUARD_GIT="$T/git-stub" "$PY" -I "$H/dup-guard.py" 2>"$T/stderr")
[ -z "$out" ] && [ ! -s "$T/stderr" ] && tail -n 1 "$DUP_GUARD_ERRLOG" | grep -q ' HookError git rev-parse rc=1' ||
  { echo "FAIL dup-guard broken-git: log $(tail -n 1 "$DUP_GUARD_ERRLOG" 2>/dev/null)"; f=1; }
# python that dies (here: exit 3) is logged by the shim, which still exits 0
B2="$T/dead-python"; mkdir -p "$B2"; cp "$H/dup-guard.sh" "$B2/"; printf 'import sys\nsys.exit(3)\n' > "$B2/dup-guard.py"
write "$I/trimmed.ts" "$S/products/products.schemas.ts" | "$B2/dup-guard.sh"; rc=$?
[ "$rc" -eq 0 ] && tail -n 1 "$DUP_GUARD_ERRLOG" | grep -q ' ShimExit 3$' ||
  { echo "FAIL dup-guard shim-exit: rc=$rc, log $(tail -n 1 "$DUP_GUARD_ERRLOG" 2>/dev/null)"; f=1; }
# the default log path, the one doctor.sh reads: ~/.claude/logs/dup-guard.err
write "$I/trimmed.ts" "$S/products/products.schemas.ts" |
  env -u DUP_GUARD_ERRLOG HOME="$T/home" DUP_GUARD_TREE=deadbeef0 "$PY" -I "$H/dup-guard.py" 2>/dev/null
grep -q ' HookError git grep rc=' "$T/home/.claude/logs/dup-guard.err" 2>/dev/null ||
  { echo "FAIL dup-guard default-log-path: nothing in ~/.claude/logs/dup-guard.err"; f=1; }

# ---------------------------------------------------------------- outside git: >= 5000 files in node_modules
mkdir -p "$N/src/text" "$N/dist" "$N/build"
echo '{"name":"nogit","private":true}' > "$N/package.json"
cat > "$N/src/text/slug.ts" <<'EOF'
export function slugify(title: string): string {
  return title.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}
EOF
cp "$N/src/text/slug.ts" "$N/dist/slug.js"; cp "$N/src/text/slug.ts" "$N/build/slug.js"
( cd "$N" && mkdir -p node_modules/p{1..500} ) || exit 1
body=$(cat "$N/src/text/slug.ts")   # copies everywhere: walking node_modules would cost time, not just stat calls
for i in $(seq 500); do for j in 0 1 2 3 4 5 6 7 8 9; do printf '%s\n' "$body" > "$N/node_modules/p$i/f$j.js"; done; done
nm=$(find "$N/node_modules" -type f | wc -l | tr -d ' ')
[ "$nm" -ge 5000 ] || { echo "FAIL dup-guard nogit: only $nm files in node_modules"; f=1; }
write "$N/src/text/slug.ts" "$N/src/pages/slug2.ts" > "$T/nogit.json"
fires nogit "$(cat "$T/nogit.json")" 'src/text/slug.ts:1 ' '!node_modules' '!dist/' '!build/'
# a project outside HOME whose path is shorter than HOME still gets its root
HOME="/nonexistent/$(printf '%0600d' 0)" fires nogit-long-home "$(cat "$T/nogit.json")" 'src/text/slug.ts:1 '
# median of 5 runs; a busy machine gets up to 3 rounds and the best one counts
best=999
for _ in 1 2 3; do
  ms=$("$PY" -I -c 'import subprocess, sys, time
data, t = open(sys.argv[2], "rb").read(), []
for _ in range(5):
    s = time.perf_counter(); subprocess.run([sys.argv[1]], input=data, capture_output=True)
    t.append((time.perf_counter() - s) * 1000)
print(int(sorted(t)[2]))' "$H/dup-guard.sh" "$T/nogit.json")
  [ "${ms:-999}" -ge "$best" ] || best=$ms
  [ "$best" -ge 150 ] || break
done
[ "$best" -lt 150 ] || { echo "FAIL dup-guard nogit latency: best median $best ms, limit 150"; f=1; }
[ -z "$DUP_TESTS_SHOW" ] || echo "nogit best median ${best} ms (5 runs per round), $nm files in node_modules" >&2

[ $f -eq 0 ] && echo "DUP OK"; exit $f
