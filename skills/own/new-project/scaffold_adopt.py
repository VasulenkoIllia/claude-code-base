"""«Прийняти в стандарт» (scaffold.py --adopt): an existing project gets the card with its facts read from the repository,
the docs skeleton, a STATUS with its archive when it has none, and the gap report. No existing file is changed: what is
already there stays and is named in the output.
"""
import datetime
import os
import re

import node_std
import scaffold_gaps
import scaffold_project
import scaffold_render as sr
from scaffold_target import NOT_A_REPO, run_git

CARD = 'CLAUDE.local.md'
# Other files a card may live in; a card there stays the project's card
CARD_FILES = (CARD, 'CLAUDE.md', 'AGENTS.md')
UNKNOWN = 'не визначено, уточнити'
KNOWN_STACK = (('typescript', 'TypeScript'), ('@nestjs/core', 'NestJS'), ('fastify', 'Fastify'), ('express', 'Express'),
               ('next', 'Next'), ('react', 'React'), ('vite', 'Vite'), ('vue', 'Vue'), ('grammy', 'grammY'),
               ('telegraf', 'Telegraf'), ('prisma', 'Prisma'), ('drizzle-orm', 'Drizzle'), ('typeorm', 'TypeORM'))
MAX_COMMANDS = 10
MAX_BRANCHES = 5
MAX_DEPLOY_FILES = 6
# These never fall off the end of a list, and the rule on a develop branch reads the line of the branches
FIRST_COMMANDS = ('check', 'test', 'build', 'dev', 'start')
MAIN_BRANCHES = ('main', 'master', 'develop', 'dev')
DOCS_FROM_COMMON = ('docs/decisions.md', 'docs/integrations.md')
OWN_DOCS = ('docs/deployment.md', 'docs/standard-gaps.md')
# Where a STATUS of the project may stand, in the order scripts/project-doctor.sh looks; the first one found counts
STATUS_PLACES = ('docs/STATUS.md', sr.STATE_DIR + '/STATUS.md', 'STATUS.md')
# The card's «З чого почати»: the project's READMEs, then the docs the adoption keeps or writes
README_FILES = ('README.md', 'docs/README.md')
DOCS_INDEX = sr.DOCS_INDEX + ', docs/standard-gaps.md (розриви зі стандартом)'


def package_major(version):
    """The major of a plain version or range; anything else (a tag, a path, a number of any length) names no version."""
    m = re.match(r'[\^~>=<v\s]*(\d{1,4})(?!\d)', str(version), re.A)
    return ' %s' % m.group(1) if m else ''


def stack_major(name, deps, catalog):
    """The major of a dependency, nothing when packages or catalogs disagree: a card doesn't name one of two."""
    versions = []
    for dep, version in deps:
        if dep == name:
            versions += [v for n, v in catalog if n == name] if str(version).startswith('catalog:') else [version]
    majors = {package_major(version) for version in versions}
    return majors.pop() if len(majors) == 1 else ''


def stack_fact(target, pkg, files):
    """The stack as the repository shows it."""
    if pkg is None:
        python = any(os.path.exists(os.path.join(target, f)) for f in ('pyproject.toml', 'requirements.txt'))
        return 'Python' if python else UNKNOWN
    node = scaffold_gaps.node_major(target)
    deps, catalog = scaffold_gaps.dependencies(target, files), scaffold_gaps.catalog_of(target)
    names = {name for name, _ in deps}
    parts = ['Node %s (`.nvmrc`)' % node if node else 'Node, версія не зафіксована']
    parts += [title + stack_major(name, deps, catalog) for name, title in KNOWN_STACK if name in names]
    return ', '.join(parts)


def some_of(words, first, limit):
    """Up to limit names, those in first ahead of the rest, and a mark of how many stayed out, unfit names among them."""
    safe = scaffold_gaps.safe_words(words)
    listed = ([w for w in first if w in safe] + [w for w in safe if w not in first])[:limit]
    return listed, ' (+%d)' % (len(words) - len(listed)) if len(words) > len(listed) else ''


def commands_fact(target, pkg):
    manager = scaffold_gaps.manager(target, pkg)
    scripts, more = some_of(sorted(scaffold_gaps.section(pkg, 'scripts')), FIRST_COMMANDS, MAX_COMMANDS)
    return (' | '.join('`%s run %s`' % (manager, s) for s in scripts) or UNKNOWN) + more


def data_fact(target, files):
    compose = '\n'.join(scaffold_gaps.read(target, f) or '' for f in scaffold_gaps.compose_files(target, files))
    schema = next((f for f in files if os.path.basename(f) == 'schema.prisma'), None)
    parts = ['Prisma, схема `%s`' % scaffold_gaps.label(schema)] if schema else []
    if re.search(r'^\s+image:\s*\S*(postgres|pgvector)', compose, re.M):
        parts.append('Postgres у Compose')
    return ', '.join(parts) or UNKNOWN


def deploy_fact(target, files):
    found = ['GitHub Actions'] if os.path.exists(os.path.join(target, '.github/workflows')) else []
    paths = scaffold_gaps.dockerfiles(target, files) + scaffold_gaps.compose_files(target, files)
    listed, more = some_of([scaffold_gaps.label(f) for f in paths], (), MAX_DEPLOY_FILES)
    return ', '.join(found + listed) + more or UNKNOWN


