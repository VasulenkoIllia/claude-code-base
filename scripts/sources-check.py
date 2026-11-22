#!/usr/bin/env python3
"""sources-check.py: which sources of the vendored files moved from their pins. Read-only for GitHub and for the tree.

Usage (the network and `gh` with a sign-in, except --doctor):
  python3 -I -B scripts/sources-check.py                        every source, a line each; then the state file
  python3 -I -B scripts/sources-check.py --source <owner/name>  one source, with our files whose original changed
  python3 -I -B scripts/sources-check.py --doctor               offline, for doctor.sh: how old the last full check is
  --tree <dir>: another tree than the repo of this script (tests).

The sources are the GitHub repos named by vendor/items.tsv (the core) and packs/*/vendor/items.tsv (the packs library),
a row per pair "our file and its path in the source" (the format: scripts/vendor_items.py). For each repo three calls
of `gh api` (scripts/sources_github.py): the repo (renamed, archived, a fork, no longer public), the head commit of its
default branch, the tree of that commit; one more per pin that is not the head: a repo that no longer has the commit of
our pin is said so. The original of a row changed when the blob at its path in the head tree is not the blob at the
pin: the column upstream_blob of a derived or patched file, the git blob id of our own file for a verbatim one (it
equals the source at the pin). A path that is gone is looked for by that blob, so a file the source only moved is named
with its new place. `compare` of the API is not used (it lists 300 files at most); a tree GitHub cuts short leaves its
source not checked. The numbers count our files, not rows: a file made of several originals has a row for each and
takes the worst state of them (gone, then changed). Only a failure that is not about one source (no gh, no sign-in,
a rate limit, no answer to the first call about a repo) stops the run.

Nothing is updated and no file of a source is fetched: an update of a source is a release of its own. Text of a
source never reaches the output: ids, names and dates of the API are checked by form; a name the source chose (a path
of its tree, the new name of its repo) is printed as data, cut, with every character outside a short list replaced.

A run over every source that got every answer writes CLAUDE_HOME/state/sources-check.json (default ~/.claude): when it
was, of which tree, how many sources moved, how many of our files have an original that changed or is gone. --source,
and a run with a source not checked, leave the file as it was. --doctor reads only that file: a WARN when there is
none, when it does not read, when it is of another tree, or when the check is over MAX_AGE_DAYS days old.
Exit: 0 every source checked (moved or not) | 1 a source not checked, or the state file not written | 2 bad usage, or
items.tsv or a file it names does not read. --doctor: always 0.
"""
import argparse
import collections
import datetime
import hashlib
import json
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I drops the script folder from sys.path
import sources_github as github  # noqa: E402

HEADER = 'path class repo pin upstream_path license sha256 upstream_blob reviewed patch'.split()   # scripts/vendor_items.py
CLASSES = ('patched', 'verbatim', 'derived')
MAX_AGE_DAYS = 35      # owner's decision 22.11.2026: the rhythm of the stack line of doctor.sh (versions.json)
LISTED_MAX = 3         # our files under one original, new places of a moved file: so many are named, the rest counted
COUNT_MAX = 10 ** 6    # a count of the state file above this is not one this tool wrote
TIME_FORMAT = '%Y-%m-%dT%H:%M:%SZ'
STATE_FILE = 'sources-check.json'
COUNTS = ('sources', 'moved', 'files_changed', 'files_gone')
RANK = {'same': 0, 'changed': 1, 'gone': 2}
RUN_HINT = 'python3 -I -B scripts/sources-check.py in the base repo (the network and gh with a sign-in)'

Row = collections.namedtuple('Row', 'where base path cls repo pin upstream_path sha256 upstream_blob')
Finding = collections.namedtuple('Finding', 'row state now_at')   # state: same, changed, gone
shown = github.shown


class CheckError(Exception):
    """The tree does not read the way this tool needs: nothing is asked, exit 2."""


# ---------- the tree: rows of every items.tsv ----------

def items_files(tree):
    """(where, the folder its paths start at, the file) for the core and for every pack of the tree that has one."""
    found = [('core', tree, os.path.join(tree, 'vendor', 'items.tsv'))]
    packs = os.path.join(tree, 'packs')
    if os.path.isdir(packs):
        for name in sorted(os.listdir(packs)):
            path = os.path.join(packs, name, 'vendor', 'items.tsv')
            if os.path.lexists(path):
                found.append(('pack ' + shown(name), os.path.join(packs, name), path))
    return found


def not_a_file(path):
    """Something that is there and is no file to read: a folder, a pipe, a device (a read of one may never end)."""
    return os.path.lexists(path) and not os.path.isfile(path)


