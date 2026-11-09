#!/usr/bin/env python3
"""Checks for a start from a client's brief (skill /new-project, brief.md).

  python3 -I brief_check.py tree DIR
  python3 -I brief_check.py save PATHS_FILE DIR
  python3 -I brief_check.py convert DIR OUT_DIR
  python3 -I brief_check.py docs (--names FILE | --no-names) FILE...
  python3 -I brief_check.py --self-test

tree: the brief folder before it is read (brief_tree.py). Prints its regular files, one path per line (no .DS_Store,
Finder Icon, Thumbs.db, desktop.ini, Office ~$ lock files, macOS ._* and __MACOSX copies), then the count; exit 0, also
when DIR does not exist (0 files). Exit 1, one line per problem with the name escaped: a symlink (never followed),
a file that is not regular, a name with control or invisible characters, a folder that can't be read, an instruction
file Claude Code would load (CLAUDE.md, AGENTS.md, .claude). scaffold.py takes the same list for its brief mode.
save: the files and folders the owner named, one absolute path per line of the UTF-8 file PATHS_FILE, copied into DIR
(a folder under its own name, junk and macOS copies left out). No shell is involved, nothing is overwritten, and a
problem of tree in any of them copies nothing: exit 1, one line per problem; exit 2 when a file can't be read or written.
convert: the docx, doc, rtf and odt files of that list to text in OUT_DIR with macOS textutil, no shell involved and
nothing loaded that a document points to. Prints `text file <- file` or `FAILED file`; exit 1 on a problem of tree,
2 when OUT_DIR is inside DIR or can't be written.
docs: the docs written from the brief, for what must not reach git. Prints `file:line: kinds` for every hit, never the
text (it may be a secret or personal data); a line over 10 000 characters is a hit of its own. Exit 0: clean; 1: hits;
2: a file or the names file can't be read, the names file holds no name, or neither --names nor --no-names is given.
--names: a UTF-8 file, one name per line (the client's name and brand, people's names from the brief), as written or
as a stem. Case, apostrophes, stress marks, invisible characters and Latin or Greek look-alike letters are ignored;
a final vowel, ь, й or -ий is dropped, a final к, г or х also gives its ц, з or с form, and -ець, -єць or -ок the form
without the vowel, so «Ромашка» finds «Ромашці», «Коваль» «Ковалем», «Кравець» «Кравця». A stem of 5 letters or more
is found inside words, a shorter one only at the start of a word with up to 3 more letters («Анна»: «Анні», not
«налаштування»).
Not checked: street addresses, names outside --names, sums and numbers written in words.
"""
import argparse
import contextlib
import functools
import io
import os
import re
import sys
import tempfile
import unicodedata

# A docs line longer than this is no prose: reported instead of checked, so no pattern runs over a megabyte of base64
MAX_LINE = 10000
# The bot type's own docs name the Telegram account that issues tokens; Nest decorators are no accounts
ALLOWED = re.compile(r'@(BotFather|Module|Controller|Injectable)(?!\w)')
# Domain zones, without those that are common words in field and file names (customer.email, created.at)
TLDS = ('com|net|org|ua|io|dev|app|me|eu|pl|de|uk|us|info|biz|shop|store|online|site|cloud|ai|co|xyz|pro|tech|club|'
        'ru|by|kz|cz|fr|es|nl|ch|se|dk|fi|ca|au|tv|ly|gl|ee|lt|lv|ro|bg|hu|sk|pt|gr|tr|be|so|top|live|life|space|'
        'world|agency|digital|solutions|systems|software|services|website|local|internal|lan|corp|укр|рф')
CURRENCIES = (r'грн|гривн\w*|гривен\w*|uah|usd|usdt|eur|euros?|євро|евро|долар\w*|доллар\w*|dollars?|бакс\w*|pln|'
              r'gbp|chf|czk|kzt|rub|руб(л\w*)?|zł|у\.\s?[ое]\.?')
# Letters before a word are bounded: a 100 000-letter word of «оплат» stays linear
PRICE_WORDS = (r'бюджет\w*|\w{0,20}вартіст\w*|ціна|ціну|ціною|ціни|цін|ціні|цінами|кошту\w*|кошторис\w*|ставк\w*|'
               r'тариф\w*|\w{0,20}оплат\w*|абонплат\w*|сума|суму|сумою|знижк\w*|budget\w*|prices?|pricing|costs?|fees?|'
               r'invoices?')
