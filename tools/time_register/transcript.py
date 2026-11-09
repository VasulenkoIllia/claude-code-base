"""Reading transcripts: JSONL lines, timestamps, prompts typed by the user, the uuid and sessionId of an entry, fork
copies, token counts, lines changed by edit tools, records of a form the prompt rule does not know and the warning
lines of them that claude-time and claude-metrics print."""
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone

from .patterns import (FORM_NAME_WIDTH, FORM_NAMES_MAX, LEADING_REMINDERS, LEADING_TAG, LOSSY_FORMS, MODES, NO_NAME,
                       NOT_NAME, NOT_OBJECT, ORIGINS, PASTED, SERVICE_TAGS, TYPED_KINDS, UNKNOWN_KINDS)


def parse_ts(value):
    """Aware datetime of a transcript timestamp (a naive one is UTC, as Claude Code writes them), or None."""
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def nlines(text):
    return text.count("\n") + 1 if isinstance(text, str) and text else 0


def edit_lines(name, inp):
    if name == "Write":
        return nlines(inp.get("content")), 0
    if name == "Edit":
        return nlines(inp.get("new_string")), nlines(inp.get("old_string"))
    if name == "MultiEdit":
        edits = [e for e in inp.get("edits") or [] if isinstance(e, dict)]
        return sum(nlines(e.get("new_string")) for e in edits), sum(nlines(e.get("old_string")) for e in edits)
    return nlines(inp.get("new_source")), 0


def prompt_content(entry):
    """Content of a prompt entry, or None. A prompt is a user message, or a prompt the user sent while the model was
    working: Claude Code gives it to the model mid-turn as a queued_command attachment, never as a user message. Only
    the human origin counts, or no origin at all (older entries and many typed ones): task notifications and messages
    of other sessions come both ways with their own origin (queued notifications also with their own commandMode).
    CI events come queued without an origin, their tag keeps them out (prompt_text). A user message or an attachment
    that is no object (or none), an origin kind or commandMode not in ORIGINS and MODES, the origin of a queued one (in
    any mode) on its entry instead of the attachment, or content of a would-be prompt that is neither text nor a list
    of objects (an empty message, null, a number, one block as an object, a list of strings) is a format change: not
    counted, note_unknown() keeps it for the warning."""
    holder = entry
    if entry.get("type") == "user":
        message = entry.get("message")
        if not isinstance(message, dict):
            note_unknown("message")
            return None
        content = message.get("content")
    elif entry.get("type") == "attachment":
        holder = entry.get("attachment")
        if not isinstance(holder, dict):
            note_unknown("attachment")
            return None
        if holder.get("type") != "queued_command":
            return None
        if holder.get("commandMode") not in MODES:
            note_unknown("mode", form_name(holder.get("commandMode")))
            return None
        if holder.get("origin") is None and entry.get("origin") is not None:
            note_unknown("queued_origin", origin_name(entry.get("origin")))
            return None
        if holder.get("commandMode") != "prompt" or holder.get("isMeta"):
            return None
        content = holder.get("prompt")
    else:
        return None
    origin = holder.get("origin")
    if origin is not None:
        kind = origin_kind(origin)
        if kind not in ORIGINS:
            note_unknown("origin", origin_name(origin))
            return None
        if kind != "human":
            return None
    if isinstance(content, str) or (isinstance(content, list) and all(isinstance(b, dict) for b in content)):
        return content
    note_unknown("content")
    return None


def origin_kind(origin):
    return origin.get("kind") if isinstance(origin, dict) else None


def origin_name(origin):
    """The name of an origin in the warning: its kind (form_name), or "не об'єкт" for an origin that is no object,
    so a changed shape of the field is told from a missing kind."""
    return form_name(origin_kind(origin)) if isinstance(origin, dict) else NOT_OBJECT


def pasted_label(text):
    return f"[вставлено {len(text.strip())} симв.]"


