"""The edges of claude-metrics --packs for tests/metrics-test.py (ADR-007, L4), each on a small made-up home of its own
(the helpers and the catalog are those of metrics_packs_checks.py):
  - a home with no library, with no transcripts, with a journal that does not open and nothing else;
  - a catalog of another schema, one that is no JSON, one with no packs;
  - transcripts that start later than the window: "no call in 60 days" is not judged;
  - the day "no call in 60 days" starts (60 days on, not 59); a pack turned off and on again starts its days anew while
    its reviews count from the first enable; a pack the settings have on after the journal turned it off;
  - one session id in two transcript folders: two sessions, and a call both files hold counts once, for the older file;
  - a skill listed twice in a session: the first listing that names it says whether its description is cut;
  - records with no time, a time that has no Kyiv day, tool calls of another form, a journal line whose project is no
    path, and sessions none of which starts with a skill listing: counted and said, nothing raised.
"""
import contextlib
import io
import json
import os
from datetime import datetime

from claude_metrics import packs, packs_report, packs_scan
from claude_metrics.patterns import KYIV
from metrics_packs_checks import CATALOG, TODAY, at, calls, day, journal_line, listing, put, rec, session, tool

WARN = "  WARN: library: "
SOLO = (("beta:solo", "solo skill"),)


def home_of(tmp, name, catalog=True):
    """(home, projects folder, the project folder app) of a new made-up home, with the catalog or without."""
    root = os.path.join(tmp, name)
    home, work = os.path.join(root, ".claude"), os.path.join(root, "work")
    os.makedirs(os.path.join(home, "projects"))
    if catalog:
        put(os.path.join(home, "packs", "catalog.json"), json.dumps(CATALOG))
    return home, work, os.path.join(work, "app")


def aged(path, ago):
    """Set the time a transcript was last written to: noon of the Kyiv day `ago` days back."""
    then = datetime.combine(day(ago), datetime.min.time(), KYIV).timestamp() + 43200
    os.utime(path, (then, then))


def warns(home, work, enabled):
    """The WARNs of doctor, without their prefix."""
    lines = packs_report.doctor_lines(packs.collect(home, work, 60, TODAY, enabled), "J")
    return [ln[len(WARN):] for ln in lines if ln.startswith(WARN)]


def printed(data):
    shown = io.StringIO()
    with contextlib.redirect_stdout(shown):
        packs_report.print_report(data)
    return shown.getvalue()


def bare_checks(check, tmp):
    home, work, app = home_of(tmp, "packs-bare", catalog=False)
    data = packs.collect(home, work, 60, TODAY)
    check("packs: a home with no library: nothing, and no note", (data["catalog"], data["catalog_note"], data["pairs"],
                                                                   data["fill"], data["reviews"]) == (False, None, [], [], []), str(data))
    check("packs: a home with no library: the report says so", "Бібліотеки паків тут немає" in printed(data), printed(data))
    journal = os.path.join(home, "state", "packs.jsonl")
    put(journal, journal_line(10, app, "beta", "enable"))
    data = packs.collect(home, work, 60, TODAY)
    check("packs: no transcript at all: the first 30 days are not covered, and the report says there are none",
          [p["first_days"]["covered"] for p in data["pairs"]] == [False]
          and "увага: транскриптів не знайдено" in printed(data), printed(data))
    none = "no transcript under the projects folder of the home of Claude Code: nothing is known of the use of the packs that are on"
    check("doctor: no transcript at all and a pack on: a WARN; with no pack on, none",
          none in warns(home, work, {(app, "beta")}) and none not in warns(home, work, set()), str(warns(home, work, {(app, "beta")})))
    os.remove(journal)
    os.makedirs(journal)
    text = printed(packs.collect(home, work, 60, TODAY))
    check("packs: a journal that does not open and nothing else: said, not passed for no library",
          "увага: журнал claude-pack не відкрився (IsADirectoryError)" in text and "Бібліотеки паків тут немає" not in text, text)
    path = os.path.join(home, "packs", "catalog.json")
    put(path, json.dumps({"schema": 2, "catalog": "library", "packs": []}))
    check("packs: a catalog of another schema is named", packs.collect(home, "/w", 60, TODAY)["catalog_note"] == "another catalog")
    put(path, "{")
    check("packs: a catalog that is no JSON is named", packs.collect(home, "/w", 60, TODAY)["catalog_note"] == "JSONDecodeError")


