"""Checks of the packs library in scripts/install.sh, plan.sh and rollback.sh for tests/install-drift-test.py (split off
for size). Tags after v8 of its made-up base: p1 brings the library (the pack alpha, the three catalog files,
claude-pack), p2 changes alpha and adds beta, p3 drops alpha; three more tags must not install (a link inside a pack, a
pack without plugin.json, packs/ without its catalog). The plan of a tag with packs has only the new items; a pack
comes, changes and goes as a plan item of its own; a file added to a live pack is drift; a rollback to a tag without
the library takes all of it away and says what Claude Code still records. The tags v1-v8 have no packs/: every other
case of install-drift-test.py proves that such a tag still installs."""
import os

CATALOG = ('.claude-plugin/marketplace.json', 'catalog.json', 'CATALOG.md')
NOTE = 'library:      the packs catalog left CLAUDE_HOME/packs'


def new(key):
    return 'new     ' + key


def update(key):
    return 'update  ' + key


def retire(key):
    return 'retire  ' + key


def changes(count):
    return 'plan:         %d item(s) to change' % count


def pack_tags(t, repo):
    def tag(name):
        t.git(repo, 'add', '-A')
        t.git(repo, *t.USER, 'commit', '-q', '-m', name)
        t.git(repo, 'tag', name)

    def pack(name, text):
        t.write(os.path.join(repo, 'packs', name, '.claude-plugin', 'plugin.json'), '{"name": "%s"}\n' % name)
        t.write(os.path.join(repo, 'packs', name, 'skills', name + '-lint', 'SKILL.md'), text)

    def catalog(text):
        for rel in CATALOG:
            t.write(os.path.join(repo, 'packs', rel), text)

    pack('alpha', 'lint 1\n')
    catalog('catalog 1\n')
    t.write(os.path.join(repo, 'tools', 'claude-pack.py'), 'print(1)\n')
    tag('p1')
    pack('alpha', 'lint 2\n')
    pack('beta', 'lint 1\n')
    catalog('catalog 2\n')
    tag('p2')
    t.git(repo, 'rm', '-r', '-q', 'packs/alpha')
    catalog('catalog 3\n')
    tag('p3')
    link = os.path.join(repo, 'packs', 'beta', 'skills', 'beta-lint', 'link.md')
    os.symlink('SKILL.md', link)
    tag('p4')
    os.remove(link)
    t.write(os.path.join(repo, 'packs', 'gamma', 'skills', 'gamma-lint', 'SKILL.md'), 'lint 1\n')
    tag('p5')
    t.git(repo, 'rm', '-r', '-q', 'packs/gamma')
    t.git(repo, 'rm', '-q', 'packs/CATALOG.md')
    tag('p6')


def fact(t, name, ok, detail=''):
    """A case about the live files, counted with the cases of install-drift-test.py."""
    t.cases += 1
    if not ok:
        t.failed += 1
        print('FAIL %s%s' % (name, ': ' + detail if detail else ''))


def kept(box, rel):
    """Whether a snapshot keeps the replaced live file rel (a key path)."""
    return any(os.path.isfile(os.path.join(top, rel)) for top, _, _ in os.walk(box.snap_root) if top.endswith(os.sep + 'replaced'))


