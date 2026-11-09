"""The scan: one record per session from its main transcript and its subagent and workflow transcripts."""
import glob
import json
import os
import sys
from collections import Counter

from .patterns import EDIT_TOOLS, LABEL, MARKER, PROJECTS, guess_kind
from .projects import project_of
from .timeline import work_intervals
from .transcript import (STATS, edit_lines, fork_copy, is_number, lossy_records, parse_ts, prompt_text, read_jsonl,
                         record_id)

LOSSY_SESSIONS = set()  # ids of the sessions scan_all saw records of a LOSSY_FORMS form in
# id -> (the transcript read, its older copies) of a session with a main transcript in two project folders
DUPLICATE_SESSIONS = {}


def scan_session(main_path, known):
    """One session record. A fork copies the entries of the original session with its sessionId: an entry
    whose sessionId is another known session (live or stored) belongs to that session and is skipped here.
    An entry repeated inside the file (same uuid) counts once."""
    sid = os.path.basename(main_path)[:-len(".jsonl")]
    side = sorted(glob.glob(os.path.join(main_path[:-len(".jsonl")], "**", "*.jsonl"), recursive=True))
    stamps, span, usage, tool_ids, edited, markers, seen, prompt_ts = [], [], {}, set(), set(), [], set(), []
    cwds, models = Counter(), Counter()
    title = ai_title = agent_name = first = branch = src = ""
    prompts = lines_add = lines_del = forked = 0
    for path in [main_path] + side:
        main = path == main_path
        for d in read_jsonl(path):
            ts = parse_ts(d.get("timestamp"))
            if ts is None and d.get("timestamp") is not None:
                STATS["bad_ts"] += 1
            if main:
                if isinstance(d.get("cwd"), str):
                    cwds[d["cwd"]] += 1
                if ts:
                    span.append(ts)
                if fork_copy(d, sid, known):
                    forked += 1
                    continue
                uid = record_id(d, "uuid", "uuid")
                if uid:
                    if uid in seen:
                        STATS["repeats"] += 1
                        continue
                    seen.add(uid)
            if ts:
                stamps.append(ts)
            kind = d.get("type")
            if main:
                if kind == "custom-title" and d.get("customTitle"):
                    title = str(d["customTitle"])
                elif kind == "ai-title" and d.get("aiTitle"):
                    ai_title = str(d["aiTitle"])
                elif kind == "agent-name" and d.get("agentName"):
                    agent_name = str(d["agentName"])
                branch = d.get("gitBranch") or branch
                src = d.get("entrypoint") or src
                if kind in ("user", "attachment"):  # a prompt sent while the model worked is an attachment
                    text = prompt_text(d)
                    if text:
                        prompts += 1
                        if ts:
                            prompt_ts.append(int(ts.timestamp()))
                        # not a label: sessions titled "[картинка]" would merge into one task
                        first = first or ("" if LABEL.fullmatch(text) else " ".join(text.split()))
                        m = MARKER.match(text)
                        if m and ts:
                            markers.append([int(ts.timestamp()), m.group(1).strip()[:80]])
            msg = d.get("message")
            if kind != "assistant" or not isinstance(msg, dict):
                continue
            # a model, id or output count of another form is skipped silently (claude-metrics warns of it)
            if main and isinstance(msg.get("model"), str) and msg["model"] not in ("", "<synthetic>"):
                models[msg["model"]] += 1
            if isinstance(msg.get("usage"), dict) and isinstance(msg.get("id"), str) and msg["id"]:
                out = msg["usage"].get("output_tokens")
                if out is None or is_number(out):  # one of another form keeps the count of a streamed line before
                    usage[msg["id"]] = out or 0
            content = msg.get("content")
            for block in content if isinstance(content, list) else []:
                if not (isinstance(block, dict) and block.get("type") == "tool_use"
                        and block.get("name") in EDIT_TOOLS and block.get("id") not in tool_ids):
                    continue
                tool_ids.add(block.get("id"))
                inp = block.get("input") if isinstance(block.get("input"), dict) else {}
                target = inp.get("file_path") or inp.get("notebook_path")
                if target:
                    edited.add(target)
                a, r = edit_lines(block["name"], inp)
                lines_add += a
                lines_del += r
    STATS["fork_entries"] += forked
    span += stamps
    if not span:
        return None
    if not title:
        try:
            with open(os.path.join(main_path[:-len(".jsonl")], "custom-title.json"), encoding="utf-8") as f:
                title = str(json.load(f).get("customTitle") or "")
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError) as e:
            print(f"{sid[:8]}: custom-title.json unreadable ({e})", file=sys.stderr)
    title = title or ai_title or agent_name or first[:70]
    return {
        "session": sid,
        "project": project_of(cwds.most_common(1)[0][0] if cwds else "", os.path.basename(os.path.dirname(main_path))),
        "start_ts": int(min(span).timestamp()),
        "end_ts": int(max(span).timestamp()),
        "intervals": work_intervals(stamps),
        "markers": sorted(markers),
        "prompts": prompts,
        "prompt_ts": sorted(prompt_ts),
        "fork_entries": forked,
        "agents": sum(1 for p in side if "/subagents/" in p),
        "files": len(edited),
        "lines_add": lines_add,
        "lines_del": lines_del,
        "out_ktok": round(sum(usage.values()) / 1000),
        "model": models.most_common(1)[0][0] if models else "",
        "src": src,
        "branch": branch,
        "title": title,
        "kind_auto": guess_kind(title) or guess_kind(first[:300]),
    }


