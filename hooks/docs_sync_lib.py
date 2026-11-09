"""docs-sync, shared part (stdlib, 3.9+): what is mirrored from a project, the registry of projects and their docs
(registry.tsv and the REGISTRY.md made from it) and the hook keys of a connected project. docs_sync.py,
docs_sync_repo.py and docs_sync_report.py import it.
Mirrored from the main folder of a project: docs/ and _internal/ with no tracked file and no repo of their own and the
STATUS*.md files of .claude/state (outside git in every project through the global excludes); never hidden files,
SKIP_DIRS, key files (SKIP_SUFFIXES, SKIP_PREFIXES), bytecode or a file over MAX_FILE_B. doc-reminder.py (local_docs)
counts docs outside git by the same rule, with two differences on purpose: a folder reached through a link or with a
repo of its own is not mirrored here (a link may lead anywhere; an own repo is a copy already).
"""
import collections
import errno
import os
import re
import shlex
import stat
import subprocess
import time
import urllib.parse

SOURCES = ('docs', '_internal')
STATE = os.path.join('.claude', 'state')
STATUS_RE = re.compile(r'STATUS.*\.md')   # the only files of STATE that are mirrored, at its top
SKIP_DIRS = frozenset(('node_modules', 'graphify-out', '__pycache__'))
SKIP_SUFFIXES = ('.pyc', '.pem', '.key', '.p12', '.pfx', '.p8', '.ppk', '.jks', '.keystore', '.kdbx', '.gpg', '.ovpn',
                 '.env')
SKIP_PREFIXES = ('id_rsa', 'id_dsa', 'id_ecdsa', 'id_ed25519')   # ssh keys by their usual names
# what gitleaks does not read: the paths of its default allowlist (images, fonts, office files, pdf, lock files; another
# gitleaks version may differ a little) and what git sees as binary, which UNSCANNED_RE names by format and
# BINARY_PEEK_B finds by content. Owner's decision 04.11.2026: they are mirrored all the same and counted in the done
# line and the registry note
UNSCANNED_RE = re.compile(
    r'\.(bmp|gif|jpe?g|png|svg|tiff?|webp|heic|ico|eot|[ot]tf|woff2?|docx?|xlsx?|pptx?|od[tsp]|pdf|zip|t?gz|7z|rar|bin|'
    r'exe|dll|mp[34]|mov|wav)$|(^|/)(gitleaks\.toml|package-lock\.json|npm-shrinkwrap\.json|pnpm-lock\.yaml|yarn\.lock|'
    r'deno\.lock|Pipfile\.lock|poetry\.lock|go\.(mod|sum|work(\.sum)?)|gradle\.lockfile|gradlew(\.bat)?|mvnw(\.cmd)?)$|'
    r'(^|/)vendor/', re.I)
BINARY_PEEK_B = 8000   # git sees a file with a NUL in its first 8000 bytes as binary: no diff, nothing to scan
MAX_FILE_B = int(os.environ.get('DOCS_SYNC_MAX_FILE_B') or 50 * 1024 * 1024)   # GitHub warns at 50 MB, refuses 100 MB
MAX_FILE_MB = MAX_FILE_B // 2 ** 20
MAX_FILES = 20000      # per folder; more is not a docs folder
GIT_TIMEOUT_S = 60     # docs_sync.py sets less for a hook, which holds a commit or a push of a project
SHOW_NAMES = 8         # names in a line, then "+N"
REGISTRY_TSV, REGISTRY_MD = 'registry.tsv', 'REGISTRY.md'
COLUMNS = ('folder', 'path', 'mode', 'docs', 'repo', 'since', 'note')
MODES = {'mirror': 'дзеркало', 'outside': 'поза git, не підключено', 'own-repo': 'власний репо', 'in-git': 'у git',
         'no-git': 'без git', 'off': 'вимкнено'}
