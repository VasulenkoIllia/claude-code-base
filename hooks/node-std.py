#!/usr/bin/env python3
"""node-std: SessionStart hook, started by node-std.sh (stdlib, 3.9+). At the start of a new conversation it looks at
the project twice and prints what it has to say as one hookSpecificOutput.additionalContext, a line per check (each
under 1000 B). A check that breaks, or runs out of its time, leaves the other its say: of the 5 s budget the packs
check may take 2, the Node check has the rest. The locks of the two state files are taken only when both checks have
decided, for the lines and their records: a slow check never holds one.
1. Packs of the library (ADR-007, owner's decisions B7 and the quiz of 22.11.2026), made first, so before both early
exits of the Node check: the packs of ~/.claude/packs/catalog.json whose file signals match the root of the project
and that its settings neither enable nor refuse, by pack_signals.py next to this file, the code `claude-pack suggest`
runs. The line names them and asks the model to tell the owner and to offer the skill library-advisor; the hook
enables nothing. A pack is named once per project, and a project is judged once per version of the signals of the
catalog, "nothing" included: the state file (~/.claude/state/pack-hint.jsonl, one JSON line: the version, the project,
the packs named, the date) keeps both. Settings or a signal file that did not read, and a project that has 3 packs on
(no room), leave no "judged" record: the next session looks again. The project is the repository of the session's
folder, with no git the folder itself. Silent with no catalog (the public version), where .git is a file (a git
worktree: the local settings are in the main repository; a submodule too) and in a folder that is no project (the home
folder, a folder of ~/.claude).
2. The Node standard: once per project and standard it tells the model that the project's Node is behind the base's
standard and asks it to propose the upgrade as a task of its own: a new-session card whose brief follows
~/.claude/skills/new-project/upgrade.md (owner's decisions 03.11.2026).
The project is the git repository of the session's folder (searched up to the home folder; outside it, or with no
git, the folder itself), a worktree counted as its main repository when main lists it, with a package.json in its root
that holds a JSON object. The skill's node_std.py decides: the oldest Node of `.nvmrc`, of the node images of the
Dockerfiles and Compose files and of the CI, against versions.json. Behind the standard, end of life within 6 months or
past it, or no Node pinned: a line; on the standard or newer: silence. Then the verdict goes into the state file
(~/.claude/state/node-std.jsonl, one JSON line: the standard's major, the main repository, the state, the date) under
a lock, and the project stays silent until the standard's major changes; an unknown one (a place not read or with no
plain version) is not recorded, the next session judges again.
Speaks only at the start of a new conversation (source startup or clear). A resume, a fork and a compaction go on
with an old one, and the app resumes an old session with no prompt to follow (seen 08.11), so a line would be
recorded as said and never reach the model. Silent for a subagent (agent_id) and outside a project too.
The lines hold only numbers, dates, pack names of the catalog (each checked against the form of a pack name) and fixed
words: the repository is untrusted.
Never blocks: always exit 0. An error or the time gone: silence of that check, no record of it and one line (time,
class, step) in ~/.claude/logs/node-std.err, which scripts/doctor.sh shows; the steps of the packs check are packs
and pack-state, of the Node check skill, verdict and state, a record that was not written adds -record. An input
field of another type or missing: a ShapeDrift line, then on as before.
Env (tests only): NODE_STD_SKILL=<folder of node_std.py>, NODE_STD_VERSIONS=<versions.json>, NODE_STD_STATE=<file>,
NODE_STD_PACK_STATE=<file>, NODE_STD_ERRLOG=<file>, NODE_STD_TODAY=YYYY-MM-DD, NODE_STD_BUDGET_S=<seconds>,
NODE_STD_DEBUG=1 (the reasons for silence on stderr, the ones of the packs check after "packs:").
"""
import datetime
import json
import os
import re
import signal
import stat
import sys
import time

