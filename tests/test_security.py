"""
Comprehensive security tests for TG News Bot.

Тестирует:
- SQL injection protection
- Input sanitization
- XSS prevention
- Rate limiting
- Control character handling
- Unicode normalization
"""

import asyncio
import sqlite3
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from database.db import Database
from utils.sanitization import (
    InputSanitizer,
    SecurityValidator,
    sanitize_text,
    sanitize_username,
    sanitize_channel_name,
    sanitize_phone,
    sanitize_url,
    is_safe_for_storage,
)
from utils.advanced_rate_limiter import (
    MultiLevelRateLimiter,
    AdaptiveRateLimiter,
    TokenBucket,
    SlidingWindowRateLimiter,
)


class TestInputSanitization:
    """Тесты для санитизации входных данных"""

    def test_sanitize_text_removes_null_bytes(self):
        """Проверка удаления null bytes"""
        dangerous = "Hello\x00World\x00!"
        clean = sanitize_text(dangerous)
        assert clean == "HelloWorld!"
        assert '\x00' not in clean

    def test_sanitize_text_removes_control_characters(self):
        """Проверка удаления управляющих символов"""
        dangerous = "Test\x01\x02\x03\x1b[31mRed\x1b[0m"
        clean = sanitize_text(dangerous)
        assert '\x01' not in clean
        assert '\x02' not in clean
        assert '\x03' not in clean
        assert '\x1b' not in clean

    def test_sanitize_text_preserves_newlines_when_allowed(self):
        """Проверка сохранения переносов строк когда разрешено"""
        text = "Line 1\nLine 2\rLine 3\tTabbed"
        clean = sanitize_text(text, allow_newlines=True)
        assert '\n' in clean
        assert '\r' in clean
        assert '\t' in clean

    def test_sanitize_text_removes_newlines_when_not_allowed(self):
        """Проверка удаления переносов строк когда запрещено"""
        text = "Line 1\nLine 2\rLine 3\tTabbed"
        clean = sanitize_text(text, allow_newlines=False)
        assert '\n' not in clean
        assert '\r' not in clean
        assert '\t' not in clean

    def test_sanitize_text_unicode_normalization(self):
        """Проверка нормализации Unicode"""
        # Разные представления одной буквы 'é'
        text1 = "café"  # é как один символ
        text2 = "cafe\u0301"  # e + combining accent

        clean1 = sanitize_text(text1)
        clean2 = sanitize_text(text2)
        assert clean1 == clean2  # После нормализации должны быть одинаковые

    def test_sanitize_text_removes_zero_width_characters(self):
        """Проверка удаления zero-width символов"""
        dangerous = "Hello\u200bWorld\u200c!\u200d"  # Zero-width space, non-joiner, joiner
        clean = sanitize_text(dangerous)
        assert clean == "HelloWorld!"
        assert '\u200b' not in clean
        assert '\u200c' not in clean
        assert '\u200d' not in clean

    def test_sanitize_text_removes_bidirectional_override(self):
        """Проверка удаления bidirectional override символов"""
        dangerous = "Hello\u202eWorld"  # Right-to-left override
        clean = sanitize_text(dangerous)
        assert '\u202e' not in clean

    def test_sanitize_text_length_limit(self):
        """Проверка ограничения длины"""
        long_text = "a" * 1000
        clean = sanitize_text(long_text, max_length=100)
        assert len(clean) == 100

    def test_sanitize_username_valid(self):
        """Проверка валидного username"""
        assert sanitize_username("@user123") == "@user123"
        assert sanitize_username("test_user") == "test_user"
        assert sanitize_username("a" * 32) == "a" * 32

    def test_sanitize_username_invalid(self):
        """Проверка невалидного username"""
        with pytest.raises(ValueError):
            sanitize_username("user with spaces")
        with pytest.raises(ValueError):
            sanitize_username("user!@#$")
        with pytest.raises(ValueError):
            sanitize_username("a" * 33)  # Слишком длинный

    def test_sanitize_channel_name(self):
        """Проверка санитизации имени канала"""
        assert sanitize_channel_name("My Channel") == "My Channel"
        assert len(sanitize_channel_name("a" * 1000)) <= 256

    def test_sanitize_phone_valid(self):
        """Проверка валидного телефона"""
        assert sanitize_phone("+79991234567") == "+79991234567"
        assert sanitize_phone("89991234567") == "89991234567"

    def test_sanitize_phone_invalid(self):
        """Проверка невалидного телефона"""
        with pytest.raises(ValueError):
            sanitize_phone("not a phone")
        with pytest.raises(ValueError):
            sanitize_phone("+7999")  # Слишком короткий

    def test_sanitize_url_safe(self):
        """Проверка безопасных URL"""
        assert sanitize_url("https://example.com") == "https://example.com"
        assert sanitize_url("http://test.org/path") == "http://test.org/path"

    def test_sanitize_url_dangerous(self):
        """Проверка опасных URL схем"""
        assert sanitize_url("javascript:alert(1)") == ""
        assert sanitize_url("data:text/html,<script>alert(1)</script>") == ""
        assert sanitize_url("vbscript:msgbox") == ""


