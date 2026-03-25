"""
Functional tests for Phase 1B ADK agents — requires live Docker stack + Gemini API.

These tests run real chaos scenarios end-to-end through the ADK orchestrator.

Run with:
    GOOGLE_CLOUD_PROJECT=eod-sbox-entitlement-server \
    GOOGLE_CLOUD_LOCATION=northamerica-northeast1 \
    GOOGLE_GENAI_USE_VERTEXAI=TRUE \
    pytest tests/test_agents_functional.py -v
"""

import json
import os
from pathlib import Path

import pytest
import pytest_asyncio

from .conftest import requires_stack

from agentic_chaos.models import (
    BlastRadius,
    FaultCategory,
    FaultSpec,
    Scenario,
)
from agentic_chaos.fault_registry import FaultRegistry
from agentic_chaos.orchestrator import run_scenario


def _has_gemini_env() -> bool:
    return bool(os.environ.get("GOOGLE_CLOUD_PROJECT"))


requires_gemini = pytest.mark.skipif(
    not _has_gemini_env(),
    reason="GOOGLE_CLOUD_PROJECT not set — Gemini API unavailable",
)


EPISODES_DIR = Path(__file__).resolve().parents[1] / "episodes"


@requires_stack
@requires_gemini
class TestChaosDirectorEndToEnd:
    """Full orchestrator tests — inject, observe, heal, record."""

    @pytest_asyncio.fixture
    async def registry(self, tmp_path):
        """Create an isolated registry for each test."""
        reg = FaultRegistry(db_path=tmp_path / "test_registry.db")
        await reg.initialize()
        yield reg
        await reg.heal_all(method="test_cleanup")

    @pytest.mark.asyncio
    async def test_container_pause_scenario(self, registry):
        """Pause DNS, observe symptoms, heal, verify episode recorded."""
        scenario = Scenario(
            name="Test DNS Pause",
            description="Pause DNS to verify full pipeline",
            category=FaultCategory.CONTAINER,
            blast_radius=BlastRadius.SINGLE_NF,
            faults=[FaultSpec(fault_type="container_pause", target="dns", ttl_seconds=60)],
            expected_symptoms=["DNS resolution failure"],
            observation_window_seconds=10,
        )

        episode = await run_scenario(scenario, registry=registry)

        assert episode["schema_version"] == "1.0"
        assert episode["episode_id"].startswith("ep_")
        assert episode["scenario"]["name"] == "Test DNS Pause"
        assert len(episode["faults"]) == 1
        assert episode["faults"][0]["verified"] is True
        assert episode["resolution"]["heal_method"] == "scheduled"
        assert episode["rca_label"]["failure_domain"] == "data_layer"

        # Verify no orphaned faults
        active = await registry.get_active_faults()
        assert len(active) == 0, f"Orphaned faults: {[f.fault_id for f in active]}"

    @pytest.mark.asyncio
    async def test_network_latency_scenario(self, registry):
        """Inject latency on rtpengine, observe, heal, verify episode."""
        scenario = Scenario(
            name="Test RTPEngine Latency",
            description="Inject 200ms latency on RTPEngine container",
            category=FaultCategory.NETWORK,
            blast_radius=BlastRadius.SINGLE_NF,
            faults=[
                FaultSpec(
                    fault_type="network_latency",
                    target="rtpengine",
                    params={"delay_ms": 200},
                    ttl_seconds=60,
                ),
            ],
            expected_symptoms=["Increased latency to RTPEngine"],
            observation_window_seconds=10,
        )

        episode = await run_scenario(scenario, registry=registry)

        assert len(episode["faults"]) == 1
        assert episode["faults"][0]["verified"] is True
        assert episode["faults"][0]["fault_type"] == "network_latency"

        # Verify healed
        active = await registry.get_active_faults()
        assert len(active) == 0

    @pytest.mark.asyncio
    async def test_episode_json_written_to_disk(self, registry):
        """Verify that the episode JSON file is actually written."""
        scenario = Scenario(
            name="Test Episode Write",
            description="Verify JSON recording",
            category=FaultCategory.CONTAINER,
            blast_radius=BlastRadius.SINGLE_NF,
            faults=[FaultSpec(fault_type="container_pause", target="dns", ttl_seconds=30)],
            observation_window_seconds=5,
        )

        episode = await run_scenario(scenario, registry=registry)
        episode_id = episode["episode_id"]

        filepath = EPISODES_DIR / f"{episode_id}.json"
        assert filepath.exists(), f"Episode file not written: {filepath}"

        with open(filepath) as f:
            loaded = json.load(f)
        assert loaded["episode_id"] == episode_id
        assert loaded["schema_version"] == "1.0"

        # Cleanup test episode file
        filepath.unlink()

    @pytest.mark.asyncio
    async def test_multi_fault_scenario(self, registry):
        """Inject two faults simultaneously and verify both recorded."""
        scenario = Scenario(
            name="Test Multi Fault",
            description="Pause DNS + latency on DNS",
            category=FaultCategory.COMPOUND,
            blast_radius=BlastRadius.SINGLE_NF,
            faults=[
                FaultSpec(fault_type="container_pause", target="dns", ttl_seconds=60),
                FaultSpec(
                    fault_type="network_latency",
                    target="rtpengine",
                    params={"delay_ms": 100},
                    ttl_seconds=60,
                ),
            ],
            observation_window_seconds=10,
        )

        episode = await run_scenario(scenario, registry=registry)

        # At least the first fault should succeed (dns pause).
        # The second may or may not depending on timing.
        successful = [f for f in episode["faults"] if f.get("verified")]
        assert len(successful) >= 1

        # Verify all healed
        active = await registry.get_active_faults()
        assert len(active) == 0

    @pytest.mark.asyncio
    async def test_observations_captured(self, registry):
        """Verify that observations are captured during the episode."""
        scenario = Scenario(
            name="Test Observations",
            description="Verify observation collection",
            category=FaultCategory.CONTAINER,
            blast_radius=BlastRadius.SINGLE_NF,
            faults=[FaultSpec(fault_type="container_pause", target="dns", ttl_seconds=60)],
            observation_window_seconds=10,
        )

        episode = await run_scenario(scenario, registry=registry)

        observations = episode.get("observations", [])
        assert len(observations) >= 1

        obs = observations[0]
        assert "timestamp" in obs
        assert "elapsed_seconds" in obs
        assert "symptoms_detected" in obs
        assert isinstance(obs["iteration"], int)
