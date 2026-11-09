"""The Node standard of the base against a project (owner's decisions 03.11.2026). Where a project names its Node:
`.nvmrc`, the node images of its Dockerfiles and Compose files, its CI. The oldest of them decides its state by the
schedule of versions.json (`node_lines`): the standard, newer, behind, end of life within SOON_DAYS or past it. And when
the standard itself is due: versions.json checked over CHECKED_MAX_DAYS ago, or a newer LTS line LTS_WAIT_DAYS old.
One source for the adoption's gap lines, the hook node-std, the inventory upgrade.md starts with, the flags of
scripts/project-doctor.sh and the stack lines of scripts/doctor.sh. The repository is untrusted and these lines reach
the model: only numbers, dates, the standard's own package names and path labels (scaffold_gaps.label) are printed.
  python3 -I node_std.py <folder>                 the inventory of one project
  python3 -I node_std.py --flags <folder>         the flags of project-doctor (flags()), comma-separated, maybe none
  python3 -I node_std.py --doctor <projects dir>  the stack line and its WARNs
  --today YYYY-MM-DD (tests) instead of the date of today. Exit 1 with one line on stderr when it can't answer.
"""
import argparse
import datetime
import os
import re
import signal
import sys

sys.dont_write_bytecode = True  # no __pycache__ in the installed skill folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I leaves the script's folder off sys.path

import scaffold_gaps  # noqa: E402
import scaffold_project  # noqa: E402
import scaffold_render  # noqa: E402

SOON_DAYS = 183        # end of life within about 6 months: the upgrade is urgent
LTS_WAIT_DAYS = 14     # a new LTS line becomes due two weeks after its LTS start, as a package version does
CHECKED_MAX_DAYS = 35  # versions.json checked longer ago: a base release of versions is due
NAMES_MAX = 8          # projects one doctor line names
PROJECT_BUDGET_S = 10  # one folder: doctor counts a slower one as not read and goes on, --flags and the inventory stop
STANDARD, AHEAD, BEHIND, SOON, EOL, UNPINNED, UNKNOWN = ('standard', 'newer', 'behind', 'soon', 'eol', 'unpinned',
                                                         'unknown')
URGENT = (SOON, EOL)
NODE_IMAGE = re.compile(r'(?:^|/)node:(\d{1,3})(?!\d)', re.I)  # node:24, node:24.11-alpine, cimg/node:20.11
# `[ \t]`, never `\s`, inside a line: under re.M `^\s*` runs on over blank lines, so a file of them costs O(n²);
# never two quantifiers of the same spaces side by side (`[ \t]*-?[ \t]*` on one long line of spaces is O(n²) too)
ARG_LINE = re.compile(r'^[ \t]*ARG[ \t]+(\w+)[ \t]*=[ \t]*["\']?([\w.:/@-]*)', re.M | re.I)
VARIABLE = re.compile(r'\$\{(\w+)(?::?-([\w.-]*))?\}|\$(\w+)')
IMAGE_LINE = re.compile(r'^[ \t]*(?:-[ \t]*)?(?:image|container|name)[ \t]*:[ \t]*["\']?([^\s"\'#]+)', re.M)
CI_VERSION = re.compile(r'^[ \t]*(?:-[ \t]*)?node-version[ \t]*:[ \t]*([^#\n]*)', re.M)
CI_NUMBER = re.compile(r'(?<![\w.$])(\d{1,3})(?:\.(?:\d{1,4}|x|\*))*(?![\w.])')
CI_FILES = ('.gitlab-ci.yml', 'bitbucket-pipelines.yml', '.circleci/config.yml')
CI_FOLDER = '.github/workflows'
CI_MAX = 50  # CI files read; the rest are cut without a trace (a known limit of v2026.11.19)
SPEC_MAJOR = re.compile(r'\s*(?:(?:[\^~]|>=?|=)\s*)?v?(\d{1,4})(?!\w)')
ENGINES_MIN = re.compile(r'\s*(?:(?:>=?|\^|~)\s*)?v?(\d{1,3})(?!\d)')
PNPM_VERSION = re.compile(r'pnpm@(\d{1,4})\.(\d{1,4})\.(\d{1,4})(?![\w.])', re.A)


class TimeLimit(Exception):
    """PROJECT_BUDGET_S ran out for one folder."""


def on_alarm(*_):
    raise TimeLimit('over %d s' % PROJECT_BUDGET_S)


