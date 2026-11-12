#!/usr/bin/env python3
"""hint-delivered: did Claude Code really deliver session-hint's hints in live sessions? The check after install and in
the canary. tests/hint-replay.py proves the hook's rules on old transcripts; this one proves the whole path: the wiring
in settings.json, the input Claude Code sends, the timeout and the delivery to the model.

Usage (from the repo root): python3 -I tests/hint-delivered.py [--since 2026-10-26T21:30 | --days N] [--include-audit]
[--jobs N] [--claude-home DIR] [--doctor]
--since is local time; by default the last install (installed_at in ~/.claude/.setup-manifest.json plus a minute).
--days N: sessions started in the last N days, but not before the last install. --claude-home: another folder with
projects/ and .setup-manifest.json (a sandbox). --doctor: one line and a WARN for every problem instead of the report;
scripts/doctor.sh prints them for --days 7. tests/hint-delivered-test.py runs it on made-up transcripts in a temp HOME,
tests/doctor-test.py through doctor.sh (verify.sh runs both).

--doctor --days N also prints the line of hook failures (tests/hook_failures.py), which never changes the exit code,
also when it breaks.

Reads the transcripts changed since --since. A main session is checked when its first record is not older than --since:
an older one may still run the hooks it read at its start, so it is only counted, with a WARN when it has problems (a
resumed or forked session is older too: its file starts with the old chain). A record whose uuid came earlier in the
file is skipped: resuming a session appends copies of its chain. For every Bash call with "push" or "pr create" in the
command that has a result, expect() (tests/hint_common.py, the hook's rules) says whether a hint was due and which; both
count as "push" below; every compaction is due the compaction hint. Claude Code records a delivered hint as an attachment hook_additional_context with the text in
content: hookName PostToolUse:Bash and toolUseID = the call's id for a push, right after the call's result; hookName
SessionStart after the compact_boundary for a compaction; both before the next assistant message. A command hook that
printed also leaves hook_success with its command and durationMs. Subagent transcripts (<session>/subagents/) are only
searched for session-hint texts and compactions: the hook is silent in a subagent, which it knows by agent_id in its
input. One text is not extra there: the compaction hint after the subagent's own compaction. Claude Code runs
SessionStart for it with the fields of the main session and no agent_id (docs/compat.md, 2026-11-11), so the hook
cannot tell; such hints are counted as "own compaction" and not gated.

Safety: transcripts are only read. Output: counts, and the project, session and time of each problem (no commands).

Gate (exit 0 = PASS, 1 = FAIL, 2 = usage error, not proven yet or no data, 3 = the check itself broke): every due
hint delivered with the exact text (missing 0); no session-hint text where none was due, with another text, twice or
in a subagent, but for the one after its own compaction (extra 0); no failed run of session-hint.sh (an error attachment or a non-zero exit naming it as the
command: errors 0); PASS needs at least one due push hint and one due compaction hint in checked sessions, else 2. A
due hint with no assistant message after it yet is pending, not missing: a push hint while the file changed in the
last IDLE_S seconds (tests/hint_common.py: its reader of one transcript), a compaction hint until the next answer (it
may come only with the next prompt). Info: what the
reader saw in checked sessions, with NO DATA when it saw nothing to judge (no transcript, push calls with no result:
a format change); hook errors and cancels on the hook's events with no command (Claude Code drops the command when a
PostToolUse hook times out: any hook of the event); WARNs for a slow run, runs not seen, unreadable files, older
sessions with problems, a --since before the last install and a reader that does not see what it should (a format
change?): BLIND_FILES main transcripts of checked sessions with no Bash call, BLIND_FILES changed main transcripts with
no usable record, push calls with an answer after them but no result, tool results with no string tool_use_id, more
compaction summaries than compactions; also an unreadable transcripts folder and --days with no installed_at.
--doctor also WARNs for the gate's FAIL and for push calls with no result at all.
"""
import argparse
import collections
import datetime
import json
import os
import shlex
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I drops the script folder from sys.path
try:
    from hint_common import TEXT, expect, push_payload, scan_file  # noqa: E402
    from replay_common import HOME, list_files, pct, proj_name, session_of  # noqa: E402
