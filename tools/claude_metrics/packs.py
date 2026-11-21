"""claude-metrics --packs (ADR-007, the feedback of L4): the use of the packs of the library, from the transcripts of
the window (claude_metrics/packs_scan.py), the journal of claude-pack and the catalog (packs_sources.py). Read-only.

A project is the folder a session runs in, taken up to a project folder the journal or doctor names, else to the
folder of --projects-dir it is in. A pack is on in a session whose skill listing names one of its skills, or that calls
one. A call of a pack is a Skill call or a slash command of its skill, or a run of its agent. A work session (owner's
decision 21.11.2026) is a main session with the pack on and an edit of a file, its subagents included, on a day of the
window. Per project and pack over the window: the sessions, the work sessions, those of them with a call and their
share, the calls by skill and agent, the day of the last one, the misses (only a pack with file signals has them: a
work session that edited a file a signal of the pack names and called nothing of the pack) and the sessions whose
listing left a skill of the pack with its bare name, the description cut. A pair with a first enable in the journal
also gets the share over its first FIRST_DAYS days (criterion 9 of the pilot); for that the scan starts at the oldest
such enable, up to MAX_DAYS back. Then: the packs that are on and were not called; the size of the skill listing the
last session of each project started with, against LIST_LIMIT; the reviews of REVIEW_DAYS, counted from the first
enable of a pack in a project of --projects-dir and recorded by `claude-pack review`.

With --doctor (scripts/doctor.sh) the window is not widened, the pairs that are on come from the settings of the
projects (--enabled: lines `pack TAB project folder name`) and the output is the lines of doctor
(claude_metrics/packs_report.py). Without a catalog and a journal there is nothing to report, and the exit is 0.
"""
import json
import os
from collections import Counter
from datetime import datetime, time, timedelta

from .packs_report import doctor_lines, print_report
from .packs_scan import LIST_LIMIT, project_of, scan_packs
from .packs_sources import REVIEW_DAYS, read_catalog, read_journal
from .patterns import KYIV
from .transcript import kday

WINDOW_DAYS = 60   # ADR-007: a pack with no call in 60 days in a project is turned off there
FIRST_DAYS = 30    # criterion 9 of the pilot: the first 30 days after the first enable
MAX_DAYS = 180     # how far back transcripts are kept


def add_arguments(ap):
    ap.add_argument("--packs", action="store_true", help="the packs of the library: calls of their skills and agents by project")
    ap.add_argument("--days", type=int, default=WINDOW_DAYS, help="with --packs: the window in days (default %d)" % WINDOW_DAYS)
    ap.add_argument("--projects-dir", help="with --packs: the folder of the project folders (default $PROJECTS_DIR or ~/WebstormProjects)")
    ap.add_argument("--claude-home", help="with --packs: the home of Claude Code (default ~/.claude)")
    ap.add_argument("--doctor", action="store_true", help="with --packs: print the lines of scripts/doctor.sh")
    ap.add_argument("--enabled", help="with --doctor: a file of `pack TAB project folder name` lines, the packs that are on")
    ap.add_argument("--journal-shown", default="CLAUDE_HOME/state/packs.jsonl", help="with --doctor: how to name the journal")


def journal_facts(journal):
    """(the Kyiv day of the first enable of each (project, pack); the day its current time on began: the first enable
    after the last disable or decline; the last action of each; the recorded reviews by pack)."""
    since, began, state, recorded = {}, {}, {}, {}
    for ts, project, pack, action, day in journal:
        if action == "review":
            recorded.setdefault(pack, set()).add(day)
            continue
        pair = (project, pack)
        if action == "enable":
            since.setdefault(pair, kday(ts))
            if state.get(pair) != "enable":
                began[pair] = kday(ts)
        state[pair] = action
    return since, began, state, recorded


