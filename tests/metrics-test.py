#!/usr/bin/env -S python3 -I
"""Offline test of claude-metrics: cost per pushed commit and per 100 changed lines (B5.1).

Builds made-up transcripts and two git repos with bare remotes (plus a second clone of one) in a temp folder,
deleted afterwards, runs tools/claude-metrics.py --json against them with HOME pointing there, and checks the
numbers by hand:
  S1 (cwd repo_a; its second call also looks at the clone repo_a2): commit c1 (+10) and c2 (+5 -2, plus package-lock.json, a PNG and
     a rename), both pushed; a subagent of S1 adds to S1's cost a day before the window, which still goes to S1's
     commits; repo_a2 shows c1, c2 and c4 again
  S2 (cwd repo_a): commit c3 on a local branch, never pushed
  c4: pushed by hand, no tool call
  S3 (cwd: the parent folder): `cd repo_b && git commit`, pushed (+7)
  c6: pushed by hand in repo_b during S2's commit call in repo_a: other repo, so not S2's, though S2 also worked in
     repo_b (session folders count only for a call without its own)
  S4 (cwd repo_b only on its first record): c7 (+4) 3 s before its call starts, c8 (+2) 3 s after its call ends,
     made by `git -c user.name=x commit`, c9 (+1) at 21:30 UTC the day before (00:30 in Kyiv, so the window's day);
     a merge commit inside one of its calls and a hand-made commit on the merged branch do not count
The matching itself (overlapping calls, a hash in two clones, unmatched hashes) is checked on match_commits directly,
the commit-call pattern and a repo whose rev-parse fails on their own; so are the reviewer coverage (a commit made
with `git -c` or a plain `git commit`, not `git commit-tree`) and the date order in which summarize reads and adds
the days of a window.
Prompts (prompt_checks): one more made-up session of every prompt form; claude-metrics must count what claude-time's
scan counts (the same rule, time_register.transcript.prompt_text), keep pasted text out of the text metrics and warn
of records of an unknown form in the same words as claude-time, with each kind, name and count (also in --json).
Records whose message is no object (message_checks: user and assistant ones, a subagent's too) fail neither tool; the
user ones are warned of as the kind "message не об'єкт" in the same words; claude-metrics counts them all in
message_not_object and warns of them in a line of its own (with --json and in the plain report), an assistant one
also counts in assistant_no_usage.
The other unknown forms (forms_checks): an attachment that is no object, content of a would-be prompt of another
form, blocks with no text or image, a uuid or sessionId that is not text fail neither tool and are warned of in the
same words by both (the entry with such a uuid or sessionId still counts); the fields only the metrics read (an
attachment, a compactMetadata other than null or none, a preTokens of an auto compaction that is no number, a message
id or model, a token count that is no number, true, NaN, an infinity and an int too large for a float included, a
cache_creation that is no object, a text block whose text is no text, in a tool result and a subagent's meta record
too) are taken as missing and warned of in a line of claude-metrics' own, with each form's count in --json, while the
usage of an answer the metrics skip (<synthetic>, an API error) is not read; a JSON line that is no object or has an
integer over Python's digit limit is broken in both; usage_of on its own (usage_checks). A clean run has neither that
line nor those keys.
The language of what the model writes to the owner and the context of a session's first request by project:
tests/metrics_lang_checks.py. Real permission prompts: tests/metrics_perm_checks.py.
Run: python3 -I tests/metrics-test.py (verify.sh check 16). Exit 0 = all checks passed.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(ROOT, "tools"))
sys.path.append(os.path.join(ROOT, "tests"))
# pylint: disable=wrong-import-position
from claude_metrics import coverage, events, patterns, pushes, summary  # noqa: E402
from claude_metrics import transcript as metrics_transcript  # noqa: E402
from claude_metrics.transcript import STATS  # noqa: E402
from metrics_lang_checks import language_checks  # noqa: E402
from metrics_perm_checks import permission_checks  # noqa: E402
from time_register import scan as time_scan  # noqa: E402
from time_register.transcript import pasted_label  # noqa: E402

CLI = os.path.join(ROOT, "tools", "claude-metrics.py")
DAY = "2026-10-20"
UNKNOWN_LINE = ("увага: записів незнайомої форми 4 (невідомий origin: martian 1, plugin 1; невідомий commandMode: "
                "telepathy 1; origin у записі черги: human 1): можливо, змінився формат транскриптів, і частину "
                "запитів не враховано")
TYPED_LINE = ("примітка: записів з «<» на початку 3 (тег на початку: div 2; «<» без тегу 1): запитами не враховано; "
              "зазвичай це набраний текст, а тег, якого ніхто не набирав, означає зміну формату транскриптів")
UNKNOWN_PREFIXES = ("увага: записів незнайомої форми", "примітка:")  # the lines of time_register's unknown_warning
MESSAGE_LINE = ("увага: записів незнайомої форми 3 (message не об'єкт 3): можливо, змінився формат транскриптів, і "
                "частину запитів не враховано")
MESSAGE_METRICS_LINE = ("увага: записів, у яких message не об'єкт, 8: можливо, змінився формат транскриптів, і метрики "
                        "неповні (відповіді моделі, результати інструментів)")
FORMS_LINE = ("увага: записів незнайомої форми 5 (attachment не об'єкт 1; content незнайомої форми 1; блоки без тексту 1; "
              "uuid не рядок 1; sessionId не рядок 1): можливо, змінився формат транскриптів, і частину запитів не "
              "враховано")
FIELDS_LINE = ("увага: записів з полями незнайомої форми 20 (attachment не об'єкт 2; compactMetadata не об'єкт 2; "
               "preTokens не число 4; message.id не рядок 2; model не рядок 2; число токенів у usage не число 5; "
               "текст блоку не рядок 3): можливо, змінився формат транскриптів, і метрики неповні")
FIELD_KEYS = {"attachment_not_object", "compact_metadata_not_object", "pretokens_not_number", "message_id_not_text",
              "model_not_text", "usage_not_number", "text_not_text"}
FAILS = []
CHECKS = [0]


def check(what, ok, detail=""):
    CHECKS[0] += 1
    if not ok:
        FAILS.append(f"{what} {detail}".strip())


def git(repo, *args, when=None):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": repo, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull, "LC_ALL": "C"}
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = (when if "T" in when else f"{DAY}T{when}") + "+00:00"
    subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", "-c", "init.defaultBranch=main",
                    "-c", "commit.gpgsign=false", *args], cwd=repo, env=env, check=True, capture_output=True)


def write(path, text, mode="w"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode) as f:
        f.write(text)


def repo_with_remote(tmp, name):
    remote, repo = os.path.join(tmp, name + ".git"), os.path.join(tmp, "work", name)
    os.makedirs(remote)
    os.makedirs(repo)
    git(remote, "init", "-q", "--bare")
    git(repo, "init", "-q")
    git(repo, "remote", "add", "origin", remote)
    return repo


def lines(n, tag):
    return "".join(f"{tag} {i}\n" for i in range(n))


def commit(repo, name, when, files):
    for rel, text in files.items():
        write(f"{repo}/{rel}", text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", name, when=when)


def build_repos(tmp):
    a = repo_with_remote(tmp, "repo_a")
    commit(a, "c1", "10:00:15", {"a.ts": lines(8, "a"), "b.ts": lines(2, "b")})             # +10
    write(f"{a}/logo.png", "\x89PNG\r\n\x1a\n\x00\x00\x00binary")
    git(a, "mv", "b.ts", "c.ts")
    commit(a, "c2", "10:05:12", {"a.ts": lines(6, "a") + lines(5, "new"),                    # -2 +5
                                 "package-lock.json": lines(1000, "lock")})
    git(a, "push", "-q", "origin", "main")
    git(a, "checkout", "-q", "-b", "wip")
    commit(a, "c3", "11:00:02", {"wip.ts": lines(50, "w")})                                  # never pushed
    git(a, "checkout", "-q", "main")
    commit(a, "c4", "12:00:00", {"manual.ts": lines(40, "m")})                               # pushed by hand
    git(a, "push", "-q", "origin", "main")
    a2 = os.path.join(tmp, "work", "repo_a2")
    git(os.path.join(tmp, "work"), "clone", "-q", os.path.join(tmp, "repo_a.git"), a2)      # c1, c2, c4 once more
    b = repo_with_remote(tmp, "repo_b")
    commit(b, "c5", "13:00:01", {"x.ts": lines(7, "x")})                                     # +7, cd from the parent
    commit(b, "c6", "11:00:03", {"y.ts": lines(3, "y")})                                     # by hand, during S2's call
    commit(b, "old", "2026-01-01T00:00:00", {"old.ts": lines(9, "o")})  # back-dated: must not hide c5 and c6 below it
    commit(b, "c7", "13:59:57", {"z.ts": lines(4, "z")})                                     # 3 s before S4's call
    commit(b, "c8", "15:00:05", {"w.ts": lines(2, "w")})                                     # 3 s after S4's call
    git(b, "checkout", "-q", "-b", "side")
    commit(b, "side", "09:00:00", {"s.ts": lines(5, "s")})                                   # by hand on a branch
    git(b, "checkout", "-q", "main")
    git(b, "merge", "-q", "--no-ff", "side", "-m", "merge", when="14:00:01")  # inside S4's call, but a merge: not counted
    commit(b, "c9", "2026-10-19T21:30:01", {"n.ts": lines(1, "n")})  # 00:30 in Kyiv: a commit of the window's day
    git(b, "push", "-q", "origin", "main")
    return a, a2, b


def entries(sid, cwd, steps):
    """steps: (time, "call", (message id, usage, tool id, command)) or (time, "result", tool id)."""
    out = [{"type": "user", "sessionId": sid, "uuid": f"{sid}-0", "cwd": cwd, "timestamp": f"{DAY}T09:59:00Z",
            "message": {"role": "user", "content": "do it"}}]
    for n, (when, kind, extra) in enumerate(steps, 1):
        base = {"sessionId": sid, "uuid": f"{sid}-{n}", "cwd": cwd,
                "timestamp": (when if "T" in when else f"{DAY}T{when}") + "Z"}
        if kind == "call":
            mid, usage, tid, cmd = extra
            content = [{"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": cmd}}]
            out.append({**base, "type": "assistant", "message": {"id": mid, "model": "m", "usage": usage,
                                                                 "content": content}})
        else:
            out.append({**base, "type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": extra, "content": "ok"}]}})
    return out


def call(when, mid, usage, tid, cmd):
    return (when, "call", (mid, usage, tid, cmd))


def build_home(tmp, a, a2, b):
    proj = os.path.join(tmp, "home", ".claude", "projects", "-work")
    os.makedirs(os.path.join(tmp, "home", ".claude", "skills"))
    sessions = {
        "s1": entries("s1", a, [
            call("10:00:10", "m1", {"input_tokens": 1000, "output_tokens": 100}, "t1", "git add -A && git commit -q -m c1"),
            ("10:00:20", "result", "t1"),
            call("10:05:00", "m2", {"input_tokens": 2000, "cache_read_input_tokens": 10000, "output_tokens": 50},
                 "t2", "git commit -q -m c2 2>&1 | tail -1; git -C ../repo_a2 log -1"),
            ("10:05:30", "result", "t2")]),
        "s2": entries("s2", a, [
            call("11:00:00", "m3", {"input_tokens": 5000, "output_tokens": 10}, "t3", "git commit -qm c3"),
            ("11:00:05", "result", "t3")]),
        "s3": entries("s3", os.path.dirname(a), [
            call("13:00:00", "m4", {"input_tokens": 3000}, "t4", f'cd "{os.path.basename(b)}" && git commit -q -m c5'),
            ("13:00:03", "result", "t4")]),
        "s4": entries("s4", b, [
            call("14:00:00", "m5", {"input_tokens": 2000}, "t5", "git commit -q -m c7"),
            ("14:00:02", "result", "t5"),
            call("15:00:00", "m6", {"input_tokens": 1000}, "t6", "git -c user.name=x commit -q -m c8"),
            ("15:00:02", "result", "t6"),
            call("2026-10-19T21:30:00", "m7", {"input_tokens": 500}, "t7", "git commit -q -m c9"),
            ("2026-10-19T21:30:03", "result", "t7")]),
    }
    # S2 also worked in repo_b; its call in repo_a must still not take the hand-made c6 in repo_b
    sessions["s2"].append({"type": "system", "subtype": "note", "sessionId": "s2", "uuid": "s2-b", "cwd": b,
                           "timestamp": f"{DAY}T11:30:00Z"})
    for row in sessions["s4"][1:]:  # S4's calls carry no cwd: the repo comes from the session's first record
        row.pop("cwd")
    for sid, rows in sessions.items():
        write(os.path.join(proj, sid + ".jsonl"), "".join(json.dumps(r) + "\n" for r in rows))
    sub = [{"type": "assistant", "sessionId": "s1", "uuid": "s1-sub-1", "timestamp": "2026-10-19T10:02:00Z",
            "message": {"id": "sm1", "model": "m", "usage": {"input_tokens": 4000}, "content": []}}]
    write(os.path.join(proj, "s1", "subagents", "agent-x.jsonl"), "".join(json.dumps(r) + "\n" for r in sub))
    return os.path.join(tmp, "home")


def run_cli(tmp, home, path=None, mode=("--json",)):
    env = {"HOME": home, "PATH": path if path is not None else os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C",
           "GIT_CEILING_DIRECTORIES": tmp,  # a temp folder inside some work tree must not resolve to that repo
           "GIT_DIR": os.path.join(tmp, "repo_b.git")}  # as if run from a git hook: claude-metrics must drop it
    run = subprocess.run([sys.executable, "-I", CLI, *mode, "--before", "2026-10-01", "2026-10-10",
                          "--after", DAY, DAY], env=env, capture_output=True, text=True, check=False)
    check(f"cli {' '.join(mode)} exit 0", run.returncode == 0, run.stderr[-500:])
    if mode != ("--json",):
        return run.stdout, run.stderr
    return (json.loads(run.stdout) if run.returncode == 0 else {}), run.stderr


def close(x, y):
    return x is not None and abs(x - y) < 1e-9 * max(1.0, abs(y))


def unit_checks():
    numstat = ["3\t1\tsrc/a.ts", "-\t-\timg.png", "100\t0\tpackage-lock.json", "2\t2\tsrc/{old => new}/yarn.lock",
               "1\t1\t\"src/\\303\\274.ts\"", "4\t0\tdocs/{a.md => b.md}", "bad line",
               "5\t5\t\"d\\\"ir/yarn.lock\"", "3\t0\t{a.json => package-lock.json}", "x\ty\tweird.ts"]
    unparsed = STATS["numstat_unparsed"]
    total = pushes.changed_lines(numstat)
    check("changed_lines skips lock, binary, renamed lock", total == 10, str(total))
    check("unparsed numstat lines are counted", STATS["numstat_unparsed"] == unparsed + 2,
          str(STATS["numstat_unparsed"] - unparsed))

    class Acc:  # the fields note_call and note_result use
        commit_calls, early_results, tools = {}, {}, {}
    acc = Acc()
    pushes.note_call(acc, {"name": "Bash", "id": "t", "input": {"command": "cd \"/w/my repo\" && git -C ../x commit -q"}},
                     "ts", "s", "/w")
    dirs = acc.commit_calls.get("t", [None, None, None, set()])[3]
    check("note_call folders from cwd, cd and -C", dirs == {"/w", "/w/my repo", "/x"}, str(dirs))
    pushes.note_call(acc, {"name": "Bash", "id": "u", "input": {"command": "git status"}}, "ts", "s", "/w")
    check("note_call ignores calls without git commit", "u" not in acc.commit_calls)
    pushes.note_call(acc, {"name": "Bash", "id": "w", "input": {"command": "cd src && cd /abs && git commit"}}, "ts", "s", None)
    check("no cwd: a relative cd is skipped, an absolute one kept", acc.commit_calls["w"][3] == {"/abs"},
          str(acc.commit_calls["w"][3]))
    pushes.note_result(acc, {"tool_use_id": "v"}, "early")
    pushes.note_call(acc, {"name": "Bash", "id": "v", "input": {"command": "git commit -q"}}, "ts", "s", "/w")
    check("a result written before its tool_use ends the span", acc.commit_calls["v"][2] == "early")
    pushes.note_call(acc, {"name": "Bash", "id": "f", "input": {"command": "git commit"}}, "ts", "s", "/w")
    pushes.note_result(acc, {"tool_use_id": "f"}, "first")
    pushes.note_result(acc, {"tool_use_id": "f"}, "second")
    check("the first result of a call ends its span", acc.commit_calls["f"][2] == "first")

    for cmd, hit in (("git commit -q", True), ("cd x && git -C 'my dir' -c user.email=a@b commit -m m", True),
                     ('git -c user.name="A B" --no-pager commit', True), ("git --work-tree=. commit -q", True),
                     ("git commit-tree HEAD^{tree}", False),
                     ("git status", False), ("git log --grep commit", False)):
        check(f"COMMIT_CALL on {cmd!r}", bool(patterns.COMMIT_CALL.search(cmd)) == hit)
    r, q = frozenset({"/r", "/r2"}), frozenset({"/q"})
    calls = [pushes.Call(100, 200, "a", r), pushes.Call(150, 250, "b", r), pushes.Call(100, 200, "c", q),
             pushes.Call(120, 220, "c", q)]  # two parallel calls of one session: not ambiguous
    commits = {"/r": [("h1", 160, 5), ("h2", 300, 1), ("h3", 120, 2)], "/r2": [("h1", 160, 5), ("h2", 300, 1)],
               "/q": [("h4", 160, 7)], "/z": [("h5", 160, 9)]}
    matches, made, other, ambiguous = pushes.match_commits(calls, commits)
    check("overlapping calls: the one that started last", sorted(matches) == [("a", 120, 2), ("b", 160, 5), ("c", 160, 7)],
          str(matches))
    check("a hash in two clones counts once", sum(made.values()) == 3 and made[0] == made[1] == made[3] == 1, str(made))
    check("unmatched hashes counted once (h2 in two clones, h5 in a repo without calls)", other == 2, str(other))
    check("ambiguous only across sessions", ambiguous == 1, str(ambiguous))


def coverage_checks():
    """A .tsx edit, then a commit with a global git option: react-reviewer needed. A schema edit, then git commit-tree:
    no commit, so no database-reviewer needed. A schema edit, then a plain git commit: database-reviewer needed."""
    acc = events.Acc()
    start = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)
    for sid, path, cmd in (("r", "/w/web/src/App.tsx", "git -c user.email=a@b.invalid commit -q -m x"),
                           ("d", "/w/prisma/schema.prisma", "git commit-tree HEAD^{tree} -m x"),
                           ("e", "/w/prisma/schema.prisma", "git commit -q -m x")):
        events.register_tool(acc, {"id": sid + "1", "name": "Edit", "input": {"file_path": path}}, start, "p", sid, True)
        events.register_tool(acc, {"id": sid + "2", "name": "Bash", "input": {"command": cmd}},
                             start + timedelta(minutes=1), "p", sid, True)
        events.handle_result(acc, {"tool_use_id": sid + "2", "content": "ok"})
    coverage.coverage(acc)
    day = acc.n[date(2026, 10, 20)]
    check("coverage: git -c ... commit and git commit count, commit-tree does not",
          (day["react_need"], day["db_need"]) == (1, 1), str((day["react_need"], day["db_need"])))


def summary_checks():
    """summarize adds the days of a window in date order, so its floats do not depend on the hash seed of the run:
    it reads the days in that order, and the sum is the one of that order."""

    class Reads(dict):  # acc.n that keeps the days in the order summarize reads them
        def __init__(self, data):
            super().__init__(data)
            self.days = []

        def get(self, key, default=None):
            self.days.append(key)
            return super().get(key, default)

    acc = events.Acc()
    first = date(2026, 10, 1)
    window = [first + timedelta(days=i) for i in range(12)]  # a set of 12 days almost never comes out in date order
    values = (1e-16, 0.7, 1.1, 0.2, 3e-16)  # only 2 of the 120 orders of these give the sum of the date order
    expected = 0
    for day, value in zip(window, values):
        acc.add(day, "P")
        acc.add(day, "main_weighted", value)
        expected += value
    acc.n = Reads(acc.n)
    got = summary.summarize(acc, window[0], window[-1])["weighted_per_P_m"]
    check("summarize reads the days in date order", acc.n.days[:len(window)] == window, str(acc.n.days[:3]))
    check("summarize adds the days in date order", got == expected / len(values) / 1e6, repr(got))


def repo_checks(tmp):
    """rev-parse: "not a repo" stays silent, a broken repo is counted; the commit pattern has no backtracking blow-up."""
    os.environ["GIT_CEILING_DIRECTORIES"] = tmp
    plain, broken = os.path.join(tmp, "plain"), os.path.join(tmp, "broken")
    os.makedirs(plain)
    os.makedirs(broken)
    git(broken, "init", "-q")
    write(os.path.join(broken, ".git", "config"), "[core\nbad", "a")
    before = STATS["git_rev_parse_failed"]
    check("not a repo: None, not counted", pushes.repo_root(plain, {}) is None and STATS["git_rev_parse_failed"] == before)
    check("broken repo: None and counted", pushes.repo_root(broken, {}) is None and STATS["git_rev_parse_failed"] == before + 1)
    gone = STATS["git_dir_gone"]
    check("a folder that is gone: None and counted",
          pushes.repo_root(os.path.join(tmp, "gone"), {}) is None and STATS["git_dir_gone"] == gone + 1)
    dangling = os.path.join(tmp, "dangling")
    os.makedirs(dangling)
    git(dangling, "init", "-q")
    commit(dangling, "d1", "08:00:00", {"d.ts": "d\n"})
    write(os.path.join(dangling, ".git", "refs", "remotes", "origin", "bad"), "1" * 40 + "\n")
    failed = STATS["git_log_failed"]
    check("git log that fails (a dangling remote ref): None and counted",
          pushes.pushed_commits(dangling, datetime(2026, 1, 1, tzinfo=timezone.utc)) is None
          and STATS["git_log_failed"] == failed + 1)
    started = time.monotonic()
    patterns.COMMIT_CALL.search("git -c " + "a" * 20000 + " status")
    check("COMMIT_CALL on a long command stays fast", time.monotonic() - started < 0.5)


def prompt_rows(next_day):
    """Session p1: every form a prompt or a look-alike takes in a transcript; the comment says if it is a prompt."""
    note = "<system-reminder>\nLinked sessions now: x\n</system-reminder>\n"  # the app's note in front of a prompt
    image = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}}

    def pasted(text, pid="ab12"):
        return f'<pasted_content id="{pid}">{text}</pasted_content id="{pid}">'

    def base(n, when):  # when None: a record without a timestamp
        return {"sessionId": "p1", "uuid": f"p1-{n}", "cwd": "/w/p", **({"timestamp": f"{when}Z"} if when else {})}

    def user(n, when, content, **extra):
        return {**base(n, when), "type": "user", "message": {"role": "user", "content": content}, **extra}

    def queued(n, when, prompt, mode="prompt", **extra):
        return {**base(n, when), "type": "attachment",
                "attachment": {"type": "queued_command", "commandMode": mode, "prompt": prompt, **extra}}

    def answer(n, when, text):
        return {**base(n, when), "type": "assistant", "message": {
            "id": f"pm{n}", "model": "m", "usage": {"input_tokens": 100, "output_tokens": 10},
            "content": [{"type": "text", "text": text}]}}

    human = {"origin": {"kind": "human"}}
    d = DAY + "T08:"
    return [
        user(1, d + "00:00", "зроби звіт"),                                           # prompt
        answer(2, d + "01:00", "Зроблено частину."),
        user(3, d + "02:00", [image]),                                                # prompt: [картинка]
        user(4, d + "03:00", pasted("Last login: Mon\nu@h:~$ ls") + " подивись"),     # prompt, pasted first
        user(5, d + "04:00", "перевір це: " + pasted("спрости все")),                 # prompt; «спрости» is pasted
        user(6, d + "05:00", "<ci-monitor-event>CI failed: error</ci-monitor-event>"),  # a CI event, no origin
        user(7, d + "06:00", note),                                                   # the note only
        user(8, d + "07:00", note + "а тепер тести", **human),                        # prompt behind the note
        user(9, d + "08:00", "[Request interrupted by user]"),
        user(10, d + "09:00", "<command-name>/foo</command-name>\n<command-message>foo</command-message>"),  # a skill
        user(11, d + "10:00", "привіт від іншої сесії", origin={"kind": "peer"}),
        user(12, d + "11:00", "мета", isMeta=True),
        user(13, d + "12:00", "дивне", origin={"kind": "martian"}),                    # unknown origin: warned
        user(27, d + "13:00", "<div> не центрується"),                                # typed HTML: warned
        user(33, d + "13:30", "<div> ще раз"),                                        # the same tag again: div 2
        user(28, d + "14:00", "<side-sessions-event>x</side-sessions-event>"),       # the app's envelope
        user(29, d + "15:00", "звіт", origin={"kind": "observer"}),                    # an origin of the binary
        queued(14, d + "20:00", "ще одне", **human),                                  # prompt sent while working
        queued(15, d + "21:00", [image], **human),                                    # prompt: [картинка]
        queued(16, d + "22:00", pasted("docker compose ps"), **human),                # prompt, pasted first
        queued(17, d + "23:00", note + "і ще", **human),                              # prompt behind the note
        queued(18, d + "24:00", "<task-notification>x</task-notification>", mode="task-notification"),
        queued(19, d + "25:00", "<agent-message>hi</agent-message>", origin={"kind": "peer"}, isMeta=True),
        queued(20, d + "26:00", "щось", mode="telepathy"),                            # unknown mode: warned
        {**queued(30, d + "27:00", "ще"), "origin": {"kind": "human"}},               # origin on the entry: warned
        queued(31, d + "28:00", "від плагіна", origin={"kind": "plugin", "asUser": True}),  # a plugin's: warned
        user(32, d + "29:00", "<3 дякую"),                                            # "<" and no tag: warned
        answer(21, d + "30:00", "Готово, усе працює."),
        user(22, d + "31:00", "ок " + pasted("a" * 500, "cd34")),                     # prompt; its label says 500
        user(26, d + "32:00", "спро" + pasted("x", "ef56") + "сти"),                  # prompt; the label parts words
        user(23, f"{next_day}T08:00:00", note + "продовжуй"),                         # the next day's only prompt
        user(24, None, "без часу"),                                                   # prompts with no day:
        queued(25, None, "і в черзі без часу", **human),                              # claude-time only
    ]


def prompt_checks(tmp):
    """claude-metrics counts the prompts of claude-time's scan (one rule, prompt_text): user messages and queued ones,
    of only images or pasted text too, behind the app's note; not CI events, notes, notifications, other sessions or
    meta records. Pasted text stays out of the text metrics, and a record of an unknown form (origin, a plugin's too,
    mode, a tag at the start that is not Claude Code's, "<" and no tag, a queued origin on its entry) is counted and
    warned, by kind and name, in the same line as claude-time's, and --json lists all of them."""
    next_day = (date.fromisoformat(DAY) + timedelta(days=1)).isoformat()
    home = os.path.join(tmp, "prompts-home")
    os.makedirs(os.path.join(home, ".claude", "skills", "foo"))
    path = os.path.join(home, ".claude", "projects", "-w-p", "p1.jsonl")
    write(path, "".join(json.dumps(r) + "\n" for r in prompt_rows(next_day)))
    run = subprocess.run([sys.executable, "-I", CLI, "--json", "--before", "2026-10-01", "2026-10-10",
                          "--after", DAY, next_day], env={"HOME": home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                                                          "LC_ALL": "C"}, capture_output=True, text=True, check=False)
    check("prompts: cli exit 0", run.returncode == 0, run.stderr[-500:])
    report = json.loads(run.stdout) if run.returncode == 0 else {}
    after, scan = report.get("after", {}), report.get("scan", {})
    check("prompts: 1, 3, 4, 5, 8, 14-17, 22, 23 and 26", after.get("P") == 12, str(after.get("P")))
    rec = time_scan.scan_session(path, {"p1"}) or {}
    got = (len(rec.get("prompt_ts", [])), rec.get("prompts"))
    check("prompts: claude-time's scan puts the same on days, and 24, 25 only in its session total",
          got == (after.get("P"), (after.get("P") or 0) + 2), str(got))
    check("prompts: a slash command is a skill call, not a prompt", after.get("skill_calls") == 1,
          str(after.get("skill_calls")))
    check("prompts: a day whose only prompt is behind the app's note is active", after.get("active_days") == 2,
          str(after.get("active_days")))
    check("prompts: pasted first (4, 16) are pasted logs", after.get("paste_skipped") == 2, str(after.get("paste_skipped")))
    check("prompts: «спрости» inside a pasted block is no «спрости»", after.get("simplify_per_day") == 0,
          str(after.get("simplify_per_day")))
    check("prompts: the size in a label (500) is no HTTP 500 after «готово»", after.get("done_candidates") == 0,
          str(after.get("done_candidates")))
    label = getattr(patterns, "PASTED_LABEL", None)  # a tree without it fails this check instead of the whole test
    check("prompts: PASTED_LABEL matches claude-time's label", bool(label and label.fullmatch(pasted_label(" ab "))))
    check("prompts: unknown origins, mode, tags, «<» and queued origin in the footer", scan.get("unknown_prompts") == 7,
          str(scan.get("unknown_prompts")))
    check("prompts: --json names all their kinds, more than 5 too, a kind without a name as \"\"",
          scan.get("unknown_forms") == [
              {"kind": "origin", "name": "martian", "count": 1}, {"kind": "origin", "name": "plugin", "count": 1},
              {"kind": "mode", "name": "telepathy", "count": 1}, {"kind": "queued_origin", "name": "human", "count": 1},
              {"kind": "tag", "name": "div", "count": 2}, {"kind": "no_tag", "name": "", "count": 1}],
          str(scan.get("unknown_forms")))
    check("prompts: the footer's number is the sum of the --json kinds",
          scan.get("unknown_prompts") == sum(f.get("count", 0) for f in scan.get("unknown_forms") or []))
    check("prompts: unknown forms warned with their kinds and names, text with «<» in a примітка line",
          {UNKNOWN_LINE, TYPED_LINE} <= set(run.stderr.splitlines()), run.stderr[-700:])
    time_run = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", "time-register.py"), "--by", "session",
                               "--home", os.path.join(tmp, "prompts-reg")],
                              env={"HOME": home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"},
                              capture_output=True, text=True, check=False)
    warned = [[x for x in r.stderr.splitlines() if x.startswith(UNKNOWN_PREFIXES)] for r in (run, time_run)]
    check("prompts: claude-time warns of the same records in the same words, the tag div and the origin plugin too",
          warned[0] == warned[1] == [UNKNOWN_LINE, TYPED_LINE], str(warned))


