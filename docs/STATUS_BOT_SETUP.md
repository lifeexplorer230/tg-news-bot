# Настройка Status Bot

## Проблема конфликтов сессий

StatusReporter и TelegramListener используют Telegram API для разных целей:
- **Listener** - слушает каналы через User API (требует номер телефона)
- **StatusReporter** - отправляет статусы в группу

Если оба используют **один и тот же номер телефона**, возникают конфликты сессий Telegram.

## Решение: Bot API для StatusReporter

### Шаг 1: Создать бота через BotFather

1. Открой Telegram и найди [@BotFather](https://t.me/BotFather)
2. Отправь команду `/newbot`
3. Укажи имя бота (например: "Marketplace Status Bot")
4. Укажи username бота (например: "marketplace_status_bot")
5. BotFather выдаст **bot token** вида: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`

### Шаг 2: Добавить бота в группу статусов

1. Найди группу "Soft Status" (или создай новую)
2. Добавь бота в группу
3. Дай боту права на отправку сообщений

### Шаг 3: Настроить config.yaml

```yaml
status:
  enabled: true
  chat: "Soft Status"  # или ID группы: -1001234567890
  bot_name: "Marketplace News Bot"
  bot_token: "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"  # ← Вставь токен сюда
  timezone: "Europe/Moscow"
```

### Шаг 4: Проверить работу

```bash
# Запустить отправку статуса вручную
python3 -c "
import asyncio
from utils.config import load_config
from services.status_reporter import run_status_reporter

config = load_config()
asyncio.run(run_status_reporter(config))
"
```

## Альтернативный вариант (НЕ рекомендуется)

Если не хочешь создавать бота, можно оставить `bot_token` пустым - тогда StatusReporter будет использовать User API.

⚠️ **ВНИМАНИЕ:** Это может вызвать конфликты если Listener активен одновременно!

## Как узнать ID группы

Если нужно использовать ID группы вместо названия:

1. Добавь бота [@raw_info_bot](https://t.me/raw_info_bot) в группу
2. Он пришлет ID группы (например: `-1001234567890`)
3. Используй этот ID в `status.chat`

## Проверка логов

При старте StatusReporter логирует используемый режим:

```
# Если настроен bot_token:
StatusReporter использует Bot API (избегает конфликтов сессий)

# Если bot_token не настроен:
⚠️ StatusReporter использует User API - может конфликтовать с listener!
   Рекомендуется задать status.bot_token в config.yaml
```

## Troubleshooting

### Ошибка "chat not found"

- Убедись что бот добавлен в группу
- Попробуй использовать ID группы вместо названия

### Ошибка "bot token invalid"

- Проверь что токен скопирован полностью
- Проверь что нет лишних пробелов

### Бот не может отправлять сообщения

- Проверь права бота в группе
- Убедись что группа не в режиме "только админы могут писать"
