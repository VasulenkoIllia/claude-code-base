#!/usr/bin/env python3
"""bash-guard-dirs: the part of a Bash command that bash-guard.sh still checks for a commit identity that is not the
owner's (stdlib, 3.9+; the shell reader is in bash_guard_shell.py and bash_guard_words.py, the folder checks in
bash_guard_repo.py). bash-guard asks before a commit or a git setting under another name; in a one-off repo under
/tmp (/private/tmp, the session scratchpads too) and for the text of a heredoc that only goes to a file or to git it
should not. bash-guard starts this script only when it is about to ask. The script reads the hook input (stdin JSON:
tool_input.command, cwd) and prints every simple command or heredoc of code with identity text (--author, user.name,
user.email, GIT_AUTHOR_*, GIT_COMMITTER_*) that does not provably run in a one-off repo, then a line "end";
bash-guard checks only that text again. On an error it prints "error <name>" and exits 1; for a field of the input
that is not a string it prints "error ShapeDrift <fields>" (tool_input.command, cwd), which bash-guard logs as such.
Any doubt keeps the text, so the worst case is the ask of before: what the reader does not follow (the whole
command); an unknown folder (a cd into a folder that is not there and that no mkdir before it makes; past the &&
list of a cd after a command that may fail; after cd -P, command cd, a function, eval or source; git -C with ..; the
terminal tool); an unknown, wrapped or zsh =command word ($GIT, a function, env -C, npm --prefix); a folder whose
files may be elsewhere (a link that ln makes or a copy of a folder with a link or a repo of elsewhere in it, a
worktree, a clone or a repo with a remote outside /tmp); ssh, docker, sudo, xargs or find; code that a shell or an
interpreter reads from a pipe (echo ... | bash); cd, -C, chdir or cwd in the identity word of git, in any word of
another command or in a heredoc of code; a write to a dot file outside /tmp
(~/.zshrc); git config --global, --system or --file; an export, an assignment, a function or a trap with identity
text and later a folder elsewhere or a script; code that runs with identity text in its environment (GIT_AUTHOR_NAME=x
bash <<EOF, bash -c, eval) and moves, links or, in shell code, does anything that is not provably in its one-off
folder; a trap that changes the folder or runs between commands (DEBUG, ERR); a command that links the repo to another
one (git push, clone, worktree, remote, submodule, --git-dir, GIT_DIR and the like but not a test's
GIT_CONFIG_NOSYSTEM or GIT_CONFIG_GLOBAL=/dev/null, -c alias. or include., gh, alias; a write into .git; an ln whose
link is on the way to the folder of git or inside a .git, any ln in a script or after xargs or sudo). The text of a
heredoc that cat or tee writes to a file, that git reads or that $(...) gives to git counts only when the command also
runs a script (bash, python3, ./file ...) and the script runs outside a one-off folder or the text has cd, -C, chdir,
cwd or a link to another repo (git push ...); with an unquoted delimiter and $(...) or backticks in it, it is code;
shell code of a heredoc that sets identity text itself is read as a command of
its own. A mkdir, a copy or git init that may not run or may fail does not count (in the background, after !, through
a link out of /tmp, mkdir -m without rwx for the owner); a command with a redirection that may fail counts as one that
may fail; rm, rmdir and mv may remove a folder (also after command or env, in a function at each call, rmdir -p with
its parents). Known limit: a folder that another command removes or closes (a script, find -delete, chmod) is taken
to be there and open, and a script that code of another language starts (python3 - <<EOF) is not followed. Env
(tests only): BASH_GUARD_DIRS_DEBUG=1 (the reason of a doubt on stderr).
"""
import json
import os
import re
import signal
import sys

sys.dont_write_bytecode = True   # no __pycache__ in the managed hooks folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I drops the script folder from sys.path
from bash_guard_repo import WRAP_DIR, Places, lexical_tmp  # noqa: E402  (missing or broken: bash-guard asks)
from bash_guard_shell import NAME, Doubt, ShellReader  # noqa: E402
from bash_guard_words import as_read, command_word, git_cmd, split_assigns  # noqa: E402

