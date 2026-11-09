#!/usr/bin/env python3
"""docs-sync: a one-way mirror of the docs each project keeps outside git into one private docs repo (owner's
decisions 03.11.2026: one repo for all projects, a git hook in the .git/config of each connected project, a push in the
background, ~/project-docs on a private GitHub repo; 04.11.2026: the files gitleaks does not read are mirrored too, and
counted). The project folder stays the source: nothing is written there but the hook keys of connect. What is mirrored
and the registry: docs_sync_lib.py; the mirror, the scan, the commit and the push: docs_sync_repo.py; the lines of
doctor.sh: docs_sync_report.py. Commands (docs-sync.sh passes them on):
  hook post-commit|pre-push  git runs it in a connected project: mirror its main folder, commit in the docs repo, push
                             in the background while the docs repo is ahead of origin. Never fails a commit or a push:
                             a problem is one stderr line and one line in the error log, which doctor.sh shows
  init                       make the docs repo: README, registry (again after an init that stopped before its commit)
  connect [--dry-run] <folder>  a registry row and the first mirror, then the hook keys in the project's .git/config;
                             --dry-run says what would go and writes nothing
  disconnect <folder>        the keys go, the row says off, the mirror stays
  register <folder>          a registry row only: docs in git, in an own repo, a folder without git
  sync <folder>              mirror a connected project now (docs changed after its last commit), then push
  push                       push the docs repo now and say how it went (push-bg: the same in the background)
  report                     the lines of doctor.sh
Env: DOCS_SYNC_REPO (default ~/project-docs), DOCS_SYNC_PROJECTS (default ~/WebstormProjects), DOCS_SYNC_ERRLOG
(default ~/.claude/logs/docs-sync.err), DOCS_SYNC_MAX_FILE_B, DOCS_SYNC_LOCK_WAIT_S, DOCS_SYNC_SCAN_S and
DOCS_SYNC_ALARM_S (tests).
"""
import contextlib
import errno
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import traceback

sys.dont_write_bytecode = True   # no __pycache__ in the managed hooks folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I drops the script folder from sys.path
import docs_sync_lib  # noqa: E402
from docs_sync_lib import (BRANCH, ENV, HOME, HOOKS, IDENTITY, KEYS, MAX_FILE_MB, MODES, README, REGISTRY_MD,  # noqa: E402
                           REGISTRY_TSV, REPO, SyncError, TimedOut, arg, cell, check_name, connected, describe, git,
                           hook_command, keys_of, kinds, main_folder, names, plan_text, project, read_registry, remote,
                           row_of, set_docs, set_note, show, sources, tracked, unscanned, write_registry)
from docs_sync_report import report  # noqa: E402
from docs_sync_repo import Busy, PushError, changes, commit, locked, mirror_all, push, unpushed  # noqa: E402

ERRLOG = os.path.expanduser(os.environ.get('DOCS_SYNC_ERRLOG') or '~/.claude/logs/docs-sync.err')
ERR_LOG_MAX = 64_000  # bytes; then the log moves to docs-sync.err.1 and starts again
ONCE_LINES, ONCE_TAIL_B = 20, 16_384   # a line logged once is not written while one of the last 20 says the same
HOOK_LOCK_S = float(os.environ.get('DOCS_SYNC_LOCK_WAIT_S') or 3)   # a hook holds a commit: the next sync takes it
CLI_LOCK_S = 60
HOOK_GIT_S = 25       # one git call of a hook; a command keeps docs_sync_lib.GIT_TIMEOUT_S
HOOK_ALARM_S = int(os.environ.get('DOCS_SYNC_ALARM_S') or 60)   # the whole hook: a git hook has no time limit of its own
REPORT_ALARM_S = 120
HOOK_SCAN_S = float(os.environ.get('DOCS_SYNC_SCAN_S') or 15)   # the docs change of one commit
CLI_SCAN_S = 300      # the first snapshot of a folder
PUSH_WAIT_S = 300     # a push waits for the one before it
GIT_MIN = (2, 54)     # older git runs no hook from .git/config
EVENTS = {'post-commit': 'документи після', 'pre-push': 'документи перед пушем'}
REG = [REGISTRY_TSV, REGISTRY_MD]
INSTALLED = os.path.join(os.environ.get('CLAUDE_HOME') or os.path.join(HOME, '.claude'), 'hooks')
DEFAULT_REPO = os.path.join(HOME, 'project-docs')


