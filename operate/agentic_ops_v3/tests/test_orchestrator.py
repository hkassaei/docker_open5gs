"""Tests for v3 orchestrator — dispatch parsing and agent construction."""

import sys
sys.path.insert(0, "operate")

from agentic_ops_v3.orchestrator import _parse_dispatch_output


class TestParseDispatchOutput:
    def test_structured_format(self):
        text = "Some reasoning...\n\nDISPATCH: ims, transport"
        assert _parse_dispatch_output(text) == ["ims", "transport"]

    def test_structured_single(self):
        text = "DISPATCH: transport"
        assert _parse_dispatch_output(text) == ["transport"]

    def test_structured_all_four(self):
        text = "DISPATCH: ims, transport, core, subscriber_data"
        result = _parse_dispatch_output(text)
        assert set(result) == {"ims", "transport", "core", "subscriber_data"}

    def test_case_insensitive(self):
        text = "dispatch: IMS, Transport"
        assert _parse_dispatch_output(text) == ["ims", "transport"]

    def test_filters_invalid_names(self):
        text = "DISPATCH: ims, nonexistent, transport"
        assert _parse_dispatch_output(text) == ["ims", "transport"]

    def test_keyword_fallback(self):
        """When no DISPATCH: line, scan for specialist names in text."""
        text = "We should investigate the transport layer and subscriber_data."
        result = _parse_dispatch_output(text)
        assert "transport" in result
        assert "subscriber_data" in result

    def test_garbage_input_defaults(self):
        text = "I have no idea what to do."
        result = _parse_dispatch_output(text)
        assert result == ["ims", "transport"]

    def test_empty_input_defaults(self):
        assert _parse_dispatch_output("") == ["ims", "transport"]


class TestAgentConstruction:
    def test_triage_agent(self):
        from agentic_ops_v3.agents.triage import create_triage_agent
        agent = create_triage_agent()
        assert agent.name == "TriageAgent"
        assert agent.output_key == "triage"
        assert len(agent.tools) == 4

    def test_tracer_agent(self):
        from agentic_ops_v3.agents.tracer import create_tracer_agent
        agent = create_tracer_agent()
        assert agent.name == "EndToEndTracer"
        assert agent.output_key == "trace"
        assert "{triage}" in agent.instruction

    def test_dispatcher_agent(self):
        from agentic_ops_v3.agents.dispatcher import create_dispatch_agent
        agent = create_dispatch_agent()
        assert agent.name == "DispatchAgent"
        assert agent.output_key == "dispatch"
        assert "{triage}" in agent.instruction
        assert "{trace}" in agent.instruction
        assert "DISPATCH:" in agent.instruction

    def test_specialists_have_state_placeholders(self):
        from agentic_ops_v3.agents.ims_specialist import create_ims_specialist
        from agentic_ops_v3.agents.transport_specialist import create_transport_specialist
        from agentic_ops_v3.agents.core_specialist import create_core_specialist
        from agentic_ops_v3.agents.subscriber_data_specialist import create_subscriber_data_specialist

        for factory in [create_ims_specialist, create_transport_specialist,
                        create_core_specialist, create_subscriber_data_specialist]:
            agent = factory()
            assert "{triage}" in agent.instruction, f"{agent.name} missing {{triage}}"
            assert "{trace}" in agent.instruction, f"{agent.name} missing {{trace}}"

    def test_synthesis_has_all_placeholders(self):
        from agentic_ops_v3.agents.synthesis import create_synthesis_agent
        agent = create_synthesis_agent()
        assert "{triage}" in agent.instruction
        assert "{trace}" in agent.instruction
        assert "{dispatch}" in agent.instruction
        assert "{finding_ims?}" in agent.instruction
        assert "{finding_transport?}" in agent.instruction
        assert "{finding_core?}" in agent.instruction
        assert "{finding_subscriber_data?}" in agent.instruction

    def test_triage_has_no_upstream_placeholders(self):
        """Triage is the first phase — it should not reference upstream state."""
        from agentic_ops_v3.agents.triage import create_triage_agent
        agent = create_triage_agent()
        assert "{triage}" not in agent.instruction
        assert "{trace}" not in agent.instruction
