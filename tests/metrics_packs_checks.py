"""Checks of claude-metrics --packs for tests/metrics-test.py (ADR-007, L4): the use of the packs of the library on one
made-up home with a catalog, a journal of claude-pack and transcripts, the day fixed at TODAY.

The home: packs alpha (a file signal alpha.toml and a manifest package.json; skills one and two, agent rev), beta and
gamma (no file signals). Project folders app, site and idle in the projects folder `work`, lab outside it.
  app: alpha on for 40 days, gamma for 90 (both in the journal), the review of day 30 of alpha recorded. Sessions:
    a1 edit, Skill alpha:one (its line written twice: counted once), agent alpha:rev, calls of a skill of the base and
       of another plugin (not packs); its subagent: Skill alpha:two and an edit;
    a2 the listing leaves alpha:two with its bare name (cut), an edit of alpha.toml, no call: a miss;
    a3 no edit, `/alpha:one` typed (and a preloaded skill, a meta record: no call);
    a4 an edit of sub/alpha.toml (not the root: no miss), no call;
    a5 38 days ago, inside the first 30 days of alpha: an edit and a call;
    a6 in a worktree the app keeps inside app: alpha:two cut, an edit of alpha.toml in its root, Skill alpha:two;
    old 70 days ago and not changed since: outside the window, never opened by doctor's scan;
    f1 a fork that copied a1: nothing of it counts twice.
  site: beta on with no journal line (by hand); s1 with a listing of the old form (no `names`) of 25 000 characters,
    an edit, no call; a second listing of an unknown form and a line that is no JSON; a transcript that does not open.
  lab: alpha enabled 20 days ago and disabled 10 days ago; l1 an edit and a call.
  idle: no pack; i1 an edit.
Checked: the numbers of every pair by hand, the first 30 days, the reviews, the fill of the skill listing, what the
report prints, the lines of doctor (its scan reads in full only the folders of the projects with a pack on), a journal
that does not open, and the command line. The edges, each on a home of its own: metrics_packs_edge_checks.py.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timedelta

from claude_metrics import packs, packs_report, packs_scan, packs_sources
from claude_metrics.patterns import KYIV

TODAY = date(2026, 11, 20)
ALPHA = (("base", "a skill of the base"), ("alpha:one", "does one"), ("alpha:two", "does two"), ("gamma:g", "does g"),
         ("other:x", "a plugin that is no pack"))
CUT = tuple((name, None if name == "alpha:two" else text) for name, text in ALPHA)
CATALOG = {"schema": 1, "catalog": "library", "packs": [
    {"name": "alpha", "status": "active",
     "signals": {"filesRead": ["alpha.toml"], "manifestDeps": [{"file": "package.json", "pattern": "x"}], "cwd": []},
     "skills": [{"name": "one", "desc_chars": 8, "auto": True}, {"name": "two", "desc_chars": 8, "auto": True}],
     "agents": [{"name": "rev"}]},
    {"name": "beta", "status": "pilot", "signals": {"filesRead": [], "manifestDeps": [], "cwd": []},
     "skills": [{"name": "solo", "desc_chars": 10, "auto": True}], "agents": []},
    {"name": "gamma", "status": "pilot", "signals": {}, "skills": [{"name": "g", "desc_chars": 6}], "agents": []}]}


def day(ago):
    return TODAY - timedelta(days=ago)


def at(ago, minute=0):
    return "%sT10:%02d:00Z" % (day(ago), minute)


def rec(sid, n, kind, when, cwd, **extra):
    return {"type": kind, "sessionId": sid, "uuid": "%s-%d" % (sid, n), "cwd": cwd, "timestamp": when, **extra}


def listing(sid, n, when, cwd, skills, names=True, pad=0, initial=True):
    """A skill listing: skills are (name, description or None: the bare name); names False: the old form without them."""
    lines = ["- %s: %s" % (name, text) if text else "- " + name for name, text in skills]
    if pad:
        lines.append("- filler: " + "x" * (pad - len("\n".join(lines)) - len("\n- filler: ")))
    att = {"type": "skill_listing", "content": "\n".join(lines), "skillCount": len(lines), "isInitial": initial}
    if names is True:
        att["names"] = [ln[2:].split(": ")[0] for ln in lines]
    elif names is not False:
        att["names"] = names
    return rec(sid, n, "attachment", when, cwd, attachment=att)


def tool(name, tid, **inp):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def calls(sid, n, when, cwd, *blocks):
    return rec(sid, n, "assistant", when, cwd, message={"id": "%sm%d" % (sid, n), "model": "m", "content": list(blocks)})


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def session(home, folder, sid, rows, sub=None):
    base = os.path.join(home, "projects", folder)
    put(os.path.join(base, sid + ".jsonl"), "".join(json.dumps(r) + "\n" for r in rows))
    if sub:
        put(os.path.join(base, sid, "subagents", "agent-1.jsonl"), "".join(json.dumps(r) + "\n" for r in sub))
    return os.path.join(base, sid + ".jsonl")


def journal_line(ago, project, pack, action, **more):
    return json.dumps(dict({"ts": at(ago), "project": project, "pack": pack, "action": action}, **more, tag="v-test")) + "\n"


def build(root):
    """The made-up home; returns (home, projects folder, {name: project folder})."""
    home, work = os.path.join(root, ".claude"), os.path.join(root, "work")
    where = {"app": os.path.join(work, "app"), "site": os.path.join(work, "site"), "idle": os.path.join(work, "idle"),
             "lab": os.path.join(root, "elsewhere", "lab")}
    app, site, lab, idle = where["app"], where["site"], where["lab"], where["idle"]
    tree = os.path.join(app, ".claude", "worktrees", "w1")
    put(os.path.join(home, "packs", "catalog.json"), json.dumps(CATALOG))
    put(os.path.join(home, "state", "packs.jsonl"), "".join([
        journal_line(90, app, "gamma", "enable"), journal_line(40, app, "alpha", "enable"),
        journal_line(20, lab, "alpha", "enable"), journal_line(10, lab, "alpha", "disable"),
        journal_line(5, None, "alpha", "review", day=30), "not a line of the journal\n",
        journal_line(3, app, "alpha", "explode"), "\n"]))
    one = calls("a1", 2, at(5, 2), app, tool("Skill", "a1-s1", skill="alpha:one"))
    a1 = [listing("a1", 0, at(5), app, ALPHA),
          calls("a1", 1, at(5, 1), app, tool("Edit", "a1-e1", file_path=app + "/src/x.py"),
                tool("Agent", "a1-g1", subagent_type="alpha:rev"), tool("Skill", "a1-o1", skill="other:x"),
                tool("Skill", "a1-b1", skill="base"), tool("Bash", "a1-c1", command="ls")),
          one, dict(one, uuid="a1-3")]
    session(home, "-work-app", "a1", a1, sub=[
        calls("a1", 10, at(5, 5), app, tool("Skill", "a1-s2", skill="alpha:two"), tool("Write", "a1-e2", file_path=app + "/y.txt"))])
    session(home, "-work-app", "a2", [listing("a2", 0, at(4), app, CUT),
                                      calls("a2", 1, at(4, 1), app, tool("Edit", "a2-e1", file_path=app + "/alpha.toml"))])
    session(home, "-work-app", "a3", [
        listing("a3", 0, at(3), app, ALPHA),
        rec("a3", 1, "user", at(3, 1), app, message={"role": "user", "content": "<command-name>/alpha:one</command-name>\n<command-message>alpha:one</command-message>"}),
        rec("a3", 2, "user", at(3, 2), app, isMeta=True, message={"role": "user", "content": "<command-name>alpha:two</command-name> <skill-format>true</skill-format>"})])
    session(home, "-work-app", "a4", [listing("a4", 0, at(2), app, ALPHA),
                                      calls("a4", 1, at(2, 1), app, tool("Edit", "a4-e1", file_path=app + "/sub/alpha.toml"))])
    session(home, "-work-app", "a5", [listing("a5", 0, at(38), app, ALPHA),
                                      calls("a5", 1, at(38, 1), app, tool("Write", "a5-e1", file_path=app + "/z.py"),
                                            tool("Skill", "a5-s1", skill="alpha:one"))])
    session(home, "-work-app-wt", "a6", [listing("a6", 0, at(1), tree, CUT),
                                         calls("a6", 1, at(1, 1), tree, tool("MultiEdit", "a6-e1", file_path=tree + "/alpha.toml"),
                                               tool("Skill", "a6-s1", skill="alpha:two"))])
    old = session(home, "-work-app", "old", [listing("old", 0, at(70), app, ALPHA),
                                             calls("old", 1, at(70, 1), app, tool("Edit", "old-e1", file_path=app + "/o.py"),
                                                   tool("Skill", "old-s1", skill="alpha:one"))])
    then = datetime.combine(day(70), datetime.min.time(), KYIV).timestamp() + 43200
    os.utime(old, (then, then))
    session(home, "-work-app", "f1", a1 + [rec("f1", 9, "assistant", at(5, 9), app, message={"id": "f1m", "model": "m", "content": []})])
    s1 = session(home, "-work-site", "s1", [
        listing("s1", 0, at(6), site, (("base", "a skill of the base"), ("beta:solo", "solo skill")), names=False, pad=25000),
        calls("s1", 1, at(6, 1), site, tool("Write", "s1-e1", file_path=site + "/page.md")),
        listing("s1", 2, at(6, 2), site, (("beta:solo", "solo skill"),), names={"beta:solo": 1}, initial=False)])
    with open(s1, "a", encoding="utf-8") as fh:
        fh.write('{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit"\n')
    os.makedirs(os.path.join(home, "projects", "-work-site", "broken.jsonl"))
    session(home, "-lab", "l1", [listing("l1", 0, at(15), lab, (("alpha:one", "does one"),)),
                                 calls("l1", 1, at(15, 1), lab, tool("Edit", "l1-e1", file_path=lab + "/z.py"),
                                       tool("Skill", "l1-s1", skill="alpha:one"))])
    session(home, "-work-idle", "i1", [listing("i1", 0, at(7), idle, (("base", "a skill of the base"),)),
                                       calls("i1", 1, at(7, 1), idle, tool("Edit", "i1-e1", file_path=idle + "/a.txt"))])
    return home, work, where


def unit_checks(check):
    match = packs_scan.root_match
    check("packs: a signal file is a file of the root", match("alpha.toml", "alpha.toml") and match("main.tf", "*.tf")
          and match("a/b.json", "a/*.json") and not match("sub/alpha.toml", "alpha.toml") and not match("infra/main.tf", "*.tf"))
    of = packs_scan.project_of
    check("packs: the project of a session folder",
          (of("/w/app/pkg", {"/w/app", "/w/app/pkg/deep"}, "/w"), of("/w/app", {"/w/app"}, "/w"), of("/w/mono/api/src", set(), "/w"),
           of("/x/lab/.claude/worktrees/t/src", set(), "/w"), of("/w/apple", {"/w/app"}, "/w"), of(None, set(), "/w"))
          == ("/w/app", "/w/app", "/w/mono", "/x/lab", "/w/apple", None))
    row = packs_sources.journal_row
    good = row('{"ts": "2026-11-01T10:00:00Z", "project": "/w/app", "pack": "alpha", "action": "enable", "tag": null}')
    review = row('{"ts": "2026-11-01T10:00:00Z", "project": null, "pack": "alpha", "action": "review", "day": 60}')
    bad = ['[]', '{"ts": "then", "project": "/w", "pack": "alpha", "action": "enable"}',
           '{"ts": "2026-11-01T10:00:00Z", "project": "/w", "pack": "Alpha!", "action": "enable"}',
           '{"ts": "2026-11-01T10:00:00Z", "project": null, "pack": "alpha", "action": "enable"}',
           '{"ts": "2026-11-01T10:00:00Z", "project": 5, "pack": "alpha", "action": "disable"}',
           '{"ts": "2026-11-01T10:00:00Z", "project": null, "pack": "alpha", "action": "review", "day": 45}',
           '{"ts": "2026-11-01T10:00:00Z", "project": null, "pack": "alpha", "action": "review", "day": true}']
    check("packs: a journal line of a known form", good and good[1:] == ("/w/app", "alpha", "enable", None)
          and review and review[1:] == (None, "alpha", "review", 60), str((good, review)))
    check("packs: journal lines of another form are none", [row(b) for b in bad] == [None] * len(bad), str([row(b) for b in bad]))
    far = b'{"type":"user","message":{"content":"' + b"x" * 5000 + b'<command-name>/alpha:one</command-name>"}}'
    check("packs: which lines are parsed", packs_scan.wanted(b'{"attachment":{"type":"skill_listing"}}')
          and packs_scan.wanted(b'{"message":{"content":"<command-name>/alpha:one</command-name>"}}')
          and packs_scan.wanted(b'{"type":"tool_use","name":"Edit"}') and not packs_scan.wanted(b'{"type":"tool_use","name":"Bash"}')
          and not packs_scan.wanted(far) and not packs_scan.wanted(b'{"type":"tool_result","content":"Edit"}'))


def pair(data, name, pack):
    return next((p for p in data["pairs"] if (p["name"], p["pack"]) == (name, pack)), {})


def picked(row, *keys):
    return tuple(row.get(k) for k in keys)


def report_checks(check, home, work):
    data = packs.collect(home, work, 60, TODAY)
    check("packs: the pairs of the window", [(p["name"], p["pack"]) for p in data["pairs"]] == [
        ("lab", "alpha"), ("app", "alpha"), ("app", "gamma"), ("site", "beta")], str([(p["name"], p["pack"]) for p in data["pairs"]]))
    alpha = pair(data, "app", "alpha")
    check("packs: app and alpha: sessions 6, work 5, called 3, misses 1, cut in 2",
          picked(alpha, "sessions", "work", "called", "share_pct", "misses", "cut_sessions", "cut_max", "calls_total", "last_call")
          == (6, 5, 3, 60, 1, 2, 1, 6, day(1)), str(alpha))
    check("packs: app and alpha: the calls by skill, command and agent",
          alpha.get("calls") == {"skill": {"one": 2, "two": 2}, "slash": {"one": 1}, "agent": {"rev": 1}}, str(alpha.get("calls")))
    check("packs: app and alpha: on since the journal line, with file signals",
          picked(alpha, "on", "enabled_since", "journal_state", "has_signals") == (True, day(40), "enable", True), str(alpha))
    first = alpha.get("first_days") or {}
    check("packs: the first 30 days of alpha in app: one work session, called",
          picked(first, "first", "last", "complete", "covered", "work", "called", "share_pct")
          == (day(40), day(11), True, True, 1, 1, 100), str(first))
    gamma = pair(data, "app", "gamma")
    check("packs: app and gamma: on, 5 work sessions, never called, no misses to count",
          picked(gamma, "on", "work", "called", "share_pct", "calls_total", "misses", "has_signals", "last_call")
          == (True, 5, 0, 0, 0, 0, False, None), str(gamma))
    check("packs: the first 30 days of gamma are before the oldest transcript: not covered, no numbers",
          picked(gamma.get("first_days") or {}, "covered", "work") == (False, None), str(gamma.get("first_days")))
    beta = pair(data, "site", "beta")
    check("packs: site and beta: seen in a session, no journal line, a listing without names read by its lines",
          picked(beta, "on", "enabled_since", "journal_state", "sessions", "work", "called", "calls_total", "cut_sessions")
          == (False, None, None, 1, 1, 0, 0, 0), str(beta))
    lab = pair(data, "lab", "alpha")
    check("packs: lab and alpha: disabled by the journal, its session counts",
          picked(lab, "on", "enabled_since", "journal_state", "work", "called", "share_pct") == (False, day(20), "disable", 1, 1, 100), str(lab))
    fill = {f["name"]: f for f in data["fill"]}
    check("packs: the fill of the skill listing by project: the listing a last session started with",
          sorted(fill) == ["app", "idle", "lab", "site"] and picked(fill["site"], "chars", "pct", "cut", "day") == (25000, 83, 0, day(6))
          and picked(fill["app"], "cut", "day") == (1, day(1)) and fill["idle"]["pct"] == 0, str(fill))
    check("packs: the reviews: alpha has day 30 recorded, gamma is due both",
          [picked(r, "pack", "name", "first_enable", "days", "recorded", "due") for r in data["reviews"]]
          == [("alpha", "app", day(40), 40, [30], []), ("gamma", "app", day(90), 90, [], [30, 60])], str(data["reviews"]))
    scan = data["scan"]
    check("packs: what was not read is counted", picked(scan, "unreadable", "bad_lines", "listing_form_unknown", "oldest")
          == (1, 1, 1, day(70)) and (data["journal_bad"], data["journal_lines"]) == (2, 5), str((scan, data["journal_bad"])))
    shown = io.StringIO()
    with contextlib.redirect_stdout(shown):
        packs_report.print_report(data)
    text = shown.getvalue()
    wanted = ("увага: рядків журналу claude-pack незнайомої форми: 2",
              "увага: транскрипти прочитано не повністю (файлів не відкрилось чи обірвалось 1, рядків не JSON 1)",
              "увага: списків скілів чи їхніх рядків незнайомої форми: 1",
              "Паки бібліотеки за 60 днів (%s..%s)." % (day(59), TODAY),
              "app · alpha (увімкнено %s): сесій з паком 6, робочих 5, з них з викликом 3 (60%%); викликів 6, останній %s; "
              "пропусків 1; сесій з обрізаним описом 2 (до 1 описів)" % (day(40), day(1)),
              "    скіли: one 2, two 2; командою: one 1; агенти: rev 1",
              "    перші 30 днів від вмикання (%s..%s): з викликом 1 з 1 робочих сесій (100%%)" % (day(40), day(11)),
              "    перші 30 днів від вмикання (%s..%s): транскрипти так далеко не сягають" % (day(90), day(61)),
              "site · beta (рядка вмикання в журналі немає): сесій з паком 1, робочих 1, з них з викликом 0 (0%); викликів 0; "
              "пропуски не рахуються: пак без файлових сигналів; сесій з обрізаним описом 0",
              "lab · alpha (увімкнено %s, за журналом зараз вимкнено)" % day(20),
              "Увімкнені і без викликів у вікні: gamma у app (робочих сесій 5)",
              "site 25000 (83%)", "обрізано описів паків: 1", "решта проєктів: 1, найбільший idle 0%",
              "alpha: перше вмикання %s (app), 40 днів тому; огляд 30 дня записано, огляд 60 дня з %s" % (day(40), day(-20)),
              "gamma: перше вмикання %s (app), 90 днів тому; огляд 30 дня НЕ ЗАПИСАНО, огляд 60 дня НЕ ЗАПИСАНО" % day(90))
    for line in wanted:
        check("packs: the report says: " + line[:60], line in text, text)
    # a window of 10 days still reaches back to the first enable for the first 30 days
    short = packs.collect(home, work, 10, TODAY)
    check("packs: a window of 10 days: 5 sessions of alpha in app, the first 30 days still read",
          picked(pair(short, "app", "alpha"), "sessions", "work", "called") == (5, 4, 2)
          and picked(pair(short, "app", "alpha").get("first_days") or {}, "covered", "work") == (True, 1)
          and pair(short, "lab", "alpha") == {}, str(short["pairs"]))


def doctor_checks(check, home, work, where):
    enabled = {(where["app"], "alpha"), (where["app"], "gamma"), (where["site"], "beta"), (where["app"], "zeta")}
    data = packs.collect(home, work, 60, TODAY, enabled)
    check("doctor: a pack the catalog does not have is not counted; only the folders of the projects with a pack on are read in full",
          [(p["name"], p["pack"], p["on"]) for p in data["pairs"]] == [
              ("lab", "alpha", False), ("app", "alpha", True), ("app", "gamma", True), ("site", "beta", True)]
          and data["scan"].get("folders_head_only") == 2 and pair(data, "lab", "alpha")["work"] == 0, str(data["pairs"]))
    lines = packs_report.doctor_lines(data, "J")
    warn = "  WARN: library: "
    want = [
        # app has two packs on: its 5 sessions with an edit count once, with the one of site that is 6
        "  library use: 3 pack(s) on in 2 project(s); 60 days of transcripts, 11 session(s) looked at: 6 with a pack on and "
        "an edit, 6 call(s) of pack skills and agents; the skill list a last session started with: at most 83% of 30000 "
        "chars (site)",
        warn + "2 line(s) of J are no journal line of claude-pack: an enable or a review they held is not counted",
        warn + "transcripts of the packs not read in full (1 file(s) did not open or broke off, 1 line(s) are no JSON): the "
        "counts of calls and sessions are a lower bound",
        warn + "1 skill listing(s) or lines of one of an unknown form (a transcript format change? Compare with docs/compat.md): "
        "cut descriptions are not counted there",
        warn + 'on, and the last line of the journal does not say so (turned on by hand, or before the journal): beta in 1 '
        '(site): the days to "no call in 60 days" are not counted there, nor to the reviews of a pack the journal never '
        'enabled (~/bin/claude-pack disable <pack> and then enable <pack> in the project writes the line)',
        warn + "no call in 60 days: gamma in 1 (app: on since %s, 5 session(s) with an edit): ADR-007 turns such a pack off in "
        "the project (~/bin/claude-pack disable <pack> there)" % day(90),
        warn + "the skill list of app: %d chars at the start of its last session (%s), 0%% of about 30000; 1 description(s) of "
        "pack skills cut: what does not fit keeps its bare name, the least used first (~/bin/claude-pack disable a pack "
        "there, or turn off skills of the account)" % (len("\n".join("- %s: %s" % s if s[1] else "- " + s[0] for s in CUT)), day(1)),
        warn + "the skill list of site: 25000 chars at the start of its last session (%s), 83%% of about 30000: what does not "
        "fit keeps its bare name, the least used first (~/bin/claude-pack disable a pack there, or turn off skills of the "
        "account)" % day(6),
        warn + "pack gamma: 90 days since its first enable (%s, app), the review of day 30 and 60 is not recorded (in the "
        "planned review of the base: ~/bin/claude-metrics --packs and a sample of 5-10 sessions; then ~/bin/claude-pack "
        "review gamma --day 30)" % day(90)]
    check("doctor: the lines of the use of the packs", lines == want, "\n".join("got  " + ln for ln in lines) + "\n" + "\n".join("want " + ln for ln in want))
    # the journal is a folder: said once, and no pack is called "by hand" for it
    journal = os.path.join(home, "state", "packs.jsonl")
    os.rename(journal, journal + ".kept")
    os.makedirs(journal)
    lines = packs_report.doctor_lines(packs.collect(home, work, 60, TODAY, enabled), "J")
    check("doctor: a journal that does not open is one WARN, not three packs on by hand",
          [ln for ln in lines if " J " in ln or "by hand" in ln] == [
              warn + 'J does not open (IsADirectoryError): the first enable of the packs is not known, the reviews and "no call '
              'in 60 days" are not counted'], "\n".join(lines))
    os.rmdir(journal)
    os.rename(journal + ".kept", journal)


def cli_checks(check, cli, home, work, tmp):
    """The command line, whatever the day: the fixed days of the made-up sessions drift out of its window."""
    env = {"HOME": os.path.join(tmp, "packs-nohome"), "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}
    enabled = os.path.join(tmp, "packs-enabled.tsv")
    put(enabled, "alpha\tapp\nbeta\tsite\nzeta\tapp\n\n")

    def run(*args):
        p = subprocess.run([sys.executable, "-I", cli, "--packs", "--claude-home", home, "--projects-dir", work, *args],
                           env=env, capture_output=True, text=True, check=False)
        return p.returncode, p.stdout, p.stderr
    rc, out, err = run()
    check("cli --packs: the report", rc == 0 and "Паки бібліотеки за 60 днів" in out and "Огляди паків" in out and not err, out + err)
    rc, out, err = run("--json", "--days", "30")
    try:
        data = json.loads(out)
    except ValueError:
        data = {}
    check("cli --packs --json: one object with the window and the scan",
          rc == 0 and data.get("window", {}).get("days") == 30 and data.get("limit") == 30000 and "scan" in data
          and isinstance(data.get("pairs"), list), out[:300] + err)
    rc, out, err = run("--doctor", "--enabled", enabled, "--journal-shown", "CLAUDE_HOME/state/packs.jsonl")
    check("cli --packs --doctor: the first line is the summary, the journal is named as told",
          rc == 0 and out.startswith("  library use: 2 pack(s) on in 2 project(s); 60 days of transcripts, 11 session(s) looked at: ")
          and "of CLAUDE_HOME/state/packs.jsonl are no journal line" in out and not err, out + err)
    for args, name in ((("--days", "0"), "a window of no days"), (("--days", "181"), "a window over the limit"),
                       (("--doctor",), "--doctor with no file of the packs that are on"),
                       (("--doctor", "--enabled", os.path.join(tmp, "packs-no-such-file")), "a file that is not there")):
        rc, out, err = run(*args)
        check("cli --packs: refused: " + name, rc != 0 and not out.startswith("  library use: "), out + err)
    rc, out, err = run("--claude-home", os.path.join(tmp, "packs-bare-cli"))
    check("cli --packs: a home with no library says so and exits 0", rc == 0 and "Бібліотеки паків тут немає" in out, out + err)


def packs_checks(tmp, check, cli):
    unit_checks(check)
    home, work, where = build(os.path.join(tmp, "packs"))
    report_checks(check, home, work)
    doctor_checks(check, home, work, where)
    cli_checks(check, cli, home, work, tmp)
    stats = Counter()
    list(packs_scan.rows(os.path.join(home, "projects", "-work-site", "broken.jsonl"), stats))
    check("packs: a transcript that does not open is counted, not raised", stats == Counter(unreadable=1), str(stats))
