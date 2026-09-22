# The dragons game

A reference for the rules as the engine actually implements them. Everything
here was read out of `unswbc_engine.wasm` and checked against it; where a rule
is easy to assume wrongly, the wrong assumption is named.

## Board

The board is a **torus**: x and y both wrap, so there is no edge to back into.
Sizes run from 7x7, the smallest the engine accepts, up to 64x64.

Every tile holds at most one **pearl** and a countdown to its next spawn
attempt. Between tiles are **edges**, each one of:

| edge | effect |
|---|---|
| empty | walk through freely |
| **kelp** | impassable, and it blocks sonar |
| **portal** | paired with exactly one other edge of the same orientation |

Kelp blocks movement and sonar but **not sight** — the 7x7 window is a plain
rectangle with no line-of-sight test. You can see through a wall; you just
cannot walk through it.

## Dragons

A dragon is a snake of segments, head first, belonging to team A or B. Maps
start each side with one or more, typically length 3. A team may have at most
`UNIT_LIMIT` alive at once (64 unless the map says otherwise).

Dragons never respawn. Dead is dead.

## A round

The match is **500 rounds**, numbered 0 to 499. Within a round, dragons act
**one at a time in id order**, and each sees the board *after* the dragons
before it have moved. A dragon created by a split takes the next free id, so it
acts later in **the round it is born**.

The result is decided **after a complete round**, never in the middle of one.
A dragon dying does not end the round; the dragons after it still take a turn.

Pearls tick at the **start** of a round, before any dragon moves, so a pearl
planted this round can be eaten this round.

## What a dragon sees

At spawn: its own id, its team, the board size, the unit limit.

Each turn: the round number, its own heading, its own length, how many dragons
its team has alive, any sonar that reached it since its last turn, a **7x7
window centred on its head** — per tile the absolute `x y`, whether a pearl is
there, and the countdown — every dragon segment inside that window (team, id,
position, facing, whether it is a head), and that window's edges.

It does **not** see: the score, the board beyond the window, where its team
mates are, or how much time is left beyond the round number. Note that each
tile carries its **absolute coordinates**, so the window is anchored on the
board rather than floating.

A body segment's reported facing points **towards the head**, not where the
dragon is going; only the head's facing is its heading.

## Actions

One action per turn. `MOVE` and `SPLIT` are actions and **only the last one
sent is applied**. `SONAR`, `LOG`, `DOT`, `LINE` and `INDICATOR` are not
actions and do not replace a move.

**A turn with no legal action is death.** Sending nothing, a malformed or
mis-cased command, a sprint you cannot pay for, or an illegal split all kill
the dragon.

### MOVE

`MOVE N`, or `MOVE ENE` to sprint. Each direction is one step, taken in order.

* k steps cost **k-1 segments**;
* affordability is re-checked **before every step**, requiring length > 2 at
  that moment — so a pearl eaten part-way through a sprint pays for another
  step;
* every intermediate tile is checked, so a sprint dies on the first blocked
  step rather than only at its destination;
* pearls along the whole path are eaten.

### SPLIT

`SPLIT n` detaches the last `n` segments as a new dragon. It requires
`n >= 2`, a remainder of at least 2, and the team below its unit limit;
otherwise the parent dies of no valid action.

The child's head is the parent's **old tail tip**, so it faces back the way the
parent came. It gets a new id and acts later in the same round. **The parent
does not move on the turn it splits** — which also makes splitting the only way
to survive a turn where no move is legal.

### SONAR

`SONAR v` sends an unsigned 32-bit value along the head's facing **after** the
action resolves. One per turn; the last one sent wins.

The ray is instant and travels until something stops it: it **wraps around the
torus**, passes **through portals**, is **blocked by kelp**, and is delivered
to the **first dragon segment it meets** — ally, enemy, or the sender's own
body if the ray comes all the way round. Its range is `width + height` steps,
which always covers at least one full wrap.

