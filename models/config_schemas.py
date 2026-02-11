"""
Pydantic schemas для валидации конфигурации (CR-H4)

Валидирует все секции config.yaml и env переменных.
Предоставляет дружелюбные error messages при невалидных значениях.
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PathsConfig(BaseModel):
    """Валидация секции paths"""

    model_config = ConfigDict(extra="forbid")

    data_dir: str = Field(default="./data", description="Директория для данных")
    logs_dir: str = Field(default="./logs", description="Директория для логов")
    sessions_dir: str = Field(default="./sessions", description="Директория для сессий")
    snapshots_dir: str = Field(default="./snapshot", description="Директория для снапшотов")
    db_file_pattern: str = Field(
        default="{data_dir}/{profile}.db", description="Паттерн для файла БД"
    )
    log_file_pattern: str = Field(
        default="{logs_dir}/{profile}.log", description="Паттерн для лог-файла"
    )
    session_file_pattern: str = Field(
        default="{sessions_dir}/{profile}.session", description="Паттерн для файла сессии"
    )


class DatabaseRetryConfig(BaseModel):
    """Валидация database.retry"""

    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=5, ge=1, le=20, description="Максимум попыток")
    base_delay_seconds: float = Field(default=0.5, ge=0.1, le=10.0, description="Базовая задержка")
    backoff_multiplier: float = Field(default=1.0, ge=1.0, le=5.0, description="Множитель задержки")


class DatabaseConfig(BaseModel):
    """Валидация секции database"""

    model_config = ConfigDict(extra="forbid")

    timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0, description="Таймаут БД")
    busy_timeout_ms: int = Field(default=30000, ge=1000, le=60000, description="Таймаут busy")
    retry: DatabaseRetryConfig = Field(
        default_factory=DatabaseRetryConfig, description="Настройки retry"
    )
    path: str | None = Field(default=None, description="Путь к БД (опционально)")


class TelegramConfig(BaseModel):
    """Валидация секции telegram"""

    model_config = ConfigDict(extra="forbid")

    session_name: str | None = Field(default=None, description="Имя сессии")


class PublicationConfig(BaseModel):
    """Валидация секции publication"""

    model_config = ConfigDict(extra="forbid")

    channel: str = Field(default="", description="Канал для публикации")
    preview_channel: str = Field(default="", description="Канал предпросмотра")
    header_template: str = Field(
        default="📌 Главные новости мира маркетплейсов за {date}",
        description="Шаблон заголовка",
    )
    footer_template: str = Field(
        default="____________________________________\nПодпишись, чтобы быть в курсе: {channel}",
        description="Шаблон футера",
    )
    notify_account: str = Field(default="", description="Аккаунт для уведомлений")


class LLMConfig(BaseModel):
    """Валидация секции llm"""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(default="gemini", pattern="^(gemini|openai|anthropic)$")


class GeminiPromptsConfig(BaseModel):
    """Валидация gemini.prompts"""

    model_config = ConfigDict(extra="allow")  # Разрешаем дополнительные промпты

    select_top_news: str | None = None
    select_and_format_news: str | None = None
    select_three_categories: str | None = None
    select_and_format_marketplace_news: str | None = None
    format_news_post: str | None = None


class GeminiConfig(BaseModel):
    """Валидация секции gemini"""

    model_config = ConfigDict(extra="forbid")

    model: str = Field(default="gemini-2.0-flash-exp", description="Модель Gemini")
    max_tokens: int = Field(default=2048, ge=128, le=8192, description="Макс токенов")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Температура")
    prompts: GeminiPromptsConfig = Field(
        default_factory=GeminiPromptsConfig, description="Пути к промптам"
    )


class ListenerHealthcheckConfig(BaseModel):
    """Валидация listener.healthcheck"""

    model_config = ConfigDict(extra="forbid")

    heartbeat_path: str = Field(
        default="{logs_dir}/listener.heartbeat", description="Путь к heartbeat"
    )
    interval_seconds: int = Field(default=60, ge=10, le=600, description="Интервал проверки")
    max_age_seconds: int = Field(default=180, ge=30, le=1800, description="Макс возраст")


class ListenerConfig(BaseModel):
    """Валидация секции listener"""

    model_config = ConfigDict(extra="forbid")

    mode: str = Field(default="subscriptions", pattern="^(subscriptions|manual)$")
    min_message_length: int = Field(default=50, ge=10, le=1000, description="Мин длина сообщения")
    channel_whitelist: List[str] = Field(default_factory=list, description="Whitelist каналов")
    channel_blacklist: List[str] = Field(default_factory=list, description="Blacklist каналов")
    manual_channels: List[str] = Field(default_factory=list, description="Ручные каналы")
    healthcheck: ListenerHealthcheckConfig = Field(
        default_factory=ListenerHealthcheckConfig, description="Настройки healthcheck"
    )


class FiltersConfig(BaseModel):
    """Валидация секции filters"""

    model_config = ConfigDict(extra="forbid")

    exclude_keywords: List[str] = Field(default_factory=list, description="Исключить keywords")


class ProcessorConfig(BaseModel):
    """Валидация секции processor"""

    model_config = ConfigDict(extra="forbid")

    schedule_time: str = Field(
        default="09:00", pattern=r"^\d{2}:\d{2}$", description="Время запуска"
    )
    timezone: str = Field(default="Europe/Moscow", description="Часовой пояс")
    duplicate_threshold: float = Field(default=0.85, ge=0.5, le=1.0, description="Порог дубликатов")
    top_n: int = Field(default=10, ge=1, le=100, description="Топ N новостей")
    exclude_count: int = Field(default=5, ge=0, le=50, description="Количество исключений")


class EmbeddingsConfig(BaseModel):
    """Валидация секции embeddings"""

    model_config = ConfigDict(extra="forbid")

    model: str = Field(
        default="paraphrase-multilingual-MiniLM-L12-v2", description="Модель embeddings"
    )
    local_path: str = Field(
        default="./models/paraphrase-multilingual-MiniLM-L12-v2",
        description="Локальный путь",
    )
    enable_fallback: bool = Field(default=True, description="Включить fallback")
    allow_remote_download: bool = Field(default=False, description="Разрешить скачивание")


class ModerationMessageConfig(BaseModel):
    """Валидация moderation.message"""

    model_config = ConfigDict(extra="forbid")

    title_template: str = Field(
        default="📋 **МОДЕРАЦИЯ: {context}**", description="Шаблон заголовка"
    )
    intro_template: str = Field(
        default="_(Отсортировано по важности)_", description="Шаблон вступления"
    )
    footer_template: str = Field(
        default="Отправь номера для УДАЛЕНИЯ через пробел", description="Шаблон футера"
    )


class ModerationConfig(BaseModel):
    """Валидация секции moderation"""

    model_config = ConfigDict(extra="forbid")

    auto: bool = Field(default=True, description="Автоматическая модерация (без участия человека)")
    enabled: bool = Field(default=False, description="Ручная модерация (legacy)")
    final_top_n: int = Field(default=10, ge=1, le=50, description="Финальное количество новостей после модерации")
    timeout_hours: int = Field(default=2, ge=1, le=24, description="Таймаут модерации (для ручной)")
    instructions_template: str = Field(default="default", description="Шаблон инструкций")
    cancel_keywords: List[str] = Field(
        default_factory=lambda: ["отмена", "cancel"], description="Keywords отмены"
    )
    publish_all_keywords: List[str] = Field(
        default_factory=lambda: ["0", "все", "all"], description="Keywords публикации всех"
    )
    message: ModerationMessageConfig = Field(
        default_factory=ModerationMessageConfig, description="Настройки сообщений"
    )


class CleanupConfig(BaseModel):
    """Валидация секции cleanup"""

    model_config = ConfigDict(extra="forbid")

    raw_messages_days: int = Field(default=14, ge=1, le=365, description="Дни хранения сырых")
    published_days: int = Field(default=60, ge=1, le=730, description="Дни хранения опубликованных")
    run_weekly: bool = Field(default=True, description="Запускать еженедельно")


class StatusConfig(BaseModel):
    """Валидация секции status"""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=False, description="Включить статус-репорты")
    chat: str = Field(default="Soft Status", description="Чат для статусов")
    bot_name: str = Field(default="Universal Digest Bot", description="Имя бота")
    interval_minutes: int = Field(default=60, ge=1, le=1440, description="Интервал отправки")
    bot_token: str = Field(default="", description="Токен бота")
    timezone: str = Field(default="Europe/Moscow", description="Часовой пояс")
    message_template: str = Field(default="", description="Шаблон сообщения")


class LoggingRotateConfig(BaseModel):
    """Валидация logging.rotate"""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=True, description="Включить ротацию")
    max_bytes: int = Field(default=10485760, ge=1024, le=104857600, description="Макс байт")
    backup_count: int = Field(default=5, ge=1, le=20, description="Количество бэкапов")


class LoggingConfig(BaseModel):
    """Валидация секции logging"""

    model_config = ConfigDict(extra="forbid")

    level: str = Field(
        default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$", description="Уровень логов"
    )
    format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Формат логов",
    )
    datefmt: str = Field(default="%Y-%m-%d %H:%M:%S", description="Формат даты")
    file: str = Field(default="{logs_dir}/bot.log", description="Файл логов")
    rotate: LoggingRotateConfig = Field(
        default_factory=LoggingRotateConfig, description="Настройки ротации"
    )


class AppConfig(BaseModel):
    """
    Главная схема конфигурации приложения (CR-H4)

    Валидирует весь config.yaml с дружелюбными error messages.
    """

    model_config = ConfigDict(extra="allow")  # Разрешаем профиль-специфичные поля

    profile: str = Field(default="marketplace", description="Профиль конфигурации")
    paths: PathsConfig = Field(default_factory=PathsConfig, description="Пути")
    database: DatabaseConfig = Field(default_factory=DatabaseConfig, description="База данных")
    telegram: TelegramConfig = Field(default_factory=TelegramConfig, description="Telegram")
    publication: PublicationConfig = Field(
        default_factory=PublicationConfig, description="Публикация"
    )
    llm: LLMConfig = Field(default_factory=LLMConfig, description="LLM")
    gemini: GeminiConfig = Field(default_factory=GeminiConfig, description="Gemini")
    listener: ListenerConfig = Field(default_factory=ListenerConfig, description="Listener")
    filters: FiltersConfig = Field(default_factory=FiltersConfig, description="Фильтры")
    processor: ProcessorConfig = Field(default_factory=ProcessorConfig, description="Processor")
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig, description="Embeddings")
    moderation: ModerationConfig = Field(default_factory=ModerationConfig, description="Модерация")
    cleanup: CleanupConfig = Field(default_factory=CleanupConfig, description="Очистка")
    status: StatusConfig = Field(default_factory=StatusConfig, description="Статус")
    logging: LoggingConfig = Field(default_factory=LoggingConfig, description="Логирование")

    @model_validator(mode="after")
    def validate_schedule_time_format(self) -> AppConfig:
        """Валидация формата schedule_time"""
        schedule_time = self.processor.schedule_time
        parts = schedule_time.split(":")
        if len(parts) != 2:
            raise ValueError(
                f"processor.schedule_time должен быть в формате HH:MM, получен: {schedule_time}"
            )

        try:
            hours = int(parts[0])
            minutes = int(parts[1])
        except ValueError:
            raise ValueError(
                f"processor.schedule_time должен содержать числа, получен: {schedule_time}"
            )

        if not (0 <= hours <= 23):
            raise ValueError(f"processor.schedule_time: часы должны быть 0-23, получено: {hours}")

        if not (0 <= minutes <= 59):
            raise ValueError(
                f"processor.schedule_time: минуты должны быть 0-59, получено: {minutes}"
            )

        return self


class EnvConfig(BaseModel):
    """
    Схема для валидации env переменных (CR-H4)

    Валидирует обязательные env переменные с дружелюбными error messages.
    """

    model_config = ConfigDict(extra="ignore")

    TELEGRAM_API_ID: int = Field(..., gt=0, description="Telegram API ID")
    TELEGRAM_API_HASH: str = Field(
        ..., min_length=32, max_length=32, description="Telegram API Hash"
    )
    TELEGRAM_PHONE: str = Field(..., pattern=r"^\+?\d{10,15}$", description="Telegram Phone")
    GEMINI_API_KEY: str = Field(..., min_length=20, description="Gemini API Key")
    MY_CHANNEL: str = Field(default="", description="Канал для публикации")
    MY_PERSONAL_ACCOUNT: str = Field(default="", description="Личный аккаунт")
    STATUS_BOT_TOKEN: str = Field(default="", description="Bot token для статус-репортов")

    @field_validator("TELEGRAM_API_ID")
    @classmethod
    def validate_api_id(cls, v: int) -> int:
        """Валидация TELEGRAM_API_ID"""
        if v <= 0:
            raise ValueError(
                "TELEGRAM_API_ID должен быть положительным числом. "
                "Получите его на https://my.telegram.org/apps"
            )
        return v

    @field_validator("TELEGRAM_API_HASH")
    @classmethod
    def validate_api_hash(cls, v: str) -> str:
        """Валидация TELEGRAM_API_HASH"""
        if len(v) != 32:
            raise ValueError(
                "TELEGRAM_API_HASH должен быть длиной 32 символа. "
                "Получите его на https://my.telegram.org/apps"
            )
        return v

    @field_validator("TELEGRAM_PHONE")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        """Валидация TELEGRAM_PHONE"""
        if not v.startswith("+"):
            raise ValueError(f"TELEGRAM_PHONE должен начинаться с '+', получено: {v}")
        digits = v.replace("+", "")
        if not digits.isdigit():
            raise ValueError(
                f"TELEGRAM_PHONE должен содержать только цифры после '+', получено: {v}"
            )
        if not (10 <= len(digits) <= 15):
            raise ValueError(f"TELEGRAM_PHONE должен содержать 10-15 цифр, получено: {len(digits)}")
        return v

    @field_validator("GEMINI_API_KEY")
    @classmethod
    def validate_gemini_key(cls, v: str) -> str:
        """Валидация GEMINI_API_KEY"""
        if len(v) < 20:
            raise ValueError(
                "GEMINI_API_KEY слишком короткий (минимум 20 символов). "
                "Получите ключ на https://aistudio.google.com/apikey"
            )
        return v