# the words of bash-guard's identity rules (it matches them without case)
IDENTITY = re.compile(r'--author|user\.(?:name|email)|git_(?:author|committer)_(?:name|email)', re.I)
# a move to another folder or host inside a word, a script or a heredoc of code
DIRCHANGE = re.compile(r'(?:^|[\s;&|(){}`\'"])(?:cd|pushd|popd|ssh|su)(?=[\s;&|(){}`\'"]|$)'
                       r'|(?:^|[\s\'"(\[,])-C(?=[\s\'",\])]|$)|--(?:git-dir|work-tree|prefix|cwd|dir|directory)\b'
                       r'|GIT_(?:DIR|WORK_TREE|COMMON_DIR)\b|chdir|\bcwd\b')
# what links a repo to another one, in a script or a heredoc of shell code
LINK_TEXT = re.compile(r'\bgit\b[^\n;&|]*?\s(?:push|clone|worktree|remote|submodule|subtree|svn|p4|send-email)\b'
                       r'|(?:^|[\s;&|(`\'"])(?:gh|glab|hub|ln)\s')
GLOBAL = re.compile(r'--(?:global|system|file)\b|(?:^|\s)-f(?:\s|$)')   # a git setting outside the repo
GIT_VARS = re.compile(r'GIT_(?:DIR|WORK_TREE|COMMON_DIR|OBJECT_DIRECTORY|ALTERNATE_OBJECT_DIRECTORIES|INDEX_FILE'
                      r'|NAMESPACE|TEMPLATE_DIR|EXEC_PATH|CONFIG\w*)\+?=')   # a repo, a config or a git of elsewhere
NO_CONFIG = re.compile(r'GIT_CONFIG_NOSYSTEM=.*|GIT_CONFIG_(?:GLOBAL|SYSTEM)=/dev/null', re.S)   # a test's isolation
RUNNER = re.compile(r'(?:ba|z|da|k)?sh|eval|source|\.|python[\d.]*|node|perl|ruby|php|deno|bunx?|tsx|npx|uvx?|make'
                    r'|osascript')   # may run a script the command writes
CODE_STDIN = re.compile(r'(?:ba|z|da|k)?sh|python[\d.]*|node|perl|ruby|php|deno|bun|osascript')   # bash <<EOF: code
LINK_CMD = {'gh', 'glab', 'hub'}   # ln: only when its links are in the way (ln())
ELSEWHERE = {'ssh', 'mosh', 'docker', 'podman', 'kubectl', 'vagrant', 'lxc', 'multipass', 'limactl', 'orb', 'orbctl',
             'su', 'sudo', 'doas', 'chroot', 'xargs', 'parallel', 'find'}   # may run anything in another folder
SHELLS = {'bash', 'sh', 'zsh', 'dash', 'ksh'}
# run no program and no git: an identity they get stays text; any other program may run git with it
QUIET = {':', '[', 'basename', 'cat', 'cd', 'chdir', 'chmod', 'cmp', 'comm', 'cp', 'cut', 'date', 'declare', 'diff',
         'dirname', 'du', 'echo', 'export', 'false', 'file', 'grep', 'head', 'jq', 'ln', 'local', 'ls', 'md5', 'mkdir',
         'mktemp', 'mv', 'od', 'paste', 'popd', 'printenv', 'printf', 'pushd', 'pwd', 'read', 'readlink', 'readonly',
         'realpath', 'rg', 'rm', 'rmdir', 'sed', 'seq', 'set', 'shasum', 'shift', 'sleep', 'sort', 'stat', 'tail',
         'tee', 'test', 'touch', 'tr', 'true', 'type', 'typeset', 'uniq', 'unset', 'wait', 'wc', 'which', 'xxd'}
ENV_CODE = ('BASH_ENV', 'ENV', 'ZDOTDIR', 'NODE_OPTIONS', 'PERL5OPT', 'RUBYOPT', 'PYTHONPATH', 'PYTHONSTARTUP',
            'DYLD_INSERT_LIBRARIES')   # a shell or a runtime first runs the file they name (also BASH_FUNC_*)
RESERVED = {'{', '}', 'if', 'then', 'else', 'elif', 'fi', 'for', 'while', 'until', 'do', 'done', 'case', 'esac',
            'select', 'function', 'coproc', 'repeat', 'foreach', 'end', '[[', '!', 'time'}