def row_problem(row):
    """What is wrong with a row of items.tsv for this tool, or nothing."""
    if row['class'] not in CLASSES:
        return 'class is not one of %s' % ', '.join(CLASSES)
    if not github.REPO.match(row['repo']) or any(part in ('.', '..') for part in row['repo'].split('/')):
        return 'repo is not owner/name'
    if not github.HEX40.match(row['pin']):
        return 'pin is not a full commit id (40 hex)'
    if row['upstream_path'] in ('', '-') or row['upstream_path'].startswith('/'):
        return 'upstream_path is not a path of the source'
    if not row['path'].strip() or os.path.isabs(row['path']) or '..' in row['path'].split('/'):
        return 'path leaves its folder'
    if row['class'] != 'verbatim' and not github.HEX40.match(row['upstream_blob']):
        return 'a %s file names the blob of its original at the pin (40 hex)' % row['class']
    return None


def read_rows(tree):
    """Every row of every items.tsv of the tree; a CheckError for the first thing that does not read."""
    rows = []
    for where, base, path in items_files(tree):
        name = shown(os.path.relpath(path, tree))
        if not_a_file(path):
            raise CheckError('%s is not a file' % name)
        try:
            with open(path, encoding='utf-8') as fh:
                lines = [line for line in fh.read().split('\n') if line.strip()]
        except (OSError, UnicodeDecodeError) as e:
            raise CheckError('%s does not read (%s): the tree is the repo of this script, or the one --tree names'
                             % (name, type(e).__name__)) from e
        if not lines or lines[0].split('\t') != HEADER:
            raise CheckError('%s: the first line is not the header %s' % (name, ' '.join(HEADER)))
        for number, line in enumerate(lines[1:], 2):
            cells = line.split('\t')
            if len(cells) != len(HEADER):
                raise CheckError('%s, line %d: %d fields, the header has %d' % (name, number, len(cells), len(HEADER)))
            row = dict(zip(HEADER, cells))
            problem = row_problem(row)
            if problem:
                raise CheckError('%s, line %d: %s' % (name, number, problem))
            rows.append(Row(where, base, row['path'], row['class'], row['repo'], row['pin'], row['upstream_path'],
                            row['sha256'], row['upstream_blob']))
    if not rows:
        raise CheckError('vendor/items.tsv has no row: nothing to check')
    return rows


def pinned_blob(row):
    """The git blob id of the row's original at its pin."""
    if row.cls != 'verbatim':
        return row.upstream_blob
    ours, path = '%s: %s' % (row.where, shown(row.path)), os.path.join(row.base, row.path)
    try:
        if not_a_file(path):
            raise CheckError('%s is not a file: a verbatim row needs the bytes of our file' % ours)
        with open(path, 'rb') as fh:
            raw = fh.read()
    except (OSError, ValueError) as e:   # ValueError: a path with a zero byte
        raise CheckError('%s does not read (%s): a verbatim row needs the bytes of our file' % (ours, type(e).__name__)) from e
    if hashlib.sha256(raw).hexdigest() != row.sha256:
        raise CheckError('%s has not the sha256 of its row: a verbatim file equals its source (bash scripts/verify.sh)' % ours)
    return hashlib.sha1(b'blob %d\0' % len(raw) + raw).hexdigest()   # the id git gives these bytes, not a secret


def findings(pairs, head):
    """A Finding per (row, blob at the pin): the original is the same, changed or gone at the head."""
    by_blob, out = None, []
    for row, pinned in pairs:
        now = head.blobs.get(row.upstream_path)
        if now == pinned:
            out.append(Finding(row, 'same', ()))
        elif now is not None:
            out.append(Finding(row, 'changed', ()))
        else:
            if by_blob is None:
                by_blob = collections.defaultdict(list)
                for path, sha in head.blobs.items():
                    by_blob[sha].append(path)
            out.append(Finding(row, 'gone', tuple(sorted(by_blob.get(pinned, ())))))
    return out


def file_states(found):
    """How many of our files are in each state: a file with several originals takes the worst state of them."""
    worst = {}
    for f in found:
        key = (f.row.where, f.row.path)
        if RANK[f.state] >= RANK[worst.get(key, 'same')]:
            worst[key] = f.state
    return collections.Counter(worst.values())


# ---------- the report ----------

def pins_of(rows):
    return sorted(set(row.pin for row in rows))


