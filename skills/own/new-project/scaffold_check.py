"""Offline self-check of the new-project standard: `scaffold.py --self-check`, run by scripts/verify.sh.

Renders every type x db, without and with a brief, into memory (and to disk for the target guards) and checks the
output against the base rules (deploy.md, deps.md, global CLAUDE.md) and the template tree itself. The online gate
(pnpm install, check, docker build and smoke start) is tests/new-project-test.sh.
This file: the run over every combination and the checks of how scaffold.py behaves (template tree, target guards,
rollback, --texts, the brief mode, the skill files); the checks of each rendered file: scaffold_check_files.py; the
folder modes, modules, stages, an existing project and the osv rule: scaffold_check_modes.py; the gap report on a
monorepo: scaffold_check_monorepo.py; where the adoption puts STATUS: scaffold_check_state.py.
"""
import itertools
import json
import os
import re
import tempfile

import brief_check  # next to scaffold.py, which puts its folder on sys.path
import scaffold_render as sr
from scaffold_check_files import EXACT, HTTP_KINDS, check_brief_delta, check_files, check_parity
from scaffold_check_modes import check_modes
from scaffold_check_monorepo import check_monorepo
from scaffold_check_node import check_node
from scaffold_check_state import check_state

# The standard's docs that brief.md has brief_check.py read, next to docs/requirements.md
DOCS_CHECKED = ('docs/decisions.md', 'docs/integrations.md')
ISO_DAY = re.compile(r'\d{4}-\d{2}-\d{2}')


def options(sc, kind, db, target, stage='prod', modules=()):
    argv = [target, '--type', kind, '--db', db, '--risk', 'R1', '--data', 'V0', '--stage', stage, '--name', 'np-check',
            '--date', '2026-01-01'] + (['--ui', 'B'] if kind == 'fullstack' else [])
    for module in modules:
        argv += ['--module', module, '--custom', 'вектори й платні API, бо так вимагає задача']
    return sc.parse(argv)


def check_tree(sc):
    """Every template folder is a layer some type uses, and the defaults of the real argument parser hold."""
    fails = []
    layers = {layer for kind in sr.TYPES for layer in sr.LAYERS[kind]} | {sr.DB_LAYER, sr.ADOPT_LAYER} \
        | {layer for extra in sr.DB_EXTRA.values() for layer in extra} | set(sr.MODULE_LAYERS.values())
    try:
        present = {d for d in os.listdir(sr.TEMPLATES) if os.path.isdir(os.path.join(sr.TEMPLATES, d))}
    except OSError as e:
        return ['templates: %s' % e]
    fails += ['templates/%s is used by no project type' % d for d in sorted(present - layers)]
    fails += ['templates/%s is missing' % d for d in sorted(layers - present)]
    # The passport prints the card before the quiz asks Fastify or NestJS, so it shows one card for both
    if any(d['nest'] != d['api'] for d in (sr.DEFAULT_TIER, sr.DEFAULT_NOT_ADD, sr.DEFAULT_HATCHES)):
        fails.append('defaults: the nest card (tier, «Не додаємо», «Люки») differs from the api card')
    o = sc.parse(['/tmp/My_App', '--type', 'fullstack', '--db', 'none', '--risk', 'R1', '--data', 'V0', '--ui', 'B',
                  '--stage', 'demo'])
    if (o.name, o.ui_source, o.numbers) != ('my-app', sr.DEFAULT_UI_SOURCE, sr.DEFAULT_NUMBERS):
        fails.append('parse: defaults changed (name from the folder, UI source, numbers): %s'
                     % ((o.name, o.ui_source, o.numbers),))
    return fails


