"""The scan: every main transcript and its subagent and workflow transcripts, each entry once, into one accumulator."""
import glob
import json
import os

# the prompt rule of claude-time (its package next to this one): both tools count the same prompts, and read the
# uuid and sessionId of an entry alike
from time_register.transcript import UNKNOWN as PROMPT_UNKNOWN, fork_copy, prompt_text, record_id

from .asks import note_permission, permission_asks
from .coverage import coverage, skill_coverage
from .events import Acc, add_usage, count_prompt, handle_result, hook_ask, hook_context, register_tool, skill_used
from .language import note_language
from .patterns import COMMAND_NAME, EXCLUDED_DIRS, PRELOAD_MARK, PROJECTS, SKILLS_DIR
from .pushes import note_call, note_record, note_result
from .transcript import (STATS, attachment_of, compact_metadata_of, kday, message_of, parse_ts, pre_tokens_of,
                         read_jsonl, text_field, text_of, usage_of)


def scan_main(acc, path, project, known, seen, skills):
    sid = os.path.basename(path)[:-len(".jsonl")]
    forked = False
    last_text = ""          # last 1500 chars of the last assistant text block, for "done" claims
    requests = {}           # message id -> [first ts, model, usage with max values]
    prev = None             # (ts, context, model) of the previous request, for idle resumes
    compacted = False       # a compaction between the previous request and this one
    after_compact = False   # a compaction earlier in the session
    for d in read_jsonl(path):
        if fork_copy(d, sid, known):
            forked = True
            STATS["fork_entries"] += 1
            continue
        uid = record_id(d, "uuid", "uuid")
        if uid:
            if uid in seen["uuid"]:
                STATS["uuid_repeats"] += 1
                continue
            seen["uuid"].add(uid)
        note_record(acc, d, sid)
        kind, ts = d.get("type"), parse_ts(d.get("timestamp"))
        acc.saw(ts)
        if not ts and kind in ("user", "assistant", "attachment", "system"):
            STATS["no_timestamp"] += 1
        if kind == "system" and d.get("subtype") == "compact_boundary":
            compacted = after_compact = True
            if ts:
                meta = compact_metadata_of(d)
                auto = meta.get("trigger") == "auto"
                if meta.get("trigger") not in ("auto", "manual"):
                    STATS["compact_trigger_unknown"] += 1
                acc.add(kday(ts), "compact_auto" if auto else "compact_manual")
                if auto and pre_tokens_of(meta) is not None:
                    acc.pre[kday(ts)].append(meta["preTokens"])
                elif auto:
                    STATS["compact_no_pretokens"] += 1
            continue
        if kind == "user":
            if d.get("isCompactSummary"):
                compacted = after_compact = True
                continue
            content = message_of(d).get("content")
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    handle_result(acc, block)
                    note_result(acc, block, ts)
                    note_permission(acc, d, block, ts)
            text = prompt_text(d)
            if text and ts:
                count_prompt(acc, text, ts, sid, last_text, seen["prompt"])
            elif ts:
                m = COMMAND_NAME.search(text_of(content)[:500])
                if m and m.group(1) in skills:
                    acc.add(kday(ts), "skill_slash")
                    skill_used(acc, m.group(1), ts)
        elif kind == "attachment":
            att = attachment_of(d)
            if att is None or att.get("type") == "queued_command":  # a queued prompt or notice, or a warned form
                text = prompt_text(d)
                if text and ts:
                    count_prompt(acc, text, ts, sid, last_text, seen["prompt"])
            elif att.get("type") == "hook_success" and ts:
                hook_ask(acc, att, ts)
            elif ts:
                hook_context(acc, att, ts, sid)
        elif kind == "assistant" and ts:
            msg = message_of(d)
            if isinstance(d.get("attributionSkill"), str):
                skill_used(acc, d["attributionSkill"], ts)
            content = msg.get("content")
            spoke = msg.get("model") != "<synthetic>" and not d.get("isApiErrorMessage")  # no error text of the app
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict):
                    continue
                if spoke:
                    note_language(acc, block, ts, after_compact)
                if block.get("type") == "text" and block.get("text"):
                    last_text = block["text"][-1500:]
                elif block.get("type") == "tool_use":
                    register_tool(acc, block, ts, project, sid, True)
                    note_call(acc, block, ts, sid, d.get("cwd"))
            model = text_field(msg, "model", "model_not_text")
            if model == "<synthetic>" or d.get("isApiErrorMessage"):
                continue
            usage = usage_of(msg)  # after the skip: a skipped answer leaves the metrics complete
            if not isinstance(usage, dict):
                STATS["assistant_no_usage"] += 1
                continue
            mid = text_field(msg, "id", "message_id_not_text") or d.get("requestId") or uid
            if mid in requests:
                rec = requests[mid][2]
                for k, v in usage.items():
                    if isinstance(v, (int, float)) and v > (rec.get(k) or 0):
                        rec[k] = v
                continue
            if mid in seen["mid"]:
                continue
            seen["mid"].add(mid)
            requests[mid] = [ts, model, dict(usage)]
            context = sum(usage.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
            write = usage.get("cache_creation_input_tokens") or 0
            if len(requests) == 1 and not forked:
                acc.startup.append((kday(ts), context, project))
            # idle resume that rewrites the cache (audit misses.py, cause "idle >= 1h")
            if (prev and prev[1] > 20000 and write > 0.5 * context and not compacted and model == prev[2]
                    and (ts - prev[0]).total_seconds() >= 3600):
                acc.add(kday(ts), "idle")
                acc.add(kday(ts), "idle_write", write)
            prev, compacted = (ts, context, model), False
    for ts, _model, usage in requests.values():
        day = kday(ts)
        acc.ctx[day].append(sum(usage.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")))
        add_usage(acc, day, usage, "main_", sid)


def scan_side(acc, path, project, sid, seen):
    workflow = "/workflows/" in path
    first = None
    requests = {}  # message id -> [first ts, usage with max values]: streamed lines repeat the usage
    try:  # the Agent tool_use that started this transcript (workflow agents have none)
        with open(path[:-len(".jsonl")] + ".meta.json", encoding="utf-8") as f:
            run = json.load(f).get("toolUseId")
    except (OSError, ValueError, AttributeError):
        run = None
    preloaded, answered = set(), False  # skills: entries loaded before the agent's first answer
    for d in read_jsonl(path):
        ts = parse_ts(d.get("timestamp"))
        if ts and first is None:
            first = ts
        acc.saw(ts)
        kind = d.get("type")
        if kind == "user":
            content = message_of(d).get("content")
            mark = PRELOAD_MARK.search(text_of(content)[:500]) if d.get("isMeta") and not answered and ts else None
            if mark:
                preloaded.add(mark.group(1).rsplit(":", 1)[-1])
                skill_used(acc, mark.group(1), ts)
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    handle_result(acc, block)
                    note_permission(acc, d, block, ts)
        elif kind == "attachment" and ts:
            att = attachment_of(d)
            if att is not None and att.get("type") == "hook_success":
                hook_ask(acc, att, ts)
            elif att is not None:
                hook_context(acc, att, ts, sid)
        elif kind == "assistant" and ts:
            answered = True
            msg = message_of(d)
            if isinstance(d.get("attributionSkill"), str):
                skill_used(acc, d["attributionSkill"], ts)
            content = msg.get("content")
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    register_tool(acc, block, ts, project, sid, False)
            if text_field(msg, "model", "model_not_text") == "<synthetic>" or d.get("isApiErrorMessage"):
                continue
            usage = usage_of(msg)  # after the skip, as in scan_main
            mid = text_field(msg, "id", "message_id_not_text") or d.get("requestId")
            if not isinstance(usage, dict) or not mid:
                STATS["assistant_no_usage"] += 1
                continue
            if mid in requests:
                rec = requests[mid][1]
                for k, v in usage.items():
                    if isinstance(v, (int, float)) and v > (rec.get(k) or 0):
                        rec[k] = v
            elif mid not in seen["sub_mid"]:
                seen["sub_mid"].add(mid)
                requests[mid] = [ts, dict(usage)]
    for ts, usage in requests.values():
        add_usage(acc, kday(ts), usage, "sub_", sid)
    if workflow and first:
        acc.add(kday(first), "workflow_agents")
    if run:
        acc.preloaded.setdefault(run, set()).update(preloaded)


def scan():
    acc = Acc()
    seen = {"uuid": set(), "mid": set(), "sub_mid": set(), "prompt": set()}
    mains = sorted(p for p in glob.glob(os.path.join(PROJECTS, "*", "*.jsonl"))
                   if not any(x in os.path.basename(os.path.dirname(p)) for x in EXCLUDED_DIRS))
    known = {os.path.basename(p)[:-len(".jsonl")] for p in glob.glob(os.path.join(PROJECTS, "*", "*.jsonl"))}
    try:
        skills = {s for s in os.listdir(SKILLS_DIR) if not s.startswith(".") and os.path.isdir(os.path.join(SKILLS_DIR, s))}
    except OSError:
        skills = None  # no skills dir: slash skills are not counted and the stale list is not printed
    for path in mains:
        project, sid = os.path.basename(os.path.dirname(path)), os.path.basename(path)[:-len(".jsonl")]
        scan_main(acc, path, project, known, seen, skills or set())
        for side in sorted(glob.glob(os.path.join(path[:-len(".jsonl")], "**", "*.jsonl"), recursive=True)):
            if not side.endswith("journal.jsonl"):
                scan_side(acc, side, project, sid, seen)
    STATS["orphan_results"] = len(acc.pending)
    STATS["unknown_prompts"] = sum(PROMPT_UNKNOWN.values())  # records of a form the prompt rule does not know
    coverage(acc)
    skill_coverage(acc)
    permission_asks(acc)
    return acc, len(mains), skills