def within_budget(fn, *args):
    """fn(*args) with PROJECT_BUDGET_S on the clock, for doctor and the commands of main: the hook keeps its own."""
    signal.signal(signal.SIGALRM, on_alarm)
    signal.setitimer(signal.ITIMER_REAL, PROJECT_BUDGET_S)
    try:
        return fn(*args)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def day(text):
    """A date of versions.json, None for anything else."""
    try:
        return datetime.date.fromisoformat(text) if isinstance(text, str) else None
    except ValueError:
        return None


def schedule(versions):
    """{major: (LTS start, end of life)} of node_lines, None for a date that is missing or bad."""
    lines = versions.get('node_lines')
    return {int(major): (day(line.get('lts')), day(line.get('end')))
            for major, line in (lines.items() if isinstance(lines, dict) else ())
            if str(major).isdigit() and isinstance(line, dict)}


def line_state(major, versions, today):
    """(state, end of life) of a Node major: a line the schedule lacks is an odd one (21, 23, 25) or older than it,
    out of support either way."""
    std = int(versions['node'])
    end = schedule(versions).get(major, (None, None))[1]
    if major >= std:
        return (STANDARD if major == std else AHEAD), end
    if end is None or end < today:
        return EOL, end
    return (SOON if (end - today).days < SOON_DAYS else BEHIND), end


def due_line(versions, today):
    """The newest line after the standard's whose LTS started LTS_WAIT_DAYS ago or earlier; None while there is none."""
    std = int(versions['node'])
    return max((major for major, (lts, _) in schedule(versions).items()
                if major > std and lts is not None and lts + datetime.timedelta(days=LTS_WAIT_DAYS) <= today),
               default=None)


def checked_days(versions, today):
    """Days since versions.json was checked, None when `_checked` holds no date."""
    checked = day(versions.get('_checked'))
    return None if checked is None else (today - checked).days


def image_majors(text):
    """The Node majors of the node images a Dockerfile builds on; an ARG default stands in for its variable."""
    args = dict(ARG_LINE.findall(text))

    def value(m):
        return args.get(m.group(1) or m.group(3)) or m.group(2) or ''
    images = [VARIABLE.sub(value, image) for image, _ in scaffold_project.stages(text)]
    return [int(m.group(1)) for m in map(NODE_IMAGE.search, images) if m]


def yaml_majors(text):
    """The Node majors of the node images of a Compose file or a CI config."""
    return [int(m.group(1)) for m in map(NODE_IMAGE.search, IMAGE_LINE.findall(text)) if m]


def ci_majors(text):
    """The node-version values of a CI config and its node images. A list of them (a matrix) counts by its newest: a
    project that tests an older Node on purpose doesn't run on it. node-version-file follows .nvmrc, a variable or
    lts/* names no major."""
    values = [[int(n) for n in CI_NUMBER.findall(value)] for value in CI_VERSION.findall(text)]
    return [max(majors) for majors in values if majors] + yaml_majors(text)


def ci_files(target):
    """The CI configs of GitHub, GitLab, Bitbucket and CircleCI: scaffold_project skips their folders. A folder that
    is a link may lead out of the project, so it is not read."""
    rels = [rel for rel in CI_FILES if os.path.lexists(os.path.join(target, rel))
            and not os.path.islink(os.path.join(target, os.path.dirname(rel) or '.'))]
    folder = os.path.join(target, CI_FOLDER)
    if os.path.islink(os.path.dirname(folder)) or os.path.islink(folder):
        return rels
    try:
        with os.scandir(folder) as entries:
            rels += sorted(os.path.join(CI_FOLDER, e.name) for e in entries if e.name.endswith(('.yml', '.yaml')))
    except OSError:  # no workflows
        pass
    return rels[:CI_MAX]


def places(target, files):
    """[(place, path, major)] where the project names its Node: `.nvmrc`, Docker (node images of Dockerfiles and
    Compose files), CI. Major None: a .nvmrc with no plain version (lts/*) or a file not read (a link): any Node may
    stand there. A node image or CI version that names no major (node:lts, a variable) is no place."""
    found = []
    if os.path.lexists(os.path.join(target, '.nvmrc')):
        text = scaffold_gaps.read(target, '.nvmrc')
        m = scaffold_gaps.NODE_VERSION.fullmatch((text or '').strip())
        if text is None or text.strip():
            found.append(('.nvmrc', '.nvmrc', int(m.group(1)) if m else None))
    readers = (('Docker', scaffold_gaps.dockerfiles(target, files), image_majors),
               ('Docker', scaffold_gaps.compose_files(target, files), yaml_majors),
               ('CI', ci_files(target), ci_majors))
    for place, rels, majors in readers:
        for rel in rels:
            text = scaffold_gaps.read(target, rel)
            found += [(place, rel, None)] if text is None else [(place, rel, n) for n in sorted(set(majors(text)))]
    return found