def check_guards(sc):
    """The target guard and the option validation refuse what they must."""
    fails = []
    with tempfile.TemporaryDirectory() as tmp:
        # .claude/settings.local.json comes from an "always allow" answer in the new session: still a new folder
        os.makedirs(os.path.join(tmp, '.claude'))
        o = options(sc, 'api', 'none', tmp)
        try:
            sc.write(tmp, sr.plan(o))
        except sr.ScaffoldError as e:
            fails.append('guard: a new folder with only .claude/ was refused: %s' % e)
        else:
            try:
                sc.write(tmp, sr.plan(o))
                fails.append('guard: a second scaffold into the same folder was not refused')
            except sr.ScaffoldError:
                pass
    fails += check_rollback(sc)
    fails += check_texts_file(sc)
    fails += check_brief_target(sc)
    bad = [('fullstack without UI', dict(type='fullstack', ui='none')), ('api with UI', dict(ui='A')),
           ('nest with UI', dict(type='nest', ui='A')), ('long dash in hatches', dict(hatches='worker — env')),
           ('bad name', dict(name='My App')), ('name with a newline', dict(name='ab\n')),
           ('name starting with a digit', dict(name='1c-sync')),
           ('long dash', dict(numbers='a — b')), ('multi-line text', dict(not_add='a\nb')),
           ('carriage return', dict(not_add='a\rb')), ('shell expansion', dict(numbers='$(id)')),
           ('backtick', dict(review_when='`id`')), ('empty numbers', dict(numbers='')),
           ('spaces only', dict(not_add='  ')), ('zero-width space', dict(numbers='a\u200bb')),
           ('bidi override', dict(numbers='a\u202eb')), ('line separator', dict(numbers='a\u2028b')),
           ('next line', dict(numbers='a\x85b')), ('tag character', dict(numbers='a\U000e0041b')),
           ('lone surrogate (non-UTF-8 argv)', dict(numbers='a\udcffb')), ('compact date', dict(date='20261013')),
           ('long dash in the stage goal', dict(stage_goal='a — b')), ('backtick in «Нестандартне»', dict(custom='`id`')),
           ('pgvector without a database', dict(modules=['pgvector'], custom='вектори')),
           ('a module without a reason', dict(modules=['budget']))]
    o = options(sc, 'api', 'none', '/nonexistent')
    o.numbers = 'до 100 замовлень на день, обʼєм 5 ГБ'
    try:
        sc.validate(o)
    except sr.ScaffoldError as e:
        fails.append('guard: plain Ukrainian text with an apostrophe was refused: %s' % e)
    for what, change in bad:
        o = options(sc, 'api', 'none', '/nonexistent')
        for key, value in change.items():
            setattr(o, key, value)
        try:
            sc.validate(o)
            fails.append('guard: %s was accepted' % what)
        except sr.ScaffoldError:
            pass
    return fails


def check_rollback(sc):
    """A failure midway (an OSError or Ctrl-C) leaves the folder as it was: only what existed before stays."""
    fails = []
    real_open = sc.os.open
    for error in (OSError('disk full'), KeyboardInterrupt()):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, '.idea'))
            calls = []

            def failing_open(*args, error=error, calls=calls):
                calls.append(args)
                if len(calls) == 5:
                    raise error
                return real_open(*args)
            sc.os.open = failing_open
            try:
                sc.write(tmp, sr.plan(options(sc, 'bot', 'prisma', tmp)))
                fails.append('rollback: write did not fail on %s' % type(error).__name__)
            except (OSError, KeyboardInterrupt):
                pass
            finally:
                sc.os.open = real_open
            left = sorted(os.listdir(tmp))
            if left != ['.idea']:
                fails.append('rollback: %s left %s' % (type(error).__name__, left))
    return fails


def brief_mode(sc, files=(), links=(), brief_link=False):
    """The brief mode scaffold.py picks for a new folder whose brief/ holds these files, these symlinks to a file
    outside it and an empty subfolder; brief_link: brief itself is a symlink to a folder with a file."""
    with tempfile.TemporaryDirectory() as tmp:
        outside, target = os.path.join(tmp, 'outside'), os.path.join(tmp, 'app')
        brief = os.path.join(target, 'brief')
        os.makedirs(os.path.join(outside, 'scan'))
        os.makedirs(target)
        with open(os.path.join(outside, 'notes.txt'), 'w', encoding='utf-8') as fh:
            fh.write('поза брифом\n')
        if brief_link:
            os.symlink(outside, brief)
        else:
            os.makedirs(os.path.join(brief, 'scan'))
        for rel in files:
            with open(os.path.join(brief, rel), 'w', encoding='utf-8') as fh:
                fh.write('бриф клієнта\n')
        for rel in links:
            os.symlink(os.path.join(outside, 'notes.txt'), os.path.join(brief, rel))
        return options(sc, 'api', 'none', target).brief


