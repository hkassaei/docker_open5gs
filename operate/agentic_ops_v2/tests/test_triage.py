"""Tests for Phase 0 Triage agent — validates agent construction and prompt."""

import sys
sys.path.insert(0, "operate")

from agentic_ops_v2.agents.triage import create_triage_agent


class TestTriageAgent:
    def test_agent_creation(self):
        agent = create_triage_agent()
        assert agent.name == "TriageAgent"
        assert agent.model == "gemini-2.5-flash"
        assert agent.output_key == "triage"

    def test_has_metrics_tools(self):
        agent = create_triage_agent()
        tool_names = [t.__name__ for t in agent.tools]
        assert "get_network_status" in tool_names
        assert "get_nf_metrics" in tool_names
        assert "read_env_config" in tool_names
        assert "query_prometheus" in tool_names

    def test_tool_count(self):
        agent = create_triage_agent()
        assert len(agent.tools) == 4

    def test_has_instruction(self):
        agent = create_triage_agent()
        assert agent.instruction is not None
        assert len(agent.instruction) > 200

    def test_instruction_mentions_key_concepts(self):
        """Prompt should encode critical triage knowledge."""
        agent = create_triage_agent()
        inst = agent.instruction
        # GTP idle vs dead distinction
        assert "GTP" in inst or "gtp" in inst
        # Metrics-first approach
        assert "get_nf_metrics" in inst or "metrics" in inst.lower()
        # Should not jump to conclusions
        assert "not" in inst.lower() and ("conclusion" in inst.lower() or "diagnos" in inst.lower())

    def test_no_hardcoded_classification(self):
        """The agent should be an LlmAgent, not a BaseAgent with Python logic."""
        from google.adk.agents import LlmAgent
        agent = create_triage_agent()
        assert isinstance(agent, LlmAgent)
