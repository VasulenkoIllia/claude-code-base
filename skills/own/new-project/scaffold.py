#!/usr/bin/env python3
"""Create a project from the base standard (skill /new-project). No network and no pnpm: the skill runs pnpm install
and the gates afterwards.

  python3 -I scaffold.py <target> --type api|nest|fullstack|integration|bot --db prisma|none \
      --risk R0|R1|R2 --data V0|V1|V2 --stage demo|pilot|prod [--module pgvector] [--module budget] \
      [--ui A|B|none] [--tier T0..T3] [--name app-name] [--texts FILE.json] [--numbers TEXT] [--not-add TEXT] \
      [--hatches TEXT] [--review-when TEXT] [--ui-source TEXT] [--stage-goal TEXT] [--custom TEXT] [--date YYYY-MM-DD]
  python3 -I scaffold.py <target> --inspect    # the folder: mode new, ide (with its files) or existing; writes nothing
  python3 -I scaffold.py <target> --move-ide [--backup-dir DIR]    # after the owner's yes: the template into a backup
  python3 -I scaffold.py <target> --init-git    # after the scaffold: the repository on main, none of its hooks run
  python3 -I scaffold.py <target> --adopt --risk R --data V --stage S --tier T [--ui A|B|none] [--name N] \
      [--texts FILE.json] [--date YYYY-MM-DD]    # an existing project: card, docs skeleton, STATUS, gap report, no code
  python3 -I scaffold.py --self-check    # render every type x db into temp dirs and check the output

--texts reads the free-text fields from a JSON object (keys numbers, not_add, hatches, review_when, ui_source,
stage_goal, custom), so the texts never pass through a shell; it wins over the matching flags.
A brief/ folder with the client's files in the target is a start from a brief: the card and docs/decisions.md say the
server and CI/CD are not decided yet, README points to docs/requirements.md; brief/ itself is never touched.
Writes only into an empty target (.git, .idea, .claude, .DS_Store and brief may exist). Everything is rendered in memory
first and each file is created with O_EXCL; if writing fails midway (any error, Ctrl-C too), the files and folders
this run created are removed, so a retry starts from the same empty folder and nothing that existed before is touched.
This file: the options, their checks and the write. What each type gets (with the card defaults) and the template
rendering: scaffold_render.py; the folder modes: scaffold_target.py; an existing project: scaffold_adopt.py with
scaffold_gaps.py and scaffold_project.py; the self-check: scaffold_check.py with scaffold_check_files.py,
scaffold_check_modes.py, scaffold_check_monorepo.py and scaffold_check_state.py.
"""
import argparse
import datetime
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True  # no __pycache__ in the installed skill folder
# -I leaves the script's folder off sys.path: scaffold_render, brief_tree and scaffold_check sit next to this file
sys.path.insert(0, HERE)

import scaffold_adopt  # noqa: E402
from scaffold_render import (  # noqa: E402
    DEFAULT_CUSTOM, DEFAULT_NUMBERS, DEFAULT_REVIEW_WHEN, DEFAULT_STAGE_GOAL, DEFAULT_UI_SOURCE, MODULE_LAYERS, STAGES,
    TYPES, ScaffoldError, load_versions, plan)
from scaffold_target import classify, init_main, inspect_lines, move_template, shown  # noqa: E402

BRIEF_DIR = 'brief'
NAME_RE = re.compile(r'[a-z][a-z0-9-]{1,48}')
# The name of an existing project: it titles the card, so no spaces, which would let a folder name read as a sentence
ADOPT_NAME_RE = re.compile(r'[\w.-]{1,60}')
# Free text lands in CLAUDE.local.md, which Claude reads as instructions: no shell syntax, template markers or long
# dashes, and no invisible characters (controls, format and bidi marks, line separators, private use, tags)
BAD_TEXT_RE = re.compile(r'[`$–—]|\{\{')
BAD_CATEGORIES = {'Cc', 'Cf', 'Cn', 'Co', 'Cs', 'Zl', 'Zp'}
TEXT_KEYS = ('numbers', 'not_add', 'hatches', 'review_when', 'ui_source', 'stage_goal', 'custom')
LONG_DASHES = ('—', '–')
TEXT_MAX = 200


def has_brief(target):
    """A start from a brief: brief_tree.py lists a file in brief/ of the target, the same list `brief_check.py tree`
    prints for the skill (no symlinks, special files, junk such as .DS_Store, or macOS metadata copies)."""
    import brief_tree  # pylint: disable=import-outside-toplevel  # next to this file, on sys.path from the top
    return bool(brief_tree.scan(os.path.join(target, BRIEF_DIR))[0])


def check_target(target):
    folder = classify(target)
    if folder.kind != 'new':
        names = ', '.join(shown(name) for name in folder.entries[:5])
        raise ScaffoldError('%s is not empty (%s): the standard starts only in a new empty folder (--inspect names the '
                            'mode)' % (target, names or '%d commits' % folder.commits))


