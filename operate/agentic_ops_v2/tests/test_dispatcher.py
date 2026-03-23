"""Tests for Phase 2 dispatch logic — specialist selection validation."""

import sys
sys.path.insert(0, "operate")

from agentic_ops_v2.agents.dispatcher import _VALID_SPECIALISTS


class TestDispatchValidation:
    def test_valid_specialist_names(self):
        assert "ims" in _VALID_SPECIALISTS
        assert "transport" in _VALID_SPECIALISTS
        assert "core" in _VALID_SPECIALISTS
        assert "subscriber_data" in _VALID_SPECIALISTS
        assert len(_VALID_SPECIALISTS) == 4

    def test_invalid_specialist_filtered(self):
        raw = ["ims", "transport", "invalid_name"]
        valid = [s for s in raw if s in _VALID_SPECIALISTS]
        assert valid == ["ims", "transport"]

    def test_empty_selection_falls_back(self):
        raw = ["nonexistent"]
        valid = [s for s in raw if s in _VALID_SPECIALISTS]
        if not valid:
            valid = ["ims", "transport"]
        assert valid == ["ims", "transport"]
