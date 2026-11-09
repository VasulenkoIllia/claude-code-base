"""Constants and patterns of claude-time: paths, the break length, the --full and prompt line limits, the forms of
prompts in transcripts (reminders, pasted blocks, origins, queue modes, service tags, labels), the kinds of records
of an unknown form, those of typed text, the limits of their names in the warning and the kinds that stop a write,
tasks.csv and export columns, the "задача:" marker and the keyword guess of a task kind."""
import os
import re
from zoneinfo import ZoneInfo

KYIV = ZoneInfo("Europe/Kyiv")
PROJECTS = os.path.expanduser("~/.claude/projects")
WORKSPACE = os.path.expanduser("~/WebstormProjects")
IDLE_MIN = 30
LEAD_SECS = 300
BACKUPS = 10
STORE_VERSION = 1
# --pending --full output at most, in UTF-8 bytes (table, prompts, --prompts commands): Claude Code moves a Bash
# output over about 30000 bytes into a file and shows only a preview (Cyrillic takes 2 bytes a letter)
FULL_MAX_BYTES = 25000
PROMPT_WIDTH = 240  # characters of a prompt line in --prompts and --pending --full; a longer prompt ends with "…"
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
MANUAL = ("from", "task", "kind", "size", "extra_h", "note")
MARKER = re.compile(r"(?i)^(?:задача|task)\s*:\s*([^\n]{3,})")
# what the app puts in front of a typed prompt (e.g. the linked sessions note): cut off, the prompt itself stays
LEADING_REMINDERS = re.compile(r"(?:<system-reminder>.*?</system-reminder>\s*)+", re.S)
# text pasted into a prompt, as the desktop app wraps it: the closing tag repeats the opening tag's id, so a closing
# tag inside the pasted text does not end the block
PASTED = re.compile(r"<pasted_content(?P<attrs>[^>]*)>(?P<text>.*?)</pasted_content(?P=attrs)>", re.S)
# origin kinds of messages and commandModes of queued ones that Claude Code 2.1.296 and 2.1.299 write (their
# binaries, 16.10 and 17.10); only a human prompt counts, another value means the format changed. "plugin" is left
# out on purpose (owner, 17.10): a plugin can send a prompt as the user (asUser), so it is warned of, not dropped
ORIGINS = ("human", "peer", "task-notification", "auto-continuation", "channel", "unclassified", "coordinator",
           "observer", "observer-activity", "slack-ping")
MODES = ("prompt", "task-notification", "bash", "orphaned-permission", "poll-event")
# tags a message that is no prompt starts with: Claude Code's own (the tag lists of its binary 2.1.299, the same in
# 2.1.296: command and tool output, slash commands, notifications, messages of other sessions, agents and channels,
# IDE context, system tags) and the envelopes of the desktop app (CI events, side session events, a scheduled run).
# Text that starts with another tag (typed HTML, a block the app adds to a typed prompt, a newer form) is no prompt
# either, but it is warned of
SERVICE_TAGS = frozenset((
    "bash-input", "bash-stdout", "bash-stderr", "bash-exit-code",
    "local-command-stdout", "local-command-stderr", "local-command-caveat",
    "command-name", "command-message", "command-args", "command-contents", "skill-format",
    "task-notification", "agent-message", "teammate-message", "cross-session-message", "channel", "remote-review",
    "slack-ping", "slack-tag-message", "tick", "fetched-web-content", "coordinator-relay", "fork-boilerplate",
    "user-memory-input", "mcp-resource-update", "mcp-polling-update",
    "artifact-type-instructions", "cowritten-artifact-html", "artifact-file-content", "artifact-origin-notes",
    "artifact-stored-declaration",
    "ide_opened_file", "ide_selection", "terminal", "browser", "browser_instruction",
    "system-reminder", "system_reminder", "function_results", "tool_use_error", "sandbox_violations",
    "persisted-output", "total_tokens", "user-prompt-submit-hook", "post-tool-use-hook",
    "ci-monitor-event", "side-sessions-event", "scheduled-task",
))
LEADING_TAG = re.compile(r"<([^\W\d][\w:.-]*)")  # the name of the tag a text starts with: a letter or "_" first
NOT_NAME = re.compile(r"[^\w:.-]")  # a character no tag name has: the warning shows it as "?"
# kinds of records of a form the prompt rule does not know, as the warning names them and in its order. The first
# four also name the value that made the record unknown (an origin kind, a commandMode, the kind of an origin on the
# entry, a tag name): the warning cuts a name to FORM_NAME_WIDTH characters and shows the FORM_NAMES_MAX most
# frequent tag names; a tag name may be a word the user typed (the owner's choice, 17.10), the values of the other
# kinds are Claude Code's own words and all shown
UNKNOWN_KINDS = {"origin": "невідомий origin", "mode": "невідомий commandMode",
                 "queued_origin": "origin у записі черги", "tag": "тег на початку", "no_tag": "«<» без тегу",
                 "unclosed": "вставка без закривального тегу", "message": "message не об'єкт",
                 "attachment": "attachment не об'єкт", "content": "content незнайомої форми",
                 "blocks": "блоки без тексту", "uuid": "uuid не рядок", "session_id": "sessionId не рядок"}
