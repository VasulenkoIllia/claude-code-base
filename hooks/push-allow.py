#!/usr/bin/env python3
"""push-allow: is this Bash command a push of a feature branch and nothing else that needs the owner (stdlib, 3.9+;
the shell reader is in bash_guard_shell.py and bash_guard_words.py). push-allow.sh, the PermissionRequest hook, starts
this script when Claude Code is about to show a permission prompt for a Bash call with "push" in it, and answers the
prompt with "allow" only when the script prints "allow" (owner's decision 11.11.2026: no prompt for git push origin
<feature branch>, every other push asks as before).

The answer of such a hook covers the whole call: another ask rule in the same command and an ask of bash-guard would
go with it, and the input does not say why the prompt comes. So "allow" needs all of this, and anything else prints
"pass" (the prompt stays):
- the input is a PermissionRequest for Bash of a main session in the mode default, acceptEdits or auto;
- the reader follows the whole command (any doubt of bash_guard_shell passes), and it has no function, no
  NAME=value word, no heredoc but the quoted text of a cat that a delimiter line ends, no redirection but 2>&1, >&2
  and to /dev/null; a variable only as $name or ${name} (zsh runs the text of ${(e)x} and globs that of $~x, and
  arithmetic runs a $(...) in the value of a variable), a for list of plain words; a cd only as its first command,
  cd /folder, ./folder or ../folder (then it ran before the push; where the folder is not there git has no answer);
- exactly one command is git push, at the top level, as plain words: git, push, flags of PUSH_FLAGS, origin, one
  branch name; no option of git before push (-C, -c);
- that branch is no protected name (PROTECTED) and not the default branch of origin, which the repo must know
  (refs/remotes/origin/HEAD; git remote set-head origin --auto sets it); the folder where the push runs (the cwd,
  or the folder of that cd) is the work tree of a repo, not a bare repo or a .git folder, the name is a local
  branch there and no tag or other ref, and the repo has no remote.origin.push, no pushurl, no mirror and no
  push.followTags;
- every other command is on the short list below with the words it may take: echo, printf, true, cd; after a pipe
  tail, head, grep, wc, cut, tr, cat with options and a pattern but no file to read (the answer would also cover
  the prompt for a file outside the project); git status, log, diff, show, rev-parse, merge-base, rev-list (no
  --output, no --no-index, no path outside the repo: git diff of two such files prints them, and a $(...) of a
  message would send that to origin), branch (listing), fetch, add, commit -m; gh pr create, view, checks (no --repo, a jq
  filter only as a path: .url, .[0].state; a longer one may print the environment). A message or a title is one word
  for the shell: no glob or brace outside quotes, a $ only inside double quotes (zsh splits an unquoted $(...), and
  -m {x,--no-verify} is two words).
push-allow.sh then runs bash-guard on the same input: only when it has nothing to say does the answer go out.

Exit 0 with "allow" or "pass"; 3 with one line for the log of the wrapper: "ShapeDrift <field>" for an input of
another shape, "Error <name>" for an exception (GitSilent: git gave no answer in GIT_S or did not start); any other
code is a script that did not get that far. The prompt stays in each case. PUSH_ALLOW_DEBUG=1 (tests only): the
reason of a pass on stderr.
"""
import json
import os
import re
import signal
import subprocess
import sys

sys.dont_write_bytecode = True   # no __pycache__ in the managed hooks folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I drops the script folder from sys.path
from bash_guard_shell import Doubt, ShellReader  # noqa: E402
from bash_guard_words import split_assigns  # noqa: E402