MESSENGERS = r'telegram|телеграм|тг|instagram|інстаграм|viber|вайбер|whatsapp|facebook|tiktok|linkedin'
PATTERNS = [
    # A currency may follow a digit directly (5000грн), a letter or an underscore before it blocks it («Європа»,
    # `PAID_API_BUDGET_USD`), unless a sum follows the name (price_usd: 50); $ only next to a digit
    ('price', r'(?<![^\W\d])(%s)(?!\w)|_(%s)["\'`]?\s*[:=]\s*["\'`]?\$?\d|[€₴£₽¥]|\$\s?\d|\d\s?\$'
     % (CURRENCIES, CURRENCIES), re.I),
    # A price word with a number, not a digit glued to a letter («з 1С») other than thousands or millions («5к», «2m»)
    ('price', r'(?<!\w)(%s)(?!\w)[^\n\d]{0,25}\d(?!(?![кkмmт])[^\W\d_])' % PRICE_WORDS, re.I),
    ('payment terms', r'передоплат|предоплат|постоплат|післяоплат|(?<!\w)аванс', re.I),
    ('phone', r'(?<![\w.:/-])\d{3}[ -]\d{2}[ -]\d{2}(?![\w.:/-])', 0),
    # A mail and a link start where the word does: one try per word keeps a long line (base64, minified JSON) fast
    ('email', r'(?<![\w.%+-])[\w.%+-]+@((?:[^\W_][\w-]*\.)+[^\W\d_][\w-]*|localhost)', 0),
    ('messenger account', r'(?<![\w@])@[A-Za-z][A-Za-z0-9_]{4,}(?![\w/])|t(elegram)?\.me/|tg://'
                          r'|(?<!\w)(%s)\s*:\s*@?(?=[\w.]*[_\d])[A-Za-z][\w.]{4,}' % MESSENGERS, re.I),
    ('IBAN or card', r'(?<![A-Za-z0-9])[A-Z]{2}\d{2}[A-Z0-9]{11,30}(?![A-Za-z0-9])|(?<!\d)(\d{4}[ -]?){3}\d{4}(?!\d)',
     0),
    ('tax or ID number', r'(?<!\w)(єдрпоу|едрпоу|edrpou|іпн|інн|инн|рнокпп|nip)(?!\w)\D{0,25}\d[\d -]{5,}'
                         r'|(паспорт\w*|id-картк\w*)\D{0,15}\d{6,9}(?!\d)', re.I),
    ('date of birth', r'(?<!\w)(дат\w* народження|народи[лв]\w*|date of birth|dob|born)\D{0,15}'
                      r'(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{1,2}-\d{1,2})', re.I),
    ('link or host', r'[\w+.-]://|www\.|(?<![\w.])\d{1,3}(\.\d{1,3}){3}(?!\d)(?!\.\d)'
                     r'|(?<![\w:])([0-9a-f]{1,4}:){1,7}:([0-9a-f]{1,4})?(?![\w:])|(?<![\w:])([0-9a-f]{1,4}:){7}'
                     r'[0-9a-f]{1,4}(?![\w:])|(?<![\w@./-])[\w-]+(\.[\w-]+)*\.(%s)(?![\w-]|\.\w)' % TLDS, re.I),
    ('file name from the brief', r'brief/[^\s`]|[\w)\]-]\.(docx?|xlsx?|pptx?|pdf|rtf|odt|ods|png|jpe?g|heic|zip|rar)'
                                 r'(?!\w)', re.I),
    # Token shapes, as in the base's secret-guard hook, and long opaque tokens of letters and digits
    ('secret', r'-----BEGIN|://[^/\s:@]+:[^@\s/]+@|(?<![A-Za-z0-9])\d{8,12}:[\w-]{30,}'
               r'|(?<![\w-])sk-(ant-|proj-|or-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_\w{20,}'
               r'|xox[abprs]-[A-Za-z0-9-]{10,}|(AKIA|ASIA)[0-9A-Z]{16}|AIza[\w-]{35}|[sr]k_(live|test)_[A-Za-z0-9]{20,}'
               r'|whsec_[A-Za-z0-9]{20,}|npm_[A-Za-z0-9]{36}|glpat-[\w-]{20}|shp(at|ca|pa|ss)_[a-fA-F0-9]{32}'
               r'|SG\.[\w-]{20,}\.[\w-]{20,}|eyJ[\w-]{10,}\.[\w-]{10,}\.|GOCSPX-[\w-]{20,}|ya29\.[\w-]{30,}'
               r'|(?i:bearer)\s+[A-Za-z0-9._~+/=-]{16,}|(?i:basic)\s+(?=[A-Za-z0-9+/=]*\d)[A-Za-z0-9+/=]{8,}'
               r'|(?<![A-Za-z0-9_/.-])(?=[A-Za-z0-9_-]*\d)'
               r'(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{24,}(?![A-Za-z0-9_-])', 0),
]
COMPILED = [(kind, re.compile(rx, flags)) for kind, rx, flags in PATTERNS]
# Stage numbers («етап 2») are no prices: cut before the price patterns only. A longer number, a host
# (stage1.acme.com) or a mail after the word stays
STAGE = re.compile(r'(?<!\w)(етап[^\W\d_]*|stage)\s*\d{1,2}(?![\w@]|\.\w)', re.I)
# A credential label, also inside an env name (NP_API_KEY), so it may follow an underscore. After a strong one, any
# value that is not prose, a name or an algorithm is a secret; after a weak one (keys, access, other word forms), only
# letters with digits, 4 or more digits, or a spaced «a / b» pair. Repeats are bounded: a long word stays linear
STRONG = (r'password|passwd|pwd|passphrase|pass|secret|token|api[_ -]?key|access[_ -]?key|private[_ -]?key|pin|'
          r'credentials?|пароль|токен|секрет|пін|креденшіал\w{0,20}')