# what git exports to a hook for its own repo, or a caller for any repo: a git run in the docs repo must not take it
# (GIT_DIR or GIT_INDEX_FILE would send the commit into the project; -c, GIT_CONFIG and GIT_CONFIG_COUNT with its
# GIT_CONFIG_KEY_n of a session or an IDE would add or switch off settings there)
GIT_LOCAL = ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES',
             'GIT_COMMON_DIR', 'GIT_PREFIX', 'GIT_IMPLICIT_WORK_TREE', 'GIT_NAMESPACE', 'GIT_QUARANTINE_PATH',
             'GIT_CONFIG', 'GIT_CONFIG_PARAMETERS', 'GIT_CONFIG_COUNT', 'GIT_SHALLOW_FILE', 'GIT_GRAFT_FILE',
             'GIT_REPLACE_REF_BASE', 'GIT_NO_REPLACE_OBJECTS', 'GIT_REFLOG_ACTION')
# git commit exports the author of the project's commit to its hooks: a hook drops these, a command keeps the owner's
IDENTITY = ('GIT_AUTHOR_NAME', 'GIT_AUTHOR_EMAIL', 'GIT_AUTHOR_DATE', 'GIT_COMMITTER_NAME', 'GIT_COMMITTER_EMAIL',
            'GIT_COMMITTER_DATE')
ENV = dict({k: v for k, v in os.environ.items() if k not in GIT_LOCAL and not k.startswith(
    ('GIT_CONFIG_KEY_', 'GIT_CONFIG_VALUE_'))}, GIT_LITERAL_PATHSPECS='1')   # a folder name with * or [ is no glob
HOME = os.path.expanduser('~')
HOOKS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.expanduser(os.environ.get('DOCS_SYNC_REPO') or '~/project-docs'))
PROJECTS = os.path.abspath(os.path.expanduser(os.environ.get('DOCS_SYNC_PROJECTS') or '~/WebstormProjects'))
BRANCH = 'main'
# in .git of the docs repo, left by a git killed on its way: a commit stops on the first three, a push on the last
COMMIT_LOCKS = ('index.lock', 'HEAD.lock', os.path.join('refs', 'heads', BRANCH + '.lock'))
PUSH_LOCK = os.path.join('refs', 'remotes', 'origin', BRANCH + '.lock')
KEYS = (('docs-sync', 'post-commit'), ('docs-sync-push', 'pre-push'))   # git shows no event to a hook: a name each
NO_FILE = "echo '%s: %s (no hook file)' >&2; :"   # git appends the hook's arguments to the command: ":" takes them
BAD_CHARS = re.compile('[\x00-\x1f\x7f\x85\u2028\u2029]')   # each would split a row of the registry or a line of the log
README = """# Документація проєктів

Дзеркало документів, які проєкти тримають поза git: `docs/` і `_internal/` без трекнутих файлів, `STATUS*.md` з
`.claude/state`. Джерело правди лишається в теці проєкту. Тут нічого не правити: наступна синхронізація перезапише.

- Після коміту чи перед пушем у підключеному проєкті хук `docs-sync` копіює документи основної теки проєкту сюди,
  комітить і пушить у фоні. Копії у worktree проєкту це чернетки, вони сюди не йдуть.
- Реєстр проєктів і їхньої документації: `REGISTRY.md`, його генерує `docs-sync.sh` з `registry.tsv`.
- Підключити проєкт: `~/.claude/hooks/docs-sync.sh connect ~/WebstormProjects/<тека>`, а `connect --dry-run` спершу
  показує, що піде. Лише рядок реєстру (документи в git, у власному репо, тека без git): `register`. Від'єднати:
  `disconnect`, копія лишається. Синхронізувати зараз: `sync`. Запушити зараз: `push`.
- Не копіюються приховані файли, `node_modules`, `graphify-out`, `__pycache__`, `*.pyc`, ключі (`*.pem`, `*.key`,
  `*.p12`, `*.pfx`, `*.p8`, `*.ppk`, `*.jks`, `*.keystore`, `*.kdbx`, `*.gpg`, `*.ovpn`, `*.env`, `id_rsa*` та інші
  ключі ssh) і файли понад 50 МБ.
- Кожен коміт і кожен пуш звідси проходять скан секретів gitleaks з правилами commit-leaks: без чистого вердикту
  нічого не комітиться і не пушиться. Сканер знаходить токени відомих форматів у тексті, а зображень, docx, xlsx, pdf,
  lock-файлів, файлів, які git вважає бінарними, і паролів, записаних словами, не читає. Такі файли теж копіюються
  (рішення власника 04.11.2026), їхню кількість показує примітка в `REGISTRY.md`.
- Збої: `~/.claude/logs/docs-sync.err` і рядок `docs repo:` у `scripts/doctor.sh` бази налаштувань.
"""


