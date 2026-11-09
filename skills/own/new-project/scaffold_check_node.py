"""Self-check of node_std.py, the Node standard against a project: the state of each line by a schedule made up here
(the next standard keeps the check), where a project names its Node (.nvmrc, a Dockerfile with an ARG, Compose, the CI
configs and a matrix, a CI folder that is a link, a file not read), the adoption's Node lines (none for a project of the
standard, each for a project that breaks it, no text of the project quoted), the flags of project-doctor, the stack
lines of doctor (a folder that fails or hangs among them), the inventory of upgrade.md, files of blank lines within
the time budget. Offline, in temp folders.
"""
import datetime
import json
import os
import tempfile
import time

import node_std
import scaffold_project
from scaffold_check_modes import INJECTED, put

DAY = datetime.date(2026, 11, 8)
SCHEDULE = {'20': {'lts': '2023-10-24', 'end': '2026-04-30'}, '22': {'lts': '2024-10-29', 'end': '2027-04-30'},
            '24': {'lts': '2025-10-28', 'end': '2028-04-30'}, '26': {'lts': '2026-10-28', 'end': '2029-04-30'},
            '27': {'lts': '2027-10-20', 'end': '2030-04-30'}}
SETUP_NODE = '    steps:\n      - uses: actions/setup-node@v4\n        with:\n          node-version: %s\n'
# A project and the state its oldest Node gives on DAY by SCHEDULE, with Node 26 as the standard
STATES = (({'.nvmrc': '26\n'}, 'standard'), ({'.nvmrc': 'v27.0.0\n'}, 'newer'), ({'.nvmrc': '24\n'}, 'behind'),
          ({'.nvmrc': '22\n'}, 'soon'), ({'.nvmrc': '20\n'}, 'eol'), ({'.nvmrc': '25\n'}, 'eol'),
          ({'.nvmrc': '16\n'}, 'eol'), ({}, 'unpinned'), ({'.nvmrc': '\n'}, 'unpinned'),
          ({'.nvmrc': 'lts/*\n'}, 'unknown'),
          ({'.nvmrc': '26\n', 'Dockerfile': 'ARG NODE=24\nFROM node:${NODE}-alpine\n'}, 'behind'),
          ({'.nvmrc': '26\n', 'Dockerfile': 'FROM --platform=linux/amd64 node:${V:-20} AS b\nFROM b\n'}, 'eol'),
          ({'.nvmrc': '26\n', 'compose.yaml': 'services:\n  a:\n    image: "node:22-alpine"\n'}, 'soon'),
          ({'.nvmrc': '26\n', '.github/workflows/ci.yml': 'jobs:\n  t:\n' + SETUP_NODE % '[20.x, 26]'}, 'standard'),
          ({'.nvmrc': '26\n', '.github/workflows/ci.yml': 'jobs:\n  t:\n' + SETUP_NODE % '[20, 24.x]'}, 'behind'),
          ({'.nvmrc': '26\n', '.github/workflows/ci.yml': SETUP_NODE % '20'}, 'eol'),
          ({'.nvmrc': 'lts/*\n', 'Dockerfile': 'FROM node:26\n'}, 'unknown'),
          ({'.nvmrc': 'lts/*\n', 'Dockerfile': 'FROM node:20\n'}, 'eol'),
          ({'.nvmrc': '26\n', '.gitlab-ci.yml': 'test:\n  image: cimg/node:24.11\n'}, 'behind'),
          ({'.nvmrc': '26\n', '.github/workflows/ci.yml': SETUP_NODE % '${{ matrix.node }}'}, 'standard'),
          ({'.nvmrc': '26\n', '.github/workflows/ci.yml': SETUP_NODE % "'lts/*'"}, 'standard'),
          ({'.nvmrc': '26\n', 'Dockerfile': 'FROM node:lts\nFROM node\n'}, 'standard'),
          ({'.nvmrc': '26\n', 'Dockerfile': 'FROM mynode:20\nFROM reg:5000/node:26\n'}, 'standard'))
BROKEN = {'package.json': json.dumps({'engines': {'node': '>=18'}, 'dependencies': {
              'fastify': '^4.2.0 || ^3.0.0', 'react': 'catalog:old', 'vite': 'npm:rolldown-vite@7',
              'typescript': '99.0.0'}}),
          'pnpm-workspace.yaml': 'catalogs:\n  old:\n    react: ^18.3.0\n', '.nvmrc': '20\n',
          'infra/api.Dockerfile': 'FROM node:24-alpine\n', '.github/workflows/ci.yml': 'node-version: 22\n'}
