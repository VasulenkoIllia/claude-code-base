"""Constants and patterns of claude-metrics: paths, windows, price weights, the token counts and the fields of an
unknown form, what a tool call or result looks like in a transcript and what the text of a prompt (claude-time's
prompt_text) can hold."""
import os
import re
from datetime import date
from zoneinfo import ZoneInfo

KYIV = ZoneInfo("Europe/Kyiv")
PROJECTS = os.path.expanduser("~/.claude/projects")
SKILLS_DIR = os.path.expanduser("~/.claude/skills")
EXCLUDED_DIRS = ("claude-code-base", "scratchpad-denytest")
BEFORE = (date(2026, 8, 1), date(2026, 9, 30))
AFTER_START = date(2026, 10, 13)
BROWSER = ("mcp__Claude_Browser__", "mcp__claude-in-chrome__", "mcp__Claude_Preview__")
EDIT_TOOLS = {"Edit", "Write", "MultiEdit"}
SHELL_TOOLS = ("Bash", "Monitor", "mcp__terminal__run_in_terminal")  # the tools bash-guard reads
# API price ratios: cache read 0.1, cache write 1.25 (5 min TTL) or 2.0 (1 h TTL), output 5. The audit priced every
# cache write at 2.0, so weighted figures here run below its tables (subagent share 18.3% here, 20.7% there).
WEIGHTS = {"input": 1.0, "read": 0.1, "write_5m": 1.25, "write_1h": 2.0, "output": 5.0}
RESULT_TEXT_MAX = 60000
# the token counts of usage the metrics add up, and those of its cache_creation (writes by cache lifetime)
TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
SPLIT_KEYS = ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")
# fields the metrics read whose value came in a form they do not know, taken as missing (claude_metrics/transcript.py):
# the STATS key that counts their records (the footer, --json) and their name in the warning line, in its order
FIELD_FORMS = {"attachment_not_object": "attachment не об'єкт",
               "compact_metadata_not_object": "compactMetadata не об'єкт", "pretokens_not_number": "preTokens не число",
               "message_id_not_text": "message.id не рядок", "model_not_text": "model не рядок",
               "usage_not_number": "число токенів у usage не число", "text_not_text": "текст блоку не рядок",
               "permission_not_object": "permissionDecision не об'єкт",
               "permission_source_unknown": "незнайомий source у permissionDecision"}

# what prompt_text puts in place of a pasted block (time_register.transcript.pasted_label; tests/metrics-test.py
# checks they agree): a prompt that starts with one is pasted text, kept out of the text metrics like a pasted log
PASTED_LABEL = re.compile(r"\[вставлено \d+ симв\.\]")
PASTE = re.compile(r"(\w+@[\w.-]+:[~/][^\n]*[#$] )|CONTAINER ID|\(\d+ rows?\)|^-+\+-+|Last login:|docker compose (ps|logs)"
                   r"|STATUS\s+PORTS|\bpsql\b.*=>|NAME\s+IMAGE", re.I | re.M)
SIMPLIFY_AUDIT = re.compile(r"спрост|простіше|занадто склад|надто склад|ускладн|прототип|мінімальн|без зайв|прибери це"
                            r"|не потрібно|не треба це", re.I | re.S)
SIMPLIFY = re.compile(r"спрост(?!\w* слов)|спрощ|простіш(?!\w* слов)|занадто склад|надто склад|дуже склад|заскладн"
                      r"|переускладн|не ускладн|ускладнил|ускладнює|ускладнюва|перемудр|без зайв|упрост(?!\w* (слов|текст))"
                      r"|прощ[ея]\b(?! слов)|слишком сложн|не усложн|усложнил|переусложн|simplif|simpler|too complex"
                      r"|over-?engineer|keep it simple", re.I | re.S)
REDO_STRICT = re.compile(r"\bперероби(ть)?\b|переробіть|\bпеределай(те)?\b|зроби(ть)? (все |це |його |її )?заново"
                         r"|сделай(те)? (все |это )?заново|переписати заново|\bперепиши(ть)? (це|все|його|її|специфікац|тз|текст)"
                         r"|(це|все|його|її|їх) (треба|потрібно|варто|прийдеться) (повністю )?переробити"
                         r"|треба (все|це|повністю) переробити|не те[,.!]? (перероб|передела)|\bredo\b|start over"
                         r"|rewrite (it|this|that)\b|redo (it|this|that)\b", re.I)
