#!/usr/bin/env python3
"""commit-replay: run real git commit calls from Claude Code transcripts through doc-reminder and count reminders.

Usage (from the repo root): python3 -I tests/commit-replay.py [--days 60] [--hook PATH] [--include-audit] [--jobs N]
[--fast N] [--dump]. --hook defaults to <repo>/hooks/doc-reminder.sh (the shim; it starts doc-reminder.py).

Historical mode: every Bash call whose command has "git" and "commit" (main sessions and subagents) goes to the hook
as stdin JSON, PostToolUse or PostToolUseFailure (an error result), with its cwd, duration_ms = result time - call
time and DOC_REMINDER_NOW = result time, so the hook finds that call's commits in the reflog as it is on disk (entries
expire after 90 days). DOC_REMINDER_DOCS_MTIME = the time of the last write under docs/ or _internal/ earlier in the
same session, 0 for none: an Edit, Write, MultiEdit or NotebookEdit without an error, or a Bash command (a > redirect
there; cp, mv, tee, rsync, install or sed -i with such a path in the same part of the command), not counting a write
of only the working log (is_log of doc_reminder_lib.py next to the hook: STATUS, progress, plans, decisions...), as
the hook does; the hook compares it with the previous commit as it compares the files' times live. The report counts
the calls whose newest docs write was the log. A call whose cwd is gone (a removed worktree) is skipped and counted.
So is a call the hook found no commit for when its window closes before the first entry of the HEAD reflog of its
cwd's repo: the call's own entry went with an old .git or expired, nothing the hook can find. Only cwd's repo is
checked, not the cd and git -C targets the hook also searches, so a call that commits elsewhere may go too; with no
reflog to read a call stays counted. Hook calls run one at a time: the latency is the real one. --fast N: also N other
Bash calls through the shim.

Safety: transcripts and projects are only read (git rev-parse, log, diff-tree, ls-files and the reflog file;
GIT_OPTIONAL_LOCKS=0). Commands are never executed: they only reach the hook as stdin JSON. Output is counts; --dump
writes every commit call with its outcome and reminder (client file paths) to research/replay-cache/ (gitignored,
0600). Sessions of this repo and /tmp are skipped unless --include-audit.

Gate (exit 0 = PASS, 1 = FAIL, 2 = usage or setup error, no transcripts or no commit calls): a control commit in a
temp repo fires and a docs commit there is silent for that reason, with no error-log line, only a call whose window
closes before that repo's first reflog entry counts as older than the reflog, and a new worktree's reflog is read; at
least 100 commits found, one reminder or more, a commit found for at least 80% of the calls that reach the hook,
without those older than the reflog; 0 errors and timeouts (a non-zero exit, an error line on stderr or in the hook's
error log, whose lines are printed, an odd-input reason); every JSON valid and <= 1200 B; at least 500 fast calls, none
with output, p95 <= 50 ms. Firing rates: reported only.
"""
import argparse
import collections
import datetime
import importlib.util
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
from replay_common import (REPO, blocks, list_files, local_date, log_lines, pct, proj_name, records,  # noqa: E402
                           run_hook, sha, short, size, window_start, write_dump)

TIMEOUT = 5.0   # as in settings.json
SLACK_S = 5     # as in the hook: its window closes that long after the call
GATE_BYTES, GATE_FAST_P95_MS = 1200, 50
GATE_MIN_COMMITS, GATE_MIN_FOUND, GATE_MIN_FAST = 100, 0.8, 500
EDIT_TOOLS = ('Edit', 'Write', 'MultiEdit', 'NotebookEdit')
DOCS_PATH_RE = re.compile(r'(^|[\s/\'"=])(docs|_internal)/')
DOC_TOKEN_RE = re.compile(r'[^\s\'"<>|;&()]*(?:docs|_internal)/[^\s\'"<>|;&()]*')
DOC_REL_RE = re.compile(r'(?:^|/)((?:docs|_internal)/.*)$')
WRITE_VERB_RE = re.compile(r'(^|\s)(cp|mv|tee|rsync|install)\s|\bsed\s+(-[a-zA-Z]*\s+)*-i')
REDIRECT_RE = re.compile(r'>>?\s*[\'"]?\S*(docs|_internal)/')
PART_RE = re.compile(r'&&|\|\||[;|\n]')
LIB = 'doc_reminder_lib.py'   # next to the hook: is_log, the rule the hook applies
ODD_REASONS = ('not json', 'not an object', 'other event, tool or input', 'input too big')
NO_COMMIT = 'no commit in the window'
BEFORE_REFLOG = 'skipped: before the reflog'
REFLOG_TIME_RE = re.compile(rb'^[0-9a-f]{40,64} [0-9a-f]{40,64} [^\t]*> (\d+) [+-]\d{4}(\t|$)')   # no message: no tab

