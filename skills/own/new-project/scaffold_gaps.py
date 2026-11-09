"""The gap report of an existing project against the standard (scaffold.py --adopt, docs/standard-gaps.md).

gaps() reads the project and writes nothing. A project rendered by the standard itself has no gaps: the self-check holds
every check here to that, and to finding its gap in a project that breaks the rule.
The repository is untrusted and the report reaches the model, so read() takes only regular files, and only plain names
and version numbers are ever quoted from it.
A monorepo keeps its files in packages and infra/, so the rules work on all of its files (scaffold_project.py). What the
project chose differently from the standard is a note, not a gap.
"""
import os
import re
import stat
import subprocess
import tempfile

import scaffold_project

# Paths the project's own .gitignore must hide; asked from the real git, with the global excludes switched off
SECRET_PATHS = ('.env', '.env.local', 'certs/x.pem', 'certs/x.key', 'dump.sql', 'db.dump')
# Lines that keep each one out of the image; `.*` covers the dotfiles at the root, as in the standard. The `*` of an
# allowlist covers .git, which no line brings back; an allowed package folder brings back its .env and node_modules
DOCKERIGNORE_NEEDS = {'.env': r'(\*\*/)?\.env(\*|\.\*)?|\.\*', '.git': r'(\*\*/)?\.git/?|\.\*|\*',
                      'node_modules': r'(\*\*/)?node_modules/?'}
CHECK_SCRIPTS = ('typecheck', 'lint', 'test', 'build')
# pnpm first: a project that declares nothing and has two lock files stays on the standard's
LOCKS = {'pnpm': ('pnpm-lock.yaml',), 'npm': ('package-lock.json',), 'yarn': ('yarn.lock',),
         'bun': ('bun.lock', 'bun.lockb')}
DECLARED_MANAGER = re.compile(r'(npm|pnpm|yarn|bun)@(\d{1,4})?', re.A)
PNPM_WORKSPACE = 'pnpm-workspace.yaml'
# From version 10 pnpm runs no install script of a dependency unless a list allows it; allowBuilds is one from 10.26
PNPM_SAFE_MAJOR = 10
ONLY_BUILT = re.compile(r'^onlyBuiltDependencies:', re.M)
ALLOW_BUILDS = re.compile(r'^allowBuilds:', re.M)
# Block or flow style, the key or the value quoted: pnpm reads each of them as the flag
ALL_BUILDS_YAML = re.compile(r'''(?:^|[{,])\s*["']?dangerouslyAllowAllBuilds["']?\s*:\s*["']?true\b''', re.M | re.I)
ALL_BUILDS_NPMRC = re.compile(r'^dangerously-allow-all-builds\s*=\s*true', re.M | re.I)
EXACT_VERSION = re.compile(r'\d+\.\d+\.\d+$')
ESLINT_FILES = ('eslint.config.js', 'eslint.config.mjs', 'eslint.config.cjs', 'eslint.config.ts', '.eslintrc.json',
                '.eslintrc.js', '.eslintrc.cjs')
DB_PORTS = ('5432', '3306', '6379', '27017')
DEV_WORDS = 'dev|develop|development|local|test|tests|e2e|ci|cypress|playwright|gitpod'
# A file for local work or tests: not what runs in production, so the rules of production don't ask it, and it proves
# nothing for them either. A folder must be called just that: `dev-portal/` may well be a service
DEV_FILE = re.compile(r'(^|/)(%s)/|(^|[/._-])(%s)([._-][^/]*)?$' % (DEV_WORDS, DEV_WORDS), re.I)
TSCONFIG = re.compile(r'tsconfig(\.[\w-]+)*\.json')
# A config that only lists others compiles nothing
SOLUTION_CONFIG = re.compile(r'"files"\s*:\s*\[\s*\]')
ROOT_FILES = ('.nvmrc', '.npmrc', '.gitignore', PNPM_WORKSPACE)
READ_SUFFIXES = ('.yml', '.yaml', '.dockerignore')
EXAMPLES = 5
MAX_READ = 1_000_000
SAFE_WORD = re.compile(r'[\w.:@/+-]{1,40}', re.A)
NODE_VERSION = re.compile(r'v?(\d{1,3})(\.\d{1,3}){0,2}', re.A)


