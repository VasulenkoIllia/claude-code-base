"""All metrics of a window of Kyiv days, from the accumulator."""
import statistics
from collections import Counter, defaultdict
from datetime import timedelta

from .asks import permission_summary
from .patterns import CONDITIONAL, LANG_KINDS, PRELOAD, PROJECT_PREFIX, WORKTREE_SUFFIX


def days_between(a, b):
    return [a + timedelta(days=i) for i in range((b - a).days + 1)]


def startup_by_project(starts):
    """[project, sessions, median context of the first request] of (day, context, project dir), most sessions first;
    a worktree of a project is that project."""
    by_name = defaultdict(list)
    for _day, context, project in starts:
        by_name[WORKTREE_SUFFIX.sub("", PROJECT_PREFIX.sub("", project))].append(context)
    rows = [[name, len(c), statistics.median(c)] for name, c in by_name.items()]
    return sorted(rows, key=lambda r: (-r[1], r[0]))


def summarize(acc, a, b):
    """All metrics of the Kyiv days a..b (inclusive)."""
    window = days_between(a, b)  # in date order: float sums come out the same on every run, whatever the hash seed
    days = set(window)
    n = Counter()
    for day in window:
        n.update(acc.n.get(day, {}))
    active = sum(1 for day in window if acc.n.get(day, {}).get("P"))
    ctx = [c for day in window for c in acc.ctx.get(day, [])]
    pre = [p for day in window for p in acc.pre.get(day, [])]
    starts = [s for s in acc.startup if s[0] in days]
    first = [s[1] for s in starts]
    ui = [k for k in acc.ui_days if k[1] in days]
    per_day = lambda k: n[k] / active if active else None
    per_100p = lambda k: 100 * n[k] / n["P"] if n["P"] else None
    pct = lambda x, y: 100 * x / y if y else None
    weighted = n["main_weighted"] + n["sub_weighted"]
    asks = [(kind, seconds, (sid, day)) for day in window for kind, seconds, sid in acc.perm.get(day, [])]
    return {
        "window": f"{a}..{b}",
        "P": n["P"], "active_days": active, "P_per_day": per_day("P"),
        "requests_per_day": per_day("main_requests"),
        "ctx_mean": statistics.mean(ctx) if ctx else None, "ctx_median": statistics.median(ctx) if ctx else None,
        "ctx_over_400k_pct": pct(sum(1 for c in ctx if c > 400000), len(ctx)),
        "ctx_over_500k_pct": pct(sum(1 for c in ctx if c > 500000), len(ctx)),
        "output_per_request": n["main_output"] / n["main_requests"] if n["main_requests"] else None,
        "weighted_per_P_m": weighted / n["P"] / 1e6 if n["P"] else None,
        "sub_weighted_pct": pct(n["sub_weighted"], weighted),
        "compactions": n["compact_auto"] + n["compact_manual"], "compactions_per_100P": (
            100 * (n["compact_auto"] + n["compact_manual"]) / n["P"] if n["P"] else None),
        "compact_pre_median": statistics.median(pre) if pre else None,
        "startup_median": statistics.median(first) if first else None, "startup_n": len(first),
        "startup_by_project": startup_by_project(starts),
        "lang_en_pct": pct(sum(n["lang_en:" + k] for k in LANG_KINDS), sum(n["lang:" + k] for k in LANG_KINDS)),
        "lang_compact_en_pct": pct(n["lang_compact_en"], n["lang_compact"]),
        **{"lang:" + k: f"{n['lang_en:' + k]}/{n['lang:' + k]}" for k in LANG_KINDS},
        "idle_per_day": per_day("idle"), "idle_write_m": n["idle_write"] / 1e6,
        "simplify_per_day": per_day("simplify"), "simplify_per_100P": per_100p("simplify"),
        "simplify_audit_per_day": per_day("simplify_audit"),
        "redo_strict": n["redo_strict"], "redo_candidates": n["redo_candidates"], "done_candidates": n["done_candidates"],
        "browser_per_day": per_day("browser"), "screenshots_per_day": per_day("screenshots"),
        "browser_error_pct": pct(n["browser_errors"], n["browser"]),
        "ui_days": len(ui), "ui_narrow_pct": pct(sum(1 for k in ui if k in acc.narrow_days), len(ui)),
        "hook_blocks": n["hook_blocks"], "hook_asks": n["hook_asks"], "hook_asks_per_day": per_day("hook_asks"),
        "perm_seen": n["perm_seen"], **permission_summary(asks, active if n["perm_seen"] else 0),
        "sleep_per_day": per_day("sleep"), "sleep_fg_per_day": per_day("sleep_fg"),
        "module_missing_per_day": per_day("module_missing"), "py_crash_per_day": per_day("py_crash"),
        "skill_calls": n["skill"] + n["skill_slash"], "agent_calls": n["agent"], "reviewer_calls": n["reviewer"],
        "workflow_calls": n["workflow"], "workflow_agents": n["workflow_agents"], "paste_skipped": n["paste_skipped"],
        "react_cov": f"{n['react_cov']}/{n['react_need']}", "db_cov": f"{n['db_cov']}/{n['db_need']}",
        "prisma_errors": n["prisma_errors"], "prisma_resolve": n["prisma_resolve"],
        "preload_cov": f"{sum(n['preload_cov:' + a] for a in PRELOAD)}/{sum(n['preload_need:' + a] for a in PRELOAD)}",
        **{"preload_cov:" + a: f"{n['preload_cov:' + a]}/{n['preload_need:' + a]}" for a in PRELOAD},
        "cond_shown": f"{sum(n['shown_used:' + s] for s in CONDITIONAL)}/{sum(n['shown:' + s] for s in CONDITIONAL)}",
        **{"cond_shown:" + s: f"{n['shown_used:' + s]}/{n['shown:' + s]}" for s in CONDITIONAL},
        **{"skill_calls:" + s: n["skill:" + s] for s in CONDITIONAL},
        "dup_guard": n["dup_guard"], "dup_guard_per_day": per_day("dup_guard"),
        "push_commits": n["push_commits"], "push_lines": n["push_lines"],
        "cost_per_commit_m": n["push_weighted"] / n["push_commits"] / 1e6 if n["push_commits"] else None,
        "cost_per_100_lines_m": 100 * n["push_weighted"] / n["push_lines"] / 1e6 if n["push_lines"] else None,
        "no_push_weighted_pct": pct(n["nopush_weighted"], weighted) if n["push_commits"] else None,
    }