def log_error(cls, what, once=False):
    """One line (UTC time, class, what) in the error log; then .1 when it is full. once: not while one of the last
    ONCE_LINES says the same (a copy kept, a file that fails, a push failing: each sync repeats them)."""
    line = cell('%s %s' % (cls, what))   # a file name with a line break would make a line of its own
    try:
        os.makedirs(os.path.dirname(ERRLOG), exist_ok=True)
        if once and os.path.exists(ERRLOG):
            with open(ERRLOG, 'rb') as fh:
                fh.seek(max(0, os.path.getsize(ERRLOG) - ONCE_TAIL_B))
                tail = fh.read().decode('utf-8', 'replace').splitlines()
            if any(ln.partition(' ')[2] == line for ln in tail[-ONCE_LINES:]):
                return
        if os.path.exists(ERRLOG) and os.path.getsize(ERRLOG) > ERR_LOG_MAX:
            os.replace(ERRLOG, ERRLOG + '.1')
        with open(ERRLOG, 'a', encoding='utf-8') as fh:
            fh.write('%s %s\n' % (time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), line))
    except OSError:
        pass


def say(text):
    """One stderr line. A reader that left (git commit ... | head -1) gets no more: stderr goes to /dev/null, and the
    error log keeps what failed."""
    try:
        print('docs-sync: ' + cell(text), file=sys.stderr, flush=True)
    except OSError:
        with contextlib.suppress(OSError):
            os.dup2(os.open(os.devnull, os.O_WRONLY), 2)


def fault(e):
    """An unexpected error for the log: its class, errno and the last place in docs-sync it passed, never a path or a
    value."""
    tb = traceback.extract_tb(e.__traceback__)
    own = [f for f in tb if os.path.basename(f.filename).startswith('docs_sync')] or tb
    where = ' at %s:%s:%d' % (os.path.basename(own[-1].filename), own[-1].name, own[-1].lineno) if own else ''
    code = errno.errorcode.get(e.errno or 0, '') if isinstance(e, OSError) else ''
    return type(e).__name__ + (' ' + code if code else '') + where


