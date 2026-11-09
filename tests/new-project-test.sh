#!/bin/bash
# Online gate of the new-project standard (skills/own/new-project). Each type+db is scaffolded into a scratch
# folder, installed with pnpm (each dependency's install script decided in pnpm-workspace.yaml, none run), passes
# `pnpm run check` and osv-scanner, builds its Docker image (no pnpm and no dev dependency in the runtime image; db
# types start Prisma without network) and starts with the generated docker-compose.yml:
#   http types become healthy (db types also answer /ready), and their request line logs the path without the query;
#   integration runs its job on schedule and with --once (db: the run reaches Postgres; a wrong DATABASE_URL
#   makes --once exit 1 with "job failed");
#   a bot without BOT_TOKEN stops naming the variable, with a wrong token it names the 401;
#   db types get a real migration that git keeps and the container applies;
#   db types also run the local path on a free POSTGRES_PORT: db:up, db:migrate (the client gets the new model),
#   db:down (the data volume stays);
#   http and integration exit 0 on SIGTERM, and the app logs no error line during the run;
#   nest keeps a single fastify, the adapter's, and passes the check again with a feature from
#   `nest g module|controller|service` (its spec files run,
#   dist has none) and answers /health from `pnpm run dev` (Nest CLI on tsc: the decorator metadata survives);
#   api answers /health from `pnpm run dev` (Node's watch mode, tsx as the loader), and one Ctrl+C sent to the whole
#   process group, as a terminal does, while a request is still open: the app answers that request, shuts down once
#   and on its own, and the group stops;
#   api+none and integration+prisma start from a brief: brief/ waits in the folder, scaffold leaves it as it was,
#   the card and docs/decisions.md say the server and CI/CD are not decided, git, ESLint and the Docker build
#   context leave brief/ out, and the tool's folder and the card stay out of that context too;
#   fullstack+prisma+pgvector+budget carries both modules: the Postgres of the image has the extension and answers a
#   vector query, a broken spending limit stops the start with its name;
#   every combo: no file of the first commit names the tool in its text or path, with the global git excludes off.
# `modes` runs neither pnpm nor Docker, though the checks below still want them: a folder an IDE left (the list, the refusal, the move into a backup with what
# the IDE staged forgotten, then the scaffold and the branch renamed to main), an existing repository (the refusal, the card, docs, STATUS and gap
# report, no file of the project changed, a second run keeps everything), a brief from the chat (brief/ made by the skill)
# and docs-sync in a docs repo of the scratch root (a new project and an adopted one connected, the first commit takes
# docs/ into git and its copy goes, a folder without git gets a registry row).
# Needs network (npm registry, Docker Hub, api.telegram.org), the local Docker, the Node of versions.json in nvm with
# its pnpm, osv-scanner, gitleaks, jq and curl.
#   bash tests/new-project-test.sh [modes api+none nest+prisma ...]     default: all of them
# Env: NPT_ROOT (scratch root; default a new mktemp -d), pnpm_config_store_dir (pnpm store, read by pnpm itself),
#      NPT_KEEP=1 keeps the project folders of passed combos (they are removed by default; logs stay).
# Every compose project, network and image gets a unique npt-<run>- name and is removed with its volumes;
# anything left behind fails the combo.
set -u
HERE=$(cd "$(dirname "$0")/.." && pwd)
SCAFFOLD="$HERE/skills/own/new-project/scaffold.py"
BRIEF_CHECK="$HERE/skills/own/new-project/brief_check.py"
OSV_SUMMARY="$HERE/skills/own/new-project/osv_summary.py"
VERSIONS="$HERE/skills/own/new-project/versions.json"
RUN=$(od -An -N3 -tx1 /dev/urandom | tr -d ' \n')
ALL_COMBOS="modes api+none api+prisma nest+none nest+prisma fullstack+none fullstack+prisma integration+none \
integration+prisma bot+none bot+prisma fullstack+prisma+pgvector+budget"
# Combos that start from a brief: an HTTP one and a scheduled one with a DB (both deploy texts of the card)
BRIEF_COMBOS="api+none integration+prisma"
# brief/notes.js does not parse: ESLint fails the check if it reads brief/
BRIEF_JS='const brief = ;'
# A token in the right format that Telegram rejects (the bot must name the 401); built here, so the source holds
# nothing that looks like a token
FAKE_BOT_TOKEN="123456789:$(printf '%035d' 0 | tr 0 A)"
COMBOS=("$@")
# shellcheck disable=SC2206  # word splitting of the fixed list is intended
[ "${#COMBOS[@]}" -gt 0 ] || COMBOS=($ALL_COMBOS)
for combo in "${COMBOS[@]}"; do
  case " $ALL_COMBOS " in *" $combo "*) ;; *) echo "FAIL: unknown combo '$combo' (one of: $ALL_COMBOS)"; exit 1 ;; esac
done
for tool in docker osv-scanner gitleaks jq git curl; do
  command -v "$tool" >/dev/null || { echo "FAIL: $tool not found"; exit 1; }
done
ROOT=${NPT_ROOT:-$(mktemp -d "${TMPDIR:-/tmp}/npt.XXXXXX")}
mkdir -p "$ROOT" && ROOT=$(cd "$ROOT" && pwd) || { echo "FAIL: cannot use $ROOT"; exit 1; }
export NVM_DIR="$HOME/.nvm"
# shellcheck disable=SC1091
. "$NVM_DIR/nvm.sh" --no-use || { echo "FAIL: nvm not found"; exit 1; }
STD_NODE=$(jq -r .node "$VERSIONS") || { echo "FAIL: cannot read $VERSIONS"; exit 1; }
nvm use "$STD_NODE" >/dev/null || { echo "FAIL: no Node $STD_NODE in nvm"; exit 1; }
command -v pnpm >/dev/null \
  || { echo "FAIL: no pnpm for Node $STD_NODE (npm install --global --allow-scripts=pnpm pnpm@$(jq -r .pnpm "$VERSIONS"))"; exit 1; }
# Only the local Docker: a remote daemon or builder would get these containers and their test passwords
[ -z "${DOCKER_HOST:-}" ] || { echo "FAIL: DOCKER_HOST is set; the gate runs only against the local Docker"; exit 1; }
case "$(docker context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null)" in
  unix://*) ;;
  *) echo "FAIL: the current Docker context is not a local socket"; exit 1 ;;
