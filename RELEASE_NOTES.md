# 🚀 Release Notes — Version 2.1.0

**Release Date:** October 13, 2025  
**Status:** ✅ Ready for Production

Marketplace News Bot 2.1.0 завершает этап F (DevOps & Operations) и переводит систему в режим полностью автоматизированного сопровождения: код проверяется до коммита, контейнеры мониторятся healthcheck’ом, логи ротуются, а база покрыта резервными копиями.

---

## ✨ Основные улучшения

### 🧹 Контроль качества кода

- Добавлен pre-commit pipeline (ruff, black, isort, markdownlint, detect-secrets) — предотвращает стилистические и security-ошибки до коммита.
- Расширены dev-зависимости (`requirements-dev.txt`) и инструкции (README, инструкция выполнения) для быстрого онбординга.

### 🩺 Здоровье инфраструктуры

- Docker listener получил `healthcheck` на основе heartbeat-файла (`docker/healthcheck.py`) и `restart: always`.
- В Dockerfile добавлен пакет `logrotate`, healthcheck продублирован на уровне образа (`HEALTHCHECK`).
- README/Quick Start подчёркивают, что `docker-compose ps` должен показывать `healthy`.

### 🗄 Логи и резервные копии

- `configure_logging` теперь поддерживает вращающиеся хендлеры с настройкой из config (`logging.rotate`).
- Добавлена конфигурация `docker/logrotate.conf` и раздел README «Ротация логов».
- Скрипты `scripts/backup_db.sh` и `scripts/restore_db.sh` с runbook (`docs/backup_runbook.md`) формализуют процесс бэкапа/восстановления.
- Makefile получил обновлённые цели `db-backup` и `db-restore`.

### ✅ Тесты и документация

- Новый тест `tests/test_healthcheck.py` валидирует сценарии heartbeat (актуальный/устаревший файл).
- Дорожная карта обновлена (версия 2.1.0, статус Stage F закрыт), добавлен журнал сессии 16.
- README, QUICK_START и инструкция дополняют разделами про pre-commit, healthcheck, лог-орбиту и бэкапы.

---

## 🔍 Проверки

| Тип | Команда | Результат |
|-----|---------|-----------|
| Lint & Hooks | `pre-commit run --all-files` | ✅ Без ошибок |
| Unit Tests | `pytest tests/test_healthcheck.py` | ✅ Пройдено |
| Docker Health | `docker-compose ps` (listener) | ✅ `healthy` |
| Бэкап | `./scripts/backup_db.sh && ./scripts/restore_db.sh` | ✅ Smoke-test |

---

## 📦 Артефакты релиза

- `.pre-commit-config.yaml` — настроенный набор хуков.
- `docker/healthcheck.py` + Dockerfile `HEALTHCHECK`.
- `docker/logrotate.conf` — базовый профайл logrotate.
- `scripts/backup_db.sh`, `scripts/restore_db.sh` и runbook `docs/backup_runbook.md`.
- `docs/deploy_checklist.md` — пошаговый деплой-гайд и инструкции по тегированию v2.1.0.
- Обновлённые рабочие инструкции (README, QUICK_START, INSTRUKTSIYA_VYPOLNENIYA.md).

---

## 🚀 Чек-лист апгрейда

1. `pip install -r requirements-dev.txt` — убедиться, что pre-commit установлен.
2. `pre-commit install && pre-commit run --all-files` — локальная валидация перед коммитами.
3. `docker-compose build --no-cache` — собрать образ с logrotate/healthcheck.
4. `docker-compose up -d marketplace-listener` — перезапустить listener (статус → `healthy`).
5. `./scripts/backup_db.sh` — создать fresh-бэкап после релиза.

---

## 🆘 Известные оговорки

- Healthcheck опирается на heartbeat listener’а. Если бот не получает сообщений >3 минут, heartbeat всё равно обновляется фоновым таском, однако при ручном останове необходимо корректно вызвать `stop()`.
- Для выполнения `docker exec ... logrotate` внутрь контейнера должен заходить пользователь с правами root (по умолчанию так и есть в образе).
- Скрипты бэкапа/восстановления работают с путями по умолчанию; при кастомном деплое задействуйте переменные `DB_PATH` и `BACKUP_DIR`.

---

**Дальше:** создать git-тег `v2.1.0`, обновить релиз в трекере и запланировать деплой.
