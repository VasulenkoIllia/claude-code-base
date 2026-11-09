#!/usr/bin/env -S python3 -I
"""How Claude Code works across all projects, week by week, from session transcripts and project git (read-only).

Compares a "before" window (default 2026-08-01..2026-09-30, the audit baseline) with an "after" window (default
from 2026-10-13: the base releases B1..B3 were installed on 2026-10-12, a transition day left out of both).
Definitions follow the audit of 2026-10-11/12 (research/stability-tokens-2026-10-11.json, measure:token-baseline;
research/specialized-kit-2026-10-12.md, table "Як зрозуміти, що набір допомагає") as re-derived on 2026-10-12;
on Aug-Sep they reproduce the audit's numbers (context 493K mean / 472K median, 59% of requests over 400K,
auto-compaction near 970K, startup 73.6K).

Scope. Main transcripts ~/.claude/projects/<dir>/<sid>.jsonl give prompts, API requests, context, compactions,
startup and idle resumes. Subagent and workflow transcripts (<sid>/**/*.jsonl) count only for tool metrics
(browser, sleep, errors, skills, agents, edits) and for the subagent share of cost, as in the audit. Sessions of
the setup base itself (*claude-code-base*) and the deny-test scratch dir are left out. A fork copies its
original's entries with the original's sessionId: such entries are skipped. uuids, message ids and tool_use ids
count once.

Normalisation. P = prompts typed by the user, by claude-time's rule (time_register.transcript.prompt_text), so both
tools count the same prompts and both windows are counted alike: a user message or a prompt sent while the model
worked (a queued_command attachment), also one of only pasted text or only images; a note of the app in front of it
(<system-reminder>) is cut off; tool results, commands, task notifications, messages of other sessions and CI events
are not prompts. An active day is a Kyiv day with at least one P. Rates are per active day or per 100 P, so busy and
quiet weeks compare.

Checks. A footer on stderr ("scan: ...") counts what was skipped (forks, repeated uuids, records with no usage or
timestamp, results kept only as a preview, unknown browser tools, fields of a form the scan does not know, which it
takes as missing and warns of). The report warns when a window has no or few active days, starts before the oldest
transcript (Claude Code deletes old ones), or has prompts but no requests.

Two metrics need judgement and are only listed as candidates (--candidates): requests to redo what the agent just
did, and a "готово" claim after which the user reports a bug.

B5 (v2026.10.9) counters, zero or near zero before it. Preload: runs of the PRELOAD agents (Agent/Task subagent_type,
plugin prefix allowed) whose transcript, linked by toolUseId in <agent>.meta.json, gets the agent's skills: entry
before the first answer as a meta user record "<command-name>X</command-name> <skill-format>true</skill-format>"
(runAgent of 2.1.293; the same marker as the workflow-authoring autoload already in main transcripts). Path-scoped
skills: sessions where a CONDITIONAL skill came in a mid-session skill_listing (isInitial false: a touched file
matched its paths:, or a skills reload), and of them those with a Skill call for it afterwards. dup-guard: hook
additional context starting with "dup-guard:", once per tool call. A preload counts as use in the 30-day list.

B5.1 (v2026.10.18): cost per pushed commit and per 100 changed lines. Commits and lines come from git of the
projects (read-only, no fetch), matched to the git commit calls of main sessions: claude_metrics/pushes.py.

v2026.10.37: the language of what the model writes to the owner in main sessions (chat text over 40 characters,
wrap_up, update_plan, AskUserQuestion; claude_metrics/language.py), overall and after a compaction in the session; the
context of a session's first request by project (the comparison, as a list) and by week (--weekly).

v2026.10.38: real permission prompts, from permissionDecision on the result of a call (the field exists from
2026-10-08, so the "before" window has none): by kind (ssh read or change, git push, gh pr merge, bash-guard, other)
with the time from the call to its result, the command's own run included, and the days of a session with ssh against
the owner's targets of 30.10 (at most 10 asks on such a day, no wait over 5 minutes on a read):
claude_metrics/asks.py. hook_asks still counts only what a hook asked.

Code. This file is only the command line; the scan, the metrics and the report are in the claude_metrics package
next to it (tools/claude_metrics in the repo, ~/bin/claude_metrics live), the prompt rule in claude-time's package
time_register, next to it too.

Usage (installed by the base as ~/bin/claude-metrics; from the repo: python3 -I tools/claude-metrics.py):
  claude-metrics                                  # before vs after
  claude-metrics --after 2026-10-13 2026-10-26    # explicit windows: --before A B, --after A B
  claude-metrics --weekly --since 2026-09-01      # key rates per ISO week
  claude-metrics --candidates                     # redo / premature-done candidates of the after window
  claude-metrics --json
"""
import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta

sys.dont_write_bytecode = True  # no __pycache__ next to the live copy: doctor would report it as drift
# -I leaves the script's folder off sys.path; appended, so a stray file in ~/bin cannot shadow the standard library
sys.path.append(os.path.dirname(os.path.realpath(__file__)))
# pylint: disable=wrong-import-position
from claude_metrics.patterns import AFTER_START, BEFORE, FIELD_FORMS, KYIV, SKILLS_DIR  # noqa: E402
from claude_metrics.pushes import GIT_FAILURES, pushes  # noqa: E402
from claude_metrics.report import print_compare, print_weekly, window_warnings  # noqa: E402
from claude_metrics.scan import scan  # noqa: E402
from claude_metrics.summary import summarize  # noqa: E402
from claude_metrics.transcript import STATS  # noqa: E402
from time_register.transcript import unknown_forms, unknown_warning  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--before", nargs=2, type=date.fromisoformat, metavar=("FROM", "TO"),
                    default=list(BEFORE), help="baseline window, Kyiv days (default 2026-08-01 2026-09-30)")
    ap.add_argument("--after", nargs=2, type=date.fromisoformat, metavar=("FROM", "TO"),
                    help="window to compare (default 2026-10-13 .. today)")
    ap.add_argument("--weekly", action="store_true", help="key rates per ISO week instead of the comparison")
    ap.add_argument("--since", type=date.fromisoformat, help="with --weekly: first day (default 8 weeks back)")
    ap.add_argument("--candidates", action="store_true", help="list redo and done-then-bug candidates of the after window")
    ap.add_argument("--json", action="store_true", help="print both windows as JSON")
    a = ap.parse_args()

    today = datetime.now(KYIV).date()
    after = a.after or [AFTER_START, max(today, AFTER_START)]
    if after[0] > after[1] or a.before[0] > a.before[1]:
        ap.error("a window ends before it starts")
    since = a.since or today - timedelta(weeks=8)
    if since > today:
        ap.error("--since is in the future")
    acc, sessions, skills = scan()
    if not sessions:
        sys.exit("no transcripts found in ~/.claude/projects")
    if not (a.candidates or a.weekly):
        pushes(acc)  # reads git of the projects: only the comparison prints the cost per commit
    # one footer line on stderr, so stdout stays a clean report; non-zero skip counters are worth a look
    print(f"scan: sessions={sessions} first_day={acc.first_day} "
          + " ".join(f"{k}={v}" for k, v in sorted(STATS.items())), file=sys.stderr)
    if STATS["bad_lines"] or STATS["unreadable"]:
        print(f"увага: битих рядків {STATS['bad_lines']}, нечитаних файлів {STATS['unreadable']} з "
              f"{STATS['files'] + STATS['unreadable']}", file=sys.stderr)
    # most of its user records come in the line below too, as «message не об'єкт» (not the meta, sidechain and
    # subagent ones: the prompt rule does not read them)
    if STATS["message_not_object"]:
        print(f"увага: записів, у яких message не об'єкт, {STATS['message_not_object']}: можливо, змінився формат "
              "транскриптів, і метрики неповні (відповіді моделі, результати інструментів)", file=sys.stderr)
    fields = [(name, STATS[key]) for key, name in FIELD_FORMS.items() if STATS[key]]  # each taken as missing
    if fields:
        print(f"увага: записів з полями незнайомої форми {sum(n for _, n in fields)} "
              f"({'; '.join(f'{name} {n}' for name, n in fields)}): можливо, змінився формат транскриптів, і метрики "
              "неповні", file=sys.stderr)
    unknown = unknown_warning()  # claude-time's lines, the same rule; their numbers also count the base's sessions
    if unknown:
        print(unknown, file=sys.stderr)

    if a.candidates:
        rows = [c for c in acc.candidates if after[0] <= c[0] <= after[1]]
        for w in window_warnings(summarize(acc, *after), "після", acc.first_day):
            print("увага: " + w)
        print(f"Кандидати {after[0]}..{after[1]}: {len(rows)}. Текст запиту: claude-time --prompts <сесія> --after '<час-1 хв>'.")
        for day, ts, sid, kind, matched in sorted(rows, key=lambda r: r[1]):
            print(f"{ts.astimezone(KYIV):%Y-%m-%d %H:%M}  {sid[:8]}  {kind:16}  «{matched[:40]}»")
        return
    if a.weekly:
        print_weekly(acc, since, today)
        return
    before_s, after_s = summarize(acc, *a.before), summarize(acc, *after)
    warnings = window_warnings(before_s, "до", acc.first_day) + window_warnings(after_s, "після", acc.first_day)
    if skills is None:
        warnings.append(f"тека скілів {SKILLS_DIR} не знайдена: виклики /скілів не враховано")
    failed = [k for k in GIT_FAILURES if STATS[k]]
    if failed:
        warnings.append(f"git прочитано не повністю ({', '.join(failed)} у рядку scan:): ціна на коміт неповна")
    elif STATS["commit_calls"] >= 10 and not STATS["commit_calls_matched"]:
        warnings.append(f"{STATS['commit_calls']} викликів git commit, але жоден не дав опублікованого коміту: "
                        "схоже, змінився формат транскриптів чи git")
    if a.json:
        # every kind and name of the warning, names as it shows them (cut to 30 characters), with no limit on names
        forms = [{"kind": k, "name": n, "count": c} for k, n, c in unknown_forms()]
        print(json.dumps({"before": before_s, "after": after_s, "warnings": warnings,
                          "scan": {"sessions": sessions, "first_day": acc.first_day, **STATS, "unknown_forms": forms}},
                         ensure_ascii=False, indent=1, default=str))
        return
    for w in warnings:
        print("увага: " + w)
    if warnings:
        print()
    print_compare(before_s, after_s)
    if skills:
        stale = sorted(s for s in skills if (today - acc.skill_last.get(s, date.min)).days > 30)
        print(f"\nСкіли без виклику за останні 30 днів ({len(stale)} з {len(skills)}): {', '.join(stale) or 'немає'}")


if __name__ == "__main__":
    main()