def read(target, rel):
    """The start of a regular file of the project, None for anything else: a link may point at a file of the owner's, a
    FIFO would hang."""
    try:
        fd = os.open(os.path.join(target, rel), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as fh:
            return fh.read(MAX_READ).decode('utf-8-sig', 'replace') if stat.S_ISREG(os.fstat(fd).st_mode) else None
    except OSError:
        return None


def section(pkg, key):
    """A part of package.json as a dict: an untrusted file may hold anything there."""
    value = (pkg or {}).get(key)
    return value if isinstance(value, dict) else {}


def safe_words(words):
    """The names that may be quoted: a key of package.json or a branch name may hold a whole instruction."""
    return [w for w in words if isinstance(w, str) and SAFE_WORD.fullmatch(w)]


def label(rel):
    """A path as the report may quote it: the whole of it, its file name, or neither."""
    return (safe_words([rel, os.path.basename(rel)]) + ['файл'])[0]


def named(rels):
    """Up to EXAMPLES paths as the report may quote them, and how many stayed out: a gap is one line."""
    more = len(rels) - EXAMPLES
    return ', '.join(label(rel) for rel in rels[:EXAMPLES]) + (' (+%d)' % more if more > 0 else '')


def node_major(target):
    """The major version of .nvmrc, None when it holds anything else."""
    m = NODE_VERSION.fullmatch((read(target, '.nvmrc') or '').strip())
    return m.group(1) if m else None


def package_of(target, rel='package.json'):
    """The parsed package.json, None without one, {} when it can't be parsed."""
    text = read(target, rel)
    return None if text is None else scaffold_project.json_object(text) or {}


def manager(target, pkg):
    """The package manager: what package.json declares, else the lock file that stands, else the standard's pnpm."""
    declared = DECLARED_MANAGER.match(str((pkg or {}).get('packageManager', '')))
    if declared:
        return declared.group(1)
    stands = (name for name, locks in LOCKS.items() if any(os.path.exists(os.path.join(target, f)) for f in locks))
    return next(stands, 'pnpm')


def dependencies(target, files):
    """(name, version) of every package.json of the project: two packages may disagree."""
    pairs = []
    for rel in files:
        if os.path.basename(rel) == 'package.json':
            pkg = package_of(target, rel)
            pairs += list(section(pkg, 'dependencies').items()) + list(section(pkg, 'devDependencies').items())
    return pairs


def catalog_of(target):
    """(name, version) of the pnpm catalogs."""
    return scaffold_project.catalog_entries(read(target, PNPM_WORKSPACE) or '')


def dockerfiles(target, files):
    return [f for f in files if scaffold_project.is_dockerfile(f, lambda rel: read(target, rel))]


def compose_files(target, files):
    return [f for f in files if scaffold_project.is_compose(f, lambda rel: read(target, rel))]


def ignored_paths(text, paths):
    """Which of paths a .gitignore with this text hides, asked from the real git without any global excludes."""
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, '.gitignore'), 'w', encoding='utf-8') as fh:
            fh.write(text)
        subprocess.run(['git', 'init', '-q', tmp], check=True, env=env, capture_output=True, timeout=30)
        # GIT_CONFIG_GLOBAL leaves the default ~/.config/git/ignore on: only this setting turns it off
        run = subprocess.run(['git', '-C', tmp, '-c', 'core.excludesFile=' + os.devnull, 'check-ignore', '--stdin', '-v',
                              '-n'], env=env, check=False, input='\n'.join(paths) + '\n', capture_output=True,
                             text=True, timeout=30)
    if run.returncode not in (0, 1):
        raise subprocess.SubprocessError(run.stderr.strip())
    ignored = set()
    for line in run.stdout.splitlines():
        source, _, path = line.partition('\t')
        pattern = source.split(':', 2)[-1]
        if source != '::' and not pattern.startswith('!'):
            ignored.add(path)
    return ignored


def pnpm_blocks_scripts(pkg, workspace):
    """pnpm's own rule: its major from packageManager, or a list that this major reads."""
    declared = DECLARED_MANAGER.match(str(pkg.get('packageManager', '')))
    major = int(declared.group(2) or 0) if declared else 0
    listed = ONLY_BUILT.search(workspace) or 'onlyBuiltDependencies' in section(pkg, 'pnpm')
    return major >= PNPM_SAFE_MAJOR or bool(listed) or (not major and bool(ALLOW_BUILDS.search(workspace)))


