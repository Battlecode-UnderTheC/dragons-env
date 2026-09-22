"""A fast, verified implementation of the UNSW Battlecode dragons game.

`dragons_env.engine` drives the official wasm engine, which is ground truth.
The native simulator in `cpp/` reimplements the same rules about 500x faster,
and `tests/` compares the two turn for turn.
"""

from .actions import ActionSpace
from .engine import MatchResult, WasmEngine
from .match import Action, MatchRunner, MatchOutcome, Obs
from .native import NativeVecEnv, SlotBatch
from .observation import ObservationEncoder
from .protocol import SpawnInfo, TurnBlock, parse_spawn, parse_turn
from . import mapgen

__all__ = ["ActionSpace", "WasmEngine", "MatchResult", "MatchRunner", "Action",
           "MatchOutcome", "Obs", "NativeVecEnv", "SlotBatch",
           "ObservationEncoder", "TurnBlock", "SpawnInfo", "parse_turn",
           "parse_spawn", "mapgen"]
