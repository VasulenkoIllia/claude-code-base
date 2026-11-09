#!/usr/bin/env python3
"""hook-replay: run real history from Claude Code transcripts through an old and a new hook and compare.

Usage (from the repo root):
  python3 -I tests/hook-replay.py [--days 60] [--kind all|bash|prompts] [--old PATH] [--new PATH] [--match REGEX] [--dump]

  PATH is a hooks directory (with bash-guard.sh and/or secret-guard.sh) or one hook file.
  Defaults: --old ~/.claude/hooks (live), --new <repo>/hooks (candidate). --kind defaults to "all"
  for directories; for a single file it is taken from the name (bash-guard* / secret-guard*).
  Examples:
    python3 -I tests/hook-replay.py --days 60                         # live hooks vs repo hooks, both kinds
    python3 -I tests/hook-replay.py --days 7 --kind bash --old ~/claude-backups/2026-10-11/hooks-v1 \
        --new ~/.claude/hooks/bash-guard.sh

What it does:
  bash     Bash, Monitor and mcp__terminal__run_in_terminal calls (main sessions and subagents) go to
           bash-guard as {"tool_input":{"command":...},"cwd":...}. PATH is a gitleaks that finds nothing, then
           /usr/bin:/bin:/usr/sbin:/sbin, so no real repo is scanned. A cwd that no longer exists becomes an empty temp
           dir. A call with no command or an empty one is only counted (line "no command"): the hook asks on a call with
           no string command, but for Monitor on a WebSocket.
  prompts  Human prompts from main sessions (no isMeta/sidechain/tool results/command wrappers,
           <system-reminder> stripped) go to secret-guard as {"prompt":...} with LANG/LC_* unset
           (C locale; --utf8 sets LANG=en_US.UTF-8).

Quick replay: --match REGEX keeps only the calls and prompts it finds (case-insensitive) and prints how many it dropped.
It is for work in progress and does not replace the full replay: the regex must find every command the edit can change,
a line continuation (backslash, newline) inside its text too. The median of new asks is still over all working days.
The verdict is QUICK PASS or QUICK FAIL, and a kind with no call kept fails (pass --kind bash for a command regex).

Safety:
  - ~/.claude/projects is only read; the script writes nothing (a temp dir is the cwd and holds the error log of
    bash-guard-dirs.py, BASH_GUARD_ERRLOG, and the stand-in for gitleaks, and is removed);
    the only exception is --dump, which writes the changed items (raw) to research/replay-cache/ (gitignored, 0600);
  - commands and prompts are never executed: they only reach the hooks as stdin JSON;
  - output is aggregate counts plus redacted command shapes; prompts are never printed (only date and size);
  - sessions of this repo and of /tmp folders (hook audits with synthetic commands) are skipped unless
    --include-audit is given.
  - hook timeouts default to the ones in settings.json (bash-guard 15 s, secret-guard 5 s).

Gate (exit code): 0 = no new blocks, no new hook errors or timeouts, no line in the bash-guard error log, no ask
that goes away for no listed class, and median new asks per working day <= 1; 1 = gate failed; 2 = usage or setup error
(hook missing, a hook that ran another gitleaks). An ask may go away only for a class of lost_kind, each printed with its count and
shapes: an ask about the commit identity in a one-off repo under /tmp or for text only in heredoc bodies (lost_far: else
neither the folder nor a folder the command names, by cd, mkdir, git -C, git init or NAME=, is under /tmp), and the
others for a quoted heredoc of cat, tee, python or node, docker exec or docker volume rm on a name with a part e2e,
test, tmp, scratch or sandbox, docker compose config with its output in a file, and curl | sh over several lines. These
regexes are the gate's own, not the hook's code, and each class must explain its ask: the old hook does not ask once the
text of the class is gone (classes_left).
tests/hook-replay-test.py checks that gate offline on made-up results.

Runtime (2026-10-12, 8 workers): --days 60 about 4 min (~41k Bash calls, ~1.8k prompts); --days 180 bash about 5.5 min.
Reference: hooks-v1 -> v2 over 180 days gives blocks 326 -> 318 (7 force-push + 1 hooksPath false blocks gone)
and hook asks 221 -> 150.
"""
import argparse
import collections
import datetime
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I drops the script folder from sys.path
from replay_common import (HOME, REPO, blocks, list_files, local_date, log_lines, pct, records, sha,  # noqa: E402
                           short, window_start, write_dump)

