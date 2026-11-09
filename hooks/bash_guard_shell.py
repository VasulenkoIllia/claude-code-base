"""bash_guard_shell: the shell reader of bash-guard-dirs.py (stdlib, 3.9+), split off for size. It walks a Bash or
zsh command as the shell would (words with their quotes and expansions, backslash-newline continuations, operators,
subshells and $(...), if, loops, { } groups, functions, heredocs) and keeps self.state, the folder and the variables a
command runs with (a subshell drops its changes at its end). What the reader does not follow raises Doubt (case,
select, function, coproc, backticks, <(...), a command in arithmetic, a ( inside a command, an open quote or compound
command, a loop that changes the folder or a variable, a piped or background list or compound command that does or
that makes or removes a folder, ! before a compound command or a cd, a function the shell runs by itself): the caller
keeps it all."""
import os
import re

from bash_guard_words import NAME, Doubt, WordReader

KEYWORD = re.compile(r'(if|then|elif|else|fi|for|while|until|do|done|case|esac|select|function|coproc|time|!|\{|\})'
                     r'(?=[ \t\n;&|()<>]|$)')
REDIR = re.compile(r'(\d*|\{[A-Za-z_][A-Za-z0-9_]*\})(<<<|<<-|<<|<>|<&|>&|>>|>\||&>>|&>|<|>)')
FUNC = re.compile(r'\([ \t]*\)')
BLANKS = re.compile(r'(?:[ \t]|\\\n)*')
NEXT_OP = re.compile(r'(?:[ \t]|\\\n)*(&&|\|\||&>|[|&;\n)])')   # the operator after a command (&> is a redirection)
CLOSE = {'fi': ('if',), 'done': ('loop',), '}': ('group', 'func')}
# functions zsh or bash runs by themselves: on a trap (zsh TRAPDEBUG, TRAPZERR), after a cd, for a missing command
HOOK_FUNC = re.compile(r'TRAP[A-Z0-9]+|chpwd|precmd|preexec|periodic|zshexit|zshaddhistory|command_not_found_handler?')


class State:
    __slots__ = ('dir', 'vars', 'fail')

    def __init__(self, d, v, fail=False):
        self.dir, self.vars, self.fail = d, v, fail   # dir: absolute, normalized or None (unknown); vars: name -> value
        # or None; fail: the folder holds only for the rest of the && list (a cd of the caller or a { } group that may
        # not have run), dropped with the state at the end of a subshell

    def copy(self):
        return State(self.dir, dict(self.vars), self.fail)


class Frame:
    """A subshell (top, sub, subst: its state is dropped at its end) or a compound command of the same shell (group,
    func, if, loop; cond: what runs in it may not run). start: the folder and variables at its start; lists: the
    and-or list it is in (list_flags()); outer: of a $(...), the words before it of the command it is in; name: of a
    function."""

    def __init__(self, kind, cond=False, pipe=False, start=None, lists=None, outer=None, name=None):
        self.kind, self.cond, self.pipe, self.start, self.lists = kind, cond, pipe, start, lists
        self.outer, self.name = outer, name
        self.shell = kind in ('top', 'sub', 'subst')
        self.mark = False    # for the caller: bash-guard-dirs marks identity text that outlives its call


class Heredoc:
    __slots__ = ('raw', 'delim', 'strip', 'quoted', 'info', 'span', 'closed')

    def __init__(self, raw, strip):   # the delimiter after quote removal, as the shell compares it
        self.raw, self.delim = raw, re.sub(r'[\'"\\]', '', raw)
        self.strip, self.quoted, self.info = strip, self.delim != raw, None   # info: set by command(), read by body()
        self.span, self.closed = None, False   # where the body and its delimiter line are in the text; a line ended it


