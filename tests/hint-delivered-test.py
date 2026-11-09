#!/usr/bin/env python3
"""hint-delivered-test: tests/hint-delivered.py as a command on made-up transcripts in a temp HOME (offline, no real
data): every outcome and report line, the exit codes 0, 1, 2 and 3, resumed copies, a pending call next to a line
still being written and in an idle file (where an open compaction stays pending), a hint twice, subagent records and
files, an older session with problems, a file not changed since --since, more problems than are printed, an audit
project with and without --include-audit, the default --since from the setup manifest, a --since before it, a local
--since in another time zone, an unreadable file, no data, usage errors, the check itself broken. verify.sh runs it.

Run (from the repo root): python3 -I tests/hint-delivered-test.py -> the last line "hint-delivered test: N cases,
F failed"; exit 0 when none failed.
"""
import datetime
import json
import os
import subprocess
import sys
import tempfile
import time

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS)   # -I drops the script folder from sys.path
from hint_common import TEXT  # noqa: E402

SCRIPT = os.path.join(TESTS, 'hint-delivered.py')
SINCE = '2026-01-01T00:00:00+00:00'
BASE = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
HOOK = '/h/.claude/hooks/session-hint.sh'

# ---------------------------------------------------------------- made-up transcript records


def rec(kind, sec, sidechain=False, **kw):
    """A record sec seconds after SINCE (before it when negative); the same kind and second give the same uuid, as a
    copy appended on resume has."""
    t = BASE + datetime.timedelta(seconds=sec)
    return dict(type=kind, timestamp=t.strftime('%Y-%m-%dT%H:%M:%S.000Z'), sessionId='s', cwd='/p',
                uuid='%s-%d' % (kind, sec), isSidechain=sidechain, **kw)


def push_recs(sec, tid, cmd, stdout='', sidechain=False):
    """A Bash call and its successful result a second later."""
    use = {'type': 'tool_use', 'id': tid, 'name': 'Bash', 'input': {'command': cmd}}
    res = {'type': 'tool_result', 'tool_use_id': tid, 'content': stdout}
    return [rec('assistant', sec, sidechain, message={'role': 'assistant', 'content': [use]}),
            rec('user', sec + 1, sidechain, message={'role': 'user', 'content': [res]},
                toolUseResult={'stdout': stdout, 'stderr': ''})]


def attach(sec, sidechain=False, **a):
    return rec('attachment', sec, sidechain, attachment=a)


def hint_rec(sec, name, tid, *texts, sidechain=False):
    return attach(sec, sidechain, type='hook_additional_context', content=list(texts), hookName=name, toolUseID=tid,
                  hookEvent=name.split(':')[0])


def run_rec(sec, tid, exit_code, ms, command=HOOK, stdout='{}'):
    return attach(sec, type='hook_success', hookName='PostToolUse:Bash', toolUseID=tid, command=command,
                  exitCode=exit_code, durationMs=ms, stdout=stdout, stderr='', content='')


def say(sec):
    return rec('assistant', sec, message={'role': 'assistant', 'content': [{'type': 'text', 'text': 'ok'}]})


def boundary(sec):
    return rec('system', sec, subtype='compact_boundary')


PR_URL = 'https://github.com/o/r/pull/1'


