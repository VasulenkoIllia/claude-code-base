#!/usr/bin/env python3
"""edit-replay: run real Edit/Write/MultiEdit calls on JS/TS files from Claude Code transcripts through dup-guard.

Usage (from the repo root): python3 -I tests/edit-replay.py [--days 60] [--hook PATH] [--include-audit] [--jobs N]
[--dump]. --hook defaults to <repo>/hooks/dup-guard.sh (the shim; it starts dup-guard.py next to it).

Historical mode: each call goes to the hook as PostToolUse stdin JSON with DUP_GUARD_TREE = the last commit (any
ref) before the call, so the hook searches the repo as it was then. Calls outside git or before the first commit
are skipped (counted); files that were uncommitted at that moment are not seen (hooks/dup-tests.sh covers that).
Hook calls run one at a time, so the latency is the real one.

Safety: transcripts and projects are only read (git rev-parse, rev-list, show; GIT_OPTIONAL_LOCKS=0; the hook gets
the commit tree, never the working tree). Output is counts only; --dump writes the raw notes (client code signatures)
to research/replay-cache/ (gitignored, 0600). Sessions of this repo and /tmp are skipped unless --include-audit.

Gate (exit code 0 = PASS, 1 = FAIL, 2 = usage or setup error), owner's plan B5 item A:
  a control call (a known duplicate in a temp git repo) fires first, so a broken hook cannot pass as "silent"; at
  least 200 calls run and at least 1 fires; 0 hook errors and timeouts (stderr, a non-zero exit, a line in the hook's
  error log: DUP_GUARD_ERRLOG points at a temp file); p95 <= 100 ms; firings <= 2.5% of the calls run; every printed
  JSON <= 1200 B; 0 misleading notes without a visible hint: a hit in another top-level part without "other part:
  X/", "not exported" missing for a helper the file does not export or present for one it does (export list,
  export default, CommonJS), an order or "unused" in the text, a string literal in a signature; 0 hit lines
  this check cannot parse or read. Every firing that an earlier run did not have is reviewed by hand (--dump) before a
  release. Reference run and runtime (about 2.5 min): CHANGELOG v2026.10.9.
"""
import argparse
import collections
import datetime
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I drops the script folder from sys.path
from replay_common import (HOME, REPO, blocks, list_files, local_date, pct, records, sha, short,  # noqa: E402
                           window_start, write_dump)

TOOLS = ('Edit', 'Write', 'MultiEdit')
EXT_RE = re.compile(r'\.(ts|tsx|js|jsx|mjs|cjs)$')
TIMEOUT = 5.0              # as in settings.json
GATE_P95_MS, GATE_RATE, GATE_BYTES, GATE_MIN_RAN = 100, 0.025, 1200, 200
SHARED_TOP = {'shared', 'common', 'lib', 'libs', 'packages', 'core', 'utils', 'types'}
HIT_RE = re.compile(r'^- (?P<label>[^:\n]+): (?P<path>.+?):(?P<line>\d+) `(?P<sig>[^`]*)` \((?P<notes>[^\n]*)\)$', re.M)
SIMILAR_RE = re.compile(r'\(similar name ([^)\s]+)\)')
MORE_RE = re.compile(r'\n\(\d+ more\)\n')
CONTROL = ("export function normalizePhoneNumber(raw: string): string {\n  const digits = raw.replace(/\\D/g, '');\n"
           "  return digits.startsWith('380') ? '+' + digits : '+38' + digits;\n}\n")
# orders and claims the hook cannot check; matched in the hook's own words only (not in names or signatures)
ORDER_RE = re.compile(r'\b(unused|use[ds]?|using|reus\w*|remov\w*|replac\w*|delet\w*|import\w*|explain\w*|consider\w*'
                      r'|prefer\w*|instead|avoid\w*|should|must|needs?|worth)\b', re.I)

# ---------------------------------------------------------------- extraction (read-only, in worker processes)


def edit_line(line):
    """A line that may hold an Edit/Write/MultiEdit call or a result."""
    return ('"tool_use"' in line and any('"%s"' % t in line for t in TOOLS)) or '"tool_result"' in line


def calls_in(d, proj):
    """{tool_use id: call} for the Edit/Write/MultiEdit blocks on JS/TS files of one assistant record."""
    out, ts = {}, d['timestamp']
    for b in blocks(d, 'tool_use'):
        inp = b.get('input') if b.get('name') in TOOLS else None
        fp = inp.get('file_path') if isinstance(inp, dict) else None
        if isinstance(fp, str) and EXT_RE.search(fp) and b.get('id'):
            out[b['id']] = {'id': b['id'], 'proj': proj, 'tool': b['name'], 'file_path': fp, 'ts': ts,
                            'date': local_date(ts), 'input': inp, 'sidechain': bool(d.get('isSidechain'))}
    return out


