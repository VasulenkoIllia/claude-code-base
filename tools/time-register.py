#!/usr/bin/env -S python3 -I
"""Global register of tasks and session time for all projects, built from Claude Code transcripts.

Source: ~/.claude/projects/<dir>/<session>.jsonl plus <session>/**/*.jsonl (subagents, workflows). The
transcripts are only read. Claude Code deletes them after cleanupPeriodDays, so --write keeps every session
it has seen in register.json (in --home): the register outlives the transcripts, a session whose transcript
has less than the register keeps its stored time, and the 10 latest register.json.bak-* copies are kept.

Time. All entries of a session (subagents included) go on one timeline; a gap not longer than IDLE_MIN
minutes is work, a longer gap is a break. "Годинник" merges the timelines of all sessions, so sessions that
ran at the same time are counted once. A fork copies the original's entries with the original's sessionId:
they count only in the original (live or stored). Time outside sessions (calls, server work) goes to extra_h.

Tasks. A session holds several tasks. A task starts at a row of tasks.csv in --home
(session,from,task,kind,size,extra_h,note: session is an id prefix of at least 8 chars, from is
"YYYY-MM-DD HH:MM" Kyiv time, empty from means the session start) or, for a session without rows there, at a
prompt that begins with "задача: <назва>" (after any <system-reminder> blocks the app puts in front of a typed
prompt; they are cut off). Time before the first task start belongs to the session title,
unless the first task starts within LEAD_SECS of the session start (hooks and the title come first).
Tasks of one project with the same name are one task. A bad tasks.csv row stops the run with its line number
(";" as the separator, as Excel saves it, is accepted).

Kinds (for estimates): module, integration, ui, data, bug, ops, analysis, docs, setup, refactor, prototype.
kind_auto is only a keyword guess from the title. Project level (T/R/V/UI) comes from the "Рівень" line of
the project card (CLAUDE.local.md, AGENTS.md or CLAUDE.md in ~/WebstormProjects/<project>).

Prompts. A message the user typed, also one sent while the model was working (Claude Code gives it to the model as
a queued_command attachment); a pasted block shows as "[вставлено N симв.]", a prompt of images only as
"[картинка]". Fork copies and repeated entries are left out everywhere, a printed prompt longer than 240 characters
ends with "…". A record of a form the scan does not know is no prompt and is warned of (an entry whose uuid or
sessionId is not text still counts), text that starts with "<" (usually typed) in a "примітка:" line of its own; a user
message, an attachment or an origin that is no object (also one on a queued record), or content of a prompt of another
form, also stops --write, --add and --split-done, so the register keeps those sessions' prompts and "задача:" markers.

Splitting new work. split-until.txt in --home holds the time up to which prompts are split into tasks.
--pending lists sessions with newer prompts, --pending --full also prints them (up to FULL_MAX_BYTES, the other
sessions as --prompts commands), --prompts SESSION --after TIME prints one session's (a session the app moved to
another project folder has a transcript in each: the newer one counts everywhere), --add appends task rows (checked with
the whole file, previous file kept as tasks.csv.bak-*; a row in the minute of a "задача:" marker replaces the marker),
--add ... --stage checks the rows the same way but only keeps them in add-staged.json (--restart drops the ones kept
before), --split-done TIME --rows N --after BOUNDARY writes the rows this session kept to tasks.csv and moves the mark
(not into the future, and back only with --allow-back; it scans the transcripts first, prints the lines of the scan as
--write does and stops on the records that stop a write and when no session of the transcripts there are was read).
So a split of any size goes in chunks of short commands: Claude Code asks before it runs a command it cannot parse, one
over 10000 characters among them, and nobody may be there to answer. The kept rows are per Claude Code session
(CLAUDE_CODE_SESSION_ID; inside Claude Code without it nothing is staged or written) with the boundary they were
checked from, under a lock that every write of tasks.csv takes: another session's rows are never written, and
--split-done writes nothing unless the boundary is still BOUNDARY (from --pending) and the one the rows were kept from,
N is the number this session kept and none starts after TIME. Run again after it was cut short, it completes the same
split; cut short between its two writes, the next run of any session finishes it and stops.

Code. This file is only the command line; the scan, the tasks, the register folder, the split in chunks and the report
are in the time_register package next to it (tools/time_register in the repo, ~/bin/time_register live).

Usage (installed by the base as ~/bin/claude-time; from the repo: python3 -I tools/time-register.py):
  claude-time                                    # hours by project, print only
  claude-time --by task --project my_app --since 2026-09-01
  claude-time --by kind --level T2               # hours per task kind, base for estimates
  claude-time --by task --grep 'чат|chat'        # analogs by task name or note
  claude-time --by session                       # one line per session
  claude-time --pending                          # sessions with prompts not yet split into tasks
  claude-time --pending --full                   # the same with their new prompts, for the weekly split
  claude-time --prompts 543f28d0 --after '2026-10-12 13:06'
  claude-time --add 543f28d0 '2026-10-13 10:00' 'Модуль чату: реалізація' module 'вкладення, 2 екрани'
  claude-time --add 543f28d0 '2026-10-13 10:00' 'Модуль чату: реалізація' module '' --add ... --stage
  claude-time --split-done '2026-10-13 18:00' --rows 12 --after '2026-10-06 09:00'   # 12 rows staged from that boundary
  claude-time --write                            # refresh register.json, register.csv, sessions.csv
"""
import argparse
import os
import re
import sys
from datetime import date, datetime, time, timedelta

