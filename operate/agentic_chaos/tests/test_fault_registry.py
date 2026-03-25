"""Unit tests for agentic_chaos.fault_registry — uses temp SQLite, no Docker."""

import asyncio
from datetime import datetime, timezone, timedelta

import pytest
import pytest_asyncio

from agentic_chaos.fault_registry import FaultRegistry
from agentic_chaos.models import Fault, FaultStatus


@pytest_asyncio.fixture
async def registry(tmp_db):
    """Create and initialize a FaultRegistry with a temp database."""
    reg = FaultRegistry(db_path=tmp_db)
    await reg.initialize()
    yield reg
    # No reaper to stop in unit tests — we don't start it


def _make_fault(
    fault_id: str = "f_001",
    episode_id: str = "ep_test",
    ttl_seconds: int = 120,
    expired: bool = False,
) -> Fault:
    """Helper to create a Fault with sensible defaults."""
    now = datetime.now(timezone.utc)
    if expired:
        injected_at = now - timedelta(seconds=ttl_seconds + 10)
        expires_at = now - timedelta(seconds=10)
    else:
        injected_at = now
        expires_at = now + timedelta(seconds=ttl_seconds)

    return Fault(
        fault_id=fault_id,
        episode_id=episode_id,
        fault_type="network_latency",
        target="pcscf",
        params={"delay_ms": 500},
        mechanism="sudo nsenter -t 999 -n tc qdisc add dev eth0 root netem delay 500ms",
        heal_command="echo healed",  # Safe no-op for tests
        injected_at=injected_at,
        ttl_seconds=ttl_seconds,
        expires_at=expires_at,
    )


# -------------------------------------------------------------------------
# Basic CRUD
# -------------------------------------------------------------------------

class TestRegistryCRUD:
    @pytest.mark.asyncio
    async def test_initialize_creates_table(self, registry):
        import aiosqlite
        async with aiosqlite.connect(registry._db_path) as db:
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ) as cur:
                tables = [row[0] async for row in cur]
        assert "active_faults" in tables

    @pytest.mark.asyncio
    async def test_register_and_get(self, registry):
        f = _make_fault()
        await registry.register_fault(f)

        active = await registry.get_active_faults()
        assert len(active) == 1
        assert active[0].fault_id == "f_001"
        assert active[0].status == FaultStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_register_multiple_faults(self, registry):
        await registry.register_fault(_make_fault(fault_id="f_001"))
        await registry.register_fault(_make_fault(fault_id="f_002"))
        await registry.register_fault(_make_fault(fault_id="f_003"))

        active = await registry.get_active_faults()
        assert len(active) == 3

    @pytest.mark.asyncio
    async def test_mark_healed(self, registry):
        await registry.register_fault(_make_fault())
        await registry.mark_healed("f_001", method="test")

        active = await registry.get_active_faults()
        assert len(active) == 0

    @pytest.mark.asyncio
    async def test_mark_verified(self, registry):
        await registry.register_fault(_make_fault())
        await registry.mark_verified("f_001", result="RTT 523ms")

        active = await registry.get_active_faults()
        assert active[0].verified is True
        assert active[0].verification_result == "RTT 523ms"

    @pytest.mark.asyncio
    async def test_mark_failed(self, registry):
        await registry.register_fault(_make_fault())
        await registry.mark_failed("f_001")

        active = await registry.get_active_faults()
        assert len(active) == 0  # Failed faults are not "active"

    @pytest.mark.asyncio
    async def test_remove_fault(self, registry):
        await registry.register_fault(_make_fault())
        await registry.remove_fault("f_001")

        active = await registry.get_active_faults()
        assert len(active) == 0

    @pytest.mark.asyncio
    async def test_get_faults_for_episode(self, registry):
        await registry.register_fault(_make_fault(fault_id="f_001", episode_id="ep_A"))
        await registry.register_fault(_make_fault(fault_id="f_002", episode_id="ep_A"))
        await registry.register_fault(_make_fault(fault_id="f_003", episode_id="ep_B"))

        ep_a = await registry.get_faults_for_episode("ep_A")
        assert len(ep_a) == 2

        ep_b = await registry.get_faults_for_episode("ep_B")
        assert len(ep_b) == 1

    @pytest.mark.asyncio
    async def test_duplicate_fault_id_raises(self, registry):
        await registry.register_fault(_make_fault(fault_id="f_dup"))
        with pytest.raises(Exception):  # IntegrityError from SQLite
            await registry.register_fault(_make_fault(fault_id="f_dup"))