def results_in(d, calls):
    """{tool_use id: (is_error, Write type, Write originalFile, has Write fields)} for known calls of one record."""
    tur, out = d.get('toolUseResult'), {}
    for b in blocks(d, 'tool_result'):
        tid = b.get('tool_use_id')
        if tid in calls:
            w = isinstance(tur, dict) and calls[tid]['tool'] == 'Write' and 'originalFile' in tur
            out[tid] = (bool(b.get('is_error')), tur.get('type') if w else None,
                        tur.get('originalFile') if w else None, w)
    return out


def extract_file(job):
    """(calls, results, bad_lines) of one transcript file; see calls_in() and results_in()."""
    proj, path, cutoff = job
    calls, results, n = {}, {}, collections.Counter()
    try:
        fh = open(path, 'r', encoding='utf-8', errors='replace')
    except OSError:
        return [], {}, 1
    with fh:
        for d in records(fh, n, edit_line):
            if d['timestamp'][:19] >= cutoff:
                calls.update(calls_in(d, proj))
            results.update(results_in(d, calls))
    return list(calls.values()), results, n['bad']


def extract(files, cutoff, jobs):
    """Calls deduplicated by tool_use id (resumed sessions repeat history), with their results joined."""
    calls, results, bad = {}, {}, 0
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        for cs, rs, b in ex.map(extract_file, [(p, f, cutoff) for p, f in files], chunksize=4):
            bad += b
            for c in cs:
                calls.setdefault(c['id'], c)
            for k, r in rs.items():
                if k not in results or (r[3] and not results[k][3]):
                    results[k] = r
    rows = sorted(calls.values(), key=lambda c: c['ts'])
    for c in rows:
        c['result'] = results.get(c['id'])
    return rows, bad

# ---------------------------------------------------------------- git (read-only) and hook runs


def git(args, cwd, isolated=False):
    """isolated (the control repo): no global or system git config, so no user hooks, templates or signing."""
    env = {'PATH': '/usr/bin:/bin', 'GIT_OPTIONAL_LOCKS': '0', 'LC_ALL': 'C', 'HOME': HOME}
    env.update({'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'} if isolated else {})
    p = subprocess.run(['git', '-c', 'core.quotePath=false'] + args, cwd=cwd, capture_output=True, timeout=20, env=env)
    return p.returncode, p.stdout.decode('utf-8', 'replace')


class Repos:
    def __init__(self):
        self.roots, self.commits, self.files = {}, {}, {}

    def root(self, fp):
        d = os.path.dirname(fp)
        while d and not os.path.isdir(d):
            d = os.path.dirname(d)
        if d not in self.roots:
            rc, out = git(['rev-parse', '--show-toplevel'], d) if d and d != '/' else (1, '')
            self.roots[d] = out.strip() if rc == 0 and out.strip() else None
        return self.roots[d]

    def commit_before(self, root, ts):
        k = (root, ts[:16])
        if k not in self.commits:
            rc, out = git(['rev-list', '-1', '--all', '--before=' + ts], root)
            self.commits[k] = out.strip() if rc == 0 else ''
        return self.commits[k]

    def line(self, root, commit, path, n):
        k = (root, commit, path)
        if k not in self.files:
            rc, out = git(['show', '%s:%s' % (commit, path)], root)
            self.files[k] = out.splitlines() if rc == 0 else []
        lines = self.files[k]
        return lines[n - 1] if 0 < n <= len(lines) else None

    def exports(self, root, commit, path, name):
        """The file exports name apart from its definition line (read by line() first)."""
        text, n = '\n'.join(self.files.get((root, commit, path)) or []), re.escape(name)
        return any(re.search(p % n, text) for p in (
            r'\bexport\s*\{[^}]*\b%s\b', r'\bexport\s+default\s+%s\b', r'\bmodule\.exports\s*=\s*\{[^}]*\b%s\b',
            r'\bmodule\.exports\s*=\s*%s\b', r'\bexports\.%s\s*='))


def part(path):
    s = path.split('/')
    if s[0] in ('apps', 'packages', 'services') and len(s) > 2:
        return s[0] + '/' + s[1]
    return s[0] if len(s) > 1 else '.'


