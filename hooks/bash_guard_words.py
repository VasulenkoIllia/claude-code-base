"""bash_guard_words: the word reader of bash_guard_shell.py (stdlib, 3.9+), split off for size: a word of a Bash or
zsh command with its quotes and expansions ($x, ${x}, $(...), ~, a backslash-newline), the skips past ${...} and
arithmetic (a variable it assigns gets unknown) and the word of what a command runs."""
import os
import re

NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
ASSIGN = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\+?=')
# a variable that arithmetic assigns: x = 1, x[2] += 1, x++, --x (not ==, <=, >=, !=)
ARITH_SET = re.compile(r'([A-Za-z_]\w*)(?:\[[^\]]*\])?\s*(?:\*\*|<<|>>|&&|\|\||\^\^|[-+*/%&|^])?=(?!=)'
                       r'|(?:\+\+|--)\s*([A-Za-z_]\w*)|([A-Za-z_]\w*)\s*(?:\+\+|--)')
META = ' \t\n;&|()<>'
GIT_PATHS = ('git', '/usr/bin/git', '/opt/homebrew/bin/git', '/usr/local/bin/git')   # ./git may be a script
WRAPPERS = {'env', 'command', 'builtin', 'exec', 'nice', 'nohup', 'time', 'noglob', 'nocorrect', 'timeout', 'gtimeout'}


def as_read(t):
    """A command as bash-guard reads it: a blank for each backslash-newline; with one inside a word the glued text too, as
    one more line (a \\\\ before the newline: one backslash in a double-quoted script)."""
    blank = t.replace('\\\n', ' ')
    return blank + '\n' + re.sub(r'\\?\\\n', '', t) if re.search(r'\S\\\n\S', t) else blank


class Doubt(Exception):
    """A construct the reader does not follow: the caller keeps the whole command."""


def command_word(cmdw):
    """The word of what runs, past wrappers (env, nice, time ...) and their options; None when there is none."""
    for w in cmdw:
        if (os.path.basename(w.value) if w.value else None) not in WRAPPERS and not re.fullmatch(
                r'-\S*|\w+=.*|\d+[smhd]?', w.value or ''):
            return w
    return None


def git_cmd(cmdw):
    w = command_word(cmdw)
    return w is not None and w.value in GIT_PATHS


def split_assigns(words):
    k = 0
    while k < len(words) and words[k].name is not None:
        k += 1
    return words[:k], words[k:]


class Word:
    """value: after quote removal and expansion, None when unknown; holes: the spans of $(...) in it; name and
    avalue: of NAME=value; plain: no quotes or expansions (only then a reserved word counts); fd: of the target of a
    redirection, the number before the operator ('' when there is none)."""
    __slots__ = ('start', 'end', 'value', 'glob', 'holes', 'name', 'avalue', 'plain', 'fd')


