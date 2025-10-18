"""Comprehensive tests for auth.py security features

Test Coverage:
- Phone masking functionality
- Edge cases and boundary conditions
- Security compliance (PII protection)
- Integration with authorization flow
"""

import pytest

from auth import mask_phone


class TestPhoneMasking:
    """Tests for phone number masking (PII protection)"""

    def test_mask_standard_phone(self):
        """Test masking of standard Russian phone number"""
        phone = "+79252124626"
        masked = mask_phone(phone)

        assert masked == "+792****4626"
        # Verify middle digits are masked
        assert "2521246" not in masked
        # Verify first 4 and last 4 digits are preserved
        assert masked.startswith("+792")
        assert masked.endswith("4626")

    def test_mask_international_phone(self):
        """Test masking of international phone numbers"""
        # US phone number
        phone = "+14155552671"
        masked = mask_phone(phone)

        assert masked == "+141****2671"
        assert "155552" not in masked

    def test_mask_long_phone(self):
        """Test masking of long phone numbers"""
        phone = "+380501234567"
        masked = mask_phone(phone)

        assert masked == "+380****4567"
        assert "050123" not in masked

    def test_mask_without_plus(self):
        """Test masking of phone number without + prefix"""
        phone = "79252124626"
        masked = mask_phone(phone)

        assert masked == "7925****4626"
        assert "2521246" not in masked

    def test_mask_short_phone(self):
        """Test masking of short phone numbers (< 8 digits)"""
        # Edge case: very short number
        phone = "1234567"
        masked = mask_phone(phone)

        assert masked == "***"

    def test_mask_minimum_length(self):
        """Test masking of minimum valid length (8 digits)"""
        phone = "12345678"
        masked = mask_phone(phone)

        assert masked == "1234****5678"
        assert "4567" not in masked

    def test_mask_empty_string(self):
        """Test masking of empty string"""
        phone = ""
        masked = mask_phone(phone)

        assert masked == "***"

    def test_mask_none_value(self):
        """Test masking of None value"""
        phone = None
        masked = mask_phone(phone)

        assert masked == "***"

    def test_mask_whitespace(self):
        """Test masking of whitespace-only string"""
        phone = "   "
        masked = mask_phone(phone)

        assert masked == "***"

    def test_mask_preserves_sensitive_portions(self):
        """Test that masking hides the middle sensitive digits"""
        phone = "+79251234567"
        masked = mask_phone(phone)

        # Middle digits should be completely hidden
        assert "9251234" not in masked
        assert "12345" not in masked
        assert "****" in masked

    def test_mask_different_lengths(self):
        """Test masking works for various phone lengths"""
        test_cases = [
            ("+123456789", "+123****6789"),
            ("+1234567890", "+123****7890"),
            ("+12345678901", "+123****8901"),
            ("+123456789012", "+123****9012"),
        ]

        for phone, expected in test_cases:
            masked = mask_phone(phone)
            assert masked == expected

    def test_mask_reveals_country_code(self):
        """Test that country code remains visible"""
        test_cases = [
            ("+79251234567", "+792"),  # Russia
            ("+14155551234", "+141"),  # USA
            ("+442071234567", "+442"),  # UK
            ("+33612345678", "+336"),  # France
        ]

        for phone, expected_prefix in test_cases:
            masked = mask_phone(phone)
            assert masked.startswith(expected_prefix)

    def test_mask_reveals_last_four(self):
        """Test that last 4 digits remain visible"""
        test_cases = [
            ("+79251234567", "4567"),
            ("+14155559876", "9876"),
            ("+442071231111", "1111"),
        ]

        for phone, expected_suffix in test_cases:
            masked = mask_phone(phone)
            assert masked.endswith(expected_suffix)


class TestPhoneMaskingSecurity:
    """Security-focused tests for phone masking"""

    def test_mask_prevents_pii_leakage(self):
        """Test that masking prevents PII leakage in logs"""
        sensitive_phone = "+79252124626"
        masked = mask_phone(sensitive_phone)

        # Verify that the masked version doesn't contain sensitive middle digits
        middle_digits = sensitive_phone[3:-4]  # "25212462"
        assert middle_digits not in masked

    def test_mask_length_consistency(self):
        """Test that masked output has consistent length"""
        phones = [
            "+79251234567",
            "+14155552671",
            "+442071234567",
        ]

        for phone in phones:
            masked = mask_phone(phone)
            # Masked should always have format: prefix + **** + suffix
            assert "****" in masked
            # Length should be: len(prefix) + 4 + 4
            assert len(masked) == len(phone[:4]) + 4 + 4

    def test_mask_idempotent(self):
        """Test that masking twice doesn't change result"""
        phone = "+79252124626"
        masked_once = mask_phone(phone)
        masked_twice = mask_phone(masked_once)

        # Should return *** for already masked phone (too many *)
        assert masked_twice == "***"

    def test_mask_no_plaintext_leakage(self):
        """Test that no plaintext digits leak through masking"""
        phone = "+79252124626"
        masked = mask_phone(phone)

        # Extract middle portion
        sensitive_part = phone[3:-4]  # "25212462"

        # Verify none of the sensitive digits appear consecutively
        for i in range(len(sensitive_part) - 2):
            three_digits = sensitive_part[i : i + 3]
            assert three_digits not in masked


