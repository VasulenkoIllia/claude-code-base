"""Printing: the before/after table and its counts, window warnings, the weekly table."""
from datetime import date, timedelta

from .patterns import CONDITIONAL, LANG_KINDS, PRELOAD, SERVER_DAY_MAX, WAIT_LONG_S
from .summary import summarize

ROWS = (  # key, label, format, better ("down", "up" or "" when the direction is not a goal)
    ("P_per_day", "Промптів на активний день", "{:.1f}", ""),
    ("requests_per_day", "API-запитів на активний день", "{:.0f}", ""),
    ("ctx_mean", "Контекст запиту, середнє", "{:,.0f}", "down"),
    ("ctx_median", "Контекст запиту, медіана", "{:,.0f}", "down"),
    ("ctx_over_400k_pct", "Запити понад 400K, %", "{:.1f}", "down"),
    ("ctx_over_500k_pct", "Запити понад 500K, % (B1)", "{:.1f}", "down"),
    ("weighted_per_P_m", "Зважена ціна на промпт, млн од.", "{:.2f}", "down"),
    ("sub_weighted_pct", "Частка субагентів у ціні, %", "{:.1f}", ""),
    ("cost_per_commit_m", "Ціна на коміт за пушами, млн од.", "{:.2f}", "down"),
    ("cost_per_100_lines_m", "Ціна на 100 змінених рядків, млн од.", "{:.2f}", "down"),
    ("no_push_weighted_pct", "Частка ціни сесій без пушу, %", "{:.1f}", ""),
    ("output_per_request", "Вихідних токенів на запит", "{:.0f}", ""),
    ("compactions_per_100P", "Стискань на 100 промптів", "{:.2f}", ""),
    ("compact_pre_median", "Поріг стискання (медіана)", "{:,.0f}", "down"),
    ("startup_median", "Старт сесії (медіана)", "{:,.0f}", "down"),
    ("idle_per_day", "Перепис кешу після паузи 1 год, на день", "{:.2f}", "down"),
    ("simplify_per_day", "«Спрости», на активний день", "{:.2f}", "down"),
    ("simplify_per_100P", "«Спрости», на 100 промптів", "{:.2f}", "down"),
    ("simplify_audit_per_day", "«Спрости» (regex аудиту), на день", "{:.2f}", "down"),
    ("browser_per_day", "Дій у браузері на день", "{:.1f}", ""),
    ("screenshots_per_day", "Скриншотів на день", "{:.1f}", ""),
    ("browser_error_pct", "Помилки браузера, %", "{:.1f}", "down"),
    ("ui_narrow_pct", "UI-дні з перевіркою вужче 900px, %", "{:.0f}", "up"),
    ("hook_asks_per_day", "Ask хуків на день", "{:.2f}", ""),
    ("perm_asks_per_day", "Запитів дозволу на день", "{:.1f}", "down"),
    ("sleep_per_day", "sleep у Bash на день", "{:.2f}", "down"),
    ("module_missing_per_day", "Відсутній модуль, на день", "{:.2f}", "down"),
    ("py_crash_per_day", "Падіння Python, на день", "{:.2f}", "down"),
    ("dup_guard_per_day", "Підказок dup-guard на активний день", "{:.2f}", ""),
    ("lang_en_pct", "Тексти власнику англійською, %", "{:.1f}", "down"),
    ("lang_compact_en_pct", "Те саме після стискання в сесії, %", "{:.1f}", "down"),
)
COUNTS = ("P", "active_days", "paste_skipped", "compactions", "startup_n", "ui_days", "hook_blocks", "hook_asks",
          "perm_asks", "perm_long_waits",
          "redo_strict", "redo_candidates", "done_candidates", "skill_calls", "agent_calls", "reviewer_calls",
          "workflow_calls", "workflow_agents", "react_cov", "db_cov", "prisma_errors", "prisma_resolve",
          *("preload_cov:" + a for a in PRELOAD), *(k + s for s in CONDITIONAL for k in ("cond_shown:", "skill_calls:")),
          "dup_guard", "push_commits", "push_lines", *("lang:" + k for k in LANG_KINDS))
PERM_COUNTS = ("perm_asks", "perm_long_waits")
MIN_DAYS = 5  # fewer active days in a window: no +/- marks, the rates swing too much
STARTUP_TOP = 10  # projects in the list of session starts
LANG_MIN_P = 20  # from this many prompts in the "after" window the app's tools must show up, or the language rows lie
LANG_APP_KINDS = ("wrap_up", "plan")  # none before the app's tools (mid-October), so only the "after" window is checked
LANG_LABELS = {"chat": "репліки чату", "wrap_up": "wrap_up", "plan": "плани update_plan", "quiz": "квізи"}
PERM_LABELS = {"ssh_read": "ssh, читання", "ssh_write": "ssh, зміна", "push": "git push", "merge": "gh pr merge",
               "guard": "bash-guard", "other": "інше"}