# kinds of text that starts with "<", usually typed (<div>, <3): a line "примітка:" of their own, not "увага:", since
# the weekly split stops on "увага:" and a typed <div> would stop it for the ≈180 days its transcript lives (the owner,
# 03.11). A new tag of Claude Code itself shows in that line too, with a name nobody typed
TYPED_KINDS = ("tag", "no_tag")
FORM_NAME_WIDTH = 30
NO_NAME = "без назви"  # the name of a value that is missing, empty or not text
NOT_OBJECT = "не об'єкт"  # the name of an origin that is no object
FORM_NAMES_MAX = 5
# forms that stop --write, --add and --split-done (the owner, 19.10 and 20.10), as (kind, name), None for any name: a
# format no typed text makes, whose prompts and "задача:" markers the register would lose for good; the line names at
# most BLOCK_SESSIONS_MAX of their sessions
LOSSY_FORMS = (("origin", NOT_OBJECT), ("queued_origin", NOT_OBJECT), ("message", None), ("attachment", None),
               ("content", None))
BLOCK_SESSIONS_MAX = 5
# what prompt_text puts for a prompt of only pasted text or only images: no typed words, so not a session title
LABEL = re.compile(r"\[(?:вставлено \d+ симв\.|картинка|картинок: \d+)\]")
KINDS = (
    ("bug", r"\bбаг(?:и|ів|у|а|ом|ами)?\b|\bbug|\bfix|виправ|помилк|error|падає|не працю|злама|ошибк|не работа"),
    ("ops", r"деплой|deploy|сервер|server|docker|nginx|\bci\b|github actions|\bпрод|\bvps\b|бекап|backup|домен"),
    ("analysis", r"аналіз|аудит|audit|review|рев.?ю|дослід|research|порівня|анализ|розбер|поясни|оцін|план"),
    ("docs", r"\bтз\b|документ|readme|\bspec|специфікац|інструкц"),
    ("integration", r"інтеграц|integration|webhook|вебхук|\bapi\b|синхрон|\bsync|hubspot|monday|keycrm|airtable|n8n|\bmcp\b"),
    ("data", r"міграц|migration|схем|schema|\bбд\b|баз[аиі] даних|database|prisma|\bsql|імпорт|import|очистк"),
    ("ui", r"\bui\b|дизайн|design|figma|верст|екран|сторінк|frontend|фронт|макет"),
    ("prototype", r"прототип|prototype|демо|\bdemo\b|\bmvp\b"),
    ("setup", r"налаштув|setup|install|встанов|конфіг|config|ініціаліз|скіл"),
    ("refactor", r"рефактор|refactor|декомпоз|cleanup|прибер|оптиміз"),
    ("module", r"модул|module|фіч|feature|додай|додати|реаліз|зроби|створи|implement|\badd\b|розроб|чат|бот"),
)
KIND_NAMES = tuple(k for k, _ in KINDS)
TASK_COLUMNS = ("project", "level", "task", "kind", "size", "hours", "minutes", "sessions", "first", "last", "note")
SESSION_COLUMNS = ("session", "project", "start", "end", "minutes", "tasks", "title", "prompts", "agents", "files",
                   "lines_add", "lines_del", "out_ktok", "model", "src", "branch", "transcript")


def guess_kind(text):
    text = text.lower()
    for kind, pattern in KINDS:
        if re.search(pattern, text):
            return kind
    return ""
