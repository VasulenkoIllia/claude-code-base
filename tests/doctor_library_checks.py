"""Checks of the packs library section of scripts/doctor.sh for tests/doctor-test.py (split off for size): silent
with no catalog and no record of one; the line `library` with a catalog; the WARNs about a pack that a project enables
and the catalog lacks, a settings.local.json or a catalog.json that does not read, the records Claude Code keeps
of a catalog that is gone, a project (also a worktree of it) that declares a catalog named library of its own under
either key of Claude Code, and a record of Claude Code that is not the folder of the base. Every other case of
doctor-test.py runs with no catalog and proves the silence."""
import json
import os
import shutil
import subprocess

LINE = '  library: '
LOST = ('  WARN: library: pack %s is enabled in %d project(s) (%s), the catalog has no such pack: their sessions start '
        'without it and say nothing (~/bin/claude-pack disable %s there, or install a tag that has the pack)')
# after a rollback there is no claude-pack either: the advice names the key
LOST_GONE = LOST.replace('~/bin/claude-pack disable %s there',
                         'set enabledPlugins["%s@library"] to false in their .claude/settings.local.json')
UNREAD = '  WARN: library: .claude/settings.local.json does not read as JSON, its packs are not known: %s'
BROKEN = ('  WARN: library: CLAUDE_HOME/packs/catalog.json does not read as the catalog library: claude-pack cannot '
          'list or enable packs (install the base again)')
RECORDS = '  WARN: library: %s in CLAUDE_HOME/plugins does not read: what Claude Code records of the catalog is not known'
OWN = ('  WARN: library: %d project(s) declare a catalog named library of their own (%s): once such a project is trusted, '
       'Claude Code loads packs from the folder it names and not from the base, also in the next session of another project '
       '(remove the key library of extraKnownMarketplaces or additionalMarketplaces there; claude-pack enable refuses in '
       'such a project)')
OWN_UNREAD = ('  WARN: library: settings that do not read as JSON or hold a catalog key that is no object, whether they '
              'declare a catalog of their own is not known: %s')
ELSEWHERE = ('  WARN: library: Claude Code has the catalog library registered at %s, not at CLAUDE_HOME/packs: a project '
             'declared a catalog of that name and sessions load packs from there, or Claude Code keeps its records in a new '
             'form (remove the key library of extraKnownMarketplaces or additionalMarketplaces in that project; a session '
             'of a project without the key registers the catalog of the base again)')
GONE = ('  WARN: library: no catalog in CLAUDE_HOME/packs, but CLAUDE_HOME/plugins still names it (known_marketplaces.json:'
        ' the catalog library %s; installed_plugins.json: %d record(s) of its packs): left by a rollback to a tag without'
        ' the library, harmless; no install touches these files, remove the records by hand if they are in the way')


