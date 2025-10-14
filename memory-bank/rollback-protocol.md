# 🔄 ROLLBACK PROTOCOL — Протокол отката изменений

**Дата:** 2025-10-14
**Версия:** 1.0.0

---

## 🎯 Цель

Обеспечить быстрый и безопасный откат при:
- Критичных багах после коммита
- Неожиданных регрессиях
- Проблемах с production
- Превышении diff limits
- Нарушении стабильности

---

## 🚨 Когда откатывать

### Критичные случаи (откат немедленно):

- ❌ FloodWait errors вернулись
- ❌ Database corrupted
- ❌ Listener/Processor крашится при старте
- ❌ Data loss detected
- ❌ Security breach
- ❌ Production down

### Некритичные случаи (оценить → откат):

- ⚠️ Тесты падают
- ⚠️ Performance degradation > 50%
- ⚠️ Memory leak detected
- ⚠️ Логи полны errors
- ⚠️ Coverage упал > 10%

### Не откатывать (исправить forward):

- ✅ Минорные bugs
- ✅ Formatting issues
- ✅ Documentation errors
- ✅ Non-critical warnings
- ✅ Улучшения, которые можно доработать

---

## 📍 Точки отката

### 1. Snapshot commits (рекомендуется)

**Создание snapshot:**
```bash
# После завершения этапа (A, B, C, D, E)
git tag -a v1.0.0-stageA -m "Snapshot after Stage A completion"
git log -1 --oneline > snapshot/baseline_commit_stageA.txt

# Сохранить current state
mkdir -p snapshot/$(date +%Y%m%d)-stageA/
cp -r data/ snapshot/$(date +%Y%m%d)-stageA/
cp -r logs/ snapshot/$(date +%Y%m%d)-stageA/
```

**Откат к snapshot:**
```bash
# Проверить доступные snapshots
git tag -l "v1.0.0-stage*"

# Откатиться
git checkout v1.0.0-stageA

# Или создать новую ветку от snapshot
git checkout -b fix/rollback-stageA v1.0.0-stageA
```

### 2. Last known good commit

**Сохранение LKG:**
```bash
# После успешной verification
echo "$(git rev-parse HEAD)" > snapshot/last_known_good.txt
echo "$(date)" >> snapshot/last_known_good.txt
```

**Откат к LKG:**
```bash
# Прочитать LKG commit
cat snapshot/last_known_good.txt

# Откатиться
git checkout $(head -1 snapshot/last_known_good.txt)
```

### 3. Конкретный commit

**Найти commit:**
```bash
# Посмотреть историю
git log --oneline -20

# Найти commit перед проблемой
git log --oneline --since="2 hours ago"
```

**Откатиться:**
```bash
git checkout <commit-hash>
```

---

## 🔄 Методы отката

### Метод 1: Soft reset (рекомендуется для локальной разработки)

**Когда использовать:**
- Еще не запушили изменения
- Хотите сохранить изменения для доработки
- Проблема в последнем коммите

**Команды:**
```bash
# Откатить последний коммит, сохранив изменения
git reset --soft HEAD~1

# Проверить что изменения still staged
git status

# Исправить проблему
# Сделать новый коммит
git commit -m "fix: исправленная версия"
```

**Плюсы:**
- Изменения не теряются
- Можно быстро исправить
- History остается чистой

**Минусы:**
- Только для последнего коммита
- Не подходит если уже запушили

---

### Метод 2: Hard reset (для серьезных проблем)

**Когда использовать:**
- Нужно полностью удалить изменения
- Последние N коммитов полностью неправильные
- Хотите начать с чистого листа

**Команды:**
```bash
# ВНИМАНИЕ: Все uncommitted changes будут потеряны!

# Откатить последний коммит (удалить изменения)
git reset --hard HEAD~1

# Откатить последние 3 коммита
git reset --hard HEAD~3

# Откатить к конкретному коммиту
git reset --hard <commit-hash>

# Или к тегу
git reset --hard v1.0.0-stageA
```

**Плюсы:**
- Полностью чистый откат
- Быстро
- Просто

**Минусы:**
- **Все изменения теряются!**
- Нельзя отменить (без reflog)
- Опасно для production

---

### Метод 3: Revert commit (для production)

**Когда использовать:**
- Изменения уже запушены
- Работаете на shared branch
- Нужна история всех изменений
- Production environment

**Команды:**
```bash
# Создать reverse commit для последнего коммита
git revert HEAD

# Для нескольких коммитов
git revert HEAD~3..HEAD

# Для конкретного коммита
git revert <commit-hash>

# Без автокоммита (чтобы отредактировать)
git revert --no-commit HEAD
# Внести правки
git commit -m "revert: откат проблемного изменения"
```

**Плюсы:**
- Безопасно для shared branches
- История сохраняется
- Можно отменить revert
- Best practice для production

**Минусы:**
- History становится длиннее
- Может быть сложно для множественных коммитов

---

### Метод 4: Create fix branch

**Когда использовать:**
- Проблема сложная, нужно время для исправления
- Main branch должен оставаться стабильным
- Хотите протестировать fix перед merge

**Команды:**
```bash
# Создать ветку от last known good
git checkout -b fix/critical-issue v1.0.0-stageA

# Или от конкретного коммита
git checkout -b fix/critical-issue <good-commit-hash>

# Исправить проблему
# ...

# Commit и push
git add .
git commit -m "fix: критичная проблема"
git push origin fix/critical-issue

# Создать PR
gh pr create --title "Fix: Critical issue" --body "..."

# После review — merge в main
```

**Плюсы:**
- Не ломает main
- Можно review fix
- Можно тестировать
- Best practice для команды

**Минусы:**
- Требует больше времени
- Нужен PR process

