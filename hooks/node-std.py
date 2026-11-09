#!/usr/bin/env python3
"""node-std: SessionStart hook, started by node-std.sh (stdlib, 3.9+). Once per project and Node standard it tells the
model that the project's Node is behind the base's standard and asks it to propose the upgrade as a task of its own: a
new-session card whose brief follows ~/.claude/skills/new-project/upgrade.md (owner's decisions 03.11.2026).
The project is the git repository of the session's folder (searched up to the home folder; outside it, or with no
git, the folder itself), a worktree counted as its main repository when main lists it, with a package.json in its root
that holds a JSON object. The skill's node_std.py decides: the oldest Node of `.nvmrc`, of the node images of the
Dockerfiles and Compose files and of the CI, against versions.json. Behind the standard, end of life within 6 months or
past it, or no Node pinned: one line of hookSpecificOutput.additionalContext (under 1000 B); on the standard or newer:
silence. Then the verdict goes into the state file (~/.claude/state/node-std.jsonl, one JSON line: the standard's major,
the main repository, the state, the date) under a lock, and the project stays silent until the standard's major
changes; an unknown one (a place not read or with no plain version) is not recorded, the next session judges again.
Speaks only at the start of a new conversation (source startup or clear). A resume, a fork and a compaction go on
with an old one, and the app resumes an old session with no prompt to follow (seen 08.11), so the line would be
recorded as said and never reach the model. Silent for a subagent (agent_id) and outside a project too.
The line holds only numbers, dates and fixed words: the repository is untrusted.
Never blocks: always exit 0. An error or the time budget gone: silence, no record and one line (time, class, step) in
~/.claude/logs/node-std.err, which scripts/doctor.sh shows; an input field of another type or missing: a ShapeDrift
line, then on as before.
Env (tests only): NODE_STD_SKILL=<folder of node_std.py>, NODE_STD_VERSIONS=<versions.json>, NODE_STD_STATE=<file>,
NODE_STD_ERRLOG=<file>, NODE_STD_TODAY=YYYY-MM-DD, NODE_STD_BUDGET_S=<seconds>, NODE_STD_DEBUG=1 (the reason for
silence on stderr).
"""
import datetime
import fcntl
import json
import os
import re
import signal
import stat
import sys
import time

sys.dont_write_bytecode = True  # no __pycache__ in the managed hooks folder or in the skill
HOOKS = os.path.dirname(os.path.abspath(__file__))
SKILLS = (os.path.join(HOOKS, '..', 'skills', 'new-project'),
          os.path.join(HOOKS, '..', 'skills', 'own', 'new-project'))
MAX_INPUT = 1_000_000
MAX_STATE = 1_000_000  # bytes at the end of the state file that are read: the newest records
ERR_LOG_MAX = 64_000   # bytes; then no more lines
DRIFT_CAP = 32_000     # ShapeDrift comes with every session while the input stays odd: room for a later error
BUDGET_S = 5.0         # settings.json gives the hook 10 s
LOCK_WAIT_S = 2.0
HOME_DEPTH = 40
WORKTREE = re.compile(r'^(.*)/\.git/worktrees/[^/]+/?$')
SMALL_FILE = 4096      # bytes of a .git file or of a worktree's gitdir file that are read
SPEAKS = ('behind', 'soon', 'eol', 'unpinned')
NEW_CONVERSATION = ('startup', 'clear')  # the line comes with the first prompt; any other source, or none: silence
ASK = (' In your first reply tell the owner this in one sentence and propose the upgrade as a task of its own: a'
       ' new-session card (app: start_session with initiation own_initiative; CLI: suggest a new session) whose brief'
       ' says to follow ~/.claude/skills/new-project/upgrade.md. If the owner already asks for this upgrade, follow it'
       ' here instead. Change nothing of it without the owner\'s OK. The line comes once per project and Node'
       ' standard.')
step = 'input'


class TimeLimit(Exception):
    pass


def debug(reason):
    if os.environ.get('NODE_STD_DEBUG'):
        print('node-std: ' + reason, file=sys.stderr)


def log(what, cap=ERR_LOG_MAX):
    path = os.environ.get('NODE_STD_ERRLOG') or os.path.expanduser('~/.claude/logs/node-std.err')
    try:
        if os.path.exists(path) and os.path.getsize(path) > cap:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write('%s %s\n' % (time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), what))
    except OSError:
        pass


