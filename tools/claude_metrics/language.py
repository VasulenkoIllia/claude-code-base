"""The language of what the model writes to the owner: chat text and the texts of wrap_up, update_plan and
AskUserQuestion, main sessions only (a subagent's report goes to the model, not to the owner)."""
from .patterns import CYRILLIC, LANG_CODE, LATIN, LATIN_RATIO, MIN_CHAT_CHARS, MIN_LATIN
from .transcript import STATS, kday


def is_english(text):
    """At least MIN_LATIN Latin letters, over LATIN_RATIO times the Cyrillic ones, once code, links and paths are out."""
    text = LANG_CODE.sub(" ", text)
    latin = len(LATIN.findall(text))
    return latin >= MIN_LATIN and latin > LATIN_RATIO * len(CYRILLIC.findall(text))


def joined(values):
    return " ".join(v for v in values if isinstance(v, str))


def dicts(value):
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def wrap_up_text(inp):
    return joined([inp.get("recap"), inp.get("ask"), *(a.get("label") for a in dicts(inp.get("actions")))])


def plan_text(inp):
    return joined(item.get("content") for item in dicts(inp.get("items")))


def quiz_text(inp):
    """Only what the owner reads: the keys of the input are English in every language."""
    parts = []
    for q in dicts(inp.get("questions")):
        parts += [q.get("question"), q.get("header")]
        for option in dicts(q.get("options")):
            parts += [option.get("label"), option.get("description")]
    return joined(parts)


TOOLS = {"mcp__ccd_turn__wrap_up": ("wrap_up", wrap_up_text), "mcp__ccd_turn__update_plan": ("plan", plan_text),
         "AskUserQuestion": ("quiz", quiz_text)}
NO_TEXT_KEYS = {"advance", "done", "start"}  # update_plan moving a step: a call of a known form with no text


def text_of_block(block):
    """(kind, text) of a block of a model answer that the owner reads, else None. A call of a tool of TOOLS with no text
    and not of a known form counts in lang_no_text (the scan: line)."""
    if block.get("type") == "text":
        text = block.get("text")
        return ("chat", text) if isinstance(text, str) and len(text) > MIN_CHAT_CHARS else None
    name, inp = block.get("name"), block.get("input")
    if block.get("type") != "tool_use" or not isinstance(name, str) or name not in TOOLS:
        return None
    kind, read = TOOLS[name]
    text = read(inp) if isinstance(inp, dict) else ""
    if text.strip():
        return kind, text
    if not (isinstance(inp, dict) and NO_TEXT_KEYS & set(inp)):
        STATS["lang_no_text"] += 1
    return None


def note_language(acc, block, ts, after_compact):
    """One block of a main session's model answer; after_compact: a compaction came earlier in the session."""
    found = text_of_block(block)
    if not found:
        return
    kind, text = found
    day, english = kday(ts), int(is_english(text))
    acc.add(day, "lang:" + kind)
    acc.add(day, "lang_en:" + kind, english)
    if after_compact:
        acc.add(day, "lang_compact")
        acc.add(day, "lang_compact_en", english)