def main_transcripts():
    """One main transcript per session, for the scan and for --prompts alike. The app moves a session to another project
    folder by copying its transcript there and going on in the copy, so the newer file (mtime; on a tie the last by
    path) is the session's and the old one holds its beginning only."""
    copies = {}
    for path in sorted(glob.glob(os.path.join(PROJECTS, "*", "*.jsonl"))):
        try:
            mtime = os.path.getmtime(path)
        except OSError:  # gone or unreadable: read_jsonl reports the file if it is the session's only one
            mtime = float("-inf")
        copies.setdefault(os.path.basename(path)[:-len(".jsonl")], []).append((mtime, path))
    for sid, found in copies.items():
        found.sort(key=lambda copy: copy[0])  # stable: on a tie the order by path stays
        if len(found) > 1:
            DUPLICATE_SESSIONS[sid] = (found[-1][1], [path for _, path in found[:-1]])
    return sorted(found[-1][1] for found in copies.values())


def diverged_copies():
    """Ids of DUPLICATE_SESSIONS with an older copy that is not the start of the transcript read, or cannot be read:
    the session went on in both folders, and what only that copy holds is not counted."""
    def starts(older, path):
        try:
            with open(older, "rb") as a, open(path, "rb") as b:
                head = a.read()
                return b.read(len(head)) == head
        except OSError:
            return False
    return sorted(sid for sid, (path, older) in DUPLICATE_SESSIONS.items() if not all(starts(o, path) for o in older))


def known_sessions(stored):
    """Ids of the live main transcripts and of the register's sessions (`stored`): an entry of another of them in a
    transcript is a fork copy. A fork whose original transcript was already deleted still gives the copied entries
    to the stored original."""
    return set(stored) | {os.path.basename(p)[:-len(".jsonl")] for p in main_transcripts()}


def scan_all(stored):
    """All live sessions; `stored` are the register's session ids (known_sessions). A session with records of a
    LOSSY_FORMS form goes into LOSSY_SESSIONS, which the line that stops a write names."""
    paths = main_transcripts()
    known = known_sessions(stored)
    sessions = {}
    for path in paths:
        before = lossy_records()
        rec = scan_session(path, known)
        if lossy_records() > before:
            LOSSY_SESSIONS.add(os.path.basename(path)[:-len(".jsonl")])
        if rec:
            sessions[rec["session"]] = rec
    return sessions
