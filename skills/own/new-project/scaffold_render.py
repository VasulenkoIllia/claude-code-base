"""What each project type of the new-project standard gets, rendered in memory (scaffold.py writes it).

The types and their template layers, package.json from versions.json, the card (CLAUDE.local.md) and plan():
{output path: text} for every file of the project. The card defaults (DEFAULT_*) stay in this file: SKILL.md has the
model read them here for the passport, and the self-check holds it to that.
Templates: templates/<layer>/<path>.tmpl. {{key}} is a value; a line holding only {{#flag}}, {{^flag}} or
{{/flag}} opens (if flag / if not flag) or closes a block.
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(HERE, 'templates')
TYPES = ('api', 'nest', 'fullstack', 'integration', 'bot')
# The catalog of modules: only what a project has already needed, the rest comes when it is needed a second time
MODULE_LAYERS = {'pgvector': 'mod-pgvector', 'budget': 'mod-budget'}
MODULE_NAMES = {'pgvector': 'pgvector у тій самій БД', 'budget': 'ліміт бюджету платних API'}
LAYERS = {'api': ('common', 'http'), 'nest': ('common', 'nest'), 'fullstack': ('common', 'http', 'web'),
          'integration': ('common', 'worker', 'integration'), 'bot': ('common', 'worker', 'bot')}
# HTTP services behind Traefik: PORT, healthcheck and labels in the common layer
HTTP_TYPES = ('api', 'nest', 'fullstack')
DB_LAYER = 'db'
# Layers a type adds on top of DB_LAYER: Nest gets the Prisma client as a module
DB_EXTRA = {'nest': ('nest-db',)}
# Files of an existing project taken into the standard: the card and the rest of the docs come from the common layer
ADOPT_LAYER = 'adopt'
DOTFILES = {'gitignore': '.gitignore', 'dockerignore': '.dockerignore', 'nvmrc': '.nvmrc', 'npmrc': '.npmrc',
            'env.example': '.env.example'}
# STATUS and its archive (templates/<layer>/state/): local, as the owner's global git excludes hide .claude/state/; a
# line for it in .gitignore would name the tool in the first commit
STATE_DIR = '.claude/state'
STATE_FILES = ('STATUS.md', 'STATUS-archive.md')
DOTDIRS = {'state': STATE_DIR}
# The card's «З чого почати»: the docs a created and an adopted project both have
DOCS_INDEX = 'docs/decisions.md (рішення), docs/integrations.md (зовнішні сервіси), docs/deployment.md (сервер)'
MARK_RE = re.compile(r'^\s*\{\{([#^/])(\w+)\}\}\s*$')
VAR_RE = re.compile(r'\{\{(\w+)\}\}')

DEFAULT_TIER = {'api': 'T2', 'nest': 'T2', 'fullstack': 'T2', 'integration': 'T1', 'bot': 'T1'}
DEFAULT_NUMBERS = 'немає, новий проєкт'
DEFAULT_UI_SOURCE = 'чистий React, без UI-кіта'
DEFAULT_STAGE_GOAL = 'не визначено'
DEFAULT_CUSTOM = 'немає'
# The card's stage: ~/.claude/rules/demo-gates.md turns on by the words «Етап: демо»
STAGES = {'demo': 'демо', 'pilot': 'пілот', 'prod': 'прод'}
STAGE_GATES = {'demo': "~/.claude/rules/demo-gates.md замість глобальних правил про рев'ю, тести, перевірки й документи",
               'pilot': 'глобальні правила повністю', 'prod': 'глобальні правила повністю'}
DEFAULT_NOT_ADD = {
    'api': 'Redis, черги, мікросервіси, GraphQL, друга копія застосунку',
    'fullstack': 'SSR чи Next, компоненти поза UI-джерелом, Redis, черги, друга копія застосунку',
    'integration': 'веб-UI, Redis, черги, друга копія застосунку',
    'bot': 'Redis, черги, друга копія застосунку',
}
# «Люки»: the growth paths agreed in advance; only for them Claude may prepare a layer before it is needed
DEFAULT_HATCHES = {
    'api': 'worker через env-прапорець, той самий image',
    'fullstack': 'worker через env-прапорець, той самий image',
    'integration': 'друга задача в тому ж процесі, окремим файлом',
    'bot': 'webhook замість long polling через env, той самий код',
}
# The passport prints the card before the quiz asks Fastify or NestJS, so both frameworks share the API card
DEFAULT_NOT_ADD['nest'] = DEFAULT_NOT_ADD['api']
DEFAULT_HATCHES['nest'] = DEFAULT_HATCHES['api']
DEFAULT_REVIEW_WHEN = 'таблиця понад 100 тис. рядків; друга копія застосунку; оплати; новий тип персональних даних'
NOTES = {
    'api': 'HTTP лише через Traefik, порт назовні не відкритий; /health для healthcheck, помилки 5xx без деталей.',
    'nest': 'HTTP лише через Traefik, порт назовні не відкритий; /health для healthcheck, помилки 5xx без деталей, '
            'HttpException до 500 іде клієнту як є, тому текст чужої помилки в нього не класти (src/errors.filter.ts). '
            'Фічі в `src/<фіча>/` (`pnpm exec nest g module|controller|service <фіча>`, не `resource`: він ставить пакет '
            'без точної версії). DI бере тип з конструктора: клас залежності імпортувати як значення, '
            'не `import type`; dev через `nest start` (tsx не пише метадані декораторів).',
    'fullstack': 'Прод: Fastify віддає зібраний web з dist/web; dev: `pnpm run dev` і `pnpm run dev:web` (Vite проксує /api і /health).',
    'integration': 'Пропущений через зайнятість запуск пишеться в лог; разовий запуск `pnpm run once`.',
    'bot': '401 означає хибний BOT_TOKEN, 409 що з цим токеном уже працює інша копія бота.',
}
BASE_DEV = ('typescript', '@types/node', 'tsx', 'vitest', 'eslint', '@eslint/js', 'typescript-eslint', 'globals')
# The standard's dependencies with an install script, and why none of them needs it: pnpm-workspace.yaml lists each one
# as false, and pnpm stops on any other (strictDepBuilds) until the owner decides
BUILDS_OFF = {
    'esbuild': 'its binary comes from its platform package; the script only checks it',
    'prisma': 'the script only checks the environment',
    '@prisma/engines': 'the migration engine is fetched explicitly: Dockerfile prisma version, locally the CLI',
}
PLAIN_YAML_KEY = re.compile(r'[a-z0-9][\w.-]*')


class ScaffoldError(Exception):
    pass


def load_versions():
    path = os.path.join(HERE, 'versions.json')
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        raise ScaffoldError('versions.json: %s' % e) from e
    if not isinstance(data, dict):
        raise ScaffoldError('versions.json: not a JSON object')
    missing = [k for k in ('_checked', 'node', 'pnpm', 'nest_fastify', 'postgres', 'pgvector_image', 'packages',
                           'overrides') if k not in data]
    if missing:
        raise ScaffoldError('versions.json: no %s' % ', '.join(missing))
    return data


def flags_for(kind, db, brief=False, modules=()):
    layers = LAYERS[kind]
    return {'http': kind in HTTP_TYPES, 'web': 'web' in layers, 'nest': kind == 'nest',
            'integration': kind == 'integration', 'bot': kind == 'bot', 'db': db == 'prisma',
            'required_env': db == 'prisma' or kind == 'bot', 'brief': brief, 'adopt': False,
            'modules': bool(modules), 'pgvector': 'pgvector' in modules, 'budget': 'budget' in modules}


def render(text, flags, values, where):
    out, stack = [], []
    for no, line in enumerate(text.splitlines(keepends=True), 1):
        m = MARK_RE.match(line)
        if m:
            sign, flag = m.groups()
            if flag not in flags:
                raise ScaffoldError('%s:%d: unknown flag %s' % (where, no, flag))
            if sign == '/':
                if not stack or stack[-1][0] != flag:
                    raise ScaffoldError('%s:%d: {{/%s}} closes nothing' % (where, no, flag))
                stack.pop()
            else:
                stack.append((flag, flags[flag] if sign == '#' else not flags[flag]))
            continue
        if all(on for _, on in stack):
            def value(v, no=no):
                if v.group(1) not in values:
                    raise ScaffoldError('%s:%d: unknown value {{%s}}' % (where, no, v.group(1)))
                return values[v.group(1)]
            out.append(VAR_RE.sub(value, line))
    if stack:
        raise ScaffoldError('%s: {{%s}} is never closed' % (where, stack[-1][0]))
    return ''.join(out)


def output_name(rel):
    head, base = os.path.split(rel[:-len('.tmpl')])
    if head:
        return os.path.join(DOTDIRS.get(head, head), base)
    return DOTFILES.get(base, base)


def major(versions, package):
    if package not in versions['packages']:
        raise ScaffoldError('versions.json has no version for: ' + package)
    return versions['packages'][package].split('.')[0]


def package_versions(kind, versions):
    # Nest names fastify at the version its adapter pins: pnpm resolves an import only from package.json, and the
    # same version keeps a single copy, the one the Fastify types describe
    pkgs = versions['packages']
    return dict(pkgs, fastify=versions['nest_fastify']) if kind == 'nest' else pkgs


def package_json(name, kind, db, versions):
    flags, pkgs = flags_for(kind, db), package_versions(kind, versions)
    deps, dev = set(), set(BASE_DEV)
    if flags['http']:
        deps.add('fastify')
    if flags['nest']:
        deps |= {'@nestjs/common', '@nestjs/core', '@nestjs/platform-fastify', 'reflect-metadata', 'rxjs'}
        dev = (dev - {'tsx'}) | {'@nestjs/cli', '@nestjs/schematics', '@nestjs/testing'}
    if flags['web']:
        deps |= {'@fastify/static', 'react', 'react-dom'}
        dev |= {'vite', '@vitejs/plugin-react', '@types/react', '@types/react-dom', 'eslint-plugin-react-hooks'}
    deps |= {'integration': {'croner'}, 'bot': {'grammy'}}.get(kind, set())
    if flags['db']:
        deps |= {'prisma', '@prisma/client', '@prisma/adapter-pg'}
    # No install script of a dependency runs (pnpm-workspace.yaml): the Prisma client is generated explicitly
    generate = 'prisma generate && ' if flags['db'] else ''
    # tsx (esbuild) drops the decorator metadata that Nest's DI reads, so Nest runs through its CLI on tsc. The other
    # types run in Node's own watch mode with tsx as the loader: tsx watch answers the second copy of a Ctrl+C with
    # SIGKILL halfway through closing, while Node's watch mode only passes the signal on
    scripts = {'dev': 'nest start --watch --exec "node --env-file-if-exists=.env"' if flags['nest']
               else 'node --watch --env-file-if-exists=.env --import tsx src/main.ts'}
    if flags['web']:
        scripts['dev:web'] = 'vite'
    if kind == 'integration':
        scripts['once'] = 'tsx --env-file-if-exists=.env src/main.ts --once'
    scripts.update({
        'build': generate + 'tsc -p tsconfig.build.json' + (' && vite build' if flags['web'] else ''),
        'start': 'node --env-file-if-exists=.env dist/main.js',
        'typecheck': generate + 'tsc --noEmit' + (' && tsc --noEmit -p web/tsconfig.json' if flags['web'] else ''),
        'lint': 'eslint .',
        'test': 'vitest run',
        'check': 'pnpm run typecheck && pnpm run lint && pnpm run test && pnpm run build',
    })
    if flags['db']:
        dev_compose = 'docker compose -f docker-compose.dev.yml '
        # db:up returns once Postgres is healthy; db:down keeps the data volume
        scripts.update({'db:generate': 'prisma generate', 'db:up': dev_compose + 'up -d --wait',
                        'db:down': dev_compose + 'down',
                        # Prisma 7 `migrate dev` no longer regenerates the client; it goes last, so pnpm appends
                        # arguments (`pnpm run db:migrate --name add_orders`) to it
                        'db:migrate': 'prisma generate && prisma migrate dev', 'db:deploy': 'prisma migrate deploy'})
    missing = sorted((deps | dev) - set(pkgs))
    if missing:
        raise ScaffoldError('versions.json has no version for: ' + ', '.join(missing))
    # The Dockerfile installs this version, and a pnpm of another version on the Mac runs it too
    data = {'name': name, 'version': '0.1.0', 'private': True, 'type': 'module',
            'packageManager': 'pnpm@%s' % versions['pnpm'],
            'engines': {'node': '>=%s' % versions['node']}, 'scripts': scripts,
            'dependencies': {p: pkgs[p] for p in sorted(deps)},
            'devDependencies': {p: pkgs[p] for p in sorted(dev)}}
    return json.dumps(data, indent=2, ensure_ascii=False) + '\n'


def builds_of(kind, db):
    """The packages of BUILDS_OFF a type installs: tsx brings esbuild (Nest runs on tsc), Prisma the other two."""
    builds = set() if kind == 'nest' else {'esbuild'}
    return sorted(builds | ({'prisma', '@prisma/engines'} if db == 'prisma' else set()))


def yaml_key(name):
    return name if PLAIN_YAML_KEY.fullmatch(name) else "'%s'" % name


def workspace_yaml(kind, db, versions):
    """pnpm-workspace.yaml: pnpm 11 and later read only auth and registry settings from .npmrc, the rest from here."""
    builds = builds_of(kind, db)
    lines = ['# pnpm settings of the project; .npmrc gives pnpm only auth and registry settings.',
             '# An install script of a dependency runs only for a package listed here as true. A new dependency with',
             '# a script stops `pnpm install` (strictDepBuilds) until its line is added, true or false, with the reason.',
             '# dangerouslyAllowAllBuilds stays false here: a true one in the global pnpm config would lift that stop.',
             'strictDepBuilds: true',
             'dangerouslyAllowAllBuilds: false',
             'allowBuilds:' + ('' if builds else ' {}')]
    lines += ['  %s: false  # %s' % (yaml_key(name), BUILDS_OFF[name]) for name in builds]
    overrides = versions['overrides'] if db == 'prisma' else {}
    if overrides:
        lines.append('overrides:')
        lines += ['  %s: %s' % (yaml_key(name), version) for name, version in sorted(overrides.items())]
    return '\n'.join(lines) + '\n'


def card_values(o, versions):
    flags = flags_for(o.type, o.db, modules=o.modules)
    stack = ['TypeScript %s, Node %s (`.nvmrc`)' % (major(versions, 'typescript'), versions['node'])]
    if o.type == 'nest':
        stack.append('NestJS %s на Fastify %s (`@nestjs/platform-fastify`), тести Vitest' % (
            major(versions, '@nestjs/core'), major(versions, 'fastify')))
    elif flags['http']:
        stack.append('Fastify %s' % major(versions, 'fastify'))
    if flags['web']:
        stack.append('React %s + Vite %s (web/)' % (major(versions, 'react'), major(versions, 'vite')))
    if o.type == 'integration':
        stack.append('croner %s (розклад CRON_SCHEDULE)' % major(versions, 'croner'))
    if o.type == 'bot':
        stack.append('grammY %s (long polling)' % major(versions, 'grammy'))
    if flags['db']:
        stack.append('Postgres %s%s + Prisma %s' % (versions['postgres'], ' з pgvector' if flags['pgvector'] else '',
                                                    major(versions, 'prisma')))
    commands = ['`pnpm run check` (typecheck, lint, test, build)', 'dev'] + (['dev:web'] if flags['web'] else []) \
        + (['once'] if o.type == 'integration' else []) \
        + (['db:up', 'db:migrate', 'db:down', 'db:generate', 'db:deploy'] if flags['db'] else [])
    data = ('Postgres %s у Compose, міграції Prisma в `prisma/migrations` (лише additive), застосовуються на старті '
            'контейнера; клієнт у `src/generated` не комітиться, його генерують typecheck і build.' % versions['postgres']
            if flags['db'] else 'БД немає.')
    if flags['pgvector']:
        data += ' Вектори в тій самій БД: образ `%s`, розширення вмикає перша міграція.' % versions['pgvector_image']
    compose = 'Docker Compose на VPS' + (' за Traefik' if flags['http'] else '')
    deploy = compose + ', вручну власник; CI немає; кроки в docs/deployment.md.'
    if o.brief:
        # The server and CI/CD wait for the base's infrastructure stage (owner's decision 14.10.2026)
        deploy = ('заготовка %s (кроки в docs/deployment.md); сервер і CI/CD не вирішено до етапу інфраструктури '
                  '(docs/decisions.md).' % compose)
    return {'stack': ', '.join(stack) + '; pnpm %s (`packageManager`), скрипти встановлення залежностей лише за '
                     '`allowBuilds` у `pnpm-workspace.yaml`.' % versions['pnpm'],
            'commands': ' | '.join(commands), 'data_fact': data, 'deploy': deploy, 'note': NOTES[o.type],
            'status_file': STATE_DIR + '/STATUS.md',
            'docs_index': 'README (запуск і перевірка), ' + DOCS_INDEX
                          + (', docs/requirements.md (вимоги)' if o.brief else '') + '.'}


def build_values(o, versions):
    values = {'name': o.name, 'db_name': o.name.replace('-', '_'), 'date': o.date, 'node': versions['node'],
              'pnpm': versions['pnpm'],
              'postgres': versions['postgres'], 'type': o.type, 'tier': o.tier or DEFAULT_TIER[o.type],
              'db_image': (versions['pgvector_image'] if 'pgvector' in o.modules
                           else 'postgres:%s-alpine' % versions['postgres']),
              'risk': o.risk, 'data': o.data, 'ui': o.ui, 'numbers': o.numbers,
              'not_add': o.not_add or DEFAULT_NOT_ADD[o.type], 'hatches': o.hatches or DEFAULT_HATCHES[o.type],
              'review_when': o.review_when,
              'ui_source': o.ui_source, 'standard': versions['_checked'], 'branches': 'лише `main`.',
              'modules_text': ', '.join(MODULE_NAMES[m] for m in o.modules)}
    values.update(stage_values(o))
    values.update(card_values(o, versions))
    return values


def stage_values(o):
    """The card lines of the stage and of what is not standard, shared with an existing project taken into the
    standard."""
    return {'stage': STAGES[o.stage], 'stage_gates': STAGE_GATES[o.stage], 'stage_goal': o.stage_goal, 'custom': o.custom}


def layer_files(layer):
    """(relative template path, absolute path) for every file of a layer; an unreadable folder is an error."""
    def fail(e):
        raise ScaffoldError('templates/%s: %s' % (layer, e))
    root = os.path.join(TEMPLATES, layer)
    if not os.path.isdir(root):
        raise ScaffoldError('templates/%s is missing' % layer)
    for dirpath, _, names in os.walk(root, onerror=fail):
        for fname in sorted(names):
            yield os.path.relpath(os.path.join(dirpath, fname), root), os.path.join(dirpath, fname)


def plan(o):
    """{output path: text} for every file of the project, rendered in memory."""
    versions, flags = load_versions(), flags_for(o.type, o.db, o.brief, o.modules)
    values = build_values(o, versions)
    files = {'package.json': package_json(o.name, o.type, o.db, versions),
             'pnpm-workspace.yaml': workspace_yaml(o.type, o.db, versions)}
    layers = LAYERS[o.type] + (((DB_LAYER,) + DB_EXTRA.get(o.type, ())) if flags['db'] else ()) \
        + tuple(MODULE_LAYERS[m] for m in o.modules)
    for layer in layers:
        for rel, path in layer_files(layer):
            if not rel.endswith('.tmpl'):
                raise ScaffoldError('templates/%s/%s: template files end with .tmpl' % (layer, rel))
            out = output_name(rel)
            if out in files:
                raise ScaffoldError('templates/%s/%s: %s comes from two layers' % (layer, rel, out))
            files[out] = render_file(path, flags, values, 'templates/%s/%s' % (layer, rel))
    return files


def render_file(path, flags, values, where):
    with open(path, encoding='utf-8') as fh:
        return render(fh.read(), flags, values, where)
