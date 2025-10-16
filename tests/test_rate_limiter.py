"""Comprehensive tests for RateLimiter (Security Feature)

Test Coverage:
- Basic rate limiting functionality
- Edge cases (boundary conditions)
- Concurrent access scenarios
- Rate limit reset functionality
- Performance under load
"""

import asyncio
import time
from datetime import datetime, timedelta

import pytest

from utils.rate_limiter import RateLimiter


class TestRateLimiterBasic:
    """Basic functionality tests for RateLimiter"""

    @pytest.mark.asyncio
    async def test_initialization(self):
        """Test RateLimiter initialization with default parameters"""
        limiter = RateLimiter()

        assert limiter.max_requests == 20
        assert limiter.per_seconds == 60
        assert limiter.current_usage == 0
        assert len(limiter.requests) == 0

    @pytest.mark.asyncio
    async def test_initialization_custom_params(self):
        """Test RateLimiter initialization with custom parameters"""
        limiter = RateLimiter(max_requests=10, per_seconds=30)

        assert limiter.max_requests == 10
        assert limiter.per_seconds == 30
        assert limiter.current_usage == 0

    @pytest.mark.asyncio
    async def test_single_request_allowed(self):
        """Test that a single request is always allowed"""
        limiter = RateLimiter(max_requests=5, per_seconds=1)

        start = time.time()
        await limiter.acquire()
        duration = time.time() - start

        # Should complete immediately (< 0.1s)
        assert duration < 0.1
        assert limiter.current_usage == 1

    @pytest.mark.asyncio
    async def test_requests_within_limit(self):
        """Test that requests within limit are not blocked"""
        limiter = RateLimiter(max_requests=5, per_seconds=10)

        start = time.time()

        # Make 5 requests (at the limit)
        for _ in range(5):
            await limiter.acquire()

        duration = time.time() - start

        # Should complete immediately (< 0.5s for 5 requests)
        assert duration < 0.5
        assert limiter.current_usage == 5

    @pytest.mark.asyncio
    async def test_rate_limit_blocking(self):
        """Test that rate limit blocks when exceeded"""
        limiter = RateLimiter(max_requests=3, per_seconds=2)

        # Fill up the rate limit
        for _ in range(3):
            await limiter.acquire()

        # Next request should be blocked for ~2 seconds
        start = time.time()
        await limiter.acquire()
        duration = time.time() - start

        # Should have waited approximately 2 seconds
        assert 1.8 <= duration <= 2.5  # Allow some variance for system timing
        assert limiter.current_usage == 1  # Old requests expired, new one added


class TestRateLimiterEdgeCases:
    """Edge case and boundary condition tests"""

    @pytest.mark.asyncio
    async def test_zero_max_requests(self):
        """Test behavior with max_requests=0 (edge case)"""
        limiter = RateLimiter(max_requests=0, per_seconds=1)

        # Should block indefinitely or handle gracefully
        # In current implementation, this would block forever
        # Let's test with a timeout to verify blocking behavior
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(limiter.acquire(), timeout=0.5)

    @pytest.mark.asyncio
    async def test_very_short_time_window(self):
        """Test with very short time window (1 second)"""
        limiter = RateLimiter(max_requests=2, per_seconds=1)

        # Fill limit
        await limiter.acquire()
        await limiter.acquire()

        # Should block for ~1 second
        start = time.time()
        await limiter.acquire()
        duration = time.time() - start

        assert 0.8 <= duration <= 1.5

    @pytest.mark.asyncio
    async def test_very_long_time_window(self):
        """Test with long time window (doesn't affect short-term behavior)"""
        limiter = RateLimiter(max_requests=5, per_seconds=300)

        # Should allow 5 requests immediately
        start = time.time()
        for _ in range(5):
            await limiter.acquire()
        duration = time.time() - start

        assert duration < 0.5

    @pytest.mark.asyncio
    async def test_current_usage_accuracy(self):
        """Test that current_usage property accurately reflects state"""
        limiter = RateLimiter(max_requests=10, per_seconds=2)

        # Initially zero
        assert limiter.current_usage == 0

        # Add 3 requests
        for _ in range(3):
            await limiter.acquire()

        assert limiter.current_usage == 3

        # Wait for expiration (2+ seconds)
        await asyncio.sleep(2.2)

        # Should be zero again (requests expired)
        assert limiter.current_usage == 0


