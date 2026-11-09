#!/usr/bin/env python3
"""doctor-test: scripts/doctor.sh --live --skip-tests in a sandbox (CLAUDE_HOME, HOME_AGENTS, GIT_EXCLUDES and BIN_DIR in
a temp folder with a manifest of no items; offline, no real data). The delivery line of tests/hint-delivered.py
--doctor --days 7 on made-up transcripts of the last hours (those of tests/hint-delivered-test.py, moved to now): PASS,
FAIL, push calls with no result, a blind reader (5 main transcripts of checked sessions with no Bash call; not 4, not
with a subagent or an older one as the fifth, not when one has Bash calls; 5 with no usable record, not 4), a result
under another block type, a compaction summary with no boundary, no installed_at, no data, the check itself broken
(also a script that python stops with exit 1 or 2, or that prints no delivery line); the line of hook failures of the
same run: 0 with no WARN in every case with none, every kind, one from before the install, in a subagent and in /tmp,
each uuid once, nothing older than the window or from a file not changed in it, no text of a command or of stderr, more
projects than it names, the same transcripts through a window with the failure and one without, an unreadable
transcript, a line that cannot be parsed, attachments of an unknown shape, a reader that sees no hook attachment, a
broken tests/hook_failures.py that costs only its line; the WARN lines of the hooks' error logs, internal errors apart
from ShapeDrift, an unreadable log; project CLAUDE.md, AGENTS.md and STATUS over 30 KB or unreadable, a folder of
projects with no such files or none at all; the docs lines of the projects (STATUS length and its archive, a big .md, a
README behind the code, active projects with no instructions or card, the old template); the lines of the docs repo of
docs-sync and its error log; the line of the scan inside a commit; and the exit code, which no WARN changes. verify.sh
runs it.

Run (from the repo root): python3 -I tests/doctor-test.py -> the last line "doctor test: N cases, F failed"; exit 0
when none failed.
"""
import datetime
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

TESTS = os.path.dirname(os.path.abspath(__file__))
DOCTOR = os.path.join(os.path.dirname(TESTS), 'scripts', 'doctor.sh')
HOOKS = os.path.join(os.path.dirname(TESTS), 'hooks')
HINT_DELIVERED = shlex.quote(os.path.join(TESTS, 'hint-delivered.py'))   # as the FAIL WARN names it
_spec = importlib.util.spec_from_file_location('hint_delivered_test', os.path.join(TESTS, 'hint-delivered-test.py'))
hdt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hdt)
# the made-up sessions start two hours ago, a minute after the install: inside the delivery line's 7 days
hdt.BASE = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0) - datetime.timedelta(hours=2)
INSTALLED = (hdt.BASE - datetime.timedelta(seconds=60)).strftime('%Y-%m-%dT%H:%M:%SZ')
OLD_INSTALL = (hdt.BASE - datetime.timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ')   # then the window is 7 days
SINCE = '%sZ (the last install + 60 s, within 7 days)' % hdt.BASE.strftime('%Y-%m-%dT%H:%M:%S')
DAYS_AGO = re.compile(r'since (\S+)Z \(7 days ago\)')
T = '2026-10-27T10:00:00Z'   # error-log lines
SECRET = 'TOKEN=doctor-test'   # in the command and stderr of made-up failures: doctor prints neither
FORK = 'bash: fork: Resource temporarily unavailable\n'
DAY = 86400
GIT_LOCAL = ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES',
             'GIT_COMMON_DIR', 'GIT_PREFIX')   # what a git hook exports; verify.sh clears the same before its probe
FAILURES_0 = re.compile(r'  hook failures: 0 in 7 days \(\d+ transcripts, \d+ hook attachments\)\Z')
FAILURES_N = re.compile(r'  WARN: hook failures: (\d+ in |not checked)')
UNCOUNTED = '  WARN: hook failures: 1 transcripts could not be read: their failures are not counted'
TORN = '  WARN: hook failures: 1 lines with a hook type could not be parsed: their failures are not counted'
UNKNOWN = ('  WARN: hook failures: attachments of an unknown shape: %s (a transcript format change? Compare with '
           'docs/compat.md): their failures are not counted')
NO_HOOKS = ('  WARN: hook failures: no hook attachment seen in %d transcripts (a transcript format change?): the 0 proves '
            'nothing')


def delivery(outcomes, push, compaction, rest, verdict, since=SINCE):
    """push and compaction: (delivered, missing); rest: (pending, extra, errors)."""
    return ('  delivery: session-hint in sessions started since %s: with outcomes %d; push delivered %d, missing %d; '
            'compaction delivered %d, missing %d; pending %d, extra %d, errors %d -> %s' % (
                since, outcomes, *push, *compaction, *rest, verdict))


def seven_days_ago(line):
    """The line with "since <7 days ago>" when its since is now minus 7 days (give or take 5 minutes)."""
    m = DAYS_AGO.search(line or '')
    if not m:
        return line
    t = datetime.datetime.fromisoformat(m.group(1) + '+00:00')
    off = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7) - t
    return line.replace(m.group(0), 'since <7 days ago>') if abs(off.total_seconds()) < 300 else line


def warn(text):
    return '  WARN: session-hint delivery: ' + text


def errlog_warns(name, kind, n, last):
    return ['  WARN: %s %s: %d in CLAUDE_HOME/logs/%s.err, last: %s' % (name, kind, n, name, last)]


def hook_rec(sec, kind, stderr=SECRET, sidechain=False, **kw):
    """A made-up hook attachment with a value in its command and stderr, sec seconds after BASE."""
    return hdt.attach(sec, sidechain, type=kind, hookName='PreToolUse:Bash', hookEvent='PreToolUse', toolUseID='f1',
                      command='/h/hooks/bash-guard.sh ' + SECRET, stderr=stderr, **kw)


def failures_warn(total, files, hooks, kinds, projects, sec, last_proj, days=7):
    """The WARN line of hook failures; sec: the last one, seconds after BASE, in the local time of this run."""
    last = (hdt.BASE + datetime.timedelta(seconds=sec)).astimezone().strftime('%Y-%m-%d %H:%M')
    return ('  WARN: hook failures: %d in %d days (%d transcripts, %d hook attachments): %s; by project: %s; last %s '
            'local time, %s' % (total, days, files, hooks, kinds, projects, last, last_proj))


