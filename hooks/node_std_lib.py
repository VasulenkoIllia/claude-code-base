"""node_std_lib: the state files of the hook node-std.py (stdlib, 3.9+). A state file is JSON lines in
~/.claude/state, the owner's only (600), appended to under an exclusive lock; its newest MAX_STATE bytes are read.
The hook opens the file of a check, looks without the lock whether there is anything to do, and takes the lock only
to decide and to write: `kept` keeps the file open for exactly that.
"""
import collections
import fcntl
import json
import os
import stat
import time

MAX_STATE = 1_000_000  # bytes at the end of a state file that are read: the newest records
LOCK_WAIT_S = 2.0
# a check with something to say or to record: its open state file, what decides it under the lock of that file
# (-> (line or None, record), or None: another session was first) and the step name of the file
Pending = collections.namedtuple('Pending', 'fd settle step')


def records(fd):
    """The JSON objects of the newest MAX_STATE bytes of a state file."""
    size = os.fstat(fd).st_size
    os.lseek(fd, max(0, size - MAX_STATE), os.SEEK_SET)
    lines = os.read(fd, MAX_STATE).decode('utf-8', 'replace').splitlines()[1 if size > MAX_STATE else 0:]
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            yield rec


def recorded(fd, std, project):
    """Is the project's verdict for this Node standard in the state file of the Node check?"""
    return any(rec.get('std') == std and rec.get('project') == project for rec in records(fd))


def named(fd, version, project):
    """(is the project judged for this version of the signals, the packs its records name) of the packs state file."""
    judged, packs = False, set()
    for rec in records(fd):
        if rec.get('project') == project and isinstance(rec.get('packs'), list):
            packs.update(p for p in rec['packs'] if isinstance(p, str))
            judged = judged or (rec.get('catalog') == version and not rec.get('unread'))
    return judged, packs


def open_state(env, name):
    """A state file, a regular file of the owner's only: a FIFO or a device there is an error, not a wait."""
    path = os.environ.get(env) or os.path.expanduser('~/.claude/state/' + name)
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


def kept(fd, name, compute):
    """compute(fd) -> the settle function of a check, or None. The state file stays open only for a check that has
    something left to settle."""
    settle = None
    try:
        settle = compute(fd)
        return Pending(fd, settle, name) if settle is not None else None
    finally:
        if settle is None:
            os.close(fd)


def append(fd, record):
    """One JSON line at the end of a state file, on a line of its own also after a record that was cut short (a full
    disk): a cut one then costs only itself. A write that comes short is an error."""
    size = os.fstat(fd).st_size
    lead = b'\n' if size and os.pread(fd, 1, size - 1) != b'\n' else b''
    blob = lead + (json.dumps(record) + '\n').encode('utf-8')
    if os.write(fd, blob) != len(blob):
        raise OSError('a state record was cut short')


def locked(fd):
    """An exclusive lock on a state file within LOCK_WAIT_S: another session may be writing its verdict."""
    stop = time.monotonic() + LOCK_WAIT_S
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            if time.monotonic() > stop:
                return False
            time.sleep(0.05)
