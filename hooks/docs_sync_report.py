"""docs-sync, the lines of doctor.sh (stdlib, 3.9+): WARNs of the connected projects, of the folders not in the
registry and of the docs repo, then the summary line. It writes nothing: its git status takes no optional lock, so the
index of the docs repo stays as it is while a sync may be at work there.
"""
import os
import re
import subprocess
import time

from docs_sync_lib import (BRANCH, COMMIT_LOCKS, KEYS, PROJECTS, PUSH_LOCK, REPO, SOURCES, STATE, SyncError, git,
                           hook_command, keys_of, names, read_registry, remote, show, sources, walk)

DAY_S = 86400
STALE_DAYS = 60        # owner's decision 03.11.2026: the registry holds the projects of 60 days, older ones are offered
LAG_S = DAY_S          # docs changed this long after the last sync of a project: a WARN (its next commit syncs them)
UNPUSHED_S = 600       # a background push takes seconds: an older commit not on the remote is a WARN


def newest(path, units):
    """Newest mtime (s) of the mirrored files of units under path, 0 with none."""
    best = 0
    for rel, is_flat in units:
        files, _ = walk(os.path.join(path, rel), is_flat)
        best = max([best] + [m // 10 ** 9 for _, m in files.values()])
    return best


def activity(path):
    """The last commit or the newest change of docs, README, STATUS or instructions of a folder, 0 with none."""
    t = 0
    if os.path.isdir(os.path.join(path, '.git')):
        t = int(git(['log', '-1', '--format=%ct'], path, check=False).stdout.strip() or 0)
    for f in os.listdir(path):
        if re.match(r'(readme|status|claude|agents)\b', f, re.I) and os.path.isfile(os.path.join(path, f)):
            t = max(t, int(os.lstat(os.path.join(path, f)).st_mtime))
    for name in SOURCES + (STATE,):
        if os.path.isdir(os.path.join(path, name)) and not os.path.islink(os.path.join(path, name)):
            try:
                t = max(t, newest(path, [(name, name == STATE)]))
            except SyncError:   # an odd folder of thousands of files: its commits still count
                pass
    return t


def ahead(repo):
    """(commits not on origin, committer time of the oldest one), or None with no origin."""
    if git(['remote', 'get-url', 'origin'], repo, check=False).returncode:
        return None
    has_up = not git(['rev-parse', '-q', '--verify', 'refs/remotes/origin/' + BRANCH], repo, check=False).returncode
    times = git(['log', '--format=%ct', ('origin/%s..HEAD' % BRANCH) if has_up else 'HEAD'], repo).stdout.split()
    return len(times), int(times[-1]) if times else 0


def project_warns(repo, rows, now):
    """WARNs of the connected projects: a missing folder, missing hook keys or keys connect would not write now (an
    older form, another copy of docs-sync), docs changed long after the last sync, a project git cannot read."""
    want = {'hook.%s.%s' % (n, k): v for n, e in KEYS for k, v in (('event', e), ('command', hook_command(e)))}
    gone, keys, other, lag, broken = [], [], [], [], []
    for r in (r for r in rows.values() if r['mode'] == 'mirror'):
        if not os.path.isdir(r['path']):
            gone.append(r['folder'])
            continue
        try:
            have = keys_of(r['path'])
            if any(k.endswith('.event') and k not in have for k in want):
                keys.append(r['folder'])
            elif have != want:
                other.append(r['folder'])
            last = int(git(['log', '-1', '--format=%ct', '--', r['folder']], repo).stdout.strip() or 0)
            if newest(r['path'], sources(r['path'])) - last > LAG_S:
                lag.append('%s (%s)' % (r['folder'], '%d days ago' % ((now - last) // DAY_S) if last else 'never'))
        except (SyncError, OSError, subprocess.SubprocessError):
            broken.append(r['folder'])
    out = [('a connected folder is gone: %s (docs-sync.sh disconnect <folder>, or connect it where it is now)', gone),
           ('hook keys missing in a connected project: %s (docs-sync.sh connect <folder> again)', keys),
           ('hook keys of another form or another copy of docs-sync: %s (docs-sync.sh connect <folder> again)', other),
           ('docs changed over a day after the last sync: %s (docs-sync.sh sync <folder>, or the next commit there)',
            lag), ('a connected project could not be checked: %s (git -C <folder> status says why)', broken)]
    return [text % names(items) for text, items in out if items]


def stray_warns(rows):
    """Folders of the registry that are not connected and still have hook keys: each commit there prints a line."""
    stray = [r['folder'] for r in rows.values() if r['mode'] != 'mirror' and os.path.isdir(
        os.path.join(r['path'], '.git')) and keys_of(r['path'])]
    return ['hook keys in folders not connected: %s (docs-sync.sh disconnect <folder>)' % names(stray)] if stray else []


def candidate_warns(repo, rows, projects, now):
    """WARNs of the project folders not in the registry: active ones (STALE_DAYS) to connect or register, and older
    ones with docs to bring up to date and add (owner's decision 03.11.2026)."""
    listed = {os.path.realpath(r['path']) for r in rows.values()} | {os.path.realpath(repo)}
    active, stale = [], []
    for name in sorted(os.listdir(projects), key=str.lower) if os.path.isdir(projects) else []:
        path = os.path.join(projects, name)
        if os.path.islink(path) or not os.path.isdir(path) or os.path.isfile(os.path.join(path, '.git')) or \
                os.path.realpath(path) in listed:
            continue
        try:
            last = activity(path)
        except (OSError, subprocess.SubprocessError):   # an unreadable folder: doctor's docs lines name it
            continue
        if now - last <= STALE_DAYS * DAY_S:
            active.append(name)
        elif any(os.path.isdir(os.path.join(path, n)) for n in SOURCES):
            stale.append(name)
    out = [('active in %d days, not in the registry: %%s (docs-sync.sh connect <folder> for docs outside git, else '
            'register)' % STALE_DAYS, active),
           ('no work in %d days, docs not in the registry: %%s (bring the docs up to date in a session of that '
            'project, then connect or register)' % STALE_DAYS, stale)]
    return [text % names(items) for text, items in out if items]


def repo_warns(repo, now):
    """WARNs of the docs repo itself: no origin or commits not on it, a lock left by a git killed on its way, entries
    a sync left uncommitted; and the count of commits not on origin for the summary line ('-' with no origin)."""
    warns, state = [], ahead(repo)
    if state is None:
        warns.append('no remote origin: the docs are on this Mac only')
    elif state[0] and now - state[1] > UNPUSHED_S:
        warns.append('%d commits not on origin, the oldest %d min ago (the next sync or docs-sync.sh push tries '
                     'again; the error log says why it failed)' % (state[0], (now - state[1]) // 60))
    for name in COMMIT_LOCKS + (PUSH_LOCK,):
        if os.path.exists(os.path.join(repo, '.git', name)):
            warns.append('.git/%s is left in the docs repo: no sync %s until it goes (no git runs there? then delete '
                         'it)' % (name, 'pushes' if name == PUSH_LOCK else 'commits'))
    dirty = git(['--no-optional-locks', '-c', 'core.excludesFile=/dev/null', 'status', '--porcelain'], repo,
                check=False).stdout.splitlines()
    if dirty:
        warns.append('%d entries not committed in the docs repo (a sync refused or stopped: the error log or the last '
                     'docs-sync.sh command says why)' % len(dirty))
    return warns, '-' if state is None else state[0]


def report(repo=REPO, projects=PROJECTS, now=None):
    """doctor.sh lines: WARNs, then the summary line."""
    now = int(now or time.time())
    if not os.path.isdir(os.path.join(repo, '.git')):
        return ['  WARN: docs repo: not set up at %s (docs-sync.sh init, then connect the projects)' % show(repo)]
    rows = read_registry(repo)
    own, behind = repo_warns(repo, now)
    warns = project_warns(repo, rows, now) + stray_warns(rows) + candidate_warns(repo, rows, projects, now) + own
    last = git(['log', '-1', '--format=%cr'], repo, check=False).stdout.strip() or 'never'
    mirror = sum(r['mode'] == 'mirror' for r in rows.values())
    return ['  WARN: docs repo: ' + w for w in warns] + [
        '  docs repo: %s, %s, mirror %d, in the registry %d, last commit %s, not on origin %s' % (
            show(repo), remote(repo), mirror, len(rows), last, behind)]