except Exception:   # a broken module is the check broken (exit 3), not a FAIL of the hook (1)
    traceback.print_exc()
    sys.exit(3)

KINDS = ('push', 'compaction')
OUTCOMES = ('delivered', 'missing', 'pending', 'extra')
PROBLEMS = ('missing', 'extra', 'error')
SHOW_PROBLEMS = 20   # problems printed one per line; the rest only counted
SLOW_MS = 2500   # half the hook's timeout of 5 s in settings.json
INSTALL_MARGIN_S = 60   # installed_at is taken before the files are copied: a session started in between is older
CLAUDE_DIR = os.path.join(HOME, '.claude')
MAX_DAYS = 3650
BLIND_FILES = 5   # this many main transcripts of checked sessions and no Bash call seen: the reader is blind
NO_RESULTS = 'NO DATA: push calls but none with a result (a format change?)'

# ---------------------------------------------------------------- judging and the gate


def judge(f):
    """(outcome, kind, time) of one transcript: delivered, missing or pending for each due hint, extra for each
    session-hint text that was not due, error for each failed session-hint run, known for the compaction hint of a
    subagent's own compaction (the hook cannot see the subagent there: not gated)."""
    out = [('extra', 'subagent', ts) for ts in f['sub_texts']]
    for c in (c for own in f['sub_compactions'].values() for c in own):
        hit = min(1, c['texts'].count(TEXT['SessionStart']))
        out += [('known', 'subagent', c['ts'])] * hit + [('extra', 'subagent', c['ts'])] * (len(c['texts']) - hit)
    for cid, got in f['hints'].items():
        if cid not in f['calls']:   # a hint on a call with neither "push" nor "pr create" in the command
            out += [('extra', 'push', ts) for _, lines, ts in got for line in lines]
    for cid, call in f['calls'].items():
        if cid not in f['results']:
            continue   # no result yet
        ts = f['results'][cid][0]
        texts = [(name, line) for name, lines, _ in f['hints'].get(cid, []) for line in lines]
        due = expect(push_payload(call, f['results'][cid]))
        hit = min(1, texts.count(('PostToolUse:Bash', TEXT.get(due))))
        if due:
            closed = f['last_assistant'] > f['result_seq'][cid] or f['idle']
            out.append(('delivered' if hit else 'missing' if closed else 'pending', 'push', ts))
            out += [('extra', 'push', ts)] * (len(texts) - hit)
        else:
            out += [('extra', 'push', ts)] * len(texts)
    for c in f['compactions']:
        hit = min(1, c['texts'].count(TEXT['SessionStart']))
        out.append(('delivered' if hit else 'missing' if c['closed'] else 'pending', 'compaction', c['ts']))
        out += [('extra', 'compaction', c['ts'])] * (len(c['texts']) - hit)
    return out + [('extra', 'compaction', ts) for ts in f['stray']] + [('error', k, ts) for ts, k in f['errors']]


def tally(agg, f, since):
    """Add one transcript's outcomes from since on to its group: checked (started since) or older."""
    items = [o for o in judge(f) if o[2][:19] >= since]
    group = 'checked' if (f['first'] or '')[:19] >= since else 'older'
    agg['sessions'][group] += bool(items) and not f['sub']
    agg['unusable'] += not f['sub'] and f['first'] is None and not f['bad_files']
    if group == 'checked':
        agg['seen'] += f['seen']
        agg['main_checked'] += not f['sub']
        agg['unpaired'] += sum(1 for cid in f['calls'] if cid not in f['results']
                               and f['answers'] > f['call_answer'][cid])
    for outcome, kind, ts in items:
        agg[group][outcome, 'run' if outcome == 'error' else kind] += 1
        if group == 'checked' and outcome in PROBLEMS:
            agg['problems'].append((outcome, kind, f['proj'], f['sid'], ts))


def collect(files, since, jobs):
    """Counters of checked sessions (first record not older than since) and older ones, problems, run times,
    unattributed errors, unreadable lines and files, what was seen in checked sessions."""
    agg = {'checked': collections.Counter(), 'older': collections.Counter(), 'sessions': collections.Counter(),
           'seen': collections.Counter(), 'problems': [], 'runs': [], 'unattributed': 0, 'bad': 0, 'bad_files': 0,
           'main_checked': 0, 'unusable': 0, 'unpaired': 0}
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        for f in ex.map(scan_file, files, chunksize=2):
            agg['bad'] += f['bad']
            agg['bad_files'] += f['bad_files']
            agg['runs'] += [ms for ts, ms in f['runs'] if ts[:19] >= since and isinstance(ms, (int, float))]
            agg['unattributed'] += sum(1 for ts in f['unattributed'] if ts[:19] >= since)
            tally(agg, f, since)
    return agg


