#!/usr/bin/env python3
"""bash-guard-exec: the part of a Bash command that the ask rules of bash-guard.sh read (stdlib, 3.9+; the shell reader
is in bash_guard_shell.py and bash_guard_words.py). The rules match text, so they also trip on text that does not run
here: a script a heredoc writes, a command inside a test container. bash-guard starts this script only when a rule
tripped. It reads the hook input (stdin JSON: tool_input.command) and prints the command without what is listed below,
then a line "end"; bash-guard runs its ask rules again on that text. On an error it prints "error <name>" and exits 1;
for a command that is not a string it prints "error ShapeDrift tool_input.command", which bash-guard logs as such.

What goes, and only when all of it holds:
- the body of a heredoc with a quoted delimiter of cat or tee, or of python or node that read their code from stdin
  (python3 -, python3 -I - "$x", node -), with none of EXEC in it: no pipe after the command, no $(...) around it but
  one in a word of git commit (a message), no write to a dot path (~/.zshrc, .git/hooks/x) or to a file the text does
  not name, and no other command in the text that may run what was written (one outside NO_RUN and GIT_QUIET, also a
  $GIT or a function, but not docker exec on a container of the next point);
- the words after the container of docker exec, and its heredocs, when a name part of the container is e2e, test, tmp,
  scratch or sandbox (EPHEMERAL), with no $(...) that runs here in them, none of REMOTE, and no option of docker exec we
  do not know;
- docker volume rm when all its names are of that kind;
- docker compose config (or convert) with its output in a file: -o, --output, a redirection of stdout; not /dev/stdout
  and the like, not a lone variable, no pipe after it, no >&2 on it, and no cat, grep, jq and the like of that file
  in the text.
Docker that may talk to another daemon (DOCKER_HOST, --context) keeps its text.

Any doubt keeps the text, so the worst case is the ask of before: what the reader does not follow, a heredoc with no
delimiter line or with more than plain characters in it, a command too long and a pipe into something that may run
what comes (a shell or an interpreter with no script of its own, a program outside NO_RUN, not docker exec on such a
container) keep the whole command. Known limit: what a later Bash call runs is not followed (it has its own check), nor
is a file the model reads after writing it there.

BASH_GUARD_DIRS_DEBUG=1 (tests only): the reason of a doubt on stderr.
"""
import json
import os
import re
import signal
import sys

sys.dont_write_bytecode = True   # no __pycache__ in the managed hooks folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I drops the script folder from sys.path
from bash_guard_shell import Doubt, ShellReader  # noqa: E402  (missing or broken: bash-guard asks)
from bash_guard_words import as_read, command_word, git_cmd, split_assigns  # noqa: E402

# a program of the system: ./cat or a function may be anything
SYSTEM_BIN = re.compile(r'(?:/(?:usr/(?:local/)?|opt/homebrew/)?bin/)?([\w.+-]+)')
PYTHON = re.compile(r'python(?:3(?:\.\d+)?)?')
CODE_READER = re.compile(r'(?:ba|z|da|k)?sh|python[\d.]*|node|perl|ruby|php|deno|bun|osascript')   # code on stdin
# options of python and node that leave the code on stdin
STDIN_OPTION = re.compile(r'-[IuEsSBqOP]+|--(?:input-type=\w+|no-warnings)')
# what lets text in a heredoc run or reach a database, a removal in code (owner's decision 30.10: subprocess, eval,
# rmtree; the rest for the same reason)
EXEC = re.compile(r'subprocess|child_process|rmtree|__import__|importlib|ctypes|pexpect|paramiko|\bpty\b|\beval\b'
                  r'|\bos\.(?:system|popen|exec|spawn|posix_spawn|fork|remove|unlink|rmdir)|\bfrom\s+os\s+import\b'
                  r'|(?:exec|eval|system|popen|spawn|fork)\w*\s*\(|(?<![\w.])compile\s*\('
                  r'|\bnew\s+Function\b|\bFunction\s*\(|\b(?:Bun|Deno)\.|\bvm\.'
                  r'|\.(?:query|prepare|raw|run|unlink|rmdir)\s*\(|\$`|\$(?:execute|query)Raw|rmSync|unlinkSync'
                  r'|\bfs\.rm\b')