SHELL_TOOLS = ('Bash', 'Monitor', 'mcp__terminal__run_in_terminal')
HOOK_FILES = {'bash': 'bash-guard.sh', 'prompts': 'secret-guard.sh'}
SAFE_PATH = '/usr/bin:/bin:/usr/sbin:/sbin'
TIMEOUTS = {'bash': 15.0, 'prompts': 5.0}   # as in ~/.claude/settings.json
DECISIONS = {'bash': ('allow', 'ask', 'block'), 'prompts': ('allow', 'warn', 'block')}
EXTRA = ('error', 'timeout')

# ---------------------------------------------------------------- extraction (read-only, in worker processes)
SR_RE = re.compile(r'<system-reminder>.*?</system-reminder>', re.S)
WRAPPER_RE = re.compile(r'^\s*<(command-name|command-message|local-command-stdout|local-command-stderr|'
                        r'local-command-caveat|bash-input|bash-stdout|bash-stderr|task-notification|'
                        r'user-prompt-submit-hook)')
SKIP_PREFIXES = ('[Request interrupted', 'This session is being continued', 'Caveat: ')


def wanted(kind):
    """The lines extract_file() parses: calls for bash, human prompts (no tool results) for prompts."""
    if kind == 'bash':
        return lambda line: '"tool_use"' in line
    return lambda line: '"user"' in line and '"tool_use_id"' not in line


def extract_file(job):
    """Return (items, bad_lines, ids of calls with no command). Items: bash -> (id, tool, cmd, cwd, date); prompts ->
    (uuid, text, date)."""
    kind, path, cutoff = job
    items, n, no_command = [], collections.Counter(), []
    try:
        fh = open(path, 'r', encoding='utf-8', errors='replace')
    except OSError:
        return items, 1, no_command
    with fh:
        for d in records(fh, n, wanted(kind)):
            ts = d['timestamp']
            if ts[:19] < cutoff:
                continue
            msg = d.get('message') or {}
            if not isinstance(msg, dict):
                continue
            content = msg.get('content')
            if kind == 'bash':
                for b in blocks(d, 'tool_use'):
                    if b.get('name') not in SHELL_TOOLS:
                        continue
                    cmd = (b.get('input') or {}).get('command')
                    if isinstance(cmd, str) and cmd:
                        items.append((b.get('id') or '', b.get('name'), cmd, d.get('cwd') or '', local_date(ts)))
                    else:
                        no_command.append(b.get('id') or '')
                continue
            # prompts
            if d.get('type') != 'user' or d.get('isMeta') or d.get('isSidechain') or d.get('isCompactSummary'):
                continue
            if d.get('toolUseResult') is not None or msg.get('role') != 'user':
                continue
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                if any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in content):
                    continue
                text = '\n'.join(b.get('text') or '' for b in content if isinstance(b, dict) and b.get('type') == 'text')
            else:
                continue
            text = SR_RE.sub('', text).strip()
            if not text or WRAPPER_RE.match(text) or text.startswith(SKIP_PREFIXES):
                continue
            items.append((d.get('uuid') or '', text, local_date(ts)))
    return items, n['bad'], no_command


def extract(kind, files, cutoff, jobs):
    """Collect occurrences, deduplicated by tool_use id / prompt uuid (resumed sessions repeat history)."""
    seen, rows, bad, no_command = set(), [], 0, set()
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        results = ex.map(extract_file, [(kind, f, cutoff) for _, f in files], chunksize=4)
        for (proj, _), (items, b, c) in zip(files, results):
            bad += b
            no_command.update(c)
            for it in items:
                if it[0]:
                    if it[0] in seen:
                        continue
                    seen.add(it[0])
                rows.append((proj,) + it[1:])
    return rows, bad, len(no_command)

