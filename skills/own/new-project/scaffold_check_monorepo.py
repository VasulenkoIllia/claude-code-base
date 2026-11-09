"""Self-check of the gap report on a project whose files don't stand in its root: a pnpm monorepo that keeps the rules
its own way has only its real gap, each rule still finds a broken file in a package or infra/, a file for local work
stays out of the rules of production, and what git ignores is not the project. Offline, in temp folders.
"""
import json
import os
import tempfile

import scaffold_gaps
import scaffold_project
from scaffold_check_modes import ADOPT_ARGS, INJECTED, commit, git, put, run_quiet, text_of

ROOT = {'name': 'mono', 'packageManager': 'pnpm@12.9.1', 'scripts': {'check': 'x'},
        'devDependencies': {'eslint': '^10.0.0', 'typescript': '6.0.3'}}
API_IMAGE = 'FROM a:1 AS build\nFROM a:1 AS runtime\nUSER node\nFROM runtime AS api\n'
APP_COMPOSE = ('services:\n  api:\n    image: ${API:?}\n    restart: always\n    logging:\n      options:\n'
               '        max-size: 10m\n')
DEV_COMPOSE = 'services:\n  db:\n    image: postgres:18\n    ports:\n      - "127.0.0.1:5432:5432"\n    healthcheck:\n'
WORKSPACE = ('packages:\n  - apps/*\n\nallowBuilds:\n  esbuild: true\n\ncatalog:\n  # why\n  zod: ^4.0.0 # why\n'
             "  '@prisma/client': 7.10.0\ncatalogs:\n  old:\n    react: ^18.0.0\n")
# What stands in the folders of SKIP_DIRS is not the project's
PROJECT = {'package.json': json.dumps(ROOT), 'pnpm-lock.yaml': 'lockfileVersion: 9.0\n', '.nvmrc': '24\n',
           'README.md': '', 'eslint.config.js': '', '.gitignore': '.env\n.env.*\n*.pem\n*.key\n*.sql\n*.dump\n',
           'pnpm-workspace.yaml': WORKSPACE, '.dockerignore': '*\n!apps/\n**/node_modules\n**/.env\n**/.env.*\n',
           'tsconfig.base.json': '{"compilerOptions": {"strict": true}}\n',
           'apps/api/package.json': json.dumps({'dependencies': {'fastify': '^5.0.0', 'zod': 'catalog:',
                                                                 'react': 'catalog:old', '@m/shared': 'workspace:*'}}),
           'apps/api/tsconfig.json': '{"extends": "../../tsconfig.base.json"}\n', 'apps/api/.env.example': 'A=1\n',
           'apps/api/prisma/schema.prisma': '', 'infra/docker/api.Dockerfile': API_IMAGE,
           'infra/docker/web.Dockerfile': 'FROM a:1 AS build\nFROM nginxinc/nginx-unprivileged:1.30\n',
           'infra/compose/app.yml': APP_COMPOSE, 'infra/compose/dev.yml': DEV_COMPOSE + '      test: x\n'}
