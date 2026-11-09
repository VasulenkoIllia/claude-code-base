"""Checks of claude-metrics for tests/metrics-test.py: the language of what the model writes to the owner and the
context of a session's first request by project, on one made-up home."""
import json
import os
import subprocess
import sys

from claude_metrics.language import is_english, text_of_block

UK = "Перевірив усе, файл на місці, можна рухатись далі без змін."
EN = "Now I will check the hook and then run the whole test suite again."
MIXED = "Запустив `npm run check --workspaces --if-present` і перевірив https://example.invalid/long/path/here у README.md"
TERMS = "Звіт database-reviewer отримано. Чекаю на code-reviewer і typescript-reviewer."


def record(sid, n, kind, day, **extra):
    return {"type": kind, "sessionId": sid, "uuid": f"{sid}-{n}", "cwd": "/w", "timestamp": f"{day}T08:{n:02}:00Z", **extra}


def answer(sid, n, day, blocks, usage=None):
    usage = usage or {"input_tokens": 1000, "output_tokens": 10}
    return record(sid, n, "assistant", day, message={"id": f"{sid}m{n}", "model": "m", "usage": usage, "content": blocks})


def text(value):
    return {"type": "text", "text": value}


def tool(name, tid, inp):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


WRAP, PLAN = "mcp__ccd_turn__wrap_up", "mcp__ccd_turn__update_plan"


def plan_items(content):
    return {"items": [{"content": content, "status": "pending"}], "scope": "first_task"}


def main_rows(day):
    """Before the compaction: chat 1 of 4 (the short one is left out; a text mostly of code and one full of terms are
    not English), wrap_up 1 of 2, plan 0 of 1 ({"advance": true} shows no text), quiz 0 of 1 (its keys are English in
    every language). After it: chat 1 of 2, plan 1 of 1."""
    quiz = {"questions": [{"question": UK, "header": "Вибір", "multiSelect": False,
                           "options": [{"label": "Так", "description": UK}, {"label": "Ні", "description": UK}]}]}
    return [
        record("l1", 0, "user", day, message={"role": "user", "content": "зроби"}),
        answer("l1", 1, day, [text(EN), text(UK), text("ok"), text(MIXED), text(TERMS)],
               {"input_tokens": 90000, "output_tokens": 10}),
        answer("l1", 2, day, [tool(WRAP, "w1", {"recap": EN, "ask": "Which one?", "actions": [{"label": "Go"}]}),
                              tool(WRAP, "w2", {"recap": UK})]),
        answer("l1", 3, day, [tool(PLAN, "p1", plan_items(UK)), tool(PLAN, "p2", {"advance": True})]),
        answer("l1", 4, day, [tool("AskUserQuestion", "q1", quiz)]),
        # the tools with another input count as nothing, in lang_no_text; moving a plan step is a known form
        answer("l1", 5, day, [tool(WRAP, "w3", {"recap": 7}), tool(WRAP, "w4", "рядок"),
                              tool(PLAN, "p3", {"items": ["рядок", {"content": 5}]}),
                              tool("AskUserQuestion", "q2", {"questions": "x"})]),
        # the app's own text, not the model's
        answer("l1", 10, day, [text(EN)], {"input_tokens": 1}) | {"isApiErrorMessage": True},
        record("l1", 11, "assistant", day, message={"id": "s", "model": "<synthetic>", "content": [text(EN)]}),
        record("l1", 6, "system", day, subtype="compact_boundary", compactMetadata={"trigger": "auto", "preTokens": 5}),
        answer("l1", 7, day, [text(EN), text(UK)]),
        answer("l1", 8, day, [tool(PLAN, "p4", plan_items(EN))]),
    ]


def write_session(home, rel, rows):
    path = os.path.join(home, ".claude", "projects", rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(json.dumps(r) + "\n" for r in rows))