class ShellReader(WordReader):
    """The caller defines command(words, redirs, heredocs, prev, nxt) for every simple command (prev, nxt: the
    operators around it), listed(words) for the words of a for list, body(heredoc, text) for each heredoc body and
    settle() before each command is read (a folder that holds only for the && list before), and appends to
    self.changes what a command makes or removes on disk."""

    def __init__(self, s, cwd, home, cdpath=False):
        self.s, self.n, self.i = s, len(s), 0
        self.home, self.cdpath = home, cdpath   # home: None when it must not count as a folder (unknown)
        self.state = State(os.path.normpath(cwd) if cwd.startswith('/') else None, {})
        self.frames = [Frame('top')]
        self.pending = []   # heredocs whose body starts after the next newline
        self.funcs = {}     # the functions the command defines: name -> its body changes the folder or a variable
        self.cmds = []      # the words of the commands being read, outermost first
        self.func = None    # name() was read: its body comes next
        self.changes = []   # filled by the caller (bash_guard_repo.Places); a list in the background must not grow it
        self.new_list(None)

    def read(self):
        self.parse_list(False)
        if len(self.frames) != 1 or self.func:
            raise Doubt('open compound command')

    # ------------------------------------------------------------ helpers
    def blanks(self):
        self.i = BLANKS.match(self.s, self.i).end()

    def new_list(self, op):
        """A new and-or list after op: in it a cd, an ||, a command that may fail (the caller sets it), and the
        folder and variables at its start."""
        self.op, self.list_cd, self.list_or, self.list_risky = op, False, False, False
        self.list_start = self.list_state()

    def snapshot(self):
        return self.state.dir, dict(self.state.vars)

    def list_state(self):
        return self.snapshot() + (len(self.changes),)

    def list_flags(self):
        return self.op, self.list_cd, self.list_or, self.list_risky, self.list_start

    def certain(self, frames):
        """The command being read surely runs, as far as these frames go: no ||, condition, loop or command that may
        fail before it in its list or in the list of a frame."""
        return not (self.list_or or self.list_risky) and not any(
            f.cond or f.lists and (f.lists[2] or f.lists[3]) for f in frames)

    def same_shell(self):
        """The frames of the current shell, innermost first, down to its subshell frame."""
        out = []
        for f in reversed(self.frames):
            out.append(f)
            if f.shell:
                break
        return out

    def var(self, name):
        if name == 'PWD':
            return self.state.dir
        return self.state.vars[name] if name in self.state.vars else self.home if name == 'HOME' else None

    def text(self, w):
        """The word as written (no backslash-newline: the shell glues its parts), each $(...) in it replaced by
        $() (its commands are reported on their own)."""
        out, at = [], w.start
        for a, b in w.holes:
            if a >= at:
                out += [self.s[at:a], '$()']
                at = b
        out.append(self.s[at:w.end])
        return ''.join(out).replace('\\\n', '')

    def peek_op(self):
        m = NEXT_OP.match(self.s, self.i)
        return m.group(1) if m and m.group(1) != '&>' else None

    # ------------------------------------------------------------ lists
    def parse_list(self, stop):
        s = self.s
        while True:
            self.blanks()
            if self.i >= self.n:
                if stop:
                    raise Doubt('open (')
                return
            c, two = s[self.i], s[self.i:self.i + 2]
            if c == ')':
                if stop:
                    return
                raise Doubt('stray )')
            if self.func and c not in '\n{':
                raise Doubt('function body')
            if c == '\n':
                self.i += 1
                self.read_heredocs()
                if self.op not in ('&&', '||', '|'):   # after them the list goes on past the newline
                    self.new_list('\n')
            elif c == '#':
                j = s.find('\n', self.i)
                self.i = self.n if j < 0 else j
            elif two in ('&&', '||'):
                self.i += 2
                self.op = two
                self.list_or = self.list_or or two == '||'
            elif c == ';' or (c == '&' and two != '&>'):
                if two in (';;', ';&') or (c == '&' and self.list_state() != self.list_start):
                    raise Doubt('case item or a background list that changes a folder or a variable')
                self.i += 1
                self.new_list(c)
            elif c == '|':
                self.i += 2 if two == '|&' else 1
                self.op = '|'
            elif two == '((':
                self.i = self.skip_arith(self.i + 2)
                self.op, self.list_risky = None, True   # (( 0 )) fails
            elif c == '(':
                self.i += 1
                self.subshell('sub')
                self.op, self.list_risky = None, True   # it may fail
            else:
                self.parse_command()

    def subshell(self, kind):
        """( list ) or $( list ): read with a copy of the state, which is dropped at the )."""
        saved, flags = self.state.copy(), self.list_flags()
        self.frames.append(Frame(kind, lists=flags, outer=self.cmds[-1] if kind == 'subst' and self.cmds else None))
        depth = len(self.frames)
        self.new_list(None)
        self.parse_list(True)
        if len(self.frames) != depth or self.func:
            raise Doubt('open compound command in ( )')
        self.frames.pop()
        self.i += 1
        self.state = saved
        self.op, self.list_cd, self.list_or, self.list_risky, self.list_start = flags

    # ------------------------------------------------------------ a command
    def parse_command(self):
        self.settle()   # before a word expands ($PWD) or a compound command keeps the folder
        prev, self.op, neg = self.op, None, False
        s = self.s
        while True:   # reserved words at the start of a command
            self.blanks()
            m = KEYWORD.match(s, self.i)
            if not m:
                if s.startswith('(', self.i):
                    return   # ! ( list ), time ( list ), then ( list ): parse_list reads the subshell
                break
            k = m.group(1)
            if k in ('case', 'esac', 'select', 'function', 'coproc') or (self.func and k != '{') or (
                    neg and k in ('if', 'while', 'until', 'for', '{')):
                raise Doubt(k)   # ! { cd x; } && git: git runs where the cd failed
            neg = neg or k == '!'
            self.i = m.end()
            if k in ('if', 'while', 'until', '{'):
                kind = 'func' if self.func else {'if': 'if', '{': 'group'}.get(k, 'loop')
                self.frames.append(Frame(kind, kind != 'group' or self.list_or, prev == '|', self.snapshot(),
                                         self.list_flags(), name=self.func))
                self.func = None
            elif k in CLOSE:
                f = self.frames[-1]
                if f.kind not in CLOSE[k]:
                    raise Doubt('unmatched ' + k)
                if f.start != self.snapshot() and (f.kind == 'loop' or self.peek_op() == '|'):
                    raise Doubt('a loop or a piped compound command that changes the folder or a variable')
                if f.kind == 'func':   # the body runs at a call, not here
                    self.funcs[f.name] = f.start != self.snapshot()
                    self.state.dir, self.state.vars = f.start[0], dict(f.start[1])
                moved = f.kind == 'group' and f.lists[3] and f.start[0] != self.state.dir   # it may not have run
                self.frames.pop()
                self.op, self.list_cd, self.list_or, self.list_risky, self.list_start = f.lists
                self.list_risky = True   # back in the list it is in, where it may fail
                if moved:
                    self.state.fail = self.list_cd = True   # its folder holds for the rest of the && list only
                break   # then only redirections
            elif k == 'for':
                self.for_header(prev)
                return
            # then, elif, else, do, !, time: the command follows
        words, redirs, heredocs = [], [], []
        self.cmds.append(words)
        while True:
            self.blanks()
            if self.i >= self.n:
                break
            c = s[self.i]
            if c in '\n;|)#' or (c == '&' and s[self.i:self.i + 2] != '&>'):
                break
            if c == '(':
                m = FUNC.match(s, self.i)
                if m and len(words) == 1 and not redirs and words[0].plain and NAME.fullmatch(words[0].value or ''):
                    if HOOK_FUNC.fullmatch(words[0].value):
                        raise Doubt('a function the shell runs by itself')
                    self.i = m.end()
                    self.func = words[0].value   # name() { body }
                    self.funcs[self.func] = True   # till its body is read: it may change anything
                    self.cmds.pop()
                    return
                raise Doubt('( inside a command')
            m = REDIR.match(s, self.i) if c in '<>&{0123456789' else None
            if m:
                self.redirection(m, redirs, heredocs)
            else:
                words.append(self.read_word())
        self.cmds.pop()
        if words or redirs or heredocs:
            at = self.state.dir
            self.command(words, redirs, heredocs, prev, self.peek_op())
            if neg and self.state.dir != at:
                raise Doubt('! cd')   # its && list goes on only where the cd failed
        self.list_risky = self.list_risky or neg   # ! cmd: its success stops the && list after it

    def for_header(self, prev):
        self.blanks()
        if self.s.startswith('((', self.i):
            self.i = self.skip_arith(self.i + 2)
        else:
            w = self.read_word()
            if w.value and NAME.fullmatch(w.value):
                self.state.vars[w.value] = None
            words = []
            while True:
                self.blanks()
                if self.i >= self.n or self.s[self.i] in '\n;&|)#':
                    break
                if self.s[self.i] in '(<>':
                    raise Doubt('odd for list')
                words.append(self.read_word())
            self.listed(words[1:] if words and words[0].plain and words[0].value == 'in' else words)
        self.frames.append(Frame('loop', True, prev == '|', self.snapshot(), self.list_flags()))

    def redirection(self, m, redirs, heredocs):
        op = m.group(2)
        self.i = m.end()
        self.blanks()
        if self.i >= self.n or self.s[self.i] in '\n;&|()<>':
            raise Doubt('redirection without a target or <(...)')
        w = self.read_word()
        w.fd = m.group(1)
        if op in ('<<', '<<-'):
            h = Heredoc(self.s[w.start:w.end], op == '<<-')
            heredocs.append(h)
            self.pending.append(h)
        else:
            redirs.append((op, w))

    # ------------------------------------------------------------ heredocs
    def read_heredocs(self):
        pend, self.pending = self.pending, []
        for h in pend:
            start, end, line, at = self.i, self.n, '', None   # no delimiter: the body runs to the end
            while self.i < self.n:
                j = self.s.find('\n', self.i)
                part = self.s[self.i:self.n if j < 0 else j]
                at = self.i if at is None else at
                self.i = self.n if j < 0 else j + 1
                if j >= 0 and not h.quoted and (len(part) - len(part.rstrip('\\'))) % 2:
                    line += part[:-1]   # with an unquoted delimiter a backslash-newline joins two lines
                    continue
                line += part
                if (line.lstrip('\t') if h.strip else line) == h.delim:
                    end, h.closed = at, True
                    break
                line, at = '', None
            h.span = start, self.i
            self.body(h, self.s[start:end])
