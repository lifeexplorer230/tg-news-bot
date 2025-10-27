"""
Модуль для санитизации и валидации входных данных.

Защищает от:
- SQL инъекций
- Control characters
- Malformed Unicode
- Чрезмерно длинных сообщений
- XSS атак (если данные используются в web)
"""

import re
import unicodedata
from typing import Optional

from utils.logger import setup_logger

logger = setup_logger(__name__)


class InputSanitizer:
    """Централизованный класс для санитизации входных данных"""

    # Максимальные размеры для различных типов данных
    MAX_MESSAGE_SIZE = 100000  # 100KB для сообщений
    MAX_USERNAME_SIZE = 256
    MAX_CHANNEL_NAME_SIZE = 256
    MAX_URL_SIZE = 2048

    # Паттерны для валидации
    USERNAME_PATTERN = re.compile(r'^@?[a-zA-Z0-9_]{1,32}$')
    PHONE_PATTERN = re.compile(r'^\+?[0-9]{10,15}$')

    @staticmethod
    def sanitize_text(
        text: Optional[str],
        max_length: int = MAX_MESSAGE_SIZE,
        allow_newlines: bool = True
    ) -> str:
        """
        Санитизация текстовых данных.

        Args:
            text: Входной текст для санитизации
            max_length: Максимально допустимая длина
            allow_newlines: Разрешить переносы строк

        Returns:
            Очищенный и безопасный текст
        """
        if not text:
            return ""

        # 1. Удаляем null bytes
        text = text.replace('\x00', '')

        # 2. Удаляем управляющие символы (кроме newlines/tabs если разрешены)
        if allow_newlines:
            # Сохраняем \n, \r, \t
            text = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', text)
        else:
            # Удаляем все управляющие символы
            text = re.sub(r'[\x00-\x1F\x7F]', '', text)

        # 3. Нормализация Unicode для предотвращения homograph attacks
        text = unicodedata.normalize('NFKC', text)

        # 4. Удаляем невидимые Unicode символы (Zero-width characters)
        # Zero-width space, zero-width joiner, zero-width non-joiner, etc.
        text = re.sub(r'[\u200B-\u200D\uFEFF]', '', text)

        # 5. Удаляем bidirectional override characters (могут использоваться для обмана)
        text = re.sub(r'[\u202A-\u202E\u2066-\u2069]', '', text)

        # 6. Ограничиваем длину
        if len(text) > max_length:
            text = text[:max_length]
            logger.warning(f"Text truncated from {len(text)} to {max_length} characters")

        # 7. Удаляем лишние пробелы
        text = re.sub(r'\s+', ' ', text) if not allow_newlines else text

        return text.strip()

    @staticmethod
    def sanitize_username(username: Optional[str]) -> str:
        """
        Санитизация имени пользователя Telegram.

        Args:
            username: Имя пользователя для проверки

        Returns:
            Очищенное имя пользователя

        Raises:
            ValueError: Если имя пользователя невалидно
        """
        if not username:
            return ""

        # Базовая санитизация
        username = InputSanitizer.sanitize_text(
            username,
            max_length=InputSanitizer.MAX_USERNAME_SIZE,
            allow_newlines=False
        )

        # Проверка формата Telegram username
        if not InputSanitizer.USERNAME_PATTERN.match(username):
            logger.warning(f"Invalid username format: {username[:20]}...")
            raise ValueError(f"Invalid Telegram username format")

        return username

    @staticmethod
    def sanitize_channel_name(channel_name: Optional[str]) -> str:
        """
        Санитизация имени канала.

        Args:
            channel_name: Имя канала для проверки

        Returns:
            Очищенное имя канала
        """
        if not channel_name:
            return ""

        return InputSanitizer.sanitize_text(
            channel_name,
            max_length=InputSanitizer.MAX_CHANNEL_NAME_SIZE,
            allow_newlines=False
        )

    @staticmethod
    def sanitize_phone(phone: Optional[str]) -> str:
        """
        Санитизация номера телефона.

        Args:
            phone: Номер телефона для проверки

        Returns:
            Очищенный номер телефона

        Raises:
            ValueError: Если номер телефона невалиден
        """
        if not phone:
            return ""

        # Удаляем все кроме цифр и +
        phone = re.sub(r'[^+0-9]', '', phone)

        # Проверка формата
        if not InputSanitizer.PHONE_PATTERN.match(phone):
            # Маскируем номер в логах
            masked = phone[:3] + "***" + phone[-2:] if len(phone) > 5 else "***"
            logger.warning(f"Invalid phone format: {masked}")
            raise ValueError("Invalid phone number format")

        return phone

    @staticmethod
    def sanitize_url(url: Optional[str]) -> str:
        """
        Санитизация URL.

        Args:
            url: URL для проверки

        Returns:
            Очищенный URL
        """
        if not url:
            return ""

        # Базовая санитизация
        url = InputSanitizer.sanitize_text(
            url,
            max_length=InputSanitizer.MAX_URL_SIZE,
            allow_newlines=False
        )

        # Удаляем опасные схемы
        dangerous_schemes = ['javascript:', 'data:', 'vbscript:']
        for scheme in dangerous_schemes:
            if url.lower().startswith(scheme):
                logger.warning(f"Dangerous URL scheme blocked: {scheme}")
                return ""

        return url

    @staticmethod
    def sanitize_sql_parameter(value: Optional[str]) -> str:
        """
        Санитизация параметров для SQL запросов.

        ВАЖНО: Используйте параметризованные запросы!
        Эта функция - дополнительный уровень защиты.

        Args:
            value: Значение для санитизации

        Returns:
            Очищенное значение
        """
        if not value:
            return ""

        # Базовая санитизация
        value = InputSanitizer.sanitize_text(value, allow_newlines=False)

        # Экранируем опасные символы для SQL
        # Но лучше использовать параметризованные запросы!
        value = value.replace("'", "''")
        value = value.replace('"', '""')
        value = value.replace('\\', '\\\\')
        value = value.replace('\0', '')

        return value

    @staticmethod
    def validate_and_sanitize_json_field(
        data: dict,
        field_name: str,
        field_type: type,
        required: bool = False,
        default=None,
        max_length: Optional[int] = None
    ):
        """
        Валидация и санитизация поля в JSON/dict.

        Args:
            data: Словарь с данными
            field_name: Имя поля для проверки
            field_type: Ожидаемый тип поля
            required: Обязательное ли поле
            default: Значение по умолчанию
            max_length: Максимальная длина для строк

        Returns:
            Санитизированное значение

        Raises:
            ValueError: Если поле невалидно
        """
        value = data.get(field_name, default)

        if required and value is None:
            raise ValueError(f"Required field '{field_name}' is missing")

        if value is None:
            return default

        # Проверка типа
        if not isinstance(value, field_type):
            raise ValueError(
                f"Field '{field_name}' must be {field_type.__name__}, "
                f"got {type(value).__name__}"
            )

        # Санитизация строк
        if field_type == str:
            value = InputSanitizer.sanitize_text(value, max_length=max_length or 10000)

        return value