sys.dont_write_bytecode = True  # no __pycache__ next to the live copy: doctor would report it as drift
# -I leaves the script's folder off sys.path; appended, so a stray file in ~/bin cannot shadow the standard library
sys.path.append(os.path.dirname(os.path.realpath(__file__)))
# pylint: disable=wrong-import-position
from time_register.patterns import BLOCK_SESSIONS_MAX, FULL_MAX_BYTES, KYIV, UNKNOWN_KINDS  # noqa: E402
from time_register.projects import project_level  # noqa: E402
from time_register.report import print_pending, print_prompts, report  # noqa: E402
from time_register.scan import (DUPLICATE_SESSIONS, LOSSY_SESSIONS, diverged_copies, known_sessions,  # noqa: E402
                                scan_all)
from time_register.staging import commit_split, stage_tasks, staged_lock  # noqa: E402
from time_register.store import (add_tasks, check_split_until, load_store, merge_store, read_split_until,  # noqa: E402
                                 save_exports, save_store)
from time_register.tasks import group_tasks, in_window, load_tasks, segments  # noqa: E402
from time_register.timeline import parse_minute  # noqa: E402
from time_register.transcript import STATS, lossy_forms, unknown_warning  # noqa: E402


def warn_unknown():
    """Warn of entries in a form the scan does not know (the lines of unknown_warning: their number, kinds and names):
    prompts that Claude Code wrote in a new form were once left out silently for weeks."""
    warning = unknown_warning()
    if warning:
        print(warning, file=sys.stderr)


def listed(ids):
    """Up to BLOCK_SESSIONS_MAX session ids, 8 characters each, then «…»."""
    ids = sorted(sid[:8] for sid in ids)
    return ", ".join(ids[:BLOCK_SESSIONS_MAX]) + (", …" if len(ids) > BLOCK_SESSIONS_MAX else "")


def warn_scan(live):
    """The lines of what the scan could not read and of the unknown forms, as --write prints them. True when there
    are transcripts, read or not (the owner, 20.10), but no session was read: --write and --split-done then stop."""
    if STATS["bad_lines"] or STATS["unreadable"] or STATS["bad_ts"]:
        print(f"увага: битих рядків {STATS['bad_lines']}, нечитаних файлів {STATS['unreadable']} "
              f"з {STATS['files'] + STATS['unreadable']}, нерозібраних timestamp {STATS['bad_ts']}", file=sys.stderr)
    if STATS["fork_entries"]:
        print(f"форки: {STATS['fork_entries']} скопійованих записів віддано оригінальним сесіям", file=sys.stderr)
    if DUPLICATE_SESSIONS:
        print(f"сесій з транскриптом у двох теках: {len(DUPLICATE_SESSIONS)} ({listed(DUPLICATE_SESSIONS)}), "
              "читається новіший", file=sys.stderr)
        diverged = diverged_copies()
        if diverged:
            print("увага: старіша копія транскрипту не є початком новішої, її записів не враховано: "
                  f"{listed(diverged)}", file=sys.stderr)
    warn_unknown()
    if live or not STATS["files"] + STATS["unreadable"]:
        return False
    print("увага: транскрипти є, але жодної сесії не прочитано (змінився формат?)", file=sys.stderr)
    return True


