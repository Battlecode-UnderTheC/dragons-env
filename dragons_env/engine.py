"""In-process driver for the official engine (`unswbc_engine.wasm`).

The engine runs a whole match inside one `ubc_run` call and calls back into the
host once per dragon-turn; there is no step/reset API. So the environment is
callback shaped: you hand `run` a `reply(dragon_id, block) -> bytes` and it
drives the match to completion.

Compiling the 4.5 MB module takes a moment, so one `WasmEngine` should be built
per process and reused across matches.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from unswbc.engine import DEBUG_ALL, EngineModule

# The replay/indicator channels cost time and we never read them while training.
DEBUG_NONE = 0

DEATH_REASONS = {
    "W": "hit a wall",
    "S": "hit itself",
    "O": "hit another dragon",
    "H": "lost a head-to-head",
    "A": "no valid action",
}


@dataclass
class MatchResult:
    """What the engine reports at the end of a match.

    `a_length`/`b_length` are TOTAL living length, which is only the tiebreak --
    the winner is decided by the longest single living dragon.
    """
    rounds: int
    winner: str | None          # "A", "B" or None for a draw
    end_reason: int             # 0 = elimination, 1 = on length
    a_dragons: int
    b_dragons: int
    a_length: int
    b_length: int
    events: int


class WasmEngine:
    """One compiled copy of the engine, reusable for many matches."""

    def __init__(self) -> None:
        self._module = EngineModule()

    def run(
        self,
        map_bytes: bytes,
        reply: Callable[[int, bytes], bytes],
        on_spawn: Callable[[int, bytes], None] | None = None,
        on_death: Callable[[int, int, str], None] | None = None,
        on_notice: Callable[[str], None] | None = None,
        debug: int = DEBUG_NONE,
    ) -> MatchResult:
        result = self._module.run(map_bytes, reply, on_death, on_spawn,
                                  on_notice or (lambda line: None), debug)
        return MatchResult(result.rounds, result.winner, result.end_reason,
                           result.a_dragons, result.b_dragons,
                           result.a_length, result.b_length, result.events)

    def replay(self, team_a: str = "A", team_b: str = "B") -> bytes:
        """Replay blob for the match just run (needs debug != DEBUG_NONE to be useful)."""
        return self._module.replay(team_a, team_b)
