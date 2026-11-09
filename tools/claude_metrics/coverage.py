"""Reviewer and skill coverage, worked out from the per-session events once every transcript is read."""
from .patterns import LIGHT_LINES, PRELOAD
from .transcript import STATS, kday


def coverage(acc):
    """Commits that needed react-reviewer or database-reviewer since the previous commit of the session.

    A Light commit (at most LIGHT_LINES changed lines, as printed by git) needs no react-reviewer and is left out
    of the react rows; a DB change is never Light, so DB rows count every commit. A commit whose size was not
    printed (git commit -q) counts as not Light; the footer shows how many (commit_size_unknown)."""
    for events in acc.events.values():
        react = db = react_rev = db_rev = False
        for ts, kind, value in sorted(events, key=lambda e: e[0]):
            if kind == "react_edit":
                react = True
            elif kind == "db_edit":
                db = True
            elif kind == "agent":  # a plugin prefix ("x:react-reviewer") counts too
                react_rev = react_rev or value.rsplit(":", 1)[-1] == "react-reviewer"
                db_rev = db_rev or value.rsplit(":", 1)[-1] == "database-reviewer"
            elif kind == "commit" and acc.commit_ok.get(value):
                day = kday(ts)
                size = acc.commit_size.get(value)
                STATS["commit_size_unknown" if size is None else "commit_size_known"] += 1
                if react and not (size is not None and size <= LIGHT_LINES):
                    acc.add(day, "react_need")
                    acc.add(day, "react_cov", int(react_rev))
                if db:
                    acc.add(day, "db_need")
                    acc.add(day, "db_cov", int(db_rev))
                react = db = react_rev = db_rev = False


def skill_coverage(acc):
    """PRELOAD runs whose transcript got the agent's skill; sessions with a CONDITIONAL skill listed mid-session, and of
    them those with a Skill call for it afterwards (both counted on the run's or the first listing's day)."""
    for tid, (day, agent) in acc.preload_runs.items():
        if tid not in acc.preloaded:
            STATS["preload_run_no_transcript"] += 1  # no <agent>.meta.json names this run: counted as not preloaded
        acc.add(day, "preload_need:" + agent)
        acc.add(day, "preload_cov:" + agent, int(PRELOAD[agent] in acc.preloaded.get(tid, ())))
    for events in acc.events.values():
        shown = {}  # skill -> day of its first listing in the session; None once a Skill call followed
        for ts, kind, value in sorted(events, key=lambda e: e[0]):
            if kind == "shown" and value not in shown:
                shown[value] = kday(ts)
                acc.add(shown[value], "shown:" + value)
            elif kind == "skill" and shown.get(value):
                acc.add(shown[value], "shown_used:" + value)
                shown[value] = None
