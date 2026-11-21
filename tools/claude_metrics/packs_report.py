"""Printing for claude-metrics --packs: the report (in Ukrainian, as the rest of claude-metrics) and the lines of
scripts/doctor.sh (in English, as the rest of doctor), both from the dict of claude_metrics.packs.collect.

Doctor's lines: first `  library use: ...`, a line that says what was looked at, so a scan of nothing does not pass for
"no finding"; then WARNs, each naming what to do: a journal that does not open or holds lines of another form;
transcripts not read in full; skill listings, tool calls and times of an unknown form; sessions none of which starts
with a skill listing; no transcript at all; packs that are on and not by the last line of the journal (the days to "no call" are not counted
there); a pack the journal has on for the whole window without a break, in a project with work sessions, that got no
call (ADR-007 turns it off there; not judged, and said so, when the transcripts start later than the window); a project of the projects folder whose last session started with a skill listing of FILL_WARN
per cent of its limit or more, or with a description of a pack skill cut; a review of a pack that is due and not
recorded.
"""
import os
from datetime import timedelta

from .packs_sources import REVIEW_DAYS

FILL_WARN = 80   # per cent of the limit of the skill listing from which doctor warns (ADR-007, section 13)
WARN = "  WARN: library: "
KINDS = (("skill", "скіли"), ("slash", "командою"), ("agent", "агенти"))


