# ECC pin (manual install ledger)

pin: 2d515e4   # origin/main 2026-10-10, VERSION 2.2.3; tag v2.2.3 lacks the verification-loop pipefail fix
source: https://github.com/affaan-m/everything-claude-code (local clone ~/ai-stack/everything-claude-code)
method: git archive <pin> skills/<x> | tar -x --strip-components=1 ; git show <pin>:agents/<x>.md
installed: 2026-10-11 (previous: 125d5e6, 2026-04-10, VERSION 1.10.0)
drift check: bash ~/bin/ecc-drift.sh

## Installed from ECC
skills: api-design database-migrations docker-patterns documentation-lookup security-review
agents: architect code-reviewer database-reviewer react-reviewer security-reviewer typescript-reviewer

## Archived (not installed)
skills: git-workflow hexagonal-architecture mcp-server-patterns repo-scan strategic-compact tdd-workflow terminal-ops token-budget-advisor
skills removed 2026-10-15 (v2026.10.19; hidden since B4, no call in 60 days, the useful parts live in rules and the reviewers): backend-patterns coding-standards deployment-patterns e2e-testing frontend-patterns nestjs-patterns postgres-patterns search-first verification-loop
agents: build-error-resolver doc-updater (2026-10-12, v2026.10.1) e2e-runner planner tdd-guide

## Not from ECC
- silent-failure-hunter (agent): anthropics/claude-plugins-official pr-review-toolkit (Apache-2.0)
- graphify (skill): uv tool graphifyy

## Local divergences
- docker-patterns: body kept from 125d5e6 (upstream added ECC installer harness); description rewritten; origin moved to metadata.origin; B5: checklist description, when_to_use and paths (Dockerfile, .dockerignore, compose) make it a conditional skill, priority line, Kubernetes anti-pattern cut
- database-migrations, security-review, docker-patterns, api-design: first body line says project rules, ~/.claude/rules and the existing repo contract win, new and changed code only
- database-migrations: Kysely, Django and golang-migrate cut; UP/DOWN and "backfill as a migration" checklist items cut; DO block with COMMIT marked as a separate script, not a migration; every backfill (principles, rename example, expand-contract, timeline, anti-patterns) is a separate batched script outside the migration; backfill script as in db-queries.md (dry-run, safe rerun, target DB name); NOT NULL on a large table via CHECK NOT VALID, VALIDATE, SET NOT NULL, each its own migration with lock_timeout, helper CHECK dropped; DROP or SET NOT NULL only after the backfill check is 0 and a backup; DO-block WHERE fixed so the loop ends
- security-review: Supabase (query example, RLS), rate limiting section and test, Solana, dependency section (npm audit, npm update, Dependabot) cut; SameSite per cookie instead of Strict everywhere, cookie examples Lax and Strict to match; upload example checks size and type by content (magic bytes), not file.type or extension; error shape as the repo returns it; priority line: rules win on style and scope, never switch off a CRITICAL or HIGH finding, CRITICAL and HIGH issues in existing code reported in one line, repo contract never overrides a security finding; checklist lines for object-level authorization (IDOR), webhooks (signature over raw body, constant-time, dedupe), nosniff on uploads, rate limiting (repo limiter, none: report missing)
- api-design: checklist description, when_to_use and paths (routes, controllers, api, handlers, *.controller, openapi) make it a conditional skill; repo contract named in the priority line; Python/DRF and Go examples cut
- database-reviewer: preloads database-migrations (skills:); priority line (project rules and existing schema conventions win, new and changed code only, existing problems in one line); Supabase RLS, auth.uid, bigint IDs and "random UUID PK" removed (IDs as already in the schema), one generic line kept: project already on RLS, new tables enable it, policy columns indexed; time type and naming as already in the schema (timestamptz from scratch, Prisma camelCase fine); money as already in the schema (numeric/Decimal or integer minor units, never float); cursor pagination only for tables of hundreds of thousands of rows, existing pagination contract kept; unindexed-FK and bloat queries from postgres-patterns; diagnostic commands local or on a copy only, never production; description without "Incorporates Supabase best practices." (v2026.11.25)
- security-reviewer: preloads security-review (skills:); priority line as in security-review, with the security carve-out; npm audit and eslint-plugin-security removed; dependencies as in deps.md (new package genuine, no typosquat; osv-scanner on new or updated packages only, existing vulnerabilities named not updated, no fix command); IDOR and webhook rows (HIGH); missing rate limiting MEDIUM, with the repo's existing limiter (none: report missing), for login, OTP and password reset and for public endpoints that send email or SMS or are expensive
- typescript-reviewer, react-reviewer: "MUST BE USED ..." sentence removed from description (routing lives in ~/.claude/CLAUDE.md)
- architect, react-reviewer: description without "Use PROACTIVELY when planning ..." (architect) and "Use for any change touching .tsx/.jsx ..." (react-reviewer) (v2026.11.25)
- typescript-reviewer: Reference no longer points to coding-standards, frontend-patterns or backend-patterns (not in the base); clean code is left to code-reviewer
- react-reviewer: references to skills/accessibility and /react-* commands are absent and ignored
- code-reviewer: Clean Code section for new and changed code (duplication, size, nesting, I/O vs logic, speculative abstraction, size card «Не додаємо», dead code, naming, magic values, comments); size, nesting, console.log and dead code no longer HIGH; Mutation patterns narrowed to Mutated input; Missing tests only where the repo has tests; Copied business rule added; TODO tickets, JSDoc and formatting items removed
- silent-failure-hunter: model: sonnet; tools: Read, Grep, Glob, Bash; description shortened
