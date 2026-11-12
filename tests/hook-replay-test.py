#!/usr/bin/env -S python3 -I
"""Offline test of the bash gate of tests/hook-replay.py on made-up results: an ask about the identity that goes away in
a /tmp folder, for a /tmp folder the command names or for identity text only in a heredoc body passes, one in another
folder fails (also with /tmp only in a log path); any other ask passes only for a class of lost_kind that explains it:
hooks/bash-guard.sh without bash-guard-exec.py, the old hook here, must not ask once the text of the class is gone; a
line in the bash-guard error log fails; --match keeps its rows, says what it dropped, counts the median of new asks over all
working days, gives a QUICK verdict and fails with no call kept; a new block passes only for a class named by
--block-class that the command explains; the model of the ask rules (tests/replay_rules.py), the class of a prompt that
the hook of PermissionRequest answers, a rule ask that goes away and new asks of a rule in the median. Prints the
failed cases and a last line with the count; exit 0 or 1."""
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


COMPOSE, ENV = 'docker compose config prints the env values', 'printing an env file puts its values'
# (command, old verdict, reason of the new block, classes the run names, the gate passes)
BLOCKS = [('docker compose config', 'ask', COMPOSE, {'compose-config'}, True),
          ('docker compose config', 'ask', COMPOSE, set(), False),
          ('docker compose config', 'ask', COMPOSE, {'env-print'}, False),
          ('docker compose -f a.yml \\\n  --profile x config --format json | python3 check.py', 'ask', COMPOSE, {'compose-config'}, True),
          ('ls -la', 'ask', COMPOSE, {'compose-config'}, False),
          ('cat .env', 'ask', ENV, {'compose-config', 'env-print'}, True),
          ('cd app && grep -n KEY config/stage.env | head', 'allow', ENV, {'env-print'}, True),
          ('grep -rn process.env src/', 'allow', ENV, {'env-print'}, False),
          # the forms the hooks let through explain no block: one of them blocked is a regression of the hook
          ('cat .env.example', 'allow', ENV, {'env-print'}, False),
          ('grep -c KEY .env', 'allow', ENV, {'env-print'}, False),
          ('cat .env | cut -d= -f1', 'ask', ENV, {'env-print'}, False),
          ('grep KEY .env > /dev/null && echo set', 'allow', ENV, {'env-print'}, False),
          ("sed 's/x/y/' .env.example > .env", 'allow', ENV, {'env-print'}, False),
          ('docker compose config --services', 'ask', COMPOSE, {'compose-config'}, False),
          ('docker compose -f a.yml config -o /tmp/c.yml', 'ask', COMPOSE, {'compose-config'}, False),
          ('docker compose exec app npm config get registry', 'ask', COMPOSE, {'compose-config'}, False),
          ('docker --context prod compose config', 'allow', COMPOSE, {'compose-config'}, True),
          ('cat .env.example .env', 'ask', ENV, {'env-print'}, True),
          ('cat "$PWD/.env" | head -3', 'allow', ENV, {'env-print'}, True),
          ('grep -eKEY .env.local; cat .env | cut -d= -f1', 'allow', ENV, {'env-print'}, True),
          ('cat .env 2>/dev/null | head -3', 'ask', ENV, {'env-print'}, True),
          ('grep -rn -i KEY config/stage.env .env.example | head', 'allow', ENV, {'env-print'}, True),
          ("sed -i 's/a/b/' .env", 'allow', ENV, {'env-print'}, False),
          ('docker compose -f a.yml config -o /tmp/c.json > /tmp/log 2>&1; jq . /tmp/c.json', 'ask', COMPOSE, {'compose-config'}, True),
          ('docker compose -f a.yml config 2>&1 | head', 'ask', COMPOSE, {'compose-config'}, True),
          ('docker compose -f a.yml config --format json > /tmp/c.json 2>&1', 'ask', COMPOSE, {'compose-config'}, False),
          ('rm -rf ~/.claude', 'allow', 'rm -r on a system or home directory', {'compose-config', 'env-print'}, False)]