class TestRateLimiterReset:
    """Tests for reset functionality"""

    @pytest.mark.asyncio
    async def test_reset_clears_requests(self):
        """Test that reset() clears all tracked requests"""
        limiter = RateLimiter(max_requests=5, per_seconds=10)

        # Fill up partially
        for _ in range(3):
            await limiter.acquire()

        assert limiter.current_usage == 3

        # Reset
        limiter.reset()

        assert limiter.current_usage == 0
        assert len(limiter.requests) == 0

    @pytest.mark.asyncio
    async def test_reset_allows_immediate_requests(self):
        """Test that reset allows immediate requests even after hitting limit"""
        limiter = RateLimiter(max_requests=2, per_seconds=5)

        # Hit the limit
        await limiter.acquire()
        await limiter.acquire()

        # Reset
        limiter.reset()

        # Should be able to make requests immediately
        start = time.time()
        await limiter.acquire()
        duration = time.time() - start

        assert duration < 0.1
        assert limiter.current_usage == 1


class TestRateLimiterConcurrency:
    """Concurrency and thread-safety tests"""

    @pytest.mark.asyncio
    async def test_concurrent_requests_under_limit(self):
        """Test multiple concurrent requests under the limit"""
        limiter = RateLimiter(max_requests=10, per_seconds=5)

        # Launch 5 concurrent requests (under limit)
        start = time.time()
        await asyncio.gather(*[limiter.acquire() for _ in range(5)])
        duration = time.time() - start

        # Should complete quickly
        assert duration < 0.5
        assert limiter.current_usage == 5

    @pytest.mark.asyncio
    async def test_concurrent_requests_over_limit(self):
        """Test behavior when concurrent requests exceed limit"""
        limiter = RateLimiter(max_requests=3, per_seconds=2)

        # Launch 6 concurrent requests (2x the limit)
        start = time.time()
        await asyncio.gather(*[limiter.acquire() for _ in range(6)])
        duration = time.time() - start

        # First 3 should be immediate, next 3 should wait ~2 seconds
        # Total time should be around 2-3 seconds
        assert 1.8 <= duration <= 3.5

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_high_concurrency(self):
        """Test behavior under high concurrent load"""
        limiter = RateLimiter(max_requests=20, per_seconds=5)

        # Launch 50 concurrent requests
        start = time.time()
        await asyncio.gather(*[limiter.acquire() for _ in range(50)])
        duration = time.time() - start

        # Should handle all 50 requests
        # 20 immediate, 20 after 5s, 10 after 10s
        # Total ~10-12 seconds
        assert 9 <= duration <= 15


class TestRateLimiterTelegramLimits:
    """Tests specific to Telegram API rate limits"""

    @pytest.mark.asyncio
    async def test_telegram_default_limits(self):
        """Test with Telegram's default rate limits (20 req/60s)"""
        limiter = RateLimiter(max_requests=20, per_seconds=60)

        # Should allow 20 requests immediately
        start = time.time()
        for _ in range(20):
            await limiter.acquire()
        duration = time.time() - start

        assert duration < 1.0
        assert limiter.current_usage == 20

    @pytest.mark.asyncio
    async def test_telegram_burst_protection(self):
        """Test that limiter prevents Telegram API burst violations"""
        limiter = RateLimiter(max_requests=20, per_seconds=60)

        # Fill up the limit
        for _ in range(20):
            await limiter.acquire()

        # Next request should block for ~60 seconds
        # We'll test with a shorter timeout to verify blocking
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(limiter.acquire(), timeout=1.0)

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_telegram_sustained_load(self):
        """Test sustained load matching Telegram's limits"""
        limiter = RateLimiter(max_requests=20, per_seconds=60)

        # Simulate sending messages at a rate just under the limit
        # 15 requests per minute = safe
        start = time.time()

        for i in range(15):
            await limiter.acquire()
            # Small delay between requests (realistic usage)
            if i < 14:
                await asyncio.sleep(0.1)

        duration = time.time() - start

        # Should complete in ~1-2 seconds (15 requests + delays)
        assert duration < 5.0