class SecurityValidator:
    """Класс для валидации данных на предмет безопасности"""

    @staticmethod
    def check_for_sql_injection(text: str) -> bool:
        """
        Проверка на попытки SQL инъекций.

        Args:
            text: Текст для проверки

        Returns:
            True если обнаружены признаки SQL инъекции
        """
        sql_patterns = [
            r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|EXEC|EXECUTE)\b)",
            r"(--|#|/\*|\*/)",  # SQL комментарии
            r"(\bUNION\b.*\bSELECT\b)",
            r"(\bOR\b.*=.*)",  # OR 1=1
            r"(';|';--|';\s*DROP)",
            r"(\bxp_cmdshell\b|\bsp_executesql\b)",  # SQL Server specific
        ]

        text_upper = text.upper()
        for pattern in sql_patterns:
            if re.search(pattern, text_upper, re.IGNORECASE):
                logger.warning(f"Potential SQL injection detected: {pattern}")
                return True

        return False

    @staticmethod
    def check_for_xss(text: str) -> bool:
        """
        Проверка на попытки XSS атак.

        Args:
            text: Текст для проверки

        Returns:
            True если обнаружены признаки XSS
        """
        xss_patterns = [
            r"<script[^>]*>.*?</script>",
            r"javascript:",
            r"on\w+\s*=",  # onclick=, onerror=, etc.
            r"<iframe[^>]*>",
            r"<embed[^>]*>",
            r"<object[^>]*>",
            r"<img[^>]*onerror\s*=",
            r"<svg[^>]*onload\s*=",
        ]

        for pattern in xss_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                logger.warning(f"Potential XSS detected: {pattern}")
                return True

        return False

    @staticmethod
    def is_safe_for_storage(text: str) -> bool:
        """
        Комплексная проверка безопасности текста перед сохранением.

        Args:
            text: Текст для проверки

        Returns:
            True если текст безопасен для сохранения
        """
        # Проверяем на SQL инъекции
        if SecurityValidator.check_for_sql_injection(text):
            return False

        # Проверяем на XSS (если данные могут быть отображены в web)
        if SecurityValidator.check_for_xss(text):
            return False

        # Проверяем на слишком длинные строки без пробелов (возможная атака)
        words = text.split()
        for word in words:
            if len(word) > 1000:  # Слово длиннее 1000 символов подозрительно
                logger.warning(f"Suspiciously long word detected: {len(word)} chars")
                return False

        return True


# Экспортируем для удобного импорта
sanitize_text = InputSanitizer.sanitize_text
sanitize_username = InputSanitizer.sanitize_username
sanitize_channel_name = InputSanitizer.sanitize_channel_name
sanitize_phone = InputSanitizer.sanitize_phone
sanitize_url = InputSanitizer.sanitize_url
is_safe_for_storage = SecurityValidator.is_safe_for_storage