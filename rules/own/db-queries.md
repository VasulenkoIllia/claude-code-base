---
paths:
  - "**/*{repository,Repository,repo,service,Service,store,Store,dao,queries}*.{ts,js,mjs,cjs,py}"
  - "**/{db,database,repositories,services,seed,scripts,routes,core,jobs,cron}/**/*.{ts,js,mjs,cjs,py}"
  - "lib/**/*.{ts,js,mjs,cjs}"
  - "**/src/lib/**/*.{ts,js,mjs,cjs}"
  - "**/{server,backend,app,api,bot,workers,modules}/**/lib/**/*.{ts,js,mjs,cjs}"
  - "**/{apps,packages}/*/lib/**/*.{ts,js,mjs,cjs}"
---
The project takes precedence. New and changed code only: don't rewrite or audit existing code, name a noticed violation in one line.
- New query: an index for the filter, join and sort; `select` instead of a deep `include`. Only for tables with hundreds of thousands of rows: keyset instead of `OFFSET`, no exact `count()`; don't change an existing pagination contract.
- N+1: the number of SQL queries per list doesn't grow with page size (25 and 100).
- Slow query: first `EXPLAIN (ANALYZE, BUFFERS)` on real data volume, then the schema. Don't go to prod yourself: give me a command block. `EXPLAIN ANALYZE` executes the query: DML only inside `BEGIN … ROLLBACK`.
- No HTTP or email inside a transaction; an event to a queue from a transaction only as an outbox row in the same DB.
- Raw SQL only parameterized, no `$queryRawUnsafe` with external data.
- Prisma: `updateMany` returns only `count`; an interactive `$transaction` rolls back after 5 s, long work goes in batches outside it; `@updatedAt` is set by the client, raw SQL doesn't touch it.
- Data script: `--dry-run` with counts, safe to re-run; before writing it prints the target DB name (no URL) and exits if it's the wrong one; batches once it touches thousands of rows.
