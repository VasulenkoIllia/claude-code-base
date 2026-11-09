#!/usr/bin/env python3
"""doc-reminder: PostToolUse and PostToolUseFailure hook for Bash, started by doc-reminder.sh only when the command
runs git commit (stdlib, 3.9+). The global rule it backs: docs are part of done, also the docs outside git.
Finds the commits of this call: HEAD reflog entries "commit..." from duration_ms before now (plus 5 s) until now, in
the repo of every cd / git -C target of the command and of cwd. If a repo's commits change code (a file that is not a
doc, a lock file or media) and no docs (README, docs/, *.md, *.mdx; the working log is no docs: STATUS, progress,
plans, decisions, CHANGELOG..., doc_reminder_lib.is_log), and its local docs outside git (docs/ and _internal/ without
a tracked file; for a worktree those of the main folder, as its own copies are drafts) did not change after the session
started and after the previous commit (the newest mtime of a file that is not the log, the STATUS.md checkpoint of the
global rules among it, against the later of the transcript's birth time and the committer time of the first parent of
the call's oldest commit: an edit early in a session does not cover the commits after it), it prints
hookSpecificOutput.additionalContext ("doc-reminder: ...", JSON <= 1200 B), which also names the docs the commit's
areas point to (env and commands: README; deploy, schema, API, integrations: such a doc of the repo, by its name;
doc_reminder_lib.area_hint). Once per run of commits with no docs
change: silent when a first-parent ancestor made in this session after the last docs change had it already (code and
no docs, the docs unchanged since its own previous commit; a commit the hook did not see counts too).
When that check cannot be made (no session start, a folder not walked in full, a symlink), the reminder says so.
Never blocks; any error, timeout or odd input -> silent exit 0.
An internal error (not odd input: a broken git or repo, an unreadable reflog, a timeout) also appends one line (time,
error class, step) to ~/.claude/logs/doc-reminder.err, which scripts/doctor.sh shows, so a dead hook does not look
like "nothing to remind".
Env (tests and replay only): DOC_REMINDER_NOW=<epoch> (the end of the call instead of now), DOC_REMINDER_LOCAL=
changed|unchanged (instead of the whole check), DOC_REMINDER_DOCS_MTIME=<epoch> (the newest docs change of this
session, 0 for none, instead of the file times; tests/commit-replay.py takes it from the transcript),
DOC_REMINDER_ERRLOG=<file> (error log instead of the live one), DOC_REMINDER_GIT=<path> (a git stub:
tests), DOC_REMINDER_DEBUG=1 (reason for silence on stderr).
"""
import json
import os
import re
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True   # no __pycache__ in the managed hooks folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I drops the script folder from sys.path
try:
    import doc_reminder_lib as lib  # noqa: E402
    LIB_ERROR = ''
except Exception as e:  # a partial install or a broken copy: main() fails open with a line that names it
    lib, LIB_ERROR = None, type(e).__name__

EVENTS = ('PostToolUse', 'PostToolUseFailure')
NOT_CODE_RE = re.compile(
    r'(^|/)(package-lock\.json|npm-shrinkwrap\.json|pnpm-lock\.yaml|yarn\.lock|bun\.lockb?|Cargo\.lock|poetry\.lock|'
    r'uv\.lock|Pipfile\.lock|Gemfile\.lock|composer\.lock|go\.sum)$'
    r'|\.(png|jpe?g|gif|webp|avif|ico|svg|pdf|woff2?|ttf|otf|eot|mp[34]|mov|webm|zip)$', re.I)
TEST_RE = re.compile(r'(^|/)(tests?|__tests__|e2e)/|\.(test|spec)\.[^/]+$', re.I)   # listed last in the reminder
LOCAL_DIRS = ('docs', '_internal')
WORD = r'"[^"]*"|\'[^\']*\'|[^\s;&|()<>"\']+'
CD_RE = re.compile(r'(?:^|[;&|(\n])\s*(?:cd|pushd)\s+(%s)' % WORD)
GIT_OPTS_RE = re.compile(r'\bgit((?:\s+-[cC]\s+(?:%s))+)\s+commit\b' % WORD)
C_ARG_RE = re.compile(r'-C\s+(%s)' % WORD)
REFLOG_RE = re.compile(r'^[0-9a-f]{40,64} ([0-9a-f]{40,64}) [^\t]*> (\d+) [+-]\d{4}\t(.*)$')   # old new who time\tmsg
# git rc 128 that answers (LC_ALL=C): not a repo, a bare one, no commit yet; any other 128 is a broken git or repo
ANSWER_128_RE = re.compile(r"not a git repository|must be run in a work tree|does not have any commits yet|"
                           r"ambiguous argument 'HEAD'")
