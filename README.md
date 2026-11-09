# claude-code-base

База налаштувань Claude Code для macOS: глобальні правила, хуки-охоронці, правила за шляхами, скіли, агенти-рев'юери й інструменти. Вони ставляться в `~/.claude` копією одного тегу, з маніфестом, знімком попереднього стану і відкатом однією командою. Це публічний експорт моєї робочої бази: те саме, крім особистого. Правила, повідомлення хуків і скіли українською.

English: [README.en.md](README.en.md).

## Що всередині

| Тека | Що там | Куди ставиться |
|---|---|---|
| `global/` | глобальні правила, `settings.json` з хуками й дозволами, `home-agents.md`, рядки git ignore | `~/.claude/CLAUDE.md`, `~/.claude/settings.json`, `~/AGENTS.md`, `~/.config/git/ignore` (рядки лише дописуються) |
| `hooks/` | bash-guard (питає чи не пускає небезпечні команди: знищення даних, обхід git-хуків, підміну автора, секрети в коміті), secret-guard (секрет у промпті), commit-leaks (gitleaks у кожному коміті, його запускає git), dup-guard, doc-reminder, session-hint, node-std, nvm-env, docs-sync; тести `test-all.sh` | `~/.claude/hooks/` |
| `rules/own/` | правила, які вантажаться, коли Claude торкається файлів з їхніх `paths:` (backend, frontend, БД, deploy, залежності, чистий код, демо) | `~/.claude/rules/` |
| `skills/` | new-project (проєкт за стандартом: Node, pnpm, Docker), client-tz (ТЗ і кошторис у Word), time-register (реєстр часу сесій і оцінки), 5 скілів ECC | `~/.claude/skills/` |
| `agents/` | рев'юери: code-reviewer, security-reviewer, typescript-reviewer, react-reviewer, database-reviewer, architect (ECC), silent-failure-hunter (Anthropic) | `~/.claude/agents/` |
| `tools/` | claude-time (час сесій за проєктами й задачами), claude-metrics (метрики роботи до і після релізів) | `~/bin/` |
| `vendor/ecc/` | звідки кожен скіл і агент ECC, локальні відмінності (`patches/`) | `ECC-PIN.md` у `~/.claude/` |
| `scripts/`, `tests/` | install, rollback, doctor, verify, знімки, project-doctor; тести й гейти | не ставляться (крім `legacy/ecc-drift.sh` у `~/bin/`) |

Що робить кожен хук, скрипт і інструмент, кажуть їхні заголовки. Перелік керованих файлів виводиться з розкладки репо (`scripts/lib.sh`, `managed_items`). Решту `~/.claude` install не чіпає: плагіни, `~/.claude.json`, транскрипти, memory, свої скіли, агенти й правила з іншими назвами.

## Вимоги

- macOS на Apple Silicon з Homebrew: хуки беруть `/opt/homebrew/bin/python3` і gitleaks звідти.
- Claude Code: застосунок або CLI.
- Інструменти:

  ```bash
  brew install git jq gitleaks shellcheck python coreutils
  ```

  `git --version` 2.54 чи новіший (з цієї версії git сам запускає commit-leaks на кожен коміт), `python3 --version` 3.11 чи новіший; Homebrew першим у PATH.
- Для `/new-project` ще `brew install uv osv-scanner` і Docker Desktop.

## Перше встановлення

1. Склонуйте репо поза `~/WebstormProjects` (інструменти вважають кожну теку там проєктом), наприклад у `~/claude-code-base`:

   ```bash
   git clone <адреса цього репо> ~/claude-code-base
   ```

2. План, нічого не пише:

   ```bash
   cd ~/claude-code-base && bash scripts/install.sh "$(git tag --sort=-v:refname | head -n 1)" --dry-run
   ```

   Якщо у `~/.claude` вже є ваші `CLAUDE.md`, `settings.json`, хуки, скіли чи агенти з тими самими назвами, план перелічить їх після рядка `differ from <тег>` і закінчиться кодом 3 і рядком `would stop on the drift above`: для першого встановлення це нормально. Що з них хочете зберегти, перенесіть в особистий шар (нижче).
3. Встановлення:

   ```bash
   cd ~/claude-code-base && bash scripts/install.sh "$(git tag --sort=-v:refname | head -n 1)" --force-drift
   ```

   Маніфесту ще немає, тож кожен ваш файл, відмінний від тегу, рахується дрейфом: тому `--force-drift` (якщо план був без дрейфу, прапорець нічого не міняє). Замінене лягає в знімок `~/claude-backups/setup-snapshots/<час>-pre-install-<тег>/replaced/`.