MODES = ('default', 'acceptEdits', 'auto')
# compared in lower case (macOS folds the case of a ref); the branches a deploy may hang on ask as main does
PROTECTED = ('main', 'master', 'prod', 'production', 'head', 'develop', 'development', 'dev', 'staging', 'stage',
             'release', 'deploy', 'live')
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._/-]*')   # a branch or a remote as plain characters: no refspec, no option
PUSH_FLAGS = {'-u', '--set-upstream', '-q', '--quiet', '-v', '--verbose', '--progress', '--no-progress'}
PRINTS = {'echo', 'printf', 'true', ':'}
GREP_VALUE = ('-e', '-m', '-A', '-B', '-C')   # the next word is their value
GREP_FLAG = re.compile(r'-[viEFPnocqwxs]+|--line-buffered|--color=\w+')
CUT_VALUE = ('-d', '-f', '-c', '-b')
GIT_READ_NO = ('--output', '--ext-diff', '--no-index')   # write a file, run a program, read a file outside the repo
OUTSIDE = re.compile(r'[/~]|(.*/)?\.\.(/|$)')              # a path that starts outside the folder or climbs out of it
VAR = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
DELIM = re.compile(r'\\?[\w.-]+|\'[\w.-]+\'|"[\w.-]+"')    # as in bash-guard-exec.py: the shell reads no other in another way
FOR_WORD = re.compile(r'[\w./:@%+,=-]*')                   # a word of a for list: a name, a number, a path
PIPE_FILTERS = {'tail', 'head', 'grep', 'wc', 'cut', 'tr', 'cat'}   # read a pipe, write no file (sort -o, sed -i do)
GIT_READ = {'status', 'log', 'diff', 'show', 'rev-parse', 'merge-base', 'rev-list'}
BRANCH_FLAGS = {'--show-current', '-a', '--all', '-r', '--remotes', '-v', '-vv', '--list'}
FETCH_FLAGS = {'-q', '--quiet', '-p', '--prune', '--tags', '--no-tags', '--all'}
ADD_FLAGS = {'-A', '--all', '-u', '--update', '--'}
COMMIT_FLAGS = {'-a', '--all', '-q', '--quiet', '--allow-empty'}
COMMIT_MESSAGE = re.compile(r'-[aq]*m|--message')   # the next word is the message
# gh pr <verb>: (flags alone, flags whose next word is free text, flags whose next word is a plain value, positionals)
GH_PR = {'create': ({'-d', '--draft', '-f', '--fill', '--fill-first', '--fill-verbose'}, {'-t', '--title', '-b', '--body'},
                    {'-B', '--base', '-H', '--head', '-a', '--assignee', '-l', '--label', '-r', '--reviewer'}, 0),
         'view': ({'--comments'}, set(), {'--json'}, 1),
         'checks': ({'--watch', '--fail-fast', '--required'}, set(), {'--json', '-i', '--interval'}, 1)}
GH_JQ = ('-q', '--jq')                       # the next word is a jq filter
JQ_PATH = re.compile(r'\.[\w.\[\]]*')        # a path into the answer and nothing more: env and $ENV print the environment
MAX_INPUT = 100_000   # characters; a longer command passes
ALARM_S = 4           # then the alarm kills the script: the wrapper logs it and the prompt stays
GIT_S = 2             # each question to git about the repo


def known(words):
    """Every word is text as written: no variable, no $(...) (their value is None), no glob."""
    return all(w.value is not None and not w.glob for w in words)


def values(words):
    if not known(words):
        raise Doubt('a word that is not plain text')
    return [w.value for w in words]


def reads_pipe_only(name, words):
    """The words of a filter after a pipe name no file: it reads the pipe and nothing else."""
    if name == 'cat':
        return not words
    if name in ('head', 'tail'):   # a count of lines or bytes; -f waits
        return all(re.fullmatch(r'[-+](\d+|[nc]\d*)|\d+', v) for v in words)
    if name == 'wc':
        return all(re.fullmatch(r'-[clmw]+', v) for v in words)
    if name == 'cut':
        return all(v.startswith('-') or k and words[k - 1] in CUT_VALUE for k, v in enumerate(words))
    if name == 'tr':
        return True   # its words are sets of characters
    patterns, with_e, k = 0, False, 0   # grep: options, then one pattern unless -e gave it
    while k < len(words):
        if words[k] in GREP_VALUE:
            with_e, k = with_e or words[k] == '-e', k + 1
            if k == len(words):
                return False
        elif not words[k].startswith('-'):
            patterns += 1
        elif not GREP_FLAG.fullmatch(words[k]):
            return False
        k += 1
    return patterns == (0 if with_e else 1)


