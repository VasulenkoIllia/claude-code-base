"""replay_rules: what the bash gate of tests/hook-replay.py knows beyond the verdict of bash-guard (split off for
size): the ask rules of settings.json, the hook of PermissionRequest that answers a prompt (push-allow.sh), and the
classes a new block or an answered prompt must fall in. The regexes here are the gate's own, not the hooks' code.

The rules are a model, not Claude Code: a Bash(...) pattern is matched against every simple command of the text, cut at
&&, ||, ;, |, & and newlines outside quotes, with heredoc bodies, quotes, redirections and leading NAME=value words
gone ("x:*" is a prefix of words, any other pattern a glob over the whole command); a tool name matches the tool. A
Bash pattern does not count for Monitor or the terminal tool, as in Claude Code. Not modelled: the permission mode, the
classifier of auto mode, allow rules, deny rules, the checks Claude Code makes by itself (cd before git). So "ask"
here means: a rule or bash-guard asks, whatever else may ask too. The hook of PermissionRequest runs for real, with the
folder of the call as it is today: a branch that is gone since gets no answer, so the count of answered prompts is a
floor. It only reads the repo (git show-ref, config, symbolic-ref).
"""
import collections
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

from replay_common import run_hook, short

HEREDOC = re.compile(r'<<-?[ \t]*\\?([\'"]?)([A-Za-z_][\w.-]*)\1[^\n]*\n(?:.*?\n)??[ \t]*\2[ \t]*(?=\n|$)', re.S)
QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"|\'([^\']*)\'', re.S)
SPLIT = re.compile(r'&&|\|\||[;|&\n]')
REDIR = re.compile(r'\s\d*(?:>>?|>&|&>>?|<)\s*&?[\w./-]+')
ASSIGNS = re.compile(r'^(?:[A-Za-z_]\w*=\S*\s+)+')
RULE = re.compile(r'Bash\((.*)\)\Z', re.S)
PERMISSION_HOOK = 'push-allow.sh'
PERMISSION_TIMEOUT = 15.0   # as in settings.json

# (name, start of the reason of the new block, what the command must hold): a new block passes the gate only for a
# class that the run allows by name (--block-class) and that the command explains. The forms the hooks let through
# (a listing flag, an example file, a mask, a count) explain no block: one of them blocked is a regression
OPTIONS = r'(?:\s+-\S+(?:\s+[^-\s;&|]\S*)?)*'   # options, each with a value word or not
COMPOSE = re.compile(r'(?:docker' + OPTIONS + r'\s+compose|docker-compose)' + OPTIONS +
                     r'\s+(?:config|convert)(?=[\s;&|)"\'`]|$)')
COMPOSE_FLAG = re.compile(r'\s(?:-q|--quiet|--services|--volumes|--images|--profiles|--networks|--hash)(?=[\s=]|$)')
# the file of -o or of > (1>): 2> and 2>&1 are not the output
COMPOSE_FILE = re.compile(r'(?:\s(?:-o|--output)[\s=]+|(?:(?<![\d&>])|(?<=\s)1)>>?(?!&)\s*)(\S+)')
# for grep, sed and awk the file comes after the pattern or the script
ENV_HEAD = re.compile(r'(?:^|[\s;&|(\'"`])(?:/usr)?(?:/bin/)?(?:(?:cat|head|tail|less|more|bat)\s|(grep|sed|awk)\s+(?:-\S+\s+)*?'
                      r'(?:"[^"]*"|\'[^\']*\'|[^-\s;&|]\S*|-\w*[ef]\s*\S+|--(?:regexp|expression|file)=\S+)\s)')
ENV_WORD = re.compile(r'(>>?\s*)?["\']?[^\s;&|"\'`]*\.env(?:\.[\w.*-]*|\*)?["\']?(?=[\s;&|)`]|$)')
ENV_EXAMPLE = re.compile(r'\.(?:example|sample|template|dist)["\']?\Z', re.I)
# by verb: grep that counts or lists, or -o with a pattern of key names; sed in place or with a script that cuts the values
ENV_QUIET = {'grep': re.compile(r'\s(?:-[A-Za-z]*[cqlL][A-Za-z]*|--(?:count|quiet|silent|files-with-matches|files-without-match))\s|'
                                r'\s-[A-Za-z]*o[A-Za-z]*\s(?:\S+\s)*["\']?\^[^\s.]*=["\']?\s'),
             'sed': re.compile(r'\s(?:-[A-Za-z]*i\S*|--in-place\S*)\s|\s["\']?s[/|]=\.[*+]'),
             'awk': re.compile(r'(?!)')}