def branches_fact(target):
    run = run_git(target, 'for-each-ref', '--format=%(refname:short)', 'refs/heads')
    listed, more = some_of(run.stdout.split() if run.returncode == 0 else [], MAIN_BRANCHES, MAX_BRANCHES)
    return (', '.join('`%s`' % n for n in listed) or UNKNOWN) + more + '.'


def card_exists(target):
    """The file that already holds a card, or None."""
    for name in CARD_FILES:
        if '## Розмір' in (scaffold_gaps.read(target, name) or ''):
            return name
    return None


def has_card_file(target):
    return bool(card_exists(target)) or os.path.lexists(os.path.join(target, CARD))


def status_place(target):
    """(path, True) of the project's STATUS, or (where a new one goes, False) by the global rule: docs/ when git ignores
    it or there is no repository, else .claude/state/, which the owner's global git excludes hide."""
    for rel in STATUS_PLACES:
        if os.path.lexists(os.path.join(target, rel)):
            return rel, True
    # Both files, as a .gitignore line for docs/STATUS.md alone would leave the archive to the next commit
    run = run_git(target, 'check-ignore', *['docs/' + name for name in sr.STATE_FILES])
    hidden = run.returncode == 0 and len(run.stdout.splitlines()) == len(sr.STATE_FILES)
    folder = 'docs' if hidden or NOT_A_REPO in run.stderr else sr.STATE_DIR
    return folder + '/STATUS.md', False


def docs_index(target):
    return ', '.join([rel for rel in README_FILES if os.path.isfile(os.path.join(target, rel))] + [DOCS_INDEX]) + '.'


def kept(target, files):
    """What the project already had of the files the adoption writes; a card file without a card says so. Called after
    the write: a STATUS this run wrote is in files, so status_place finds it and it is not named."""
    rels = [r for r in DOCS_FROM_COMMON + OWN_DOCS + (status_place(target)[0],) if r not in files]
    if CARD in files:
        return rels
    return [card_exists(target) or '%s (no «Розмір» in it: add the card by hand)' % CARD] + rels


def card_gap(target):
    """The card is local. The real git answers, as the owner's global excludes may hide it; no repository, no gap."""
    run = run_git(target, 'check-ignore', '-q', CARD)
    if run.returncode == 1:
        return ['`.gitignore` не ховає локальну картку (`*.local.md`): вона потрапить у коміт']
    return ['не перевірено, чи git ховає локальну картку'] if run.returncode and NOT_A_REPO not in run.stderr else []


def card_values(o, target, versions, pkg, files, status):
    values = {'name': o.name, 'date': o.date, 'tier': o.tier, 'risk': o.risk, 'data': o.data, 'ui': o.ui,
              'numbers': UNKNOWN if o.numbers == sr.DEFAULT_NUMBERS else o.numbers, 'not_add': o.not_add,
              'hatches': o.hatches, 'review_when': o.review_when, 'ui_source': o.ui_source,
              'standard': versions['_checked'], 'stack': stack_fact(target, pkg, files),
              'commands': commands_fact(target, pkg), 'data_fact': data_fact(target, files),
              'deploy': deploy_fact(target, files), 'branches': branches_fact(target), 'type': '', 'modules_text': '',
              'note': '', 'status_file': status, 'docs_index': docs_index(target)}
    values.update(sr.stage_values(o))
    return values


def plan(o, versions):
    """{output path: text} for what the project lacks, the gap lines, and the notes on what was not checked."""
    target, pkg = o.target, scaffold_gaps.package_of(o.target)
    project = scaffold_project.project_files(target)
    gaps = card_gap(target) + scaffold_gaps.gaps(target, versions) \
        + node_std.gaps(target, versions, project, datetime.date.fromisoformat(o.date))
    flags = dict(sr.flags_for('api', 'none'), adopt=True, web=bool(o.ui_source))
    status, has_status = status_place(target)
    values = card_values(o, target, versions, pkg, project, status)
    notes = scaffold_gaps.notes(target, pkg, project)
    values['gaps'] = '\n'.join(['- [ ] ' + line for line in gaps] + ['Примітка: ' + line for line in notes]) \
        or 'За цими правилами розривів немає.'
    common = [(CARD, 'common/CLAUDE.local.md.tmpl')] + [(rel, 'common/%s.tmpl' % rel) for rel in DOCS_FROM_COMMON]
    state = [] if has_status else [('%s/%s' % (os.path.dirname(status), name), 'common/state/%s.tmpl' % name)
                                   for name in sr.STATE_FILES]
    own = [(rel, 'adopt/%s.tmpl' % rel) for rel in OWN_DOCS]
    files = {}
    for rel, template in common + state + own:
        taken = has_card_file(target) if rel == CARD else os.path.lexists(os.path.join(target, rel))
        if not taken:
            files[rel] = sr.render_file(os.path.join(sr.TEMPLATES, template), flags, values, 'templates/' + template)
    return files, gaps, notes
