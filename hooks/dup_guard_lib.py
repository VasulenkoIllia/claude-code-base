"""dup_guard_lib: the pure text part of dup-guard.py (definitions, tokens, similarity notes, the message).
No I/O, no git; imported by dup-guard.py from the same folder."""
import difflib
import json
import re
import zlib

NEUTRAL_PREFIX = re.compile(r'^(to|get|as|format|fmt)(?=[A-Z_])')
DEF_RE = re.compile(
    r'^(?P<ind>[ \t]*)(?P<exp>export[ \t]+(?:default[ \t]+)?)?(?:declare[ \t]+)?'
    r'(?:(?:async[ \t]+)?function[ \t]*\*?[ \t]*(?P<fn>[A-Za-z_$][\w$]*)'
    r'|(?:abstract[ \t]+)?class[ \t]+(?P<cls>[A-Za-z_$][\w$]*)'
    r'|(?:const|let|var)[ \t]+(?P<var>[A-Za-z_$][\w$]*)[ \t]*(?::[^=;\n]{1,200})?=(?![=>])[ \t]*(?P<rhs>[^\n]*))',
    re.M)
ARROW_WIN = re.compile(r'^\s*(?:async\s*)?(?:<[^>\n]{1,80}>\s*)?\([^;]{0,400}?\)\s*(?::\s*[^=;{]{1,160})?=>', re.S)
FUNC_RHS = re.compile(r'^(?:async[ \t]+)?(?:function\b|[A-Za-z_$][\w$]*[ \t]*=>|(?:React\.)?(?:memo|forwardRef)\b)')
TOKEN = re.compile(r'[A-Za-z_$][\w$]*|\d+|[^\s\w]')
IDENT = re.compile(r'^[A-Za-z_$][\w$]*$')
NOISE = {'export', 'default', 'async', 'declare', 'NAME'}
# comments, /regex/ after an operator, '...', "..." and `...`; every branch has exclusive alternatives (linear time)
LITERAL = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/'
                     r'|(?<=[(,=:\[!&|?{};])[ \t]*/(?![/*])(?:\\.|\[(?:\\.|[^\]\\\n])*\]|[^/\\\n\[])+/[a-z]*'
                     r'|\'(?:\\.|[^\'\\\n])*\'|"(?:\\.|[^"\\\n])*"|`(?:[^`\\$]|\\[\s\S]|\$(?!\{)|\$\{[^}`]*\})*`')
QUOTED = re.compile(r'\'(?:\\.|[^\'\\\n])*\'|"(?:\\.|[^"\\\n])*"')
TEMPLATE_EXPR = re.compile(r'\$\{([^}`]*)\}')
BODY_LINES = 40
LINE_MAX, BODY_MAX = 2000, 8000   # chars: a minified or hostile line never reaches the regexes whole
SIG_KEYWORDS = set('export default declare async function class abstract extends implements const let var readonly '
                   'keyof typeof infer is asserts unique new in of as satisfies'.split())
CAP = 3              # hit lines in the message
MAX_OUT = 1200       # bytes of the printed JSON


def definitions(text):
    """{name: (offset, exported)} for top-level function-like and class definitions in text."""
    out = {}
    for m in DEF_RE.finditer(text or ''):
        if m.group('ind'):
            continue   # a nested local cannot be imported
        name, rhs = m.group('fn') or m.group('cls'), m.group('rhs') or ''
        if not name and m.group('var') and (FUNC_RHS.match(rhs) or (rhs.lstrip().startswith(('(', 'async', '<'))
                                            and ARROW_WIN.match(text[m.start('rhs'):m.start('rhs') + 600]))):
            name = m.group('var')
        if name and name not in out:
            out[name] = (m.start(), bool(m.group('exp')))
    return out


def body_lines(lines, start):
    """Lines of the definition that starts at lines[start]: until the closing line at the same indent."""
    if start >= len(lines):
        return []
    first = lines[start]
    ind = len(first) - len(first.lstrip())
    out = [first]
    for ln in lines[start + 1:start + BODY_LINES]:
        s = ln.strip()
        if not s:
            out.append(ln)
            continue
        cur = len(ln) - len(ln.lstrip())
        if cur < ind or (cur == ind and not s.startswith(('}', ')', ']', '.', '?', ':', '|', '&'))):
            break
        out.append(ln)
        if cur == ind:
            break
    return out


def mask(text):
    """Comments out; a string literal -> one opaque token (equal literals stay equal, their words never reach the
    model, so a secret in a body stays out of the context); a template keeps its ${...} code."""
    def opaque(s):
        return ' %s ' % chr(0xE000 + zlib.crc32(s.encode('utf-8', 'replace')) % 6400)   # a private-use char

    def sub(m):
        s = m.group(0).lstrip()
        if s[0] == '`':
            return opaque(TEMPLATE_EXPR.sub('', s)) + ' '.join(
                QUOTED.sub(lambda q: opaque(q.group(0)), e) for e in TEMPLATE_EXPR.findall(s))
        return ' ' if s[:2] in ('//', '/*') else opaque(s)
    text = re.sub(r'`[\s\S]*', ' ', LITERAL.sub(sub, text))   # a template cut by BODY_LINES: drop the rest
    return re.sub(r'[\'"][^\n]*', ' ', text)                  # a quote left over (regex literal): drop the line rest


def tokens(lines, name):
    text = '\n'.join(ln[:LINE_MAX] for ln in lines)[:BODY_MAX]
    return ['NAME' if t == name else t for t in TOKEN.findall(mask(text))][:300]


