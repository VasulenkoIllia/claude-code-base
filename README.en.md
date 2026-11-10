# claude-code-base

A Claude Code setup for macOS: global rules, guard hooks, path-scoped rules, skills, review agents and tools. They go into `~/.claude` as a copy of one tag, with a manifest, a snapshot of the previous state and a one-command rollback. This is the public export of my working setup: the same, minus what is personal. Rules and skills are written in English (so they take fewer tokens) and ask Claude to answer in Ukrainian; hook messages are in Ukrainian. Of the docs, only this README is in English.

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

The header of each hook, script and tool says what it does. The list of managed files comes from the repo layout (`scripts/lib.sh`, `managed_items`). Install leaves the rest of `~/.claude` alone: plugins, `~/.claude.json`, transcripts, memory, your own skills, agents and rules under other names. Install neither looks for nor touches your projects: rules, hooks, agents and skills work globally, in a session in any folder. Only claude-time, claude-metrics, the project checks of doctor (another folder: `PROJECTS_DIR`) and docs-sync, once you connect it, read the projects folder `~/WebstormProjects`.

## Requirements

- macOS on Apple Silicon with Homebrew: the hooks use `/opt/homebrew/bin/python3` and gitleaks from there.
- Claude Code: the desktop app or the CLI.
- Tools:

  ```bash
  brew install git jq gitleaks shellcheck python coreutils
  ```

  Check: `uname -m` prints `arm64`; `git --version` 2.54 or newer (from that version git itself runs commit-leaks on every commit); `python3 --version` 3.11 or newer; `command -v python3` prints `/opt/homebrew/bin/python3` (Homebrew first on PATH).
- nvm for the Node of your projects: the nvm-env hook and `/new-project` load it from `~/.nvm/nvm.sh`.

  ```bash
  brew install nvm
  ```

  Then add the two lines `brew info nvm` suggests to `~/.zshrc` (`export NVM_DIR="$HOME/.nvm"` and the line that loads `/opt/homebrew/opt/nvm/nvm.sh`) and open a new terminal: the first load creates `~/.nvm/nvm.sh` itself. Check: `[ -s ~/.nvm/nvm.sh ] && echo ok` prints `ok`.
- For `/new-project` also `brew install uv osv-scanner` and Docker Desktop.
- Context7 for library docs (the global rules and the documentation-lookup skill call it): the Context7 connector in claude.ai (Settings, Connectors), or in the CLI `claude mcp add --scope user --header "Authorization: Bearer <key>" --transport http context7 https://mcp.context7.com/mcp` with a key from context7.com. Without it Claude takes library docs from the model's memory.

## First install

About 10 minutes. Install deletes nothing: every replaced file goes into a snapshot, and one command puts it all back (section "Rollback"). Claude Code can do the same steps from a ready prompt (section below).

1. Clone the repo outside `~/WebstormProjects` (the tools take every folder there for a project), for example into `~/claude-code-base`. The URL is on the Code button of this page:

   ```bash
   git clone <this repo's URL> ~/claude-code-base
   ```

2. The plan, writes nothing:

   ```bash
   cd ~/claude-code-base && bash scripts/install.sh "$(git tag --sort=-v:refname | head -n 1)" --dry-run
   ```

   If `~/.claude` already holds your own `CLAUDE.md`, `settings.json`, hooks, skills or agents of the same names, the plan lists them after the line `differ from <tag>` and ends with exit code 3 and the line `would stop on the drift above`: normal for a first install.
3. Move what you want to keep from those files (your own rules, answer language) into your personal layer (section below). The rest goes into the snapshot anyway.
4. Install:

   ```bash
   cd ~/claude-code-base && bash scripts/install.sh "$(git tag --sort=-v:refname | head -n 1)" --force-drift
   ```

   There is no manifest yet, so every file of yours that differs from the tag counts as drift: hence `--force-drift` (after a plan without drift the flag changes nothing). What gets replaced goes into the snapshot `~/claude-backups/setup-snapshots/<time>-pre-install-<tag>/replaced/`.