REDO_BROAD = re.compile(r"переробити|переробл|перероби\b|переробимо|переробіть|зроби заново|зробити заново|робимо заново"
                        r"|заново зроб|з нуля|перепиши|переписати|перепишемо|перебудуй|перебудувати|передела|переделать"
                        r"|сделай заново|заново сдела|с нуля|переписать|\bredo\b|start over|from scratch|rewrite it|rebuild it",
                        re.I)
# English variants mirror the Ukrainian ones, so the metric holds if replies switch language (rules in English, v2026.10.14)
DONE_CLAIM = re.compile(r"готово\b|завершено|все працює|нуль помилок|0 помилок|готово до тестування|все зелен|all green"
                        r"|усе зелен|все пройшло|спринт закрито|можна тестувати|done\b"
                        r"|everything works|all works\b|zero errors|\b0 errors|ready (for|to) test"
                        r"|all tests pass|everything passed|all passed|sprint closed|you can test", re.I)
BUG = re.compile(r"не працю|не заходить|не відображ|не зберіга|не можу|не вийшло|помилк|баг\b|bug|error|зламал|поламал"
                 r"|не працює|не бачу|пропал|зникл|падає|впав|не грузить|не вантаж|500\b|404\b|не спрацю|криво", re.I)
REWORK = re.compile(r"знову (не|появ|завис|зліта|та сама|те саме|проблем|помилк|баг|зламал|поламал|стриб|з'явил)"
                    r"|та сама помилка|те саме\b|так і не|досі не|все ще не|переробляємо|знов (не|те)|still not"
                    r"|не виправил|нічого не змінил|не змінилось|чому знову|знову\?", re.I)
SLEEP = re.compile(r"(^|[;&|(]\s*)sleep\s+\d")
HOOK_BLOCK = re.compile(r"^\s*(<tool_use_error>)?\s*(Error: )?PreToolUse:[\w.-]+ hook error: \[[^\]]*\]: "
                        r"(BLOCKED by [\w-]+: )?")
HOOK_ASK = re.compile(r'permissionDecision\\*"\s*:\s*\\*"ask')
MODULE_MISSING = re.compile(r"ModuleNotFoundError: No module named|externally-managed-environment"
                            r"|Error: Cannot find module '|ERR_MODULE_NOT_FOUND|Cannot find package '|NODE_MODULE_VERSION"
                            r"|ERR_DLOPEN_FAILED")
PY_RUN = re.compile(r"\b(python3?|uv run|pytest|pip3?)\b")
PY_CRASH = re.compile(r'Traceback \(most recent call last\)|File "[^"]*", line \d+[\s\S]{0,400}SyntaxError: ')
BROWSER_LIKE = re.compile(r"^mcp__.*(browser|chrome|playwright|puppeteer|devtools|preview)", re.I)
# A git commit call, for the reviewer coverage and the cost per commit: git, its global options (-C dir, -c key=value,
# --flag), then the commit subcommand, not commit-tree. One character per step: no backtracking blow-up.
COMMIT_CALL = re.compile(r"""\bgit(?:\s+(?:-[Cc]\s+(?:"[^"]*"|'[^']*'|[^\s"';&|])+|--[\w-]+(?:=[^\s;&|]+)?))*"""
                         r"""\s+commit(?![\w-])""")
UI_FILE = re.compile(r"\.(tsx|jsx|css|scss)$")
REACT_FILE = re.compile(r"\.(tsx|jsx)$")
DB_FILE = re.compile(r"(schema\.prisma$|/prisma/migrations/|\.sql$)")
PRISMA_ERROR = re.compile(r"was modified after it was applied|Error: P30(05|06|09|14|18)\b"
                          r"|Drift detected: Your database schema is not in sync|We need to reset the \S+ schema")
