#include "dragons/game.hpp"

#include <algorithm>
#include <sstream>
#include <stdexcept>

namespace dragons {
namespace {

int Mod(int value, int modulus) {
  const int r = value % modulus;
  return r < 0 ? r + modulus : r;
}

}  // namespace

Point Game::Wrap(int x, int y) const {
  return Point{static_cast<int16_t>(Mod(x, width_)),
               static_cast<int16_t>(Mod(y, height_))};
}

const Edge& Game::EdgeOnTileSide(Point p, Dir dir) const {
  switch (dir) {
    case Dir::N: return h_edges_[Index(p)];
    case Dir::S: return h_edges_[Index(Wrap(p.x, p.y + 1))];
    case Dir::W: return v_edges_[Index(p)];
    case Dir::E: return v_edges_[Index(Wrap(p.x + 1, p.y))];
  }
  return h_edges_[Index(p)];
}

// Mirrors the engine's TileAfterStep: kelp blocks, a portal jumps to its
// partner keeping the direction of travel, anything else steps and wraps.
std::optional<Point> Game::TileAfterStep(Point from, Dir dir) const {
  const Edge& edge = EdgeOnTileSide(from, dir);
  if (edge.kind == EdgeKind::Kelp) return std::nullopt;
  if (edge.kind == EdgeKind::Portal) {
    int x = edge.partner.x;
    int y = edge.partner.y;
    // The partner edge is the west (or north) side of `partner`, so entering it
    // from the negative side lands on `partner` itself and from the positive
    // side lands on the tile before it.
    if (edge.partner_vertical) {
      if (dir != Dir::E) x -= 1;
    } else {
      if (dir != Dir::S) y -= 1;
    }
    return Wrap(x, y);
  }
  return Wrap(from.x + kDx[static_cast<int>(dir)],
              from.y + kDy[static_cast<int>(dir)]);
}

void Game::Occupy(Point p, int32_t dragon_index, Dir facing) {
  occupant_[Index(p)] = dragon_index;
  tile_facing_[Index(p)] = facing;
}

void Game::Vacate(Point p) { occupant_[Index(p)] = -1; }

int32_t Game::IndexOfDragon(const Dragon& dragon) const {
  return static_cast<int32_t>(&dragon - dragons_.data());
}

// Recomputes the per-tile facing of a whole dragon. Only needed after a split,
// where the detached half reverses direction; ordinary steps update the two
// tiles they touch.
void Game::RefreshFacings(const Dragon& dragon) {
  const int32_t index = IndexOfDragon(dragon);
  for (size_t i = 0; i < dragon.segments.size(); ++i) {
    Dir facing = dragon.facing;
    if (i > 0) {
      for (int d = 0; d < 4; ++d) {
        const std::optional<Point> step =
            TileAfterStep(dragon.segments[i], static_cast<Dir>(d));
        if (step && *step == dragon.segments[i - 1]) {
          facing = static_cast<Dir>(d);
          break;
        }
      }
    }
    Occupy(dragon.segments[i], index, facing);
  }
}

Dragon* Game::AliveDragonOccupying(Point p) {
  const int32_t index = occupant_[Index(p)];
  if (index < 0) return nullptr;
  Dragon& dragon = dragons_[index];
  return dragon.alive ? &dragon : nullptr;
}

const Dragon* Game::AliveDragonOccupying(Point p) const {
  return const_cast<Game*>(this)->AliveDragonOccupying(p);
}

int Game::AliveUnitCount(uint8_t team) const {
  int count = 0;
  for (const Dragon& dragon : dragons_) {
    if (dragon.alive && dragon.team == team) ++count;
  }
  return count;
}

// Kill: every second segment from the head becomes a pearl, unconditionally.
void Game::Kill(Dragon& dragon, Death reason) {
  if (!dragon.alive) return;
  for (size_t i = 0; i < dragon.segments.size(); i += 2) {
    TileAt(dragon.segments[i]).pearl = true;
  }
  for (const Point& segment : dragon.segments) Vacate(segment);
  dragon.alive = false;
  // dead dragons stay in the list (indices are stable) but nothing reads
  // their body again: release it, or a long match with many splits keeps
  // every corpse until the match ends
  std::deque<Point>().swap(dragon.segments);
  std::vector<uint32_t>().swap(dragon.inbox);
  deaths_.push_back(DeathEvent{dragon.id, round_, reason});
}

// Step, in the engine's order: kelp, then own body, then another dragon (head
// to head kills both), then move, eat and pay.
bool Game::Step(Dragon& dragon, Dir dir, bool pay) {
  dragon.facing = dir;
  const std::optional<Point> destination = TileAfterStep(dragon.head(), dir);
  if (!destination) {
    Kill(dragon, Death::Wall);
    return false;
  }
  for (const Point& segment : dragon.segments) {
    if (segment == *destination) {
      // Note the tail counts: it has not vacated yet, so following it is fatal.
      Kill(dragon, Death::Self);
      return false;
    }
  }
  if (Dragon* other = AliveDragonOccupying(*destination)) {
    if (other->head() == *destination) {
      Kill(*other, Death::HeadToHead);
      Kill(dragon, Death::HeadToHead);
    } else {
      Kill(dragon, Death::Other);
    }
    return false;
  }

  const int32_t index = IndexOfDragon(dragon);
  // The tile being left behind now points at where the head went.
  Occupy(dragon.head(), index, dir);
  dragon.segments.push_front(*destination);
  Occupy(*destination, index, dir);

  Tile& tile = TileAt(*destination);
  if (tile.pearl) {
    tile.pearl = false;          // eating keeps the tail, which is the growth
  } else {
    Vacate(dragon.segments.back());
    dragon.segments.pop_back();
  }
  if (pay) {
    Vacate(dragon.segments.back());
    dragon.segments.pop_back();  // a sprint step costs one segment
  }
  return true;
}

// Move: the first step is free, every later one costs a segment and is only
// allowed while the dragon is longer than the minimum.
void Game::Move(Dragon& dragon, const std::vector<Dir>& dirs) {
  if (dirs.empty()) {
    Kill(dragon, Death::NoAction);
    return;
  }
  if (!Step(dragon, dirs[0], false)) return;
  for (size_t i = 1; i < dirs.size(); ++i) {
    // Re-checked every step, so a pearl eaten part-way pays for another one.
    if (dragon.length() <= kMinSize) {
      Kill(dragon, Death::NoAction);
      return;
    }
    if (!Step(dragon, dirs[i], true)) return;
  }
}

void Game::Split(Dragon& dragon, int size) {
  if (size < kMinSize || size > dragon.length() - kMinSize) {
    Kill(dragon, Death::NoAction);
    return;
  }
  if (AliveUnitCount(dragon.team) >= unit_limit_) {
    Kill(dragon, Death::NoAction);
    return;
  }
  Dragon child;
  child.id = next_id_++;
  child.team = dragon.team;
  child.alive = true;
  // The child is the parent's last `size` segments, reversed: its head is the
  // old tail TIP -- the segment furthest from the parent's head -- so taking
  // from the parent's back and appending keeps that at the child's front.
  for (int i = 0; i < size; ++i) {
    child.segments.push_back(dragon.segments.back());
    dragon.segments.pop_back();
  }
  const Point& head = child.segments.front();
  const Point& neck = child.segments.size() > 1 ? child.segments[1] : head;
  child.facing = Dir::N;
  for (int d = 0; d < 4; ++d) {
    const std::optional<Point> ahead = TileAfterStep(neck, static_cast<Dir>(d));
    if (ahead && *ahead == head) {
      child.facing = static_cast<Dir>(d);
      break;
    }
  }
  dragons_.push_back(std::move(child));
  RefreshFacings(dragons_.back());   // the detached half now faces the other way
  // Splitting replaces the move, so the parent does not step this turn.
}

// CastSonar: a straight ray along the dragon's facing, stopped by kelp, carried
// through portals, delivered to the first living dragon it touches. The range
// limit is width + height steps, which always covers at least one full wrap.
void Game::CastSonar(Dragon& dragon, uint32_t message) {
  Point at = dragon.head();
  const int limit = width_ + height_;
  for (int i = 0; i < limit; ++i) {
    const std::optional<Point> next = TileAfterStep(at, dragon.facing);
    if (!next) return;
    at = *next;
    if (Dragon* hit = AliveDragonOccupying(at)) {
      hit->inbox.push_back(message);
      return;
    }
  }
}

// PearlTick: count every tile down; at zero plant a pearl, but never on a tile
// that already has one or that a living dragon is standing on.
void Game::PearlTick() {
  for (int y = 0; y < height_; ++y) {
    for (int x = 0; x < width_; ++x) {
      Point p{static_cast<int16_t>(x), static_cast<int16_t>(y)};
      Tile& tile = TileAt(p);
      if (!tile.spawns) continue;
      const int32_t before = tile.countdown;
      tile.countdown = before - 1;
      if (before > 1) continue;
      if (!tile.pearl && AliveDragonOccupying(p) == nullptr) {
        tile.pearl = true;
      }
      std::uniform_int_distribution<int32_t> gap(tile.gap_min, tile.gap_max);
      tile.countdown = gap(rng_);
    }
  }
}

std::vector<int> Game::TurnOrder() const {
  std::vector<int> order;
  for (size_t i = 0; i < dragons_.size(); ++i) {
    if (dragons_[i].alive) order.push_back(static_cast<int>(i));
  }
  return order;
}

void Game::TakeTurn(int dragon_index, const Action& action) {
  Dragon& dragon = dragons_[dragon_index];
  if (!dragon.alive) return;
  dragon.inbox.clear();
  switch (action.kind) {
    case Action::Kind::Move: Move(dragon, action.dirs); break;
    case Action::Kind::Split: Split(dragon, action.split_size); break;
    case Action::Kind::None: Kill(dragon, Death::NoAction); break;
  }
  // Sonar is not an action: it goes out after the action, from wherever the
  // dragon ended up, and only if it survived. Split may have grown dragons_,
  // which invalidates `dragon`, so the reference is taken afresh.
  Dragon& after = dragons_[dragon_index];
  if (action.sonar && after.alive) CastSonar(after, action.payload);
}

void Game::BeginRound() { PearlTick(); }

void Game::EndRound() { ++round_; }

Score Game::TeamScore(uint8_t team) const {
  Score score;
  for (const Dragon& dragon : dragons_) {
    if (!dragon.alive || dragon.team != team) continue;
    ++score.dragons;
    score.total_length += dragon.length();
    score.max_length = std::max(score.max_length, dragon.length());
  }
  return score;
}

Outcome Game::Result(bool forced) const {
  const Score a = TeamScore(0);
  const Score b = TeamScore(1);
  if (a.dragons == 0 || b.dragons == 0) {
    if (a.dragons == 0 && b.dragons == 0) return Outcome::Draw;
    return a.dragons > 0 ? Outcome::TeamA : Outcome::TeamB;
  }
  // The engine decides after a round, comparing the round it just finished
  // against 499; EndRound has already advanced the counter past it.
  if (!forced && round_ < kMaxRounds) return Outcome::Running;
  if (a.max_length != b.max_length) {
    return a.max_length > b.max_length ? Outcome::TeamA : Outcome::TeamB;
  }
  if (a.total_length != b.total_length) {
    return a.total_length > b.total_length ? Outcome::TeamA : Outcome::TeamB;
  }
  return Outcome::Draw;
}

Game Game::FromMapText(const std::string& text, uint64_t seed) {
  Game game;
  game.rng_.seed(static_cast<uint32_t>(seed));
  std::istringstream stream(text);
  std::string line;
  std::vector<std::array<int, 3>> raw_edges;   // index, kind, portal id

  while (std::getline(stream, line)) {
    std::istringstream fields(line);
    std::string key;
    fields >> key;
    if (key == "MAP") {
      fields >> game.width_ >> game.height_;
      game.tiles_.assign(static_cast<size_t>(game.width_) * game.height_, Tile{});
      game.h_edges_.assign(game.tiles_.size(), Edge{});
      game.v_edges_.assign(game.tiles_.size(), Edge{});
    } else if (key == "UNIT_LIMIT") {
      fields >> game.unit_limit_;
    } else if (key == "TILE") {
      int x, y, lo, hi;
      fields >> x >> y >> lo >> hi;
      Tile& tile = game.tiles_[static_cast<size_t>(y) * game.width_ + x];
      tile.gap_min = lo;
      tile.gap_max = hi;
      tile.spawns = hi > 0;
      if (tile.spawns) {
        std::uniform_int_distribution<int32_t> gap(lo, hi);
        tile.countdown = gap(game.rng_);
      }
    } else if (key == "EDGE") {
      int index, kind, portal;
      fields >> index >> kind >> portal;
      raw_edges.push_back({index, kind, portal});
    } else if (key == "DRAGON") {
      int team, count;
      fields >> team >> count;
      Dragon dragon;
      dragon.id = game.next_id_++;
      dragon.team = static_cast<uint8_t>(team);
      for (int i = 0; i < count; ++i) {
        int x, y;
        fields >> x >> y;
        dragon.segments.push_back(
            Point{static_cast<int16_t>(x), static_cast<int16_t>(y)});
      }
      const Point& head = dragon.segments.front();
      const Point& neck = dragon.segments[1];
      for (int d = 0; d < 4; ++d) {
        if (game.Wrap(neck.x + kDx[d], neck.y + kDy[d]) == head) {
          dragon.facing = static_cast<Dir>(d);
          break;
        }
      }
      game.dragons_.push_back(std::move(dragon));
    }
  }
  if (game.width_ == 0) throw std::runtime_error("map has no MAP line");
  game.occupant_.assign(game.tiles_.size(), -1);
  game.tile_facing_.assign(game.tiles_.size(), Dir::N);

  // Edge indices: y * 2 * (w + 1) + x is the north edge of (x, y); the same
  // plus (w + 1) is its west edge. Row h and column w mirror row/column 0.
  const int stride = 2 * (game.width_ + 1);
  std::vector<std::pair<int, Point>> portal_slots;   // portal id -> owning tile
  for (const auto& entry : raw_edges) {
    const int index = entry[0];
    const int y = index / stride;
    int offset = index % stride;
    const bool vertical = offset >= game.width_ + 1;
    if (vertical) offset -= game.width_ + 1;
    const Point owner = game.Wrap(offset, y);
    Edge& edge = vertical ? game.v_edges_[game.Index(owner)]
                          : game.h_edges_[game.Index(owner)];
    if (entry[1] == 1) {
      edge.kind = EdgeKind::Kelp;
    } else if (entry[1] == 2) {
      edge.kind = EdgeKind::Portal;
      portal_slots.emplace_back(entry[2], owner);
      // orientation recorded so the partner lookup below knows which side
      edge.partner_vertical = vertical;
    }
  }
  for (size_t i = 0; i < portal_slots.size(); ++i) {
    for (size_t j = i + 1; j < portal_slots.size(); ++j) {
      if (portal_slots[i].first != portal_slots[j].first) continue;
      const Point a = portal_slots[i].second;
      const Point b = portal_slots[j].second;
      Edge& ea = game.v_edges_[game.Index(a)].kind == EdgeKind::Portal
                     ? game.v_edges_[game.Index(a)] : game.h_edges_[game.Index(a)];
      Edge& eb = game.v_edges_[game.Index(b)].kind == EdgeKind::Portal
                     ? game.v_edges_[game.Index(b)] : game.h_edges_[game.Index(b)];
      ea.partner = b;
      eb.partner = a;
      const bool a_vertical = game.v_edges_[game.Index(a)].kind == EdgeKind::Portal;
      ea.partner_vertical = a_vertical;
      eb.partner_vertical = a_vertical;
    }
  }
  for (const Dragon& dragon : game.dragons_) game.RefreshFacings(dragon);
  return game;
}

}  // namespace dragons
