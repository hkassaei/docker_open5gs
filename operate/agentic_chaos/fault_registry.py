"""
Fault Registry — SQLite-backed tracking of active faults with Triple Lock safety.

Lock 1: Every injected fault is recorded in SQLite with its heal command.
Lock 2: A background asyncio task auto-heals faults that exceed their TTL.
Lock 3: Signal handlers + atexit heal ALL active faults on process exit.

Safety invariant: a fault cannot exist in the network without a corresponding
row in the registry that has a valid heal_command and expires_at.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from .models import Fault, FaultStatus

log = logging.getLogger("chaos-registry")

# Default database path — next to this file
_DEFAULT_DB_PATH = Path(__file__).resolve().parent / "state.db"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS active_faults (
    fault_id       TEXT PRIMARY KEY,
    episode_id     TEXT NOT NULL,
    fault_type     TEXT NOT NULL,
    target         TEXT NOT NULL,
    params         TEXT NOT NULL DEFAULT '{}',
    mechanism      TEXT NOT NULL,
    heal_command   TEXT NOT NULL,
    injected_at    TEXT NOT NULL,
    ttl_seconds    INTEGER NOT NULL,
    expires_at     TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active',
    verified       INTEGER NOT NULL DEFAULT 0,
    verification_result TEXT NOT NULL DEFAULT ''
);
"""


