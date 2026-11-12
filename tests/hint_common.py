"""hint_common: what tests/hint-replay.py and tests/hint-delivered.py share: session-hint's exact texts and its rules
written again in Python (expect()), the stdin JSON the hook gets, the readers of Bash calls in a transcript, and for
hint-delivered.py the reader of one transcript (scan_file()): push calls and results, hint texts, compactions, runs
and errors of session-hint."""
import collections
import os
import re
import time

from replay_common import blocks, records, session_of

NEXT = ("don't start it here: end this turn with a new-session card and a short brief (app: start_session, or "
        "hand_off_to_session for work in progress; CLI: update the STATUS checkpoint and suggest a new session). "
        "Same task: continue.")
TEXT = {'PostToolUse': 'session-hint: push done. If the next step is a different task or feature (not CI, a deploy or '
                       'a fix of this push), ' + NEXT,
        'PullRequest': 'session-hint: PR opened. Start one background call, not a poll: `gh pr checks <number> --watch` '
                       'with run_in_background (the app wakes you only on failures, not on green). When it ends green, '
                       'say in one line what gets merged into which branch and run `gh pr merge` right away: its '
                       "permission prompt is the user's merge decision, so no question and no reply buttons before it "
                       '(in a session that shows no permission prompts, ask before the merge instead).',
        'SessionStart': 'session-hint: the context was just compacted. Відповідай українською, також wrap_up, плани, '
                        'квізи. If the next step is a different task or feature, ' + NEXT}
EVENT = {'PostToolUse': 'PostToolUse', 'PullRequest': 'PostToolUse', 'SessionStart': 'SessionStart'}   # of each text
# the hook's rules (session-hint.sh), as Python regexes with ASCII \s like bash [[:space:]] in the C locale (the hook
# runs with LC_ALL=C)
W = r'''("[^"]*"|'[^']*'|[^\s;&|"'])+'''
G = r'git([ \t]+-[cC][ \t]+%s)*[ \t]+push' % W
E = r'([\s;&|)]|\Z)'
PUSH_RE = re.compile(G + E, re.ASCII)
DRY_RE = re.compile(G + r'([ \t]+%s)*[ \t]+(--dry-run|-[fuvqd46]*n[fuvqd46]*)' % W + E, re.ASCII)
FAILED_RE = re.compile(r'failed to push some refs|\[(remote )?rejected\]|(^|\n)fatal: ')
R = r'gh([ \t]+(-R|--repo)[ \t]+%s)*[ \t]+pr ' % W
PR_RE, MERGE_RE = re.compile(R + 'create' + E, re.ASCII), re.compile(R + 'merge' + E, re.ASCII)
OPENED_RE = re.compile(r'/pull/[0-9]+')
HOOK = '/session-hint.sh'
UNATTRIBUTED = ('hook_cancelled', 'hook_error_during_execution', 'hook_non_blocking_error')
IDLE_S = 60   # a push hint is written with its call's result: in a file idle this long none is still to come


def record_base(d, proj, path):
    """What every item of one transcript record keeps: where and when, its session and subagent."""
    return {'proj': proj, 'file': path, 'ts': d['timestamp'], 'cwd': d.get('cwd') or '', 'uuid': d.get('uuid'),
            'sid': d.get('sessionId') if isinstance(d.get('sessionId'), str) else path,
            'agent': d.get('agentId') if isinstance(d.get('agentId'), str) and d.get('isSidechain') else ''}


def hint_candidate(cmd):
    """A Bash call the hook may answer: the two words its first test looks for in the input."""
    return 'push' in cmd or 'pr create' in cmd


def bash_call(b, base):
    """The Bash call of a tool_use block with its id and command, or None."""
    cmd = b['input'].get('command') if isinstance(b.get('input'), dict) else None
    if b.get('name') != 'Bash' or not isinstance(cmd, str) or not isinstance(b.get('id'), str):
        return None
    return dict(base, id=b['id'], cmd=cmd)


def block_text(c):
    """The text of a tool_result block's content: a string or a list of text blocks."""
    if isinstance(c, list):
        return ''.join(x['text'] for x in c if isinstance(x, dict) and isinstance(x.get('text'), str))
    return c if isinstance(c, str) else ''


def bash_result(d, b):
    """(result time, is_error, stdout, stderr, odd) of a tool_result block; odd: a successful call with no
    toolUseResult object (subagent transcripts keep none), whose stdout is then the text of the block."""
    is_err, tur = bool(b.get('is_error')), d.get('toolUseResult')
    if not isinstance(tur, dict):
        return d['timestamp'], is_err, block_text(b.get('content')), '', not is_err
    out = [tur.get(k) if isinstance(tur.get(k), str) else '' for k in ('stdout', 'stderr')]
    return d['timestamp'], is_err, out[0], out[1], False