def verdict(found, versions, today):
    """(state, the oldest Node major, its end of life): the oldest place decides. A place with no major leaves the
    standard unproven, so unknown; an older Node than the standard stays a fact whatever that place holds."""
    majors = [major for _, _, major in found if major is not None]
    if not majors:
        return (UNKNOWN if found else UNPINNED), None, None
    oldest = min(majors)
    state, end = line_state(oldest, versions, today)
    return (UNKNOWN if state in (STANDARD, AHEAD) and len(majors) < len(found) else state), oldest, end


def where(found):
    """`.nvmrc 24, Docker 24, CI 18 and 20`: each place with its majors, the text of no file."""
    by_place = {}
    for place, _, major in found:
        if major is not None:
            by_place.setdefault(place, set()).add(major)
    return ', '.join('%s %s' % (place, ' and '.join(map(str, sorted(majors)))) for place, majors in by_place.items())


def listed(items, limit=scaffold_gaps.EXAMPLES):
    """Up to limit items and how many stayed out."""
    more = len(items) - limit
    return ', '.join(items[:limit]) + (' (+%d)' % more if more > 0 else '')


def engines_min(pkg):
    """The lowest Node major engines.node lets in, None for none or a form this doesn't read (`||`, `<`, a word)."""
    value = scaffold_gaps.section(pkg, 'engines').get('node')
    m = ENGINES_MIN.match(value) if isinstance(value, str) and '||' not in value else None
    return int(m.group(1)) if m else None


def spec_major(spec):
    """The highest of the first majors of a range's `||` parts (`^4.2 || ^5` is 5, `>=4 <6` is 4), None for a form
    this doesn't read (a tag, a link, a path)."""
    majors = [SPEC_MAJOR.match(part) for part in str(spec).split('||')]
    return max(int(m.group(1)) for m in majors) if all(majors) else None


def packages_behind(target, files, versions):
    """{name: major} of the standard's packages that the project has on an older major, the oldest of its package.json
    files and catalog entries; the names are the standard's own."""
    catalog = {}
    for name, spec in scaffold_gaps.catalog_of(target):
        catalog.setdefault(name, []).append(spec)
    behind = {}
    for name, spec in scaffold_gaps.dependencies(target, files):
        want = versions['packages'].get(name)
        specs = catalog.get(name, []) if str(spec).startswith('catalog:') else [spec]
        majors = [m for m in map(spec_major, specs) if m is not None]
        if want and majors and min(majors) < int(want.split('.')[0]):
            behind[name] = min(min(majors), behind.get(name, min(majors)))
    return behind


def manager_state(target, pkg, versions):
    """(manager, its exact pnpm version or None, behind the standard): any manager but pnpm, or a pnpm older than
    the standard's."""
    name = scaffold_gaps.manager(target, pkg)
    m = PNPM_VERSION.match(str(pkg.get('packageManager', ''))) if name == 'pnpm' else None
    have = tuple(int(n) for n in m.groups()) if m else None
    want = tuple(int(n) for n in versions['pnpm'].split('.'))
    return name, have, name != 'pnpm' or (have is not None and have < want)


