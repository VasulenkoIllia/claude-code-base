"""Checks of the rendered files of the new-project standard, for scaffold_check.self_check.

Each check takes the files of one type x db (path: text, rendered in memory) and returns failure lines: the file
manifest, Docker and Compose (deploy.md), .gitignore asked from the real git, .dockerignore and ESLint ignores,
pinned versions, bare imports package.json names, scripts and pnpm settings (deps.md), the Nest settings, the dev command and signal handlers, the card
fields, the brief marks, and the error handling and request line the Fastify and the Nest type must share.
"""
import json
import os
import re
import subprocess

import scaffold_render as sr
from scaffold_gaps import ignored_paths

EXACT = re.compile(r'^\d+\.\d+\.\d+$')
# The specifier of `import ... from "x"` (one statement, over several lines too), of `import "x"` or of `import("x")`,
# not a relative one
BARE_IMPORT = re.compile(r'''^\s*(?:import|export)\b[^"';]*?\bfrom\s+["']([^"'./][^"']*)["']'''
                         r'''|^\s*import\s+["']([^"'./][^"']*)["']|\bimport\(\s*["']([^"'./][^"']*)["']''', re.M)
CARD_FIELDS = ('- Стан: `.claude/state/STATUS.md`', '- Документи: ', '- Команди: ', 'Рівень T', 'Етап: ',
               'Гейти етапу: ', 'Успіх етапу: ', 'Цифри: ', 'Не додаємо: ', 'Люки: ', 'Нестандартне: ',
               'Переглянути, коли: ')
# Files a first commit holds, by the owner's rule: no word of the tool that wrote them. The card stays local
NO_TOOL_WORD = re.compile(r'claude|anthropic', re.I)
NO_TOOL_WORD_EXEMPT = ('CLAUDE.local.md',)
DOCKERIGNORE_NEEDS = ('**/.env*', '.git', '**/node_modules', '*.sql', '**/*.dump', '**/*.pem', '**/*.key', 'design',
                      'brief')
# Paths git must ignore, and must keep (relative to the project root), checked with the real git
GIT_IGNORED = ('.env', '.env.local', 'backup.sql', 'db.dump', 'certs/x.pem', 'certs/x.key', 'node_modules/x/i.js',
               'dist/main.js', 'app.log', 'brief/tz.pdf', 'brief/scan/page-1.png', 'CLAUDE.local.md',
               'brief')  # no such path on disk, so git checks it as a file: a symlink or a file named brief
# A start from a brief: what the card, docs/decisions.md and README say, and only then
BRIEF_MARKS = {'CLAUDE.local.md': ('`brief/`', 'не вирішено'), 'docs/decisions.md': ('не вирішено',),
               'README.md': ('docs/requirements.md', '`brief/`')}
GIT_KEPT = ('.env.example', 'src/main.ts', 'pnpm-lock.yaml', 'pnpm-workspace.yaml')
GIT_KEPT_DB = ('prisma/migrations/0_init/migration.sql', 'prisma/migrations/migration_lock.toml')
COMMON_FILES = ('.npmrc', '.nvmrc', '.gitignore', '.dockerignore', '.env.example', 'package.json', 'pnpm-workspace.yaml',
                'tsconfig.json', 'tsconfig.build.json', 'eslint.config.js', 'vitest.config.ts', 'Dockerfile',
                'docker-compose.yml',
                'README.md', 'CLAUDE.local.md', 'docs/deployment.md', 'docs/integrations.md', 'docs/decisions.md',
                '.claude/state/STATUS.md', '.claude/state/STATUS-archive.md', 'src/config.ts', 'src/main.ts')
TYPE_FILES = {'api': ('src/app.ts', 'src/app.test.ts'),
              'nest': ('nest-cli.json', 'src/app.module.ts', 'src/errors.filter.ts', 'src/health/health.controller.ts',
                       'src/http.ts', 'src/app.test.ts'),
              'fullstack': ('src/app.ts', 'src/app.test.ts', 'vite.config.ts', 'web/index.html', 'web/tsconfig.json',
                            'web/src/main.tsx', 'web/src/App.tsx', 'web/src/index.css'),
              'integration': ('src/log.ts', 'src/log.test.ts', 'src/job.ts', 'src/job.test.ts'),
              'bot': ('src/log.ts', 'src/log.test.ts', 'src/bot.ts', 'src/bot.test.ts')}