WEAK = r'passwords|secrets|tokens|парол\w{1,20}|токен\w{1,20}|секрет\w{1,20}|ключ(а|у|і|ем|ів)?|доступ(и|у|ів|ом)?'
CREDENTIAL = r'(?<![^\W_])((?P<strong>%s)|%s)(_\w{0,40})?(?!\w)' % (STRONG, WEAK)
# The label, up to 30 characters of prose, «:», «=», an arrow or a spaced dash (Markdown marks may close the label),
# then the value in any quotes; the rest of the line is only looked at, so a second label on the line is checked too
LABELED = re.compile(CREDENTIAL + r'[^\n:=;.!?]{0,30}?(\s*(=>|->|→|[:=]+)[*_~]*\s*|\s+-+\s+)[`"\']*(?P<v>[^\s`"\']+)'
                     r'(?=(?P<rest>.*))', re.I)
# The label right before the value («the password is hunter2», «API key abc123def»)
BARE = re.compile(CREDENTIAL + r'\s+(is\s+)?[`"\']*(?P<v>[^\s`"\']{4,})', re.I)
# An env name, an abbreviation or an algorithm (BOT_TOKEN, API_KEY_2, JWT, SHA-256, AES256), not a value; capitals
# with digits (ADMIN123, ADMIN_2026) are a value
ENV_NAME = re.compile(r'[A-Z]+(-\d+)?|[A-Z][A-Z0-9]*(_([A-Z][A-Z0-9]*|\d))+')
NOT_SECRET = re.compile(r'(oauth2?|ed25519|rsa-?\d*|aes-?\d*|hmac|sha-?\d*|hs\d+|rs\d+|es\d+|argon2(id|i|d)?|bcrypt|'
                        r'scrypt|pbkdf2|md5|jwt|bearer|basic|access|refresh|totp|otp|2fa|mfa|sso|tls\d*|https?\d*|'
                        r'base64|utf-?8)([-_]([a-z]+|(sha|aes|rsa|hs|rs|es|ps|md|tls|oauth|argon)-?\d{1,4}[a-z]{0,2}|'
                        r'\d{1,4}))*', re.I)
CYRILLIC = re.compile('[а-яґєіїё]', re.I)
# Phone and account numbers: digits with spaces, dots, dashes, slashes or brackets between them, not dates
DIGIT_SEP = re.compile(r'(?<=\d)[ .\-/()]{1,2}(?=[\d(])|(?<=\d)\)[ .-]?(?=\d)')
DATES = re.compile(r'(?<![\d./-])(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[./]\d{1,2}[./]\d{2,4})(?![\d./-])')
LONG_NUMBER = re.compile(r'(?<!\d)\d{10,}(?!\d)')
# No-break, thin and other spaces; hyphens, dashes and minus
PLAIN = {**dict.fromkeys([0xa0, 0x1680, *range(0x2000, 0x200b), 0x202f, 0x205f, 0x3000], ' '),
         **dict.fromkeys([*range(0x2010, 0x2016), 0x2212], '-')}