def gaps(target, versions, files, today):
    """The Node lines of the adoption report beside scaffold_gaps' `.nvmrc` line: node images and CI on another major,
    engines.node, the support of the oldest line, packages on older majors. A project of the standard has none."""
    pkg = scaffold_gaps.package_of(target)
    if not pkg:  # no package.json, or one that can't be parsed: scaffold_gaps says so
        return []
    std, found, lines = int(versions['node']), places(target, files), []
    for place, what in (('Docker', 'образи Docker'), ('CI', 'CI')):
        other = ['`%s` (%d)' % (scaffold_gaps.label(rel), m) for p, rel, m in found
                 if p == place and m is not None and m != std]
        if other:
            lines.append('%s не на Node %d: %s' % (what, std, listed(other)))
    if 'node' not in scaffold_gaps.section(pkg, 'engines'):
        lines.append('немає `engines.node`: стандарт `>=%d`' % std)
    elif engines_min(pkg) != std:
        low = engines_min(pkg)
        lines.append('`engines.node` %s, стандарт `>=%d`' % ('від Node %d' % low if low else 'іншої форми', std))
    state, oldest, end = verdict(found, versions, today)
    if state == EOL:
        lines.append('Node %d без підтримки%s: оновлення термінове, порядок у файлі `upgrade.md` скіла'
                     % (oldest, ' з ' + end.isoformat() if end else ''))
    elif state == SOON:
        lines.append('підтримка Node %d закінчується %s, менше ніж за 6 місяців: порядок оновлення у файлі '
                     '`upgrade.md` скіла' % (oldest, end.isoformat()))
    behind = packages_behind(target, files, versions)
    if behind:
        lines.append('пакети старіших мажорних версій, ніж у стандарті: %s' % listed(
            ['%s %d (стандарт %s)' % (n, behind[n], versions['packages'][n].split('.')[0]) for n in sorted(behind)]))
    return lines


def flags(target, versions, today):
    """The flags of scripts/project-doctor.sh: NODE-EOL (out of support or within SOON_DAYS of it), NODE<STD,
    NODE-UNPINNED, NODE-UNKNOWN (a place not read or with no plain version), PM!=STD, PNPM<STD; none for a folder
    whose package.json is missing or holds no JSON object."""
    pkg = scaffold_gaps.package_of(target)
    if not pkg:
        return []
    state, oldest, _ = verdict(places(target, scaffold_project.project_files(target)), versions, today)
    found = []
    if state in URGENT:
        found.append('NODE-EOL:%d' % oldest)
    elif state == BEHIND:
        found.append('NODE<STD:%d<%s' % (oldest, versions['node']))
    elif state in (UNPINNED, UNKNOWN):
        found.append('NODE-' + state.upper())
    name, have, behind = manager_state(target, pkg, versions)
    if name != 'pnpm':
        found.append('PM!=STD:%s' % name)
    elif behind:
        found.append('PNPM<STD:%s<%s' % ('.'.join(map(str, have)), versions['pnpm']))
    return found


def inventory(target, versions, today):
    """The lines upgrade.md starts with: the standard, the state of the project, each place of its Node, engines.node,
    the package manager and the packages on older majors."""
    pkg = scaffold_gaps.package_of(target)
    if not pkg:
        return ['no package.json with a JSON object in the root: the Node standard does not apply']
    files = scaffold_project.project_files(target)
    found = places(target, files)
    state, oldest, end = verdict(found, versions, today)
    name, have, _ = manager_state(target, pkg, versions)
    low, behind = engines_min(pkg), packages_behind(target, files, versions)
    return ['standard: Node %s (end of life %s), pnpm %s; versions.json checked %s' % (
                versions['node'], line_state(int(versions['node']), versions, today)[1], versions['pnpm'],
                versions.get('_checked')),
            'project: %s%s' % (state, '' if oldest is None else ', oldest Node %d (end of life %s)' % (
                oldest, end or 'unknown, not an LTS line of the schedule')),
            'places: ' + (listed(['%s %s' % (scaffold_gaps.label(rel),
                                             'not read or no plain version' if m is None else m)
                                  for _, rel, m in found]) or 'none'),
            'engines.node: ' + ('none' if 'node' not in scaffold_gaps.section(pkg, 'engines')
                                else 'from Node %d' % low if low else 'a form this does not read'),
            'package manager: %s%s' % (name, ' ' + '.'.join(map(str, have)) if have else ''),
            'packages on older majors: ' + (listed(['%s %d (standard %s)' % (
                n, behind[n], versions['packages'][n]) for n in sorted(behind)]) or 'none')]


def project_folders(projects):
    """Folders of projects with a package.json that holds a JSON object, by name; a link and a worktree copy (a .git
    file) aside."""
    with os.scandir(projects) as entries:
        folders = sorted((e for e in entries if e.is_dir(follow_symlinks=False)), key=lambda e: e.name)
    return [e for e in folders if not os.path.isfile(os.path.join(e.path, '.git')) and scaffold_gaps.package_of(e.path)]


def judged(path, versions, today):
    """(state, oldest major) of one folder of doctor's; unknown when it can't be read: git failed or timed out, a tree
    too deep, PROJECT_BUDGET_S gone. doctor names such folders, so none of it is silent."""
    try:
        return within_budget(lambda: verdict(places(path, scaffold_project.project_files(path)), versions, today)[:2])
    except (scaffold_render.ScaffoldError, OSError, RecursionError, ValueError, TimeLimit):
        return UNKNOWN, None


