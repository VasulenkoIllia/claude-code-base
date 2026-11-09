#!/usr/bin/env -S python3 -I
"""Offline test of the split in chunks of claude-time: --add ... --stage and --split-done --rows --after
(tools/time-register.py, tools/time_register/staging.py).

Runs on the made-up transcripts of tests/time-register-test.py (its build_home and helpers, imported, not copied), with
HOME, --home and the Claude Code session (CLAUDE_CODE_SESSION_ID, CLAUDECODE) set per call, in a temp folder under
/private/tmp:
  chunks: --split-done with nothing staged moves the boundary only; --add --stage keeps the rows in this session's
     entry of add-staged.json (0600, with the boundary, task and note on one line; add-staged.lock 0600) and leaves
     tasks.csv and the boundary as they were; a row staged again counts once, a row of the same session and start
     replaces the staged one; a chunk with a bad row, two rows of a session in one minute (also when that start is
     staged already), a row without its start or not after the boundary stages nothing; --split-done without --rows,
     with another number or with an --after that is not the boundary writes nothing; with the number it writes all
     the rows (the "задача:" markers carried or replaced as --add does) and the boundary, says how many, and removes
     the entry; --restart drops the rows staged before;
  atomic: a staged row that starts after the new boundary, a time in the future or back, a staged row that clashes
     with a row added after the staging: neither the rows nor the boundary are written, the rows stay staged;
  sessions: --split-done of another session leaves this session's rows alone and moves the boundary, then this
     session's --split-done and --stage stop (another session split meanwhile), nothing written; a session that read
     the boundary before another one split and staged after it stops at --split-done --after; two sessions stage side
     by side and the one that commits writes its own rows only; inside Claude Code without a session id --stage and
     --split-done --rows stop, nothing written; outside Claude Code (no variables) it works; an entry not staged for
     STAGED_DAYS goes with the next write;
  parallel: chunks of one session sent at once all stay staged (the lock);
  retry: a --split-done cut short after its tasks.csv write, or after its boundary write, completes when run again,
     without a row twice; cut short between its two writes, the next run of another session finishes it and stops,
     but not one whose rows never reached tasks.csv;
  arguments: --stage without --add or with --write, --rows without --split-done, below 0 or without --after, --restart
     without --stage, --after with --pending stop; --prompts with --add --stage prints and stages nothing (the allow
     rule for --prompts relies on it); --prompts of an unknown id names the problem; an add-staged.json that is broken
     or of another form stops --split-done and --stage, nothing written;
  lossy forms: a record that stops a write stops --stage, and --split-done after a staging, nothing written;
  typed: text that starts with "<" after the boundary (a typed <div> and <3) gives its "примітка:" line and no
     "увага:" in --write, --pending --full, --stage and --split-done, and the split is written;
  length: a chunk of CHUNK rows of the longest task and note the skill allows is a command under CMD_MAX characters.
Run: python3 -I tests/time-register-stage-test.py (verify.sh check 17). Exit 0 = all checks passed.
"""
import contextlib
import importlib.util
import io
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location("time_register_test", os.path.join(ROOT, "tests", "time-register-test.py"))
base = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(base)
# pylint: disable=wrong-import-position
from time_register import staging, store  # noqa: E402  (base put tools/ on sys.path)

check, files_of, split_until, task_rows = base.check, base.files_of, base.split_until, base.task_rows
A, B, C, E, F = (sid[:8] for sid in (base.SID_A, base.SID_B, base.SID_C, base.SID_E, base.SID_F))
STAGED = "add-staged.json"
CMD_MAX = 10000  # Claude Code 2.1.309 asks before a Bash command over this many characters: it cannot parse it
CHUNK = 20  # --add per call in the skill


def env_of(home, session, claudecode=False):
    """The environment of a claude-time call by the Claude Code session `session` (None: no session id)."""
    env = {"HOME": home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}
    if session is not None:
        env[staging.SESSION_ENV] = session
    if claudecode:
        env["CLAUDECODE"] = "1"
    return env


