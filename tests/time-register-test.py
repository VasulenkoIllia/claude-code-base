#!/usr/bin/env -S python3 -I
"""Offline test of claude-time (tools/time-register.py and its package tools/time_register).

Builds made-up transcripts and a project card in a temp folder under /private/tmp (deleted afterwards) and runs the
command line against them with HOME pointing there and --home in the same temp folder:
  A (project demo, card T1 R0 V0 none): "задача: Перша задача тесту" at 10:00, prompts at 10:30 and 11:30; work
     10:00-10:40 and 11:30-11:50 (the 50-minute gap is a break), so 1.0 h
  B (project demo): a prompt at 12:00, "задача: Маркер B" at 12:20, work 12:00-12:30
  C: markers "задача: Маркер C" at 13:00:37 and "задача: Другий маркер C" at 13:10, work until 13:20
  D: prompts behind <system-reminder> blocks the app puts in front (as one string, two in a row, and as a list of
     text blocks, one of them a marker), a reminder in the middle of a prompt (kept), a message of a reminder only and
     a reminder before a task notification (neither is a prompt); work 14:00-14:20
  G: prompts the scan used to miss, at 14:30-14:44: pasted blocks (alone, with text after, in the middle of a prompt
     with a closing tag inside the pasted text), prompts queued while the model worked (with origin human, the old
     form without origin, behind a reminder, images only, text with an image, a "задача:" marker), typed prompts of
     two images, of text with an image and with two pasted blocks, an entry repeated with its uuid and a prompt of
     exactly 240 characters; and what stays out: queued task notifications
     (also one without a tag), messages of other sessions (queued meta or plain, and typed), a meta queued prompt, a
     CI event, a meta image, another attachment; work 14:30-14:48
  H: a fork of G: copies of two of G's prompts (G's sessionId), its own prompt at 14:50, work until 14:55
  E: 60 prompts of 257 characters, mostly Cyrillic, at 15:00-15:59: fewer than 25000 characters, more bytes
  F (id 0fff..., so first by id, last by time): an entry at 18:00, "задача: Маркер F" at 18:02, "задача: Другий
     маркер F" at 18:25, work 18:00-18:40
Checks: the package imports and writes no bytecode; --write makes register.json, register.csv, sessions.csv and
tasks.csv with mode 0600 in a 0700 folder; the report counts A's marker task; --prompts with --add or --write
writes nothing (the allow rule for --prompts relies on it) and --prompts with --split-done stops; --add carries A's
marker over as a row and splits the time at 10:30 (also on a tasks.csv of a bare header without a newline), a
second --add for A carries nothing and writes its note on one line; a row in the minute of C's
first marker replaces it (the second is carried), a row without a from replaces F's first marker (at the session
start) but not the second one, nor B's marker 20 minutes in; a bad batch writes nothing and says nothing of markers;
--split-done moves the boundary that --pending counts from, refuses the current minute, a time in the future and a
time back without --allow-back; D's prompts count without the reminders; G's prompts count and print as labels
without the pasted text, the queued "задача:" starts a task, H prints and counts only its own prompt, a prompt over
240 characters ends with "…", known forms give no warning; --pending lists the sessions by time; --pending --full
writes nothing, prints the new prompts of A, B, C, D, G and H (without the copies) within FULL_MAX_BYTES and gives E
and F (after E, to keep the order) as --prompts commands, and --prompts --after of every session prints as many
prompts as the table counts; with 120 sessions (a second HOME) whose table and commands would not fit, one line with
the command pattern and --after; a session id with two transcripts (a third HOME): --full and --prompts print the
prompts of the one the scan reads; a fork whose original is only in register.json (two more HOMEs): --prompts leaves out the
copies with that register (--pending --full too), keeps them without it and stops on a broken one; forms the scan
does not know (one more HOME): not counted, warnings with their number and each kind with its names and counts,
a pasted block without its closing tag counts as a label but is no session title, a typed prompt that starts with a
tag not of Claude Code (HTML, a block the app adds, a name over 30 characters, cut) or with "<" and no tag, a queued
prompt or shell command whose origin sits on its entry (with a new mode too) and a plugin's prompt are warned of and
stop no --write; a channel message, a queued shell command, an auto-continuation, Claude Code's own tags at
the start (command output, a slash command, side sessions, a message of another session behind a reminder, a
scheduled run, shell input) and its origin kinds observer, observer-activity, coordinator and slack-ping are neither
counted nor warned of; a user record whose message is no object (a string, a list, a number) or that has none (one
more HOME): --by session, --prompts and --pending --full run, it is no prompt and is warned of as the kind "message
не об'єкт", once even with an unknown origin, while --write and --add write nothing and say so, naming the session;
meta, sidechain and compact summary records, an assistant record and a subagent's records of that form are not
warned of and stop no --write; an entry whose uuid or sessionId is not text (one more HOME) still counts and is
warned of, blocks of a would-be prompt with no text or image (a queued one too, also beside an empty text) are no
prompt and are warned of while a text with another block counts and an empty text block alone is no prompt without a
warning, a model answer whose id, model or output count has another form and a subagent's attachment that is no
object are skipped without a warning (an output count of another form keeps the count of a streamed line before),
content or blocks of another form in a record that is no prompt, an empty text or list are not warned of, a JSON line
that is no object or has an integer over Python's digit limit is a broken line, and --write and --split-done run,
both printing the lines of the scan; an origin that is no object (also one on a queued record), an attachment that is
no object or none and content of a would-be prompt of another form (one more HOME of 9 sessions) are no prompt and
are warned of, and --write, --add and --split-done (with --allow-back too) write nothing and say so, naming the kinds
and the first 5 of their sessions by id; such a record in a fork's copy stops nothing while its original is only in
register.json (both print the forks line) and stops --write, naming the original alone, while the original is live;
transcripts of which no session is read (three more HOMEs: broken lines only, a timestamp that does not parse, a file
that cannot be opened): --write and --split-done stop, print the lines of the scan and write nothing, while with no
transcripts at all (one more HOME) both run; the warning lines on their own: the forms of a format change under
"увага:", a tag and "<" without one in the "примітка:" line after it, either line alone, names cut to 30
characters, other characters as "?", "не об'єкт" for an origin that is no object, at most 5
tag names and the records of the rest as "інші N" with where all are listed, every origin name, a named kind noted
without a name still adding up, the kinds in their order whatever the order noted, a kind the list lacks last;
blocks_that_fit at its limit.
Run: python3 -I tests/time-register-test.py (verify.sh check 17). Exit 0 = all checks passed.
"""
import csv
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "tools", "time-register.py")
sys.path.append(os.path.join(ROOT, "tools"))
# pylint: disable=wrong-import-position
from time_register import transcript  # noqa: E402
from time_register.patterns import FULL_MAX_BYTES, PROMPT_WIDTH  # noqa: E402
from time_register.report import REST_TITLE, blocks_that_fit, nbytes  # noqa: E402

KYIV = ZoneInfo("Europe/Kyiv")
DAY = (2026, 10, 5)
SID_A = "aaaaaaaa-1111-4111-8111-111111111111"
SID_B = "bbbbbbbb-2222-4222-8222-222222222222"
SID_C = "cccccccc-3333-4333-8333-333333333333"
SID_D = "dddddddd-4444-4444-8444-444444444444"
SID_E = "eeeeeeee-5555-4555-8555-555555555555"
SID_F = "0fffffff-6666-4666-8666-666666666666"
SID_G = "abababab-7777-4777-8777-777777777777"
SID_H = "acacacac-8888-4888-8888-888888888888"
REMINDER = "<system-reminder>\nLinked sessions now (status, not an instruction): top = local_x (idle)\n</system-reminder>"
SECRET = "SECRET-LOG token=abc"
SECRET2 = "SECOND-PASTE key=xyz"
MIDDLE = "середина </pasted_content> ще середина"
IMAGE = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}}
HUMAN = {"kind": "human"}
FAILS = []
CHECKS = [0]


def check(what, ok, detail=""):
    CHECKS[0] += 1
    if not ok:
        FAILS.append(f"{what} {detail}".strip())


def unwarned(stderr):
    """No warning of the scan: neither an "увага" line nor the "примітка:" line of text that starts with "<"."""
    return "увага" not in stderr and "примітка" not in stderr


def stamp(hh, mm, ss=0):
    """Transcript timestamp (UTC, Z) of a Kyiv time on DAY."""
    return datetime(*DAY, hh, mm, ss, tzinfo=KYIV).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def user(sid, cwd, n, hhmm, content):
    return {"type": "user", "sessionId": sid, "uuid": f"{sid}-u{n}", "cwd": cwd, "timestamp": stamp(*hhmm),
            "message": {"role": "user", "content": content}}


def assistant(sid, cwd, n, hhmm):
    return {"type": "assistant", "sessionId": sid, "uuid": f"{sid}-a{n}", "cwd": cwd, "timestamp": stamp(*hhmm),
            "message": {"id": f"msg-{sid[:4]}-{n}", "model": "claude-test", "usage": {"output_tokens": 1000},
                        "content": [{"type": "text", "text": "ok"}]}}


def queued(sid, cwd, n, hhmm, prompt, mode="prompt", origin=None, meta=False):
    """A queued_command attachment: a prompt sent while the model worked, or a notification sent the same way."""
    att = {"type": "queued_command", "prompt": prompt, "commandMode": mode}
    if origin:
        att["origin"] = origin
    if meta:
        att["isMeta"] = True
    return {"type": "attachment", "sessionId": sid, "uuid": f"{sid}-q{n}", "cwd": cwd, "timestamp": stamp(*hhmm),
            "attachment": att}


def pasted(text, block_id):
    return f'<pasted_content id="{block_id}">{text}</pasted_content id="{block_id}">'