EVALS = ('source', '.', 'eval', 'emulate', 'fc')   # run text in this shell: it may cd and set anything
PERSIST = {'export', 'declare', 'typeset', 'local', 'readonly', 'trap'}   # identity text outlives the call
SETTERS = ('export', 'declare', 'typeset', 'local', 'readonly')   # their NAME=value arguments set shell variables
UNKNOWN_AFTER = ('unset', 'read', 'mapfile', 'readarray', 'getopts', 'printf')   # their NAME arguments get unknown
CD = ('cd', 'pushd', 'popd', 'chdir')
PREFIX = {'builtin', 'noglob', 'nocorrect', 'exec', '-'}   # the command after them runs as is (zsh: also repeat N)
TRUSTED = {'cd', 'pushd', 'mkdir', 'true', ':', 'export', 'echo', 'printf'}   # do not fail before a cd of their list
COPIERS = {'cp', 'gcp', 'mv', 'gmv', 'rsync', 'ditto'}
WRITES = ('>', '>>', '>|', '&>', '&>>', '<>')
MAX_INPUT = 200_000   # characters; a longer command is kept whole
ALARM_S = 4           # then the alarm kills the script: bash-guard logs it and asks as before (its timeout is 15 s)


class ShapeDrift(Exception):
    """A field of the hook input that the script reads is not a string (the names of such fields in its text)."""


