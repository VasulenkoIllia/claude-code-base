#!/usr/bin/env python3
"""dup-guard: PostToolUse hook for Edit|Write|MultiEdit on JS/TS files, started by dup-guard.sh (stdlib, 3.9+;
the text part is in dup_guard_lib.py next to it).
Takes the NEW top-level function/class definitions from the text the call adds and looks for top-level
definitions with the same or a normalized name (isoDay ~ toIsoDay ~ iso_day) elsewhere in the repo: git grep over
tracked + untracked-not-ignored files; outside git, the top-level folders of the nearest package.json/tsconfig.json
root without node_modules/dist/build/.next. Each hit gets a body similarity (token SequenceMatcher on the first
40 lines, literals masked) that drops "same name, other meaning". Prints hookSpecificOutput.additionalContext
("dup-guard: ...", facts only, JSON <= 1200 B). Never blocks; any error, timeout or odd input -> silent exit 0.
An internal error (not odd input) also appends one line (time, error class) to ~/.claude/logs/dup-guard.err,
which scripts/doctor.sh shows, so a dead hook does not look like "no duplicates".
Env (tuning, replay and tests only): DUP_GUARD_MIN_SIM=0.55 (same name), DUP_GUARD_MIN_SIM_SIM=0.7 (similar
name), DUP_GUARD_TREE=<commit> (search that commit's tree: tests/edit-replay.py), DUP_GUARD_ALLOW_TMP=1 (do not
skip /tmp and /var/folders: hooks/dup-tests.sh), DUP_GUARD_ERRLOG=<file> (error log instead of the live one:
tests and replay), DUP_GUARD_GIT=<path> (a git stub: tests), DUP_GUARD_DEBUG=1 (reason for silence on stderr).
"""
import difflib
import json
import os
import re
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True   # no __pycache__ in the managed hooks folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I drops the script folder from sys.path
try:   # a missing or broken dup_guard_lib.py: main() raises it again, so it reaches the error log
    from dup_guard_lib import (DEF_RE, FUNC_RHS, NEUTRAL_PREFIX, body_lines, definitions,  # noqa: E402
                               exported_elsewhere, name_pattern, part, render, signature, token_diff, tokens)
    LIB_ERROR = None
except Exception as e:  # noqa: BLE001
    LIB_ERROR = e

EXTS = ('.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs')
PATHSPEC = ['*' + x for x in EXTS] + [':!*.d.ts', ':!*.min.js'] + [':!**/%s/**' % d for d in (
    'node_modules', 'dist', 'build', '.next', 'coverage', 'out', 'vendor', 'generated')]
SKIP_PATH = re.compile(
    r'(^|/)(node_modules|dist|build|out|coverage|\.next|\.nuxt|\.output|\.turbo|\.vercel|vendor|generated|'
    r'__generated__|__tests__|__mocks__|tests?|e2e|fixtures?|migrations|seeds?)(/|$)'
    r'|\.(test|spec|e2e|stories|d)\.[cm]?[jt]sx?$|\.min\.js$|[.-]gen(erated)?\.[cm]?[jt]sx?$', re.I)
SHARED_PATH = re.compile(r'(^|/)(lib|libs|shared|common|utils?|helpers?|core)(/|$)', re.I)
SHARED_TOP = {'shared', 'common', 'lib', 'libs', 'packages', 'core', 'utils', 'types'}
TMP_PREFIX = ('/tmp/', '/private/tmp/', '/private/var/folders/', '/var/folders/')
PROJECT_MARKERS = ('package.json', 'tsconfig.json', 'jsconfig.json', 'deno.json')
GENERIC = set(
    'handler main run init render default index props types setup start stop test helper helpers util utils config '
    'app page layout loading error notfound template middleware loader action meta links get post put patch delete '
    'head options generatemetadata generatestaticparams getserversideprops getstaticprops getstaticpaths revalidate '
    'schema router routes server client prisma logger noop wrapper provider context store reducer fetcher callback '
    'home root rootlayout bootstrap register plugin module service controller'.split())
