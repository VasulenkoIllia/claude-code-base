"""pack_signals: which packs of the library (ADR-007) fit a project folder by its files. One code for the two that
ask: claude-pack (`suggest`; tools/claude-pack.py in the repo of the base, ~/bin/claude-pack when installed) and the
hook node-std.py, which names the packs at the start of a session. Stdlib, 3.9+. Reads only: no write, no network, no
git; neither caller may ask for a permission prompt because of it.
A pack is proposed when the catalog gives it the status pilot or active and the project neither enables it nor has it
set to false (a false is the owner's refusal, whether `disable` or `disable --decline` wrote it). Signals are read in
the root of the project only, no walk of the tree: filesRead is a name or a glob there, of a file or a folder (a match
that a link takes out of the project does not count and is named as not read), manifestDeps a regex over a regular file
of the root (a bare name; up to MANIFEST_MAX bytes; a link, a pipe and a bigger file are not read; ^ and $ match at
every line, re.M; the search stops after REGEX_SECS, as the file is the project's and may be written to hang a
pattern), cwd a glob of the folder name. A signal file that is there and was not read is named: "no match" then means
"not known". What comes back is the text of the catalog and fixed words, never the text of a project file: a name of
the project's settings that is no pack name is left out.
"""
import errno
import fnmatch
import glob
import hashlib
import json
import os
import re
import signal
import stat
import time

CATALOG = 'library'
MAX_PACKS = 3            # per project (ADR-007: the skill listing holds about 30 000 characters)
NAME = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}\Z')
SETTINGS = os.path.join('.claude', 'settings.local.json')
ADVISED = ('pilot', 'active')   # a frozen pack is not proposed
MANIFEST_MAX = 1 << 20          # bytes of a project file a manifestDeps signal reads
REGEX_SECS = 1.0                # one manifestDeps search: the text is the project's and may be made to hang a pattern
SETTINGS_MAX = 1 << 20          # bytes of the settings.local.json of a project that a proposal reads
CATALOG_MAX = 4_000_000         # bytes of a catalog.json that `load` reads: a bigger one is not the base's
NO_ROOM = 'no room for one more pack'      # why `fitting` gives no verdict: the two fixed reasons
NOT_READ = 'a signal file was not read'
VERSION_CHARS = 16


class Unread(Exception):
    """The settings of a project do not say which packs it has on; the message says why."""


class CatalogShape(Exception):
    """A pack of the catalog has signals, or a name, of a shape this code does not read; the message says which."""


def packs_of(data):
    """{pack name: entry} of a parsed catalog.json. Another catalog or schema: KeyError, TypeError or AttributeError."""
    packs = data['packs'] if data.get('schema') == 1 and data.get('catalog') == CATALOG else None
    return dict((p['name'], p) for p in packs)


def is_project(root, claude):
    """Whether a folder can hold a project (both are real paths): not the home folder (its settings.local.json is a
    user file), not the root of the disk, not a folder of ~/.claude (`claude`) and not one that holds it."""
    home = os.path.realpath(os.path.expanduser('~'))
    inside = (claude + os.sep).startswith(root + os.sep) or (root + os.sep).startswith(claude + os.sep)
    return root not in (home, os.sep) and not inside


def read_settings(root, limit=0):
    """(the JSON object of <root>/.claude/settings.local.json, its file mode or None when there is no file). With a
    limit, a bigger file is not read: a proposal looks at every project, and one of them must not cost it its memory.
    The file is the project's and may change under the reader: it is opened once, never as a link itself and never
    to wait (a pipe), and judged by what was opened. (A folder on the way to it that is swapped for a link at that
    moment is followed; `fitting` and the tool look at .claude first, and all that comes back is which packs are named.)"""
    path = os.path.join(root, SETTINGS)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return {}, None
    except OSError as e:
        if e.errno == errno.ELOOP:   # the file itself is a link
            raise Unread('%s is not a regular file (a link or a folder): nothing written' % path)
        if os.path.lexists(path):    # the file is there and does not open
            raise Unread('%s is not readable JSON (%s): fix it first, nothing written' % (path, type(e).__name__))
        raise Unread('%s: %s' % (path, type(e).__name__))
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise Unread('%s is not a regular file (a link or a folder): nothing written' % path)
        if limit and st.st_size > limit:
            raise Unread('%s is over %d bytes: not read' % (path, limit))
        with os.fdopen(os.dup(fd), 'rb') as fh:
            raw = fh.read(limit + 1) if limit else fh.read()
        if limit and len(raw) > limit:   # it grew after the look at its size
            raise Unread('%s is over %d bytes: not read' % (path, limit))
        text = raw.decode('utf-8')
        data = json.loads(text) if text.strip() else {}   # a blank file: no settings yet, as Claude Code reads it
    except (OSError, ValueError, RecursionError) as e:   # RecursionError: brackets nested by the thousand
        raise Unread('%s is not readable JSON (%s): fix it first, nothing written' % (path, type(e).__name__))
    finally:
        os.close(fd)
    if not isinstance(data, dict) or not isinstance(data.get('enabledPlugins', {}), dict):
        raise Unread('%s: not a JSON object, or enabledPlugins is not one: nothing written' % path)
    return data, stat.S_IMODE(st.st_mode)