4. Перезапустіть усі сесії Claude (застосунок і CLI) і перевірте:

   ```bash
   cd ~/claude-code-base && bash scripts/doctor.sh --live
   ```

   Очікувано: код 0, `live = <тег>, drift 0`, рядок `commit scan: OK`. WARN про проєкти, документи чи docs-sync це підказки, не збій.
5. У новій сесії попросіть Claude виконати `git commit --no-verify -m test`: bash-guard не пустить команду і скаже чому.

## Особистий шар

- Свої правила й уподобання (мова відповідей, стиль, інструменти): `~/.claude/rules/<своє>.md` без `paths:` у frontmatter, такий файл Claude Code вантажить на старті кожної сесії. Назва не має збігатися з правилом бази (`rules/own/`): файл з такою назвою база вважає своїм, і наступний install зупиниться з кодом 3.
- Налаштування й дозволи проєкту: `<проєкт>/.claude/settings.local.json`.
- Керовані файли не правте: зміна це дрейф, `doctor.sh --live` її покаже, а наступний install зупиниться з кодом 3. У `settings.json` пише і застосунок (плагін, дозвіл «завжди», тема), це теж дрейф.

## Оновлення

```bash
cd ~/claude-code-base && git pull --ff-only && git fetch --tags
bash scripts/install.sh "$(git tag --sort=-v:refname | head -n 1)" --dry-run
```

Що змінилось: [CHANGELOG.md](CHANGELOG.md). Якщо план без дрейфу, та сама команда без `--dry-run`, потім перезапуск сесій і `doctor.sh --live`. Дрейф означає, що змінено керований файл: перенесіть зміну в особистий шар, тоді `--force-drift` (змінений файл лишиться в знімку).

## Відкат

- На попередній тег: `bash scripts/rollback.sh <тег>` у теці репо, потім перезапуск сесій.
- До стану до бази: знімок першого встановлення, спершу пробний прогін, потім `--apply`:

  ```bash
  ls ~/claude-backups/setup-snapshots/
  bash ~/claude-backups/setup-snapshots/<час>-pre-install-<перший тег>/restore.sh
  bash ~/claude-backups/setup-snapshots/<час>-pre-install-<перший тег>/restore.sh --apply
  ```

  `restore.sh` нічого не видаляє: усе, що він замінює чи прибирає, спершу кладе в `displaced-<час>/` того ж знімка.
- Claude не може виконати жодної команди (хук не пускає все): у чаті попросіть «інструментом Edit прибери ключ `hooks` з `~/.claude/settings.json`», відкрийте нову сесію і зробіть відкат.

## Відомі межі

- Лише macOS на Apple Silicon з Homebrew. Правила, повідомлення хуків і скіли українською, і глобальні правила просять відповідати українською; інша мова: своє правило в особистому шарі.
- `settings.json` керований повністю: ваші ключі там (плагіни, модель, дозволи) install замінить, а окремого файла налаштувань користувача поруч Claude Code не читає. Особисте лише в `~/.claude/rules/` і в проєктах.
- Проєкти очікуються в `~/WebstormProjects`: там їх шукають claude-time, claude-metrics, doctor (для doctor і project-doctor інша тека через `PROJECTS_DIR`) і docs-sync. claude-metrics не рахує сесій у теці `claude-code-base` (сама база); дні рахує за Києвом, вікна «до» і «після» за замовчуванням з моєї історії (свої: `--before`, `--after`).
- docs-sync (дзеркало документів проєктів у `~/project-docs`), ecc-drift (клон ECC у `~/ai-stack/everything-claude-code`) і claude-time нічого не роблять, доки ви їх не запустите чи не підключите.
- Хуки-охоронці страхують від помилок моделі, а не від людини: їхня логіка відкрита.
- Сповіщення про новий тег немає: оновлення вручну. Теги calver `vYYYY.MM.N` з моєї бази, пропуски номерів нормальні.

## Внески

Issues і PR приймаю як пропозиції: зміну я переношу у свою базу, і вона виходить наступним тегом; сам PR закривається без злиття. У `main` і теги пушу лише я.

## Ліцензія

MIT ([LICENSE](LICENSE)). Скіли й агенти ECC і silent-failure-hunter мають свої ліцензії: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