def write_jsonl(path, records):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def build_home(tmp):
    home = os.path.join(tmp, "home")
    card = os.path.join(home, "WebstormProjects", "demo")
    os.makedirs(card)
    with open(os.path.join(card, "CLAUDE.local.md"), "w", encoding="utf-8") as f:
        f.write("# demo\n\n## Розмір\nРівень T1 · Ризик R0 · Дані V0 · UI none\n")
    cwd = "/Users/time-register-test/WebstormProjects/demo"  # a folder under the temp HOME would count as (scratch)
    sessions = os.path.join(home, ".claude", "projects", "-demo")
    write_jsonl(os.path.join(sessions, SID_A + ".jsonl"), [
        {"type": "ai-title", "aiTitle": "Сесія A", "sessionId": SID_A},
        user(SID_A, cwd, 1, (10, 0), "задача: Перша задача тесту"),
        assistant(SID_A, cwd, 1, (10, 20)),
        user(SID_A, cwd, 2, (10, 30), "друга частина"),
        assistant(SID_A, cwd, 2, (10, 40)),
        user(SID_A, cwd, 3, (11, 30), "після перерви"),
        assistant(SID_A, cwd, 3, (11, 50)),
    ])
    write_jsonl(os.path.join(sessions, SID_B + ".jsonl"), [
        {"type": "ai-title", "aiTitle": "Сесія B", "sessionId": SID_B},
        user(SID_B, cwd, 1, (12, 0), "окрема сесія"),
        user(SID_B, cwd, 2, (12, 20), "задача: Маркер B"),
        assistant(SID_B, cwd, 1, (12, 30)),
    ])
    write_jsonl(os.path.join(sessions, SID_C + ".jsonl"), [
        {"type": "ai-title", "aiTitle": "Сесія C", "sessionId": SID_C},
        user(SID_C, cwd, 1, (13, 0, 37), "задача: Маркер C"),
        user(SID_C, cwd, 2, (13, 10), "задача: Другий маркер C"),
        assistant(SID_C, cwd, 1, (13, 20)),
    ])
    write_jsonl(os.path.join(sessions, SID_D + ".jsonl"), [
        {"type": "ai-title", "aiTitle": "Сесія D", "sessionId": SID_D},
        user(SID_D, cwd, 1, (14, 0), REMINDER + "\n\nзапит після нагадування"),
        user(SID_D, cwd, 2, (14, 5), [{"type": "text", "text": REMINDER},
                                      {"type": "text", "text": "задача: Задача з нагадуванням"}]),
        user(SID_D, cwd, 3, (14, 10), REMINDER),
        user(SID_D, cwd, 4, (14, 12), REMINDER + "\n<task-notification>\n<task-id>x</task-id>\n</task-notification>"),
        user(SID_D, cwd, 5, (14, 14), REMINDER + "\n" + REMINDER + "\n\nзапит після двох нагадувань"),
        user(SID_D, cwd, 6, (14, 16), "текст до нагадування " + REMINDER + " текст після"),
        assistant(SID_D, cwd, 1, (14, 20)),
    ])
    g_pasted_after = user(SID_G, cwd, 2, (14, 31), pasted("вставка два", "p2x3") + "\n\nзапит після вставки")
    g_queued = queued(SID_G, cwd, 4, (14, 33), "запит у черзі", origin=HUMAN)
    g_repeated = user(SID_G, cwd, 17, (14, 43), "повтор запису")
    write_jsonl(os.path.join(sessions, SID_G + ".jsonl"), [
        {"type": "ai-title", "aiTitle": "Сесія G", "sessionId": SID_G},
        user(SID_G, cwd, 1, (14, 30), pasted("\n" + SECRET + "\n", "p1x2")),
        g_pasted_after,
        user(SID_G, cwd, 3, (14, 32), "текст до вставки " + pasted(MIDDLE, "p3x4") + " текст після вставки"),
        g_queued,
        queued(SID_G, cwd, 5, (14, 34), "старий запит у черзі"),
        queued(SID_G, cwd, 6, (14, 35), "<task-notification>\n<task-id>x</task-id>\n</task-notification>",
               mode="task-notification", origin={"kind": "task-notification"}),
        queued(SID_G, cwd, 7, (14, 35, 30), "сповіщення без тегу", mode="task-notification"),
        queued(SID_G, cwd, 8, (14, 36), '<agent-message from="x">звіт</agent-message>', origin={"kind": "peer"},
               meta=True),
        queued(SID_G, cwd, 9, (14, 36, 30), "текст іншої сесії", origin={"kind": "peer"}),
        dict(user(SID_G, cwd, 9, (14, 36, 40), "повідомлення іншої сесії"), origin={"kind": "peer"}),
        queued(SID_G, cwd, 10, (14, 37), "мета-запит у черзі", origin=HUMAN, meta=True),
        queued(SID_G, cwd, 11, (14, 37, 30), "<ci-monitor-event>\nCI failed\n</ci-monitor-event>"),
        queued(SID_G, cwd, 12, (14, 38), REMINDER + "\n\nзапит у черзі після нагадування", origin=HUMAN),
        queued(SID_G, cwd, 13, (14, 39), [IMAGE], origin=HUMAN),
        user(SID_G, cwd, 14, (14, 40), [IMAGE, IMAGE]),
        dict(user(SID_G, cwd, 15, (14, 41), [IMAGE]), isMeta=True),
        queued(SID_G, cwd, 16, (14, 42), "задача: Задача з черги", origin=HUMAN),
        g_repeated,
        g_repeated,
        user(SID_G, cwd, 18, (14, 44), "р" * PROMPT_WIDTH),
        {"type": "attachment", "sessionId": SID_G, "uuid": f"{SID_G}-t1", "cwd": cwd, "timestamp": stamp(14, 45),
         "attachment": {"type": "total_tokens_reminder", "content": "текст нагадування"}},
        user(SID_G, cwd, 19, (14, 46), [{"type": "text", "text": "запит зі скриншотом"}, IMAGE]),
        queued(SID_G, cwd, 20, (14, 46, 30), [{"type": "text", "text": "запит у черзі зі скриншотом"}, IMAGE],
               origin=HUMAN),
        user(SID_G, cwd, 21, (14, 47), pasted("перша вставка", "q1w2") + " і " + pasted(SECRET2, "e3r4")),
        assistant(SID_G, cwd, 1, (14, 48)),
    ])
    write_jsonl(os.path.join(sessions, SID_H + ".jsonl"), [
        g_pasted_after, g_queued,
        {"type": "ai-title", "aiTitle": "Сесія H", "sessionId": SID_H},
        user(SID_H, cwd, 1, (14, 50), "власний запит форку"),
        assistant(SID_H, cwd, 1, (14, 55)),
    ])
    long_prompts = [user(SID_E, cwd, i, (15, i), f"довгий запит {i:03} " + "х" * 240) for i in range(60)]
    write_jsonl(os.path.join(sessions, SID_E + ".jsonl"), [
        {"type": "ai-title", "aiTitle": "Сесія E", "sessionId": SID_E}, *long_prompts, assistant(SID_E, cwd, 1, (16, 0))])
    write_jsonl(os.path.join(sessions, SID_F + ".jsonl"), [
        {"type": "ai-title", "aiTitle": "Сесія F", "sessionId": SID_F},
        assistant(SID_F, cwd, 1, (18, 0)),
        user(SID_F, cwd, 1, (18, 2), "задача: Маркер F"),
        user(SID_F, cwd, 2, (18, 25), "задача: Другий маркер F"),
        assistant(SID_F, cwd, 2, (18, 40)),
    ])
    return home


def run(home, *args):
    env = {"HOME": home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}
    return subprocess.run([sys.executable, "-I", CLI, *args], env=env, capture_output=True, text=True, check=False)


def files_of(reg):
    """Name, mode, inode, mtime and sha256 of every file in the register folder: what a run must not change. The
    inode and mtime show a rewrite with the same content too (every write is a temp file renamed over the old one)."""
    if not os.path.isdir(reg):
        return None
    out = {}
    for name in sorted(os.listdir(reg)):
        p = os.path.join(reg, name)
        st = os.stat(p)
        with open(p, "rb") as f:
            out[name] = (stat.S_IMODE(st.st_mode), st.st_ino, st.st_mtime_ns, hashlib.sha256(f.read()).hexdigest())
    return out


def task_hours(out, name):
    """Hours column of the --by task line of a task, or None."""
    for line in out.splitlines():
        if line.endswith(name):
            return line[24:30].strip()
    return None


def task_rows(reg):
    with open(os.path.join(reg, "tasks.csv"), encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.reader(f)][1:]


def split_until(reg):
    with open(os.path.join(reg, "split-until.txt"), encoding="utf-8") as f:
        return f.read()