def source_line(repo, found, head):
    """(the line of one source, whether it moved)."""
    rows, states = [f.row for f in found], file_states(found)
    pins = pins_of(rows)
    moved = any(pin != head.sha for pin in pins)
    place = '%s -> head %s' % (', '.join(p[:8] for p in pins), head.sha[:8]) if moved else '%s is the head' % pins[0][:8]
    line = '  %-5s  %s: pin %s (%s); %s; %d file(s): the original of %d changed, %d gone' % (
        'moved' if moved else 'same', repo, place, head.day, ', '.join(sorted(set(r.where for r in rows))),
        sum(states.values()), states['changed'], states['gone'])
    return line + ''.join('; %s' % flag for flag in head.flags), moved


def detail_lines(repo, found, head):
    """Our files of one source whose original changed or is gone, grouped by the original."""
    out, by_original = [], collections.OrderedDict()
    for f in sorted((f for f in found if f.state != 'same'), key=lambda f: (f.state, f.row.upstream_path, f.row.where, f.row.path)):
        by_original.setdefault((f.state, f.row.upstream_path, f.now_at), []).append(f.row)
    for (state, original, now_at), rows in by_original.items():
        moved_to = '; the same bytes are now at %d path(s) of the source, the "data:" lines' % len(now_at) if now_at else ''
        out.append('    %-7s  %s%s' % (state, shown(original), moved_to))
        out.extend('               data: %s' % github.shown_name(place) for place in now_at[:LISTED_MAX])
        if len(now_at) > LISTED_MAX:
            out.append('               and %d more path(s) of the source' % (len(now_at) - LISTED_MAX))
        for row in rows[:LISTED_MAX]:
            out.append('               %s: %s (%s)' % (row.where, shown(row.path), row.cls))
        if len(rows) > LISTED_MAX:
            out.append('               and %d more of our files' % (len(rows) - LISTED_MAX))
    out.append('    the original of %d of our file(s) is as at the pin' % file_states(found)['same'])
    for pin in pins_of([f.row for f in found]):
        if pin != head.sha:
            out.append('    the changes of the source: https://github.com/%s/compare/%s...%s' % (repo, pin, head.sha))
    out.append('    a verbatim file takes the new bytes and sha256, a derived or patched one a look at the diff of its original '
               'and a decision; both as a release of the base')
    return out


def write_state(home, doc):
    folder = os.path.join(home, 'state')
    os.makedirs(folder, mode=0o700, exist_ok=True)
    tmp = os.path.join(folder, '.%s.%d.tmp' % (STATE_FILE, os.getpid()))
    try:
        with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as fh:
            json.dump(doc, fh, indent=1, sort_keys=True)
            fh.write('\n')
        os.replace(tmp, os.path.join(folder, STATE_FILE))
    except OSError:
        if os.path.lexists(tmp):
            os.unlink(tmp)
        raise


def ask_sources(repos, pairs, with_detail):
    """Asks GitHub about every repo in turn and prints its line. Returns (how many answered, how many moved, their findings)."""
    checked, moved_count, all_found = 0, 0, []
    for number, repo in enumerate(repos):
        mine = [pair for pair in pairs if pair[0].repo == repo]
        try:
            head = github.head_of(repo, pins_of([row for row, _ in mine]))
        except github.SourceError as e:
            print('  NOT CHECKED  %s: %s' % (repo, e))
            if not e.stop:
                continue
            if number + 1 < len(repos):
                print('  stopped: this failure is not about one source; the other %d source(s) were not asked' % (len(repos) - number - 1))
            break
        found = findings(mine, head)
        line, moved = source_line(repo, found, head)
        print(line)
        if with_detail:
            print('\n'.join(detail_lines(repo, found, head)))
        checked, moved_count = checked + 1, moved_count + (1 if moved else 0)
        all_found.extend(found)
    return checked, moved_count, all_found


def check(tree, home, only):
    """The run over the sources: prints the report, writes the state after a full one. Returns the exit code."""
    rows = read_rows(tree)
    repos = sorted(set(row.repo for row in rows))
    if only is not None:
        if only not in repos:
            raise CheckError('no row names the source %s; the sources: %s' % (shown(only), ', '.join(repos)))
        rows, repos = [row for row in rows if row.repo == only], [only]
    pairs = [(row, pinned_blob(row)) for row in rows]
    print('sources: %d, by %d row(s) of items.tsv (%s)' % (len(repos), len(rows), ', '.join(sorted(set(row.where for row in rows)))))
    checked, moved, found = ask_sources(repos, pairs, only is not None)
    states = file_states(found)   # over every source at once: a file with originals in two repos is one file
    total = dict(zip(COUNTS, (checked, moved, states['changed'], states['gone'])))
    unchecked = len(repos) - checked
    print('summary: %d source(s) checked, %d moved from the pin, the original of %d of our file(s) changed, %d gone%s'
          % (tuple(total[key] for key in COUNTS) + ('; NOT CHECKED: %d' % unchecked if unchecked else '',)))
    if only is not None:
        return 1 if unchecked else 0
    if unchecked:
        print('state: not written, the check is not full; the date of the last full check stays')
        return 1
    doc = dict(total, schema=1, tree=os.path.realpath(tree), checked_at=datetime.datetime.now(datetime.timezone.utc).strftime(TIME_FORMAT))
    try:
        write_state(home, doc)
    except OSError as e:
        print('state: NOT WRITTEN (%s): doctor.sh will not know of this check' % type(e).__name__)
        return 1
    print('state: %s written (%s)' % (os.path.join(short(home), 'state', STATE_FILE), doc['checked_at']))
    if total['moved']:
        print('next: --source <owner/name> lists our files of one source; nothing is updated here')
    return 0