ASK_RULES = ['Bash(git push:*)', 'Bash(git -C * push)', 'Bash(git -C * push *)', 'Bash(gh repo create --public*)',
             'Bash(gh repo create * --public*)', 'mcp__terminal__run_in_terminal', 'Read(x)', 5]
# (tool, command, the ask rule that matches)
RULES = [('Bash', 'git push origin x', 'Bash(git push:*)'), ('Bash', 'cd a && git push', 'Bash(git push:*)'),
         ('Bash', 'X=1 git push origin x 2>&1 | tail -3', 'Bash(git push:*)'), ('Bash', 'git pushd', None),
         ('Bash', 'git commit -m "docs: git push notes"', None), ('Bash', "cat > n.md <<'EOF'\ngit push origin x\nEOF", None),
         ('Bash', 'git -C /x push origin y', 'Bash(git -C * push *)'), ('Bash', 'git -C "/a b" push', 'Bash(git -C * push)'),
         ('Bash', 'git -C /x status', None), ('Bash', 'git -C /x commit -m pushed', None),
         ('Bash', 'gh repo create x --public --source .', 'Bash(gh repo create * --public*)'),
         ('Bash', 'gh repo create --public x', 'Bash(gh repo create --public*)'), ('Bash', 'gh repo create x --private', None),
         ('mcp__terminal__run_in_terminal', 'ls', 'mcp__terminal__run_in_terminal'), ('Monitor', 'git push origin x', None)]
# (command, it is a push to a feature branch and nothing else that asks)
PUSHES = [('git push origin feat/x', True), ('cd a && git push origin -u fix-1 2>&1 | tail -3', True),
          ('git add -A && git commit -m "ssh host; git push origin main" && git push -u origin feat/x', True),
          ("git push 'origin' \"feat/x\" &", True), ('git push -q -u origin feat/x 2>&1 | tail -3; echo push=$?', True),
          ('git push origin main', False), ('git push origin HEAD', False), ('git push origin feat/x; git stash push', False),
          ('git push', False), ('git push origin', False), ('git push origin feat/x && git push origin fix', False),
          ('git push origin feat/x; ssh host uptime', False), ('git push origin feat/x && gh pr merge 5', False),
          ('git push --force origin feat/x', False), ('git push origin feat/x --tags', False),
          ('git push origin feat/x:main', False), ('git push origin +feat/x', False), ('git push upstream feat/x', False),
          ('git -C a push origin feat/x', False), ('git push origin feat/x fix-1', False),
          ('git push origin "$(git branch --show-current)"', False), ('echo "git push origin feat/x"', False)]
OLD_ASK, NEW_ASK = ('Bash(git push:*)', False), ('Bash(git push:*)', True)
# (command, verdicts of bash-guard old and new, (old rule, old answered), (new rule, new answered), the gate passes)
ANSWERS = [('git push origin feat/x', 'allow', 'allow', OLD_ASK, NEW_ASK, True),
           ('git push origin main', 'allow', 'allow', OLD_ASK, NEW_ASK, False),
           ('git push origin feat/x; ssh h', 'allow', 'allow', OLD_ASK, NEW_ASK, False),
           ('git push origin feat/x', 'ask', 'ask', (None, False), (None, True), True),
           ('git stash drop; git push origin feat/x', 'ask', 'ask', (None, False), (None, True), True),
           ('git push origin feat/x', 'allow', 'allow', OLD_ASK, OLD_ASK, True),
           ('git push origin feat/x', 'allow', 'allow', OLD_ASK, (None, False), False),
           ('git push origin main', 'block', 'block', OLD_ASK, (None, False), True),
           ('git -C a push origin x', 'allow', 'allow', (None, False), ('Bash(git -C * push *)', False), True)]