def young_checks(check, tmp):
    home, work, app = home_of(tmp, "packs-young")
    put(os.path.join(home, "state", "packs.jsonl"), journal_line(90, app, "beta", "enable"))
    path = session(home, "-work-app", "y1", [listing("y1", 0, at(2), app, SOLO),
                                             calls("y1", 1, at(2, 1), app, tool("Edit", "y1-e1", file_path=app + "/a.py"))])
    aged(path, 2)
    check("doctor: transcripts that start later than the window: no call is not judged",
          [ln for ln in warns(home, work, {(app, "beta")}) if "no call" in ln] == [
              'the transcripts start on %s, later than the 60 days: "no call in 60 days" is not judged' % day(2)])
    put(os.path.join(home, "packs", "catalog.json"), json.dumps(dict(CATALOG, packs=[])))
    data = packs.collect(home, work, 60, TODAY, {(app, "beta")})
    check("packs: a catalog with no packs: a pack it does not name is not on", data["catalog"]
          and [(p["pack"], p["on"]) for p in data["pairs"]] == [("beta", False)], str(data["pairs"]))
    put(os.path.join(home, "packs", "catalog.json"), "{")
    data = packs.collect(home, work, 60, TODAY, {(app, "beta")})
    check("packs: a catalog that does not read: the packs that are on stay on", data["catalog_note"] == "JSONDecodeError"
          and [(p["pack"], p["on"]) for p in data["pairs"]] == [("beta", True)], str(data["pairs"]))


def idle_checks(check, tmp):
    home, work, app = home_of(tmp, "packs-idle")
    session(home, "-work-app", "y1", [listing("y1", 0, at(2), app, SOLO),
                                      calls("y1", 1, at(2, 1), app, tool("Edit", "y1-e1", file_path=app + "/a.py"))])
    aged(session(home, "-work-app", "y0", [calls("y0", 0, at(70), app, tool("Edit", "y0-e1", file_path=app + "/o.py"))]), 70)

    def said(*journal):
        put(os.path.join(home, "state", "packs.jsonl"), "".join(journal))
        return warns(home, work, {(app, "beta")})
    idle = "no call in 60 days: beta in 1 (app: on since %s, 1 session(s) with an edit)"
    got = said(journal_line(60, app, "beta", "enable"))
    check("doctor: on for 60 days, a work session, no call: the WARN", [ln for ln in got if ln.startswith(idle % day(60))], str(got))
    got = said(journal_line(59, app, "beta", "enable"))
    check("doctor: on for 59 days: no WARN yet", not [ln for ln in got if "no call" in ln], str(got))
    got = said(journal_line(100, app, "beta", "enable"), journal_line(50, app, "beta", "disable"), journal_line(3, app, "beta", "enable"))
    check("doctor: turned off and on again 3 days ago: the days of no call start anew, the reviews count from the first enable",
          not [ln for ln in got if "no call" in ln]
          and [ln for ln in got if ln.startswith("pack beta: 100 days since its first enable (%s, app)" % day(100))], str(got))
    got = said(journal_line(100, app, "beta", "enable"), journal_line(50, app, "beta", "disable"))
    check("doctor: on by the settings after the journal turned it off: named, no call is not judged",
          [ln for ln in got if ln.startswith("on, and the last line of the journal does not say so") and "beta in 1 (app)" in ln]
          and not [ln for ln in got if ln.startswith("no call")], str(got))


def twin_checks(check, tmp):
    home, work, app = home_of(tmp, "packs-twins")
    put(os.path.join(home, "state", "packs.jsonl"), journal_line(10, app, "beta", "enable"))
    first = [listing("t1", 0, at(4), app, SOLO),
             calls("t1", 1, at(4, 1), app, tool("Edit", "t1-e1", file_path=app + "/a.py"), tool("Skill", "t1-s1", skill="beta:solo"))]
    # the older file lies in the folder that sorts last: the order of reading is by time, not by name
    aged(session(home, "-work-zed", "t1", first), 4)
    aged(session(home, "-work-app", "t1", first + [calls("t1", 5, at(3), app, tool("Write", "t1-e2", file_path=app + "/b.py"))]), 3)
    start = datetime.combine(day(59), datetime.min.time(), KYIV)
    sessions, stats = packs_scan.scan_packs(home, start, {"beta"}, {})
    got = {key: (len(s.calls), sorted(s.edit_days)) for key, s in sessions.items()}
    check("packs: one session id in two transcript folders: two sessions, what both hold counts for the older file",
          got == {("-work-zed", "t1"): (1, [day(4)]), ("-work-app", "t1"): (0, [day(3)])} and stats["sessions"] == 2, str(got))
    data = packs.collect(home, work, 60, TODAY)
    row = data["pairs"][0] if data["pairs"] else {}
    check("packs: one session id in two transcript folders: the pair has both sessions, the call once",
          tuple(row.get(k) for k in ("sessions", "work", "called", "calls_total")) == (2, 2, 1, 1) and data["work_sessions"] == 2,
          str(data["pairs"]))


