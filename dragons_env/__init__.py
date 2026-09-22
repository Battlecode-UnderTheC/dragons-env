"""A fast, verified implementation of the UNSW Battlecode dragons game.

`dragons_env.engine` drives the official wasm engine, which is ground truth.
The native simulator in `cpp/` reimplements the same rules roughly 500x faster,
and `tests/` compares the two turn for turn.

This package is the environment only. Observation encoding, action spaces and
anything else an agent needs belong with the agent, not here.
"""

from .engine import MatchResult, WasmEngine
from .protocol import SpawnInfo, TurnBlock, parse_spawn, parse_turn
from . import mapgen

__all__ = ["WasmEngine", "MatchResult", "TurnBlock", "SpawnInfo", "parse_turn",
           "parse_spawn", "mapgen"]