def message_checks(tmp):
    """A record whose message is no object (a string, a list, a number) fails neither claude-metrics nor claude-time:
    a user one is no prompt and is warned of as its own kind, once even with an unknown origin, in the same words by
    both tools (--json lists the kind), a meta, sidechain or compact summary one is not warned of so. claude-metrics
    also counts every such record it reads (all but the compact summary in the main transcript: user and assistant
    ones, a subagent's too) in message_not_object and warns of them in a line of its own; an assistant one also
    counts in assistant_no_usage."""
    home = os.path.join(tmp, "message-home")
    os.makedirs(os.path.join(home, ".claude", "skills"))
    proj = os.path.join(home, ".claude", "projects", "-w-m")

    def row(n, kind, message):
        return {"type": kind, "sessionId": "m1", "uuid": f"m1-{n}", "cwd": "/w/m", "timestamp": f"{DAY}T08:{n:02}:00Z",
                "message": message}

    answer = {"id": "mm1", "model": "m", "usage": {"input_tokens": 100, "output_tokens": 10},
              "content": [{"type": "text", "text": "Зроблено."}]}
    rows = [row(1, "user", {"role": "user", "content": "зроби звіт"}),
            {**row(2, "user", "message рядком"), "origin": {"kind": "martian"}},
            row(3, "user", ["message списком"]), row(4, "user", 7), row(5, "assistant", "відповідь рядком"),
            row(6, "assistant", answer),
            *({**row(n, "user", "службовий рядком"), flag: True}
              for n, flag in ((9, "isMeta"), (10, "isSidechain"), (11, "isCompactSummary")))]
    write(os.path.join(proj, "m1.jsonl"), "".join(json.dumps(r) + "\n" for r in rows))
    side = [row(7, "user", "субагент рядком"), row(8, "assistant", ["субагент списком"])]
    write(os.path.join(proj, "m1", "subagents", "agent-m.jsonl"), "".join(json.dumps(r) + "\n" for r in side))
    env = {"HOME": home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}
    run = subprocess.run([sys.executable, "-I", CLI, "--json", "--before", "2026-10-01", "2026-10-10", "--after", DAY,
                          DAY], env=env, capture_output=True, text=True, check=False)
    report = json.loads(run.stdout) if run.returncode == 0 else {}
    scan = report.get("scan", {})
    check("message no object: claude-metrics runs and counts only the typed prompt",
          run.returncode == 0 and report.get("after", {}).get("P") == 1, run.stderr[-500:])
    got = (scan.get("unknown_forms"), scan.get("assistant_no_usage"), scan.get("message_not_object"))
    check("message no object: --json has the 3 user records as their kind, the 2 assistant ones without usage, all 8",
          got == ([{"kind": "message", "name": "", "count": 3}], 2, 8), str(got))
    check("message no object: claude-metrics warns of all 8 in a line of its own",
          run.stderr.splitlines().count(MESSAGE_METRICS_LINE) == 1, run.stderr[-700:])
    for mode in ((), ("--weekly", "--since", "2026-10-01"), ("--candidates",)):
        other = subprocess.run([sys.executable, "-I", CLI, *mode, "--before", "2026-10-01", "2026-10-10", "--after", DAY,
                                DAY], env=env, capture_output=True, text=True, check=False)
        check(f"message no object: {' '.join(mode[:1]) or 'the plain report'} warns of them too",
              other.returncode == 0 and other.stderr.splitlines().count(MESSAGE_METRICS_LINE) == 1, other.stderr[-700:])
    time_run = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", "time-register.py"), "--by", "session",
                               "--home", os.path.join(tmp, "message-reg")], env=env, capture_output=True, text=True,
                              check=False)
    warned = [[x for x in r.stderr.splitlines() if x.startswith(UNKNOWN_PREFIXES)] for r in (run, time_run)]
    check("message no object: claude-time runs too, both warn of the user records in the same words",
          time_run.returncode == 0 and warned[0] == warned[1] == [MESSAGE_LINE], str(warned) + time_run.stderr[-500:])
    check("message no object: the line of its own is claude-metrics' only", MESSAGE_METRICS_LINE not in time_run.stderr)


