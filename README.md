# dragons-env

A fast simulator for the UNSW Battlecode dragons game, checked turn for turn
against the official engine.

The official engine (`unswbc_engine.wasm`) is ground truth but costs ~19 µs per
dragon-turn and calls back into Python for every single one. The native
simulator here reimplements the same rules and steps at roughly **1 µs per
dragon-turn on one core**.

```python
import _dragons                                  # built into cpp/
from dragons_env import mapgen
import random

game = _dragons.Game.from_map_text(mapgen.random_map(random.Random(0)).to_text())
while not game.finished() and game.round < 500:
    game.begin_round()
    index = game.next_turn()
    while index is not None:                     # includes children born this round
        dragon = game.dragons()[index]
        game.take_turn(index, _dragons.Action.move(dragon["facing"]))
        index = game.next_turn(index)
    game.end_round()
print(game.result(), game.team_score(0), game.team_score(1))
```

This is the **environment only**: the rules, a driver for the official engine to
check them against, and map generation. Observation encoding, action spaces,
policies and training belong with the agent and are deliberately not here.

## How the rules were obtained

Not by guessing. `wasm-decompile --enable-all` lifts the engine to readable
pseudocode, and the binary keeps its C++ name section, so `Step`, `Move`,
`Split`, `CastSonar`, `Kill`, `PearlTick` and `ResultAfterRound` were read
directly. `cpp/dragons/game.cpp` transcribes them, and the comments say where a
rule is surprising.

A few worth knowing:

* the winner is the **longest single living dragon**, total length only breaks a
  tie -- splitting 100 into 50+50 halves your score;
* head-to-head kills **both** dragons whatever their lengths, so a 2-segment
  child can trade itself for a 100-segment rival;
* a dying dragon drops a pearl on **every second segment from the head**;
* a sprint re-checks affordability **before each step**, so a pearl eaten
  part-way pays for another one;
* dragons act **in id order within a round**, each seeing what earlier ones
  left, and a split child takes its turn in the round it is born;
* pearls tick at the **start** of a round, so one planted this round is edible
  this round, and never spawn under a living dragon.

## What is verified, and what is not

`tests/test_cpp_sim.py` drives both engines through identical action sequences
and compares the complete visible state -- every visible pearl and dragon
segment, lengths, facings, sonar inboxes, death causes, and winner -- before
every turn. Boards use the documented minimum size of 10x10.

**Verified in CI**: 32 differential matches across four pearl regimes, plus
targeted regressions for split-and-sonar, same-tile horizontal and vertical
portals, symmetric pearl countdowns, split-child turn order, and map bounds.
Movement, sprints and their per-step cost, splits, sonar, collisions, all five
death causes, corpse pearls, pearl spawning, scoring and the 500-round horizon
are covered.

This caught five real bugs during development: the result being decided per
round rather than per turn, split children acting in the round they are born,
an off-by-one at the 499 horizon, pearl ticking at the wrong end of the round,
and a split child built back to front.

**Not verified**, and worth closing before trusting this beyond its envelope:

1. **Portals are not fuzzed.** Portal traversal and overlapping portal-owner
   cases have hand-written tests only.
2. **Only visible state is compared.** The official protocol does not expose
   global state outside a dragon's 7x7 window.
3. **Only two dragons.** Unit limits and crowded multi-dragon rounds are
   untested.

## Layout

```
cpp/dragons/    the rules
cpp/bindings.cpp
dragons_env/    python: wasm engine driver, wire protocol, map generation
tests/          differential tests against the real engine
```

## Build

```sh
uv venv .venv && uv pip install --python .venv/bin/python numpy unswbc pybind11 pytest
PYTHON=.venv/bin/python ./tools/build_native.sh
PYTHONPATH=.:cpp .venv/bin/python -m pytest tests -q
```
