"""The light scan of the transcripts for claude-metrics --packs (ADR-007, the feedback of L4), read-only. The catalog
and the journal of claude-pack are read by packs_sources.py; the transcripts say the rest, per main transcript with
its subagents (a session; an id met in two transcript folders is two sessions):
  - a pack is on in a session when a skill listing of the session (attachment skill_listing) names `<pack>:<skill>`,
    or when the session calls one; the first listing that names a pack skill also shows whether it is left with its
    bare name, its description cut (the listing has a limit of about LIST_LIMIT characters, and what does not fit
    loses its description);
  - a call of a pack is a Skill call of `<pack>:<skill>`, the same typed as a slash command, or a run of the agent
    `<pack>:<agent>`, in the main transcript or a subagent's; a tool_use id counts once, for the oldest transcript
    that holds it (a resumed session carries the records of the one it continues);
  - an edit is an Edit, Write, MultiEdit or NotebookEdit call; one of a file that a file signal of a pack names (in the
    root of the folder the session runs in) is kept by pack, for the misses.
Only a line that can hold one of these is parsed (rows): most of a transcript is tool output, and doctor runs this
scan. A transcript not changed since the start of the window is not opened. Entries a fork copied from its original
are skipped, as in the main scan. Text of a transcript is never returned: a name is a pack of the catalog or the journal and matches PART.
What cannot be read is counted, never passed over: a file that does not open, a line that is no JSON, a listing or a
tool call of another form, a record with no time (packs_report.py turns each counter into a line).
"""
import fnmatch
import glob
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone

from time_register.transcript import fork_copy

from .packs_sources import when
from .patterns import COMMAND_NAME, EDIT_TOOLS
from .transcript import kday, text_of

LIST_LIMIT = 30000   # characters of the skill listing on the 5.x models (ADR-007, L0 check 8; about 8 000 on a 200K window)
PART = re.compile(r"[A-Za-z0-9][\w.-]{0,63}\Z")       # a skill or an agent of a pack
EDITS = EDIT_TOOLS | {"NotebookEdit"}
AGENTS = ("Agent", "Task")
# What a line must hold to be parsed, as bytes: a skill listing, a slash command, or a tool call of one of TOOLS
LISTING, COMMAND, TOOL_USE = b'"skill_listing"', b"<command-name>", b'"tool_use"'
TOOLS = tuple(b'"%s"' % t.encode() for t in sorted(EDITS | {"Skill"} | set(AGENTS)))
COMMAND_WITHIN = 4096   # bytes from the start of a line in which the record of a slash command names it
HEAD_LINES = 200        # lines of a transcript read for the folder of a session and the skill listing it started with
WORKTREE = re.compile(r"/\.claude/worktrees/[^/]+(/.*)?\Z")   # a worktree the app keeps inside a project


class Session:
    """What one main transcript and its subagents say of the packs."""

    def __init__(self, sid, folder):
        self.sid, self.folder = sid, folder
        self.key = (folder, sid)   # an id is met in two transcript folders: each file is a session of its own
        self.cwd = None        # the folder the session runs in
        self.on = {}           # pack -> {skill: its description is in the first listing that names it; None: not known}
        self.listing = None    # (time, characters, skills) of the skill listing the session started with
        self.calls = []        # (time, pack, kind, name); kind: skill, slash or agent
        self.edit_days = set()  # Kyiv days with an edit of a file
        self.signal_days = {}  # Kyiv day -> packs whose signal file was edited that day


class Scan:
    """The state of one scan: what is a pack and its signal files, the ids already counted, the counters."""

    def __init__(self, packs, signals):
        self.packs, self.signals = packs, signals   # the names of the packs; pack -> the file signals of the catalog
        self.seen = set()                           # tool_use ids and the uuids of slash commands: each counts once
        self.stats = Counter()

    def part(self, target):
        """(pack, skill or agent) of `<pack>:<name>` for a pack of the library, else None."""
        if not isinstance(target, str) or ":" not in target:
            return None
        pack, _, name = target.partition(":")
        return (pack, name) if pack in self.packs and PART.match(name) else None

    def first(self, key):
        """Whether the id is seen for the first time; a call or a command with no id is not counted."""
        if not isinstance(key, str) or key in self.seen:
            return False
        self.seen.add(key)
        return True


def wanted(line):
    """Whether a line of a transcript can say something of the packs. A slash command is looked for at the start of
    the line only: its record is short, and a long line that quotes one (a tool result, a summary) is not it."""
    return (LISTING in line or line.find(COMMAND, 0, COMMAND_WITHIN) >= 0
            or (TOOL_USE in line and any(t in line for t in TOOLS)))


def rows(path, stats, head=False):
    """The records of a transcript that can say something of the packs. The file is read as bytes and a line is
    decoded and parsed only when `wanted`: the scan of 60 days then takes seconds, not half a minute. With `head`,
    only the first HEAD_LINES lines, every one of them parsed."""
    try:
        with open(path, "rb") as fh:
            stats["heads" if head else "files"] += 1
            for n, line in enumerate(fh):
                if head and n >= HEAD_LINES:
                    return
                if not (head or wanted(line)):
                    continue
                try:
                    d = json.loads(line.decode("utf-8", "replace"))
                except ValueError:   # not JSON, or an integer over Python's digit limit
                    stats["bad_lines"] += 1
                    continue
                if isinstance(d, dict):
                    yield d
                else:
                    stats["bad_lines"] += 1
    except OSError:   # does not open, or stops reading half way: what it held is not counted, and the report says so
        stats["unreadable"] += 1