def warned(what, names):
    """A WARN line naming up to NAMES_MAX projects, none for none."""
    return ['  WARN: stack: %s in %d projects: %s' % (what, len(names), listed(names, NAMES_MAX))] if names else []


def doctor(projects, versions, today):
    """The stack line of scripts/doctor.sh with counts, then WARNs: projects out of support or within SOON_DAYS of it,
    behind, with no Node pinned (the hook speaks to each), not read; versions.json checked over CHECKED_MAX_DAYS ago, a
    newer LTS line due as the standard."""
    counts = dict.fromkeys((STANDARD, AHEAD, BEHIND, SOON, EOL, UNPINNED, UNKNOWN), 0)
    named = {URGENT: [], BEHIND: [], UNPINNED: [], UNKNOWN: []}
    for entry in project_folders(projects):
        state, oldest = judged(entry.path, versions, today)
        counts[state] += 1
        group = URGENT if state in URGENT else state
        name = (scaffold_gaps.safe_words([entry.name]) or ['?'])[0]
        if group in named:
            named[group].append(name if oldest is None else '%s (%d)' % (name, oldest))
    std, days = int(versions['node']), checked_days(versions, today)
    checked = '%s (%d days ago)' % (versions['_checked'], days) if days is not None else 'with no date'
    out = ['  stack: Node standard %d (end of life %s), versions.json checked %s; %d folders with package.json: on '
           'the standard %d, newer %d, behind %d, end of life within 6 months or past %d, no Node pinned %d, not read '
           '%d' % (std, line_state(std, versions, today)[1], checked, sum(counts.values()), counts[STANDARD],
                   counts[AHEAD], counts[BEHIND], counts[SOON] + counts[EOL], counts[UNPINNED], counts[UNKNOWN])]
    out += warned('Node out of support or within 6 months of it', named[URGENT]) \
        + warned('Node behind the standard', named[BEHIND]) + warned('no Node pinned', named[UNPINNED])
    if named[URGENT] or named[BEHIND] or named[UNPINNED]:
        out.append('        (the node-std hook proposes the upgrade once, in the next session of each project; the '
                   'order: ~/.claude/skills/new-project/upgrade.md; every flag: bash scripts/project-doctor.sh --all)')
    if named[UNKNOWN]:
        out += warned('Node not read', named[UNKNOWN]) + [
            '        (a file a link or with no access, a .nvmrc with no plain version such as lts/*, git failed or '
            'over %d s; the places: python3 -I ~/.claude/skills/new-project/node_std.py <folder>)' % PROJECT_BUDGET_S]
    if days is None or days > CHECKED_MAX_DAYS:
        out.append('  WARN: stack: versions.json checked %s, over %d days: a base release of the standard\'s versions '
                   'is due, with tests/new-project-test.sh' % (checked, CHECKED_MAX_DAYS))
    due = due_line(versions, today)
    if due is not None:
        out.append('  WARN: stack: Node %d has been an LTS line since %s, %d days or more: the standard (Node %d) is '
                   'due for a base release' % (due, schedule(versions)[due][0], LTS_WAIT_DAYS, std))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog='node_std.py', description='The Node standard of the base against projects.')
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--flags', action='store_true', help='the flags of scripts/project-doctor.sh for one folder')
    mode.add_argument('--doctor', action='store_true', help='the stack lines of doctor.sh for a projects folder')
    ap.add_argument('--today', type=datetime.date.fromisoformat, default=datetime.date.today())
    ap.add_argument('folder')
    a = ap.parse_args(argv)
    try:
        if not os.path.isdir(a.folder):
            raise OSError('not a folder: %s' % a.folder)
        versions = scaffold_render.load_versions()
        lines = (doctor(a.folder, versions, a.today) if a.doctor else
                 [','.join(within_budget(flags, a.folder, versions, a.today))] if a.flags else
                 within_budget(inventory, a.folder, versions, a.today))
    except (scaffold_render.ScaffoldError, OSError, KeyError, ValueError, TypeError, AttributeError, RecursionError,
            TimeLimit) as e:
        print('node_std: %s: %s' % (type(e).__name__, e), file=sys.stderr)
        return 1
    print('\n'.join(lines))
    return 0


if __name__ == '__main__':
    sys.exit(main())