The receiver reads it on **its next turn**: the same round if it acts later in
the id order, otherwise the following round.

## Dying

| reason | cause |
|---|---|
| `W` | crossed a kelp edge |
| `S` | moved into its own body — including reversing, and including its own tail, which has not vacated yet |
| `O` | moved into another dragon's body, ally or enemy |
| `H` | moved onto another dragon's **head**: both die, whatever their lengths |
| `A` | no valid action |

The checks happen in that order: kelp, then own body, then other dragons.

Two consequences worth dwelling on. There is **no free reverse** — turning
back is a self-collision. And **head-to-head kills both regardless of size**,
so a 2-segment dragon can trade itself for a 100-segment one.

A dying dragon **drops a pearl on every second segment from its head** —
indices 0, 2, 4 and so on, written unconditionally. Roughly half its length
returns to the board as food, so a kill feeds the killer and dying feeds the
opponent.

## Pearls

Eating one adds a segment: the head advances and the tail **stays put**, which
is the growth.

Each tile counts down to its next spawn attempt, the delay drawn from the
range the map gives it (`0 0` means the tile never spawns). At zero a pearl
appears **only if** the tile has no pearl already and **no living dragon is
standing on it**; the countdown is then redrawn.

The engine seeds its pearl RNG from a **fixed constant**, so a given map plays
out with identical pearl timings every single time. There is no seed to pass;
varying the map's gap ranges is what changes the timings.

## Portals

Crossing a portal edge teleports the **head** to the tile on the far side of
the partner edge, keeping its direction. The body follows over the next turns,
so the dragon is briefly in two places. Portals always join two edges of the
same orientation.

Vision does not follow a portal: the window shows the tile that is
geometrically adjacent, which is not where a step would land.

## Winning

At the end of a round:

1. a team with **no living dragons** loses; both empty is a draw;
2. otherwise, once round 499 is finished, compare the **longest single living
   dragon**. Bigger wins;
3. if those tie, compare **total living length**;
4. if those tie too, it is a draw.

The number of dragons is never a tiebreak.

This ordering is the whole strategic shape of the game. One dragon of 10 beats
two of 7 — total length 10 against 14 — so **splitting halves the number that
decides the match**. Combined with head-to-head killing both dragons whatever
their sizes, a cheap child traded for the opponent's longest dragon is a real
play.

## Constants

| | |
|---|---|
| rounds | 500 (0–499) |
| vision | 7x7, radius 3 |
| starting length | 3 (map may differ) |
| minimum length | 2 |
| default unit limit | 64 |
| sonar range | width + height steps |
| board size | 7x7 to 64x64 |

## Map files

```
MAP <w> <h>
MAP_NAME <text>
SYMMETRY x|y|xy
UNIT_LIMIT <n>
TILE_COUNT <n>
TILE <x> <y> <minGap> <maxGap>     pearl respawn range; 0 0 never spawns
EDGE_COUNT <n>
EDGE <index> <kind> <portalId>     kind 0 empty, 1 kelp, 2 portal
DRAGON_COUNT <n>
DRAGON <team> <segments> <x> <y> ...   head first, team 0 or 1
```

Edge indices, for a board of width `w`:

```
north edge of (x, y) = y * 2 * (w + 1) + x
west  edge of (x, y) = y * 2 * (w + 1) + (w + 1) + x
```

Row `y = h` and column `x = w` mirror row and column 0; the engine checks that
a mirrored pair agrees. Portals must join two edges of the same orientation.

## Running a bot

Each dragon is its own process, forked from a pre-warmed interpreter, so a
dragon's memory is private and a split child begins with none of its parent's.

The judge gives each turn **100M CPU points** and 48 MB, with a 10 second wall
limit and 10 KB of output. A submission is at most 4 MB zipped and contains
only the files its `bot.toml` lists. numpy is available and pre-imported, so
importing it is nearly free; building large arrays at runtime is not, and
weights are better embedded and read with `frombuffer`.