esac
docker info >/dev/null 2>&1 || { echo "FAIL: Docker is not running"; exit 1; }
# Shell values would override the test .env in compose and in the apps, or pnpm settings of the project
for var in $(compgen -e); do
  case $var in
    COMPOSE_*|POSTGRES_*|APP_*|TRAEFIK_*|BUILDX_*|BUILDKIT_*) unset "$var" ;;
    pnpm_config_store_dir|PNPM_CONFIG_STORE_DIR) ;;
    npm_config_*|NPM_CONFIG_*|pnpm_config_*|PNPM_CONFIG_*|COREPACK_*) unset "$var" ;;
  esac
done
# CI would make pnpm install want a lockfile that does not exist yet
unset PORT HOST DATABASE_URL BOT_TOKEN CRON_SCHEDULE LOG_LEVEL NODE_ENV TZ CI
echo "new-project-test: run $RUN, logs in $ROOT"
fails=0

dc() { docker compose -p "$name" "$@"; }

# wait_for <seconds> <command...>: poll once a second until the command succeeds
wait_for() {
  local left=$1; shift
  until "$@" >/dev/null 2>&1; do
    left=$((left - 1)); [ "$left" -gt 0 ] || return 1; sleep 1
  done
}

logs_have() {  # the whole log first, then grep: grep -q on a pipe would cut compose off with SIGPIPE
  local out
  out=$(dc logs --no-color app 2>&1) || return 1
  grep -q "$1" <<< "$out"
}

free_port() {  # a local TCP port nothing listens on right now
  python3 -I -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'
}