def refuse_lossy_write(a):
    """Stop --write, --add and --split-done when the scan saw records of a LOSSY_FORMS form (a user message or an
    attachment that is no object, an origin that is no object, also on a queued record, content of a would-be prompt
    of another form): a format change no typed text makes. Written now, their sessions would lose their prompts and
    "задача:" markers in the register, for good once tasks.csv has rows for them, and a boundary moved past prompts
    nobody saw would keep them out of --pending. Other unknown forms are written with the warning (a tag may be typed
    text, a plugin's origin is expected, an entry whose uuid or sessionId is not text still counts, blocks without
    text may be a document only). The line names the forms and up to BLOCK_SESSIONS_MAX of the sessions."""
    kinds = [UNKNOWN_KINDS[k] + (f": {n}" if n else "") for k, n in lossy_forms()]
    if not (kinds and (a.write or a.add or a.split_done)):
        return
    ids = sorted(sid[:8] for sid in LOSSY_SESSIONS)
    rest = f", інші {len(ids) - BLOCK_SESSIONS_MAX}" if len(ids) > BLOCK_SESSIONS_MAX else ""
    print(f"увага: реєстр не записано: через записи {', '.join(f'«{k}»' for k in kinds)} їхні сесії втратили б запити "
          f"й маркери «задача:»; --split-done теж не запускай, доки базу не оновлено; сесії: "
          f"{', '.join(ids[:BLOCK_SESSIONS_MAX])}{rest}", file=sys.stderr)
    sys.exit("split-until.txt not changed" if a.split_done else "the register was not written")