def fmt(value, pattern):
    return "-" if value is None else pattern.format(value).replace(",", " ")


def window_warnings(s, name, first_day):
    """Signs that a window's numbers are not real: no data, too little data, or a field the scan no longer finds."""
    a, _b = (date.fromisoformat(x) for x in s["window"].split(".."))
    out = []
    if first_day and a < first_day:
        out.append(f"вікно «{name}» починається {a}, а найстаріший транскрипт {first_day}: старі дні вже видалено, "
                   "цифри неповні")
    if not s["active_days"]:
        out.append(f"у вікні «{name}» ({s['window']}) немає жодного активного дня")
    elif s["active_days"] < MIN_DAYS:
        out.append(f"у вікні «{name}» лише {s['active_days']} активн. дн.: вибірка мала")
    if s["P"] and not s["requests_per_day"]:
        out.append(f"вікно «{name}»: є промпти, але 0 API-запитів; схоже, змінився формат транскриптів (usage)")
    if s["P"] and s["ctx_mean"] is None:
        out.append(f"вікно «{name}»: є промпти, але немає контексту запитів; схоже, змінився формат транскриптів")
    gone = [LANG_LABELS[k] for k in LANG_APP_KINDS if s["lang:" + k].endswith("/0")]
    if name == "після" and s["P"] >= LANG_MIN_P and gone:
        out.append(f"вікно «після»: {s['P']} промптів, але 0 текстів: {', '.join(gone)}; схоже, застосунок змінив "
                   "інструмент чи його поле, і рядки мови неповні (claude_metrics/language.py)")
    if name == "після" and s["P"] >= LANG_MIN_P and not s["perm_seen"]:
        out.append(f"вікно «після»: {s['P']} промптів, але жодного permissionDecision; схоже, змінився формат транскриптів, "
                   "і запитів дозволу не видно (claude_metrics/asks.py)")
    return out


def print_startup(after):
    """Context of the first request by project in the "after" window: the check of the state-files rule."""
    rows = after["startup_by_project"]
    print(f"\nСтарт сесії за проєктами, вікно «після» ({min(len(rows), STARTUP_TOP)} з {len(rows)}, більше сесій вгорі):")
    for name, sessions, median in rows[:STARTUP_TOP]:
        print(f"  {name[:38]:38} {sessions:>5} сес. {fmt(median, '{:,.0f}'):>10}")


def count_cell(s, key):
    """A count of the summary: a window with no permissionDecision (before 2026-10-08) has no count of prompts."""
    return "-" if key in PERM_COUNTS and not s["perm_seen"] else str(s[key])


def print_permissions(s):
    """Real permission prompts of the "after" window: the check of the owner's targets of 30.10."""
    if not s["perm_seen"]:
        return
    print(f"\nЗапити дозволу, вікно «після» ({s['perm_asks']}, разом {s['perm_wait_h']:.1f} год з виконанням):")
    print(f"  {'вид':14} {'запитів':>8} {'медіана, с':>11} {'макс., с':>9} {'> ' + str(WAIT_LONG_S // 60) + ' хв':>7}")
    for kind, count, median, longest, long_waits in s["perm_rows"]:
        print(f"  {PERM_LABELS[kind]:14} {count:>8} {median:>11.0f} {longest:>9.0f} {long_waits:>7}")
    print(f"  сесія-днів із ssh: {s['perm_server_days']}, запитів на такий день: медіана {fmt(s['perm_server_median'], '{:.0f}')}, "
          f"максимум {fmt(s['perm_server_max'], '{:.0f}')}, понад {SERVER_DAY_MAX}: {s['perm_server_over']}")


