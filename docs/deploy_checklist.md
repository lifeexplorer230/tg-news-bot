# 🚀 Deployment Checklist — Marketplace News Bot v2.1.0

## 1. Подготовка
- [ ] Синхронизировать `main` с репозиторием (`git pull`).
- [ ] Убедиться, что `pre-commit run --all-files` завершился без ошибок.
- [ ] Обновить `requirements*.txt` в прод-окружении при необходимости.
- [ ] Проверить наличие свежего бэкапа БД (`./scripts/backup_db.sh`).

## 2. Тегирование релиза
- [ ] Выполнить `git tag -a v2.1.0 -m "Release 2.1.0 — DevOps hardening"`.
- [ ] Запушить тег: `git push origin v2.1.0`.
- [ ] Обновить карточку релиза в трекере/Notion.

## 3. Сборка и выкладка
- [ ] Пересобрать образ: `docker compose build --no-cache`.
- [ ] Применить миграции/инициализацию (при первом запуске): `python main.py processor --dry-run` (опционально).
- [ ] Запустить listener: `docker compose up -d marketplace-listener`.
- [ ] Убедиться, что контейнер в статусе `healthy` (`docker compose ps`).

## 4. Пост-деплой проверки
- [ ] Проверить логи: `docker compose logs -f marketplace-listener` (нет ошибок).
- [ ] Убедиться, что heartbeat обновляется (`ls -l logs/listener.heartbeat`).
- [ ] Запустить smoke-тест обработчика: `docker compose run --rm marketplace-processor python main.py processor`.
- [ ] Проверить статусы backup-скриптов: `./scripts/backup_db.sh && ./scripts/restore_db.sh backups/latest.db` (dry-run).

## 5. Мониторинг и откат
- [ ] Добавить задачу в cron/CI на ежедневный бэкап (см. `docs/backup_runbook.md`).
- [ ] Зафиксировать релиз в `DOROZHNAYA_KARTA.md` (раздел журнал).
- [ ] В случае инцидента следовать `memory-bank/rollback-protocol.md`.

## Примечания
- Healthcheck активен в Dockerfile и docker-compose (`docker/healthcheck.py`).
- Логи ротируются автоматически (`utils/logger.py` + `docker/logrotate.conf`).
- Перед выкладкой на прод желательно прогнать `make ci-local` на staging.
