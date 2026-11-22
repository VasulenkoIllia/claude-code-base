"""sources_check_state: the third part of tests/sources-check-test.py (split off for size).

--doctor on state files of every kind (also one of another tree), a state folder that refuses the file, a file whose
originals are in two repos, the items.tsv of the real tree, and no answer of gh in time (the stand-in gh cannot play that one, so the module is called with a
stand-in for subprocess). Each function takes the test module as `t`: its helpers and the made-up repos.
"""
import datetime
import json
import os
import shutil
import subprocess
import sys
import types


def stamp(days=0, hours=0):
    then = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days, hours=hours)
    return then.strftime('%Y-%m-%dT%H:%M:%SZ')


def check_doctor(t, env, gh_root, state):
    name = '~/.claude/state/sources-check.json'
    hint = 'python3 -I -B scripts/sources-check.py in the base repo (the network and gh with a sign-in)'
    good = {'schema': 1, 'checked_at': stamp(), 'tree': t.REPO, 'sources': 10, 'moved': 6, 'files_changed': 22, 'files_gone': 1}

    def lines_for(doc):
        t.put(state, doc if isinstance(doc, (str, bytes)) else json.dumps(doc))
        rc, out, err = t.run(env, '--doctor')
        return rc, [x for x in out.split('\n') if x], err

    rc, lines, err = lines_for(good)
    t.case('doctor: a check of today is one line and no WARN', rc == 0 and not err and lines == [
        '  sources: checked %s (0 day(s) ago): 10 source(s), 6 moved from the pin, the original of 22 of our file(s) changed, 1 gone' % good['checked_at'][:10]], (rc, lines, err))
    rc, lines, err = lines_for(dict(good, checked_at=stamp(days=35, hours=1)))
    t.case('doctor: 35 days old is no WARN yet', rc == 0 and len(lines) == 1 and '(35 day(s) ago)' in lines[0], lines)
    old = stamp(days=36, hours=1)
    rc, lines, err = lines_for(dict(good, checked_at=old))
    t.case('doctor: 36 days old is the line and a WARN with the command', rc == 0 and len(lines) == 2 and '(36 day(s) ago)' in lines[0]
           and lines[1].startswith('  WARN: sources: checked %s, over 35 days ago: %s' % (old[:10], hint)), lines)
    rc, lines, err = lines_for(dict(good, checked_at=stamp(hours=-2)))
    t.case('doctor: a clock a little behind the file is still today', rc == 0 and len(lines) == 1 and '(0 day(s) ago)' in lines[0], lines)
    rc, lines, err = lines_for(dict(good, checked_at=stamp(days=-3)))
    t.case('doctor: a time in the future is a WARN', rc == 0 and len(lines) == 1 and lines[0].startswith('  WARN: sources: %s names a time in the future' % name), lines)
    rc, lines, err = lines_for(dict(good, tree='/somewhere/else `now` $(x)\n'))
    t.case('doctor: a check of another tree is one WARN and no line; the tree, text of a file, is not printed', rc == 0 and not err and lines == [
        '  WARN: sources: the last full check (%s) was of another tree (%s names it), not of this base: %s' % (good['checked_at'][:10], name, hint)], (lines, err))
    rc, lines, err = lines_for(dict(good, tree=t.REPO + '\0'))
    t.case('doctor: a tree with a zero byte is another tree too, exit 0', rc == 0 and not err and len(lines) == 1 and 'was of another tree' in lines[0], (rc, lines, err))
    forms = (('another schema', dict(good, schema=2)), ('a schema that is true', dict(good, schema=True)), ('a count below zero', dict(good, moved=-1)),
             ('a count that is true', dict(good, sources=True)), ('a count as text', dict(good, files_gone='1')),
             ('no count', {k: v for k, v in good.items() if k != 'files_changed'}), ('no source', dict(good, sources=0, moved=0)),
             ('more sources moved than there are', dict(good, moved=11)), ('a count no check could give', dict(good, files_changed=10 ** 7)),
             ('a day with no time', dict(good, checked_at='2026-11-22')), ('a time that is a number', dict(good, checked_at=20261122)),
             ('a time in other digits', dict(good, checked_at='٢٠٢٦-11-22T10:00:00Z')), ('no tree', {k: v for k, v in good.items() if k != 'tree'}),
             ('a tree that is a number', dict(good, tree=1)), ('an empty tree', dict(good, tree=' ')), ('a list', [good]), ('a word', '"never"'))
    for what, doc in forms:
        rc, lines, err = lines_for(doc)
        t.case('doctor: %s is a WARN, not a date' % what, rc == 0 and lines == [
            '  WARN: sources: %s is of another form: when the sources were last checked is not known (%s writes it anew)' % (name, hint)], lines)
    rc, lines, err = lines_for(dict(good, checked_at='2026-02-30T00:00:00Z'))
    t.case('doctor: a day that does not exist is a WARN', rc == 0 and len(lines) == 1 and lines[0].startswith('  WARN: sources: %s names no real time' % name), lines)
    unread = (('a file that is not JSON', '{"schema": 1,'), ('a file that is not text', b'\xff\xfe\x00'), ('an empty file', ''),
              ('JSON nested too deep to read', '[' * 200000))
    for what, raw in unread:
        rc, lines, err = lines_for(raw)
        t.case('doctor: %s is a WARN' % what, rc == 0 and not err and len(lines) == 1 and lines[0].startswith('  WARN: sources: %s does not read: ' % name), (lines, err[-300:]))
    for what, make in (('a folder', os.makedirs), ('a pipe', os.mkfifo)):
        os.unlink(state)
        make(state)
        rc, out, err = t.run(env, '--doctor')
        t.case('doctor: %s in place of the file is a WARN at once' % what, rc == 0 and out.startswith('  WARN: sources: %s does not read: ' % name), (rc, out, err))
        os.rmdir(state) if os.path.isdir(state) else os.unlink(state)
        t.put(state, '')
    os.unlink(state)
    rc, out, err = t.run(env, '--doctor')
    t.case('doctor: no file is a WARN that names the command', rc == 0 and not err and out == (
        '  WARN: sources: never checked against their sources (no %s): %s\n' % (name, hint)), (rc, out, err))
    t.case('doctor: nothing of this asked GitHub or wrote the file', t.calls(gh_root) == [] and not os.path.exists(state), '')