def language_checks(tmp, check, cli):
    day = "2026-10-20"
    home = os.path.join(tmp, "lang-home")
    os.makedirs(os.path.join(home, ".claude", "skills"))
    prefix = "-Users-someone-WebstormProjects-"
    files = {
        f"{prefix}alpha-ui/l1.jsonl": main_rows(day),
        f"{prefix}alpha-ui/l1/subagents/agent-a.jsonl": [answer("l1", 9, day, [text(EN), tool(PLAN, "p9", plan_items(EN))])],
        f"{prefix}alpha-ui--claude-worktrees-a-b/l2.jsonl": [answer("l2", 1, day, [], {"input_tokens": 110000})],
        f"{prefix}alpha-ui/l3.jsonl": [answer("l3", 1, day, [], {"input_tokens": 70000})],
        f"{prefix}beta-app/l4.jsonl": [answer("l4", 1, day, [], {"input_tokens": 84000})],
    }
    for rel, rows in files.items():
        write_session(home, rel, rows)
    env = {"HOME": home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}
    args = ("--before", "2026-10-01", "2026-10-10", "--after", day, day)

    def run(*mode, window=args):
        return subprocess.run([sys.executable, "-I", cli, *mode, *window], env=env, capture_output=True, text=True,
                              encoding="utf-8", check=False)

    res = run("--json")
    check("language: claude-metrics runs", res.returncode == 0, res.stderr[-500:])
    report = json.loads(res.stdout) if res.returncode == 0 else {}
    after, scan = report.get("after", {}), report.get("scan", {})
    kinds = {k: after.get("lang:" + k) for k in ("chat", "wrap_up", "plan", "quiz")}
    check("language: English of all, by kind; a subagent's texts do not count",
          kinds == {"chat": "2/6", "wrap_up": "1/2", "plan": "1/2", "quiz": "0/1"}, str(kinds))
    check("language: the share of English", abs((after.get("lang_en_pct") or 0) - 400 / 11) < 1e-9, str(after.get("lang_en_pct")))
    check("language: the share after a compaction", abs((after.get("lang_compact_en_pct") or 0) - 200 / 3) < 1e-9,
          str(after.get("lang_compact_en_pct")))
    check("startup: by project, a worktree in its project, most sessions first", after.get("startup_by_project") == [
        ["alpha-ui", 3, 90000], ["beta-app", 1, 84000]], str(after.get("startup_by_project")))
    check("startup: the median of all starts", after.get("startup_median") == 87000, str(after.get("startup_median")))
    check("language: 4 calls of the tools with no text in the scan's line", scan.get("lang_no_text") == 4,
          str(scan.get("lang_no_text")))
    check("language: a tool name or a text that is no text is no block of the owner's",
          text_of_block(tool(["x"], "w5", {})) is None and text_of_block({"type": "text", "text": 5}) is None)
    check("language: few Latin letters and no Cyrillic ones are no English",
          not is_english("OK: 1200, 3400, 5600, 7800, 9000"))
    question = tool("AskUserQuestion", "q3", {"questions": [{"question": EN, "header": "Вибір"}]})
    check("language: a quiz is its question too", text_of_block(question) == ("quiz", EN + " Вибір"),
          str(text_of_block(question)))
    plain = run()
    check("language: the plain report has the rows", "Тексти власнику англійською, %" in plain.stdout,
          plain.stderr[-300:])
    check("startup: the plain report lists the projects", "Старт сесії за проєктами" in plain.stdout
          and any(line.split()[:2] == ["beta-app", "1"] for line in plain.stdout.splitlines()), plain.stdout[-400:])
    weekly = run("--weekly", "--since", day)
    row = next((ln for ln in weekly.stdout.splitlines() if ln.startswith("20.10.2026")), "")
    check("weekly: the start of sessions and the share of English close the row", row.split()[-3:] == ["87", "000", "36.4"],
          row)
    check("language: few prompts: no warning about the app's tools",
          not any("0 текстів" in w for w in report.get("warnings", [])), str(report.get("warnings")))
    later = "2026-10-21"  # a day of its own: the rows above have a plan
    prompts = [record("l5", n, "user", later, message={"role": "user", "content": f"запит {n}"}) for n in range(20)]
    write_session(home, f"{prefix}alpha-ui/l5.jsonl", prompts + [answer("l5", 30, later, [text(UK)])])
    write_session(home, f"{prefix}alpha-ui/l6.jsonl", [answer("l6", 1, later, [tool(WRAP, "w9", {"recap": UK})])])
    gone = run("--json", window=(*args[:3], "--after", later, later))
    warned = [w for w in (json.loads(gone.stdout).get("warnings", []) if gone.returncode == 0 else []) if "0 текстів" in w]
    check("language: 20 prompts and no plan text: the warning names only the plans", len(warned) == 1
          and "плани update_plan" in warned[0] and "wrap_up" not in warned[0], str(warned))