write_env() {  # .env for the smoke start: the example plus test values; the password is never printed
  local db_name=${name//-/_} pass port
  pass=$(od -An -N12 -tx1 /dev/urandom | tr -d ' \n')
  # A free local port for the dev database, as the README asks when 5432 is taken: POSTGRES_PORT and DATABASE_URL
  port=$(free_port) || return 1
  grep -v -E '^(APP_DOMAIN|TRAEFIK_NETWORK|TRAEFIK_CERTRESOLVER|CRON_SCHEDULE|POSTGRES_PASSWORD|POSTGRES_PORT|DATABASE_URL)=' \
    .env.example > .env
  printf 'APP_DOMAIN=%s.test\nTRAEFIK_NETWORK=%s-proxy\nTRAEFIK_CERTRESOLVER=none\nCRON_SCHEDULE=* * * * * *\n' "$name" "$name" >> .env
  printf 'POSTGRES_PASSWORD=%s\nPOSTGRES_PORT=%s\nDATABASE_URL=postgresql://%s:%s@127.0.0.1:%s/%s\n' \
    "$pass" "$port" "$db_name" "$pass" "$port" "$db_name" >> .env
}

add_migration() {  # a model and its migration, as `pnpm run db:migrate` would write them: git must keep the migration
  local sql=prisma/migrations/0_init/migration.sql rc
  mkdir -p prisma/migrations/0_init || return 1
  printf '\nmodel NptCheck {\n  id Int @id\n}\n' >> prisma/schema.prisma
  printf 'CREATE TABLE "NptCheck" ("id" INTEGER NOT NULL PRIMARY KEY);\n' > "$sql"
  printf '# Please do not edit this file manually\nprovider = "postgresql"\n' > prisma/migrations/migration_lock.toml
  git init -q . || return 1
  git -c core.excludesFile=/dev/null check-ignore -q "$sql"; rc=$?
  [ "$rc" -eq 1 ] || { echo "    .gitignore hides $sql (check-ignore exit $rc)"; return 1; }
}

put_brief() {  # the client's files wait in brief/ of the new folder before the scaffold
  mkdir -p "$dir/brief/scan" "$dir/.claude" || return 1
  printf '{}\n' > "$dir/.claude/settings.local.json" || return 1
  printf '%s\n' "$BRIEF_JS" > "$dir/brief/notes.js" && printf 'npt brief\n' > "$dir/brief/scan/tz.md"
}

brief_kept() {  # after the scaffold: brief/ as it was, the card and decisions say what is not decided, git ignores it
  local rel
  [ "$(cat brief/notes.js)" = "$BRIEF_JS" ] && [ "$(cat brief/scan/tz.md)" = 'npt brief' ] \
    || { echo "    scaffold changed brief/"; return 1; }
  grep -q 'сервер і CI/CD не вирішено' CLAUDE.local.md && grep -q 'сервер і CI/CD не вирішено' docs/decisions.md \
    || { echo "    the card or docs/decisions.md does not say that the server and CI/CD are not decided"; return 1; }
  git init -q . || return 1
  for rel in brief/notes.js brief/scan/tz.md; do
    git -c core.excludesFile=/dev/null check-ignore -q "$rel" || { echo "    git does not ignore $rel"; return 1; }
  done
}

brief_outside_image() {  # the Docker build context leaves brief/ out: the build stage (COPY . .) has no /app/brief
  docker build -q --target build -t "$name:ctx" . > /dev/null || return 1
  # package.json first: a changed WORKDIR must fail the check, not pass it
  docker run --rm --network none --entrypoint sh "$name:ctx" -c '[ -f /app/package.json ] && [ -f /app/pnpm-workspace.yaml ] && [ ! -e /app/.npmrc ] && [ ! -e /app/brief ] && [ ! -e /app/.claude ] && [ ! -e /app/CLAUDE.local.md ]' \
    || { echo "    brief/, the tool's folder or the card reached the Docker build context"; return 1; }
  docker image rm "$name:ctx" > /dev/null
}

ddc() { docker compose -p "$name-dev" -f docker-compose.dev.yml "$@"; }

kill_tree() {  # <pid>: stops a process and its children, by PID only (pnpm runs nest, nest runs node)
  local child
  for child in $(pgrep -P "$1"); do kill_tree "$child"; done
  kill "$1" 2>/dev/null
}

nest_generate() {  # nest: a feature from `nest g`, as the README tells, passes the whole check with its spec files
  local out rc schematic
  for schematic in module controller service; do
    pnpm exec nest g "$schematic" npt-smoke < /dev/null || return 1
  done
  out=$(pnpm run check 2>&1); rc=$?
  printf '%s\n' "$out" | sed 's/^/    check after nest g: /'
  [ "$rc" -eq 0 ] || return 1
  # A Vitest log names no test files, so ask Vitest which files it runs
  out=$(pnpm exec vitest list --filesOnly 2>&1) || { printf '%s\n' "$out" | sed 's/^/    /'; return 1; }
  grep -q 'src/npt-smoke/npt-smoke.service.spec.ts' <<< "$out" \
    || { echo "    Vitest does not run the spec file of nest g"; return 1; }
  [ -e dist/npt-smoke/npt-smoke.service.js ] || { echo "    the build left out the service of nest g"; return 1; }
  [ ! -e dist/npt-smoke/npt-smoke.service.spec.js ] || { echo "    the build put a spec file into dist"; return 1; }
  grep -q 'NptSmokeModule' src/app.module.ts || { echo "    nest g did not add the module to src/app.module.ts"; return 1; }
}

dev_get() {  # <url>: the body of a local answer; no proxy, and a socket that stays silent cannot hang the gate
  curl -sS --noproxy '*' --max-time 3 "$1"
}

dev_up() {  # <url>: /health of pnpm run dev answers ok within 90 s; fails at once when pnpm run dev has exited
  local left=90 body
  while :; do
    body=$(dev_get "$1/health" 2>/dev/null) && [[ $body == *'"status":"ok"'* ]] && return 0
    kill -0 "$dev_pid" 2>/dev/null || { echo "    pnpm run dev exited before /health answered"; return 1; }
    left=$((left - 1)); [ "$left" -gt 0 ] || { echo "    pnpm run dev did not answer /health within 90 s"; return 1; }
    sleep 1
  done
}

dev_nest() {  # nest: `pnpm run dev` compiles with the Nest CLI, answers on a free port with DI working, then stops
  local port url body ok=0
  port=$(free_port) || return 1
  url="http://127.0.0.1:$port"
  # The shell PORT wins over .env (node --env-file keeps variables that are already set)
  PORT=$port pnpm run dev > "$ROOT/$combo.nest-dev.log" 2>&1 &
  dev_pid=$!
  if dev_up "$url"; then
    # A missing route gets its 404 from ErrorsFilter, which receives HttpAdapterHost by DI: a compiler that drops
    # the decorator metadata (tsx) turns it into a 500, while /health still answers
    body=$(dev_get "$url/npt-missing" 2>&1)
    [[ $body == *'"statusCode":404'* ]] || { echo "    a missing route did not get the 404 of ErrorsFilter: $body"; ok=1; }
  else
    ok=1
  fi
  kill_tree "$dev_pid"; wait "$dev_pid" 2>/dev/null; dev_pid=
  # The Nest CLI clears the screen in watch mode: no escape sequences into the terminal
  [ "$ok" -eq 0 ] || { tail -n 20 "$ROOT/$combo.nest-dev.log" | tr -d '\033'; return 1; }
  # Stopped means no answer at all: a 503 from a server that is closing still counts as running
  if wait_for 10 sh -c "! curl -sS --noproxy '*' --max-time 2 -o /dev/null '$url/health'"; then return 0; fi
  echo "    pnpm run dev still answers after it was stopped"; return 1
}

dev_node() {  # api: `pnpm run dev` answers on a free port. One Ctrl+C reaches the app from the terminal and the
              # watch mode while a request is still open: the app waits for that request, answers it and shuts down
              # once (under tsx watch the second copy of the signal killed the app halfway, the request with it)
  local port url n answer='' ok=0 log="$ROOT/$combo.pnpm-dev.log"
  port=$(free_port) || return 1
  url="http://127.0.0.1:$port"
  set -m   # its own process group, like a foreground job in a terminal
  PORT=$port pnpm run dev > "$log" 2>&1 &
  dev_pid=$!
  set +m
  # Without a group of its own the Ctrl+C below would go nowhere, and the wait at the end would hang
  if ! kill -0 -- "-$dev_pid" 2>/dev/null; then
    echo "    pnpm run dev did not get a process group of its own"
    kill_tree "$dev_pid"; wait "$dev_pid" 2>/dev/null; dev_pid=; return 1
  fi
  dev_up "$url" || ok=1
  # Headers not finished yet: closing the server has to wait for the rest of this request
  if [ "$ok" -eq 0 ] && { exec 3<>"/dev/tcp/127.0.0.1/$port"; } 2>/dev/null; then
    printf 'GET /health HTTP/1.1\r\nHost: localhost\r\n' >&3
    kill -INT -- "-$dev_pid" 2>/dev/null
    sleep 2
    kill -0 -- "-$dev_pid" 2>/dev/null || { echo "    Ctrl+C killed pnpm run dev while a request was open"; ok=1; }
    printf 'Connection: close\r\n\r\n' >&3 2>/dev/null
    IFS= read -r -t 5 answer <&3 2>/dev/null
    exec 3<&-
    [[ $answer == "HTTP/1.1 "* ]] || { echo "    the open request got no answer"; ok=1; }
  else
    [ "$ok" -ne 0 ] || { echo "    could not open a request to pnpm run dev"; ok=1; }
    kill -INT -- "-$dev_pid" 2>/dev/null
  fi
  if ! wait_for 15 sh -c "! kill -0 -- -$dev_pid"; then
    echo "    pnpm run dev still runs 15 s after Ctrl+C"; kill -KILL -- "-$dev_pid" 2>/dev/null; ok=1
  fi
  wait "$dev_pid" 2>/dev/null; dev_pid=
  n=$(grep -c '"msg":"shutting down"' "$log")
  [ "$n" = 1 ] || { echo "    one Ctrl+C shut the app down $n times"; ok=1; }
  if grep -q -E 'shutdown (timed out|failed)' "$log"; then echo "    the app did not close on its own"; ok=1; fi
  [ "$ok" -eq 0 ] || { tail -n 20 "$log" | tr -d '\033'; return 1; }
}

dev_migrate() {  # [args...]: db:migrate with its output kept in $out; pnpm appends the args, with no -- before them
  local rc
  # No stdin: a Prisma prompt (schema and SQL drifted apart) fails the gate instead of hanging it
  out=$(pnpm run db:migrate "$@" < /dev/null 2>&1); rc=$?
  printf '%s\n' "$out" | sed 's/^/    db:migrate: /'
  return "$rc"
}

dev_db() {  # db types, the local path of the README: db:up waits for Postgres on POSTGRES_PORT, db:migrate applies
            # the migrations and refreshes the Prisma client, `db:migrate --name` creates a named migration
            # without a prompt, db:down stops Postgres and keeps its data
  local out
  pnpm run db:up || return 1
  dev_migrate || return 1
  grep -q '0_init' <<< "$out" || { echo "    db:migrate did not apply 0_init"; return 1; }
  grep -rqs 'NptCheck' src/generated/prisma || { echo "    db:migrate left the Prisma client without the new model"; return 1; }
  printf '\nmodel NptNext {\n  id Int @id\n}\n' >> prisma/schema.prisma
  dev_migrate --name npt_next || return 1
  compgen -G 'prisma/migrations/*_npt_next/migration.sql' > /dev/null \
    || { echo "    db:migrate --name npt_next created no such migration"; return 1; }
  pnpm run db:down || return 1
  [ -z "$(ddc ps -aq)" ] || { echo "    db:down left the dev containers"; return 1; }
  [ -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$name-dev")" ] \
    || { echo "    db:down removed the dev data volume"; return 1; }
}

pnpm_settings() {  # pnpm reads the standard's pnpm-workspace.yaml: an unlisted install script stops the install, every
                   # listed one is off (pnpm prints null for allowBuilds it did not read), no global flag lifts the stop,
                   # and the pnpm that runs is the one of packageManager
  [ "$(pnpm config get strictDepBuilds)" = true ] && [ "$(pnpm config get dangerouslyAllowAllBuilds)" = false ] \
    && pnpm config get allowBuilds --json | jq -e 'type == "object" and all(.[]; . == false)' > /dev/null \
    || { echo "    pnpm-workspace.yaml: strictDepBuilds, dangerouslyAllowAllBuilds or allowBuilds is not in effect"; return 1; }
  [ "pnpm@$(pnpm --version)" = "$(jq -r .packageManager package.json)" ] \
    || { echo "    pnpm $(pnpm --version) runs, not $(jq -r .packageManager package.json) of package.json"; return 1; }
}

one_fastify() {  # nest: package.json names fastify at the pin of @nestjs/platform-fastify, so pnpm keeps one copy
  [ "$(grep -oE '^  fastify@[^:(]+' pnpm-lock.yaml | sort -u | grep -c .)" = 1 ] \
    || { echo "    pnpm-lock.yaml has no fastify or two: nest_fastify in versions.json is not the adapter's pin"; return 1; }
}

image_lean() {  # the runtime image holds the pnpm layout of production dependencies only (vitest and typescript are dev
                # ones of every type) and no pnpm; with a DB, Prisma answers without network, so the start downloads
                # no engine
  docker run --rm --network none --user root --entrypoint sh "$name:check" -c \
    '[ -d /app/node_modules/.pnpm ] && [ ! -e /app/node_modules/vitest ] && [ ! -e /app/node_modules/typescript ] \
     && ! command -v pnpm' \
    || { echo "    the runtime image has a dev dependency or pnpm, or no pnpm layout"; return 1; }
  [ "$db" != prisma ] || docker run --rm --network none --entrypoint sh "$name:check" -c './node_modules/.bin/prisma version' > /dev/null \
    || { echo "    Prisma in the runtime image needs the network (no engine)"; return 1; }
}

osv_check() {  # <out>: the rule of the standard, osv_summary.py: HIGH only in dev dependencies warns, the rest stops
  local out=$1 rc found want
  osv-scanner scan source -L pnpm-lock.yaml --format json > "$out" 2> "$out.err"; rc=$?
  case $rc in
    0|1) ;;   # 1 means "found", not an error
    *) echo "    osv-scanner failed (exit $rc), see $out.err"; return 1 ;;
  esac
  # The scanner read the whole lockfile, not only its first document (pnpm's own pin): a package for each snapshot
  found=$(sed -n 's/.* file and found \([0-9][0-9]*\) packages.*/\1/p' "$out.err" | tail -1)
  want=$(awk '/^snapshots:/ { s = 1; next } /^[^ ]/ { s = 0 } s && /^  [^ ]/ { n++ } END { print n + 0 }' pnpm-lock.yaml)
  [ "$found" = "$want" ] || { echo "    osv-scanner read ${found:-no} packages, pnpm-lock.yaml holds $want"; return 1; }
  if [ "$rc" -eq 0 ]; then
    jq -e '.results | type == "array"' "$out" > /dev/null || { echo "    osv-scanner exit 0 without a result in $out"; return 1; }
    return 0
  fi
  python3 -I "$OSV_SUMMARY" "$out" pnpm-lock.yaml | sed 's/^/    osv: /'
  return "${PIPESTATUS[0]}"
}