DB_FILES = ('prisma/schema.prisma', 'prisma.config.ts', 'src/db.ts', 'docker-compose.dev.yml')
DB_TYPE_FILES = {'nest': ('src/database/database.module.ts',)}
MODULE_FILES = {'pgvector': ('prisma/migrations/00000000000000_pgvector/migration.sql',
                             'prisma/migrations/migration_lock.toml'),
                'budget': ('src/budget.ts', 'src/budget.test.ts')}
# Its own list, not scaffold_render.HTTP_TYPES: a type dropped from that tuple must fail here
HTTP_KINDS = ('api', 'nest', 'fullstack')
# What the client may learn from an error and what the request line logs: the Fastify type and the Nest type must
# decide it the same way. (function, file in the Fastify type, file in the Nest type)
SHARED_FUNCTIONS = (('statusOf', 'src/app.ts', 'src/errors.filter.ts'),
                    ('clientMessage', 'src/app.ts', 'src/errors.filter.ts'),
                    ('requestLine', 'src/app.ts', 'src/http.ts'))
# The logger must get it, in code and not in a comment: Fastify's own request line keeps the query
REQUEST_LINE_USE = re.compile(r'^[^/\n]*logger: [^/\n]*serializers: \{ req: requestLine \}', re.M)
NEST_DEV = 'nest start --watch --exec "node --env-file-if-exists=.env"'
# The other types: Node's watch mode with tsx as the loader (tsx watch answers a second Ctrl+C with SIGKILL)
NODE_DEV = 'node --watch --env-file-if-exists=.env --import tsx src/main.ts'
# Under pnpm run dev one Ctrl+C reaches the app from the terminal and from the watch mode: the handler of both
# signals returns early on its flag and sets that flag, and a timer ends a stop that hangs
SIGNAL_HANDLER = re.compile(r'for \(const signal of \["SIGTERM", "SIGINT"\] as const\) \{\n\s+'
                            r'process\.on\(signal, \(\) => \{\n\s+if \((?P<flag>[\w.]+)\) return;[\s\S]*?\n\s+'
                            r'(?P=flag) = ')
SHUTDOWN_TIMER = re.compile(r'\}, SHUTDOWN_TIMEOUT_MS\)\.unref\(\);')
# Integration: armed after the wait for a busy run, the timer would not stop a run that ignores its signal
BUSY_WAIT = 'while (job.isBusy())'
# The project runs on pnpm: a command of npm or npx in its files is one the standard forgot to change, and pnpx,
# pnpm dlx and pnpm create run a package from the registry outside the lockfile
NPM_COMMAND = re.compile(r'\bnpm +(run|install|ci|exec|i|add|t|test|start|audit|update|uninstall|rebuild|publish|init'
                         r'|link|pack)\b|\bnpx +[a-z@-]|\bpnpx\b|\bpnpm +(dlx|create)\b')
# The one npm command a project names: pnpm itself at an exact version, with its own install script allowed by name,
# in the Dockerfile and the README (Node 25 and later ship no corepack); the command ends there, at the end of the
# line or the closing backtick
PNPM_FROM_NPM = re.compile(r'\bnpm install --global --allow-scripts=pnpm pnpm@\d+\.\d+\.\d+(?=`|$)', re.M)
# The top-level keys of pnpm-workspace.yaml, in this order: any other one (ignoreScripts, onlyBuiltDependencies,
# permissions, a quoted key) could run or skip install scripts without a decision
WORKSPACE_KEYS = ('strictDepBuilds', 'dangerouslyAllowAllBuilds', 'allowBuilds')
# The project's own scripts that pnpm install runs by itself, whatever allowBuilds says
INSTALL_HOOKS = ('preinstall', 'install', 'postinstall', 'preprepare', 'prepare', 'postprepare', 'pnpm:devPreinstall')
# A credential in .npmrc: the file is committed
NPMRC_CREDENTIAL = re.compile(r'^\s*(?://\S+:)?_auth(?:Token)?\s*=|_password|://[^/\s:@]+:[^/\s@]+@', re.M)
# What the runtime stage takes from the others, line by line: the production dependencies and the compiled code
RUNTIME_COPIES = {'COPY --from=deps /app/node_modules ./node_modules', 'COPY --from=build /app/dist ./dist'}
# A setting that lifts the install-script stop, a credential left in a layer, a download piped into a shell
DOCKER_FORBIDDEN = re.compile(r'dangerously|pnpm_config_|npm_config_|^(?:ARG|ENV)\b.*(?:TOKEN|SECRET|PASSWORD|_AUTH)'
                              r'|\b(?:curl|wget)\b[^\n]*\|\s*(?:ba)?sh\b', re.I | re.M)
