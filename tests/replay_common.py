"""replay_common: what the replay gates tests/hook-replay.py, edit-replay.py, commit-replay.py, hint-replay.py and the
check tests/hint-delivered.py share: transcript folders, audit skip, dates, the reader of transcript records and their
content blocks, the percentile; for the gates that run a hook as stdin JSON: the run, the error log and the dump. They
run with python3 -I, so they add this folder to sys.path themselves."""
import datetime
import glob
import hashlib
import json
import os
import re
import subprocess
import time

HOME = os.path.expanduser('~')
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS = os.path.join(HOME, '.claude', 'projects')
CACHE = os.path.join(REPO, 'research', 'replay-cache')
ROLE = {'tool_use': 'assistant', 'tool_result': 'user'}   # the record type whose message holds such content blocks


def encode_dir(path):
    """Claude Code names a project folder after its path with every non-alphanumeric character as '-'."""
    return re.sub(r'[^A-Za-z0-9]', '-', path)


AUDIT_PREFIXES = (encode_dir(REPO), '-private-tmp-', '-tmp-', '-private-var-folders-', '-var-folders-')


def local_date(ts, fmt='%Y-%m-%d'):
    try:
        return datetime.datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone().strftime(fmt)
    except ValueError:
        return ''


def window_start(days):
    """(epoch, UTC time as in transcripts) of now minus days: where a replay window starts."""
    epoch = time.time() - days * 86400
    return epoch, datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')


def list_files(cutoff_epoch, include_audit, top_only=False, projects=PROJECTS):
    """[(project folder, transcript)] changed since cutoff_epoch, and the number of audit files skipped.
    top_only: main session files only (no subagent transcripts in subfolders). projects: the folder of the project
    folders (another one only for hint-delivered.py --claude-home)."""
    files, audit_skipped = [], 0
    try:
        names = sorted(os.listdir(projects))
    except OSError:
        return files, audit_skipped
    for proj in names:
        pdir = os.path.join(projects, proj)
        if not os.path.isdir(pdir):
            continue
        if top_only:
            cands = glob.glob(os.path.join(glob.escape(pdir), '*.jsonl'))
        else:
            cands = [os.path.join(dp, f) for dp, _, fns in os.walk(pdir) for f in fns if f.endswith('.jsonl')]
        for f in sorted(cands):
            try:
                if os.stat(f).st_mtime < cutoff_epoch:
                    continue
            except OSError:
                continue
            if not include_audit and proj.startswith(AUDIT_PREFIXES):
                audit_skipped += 1
                continue
            files.append((proj, f))
    return files, audit_skipped


def session_of(proj, path):
    """(session id, is a subagent transcript) of a transcript in the project folder proj: <session>.jsonl, or a file
    under <session>/subagents/. The last folder named proj: the same name may come earlier in the path."""
    rest = path.rpartition(os.sep + proj + os.sep)[2]
    first = rest.split(os.sep)[0]
    return (first[:-len('.jsonl')], False) if first == rest else (first, True)


def records(lines, counts, keep=None, dedup=False):
    """The records of transcript lines that are objects with a timestamp. keep(line): only such lines are parsed (a
    cheap filter; the others are not counted). dedup: each uuid once (resuming a session appends copies of its chain
    with the same uuid and time). Unreadable lines are counted in counts['bad'] (also the last line while it is
    written)."""
    uuids = set()
    for line in lines:
        if keep and not keep(line):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            counts['bad'] += 1
            continue
        if not isinstance(d, dict) or not isinstance(d.get('timestamp'), str):
            continue
        uid = d['uuid'] if dedup and isinstance(d.get('uuid'), str) else None
        if uid in uuids:
            continue
        if uid:
            uuids.add(uid)
        yield d


def blocks(d, kind):
    """The content blocks of one type in a record: 'tool_use' (calls) of an assistant message, 'tool_result' (their
    results) of a user one."""
    msg = d.get('message') if d.get('type') == ROLE[kind] else None
    content = msg.get('content') if isinstance(msg, dict) else None
    return [b for b in content if isinstance(b, dict) and b.get('type') == kind] if isinstance(content, list) else []


def pct(values, q):
    """The value at rank q (0..1) of values, 0 when there are none."""
    v = sorted(values)
    return v[min(len(v) - 1, int(len(v) * q))] if v else 0


def sha(path):
    with open(path, 'rb') as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:12]


def short(path):
    return path.replace(HOME, '~', 1) if path.startswith(HOME) else path


def proj_name(proj):
    """A project folder name without the WebstormProjects path before it."""
    return re.sub(r'^-Users-[^-]+-WebstormProjects-', '', proj)

# ---------------------------------------------------------------- the gates that run a hook as stdin JSON


def run_hook(hook, payload, env, timeout):
    """(exit code or 'timeout', stdout, stderr, ms) of one hook run."""
    t = time.perf_counter()
    try:
        p = subprocess.run(['/bin/bash', hook], input=json.dumps(payload).encode('utf-8'), capture_output=True,
                           timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return 'timeout', '', '', (time.perf_counter() - t) * 1000
    return p.returncode, p.stdout.decode('utf-8', 'replace'), p.stderr.decode('utf-8', 'replace'), \
        (time.perf_counter() - t) * 1000


def size(path):
    return os.path.getsize(path) if os.path.exists(path) else 0


def log_lines(path):
    """The lines of a hook's error log; none when the hook never wrote one."""
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            return fh.read().splitlines()
    except FileNotFoundError:
        return []


def write_dump(name, items, what):
    """--dump: items as JSON lines to research/replay-cache/<name>-<time>.jsonl (gitignored, 0600)."""
    os.makedirs(CACHE, mode=0o700, exist_ok=True)
    path = os.path.join(CACHE, '%s-%s.jsonl' % (name, time.strftime('%Y%m%d-%H%M%S')))
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as fh:
        for item in items:
            fh.write(json.dumps(item, ensure_ascii=False) + '\n')
    print('dump  %d %s (raw, do not paste) -> %s' % (len(items), what, short(path)))