# ---------------------------------------------------------------- hook runs (stdin JSON only)


def classify_bash(rc, out, err):
    if rc == 2:
        first = (err.strip().splitlines() or [''])[0]
        return 'block', norm_reason(first)
    if rc != 0:
        return 'error', 'rc=%d' % rc
    if out.strip():
        try:
            hso = json.loads(out).get('hookSpecificOutput') or {}
        except (ValueError, AttributeError):
            return 'error', 'bad JSON on stdout'
        pd = hso.get('permissionDecision')
        if pd in ('ask', 'deny'):
            return ('ask' if pd == 'ask' else 'block'), norm_reason(hso.get('permissionDecisionReason') or '')
    return 'allow', ''


def classify_prompt(rc, out, err):
    if rc == 2:
        return 'block', ''
    if rc != 0:
        return 'error', 'rc=%d' % rc
    return ('warn' if 'additionalContext' in out else 'allow'), ''


def norm_reason(r):
    r = re.sub(r'^(BLOCKED by )?[a-z-]+-guard:\s*', '', r.strip())
    r = re.split(r'\. | \(', r, maxsplit=1)[0]
    return r[:70]


def bash_payload(tool, cmd, cwd, workdir):
    return json.dumps({'session_id': 'hook-replay', 'hook_event_name': 'PreToolUse', 'tool_name': tool,
                       'tool_input': {'command': cmd}, 'cwd': cwd if cwd and os.path.isdir(cwd) else workdir},
                      ensure_ascii=False).encode('utf-8')


def run_hook(hook, payload, env, timeout, workdir, classify):
    t = time.perf_counter()
    try:
        p = subprocess.run(['/bin/bash', hook], input=payload, capture_output=True, timeout=timeout,
                           env=env, cwd=workdir)
    except subprocess.TimeoutExpired:
        return 'timeout', '', time.perf_counter() - t
    dec, reason = classify(p.returncode, p.stdout.decode('utf-8', 'replace'), p.stderr.decode('utf-8', 'replace'))
    return dec, reason, time.perf_counter() - t

# ---------------------------------------------------------------- redaction of command shapes


HEREDOC_RE = re.compile(r'<<-?\s*([\'"]?)([A-Za-z_][A-Za-z0-9_]*)\1')
QUOTED_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\'[^\']*\'', re.S)
def project_names_rules():
    """Folder names in ~/WebstormProjects (4+ chars; '-', '_' and ' ' interchangeable) are client names."""
    try:
        names = [n for n in os.listdir(os.path.join(HOME, 'WebstormProjects')) if len(n) >= 4 and n[0] != '.']
    except OSError:
        return []
    alts = sorted(('[-_ ]'.join(map(re.escape, re.split(r'[-_ ]', n))) for n in names), key=len, reverse=True)
    return [(re.compile(r'(?<![A-Za-z0-9])(%s)' % '|'.join(alts), re.I), '<PROJECT>')] if alts else []


SHAPE_RULES = [
    (re.compile(r'WebstormProjects/(?:\\.|[^/\s"\'<>;&|\\])+'), '<PROJECT>'),
] + project_names_rules() + [
    (re.compile(r'\b([a-z][a-z0-9+.-]*://)[^\s/"\'<>]+', re.I), r'\1<HOST>'),
    (re.compile(r'[\w.+-]+@[\w-]+(\.[\w-]+)+'), '<EMAIL>'),
    (re.compile(r'\b\d{1,3}(\.\d{1,3}){3}\b'), '<IP>'),
    (re.compile(r'=\S+'), '=<R>'),
    (re.compile(r'(sshpass\s+-p|--password|--passwd|--token|--secret|--api-key)(\s+)\S+', re.I), r'\1\2<R>'),
    (re.compile(r'(curl\b[^|;&\n]*?\s)(-u|--user)\s+\S+'), r'\1\2 <R>'),
    (re.compile(r'(?<!\S)-p(\S{4,})'), '-p<R>'),
    (re.compile(r'[A-Za-z0-9+/=_.-]{32,}'), '<R>'),
    (re.compile(r'[A-Za-z0-9_-]{16,}'), '<R>'),
    (re.compile(r'\+?\d[\d\s()-]{8,}\d'), '<N>'),
]