SOURCE_EXTENSIONS = ('.ts', '.tsx', '.mts', '.cts', '.js', '.jsx', '.mjs', '.cjs')


def check_text(sc, rel, text, label):
    fails, base = [], os.path.basename(rel)
    if '{{' in text:
        fails.append('%s: %s: template marker left' % (label, rel))
    if any(d in text for d in sc.LONG_DASHES):
        fails.append('%s: %s: long dash' % (label, rel))
    if rel not in NO_TOOL_WORD_EXEMPT and NO_TOOL_WORD.search(text):
        fails.append('%s: %s: names the tool in a file of the first commit' % (label, rel))
    if NPM_COMMAND.search(PNPM_FROM_NPM.sub('', text)):
        fails.append('%s: %s: an npm command, or a download-and-run (npx, pnpx, pnpm dlx, pnpm create), in a project '
                     'on pnpm' % (label, rel))
    if ':latest' in text:
        fails.append('%s: %s: image tag latest' % (label, rel))
    if base.lower() in ('claude.md', 'agents.md') or (base == 'CLAUDE.local.md' and rel != base):
        fails.append('%s: %s: instruction file outside the card' % (label, rel))
    if rel.endswith('.json'):
        try:
            json.loads(text)
        except ValueError as e:
            fails.append('%s: %s: invalid JSON (%s)' % (label, rel, e))
    return fails