class Pushes(ShellReader):
    def __init__(self, s, cwd, home, cdpath):
        super().__init__(s, cwd, home, cdpath)
        self.pushes = []   # (folder, branch)
        self.first = True  # no command was read yet

    def settle(self):
        pass

    def listed(self, words):
        # the variable of the loop holds these words: arithmetic would run a $(...) in such a value
        if any(w.value is None or not FOR_WORD.fullmatch(w.value) for w in words):
            raise Doubt('a for list with more than plain words')

    def body(self, h, text):
        if not h.quoted or not h.closed:   # no delimiter line: the shell may end it elsewhere, as in $(cat <<E ... E)
            raise Doubt('a heredoc that is no quoted text with its delimiter line')

    def subshell(self, kind):
        docs = list(self.pending)
        super().subshell(kind)
        if kind == 'subst' and self.pending != docs:   # "$(cat <<'E')": the lines after it run, the reader skips them
            raise Doubt('a heredoc open across the ) of $(...)')

    def skip_brace(self, j, dq):
        end = super().skip_brace(j, dq)
        if not VAR.fullmatch(self.s[j:end - 1]):
            raise Doubt('${...} with more than a name: a flag of zsh may run its text')
        return end

    def read_dollar(self, parts, holes, dq):
        if self.s[self.i + 1:self.i + 2] in ('[', '~', '=', '^', '+') or self.s.startswith('$((', self.i):
            raise Doubt('arithmetic or a flag of zsh after the $')
        super().read_dollar(parts, holes, dq)

    def command(self, words, redirs, heredocs, prev, nxt):
        first, self.first = self.first, False
        assigns, cmdw = split_assigns(words)
        if assigns or not cmdw or self.funcs:
            raise Doubt('an assignment, a lone redirection or a function')
        for op, w in redirs:
            target = self.s[w.start:w.end]
            if not (op == '>&' and target in ('1', '2') or op in ('>', '>>', '&>', '&>>') and target == '/dev/null'):
                raise Doubt('a redirection to a file or from one')
        head, args = cmdw[0], cmdw[1:]
        if not head.plain or head.value is None:
            raise Doubt('a command word that is not plain')
        name = head.value
        if heredocs and not (name == 'cat' and not args and all(DELIM.fullmatch(h.raw) for h in heredocs)):
            raise Doubt('a heredoc that is not the text of a cat')
        if name == 'cd':
            self.cd(args, first and len(self.frames) == 1 and nxt != '|')   # a pipe runs it in a subshell
        elif name == 'printf' and (not known(args[:1]) or args and args[0].value.startswith('-')):
            raise Doubt('printf with an option')   # -v sets a variable
        elif name in PRINTS or name == 'cat' and heredocs:
            pass   # their $(...) are commands of their own
        elif name in PIPE_FILTERS:
            if prev != '|' or not reads_pipe_only(name, values(args)):
                raise Doubt('a filter that reads no pipe or names a file')
        elif name == 'git':
            self.git(values(args[:1]), args[1:])
        elif name == 'gh':
            self.gh(args)
        else:
            raise Doubt('not on the list: ' + name)

    def cd(self, args, surely):
        if not surely or len(args) != 1 or not known(args):
            raise Doubt('a cd that is not cd <folder> as the first command')   # later it may not run: a && cd x; push
        to = args[0].value   # cd name: the CDPATH of the shell, which the hook may not see, may send it elsewhere
        if not to.startswith(('/', './', '../')) and to not in ('.', '..'):
            raise Doubt('cd - or a cd that CDPATH may send elsewhere')
        # a folder that is not there: the cd fails, the push runs where we are, and git has no answer about this one
        self.state.dir = os.path.normpath(to if to.startswith('/') else os.path.join(self.state.dir or '/nonexistent', to))

    def text_word(self, w):
        """A word of free text (a message, a title) is one word for the program whatever it holds: see the docstring."""
        if w.glob:
            raise Doubt('a glob or a brace outside quotes in a text word')
        i, quoted, holes = w.start, False, dict(w.holes)
        while i < w.end:
            c = self.s[i]
            if c == '\\':
                i += 2
            elif quoted and i in holes:
                i = holes[i]   # past the $(...): its commands are read on their own
            elif c == "'" and not quoted:
                i = self.s.index("'", i + 1) + 1
            elif c == '$' and not quoted:
                raise Doubt('a $ outside double quotes in a text word')
            else:
                quoted, i = quoted != (c == '"'), i + 1

    def git(self, sub, args):
        sub = sub[0] if sub else ''
        if sub == 'push':
            self.push(values(args))
        elif sub in GIT_READ:   # git takes --no-ind for --no-index
            if any(OUTSIDE.match(v) or v.startswith('--') and len(v) > 2 and any(
                    no.startswith(v.split('=')[0]) or v.startswith(no) for no in GIT_READ_NO) for v in values(args)):
                raise Doubt('git writes a file, runs a program or reads a file outside the repo')
        elif sub == 'branch':
            if not set(values(args)) <= BRANCH_FLAGS:
                raise Doubt('git branch that does more than list')
        elif sub == 'fetch':
            if any(v not in FETCH_FLAGS and not NAME.fullmatch(v) for v in values(args)):
                raise Doubt('git fetch with an option off the list')
        elif sub == 'add':   # a glob is a path here, a brace may hold an option: {-f,.env}
            if any(w.value is None or '{' in w.value or w.value.startswith('-') and w.value not in ADD_FLAGS for w in args):
                raise Doubt('git add with an option off the list')
        elif sub == 'commit':
            self.commit(args)
        else:
            raise Doubt('git ' + sub + ' is not on the list')

    def commit(self, args):
        k = 0
        while k < len(args):
            v = values(args[k:k + 1])[0]
            if COMMIT_MESSAGE.fullmatch(v) and k + 1 < len(args):
                k += 1   # the message: any text, its $(...) is a command of its own
                self.text_word(args[k])
            elif v not in COMMIT_FLAGS and not v.startswith('--message='):
                raise Doubt('git commit with an option off the list')
            k += 1

    def push(self, args):
        flags = [v for v in args if v.startswith('-')]
        rest = [v for v in args if not v.startswith('-')]
        if len(self.frames) != 1 or not set(flags) <= PUSH_FLAGS or len(rest) != 2 or rest[0] != 'origin':
            raise Doubt('a push that is not git push [-u] origin <branch> at the top level')
        if not NAME.fullmatch(rest[1]) or rest[1].lower() in PROTECTED or rest[1].startswith('refs/'):
            raise Doubt('a protected branch or no plain branch name')   # refs/heads/main is main
        if self.state.dir is None:
            raise Doubt('an unknown folder')
        self.pushes.append((self.state.dir, rest[1]))

    def gh(self, args):
        if len(args) < 2 or not known(args[:2]) or args[0].value != 'pr' or args[1].value not in GH_PR:
            raise Doubt('gh that is not pr create, view or checks')
        alone, text, plain, free = GH_PR[args[1].value]
        k = 2
        while k < len(args):
            v = values(args[k:k + 1])[0]
            if v in text and k + 1 < len(args):
                k += 1
                self.text_word(args[k])
            elif v in plain and k + 1 < len(args):
                k += 1
                values(args[k:k + 1])
            elif v in GH_JQ and k + 1 < len(args):
                k += 1
                if not JQ_PATH.fullmatch(values(args[k:k + 1])[0]):
                    raise Doubt('a jq filter that is more than a path')
            elif not v.startswith('-') and free:
                free -= 1
            elif v not in alone:
                raise Doubt('gh pr with an option off the list')
            k += 1


