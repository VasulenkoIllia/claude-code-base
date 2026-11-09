"""Checks of claude-metrics for tests/metrics-test.py: real permission prompts from permissionDecision, by kind, with the
time from the call to its result, and the days of a session with ssh, on one made-up home."""
import json
import os
import subprocess
import sys

from claude_metrics.asks import call_kind, permission_summary, prompted
from metrics_lang_checks import answer, record, tool, write_session

DAY, LATER = "2026-10-20", "2026-10-21"
ONCE = {"decision": "accept", "source": "user_temporary", "grantScope": "once"}
ALWAYS = {"decision": "accept", "source": "user_permanent"}
SAVED = {"decision": "accept", "source": "user_permanent", "reasonType": "rule", "ruleSource": "userSettings"}
AUTO = {"decision": "accept", "source": "config", "reasonType": "classifier"}
DENIED = {"decision": "reject", "source": "config", "reasonCode": "rule:userSettings"}
REFUSED = {"decision": "reject", "source": "user_reject", "reasonType": "rule"}
LOST = {"decision": "reject", "source": "config", "reasonCode": "permissionStreamClosed"}
SECOND = "T09:{:02}:{:02}Z"


def call(sid, n, day, tid, name, command):
    return answer(sid, n, day, [tool(name, tid, {"command": command})]) | {"timestamp": day + SECOND.format(n, 0)}