first_commit_clean() {  # no file the first commit would hold names the tool; with the global excludes off, the card
                        # stays out by the project's own .gitignore. Only those excludes hide .claude/: a line for it
                        # would put the tool's name into .gitignore
  local hits rc
  git init -q . || return 1
  hits=$(git -c core.excludesFile=/dev/null grep --untracked -il -E 'claude|anthropic'); rc=$?
  [ "$rc" = 1 ] || { echo "    the first commit would name the tool (git grep exit $rc): $hits"; return 1; }
  hits=$(git -c core.excludesFile=/dev/null ls-files -co --exclude-standard) || return 1
  grep -q '^package\.json$' <<< "$hits" || { echo "    git lists no files of the project"; return 1; }
  hits=$(grep -iE 'claude|anthropic' <<< "$hits" | grep -v '^\.claude/')
  [ -z "$hits" ] || { echo "    the first commit would hold: $hits"; return 1; }
}

vector_ready() {  # module pgvector: the image has the extension, the migration enabled it, a vector query answers
  local out
  out=$(dc exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT '"'"'[1,2,3]'"'"'::vector <-> '"'"'[1,2,4]'"'"'::vector"')
  [ "$out" = 1 ] || { echo "    the vector query gave: $out"; return 1; }
}

budget_guard() {  # module budget: a broken limit stops the start and names the setting
  local out rc
  out=$(DATABASE_URL=postgresql://npt@127.0.0.1:1/npt PAID_API_BUDGET_USD=abc \
    pnpm exec tsx -e 'import("./src/config.ts").catch((e) => { console.error(e.message); process.exit(1); })' 2>&1); rc=$?
  [ "$rc" -ne 0 ] && grep -q 'PAID_API_BUDGET_USD must be USD' <<< "$out" \
    || { echo "    a broken PAID_API_BUDGET_USD did not stop the start (exit $rc): $out"; return 1; }
}

app_fetch() {  # <path> [text]: the app answers 2xx on the path inside its container (and the body has the text)
  dc exec -T app node -e "fetch('http://127.0.0.1:3000$1').then(async (r) => process.exit(r.ok && (await r.text()).includes(process.argv[1]) ? 0 : 1), () => process.exit(1))" "${2:-}"
}

query_left_out() {  # http types: Fastify's request line keeps the path, the query (a token, an email) stays out of the log
  local url_path="/npt-query-$RUN"
  dc exec -T app node -e "fetch('http://127.0.0.1:3000$url_path?npt=q$RUN').then(() => process.exit(0), () => process.exit(1))" \
    || { echo "    the app did not answer $url_path"; return 1; }
  # Open quote: the line counts with or without the query, which is checked next
  wait_for 10 logs_have "\"url\":\"$url_path" || { echo "    no request line for $url_path in the app log"; return 1; }
  query_not_logged
}

query_not_logged() {  # no line of the app log so far carries the query of query_left_out's request
  local out
  out=$(dc logs --no-color app 2>&1) || { echo "    could not read the app log"; return 1; }
  if grep -q "npt=q$RUN" <<< "$out"; then echo "    the query of a request reached the app log"; return 1; fi
}

migrated() {  # db types: the container applies the test migration on start (integration has no healthcheck to wait on)
  [ "$db" != prisma ] || wait_for 60 logs_have 'successfully applied' \
    || { echo "    migration 0_init was not applied within 60 s"; dc logs --tail 20 app; return 1; }
}

stops_cleanly() {  # docker compose stop sends SIGTERM; the app must exit 0 on its own within stop_grace_period
  local code
  dc stop app || return 1
  code=$(docker inspect -f '{{.State.ExitCode}}' "$(dc ps -aq app)") || return 1
  echo "    app exit code after SIGTERM: $code"
  [ "$code" = 0 ]
}

no_app_errors() {  # no error line from the app during the run (pino level 50+, our "error", Nest's "fatal")
  local out
  out=$(dc logs --no-color app 2>&1) || return 1
  if grep -E '"level":("error"|"fatal"|5[0-9]|60)' <<< "$out"; then echo "    the app logged errors (above)"; return 1; fi
}

smoke() {  # <type> <db>; runs inside the project folder
  local kind=$1 db=$2 out rc started
  dc config -q || return 1
  if [ "$db" = prisma ]; then ddc config -q || return 1; fi
  case "$kind" in
    api|nest|fullstack)
      docker network create "$name-proxy" >/dev/null || return 1
      dc up -d --wait --wait-timeout 180 || return 1
      migrated || return 1
      app_fetch /health || return 1
      if [ "$db" = prisma ]; then app_fetch /ready || return 1; fi
      if [ "$kind" = fullstack ]; then app_fetch / 'id="root"' || return 1; fi
      case "+$mods+" in *+pgvector+*) vector_ready || return 1 ;; esac
      query_left_out || return 1
      # The whole run once more: a line written later, while the app stops, must not carry the query either
      stops_cleanly && no_app_errors && query_not_logged || return 1 ;;
    integration)
      dc up -d --wait --wait-timeout 180 || return 1
      migrated || return 1
      wait_for 60 logs_have "job finished" || { echo "    no finished run within 60 s"; dc logs --tail 20 app; return 1; }
      out=$(dc exec -T app node dist/main.js --once 2>&1); rc=$?
      printf '%s\n' "$out" | sed 's/^/    once: /'
      [ "$rc" -eq 0 ] && grep -q 'job finished' <<< "$out" || return 1
      if [ "$db" = prisma ]; then
        grep -q 'database time' <<< "$out" || return 1
        # A user that does not exist and no password: Postgres refuses the connection
        started=$SECONDS
        out=$(dc exec -T -e DATABASE_URL="postgresql://npt-nobody@db:5432/npt" app node dist/main.js --once 2>&1); rc=$?
        printf '%s\n' "$out" | sed 's/^/    once (wrong DATABASE_URL): /'
        [ "$rc" -eq 1 ] && grep -q '"message":"job failed"' <<< "$out" || return 1
        # A refused login leaves a socket that Postgres keeps for up to a minute: --once must not wait for it
        [ $((SECONDS - started)) -lt 20 ] || { echo "    --once took $((SECONDS - started)) s to exit after failing"; return 1; }
      fi
      stops_cleanly && no_app_errors || return 1 ;;
    bot)
      out=$(dc run --rm app 2>&1); rc=$?
      printf '%s\n' "$out" | sed 's/^/    bot (no token): /'
      [ "$rc" -ne 0 ] && grep -q 'BOT_TOKEN is not set' <<< "$out" || return 1
      if [ "$db" = prisma ]; then grep -q 'successfully applied' <<< "$out" || return 1; fi
      out=$(BOT_TOKEN=$FAKE_BOT_TOKEN dc run --rm -e BOT_TOKEN app 2>&1); rc=$?
      printf '%s\n' "$out" | sed 's/^/    bot (wrong token): /'
      [ "$rc" -eq 1 ] && grep -q 'Telegram rejected BOT_TOKEN (401)' <<< "$out" || return 1 ;;
  esac
}