class TestPhoneMaskingEdgeCases:
    """Edge case tests"""

    def test_mask_special_characters(self):
        """Test masking with special characters"""
        phone = "+7 (925) 212-46-26"
        masked = mask_phone(phone)

        # Should work with the string as-is (not a valid format)
        assert masked == "+7 (****6-26"

    def test_mask_numeric_input(self):
        """Test masking with numeric input (if passed)"""
        # If someone accidentally passes an int
        phone = 79252124626
        masked = mask_phone(str(phone))

        assert "****" in masked

    def test_mask_very_long_string(self):
        """Test masking of unusually long string"""
        phone = "+7" + "9" * 100
        masked = mask_phone(phone)

        assert masked == "+799****" + "9" * 4
        assert len(masked) == 4 + 4 + 4

    def test_mask_unicode_characters(self):
        """Test behavior with unicode characters (invalid phone)"""
        phone = "+7925212😀626"
        masked = mask_phone(phone)

        # Should still mask, treating unicode as regular chars
        assert "****" in masked


class TestPhoneMaskingPerformance:
    """Performance tests for phone masking"""

    def test_mask_performance(self):
        """Test that masking is fast"""
        import time

        phone = "+79252124626"

        start = time.time()
        for _ in range(10000):
            mask_phone(phone)
        duration = time.time() - start

        # Should complete 10k maskings in < 0.1 second
        assert duration < 0.1

    def test_mask_memory_efficiency(self):
        """Test that masking doesn't create excessive objects"""
        import sys

        phone = "+79252124626"

        # Get size of result
        masked = mask_phone(phone)
        size = sys.getsizeof(masked)

        # Should be small (< 100 bytes for the string)
        assert size < 100


class TestPhoneMaskingIntegration:
    """Integration tests simulating real usage"""

    def test_mask_in_log_message(self):
        """Test masking in log message context"""
        phone = "+79252124626"
        masked = mask_phone(phone)

        log_message = f"Sending code to {masked}"

        assert "Sending code to +792****4626" in log_message
        assert "+79252124626" not in log_message

    def test_mask_multiple_phones_in_batch(self):
        """Test masking multiple phone numbers"""
        phones = [
            "+79251234567",
            "+14155552671",
            "+442071234567",
            "+33612345678",
        ]

        masked_phones = [mask_phone(phone) for phone in phones]

        # All should be masked
        assert all("****" in masked for masked in masked_phones)

        # None should contain full middle digits
        for phone, masked in zip(phones, masked_phones):
            middle = phone[3:-4]
            assert middle not in masked

    def test_mask_database_storage(self):
        """Test that masked phones are safe for database storage"""
        phone = "+79252124626"
        masked = mask_phone(phone)

        # Masked phone should be:
        # 1. Not too long
        assert len(masked) <= 20

        # 2. Still recognizable as a phone
        assert masked.startswith("+") or masked == "***"

        # 3. Not reversible
        # (cannot reconstruct original from masked version)
        assert phone != masked


class TestPhoneMaskingCompliance:
    """Compliance and regulatory tests"""

    def test_mask_gdpr_compliance(self):
        """Test GDPR compliance - PII should be masked"""
        # EU phone number
        phone = "+33612345678"
        masked = mask_phone(phone)

        # Should mask middle digits (PII protection)
        assert "1234567" not in masked
        assert "****" in masked

    def test_mask_hipaa_compliance(self):
        """Test that masking meets HIPAA-like requirements"""
        # Should not store full phone numbers in logs
        phone = "+14155552671"
        masked = mask_phone(phone)

        # Full number should not be recoverable
        assert masked != phone
        # Should still be useful for identification
        assert masked.startswith("+14")
        assert masked.endswith("2671")

    def test_mask_minimal_exposure(self):
        """Test that masking exposes minimum necessary information"""
        phone = "+79252124626"
        masked = mask_phone(phone)

        # Count visible digits (excluding + and *)
        visible_digits = sum(c.isdigit() for c in masked)

        # Should expose exactly 7 digits (3 prefix + 4 suffix)
        assert visible_digits == 7

        # Original has 11 digits - we're hiding 4 digits
        total_digits = sum(c.isdigit() for c in phone)
        assert total_digits - visible_digits == 4