def collapse_heredocs(s):
    lines, out, i = s.split('\n'), [], 0
    while i < len(lines):
        line = lines[i]
        i += 1
        for m in HEREDOC_RE.finditer(line):
            n = 0
            while i < len(lines) and lines[i].strip() != m.group(2):
                i += 1
                n += 1
            i += 1 if i < len(lines) else 0
            line += ' <HEREDOC %d lines>' % n
        out.append(line)
    return '\n'.join(out)


def shape(cmd, width=150):
    s = collapse_heredocs(cmd.replace(HOME, '~'))
    s = QUOTED_RE.sub('<S>', s)
    for rx, rep in SHAPE_RULES:
        s = rx.sub(rep, s)
    lines = [ln.strip() for ln in s.split('\n') if ln.strip()]
    s = (lines[0] if lines else '') + (' ⏎ (+%d lines)' % (len(lines) - 1) if len(lines) > 1 else '')
    return s if len(s) <= width else s[:width - 1] + '…'

# ---------------------------------------------------------------- report


def ms(values):
    if not values:
        return 'n/a'
    return 'median %.0f ms, p99 %.0f ms, max %.0f ms' % (
        statistics.median(values) * 1000, pct(values, 0.99) * 1000, max(values) * 1000)


def label(dec, reason):
    return '%s "%s"' % (dec, reason) if reason else dec


# lost_far: bash-guard's identity words, a /tmp folder the command names, a heredoc body with its delimiter line
IDENTITY_RE = re.compile(r'--author|user\.(?:name|email)|git_(?:author|committer)_(?:name|email)', re.I)
TMP_PLACE_RE = re.compile(r'(?:^|[\s;&|(`])(?:cd|pushd|mkdir(?:\s+-p)?|-C|init(?:\s+-q)?|\w+=)\s*["\']?'
                          r'(?:/private)?/tmp/')
BODY_RE = re.compile(r'(<<-?[ \t]*([\'"]?)([A-Za-z_]\w*)\2)([^\n]*)\n(?:.*?\n)??[ \t]*\3[ \t]*(?=\n|$)', re.S)


def lost_far(cmd, cwd):
    """An ask that went away outside a one-off repo: no /tmp folder (the cwd or one the command names) and identity
    text also outside heredoc bodies."""
    if (cwd or '').startswith(('/tmp/', '/private/tmp/')) or TMP_PLACE_RE.search(cmd):
        return False
    return bool(IDENTITY_RE.search(BODY_RE.sub(lambda m: m.group(1) + m.group(4), cmd)))


NAME_PART = r'(?:[\w.-]*[-_.])?(?:e2e|test|tmp|scratch|sandbox)\d*(?:[-_.][\w.-]*)?'
WORDS = r"""(?:[ \t]+(?:"(?:[^"\\]|\\.)*"|'[^']*'|[^\s;&|"'])+)*"""   # the rest of a simple command, ; in quotes too
LIST_END = r'(?=[ \t]*(?:$|\n|;|&|\|\|))'
# (name, what the class lets go, what stays of it)
LOST_CLASSES = (
    ('docker exec', re.compile(r'\bdocker\s+exec(?:\s+-\S+(?:\s+(?:[^-\s]\S*=\S*|/\S*))?)*\s+%s(?=\s)%s' % (NAME_PART, WORDS)),
     'docker exec'),
    ('docker volume rm', re.compile(r'\bdocker\s+volume\s+rm(?:\s+-\S+)*(?:\s+%s)+(?=\s*(?:$|[;&|<>]|\d>))' % NAME_PART), ''),
    ('compose config to a file', re.compile(r'(?:docker\s+compose|docker-compose)\b[^\n|;&]*\s(?:config|convert)(?=\s)[^\n|;&]*'
                                            r'(?:\s-o\s|\s--output[=\s]|(?<![02-9])>(?!&))[^\n|;&]*%s' % LIST_END), ''),
    ('heredoc', re.compile(r"""((?:^|[\s;&|(])(?:\S*/)?(?:cat|tee|python[\d.]*|node)\b[^\n]*<<-?[ \t]*\\?(['"]?)([A-Za-z_][\w.-]*)\2)"""
                           r"""([^\n]*)\n(?:.*?\n)??[ \t]*\3[ \t]*(?=\n|$)""", re.S), r'\1\4'),
)
CURL_LINE = re.compile(r'(?:curl|wget)[^\n]*\|')   # the words of curl and its pipe on one line