def run(home, session, *args, claudecode=False):
    return subprocess.run([sys.executable, "-I", base.CLI, *args], env=env_of(home, session, claudecode),
                          capture_output=True, text=True, check=False)


def add(*rows):
    return [arg for row in rows for arg in ("--add", *row)]


def done(until, rows, after):
    """The arguments of --split-done with --rows and --after, times as "HH:MM" of the test day."""
    return ["--split-done", f"2026-10-05 {until}", "--rows", str(rows), "--after", f"2026-10-05 {after}"]


def staged(reg):
    path = os.path.join(reg, STAGED)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_staged(reg, data):
    with open(os.path.join(reg, STAGED), "w", encoding="utf-8") as f:
        json.dump(data, f)


def minute(hhmm):
    return int(datetime(*base.DAY, *hhmm, tzinfo=base.KYIV).timestamp())


def fresh(home, tmp, name, boundary="2026-10-05 10:00"):
    """A register folder with its exports and the boundary set."""
    reg = os.path.join(tmp, name)
    run(home, None, "--write", "--home", reg)
    run(home, None, "--split-done", boundary, "--home", reg)
    return reg


def checks_chunks(home, reg):
    run(home, None, "--write", "--home", reg)
    r = run(home, "s1", "--split-done", "2026-10-05 10:00", "--home", reg)
    check("--split-done with nothing staged moves the boundary only", r.returncode == 0 and "записано" not in r.stderr
          and split_until(reg) == "2026-10-05 10:00\n", r.stderr[-300:])
    tasks = files_of(reg)["tasks.csv"]
    row_a = (A, "2026-10-05 10:30", "Задача A частинами", "module", "перша   частина")
    row_b = (B, "2026-10-05 12:00", "Задача B частинами", "bug", "")
    row_c = (C, "2026-10-05 13:10", "Задача C частинами", "ops", "сумнів: лише мітки")
    row_b2 = (B, "2026-10-05 12:00", "Задача B з нової назви", "bug", "друга думка")
    r = run(home, "s1", *add(row_a, row_b), "--stage", "--home", reg)
    check("--stage exit 0", r.returncode == 0 and "нових 2, замінено 0, уже були 0; разом 2" in r.stderr
          and "--rows 2 --after" in r.stderr, r.stderr[-300:])
    check("... tasks.csv not changed", files_of(reg)["tasks.csv"] == tasks)
    entry = (staged(reg) or {}).get("s1", {})
    check("... the rows kept in this session's entry with the boundary, a note on one line",
          entry.get("boundary") == minute((10, 0)) and entry.get("rows") == [
              [A, "2026-10-05 10:30", "Задача A частинами", "module", "перша частина"],
              [B, "2026-10-05 12:00", "Задача B частинами", "bug", ""]], str(entry))
    check("... add-staged.json and add-staged.lock are 0600", all(
        stat.S_IMODE(os.stat(os.path.join(reg, n)).st_mode) == 0o600 for n in (STAGED, "add-staged.lock")))
    r = run(home, "s1", *add(row_b, row_c), "--stage", "--home", reg)
    check("a row staged again counts once", r.returncode == 0 and "нових 1, замінено 0, уже були 1; разом 3" in r.stderr,
          r.stderr[-300:])
    r = run(home, "s1", *add(row_b2), "--stage", "--home", reg)
    check("a row of the same session and start replaces the staged one", r.returncode == 0
          and "нових 0, замінено 1, уже були 0; разом 3" in r.stderr
          and (staged(reg) or {}).get("s1", {}).get("rows", [None, None])[1][2] == "Задача B з нової назви",
          r.stderr[-300:])
    before = files_of(reg)
    for rows, why, said in (
            (((C, "2026-10-05 13:15", "Погана задача", "wrongkind", ""),), "a bad row", "wrongkind"),
            (((E, "2026-10-05 15:00", "Перша E", "bug", ""), (E, "2026-10-05 15:00", "Друга E", "bug", "")),
             "two rows of a session in one minute", "same time"),
            (((A, "2026-10-05 10:30", "Інша A", "module", ""), (A, "2026-10-05 10:30", "Ще інша A", "module", "")),
             "two rows of a start staged already", "two rows of the chunk start at the same time"),
            (((A, "", "Задача без початку", "module", ""),), "a row without its start", "no start"),
            (((A, "2026-10-05 10:00", "Задача на межі", "module", ""),), "a row not after the boundary",
             "not after the boundary 2026-10-05 10:00")):
        r = run(home, "s1", *add(*rows), "--stage", "--home", reg)
        check(f"a chunk with {why} stages nothing", r.returncode == 1 and said in r.stderr
              and "nothing staged, the new rows are bad" in r.stderr and files_of(reg) == before, r.stderr[-300:])
    r = run(home, None, "--pending", "--home", reg)
    check("--stage keeps the boundary", r.stdout.startswith("Поділено на задачі до: 2026-10-05 10:00"), r.stdout[:200])
    for args, why, said in ((["--split-done", "2026-10-05 13:30"], "without --rows", "(it is missing)"),
                            (done("13:30", 2, "10:00"), "with another number", "--rows says 2"),
                            (done("13:30", 3, "09:00"), "with an --after that is not the boundary", "not --after")):
        r = run(home, "s1", *args, "--home", reg)
        check(f"--split-done {why} writes nothing", r.returncode == 1 and said in r.stderr and files_of(reg) == before,
              r.stderr[-300:])
    r = run(home, "s1", *done("13:30", 3, "10:00"), "--home", reg)
    check("--split-done --rows 3 --after the boundary writes the staged rows and the boundary", r.returncode == 0
          and "записано рядків: 3" in r.stderr and "додано задач 3" in r.stderr
          and split_until(reg) == "2026-10-05 13:30\n" and staged(reg) is None, r.stderr[-300:])
    check("... with the markers carried and replaced as --add does", "перенесено в tasks.csv: 3" in r.stderr
          and "замінено новими рядками з того самого часу: 1" in r.stderr and [(x[0], x[2], x[6]) for x in task_rows(reg)]
          == [(A, "Перша задача тесту", ""), (B, "Маркер B", ""), (C, "Маркер C", ""),
              (A, "Задача A частинами", "перша частина"), (B, "Задача B з нової назви", "друга думка"),
              (C, "Задача C частинами", "сумнів: лише мітки")], r.stderr[-300:] + str(task_rows(reg)))