# Letters that show nothing after NFKC: Hangul fillers (NFKC turns the others into U+1160), the blank Braille cell
INVISIBLE = {0x115f, 0x1160, 0x2800}
# Latin and Greek letters that look like Cyrillic ones: a name typed in the wrong keyboard layout still matches
LAT, CYR = 'aceiopxykmhtb', 'асеіорхукмнтв'
LOOK_ALIKES = str.maketrans(LAT + 'αειορχυκτμ' + 'ёґў', CYR + 'аеіорхуктм' + 'егу')
# A word with letters of both scripts («Пaроль» with a Latin «a»), read in either one to find a label
MIXED = re.compile(r'(?<!\w)(?=\w*[a-z])(?=\w*%s)\w+' % CYRILLIC.pattern, re.I)
TO_CYR = str.maketrans(LAT + LAT.upper(), CYR + CYR.upper())
TO_LAT = str.maketrans(CYR + CYR.upper(), LAT + LAT.upper())


def norm(s):
    """NFKC with plain spaces and dashes, without invisible characters and the marks NFKC leaves (stress marks)."""
    s = unicodedata.normalize('NFKC', s).translate(PLAIN)
    return ''.join(c for c in s if unicodedata.category(c) not in ('Cf', 'Mn', 'Me') and ord(c) not in INVISIBLE)


def fold(s):
    return ''.join(c for c in norm(s).casefold() if c not in "'’ʼ`´‘′ʹ՚").translate(LOOK_ALIKES)


def labeled_secret(line):
    """secret_after_label for the line, and for the line with its mixed-script words in either script."""
    tables = (TO_CYR, TO_LAT) if MIXED.search(line) else ()
    return secret_after_label(line) or any(
        secret_after_label(MIXED.sub(lambda m, t=t: m.group().translate(t), line)) for t in tables)


def secret_after_label(line):
    """A value after a credential label that looks like a secret, not like prose («Пароль: мінімум 8 символів»), an env
    name, abbreviation or algorithm («Токен: `BOT_TOKEN`», «JWT», «bcrypt») or a placeholder («${DB_PASSWORD}»)."""
    found = [(m, False) for m in LABELED.finditer(line)] + [(m, True) for m in BARE.finditer(line)]
    for m, bare in found:
        value = m.group('v')
        core = value.rstrip('.,;:)!?')
        # A placeholder has no lowercase letters next to digits: «<token>», «%s», but «$Qwerty2026» is a value
        placeholder = core[:1] in tuple('<${%') and not (re.search('[a-z]', core) and re.search(r'\d', core))
        if (len(core) < 3 or placeholder or ENV_NAME.fullmatch(core) or NOT_SECRET.fullmatch(core)
                or re.fullmatch(r'\d{1,2}/\d{1,2}', core) or (CYRILLIC.search(core) and not re.search(r'\d', core))):
            continue
        tail = '' if bare else value[len(core):] + m.group('rest')
        has_latin, has_digit = re.search('[A-Za-z]', core), re.search(r'\d', core)
        if not m.group('strong'):
            if (has_latin and has_digit) or re.fullmatch(r'\d{4,}', core) or re.match(r'\s+/\s+\S', tail):
                return True
            continue
        # Latin letters with digits or symbols («Qwerty123», «admin/admin») or 6 digits: a secret wherever it stands
        if has_latin and (has_digit or re.search(r'[^\w\'-]', core)) or re.fullmatch(r'\d{6,}', core):
            return True
        # Only digits or only Latin letters: a secret when it ends the line or a list item («Пароль: qwerty»)
        if not bare and (not tail.strip(' `"\'.,;:)!?') or re.match(r'[,;]|\s*[/|]', tail)):
            return True
    return False


def line_hits(line, names):
    """The kinds of what a line must not hold; names: the stems of name_stems."""
    if len(line) > MAX_LINE:
        return ['line too long to check']
    line = ALLOWED.sub('', norm(line))
    staged = STAGE.sub(' ', line)
    kinds = [kind for kind, rx in COMPILED if rx.search(staged if kind == 'price' else line)]
    if labeled_secret(line):
        kinds.append('secret')
    if LONG_NUMBER.search(DIGIT_SEP.sub('', DIGIT_SEP.sub('', DATES.sub(' ', line)))):
        kinds.append('phone or long number')
    if names and name_regex(tuple(names)).search(fold(line)):
        kinds.append('client or person name')
    return list(dict.fromkeys(kinds))