class GitSilent(Exception):
    """git gave no answer: it did not start or did not end in GIT_S. The prompt stays, the wrapper logs the name."""


def git(folder, *args):
    """(exit code, stdout) of a read-only question to git about the repo of folder."""
    try:
        p = subprocess.run(['git', '-C', folder] + list(args), capture_output=True, timeout=GIT_S,
                           stdin=subprocess.DEVNULL, env=dict(os.environ, GIT_OPTIONAL_LOCKS='0'))
    except (OSError, subprocess.SubprocessError) as e:
        raise GitSilent(type(e).__name__)
    return p.returncode, p.stdout.decode('utf-8', 'replace').strip()


def repo_ok(folder, branch):
    """The push of this name from this folder sends one local branch to the branch of that name of origin: the name is
    a local branch and nothing else (a tag of that name would go instead), origin is set, no setting sends it to
    another ref or adds tags, and it is not the default branch of origin, which the repo must know (a repo that does
    not could be asked about only over the network). Each answer must be the expected one: outside a repo it is not."""
    off = ((1, ''), (0, 'false'))
    default = git(folder, 'symbolic-ref', '-q', '--short', 'refs/remotes/origin/HEAD')
    where = git(folder, 'rev-parse', '--is-bare-repository', '--is-inside-work-tree', '--is-inside-git-dir')
    return (where == (0, 'false\ntrue\nfalse')   # a folder with HEAD, config and hooks/ in it is a repo for git too
            and git(folder, 'show-ref', '--verify', '--quiet', 'refs/heads/' + branch)[0] == 0
            and git(folder, 'show-ref', '--verify', '--quiet', 'refs/tags/' + branch)[0] == 1
            and git(folder, 'show-ref', '--verify', '--quiet', 'refs/' + branch)[0] == 1
            and git(folder, 'config', '--get', 'remote.origin.url')[0] == 0
            and git(folder, 'config', '--get-all', 'remote.origin.push')[0] == 1
            and git(folder, 'config', '--get-all', 'remote.origin.pushurl')[0] == 1
            and git(folder, 'config', '--type=bool', '--get', 'remote.origin.mirror') in off
            and git(folder, 'config', '--type=bool', '--get', 'push.followTags') in off
            and default[0] == 0 and default[1].lower() != 'origin/' + branch.lower())


