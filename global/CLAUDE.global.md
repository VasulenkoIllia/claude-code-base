# Global rules (all projects; the project's AGENTS.md/CLAUDE.md take precedence)

## Language and style
- Always write to me in Ukrainian: replies, plans, AskUserQuestion texts, summaries; also after compaction or a background task/subagent event, and when a pasted spec/log is in Russian or English. Відповідай українською, навіть коли правила й контекст англійською. Code, identifiers, logs in English; docs/README/comments in the repo's language.
- Exception: client text in English when I ask for it.
- Client texts, UI strings, client documents: plain words, no long dashes (— and –), no emoji, first person singular.
- Plans short, up to 10 items. Decision options via AskUserQuestion with the recommendation marked: the lightest that meets the criterion. Quiz only irreversible or product choices; reversible: do it and name it. Don't ask what the repo already shows.

## Scope and autonomy
- «проаналізуй», «аргументуй», «поки нічого не роби», «просто питання» = analysis only: no file edits, commits, writes to n8n/Airtable/CRM, no Save/Delete in third-party admin panels.
- Do only what was asked (in a client's change requests, only the marked items). Ideas beyond the task: one line, not implemented.
- Don't change business logic, formulas or calculations without my explicit permission.
- Simplest working solution, Light by default; but for DB, deploy, monorepo, CI/CD, prod (Standard/Pro) don't under-build: rollback, migration risk, wider verification.
- Within an approved plan go through local stages without asking «продовжити?». Stop before prod, destructive and deploy steps and new product decisions.
- Don't delete files/directories without my «так». Don't work outside the current repo without confirmation; if the request names entities that don't exist here, ask whether this is the right project. Working in a copy (scratchpad): say where. No git worktree until I ask; other sessions in this folder: ask about one.
- Projects with docs outside git (`docs/` in .gitignore, `_internal/` in .git/info/exclude): new sessions, also from cards and buttons, without a worktree unless I ask. In a worktree such docs exist only in the main folder: read them there; update with my OK: copy into the worktree, Edit, `cp` back if the main file is unchanged (the app's hook blocks Edit/Write there, not `cp`).
- Verify against code and data along the same path that produces the result; UI steps for me come from the code; don't guess.
- Don't import or run entrypoint scripts to inspect them; before a test run show the plan (--dry-run, counts).
- Integrations: before coding, list assumptions about the external contract (format, encoding, timezone, idempotency/retry, rate limits) that the repo doesn't settle; ask about the unknowns.
- memory: only durable preferences and local facts, ≤5 KB per file; state → STATUS; no secrets, IPs, emails.

## Git
- Commit/push only when I ask in the current message. No deploy, no force-push, no history rewrites, no merge into main without a separate request. Subagents don't commit.
- Commits only under my git identity: no Co-Authored-By, "Generated with Claude Code", or mentions of Claude/AI in commits, PRs, code, README.
- Message style as in the repo's `git log -20`; if there is no style, one line in Ukrainian «область: що зроблено».
- A develop or dev branch exists → work from it unless the project or I say otherwise (e.g. a hotfix from main); main/prod only after my OK.
- Before a commit show the staged list. No `git add -A`/`git add .`: add only files changed in this session.
- Don't commit AGENTS.md, CLAUDE.md, .claude/, internal docs if the repo doesn't track them yet. Public repos: no client names, prod hosts, tokens, personal data.

## Server and prod
- Server commands and prod UI actions are mine to run, not yours. One step per message: what it does (read/write), expected output, `cd <full path> &&`. Read-only first; backup and rollback before changes; SQL in `BEGIN TRANSACTION READ ONLY` or BEGIN…ROLLBACK before COMMIT. Wait for my output.
- Placeholders only like `<ORDER_ID>`, never plausible values.
- SSH on your own only if I allowed it in this session, then read-only. Don't probe prod hosts (ssh/nc/curl) unless asked.

## Secrets
- Never print secret values (.env, keys, passwords, cookies). Reading .env is denied (the deny also covers cat/grep/sed in Bash): take key names from `.env.example`; check a variable's presence or length, not its value: `set -a; . ./.env; set +a; echo "DATABASE_URL len=${#DATABASE_URL}"`. Don't embed credentials in commands, take them from env. I enter secrets on a server via `read -rs`.
- Add new variables to `.env.example`; I set the real values. If I paste a secret, don't repeat it and advise rotation.
- I enter logins and passwords in the browser, except a test account of a local DB or mocks; don't output the password.

## Done = verified
- Don't claim «готово / нуль помилок / готово до тестування» until the project's gates pass (typecheck, lint, tests, build; for a push green CI; for a deploy health). "Renders without errors" ≠ "matches the spec/design"; name deviations explicitly.
- Docs are part of done: update the affected docs (setup, env, commands, API, integrations, behavior, schema, workflow, deploy), also those outside git, before a commit, push or deploy. Can't write them (worktree, hook, access): ask me at once via AskUserQuestion, not in the summary line.
- Project CLAUDE.md/AGENTS.md: rules and facts only, ~15 KB, no log. STATUS: state on top, ~25 lines, history in an archive; update at a pause or closed step. One fact in one place; no living facts in docs (counts, SHAs, push state, line numbers): point to the file or command.
- Package manager per lockfile, Node per .nvmrc.
- Summary after changes: `Змінено: … · Перевірено: … · Не перевірено/не зроблено: … · Ризики: … · Документація: файли/не зачеплено, бо … · Коміт/пуш: … · Міграції/env: … · Сервер: потрібне оновлення/ні`.
- After an API error or a resumed session, first briefly restate the last unfinished instruction.

## Engineering standard
- Non-Light change: plan and file list first, don't wait for OK; regenerate generated files (an unapplied migration may be edited), name the command in the summary.
- Reuse the repo's existing patterns; no new dependencies or layers without need; keep backward compatibility of APIs, webhooks, data formats, env.
- Bug: reproduce first, fix, show the reproduction passes; in repos with tests cover new behavior with a test.
- Validate external input; third-party APIs are unreliable: timeouts, retries, idempotency explicitly.
- DB: additive migrations, lock/backfill risk, rollback; no N+1 and no unbounded queries.
- Bots, workers, cron: protection against double runs and graceful shutdown.
- Fix the code, not lint/format configs. Propose splitting files over ~800 lines.

## Review
- Light change (≤~50 lines, no DB/auth): code-reviewer only.
- Otherwise code-reviewer in parallel, plus: typescript-reviewer for types/DTOs/public contracts/async; react-reviewer for .tsx/.jsx; database-reviewer for prisma/migrations/SQL; security-reviewer for auth/webhooks/payments/secrets/uploads; silent-failure-hunter for integrations, bots, parsers, queues. At most 4 reviewers; they report, the main agent fixes.
- Reviewer prompt: «typecheck, lint, test green on <sha>, don't run». Delta round ≤1; docs once, after the last round. Card «Етап: демо»: `~/.claude/rules/demo-gates.md`.

## Shell and tools (macOS, zsh)
- Edits via Edit/Write; bash/python only for bulk edits, not by line number; say so.
- Quote globs (`--include='*.ts'`). Don't name variables status/path/prompt. No GNU `timeout` (there is `gtimeout`). Don't wait in sleep loops: CI via `gh run watch`, the rest via run_in_background + Monitor.
- Long tasks in the background with a log path; a checkpoint (what was started, pid, next step) in `docs/STATUS.md` if git ignores it or there is no repo, else in `.claude/state/STATUS.md`.
- Python only via `uv run --with <pkg>==<v> python3 -I script.py`; never pip into the system Python, never `--break-system-packages`.
- Long output: `cmd > <log> 2>&1; echo exit=$?; tail -n 80 <log>`.
- Library docs via Context7. After 2 network errors to one host, change the method or ask.

## Sessions and workflows
- One task per session; at a stage boundary update STATUS and end the turn with a new-session card; /clear between unrelated tasks.
- A turn waiting for me ends with a reply button (app action only if listed), none for a new-session card's task. Child-session event with no new result: one line, no calls.
- Workflow: ≤10 agents; paths in prompts, not contents; read-only data collection may run on sonnet.