PASS = delivery(1, (1, 0), (1, 0), (0, 0, 0), 'PASS')
UNPROVEN = 'NOT PROVEN YET: no due push and compaction hint in a session started since --since'
CLEAN = {'clean': [('sess-clean.jsonl', 'clean')]}
EMPTY = {'empty': [('sess-e%d.jsonl' % i, 'empty') for i in range(5)]}
UNTIMED = {'untimed': [('sess-u%d.jsonl' % i, 'untimed') for i in range(5)]}
UNPAIRED = '%d push calls with an answer after them but no result (a transcript format change?): their hints are not checked'
LOGS = {'session-hint': '%s JqExit 127\n%s ShapeDrift tool_response\n%s ShapeDrift tool_input.command\n' % (T, T, T),
        'doc-reminder': '%s ShapeDrift cwd duration_ms\n' % T,
        'dup-guard': '%s HookError git show rc=128' % T,   # the last line without its newline counts too
        # a HookExit line has no date: the EXIT trap of bash-guard must not fork
        'bash-guard': 'no-time HookExit 128\n%s TimeLimit long command\n%s ShimExit 1\n%s ShapeDrift cwd\n%s JqExit 127\n'
                      '%s ShapeDrift tool_input.command\n%s ShimOutput\n' % (T, T, T, T, T, T),
        'node-std': '%s ShapeDrift source\n%s LockBusy state\n' % (T, T)}
# stale: a file changed before the 7 days; the /tmp project is an audit one: the delivery line skips it, this line not
HOOK_FAILED = {**CLEAN, 'erp': [('sess-f.jsonl', 'hook-failed'), ('sess-c.jsonl', 'hook-failed-copy'),
                                ('sess-f/subagents/agent-a.jsonl', 'hook-failed-sub'), ('stale.jsonl', 'stale')],
               '-private-tmp-x': [('sess-t.jsonl', 'hook-failed-tmp')]}
# (name, projects as in hint-delivered-test.py, error logs, the delivery line, the WARN lines in order, legends,
# installed_at)
CASES = [
    ('pass', CLEAN, {}, PASS, [], 0, INSTALLED),
    ('old-install', CLEAN, {}, delivery(1, (1, 0), (1, 0), (0, 0, 0), 'PASS', '<7 days ago>'), [], 0, OLD_INSTALL),
    ('fail', {'clean': [('sess-clean.jsonl', 'clean'), ('sess-missed.jsonl', 'missed')]}, {},
     delivery(2, (1, 1), (1, 0), (0, 0, 0), 'FAIL'),
     [warn('FAIL: missing 1, extra 0, errors 0 (the list: python3 -I %h --days 7 --claude-home %s)')], 0, INSTALLED),
    ('no-results', {'unpaired': [('sess-unpaired.jsonl', 'unpaired')]}, {},
     delivery(0, (0, 0), (0, 0), (0, 0, 0), 'NO DATA: push calls but none with a result (a format change?)'),
     [warn('NO DATA: push calls but none with a result (a format change?)'), warn(UNPAIRED % 1),
      warn('2 tool results with no string tool_use_id (a transcript format change?): their calls are not paired')], 0,
     INSTALLED),
    ('blind', EMPTY, {}, delivery(0, (0, 0), (0, 0), (0, 0, 0), UNPROVEN),
     [warn('no Bash call seen in 5 main transcripts of sessions started since then (a transcript format change?)'),
      NO_HOOKS % 5], 0, INSTALLED),
    ('not-blind', {'empty': EMPTY['empty'][:4]}, {}, delivery(0, (0, 0), (0, 0), (0, 0, 0), UNPROVEN), [], 0,
     INSTALLED),
    ('subagent-not-main', {'empty': EMPTY['empty'][:4] + [('sess-e0/subagents/agent-a.jsonl', 'subagent-quiet')]}, {},
     delivery(0, (0, 0), (0, 0), (0, 0, 0), UNPROVEN), [NO_HOOKS % 5], 0, INSTALLED),
    ('older-not-checked', {'empty': EMPTY['empty'][:4] + [('sess-older.jsonl', 'older-quiet')]}, {},
     delivery(0, (0, 0), (0, 0), (0, 0, 0), UNPROVEN), [NO_HOOKS % 5], 0, INSTALLED),
    ('bash-seen', {'empty': EMPTY['empty'][:4], **CLEAN}, {}, PASS, [], 0, INSTALLED),
    ('unreadable', {'clean': CLEAN['clean'] + [('locked.jsonl', 'locked')]}, {}, PASS,
     [warn('1 transcripts could not be read: their hints are not checked'), UNCOUNTED], 0, INSTALLED),
    ('no-data', {}, {}, delivery(0, (0, 0), (0, 0), (0, 0, 0), 'NO DATA: no main session transcript changed since '
                                 '--since'), [warn('cannot read the transcripts folder %c/projects')], 0, INSTALLED),
    ('envelope', UNTIMED, {}, delivery(0, (0, 0), (0, 0), (0, 0, 0), UNPROVEN),
     [warn('5 main transcripts changed since then have no record the reader can use, 5 unreadable lines (a transcript '
           'format change?)'), NO_HOOKS % 5], 0, INSTALLED),
    # 4 main transcripts: a subagent one and one that cannot be opened (its own WARN) do not count
    ('envelope-4', {'untimed': UNTIMED['untimed'][:4] + [('sess-u0/subagents/agent-a.jsonl', 'untimed'),
                                                       ('locked.jsonl', 'locked')]}, {},
     delivery(0, (0, 0), (0, 0), (0, 0, 0), UNPROVEN),
     [warn('1 transcripts could not be read: their hints are not checked'), UNCOUNTED, NO_HOOKS % 6], 0, INSTALLED),
    ('hook-failures', HOOK_FAILED, {}, PASS,
     [failures_warn(9, 5, 18, 'hook_non_blocking_error 4, hook_cancelled 3, hook_error_during_execution 1, hook_success '
                    'with a failed fork 1', '-p-erp 8, -private-tmp-x 1', 120, '-private-tmp-x'), TORN,
      UNKNOWN % 'hook_success 1'], 1, INSTALLED),
    ('hook-unknown', {**CLEAN, 'new': [('sess-n.jsonl', 'hook-unknown')]}, {}, PASS,
     [UNKNOWN % 'hook_renamed_error 2, hook_success 1'], 0, INSTALLED),
    ('hook-failures-projects', {**CLEAN, **{'p%d' % i: [('sess-m.jsonl', 'many-%d' % i)] for i in range(7)}}, {}, PASS,
     [failures_warn(7, 8, 10, 'hook_non_blocking_error 7', '-p-p0 1, -p-p1 1, -p-p2 1, -p-p3 1, -p-p4 1, 2 more', 206,
                    '-p-p6')], 1, INSTALLED),
    # two push calls in one answer, one still running: not a call with an answer after it
    ('parallel', {'clean': CLEAN['clean'] + [('sess-parallel.jsonl', 'parallel')]}, {},
     delivery(2, (1, 0), (1, 0), (1, 0, 0), 'PASS'), [], 0, INSTALLED),
    ('result-renamed', {'clean': CLEAN['clean'] + [('sess-result.jsonl', 'renamed-result')]}, {}, PASS,
     [warn(UNPAIRED % 1)], 0, INSTALLED),
    ('boundary-renamed', {'clean': CLEAN['clean'] + [('sess-renamed.jsonl', 'renamed-boundary')]}, {}, PASS,
     [warn('compaction summaries 2, compactions seen 1 (a transcript format change?): their hints are not checked')],
     0, INSTALLED),
    ('no-installed-at', CLEAN, {}, delivery(1, (1, 0), (1, 0), (0, 0, 0), 'PASS', '<7 days ago>'),
     [warn('no installed_at in %c/.setup-manifest.json: the window is the last 7 days, sessions started before the '
           'install may count')], 0, 'garbage'),
    ('unreadable-log', CLEAN, {'session-hint': ('%s JqExit 127\n' % T, 0o200)}, PASS,
     ['  WARN: CLAUDE_HOME/logs/session-hint.err is not readable: its lines are not shown'], 0, INSTALLED),
    ('logs', CLEAN, LOGS, PASS,
     errlog_warns('dup-guard', 'internal errors', 1, '%s HookError git show rc=128' % T) +
     errlog_warns('doc-reminder', 'input of an unknown shape', 1, '%s ShapeDrift cwd duration_ms' % T) +
     errlog_warns('session-hint', 'internal errors', 1, '%s JqExit 127' % T) +
     errlog_warns('session-hint', 'input of an unknown shape', 2, '%s ShapeDrift tool_input.command' % T) +
     errlog_warns('bash-guard', 'internal errors', 5, '%s ShimOutput' % T) +
     errlog_warns('bash-guard', 'input of an unknown shape', 2, '%s ShapeDrift tool_input.command' % T) +
     errlog_warns('node-std', 'internal errors', 1, '%s LockBusy state' % T) +
     errlog_warns('node-std', 'input of an unknown shape', 1, '%s ShapeDrift source' % T), 8, INSTALLED),
    # installed_at so late that its minute of margin overflows: the check itself breaks (exit 3)
    ('broken', CLEAN, {}, None,
     ['  WARN: delivery: tests/hint-delivered.py broke (exit 3), last line: OverflowError: date value out of range'], 0,
     '9999-12-31T23:59:59Z'),
]
EXIT_CODES = (('clean', 0), ('missed', 1), (None, 2))   # a transcript kind (None: no transcript) and the exit code
# hint-delivered.py that python stops (a syntax error: exit 1; a usage error: exit 2), that prints no delivery line,
# that crashes after it (exit 3), or the real script with a broken module (exit 3): doctor.sh says the check broke
# instead of printing its lines; (name, files of tests/: None for the real one, exit code, its last line)
REAL = {'hint-delivered.py': None, 'hint_common.py': None, 'hook_failures.py': None, 'replay_common.py': None}
FAKES = (('exit-1', {'hint-delivered.py': "print('Traceback (most recent call last):')\n"
                                         "print('SyntaxError: invalid syntax')\nraise SystemExit(1)"},
          1, 'SyntaxError: invalid syntax'),
         ('exit-2', {'hint-delivered.py': "import sys\nsys.stderr.write('usage: hint-delivered.py [-h]\\n')\n"
                                         "raise SystemExit(2)"}, 2, 'usage: hint-delivered.py [-h]'),
         ('no-line', {'hint-delivered.py': "print('something else')"}, 0, 'something else'),
         ('late-crash', {'hint-delivered.py': "print('delivery: x')\nraise SystemExit(3)"}, 3, 'delivery: x'),
         ('broken-module', dict(REAL, **{'hint_common.py': "raise ImportError('broken on purpose')"}), 3,
          'ImportError: broken on purpose'))