OLD_PNPM = json.dumps(dict(ROOT, packageManager='pnpm@9.15.0'))
NO_MANAGER = json.dumps({k: v for k, v in ROOT.items() if k != 'packageManager'})
NO_BUILD_LIST = 'packages:\n  - apps/*\n'
NO_DOCKERFILES = {'infra/docker/api.Dockerfile': None, 'infra/docker/web.Dockerfile': None}
BARE_APP = 'services:\n  api:\n    image: a:1\n'
OVERLAY = 'services:\n  api:\n    restart: always\n    logging:\n      options:\n        max-size: 10m\n'
# Changes to PROJECT, None removes a file, and the gap each must give
BROKEN = (
    ({'pnpm-lock.yaml': None}, 'немає `pnpm-lock.yaml`'),
    ({'pnpm-workspace.yaml': 'dangerouslyAllowAllBuilds: true\nallowBuilds:\n  a: true\n'}, 'запускаються при'),
    ({'.npmrc': 'dangerously-allow-all-builds=true\n'}, 'запускаються при'),
    # pnpm 11 and later read no ignore-scripts from .npmrc, so the old standard's line hides nothing
    ({'.npmrc': 'ignore-scripts=true\n', 'pnpm-workspace.yaml': 'dangerouslyAllowAllBuilds: true\n'}, 'запускаються при'),
    ({'pnpm-workspace.yaml': '"dangerouslyAllowAllBuilds": "true"\n'}, 'запускаються при'),
    ({'pnpm-workspace.yaml': '{packages: [apps/*], dangerouslyAllowAllBuilds: true}\n'}, 'запускаються при'),
    ({'package.json': json.dumps(dict(ROOT, pnpm={'dangerouslyAllowAllBuilds': True}))}, 'запускаються при'),
    ({'package.json': OLD_PNPM, 'pnpm-workspace.yaml': NO_BUILD_LIST}, '`packageManager` без pnpm 10+'),
    ({'package.json': OLD_PNPM}, '`packageManager` без pnpm 10+'),  # version 9 doesn't read allowBuilds
    ({'package.json': NO_MANAGER, 'pnpm-workspace.yaml': NO_BUILD_LIST}, '`packageManager` без pnpm 10+'),
    ({'package.json': NO_MANAGER, 'pnpm-lock.yaml': None}, 'немає `pnpm-lock.yaml`'),  # the standard's manager
    ({'apps/api/tsconfig.json': '{"compilerOptions": {"strict": false}}\n'}, '`apps/api/tsconfig.json` без'),
    ({'tsconfig.base.json': '{}\n'}, '`apps/api/tsconfig.json` без'),
    ({'tsconfig.json': '{}\n'}, '`tsconfig.json` без'),
    ({'apps/api/tsconfig.json': '{"extends": ["./a.json", "../../tsconfig.base.json"]}\n', 'apps/api/a.json': '{}'},
     None),
    ({'tsconfig.base.json': None, 'apps/api/tsconfig.json': None}, 'немає `tsconfig.json`'),
    ({'apps/api/.env.example': None}, 'немає `.env.example`'),
    (NO_DOCKERFILES, 'немає `Dockerfile`'),
    ({**NO_DOCKERFILES, 'node_modules/x/Dockerfile': 'FROM a\n'}, 'немає `Dockerfile`'),
    ({**NO_DOCKERFILES, '.claude/worktrees/w/Dockerfile': 'FROM a\n'}, 'немає `Dockerfile`'),
    ({'infra/docker/api.Dockerfile': 'FROM a:1 AS x\nFROM a:1 AS runtime\nUSER root\nFROM runtime\n'},
     '`infra/docker/api.Dockerfile` запускає'),
    ({'infra/docker/web.Dockerfile': 'FROM a:1 AS b\nFROM nginx:1.30\n'}, '`infra/docker/web.Dockerfile` запускає'),
    ({'infra/docker/web.Dockerfile': 'FROM a:1 AS b\nFROM b AS b\n'}, '`infra/docker/web.Dockerfile` запускає'),
    ({'infra/docker/web.Dockerfile': 'FROM a:1 AS b\nFROM reg/rootless-tools/ubuntu:22\n'}, 'web.Dockerfile` запускає'),
    ({'infra/docker/web.Dockerfile': 'FROM a:1\n'}, '`infra/docker/web.Dockerfile` в один етап'),
    ({'docker/Dockerfile-prod': 'FROM a:1\n'}, '`docker/Dockerfile-prod` в один етап'),
    ({'docker/prod.dockerfile': 'FROM a:1\n'}, '`docker/prod.dockerfile` в один етап'),
    ({'Containerfile': 'FROM a:1\n'}, '`Containerfile` в один етап'),
    ({'dev-portal/Dockerfile': 'FROM a:1\n'}, '`dev-portal/Dockerfile` в один етап'),  # a service, not a file for dev
    ({'ci-bot/Dockerfile': 'FROM a:1\n'}, '`ci-bot/Dockerfile` в один етап'),
    ({'infra/docker/Dockerfile.dev': 'FROM a\n'}, '`infra/docker/Dockerfile.dev`: образ без тега'),
    ({'.dockerignore': '*\n!apps/\n'}, '`.dockerignore` без: .env, node_modules'),
    ({'services/b/.dockerignore': 'dist\n'}, '`services/b/.dockerignore` без: .env, node_modules'),
    ({'infra/docker/api.Dockerfile.dockerignore': 'dist\n'},
     '`infra/docker/api.Dockerfile.dockerignore` без: .env, .git, node_modules'),
    ({'.dockerignore': None}, 'немає `.dockerignore` для `infra/docker/api.Dockerfile, infra/docker/web.Dockerfile`'),
    ({'.dockerignore': None, 'infra/docker/api.Dockerfile': None, 'infra/.dockerignore': PROJECT['.dockerignore'],
      'apps/web/Dockerfile': API_IMAGE}, 'немає `.dockerignore` для `apps/web/Dockerfile`'),
    ({'infra/compose/app.yml': BARE_APP}, 'Compose-файли без `restart`'),
    ({'infra/compose/app.yml': BARE_APP}, 'Compose-файли без логів'),
    ({'infra/compose/app.yml': BARE_APP, 'e2e/docker-compose.yml': APP_COMPOSE}, 'Compose-файли без `restart`'),
    ({'infra/compose/dev.yml': 'services:\n  db:\n    image: a\n'}, '`infra/compose/dev.yml`: образ без тега'),
    ({'infra/compose/dev.yml': 'services:\n  db:\n    image: postgres:18\n'}, '`infra/compose/dev.yml`: Postgres без'),
    ({'infra/compose/dev.yml': 'services:\n  db:\n    build: .\n    ports:\n      - "5432:5432"\n'},
     '`infra/compose/dev.yml`: порт БД'),
    ({'infra/compose/app.yml': None, 'infra/compose/dev.yml': None}, 'немає `docker-compose.yml`'),
    ({'infra/compose/app.yml': None, 'infra/compose/dev.yml': None, '.travis.yml': 'services:\n  - postgresql\n'},
     'немає `docker-compose.yml`'),
    ({'infra/compose/app.yml': None, 'infra/compose/dev.yml': None, '.gitlab-ci.yml': BARE_APP},
     'немає `docker-compose.yml`'),
    ({'infra/compose/app.yml': None, 'infra/compose/dev.yml': None, 'config/services.yaml': 'services:\n  a: b\n'},
     'немає `docker-compose.yml`'),
    ({'eslint.config.js': None}, 'немає конфігурації ESLint'),
    ({'apps/api/package.json': '{"name": '}, 'не перевірено: apps/api/package.json'))