def check_brief_target(sc):
    """brief/ with the client's files may wait in the new folder: scaffold.py takes it as a start from a brief and
    leaves it as it was. An empty brief/ (or one with only .DS_Store) is no brief, and symlinks don't count."""
    fails = ['brief: brief/ with %s must %sturn the brief mode on' % (what, '' if want else 'not ')
             for what, kwargs, want in (('only .DS_Store', {'files': ['.DS_Store']}, False),
                                        ('a file at its top', {'files': ['tz.pdf']}, True),
                                        ('a file in a subfolder', {'files': ['scan/page-1.png']}, True),
                                        ('only a symlink to a file outside', {'links': ['tz.pdf']}, False),
                                        ('brief itself a symlink', {'brief_link': True}, False))
             if brief_mode(sc, **kwargs) != want]
    with tempfile.TemporaryDirectory() as tmp:
        tz = os.path.join(tmp, 'brief', 'tz.md')
        os.makedirs(os.path.dirname(tz))
        with open(tz, 'w', encoding='utf-8') as fh:
            fh.write('бриф клієнта\n')
        try:
            sc.write(tmp, sr.plan(options(sc, 'api', 'none', tmp)))
        except sr.ScaffoldError as e:
            fails.append('brief: a new folder with brief/ was refused: %s' % e)
        with open(tz, encoding='utf-8') as fh:
            if fh.read() != 'бриф клієнта\n' or os.listdir(os.path.dirname(tz)) != ['tz.md']:
                fails.append('brief: scaffold.py changed brief/')
    return fails


def check_skill_files(sc):
    """Every file SKILL.md, brief.md and upgrade.md name in the installed skill folder is here: install copies the tag,
    so a file left out of the commit fails this check before it fails a /new-project run. A line that has the model read
    card defaults (`DEFAULT_*`, the passport in SKILL.md) names the file that assigns them."""
    fails = []
    for doc in ('SKILL.md', 'brief.md', 'upgrade.md'):
        try:
            with open(os.path.join(sc.HERE, doc), encoding='utf-8') as fh:
                text = fh.read()
        except OSError as e:
            fails.append('skill: %s' % e)
            continue
        named = set(re.findall(r'~/\.claude/skills/new-project/([\w.-]+)', text))
        fails += ['skill: %s names %s, which is not in the skill folder' % (doc, n) for n in sorted(named)
                  if not os.path.isfile(os.path.join(sc.HERE, n))]
        for line in text.splitlines():
            defaults = sorted(set(re.findall(r'`(DEFAULT_\w+)`', line)))
            sources = [n for n in re.findall(r'~/\.claude/skills/new-project/(\w+\.py)', line)
                       if os.path.isfile(os.path.join(sc.HERE, n))]
            if defaults and not sources:
                fails.append('skill: %s names %s without the file to read them from' % (doc, ', '.join(defaults)))
            for source in sources if defaults else ():
                with open(os.path.join(sc.HERE, source), encoding='utf-8') as fh:
                    code = fh.read()
                fails += ['skill: %s has the model read %s from %s, which does not assign it' % (doc, n, source)
                          for n in defaults if not re.search(r'^%s = ' % n, code, re.M)]
    return fails


def check_brief_check(brief_docs):
    """brief_check.py passes its self-test, and the standard's own docs it reads after a brief start stay clean."""
    fails = brief_check.self_test()
    for label, docs in brief_docs.items():
        for rel, text in docs.items():
            for no, line in enumerate(text.splitlines(), 1):
                kinds = brief_check.line_hits(line, [])
                if kinds:
                    fails.append('%s: %s:%d: brief_check finds %s in the standard' % (label, rel, no, ', '.join(kinds)))
    return fails