def prompt_text(entry):
    """Text of a prompt typed by the user (prompt_content), or "" for tool results, commands, reminders, notifications
    and meta entries. <system-reminder> blocks in front are cut off (a message of reminders only gives ""); a pasted
    block becomes "[вставлено N симв.]", so pasted logs and specs are not printed; a prompt of images only gives
    "[картинка]" or "[картинок: N]"; blocks of which none gives text, an image or a tool result (a text that is no
    text, a type the rule does not know, only a document, also next to empty texts or reminders only) are no prompt,
    with note_unknown() (the owner, 19.10: a warning that stops no write), empty text blocks alone without it, as an
    empty text. Text that
    starts with "<" is no prompt: silently after a tag of SERVICE_TAGS, with note_unknown() after any other (typed
    HTML, a newer form) or none, for the "примітка:" line of unknown_warning. claude-metrics counts its prompts with
    this too (claude_metrics/scan.py, its PASTED_LABEL reads the pasted label): a change here moves the metrics of
    both windows, measure both tools."""
    if entry.get("isMeta") or entry.get("isSidechain") or entry.get("isCompactSummary"):
        return ""
    content, images, odd = prompt_content(entry), 0, False
    if isinstance(content, list):
        blocks = [b for b in content if isinstance(b, dict)]
        if any(b.get("type") == "tool_result" for b in blocks):
            return ""
        images = sum(1 for b in blocks if b.get("type") == "image")
        odd = any(b.get("type") != "text" or not isinstance(b.get("text"), str) for b in blocks)
        content = " ".join(b["text"] for b in blocks if b.get("type") == "text" and isinstance(b.get("text"), str))
    if not isinstance(content, str):
        return ""
    content = content.strip()
    lead = LEADING_REMINDERS.match(content)
    if lead:
        content = content[lead.end():]
    if odd and not images and not content:  # nothing typed beside them; text blocks alone stay known forms
        note_unknown("blocks")
        return ""
    content = PASTED.sub(lambda m: pasted_label(m.group("text")), content)
    if content.startswith("<pasted_content"):  # no closing tag of the same form: all the rest is pasted
        note_unknown("unclosed")
        content = pasted_label(content[content.find(">") + 1:])
    if content.startswith("<"):
        tag = LEADING_TAG.match(content)
        if not tag:  # "<3", "< 5", a closing tag
            note_unknown("no_tag")
        elif tag.group(1) not in SERVICE_TAGS:  # typed HTML, a block the app adds to a typed prompt, a newer form
            note_unknown("tag", form_name(tag.group(1)))
        return ""
    if content.startswith(("[Request interrupted", "Caveat:")):
        return ""
    if not content and images:
        return "[картинка]" if images == 1 else f"[картинок: {images}]"
    return content


def record_id(entry, field, kind):
    """The uuid or sessionId (`field`) of an entry, None without one. One that is not text is a format change, noted
    as `kind` and taken as none: the entry still counts, only without the repeat or fork check."""
    value = entry.get(field)
    if value is None or isinstance(value, str):
        return value
    note_unknown(kind)
    return None


def fork_copy(entry, sid, known):
    """An entry that the fork `sid` copied from another known session (live or stored): it counts in that one only.
    A sessionId that is not text names no session (record_id): the entry stays in `sid`."""
    owner = record_id(entry, "sessionId", "session_id")
    return bool(owner) and owner != sid and owner in known


def is_number(value):
    """A token count of a known form: an int or a float, not true or false (a bool is an int in Python), not NaN or
    an infinity (Python's json reads those words), nor an int too large for a float."""
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


STATS = Counter()  # main() prints files, unreadable, bad_lines, bad_ts, fork_entries; not repeats
# (kind of UNKNOWN_KINDS, name) of every record of a form the prompt rule does not know: their only count, so the
# numbers of the warning lines and unknown_prompts of claude-metrics (their sum) always match the kinds
UNKNOWN = Counter()


def note_unknown(kind, name=""):
    """Count a record of a form the prompt rule does not know (a format change): its kind of UNKNOWN_KINDS and, for a
    kind that has one, the name of the value that made it unknown (form_name, origin_name)."""
    UNKNOWN[kind, name] += 1


def lossy_match(form, key):
    """Whether an UNKNOWN key (kind, name) is of a LOSSY_FORMS form (kind, name or None for any name)."""
    return key[0] == form[0] and form[1] in (None, key[1])


def lossy_forms():
    """The LOSSY_FORMS noted so far, in their order: their prompts and "задача:" markers a write would lose."""
    return [form for form in LOSSY_FORMS if any(lossy_match(form, key) for key in UNKNOWN)]


