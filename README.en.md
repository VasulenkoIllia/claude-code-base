# claude-code-base

A Claude Code setup for macOS: global rules, guard hooks, path-scoped rules, skills, review agents and tools. They go into `~/.claude` as a copy of one tag, with a manifest, a snapshot of the previous state and a one-command rollback. This is the public export of my working setup: the same, minus what is personal. Rules, hook messages and skills are in Ukrainian; only this README is in English.

Українською: [README.md](README.md).

## What is inside

| Folder | What | Installed to |
|---|---|---|
| `global/` | global rules, `settings.json` with hooks and permissions, `home-agents.md`, git ignore lines | `~/.claude/CLAUDE.md`, `~/.claude/settings.json`, `~/AGENTS.md`, `~/.config/git/ignore` (lines only added) |
| `hooks/` | bash-guard (asks about or stops risky commands: data loss, skipping git hooks, a changed author, secrets in a commit), secret-guard (a secret in a prompt), commit-leaks (gitleaks in every commit, git runs it), dup-guard, doc-reminder, session-hint, node-std, nvm-env, docs-sync; tests in `test-all.sh` | `~/.claude/hooks/` |
| `rules/own/` | rules that load when Claude touches files matching their `paths:` (backend, frontend, databases, deploy, dependencies, clean code, demos) | `~/.claude/rules/` |
| `skills/` | new-project (a project from the standard: Node, pnpm, Docker), client-tz (a spec and estimate in Word), time-register (a register of session hours and estimates), 5 ECC skills | `~/.claude/skills/` |
| `agents/` | reviewers: code-reviewer, security-reviewer, typescript-reviewer, react-reviewer, database-reviewer, architect (ECC), silent-failure-hunter (Anthropic) | `~/.claude/agents/` |
| `tools/` | claude-time (session hours per project and task), claude-metrics (work metrics before and after releases) | `~/bin/` |
| `vendor/ecc/` | where each ECC skill and agent came from, local changes (`patches/`) | `ECC-PIN.md` in `~/.claude/` |
| `scripts/`, `tests/` | install, rollback, doctor, verify, snapshots, project-doctor; tests and gates | not installed (except `legacy/ecc-drift.sh` to `~/bin/`) |

The header of each hook, script and tool says what it does. The list of managed files comes from the repo layout (`scripts/lib.sh`, `managed_items`). Install leaves the rest of `~/.claude` alone: plugins, `~/.claude.json`, transcripts, memory, your own skills, agents and rules under other names.

## Requirements

- macOS on Apple Silicon with Homebrew: the hooks use `/opt/homebrew/bin/python3` and gitleaks from there.
- Claude Code: the desktop app or the CLI.
- Tools:

  ```bash
  brew install git jq gitleaks shellcheck python coreutils
  ```

  `git --version` 2.54 or newer (from that version git itself runs commit-leaks on every commit), `python3 --version` 3.11 or newer; Homebrew first on PATH.
- For `/new-project` also `brew install uv osv-scanner` and Docker Desktop.

## First install

1. Clone the repo outside `~/WebstormProjects` (the tools take every folder there for a project), for example into `~/claude-code-base`:

   ```bash
   git clone <this repo's URL> ~/claude-code-base
   ```

2. The plan, writes nothing:

   ```bash
   cd ~/claude-code-base && bash scripts/install.sh "$(git tag --sort=-v:refname | head -n 1)" --dry-run
   ```

   If `~/.claude` already holds your own `CLAUDE.md`, `settings.json`, hooks, skills or agents of the same names, the plan lists them after the line `differ from <tag>` and ends with exit code 3 and the line `would stop on the drift above`: normal for a first install. Move what you want to keep into your personal layer (below).
3. Install:

   ```bash
   cd ~/claude-code-base && bash scripts/install.sh "$(git tag --sort=-v:refname | head -n 1)" --force-drift
   ```

   There is no manifest yet, so every file of yours that differs from the tag counts as drift: hence `--force-drift` (after a plan without drift the flag changes nothing). What gets replaced goes into the snapshot `~/claude-backups/setup-snapshots/<time>-pre-install-<tag>/replaced/`.