def without_classes(cmd):
    """The command with no text of the classes, and their names that took some."""
    names = []
    for name, rx, stays in LOST_CLASSES:
        cmd, n = rx.subn(stays, cmd)
        if n:
            names.append(name)
    return cmd, names


def classes_left(old, keys, env, timeout, workdir, jobs):
    """For each call whose ask went away: the names of its classes, when the old hook does not ask once their text is
    gone, else None: a class must explain the ask, a heredoc elsewhere in the command does not."""
    def one(key):
        rest, names = without_classes(key[1])
        if not names:
            return key, None
        return key, names if run_hook(old, bash_payload(key[0], rest, key[2], workdir), env, timeout, workdir,
                                      classify_bash)[0] == 'allow' else None
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        return dict(ex.map(one, keys))


def lost_kind(cmd, cwd, reason, classes):
    """The class that lets this ask go away, None when none does (the gate fails); classes: from classes_left."""
    if reason.startswith('коміт чи git-налаштування'):
        return None if lost_far(cmd, cwd) else 'one-off repo or heredoc (identity)'
    if classes:
        return ' + '.join(classes)
    if reason.startswith('виконання скрипта') and not CURL_LINE.search(cmd.replace('\\\n', ' ')):
        return 'curl | sh over several lines'
    return None