def transcripts():
    """{name: records}; a string is written as it is (a line still being written)."""
    hi = rec('user', 0, message={'role': 'user', 'content': 'hi'})
    no_result = rec('assistant', 2, message={'role': 'assistant', 'content': [
        {'type': 'tool_use', 'id': 't0', 'name': 'Bash', 'input': {'command': 'git push'}}]})   # still running
    pushed = [{'type': 'summary', 'summary': 'a title', 'leafUuid': 'l1'},   # no timestamp: skipped
              hi, *push_recs(1, 't1', 'git push origin main', 'To x'),
              hint_rec(3, 'PostToolUse:Bash', 't1', TEXT['PostToolUse']), run_rec(4, 't1', 0, 12),
              attach(5, type='todo_reminder', content=[])]   # not a hook attachment: not seen as one
    settled = pushed + [
        boundary(20), rec('user', 21, isCompactSummary=True, message={'role': 'user', 'content': 'summary'}),
        hint_rec(22, 'SessionStart', 'SessionStart', '## an app hook', TEXT['SessionStart']), say(24)]
    clean = settled + [no_result]   # a push call with no result and no answer after it: not judged yet
    error = attach(27, type='hook_non_blocking_error', hookName='PostToolUse:Bash', toolUseID='t9', command=HOOK,
                   exitCode=1, stderr='')
    every = clean + [
        *push_recs(5, 't2', 'git push --dry-run'),   # nothing due, nothing delivered
        *push_recs(7, 't3', 'git push'),   # missing; its event cancelled with no command: not attributed
        attach(8, type='hook_cancelled', hookName='PostToolUse:Bash', toolUseID='t3', hookEvent='PostToolUse'),
        *push_recs(9, 't4', 'git push', ' ! [rejected]  main -> main'),   # a failed push with a hint: extra
        attach(10, type='hook_non_blocking_error', hookName='PostToolUse:Bash', toolUseID='t4', exitCode=1,
               command='/h/.claude/hooks/doc-reminder.sh'),   # another hook's error: not counted
        hint_rec(11, 'PostToolUse:Bash', 't4', TEXT['PostToolUse']),
        *push_recs(12, 't5', 'npm test'),   # a hint for a call with no push: extra
        hint_rec(14, 'PostToolUse:Bash', 't5', TEXT['PostToolUse']),
        *push_recs(15, 't6', 'git push', sidechain=True),   # subagent records: their hint is extra
        hint_rec(16, 'PostToolUse:Bash', 't6', TEXT['PostToolUse'], sidechain=True),
        *push_recs(17, 't7', 'git push'),   # another text: missing and extra; a slow run
        hint_rec(19, 'PostToolUse:Bash', 't7', TEXT['PostToolUse'][:-1]), run_rec(23, 't7', 0, 3000),
        boundary(25), say(26),   # a compaction with no hint: missing
        error, run_rec(28, 't9', 1, 5),   # two errors
        hint_rec(29, 'SessionStart', 'SessionStart', TEXT['SessionStart']),   # no compaction open: extra
        boundary(30), hint_rec(31, 'SessionStart', 'SessionStart', TEXT['SessionStart'][:-1]), say(32),   # another
        *push_recs(33, 't8', 'git push'),   # the text under another hook: missing and extra
        run_rec(34, 't8', 0, 9999, '/h/.claude/hooks/doc-reminder.sh', 'see /h/.claude/hooks/session-hint.sh'),
        hint_rec(35, 'PostToolUseFailure:Bash', 't8', TEXT['PostToolUse']), say(36),
        attach(36, type='hook_error_during_execution', hookName='SessionStart', hookEvent='SessionStart'),
        *push_recs(40, 't10', 'git push origin HEAD'),   # the text as a string, not a list: delivered
        attach(42, type='hook_additional_context', content=TEXT['PostToolUse'], hookName='PostToolUse:Bash',
               toolUseID='t10', hookEvent='PostToolUse'), run_rec(43, 't10', 0, 20),   # three runs: a true median
        boundary(44), boundary(45),   # a compaction closed by the next one: missing; the last one: pending
        attach(46, type='hook_cancelled', hookName='PostToolUse:Edit')]   # another tool's event: not counted
    every.sort(key=lambda r: r.get('timestamp', ''))
    # a due push with no assistant message after it, and the line of its hint still being written
    pending = settled + [*push_recs(90, 'p1', 'git push'),
                       '{"type": "attachment", "timestamp": "2026-01-01T00:01:32.000Z", "attachment": {"t']
    missed = [*push_recs(60, 'z1', 'git push'), say(62)]
    return {
        'every': every, 'clean': clean, 'push-only': pushed + [no_result], 'failed-run': clean + [error], 'empty': [hi],
        # resumed: the chain appended again (same uuid and time) after new records, then the session goes on
        'resumed': settled + [rec('queue-operation', 80), boundary(20),
                              hint_rec(3, 'PostToolUse:Bash', 't1', TEXT['PostToolUse']), say(81), no_result],
        # the idle one is written as changed an hour ago; its compaction left open stays pending there too
        'pending-push': pending, 'pending-idle': pending[:-1] + [boundary(91), pending[-1]],
        'subagent': [rec('user', 70, True, message={'role': 'user', 'content': 'go'}),
                     hint_rec(71, 'PostToolUse:Bash', 'a1', TEXT['PostToolUse'], sidechain=True)],
        # gh pr create that opened a PR is due the PR text: delivered; with the push text it is missing and extra
        'pr': [hi, *push_recs(1, 'r1', 'gh pr create --fill', PR_URL), hint_rec(3, 'PostToolUse:Bash', 'r1', TEXT['PullRequest']),
               run_rec(4, 'r1', 0, 12), *push_recs(5, 'r2', 'gh pr create --fill', PR_URL),
               hint_rec(7, 'PostToolUse:Bash', 'r2', TEXT['PostToolUse']), say(8)],
        # a hint twice: two attachments, one attachment with two lines, a compaction with two lines; subagent files
        # with two lines, and one that started before --since (older); errors and cancels with no command
        'twice': [hi, *push_recs(1, 'w1', 'git push'), hint_rec(3, 'PostToolUse:Bash', 'w1', TEXT['PostToolUse']),
                  hint_rec(4, 'PostToolUse:Bash', 'w1', TEXT['PostToolUse']), *push_recs(5, 'w2', 'git push'),
                  hint_rec(7, 'PostToolUse:Bash', 'w2', TEXT['PostToolUse'], TEXT['PostToolUse']), boundary(8),
                  hint_rec(9, 'SessionStart', 'SessionStart', TEXT['SessionStart'], TEXT['SessionStart']), say(10),
                  attach(11, type='hook_non_blocking_error', hookName='SessionStart', hookEvent='SessionStart'),
                  attach(12, type='hook_cancelled', hookName='SessionStart:compact', hookEvent='SessionStart'),
                  hint_rec(13, 'PostToolUse:Bash', ['w1'], TEXT['PostToolUse'])],   # toolUseID not a string: extra
        'subagent-twice': [rec('user', 70, True, message={'role': 'user', 'content': 'go'}),
                           hint_rec(71, 'PostToolUse:Bash', 'a1', TEXT['PostToolUse'], TEXT['PostToolUse'],
                                    sidechain=True)],
        'subagent-older': [rec('user', -10, True, message={'role': 'user', 'content': 'go'}),
                           hint_rec(75, 'PostToolUse:Bash', 'a2', TEXT['PostToolUse'], sidechain=True)],
        'many': [hi, *[r for i in range(21) for r in push_recs(100 + 2 * i, 'm%d' % i, 'git push')], say(150)],
        'missed': missed, 'locked': missed,   # the locked one is written with no permissions
        # results under another key: push calls the reader cannot judge
        'unpaired': [hi, rec('assistant', 1, message={'role': 'assistant', 'content': [
                         {'type': 'tool_use', 'id': 'u1', 'name': 'Bash', 'input': {'command': 'git push'}}]}),
                     rec('user', 2, message={'role': 'user', 'content': [
                         {'type': 'tool_result', 'toolUseId': 'u1', 'content': ''}]}),
                     hint_rec(3, 'PostToolUse:Bash', 'u1', TEXT['PostToolUse']), say(4),
                     rec('user', 5, message={'role': 'user', 'content': [
                         {'type': 'tool_result', 'tool_use_id': ['u1'], 'content': ''}]})],   # an id not a string
        # an older session with problems but no missing hint
        'older-extra': [rec('user', -60, message={'role': 'user', 'content': 'hi'}), *push_recs(50, 'q1', 'git push'),
                        hint_rec(52, 'PostToolUse:Bash', 'q1', TEXT['PostToolUse'], TEXT['PostToolUse']), say(53),
                        attach(54, type='hook_non_blocking_error', hookName='PostToolUse:Bash', toolUseID='q1',
                               command=HOOK, exitCode=1)],
        'older': [rec('user', -60, message={'role': 'user', 'content': 'hi'}), *push_recs(-50, 'o0', 'git push'),
                  run_rec(-40, 'o0', 0, 7), attach(-30, type='hook_cancelled', hookName='SessionStart'),
                  *push_recs(50, 'o1', 'git push'), hint_rec(52, 'PostToolUse:Bash', 'o1', TEXT['PostToolUse']),
                  *push_recs(53, 'o2', 'git push'), say(55),
                  attach(56, type='hook_non_blocking_error', hookName='PostToolUse:Bash', toolUseID='o2',
                         command=HOOK, exitCode=1)],
        'stale': missed}   # in a file changed before --since: not read