def check_state_refused(t, env, gh_root, root, tree):
    """A full check whose state file cannot be written says so and exits 1."""
    t.serve_pins(gh_root)
    home = os.path.join(root, 'home-file')
    t.put(os.path.join(home, 'state'), 'a file where the folder goes\n')
    rc, out, err = t.run(dict(env, CLAUDE_HOME=home), '--tree', tree)
    t.case('state: a state folder that cannot be made is said, exit 1', rc == 1 and 'summary: 2 source(s) checked' in out
           and 'state: NOT WRITTEN (FileExistsError): doctor.sh will not know of this check\n' in out and not err, (rc, out, err))
    locked = os.path.join(root, 'home-locked')
    os.makedirs(os.path.join(locked, 'state'))
    os.chmod(os.path.join(locked, 'state'), 0o500)
    rc, out, err = t.run(dict(env, CLAUDE_HOME=locked), '--tree', tree)
    os.chmod(os.path.join(locked, 'state'), 0o700)
    t.case('state: a state folder that takes no file is said, exit 1, nothing is left in it',
           rc == 1 and 'state: NOT WRITTEN (PermissionError)' in out and os.listdir(os.path.join(locked, 'state')) == [], (rc, out, err))
    t.calls(gh_root)


def check_two_repos(t, env, gh_root, root):
    """A file with an original in each of two repos is in the line of both and is one file in the summary and the state."""
    tree, home = os.path.join(root, 'two-repos'), os.path.join(root, 'home-two')
    shutil.copytree(os.path.join(root, 'tree'), tree)
    items = os.path.join(tree, 'packs', 'demo', 'vendor', 'items.tsv')
    t.put(items, t.read(items) + t.row('agents/reviewer.md', 'derived', t.B, t.PIN_B, 'docs/guide.md', 'reviewer, made of two\n', t.GUIDE))
    t.serve(gh_root, t.A, t.HEAD_A, t.MOVED_A)
    t.serve(gh_root, t.B, 'f' * 40, {'docs/guide.md': 'guide, changed by the source\n'})
    rc, out, err = t.run(dict(env, CLAUDE_HOME=home), '--tree', tree)
    lines = out.split('\n')
    t.case('two repos: the file is counted in the line of each of its sources',
           rc == 0 and any(x.endswith('10 file(s): the original of 7 changed, 1 gone') for x in lines)
           and '  moved  orig/lib: pin bbbbbbbb -> head ffffffff (2026-11-20); pack demo; 2 file(s): the original of 2 changed, 0 gone' in lines, (rc, out, err))
    state = os.path.join(home, 'state', 'sources-check.json')
    doc = json.loads(t.read(state)) if os.path.isfile(state) else {}
    t.case('two repos: the summary and the state file count it once',
           'summary: 2 source(s) checked, 2 moved from the pin, the original of 8 of our file(s) changed, 1 gone' in lines
           and (doc.get('files_changed'), doc.get('files_gone')) == (8, 1), (out, doc))
    t.calls(gh_root)