# stdout to /dev/null in the command itself, or a mask after a pipe later on the line (the list of the hook)
ENV_MASKED = re.compile(r'[^\n;&|]*?(?:(?<![\d&>])|(?<=\s)1|&)>\s*/dev/null|'
                        r'[^\n;&]*\|\s*(?:cut|sed|awk|grep\s+-c|wc|od)(?=\s|$)')
SEGMENT_END = re.compile(r'[\n;&|]')


def compose_prints(text):
    """A compose config call with only options before config and no listing flag after it; its output file, if it has
    one, is named again in the command (the hook blocks a print of that file too)."""
    for m in COMPOSE.finditer(text):
        tail = SEGMENT_END.search(text, m.end())
        seg = text[m.end():tail.start() if tail else len(text)]
        files = COMPOSE_FILE.findall(seg)
        if not COMPOSE_FLAG.search(seg) and (not files or any(text.count(f) > 1 for f in files)):
            return True
    return False


def env_read(text):
    """A cat or grep kind of command that names an env file to read (no example, no file it writes), with no count
    option, no mask after it and stdout not to /dev/null."""
    for head in ENV_HEAD.finditer(text):
        end = SEGMENT_END.search(text, head.end())
        words = ENV_WORD.finditer(text, head.end(), end.start() if end else len(text))
        if any(not w.group(1) and not ENV_EXAMPLE.search(w.group(0)) for w in words) and not (
                head.group(1) and ENV_QUIET[head.group(1)].search(' ' + head.group(0))) and not ENV_MASKED.match(text, head.end()):
            return True
    return False


BLOCK_CLASSES = (('compose-config', 'docker compose config prints', compose_prints),
                 ('env-print', 'printing an env file', env_read))
# a prompt the hook of PermissionRequest may answer: the text has one push, git push [flags] origin <branch> of no
# protected name, and nothing outside quotes that another ask rule names
FEATURE = 'push to a feature branch'
PUSH_FLAGS = r'(?:\s+(?:-u|--set-upstream|-q|--quiet|-v|--verbose|--progress|--no-progress))*'
FEATURE_PUSH = re.compile(r'(?:^|&&|\|\||[;|&\n])\s*git\s+push' + PUSH_FLAGS + r'\s+origin' + PUSH_FLAGS +
                          r'\s+([A-Za-z0-9][\w./-]*)' + PUSH_FLAGS + r'(?=\s*(?:$|[;&|\n]|\d?>))')
ANY_PUSH = re.compile(r'\bgit\b[^\n;&|]*?\spush(?=[\s;&|)]|$)')   # a git command with the word push
PROTECTED = re.compile(r'main|master|prod|production|head|develop|development|dev|staging|stage|release|deploy|live', re.I)
OTHER_ASK = re.compile(r'\bgh\s+pr\s+merge\b|\b(?:ssh|scp|rsync)\s|\bprisma\s+(?:migrate\s+reset|db\s+push)|\bgh\s+repo\s|'
                       r'\bgit\s+-[cC]\b')
PLAIN = re.compile(r'[\w./-]+')


def flat(cmd):
    """The command as the rules read it: no heredoc bodies, no quote characters."""
    return QUOTED.sub(lambda m: m.group(1) if m.group(1) is not None else m.group(2), HEREDOC.sub(' ', cmd))


def simple_commands(cmd):
    """The simple commands of the text, cut outside quotes, each without redirections and leading NAME=value words."""
    cmd = HEREDOC.sub(lambda m: ' ' * len(m.group(0)), cmd)
    masked = QUOTED.sub(lambda m: 'q' * len(m.group(0)), cmd)
    out, at = [], 0
    for m in list(SPLIT.finditer(masked)) + [None]:
        part = cmd[at:m.start() if m else len(cmd)]
        at = m.end() if m else at
        part = ASSIGNS.sub('', REDIR.sub(' ', ' ' + flat(part)).strip())
        if part:
            out.append(' '.join(part.split()))
    return out


