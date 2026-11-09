"""Tasks: tasks.csv rows, the split of a session into task segments, the cut to a date window, tasks per project."""
import csv
import io
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime

from .patterns import KIND_NAMES, KYIV, LEAD_SECS, MANUAL, guess_kind
from .projects import project_level
from .timeline import clip, local


def hours(text):
    """Hours from "1,5" or "1.5"; ValueError on anything else."""
    value = float(text.replace(",", "."))
    if not 0 <= value < 1000:
        raise ValueError(text)
    return value


def tasks_delimiter(text):
    header = text.split("\n", 1)[0]
    return ";" if header.count(";") > header.count(",") else ","


def load_tasks(home, sessions):
    """tasks.csv rows per session id, and the list of bad rows. The caller stops on bad rows: a silently
    skipped row would make the register look complete while it is not."""
    path = os.path.join(home, "tasks.csv")
    if not os.path.exists(path):
        return defaultdict(list), []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return parse_tasks(f.read(), sessions)


def parse_tasks(text, sessions):
    out = defaultdict(list)
    reader = csv.reader(io.StringIO(text), delimiter=tasks_delimiter(text))
    names = [c.strip().lower() for c in next(reader, [])]
    if "session" not in names or "task" not in names:
        return out, ["the header has no session or task column"]
    errors, seen = [], set()
    for n, cells in enumerate(reader, start=2):
        row = {k: (cells[i].strip() if i < len(cells) else "") for i, k in enumerate(names)}
        if not any(row.values()):
            continue
        prefix = row["session"]
        hits = [s for s in sessions if s.startswith(prefix)] if len(prefix) >= 8 else []
        if len(hits) != 1:
            errors.append(f"line {n}: session {prefix!r} matches {len(hits)} sessions (an id prefix of 8+ chars)")
            continue
        rec = {k: row.get(k, "") for k in MANUAL}
        rec["kind"] = rec["kind"].lower()
        if rec["kind"] and rec["kind"] not in KIND_NAMES:
            errors.append(f"line {n}: kind {rec['kind']!r} is not one of {', '.join(KIND_NAMES)}")
        try:
            rec["extra"] = hours(rec["extra_h"]) if rec["extra_h"] else 0.0
        except ValueError:
            errors.append(f"line {n}: extra_h {rec['extra_h']!r} is not hours like 1,5")
        if rec["from"]:
            try:
                rec["from_ts"] = int(datetime.strptime(rec["from"], "%Y-%m-%d %H:%M").replace(tzinfo=KYIV).timestamp())
            except ValueError:
                errors.append(f"line {n}: from {rec['from']!r} is not YYYY-MM-DD HH:MM")
                continue
        key = (hits[0], rec.get("from_ts", sessions[hits[0]]["start_ts"]))
        if key in seen:
            errors.append(f"line {n}: a second task of {prefix} starts at the same time")
        seen.add(key)
        out[hits[0]].append(rec)
    return out, errors


def from_start(ts, start_ts):
    """A first task that starts within LEAD_SECS of its session start takes the session from the start."""
    return ts - start_ts <= LEAD_SECS


def segments(rec, rows):
    """Split a session into task segments: tasks.csv rows, else "задача:" prompts, start a task at their time."""
    start = rec["start_ts"]
    if rows:
        cuts = [(r.get("from_ts", start), r) for r in rows]
    else:
        cuts = [(ts, {"task": name, "kind": guess_kind(name)}) for ts, name in rec.get("markers", [])]
    cuts.sort(key=lambda c: c[0])
    if cuts and from_start(cuts[0][0], start):
        # the first prompt comes a little after the session's first entries (hooks, title): they are its task
        cuts[0] = (min(start, cuts[0][0]), cuts[0][1])
    elif not cuts or cuts[0][0] > start:
        cuts.insert(0, (start, {}))
    out = []
    for i, (lo, row) in enumerate(cuts):
        hi = cuts[i + 1][0] if i + 1 < len(cuts) else float("inf")
        ivs = clip(rec["intervals"], lo, hi)
        extra = round(row.get("extra", 0.0) * 3600)
        out.append({
            "session": rec["session"],
            "project": rec["project"],
            "task": row.get("task") or rec["title"] or rec["session"][:8],
            "kind": row.get("kind") or (rec.get("kind_auto") if not row else guess_kind(row.get("task", ""))) or "?",
            "size": row.get("size", ""),
            "note": row.get("note", ""),
            "intervals": ivs,
            "extra_secs": extra,
            "secs": sum(b - a for a, b in ivs) + extra,
            "start_ts": ivs[0][0] if ivs else lo,
            "start": local(ivs[0][0] if ivs else lo),
            "end": local(ivs[-1][1] if ivs else lo),
        })
    empty = sum(1 for s, (_, row) in zip(out, cuts) if row and not s["secs"])
    if empty:
        print(f"{rec['session'][:8]}: {empty} task(s) with no time (fork copy, or tasks.csv rows too close)", file=sys.stderr)
    return out


def in_window(segs, lo, hi):
    """Segments cut to [lo, hi): a task that runs across the edge keeps only its time inside."""
    out = []
    for s in segs:
        ivs = clip(s["intervals"], lo, hi)
        extra = s["extra_secs"] if lo <= s["start_ts"] < hi else 0
        if ivs or extra:
            out.append(dict(s, intervals=ivs, secs=sum(b - a for a, b in ivs) + extra,
                            start=local(ivs[0][0]) if ivs else s["start"], end=local(ivs[-1][1]) if ivs else s["end"]))
    return out


def group_tasks(segs):
    tasks = defaultdict(list)
    for s in segs:
        tasks[(s["project"], s["task"])].append(s)
    out = []
    for (project, task), ss in tasks.items():
        out.append({
            "project": project, "level": project_level(project), "task": task,
            "kind": Counter(s["kind"] for s in ss).most_common(1)[0][0],
            "size": next((s["size"] for s in ss if s["size"]), ""),
            "note": "; ".join(dict.fromkeys(s["note"] for s in ss if s["note"])),
            "secs": sum(s["secs"] for s in ss),
            "sessions": len({s["session"] for s in ss}),
            "first": min(s["start"] for s in ss)[:10], "last": max(s["end"] for s in ss)[:10],
        })
    return out
