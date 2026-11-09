"""docs-sync, the docs repo side (stdlib, 3.9+): the mirror of a project's docs, the secret scan, the commit and the
push. docs_sync.py runs them under the flock of locked(); docs_sync_lib.py says what is mirrored.
Every commit and every push goes through gitleaks with the rules of commit-leaks (commit-leaks.toml, or a .gitleaks.toml
at the top of the docs repo), run here: only its clean verdict lets them go, whatever the git config or the env of the
caller says (a hook of the docs repo could be off, gone or never set up after a clone). The git that gitleaks runs reads
none of the owner's config or attributes (SCAN_GIT): color.ui=always or a -diff attribute there would hide the text from
it, and it would find nothing.
"""
import contextlib
import fcntl
import json
import os
import re
import shlex
import shutil
import subprocess
import time
import unicodedata

from docs_sync_lib import (BRANCH, COMMIT_LOCKS, ENV, HOOKS, PUSH_LOCK, SOURCES, STATE, SyncError, TimedOut, arg,
                           cell, errno_name, git, names, show, sources, tracked, unscanned, walk)

GUARD_FILES, GUARD_SHARE = 20, 0.5   # deleting more files and this share of a copy at once: kept (a folder moved?)
HEAD_FILE_MODES = ('100644', '100755')   # a file in a git tree; 120000 is a link, 160000 a submodule
LEAKS_CODE = 17       # as in commit-leaks.sh: gitleaks exits with 1 on a broken config as well
PUSH_SCAN_S = 600     # the commits of a push, in the background
PUSH_TIMEOUT_S = 900  # a first push of over 100 MB on a slow uplink: git resumes no push
PUSH_ROUNDS = 3       # commits that landed during a push go in the next round
COPY_TMP = 'docs-sync-copy'          # in .git: a copy goes there first, then takes the place of the last one
SCAN_REPORT = 'docs-sync-scan.json'  # in .git: what gitleaks found (redacted), read for the place and the rule
SSH_OPTS = ' -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 -o ServerAliveCountMax=4'
HTTP_SLOW = ['-c', 'http.lowSpeedLimit=1000', '-c', 'http.lowSpeedTime=60']   # a push over https stalled for a minute
SCAN_GIT = {'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_ATTR_NOSYSTEM': '1', 'GIT_CONFIG_COUNT': '4',
            'GIT_CONFIG_KEY_0': 'color.ui', 'GIT_CONFIG_VALUE_0': 'never', 'GIT_CONFIG_KEY_1': 'color.diff',
            'GIT_CONFIG_VALUE_1': 'never', 'GIT_CONFIG_KEY_2': 'core.attributesFile', 'GIT_CONFIG_VALUE_2': os.devnull,
            'GIT_CONFIG_KEY_3': 'core.bigFileThreshold', 'GIT_CONFIG_VALUE_3': '512m'}
# the class of a failed push by git's stderr, the first that matches: a network failure also says "Could not read from
# remote repository", and a refused login "unable to access"
PUSH_CLASSES = (('no repo', ('does not appear to be a git repository',)),
                ('network', ('Could not resolve', 'timed out', 'Connection refused', 'Network is unreachable',
                             'Connection reset', 'Connection closed', 'Failed to connect', 'remote end hung up',
                             'RPC failed', 'Operation too slow', 'early EOF')),
                ('auth', ('Permission denied', 'Authentication failed', 'Repository not found', 'could not read Username',
                          'denied to', 'returned error: 403', 'Host key verification failed',
                          'Could not read from remote repository')),
                ('rejected', ('[rejected]', '[remote rejected]', 'non-fast-forward', 'fetch first', 'declined')))


class Busy(SyncError):
    """The flock is held over the wait: the next sync or push takes the change."""


class PushError(SyncError):
    """git push failed: its class in the text, git's last lines in detail (a push by hand prints them)."""

    def __init__(self, text, detail):
        super().__init__(text)
        self.detail = detail


