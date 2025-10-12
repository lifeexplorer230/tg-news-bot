# 🛠️ OPS PLAYBOOK
## Поддержка этапа F — Операции и DevOps

**Версия:** 1.0  
**Дата:** 2025-10-12

---

## 🎯 Цели этапа F

- Автоматизировать проверки (CI/CD, pre-commit)
- Повысить надёжность контейнеров (healthcheck, restart)
- Обеспечить управляемость логов и бэкапов
- Задокументировать эксплуатационные процедуры

---

## 📦 F1 — CI/CD (GitHub Actions)

**Проверочный чек-лист:**
- [ ] Workflow создан в `.github/workflows/ci.yml`
- [ ] Матрица Python ≥ 3.11, кеш pip активен
- [ ] Запускаются `pytest` и `ruff`
- [ ] README содержит бейдж статуса
- [ ] При push/PR workflow отображается в Actions

**Команды для быстрой проверки:**
```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('✅ YAML OK')"
gh workflow view CI --json name,path  # опционально
```

---

## 🧹 F2 — pre-commit и автоформат

**Чек-лист:**
- [ ] `pyproject.toml` настроен для `black`, `isort`, `ruff`
- [ ] `.pre-commit-config.yaml` добавлен и валидирован
- [ ] `pre-commit install` выполнен локально
- [ ] `pre-commit run --all-files` проходит без ошибок
- [ ] README/инструкции обновлены (раздел “Перед началом работы”)

**Команды:**
```bash
pre-commit run --all-files
python - <<'PY'
import tomllib
tomllib.load(open("pyproject.toml","rb"))
print("✅ pyproject.toml валиден")
PY
```

---

## ♻️ F3 — Healthcheck + restart

**Чек-лист:**
- [ ] В Dockerfile есть HEALTHCHECK
- [ ] В `docker-compose.yml` настроены `restart: unless-stopped` и `depends_on`
- [ ] `docker compose ps` показывает статус `healthy`
- [ ] Симуляция падения → контейнер перезапускается
- [ ] Логи healthcheck не захламляют stdout

**Команды:**
```bash
docker compose config
docker compose up --build -d
docker compose kill processor && sleep 5 && docker compose ps
```

---

## 📑 F4 — Log rotation

**Чек-лист:**
- [ ] `utils/logger.py` использует `dictConfig` и ротацию
- [ ] Файл `docker/logrotate.conf` создан
- [ ] `logrotate -d docker/logrotate.conf` проходит без ошибок
- [ ] Логи уходят в stdout + файл (`logs/*.log`)
- [ ] Документация обновлена (как запускать ротацию в контейнере)

**Команды:**
```bash
python - <<'PY'
from utils.logger import setup_logging, get_logger
setup_logging()
get_logger(__name__).info("rotation smoke-test")
PY

logrotate -d docker/logrotate.conf
```

---

## 💾 F5 — Бэкапы и runbook

**Чек-лист:**
- [ ] Скрипты `scripts/backup_db.sh`, `scripts/restore_db.sh` существуют и исполняемы
- [ ] Каталог `backups/` создаётся автоматически
- [ ] Runbook `docs/backup_runbook.md` описывает процесс и проверки
- [ ] Smoke-тест: бэкап → восстановление → сравнение размеров
- [ ] План расписания бэкапов (cron/docker) зафиксирован в документации

**Команды:**
```bash
./scripts/backup_db.sh data/marketplace.db backups
LATEST="$(ls -t backups/marketplace-db-*.tar.gz | head -n1)"
./scripts/restore_db.sh "$LATEST" data/marketplace_restored.db
du -h data/marketplace.db data/marketplace_restored.db
```

---

## 📘 Навигация

- Основная дорожная карта: `../DOROZHNAYA_KARTA.md`
- Детальный анализ: `../ROADMAP_ANALYSIS.md`
- Шаги выполнения: `../INSTRUKTSIYA_VYPOLNENIYA.md`
- Чек-листы проверок: `verification-protocol.md`
- Процедуры отката: `rollback-protocol.md`

---

**Примечание:** При изменении любой инструкции обязательно обновляйте версию и дату в этом playbook.