# ---------------------------------------------------------------- extraction (read-only, in worker processes)


def epoch(ts):
    try:
        return datetime.datetime.fromisoformat(ts.replace('Z', '+00:00')).timestamp()
    except (AttributeError, ValueError):
        return None


def bash_doc_writes(cmd):
    """The docs/ and _internal/ paths a Bash command writes, [] for none: a > redirect there, or cp, mv, tee, rsync,
    install or sed -i with such a path in the same part of the command (split at ;, &&, ||, | and newlines); every
    such path of that part (the source of a cp is not told from its target), '?' when none can be read."""
    if 'docs/' not in cmd and '_internal/' not in cmd:
        return []
    found = []
    for part in PART_RE.split(cmd):
        if REDIRECT_RE.search(part) or (WRITE_VERB_RE.search(part) and DOCS_PATH_RE.search(part)):
            found += DOC_TOKEN_RE.findall(part) or ['?']
    return found


def doc_rel(p):
    """A docs path from its docs/ or _internal/ folder on, as the hook sees the files there: an archive/ above the
    project does not make an absolute Edit path the log."""
    m = DOC_REL_RE.search(p)
    return m.group(1) if m else p


def calls_in(d, proj, path, cutoff):
    """(Bash calls from cutoff on, docs edits waiting for their result, Bash docs writes as (session, time, paths)) of
    one assistant record."""
    ts = d['timestamp']
    sid = d.get('sessionId') if isinstance(d.get('sessionId'), str) else path
    calls, edits, writes = {}, {}, []
    for b in blocks(d, 'tool_use'):
        if not isinstance(b.get('id'), str):
            continue
        inp = b.get('input') if isinstance(b.get('input'), dict) else {}
        cmd, fp = inp.get('command'), inp.get('file_path') or inp.get('notebook_path')
        docs = isinstance(fp, str) and DOCS_PATH_RE.search(fp)
        if b.get('name') == 'Bash' and isinstance(cmd, str):
            paths = bash_doc_writes(cmd)
            if paths:
                writes.append((sid, ts, paths))
            if ts[:19] >= cutoff:
                calls[b['id']] = {'id': b['id'], 'proj': proj, 'cmd': cmd, 'cwd': d.get('cwd') or '', 'ts': ts,
                                  'sid': sid, 'file': path}
        elif b.get('name') in EDIT_TOOLS and docs:
            edits[b['id']] = (sid, ts, [fp])
    return calls, edits, writes


def results_in(d, calls, edits):
    """(results of known Bash calls, docs writes of the edits that did not fail) of one user record."""
    tur, results, writes = d.get('toolUseResult'), {}, []
    for b in blocks(d, 'tool_result'):
        tid = b.get('tool_use_id')
        if tid in calls:
            text = tur.get('stdout', '') if isinstance(tur, dict) else ''
            results[tid] = (d['timestamp'], bool(b.get('is_error')), text if isinstance(text, str) else '')
        elif tid in edits and not b.get('is_error'):
            writes.append(edits.pop(tid))
    return results, writes


def extract_file(job):
    """(Bash calls, results, docs writes, bad lines) of one transcript file; see calls_in() and results_in()."""
    proj, path, cutoff = job
    calls, results, edits, writes, n = {}, {}, {}, [], collections.Counter()
    try:
        fh = open(path, 'r', encoding='utf-8', errors='replace')
    except OSError:
        return [], {}, [], 1
    with fh:
        for d in records(fh, n, lambda line: '"tool_use"' in line or '"tool_result"' in line):
            cs, es, ws = calls_in(d, proj, path, cutoff)
            calls.update(cs)
            edits.update(es)
            rs, ws2 = results_in(d, calls, edits)
            results.update(rs)
            writes += ws + ws2
    return list(calls.values()), results, writes, n['bad']