class Guard(Places, ShellReader):
    def __init__(self, s, cwd, env):
        home = env.get('HOME') or ''
        super().__init__(s, cwd, home if home.startswith('/') and lexical_tmp(home) is None else None,
                         bool(env.get('CDPATH')))   # a home under /tmp (a sandbox) is no one-off folder either
        self.pieces = []    # (identity text, runs in a one-off repo, the folder of git)
        self.texts = []     # (identity text, as a shell runs it) of heredocs that only go to a file or to git
        self.runners = []   # the folders of the commands that may run a script the command writes (None: unknown)
        self.linked = self.unsafe = self.chase = False   # chase: set -P or setopt chaselinks, cd takes .. physically
        self.sure, self.env, self.cache, self.impure = True, env, {}, set()   # impure: see command()
        self.links, self.removers = [], set()   # (bash_guard_repo.Places)

    def result(self):
        self.read()
        keep = self.linked or self.unsafe
        out = [t for t, here, d in self.pieces if keep or not here or self.via_link(d)]
        far = keep or not all(self.ok(d) for d in self.runners)
        return out + [t for t, c in self.texts if self.runners and (far or DIRCHANGE.search(c) or LINK_TEXT.search(c))]

    def marked(self):
        return any(f.mark for f in self.frames if f.shell)

    def set_dir(self, d):
        if not self.ok(d) and self.marked():
            self.unsafe = True   # identity text that outlives its call, then a folder elsewhere
        self.state.dir = d

    def forget(self):
        """After a function, eval or source: any folder, any variable."""
        self.set_dir(None)
        self.state.vars = dict.fromkeys(self.state.vars)

    def settle(self):
        """Only the && list after a cd that may not run surely runs in its folder; past an ;, a newline, an & or an
        || (also in a subshell or a compound command after it) the folder may be the old one."""
        if self.state.fail and (self.list_or or not self.list_cd):
            self.state.fail = False
            self.set_dir(None)

    def command(self, words, redirs, heredocs, prev, nxt):
        self.sure = self.certain(self.frames)   # for the folders a mkdir or a copy makes (in the background: Doubt)
        assigns, cmdw = split_assigns(words)
        names = [os.path.basename(w.value) if w.value else None for w in cmdw]
        first, cw = (names[0] if names else None), command_word(cmdw)
        cname = os.path.basename(cw.value) if cw and cw.value else None
        scripts = self.scripts(cmdw, names)
        targets = [w for op, w in redirs if op in WRITES or op == '>&' and not re.fullmatch(r'\d*-?', w.value or '')]
        targets += [w for w in cmdw[1:] if not (w.value or '').startswith('-')] if first == 'tee' else []
        self.links_of(words, cmdw, names, scripts, targets, cw)
        if cname in ('rm', 'rmdir'):   # also after a wrapper (command rm, env rm)
            self.remove(cname, cmdw[cmdw.index(cw) + 1:])
        self.cdpath = self.cdpath or any(w.name in ('CDPATH', 'cdpath') for w in words)   # cd reads it unexported
        is_git, place = git_cmd(cmdw), self.place_of(cmdw, names)
        unknown = cw is not None and (cname is None or cname.startswith('='))   # $GIT, $(...), zsh =git
        call = bool({first, cname} & self.funcs.keys())   # its words may go to a git -C "$1" of the function
        moved = bool(ELSEWHERE & set(names)) or any(DIRCHANGE.search(t) for t in scripts) or not is_git and any(
            WRAP_DIR.match(w.value or '') for w in cmdw[1:])
        far_write = any(self.dot_far(w) for w in targets)
        runner = unknown or bool(ELSEWHERE & set(names)) or bool(cname and not is_git and (
            RUNNER.fullmatch(cname) or '/' in cw.value))
        if runner:
            self.runners.append(None if moved or unknown else self.state.dir)
        code_in = bool(cname and CODE_STDIN.fullmatch(cname)) and all(   # bash, python3 -: the code comes on stdin
            (w.value or 'x').startswith('-') for w in cmdw[cmdw.index(cw) + 1:])
        stdin = code_in and bool(heredocs)   # bash <<EOF: the heredoc is the script
        self.unsafe = self.unsafe or code_in and prev == '|'   # echo ... | bash: code we do not read
        env_code = any(w.name in ENV_CODE or (w.value or '').startswith('BASH_FUNC_') for w in words) or any(
            v in self.state.vars for v in ENV_CODE)
        opaque = cw is not None and not (is_git or call) and cname not in QUIET   # may run git with what it gets
        script = (runner or opaque) and (env_code or not scripts and not stdin)   # a script file, a program we do
        # not read
        dark = moved or unknown or script or bool(call and self.impure & {first, cname})   # runs what we do not read
        self.impure.update(f.name for f in self.frames if dark and f.kind == 'func')   # so does a later call of it
        if self.marked() and (place != self.state.dir and not self.ok(place) or dark):
            self.unsafe = True   # identity text that outlives its call, then git or a script elsewhere
        here = self.ok(place) and not (moved or unknown or call or far_write or script)
        env_id = self.marked() or bool(IDENTITY.search(' '.join(self.text(w) for w in words)))   # reaches its code
        for nm, ws in self.script_words(cmdw, names) if env_id else ():
            if nm != 'trap':
                vals = [w.value for w in ws]
                self.code_env(None if None in vals else ' '.join(vals), self.state.dir, True, nm == 'eval')
        persist = not cmdw or first in PERSIST or any(f.kind == 'func' for f in self.frames)
        self.identity(words + [w for _, w in redirs], place, here, persist, is_git)
        f = self.same_shell()[-1]   # $(cat <<EOF) in a word of git: its message
        to_git = f.kind == 'subst' and git_cmd(split_assigns(f.outer or [])[1])
        data = nxt != '|' and not far_write and (first in ('cat', 'tee') and (bool(targets) or to_git) or is_git)
        for h in heredocs:
            h.info = (data, here, cname in SHELLS, place, env_id)
        self.effects(assigns, cmdw, names, prev, nxt, any(self.redirect_fails(op, w) for op, w in redirs))

    def links_of(self, words, cmdw, names, scripts, targets, cw):
        """A command that may link the repo to another one sets linked; ln and copies (also after a wrapper: command
        mv) record where their files go."""
        assigned = [w.value if w.value is not None else (w.name or '') + '=' for w in words]
        if any(GIT_VARS.match(v) and not NO_CONFIG.fullmatch(v) for v in assigned) or (
                LINK_CMD & set(names) or 'ln' in names[1:] or names[:1] == ['alias']
                or any(LINK_TEXT.search(t) for t in scripts)
                or any(self.into_git(w) for w in targets)):
            self.linked = True
        if names[:1] == ['ln']:
            self.ln(cmdw[1:])
        elif cw is not None and os.path.basename(cw.value or '') in COPIERS:
            self.copy(os.path.basename(cw.value), cmdw[cmdw.index(cw) + 1:])

    def effects(self, assigns, cmdw, names, prev, nxt, bad):
        """What the command leaves to the next ones: variables and the folder (bad: a redirection that may fail, then
        the command does not run)."""
        frames = self.same_shell()
        piped = prev == '|' or nxt == '|' or any(f.pipe for f in frames)   # an & : bash_guard_shell doubts it
        maybe = bad or self.list_or or any(f.cond for f in frames)   # it may not run
        k = 0
        while k < len(names) and (names[k] in PREFIX or names[k] == 'repeat' and k + 1 < len(names) and (
                names[k + 1] or '').isdigit()):
            k += 2 if names[k] == 'repeat' else 1
        first = names[k] if k < len(names) else None
        args = [w.value or '' for w in cmdw[k + 1:]]
        if k and first in RESERVED and cmdw[k].plain:
            raise Doubt('a compound command after ' + names[0])   # zsh repeat 2 { cd ... }
        if first in self.funcs:   # a function runs instead, also one named cd
            if first in self.removers:
                self.changes.append((None, False, False, False))   # its body removes folders: any may be gone
            if self.funcs[first]:
                self.forget()   # its body may cd and set anything
        elif k < len(names) and (first is None or first.startswith('=')):
            self.forget()   # an unknown word ($C, $(...), zsh =cd) may be cd or eval
        elif first == 'command' and k + 1 < len(names) and names[k + 1] in CD + EVALS:
            self.forget()   # zsh runs /usr/bin/cd, which does nothing; bash its cd
        elif first in CD:
            self.cd('cd' if first == 'chdir' else first, cmdw[k + 1:], piped, maybe)
        elif first in EVALS:
            self.forget()
        elif first == 'trap' and (any(DIRCHANGE.search(t) for t in self.scripts(cmdw, names)) or any(
                a.upper() in ('DEBUG', 'ERR', 'ZERR', 'RETURN') for a in args[1:])):
            raise Doubt('a trap that changes the folder or runs between commands')
        elif first in ('set', 'setopt') and any(re.fullmatch(r'-\w*P\w*|physical|chase_?(?:links|dots)', a, re.I)
                                                for a in args):
            self.chase = True
        else:
            if first == 'mkdir':
                self.mkdir(cmdw[k + 1:])
            elif first == 'let':
                self.arith(' '.join(args))
            sure = not (piped or bad) and self.certain([f for f in frames if not f.shell])   # not after a risky one
            for w in assigns if not cmdw else cmdw[k + 1:] if first in SETTERS else ():
                if w.name:
                    self.state.vars[w.name] = w.avalue if sure else None
            for w in cmdw[k + 1:] if first in UNKNOWN_AFTER else ():
                if w.value and NAME.fullmatch(w.value):
                    self.state.vars[w.value] = None
        if bad or cmdw and first not in TRUSTED and not (first == 'git' and 'init' in args[:3]) and not (
                first == 'rm' and any(re.fullmatch(r'-[a-zA-Z]*f[a-zA-Z]*', a) for a in args)):
            self.list_risky = True   # a cd after it in its && list may not run

    def cd(self, kind, args, piped, maybe):
        if piped:
            raise Doubt('cd in a pipeline or in the background')
        self.list_cd = True
        new = self.target(kind, args)
        if new is not None and not self.exists(new):
            new = None   # something else in the command may make it (a link, a copy), or the cd fails
        self.set_dir(None if maybe and new != self.state.dir else new)
        self.state.fail = self.state.fail or (self.list_risky and self.state.dir is not None)
        self.list_risky = self.list_risky or self.state.dir is None   # it may fail: a cd after it may not run

    def target(self, kind, args):
        """The folder after cd, pushd or popd with these arguments, None when unknown."""
        k = 0
        while k < len(args) and re.fullmatch(r'-[LPe@]+|--', args[k].value or ''):
            k += 1
            if args[k - 1].value == '--':
                break
        rest = args[k:]
        if kind == 'popd' or any('P' in w.value for w in args[:k]):
            return None   # the stack; -P resolves the links before .., so the folder is not the path as written
        if kind == 'pushd' and any(w.value == '-n' for w in rest):
            return self.state.dir   # only the stack changes
        if not rest:
            return self.var('HOME') if kind == 'cd' else None
        v = rest[0].value
        if len(rest) > 1 or not v or rest[0].glob or v == '-' or re.fullmatch(r'[+-]\d+', v):
            return None   # zsh cd old new, unknown or empty (cd $EMPTY is cd), a glob, the previous folder, the stack
        if self.chase and '..' in v.split('/'):
            return None   # set -P: the .. of the folder after the links
        if self.cdpath and not v.startswith(('/', './', '../')) and v not in ('.', '..'):
            return None   # CDPATH may send it elsewhere
        return self.join(self.state.dir, v)

    def listed(self, words):
        self.identity(words, self.state.dir, self.ok(self.state.dir), False, False)

    def body(self, h, text):
        data, here, shell, place, env_id = h.info or (False, False, False, None, False)
        code = text.replace('\\\n', '')   # as the shell that runs it reads it: c\<newline>d is cd
        text = as_read(text)
        if data and (h.quoted or not re.search(r'\$\(|`', text)):
            if IDENTITY.search(text):
                self.texts.append((text, code))
            return
        if shell and LINK_TEXT.search(code):
            self.linked = True
        if env_id or shell and IDENTITY.search(text):   # identity in its environment or set in its shell code
            self.code_env(code, place, shell, mark=env_id)
        if IDENTITY.search(text):
            self.pieces.append((text, here and not DIRCHANGE.search(code), place))

    def identity(self, words, place, here, persist, is_git):
        piece = ' '.join(self.text(w) for w in words)
        if not IDENTITY.search(piece):
            return
        moves = not is_git and bool(DIRCHANGE.search(piece) or LINK_TEXT.search(piece))   # git: a message may say cd
        here = here and not GLOBAL.search(piece) and not moves
        self.pieces.append((piece, here, place))
        if here and persist:
            next(f for f in reversed(self.frames) if f.shell).mark = True

    def scripts(self, cmdw, names):
        """The text of the scripts a command runs (a heredoc in a $(...) of it is code, see to_git)."""
        return [' '.join(self.text(w) for w in ws) for _, ws in self.script_words(cmdw, names)]

    def script_words(self, cmdw, names):
        """(what runs it, its words) of each script a command runs: bash -c <script>, the arguments of eval, trap or
        watch as one."""
        found = []
        for j, nm in enumerate(names):
            if nm in SHELLS:
                k, c = j + 1, False
                while k < len(cmdw) and (cmdw[k].value or '').startswith('-'):
                    c = c or ('c' in cmdw[k].value and not cmdw[k].value.startswith('--'))
                    k += 1
                if c and k < len(cmdw):
                    found.append((nm, cmdw[k:k + 1]))
            elif nm in ('eval', 'trap', 'watch'):
                found.append((nm, cmdw[j + 1:]))
        return found

    def code_env(self, code, start, shell, same=False, mark=True):
        """Code that runs with identity text in its environment (bash <<EOF, bash -c, eval, python3 - <<EOF; None: a
        word we do not know): a move or a link in it, and in shell code anything that is not provably in its one-off
        folder (read as after an export of the identity), keeps the text. same: eval, in this shell. mark False:
        shell code that sets the identity itself, read as a command of its own."""
        if code is None or DIRCHANGE.search(code) or LINK_TEXT.search(code):
            self.unsafe = True
            return
        if not shell:
            return
        inner = Guard(code, start or '', self.env)
        inner.frames[0].mark = mark
        inner.cache, inner.links, inner.changes = self.cache, list(self.links), list(self.changes)
        inner.new_list(None)   # its first list starts after these changes
        if same:
            inner.state.vars, inner.chase = dict(self.state.vars), self.chase
            inner.funcs, inner.impure = dict(self.funcs), set(self.impure)
        if inner.result() or inner.linked or inner.unsafe:   # a doubt in it: the whole command
            self.unsafe = True