def write(target, files):
    check_target(target)
    return write_files(target, files)


def check_no_links(target, files):
    """Nothing is written through a link: an existing project may hold docs -> ~/.claude/rules."""
    for rel in files:
        parts = rel.split('/')[:-1]
        for depth in range(1, len(parts) + 1):
            if os.path.islink(os.path.join(target, *parts[:depth])):
                raise ScaffoldError('%s is a link: nothing is written through it' % '/'.join(parts[:depth]))


def write_files(target, files):
    check_no_links(target, files)
    created_files, created_dirs = [], []
    try:
        for rel in sorted(files):
            path = os.path.join(target, rel)
            parent = os.path.dirname(path)
            missing = []
            while not os.path.isdir(parent):
                missing.append(parent)
                parent = os.path.dirname(parent)
            for d in reversed(missing):
                os.mkdir(d)
                created_dirs.append(d)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            created_files.append(path)
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                fh.write(files[rel])
    except BaseException:
        undo(created_files, created_dirs)
        raise
    return sorted(files)


def undo(created_files, created_dirs):
    """Best effort: a file that cannot be removed stays (the retry then reports the folder as not empty), and the
    original error is what the caller sees."""
    for path in reversed(created_files):
        try:
            os.unlink(path)
        except OSError:
            pass
    for d in reversed(created_dirs):
        try:
            os.rmdir(d)
        except OSError:
            pass


def validate(o):
    if o.type == 'fullstack' and o.ui == 'none':
        raise ScaffoldError('--ui A or B for fullstack (A desktop, B also on a phone)')
    if o.type != 'fullstack' and o.ui != 'none':
        raise ScaffoldError('--ui applies to fullstack only; %s has no web UI' % o.type)
    if o.type != 'fullstack' and o.ui_source:
        raise ScaffoldError('--ui-source applies to fullstack only')
    if not NAME_RE.fullmatch(o.name):
        raise ScaffoldError('name "%s": starts with a lowercase letter, then lowercase letters, digits and -, '
                            '2-49 chars (pass --name)' % o.name)
    if 'pgvector' in o.modules and o.db != 'prisma':
        raise ScaffoldError('--module pgvector needs --db prisma')
    if o.modules and o.custom == DEFAULT_CUSTOM:
        raise ScaffoldError('--module: name it and why in --custom (the card line «Нестандартне»)')
    check_texts(o)
    for key in ('numbers', 'review_when') + (('ui_source',) if o.type == 'fullstack' else ()):
        if not getattr(o, key):
            raise ScaffoldError('--%s must not be empty' % key.replace('_', '-'))
    check_date(o)


def check_texts(o):
    for key in TEXT_KEYS:
        text, flag = getattr(o, key), '--' + key.replace('_', '-')
        if (BAD_TEXT_RE.search(text) or len(text) > TEXT_MAX
                or any(unicodedata.category(c) in BAD_CATEGORIES for c in text)):
            raise ScaffoldError('%s: one line up to %d chars; no $, backticks, long dashes, control or invisible '
                                'characters' % (flag, TEXT_MAX))
        if text and not text.strip():
            raise ScaffoldError('%s holds only spaces' % flag)


def check_date(o):
    try:
        if datetime.date.fromisoformat(o.date).isoformat() != o.date:
            raise ValueError('not YYYY-MM-DD')
    except ValueError as e:
        raise ScaffoldError('--date %s: %s' % (o.date, e)) from e


def read_texts(path):
    """Free-text fields from a JSON object, written by the skill with the Write tool instead of a shell command."""
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        raise ScaffoldError('--texts %s: %s' % (path, e)) from e
    if not isinstance(data, dict):
        raise ScaffoldError('--texts: a JSON object with keys ' + ', '.join(TEXT_KEYS))
    unknown = sorted(set(data) - set(TEXT_KEYS))
    if unknown:
        raise ScaffoldError('--texts: unknown keys %s (allowed: %s)' % (', '.join(unknown), ', '.join(TEXT_KEYS)))
    if not all(isinstance(v, str) for v in data.values()):
        raise ScaffoldError('--texts: every value is a string')
    return data


def validate_adopt(o):
    """An existing project keeps its name, whatever its folder is called: the name only titles the card."""
    if not ADOPT_NAME_RE.fullmatch(o.name):
        raise ScaffoldError('name %s: letters, digits, dots, _ and -, up to 60 chars (pass --name)' % ascii(o.name))
    if o.modules or o.type or o.db:
        raise ScaffoldError('--adopt takes no --type, --db or --module: it changes no code, a module is a later task')
    check_texts(o)
    missing = [key.replace('_', '-') for key in ('not_add', 'hatches') if not getattr(o, key)]
    if missing:
        raise ScaffoldError('--adopt needs --%s: there is no type to take a default from' % ' and --'.join(missing))
    check_date(o)