def root_match(rel, pattern):
    """Whether the path under the session folder is the file a signal names: part by part, so `*.tf` is a file of the
    root and not one of a subfolder (the signals are read in the root of a project only)."""
    have, want = rel.split("/"), pattern.split("/")
    return len(have) == len(want) and all(fnmatch.fnmatchcase(h, w) for h, w in zip(have, want))


def note_listing(session, att, ts, scan):
    content, names = att.get("content"), att.get("names")
    lines = set(content.split("\n")) if isinstance(content, str) else set()
    if names is None:   # a listing of Claude Code before the field `names` (seen up to 2.1.142): the lines name the skills
        names = [ln[2:].split(": ", 1)[0] for ln in lines if ln.startswith("- ")]
    if not isinstance(content, str) or not isinstance(names, list):
        scan.stats["listing_form_unknown"] += 1
        return
    scan.stats["listings"] += 1
    if att.get("isInitial") is True and session.listing is None:
        if ts:
            session.listing = (ts, len(content), len(names))
        else:   # the listing a session started with cannot be put on a day
            scan.stats["no_timestamp"] += 1
    for name in names:
        found = scan.part(name)
        if not found:
            continue
        if "- " + name in lines:
            described = False
        elif any(ln.startswith("- %s: " % name) for ln in lines):
            described = True
        else:   # the line of a listed skill has another form: on, and whether its description is there is not known
            described = None
            scan.stats["listing_form_unknown"] += 1
        skills = session.on.setdefault(found[0], {})
        if skills.get(found[1]) is None:   # the first listing that names the skill says it: a later one repeats names
            skills[found[1]] = described


def note_edit(session, inp, ts, scan):
    day = kday(ts)
    session.edit_days.add(day)
    path, root = inp.get("file_path") or inp.get("notebook_path"), (session.cwd or "").rstrip("/")
    if not isinstance(path, str) or not root or not path.startswith(root + "/"):
        return
    rel = path[len(root) + 1:]
    for pack, patterns in scan.signals.items():
        if any(root_match(rel, p) for p in patterns):
            session.signal_days.setdefault(day, set()).add(pack)


def note_tool(session, block, ts, scan):
    name = block.get("name")
    inp = block.get("input") if isinstance(block.get("input"), dict) else {}
    if name == "Skill":
        target = inp.get("skill") or inp.get("name")
        found, kind = scan.part(target), "skill"
        if not isinstance(target, str):   # a Skill call that names no skill: the key of its input has changed
            scan.stats["call_form_unknown"] += 1
    elif name in AGENTS:
        found, kind = scan.part(inp.get("subagent_type")), "agent"
    elif name in EDITS:
        found, kind = None, "edit"
    else:
        return
    if not found and kind != "edit":
        return
    if not isinstance(block.get("id"), str):   # no id to count the call once by
        scan.stats["call_form_unknown"] += 1
    elif not ts:   # a call that cannot be put on a day; its id stays free for a copy of the record that has the time
        scan.stats["no_timestamp"] += 1
    elif not scan.first(block["id"]):
        return
    elif kind == "edit":
        note_edit(session, inp, ts, scan)
    else:
        session.calls.append((ts, found[0], kind, found[1]))
        session.on.setdefault(found[0], {})   # a call is proof enough that the pack is on


def note_record(session, d, main, scan):
    kind, ts = d.get("type"), when(d.get("timestamp"))
    message = d.get("message") if isinstance(d.get("message"), dict) else {}
    content = message.get("content")
    if kind == "attachment" and main:
        att = d.get("attachment")
        if isinstance(att, dict) and att.get("type") == "skill_listing":
            note_listing(session, att, ts, scan)
    elif kind == "assistant":
        if not isinstance(content, list):   # the tool calls of a turn are no list: they cannot be read
            scan.stats["call_form_unknown"] += 1
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                note_tool(session, block, ts, scan)
    elif kind == "user" and main and not d.get("isMeta"):
        m = COMMAND_NAME.search(text_of(content)[:500])
        found = scan.part(m.group(1)) if m else None
        if found and not ts:
            scan.stats["no_timestamp"] += 1
        elif found and not isinstance(d.get("uuid"), str):   # no id to count the command once by
            scan.stats["call_form_unknown"] += 1
        elif found and scan.first(d["uuid"]):
            session.calls.append((ts, found[0], "slash", found[1]))
            session.on.setdefault(found[0], {})


def changed_since(path, floor, stats):
    """The time a transcript was last written to when that is `floor` or later, else None; one that does not stat is
    counted as not read."""
    try:
        changed = os.path.getmtime(path)
    except OSError:
        stats["unreadable"] += 1
        return None
    return changed if changed >= floor else None