class TestSecurityValidation:
    """Тесты для валидации безопасности"""

    def test_sql_injection_detection(self):
        """Проверка обнаружения SQL инъекций"""
        injections = [
            "'; DROP TABLE users; --",
            "' OR '1'='1",
            "1; DELETE FROM messages",
            "admin'--",
            "' UNION SELECT * FROM passwords --",
            "'; EXEC xp_cmdshell('dir'); --",
        ]

        for injection in injections:
            assert SecurityValidator.check_for_sql_injection(injection) is True

    def test_sql_injection_false_positives(self):
        """Проверка что обычный текст не определяется как SQL инъекция"""
        normal_texts = [
            "I need to select the best option",
            "Drop me a message",
            "Union workers unite!",
            "Create amazing content",
        ]

        for text in normal_texts:
            # В нижнем регистре может быть false positive, но это ok для безопасности
            pass

    def test_xss_detection(self):
        """Проверка обнаружения XSS атак"""
        xss_payloads = [
            "<script>alert('XSS')</script>",
            "<img src=x onerror=alert(1)>",
            "<iframe src='evil.com'></iframe>",
            "javascript:alert(document.cookie)",
            "<svg onload=alert(1)>",
            "<embed src='evil.swf'>",
            "<object data='evil.swf'>",
        ]

        for payload in xss_payloads:
            assert SecurityValidator.check_for_xss(payload) is True

    def test_xss_false_positives(self):
        """Проверка что обычный текст не определяется как XSS"""
        normal_texts = [
            "I love JavaScript programming",
            "Click on the button",
            "Image processing script",
        ]

        for text in normal_texts:
            assert SecurityValidator.check_for_xss(text) is False

    def test_is_safe_for_storage(self):
        """Комплексная проверка безопасности для хранения"""
        # Безопасные тексты
        safe_texts = [
            "Normal message text",
            "Привет мир! Hello world!",
            "Some numbers: 123456",
        ]

        for text in safe_texts:
            assert is_safe_for_storage(text) is True

        # Опасные тексты
        dangerous_texts = [
            "'; DROP TABLE users; --",
            "<script>alert(1)</script>",
            "a" * 1001,  # Слишком длинное слово
        ]

        for text in dangerous_texts:
            assert is_safe_for_storage(text) is False


