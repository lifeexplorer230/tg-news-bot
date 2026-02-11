"""Tests for shared constants."""
from utils.constants import NUMBER_EMOJIS


class TestNumberEmojis:
    def test_contains_1_to_15(self):
        for i in range(1, 16):
            assert i in NUMBER_EMOJIS, f"Missing key {i}"

    def test_basic_emojis(self):
        assert NUMBER_EMOJIS[1] == "1️⃣"
        assert NUMBER_EMOJIS[9] == "9️⃣"
        assert NUMBER_EMOJIS[10] == "🔟"

    def test_double_digit_emojis(self):
        assert NUMBER_EMOJIS[11] == "1️⃣1️⃣"
        assert NUMBER_EMOJIS[15] == "1️⃣5️⃣"

    def test_formatters_use_shared_constant(self):
        """Ensure formatters import from constants, not define locally."""
        import inspect
        from utils import formatters

        source = inspect.getsource(formatters)
        assert "number_emojis = {" not in source
        assert "NUMBER_EMOJIS" in source
