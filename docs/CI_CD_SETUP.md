# CI/CD Setup

## Обзор

Проект использует GitHub Actions для автоматического тестирования и проверки качества кода при каждом push и pull request.

## Workflow: CI

Файл: `.github/workflows/ci.yml`

### Триггеры

- Push в ветки `main`, `develop`
- Pull request в ветки `main`, `develop`

### Jobs

#### 1. lint-and-test

Запускается на Ubuntu с Python 3.11 и 3.12.

**Шаги:**
1. Checkout кода
2. Установка Python
3. Кэширование pip пакетов
4. Установка зависимостей
5. **Lint с ruff** - проверка стиля кода
6. **Format check с black** - проверка форматирования
7. **pytest** - запуск тестов с coverage
8. **Coverage check** - проверка что coverage ≥ 60%
9. **Upload to Codecov** - загрузка отчёта в Codecov (опционально)

#### 2. security-check

Проверка безопасности кода и зависимостей.

**Шаги:**
1. **safety** - проверка уязвимостей в зависимостях
2. **bandit** - статический анализ безопасности кода

#### 3. docker-build

Проверка что Docker образ собирается корректно.

**Шаги:**
1. Build Docker image
2. Smoke test - проверка импортов

## Локальный запуск проверок

### Установка dev зависимостей

```bash
pip install -r requirements-dev.txt
```

### Запуск линтера

```bash
# Ruff - быстрая проверка
ruff check .

# Ruff с автофиксом
ruff check . --fix

# Black - проверка форматирования
black --check .

# Black - применить форматирование
black .
```

### Запуск тестов

```bash
# Все тесты
pytest

# С coverage
pytest --cov=. --cov-report=term-missing

# Только быстрые тесты
pytest -m "not slow"
```

### Проверка безопасности

```bash
# Проверка зависимостей
safety check

# Проверка кода
bandit -r .
```

### Docker build

```bash
# Собрать образ
docker build -t marketplace-news-bot:test .

# Запустить smoke test
docker run --rm marketplace-news-bot:test python -c "import database.db; import services.gemini_client; print('✅ OK')"
```

## Конфигурация

### ruff.toml

Настройки для ruff linter:
- Line length: 100
- Target: Python 3.11+
- Enabled rules: E, W, F, I, N, UP, B, C4, DTZ, T10, PIE, T20
- Excluded: `.git`, `__pycache__`, `.venv`, `data`, `logs`

### pyproject.toml

Настройки для black и pytest:
- **Black**: line-length 100, target py311/py312
- **Pytest**: testpaths, markers, coverage options
- **Coverage**: exclude tests, venv, data; fail-under 60%

## Badge для README

После настройки можно добавить badge в README.md:

```markdown
![CI](https://github.com/USERNAME/marketplace-news-bot/workflows/CI/badge.svg)
[![codecov](https://codecov.io/gh/USERNAME/marketplace-news-bot/branch/main/graph/badge.svg)](https://codecov.io/gh/USERNAME/marketplace-news-bot)
```

## Troubleshooting

### Ошибка "ruff not found"

```bash
pip install ruff
```

### Ошибка "coverage below 60%"

Добавьте тесты или понизьте порог в:
- `.github/workflows/ci.yml` (строка `--fail-under=60`)
- `pyproject.toml` (`fail_under = 60`)

### Docker build fails

Проверьте:
1. `Dockerfile` корректен
2. Все зависимости в `requirements.txt`
3. Нет hardcoded путей

## Дальнейшие улучшения

1. **Pre-commit hooks** - автоматическая проверка перед коммитом
2. **Auto-deploy** - автоматический деплой после merge в main
3. **Notifications** - уведомления в Slack/Telegram при падении тестов
4. **Performance tests** - тесты производительности
5. **Integration tests** - полный end-to-end тест
