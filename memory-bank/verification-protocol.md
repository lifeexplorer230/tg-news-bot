# ✅ VERIFICATION PROTOCOL — Протокол проверки изменений

**Дата:** 2025-10-14
**Версия:** 1.0.0

---

## 🎯 Цель

Обеспечить качество каждого изменения через систематическую проверку:
- Код работает корректно
- Тесты проходят
- Документация актуальна
- Нет регрессий
- Diff size в безопасных пределах

---

## 📋 Чек-лист проверки (универсальный)

### 1. Pre-Commit Проверки

#### 1.1 Размер изменений
```bash
git diff --stat
# Проверить: < 150 строк (Safe) или < 300 строк (Warning)
```

- [ ] Diff size в пределах лимита
- [ ] Если > 150 строк — рассмотрено разбиение

#### 1.2 Синтаксис Python
```bash
python -m py_compile <измененные файлы>
```

- [ ] Все файлы компилируются без ошибок

#### 1.3 Форматирование
```bash
ruff check .
black --check .
```

- [ ] Нет ruff ошибок
- [ ] Код отформатирован через black

#### 1.4 Type hints
```bash
mypy <измененные файлы> || echo "mypy not required yet"
```

- [ ] Type hints добавлены (если применимо)
- [ ] mypy проходит (если настроен)

---

### 2. Функциональные проверки

#### 2.1 Unit тесты (если есть)
```bash
pytest tests/ -v
pytest tests/ --cov --cov-report=term-missing
```

- [ ] Все тесты проходят
- [ ] Новые тесты добавлены для новой функциональности
- [ ] Coverage не упал

#### 2.2 Integration тесты (если есть)
```bash
pytest tests/integration/ -v
```

- [ ] Integration тесты проходят
- [ ] End-to-end flow работает

#### 2.3 Smoke-тест (для критичных изменений)

Для listener:
```bash
python main.py listener &
sleep 30
kill %1
# Проверить логи
tail -20 logs/bot.log
```

- [ ] Listener запускается
- [ ] Нет ошибок в логах
- [ ] Heartbeat обновляется

Для processor:
```bash
python main.py processor
# Проверить вывод
```

- [ ] Processor запускается
- [ ] Gemini API отвечает
- [ ] Нет критичных ошибок

---

### 3. Database проверки

#### 3.1 Схема БД
```bash
sqlite3 data/news_bot.db ".schema"
```

- [ ] Все таблицы существуют
- [ ] Indexes созданы
- [ ] WAL mode включен

#### 3.2 Проверка данных
```bash
sqlite3 data/news_bot.db "SELECT COUNT(*) FROM raw_messages;"
sqlite3 data/news_bot.db "PRAGMA integrity_check;"
```

- [ ] БД не повреждена
- [ ] Данные доступны
- [ ] Нет блокировок

---

### 4. Configuration проверки

#### 4.1 Config валидность
```bash
python -c "from utils.config import load_config; c = load_config(); print('OK')"
```

- [ ] Config загружается без ошибок
- [ ] Все required ключи присутствуют
- [ ] Profile loading работает

#### 4.2 Environment variables
```bash
cat .env | grep -v "^#" | grep "="
```

- [ ] Все required env vars установлены
- [ ] Нет дублирования
- [ ] Нет незащищенных секретов

---

### 5. Documentation проверки

#### 5.1 README актуальность
```bash
grep "Version:" README.md
```

- [ ] Версия актуальна
- [ ] Новая функциональность задокументирована
- [ ] Примеры работают

#### 5.2 Memory-bank обновлен
```bash
ls -lt memory-bank/
```

- [ ] Новые проблемы добавлены в common-issues.md
- [ ] Архитектурные решения в arkhitektura.md
- [ ] Операционные процедуры в ops-playbook.md

#### 5.3 DOROZHNAYA_KARTA обновлена
```bash
grep "$(date +%Y-%m-%d)" DOROZHNAYA_KARTA.md
```

- [ ] Журнал прогресса обновлен
- [ ] Текущее состояние актуально
- [ ] Метрики обновлены

---

### 6. Security проверки

#### 6.1 Secrets scan
```bash
git diff --cached | grep -i "api_key\|password\|secret\|token" || echo "OK"
```

- [ ] Нет секретов в коде
- [ ] .env не в staged changes
- [ ] .session файлы не в staged changes

#### 6.2 Dependencies scan
```bash
pip list --outdated
```

- [ ] Нет критичных уязвимостей (если проверяете)
- [ ] Dependencies актуальны

---

### 7. Git проверки

#### 7.1 Commit message
```bash
git log -1 --pretty=%B
```

- [ ] Commit message осмысленный
- [ ] Следует формату: `type: description`
- [ ] Описывает ЧТО и ПОЧЕМУ

#### 7.2 Staged files
```bash
git diff --cached --name-only
```

- [ ] Все нужные файлы в staged
- [ ] Нет случайных файлов (temp, .pyc, etc)
- [ ] Нет конфликтов