def verdict(data):
    """'allow' or the reason of a pass."""
    if data.get('hook_event_name') != 'PermissionRequest' or data.get('tool_name') != 'Bash':
        return 'another event or tool'
    if data.get('permission_mode') not in MODES or data.get('agent_id'):
        return 'another permission mode or a subagent'
    cmd, cwd = data['tool_input']['command'], data['cwd']
    if data['tool_input'].get('dangerouslyDisableSandbox'):
        return 'a call that leaves the sandbox'
    if len(cmd) > MAX_INPUT or '\0' in cmd or not cwd.startswith('/') or not os.path.isdir(cwd):
        return 'a long command, a NUL in it or no folder'
    reader = Pushes(cmd, cwd, os.environ.get('HOME') or None, True)
    try:
        reader.read()
    except (Doubt, RecursionError) as e:
        return 'doubt: %s' % e
    if len(reader.pushes) != 1:
        return '%d pushes' % len(reader.pushes)
    return 'allow' if repo_ok(*reader.pushes[0]) else \
        'the repo: no work tree, no such local branch, a tag, the default branch of origin (or none known) or a push setting'


def main():
    signal.alarm(ALARM_S)
    data = json.loads(sys.stdin.buffer.read().decode('utf-8', 'surrogateescape'))
    ti = data.get('tool_input') if isinstance(data, dict) else None
    bad = ['input'] if not isinstance(data, dict) else [k for k, v in (
        ('tool_input.command', ti.get('command') if isinstance(ti, dict) else None), ('cwd', data.get('cwd')),
        ('hook_event_name', data.get('hook_event_name')), ('tool_name', data.get('tool_name')),
        ('permission_mode', data.get('permission_mode'))) if not isinstance(v, str)]
    if bad:
        print('ShapeDrift ' + ' '.join(bad))
        sys.exit(3)
    why = verdict(data)
    if why != 'allow' and os.environ.get('PUSH_ALLOW_DEBUG'):
        print('pass: %s' % why, file=sys.stderr)
    print('allow' if why == 'allow' else 'pass')


if __name__ == '__main__':
    try:
        main()
    except Exception as e:   # a bug, an input that is no JSON, git with no answer: one line for the log of the wrapper
        print('Error ' + type(e).__name__)
        sys.exit(3)