PRISMA_RESOLVE = re.compile(r"prisma\s+migrate\s+resolve\b[^\n]*--applied")
COMMAND_NAME = re.compile(r"<command-name>/?([\w:.-]+)</command-name>")
COMMIT_HEAD = re.compile(r"^\[[^\]\n]+ [0-9a-f]{7,40}\]", re.M)  # "[main 1a2b3c4] subject", "[main (root-commit) ...]"
COMMIT_STAT = re.compile(r"(\d+) insertions?\(\+\)|(\d+) deletions?\(-\)")
LIGHT_LINES = 50  # a commit with at most this many changed lines and no DB files is Light: no react-reviewer
PRELOAD = {"database-reviewer": "database-migrations", "security-reviewer": "security-review"}  # agent -> skills:
CONDITIONAL = ("docker-patterns", "api-design")  # skills with paths: in frontmatter, listed once a matching file is touched
PRELOAD_MARK = re.compile(r"<command-name>([^<]+)</command-name>\s*<skill-format>true</skill-format>")
# the language of what the model writes to the owner (claude_metrics/language.py): chat text from MIN_CHAT_CHARS on, and
# code, links, paths and file names are no words, as in the one-off counts of 26.10 and 30.10; but they took more Latin
# than Cyrillic letters for English, which on the week of 30.10 also counted one text in eight of Ukrainian full of terms
LANG_KINDS = ("chat", "wrap_up", "plan", "quiz")
LANG_CODE = re.compile(r"```.*?```|`[^`]*`|https?://\S+|/[\w./-]+|\b[\w-]{1,100}\.(?:md|ts|tsx|json|sh|py|yml)\b", re.S)
LATIN = re.compile(r"[A-Za-z]")
CYRILLIC = re.compile(r"[А-Яа-яІіЇїЄєҐґ]")
MIN_LATIN, LATIN_RATIO, MIN_CHAT_CHARS = 20, 3, 40
PROJECT_PREFIX = re.compile(r"^-Users-[^-]+-WebstormProjects-")  # a project folder's name, for the start of sessions
WORKTREE_SUFFIX = re.compile(r"--claude-worktrees-.*$")
# real permission prompts (claude_metrics/asks.py): the ask rules of the base; a quiz or a plan to approve is no permission
PERM_KINDS = ("ssh_read", "ssh_write", "push", "merge", "guard", "other")
NO_PERMISSION = ("AskUserQuestion", "ExitPlanMode")
PERM_SOURCES = ("config", "hook", "user_temporary", "user_permanent", "user_reject")   # another one: the field changed
SSH_CALL = re.compile(r"(?:^|[;&|(\n]\s*)(?:[A-Za-z_]\w*=\S*\s+)*(?:ssh|scp|rsync)\s")
PUSH_CALL = re.compile(r"\bgit(?:\s+-[Cc]\s+\S+|\s+--[\w-]+(?:=\S+)?)*\s+push\b")
MERGE_CALL = re.compile(r"\bgh\s[^\n;&|]*\bpr\s+merge\b")
# a word that changes the server, also inside the quotes of ssh host '...' (git: not status, log, diff, show)
SSH_WRITE = re.compile(r"""(?:^|[\s;&|'"(])(?:rm|rmdir|mv|cp|tee|mkdir|touch|chmod|chown|ln|kill|pkill|reboot|shutdown|apt"""
                       r"""|apt-get|crontab|useradd|usermod|passwd|scp|rsync|sed\s+-i|git\s+(?:pull|reset|clean|checkout|stash|merge)"""
                       r"""|systemctl\s+(?:start|stop|restart|reload|enable|disable)|service\s+\S+\s+(?:start|stop|restart|reload)"""
                       r"""|docker(?:\s+compose)?(?:\s+-\S+(?:\s+\S+)?)*\s+(?:up|down|restart|stop|start|rm|run|pull|build|prune"""
                       r"""|system|volume|image|network))(?=[\s;&|'")]|$)"""
                       r"""|\b(?:insert\s+into|update\s+\S+\s+set|delete\s+from|drop\s+(?:table|database|schema)"""
                       r"""|alter\s+table|create\s+(?:table|database|index)|truncate\s)|(?<![0-9&])>>?\s*(?!/dev/)[/~]""", re.I)
WAIT_LONG_S = 300    # target of 30.10: no wait over 5 minutes on a read
SERVER_DAY_MAX = 10  # target of 30.10: at most 10 asks on a day of a session with ssh