def misleading(text, rel, root, commit, repos):
    """Counter of notes that point at a helper without the visible hint (see the module docstring)."""
    bad = collections.Counter()
    own = re.sub(r'^dup-guard: .*? adds .*?;', 'dup-guard:', HIT_RE.sub('', text))
    if ORDER_RE.search(own):
        bad['wording'] += 1
    bad['unchecked'] += sum(1 for ln in text.splitlines() if ln.startswith('- ')) - len(HIT_RE.findall(text))
    for m in HIT_RE.finditer(text):
        path, notes = m.group('path'), m.group('notes')
        if re.search(r'[\'"`]', m.group('sig').replace("'…'", '')):
            bad['literal'] += 1
        theirs = part(path)
        if theirs not in (part(rel), '.') and theirs.split('/')[0] not in SHARED_TOP \
                and 'other part: %s/' % theirs not in notes:
            bad['part'] += 1
        src = repos.line(root, commit, path, int(m.group('line')))
        if src is None:
            bad['unread'] += 1
            continue
        similar = SIMILAR_RE.search(m.group('label'))
        name = similar.group(1) if similar else m.group('label').strip()
        exported = bool(re.match(r'export\b', src)) or repos.exports(root, commit, path, name)
        if exported == ('not exported' in notes):
            bad['export'] += 1
    return bad


def run_hook(hook, call, commit, errlog, extra_env=None):
    """(kind, (text, bytes) or None, ms). kind: fired, silent, error (stderr, exit code, a new error log line,
    a bad JSON shape) or timeout."""
    inp = {'session_id': 'edit-replay', 'hook_event_name': 'PostToolUse', 'tool_name': call['tool'],
           'tool_input': call['input'], 'tool_use_id': call['id']}
    r = call['result']
    if call['tool'] == 'Write' and r and r[3]:
        inp['tool_response'] = {'type': r[1], 'originalFile': r[2]}   # else the hook reads the file at the commit
    env = dict({'PATH': '/usr/bin:/bin', 'HOME': HOME, 'DUP_GUARD_TREE': commit, 'DUP_GUARD_ERRLOG': errlog},
               **(extra_env or {}))
    logged = os.path.getsize(errlog) if os.path.isfile(errlog) else 0
    t = time.perf_counter()
    try:
        p = subprocess.run(['/bin/bash', hook], input=json.dumps(inp, ensure_ascii=False).encode('utf-8'),
                           capture_output=True, timeout=TIMEOUT, env=env, cwd='/')
    except subprocess.TimeoutExpired:
        return 'timeout', None, (time.perf_counter() - t) * 1000
    ms = (time.perf_counter() - t) * 1000
    out = p.stdout.strip()
    if p.returncode != 0 or p.stderr.strip() or (os.path.getsize(errlog) if os.path.isfile(errlog) else 0) > logged:
        return 'error', None, ms
    if not out:
        return 'silent', None, ms
    try:
        o = json.loads(out)
        hso = o['hookSpecificOutput']
        text = hso['additionalContext']
        ok = list(o) == ['hookSpecificOutput'] and hso.get('hookEventName') == 'PostToolUse' \
            and set(hso) == {'hookEventName', 'additionalContext'} and text.startswith('dup-guard:')
    except (ValueError, KeyError, TypeError, AttributeError):
        ok = False
    return ('fired', (text, len(out)), ms) if ok else ('error', None, ms)


def die(msg):
    print('edit-replay: ' + msg, file=sys.stderr)
    sys.exit(2)


def control_call(hook, errlog):
    """A known duplicate in a temp git repo must fire: a hook that broke inside stays silent, not failed."""
    with tempfile.TemporaryDirectory(prefix='edit-replay-control.') as d:
        os.makedirs(os.path.join(d, 'src', 'lib'))
        with open(os.path.join(d, 'src', 'lib', 'phone.ts'), 'w', encoding='utf-8') as fh:
            fh.write(CONTROL)
        user = ['-c', 'user.name=edit-replay', '-c', 'user.email=edit-replay@localhost.invalid', '-c', 'core.hooksPath=']
        steps = (['init', '-q', '--template='], ['add', '-A'], user + ['commit', '-q', '--no-verify', '-m', 'control'])
        if any(git(args, d, isolated=True)[0] for args in steps):
            die('control repo: git setup failed')
        commit = git(['rev-parse', 'HEAD'], d)[1].strip()
        call = {'id': 'control', 'tool': 'Write', 'result': (False, 'create', None, True),
                'input': {'file_path': os.path.join(d, 'src', 'api', 'phone.ts'), 'content': CONTROL}}
        kind, note, _ = run_hook(hook, call, commit, errlog, {'DUP_GUARD_ALLOW_TMP': '1'})
    return kind == 'fired' and 'src/lib/phone.ts:1 ' in note[0], kind


