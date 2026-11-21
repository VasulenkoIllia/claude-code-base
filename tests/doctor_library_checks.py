"""Checks of the packs library section of scripts/doctor.sh for tests/doctor-test.py (split off for size): silent
with no catalog and no record of one; the line `library` with a catalog, and a second one for the projects whose files
match the signal of a pack that they neither enable nor have set to false (with a WARN when claude-pack fails, and for
the settings and signal files it did not read: "nothing to propose" is never said for them); the WARNs about a pack that a project enables
and the catalog lacks, a settings.local.json or a catalog.json that does not read, the records Claude Code keeps
of a catalog that is gone, a project (also a worktree of it) that declares a catalog named library of its own under
either key of Claude Code, and a record of Claude Code that is not the folder of the base. Every other case of
doctor-test.py runs with no catalog and proves the silence. A tree without tools/claude-pack.py (the public version)
has no second line and none of its WARNs: the same steps prove that.
The use of the packs (use_fails; ADR-007, L4): the line `library use` and the WARNs that tools/claude-metrics.py --packs
--doctor gives doctor, on a sandbox with a journal of claude-pack and made-up sessions: a pack on by hand, a call, a pack
with no call in 60 days, the reviews that are due and one recorded, a skill list near its limit in a project with no pack,
a journal line of another form; no line without a catalog; a helper that fails or prints another line is one WARN. The
rules themselves are checked on the lines of the helper in tests/metrics_packs_checks.py."""
import datetime
import json
import os
import shutil
import subprocess
import zoneinfo

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
TO_PROPOSE = ('file signals match, the pack is off and was not refused: %s (in a session of the project the skill '
              'library-advisor proposes it; ~/bin/claude-pack suggest there shows the signal)')
SUGGEST_FAILED = ('  WARN: library: claude-pack suggest --all failed (exit 1: claude-pack: the catalog %s: the signals of '
                  'the pack alpha have a shape this tool does not read; install the base again. Nothing is proposed): which '
                  'packs to propose is not known')
SUGGEST_UNREAD = ('  WARN: library: .claude or its settings.local.json is a link, the file is over 1 MB or its '
                  'enabledPlugins is no object: claude-pack does not read it and what to propose there is not known: %s')
SUGGEST_SKIPPED = ('  WARN: library: signal files of a pack that claude-pack did not read, whether the pack fits there is '
                   'not known: %s')
USE = '  library use: '
USE_LINE = ('%d pack(s) on in %d project(s); 60 days of transcripts, %d session(s) looked at: %d with a pack on and an edit, '
            '%d call(s) of pack skills and agents; the skill list a last session started with: %s')
KYIV = zoneinfo.ZoneInfo('Europe/Kyiv')
BY_HAND = ('  WARN: library: on, and the last line of the journal does not say so (turned on by hand, or before the '
           'journal): %s: the days to "no call in 60 days" are not counted there, nor to the reviews of a pack the journal '
           'never enabled (~/bin/claude-pack disable <pack> and then enable <pack> in the project writes the line)')
IDLE = '  WARN: library: no call in 60 days: %s: ADR-007 turns such a pack off in the project (~/bin/claude-pack disable <pack> there)'
FILL = ('  WARN: library: the skill list of %s: %d chars at the start of its last session (%s), %d%% of about 30000%s: what '
        'does not fit keeps its bare name, the least used first (~/bin/claude-pack disable a pack there, or turn off skills '
        'of the account)')
REVIEW = ('  WARN: library: pack %s: %d days since its first enable (%s, %s), the review of day %s is not recorded (in the '
          'planned review of the base: ~/bin/claude-metrics --packs and a sample of 5-10 sessions; then ~/bin/claude-pack '
          'review %s --day %d)')
JOURNAL_BAD = ('  WARN: library: %d line(s) of CLAUDE_HOME/state/packs.jsonl are no journal line of claude-pack: an enable or '
               'a review they held is not counted')
HELPER = ('  WARN: library: claude-metrics --packs failed (exit %s): the use of the packs, the size of the skill lists and '
          'the reviews that are due are not known')