# ---------------------------------------------------------------- what the report must say


def header(main, sub, bad=0, since=SINCE, utc='2026-01-01T00:00:00', audit=0, bad_files=0):
    return ('== session-hint delivered: since %s (%sZ), %d main and %d subagent transcripts changed since, %d audit '
            'files skipped, %d unreadable lines, %d unreadable files' % (since, utc, main, sub, audit, bad, bad_files))


def group_line(group, push=(0, 0, 0, 0), compaction=(0, 0, 0, 0), sub=0, errors=0):
    """push and compaction: (delivered, missing, pending, extra)."""
    return ('%-8s push: delivered %d, missing %d, pending %d, extra %d; compaction: delivered %d, missing %d, pending '
            '%d, extra %d; subagent extra %d; errors %d' % (group, *push, *compaction, sub, errors))


def sessions(checked, older):
    return ('sessions with outcomes  checked (started since): %d; older (may run the hooks read at their start, not '
            'gated): %d' % (checked, older))


def seen(bash, push, results, compactions, hooks, events):
    return ('seen  in checked sessions: Bash calls %d, with "push" or "pr create" %d, with a result %d, compactions %d, hook '
            "attachments %d, on the hook's events %d" % (bash, push, results, compactions, hooks, events))


def gate(push, compaction, missing, pending, extra, errors, outcome):
    return 'gate  due push %d and compaction %d (>=1 each), missing %d, pending %d, extra %d, errors %d -> %s' % (
        push, compaction, missing, pending, extra, errors, outcome)