def use(sessions, pack, first, last, described):
    """What the sessions of one project that have the pack on say of it on the Kyiv days first..last."""
    out = {"sessions": 0, "work": 0, "called": 0, "misses": 0, "cut_sessions": 0, "cut_max": 0, "last_call": None}
    calls = Counter()
    for s in sessions:
        mine = [c for c in s.calls if c[1] == pack and first <= kday(c[0]) <= last]
        for ts, _, kind, name in mine:
            calls[(kind, name)] += 1
            out["last_call"] = max(out["last_call"] or kday(ts), kday(ts))
        days = [d for d in s.edit_days if first <= d <= last]
        if not (days or mine or (s.listing and first <= kday(s.listing[0]) <= last)):
            continue
        out["sessions"] += 1
        cut = sum(1 for skill, shown in s.on[pack].items() if shown is False and described.get(skill))
        out["cut_sessions"] += bool(cut)
        out["cut_max"] = max(out["cut_max"], cut)
        if days:
            out["work"] += 1
            out["called"] += bool(mine)
            out["misses"] += not mine and any(pack in s.signal_days.get(d, ()) for d in days)
    out["calls"] = {kind: {n: c for (k, n), c in sorted(calls.items()) if k == kind} for kind in ("skill", "slash", "agent")}
    out["calls_total"] = sum(calls.values())
    out["share_pct"] = round(100 * out["called"] / out["work"]) if out["work"] else None
    return out


def shown_name(project, projects_dir):
    """How a project folder is printed: its path under projects_dir, else its last part; printable characters only."""
    base = projects_dir.rstrip("/") + "/"
    name = project[len(base):] if project.startswith(base) else os.path.basename(project.rstrip("/")) or project
    return "".join(c if c.isprintable() else "?" for c in name)


def first_days(sessions, pack, day, today, read_from, oldest, described):
    """The use of a pack over the FIRST_DAYS days from its first enable on `day`; `covered` False when the transcripts
    read do not reach back to that day, or there are none (then the numbers are left out)."""
    last = day + timedelta(days=FIRST_DAYS - 1)
    out = {"first": day, "last": last, "complete": today > last, "covered": read_from <= day and oldest is not None and oldest <= day}
    if out["covered"]:
        got = use(sessions, pack, day, min(last, today), described)
        out.update(work=got["work"], called=got["called"], share_pct=got["share_pct"])
    return out


def fills(sessions, where, first, last, packs):
    """project -> the last initial skill listing of its sessions on the days first..last: its size against LIST_LIMIT
    and the pack skills it left with no description."""
    latest = {}
    for s in sessions.values():
        if s.listing and first <= kday(s.listing[0]) <= last:
            project = where[s.key]
            if project not in latest or s.listing[0] > latest[project].listing[0]:
                latest[project] = s
    out = {}
    for project, s in latest.items():
        cut = sum(1 for pack, skills in s.on.items() for skill, shown in skills.items()
                  if shown is False and packs.get(pack, {}).get("skills", {}).get(skill))
        out[project] = {"chars": s.listing[1], "skills": s.listing[2], "day": kday(s.listing[0]),
                        "pct": round(100 * s.listing[1] / LIST_LIMIT), "cut": cut}
    return out


def reviews(since, recorded, enabled, projects_dir, today):
    """Per pack that is on somewhere: the first enable in a project folder of projects_dir, the days since, and the
    reviews of REVIEW_DAYS that are due and not recorded."""
    first = {}
    for (project, pack), day in since.items():
        if os.path.dirname(project.rstrip("/")) == projects_dir.rstrip("/") and (pack not in first or day < first[pack][0]):
            first[pack] = (day, project)
    on = {pack for _, pack in enabled}
    out = []
    for pack, (day, project) in sorted(first.items()):
        if pack in on:
            days = (today - day).days
            done = recorded.get(pack, set())
            out.append({"pack": pack, "first_enable": day, "project": project, "name": shown_name(project, projects_dir),
                        "days": days, "recorded": sorted(done), "due": [d for d in REVIEW_DAYS if days >= d and d not in done]})
    return out