def split_done(a, home):
    """--split-done: write the rows this session staged with --add --stage to tasks.csv and move the boundary
    (commit_split), not when the scan read no session of the transcripts there are or saw records that would lose
    prompts (refuse_lossy_write); it prints the lines of the scan as --write does."""
    until = parse_minute(a.split_done, "--split-done")
    stored = load_store(home)
    live = scan_all(stored)
    if warn_scan(live):
        sys.exit("split-until.txt not changed")
    refuse_lossy_write(a)
    check_split_until(home, until, a.allow_back)  # a time that cannot be the boundary writes nothing, not even the folder
    after = parse_minute(a.after, "--after") if a.after else None
    commit_split(home, merge_store(stored, live), until, a.allow_back, a.rows, after)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--by", choices=("project", "task", "kind", "session", "day", "week"), default="project")
    ap.add_argument("--project", help="only this project (name as in the report)")
    ap.add_argument("--level", help="only projects whose level contains this, e.g. T2 or R2")
    ap.add_argument("--grep", help="only tasks whose name or note matches this regex (case-insensitive)")
    ap.add_argument("--since", type=date.fromisoformat, help="count time from this day on, Kyiv time")
    ap.add_argument("--until", type=date.fromisoformat, help="count time up to this day, inclusive")
    ap.add_argument("--home", default=os.path.expanduser("~/claude-time"), help="register folder (default ~/claude-time)")
    ap.add_argument("--prompts", metavar="SESSION", help="print the prompts of one session with Kyiv times and exit "
                    "(without fork copies, as --pending counts: reads --home's register.json for that)")
    ap.add_argument("--after", metavar="'YYYY-MM-DD HH:MM'", help="with --prompts: only prompts after this time; "
                    "with --split-done: the boundary the split started from (first line of --pending), else nothing "
                    "is written")
    ap.add_argument("--pending", action="store_true", help="sessions with prompts not yet split into tasks")
    ap.add_argument("--full", action="store_true",
                    help=f"with --pending: also their new prompts, up to {FULL_MAX_BYTES} bytes, then --prompts commands")
    ap.add_argument("--split-done", metavar="'YYYY-MM-DD HH:MM'", help="prompts up to this time are split: save it")
    ap.add_argument("--allow-back", action="store_true", help="with --split-done: accept a time before the saved one")
    ap.add_argument("--rows", type=int, metavar="N", help="with --split-done and --after: the number of rows this "
                    "session staged (0: none); another number stops it, and so do staged rows without it")
    ap.add_argument("--add", nargs=5, action="append", metavar=("SESSION", "FROM", "TASK", "KIND", "NOTE"),
                    help="append a task row to tasks.csv (FROM may be empty: the session start); repeatable")
    ap.add_argument("--stage", action="store_true", help="with --add: check the rows and keep them for --split-done, "
                    "which writes them with the boundary (a split in chunks); tasks.csv is not changed")
    ap.add_argument("--restart", action="store_true", help="with --add --stage: drop the rows this session staged "
                    "before (the split staged again from its first chunk)")
    ap.add_argument("--write", action="store_true", help="refresh register.json, register.csv and sessions.csv in --home")
    a = ap.parse_args()
    if a.after and not (a.prompts or a.split_done):
        ap.error("--after works only with --prompts or --split-done")
    if a.split_done and (a.add or a.write or a.pending or a.prompts):
        ap.error("--split-done runs alone")
    if a.pending and (a.add or a.write):
        ap.error("--pending runs alone")
    if a.full and not a.pending:
        ap.error("--full works only with --pending")
    if a.allow_back and not a.split_done:
        ap.error("--allow-back works only with --split-done")
    if a.stage and (not a.add or a.write):
        ap.error("--stage works only with --add, without --write")
    if a.rows is not None and (not a.split_done or a.rows < 0):
        ap.error("--rows works only with --split-done, as a number from 0")
    if a.rows is not None and not a.after:
        ap.error("--rows needs --after: the boundary the split started from (first line of --pending)")
    if a.restart and not a.stage:
        ap.error("--restart works only with --add --stage")

    home = os.path.abspath(os.path.expanduser(a.home))
    if a.prompts:
        after = parse_minute(a.after, "--after") if a.after else None
        print_prompts(a.prompts, known_sessions(load_store(home)), after)
        warn_unknown()
        return
    if a.split_done:
        split_done(a, home)
        return
    store_path = os.path.join(home, "register.json")
    if a.write and not os.path.exists(store_path) and any(
            os.path.exists(os.path.join(home, n)) for n in ("register.csv", "sessions.csv")):
        sys.exit(f"{store_path} is missing but {home} has a register: restore register.json from a .bak-* copy first")
    stored = load_store(home)
    live = scan_all(stored)
    if warn_scan(live) and a.write:
        sys.exit("the register was not written")
    refuse_lossy_write(a)
    store = merge_store(stored, live)
    if a.add:
        if a.stage:
            stage_tasks(home, store, a.add, a.restart)
        else:
            with staged_lock(home):  # a --split-done writes tasks.csv under the same lock
                add_tasks(home, store, a.add)
        if not a.write:
            return
    if a.pending:
        print_pending(live, read_split_until(home), known_sessions(stored), a.full)
        return
    ann, errors = load_tasks(home, store)
    if a.write:
        save_store(home, store)
    if errors:
        sys.exit(f"{os.path.join(home, 'tasks.csv')}: {len(errors)} bad row(s), "
                 f"{'register.json saved, ' if a.write else ''}nothing reported:\n  " + "\n  ".join(errors))
    # a task without time (a fork copy, a one-prompt session) only clutters the register
    segs = [s for sid, rec in store.items() for s in segments(rec, ann.get(sid, [])) if s["secs"] > 0]
    if a.write:
        with staged_lock(home):  # it makes tasks.csv when there is none
            save_exports(home, store, segs, live)
        print(f"записано в {home}: сесій {len(store)} (з транскриптами {len(live)})", file=sys.stderr)

    if a.project:
        segs = [s for s in segs if s["project"] == a.project]
    if a.level:
        segs = [s for s in segs if a.level.lower() in project_level(s["project"]).lower().split()]
    if a.grep:
        try:
            pattern = re.compile(a.grep, re.I)
        except re.error as e:
            sys.exit(f"--grep: {e}")
        # match whole tasks (a note usually sits on one part only), then keep all their parts
        hits = {(t["project"], t["task"]) for t in group_tasks(segs) if pattern.search(f"{t['task']} {t['note']}")}
        segs = [s for s in segs if (s["project"], s["task"]) in hits]
    if a.since or a.until:
        lo = datetime.combine(a.since, time.min, KYIV).timestamp() if a.since else float("-inf")
        hi = datetime.combine(a.until + timedelta(days=1), time.min, KYIV).timestamp() if a.until else float("inf")
        segs = in_window(segs, lo, hi)
    report(store, segs, a.by)


if __name__ == "__main__":
    main()