def checks_split(home, reg):
    """The register, --prompts that writes nothing, --add with A's marker carried over."""
    r = run(home, "--help")
    check("--help exit 0 (the package imports)", r.returncode == 0 and "--prompts" in r.stdout, r.stderr[-300:])

    r = run(home, "--write", "--home", reg)
    check("--write exit 0", r.returncode == 0, r.stderr[-300:])
    files = files_of(reg) or {}
    check("--write makes the four files and the lock it writes them under", set(files) == {
        "register.json", "register.csv", "sessions.csv", "tasks.csv", "add-staged.lock"}, str(sorted(files)))
    check("files are 0600", all(f[0] == 0o600 for f in files.values()), str(files))
    check("the register folder is 0700", stat.S_IMODE(os.stat(reg).st_mode) == 0o700)

    r = run(home, "--by", "task", "--home", reg)
    check("A's marker task has 1.0 h", task_hours(r.stdout, "Перша задача тесту") == "1.0", r.stdout)
    r = run(home, "--home", reg)
    check("the project shows the card level", "T1 R0 V0 none" in r.stdout, r.stdout)

    before = files_of(reg)
    # a valid row (10:45 is no marker's minute): if --prompts fell through, --add would write it
    r = run(home, "--prompts", SID_A[:8], "--add", SID_A[:8], "2026-10-05 10:45", "Задача з --prompts", "module", "",
            "--home", reg)
    check("--prompts --add prints the prompts", r.returncode == 0 and "задача: Перша задача тесту" in r.stdout,
          r.stdout + r.stderr)
    check("--prompts --add writes nothing", files_of(reg) == before)
    r = run(home, "--prompts", SID_A[:8], "--write", "--home", reg)
    check("--prompts --write prints the prompts", r.returncode == 0 and "після перерви" in r.stdout, r.stderr[-300:])
    check("--prompts --write writes nothing", files_of(reg) == before)
    r = run(home, "--prompts", SID_A[:8], "--split-done", "2026-10-05 10:00", "--home", reg)
    check("--prompts --split-done stops", r.returncode == 2, str(r.returncode))
    check("--prompts --split-done writes nothing", files_of(reg) == before)
    fresh = os.path.join(os.path.dirname(reg), "fresh")
    r = run(home, "--prompts", SID_A[:8], "--add", SID_A[:8], "2026-10-05 10:45", "x", "module", "", "--write",
            "--home", fresh)
    check("--prompts with --add and --write makes no register folder", r.returncode == 0 and not os.path.exists(fresh),
          r.stderr[-300:])

    r = run(home, "--add", SID_A[:8], "2026-10-05 10:30", "Друга задача тесту", "module", "нотатка", "--home", reg)
    check("--add exit 0", r.returncode == 0, r.stderr[-300:])
    check("--add carries A's marker over", "перенесено в tasks.csv: 1" in r.stderr, r.stderr[-300:])
    check("--add keeps a tasks.csv.bak copy", any(n.startswith("tasks.csv.bak-") for n in os.listdir(reg)))
    r = run(home, "--by", "task", "--home", reg)
    check("the marker task keeps 10:00-10:30", task_hours(r.stdout, "Перша задача тесту") == "0.5", r.stdout)
    check("the added task gets the rest of A", task_hours(r.stdout, "Друга задача тесту") == "0.5", r.stdout)
    r = run(home, "--add", SID_A[:8], "2026-10-05 11:40", "Третя задача тесту", "module", "два\n рядки", "--home", reg)
    check("a second --add for A carries nothing", r.returncode == 0 and "маркери" not in r.stderr, r.stderr[-300:])
    rows = [row for row in task_rows(reg) if row[0] == SID_A[:8]]
    check("A's rows: the marker once and the two added",
          sorted(row[2] for row in rows) == ["Друга задача тесту", "Перша задача тесту", "Третя задача тесту"], str(rows))
    check("--add writes a note on one line", rows[-1][6] == "два рядки", str(rows[-1]))


def checks_bare_header(home, tmp):
    """tasks.csv of a header only, without a newline (as an editor may save it): --add still carries A's marker."""
    bare = os.path.join(tmp, "bare")
    os.makedirs(bare, mode=0o700)
    with open(os.path.join(bare, "tasks.csv"), "w", encoding="utf-8", newline="") as f:
        f.write("session,from,task,kind,size,extra_h,note")
    r = run(home, "--add", SID_A[:8], "2026-10-05 10:30", "Друга задача тесту", "module", "", "--home", bare)
    check("a header without a newline: --add carries A's marker", r.returncode == 0
          and "перенесено в tasks.csv: 1" in r.stderr, r.stderr[-300:])
    check("... and writes both rows", sorted(row[2] for row in task_rows(bare)) == ["Друга задача тесту",
                                                                                     "Перша задача тесту"])


def checks_marker_replaced(home, reg):
    """A row in the minute of a marker (13:00 for a marker at 13:00:37, a from with a space) replaces it instead of
    failing the batch as a second start; a row without a from replaces a marker at the session start."""
    r = run(home, "--add", SID_C[:8], " 2026-10-05 13:00", "Нова назва C", "bug", "", "--home", reg)
    check("--add in a marker's minute exit 0", r.returncode == 0, r.stderr[-300:])
    check("--add says one marker replaced, one carried", "замінено новими рядками з того самого часу: 1" in r.stderr
          and "перенесено в tasks.csv: 1" in r.stderr, r.stderr[-300:])
    names = [row[2] for row in task_rows(reg) if row[0] == SID_C[:8]]
    check("C's rows: the new name and the second marker", sorted(names) == ["Другий маркер C", "Нова назва C"], str(names))
    r = run(home, "--by", "task", "--home", reg)
    check("the replaced marker is gone from the report", r.returncode == 0 and task_hours(r.stdout, "Маркер C") is None
          and task_hours(r.stdout, "Другий маркер C") is not None, r.stdout)
    check("the new row takes 13:00-13:10", task_hours(r.stdout, "Нова назва C") == "0.2", r.stdout)

    r = run(home, "--add", SID_F[:8], "", "Задача F з початку", "module", "", "--home", reg)
    check("--add without a from exit 0", r.returncode == 0, r.stderr[-300:])
    check("... replaces F's first marker, carries the second", "замінено новими рядками з того самого часу: 1"
          in r.stderr and "перенесено в tasks.csv: 1" in r.stderr, r.stderr[-300:])
    r = run(home, "--add", SID_B[:8], "", "Задача B з початку", "module", "", "--home", reg)
    check("--add without a from keeps a marker 20 minutes in", r.returncode == 0 and "перенесено в tasks.csv: 1"
          in r.stderr and "замінено" not in r.stderr, r.stderr[-300:])
    r = run(home, "--by", "task", "--home", reg)
    check("F: the new row up to the second marker", r.returncode == 0 and task_hours(r.stdout, "Маркер F") is None
          and task_hours(r.stdout, "Задача F з початку") == "0.4" and task_hours(r.stdout, "Другий маркер F") == "0.2",
          r.stdout)
    check("B: the new row up to the marker", task_hours(r.stdout, "Задача B з початку") == "0.3"
          and task_hours(r.stdout, "Маркер B") == "0.2", r.stdout)

    before = files_of(reg)
    r = run(home, "--add", SID_D[:8], "2026-10-05 14:30", "Погана задача", "wrongkind", "", "--home", reg)
    check("a bad batch stops and says nothing of markers", r.returncode == 1 and "wrongkind" in r.stderr
          and "маркери" not in r.stderr, r.stderr[-300:])
    check("... and writes nothing", files_of(reg) == before)


def checks_boundary(home, reg):
    """--split-done: the boundary --pending counts from; not the current minute nor a future time, back only with
    --allow-back. --pending lists the sessions by their first new prompt."""
    r = run(home, "--split-done", "2026-10-05 10:30", "--home", reg)
    check("--split-done exit 0", r.returncode == 0, r.stderr[-300:])
    check("split-until.txt holds the minute", split_until(reg) == "2026-10-05 10:30\n")
    r = run(home, "--pending", "--home", reg)
    check("--pending counts the prompts after 10:30", "Нових запитів: 86" in r.stdout, r.stdout[:300])
    order = [line[:8] for line in r.stdout.splitlines()[2:]]
    by_time = (SID_A, SID_B, SID_C, SID_D, SID_G, SID_H, SID_E, SID_F)
    check("--pending lists the sessions by time, not by id", order == [s[:8] for s in by_time], str(order))
    now_reg = os.path.join(os.path.dirname(reg), "now")
    minute = datetime.now(KYIV).replace(second=0, microsecond=0)
    r = run(home, "--split-done", f"{minute:%Y-%m-%d %H:%M}", "--home", now_reg)
    same_minute = datetime.now(KYIV).replace(second=0, microsecond=0) == minute  # else the minute was over: no check
    check("--split-done in the current minute stops", not same_minute or (
        r.returncode == 1 and "not over yet" in r.stderr and not os.path.exists(now_reg)), r.stderr[-300:])
    r = run(home, "--split-done", "2099-01-01 00:00", "--home", reg)
    check("--split-done in the future stops", r.returncode == 1 and "not over yet" in r.stderr, r.stderr[-300:])
    check("... and keeps the boundary", split_until(reg) == "2026-10-05 10:30\n")
    r = run(home, "--split-done", "2026-10-05 10:00", "--home", reg)
    check("--split-done back stops", r.returncode == 1 and "--allow-back" in r.stderr, r.stderr[-300:])
    check("... and keeps the boundary", split_until(reg) == "2026-10-05 10:30\n")
    r = run(home, "--split-done", "2026-10-05 10:00", "--allow-back", "--home", reg)
    check("--split-done back with --allow-back exit 0", r.returncode == 0 and "назад" in r.stderr, r.stderr[-300:])
    check("... moves the boundary back", split_until(reg) == "2026-10-05 10:00\n")
    r = run(home, "--split-done", "2026-10-05 10:30", "--home", reg)
    check("--split-done forward again exit 0", r.returncode == 0 and split_until(reg) == "2026-10-05 10:30\n")
    r = run(home, "--allow-back", "--home", reg)
    check("--allow-back alone stops", r.returncode == 2, str(r.returncode))
    r = run(home, "--full", "--home", reg)
    check("--full without --pending stops", r.returncode == 2, str(r.returncode))


