"""Tests for Phase 2 Dispatch agent — validates agent construction."""

import sys
sys.path.insert(0, "operate")

from agentic_ops_v2.agents.dispatcher import create_dispatch_agent


class TestDispatchAgent:
    def test_agent_creation(self):
        agent = create_dispatch_agent()
        assert agent.name == "DispatchAgent"
        assert agent.model == "gemini-2.5-flash"
        assert agent.output_key == "dispatch"

    def test_no_tools(self):
        """Dispatch agent reasons from session state only — no tools needed."""
        agent = create_dispatch_agent()
        assert agent.tools == []

    def test_has_instruction(self):
        agent = create_dispatch_agent()
        assert agent.instruction is not None
        assert len(agent.instruction) > 100
        # Should mention specialist names
        assert "ims" in agent.instruction
        assert "transport" in agent.instruction
        assert "core" in agent.instruction
        assert "subscriber_data" in agent.instruction

    def test_instruction_mentions_key_patterns(self):
        """Prompt should mention specialist domains."""
        agent = create_dispatch_agent()
        inst = agent.instruction
        assert "transport" in inst.lower()
        assert "triage" in inst.lower()
        assert "trace" in inst.lower()
