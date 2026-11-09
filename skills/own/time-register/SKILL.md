---
name: time-register
description: Глобальний реєстр задач і часу сесій Claude по всіх проєктах і оцінка трудозатрат на його основі. Use when the user asks to update the time register, how many hours a task, project or week took, or for any estimate of work time or effort for a project, ТЗ, feature or change, in hours or days ("онови реєстр часу", "скільки часу пішло", "скільки часу піде", "наскільки довго", "оцінка строку", "оціни в годинах", "трудозатрати", "how long will it take").
---

# Task and time register

Tool: `~/bin/claude-time` (the ECC base, `tools/time-register.py`); write it exactly so, also `~/bin/claude-metrics`: `~/bin` is not in PATH, and the permission rules match only this form. Data: `~/claude-time/`, private and outside git. Transcripts are only read. All flags: `~/bin/claude-time --help`.

## Rules
- Don't edit `register.json` and `register.csv` by hand. Manual data lives only in `tasks.csv` and is written only via `--add` (with `--stage`: via `--split-done`).
- No secrets, emails, phone numbers, hosts, IPs or personal data in task names and `note`.
- Hours = Claude session time (a pause over 30 min doesn't count). Time outside sessions (calls, server) is added only from the user's words (column `extra_h`). Don't invent numbers.
- Run the tools as plain commands, one per Bash call: no loops, `cd` or variables; a pipe into `head` or `tail` is fine for reports, but read `--pending --full` and `--prompts` in full. No grep or Read of the files in `~/claude-time`, except fixing `tasks.csv` errors with the user. Anything else may wait for the user's approval, and a scheduled run has nobody to give it.

## 1. Weekly update («онови реєстр», «скільки часу за тиждень»)
Every Monday 10:00 Kyiv time the app's scheduled task `time-register-weekly` runs this section in a session in the base folder. Nobody confirms the split (the owner, 02.11): split and write it on your own, the report is read later; the same on «онови реєстр» in a session.
Stop: a line starting with `увага:` from `~/bin/claude-time` before the split is written, or its error (but bad rows of `--stage`, step 4), ends the split: no `--add` or `--split-done` after it; quote those lines verbatim in the report (or the short reply of step 2) and say the split was not written. E.g. «записів незнайомої форми» means the transcript format may have changed and some prompts were not counted. A `примітка:` line (usually typed text starting with «<») never stops the split: quote it verbatim, as `--write` or `--pending` print it, in the report or, without one, in your last message. `увага:` lines after the split or from `~/bin/claude-metrics` are only quoted; claude-metrics prints them before its report, so don't pipe it into `tail`.
1. `~/bin/claude-time --write`. `tasks.csv` errors: stop and name them (fixing needs the user).
2. `~/bin/claude-time --pending --full`: the first line shows the boundary B, then the sessions with unsplit prompts and their new prompts; sessions that did not fit come last as `--prompts` commands, run each as printed, one per call. No boundary yet («ще ніколи»): write nothing and say the owner sets it. Nothing new but this session: say all is split (B), quote any `примітка:` line and end, without report and metrics.
3. Splitting:
   - task = one goal (module, integration, bug, audit, deploy, document); «продовжуй», checks and fixes of what was just done stay in the current task;
   - a new task only for a new goal, no fragmenting (usually 1-3 tasks per 20 prompts);
   - the first new prompt that continues the session's last task needs no row; the tool doesn't show which task that was, so when unsure add a row with the existing task's exact name: the same name in a project is one task;
   - name in Ukrainian, up to 60 characters; the same work in another session gets exactly the same name (existing ones: `--by task --project '<project>'`; a project name cut with «…» in the table doesn't match, then `--by task --grep '<words>'`);
   - kind: module, integration, ui, data, bug, ops, analysis, docs, setup, refactor, prototype;
   - note in Ukrainian, up to 12 words about the scope (needed for analogs in estimates);
   - doubtful (only labels like «[вставлено N симв.]» or «[картинка]», an unclear goal, unknown which task it continues): your best guess still gets a row, its note starts with «сумнів:»;
   - this session, if listed: a row «Щотижневе оновлення реєстру часу», kind ops.
4. Stage the rows: `~/bin/claude-time --add <id> "<YYYY-MM-DD HH:MM>" "<task>" <kind> "<note>" --add … --stage`, up to 20 `--add` per call, one line (a command over 10 000 characters waits for permission), chunks one after another; the time is the task's first new prompt, after B. Each chunk starts exactly `~/bin/claude-time --add` and has `--stage` after its last row: the permission rule matches only that start, any other (`--restart` or `--stage` first) waits for permission. It checks them with `tasks.csv` and the rows staged before, writes no `tasks.csv` and prints the `--rows` number. Bad rows (`the new rows are bad`): nothing staged, fix them and resend the chunk; still bad after two resends: stop. Only after a context compaction, unsure what was staged: stage all rows again, the first chunk as `~/bin/claude-time --add … --stage --restart`; no `--restart` otherwise. Task and note in double quotes, only words, digits and `. , : ; - + ( ) % № « » ' ?`, never `--`: no commands, paths or file names (some ask for permission).
5. After the last chunk: `~/bin/claude-time --split-done '<T>' --rows <N> --after '<B>'`, T = the latest «останній» of the step 2 table, N = the `--rows` number of the last `--stage` (0 if none). It checks that the boundary is still B and writes the staged rows with the boundary, or nothing; «поділено до» in its output means written. Cut short without a line of its own (a timeout): run it once more. Then `--write`.
6. Report: rows written (the «записано рядків» line), sessions and new tasks per project, the «сумнів:» rows (session, time, task), B and the new boundary, any `примітка:` line; `--by project --since <date of B>` and `--by week`; explain the difference between «сума» and «годинник» in one line (parallel sessions).
7. Metrics: `~/bin/claude-metrics` (before and after base releases) and `~/bin/claude-metrics --weekly`. Show the rows marked `-` (worse) and up to 3 largest `+`. The user labels the «переробити» and «готово, потім баг» candidates (`--candidates`, session and keyword match); don't copy full prompt texts into the report.

## 2. Estimating a project, ТЗ or feature («оціни», «скільки годин», «трудозатрати»)
1. Split into work items, each with a kind and a short scope. Don't forget the cross-cutting ones: analysis and plan, ТЗ and documents, deploy and server, testing and client revisions.
2. Baseline: `~/bin/claude-time --by kind`; with `--level T<n>` when the project level is known and there are at least 10 tasks of that level.
3. Analogs: `~/bin/claude-time --by task --grep '<keywords>'` (names are in Ukrainian), the 1-3 closest by note.
4. Per item: a close analog exists, take its hours; otherwise the kind's median as the lower bound and p75 as the upper. Mark a kind with fewer than 5 tasks «мало даних».
5. Take the cross-cutting shares from `--by kind --project <similar project>` (share of analysis, docs, ops, bug in the total), not from your head.
6. Result: a table «пункт, тип, аналоги з годинами, оцінка від і до», total from-to session hours. Separately: «це години сесій Claude без часу поза ними; календарний строк довший» and a list of assumptions.
7. Client text (estimate, ТЗ): plain words, no long dashes or emoji, first person. Don't show the client the names of other projects or tasks from the register.
