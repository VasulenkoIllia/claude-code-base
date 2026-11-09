"""The folder /new-project runs in (scaffold.py --inspect, --move-ide, --init-git): new, a template an IDE left, or a real
project.

A template is moved whole into a backup folder on the same volume and never deleted; a failure midway moves it back.
All git in such a folder goes through run_git.
"""
import collections
import datetime
import os
import subprocess
import unicodedata

from brief_tree import BAD_CATEGORIES
from scaffold_render import ScaffoldError

# .claude: Claude Code writes settings.local.json there when a permission is answered "always allow";
# brief: the client's materials for a start from a brief (outside git and the Docker image)
ALLOWED_IN_TARGET = {'.git', '.idea', '.claude', '.DS_Store', 'brief'}
# An IDE template is a few files and at most the commit the IDE made; a folder past either bound is a real project.
# The owner sees the list before anything moves, so a wrong guess costs one answer
IDE_MAX_FILES = 40
IDE_MAX_COMMITS = 1
DEPENDENCY_DIRS = {'node_modules'}
BACKUP_ROOT = os.path.join('~', 'claude-backups')
GIT_TIMEOUT_S = 15
NOT_A_REPO = 'not a git repository'
Folder = collections.namedtuple('Folder', 'kind entries files commits')


def run_git(target, *args):
    """git in the target's own repository, without the optional locks that would disturb a running IDE and without the
    hooks and the monitor a folder from elsewhere may bring in its .git."""
    env = dict(os.environ, GIT_OPTIONAL_LOCKS='0', LC_ALL='C')  # C: NOT_A_REPO is matched as English text
    guarded = ['git', '-C', target, '-c', 'core.hooksPath=' + os.devnull, '-c', 'core.fsmonitor=false']
    try:
        return subprocess.run(guarded + list(args), capture_output=True, text=True, env=env, timeout=GIT_TIMEOUT_S,
                              check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ScaffoldError('git in %s: %s' % (target, e)) from e


def has_repo(target):
    """The target's own .git: a folder inside another repository has none of its commits."""
    return os.path.lexists(os.path.join(target, '.git'))


def commit_count(target):
    if not has_repo(target):
        return 0
    run = run_git(target, 'rev-list', '--count', '--all')
    if run.returncode != 0:
        raise ScaffoldError('git rev-list in %s: %s' % (target, run.stderr.strip()))
    return int(run.stdout.strip() or 0)


def tracked(target, where):
    """The repository around the target tracks files under where; no repository, no files."""
    run = run_git(target, 'ls-files', '--', where)
    if run.returncode != 0 and NOT_A_REPO not in run.stderr:
        raise ScaffoldError('git ls-files in %s: %s' % (target, run.stderr.strip()))
    return bool(run.stdout)


def tracked_by_parent(target):
    """The folder sits in another repository that tracks its files: they are that project's, not a template."""
    return not has_repo(target) and tracked(target, '.')


def entries_of(target):
    """What stands in the target besides the entries a new folder may hold."""
    if not os.path.isdir(target):
        raise ScaffoldError('%s is not a folder: create an empty folder first' % target)
    return sorted(set(os.listdir(target)) - ALLOWED_IN_TARGET)


def list_files(target, entries, limit):
    """Relative paths of the files under entries, dependency folders left out; stops once past limit."""
    def fail(e):
        raise ScaffoldError('%s: %s' % (shown(e.filename), e.strerror))
    found = []
    for name in entries:
        path = os.path.join(target, name)
        if name in DEPENDENCY_DIRS:
            continue
        if not os.path.isdir(path) or os.path.islink(path):
            found.append(name)
            continue
        for dirpath, dirnames, filenames in os.walk(path, onerror=fail):
            dirnames[:] = sorted(d for d in dirnames if d not in DEPENDENCY_DIRS)
            found += sorted(os.path.relpath(os.path.join(dirpath, n), target) for n in filenames)
            if len(found) > limit:
                return found
    return found


def classify(target):
    entries = entries_of(target)
    commits = commit_count(target)
    if not entries:  # a longer history with no files here is a project a checkout away, not a new folder
        return Folder('new' if commits <= IDE_MAX_COMMITS else 'existing', [], [], commits)
    files = list_files(target, entries, IDE_MAX_FILES)
    template = commits <= IDE_MAX_COMMITS and len(files) <= IDE_MAX_FILES and not tracked_by_parent(target)
    return Folder('ide' if template else 'existing', entries, files, commits)


def shown(name):
    """A name for a line the model and the owner read: one with a line break or a bidi mark would fake other lines."""
    return ascii(name) if any(unicodedata.category(c) in BAD_CATEGORIES for c in name) else name


def inspect_lines(folder):
    """What the skill reads: the first line names the mode, a template lists every file for the owner."""
    if folder.kind == 'new':
        return ['scaffold: mode new']
    count = 'over %d' % IDE_MAX_FILES if len(folder.files) > IDE_MAX_FILES else str(len(folder.files))
    head = 'scaffold: mode %s: %s files, %d commits' % (folder.kind, count, folder.commits)
    if folder.kind != 'ide':
        return [head]
    dependencies = [d for d in folder.entries if d in DEPENDENCY_DIRS]
    return [head] + ['  ' + shown(rel) for rel in folder.files] + ['  %s/ (whole)' % d for d in dependencies]


def backup_folder(target, root, now):
    root = os.path.expanduser(root or BACKUP_ROOT)
    dest = os.path.join(root, now.strftime('%Y-%m-%d'), 'new-project-%s-%s' % (os.path.basename(target),
                                                                               now.strftime('%H%M%S')))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    os.mkdir(dest, 0o700)  # a template may hold a .env
    return dest


def clear_index(target):
    """No commits yet, but the IDE staged its template: the index would carry the moved files into the first commit.
    Only a real .git folder: a .git file may name the repository of another project."""
    git_dir = os.path.join(target, '.git')
    if not os.path.isdir(git_dir) or os.path.islink(git_dir):
        return
    run = run_git(target, 'read-tree', '--empty')
    if run.returncode != 0:
        raise ScaffoldError('git read-tree in %s: %s' % (target, run.stderr.strip()))


def move_template(target, root=None, now=None):
    """Moves a template to a backup folder; returns the folder and the moved entries."""
    folder = classify(target)
    if folder.kind != 'ide':
        raise ScaffoldError('%s: mode %s, not an IDE template; nothing moved' % (target, folder.kind))
    dest = backup_folder(target, root, now or datetime.datetime.now())
    moved = []
    try:
        for name in folder.entries:
            os.rename(os.path.join(target, name), os.path.join(dest, name))
            moved.append(name)
        if folder.commits == 0:
            clear_index(target)
    except BaseException as e:
        try:
            for name in reversed(moved):
                os.rename(os.path.join(dest, name), os.path.join(target, name))
            os.rmdir(dest)
        except OSError as back:
            raise ScaffoldError('the move failed (%s), moving back too (%s): the files are in %s and %s'
                                % (e, back, target, dest)) from e
        raise
    return dest, moved


def init_main(target):
    """The new project's repository on main, no commit. A .git the IDE made may hold another branch, and a .git from
    elsewhere its hooks, which `git branch -m` from a shell would run; a .git file or link is another repository."""
    git_dir = os.path.join(target, '.git')
    if not os.path.lexists(git_dir):
        args = ('init', '-q', '-b', 'main')
    elif os.path.islink(git_dir) or not os.path.isdir(git_dir):
        raise ScaffoldError('%s is a link or a file, so the repository is another one: nothing changed' % git_dir)
    elif tracked(target, 'brief'):
        raise ScaffoldError('the repository in %s tracks brief/, which stays out of git: nothing changed' % target)
    else:
        args = ('branch', '-m', 'main')
    run = run_git(target, *args)
    if run.returncode != 0:
        raise ScaffoldError('git %s in %s: %s' % (args[0], target, run.stderr.strip()))