EPHEMERAL = re.compile(r'(?:^|[-_.])(?:e2e|test|tmp|scratch|sandbox)\d*(?:[-_.]|$)', re.I)   # whole name parts only:
# latest, fs-migrate or storage-check do not count
DOCKER_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]*')
EXEC_SWITCH = {'-i', '-t', '-d', '-it', '-ti', '--interactive', '--tty', '--detach'}
EXEC_VALUE = {'-e', '--env', '--env-file', '-u', '--user', '-w', '--workdir', '--detach-keys'}
EXEC_PAIR = re.compile(r'--(?:env|env-file|user|workdir|detach-keys)=')
OTHER_DAEMON = re.compile(r'DOCKER_(?:HOST|CONTEXT)|--context\b')
# a script with one of these reaches past its container; service= is the psql word, not a label like
# com.docker.compose.service=api
REMOTE = re.compile(r'\b(?:ssh|scp|rsync|curl|wget|nc|kubectl|aws|gcloud|gh)\b|://'
                    r'|(?:^|[\s"\'])(?:-h|(?:host|hostaddr|service)=)'
                    r'|--host\b|\bPG(?:HOST|SERVICE)\b|DATABASE_URL|docker\.sock|\bgit\s+push\b')
# cannot run a file of the text
NO_RUN = {':', '[', '[[', 'basename', 'break', 'cat', 'cd', 'chmod', 'chown', 'cmp', 'comm', 'continue', 'cp', 'cut',
          'date', 'declare', 'df', 'diff', 'dirname', 'du', 'echo', 'egrep', 'exit', 'export', 'false', 'fgrep', 'file',
          'grep', 'head', 'jq', 'ln', 'local', 'ls', 'md5', 'mkdir', 'mktemp', 'mv', 'od', 'paste', 'popd',
          'printf', 'pushd', 'pwd', 'read', 'readlink', 'readonly', 'realpath', 'return', 'rg', 'rm', 'rmdir', 'sed',
          'seq', 'set', 'sha256sum', 'shasum', 'shift', 'sleep', 'sort', 'stat', 'tail', 'tee', 'test', 'touch', 'tr',
          'true', 'type', 'typeset', 'uniq', 'unset', 'wait', 'wc', 'which', 'xxd'}
# these subcommands run no text of the command (its hooks are the project's own); rebase -x, bisect run, -c do
GIT_QUIET = {'add', 'branch', 'checkout', 'commit', 'diff', 'fetch', 'log', 'ls-files', 'pull', 'push', 'remote', 'reset',
             'restore', 'rev-parse', 'rm', 'show', 'stash', 'status', 'switch', 'tag'}
MOVES = {'cp', 'ln', 'mv'}   # to a dot path: a hook that a later git runs
PRINTS = {'awk', 'bat', 'cat', 'grep', 'head', 'jq', 'less', 'more', 'sed', 'tail', 'yq'}
WRITES = ('>', '>>', '>|', '&>', '&>>', '<>')
DOT_PATH = re.compile(r'(?:^|/)\.(?!\.?(?:/|$))')   # a dot file or folder on the way, not . or ..
LONE_VAR = re.compile(r'\$\{?\w+\}?')
TERMINAL = re.compile(r'/dev/(?!null$)|(?:^|/)(?:stdout|stderr|tty|fd/\d+)$')
HOLE = re.compile(r'\$\(|`')   # in a heredoc with a bare delimiter it runs here, before the text goes to the container
# a delimiter as written, of plain characters: the reader and the shell end the body on the same line
DELIM = re.compile(r'\\?[\w.-]+|\'[\w.-]+\'|"[\w.-]+"')
COMPOSE_VALUE = {'-f', '--file', '-p', '--project-name', '--env-file', '--project-directory', '--profile', '--ansi',
                 '--parallel', '--progress', '--workdir'}   # global options of docker compose with a value
DATA, CODE, CONTAINER = 'data', 'code', 'container'   # Heredoc.info
MAX_INPUT = 200_000   # characters; a longer command is kept whole
ALARM_S = 4           # then the alarm kills the script: bash-guard logs it and asks as before (its timeout is 15 s)


def tool(word):
    """The program this word runs when it is the system's, else None (an unknown word too)."""
    m = SYSTEM_BIN.fullmatch(word.value or '')
    return m.group(1) if m else None


def is_file(path):
    """The text of an output word names a file: not a terminal, not stdout, not a lone variable that may be either."""
    return bool(path) and path not in ('-', '!') and not LONE_VAR.fullmatch(path) and not TERMINAL.search(path)   # zsh >!


def ephemeral(w):
    return w.value is not None and not w.glob and bool(DOCKER_NAME.fullmatch(w.value) and EPHEMERAL.search(w.value))


def container_at(args):
    """The index of the container in the words after docker exec; None with an option we do not know."""
    k = 0
    while k < len(args) and (args[k].value or '').startswith('-'):
        v = args[k].value
        if v not in EXEC_SWITCH and v not in EXEC_VALUE and not EXEC_PAIR.match(v):
            return None
        k += 2 if v in EXEC_VALUE else 1
    return k if k < len(args) else None


