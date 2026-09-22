"""Write `.map` files, including randomised ones.

The engine seeds its RNG from a fixed constant, so every match on a given map
has identical pearl timers. Variety has to come from generating maps.

Edge indexing (verified against the engine): for a `w` x `h` board,

    north edge of (x, y) -> y * 2 * (w + 1) + x
    west  edge of (x, y) -> y * 2 * (w + 1) + (w + 1) + x

Row `y = h` and column `x = w` mirror row/column 0; the engine checks that a
mirrored pair agrees. Portals must join two edges of the same orientation.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

MIN_DIM = 7          # the engine refuses anything smaller
DEFAULT_UNIT_LIMIT = 64

OFFSET = {"N": (0, -1), "E": (1, 0), "S": (0, 1), "W": (-1, 0)}
OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}


def north(x: int, y: int, w: int) -> int:
    return y * 2 * (w + 1) + x


def west(x: int, y: int, w: int) -> int:
    return y * 2 * (w + 1) + (w + 1) + x


def edge_between(x: int, y: int, direction: str, w: int, h: int) -> int:
    """Index of the edge you cross stepping `direction` out of (x, y)."""
    if direction == "N":
        return north(x, y, w)
    if direction == "S":
        return north(x, (y + 1) % h, w)
    if direction == "W":
        return west(x, y, w)
    return west((x + 1) % w, y, w)


@dataclass
class MapSpec:
    width: int
    height: int
    dragons: list[tuple[int, list[tuple[int, int]]]]     # (team 0/1, segments head first)
    kelp: list[int] = field(default_factory=list)        # edge indices
    portals: list[tuple[int, int]] = field(default_factory=list)   # (edge index, portal id)
    pearl_gap: tuple[int, int] = (8, 20)                 # per tile (min, max) respawn delay
    tile_gaps: dict[tuple[int, int], tuple[int, int]] | None = None
    name: str = "Generated"
    unit_limit: int | None = None

    def to_text(self) -> str:
        w, h = self.width, self.height
        out = [f"MAP {w} {h}", f"MAP_NAME {self.name}"]
        if self.unit_limit is not None:
            out.append(f"UNIT_LIMIT {self.unit_limit}")
        tiles = []
        for y in range(h):
            for x in range(w):
                lo, hi = (self.tile_gaps or {}).get((x, y), self.pearl_gap)
                tiles.append(f"TILE {x} {y} {lo} {hi}")
        out.append(f"TILE_COUNT {len(tiles)}")
        out += tiles
        edges = [f"EDGE {i} 1 -1" for i in self.kelp]
        edges += [f"EDGE {i} 2 {pid}" for i, pid in self.portals]
        out.append(f"EDGE_COUNT {len(edges)}")
        out += edges
        out.append(f"DRAGON_COUNT {len(self.dragons)}")
        for team, segs in self.dragons:
            flat = " ".join(f"{x} {y}" for x, y in segs)
            out.append(f"DRAGON {team} {len(segs)} {flat}")
        return "\n".join(out) + "\n"

    def to_bytes(self) -> bytes:
        return self.to_text().encode()


def snake(x: int, y: int, length: int, facing: str, w: int, h: int) -> list[tuple[int, int]]:
    """Segments for a dragon whose head is at (x, y) looking `facing`."""
    dx, dy = OFFSET[OPPOSITE[facing]]
    return [((x + dx * i) % w, (y + dy * i) % h) for i in range(length)]


def open_board(width: int = 15, height: int = 15, length: int = 3,
               pearl_gap: tuple[int, int] = (8, 20), name: str = "Open") -> MapSpec:
    """Two dragons facing each other on an empty torus."""
    y = height // 2
    return MapSpec(width, height, name=name, pearl_gap=pearl_gap, dragons=[
        (0, snake(width // 4, y, length, "E", width, height)),
        (1, snake(3 * width // 4, y, length, "W", width, height)),
    ])


def random_map(rng: random.Random, *, min_size: int = 11, max_size: int = 24,
               dragons_per_team: int = 1, length: int = 3,
               kelp_density: float = 0.06, portal_pairs: int = 0,
               pearl_gap_choices: tuple[tuple[int, int], ...] = ((4, 12), (8, 20), (15, 40)),
               ) -> MapSpec:
    """A randomised board. Spawns are placed symmetrically and kept apart."""
    w = rng.randrange(max(min_size, MIN_DIM), max_size + 1)
    h = rng.randrange(max(min_size, MIN_DIM), max_size + 1)

    occupied: set[tuple[int, int]] = set()
    dragons: list[tuple[int, list[tuple[int, int]]]] = []
    for i in range(dragons_per_team):
        for attempt in range(200):
            x = rng.randrange(w)
            y = rng.randrange(h)
            facing = rng.choice("NESW")
            a = snake(x, y, length, facing, w, h)
            b = snake((x + w // 2) % w, (y + h // 2) % h, length, OPPOSITE[facing], w, h)
            if occupied.isdisjoint(a) and occupied.isdisjoint(b) and set(a).isdisjoint(b):
                occupied.update(a)
                occupied.update(b)
                dragons.append((0, a))
                dragons.append((1, b))
                break
        else:
            raise RuntimeError("could not place dragons; board too small or too crowded")

    # kelp: never right next to a spawning head, so nobody dies on round 0
    forbidden = {(x, y) for _, segs in dragons for x, y in segs}
    kelp: set[int] = set()
    for y in range(h):
        for x in range(w):
            if (x, y) in forbidden:
                continue
            for direction in ("N", "W"):
                if rng.random() < kelp_density:
                    kelp.add(edge_between(x, y, direction, w, h))

    portals: list[tuple[int, int]] = []
    used: set[int] = set()          # an edge may belong to at most one portal
    for pid in range(portal_pairs):
        horizontal = rng.random() < 0.5
        picked: list[int] = []
        for _ in range(500):
            x, y = rng.randrange(w), rng.randrange(h)
            idx = north(x, y, w) if horizontal else west(x, y, w)
            # row h and column w mirror 0, so keep off them to avoid aliasing
            if idx in kelp or idx in used or idx in picked:
                continue
            picked.append(idx)
            if len(picked) == 2:
                break
        if len(picked) < 2:
            break
        used.update(picked)
        portals += [(picked[0], pid), (picked[1], pid)]

    return MapSpec(w, h, dragons, sorted(kelp), portals,
                   pearl_gap=rng.choice(pearl_gap_choices), name=f"R{w}x{h}")
