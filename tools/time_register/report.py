"""Printing: the report by project, task, kind, session, day or week, the sessions still to split, their prompts."""
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import timedelta

from .patterns import FULL_MAX_BYTES, IDLE_MIN, PROMPT_WIDTH
from .projects import project_level
from .scan import main_transcripts
from .tasks import group_tasks
from .timeline import local, per_day, union_secs
from .transcript import fork_copy, parse_ts, prompt_text, read_jsonl, record_id


def h(secs):
    return f"{secs / 3600:6.1f}"


def short(text, width):
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[:width - 1] + "…"


def transcripts(prefix):
    """The main transcripts of the sessions whose id starts with prefix, the ones the scan reads (main_transcripts: a
    session moved to another project folder has two), so the prompts are the ones --pending counts."""
    return [p for p in main_transcripts() if os.path.basename(p).startswith(prefix)]


def prompt_lines(path, known, after=None):
    """Lines "YYYY-MM-DD HH:MM  prompt" of the prompts in one main transcript, after the named minute when given. As in
    the scan, fork copies of other `known` sessions and a repeated entry (same uuid) are left out, so the lines are
    the prompts --pending counts."""
    sid = os.path.basename(path)[:-len(".jsonl")]
    lines, seen = [], set()
    for d in read_jsonl(path):
        if fork_copy(d, sid, known):
            continue
        uid = record_id(d, "uuid", "uuid")
        if uid:
            if uid in seen:
                continue
            seen.add(uid)
        text = prompt_text(d)
        ts = parse_ts(d.get("timestamp"))
        if text and ts and (after is None or ts.timestamp() >= after + 60):  # the named minute is done
            lines.append(f"{local(ts.timestamp())}  {short(text, PROMPT_WIDTH)}")
    return lines


def print_prompts(prefix, known, after=None):
    paths = transcripts(prefix)
    if len(paths) != 1:
        sys.exit(f"{prefix}: matches {len(paths)} sessions")
    for line in prompt_lines(paths[0], known, after):
        print(line)


def report(sessions, segs, by):
    if not segs:
        print("сесій у вибірці немає")
        return
    if by == "session":
        count = Counter(s["session"] for s in segs)
        print("Уся сесія, без extra_h і без обрізання датами. Задач: її частин у вибірці.")
        print(f"{'сесія':8}  {'початок':16}  {'год':>6}  {'запитів':>7}  {'задач':>5}  {'проєкт':22}  назва")
        for r in sorted((sessions[sid] for sid in count), key=lambda r: r["start_ts"]):
            print(f"{r['session'][:8]}  {local(r['start_ts'])}  {h(sum(b - a for a, b in r['intervals']))}  "
                  f"{r['prompts']:7}  {count[r['session']]:5}  {short(r['project'], 22):22}  {short(r['title'], 60)}")
        return
    if by in ("day", "week"):
        groups = defaultdict(float)
        for day, secs in per_day([iv for s in segs for iv in s["intervals"]]).items():
            groups[day if by == "day" else day - timedelta(days=day.weekday())] += secs
        for key in sorted(groups):
            label = f"{key:%d.%m.%Y}" if by == "day" else f"тиждень з {key:%d.%m}"
            print(f"{label:16}  {h(groups[key])} год")
        print(f"Годинник         {h(sum(groups.values()))} год  (паралельні сесії один раз, без extra_h, пауза понад {IDLE_MIN} хв не рахується)")
        return

    tasks = group_tasks(segs)
    if by == "project":
        projects = defaultdict(list)
        for s in segs:
            projects[s["project"]].append(s)
        print(f"{'проєкт':26}  {'рівень':14}  {'сесій':>5}  {'задач':>5}  {'сума год':>8}  {'годинник':>8}  період")
        for name in sorted(projects, key=lambda p: -sum(s["secs"] for s in projects[p])):
            ss = projects[name]
            print(f"{short(name, 26):26}  {short(project_level(name), 14):14}  {len({s['session'] for s in ss}):5}  "
                  f"{len({s['task'] for s in ss}):5}  {h(sum(s['secs'] for s in ss)):>8}  "
                  f"{h(union_secs([iv for s in ss for iv in s['intervals']])):>8}  "
                  f"{min(s['start'] for s in ss)[:10]} - {max(s['end'] for s in ss)[:10]}")
        print(f"{'Разом':26}  {'':14}  {len({s['session'] for s in segs}):5}  {len(tasks):5}  "
              f"{h(sum(s['secs'] for s in segs)):>8}  {h(union_secs([iv for s in segs for iv in s['intervals']])):>8}")
        print(f"Сума: усі задачі разом з extra_h. Годинник: паралельні сесії один раз, без extra_h. Пауза понад {IDLE_MIN} хв не рахується.")
        return
    if by == "task":
        print(f"{'проєкт':22}  {'год':>6}  {'сесій':>5}  {'тип':11}  {'розмір':6}  {'період':23}  задача")
        for t in sorted(tasks, key=lambda t: (t["project"], -t["secs"])):
            print(f"{short(t['project'], 22):22}  {h(t['secs'])}  {t['sessions']:5}  {t['kind']:11}  "
                  f"{short(t['size'], 6):6}  {t['first']} - {t['last']}  {short(t['task'], 60)}")
        return

    # by kind: hours per task, the base for estimates
    per_kind = defaultdict(list)
    for t in tasks:
        if t["secs"] >= 60:
            per_kind[t["kind"]].append(t["secs"] / 3600)
    print(f"{'тип':11}  {'задач':>5}  {'разом год':>9}  {'медіана':>7}  {'p75':>6}  {'макс':>6}")
    for kind, values in sorted(per_kind.items(), key=lambda kv: -sum(kv[1])):
        values.sort()
        p75 = statistics.quantiles(values, n=4, method="inclusive")[2] if len(values) > 1 else values[0]
        print(f"{kind:11}  {len(values):5}  {sum(values):9.1f}  {statistics.median(values):7.1f}  {p75:6.1f}  {values[-1]:6.1f}")
    print("Година задачі: сума її частин у всіх сесіях і extra_h; задачі коротші за 1 хв не враховано. "
          "Тип із tasks.csv, інакше вгадано за назвою (kind_auto).")