# Changes that keep the rules: no gap but the versions'
CLEAN = ({'package.json': OLD_PNPM, 'pnpm-workspace.yaml': 'onlyBuiltDependencies:\n  - a\n'},
         {'package.json': json.dumps(dict(ROOT, packageManager='pnpm@9.15.0', pnpm={'onlyBuiltDependencies': ['a']})),
          'pnpm-workspace.yaml': NO_BUILD_LIST},
         {'package.json': NO_MANAGER},
         {'package.json': json.dumps(dict(ROOT, packageManager='pnpm@10.0.0')), 'pnpm-workspace.yaml': NO_BUILD_LIST},
         {**NO_DOCKERFILES, 'infra/docker/Dockerfile.api': API_IMAGE},
         {'infra/docker/Dockerfile.dev': 'FROM a:1\nCMD ["x"]\n'}, {'infra/docker/test.Dockerfile': 'FROM a:1\n'},
         {'infra/docker/Dockerfile.dockerignore': '*\n.env\nnode_modules\n'}, {'docs/Dockerfile.md': 'text\n'},
         {'templates/Dockerfile.tmpl': 'FROM a\n'}, {'src/dockerfile.ts': 'export const a = 1\n'},
         {'tools/parse-dockerfile.js': ''}, {'.gitpod.Dockerfile': 'FROM a:1\n'}, {'.github/x/Dockerfile': 'FROM a\n'},
         {'docker-compose.yml': APP_COMPOSE, 'infra/compose/app.yml': None},
         {'infra/compose/app.yml': None, 'infra/compose/dev.yml': None, 'compose.dev.yml': APP_COMPOSE},
         {'infra/compose/app.prod.yml': 'services:\n  api:\n    environment:\n      A: b\n'},
         {'infra/compose/app.yml': BARE_APP, 'infra/compose/docker-compose.prod.yml': OVERLAY},
         {'infra/compose/app.yml': BARE_APP, 'infra/compose/compose.prod.yaml': OVERLAY},
         {'infra/compose/app.yml': BARE_APP, 'infra/compose/docker-compose-prod.yml': OVERLAY},
         {'infra/compose/app.yml': BARE_APP, 'infra/compose/prod.compose.yaml': OVERLAY},
         {'services/api/.dockerignore': '**/.env\n**/.env.*\n**/node_modules\n'}, {'cypress/tsconfig.json': '{}\n'},
         {'e2e/tsconfig.json': '{"compilerOptions": {"strict": false}}\n'}, {'apps/web/package.json': '{}'},
         {'services/api/.dockerignore': PROJECT['.dockerignore']},
         {'.dockerignore': None, 'infra/docker/.dockerignore': PROJECT['.dockerignore']},
         {'eslint.config.js': None, 'apps/api/eslint.config.mjs': ''},
         {'apps/api/tsconfig.json': '{"files": [], "references": [{"path": "./tsconfig.app.json"}]}\n',
          'apps/api/tsconfig.app.json': '{"extends": "../../tsconfig.base.json"}\n'},
         {'apps/api/tsconfig.json': '{"extends": "@repo/ts/base.json"}\n'})