SLACK_S = 5
NO_DURATION_S = 600   # duration_ms missing: the longest Bash call
MAX_INPUT = 16_000_000
MAX_TARGETS = 6
MAX_REFLOG_BYTES = 8_000_000   # the end of HEAD's reflog file that is read
MAX_NAMES = 20_000
MAX_WALK = 5000       # files under the local docs; with more, an older newest mtime is no answer
MAX_RUN = 30          # commits before the call's that are looked at for the reminder of this run
MAX_OUT = 1200        # bytes of the printed JSON
BUDGET_S = 3.0        # then stop silently (settings.json timeout is 5 s)
GIT = os.environ.get('DOC_REMINDER_GIT') or 'git'
ERR_LOG_MAX = 64_000  # bytes; then the log moves to doc-reminder.err.1 and starts again
T0 = time.monotonic()


class HookError(Exception):
    """Our own failures; only their messages reach the error log (they never hold paths or commands)."""


def dbg(msg):
    if os.environ.get('DOC_REMINDER_DEBUG'):
        print('doc-reminder: ' + msg, file=sys.stderr)


def log_error(e):
    """One line per internal error: time, class and only our own messages (never paths or commands)."""
    path = os.environ.get('DOC_REMINDER_ERRLOG') or os.path.join(os.path.expanduser('~'), '.claude', 'logs',
                                                                 'doc-reminder.err')
    own = str(e)[:80] if isinstance(e, HookError) else ''
    try:
        if os.path.isfile(path) and os.path.getsize(path) > ERR_LOG_MAX:
            os.replace(path, path + '.1')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write('%s %s %s\n' % (time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), type(e).__name__, own))
    except OSError:
        pass


def check_budget():
    if time.monotonic() - T0 > BUDGET_S:
        raise HookError('budget %.0f s' % BUDGET_S)


def git(args, cwd, timeout):
    """(rc, stdout). rc 0, and 128 with an answer (ANSWER_128_RE), are answers; anything else is a HookError that
    names the step, so it reaches the error log (a broken git, e.g. xcrun after a macOS update; a bad config, a repo
    extension this git does not know, a missing object; a timeout)."""
    check_budget()
    try:
        p = subprocess.run([GIT, '-c', 'core.quotePath=false'] + args, cwd=cwd, capture_output=True, timeout=timeout,
                           env={'PATH': '/usr/bin:/bin', 'GIT_OPTIONAL_LOCKS': '0', 'LC_ALL': 'C',
                                'HOME': os.environ.get('HOME', '/')})
    except subprocess.TimeoutExpired:
        raise HookError('git %s timeout' % args[0])
    except OSError as e:
        raise HookError('git %s %s' % (args[0], type(e).__name__))
    if p.returncode != 0 and not (p.returncode == 128 and ANSWER_128_RE.search(p.stderr.decode('utf-8', 'replace'))):
        raise HookError('git %s rc=%d' % (args[0], p.returncode))
    return p.returncode, p.stdout.decode('utf-8', 'replace')


def unquote(word):
    if len(word) >= 2 and word[0] == word[-1] and word[0] in '"\'':
        word = word[1:-1]
    return word


def targets(cmd, cwd):
    """Folders the commit may have run in: git -C and cd targets of the command (in order), then cwd."""
    home = os.environ.get('HOME', '')
    words = []
    for m in GIT_OPTS_RE.finditer(cmd):
        words += [c.group(1) for c in C_ARG_RE.finditer(m.group(1))]
    words += [m.group(1) for m in CD_RE.finditer(cmd)]
    out = []
    for w in words + ([cwd] if cwd else []):
        p = unquote(w)
        var = next((v for v in ('~', '$HOME', '${HOME}') if p == v or p.startswith(v + '/')), '')
        if var:
            p = home + p[len(var):]
        if not os.path.isabs(p):
            if not cwd:
                continue
            p = os.path.join(cwd, p)
        p = os.path.normpath(p)
        if p not in out and os.path.isdir(p):
            out.append(p)
    return out[:MAX_TARGETS]