leftovers() {  # prints whatever this combo left in Docker
  local project label
  for project in "$name" "$name-dev"; do
    label="label=com.docker.compose.project=$project"
    docker ps -aq --filter "$label"
    docker volume ls -q --filter "$label"
    docker network ls -q --filter "$label"
  done
  docker network inspect "$name-proxy" >/dev/null 2>&1 && echo "$name-proxy"
  docker image ls -q --filter "reference=$name*"
}

cleanup() {  # removes the combo's containers, volumes, networks and images; returns 1 if anything is left
  (cd "$dir" && dc down -v --remove-orphans --rmi local) > "$ROOT/$combo.cleanup.log" 2>&1 \
    || echo "    cleanup: compose down failed, see $ROOT/$combo.cleanup.log"
  if [ -f "$dir/docker-compose.dev.yml" ]; then
    (cd "$dir" && ddc down -v --remove-orphans) >> "$ROOT/$combo.cleanup.log" 2>&1 \
      || echo "    cleanup: dev compose down failed, see $ROOT/$combo.cleanup.log"
  fi
  docker network rm "$name-proxy" >/dev/null 2>&1
  docker image rm "$name:check" "$name:ctx" >/dev/null 2>&1
  docker info >/dev/null 2>&1 || { echo "    cleanup: Docker is not reachable, leftovers unknown"; return 1; }
  local left
  left=$(leftovers 2>/dev/null)
  [ -z "$left" ] || { echo "    cleanup: left in Docker:"; printf '%s\n' "$left" | sed 's/^/      /'; return 1; }
}

# ---------- modes: no pnpm, no Docker ----------

mode_is() {  # <folder> <mode>: what --inspect says about the folder
  python3 -I "$SCAFFOLD" "$1" --inspect | grep -q "^scaffold: mode $2\b" \
    || { echo "    --inspect of $1 does not say $2:"; python3 -I "$SCAFFOLD" "$1" --inspect | sed 's/^/    /'; return 1; }
}