def gaps_of(changes, versions):
    """The gap lines of PROJECT with changes over it; its .nvmrc holds the standard's Node, so it is no gap."""
    with tempfile.TemporaryDirectory() as tmp:
        project = {**PROJECT, '.nvmrc': versions['node'] + '\n', **changes}
        put(tmp, {rel: text for rel, text in project.items() if text is not None})
        return scaffold_gaps.gaps(tmp, versions)


def check_rules(versions):
    fails = []
    versions_gap = 'пакетів без точної версії: 2 у `package.json`, 2 у каталозі pnpm (eslint, fastify, react, zod)'
    if gaps_of({}, versions) != [versions_gap]:
        fails.append('monorepo: the versions are miscounted: %s' % gaps_of({}, versions))
    for changes in CLEAN:
        lines = gaps_of(changes, versions)
        if [g for g in lines if 'без точної версії' not in g]:
            fails.append('monorepo: a false gap with %s: %s' % (sorted(changes), lines))
    for changes, want in BROKEN:
        lines = gaps_of(changes, versions)
        if want is None and [g for g in lines if 'tsconfig' in g] or want and not any(want in g for g in lines):
            fails.append('monorepo: nothing says %s with %s: %s' % (want, sorted(changes), lines))
    for folder in sorted(scaffold_project.SKIP_DIRS):
        lines = gaps_of({**NO_DOCKERFILES, folder + '/Dockerfile': 'FROM a\n'}, versions)
        if not any('немає `Dockerfile`' in g for g in lines):
            fails.append('monorepo: a Dockerfile in %s/ counts' % folder)
    many = gaps_of({'.dockerignore': None, **{'s%d/Dockerfile' % n: API_IMAGE for n in range(4)}}, versions)
    if not any('s3/Dockerfile, infra/docker/api.Dockerfile (+1)`' in g for g in many):
        fails.append('monorepo: a long list is not cut: %s' % many)
    return fails


def check_versions(versions):
    """Each package.json on its own, each catalog entry whole, none from a quote inside a version, a `catalog:`
    reference to an entry nobody read."""
    fails = []
    disagree = gaps_of({'apps/web/package.json': json.dumps({'devDependencies': {'typescript': '^6.0.0'}})}, versions)
    if not any('3 у `package.json`' in g and 'typescript' in g for g in disagree):
        fails.append('monorepo: a package loses to the root: %s' % disagree)
    flow = gaps_of({'pnpm-workspace.yaml': 'allowBuilds:\n  a: true\ncatalog: { zod: ^4.0.0 }\n'}, versions)
    if not any('пакетів без точної версії: 4 у `package.json` (' in g for g in flow):
        fails.append('monorepo: a reference to an unread entry reads as pinned: %s' % flow)
    entries = scaffold_project.catalog_entries('catalog:\n  a: "1.0.0 || 2.0.0"\n  b: 1.0.0 # c\n  c: \n'
                                               "  e:   x'y\ncatalogs:\n  o:\n    a: '3.0.0'\nother:\n  d: 1\n")
    if entries != [('a', '1.0.0 || 2.0.0'), ('b', '1.0.0'), ('a', '3.0.0')]:
        fails.append('monorepo: the catalog reads as %s' % entries)
    if 'пакетів без точної версії: 1 у каталозі pnpm' not in ' '.join(
            gaps_of({'package.json': json.dumps(dict(ROOT, devDependencies={})), 'apps/api/package.json': '{}',
                     'pnpm-workspace.yaml': 'allowBuilds:\n  a: true\ncatalog:\n  a: "1.0.0 || 2.0.0"\n'}, versions)):
        fails.append('monorepo: a range with spaces reads as exact')
    return fails