def forms_rows():
    """Session f1 (a main transcript and a subagent's) with a record of every other unknown form."""
    def row(n, kind, **extra):
        return {"type": kind, "sessionId": "f1", "uuid": f"f1-{n}", "cwd": "/w/f", "timestamp": f"{DAY}T08:{n:02}:00Z",
                **extra}

    def answer(n, mid, usage, model="m"):
        return row(n, "assistant", message={"id": mid, "model": model, "usage": usage, "content": []})

    def prompt(n, text, **extra):
        return {**row(n, "user", message={"role": "user", "content": text}), **extra}

    main = [prompt(1, "зроби звіт"), answer(2, "fa2", {"input_tokens": 100, "output_tokens": 10}),
            row(29, "assistant", message={"id": "fa2", "model": "m", "usage": {"input_tokens": 100, "output_tokens": 10},
                                         "content": [{"type": "tool_use", "id": "tu29", "name": "Bash",
                                                      "input": {"command": "python3 x.py"}}]}),
            row(30, "user", message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu29",
                                                                  "content": [{"type": "text", "text": ["Traceback"]},
                                                                              {"type": "text", "text": 7}]}]}),
            row(3, "attachment", attachment="рядок"),
            row(4, "system", subtype="compact_boundary", compactMetadata="auto"),
            row(5, "system", subtype="compact_boundary", compactMetadata=["auto"]),
            row(14, "system", subtype="compact_boundary", compactMetadata=None),  # null or none: known, not counted
            row(15, "system", subtype="compact_boundary"),
            *(row(n, "system", subtype="compact_boundary", compactMetadata={"trigger": "auto", "preTokens": pre})
              for n, pre in ((23, True), (24, float("nan")), (25, float("inf")), (26, "x"), (27, None), (28, 5000))),
            prompt(6, "запит з uuid списком", uuid=["x"]), prompt(7, "запит з sessionId об'єктом", sessionId={"x": 1}),
            prompt(8, 7),  # content of another form
            prompt(19, [{"type": "text", "text": None}]),  # blocks without text
            answer(9, ["x"], {"input_tokens": "100", "cache_read_input_tokens": "5", "output_tokens": 5}, model=["m"]),
            answer(10, "fa10", {"input_tokens": 200, "cache_creation_input_tokens": 50, "output_tokens": 1,
                                "cache_creation": {"ephemeral_5m_input_tokens": "50", "ephemeral_1h_input_tokens": 0}}),
            row(13, "assistant", requestId="fr13", message={"usage": {"input_tokens": 50}, "content": []}),  # no id or model
            answer(16, "fa16", {"input_tokens": 10, "output_tokens": 1,
                                "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}),
            answer(17, "fa16", {"input_tokens": 10, "output_tokens": 2, "cache_creation": 5}),  # a streamed line of it
            answer(18, "fa18", {"input_tokens": float("nan"), "cache_read_input_tokens": 190, "output_tokens": True}),
            # skipped answers: their usage is not read, so it leaves the metrics complete
            answer(20, "fs20", {"input_tokens": "x"}, model="<synthetic>"),
            {**answer(21, "fe21", {"input_tokens": "x"}), "isApiErrorMessage": True}]
    side = [{**row(31, "user", message={"role": "user", "content": [{"type": "text", "text": 7}]}), "isMeta": True},
            row(11, "attachment", attachment=["x"]),
            answer(12, {"x": 1}, {"input_tokens": 10, "output_tokens": "x"}, model=["m"]),
            answer(22, "fs22", {"output_tokens": "x"}, model="<synthetic>")]
    return main, side


def forms_checks(tmp):
    """The other unknown forms fail neither tool. In a main transcript an attachment that is no object, content of a
    would-be prompt of another form, blocks without text, a uuid and a sessionId that are not text are warned of in
    the same words by both tools (--json lists the kinds), the entry with such a uuid or sessionId still counts. The
    fields only the metrics read, in a subagent's transcript too (an attachment that is no object, compactMetadata that
    is no object, a preTokens of an auto compaction that is no number: true, NaN, an infinity, text, a message id or
    model that is not text, a token count that is no number: text, true, NaN, a cache_creation that is no object, also
    in a streamed line of an answer whose first one has the split, and a text block whose text is no text: in a tool
    result, a would-be prompt and a subagent's meta record), are taken as missing (a compaction of an unknown trigger
    or without preTokens, the request by its uuid, the count left out): claude-metrics counts each record once in its
    key and warns of them in a line of its own, in every mode. compactMetadata that is null or none is a known form:
    only the unknown trigger, a null preTokens only none; a synthetic answer and an API error are skipped before their
    usage is read, in a subagent's transcript too. A JSON line that is no object or has an integer over Python's digit
    limit is a broken line in both tools."""
    home = os.path.join(tmp, "forms-home")
    os.makedirs(os.path.join(home, ".claude", "skills"))
    proj = os.path.join(home, ".claude", "projects", "-w-f")
    main_rows, side_rows = forms_rows()
    write(os.path.join(proj, "f1.jsonl"), "".join(json.dumps(r) + "\n" for r in main_rows) + "[1, 2]\n"
          + '{"n": ' + "1" * 5000 + "}\n")  # the last line: an integer over Python's digit limit
    write(os.path.join(proj, "f1", "subagents", "agent-f.jsonl"), "".join(json.dumps(r) + "\n" for r in side_rows))
    env = {"HOME": home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}
    windows = ("--before", "2026-10-01", "2026-10-10", "--after", DAY, DAY)
    run = subprocess.run([sys.executable, "-I", CLI, "--json", *windows], env=env, capture_output=True, text=True,
                         check=False)
    report = json.loads(run.stdout) if run.returncode == 0 else {}
    after, scan = report.get("after", {}), report.get("scan", {})
    got = (after.get("P"), after.get("requests_per_day"), after.get("ctx_mean"), after.get("compactions"))
    check("forms: claude-metrics runs: 3 prompts, 6 requests (one by its uuid, one by requestId), context without the "
          "counts of another form, 10 compactions", run.returncode == 0 and got == (3, 6, 100, 10),
          f"{got} {run.stderr[-500:]}")
    check("forms: the median of preTokens leaves out those of another form (true, NaN, an infinity, text)",
          after.get("compact_pre_median") == 5000, str(after.get("compact_pre_median")))
    fields = {k: scan.get(k) for k in (*sorted(FIELD_KEYS), "compact_trigger_unknown", "compact_no_pretokens",
                                       "bad_lines", "assistant_no_usage")}
    check("forms: --json counts each field form once per record, main and subagent", fields == {
        "attachment_not_object": 2, "compact_metadata_not_object": 2, "pretokens_not_number": 4,
        "message_id_not_text": 2, "model_not_text": 2, "usage_not_number": 5, "text_not_text": 3,
        "compact_trigger_unknown": 4, "compact_no_pretokens": 5, "bad_lines": 2, "assistant_no_usage": 1}, str(fields))
    check("forms: --json names the prompt rule's new kinds in their order", scan.get("unknown_forms") == [
        {"kind": "attachment", "name": "", "count": 1}, {"kind": "content", "name": "", "count": 1},
        {"kind": "blocks", "name": "", "count": 1}, {"kind": "uuid", "name": "", "count": 1},
        {"kind": "session_id", "name": "", "count": 1}], str(scan.get("unknown_forms")))
    for mode in (("--json",), (), ("--weekly", "--since", "2026-10-01"), ("--candidates",)):
        other = subprocess.run([sys.executable, "-I", CLI, *mode, *windows], env=env, capture_output=True, text=True,
                               check=False)
        check(f"forms: {' '.join(mode[:1]) or 'the plain report'} warns of the fields in a line of their own",
              other.returncode == 0 and other.stderr.splitlines().count(FIELDS_LINE) == 1, other.stderr[-700:])
    time_run = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", "time-register.py"), "--by", "session",
                               "--home", os.path.join(tmp, "forms-reg")], env=env, capture_output=True, text=True,
                              check=False)
    try:
        rec = time_scan.scan_session(os.path.join(proj, "f1.jsonl"), {"f1"}) or {}
    except (TypeError, AttributeError) as e:  # a tree that fails on these forms fails the check, not the whole test
        rec = {"error": repr(e)}
    check("forms: claude-time runs too and counts the same 3 prompts", time_run.returncode == 0
          and rec.get("prompts") == 3, f"{rec.get('error', '')} {time_run.stderr[-500:]}")
    warned = [[x for x in r.stderr.splitlines() if x.startswith(UNKNOWN_PREFIXES)] for r in (run, time_run)]
    check("forms: both warn of the prompt rule's forms in the same words", warned[0] == warned[1] == [FORMS_LINE],
          str(warned))
    check("forms: the fields line is claude-metrics' only", "полями незнайомої форми" not in time_run.stderr,
          time_run.stderr[-500:])
    broken = [[x for x in r.stderr.splitlines() if x.startswith("увага: битих рядків 2,")] for r in (run, time_run)]
    check("forms: both count the JSON line that is no object and the one over the digit limit as broken",
          all(len(b) == 1 for b in broken), str(broken))