HANDLER = re.compile(r'^(handle|on)[A-Z]')
REEXPORT = re.compile(r'\b(lazy|import|require|dynamic)\s*\(')
MIN_LEN = 4
MAX_TEXT = 400_000
MAX_NAMES = 60
MAX_SCORED = 8       # hits per name that get a similarity score (file reads)
BUDGET_S = 3.0       # then stop silently (settings.json timeout is 5 s)
GIT = os.environ.get('DUP_GUARD_GIT') or 'git'
ERR_LOG_MAX = 64_000  # bytes; then the log moves to dup-guard.err.1 and starts again
T0 = time.monotonic()


class HookError(Exception):
    """Our own failures; only their messages reach the error log (they never hold code or paths)."""


def dbg(msg):
    if os.environ.get('DUP_GUARD_DEBUG'):
        print('dup-guard: ' + msg, file=sys.stderr)


def log_error(e):
    """One line per internal error: time, class and only our own messages (never code or paths)."""
    path = os.environ.get('DUP_GUARD_ERRLOG') or os.path.join(os.path.expanduser('~'), '.claude', 'logs',
                                                              'dup-guard.err')
    own = str(e)[:80] if isinstance(e, HookError) else ''
    try:
        if os.path.isfile(path) and os.path.getsize(path) > ERR_LOG_MAX:
            os.replace(path, path + '.1')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write('%s %s %s\n' % (time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), type(e).__name__, own))
    except OSError:
        pass


def check_budget():
    if time.monotonic() - T0 > BUDGET_S:
        raise HookError('budget %.0f s' % BUDGET_S)