def check_texts_file(sc):
    """--texts reads the free text from JSON and refuses unknown keys and non-strings."""
    fails = []
    base = ['/tmp/x-app', '--type', 'api', '--db', 'none', '--risk', 'R1', '--data', 'V0', '--stage', 'prod']
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'texts.json')
        for data, ok in (({'numbers': 'клієнтʼс текст', 'not_add': 'Redis', 'hatches': 'черга на Postgres'}, True),
                         ({'numbers': 'a', 'extra': 'b'}, False), ({'numbers': 5}, False), (['numbers'], False)):
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(data, fh, ensure_ascii=False)
            try:
                o = sc.parse(base + ['--numbers', 'flag text', '--hatches', 'flag text', '--texts', path])
                if not ok:
                    fails.append('texts: %s was accepted' % (data,))
                elif (o.numbers, o.not_add, o.hatches) != (data['numbers'], data['not_add'], data['hatches']):
                    fails.append('texts: values from the file did not win over the flags')
            except sr.ScaffoldError:
                if ok:
                    fails.append('texts: a valid file was refused')
    return fails


def check_node_lines(versions):
    """The schedule of the Node lines holds the standard's line, its LTS start before its end of life."""
    lines = versions.get('node_lines')
    line = lines.get(versions['node']) if isinstance(lines, dict) else None
    dates = [line.get(k) if isinstance(line, dict) else None for k in ('lts', 'end')]
    if not all(isinstance(d, str) and ISO_DAY.fullmatch(d) for d in dates) or dates[0] >= dates[1]:
        return ['versions.json: node_lines has no LTS start and end of life of Node %s' % versions['node']]
    return []


def self_check(sc):
    try:
        versions = sr.load_versions()
    except sr.ScaffoldError as e:
        print(e)
        return 1
    fails, used, nfiles, rendered, plain, brief_docs = [], set(), 0, {}, {}, {}
    for kind, db, brief in itertools.product(sr.TYPES, ('none', 'prisma'), (False, True)):
        try:
            o = options(sc, kind, db, '/nonexistent')
            o.brief = brief
            sc.validate(o)
            files = sr.plan(o)
        except sr.ScaffoldError as e:
            fails.append('%s+%s%s: %s' % (kind, db, '+brief' if brief else '', e))
            continue
        if db == 'none' and not brief:
            rendered[kind] = files
        if not brief:
            plain[kind, db] = files
        else:
            brief_docs['%s+%s+brief' % (kind, db)] = {r: files.get(r, '') for r in DOCS_CHECKED}
            if (kind, db) in plain:
                fails += check_brief_delta(plain[kind, db], files, '%s+%s+brief' % (kind, db))
        nfiles += len(files)
        f, u = check_files(sc, files, versions, kind, db, brief)
        fails += f
        used |= u
    fails += ['versions.json: %s is used by no project type' % p for p in sorted(set(versions['packages']) - used)]
    fails += ['versions.json: override %s %s is not exact' % (p, v) for p, v in versions['overrides'].items()
              if not EXACT.match(v)]
    fails += check_node_lines(versions)
    fails += check_tree(sc) + check_guards(sc) + check_parity(rendered) + check_skill_files(sc) \
        + check_brief_check(brief_docs) + check_modes(sc, versions, plain) + check_monorepo(sc, versions) \
        + check_state(sc) + check_node(versions, plain)
    if set(sr.HTTP_TYPES) != set(HTTP_KINDS):
        fails.append('HTTP types: scaffold_render.py has %s, scaffold_check_files.py expects %s'
                     % (sr.HTTP_TYPES, HTTP_KINDS))
    print('%d combos, each also with a brief, %d files' % (len(sr.TYPES) * 2, nfiles))
    for f in fails:
        print(f)
    return 1 if fails else 0
