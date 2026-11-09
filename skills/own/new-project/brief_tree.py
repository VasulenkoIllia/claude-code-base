#!/usr/bin/env python3
"""The brief folder of a start from a client's brief (skill /new-project): its regular files, its problems, the copy of
the files the owner named into it, and the conversion of its office documents to text.

`brief_check.py tree`, `save` and `convert` use it for the model, scaffold.py takes the same list for its brief mode,
and `brief_check.py --self-test` runs tree_test.
"""
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unicodedata

# Characters a file name must not hold: controls, format and bidi marks, line separators, private use, unassigned
BAD_CATEGORIES = {'Cc', 'Cf', 'Cn', 'Co', 'Cs', 'Zl', 'Zp'}
# Files the owner doesn't see or can't rename (Finder state and folder icon, Windows thumbnails and settings, Office
# lock files): neither listed nor checked
JUNK = re.compile(r'\.DS_Store\Z|Icon\r\Z|Thumbs\.db\Z|desktop\.ini\Z|~\$.*\.(do[ct][xm]?|xls[xm]?|ppt[xm]?|rtf)\Z',
                  re.I | re.S)
# macOS metadata copies next to the real files (AppleDouble, the metadata folder of a zip): checked, never listed
COPIES = re.compile(r'\._')
COPIES_DIR = '__MACOSX'
# Claude Code loads these as instructions, not as data, when it reads a file next to or below them
INSTRUCTIONS = re.compile(r'(claude(\.local)?\.md|agents\.md|gemini\.md|\.claude|\.cursorrules|\.windsurfrules)\Z',
                          re.I)
# Office documents the Read tool can't read: converted with macOS textutil
OFFICE = re.compile(r'.*\.(docx?|rtf|odt)\Z', re.I | re.S)
CONVERT_TIMEOUT_S = 120


def entry_problem(path, name):
    """What is wrong with one entry of the brief folder, or None."""
    try:
        mode = os.lstat(path).st_mode
    except OSError as e:
        return 'cannot read (%s)' % e.strerror
    kinds = []
    if stat.S_ISLNK(mode):
        kinds.append('symlink')
    elif not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
        kinds.append('not a regular file')
    if any(unicodedata.category(c) in BAD_CATEGORIES for c in name):
        kinds.append('control or invisible character in the name')
    if INSTRUCTIONS.match(name):
        kinds.append('an instruction file that Claude Code would load')
    return ', '.join(kinds) or None


def scan(top):
    """(regular files to read, problems) of the brief folder top; nothing behind a symlink is listed or read."""
    top = os.path.normpath(top)
    if not os.path.lexists(top):
        return [], []
    problem = entry_problem(top, '')
    if problem or not os.path.isdir(top):
        return [], ['%s: %s' % (ascii(top), problem or 'not a folder')]
    files, problems = [], []

    def unreadable(e):
        problems.append('%s: cannot read (%s)' % (ascii(e.filename), e.strerror))

    for dirpath, dirnames, filenames in os.walk(top, onerror=unreadable):
        copies = COPIES_DIR in os.path.relpath(dirpath, top).split(os.sep)
        plain = set(filenames)
        for name in sorted(dirnames) + sorted(n for n in filenames if not JUNK.match(n)):
            path = os.path.join(dirpath, name)
            problem = entry_problem(path, name)
            if problem:
                problems.append('%s: %s' % (ascii(path), problem))
            elif name in plain and not copies and not COPIES.match(name):
                files.append(path)
    return files, problems


def private_part(rel):
    """A repository's own folder or an env file: neither belongs in a brief, however it was named."""
    return any(p == '.git' or (p.startswith('.env') and p != '.env.example') for p in rel.lower().split(os.sep))


def named_files(path):
    """(source, path under the brief folder) of one path the owner named, and its problems. A folder is listed by
    scan(), so a link stays out in the same way; the name itself gets the checks of an entry of the brief folder."""
    name = os.path.basename(path.rstrip(os.sep))
    problem = entry_problem(path, name)
    if not os.path.isabs(path) or name in ('', '.', '..'):
        problem = 'not a full path'
    elif private_part(name):
        problem = 'a .git folder or an .env file stays out of the brief'
    if problem or not (os.path.isfile(path) or os.path.isdir(path)):
        return [], ['%s: %s' % (ascii(path), problem or 'neither a file nor a folder')]
    if not os.path.isdir(path):
        return [(path, name)], []
    files, problems = scan(path)
    rels = [(f, os.path.relpath(f, path)) for f in files]
    problems += ['%s: a .git folder or an .env file stays out of the brief' % ascii(f) for f, r in rels
                 if private_part(r)]
    return [(f, os.path.join(name, r)) for f, r in rels], problems


