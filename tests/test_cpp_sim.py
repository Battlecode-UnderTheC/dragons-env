"""Differential test: the native sim must match the real engine move for move.

The engine only ever shows a dragon a 7x7 window. Tests use the documented
minimum 10x10 board and compare the native state inside the acting dragon's
window with the official engine's observation.

The native simulator uses the official engine's mt19937 seed and modulo-based
range reduction, so both fixed and variable pearl gaps are compared. Everything
is checked round by round: movement, sprints and their incremental cost,
collisions, splits, directed 64-bit sonar and echoes, corpse pearls, eating,
spawning and scoring.
"""
from __future__ import annotations

import random
import sys
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "cpp"))
try:
    import _dragons
except ImportError:                      # pragma: no cover
    _dragons = None

from dragons_env import WasmEngine
from dragons_env.mapgen import MapSpec, edge_between, rotate_edge, snake
from dragons_env.protocol import parse_turn

pytestmark = pytest.mark.skipif(_dragons is None,
                                reason="native sim not built; see cpp/README.md")

REL_TO_ABS = {
    "N": {"F": "N", "L": "W", "R": "E"}, "E": {"F": "E", "L": "N", "R": "S"},
    "S": {"F": "S", "L": "E", "R": "W"}, "W": {"F": "W", "L": "S", "R": "N"},
}


def scripted_action(seed, round_num, dragon_id, facing, length):
    """Depends only on (round, dragon id) and the dragon's own facing, so both
    engines can be driven through the identical sequence."""
    rng = random.Random(f"{seed}:{round_num}:{dragon_id}")
    sonars = {}
    for direction in "NESW":
        if rng.random() < 0.18:
            payload = rng.randrange(2 ** 64)
            # A dragon only opts into protocol 3 at the end of its first turn.
            # Keep round-zero values compatible with recipients still on v2.
            sonars[direction] = payload if round_num else payload & 0xFFFFFFFF
    if length >= 5 and rng.random() < 0.10:
        return ("split", rng.randint(2, length - 2), sonars)
    steps = 1 if rng.random() < 0.65 else rng.randint(2, 3)
    dirs, at = [], facing
    for _ in range(steps):
        at = REL_TO_ABS[at][rng.choice("FLR")]
        dirs.append(at)
    return ("move", "".join(dirs), sonars)


def echoes_tuple(echoes):
    return (echoes.kelp, echoes.ally, echoes.ally_head,
            echoes.enemy, echoes.enemy_head)


def random_board(rng, pearl_gap=(0, 0)) -> MapSpec:
    """A documented-minimum 10x10 symmetric board."""
    w = h = 10
    kelp = set()
    for y in range(h):
        for x in range(w):
            for direction in ("N", "W"):
                if rng.random() < 0.05:
                    edge = edge_between(x, y, direction, w, h)
                    kelp.add(edge)
                    kelp.add(rotate_edge(edge, w, h))
    first = snake(2, 2, 3, "E", w, h)
    second = [(w - 1 - x, h - 1 - y) for x, y in first]
    spec = MapSpec(w, h, [(0, first), (1, second)], kelp=sorted(kelp),
                   pearl_gap=pearl_gap, symmetry="xy")
    spawn = {p for _, segs in spec.dragons for p in segs}
    spec.kelp = [e for e in spec.kelp
                 if all(e != edge_between(x, y, d, w, h)
                        for x, y in spawn for d in "NESW")]
    return spec


