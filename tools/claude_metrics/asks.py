"""Real permission prompts: what the owner had to answer, read from permissionDecision on the result of a tool call
(the field exists from 2026-10-08), by kind, with the time from the call to its result. The transcript has no time of
the answer, so a command's own run is in that time. hook_asks counts only what a hook asked."""
import statistics
from collections import Counter, defaultdict

from .patterns import (MERGE_CALL, NO_PERMISSION, PERM_KINDS, PERM_SOURCES, PUSH_CALL, SERVER_DAY_MAX, SSH_CALL,
                       SSH_WRITE, WAIT_LONG_S)
from .transcript import STATS, kday


def prompted(decision):
    """The owner was asked. user_permanent with reasonType rule is a rule saved earlier, no prompt; a prompt that closed
    on an error (permissionStreamClosed) lost its call."""
    source = decision.get("source")
    return (source in ("user_temporary", "user_reject") or source == "user_permanent" and decision.get("reasonType") != "rule"
            or decision.get("reasonCode") == "permissionStreamClosed")


def call_kind(cmd):
    """The kind of a shell call by the ask rules of the base; a read over ssh is any without a word that changes the
    server, so a script it runs from a file counts as a read."""
    if MERGE_CALL.search(cmd):
        return "merge"
    if PUSH_CALL.search(cmd):
        return "push"
    if SSH_CALL.search(cmd):
        return "ssh_write" if SSH_WRITE.search(cmd) else "ssh_read"
    return "other"


def note_permission(acc, record, block, ts):
    """The record of a tool result; the time of the answer is known only with the call, see permission_asks."""
    decision = record.get("permissionDecision")
    if decision is None:
        return
    if not isinstance(decision, dict):
        STATS["permission_not_object"] += 1
    elif ts:
        acc.add(kday(ts), "perm_seen")
        if decision.get("source") not in PERM_SOURCES:
            STATS["permission_source_unknown"] += 1
        if block.get("tool_use_id") and prompted(decision):
            acc.prompted[block["tool_use_id"]] = ts


def permission_asks(acc):
    """Once every call is known (parallel calls can write a result before its tool_use): day -> asks and acc.perm."""
    for tid, answered in acc.prompted.items():
        facts = acc.tools.get(tid)
        if not facts:
            STATS["permission_no_call"] += 1
        elif facts["name"] not in NO_PERMISSION:
            kind = "guard" if tid in acc.asks_seen else facts.get("ask_kind", "other")
            acc.perm[facts["day"]].append((kind, max(0.0, (answered - facts["ts"]).total_seconds()), facts["sid"]))


def permission_summary(asks, active):
    """The numbers of a window from (kind, seconds, session day) of its asks; active: its active days."""
    by_kind = defaultdict(list)
    per_day, server = Counter(), set()
    for kind, seconds, session_day in asks:
        by_kind[kind].append(seconds)
        per_day[session_day] += 1
        if kind in ("ssh_read", "ssh_write"):
            server.add(session_day)
    counts = [per_day[k] for k in server]
    waits = [s for _, s, _ in asks]
    return {
        "perm_asks": len(asks), "perm_asks_per_day": len(asks) / active if active else None,
        "perm_wait_h": sum(waits) / 3600, "perm_long_waits": sum(1 for s in waits if s > WAIT_LONG_S),
        "perm_rows": [[k, len(v), statistics.median(v), max(v), sum(1 for s in v if s > WAIT_LONG_S)]
                      for k, v in ((k, by_kind[k]) for k in PERM_KINDS) if v],
        "perm_server_days": len(counts), "perm_server_median": statistics.median(counts) if counts else None,
        "perm_server_max": max(counts, default=None), "perm_server_over": sum(1 for c in counts if c > SERVER_DAY_MAX),
    }
