---
paths:
  - "**/{Dockerfile*,*.Dockerfile,.dockerignore,nginx*.conf,render.yaml,Procfile,ecosystem.config.*}"
  - "**/*compose*.{yml,yaml}"
  - "**/.github/workflows/**"
  - "**/{infra,deploy,docker,nginx,backup}/**"
  - "**/*.sh"
  - "**/*.{service,timer}"
  - "**/*.{service,timer}.in"
---
The project takes precedence. New and changed code only: don't rewrite or audit existing code, name a noticed violation in one line.
- Don't silently change DB storage: a new volume name, compose project `name:` or bind path gives an empty DB; `down -v`, `volume rm`, `prune` erase data.
- Image tag as already in the repo (major), not `latest`; Node as in `.nvmrc`; Postgres major as in prod (a new major only via dump/restore); ask me for the prod platform and versions; `.dockerignore` with `.env*` and `.git`.
- With a DB: its healthcheck and `depends_on: condition: service_healthy`; an app healthcheck only if the app already listens on HTTP. Migrations before app start the way the repo already does it, not from several replicas at once.
- In prod the DB/Redis port is not exposed (only `127.0.0.1:`); logs with `max-size`.
- `docker compose config` only with `-q` (validation), `--services` or with its output in a file (`-o <file>`, `> file`): the full output contains secrets from env, so don't print that file either.
- CI: don't silently weaken gates (`continue-on-error`, skipped tests); name pipeline and dependency changes in the summary.
- Server checks: one ssh per step, as a script: `ssh host 'bash -s' < file`, with no `cd X &&` and no `; echo X_exit=$?`.
- Push, PR and merge: one command at the end of the step; no manual check that only repeats pre-push.
- Every command for me is labelled «на Mac» or «на сервері після ssh».