def parse(argv):
    ap = argparse.ArgumentParser(description='Create a project from the base standard.')
    ap.add_argument('target', nargs='?')
    ap.add_argument('--self-check', action='store_true')
    ap.add_argument('--inspect', action='store_true')
    ap.add_argument('--move-ide', dest='move_ide', action='store_true')
    ap.add_argument('--backup-dir', dest='backup_dir')
    ap.add_argument('--init-git', dest='init_git', action='store_true')
    ap.add_argument('--adopt', action='store_true')
    ap.add_argument('--type', choices=TYPES)
    ap.add_argument('--db', choices=('prisma', 'none'))
    ap.add_argument('--name')
    ap.add_argument('--tier', choices=('T0', 'T1', 'T2', 'T3'))
    ap.add_argument('--risk', choices=('R0', 'R1', 'R2'))
    ap.add_argument('--data', choices=('V0', 'V1', 'V2'))
    ap.add_argument('--stage', choices=tuple(STAGES))
    ap.add_argument('--module', dest='modules', action='append', choices=tuple(MODULE_LAYERS), default=[])
    ap.add_argument('--ui', choices=('A', 'B', 'none'), default='none')
    ap.add_argument('--numbers', default=DEFAULT_NUMBERS)
    ap.add_argument('--not-add', dest='not_add', default='')
    ap.add_argument('--hatches', default='')
    ap.add_argument('--review-when', dest='review_when', default=DEFAULT_REVIEW_WHEN)
    ap.add_argument('--ui-source', dest='ui_source', default='')
    ap.add_argument('--stage-goal', dest='stage_goal', default=DEFAULT_STAGE_GOAL)
    ap.add_argument('--custom', default=DEFAULT_CUSTOM)
    ap.add_argument('--texts', metavar='FILE.json')
    ap.add_argument('--date', default=datetime.date.today().isoformat())
    o = ap.parse_args(argv)
    if o.self_check:
        return o
    if o.texts:
        for key, text in read_texts(o.texts).items():
            setattr(o, key, text)
    folder_only = o.inspect or o.move_ide or o.init_git
    required = ('target',) if folder_only else ('target', 'risk', 'data', 'stage', 'tier') if o.adopt \
        else ('target', 'type', 'db', 'risk', 'data', 'stage')
    for key in required:
        if not getattr(o, key):
            ap.error('%s is required' % ('target' if key == 'target' else '--' + key))
    o.target = os.path.abspath(o.target)
    o.modules = sorted(set(o.modules))
    if folder_only:
        return o
    if o.adopt:
        o.name = o.name or os.path.basename(o.target)
        return o
    o.brief = has_brief(o.target)
    o.name = o.name or os.path.basename(o.target).lower().replace('_', '-')
    if o.type == 'fullstack' and not o.ui_source:
        o.ui_source = DEFAULT_UI_SOURCE
    return o


def main(argv):
    try:
        o = parse(argv)
        if o.self_check:
            from scaffold_check import self_check  # pylint: disable=import-outside-toplevel
            return self_check(sys.modules[__name__])
        if o.inspect:
            print('\n'.join(inspect_lines(classify(o.target))))
            return 0
        if o.move_ide:
            return report_move(*move_template(o.target, o.backup_dir))
        if o.init_git:
            init_main(o.target)
            print('scaffold: git on main in %s, no commit' % o.target)
            return 0
        if o.adopt:
            return adopt(o)
        validate(o)
        written = write(o.target, plan(o))
    except (ScaffoldError, OSError) as e:
        print('scaffold: %s' % e, file=sys.stderr)
        return 1
    print('scaffold: %d files in %s%s' % (len(written), o.target, ' (start from brief/)' if o.brief else ''))
    for rel in written:
        print('  ' + rel)
    return 0


def report_move(dest, moved):
    print('scaffold: moved %d entries to %s; nothing deleted' % (len(moved), dest))
    for name in moved:
        print('  ' + shown(name))
    return 0


def adopt(o):
    if classify(o.target).kind != 'existing':
        raise ScaffoldError('%s: not an existing project (--inspect names the mode)' % o.target)
    validate_adopt(o)
    files, gaps, notes = scaffold_adopt.plan(o, load_versions())
    written = write_files(o.target, files)
    print('scaffold: adopted %s: %d files, %d gaps' % (o.target, len(written), len(gaps)))
    for rel in written:
        print('  created ' + rel)
    for rel in scaffold_adopt.kept(o.target, files):
        print('  kept ' + rel)
    for line in gaps:
        print('  gap: ' + line)
    for line in notes:
        print('  note: ' + line)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