sys.dont_write_bytecode = True  # no __pycache__ in the managed hooks folder or in the skill
HOOKS = os.path.dirname(os.path.abspath(__file__))
sys.path.append(HOOKS)  # -I drops the script folder from sys.path; at the end: nothing of it stands before the stdlib
from node_std_lib import append, kept, locked, named, open_state, recorded  # noqa: E402 (after the path line)
SKILLS = (os.path.join(HOOKS, '..', 'skills', 'new-project'),
          os.path.join(HOOKS, '..', 'skills', 'own', 'new-project'))
MAX_INPUT = 1_000_000
ERR_LOG_MAX = 64_000   # bytes; then no more lines
DRIFT_CAP = 32_000     # ShapeDrift comes with every session while the input stays odd: room for a later error
BUDGET_S = 5.0         # settings.json gives the hook 10 s
PACKS_S = 2.0          # of the budget, what the packs check may take; the rest, 3 s or more, is the Node check's
GRACE_S = 0.5          # after a check that used the budget up: the time to say what the other one decided
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
HINT = ('library-hint: the files of this project match packs of the owner\'s library that are not enabled here: %s.'
        ' In your first reply tell the owner this in one sentence and offer to pick packs with the skill'
        ' library-advisor; run it only on the owner\'s yes (if the owner already asks what to connect, run it now).'
        ' Enable nothing without the owner\'s OK. The line comes once per project and pack.')
step = 'input'
deadline = 0.0         # time.monotonic() at which the budget ends; main sets it


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


def arm(share=None, least=0.001):
    """The alarm at the end of the hook's budget, or `share` seconds from now when that is sooner; never under `least`
    seconds: a spent budget still rings. With the hook's handler: a search of pack_signals borrows the signal."""
    left = deadline - time.monotonic()
    signal.signal(signal.SIGALRM, on_alarm)
    signal.setitimer(signal.ITIMER_REAL, max(min(left, share) if share else left, least))


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


def packs_part(root, today):
    """The packs of the library that fit the project by its files, each named once. Pending: the line, and the record
    that the project is judged for this version of the signals (also when there is nothing to name)."""
    global step
    step = 'packs'
    claude = os.path.realpath(os.path.expanduser('~/.claude'))
    path, git = os.path.join(claude, 'packs', 'catalog.json'), os.path.join(root, '.git')
    if not os.path.lexists(path):  # a catalog that is there and does not open is an error, logged by its class
        return debug('packs: no catalog')
    if os.path.lexists(git) and not os.path.isdir(git):
        return debug('packs: a git worktree')
    import pack_signals as lib
    project = os.path.realpath(root)
    if not lib.is_project(project, claude):
        return debug('packs: not a project folder')
    known, packs, version = lib.load(path)

    def compute(fd):
        global step
        judged, said = named(fd, version, project)
        if judged:
            return debug('packs: judged for this project and catalog')
        step = 'packs'
        try:
            fits, open_why = lib.fitting(project, known, packs)
        except lib.Unread:  # the project's own file: its doctor line says so, here the next session looks again
            return debug('packs: the settings of the project do not read')
        if open_why and said.issuperset(fits):  # no verdict on the project, nothing to say: no record and no lock
            return debug('packs: ' + open_why)

        def settle():
            judged, said = named(fd, version, project)
            if judged:
                return debug('packs: another session judged it')
            new = [name for name in fits if name not in said]
            if not new:
                debug('packs: ' + (open_why or 'nothing new to name'))
            if open_why and not new:  # another session named them meanwhile: no record
                return None
            record = {'catalog': version, 'project': project, 'packs': new, 'date': today.isoformat()}
            return HINT % ', '.join(new) if new else None, dict(record, unread=True) if open_why else record
        return settle
    step = 'pack-state'
    return kept(open_state('NODE_STD_PACK_STATE', 'pack-hint.jsonl'), 'pack-state', compute)