# a broken tests/hook_failures.py, at import or at work: its WARN in place of its line, the delivery line stays
FAILURE_FAKES = (('failures-import', "raise ImportError('broken on purpose')", 'ImportError: broken on purpose'),
                 ('failures-run', "def report(*args):\n    raise OSError('broken on purpose')",
                  'OSError: broken on purpose'))


def sandbox(home, projects, logs, installed_at, data):
    """The made-up transcripts, a manifest of no items installed at installed_at, the error logs; the doctor's env.
    CLAUDE_HOME is not HOME/.claude, so the delivery check finds the transcripts only through --claude-home."""
    base = os.path.join(home, 'sandbox')
    hdt.make_home(base, projects, None, data)
    claude = os.path.join(base, '.claude')
    with open(os.path.join(claude, '.setup-manifest.json'), 'w', encoding='utf-8') as fh:
        json.dump({'schema': 1, 'ref': 'WORKTREE', 'commit': '-', 'installed_at': installed_at, 'how': 'doctor-test',
                   'items': [], 'files': {}}, fh)
    os.makedirs(os.path.join(claude, 'logs'), exist_ok=True)
    for name, text in logs.items():
        text, mode = text if isinstance(text, tuple) else (text, None)
        with open(os.path.join(claude, 'logs', name + '.err'), 'w', encoding='utf-8') as fh:
            fh.write(text)
        if mode is not None:
            os.chmod(fh.name, mode)
    projects = os.path.join(home, 'projects')
    os.makedirs(os.path.join(projects, 'p'), exist_ok=True)
    with open(os.path.join(projects, 'p', 'CLAUDE.md'), 'w', encoding='utf-8') as fh:
        fh.write('small\n')
    return dict(os.environ, HOME=home, CLAUDE_HOME=claude, HOME_AGENTS=os.path.join(home, 'AGENTS.md'),
                GIT_EXCLUDES=os.path.join(home, 'git-ignore'), BIN_DIR=os.path.join(home, 'bin'),
                PROJECTS_DIR=projects)


def check(name, p, want_line, want_warns, legends, claude):
    """The differences between doctor's output and the lines it must have."""
    lines = p.stdout.splitlines()
    got_line = seven_days_ago(next((ln for ln in lines if ln.startswith('  delivery:')), None))
    got_warns = [ln for ln in lines if ln.startswith('  WARN:')]
    want_warns = [w.replace('%s', shlex.quote(claude)).replace('%c', claude).replace('%h', HINT_DELIVERED)
                  for w in want_warns]
    fails = ['FAIL %s: exit %d, stderr %r' % (name, p.returncode, p.stderr[-300:])] if p.returncode or p.stderr else []
    fails += [] if lines[:1] == ['live = WORKTREE, drift 0'] else ['FAIL %s: first line %r' % (name, lines[:1])]
    fails += [] if got_line == want_line else ['FAIL %s delivery:\n  got  %r\n  want %r' % (name, got_line, want_line)]
    fails += [] if got_warns == want_warns else ['FAIL %s WARN:\n  got  %r\n  want %r' % (name, got_warns, want_warns)]
    zero = [ln for ln in lines if ln.startswith('  hook failures:')]   # none when a WARN has the count or the check broke
    good = not zero if want_line is None or any(map(FAILURES_N.match, want_warns)) else (
        len(zero) == 1 and FAILURES_0.match(zero[0]))
    fails += [] if good else ['FAIL %s hook failures: %r' % (name, zero)]
    fails += ['FAIL %s: a raw value in the output' % name] if SECRET in p.stdout else []
    n = sum(1 for ln in lines if ln.startswith('        ('))
    return fails + ([] if n == legends else ['FAIL %s: %d legend lines, want %d' % (name, n, legends)])