def replay(rows, hook, dump, errlog):
    """Run the calls one at a time; skipped calls are counted. Returns the counters for report()."""
    repos, st = Repos(), {'skip': collections.Counter(), 'res': collections.Counter(), 'times': [], 'sizes': [],
                          'per_day': collections.Counter(), 'marks': collections.Counter(),
                          'bad': collections.Counter(), 'dumps': []}
    for c in rows:
        if c['result'] and c['result'][0]:
            st['skip']['tool error'] += 1
            continue
        root = repos.root(c['file_path'])
        commit = repos.commit_before(root, c['ts']) if root else ''
        if not commit:
            st['skip']['outside git' if not root else 'no commit before the call'] += 1
            continue
        kind, note, ms = run_hook(hook, c, commit, errlog)
        st['res'][kind] += 1
        st['times'].append(ms)
        if kind != 'fired':
            continue
        text, size = note
        st['sizes'].append(size)
        st['per_day'][c['date']] += 1
        st['res']['fired ' + c['tool']] += 1
        st['res']['fired by subagents'] += c['sidechain']
        for label, needle in (('other part', 'other part:'), ('not exported', 'not exported'),
                              ('differs', 'differs:'), ('extraction', 'shared folder')):
            st['marks'][label] += needle in text
        st['marks']['more lines'] += bool(MORE_RE.search(text))
        rel = os.path.relpath(os.path.realpath(c['file_path']), os.path.realpath(root))
        st['bad'].update(misleading(text, rel, root, commit, repos))
        if dump:
            st['dumps'].append({'id': c['id'], 'date': c['date'], 'proj': c['proj'], 'tool': c['tool'],
                                'file_path': c['file_path'], 'sidechain': c['sidechain'], 'commit': commit,
                                'ms': round(ms, 1), 'note': text})
    return st


def report(ctx, rows, st):
    """Print the counts and the gate line; True when the gate passes."""
    res, times, sizes, bad = st['res'], st['times'], st['sizes'], st['bad']
    ran, fired = sum(res[k] for k in ('fired', 'silent', 'error', 'timeout')), res['fired']
    dates = collections.Counter(c['date'] for c in rows)
    tools = collections.Counter(c['tool'] for c in rows)
    print('== dup-guard edits: %d days (%s .. %s), historical mode%s' % (
        ctx['days'], ctx['since'], ctx['today'], '' if ctx['include_audit'] else ', audit sessions skipped'))
    print('hook  %s  sha256:%s; dup-guard.py sha256:%s; dup_guard_lib.py sha256:%s' % (
        short(ctx['hook']), sha(ctx['hook']), sha(ctx['py']), sha(ctx['lib'])))
    print('control  known duplicate in a temp repo: %s' % ('fired' if ctx['control'][0] else
                                                          'NOT FIRED (%s): the hook is broken' % ctx['control'][1]))
    print('corpus  %d calls (%s; subagents %d), %d projects, %d working days, %d files read, %d audit files '
          'skipped, %d unreadable lines' % (len(rows), ', '.join('%s %d' % kv for kv in sorted(tools.items())),
                                            sum(c['sidechain'] for c in rows), len({c['proj'] for c in rows}),
                                            len(dates), ctx['files'], ctx['audit_skipped'], ctx['bad_lines']))
    print('skipped  %s' % (', '.join('%s %d' % kv for kv in sorted(st['skip'].items())) or 'none'))
    print('ran  %d calls: fired %d (%.1f%%), silent %d, errors %d, timeouts %d' % (
        ran, fired, 100.0 * fired / ran if ran else 0, res['silent'], res['error'], res['timeout']))
    if times:
        print('time  median %.0f ms, p95 %.0f ms, p99 %.0f ms, max %.0f ms' % (
            statistics.median(times), pct(times, .95), pct(times, .99), max(times)))
    day_counts = [st['per_day'][d] for d in dates]
    print('firings  by tool: Write %d, Edit %d, MultiEdit %d; by subagents %d; per working day median %.1f, '
          'p90 %d, max %d; days with firings %d of %d' % (
              res['fired Write'], res['fired Edit'], res['fired MultiEdit'], res['fired by subagents'],
              statistics.median(day_counts) if day_counts else 0, pct(day_counts, .9),
              max(day_counts) if day_counts else 0, len(st['per_day']), len(dates)))
    print('notes  %s; JSON median %d B, max %d B' % (', '.join('%s %d' % (k, st['marks'][k]) for k in (
        'other part', 'not exported', 'differs', 'more lines', 'extraction')),
        statistics.median(sizes) if sizes else 0, max(sizes) if sizes else 0))
    n_bad = sum(bad.values())
    print('misleading without a hint  %d (%s; hit lines this check cannot parse %d or read %d)' % (n_bad, ', '.join(
        '%s %d' % (k, bad[k]) for k in ('part', 'export', 'wording', 'literal')), bad['unchecked'], bad['unread']))
    p95, max_b, errs = pct(times, .95), max(sizes) if sizes else 0, res['error'] + res['timeout']
    rate = float(fired) / ran if ran else 0.0
    checks = {'control': ctx['control'][0], 'ran': ran >= GATE_MIN_RAN, 'fired': fired >= 1, 'errors': errs == 0,
              'p95': p95 <= GATE_P95_MS, 'firings': rate <= GATE_RATE, 'size': max_b <= GATE_BYTES, 'misleading': n_bad == 0}
    ok = all(checks.values())
    print('wall  extract %.1f s, replay %.1f s' % ctx['wall'])
    print('gate  control %s; ran %d (>=%d), fired %d (>=1); errors/timeouts %d; p95 %.0f ms (<=%d); firings %.1f%% '
          '(<=%.1f%%); max message %d B (<=%d); misleading without a hint %d -> %s' % (
              'ok' if ctx['control'][0] else 'FAIL', ran, GATE_MIN_RAN, fired, errs, p95, GATE_P95_MS, 100 * rate,
              100 * GATE_RATE, max_b, GATE_BYTES, n_bad, 'PASS' if ok else 'FAIL: ' + ', '.join(k for k, v in checks.items() if not v)))
    return ok