def link_on_the_way(brief_dir, rel):
    """A link in the brief folder itself or between it and a file to write, which the copy would follow."""
    path, parts = brief_dir, rel.split(os.sep)[:-1]
    for part in [''] + parts:
        path = os.path.join(path, part) if part else path
        if os.path.islink(path):
            return path
    return None


def save_pairs(paths, brief_dir):
    """(source, destination) of every file of the owner's paths, and the problems of the whole list."""
    brief_dir = os.path.normpath(brief_dir)  # with an ending slash islink() would look through the link
    pairs, problems = [], []
    for path in paths:
        files, found = named_files(path)
        pairs += files
        problems += found
    if not pairs and not problems:
        problems.append('nothing to copy')
    links = {link_on_the_way(brief_dir, rel) for _, rel in pairs} | {link_on_the_way(brief_dir, 'x')}
    problems += ['%s: a link in the brief folder' % ascii(link) for link in sorted(links - {None})]
    rels = [rel for _, rel in pairs]
    problems += ['%s: named twice' % ascii(rel) for rel in sorted(set(rels)) if rels.count(rel) > 1]
    problems += ['%s: already in the brief folder' % ascii(rel) for rel in rels
                 if os.path.lexists(os.path.join(brief_dir, rel))]
    return [(source, os.path.join(brief_dir, rel)) for source, rel in pairs], problems