def relist_checks(check, tmp):
    home, work, app = home_of(tmp, "packs-re[l]ist*")   # a home whose name reads as a pattern: found all the same
    put(os.path.join(home, "state", "packs.jsonl"), journal_line(10, app, "beta", "enable"))
    edit = tool("Edit", "r-e1", file_path=app + "/a.py")
    bare, said = (("beta:solo", None),), listing("r2", 2, at(4, 2), app, (("beta:solo", None),), initial=False)
    session(home, "-work-app", "r1", [listing("r1", 0, at(2), app, bare), calls("r1", 1, at(2, 1), app, edit),
                                      listing("r1", 2, at(2, 2), app, SOLO, initial=False)])
    session(home, "-work-app", "r2", [listing("r2", 0, at(4), app, SOLO), said])
    data = packs.collect(home, work, 60, TODAY)
    row = data["pairs"][0] if data["pairs"] else {}
    check("packs: a description is cut when the first listing that names the skill says so, whatever a later one repeats",
          (row.get("sessions"), row.get("cut_sessions")) == (2, 1) and [f["cut"] for f in data["fill"]] == [1], str((row, data["fill"])))


def form_checks(check, tmp):
    home, work, app = home_of(tmp, "packs-formless")
    put(os.path.join(home, "state", "packs.jsonl"), journal_line(10, app, "beta", "enable")
        + json.dumps({"ts": at(9), "project": "/w/a\x00b", "pack": "beta", "action": "enable"}) + "\n")
    session(home, "-work-app", "q1", [
        listing("q1", 0, None, app, SOLO),                                                                 # no time
        rec("q1", 1, "user", None, app, message={"role": "user", "content": "<command-name>/beta:solo</command-name>"}),   # no time
        dict(rec("q1", 5, "user", at(2, 2), app, message={"role": "user", "content": "<command-name>/beta:solo</command-name>"}),
             uuid=None),                                                                                   # a command with no id
        calls("q1", 2, "9999-12-31T23:59:59Z", app, tool("Edit", "q1-e1", file_path=app + "/a.py")),      # a time with no Kyiv day
        calls("q1", 3, at(2), app, tool("Skill", "q1-s1", skill=["beta:solo"]), tool("Skill", None, skill="beta:solo"),
              tool("Edit", "q1-e2", file_path=app + "/b.py")),                                             # no skill named; no id
        rec("q1", 4, "assistant", at(2, 1), app, message={"content": {"type": "tool_use", "name": "Edit"}})])   # no list of calls
    data = packs.collect(home, work, 60, TODAY, {(app, "beta")})
    scan = data["scan"]
    check("packs: records with no time and calls of another form are counted, not raised and not passed over",
          tuple(scan.get(k) for k in ("no_timestamp", "call_form_unknown", "sessions", "sessions_with_listing")) == (3, 4, 1, 0)
          and data["journal_bad"] == 1 and [(p["work"], p["calls_total"]) for p in data["pairs"]] == [(1, 0)], str((scan, data["pairs"])))
    got = [ln[len(WARN):] for ln in packs_report.doctor_lines(data, "J") if ln.startswith(WARN)]
    want = ("3 call(s), edit(s) or skill listing(s) of the transcripts have no time and 4 call(s) are of an unknown form "
            "(a transcript format change? Compare with docs/compat.md): they are not counted",
            "1 session(s) looked at and none starts with a skill listing (a transcript format change? Compare with "
            "docs/compat.md): the packs that are on in a session and the size of the skill lists are not known")
    check("doctor: no time, another form and no skill listing at all are each a WARN", all(w in got for w in want), "\n".join(got))
    text = printed(data)
    check("packs: the report says the same", "увага: викликів, правок і списків скілів без часу: 3, викликів незнайомої форми: 4" in text
          and "увага: сесій прочитано 1, і жодна не починається списком скілів" in text, text)


def packs_edge_checks(tmp, check):
    for checks in (bare_checks, young_checks, idle_checks, twin_checks, relist_checks, form_checks):
        checks(check, tmp)