4. Restart every Claude session (app and CLI) and check:

   ```bash
   cd ~/claude-code-base && bash scripts/doctor.sh --live
   ```

   Expected: exit 0, `live = <tag>, drift 0`, a `commit scan: OK` line. WARN lines about projects, docs or docs-sync are hints, not failures.
5. In a new session ask Claude to run `git commit --no-verify -m test`: bash-guard stops the command and says why.

## Personal layer

- Your own rules and preferences (answer language, style, tools): `~/.claude/rules/<yours>.md` without `paths:` in the frontmatter; Claude Code loads such a file at the start of every session. Its name must not be one of the base rules (`rules/own/`): the base takes a file of that name for its own, and the next install stops with exit 3.
- Project settings and permissions: `<project>/.claude/settings.local.json`.
- Do not edit managed files: a change is drift, `doctor.sh --live` shows it and the next install stops with exit 3. The app writes to `settings.json` too (a plugin, an "always allow", a theme), and that is drift as well.

## Update

```bash
cd ~/claude-code-base && git pull --ff-only && git fetch --tags
bash scripts/install.sh "$(git tag --sort=-v:refname | head -n 1)" --dry-run
```

What changed: [CHANGELOG.md](CHANGELOG.md) (in Ukrainian). If the plan shows no drift, run the same command without `--dry-run`, then restart the sessions and run `doctor.sh --live`. Drift means a managed file was changed: move the change into your personal layer, then use `--force-drift` (the changed file stays in the snapshot).

## Rollback

- To the previous tag: `bash scripts/rollback.sh <tag>` in the repo folder, then restart the sessions.
- To the state before the base: the snapshot of the first install, a dry run first, then `--apply`:

  ```bash
  ls ~/claude-backups/setup-snapshots/
  bash ~/claude-backups/setup-snapshots/<time>-pre-install-<first tag>/restore.sh
  bash ~/claude-backups/setup-snapshots/<time>-pre-install-<first tag>/restore.sh --apply
  ```

  `restore.sh` deletes nothing: whatever it replaces or removes goes into `displaced-<time>/` of the same snapshot first.
- Claude cannot run any command (a hook stops everything): in the chat ask it to "remove the `hooks` key from `~/.claude/settings.json` with the Edit tool", open a new session and roll back.

## Known limits

- macOS on Apple Silicon with Homebrew only. Rules, hook messages and skills are in Ukrainian, and the global rules ask for answers in Ukrainian; for another language, add your own rule in the personal layer.
- `settings.json` is managed as a whole: your keys there (plugins, model, permissions) are replaced by install, and Claude Code reads no separate user settings file next to it. Personal settings live only in `~/.claude/rules/` and in projects.
- Projects are expected in `~/WebstormProjects`: claude-time, claude-metrics, doctor (doctor and project-doctor take another folder from `PROJECTS_DIR`) and docs-sync look there. claude-metrics leaves out the sessions in a folder named `claude-code-base` (the base itself); it counts days in Kyiv time, and its default "before" and "after" windows come from my history (yours: `--before`, `--after`).
- docs-sync (a mirror of project docs in `~/project-docs`), ecc-drift (an ECC clone in `~/ai-stack/everything-claude-code`) and claude-time do nothing until you run or connect them.
- The guard hooks catch a model's mistakes, not a person's intent: their logic is open.
- No notice of a new tag: updates are manual. Tags are calver `vYYYY.MM.N` from my setup; gaps in the numbers are normal.

## Contributing

Issues and pull requests are welcome as proposals: I carry a change over into my setup and it ships with the next tag; the pull request itself is closed without a merge. Only I push to `main` and the tags.

## License

MIT ([LICENSE](LICENSE)). The ECC skills and agents and silent-failure-hunter keep their own licenses: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