BROKEN_LINES = ('образи Docker не на Node 26: `infra/api.Dockerfile` (24)',
                'CI не на Node 26: `.github/workflows/ci.yml` (22)', '`engines.node` від Node 18, стандарт `>=26`',
                'Node 20 без підтримки з 2026-04-30', 'fastify 4 (стандарт ', 'react 18 (стандарт ')
ENGINES = (('{"name": "a"}', 'немає `engines.node`: стандарт `>=26`'),
           ('{"engines": {"node": "18 || 20"}}', 'іншої форми'),
           ('{"engines": {"node": 26}}', 'іншої форми'), ('{"engines": {"node": ">=26"}}', None),
           ('{"engines": {"node": "^26.1"}}', None))
FLAGS = (({'package.json': '{"packageManager": "pnpm@12.9.1"}', 'pnpm-lock.yaml': '', '.nvmrc': '24\n'},
          ['NODE<STD:24<26', 'PNPM<STD:12.9.1<12.14.0']),
         ({'package.json': '{"name": "a"}', 'package-lock.json': '{}', '.nvmrc': '20\n'},
          ['NODE-EOL:20', 'PM!=STD:npm']),
         ({'package.json': '', 'package-lock.json': '{}', '.nvmrc': '20\n'}, []),
         ({'package.json': '{"packageManager": "pnpm@12.14.0"}', '.nvmrc': '22\n'}, ['NODE-EOL:22']),
         ({'package.json': '{"packageManager": "pnpm@12.14.0"}', '.nvmrc': '26\n'}, []),
         ({'package.json': '{"packageManager": "pnpm@12.14.0"}'}, ['NODE-UNPINNED']),
         ({'package.json': '{"packageManager": "pnpm@12.14.0"}', '.nvmrc': 'lts/*\n'}, ['NODE-UNKNOWN']),
         ({'.nvmrc': '20\n'}, []))
# The worst cases of a regex that starts with ^\s* under re.M and of two quantifiers of spaces side by side, within
# the 1 MB scaffold_gaps reads
BLANK = '\n' * 400_000 + ' ' * 500_000 + '\n'
# Catalog lines of spaces, the second with a quote inside its version: a lazy version between two runs of spaces took
# cubic time on it
CATALOG_SPACES = 'catalog:\n  react: ' + ' ' * 200_000 + 'x\n  zod: ' + ' ' * 200_000 + "x'y\n"


def made_up(versions, **changes):
    """The real versions on Node 26 and pnpm 12.14.0 with SCHEDULE, and the changes."""
    return {**versions, 'node': '26', 'pnpm': '12.14.0', 'node_lines': SCHEDULE, **changes}


def state_of(tmp, versions):
    return node_std.verdict(node_std.places(tmp, scaffold_project.project_files(tmp)), versions, DAY)[0]


def check_states(versions):
    """Each line's state, the places a project names its Node in, the dates of the standard's own check."""
    fails = []
    for files, want in STATES:
        with tempfile.TemporaryDirectory() as tmp:
            put(tmp, files)
            if state_of(tmp, versions) != want:
                fails.append('node_std: %s gives %s, not %s' % (sorted(files), state_of(tmp, versions), want))
    with tempfile.TemporaryDirectory() as tmp:  # a CI folder that is a link may lead out of the project
        put(tmp, {'p/.nvmrc': '26\n', 'out/workflows/ci.yml': SETUP_NODE % '18', 'out/config.yml': 'image: node:18\n'})
        os.symlink(os.path.join(tmp, 'out'), os.path.join(tmp, 'p', '.github'))
        os.symlink(os.path.join(tmp, 'out'), os.path.join(tmp, 'p', '.circleci'))
        if state_of(os.path.join(tmp, 'p'), versions) != 'standard':
            fails.append('node_std: a CI folder that is a link is read')
    with tempfile.TemporaryDirectory() as tmp:  # a place not read (a link) may hold any Node: never the standard
        put(tmp, {'a/package.json': '{}', 'b/.nvmrc': '26\n', 'c/Dockerfile': 'FROM node:26\n'})
        os.symlink(os.path.join(tmp, 'c', 'Dockerfile'), os.path.join(tmp, 'a', '.nvmrc'))
        os.symlink(os.path.join(tmp, 'c', 'Dockerfile'), os.path.join(tmp, 'b', 'Dockerfile'))
        got = [state_of(os.path.join(tmp, p), versions) for p in 'ab']
        if got != ['unknown', 'unknown']:
            fails.append('node_std: a .nvmrc and a Dockerfile that are links give %s, not unknown' % got)
    due = [node_std.due_line(versions, datetime.date(2027, 11, d)) for d in (2, 3)]
    if due != [None, 27]:
        fails.append('node_std: Node 27 is due on 2027-11-02 and 2027-11-03 as %s, not [None, 27]' % due)
    if node_std.checked_days({'_checked': '2026-10-01'}, DAY) != 38 or node_std.checked_days({}, DAY) is not None:
        fails.append('node_std: the days since versions.json was checked are miscounted')
    return fails