def toplevel(d):
    rc, out = git(['rev-parse', '--show-toplevel'], d, 1.0)
    return out.strip() if rc == 0 and out.strip() else ''


def reflog_lines(top):
    """The end of HEAD's reflog file (this worktree's), or None without one (core.logAllRefUpdates off, reftable).
    One that cannot be read is a HookError: the fallback would miss all but the last commit."""
    rc, out = git(['rev-parse', '--git-path', 'logs/HEAD'], top, 1.0)
    if rc != 0 or not out.strip():
        return None
    try:
        with open(os.path.join(top, out.strip()), 'rb') as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - MAX_REFLOG_BYTES))
            return fh.read().decode('utf-8', 'replace').splitlines()
    except FileNotFoundError:
        return None
    except OSError as e:
        raise HookError('reflog %s' % type(e).__name__)


def commits(top, since, now):
    """Commits that HEAD's reflog recorded in [since, now], newest first (one line per HEAD move, in time order).
    Without a reflog file: HEAD, when its committer time is in the window."""
    lines = reflog_lines(top)
    if lines is not None:
        found = []
        for line in reversed(lines):
            m = REFLOG_RE.match(line)
            if not m:
                continue
            ts = int(m.group(2))
            if ts < since:
                break
            if ts <= now + SLACK_S and m.group(3).startswith('commit') and m.group(1) not in found:
                found.append(m.group(1))
        return found
    rc, out = git(['log', '-1', '--format=%H%x09%ct', 'HEAD', '--'], top, 1.0)
    parts = out.strip().split('\t')
    if rc == 0 and len(parts) == 2 and parts[1].isdigit() and since <= int(parts[1]) <= now + SLACK_S:
        return [parts[0]]
    return []


def changed_files(top, shas):
    """Paths the commits change against their parent (a merge commit gives none: git diff-tree's default)."""
    names = {}   # ordered set
    for sha in shas:
        rc, out = git(['diff-tree', '--no-commit-id', '--name-only', '-r', '--root', '-z', sha, '--'], top, 1.5)
        if rc == 0:
            names.update((n, None) for n in out.split('\0')[:MAX_NAMES] if n)
    return list(names)


def code_files(names):
    """The code among a commit's paths, tests last; none when a path is a doc: the commit carries its docs. The working
    log is neither docs nor code."""
    if any(lib.is_doc(n) for n in names):
        return []
    return sorted((n for n in names if not NOT_CODE_RE.search(n) and not lib.DOC_RE.search(n)),
                  key=lambda n: bool(TEST_RE.search(n)))


def history(top, oldest):
    """The call's oldest commit and its first-parent ancestors, newest first (at most MAX_RUN + 1), as
    (sha, committer time)."""
    rc, out = git(['log', '-n', str(MAX_RUN + 1), '--first-parent', '--no-show-signature', '--format=%H %ct',
                   oldest, '--'], top, 1.0)
    found = []
    for line in out.splitlines() if rc == 0 else []:
        parts = line.split()
        if len(parts) == 2 and parts[1].isdecimal():
            found.append((parts[0], int(parts[1])))
    return found


def main_folder(top):
    """The main worktree's folder ('' for a bare repo or a submodule)."""
    rc, out = git(['rev-parse', '--git-common-dir'], top, 1.0)
    common = out.strip()
    if rc != 0 or not common:
        return ''
    common = os.path.normpath(os.path.join(top, common))
    return os.path.dirname(common) if os.path.basename(common) == '.git' else ''


def local_docs(roots):
    """docs/ and _internal/ folders under roots that hold no tracked file: the docs outside git."""
    dirs = []
    for root in roots:
        for name in LOCAL_DIRS:
            p = os.path.join(root, name)
            if p in dirs or not os.path.isdir(p):
                continue
            rc, out = git(['ls-files', '-z', '--', name], root, 1.5)
            if rc == 0 and not out:
                dirs.append(p)
    return dirs


def doc_files(d, errors):
    """The visible files under a local docs folder that are not the working log (lib.is_log; the STATUS.md checkpoint
    the global rules put in an ignored docs/ is log too): hidden ones (.DS_Store from Finder, editor swap files) and
    the log change without an edit of the docs, as folder times do. Walk errors go to errors."""
    top = os.path.dirname(d)
    for dp, dns, fns in os.walk(d, onerror=errors.append):
        check_budget()
        dns[:] = [x for x in dns if not x.startswith('.') and x != 'node_modules' and x.lower() not in lib.LOG_DIRS]
        yield from (p for p in (os.path.join(dp, f) for f in fns if not f.startswith('.'))
                    if not lib.is_log(os.path.relpath(p, top)))