def read_input():
    data = json.loads(sys.stdin.buffer.read().decode('utf-8', 'surrogateescape'))
    ti = data.get('tool_input') if isinstance(data, dict) else None
    cmd, cwd = ti.get('command') if isinstance(ti, dict) else None, data.get('cwd') if isinstance(data, dict) else None
    drift = [name for name, v in (('tool_input.command', cmd), ('cwd', cwd)) if not isinstance(v, str)]
    if drift:
        raise ShapeDrift(' '.join(drift))
    if data.get('tool_name') == 'mcp__terminal__run_in_terminal':
        cwd = ''   # the terminal tab has its own folder
    return cmd.replace('\0', ''), cwd   # as bash: a NUL is dropped


def kept(cmd, cwd):
    """The parts of the command that bash-guard checks again: the whole command when it is too long or in doubt."""
    if len(cmd) > MAX_INPUT:
        return [cmd]
    try:
        return Guard(cmd, cwd, os.environ).result()
    except (Doubt, RecursionError) as e:
        if os.environ.get('BASH_GUARD_DIRS_DEBUG'):
            print('doubt: %s' % e, file=sys.stderr)
        return [cmd]


def main():
    signal.alarm(ALARM_S)
    try:
        out = '\n'.join([as_read(t) for t in kept(*read_input())] + ['end'])
    except Exception as e:   # bash-guard logs the name (ShapeDrift with its fields) and asks as before
        sys.stdout.write(' '.join(['error', type(e).__name__] + ([str(e)] if isinstance(e, ShapeDrift) else [])))
        sys.exit(1)
    sys.stdout.buffer.write(out.encode('utf-8', 'replace'))   # a raw byte comes as a lone surrogate: strict UTF-8 would raise


if __name__ == '__main__':
    main()