def joined(counts):
    return ", ".join("%s %d" % (name, n) for name, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def scan_notes(data):
    """What the report must say before its numbers: what was not read."""
    stats, notes = data["scan"], []
    if data["catalog_note"]:
        notes.append("каталог паків не читається (%s): скіли й сигнали паків невідомі, пропуски й обрізані описи не рахуються"
                     % data["catalog_note"])
    if data["journal_note"]:
        notes.append("журнал claude-pack не відкрився (%s): дати першого вмикання й огляди невідомі" % data["journal_note"])
    if data["journal_bad"]:
        notes.append("рядків журналу claude-pack незнайомої форми: %d, їх не враховано" % data["journal_bad"])
    if stats.get("unreadable") or stats.get("bad_lines"):
        notes.append("транскрипти прочитано не повністю (файлів не відкрилось чи обірвалось %d, рядків не JSON %d): "
                     "виклики й сесії це нижня межа" % (stats.get("unreadable", 0), stats.get("bad_lines", 0)))
    if stats.get("listing_form_unknown"):
        notes.append("списків скілів чи їхніх рядків незнайомої форми: %d (змінився формат транскриптів?): обрізані описи "
                     "там не пораховано" % stats["listing_form_unknown"])
    if stats.get("no_timestamp") or stats.get("call_form_unknown"):
        notes.append("викликів, правок і списків скілів без часу: %d, викликів незнайомої форми: %d (змінився формат "
                     "транскриптів?): їх не враховано" % (stats.get("no_timestamp", 0), stats.get("call_form_unknown", 0)))
    if stats.get("sessions") and not stats.get("sessions_with_listing"):
        notes.append("сесій прочитано %d, і жодна не починається списком скілів (змінився формат транскриптів?): які паки "
                     "ввімкнено в сесіях і розмір списків невідомо" % stats["sessions"])
    oldest, first = stats.get("oldest"), data["window"]["first"]
    if oldest is None:
        notes.append("транскриптів не знайдено: нулі нижче нічого не доводять")
    elif oldest > first:
        notes.append("найстаріший транскрипт від %s, вікно починається %s: раніших днів немає, нуль викликів там нічого "
                     "не доводить" % (oldest, first))
    return notes


def pair_lines(p):
    """The lines of one project and pack."""
    if p["enabled_since"]:
        since = "увімкнено %s" % p["enabled_since"]
        since += "" if p["journal_state"] == "enable" else ", за журналом зараз вимкнено"
    else:
        since = "рядка вмикання в журналі немає"
    share = "" if p["share_pct"] is None else " (%d%%)" % p["share_pct"]
    misses = "пропусків %d" % p["misses"] if p["has_signals"] else "пропуски не рахуються: пак без файлових сигналів"
    last = ", останній %s" % p["last_call"] if p["last_call"] else ""
    lines = ["%s · %s (%s): сесій з паком %d, робочих %d, з них з викликом %d%s; викликів %d%s; %s; сесій з обрізаним описом %d%s" % (
        p["name"], p["pack"], since, p["sessions"], p["work"], p["called"], share, p["calls_total"], last, misses,
        p["cut_sessions"], " (до %d описів)" % p["cut_max"] if p["cut_max"] else "")]
    parts = ["%s: %s" % (title, joined(p["calls"][kind])) for kind, title in KINDS if p["calls"][kind]]
    if parts:
        lines.append("    " + "; ".join(parts))
    f = p["first_days"]
    if f and f["covered"]:
        share = "" if f["share_pct"] is None else " (%d%%)" % f["share_pct"]
        lines.append("    перші 30 днів від вмикання (%s..%s%s): з викликом %d з %d робочих сесій%s" % (
            f["first"], f["last"], "" if f["complete"] else ", ще тривають", f["called"], f["work"], share))
    elif f:
        lines.append("    перші 30 днів від вмикання (%s..%s): транскрипти так далеко не сягають" % (f["first"], f["last"]))
    return lines


def review_text(r):
    day = r["first_enable"]
    plan = ", ".join("огляд %d дня %s" % (d, "записано" if d in r["recorded"] else
                                          "НЕ ЗАПИСАНО" if d in r["due"] else "з %s" % (day + timedelta(days=d)))
                     for d in REVIEW_DAYS)
    return "%s: перше вмикання %s (%s), %d днів тому; %s" % (r["pack"], day, r["name"], r["days"], plan)


def print_report(data):
    w = data["window"]
    if not (data["catalog"] or data["catalog_note"] or data["journal_lines"] or data["journal_note"]
            or data["journal_bad"] or data["pairs"]):
        print("Бібліотеки паків тут немає: ні каталогу, ні журналу claude-pack. Рахувати нічого.")
        return
    for note in scan_notes(data):
        print("увага: " + note)
    print("Паки бібліотеки за %d днів (%s..%s). Виклик: Skill або /команда скіла паку чи запуск його агента. Робоча сесія: "
          "основна сесія з паком у списку скілів і правкою файла, з її субагентами." % (w["days"], w["first"], w["last"]))
    for p in data["pairs"]:
        print("\n".join(pair_lines(p)))
    if not data["pairs"]:
        print("Паків, увімкнених у проєктах чи видимих у сесіях вікна, немає.")
    idle = ["%s у %s (робочих сесій %d)" % (p["pack"], p["name"], p["work"]) for p in data["pairs"]
            if p["on"] and not p["calls_total"]]
    print("Увімкнені і без викликів у вікні: %s" % ("; ".join(idle) or "немає"))
    with_pack = {p["project"] for p in data["pairs"]}
    shown = [f for f in data["fill"] if f["project"] in with_pack or f["pct"] >= FILL_WARN or f["cut"]]
    rest = [f for f in data["fill"] if f not in shown]
    text = "; ".join("%s %d (%d%%)%s" % (f["name"], f["chars"], f["pct"], ", обрізано описів паків: %d" % f["cut"] if f["cut"] else "")
                     for f in shown) or "немає сесій з паком у вікні"
    if rest:
        top = max(rest, key=lambda f: f["pct"])
        text += "; решта проєктів: %d, найбільший %s %d%%" % (len(rest), top["name"], top["pct"])
    print("Список скілів на старті останньої сесії проєкту (межа близько %d символів): %s" % (data["limit"], text))
    print("Огляди паків (відлік від першого вмикання в теці проєктів; запис: claude-pack review <пак> --day 30|60): %s"
          % ("; ".join(review_text(r) for r in data["reviews"]) or "жоден увімкнений пак не має рядка вмикання в журналі"))


def grouped(rows, detail):
    """`pack in N (project, ...)` phrases of doctor, joined with "; ": one per pack, projects in order."""
    by_pack = {}
    for p in rows:
        by_pack.setdefault(p["pack"], []).append(detail(p))
    return "; ".join("%s in %d (%s)" % (pack, len(names), ", ".join(names)) for pack, names in sorted(by_pack.items()))


def source_warns(data, journal_shown):
    """The WARNs about what was not read: without them a zero below would pass for a finding."""
    stats, out = data["scan"], []
    if data["catalog_note"]:
        out.append("%sclaude-metrics does not read the catalog (%s): the skills and file signals of the packs are not "
                   "known, misses and cut descriptions are not counted" % (WARN, data["catalog_note"]))
    if data["journal_note"]:
        out.append('%s%s does not open (%s): the first enable of the packs is not known, the reviews and "no call in %d '
                   'days" are not counted' % (WARN, journal_shown, data["journal_note"], data["window"]["days"]))
    if data["journal_bad"]:
        out.append("%s%d line(s) of %s are no journal line of claude-pack: an enable or a review they held is not counted"
                   % (WARN, data["journal_bad"], journal_shown))
    if stats.get("unreadable") or stats.get("bad_lines"):
        out.append("%stranscripts of the packs not read in full (%d file(s) did not open or broke off, %d line(s) are no "
                   "JSON): the counts of calls and sessions are a lower bound"
                   % (WARN, stats.get("unreadable", 0), stats.get("bad_lines", 0)))
    if stats.get("listing_form_unknown"):
        out.append("%s%d skill listing(s) or lines of one of an unknown form (a transcript format change? Compare with "
                   "docs/compat.md): cut descriptions are not counted there" % (WARN, stats["listing_form_unknown"]))
    if stats.get("no_timestamp") or stats.get("call_form_unknown"):
        out.append("%s%d call(s), edit(s) or skill listing(s) of the transcripts have no time and %d call(s) are of an "
                   "unknown form (a transcript format change? Compare with docs/compat.md): they are not counted"
                   % (WARN, stats.get("no_timestamp", 0), stats.get("call_form_unknown", 0)))
    if stats.get("sessions") and not stats.get("sessions_with_listing"):
        out.append("%s%d session(s) looked at and none starts with a skill listing (a transcript format change? Compare "
                   "with docs/compat.md): the packs that are on in a session and the size of the skill lists are not known"
                   % (WARN, stats["sessions"]))
    return out


def doctor_lines(data, journal_shown):
    """The lines of scripts/doctor.sh: the summary first, then the WARNs."""
    w, today, base = data["window"], data["window"]["last"], data["projects_dir"]
    on = [p for p in data["pairs"] if p["on"]]
    fill = [f for f in data["fill"] if os.path.dirname(f["project"].rstrip("/")) == base]
    top = max(fill, key=lambda f: f["pct"], default=None)
    listing = ("at most %d%% of %d chars (%s)" % (top["pct"], data["limit"], top["name"]) if top
               else "no session of a project with a skill listing")
    out = ["  library use: %d pack(s) on in %d project(s); %d days of transcripts, %d session(s) looked at: %d with a pack "
           "on and an edit, %d call(s) of pack skills and agents; the skill list a last session started with: %s" % (
               len({p["pack"] for p in on}), len({p["project"] for p in on}), w["days"], data["scan"].get("sessions", 0),
               data["work_sessions"], sum(p["calls_total"] for p in on), listing)]
    out += source_warns(data, journal_shown)
    if on and data["scan"].get("oldest") is None:
        out.append("%sno transcript under the projects folder of the home of Claude Code: nothing is known of the use of "
                   "the packs that are on" % WARN)
    by_hand = [p for p in on if p["journal_state"] != "enable"]
    if by_hand and not data["journal_note"]:
        # shown for the reader, not a path to expand
        out.append('%son, and the last line of the journal does not say so (turned on by hand, or before the journal): %s: '
                   'the days to "no call in %d days" are not counted there, nor to the reviews of a pack the journal never '
                   'enabled (~/bin/claude-pack disable <pack> and then enable <pack> in the project writes the line)'
                   % (WARN, grouped(by_hand, lambda p: p["name"]), w["days"]))
    # the time on without a break: a pack turned off and on again starts its days anew
    old = [p for p in on if p["journal_state"] == "enable" and (today - p["on_since"]).days >= w["days"]]
    oldest = data["scan"].get("oldest")
    if old and (oldest is None or oldest > w["first"]):
        out.append('%sthe transcripts start on %s, later than the %d days: "no call in %d days" is not judged'
                   % (WARN, oldest or "no day", w["days"], w["days"]))
    else:
        idle = [p for p in old if p["work"] and not p["calls_total"]]
        if idle:
            out.append("%sno call in %d days: %s: ADR-007 turns such a pack off in the project (~/bin/claude-pack disable "
                       "<pack> there)" % (WARN, w["days"], grouped(idle, lambda p: "%s: on since %s, %d session(s) with an edit"
                                                                   % (p["name"], p["on_since"], p["work"]))))
    for f in fill:
        if f["pct"] >= FILL_WARN or f["cut"]:
            cut = "; %d description(s) of pack skills cut" % f["cut"] if f["cut"] else ""
            out.append("%sthe skill list of %s: %d chars at the start of its last session (%s), %d%% of about %d%s: what "
                       "does not fit keeps its bare name, the least used first (~/bin/claude-pack disable a pack there, or "
                       "turn off skills of the account)" % (WARN, f["name"], f["chars"], f["day"], f["pct"], data["limit"], cut))
    for r in data["reviews"]:
        if r["due"]:
            days = " and ".join(str(d) for d in r["due"])
            out.append("%spack %s: %d days since its first enable (%s, %s), the review of day %s is not recorded (in the "
                       "planned review of the base: ~/bin/claude-metrics --packs and a sample of 5-10 sessions; then "
                       "~/bin/claude-pack review %s --day %d)" % (WARN, r["pack"], r["days"], r["first_enable"], r["name"],
                                                                   days, r["pack"], r["due"][0]))
    return out