refused() {  # <scaffold arguments>: exit 1 with scaffold.py's own reason; argparse and a crash don't count
  local err rc
  err=$(python3 -I "$SCAFFOLD" "$@" 2>&1 > /dev/null); rc=$?
  [ "$rc" = 1 ] && grep -q '^scaffold: ' <<< "$err" || { echo "    scaffold.py $*: exit $rc, $err"; return 1; }
}

save_refused() {  # <paths file> <brief folder>: exit 1, a crash doesn't count
  python3 -I "$BRIEF_CHECK" save "$1" "$2" > /dev/null 2>&1
  [ "$?" = 1 ]
}

new_args() {  # the options of a plain project of the standard
  printf '%s\n' --type api --db none --risk R1 --data V0 --stage demo
}

identity=(-c user.name=npt -c user.email=npt@example.test)

put_template() {  # <folder>: what a project template of an IDE leaves, with its placeholder and its AGENTS.md
  mkdir -p "$1/.idea" "$1/src" "$1/docs" || return 1
  printf '<project/>\n' > "$1/.idea/workspace.xml"
  # shellcheck disable=SC2016  # the placeholder of the template, not a shell variable
  printf '{"name": "${PROJECT_NAME}"}\n' > "$1/package.json"
  printf '{}\n' > "$1/tsconfig.json"; printf 'dist\n' > "$1/.gitignore"; printf 'console.log(1);\n' > "$1/src/index.ts"
  printf 'template rules\n' > "$1/AGENTS.md"; printf '# Decisions\n' > "$1/docs/decisions.md"
}

case_ide() {  # <commits of the template>: the IDE staged its template; the owner's yes moves it, nothing is deleted
  local commits=$1 app="$ROOT/modes/ide-$1" backup="$ROOT/modes/backup-$1" dest rel
  put_template "$app" || return 1
  git -C "$app" init -q -b master || return 1
  git -C "$app" add package.json || return 1
  if [ "$commits" = 1 ]; then git -C "$app" add -A && git -C "$app" "${identity[@]}" commit -q -m template || return 1; fi
  mode_is "$app" ide || return 1
  # shellcheck disable=SC2046  # new_args prints one word per line
  refused "$app" $(new_args) || return 1
  dest=$(python3 -I "$SCAFFOLD" "$app" --move-ide --backup-dir "$backup" | sed -n 's/^scaffold: moved [0-9]* entries to \(.*\); nothing deleted$/\1/p')
  [ -n "$dest" ] && [ -d "$dest" ] || { echo "    --move-ide named no backup folder"; return 1; }
  for rel in package.json tsconfig.json .gitignore src/index.ts AGENTS.md docs/decisions.md; do
    [ -f "$dest/$rel" ] || { echo "    $rel is not in the backup"; return 1; }
    [ ! -e "$app/$rel" ] || { echo "    $rel stayed in the folder"; return 1; }
  done
  grep -q 'PROJECT_NAME' "$dest/package.json" || { echo "    the backup changed package.json"; return 1; }
  [ -f "$app/.idea/workspace.xml" ] || { echo "    the move took .idea"; return 1; }
  mode_is "$app" new || return 1
  if [ "$commits" = 0 ]; then
    [ -z "$(git -C "$app" ls-files)" ] || { echo "    the index still holds the template"; return 1; }
  else
    [ "$(git -C "$app" rev-list --count HEAD)" = 1 ] || { echo "    the move changed the history"; return 1; }
  fi
  # shellcheck disable=SC2046  # new_args prints one word per line
  python3 -I "$SCAFFOLD" "$app" $(new_args) --name npt-ide > /dev/null || { echo "    no scaffold after the move"; return 1; }
  python3 -I "$SCAFFOLD" "$app" --init-git > /dev/null || { echo "    --init-git failed"; return 1; }
  [ "$(git -C "$app" symbolic-ref --short HEAD)" = main ] || { echo "    the branch of the IDE stayed"; return 1; }
  grep -q '^Етап: демо$' "$app/CLAUDE.local.md" || { echo "    the card has no stage"; return 1; }
  grep -q 'demo-gates.md' "$app/CLAUDE.local.md" || { echo "    the card has no demo gates"; return 1; }
  grep -q 'npt-ide' "$app/package.json" || { echo "    package.json is not the standard's"; return 1; }
}

put_project() {  # <folder>: a project with its own life: two commits, loose versions, a root Dockerfile, a public DB port
  mkdir -p "$1/src" || return 1
  printf '{"name": "old", "scripts": {"start": "node ."}, "dependencies": {"fastify": "^5.0.0"}}\n' > "$1/package.json"
  printf 'node_modules\n' > "$1/.gitignore"; printf 'console.log(1);\n' > "$1/src/main.js"
  printf 'FROM node:latest\nCMD ["node", "src/main.js"]\n' > "$1/Dockerfile"
  printf 'services:\n  db:\n    image: postgres:18\n    ports:\n      - "5432:5432"\n' > "$1/docker-compose.yml"
  git -C "$1" init -q -b main && git -C "$1" add -A && git -C "$1" "${identity[@]}" commit -q -m first || return 1
  printf 'console.log(2);\n' > "$1/src/main.js"
  git -C "$1" add -A && git -C "$1" "${identity[@]}" commit -q -m second
}

case_existing() {  # no scaffold and no move; the adoption writes only new files, and a second run keeps them
  local app="$ROOT/modes/existing" head texts="$ROOT/modes/texts.json" rel gaps
  put_project "$app" || return 1
  head=$(git -C "$app" rev-parse HEAD)
  mode_is "$app" existing || return 1
  # shellcheck disable=SC2046  # new_args prints one word per line
  refused "$app" $(new_args) || return 1
  refused "$app" --move-ide --backup-dir "$ROOT/modes/backup-existing" || return 1
  [ ! -e "$ROOT/modes/backup-existing" ] || { echo "    the refused move made a backup folder"; return 1; }
  printf '{"not_add": "нові сервіси", "hatches": "немає", "numbers": "20 замовлень на день"}\n' > "$texts"
  python3 -I "$SCAFFOLD" "$app" --adopt --risk R1 --data V0 --stage pilot --tier T1 --texts "$texts" > "$ROOT/modes/adopt.out" \
    || { echo "    --adopt failed"; return 1; }
  for rel in CLAUDE.local.md docs/decisions.md docs/integrations.md docs/deployment.md docs/standard-gaps.md \
      .claude/state/STATUS.md .claude/state/STATUS-archive.md; do
    [ -f "$app/$rel" ] || { echo "    --adopt did not create $rel"; return 1; }
  done
  [ "$(git -C "$app" rev-parse HEAD)" = "$head" ] && [ -z "$(git -C "$app" diff --stat)" ] \
    || { echo "    --adopt changed the project"; return 1; }
  grep -q '^Етап: пілот$' "$app/CLAUDE.local.md" && grep -q 'Fastify 5' "$app/CLAUDE.local.md" && grep -q '`main`' "$app/CLAUDE.local.md" \
    || { echo "    the card does not say the stage and the facts of the repository"; return 1; }
  gaps=$(grep -c '^- \[ \]' "$app/docs/standard-gaps.md")
  [ "$gaps" -ge 10 ] || { echo "    the gap report lists only $gaps gaps"; return 1; }
  if grep -il -E 'claude|anthropic' "$app/docs/"*.md "$app/.claude/state/"*.md; then echo "    docs or STATUS name the tool"; return 1; fi
  printf 'мої правки\n' >> "$app/CLAUDE.local.md"
  python3 -I "$SCAFFOLD" "$app" --adopt --risk R1 --data V0 --stage pilot --tier T1 --texts "$texts" > "$ROOT/modes/adopt2.out" \
    || { echo "    the second --adopt failed"; return 1; }
  grep -q 'мої правки' "$app/CLAUDE.local.md" && ! grep -q '  created ' "$ROOT/modes/adopt2.out" \
    || { echo "    the second --adopt changed a file"; return 1; }
}