def push_payload(c, result):
    is_err, stdout, stderr = result[1:4]
    p = {'session_id': c['sid'], 'transcript_path': c['file'], 'cwd': c['cwd'], 'permission_mode': 'default',
         'hook_event_name': 'PostToolUseFailure' if is_err else 'PostToolUse', 'tool_name': 'Bash',
         'tool_input': {'command': c['cmd']}, 'tool_use_id': c['id'], 'duration_ms': 1000}
    if is_err:
        p['error'] = 'Exit code 1'
    else:
        p['tool_response'] = {'stdout': stdout, 'stderr': stderr, 'interrupted': False, 'isImage': False}
    if c['agent']:
        p.update(agent_id=c['agent'], agent_type='general-purpose')
    return p


def compact_payload(c):
    """The SessionStart input of a compaction. A subagent's has no agent_id either: Claude Code sends the same fields
    as for the main session (docs/compat.md, 2026-11-11), so the hook cannot tell the two apart."""
    return {'session_id': c['sid'], 'transcript_path': c['file'], 'cwd': c['cwd'], 'hook_event_name': 'SessionStart',
            'source': 'compact', 'model': 'claude-opus-5-5'}


def expect(p):
    """The key in TEXT of the hint the hook must print for this payload, or None for silence (session-hint.sh's
    rules). A subagent is known only by agent_id: its compaction comes without one and gets the hint."""
    if p.get('agent_id'):
        return None
    if p['hook_event_name'] == 'SessionStart':
        return 'SessionStart' if p.get('source') == 'compact' else None
    if p['hook_event_name'] != 'PostToolUse':
        return None
    tr = p.get('tool_response') or {}
    out = tr.get('stdout', '') + '\n' + tr.get('stderr', '')
    if FAILED_RE.search(out):
        return None
    cmd = p['tool_input']['command'].rstrip('\n').replace('\\\n', ' ')   # $(...) in the hook drops trailing newlines
    if OPENED_RE.search(out) and 'already exists' not in out and PR_RE.search(cmd) and not MERGE_RE.search(cmd):
        return 'PullRequest'
    return 'PostToolUse' if PUSH_RE.search(cmd) and not DRY_RE.search(cmd) else None

# ---------------------------------------------------------------- hint-delivered.py: the reader of one transcript


def is_session_start(name):
    """SessionStart as a hookName: the context attachment has it bare, the hook runner adds the matcher."""
    return isinstance(name, str) and (name == 'SessionStart' or name.startswith('SessionStart:'))


def on_hook_event(name):
    return name == 'PostToolUse:Bash' or is_session_start(name)


def hint_texts(a):
    """The session-hint lines in the content of a hook_additional_context attachment."""
    c = a.get('content')
    return [s for s in (c if isinstance(c, list) else [c]) if isinstance(s, str) and s.startswith('session-hint:')]


def is_ours(a):
    """A hook attachment that names session-hint.sh as its command."""
    return isinstance(a.get('command'), str) and a['command'].rstrip().endswith(HOOK)


def open_compaction(f):
    """The last compaction while no assistant message or other compaction has come after it, else None."""
    return f['compactions'][-1] if f['compactions'] and not f['compactions'][-1]['closed'] else None


def add_attachment(a, ts, f):
    """A hook attachment: a session-hint text (of a tool call, or of the open compaction), a run or an error of
    session-hint.sh, an error or a cancel on one of its events with no command."""
    kind, name = a.get('type'), a.get('hookName')
    is_hook = isinstance(kind, str) and kind.startswith('hook_')
    f['seen']['hooks'] += is_hook
    f['seen']['events'] += is_hook and on_hook_event(name)
    if kind == 'hook_additional_context':
        lines, c = hint_texts(a), open_compaction(f)
        if lines and is_session_start(name) and c:
            c['texts'] += lines
        elif lines and is_session_start(name):
            f['stray'] += [ts] * len(lines)   # a compaction hint with no compaction before it
        elif lines:
            tid = a.get('toolUseID')
            f['hints'][tid if isinstance(tid, str) else ''].append((name, lines, ts))
    elif is_hook and is_ours(a):
        if kind == 'hook_success' and a.get('exitCode') == 0:
            f['runs'].append((ts, a.get('durationMs')))
        else:
            f['errors'].append((ts, kind))   # also hook_cancelled of the command itself (timedOut)
    elif kind in UNATTRIBUTED and on_hook_event(name) and 'command' not in a:
        f['unattributed'].append(ts)