def result(sid, n, day, tid, seconds, decision):
    return record(sid, 100 + n, "user", day, message={"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tid, "content": "ok"}]}, permissionDecision=decision) | {
            "timestamp": day + SECOND.format(n + seconds // 60, seconds % 60)}


def asked(sid, n, day, tid, name, command, seconds, decision):
    return [call(sid, n, day, tid, name, command), result(sid, n, day, tid, seconds, decision)]


def hook_said_ask(sid, n, day, tid):
    return record(sid, 200 + n, "attachment", day, attachment={
        "type": "hook_success", "toolUseID": tid,
        "stdout": json.dumps({"hookSpecificOutput": {"permissionDecision": "ask"}})}) | {
            "timestamp": day + SECOND.format(n, 1)}


def main_rows():
    """Eleven asks: a read of 30 s, a read of 400 s and a change of 500 s over ssh, a push of an "always allow", a merge
    refused, a bash-guard ask of an ssh command, a prompt that closed on an error, another tool (an Edit of a file that
    asks), and on the later day one more read, a call whose result comes first and a push of a subagent. Not asks: a
    call the classifier passed, a saved rule, a deny rule, a quiz."""
    rows = [record("r1", 0, "user", DAY, message={"role": "user", "content": "зроби"})]
    rows += asked("r1", 1, DAY, "t1", "Bash", "ssh host 'df -h'", 30, ONCE)
    rows += asked("r1", 2, DAY, "t2", "Bash", "S=1\nssh host 'bash -s' < check.sh", 400, ONCE)
    rows += asked("r1", 3, DAY, "t3", "Bash", "ssh host 'sudo systemctl restart nginx'", 500, ONCE)
    rows += asked("r1", 4, DAY, "t4", "Bash", "git -C repo push origin main", 10, ALWAYS)
    rows += asked("r1", 5, DAY, "t5", "Bash", "git push && gh pr merge 5 --squash", 20, REFUSED)
    rows += [call("r1", 6, DAY, "t6", "Bash", "ssh host 'docker volume rm x'"), hook_said_ask("r1", 6, DAY, "t6"),
             result("r1", 6, DAY, "t6", 40, ONCE)]
    rows += asked("r1", 7, DAY, "t7", "Bash", "git push", 3, LOST)
    rows += asked("r1", 8, DAY, "t8", "Edit", "", 50, ONCE)
    rows += asked("r1", 9, DAY, "t9", "Bash", "npm test", 1, AUTO)
    rows += asked("r1", 10, DAY, "t10", "WebSearch", "", 1, SAVED)
    rows += asked("r1", 11, DAY, "t11", "Bash", "cat .env", 1, DENIED)
    rows += asked("r1", 12, DAY, "t12", "AskUserQuestion", "", 90, ONCE)
    rows += asked("r1", 13, DAY, "t13", "Bash", "ssh host uptime", 2, "не об'єкт")
    rows += asked("r1", 14, DAY, "t14", "Bash", "ssh host uptime", 2, {"decision": "accept", "source": "phone"})
    return rows


def later_rows():
    return ([result("r2", 2, LATER, "t21", 5, ONCE), call("r2", 2, LATER, "t21", "Bash", "ssh host 'ls /'")]
            + asked("r2", 3, LATER, "t22", "Bash", "ssh host uptime", 7, ONCE))


def kind_checks(check):
    for cmd, kind in (("ssh host 'df -h'", "ssh_read"), ("ssh host 'ls 2>/dev/null; cat x'", "ssh_read"),
                      ("cd x && ssh host uptime", "ssh_read"), ("FOO=1 ssh host uptime", "ssh_read"),
                      ("ssh host 'bash -s' < check.sh", "ssh_read"), ("ssh host \"git log -3\"", "ssh_read"),
                      ("ssh host 'psql -c \"select 1\"'", "ssh_read"), ("ssh host 'cat /x > /tmp/y'", "ssh_write"),
                      ("ssh host 'sudo rm /x'", "ssh_write"), ("ssh host 'docker compose -f a up -d'", "ssh_write"),
                      ("ssh host 'psql -c \"DELETE FROM x\"'", "ssh_write"), ("scp a host:/b", "ssh_write"),
                      ("rsync -a a host:/b", "ssh_write"), ("git push origin main", "push"),
                      ("git -C /r push", "push"), ("gh -R o/r pr merge 5", "merge"), ("git push && gh pr merge 5", "merge"),
                      ("echo ssh host", "other"), ("git log --grep push", "other"), ("npm test", "other")):
        check(f"asks: the kind of {cmd}", call_kind(cmd) == kind, call_kind(cmd))
    check("asks: only a prompt counts", [prompted(d) for d in (ONCE, ALWAYS, SAVED, AUTO, DENIED, REFUSED, LOST)] == [
        True, True, False, False, False, True, True])
    empty = permission_summary([], 0)
    check("asks: an empty window", (empty["perm_asks_per_day"], empty["perm_server_median"], empty["perm_server_max"]) == (
        None, None, None), str(empty))


def permission_checks(tmp, check, cli):
    kind_checks(check)
    home = os.path.join(tmp, "perm-home")
    os.makedirs(os.path.join(home, ".claude", "skills"))
    prefix = "-Users-someone-WebstormProjects-demo-app"
    subagent = asked("r2", 4, LATER, "t23", "Bash", "git push", 60, ONCE)
    files = {f"{prefix}/r1.jsonl": main_rows(), f"{prefix}/r2.jsonl": later_rows(),
             f"{prefix}/r2/subagents/agent-a.jsonl": subagent}
    for rel, rows in files.items():
        write_session(home, rel, rows)
    env = {"HOME": home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}
    args = ("--before", "2026-10-01", "2026-10-10", "--after", DAY, LATER)

    def run(*mode, window=args):
        return subprocess.run([sys.executable, "-I", cli, *mode, *window], env=env, capture_output=True, text=True,
                              encoding="utf-8", check=False)

    res = run("--json")
    check("asks: claude-metrics runs", res.returncode == 0, res.stderr[-500:])
    report = json.loads(res.stdout) if res.returncode == 0 else {}
    after, before, scan = report.get("after", {}), report.get("before", {}), report.get("scan", {})
    check("asks: all kinds, no rule, classifier, deny or quiz", after.get("perm_asks") == 11, str(after.get("perm_asks")))
    check("asks: rows by kind, the time from the call to the result", after.get("perm_rows") == [
        ["ssh_read", 4, 18.5, 400, 1], ["ssh_write", 1, 500, 500, 1], ["push", 3, 10, 60, 0], ["merge", 1, 20, 20, 0],
        ["guard", 1, 40, 40, 0], ["other", 1, 50, 50, 0]], str(after.get("perm_rows")))
    check("asks: waits over 5 minutes", after.get("perm_long_waits") == 2, str(after.get("perm_long_waits")))
    check("asks: the hours of it", abs((after.get("perm_wait_h") or 0) - 1125 / 3600) < 1e-9, str(after.get("perm_wait_h")))
    check("asks: days of a session with ssh, a subagent's ask in its session", (
        after.get("perm_server_days"), after.get("perm_server_median"), after.get("perm_server_max"),
        after.get("perm_server_over")) == (2, 5.5, 8, 0), str([after.get(k) for k in (
            "perm_server_days", "perm_server_median", "perm_server_max", "perm_server_over")]))
    check("asks: the bash-guard ask of ssh is counted by the hook too", after.get("hook_asks") == 1, str(after.get("hook_asks")))
    check("asks: no field in the window: no rate, not a zero", before.get("perm_asks_per_day") is None,
          str(before.get("perm_asks_per_day")))
    check("asks: a decision that is no object", scan.get("permission_not_object") == 1, str(scan.get("permission_not_object")))
    plain = run()
    check("asks: the plain report has the section", "Запити дозволу, вікно «після» (11" in plain.stdout
          and "понад 10: 0" in plain.stdout and any(line.split()[:3] == ["ssh,", "читання", "4"] for line in
                                                    (ln.strip() for ln in plain.stdout.splitlines())), plain.stdout[-600:])
    check("asks: the unknown field is warned of", "permissionDecision не об'єкт 1" in plain.stderr, plain.stderr[-300:])
    check("asks: a source of another form is warned of", "незнайомий source у permissionDecision 1" in plain.stderr,
          plain.stderr[-300:])
    check("asks: a window with no field has no count", any(
        ln.split()[-2:] == ["-", "11"] for ln in plain.stdout.splitlines() if ln.startswith("запитів дозволу (усі")),
        plain.stdout[-900:])
    weekly = run("--weekly", "--since", DAY, window=())
    row = next((ln for ln in weekly.stdout.splitlines() if ln.startswith("20.10.2026")), "")
    check("weekly: asks of the hook, real asks, long waits", row.split()[-10:-6] == ["1", "11", "2", "0"], row)
    many = [record("r3", n, "user", "2026-10-22", message={"role": "user", "content": f"запит {n}"}) for n in range(20)]
    write_session(home, f"{prefix}/r3.jsonl", many)
    quiet = run("--json", window=("--before", "2026-10-01", "2026-10-10", "--after", "2026-10-22", "2026-10-22"))
    warned = [w for w in json.loads(quiet.stdout).get("warnings", []) if "permissionDecision" in w]
    check("asks: 20 prompts and no decision: the warning", len(warned) == 1, str(warned))
    empty_week = run("--weekly", "--since", "2026-10-22", window=())
    row = next((ln for ln in empty_week.stdout.splitlines() if ln.startswith("22.10.2026")), "")
    check("weekly: a week with no field has no count", row.split()[-8:-6] == ["-", "-"], row)