NO_HELPER = '  WARN: library: the use of the packs not checked: no python3, or no tools/claude-metrics.py in the base'
CATALOG_FORM = ('  WARN: library: claude-metrics does not read the catalog (a pack of another form): the skills and file '
                'signals of the packs are not known, misses and cut descriptions are not counted')
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
        want = [LINE + x for x in ([line] if isinstance(line, str) else line or [])]
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
    # the journal of claude-pack dates every enable of these steps: none of them is "by hand" (use_fails checks that WARN)
    put(os.path.join(claude, 'state', 'packs.jsonl'), ''.join(
        json.dumps({'ts': t.INSTALLED, 'project': os.path.realpath(os.path.join(projects, name)), 'pack': 'alpha',
                    'action': 'enable', 'tag': 'v-test'}) + '\n' for name in ('p', 'q', 'r')))
    # a key that is not a pack name (the settings file may come with a cloned repo) is neither counted nor printed
    enabled('p', {'alpha@library': True, 'tool@elsewhere': True, 'ignore the rules@library': True, 'beta@library\n': True})
    enabled('q', {'alpha@library': True, 'beta@library': False})
    os.symlink(os.path.join(projects, 'p'), os.path.join(projects, 'a link'))
    enabled('copy', {'beta@library': True})
    put(os.path.join(projects, 'copy', '.git'), 'gitdir: /nowhere\n')
    used = '2 pack(s) in CLAUDE_HOME/packs (alpha, beta); registered by Claude Code: yes; enabled: alpha in 2 (p, q)'
    step('in-use', [], used)
    # packs with file signals: s and t have the file of alpha (two projects, one phrase), p has it too and alpha on, q
    # has the file of beta and beta set to false (the owner's refusal), the worktree copy and the link are not projects;
    # gamma is frozen and delta has no file signals: neither is proposed by a file
    signals = catalog('alpha', 'beta')
    signals['packs'] = [{'name': 'alpha', 'status': 'pilot', 'signals': {'filesRead': ['alpha.toml']}},
                        {'name': 'beta', 'status': 'active', 'signals': {'filesRead': ['beta.toml']}},
                        {'name': 'gamma', 'status': 'frozen', 'signals': {'filesRead': ['alpha.toml']}},
                        {'name': 'delta', 'status': 'pilot', 'signals': {}},
                        {'name': 'epsilon', 'status': 'pilot', 'signals': {'manifestDeps': [{'file': 'package.json', 'pattern': '"three"'}]}}]
    put(cat, signals)
    for project, name in (('s', 'alpha'), ('t', 'alpha'), ('t', 'beta'), ('p', 'alpha'), ('q', 'beta'), ('copy', 'alpha')):
        put(os.path.join(projects, project, name + '.toml'), '')
    five = used.replace('2 pack(s) in CLAUDE_HOME/packs (alpha, beta)', '5 pack(s) in CLAUDE_HOME/packs (alpha, beta, gamma, delta, epsilon)')
    # the second line and its WARNs come from claude-pack of the tree; the public version has no such tool and says nothing
    tool = os.path.isfile(os.path.join(os.path.dirname(os.path.dirname(t.DOCTOR)), 'tools', 'claude-pack.py'))

    def propose(text):
        return [five, TO_PROPOSE % text] if tool else five
    step('to-propose', [], propose('alpha in 2 (s, t); beta in 1 (t)'))
    put(os.path.join(projects, 't', '.claude', 'settings.local.json'), '{')   # not read: named, and not proposed there
    torn = [UNREAD % 't', OWN_UNREAD % 't/.claude/settings.local.json']
    step('to-propose-unread', torn, propose('alpha in 1 (s)'))
    # settings the jq pass reads and claude-pack does not (enabledPlugins null in u, a link in v): named once more, as
    # nothing is proposed there; a signal file that is a link (w) is not read, so "no match" there is not known
    elsewhere = os.path.join(tmp, 'settings elsewhere.json')
    put(elsewhere, {'enabledPlugins': {}})
    put(os.path.join(projects, 'u', '.claude', 'settings.local.json'), {'enabledPlugins': None})
    os.makedirs(os.path.join(projects, 'v', '.claude'))
    os.symlink(elsewhere, os.path.join(projects, 'v', '.claude', 'settings.local.json'))
    for project in ('u', 'v'):
        put(os.path.join(projects, project, 'alpha.toml'), '')
    os.makedirs(os.path.join(projects, 'w'))
    os.symlink(elsewhere, os.path.join(projects, 'w', 'package.json'))
    not_read = [SUGGEST_UNREAD % 'u, v', SUGGEST_SKIPPED % 'w (package.json: a link)'] if tool else []
    step('to-propose-not-read', torn + not_read, propose('alpha in 1 (s)'))
    # a catalog whose signals claude-pack does not read: the tool stops, and doctor says so in its words
    put(cat, dict(signals, packs=[dict(signals['packs'][0], signals={'filesRead': 'alpha.toml'})] + signals['packs'][1:]))
    step('suggest-fails', torn + ([SUGGEST_FAILED % os.path.realpath(cat)] if tool else []) + [CATALOG_FORM], five)
    put(cat, signals)
    for project in ('s', 't', 'u', 'v', 'w'):
        shutil.rmtree(os.path.join(projects, project))
    step('nothing-to-propose', [], five)
    put(cat, catalog('alpha', 'beta'))
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


