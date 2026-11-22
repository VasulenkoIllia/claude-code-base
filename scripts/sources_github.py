"""sources_github.py: what GitHub says of a source repo, for scripts/sources-check.py (split off for size).

Three calls of `gh api` per repo, read-only: the repo, the head commit of its default branch, the tree of that commit;
one more per pin that is not the head: whether the repo still serves that commit (one that does not had its history
rewritten, or is another repo under the old name; the reverse does not hold: GitHub may serve a commit only a fork
has). An answer is taken only in the usual form: ids as 40 hex, a name as
owner/name, a time as ISO; anything else leaves the source not checked. One more try after no answer in GH_TIMEOUT_S or
an HTTP 5xx, none after any other failure. Only a failure that is not about one repo (no gh, no sign-in, a rate limit,
a failure of gh with no HTTP code, no answer to the first call about a repo) is marked to stop the run.
"""
import collections
import json
import re
import subprocess
import time

HEX40 = re.compile(r'[0-9a-f]{40}\Z')
REPO = re.compile(r'[A-Za-z0-9._-]+/[A-Za-z0-9._-]+\Z')
ISO_TIME = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z')
HTTP_CODE = re.compile(r'\bHTTP ([0-9]{3})\b')   # gh says "(HTTP 404)" after a message of the API and a bare "HTTP 502" without one
UNSAFE = re.compile(r'[^A-Za-z0-9._/@+:()=, -]')
UNSAFE_NAME = re.compile(r'[^A-Za-z0-9._/@+-]')   # a name a source chose: no space and no punctuation of a sentence
SHOWN_MAX = 200
NAME_MAX = 80
GH_TIMEOUT_S = 60
RETRY_PAUSE_S = 2

Head = collections.namedtuple('Head', 'flags sha day blobs')   # blobs: path -> blob id of every file of the head tree


class SourceError(Exception):
    """A source that did not answer, or not in the usual form: it is not checked.

    stop: the failure is not about this one repo, the run ends; again: one more try makes sense; http: the code, if any.
    """

    def __init__(self, reason, stop=False, again=False, http=0):
        super().__init__(reason)
        self.stop, self.again, self.http = stop, again, http


class NoAnswer(SourceError):
    """gh did not answer in GH_TIMEOUT_S."""


def shown(text):
    """Text that is not ours (a message of gh, a path of our tree) made safe to print: a short list of characters, cut."""
    return UNSAFE.sub('?', str(text))[:SHOWN_MAX]


def shown_name(text):
    """A name a source chose (a path of its tree, the new name of its repo): no room for a sentence, shorter still."""
    return UNSAFE_NAME.sub('?', str(text))[:NAME_MAX]


def failure(code, err):
    """Why `gh api` failed, by its exit code and stderr, as a SourceError."""
    found = HTTP_CODE.search(err)
    http = int(found.group(1)) if found else 0
    if http == 404:
        return SourceError('not found (HTTP 404): the repo is deleted, renamed away or no longer public', http=http)
    if http == 401 or 'gh auth login' in err:
        return SourceError('gh has no sign-in (gh auth login)', stop=True, http=http)
    if http == 429 or (http == 403 and 'rate limit' in err.lower()):
        return SourceError('refused (HTTP %d): a rate limit; try later' % http, stop=True, http=http)
    if http >= 500:   # a big tree can time out at GitHub for one repo only: the next source is still asked
        return SourceError('GitHub failed (HTTP %d); try later' % http, again=True, http=http)
    if http:
        return SourceError('refused (HTTP %d)' % http, http=http)
    last = [line for line in err.split('\n') if line.strip()][-1:] or ['no message']
    return SourceError('gh api failed (exit %d): %s' % (code, shown(last[0])), stop=True)


