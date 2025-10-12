# 🛡️ Backup Runbook — Marketplace News Bot

## 🎯 Цель

Обеспечить резервное копирование и быстрое восстановление базы данных `marketplace_news.db` без простоя сервиса.

## 📦 Что входит

- Скрипты:  
  - `scripts/backup_db.sh` — создаёт snapshot базы  
  - `scripts/restore_db.sh` — восстанавливает базу из snapshot
- Конфигурация: backups хранятся в `./backups/` (переопределяется переменными `BACKUP_DIR`, `DB_PATH`)

## ✅ Предварительные условия

- Контейнер `marketplace-listener` запущен (или доступ к каталогу проекта локально)
- SQLite установлен (опционально, для проверки `PRAGMA integrity_check`)
- Хранилище c достаточным свободным местом под бэкапы

## 💾 Создание резервной копии

```bash
# Локально
./scripts/backup_db.sh

# Внутри контейнера Docker
docker exec marketplace-listener /app/scripts/backup_db.sh
```

Результат: файл `backups/marketplace_news_<YYYYmmdd_HHMMSS>.db`.

Переопределить пути:

```bash
DB_PATH=/custom/path.db BACKUP_DIR=/mnt/backups ./scripts/backup_db.sh
```

## ♻️ Восстановление

```bash
# Останови listener, чтобы не получить блокировку
docker-compose stop marketplace-listener

# Восстанови из конкретного бэкапа
./scripts/restore_db.sh backups/marketplace_news_20250101_090000.db

# Запусти listener снова
docker-compose up -d marketplace-listener
```

Скрипт автоматически создаёт safety-copy текущей БД (`backups/marketplace_news_pre_restore_<timestamp>.db`).

## 🔍 Проверка

```bash
# Проверка целостности SQLite
sqlite3 data/marketplace_news.db "PRAGMA integrity_check;"

# Быстрый smoke-test
pytest tests/test_database.py -k published --maxfail=1
```

## 📅 Рекомендуемый график

- Ежедневно: `./scripts/backup_db.sh`
- Еженедельно: копировать свежий snapshot во внешнее хранилище
- После релиза: выполнить дополнительный бэкап вручную

Пример cron (на хосте):

```cron
0 2 * * * cd /root/marketplace-news-bot && ./scripts/backup_db.sh >> logs/backup.log 2>&1
```

## 🆘 Аварийный чек-лист

1. Зафиксировать инцидент в логах/трекере
2. Остановить `marketplace-listener`
3. Восстановить последнюю проверенную копию
4. Прогнать `sqlite3 ... PRAGMA integrity_check`
5. Перезапустить контейнер и убедиться, что healthcheck → `healthy`
6. Обновить дорожную карту/журнал миграции
