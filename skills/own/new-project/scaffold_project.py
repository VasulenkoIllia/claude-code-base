"""How the gap report sees an existing project: which files are the project's, which of them are a Dockerfile or a
Compose file, and readers of their text by shape. The skill has no YAML parser and a tsconfig is JSON with comments, so
each reader takes the forms projects use and says what it can't tell: a form the catalog reader doesn't take gives no
entry, a config outside the project gives None.
"""
import collections
import json
import os
import re

from scaffold_target import run_git

# Dependencies, output, tools, CI and the client's brief. What git ignores stays out as well, see ignored_by_git
SKIP_DIRS = {'node_modules', 'dist', 'coverage', 'vendor', 'venv', '__pycache__', 'brief', '.git', '.claude',
             '.devcontainer', '.idea', '.vscode', '.venv', '.next', '.turbo', '.cache', '.github', '.gitlab',
             '.circleci', '.buildkite'}
MAX_FILES = 50_000
DOCKERFILE = re.compile(r'([\w.-]+[._-])?(docker|container)file([._-][\w.-]+)?', re.I)
NOT_DOCKERFILE = re.compile(r'\.(dockerignore|containerignore|md|txt|json|ya?ml|tmpl|tpl|template|example|j2)$', re.I)
COMPOSE_NAME = re.compile(r'((docker[._-])?compose([._-][\w.-]+)?|[\w.-]+[._-]compose)\.ya?ml', re.I)
COMPOSE_TOP = re.compile(r'^services:', re.M)
COMPOSE_SERVICE = re.compile(r'^[ \t]+(image|build):', re.M)  # [ \t]: under re.M \s runs over blank lines, O(n²)
CATALOG_BLOCK = re.compile(r'catalogs?:\s*(#.*)?')
# Linear: the spaces after the colon end at a non-space and the version is greedy. A lazy version between two runs of
# spaces took cubic time on a line with spaces and a quote inside the version. A version without a closing quote loses
# its trailing spaces in catalog_entries, one with it keeps them
CATALOG_ENTRY = re.compile(r'''\s+["']?([^"':\s]+)["']?:\s+(?!\s)["']?([^"'#]*)(["']\s*)?(#.*)?''')
FROM_LINE = re.compile(r'^FROM\s+(?:--\S+\s+)*(\S+)(?:\s+AS\s+(\S+))?', re.M | re.I)
# An image built to run without root needs no USER; only its own name counts, not a registry's or a folder's
NON_ROOT_IMAGE = re.compile(r'unprivileged|nonroot|rootless', re.I)
LINE_COMMENT = re.compile(r'//.*')
STRICT = re.compile(r'"strict"\s*:\s*(true|false)')
EXTENDS = re.compile(r'"extends"\s*:\s*("[^"]*"|\[[^\]]*\])')
QUOTED = re.compile(r'"([^"]+)"')
UNSET = 'unset'


def ignored_by_git(target):
    """What git ignores, a whole folder as one entry: a folder kept out of git, like `_internal/`, is not the project.
    Nothing without a repository of its own or when git can't say: the report then shows more, not less."""
    if not os.path.lexists(os.path.join(target, '.git')):
        return set()
    try:
        run = run_git(target, 'ls-files', '-z', '--others', '--ignored', '--exclude-standard', '--directory')
    except UnicodeDecodeError:  # a name in no encoding
        return set()
    return {name.rstrip('/') for name in run.stdout.split('\0') if name} if run.returncode == 0 else set()


def project_files(target):
    """Paths from the project's root, shallow ones first, so MAX_FILES cuts the deepest. A link, a special file and a
    folder that can't be read stay in the list: the report's read() refuses them and unread_gaps names them."""
    ignored = ignored_by_git(target)
    found, folders = [], collections.deque([''])
    while folders and len(found) < MAX_FILES:
        folder = folders.popleft()
        try:
            entries = sorted(os.scandir(os.path.join(target, folder)), key=lambda entry: entry.name)
        except OSError:
            found.append(folder)
            continue
        for entry in entries:
            rel = os.path.join(folder, entry.name)
            is_folder = entry.is_dir(follow_symlinks=False)
            if (is_folder and entry.name in SKIP_DIRS) or rel in ignored:
                continue
            (folders if is_folder else found).append(rel)
    return found