def check_node_gaps(versions, made, plain):
    """No Node line for a project of the standard; each for a project that breaks it; no text of the project."""
    fails = []
    for (kind, db), files in plain.items():
        with tempfile.TemporaryDirectory() as tmp:
            put(tmp, files)
            lines = node_std.gaps(tmp, versions, scaffold_project.project_files(tmp), DAY)
            fails += ['node_std: the standard %s+%s has a gap: %s' % (kind, db, g) for g in lines]
    with tempfile.TemporaryDirectory() as tmp:
        put(tmp, BROKEN)
        lines = node_std.gaps(tmp, made, scaffold_project.project_files(tmp), DAY)
        fails += ['node_std: nothing says %s: %s' % (want, lines) for want in BROKEN_LINES
                  if not any(want in g for g in lines)]
        fails += ['node_std: a package read wrong: %s' % g for g in lines if 'vite' in g or 'typescript' in g]
    for pkg, want in ENGINES:
        with tempfile.TemporaryDirectory() as tmp:
            put(tmp, {'package.json': pkg, '.nvmrc': '26\n'})
            lines = node_std.gaps(tmp, made, [], DAY)
            if (want is None) != (lines == []) or want and not any(want in g for g in lines):
                fails.append('node_std: engines %s gives %s' % (pkg, lines))
    with tempfile.TemporaryDirectory() as tmp:
        put(tmp, {'package.json': '{"engines": {"node": ">=26"}}', '.nvmrc': '22\n'})
        if node_std.gaps(tmp, made, [], DAY) != [
                'підтримка Node 22 закінчується 2027-04-30, менше ніж за 6 місяців: порядок оновлення у файлі '
                '`upgrade.md` скіла']:
            fails.append('node_std: the line of an end of life within 6 months: %s' % node_std.gaps(tmp, made, [], DAY))
        put(tmp, {'.nvmrc': INJECTED + ' 24\n', 'a b/Dockerfile': 'FROM node:20 AS %s\n' % INJECTED.replace(' ', '_')})
        said = ' '.join(node_std.gaps(tmp, made, scaffold_project.project_files(tmp), DAY)
                        + node_std.inventory(tmp, made, DAY)
                        + [node_std.where(node_std.places(tmp, ['a b/Dockerfile']))])
        if 'IGNORE' in said or '`Dockerfile` (20)' not in said:
            fails.append('node_std: a text of the project is quoted, or the Dockerfile is not named: %s' % said)
    return fails