@contextlib.contextmanager
def locked(repo, name, wait_s):
    """flock on .git/<name> of the docs repo: syncs of several projects share one index and one registry."""
    if not os.path.isdir(os.path.join(repo, '.git')):
        raise SyncError('no docs repo at %s (docs-sync.sh init)' % show(repo))
    fd = os.open(os.path.join(repo, '.git', name), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        end = time.monotonic() + wait_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= end:
                    raise Busy('the docs repo is busy over %g s' % wait_s) from None
                time.sleep(0.1)
        yield
    finally:
        os.close(fd)


class Tally:
    """What a mirror found: the units mirrored, files over the cap (their last copy stays), copies the guard kept,
    copies of units that are no longer sources, units whose copy went because they are in the project's git now, files
    that failed (name and errno), files of the source gitleaks does not read."""

    def __init__(self, units):
        self.units = units
        self.big, self.kept, self.stale, self.moved, self.failed, self.unscanned = [], [], [], [], [], []


def prune(root):
    for dp, _, _ in os.walk(root, topdown=False):
        if dp != root and not os.listdir(dp):
            with contextlib.suppress(OSError):
                os.rmdir(dp)


def mirror_unit(repo, main, folder, rel, is_flat, is_guarded, tally):
    """Make <repo>/<folder>/<rel> a copy of the mirrored files of <main>/<rel>. With is_guarded (a hook), a source with
    no file keeps the copy as it is, and so does deleting over GUARD_FILES files and GUARD_SHARE of the copy at once;
    sync by hand applies them. A copy goes to COPY_TMP first and then takes the place of the last one, so a copy that
    fails leaves that one; the file is named in tally.failed, the others go on."""
    src, dst, tmp = os.path.join(main, rel), os.path.join(repo, folder, rel), os.path.join(repo, '.git', COPY_TMP)
    have, big = walk(src, is_flat)
    old = walk(dst, is_flat, 'mirror')[0] if os.path.isdir(dst) else {}
    tally.big += [cell(os.path.join(rel, b)) for b in big]
    tally.unscanned += [r for r in have if unscanned(os.path.join(src, r), r)]
    gone = [r for r in old if r not in have and r not in big]   # a file grown over the cap keeps its last copy
    if is_guarded and old and (not have or (len(gone) > GUARD_FILES and len(gone) > GUARD_SHARE * len(old))):
        tally.kept.append('%s/%s: %d of %d copied files are gone from the source, nothing copied or deleted there' % (
            folder, rel, len(gone), len(old)))
        return
    for name in gone:   # first: a file that became a folder, or a name that changed case, takes its place after it
        try:
            os.remove(os.path.join(dst, name))
        except OSError as e:
            tally.failed.append('%s (%s)' % (cell(os.path.join(rel, name)), errno_name(e)))
    prune(dst)
    for name, sig in have.items():
        if old.get(name) == sig:
            continue
        target = os.path.join(dst, name)
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(os.path.join(src, name), tmp)
            os.replace(tmp, target)   # over a read-only copy too
        except OSError as e:
            with contextlib.suppress(OSError):
                os.remove(tmp)
            tally.failed.append('%s (%s)' % (cell(os.path.join(rel, name)), errno_name(e)))


def mirror_all(repo, folder, main, is_guarded=True):
    """Mirror every source of main into <repo>/<folder>: a Tally. The copy of a unit that is no longer a source stays,
    unless its folder went into git (leave_unit). No source and no copy that went: the project has no docs outside
    git, a SyncError that names the copies that stay and why."""
    units = sources(main)
    with contextlib.suppress(OSError):
        os.remove(os.path.join(repo, '.git', COPY_TMP))   # left by a sync that was stopped; it may be read-only
    tally = Tally(units)
    for rel, is_flat in units:
        mirror_unit(repo, main, folder, rel, is_flat, is_guarded, tally)
    now = {rel for rel, _ in units}
    for rel in SOURCES + (STATE,):
        if rel not in now and os.path.isdir(os.path.join(repo, folder, rel)):
            leave_unit(repo, main, folder, rel, tally)
    if not units and not tally.moved:
        raise SyncError('%s: no docs outside git to mirror (all in git? docs-sync.sh disconnect %s)%s' % (
            folder, arg(main), ''.join('; ' + s for s in tally.stale)))
    return tally


def leave_unit(repo, main, folder, rel, tally):
    """The copy of a unit that is no longer a source: it goes when the folder went into git as a whole (in_head), and
    the history of the docs repo keeps it; a copy with no file left goes without a word; else it stays, and each sync
    says so. Only the kinds of files docs-sync mirrors are compared: a hidden or a key file put into the copy by hand
    goes with it."""
    copy, label = os.path.join(repo, folder, rel), '%s/%s' % (folder, rel)
    if os.path.realpath(copy) != os.path.join(os.path.realpath(repo), folder, rel):
        why = ' (a link in the docs repo)'
    else:
        with contextlib.suppress(OSError):   # git keeps no empty folder: nothing to say
            prune(copy)
            os.rmdir(copy)
            prune(os.path.join(repo, folder))   # .claude of the copy of .claude/state
            return
        why = in_head(main, rel, copy)
    if why is None:
        try:
            shutil.rmtree(copy)
        except OSError as e:   # a part may be gone: the commit takes that, the next sync tries the rest
            why = " (in the project's git now, it could not go: %s)" % errno_name(e)
        else:
            prune(os.path.join(repo, folder))
            tally.moved.append(label)
            return
    tally.stale.append('%s: no longer a source (gone, in git, a link or a repo of its own), its copy stays%s' % (
        label, why))


def in_head(main, rel, copy):
    """None when the folder rel of the project went into git as a whole: each file of its copy and each file docs-sync
    would mirror from it is a regular file of the project's HEAD. By path: an older version in the copy (a doc changed
    between connect and the first commit) goes as well. Else why the copy stays: the files that are not (a folder gone,
    partly in git, a repo of its own), '' for a link or no such file, the cause for a folder that cannot be read or a
    HEAD git cannot list."""
    is_flat, src = rel == STATE, os.path.join(main, rel)
    if os.path.lexists(src) and os.path.realpath(src) != os.path.join(os.path.realpath(main), rel):
        return ''   # a link now: what it leads to is no folder of the project
    try:
        found = files_of(copy, is_flat, 'mirror') + (files_of(src, is_flat) if os.path.isdir(src) else [])
    except TimedOut:
        raise
    except SyncError as e:
        return ' (%s)' % e
    head = committed(main, rel)
    if head is None:
        return ' (git cannot list the HEAD of the project)'
    missing = sorted({nfc(os.path.join(rel, p)) for p in found} - {nfc(p) for p in head})
    if found and not missing:
        return None
    return " (not a file in the project's HEAD: %s)" % names([cell(m) for m in missing]) if missing else ''


def committed(main, rel):
    """The paths of the regular files under rel in the HEAD of the repo at main (a link or a submodule there holds no
    doc): an empty set before its first commit, None when git cannot list it (a broken repo, objects a partial clone
    would fetch: no network from here). The replace refs of the repo do not count."""
    p = git(['--no-replace-objects', 'ls-tree', '-r', '-z', 'HEAD', '--', rel], main, check=False,
            env=dict(ENV, GIT_NO_LAZY_FETCH='1'))
    if p.returncode:
        return set() if git(['rev-parse', '-q', '--verify', 'HEAD'], main, check=False).returncode else None
    entries = (e.partition('\t') for e in p.stdout.split('\0') if e)
    return {path for meta, _, path in entries if meta.split(' ', 1)[0] in HEAD_FILE_MODES}


def files_of(root, is_flat, what='source'):
    """The relative paths walk finds under root, the files over the cap among them."""
    files, big = walk(root, is_flat, what)
    return list(files) + big


def nfc(path):
    return unicodedata.normalize('NFC', path)   # git on macOS keeps the composed form of a name


def gitleaks():
    """The gitleaks commit-leaks runs: an absolute one on PATH, else Homebrew's."""
    gl = shutil.which('gitleaks', path=ENV.get('PATH', ''))
    if not (gl and os.path.isabs(gl)):
        gl = '/opt/homebrew/bin/gitleaks'
    if not os.access(gl, os.X_OK):
        raise SyncError('no gitleaks, and nothing goes to the docs repo unscanned (brew install gitleaks)')
    return gl


def findings(report):
    """'proj/docs/leak.md:1 (github-pat)' of each finding of a gitleaks JSON report, with the commit in a push: the place
    and the rule only (the match is redacted there as well)."""
    try:
        with open(report, encoding='utf-8') as fh:
            items = json.load(fh)
    except (OSError, ValueError):
        return []
    out = set()
    for f in items if isinstance(items, list) else []:
        if isinstance(f, dict):
            sha = str(f.get('Commit') or '')[:7]
            out.add(cell('%s:%s (%s%s)' % (f.get('File', '?'), f.get('StartLine', '?'), f.get('RuleID', '?'),
                                           ', ' + sha if sha else '')))
    return sorted(out)


def scan(repo, args, limit_s, fix):
    """gitleaks over what the docs repo is about to commit or push: its clean verdict lets it go; a finding (its place,
    then fix: what to do), any other code or no answer in limit_s stops it."""
    rules = os.path.join(repo, '.gitleaks.toml')
    rules = rules if os.path.isfile(rules) else os.path.join(HOOKS, 'commit-leaks.toml')
    report = os.path.join(repo, '.git', SCAN_REPORT)
    try:
        p = subprocess.run([gitleaks(), 'git', '--redact', '--no-banner', '--exit-code', str(LEAKS_CODE), '--config',
                            rules, '--report-format', 'json', '--report-path', report] + args, cwd=repo,
                           env=dict(ENV, **SCAN_GIT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=limit_s)
        found = findings(report) if p.returncode == LEAKS_CODE else []
    except subprocess.TimeoutExpired:
        raise SyncError('the secret scan took over %g s, so nothing goes on' % limit_s) from None
    finally:
        with contextlib.suppress(OSError):
            os.remove(report)
    if p.returncode == LEAKS_CODE:
        raise SyncError('gitleaks found a secret in %s: %s' % (names(found) or 'the docs', fix))
    if p.returncode:
        raise SyncError('gitleaks exit %d: no verdict, so nothing goes on' % p.returncode)


def clean_locks(repo, since, locks):
    """Remove the locks of the docs repo made since then: left by the git this call killed (a timer, a signal)."""
    for name in locks:
        path = os.path.join(repo, '.git', name)
        with contextlib.suppress(OSError):
            if os.path.getmtime(path) >= since - 1:
                os.remove(path)


def left_lock(repo, locks):
    left = [os.path.join(repo, '.git', n) for n in locks if os.path.exists(os.path.join(repo, '.git', n))]
    if left:
        raise SyncError('%s is left in the docs repo: delete it when no git runs there' % show(left[0]))


def commit(repo, paths, message, scan_s):
    """Commit the changes under paths in the docs repo once gitleaks has passed exactly them: the sha, or None with
    nothing to commit. The index then holds this commit only (a change a refused sync left there waits for its own),
    and the owner's global excludes do not hide a mirrored file."""
    paths = [p for p in paths if os.path.lexists(os.path.join(repo, p)) or tracked(repo, p)]
    if not paths:
        return None
    left_lock(repo, COMMIT_LOCKS)
    t0 = time.time()
    try:
        if git(['diff', '--cached', '--quiet'], repo, check=False).returncode:
            git(['reset', '-q'], repo)
        git(['-c', 'core.excludesFile=/dev/null', 'add', '-A', '--'] + paths, repo)
        if not git(['diff', '--cached', '--quiet'], repo, check=False).returncode:
            return None
        scan(repo, ['--pre-commit', '--staged'], scan_s, 'remove it in the project, the next sync retries')
        git(['commit', '-q', '-m', message], repo)
        return git(['rev-parse', 'HEAD'], repo).stdout.strip()
    except (TimedOut, KeyboardInterrupt):
        clean_locks(repo, t0, COMMIT_LOCKS)
        raise


def changes(repo, sha, folder):
    """([paths added or changed], number of paths deleted) under folder in the commit sha."""
    out = git(['diff-tree', '--root', '--no-commit-id', '--no-renames', '--name-status', '-r', '-z', sha, '--', folder],
              repo).stdout.split('\0')
    written = [path for st, path in zip(out[::2], out[1::2]) if st != 'D']
    return written, sum(st == 'D' for st in out[::2])


def unpushed(repo):
    """True when the docs repo has an origin and its HEAD is not what the last push left there."""
    if git(['config', '--get', 'remote.origin.url'], repo, check=False).returncode:
        return False
    p = git(['rev-parse', 'HEAD', 'refs/remotes/origin/' + BRANCH], repo, check=False)
    shas = p.stdout.split()
    return bool(p.returncode) or len(shas) != 2 or shas[0] != shas[1]


def push_env(repo):
    """The env of git push: no prompt for a password or a passphrase from git, ssh, the askpass of an IDE or a
    credential manager; the owner's own ssh command (core.sshCommand, GIT_SSH) with the options of BatchMode after it."""
    env = dict(ENV, GIT_TERMINAL_PROMPT='0', GIT_ASKPASS='', SSH_ASKPASS_REQUIRE='never', GCM_INTERACTIVE='never')
    env.pop('SSH_ASKPASS', None)   # GIT_ASKPASS '' skips core.askPass too
    ssh = ENV.get('GIT_SSH_COMMAND') or git(['config', '--get', 'core.sshCommand'], repo, check=False).stdout.strip() or (
        shlex.quote(ENV['GIT_SSH']) if ENV.get('GIT_SSH') else 'ssh')
    env['GIT_SSH_COMMAND'] = ssh + SSH_OPTS   # of two values of an option ssh takes the first: the owner's
    return env


def push_class(err):
    return next((cls for cls, marks in PUSH_CLASSES if any(m in err for m in marks)), 'other')


def push_reason(err, n=2):
    """The first n lines of git's stderr that say why a push failed (fatal, error, remote, a rejected ref), else its
    last n (the hint after them says nothing of the cause): no user or password of a URL, no control character."""
    lines = [re.sub(r'://\S*@', '://', ln.strip()) for ln in err.splitlines() if ln.strip()]
    why = [ln for ln in lines if ln.startswith(('fatal:', 'error:', 'remote:', '! '))] or lines[-n:]
    return '; '.join(cell(ln) for ln in why[:n])


def push(repo, wait_s):
    """Push the docs repo while it is ahead of origin, one push at a time, each round once gitleaks has passed the
    commits it takes (the one scanned is the one pushed): the number of commits pushed."""
    env, pushed = push_env(repo), 0
    with locked(repo, 'docs-sync-push.lock', wait_s):
        if git(['config', '--get', 'remote.origin.url'], repo, check=False).returncode:
            raise SyncError('no remote origin in the docs repo')
        left_lock(repo, (PUSH_LOCK,))
        for _ in range(PUSH_ROUNDS):
            head = git(['rev-parse', 'HEAD'], repo).stdout.strip()
            up = git(['rev-parse', '-q', '--verify', 'refs/remotes/origin/' + BRANCH], repo, check=False).stdout.strip()
            if head == up:
                break
            span = '%s..%s' % (up, head) if up else head
            scan(repo, ['--log-opts=' + span], PUSH_SCAN_S, 'nothing pushed (a commit not on origin holds it)')
            t0 = time.time()
            try:
                p = git(HTTP_SLOW + ['push', '-q', 'origin', '%s:refs/heads/%s' % (head, BRANCH)], repo, check=False,
                        env=env, timeout=PUSH_TIMEOUT_S)
            except (TimedOut, KeyboardInterrupt):
                clean_locks(repo, t0, (PUSH_LOCK,))
                raise
            if p.returncode:
                raise PushError('git push rc=%d (%s)' % (p.returncode, push_class(p.stderr)), push_reason(p.stderr))
            pushed += int(git(['rev-list', '--count', span], repo).stdout.strip() or 0)
    return pushed