def check_docker(files, versions, http, db, label, modules=()):
    fails = []
    pg_image = versions['pgvector_image'] if 'pgvector' in modules else 'postgres:%s-alpine' % versions['postgres']
    node_image = 'node:%s-alpine' % versions['node']
    dockerfile = files['Dockerfile']
    froms = re.findall(r'^FROM (\S+)', dockerfile, re.M)
    if len(froms) < 2 or any(f != node_image for f in froms):
        fails.append('%s: Dockerfile needs a build and a runtime stage FROM %s, got %s' % (label, node_image, froms))
    if not re.search(r'^USER node$', dockerfile, re.M):
        fails.append('%s: Dockerfile runtime does not switch to USER node' % label)
    installs = re.findall(r'^RUN .*\bpnpm[ \t]+(?:install|i|add)\b.*$', dockerfile, re.M)
    paired = re.findall(r'^COPY package\.json pnpm-lock\.yaml pnpm-workspace\.yaml \./\nRUN .*\bpnpm[ \t]+(?:install|i|add)\b',
                        dockerfile, re.M)
    if not installs or len(paired) != len(installs):
        fails.append('%s: Dockerfile must copy pnpm-workspace.yaml with the manifests right before each pnpm install '
                     '(without allowBuilds the install stops)' % label)
    if any('--frozen-lockfile' not in line.split() for line in installs) \
            or re.search(r'\bnpm (ci|install)\b', PNPM_FROM_NPM.sub('', dockerfile)):
        fails.append('%s: Dockerfile must install with pnpm install --frozen-lockfile only' % label)
    # pnpm of packageManager in each stage that installs; corepack, a COREPACK_* setting too, is a leftover outside
    # a comment
    pnpm_lines = re.findall(r'^RUN npm install --global --allow-scripts=pnpm pnpm@(\S+)$', dockerfile, re.M)
    if re.search(r'^(?:COPY|ADD)\b.*\.npmrc', dockerfile, re.M) or len(pnpm_lines) != len(installs) \
            or set(pnpm_lines) != {versions['pnpm']} or re.search(r'^[^#\n]*corepack', dockerfile, re.M | re.I):
        fails.append('%s: Dockerfile must install pnpm %s with npm in each stage that installs, use no corepack and '
                     'copy no .npmrc' % (label, versions['pnpm']))
    if DOCKER_FORBIDDEN.search(dockerfile):
        fails.append('%s: Dockerfile holds a pnpm or npm setting, a credential or a download piped into a shell' % label)
    # osv_summary only warns on HIGH in a dev-only package because none ships: the runtime takes node_modules from
    # the one install with --prod, and besides only the compiled code
    copies = {line.strip() for line in dockerfile.splitlines() if line.startswith(('COPY', 'ADD')) and '--from' in line}
    if sum('--prod' in line.split() for line in installs) != 1 or copies != RUNTIME_COPIES:
        fails.append('%s: Dockerfile runtime must copy node_modules from the deps stage, the one install with --prod, '
                     'and dist from the build stage, nothing else' % label)
    prod = files['docker-compose.yml']
    services = 1 + (db == 'prisma')
    for what, pattern, want in (
            ('restart: unless-stopped', r'^\s+restart: unless-stopped$', services),
            ('logging max-size', r'^\s+max-size: ', services),
            ('stop_grace_period', r'^\s+stop_grace_period: ', 1),
            ('healthcheck (db always, app only with HTTP)', r'^\s+healthcheck:$', (db == 'prisma') + http),
            ('depends_on service_healthy', r'condition: service_healthy$', db == 'prisma'),
            ('no-new-privileges', r'no-new-privileges:true$', services),
            ('cap_drop ALL (app)', r'^\s+cap_drop:\n\s+- ALL$', 1),
            ('HOST: 0.0.0.0 (http app)', r'^\s+HOST: 0\.0\.0\.0$', http)):
        if len(re.findall(pattern, prod, re.M)) != want:
            fails.append('%s: docker-compose.yml: %s expected %d time(s)' % (label, what, want))
    grace = re.search(r'^\s+stop_grace_period: (\d+)s$', prod, re.M)
    timeout = re.search(r'^const SHUTDOWN_TIMEOUT_MS = ([\d_]+);$', files.get('src/main.ts', ''), re.M)
    if not grace or not timeout or int(timeout.group(1).replace('_', '')) > int(grace.group(1)) * 1000 - 5000:
        fails.append('%s: SHUTDOWN_TIMEOUT_MS in src/main.ts must end 5 s or more before stop_grace_period' % label)
    if re.search(r'^\s+ports:', prod, re.M):
        fails.append('%s: docker-compose.yml publishes a port (production goes through Traefik only)' % label)
    for rel in (r for r in files if r.startswith('docker-compose')):
        fails += ['%s: %s: image %s, expected %s' % (label, rel, i, pg_image)
                  for i in re.findall(r'^\s+image: (\S+)', files[rel], re.M) if i != pg_image]
    if db == 'prisma':
        mappings = re.findall(r'^\s+- "([^"]+:\d+)"$', files['docker-compose.dev.yml'], re.M)
        if not mappings or any(not m.startswith('127.0.0.1:') for m in mappings):
            fails.append('%s: docker-compose.dev.yml ports must bind 127.0.0.1, got %s' % (label, mappings))
        # The first-start init server answers only on the socket: a socket check reports healthy too early
        fails += ['%s: %s: the Postgres healthcheck must use TCP (pg_isready -h 127.0.0.1)' % (label, rel)
                  for rel in ('docker-compose.yml', 'docker-compose.dev.yml')
                  if 'pg_isready -h 127.0.0.1 ' not in files[rel]]
    return fails


def check_gitignore(text, db, label):
    """Asks the real git which paths the generated .gitignore ignores (global excludes switched off)."""
    kept = GIT_KEPT + (GIT_KEPT_DB if db == 'prisma' else ())
    try:
        ignored = ignored_paths(text, GIT_IGNORED + kept)
    except (OSError, subprocess.SubprocessError) as e:
        return ['%s: .gitignore not checked, git failed: %s' % (label, e)]
    return (['%s: .gitignore does not ignore %s' % (label, p) for p in GIT_IGNORED if p not in ignored]
            + ['%s: .gitignore ignores %s' % (label, p) for p in kept if p in ignored])