def gh_once(path):
    try:
        res = subprocess.run(['gh', 'api', '--hostname', 'github.com', path], capture_output=True,
                             stdin=subprocess.DEVNULL, timeout=GH_TIMEOUT_S)
    except OSError as e:
        raise SourceError('gh is not installed or does not start', stop=True) from e
    except subprocess.TimeoutExpired as e:
        raise NoAnswer('no answer of gh in %d s (the network?)' % GH_TIMEOUT_S, stop=True, again=True) from e
    if res.returncode != 0:
        raise failure(res.returncode, res.stderr.decode('utf-8', 'replace'))
    return res.stdout


def gh_api(path):
    """The bytes `gh api <path>` prints."""
    try:
        return gh_once(path)
    except SourceError as e:
        if not e.again:
            raise
    time.sleep(RETRY_PAUSE_S)
    return gh_once(path)


def gh_json(path):
    try:
        doc = json.loads(gh_api(path).decode('utf-8'))
    except ValueError as e:   # UnicodeDecodeError is one
        raise SourceError('an answer of GitHub that is not JSON') from e
    if not isinstance(doc, dict):
        raise SourceError('an answer of GitHub that is not an object')
    return doc


def inner(doc, key):
    """A nested object of an answer, or an empty one."""
    return doc[key] if isinstance(doc.get(key), dict) else {}


def entry_ok(entry):
    return (isinstance(entry, dict) and isinstance(entry.get('path'), str) and entry['path'] != ''
            and entry.get('type') in ('blob', 'tree', 'commit') and isinstance(entry.get('sha'), str)
            and HEX40.match(entry['sha']) is not None)


def repo_flags(repo, info):
    """What the answer about the repo says a reader must know: renamed, archived, a fork, not public."""
    name, flags = info.get('full_name'), []
    if not isinstance(name, str) or not REPO.match(name):
        raise SourceError('the answer about the repo has no name of the usual form')
    if name.lower() != repo.lower():
        flags.append('renamed (the new name, data): %s' % shown_name(name))
    if info.get('archived') is True:
        flags.append('archived')
    if info.get('fork') is True:
        flags.append('a fork')
    if info.get('private') is not False:
        flags.append('not public now')
    return flags


def pin_known(repo, pin):
    """Whether GitHub still serves the commit of a pin under this repo."""
    try:
        commit = gh_json('repos/%s/git/commits/%s' % (repo, pin))
    except SourceError as e:
        if e.http == 404:
            return False
        raise
    if commit.get('sha') != pin:
        raise SourceError('the answer about the pin %s is of another form' % pin[:8])
    return True


def head_of(repo, pins):
    """The head of the default branch of a repo: the flags of the repo and of our pins, the commit, its day, path -> blob id."""
    flags = repo_flags(repo, gh_json('repos/%s' % repo))
    try:
        return head_tree(repo, pins, flags)
    except NoAnswer as e:   # the repo itself just answered: no answer now is about this repo (a big tree), the run goes on
        raise SourceError(str(e)) from e


def head_tree(repo, pins, flags):
    commit = gh_json('repos/%s/commits/HEAD' % repo)
    sha, tree_sha = commit.get('sha'), inner(inner(commit, 'commit'), 'tree').get('sha')
    when = inner(inner(commit, 'commit'), 'committer').get('date')
    if not all(isinstance(x, str) and HEX40.match(x) for x in (sha, tree_sha)):
        raise SourceError('the head commit has no ids of the usual form')
    for pin in pins:
        if pin != sha and not pin_known(repo, pin):
            flags.append('pin %s is not in this repo now (a rewritten history, or another repo under this name)' % pin[:8])
    tree = gh_json('repos/%s/git/trees/%s?recursive=1' % (repo, tree_sha))
    if tree.get('truncated') is not False:
        raise SourceError('GitHub cut the tree short (over 100 000 entries or 7 MB): such a source is not supported')
    entries = tree.get('tree')
    if not isinstance(entries, list) or not all(entry_ok(e) for e in entries):
        raise SourceError('the tree has an entry of another form')
    blobs = {e['path']: e['sha'] for e in entries if e['type'] == 'blob'}
    if not blobs:
        raise SourceError('the head tree has no file')
    day = when[:10] if isinstance(when, str) and ISO_TIME.match(when) else 'no date'
    return Head(flags, sha, day, blobs)