def verdict(counts):
    """(exit code, due by kind, outcomes) of the checked sessions' counters: 0 only when a push hint and a compaction
    hint were due and every due hint was delivered."""
    n, due = collections.Counter(), collections.Counter()
    for (outcome, kind), v in counts.items():
        n[outcome] += v
        due[kind] += v if outcome in ('delivered', 'missing') else 0
    bad = n['missing'] + n['extra'] + n['error']
    return (1 if bad else 0 if all(due[k] for k in KINDS) else 2), due, n


def blind_warnings(agg, ctx):
    """The texts of the WARNs of a reader that does not see what it should (a transcript format change?) and of a
    window it cannot bound."""
    seen, out = agg['seen'], []
    if agg['main_checked'] >= BLIND_FILES and not seen['bash']:
        out.append('no Bash call seen in %d main transcripts of sessions started since then (a transcript format '
                   'change?)' % agg['main_checked'])
    if agg['unusable'] >= BLIND_FILES:
        out.append('%d main transcripts changed since then have no record the reader can use, %d unreadable lines '
                   '(a transcript format change?)' % (agg['unusable'], agg['bad']))
    if agg['unpaired']:
        out.append('%d push calls with an answer after them but no result (a transcript format change?): their hints '
                   'are not checked' % agg['unpaired'])
    if seen['odd_results']:
        out.append('%d tool results with no string tool_use_id (a transcript format change?): their calls are not '
                   'paired' % seen['odd_results'])
    if seen['summaries'] > seen['compactions']:
        out.append('compaction summaries %d, compactions seen %d (a transcript format change?): their hints are not '
                   'checked' % (seen['summaries'], seen['compactions']))
    if ctx['no_projects']:
        out.append('cannot read the transcripts folder %s' % ctx['no_projects'])
    if ctx['no_install']:
        out.append('no installed_at in %s: the window is the last %d days, sessions started before the install may '
                   'count' % ctx['no_install'])
    return out


def warnings(agg, ctx):
    """The texts of the WARNs: a slow run, push hints with no run seen, unreadable files, older sessions with problems,
    a --since before the last install, then blind_warnings()."""
    runs, older, out = agg['runs'], collections.Counter(), []
    for (outcome, _), v in agg['older'].items():
        older[outcome] += v
    if max(runs or [0]) > SLOW_MS:
        out.append('slowest session-hint run %d ms, over %d ms (half the hook timeout): a slow machine or a hung jq' % (
            max(runs), SLOW_MS))
    if agg['checked']['delivered', 'push'] and not runs:
        out.append('push hints delivered but no session-hint run seen (no hook_success naming it: a format change?)')
    if agg['bad_files']:
        out.append('%d transcripts could not be read: their hints are not checked' % agg['bad_files'])
    if older['missing'] + older['extra'] + older['error']:
        out.append('older sessions (started before --since) since then: missing %d, extra %d, errors %d: problems if '
                   'they already ran the new hooks; else restart them and check again with --since after the restart'
                   % (older['missing'], older['extra'], older['error']))
    if ctx['before_install']:
        out.append('--since is before the last install + %d s (%sZ): sessions started in between ran without '
                   'session-hint' % (INSTALL_MARGIN_S, ctx['before_install']))
    return out + blind_warnings(agg, ctx)


def gate_text(agg, ctx):
    """(exit code, due by kind, outcomes, the verdict) of the checked sessions."""
    code, due, n = verdict(agg['checked'])
    unproven = ' and '.join(k for k in KINDS if not due[k])
    text = ('PASS', 'FAIL', 'NOT PROVEN YET: no due %s hint in a session started since --since' % unproven)[code]
    if code == 2 and not ctx['main']:
        text = 'NO DATA: no main session transcript changed since --since'
    elif code == 2 and agg['seen']['push'] and not agg['seen']['results']:
        text = NO_RESULTS
    return code, due, n, text


