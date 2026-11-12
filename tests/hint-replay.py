#!/usr/bin/env python3
"""hint-replay: run real git push and gh pr create calls and compactions from Claude Code transcripts through
session-hint.

Usage (from the repo root): python3 -I tests/hint-replay.py [--days 60] [--hook PATH] [--include-audit] [--jobs N]
[--fast N] [--dump]. --hook defaults to <repo>/hooks/session-hint.sh.

Historical mode: every Bash call with "push" or "pr create" in the command (main sessions and subagents) goes to the
hook as stdin JSON with its real result: PostToolUse with stdout and stderr when it succeeded, PostToolUseFailure when it failed (the
hook is wired to PostToolUse only, so that event must stay silent); a subagent's call carries its agent_id. Every
compaction (a compact_boundary record) goes as SessionStart with source "compact"; a subagent's too, with no agent_id,
as Claude Code sends it (docs/compat.md, 2026-11-11). The
expected outcome comes from the hook's rules written again in Python (expect() in tests/hint_common.py): the push hint
for a successful main session call whose command runs git [-c x | -C dir]... push, not a dry run, with no failed push in
the output; the PR hint when such a call runs gh [-R repo]... pr create with no gh pr merge, and its output shows a new
PR; the compaction hint for every compaction, a subagent's own too (the hook cannot tell it from the main session's:
"compact subagent hint" in the counts); silence otherwise. --fast N: also N other Bash calls
through the hook. Whether Claude Code really delivers the hints: tests/hint-delivered.py.

Safety: transcripts are only read; commands are never executed: they only reach the hook as stdin JSON. Output is
counts; --dump writes every replayed call with its outcome (commands hold client paths) to research/replay-cache/
(gitignored, 0600). Sessions of this repo and /tmp are skipped unless --include-audit.

Gate (exit 0 = PASS, 1 = FAIL, 2 = usage or setup error, no transcripts, no push calls): control inputs (a push fires,
a gh pr create and a compaction fire, a dry run, a subagent push and a startup stay silent) with no error-log line; at
least 100 calls and 50 compactions replayed, at least one hint of each kind, at least one failed push in a main session (so the
output of Bash results still reaches the rule; with none in the period, take more --days); the outcome equals expect() for every call (mismatches 0); 0 errors
and timeouts (a non-zero exit, stderr other than the debug line, an error-log line); every hint is one JSON line with
the exact text for its event; at least 500 fast calls, none with output, p95 <= 50 ms. Also printed: push calls with
no result (not replayed) and successful ones with no toolUseResult object (subagent transcripts keep none; their stdout
is the text of the tool_result block).
"""
import argparse
import collections
import json
import os
import statistics
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I drops the script folder from sys.path
from hint_common import (EVENT, TEXT, bash_call, bash_result, compact_payload, expect, hint_candidate,  # noqa: E402
                         push_payload, record_base)
from replay_common import (REPO, blocks, list_files, local_date, log_lines, pct, proj_name, records,  # noqa: E402
                           run_hook, sha, short, size, window_start, write_dump)

TIMEOUT = 5.0   # as in settings.json
GATE_MIN_PUSH, GATE_MIN_COMPACT, GATE_MIN_FAILED, GATE_MIN_FAST, GATE_FAST_P95_MS = 100, 50, 1, 500, 50
AFTER = '2026-10-13'   # the "after" window of the metrics review 26.10

# ---------------------------------------------------------------- extraction (read-only, in worker processes)


def scanned(line):
    return '"tool_use"' in line or '"tool_result"' in line or 'compact_boundary' in line


def scan_record(d, base, push, other, compact, results):
    """Add one transcript record: a compaction, Bash calls (push in the command or not), results of known calls."""
    if d.get('type') == 'system' and d.get('subtype') == 'compact_boundary':
        compact.append(base)
        return
    for b in blocks(d, 'tool_use'):
        call = bash_call(b, base)
        if call:
            (push if hint_candidate(call['cmd']) else other)[call['id']] = call
    for b in blocks(d, 'tool_result'):
        if b.get('tool_use_id') in push or b.get('tool_use_id') in other:
            results[b['tool_use_id']] = bash_result(d, b)


def extract_file(job):
    """(push calls, other Bash calls, compactions, results, bad lines) of one transcript file."""
    proj, path, cutoff = job
    push, other, compact, results, n = {}, {}, [], {}, collections.Counter()
    try:
        fh = open(path, 'r', encoding='utf-8', errors='replace')
    except OSError:
        return {}, {}, [], {}, 1
    with fh:
        for d in records(fh, n, scanned):
            if d['timestamp'][:19] >= cutoff:
                scan_record(d, record_base(d, proj, path), push, other, compact, results)
    return push, other, compact, results, n['bad']