def check_nest(files, kind, label):
    """Nest's DI reads constructor types from decorator metadata: tsc emits it, tsx (esbuild) does not. Only Nest
    turns decorators on, and `nest g` spec files need the Vitest globals."""
    fails = []
    try:
        tsconfig = json.loads(files.get('tsconfig.json', '{}')).get('compilerOptions', {})
    except ValueError:
        return fails  # check_text already names the broken JSON
    nest = kind == 'nest'
    if bool(tsconfig.get('emitDecoratorMetadata')) != nest or bool(tsconfig.get('experimentalDecorators')) != nest:
        fails.append('%s: tsconfig.json decorators (experimentalDecorators, emitDecoratorMetadata) must be on '
                     'for nest only' % label)
    if not nest:
        return fails
    dev = json.loads(files['package.json']).get('scripts', {}).get('dev', '')
    if dev != NEST_DEV:
        fails.append('%s: dev must be `%s` (tsx drops the decorator metadata, the app reads .env when it exists)'
                     % (label, NEST_DEV))
    # `nest g` writes *.spec.ts next to the code: Vitest runs them with its globals, the build leaves them out
    vitest = files.get('vitest.config.ts', '')
    if ('vitest/globals' not in tsconfig.get('types', []) or 'globals: true' not in vitest
            or '"src/**/*.{test,spec}.ts"' not in vitest):
        fails.append('%s: Vitest must run the *.spec.ts files of `nest g` with its globals' % label)
    try:
        build = json.loads(files.get('tsconfig.build.json', '{}'))
        cli = json.loads(files.get('nest-cli.json', '{}')).get('compilerOptions', {})
    except ValueError:
        return fails  # check_text already names the broken JSON
    if 'src/**/*.spec.ts' not in build.get('exclude', []):
        fails.append('%s: tsconfig.build.json does not leave the *.spec.ts files out of dist' % label)
    if build.get('compilerOptions', {}).get('types') != ['node']:
        fails.append('%s: tsconfig.build.json must keep the Vitest globals out of the app code (types: ["node"])'
                     % label)
    # Another builder (swc, webpack) emits the decorator metadata differently from the build and the tests
    if (cli.get('builder'), cli.get('tsConfigPath')) != ('tsc', 'tsconfig.build.json'):
        fails.append('%s: nest-cli.json must build with tsc from tsconfig.build.json, like pnpm run build' % label)
    return fails


def check_signals(files, kind, label):
    """Ctrl+C in pnpm run dev stops the app the way SIGTERM does in production: the extra copies of the signal are
    ignored, so none of them kills the app halfway through closing, and a stop that hangs still ends."""
    fails = []
    dev = json.loads(files['package.json']).get('scripts', {}).get('dev', '')
    if kind != 'nest' and dev != NODE_DEV:
        fails.append('%s: dev must be `%s` (tsx watch kills the app on the second Ctrl+C)' % (label, NODE_DEV))
    main = files.get('src/main.ts', '')
    if 'process.once(' in main or not SIGNAL_HANDLER.search(main):
        fails.append('%s: src/main.ts must loop over ["SIGTERM", "SIGINT"] with process.on(signal, () => {...}) whose '
                     'first line is `if (<flag>) return;` and which sets that flag (`<flag> = ...`), not process.once'
                     % label)
    if not SHUTDOWN_TIMER.search(main):
        fails.append('%s: src/main.ts must end a stop that hangs with setTimeout(..., SHUTDOWN_TIMEOUT_MS).unref()'
                     % label)
    elif kind == 'integration' and not 0 <= SHUTDOWN_TIMER.search(main).start() < main.find(BUSY_WAIT):
        fails.append('%s: src/main.ts must arm the shutdown timer before it waits for a busy run (%s)'
                     % (label, BUSY_WAIT))
    return fails


def function_body(text, name):
    """The text of a top-level `function <name>` (exported or not) up to its closing brace, comment lines and blank
    lines left out."""
    m = re.search(r'^(?:export )?function %s\(.*?^}$' % re.escape(name), text, re.M | re.S)
    if not m:
        return None
    return '\n'.join(line.rstrip() for line in m.group(0).splitlines()
                     if line.strip() and not line.strip().startswith('//'))


