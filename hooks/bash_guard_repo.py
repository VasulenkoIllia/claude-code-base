"""bash_guard_repo: the folder checks of bash-guard-dirs.py (stdlib, 3.9+), split off for size. A folder is one-off
when it is under /tmp (/private/tmp) as written and with its links resolved, and the repo git finds there (if any yet)
has its git folder, common folder and remotes under /tmp too, with no include. A copy is risky when it may bring a
repo whose files are elsewhere."""
import glob
import os
import re

TMP = '/private/tmp'   # /tmp is a link to it
LN_FLAGS = re.compile(r'-[bdfhinrsvwFLPT]+')   # ln options without an argument (BSD and GNU)
GIT_INIT_ARG = {'-b', '--initial-branch', '--template', '--object-format', '--ref-format'}   # with a value
WALK_MAX = 2000        # entries of a copied folder to look through; a bigger one counts as risky
# config sections and core keys that run a program (an alias with !, an editor, a filter ...) or read a config or a
# remote url of elsewhere: in a repo config the repo is no one-off; in git -c or git config they link it
RUN_SECTIONS = ('alias', 'include', 'includeif', 'url', 'filter', 'credential', 'gpg', 'diff', 'merge', 'sequence',
                'pager', 'trailer', 'interactive')
RUN_CORE = ('editor', 'pager', 'fsmonitor', 'sshcommand', 'hookspath', 'askpass', 'gitproxy', 'worktree')
CORE_KEY = re.compile(r'(?:%s)\b' % '|'.join(RUN_CORE), re.I)
GIT_SET = re.compile(r'(?:%s)\.|core\.(?:%s)\b' % ('|'.join(RUN_SECTIONS), '|'.join(RUN_CORE)), re.I)   # their keys
# a write that puts the repo elsewhere or runs code on a commit
DOT_GIT = re.compile(r'(?:^|/)\.git(?:/(?:commondir|config(?:\.worktree)?|hooks(?:/.*)?|objects/info/alternates))?$',
                     re.I)
HEADER = re.compile(r'\[\s*([A-Za-z0-9.-]*)[^\]]*\]?\s*')
WRAP_DIR = re.compile(r'-C|--(?:chdir|prefix|cwd|dir|directory)\b')   # an option that runs a command elsewhere
LINK_SUB = {'push', 'clone', 'worktree', 'remote', 'submodule', 'subtree', 'svn', 'p4', 'send-email'}
GIT_OPT_ARG = {'-C', '-c', '--git-dir', '--work-tree', '--namespace', '--config-env', '--super-prefix', '--attr-source'}
OWNER_X = re.compile(r'0*[0-7]?7[0-7]{2}')   # a mkdir -m mode that leaves the owner rwx (a symbolic one: unknown)


def under(p):
    return p == TMP or p.startswith(TMP + '/')


def covers(g, d):
    """A removal of g (lower case) takes the folder d: d is g or inside it (APFS ignores case)."""
    d = d.lower()
    return d == g or d.startswith(g + '/')


def lexical_tmp(p):
    """p under /tmp or /private/tmp as written (.. resolved), as a /private/tmp path; else None."""
    p = os.path.normpath(p)
    if p == '/tmp' or p.startswith('/tmp/'):
        p = '/private' + p
    return p if under(p) else None


def physical_tmp(p):
    """The nearest existing folder of p is under /private/tmp also with links resolved."""
    while not os.path.lexists(p):
        p = os.path.dirname(p)
    return under(os.path.realpath(p))


def in_tmp(p):
    """p is under /tmp as written and with the links of its existing part resolved."""
    q = lexical_tmp(p)
    return q is not None and physical_tmp(q)


def url_ok(u, top):
    """A remote url that is a folder under /tmp (a bare repo of the test, say)."""
    if u.startswith('file://'):
        u = u[len('file://'):]
    if not u or u.startswith('~') or '://' in u or ':' in u.split('/')[0]:
        return False
    return in_tmp(os.path.join(top, u))