5. Restart every Claude session: quit and reopen the app, and restart `claude` in the terminal too. New rules, hooks and `settings.json` apply only to new sessions.
6. Check:

   ```bash
   cd ~/claude-code-base && bash scripts/doctor.sh --live
   ```

   Expected: exit 0, `live = <tag>, drift 0`, a `commit scan: OK` line. WARN lines about projects, docs or docs-sync are hints, not failures.
7. In a new session ask Claude to run `git commit --no-verify -m test`: bash-guard stops the command and says why.

## Ready prompts for Claude Code

Clone the repo (step 1 above), open a new Claude Code session in the folder `~/claude-code-base` (the app: this folder as the project; the terminal: `cd ~/claude-code-base && claude`) and paste a prompt. The repo's `.claude/settings.json` applies in that folder: install, rollback and `restore.sh --apply` always ask for permission.

First install:

```text
Install the setup from this repo into my ~/.claude following README.en.md, section "First install". Go step by step and stop wherever I have to answer. Save the output and the exit code of every command into ~/claude-code-base-report/ (a file per step: 01-requirements.txt, 02-dry-run.txt, 03-install.txt).
1. Check the requirements from the section "Requirements" and tell me what is missing. Do not install anything yourself.
2. Take the newest tag (git tag --sort=-v:refname | head -n 1) and run bash scripts/install.sh <tag> --dry-run. Explain the plan in plain words: what gets installed and which of my files count as drift.
3. For each of my drifted files, tell me what in it is mine and suggest what to move into ~/.claude/rules/<mine>.md. Move things only after my "yes".
4. After a separate "yes" from me, run bash scripts/install.sh <tag> --force-drift and tell me where the snapshot is.
5. Ask me to restart every Claude session and stop there.
```

Check in a new session after the restart:

```text
Check the setup: run bash scripts/doctor.sh --live. I expect exit 0, live = <tag>, drift 0 and a commit scan: OK line; sum up any WARN lines briefly. Then try to run git commit --no-verify -m test and show me what bash-guard answered. Save the output and the exit code into ~/claude-code-base-report/04-doctor.txt and 05-bash-guard.txt.
```

A report, if I asked you to send one (look through the folder before you send it):

```text
Write a report on the setup install into ~/claude-code-base-report/report.md from the files of that folder: the date; macOS and the chip; the versions of git, python3, jq, gitleaks, shellcheck; the installed tag; what the plan showed as drift and what I moved into the personal layer; the exit code of install and the snapshot path; doctor (exit code, the live line, commit scan, WARN lines); what bash-guard answered; errors, unclear steps and my questions. No secrets, tokens or passwords; replace the names of my projects and clients with "project 1", "project 2", in the logs of the folder too. Show me the report and remind me to look through the whole folder before sending it.
```

Update:

```text
Update the setup from this repo following README.en.md, section "Update":
1. Run git pull --ff-only and git fetch --tags. Tell me which tag is live (jq -r .ref ~/.claude/.setup-manifest.json) and which is the newest (git tag --sort=-v:refname | head -n 1). If they are the same, stop there.
2. Sum up from CHANGELOG.md what changed between them.
3. Run bash scripts/install.sh <newest tag> --dry-run and explain the plan. If there is drift, show the files and suggest moving my changes into the personal layer; --force-drift only after a separate "yes" from me.
4. After my "yes", install the tag without --dry-run, ask me to restart every Claude session and stop.
```

Rollback:

```text
Roll the setup back following README.en.md, section "Rollback". Tell me which tag is live (jq -r .ref ~/.claude/.setup-manifest.json) and which one we roll back to, show the plan (bash scripts/rollback.sh <tag> --dry-run), and run the rollback itself only after my "yes". Then ask me to restart every Claude session.
```

## Personal layer

- Your own rules and preferences (answer language, style, tools): `~/.claude/rules/<yours>.md` without `paths:` in the frontmatter; Claude Code loads such a file at the start of every session. Its name must not be one of the base rules (`rules/own/`): the base takes a file of that name for its own, and the next install stops with exit 3.
- Project settings and permissions: `<project>/.claude/settings.local.json`.
- Do not edit managed files: a change is drift, `doctor.sh --live` shows it and the next install stops with exit 3. The app writes to `settings.json` too (a plugin, an "always allow", a theme), and that is drift as well.