def report(kind, old, new, rows, uniq, results, ctx, shapes_n):
    cols = DECISIONS[kind] + EXTRA
    occ = collections.Counter()      # (old_dec, new_dec) -> calls
    by_key = {}
    for row in rows:
        by_key.setdefault(row_key(kind, row), []).append(row)
    for key, res in results.items():
        occ[(res[0], res[3])] += len(by_key[key])
    hook = HOOK_FILES[kind]
    print('== %s: %d days (%s .. %s)%s' % (hook, ctx['days'], ctx['since'], ctx['today'],
                                           '' if ctx['include_audit'] else ', audit sessions skipped'))
    same = ' (identical bytes)' if sha(old) == sha(new) else ''
    print('old  %s  sha256:%s' % (short(old), sha(old)))
    print('new  %s  sha256:%s%s' % (short(new), sha(new), same))
    dates = collections.Counter(r[-1] for r in rows)
    if 'match_total' in ctx:
        print('match  kept %d of %d, filtered out %d: not a substitute for the full replay'
              % (len(rows), ctx['match_total'], ctx['match_total'] - len(rows)))
    projects = {r[0] for r in rows}
    print('corpus  %d %s, %d unique, %d projects, %d working days, %d files read, %d audit files skipped, '
          '%d unreadable lines' % (len(rows), 'calls' if kind == 'bash' else 'prompts', len(uniq), len(projects),
                                   len(dates), ctx['files'], ctx['audit_skipped'], ctx['bad']))
    if kind == 'bash':
        print('no command  %d calls with none or an empty one, not replayed: look at them, the hook asks on no string '
              'command, but for Monitor on a WebSocket' % ctx['no_command'])
    print('matrix (occurrences; rows = old, columns = new)')
    print('  %-8s' % '' + ''.join('%9s' % c for c in cols) + '%9s' % 'total')
    for o in cols:
        total = sum(occ[(o, n)] for n in cols)
        if total or o in DECISIONS[kind]:
            print('  %-8s' % o + ''.join('%9d' % occ[(o, n)] for n in cols) + '%9d' % total)
    print('  %-8s' % 'total' + ''.join('%9d' % sum(occ[(o, n)] for o in cols) for n in cols) + '%9d' % len(rows))

    groups = collections.defaultdict(list)   # (old label, new label) -> keys
    reason_only = 0
    for key, (od, orr, _, nd, nr, _) in results.items():
        if od != nd:
            groups[(label(od, orr), label(nd, nr))].append(key)
        elif orr != nr:
            reason_only += len(by_key[key])
    changed = sum(len(by_key[k]) for ks in groups.values() for k in ks)
    print('changed decisions: %d %s (%d unique); same decision, different reason text: %d'
          % (changed, 'calls' if kind == 'bash' else 'prompts', sum(len(ks) for ks in groups.values()), reason_only))
    for (ol, nl), keys in sorted(groups.items(), key=lambda g: -sum(len(by_key[k]) for k in g[1])):
        n_occ = sum(len(by_key[k]) for k in keys)
        n_proj = len({r[0] for k in keys for r in by_key[k]})
        print('  %s -> %s: %d (%d unique, %d projects)' % (ol, nl, n_occ, len(keys), n_proj))
        if kind == 'bash':
            c = collections.Counter()
            for k in keys:
                c[shape(k[1])] += len(by_key[k])
            for s, n in c.most_common(shapes_n):
                print('      %4dx  %s' % (n, s))
            if len(c) > shapes_n:
                print('      ... %d more shapes' % (len(c) - shapes_n))
        else:
            for k in sorted(keys, key=lambda k: by_key[k][0][-1])[:shapes_n]:
                print('      %s  %d chars, %d lines' % (by_key[k][0][-1], len(k), k.count('\n') + 1))
            if len(keys) > shapes_n:
                print('      ... %d more prompts' % (len(keys) - shapes_n))

    worse = 'ask' if kind == 'bash' else 'warn'
    new_block = new_err = new_soft = far = 0
    per_day, lost = collections.Counter(), collections.Counter()
    for key, (od, orr, _, nd, _, _) in results.items():
        n = len(by_key[key])
        if nd == 'block' and od != 'block':
            new_block += n
        if nd in EXTRA and od != nd:
            new_err += n
        if nd == worse and od == 'allow':
            new_soft += n
            for r in by_key[key]:
                per_day[r[-1]] += 1
        if kind == 'bash' and od == 'ask' and nd == 'allow':
            why = lost_kind(key[1], key[2], orr, ctx['left'].get(key))
            lost[why or 'NO CLASS'] += n
            far += 0 if why else n
    median_soft = statistics.median([per_day[d] for d in ctx.get('work_days', dates)]) if dates else 0
    timeouts = sum(len(by_key[k]) for k, r in results.items() if 'timeout' in (r[0], r[3]))
    logged = ctx['logged']
    quick = 'match_total' in ctx
    ok = new_block == 0 and new_err == 0 and not logged and not far and (kind != 'bash' or median_soft <= 1) \
        and (bool(rows) or not quick)
    for line in logged[:shapes_n]:
        print('logged  %s' % line[:160])
    for why, n in lost.most_common():
        print('lost asks  %s: %d' % (why, n))
    print('gate  new blocks %d; new %ss %d (median %.1f per working day); new errors/timeouts %d; error log %d '
          'lines; asks gone with no class %d -> %s%s' % (new_block, worse, new_soft, median_soft, new_err, len(logged),
                                                          far, 'QUICK ' if quick else '', 'PASS' if ok else 'FAIL'))
    print('time  old %s; new %s; timeouts %d' % (ms([r[2] for r in results.values()]),
                                                  ms([r[5] for r in results.values()]), timeouts))
    return ok


def matching(kind, rows, rx):
    """--match: the rows whose command or prompt the regex finds."""
    return [r for r in rows if rx.search(r[2] if kind == 'bash' else r[1])]


def row_key(kind, row):
    # bash: (tool, cmd, cwd); prompts: (text,)
    return (row[1], row[2], row[3]) if kind == 'bash' else row[1]


