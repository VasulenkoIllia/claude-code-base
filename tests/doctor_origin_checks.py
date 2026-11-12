"""Checks of the line "docs repo origin" of scripts/doctor.sh for tests/doctor-test.py (split off for size): the
privacy of the GitHub repo that docs-sync pushes to, asked through a stand-in gh."""
import os
import shlex
import subprocess


def docs_origin_fails(tmp, data, t):
    """The line of the origin of the docs repo: gh (a stand-in first on PATH, which keeps its arguments) says PRIVATE,
    PUBLIC, nothing (it fails) or hangs past DOCS_GH_SECS; an origin that is no GitHub repo is not asked about, and
    its URL with a token is not printed. docs-sync is not in the sandbox, so its WARN comes in every case."""
    env = t.sandbox(os.path.join(tmp, 'docs-origin home'), t.CLEAN, {}, t.INSTALLED, data)
    env = {k: v for k, v in env.items() if not k.startswith('DOCS_SYNC_')}
    claude, repo, stub = env['CLAUDE_HOME'], os.path.join(env['HOME'], 'project-docs'), os.path.join(tmp, 'gh bin')
    os.makedirs(stub)
    env.update(PATH=stub + os.pathsep + env['PATH'], DOCS_GH_SECS='2')
    genv = {k: v for k, v in env.items() if k not in t.GIT_LOCAL}
    subprocess.run(['git', 'init', '-q', repo], env=genv, check=True, capture_output=True, timeout=60)
    gone = ('  WARN: docs repo: ~/project-docs is there, docs-sync is not installed: each commit of a connected project '
            'prints a line (install the base again, or git config --remove-section hook.docs-sync and hook.docs-sync-push '
            'in those projects)')
    line = '  docs repo origin: PRIVATE on GitHub'
    unknown = ('  WARN: docs repo origin: privacy not checked (no answer of gh in 2 s: gh, the network or the sign-in)')
    public = ('  WARN: docs repo origin: GitHub says PUBLIC, not PRIVATE: docs-sync pushes the docs of client projects '
              'there in the background with no ask (make the repo private, or stop the push: git -C <docs repo> remote '
              'remove origin)')
    other = ('  WARN: docs repo origin: not a GitHub repo, its privacy is not checked: docs-sync pushes the docs of '
             'client projects there with no ask')
    cases = (('private', 'git@github.com:o/docs.git', 'echo PRIVATE', [gone], True),
             ('https', 'https://github.com/o/docs', 'echo PRIVATE', [gone], True),
             ('public', 'ssh://git@github.com/o/docs.git/', 'echo PUBLIC', [gone, public], False),
             ('odd-answer', 'git@github.com:o/docs.git', 'echo "PRIVATE; rm x"', [gone, unknown], False),
             ('no-answer', 'git@github.com:o/docs.git', 'exit 1', [gone, unknown], False),
             ('hangs', 'git@github.com:o/docs.git', 'sleep 30; echo PRIVATE', [gone, unknown], False),
             ('token', 'https://bot:%s@github.com/o/docs.git' % t.SECRET, 'echo PRIVATE', [gone, other], False),
             ('other-host', 'git@example.com:o/docs.git', 'echo PRIVATE', [gone, other], False))
    fails = []
    for name, url, body, warns, private in cases:
        subprocess.run(['git', '-C', repo, 'remote', 'remove', 'origin'], env=genv, capture_output=True, timeout=60)
        subprocess.run(['git', '-C', repo, 'remote', 'add', 'origin', url], env=genv, check=True, capture_output=True,
                       timeout=60)
        args = os.path.join(stub, 'args')
        with open(os.path.join(stub, 'gh'), 'w', encoding='utf-8') as fh:
            fh.write('#!/bin/bash\nprintf "%%s\\n" "$*" >%s\n%s\n' % (shlex.quote(args), body))
        os.chmod(fh.name, 0o755)
        if os.path.exists(args):
            os.remove(args)
        p = subprocess.run(['/bin/bash', t.DOCTOR, '--live', '--skip-tests'], env=env, capture_output=True, text=True,
                           timeout=120)
        fails += t.check('docs-origin-' + name, p, t.PASS, warns, 0, claude)
        fails += [] if (line in p.stdout.splitlines()) == private else ['FAIL docs-origin-%s: the line of PRIVATE' % name]
        asked = open(args, encoding='utf-8').read().strip() if os.path.exists(args) else None
        want = None if 'not a GitHub repo' in warns[-1] else 'repo view github.com/o/docs --json visibility -q .visibility'
        fails += [] if asked == want else ['FAIL docs-origin-%s: gh was asked %r' % (name, asked)]
    # a push goes to the pushurl, not to the url: every repo it names is asked about, and one that is not private is a WARN
    with open(os.path.join(stub, 'gh'), 'w', encoding='utf-8') as fh:
        fh.write('#!/bin/bash\ncase "$*" in *o/open*) echo PUBLIC ;; *) echo PRIVATE ;; esac\n')
    for name, urls, warns in (('pushurl-public', ('git@github.com:o/docs.git', 'git@github.com:o/open.git'), [gone, public]),
                              ('pushurl-other-host', ('git@example.com:o/docs.git',), [gone, other]),
                              ('pushurl-private', ('git@github.com:o/docs.git', 'https://github.com/o/more'), [gone])):
        subprocess.run(['git', '-C', repo, 'config', '--unset-all', 'remote.origin.pushurl'], env=genv, capture_output=True,
                       timeout=60)
        for url in urls:
            subprocess.run(['git', '-C', repo, 'config', '--add', 'remote.origin.pushurl', url], env=genv, check=True,
                           capture_output=True, timeout=60)
        p = subprocess.run(['/bin/bash', t.DOCTOR, '--live', '--skip-tests'], env=env, capture_output=True, text=True,
                           timeout=120)
        fails += t.check('docs-origin-' + name, p, t.PASS, warns, 0, claude)
        fails += [] if (line in p.stdout.splitlines()) == (len(warns) == 1) else ['FAIL docs-origin-%s: the line of PRIVATE' % name]
    subprocess.run(['git', '-C', repo, 'remote', 'remove', 'origin'], env=genv, check=True, capture_output=True, timeout=60)
    p = subprocess.run(['/bin/bash', t.DOCTOR, '--live', '--skip-tests'], env=env, capture_output=True, text=True, timeout=120)
    fails += t.check('docs-origin-none', p, t.PASS, [gone], 0, claude)
    return fails + (['FAIL docs-origin-none: a line with no origin'] if 'docs repo origin' in p.stdout else [])
