"""Cost per pushed commit and per 100 changed lines (B5.1).

Transcripts rarely show a commit's size (git commit -q, | tail, chained commands) and pushes mostly run with -q, so
commits and lines come from git itself, read-only and without fetching. A commit counts when it is reachable from a
remote-tracking branch (pushed, by anyone, as of the last push or fetch) and its committer time falls inside a
`git commit` Bash call of a main session, in a repo that call worked in (its cwd, `cd <dir>`, `git -C <dir>`; the
session's working folders only when the call has none). Lines are numstat added + deleted, without lock files and
binary files. A session with such commits spreads its whole cost (main and subagents, every day) evenly over them, on
the commit days, so the cost and the commits of a window always belong together; the other sessions keep their cost
on the days it was spent and show as a share.
Not counted: commits made by hand or by others, and commits whose committer time changed later (rebase, squash on
the server); the footer shows them as pushed_commits_other. Every way git can fail has a footer counter
(GIT_FAILURES), and main() turns any of them into a warning.
"""
import os
import re
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from .patterns import COMMIT_CALL
from .transcript import STATS, kday

GIT_TIMEOUT_S = 30
MATCH_SLACK_S = 5  # committer time can sit a moment outside the timestamps of the tool call that made the commit
LOCK_FILES = {"package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb",
              "deno.lock", "composer.lock", "Gemfile.lock", "Cargo.lock", "poetry.lock", "uv.lock", "Pipfile.lock",
              "go.sum", "flake.lock", "Podfile.lock", "pubspec.lock", "mix.lock", "packages.lock.json"}
CD_DIR = re.compile(r"""(?:^|[;&|(\n]\s*)cd\s+(?:"([^"]+)"|'([^']+)'|([^\s;&|)]+))""")
GIT_C_DIR = re.compile(r"""\bgit\s+-C\s+(?:"([^"]+)"|'([^']+)'|([^\s;&|)]+))""")
RENAME_PART = re.compile(r"\{[^{}]* => ([^{}]*)\}")
NOT_A_REPO = "not a git repository"  # the one rev-parse failure that is expected and stays silent
GIT_ENV_KEEP = ("GIT_CEILING_DIRECTORIES",)  # other GIT_* (GIT_DIR from a hook, say) would point every call at one repo
GIT_CONFIG = ["-c", "core.quotepath=false", "-c", "log.showSignature=false", "-c", "color.ui=false"]
GIT_FAILURES = ("git_missing", "git_cannot_run", "git_timeouts", "git_rev_parse_failed", "git_log_failed")


def note_record(acc, d, sid):
    """The working folders of a main session (its records carry cwd)."""
    if isinstance(d.get("cwd"), str):
        acc.cwds.setdefault(sid, set()).add(d["cwd"])


def note_call(acc, block, ts, sid, cwd):
    """A Bash call of a main session that may make a commit: when it ran and which folders it could commit in."""
    inp = block.get("input") if isinstance(block.get("input"), dict) else {}
    cmd = str(inp.get("command") or "")
    tid = block.get("id")
    if block.get("name") != "Bash" or not tid or tid in acc.commit_calls or not COMMIT_CALL.search(cmd):
        return
    base = cwd if isinstance(cwd, str) else ""
    dirs = {base} if base else set()
    for m in list(CD_DIR.finditer(cmd)) + list(GIT_C_DIR.finditer(cmd)):
        path = os.path.expanduser(next(g for g in m.groups() if g is not None))
        if "$" in path or "`" in path or not (base or os.path.isabs(path)):
            continue  # a variable, or a relative path with no folder to resolve it against
        dirs.add(os.path.normpath(os.path.join(base, path)))
    acc.commit_calls[tid] = [sid, ts, acc.early_results.pop(tid, None), dirs]


def note_result(acc, block, ts):
    """When the result of a call arrived: the end of the span a commit made by that call can have."""
    tid = block.get("tool_use_id")
    if not tid or ts is None:
        return
    call = acc.commit_calls.get(tid)
    if call is not None:
        call[2] = call[2] or ts
    elif tid not in acc.tools:  # parallel calls can write a result before its tool_use
        acc.early_results.setdefault(tid, ts)