def lossy_records():
    """Records of a LOSSY_FORMS form noted so far."""
    return sum(count for key, count in UNKNOWN.items() if any(lossy_match(form, key) for form in LOSSY_FORMS))


def form_name(value):
    """An origin kind, commandMode or tag name as the warning shows it (of a prompt, only the name of its first tag): a
    character no tag name has becomes "?", a name over FORM_NAME_WIDTH characters is cut with "…"; "без назви" for a
    missing or empty value or one that is not text."""
    if not isinstance(value, str) or not value:
        return NO_NAME
    name = NOT_NAME.sub("?", value)
    return name if len(name) <= FORM_NAME_WIDTH else name[:FORM_NAME_WIDTH - 1] + "…"


def unknown_forms():
    """(kind, name, count) of the records of unknown forms: the kinds in the order of UNKNOWN_KINDS (a kind it lacks
    after them, so nothing counted drops out), the most frequent name of a kind first, then by name ("" for a kind
    without names)."""
    kinds = list(UNKNOWN_KINDS) + sorted({kind for kind, _ in UNKNOWN} - set(UNKNOWN_KINDS))
    by_count = sorted(UNKNOWN.items(), key=lambda item: (-item[1], item[0][1]))
    return [(kind, name, count) for kind in kinds for (k, name), count in by_count if k == kind]


def forms_text(forms):
    """The number of records of `forms` ((kind, name, count) in the order of unknown_forms; the sum of the kinds, so a
    line always adds up), then each kind with its names and counts. Tag names, words the user may have typed, are cut
    to the FORM_NAMES_MAX most frequent, the records of the others as "інші N" with where all are listed; origin kinds
    and commandModes, Claude Code's own words, are all shown."""
    parts = []
    for kind in dict.fromkeys(kind for kind, _, _ in forms):  # the kinds there are, in the order of unknown_forms
        label, names = UNKNOWN_KINDS.get(kind, kind), [(name, count) for k, name, count in forms if k == kind]
        # a kind without names: "<" with no tag, a pasted block not closed, a message, attachment, content, blocks,
        # uuid or sessionId of an unknown form
        if not any(name for name, _ in names):
            parts.append(f"{label} {sum(count for _, count in names)}")
            continue
        limit = FORM_NAMES_MAX if kind == "tag" else len(names)
        shown = [f"{name or NO_NAME} {count}" for name, count in names[:limit]]
        rest = sum(count for _, count in names[limit:])
        if rest:
            shown.append(f"інші {rest}, перелік у claude-metrics --json")
        parts.append(f"{label}: {', '.join(shown)}")
    return f"{sum(count for _, _, count in forms)} ({'; '.join(parts)})"


def unknown_warning():
    """The lines of records of a form the prompt rule does not know, "" without them: "увага:" with the forms of a
    format change, then "примітка:" with text that starts with "<" (TYPED_KINDS, usually typed), each with forms_text.
    The weekly split stops on "увага:" only. claude-time and claude-metrics print these lines; the skill and the weekly
    run quote them verbatim."""
    forms, lines = unknown_forms(), []
    changed = [form for form in forms if form[0] not in TYPED_KINDS]
    typed = [form for form in forms if form[0] in TYPED_KINDS]
    if changed:
        lines.append(f"увага: записів незнайомої форми {forms_text(changed)}: можливо, змінився формат транскриптів, і "
                     "частину запитів не враховано")
    if typed:
        lines.append(f"примітка: записів з «<» на початку {forms_text(typed)}: запитами не враховано; зазвичай це "
                     "набраний текст, а тег, якого ніхто не набирав, означає зміну формату транскриптів")
    return "\n".join(lines)


def read_jsonl(path):
    try:
        f = open(path, encoding="utf-8", errors="replace")
    except OSError as e:
        STATS["unreadable"] += 1
        print(f"skip {path}: {e}", file=sys.stderr)
        return
    STATS["files"] += 1
    with f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:  # not JSON, or an integer over Python's digit limit
                STATS["bad_lines"] += 1
                continue
            if isinstance(d, dict):
                yield d
            else:  # a list, a string, a number or null: a broken line, as claude-metrics counts it
                STATS["bad_lines"] += 1