def fenv(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def git(args, cwd, timeout):
    """(rc, stdout). rc 0, 1 (no match) and 128 (not a repo, no such path) are answers; any other rc, or rc 1 with
    stderr (a broken git, e.g. xcrun after a macOS update), is a HookError, so it reaches the error log."""
    p = subprocess.run([GIT, '-c', 'core.quotePath=false'] + args, cwd=cwd, capture_output=True,
                       timeout=timeout, env={'PATH': '/usr/bin:/bin', 'GIT_OPTIONAL_LOCKS': '0', 'LC_ALL': 'C',
                                             'HOME': os.environ.get('HOME', '/')})
    if p.returncode not in (0, 1, 128) or (p.returncode == 1 and p.stderr.strip()):
        raise HookError('git %s rc=%d' % (args[0], p.returncode))
    return p.returncode, p.stdout.decode('utf-8', 'replace')


def repo_root(fp):
    """(root, is_git). Outside git: the nearest ancestor with package.json/tsconfig.json (never HOME or /)."""
    d = os.path.dirname(fp)
    while d and not os.path.isdir(d):
        d = os.path.dirname(d)
    if not d or d == '/':
        return None, False
    rc, out = git(['rev-parse', '--show-toplevel'], d, 1.0)
    if rc == 0 and out.strip():
        return out.strip(), True
    home = os.path.expanduser('~')
    while d and d not in ('/', home):
        if any(os.path.isfile(os.path.join(d, m)) for m in PROJECT_MARKERS):
            return d, False
        d = os.path.dirname(d)
    return None, False


def original_text(resp, root, rel, tree, is_git):
    """Text of the file before a Write. originalFile is null for new files and for too large ones: then HEAD."""
    if isinstance(resp, dict):
        if isinstance(resp.get('originalFile'), str):
            return resp['originalFile']
        if resp.get('type') == 'create':
            return ''
    rc, out = git(['show', '%s:%s' % (tree or 'HEAD', rel)], root, 1.0) if is_git else (1, '')
    return out if rc == 0 else ''


def added_pairs(tool, ti, original):
    """(added text, text it replaced) per change; a field that is not a string counts as empty."""
    def text(d, key):
        return d.get(key) if isinstance(d.get(key), str) else ''
    if tool == 'Write':
        return [(text(ti, 'content'), original or '')]
    if tool == 'Edit':
        return [(text(ti, 'new_string'), text(ti, 'old_string'))]
    edits = ti.get('edits') if isinstance(ti.get('edits'), list) else []
    return [(text(e, 'new_string'), text(e, 'old_string')) for e in edits if isinstance(e, dict)]


def search(root, rel, names, tree, is_git):
    """One git grep for top-level definitions named like names: {name: [dict(path, line, sig, how, ...)]}."""
    keys = {n: name_pattern(n) for n in names}   # name -> (normalized key or None, grep alternative)
    pat = (r'^(?:export\s+(?:default\s+)?)?(?:declare\s+)?(?:(?:async\s+)?function\s*\*?\s*|'
           r'(?:abstract\s+)?class\s+|(?:const|let|var)\s+)(?:(?:to|get|as|format|fmt)_?)?(?:'
           + '|'.join(sorted({alt for _, alt in keys.values()})) + r')\b')
    args = ['grep', '-n', '-I', '-i', '-P', '--no-color', '-e', pat]
    spec = PATHSPEC
    if not is_git:
        # --no-index walks node_modules despite a :! pathspec, so name the top-level entries instead
        tops = [e for e in sorted(os.listdir(root))[:200] if not e.startswith('.') and not SKIP_PATH.search(e + '/')]
        dirs = [e + '/' for e in tops if os.path.isdir(os.path.join(root, e))]
        files = [e for e in tops if e.endswith(EXTS) and os.path.isfile(os.path.join(root, e))]
        if not dirs and not files:
            return {}
        args = ['grep', '--no-index', '--exclude-standard'] + args[1:] + ['--']
        spec = [d + '*' + x for d in dirs for x in EXTS] + files   # '*' crosses '/' in a plain pathspec
    else:
        args += [tree, '--'] if tree else ['--untracked', '--']
    rc, out = git(args + spec, root, 2.0)
    if rc not in (0, 1):
        raise HookError('git grep rc=%d' % rc)
    res = {}
    for line in out.splitlines():
        if tree and line.startswith(tree + ':'):
            line = line[len(tree) + 1:]
        try:
            path, ln, text = line.split(':', 2)
        except ValueError:
            continue
        m = DEF_RE.match(text)
        if path == rel or SKIP_PATH.search(path) or REEXPORT.search(text) or not m or m.group('ind'):
            continue
        hname = m.group('fn') or m.group('cls') or m.group('var')
        if m.group('var') and not (FUNC_RHS.match(m.group('rhs')) or
                                   m.group('rhs').lstrip().startswith(('(', 'async', '<'))):
            continue   # a value, not a helper (const x = await ..., const path =\n ...)
        hkey = NEUTRAL_PREFIX.sub('', hname).replace('_', '').lower()
        for n in names:
            how = 'same' if hname == n else 'similar' if keys[n][0] and hkey == keys[n][0] else ''
            if how:
                res.setdefault(n, []).append({'path': path, 'line': int(ln), 'sig': signature(text), 'how': how,
                                              'hname': hname, 'exported': bool(m.group('exp'))})
    return res


def read_lines(root, path, tree, cache):
    if path not in cache:
        check_budget()
        if tree:
            rc, out = git(['show', '%s:%s' % (tree, path)], root, 1.0)
            cache[path] = out.splitlines() if rc == 0 else []
        else:
            try:
                with open(os.path.join(root, path), 'r', encoding='utf-8', errors='replace') as fh:
                    cache[path] = fh.read(MAX_TEXT).splitlines()
            except OSError:
                cache[path] = []
    return cache[path]


def main():
    if LIB_ERROR:
        raise LIB_ERROR
    raw = sys.stdin.buffer.read(2 * MAX_TEXT + 1).decode('utf-8', 'replace')
    if len(raw) > 2 * MAX_TEXT:
        return dbg('input too big')
    try:
        d = json.loads(raw)
    except ValueError:
        return dbg('not json')
    if not isinstance(d, dict):
        return dbg('not an object')
    tool, ti = d.get('tool_name'), d.get('tool_input') or {}
    if tool not in ('Edit', 'Write', 'MultiEdit') or not isinstance(ti, dict) or not isinstance(
            ti.get('file_path'), str):
        return dbg('other tool or input')
    fp = ti['file_path'].replace('\\', '/')
    if (not fp.endswith(EXTS) or '/.claude/' in fp
            or (fp.startswith(TMP_PREFIX) and not os.environ.get('DUP_GUARD_ALLOW_TMP'))):
        return dbg('path skipped')
    root, is_git = repo_root(fp)
    if not root:
        return dbg('no project root')
    rel = os.path.relpath(os.path.realpath(fp), os.path.realpath(root))
    if rel.startswith('..') or SKIP_PATH.search(rel):
        return dbg('test/generated/outside')
    tree = os.environ.get('DUP_GUARD_TREE') or ''
    tree = tree if is_git and re.match(r'^[0-9a-f]{7,40}$', tree) else ''
    resp = d.get('tool_response')
    original = original_text(resp, root, rel, tree, is_git) if tool == 'Write' else ''
    created = tool == 'Write' and isinstance(resp, dict) and resp.get('type') == 'create'
    new = {}      # name -> (exported, body tokens)
    for added, old in added_pairs(tool, ti, original):
        if len(added) > MAX_TEXT:
            return dbg('text too big')
        before, lines = definitions(old), added.splitlines()
        for n, (off, exp) in definitions(added).items():
            if n in before or n in new or len(n) < MIN_LEN or n.lower() in GENERIC or HANDLER.match(n):
                continue
            new[n] = (exp, tokens(body_lines(lines, added.count('\n', 0, off)), n))
    if not new:
        return dbg('no new definitions')
    names = list(new)[:MAX_NAMES]
    hits = search(root, rel, names, tree, is_git)
    min_same, min_similar = fenv('DUP_GUARD_MIN_SIM', 0.55), fenv('DUP_GUARD_MIN_SIM_SIM', 0.7)
    mine = part(rel)
    cache, fired, queues = {}, [], []
    for n in names:
        hs = sorted(hits.get(n) or [], key=lambda h: (h['how'] != 'same', not h['exported'], h['path'].count('/'),
                                                      h['path']))[:MAX_SCORED]
        for h in hs:
            check_budget()
            lines = read_lines(root, h['path'], tree, cache)
            htoks = tokens(body_lines(lines, h['line'] - 1), h['hname'])
            if not h['exported']:
                h['exported'] = exported_elsewhere(lines, h['hname']) if lines else None
            sm = difflib.SequenceMatcher(None, new[n][1], htoks, autojunk=False)
            h['sim'] = round(sm.ratio(), 3) if new[n][1] and htoks else 0.0
            h['diff'] = token_diff(htoks, new[n][1]) if h['sim'] < 0.98 else []
            theirs = part(h['path'])   # '' = same part or a shared one
            h['cross'] = '' if theirs in (mine, '.') or theirs.split('/')[0] in SHARED_TOP else theirs
        keep = [h for h in hs if h['sim'] >= (min_same if h['how'] == 'same' else min_similar)]
        if keep:
            # same part first, then exported, then similarity
            keep.sort(key=lambda h: (bool(h['cross']), not h['exported'], -h['sim'], h['path'].count('/')))
            fired.append(n)
            queues.append((n, keep))
    if not fired:
        return dbg('no similar bodies')
    extraction = created and bool(SHARED_PATH.search(rel)) and all(new[n][0] for n in fired)
    print(render(rel, fired, queues, extraction))


if __name__ == '__main__':
    # hard stop at 4 s: BUDGET_S is checked between steps only; SIGALRM's default action ends the process even
    # inside a C regex; the shim then logs "ShimExit 142" and still exits 0
    signal.alarm(4)
    try:
        main()
    except BaseException as e:  # fail open, but leave a trace for doctor.sh
        dbg('error %s' % type(e).__name__)
        log_error(e)
    sys.exit(0)