def checks_restart(home, tmp):
    reg = fresh(home, tmp, "reg-restart")
    run(home, "s15", *add((A, "2026-10-05 10:30", "Старий поділ 1", "module", ""),
                          (A, "2026-10-05 11:30", "Старий поділ 2", "module", "")), "--stage", "--home", reg)
    new = [[A, "2026-10-05 10:30", "Новий поділ 1", "module", ""], [B, "2026-10-05 12:00", "Новий поділ 3", "bug", ""]]
    r = run(home, "s15", *add(*new), "--stage", "--restart", "--home", reg)
    check("--restart drops the rows staged before", r.returncode == 0 and "прибрано підготовлених раніше: 2" in r.stderr
          and "разом 2" in r.stderr and (staged(reg) or {}).get("s15", {}).get("rows") == new, r.stderr[-300:])


def checks_atomic(home, reg):
    run(home, "s2", *add((E, "2026-10-05 15:00", "Задача E частинами", "module", "")), "--stage", "--home", reg)
    before = files_of(reg)
    for args, why, said in ((done("14:00", 1, "13:30"), "before a staged row starts", "start after"),
                            (["--split-done", "2099-01-01 00:00", "--rows", "1", "--after", "2026-10-05 13:30"],
                             "in the future", "not over yet"),
                            (done("12:00", 1, "13:30"), "back", "--allow-back")):
        r = run(home, "s2", *args, "--home", reg)
        check(f"--split-done {why} writes neither the rows nor the boundary", r.returncode == 1 and said in r.stderr
              and files_of(reg) == before, r.stderr[-300:])
    run(home, None, *add((E, "2026-10-05 15:00", "Пряма задача E", "module", "")), "--home", reg)
    before = files_of(reg)
    r = run(home, "s2", *done("16:00", 1, "13:30"), "--home", reg)
    check("a staged row --split-done cannot write: neither the rows nor the boundary, the rows stay", r.returncode == 1
          and "same time" in r.stderr and files_of(reg) == before, r.stderr[-300:])