def usage_checks():
    """usage_of on its own: a token count that is no number (text, true, NaN, an infinity, an int too large for a
    float) under each key, named here so that a key dropped from TOKEN_KEYS or SPLIT_KEYS fails, and a cache_creation
    that is no object are left out, the other keys kept, each record counted once in usage_not_number; a usage of
    known forms comes back as it is."""
    usage_of = getattr(metrics_transcript, "usage_of", None)
    if usage_of is None:  # a tree without it fails this check instead of the whole test
        check("usage_of: claude_metrics.transcript has usage_of", False)
        return
    start, bad = STATS["usage_not_number"], []
    tokens = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    for key in tokens:
        for value in ("1", True, float("nan"), float("inf"), 10 ** 400):
            got = usage_of({"usage": {key: value, "speed": "fast"}})
            if got != {"speed": "fast"}:
                bad.append(f"{key}={value!r}")
    splits = ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")
    for key in splits:
        if usage_of({"usage": {"cache_creation": {key: "1", "other": 2}}}) != {"cache_creation": {"other": 2}}:
            bad.append(f"cache_creation.{key}")
    for value in ("x", 5, True, ["x"]):
        if usage_of({"usage": {"cache_creation": value, "input_tokens": 3}}) != {"input_tokens": 3}:
            bad.append(f"cache_creation={value!r}")
    counted = STATS["usage_not_number"] - start
    known = {"input_tokens": 5, "output_tokens": 0, "cache_creation": None, "service_tier": "standard"}
    check("usage_of: each count of another form and a cache_creation that is no object are left out, the rest kept",
          not bad, ", ".join(bad))
    check("usage_of: each such record counted once", counted == 5 * len(tokens) + len(splits) + 4, str(counted))
    check("usage_of: a usage of known forms comes back as it is and is not counted",
          usage_of({"usage": known}) is known and STATS["usage_not_number"] - start == counted)