def check_files_seen():
    """The look through a project: shallow first, no link followed, a folder it can't enter named, no limit in silence,
    no name quoted that is unfit."""
    fails = []
    with tempfile.TemporaryDirectory() as tmp:
        app = os.path.join(tmp, 'app')
        put(tmp, {'elsewhere/Dockerfile': 'FROM a\n', 'app/a.txt': '', 'app/b/c/d/e/f/g.txt': '', 'app/y/h.txt': '',
                  'app/z.txt': ''})
        os.symlink(os.path.join(tmp, 'elsewhere'), os.path.join(app, 'linked'))
        if scaffold_project.project_files(app) != ['a.txt', 'linked', 'z.txt', 'y/h.txt', 'b/c/d/e/f/g.txt']:
            fails.append('monorepo: the look through the project: %s' % scaffold_project.project_files(app))
        if 'linked' not in ' '.join(scaffold_gaps.unread_gaps(app, scaffold_project.project_files(app))):
            fails.append('monorepo: a link to a folder is not named')
        limit = scaffold_project.MAX_FILES
        scaffold_project.MAX_FILES = 3
        try:
            cut = scaffold_project.project_files(app)
            said = scaffold_gaps.notes(app, None, cut)
        finally:
            scaffold_project.MAX_FILES = limit
        if cut != ['a.txt', 'linked', 'z.txt'] or not any('зупинився на 3 файлах' in n for n in said):
            fails.append('monorepo: the limit: %s, %s' % (cut, said))
        put(app, {'blocked/x.txt': ''})
        os.chmod(os.path.join(app, 'blocked'), 0)
        try:
            unread = scaffold_gaps.unread_gaps(app, scaffold_project.project_files(app))
            if os.geteuid() and 'blocked' not in ' '.join(unread):  # root reads any folder
                fails.append('monorepo: a folder that can\'t be read is not named')
        finally:
            os.chmod(os.path.join(app, 'blocked'), 0o755)
        put(tmp, {'elsewhere/base.json': '{"strict": true}', 'via/tsconfig.json': '{"extends": "./linked/base.json"}'})
        os.symlink(os.path.join(tmp, 'elsewhere'), os.path.join(tmp, 'via/linked'))
        via = os.path.join(tmp, 'via')
        if scaffold_gaps.tsconfig_states(via, scaffold_project.project_files(via)) != {'tsconfig.json': None}:
            fails.append('monorepo: a base read through a linked folder')
        put(tmp, {'links/x.txt': ''})
        for name in ('.dockerignore', '.npmrc'):
            os.symlink(os.path.join(tmp, 'elsewhere/Dockerfile'), os.path.join(tmp, 'links', name))
        unread = ' '.join(scaffold_gaps.unread_gaps(os.path.join(tmp, 'links'), ['.dockerignore', '.npmrc']))
        if '.dockerignore' not in unread or '.npmrc' not in unread:
            fails.append('monorepo: a link in place of a file the rules read is not named: %s' % unread)
        put(tmp, {'yarn/package.json': '{"name": "a"}', 'yarn/yarn.lock': '', 'npm/package.json': '{"name": "a"}',
                  'npm/package-lock.json': '{}'})
        for name in ('yarn', 'npm'):
            if 'менеджер %s, стандарт pnpm' % name not in ' '.join(scaffold_gaps.notes(os.path.join(tmp, name), {}, [])):
                fails.append('monorepo: a lock file of %s is no note' % name)
        put(tmp, {'nested/x/.npmrc': '', 'nested/x/.gitignore': ''})
        os.unlink(os.path.join(tmp, 'nested/x/.npmrc'))
        os.symlink(os.path.join(tmp, 'elsewhere/Dockerfile'), os.path.join(tmp, 'nested/x/.npmrc'))
        nested = os.path.join(tmp, 'nested')
        if scaffold_gaps.unread_gaps(nested, scaffold_project.project_files(nested)):
            fails.append('monorepo: a file no rule reads is named as unread')
    if scaffold_gaps.label('папка з пробілом/ім я') != 'файл':
        fails.append('monorepo: a name unfit to quote: %s' % scaffold_gaps.label('папка з пробілом/ім я'))
    return fails