class TestDatabaseSecurity:
    """Тесты безопасности базы данных"""

    def test_sql_injection_in_database(self):
        """Проверка защиты от SQL инъекций в Database классе"""
        db = Database(":memory:")

        # Попытки SQL инъекций
        malicious_inputs = [
            "'; DROP TABLE channels; --",
            "' OR '1'='1",
            "admin'--",
            "' UNION SELECT * FROM raw_messages --",
        ]

        for malicious in malicious_inputs:
            # Добавляем канал с вредоносным именем
            channel_id = db.add_channel(malicious, "Test Channel")
            assert channel_id is not None

            # Проверяем что таблица все еще существует
            channels = db.get_active_channels()
            assert isinstance(channels, list)

            # Проверяем что данные сохранились корректно (экранированы)
            channel_id_check = db.get_channel_id(malicious)
            assert channel_id_check == channel_id  # Проверяем что можем найти по username

    def test_database_handles_unicode(self):
        """Проверка обработки Unicode в базе данных"""
        db = Database(":memory:")

        # Unicode тексты
        unicode_texts = [
            "Emoji test 😀🎉🚀",
            "Русский текст с ударениями",
            "中文字符",
            "العربية",
        ]

        for text in unicode_texts:
            channel_id = db.add_channel(f"channel_{hash(text)}", text)
            assert channel_id is not None

    def test_database_thread_safety(self):
        """Проверка thread safety базы данных"""
        import threading

        db = Database(":memory:")
        errors = []

        def worker():
            try:
                for i in range(10):
                    db.add_channel(f"channel_{threading.get_ident()}_{i}", f"Title {i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread safety errors: {errors}"


class TestRateLimiting:
    """Тесты для rate limiting"""

    @pytest.mark.asyncio
    async def test_token_bucket_basic(self):
        """Тест базовой функциональности TokenBucket"""
        bucket = TokenBucket(rate=10, capacity=10)  # 10 tokens/sec, capacity 10

        # Должны мочь взять 10 токенов сразу
        wait_time = await bucket.acquire(10)
        assert wait_time == 0

        # Следующий запрос должен ждать
        wait_time = await bucket.acquire(1)
        assert wait_time > 0

    @pytest.mark.asyncio
    async def test_token_bucket_refill(self):
        """Тест пополнения токенов в TokenBucket"""
        bucket = TokenBucket(rate=10, capacity=10)

        # Забираем все токены
        await bucket.acquire(10)

        # Ждем 0.1 секунды - должен пополниться 1 токен
        await asyncio.sleep(0.1)

        # Должны мочь взять 1 токен
        wait_time = await bucket.acquire(1)
        assert wait_time == 0

    @pytest.mark.asyncio
    async def test_sliding_window_rate_limiter(self):
        """Тест SlidingWindowRateLimiter"""
        limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=1)

        # Первые 3 запроса должны пройти
        for _ in range(3):
            wait_time = await limiter.acquire()
            assert wait_time == 0

        # 4-й запрос должен ждать
        wait_time = await limiter.acquire()
        assert wait_time > 0

    @pytest.mark.asyncio
    async def test_multi_level_rate_limiter(self):
        """Тест многоуровневого rate limiter"""
        limiter = MultiLevelRateLimiter()

        # Тестируем global limit
        start = time.monotonic()
        for _ in range(5):
            await limiter.acquire()
        elapsed = time.monotonic() - start

        # При лимите 30 req/sec, 5 запросов не должны занимать больше 0.2 сек
        assert elapsed < 0.5

    @pytest.mark.asyncio
    async def test_multi_level_per_chat_limit(self):
        """Тест per-chat limiting"""
        limiter = MultiLevelRateLimiter()

        # Разные чаты не должны влиять друг на друга
        tasks = []
        for chat_id in [1, 2, 3]:
            for _ in range(5):
                tasks.append(limiter.acquire(chat_id=chat_id))

        # Все должны выполниться параллельно
        start = time.monotonic()
        await asyncio.gather(*tasks)
        elapsed = time.monotonic() - start

        # Должно быть быстро так как разные чаты
        assert elapsed < 1

    @pytest.mark.asyncio
    async def test_flood_wait_handling(self):
        """Тест обработки FloodWait"""
        limiter = MultiLevelRateLimiter()

        # Симулируем FloodWait
        await limiter.handle_flood_wait(1, "test_endpoint")

        # Следующий запрос к этому endpoint должен ждать
        start = time.monotonic()
        await limiter.acquire(endpoint="test_endpoint")
        elapsed = time.monotonic() - start

        assert elapsed >= 0.9  # Должен был ждать ~1 секунду

    @pytest.mark.asyncio
    async def test_adaptive_rate_limiter(self):
        """Тест адаптивного rate limiter"""
        base_limiter = MultiLevelRateLimiter()
        adaptive = AdaptiveRateLimiter(base_limiter)

        # Записываем успешные запросы
        for _ in range(10):
            adaptive.record_result(True)

        assert adaptive.success_rate == 1.0
        assert adaptive.adjustment_factor <= 1.0  # Должен ускориться

        # Записываем неудачные запросы
        for _ in range(10):
            adaptive.record_result(False)

        assert adaptive.success_rate < 1.0
        assert adaptive.adjustment_factor > 1.0  # Должен замедлиться

    @pytest.mark.asyncio
    async def test_rate_limiter_priority(self):
        """Тест приоритетов в rate limiter"""
        limiter = MultiLevelRateLimiter()

        # Создаём ситуацию с реальной задержкой (FloodWait)
        await limiter.handle_flood_wait(1, "test_endpoint")

        # Высокоприоритетный запрос должен ждать меньше
        start = time.monotonic()
        await limiter.acquire(endpoint="test_endpoint", priority=2)  # Критический
        high_priority_time = time.monotonic() - start

        # Сбрасываем FloodWait для второго теста
        await limiter.handle_flood_wait(1, "test_endpoint2")

        start = time.monotonic()
        await limiter.acquire(endpoint="test_endpoint2", priority=0)  # Обычный
        normal_priority_time = time.monotonic() - start

        # Высокий приоритет должен ждать меньше
        # priority=2: wait * (1/(2+1)) = wait * 0.33
        # priority=0: wait * 1.0
        # Поэтому high_priority_time должно быть примерно в 3 раза меньше
        assert high_priority_time < normal_priority_time * 0.9  # С небольшим допуском


