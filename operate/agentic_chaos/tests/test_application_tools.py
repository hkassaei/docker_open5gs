"""Unit tests for application_tools — validation and input handling."""

import pytest

from agentic_chaos.tools.application_tools import (
    corrupt_config,
    delete_subscriber_mongo,
)


class TestIMSIValidation:
    @pytest.mark.asyncio
    async def test_invalid_imsi_non_digits(self):
        with pytest.raises(ValueError, match="Invalid IMSI"):
            await delete_subscriber_mongo("not_a_number")

    @pytest.mark.asyncio
    async def test_invalid_imsi_too_short(self):
        with pytest.raises(ValueError, match="Invalid IMSI"):
            await delete_subscriber_mongo("12345")

    @pytest.mark.asyncio
    async def test_valid_imsi_format_accepted(self):
        """Valid IMSI format should not raise ValueError (will fail at Docker level)."""
        # This will fail because mongo container command will fail in test env,
        # but it should NOT raise ValueError
        result = await delete_subscriber_mongo("001011234567891")
        # We just check it didn't raise ValueError — the Docker command may fail
        assert "mechanism" in result


class TestCorruptConfigValidation:
    @pytest.mark.asyncio
    async def test_invalid_container_raises(self):
        with pytest.raises(ValueError, match="Unknown container"):
            await corrupt_config("fake_container", "/etc/config", "old", "new")

    @pytest.mark.asyncio
    async def test_valid_container_accepted(self):
        """Valid container should not raise ValueError."""
        # Will fail at Docker level but not at validation
        result = await corrupt_config("dns", "/etc/nonexistent", "old", "new")
        assert "mechanism" in result
        # Verify it uses python3 instead of sed
        assert "python3" in result["mechanism"]
        assert "sed" not in result["mechanism"]

    @pytest.mark.asyncio
    async def test_heal_cmd_reverses_replacement(self):
        """The heal command should swap search and replace."""
        result = await corrupt_config("dns", "/etc/test", "original", "corrupted")
        # heal_cmd should replace "corrupted" back to "original"
        assert "corrupted" in result["heal_cmd"]
        assert "original" in result["heal_cmd"]
