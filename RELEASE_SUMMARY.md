# 🎉 Release v2.1.0 Summary — Marketplace News Bot

**Release Date:** October 13, 2025  
**Status:** ✅ READY TO SHIP  
**Focus:** Stage F — Operations & DevOps hardening

---

## ✅ Что сделано

### Dev Experience

- Pre-commit конфигурация (ruff, black, isort, markdownlint, detect-secrets) + dev-зависимости.
- README, Quick Start и инструкция пополнились разделами про хуки и проверку перед коммитом.

### Runtime & Observability

- Docker listener с `restart: always` и healthcheck на heartbeat (`docker/healthcheck.py`).
- Dockerfile включает logrotate; образ содержит `HEALTHCHECK` для единообразия.
- Логирование через RotatingFileHandler (настраивается через `logging.rotate`), доступен `docker/logrotate.conf`.

### Data Safety

- Скрипты `scripts/backup_db.sh` / `scripts/restore_db.sh`, runbook `docs/backup_runbook.md`, Makefile цели `db-backup`, `db-restore`.
- Smoke-test: бэкап → восстановление → `PRAGMA integrity_check`.

### Тесты & Документация

- Добавлен unit-тест `tests/test_healthcheck.py` (валидирует свежий/устаревший heartbeat).
- Дорожная карта обновлена до версии 2.1.0, зафиксирована сессия 16 и новая «Следующая задача».

---

## 🔍 Верификация

| Проверка | Команда | Результат |
|----------|---------|-----------|
| Pre-commit | `pre-commit run --all-files` | ✅ |
| Unit-test | `pytest tests/test_healthcheck.py` | ✅ |
| Docker health | `docker-compose ps` (listener) | ✅ `healthy` |
| Backup | `./scripts/backup_db.sh && ./scripts/restore_db.sh` | ✅ |

---

## 📦 Артефакты

- `.pre-commit-config.yaml`, `.secrets.baseline` (baseline detect-secrets)
- `docker/healthcheck.py`, `docker/logrotate.conf`
- `scripts/backup_db.sh`, `scripts/restore_db.sh`
- `docs/deploy_checklist.md` — пошаговый гайд для выкладки и тегирования
- Обновлённые docs: `README.md`, `QUICK_START.md`, `docs/backup_runbook.md`, `DOROZHNAYA_KARTA.md`

---

## 📄 Следующие действия

1. 🎯 Создать git-тег `v2.1.0` и зафиксировать релиз в трекере.
2. 🚀 Выполнить выкладку по `docs/deploy_checklist.md` (пошагово).
3. 🛡 Настроить cron/CI для ежедневных бэкапов (см. runbook).

---

**Готово к выкладке.**