def same(a, b):
    """a and b are one folder: the same file when both exist, else the same path in the case APFS ignores."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.realpath(a).lower() == os.path.realpath(b).lower()


def check_copy():
    """Only the installed copy writes or pushes in the real docs repo: hook keys lead to the folder of the copy that
    wrote them, and its commit-leaks.toml is the one that scans."""
    if same(REPO, DEFAULT_REPO) and not same(HOOKS, INSTALLED):
        raise SyncError('this copy is not the installed one: run %s' % show(os.path.join(INSTALLED, 'docs-sync.sh')))


def check_git():
    out = git(['version'], HOME).stdout.strip()
    m = re.search(r'(\d+)\.(\d+)', out)
    if not m or tuple(map(int, m.groups())) < GIT_MIN:
        raise SyncError('%s runs no hook from .git/config: %d.%d or newer is needed' % ((out or 'git',) + GIT_MIN))


def alarm(seconds, what):
    """A TimedOut in seconds: the git it waits for is killed, and the locks go on the way out."""
    def ring(signum, frame):
        raise TimedOut('%s took over %d s' % (what, seconds))
    signal.signal(signal.SIGALRM, ring)
    signal.alarm(seconds)


def done_text(folder, tally, sha, push_text=''):
    """The line of a sync that committed: what the commit wrote and deleted under folder, what of that gitleaks does not
    read, how many files are over the cap."""
    try:
        written, deleted = changes(REPO, sha, folder)
    except SyncError:   # the commit is there all the same
        return '%s: committed to %s (%s)%s' % (folder, show(REPO), sha[:7], push_text)
    unread = [p for p in written if unscanned(os.path.join(REPO, p), p)]
    return '%s: %d copied, %d deleted to %s (%s)%s%s%s' % (
        folder, len(written), deleted, show(REPO), sha[:7], push_text,
        '; not scanned: %d (%s)' % (len(unread), kinds(unread)) if unread else '',
        '; over %d MB, not copied: %d' % (MAX_FILE_MB, len(tally.big)) if tally.big else '')


def extra_lines(main, tally):
    """The lines before the done line: copies the guard kept, copies that went with their docs into git, copies of units
    no longer mirrored, files that failed."""
    lines = ['%s (a folder moved or emptied? docs-sync.sh sync %s applies it)' % (k, arg(main)) for k in tally.kept]
    lines += ["%s: in the project's git now, its copy is gone from %s" % (m, show(REPO)) for m in tally.moved]
    lines += ['%s in %s' % (s, show(REPO)) for s in tally.stale]
    return lines + (['%d files not copied or deleted: %s' % (len(tally.failed), names(tally.failed))]
                    if tally.failed else [])


def update_row(rows, folder, main, tally):
    """The note and the docs of the row of folder (set_note, set_docs): True when one changed."""
    has_new_note = set_note(rows, folder, tally)
    return set_docs(rows, folder, main, tally) or has_new_note


def spawn_push(repo):
    """A push in the background while the docs repo is ahead of origin: a commit of a project never waits for the
    network, and the next sync tries a failed push again. The text for the done line."""
    try:
        if not unpushed(repo):
            return ''
        subprocess.Popen([sys.executable, '-I', os.path.abspath(__file__), 'push-bg'], cwd=repo,
                         env=dict(ENV, DOCS_SYNC_REPO=repo), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except (SyncError, OSError) as e:
        log_error('PushFailed', 'the push did not start: %s' % (e if isinstance(e, SyncError) else fault(e)))
        return ', the push did not start (%s)' % show(ERRLOG)
    return ', push in the background'


def hook(event):
    """git's post-commit or pre-push of a connected project; git runs a hook at the top of the worktree."""
    top = os.getcwd()
    main = main_folder(top)
    rows = read_registry(REPO)
    try:
        connected(rows, main)
    except SyncError as e:
        old = rows.get(os.path.basename(main))
        if old and old['mode'] == 'mirror' and not os.path.isdir(old['path']):
            return say('%s (moved here? docs-sync.sh connect %s takes the row over)' % (e, arg(main)))
        return say('%s (keys left over? docs-sync.sh disconnect %s)' % (e, arg(main)))
    sha = git(['rev-parse', '--short', 'HEAD'], top).stdout.strip()
    with locked(REPO, 'docs-sync.lock', HOOK_LOCK_S):
        rows = read_registry(REPO)   # again under the lock: a command may have changed it
        folder = connected(rows, main)
        tally = mirror_all(REPO, folder, main)
        if update_row(rows, folder, main, tally):
            write_registry(REPO, rows)
        done = commit(REPO, [folder] + REG, '%s: %s %s' % (folder, EVENTS[event], sha), HOOK_SCAN_S)
    for k in tally.kept + tally.stale:
        log_error('Kept', k, once=True)
    if tally.failed:
        log_error('SyncError', '%s: %d files not copied or deleted: %s' % (folder, len(tally.failed),
                                                                         names(tally.failed)), once=True)
    for line in extra_lines(main, tally):
        say(line)
    push_text = spawn_push(REPO)
    if done:
        say(done_text(folder, tally, done, push_text))


def init():
    check_copy()
    check_git()
    if not os.path.isdir(os.path.join(REPO, '.git')):
        if os.path.isdir(REPO) and os.listdir(REPO):
            raise SyncError('%s is not empty' % show(REPO))
        os.makedirs(REPO, exist_ok=True)
        git(['init', '-q', '-b', BRANCH], REPO)
    elif not git(['rev-parse', '-q', '--verify', 'HEAD'], REPO, check=False).returncode:
        raise SyncError('%s is a repo already' % show(REPO))   # with no commit: an init that stopped goes on
    for name, text in (('README.md', README), ('.gitignore', '.DS_Store\n')):
        with open(os.path.join(REPO, name), 'w', encoding='utf-8') as fh:
            fh.write(text)
    write_registry(REPO, {})
    commit(REPO, ['README.md', '.gitignore'] + REG, 'документація проєктів: старт', CLI_SCAN_S)
    print('docs-sync: %s is ready; next: docs-sync.sh connect <project folder>' % show(REPO))