def gate_line(agg, ctx):
    """The gate line and the exit code."""
    code, due, n, text = gate_text(agg, ctx)
    return ('gate  due push %d and compaction %d (>=1 each), missing %d, pending %d, extra %d, errors %d -> %s' % (
        due['push'], due['compaction'], n['missing'], n['pending'], n['extra'], n['error'], text)), code


def report(agg, ctx):
    """Print the counts, the warnings, the problems and the gate line; the exit code."""
    print('== session-hint delivered: since %s (%sZ), %d main and %d subagent transcripts changed since, %d audit files '
          'skipped, %d unreadable lines, %d unreadable files' % (ctx['since_text'], ctx['since'], ctx['main'],
                                                                ctx['sub'], ctx['audit_skipped'], agg['bad'],
                                                                agg['bad_files']))
    print('sessions with outcomes  checked (started since): %d; older (may run the hooks read at their start, not '
          'gated): %d' % (agg['sessions']['checked'], agg['sessions']['older']))
    seen = agg['seen']
    print('seen  in checked sessions: Bash calls %d, with "push" or "pr create" %d, with a result %d, compactions %d, hook attachments '
          '%d, on the hook\'s events %d' % (seen['bash'], seen['push'], seen['results'], seen['compactions'],
                                           seen['hooks'], seen['events']))
    for group in ('checked', 'older'):
        n = agg[group]
        print('%-8s push: delivered %d, missing %d, pending %d, extra %d; compaction: delivered %d, missing %d, pending '
              '%d, extra %d; subagent extra %d, own compaction (not gated) %d; errors %d' % (
                  group, *(n[o, k] for k in KINDS for o in OUTCOMES), n['extra', 'subagent'], n['known', 'subagent'],
                  n['error', 'run']))
    runs = agg['runs']
    print('time  session-hint runs that printed: %d, durationMs p50 %d, p95 %d, max %d' % (
        len(runs), pct(runs, 0.5), pct(runs, 0.95), max(runs or [0])))
    print('not attributed  hook errors and cancels with no command on PostToolUse:Bash or SessionStart (any hook of '
          'the event): %d' % agg['unattributed'])
    for text in warnings(agg, ctx):
        print('WARN  ' + text)
    for outcome, kind, proj, sid, ts in agg['problems'][:SHOW_PROBLEMS]:
        short = proj_name(proj)[:40]
        print('problem  %-8s %-24s %-40s %s  %sZ' % (outcome, kind, short, sid[:8], ts[:19]))
    if len(agg['problems']) > SHOW_PROBLEMS:
        print('problem  ... and %d more' % (len(agg['problems']) - SHOW_PROBLEMS))
    line, code = gate_line(agg, ctx)
    print(line)
    return code


def doctor_report(agg, ctx):
    """--doctor: the line scripts/doctor.sh shows and a WARN for every problem; the exit code."""
    code, _, n, text = gate_text(agg, ctx)
    c = agg['checked']
    print('delivery: session-hint in sessions started since %sZ (%s): with outcomes %d; push delivered %d, missing %d; '
          'compaction delivered %d, missing %d; pending %d, extra %d, errors %d -> %s' % (
              ctx['since'], ctx['since_text'], agg['sessions']['checked'], c['delivered', 'push'], c['missing', 'push'],
              c['delivered', 'compaction'], c['missing', 'compaction'], n['pending'], n['extra'], n['error'], text))
    warns = ['FAIL: missing %d, extra %d, errors %d (the list: %s)' % (
        n['missing'], n['extra'], n['error'], ' '.join(['python3 -I', shlex.quote(os.path.abspath(__file__))] + ctx['again']))
        ] if code == 1 else []
    warns += [text] if text == NO_RESULTS else []
    for w in warns + warnings(agg, ctx):
        print('WARN: session-hint delivery: ' + w)
    return code


def failures_line(days, projects):
    """The line of hook failures. When it breaks, the delivery verdict above it and the exit code stay, so the import is
    here too."""
    try:
        import hook_failures
        hook_failures.report(days, projects)
    except Exception as e:
        print('WARN: hook failures: not checked (%s: %s)' % (type(e).__name__, str(e)[:120]))