def read_input():
    """The SessionStart input, or None (logged as ShapeDrift input): fields of another type are logged and dropped."""
    raw = sys.stdin.read(MAX_INPUT + 1)
    try:
        data = json.loads(raw) if len(raw) <= MAX_INPUT else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        log('ShapeDrift input', DRIFT_CAP)
        return None
    odd = [k for k in ('hook_event_name', 'source', 'cwd') if not isinstance(data.get(k), str)]
    odd += ['agent_id'] * (data.get('agent_id') is not None and not isinstance(data.get('agent_id'), str))
    if odd:
        log('ShapeDrift ' + ' '.join(odd), DRIFT_CAP)
    return {k: v for k, v in data.items() if k not in odd}


def repo_root(cwd):
    """The folder of the session's repository (where `.git` stands), else cwd. The search stays in the home folder:
    outside it (/tmp, another volume) only cwd counts, so a `.git` planted above it doesn't."""
    home, folder = os.path.abspath(os.path.expanduser('~')), cwd  # abspath: HOME may hold // or a trailing /
    inside = folder == home or folder.startswith(home.rstrip(os.sep) + os.sep)
    for _ in range(HOME_DEPTH if inside else 1):
        if os.path.lexists(os.path.join(folder, '.git')):
            return folder
        if folder == home or os.path.dirname(folder) == folder:
            break
        folder = os.path.dirname(folder)
    return cwd


def small_text(path):
    """The stripped start of a regular file, '' for a link, a FIFO or no file: the repository is untrusted."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return ''
    try:  # a main repository's .git is a folder: no fdopen, which refuses one
        return os.read(fd, SMALL_FILE).decode('utf-8', 'replace').strip() if stat.S_ISREG(os.fstat(fd).st_mode) else ''
    finally:
        os.close(fd)


def main_repo(root):
    """The main repository of a worktree, else the root itself. A worktree's .git file names <main>/.git/worktrees/
    <name>, and git keeps the way back in that folder's gitdir file: a worktree main doesn't list there can't take
    main's state."""
    first = small_text(os.path.join(root, '.git'))
    if first.startswith('gitdir:'):
        admin = os.path.normpath(os.path.join(root, first[len('gitdir:'):].strip()))
        back, m = small_text(os.path.join(admin, 'gitdir')), WORKTREE.match(admin)
        if m and back and os.path.realpath(os.path.join(admin, back)) == os.path.realpath(os.path.join(root, '.git')):
            return os.path.realpath(m.group(1))
    return os.path.realpath(root)


def skill():
    """node_std of the skill next to the hooks (installed or the repo's layout), or NODE_STD_SKILL."""
    folder = os.environ.get('NODE_STD_SKILL') or next(
        (p for p in SKILLS if os.path.isfile(os.path.join(p, 'node_std.py'))), None)
    if folder is None:
        raise ImportError('no skill new-project')
    sys.path.insert(0, os.path.abspath(folder))
    import node_std
    return node_std, os.environ.get('NODE_STD_VERSIONS') or os.path.join(folder, 'versions.json')


def recorded(fd, std, project):
    """Is the project's verdict for this standard in the state file? Its newest MAX_STATE bytes are read."""
    size = os.fstat(fd).st_size
    os.lseek(fd, max(0, size - MAX_STATE), os.SEEK_SET)
    lines = os.read(fd, MAX_STATE).decode('utf-8', 'replace').splitlines()[1 if size > MAX_STATE else 0:]
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get('std') == std and rec.get('project') == project:
            return True
    return False


def open_state():
    """The state file, a regular file of the owner's only: a FIFO or a device there is an error, not a wait."""
    path = os.environ.get('NODE_STD_STATE') or os.path.expanduser('~/.claude/state/node-std.jsonl')
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError('the state file is not a regular file')
        os.fchmod(fd, 0o600)
    except OSError:
        os.close(fd)
        raise
    return fd


def locked(fd):
    """An exclusive lock on the state file within LOCK_WAIT_S: another session may be writing its verdict."""
    stop = time.monotonic() + LOCK_WAIT_S
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            if time.monotonic() > stop:
                return False
            time.sleep(0.05)