def extract(files, cutoff, jobs):
    push, other, compact, results, bad = {}, {}, [], {}, 0
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        for p, o, c, r, b in ex.map(extract_file, [(pr, f, cutoff) for pr, f in files], chunksize=4):
            for k, v in p.items():
                push.setdefault(k, v)   # resumed sessions repeat history
            for k, v in o.items():
                other.setdefault(k, v)
            compact += c
            results.update(r)
            bad += b
    seen, uniq = set(), []
    for c in compact:   # a resumed session repeats its boundaries
        key = c['uuid'] if isinstance(c['uuid'], str) else (c['sid'], c['agent'], c['ts'])
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return push, other, uniq, results, bad

# ---------------------------------------------------------------- hook runs (payloads and expect() in hint_common)


def hint_of(out):
    """The key in TEXT of a valid hint (one JSON line, only additionalContext with the exact text of its event), ''
    for none, None if the output is anything else."""
    if not out:
        return ''
    try:
        o = json.loads(out)
    except ValueError:
        return None
    hso = o.get('hookSpecificOutput') if isinstance(o, dict) else None
    if not isinstance(hso, dict):
        return None
    key = next((k for k, text in TEXT.items() if text == hso.get('additionalContext')), None)
    ok = (out.count('\n') == 1 and out.endswith('\n') and list(o) == ['hookSpecificOutput']
          and set(hso) == {'hookEventName', 'additionalContext'} and EVENT.get(key) == hso['hookEventName'])
    return key if ok else None


def control(hook, env, errlog):
    """Fixed inputs: a push, a gh pr create and a compaction fire, a dry run, a subagent push and a startup stay
    silent."""
    before, b = size(errlog), {'hook_event_name': 'PostToolUse', 'tool_name': 'Bash', 'session_id': 'hint-replay',
                               'tool_response': {'stdout': '', 'stderr': ''}}
    cases = [(dict(b, tool_input={'command': 'git push origin main'}), 'PostToolUse'),
             (dict(b, tool_input={'command': 'gh pr create --fill'},
                   tool_response={'stdout': 'https://github.com/o/r/pull/1', 'stderr': ''}), 'PullRequest'),
             ({'hook_event_name': 'SessionStart', 'source': 'compact'}, 'SessionStart'),
             (dict(b, tool_input={'command': 'git push --dry-run'}), ''),
             (dict(b, tool_input={'command': 'git push'}, agent_id='a1'), ''),
             ({'hook_event_name': 'SessionStart', 'source': 'startup'}, '')]
    runs = [(run_hook(hook, p, env, TIMEOUT), want) for p, want in cases]
    return all(r[0] == 0 and hint_of(r[1]) == want for r, want in runs) and size(errlog) == before


def replay(items, results, hook, env, errlog, dump):
    """items: (kind, call) oldest first. Returns the counters for report()."""
    st = {'reason': collections.Counter(), 'hints': collections.Counter(), 'times': collections.defaultdict(list),
          'mismatch': collections.Counter(), 'errors': 0, 'bad_out': 0, 'by_sess': collections.Counter(),
          'by_day': collections.Counter(), 'by_proj': collections.Counter(), 'after': collections.Counter(),
          'after_sess': set(), 'dumps': []}
    for kind, c in items:
        p = push_payload(c, results[c['id']]) if kind == 'push' else compact_payload(c)
        before = size(errlog)
        rc, out, err, ms = run_hook(hook, p, env, TIMEOUT)
        st['times'][kind].append(ms)
        debug = [ln for ln in err.splitlines() if ln.startswith('session-hint: ')]
        if rc != 0 or size(errlog) != before or len(debug) != len(err.splitlines()):
            st['errors'] += 1
            st['reason']['ERROR %s' % (rc if rc != 0 else 'stderr or error log')] += 1
            continue
        got = hint_of(out)
        if got is None:
            st['bad_out'] += 1
            continue
        want = expect(p) or ''
        if got != want:
            st['mismatch']['%s: want %s, got %s' % (kind, want or 'silence', got or 'silence')] += 1
        reason = 'hint' if got else (debug[-1][len('session-hint: '):] if debug else '?')
        reason = 'PR hint' if got == 'PullRequest' else reason
        st['reason']['%s %s%s' % (kind, 'subagent ' if c['agent'] and reason != 'subagent' else '', reason)] += 1
        ts = results[c['id']][0] if kind == 'push' else c['ts']
        if got:
            st['hints']['pr' if got == 'PullRequest' else kind] += 1
            st['by_sess'][c['sid']] += 1
            st['by_day'][local_date(ts)] += 1
            st['by_proj'][c['proj']] += 1
            if local_date(ts) >= AFTER:
                st['after'][kind] += 1
                st['after_sess'].add(c['sid'])
        if dump:
            st['dumps'].append({'kind': kind, 'proj': c['proj'], 'session': c['sid'], 'agent': c['agent'], 'ts': ts,
                                'event': p['hook_event_name'], 'cmd': c.get('cmd', ''), 'want': want, 'got': got,
                                'reason': reason})
    return st