def print_pending(live, until, known, full=False):
    """Live sessions with prompts newer than split-until.txt: they still have to be split into tasks (a session
    whose transcript is gone cannot be split any more, --prompts has nothing to read). With full, the new prompts
    of each session follow the table (`known` as for prompt_lines)."""
    rows = []
    for rec in live.values():
        new = [t for t in rec.get("prompt_ts", []) if until is None or t >= until + 60]  # the named minute is done
        if new:
            rows.append((new[0], new[-1], len(new), rec))
    rows.sort(key=lambda r: r[0])
    lines = [f"Поділено на задачі до: {local(until) if until else 'ще ніколи'}. Нових запитів: {sum(r[2] for r in rows)}"]
    if rows:
        lines.append(f"{'сесія':8}  {'запитів':>7}  {'перший':16}  {'останній':16}  {'проєкт':22}  назва")
    lines += [f"{rec['session'][:8]}  {n:7}  {local(first_ts)}  {local(last_ts)}  "
              f"{short(rec['project'], 22):22}  {short(rec['title'], 60)}" for first_ts, last_ts, n, rec in rows]
    print("\n".join(lines))
    if full:
        print_new_prompts([r[3] for r in rows], until, nbytes("\n".join(lines)), known)


REST_TITLE = "\nНе вмістилися ({}), кожну окремим викликом:"


def nbytes(text):
    """Bytes of a printed text with its newline: the Bash output limit counts UTF-8 bytes."""
    return len(text.encode()) + 1


def blocks_that_fit(used, block_bytes, command_bytes, limit=FULL_MAX_BYTES):
    """How many leading blocks to print: `used` bytes are out already, and after the last shown block come the
    commands of all the blocks after it with their title line; everything stays within limit. Stops at the first
    block that does not fit, so the sessions keep their order."""
    shown = 0
    for i, size in enumerate(block_bytes):
        later = command_bytes[i + 1:]
        tail = nbytes(REST_TITLE.format(len(later))) + sum(later) if later else 0
        if used + size + tail > limit:
            break
        used += size
        shown += 1
    return shown


def print_new_prompts(recs, until, used, known):
    """The new prompts of the sessions in order while the output stays within FULL_MAX_BYTES (blocks_that_fit); the
    rest get the --prompts commands that print them, so nothing is cut and nothing needs a loop. A session whose
    transcript is gone by now gets a command too, and that command names the problem."""
    after = f" --after '{local(until)}'" if until else ""
    commands = [f"~/bin/claude-time --prompts {rec['session'][:8]}{after}" for rec in recs]
    blocks = []
    for rec in recs:
        paths = transcripts(rec["session"])
        head = f"\n{rec['session'][:8]}  {short(rec['project'], 22)}  {short(rec['title'], 60)}"
        blocks.append("\n".join([head] + prompt_lines(paths[0], known, until)) if len(paths) == 1 else None)
    sizes = [nbytes(b) if b is not None else FULL_MAX_BYTES + 1 for b in blocks]
    shown = blocks_that_fit(used, sizes, [nbytes(c) for c in commands])
    for block in blocks[:shown]:
        print(block)
    rest = commands[shown:]
    if not rest:
        return
    if shown or used + nbytes(REST_TITLE.format(len(rest))) + sum(nbytes(c) for c in rest) <= FULL_MAX_BYTES:
        print(REST_TITLE.format(len(rest)))
        print("\n".join(rest))
    else:  # the table and all the commands would not fit either: the table already names every session
        print(f"\nНе вмістилися ({len(rest)}): для кожної сесії з таблиці окремий виклик "
              f"~/bin/claude-time --prompts <сесія>{after}")