def put(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(data if isinstance(data, str) else json.dumps(data))


def catalog(*names):
    return {'schema': 1, 'catalog': 'library', 'packs': [{'name': n} for n in names]}


def library_fails(tmp, data, t):
    """One sandbox, changed step by step; every step: the exact WARN list of doctor and its line `library` (or none)."""
    env = t.sandbox(os.path.join(tmp, 'library home'), t.CLEAN, {}, t.INSTALLED, data)
    claude, projects = env['CLAUDE_HOME'], env['PROJECTS_DIR']
    cat, plug = os.path.join(claude, 'packs', 'catalog.json'), os.path.join(claude, 'plugins')
    packs = os.path.join(claude, 'packs')
    record = {'library': {'source': {'source': 'directory', 'path': packs}, 'installLocation': packs}, 'elsewhere': {}}
    fails = []

    def enabled(project, plugins):
        put(os.path.join(projects, project, '.claude', 'settings.local.json'), {'enabledPlugins': plugins})

    def step(name, warns, line):
        p = subprocess.run(['/bin/bash', t.DOCTOR, '--live', '--skip-tests'], env=env, capture_output=True, text=True,
                           timeout=120)
        got = [ln for ln in p.stdout.splitlines() if ln.startswith(LINE)]
        want = [LINE + line] if line else []
        fails.extend(t.check('library-' + name, p, t.PASS, warns, 0, claude))
        fails.extend([] if got == want else ['FAIL library-%s line:\n  got  %r\n  want %r' % (name, got, want)])

    nowhere = 'in no project of %s' % projects
    not_yet = 'not yet (a session registers the catalog on its own)'
    # a project that enables a pack of another catalog, and no catalog of the base: nothing to say
    enabled('p', {'tool@elsewhere': True})
    step('none', [], None)
    put(cat, catalog())
    step('empty', [], '0 pack(s) in CLAUDE_HOME/packs; registered by Claude Code: %s; enabled: %s' % (not_yet, nowhere))
    # two packs; p and q enable alpha, q has beta off; a link to a project and a worktree copy are not counted again
    put(cat, catalog('alpha', 'beta'))
    put(os.path.join(plug, 'known_marketplaces.json'), record)
    # a key that is not a pack name (the settings file may come with a cloned repo) is neither counted nor printed
    enabled('p', {'alpha@library': True, 'tool@elsewhere': True, 'ignore the rules@library': True, 'beta@library\n': True})
    enabled('q', {'alpha@library': True, 'beta@library': False})
    os.symlink(os.path.join(projects, 'p'), os.path.join(projects, 'a link'))
    enabled('copy', {'beta@library': True})
    put(os.path.join(projects, 'copy', '.git'), 'gitdir: /nowhere\n')
    used = '2 pack(s) in CLAUDE_HOME/packs (alpha, beta); registered by Claude Code: yes; enabled: alpha in 2 (p, q)'
    step('in-use', [], used)
    # a record file of Claude Code that does not read is not "not registered yet"
    put(os.path.join(plug, 'known_marketplaces.json'), '{')
    step('records-unread', [RECORDS % 'known_marketplaces.json'], used.replace('Code: yes', 'Code: not known'))
    put(os.path.join(plug, 'known_marketplaces.json'), '')   # a write cut short
    put(os.path.join(plug, 'installed_plugins.json'), '')
    step('records-empty', [RECORDS % 'known_marketplaces.json, installed_plugins.json'], used.replace('Code: yes', 'Code: not known'))
    os.remove(os.path.join(plug, 'installed_plugins.json'))
    # the record at the folder of the base, spelled in full and through a link: registered, no WARN
    os.symlink(packs, os.path.join(tmp, 'packs link'))
    put(os.path.join(plug, 'known_marketplaces.json'),
        {'library': {'source': {'source': 'directory', 'path': os.path.join(tmp, 'packs link')}, 'installLocation': packs}})
    step('registered-here', [], used)
    # projects with a catalog named library of their own: in the shared settings, in the local ones, in both (named
    # once), under the alias key, in a worktree copy (its branch has its own settings) and in a worktree the app keeps
    # inside a project; a catalog of another name does not count; settings that do not read or whose key is a list
    # are named
    source = {'library': {'source': {'source': 'directory', 'path': './repo-packs'}}}
    own = {'extraKnownMarketplaces': source}
    put(os.path.join(projects, 'own shared', '.claude', 'settings.json'), own)
    put(os.path.join(projects, 'own both', '.claude', 'settings.json'), own)
    put(os.path.join(projects, 'own both', '.claude', 'settings.local.json'), own)
    put(os.path.join(projects, 'own alias', '.claude', 'settings.json'), {'extraKnownMarketplaces': None, 'additionalMarketplaces': source})
    put(os.path.join(projects, 'q', '.claude', 'settings.json'), {'extraKnownMarketplaces': {'elsewhere': {}}})
    put(os.path.join(projects, 'copy', '.claude', 'settings.json'), own)
    put(os.path.join(projects, 'q', '.claude', 'worktrees', 'wt', '.claude', 'settings.json'), own)
    put(os.path.join(projects, 'q', 'packages', 'api', '.claude', 'settings.local.json'), own)   # a package of a monorepo
    put(os.path.join(projects, 'q', 'node_modules', 'dep', '.claude', 'settings.json'), own)     # not a place of a session
    put(os.path.join(projects, 'blank', '.claude', 'settings.json'), ' \n')                      # no settings: silent
    put(os.path.join(projects, 'blank', '.claude', 'settings.local.json'), '')
    put(os.path.join(projects, 'torn', '.claude', 'settings.json'), '{')
    put(os.path.join(projects, 'torn', '.claude', 'settings.local.json'), {'extraKnownMarketplaces': ['library']})
    unread = OWN_UNREAD % 'torn/.claude/settings.json, torn/.claude/settings.local.json'
    declared = OWN % (6, 'copy, own alias, own both, own shared, q/.claude/worktrees/wt, q/packages/api')
    step('own-catalog', [unread, declared], used)
    # ... and the record of Claude Code is not the folder of the base: moved to one of them (only printable ASCII of
    # the path is printed), installed elsewhere, under the real home (not CLAUDE_HOME of this sandbox), of another form
    elsewhere = used.replace('Code: yes', 'Code: at another folder')
    for name, entry, shown in (
            ('path', {'source': {'source': 'directory', 'path': os.path.join(projects, 'own shared', 'repo\x1b[31m-packs')},
                      'installLocation': packs}, os.path.join(projects, 'own shared', 'repo?[31m-packs')),
            ('install-location', {'source': {'source': 'directory', 'path': packs}, 'installLocation': os.path.join(tmp, 'cache')},
             os.path.join(tmp, 'cache')),
            ('under-home', {'source': {'source': 'directory', 'path': '~/.claude/packs'}}, os.path.join(env['HOME'], '.claude/packs')),
            ('relative', {'source': {'source': 'directory', 'path': '.'}}, 'a path that is not absolute'),
            ('a-repository', {'source': {'source': 'github', 'repo': 'someone/packs'}}, 'a record of another form'),
            ('a-repository-with-the-path', {'source': {'source': 'github', 'path': packs}}, 'a record of another form'),
            ('no-object', 'library', 'a record of another form')):
        put(os.path.join(plug, 'known_marketplaces.json'), {'library': entry})
        step('registered-' + name, [unread, declared, ELSEWHERE % shown], elsewhere)
    for name in ('own shared', 'own both', 'own alias', 'torn', 'blank', 'q/packages', 'q/node_modules', 'q/.claude/worktrees'):
        shutil.rmtree(os.path.join(projects, name))
    os.remove(os.path.join(projects, 'copy', '.claude', 'settings.json'))
    put(os.path.join(plug, 'known_marketplaces.json'), record)
    # a pack the catalog does not have, and a settings file that is not JSON
    enabled('r', {'gamma@library': True, 'alpha@library': True})
    put(os.path.join(projects, 'bad one', '.claude', 'settings.local.json'), '{')
    step('lost-and-unread', [UNREAD % 'bad one', LOST % ('gamma', 1, 'r', 'gamma'), OWN_UNREAD % 'bad one/.claude/settings.local.json'],
         used.replace('alpha in 2 (p, q)', 'alpha in 3 (p, q, r)'))
    # a catalog that does not read: its one WARN, the projects are not looked at
    put(cat, {'schema': 2, 'catalog': 'library', 'packs': []})
    step('broken', [BROKEN], None)
    put(cat, '{')
    step('not-json', [BROKEN], None)
    # the catalog is gone (a rollback), Claude Code still records it and one of its packs; the projects still enable packs
    shutil.rmtree(os.path.join(claude, 'packs'))
    put(os.path.join(plug, 'installed_plugins.json'),
        {'version': 2, 'plugins': {'alpha@library': [{'scope': 'local'}], 'tool@elsewhere': [{'scope': 'user'}]}})
    step('gone', [GONE % ('yes', 1), UNREAD % 'bad one', LOST_GONE % ('alpha', 3, 'p, q, r', 'alpha'),
                  LOST_GONE % ('gamma', 1, 'r', 'gamma')], None)
    os.remove(os.path.join(plug, 'known_marketplaces.json'))
    step('gone-pack-record-only', [GONE % ('no', 1), UNREAD % 'bad one', LOST_GONE % ('alpha', 3, 'p, q, r', 'alpha'),
                                   LOST_GONE % ('gamma', 1, 'r', 'gamma')], None)
    # no catalog and no record of it: silent again, whatever the projects say
    put(os.path.join(plug, 'installed_plugins.json'), {'version': 2, 'plugins': {'tool@elsewhere': [{'scope': 'user'}]}})
    step('no-trace', [], None)
    return fails