---

## 📋 Чек-лист отката

### Pre-rollback

- [ ] **Документировать проблему**
  ```bash
  echo "Дата: $(date)" > rollback_log.txt
  echo "Причина: <описание>" >> rollback_log.txt
  echo "Коммит с проблемой: $(git rev-parse HEAD)" >> rollback_log.txt
  ```

- [ ] **Создать backup текущего состояния**
  ```bash
  mkdir -p snapshot/backup-before-rollback/
  cp -r data/ snapshot/backup-before-rollback/
  git stash save "backup before rollback"
  ```

- [ ] **Проверить Last Known Good**
  ```bash
  cat snapshot/last_known_good.txt
  git show $(head -1 snapshot/last_known_good.txt)
  ```

- [ ] **Остановить запущенные процессы**
  ```bash
  # Остановить listener/processor
  pkill -f "main.py listener"
  pkill -f "main.py processor"
  # Или docker
  docker compose down
  ```

### During rollback

- [ ] **Выполнить откат**
  - Выбрать метод (soft/hard/revert/branch)
  - Выполнить команды отката
  - Проверить git status

- [ ] **Восстановить данные (если нужно)**
  ```bash
  # Восстановить БД из backup
  cp snapshot/backup-before-rollback/data/news_bot.db data/
  ```

- [ ] **Проверить состояние**
  ```bash
  git log --oneline -5
  git status
  ls -lh data/
  ```

### Post-rollback

- [ ] **Запустить verification**
  ```bash
  # Проверить что система работает
  python -m py_compile services/*.py
  pytest tests/ -v || echo "Tests not ready yet"
  ```

- [ ] **Запустить smoke-тест**
  ```bash
  # Listener
  python main.py listener &
  sleep 30
  kill %1
  tail -20 logs/bot.log

  # Processor
  python main.py processor
  ```

- [ ] **Обновить документацию**
  ```bash
  # Добавить запись в DOROZHNAYA_KARTA.md (Журнал прогресса)
  # Обновить snapshot/last_known_good.txt
  # Добавить в memory-bank/rollback-protocol.md (История откатов)
  ```

- [ ] **Проанализировать причину**
  - Что пошло не так?
  - Почему verification не поймал?
  - Как предотвратить в будущем?

---

## 🚑 Emergency Rollback (быстрый откат)

### Production down - немедленный откат:

```bash
# 1. STOP всё
docker compose down

# 2. Откат к LKG
git reset --hard $(cat snapshot/last_known_good.txt 2>/dev/null || echo "HEAD~3")

# 3. Restore data
cp snapshot/backup-latest/data/news_bot.db data/ 2>/dev/null || echo "No backup"

# 4. START
docker compose up -d

# 5. Проверить
docker compose logs -f --tail=50

# 6. Уведомить
echo "Rollback completed at $(date)" | \
  mail -s "Production Rollback" admin@example.com
```

### Copy-paste команда:

```bash
docker compose down && \
git reset --hard $(cat snapshot/last_known_good.txt) && \
docker compose up -d && \
docker compose logs -f --tail=50
```

---

## 📊 История откатов

### Формат записи:

| Дата | Коммит | Причина | Метод | Результат | Lessons Learned |
|------|--------|---------|-------|-----------|-----------------|
| 2025-10-14 | abc123 | FloodWait returned | Hard reset | ✅ Успешно | Добавить проверку safe_connect в CI |

### Записи:

_Пока пусто — история будет заполняться_

---

## 🎓 Best Practices

### 1. Делайте snapshot часто

```bash
# После каждого успешного этапа
git tag -a v1.0.0-stage<X> -m "Snapshot"
echo "$(git rev-parse HEAD)" > snapshot/last_known_good.txt
```

### 2. Тестируйте перед push

```bash
# Всегда запускайте verification перед push
./verify.sh
git push origin main
```

### 3. Используйте feature branches

```bash
# Никогда не коммитьте в main напрямую
git checkout -b feature/my-feature
# ... работа ...
git push origin feature/my-feature
# Создать PR → review → merge
```

### 4. Документируйте проблемы

```bash
# После отката всегда добавляйте запись
echo "$(date): Откат из-за <причина>" >> snapshot/rollback_history.txt
```

---

## 🔍 Debugging после отката

### Найти что пошло не так:

```bash
# Сравнить LKG с проблемным коммитом
git diff $(cat snapshot/last_known_good.txt) <problem-commit>

# Посмотреть изменения в конкретном файле
git diff $(cat snapshot/last_known_good.txt) <problem-commit> -- file.py

# Bisect (найти commit с проблемой)
git bisect start
git bisect bad <problem-commit>
git bisect good $(cat snapshot/last_known_good.txt)
# Тестировать каждый commit
```

---

## 📞 Эскалация

### Если откат не помог:

1. **Проверить инфраструктуру**
   ```bash
   docker ps
   docker logs -f tg-news-bot
   df -h  # Disk space
   free -h  # Memory
   ```

2. **Проверить внешние зависимости**
   ```bash
   # Gemini API
   curl https://generativelanguage.googleapis.com/v1/models \
     -H "X-Goog-Api-Key: $GEMINI_API_KEY"

   # Telegram API
   curl https://api.telegram.org/bot<token>/getMe
   ```

3. **Собрать диагностику**
   ```bash
   tar -czf diagnostic_$(date +%Y%m%d_%H%M%S).tar.gz \
     logs/ \
     snapshot/ \
     data/news_bot.db \
     config/ \
     rollback_log.txt
   ```

4. **Создать GitHub issue**
   - Приложить diagnostic.tar.gz
   - Описать шаги для воспроизведения
   - Указать версию, commit hash, environment

---

_Последнее обновление: 2025-10-14_