class FaultRegistry:
    """SQLite-backed fault registry with TTL reaper and emergency cleanup."""

    def __init__(self, db_path: str | Path | None = None):
        self._db_path = str(db_path or _DEFAULT_DB_PATH)
        self._reaper_task: asyncio.Task | None = None
        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        """Whether the registry has been initialized (table created)."""
        return self._initialized

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    async def initialize(self) -> None:
        """Create the database table if it doesn't exist."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute(_CREATE_TABLE_SQL)
            await db.commit()
        self._initialized = True
        self._install_signal_handlers()
        log.info("Fault registry initialized: %s", self._db_path)

    def start_reaper(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Start the background TTL reaper task (Lock 2)."""
        if self._reaper_task and not self._reaper_task.done():
            return
        target_loop = loop or asyncio.get_event_loop()
        self._reaper_task = target_loop.create_task(self._ttl_reaper())
        log.info("TTL reaper started")

    async def shutdown(self) -> None:
        """Stop the reaper and heal all active faults."""
        if self._reaper_task and not self._reaper_task.done():
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except asyncio.CancelledError:
                pass
        await self.heal_all(method="shutdown")

    # -----------------------------------------------------------------
    # CRUD
    # -----------------------------------------------------------------

    async def register_fault(self, fault: Fault) -> None:
        """Record a fault BEFORE executing the inject command.

        The caller must:
        1. Call register_fault() to record the intent + heal_command
        2. Execute the inject command
        3. On success: call mark_verified()
        4. On failure: call remove_fault() and run the heal_command
        """
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """INSERT INTO active_faults
                   (fault_id, episode_id, fault_type, target, params,
                    mechanism, heal_command, injected_at, ttl_seconds,
                    expires_at, status, verified, verification_result)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    fault.fault_id,
                    fault.episode_id,
                    fault.fault_type,
                    fault.target,
                    json.dumps(fault.params),
                    fault.mechanism,
                    fault.heal_command,
                    fault.injected_at.isoformat(),
                    fault.ttl_seconds,
                    fault.expires_at.isoformat(),
                    fault.status.value,
                    int(fault.verified),
                    fault.verification_result,
                ),
            )
            await db.commit()
        log.info("Registered fault %s on %s (TTL=%ds)",
                 fault.fault_id, fault.target, fault.ttl_seconds)

    async def mark_verified(self, fault_id: str, result: str = "") -> None:
        """Mark a fault as verified after the inject + verify cycle succeeds."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE active_faults SET verified=1, verification_result=? WHERE fault_id=?",
                (result, fault_id),
            )
            await db.commit()

    async def mark_healed(self, fault_id: str, method: str = "scheduled") -> None:
        """Mark a fault as healed."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE active_faults SET status=? WHERE fault_id=?",
                (FaultStatus.HEALED.value, fault_id),
            )
            await db.commit()
        log.info("Healed fault %s (method=%s)", fault_id, method)

    async def mark_failed(self, fault_id: str) -> None:
        """Mark a fault that failed to inject."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE active_faults SET status=? WHERE fault_id=?",
                (FaultStatus.FAILED.value, fault_id),
            )
            await db.commit()

    async def remove_fault(self, fault_id: str) -> None:
        """Remove a fault record entirely (used when injection fails before commit)."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM active_faults WHERE fault_id=?", (fault_id,))
            await db.commit()

    async def get_active_faults(self) -> list[Fault]:
        """Return all faults with status='active'."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM active_faults WHERE status=?",
                (FaultStatus.ACTIVE.value,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_fault(r) for r in rows]

    async def get_faults_for_episode(self, episode_id: str) -> list[Fault]:
        """Return all faults (any status) for a given episode."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM active_faults WHERE episode_id=?",
                (episode_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_fault(r) for r in rows]

    async def get_expired_faults(self) -> list[Fault]:
        """Return active faults whose TTL has expired."""
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM active_faults WHERE status=? AND expires_at < ?",
                (FaultStatus.ACTIVE.value, now),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_fault(r) for r in rows]

    # -----------------------------------------------------------------
    # Lock 2: TTL Reaper
    # -----------------------------------------------------------------

    async def _ttl_reaper(self) -> None:
        """Background task: heal any fault that has exceeded its TTL."""
        while True:
            try:
                await asyncio.sleep(5)
                expired = await self.get_expired_faults()
                for fault in expired:
                    log.warning("TTL expired for fault %s on %s — auto-healing",
                                fault.fault_id, fault.target)
                    await self._execute_heal(fault.heal_command)
                    await self.mark_healed(fault.fault_id, method="ttl_expired")
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("TTL reaper error")

    # -----------------------------------------------------------------
    # Lock 3: Signal handlers + atexit
    # -----------------------------------------------------------------

    def _install_signal_handlers(self) -> None:
        """Install emergency cleanup on SIGINT, SIGTERM, and atexit."""
        atexit.register(self._emergency_heal_all_sync)

        for sig in (signal.SIGINT, signal.SIGTERM):
            original = signal.getsignal(sig)
            def _handler(signum, frame, _orig=original):
                log.warning("Signal %s received — emergency healing all faults", signum)
                self._emergency_heal_all_sync()
                # Call the original handler (e.g., KeyboardInterrupt for SIGINT)
                if callable(_orig) and _orig not in (signal.SIG_DFL, signal.SIG_IGN):
                    _orig(signum, frame)
                else:
                    sys.exit(128 + signum)
            signal.signal(sig, _handler)

        log.debug("Signal handlers installed (SIGINT, SIGTERM, atexit)")

    def _emergency_heal_all_sync(self) -> None:
        """Synchronous cleanup: heal every active fault. Called from atexit/signals."""
        import sqlite3
        if not os.path.exists(self._db_path):
            return
        try:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT fault_id, heal_command FROM active_faults WHERE status=?",
                (FaultStatus.ACTIVE.value,),
            )
            rows = cursor.fetchall()
            for row in rows:
                fid = row["fault_id"]
                cmd = row["heal_command"]
                log.warning("Emergency heal: %s — %s", fid, cmd)
                try:
                    subprocess.run(cmd, shell=True, timeout=10, capture_output=True)
                except Exception as e:
                    log.error("Emergency heal failed for %s: %s", fid, e)
                conn.execute(
                    "UPDATE active_faults SET status=? WHERE fault_id=?",
                    (FaultStatus.HEALED.value, fid),
                )
            conn.commit()
            conn.close()
        except Exception:
            log.exception("Emergency heal-all failed")

    # -----------------------------------------------------------------
    # Async heal-all (for graceful shutdown)
    # -----------------------------------------------------------------

    async def heal_all(self, method: str = "manual") -> int:
        """Heal all active faults. Returns count of faults healed."""
        faults = await self.get_active_faults()
        count = 0
        for fault in faults:
            await self._execute_heal(fault.heal_command)
            await self.mark_healed(fault.fault_id, method=method)
            count += 1
        if count:
            log.info("Healed %d active faults (method=%s)", count, method)
        return count

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    @staticmethod
    async def _execute_heal(heal_command: str) -> tuple[int, str]:
        """Run a heal command asynchronously."""
        proc = await asyncio.create_subprocess_shell(
            heal_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        output = stdout.decode(errors="replace").strip()
        if proc.returncode != 0:
            log.warning("Heal command exited %d: %s → %s",
                        proc.returncode, heal_command, output)
        return proc.returncode or 0, output

    @staticmethod
    def _row_to_fault(row) -> Fault:
        """Convert a sqlite Row to a Fault model."""
        return Fault(
            fault_id=row["fault_id"],
            episode_id=row["episode_id"],
            fault_type=row["fault_type"],
            target=row["target"],
            params=json.loads(row["params"]),
            mechanism=row["mechanism"],
            heal_command=row["heal_command"],
            injected_at=datetime.fromisoformat(row["injected_at"]),
            ttl_seconds=row["ttl_seconds"],
            expires_at=datetime.fromisoformat(row["expires_at"]),
            status=FaultStatus(row["status"]),
            verified=bool(row["verified"]),
            verification_result=row["verification_result"],
        )
