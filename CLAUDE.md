# claude-code-base: репо бази налаштувань Claude Code

- Це клон публічного релізу. Файли репо не правити: живий `~/.claude` ставиться з тегу за README.md (`bash scripts/install.sh <тег> --dry-run`, показати план, потім без `--dry-run`; перше встановлення з `--force-drift`).
- `install.sh`, `rollback.sh` і `restore.sh --apply` змінюють живий `~/.claude`: лише на прохання користувача, з планом перед тим; дозволу вони питають завжди (`.claude/settings.json`).
- Своє (правила, мова, дозволи): `~/.claude/rules/<своє>.md` і `.claude/settings.local.json` проєктів, не керовані файли бази.
- Перевірка після встановлення: `bash scripts/doctor.sh --live` (код 0, `drift 0`, `commit scan: OK`).
- Пропозиції змін: issue чи PR; автор переносить їх у свою базу, вони виходять наступним тегом.
- Своя копія з власними змінами (форк, свої теги): лише за циклом `docs/FORK.md`.
