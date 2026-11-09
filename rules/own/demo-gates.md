---
paths:
  - "**/CLAUDE.local.md"
---
The project takes precedence. New and changed code only: don't rewrite or audit existing code, name a noticed violation in one line.
Only when the project card says «Етап: демо»: these gates then take precedence over the global rules on review, tests, checks and docs.
- Always: the card's check command (`pnpm run check`) before a stage commit, not after every edit; secrets only in .env, never in logs; external systems read-only with a hard list of methods; a spend limit on paid APIs and an estimate with my OK before the first paid run; the API on loopback only.
- Tests: pure logic and the money, secrets and data truthfulness paths only; no mutation tests, no coverage targets.
- Review: code-reviewer per stage; security-reviewer only when keys, paid APIs or publishing are touched; one round; fix only HIGH on secrets, money, data; the rest one list «до старту».
- Demo acceptance: a demo scenario (a page or a command) and a quality number on 20-50 real requests (for search: a hit in the top 10), written in README; a full import of real data right after the schema.
- Docs: README «як запустити демо», decisions.md up to 5 lines per decision, STATUS one page, integrations only facts for the next stage; update at a stage boundary.
- Put off until «проєкт стартує»: 3-4 reviewers, silent-failure-hunter and typescript-reviewer per stage, mutation tests, worker resilience, scale of 1-2 million, rate limits, docker build and deploy docs, the osv stop on dev dependencies. At the start: «Етап: прод» and a «зміцнення» task (tests and review of the demo code that stays).
