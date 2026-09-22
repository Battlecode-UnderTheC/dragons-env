"""Helpers for driving the official engine with scripted dragons."""
from __future__ import annotations

import pytest

from dragons_env import WasmEngine, parse_spawn, parse_turn
from dragons_env.mapgen import MapSpec, snake


@pytest.fixture(scope="session")
def engine() -> WasmEngine:
    return WasmEngine()
