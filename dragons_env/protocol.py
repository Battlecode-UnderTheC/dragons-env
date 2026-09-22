"""The judge's wire protocol, parsed exactly the way `helper.py` parses it.

A turn block looks like:

    ROUND 12
    DIR E
    LENGTH 6
    UNIT_COUNT 2
    NUM_MSGS 1
    <one message per line, uint32>
    <49 lines "x y hasPearl pearlIn", row major from the window's top left>
    DRAGON_BODIES 7
    <one line per part: "team dragonId x y facing isHead">
    <8 rows of 7 horizontal edge tokens, then 7 rows of 8 vertical ones>

Edge tokens are "." (empty), "w" (kelp) or a portal id.

Parsing is on the hot path of every rollout, so the tile and edge blocks are
converted in bulk and the per-tile edge/occupancy views are derived lazily with
numpy rather than in Python loops.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

VISION_RADIUS = 3
VISION = 2 * VISION_RADIUS + 1
TILES = VISION * VISION
CENTER = TILES // 2
MAX_ROUNDS = 500
INITIAL_LENGTH = 3
MIN_SIZE = 2

DIRS = ("N", "E", "S", "W")
DIR_INDEX = {d: i for i, d in enumerate(DIRS)}
OFFSET = {"N": (0, -1), "E": (1, 0), "S": (0, 1), "W": (-1, 0)}
OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}
LEFT = {d: DIRS[(i + 3) % 4] for i, d in enumerate(DIRS)}
RIGHT = {d: DIRS[(i + 1) % 4] for i, d in enumerate(DIRS)}

KELP = "w"
EMPTY = "."

# where each window tile's four edges live in the flat edge rows
_I = np.arange(TILES)
_H_NORTH = _I
_H_SOUTH = _I + VISION
_V_WEST = _I + _I // VISION
_V_EAST = _V_WEST + 1
# indexed by direction order N, E, S, W
_EDGE_ROW = (0, 1, 0, 1)                      # 0 = horizontal rows, 1 = vertical
_EDGE_IDX = (_H_NORTH, _V_EAST, _H_SOUTH, _V_WEST)
_ROW = _I // VISION
_COL = _I % VISION


@dataclass(frozen=True)
class SpawnInfo:
    dragon_id: int
    team: str
    width: int
    height: int
    unit_limit: int


@dataclass
class Part:
    __slots__ = ("team", "dragon_id", "x", "y", "facing", "is_head")
    team: str
    dragon_id: int
    x: int
    y: int
    facing: str
    is_head: bool


@dataclass
class TurnBlock:
    """One dragon's view of one of its turns. Positions are absolute board tiles."""
    round: int
    facing: str
    length: int
    unit_count: int
    messages: list[int]
    pearl: np.ndarray             # [49] int8, 1 where a pearl sits
    pearl_time: np.ndarray        # [49] int32, -1 where the tile never spawns
    parts: list[Part]
    h_edges: np.ndarray           # [56] tokens, 8 rows of 7
    v_edges: np.ndarray           # [56] tokens, 7 rows of 8
    head_x: int = 0
    head_y: int = 0
    width: int = 0                # board size, needed to wrap window coordinates
    height: int = 0
    _xs: np.ndarray | None = field(default=None, repr=False)
    _ys: np.ndarray | None = field(default=None, repr=False)
    _kelp: np.ndarray | None = field(default=None, repr=False)
    _portal: np.ndarray | None = field(default=None, repr=False)
    _occupied: np.ndarray | None = field(default=None, repr=False)
    _lookup: dict | None = field(default=None, repr=False)

    @property
    def head(self) -> tuple[int, int]:
        return self.head_x, self.head_y

    @property
    def xs(self) -> np.ndarray:
        """Board x of each window tile, row major. Derived when the board size
        is known, otherwise taken from what the engine printed."""
        if self._xs is None:
            self._xs = (self.head_x - VISION_RADIUS + _COL) % self.width
        return self._xs

    @property
    def ys(self) -> np.ndarray:
        if self._ys is None:
            self._ys = (self.head_y - VISION_RADIUS + _ROW) % self.height
        return self._ys

    def window_index(self, x: int, y: int) -> int | None:
        """Window tile holding board position (x, y), or None if out of view."""
        if self.width:
            col = (x - self.head_x + VISION_RADIUS) % self.width
            row = (y - self.head_y + VISION_RADIUS) % self.height
            if col >= VISION or row >= VISION:
                return None
            return row * VISION + col
        if self._lookup is None:
            self._lookup = {(int(self.xs[i]), int(self.ys[i])): i for i in range(TILES)}
        return self._lookup.get((x, y))

    def edge(self, i: int, direction: str) -> str:
        """Edge token on the given side of window tile `i`."""
        d = DIR_INDEX[direction]
        rows = self.v_edges if _EDGE_ROW[d] else self.h_edges
        return str(rows[_EDGE_IDX[d][i]])

    @property
    def kelp(self) -> np.ndarray:
        """[49, 4] bool, in N E S W order: is that side of the tile impassable."""
        if self._kelp is None:
            self._derive_edges()
        return self._kelp

    @property
    def portal(self) -> np.ndarray:
        """[49, 4] bool: is that side of the tile a portal."""
        if self._portal is None:
            self._derive_edges()
        return self._portal

    @property
    def occupied(self) -> np.ndarray:
        """[49] bool: does any dragon part stand on that window tile."""
        if self._occupied is None:
            occ = np.zeros(TILES, dtype=bool)
            for part in self.parts:
                i = self.window_index(part.x, part.y)
                if i is not None:
                    occ[i] = True
            self._occupied = occ
        return self._occupied

    def _derive_edges(self) -> None:
        kelp = np.empty((TILES, 4), dtype=bool)
        portal = np.empty((TILES, 4), dtype=bool)
        for d in range(4):
            rows = self.v_edges if _EDGE_ROW[d] else self.h_edges
            tokens = rows[_EDGE_IDX[d]]
            is_kelp = tokens == KELP
            kelp[:, d] = is_kelp
            portal[:, d] = ~is_kelp & (tokens != EMPTY)
        self._kelp, self._portal = kelp, portal