def extract(files, cutoff, jobs):
    calls, results, writes, bad = {}, {}, collections.defaultdict(list), 0
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        for cs, rs, ws, b in ex.map(extract_file, [(p, f, cutoff) for p, f in files], chunksize=4):
            bad += b
            for c in cs:
                calls.setdefault(c['id'], c)   # resumed sessions repeat history
            results.update(rs)
            for sid, ts, paths in ws:
                writes[sid].append((ts, paths))
    return calls, results, writes, bad

# ---------------------------------------------------------------- hook runs (stdin JSON only)


def reason_of(err):
    """The hook's last debug line: why it stayed silent, or 'error ...'."""
    return next((ln[len('doc-reminder: '):] for ln in reversed(err.splitlines()) if ln.startswith('doc-reminder: ')),
                '')


def valid(out, event):
    out = out.rstrip('\n')   # the line end; the limit is on the JSON, as in doc-tests.sh
    try:
        o = json.loads(out)
    except ValueError:
        return False
    hso = o.get('hookSpecificOutput') if isinstance(o, dict) else None
    return (list(o) == ['hookSpecificOutput'] and isinstance(hso, dict) and hso.get('hookEventName') == event
            and set(hso) == {'hookEventName', 'additionalContext'}
            and str(hso.get('additionalContext')).startswith('doc-reminder: ')
            and len(out.encode('utf-8')) <= GATE_BYTES)


def note_of(out):
    try:
        return json.loads(out)['hookSpecificOutput']['additionalContext']
    except (ValueError, KeyError, TypeError):
        return out[:2000]


def reflog_start(cwd, env):
    """Epoch of the first entry of the HEAD reflog of cwd's repo (this worktree's, the file the hook reads), or None
    without one (outside git rev-parse gives no path, so the open fails)."""
    try:
        p = subprocess.run(['git', 'rev-parse', '--git-path', 'logs/HEAD'], cwd=cwd, capture_output=True, env=env,
                           timeout=TIMEOUT)
        with open(os.path.join(cwd, p.stdout.decode('utf-8', 'replace').strip()), 'rb') as fh:
            m = REFLOG_TIME_RE.match(fh.readline())
    except (OSError, subprocess.TimeoutExpired):
        return None
    return int(m.group(1)) if m else None


def before_reflog(cwd, end, env, starts):
    """The hook's window of a call that ended at end closes before the reflog of cwd's repo starts, so the call's
    entry cannot be in that file. starts: reflog_start() by cwd. With no reflog to read the call stays counted."""
    if cwd not in starts:
        starts[cwd] = reflog_start(cwd, env)
    return starts[cwd] is not None and end + SLACK_S < starts[cwd]


