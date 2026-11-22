"""Checks of the line `sources` of scripts/doctor.sh for tests/doctor-test.py (split off for size): when the sources of
the vendored files were last checked, by the state file of scripts/sources-check.py (ADR-007, L4). The sandbox of
doctor-test.py holds a check of today of the real base (checked_today), so every other case of that test proves the
line costs no WARN; a case that runs doctor.sh of a copy of scripts/ names that copy with it. Here: the line itself; no
state file, an old check, a check of another tree and a file that does not read, each a WARN; a helper that fails,
prints another line or is not there, one WARN and no line. No case asks the network: the helper reads one file. The rules of the line
are checked on the helper itself in tests/sources_check_cases.py."""
import datetime
import json
import os
import shutil
import subprocess

NAME = '~/sandbox/.claude/state/sources-check.json'   # HOME of the sandbox is one folder above its CLAUDE_HOME
HINT = 'python3 -I -B scripts/sources-check.py in the base repo (the network and gh with a sign-in)'
LINE = '  sources: checked %s (%d day(s) ago): 3 source(s), 1 moved from the pin, the original of 2 of our file(s) changed, 0 gone'
NEVER = '  WARN: sources: never checked against their sources (no %s): %s' % (NAME, HINT)
OLD = '  WARN: sources: checked %s, over 35 days ago: ' + HINT + '; an update of a source is a release of its own'
OTHER = '  WARN: sources: the last full check (%s) was of another tree (' + NAME + ' names it), not of this base: ' + HINT
UNREAD = '  WARN: sources: %s does not read: when the sources were last checked is not known (%s writes it anew)' % (NAME, HINT)
HELPER = '  WARN: sources: sources-check.py --doctor failed (exit %s): when they were last checked is not known'
NO_HELPER = '  WARN: sources: when they were last checked is not known: no python3, or no scripts/sources-check.py in the base'


def checked_today(claude, repo):
    """Writes the state file of scripts/sources-check.py into the sandbox: the sources of the base at `repo` checked today
    (the tree as the tool writes it, with every link of the path resolved)."""
    os.makedirs(os.path.join(claude, 'state'), exist_ok=True)
    with open(os.path.join(claude, 'state', 'sources-check.json'), 'w', encoding='utf-8') as fh:
        json.dump({'schema': 1, 'checked_at': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                   'tree': os.path.realpath(repo), 'sources': 3, 'moved': 1, 'files_changed': 2, 'files_gone': 0}, fh)


def doctor(script, env):
    return subprocess.run(['/bin/bash', script, '--live', '--skip-tests'], env=env, capture_output=True, text=True, timeout=120)


def line_fails(name, p, want):
    got = [ln for ln in p.stdout.splitlines() if ln.startswith('  sources: ')]
    return [] if got == want else ['FAIL sources-%s line:\n  got  %r\n  want %r' % (name, got, want)]


def state_fails(tmp, data, t, name, state, warn, days):
    """doctor.sh on a sandbox whose state file is the sandbox's with these keys (a dict), this text, or gone (None).
    warn: the one WARN it must give, with %s for the day of the check, or None; days: the age the line must name, or
    None for no line."""
    env = t.sandbox(os.path.join(tmp, 'sources %s home' % name), t.CLEAN, {}, t.INSTALLED, data)
    path = os.path.join(env['CLAUDE_HOME'], 'state', 'sources-check.json')
    with open(path, encoding='utf-8') as fh:
        doc = json.load(fh)
    if state is None:
        os.unlink(path)
    else:
        doc.update(state if isinstance(state, dict) else {})
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(json.dumps(doc) if isinstance(state, dict) else state)
    day = doc['checked_at'][:10]
    p = doctor(t.DOCTOR, env)
    warns = [] if warn is None else [warn % day if '%s' in warn else warn]
    return t.check('sources-' + name, p, t.PASS, warns, 0, env['CLAUDE_HOME']) + line_fails(
        name, p, [] if days is None else [LINE % (day, days)])


def helper_fails(tmp, data, t, name, text, warn):
    """doctor.sh of a copy of scripts/ with this text as scripts/sources-check.py (None: no such file): one WARN, no line."""
    repo = os.path.join(tmp, 'sources fake ' + name)
    shutil.copytree(os.path.dirname(t.DOCTOR), os.path.join(repo, 'scripts'), ignore=shutil.ignore_patterns('__pycache__'))
    os.makedirs(os.path.join(repo, 'tests'))
    for f in t.REAL:
        shutil.copy2(os.path.join(t.TESTS, f), os.path.join(repo, 'tests', f))
    helper = os.path.join(repo, 'scripts', 'sources-check.py')
    os.unlink(helper)
    if text is not None:
        with open(helper, 'w', encoding='utf-8') as fh:
            fh.write(text + '\n')
    env = t.sandbox(os.path.join(tmp, 'sources fake-home ' + name), t.CLEAN, {}, t.INSTALLED, data)
    p = doctor(os.path.join(repo, 'scripts', 'doctor.sh'), env)
    return t.check('sources-' + name, p, t.PASS, [warn], 0, env['CLAUDE_HOME']) + line_fails(name, p, [])


def sources_fails(tmp, data, t):
    old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=40, hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
    fails = state_fails(tmp, data, t, 'today', {}, None, 0)
    fails += state_fails(tmp, data, t, 'never', None, NEVER, None)
    fails += state_fails(tmp, data, t, 'old', {'checked_at': old}, OLD, 40)
    fails += state_fails(tmp, data, t, 'other-tree', {'tree': '/another/base'}, OTHER, None)
    fails += state_fails(tmp, data, t, 'unread', '{"schema": 1,', UNREAD, None)
    fails += helper_fails(tmp, data, t, 'helper-exit-1', "import sys\nsys.stderr.write('boom\\n')\nraise SystemExit(1)", HELPER % '1: boom')
    fails += helper_fails(tmp, data, t, 'helper-other-line', "print('hello')", HELPER % '0')
    fails += helper_fails(tmp, data, t, 'helper-missing', None, NO_HELPER)
    return fails