def comes_and_goes(t, root, repo):
    box = t.Box(root, repo, 'v8')
    lint = 'claude/packs/alpha/skills/alpha-lint/SKILL.md'

    def live(rel):
        return t.read_or_none(os.path.join(box.dir, rel))
    library = [new('CLAUDE_HOME/packs/alpha')] + [new('CLAUDE_HOME/packs/' + rel) for rel in CATALOG] + [new('BIN_DIR/claude-pack')]
    t.check('packs: the plan of the first tag with the library has only its items', box, box.run('plan.sh', 'p1'), 0, 'v8',
            has=library + [changes(5)], wrote=False)
    t.check('packs: the library installs', box, box.run('install.sh', 'p1'), 0, 'p1', has=('live = p1, drift 0',), hasnt=(NOTE,))
    fact(t, 'packs: the pack, the catalog and claude-pack are live', live(lint) == 'lint 1\n'
         and all(live('claude/packs/' + rel) == 'catalog 1\n' for rel in CATALOG) and live('bin/claude-pack') == 'print(1)\n')
    t.check('packs: nothing to do after it', box, box.run('install.sh', 'p1'), 0, 'p1', has=('nothing to do',), wrote=False)
    t.check('packs: a pack changes and another comes, each its own item', box, box.run('plan.sh', 'p2'), 0, 'p1',
            has=[update('CLAUDE_HOME/packs/alpha'), new('CLAUDE_HOME/packs/beta'), changes(5)]
            + [update('CLAUDE_HOME/packs/' + rel) for rel in CATALOG], hasnt=('BIN_DIR/claude-pack',), wrote=False)
    t.check('packs: the same, install', box, box.run('install.sh', 'p2'), 0, 'p2', has=('live = p2, drift 0',))
    fact(t, 'packs: both packs are live', live(lint) == 'lint 2\n' and live('claude/packs/beta/skills/beta-lint/SKILL.md') == 'lint 1\n')
    t.check('packs: a pack goes as its own item', box, box.run('plan.sh', 'p3'), 0, 'p2',
            has=(retire('CLAUDE_HOME/packs/alpha'), changes(4)), hasnt=('CLAUDE_HOME/packs/beta',), wrote=False)
    t.check('packs: the same, install', box, box.run('install.sh', 'p3'), 0, 'p3', has=('live = p3, drift 0',), hasnt=(NOTE,))
    fact(t, 'packs: the pack is gone from live and kept in the snapshot', not os.path.exists(os.path.join(box.dir, 'claude/packs/alpha'))
         and kept(box, 'CLAUDE_HOME/packs/alpha/skills/alpha-lint/SKILL.md')
         and live('claude/packs/beta/skills/beta-lint/SKILL.md') == 'lint 1\n' and live('claude/packs/catalog.json') == 'catalog 3\n')
    for ref, text in (('p4', 'packs/beta contains a symlink'), ('p5', 'packs/gamma/.claude-plugin/plugin.json'),
                      ('p6', 'packs/CATALOG.md')):
        t.check('packs: the tag %s does not install' % ref, box, box.run('install.sh', ref), 1, 'p3', has=(text,), wrote=False)


def drift_and_rollback(t, root, repo):
    box = t.Box(root, repo, 'v8', 'p2')
    extra = os.path.join(box.dir, 'claude/packs/alpha/skills/alpha-lint/notes.md')
    t.write(extra, 'added by hand\n')
    t.check('packs: a file added to a live pack is drift', box, box.run('install.sh', 'p3'), 3, 'p2',
            has=(t.row('extra', 'CLAUDE_HOME/packs/alpha/skills/alpha-lint/notes.md'),))
    os.remove(extra)
    t.write(os.path.join(box.dir, 'claude/packs/catalog.json'), 'edited by hand\n')
    t.check('packs: an edited catalog is drift', box, box.run('plan.sh', 'p3'), 3, 'p2',
            has=(t.row('changed', 'CLAUDE_HOME/packs/catalog.json'),))
    gone = [retire('CLAUDE_HOME/packs/alpha'), retire('CLAUDE_HOME/packs/beta'), retire('BIN_DIR/claude-pack')] + [
        retire('CLAUDE_HOME/packs/' + rel) for rel in CATALOG]
    t.check('packs: a rollback to a tag without the library takes it away, over the drift', box, box.run('rollback.sh', 'v8'), 0, 'v8',
            has=gone + [NOTE, 'live = v8, drift 0'])
    left = [name for name in ('claude/packs/alpha', 'claude/packs/beta', 'claude/packs/catalog.json', 'claude/packs/CATALOG.md',
                              'claude/packs/.claude-plugin/marketplace.json', 'bin/claude-pack')
            if os.path.lexists(os.path.join(box.dir, name))]
    fact(t, 'packs: nothing of the library is live after the rollback', not left and kept(box, 'CLAUDE_HOME/packs/catalog.json'), str(left))
    t.check('packs: and the library installs again after it', box, box.run('install.sh', 'p2'), 0, 'p2', has=('live = p2, drift 0',))


def pack_cases(t, root, repo):
    pack_tags(t, repo)
    comes_and_goes(t, root, repo)
    drift_and_rollback(t, root, repo)