def pattern_regex(pattern):
    if pattern.endswith(':*'):
        return re.compile(re.escape(pattern[:-2]) + r'(?:\s|\Z)')
    return re.compile('.*'.join(map(re.escape, pattern.split('*'))) + r'\Z', re.S)


def load_rules(path):
    """The ask rules of a settings.json: ([(rule as written, regex)] for Bash, {tool names}). A file that is not there
    or is no JSON object is a setup error of the run: ValueError."""
    try:
        with open(path, encoding='utf-8') as fh:
            ask = (json.load(fh).get('permissions') or {}).get('ask') or []
    except (OSError, ValueError, AttributeError) as e:
        raise ValueError('settings not read: %s (%s)' % (short(path), type(e).__name__))
    bash = [(r, pattern_regex(RULE.match(r).group(1))) for r in ask if isinstance(r, str) and RULE.match(r)]
    tools = {r for r in ask if isinstance(r, str) and re.fullmatch(r'[A-Za-z_][\w-]*', r)}
    if not bash and not tools:   # the settings of this base always have some: the gate would count no prompt of a rule
        raise ValueError('settings with no ask rule: %s' % short(path))
    return bash, tools


def registered(settings):
    """The settings name the hook under PermissionRequest: with the file alone Claude Code never runs it."""
    with open(settings, encoding='utf-8') as fh:
        groups = (json.load(fh).get('hooks') or {}).get('PermissionRequest') or []
    return any(isinstance(h, dict) and str(h.get('command', '')).endswith('/' + PERMISSION_HOOK)
               for g in groups if isinstance(g, dict) for h in g.get('hooks') or [])


def rule_ask(rules, tool, cmd):
    """The first ask rule that matches this call, None when none does."""
    bash, tools = rules
    if tool in tools:
        return tool
    if tool != 'Bash':
        return None
    parts = simple_commands(cmd)
    return next((rule for rule, rx in bash if any(rx.match(p) for p in parts)), None)


def side(settings, bash_guard):
    """One side of the replay: (its ask rules, the hook of PermissionRequest next to its bash-guard or None, the
    settings path). The hook counts only when the settings of that side name it."""
    hook = os.path.join(os.path.dirname(bash_guard), PERMISSION_HOOK)
    rules = load_rules(settings)
    return rules, hook if os.path.isfile(hook) and registered(settings) else None, settings


def permission_allows(hook, tool, cmd, cwd, env):
    """The hook of PermissionRequest says allow for this call (the prompt does not come)."""
    payload = {'session_id': 'hook-replay', 'hook_event_name': 'PermissionRequest', 'permission_mode': 'default',
               'tool_name': tool, 'tool_input': {'command': cmd}, 'cwd': cwd}
    rc, out, _, _ = run_hook(hook, payload, env, PERMISSION_TIMEOUT)
    if rc != 0 or not out.strip():
        return False
    try:
        return json.loads(out)['hookSpecificOutput']['decision']['behavior'] == 'allow'
    except (ValueError, KeyError, TypeError):
        return False


def block_class(cmd, reason):
    """The class of a new block: by the reason, when the command holds what the class names; else None."""
    text = cmd.replace('\\\n', ' ')   # a backslash-newline is a blank
    return next((name for name, start, explains in BLOCK_CLASSES if reason.startswith(start) and explains(text)), None)


def feature_push(cmd):
    """The text is a push the hook may answer: see FEATURE_PUSH. A quoted word counts only as a plain name."""
    text = QUOTED.sub(lambda m: m.group(1) or m.group(2) or '' if PLAIN.fullmatch(m.group(1) or m.group(2) or '') else ' \0 ',
                      HEREDOC.sub(' ', cmd))   # \0: no word of a push
    found = FEATURE_PUSH.findall(text)
    return len(found) == 1 and len(ANY_PUSH.findall(text)) == 1 and not PROTECTED.fullmatch(found[0]) \
        and not OTHER_ASK.search(text)


