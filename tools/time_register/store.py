"""The register folder (--home): register.json, the CSV exports, tasks.csv rows added by --add, split-until.txt (the
rows --add --stage keeps for --split-done: staging.py). Every file is written atomically with mode 0600; register.json
and tasks.csv keep their previous copies."""
import csv
import glob
import io
import json
import os
import shutil
import sys
import tempfile
from collections import Counter
from datetime import datetime

from .patterns import BACKUPS, IDLE_MIN, KYIV, MANUAL, SESSION_COLUMNS, STORE_VERSION, TASK_COLUMNS, guess_kind
from .tasks import from_start, group_tasks, parse_tasks, tasks_delimiter
from .timeline import local, merge_intervals, parse_minute, union_secs


def csv_safe(value):
    """A cell that Excel and Numbers will not run as a formula."""
    value = "" if value is None else str(value)
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def read_split_until(home):
    """End of the prompts already split into tasks (split-until.txt in --home), or None."""
    try:
        with open(os.path.join(home, "split-until.txt"), encoding="utf-8") as f:
            return parse_minute(f.read().strip(), "split-until.txt")
    except FileNotFoundError:
        return None


def load_store(home):
    path = os.path.join(home, "register.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        sys.exit(f"{path}: unreadable ({e}); restore it from a register.json.bak-* copy")
    if not isinstance(data, dict) or data.get("version") != STORE_VERSION:
        sys.exit(f"{path}: not a version {STORE_VERSION} register")
    if data.get("idle_min") != IDLE_MIN:
        sys.exit(f"{path}: built with a {data.get('idle_min')}-minute break, this script uses {IDLE_MIN}")
    sessions = data.get("sessions")
    need = ("session", "project", "start_ts", "end_ts", "intervals", "title")
    if not isinstance(sessions, dict) or not all(isinstance(r, dict) and all(k in r for k in need)
                                                 for r in sessions.values()):
        sys.exit(f"{path}: malformed sessions; restore it from a register.json.bak-* copy")
    return sessions


def merge_store(store, live):
    """Live records replace stored ones. When a transcript has lost entries the store has seen (cleanup, a cut
    file), the stored and live intervals are joined, so recorded time is never lost."""
    for sid, rec in live.items():
        old = store.get(sid)
        # a fork's time shrinks on purpose when its copied entries go to the original: trust the transcript
        if old and not rec.get("fork_entries") and (
                rec["start_ts"] > old["start_ts"] or rec["end_ts"] < old["end_ts"]
                or union_secs(rec["intervals"]) < union_secs(old["intervals"]) - 60):
            print(f"{sid[:8]}: the transcript has less than the register, stored time is kept", file=sys.stderr)
            markers = {ts: name for ts, name in old.get("markers", []) + rec.get("markers", [])}
            rec = dict(rec, start_ts=min(rec["start_ts"], old["start_ts"]), end_ts=max(rec["end_ts"], old["end_ts"]),
                       intervals=merge_intervals(old["intervals"] + rec["intervals"]),
                       markers=sorted([ts, name] for ts, name in markers.items()), title=old["title"] or rec["title"])
        store[sid] = rec
    return store


def write_private(path, writer):
    """Write a file atomically with mode 0600: temp file in the same folder, then rename."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig" if path.endswith(".csv") else "utf-8", newline="") as f:
            writer(f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def save_store(home, store):
    """register.json, with a timestamped copy of the previous one when it changes (BACKUPS latest are kept)."""
    os.makedirs(home, mode=0o700, exist_ok=True)
    store_path = os.path.join(home, "register.json")
    if os.path.exists(store_path):
        try:
            with open(store_path, encoding="utf-8") as f:
                unchanged = json.load(f).get("sessions") == json.loads(json.dumps(store))
        except (OSError, ValueError):
            unchanged = False
        if unchanged:
            return
        shutil.copy2(store_path, f"{store_path}.bak-{datetime.now(KYIV):%Y%m%d-%H%M%S-%f}")
        for old in sorted(glob.glob(glob.escape(store_path) + ".bak-*"))[:-BACKUPS]:
            os.unlink(old)
    payload = {"version": STORE_VERSION, "idle_min": IDLE_MIN,
               "updated": datetime.now(KYIV).strftime("%Y-%m-%d %H:%M"), "sessions": store}
    write_private(store_path, lambda f: json.dump(payload, f, ensure_ascii=False, indent=1))


def save_exports(home, store, segs, live):
    """register.csv (tasks), sessions.csv, and an empty tasks.csv with its header when there is none."""
    def task_rows(f):
        w = csv.writer(f)
        w.writerow(TASK_COLUMNS)
        for t in sorted(group_tasks(segs), key=lambda t: (t["project"], t["first"])):
            t["minutes"] = round(t["secs"] / 60)
            t["hours"] = f"{t['secs'] / 3600:.1f}".replace(".", ",")
            w.writerow([csv_safe(t[c]) for c in TASK_COLUMNS])
    write_private(os.path.join(home, "register.csv"), task_rows)

    count = Counter(s["session"] for s in segs)

    def session_rows(f):
        w = csv.writer(f)
        w.writerow(SESSION_COLUMNS)
        for r in sorted(store.values(), key=lambda r: r["start_ts"]):
            extra = {"start": local(r["start_ts"]), "end": local(r["end_ts"]), "tasks": count[r["session"]],
                     "minutes": round(sum(b - a for a, b in r["intervals"]) / 60),
                     "transcript": "так" if r["session"] in live else "видалено"}
            w.writerow([csv_safe(extra[c] if c in extra else r.get(c, "")) for c in SESSION_COLUMNS])
    write_private(os.path.join(home, "sessions.csv"), session_rows)

    tasks_path = os.path.join(home, "tasks.csv")
    if not os.path.exists(tasks_path):
        write_private(tasks_path, lambda f: csv.writer(f).writerow(("session",) + MANUAL))


def rows_text(rows, names, delimiter):
    """CSV lines of (session, from, task, kind, note) rows in the column order of tasks.csv."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=delimiter)
    for session, start, task, kind, note in rows:
        values = {"session": session, "from": start, "task": " ".join(task.split()), "kind": kind,
                  "note": " ".join(note.split())}
        w.writerow([values.get(n, "") for n in names])
    return buf.getvalue()


def carry_markers(sessions, existing, added):
    """Rows for the "задача:" markers of the sessions that get their first tasks.csv rows now: once a session has
    rows, its markers no longer count. `added` are the new rows as parse_tasks reads them. A new row replaces a
    marker instead when it starts in the marker's minute, or has no from (the session start) while the marker is
    the session's first one and segments() puts it at the start anyway (from_start)."""
    carried, replaced = [], 0
    for sid, recs in added.items():
        markers = sessions[sid].get("markers", [])
        if existing.get(sid) or not markers:
            continue
        minutes = {rec["from_ts"] for rec in recs if "from_ts" in rec}
        opens = any("from_ts" not in rec for rec in recs) and from_start(markers[0][0], sessions[sid]["start_ts"])
        for n, (ts, name) in enumerate(markers):
            if ts - ts % 60 in minutes or (n == 0 and opens):  # Kyiv is whole hours off UTC: the same minute
                replaced += 1
            else:
                carried.append((sid[:8], local(ts), name, guess_kind(name), ""))
    return carried, replaced


def check_split_until(home, until, allow_back):
    """Stop unless `until` may become the split boundary, and return the saved one. A minute that is not over yet is
    refused: prompts may still come in it. So is a time before the saved boundary unless allow_back: those prompts
    would be split twice."""
    if until + 60 > datetime.now(KYIV).timestamp():
        sys.exit(f"--split-done {local(until)} is not over yet: split-until.txt not changed")
    old = read_split_until(home)
    if old and until < old and not allow_back:
        sys.exit(f"--split-done {local(until)} is before the saved boundary {local(old)}: split-until.txt not "
                 "changed (add --allow-back only when the user asked to redo the split from there)")
    return old


def save_split_until(home, until, allow_back):
    """Move the split boundary (split-until.txt) to `until` (check_split_until)."""
    old = check_split_until(home, until, allow_back)
    if old and until < old:
        print(f"увага: межа поділу йде назад, з {local(old)} на {local(until)}", file=sys.stderr)
    os.makedirs(home, mode=0o700, exist_ok=True)
    write_private(os.path.join(home, "split-until.txt"), lambda f: f.write(local(until) + "\n"))
    print(f"поділено до {local(until)}", file=sys.stderr)


def checked_tasks(home, sessions, rows, refusal=None):
    """tasks.csv with rows (session, from, task, kind, note) appended and checked as a whole: (path, new text, markers
    carried, markers replaced). A session that gets its first rows keeps its "задача:" markers as rows (carry_markers).
    Bad rows stop the run, nothing written; `refusal` is the head of that message (--stage writes no tasks.csv)."""
    path = os.path.join(home, "tasks.csv")
    text = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig", newline="") as f:
            text = f.read()
    if not text.strip():
        text = ",".join(("session",) + MANUAL) + "\r\n"
    delimiter = tasks_delimiter(text)
    names = [c.strip().lower() for c in next(csv.reader(io.StringIO(text), delimiter=delimiter))]
    missing = [c for c in ("session", "from", "task", "kind", "note") if c not in names]
    if missing:
        sys.exit(f"{path}: not changed, add the column(s) {', '.join(missing)} to its header first")
    # a session split by "задача:" prompts loses them once it has rows: carry them over as rows first
    existing, _ = parse_tasks(text, sessions)
    new_rows = rows_text([tuple(r) for r in rows], names, delimiter)
    head = io.StringIO()
    csv.writer(head, delimiter=delimiter).writerow(names)  # not the file's first line: it may end without a newline
    added, _ = parse_tasks(head.getvalue() + new_rows, sessions)  # bad rows: reported below
    carried, replaced = carry_markers(sessions, existing, added)
    new = (text if text.endswith(("\n", "\r")) else text + "\r\n") + rows_text(carried, names, delimiter) + new_rows
    _, errors = parse_tasks(new, sessions)
    if errors:
        sys.exit(f"{refusal or f'{path}: not changed, the new rows are bad'}:\n  " + "\n  ".join(errors))
    return path, new, len(carried), replaced


def add_tasks(home, sessions, rows, checked=None):
    """Append rows (session, from, task, kind, note) to tasks.csv after checking the whole file with them
    (checked_tasks, or its result as `checked`); the previous file is kept as tasks.csv.bak-*."""
    path, new, carried, replaced = checked or checked_tasks(home, sessions, rows)
    if carried:
        print(f"маркери «задача:» перенесено в tasks.csv: {carried}", file=sys.stderr)
    if replaced:
        print(f"маркери «задача:» замінено новими рядками з того самого часу: {replaced}", file=sys.stderr)
    os.makedirs(home, mode=0o700, exist_ok=True)
    if os.path.exists(path):
        shutil.copy2(path, f"{path}.bak-{datetime.now(KYIV):%Y%m%d-%H%M%S-%f}")
        for old in sorted(glob.glob(glob.escape(path) + ".bak-*"))[:-BACKUPS]:
            os.unlink(old)
    write_private(path, lambda f: f.write(new))
    print(f"{path}: додано задач {len(rows)}", file=sys.stderr)