def add_record(d, f, proj, path):
    """One main session record: a compaction, a hook attachment, a push call or its result, and its place."""
    kind, c = d.get('type'), open_compaction(f)
    f['seq'] += 1   # the place in the file, not the time: in 143 of 164 files timestamps go back between records
    if kind == 'assistant':
        f['last_assistant'] = f['seq']
        msg = d.get('message')
        mid = msg.get('id') if isinstance(msg, dict) else None
        f['answers'] += mid is None or mid != f['answer_id']   # every block of one answer is a record of its own
        f['answer_id'] = mid
    if c and (kind == 'assistant' or d.get('subtype') == 'compact_boundary'):
        c['closed'] = True
    if kind == 'system' and d.get('subtype') == 'compact_boundary':
        f['compactions'].append({'ts': d['timestamp'], 'texts': [], 'closed': False})
        f['seen']['compactions'] += 1
    elif kind == 'attachment' and isinstance(d.get('attachment'), dict):
        add_attachment(d['attachment'], d['timestamp'], f)
    f['seen']['summaries'] += d.get('isCompactSummary') is True   # 1:1 with compact_boundary in 60 days of transcripts
    for b in blocks(d, 'tool_use'):
        call = bash_call(b, record_base(d, proj, path))
        f['seen']['bash'] += call is not None
        if call and hint_candidate(call['cmd']):
            f['calls'][call['id']] = call
            f['call_answer'][call['id']] = f['answers']
            f['seen']['push'] += 1
    for b in blocks(d, 'tool_result'):
        tid = b.get('tool_use_id')
        f['seen']['odd_results'] += not isinstance(tid, str)
        if isinstance(tid, str) and tid in f['calls']:
            f['results'][tid] = bash_result(d, b)
            f['result_seq'][tid] = f['seq']
            f['seen']['results'] += 1


def add_subagent_record(d, f):
    """A subagent record: its compaction, or session-hint texts. The texts of a SessionStart hint after the subagent's
    own compaction go to that compaction: Claude Code runs SessionStart there with no agent_id (compact_payload()), so
    the hook cannot stay silent. One exact text per compaction; every other text is extra (judge() in
    hint-delivered.py), as is a push hint: PostToolUse does carry agent_id. A subagent file is one subagent, whatever
    its records say; an older main file holds the records of several, told apart by agentId."""
    agent = d.get('agentId') if isinstance(d.get('agentId'), str) and not f['sub'] else ''
    if d.get('type') == 'system' and d.get('subtype') == 'compact_boundary':
        f['sub_compactions'][agent].append({'ts': d['timestamp'], 'texts': []})
    a = d.get('attachment') if d.get('type') == 'attachment' else None
    if isinstance(a, dict) and a.get('type') == 'hook_additional_context':
        lines, own = hint_texts(a), f['sub_compactions'][agent]
        if own and is_session_start(a.get('hookName')):
            own[-1]['texts'] += lines
        else:
            f['sub_texts'] += [d['timestamp']] * len(lines)


def scan_file(job):
    """The facts of one transcript. A main session: its first record, push calls and results, hint texts by tool call,
    compactions with the texts after them, session-hint runs and errors, unattributed errors and cancels, what was
    seen, whether the file is idle. A subagent transcript: its first record, its compactions with the SessionStart
    texts after them and its other session-hint texts (only lines with a text or a compaction are parsed)."""
    proj, path = job
    sid, sub = session_of(proj, path)
    f = {'proj': proj, 'sid': sid, 'sub': sub, 'first': None, 'seq': 0, 'last_assistant': 0, 'idle': False,
         'answers': 0, 'answer_id': None, 'call_answer': {},
         'calls': {}, 'results': {}, 'result_seq': {}, 'hints': collections.defaultdict(list), 'compactions': [],
         'stray': [], 'errors': [], 'runs': [], 'unattributed': [], 'sub_texts': [],
         'sub_compactions': collections.defaultdict(list), 'seen': collections.Counter(), 'bad': 0, 'bad_files': 0}
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            f['idle'] = time.time() - os.fstat(fh.fileno()).st_mtime > IDLE_S
            lines = (line for i, line in enumerate(fh)
                     if i == 0 or 'session-hint:' in line or 'compact_boundary' in line) if sub else fh
            for d in records(lines, f, dedup=True):
                f['first'] = f['first'] or d['timestamp']
                if sub or d.get('isSidechain'):
                    add_subagent_record(d, f)   # also subagent records in the main file (older Claude Code)
                else:
                    add_record(d, f, proj, path)
    except OSError:
        f['bad_files'] += 1
    return f
