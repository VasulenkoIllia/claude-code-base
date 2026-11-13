---
paths:
  - "**/{prisma,migrations,drizzle,alembic}/**"
  - "**/*.{prisma,sql}"
  - "**/{db,database}/schema/**"
  - "**/drizzle.config.*"
  - "**/*{migrat,Migrat}*.{ts,js,mjs,py}"
---
The project takes precedence. New and changed code only: don't rewrite or audit existing code, name a noticed violation in one line.
- Don't edit an applied migration, create a new one. Before apply read the generated SQL: a rename often becomes DROP + ADD, i.e. data loss. A not yet applied one may be edited.
- New columns per the repo's convention: money as `Decimal`/`numeric` or integer minor units, never `Float`; time as already in the schema (schema from scratch: `timestamptz`), a new FK with an index.
- A new relation to payments, invoices/accounts, journals, audit: `onDelete: Restrict`; `Cascade` only with a reason in the plan.
- A table with ~100k+ rows or a hot one: `CREATE INDEX CONCURRENTLY` only outside a transaction (Prisma: the only statement in the file; Drizzle `migrate()` is transactional, so a separate step; Alembic: alone in its revision, inside `op.get_context().autocommit_block()`); NOT NULL via `CHECK … NOT VALID` → `VALIDATE` → `SET NOT NULL`, FK via `NOT VALID` → `VALIDATE`; no volatile DEFAULT; `lock_timeout`; backfill in a separate script in batches. In the plan: row count and expected locking.
- Schema or migration change: database-reviewer; `migrate dev` only locally, on a server `migrate deploy`; `migrate resolve` only after `migrate status` and showing the mismatch. Alembic: `revision --autogenerate` only locally, read the revision before `upgrade` (a rename comes out as drop + add), on a server `upgrade head`; `stamp` only after `current` and showing the mismatch.