def scripts_gaps(target, pkg, name):
    """Install scripts of dependencies stay off: `ignore-scripts=true`, or pnpm's own rule. The pnpm flag that runs
    them all goes first: pnpm 11 and later read no ignore-scripts from .npmrc, and the standard's .npmrc has one."""
    npmrc = read(target, '.npmrc') or ''
    workspace = read(target, PNPM_WORKSPACE) or ''
    if name == 'pnpm' and (ALL_BUILDS_YAML.search(workspace) or ALL_BUILDS_NPMRC.search(npmrc)
                           or section(pkg, 'pnpm').get('dangerouslyAllowAllBuilds') is True):
        return ['`dangerouslyAllowAllBuilds`: скрипти всіх залежностей запускаються при встановленні']
    settings = [line.replace(' ', '') for line in npmrc.splitlines()]
    if [s for s in settings if s.startswith('ignore-scripts=')][-1:] == ['ignore-scripts=true']:
        return []
    if name == 'pnpm' and pnpm_blocks_scripts(pkg, workspace):
        return []
    if name == 'pnpm':  # pnpm 11 and later read only auth and registry settings from .npmrc
        return ['`packageManager` без pnpm 10+ і без `allowBuilds`: пакет може виконати свій код при встановленні']
    return ['`.npmrc` без `ignore-scripts=true`: пакет із npm може виконати свій код при встановленні']


def pinned(name, version, catalog_names):
    """An exact version, one the workspace gives, or a `catalog:` reference to an entry that was read: an entry that
    wasn't is a version nobody saw, so it counts as loose."""
    if version.startswith('catalog:'):
        return name in catalog_names
    return version.startswith('workspace:') or bool(EXACT_VERSION.match(version))


def version_gaps(target, files):
    """Exact versions in every package.json, each on its own, and in the pnpm catalog."""
    catalog = catalog_of(target)
    names = {name for name, _ in catalog}
    loose = sorted({n for n, v in dependencies(target, files) if not pinned(n, str(v), names)})
    floating = sorted({n for n, v in catalog if not EXACT_VERSION.match(v)})
    counts = ['%d у `package.json`' % len(loose)] * bool(loose)
    counts += ['%d у каталозі pnpm' % len(floating)] * bool(floating)
    if not counts:
        return []
    examples = ', '.join(safe_words(loose + floating)[:EXAMPLES])
    return ['пакетів без точної версії: %s (%s)' % (', '.join(counts), examples)]


def tsconfig_states(target, files):
    """{config: True, False or None, scaffold_project.strict_of}: each `tsconfig.json`, or every config that compiles
    when no such file does. A base is read only from the files of the project: read() follows a linked folder."""
    configs = [f for f in files if TSCONFIG.fullmatch(os.path.basename(f))
               and not SOLUTION_CONFIG.search(read(target, f) or '')]
    main = [f for f in configs if os.path.basename(f) == 'tsconfig.json'] or configs
    known = set(files)
    return {f: scaffold_project.strict_of(f, lambda rel: read(target, rel) if rel in known else None) for f in main}


def tsconfig_gaps(target, files):
    """`strict` in each config, a config for tests aside, or in the base it extends; a base from a package is a note,
    see notes()."""
    if not any(TSCONFIG.fullmatch(os.path.basename(f)) for f in files):
        return ['немає `tsconfig.json`'] if any(n == 'typescript' for n, _ in dependencies(target, files)) else []
    loose = [f for f, state in tsconfig_states(target, files).items() if state is False and not DEV_FILE.search(f)]
    return ['`%s` без `"strict": true`' % label(loose[0])] if loose else []