def text(ns, state, oldest, end, found, versions, manager):
    """The line for the model: numbers, dates and fixed words only."""
    where = ns.where(found)
    if state == 'unpinned':
        head = 'this project pins no Node major (none found in .nvmrc, Docker or CI), so its sessions run the ' \
               'default Node of nvm'
    elif state == 'eol':
        head = 'this project runs Node %d (%s), out of support %s: no security fixes' % (
            oldest, where, 'since ' + end.isoformat() if end else 'as it is no LTS line of the schedule')
    elif state == 'soon':
        head = 'this project runs Node %d (%s), whose support ends on %s, in under 6 months' % (oldest, where, end)
    else:
        head = 'this project runs Node %d (%s), behind the standard; its support ends on %s' % (oldest, where, end)
    name, have, behind = manager
    tool = '' if not behind else ' Package manager: %s (the standard is pnpm %s).' % (
        name if name != 'pnpm' else 'pnpm ' + '.'.join(map(str, have)), versions['pnpm'])
    return "node-std: %s; the base's Node standard is %s.%s%s" % (head, versions['node'], tool, ASK)


def run(data):
    global step
    if data.get('agent_id'):
        return debug('subagent')
    if data.get('hook_event_name') != 'SessionStart':
        return debug('not a session start')
    if data.get('source') not in NEW_CONVERSATION:
        return debug('not a new conversation')
    cwd = os.path.abspath(data['cwd'] if os.path.isdir(data.get('cwd') or '') else os.getcwd())
    root = repo_root(cwd)
    if not os.path.lexists(os.path.join(root, 'package.json')):
        return debug('no package.json')
    step = 'skill'
    ns, versions_path = skill()
    with open(versions_path, encoding='utf-8') as fh:
        versions = json.load(fh)
    std = str(versions['node'])
    step = 'verdict'
    project = main_repo(root)
    today = datetime.date.fromisoformat(os.environ.get('NODE_STD_TODAY') or datetime.date.today().isoformat())
    step = 'state'
    fd = open_state()
    try:
        if recorded(fd, std, project):
            return debug('said for this project and standard')
        step = 'verdict'
        pkg = ns.scaffold_gaps.package_of(root)
        if not pkg:  # a link, a special file, empty or not a JSON object: no project the standard can judge
            return debug('package.json is not a JSON object the hook reads')
        found = ns.places(root, ns.scaffold_project.project_files(root))
        state, oldest, end = ns.verdict(found, versions, today)
        line = text(ns, state, oldest, end, found, versions, ns.manager_state(root, pkg, versions)) \
            if state in SPEAKS else None
        step = 'state'
        if not locked(fd):
            return log('LockBusy state')
        if recorded(fd, std, project):
            return debug('another session said it')
        signal.setitimer(signal.ITIMER_REAL, 0)  # no alarm between the line and its record
        if line is not None:  # the line before its record: a failed write repeats it later, never loses it
            print(json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': line}}),
                  flush=True)
        if state != ns.UNKNOWN:  # a place not read or with no plain version: the next session judges again
            os.write(fd, (json.dumps({'std': std, 'project': project, 'state': state, 'date': today.isoformat()})
                          + '\n').encode('utf-8'))
    finally:
        os.close(fd)
    if line is None:
        debug('state ' + state)


def on_alarm(*_):
    raise TimeLimit()


def budget():
    """NODE_STD_BUDGET_S (tests) within (0, BUDGET_S]: zero would turn the timer off, a word would break the run."""
    try:
        seconds = float(os.environ.get('NODE_STD_BUDGET_S') or BUDGET_S)
    except ValueError:
        return BUDGET_S
    return seconds if 0 < seconds <= BUDGET_S else BUDGET_S


def main():
    signal.signal(signal.SIGALRM, on_alarm)
    try:  # the timer inside: an alarm right after it still lands in the handler below
        signal.setitimer(signal.ITIMER_REAL, budget())
        data = read_input()
        if data is not None:
            run(data)
    except Exception as e:  # never block a session start: the class and the step go to the log, nothing else
        signal.setitimer(signal.ITIMER_REAL, 0)  # no alarm inside the handler
        log('%s %s' % (type(e).__name__, step))
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    return 0


if __name__ == '__main__':
    sys.exit(main())