def parse_spawn(block: str) -> SpawnInfo:
    fields = {}
    for line in block.splitlines():
        if line:
            key, *rest = line.split()
            fields[key] = rest
    return SpawnInfo(dragon_id=int(fields["ID"][0]), team=fields["TEAM"][0],
                     width=int(fields["MAP"][0]), height=int(fields["MAP"][1]),
                     unit_limit=int(fields["UNIT_LIMIT"][0]))


def parse_turn(block: str, width: int = 0, height: int = 0) -> TurnBlock:
    """Parse one turn block. `width`/`height` are the board size, which lets the
    window's board coordinates be derived instead of parsed."""
    lines = block.split("\n")
    rnd = int(lines[0].split()[1])
    facing = lines[1].split()[1]
    length = int(lines[2].split()[1])
    units = int(lines[3].split()[1])
    n_msgs = int(lines[4].split()[1])
    at = 5
    messages = [int(lines[at + i]) for i in range(n_msgs)]
    at += n_msgs

    tile_tokens = " ".join(lines[at:at + TILES]).split()
    at += TILES
    # only the pearl columns need converting; x and y follow from the head once
    # the board size is known
    pearl = np.array(list(map(int, tile_tokens[2::4])), dtype=np.int8)
    pearl_time = np.array(list(map(int, tile_tokens[3::4])), dtype=np.int32)
    head_x, head_y = int(tile_tokens[CENTER * 4]), int(tile_tokens[CENTER * 4 + 1])

    n_parts = int(lines[at].split()[1])
    at += 1
    parts = []
    if n_parts:
        tokens = " ".join(lines[at:at + n_parts]).split()
        at += n_parts
        for i in range(0, len(tokens), 6):
            parts.append(Part(tokens[i], int(tokens[i + 1]), int(tokens[i + 2]),
                              int(tokens[i + 3]), tokens[i + 4], tokens[i + 5] == "1"))

    h_edges = np.array(" ".join(lines[at:at + VISION + 1]).split())
    at += VISION + 1
    v_edges = np.array(" ".join(lines[at:at + VISION]).split())
    out = TurnBlock(rnd, facing, length, units, messages, pearl, pearl_time,
                    parts, h_edges, v_edges, head_x, head_y, width, height)
    if not width:
        # board size unknown: fall back to the coordinates the engine printed,
        # since a window that wraps cannot reveal the board size by itself
        out._xs = np.array(list(map(int, tile_tokens[0::4])), dtype=np.int32)
        out._ys = np.array(list(map(int, tile_tokens[1::4])), dtype=np.int32)
    return out