## Update

New releases come as tags from my private setup. `main` here only moves forward, and tags are never moved or deleted, so `git pull --ff-only` always works. Claude Code can do the same from the "Update" prompt above.

```bash
cd ~/claude-code-base && git pull --ff-only && git fetch --tags
bash scripts/install.sh "$(git tag --sort=-v:refname | head -n 1)" --dry-run
```

What changed: [CHANGELOG.md](CHANGELOG.md) (in Ukrainian). If the plan shows no drift, run the same command without `--dry-run`, then restart the sessions and run `doctor.sh --live`. Drift means a managed file was changed: move the change into your personal layer, then use `--force-drift` (the changed file stays in the snapshot).

## Rollback

From the lightest to the heaviest. The terminal commands work without Claude too. A ready prompt: "Rollback" above.

1. **Something behaves oddly after an update:** in the repo folder `bash scripts/rollback.sh <previous tag>` (a `--dry-run` first if you like), then restart every session. It does not stop on drift (a changed file stays in the snapshot) or on verify warnings of an old tag under newer shellcheck or gitleaks; the hook tests still apply.
2. **Claude cannot run any command** (bash-guard stops everything or broke): in the chat ask it to "remove the `hooks` key from `~/.claude/settings.json` with the Edit tool", open a new session and do step 1. If bash-guard asks about every command with the reason «вхід хука не прочитано» or «хук зупинився» (hook input not read, hook stopped), the commands run after a "yes", and the cause is in `~/.claude/logs/bash-guard.err`.
3. **`rollback.sh` failed:** restore a snapshot. `install.sh` takes one before every install, and the `restore.sh` in it works even without the repo:

   ```bash
   ls ~/claude-backups/setup-snapshots/
   bash ~/claude-backups/setup-snapshots/<snapshot>/restore.sh
   bash ~/claude-backups/setup-snapshots/<snapshot>/restore.sh --apply
   ```

   The first line lists the snapshots, the second is a dry run (changes nothing), the third restores and checks (MATCH/DIFF). With the repo intact, `bash scripts/rollback.sh --to-snapshot ~/claude-backups/setup-snapshots/<snapshot>` does the same: it snapshots the current state first, so this rollback can be undone too.
4. **Remove the setup completely:** the same `restore.sh` from the snapshot of the first install (`<time>-pre-install-<first tag>`). `restore.sh` deletes nothing: whatever it replaces or removes goes into `displaced-<time>/` of the same snapshot first. To come back to the setup later: `bash scripts/rollback.sh <tag>`.

Small cases:

- A false secret block on a prompt: put `[secret-ok]` at the start or the end of the message.
- A new session offers to upgrade the Node of a project: that is the node-std hook, once per project and standard, only in a new session or after `/clear`. You can skip it: it does not come back until the next standard.
- A commit prints a `docs-sync: …` line: the commit and the push went through, only the docs did not sync; the cause is in the line and in `~/.claude/logs/docs-sync.err`.
- One project behaves unlike the rest: `bash scripts/project-doctor.sh <project folder>` in the repo folder, read-only.

## Time tracking (claude-time)

`~/bin/claude-time` sums up the time of Claude Code sessions per project into a task register: it reads the transcripts in `~/.claude/projects` and takes the projects and their cards from `~/WebstormProjects`. Without `--write` it writes nothing; with `--write` the data goes into the private folder `~/claude-time` (outside git). Reports and flags: `~/bin/claude-time --help`.

- The `time-register` skill: ask Claude «онови реєстр часу» (update the time register: split new prompts into tasks and write them) or «скільки часу піде на …» (how long will … take: an estimate from analogs in the register, Claude session hours only).
- `~/bin/claude-metrics`: work metrics before and after setup releases (`--help`); the weekly update shows them itself.
- Weekly, on its own: in the Claude app (the Code tab) create a scheduled task, every Monday, folder `~/claude-code-base`, with the prompt:

  ```text
  Weekly update of the Claude session time register. Call the time-register skill and do its section 1 step by step: split the new prompts into tasks and write the split yourself, without my confirmation; then the report and the metrics of the week.
  ```