def read_session(path, known, scan, floor):
    """The Session of a main transcript read in full, with its subagent and workflow transcripts changed since `floor`."""
    sid = os.path.basename(path)[:-len(".jsonl")]
    session = Session(sid, os.path.basename(os.path.dirname(path)))
    for d in rows(path, scan.stats):
        if fork_copy(d, sid, known):
            continue
        if session.cwd is None and isinstance(d.get("cwd"), str):
            session.cwd = d["cwd"]
        note_record(session, d, True, scan)
    for side in sorted(glob.glob(os.path.join(glob.escape(path[:-len(".jsonl")]), "**", "*.jsonl"), recursive=True)):
        if side.endswith("journal.jsonl") or changed_since(side, floor, scan.stats) is None:
            continue
        for d in rows(side, scan.stats):
            note_record(session, d, False, scan)
    return session


def head_session(path, known, scan):
    """The Session the first HEAD_LINES lines of a main transcript give: the folder it runs in and the skill listing it
    started with. Its calls and edits are not read."""
    sid = os.path.basename(path)[:-len(".jsonl")]
    session = Session(sid, os.path.basename(os.path.dirname(path)))
    for d in rows(path, scan.stats, head=True):
        if fork_copy(d, sid, known):
            continue
        if session.cwd is None and isinstance(d.get("cwd"), str):
            session.cwd = d["cwd"]
        att = d.get("attachment")
        if d.get("type") == "attachment" and isinstance(att, dict) and att.get("type") == "skill_listing":
            note_listing(session, att, when(d.get("timestamp")), scan)
        if session.cwd is not None and session.listing is not None:
            break
    return session


def head_cwd(path):
    """The folder a session runs in, by the first HEAD_LINES lines of its transcript; None when they do not name it.
    What this look fails to read is not counted here: the read that follows (in full, or of the head) counts it once."""
    for d in rows(path, Counter(), head=True):
        if isinstance(d.get("cwd"), str):
            return d["cwd"]
    return None


def head_only(paths, known, scan, floor, full):
    """Doctor's short read of one transcript folder, its main transcripts given newest first. A folder holds the
    sessions of one session folder. None when their calls and edits are needed: `full` says so of the folder the newest
    transcript names, or no head names one. Else the sessions to keep: the newest one whose head has a skill listing
    since `floor`, if any."""
    cwd = next((c for c in map(head_cwd, paths) if c is not None), None)
    if cwd is None or full(cwd):
        return None
    scan.stats["folders_head_only"] += 1
    for path in paths:
        session = head_session(path, known, scan)
        if session.listing and session.listing[0].timestamp() >= floor:
            return [session]
    return []


def scan_packs(home, start, packs, signals, full=None):
    """({(transcript folder, session id): Session} of the main transcripts changed since `start`, a time; the counters
    of the scan with `oldest`, the Kyiv day of the oldest main transcript: older days were cleaned up and prove nothing).
    full: None reads every such transcript in full (the report); else a function of a session folder that says whether
    the calls and edits of its sessions are needed (doctor: a project with a pack on), see head_only.
    The transcripts are read oldest first: a call or an edit that a resumed session carries over from the session it
    continues has the same id there and counts once, for the session it was made in."""
    scan = Scan(packs, signals)
    mains = sorted(glob.glob(os.path.join(glob.escape(home), "projects", "*", "*.jsonl")))
    known = {os.path.basename(p)[:-len(".jsonl")] for p in mains}
    folders, oldest, floor = {}, None, start.timestamp()
    for path in mains:
        changed = changed_since(path, 0, scan.stats)
        if changed is None:
            continue
        oldest = changed if oldest is None else min(oldest, changed)
        if changed >= floor:
            folders.setdefault(os.path.dirname(path), []).append((changed, path))
    sessions, in_full = {}, []
    for _, found in sorted(folders.items()):
        short = head_only([path for _, path in sorted(found, reverse=True)], known, scan, floor, full) if full else None
        if short is None:
            in_full += found
        else:
            sessions.update((s.key, s) for s in short)
    for _, path in sorted(in_full):
        session = read_session(path, known, scan, floor)
        sessions[session.key] = session
    scan.stats["sessions"] = len(sessions)
    scan.stats["sessions_with_listing"] = sum(1 for s in sessions.values() if s.listing)
    stats = dict(scan.stats, oldest=kday(datetime.fromtimestamp(oldest, timezone.utc)) if oldest is not None else None)
    return sessions, stats


def project_of(cwd, roots, projects_dir):
    """The project of a session folder: the longest known project folder (`roots`: of the journal, of doctor) it is in;
    else the folder of `projects_dir` it is in; else the folder itself, a worktree the app keeps inside it cut off."""
    if not cwd:
        return None
    held = [r for r in roots if cwd == r or cwd.startswith(r.rstrip("/") + "/")]
    if held:
        return max(held, key=len)
    base = (projects_dir or "").rstrip("/")
    if base and cwd.startswith(base + "/"):
        return os.path.join(base, cwd[len(base) + 1:].split("/")[0])
    return WORKTREE.sub("", cwd)