def git_sub(args):
    """The subcommand of git past -C <dir> and --no-pager; another option first (-c may set an alias) gives that word."""
    k = 0
    while k < len(args) and args[k].value in ('-C', '--no-pager'):
        k += 2 if args[k].value == '-C' else 1
    return args[k].value if k < len(args) else None


def commit_message(words):
    """These are the words of git commit: the text of a $(...) in them is a message."""
    cmdw = split_assigns(words)[1]
    return git_cmd(cmdw) and git_sub(cmdw[cmdw.index(command_word(cmdw)) + 1:]) == 'commit'


def subcommand_at(args, k):
    """The index of the subcommand of docker compose in args, past its global options from index k."""
    while k < len(args) and (args[k].value or '').startswith('-'):
        k += 2 if args[k].value in COMPOSE_VALUE else 1
    return k


def stdin_code(args):
    """python or node with these words takes its code from stdin."""
    for w in args:
        if w.value == '-':
            return True
        if w.value is None or not STDIN_OPTION.fullmatch(w.value):
            return False
    return True


def reads_code(name, args):
    """A shell or an interpreter with no script of its own, or a program we do not know, runs what comes on a pipe."""
    if not name or not CODE_READER.fullmatch(name):
        return name not in NO_RUN and name != 'awk'
    for w in args:
        v = w.value or 'x'
        if v in ('-', '--') or re.fullmatch(r'-\w*s\w*', v):   # bash -s -- a, python3 - a
            return True
        if not v.startswith('-'):
            return False
    return True