def states(data):
    """{pack: True or False} of the packs of the catalog `library` named in enabledPlugins. A key that is not a pack
    name is left out: the file may come with a cloned repo, and its text must not reach the output."""
    suffix = '@' + CATALOG
    return dict((k[:-len(suffix)], v is True) for k, v in data.get('enabledPlugins', {}).items()
                if k.endswith(suffix) and NAME.match(k[:-len(suffix)]))


def enabled(state, known):
    """The packs of the catalog a project has on, sorted; it holds MAX_PACKS of them."""
    return sorted(name for name, on in state.items() if on and name in known)


def signal_path(root, rel):
    """The path of a signal under the root of the project, None for one that would leave it."""
    parts = rel.split('/') if isinstance(rel, str) else ['']
    if not rel or os.path.isabs(rel) or rel.startswith('~') or any(p in ('', '.', '..', '**') for p in parts):
        return None
    return os.path.join(glob.escape(root), rel)


def advised(catalog):
    """[(pack, entry, filesRead, [(file, pattern, regex)], cwd)] of the packs to propose. Signals of another shape
    raise CatalogShape: a misread entry would propose a pack, or leave one out, for a wrong reason."""
    out = []
    for name, p in sorted(catalog.items()):
        if not isinstance(p, dict) or p.get('status') not in ADVISED:
            continue
        sig = p.get('signals', {})
        try:
            lists = [sig.get(k, []) for k in ('filesRead', 'cwd', 'manifestDeps')]
            ok = all(isinstance(x, list) for x in lists) and all(isinstance(x, str) for x in lists[0] + lists[1])
            # a path or a folder glob that can never match is a catalog this code misreads, not "no match"
            ok = ok and all(signal_path(os.sep, x) for x in lists[0]) and not any('/' in x or not x for x in lists[1])
            deps = [(d['file'], d['pattern'], re.compile(d['pattern'], re.M)) for d in lists[2]] if ok else []
            ok = ok and all(isinstance(f, str) and '/' not in f and f not in ('', '.', '..') for f, _, _ in deps)
        except (AttributeError, KeyError, TypeError, re.error):
            ok = False
        if not ok:
            raise CatalogShape(name)
        out.append((name, p, lists[0], deps, lists[1]))
    return out


def version(packs):
    """An id of what `advised` gave: the names, the statuses and the signals. The hook judges a project once per id, so
    a catalog that changed only a description or a cost asks for no new look."""
    shape = [[name, p.get('status'), files, [d[:2] for d in deps], cwds] for name, p, files, deps, cwds in packs]
    return hashlib.sha256(json.dumps(shape, sort_keys=True).encode('utf-8')).hexdigest()[:VERSION_CHARS]


def load(path):
    """(the packs of a catalog file by name, the ones to propose with their signals, the version of those signals) for
    a caller that prints pack names: a name of another form raises CatalogShape, as signals of another shape do. A
    file that does not open or parse raises what open, json and packs_of raise."""
    with open(path, 'rb') as fh:
        raw = fh.read(CATALOG_MAX + 1)
    if len(raw) > CATALOG_MAX:
        raise ValueError('the catalog is over CATALOG_MAX bytes')
    known = packs_of(json.loads(raw.decode('utf-8')))
    packs = advised(known)
    if not all(isinstance(pack[0], str) and NAME.match(pack[0]) for pack in packs):
        raise CatalogShape('a pack name')
    return known, packs, version(packs)