def control(hook, env, errlog):
    """A code commit and, 1000 s later on the commit clock (git takes reflog times from GIT_COMMITTER_DATE), a docs
    commit in a temp repo: the first must fire, the second must stay silent as "docs in the commit"; neither may
    leave an error-log line. The first commit opens the reflog: a call whose window closes a second before it counts
    as older than the reflog, one whose window reaches it does not. A new worktree's reflog must be read too: its
    first entry has no message."""
    before = size(errlog)
    with tempfile.TemporaryDirectory(prefix='commit-replay-') as r:
        r = os.path.realpath(r)
        g = ['git', '-c', 'user.name=Replay', '-c', 'user.email=replay@example.com', '-c', 'commit.gpgsign=false',
             '-c', 'init.defaultBranch=main', '-C', r]
        genv = dict(os.environ, GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1')
        subprocess.run(g + ['init', '-q'], env=genv, capture_output=True, check=True)
        res, t = [], int(time.time()) - 2000
        for name in ('app.ts', 'README.md'):
            t += 1000
            with open(os.path.join(r, name), 'w') as fh:
                fh.write('x\n')
            for a in ['add', name], ['commit', '-q', '-m', name]:
                subprocess.run(g + a, env=dict(genv, GIT_COMMITTER_DATE='@%d' % t, GIT_AUTHOR_DATE='@%d' % t),
                               capture_output=True, check=True)
            # transcript_path: the hook wants the field; with no docs outside git here it is not read
            payload = {'session_id': 'commit-replay', 'transcript_path': '', 'cwd': r, 'hook_event_name': 'PostToolUse',
                       'tool_name': 'Bash', 'tool_input': {'command': 'git commit -q -m x'}, 'duration_ms': 2000}
            res.append(run_hook(hook, payload, dict(env, DOC_REMINDER_NOW=str(t + 1)), TIMEOUT))
        first, starts, worktree = t - 1000, {}, os.path.join(r, 'wt')
        subprocess.run(g + ['worktree', 'add', '-q', worktree], env=genv, capture_output=True, check=True)
        reflog_ok = (before_reflog(r, first - SLACK_S - 1, env, starts)
                     and not before_reflog(r, first - SLACK_S, env, starts) and reflog_start(worktree, env) is not None)
    clean = size(errlog) == before
    return (clean and res[0][0] == 0 and valid(res[0][1], 'PostToolUse'),
            clean and res[1][:2] == (0, '') and reason_of(res[1][2]) == 'docs in the commit', reflog_ok)

# ---------------------------------------------------------------- replay and report


def call_payload(c, result, writes, is_log):
    """(hook stdin JSON, env for the hook, time of the newest docs write with the working log) of a commit call, or
    (None, why it is skipped, 0)."""
    rts, is_err, text = result
    t_call, t_res = epoch(c['ts']), epoch(rts)
    if t_call is None or t_res is None:
        return None, 'skipped: bad timestamp', 0
    if not os.path.isdir(c['cwd']):
        return None, 'skipped: cwd gone', 0
    done = [(epoch(ts), paths) for ts, paths in writes.get(c['sid'], []) if ts < rts]   # the session's, before it
    docs = max([t for t, paths in done if t is not None and not all(is_log(doc_rel(p)) for p in paths)], default=0)
    every = max([t for t, _ in done if t is not None], default=0)
    payload = {'session_id': 'commit-replay', 'transcript_path': c['file'], 'cwd': c['cwd'],
               'hook_event_name': 'PostToolUseFailure' if is_err else 'PostToolUse', 'tool_name': 'Bash',
               'tool_input': {'command': c['cmd']}, 'tool_use_id': c['id'],
               'duration_ms': max(0, int((t_res - t_call) * 1000))}
    if not is_err:
        payload['tool_response'] = {'stdout': text, 'stderr': '', 'interrupted': False}
    return payload, {'DOC_REMINDER_NOW': str(t_res), 'DOC_REMINDER_DOCS_MTIME': str(docs)}, every


def replay(commit_calls, results, writes, hook, is_log, env, errlog, dump):
    """Run the commit calls one at a time, oldest first; returns the counters for report()."""
    st = {'outcome': collections.Counter(), 'by_proj': collections.defaultdict(collections.Counter),
          'per_day': collections.Counter(), 'times': [], 'dumps': [], 'errors': 0, 'bad_json': 0, 'reached': 0,
          'found': 0, 'log_newest': 0}
    starts = {}
    for c in sorted(commit_calls, key=lambda c: c['ts']):
        payload, extra, every = call_payload(c, results[c['id']], writes, is_log)
        if payload is None:
            st['outcome'][extra] += 1
            continue
        st['log_newest'] += every > float(extra['DOC_REMINDER_DOCS_MTIME'])
        before = size(errlog)
        rc, out, err, ms = run_hook(hook, payload, dict(env, **extra), TIMEOUT)
        st['times'].append(ms)
        reason = reason_of(err)
        if rc != 0 or size(errlog) != before or reason.startswith('error') or reason in ODD_REASONS:
            st['errors'] += 1
            st['outcome']['ERROR %s' % (rc if rc != 0 else reason or 'error log')] += 1
            continue
        lost = reason == NO_COMMIT and before_reflog(c['cwd'], float(extra['DOC_REMINDER_NOW']), env, starts)
        st['reached'] += bool(out or reason) and not lost
        if out or reason not in ('', NO_COMMIT):
            st['found'] += 1
            st['by_proj'][c['proj']]['commits'] += 1
        if out:
            st['bad_json'] += not valid(out, payload['hook_event_name'])
            st['by_proj'][c['proj']]['fired'] += 1
            st['per_day'][local_date(results[c['id']][0])] += 1
        st['outcome'][BEFORE_REFLOG if lost else 'fired' if out else
                      'silent: ' + (reason or 'no git commit in the command (shim)')] += 1
        if dump:
            st['dumps'].append({'proj': c['proj'], 'session': c['sid'], 'ts': results[c['id']][0], 'cwd': c['cwd'],
                                'docs_mtime': extra['DOC_REMINDER_DOCS_MTIME'], 'docs_mtime_with_log': every,
                                'event': payload['hook_event_name'],
                                'result': 'fired' if out else reason or 'shim', 'before_reflog': lost,
                                'note': note_of(out) if out else ''})
    return st


def replay_fast(other, results, hook, env, tmp, n):
    """n other Bash calls, spread over the period, through the shim: (times, calls with any output)."""
    times, with_output = [], 0
    other = sorted(other, key=lambda c: c['ts'])
    for c in other[::max(1, len(other) // n)][:n] if n else []:
        payload = {'session_id': 'commit-replay', 'transcript_path': c['file'],
                   'cwd': c['cwd'] if os.path.isdir(c['cwd']) else tmp, 'hook_event_name': 'PostToolUse', 'tool_name': 'Bash', 'tool_input': {'command': c['cmd']},
                   'tool_response': {'stdout': results[c['id']][2], 'stderr': '', 'interrupted': False},
                   'duration_ms': 1000}
        rc, out, err, ms = run_hook(hook, payload, env, TIMEOUT)
        times.append(ms)
        with_output += bool(out or err or rc != 0)
    return times, with_output


def report(ctx, st, fast_times, fast_out):
    """Print the counts and the gate line; True when the gate passes."""
    outcome, by_proj, per_day, times = st['outcome'], st['by_proj'], st['per_day'], st['times']
    fired, found, reached, days = outcome['fired'], st['found'], st['reached'], ctx['days_with_calls']
    lost = outcome[BEFORE_REFLOG]
    print('== doc-reminder: %d days, %s, %d files read, %d audit files skipped, %d unreadable lines' % (
        ctx['days'], 'all sessions' if ctx['include_audit'] else 'audit sessions skipped', ctx['files'],
        ctx['audit_skipped'], ctx['bad_lines']))
    print('hook  %s  sha256:%s; %s sha256:%s' % (short(ctx['hook']), sha(ctx['hook']), LIB, sha(ctx['lib'])))
    print('control  code commit fires: %s; docs commit silent: %s; only a call older than the reflog skipped: %s'
          % ctx['control'])
    print('calls  %d with git and commit in the command (%d days with such calls); %d reached the hook (%d more older '
          'than the reflog), %d commits found by it' % (ctx['commit_calls'], len(days), reached, lost, found))
    for k, v in sorted(outcome.items(), key=lambda kv: -kv[1]):
        print('  %5d  %s' % (v, k))
    print('log  %d calls whose newest docs write before them was the working log only (no docs change for the hook)'
          % st['log_newest'])
    print('fired  %d of %d commits (%.1f%%); per working day with commits: median %.1f, max %d' % (
        fired, found, 100.0 * fired / found if found else 0.0,
        statistics.median([per_day[d] for d in days]) if days else 0.0, max(per_day.values() or [0])))
    for proj, v in sorted(by_proj.items(), key=lambda kv: -kv[1]['commits']):
        print('  %-48s commits %4d  fired %4d' % (proj_name(proj)[:48], v['commits'], v['fired']))
    print('time  commit calls: p50 %.0f ms, p95 %.0f ms, max %.0f ms; fast calls (%d): p50 %.0f ms, p95 %.0f ms, '
          'with output %d' % (pct(times, 0.5), pct(times, 0.95), max(times or [0]), len(fast_times),
                              pct(fast_times, 0.5), pct(fast_times, 0.95), fast_out))
    for line in ctx['errlog'][-5:]:
        print('errlog  %s' % line)   # time, error class and the hook's own message: no paths
    rate, p95 = float(found) / reached if reached else 0.0, pct(fast_times, 0.95)
    checks = {'control': all(ctx['control']), 'commits': found >= GATE_MIN_COMMITS, 'fired': fired >= 1,
              'found': rate >= GATE_MIN_FOUND, 'errors': st['errors'] == 0, 'json': st['bad_json'] == 0,
              'fast': len(fast_times) >= GATE_MIN_FAST and fast_out == 0 and p95 <= GATE_FAST_P95_MS}
    ok = all(checks.values())
    print('gate  control %s; commits found %d (>=%d), fired %d (>=1), found for %.0f%% (>=%.0f%%) of the calls the '
          'hook got, not counting %d older than the reflog; errors/timeouts %d (error-log lines %d); invalid JSON %d; '
          'fast calls %d (>=%d), with output %d, p95 %.0f ms (<=%d) -> %s' % (
              'ok' if checks['control'] else 'FAIL', found, GATE_MIN_COMMITS, fired, 100 * rate, 100 * GATE_MIN_FOUND,
              lost, st['errors'], len(ctx['errlog']), st['bad_json'], len(fast_times), GATE_MIN_FAST, fast_out, p95,
              GATE_FAST_P95_MS, 'PASS' if ok else 'FAIL: ' + ', '.join(k for k, v in checks.items() if not v)))
    return ok


def main():
    ap = argparse.ArgumentParser(description='Replay real git commit calls through doc-reminder.')
    ap.add_argument('--days', type=int, default=60)
    ap.add_argument('--hook', default=os.path.join(REPO, 'hooks', 'doc-reminder.sh'))
    ap.add_argument('--include-audit', action='store_true', help='also replay sessions of this repo and /tmp')
    ap.add_argument('--jobs', type=int, default=min(8, os.cpu_count() or 4), help='extraction workers')
    ap.add_argument('--fast', type=int, default=2000, help='other Bash calls through the shim (default 2000)')
    ap.add_argument('--dump', action='store_true',
                    help='write every commit call with its outcome and reminder to research/replay-cache/ (0600)')
    args = ap.parse_args()
    if args.days < 1 or args.jobs < 1 or args.fast < 0:
        ap.error('--days and --jobs must be positive, --fast not negative')
    hook = os.path.abspath(os.path.expanduser(args.hook))
    lib_path = os.path.join(os.path.dirname(hook), LIB)
    if not os.path.isfile(hook) or not os.path.isfile(lib_path):
        print('commit-replay: hook not found: %s (and %s next to it)' % (hook, LIB), file=sys.stderr)
        return 2
    sys.dont_write_bytecode = True   # no __pycache__ next to the hook, also the live one
    spec = importlib.util.spec_from_file_location('doc_reminder_lib', lib_path)
    lib = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lib)
    t0 = time.perf_counter()
    cutoff_epoch, cutoff = window_start(args.days)
    files, audit_skipped = list_files(cutoff_epoch, args.include_audit)
    print('[commit-replay] reading %d transcript files ...' % len(files), file=sys.stderr, flush=True)
    calls, results, writes, bad = extract(files, cutoff, args.jobs)
    commit_calls = [c for c in calls.values() if 'git' in c['cmd'] and 'commit' in c['cmd'] and c['id'] in results]
    other = [c for c in calls.values() if not ('git' in c['cmd'] and 'commit' in c['cmd']) and c['id'] in results]
    if not commit_calls:
        print('commit-replay: no git commit calls in %d transcript files of %d days' % (len(files), args.days),
              file=sys.stderr)
        return 2
    print('[commit-replay] %d calls with git and commit, %d other ...' % (len(commit_calls), len(other)),
          file=sys.stderr, flush=True)
    with tempfile.TemporaryDirectory(prefix='commit-replay-') as tmp:
        errlog = os.path.join(tmp, 'err.log')   # the hook's error channel, never the live log
        env = {k: v for k, v in os.environ.items() if not k.startswith('DOC_REMINDER_')}
        env.update(DOC_REMINDER_ERRLOG=errlog, DOC_REMINDER_DEBUG='1', GIT_OPTIONAL_LOCKS='0')
        ctl = control(hook, env, errlog)
        st = replay(commit_calls, results, writes, hook, lib.is_log, env, errlog, args.dump)
        fast_times, fast_out = replay_fast(other, results, hook, env, tmp, args.fast)
        errlines = log_lines(errlog)
    ctx = {'days': args.days, 'include_audit': args.include_audit, 'files': len(files), 'audit_skipped': audit_skipped,
           'bad_lines': bad, 'hook': hook, 'lib': lib_path, 'control': ctl, 'commit_calls': len(commit_calls),
           'errlog': errlines,
           'days_with_calls': sorted({local_date(results[c['id']][0]) for c in commit_calls})}
    if args.dump:
        write_dump('commit', st['dumps'], 'commit calls with their outcome and reminder')
    ok = report(ctx, st, fast_times, fast_out)
    print('total %.1f s' % (time.perf_counter() - t0))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