#### 7.3 Branch status
```bash
git status
git log --oneline -5
```

- [ ] Ветка чистая (no untracked/modified)
- [ ] История линейная
- [ ] Нет merge conflicts

---

## 🚦 Критерии прохождения

### ✅ Ready to Commit

**Все следующие должны быть выполнены:**
- Diff size < 300 строк (или обоснованно больше)
- Python syntax OK
- Ruff/Black OK
- Тесты проходят (если есть)
- Smoke-тест OK (для критичных изменений)
- Документация обновлена
- Commit message написан
- Нет секретов в коде

### ⚠️ Warning — требует внимания

**Можно коммитить, но с осторожностью:**
- Diff size 150-300 строк
- Coverage слегка упал
- Минорные warnings от линтеров
- Smoke-тест показывает warnings (не errors)

### 🔴 Not Ready — блокер

**НЕ коммитить пока не исправлено:**
- Diff size > 500 строк
- Syntax errors
- Тесты падают
- Critical errors в smoke-тесте
- Секреты в коде
- БД повреждена

---

## 📊 Этап-специфичные проверки

### Этап A (Стабилизация)

**Дополнительно проверить:**
- [ ] Listener работает 5+ минут без errors
- [ ] Processor успешно обрабатывает тестовые данные
- [ ] Database WAL mode подтвержден
- [ ] FloodWait protection работает

### Этап B (Тестирование)

**Дополнительно проверить:**
- [ ] Coverage увеличился или остался >70%
- [ ] Новые тесты покрывают edge cases
- [ ] Mocks настроены правильно
- [ ] Fixtures переиспользуемые

### Этап C (Надежность)

**Дополнительно проверить:**
- [ ] Retry логика работает (тест с mock failures)
- [ ] Graceful shutdown работает (Ctrl+C тест)
- [ ] Error recovery восстанавливается
- [ ] Логи структурированы

### Этап D (Оптимизация)

**Дополнительно проверить:**
- [ ] Benchmark показывает улучшение
- [ ] Профилировщик подтверждает оптимизацию
- [ ] Memory usage не вырос
- [ ] Lazy loading работает корректно

### Этап E (DevOps)

**Дополнительно проверить:**
- [ ] CI/CD pipeline зеленый
- [ ] Pre-commit hooks работают
- [ ] Docker image собирается
- [ ] Deployment инструкции актуальны

---

## 🔧 Quick Commands

### Полная проверка (copy-paste):

```bash
echo "=== 1. Diff Size ==="
git diff --stat

echo "=== 2. Syntax Check ==="
find . -name "*.py" -not -path "*/venv/*" -exec python -m py_compile {} \;

echo "=== 3. Linters ==="
ruff check . && echo "ruff: OK" || echo "ruff: FAIL"
black --check . && echo "black: OK" || echo "black: FAIL"

echo "=== 4. Tests ==="
pytest tests/ -v --tb=short || echo "No tests yet"

echo "=== 5. Coverage ==="
pytest tests/ --cov --cov-report=term-missing || echo "No tests yet"

echo "=== 6. Git Status ==="
git status --short

echo "=== 7. Ready to commit? ==="
```

### Минимальная проверка (быстрая):

```bash
git diff --stat && \
python -m py_compile $(git diff --name-only --cached | grep ".py$") && \
echo "Ready to commit!"
```

---

## 📝 Checklist для PR Review

### Когда создаете PR:

- [ ] Все коммиты в PR прошли verification
- [ ] PR description заполнен
- [ ] Linked issue (если есть)
- [ ] Screenshots/logs (если применимо)
- [ ] Breaking changes отмечены
- [ ] Migration guide (если нужно)

### Reviewer должен проверить:

- [ ] Код соответствует style guide (pravila.md)
- [ ] Тесты достаточны
- [ ] Документация обновлена
- [ ] Нет security issues
- [ ] Performance acceptable
- [ ] Commits атомарные

---

## 🎓 Best Practices

### 1. Проверяйте часто

```bash
# После каждого логического изменения
git diff --stat
ruff check .
pytest tests/ -v
```

### 2. Автоматизируйте

```bash
# Создайте alias в ~/.bashrc
alias verify='git diff --stat && ruff check . && pytest tests/ -v'

# Использование
verify
```

### 3. Используйте pre-commit hooks

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: verify
        name: Full verification
        entry: bash -c 'verification-protocol checklist'
        language: system
```

---

## 📞 Что делать если проверка не прошла

### Syntax errors:
```bash
# Найти файл с ошибкой
python -m py_compile problem_file.py

# Исправить ошибку
# Проверить снова
```

### Tests fail:
```bash
# Запустить конкретный тест с verbose
pytest tests/test_file.py::test_function -vv

# Посмотреть traceback
pytest tests/ --tb=long

# Исправить код или тест
```

### Diff too large:
```bash
# Откатить staged changes
git reset

# Добавить файлы частями
git add file1.py
git commit -m "Part 1"

git add file2.py
git commit -m "Part 2"
```

---

_Последнее обновление: 2025-10-14_