def copy_file(source, dest):
    """A source replaced by a link since scan() is not read, a file that is there is not overwritten, and a copy that
    fails leaves no part of a file: a later session would read it as whole."""
    with os.fdopen(os.open(source, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as src, open(dest, 'xb') as out:
        try:
            shutil.copyfileobj(src, out)
        except BaseException:
            os.unlink(dest)
            raise


def save(paths, brief_dir):
    """Copies the owner's files and folders into the brief folder; (copied files, problems). A problem copies nothing,
    a failure midway removes what this run copied, and nothing that is there is overwritten."""
    pairs, problems = save_pairs(paths, brief_dir)
    if problems:
        return [], problems
    done = []
    try:
        for source, dest in pairs:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            copy_file(source, dest)
            done.append(dest)
    except BaseException:
        for dest in done:
            os.unlink(dest)
        raise
    return done, []


def convert(files, out_dir):
    """(file, text file or None) for each office document of files: textutil runs without a shell, so a file name never
    reaches a command line, and loads nothing a document points to (an HTML saved as .doc may hold images and links);
    None when the file is no longer a regular file, or textutil fails or writes nothing (it exits 0 on some
    failures)."""
    done = []
    for path in (p for p in files if OFFICE.match(os.path.basename(p))):
        fd, out = tempfile.mkstemp(prefix='brief-', suffix='.txt', dir=out_dir)
        os.close(fd)
        try:
            # A file replaced by a link since scan() is not read
            ok = stat.S_ISREG(os.lstat(path).st_mode)
            if ok:
                run = subprocess.run(['textutil', '-convert', 'txt', '-noload', '-nostore', '-output', out, '--',
                                      os.path.abspath(path)],
                                     capture_output=True, timeout=CONVERT_TIMEOUT_S, check=False)
                ok = run.returncode == 0 and os.path.getsize(out) > 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        if not ok and os.path.lexists(out):
            os.unlink(out)
        done.append((path, out if ok else None))
    return done


def touch(path, text=''):
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(text)


def tree_test():
    """scan lists the regular files without junk and macOS copies and reports each kind of problem on its own; convert
    turns an rtf into text and reports a broken docx."""
    fails = []
    with tempfile.TemporaryDirectory() as tmp:
        top, outside = os.path.join(tmp, 'brief'), os.path.join(tmp, 'outside.txt')
        touch(outside)
        for rel in ('tz.pdf', 'scan/page 1.png', 'ТЗ клієнта.docx', '~$100 прайс.pdf', '.DS_Store', 'Icon' + chr(13),
                    '~$ТЗ.docx', '~$план.xlsm', '~$ТЗ.rtf', '._tz.pdf', '__MACOSX/scan/x.png'):
            os.makedirs(os.path.dirname(os.path.join(top, rel)), exist_ok=True)
            touch(os.path.join(top, rel))
        files, problems = scan(top)
        want = sorted(os.path.join(top, rel) for rel in ('tz.pdf', 'scan/page 1.png', 'ТЗ клієнта.docx',
                                                         '~$100 прайс.pdf'))
        if sorted(files) != want or problems:
            fails.append('brief_tree: %s and %s, expected %s' % (files, problems, want))
        # Newline, bidi override, zero width space, line separator, private use; junk names with a newline; instructions
        cases = [('link.pdf', lambda p: os.symlink(outside, p)), ('scan', lambda p: os.symlink(tmp, p)),
                 ('pipe', os.mkfifo), ('.claude', os.mkdir)]
        cases += [(name, touch) for name in ['a%sb.pdf' % chr(c) for c in (10, 0x202e, 0x200b, 0x2028, 0xe000)]
                  + ['.DS_Store' + chr(10), 'CLAUDE.md', 'claude.local.md', 'AGENTS.md', 'GEMINI.md', '.cursorrules',
                     '.windsurfrules']]
        for no, (name, make) in enumerate(cases):
            case = os.path.join(tmp, 'case%d' % no)
            os.makedirs(case)
            make(os.path.join(case, name))
            if not scan(case)[1]:
                fails.append('brief_tree: no problem for %s' % ascii(name))
        # Unassigned and a lone surrogate: APFS refuses such names, other file systems may not
        fails += ['brief_tree: no problem for %s' % ascii(chr(c)) for c in (0x378, 0xd800)
                  if not entry_problem(outside, 'a%sb.pdf' % chr(c))]
        # A folder that can't be listed, and one whose entries can't be looked up; root reads any folder
        for mode in (0o000, 0o444) if os.geteuid() else ():
            locked = os.path.join(tmp, 'locked%o' % mode, 'scan')
            os.makedirs(locked)
            touch(os.path.join(locked, 'x.pdf'))
            os.chmod(locked, mode)
            problems = scan(os.path.dirname(locked))[1]
            os.chmod(locked, 0o755)
            if not problems:
                fails.append('brief_tree: no problem for a folder with mode %o' % mode)
        os.symlink(top, os.path.join(tmp, 'brief-link'))
        for rel, want_problem in (('none', False), ('brief-link', True), ('outside.txt', True)):
            files, problems = scan(os.path.join(tmp, rel))
            if files or bool(problems) != want_problem:
                fails.append('brief_tree: %s gives %s and %s' % (rel, files, problems))
        fails += save_test(tmp)
        if shutil.which('textutil'):
            docs, out = os.path.join(tmp, 'docs'), os.path.join(tmp, 'out')
            os.makedirs(docs)
            os.makedirs(out)
            touch(os.path.join(docs, 'tz.rtf'), '{%srtf1%sansi brief text}' % (chr(92), chr(92)))
            touch(os.path.join(docs, 'broken.docx'), 'PK' + chr(3) + chr(4) + 'not a zip')  # textutil exits 0
            touch(os.path.join(docs, 'notes.txt'), 'read as it is')
            # A listed file replaced by a link before convert() runs
            swapped = os.path.join(tmp, 'swapped.rtf')
            os.symlink(os.path.join(docs, 'tz.rtf'), swapped)
            got = {os.path.basename(f): t for f, t in convert(scan(docs)[0] + [swapped], out)}
            with open(got.get('tz.rtf') or outside, encoding='utf-8') as fh:
                text = fh.read()
            if ('brief text' not in text or set(got) != {'tz.rtf', 'broken.docx', 'swapped.rtf'}
                    or got['broken.docx'] is not None or got['swapped.rtf'] is not None or len(os.listdir(out)) != 1):
                fails.append('brief_tree: convert gives %s, %r' % (got, text))
    return fails


def save_test(tmp):
    """save copies a file and a folder, refuses links on either side, instruction files, relative paths, private files
    and a name given twice, copying nothing then, and overwrites nothing."""
    fails = []
    top, brief = os.path.join(tmp, 'owner'), os.path.join(tmp, 'saved', 'brief')
    os.makedirs(os.path.join(top, 'docs', 'scan'))
    touch(os.path.join(top, 'tz.md'), 'tz')
    touch(os.path.join(top, 'docs', 'scan', 'a.txt'), 'a')
    touch(os.path.join(top, 'docs', '.DS_Store'))
    os.symlink(os.path.join(top, 'tz.md'), os.path.join(top, 'link.md'))
    touch(os.path.join(top, 'CLAUDE.md'))
    touch(os.path.join(top, 'other.md'), 'x')
    os.makedirs(os.path.join(top, 'twice'))
    touch(os.path.join(top, 'twice', 'tz.md'), 'x')
    os.makedirs(os.path.join(top, '.claude'))
    touch(os.path.join(top, '.claude', 'settings.json'))
    os.makedirs(os.path.join(top, 'repo', '.git'))
    touch(os.path.join(top, 'repo', '.git', 'config'))
    os.makedirs(os.path.join(top, 'env'))
    touch(os.path.join(top, 'env', '.env.local'), 'A=1')
    os.makedirs(os.path.join(top, 'upper', '.GIT'))
    touch(os.path.join(top, 'upper', '.GIT', 'config'))
    good = [os.path.join(top, 'tz.md'), os.path.join(top, 'docs')]
    for bad in (os.path.join(top, 'link.md'), os.path.join(top, 'CLAUDE.md'), os.path.join(top, 'none.md'),
                os.path.join(top, '.claude'), os.path.join(top, 'repo'), os.path.join(top, 'env'),
                os.path.join(top, 'upper'), os.path.join(top, 'twice', 'tz.md'), os.path.join(top, 'env', '.env.local'),
                'other.md', '..', os.path.join(top, 'docs', '..'), os.path.join(top, 'docs', '.')):
        done, problems = save(good + [bad], brief)
        if done or not problems or os.path.exists(brief):
            fails.append('brief_tree: save of %s gives %s and %s' % (bad, done, problems))
    elsewhere = os.path.join(tmp, 'elsewhere')
    os.makedirs(elsewhere)
    linked = os.path.join(tmp, 'saved', 'linked')
    os.makedirs(os.path.dirname(linked), exist_ok=True)
    os.symlink(elsewhere, linked)
    inner = os.path.join(tmp, 'saved', 'inner')
    os.makedirs(inner)
    os.symlink(elsewhere, os.path.join(inner, 'docs'))
    for where in (linked, linked + os.sep, os.path.join(linked, '.'), inner):
        if not save(good, where)[1] or os.listdir(elsewhere):
            fails.append('brief_tree: save wrote through a link in %s' % where)
    done, problems = save(good, brief)
    if problems or sorted(os.path.relpath(d, brief) for d in done) != ['docs/scan/a.txt', 'tz.md']:
        fails.append('brief_tree: save gives %s and %s' % (done, problems))
    if not save([os.path.join(top, 'tz.md')], brief)[1]:
        fails.append('brief_tree: a second save of the same file was not refused')
    os.makedirs(os.path.join(top, 'empty'))
    touch(os.path.join(top, 'empty', '.DS_Store'))
    for nothing in ([], [os.path.join(top, 'empty')]):
        if not save(nothing, brief)[1]:
            fails.append('brief_tree: a save of nothing reads as a success: %s' % nothing)
    return fails + save_failure_test(tmp, top)


def save_failure_test(tmp, top):
    """A failure midway removes what this run copied, and a link in place of a source is not read."""
    fails = []
    brief = os.path.join(tmp, 'midway', 'brief')
    real, calls = shutil.copyfileobj, []

    def failing(src, out):
        calls.append(src)
        if len(calls) == 2:
            out.write(b'part')
            raise OSError('disk')
        return real(src, out)
    shutil.copyfileobj = failing
    try:
        save([os.path.join(top, 'tz.md'), os.path.join(top, 'other.md')], brief)
        fails.append('brief_tree: a failing copy went unseen')
    except OSError:
        pass
    finally:
        shutil.copyfileobj = real
    left = [f for _, _, files in os.walk(brief) for f in files]
    if left:
        fails.append('brief_tree: a failure midway left %s' % left)
    try:
        copy_file(os.path.join(top, 'link.md'), os.path.join(tmp, 'midway', 'x'))
        fails.append('brief_tree: a link in place of a source was read')
    except OSError:
        pass
    return fails