class Executed(ShellReader):
    def __init__(self, s):
        super().__init__(s, '', None)   # no folder and no variable is followed here: each $x is unknown
        self.docker_here = not OTHER_DAEMON.search(s)
        self.cuts, self.held = [], []   # spans that go; held: of heredocs, they go unless self.runs
        self.outs, self.shown = [], set()   # (span, file) of compose config; what cat, head and tail read
        self.runs = False    # a command that may run a file of this text
        self.piped = False   # a program outside NO_RUN reads a pipe: it may run what comes

    def settle(self):
        pass   # no folders

    def listed(self, words):
        pass

    def raw(self, w):
        return os.path.normpath(re.sub(r'[\'"\\]', '', self.s[w.start:w.end]))

    def plain_file(self, w):
        """A file the text names, not a dot path: ~/.zshrc or .git/hooks/x runs by itself."""
        return not w.glob and is_file(self.raw(w)) and not DOT_PATH.search(self.raw(w))

    def subshell(self, kind):
        docs = list(self.pending)
        super().subshell(kind)
        if kind == 'subst' and self.pending != docs:
            raise Doubt('a heredoc open across the ) of $(...): the shell does not read it as the reader does')

    def command(self, words, redirs, heredocs, prev, nxt):
        cmdw = split_assigns(words)[1]
        cw = command_word([w for w in cmdw if w.name is None])   # env A=$x docker ...: the value of A is unknown
        if cw is None:   # $(<file), or the redirections of { ...; } > file
            self.shown.update(self.raw(w) for op, w in redirs if op == '<')
            self.runs = self.runs or not all(self.plain_file(w) for op, w in redirs if op in WRITES)
            return
        if any(not DELIM.fullmatch(h.raw) for h in heredocs):
            raise Doubt('a delimiter the shell may read in another way')
        name, args = tool(cw), cmdw[cmdw.index(cw) + 1:]
        if name in self.funcs:
            name = None   # docker() { "$@"; }: its words may run here
        inside = self.test_container(name, args)
        if prev == '|' and inside is None and reads_code(name, args):
            self.piped = True
        if name in PRINTS:
            self.shown.update(self.raw(w) for w in args + [w for op, w in redirs if op == '<'])
            self.shown.update('*' for w in args if w.glob)
        kind = self.heredoc_kind(name, args, redirs, nxt) if heredocs and all(h.quoted for h in heredocs) else None
        for h in heredocs:
            h.info = CONTAINER if inside is not None else kind
        quiet = name in NO_RUN or name == 'git' and git_sub(args) in GIT_QUIET
        if not quiet and kind != CODE and inside is None or name in MOVES and any(
                DOT_PATH.search(self.raw(w)) for w in args):
            self.runs = True
        if inside is not None:
            self.script(args[inside + 1:])
        elif self.docker_here and name == 'docker' and [w.value for w in args[:2]] == ['volume', 'rm']:
            names = [w for w in args[2:] if w.value not in ('-f', '--force')]
            if names and all(ephemeral(w) for w in names):
                self.cuts.append((cw.start, args[-1].end))
        elif self.docker_here and name in ('docker', 'docker-compose'):
            self.compose(name, cw, args, redirs, nxt)

    def test_container(self, name, args):
        """The index in args of the container of docker exec, when its name counts (EPHEMERAL), else None."""
        if name != 'docker' or not self.docker_here or not args or args[0].value != 'exec':
            return None
        k = container_at(args[1:])
        return k + 1 if k is not None and ephemeral(args[k + 1]) else None

    def heredoc_kind(self, name, args, redirs, nxt):
        """DATA, CODE or None for the quoted heredocs of this command."""
        f = self.same_shell()[-1]
        if nxt == '|' or f.kind == 'subst' and not commit_message(f.outer or []):
            return None   # a $(...) gives the text to its command; git commit takes it as a message
        targets = [w for op, w in redirs if op in WRITES or op == '>&' and not re.fullmatch(r'\d*-?', self.raw(w))]
        targets += [w for w in args if not (w.value or '').startswith('-')] if name == 'tee' else []
        if not all(self.plain_file(w) for w in targets):
            return None
        if name in ('cat', 'tee'):
            return DATA
        return CODE if (name == 'node' or PYTHON.fullmatch(name or '')) and stdin_code(args) else None

    def body(self, h, text):
        if not h.closed:
            raise Doubt('no delimiter line: the shell may end this heredoc elsewhere, as in $(cat <<E ... E)')
        if h.info in (DATA, CODE) and not EXEC.search(text):
            self.held.append(h.span)
        elif h.info == CODE:
            self.runs = True
        elif h.info == CONTAINER and not REMOTE.search(text) and (
                h.quoted or not HOLE.search(text.replace('\\\n', ''))):   # a backslash-newline joins $ and (
            self.cuts.append(h.span)

    def script(self, words):
        """The words after the container: a $(...) in them runs here, not in it."""
        if words and not any(w.holes for w in words):
            span = words[0].start, words[-1].end
            if not REMOTE.search(self.s[span[0]:span[1]]):
                self.cuts.append(span)

    def compose(self, name, cw, args, redirs, nxt):
        """docker compose config with its output in a file: its words go, unless the text then prints that file."""
        words = [w.value for w in args]
        if name == 'docker' and words[:1] != ['compose']:
            return
        at = subcommand_at(args, 1 if name == 'docker' else 0)
        if words[at:at + 1] not in (['config'], ['convert']) or nxt == '|' or any(w.holes for w in args):
            return
        if any(op == '>&' and w.fd in ('', '1') for op, w in redirs):
            return   # > c.json >&2: stdout ends on another descriptor
        files = [self.raw(w) for op, w in redirs if op in WRITES and op != '<>' and w.fd in ('', '1')]
        for k, w in enumerate(args[at + 1:], at + 1):
            if words[k] in ('-o', '--output') and k + 1 < len(args):
                files.append(self.raw(args[k + 1]))
            elif self.raw(w).startswith('--output='):
                files.append(os.path.normpath(self.raw(w)[len('--output='):]))
        if files and all(is_file(p) for p in files):
            self.outs += [((cw.start, args[-1].end), p) for p in files]

    def result(self):
        self.read()
        if self.piped:
            return self.s
        cuts = self.cuts + ([] if self.runs else self.held)
        gone = {span for span, p in self.outs if p in self.shown or '*' in self.shown}
        cuts += [span for span, _ in self.outs if span not in gone]
        out, at = [], 0
        for a, b in sorted(cuts):
            out.append(self.s[at:max(a, at)])
            at = max(at, b)
        return ''.join(out) + self.s[at:]


def executed(cmd):
    """The text the ask rules read; the whole command when it is too long or in doubt."""
    if len(cmd) > MAX_INPUT:
        return cmd
    try:
        return Executed(cmd).result()
    except (Doubt, RecursionError) as e:
        if os.environ.get('BASH_GUARD_DIRS_DEBUG'):
            print('doubt: %s' % e, file=sys.stderr)
        return cmd


def main():
    signal.alarm(ALARM_S)
    try:
        data = json.loads(sys.stdin.buffer.read().decode('utf-8', 'surrogateescape'))
        ti = data.get('tool_input') if isinstance(data, dict) else None
        cmd = ti.get('command') if isinstance(ti, dict) else None
        if not isinstance(cmd, str):
            sys.stdout.write('error ShapeDrift tool_input.command')
            sys.exit(1)
        out = as_read(executed(cmd.replace('\0', ''))) + '\nend'   # as bash reads it: no NUL
    except Exception as e:   # bash-guard logs the name and asks as before
        sys.stdout.write('error ' + type(e).__name__)
        sys.exit(1)
    sys.stdout.buffer.write(out.encode('utf-8', 'replace'))   # a raw byte comes as a lone surrogate: strict UTF-8 would raise


if __name__ == '__main__':
    main()