def unattributed(n):
    return ('not attributed  hook errors and cancels with no command on PostToolUse:Bash or SessionStart (any hook of '
            'the event): %d' % n)


def warn_older(missing=1, extra=0, errors=1):
    return ('WARN  older sessions (started before --since) since then: missing %d, extra %d, errors %d: problems if '
            'they already ran the new hooks; else restart them and check again with --since after the restart' % (
                missing, extra, errors))


WARN_SLOW = 'WARN  slowest session-hint run 3000 ms, over 2500 ms (half the hook timeout): a slow machine or a hung jq'
WARN_NO_RUNS = 'WARN  push hints delivered but no session-hint run seen (no hook_success naming it: a format change?)'
WARN_UNREADABLE = 'WARN  1 transcripts could not be read: their hints are not checked'
WARN_UNPAIRED = ('WARN  %d push calls with an answer after them but no result (a transcript format change?): their '
                 'hints are not checked')
WARN_BEFORE = ('WARN  --since is before the last install + 60 s (2026-01-01T00:00:00Z): sessions started in between '
               'ran without session-hint')
UNPROVEN = 'NOT PROVEN YET: no due %s hint in a session started since --since'
TIME0 = 'time  session-hint runs that printed: 0, durationMs p50 0, p95 0, max 0'
CLEAN = {'==': header(2, 0), 'sessions': sessions(1, 1), 'seen': seen(2, 2, 1, 1, 3, 3),
         'checked': group_line('checked', (1, 0, 0, 0), (1, 0, 0, 0)),
         'older': group_line('older', (1, 1, 0, 0), errors=1),
         'time': 'time  session-hint runs that printed: 1, durationMs p50 12, p95 12, max 12',
         'not attributed': unattributed(0), 'WARN': [warn_older()], 'problem': 0,
         'gate': gate(1, 1, 0, 0, 0, 0, 'PASS')}
NOTHING = {'==': header(1, 0), 'sessions': sessions(0, 0), 'seen': seen(0, 0, 0, 0, 0, 0),
           'checked': group_line('checked'), 'older': group_line('older'), 'time': TIME0,
           'not attributed': unattributed(0), 'WARN': [], 'problem': 0}
OLDER = [('sess-older.jsonl', 'older'), ('stale.jsonl', 'stale')]
KEYS = ('==', 'sessions', 'seen', 'checked', 'older', 'time', 'not attributed', 'gate')


def case(name, projects, args, want, code, installed_at=None, env=None, older=True):
    """projects {project: [(file, transcript)]} (the older project too unless older is False); installed_at for the
    setup manifest; env on top of HOME."""
    return dict(name=name, projects=projects, args=args, want=want, code=code, installed_at=installed_at,
                env=env or {}, older=older)


