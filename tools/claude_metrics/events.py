"""What one transcript entry adds to the scan: the accumulator, request usage, tool calls and their results, typed
prompts, hook output."""
from collections import Counter, defaultdict

from .asks import call_kind
from .patterns import (BROWSER, BROWSER_LIKE, BUG, COMMIT_CALL, CONDITIONAL, DB_FILE, DONE_CLAIM, EDIT_TOOLS, HOOK_ASK,
                       HOOK_BLOCK, MODULE_MISSING, PASTE, PASTED_LABEL, PRELOAD, PRISMA_ERROR, PRISMA_RESOLVE, PY_CRASH,
                       PY_RUN, REACT_FILE, REDO_BROAD, REDO_STRICT, RESULT_TEXT_MAX, REWORK, SHELL_TOOLS, SIMPLIFY,
                       SIMPLIFY_AUDIT, SLEEP, UI_FILE, WEIGHTS)
from .transcript import STATS, commit_size, kday, text_of


class Acc:
    """Everything the scan collects, keyed by Kyiv day so any window can be summarised afterwards."""

    def __init__(self):
        self.n = defaultdict(Counter)          # day -> counter name -> count
        self.ctx = defaultdict(list)           # day -> context of each main request
        self.pre = defaultdict(list)           # day -> preTokens of auto compactions
        self.startup = []                      # (day, context of a session's first request, project dir)
        self.ui_days = set()                   # (project dir, day) with UI edits
        self.narrow_days = set()               # (project dir, day) with a browser check narrower than 900px
        self.skill_last = {}                   # skill -> last day used
        self.events = defaultdict(list)        # session -> (ts, kind, value) for reviewer coverage
        self.commit_ok = {}                    # tool_use id of a git commit -> result was not an error
        self.commit_size = {}                  # tool_use id of a git commit -> changed lines (None: not printed, e.g. -q)
        self.candidates = []                   # (day, ts, session, kind, matched)
        self.tools = {}                        # tool_use id -> facts needed when its result arrives
        self.results_seen = set()
        self.pending = {}                      # tool_use id -> result written before its tool_use (parallel calls)
        self.asks_seen = set()
        self.prompted = {}                     # tool_use id of a call the owner was asked about -> time of its result
        self.perm = defaultdict(list)          # day -> (kind, seconds to the result, session) of each real ask (asks.py)
        self.dup_seen = set()                  # tool_use ids with a dup-guard hint
        self.preload_runs = {}                 # tool_use id of a PRELOAD agent run -> (day, agent)
        self.preloaded = {}                    # toolUseId of a subagent transcript -> skills preloaded there
        self.first_day = None                  # oldest Kyiv day in the transcripts: older days were cleaned up
        self.session_cost = defaultdict(Counter)  # main session -> day -> weighted cost, its subagents included
        self.cwds = {}                         # main session -> working folders (pushes.py)
        self.commit_calls = {}                 # tool_use id of a git commit call -> [session, start, end, folders]
        self.early_results = {}                # tool_use id -> time of a result written before its tool_use

    def saw(self, ts):
        if ts and (self.first_day is None or kday(ts) < self.first_day):
            self.first_day = kday(ts)

    def add(self, day, name, value=1):
        self.n[day][name] += value


def add_usage(acc, day, usage, prefix, sid):
    write = usage.get("cache_creation_input_tokens") or 0
    split = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
    w5, w1 = split.get("ephemeral_5m_input_tokens") or 0, split.get("ephemeral_1h_input_tokens") or 0
    if w5 + w1 != write:  # no split recorded: the audit counted writes at the 1 h price
        w5, w1 = 0, write
    weighted = (WEIGHTS["input"] * (usage.get("input_tokens") or 0) + WEIGHTS["read"] * (usage.get("cache_read_input_tokens") or 0)
                + WEIGHTS["write_5m"] * w5 + WEIGHTS["write_1h"] * w1 + WEIGHTS["output"] * (usage.get("output_tokens") or 0))
    acc.add(day, prefix + "weighted", weighted)
    acc.session_cost[sid][day] += weighted
    acc.add(day, prefix + "requests")
    acc.add(day, prefix + "output", usage.get("output_tokens") or 0)