# ---------------------------------------------------------------- the command line


def install_time(manifest):
    """installed_at of the setup manifest plus INSTALL_MARGIN_S, or None."""
    try:
        with open(manifest, encoding='utf-8') as fh:
            t = datetime.datetime.fromisoformat(json.load(fh).get('installed_at').replace('Z', '+00:00'))
    except (OSError, ValueError, AttributeError, TypeError):
        return None
    return t + datetime.timedelta(seconds=INSTALL_MARGIN_S)


def since_utc(value):
    """(UTC time as in transcripts, epoch) of a datetime or an ISO text (local time when it has no offset), or None."""
    try:
        t = value if isinstance(value, datetime.datetime) else datetime.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    t = t.astimezone() if t.tzinfo is None else t
    return t.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S'), t.timestamp()


def window(days, installed):
    """(since pair, its text) of --days: now minus days, but not before the last install: a session started before it
    may still run the hooks it read at its start."""
    by_days = since_utc(datetime.datetime.now().astimezone() - datetime.timedelta(days=days))
    if installed and installed[1] > by_days[1]:
        return installed, 'the last install + %d s, within %d days' % (INSTALL_MARGIN_S, days)
    return by_days, '%d days ago' % days


def main():
    ap = argparse.ArgumentParser(description='Check that Claude Code delivered session-hint hints in live sessions.')
    ap.add_argument('--since', help='local date or time, e.g. 2026-10-26T21:30: sessions started since are checked '
                                    '(default: the last install, installed_at in ~/.claude/.setup-manifest.json)')
    ap.add_argument('--days', type=int, help='instead of --since: sessions started in the last N days, not before the '
                                             'last install (doctor.sh: 7)')
    ap.add_argument('--claude-home', default=CLAUDE_DIR,
                    help='the folder with projects/ and .setup-manifest.json (default ~/.claude)')
    ap.add_argument('--doctor', action='store_true', help='one line and WARNs for scripts/doctor.sh, not the report; '
                                                          'with --days also the line of hook failures')
    ap.add_argument('--include-audit', action='store_true', help='also sessions of this repo and /tmp')
    ap.add_argument('--jobs', type=int, default=min(8, os.cpu_count() or 4), help='reading workers')
    args = ap.parse_args()
    if args.since and args.days is not None:
        ap.error('--since and --days exclude each other')
    if args.days is not None and not 1 <= args.days <= MAX_DAYS:
        ap.error('--days must be 1 to %d' % MAX_DAYS)
    manifest = os.path.join(args.claude_home, '.setup-manifest.json')
    installed = since_utc(install_time(manifest))
    if args.days is not None:
        since_pair, since_text = window(args.days, installed)
    else:
        since_pair = since_utc(args.since) if args.since else installed   # (UTC text, epoch)
        since_text = args.since or 'the last install + %d s' % INSTALL_MARGIN_S
    if since_pair is None:
        ap.error('--since must be a local date or time like 2026-10-26T21:30 (no default without installed_at in '
                 '~/.claude/.setup-manifest.json)')
    if args.jobs < 1:
        ap.error('--jobs must be positive')
    projects = os.path.join(args.claude_home, 'projects')
    files, audit_skipped = list_files(since_pair[1], args.include_audit, projects=projects)
    sub = sum(session_of(proj, path)[1] for proj, path in files)
    agg = collect(files, since_pair[0], args.jobs)
    before = installed[0] if args.since and installed and since_pair[1] < installed[1] else ''
    ctx = {'since_text': since_text, 'since': since_pair[0], 'main': len(files) - sub, 'sub': sub,
           'audit_skipped': audit_skipped, 'before_install': before,
           'no_projects': '' if os.access(projects, os.R_OK | os.X_OK) else projects,
           'no_install': (manifest, args.days) if args.days is not None and not installed else None,
           'again': [shlex.quote(a) for a in sys.argv[1:] if a != '--doctor']}   # the report of the same window
    code = (doctor_report if args.doctor else report)(agg, ctx)
    if args.doctor and args.days is not None:
        failures_line(args.days, projects)
    return code


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:   # the check itself broke: exit 3, not 1, which reads as FAIL and leads to a rollback
        traceback.print_exc()
        sys.exit(3)