def json_object(text):
    """The object a JSON text holds, None for anything else, thousands of nested brackets too."""
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def is_dockerfile(rel, read_text):
    """By its name and a FROM line: `src/dockerfile.ts` is code. A file that can't be read stays, the report names it.
    """
    if not DOCKERFILE.fullmatch(os.path.basename(rel)) or NOT_DOCKERFILE.search(rel):
        return False
    text = read_text(rel)
    return text is None or bool(stages(text))


def is_compose(rel, read_text):
    """By its name, as an overlay may set `restart` alone; or a YAML under another name with services that have an image
    or a build. A CI config has that shape too: it has a dot in its name or folder."""
    if COMPOSE_NAME.fullmatch(os.path.basename(rel)):
        return True
    if not rel.endswith(('.yml', '.yaml')) or any(part.startswith('.') for part in rel.split(os.sep)):
        return False
    text = read_text(rel) or ''
    return bool(COMPOSE_TOP.search(text) and COMPOSE_SERVICE.search(text))


def catalog_entries(text):
    """(name, version) of the catalogs of a pnpm-workspace.yaml, in file order, read by indent: a name may stand in
    several catalogs."""
    found, inside = [], False
    for line in text.splitlines():
        if line.lstrip().startswith('#'):
            continue
        if line[:1].strip():
            inside = bool(CATALOG_BLOCK.fullmatch(line))
        entry = CATALOG_ENTRY.fullmatch(line) if inside else None
        version = entry and (entry.group(2) if entry.group(3) else entry.group(2).rstrip())
        if version:
            found.append((entry.group(1), version))
    return found


def stages(text):
    """(image, name) of each FROM of a Dockerfile."""
    return FROM_LINE.findall(text)


def runs_as_root(text):
    """The USER of the last stage or of the earlier stage it is built on; with none, the image decides."""
    froms = list(FROM_LINE.finditer(text))
    names = {m.group(2).lower(): i for i, m in enumerate(froms) if m.group(2)}
    index, image = len(froms) - 1, ''
    while index >= 0:
        stage, end = froms[index], froms[index + 1].start() if index + 1 < len(froms) else len(text)
        users = re.findall(r'^USER\s+(\S+)', text[stage.end():end], re.M | re.I)
        if users:
            return bool(re.match(r'(root|0)\b', users[-1], re.I))
        image = stage.group(1)
        parent = names.get(image.lower(), -1)
        index = parent if parent < index else -1  # a stage can't be built on itself or on a later one
    return not NON_ROOT_IMAGE.search(image.rsplit('/', 1)[-1])


def strict_chain(rel, read_text, seen):
    """What the config or what it extends says of `strict`: True, False, UNSET, or None when the answer may lie outside
    the project's files."""
    text = read_text(rel)
    if text is None or rel in seen:
        return None
    text = LINE_COMMENT.sub('', text)
    own = STRICT.search(text)
    if own:
        return own.group(1) == 'true'
    parents = EXTENDS.search(text)
    for parent in reversed(QUOTED.findall(parents.group(1) if parents else '')):  # the last one wins, as in tsc
        path = os.path.normpath(os.path.join(os.path.dirname(rel), parent))
        state = None
        if parent.startswith('.') and not path.startswith(os.pardir):
            state = strict_chain(path if path.endswith('.json') else path + '.json', read_text, seen + (rel,))
        if state is not UNSET:
            return state
    return UNSET


def strict_of(rel, read_text):
    """True or False as the config or what it extends sets `strict`, False when none of them does. None when that lies
    outside the project's files: a base from a package, a path that leaves the project, a file that can't be read, a
    loop. read_text takes a path from the project's root."""
    state = strict_chain(rel, read_text, ())
    return False if state is UNSET else state