def newest_mtime(dirs):
    """(newest mtime of the docs files, whether every file was seen): a symlinked folder may lead anywhere and is
    not walked; an unreadable folder or file and more than MAX_WALK files leave the answer incomplete too."""
    newest, n, errors = 0.0, 0, []
    for d in dirs:
        if os.path.islink(d):
            errors.append(d)
            continue
        for p in doc_files(d, errors):
            n += 1
            if n > MAX_WALK:
                return newest, False
            try:
                newest = max(newest, os.lstat(p).st_mtime)
            except OSError as e:
                errors.append(e)
    return newest, not errors


def session_start(transcript):
    """Birth time of the session's transcript (macOS), or None."""
    if not isinstance(transcript, str) or not transcript:
        return None
    try:
        return getattr(os.stat(transcript), 'st_birthtime', None)
    except OSError:
        return None


def reminded(top, run, start, newest):
    """Whether a commit of run (first-parent ancestors of the call's oldest commit, newest first) made after the
    session start and the last docs change had the reminder: it changes code and no docs (a merge changes none), and
    the docs had not changed after its own previous commit (owner's decision 03.11.2026: one per run of commits with
    no docs change, without a state file). A commit the hook did not see (a terminal, a script, a rebase) counts too."""
    for i, (sha, t) in enumerate(run):
        if t <= max(start, newest):
            break
        before = run[i + 1][1] if i + 1 < len(run) else 0
        if newest >= max(start, before):
            continue
        if code_files(changed_files(top, [sha])):
            return True
    return False


def docs_state(dirs, transcript, runs):
    """'changed' when a local doc changed after the session started and after the previous commit (the first parent
    of the call's oldest commit); 'repeat' when in each repo a commit of this run already had the reminder
    (reminded); else 'unchanged', or 'unknown' when that cannot be told (no session start, a folder not walked in
    full: then the run starts at the newest change seen). runs: (toplevel, history) of each repo."""
    override = os.environ.get('DOC_REMINDER_LOCAL')
    if override in ('changed', 'unchanged'):
        return override
    start = session_start(transcript)
    if start is None:
        return 'unknown'
    replay = os.environ.get('DOC_REMINDER_DOCS_MTIME')
    try:
        newest, complete = (float(replay), True) if replay is not None else newest_mtime(dirs)
    except ValueError:
        return 'unknown'
    prev = max(h[1][1] if len(h) > 1 else 0 for _, h in runs)
    if newest >= max(start, prev):
        return 'changed'
    if all(reminded(top, h[1:], start, newest) for top, h in runs):
        return 'repeat'
    return 'unchanged' if complete else 'unknown'


def clip(s, n=80):
    return s if len(s) <= n else '…' + s[-(n - 1):]


def hint_of(files, roots):
    """lib.area_hint(), or None past the budget or on an error: the hint is extra, so the reminder goes out without it
    and the error log names the step."""
    try:
        check_budget()
        return lib.area_hint(files, roots)
    except Exception as e:
        log_error(HookError('area hint %s' % (e if isinstance(e, HookError) else type(e).__name__)))
        return None