def rules_scan(results, sides, env, workdir, jobs):
    """key -> ((old rule, old answered), (new rule, new answered)) for every replayed call: the ask rule of each side
    that matches it, and whether the hook of PermissionRequest of that side answers the prompt (of the rule or of
    bash-guard). The hook runs only where there is a prompt and the word push."""
    def one(item):
        (tool, cmd, cwd), res = item
        out = []
        for (rules, hook, _), dec in zip(sides, (res[0], res[3])):
            rule = rule_ask(rules, tool, cmd)
            asked = dec == 'ask' or (dec == 'allow' and rule is not None)
            out.append((rule, bool(hook and asked and 'push' in cmd and permission_allows(
                hook, tool, cmd, cwd if cwd and os.path.isdir(cwd) else workdir, env))))
        return (tool, cmd, cwd), tuple(out)
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        return dict(ex.map(one, results.items()))


def effective(dec, rule, answered):
    """What the user sees on one side: the verdict of bash-guard, with the prompt of a rule and the answer of the hook."""
    if dec == 'allow' and rule is not None and not answered:
        return 'ask'
    return 'allow' if dec == 'ask' and answered else dec


def rules_gate(by_key, results, scan, sides, shape, shapes_n):
    """Prints what the rules and the hook of PermissionRequest change and returns (ok, new asks per day). A prompt
    that the new hook answers must be in the class FEATURE (the gate's own regex); an ask of a rule that goes away with
    no answer has no class; a new ask of a rule is listed by rule and counts in the median of new asks."""
    asks = [0, 0]
    answered, gone, new = collections.Counter(), collections.Counter(), collections.defaultdict(collections.Counter)
    odd, per_day = collections.Counter(), collections.Counter()
    pushes = [0, 0]   # prompts of the new side with the word push in the call, and those its hook answered
    for key, ((orule, oans), (nrule, nans)) in scan.items():
        n, od, nd = len(by_key[key]), results[key][0], results[key][3]
        asks[0] += n if orule else 0
        asks[1] += n if nrule else 0
        if 'push' in key[1] and (nd == 'ask' or nd == 'allow' and nrule):
            pushes[0] += n
            pushes[1] += n if nans else 0
        was, now = effective(od, orule, oans), effective(nd, nrule, nans)
        if was == 'ask' and now == 'allow' and nans:
            cls = FEATURE if feature_push(key[1]) else 'NO CLASS'
            answered[cls] += n
            if cls == 'NO CLASS':
                odd[shape(key[1])] += n
        elif was == 'ask' and now == 'allow' and od == 'allow':
            gone[orule] += n
            odd[shape(key[1])] += n
        elif was == 'allow' and now == 'ask' and nd == 'allow':
            new[nrule][shape(key[1])] += n
            for row in by_key[key]:
                per_day[row[-1]] += 1
    names = [os.path.basename(hook) if hook else 'none' for _, hook, _ in sides]
    print('rules  old %s: %d ask rules, hook of PermissionRequest %s; new %s: %d ask rules, hook %s'
          % (short(sides[0][2]), len(sides[0][0][0]) + len(sides[0][0][1]), names[0],
             short(sides[1][2]), len(sides[1][0][0]) + len(sides[1][0][1]), names[1]))
    print('rule asks  old %d calls, new %d calls (a model of the rules: tests/replay_rules.py)' % tuple(asks))
    if sides[1][1]:   # 0 of many: the hook is silent (broken, or the repos are gone); the gate cannot tell which
        print('push prompts  new %d calls with a prompt and the word push, %s answered %d' % (pushes[0], names[1], pushes[1]))
    for cls, n in answered.most_common():
        print('lost asks  %s (answered by %s; a floor: the repos are as they are today): %d' % (cls, names[1], n))
    for rule, n in gone.most_common():
        print('lost asks  NO CLASS (the rule %s no longer asks): %d' % (rule, n))
    for s, n in odd.most_common(shapes_n):
        print('      %4dx  %s' % (n, s))
    for rule, shapes in sorted(new.items(), key=lambda kv: -sum(kv[1].values())):
        print('new asks  rule %s: %d' % (rule, sum(shapes.values())))
        for s, n in shapes.most_common(shapes_n):
            print('      %4dx  %s' % (n, s))
    return not answered['NO CLASS'] and not gone, per_day
