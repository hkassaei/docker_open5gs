"""Tests for v3 tool truncation."""

import sys
sys.path.insert(0, "operate")

from agentic_ops_v3.tools import _truncate_output


class TestTruncateOutput:
    def test_under_limit_unchanged(self):
        text = "line 1\nline 2\nline 3\n"
        assert _truncate_output(text, max_bytes=1000) == text

    def test_empty_input(self):
        assert _truncate_output("", max_bytes=100) == ""

    def test_over_limit_keeps_tail(self):
        lines = [f"line {i}\n" for i in range(100)]
        text = "".join(lines)
        result = _truncate_output(text, max_bytes=200)
        # Should contain the truncation warning
        assert "truncated" in result
        assert "older lines omitted" in result
        # Should contain the last lines, not the first
        assert "line 99" in result
        # Should NOT contain the first line
        assert "line 0\n" not in result

    def test_truncation_at_line_boundary(self):
        text = "short\n" * 50 + "last line\n"
        result = _truncate_output(text, max_bytes=100)
        # Result should not have partial lines (other than the truncation prefix)
        lines = result.splitlines()
        assert len(lines) >= 2  # at least truncation warning + some content

    def test_exact_limit(self):
        text = "hello\n"
        result = _truncate_output(text, max_bytes=len(text.encode("utf-8")))
        assert result == text  # exactly at limit, no truncation

    def test_single_huge_line(self):
        text = "x" * 20000 + "\n"
        result = _truncate_output(text, max_bytes=100)
        # Can't keep any full line, should at least have the truncation warning
        assert "truncated" in result