def headers(line):
    """The sections of the [headers] at the start of a config line (git reads them all) and the rest of the line."""
    heads, t = [], line.strip()
    while t[:1] == '[':
        m = HEADER.match(t)
        heads.append(m.group(1).lower().split('.')[0])
        t = t[m.end():]
    return heads, t


def config_ok(path, top):
    """No section or core key of RUN_SECTIONS and RUN_CORE in a repo config, and every remote url or pushurl a
    folder under /tmp."""
    section = ''
    with open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            heads, t = headers(line)
            if set(RUN_SECTIONS) & set(heads):
                return False
            section = heads[-1] if heads else section
            if section == 'core' and CORE_KEY.match(t):
                return False
            m = re.match(r'(url|pushurl)\s*=\s*(.*)$', t, re.I)
            if section == 'remote' and m and not url_ok(m.group(2).strip().strip('"'), top):
                return False
    return True


def repo_ok(top, g):
    """The repo of the .git g at top: its git folder, common folder (the main repo of a worktree) and remotes under
    /tmp."""
    try:
        if os.path.isdir(g):
            gd = os.path.realpath(g)
        else:
            with open(g, encoding='utf-8', errors='replace') as fh:
                m = re.match(r'gitdir:\s*(.*?)\s*$', fh.readline())
            if not m:
                return False
            gd = os.path.realpath(os.path.join(top, m.group(1)))
        common = gd
        if os.path.lexists(os.path.join(gd, 'commondir')):
            with open(os.path.join(gd, 'commondir'), encoding='utf-8', errors='replace') as fh:
                common = os.path.realpath(os.path.join(gd, fh.readline().strip()))
        return under(gd) and under(common) and all(
            not os.path.lexists(c) or config_ok(c, top)
            for c in (os.path.join(common, 'config'), os.path.join(gd, 'config.worktree')))
    except (OSError, ValueError):
        return False


def one_off(d):
    """git in folder d works in a one-off repo: d under /tmp, also with links resolved, and the repo git finds there
    (if any yet) has its files and remotes under /tmp."""
    p = lexical_tmp(d) if d else None
    if p is None or not physical_tmp(p):
        return False
    while not os.path.lexists(p):
        p = os.path.dirname(p)
    p = os.path.realpath(p)
    while True:   # the nearest .git, as git looks for it
        g = os.path.join(p, '.git')
        if os.path.lexists(g):
            return repo_ok(p, g)
        if p in (TMP, '/'):
            return True   # no repo yet: git init comes later in the command
        p = os.path.dirname(p)


def copy_risky(src):
    """A copy of src may bring a repo whose files are elsewhere: src is not there yet (the command makes it), is a
    link or a .git, or is a folder with a link or a .git of no one-off repo inside, or too big to look through."""
    if os.path.islink(src) or not os.path.exists(src) or os.path.basename(src).lower() == '.git':
        return True
    seen = 0
    for root, dirs, files in os.walk(src):
        seen += len(dirs) + len(files)
        if seen > WALK_MAX:
            return True
        for name in dirs + files:
            p = os.path.join(root, name)
            if os.path.islink(p) or (name.lower() == '.git' and not repo_ok(root, p)):
                return True
        dirs[:] = [d for d in dirs if d.lower() != '.git']
    return False


