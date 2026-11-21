"""What claude-metrics --packs reads besides the transcripts (ADR-007, the feedback of L4), read-only.

The catalog (<home>/packs/catalog.json) names the packs, their skills and their file signals. The journal
(<home>/state/packs.jsonl, written by claude-pack) dates the enables of a pack in a project and records the reviews of
a pack. A catalog or a journal that is there and does not read, and a journal line of another form, are named to the
caller, never passed for "nothing there".
"""
import json
import os
import re

from .transcript import parse_ts

CATALOG = "library"
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")       # a pack, as claude-pack names one
ACTIONS = ("enable", "disable", "decline", "review")
REVIEW_DAYS = (30, 60)                                # owner's decision Б8: a review 30 and 60 days after the first enable


def read_catalog(home):
    """({pack: {"skills": {name: it has a description}, "files": the file signals}}, None), (None, None) with no
    catalog in the home, (None, why) for one that is there and does not read."""
    path = os.path.join(home, "packs", "catalog.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError) as e:
        return None, type(e).__name__
    try:
        if data["schema"] != 1 or data["catalog"] != CATALOG:
            return None, "another catalog"
        packs = {}
        for p in data["packs"]:
            signals = p.get("signals") or {}
            named, deps = signals.get("filesRead") or [], signals.get("manifestDeps") or []
            if not isinstance(named, list) or not isinstance(deps, list):   # a text would be read letter by letter
                return None, "a pack of another form"
            files = named + [d["file"] for d in deps]
            if not NAME.match(p["name"]) or not all(isinstance(f, str) for f in files):
                return None, "a pack of another form"
            packs[p["name"]] = {"skills": {s["name"]: bool(s.get("desc_chars")) for s in p.get("skills") or []},
                                "files": files}
    except (AttributeError, KeyError, TypeError):
        return None, "a catalog of another form"
    return packs, None


def when(value):
    """The time a record or a journal line gives; None for no time and for a year that is not of this century (the
    last day of the year 9999 has no Kyiv day, and one such record would stop the whole scan)."""
    ts = parse_ts(value)
    return ts if ts and 2000 <= ts.year < 2100 else None


def journal_row(line):
    """(time, project folder or None, pack, action, day of a review or None) of a journal line, None for another form."""
    try:
        d = json.loads(line)
    except ValueError:
        return None
    if not isinstance(d, dict):
        return None
    ts, project, pack, action, day = when(d.get("ts")), d.get("project"), d.get("pack"), d.get("action"), d.get("day")
    known = ts and isinstance(pack, str) and NAME.match(pack) and action in ACTIONS
    if not known or not (project is None or isinstance(project, str)):
        return None
    if action == "review":
        return (ts, None, pack, action, day) if type(day) is int and day in REVIEW_DAYS else None
    try:
        return (ts, os.path.realpath(project), pack, action, None) if project else None
    except ValueError:   # a NUL in the name: no folder
        return None


def read_journal(home):
    """(the rows of the journal in its order, lines of another form, why a journal that is there did not open or None)."""
    path = os.path.join(home, "state", "packs.jsonl")
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    except FileNotFoundError:
        return [], 0, None
    except OSError as e:
        return [], 0, type(e).__name__
    rows = [journal_row(ln) for ln in lines]
    return [r for r in rows if r], sum(1 for r in rows if r is None), None