def exit_code_fails(tmp, data):
    """hint-delivered.py --doctor alone: the gate's exit code (doctor.sh shows 0 to 2 alike) and the line in place of
    the report."""
    fails = []
    for kind, code in EXIT_CODES:
        home = os.path.join(tmp, 'exit-%s' % kind)
        hdt.make_home(home, {kind: [('sess-x.jsonl', kind)]} if kind else {}, None, data)
        p = hdt.run(home, ['--days', '1', '--doctor'])
        if p.returncode != code or not p.stdout.startswith('delivery: ') or p.stderr:
            fails.append('FAIL exit-%s: exit %d, want %d, stdout %r, stderr %r' % (
                kind, p.returncode, code, p.stdout[:80], p.stderr[-200:]))
    return fails


def window_fails(tmp, data):
    """The same transcripts through hint-delivered.py: a failure 3 days old shows in --doctor --days 7, --days 1 says 0
    with no WARN, with no --days or no --doctor there is no such line. The 0 and its counts in full."""
    home = os.path.join(tmp, 'window')
    hdt.make_home(home, {'clean': CLEAN['clean'] + [('sess-w.jsonl', 'hook-failed-old')]}, INSTALLED, data)
    out = {}
    for args in ('--days 7 --doctor', '--days 1 --doctor', '--since 2026-01-01 --doctor', '--days 7'):
        p = hdt.run(home, args.split())
        out[args] = [ln for ln in p.stdout.splitlines() if 'hook failures' in ln] if p.returncode == 0 else p.returncode
    want = {'--days 7 --doctor': [failures_warn(1, 2, 4, 'hook_non_blocking_error 1', '-p-clean 1', -3 * DAY,
                                                '-p-clean')[2:]],
            '--days 1 --doctor': ['hook failures: 0 in 1 days (2 transcripts, 3 hook attachments)'],
            '--since 2026-01-01 --doctor': [], '--days 7': []}
    return ['FAIL window %s:\n  got  %r\n  want %r' % (k, out[k], v) for k, v in want.items() if out[k] != v]


def fake_run(tmp, name, files, data):
    """doctor.sh of a copy of scripts/ next to these files of tests/ (None: the real one): the run and CLAUDE_HOME."""
    repo = os.path.join(tmp, 'fake ' + name)
    os.makedirs(os.path.join(repo, 'tests'))
    shutil.copytree(os.path.dirname(DOCTOR), os.path.join(repo, 'scripts'))
    for f, text in files.items():
        if text is None:
            shutil.copy2(os.path.join(TESTS, f), os.path.join(repo, 'tests', f))
        else:
            with open(os.path.join(repo, 'tests', f), 'w', encoding='utf-8') as fh:
                fh.write(text + '\n')
    env = sandbox(os.path.join(tmp, 'fake-home ' + name), CLEAN, {}, INSTALLED, data)
    return subprocess.run(['/bin/bash', os.path.join(repo, 'scripts', 'doctor.sh'), '--live', '--skip-tests'], env=env,
                          capture_output=True, text=True, timeout=120), env['CLAUDE_HOME']


def fake_fails(tmp, data):
    """FAKES and FAILURE_FAKES; one list of fails per fake."""
    out = []
    for name, files, code, last in FAKES:
        p, claude = fake_run(tmp, name, files, data)
        want = ['  WARN: delivery: tests/hint-delivered.py broke (exit %d), last line: %s' % (code, last)]
        out.append(check('fake-' + name, p, None, want, 0, claude))
    for name, text, last in FAILURE_FAKES:
        p, claude = fake_run(tmp, name, dict(REAL, **{'hook_failures.py': text}), data)
        out.append(check('fake-' + name, p, PASS, ['  WARN: hook failures: not checked (%s)' % last], 0, claude))
    return out


def commit_scan_fails(tmp, data):
    """The line of the scan inside a commit comes from real commits in a throwaway repo, on the hook of the sandbox, with the
    keys and the command of global/settings.json: nothing else runs them. No keys, no line; a dead scan or one that stops
    every commit is a WARN."""
    repo = os.path.dirname(TESTS)
    with open(os.path.join(repo, 'global', 'settings.json'), encoding='utf-8') as fh:
        keys = {k: v for k, v in json.load(fh)['env'].items() if k.startswith('GIT_CONFIG_')}
    lands = '  WARN: commit scan: a commit with a made-up token lands: '
    no_word = lands + 'no word from the scan (a key of the env, or git before 2.54?)'
    cases = (('no-keys', {}, True, [], False), ('no-settings', None, True, [], False),
             ('broken', '{', True, ['  WARN: commit scan: the env of settings.json does not read: '], True),
             ('ok', keys, True, ['  commit scan: OK, a commit with a made-up token stops'], False),
             ('no-file', keys, False, [lands + 'commit-leaks: secrets in this commit are not checked (no hook file)'], False),
             ('other-event', dict(keys, GIT_CONFIG_VALUE_0='post-commit'), True, [no_word], False),
             ('stops-all', dict(keys, GIT_CONFIG_VALUE_1='echo bad >&2; exit 1'), True, ['  WARN: commit scan: a clean commit stops: bad'], False),
             ('stops-other', dict(keys, GIT_CONFIG_VALUE_1='! git diff --cached --name-only | grep -q b.txt || exit 1'), True,
              ['  WARN: commit scan: a commit with a made-up token stops, not on the scan: '], False))
    fails = []
    for name, env_keys, has_file, want, prefix in cases:
        env = sandbox(os.path.join(tmp, 'scan home ' + name), CLEAN, {}, INSTALLED, data)
        claude = env['CLAUDE_HOME']
        if env_keys is not None:
            text = env_keys if isinstance(env_keys, str) else json.dumps({'env': env_keys})
            with open(os.path.join(claude, 'settings.json'), 'w', encoding='utf-8') as fh:
                fh.write(re.sub(r'[^ ]*/\.claude/hooks/', lambda _: "'%s/hooks/'" % claude, text))
        if has_file:
            os.makedirs(os.path.join(claude, 'hooks'), exist_ok=True)
            for f in ('commit-leaks.sh', 'commit-leaks.toml'):
                shutil.copy2(os.path.join(repo, 'hooks', f), os.path.join(claude, 'hooks', f))
        p = subprocess.run(['/bin/bash', DOCTOR, '--live', '--skip-tests'], env=env, capture_output=True, text=True, timeout=120)
        got = [ln for ln in p.stdout.splitlines() if 'commit scan' in ln]
        matched = len(got) == len(want) and all(g.startswith(w) if prefix else g == w for g, w in zip(got, want))
        if not matched or p.returncode:
            fails.append('FAIL commit scan %s: exit %d\n  got  %r\n  want %r' % (name, p.returncode, got, want))
    return fails