def main():
    unit_checks()
    usage_checks()
    coverage_checks()
    summary_checks()
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="claude-metrics-test."))
    try:
        repo_checks(tmp)
        prompt_checks(tmp)
        message_checks(tmp)
        forms_checks(tmp)
        language_checks(tmp, check, CLI)
        permission_checks(tmp, check, CLI)
        a, a2, b = build_repos(tmp)
        home = build_home(tmp, a, a2, b)
        report, err = run_cli(tmp, home)
        after = report.get("after", {})
        scan = report.get("scan", {})
        check("no message warning on a clean run", "message не об'єкт" not in err and "message_not_object" not in scan,
              err[-300:])
        check("no fields warning or key on a clean run", "полями незнайомої форми" not in err
              and not FIELD_KEYS & set(scan), err[-300:])
        # weighted: input 1, cache read 0.1, output 5; S1 with its subagent
        s1, s2, s3, s4 = 1500 + 3250 + 4000, 5050, 3000, 2000 + 1000 + 500
        paid, spent = s1 + s3 + s4, s1 - 4000 + s2 + s3 + s4  # S1's subagent spent on the day before the window
        check("push_commits = c1, c2, c5, c7, c8, c9", after.get("push_commits") == 6, str(after.get("push_commits")))
        check("push_lines = 10 + 7 + 7 + 4 + 2 + 1 (no lock, png, rename)", after.get("push_lines") == 31,
              str(after.get("push_lines")))
        check("cost per commit", close(after.get("cost_per_commit_m"), paid / 6 / 1e6), str(after.get("cost_per_commit_m")))
        check("cost per 100 lines", close(after.get("cost_per_100_lines_m"), 100 * paid / 31 / 1e6),
              str(after.get("cost_per_100_lines_m")))
        check("share without push = S2", close(after.get("no_push_weighted_pct"), 100 * s2 / spent),
              str(after.get("no_push_weighted_pct")))
        check("hand-made pushed commits c4, c6 and side are other, c4 once though in two clones; no merge",
              scan.get("pushed_commits_other") == 3, str(scan.get("pushed_commits_other")))
        check("unpushed commit call of S2", scan.get("commit_calls_unpushed") == 1, str(scan.get("commit_calls_unpushed")))
        check("7 commit calls, 6 matched, 0 without a repo",
              (scan.get("commit_calls"), scan.get("commit_calls_matched"), scan.get("commit_calls_no_repo")) == (7, 6, 0),
              str((scan.get("commit_calls"), scan.get("commit_calls_matched"), scan.get("commit_calls_no_repo"))))
        check("no git warning on a clean run", not any("git" in w for w in report.get("warnings", [])),
              str(report.get("warnings")))
        check("three repos read (repo_a, its clone, repo_b)", scan.get("git_repos") == 3, str(scan.get("git_repos")))
        check("before window empty", report.get("before", {}).get("cost_per_commit_m") is None)
        _out, err = run_cli(tmp, home, mode=("--weekly", "--since", "2026-10-01"))
        check("--weekly does not read git", "git_repos=" not in err, err[-300:])
        check("no __pycache__ written", not any(os.path.exists(os.path.join(ROOT, "tools", p, "__pycache__"))
                                                for p in ("claude_metrics", "time_register")))
        fake = os.path.join(tmp, "fakebin")
        write(os.path.join(fake, "git"), "#!/bin/sh\n")  # not executable: PermissionError, which must not end the run
        report, err = run_cli(tmp, home, path=fake)
        check("git not executable: counted and warned", "git_cannot_run=" in err
              and any("git_cannot_run" in w for w in report.get("warnings", [])), err[-300:])
        report, err = run_cli(tmp, home, path="/nonexistent")  # no git: counted in the footer, no numbers, no crash
        check("no git: no cost per commit", report.get("after", {}).get("cost_per_commit_m") is None)
        check("no git: git_missing in the footer", "git_missing=" in err, err[-300:])
        check("no git: a warning says the cost is incomplete",
              any("git прочитано не повністю" in w for w in report.get("warnings", [])), str(report.get("warnings")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for f in FAILS:
        print("FAIL " + f)
    print(f"metrics test: {CHECKS[0]} checks, {len(FAILS)} failed")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