def replay_fast(other, results, hook, env, n):
    """n other Bash calls, spread over the period, with their real output: (times, calls with any output)."""
    times, with_output = [], 0
    other = sorted((c for c in other.values() if c['id'] in results), key=lambda c: c['ts'])
    for c in other[::max(1, len(other) // n)][:n] if n else []:
        p = push_payload(c, results[c['id']])
        rc, out, err, ms = run_hook(hook, p, env, TIMEOUT)
        times.append(ms)
        with_output += bool(out or rc != 0 or [ln for ln in err.splitlines() if not ln.startswith('session-hint: ')])
    return times, with_output


def report(ctx, st, fast_times, fast_out):
    """Print the counts and the gate line; True when the gate passes."""
    hints, times, days = st['hints'], st['times'], sorted(ctx['days_with_items'])
    print('== session-hint: %d days, %s, %d files read, %d audit files skipped, %d unreadable lines' % (
        ctx['days'], 'all sessions' if ctx['include_audit'] else 'audit sessions skipped', ctx['files'],
        ctx['audit_skipped'], ctx['bad_lines']))
    print('hook  %s  sha256:%s' % (short(ctx['hook']), sha(ctx['hook'])))
    print('control  push and compaction fire, dry run, subagent and startup silent: %s' % ('ok' if ctx['control']
                                                                                            else 'FAIL'))
    print('calls  %d Bash calls with "push" or "pr create" in the command (%d in subagents); %d compactions (%d in '
          'subagents)' % (
        ctx['push'], ctx['push_sub'], ctx['compact'], ctx['compact_sub']))
    print('results  %d push calls without a result (not replayed); successful with no toolUseResult object (stdout is '
          'the text of the tool_result): main sessions %d, subagents %d' % (ctx['no_result'], ctx['odd']['main'],
                                                                           ctx['odd']['sub']))
    for k, v in sorted(st['reason'].items(), key=lambda kv: -kv[1]):
        print('  %5d  %s' % (v, k))
    per_sess = sorted(st['by_sess'].values())
    print('hints  push %d, PR %d, compaction %d; %d sessions, per session median %.1f, max %d; per day with replayed '
          'calls median %.1f, max %d' % (hints['push'], hints['pr'], hints['compact'], len(per_sess),
                                         statistics.median(per_sess) if per_sess else 0.0, max(per_sess or [0]),
                                         statistics.median([st['by_day'][d] for d in days]) if days else 0.0,
                                         max(st['by_day'].values() or [0])))
    print('since %s  push %d, compaction %d, sessions %d' % (AFTER, st['after']['push'], st['after']['compact'],
                                                            len(st['after_sess'])))
    for proj, v in st['by_proj'].most_common(8):
        print('  %-48s hints %4d' % (proj_name(proj)[:48], v))
    for k, v in sorted(st['mismatch'].items()):
        print('mismatch  %d  %s' % (v, k))
    print('time  push calls: p50 %.0f ms, p95 %.0f ms, max %.0f ms; compactions: p50 %.0f ms, p95 %.0f ms; fast calls '
          '(%d): p50 %.0f ms, p95 %.0f ms, with output %d' % (
              pct(times['push'], 0.5), pct(times['push'], 0.95), max(times['push'] or [0]),
              pct(times['compact'], 0.5), pct(times['compact'], 0.95), len(fast_times), pct(fast_times, 0.5),
              pct(fast_times, 0.95), fast_out))
    for line in ctx['errlog'][-5:]:
        print('errlog  %s' % line)   # time and class only
    mism, p95, failed = sum(st['mismatch'].values()), pct(fast_times, 0.95), st['reason']['push push failed']
    checks = {'control': ctx['control'], 'push': ctx['push'] >= GATE_MIN_PUSH and hints['push'] >= 1 and hints['pr'] >= 1,
              'compact': ctx['compact'] >= GATE_MIN_COMPACT and hints['compact'] >= 1,
              'failed': failed >= GATE_MIN_FAILED, 'mismatch': mism == 0,
              'errors': st['errors'] == 0 and not ctx['errlog'], 'output': st['bad_out'] == 0,
              'fast': len(fast_times) >= GATE_MIN_FAST and fast_out == 0 and p95 <= GATE_FAST_P95_MS}
    ok = all(checks.values())
    print('gate  control %s; calls %d (>=%d), compactions %d (>=%d), hints %d, %d and %d (>=1 each), failed pushes '
          '%d (>=%d); mismatches %d; errors/timeouts %d (error-log lines %d); bad output %d; fast calls %d (>=%d), '
          'with output %d, p95 %.0f ms (<=%d) -> %s' % (
              'ok' if ctx['control'] else 'FAIL', ctx['push'], GATE_MIN_PUSH, ctx['compact'], GATE_MIN_COMPACT,
              hints['push'], hints['pr'], hints['compact'], failed, GATE_MIN_FAILED, mism, st['errors'],
              len(ctx['errlog']),
              st['bad_out'], len(fast_times), GATE_MIN_FAST, fast_out, p95, GATE_FAST_P95_MS,
              'PASS' if ok else 'FAIL: ' + ', '.join(k for k, v in checks.items() if not v)))
    return ok


def main():
    ap = argparse.ArgumentParser(description='Replay real git push calls and compactions through session-hint.')
    ap.add_argument('--days', type=int, default=60)
    ap.add_argument('--hook', default=os.path.join(REPO, 'hooks', 'session-hint.sh'))
    ap.add_argument('--include-audit', action='store_true', help='also replay sessions of this repo and /tmp')
    ap.add_argument('--jobs', type=int, default=min(8, os.cpu_count() or 4), help='extraction workers')
    ap.add_argument('--fast', type=int, default=2000, help='other Bash calls through the hook (default 2000)')
    ap.add_argument('--dump', action='store_true', help='write every replayed call to research/replay-cache/ (0600)')
    args = ap.parse_args()
    if args.days < 1 or args.jobs < 1 or args.fast < 0:
        ap.error('--days and --jobs must be positive, --fast not negative')
    hook = os.path.abspath(os.path.expanduser(args.hook))
    if not os.path.isfile(hook):
        print('hint-replay: hook not found: %s' % hook, file=sys.stderr)
        return 2
    t0 = time.perf_counter()
    cutoff_epoch, cutoff = window_start(args.days)
    files, audit_skipped = list_files(cutoff_epoch, args.include_audit)
    print('[hint-replay] reading %d transcript files ...' % len(files), file=sys.stderr, flush=True)
    push, other, compact, results, bad = extract(files, cutoff, args.jobs)
    no_result = sum(1 for k in push if k not in results)   # the session ended or was cut before the result
    push = {k: v for k, v in push.items() if k in results}
    if not push:
        print('hint-replay: no push calls in %d transcript files of %d days' % (len(files), args.days), file=sys.stderr)
        return 2
    items = sorted([('push', c) for c in push.values()] + [('compact', c) for c in compact], key=lambda kc: kc[1]['ts'])
    print('[hint-replay] %d push calls, %d compactions, %d other Bash calls ...' % (
        len(push), len(compact), len(other)), file=sys.stderr, flush=True)
    with tempfile.TemporaryDirectory(prefix='hint-replay-') as tmp:
        errlog = os.path.join(tmp, 'err.log')   # the hook's error channel, never the live log
        env = {k: v for k, v in os.environ.items() if not k.startswith('SESSION_HINT_')}
        env.update(SESSION_HINT_ERRLOG=errlog, SESSION_HINT_DEBUG='1')
        ctl = control(hook, env, errlog)
        st = replay(items, results, hook, env, errlog, args.dump)
        fast_times, fast_out = replay_fast(other, results, hook, env, args.fast)
        errlines = log_lines(errlog)
    ctx = {'days': args.days, 'include_audit': args.include_audit, 'files': len(files), 'audit_skipped': audit_skipped,
           'bad_lines': bad, 'hook': hook, 'control': ctl, 'push': len(push), 'no_result': no_result,
           'odd': collections.Counter('sub' if push[k]['agent'] else 'main' for k in push if results[k][4]),
           'push_sub': sum(1 for c in push.values() if c['agent']), 'compact': len(compact),
           'compact_sub': sum(1 for c in compact if c['agent']), 'errlog': errlines,
           'days_with_items': {local_date(c['ts']) for _, c in items}}
    if args.dump:
        write_dump('hint', st['dumps'], 'calls with their outcome')
    ok = report(ctx, st, fast_times, fast_out)
    print('total %.1f s' % (time.perf_counter() - t0))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
