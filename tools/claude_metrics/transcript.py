"""Reading transcripts: JSONL lines, timestamps, Kyiv days, the message of a record and its text, the fields the
metrics read, git commit output. Typed prompts are claude-time's (time_register.transcript.prompt_text, used by the
scan)."""
import json
import sys
from collections import Counter
from datetime import datetime, timezone

from time_register.transcript import is_number

from .patterns import COMMIT_HEAD, COMMIT_STAT, KYIV, SPLIT_KEYS, TOKEN_KEYS


def commit_size(text):
    """Changed lines of the last commit git printed (its stat line follows the [branch hash] header); None if not printed."""
    heads = list(COMMIT_HEAD.finditer(text))
    if not heads:
        return None
    for line in text[heads[-1].end():].splitlines()[1:4]:
        if " changed" in line:
            return sum(int(a or 0) + int(b or 0) for a, b in COMMIT_STAT.findall(line))
    return None

# What the scan skipped or could not read, printed as one footer line (and under "scan" in --json) so a partial
# scan or a transcript format change shows up instead of passing for a true zero.
STATS = Counter()


def parse_ts(value):
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def kday(ts):
    return ts.astimezone(KYIV).date()


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
            else:
                STATS["bad_lines"] += 1


def text_of(content):
    """Text of message content or of a tool_result: a string, or the text blocks of a list. A text that is no text is
    taken as an empty one and counts once per content in text_not_text (FIELD_FORMS)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        if not all(isinstance(t, str) for t in texts):
            STATS["text_not_text"] += 1
        return "\n".join(t if isinstance(t, str) else "" for t in texts)
    return ""


def message_of(d):
    """The message of a record, {} for none or one that is no object, so the scan does not fail on it. Such a record is
    a format change that leaves the metrics incomplete: it counts in message_not_object, which claude-metrics warns of
    (the prompt rule also warns of a user one, time_register.transcript.prompt_content)."""
    message = d.get("message")
    if isinstance(message, dict):
        return message
    STATS["message_not_object"] += 1
    return {}


# The fields below (FIELD_FORMS) of an unknown form are taken as missing, so the scan does not fail on them, and their
# records are counted, so claude-metrics warns that the metrics are incomplete.
def attachment_of(d):
    """The attachment of an attachment record, None for none or one that is no object (attachment_not_object; in a
    main transcript the prompt rule warns of it too)."""
    att = d.get("attachment")
    if isinstance(att, dict):
        return att
    STATS["attachment_not_object"] += 1
    return None


def compact_metadata_of(d):
    """compactMetadata of a compaction, {} for none (null too, a form known before) or one that is no object
    (compact_metadata_not_object): the compaction then counts as one with an unknown trigger, as before."""
    meta = d.get("compactMetadata")
    if isinstance(meta, dict):
        return meta
    if meta is not None:
        STATS["compact_metadata_not_object"] += 1
    return {}


def pre_tokens_of(meta):
    """preTokens of a compaction's compactMetadata, None for none or one that is no number (pretokens_not_number):
    the compaction then counts as one without it, as before."""
    pre = meta.get("preTokens")
    if pre is None or is_number(pre):
        return pre
    STATS["pretokens_not_number"] += 1
    return None


def text_field(msg, key, stat):
    """The id or model (`key`) of a model answer, None without one; one that is not text counts in `stat`."""
    value = msg.get(key)
    if value is None or isinstance(value, str):
        return value
    STATS[stat] += 1
    return None


def is_count(value):
    return value is None or is_number(value)


def usage_of(msg):
    """The usage of a model answer without the token counts (TOKEN_KEYS, SPLIT_KEYS of cache_creation) that are no
    number and without a cache_creation that is no object: such a record counts once in usage_not_number. A usage
    that is no object comes back as it is."""
    usage = msg.get("usage")
    if not isinstance(usage, dict):
        return usage
    split = usage.get("cache_creation")
    bad = [k for k in TOKEN_KEYS if not is_count(usage.get(k))]
    if split is not None and not isinstance(split, dict):  # the split of the cache writes, taken as not recorded
        bad.append("cache_creation")
    split = split if isinstance(split, dict) else {}
    bad_split = [k for k in SPLIT_KEYS if not is_count(split.get(k))]
    if not bad and not bad_split:
        return usage
    STATS["usage_not_number"] += 1
    usage = {k: v for k, v in usage.items() if k not in bad}
    if bad_split:
        usage["cache_creation"] = {k: v for k, v in split.items() if k not in bad_split}
    return usage