CLEAN_FILES = {'clean': [('sess-clean.jsonl', 'clean')]}
CASES = [
    case('every', {'every': [('sess-every.jsonl', 'every'), ('sess-every/subagents/agent-a.jsonl', 'subagent')]},
         ['--since', SINCE, '--jobs', '2'],
         {**CLEAN, '==': header(2, 1), 'seen': seen(9, 8, 7, 5, 19, 17),
          'checked': group_line('checked', (2, 3, 0, 4), (1, 3, 1, 2), sub=2, errors=2),
          'time': 'time  session-hint runs that printed: 3, durationMs p50 20, p95 3000, max 3000',
          'not attributed': unattributed(2), 'WARN': [WARN_SLOW, warn_older(), WARN_UNPAIRED % 1], 'problem': 16,
          'problem 1': 'problem  extra    subagent                 -p-every                                 sess-eve  '
                       '2026-01-01T00:00:16Z',
          'gate': gate(5, 4, 6, 1, 8, 2, 'FAIL')}, 1),
    case('clean', CLEAN_FILES, ['--since', SINCE], CLEAN, 0),
    case('resumed', {'resumed': [('sess-resumed.jsonl', 'resumed')]}, ['--since', SINCE], CLEAN, 0),
    case('pr', {'pr': [('sess-pr.jsonl', 'pr')]}, ['--since', SINCE],
         {**CLEAN, 'seen': seen(2, 2, 2, 0, 3, 3), 'checked': group_line('checked', (1, 1, 0, 1)), 'problem': 2,
          'gate': gate(2, 0, 1, 0, 1, 0, 'FAIL')}, 1),
    case('push-only', {'push-only': [('sess-push.jsonl', 'push-only')]}, ['--since', SINCE],
         {**CLEAN, 'seen': seen(2, 2, 1, 0, 2, 2), 'checked': group_line('checked', (1, 0, 0, 0)),
          'gate': gate(1, 0, 0, 0, 0, 0, UNPROVEN % 'compaction')}, 2),
    case('failed-run', {'failed-run': [('sess-failed.jsonl', 'failed-run')]}, ['--since', SINCE],
         {**CLEAN, 'seen': seen(2, 2, 1, 1, 4, 4), 'checked': group_line('checked', (1, 0, 0, 0), (1, 0, 0, 0), errors=1),
          'problem': 1, 'gate': gate(1, 1, 0, 0, 0, 1, 'FAIL')}, 1),
    case('pending-push', {'pending-push': [('sess-pending.jsonl', 'pending-push')]}, ['--since', SINCE],
         {**CLEAN, '==': header(2, 0, bad=1), 'seen': seen(2, 2, 2, 1, 3, 3),
          'checked': group_line('checked', (1, 0, 1, 0), (1, 0, 0, 0)), 'gate': gate(1, 1, 0, 1, 0, 0, 'PASS')}, 0),
    case('pending-idle', {'pending-idle': [('sess-idle.jsonl', 'pending-idle')]}, ['--since', SINCE],
         {**CLEAN, '==': header(2, 0, bad=1), 'seen': seen(2, 2, 2, 2, 3, 3),
          'checked': group_line('checked', (1, 1, 0, 0), (1, 0, 1, 0)), 'problem': 1,
          'gate': gate(2, 1, 1, 1, 0, 0, 'FAIL')}, 1),
    case('twice', {'twice': [('sess-twice.jsonl', 'twice'), ('sess-twice/subagents/agent-a.jsonl', 'subagent-twice'),
                             ('sess-twice/subagents/workflows/wf_1/agent-b.jsonl', 'subagent-older')]},
         ['--since', SINCE],
         {**CLEAN, '==': header(2, 2), 'seen': seen(2, 2, 2, 1, 7, 7),
          'checked': group_line('checked', (2, 0, 0, 3), (1, 0, 0, 1), sub=2),
          'older': group_line('older', (1, 1, 0, 0), sub=1, errors=1), 'time': TIME0,
          'not attributed': unattributed(2), 'WARN': [WARN_NO_RUNS, warn_older(extra=1)], 'problem': 6,
          'gate': gate(2, 1, 0, 0, 6, 0, 'FAIL')}, 1),
    case('older-problems', {**CLEAN_FILES, 'older-extra': [('sess-oldx.jsonl', 'older-extra')]}, ['--since', SINCE],
         {**CLEAN, 'older': group_line('older', (1, 0, 0, 1), errors=1),
          'WARN': [warn_older(missing=0, extra=1, errors=1)]}, 0, older=False),
    case('many', {'many': [('sess-many.jsonl', 'many')]}, ['--since', SINCE],
         {**CLEAN, 'seen': seen(21, 21, 21, 0, 0, 0), 'checked': group_line('checked', (0, 21, 0, 0)), 'time': TIME0,
          'problem': 21, 'problem last': 'problem  ... and 1 more', 'gate': gate(21, 0, 21, 0, 0, 0, 'FAIL')}, 1),
    case('audit-skipped', {**CLEAN_FILES, '-private-tmp-x': [('sess-tmp.jsonl', 'missed')]}, ['--since', SINCE],
         {**CLEAN, '==': header(2, 0, audit=1)}, 0),
    case('audit-included', {**CLEAN_FILES, '-private-tmp-x': [('sess-tmp.jsonl', 'missed')]},
         ['--since', SINCE, '--include-audit'],
         {**CLEAN, '==': header(3, 0), 'sessions': sessions(2, 1), 'seen': seen(3, 3, 2, 1, 3, 3),
          'checked': group_line('checked', (1, 1, 0, 0), (1, 0, 0, 0)), 'problem': 1,
          'gate': gate(2, 1, 1, 0, 0, 0, 'FAIL')}, 1),
    # installed_at plus the minute of margin is SINCE; a --since before it gets a WARN
    case('manifest', CLEAN_FILES, [], {**CLEAN, '==': header(2, 0, since='the last install + 60 s')}, 0,
         installed_at='2025-12-31T23:59:00Z'),
    case('before-install', CLEAN_FILES, ['--since', '2025-12-31T23:00:00+00:00'],
         {**CLEAN, '==': header(1, 0, since='2025-12-31T23:00:00+00:00', utc='2025-12-31T23:00:00'),
          'sessions': sessions(1, 0), 'older': group_line('older'), 'WARN': [WARN_BEFORE]}, 0,
         installed_at='2025-12-31T23:59:00Z', older=False),
    case('local-since', CLEAN_FILES, ['--since', '2025-12-31T19:00:00'],   # 19:00 at UTC-5 is SINCE
         {**CLEAN, '==': header(2, 0, since='2025-12-31T19:00:00')}, 0, env={'TZ': 'Etc/GMT+5'}),
    case('unreadable', {'clean': [('sess-clean.jsonl', 'clean'), ('locked.jsonl', 'locked')]}, ['--since', SINCE],
         {**CLEAN, '==': header(3, 0, bad_files=1), 'WARN': [WARN_UNREADABLE, warn_older()]}, 0),
    case('empty', {'empty': [('sess-empty.jsonl', 'empty')]}, ['--since', SINCE],
         {**NOTHING, 'gate': gate(0, 0, 0, 0, 0, 0, UNPROVEN % 'push and compaction')}, 2, older=False),
    case('no-data', {}, ['--since', SINCE],
         {**NOTHING, '==': header(0, 0), 'WARN': ['WARN  cannot read the transcripts folder <home>/.claude/projects'],
          'gate': gate(0, 0, 0, 0, 0, 0, 'NO DATA: no main session transcript changed since --since')}, 2, older=False),
    case('unpaired', {'unpaired': [('sess-unpaired.jsonl', 'unpaired')]}, ['--since', SINCE],
         {**NOTHING, 'seen': seen(1, 1, 0, 0, 1, 1), 'WARN': [WARN_UNPAIRED % 1, 'WARN  2 tool results with no string '
                                                       'tool_use_id (a transcript format change?): their calls are not paired'],
          'gate': gate(0, 0, 0, 0, 0, 0, 'NO DATA: push calls but none with a result (a format change?)')}, 2,
         older=False),
]