def node_gaps(target, pkg, versions, files):
    """Node, the manager and the check script. A package.json that can't be parsed is the only gap of that part."""
    if not pkg:
        return ['`package.json` не читається як JSON']
    found = []
    node = node_major(target)
    if node != versions['node']:
        found.append('`.nvmrc`: %s, стандарт Node %s' % ('Node ' + node if node else 'немає версії', versions['node']))
    name = manager(target, pkg)
    found += scripts_gaps(target, pkg, name)
    if not any(os.path.exists(os.path.join(target, lock)) for lock in LOCKS[name]):
        found.append('немає `%s`: версії залежностей не зафіксовані' % LOCKS[name][0])
    found += version_gaps(target, files)
    scripts = section(pkg, 'scripts')
    if 'check' not in scripts:
        found.append('немає `%s run check` (typecheck, lint, test, build разом)' % name)
    missing = [s for s in CHECK_SCRIPTS if s not in scripts and 'check' not in scripts]
    if missing:
        found.append('немає скриптів: %s' % ', '.join(missing))
    if not any(os.path.basename(f) in ESLINT_FILES for f in files):
        found.append('немає конфігурації ESLint')
    return found + tsconfig_gaps(target, files)


def unpinned(image):
    """No tag and no digest, or the tag latest; only the last part counts, a registry may have a port."""
    name = image.rsplit('/', 1)[-1]
    return '@' not in name and (':' not in name or name.endswith(':latest'))


def dockerfile_gaps(rel, text):
    """A dev image answers only for its tags: the two stages and the user are rules of what runs in production."""
    name, stages = label(rel), scaffold_project.stages(text)
    names = {stage.lower() for _, stage in stages if stage}
    found = []
    if not DEV_FILE.search(rel) and len(stages) < 2:
        found.append('`%s` в один етап: стандарт окремо збирає й окремо запускає' % name)
    if not DEV_FILE.search(rel) and scaffold_project.runs_as_root(text):
        found.append('`%s` запускає застосунок від root: потрібен `USER`' % name)
    images = [i for i, _ in stages if i.lower() != 'scratch' and i.lower() not in names and '$' not in i]
    if any(unpinned(image) for image in images):
        found.append('`%s`: образ без тега чи з latest' % name)
    return found


def dockerignore_gaps(target, files, names):
    """A build context can't be seen from here: each Dockerfile needs a .dockerignore in its folder or above it, and
    each .dockerignore must hold the lines. .git stands at the root, so a plain .dockerignore in a folder needs no line
    for it; one named after a Dockerfile may serve a build from the root."""
    ignores = [f for f in files if f.endswith('.dockerignore')]
    folders = {os.path.dirname(f) for f in ignores}
    bare = [f for f in names if not any(not d or f.startswith(d + os.sep) for d in folders)]
    found = ['немає `.dockerignore` для `%s`: `.env*` і `.git` потраплять в образ' % named(bare)] if bare else []
    for rel in ignores:
        no_git = os.path.dirname(rel) and os.path.basename(rel) == '.dockerignore'
        needs = {n: rx for n, rx in DOCKERIGNORE_NEEDS.items() if not (no_git and n == '.git')}
        lines = [line.strip() for line in (read(target, rel) or '').splitlines()]
        lacks = [n for n, rx in needs.items() if not any(re.fullmatch(rx, line) for line in lines)]
        if lacks and read(target, rel) is not None:  # unread_gaps names the rest
            found.append('`%s` без: %s' % (label(rel), ', '.join(lacks)))
    return found


def docker_gaps(target, files):
    names = dockerfiles(target, files)
    if not names:
        return ['немає `Dockerfile`']
    found = []
    for rel in names:
        text = read(target, rel)
        if text is not None:  # unread_gaps names the rest
            found += dockerfile_gaps(rel, text)
    return found + dockerignore_gaps(target, files, names)


def compose_file_gaps(name, text):
    found = []
    images = re.findall(r'^\s+image:\s*["\']?([^\s"\']+)', text, re.M)
    if any(unpinned(image) for image in images if '$' not in image):
        found.append('`%s`: образ без тега чи з latest' % name)
    ports = '|'.join(DB_PORTS)
    short = re.search(r'^\s+-\s*["\']?(?!127\.0\.0\.1:)(?:[\d.:$\{\}\w-]*:)?(%s)["\']?\s*$' % ports, text, re.M)
    long = re.search(r'^[\s-]+target:\s*["\']?(%s)["\']?\s*$' % ports, text, re.M) and 'host_ip: 127.0.0.1' not in text
    if short or long:
        found.append('`%s`: порт БД відкритий назовні, стандарт лише `127.0.0.1:`' % name)
    if re.search(r'^\s+image:\s*\S*postgres', text, re.M) and 'healthcheck:' not in text:
        found.append('`%s`: Postgres без `healthcheck`' % name)
    return found