class Places:
    """For bash-guard-dirs' Guard (a ShellReader): where git runs and where a command puts files. It reads
    self.state.dir and self.sure (the command surely runs and ends before the next one) and keeps self.cache (folder ->
    one-off), self.links (lower case paths where ln or a risky copy put files) and self.changes, in order, what mkdir,
    a copy or git init make and what rm, rmdir or mv may remove: (path, made, with its parents (None: a copy, with
    what it brings inside), surely); a removed path is in lower case, None when we do not know it. It sets self.linked,
    self.list_risky for a mkdir or git init that may fail and self.removers, the functions whose body removes one."""

    def ok(self, d):
        if d not in self.cache:
            self.cache[d] = one_off(d)
        return self.cache[d]

    def join(self, base, v):
        if v is None or (base is None and not v.startswith('/')):
            return None
        return os.path.normpath(os.path.join(base or '/', v))

    def exists(self, d):
        """The folder d is surely there: the last change before that touches it is a mkdir, copy or git init that
        surely runs (with -p also a folder inside it), or none touches it and it is there now, one we may enter."""
        d = lexical_tmp(d) or d
        for p, made, tree, sure in reversed(self.changes):
            if made and sure and (p == d or tree and p.startswith(d + '/')):
                return True
            if not made and (p is None or covers(p, d)):
                return False
        return os.path.isdir(d) and os.access(d, os.X_OK)

    def there(self, d):
        """Something may be at d, so a plain mkdir of it fails: the last change before that touches it makes it, or
        none but a removal that may not run does and something is there now."""
        d = lexical_tmp(d) or d
        low = d.lower()
        for p, made, tree, sure in reversed(self.changes):
            q = p and p.lower()
            if made and (covers(q, d) if tree is None else q == low or tree and q.startswith(low + '/')):
                return True
            if not made and sure and p is not None and covers(p, d):
                return False
        return os.path.lexists(d)

    def via_link(self, d):
        """The folder d is a link that ln makes, a risky copy or inside one, so its files may be elsewhere (APFS
        ignores case)."""
        d = (lexical_tmp(d) or d).lower()
        return any(d == p or d.startswith(p + '/') for p in self.links)

    def real(self, v):
        """The path the kernel opens for v: the links on the way and a .. after them resolved (None: unknown)."""
        if v is None or self.state.dir is None and not v.startswith('/'):
            return None
        return os.path.realpath(os.path.join(self.state.dir or '/', v))

    def dot_far(self, w):
        """A write to a dot file or folder outside /tmp (~/.zshrc, ~/.gitconfig), also through a link or a .. after
        one, or to one we do not know (a glob, a link that ln makes): its text may outlive the command."""
        p = self.join(self.state.dir, w.value)
        if p is None:
            return any(c.startswith('.') and c not in ('.', '..') for c in (w.value or '.?').split('/'))
        if w.glob or self.via_link(p):
            return True
        real = self.real(w.value)
        if in_tmp(p) and under(real):
            return False
        return any(c.startswith('.') and c not in ('.', '..') for c in (p + '/' + real).split('/'))

    def into_git(self, w):
        """A write target in a .git (commondir, config, hooks, alternates), also through a link; unknown counts."""
        return w.value is None or w.glob or any(DOT_GIT.search(q) for q in (
            self.join(self.state.dir, w.value) or w.value, self.real(w.value) or ''))

    def place_of(self, cmdw, names):
        """Where git runs in this command (None when unknown): the folder, then each -C; git init makes its folder."""
        place, moved = self.state.dir, False
        for j, nm in enumerate(names):
            if nm == 'git':
                cdirs, sub, odd = self.git_call(cmdw, j + 1)
                place = None if moved or odd else place   # env -C <folder> git, npm --prefix, an unknown word
                for w in cdirs:   # chdir() takes .. after the links, unlike cd: unknown; a glob: unknown
                    place = None if w.glob or '..' in (w.value or '').split('/') else self.join(place, w.value)
                if sub < len(cmdw) and cmdw[sub].value == 'init':
                    self.git_init(cmdw[sub + 1:], place)
                elif sub < len(cmdw) and cmdw[sub].value == 'config':
                    self.git_config(cmdw[sub + 1:])
                break
            moved = moved or bool(WRAP_DIR.match(cmdw[j].value or ''))
        return place

    def git_call(self, cmdw, j):
        """The -C words of git ... <subcommand>, where the subcommand is and whether a word before it is unknown; a
        subcommand or an option that links the repo sets linked."""
        cdirs = []
        while j < len(cmdw):
            v = cmdw[j].value
            if v is None or not v.startswith('-'):
                self.linked = self.linked or v in LINK_SUB
                return cdirs, j, v is None
            key = v.split('=', 1)[1] if v.startswith('--config-env=') else None
            if v in ('-c', '--config-env') and j + 1 < len(cmdw):
                key = re.sub(r'[\'"\\]', '', self.text(cmdw[j + 1]))
            self.linked = self.linked or v.startswith(('--git-dir', '--work-tree', '--namespace')) or bool(
                key is not None and (GIT_SET.match(key) or '$' in key.split('=')[0]))
            if v == '-C' and j + 1 < len(cmdw):
                cdirs.append(cmdw[j + 1])
            j += 2 if v in GIT_OPT_ARG else 1
        return cdirs, j, False

    def git_config(self, args):
        """git config of a key of GIT_SET (alias.x '!cd ...', core.editor) or of one we do not know: linked."""
        ops = [w.value for w in args if not (w.value or '').startswith('-')][:3]   # [set] key value
        self.linked = self.linked or None in ops or any(GIT_SET.match(v) for v in ops)

    def ln(self, args):
        """The paths where ln makes links (for via_link); unknown ones, an option with an argument or a link inside a
        .git: linked."""
        k = 0
        while k < len(args) and LN_FLAGS.fullmatch(args[k].value or ''):
            k += 1
        if k < len(args) and args[k].value == '--':
            k += 1
        ops = [w.value for w in args[k:]]
        if None in ops or any(w.glob for w in args[k:]) or any(v.startswith('-') for v in ops):
            self.linked = True   # -t DIR, -S SUFFIX, long or late options, a name we do not know
            return
        dest = ops[-1] if len(ops) > 1 else '.'
        at = [os.path.join(dest, os.path.basename(v)) for v in ops[:-1] or ops]
        if len(ops) > 1 and os.path.basename(dest) not in ('', '.', '..'):
            at.append(dest)   # the link itself, unless dest is a folder
        at = [self.join(self.state.dir, p) for p in at]
        if None in at or any('.git' in p.lower().split('/') for p in at):
            self.linked = True
        else:
            self.links += [(lexical_tmp(p) or p).lower() for p in at]

    def copy(self, kind, args):
        """cp, mv, rsync or ditto: a destination in a .git or unknown links the repo; a risky source puts the
        destination with the links (for via_link)."""
        ops = [w for w in args if w.value is None or not w.value.startswith('-')]
        if any(w.value == '-t' and kind != 'rsync' or (w.value or '').startswith('--target') for w in args):
            self.linked = True   # -t DIR, --target-directory: a destination we do not follow
            return
        if len(ops) < 2:
            return   # with one operand it fails
        dest = self.join(self.state.dir, ops[-1].value)
        if dest is None or ops[-1].glob or '.git' in dest.lower().split('/'):
            self.linked = True
            return
        if any(self.copied_risky(w) for w in ops[:-1]):
            self.links.append((lexical_tmp(dest) or dest).lower())
        srcs = [None if w.glob else self.join(self.state.dir, w.value) for w in ops[:-1]]
        whole = kind not in ('cp', 'gcp', 'rsync') or any(
            re.fullmatch(r'-[a-zA-Z]*[rRa][a-zA-Z]*|--(?:recursive|archive)', w.value or '') for w in args)
        folder = self.sure and whole and None not in srcs and all(map(self.exists, srcs)) and self.exists(
            os.path.dirname(dest))   # a copy of folders surely leaves a folder: a cd into it may follow
        if kind in ('mv', 'gmv'):
            for p in srcs:
                self.removed(p, False)
        self.changes.append((lexical_tmp(dest) or dest, True, None, folder))

    def copied_risky(self, w):
        """A copy of the source word w may bring files of elsewhere (bash_guard_repo.copy_risky), also a link that ln
        or a risky copy of this command puts in it."""
        p = self.join(self.state.dir, w.value)
        if p is None:
            return True
        paths = glob.glob(p) if w.glob else [p]
        made = not w.glob and not os.path.lexists(p) and self.exists(p)   # a mkdir, git init or copy before makes it
        inside = any(q.startswith((lexical_tmp(s) or s).lower() + '/') for q in self.links for s in paths)
        return not paths or inside or any(self.via_link(q) for q in paths) or not made and any(
            copy_risky(q) for q in paths)

    def mkdir(self, args):
        """mkdir makes its folders when it surely runs; one that may fail (a folder that may be there, without -p a
        parent that may not be, a word we do not know, a folder not under /tmp with its links resolved) sets
        list_risky: a cd after it in its && list may not run. With -m a mode that is not rwx for the owner a cd into
        it may fail."""
        tree = any(re.fullmatch(r'-[mpv]*p[mpv]*|--parents', w.value or '') for w in args)
        k, mode = 0, '777'
        while k < len(args):
            w, k = args[k], k + 1
            if (w.value or '').startswith('-'):
                m = re.fullmatch(r'-[pv]*m(.*)|--mode(?:=(.*))?', w.value)
                if m:   # -m 700, -m700, --mode=700
                    mode = m.group(1) or m.group(2) or (args[k].value if k < len(args) else None)
                    k += not (m.group(1) or m.group(2))
                continue
            d = None if w.glob else self.join(self.state.dir, w.value)
            fails = d is None or not in_tmp(d) or (os.path.lexists(d) and not os.path.isdir(d) if tree else
                                                   self.there(d) or not self.exists(os.path.dirname(d)))
            self.list_risky = self.list_risky or fails
            if d is not None:
                sure = self.sure and not fails and bool(OWNER_X.fullmatch(mode or ''))
                self.changes.append((lexical_tmp(d) or d, True, tree, sure))

    def remove(self, kind, args):
        """rm or rmdir: what it may remove (a glob or a word we do not know: anything; rmdir -p: the parents too);
        surely: an rm -r of a known path that surely runs."""
        whole = kind == 'rm' and any(re.fullmatch(r'-[a-zA-Z]*[rR][a-zA-Z]*|--recursive', w.value or '') for w in args)
        up = kind == 'rmdir' and any(re.fullmatch(r'-[pv]*p[pv]*|--parents', w.value or '') for w in args)
        for w in args:
            if not (w.value or '').startswith('-'):
                p = None if w.glob else self.join(self.state.dir, w.value)
                self.removed(p, whole and self.sure and p is not None)
                while up and p and p != '/':
                    p = os.path.dirname(p)
                    self.removed(p, False)

    def removed(self, p, sure):
        """p (None: we do not know it) may be gone after this command; in a function body after each call of it."""
        self.removers.update(f.name for f in self.frames if f.kind == 'func')
        self.changes.append((p and (lexical_tmp(p) or p).lower(), False, False, sure))

    def redirect_fails(self, op, w):
        """A redirection that may fail, so its command does not run: a file to read that is not there, a file to
        write that is a folder or in a folder that may not be there, a word we do not know (2>&1, <<< do not)."""
        if op == '<<<' or op in ('>&', '<&') and re.fullmatch(r'\d*-?', w.value or ''):
            return False
        p = None if w.glob else self.join(self.state.dir, w.value)
        if p is None:
            return True
        return not os.path.exists(p) if op == '<' else os.path.isdir(p) or not self.exists(os.path.dirname(p))

    def git_init(self, args, place):
        """git init [dir] makes dir with its parents, like mkdir -p (it fails on a file or through a link out of
        /tmp: list_risky); --separate-git-dir puts the repo elsewhere."""
        d, k = None, 0
        while k < len(args):
            v = args[k].value
            if v is None or args[k].glob:
                return   # a folder we do not know is not counted as made
            if v.startswith('--separate-git-dir'):
                self.linked = True
                return
            if not v.startswith('-'):
                d = v
            k += 2 if v in GIT_INIT_ARG else 1
        d = self.join(place, d) if d else None
        if d:
            fails = not in_tmp(d) or os.path.lexists(d) and not os.path.isdir(d)
            self.list_risky = self.list_risky or fails
            self.changes.append((lexical_tmp(d) or d, True, True, self.sure and not fails))