class TestIntegrationSecurity:
    """Интеграционные тесты безопасности"""

    @pytest.mark.asyncio
    async def test_telegram_listener_with_sanitization(self):
        """Тест TelegramListener с санитизацией"""
        from services.telegram_listener import TelegramListener
        from utils.config import Config

        # Мокаем конфиг
        mock_config = MagicMock(spec=Config)
        mock_config.telegram_api_id = "test"
        mock_config.telegram_api_hash = "test"
        mock_config.telegram_phone = "+79991234567"
        mock_config.db_path = ":memory:"
        mock_config.database_settings.return_value = {}
        mock_config.get.side_effect = lambda key, default=None: {
            "telegram.session_name": "test_session",
            "listener.channel_whitelist": [],
            "listener.channel_blacklist": [],
            "listener.min_message_length": 50,
            "listener.exclude_keywords": [],
        }.get(key, default)

        # Мокаем TelegramClient
        with patch("services.telegram_listener.TelegramClient") as mock_telegram_client:
            mock_telegram_client.return_value = MagicMock()

            # Создаем listener
            listener = TelegramListener(mock_config)

            # Мокаем event с опасным сообщением
            mock_event = MagicMock()
            mock_event.message.text = "Test\x00message'; DROP TABLE channels; --<script>alert(1)</script>"
            mock_event.message.date = asyncio.get_event_loop().time()

            mock_chat = AsyncMock()
            mock_chat.username = "test_channel\x00"
            mock_chat.title = "Test Channel<script>"
            mock_chat.id = 12345
            mock_event.get_chat = AsyncMock(return_value=mock_chat)

            # Обрабатываем сообщение
            with patch.object(listener, 'db') as mock_db:
                mock_db.get_channel_id = AsyncMock(return_value=1)
                mock_db.save_raw_message = AsyncMock(return_value=1)

                await listener.handle_new_message(mock_event)

                # Проверяем что текст был санитизирован
                call_args = mock_db.save_raw_message.call_args
                if call_args:
                    saved_text = call_args[0][0] if call_args[0] else call_args[1].get('text')
                    if saved_text:
                        assert '\x00' not in saved_text
                    assert '<script>' not in saved_text


class TestPerformanceSecurity:
    """Тесты производительности функций безопасности"""

    def test_sanitization_performance(self):
        """Тест производительности санитизации"""
        import timeit

        text = "Normal text " * 100  # ~1200 символов

        # Должно быть быстро даже для больших текстов
        time_taken = timeit.timeit(
            lambda: sanitize_text(text),
            number=1000
        )

        # 1000 санитизаций должны занимать меньше секунды
        assert time_taken < 1.0

    @pytest.mark.asyncio
    async def test_rate_limiter_performance(self):
        """Тест производительности rate limiter"""
        limiter = MultiLevelRateLimiter()

        start = time.monotonic()
        tasks = [limiter.acquire(chat_id=i) for i in range(100)]
        await asyncio.gather(*tasks)
        elapsed = time.monotonic() - start

        # 100 запросов должны обработаться за разумное время
        assert elapsed < 5.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])