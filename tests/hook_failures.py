"""hook_failures: the line of hook failures that tests/hint-delivered.py --doctor --days N prints for scripts/doctor.sh, on
the transcript reader of replay_common.py. A hook that fails never blocks, so nothing else shows it. It counts the hook
attachments of a type in UNATTRIBUTED (tests/hint_common.py) and hook_success with a failed fork in stderr, whichever hook
wrote them: every project with this repo and /tmp, subagents too, the last N days whatever the install, each uuid once
(a forked session's file starts with copies of the old chain). Stop hooks leave stop_hook_summary records, not
attachments: the base has none. A WARN when there are any, never another exit code. Output: counts, kinds, projects, the
local time of the last one; no text of a command or of stderr. Also a WARN for each reason a 0 would prove nothing:
transcripts or lines that could not be read, attachments of an unknown shape, BLIND_FILES transcripts with no hook
attachment at all. One process: this check exists for a machine that ran out of them."""
import collections

from hint_common import UNATTRIBUTED
from replay_common import list_files, local_date, proj_name, records, window_start

FORK_ERROR = 'fork: Resource temporarily unavailable'   # bash in a hook's stderr: the process limit ran out
FORK_KIND = 'hook_success with a failed fork'
# the other attachment types of Claude Code 2.1.307 and 2.1.309: no failures; any other type is a format change
KNOWN = UNATTRIBUTED + ('hook_success', 'hook_additional_context', 'hook_blocking_error', 'hook_stopped_continuation',
                        'hook_system_message', 'hook_permission_decision')
BLIND_FILES = 5   # this many transcripts and no hook attachment seen: the reader is blind
SHOW_NAMES = 5   # projects named in the line; the rest only counted
LEGEND = ('      (a hook that fails does not block: the call goes on with its check undone and the chat shows nothing; only '
          'bash-guard asks on a fork failed outside $(...). A failed fork: the process limit ran out, look for heavy '
          'parallel runs at that time. The line clears when the failure is %d days old)')   # 8 spaces in doctor.sh, as its other legends


def failure_kind(a):
    """A hook attachment's kind of failure, or None: an error or a cancel of any hook that leaves attachments (Stop does
    not); a run with a failed fork in stderr reads as a success, but the hook went on with part of its check undone."""
    kind, err = a.get('type'), a.get('stderr')
    if kind in UNATTRIBUTED:
        return kind
    return FORK_KIND if kind == 'hook_success' and isinstance(err, str) and FORK_ERROR in err else None


def is_unread(a):
    """A hook attachment failure_kind() cannot judge: an unknown type, or a hook_success with no stderr text."""
    kind = a.get('type')
    return kind not in KNOWN or (kind == 'hook_success' and not isinstance(a.get('stderr'), str))


def scan(proj, path, since, agg):
    """Add the hook attachments of one transcript, main or subagent, from since on (UTC as in transcripts) to agg. Only
    lines with a hook type are parsed: a week of transcripts is gigabytes, its hook attachments are a few hundred lines."""
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            for d in records(fh, agg, keep=lambda line: '"hook_' in line, dedup=True):
                a = d.get('attachment') if d.get('type') == 'attachment' else None
                if not isinstance(a, dict) or not str(a.get('type')).startswith('hook_') or d['timestamp'][:19] < since:
                    continue
                agg['hooks'] += 1
                agg['unread'][str(a['type'])[:40]] += is_unread(a)
                kind, uid = failure_kind(a), d.get('uuid')
                if kind:
                    agg['failures'][uid if isinstance(uid, str) else (path, agg['hooks'])] = (d['timestamp'], kind, proj)
    except OSError:
        agg['bad_files'] += 1


def by_count(counts):
    """A Counter as text with no zeros, the biggest first, at most SHOW_NAMES."""
    named = [c for c in counts.most_common() if c[1]]
    more = len(named) - SHOW_NAMES
    return ', '.join('%s %d' % c for c in named[:SHOW_NAMES]) + (', %d more' % more if more > 0 else '')


def report(days, projects):
    """Print the line of hook failures of the last days, a WARN with its legend when there are any, and a WARN for each
    reason its 0 would prove nothing. projects: the folder of the project folders."""
    epoch, since = window_start(days)
    files = list_files(epoch, True, projects=projects)[0]
    agg = {'hooks': 0, 'failures': {}, 'unread': collections.Counter(), 'bad': 0, 'bad_files': 0}
    for proj, path in files:
        scan(proj, path, since, agg)
    failures = list(agg['failures'].values())
    line = 'hook failures: %d in %d days (%d transcripts, %d hook attachments)' % (
        len(failures), days, len(files), agg['hooks'])
    if failures:
        ts, _, proj = max(failures)
        print('WARN: %s: %s; by project: %s; last %s local time, %s' % (
            line, by_count(collections.Counter(f[1] for f in failures)),
            by_count(collections.Counter(proj_name(f[2])[:40] for f in failures)),
            local_date(ts, '%Y-%m-%d %H:%M'), proj_name(proj)[:40]))
        print(LEGEND % days)
    else:
        print(line)
    if agg['bad_files']:
        print('WARN: hook failures: %d transcripts could not be read: their failures are not counted' % agg['bad_files'])
    if agg['bad']:
        print('WARN: hook failures: %d lines with a hook type could not be parsed: their failures are not counted' % agg['bad'])
    if any(agg['unread'].values()):
        print('WARN: hook failures: attachments of an unknown shape: %s (a transcript format change? Compare with '
              'docs/compat.md): their failures are not counted' % by_count(agg['unread']))
    if len(files) >= BLIND_FILES and not agg['hooks']:
        print('WARN: hook failures: no hook attachment seen in %d transcripts (a transcript format change?): the 0 '
              'proves nothing' % len(files))