def render(event, shas, code, dirs, worktree, state, hint=None):
    """The reminder as hook JSON of at most MAX_OUT bytes: long paths get shorter and at last go (a doc named in the
    hint then by what it is), then the hint goes; the instruction stays whole. hint: lib.area_hint()."""
    what = 'commit %s changes' % shas[0][:7] if len(shas) == 1 else 'commits %s change' % ', '.join(
        s[:7] for s in shas[:3])
    seen = ('did not change in this session since the previous commit' if state == 'unchanged' else
            'could not be checked for this session')
    ask = ('. Update the docs this change affects before a push or deploy and name them in the summary, or say there '
           'why none is affected. If you cannot write them (worktree, hook, access), ask the user now via '
           'AskUserQuestion')
    ask += ('; with the OK: copy into the worktree, Edit, cp back if the main file is unchanged (Bash cp is not '
            'blocked).' if worktree and dirs else '.')
    # characters per path, a folder twice that; 0: no paths, fits any names; at last without the hint
    for width, with_hint in ((80, True), (40, True), (16, True), (0, True), (0, False)):
        sample = ' (%s%s)' % (', '.join(clip(c, width) for c in code[:3]),
                              ', +%d' % (len(code) - 3) if len(code) > 3 else '') if width else ''
        text = ('doc-reminder: %s %d file%s%s and no docs (README, docs/, *.md; the working log is no docs: STATUS, '
                'progress, plans, decisions, CHANGELOG)') % (what, len(code), '' if len(code) == 1 else 's', sample)
        if hint and with_hint:
            names = dict.fromkeys(clip(p, 2 * width) if p and width else label for p, label in hint[1])
            text += '; it touches %s: check %s' % (', '.join(hint[0]), ', '.join(list(names)[:4]))
        if dirs:
            text += '; the docs outside git (the log aside) %s%s' % (seen, ': ' + ', '.join(
                clip(d, 2 * width) + '/' for d in dirs[:3]) if width else '')
            if worktree:
                text += ' (in the main folder; copies in this worktree do not count)'
        out = json.dumps({'hookSpecificOutput': {'hookEventName': event, 'additionalContext': text + ask}},
                         ensure_ascii=False)
        if len(out.encode('utf-8')) <= MAX_OUT:
            break
    return out


def main():
    if lib is None:
        raise HookError('lib %s' % LIB_ERROR)
    raw = sys.stdin.buffer.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT:
        return dbg('input too big')
    try:
        d = json.loads(raw.decode('utf-8', 'replace'))
    except ValueError:
        return dbg('not json')
    if not isinstance(d, dict):
        return dbg('not an object')
    event, ti, cwd = d.get('hook_event_name'), d.get('tool_input'), d.get('cwd')
    if event not in EVENTS or d.get('tool_name') != 'Bash' or not isinstance(ti, dict) or not isinstance(
            ti.get('command'), str):
        return dbg('other event, tool or input')
    cwd = cwd if isinstance(cwd, str) and os.path.isabs(cwd) else ''
    try:
        now = float(os.environ.get('DOC_REMINDER_NOW') or time.time())
    except ValueError:
        now = time.time()
    dur = d.get('duration_ms')
    ok = isinstance(dur, (int, float)) and not isinstance(dur, bool) and 0 <= dur <= 86_400_000
    since = now - (dur / 1000.0 if ok else NO_DURATION_S) - SLACK_S
    repos = []   # (toplevel, shas)
    for t in targets(ti['command'], cwd):
        top = toplevel(t)
        if top and top not in [r[0] for r in repos]:
            repos.append((top, commits(top, since, now)))
    repos = [r for r in repos if r[1]]
    if not repos:
        return dbg('no commit in the window')
    todo, with_docs = [], False   # (toplevel, shas, code) of each repo whose commits change code and no docs
    for top, shas in repos:
        names = changed_files(top, shas)
        if any(lib.is_doc(n) for n in names):
            with_docs = True
            continue
        code = code_files(names)
        if code:
            todo.append((top, shas, code))
    if not todo:
        return dbg('docs in the commit' if with_docs else 'no code in the commit')
    roots, worktree = [], False
    for top, _, _ in todo:
        main_dir = main_folder(top)
        in_worktree = bool(main_dir and main_dir != top)
        worktree = worktree or in_worktree
        root = main_dir if in_worktree else top   # a worktree's own docs/ holds copies being edited or a checkpoint
        if root not in roots:
            roots.append(root)
    dirs = local_docs(roots)
    state = 'unchanged'
    if dirs:
        state = docs_state(dirs, d.get('transcript_path'), [(top, history(top, shas[-1])) for top, shas, _ in todo])
    if state == 'changed':
        return dbg('local docs changed in this session since the previous commit')
    if state == 'repeat':
        return dbg('no docs change since the reminder earlier in this run')
    files = [c for _, _, code in todo for c in code]
    out = render(event, [s for _, shas, _ in todo for s in shas], files, dirs, worktree, state,
                 hint_of(files, roots))
    sys.stdout.buffer.write((out + '\n').encode('utf-8'))   # UTF-8 whatever the locale


if __name__ == '__main__':
    # hard stop at 4 s: BUDGET_S is checked between steps only; the shim then logs "ShimExit 142" and still exits 0
    signal.alarm(4)
    try:
        main()
    except BaseException as e:  # fail open, but leave a trace for doctor.sh
        dbg('error %s' % type(e).__name__)
        log_error(e)
    sys.exit(0)