case_chat_brief() {  # the skill makes brief/: chat.md with the Write tool, the owner's paths through brief_check.py save
  local app="$ROOT/modes/chat-app" from="$ROOT/modes/owner-files" list="$ROOT/modes/paths.txt" out
  mkdir -p "$app/brief" "$from/scan with space" || return 1
  printf 'бриф із чату\n' > "$app/brief/chat.md"
  printf 'tz\n' > "$from/tz.md"; printf 'scan\n' > "$from/scan with space/page.txt"
  printf '%s\n' "$from/tz.md" "$from/scan with space" > "$list"
  python3 -I "$BRIEF_CHECK" save "$list" "$app/brief" > /dev/null || { echo "    brief_check.py save failed"; return 1; }
  [ -f "$app/brief/tz.md" ] && [ -f "$app/brief/scan with space/page.txt" ] || { echo "    the owner's files are not in brief/"; return 1; }
  save_refused "$list" "$app/brief" || { echo "    a second save was not refused"; return 1; }
  ln -s "$from/tz.md" "$from/link.md" || return 1
  printf '%s\n' "$from/link.md" > "$list"
  save_refused "$list" "$app/brief" || { echo "    save did not refuse a link"; return 1; }
  mode_is "$app" new || return 1
  [ "$(python3 -I "$BRIEF_CHECK" tree "$app/brief" | tail -1)" = 'brief_check: 3 files' ] || { echo "    tree does not list the 3 files"; return 1; }
  # shellcheck disable=SC2046  # new_args prints one word per line
  out=$(python3 -I "$SCAFFOLD" "$app" $(new_args) --name npt-chat) || { echo "    no scaffold from a brief in the chat"; return 1; }
  grep -q '(start from brief/)' <<< "$out" || { echo "    scaffold did not see the brief"; return 1; }
  grep -q 'сервер і CI/CD не вирішено' "$app/CLAUDE.local.md" || { echo "    the card does not take the brief"; return 1; }
  python3 -I "$SCAFFOLD" "$app" --init-git > /dev/null && git -C "$app" -c core.excludesFile=/dev/null check-ignore -q brief/chat.md \
    || { echo "    git does not ignore brief/chat.md"; return 1; }
}

mirrored() {  # <folder>: the files of its copy in the docs repo, sorted, on one line
  (cd "$DOCS_SYNC_REPO/$1" && find . -type f | sed 's#^\./##' | LC_ALL=C sort | tr '\n' ' ')
}

case_docs_sync() {  # docs-sync as the skill runs it, in a docs repo of the scratch root with this tree's hook and the
                    # base's global excludes: a new project connected after --init-git (docs/ before its first commit
                    # and STATUS), the first commit takes docs/ into git and its copy goes; an adopted project; a folder
                    # without git gets a registry row only
  local ds="$HERE/hooks/docs-sync.sh" app="$ROOT/modes/ds-new" old="$ROOT/modes/ds-old" bare="$ROOT/modes/ds-nogit" \
    texts="$ROOT/modes/ds-texts.json" out state='.claude/state/STATUS-archive.md .claude/state/STATUS.md '
  unset GIT_CONFIG_COUNT
  export DOCS_SYNC_REPO="$ROOT/modes/docs-repo" DOCS_SYNC_PROJECTS="$ROOT/modes" DOCS_SYNC_ERRLOG="$ROOT/modes/docs-sync.err" \
    GIT_CONFIG_GLOBAL="$ROOT/modes/ds-gitconfig" GIT_CONFIG_NOSYSTEM=1
  printf '[user]\n\tname = npt\n\temail = npt@example.test\n[core]\n\texcludesFile = %s\n' "$HERE/global/git-excludes" \
    > "$GIT_CONFIG_GLOBAL" && "$ds" init > /dev/null || { echo "    docs-sync init failed"; return 1; }
  mkdir -p "$app" || return 1
  # shellcheck disable=SC2046  # new_args prints one word per line
  python3 -I "$SCAFFOLD" "$app" $(new_args) --name npt-ds > /dev/null && python3 -I "$SCAFFOLD" "$app" --init-git > /dev/null \
    || { echo "    no scaffold for docs-sync"; return 1; }
  out=$("$ds" connect "$app" 2>&1) || { echo "    connect: $out"; return 1; }
  [ "$(mirrored ds-new)" = "${state}docs/decisions.md docs/deployment.md docs/integrations.md " ] \
    || { echo "    the first snapshot: $(mirrored ds-new)"; return 1; }
  git -C "$app" config --get hook.docs-sync-push.command | grep -qF "$ds" || { echo "    connect wrote no hook keys"; return 1; }
  git -C "$app" add -A && out=$(git -C "$app" commit -q -m first 2>&1) || { echo "    the first commit: $out"; return 1; }
  grep -qF "ds-new/docs: in the project's git now, its copy is gone from" <<< "$out" || { echo "    the first commit: $out"; return 1; }
  [ "$(mirrored ds-new)" = "$state" ] && [ -z "$(git -C "$app" ls-files .claude CLAUDE.local.md)" ] \
    || { echo "    after the first commit: $(mirrored ds-new)"; return 1; }
  grep -q '^ds-new	[^	]*	mirror	.claude/state/STATUS\*\.md, docs/ in git	' "$DOCS_SYNC_REPO/registry.tsv" \
    || { echo "    the row: $(grep '^ds-new' "$DOCS_SYNC_REPO/registry.tsv")"; return 1; }
  put_project "$old" && printf '{"not_add": "нові сервіси", "hatches": "немає"}\n' > "$texts" \
    && python3 -I "$SCAFFOLD" "$old" --adopt --risk R1 --data V0 --stage pilot --tier T1 --texts "$texts" > /dev/null \
    || { echo "    no adoption for docs-sync"; return 1; }
  out=$("$ds" connect "$old" 2>&1) || { echo "    connect after the adoption: $out"; return 1; }
  [ "$(mirrored ds-old)" = "${state}docs/decisions.md docs/deployment.md docs/integrations.md docs/standard-gaps.md " ] \
    || { echo "    the snapshot of the adopted project: $(mirrored ds-old)"; return 1; }
  mkdir -p "$bare/docs" && printf 'notes\n' > "$bare/docs/notes.md" || return 1
  out=$("$ds" connect "$bare" 2>&1); [[ $out == *'(register it instead)' ]] || { echo "    connect without git: $out"; return 1; }
  "$ds" register "$bare" > /dev/null && grep -q '^ds-nogit	[^	]*	no-git	' "$DOCS_SYNC_REPO/registry.tsv" \
    || { echo "    register without git"; return 1; }
  [ ! -s "$DOCS_SYNC_ERRLOG" ] || { echo "    the error log: $(cat "$DOCS_SYNC_ERRLOG")"; return 1; }
}

