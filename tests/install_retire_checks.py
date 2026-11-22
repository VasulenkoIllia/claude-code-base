"""Checks of a tool that left the base, for tests/install-drift-test.py (split off for size): scripts/legacy/ecc-drift.sh.
Every tag up to v2026.11.46 installs it as BIN_DIR/ecc-drift.sh; the tags after it do not have it (the check of the
sources, scripts/sources-check.py, replaced it and runs from the repo; ADR-007, L4). The tag d1 of the made-up base is
v8 without that file: its plan is the one item, the install moves the live file into the snapshot, a rollback to v8
brings it back, and a first install of d1 on an empty home goes through. Every other tag of the test has the file:
those cases prove that such a tag still installs."""
import os

from install_pack_checks import changes, fact, kept, retire

LEGACY, LIVE = 'scripts/legacy/ecc-drift.sh', 'bin/ecc-drift.sh'


def retire_tag(t, repo):
    """The tag d1: v8 without the legacy tool. The file comes back in the next commit, so the tags after it have it."""
    t.git(repo, 'rm', '-q', LEGACY)
    t.git(repo, *t.USER, 'commit', '-q', '-m', 'd1')
    t.git(repo, 'tag', 'd1')
    t.write(os.path.join(repo, LEGACY), t.BASE[LEGACY])
    t.git(repo, 'add', '-A')
    t.git(repo, *t.USER, 'commit', '-q', '-m', 'the legacy tool again')


def retire_cases(t, root, repo):
    retire_tag(t, repo)
    box = t.Box(root, repo, 'v8')
    live = os.path.join(box.dir, LIVE)
    fact(t, 'retire: a tag with the legacy tool has it live', t.read_or_none(live) == t.BASE[LEGACY])
    t.check('retire: the plan of a tag without the legacy tool is the one item', box, box.run('plan.sh', 'd1'), 0, 'v8',
            has=(retire('BIN_DIR/ecc-drift.sh'), changes(1)), wrote=False)
    t.check('retire: the same, install', box, box.run('install.sh', 'd1'), 0, 'd1', has=('live = d1, drift 0',))
    fact(t, 'retire: the live file is gone and kept in the snapshot', not os.path.lexists(live) and kept(box, 'BIN_DIR/ecc-drift.sh'))
    t.check('retire: nothing to do after it', box, box.run('install.sh', 'd1'), 0, 'd1', has=('nothing to do',), wrote=False)
    t.check('retire: a rollback to a tag that has the tool brings it back', box, box.run('rollback.sh', 'v8'), 0, 'v8',
            has=('live = v8, drift 0',))
    fact(t, 'retire: the live file is back', t.read_or_none(live) == t.BASE[LEGACY])
    empty = t.Box(root, repo)
    t.check('retire: a first install of a tag without the tool', empty, empty.run('install.sh', 'd1'), 0, 'd1',
            has=('live = d1, drift 0',), hasnt=('ecc-drift',))
    fact(t, 'retire: and no such file is live', not os.path.lexists(os.path.join(empty.dir, LIVE)))