def node_part(root, today):
    """The Node of the project against the base's standard, said once per project and standard. Pending: the line,
    and the record of the verdict."""
    global step
    if not os.path.lexists(os.path.join(root, 'package.json')):
        return debug('no package.json')
    step = 'skill'
    ns, versions_path = skill()
    with open(versions_path, encoding='utf-8') as fh:
        versions = json.load(fh)
    std = str(versions['node'])
    step = 'verdict'
    project = main_repo(root)

    def compute(fd):
        global step
        if recorded(fd, std, project):
            return debug('said for this project and standard')
        step = 'verdict'
        pkg = ns.scaffold_gaps.package_of(root)
        if not pkg:  # a link, a special file, empty or not a JSON object: no project the standard can judge
            return debug('package.json is not a JSON object the hook reads')
        found = ns.places(root, ns.scaffold_project.project_files(root))
        state, oldest, end = ns.verdict(found, versions, today)
        if state == ns.UNKNOWN:  # a place not read or with no plain version: the next session judges again
            return debug('state ' + state)
        line = text(ns, state, oldest, end, found, versions, ns.manager_state(root, pkg, versions)) \
            if state in SPEAKS else None

        def settle():
            if recorded(fd, std, project):
                return debug('another session said it')
            if line is None:
                debug('state ' + state)
            return line, {'std': std, 'project': project, 'state': state, 'date': today.isoformat()}
        return settle
    step = 'state'
    return kept(open_state('NODE_STD_STATE', 'node-std.jsonl'), 'state', compute)


def answer_of(waits):
    """(line, record) of a check that still has something to say or to record, decided under the lock of its state
    file, else None. A busy lock, an error and the time gone are logged and cost that check alone: each has the rest
    of the budget, GRACE_S at the least."""
    global step
    step = waits.step
    try:
        arm(least=GRACE_S)
        if locked(waits.fd):
            return waits.settle()
        log('LockBusy ' + step)
    except TimeLimit:
        log('TimeLimit ' + step)
    except Exception as e:  # the state file of this check; the other one is settled all the same
        signal.setitimer(signal.ITIMER_REAL, 0)  # no alarm inside the handler
        log('%s %s' % (type(e).__name__, step))
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)  # no alarm between the checks, nor between the lines and the records
    return None


def settled(pending):
    """[(check, (line, record))] of the checks that have an answer."""
    answers = [(waits, answer_of(waits)) for waits in pending]
    return [(waits, got) for waits, got in answers if got is not None]


def checks(root, today, pending):
    """Both checks, each within its share of the budget; what one leaves to settle goes to `pending`."""
    for check, share in ((packs_part, PACKS_S), (node_part, None)):
        try:
            arm(share)
            waits = check(root, today)
            if waits is not None:
                pending.append(waits)
        except TimeLimit:  # out of its share: the other check keeps its own; out of the budget: one line says so
            log('TimeLimit ' + step)
            if time.monotonic() >= deadline:
                break
        except Exception as e:  # a check that broke leaves the other its say; the class and the step go to the log
            signal.setitimer(signal.ITIMER_REAL, 0)  # no alarm inside the handler
            log('%s %s' % (type(e).__name__, step))
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)  # no alarm between the checks


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
    today = datetime.date.fromisoformat(os.environ.get('NODE_STD_TODAY') or datetime.date.today().isoformat())
    pending = []
    try:
        try:
            checks(root, today, pending)
        except TimeLimit:  # a ring between the checks or in the handler of one: what is decided is said all the same
            log('TimeLimit ' + step)
        said = settled(pending)
        step = 'print'
        lines = [line for _, (line, _) in said if line is not None]
        if lines:  # the lines before their records: a failed write repeats a line later, never loses it
            print(json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart',
                                                     'additionalContext': '\n'.join(lines)}}), flush=True)
        for waits, (_, record) in said:
            step = waits.step + '-record'
            try:
                append(waits.fd, record)
            except Exception as e:  # wide on purpose: the record of the other check is written all the same
                log('%s %s' % (type(e).__name__, step))
    finally:
        for waits in pending:
            os.close(waits.fd)


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
    global deadline
    try:  # the handler and the timer inside: an alarm right after them still lands in the handler below
        deadline = time.monotonic() + budget()
        arm()
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