def git(args):
    """A finished read-only git command, or None when git could not run (counted)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") or k in GIT_ENV_KEEP}
    env.update(LC_ALL="C", GIT_NO_LAZY_FETCH="1")  # stable messages; a partial clone must not fetch missing blobs
    try:
        return subprocess.run(["git", "--no-optional-locks", *GIT_CONFIG, *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=GIT_TIMEOUT_S, check=False, env=env)
    except FileNotFoundError:
        STATS["git_missing"] += 1
    except subprocess.TimeoutExpired:
        STATS["git_timeouts"] += 1
    except OSError:  # git not executable, no file descriptors left
        STATS["git_cannot_run"] += 1
    return None


def repo_root(path, cache):
    """The repo of a folder, or None: gone, not a repo, or git failed there (all but "not a repo" are counted)."""
    if path not in cache:
        cache[path] = None
        if not os.path.isdir(path):
            STATS["git_dir_gone"] += 1
            return None
        run = git(["-C", path, "rev-parse", "--show-toplevel"])
        if run is not None and run.returncode == 0 and run.stdout.strip():
            cache[path] = run.stdout.strip()
        elif run is not None and NOT_A_REPO not in run.stderr:
            STATS["git_rev_parse_failed"] += 1  # a broken config, "dubious ownership", the Xcode license stub
    return cache[path]


def changed_lines(numstat):
    """Added + deleted lines of numstat lines, without lock files; binary files ("-" rows) are skipped."""
    total = 0
    for line in numstat:
        parts = line.split("\t", 2)
        if len(parts) == 3 and parts[0] == parts[1] == "-":
            continue
        if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
            if line.strip():
                STATS["numstat_unparsed"] += 1
            continue
        path = RENAME_PART.sub(r"\1", parts[2].strip().strip('"')).split(" => ")[-1]
        if os.path.basename(path) not in LOCK_FILES:
            total += int(parts[0]) + int(parts[1])
    return total


def pushed_commits(root, since):
    """[(hash, committer time, changed lines)] of commits reachable from a remote-tracking branch, or None.
    --since-as-filter, not --since: --since stops walking at the first older commit, so one back-dated commit would
    hide the newer ones below it."""
    run = git(["-C", root, "log", "--remotes", "--no-merges", "-M", "--no-ext-diff", "--no-textconv",
               f"--since-as-filter={since.isoformat()}", "--format=%x00%H %ct", "--numstat"])
    if run is None:
        return None
    if run.returncode != 0 or (run.stdout.strip() and "\x00" not in run.stdout):
        STATS["git_log_failed"] += 1
        return None
    commits = []
    for chunk in run.stdout.split("\x00")[1:]:
        head, _, rest = chunk.partition("\n")
        sha, _, ct = head.partition(" ")
        if ct.isdigit():
            commits.append((sha, int(ct), changed_lines(rest.split("\n"))))
        else:
            STATS["numstat_unparsed"] += 1
    return commits


class Call(NamedTuple):
    """A git commit call of a main session: the seconds a commit made by it can have, and where it can be."""
    first: float  # epoch seconds, MATCH_SLACK_S included
    last: float
    sid: str
    roots: frozenset  # repo roots of the call's folders (of its session's working folders when it has none)


def match_commits(calls, commits_by_root):
    """Pure matching: each pushed commit goes to the call that started last among those whose span holds its committer
    time in the same repo; a hash in two clones counts once.
    Returns ([(session, committer time, lines)], commits per call index, unmatched hashes, commits two sessions could
    have made)."""
    matched, seen, made, out, ambiguous = set(), set(), Counter(), [], 0
    for root in sorted(commits_by_root):
        for sha, ct, lines in commits_by_root[root]:
            seen.add(sha)
            if sha in matched:
                continue
            hits = [i for i, c in enumerate(calls) if c.first <= ct <= c.last and root in c.roots]
            if not hits:
                continue
            ambiguous += len({calls[j].sid for j in hits}) > 1  # the cost may go to the wrong session
            i = max(hits, key=lambda j: calls[j].first)
            matched.add(sha)
            made[i] += 1
            out.append((calls[i].sid, ct, lines))
    return out, made, len(seen - matched), ambiguous


def add_push_cost(acc, matches):
    """push_commits, push_lines and push_weighted on the commit days (each commit carries an equal share of its
    session's whole cost); nopush_weighted on the days spent, for the sessions without a matched commit."""
    commits = Counter(m[0] for m in matches)
    total = {sid: sum(acc.session_cost.get(sid, {}).values()) for sid in commits}
    for sid, ct, lines in matches:
        day = kday(datetime.fromtimestamp(ct, timezone.utc))
        acc.add(day, "push_commits")
        acc.add(day, "push_lines", lines)
        acc.add(day, "push_weighted", total[sid] / commits[sid])
    for sid, costs in acc.session_cost.items():
        if sid not in commits:
            for day, weighted in costs.items():
                acc.add(day, "nopush_weighted", weighted)


def pushes(acc):
    """Pushed commits of the commit calls of main sessions, with their cost. Reads git of the projects, so main() runs
    it only for the comparison and --json, not for --weekly or --candidates."""
    STATS["commit_calls"] = len(acc.commit_calls)  # 0 shows too: a transcript format change must not pass for no work
    STATS["commit_calls_matched"] = 0
    if not acc.commit_calls:
        return
    cache, calls = {}, []
    for sid, start, end, dirs in acc.commit_calls.values():
        roots = frozenset({repo_root(p, cache) for p in dirs or acc.cwds.get(sid, set())} - {None})
        last = max(start, end or start)
        calls.append(Call(start.timestamp() - MATCH_SLACK_S, last.timestamp() + MATCH_SLACK_S, sid, roots))
    since = datetime.fromtimestamp(max(0.0, min(c.first for c in calls)), timezone.utc) - timedelta(days=1)
    commits_by_root = {}
    for root in sorted(set().union(*(c.roots for c in calls))):
        STATS["git_repos"] += 1
        commits_by_root[root] = pushed_commits(root, since) or []
    matches, made, other, ambiguous = match_commits(calls, commits_by_root)
    STATS["commit_calls_matched"] = sum(1 for i in range(len(calls)) if made[i])
    STATS["commit_calls_no_repo"] = sum(1 for c in calls if not c.roots)
    STATS["commit_calls_unpushed"] = sum(1 for i, c in enumerate(calls) if c.roots and not made[i])
    STATS["pushed_commits_other"] = other
    STATS["pushed_commits_ambiguous"] = ambiguous
    add_push_cost(acc, matches)