class SyncError(Exception):
    """A failure with a short reason (a folder name at most, never file contents): one stderr and one log line."""


class TimedOut(SyncError):
    """A git call or the whole hook over its time: the git it waited for is killed and may leave a lock."""


def subcommand(args):
    """The git command of args, after any -c key=value."""
    it = iter(args)
    for a in it:
        if a == '-c':
            next(it, None)
        elif not a.startswith('-'):
            return a
    return '?'


def git(args, cwd, check=True, env=None, timeout=None):
    limit = timeout or GIT_TIMEOUT_S
    try:
        p = subprocess.run(['git', '-C', cwd] + list(args), env=env or ENV, capture_output=True, encoding='utf-8',
                           errors='replace', timeout=limit)
    except subprocess.TimeoutExpired:
        raise TimedOut('git %s took over %g s in %s' % (subcommand(args), limit, show(cwd))) from None
    if check and p.returncode:
        raise SyncError('git %s rc=%d' % (subcommand(args), p.returncode))
    return p


def show(path):
    return '~' + path[len(HOME):] if path == HOME or path.startswith(HOME + os.sep) else path


def arg(path):
    """path for a command line: ~/ outside the quotes, so that the shell still expands it."""
    shown = show(path)
    return '~/' + shlex.quote(shown[2:]) if shown.startswith('~/') else shlex.quote(shown)


def cell(text):
    return BAD_CHARS.sub(' ', text)


def errno_name(e):
    return errno.errorcode.get(e.errno or 0, type(e).__name__)


def hook_command(event):
    """What connect writes as hook.<name>.command for event: the shim of this copy, or one stderr line when it is gone
    (a pre-push still reads the refs git writes to it)."""
    shim = shlex.quote(os.path.join(HOOKS, 'docs-sync.sh'))
    return 'test -x %s && exec %s hook %s; %s%s' % (shim, shim, event, 'cat >/dev/null; ' if event == 'pre-push' else '',
                                                   NO_FILE % ('docs-sync', 'the docs are not mirrored'))


def main_folder(top):
    """The main worktree's folder of the repo at top: the docs of a worktree are drafts of those in the main folder."""
    common = os.path.normpath(os.path.join(top, git(['rev-parse', '--git-common-dir'], top).stdout.strip()))
    if os.path.basename(common) != '.git':
        raise SyncError('a bare repo or a submodule')
    return os.path.dirname(common)


def check_name(path):
    if BAD_CHARS.search(path):
        raise SyncError('a control or line separator character in the folder path')


def tracked(main, rel):
    return bool(git(['ls-files', '-z', '--', rel], main).stdout)


