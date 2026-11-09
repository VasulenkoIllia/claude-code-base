"""The split in chunks: --add ... --stage keeps the rows in this Claude Code session's entry of add-staged.json, and
--split-done --rows writes them all to tasks.csv with the boundary, or nothing. Every write of tasks.csv and
split-until.txt goes under the register's lock (add-staged.lock). Chunks, because Claude Code asks before it runs a Bash
command it cannot parse, one over 10000 characters among them, and a scheduled run has nobody to answer."""
import contextlib
import csv
import fcntl
import io
import json
import os
import sys
from collections import Counter
from datetime import datetime

from .patterns import KYIV
from .store import add_tasks, check_split_until, checked_tasks, read_split_until, save_split_until, write_private
from .tasks import tasks_delimiter
from .timeline import local, parse_minute

STAGED, STAGED_LOCK = "add-staged.json", "add-staged.lock"
# the Claude Code session a command runs in (Claude Code puts it into the environment of its Bash calls): staged rows
# are kept per session, so a split that never got to --split-done stays apart from this one
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"
STAGED_DAYS = 7  # the entry of a session that has not staged for this long is of a split that stopped: dropped
STAGE_REFUSAL = ("nothing staged, the new rows are bad (fix them and send the chunk again; a --split-done without "
                 "them would mark their prompts split)")


def stage_session():
    """The Claude Code session this command runs in, "" outside Claude Code. Inside it without the variable (renamed in a
    new version) the rows of different runs could not be told apart: the run stops."""
    session = os.environ.get(SESSION_ENV, "")
    if not session and os.environ.get("CLAUDECODE"):
        sys.exit(f"{SESSION_ENV} is not set inside Claude Code: staged rows cannot be tied to this session; "
                 "nothing written")
    return session


@contextlib.contextmanager
def staged_lock(home):
    """The register's lock while add-staged.json, tasks.csv and split-until.txt are read and written (--add and --write
    take it too): chunks one session sends at once (its subagents share its id) and two sessions splitting at once must
    not lose each other's rows. Not reentrant: a second open of the lock file in the same process would wait forever."""
    os.makedirs(home, mode=0o700, exist_ok=True)
    fd = os.open(os.path.join(home, STAGED_LOCK), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)  # closing the descriptor releases the lock


def entry_ok(entry):
    """An entry of add-staged.json as stage_tasks and commit_split write it."""
    def epoch(value):
        return isinstance(value, int) and not isinstance(value, bool)
    return (isinstance(entry, dict) and "boundary" in entry and (entry["boundary"] is None or epoch(entry["boundary"]))
            and epoch(entry.get("staged")) and ("commit" not in entry or epoch(entry["commit"]))
            and isinstance(entry.get("rows"), list)
            and all(isinstance(r, list) and len(r) == 5 and all(isinstance(c, str) for c in r) for r in entry["rows"]))


def load_staged(home):
    """add-staged.json as {session: {"boundary", "staged", "rows"[, "commit"]}}, {} when there is none. A file of another
    form stops the run: staged rows must not vanish unseen."""
    path = os.path.join(home, STAGED)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        sys.exit(f"{path}: unreadable ({e}): nothing written (the owner removes it)")
    if not (isinstance(data, dict) and all(entry_ok(entry) for entry in data.values())):
        sys.exit(f"{path}: not a file of --add --stage: nothing written (the owner removes it)")
    return data


def save_staged(home, staged):
    """add-staged.json without the entries of sessions that last staged over STAGED_DAYS ago; none left: no file."""
    oldest = datetime.now(KYIV).timestamp() - STAGED_DAYS * 86400
    staged = {session: entry for session, entry in staged.items() if entry["staged"] >= oldest}
    path = os.path.join(home, STAGED)
    if staged:
        write_private(path, lambda f: json.dump(staged, f, ensure_ascii=False, indent=1))
    elif os.path.exists(path):
        os.unlink(path)


def own_rows(entry, boundary, what):
    """The rows of this session's entry, [] without one. An entry staged from another boundary means another session
    split meanwhile: the run stops, `what` names what was not written."""
    if not entry:
        return []
    if entry["boundary"] != boundary:
        was, now = (local(ts) if ts else "none" for ts in (entry["boundary"], boundary))
        sys.exit(f"this session staged its rows from the boundary {was}, it is {now} now: another session split "
                 f"meanwhile; {what}")
    return list(entry["rows"])


def clean_row(row):
    """A row as tasks.csv reads it back: cells without the spaces around, task and note on one line, kind in lower case."""
    session, start, task, kind, note = (cell.strip() for cell in row)
    return [session, start, " ".join(task.split()), kind.lower(), " ".join(note.split())]


def present_rows(home):
    """The rows of tasks.csv as clean_row gives them: a staged row found there was written by a --split-done cut short."""
    path = os.path.join(home, "tasks.csv")
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8-sig", newline="") as f:
        text = f.read()
    reader = csv.reader(io.StringIO(text), delimiter=tasks_delimiter(text))
    names = [c.strip().lower() for c in next(reader, [])]
    return {tuple(clean_row([dict(zip(names, cells)).get(k, "") for k in ("session", "from", "task", "kind", "note")]))
            for cells in reader}


def finish_cut(home, staged, boundary, session, what):
    """A --split-done of another session cut short between its tasks.csv write and its boundary write left its entry
    with the time it was writing ("commit"), the boundary it split from, still the current one, and all its rows in
    tasks.csv. Finish it as it would have (the boundary moves there, the entry goes), then stop this run: it split from
    the old boundary."""
    present = None
    for other, entry in list(staged.items()):
        cut = entry.get("commit")
        if other == session or cut is None or entry["boundary"] != boundary or (
                boundary is not None and cut < boundary):
            continue
        present = present_rows(home) if present is None else present
        if {tuple(row) for row in entry["rows"]} <= present:
            write_private(os.path.join(home, "split-until.txt"), lambda f, cut=cut: f.write(local(cut) + "\n"))
            del staged[other]
            save_staged(home, staged)
            sys.exit(f"a --split-done of another session was cut short after its tasks.csv write; finished now, the "
                     f"boundary is {local(cut)}: run --pending again and split from there; {what}")


