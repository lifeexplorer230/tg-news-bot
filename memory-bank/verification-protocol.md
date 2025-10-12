# ✅ VERIFICATION PROTOCOL

## Протокол проверок для каждого изменения

**Версия:** 1.0
**Дата:** 2025-10-11

---

## 📋 ЧЕК-ЛИСТ: ПЕРЕД КОММИТОМ

### 1. Синтаксис и импорты

```bash
# Проверить синтаксис Python
python -m py_compile <измененный_файл.py>

# Проверить импорт модуля
python -c "from <модуль> import <класс>; print('✅ Импорт OK')"

# Для всех Python файлов в проекте
find . -name "*.py" -not -path "./.git/*" -not -path "./data/*" | xargs python -m py_compile
```

✅ **Критерий:** Нет SyntaxError, импорты проходят

---

### 2. Git diff проверка

```bash
# Посмотреть размер изменений
git diff --stat

# Детальный просмотр
git diff <файл>

# Проверить что изменено только нужное
git status
```

✅ **Критерий:**

- Изменено ≤150 строк (safe zone)
- Нет случайных изменений
- Нет debug кода

---

### 3. Функциональная проверка

#### Для изменений в database/db.py

```bash
python -c "
from database.db import Database
db = Database('./data/test_verify.db')

# Проверить новый метод/изменение
# (конкретная проверка зависит от изменения)

print('✅ Database работает')
db.close()
"
```

#### Для изменений в marketplace_processor.py

```bash
python -c "
from utils.config import load_config
from services.marketplace_processor import MarketplaceProcessor

config = load_config()
processor = MarketplaceProcessor(config)
print('✅ MarketplaceProcessor инициализирован')
"
```

#### Для изменений в gemini_client.py

```bash
python -c "
from services.gemini_client import GeminiClient

# Без реального API ключа просто проверить импорт
print('✅ GeminiClient импортирован')
"
```

#### Для изменений в config.yaml

```bash
python -c "
from utils.config import load_config

config = load_config()
print('✅ Config загружен')
marketplaces = config.get('marketplaces', [])
if isinstance(marketplaces, dict):
    marketplaces_count = len(marketplaces)
else:
    marketplaces_count = len(marketplaces or [])
print(f'Маркетплейсов: {marketplaces_count}')
"
```

✅ **Критерий:** Код запускается без ошибок

---

### 4. Тесты (если есть)

```bash
# Запустить все тесты
pytest tests/ -v

# Запустить конкретный тест
pytest tests/test_database.py -v

# С coverage
pytest tests/ --cov=database --cov=services
```

✅ **Критерий:** Все тесты проходят (или добавлены новые для нового функционала)

---

### 5. Логирование

```bash
# Записать в лог что сделано
echo "[$(date)] [<КОД_ЗАДАЧИ>] <Описание изменения>" >> logs/migration_$(date +%Y-%m-%d).log

# Проверить git diff в последний раз
git diff --stat

# Записать размер партии
git diff --stat | tail -1 >> logs/migration_$(date +%Y-%m-%d).log
```

✅ **Критерий:** Лог обновлён

---

## 🔄 ЧЕК-ЛИСТ: ПОСЛЕ КОММИТА

### 1. Проверить коммит

```bash
# Посмотреть последний коммит
git log -1 --stat

# Проверить что всё включено
git status
```

✅ **Критерий:** Нет uncommitted изменений, коммит содержит нужные файлы

---

### 2. Push и проверка

```bash
# Push в ветку
git push origin <текущая_ветка>

# Проверить что push прошёл
git log --oneline -5
```

✅ **Критерий:** Коммит запушен в remote

---

### 3. Обновить дорожную карту

```bash
# Отметить задачу как ✅ в DOROZHNAYA_KARTA.md
# (Вручную через Edit tool)
```

✅ **Критерий:** Статус задачи обновлён в дорожной карте

---

## 🚦 УРОВНИ ПРОВЕРКИ

### Минимальная (для мелких изменений)

- ✅ Синтаксис
- ✅ Git diff
- ✅ Импорт

**Подходит для:** config, документация, мелкие фиксы

---

### Стандартная (для обычных изменений)

- ✅ Синтаксис
- ✅ Git diff
- ✅ Импорт
- ✅ Функциональная проверка
- ✅ Логирование

**Подходит для:** большинство изменений в коде

---

### Полная (для критичных изменений)

- ✅ Синтаксис
- ✅ Git diff
- ✅ Импорт
- ✅ Функциональная проверка
- ✅ Тесты (обязательно!)
- ✅ Логирование
- ✅ Ручное тестирование запуска

**Обязательна для:** database.py, main.py, критичные изменения

---

## 🎯 КРИТЕРИИ КАЧЕСТВА

### Код

- [ ] Нет синтаксических ошибок
- [ ] Все импорты работают
- [ ] Нет неиспользуемых импортов
- [ ] Нет debug print()
- [ ] Комментарии актуальны
- [ ] Docstrings обновлены (если нужно)

### Git

- [ ] Коммит включает только связанные изменения
- [ ] Сообщение коммита описательное: `[КОД] Краткое описание`
- [ ] Нет merge конфликтов
- [ ] История коммитов линейная

### Документация

- [ ] DOROZHNAYA_KARTA.md обновлена
- [ ] Логи записаны в logs/
- [ ] Memory bank обновлён (если нужно)

---

## 📊 ШАБЛОН ОТЧЁТА О ПРОВЕРКЕ

Копируйте и заполняйте:

```
### Проверка [КОД_ЗАДАЧИ] - YYYY-MM-DD HH:MM

**Файлы:** <список>
**Размер:** +XX -YY

**Проверки:**
- [ ] Синтаксис: ✅/❌
- [ ] Импорт: ✅/❌
- [ ] Функциональность: ✅/❌
- [ ] Тесты: ✅/❌/N/A
- [ ] Git diff: ✅/❌
- [ ] Логирование: ✅/❌

**Проблемы:** <если были>
**Статус:** ✅ ГОТОВ / ❌ ТРЕБУЕТСЯ ИСПРАВЛЕНИЕ
```

---

**Версия:** 1.0
**Последнее обновление:** 2025-10-11