def sources(main):
    """[(path relative to main, is_flat)] of what is mirrored; is_flat: only the STATUS*.md files at its top. A folder
    reached through a link at any level of it is not mirrored."""
    real, out = os.path.realpath(main), []
    for name in SOURCES:
        p = os.path.join(main, name)
        if os.path.isdir(p) and os.path.realpath(p) == os.path.join(real, name) and not os.path.lexists(
                os.path.join(p, '.git')) and not tracked(main, name):
            out.append((name, False))
    st = os.path.join(main, STATE)
    if os.path.isdir(st) and os.path.realpath(st) == os.path.join(real, STATE) and not tracked(main, STATE) and any(
            STATUS_RE.fullmatch(f) for f in os.listdir(st)):
        out.append((STATE, True))
    return out


def unit_label(rel, is_flat):
    return rel + ('/STATUS*.md' if is_flat else '/')


def unscanned(path, rel):
    """True for the file at path (rel: its path in a unit or in the docs repo) when gitleaks does not read it."""
    if UNSCANNED_RE.search(rel):
        return True
    try:
        with open(path, 'rb') as fh:
            return b'\0' in fh.read(BINARY_PEEK_B)
    except OSError:   # not read here: its copy fails and names it
        return False


def walk(root, is_flat=False, what='source'):
    """({relative path: (size, mtime_ns)}, [paths over MAX_FILE_B]) of the files mirrored from root (what: source or
    mirror, for the error). A folder it cannot read stops the walk: files missing from it would have their copies
    deleted. A file gone between the listing and its lstat (an editor's temporary file) is left out."""
    def unreadable(e):
        rel = os.path.relpath(e.filename, root) if e.filename else '?'
        raise SyncError('the %s %s could not be read (%s)' % (
            what, cell(os.path.basename(root) + ('' if rel == '.' else '/' + rel)), errno_name(e)))

    files, big = {}, []
    for dp, dns, fns in os.walk(root, onerror=unreadable):
        dns[:] = [] if is_flat else sorted(d for d in dns if not d.startswith('.') and d not in SKIP_DIRS)
        for f in sorted(fns):
            low = f.lower()
            if f.startswith('.') or low.endswith(SKIP_SUFFIXES) or low.startswith(SKIP_PREFIXES) or (
                    is_flat and not STATUS_RE.fullmatch(f)):
                continue
            try:
                st = os.lstat(os.path.join(dp, f))
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(st.st_mode):   # a link may lead anywhere
                continue
            rel = os.path.relpath(os.path.join(dp, f), root)
            if st.st_size > MAX_FILE_B:
                big.append(rel)
                continue
            files[rel] = (st.st_size, st.st_mtime_ns)
            if len(files) > MAX_FILES:
                raise SyncError('over %d files in %s' % (MAX_FILES, os.path.basename(root)))
    return files, big


def remote(path):
    """origin of the repo at path as host/owner/name, with no user, password, query or fragment; 'no remote' without
    one. All up to the last @ goes first: a password may hold a / or an @."""
    p = git(['remote', 'get-url', 'origin'], path, check=False)
    url = p.stdout.strip()
    if p.returncode or not url:
        return 'no remote'
    if '://' in url:
        scheme, rest = url.split('://', 1)
        u = urllib.parse.urlsplit('%s://%s' % (scheme, re.split(r'[?#]', rest, maxsplit=1)[0].rsplit('@', 1)[-1]))
        try:
            port = ':%d' % u.port if u.port else ''
        except ValueError:
            port = ''
        url = (u.hostname or '') + port + u.path
    elif not url.startswith(('/', '.', '~')):   # user@host:owner/name; a path on this Mac stays as it is
        m = re.match(r'([^:/]+):(.*)\Z', url.rsplit('@', 1)[-1])
        url = '%s/%s' % m.groups() if m else url.rsplit('@', 1)[-1]
    return re.sub(r'\.git/?\Z', '', url)