# ---------------------------------------------------------------- running


def make_home(home, projects, installed_at, data):
    """Transcripts under home/.claude/projects (stale: changed before --since, pending-idle: an hour ago, locked: no
    permissions) and the setup manifest."""
    mtimes = {'stale': datetime.datetime(2025, 12, 1, tzinfo=datetime.timezone.utc).timestamp(),
              'pending-idle': time.time() - 3600}
    os.makedirs(os.path.join(home, '.claude'), exist_ok=True)
    for proj, files in projects.items():
        for name, key in files:
            folder = proj if proj.startswith('-') else '-p-' + proj   # a full name: an audit project
            path = os.path.join(home, '.claude', 'projects', folder, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write(''.join(r if isinstance(r, str) else json.dumps(r) + '\n' for r in data[key]))
            if key in mtimes:
                os.utime(path, (mtimes[key], mtimes[key]))
            if key == 'locked':
                os.chmod(path, 0)
    if installed_at:
        with open(os.path.join(home, '.claude', '.setup-manifest.json'), 'w', encoding='utf-8') as fh:
            json.dump({'installed_at': installed_at}, fh)


def check(name, out, code, want, want_code):
    """The differences between the report and the lines it must have."""
    lines = out.splitlines()
    got = {k: next((line for line in lines if line.startswith(k)), None) for k in KEYS}
    got['WARN'] = [line for line in lines if line.startswith('WARN')]
    problems = [line for line in lines if line.startswith('problem')]
    got['problem'], got['problem 1'], got['problem last'] = len(problems), (problems or [None])[0], (problems or [None])[-1]
    fails = ['FAIL %s: exit %d, want %d' % (name, code, want_code)] if code != want_code else []
    return fails + ['FAIL %s %s:\n  got  %r\n  want %r' % (name, k, got[k], v) for k, v in want.items() if got[k] != v]


def run(home, args, env=None):
    cmd = [sys.executable, '-I', SCRIPT, *args] + ([] if '--jobs' in args or not args else ['--jobs', '1'])
    return subprocess.run(cmd, env=dict(os.environ, HOME=home, **(env or {})), capture_output=True, text=True,
                          timeout=120)


# (name, args, exit code, text in stderr, setup manifest): usage errors (no --since and no manifest or a broken one,
# --jobs 0) and the check itself broken (installed_at so late that adding the minute of margin overflows)
ERRORS = (('no-since', [], 2, 'no default without installed_at', None),
          ('bad-manifest', [], 2, 'no default without installed_at', '{"installed_at": 5'),
          ('jobs-0', ['--since', SINCE, '--jobs', '0'], 2, '--jobs must be positive', None),
          ('since-and-days', ['--since', SINCE, '--days', '7'], 2, '--since and --days exclude each other', None),
          ('days-0', ['--days', '0'], 2, '--days must be 1 to 3650', None),
          ('days-too-many', ['--days', '3651'], 2, '--days must be 1 to 3650', None),
          ('crash', [], 3, 'OverflowError', '{"installed_at": "9999-12-31T23:59:59Z"}'))


def error_fails(tmp, data):
    """ERRORS: each must exit with its code, print nothing to stdout and its reason to stderr."""
    fails = []
    for name, args, code, reason, manifest in ERRORS:
        home = os.path.join(tmp, 'error-' + name)
        make_home(home, {'clean': [('sess-clean.jsonl', 'clean')]}, None, data)
        if manifest:
            with open(os.path.join(home, '.claude', '.setup-manifest.json'), 'w', encoding='utf-8') as fh:
                fh.write(manifest)
        p = run(home, args)
        if p.returncode != code or p.stdout or reason not in p.stderr:
            fails.append('FAIL %s: exit %d, stdout %r, stderr %r' % (name, p.returncode, p.stdout[:80], p.stderr[-200:]))
    return fails


def main():
    data, fails, failed, ran = transcripts(), [], 0, 0
    with tempfile.TemporaryDirectory(prefix='hint-delivered-test-') as tmp:
        for c in CASES:
            if c['name'] == 'unreadable' and os.geteuid() == 0:
                continue   # root reads a file with no permissions
            home = os.path.join(tmp, '-p-' + c['name'])   # the project's folder name comes earlier in the path too
            make_home(home, dict(c['projects'], **({'older': OLDER} if c['older'] else {})), c['installed_at'], data)
            p = run(home, c['args'], c['env'])
            case_fails = check(c['name'], p.stdout.replace(home, '<home>'), p.returncode, c['want'], c['code'])
            case_fails += ['FAIL %s: stderr %r' % (c['name'], p.stderr[-300:])] if p.stderr else []
            fails, failed, ran = fails + case_fails, failed + bool(case_fails), ran + 1
        errors = error_fails(tmp, data)
        fails, failed, ran = fails + errors, failed + len(errors), ran + len(ERRORS)
    print('\n'.join(fails + ['hint-delivered test: %d cases, %d failed' % (ran, failed)]))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
