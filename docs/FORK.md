# Своя копія бази: цикл зміни

Для тих, хто веде форк claude-code-base під себе. Хто лише встановлює й оновлює, читає [README.md](../README.md).

## Правила

- Живі файли (`~/.claude/CLAUDE.md`, `settings.json`, хуки, правила, скіли, агенти) напряму не правте: кожна зміна йде через репо, тег і `install.sh`. Інакше це дрейф, і наступний install зупиниться з кодом 3.
- Тег ніколи не переноситься і не видаляється: виправлення виходить новим тегом. Свої теги давайте з суфіксом, наприклад `v2026.11.26-my.1`, щоб вони не зіткнулися з тегами upstream. `git tag --sort=-v:refname` ставить такий тег вище за `v2026.11.26`, але нижче за наступний тег upstream.
- Особисте тримайте в `~/.claude/rules/<своє>.md` і в проєктах, а не у файлах репо: тоді оновлення з upstream зливаються без конфліктів.

## Цикл

1. Правка в репо, потім `bash scripts/verify.sh`. Останній рядок `verify: N checks, 0 failed`. Він перевіряє JSON, shellcheck, тести хуків на копіях, межі розміру правил ([ADR-002](adr/ADR-002-claude-md-budget.md)), gitleaks дерева і стандарт нового проєкту; живих файлів не чіпає.
2. Зачепили хуки чи дозволи `global/settings.json`: `bash hooks/test-all.sh`, потім ваша історія команд за 60 днів через живі й нові хуки: `python3 -I tests/hook-replay.py --days 60`. Рядок `gate` закінчується на PASS: нових блоків і помилок 0, нових запитів дозволу в медіані не більше одного на робочий день. Правили dup-guard: ще `python3 -I tests/edit-replay.py --days 60`; doc-reminder: `python3 -I tests/commit-replay.py --days 60`; session-hint: `python3 -I tests/hint-replay.py --days 60`.
3. Зачепили `scripts/install.sh`, `lib.sh` чи `rollback.sh`: `python3 -I tests/install-drift-test.py`, рядок `0 failed`.
4. Зачепили глобальний файл чи rules: межі в байтах перевіряє verify, токени міряйте методом з ADR-002.
5. Коміт і тег, наприклад `git tag v2026.11.26-my.1`.
6. План, нічого не пише: `bash scripts/install.sh <тег> --dry-run`; у плані мають бути лише ваші зміни. Потім `bash scripts/install.sh <тег>`: знімок робиться сам.
7. Перезапуск усіх сесій Claude і `bash scripts/doctor.sh --live`: код 0, `live = <тег>, drift 0`, `commit scan: OK`.
8. Перевірка у свіжій сесії: зміна справді діє (правило вантажиться, хук питає чи блокує, скіл знаходиться). Збій: `bash scripts/rollback.sh <попередній тег>` і виправлення новим тегом.

## Оновлення з upstream

```bash
git remote add upstream <адреса claude-code-base>
git fetch upstream --tags
git merge <тег upstream>
```

Конфлікти бувають лише у файлах, які ви змінили. Після злиття той самий цикл з кроку 1 і свій тег.
