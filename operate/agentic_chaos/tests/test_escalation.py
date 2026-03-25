"""Unit tests for escalation logic — schedules + EscalationChecker decisions."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from agentic_chaos.models import ESCALATION_SCHEDULES


# -------------------------------------------------------------------------
# Schedule structure tests (no Docker, no ADK)
# -------------------------------------------------------------------------

class TestEscalationSchedules:
    def test_latency_levels_increase(self):
        levels = ESCALATION_SCHEDULES["network_latency"]
        delays = [l["delay_ms"] for l in levels]
        assert delays == sorted(delays)
        assert delays[0] == 100   # Starting level
        assert delays[-1] == 2000  # Max level

    def test_loss_levels_increase(self):
        levels = ESCALATION_SCHEDULES["network_loss"]
        losses = [l["loss_pct"] for l in levels]
        assert losses == sorted(losses)
        assert losses[-1] <= 100

    def test_bandwidth_levels_decrease(self):
        """Bandwidth limits get tighter (lower = more restrictive)."""
        levels = ESCALATION_SCHEDULES["network_bandwidth"]
        rates = [l["rate_kbit"] for l in levels]
        assert rates == sorted(rates, reverse=True)

    def test_jitter_levels_increase(self):
        levels = ESCALATION_SCHEDULES["network_jitter"]
        jitters = [l["jitter_ms"] for l in levels]
        assert jitters == sorted(jitters)

    def test_all_schedules_have_4_levels(self):
        for name, schedule in ESCALATION_SCHEDULES.items():
            assert len(schedule) == 4, f"{name} has {len(schedule)} levels, expected 4"

    def test_schedule_keys_match_fault_types(self):
        """Escalation schedule keys should map to valid network fault types."""
        expected_prefixes = {"network_latency", "network_loss", "network_bandwidth", "network_jitter"}
        assert set(ESCALATION_SCHEDULES.keys()) == expected_prefixes


# -------------------------------------------------------------------------
# EscalationChecker decision logic tests (mocked ADK context)
# -------------------------------------------------------------------------

class TestEscalationCheckerDecisions:
    """Test the EscalationChecker's decision logic using mock ADK contexts.

    These tests verify the agent's decision-making without running ADK or Docker:
    - symptoms detected → escalate (exit loop)
    - no symptoms + escalation disabled → continue
    - no symptoms + escalation enabled → escalate fault severity
    - max escalation level → exit loop
    """

    def _make_mock_ctx(self, state: dict):
        """Create a mock InvocationContext with the given state."""
        ctx = MagicMock()
        ctx.session.state = state
        return ctx

    @pytest.mark.asyncio
    async def test_symptoms_detected_exits_loop(self):
        """When symptoms are detected, checker should yield escalate=True."""
        from agentic_chaos.agents.escalation import EscalationChecker
        from agentic_chaos.fault_registry import FaultRegistry

        registry = AsyncMock(spec=FaultRegistry)
        checker = EscalationChecker(registry=registry)

        ctx = self._make_mock_ctx({
            "symptoms_detected": True,
            "scenario": {"escalation": True, "faults": []},
            "escalation_level": 0,
        })

        events = []
        async for event in checker._run_async_impl(ctx):
            events.append(event)

        assert len(events) == 1
        assert events[0].actions.escalate is True
        assert "Symptoms detected" in events[0].content.parts[0].text

    @pytest.mark.asyncio
    async def test_no_symptoms_escalation_disabled_continues(self):
        """When escalation is disabled and no symptoms, should just continue."""
        from agentic_chaos.agents.escalation import EscalationChecker
        from agentic_chaos.fault_registry import FaultRegistry

        registry = AsyncMock(spec=FaultRegistry)
        checker = EscalationChecker(registry=registry)

        ctx = self._make_mock_ctx({
            "symptoms_detected": False,
            "scenario": {"escalation": False, "faults": []},
            "escalation_level": 0,
        })

        events = []
        async for event in checker._run_async_impl(ctx):
            events.append(event)

        assert len(events) == 1
        # Should NOT escalate (exit loop) — just continue
        assert events[0].actions.escalate is not True
        assert "continuing" in events[0].content.parts[0].text.lower()

    @pytest.mark.asyncio
    async def test_max_level_exits_loop(self):
        """When max escalation level reached, should exit loop."""
        from agentic_chaos.agents.escalation import EscalationChecker
        from agentic_chaos.fault_registry import FaultRegistry

        registry = AsyncMock(spec=FaultRegistry)
        checker = EscalationChecker(registry=registry)

        # Level 3 is the last (0-indexed) for network_latency (4 levels total)
        ctx = self._make_mock_ctx({
            "symptoms_detected": False,
            "scenario": {
                "escalation": True,
                "faults": [{"fault_type": "network_latency", "target": "pcscf", "params": {"delay_ms": 100}}],
            },
            "escalation_level": 3,  # Already at max
        })

        events = []
        async for event in checker._run_async_impl(ctx):
            events.append(event)

        assert len(events) == 1
        assert events[0].actions.escalate is True
        assert "max" in events[0].content.parts[0].text.lower()

    @pytest.mark.asyncio
    async def test_no_escalatable_faults_continues(self):
        """Scenarios with non-escalatable fault types (e.g., container_kill) should continue."""
        from agentic_chaos.agents.escalation import EscalationChecker
        from agentic_chaos.fault_registry import FaultRegistry

        registry = AsyncMock(spec=FaultRegistry)
        checker = EscalationChecker(registry=registry)

        ctx = self._make_mock_ctx({
            "symptoms_detected": False,
            "scenario": {
                "escalation": True,
                "faults": [{"fault_type": "container_kill", "target": "dns"}],
            },
            "escalation_level": 0,
        })

        events = []
        async for event in checker._run_async_impl(ctx):
            events.append(event)

        assert len(events) == 1
        assert "No escalatable" in events[0].content.parts[0].text

    @pytest.mark.asyncio
    async def test_escalation_heals_and_reinjects(self):
        """When escalation triggers, should heal current faults and re-inject at new level."""
        from agentic_chaos.agents.escalation import EscalationChecker
        from agentic_chaos.fault_registry import FaultRegistry

        registry = AsyncMock(spec=FaultRegistry)
        registry.heal_all = AsyncMock(return_value=1)
        registry.register_fault = AsyncMock()

        checker = EscalationChecker(registry=registry)

        ctx = self._make_mock_ctx({
            "symptoms_detected": False,
            "scenario": {
                "escalation": True,
                "faults": [{"fault_type": "network_latency", "target": "dns",
                            "params": {"delay_ms": 100}, "ttl_seconds": 60}],
            },
            "escalation_level": 0,
            "episode_id": "ep_test",
            "faults_injected": [],
        })

        # Mock the network tools to succeed
        with patch("agentic_chaos.agents.escalation.clear_tc_rules", new_callable=AsyncMock) as mock_clear, \
             patch("agentic_chaos.agents.escalation.inject_latency", new_callable=AsyncMock) as mock_inject:
            mock_clear.return_value = {"success": True}
            mock_inject.return_value = {
                "success": True,
                "mechanism": "tc qdisc add ...",
                "heal_cmd": "tc qdisc del ...",
                "pid": 12345,
            }

            events = []
            async for event in checker._run_async_impl(ctx):
                events.append(event)

        assert len(events) == 1
        # Should have healed existing faults
        registry.heal_all.assert_called_once_with(method="escalation")
        # Should have re-injected at level 1 (delay_ms=250)
        mock_inject.assert_called_once()
        call_args = mock_inject.call_args
        assert call_args[0][0] == "dns"  # container
        assert call_args[0][1] == 250    # level 1 delay_ms
        # Should have registered the new fault
        registry.register_fault.assert_called_once()
        # State delta should include new escalation level
        assert events[0].actions.state_delta["escalation_level"] == 1
        assert "level 1" in events[0].content.parts[0].text.lower()