def check_parity(rendered):
    """The Fastify type and the Nest type hide error details and the query of the request line the same way."""
    api, nest = rendered.get('api', {}), rendered.get('nest', {})
    fails = []
    for name, api_rel, nest_rel in SHARED_FUNCTIONS:
        a, b = function_body(api.get(api_rel, ''), name), function_body(nest.get(nest_rel, ''), name)
        if a is None or b is None or a != b:
            fails.append('parity: function %s differs between api %s and nest %s (or is missing): a fix in one must '
                         'reach the other' % (name, api_rel, nest_rel))
    _, api_rel, nest_rel = next(f for f in SHARED_FUNCTIONS if f[0] == 'requestLine')
    fails += ['parity: %s %s does not give the logger `serializers: { req: requestLine }` in code, so the request '
              'line keeps the query' % (kind, rel)
              for kind, files, rel in (('api', api, api_rel), ('nest', nest, nest_rel))
              if not REQUEST_LINE_USE.search(files.get(rel, ''))]
    return fails


def top_block(text, key):
    """{name: value} of the two-space entries under a top-level key of a YAML file the scaffold wrote, None without the
    key; quotes around a name and a trailing comment dropped. A blank or comment line does not end the block, and a
    value on the key's own line other than {} (flow style) comes back as one entry, so no check reads it as empty."""
    m = re.search(r'^%s:(.*)$' % re.escape(key), text, re.M)
    if not m:
        return None
    inline = m.group(1).split(' #', 1)[0].strip()
    entries = {} if inline in ('', '{}') else {'(inline)': inline}
    for line in text[m.end() + 1:].splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if not line.startswith('  '):
            break
        name, _, value = line.strip().partition(': ')
        entries[name.strip("'")] = value.split(' #', 1)[0].strip()
    return entries


def check_pnpm(files, versions, db, label):
    """The pnpm of versions.json in packageManager; pnpm-workspace.yaml holds only its own keys: it stops on an install
    script nobody decided on, lets none run, and keeps a global dangerouslyAllowAllBuilds from lifting the stop;
    overrides (db types only) stand there too, since pnpm reads no overrides from package.json."""
    fails = []
    pkg = json.loads(files['package.json'])
    if pkg.get('packageManager') != 'pnpm@%s' % versions['pnpm']:
        fails.append('%s: package.json packageManager is not pnpm@%s' % (label, versions['pnpm']))
    workspace = files.get('pnpm-workspace.yaml', '')
    wanted = versions['overrides'] if db == 'prisma' else {}
    keys = re.findall(r'^([^#\s][^:]*):', workspace, re.M)  # quoted keys too; a comment line starts with #
    wanted_keys = list(WORKSPACE_KEYS) + (['overrides'] if wanted else [])
    if keys != wanted_keys or not re.search(r'^strictDepBuilds: true$', workspace, re.M) \
            or not re.search(r'^dangerouslyAllowAllBuilds: false$', workspace, re.M):
        fails.append('%s: pnpm-workspace.yaml must hold %s only, with strictDepBuilds: true and '
                     'dangerouslyAllowAllBuilds: false; got %s' % (label, ', '.join(wanted_keys), keys))
    builds = top_block(workspace, 'allowBuilds')
    if builds is None or any(value != 'false' for value in builds.values()):
        fails.append('%s: pnpm-workspace.yaml allowBuilds must list each package with a script as false, got %s'
                     % (label, builds))
    if 'overrides' in pkg or (top_block(workspace, 'overrides') or {}) != wanted:
        fails.append('%s: overrides must stand in pnpm-workspace.yaml as in versions.json (db types only)' % label)
    return fails


def check_imports(files, pkg, label):
    """Each bare import of a source file names a package of package.json: npm put the dependencies of a dependency
    next to the project's own, pnpm resolves only those package.json names."""
    named = set(pkg.get('dependencies', {})) | set(pkg.get('devDependencies', {}))
    fails = []
    for rel in sorted(r for r in files if r.endswith(SOURCE_EXTENSIONS)):
        for m in BARE_IMPORT.finditer(files[rel]):
            spec = m.group(1) or m.group(2) or m.group(3)
            parts = spec.split('/')
            package = '/'.join(parts[:2]) if spec.startswith('@') else parts[0]
            if not spec.startswith('node:') and package not in named:
                fails.append('%s: %s imports %s, which package.json does not name' % (label, rel, package))
    return fails


def check_brief(files, brief, label):
    fails = []
    for rel, marks in BRIEF_MARKS.items():
        fails += ['%s: %s %s "%s"' % (label, rel, 'lacks' if brief else 'has without a brief', mark)
                  for mark in marks if (mark in files.get(rel, '')) != brief]
    return fails