def dump(kind, rows, results):
    """--dump: raw changed items (decision or reason) for diagnosis; only into research/replay-cache/ (gitignored)."""
    by_key = collections.defaultdict(list)
    for row in rows:
        by_key[row_key(kind, row)].append(row)
    items = []
    for key, (od, orr, _, nd, nr, _) in results.items():
        if (od, orr) == (nd, nr):
            continue
        occ = by_key[key]
        item = {'tool': key[0], 'command': key[1], 'cwd': key[2]} if kind == 'bash' else {'prompt': key}
        item.update(old=[od, orr], new=[nd, nr], calls=len(occ), projects=sorted({r[0] for r in occ}),
                    dates=sorted({r[-1] for r in occ}))
        items.append(item)
    write_dump(kind, items, 'changed items')

# ---------------------------------------------------------------- main


def die(msg):
    """Usage or setup error: exit 2 (1 is reserved for a failed gate)."""
    print('hook-replay: ' + msg, file=sys.stderr)
    sys.exit(2)


def resolve(path, kind):
    path = os.path.abspath(os.path.expanduser(path))
    if os.path.isdir(path):
        path = os.path.join(path, HOOK_FILES[kind])
    if not os.path.isfile(path) or not os.access(path, os.R_OK):
        die('hook not found or unreadable: %s' % short(path))
    return path


def kinds_for(args):
    if args.kind != 'auto':
        return ['bash', 'prompts'] if args.kind == 'all' else [args.kind]
    files = [p for p in (args.old, args.new) if not os.path.isdir(os.path.expanduser(p))]
    if not files:
        return ['bash', 'prompts']
    names = {os.path.basename(p) for p in files}
    if all(n.startswith('bash-guard') for n in names):
        return ['bash']
    if all(n.startswith('secret-guard') for n in names):
        return ['prompts']
    die('cannot tell the hook type from the file names; pass --kind bash or --kind prompts')


def leaks_path(workdir):
    """PATH with a gitleaks that finds nothing in front, and leaves a file to show it ran: bash-guard also looks in the
    brew folder, and a real gitleaks would scan the real repos, with a staged state that history does not have."""
    folder = os.path.join(workdir, 'bin')
    os.makedirs(folder)
    stub = os.path.join(folder, 'gitleaks')
    with open(stub, 'w', encoding='utf-8') as fh:
        fh.write('#!/bin/sh\n: >"$0.ran"\nexit 0\n')
    os.chmod(stub, 0o755)
    return folder + ':' + SAFE_PATH