run_modes() {
  local ok=0 name log="$ROOT/modes.log"
  mkdir -p "$ROOT/modes" || return 1
  for name in 'case_ide 0' 'case_ide 1' case_existing case_chat_brief case_docs_sync; do
    # shellcheck disable=SC2086  # name holds the function and its argument
    ( $name ) >> "$log" 2>&1 || { echo "  FAIL  modes at $name, log $log"; sed 's/^/    /' "$log" | tail -n 15; ok=1; }
  done
  return "$ok"
}

for combo in "${COMBOS[@]}"; do
  if [ "$combo" = modes ]; then
    t0=$(date +%s)
    if run_modes; then echo "  ok    modes ($(( $(date +%s) - t0 )) s)"; else fails=$((fails + 1)); fi
    continue
  fi
  kind=${combo%%+*} rest=${combo#*+} db=${rest%%+*} mods=
  case "$rest" in *+*) mods=${rest#*+} ;; esac
  name="npt-$RUN-${combo//+/-}" dir="$ROOT/$combo/$name"
  log="$ROOT/$combo.log" t0=$(date +%s)
  mkdir -p "$dir"
  ui=(); [ "$kind" = fullstack ] && ui=(--ui B)
  modules=(); for module in ${mods//+/ }; do modules+=(--module "$module"); done
  [ -z "$mods" ] || modules+=(--custom 'перевірка модулів стандарту')
  brief=0; case " $BRIEF_COMBOS " in *" $combo "*) brief=1 ;; esac
  (
    set -o pipefail
    trap '[ -z "${dev_pid:-}" ] || kill_tree "$dev_pid"; cleanup; exit 130' INT TERM
    if [ "$brief" = 1 ]; then put_brief || exit 21; fi
    python3 -I "$SCAFFOLD" "$dir" --type "$kind" --db "$db" --risk R1 --data V0 --stage prod \
      ${ui[@]+"${ui[@]}"} ${modules[@]+"${modules[@]}"} --name "$name" || exit 11
    cd "$dir" || exit 11
    if [ "$brief" = 1 ]; then brief_kept || exit 21; fi
    nvm use >/dev/null || exit 12
    pnpm_settings || exit 12
    pnpm install || exit 12
    if [ "$kind" = nest ]; then one_fastify || exit 12; fi
    pnpm run check || exit 13
    first_commit_clean || exit 23
    osv_check "$ROOT/$combo.osv.json" || exit 14
    case "+$mods+" in *+budget+*) budget_guard || exit 24 ;; esac
    if [ "$kind" = nest ]; then nest_generate || exit 20; fi
    if [ "$db" = prisma ]; then add_migration || exit 15; fi
    write_env || exit 15
    if [ "$kind" = nest ]; then dev_nest || exit 19; fi
    if [ "$kind" = api ]; then dev_node || exit 22; fi
    if [ "$db" = prisma ] && ! dev_db; then
      ddc logs --no-color > "$ROOT/$combo.dev.log" 2>&1
      cleanup; exit 18
    fi
    # The dev data volume of db types is still there: a failed build cleans up too
    docker build -t "$name:check" . || { cleanup; exit 15; }
    image_lean || { cleanup; exit 25; }
    if [ "$brief" = 1 ]; then brief_outside_image || { cleanup; exit 21; }; fi
    smoke "$kind" "$db"; rc=$?
    dc logs --no-color > "$ROOT/$combo.compose.log" 2>&1
    cleanup || { [ "$rc" -ne 0 ] || rc=17; }
    [ "$rc" -eq 0 ] || exit $(( rc == 17 ? 17 : 16 ))
  ) > "$log" 2>&1
  rc=$?
  case $rc in 0) step=ok ;; 11) step=scaffold ;; 12) step=install ;; 13) step=check ;; 14) step=osv ;;
              15) step="migration or docker build" ;; 16) step=smoke ;; 17) step=cleanup ;; 18) step="dev database" ;;
              19) step="nest dev" ;; 20) step="nest g" ;; 21) step=brief ;; 22) step="node dev" ;;
              23) step="first commit" ;; 24) step="budget" ;; 25) step="runtime image" ;;
              130) step=interrupted ;;
              *) step="exit $rc" ;; esac
  if [ "$rc" -eq 0 ]; then
    echo "  ok    $combo ($(( $(date +%s) - t0 )) s)"
    if [ -z "${NPT_KEEP:-}" ]; then
      case "$dir" in "$ROOT"/*/npt-"$RUN"-*) rm -rf -- "$dir" && rmdir "$ROOT/$combo" 2>/dev/null ;; esac
    fi
  else
    fails=$((fails + 1)); echo "  FAIL  $combo at $step, log $log"; tail -n 15 "$log" | tr -d '\033' | sed 's/^/    /'
    [ "$rc" -ne 130 ] || break
  fi
done

[ "$fails" -eq 0 ] && echo "NEW PROJECT OK (${#COMBOS[@]} combos)" || echo "NEW PROJECT FAIL: $fails of ${#COMBOS[@]}"
[ "$fails" -eq 0 ]