def collect(home, projects_dir, days, today, enabled=None):
    """Everything --packs reports, as one dict. enabled: the (project folder, pack) pairs doctor read from the
    settings of the projects; None: the pairs the journal leaves on, and the scan reaches back to their first enable."""
    catalog, catalog_note = read_catalog(home)
    journal, journal_bad, journal_note = read_journal(home)
    packs = catalog or {}
    since, began, state, recorded = journal_facts(journal)
    widen = enabled is None
    if widen:
        enabled = {pair for pair, action in state.items() if action == "enable"}
    enabled = {pair for pair in enabled if catalog is None or pair[1] in catalog}   # no catalog read: every pair stays
    first = today - timedelta(days=days - 1)
    starts = [since[pair] for pair in enabled if pair in since] if widen else []
    read_from = max(today - timedelta(days=MAX_DAYS), min([first] + starts))
    names = set(packs) | {row[2] for row in journal}
    roots = {project for project, _ in list(state) + list(enabled)}
    needed = {project for project, _ in enabled}   # doctor: only their sessions are read in full
    sessions, stats = scan_packs(home, datetime.combine(read_from, time.min, KYIV), names,
                                 {n: p["files"] for n, p in packs.items() if p["files"]},
                                 None if widen else lambda cwd: project_of(cwd, roots, projects_dir) in needed)
    where = {key: project_of(s.cwd, roots, projects_dir) or "?" + s.folder for key, s in sessions.items()}
    grouped = {}
    for key, s in sessions.items():
        for pack in s.on:
            grouped.setdefault((where[key], pack), []).append(s)
    pairs = []
    for project, pack in sorted(set(grouped) | enabled):
        described = packs.get(pack, {}).get("skills", {})
        got = use(grouped.get((project, pack), []), pack, first, today, described)
        if not got["sessions"] and (project, pack) not in enabled:
            continue   # on only in sessions before the window (the scan reached back for another pair)
        day = since.get((project, pack))
        row = dict(got, project=project, name=shown_name(project, projects_dir), pack=pack, on=(project, pack) in enabled,
                   enabled_since=day, on_since=began.get((project, pack)), journal_state=state.get((project, pack)),
                   has_signals=bool(packs.get(pack, {}).get("files")),
                   first_days=first_days(grouped.get((project, pack), []), pack, day, today, read_from,
                                         stats["oldest"], described) if day else None)
        pairs.append(row)
    fill = fills(sessions, where, first, today, packs)
    worked = {s.key for pair, found in grouped.items() if pair in enabled
              for s in found if any(first <= d <= today for d in s.edit_days)}   # a session with two packs on is one
    return {"window": {"first": first, "last": today, "days": days}, "read_from": read_from, "limit": LIST_LIMIT,
            "work_sessions": len(worked),
            "projects_dir": projects_dir.rstrip("/"),
            "catalog": catalog is not None, "catalog_note": catalog_note, "journal_lines": len(journal),
            "journal_bad": journal_bad, "journal_note": journal_note, "pairs": pairs,
            "fill": [dict(v, project=p, name=shown_name(p, projects_dir)) for p, v in sorted(fill.items())],
            "reviews": reviews(since, recorded, enabled, projects_dir, today), "scan": stats}


def enabled_pairs(path, projects_dir):
    """The (project folder, pack) pairs of doctor's file: lines `pack TAB project folder name`."""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError as e:
        raise SystemExit("--enabled: %s does not open (%s)" % (path, type(e).__name__)) from e
    pairs = set()
    for line in lines:
        pack, tab, name = line.partition("\t")
        if tab and pack and name:
            pairs.add((os.path.realpath(os.path.join(projects_dir, name)), pack))
    return pairs


def run(a):
    """The exit code of `claude-metrics --packs`."""
    if not 1 <= a.days <= MAX_DAYS:
        raise SystemExit("--days: from 1 to %d" % MAX_DAYS)
    home = os.path.realpath(a.claude_home or os.path.expanduser("~/.claude"))
    projects_dir = os.path.realpath(a.projects_dir or os.environ.get("PROJECTS_DIR") or os.path.expanduser("~/WebstormProjects"))
    today = datetime.now(KYIV).date()
    if a.doctor:
        if not a.enabled:
            raise SystemExit("--doctor needs --enabled <file>")
        data = collect(home, projects_dir, a.days, today, enabled_pairs(a.enabled, projects_dir))
        print("\n".join(doctor_lines(data, a.journal_shown)))
    elif a.json:
        print(json.dumps(collect(home, projects_dir, a.days, today), ensure_ascii=False, indent=1, default=str))
    else:
        print_report(collect(home, projects_dir, a.days, today))
    return 0