def chunk_errors(rows, boundary):
    """What the check with tasks.csv cannot see in a chunk: two rows of one session and start (the second would replace
    the first unseen when that start is staged already), a row without its start or not after the boundary (those
    prompts are split already). Run after that check, so every start is a valid time."""
    errors = [f"{session} {start}: two rows of the chunk start at the same time"
              for (session, start), n in Counter((row[0], row[1]) for row in rows).items() if n > 1]
    for session, start, *_ in rows:
        if not start:
            errors.append(f"{session}: no start (a staged row starts at a new prompt)")
        elif boundary is not None and parse_minute(start, "from") <= boundary:
            errors.append(f"{session} {start}: not after the boundary {local(boundary)}, "
                          "those prompts are split already")
    return errors


def stage_tasks(home, sessions, rows, restart=False):
    """--add --stage: keep the rows in this session's entry of add-staged.json for --split-done, which writes them all
    at once with the boundary; tasks.csv is not changed. They are checked with tasks.csv and the rows staged before as
    add_tasks checks them, and a chunk with a bad row stages nothing. A row of the same session id and start as a staged
    one replaces it, so a split staged again (after a context compaction) does not cut a task twice; with restart the
    rows staged before go first (a split staged again with other starts). Entries of other sessions stay as they are."""
    session = stage_session()
    rows = [clean_row(row) for row in rows]
    with staged_lock(home):
        staged, boundary = load_staged(home), read_split_until(home)
        finish_cut(home, staged, boundary, session, "nothing staged")
        kept = own_rows(staged.get(session), boundary, "nothing staged")
        dropped = len(kept) if restart else 0
        kept = [] if restart else kept
        at = {(row[0], row[1]): n for n, row in enumerate(kept)}
        new, same, replaced = [], 0, 0
        for row in rows:
            n = at.get((row[0], row[1]))
            if n is None:
                new.append(row)
            elif kept[n] == row:
                same += 1
            else:
                kept[n], replaced = row, replaced + 1
        checked_tasks(home, sessions, kept + new, STAGE_REFUSAL)
        errors = chunk_errors(rows, boundary)
        if errors:
            sys.exit(f"{STAGE_REFUSAL}:\n  " + "\n  ".join(errors))
        staged[session] = {"boundary": boundary, "staged": int(datetime.now(KYIV).timestamp()), "rows": kept + new}
        save_staged(home, staged)
    total = len(kept) + len(new)
    print(f"{f'прибрано підготовлених раніше: {dropped}; ' if dropped else ''}підготовлено рядків: нових {len(new)}, "
          f"замінено {replaced}, уже були {same}; разом {total}: у tasks.csv їх запише --split-done --rows {total} "
          "--after <межа з --pending>", file=sys.stderr)


def commit_split(home, sessions, until, allow_back, expected, after=None):
    """--split-done after its scan: this session's staged rows go to tasks.csv (add_tasks), the boundary moves, the entry
    goes. All under staged_lock, every check before the first write: the boundary is still `after` (from --pending, when
    given) and the one the rows were staged from, their number is --rows (`expected`, None without it: then the session
    must have none), none starts after the new boundary, they pass the check with tasks.csv. Before tasks.csv the entry
    gets the new boundary ("commit"), so a run cut short between the two writes is finished by the next one
    (finish_cut). Rows tasks.csv already has are not added again: run again, a --split-done cut short completes."""
    session = stage_session() if expected is not None else os.environ.get(SESSION_ENV, "")
    unchanged = "tasks.csv and split-until.txt not changed"
    with staged_lock(home):
        staged, boundary = load_staged(home), read_split_until(home)
        finish_cut(home, staged, boundary, session, unchanged)
        check_split_until(home, until, allow_back)  # again under the lock: the boundary write must not fail later
        entry, present = staged.get(session), present_rows(home)
        if entry and boundary == until != entry["boundary"] and {tuple(r) for r in entry["rows"]} <= present:
            rows = entry["rows"]  # the same --split-done was cut short after the boundary: only the entry is left
        else:
            if after is not None and boundary != after:
                sys.exit(f"the boundary is {local(boundary) if boundary else 'none'}, not --after {local(after)}: "
                         f"another session split meanwhile; {unchanged}")
            rows = own_rows(entry, boundary, unchanged)
            late = [f"{r[0]} {r[1]}" for r in rows if r[1] and parse_minute(r[1], "from") > until]
            if late:
                sys.exit(f"staged rows start after --split-done {local(until)}: {', '.join(late)}; {unchanged}")
        if len(rows) != (expected or 0):
            sys.exit(f"this session has {len(rows)} staged row(s), --rows says {expected or 0}"
                     f"{'' if expected is not None else ' (it is missing)'}: {unchanged}")
        new = [r for r in rows if tuple(r) not in present]
        if new:
            checked = checked_tasks(home, sessions, new)
            entry["commit"] = until
            save_staged(home, staged)
            add_tasks(home, sessions, new, checked)
        if entry or expected is not None:
            print(f"записано рядків: {len(new)}" + (f", уже були в tasks.csv: {len(rows) - len(new)}"
                                                    if len(rows) > len(new) else ""), file=sys.stderr)
        save_split_until(home, until, allow_back)
        if entry:
            del staged[session]
            save_staged(home, staged)