def main():
    ap = argparse.ArgumentParser(description='Replay real JS/TS edits through dup-guard (historical mode).')
    ap.add_argument('--days', type=int, default=60, help='look back N days (default 60)')
    ap.add_argument('--hook', default=os.path.join(REPO, 'hooks', 'dup-guard.sh'), help='dup-guard shim')
    ap.add_argument('--include-audit', action='store_true', help='also replay sessions of this repo and /tmp')
    ap.add_argument('--jobs', type=int, default=min(8, os.cpu_count() or 4), help='workers for reading transcripts')
    ap.add_argument('--dump', action='store_true',
                    help='also write the notes (raw) to research/replay-cache/ (gitignored, 0600) for review')
    a = ap.parse_args()
    if a.days < 1 or a.jobs < 1:
        ap.error('--days and --jobs must be positive')
    hook = os.path.abspath(os.path.expanduser(a.hook))
    py = os.path.join(os.path.dirname(hook), 'dup-guard.py')
    lib = os.path.join(os.path.dirname(hook), 'dup_guard_lib.py')
    if not (os.path.isfile(hook) and os.path.isfile(py) and os.path.isfile(lib)):
        die('hook not found: %s (and dup-guard.py, dup_guard_lib.py next to it)' % hook)
    t0 = time.perf_counter()
    cutoff_epoch, cutoff = window_start(a.days)
    files, audit_skipped = list_files(cutoff_epoch, a.include_audit)
    print('[edits] reading %d transcript files ...' % len(files), file=sys.stderr, flush=True)
    rows, bad_lines = extract(files, cutoff, a.jobs)
    t1 = time.perf_counter()
    print('[edits] replaying %d calls one at a time ...' % len(rows), file=sys.stderr, flush=True)
    with tempfile.TemporaryDirectory(prefix='edit-replay.') as tmp:
        errlog = os.path.join(tmp, 'dup-guard.err')   # the hook's error channel, never the live log
        control = control_call(hook, errlog)
        st = replay(rows, hook, a.dump, errlog)
    today = datetime.date.today()
    ctx = {'days': a.days, 'since': today - datetime.timedelta(days=a.days), 'today': today, 'hook': hook, 'py': py,
           'lib': lib, 'include_audit': a.include_audit, 'files': len(files), 'audit_skipped': audit_skipped,
           'bad_lines': bad_lines, 'wall': (t1 - t0, time.perf_counter() - t1), 'control': control}
    if a.dump:
        write_dump('edits', st['dumps'], 'notes')
    return 0 if report(ctx, rows, st) else 1


if __name__ == '__main__':
    sys.exit(main())