def print_tally(main, tally):
    for line in extra_lines(main, tally) + ['not copied, over %d MB: %s' % (MAX_FILE_MB, b) for b in tally.big]:
        print('docs-sync: ' + line)


def undo_connect(folder, before, is_new):
    """A connect that stopped: the registry as it was, nothing staged, and no copy of a new folder (no hook keys are
    written yet). What fails here is left for the report: the reason of the stop is the one to show."""
    with contextlib.suppress(Exception):
        write_registry(REPO, before)
        git(['reset', '-q'], REPO, check=False)
        if is_new:
            shutil.rmtree(os.path.join(REPO, folder), ignore_errors=True)


def connect(path, dry_run=False):
    main = project(path)
    folder = os.path.basename(main)
    if not sources(main):
        raise SyncError('%s: no docs outside git to mirror (register it instead)' % folder)
    if dry_run:
        return print('docs-sync: ' + plan_text(folder, main))
    check_copy()
    check_git()
    _, docs, repo = describe(main)
    with locked(REPO, 'docs-sync.lock', CLI_LOCK_S):
        rows = read_registry(REPO)
        before, is_new = {k: dict(v) for k, v in rows.items()}, not tracked(REPO, folder)
        try:
            rows[folder] = row_of(rows, folder, main, 'mirror', docs, repo)
            tally = mirror_all(REPO, folder, main)
            set_note(rows, folder, tally)
            write_registry(REPO, rows)
            sha = commit(REPO, [folder] + REG, '%s: підключено, перший знімок' % folder, CLI_SCAN_S)
        except BaseException:
            undo_connect(folder, before, is_new)
            raise
    try:
        for name, event in KEYS:
            git(['config', '--local', '--replace-all', 'hook.%s.event' % name, event], main)
            git(['config', '--local', 'hook.%s.command' % name, hook_command(event)], main)
    except SyncError as e:
        raise SyncError('%s: mirrored and in the registry, the hook keys not written (%s): fix .git/config there, then '
                        'docs-sync.sh connect %s again' % (folder, e, arg(main))) from None
    push_text = spawn_push(REPO)
    print('docs-sync: ' + (done_text(folder, tally, sha, push_text) if sha else '%s: no change%s' % (folder, push_text)))
    print_tally(main, tally)


def disconnect(path):
    check_copy()
    p = os.path.abspath(os.path.expanduser(path))
    main = main_folder(p) if os.path.lexists(os.path.join(p, '.git')) else p
    folder = os.path.basename(main)
    if os.path.lexists(os.path.join(main, '.git')):   # the keys first: a broken registry leaves none of them
        for name, _ in KEYS:
            git(['config', '--local', '--remove-section', 'hook.' + name], main, check=False)   # 128 when there is none
        if keys_of(main):
            raise SyncError('%s: the hook keys are still there (git config --remove-section failed)' % folder)
    try:
        with locked(REPO, 'docs-sync.lock', CLI_LOCK_S):
            rows = read_registry(REPO)
            if folder in rows:
                rows[folder]['mode'] = 'off'
                write_registry(REPO, rows)
                commit(REPO, REG, 'реєстр: %s вимкнено' % folder, CLI_SCAN_S)
    except (SyncError, OSError) as e:
        raise SyncError('%s: no hook keys now; the registry: %s (fix it, then docs-sync.sh disconnect %s again)' % (
            folder, e, arg(main))) from None
    spawn_push(REPO)
    print('docs-sync: %s: no hook keys, the copy in %s stays' % (folder, show(REPO)))


