#!/usr/bin/env -S python3 -I
"""Offline test of the bash gate of tests/hook-replay.py on made-up results: an ask about the identity that goes away in
a /tmp folder, for a /tmp folder the command names or for identity text only in a heredoc body passes, one in another
folder fails (also with /tmp only in a log path); any other ask passes only for a class of lost_kind that explains it:
hooks/bash-guard.sh without bash-guard-exec.py, the old hook here, must not ask once the text of the class is gone; a
line in the bash-guard error log fails; --match keeps its rows, says what it dropped, counts the median of new asks over all
working days, gives a QUICK verdict and fails with no call kept. Prints the failed cases and a last line with the count; exit 0 or 1."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('hook_replay', os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                          'hook-replay.py'))
hr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hr)

CTX = {'days': 1, 'since': '2026-10-01', 'today': '2026-10-02', 'include_audit': True, 'files': 0, 'audit_skipped': 0,
       'bad': 0, 'no_command': 0}
LOG = ['2026-10-02T00:00:00Z ShimExit 1 KeyError']
ID = 'коміт чи git-налаштування з іменем'
CASES = [('/private/tmp/x', 'git -c user.name=t commit', ID, [], True),
         ('/Users/o/p', 'cd /tmp/r && git -c user.name=t commit', ID, [], True),
         ('/Users/o/p', 'X=/private/tmp/r; git -C "$X" -c user.name=t commit', ID, [], True),
         ('/Users/o/p', "cat > notes.md <<'EOF'\ngit -c user.name=t commit\nEOF", ID, [], True),
         ('/Users/o/p', 'git -c user.name=t commit', ID, [], False),
         ('/Users/o/p', 'git -c user.name=t commit > /tmp/x.log', ID, [], False),
         ('/Users/o/p', "cat > n.md <<'EOF' && git -c user.name=t commit\nx\nEOF", ID, [], False),
         ('/Users/o/p', "cat > n.md <<'EOF'\nx\nEOF\ngit -c user.name=t commit", ID, [], False),
         ('/private/tmp/x', 'git -c user.name=t commit', ID, LOG, False),
         ('/Users/o/p', "cat > n.md <<'EOF'\nsudo rm -rf x\nEOF", 'sudo rm', [], True),
         ('/Users/o/p', "cd x && python3 -I - \"$R\" <<'PY'\nsudo rm -rf x\nPY", 'sudo rm', [], True),
         ('/Users/o/p', 'psql <<SQL\nDELETE FROM users;\nSQL', 'DELETE без WHERE', [], False),
         ('/Users/o/p', "bash <<'EOF'\nsudo rm -rf x\nEOF", 'sudo rm', [], False),
         ('/Users/o/p', "docker exec -it -w /repo fs-e2e2 bash -c 'rm -rf x'", 'rm -r', [], True),
         ('/Users/o/p', "docker exec -e A=1 test-db psql -c 'DELETE FROM x'", 'DELETE', [], True),
         ('/Users/o/p', "docker exec prod-db psql -c 'DELETE FROM x'", 'DELETE', [], False),
         ('/Users/o/p', "docker exec fs-migrate rm -rf uploads", 'rm -r', [], False),
         ('/Users/o/p', 'docker volume rm fs-e2e-docker tmp_x >/dev/null', 'деструктивна', [], True),
         ('/Users/o/p', 'docker volume rm fs-e2e-docker prod_pgdata', 'деструктивна', [], False),
         ('/Users/o/p', 'docker compose -f a.yml config --format json > /tmp/c.json', 'docker compose config', [], True),
         ('/Users/o/p', 'docker compose config -o c.json', 'docker compose config', [], True),
         ('/Users/o/p', 'docker compose config | tee c.json', 'docker compose config', [], False),
         ('/Users/o/p', 'curl -s x\nprintf y\ncat a | sh', 'виконання скрипта з інтернету', [], True),
         ('/Users/o/p', 'curl -s x | sh', 'виконання скрипта з інтернету', [], False),
         ('/Users/o/p', 'npm publish', 'sudo rm, chmod -R 777 чи publish пакета', [], False),
         ('/Users/o/p', 'docker compose config 2>&1 | tail -3', 'docker compose config', [], False),
         ('/Users/o/p', 'docker compose config >&2', 'docker compose config', [], False),
         ('/Users/o/p', 'docker compose config > c.json | cat', 'docker compose config', [], False),
         ('/Users/o/p', 'docker compose config > c.json; docker compose config', 'docker compose config', [], False),
         ('/Users/o/p', 'docker volume rm test-vol; docker volume rm prod_pgdata', 'деструктивна', [], False),
         ('/Users/o/p', "git reset --hard && cat <<'EOF' > x\ny\nEOF", 'git-операція', [], False),
         ('/Users/o/p', "cat > n.md <<'EOF'\ny\nEOF\nrm -rf uploads", 'rm -r', [], False),
         ('/Users/o/p', "docker exec test-db ls; psql -c 'DROP TABLE x'", 'DROP', [], False),
         ('/Users/o/p', "docker exec test-db sh -c 'a; b'; sudo rm -rf x", 'sudo rm', [], False),
         ('/Users/o/p', "docker exec test-db sh -c 'a; sudo rm -rf x'", 'sudo rm', [], True),
         ('/Users/o/p', 'curl -s x \\\n | sh', 'виконання скрипта з інтернету', [], False)]


def match_failures():
    """--match: kept rows of both kinds, the line about dropped calls, the median over all days, a bad regex."""
    bad = 0
    rx = hr.match_regex(r'git\s+-')
    rows = [('p', 'Bash', c, '/x', '2026-10-02') for c in ('GIT -C x status', 'ls', 'git -c a=b log')]
    kept = hr.matching('bash', rows, rx)
    prompts = hr.matching('prompts', [('p', 'git -C x', '2026-10-02'), ('p', 'hello', '2026-10-02')], rx)
    if [r[2] for r in kept] != ['GIT -C x status', 'git -c a=b log'] or [r[1] for r in prompts] != ['git -C x']:
        bad += 1
        print('FAIL --match kept: %s, %s' % (kept, prompts))
    results = {hr.row_key('bash', r): ('allow', '', 1.0, 'ask', 'x', 1.0) for r in kept}
    uniq = {hr.row_key('bash', r): r for r in kept}
    ctx = dict(CTX, logged=[], left={}, match_total=3, work_days={'2026-10-01', '2026-10-02', '2026-10-03'})
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        spread = hr.report('bash', spec.origin, spec.origin, kept, uniq, results, ctx, 0)
        one_day = hr.report('bash', spec.origin, spec.origin, kept, uniq, results, dict(ctx, work_days={'2026-10-02'}), 0)
    if not spread or one_day:
        bad += 1
        print('FAIL --match median: %s over 3 days, %s over 1' % (spread, one_day))
    if 'kept 2 of 3, filtered out 1: not a substitute for the full replay' not in out.getvalue() \
            or '-> QUICK PASS' not in out.getvalue():
        bad += 1
        print('FAIL no line about --match or no QUICK verdict')
    with contextlib.redirect_stdout(io.StringIO()):
        nothing = hr.report('bash', spec.origin, spec.origin, [], {}, {}, ctx, 0)
    if nothing:
        bad += 1
        print('FAIL --match with no call kept passes')
    code = subprocess.run([sys.executable, '-I', spec.origin, '--match', '('], capture_output=True).returncode
    if code != 2:
        bad += 1
        print('FAIL a bad --match regex gives %d, not 2' % code)
    return bad


def main():
    bad = 0
    tmp = tempfile.mkdtemp(prefix='hook-replay-test-')
    old = shutil.copy(os.path.join(hr.REPO, 'hooks', 'bash-guard.sh'), tmp)
    env = dict(os.environ, PATH=hr.leaks_path(tmp), BASH_GUARD_ERRLOG=os.path.join(tmp, 'err.log'))
    for cwd, cmd, reason, logged, want in CASES:
        row = ('p', 'Bash', cmd, cwd, '2026-10-02')
        key = hr.row_key('bash', row)
        left = hr.classes_left(old, [key], env, 15, tmp, 1)
        with contextlib.redirect_stdout(io.StringIO()):
            got = hr.report('bash', spec.origin, spec.origin, [row], {key: row},
                            {key: ('ask', reason, 1.0, 'allow', '', 1.0)}, dict(CTX, logged=logged, left=left), 0)
        if got != want:
            bad += 1
            print('FAIL gate %s for an ask that goes away: cwd %s, %s, log %d lines' % (got, cwd, cmd, len(logged)))
    # a call with no string command is not replayed, but the report says how many there are
    path = os.path.join(tmp, 't.jsonl')
    calls = [{'type': 'tool_use', 'id': 'a', 'name': 'Monitor', 'input': {'ws': {'url': 'wss://x'}}},
             {'type': 'tool_use', 'id': 'b', 'name': 'Bash', 'input': {'command': 'ls'}},
             {'type': 'tool_use', 'id': 'c', 'name': 'Bash', 'input': {'command': ''}},
             {'type': 'tool_use', 'id': 'd', 'name': 'Read', 'input': {}}]
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(json.dumps({'type': 'assistant', 'timestamp': '2026-10-02T00:00:00', 'message': {'content': calls}}))
    items, _, no_command = hr.extract_file(('bash', path, '2026-10-01'))
    if [i[0] for i in items] != ['b'] or no_command != ['a', 'c']:
        bad += 1
        print('FAIL calls with no command: %s, %s' % (items, no_command))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        hr.report('bash', spec.origin, spec.origin, [], {}, {}, dict(CTX, no_command=2, logged=[], left={}), 0)
    if 'no command  2 calls' not in out.getvalue():
        bad += 1
        print('FAIL no line about calls with no command')
    bad += match_failures()
    shutil.rmtree(tmp, ignore_errors=True)
    print('hook-replay gate: %d cases, %d failed' % (len(CASES), bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