def register_tool(acc, block, ts, project, sid, main):
    tid = block.get("id")
    if not tid or tid in acc.tools:
        return
    name = block.get("name") or ""
    inp = block.get("input") if isinstance(block.get("input"), dict) else {}
    day = kday(ts)
    facts = {"name": name, "day": day, "project": project, "ts": ts, "sid": sid}
    acc.tools[tid] = facts
    if name in SHELL_TOOLS:
        facts["ask_kind"] = call_kind(str(inp.get("command") or ""))
    if BROWSER_LIKE.search(name) and not name.startswith(BROWSER):
        STATS["browser_like_not_counted"] += 1  # a new browser MCP: add its prefix to BROWSER
    if name == "Bash":
        cmd = str(inp.get("command") or "")
        facts["py"] = bool(PY_RUN.search(cmd))
        if SLEEP.search(cmd):
            acc.add(day, "sleep")
            if not inp.get("run_in_background"):
                acc.add(day, "sleep_fg")
        if PRISMA_RESOLVE.search(cmd):
            acc.add(day, "prisma_resolve")
        if main and COMMIT_CALL.search(cmd):
            facts["commit"] = True
            acc.events[sid].append((ts, "commit", tid))
    elif name in EDIT_TOOLS:
        path = str(inp.get("file_path") or "")
        if UI_FILE.search(path):
            acc.ui_days.add((project, day))
        if REACT_FILE.search(path):
            acc.events[sid].append((ts, "react_edit", None))
        if DB_FILE.search(path):
            acc.events[sid].append((ts, "db_edit", None))
    elif name.startswith(BROWSER):
        facts["browser"] = True
        acc.add(day, "browser")
        actions = [{"name": name, "input": inp}]
        if name.endswith("browser_batch"):
            actions = [a for a in inp.get("actions") or [] if isinstance(a, dict)]
        for a in actions:
            a_inp = a.get("input") if isinstance(a.get("input"), dict) else {}
            if "resize" in str(a.get("name") or ""):
                width = a_inp.get("width")
                if (isinstance(width, (int, float)) and width < 900) or a_inp.get("preset") in ("mobile", "tablet"):
                    acc.narrow_days.add((project, day))
    elif name == "Skill":
        skill = str(inp.get("skill") or inp.get("name") or "?")
        acc.add(day, "skill")
        acc.add(day, "skill:" + skill)
        acc.skill_last[skill] = max(acc.skill_last.get(skill, day), day)
        acc.events[sid].append((ts, "skill", skill.rsplit(":", 1)[-1]))
    elif name in ("Agent", "Task"):
        kind = str(inp.get("subagent_type") or "general-purpose")
        acc.add(day, "agent")
        acc.add(day, "agent:" + kind)
        if "review" in kind or "hunter" in kind:
            acc.add(day, "reviewer")
        acc.events[sid].append((ts, "agent", kind))
        if kind.rsplit(":", 1)[-1] in PRELOAD:
            acc.preload_runs[tid] = (day, kind.rsplit(":", 1)[-1])
    elif name == "Workflow":
        acc.add(day, "workflow")
    late = acc.pending.pop(tid, None)
    if late is not None:
        handle_result(acc, late)


def handle_result(acc, block):
    tid = block.get("tool_use_id")
    if not tid or tid in acc.results_seen:
        return
    facts = acc.tools.get(tid)
    if not facts:  # parallel calls can write a result a few lines before its tool_use
        acc.pending[tid] = block
        return
    acc.results_seen.add(tid)
    day, error, content = facts["day"], bool(block.get("is_error")), block.get("content")
    text = text_of(content)[:RESULT_TEXT_MAX]
    if text.startswith("<persisted-output>"):
        STATS["results_preview_only"] += 1  # the full text sits in tool-results/*.txt, not read here
    if facts.get("browser"):
        if isinstance(content, list):
            acc.add(day, "screenshots", sum(1 for b in content if isinstance(b, dict) and b.get("type") == "image"))
        if error:
            acc.add(day, "browser_errors")
    if error and HOOK_BLOCK.match(text):
        acc.add(day, "hook_blocks")
    if facts["name"] == "Bash":
        if MODULE_MISSING.search(text):
            acc.add(day, "module_missing")
        if facts.get("py") and PY_CRASH.search(text):
            acc.add(day, "py_crash")
        if PRISMA_ERROR.search(text):
            acc.add(day, "prisma_errors")
        if facts.get("commit"):
            acc.commit_ok[tid] = not error
            acc.commit_size[tid] = commit_size(text)


def count_prompt(acc, text, ts, sid, last_text, seen):
    """A prompt by its prompt_text: pasted blocks come as labels, a prompt of images only as "[картинка]"."""
    key = (ts.isoformat(), text[:200])
    if key in seen:
        return
    seen.add(key)
    day = kday(ts)
    acc.add(day, "P")
    if PASTE.search(text[:3000]) or PASTED_LABEL.match(text):
        acc.add(day, "paste_skipped")
        return
    text = PASTED_LABEL.sub(" ", text)  # typed words only: the size in "[вставлено 500 симв.]" is no HTTP 500
    if SIMPLIFY.search(text[:1500]):
        acc.add(day, "simplify")
    if SIMPLIFY_AUDIT.search(text[:4000]):
        acc.add(day, "simplify_audit")
    strict = REDO_STRICT.search(text[:1500])
    if strict:
        acc.add(day, "redo_strict")
    broad = REDO_BROAD.search(text[:1500])
    if broad:
        acc.add(day, "redo_candidates")
        acc.candidates.append((day, ts, sid, "redo" + (" (strict)" if strict else ""), broad.group(0)))
    issue = BUG.search(text[:4000]) or REWORK.search(text[:4000])
    if issue and DONE_CLAIM.search(last_text):
        acc.add(day, "done_candidates")
        acc.candidates.append((day, ts, sid, "done-then-bug", issue.group(0)))


def hook_ask(acc, att, ts):
    """A PreToolUse hook answered "ask": once per tool call, in main and subagent transcripts."""
    if HOOK_ASK.search(str(att.get("stdout") or "")):
        key = att.get("toolUseID") or ts.isoformat()
        if key not in acc.asks_seen:
            acc.asks_seen.add(key)
            acc.add(kday(ts), "hook_asks")


def hook_context(acc, att, ts, sid):
    """dup-guard hints (once per tool call) and CONDITIONAL skills listed mid-session, in main and subagent transcripts."""
    if att.get("type") == "hook_additional_context":
        texts = att.get("content") if isinstance(att.get("content"), list) else [att.get("content")]
        key = att.get("toolUseID") or ts.isoformat()
        if key not in acc.dup_seen and any(str(t).startswith("dup-guard:") for t in texts):
            acc.dup_seen.add(key)
            acc.add(kday(ts), "dup_guard")
    elif att.get("type") == "skill_listing" and att.get("isInitial") is False:
        for skill in (str(n).rsplit(":", 1)[-1] for n in att.get("names") or []):
            if skill in CONDITIONAL:
                acc.events[sid].append((ts, "shown", skill))


def skill_used(acc, name, ts):
    acc.skill_last[name] = max(acc.skill_last.get(name, kday(ts)), kday(ts))