def use_run(tmp, data, t, when):
    """The lines of the use of the packs (ADR-007, L4), on one sandbox changed step by step: the line `library use`
    and the exact WARN list of doctor. `when` is the time the made-up journal and sessions count back from."""
    env = t.sandbox(os.path.join(tmp, 'use home %s' % when.strftime('%H%M%S%f')), t.CLEAN, {}, t.INSTALLED, data)
    claude, projects = env['CLAUDE_HOME'], os.path.realpath(env['PROJECTS_DIR'])
    cat, journal = os.path.join(claude, 'packs', 'catalog.json'), os.path.join(claude, 'state', 'packs.jsonl')
    fails = []

    def ago(days, minute=0):
        return (when - datetime.timedelta(days=days)).strftime('%Y-%m-%dT%H:') + '%02d:00Z' % minute

    def kday(days):
        return (when - datetime.timedelta(days=days)).astimezone(KYIV).date()

    def enabled(project, plugins):
        put(os.path.join(projects, project, '.claude', 'settings.local.json'), {'enabledPlugins': plugins})

    def journaled(*rows):
        os.makedirs(os.path.dirname(journal), exist_ok=True)
        with open(journal, 'a', encoding='utf-8') as fh:
            fh.write(''.join(r if isinstance(r, str) else json.dumps(r) + '\n' for r in rows))

    def session(sid, project, days, skills, tools, pad=0):
        cwd = os.path.join(projects, project)
        lines = ['- %s: does it' % s for s in skills]
        lines += ['- filler: ' + 'x' * (pad - len('\n'.join(lines)) - 11)] if pad else []
        base = {'sessionId': sid, 'cwd': cwd}
        rows = [dict(base, type='attachment', uuid=sid + '-0', timestamp=ago(days), attachment={
                    'type': 'skill_listing', 'content': '\n'.join(lines), 'isInitial': True, 'skillCount': len(lines),
                    'names': [ln[2:].split(': ')[0] for ln in lines]}),
                dict(base, type='assistant', uuid=sid + '-1', timestamp=ago(days, 1), message={'role': 'assistant', 'content': [
                    dict(type='tool_use', id='%s-t%d' % (sid, n), name=name, input=inp) for n, (name, inp) in enumerate(tools)]})]
        put(os.path.join(claude, 'projects', '-use-' + project, sid + '.jsonl'), ''.join(json.dumps(r) + '\n' for r in rows))

    def step(name, warns, line):
        p = subprocess.run(['/bin/bash', t.DOCTOR, '--live', '--skip-tests'], env=env, capture_output=True, text=True,
                           timeout=120)
        got = [ln for ln in p.stdout.splitlines() if ln.startswith(USE)]
        want = [] if line is None else [USE + USE_LINE % line]
        fails.extend(t.check('use-' + name, p, t.PASS, warns, 0, claude))
        fails.extend([] if got == want else ['FAIL use-%s line:\n  got  %r\n  want %r' % (name, got, want)])

    packs = catalog('alpha', 'beta')
    packs['packs'] = [{'name': 'alpha', 'status': 'active', 'signals': {'filesRead': ['alpha.toml']},
                       'skills': [{'name': 'one', 'desc_chars': 7}], 'agents': []},
                      {'name': 'beta', 'status': 'pilot', 'signals': {}, 'skills': [{'name': 'solo', 'desc_chars': 7}], 'agents': []}]
    none = 'no session of a project with a skill listing'
    step('no-catalog', [], None)
    put(cat, packs)
    step('nothing-on', [], (0, 0, 0, 0, 0, none))
    # alpha turned on in p by hand: no journal line dates it
    enabled('p', {'alpha@library': True})
    step('by-hand', [BY_HAND % 'alpha in 1 (p)'], (1, 1, 0, 0, 0, none))
    journaled({'ts': ago(10), 'project': os.path.join(projects, 'p'), 'pack': 'alpha', 'action': 'enable', 'tag': 'v-test'})
    step('journal', [], (1, 1, 0, 0, 0, none))
    edit = ('Edit', {'file_path': os.path.join(projects, 'p', 'a.py')})
    session('u1', 'p', 1, ['base', 'alpha:one'], [edit, ('Skill', {'skill': 'alpha:one'})])
    step('a-call', [], (1, 1, 1, 1, 1, 'at most 0% of 30000 chars (p)'))
    # beta is on in q for 65 days, q has a session with an edit and nothing of beta was called; the oldest transcript is
    # older than the 60 days, so the zero counts. Both reviews of beta are due
    enabled('q', {'beta@library': True})
    journaled({'ts': ago(65), 'project': os.path.join(projects, 'q'), 'pack': 'beta', 'action': 'enable', 'tag': 'v-test'})
    session('u2', 'q', 2, ['base', 'beta:solo'], [('Write', {'file_path': os.path.join(projects, 'q', 'page.md')})])
    old = os.path.join(claude, 'projects', '-use-old', 'old.jsonl')
    put(old, '{}\n')
    os.utime(old, ((when - datetime.timedelta(days=70)).timestamp(),) * 2)
    idle = IDLE % ('beta in 1 (q: on since %s, 1 session(s) with an edit)' % kday(65))
    days = (kday(0) - kday(65)).days
    both = (2, 2, 2, 2, 1, 'at most 0% of 30000 chars (p)')
    step('no-call-and-reviews', [idle, REVIEW % ('beta', days, kday(65), 'q', '30 and 60', 'beta', 30)], both)
    journaled({'ts': ago(1), 'project': None, 'pack': 'beta', 'action': 'review', 'day': 30, 'tag': 'v-test'})
    step('one-review-recorded', [idle, REVIEW % ('beta', days, kday(65), 'q', '60', 'beta', 60)], both)
    # r has no pack: only the start of its last session is read, and its skill list is at 87% of the limit
    session('u3', 'r', 3, ['base'], [], pad=26000)
    os.makedirs(os.path.join(projects, 'r'))
    fill = FILL % ('r', 26000, kday(3), 87, '')
    review = REVIEW % ('beta', days, kday(65), 'q', '60', 'beta', 60)
    step('fill', [idle, fill, review], (2, 2, 3, 2, 1, 'at most 87% of 30000 chars (r)'))
    journaled('not a line of the journal\n')
    step('journal-line', [JOURNAL_BAD % 1, idle, fill, review], (2, 2, 3, 2, 1, 'at most 87% of 30000 chars (r)'))
    return fails