# -------------------------------------------------------------------------
# TTL expiry detection
# -------------------------------------------------------------------------

class TestTTLExpiry:
    @pytest.mark.asyncio
    async def test_expired_faults_detected(self, registry):
        await registry.register_fault(_make_fault(fault_id="f_expired", expired=True))
        await registry.register_fault(_make_fault(fault_id="f_fresh", expired=False))

        expired = await registry.get_expired_faults()
        assert len(expired) == 1
        assert expired[0].fault_id == "f_expired"

    @pytest.mark.asyncio
    async def test_no_expired_when_all_fresh(self, registry):
        await registry.register_fault(_make_fault(fault_id="f_1"))
        await registry.register_fault(_make_fault(fault_id="f_2"))

        expired = await registry.get_expired_faults()
        assert len(expired) == 0

    @pytest.mark.asyncio
    async def test_healed_faults_not_in_expired(self, registry):
        await registry.register_fault(_make_fault(fault_id="f_old", expired=True))
        await registry.mark_healed("f_old")

        expired = await registry.get_expired_faults()
        assert len(expired) == 0


# -------------------------------------------------------------------------
# heal_all
# -------------------------------------------------------------------------

class TestHealAll:
    @pytest.mark.asyncio
    async def test_heal_all_clears_active(self, registry):
        await registry.register_fault(_make_fault(fault_id="f_1"))
        await registry.register_fault(_make_fault(fault_id="f_2"))

        count = await registry.heal_all(method="test")
        assert count == 2

        active = await registry.get_active_faults()
        assert len(active) == 0

    @pytest.mark.asyncio
    async def test_heal_all_returns_zero_when_empty(self, registry):
        count = await registry.heal_all()
        assert count == 0

    @pytest.mark.asyncio
    async def test_heal_all_skips_already_healed(self, registry):
        await registry.register_fault(_make_fault(fault_id="f_1"))
        await registry.mark_healed("f_1")

        count = await registry.heal_all()
        assert count == 0


# -------------------------------------------------------------------------
# Fault model roundtrip through registry
# -------------------------------------------------------------------------

class TestFaultRoundtrip:
    @pytest.mark.asyncio
    async def test_params_preserved(self, registry):
        """Verify JSON params survive the SQLite roundtrip."""
        f = _make_fault()
        f.params = {"delay_ms": 500, "jitter_ms": 50, "nested": {"a": 1}}
        await registry.register_fault(f)

        active = await registry.get_active_faults()
        assert active[0].params == {"delay_ms": 500, "jitter_ms": 50, "nested": {"a": 1}}

    @pytest.mark.asyncio
    async def test_timestamps_preserved(self, registry):
        f = _make_fault()
        await registry.register_fault(f)

        active = await registry.get_active_faults()
        # Timestamps should roundtrip within 1 second (ISO format precision)
        assert abs((active[0].injected_at - f.injected_at).total_seconds()) < 1
        assert abs((active[0].expires_at - f.expires_at).total_seconds()) < 1


# -------------------------------------------------------------------------
# Emergency heal (synchronous)
# -------------------------------------------------------------------------

class TestEmergencyHeal:
    @pytest.mark.asyncio
    async def test_emergency_sync_heals_active_faults(self, registry):
        await registry.register_fault(_make_fault(fault_id="f_1"))
        await registry.register_fault(_make_fault(fault_id="f_2"))

        # Call the synchronous emergency heal (simulating atexit/signal)
        registry._emergency_heal_all_sync()

        # Verify faults are now healed
        active = await registry.get_active_faults()
        assert len(active) == 0

    def test_emergency_sync_handles_missing_db(self, tmp_path):
        """Emergency heal should not crash if the DB file doesn't exist."""
        reg = FaultRegistry(db_path=tmp_path / "nonexistent.db")
        reg._emergency_heal_all_sync()  # Should not raise