def token_diff(have, new, limit=2):
    """Up to `limit` 'old→new' identifier pairs, so 95% similar is not read as 'the same'."""
    out = []
    for op, a1, a2, b1, b2 in difflib.SequenceMatcher(None, have, new, autojunk=False).get_opcodes():
        if op == 'equal':
            continue
        a = [t for t in have[a1:a2] if IDENT.match(t) and t not in NOISE]
        b = [t for t in new[b1:b2] if IDENT.match(t) and t not in NOISE]
        if not (a or b):
            continue
        item = ('%s→%s' % (' '.join(a[:2]) or '∅', ' '.join(b[:2]) or '∅'))[:60]
        if item not in out:
            out.append(item)
        if len(out) >= limit:
            break
    return out


def part(path):
    """Top-level part of a repo path: 'server', 'src', 'apps/web'; '.' for a file in the root."""
    s = path.split('/')
    if s[0] in ('apps', 'packages', 'services') and len(s) > 2:
        return s[0] + '/' + s[1]
    return s[0] if len(s) > 1 else '.'


def name_pattern(name):
    """(normalized key or None, grep alternative). Prefix/underscore-insensitive only for specific names."""
    core = NEUTRAL_PREFIX.sub('', name)
    parts = re.findall(r'[A-Z]+(?![a-z])|[A-Z]?[a-z0-9]+|[A-Z]', core.replace('$', ''))
    if len(parts) >= 2 and len(core) >= 6:
        return core.replace('_', '').lower(), '_?'.join(re.escape(p.lower()) for p in parts)
    return None, re.escape(name)


def signature(line):
    """The definition line up to its body: literals as '…', no comments, no free text after the name."""
    s = LITERAL.sub(lambda m: ' ' if m.group(0).lstrip()[:2] in ('//', '/*') else
                    m.group(0)[:len(m.group(0)) - len(m.group(0).lstrip())] + '\0', line[:LINE_MAX].strip())
    s = re.sub(r'/\*.*|//.*', '', s).strip()   # an unclosed comment
    for stop in ('{', '=>'):
        i = s.find(stop)
        if i > 0:
            s = s[:i].rstrip() + (' =>' if stop == '=>' else '')
            break
    s = re.sub(r'\s*[\'"`].*', '…', s).replace('\0', "'…'")   # an unclosed literal: cut from it
    plain = False
    for m in re.finditer(r'[A-Za-z_$][\w$]*|\S', s):   # two plain words in a row are no TS signature: free text
        word = bool(IDENT.match(m.group(0))) and m.group(0) not in SIG_KEYWORDS
        if word and plain:
            s = s[:m.start()].rstrip() + ' …'
            break
        plain = word
    return s[:100] + ('…' if len(s) > 100 else '')


def exported_elsewhere(lines, name):
    """True when the file exports name apart from its definition line: export { name }, export default name,
    module.exports = { name } or = name, exports.name = ..."""
    n = re.escape(name)
    return bool(re.search(r'\bexport\s*\{[^}]{0,%d}?\b%s\b|\bexport\s+default\s+%s\b|\bmodule\.exports\s*=\s*(?:\{[^}]{0,%d}?'
                          r'\b%s\b|%s\b)|\bexports\.%s\s*=' % (LINE_MAX, n, n, LINE_MAX, n, n, n),
                          '\n'.join(ln[:LINE_MAX] for ln in lines)))


def hit_line(n, h):
    label = n if h['how'] == 'same' else '%s (similar name %s)' % (n, h['hname'])
    notes = ['similarity %d%%' % round(h['sim'] * 100)]
    if h['diff']:
        notes.append('differs: ' + ', '.join(h['diff']))
    if h['exported'] is False:   # None: the file was not read, so no claim
        notes.append('not exported')
    if h['cross']:
        notes.append('other part: %s/' % h['cross'])
    return '%s: %s:%d `%s` (%s)' % (label, h['path'], h['line'], h['sig'], '; '.join(notes))


def as_json(text):
    return json.dumps({'hookSpecificOutput': {'hookEventName': 'PostToolUse', 'additionalContext': text}},
                      ensure_ascii=False, separators=(',', ':'))


def render(rel, fired, queues, extraction):
    """The printed JSON, at most MAX_OUT bytes: every name gets a line first, then lines are dropped."""
    lines, i = [], 0
    while len(lines) < CAP and any(i < len(q) for _, q in queues):
        for n, q in queues:
            if i < len(q) and len(lines) < CAP:
                lines.append(hit_line(n, q[i]))
        i += 1
    total = sum(len(q) for _, q in queues)
    similar = any(h['how'] != 'same' for _, q in queues for h in q)
    head = 'dup-guard: %s adds %s; already present with the %s name:' % (rel, ', '.join(fired[:5]),
                                                                        'same or a similar' if similar else 'same')
    # facts only (hooks docs); nothing that asks to change or remove existing code (clean-code.md)
    tail = ('The new file in a shared folder exports these names; the listed copies stay in place for now.' if extraction
            else 'Similarity by body tokens; the same name does not guarantee the same behavior.')
    while True:
        more = total - len(lines)
        text = head + ''.join('\n- ' + ln for ln in lines) + ('\n(%d more)' % more if more else '') + '\n' + tail
        out = as_json(text)
        if len(out.encode('utf-8')) <= MAX_OUT or len(lines) == 1:
            break
        lines.pop()
    cut = len(text)
    while len(out.encode('utf-8')) > MAX_OUT:   # one line is still too long (long paths): cut the end, keep the prefix
        cut = cut * 9 // 10
        out = as_json(text[:cut] + '…')
    return out