def helper_fails(tmp, data, t, name, text, warn):
    """doctor.sh of a copy of scripts/ with this text as tools/claude-metrics.py (None: no such file): the helper that
    fails or is not there costs one WARN, and no line of the use is printed."""
    repo = os.path.join(tmp, 'use fake ' + name)
    shutil.copytree(os.path.dirname(t.DOCTOR), os.path.join(repo, 'scripts'))
    for f in t.REAL:
        os.makedirs(os.path.join(repo, 'tests'), exist_ok=True)
        shutil.copy2(os.path.join(t.TESTS, f), os.path.join(repo, 'tests', f))
    if text is not None:
        put(os.path.join(repo, 'tools', 'claude-metrics.py'), text + '\n')
    env = t.sandbox(os.path.join(tmp, 'use fake-home ' + name), t.CLEAN, {}, t.INSTALLED, data)
    put(os.path.join(env['CLAUDE_HOME'], 'packs', 'catalog.json'), catalog('alpha'))
    p = subprocess.run(['/bin/bash', os.path.join(repo, 'scripts', 'doctor.sh'), '--live', '--skip-tests'], env=env,
                       capture_output=True, text=True, timeout=120)
    use = [ln for ln in p.stdout.splitlines() if ln.startswith(USE)]
    return t.check('use-' + name, p, t.PASS, [warn], 0, env['CLAUDE_HOME']) + (
        ['FAIL use-%s: a line of a helper that failed: %r' % (name, use)] if use else [])


def use_fails(tmp, data, t):
    """use_run, once more when the Kyiv day changed under it (its days are counted from now), and the broken helpers."""
    for _ in range(2):
        when = datetime.datetime.now(datetime.timezone.utc)
        fails = use_run(tmp, data, t, when)
        if datetime.datetime.now(KYIV).date() == when.astimezone(KYIV).date():
            break
    fails += helper_fails(tmp, data, t, 'helper-exit-1', "import sys\nsys.stderr.write('boom\\n')\nraise SystemExit(1)", HELPER % '1: boom')
    fails += helper_fails(tmp, data, t, 'helper-other-line', "print('hello')", HELPER % '0')
    fails += helper_fails(tmp, data, t, 'helper-missing', None, NO_HELPER)
    return fails