def read_manifest(root, name):
    """(the text of a file of the root or None, why a file that is there was not read or None)."""
    try:
        fd = os.open(os.path.join(root, name), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)   # a pipe must not hang it
    except (FileNotFoundError, NotADirectoryError):
        return None, None   # the project has no such file: the signal does not match
    except OSError as e:
        return None, 'a link' if os.path.islink(os.path.join(root, name)) else type(e).__name__
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None, 'not a regular file'
        if st.st_size > MANIFEST_MAX:
            return None, 'over %d bytes' % MANIFEST_MAX
        with os.fdopen(os.dup(fd), 'rb') as fh:
            return fh.read(MANIFEST_MAX).decode('utf-8', 'replace'), None
    except OSError as e:
        return None, type(e).__name__
    finally:
        os.close(fd)


class SlowPattern(Exception):
    pass


def searched(regex, text):
    """Whether the pattern is found in the text; None when the search ran over REGEX_SECS. A caller with an alarm of
    its own (the hook, for its time budget) keeps it: one due within REGEX_SECS ends the search itself, with the
    caller's handler; a later one is back after the search with the time it had left. (An alarm under a microsecond
    from ringing reads as none and is lost here: the hook sets its alarm anew after each check.)"""
    outer = signal.getitimer(signal.ITIMER_REAL)[0]
    if 0 < outer <= REGEX_SECS:
        return regex.search(text) is not None
    live = [True]

    def stop(_signum, _frame):
        if live:
            raise SlowPattern()
    began, old = time.monotonic(), signal.getsignal(signal.SIGALRM)
    try:   # the handler and the timer inside: whatever rings from here on, `finally` puts the caller's back
        signal.signal(signal.SIGALRM, stop)
        signal.setitimer(signal.ITIMER_REAL, REGEX_SECS)
        return regex.search(text) is not None
    except SlowPattern:
        return None
    finally:
        live.clear()   # the search is over: a ring from here on raises nothing
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)
        if outer:
            signal.setitimer(signal.ITIMER_REAL, max(outer - (time.monotonic() - began), 0.001))


def match_signals(root, files, deps, cwds):
    """(the file signals of a pack that match the project folder, the signal files that are there and were not read),
    both in the words of the catalog. Root only."""
    hits, skipped, real = [], [], os.path.realpath(root) + os.sep
    for pattern in files:
        path = signal_path(root, pattern)
        found = glob.glob(path) if path else []
        # a link (the file or a folder on the way to it) must not answer for something outside the project
        if any(os.path.exists(m) and (os.path.realpath(m) + os.sep).startswith(real) for m in found):
            hits.append(pattern)
        elif found:
            skipped.append('%s: a link that leaves the project or leads nowhere' % pattern)
    for name, pattern, regex in deps:
        text, why = read_manifest(root, name)
        found = searched(regex, text) if text is not None else False
        if why or found is None:
            skipped.append('%s: %s' % (name, why or 'the pattern ran over %g s' % REGEX_SECS))
        elif found:
            hits.append('%s ~ %s' % (name, pattern))
    hits.extend(p for p in cwds if fnmatch.fnmatchcase(os.path.basename(root), p))
    return hits, skipped


def fitting(root, known, packs):
    """(the packs of `advised` whose file signals match the project and that its settings do not name, why this is no
    verdict on the project or ''). No verdict: NOT_READ, a signal file there was not read, so a pack may be missing
    from the list; NO_ROOM, the project has MAX_PACKS packs on, so nothing is proposed and nothing was looked at.
    Raises Unread when the settings do not read or .claude is a link (the settings of another folder)."""
    if os.path.islink(os.path.join(root, '.claude')):
        raise Unread('%s/.claude is a link: not read' % root)
    state = states(read_settings(root, SETTINGS_MAX)[0])
    if len(enabled(state, known)) >= MAX_PACKS:
        return [], NO_ROOM
    names, why = [], ''
    for name, _, files, deps, cwds in packs:
        if name in state:
            continue
        hits, skipped = match_signals(root, files, deps, cwds)
        if skipped:
            why = NOT_READ
        if hits:
            names.append(name)
    return names, why