def replay(kind, args, ctx):
    t0 = time.perf_counter()
    old, new = resolve(args.old, kind), resolve(args.new, kind)
    timeout = args.timeout or TIMEOUTS[kind]
    cutoff_epoch, cutoff = window_start(args.days)
    files, audit_skipped = list_files(cutoff_epoch, args.include_audit, top_only=kind == 'prompts')
    print('[%s] reading %d transcript files ...' % (kind, len(files)), file=sys.stderr, flush=True)
    rows, bad, no_command = extract(kind, files, cutoff, args.jobs)
    if args.match:
        ctx = dict(ctx, match_total=len(rows), work_days={r[-1] for r in rows})
        rows = matching(kind, rows, args.match)
    t1 = time.perf_counter()
    uniq = {}
    for row in rows:
        uniq.setdefault(row_key(kind, row), row)
    workdir = tempfile.mkdtemp(prefix='hook-replay-')
    errlog = os.path.join(workdir, 'bash-guard.err')   # not the live log in ~/.claude/logs
    env = {k: v for k, v in os.environ.items() if k not in ('LANG', 'LC_ALL', 'LC_CTYPE')} \
        if kind == 'prompts' else dict(os.environ, BASH_GUARD_ERRLOG=errlog)
    try:
        if kind == 'bash':
            env['PATH'] = leaks_path(workdir)
        elif args.utf8:
            env['LANG'] = 'en_US.UTF-8'

        def one(key):
            if kind == 'bash':
                data, cls = bash_payload(*key, workdir), classify_bash
            else:
                payload = {'session_id': 'hook-replay', 'hook_event_name': 'UserPromptSubmit', 'cwd': workdir,
                           'prompt': key}
                data, cls = json.dumps(payload, ensure_ascii=False).encode('utf-8'), classify_prompt
            a = run_hook(old, data, env, timeout, workdir, cls)
            b = run_hook(new, data, env, timeout, workdir, cls)
            return key, a + b
        print('[%s] replaying %d unique items through 2 hooks ...' % (kind, len(uniq)), file=sys.stderr, flush=True)
        with ThreadPoolExecutor(max_workers=args.jobs) as ex:
            results = dict(ex.map(one, list(uniq)))
        if kind == 'bash' and any('git commit ' in k[1] for k in uniq) and \
                not os.path.exists(os.path.join(workdir, 'bin', 'gitleaks.ran')):
            die('no hook ran the stand-in for gitleaks, so a real one may have scanned real repos; stop')
        gone = [k for k, r in results.items() if kind == 'bash' and r[0] == 'ask' and r[3] == 'allow']
        left = classes_left(old, gone, env, timeout, workdir, args.jobs)
        logged = log_lines(errlog)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    t2 = time.perf_counter()
    ctx = dict(ctx, files=len(files), audit_skipped=audit_skipped, bad=bad, no_command=no_command, logged=logged,
               left=left)
    ok = report(kind, old, new, rows, uniq, results, ctx, args.shapes)
    if args.dump:
        dump(kind, rows, results)
    print('wall  extract %.1f s, replay %.1f s' % (t1 - t0, t2 - t1))
    print()
    return ok


def match_regex(text):
    try:
        return re.compile(text, re.I)
    except re.error as e:
        raise argparse.ArgumentTypeError('bad regex: %s' % e)


def main():
    ap = argparse.ArgumentParser(description='Replay real transcript history through an old and a new hook.')
    ap.add_argument('--days', type=int, default=60, help='look back N days (default 60)')
    ap.add_argument('--kind', choices=('auto', 'all', 'bash', 'prompts'), default='auto',
                    help='bash = bash-guard, prompts = secret-guard (default: both for dirs, by name for files)')
    ap.add_argument('--old', default=os.path.join(HOME, '.claude', 'hooks'), help='old hook dir or file (live)')
    ap.add_argument('--new', default=os.path.join(REPO, 'hooks'), help='new hook dir or file (repo)')
    ap.add_argument('--include-audit', action='store_true', help='also replay sessions of this repo and /tmp')
    ap.add_argument('--jobs', type=int, default=min(8, os.cpu_count() or 4), help='parallel workers')
    ap.add_argument('--timeout', type=float, help='seconds per hook call (default: as in settings.json, 15 / 5)')
    ap.add_argument('--shapes', type=int, default=5, help='redacted examples per changed group (default 5)')
    ap.add_argument('--utf8', action='store_true', help='run secret-guard with LANG=en_US.UTF-8')
    ap.add_argument('--match', type=match_regex, metavar='REGEX',
                    help='quick replay: only calls and prompts it finds (case-insensitive), not a full replay')
    ap.add_argument('--dump', action='store_true',
                    help='also write the changed items (raw) to research/replay-cache/ (gitignored, 0600)')
    args = ap.parse_args()
    if args.days < 1 or args.jobs < 1 or (args.timeout is not None and args.timeout <= 0) or args.shapes < 0:
        ap.error('--days, --jobs and --timeout must be positive, --shapes not negative')
    today = datetime.date.today()
    ctx = {'days': args.days, 'today': today.isoformat(), 'include_audit': args.include_audit,
           'since': (today - datetime.timedelta(days=args.days)).isoformat()}
    t = time.perf_counter()
    ok = all([replay(kind, args, ctx) for kind in kinds_for(args)])
    print('total %.1f s, gate %s%s%s' % (time.perf_counter() - t, 'QUICK ' if args.match else '', 'PASS' if ok else 'FAIL',
                                         ' (only --match calls, not a full replay)' if args.match else ''))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
