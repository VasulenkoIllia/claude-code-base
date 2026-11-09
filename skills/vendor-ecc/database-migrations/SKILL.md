---
name: database-migrations
description: "Safe, reversible database migration patterns: forward-only production changes, expand-contract zero-downtime renames, concurrent indexes, batched backfills, and per-tool workflows for PostgreSQL, Prisma, and Drizzle. Use when writing a schema or data migration, adding a column or index to a large table, planning a rollback, or preparing a zero-downtime deploy."
metadata:
  origin: ECC
---
Project rules (AGENTS.md, CLAUDE.md), the base rules in ~/.claude/rules and the existing repo contract win over this skill. Apply it to new and changed code only.

# Database Migration Patterns

Safe, reversible database schema changes for production systems.

## When to Activate

- Creating or altering database tables
- Adding/removing columns or indexes
- Running data backfills or transforms (batched scripts, not migrations)
- Planning zero-downtime schema changes
- Setting up migration tooling for a new project

## Core Principles

1. **Every schema change is a migration** — never alter production databases manually
2. **Migrations are forward-only in production** — rollbacks use new forward migrations
3. **A backfill is not a migration** — the migration holds the DDL; the data backfill is a separate batched script in the repo, run outside the migration: safe to rerun, `--dry-run` with counts, prints the target DB name (no URL) before writing and exits if it is the wrong one
4. **Test migrations against production-sized data** — a migration that works on 100 rows may lock on 10M
5. **Migrations are immutable once deployed** — never edit a migration that has run in production

## Migration Safety Checklist

Before applying any migration:

- [ ] No full table locks on large tables (use concurrent operations)
- [ ] New columns have defaults or are nullable; NOT NULL on a large or hot table via `CHECK (col IS NOT NULL) NOT VALID` → `VALIDATE CONSTRAINT` → `SET NOT NULL` (see below)
- [ ] `lock_timeout` set for DDL on a large or hot table
- [ ] Before a DROP or SET NOT NULL that depends on a backfill: the backfill is done and verified (count of rows where the new column IS NULL or differs = 0) and a backup is taken
- [ ] Indexes created concurrently (not inline with CREATE TABLE for existing tables)
- [ ] Tested against a copy of production data
- [ ] Rollback plan documented

## PostgreSQL Patterns

### Adding a Column Safely

```sql
-- GOOD: Nullable column, no lock
ALTER TABLE users ADD COLUMN avatar_url TEXT;

-- GOOD: Column with default (Postgres 11+ is instant, no rewrite)
ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT true;

-- BAD: NOT NULL without default on existing table (requires full rewrite)
ALTER TABLE users ADD COLUMN role TEXT NOT NULL;
-- This locks the table and rewrites every row
```

### Setting NOT NULL on a Large Table

After the backfill is verified. Each step is its own migration (own transaction):

```sql
-- Migration A: instant, no scan
SET lock_timeout = '5s';
ALTER TABLE users ADD CONSTRAINT users_role_not_null CHECK (role IS NOT NULL) NOT VALID;

-- Migration B: scans the table without blocking reads or writes
SET lock_timeout = '5s';
ALTER TABLE users VALIDATE CONSTRAINT users_role_not_null;

-- Migration C: PG12+ uses the validated CHECK, so SET NOT NULL does not scan;
-- then the helper CHECK is dropped
SET lock_timeout = '5s';
ALTER TABLE users ALTER COLUMN role SET NOT NULL;
ALTER TABLE users DROP CONSTRAINT users_role_not_null;
```

### Adding an Index Without Downtime

```sql
-- BAD: Blocks writes on large tables
CREATE INDEX idx_users_email ON users (email);

-- GOOD: Non-blocking, allows concurrent writes
CREATE INDEX CONCURRENTLY idx_users_email ON users (email);

-- Note: CONCURRENTLY cannot run inside a transaction block
-- Most migration tools need special handling for this
```

### Renaming a Column (Zero-Downtime)

Never rename directly in production. Use the expand-contract pattern:

```sql
-- Step 1: Add new column (migration 001)
ALTER TABLE users ADD COLUMN display_name TEXT;

-- Step 2: Backfill existing rows with a separate batched script, not a migration
-- (batched pattern in "Large Data Migrations" below)

-- Step 3: Update application code to read/write both columns
-- Deploy application changes

-- Step 4: Before the drop: backfill verified (this count is 0) and a backup taken
SELECT count(*) FROM users WHERE display_name IS DISTINCT FROM username;
-- Then stop writing to old column, drop it (migration 002)
ALTER TABLE users DROP COLUMN username;
```

### Removing a Column Safely