def checks_sessions(home, reg, tmp):
    tasks, s2 = files_of(reg)["tasks.csv"], (staged(reg) or {}).get("s2")
    r = run(home, "s3", *done("16:00", 0, "13:30"), "--home", reg)
    check("--split-done of another session leaves this session's rows alone and moves the boundary", r.returncode == 0
          and "записано рядків: 0" in r.stderr and split_until(reg) == "2026-10-05 16:00\n" and s2
          and (staged(reg) or {}).get("s2") == s2 and files_of(reg)["tasks.csv"] == tasks, r.stderr[-300:])
    before = files_of(reg)
    r = run(home, "s2", *done("16:30", 1, "13:30"), "--home", reg)
    r2 = run(home, "s2", *add((F, "2026-10-05 18:25", "Задача F", "module", "")), "--stage", "--home", reg)
    check("... then this session's --split-done and --stage stop, nothing written", r.returncode == 1
          and r2.returncode == 1 and "another session split meanwhile" in r.stderr
          and "another session split meanwhile; nothing staged" in r2.stderr and files_of(reg) == before,
          r.stderr[-300:] + r2.stderr[-300:])
    race = fresh(home, tmp, "reg-race")  # sx read the boundary 10:00 in --pending, then sy split up to 11:00
    run(home, "sy", *add((A, "2026-10-05 10:30", "Задача іншої сесії", "module", "")), "--stage", "--home", race)
    run(home, "sy", *done("11:00", 1, "10:00"), "--home", race)
    r = run(home, "sx", *add((B, "2026-10-05 12:00", "Задача пізньої сесії", "bug", "")), "--stage", "--home", race)
    before = files_of(race)
    r2 = run(home, "sx", *done("13:30", 1, "10:00"), "--home", race)
    check("a session that staged after another one split from its boundary stops at --split-done --after",
          r.returncode == 0 and r2.returncode == 1 and "not --after 2026-10-05 10:00" in r2.stderr
          and "another session split meanwhile" in r2.stderr and files_of(race) == before, r2.stderr[-300:])
    row_s4, row_s5 = (F, "2026-10-05 18:25", "Задача F від s4", "module", ""), (F, "2026-10-05 18:30", "Задача F", "ops", "")
    run(home, "s4", *add(row_s4), "--stage", "--home", reg)
    run(home, "s5", *add(row_s5), "--stage", "--home", reg)
    r = run(home, "s5", *done("18:40", 1, "16:00"), "--home", reg)
    check("two sessions stage side by side, the one that commits writes its own rows only", r.returncode == 0
          and task_rows(reg)[-1][2] == "Задача F" and "Задача F від s4" not in str(task_rows(reg))
          and list((staged(reg) or {}).get("s4", {}).get("rows", [])) == [list(row_s4)], r.stderr[-300:])
    before = files_of(reg)
    r = run(home, None, *add(row_s4), "--stage", "--home", reg, claudecode=True)
    r2 = run(home, None, *done("18:50", 0, "18:40"), "--home", reg, claudecode=True)
    check("inside Claude Code without a session id --stage and --split-done --rows stop, nothing written",
          r.returncode == 1 and r2.returncode == 1 and staging.SESSION_ENV in r.stderr + r2.stderr
          and files_of(reg) == before, r.stderr[-300:] + r2.stderr[-300:])
    bare = fresh(home, tmp, "reg-no-session")
    run(home, None, *add((A, "2026-10-05 10:30", "Задача поза сесією", "module", "")), "--stage", "--home", bare)
    r = run(home, None, *done("12:00", 1, "10:00"), "--home", bare)
    check("outside Claude Code the same", r.returncode == 0 and "записано рядків: 1" in r.stderr and staged(bare) is None,
          r.stderr[-300:])
    old = int(datetime.now(base.KYIV).timestamp()) - (staging.STAGED_DAYS + 1) * 86400
    write_staged(bare, {"old": {"boundary": minute((12, 0)), "staged": old, "rows": []},
                        "young": {"boundary": minute((12, 0)), "staged": old + 2 * 86400, "rows": []}})
    run(home, "s6", *add((B, "2026-10-05 12:20", "Задача B", "bug", "")), "--stage", "--home", bare)
    check(f"an entry not staged for {staging.STAGED_DAYS} days goes with the next write",
          sorted(staged(bare) or {}) == ["s6", "young"], str(staged(bare)))


