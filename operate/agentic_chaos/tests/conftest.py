"""Shared fixtures for chaos monkey tests."""

import asyncio
import os
import sys
from pathlib import Path

import pytest

# Ensure operate/ is on the import path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


@pytest.fixture(scope="session")
def event_loop():
    """Use a single event loop for all async tests in the session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def tmp_db(tmp_path):
    """Return a path to a temporary SQLite database."""
    return tmp_path / "test_registry.db"


def is_stack_running() -> bool:
    """Check if the Docker stack is running (for functional test gating)."""
    import subprocess
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Status}}", "amf"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() == "running"
    except Exception:
        return False


# Marker for tests that require the live Docker stack
requires_stack = pytest.mark.skipif(
    not is_stack_running(),
    reason="Docker stack not running",
)