def checks_reminders(home, reg):
    """Prompts behind <system-reminder> blocks count; reminders only, or before a notification, do not; a reminder in
    the middle of a prompt stays in it."""
    r = run(home, "--prompts", SID_D[:8])
    lines = [line[18:] for line in r.stdout.splitlines()]
    check("--prompts shows D's prompts without the leading reminders", lines[:3] == [
        "запит після нагадування", "задача: Задача з нагадуванням", "запит після двох нагадувань"], r.stdout)
    check("... and keeps a reminder in the middle", len(lines) == 4 and lines[3].startswith(
        "текст до нагадування <system-reminder>") and lines[3].endswith("текст після"), r.stdout)
    r = run(home, "--by", "session", "--home", reg)
    d_line = next((line for line in r.stdout.splitlines() if line.startswith(SID_D[:8])), "")
    check("--by session counts 4 prompts in D", d_line[36:43].strip() == "4", d_line)
    r = run(home, "--by", "task", "--home", reg)
    check("a marker behind a reminder starts a task", task_hours(r.stdout, "Задача з нагадуванням") == "0.3", r.stdout)


def checks_new_prompts(home, reg):
    """G: pasted blocks print as labels, queued prompts and images count, notifications, other sessions and meta
    entries do not, a repeated entry prints once; H prints and counts only its own prompt; "…" after 240 characters."""
    r = run(home, "--prompts", SID_G[:8])
    lines = [line[18:] for line in r.stdout.splitlines()]
    check("--prompts G: labels for pasted blocks, queued prompts and images, no notifications, other sessions or meta",
          lines == [f"[вставлено {len(SECRET)} симв.]", "[вставлено 11 симв.] запит після вставки",
                    f"текст до вставки [вставлено {len(MIDDLE)} симв.] текст після вставки", "запит у черзі",
                    "старий запит у черзі", "запит у черзі після нагадування", "[картинка]", "[картинок: 2]",
                    "задача: Задача з черги", "повтор запису", "р" * PROMPT_WIDTH, "запит зі скриншотом",
                    "запит у черзі зі скриншотом", f"[вставлено 13 симв.] і [вставлено {len(SECRET2)} симв.]"],
          r.stdout + r.stderr[-300:])
    check("... and no pasted text", all(s not in r.stdout for s in (SECRET, SECRET2, "середина")), r.stdout)
    check("... and no warning: every form is known", unwarned(r.stderr), r.stderr[-300:])
    r = run(home, "--prompts", SID_H[:8])
    check("--prompts of a fork leaves out the copies", [line[18:] for line in r.stdout.splitlines()] == [
        "власний запит форку"], r.stdout + r.stderr[-300:])
    r = run(home, "--by", "session", "--home", reg)
    counts = {line[:8]: line[36:43].strip() for line in r.stdout.splitlines()}
    check("--by session counts 14 prompts in G and 1 in H", counts.get(SID_G[:8]) == "14"
          and counts.get(SID_H[:8]) == "1", r.stdout)
    check("a scan of known forms warns of nothing", unwarned(r.stderr), r.stderr[-300:])
    r = run(home, "--by", "task", "--home", reg)
    check("a queued «задача:» starts a task", task_hours(r.stdout, "Задача з черги") == "0.1", r.stdout)
    r = run(home, "--prompts", SID_E[:8])
    e_lines = r.stdout.splitlines()
    check("a prompt over 240 characters ends with «…» at 240", len(e_lines) == 60 and all(
        len(line) == 18 + PROMPT_WIDTH and line.endswith("х…") for line in e_lines), r.stdout[:600])


def checks_full(home, reg):
    """--pending --full writes nothing, prints the new prompts of A, B, C and D, and gives E (fewer characters than
    the limit, more bytes) and F after it as --prompts commands."""
    before = files_of(reg)
    r = run(home, "--pending", "--full", "--home", reg)
    out = r.stdout
    check("--pending --full exit 0", r.returncode == 0, r.stderr[-300:])
    check("--pending --full writes nothing", files_of(reg) == before)
    check("--full prints A's prompt after the boundary, not before", "після перерви" in out and "друга частина" not in out,
          out[:600])
    check("--full prints B, C and D", all(s in out for s in ("окрема сесія", "задача: Другий маркер C",
                                                               "запит після нагадування")), out[:900])
    blocks = {block.split("  ", 1)[0]: block for block in out.split("\n\n")[1:]}
    check("--full prints G's pasted labels and queued prompts, no pasted text", all(
        s in blocks.get(SID_G[:8], "") for s in ("[вставлено 11 симв.] запит після вставки", "запит у черзі",
                                                 "[картинка]")) and SECRET not in out and SECRET2 not in out,
          str(blocks.get(SID_G[:8])))
    h_block = blocks.get(SID_H[:8], "")
    check("--full prints H's own prompt without the copies", "власний запит форку" in h_block
          and "запит після вставки" not in h_block and "запит у черзі" not in h_block, h_block)
    table = r.stdout.split("\n\n")[0].splitlines()[2:]
    counted = {line[:8]: int(line[10:17]) for line in table}
    printed = {sid: len(run(home, "--prompts", sid, "--after", "2026-10-05 10:30").stdout.splitlines())
               for sid in counted}
    check("every session: --prompts --after prints as many prompts as the --pending table counts", printed == counted
          and len(counted) == 8, f"{counted} {printed}")
    e_cmd, f_cmd = (f"~/bin/claude-time --prompts {sid[:8]} --after '2026-10-05 10:30'" for sid in (SID_E, SID_F))
    check("--full gives E, then F, as commands", e_cmd in out and f_cmd in out and out.index(e_cmd) < out.index(f_cmd)
          and "довгий запит" not in out and "Маркер F" not in out, out[-400:])
    check("--full output stays within FULL_MAX_BYTES", len(out.encode()) <= FULL_MAX_BYTES, str(len(out.encode())))
    r = run(home, "--pending", "--home", reg)
    check("--pending without --full prints no prompt", "після перерви" not in r.stdout, r.stdout[:300])