def check_strict():
    """The chain of extends stops at a value, at what is outside the project, and at a loop."""
    texts = {'a.json': '{"extends": "./b"}', 'b.json': '{ // "strict": false\n "strict": true }',
             'c.json': '{"extends": ["./b.json", "./d.json"]}', 'd.json': '{"strict": false}',
             'e.json': '{"extends": "@repo/base.json"}', 'f.json': '{"extends": "../../outside.json"}',
             'g.json': '{"extends": "./g.json"}', 'h.json': '{}', 'i.json': '{"extends": "./missing.json"}',
             'j.json': '{"extends": ["./b.json", "./h.json"]}', 'k.json': '{"extends": ["./b.json", "@repo/x.json"]}'}
    wanted = {'a.json': True, 'c.json': False, 'e.json': None, 'f.json': None, 'g.json': None, 'h.json': False,
              'i.json': None, 'j.json': True, 'k.json': None}
    got = {rel: scaffold_project.strict_of(rel, texts.get) for rel in wanted}
    return ['monorepo: strict: %s' % got] if got != wanted else []


def check_card(sc):
    """What git ignores is not the project, and the card speaks of the project's manager and of its files in folders;
    with docs/ outside git the STATUS goes there, and a second run keeps it."""
    fails = []
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, 'mono')
        os.makedirs(target)
        git(target, 'init', '-q', '-b', 'main')
        put(target, PROJECT)
        put(target, {'.git/info/exclude': '/_internal/\n/docs/\n', '_internal/legacy/Dockerfile': 'FROM a\n',
                     '_internal/legacy/package.json': '{"dependencies": {"left": "^1.0.0"}}',
                     'apps/api/tsconfig.json': '{"extends": "@repo/ts/base.json"}\n'})
        commit(target)
        commit(target, 'second')
        code, out = run_quiet(sc, [target] + ADOPT_ARGS)
        card = text_of(target, 'CLAUDE.local.md')
        wanted = ('`pnpm run check`', 'Fastify 5', 'React 18', 'Prisma, схема `apps/api/prisma/schema.prisma`',
                  'Postgres у Compose', 'infra/docker/api.Dockerfile, infra/docker/web.Dockerfile, infra/compose/',
                  '- Стан: `docs/STATUS.md`', '- Документи: README.md, docs/decisions.md')
        if code or '`npm run' in card or not all(want in card for want in wanted) \
                or not os.path.isfile(os.path.join(target, 'docs/STATUS-archive.md')):
            fails.append('monorepo: the card: exit %s, %s' % (code, card[:300]))
        report = text_of(target, 'docs/standard-gaps.md')
        if 'менеджер pnpm' in out + report:
            fails.append('monorepo: the standard\'s own manager is a note: %s' % out[:300])
        if 'note: `strict` не перевірено, база поза файлами проєкту: apps/api/tsconfig.json' not in out:
            fails.append('monorepo: a base from a package is not named: %s' % out[:300])
        if '_internal' in out + card or 'left' in out or '1 у `package.json`' in out:
            fails.append('monorepo: a folder git ignores counts: %s' % out[:300])
        put(target, {'apps/web/package.json': '{"dependencies": {"next": "^13.0.0"}}',
                     'apps/old/package.json': '{"dependencies": {"next": "^14.0.0"}}'})
        os.unlink(os.path.join(target, 'CLAUDE.local.md'))
        code, out = run_quiet(sc, [target] + ADOPT_ARGS)
        if code or ', Next,' not in text_of(target, 'CLAUDE.local.md') or 'kept docs/STATUS.md' not in out:
            fails.append('monorepo: the card names one of two majors: %s' % text_of(target, 'CLAUDE.local.md')[:300])
    return fails


def check_unsafe_path(versions):
    unsafe = gaps_of({INJECTED + '/Dockerfile': 'FROM a\n'}, versions)
    if INJECTED in ' '.join(unsafe) or not any('`Dockerfile` в один етап' in g for g in unsafe):
        return ['monorepo: a path unfit to quote: %s' % unsafe]
    return []


def check_monorepo(sc, versions):
    return (check_rules(versions) + check_versions(versions) + check_files_seen() + check_strict() + check_card(sc)
            + check_unsafe_path(versions))