def check_reports(made):
    """The flags of project-doctor, the stack lines of doctor (a link and a worktree copy aside, a name unfit to quote
    as ?), the inventory of upgrade.md."""
    fails = []
    for files, want in FLAGS:
        with tempfile.TemporaryDirectory() as tmp:
            put(tmp, files)
            got = node_std.flags(tmp, made, DAY)
            if got != want:
                fails.append('node_std: flags of %s are %s, not %s' % (sorted(files), got, want))
    with tempfile.TemporaryDirectory() as tmp:
        for name, nvmrc in (('a', '24'), ('b', '20'), ('c', '26'), ('copy', '20'), (INJECTED, '22'), ('none', '')):
            put(tmp, {name + '/package.json': '{"name": "x"}', name + '/.nvmrc': nvmrc + '\n'})
        put(tmp, {'copy/.git': 'gitdir: /x/.git/worktrees/copy\n', 'plain/README.md': '', 'empty/package.json': '',
                  'empty/.nvmrc': '20\n'})
        os.symlink(os.path.join(tmp, 'b'), os.path.join(tmp, 'link'))
        fresh = node_std.doctor(tmp, made_up(made, _checked='2026-11-01'), DAY)
        old = node_std.doctor(tmp, made_up(made, _checked='2026-10-01', node_lines=dict(
            SCHEDULE, **{'27': {'lts': '2026-10-01', 'end': '2030-04-30'}})), DAY)
    want = ['  stack: Node standard 26 (end of life 2029-04-30), versions.json checked 2026-11-01 (7 days ago); 5 '
            'folders with package.json: on the standard 1, newer 0, behind 1, end of life within 6 months or past 2, '
            'no Node pinned 1, not read 0', '  WARN: stack: Node out of support or within 6 months of it in 2 '
            'projects: ? (22), b (20)', '  WARN: stack: Node behind the standard in 1 projects: a (24)',
            '  WARN: stack: no Node pinned in 1 projects: none']
    if fresh[:4] != want or len(fresh) != 5:
        fails.append('node_std: doctor gives %s' % fresh)
    if not (len(old) == 7 and 'over 35 days' in old[5] and 'Node 27 has been an LTS line since 2026-10-01, 14 '
            'days or more' in old[6]):
        fails.append('node_std: doctor misses an old versions.json or a due line: %s' % old[4:])
    with tempfile.TemporaryDirectory() as tmp:  # 35 days is no WARN, 36 is
        warns = [len(node_std.doctor(tmp, made_up(made, _checked=c), DAY)) for c in ('2026-10-04', '2026-10-03')]
        if warns != [1, 2]:
            fails.append('node_std: versions.json checked 35 and 36 days ago gives %s lines, not [1, 2]' % warns)
    fails += check_failing(made)
    with tempfile.TemporaryDirectory() as tmp:
        put(tmp, {'package.json': '{"packageManager": "pnpm@12.9.1"}', '.nvmrc': '24\n',
                  'Dockerfile': 'FROM node:24\n'})
        lines = node_std.inventory(tmp, made, DAY)
        want = ['project: behind, oldest Node 24 (end of life 2028-04-30)', 'places: .nvmrc 24, Dockerfile 24']
        if lines[1:3] != want or lines[4] != 'package manager: pnpm 12.9.1':
            fails.append('node_std: the inventory is %s' % lines)
    return fails


def check_failing(made):
    """A folder doctor can't read (an OSError) or that takes too long counts as not read and is named; the rest
    go on."""
    fails, places, budget = [], node_std.places, node_std.PROJECT_BUDGET_S

    def odd(target, files):
        if target.endswith('boom'):
            raise OSError('made up')
        if target.endswith('slow'):
            time.sleep(2)
        return places(target, files)
    with tempfile.TemporaryDirectory() as tmp:
        for name in ('boom', 'fine', 'slow'):
            put(tmp, {name + '/package.json': '{"name": "x"}', name + '/.nvmrc': '26\n'})
        node_std.places, node_std.PROJECT_BUDGET_S = odd, 0.3
        try:
            lines = node_std.doctor(tmp, made, DAY)
        finally:
            node_std.places, node_std.PROJECT_BUDGET_S = places, budget
    if not (lines[0].endswith('on the standard 1, newer 0, behind 0, end of life within 6 months or past 0, no Node '
                              'pinned 0, not read 2') and lines[1] == '  WARN: stack: Node not read in 2 projects: '
                              'boom, slow' and len(lines) == 3):
        fails.append('node_std: doctor with a failing and a slow folder gives %s' % lines)
    return fails


def check_blank(made):
    """Files of blank lines (Dockerfile, Compose, CI, the pnpm catalog, long package.json values) within the budget."""
    with tempfile.TemporaryDirectory() as tmp:
        put(tmp, {'Dockerfile': 'FROM node:22\n' + BLANK, 'compose.yaml': 'services:\n' + BLANK,
                  'deploy/stack.yml': 'services:\n' + BLANK, '.github/workflows/ci.yml': 'jobs:\n' + BLANK,
                  'pnpm-workspace.yaml': CATALOG_SPACES, '.nvmrc': '22\n',
                  'package.json': json.dumps({'engines': {'node': ' ' * 200_000},
                                              'dependencies': {'react': '^' + ' ' * 200_000}})})
        files, t0 = scaffold_project.project_files(tmp), time.monotonic()
        try:
            for fn, args in ((node_std.places, (tmp, files)), (node_std.flags, (tmp, made, DAY)),
                             (node_std.inventory, (tmp, made, DAY)), (node_std.gaps, (tmp, made, files, DAY))):
                node_std.within_budget(fn, *args)
        except node_std.TimeLimit:
            return ['node_std: files of blank lines take over %d s' % node_std.PROJECT_BUDGET_S]
    return [] if time.monotonic() - t0 < 5 else ['node_std: files of blank lines take %.1f s' % (time.monotonic() - t0)]


def check_node(versions, plain):
    made = made_up(versions)
    return check_states(made) + check_node_gaps(versions, made, plain) + check_reports(made) + check_blank(made)