def real_rows(t):
    """(where, repo) of every row of the items.tsv files of the real tree, read here anew."""
    files, packs = [('core', os.path.join(t.REPO, 'vendor', 'items.tsv'))], os.path.join(t.REPO, 'packs')
    for name in sorted(os.listdir(packs)) if os.path.isdir(packs) else []:   # the public version has no packs
        files.append(('pack ' + name, os.path.join(packs, name, 'vendor', 'items.tsv')))
    return [(where, line.split('\t')[2]) for where, path in files if os.path.isfile(path)
            for line in t.read(path).split('\n')[1:] if line.strip()]


def check_real_tree(t, env, gh_root, root):
    """The items.tsv files of the real tree read: every row and every source of them is seen (the stand-in gh knows no
    repo, so each source is asked once and not checked)."""
    home, rows = os.path.join(root, 'home-real'), real_rows(t)
    repos = sorted(set(repo for _, repo in rows))
    rc, out, err = t.run(dict(env, CLAUDE_HOME=home))
    want = 'sources: %d, by %d row(s) of items.tsv (%s)' % (len(repos), len(rows), ', '.join(sorted(set(where for where, _ in rows))))
    t.case('real tree: every row and every source of its items.tsv files is counted', rc == 1 and not err and out.split('\n')[0] == want
           and len(rows) > 0, (rc, out[:300], want, err))
    asked = t.calls(gh_root)
    t.case('real tree: each source is asked once and not checked, the run does not stop, no state file',
           asked == ['api --hostname github.com repos/%s' % repo for repo in repos] and out.count('  NOT CHECKED  ') == len(repos)
           and 'stopped' not in out and 'summary: 0 source(s) checked' in out and not os.path.exists(os.path.join(home, 'state')), (asked, out[-400:]))
    with open(os.path.join(t.REPO, 'scripts', 'vendor_items.py'), encoding='utf-8') as fh:
        rules = fh.read()
    t.case('real tree: the header is the one of scripts/vendor_items.py', "HEADER = '%s'.split()" % t.HEADER.strip().replace('\t', ' ') in rules
           and "HEADER = '%s'.split()" % t.HEADER.strip().replace('\t', ' ') in t.read(t.TOOL), '')


def check_no_answer(t):
    """No answer of gh in GH_TIMEOUT_S: one more try; no answer twice: a failure that stops the run."""
    sys.path.insert(0, os.path.join(t.REPO, 'scripts'))
    import sources_github as github
    tries, answers = [], []

    def run(cmd, **how):
        tries.append((cmd, how.get('timeout')))
        if not answers:
            raise subprocess.TimeoutExpired(cmd, how.get('timeout'))
        return types.SimpleNamespace(returncode=0, stdout=answers.pop(), stderr=b'')

    real = github.subprocess, github.time
    github.subprocess = types.SimpleNamespace(run=run, DEVNULL=subprocess.DEVNULL, TimeoutExpired=subprocess.TimeoutExpired)
    github.time = types.SimpleNamespace(sleep=lambda seconds: tries.append(('pause', seconds)))
    try:
        try:
            got = github.gh_api('repos/acme/skills')
        except github.SourceError as e:
            got = e
        call = (['gh', 'api', '--hostname', 'github.com', 'repos/acme/skills'], github.GH_TIMEOUT_S)
        t.case('no answer: twice in a row is two tries with the timeout and a pause, then a failure that stops the run',
               isinstance(got, github.SourceError) and got.stop and str(got) == 'no answer of gh in %d s (the network?)' % github.GH_TIMEOUT_S
               and tries == [call, ('pause', github.RETRY_PAUSE_S), call], (got, tries))
        del tries[:]
        run_once = github.subprocess.run

        def then_answer(cmd, **how):
            if tries:
                answers.append(b'{}')
            return run_once(cmd, **how)

        github.subprocess.run = then_answer
        got = github.gh_api('repos/acme/skills')
        t.case('no answer: once, then an answer on the second try, is the answer', got == b'{}' and len(tries) == 3, (got, tries))
        del tries[:]

        def repo_then_silence(cmd, **how):
            tries.append(cmd[-1])
            if cmd[-1] != 'repos/acme/skills':
                raise subprocess.TimeoutExpired(cmd, how.get('timeout'))
            return types.SimpleNamespace(returncode=0, stdout=b'{"full_name": "acme/skills", "private": false}', stderr=b'')

        github.subprocess.run = repo_then_silence
        try:
            got = github.head_of('acme/skills', [])
        except github.SourceError as e:
            got = e
        t.case('no answer: after the repo itself answered it is about this repo, the run does not stop',
               isinstance(got, github.SourceError) and not got.stop and 'no answer of gh' in str(got)
               and tries == ['repos/acme/skills', 'repos/acme/skills/commits/HEAD', ('pause', github.RETRY_PAUSE_S), 'repos/acme/skills/commits/HEAD'], (got, tries))
    finally:
        github.subprocess, github.time = real
        sys.path.remove(os.path.join(t.REPO, 'scripts'))
