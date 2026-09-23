"""Regression tests for rule mismatches found during the problem.md audit."""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "cpp"))
try:
    import _dragons
except ImportError:  # pragma: no cover
    _dragons = None

from dragons_env.mapgen import MapSpec, north, snake, west
from dragons_env import WasmEngine
from dragons_env.protocol import parse_turn

pytestmark = pytest.mark.skipif(_dragons is None, reason="native sim not built")


def two_dragons(length: int = 3):
    return [
        (0, snake(3, 3, length, "E", 10, 10)),
        (1, snake(8, 8, length, "W", 10, 10)),
    ]


def test_split_then_sonar_uses_live_parent_reference():
    game = _dragons.Game.from_map_text(
        MapSpec(10, 10, two_dragons(4), pearl_gap=(0, 0)).to_text())
    game.begin_round()
    game.take_turn(0, _dragons.Action.split(2, True, 12345))

    dragons = game.dragons()
    assert len(dragons) == 3
    assert dragons[2]["inbox"] == [12345]


def test_tail_refraction_directed_uint64_and_echo_match_official_engine():
    """A westward ray enters A's body, leaves its tail, and hits B's head."""
    payload = 2 ** 64 - 1
    spec = MapSpec(
        10, 10,
        [(0, [(5, 5), (4, 5), (3, 5), (2, 5)]),
         (1, [(0, 5), (9, 5), (8, 5)])],
        pearl_gap=(0, 0),
    )
    official = {}

    def reply(dragon_id, raw):
        block = parse_turn(raw.decode(), 10, 10)
        if block.round == 1 and dragon_id == 1:
            official["messages"] = block.messages
        if block.round == 2 and dragon_id == 0:
            official["echoes"] = block.echoes
            return b""
        lines = ["MOVE E", "PROTOCOL 3"]
        if block.round == 1 and dragon_id == 0:
            lines.insert(1, f"SONAR W {payload}")
        return ("\n".join(lines) + "\n").encode()

    WasmEngine().run(spec.to_bytes(), reply)

    game = _dragons.Game.from_map_text(spec.to_text())
    game.begin_round()
    game.take_turn(0, _dragons.Action.move("E"))
    game.take_turn(1, _dragons.Action.move("E"))
    game.end_round()
    game.begin_round()
    game.take_turn(0, _dragons.Action.move("E", sonars={"W": payload}))
    assert game.dragons()[1]["inbox"] == official["messages"] == [payload]
    game.take_turn(1, _dragons.Action.move("E"))
    game.end_round()

    echo = game.dragons()[0]["echoes"]
    assert (echo["kelp"], echo["ally"], echo["ally_head"],
            echo["enemy"], echo["enemy_head"]) == (
        official["echoes"].kelp, official["echoes"].ally,
        official["echoes"].ally_head, official["echoes"].enemy,
        official["echoes"].enemy_head,
    ) == (0, 0, 0, 0, 1)


def test_next_turn_includes_child_born_during_round():
    game = _dragons.Game.from_map_text(
        MapSpec(10, 10, two_dragons(4), pearl_gap=(0, 0)).to_text())
    game.begin_round()
    first = game.next_turn()
    assert first == 0
    game.take_turn(first, _dragons.Action.split(2))
    assert game.next_turn(1) == 2


def test_crossing_portals_on_same_owner_keep_their_orientation():
    portals = [
        (north(2, 2, 10), 10),
        (north(7, 7, 10), 10),
        (west(2, 2, 10), 11),
        (west(6, 6, 10), 11),
    ]
    dragons = [
        (0, snake(2, 2, 3, "N", 10, 10)),
        (1, snake(9, 9, 3, "W", 10, 10)),
    ]
    game = _dragons.Game.from_map_text(
        MapSpec(10, 10, dragons, portals=portals, pearl_gap=(0, 0)).to_text())
    game.begin_round()
    game.take_turn(0, _dragons.Action.move("N"))
    assert game.dragons()[0]["segments"][0] == (7, 6)


def test_symmetric_tiles_share_countdown():
    spec = MapSpec(10, 10, two_dragons(), pearl_gap=(2, 9), symmetry="xy")
    game = _dragons.Game.from_map_text(spec.to_text(), seed=7)
    for _ in range(20):
        countdowns = game.pearl_countdowns()
        for y in range(10):
            for x in range(10):
                assert countdowns[y * 10 + x] == countdowns[(9 - y) * 10 + 9 - x]
        game.begin_round()


def test_symmetry_letters_name_the_mirror_axis():
    gaps = {(0, 0): (2, 2), (9, 0): (2, 2)}
    spec = MapSpec(10, 10, two_dragons(), pearl_gap=(0, 0), tile_gaps=gaps,
                   symmetry="y")
    game = _dragons.Game.from_map_text(spec.to_text())
    countdowns = game.pearl_countdowns()
    assert countdowns[0] == countdowns[9] == 2


@pytest.mark.parametrize("symmetry", [None, "xy"])
def test_variable_pearl_rng_matches_official_engine(symmetry):
    spec = MapSpec(10, 10, two_dragons(), pearl_gap=(1, 2_147_483_647),
                   symmetry=symmetry)
    official = []

    def reply(_dragon_id, raw):
        block = parse_turn(raw.decode(), 10, 10)
        if not official:
            official.extend(int(value) for value in block.pearl_time)
        return b""  # end the probe match immediately

    WasmEngine().run(spec.to_bytes(), reply)

    game = _dragons.Game.from_map_text(spec.to_text())
    game.begin_round()
    native = game.pearl_countdowns()
    visible = [native[y * 10 + x] for y in range(7) for x in range(7)]
    assert visible == official


def test_documented_map_dimension_limits_are_enforced():
    with pytest.raises(ValueError, match="between 10 and 64"):
        MapSpec(7, 10, two_dragons(), pearl_gap=(0, 0)).to_text()

    bad = "MAP 7 10\nTILE_COUNT 0\nEDGE_COUNT 0\nDRAGON_COUNT 0\n"
    with pytest.raises(RuntimeError, match="between 10 and 64"):
        _dragons.Game.from_map_text(bad)