def checks_parallel(home, tmp):
    reg = fresh(home, tmp, "reg-parallel")
    procs = [subprocess.Popen([sys.executable, "-I", base.CLI, *add((A, f"2026-10-05 10:{31 + i}", f"Паралельна {i}",
                                                                     "module", "")), "--stage", "--home", reg],
                              env=env_of(home, "sp"), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
             for i in range(8)]
    codes = [p.wait() for p in procs]
    for p in procs:
        p.stderr.close()
    check("chunks of one session sent at once all stay staged", codes == [0] * 8
          and len((staged(reg) or {}).get("sp", {}).get("rows", [])) == 8, f"{codes} {staged(reg)}")


def checks_retry(home, tmp):
    reg = fresh(home, tmp, "reg-retry")
    run(home, "s7", *add((A, "2026-10-05 10:30", "Задача повтору", "module", "")), "--stage", "--home", reg)
    sessions = store.load_store(reg)
    with contextlib.redirect_stderr(io.StringIO()):  # a --split-done cut short after its tasks.csv write
        store.add_tasks(reg, sessions, staged(reg)["s7"]["rows"])
    r = run(home, "s7", *done("12:00", 1, "10:00"), "--home", reg)
    titles = [x[2] for x in task_rows(reg)]
    check("a --split-done cut short after tasks.csv completes when run again, no row twice", r.returncode == 0
          and "записано рядків: 0, уже були в tasks.csv: 1" in r.stderr and titles.count("Задача повтору") == 1
          and split_until(reg) == "2026-10-05 12:00\n" and staged(reg) is None, r.stderr[-300:])
    run(home, "s8", *add((B, "2026-10-05 12:30", "Задача другого повтору", "bug", "")), "--stage", "--home", reg)
    with contextlib.redirect_stderr(io.StringIO()):  # ... and after its boundary write
        store.add_tasks(reg, sessions, staged(reg)["s8"]["rows"])
        store.save_split_until(reg, minute((13, 0)), False)
    r = run(home, "s8", *done("13:00", 1, "12:00"), "--home", reg)
    titles = [x[2] for x in task_rows(reg)]
    check("... and after the boundary too, saying the rows were there", r.returncode == 0
          and "записано рядків: 0, уже були в tasks.csv: 1" in r.stderr
          and titles.count("Задача другого повтору") == 1 and split_until(reg) == "2026-10-05 13:00\n"
          and staged(reg) is None, r.stderr[-300:])


def checks_cut(home, tmp):
    reg = fresh(home, tmp, "reg-cut")
    run(home, "s11", *add((A, "2026-10-05 10:30", "Задача обірваного запису", "module", "")), "--stage", "--home", reg)
    data = staged(reg)
    data["s11"]["commit"] = minute((12, 0))  # its --split-done 12:00 wrote tasks.csv, then stopped
    write_staged(reg, data)
    with contextlib.redirect_stderr(io.StringIO()):
        store.add_tasks(reg, store.load_store(reg), data["s11"]["rows"])
    r = run(home, "s12", *add((B, "2026-10-05 12:30", "Задача наступного запуску", "bug", "")), "--stage", "--home", reg)
    check("a --split-done cut short between its writes is finished by the next run of another session, which stops",
          r.returncode == 1 and "finished now, the boundary is 2026-10-05 12:00" in r.stderr
          and split_until(reg) == "2026-10-05 12:00\n" and staged(reg) is None
          and [x[2] for x in task_rows(reg)].count("Задача обірваного запису") == 1, r.stderr[-300:])
    run(home, "s13", *add((C, "2026-10-05 13:10", "Задача без запису", "ops", "")), "--stage", "--home", reg)
    data = staged(reg)
    data["s13"]["commit"] = minute((13, 30))  # stopped before its tasks.csv write
    write_staged(reg, data)
    r = run(home, "s14", *add((E, "2026-10-05 15:00", "Задача ще одного запуску", "module", "")), "--stage", "--home", reg)
    check("... but not one whose rows never reached tasks.csv", r.returncode == 0
          and split_until(reg) == "2026-10-05 12:00\n" and sorted(staged(reg) or {}) == ["s13", "s14"], r.stderr[-300:])


def checks_args(home, reg, tmp):
    row = (A, "2026-10-05 11:40", "Задача з аргументів", "module", "")
    for args, why in ((("--stage",), "--stage without --add"), ((*add(row), "--stage", "--write"), "--stage with --write"),
                      (("--rows", "1"), "--rows without --split-done"),
                      (("--split-done", "2026-10-05 12:00", "--rows", "-1", "--after", "2026-10-05 10:00"),
                       "--rows below 0"),
                      (("--split-done", "2026-10-05 12:00", "--rows", "1"), "--rows without --after"),
                      ((*add(row), "--restart"), "--restart without --stage"),
                      (("--pending", "--after", "2026-10-05 10:00"), "--after with --pending")):
        r = run(home, "s9", *args, "--home", reg)
        check(f"{why} stops", r.returncode == 2, str(r.returncode))
    before = files_of(reg)
    r = run(home, "s9", "--prompts", A, *add(row), "--stage", "--home", reg)
    check("--prompts with --add --stage prints the prompts and stages nothing", r.returncode == 0
          and "задача: Перша задача тесту" in r.stdout and files_of(reg) == before, r.stderr[-300:])
    r = run(home, "s9", "--prompts", "77777777")
    check("--prompts of an unknown id names the problem", r.returncode == 1 and "matches 0 sessions" in r.stderr,
          r.stderr[-300:])
    broken = fresh(home, tmp, "reg-broken")
    for text, why in (("{", "unreadable"), ('{"s9": {"boundary": null, "rows": []}}', "of another form")):
        with open(os.path.join(broken, STAGED), "w", encoding="utf-8") as f:
            f.write(text)
        before = files_of(broken)
        r = run(home, "s9", *done("12:00", 0, "10:00"), "--home", broken)
        r2 = run(home, "s9", *add(row), "--stage", "--home", broken)
        check(f"add-staged.json {why}: --split-done and --stage stop, nothing written", r.returncode == 1
              and r2.returncode == 1 and STAGED in r.stderr and STAGED in r2.stderr and files_of(broken) == before,
              r.stderr[-300:] + r2.stderr[-300:])


def checks_lossy(tmp):
    home, reg, sid = os.path.join(tmp, "lossy"), os.path.join(tmp, "lossy-reg"), "51515151-9999-4999-8999-999999999999"
    cwd = "/Users/time-register-test/WebstormProjects/demo"
    path = os.path.join(home, ".claude", "projects", "-demo", sid + ".jsonl")
    records = [base.user(sid, cwd, 1, (9, 0), "запит"), base.assistant(sid, cwd, 1, (9, 10))]
    base.write_jsonl(path, records)
    run(home, "s10", "--split-done", "2026-10-05 08:00", "--home", reg)
    row = (sid[:8], "2026-10-05 09:00", "Задача з втратою", "module", "")
    run(home, "s10", *add(row), "--stage", "--home", reg)
    base.write_jsonl(path, records + [dict(base.user(sid, cwd, 2, (9, 20), ""), message="рядок")])
    before = files_of(reg)
    r = run(home, "s10", *done("09:30", 1, "08:00"), "--home", reg)
    r2 = run(home, "s10", *add(row), "--stage", "--home", reg)
    check("a record that stops a write stops --split-done after a staging and --stage, nothing written",
          r.returncode == 1 and r2.returncode == 1 and "увага: реєстр не записано" in r.stderr
          and "увага: реєстр не записано" in r2.stderr and files_of(reg) == before, r.stderr[-300:] + r2.stderr[-300:])


def checks_typed(tmp):
    home, reg, sid = os.path.join(tmp, "typed"), os.path.join(tmp, "typed-reg"), "52525252-9999-4999-8999-999999999999"
    cwd = "/Users/time-register-test/WebstormProjects/demo"
    base.write_jsonl(os.path.join(home, ".claude", "projects", "-demo", sid + ".jsonl"), [
        base.user(sid, cwd, 1, (9, 0), "запит"), base.user(sid, cwd, 2, (9, 5), "<div> не центрується"),
        base.user(sid, cwd, 3, (9, 10), "<3 дякую"), base.assistant(sid, cwd, 1, (9, 20))])
    run(home, "s11", "--split-done", "2026-10-05 08:00", "--home", reg)
    row = (sid[:8], "2026-10-05 09:00", "Задача з тегом", "ui", "")
    runs = [run(home, "s11", *args, "--home", reg) for args in (
        ["--write"], ["--pending", "--full"], [*add(row), "--stage"], done("09:30", 1, "08:00"), ["--write"])]
    note = "примітка: записів з «<» на початку 2 (тег на початку: div 1; «<» без тегу 1): запитами не враховано"
    check("text with «<» after the boundary: each step of the split runs with the примітка line and no увага, the "
          "staged row and the boundary written", all(
              r.returncode == 0 and "увага" not in r.stderr and any(x.startswith(note) for x in r.stderr.splitlines())
              for r in runs) and "записано рядків: 1" in runs[3].stderr and split_until(reg) == "2026-10-05 09:30\n"
          and [(x[0], x[2]) for x in task_rows(reg)] == [(sid[:8], "Задача з тегом")],
          "".join(r.stderr[-300:] for r in runs) + str(task_rows(reg)))


def checks_length():
    row = ("0" * 8, "2026-10-05 10:00", "з" * 60, "integration", "ґ" * 160)
    cmd = "~/bin/claude-time" + "".join(f" --add {s} {shlex.quote(t)} {shlex.quote(n)} {k} {shlex.quote(o)}"
                                        for s, t, n, k, o in [row] * CHUNK) + " --stage --restart"
    check(f"a chunk of {CHUNK} rows of the longest task and note is a command under {CMD_MAX} characters",
          len(cmd) < CMD_MAX, str(len(cmd)))


def main():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="time-register-stage-test.", dir="/private/tmp"))
    try:
        home = base.build_home(tmp)
        reg = os.path.join(tmp, "reg")
        checks_chunks(home, reg)
        checks_restart(home, tmp)
        checks_atomic(home, reg)
        checks_sessions(home, reg, tmp)
        checks_parallel(home, tmp)
        checks_retry(home, tmp)
        checks_cut(home, tmp)
        checks_args(home, reg, tmp)
        checks_lossy(tmp)
        checks_typed(tmp)
        checks_length()
        check("no __pycache__ written", not os.path.exists(os.path.join(ROOT, "tools", "time_register", "__pycache__")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for f in base.FAILS:
        print("FAIL " + f)
    print(f"time-register stage test: {base.CHECKS[0]} checks, {len(base.FAILS)} failed")
    sys.exit(1 if base.FAILS else 0)


if __name__ == "__main__":
    main()