# Legal forms that come with a client's name: not a name, and «тов» would match «товар»
LEGAL_FORMS = {fold(w) for w in ('тов', 'тзов', 'фоп', 'пат', 'прат', 'ооо', 'llc', 'ltd', 'inc', 'gmbh')}
ENDINGS = 'аеєиіїоуюяьйu'
MUTATIONS = {'к': 'ц', 'г': 'з', 'х': 'с'}
# Endings that lose their vowel in other forms: Кравець, Кравця; Заєць, Зайця; Сірок, Сірка
FLEETING = (('ець', 'ц'), ('єць', 'йц'), ('ок', 'к'))
# A shorter stem inside a word is mostly another word: «анн» in «налаштування»
STEM_ANYWHERE = 5


def letters(word):
    return sum(c.isalpha() for c in word)


def name_stems(lines):
    """The stems to look for: each word of each line (punctuation and legal forms dropped, a double name split at the
    hyphen) without a final vowel, ь or й while 3 letters stay (-ий while 4 stay), its form without a fleeting vowel,
    and the ц, з or с form of a final к, г or х."""
    stems = []
    for line in lines:
        for word in re.findall(r'[^\W_]+', fold(line)):
            if word in LEGAL_FORMS:
                continue
            if word.endswith('ий') and letters(word[:-2]) >= 4:
                forms = [word[:-2]]
            else:
                forms = [word[:-1] if word[-1] in ENDINGS and letters(word[:-1]) >= 3 else word]
            forms += [word[:-len(end)] + short for end, short in FLEETING if word.endswith(end)]
            for stem in (f for f in forms if letters(f) >= 3):
                stems.append(stem)
                if stem[-1] in MUTATIONS:
                    stems.append(stem[:-1] + MUTATIONS[stem[-1]])
    return list(dict.fromkeys(stems))


@functools.lru_cache(maxsize=16)
def name_regex(stems):
    """The stems of STEM_ANYWHERE letters or more inside any word, a shorter one at the start of a word followed by up
    to 3 letters (an ending)."""
    return re.compile('|'.join(re.escape(s) if letters(s) >= STEM_ANYWHERE else
                               r'(?<![^\W\d_])%s[^\W\d_]{0,3}(?![^\W\d_])' % re.escape(s) for s in stems))


def read_names(path):
    with open(path, encoding='utf-8-sig') as fh:
        stems = name_stems(fh)
    if not stems:
        raise ValueError('%s holds no name of 3 letters or more' % path)
    return stems


def check(paths, names):
    hits = []
    for path in paths:
        with open(path, encoding='utf-8-sig') as fh:
            for no, line in enumerate(fh, 1):
                kinds = line_hits(line, names)
                if kinds:
                    hits.append('%s:%d: %s' % (path, no, ', '.join(kinds)))
    return hits