def describe(path):
    """(mode, docs, repo) of a project folder for its registry row: 'outside' when it has docs to mirror."""
    if not os.path.isdir(os.path.join(path, '.git')):
        return 'no-git', ', '.join(n + '/' for n in SOURCES if os.path.isdir(os.path.join(path, n))) or '-', 'no git'
    mirrored = [unit_label(rel, is_flat) for rel, is_flat in sources(path)]
    own = ['%s/ (own repo %s)' % (n, remote(os.path.join(path, n))) for n in SOURCES
           if os.path.isdir(os.path.join(path, n, '.git'))]
    in_git = ['%s/ in git' % n for n in SOURCES if os.path.isdir(os.path.join(path, n)) and tracked(path, n)]
    mode = 'own-repo' if own else 'outside' if mirrored else 'in-git'
    return mode, ', '.join(mirrored + own + in_git) or 'README only', remote(path)


def project(path):
    """The main folder of the repo at path (a worktree leads to its main folder)."""
    p = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(p):
        raise SyncError('%s: no such folder' % path)
    if not os.path.lexists(os.path.join(p, '.git')):
        raise SyncError('%s: no git here (register it instead)' % show(p))
    main = main_folder(p)
    check_name(main)
    return main


def row_of(rows, folder, main, mode, docs, repo):
    """The registry row of folder at main. A connected folder of that name elsewhere stops it while it is there; a
    folder that moved takes its row over."""
    old = rows.get(folder)
    if old and os.path.realpath(old['path']) != os.path.realpath(main) and old['mode'] == 'mirror' and \
            os.path.isdir(old['path']):
        raise SyncError('%s is in the registry with another folder: %s (docs-sync.sh disconnect it first)' % (
            folder, show(old['path'])))
    since = old['since'] if old else time.strftime('%Y-%m-%d')
    return dict(folder=folder, path=main, mode=mode, docs=docs, repo=repo, since=since, note='')


def connected(rows, main):
    folder = os.path.basename(main)
    r = rows.get(folder)
    if not r or r['mode'] != 'mirror' or os.path.realpath(r['path']) != os.path.realpath(main):
        raise SyncError('%s is not connected in %s' % (folder, show(REPO)))
    return folder


def set_note(rows, folder, tally):
    """The registry note of a mirror: the files gitleaks does not read (owner's decision 04.11.2026) and the files over
    the cap. True when it changed."""
    parts = ['без скану: %d (%s)' % (len(tally.unscanned), kinds(tally.unscanned))] if tally.unscanned else []
    parts += ['понад %d МБ не скопійовано: %d' % (MAX_FILE_MB, len(tally.big))] if tally.big else []
    note = '; '.join(parts)
    if rows[folder]['note'] == note:
        return False
    rows[folder]['note'] = note
    return True


def set_docs(rows, folder, main, tally):
    """The docs of the row again when the units it names are not those of this sync (a copy went into git, a unit came
    later): True when it changed. A sync that stopped after a copy went leaves the row to the next one."""
    labels = {unit_label(rel, rel == STATE) for rel in SOURCES + (STATE,)}
    named = [part for part in rows[folder]['docs'].split(', ') if part in labels]
    if named == [unit_label(rel, is_flat) for rel, is_flat in tally.units]:
        return False
    docs = describe(main)[1]
    if rows[folder]['docs'] == docs:
        return False
    rows[folder]['docs'] = docs
    return True


def read_registry(repo):
    path = os.path.join(repo, REGISTRY_TSV)
    if not os.path.isfile(path):
        if not os.path.isdir(os.path.join(repo, '.git')):
            raise SyncError('no docs repo at %s (docs-sync.sh init)' % show(repo))
        raise SyncError('%s is missing in %s (git -C %s checkout -- %s)' % (REGISTRY_TSV, show(repo), arg(repo),
                                                                          REGISTRY_TSV))
    try:
        with open(path, encoding='utf-8') as fh:
            lines = [ln.rstrip('\r') for ln in fh.read().split('\n') if ln.strip('\r')]   # a hand edit may leave an empty one
    except ValueError:
        raise SyncError('%s is not UTF-8 (git -C %s diff -- %s shows the change)' % (REGISTRY_TSV, arg(repo),
                                                                                   REGISTRY_TSV)) from None
    if not lines or tuple(lines[0].split('\t')) != COLUMNS:
        raise SyncError('%s: an unknown header' % REGISTRY_TSV)
    rows = {}
    for ln in lines[1:]:
        cells = ln.split('\t')
        if len(cells) != len(COLUMNS):
            raise SyncError('%s: a row of %d cells' % (REGISTRY_TSV, len(cells)))
        rows[cells[0]] = dict(zip(COLUMNS, cells))
    return rows