def register(path):
    check_copy()
    p = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(p):
        raise SyncError('%s: no such folder' % path)
    main = main_folder(p) if os.path.isfile(os.path.join(p, '.git')) else p
    check_name(main)
    folder = os.path.basename(main)
    mode, docs, repo = describe(main)
    with locked(REPO, 'docs-sync.lock', CLI_LOCK_S):
        rows = read_registry(REPO)
        old = rows.get(folder)
        if old and old['mode'] == 'mirror' and os.path.realpath(old['path']) == os.path.realpath(main):
            raise SyncError('%s is connected (docs-sync.sh disconnect first)' % folder)
        rows[folder] = row_of(rows, folder, main, mode, docs, repo)
        write_registry(REPO, rows)
        commit(REPO, REG, 'реєстр: %s, %s' % (folder, MODES[mode]), CLI_SCAN_S)
    spawn_push(REPO)
    print('docs-sync: %s in the registry: %s, %s%s' % (folder, MODES[mode], docs, (
        '; connect it to mirror the docs' if mode == 'outside' else '')))


def manual_sync(path):
    check_copy()
    main = project(path)
    with locked(REPO, 'docs-sync.lock', CLI_LOCK_S):
        rows = read_registry(REPO)
        folder = connected(rows, main)
        tally = mirror_all(REPO, folder, main, is_guarded=False)   # by hand: deletions the hook kept go too
        if update_row(rows, folder, main, tally):
            write_registry(REPO, rows)
        sha = commit(REPO, [folder] + REG, '%s: документи (вручну)' % folder, CLI_SCAN_S)
    push_text = spawn_push(REPO)
    print('docs-sync: ' + (done_text(folder, tally, sha, push_text) if sha else '%s: no change%s' % (folder, push_text)))
    print_tally(main, tally)


def push_now():
    check_copy()
    try:
        n = push(REPO, PUSH_WAIT_S)
    except PushError as e:
        raise SyncError('%s%s' % (e, ': ' + e.detail if e.detail else '')) from None
    print('docs-sync: ' + ('%d commits pushed to %s' % (n, remote(REPO)) if n else 'the docs repo is up to date with '
                           'origin'))


COMMANDS = {'init': (init, 0), 'connect': (connect, 1), 'disconnect': (disconnect, 1), 'register': (register, 1),
            'sync': (manual_sync, 1), 'push': (push_now, 0), 'report': (lambda: print('\n'.join(report())), 0)}


def cli(argv):
    cmd = argv[1] if len(argv) > 1 else ''
    if cmd == 'hook':   # never fails: a pre-push hook with another code stops the push
        for k in IDENTITY:
            ENV.pop(k, None)   # the author of the project's commit: the docs repo commits as its owner
        docs_sync_lib.GIT_TIMEOUT_S = HOOK_GIT_S
        alarm(HOOK_ALARM_S, 'the hook')
        try:
            hook(argv[2] if len(argv) > 2 and argv[2] in EVENTS else 'post-commit')
        except BaseException as e:  # noqa: BLE001
            signal.alarm(0)
            why = str(e) if isinstance(e, SyncError) else fault(e)
            log_error('SyncError' if isinstance(e, SyncError) else 'Error', '%s: %s' % (os.path.basename(os.getcwd()), why))
            say('the docs are not mirrored (%s; %s)' % (why, show(ERRLOG)))
        return 0
    if cmd == 'push-bg':
        try:
            push(REPO, PUSH_WAIT_S)
        except Busy:
            pass   # the push holding the lock takes this commit in its next round, or the next sync does
        except BaseException as e:  # noqa: BLE001
            log_error('PushFailed', str(e) if isinstance(e, SyncError) else fault(e), once=True)
        return 0
    if cmd == 'report':
        alarm(REPORT_ALARM_S, 'the report')
    args = argv[2:]
    dry_run = cmd == 'connect' and args[:1] == ['--dry-run']
    args = args[1:] if dry_run else args
    fn, nargs = COMMANDS.get(cmd, (None, 0))
    if fn is None or len(args) != nargs:
        print('usage: docs-sync.sh init | connect [--dry-run] <folder> | disconnect <folder> | register <folder> | '
              'sync <folder> | push | report', file=sys.stderr)
        return 2
    try:
        fn(*args, **({'dry_run': True} if dry_run else {}))
    except (SyncError, OSError, subprocess.SubprocessError) as e:
        say(str(e) or type(e).__name__)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(cli(sys.argv))