# ---------- --doctor: the age of the last full check, offline ----------

def short(path):
    home = os.path.expanduser('~')
    return '~' + path[len(home):] if home not in ('', '/') and (path == home or path.startswith(home + os.sep)) else path


def count_of(doc, key):
    value = doc.get(key)
    return value if type(value) is int and 0 <= value <= COUNT_MAX else None


def state_of(path):
    """The state file as this tool writes it: (the time as text, the tree, the four counts), or the word for what is wrong."""
    try:
        if not_a_file(path):
            return 'does not read'
        with open(path, encoding='utf-8') as fh:
            doc = json.load(fh)
    except (OSError, ValueError, RecursionError):   # UnicodeDecodeError is a ValueError
        return 'does not read'
    doc = doc if isinstance(doc, dict) else {}
    counts, stamp, tree = [count_of(doc, key) for key in COUNTS], doc.get('checked_at'), doc.get('tree')
    if (type(doc.get('schema')) is not int or doc['schema'] != 1 or None in counts or counts[0] < 1 or counts[1] > counts[0]
            or not isinstance(stamp, str) or not github.ISO_TIME.match(stamp) or not isinstance(tree, str) or not tree.strip()):
        return 'is of another form'
    return stamp, tree, counts


def doctor_lines(home, tree, now):
    """The lines of doctor.sh: one `sources:` line of a check that reads; a WARN for none, a broken, a foreign or an old one."""
    path = os.path.join(home, 'state', STATE_FILE)
    name = os.path.join(short(home), 'state', STATE_FILE)
    unknown = 'when the sources were last checked is not known (%s writes it anew)' % RUN_HINT
    if not os.path.lexists(path):
        return ['  WARN: sources: never checked against their sources (no %s): %s' % (name, RUN_HINT)]
    state = state_of(path)
    if isinstance(state, str):
        return ['  WARN: sources: %s %s: %s' % (name, state, unknown)]
    stamp, checked_tree, counts = state
    try:
        when = datetime.datetime.strptime(stamp, TIME_FORMAT).replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return ['  WARN: sources: %s names no real time: %s' % (name, unknown)]
    if checked_tree != os.path.realpath(tree):   # the stored one is a realpath already; it is not printed: text of a file
        return ['  WARN: sources: the last full check (%s) was of another tree (%s names it), not of this base: %s'
                % (stamp[:10], name, RUN_HINT)]
    if when - now > datetime.timedelta(days=1):
        return ['  WARN: sources: %s names a time in the future (%s): %s' % (name, stamp[:10], unknown)]
    days = max(0, (now - when).days)
    out = ['  sources: checked %s (%d day(s) ago): %d source(s), %d moved from the pin, the original of %d of our file(s) '
           'changed, %d gone' % ((stamp[:10], days) + tuple(counts))]
    if days > MAX_AGE_DAYS:
        out.append('  WARN: sources: checked %s, over %d days ago: %s; an update of a source is a release of its own'
                   % (stamp[:10], MAX_AGE_DAYS, RUN_HINT))
    return out


def main(argv):
    ap = argparse.ArgumentParser(prog='sources-check.py', description=__doc__.split('\n\n')[0],
                                 epilog='The whole description: the head of this file.')
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--source', metavar='<owner/name>', help='one source, with our files whose original changed')
    mode.add_argument('--doctor', action='store_true', help='offline: the lines of doctor.sh about the last full check')
    ap.add_argument('--tree', metavar='<dir>', default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    help='the tree to read items.tsv from (default: the repo of this script)')
    args = ap.parse_args(argv)
    home = os.environ.get('CLAUDE_HOME') or os.path.join(os.path.expanduser('~'), '.claude')
    tree = os.path.abspath(args.tree)
    if args.doctor:
        print('\n'.join(doctor_lines(home, tree, datetime.datetime.now(datetime.timezone.utc))))
        return 0
    try:
        return check(tree, home, args.source)
    except CheckError as e:
        print('error: %s' % e, file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