```sql
-- Step 1: Remove all application references to the column
-- Step 2: Deploy application without the column reference
-- Step 3: Drop column in next migration
ALTER TABLE orders DROP COLUMN legacy_status;
```

### Large Data Migrations

```sql
-- BAD: Updates all rows in one transaction (locks table)
UPDATE users SET normalized_email = LOWER(email);

-- GOOD: Batch update with progress, run as a separate script, not inside a migration:
-- COMMIT inside DO fails in a transaction block, and migration tools wrap each migration in one
DO $$
DECLARE
  batch_size INT := 10000;
  rows_updated INT;
BEGIN
  LOOP
    UPDATE users
    SET normalized_email = LOWER(email)
    WHERE id IN (
      SELECT id FROM users
      WHERE normalized_email IS NULL
        AND email IS NOT NULL -- processed rows must drop out, or the loop never ends
      LIMIT batch_size
      FOR UPDATE SKIP LOCKED
    );
    GET DIAGNOSTICS rows_updated = ROW_COUNT;
    RAISE NOTICE 'Updated % rows', rows_updated;
    EXIT WHEN rows_updated = 0;
    COMMIT;
  END LOOP;
END $$;
```

## Prisma (TypeScript/Node.js)

### Workflow

```bash
# Create migration from schema changes
npx prisma migrate dev --name add_user_avatar

# Apply pending migrations in production
npx prisma migrate deploy

# Reset database (dev only)
npx prisma migrate reset

# Generate client after schema changes
npx prisma generate
```

### Schema Example

```prisma
model User {
  id        String   @id @default(cuid())
  email     String   @unique
  name      String?
  avatarUrl String?  @map("avatar_url")
  createdAt DateTime @default(now()) @map("created_at")
  updatedAt DateTime @updatedAt @map("updated_at")
  orders    Order[]

  @@map("users")
  @@index([email])
}
```

### Custom SQL Migration

For operations Prisma cannot express (concurrent indexes):

```bash
# Create empty migration, then edit the SQL manually
npx prisma migrate dev --create-only --name add_email_index
```

```sql
-- migrations/20240115_add_email_index/migration.sql
-- Prisma cannot generate CONCURRENTLY, so we write it manually
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_email ON users (email);
```

## Drizzle (TypeScript/Node.js)

### Workflow

```bash
# Generate migration from schema changes
npx drizzle-kit generate

# Apply migrations
npx drizzle-kit migrate

# Push schema directly (dev only, no migration file)
npx drizzle-kit push
```

### Schema Example

```typescript
import { pgTable, text, timestamp, uuid, boolean } from "drizzle-orm/pg-core";

export const users = pgTable("users", {
  id: uuid("id").primaryKey().defaultRandom(),
  email: text("email").notNull().unique(),
  name: text("name"),
  isActive: boolean("is_active").notNull().default(true),
  createdAt: timestamp("created_at").notNull().defaultNow(),
  updatedAt: timestamp("updated_at").notNull().defaultNow(),
});
```

## Zero-Downtime Migration Strategy

For critical production changes, follow the expand-contract pattern:

```
Phase 1: EXPAND
  - Add new column/table (nullable or with default)
  - Deploy: app writes to BOTH old and new
  - Backfill existing data (separate batched script, not a migration)

Phase 2: MIGRATE
  - Deploy: app reads from NEW, writes to BOTH
  - Verify data consistency

Phase 3: CONTRACT
  - Deploy: app only uses NEW
  - Before the drop: backfill verified (rows where NEW IS NULL or differs = 0), backup taken
  - Drop old column/table in separate migration
```

### Timeline Example

```
Day 1: Migration adds new_status column (nullable)
Day 1: Deploy app v2 — writes to both status and new_status
Day 2: Run the batched backfill script for existing rows (not a migration)
Day 3: Deploy app v3 — reads from new_status only
Day 7: Backfill check is 0 and a backup is taken; migration drops old status column
```

## Anti-Patterns

| Anti-Pattern | Why It Fails | Better Approach |
|-------------|-------------|-----------------|
| Manual SQL in production | No audit trail, unrepeatable | Migration files for schema; a data backfill is a repo script as in principle 3 |
| Editing deployed migrations | Causes drift between environments | Create new migration instead |
| NOT NULL without default | Locks table, rewrites all rows | Add nullable, backfill by batched script, then `CHECK (col IS NOT NULL) NOT VALID` → `VALIDATE CONSTRAINT` → `SET NOT NULL` |
| Inline index on large table | Blocks writes during build | CREATE INDEX CONCURRENTLY |
| Backfill inside a migration | Hard to rollback, long transactions, locks | Separate batched script outside the migration |
| Dropping column before removing code | Application errors on missing column | Remove code first, drop column next deploy |