## Docs outside git (docs-sync)

If your projects keep docs outside git (`docs/` or `_internal/` in `.gitignore`, `STATUS*.md` in `.claude/state/`), docs-sync mirrors them into one private repo `~/project-docs`: after every commit and before every push of a connected project, with a gitleaks check before every commit of the docs repo. The project folder stays the source; do not edit the mirror. Needs git 2.54 or newer.

1. The docs repo, once:

   ```bash
   ~/.claude/hooks/docs-sync.sh init
   ```

2. A private copy on GitHub (from then on the push runs by itself in the background while the repo is ahead of origin):

   ```bash
   cd ~/project-docs && gh repo create project-docs --private --source . --remote origin --push
   ```

3. Connect a project: the plan first (how many files and MB, writes nothing), then the same without `--dry-run`:

   ```bash
   ~/.claude/hooks/docs-sync.sh connect --dry-run ~/WebstormProjects/<folder>
   ~/.claude/hooks/docs-sync.sh connect ~/WebstormProjects/<folder>
   ```

After that it runs by itself. Docs changed without a commit: `~/.claude/hooks/docs-sync.sh sync <folder>`; disconnect: `disconnect <folder>`; state: the `docs repo:` lines of `doctor.sh --live`. `/new-project` connects a new project itself.

## Checking against ECC (ecc-drift)

Five skills and six agents come from ECC; the reference point is in `~/.claude/ECC-PIN.md`. What changed upstream since then, ecc-drift shows (read-only):

```bash
git clone https://github.com/affaan-m/everything-claude-code ~/ai-stack/everything-claude-code
bash ~/bin/ecc-drift.sh
```

Whether to take a change over is my call; it arrives with the next tag.

## Your own copy, and why it is built this way

- How to work with the setup day to day (what runs by itself, what to tell Claude, weekly, a new project, a command cheat sheet): [docs/USAGE.md](docs/USAGE.md) (in Ukrainian).
- To change the setup for yourself (your own hooks, rules, skills): a fork and the change cycle from [docs/FORK.md](docs/FORK.md) (in Ukrainian).
- Why the setup is built this way: [docs/adr/](docs/adr/) (in Ukrainian), ADR-001 (install by copy with a manifest) and ADR-002 (the budget of the global rules file and of the rules).

## Known limits

- macOS on Apple Silicon with Homebrew only. The global rules ask Claude to answer in Ukrainian, and hook messages are in Ukrainian too; for another answer language, add your own rule in the personal layer. After a context compaction the session-hint hook still reminds Claude to answer in Ukrainian; only your own copy can drop that ([docs/FORK.md](docs/FORK.md)).
- `settings.json` is managed as a whole: your keys there (plugins, model, permissions) are replaced by install, and Claude Code reads no separate user settings file next to it. Personal settings live only in `~/.claude/rules/` and in projects.
- Projects are expected in `~/WebstormProjects`: claude-time, claude-metrics, doctor (doctor and project-doctor take another folder from `PROJECTS_DIR`) and docs-sync look there. claude-metrics leaves out the sessions in a folder named `claude-code-base` (the base itself); it counts days in Kyiv time, and its default "before" and "after" windows come from my history (yours: `--before`, `--after`).
- docs-sync, ecc-drift and claude-time do nothing until you run or connect them (sections above).
- The guard hooks catch a model's mistakes, not a person's intent: their logic is open.
- No notice of a new tag: updates are manual. Tags are calver `vYYYY.MM.N` from my setup; gaps in the numbers are normal.

## Contributing

Issues and pull requests are welcome as proposals: I carry a change over into my setup and it ships with the next tag; the pull request itself is closed without a merge. Only I push to `main` and the tags.

## License

MIT ([LICENSE](LICENSE)). The ECC skills and agents and silent-failure-hunter keep their own licenses: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
