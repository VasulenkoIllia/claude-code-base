#!/usr/bin/env python3
"""docs_state: for scripts/doctor.sh, read-only, one project folder: which big .md files are a working journal and
which docs of an area fell behind the code of that area (stdlib, 3.9+). The names come from the rule doc-reminder
uses (hooks/doc_reminder_lib.py), so the hook and doctor share one rule.

Usage: python3 -I scripts/docs_state.py <folder with doc_reminder_lib.py> <project folder> <lag days> <lag commits>
       <window days>, with the paths of the big .md files of the project on stdin, one per line, relative to it.

Prints, tab-separated:
  journal <path>                        a path from stdin whose name is_log() calls the working log (progress, tracker,
                                        plan, decisions, journal, log, WAVE-<n>, open questions); not STATUS (doctor
                                        checks it by its own limit), not CHANGELOG (a release history) and not a dated
                                        note (audit-2026-10-13.md: written once, it does not grow)
  area <area> <doc> <commits> <days>    a doc about deploy, schema, API or integrations, found by name as doc-reminder
                                        finds it, with <commits> commits (>= lag commits, merges aside, in the last
                                        window days) that touch the area's paths after its last change, the newest of
                                        them <days> days (> lag days) after it. The last change is the doc's last commit,
                                        or the file time when git has none (docs outside git). The README has its own
                                        check in doctor, so the areas it documents (env, commands) are left out.
A folder git cannot read prints no area line: doctor names such a repo itself. Exit 0; 2 on bad usage.
"""
import os
import subprocess
import sys

sys.dont_write_bytecode = True   # the library is imported from hooks/ of the repo: leave no __pycache__ there
GIT_LOCAL = ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES',
             'GIT_COMMON_DIR', 'GIT_PREFIX')   # what a git hook exports: never the caller's repo
GRACE_S = 3600        # a commit within an hour of the doc's change belongs to that change (docs outside git)
GIT_TIMEOUT_S = 60
NOT_JOURNAL = ('status', 'changelog')


def git(folder, *args):
    """stdout of git in folder, or '' when git fails, takes too long or is not there."""
    env = {k: v for k, v in os.environ.items() if k not in GIT_LOCAL}
    env['GIT_CEILING_DIRECTORIES'] = os.path.dirname(folder)   # a broken .git must not send git looking upwards
    try:
        p = subprocess.run(['git', '--no-optional-locks', '-C', folder, '-c', 'core.quotePath=false'] + list(args),
                           env=env, capture_output=True, timeout=GIT_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        return ''
    return p.stdout.decode('utf-8', 'replace') if p.returncode == 0 else ''


def journals(lib, paths):
    """The paths whose file name is a working-log name; STATUS, CHANGELOG and dated notes aside."""
    out = []
    for path in paths:
        name = path.rsplit('/', 1)[-1]
        _, words = lib.words_of(name)
        if words and words[0] not in NOT_JOURNAL and not lib.DATE_RE.search(name.lower()) and lib.is_log(name):
            out.append(path)
    return out


def doc_time(folder, rel):
    """When the doc last changed: its last commit, else the file time; None when neither can be read."""
    t = git(folder, 'log', '-1', '--format=%ct', '--', rel).strip()
    if t.isdigit():
        return int(t)
    try:
        return int(os.stat(os.path.join(folder, rel)).st_mtime)
    except OSError:
        return None


def behind(lib, folder, lag_days, lag_commits, window_days):
    """(area, doc, commits after its last change, days from that change to the newest of them) per doc behind."""
    log = git(folder, 'log', '--since=%d days ago' % window_days, '--no-merges', '--name-only', '--format=%x01%ct')
    commits = []
    for block in log.split('\x01')[1:]:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if lines and lines[0].isdigit():
            commits.append((int(lines[0]), lines[1:]))
    if not commits:
        return []
    names, out = lib.doc_names(folder), []
    for area, rx, keys, _ in lib.AREAS:
        if keys == ('readme',):
            continue
        times = [ct for ct, files in commits if any(rx.search(f) for f in files)]
        if len(times) < lag_commits:
            continue
        for doc in [n for n in names if lib.about(n, keys)][:2]:
            t = doc_time(folder, doc)
            after = [ct for ct in times if t is not None and ct > t + GRACE_S]
            if len(after) >= lag_commits and (max(after) - t) // 86400 > lag_days:
                out.append((area, doc, len(after), (max(after) - t) // 86400))
    return out


def main():
    if len(sys.argv) != 6 or not all(a.isdigit() for a in sys.argv[3:]):
        sys.stderr.write(__doc__)
        return 2
    sys.path.insert(0, sys.argv[1])
    import doc_reminder_lib as lib
    folder = os.path.abspath(sys.argv[2])
    lag_days, lag_commits, window_days = (int(a) for a in sys.argv[3:])
    for path in journals(lib, [ln.rstrip('\n') for ln in sys.stdin if ln.strip()]):
        print('journal\t%s' % path)
    for row in behind(lib, folder, lag_days, lag_commits, window_days):
        print('area\t%s\t%s\t%d\t%d' % row)
    return 0


if __name__ == '__main__':
    sys.exit(main())