def scan_probe_fails(tmp):
    """The probe may run from a git hook, as verify.sh may: git exports GIT_DIR there and ignores SIGPIPE, which a child keeps.
    It has to leave the repo of the caller alone and end."""
    repo = os.path.dirname(TESTS)
    caller = os.path.join(tmp, 'caller')
    subprocess.run(['git', 'init', '-q', caller], check=True)
    env = dict(os.environ, GIT_DIR=os.path.join(caller, '.git'), GIT_INDEX_FILE=os.path.join(caller, '.git', 'index'))
    cmd = ['/bin/bash', os.path.join(repo, 'scripts', 'commit-scan-probe.sh'), os.path.join(repo, 'global', 'settings.json'),
           os.path.join(repo, 'hooks')]
    try:
        p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=20, restore_signals=False)
    except subprocess.TimeoutExpired:
        return ['FAIL commit scan probe: no end with SIGPIPE ignored']
    fails = [] if p.returncode == 0 else ['FAIL commit scan probe from a git hook: exit %d %r' % (p.returncode, p.stdout)]
    commits = subprocess.run(['git', '-C', caller, 'rev-list', '--all', '--count'], capture_output=True, text=True).stdout.strip()
    return fails + ([] if commits == '0' else ['FAIL commit scan probe: %s commits in the repo of the caller' % commits])


def state_file_fails(tmp, data):
    """The sizes of project files: over the limit at each known place, a project name with a space, unreadable, a link
    to nowhere, a FIFO (must not hang); exactly 30 KB, a file deeper in the project and another name say nothing. A
    folder with no such file and no folder at all are a WARN too: they must not read as small files."""
    env = sandbox(os.path.join(tmp, 'state home'), CLEAN, {}, INSTALLED, data)
    root = env['PROJECTS_DIR']
    over, limit = 30 * 1024 + 1, 30 * 1024
    files = {'demo ui/CLAUDE.md': 51908, 'a/AGENTS.md': over, 'a/STATUS.md': over, 'a/docs/STATUS.md': over,
             'a/.claude/state/STATUS.md': 148521, 'b/CLAUDE.md': limit, 'b/docs/sub/STATUS.md': over,
             'b/notes.md': over, 'b/AGENTS.md': 1}
    for rel, size in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write('x' * size)
    os.chmod(os.path.join(root, 'b/AGENTS.md'), 0o200)
    os.symlink('/nonexistent/doctor-test', os.path.join(root, 'b/STATUS.md'))
    os.mkdir(os.path.join(root, 'c'))
    os.mkfifo(os.path.join(root, 'c/CLAUDE.md'))
    run = lambda e: subprocess.run(['/bin/bash', DOCTOR, '--live', '--skip-tests'], env=e, capture_output=True, text=True,
                                   timeout=120)
    over, unreadable = '  WARN: project file over 30 KB: %s: %d KB', '  WARN: project file not readable: %s'
    want = [unreadable % 'c/CLAUDE.md', over % ('demo ui/CLAUDE.md', 51), over % ('a/AGENTS.md', 31)]
    want += [unreadable % 'b/AGENTS.md'] if os.geteuid() else []
    want += [over % ('a/STATUS.md', 31), unreadable % 'b/STATUS.md', over % ('a/docs/STATUS.md', 31),
             over % ('a/.claude/state/STATUS.md', 146)]
    fails = check('state-files', run(env), PASS, want, 1, env['CLAUDE_HOME'])
    none = sandbox(os.path.join(tmp, 'none home'), CLEAN, {}, INSTALLED, data)
    os.remove(os.path.join(none['PROJECTS_DIR'], 'p', 'CLAUDE.md'))
    for name, folder in (('no-project-files', none['PROJECTS_DIR']), ('no-projects-folder', os.path.join(tmp, 'no folder'))):
        want = ['  WARN: project files not checked: no CLAUDE.md, AGENTS.md or STATUS in the folders of ' + folder]
        fails += check(name, run(dict(none, PROJECTS_DIR=folder)), PASS, want, 0, none['CLAUDE_HOME'])
    return fails


def stack_fails(tmp, data):
    """The stack lines of the Node standard: node_std.py of a copy of the skill in CLAUDE_HOME, its versions.json with
    dates moved to today. The projects out of support and behind, then versions.json checked over 35 days ago and a
    newer LTS line due; with no skill one plain line; a broken versions.json one WARN; doctor's exit the same."""
    today = datetime.date.today()
    ago = lambda days: (today - datetime.timedelta(days=days)).isoformat()   # noqa: E731
    lines = {'20': {'lts': ago(1200), 'end': ago(100)}, '24': {'lts': ago(400), 'end': ago(-400)},
             '26': {'lts': ago(20), 'end': ago(-900)}}
    run = lambda e: subprocess.run(['/bin/bash', DOCTOR, '--live', '--skip-tests'], env=e, capture_output=True, text=True,
                                   timeout=120)   # noqa: E731
    projects = '  WARN: stack: Node out of support or within 6 months of it in 1 projects: old (20)', \
        '  WARN: stack: Node behind the standard in 1 projects: mid (24)'
    due = ['  WARN: stack: versions.json checked %s (40 days ago), over 35 days: a base release of the standard\'s '
           'versions is due, with tests/new-project-test.sh' % ago(40), '  WARN: stack: Node 27 has been an LTS line '
           'since %s, 14 days or more: the standard (Node 26) is due for a base release' % ago(20)]
    fails = []
    for name, checked, newer, want in (('stack', ago(3), {}, list(projects)),
                                       ('stack-due', ago(40), {'27': {'lts': ago(20), 'end': ago(-1300)}},
                                        list(projects) + due), ('stack-broken', None, {}, None)):
        env = sandbox(os.path.join(tmp, name + ' home'), CLEAN, {}, INSTALLED, data)
        skill = os.path.join(env['CLAUDE_HOME'], 'skills', 'new-project')
        shutil.copytree(os.path.join(os.path.dirname(TESTS), 'skills', 'own', 'new-project'), skill,
                        ignore=shutil.ignore_patterns('__pycache__'))
        with open(os.path.join(skill, 'versions.json'), encoding='utf-8') as fh:
            versions = dict(json.load(fh), node='26', _checked=checked, node_lines=dict(lines, **newer))
        with open(os.path.join(skill, 'versions.json'), 'w', encoding='utf-8') as fh:
            fh.write(json.dumps(versions) if checked else 'not json')
        for folder, nvmrc in (('old', '20'), ('mid', '24'), ('std', '26')):
            os.makedirs(os.path.join(env['PROJECTS_DIR'], folder))
            for rel, text in (('package.json', '{"name": "x"}'), ('.nvmrc', nvmrc + '\n')):
                with open(os.path.join(env['PROJECTS_DIR'], folder, rel), 'w', encoding='utf-8') as fh:
                    fh.write(text)
        p = run(env)
        if want is not None:
            fails += check(name, p, PASS, want, 1, env['CLAUDE_HOME'])
            line = '  stack: Node standard 26 (end of life %s), versions.json checked %s (%d days ago); 3 folders with ' \
                   'package.json: on the standard 1, newer 0, behind 1, end of life within 6 months or past 1, no Node ' \
                   'pinned 0, not read 0' % (ago(-900), checked, (today - datetime.date.fromisoformat(checked)).days)
            fails += [] if line in p.stdout.splitlines() else ['FAIL %s: no line %r' % (name, line)]
        elif p.returncode or not any(ln.startswith('  WARN: stack: node_std.py failed (exit 1): node_std: '
                                                    'ScaffoldError: versions.json:') for ln in p.stdout.splitlines()):
            fails.append('FAIL %s: exit %d, %r' % (name, p.returncode, p.stdout[-300:]))
    plain = run(sandbox(os.path.join(tmp, 'no skill home'), CLEAN, {}, INSTALLED, data)).stdout.splitlines()
    want = '  stack: not checked, no CLAUDE_HOME/skills/new-project/node_std.py (a tag before v2026.11.19)'
    return fails + ([] if want in plain else ['FAIL stack-no-skill: no line %r' % want])