def print_compare(before, after):
    marks = min(before["active_days"], after["active_days"]) >= MIN_DAYS
    print(f"{'Метрика':42} {'до ' + before['window']:>24} {'після ' + after['window']:>26} {'зміна':>8}")
    for key, label, pattern, better in ROWS:
        x, y = before[key], after[key]
        change = ""
        if x not in (None, 0) and y is not None:
            delta = 100 * (y - x) / x
            mark = "" if not better or not marks or abs(delta) < 5 else (" +" if (delta < 0) == (better == "down") else " -")
            change = f"{delta:+.0f}%{mark}"
        print(f"{label:42} {fmt(x, pattern):>24} {fmt(y, pattern):>26} {change:>8}")
    print()
    labels = {"P": "промптів", "active_days": "активних днів", "paste_skipped": "з них вставок логів (без текст-метрик)",
              "compactions": "стискань", "startup_n": "стартів сесій",
              "ui_days": "UI проєкт-днів", "hook_blocks": "блоків хуків PreToolUse", "hook_asks": "ask хуків",
              "perm_asks": "запитів дозволу (усі види)", "perm_long_waits": f"з них чекали понад {WAIT_LONG_S // 60} хв",
              "redo_strict": "«переробити» (точно)", "redo_candidates": "«переробити» (кандидати)",
              "done_candidates": "«готово», потім баг (кандидати)", "skill_calls": "викликів скілів",
              "agent_calls": "викликів агентів", "reviewer_calls": "з них рев'юерів", "workflow_calls": "викликів Workflow",
              "workflow_agents": "агентів workflow", "react_cov": "коміти з .tsx (не Light) під react-reviewer",
              "db_cov": "коміти з БД під database-reviewer", "prisma_errors": "помилок історії Prisma",
              "prisma_resolve": "migrate resolve --applied", "dup_guard": "підказок dup-guard",
              "push_commits": "комітів Claude, що дійшли до remote", "push_lines": "змінених рядків у них, без lock і бінарних",
              **{"lang:" + k: f"{v}: англійською / усього" for k, v in LANG_LABELS.items()},
              **{"preload_cov:" + a: f"запуски {a} з preload скіла" for a in PRELOAD},
              **{"cond_shown:" + s: f"сесії з показом {s} → Skill" for s in CONDITIONAL},
              **{"skill_calls:" + s: f"викликів Skill {s}" for s in CONDITIONAL}}
    for key in COUNTS:
        print(f"{labels[key]:42} {count_cell(before, key):>24} {count_cell(after, key):>26}")
    print_startup(after)
    print_permissions(after)
    print(f"\nЗміна: «+» краще, «-» гірше за метою метрики; зміна менше 5% або вікно з менш ніж {MIN_DAYS} "
          "активними днями не позначається. "
          "Кандидатів «переробити» і «готово, потім баг» розмічає людина чи ШІ (--candidates). "
          "Запит дозволу: те, що власник мусив підтвердити (permissionDecision, є з 2026-10-08; квізи не рахуються); час "
          "від виклику до результату, тобто з виконанням команди. ssh, читання: без слів, що змінюють сервер (оцінка). "
          "Текст англійською: латиниці більш ніж утричі більше, ніж кирилиці, і не менше 20 літер, без коду, посилань і "
          "шляхів; лише основні сесії. "
          "Рев'ю всередині Workflow у покритті комітів не видно. "
          "Preload, показ скілів за paths: і dup-guard є з B5 (v2026.10.9), тому «до» їх майже немає. "
          "Ціна на коміт (B5.1): уся ціна сесії, у якої є коміт Claude, що дійшов до remote-гілки, ділиться порівну "
          "між її такими комітами і йде на день коміту; рядки за git numstat без lock-файлів і бінарних; git лише "
          "читається, без fetch.")


def print_weekly(acc, since, until):
    """One row per ISO week; '*' marks a week cut by --since or by today, labelled with its first counted day."""
    start = since - timedelta(days=since.weekday())
    print(f"{'тиждень':12} {'P':>5} {'дн':>3} {'ctx сер.':>9} {'>500K%':>7} {'стиск/100P':>10} {'пауза/д':>8} "
          f"{'спрости/д':>9} {'браузер/д':>9} {'sleep/д':>8} {'ask':>4} {'дозв':>5} {'>5хв':>4} {'блок':>4} {'preload':>7} {'показ':>6} {'dup':>4} "
          f"{'старт':>8} {'англ%':>6}")
    while start <= until:
        first, last = max(start, since), min(start + timedelta(days=6), until)
        s = summarize(acc, first, last)
        cut = "*" if first != start or last != start + timedelta(days=6) else " "
        print(f"{first:%d.%m.%Y}{cut}  {s['P']:5} {s['active_days']:3} {fmt(s['ctx_mean'], '{:,.0f}'):>9} "
              f"{fmt(s['ctx_over_500k_pct'], '{:.1f}'):>7} {fmt(s['compactions_per_100P'], '{:.2f}'):>10} "
              f"{fmt(s['idle_per_day'], '{:.2f}'):>8} {fmt(s['simplify_per_day'], '{:.2f}'):>9} "
              f"{fmt(s['browser_per_day'], '{:.0f}'):>9} {fmt(s['sleep_per_day'], '{:.2f}'):>8} "
              f"{s['hook_asks']:4} {count_cell(s, 'perm_asks'):>5} {count_cell(s, 'perm_long_waits'):>4} {s['hook_blocks']:4} {s['preload_cov']:>7} {s['cond_shown']:>6} {s['dup_guard']:4} "
              f"{fmt(s['startup_median'], '{:,.0f}'):>8} {fmt(s['lang_en_pct'], '{:.1f}'):>6}")
        start += timedelta(days=7)
