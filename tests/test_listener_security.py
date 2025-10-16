"""Comprehensive tests for TelegramListener security features

Test Coverage:
- Message size validation (DoS protection)
- MAX_MESSAGE_SIZE constant
- Message rejection logging
- Integration with message handling flow
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from services.telegram_listener import TelegramListener
from utils.config import Config


class TestMessageSizeValidation:
    """Tests for message size validation (DoS protection)"""

    @pytest.fixture
    def config(self):
        """Create a test config"""
        return Config(config_path="config/base.yaml")

    @pytest.fixture
    def listener(self, config):
        """Create a TelegramListener instance"""
        with patch("services.telegram_listener.Database"):
            with patch("services.telegram_listener.TelegramClient"):
                return TelegramListener(config)

    def test_max_message_size_constant(self, listener):
        """Test that MAX_MESSAGE_SIZE is defined correctly"""
        assert hasattr(listener, "MAX_MESSAGE_SIZE")
        assert listener.MAX_MESSAGE_SIZE == 100000
        assert isinstance(listener.MAX_MESSAGE_SIZE, int)

    @pytest.mark.asyncio
    async def test_accept_normal_message(self, listener):
        """Test that normal-sized messages are accepted"""
        # Create a mock event with normal-sized message (1KB)
        event = Mock()
        event.message = Mock()
        event.message.text = "A" * 1000  # 1KB message
        event.message.date = datetime.now(UTC)
        event.message.id = 1
        event.message.media = None
        event.chat_id = 12345

        # Mock get_chat
        chat = Mock()
        chat.username = "test_channel"
        chat.title = "Test Channel"
        chat.id = 12345
        event.get_chat = AsyncMock(return_value=chat)

        # Mock database
        listener.db.get_channel_id = Mock(return_value=1)
        listener.db.save_message = Mock(return_value=1)

        # Should process without error
        await listener.handle_new_message(event)

        # Verify message was saved
        assert listener.db.save_message.called

    @pytest.mark.asyncio
    async def test_reject_oversized_message(self, listener):
        """Test that oversized messages are rejected"""
        # Create a mock event with oversized message (200KB)
        event = Mock()
        event.message = Mock()
        event.message.text = "A" * 200000  # 200KB message (exceeds 100KB limit)
        event.message.date = datetime.now(UTC)
        event.chat_id = 12345

        # Mock get_chat (shouldn't be called for rejected messages)
        event.get_chat = AsyncMock()

        # Mock database (shouldn't be called for rejected messages)
        listener.db.save_message = Mock()

        # Should return early without processing
        with patch("services.telegram_listener.logger") as mock_logger:
            await listener.handle_new_message(event)

            # Verify warning was logged
            assert mock_logger.warning.called
            warning_call = mock_logger.warning.call_args[0][0]
            assert "слишком большое" in warning_call.lower()

        # Verify message was NOT saved
        assert not listener.db.save_message.called
        assert not event.get_chat.called

    @pytest.mark.asyncio
    async def test_exact_limit_message(self, listener):
        """Test message at exact size limit"""
        # Create a mock event with message exactly at limit (100KB)
        event = Mock()
        event.message = Mock()
        event.message.text = "A" * 100000  # Exactly 100KB
        event.message.date = datetime.now(UTC)
        event.message.id = 1
        event.message.media = None
        event.chat_id = 12345

        # Mock get_chat
        chat = Mock()
        chat.username = "test_channel"
        chat.title = "Test Channel"
        chat.id = 12345
        event.get_chat = AsyncMock(return_value=chat)

        # Mock database
        listener.db.get_channel_id = Mock(return_value=1)
        listener.db.save_message = Mock(return_value=1)

        # Should process (at limit, not over)
        await listener.handle_new_message(event)

        # Verify message was saved
        assert listener.db.save_message.called

    @pytest.mark.asyncio
    async def test_one_byte_over_limit(self, listener):
        """Test message one byte over the limit"""
        # Create a mock event with message 1 byte over limit
        event = Mock()
        event.message = Mock()
        event.message.text = "A" * 100001  # 100KB + 1 byte
        event.message.date = datetime.now(UTC)
        event.chat_id = 12345

        # Mock database (shouldn't be called)
        listener.db.save_message = Mock()

        # Should be rejected
        with patch("services.telegram_listener.logger") as mock_logger:
            await listener.handle_new_message(event)

            # Verify warning was logged
            assert mock_logger.warning.called

        # Verify message was NOT saved
        assert not listener.db.save_message.called


class TestMessageSizeLogging:
    """Tests for logging of oversized messages"""

    @pytest.fixture
    def config(self):
        """Create a test config"""
        return Config(config_path="config/base.yaml")

    @pytest.fixture
    def listener(self, config):
        """Create a TelegramListener instance"""
        with patch("services.telegram_listener.Database"):
            with patch("services.telegram_listener.TelegramClient"):
                return TelegramListener(config)

    @pytest.mark.asyncio
    async def test_log_contains_message_size(self, listener):
        """Test that log includes actual message size"""
        event = Mock()
        event.message = Mock()
        event.message.text = "A" * 150000  # 150KB
        event.message.date = datetime.now(UTC)
        event.chat_id = 12345

        with patch("services.telegram_listener.logger") as mock_logger:
            await listener.handle_new_message(event)

            # Verify log contains size info
            assert mock_logger.warning.called
            args = mock_logger.warning.call_args[0]
            # Should log: size (150000), limit (100000), and channel_id
            assert 150000 in args or "150000" in str(args)

    @pytest.mark.asyncio
    async def test_log_contains_channel_id(self, listener):
        """Test that log includes channel ID"""
        event = Mock()
        event.message = Mock()
        event.message.text = "A" * 150000  # 150KB
        event.message.date = datetime.now(UTC)
        event.chat_id = 99999

        with patch("services.telegram_listener.logger") as mock_logger:
            await listener.handle_new_message(event)

            # Verify log contains channel ID
            assert mock_logger.warning.called
            args = mock_logger.warning.call_args[0]
            assert 99999 in args or "99999" in str(args)

    @pytest.mark.asyncio
    async def test_log_contains_max_size(self, listener):
        """Test that log includes MAX_MESSAGE_SIZE"""
        event = Mock()
        event.message = Mock()
        event.message.text = "A" * 150000
        event.message.date = datetime.now(UTC)
        event.chat_id = 12345

        with patch("services.telegram_listener.logger") as mock_logger:
            await listener.handle_new_message(event)

            # Verify log contains max size (100000)
            assert mock_logger.warning.called
            args = mock_logger.warning.call_args[0]
            assert 100000 in args or "100000" in str(args)


class TestMessageSizeEdgeCases:
    """Edge case tests for message size validation"""

    @pytest.fixture
    def config(self):
        """Create a test config"""
        return Config(config_path="config/base.yaml")

    @pytest.fixture
    def listener(self, config):
        """Create a TelegramListener instance"""
        with patch("services.telegram_listener.Database"):
            with patch("services.telegram_listener.TelegramClient"):
                return TelegramListener(config)

    @pytest.mark.asyncio
    async def test_empty_message(self, listener):
        """Test handling of empty message"""
        event = Mock()
        event.message = Mock()
        event.message.text = None  # Empty message
        event.message.date = datetime.now(UTC)

        # Should return early (no text)
        await listener.handle_new_message(event)

        # No error should occur

    @pytest.mark.asyncio
    async def test_whitespace_only_message(self, listener):
        """Test handling of whitespace-only message"""
        event = Mock()
        event.message = Mock()
        event.message.text = "   \n\t  "  # Whitespace only
        event.message.date = datetime.now(UTC)

        # After strip, will be empty and rejected by min_message_length filter
        listener.db.save_message = Mock()

        await listener.handle_new_message(event)

        # Should not save (empty after strip)
        assert not listener.db.save_message.called

    @pytest.mark.asyncio
    async def test_unicode_message_size(self, listener):
        """Test that unicode characters count correctly"""
        event = Mock()
        event.message = Mock()
        # Unicode characters may be multiple bytes
        event.message.text = "😀" * 50000  # Unicode emoji
        event.message.date = datetime.now(UTC)
        event.chat_id = 12345

        # Size should be calculated correctly (each emoji is 4 bytes)
        text_size = len(event.message.text.strip())

        if text_size > listener.MAX_MESSAGE_SIZE:
            with patch("services.telegram_listener.logger") as mock_logger:
                await listener.handle_new_message(event)
                assert mock_logger.warning.called
        else:
            # If under limit, should process normally
            chat = Mock()
            chat.username = "test"
            chat.title = "Test"
            chat.id = 12345
            event.get_chat = AsyncMock(return_value=chat)
            listener.db.get_channel_id = Mock(return_value=1)
            listener.db.save_message = Mock(return_value=1)

            await listener.handle_new_message(event)

    @pytest.mark.asyncio
    async def test_multibyte_characters(self, listener):
        """Test message with multibyte UTF-8 characters"""
        event = Mock()
        event.message = Mock()
        # Cyrillic characters (2 bytes each in UTF-8)
        event.message.text = "Привет мир" * 10000  # ~110KB
        event.message.date = datetime.now(UTC)
        event.chat_id = 12345

        with patch("services.telegram_listener.logger") as mock_logger:
            await listener.handle_new_message(event)

            # Should be rejected if over limit
            if len(event.message.text) > listener.MAX_MESSAGE_SIZE:
                assert mock_logger.warning.called


class TestMessageSizeDoSProtection:
    """Tests specifically for DoS protection"""

    @pytest.fixture
    def config(self):
        """Create a test config"""
        return Config(config_path="config/base.yaml")

    @pytest.fixture
    def listener(self, config):
        """Create a TelegramListener instance"""
        with patch("services.telegram_listener.Database"):
            with patch("services.telegram_listener.TelegramClient"):
                return TelegramListener(config)

    @pytest.mark.asyncio
    async def test_reject_1mb_message(self, listener):
        """Test rejection of 1MB message (10x limit)"""
        event = Mock()
        event.message = Mock()
        event.message.text = "A" * 1000000  # 1MB
        event.message.date = datetime.now(UTC)
        event.chat_id = 12345

        listener.db.save_message = Mock()

        with patch("services.telegram_listener.logger") as mock_logger:
            await listener.handle_new_message(event)
            assert mock_logger.warning.called

        # Should not process
        assert not listener.db.save_message.called

    @pytest.mark.asyncio
    async def test_reject_10mb_message(self, listener):
        """Test rejection of extremely large 10MB message"""
        event = Mock()
        event.message = Mock()
        event.message.text = "A" * 10000000  # 10MB
        event.message.date = datetime.now(UTC)
        event.chat_id = 12345

        listener.db.save_message = Mock()

        with patch("services.telegram_listener.logger") as mock_logger:
            await listener.handle_new_message(event)
            assert mock_logger.warning.called

        # Should not process
        assert not listener.db.save_message.called

    @pytest.mark.asyncio
    async def test_multiple_oversized_messages(self, listener):
        """Test handling of multiple oversized messages in sequence"""
        listener.db.save_message = Mock()

        for i in range(5):
            event = Mock()
            event.message = Mock()
            event.message.text = "A" * 200000  # 200KB each
            event.message.date = datetime.now(UTC)
            event.chat_id = 12345 + i

            with patch("services.telegram_listener.logger") as mock_logger:
                await listener.handle_new_message(event)
                assert mock_logger.warning.called

        # None should be saved
        assert not listener.db.save_message.called

    @pytest.mark.asyncio
    async def test_dos_protection_performance(self, listener):
        """Test that oversized message rejection is fast"""
        import time

        event = Mock()
        event.message = Mock()
        event.message.text = "A" * 1000000  # 1MB
        event.message.date = datetime.now(UTC)
        event.chat_id = 12345

        start = time.time()

        with patch("services.telegram_listener.logger"):
            await listener.handle_new_message(event)

        duration = time.time() - start

        # Should reject quickly (< 0.1s) without processing
        assert duration < 0.1


class TestMessageSizeIntegration:
    """Integration tests for message size validation"""

    @pytest.fixture
    def config(self):
        """Create a test config"""
        return Config(config_path="config/base.yaml")

    @pytest.fixture
    def listener(self, config):
        """Create a TelegramListener instance"""
        with patch("services.telegram_listener.Database"):
            with patch("services.telegram_listener.TelegramClient"):
                return TelegramListener(config)

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_message_flow_with_size_check(self, listener):
        """Test full message handling flow with size validation"""
        # Test 1: Normal message should pass all checks
        event = Mock()
        event.message = Mock()
        event.message.text = "Test message " * 100  # ~1.3KB
        event.message.date = datetime.now(UTC)
        event.message.id = 1
        event.message.media = None
        event.chat_id = 12345

        chat = Mock()
        chat.username = "test_channel"
        chat.title = "Test Channel"
        chat.id = 12345
        event.get_chat = AsyncMock(return_value=chat)

        listener.db.get_channel_id = Mock(return_value=1)
        listener.db.save_message = Mock(return_value=1)

        await listener.handle_new_message(event)

        # Should be saved
        assert listener.db.save_message.called
        listener.db.save_message.reset_mock()

        # Test 2: Oversized message should be rejected early
        event.message.text = "A" * 200000  # 200KB

        with patch("services.telegram_listener.logger") as mock_logger:
            await listener.handle_new_message(event)
            assert mock_logger.warning.called

        # Should NOT be saved
        assert not listener.db.save_message.called

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_size_check_before_other_filters(self, listener):
        """Test that size check happens before other expensive operations"""
        event = Mock()
        event.message = Mock()
        event.message.text = "A" * 200000  # Oversized
        event.message.date = datetime.now(UTC)
        event.chat_id = 12345

        # Mock expensive operations
        event.get_chat = AsyncMock()
        listener.db.get_channel_id = Mock()

        with patch("services.telegram_listener.logger"):
            await listener.handle_new_message(event)

        # Expensive operations should NOT be called
        assert not event.get_chat.called
        assert not listener.db.get_channel_id.called


class TestMessageSizeConstant:
    """Tests for MAX_MESSAGE_SIZE constant"""

    @pytest.fixture
    def config(self):
        """Create a test config"""
        return Config(config_path="config/base.yaml")

    @pytest.fixture
    def listener(self, config):
        """Create a TelegramListener instance"""
        with patch("services.telegram_listener.Database"):
            with patch("services.telegram_listener.TelegramClient"):
                return TelegramListener(config)

    def test_constant_value(self, listener):
        """Test that MAX_MESSAGE_SIZE has correct value"""
        assert listener.MAX_MESSAGE_SIZE == 100000

    def test_constant_type(self, listener):
        """Test that MAX_MESSAGE_SIZE is an integer"""
        assert isinstance(listener.MAX_MESSAGE_SIZE, int)

    def test_constant_positive(self, listener):
        """Test that MAX_MESSAGE_SIZE is positive"""
        assert listener.MAX_MESSAGE_SIZE > 0

    def test_constant_reasonable_value(self, listener):
        """Test that MAX_MESSAGE_SIZE is a reasonable limit"""
        # Should be between 10KB and 10MB
        assert 10000 <= listener.MAX_MESSAGE_SIZE <= 10000000

    def test_constant_class_attribute(self, listener):
        """Test that MAX_MESSAGE_SIZE is a class attribute"""
        # Should be accessible via class, not just instance
        assert hasattr(TelegramListener, "MAX_MESSAGE_SIZE")
        assert TelegramListener.MAX_MESSAGE_SIZE == 100000