def compose_gaps(target, files):
    """Each file answers for its images, ports and healthcheck. `restart` and the log limit belong to the set, an
    overlay needs neither; a file for local work or tests proves nothing for them."""
    names = compose_files(target, files)
    if not names:
        return ['немає `docker-compose.yml`']
    texts = {rel: read(target, rel) for rel in names}
    readable = {rel: text for rel, text in texts.items() if text is not None}  # unread_gaps names the rest
    if not readable:
        return []
    production = [text for rel, text in readable.items() if not DEV_FILE.search(rel)]
    joined = '\n'.join(production or readable.values())
    where = '`%s`' % label(names[0]) if len(names) == 1 else 'Compose-файли'
    found = []
    if not re.search(r'^\s+restart:', joined, re.M):
        found.append('%s без `restart`' % where)
    if not re.search(r'^\s+max-size:', joined, re.M):
        found.append('%s без логів з `max-size`' % where)
    for rel, text in readable.items():
        found += compose_file_gaps(label(rel), text)
    return found


def repo_gaps(target, files):
    found = []
    if not os.path.exists(os.path.join(target, 'README.md')):
        found.append('немає `README.md`')
    if not any(os.path.basename(f) == '.env.example' for f in files):
        found.append('немає `.env.example`')
    ignore = read(target, '.gitignore')
    if ignore is None:
        return found + ['немає `.gitignore`: секрети й дампи можуть потрапити в git']
    try:
        hidden = ignored_paths(ignore, SECRET_PATHS)
    except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired) as e:
        return found + ['`.gitignore` не перевірено, git: %s' % e]
    lacks = [p for p in SECRET_PATHS if p not in hidden]
    if lacks:
        found.append('`.gitignore` не ховає: %s' % ', '.join(lacks))
    return found


def read_by_rules(target, rel):
    """A file some rule reads, or a folder listed because it wasn't entered."""
    name = os.path.basename(rel)
    return (rel in ROOT_FILES or name == 'package.json' or rel.endswith(READ_SUFFIXES)
            or bool(TSCONFIG.fullmatch(name) or dockerfiles(target, [rel])) or os.path.isdir(os.path.join(target, rel)))


def unread_gaps(target, files):
    """read() gives nothing for a link or a file it may not open, so what the other checks say of it is not about it.
    A package.json in a folder that can't be parsed counts no dependency; the root's is a gap of its own."""
    unread = [f for f in files if read_by_rules(target, f) and (read(target, f) is None or (
        f != 'package.json' and os.path.basename(f) == 'package.json'
        and scaffold_project.json_object(read(target, f)) is None))]
    line = 'не прочитано (посилання чи немає доступу), тож не перевірено: %s'
    return [line % named(unread)] if unread else []


def gaps(target, versions):
    """One line per gap, in the order of the report."""
    pkg, files = package_of(target), scaffold_project.project_files(target)
    node = [] if pkg is None else node_gaps(target, pkg, versions, files)
    return unread_gaps(target, files) + node + repo_gaps(target, files) + docker_gaps(target, files) \
        + compose_gaps(target, files)


def notes(target, pkg, files):
    """What the owner should know that is no gap: what stayed unchecked, and a package manager the project chose."""
    found = []
    if pkg is None:
        found.append('перевірки Node пропущено: у корені немає `package.json`')
    elif manager(target, pkg) != 'pnpm':
        found.append('менеджер %s, стандарт pnpm: перехід окремою задачею лише за рішенням власника, не розрив'
                     % manager(target, pkg))
    inherited = [f for f, state in tsconfig_states(target, files).items() if state is None]
    if inherited:
        found.append('`strict` не перевірено, база поза файлами проєкту: %s' % named(inherited))
    if len(files) >= scaffold_project.MAX_FILES:
        found.append('огляд проєкту зупинився на %d файлах: що далі, не перевірено' % len(files))
    return found