def write_atomic(path, text):
    with open(path + '.tmp', 'w', encoding='utf-8') as fh:
        fh.write(text)
    os.replace(path + '.tmp', path)


def registry_md(rows):
    """REGISTRY.md of the rows, in their order."""
    md = lambda s: cell(s).replace('|', '\\|')   # noqa: E731
    table = ['| Тека | Режим | Документи | Репо проєкту | З | Примітка |', '|---|---|---|---|---|---|'] + [
        '| %s |' % ' | '.join(md(x) for x in (r['folder'], MODES.get(r['mode'], r['mode']), r['docs'], r['repo'],
                                                r['since'], r['note'])) for r in rows]
    return '\n'.join([
        '# Реєстр проєктів і документації', '',
        'Генерує `docs-sync.sh` з `registry.tsv`, вручну не правити. Режими: %s.' % '; '.join(
            '%s (%s)' % (MODES[m], what) for m, what in (
                ('mirror', 'копія тут, хук post-commit і pre-push'), ('outside', 'документи поза git, копії немає'),
                ('own-repo', 'документи у своєму репо'), ('in-git', 'документи в репо проєкту'),
                ('no-git', 'git-хук неможливий'), ('off', 'копія лишилась, хука немає'))), ''] + table) + '\n'


def write_registry(repo, rows):
    order = sorted(rows, key=str.lower)
    write_atomic(os.path.join(repo, REGISTRY_TSV), '\n'.join(
        ['\t'.join(COLUMNS)] + ['\t'.join(cell(rows[k][c]) for c in COLUMNS) for k in order]) + '\n')
    write_atomic(os.path.join(repo, REGISTRY_MD), registry_md([rows[k] for k in order]))


def names(items):
    return ', '.join(items[:SHOW_NAMES]) + (' (+%d)' % (len(items) - SHOW_NAMES) if len(items) > SHOW_NAMES else '')


def kinds(paths, top=4):
    """'png 84, docx 13' of the file types of paths: the extension, or the name of a file with none."""
    return ', '.join('%s %d' % kv for kv in collections.Counter(
        cell((os.path.splitext(p)[1][1:] or os.path.basename(p)).lower()) for p in paths).most_common(top))


def keys_of(path):
    """{key: value} of the docs-sync hook keys in the .git/config of the repo at path."""
    out = git(['config', '--local', '--get-regexp', r'^hook\.docs-sync(-push)?\.'], path, check=False).stdout
    return dict(ln.split(' ', 1) for ln in out.splitlines() if ' ' in ln)


def plan_text(folder, main):
    """What connect would mirror from main, written nowhere."""
    parts = []
    for rel, is_flat in sources(main):
        root = os.path.join(main, rel)
        files, big = walk(root, is_flat)
        unread = [r for r in files if unscanned(os.path.join(root, r), r)]
        parts.append('%s %d files, %.1f MB%s%s' % (
            unit_label(rel, is_flat), len(files), sum(s for s, _ in files.values()) / 2 ** 20,
            ', not scanned %d (%s)' % (len(unread), kinds(unread)) if unread else '',
            ', over %d MB %d' % (MAX_FILE_MB, len(big)) if big else ''))
    return 'dry run, nothing written: %s to %s: %s; then the hook keys in %s' % (
        folder, show(os.path.join(REPO, folder)), '; '.join(parts), show(os.path.join(main, '.git', 'config')))