def rules_failures(tmp):
    """A new block passes only for a class the run names and the command explains; the ask rules as the model reads
    them; a prompt that the hook of PermissionRequest answers passes only for a push to a feature branch, an ask of a
    rule that goes away with no answer fails, and new asks of a rule count in the median."""
    bad = 0
    rr = sys.modules['replay_rules']
    row = lambda cmd, day='2026-10-02': ('p', 'Bash', cmd, '/Users/o/p', day)   # noqa: E731
    base = dict(CTX, logged=[], left={})
    for cmd, was, reason, named, want in BLOCKS:
        key = hr.row_key('bash', row(cmd))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            got = hr.report('bash', spec.origin, spec.origin, [row(cmd)], {key: row(cmd)},
                            {key: (was, 'x', 1.0, 'block', reason, 1.0)}, dict(base, block_classes=named), 0)
        if got != want or want != ('named by --block-class: 1' in out.getvalue()):
            bad += 1
            print('FAIL gate %s for a new block with classes %s: %s' % (got, sorted(named), cmd))
    path = os.path.join(tmp, 'settings.json')
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump({'permissions': {'ask': ASK_RULES}}, fh)
    rules = rr.load_rules(path)
    for tool, cmd, want in RULES:
        if rr.rule_ask(rules, tool, cmd) != want:
            bad += 1
            print('FAIL ask rule %s, not %s: %s %s' % (rr.rule_ask(rules, tool, cmd), want, tool, cmd))
    for cmd, want in PUSHES:
        if rr.feature_push(cmd) != want:
            bad += 1
            print('FAIL feature_push is not %s: %s' % (want, cmd))
    sides = ((rules, None, path), (rules, os.path.join(tmp, 'push-allow.sh'), path))
    for cmd, od, nd, old, new, want in ANSWERS:
        key = hr.row_key('bash', row(cmd))
        with contextlib.redirect_stdout(io.StringIO()):
            got = hr.report('bash', spec.origin, spec.origin, [row(cmd)], {key: row(cmd)}, {key: (od, 'x', 1.0, nd, 'x', 1.0)},
                            dict(base, rules={key: (old, new)}, sides=sides), 0)
        if got != want:
            bad += 1
            print('FAIL gate %s with rules %s -> %s: %s' % (got, old, new, cmd))
    # two new asks of a rule on the one working day: the median is over the limit
    rows = [row('git -C a push origin x'), row('git -C b push origin x')]
    keys = [hr.row_key('bash', r) for r in rows]
    scan = {k: ((None, False), ('Bash(git -C * push *)', False)) for k in keys}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        got = hr.report('bash', spec.origin, spec.origin, rows, dict(zip(keys, rows)),
                        {k: ('allow', '', 1.0, 'allow', '', 1.0) for k in keys}, dict(base, rules=scan, sides=sides), 0)
    if got or 'new asks  rule Bash(git -C * push *): 2' not in out.getvalue() or 'new asks 2 (median 2.0' not in out.getvalue():
        bad += 1
        print('FAIL two new asks of a rule in one day pass or are not listed')
    # the hook of PermissionRequest counts for a side only when the settings of that side name it
    guard = os.path.join(tmp, 'bash-guard.sh')
    open(os.path.join(tmp, 'push-allow.sh'), 'w').close()
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump({'permissions': {'ask': ASK_RULES}}, fh)
    alone = rr.side(path, guard)[1]
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump({'permissions': {'ask': ASK_RULES}, 'hooks': {'PermissionRequest': [
            {'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': '/x/hooks/push-allow.sh'}]}]}}, fh)
    if alone is not None or rr.side(path, guard)[1] != os.path.join(tmp, 'push-allow.sh'):
        bad += 1
        print('FAIL the hook of PermissionRequest counts with no line in the settings, or does not count with one')
    for text in ('not json', '[]', '{"permissions": {"ask": []}}', '{"permissions": {"ask": ["Read(x)"]}}'):
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(text)
        try:
            rr.load_rules(path)
        except ValueError:
            continue
        bad += 1
        print('FAIL settings that are %s give rules' % text)
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
    bad += rules_failures(tmp)
    shutil.rmtree(tmp, ignore_errors=True)
    print('hook-replay gate: %d cases, %d failed' % (len(CASES) + len(BLOCKS) + len(RULES) + len(PUSHES) + len(ANSWERS), bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