class WordReader:
    """For ShellReader: reads self.s at self.i with its var() and subshell(); arith() sets self.state.vars."""

    def read_word(self):
        s, n = self.s, self.n
        w = Word()
        w.start, w.holes, w.glob = self.i, [], False
        parts, quoted = [], False
        m = ASSIGN.match(s, self.i)
        w.name = m.group(1) if m else None
        old = self.var(w.name) if m and m.group(0).endswith('+=') else ''   # NAME+=value appends
        if m:
            parts.append(s[self.i:m.end()])
            self.i = m.end()
        lead = len(parts)   # a tilde right here is the home folder
        while self.i < n and s[self.i] not in META:
            c = s[self.i]
            quoted = quoted or c in '\\\'"$~'
            if c == '\\':
                parts.append(s[self.i + 1:self.i + 2].replace('\n', ''))   # a backslash-newline is gone
                self.i += 2
            elif c == "'":
                j = s.find("'", self.i + 1)
                if j < 0:
                    raise Doubt('open quote')
                parts.append(s[self.i + 1:j])
                self.i = j + 1
            elif c == '"':
                self.read_dq(parts, w.holes)
            elif c == '$':
                self.read_dollar(parts, w.holes, False)
            elif c == '`':
                raise Doubt('backticks')
            elif c == '~' and len(parts) == lead:
                j = self.i + 1
                while j < n and s[j] not in META and s[j] not in '/:':
                    j += 1
                parts.append(self.var('HOME') if j == self.i + 1 else None)   # ~user, ~+, ~-: unknown
                self.i = j
            else:
                w.glob = w.glob or c in '*?[{'
                parts.append(c)
                self.i += 1
        w.end, w.plain = self.i, not quoted
        w.value = None if None in parts else ''.join(parts)
        w.avalue = None if w.name is None or None in parts[1:] or old is None else old + ''.join(parts[1:])
        return w

    def read_dq(self, parts, holes):
        s = self.s
        self.i += 1
        while True:
            if self.i >= self.n:
                raise Doubt('open quote')
            c = s[self.i]
            if c == '"':
                self.i += 1
                return
            if c == '`':
                raise Doubt('backticks')
            if c == '\\' and s[self.i + 1:self.i + 2] in ('$', '`', '"', '\\', '\n'):
                parts.append(s[self.i + 1].replace('\n', ''))
                self.i += 2
            elif c == '$':
                self.read_dollar(parts, holes, True)
            else:
                parts.append(c)
                self.i += 1

    def read_dollar(self, parts, holes, dq):
        s, i = self.s, self.i
        nxt, m = s[i + 1:i + 2], NAME.match(s, i + 1)
        value, self.i = None, i + 2
        if s.startswith('$((', i):
            self.i = self.skip_arith(i + 3)
        elif nxt == '[':   # $[...]: the arithmetic of zsh and old bash (a << in it is no heredoc)
            self.i = self.skip_arith(i + 2, ']')
        elif nxt == '(':
            self.subshell('subst')
            holes.append((i, self.i))
        elif nxt == '{':
            self.i = self.skip_brace(i + 2, dq)
            inner = s[i + 2:self.i - 1]
            value = self.var(inner) if NAME.fullmatch(inner) else None   # ${x:-y}, ${#x}, ${x[1]}: unknown
        elif nxt in ("'", '"') and not dq:   # $'...' (unknown) and $"..."
            self.i = i + 1
            if nxt == '"':
                self.read_dq(parts, holes)
                return
            j = i + 2
            while j < self.n and s[j] != "'":
                j += 2 if s[j] == '\\' else 1
            if j >= self.n:
                raise Doubt('open quote')
            self.i = j + 1
        elif m:
            value, self.i = self.var(m.group(0)), m.end()
        elif not nxt or nxt not in '0123456789@*#?$!-':
            value, self.i = '$', i + 1   # a lone $
        parts.append(value)

    def skip_brace(self, j, dq):
        """The end of the ${...} whose inside starts at j, past quotes and nested braces; in double quotes a ' is a
        letter (bash and zsh). A command in it ($(...), backticks) runs where we do not follow it."""
        depth = 1
        while j < self.n:
            c = self.s[j]
            if c == '`' or self.s.startswith('$(', j):
                raise Doubt('a command in ${...}')
            if c == '\\':
                j += 1
            elif c == '"' or c == "'" and not dq:
                j = self.s.find(c, j + 1)
                if j < 0:
                    raise Doubt('open quote')
            elif c in '{}':
                depth += 1 if c == '{' else -1
                if depth == 0:
                    return j + 1
            j += 1
        raise Doubt('open ${')

    def skip_arith(self, j, close=')'):
        """Past the )) of (( or $(( whose inside starts at j, or past the ] of $[ (close ]); in (( a ) and then no ) at
        its end is ( ( ...) ...), subshells."""
        pair, depth = ({'(': 1, ')': -1}, 2) if close == ')' else ({'[': 1, ']': -1}, 1)
        start = j
        while j < self.n:
            if self.s[j] == '`' or self.s.startswith('$(', j):
                raise Doubt('a command in arithmetic')
            depth += pair.get(self.s[j], 0)
            j += 1
            if close == ')' and depth == 1 and not self.s.startswith(')', j):
                raise Doubt('(( that is not arithmetic')
            if depth == 0:
                self.arith(self.s[start:j])
                return j
        raise Doubt('open ((' if close == ')' else 'open $[')

    def arith(self, text):
        """Arithmetic ((( x = 1 )), $((x++)), let x=1): the variables it assigns get unknown."""
        for found in ARITH_SET.findall(text):
            self.state.vars[''.join(found)] = None
