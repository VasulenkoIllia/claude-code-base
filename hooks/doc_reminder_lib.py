#!/usr/bin/env python3
"""doc_reminder_lib: which paths are docs for doc-reminder, and which docs a commit's areas point to (stdlib, 3.9+).
tests/commit-replay.py loads it from next to the hook it replays, so the replay and the live hook share one rule.

The working log is no docs (owner's decision 03.11.2026, from 60 days of sessions: 161 of 947 commits with code and no
docs had only log edits around them, and in docs outside git a log edit after every commit kept the reminder silent):
STATUS, progress, tracker, decisions, plans, journals and logs, CHANGELOG, WAVE-<n> step plans, open questions, dated
notes (upgrade-2026-10-31.md), and anything in _work/ or an archive. So a commit with code and only such files has no
docs, and a log edit outside git is no docs change. The names come from the docs most edited in those 60 days
(STATUS.md 1076 edits, decisions.md 722, progress.md 553, dev-plan.md 484, tracker.md 449). A word counts only where
those log names have it, so status-codes.md, decision-engine.md and archive-policy.md stay docs; on the 1459 docs
names edited in the 60 days this gives the same 354 as a word anywhere in the name did.
"""
import collections
import itertools
import os
import re

DOC_RE = re.compile(r'(^|/)(README|CHANGELOG)(\.[^/]*)?$|(^|/)docs/|\.mdx?$', re.I)   # not ChangelogModal.tsx
LOG_DIRS = frozenset(('_work', 'archive', 'archives', 'archived'))
LOG_WHOLE = frozenset(('status', 'progress', 'tracker'))          # the name before its first dot: STATUS.before-fix.md
LOG_FIRST = frozenset(('changelog',))                             # CHANGELOG-v2.md
LOG_LAST = frozenset(('plan', 'log', 'decision', 'decisions', 'journal', 'archive', 'archived'))
# dev-plan.md, 14-stage1-plan.md, activity-log.md, 00-decisions.md, SPEC-journal.md, STATUS-archive.md
DATE_RE = re.compile(r'(^|[^0-9])(19|20)[0-9]{2}-[01][0-9]([^0-9]|$)')    # 2026-10, 2026-10-31
SPLIT_RE = re.compile(r'[^a-z0-9]+')
# (area, the commit's files that touch it, words of a doc about it, what to call that doc when none is found);
# 'readme' means the README at the top of the repo only
AREAS = (
    ('env', re.compile(r'(^|/)\.env\.(example|sample|template)$', re.I), ('readme',), 'README'),
    ('commands', re.compile(r'(^|/)(package\.json|Makefile|justfile|pyproject\.toml)$', re.I), ('readme',), 'README'),
    ('deploy', re.compile(r'(^|/)(Dockerfile[^/]*|docker-compose[^/]*|compose\.ya?ml|Caddyfile|ecosystem\.config\.'
                          r'[cm]?js)$|^\.github/workflows/|(^|/)(deploy|nginx)/', re.I),
     ('deploy', 'deployment'), 'the deploy doc'),
    ('schema', re.compile(r'(^|/)schema\.prisma$|(^|/)migrations?/|\.sql$', re.I), ('schema', 'database', 'data-model'),
     'the data model doc'),
    ('API', re.compile(r'(^|/)(routes?|controllers?|router)/|\.(controller|routes?|router)\.[cm]?[jt]sx?$|'
                       r'(^|/)openapi', re.I), ('api', 'openapi'), 'the API doc'),
    ('integrations', re.compile(r'(^|/)(integrations?|webhooks?)/', re.I), ('integration', 'integrations'),
     'the integrations doc'),
)
SCAN_DIRS = ('docs', '_internal')
SCAN_DEPTH = 3       # docs/spec/modules/x.md
MAX_SCAN = 500       # entries read per folder tree for the names of the docs; more are not read


def words_of(name):
    """(base, words): a file name before its first dot, lowercase, and its words. STATUS.before-fix.md and
    decisions.head.md are copies of the log, README.uk.md is the README, progress.json is progress as progress.md is."""
    base = name.lower().split('.', 1)[0]
    return base, [w for w in SPLIT_RE.split(base) if w]


def is_log(path):
    """Whether a docs path (relative to its repo or to the folder above its docs/) is the working log, not a doc a
    reader looks things up in."""
    parts = [p for p in path.replace('\\', '/').lower().split('/') if p]
    if not parts:
        return False
    if any(p in LOG_DIRS for p in parts[:-1]) or DATE_RE.search(parts[-1]):
        return True
    base, words = words_of(parts[-1])
    if not words:
        return False
    if base in LOG_WHOLE or words[0] in LOG_FIRST or words[-1] in LOG_LAST:
        return True
    return any((a == 'wave' and b.isdigit()) or (a, b) == ('open', 'questions') for a, b in zip(words, words[1:]))


def is_doc(path):
    """A commit path that carries docs: README, docs/, *.md and the like, the working log aside."""
    return bool(DOC_RE.search(path)) and not is_log(path)


def doc_names(root):
    """Paths (relative to root) of the docs a reader looks things up in, shortest first: *.md and README* at the top,
    *.md in docs/ and _internal/ (SCAN_DEPTH levels, breadth first, at most MAX_SCAN entries read in each of the two).
    A folder or entry that cannot be read is left out: the reminder then names what to look for (the deploy doc)."""
    try:
        top = sorted(os.listdir(root))
    except OSError:
        return []
    found = [n for n in top if (n.lower().startswith('readme') or n.lower().endswith(('.md', '.mdx')))
             and not is_log(n) and os.path.isfile(os.path.join(root, n))]
    for base in SCAN_DIRS:
        queue, seen = collections.deque([(base, 1)]), 0   # breadth first: docs/deploy.md before docs/a/b/c.md
        while queue and seen < MAX_SCAN:
            rel, depth = queue.popleft()
            try:
                with os.scandir(os.path.join(root, rel)) as it:
                    entries = sorted(itertools.islice(it, MAX_SCAN - seen), key=lambda e: e.name)
            except OSError:   # most repos have no _internal/; an unreadable folder is left out
                continue
            seen += len(entries)
            for e in entries:
                if e.name.startswith('.') or e.name == 'node_modules':
                    continue
                path = rel + '/' + e.name
                try:
                    is_dir = e.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                if is_dir:
                    if depth < SCAN_DEPTH and e.name.lower() not in LOG_DIRS:
                        queue.append((path, depth + 1))
                elif e.name.lower().endswith(('.md', '.mdx')) and not is_log(path):
                    found.append(path)
    return sorted(set(found), key=lambda p: (p.count('/'), len(p), p))


def about(path, keys):
    """Whether a doc's name says it is about one of keys ('readme': only the README at the top; data-model is also
    data_model.md)."""
    _, words = words_of(path.rsplit('/', 1)[-1])
    joined = '-'.join(words)
    return any((k in words or ('-' in k and k in joined)) and not (k == 'readme' and '/' in path) for k in keys)


def area_hint(code, roots):
    """(areas the code files touch, [(doc path or '', what to call it)]) for the reminder, or None when none does."""
    areas = [a for a in AREAS if any(a[1].search(n) for n in code)]
    if not areas:
        return None
    names = [n for r in roots for n in doc_names(r)]
    docs = []
    for _, _, keys, label in areas:
        docs += [(n, label) for n in [n for n in names if about(n, keys)][:2]] or [('', label)]
    return [a[0] for a in areas], list(dict.fromkeys(docs))