class TestRateLimiterPerformance:
    """Performance and efficiency tests"""

    @pytest.mark.asyncio
    async def test_acquire_performance(self):
        """Test that acquire() is fast when under limit"""
        limiter = RateLimiter(max_requests=100, per_seconds=60)

        start = time.time()
        await limiter.acquire()
        duration = time.time() - start

        # Should be extremely fast (< 1ms)
        assert duration < 0.001

    @pytest.mark.asyncio
    async def test_current_usage_performance(self):
        """Test that current_usage property is efficient"""
        limiter = RateLimiter(max_requests=100, per_seconds=60)

        # Add some requests
        for _ in range(50):
            await limiter.acquire()

        # Check performance of current_usage
        start = time.time()
        for _ in range(100):
            _ = limiter.current_usage
        duration = time.time() - start

        # Should be fast even with 100 calls
        assert duration < 0.01

    @pytest.mark.asyncio
    async def test_old_requests_cleanup(self):
        """Test that old requests are properly cleaned up"""
        limiter = RateLimiter(max_requests=10, per_seconds=1)

        # Add 5 requests
        for _ in range(5):
            await limiter.acquire()

        assert limiter.current_usage == 5

        # Wait for expiration
        await asyncio.sleep(1.2)

        # Add another request (should trigger cleanup)
        await limiter.acquire()

        # Should only have 1 request (old ones cleaned)
        assert limiter.current_usage == 1


class TestRateLimiterRepr:
    """Tests for string representation"""

    def test_repr_format(self):
        """Test that __repr__ returns expected format"""
        limiter = RateLimiter(max_requests=10, per_seconds=30)

        repr_str = repr(limiter)

        assert "RateLimiter" in repr_str
        assert "10" in repr_str
        assert "30" in repr_str

    @pytest.mark.asyncio
    async def test_repr_reflects_current_state(self):
        """Test that __repr__ reflects current usage"""
        limiter = RateLimiter(max_requests=5, per_seconds=10)

        # Initially empty
        repr_before = repr(limiter)
        assert "0/5" in repr_before

        # Add requests
        for _ in range(3):
            await limiter.acquire()

        # Should reflect new state
        repr_after = repr(limiter)
        assert "3/5" in repr_after


class TestRateLimiterIntegration:
    """Integration tests simulating real-world scenarios"""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_news_processor_scenario(self):
        """Simulate rate limiting for news processor publishing"""
        limiter = RateLimiter(max_requests=20, per_seconds=60)

        # Simulate publishing 10 news items
        published = 0
        start = time.time()

        for i in range(10):
            await limiter.acquire()
            # Simulate actual publishing work
            await asyncio.sleep(0.01)
            published += 1

        duration = time.time() - start

        assert published == 10
        # Should complete quickly since we're under the limit
        assert duration < 2.0

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_moderation_flow_scenario(self):
        """Simulate rate limiting for moderation messages"""
        limiter = RateLimiter(max_requests=20, per_seconds=60)

        # Simulate sending moderation messages
        messages_sent = []

        # Send 5 moderation messages
        for i in range(5):
            await limiter.acquire()
            messages_sent.append(f"Message {i+1}")

        assert len(messages_sent) == 5
        # All should be sent without delay
        assert limiter.current_usage <= 20

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.slow
    async def test_error_recovery_scenario(self):
        """Test rate limiter behavior after errors/resets"""
        limiter = RateLimiter(max_requests=5, per_seconds=2)

        # Fill up the limit
        for _ in range(5):
            await limiter.acquire()

        # Simulate error condition - reset the limiter
        limiter.reset()

        # Should be able to continue immediately
        start = time.time()
        for _ in range(3):
            await limiter.acquire()
        duration = time.time() - start

        assert duration < 0.5
        assert limiter.current_usage == 3