def exit_code(argv):
    """main's exit code for argv, its output dropped."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            return main(argv)
        except SystemExit as e:  # argparse
            return e.code


def self_test():
    """The patterns against the samples of brief_samples.py, the stems against its names files, an empty names file,
    the exit codes of the modes and brief_tree.py."""
    # pylint: disable=import-outside-toplevel  # next to this file, on sys.path from __main__
    import brief_samples
    import brief_tree
    fails = []
    names = name_stems(brief_samples.SAMPLE_NAMES)
    for line, want in brief_samples.SAMPLES:
        got = line_hits(line, names)
        if (want is None and got) or (want is not None and want not in got):
            fails.append('brief_check: %r gives %s, expected %s' % (line[:80], got or 'nothing', want or 'nothing'))
    for lines, want in brief_samples.STEM_SAMPLES:
        got = name_stems(lines)
        if got != want:
            fails.append('brief_check: names %r give stems %s, expected %s' % (lines, got, want))
    with tempfile.TemporaryDirectory() as tmp:
        empty, clean, claude = (os.path.join(tmp, p) for p in ('names.txt', 'clean', 'claude/.claude'))
        brief_tree.touch(empty)
        try:
            fails.append('brief_check: an empty names file gives %s' % read_names(empty))
        except ValueError:
            pass
        os.makedirs(clean)
        os.makedirs(claude)
        brief_tree.touch(os.path.join(clean, 'tz.pdf'))
        # docs needs a names file or --no-names; tree and convert stop on a problem; convert writes nothing in the brief
        bad = os.path.dirname(claude)
        for argv, want in ((['docs', empty], 2), (['docs', '--names', '', empty], 2),
                           (['docs', '--no-names', empty], 0), (['tree', clean], 0), (['tree', bad], 1),
                           (['convert', bad, tmp], 1), (['convert', clean, clean], 2)):
            got = exit_code(argv)
            if got != want:
                fails.append('brief_check: %s exits %s, expected %d' % (' '.join(argv), got, want))
    return fails + brief_tree.tree_test()


def brief_mode(o):
    """tree and convert: the brief folder's list, or its problems with exit 1."""
    import brief_tree  # pylint: disable=import-outside-toplevel  # next to this file, on sys.path from __main__
    files, problems = brief_tree.scan(o.dir)
    if problems:
        print('\n'.join('brief_check: %s' % p for p in problems))
        return 1
    if o.mode == 'tree':
        print('\n'.join(files + ['brief_check: %d files' % len(files)]))
        return 0
    top = os.path.realpath(o.dir)
    if os.path.commonpath([top, os.path.realpath(o.out_dir)]) == top:
        print('brief_check: %s is inside %s, which stays as it is' % (o.out_dir, o.dir), file=sys.stderr)
        return 2
    try:
        done = brief_tree.convert(files, o.out_dir)
    except OSError as e:
        print('brief_check: %s' % e, file=sys.stderr)
        return 2
    ok = sum(1 for _, text in done if text)
    # The text file first: whatever a client's file name holds, the first path on the line is ours
    print('\n'.join(['%s <- %s' % (text, f) if text else 'FAILED %s' % f for f, text in done]
                    + ['brief_check: %d converted, %d failed' % (ok, len(done) - ok)]))
    return 0


def save_mode(o):
    """save: the paths file, then the copy; a problem copies nothing."""
    import brief_tree  # pylint: disable=import-outside-toplevel  # next to this file, on sys.path from __main__
    try:
        with open(o.paths_file, encoding='utf-8-sig') as fh:
            paths = [line.strip() for line in fh if line.strip()]
        done, problems = brief_tree.save(paths, o.dir)
    except (OSError, ValueError) as e:
        print('brief_check: %s' % e, file=sys.stderr)
        return 2
    if problems:
        print('\n'.join('brief_check: %s' % p for p in problems))
        return 1
    print('\n'.join(done + ['brief_check: %d files copied' % len(done)]))
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description='Checks for a start from a client brief.')
    ap.add_argument('--self-test', action='store_true')
    sub = ap.add_subparsers(dest='mode')
    tree = sub.add_parser('tree', help='list the brief folder and its problems')
    tree.add_argument('dir')
    save = sub.add_parser('save', help='copy the files the owner named into the brief folder')
    save.add_argument('paths_file')
    save.add_argument('dir')
    convert = sub.add_parser('convert', help='office documents of the brief folder to text')
    convert.add_argument('dir')
    convert.add_argument('out_dir')
    docs = sub.add_parser('docs', help='check docs for prices, personal data and secrets')
    docs.add_argument('files', nargs='+')
    who = docs.add_mutually_exclusive_group(required=True)
    who.add_argument('--names', metavar='FILE')
    who.add_argument('--no-names', action='store_true', help='the brief names no client or person')
    o = ap.parse_args(argv)
    if o.self_test:
        import brief_samples as bs  # pylint: disable=import-outside-toplevel
        fails = self_test()
        print('\n'.join(fails) or 'brief_check: %d samples and the tree OK' % (len(bs.SAMPLES) + len(bs.STEM_SAMPLES)))
        return 1 if fails else 0
    if o.mode == 'save':
        return save_mode(o)
    if o.mode in ('tree', 'convert'):
        return brief_mode(o)
    if o.mode != 'docs':
        ap.error('name a mode: tree, save, convert or docs')
    try:
        names = [] if o.no_names else read_names(o.names)  # --names '' is no file, not «no names»
        hits = check(o.files, names)
    except (OSError, ValueError) as e:
        print('brief_check: %s' % e, file=sys.stderr)
        return 2
    print('\n'.join(hits) or 'brief_check: clean, %d files, %d name stems' % (len(o.files), len(names)))
    return 1 if hits else 0


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I leaves the script's folder off sys.path
    sys.exit(main(sys.argv[1:]))
