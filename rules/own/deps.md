---
paths:
  - "**/package.json"
  - "**/{package-lock.json,npm-shrinkwrap.json,pnpm-lock.yaml,yarn.lock,bun.lock,bun.lockb}"
  - "**/{uv.lock,pyproject.toml,requirements*.txt}"
---
The project takes precedence. New and changed code only: don't rewrite or audit existing code, name a noticed violation in one line.
- New dependency: first make sure the package is genuine (exact name, repository, activity), no typosquat; no dependency if a few lines of code suffice.
- After adding or updating: `osv-scanner scan source -r . --format json > <log> 2>&1`, only a `jq` summary in the reply (package, ID, severity). Exit 1 means "found", not a failure.
- `MAL-*` or high severity in an added package: stop and tell me. Existing vulnerabilities: only name them, don't update without a request.
- Don't run `osv-scanner fix` or `npm audit fix --force`. The lockfile changes together with package.json.
- An npm or yarn project moves to pnpm only with my OK, in a session on that project, as its own commit: the risks to name before the OK and the steps are in `~/.claude/skills/new-project/upgrade.md`, step 2.