def engine_states(spec: MapSpec, seed: int):
    """Drive the real engine, recording the full board before every turn."""
    engine = WasmEngine()
    seen: list[tuple] = []
    deaths: list[tuple] = []

    def reply(dragon_id: int, raw: bytes) -> bytes:
        block = parse_turn(raw.decode(), spec.width, spec.height)
        pearls = sorted((int(block.xs[i]), int(block.ys[i]))
                        for i in range(49) if block.pearl[i])
        parts = sorted((p.dragon_id, p.x, p.y, p.is_head) for p in block.parts)
        seen.append((block.round, dragon_id, block.length, block.facing,
                     tuple(block.messages), echoes_tuple(block.echoes),
                     tuple(pearls), tuple(parts)))
        kind, arg, sonars = scripted_action(
            seed, block.round, dragon_id, block.facing, block.length)
        lines = [f"MOVE {arg}"] if kind == "move" else [f"SPLIT {arg}"]
        lines += [f"SONAR {direction} {payload}"
                  for direction, payload in sonars.items()]
        lines.append("PROTOCOL 3")
        return ("\n".join(lines) + "\n").encode()

    result = engine.run(spec.to_bytes(), reply, None,
                        lambda d, r, why: deaths.append((d, r, why)), None)
    return seen, deaths, result.winner


def native_states(spec: MapSpec, seed: int):
    game = _dragons.Game.from_map_text(spec.to_text())
    seen: list[tuple] = []
    while game.round < 500:
        # Every dragon alive when its turn comes round acts, including one born
        # from a split earlier in this same round; the engine only decides the
        # match once the whole round is done.
        game.begin_round()
        index = 0
        while index < len(game.dragons()):
            dragon = game.dragons()[index]
            if not dragon["alive"]:
                index += 1
                continue
            hx, hy = dragon["segments"][0]
            visible = {((hx + dx) % game.width, (hy + dy) % game.height)
                       for dy in range(-3, 4) for dx in range(-3, 4)}
            pearls = tuple(sorted(tuple(p) for p in game.pearls()
                                  if tuple(p) in visible))
            parts = []
            for other in game.dragons():
                if not other["alive"]:
                    continue
                for i, (x, y) in enumerate(other["segments"]):
                    if (x, y) in visible:
                        parts.append((other["id"], x, y, i == 0))
            echoes = dragon["echoes"]
            seen.append((game.round, dragon["id"], dragon["length"],
                         dragon["facing"], tuple(dragon["inbox"]),
                         tuple(echoes[name] for name in
                               ("kelp", "ally", "ally_head", "enemy", "enemy_head")),
                         pearls, tuple(sorted(parts))))
            kind, arg, sonars = scripted_action(
                seed, game.round, dragon["id"], dragon["facing"], dragon["length"])
            action = (_dragons.Action.move(arg, sonars=sonars) if kind == "move"
                      else _dragons.Action.split(arg, sonars=sonars))
            game.take_turn(index, action)
            index += 1
        game.end_round()
        if game.finished():
            break
    return seen, game.deaths(), game.result()


@pytest.mark.parametrize("gap", [(0, 0), (1, 1), (4, 4), (1, 5)])
@pytest.mark.parametrize("seed", list(range(8)))
def test_native_sim_matches_the_engine(seed, gap):
    rng = random.Random(seed)
    spec = random_board(rng, pearl_gap=gap)
    engine_seen, engine_deaths, engine_winner = engine_states(spec, seed)
    native_seen, native_deaths, native_winner = native_states(spec, seed)

    for i, (a, b) in enumerate(zip(engine_seen, native_seen)):
        assert a == b, (
            f"diverged at turn {i} (round {a[0]}, dragon {a[1]}):\n"
            f"  engine: len={a[2]} facing={a[3]} msgs={a[4]} echoes={a[5]}\n"
            f"          pearls={a[6]}\n          parts={a[7]}\n"
            f"  native: len={b[2]} facing={b[3]} msgs={b[4]} echoes={b[5]}\n"
            f"          pearls={b[6]}\n          parts={b[7]}")
    assert len(engine_seen) == len(native_seen), (
        f"turn counts differ: engine {len(engine_seen)} vs native {len(native_seen)}")
    assert [(d, r) for d, r, _ in engine_deaths] == [(d, r) for d, r, _ in native_deaths]
    assert [w for _, _, w in engine_deaths] == [w for _, _, w in native_deaths]
    expected = {"A": "A", "B": "B", None: "draw"}[engine_winner]
    assert native_winner == expected