def check_files(sc, files, versions, kind, db, brief=False, modules=()):
    label = '+'.join((kind, db) + (('brief',) if brief else ()) + tuple(modules))
    fails = []
    for rel, text in files.items():
        fails += check_text(sc, rel, text, label)
    expected = set(COMMON_FILES) | set(TYPE_FILES[kind]) \
        | (set(DB_FILES) | set(DB_TYPE_FILES.get(kind, ())) if db == 'prisma' else set()) \
        | {rel for m in modules for rel in MODULE_FILES[m]}
    fails += ['%s: %s is missing' % (label, rel) for rel in sorted(expected - set(files))]
    fails += ['%s: %s is not in the manifest (scaffold_check_files.py)' % (label, rel)
              for rel in sorted(set(files) - expected)]
    if '.npmrc' in files and 'ignore-scripts=true' not in files['.npmrc'].splitlines():
        fails.append('%s: .npmrc lacks ignore-scripts=true' % label)
    if NPMRC_CREDENTIAL.search(files.get('.npmrc', '')):
        fails.append('%s: .npmrc holds a registry credential, and the file is committed' % label)
    fails += check_gitignore(files.get('.gitignore', ''), db, label)
    lines = files.get('.dockerignore', '').splitlines()
    fails += ['%s: .dockerignore lacks %s' % (label, n) for n in DOCKERIGNORE_NEEDS if n not in lines]
    fails += ['%s: eslint.config.js does not ignore %s (client files)' % (label, d) for d in ('design/', 'brief/')
              if '"%s"' % d not in files.get('eslint.config.js', '')]
    if files.get('.nvmrc', '').strip() != versions['node']:
        fails.append('%s: .nvmrc is not Node %s' % (label, versions['node']))
    if 'Dockerfile' in files and 'docker-compose.yml' in files:
        fails += check_docker(files, versions, kind in HTTP_KINDS, db, label, modules)
    fails += check_nest(files, kind, label)
    fails += check_signals(files, kind, label)
    pkg, pins = json.loads(files['package.json']), sr.package_versions(kind, versions)
    used = set()
    for section in ('dependencies', 'devDependencies'):
        for name, ver in pkg.get(section, {}).items():
            used.add(name)
            if not EXACT.match(ver) or ver != pins.get(name):
                fails.append('%s: package.json %s %s is not the exact pinned version' % (label, name, ver))
    fails += check_imports(files, pkg, label)
    scripts = pkg.get('scripts', {})
    hooks = [s for s in INSTALL_HOOKS if s in scripts]
    if hooks:
        fails.append('%s: package.json has %s (pnpm install would run it; run it explicitly)' % (label, ', '.join(hooks)))
    if db == 'prisma':
        # The local path of the README: wait for a healthy Postgres, refresh the client after a migration, keep the data
        if '--wait' not in scripts.get('db:up', '').split():
            fails.append('%s: db:up does not wait for a healthy Postgres (--wait)' % label)
        migrate = scripts.get('db:migrate', '')
        if not (migrate.startswith('prisma generate && ') and migrate.endswith('prisma migrate dev')):
            fails.append('%s: db:migrate must regenerate the Prisma client and end with migrate dev (pnpm appends '
                         'arguments to the last command)' % label)
        if not scripts.get('db:down', '').endswith(' down'):
            fails.append('%s: db:down must be a plain compose down (the data volume stays)' % label)
    fails += check_pnpm(files, versions, db, label)
    card = files.get('CLAUDE.local.md', '')
    for field in CARD_FIELDS:
        m = re.search(r'^%s(.*)$' % re.escape(field), card, re.M)
        if not m or not m.group(1).strip():
            fails.append('%s: card field "%s" is empty' % (label, field.strip()))
    fails += check_brief(files, brief, label)
    return fails, used


def check_brief_delta(plain, brief, label):
    """A brief changes only the files of BRIEF_MARKS: the code, the deploy files and the other docs stay the same."""
    changed = {rel for rel in set(plain) | set(brief) if plain.get(rel) != brief.get(rel)}
    if changed == set(BRIEF_MARKS):
        return []
    return ['%s: the brief changes %s, expected only %s' % (label, sorted(changed), sorted(BRIEF_MARKS))]
