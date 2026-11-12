"""Checks of the packs library section of scripts/doctor.sh for tests/doctor-test.py (split off for size): silent
with no catalog and no record of one; the line `library` with a catalog; the WARNs about a pack that a project enables
and the catalog lacks, a settings.local.json or a catalog.json that does not read, and the records Claude Code keeps
of a catalog that is gone. Every other case of doctor-test.py runs with no catalog and proves the silence."""
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
    put(os.path.join(plug, 'known_marketplaces.json'), {'library': {'source': {}}, 'elsewhere': {}})
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
    put(os.path.join(plug, 'known_marketplaces.json'), {'library': {'source': {}}, 'elsewhere': {}})
    # a pack the catalog does not have, and a settings file that is not JSON
    enabled('r', {'gamma@library': True, 'alpha@library': True})
    put(os.path.join(projects, 'bad one', '.claude', 'settings.local.json'), '{')
    step('lost-and-unread', [UNREAD % 'bad one', LOST % ('gamma', 1, 'r', 'gamma')],
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
