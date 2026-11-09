#!/usr/bin/env python3
"""install-drift-test: the drift gate of scripts/install.sh, --record-only and rollback.sh in a sandbox: a made-up base
with three tags in a temp git repo that holds copies of the scripts under test, made-up live folders, snapshots on,
offline. settings.json that the app or CLI changed and that already equals the tag (normalized JSON and mode) is no
drift and is not rewritten; key order and spacing alone add no plan item; everything else still stops with exit 3 and
writes nothing: a key the tag does not have, another value, a key of the tag missing, another array order, another mode,
invalid JSON, a byte order mark or NUL bytes that jq would skip, a symlink, a removed file, a folder in its place, any
other file even when it equals the tag byte for byte (owner's decision 31.10: settings.json only). A write of
settings.json during the install stops it and restores the snapshot, in both plans (update: the guard, same: the check
after install); a write that only reformats does not. Also --force-drift, a first install with no manifest, a tag with
a byte order mark, rollback.sh <tag>, rollback.sh --to-snapshot, and plan.sh: a plan with no write, exit 3 on drift, no
option of install.sh through it. The hook tests after the hooks step get the tag's staged tree as SETUP_STAGE.

Not in verify.sh: it takes about a minute and verify runs several times per release (owner's decision 31.10 on the volume
of checks). Step 3 of the cycle in the root CLAUDE.md runs it when install.sh, plan.sh, lib.sh or rollback.sh change.

Run (from the repo root): python3 -I tests/install-drift-test.py -> the last line "install drift test: N cases, F
failed"; exit 0 when none failed.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts')
COPIED = ('install.sh', 'lib.sh', 'plan.sh', 'rollback.sh', 'snapshot-restore.sh')   # no verify.sh: install only warns about that
USER = ['-c', 'user.name=install-test', '-c', 'user.email=install-test@localhost.invalid']
GIT_ENV = {'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'}
RULES = 'global/CLAUDE.global.md'
APP_WRITE = 'app-write.json'
# Runs between the hooks step and settings.json (run_hook_tests), so it writes what the app would write at that moment
HOOK = ('#!/bin/bash\n# version %d\n'
        'if [ -f "$CLAUDE_HOME/' + APP_WRITE + '" ]; then cat "$CLAUDE_HOME/' + APP_WRITE + '" >"$CLAUDE_HOME/settings.json"; fi\n'
        "printf 'ALL OK\\nALL OK\\nEXTRA OK\\n'\n")
# The tag's staged tree reaches the hook tests as SETUP_STAGE: they run after the hooks step, before the skills of the
# tag are in place (v2026.11.19 stopped there, exit 5: node-std-tests.sh found no skill new-project)
STAGE_HOOK = ('#!/bin/bash\n# version 4\n'
              'if grep -qx "# version 4" "${SETUP_STAGE:-}/hooks/test-all.sh" 2>/dev/null; then '
              "printf 'ALL OK\\nALL OK\\nEXTRA OK\\n'; else echo 'FAIL no staged tree'; fi\n")

S1 = {'permissions': {'allow': ['Read', 'Edit']}, 'model': 'opus'}
S2 = dict(S1, tui='fullscreen')
BOM = '\ufeff'
BASE = {RULES: 'rules 1\n', 'global/home-agents.md': 'agents\n', 'global/git-excludes': '.DS_Store\n',
        'vendor/ecc/ECC-PIN.md': 'pin\n', 'scripts/legacy/ecc-drift.sh': '#!/bin/bash\n',
        'tools/time-register.py': 'print(1)\n', 'tools/claude-metrics.py': 'print(1)\n'}

NOT_DRIFT = 'not drift, not rewritten'
PLAN_SETTINGS = 'update  CLAUDE_HOME/settings.json'
cases = failed = 0


def row(reason, key='CLAUDE_HOME/settings.json'):
    return '%-24s %s' % (reason, key)


DRIFT_SETTINGS = row('changed')
DRIFT_RULES = row('changed', 'CLAUDE_HOME/CLAUDE.md')


def repo_form(obj):
    return json.dumps(obj, indent=2) + '\n'


def app_form(obj):
    """Other key order and spacing, no final newline: the same JSON in other bytes."""
    return json.dumps(obj, indent=4, sort_keys=True)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def read_or_none(path):
    try:
        return read(path)
    except (UnicodeDecodeError, OSError):
        return None


def git(repo, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    subprocess.run(['git', '-C', repo, *args], env=dict(env, **GIT_ENV), check=True, capture_output=True)


def build_repo(root):
    """Tags: v1 settings S1; v2 S2 (the key tui), nothing else; v3 S2 again and other rules; v4 adds a hook test; v5 only
    another hook; v6 another hook and S1; v7 S2 with a byte order mark; v8 S2 and a hook test that passes only
    with the staged tree of its tag."""
    repo = os.path.join(root, 'repo')
    for name in COPIED:
        os.makedirs(os.path.join(repo, 'scripts'), exist_ok=True)
        shutil.copy(os.path.join(SCRIPTS, name), os.path.join(repo, 'scripts', name))
    for rel, text in BASE.items():
        write(os.path.join(repo, rel), text)
    git(repo, 'init', '-q')
    for tag, settings, rules, hook in (('v1', repo_form(S1), 'rules 1\n', 0), ('v2', repo_form(S2), 'rules 1\n', 0),
                                       ('v3', repo_form(S2), 'rules 3\n', 0), ('v4', repo_form(S2), 'rules 3\n', 1),
                                       ('v5', repo_form(S2), 'rules 3\n', 2), ('v6', repo_form(S1), 'rules 3\n', 3),
                                       ('v7', BOM + repo_form(S2), 'rules 3\n', 3),
                                       ('v8', repo_form(S2), 'rules 3\n', 4)):
        write(os.path.join(repo, 'global/settings.json'), settings)
        write(os.path.join(repo, RULES), rules)
        if hook:
            write(os.path.join(repo, 'hooks/test-all.sh'), STAGE_HOOK if hook == 4 else HOOK % hook)
        git(repo, 'add', '-A')
        git(repo, *USER, 'commit', '-q', '-m', tag)
        git(repo, 'tag', tag)
    return repo


class Box:
    """Made-up live folders. An install takes about 2 s, so each list of tags is installed once, then copied."""
    count = 0
    ready = {}

    def __init__(self, root, repo, *installed):
        Box.count += 1
        self.repo = repo
        self.dir = os.path.join(root, 'box%d' % Box.count)
        os.mkdir(self.dir)
        self.home = os.path.join(self.dir, 'claude')
        self.snap_root = os.path.join(self.dir, 'snapshots')
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        self.env = dict(env, CLAUDE_HOME=self.home, HOME_AGENTS=os.path.join(self.dir, 'AGENTS.md'),
                        GIT_EXCLUDES=os.path.join(self.dir, 'ignore'), BIN_DIR=os.path.join(self.dir, 'bin'),
                        SNAPSHOT_ROOT=self.snap_root, **GIT_ENV)
        self.settings_path = os.path.join(self.home, 'settings.json')
        if installed:
            if installed not in Box.ready:
                Box.ready[installed] = Box(root, repo)
                for ref in installed:
                    rc, out, _ = Box.ready[installed].run('install.sh', ref)
                    assert rc == 0, out
            self.copy_live(Box.ready[installed])

    def copy_live(self, other):
        for name in ('claude', 'bin'):
            shutil.copytree(os.path.join(other.dir, name), os.path.join(self.dir, name), symlinks=True)
        for name in ('AGENTS.md', 'ignore'):
            shutil.copy2(os.path.join(other.dir, name), os.path.join(self.dir, name))

    def snapshots(self):
        return sorted(os.listdir(self.snap_root)) if os.path.isdir(self.snap_root) else []

    def run(self, script, *args):
        before = len(self.snapshots())
        p = subprocess.run(['bash', os.path.join(self.repo, 'scripts', script), *args], env=self.env, text=True,
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        return p.returncode, p.stdout, len(self.snapshots()) - before

    def set_settings(self, text):
        write(self.settings_path, text)

    def ref(self):
        path = os.path.join(self.home, '.setup-manifest.json')
        return json.loads(read(path))['ref'] if os.path.exists(path) else None

    def replaced(self):
        """Paths of settings.json kept by the snapshots under replaced/."""
        found = []
        for top, _, files in os.walk(self.snap_root):
            if os.sep + 'replaced' + os.sep in top + os.sep and 'settings.json' in files:
                found.append(os.path.join(top, 'settings.json'))
        return found

    def kept(self, text):
        """Files of this box outside live that hold these bytes: where a write during the install ended up."""
        found = []
        for top, _, files in os.walk(self.dir):
            for name in files:
                path = os.path.join(top, name)
                if path != self.settings_path and name != APP_WRITE and read_or_none(path) == text:
                    found.append(path)
        return found

    def app_writes(self, text):
        write(os.path.join(self.home, APP_WRITE), text)


def check(name, box, result, rc, ref, live=None, has=(), hasnt=(), wrote=None):
    """One case: exit code, output, the ref in the manifest, the bytes of live settings.json. Exit 3 writes nothing."""
    global cases, failed
    got, out, added = result
    errs = []
    if got != rc:
        errs.append('exit %s, want %s' % (got, rc))
    errs += ['the output has no %r' % s for s in has if s not in out]
    errs += ['the output has %r' % s for s in hasnt if s in out]
    if box.ref() != ref:
        errs.append('manifest ref %s, want %s' % (box.ref(), ref))
    if live is not None and not (os.path.isfile(box.settings_path) and read(box.settings_path) == live):
        errs.append('live settings.json is not the expected bytes')
    if (rc == 3 or wrote is False) and added:
        errs.append('wrote a snapshot')
    cases += 1
    if errs:
        failed += 1
        print('FAIL %s: %s' % (name, '; '.join(errs)))
        print('\n'.join('    ' + line for line in out.splitlines()[-14:]))


def same_content(root, repo):
    box = Box(root, repo, 'v1')
    live = app_form(S2)
    box.set_settings(live)
    check('app key the tag has too, dry run', box, box.run('install.sh', 'v2', '--dry-run'), 0, 'v1', live,
          has=(NOT_DRIFT, 'manifest'), hasnt=(PLAN_SETTINGS, 'drift: '), wrote=False)
    check('the same, install', box, box.run('install.sh', 'v2'), 0, 'v2', live,
          has=(NOT_DRIFT, 'live = v2, drift 0'), hasnt=(PLAN_SETTINGS,))
    check('nothing left to do after it', box, box.run('install.sh', 'v2'), 0, 'v2', live,
          has=('nothing to do', 'live = v2, drift 0'), hasnt=(NOT_DRIFT,), wrote=False)
    box.set_settings(app_form(dict(S2, extra=True)))
    check('rollback to a snapshot brings it back', box,
          box.run('rollback.sh', '--to-snapshot', os.path.join(box.snap_root, box.snapshots()[-1])), 0, 'v1', live,
          has=('live = v1, drift 1',))

    box = Box(root, repo, 'v1', 'v2')
    live = app_form(S2)
    box.set_settings(live)
    check('key order and spacing only, no plan item', box, box.run('install.sh', 'v3', '--dry-run'), 0, 'v2', live,
          has=('update  CLAUDE_HOME/CLAUDE.md',), hasnt=(PLAN_SETTINGS, NOT_DRIFT, 'drift: '), wrote=False)
    check('the same, install', box, box.run('install.sh', 'v3'), 0, 'v3', live, has=('live = v3, drift 0',))


def still_drift(root, repo):
    box = Box(root, repo, 'v1')   # exit 3 writes nothing, so one box takes all these contents
    for name, obj in (('a key the tag does not have', dict(S2, extra=True)), ('another value', dict(S2, tui='default')),
                      ('a key of the tag missing', {'model': 'opus', 'tui': 'fullscreen'}),
                      ('another array order', dict(S2, permissions={'allow': ['Edit', 'Read']}))):
        live = app_form(obj)
        box.set_settings(live)
        check(name, box, box.run('install.sh', 'v2'), 3, 'v1', live, has=(DRIFT_SETTINGS, '--force-drift'),
              hasnt=(NOT_DRIFT,))
    check('the last one, dry run', box, box.run('install.sh', 'v2', '--dry-run'), 3, 'v1', live, has=(DRIFT_SETTINGS,),
          hasnt=(NOT_DRIFT,))
    for name, live in (('a byte order mark before the same JSON', BOM + repo_form(S2)),
                       ('NUL bytes after the same JSON', repo_form(S2) + '\0\0')):
        box.set_settings(live)
        check(name, box, box.run('install.sh', 'v2'), 3, 'v1', live, has=(DRIFT_SETTINGS,), hasnt=(NOT_DRIFT,))
        check(name + ', --record-only', box, box.run('install.sh', 'v2', '--record-only'), 3, 'v1', live,
              has=('record-only: refused', DRIFT_SETTINGS))

    box = Box(root, repo, 'v1')
    box.set_settings(app_form(S2))
    os.chmod(box.settings_path, 0o644)
    check('the same JSON, another mode', box, box.run('install.sh', 'v2'), 3, 'v1', app_form(S2),
          has=(DRIFT_SETTINGS,), hasnt=(NOT_DRIFT,))

    box = Box(root, repo, 'v1')
    box.set_settings('{"tui": ')
    check('invalid JSON', box, box.run('install.sh', 'v2'), 3, 'v1', '{"tui": ', has=(DRIFT_SETTINGS,),
          hasnt=(NOT_DRIFT,))

    box = Box(root, repo, 'v1')
    target = os.path.join(box.dir, 'elsewhere.json')
    write(target, repo_form(S2))
    os.remove(box.settings_path)
    os.symlink(target, box.settings_path)
    check('a symlink to the same JSON', box, box.run('install.sh', 'v2'), 3, 'v1', has=(row('symlink'),),
          hasnt=(NOT_DRIFT,))

    box = Box(root, repo, 'v1')
    os.remove(box.settings_path)
    check('settings.json removed', box, box.run('install.sh', 'v2'), 3, 'v1', has=(row('missing'),), hasnt=(NOT_DRIFT,))
    os.mkdir(box.settings_path)
    check('a folder in its place', box, box.run('install.sh', 'v2'), 3, 'v1', has=(row('not-a-file'),),
          hasnt=(NOT_DRIFT,))

    box = Box(root, repo, 'v1', 'v2')
    write(os.path.join(box.home, 'CLAUDE.md'), 'rules 3\n')
    check('another file that equals the tag byte for byte', box, box.run('install.sh', 'v3'), 3, 'v2',
          has=(DRIFT_RULES,), hasnt=(NOT_DRIFT,))

    box = Box(root, repo, 'v1')
    live = app_form(S2)
    box.set_settings(live)
    write(os.path.join(box.home, 'CLAUDE.md'), 'edited live\n')
    check('settings.json clean, another file drifted', box, box.run('install.sh', 'v2'), 3, 'v1', live,
          has=(NOT_DRIFT, 'drift: 1 live path', DRIFT_RULES), hasnt=(DRIFT_SETTINGS,))


def force_and_record(root, repo):
    box = Box(root, repo, 'v1')
    drifted = app_form(dict(S2, extra=True))
    box.set_settings(drifted)
    check('--force-drift still replaces real drift', box, box.run('install.sh', 'v2', '--force-drift'), 0, 'v2',
          repo_form(S2), has=(DRIFT_SETTINGS, PLAN_SETTINGS, 'live = v2, drift 0'))
    kept = box.replaced()
    result = (0 if kept and read(kept[0]) == drifted else 1, 'kept: %s' % kept, 0)
    check('it keeps the drifted file', box, result, 0, 'v2')

    box = Box(root, repo, 'v1')
    live = app_form(S2)
    box.set_settings(live)
    check('--record-only takes the same JSON', box, box.run('install.sh', 'v2', '--record-only'), 0, 'v2', live,
          has=('live = v2, drift 0',))

    box = Box(root, repo, 'v1')
    live = app_form(dict(S2, extra=True))
    box.set_settings(live)
    check('--record-only refuses another JSON', box, box.run('install.sh', 'v2', '--record-only'), 3, 'v1', live,
          has=('record-only: refused', DRIFT_SETTINGS))

    box = Box(root, repo)
    live = app_form(dict(S2, extra=True))
    box.set_settings(live)
    os.chmod(box.settings_path, 0o600)
    check('first install, another JSON', box, box.run('install.sh', 'v2'), 3, None, live, has=(DRIFT_SETTINGS,))
    live = app_form(S2)
    box.set_settings(live)
    os.chmod(box.settings_path, 0o644)
    check('first install, the same JSON, another mode', box, box.run('install.sh', 'v2'), 3, None, live,
          has=('mode 644 (want 600)',))
    os.chmod(box.settings_path, 0o600)
    box.set_settings(BOM + live)
    check('first install, a byte order mark', box, box.run('install.sh', 'v2'), 3, None, BOM + live,
          has=(DRIFT_SETTINGS,))
    box.set_settings(live)
    check('first install, the same JSON', box, box.run('install.sh', 'v2'), 0, 'v2', live, hasnt=(PLAN_SETTINGS,))

    box = Box(root, repo, 'v1')
    live = read(box.settings_path)
    check('a tag with a byte order mark never installs', box, box.run('install.sh', 'v7'), 1, 'v1', live,
          has=('not a JSON object',), wrote=False)


def rollback(root, repo):
    box = Box(root, repo, 'v1')
    box.set_settings(app_form(S2))
    check('before the rollback: the same JSON installs', box, box.run('install.sh', 'v2'), 0, 'v2', app_form(S2))
    check('rollback.sh <tag> replaces another JSON', box, box.run('rollback.sh', 'v1'), 0, 'v1', repo_form(S1),
          has=(PLAN_SETTINGS, 'live = v1, drift 0'))

    box = Box(root, repo, 'v1', 'v2')
    box.set_settings(app_form(dict(S2, extra=True)))
    check('rollback.sh <tag> over real drift', box, box.run('rollback.sh', 'v1'), 0, 'v1', repo_form(S1),
          has=(DRIFT_SETTINGS, 'live = v1, drift 0'))

    box = Box(root, repo, 'v1', 'v2')
    live = app_form(S1)
    box.set_settings(live)
    check('rollback.sh <tag> when live is that tag already', box, box.run('rollback.sh', 'v1'), 0, 'v1', live,
          has=(NOT_DRIFT, 'live = v1, drift 0'), hasnt=(PLAN_SETTINGS,))

    box = Box(root, repo, 'v1', 'v2')
    box.set_settings(BOM + repo_form(S1))
    check('rollback.sh <tag> rewrites a byte order mark', box, box.run('rollback.sh', 'v1'), 0, 'v1', repo_form(S1),
          has=(DRIFT_SETTINGS, PLAN_SETTINGS, 'live = v1, drift 0'), hasnt=(NOT_DRIFT,))


def during_install(root, repo):
    written = app_form(dict(S2, extra=True))

    box = Box(root, repo, 'v4')
    before = read(box.settings_path)
    box.app_writes(written)
    check('settings.json in the plan, the app writes it: the guard stops', box, box.run('install.sh', 'v6'), 1, 'v4',
          before, has=('settings.json changed while installing', 'restoring the snapshot'))
    result = (0 if box.kept(written) else 1, 'kept: %s' % box.kept(written), 0)
    check('that write is kept', box, result, 0, 'v4')

    box = Box(root, repo, 'v4')
    box.app_writes(written)
    check('settings.json same, the app writes it: the check after install stops', box, box.run('install.sh', 'v5'), 1,
          'v4', before, has=(DRIFT_SETTINGS, 'live does not match v5', 'restoring the snapshot'))
    result = (0 if box.kept(written) else 1, 'kept: %s' % box.kept(written), 0)
    check('that write is kept', box, result, 0, 'v4')

    box = Box(root, repo, 'v4')
    box.app_writes(app_form(S2))
    check('settings.json same, the app only reformats it: no stop', box, box.run('install.sh', 'v5'), 0, 'v5',
          app_form(S2), has=('live = v5, drift 0',))


def staged_tree(root, repo):
    """The hook tests after the hooks step get the tag's staged tree: a hook may need a skill the install puts later."""
    box = Box(root, repo, 'v6')
    check('hook tests see the staged tree of the tag', box, box.run('install.sh', 'v8'), 0, 'v8',
          has=('hook tests:   ALL OK ALL OK EXTRA OK',), hasnt=('FAIL no staged tree',))