def docs_fails(tmp, data):
    """The docs lines on made-up projects: STATUS over 60 lines with an archive next to it, under its folder or none (60
    lines say nothing, 61 with no newline at the end do); an .md over 200 KB, not in an archive path (an "archiver" is
    none), node_modules or .claude/worktrees (200 KB says nothing); a README (.md or .rst) 10 commits and over 21 days
    behind HEAD (9 commits or 21 days say nothing); active projects, a commit or a session with a record of the last 30
    days (also in a worktree of the project, or before a last record over 64 KB; an old session that only got records
    with no time, or a subagent's, is none), with no instruction file or no card (.claude/CLAUDE.md holds one too); the
    old template, active or not; a repo git cannot read; a transcript with no time at all; a worktree copy and a link
    skipped. Then the summary and one legend."""
    env = sandbox(os.path.join(tmp, 'docs home'), CLEAN, {}, INSTALLED, data)
    root, claude = env['PROJECTS_DIR'], env['CLAUDE_HOME']
    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    genv = dict({k: v for k, v in os.environ.items() if k not in GIT_LOCAL}, GIT_CONFIG_GLOBAL='/dev/null',
                GIT_CONFIG_NOSYSTEM='1')   # run from a git hook, a fixture commit never reaches the caller's repo

    def write(rel, text):
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(text)

    def git(proj, args, at=now):
        os.makedirs(os.path.join(root, proj), exist_ok=True)
        dates = dict(genv, GIT_COMMITTER_DATE='@%d' % at, GIT_AUTHOR_DATE='@%d' % at)
        return subprocess.run(['git', '-c', 'user.name=Doctor', '-c', 'user.email=doctor@example.com', '-c',
                               'commit.gpgsign=false', '-c', 'init.defaultBranch=main', '-C', os.path.join(root, proj)] + args,
                              env=dates, check=True, capture_output=True, text=True).stdout

    def commit(proj, rel, at):
        write(os.path.join(proj, rel), '%s %d\n' % (rel, at))
        for args in (['init', '-q'], ['add', rel], ['commit', '-q', '-m', rel]):
            git(proj, args, at)

    def transcript(proj, rel, at, mtime=None, tail=''):   # a record with a time (and tail after it), then one with none,
        path = os.path.join(claude, 'projects', re.sub('[^A-Za-z0-9]', '-', os.path.join(root, proj)) + rel)   # as
        os.makedirs(os.path.dirname(path), exist_ok=True)   # Claude Code appends
        stamp = datetime.datetime.fromtimestamp(at, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write('{"type":"user","timestamp":"%s"%s}\n{"type":"last-prompt"}\n' % (stamp, tail) if at else
                     '{"type":"last-prompt"}\n')
        if mtime is not None:
            os.utime(path, (mtime, mtime))

    lines = lambda n: ''.join('line %d\n' % i for i in range(n))
    card, day = '## Розмір (підтверджено власником 01.01.2026)\n', 86400
    write('p01 status/STATUS.md', lines(61)[:-1])
    write('p01 status/.claude/state/STATUS.md', lines(61))
    write('p01 status/docs/STATUS.md', lines(60))
    for rel, n in (('STATUS.md', 61), ('STATUS-archive.md', 1), ('docs/STATUS.md', 70),
                   ('docs/_work/STATUS-2026-09-16-archive.md', 1)):
        write('p02 archived/' + rel, lines(n))
    for rel, kb in (('docs/decisions.md', 200 * 1024 + 1), ('CHANGELOG.md', 250 * 1024), ('notes.md', 200 * 1024),
                    ('docs/archive/old.md', 300 * 1024), ('docs/Archive-2025.md', 300 * 1024),
                    ('docs/archived/plan.md', 300 * 1024), ('docs/archiver-notes.md', 210 * 1024),
                    ('node_modules/pkg/README.md', 300 * 1024), ('.claude/worktrees/x/big.md', 300 * 1024)):
        write('p03 journals/' + rel, 'x' * kb)
    readme = {'p04 stale readme': (40, [now - 15 * day + 3600 * i for i in range(10)]),
              'p05 nine commits': (40, [now - 15 * day + 3600 * i for i in range(9)]),
              'p06 lag 21': (26, [now - 26 * day + 3600 * (i + 1) for i in range(9)] + [now - 5 * day + 100]),
              'p18 readme rst': (40, [now - 15 * day + 3600 * i for i in range(10)])}
    for proj, (age, times) in readme.items():
        commit(proj, 'README.rst' if proj.endswith('rst') else 'README.md', now - age * day)
        for i, at in enumerate(times):
            commit(proj, 'src/%d.ts' % i, at)
        write(proj + '/CLAUDE.local.md', card)
    lag = (readme['p04 stale readme'][1][-1] - (now - 40 * day)) // day
    commit('p07 bare', 'main.py', now - day)
    write('p08 sessions/notes.txt', 'x\n')
    transcript('p08 sessions', '/a.jsonl', now - day)
    transcript('p08 sessions', '--claude-worktrees-w1/b.jsonl', now - 2 * day)
    transcript('p08 sessions', '/s1/subagents/c.jsonl', now - day)
    transcript('p08 sessions', '/old.jsonl', now - 60 * day)
    commit('p09 no card', 'app.ts', now - day)
    write('p09 no card/CLAUDE.md', '# Rules\n')
    commit('p10 carded', 'app.ts', now - day)
    write('p10 carded/CLAUDE.local.md', card)
    write('p11 old sleeping/AGENTS.md', '# Project Agent Operating Standard\n')
    commit('p12 old active', 'app.ts', now - day)
    write('p12 old active/AGENTS.md', '# Project Agent Operating Standard\n')
    write('p12 old active/CLAUDE.local.md', card)
    write('p13 worktree copy/.git', 'gitdir: /nonexistent\n')
    write('p13 worktree copy/STATUS.md', lines(61))
    os.symlink(os.path.join(root, 'p01 status'), os.path.join(root, 'p14 link'))
    write('p15 old session/notes.txt', 'x\n')
    transcript('p15 old session', '/s.jsonl', now - 60 * day)
    transcript('p15 old session', '/t.jsonl', now - day, now - 40 * day)   # the file older than 30 days: not read
    transcript('p15 old session', '/u.jsonl', 0)
    write('p16 big record/notes.txt', 'x\n')
    transcript('p16 big record', '/a.jsonl', now - day, tail=',"toolUseResult":"%s"' % ('x' * 70000))
    commit('p17 broken head', 'app.ts', now - day)
    write('p17 broken head/.git/HEAD', 'not a ref\n')
    commit('p19 dot claude', 'app.ts', now - day)
    write('p19 dot claude/.claude/CLAUDE.md', card)
    commit('p20 broken index', 'app.ts', now - day)
    write('p20 broken index/.git/index', 'not an index\n')
    git('p21 unborn', ['init', '-q'])   # no commit yet: no failure
    write('p21 unborn/CLAUDE.local.md', card)
    commit('p22 empty branch', 'app.ts', now - day)
    write('p22 empty branch/.git/refs/heads/main', '')
    commit('p23 lost object', 'README.md', now - 40 * day)
    commit('p23 lost object', 'app.ts', now - day)
    head = git('p23 lost object', ['rev-parse', 'HEAD']).strip()
    os.remove(os.path.join(root, 'p23 lost object', '.git', 'objects', head[:2], head[2:]))
    status, md = '  WARN: STATUS over 60 lines: %s: %d lines, archive: %s', '  WARN: md file over 200 KB: %s: %d KB'
    bare = '  WARN: no instruction file in an active project: %s (%d commits, %d sessions in 30 days)'
    behind = '  WARN: README behind the code: %s: last changed %d days and 10 commits before HEAD'
    want = [status % ('p01 status/STATUS.md', 61, 'none'), status % ('p01 status/.claude/state/STATUS.md', 61, 'none'),
            status % ('p02 archived/STATUS.md', 61, 'STATUS-archive.md'),
            status % ('p02 archived/docs/STATUS.md', 70, 'docs/_work/STATUS-2026-09-16-archive.md'),
            md % ('p03 journals/CHANGELOG.md', 250), md % ('p03 journals/docs/archiver-notes.md', 210),
            md % ('p03 journals/docs/decisions.md', 201), behind % ('p04 stale readme/README.md', lag),
            bare % ('p07 bare', 1, 0), bare % ('p08 sessions', 0, 2),
            '  WARN: no card («## Розмір») in an active project: p09 no card (1 commits, 0 sessions in 30 days)',
            bare % ('p16 big record', 0, 1), behind % ('p18 readme rst/README.rst', lag),
            '  WARN: old template («Project Agent Operating Standard») in 2 projects; of them active in 30 days: p12 old '
            'active', '  WARN: git cannot read the repo (README and commits not checked; git -C <folder> status says why): '
            'p17 broken head, p20 broken index, p22 empty branch, p23 lost object',
            '  WARN: transcripts of 30 days with no record time (a new Claude Code format?): 1, their sessions not counted']
    p = subprocess.run(['/bin/bash', DOCTOR, '--live', '--skip-tests'], env=env, capture_output=True, text=True, timeout=120)
    fails = check('docs', p, PASS, want, 1, claude)
    summary = ('  docs: 22 project folders, skipped 2 (link, worktree copy); STATUS over 60 lines 4, md over 200 KB 3, '
               'README behind 2, active without instructions 3, without a card 1, old template 2, git failed 4')
    return fails + ([] if summary in p.stdout.splitlines() else ['FAIL docs summary: want %r' % summary])


def docs_sync_fails(tmp, data):
    """The lines of the docs repo: docs-sync.sh report of the copies of hooks/ in the sandbox (the cases above have no
    docs_sync.py there and no such line). Not set up; a docs repo with no origin and an active folder not in its
    registry, then the summary line, and the error log of the hook with its classes and one legend; a report that fails
    (a registry of another header) is one WARN; docs-sync gone with the docs repo still there, and a log it cannot
    write, which doctor still shows. The exit code stays 0."""
    env = sandbox(os.path.join(tmp, 'docs-sync home'), CLEAN, {}, INSTALLED, data)
    env = {k: v for k, v in env.items() if not k.startswith('DOCS_SYNC_')}
    claude, shim = env['CLAUDE_HOME'], os.path.join(env['CLAUDE_HOME'], 'hooks', 'docs-sync.sh')
    os.makedirs(os.path.dirname(shim))
    for name in ('docs-sync.sh', 'docs_sync.py', 'docs_sync_lib.py', 'docs_sync_repo.py', 'docs_sync_report.py',
                 'commit-leaks.toml'):
        shutil.copy2(os.path.join(HOOKS, name), os.path.dirname(shim))
    run = lambda: subprocess.run(['/bin/bash', DOCTOR, '--live', '--skip-tests'], env=env, capture_output=True, text=True,
                                 timeout=120)
    fails = check('docs-sync-none', run(), PASS, [
        '  WARN: docs repo: not set up at ~/project-docs (docs-sync.sh init, then connect the projects)'], 0, claude)
    genv = dict({k: v for k, v in env.items() if k not in GIT_LOCAL and not k.startswith('GIT_CONFIG')},
                GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1', GIT_AUTHOR_NAME='Doctor',
                GIT_AUTHOR_EMAIL='doctor@example.com', GIT_COMMITTER_NAME='Doctor', GIT_COMMITTER_EMAIL='doctor@example.com')
    subprocess.run(['/bin/bash', shim, 'init'], env=genv, check=True, capture_output=True, timeout=60)
    with open(os.path.join(claude, 'logs', 'docs-sync.err'), 'w', encoding='utf-8') as fh:
        fh.write('%s SyncError p: the docs repo is busy over 10 s\n%s PushFailed git push rc=128\n' % (T, T))
    log = ('  WARN: docs-sync: 2 lines in CLAUDE_HOME/logs/docs-sync.err (PushFailed 1, SyncError 1), last: %s '
           'PushFailed git push rc=128' % T)
    p = run()
    fails += check('docs-sync-repo', p, PASS, [
        '  WARN: docs repo: active in 60 days, not in the registry: p (docs-sync.sh connect <folder> for docs outside '
        'git, else register)', '  WARN: docs repo: no remote origin: the docs are on this Mac only', log], 1, claude)
    summary = re.compile(r'  docs repo: ~/project-docs, no remote, mirror 0, in the registry 0, last commit [^,]+, not on '
                         r'origin -\Z')
    fails += [] if any(map(summary.match, p.stdout.splitlines())) else ['FAIL docs-sync-repo: no summary line']
    with open(os.path.join(env['HOME'], 'project-docs', 'registry.tsv'), 'w', encoding='utf-8') as fh:
        fh.write('bogus\n')
    fails += check('docs-sync-broken', run(), PASS, [
        '  WARN: docs repo: the report failed (exit 1): docs-sync: registry.tsv: an unknown header', log], 1, claude)
    os.remove(os.path.join(claude, 'hooks', 'docs_sync.py'))
    os.chmod(os.path.join(claude, 'logs', 'docs-sync.err'), 0o444)
    return fails + check('docs-sync-gone', run(), PASS, [
        '  WARN: docs repo: ~/project-docs is there, docs-sync is not installed: each commit of a connected project '
        'prints a line (install the base again, or git config --remove-section hook.docs-sync and hook.docs-sync-push '
        'in those projects)', '  WARN: CLAUDE_HOME/logs/docs-sync.err is not writable: docs-sync cannot log its errors',
        log], 1, claude)


def made_up(data):
    """More made-up transcripts on top of hint-delivered-test.py's."""
    hi = hdt.rec('user', 0, message={'role': 'user', 'content': 'hi'})
    push = hdt.rec('assistant', 40, message={'role': 'assistant', 'content': [
        {'type': 'tool_use', 'id': 'r1', 'name': 'Bash', 'input': {'command': 'git push'}}]})
    # no Bash call and no hint: a subagent transcript, and a main one of a session started before the window
    data['subagent-quiet'] = [hdt.rec('user', 70, True, message={'role': 'user', 'content': 'go'})]
    data['older-quiet'] = [hdt.rec('user', -120, message={'role': 'user', 'content': 'hi'})]
    # the time under another key and a line that is not JSON: no record the reader can use
    data['untimed'] = [{'type': 'user', 'ts': 1, 'uuid': 'u1', 'message': {'role': 'user', 'content': 'hi'}},
                       '{"type": "user", "cut\n']
    # the result of a push under another block type, a compaction with its boundary under another subtype
    data['renamed-result'] = [hi, push, hdt.rec('user', 41, message={'role': 'user', 'content': [
        {'type': 'tool_output', 'tool_use_id': 'r1', 'content': ''}]}), hdt.say(43)]
    data['parallel'] = [hi, hdt.rec('assistant', 50, message={'role': 'assistant', 'id': 'm1', 'content': [
        {'type': 'tool_use', 'id': 'p1', 'name': 'Bash', 'input': {'command': 'git push'}}]}),
        hdt.rec('assistant', 51, message={'role': 'assistant', 'id': 'm1', 'content': [
            {'type': 'tool_use', 'id': 'p2', 'name': 'Bash', 'input': {'command': 'git push'}}]}),
        hdt.rec('user', 52, message={'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'p2'}]},
                toolUseResult={'stdout': '', 'stderr': ''})]
    data['renamed-boundary'] = [hi, hdt.rec('system', 30, subtype='compact_boundary_v2'),
                                hdt.rec('user', 31, isCompactSummary=True, message={'role': 'user', 'content': 's'}),
                                hdt.say(33)]
    # 7 failures: one before the install, every kind, two with no usable uuid; not: 8 days old, a fork that went
    # through on a retry, a run with another stderr or none, a failed fork in another hook attachment, a hook's own
    # block, the words in a message and in an attachment of another type, an attachment on another record type, a line
    # cut off inside its failure; a resumed copy counts once
    data['hook-failed'] = [hi, hook_rec(-8 * DAY, 'hook_cancelled'),
                           hook_rec(-DAY, 'hook_non_blocking_error', exitCode=128),
                           hook_rec(100, 'hook_error_during_execution'), hook_rec(101, 'hook_cancelled'),
                           hook_rec(102, 'hook_non_blocking_error', exitCode=1),
                           hook_rec(103, 'hook_success', SECRET + '\n' + FORK, exitCode=0),
                           hook_rec(104, 'hook_success', FORK.replace('fork: ', 'fork: retry: '), exitCode=0),
                           hook_rec(105, 'hook_success', exitCode=0),
                           hdt.rec('user', 106, message={'role': 'user', 'content': '"hook_cancelled" ' + FORK}),
                           hdt.attach(107, type='note', content='"hook_cancelled" ' + FORK),
                           hdt.rec('user', 107, attachment={'type': 'hook_cancelled'}),
                           hook_rec(108, 'hook_additional_context', FORK), hook_rec(109, 'hook_success', None, exitCode=0),
                           hook_rec(113, 'hook_blocking_error', exitCode=2),
                           '{"type": "attachment", "attachment": {"type": "hook_cancelled", "cut\n',
                           dict(hook_rec(110, 'hook_cancelled'), uuid=None),
                           dict(hook_rec(111, 'hook_cancelled'), uuid=['x']),
                           hook_rec(102, 'hook_non_blocking_error', exitCode=1)]
    data['hook-failed-copy'] = [hi, hook_rec(100, 'hook_error_during_execution')]   # a forked session: the same uuid
    data['hook-failed-sub'] = [hook_rec(112, 'hook_non_blocking_error', sidechain=True)]
    data['hook-failed-tmp'] = [hi, hook_rec(120, 'hook_non_blocking_error')]
    data['hook-failed-old'] = [hook_rec(-3 * DAY, 'hook_non_blocking_error')]
    data['hook-unknown'] = [hi, hook_rec(130, 'hook_renamed_error'), hook_rec(131, 'hook_renamed_error'),
                            hook_rec(132, 'hook_success', ['x'], exitCode=0)]
    data['stale'] = [hook_rec(121, 'hook_non_blocking_error')]
    data.update({'many-%d' % i: [hook_rec(200 + i, 'hook_non_blocking_error')] for i in range(7)})
    return data


def main():
    data, fails, failed, ran = made_up(hdt.transcripts()), [], 0, 0
    with tempfile.TemporaryDirectory(prefix='doctor-test-') as tmp:
        for name, projects, logs, want_line, want_warns, legends, installed_at in CASES:
            if name in ('unreadable', 'unreadable-log', 'envelope-4') and os.geteuid() == 0:
                continue   # root reads a file with no permissions
            home = os.path.join(tmp, name + ' home')   # a space in every path doctor.sh passes on
            env = sandbox(home, projects, logs, installed_at, data)
            p = subprocess.run(['/bin/bash', DOCTOR, '--live', '--skip-tests'], env=env, capture_output=True,
                               text=True, timeout=120)
            case_fails = check(name, p, want_line, want_warns, legends, env['CLAUDE_HOME'])
            fails, failed, ran = fails + case_fails, failed + bool(case_fails), ran + 1
        codes = exit_code_fails(tmp, data)
        fails, failed, ran = fails + codes, failed + len(codes), ran + len(EXIT_CODES)
        for case_fails in fake_fails(tmp, data) + [state_file_fails(tmp, data), docs_fails(tmp, data), stack_fails(tmp, data),
                                                   window_fails(tmp, data),
                                                   commit_scan_fails(tmp, data), scan_probe_fails(tmp),
                                                   docs_sync_fails(tmp, data)]:
            fails, failed, ran = fails + case_fails, failed + bool(case_fails), ran + 1
    print('\n'.join(fails + ['doctor test: %d cases, %d failed' % (ran, failed)]))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