def build_many(tmp, count):
    """A second HOME with `count` one-prompt sessions with long Cyrillic titles: their --pending table alone takes
    most of FULL_MAX_BYTES."""
    home = os.path.join(tmp, "many")
    cwd = "/Users/time-register-test/WebstormProjects/demo"
    for i in range(count):
        sid = f"{i:08x}-7777-4777-8777-777777777777"
        write_jsonl(os.path.join(home, ".claude", "projects", "-demo", sid + ".jsonl"), [
            {"type": "ai-title", "aiTitle": f"Сесія {i:03} " + "т" * 60, "sessionId": sid},
            user(sid, cwd, 1, (9 + i // 60, i % 60), f"запит сесії {i:03}"),
            assistant(sid, cwd, 1, (9 + i // 60, i % 60, 30))])
    return home


def checks_many(tmp):
    """--pending --full when the table with all the --prompts commands would not fit: one line with the pattern."""
    home, many_reg = build_many(tmp, 120), os.path.join(tmp, "many-reg")
    run(home, "--split-done", "2026-10-05 08:00", "--home", many_reg)
    r = run(home, "--pending", "--full", "--home", many_reg)
    out = r.stdout
    check("120 sessions: --pending --full exit 0", r.returncode == 0, r.stderr[-300:])
    check("120 sessions: one line with the command pattern, no prompts", out.count("--prompts") == 1
          and "для кожної сесії з таблиці окремий виклик ~/bin/claude-time --prompts <сесія> --after '2026-10-05 08:00'"
          in out and "запит сесії" not in out, out[-400:])
    check("120 sessions: within FULL_MAX_BYTES", len(out.encode()) <= FULL_MAX_BYTES, str(len(out.encode())))


def checks_dup(tmp):
    """A session id with two transcripts (the app moved it to another project folder and goes on there, the older copy
    stays): the scan reads the newer one by mtime, though by path it comes first, and --full and --prompts print its
    prompts, as many as --pending counts; an older copy that is not the start of the newer one gives an увага: line."""
    home, sid = os.path.join(tmp, "dup"), "99999999-8888-4888-8888-888888888888"
    cwd = "/Users/time-register-test/WebstormProjects/demo"
    first = [{"type": "ai-title", "aiTitle": "Сесія з двома транскриптами", "sessionId": sid},
             user(sid, cwd, 1, (9, 0), "запит з двох транскриптів"), assistant(sid, cwd, 1, (9, 10))]
    left, moved = (os.path.join(home, ".claude", "projects", folder, sid + ".jsonl") for folder in ("-z-left", "-a-moved"))
    write_jsonl(left, first)
    write_jsonl(moved, first + [user(sid, cwd, 2, (9, 20), "запит після переїзду"), assistant(sid, cwd, 2, (9, 30))])
    day_ago = datetime.now(timezone.utc).timestamp() - 86400
    os.utime(left, (day_ago, day_ago))
    r = run(home, "--pending", "--full", "--home", os.path.join(tmp, "dup-reg"))
    check("two transcripts of one id: --full prints the prompts of the one the scan reads", r.returncode == 0
          and "Нових запитів: 2" in r.stdout and "запит після переїзду" in r.stdout and "--prompts" not in r.stdout,
          r.stdout + r.stderr[-300:])
    r = run(home, "--prompts", sid[:8])
    check("... and so does --prompts", r.returncode == 0 and [line[18:] for line in r.stdout.splitlines()] == [
        "запит з двох транскриптів", "запит після переїзду"], r.stdout + r.stderr[-300:])
    r = run(home, "--pending", "--home", os.path.join(tmp, "dup-reg"))
    check("... with a line naming it, no увага: while the older copy is the start of the newer one", "сесій з "
          "транскриптом у двох теках: 1 (99999999), читається новіший" in r.stderr and unwarned(r.stderr),
          r.stderr[-300:])
    write_jsonl(left, first + [user(sid, cwd, 3, (9, 40), "запит лише в старій копії")])
    os.utime(left, (day_ago, day_ago))
    r = run(home, "--pending", "--home", os.path.join(tmp, "dup-reg"))
    check("an older copy that is not the start of the newer one gives an увага: line", r.returncode == 0
          and "увага: старіша копія транскрипту не є початком новішої, її записів не враховано: 99999999" in r.stderr,
          r.stderr[-300:])


def checks_stored_original(tmp):
    """A fork whose original transcript is gone: its copies belong to the original kept in register.json, so --prompts
    with that register leaves them out as --pending counts; with no register the original is unknown, they stay."""
    orig, fork = "12121212-9999-4999-8999-999999999999", "34343434-9999-4999-8999-999999999999"
    cwd = "/Users/time-register-test/WebstormProjects/demo"
    first = user(orig, cwd, 1, (9, 0), "запит оригіналу")
    with_orig, fork_only = os.path.join(tmp, "with-orig"), os.path.join(tmp, "fork-only")
    write_jsonl(os.path.join(with_orig, ".claude", "projects", "-demo", orig + ".jsonl"),
                [first, assistant(orig, cwd, 1, (9, 10))])
    for home in (with_orig, fork_only):
        write_jsonl(os.path.join(home, ".claude", "projects", "-demo", fork + ".jsonl"),
                    [first, user(fork, cwd, 1, (9, 20), "запит форку"), assistant(fork, cwd, 1, (9, 30))])
    reg = os.path.join(tmp, "orig-reg")
    r = run(with_orig, "--write", "--home", reg)
    check("the original goes into register.json", r.returncode == 0, r.stderr[-300:])
    r = run(fork_only, "--prompts", fork[:8], "--home", reg)
    check("--prompts leaves out copies of an original kept only in register.json", [
        line[18:] for line in r.stdout.splitlines()] == ["запит форку"], r.stdout + r.stderr[-300:])
    r = run(fork_only, "--pending", "--full", "--home", reg)
    check("... as --pending counts and --full prints", "Нових запитів: 1" in r.stdout and "запит форку" in r.stdout
          and "запит оригіналу" not in r.stdout, r.stdout[-400:])
    r = run(fork_only, "--prompts", fork[:8], "--home", os.path.join(tmp, "no-reg"))
    check("... and keeps them with no register", [line[18:] for line in r.stdout.splitlines()] == [
        "запит оригіналу", "запит форку"], r.stdout + r.stderr[-300:])
    broken = os.path.join(tmp, "broken-reg")
    os.makedirs(broken)
    with open(os.path.join(broken, "register.json"), "w", encoding="utf-8") as f:
        f.write("{")
    r = run(fork_only, "--prompts", fork[:8], "--home", broken)
    check("a broken register.json stops --prompts and names the file", r.returncode == 1 and not r.stdout
          and "register.json" in r.stderr, r.stdout + r.stderr[-300:])
    # a copy of a record that stops a write is the original's: --split-done reads the register as --write does
    copy = dict(user(orig, cwd, 2, (9, 1), ""), message="копія рядком")
    for home in (with_orig, fork_only):
        write_jsonl(os.path.join(home, ".claude", "projects", "-demo", fork + ".jsonl"),
                    [first, copy, user(fork, cwd, 1, (9, 20), "запит форку"), assistant(fork, cwd, 1, (9, 30))])
    r = run(fork_only, "--split-done", "2026-10-05 09:30", "--home", reg)
    r2 = run(fork_only, "--write", "--home", reg)
    forks = "форки: 2 скопійованих записів віддано оригінальним сесіям"
    check("a fork's copy of a record that stops a write stops no --split-done or --write with the original stored",
          r.returncode == 0 and r2.returncode == 0 and unwarned(r.stderr + r2.stderr)
          and forks in r.stderr.splitlines() and forks in r2.stderr.splitlines(),
          r.stderr[-300:] + r2.stderr[-300:])
    write_jsonl(os.path.join(with_orig, ".claude", "projects", "-demo", orig + ".jsonl"),
                [first, copy, assistant(orig, cwd, 1, (9, 10))])
    r = run(with_orig, "--write", "--home", os.path.join(tmp, "orig-reg-live"))
    check("... with the original live it stops --write, warned of once, the line naming the original alone",
          r.returncode == 1 and r.stderr.count("записів незнайомої форми 1 (message не об'єкт 1)") == 1 and any(
              x.startswith("увага: реєстр не записано") and x.endswith(f"сесії: {orig[:8]}") for x in r.stderr.splitlines()),
          r.stderr[-500:])


def checks_drift(tmp):
    """Forms the scan does not know (a new origin kind of a queued or a typed message, a new commandMode, a pasted block
    without its closing tag, text that starts with a tag not of Claude Code, a long one too, or with "<" and no tag, a
    queued record whose origin sits on its entry, in any mode (with a new mode too: the mode names it), a prompt of a
    plugin): one warning with their number, kinds, names and counts, the text that starts with "<" in a "примітка:"
    line of its own; only the pasted prompt counts, as a label, and none of them stops --write (an origin that is no
    object does: checks_forms_lossy). Claude Code's own tags at the start and the other origin kinds of its binary are
    neither counted nor warned of."""
    home, sid = os.path.join(tmp, "drift"), "56565656-9999-4999-8999-999999999999"
    cwd = "/Users/time-register-test/WebstormProjects/demo"
    write_jsonl(os.path.join(home, ".claude", "projects", "-demo", sid + ".jsonl"), [
        user(sid, cwd, 1, (9, 0), '<pasted_content id="zz11">незакрита вставка'),
        queued(sid, cwd, 2, (9, 1), "запит з новим origin", origin={"kind": "keyboard"}),
        queued(sid, cwd, 3, (9, 2), "запит з новим режимом", mode="newmode", origin=HUMAN),
        dict(user(sid, cwd, 4, (9, 3), "повідомлення з новим origin"), origin={"kind": "radio"}),
        queued(sid, cwd, 5, (9, 3, 30), "повідомлення каналу", origin={"kind": "channel"}, meta=True),
        queued(sid, cwd, 6, (9, 3, 40), "ls -la", mode="bash", origin=HUMAN),
        queued(sid, cwd, 7, (9, 3, 50), "Give the user a brief summary", origin={"kind": "auto-continuation"}),
        user(sid, cwd, 8, (9, 4), "звичайний запит"),
        user(sid, cwd, 9, (9, 5), "<div> не центрується"),
        queued(sid, cwd, 10, (9, 5, 10), "<Button> не тиснеться", origin=HUMAN),
        user(sid, cwd, 11, (9, 5, 20), "<terminal-selection>$ ls</terminal-selection> поясни"),
        user(sid, cwd, 12, (9, 5, 30), REMINDER + "\n<3 дякую"),
        dict(queued(sid, cwd, 13, (9, 5, 40), "запит з origin у записі"), origin=HUMAN),
        user(sid, cwd, 14, (9, 6), "<local-command-stdout>Set model to opus</local-command-stdout>"),
        user(sid, cwd, 15, (9, 6, 10), "<command-message>foo</command-message>\n<command-name>/foo</command-name>"),
        user(sid, cwd, 16, (9, 6, 20), "<side-sessions-event>Side sessions finished.</side-sessions-event>"),
        user(sid, cwd, 17, (9, 6, 30), REMINDER + '\n<cross-session-message from="x">звіт</cross-session-message>'),
        user(sid, cwd, 18, (9, 6, 40), '<scheduled-task name="weekly">Онови реєстр</scheduled-task>'),
        user(sid, cwd, 19, (9, 6, 50), "<bash-input>git status</bash-input>"),
        queued(sid, cwd, 20, (9, 7), "звіт спостерігача", origin={"kind": "observer"}),
        dict(user(sid, cwd, 21, (9, 7, 10), "повідомлення координатора"), origin={"kind": "coordinator"}),
        queued(sid, cwd, 22, (9, 7, 20), "огляд активності", origin={"kind": "observer-activity"}),
        queued(sid, cwd, 23, (9, 7, 30), "згадка в Slack", origin={"kind": "slack-ping"}),
        queued(sid, cwd, 24, (9, 7, 40), "запит від плагіна", origin={"kind": "plugin", "name": "x", "asUser": True}),
        dict(queued(sid, cwd, 25, (9, 7, 50), "git log", mode="bash"), origin=HUMAN),
        user(sid, cwd, 26, (9, 8), "<" + "Дуже" * 10 + "> довгий тег"),
        dict(queued(sid, cwd, 27, (9, 8, 10), "новий режим і origin у записі", mode="othermode"), origin=HUMAN),
        assistant(sid, cwd, 1, (9, 10))])
    warning = ("увага: записів незнайомої форми 8 (невідомий origin: keyboard 1, plugin 1, radio 1; "
               "невідомий commandMode: newmode 1, othermode 1; origin у записі черги: human 2; вставка без "
               "закривального тегу 1): можливо, змінився формат транскриптів, і частину запитів не враховано")
    note = ("примітка: записів з «<» на початку 5 (тег на початку: Button 1, div 1, terminal-selection 1, "
            + ("Дуже" * 8)[:29] + "… 1; «<» без тегу 1): запитами не враховано; зазвичай це набраний текст, а тег, "
            "якого ніхто не набирав, означає зміну формату транскриптів")
    r = run(home, "--by", "session", "--home", os.path.join(tmp, "drift-reg"))
    line = next((x for x in r.stdout.splitlines() if x.startswith(sid[:8])), "")
    check("unknown forms: the scan counts the pasted and the typed prompt", line[36:43].strip() == "2", r.stdout)
    check("... the title is the typed prompt, not the label", line.endswith("звичайний запит"), line)
    check("... and warns once with their number, kinds, names (cut to 30 characters) and counts, text with «<» in a "
          "примітка line of its own", r.stderr.count("увага: записів незнайомої форми") == 1
          and r.stderr.count("примітка:") == 1 and {warning, note} <= set(r.stderr.splitlines()), r.stderr[-900:])
    r = run(home, "--prompts", sid[:8])
    check("--prompts prints the pasted rest as a label and warns too", [x[18:] for x in r.stdout.splitlines()] == [
        "[вставлено 17 симв.]", "звичайний запит"] and {warning, note} <= set(r.stderr.splitlines()),
          r.stdout + r.stderr[-900:])
    r = run(home, "--write", "--home", os.path.join(tmp, "drift-reg"))
    check("... and these forms stop no --write", r.returncode == 0 and {warning, note} <= set(r.stderr.splitlines())
          and os.path.exists(os.path.join(tmp, "drift-reg", "register.json")), r.stderr[-900:])


def checks_message(tmp):
    """A user record whose message is no object (a string, a list, a number) or that has none: --by session and
    --prompts run, it is no prompt and is warned of as its own kind, once even with an unknown origin, the prompts
    around it count; --write and --add (alone or together) write nothing and say so, the register stays as it was. A
    meta, sidechain or compact summary record, an assistant record and the records of a subagent whose message is no
    object fail nothing, are not warned of and stop no --write."""
    home, sid = os.path.join(tmp, "message"), "57575757-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    cwd = "/Users/time-register-test/WebstormProjects/demo"
    sessions = os.path.join(home, ".claude", "projects", "-demo")
    no_message = user(sid, cwd, 5, (9, 4), "")
    del no_message["message"]
    known = [
        user(sid, cwd, 1, (9, 0), "запит до"),
        dict(assistant(sid, cwd, 1, (9, 5)), message="відповідь рядком"),
        *(dict(user(sid, cwd, n, (9, 5, n), ""), message="службовий рядком", **{flag: True})
          for n, flag in ((8, "isMeta"), (9, "isSidechain"), (10, "isCompactSummary"))),
        user(sid, cwd, 6, (9, 6), "запит після"),
        assistant(sid, cwd, 2, (9, 10))]
    unknown = [
        dict(user(sid, cwd, 2, (9, 1), ""), message="message рядком"),
        dict(user(sid, cwd, 3, (9, 2), ""), message=["message списком"], origin={"kind": "martian"}),
        dict(user(sid, cwd, 4, (9, 3), ""), message=7),
        no_message]
    write_jsonl(os.path.join(sessions, sid, "subagents", "agent-m.jsonl"), [
        dict(user(sid, cwd, 7, (9, 7), ""), message="субагент рядком"),
        dict(assistant(sid, cwd, 3, (9, 8)), message=["субагент списком"])])
    write_jsonl(os.path.join(sessions, sid + ".jsonl"), known)
    reg = os.path.join(tmp, "message-reg")
    r = run(home, "--write", "--home", reg)
    check("message no object: an assistant, a meta, sidechain or summary and a subagent's record stop no --write",
          r.returncode == 0 and unwarned(r.stderr) and os.path.exists(os.path.join(reg, "register.json")),
          r.stderr[-500:])
    before = files_of(reg)
    write_jsonl(os.path.join(sessions, sid + ".jsonl"), sorted(known + unknown, key=lambda rec: rec["timestamp"]))
    warning = ("увага: записів незнайомої форми 4 (message не об'єкт 4): можливо, змінився формат транскриптів, і "
               "частину запитів не враховано")
    r = run(home, "--by", "session", "--home", reg)
    line = next((x for x in r.stdout.splitlines() if x.startswith(sid[:8])), "")
    check("message no object: --by session runs and counts the 2 prompts around it",
          r.returncode == 0 and line[36:43].strip() == "2", r.stdout + r.stderr[-500:])
    check("... and warns once of the 4 user records as their own kind",
          r.stderr.count("увага: записів незнайомої форми") == 1 and warning in r.stderr.splitlines()
          and "примітка" not in r.stderr, r.stderr[-500:])
    r = run(home, "--prompts", sid[:8])
    check("... --prompts prints them and warns too", r.returncode == 0 and [x[18:] for x in r.stdout.splitlines()] == [
        "запит до", "запит після"] and warning in r.stderr.splitlines(), r.stdout + r.stderr[-500:])
    r = run(home, "--pending", "--full", "--home", reg)
    check("... --pending --full runs and warns too", r.returncode == 0 and warning in r.stderr.splitlines(),
          r.stderr[-500:])
    stop = ("увага: реєстр не записано: через записи «message не об'єкт» їхні сесії втратили б запити й маркери "
            f"«задача:»; --split-done теж не запускай, доки базу не оновлено; сесії: {sid[:8]}")
    add = ("--add", sid[:8], "", "Задача тесту", "bug", "примітка")
    for args in (("--write",), add, (*add, "--write")):
        r = run(home, *args, "--home", reg)
        check(f"... {' '.join(args[:1] + args[6:])} writes nothing and says so", r.returncode == 1
              and {warning, stop} <= set(r.stderr.splitlines()) and "the register was not written" in r.stderr
              and files_of(reg) == before, r.stderr[-500:])


def checks_forms_counted(tmp):
    """Forms that are warned of but stop nothing: an entry whose uuid (a user's or a model's) or sessionId is not text
    (a list, an object, a number) still counts, a prompt as one of its own session; a would-be prompt whose blocks give
    no text, image or tool result (a text that is no text, a type the rule does not know, a text block without text, a
    document only, also beside a blank text or a reminder only; a queued one too) is no prompt, one with text beside a
    document counts, an empty text block alone is no prompt and not warned of. A model answer whose id, model or output
    count has another form (a string, true, NaN), a subagent's too, and a subagent's attachment that is no object fail
    nothing and are not warned of here (claude-metrics warns of them); an output count of another form keeps the count
    of a streamed line of the same answer before it. Content of another form in records that are no prompt (a message of
    another session, a meta one, a queued notification or meta prompt), such blocks in a meta record or a message of
    another session, an empty text and an empty list are not warned of; a JSON line that is no object or has an integer
    over Python's digit limit counts as a broken one. --write and --split-done run, --split-done printing the lines of
    the scan too."""
    home, sid = os.path.join(tmp, "forms"), "58585858-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    cwd = "/Users/time-register-test/WebstormProjects/demo"
    sessions = os.path.join(home, ".claude", "projects", "-demo")
    odd = {"id": ["x"], "model": ["m"], "usage": {"output_tokens": 5}, "content": []}

    def streamed(n, mid, out):  # a line of a streamed answer: Claude Code repeats its id with the usage so far
        return dict(assistant(sid, cwd, n, (9, 31, n)), message={"id": mid, "model": "claude-test",
                                                                  "usage": {"output_tokens": out}, "content": []})

    write_jsonl(os.path.join(sessions, sid + ".jsonl"), [
        user(sid, cwd, 1, (9, 0), "запит до"),
        dict(user(sid, cwd, 2, (9, 1), "запит з uuid списком"), uuid=["x"]),
        dict(user(sid, cwd, 3, (9, 2), "запит з uuid об'єктом"), uuid={"x": 1}),
        dict(user(sid, cwd, 4, (9, 3), "запит з uuid числом"), uuid=7),
        dict(user(sid, cwd, 5, (9, 4), "запит з sessionId списком"), sessionId=["x"]),
        dict(user(sid, cwd, 6, (9, 5), "запит з sessionId об'єктом"), sessionId={"x": 1}),
        dict(assistant(sid, cwd, 1, (9, 6)), uuid=["y"]),
        dict(assistant(sid, cwd, 2, (9, 7)), message=odd),
        dict(assistant(sid, cwd, 3, (9, 8)), message=dict(odd, id="msg-odd", model={"x": 1},
                                                           usage={"output_tokens": "1000"})),
        dict(user(sid, cwd, 7, (9, 9), 7), origin={"kind": "peer"}),
        dict(user(sid, cwd, 8, (9, 10), 7), isMeta=True),
        queued(sid, cwd, 9, (9, 11), 7, mode="task-notification"),
        queued(sid, cwd, 10, (9, 12), 7, origin=HUMAN, meta=True),
        user(sid, cwd, 11, (9, 13), ""),
        user(sid, cwd, 12, (9, 14), []),
        user(sid, cwd, 14, (9, 15), [{"type": "text", "text": {"value": "x"}}]),
        user(sid, cwd, 15, (9, 16), [{"type": "input_text", "text": "x"}]),
        user(sid, cwd, 16, (9, 17), [{"type": "text"}]),
        user(sid, cwd, 17, (9, 18), [{"type": "document", "source": {}}]),
        queued(sid, cwd, 18, (9, 19), [{"type": "document", "source": {}}], origin=HUMAN),
        user(sid, cwd, 19, (9, 19, 30), [{"type": "text", "text": "запит з документом"}, {"type": "document"}]),
        user(sid, cwd, 22, (9, 19, 35), [{"type": "text", "text": ""}, {"type": "document"}]),
        user(sid, cwd, 24, (9, 19, 36), [{"type": "text", "text": " "}, {"type": "document"}]),
        user(sid, cwd, 25, (9, 19, 38), [{"type": "text", "text": REMINDER}, {"type": "document"}]),
        user(sid, cwd, 23, (9, 19, 37), [{"type": "text", "text": " "}]),
        dict(user(sid, cwd, 20, (9, 19, 40), [{"type": "document"}]), isMeta=True),
        dict(user(sid, cwd, 21, (9, 19, 50), [{"type": "input_text", "text": "x"}]), origin={"kind": "peer"}),
        user(sid, cwd, 13, (9, 20), "запит після"),
        assistant(sid, cwd, 4, (9, 30)),
        *(streamed(n, f"msg-stream-{n // 2}", out)
          for n, out in ((10, 1000), (11, "x"), (12, 1000), (13, True), (14, 1000), (15, float("nan"))))])
    with open(os.path.join(sessions, sid + ".jsonl"), "a", encoding="utf-8") as f:
        f.write('[1, 2]\n"рядок"\n7\nnull\n{"n": ' + "1" * 5000 + '}\n')  # the last: over Python's digit limit
    write_jsonl(os.path.join(sessions, sid, "subagents", "agent-f.jsonl"), [
        {"type": "attachment", "sessionId": sid, "uuid": f"{sid}-s1", "cwd": cwd, "timestamp": stamp(9, 15),
         "attachment": "рядок"},
        dict(assistant(sid, cwd, 9, (9, 16)), message=dict(odd, usage={"output_tokens": "x"}))])
    warning = ("увага: записів незнайомої форми 14 (блоки без тексту 8; uuid не рядок 4; sessionId не рядок 2): можливо, "
               "змінився формат транскриптів, і частину запитів не враховано")
    broken = "увага: битих рядків 5, нечитаних файлів 0 з 2, нерозібраних timestamp 0"
    reg = os.path.join(tmp, "forms-reg")
    r = run(home, "--by", "session", "--home", reg)
    line = next((x for x in r.stdout.splitlines() if x.startswith(sid[:8])), "")
    check("forms counted: --by session runs and counts the 8 prompts, also those whose uuid or sessionId is not text",
          r.returncode == 0 and line[36:43].strip() == "8", r.stdout + r.stderr[-500:])
    check("... warns once of them by kind, of no other form",
          r.stderr.count("увага: записів незнайомої форми") == 1 and warning in r.stderr.splitlines()
          and "примітка" not in r.stderr, r.stderr[-500:])
    check("... and counts the JSON lines that are no object as broken", broken in r.stderr.splitlines(), r.stderr[-500:])
    r = run(home, "--prompts", sid[:8])
    check("... --prompts prints the 8 and warns too", r.returncode == 0 and [x[18:] for x in r.stdout.splitlines()] == [
        "запит до", "запит з uuid списком", "запит з uuid об'єктом", "запит з uuid числом", "запит з sessionId списком",
        "запит з sessionId об'єктом", "запит з документом", "запит після"] and warning in r.stderr.splitlines(),
          r.stdout + r.stderr[-500:])
    r = run(home, "--write", "--home", reg)
    stored = {}
    if r.returncode == 0:
        with open(os.path.join(reg, "register.json"), encoding="utf-8") as f:
            stored = json.load(f)["sessions"].get(sid, {})
    got = (r.returncode, stored.get("prompts"), stored.get("out_ktok"), stored.get("model"))
    check("... --write runs: 8 prompts, the output (streamed lines kept) and model of the answers of known forms only",
          got == (0, 8, 5, "claude-test"), f"{got} {r.stderr[-500:]}")
    r = run(home, "--split-done", "2026-10-05 09:30", "--home", reg)
    check("... and --split-done runs and prints the lines of the scan as --write does", r.returncode == 0
          and split_until(reg) == "2026-10-05 09:30\n" and {broken, warning} <= set(r.stderr.splitlines()),
          r.stderr[-500:])


def checks_forms_lossy(tmp):
    """Forms that stop a write: an attachment record whose attachment is no object (a string, a list, a number, null
    or none), content of a would-be prompt that is neither text nor a list of objects (an empty message, none, null, a
    number, one block as an object, a list of strings; a queued prompt too) and a message whose origin is no object
    (in a session of its own, with a queued record whose origin on its entry is no object) are no prompt and are
    warned of, with a user message that is no object. --by session,
    --prompts and --pending --full run; --write, --add (with --write too) and --split-done (back too) write nothing and
    say so, naming the forms and the first 5 of their sessions by id (not a session whose only unknown form stops
    nothing), the rest as інші N."""
    home, cwd = os.path.join(tmp, "lossy"), "/Users/time-register-test/WebstormProjects/demo"
    sessions = os.path.join(home, ".claude", "projects", "-demo")
    sids = [f"6{n}6{n}6{n}6{n}-cccc-4ccc-8ccc-cccccccccccc" for n in range(1, 10)]  # 61616161 ... 69696969
    first = sids[0]

    def att(n, hhmm, *value):  # no value: a record without an attachment
        return {"type": "attachment", "sessionId": first, "uuid": f"{first}-t{n}", "cwd": cwd, "timestamp": stamp(*hhmm),
                **({"attachment": value[0]} if value else {})}

    def message(sid, n, hhmm, value):
        return dict(user(sid, cwd, n, hhmm, ""), message=value)

    known = {sid: [user(sid, cwd, 1, (9, 0), f"запит {sid[:2]}"), user(sid, cwd, 20, (9, 20), "запит після"),
                   assistant(sid, cwd, 1, (9, 30))] for sid in sids}
    lossy = {first: [att(1, (9, 1), "рядок"), att(2, (9, 2), ["x"]), att(3, (9, 3), 7), att(4, (9, 4), None),
                     att(5, (9, 5)), message(first, 2, (9, 6), {}), message(first, 3, (9, 7), {"role": "user"}),
                     user(first, cwd, 4, (9, 8), None), user(first, cwd, 5, (9, 9), 7),
                     user(first, cwd, 6, (9, 10), {"type": "text", "text": "блок"}),
                     user(first, cwd, 7, (9, 11), ["рядок"]), queued(first, cwd, 8, (9, 12), 7, origin=HUMAN),
                     queued(first, cwd, 9, (9, 13), {"type": "text", "text": "x"}, origin=HUMAN)],
             sids[1]: [message(sids[1], 2, (9, 1), "рядком")],
             sids[7]: [dict(user(sids[7], cwd, 2, (9, 1), "запит з uuid списком"), uuid=["x"])],
             sids[8]: [dict(user(sids[8], cwd, 2, (9, 1), "запит з origin рядком"), origin="human"),
                       dict(queued(sids[8], cwd, 3, (9, 2), "задача: Нова задача"), origin="human")],
             **{sid: [message(sid, 2, (9, 1), {})] for sid in sids[2:7]}}
    for sid in sids:
        write_jsonl(os.path.join(sessions, sid + ".jsonl"), known[sid])
    reg = os.path.join(tmp, "lossy-reg")
    r = run(home, "--write", "--home", reg)
    r2 = run(home, "--split-done", "2026-10-05 08:00", "--home", reg)
    check("lossy forms: the register of the known forms is written", r.returncode == 0 and r2.returncode == 0,
          r.stderr[-300:] + r2.stderr[-300:])
    before = files_of(reg)
    for sid in sids:
        write_jsonl(os.path.join(sessions, sid + ".jsonl"), sorted(known[sid] + lossy[sid], key=lambda x: x["timestamp"]))
    warning = ("увага: записів незнайомої форми 22 (невідомий origin: не об'єкт 1; origin у записі черги: не об'єкт 1; "
               "message не об'єкт 1; attachment не об'єкт 5; content незнайомої форми 13; uuid не рядок 1): можливо, "
               "змінився формат транскриптів, і частину запитів не враховано")
    r = run(home, "--by", "session", "--home", reg)
    line = next((x for x in r.stdout.splitlines() if x.startswith(first[:8])), "")
    check("lossy forms: --by session runs and counts the 2 prompts around them", r.returncode == 0
          and line[36:43].strip() == "2", r.stdout + r.stderr[-500:])
    check("... and warns once of them by kind", r.stderr.count("увага: записів незнайомої форми") == 1
          and warning in r.stderr.splitlines() and "примітка" not in r.stderr, r.stderr[-500:])
    r = run(home, "--prompts", first[:8])
    check("... --prompts prints the 2 and warns of the forms of that session", r.returncode == 0
          and [x[18:] for x in r.stdout.splitlines()] == ["запит 61", "запит після"] and (
              "увага: записів незнайомої форми 13 (attachment не об'єкт 5; content незнайомої форми 8): можливо, "
              "змінився формат транскриптів, і частину запитів не враховано") in r.stderr.splitlines(),
          r.stdout + r.stderr[-500:])
    r = run(home, "--pending", "--full", "--home", reg)
    check("... --pending --full runs and warns too", r.returncode == 0 and warning in r.stderr.splitlines(),
          r.stderr[-500:])
    stop = ("увага: реєстр не записано: через записи «невідомий origin: не об'єкт», «origin у записі черги: не об'єкт», "
            "«message не об'єкт», «attachment не об'єкт», «content незнайомої форми» їхні сесії втратили б запити й "
            "маркери «задача:»; --split-done теж не запускай, доки базу не оновлено; сесії: 61616161, 62626262, "
            "63636363, 64646464, 65656565, інші 3")
    add = ("--add", first[:8], "", "Задача тесту", "bug", "примітка")
    for args, said in ((("--write",), "the register was not written"), (add, "the register was not written"),
                       ((*add, "--write"), "the register was not written"),
                       (("--split-done", "2026-10-05 09:30"), "split-until.txt not changed"),
                       (("--split-done", "2026-10-05 07:00", "--allow-back"), "split-until.txt not changed")):
        r = run(home, *args, "--home", reg)
        check(f"... {' '.join(x for x in args if x.startswith('--'))} writes nothing and says so, naming forms and "
              "sessions",
              r.returncode == 1 and {warning, stop} <= set(r.stderr.splitlines()) and said in r.stderr
              and files_of(reg) == before, r.stderr[-700:])


def checks_blind(tmp):
    """Transcripts of which no session can be read (broken lines only, a record whose timestamp does not parse, a file
    that cannot be opened): --write and --split-done stop, print the lines of the scan and write nothing; one file that
    cannot be opened beside a read one and no transcripts at all stop neither."""
    sid = "71717171-dddd-4ddd-8ddd-dddddddddddd"
    bad_ts = {"type": "system", "subtype": "x", "sessionId": sid, "uuid": "b1", "timestamp": "вчора"}
    stats_line = "увага: битих рядків {}, нечитаних файлів {} з 1, нерозібраних timestamp {}"
    for name, text, scan_line in (("blind", '[1, 2]\n{"broken\n', stats_line.format(2, 0, 0)),
                                  ("blind-ts", json.dumps(bad_ts) + "\n", stats_line.format(0, 0, 1)),
                                  ("blind-closed", "", stats_line.format(0, 1, 0))):
        home, reg = os.path.join(tmp, name), os.path.join(tmp, name + "-reg")
        path = os.path.join(home, ".claude", "projects", "-demo", sid + ".jsonl")
        os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        if not text:  # a file that cannot be opened
            os.chmod(path, 0)
        lines = {scan_line, "увага: транскрипти є, але жодної сесії не прочитано (змінився формат?)"}
        for args, said in ((("--write",), "the register was not written"),
                           (("--split-done", "2026-10-05 09:30"), "split-until.txt not changed")):
            r = run(home, *args, "--home", reg)
            check(f"no session read ({name}): {args[0]} stops, prints the lines of the scan and writes nothing",
                  r.returncode == 1 and lines <= set(r.stderr.splitlines()) and said in r.stderr
                  and not os.path.exists(reg), r.stderr[-500:])
    home, reg = os.path.join(tmp, "partly-closed"), os.path.join(tmp, "partly-closed-reg")
    cwd = "/Users/time-register-test/WebstormProjects/demo"
    write_jsonl(os.path.join(home, ".claude", "projects", "-demo", sid + ".jsonl"),
                [user(sid, cwd, 1, (9, 0), "запит"), assistant(sid, cwd, 1, (9, 10))])
    closed = os.path.join(home, ".claude", "projects", "-demo", "72727272-dddd-4ddd-8ddd-dddddddddddd.jsonl")
    write_jsonl(closed, [user(sid, cwd, 2, (9, 20), "запит у файлі, що не відкривається")])
    os.chmod(closed, 0)
    for args in (("--write",), ("--split-done", "2026-10-05 09:30")):
        r = run(home, *args, "--home", reg)
        check(f"one file that cannot be opened beside a read one: {args[0]} runs and warns of it", r.returncode == 0
              and "увага: битих рядків 0, нечитаних файлів 1 з 2, нерозібраних timestamp 0" in r.stderr.splitlines()
              and "жодної сесії" not in r.stderr, r.stderr[-500:])
    home, reg = os.path.join(tmp, "no-transcripts"), os.path.join(tmp, "no-transcripts-reg")
    os.makedirs(os.path.join(home, ".claude", "projects"))
    for args in (("--write",), ("--split-done", "2026-10-05 09:30")):
        r = run(home, *args, "--home", reg)
        check(f"no transcripts: {args[0]} runs, without the line of no session read", r.returncode == 0
              and "жодної сесії" not in r.stderr, r.stderr[-500:])


def checks_unknown_line():
    """The warning lines on their own (unknown_warning): none without records; the forms of a format change in the
    "увага:" line, text that starts with "<" (a tag, "<" without one) in the "примітка:" line after it, either line
    alone when only its forms are there; a name is cut to FORM_NAME_WIDTH characters with "…", a character no tag
    name has becomes "?", a missing or empty value or one that is not text is "без назви", an origin that is no object
    "не об'єкт"; tags show FORM_NAMES_MAX names at most, the most frequent first (also one later by name), then by
    name, the records of the other names as "інші N" with where all are listed; origin kinds are all shown; a named
    kind noted without a name still adds up; a kind that UNKNOWN_KINDS lacks comes last by its id; the number of a
    line is the sum of its kinds."""
    if not hasattr(transcript, "unknown_warning"):  # a tree without it fails this check instead of the whole test
        check("unknown line: time_register.transcript has unknown_warning", False)
        return
    transcript.UNKNOWN.clear()
    check("unknown line: no records, no line", transcript.unknown_warning() == "")
    transcript.note_unknown("no_tag")
    transcript.note_unknown("tag", "div")
    check("unknown line: text with «<» alone gives the примітка line only, no увага", transcript.unknown_warning() == (
        "примітка: записів з «<» на початку 2 (тег на початку: div 1; «<» без тегу 1): запитами не враховано; "
        "зазвичай це набраний текст, а тег, якого ніхто не набирав, означає зміну формату транскриптів"),
          transcript.unknown_warning())
    transcript.UNKNOWN.clear()
    transcript.note_unknown("origin", "plugin")
    check("unknown line: a format change alone gives the увага line only", transcript.unknown_warning() == (
        "увага: записів незнайомої форми 1 (невідомий origin: plugin 1): можливо, змінився формат транскриптів, і "
        "частину запитів не враховано"), transcript.unknown_warning())
    transcript.UNKNOWN.clear()
    check("unknown line: a name of 30 characters stays, one of 31 is cut to 30",
          (transcript.form_name("x" * 30), transcript.form_name("x" * 31)) == ("x" * 30, "x" * 29 + "…"))
    check("unknown line: other characters become ?, no value is без назви", [transcript.form_name(v) for v in (
        "new kind\n", None, "", 7, {"kind": "x"})] == ["new?kind?", "без назви", "без назви", "без назви", "без назви"])
    check("unknown line: an origin's name is its kind, без назви without one, не об'єкт for no object",
          [transcript.origin_name(o) for o in ({"kind": "plugin"}, {}, "human")] == ["plugin", "без назви", "не об'єкт"])
    for name, times in (("f", 2), ("z", 4), ("d", 3), ("b", 3), ("e", 2), ("a", 3), ("c", 3)):  # not in their order
        for _ in range(times):
            transcript.note_unknown("tag", transcript.form_name(name))
    for name in ("o6", "o5", "o4", "o3", "o2", "o1"):
        transcript.note_unknown("origin", name)
    transcript.note_unknown("origin", transcript.origin_name("human"))
    for name in ("", "", "", "x"):
        transcript.note_unknown("mode", name)
    for kind in ("session_id", "uuid", "blocks", "content", "attachment", "message"):  # the last kinds, out of order
        transcript.note_unknown(kind)
    transcript.note_unknown("unclosed")
    transcript.note_unknown("future")
    transcript.note_unknown("no_tag")
    check("unknown line: kinds in order, 5 tag names at most and the rest as інші, all origins, an unlisted kind last; "
          "the tags and «<» without a tag in the примітка line after the увага one, each with its own number",
          transcript.unknown_warning() == (
              "увага: записів незнайомої форми 19 (невідомий origin: o1 1, o2 1, o3 1, o4 1, o5 1, o6 1, не об'єкт 1; "
              "невідомий commandMode: без назви 3, x 1; вставка без закривального тегу 1; message не об'єкт 1; "
              "attachment не об'єкт 1; content незнайомої форми 1; блоки без тексту 1; uuid не рядок 1; sessionId не "
              "рядок 1; future 1): можливо, змінився формат транскриптів, і частину запитів не враховано\n"
              "примітка: записів з «<» на початку 21 (тег на початку: z 4, a 3, b 3, c 3, d 3, інші 4, перелік у "
              "claude-metrics --json; «<» без тегу 1): запитами не враховано; зазвичай це набраний текст, а тег, якого "
              "ніхто не набирав, означає зміну формату транскриптів"), transcript.unknown_warning())
    transcript.note_unknown("queued_origin", "human")
    transcript.note_unknown("queued_origin", transcript.origin_name(7))
    check("unknown line: an origin that is no object (also a queued one), a message, an attachment and content stop a "
          "write; other origins, blocks, a uuid or sessionId do not", (
              getattr(transcript, "lossy_forms", lambda: None)(), getattr(transcript, "lossy_records", lambda: None)()
          ) == ([("origin", "не об'єкт"), ("queued_origin", "не об'єкт"), ("message", None), ("attachment", None),
                 ("content", None)], 5))
    transcript.UNKNOWN.clear()


def checks_budget():
    """blocks_that_fit: a block is shown only when it fits with the title and the commands of all the blocks after
    it; it stops at the first block that does not fit."""
    title = nbytes(REST_TITLE.format(1))
    check("budget: all blocks fit", blocks_that_fit(0, [10, 10], [5, 5], 100 + title) == 2)
    check("budget: a block that fits exactly with the title and the next command",
          blocks_that_fit(0, [10, 1000], [5, 5], 10 + title + 5) == 1)
    check("budget: one byte over shows nothing", blocks_that_fit(0, [10, 1000], [5, 5], 10 + title + 5 - 1) == 0)
    check("budget: the bytes already out count", blocks_that_fit(1, [10, 1000], [5, 5], 10 + title + 5) == 0)
    check("budget: stops at the first block that does not fit", blocks_that_fit(0, [10, 1000, 1], [5, 5, 5], 300) == 1)


def main():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="time-register-test.", dir="/private/tmp"))
    try:
        home = build_home(tmp)
        reg = os.path.join(tmp, "reg")
        checks_split(home, reg)
        checks_bare_header(home, tmp)
        checks_marker_replaced(home, reg)
        checks_boundary(home, reg)
        checks_reminders(home, reg)
        checks_new_prompts(home, reg)
        checks_full(home, reg)
        checks_many(tmp)
        checks_dup(tmp)
        checks_stored_original(tmp)
        checks_drift(tmp)
        checks_message(tmp)
        checks_forms_counted(tmp)
        checks_forms_lossy(tmp)
        checks_blind(tmp)
        checks_unknown_line()
        checks_budget()
        check("no __pycache__ written", not os.path.exists(os.path.join(ROOT, "tools", "time_register", "__pycache__")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for f in FAILS:
        print("FAIL " + f)
    print(f"time-register test: {CHECKS[0]} checks, {len(FAILS)} failed")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