def plan_script(root, repo):
    """plan.sh runs outside the ask rule of install.sh, so it must stay a dry run whatever it is given."""
    box = Box(root, repo, 'v1')
    check('plan: a tag', box, box.run('plan.sh', 'v2'), 0, 'v1', live=repo_form(S1), has=('nothing written', PLAN_SETTINGS),
          wrote=False)
    for args in ((), ('',), ('-x',), ('--help',), ('--ref=v2',), ('--force-drift',), ('--record-only',), ('--ref', 'v2'),
                 ('v2', '--force-drift'), ('v2', '--record-only'), ('v2', '--sandbox')):
        check('plan: no %r' % (args,), box, box.run('plan.sh', *args), 2, 'v1', live=repo_form(S1), wrote=False)
    box.set_settings(app_form(dict(S1, extra=1)))
    check('plan: drift', box, box.run('plan.sh', 'v2'), 3, 'v1', live=app_form(dict(S1, extra=1)), has=(DRIFT_SETTINGS,))


def main():
    root = tempfile.mkdtemp(prefix='install-drift-test.')
    try:
        repo = build_repo(root)
        same_content(root, repo)
        still_drift(root, repo)
        force_and_record(root, repo)
        rollback(root, repo)
        during_install(root, repo)
        staged_tree(root, repo)
        plan_script(root, repo)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print('install drift test: %d cases, %d failed' % (cases, failed))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
