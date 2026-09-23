// A faithful reimplementation of the UNSW Battlecode dragons engine.
//
// Every rule here was read out of unswbc_engine.wasm (see GAME_ANALYSIS.md,
// appendix) rather than inferred, and is checked against the real engine by the
// differential fuzzer in tests/test_cpp_sim.py. Where the engine does something
// surprising the comment says so; do not "clean it up".
#pragma once

#include <array>
#include <cstdint>
#include <deque>
#include <optional>
#include <random>
#include <string>
#include <vector>

namespace dragons {

enum class Dir : uint8_t { N = 0, E = 1, S = 2, W = 3 };

inline constexpr std::array<int, 4> kDx{0, 1, 0, -1};
inline constexpr std::array<int, 4> kDy{-1, 0, 1, 0};

// Death reasons, using the engine's own byte codes.
enum class Death : char {
  Wall = 'W',          // crossed kelp
  Self = 'S',          // ran into its own body
  Other = 'O',         // ran into another dragon's body
  HeadToHead = 'H',    // met another dragon's head; both die
  NoAction = 'A',      // illegal or missing action
};

struct Point {
  int16_t x = 0, y = 0;
  friend bool operator==(Point a, Point b) { return a.x == b.x && a.y == b.y; }
};

enum class EdgeKind : uint8_t { Empty, Kelp, Portal };

struct Edge {
  EdgeKind kind = EdgeKind::Empty;
  // For a portal, the tile owning the partner edge, and the partner's axis.
  // A vertical portal is the west edge of `partner`; a horizontal one is its
  // north edge.
  Point partner{};
  bool partner_vertical = false;
};

struct Tile {
  bool pearl = false;
  bool spawns = false;      // false when the map gives this tile no gap range
  int32_t countdown = 0;    // rounds until the next spawn attempt
  int32_t gap_min = 0, gap_max = 0;
};

struct Dragon {
  int32_t id = 0;
  uint8_t team = 0;               // 0 = A, 1 = B
  bool alive = true;
  Dir facing = Dir::N;
  std::deque<Point> segments;     // head at the front
  std::vector<uint64_t> inbox;    // sonar delivered since this dragon's last turn

  struct SonarEchoes {
    int32_t kelp = 0;
    int32_t ally = 0;
    int32_t ally_head = 0;
    int32_t enemy = 0;
    int32_t enemy_head = 0;
  } echoes;

  int length() const { return static_cast<int>(segments.size()); }
  const Point& head() const { return segments.front(); }
};

struct Action {
  enum class Kind : uint8_t { Move, Split, None };
  Kind kind = Kind::None;
  std::vector<Dir> dirs;        // for Move; length 1 is a plain step
  int split_size = 0;           // for Split
  // The legacy sonar form follows the dragon's facing after its action.
  bool sonar = false;
  uint32_t payload = 0;
  // Protocol 3 allows one independent 64-bit message in each N/E/S/W ray.
  std::array<std::optional<uint64_t>, 4> sonars{};
};

struct DeathEvent {
  int32_t dragon_id;
  int32_t round;
  Death reason;
};

struct Score {
  int32_t max_length = 0;       // longest living dragon -- the primary score
  int32_t total_length = 0;     // tiebreak
  int32_t dragons = 0;
};

enum class Outcome : uint8_t { Running, TeamA, TeamB, Draw };

class Game {
 public:
  static constexpr int kMaxRounds = 500;
  static constexpr int kMinSize = 2;         // a dragon may not shrink below this
  static constexpr int kVisionRadius = 3;
  static constexpr int kMinMapSize = 10;
  static constexpr int kMaxMapSize = 64;
  static constexpr uint32_t kOfficialPearlSeed = 1592614637u;

  // Parses the toolkit's .map format, the same text the real engine reads.
  static Game FromMapText(const std::string& text,
                          uint64_t seed = kOfficialPearlSeed);

  int width() const { return width_; }
  int height() const { return height_; }
  int round() const { return round_; }
  int unit_limit() const { return unit_limit_; }
  const std::vector<Dragon>& dragons() const { return dragons_; }
  const std::vector<Tile>& tiles() const { return tiles_; }
  const std::vector<DeathEvent>& deaths() const { return deaths_; }

  const Tile& TileAt(Point p) const { return tiles_[Index(p)]; }
  Tile& TileAt(Point p) { return tiles_[Index(p)]; }

  // Snapshot of the dragons currently eligible to act. A split child is
  // appended after this snapshot, so round drivers must iterate dragons()
  // dynamically (see README) rather than retaining this result for the whole
  // round.
  std::vector<int> TurnOrder() const;
  std::optional<int> NextTurn(int after_index) const;
  // A round is: BeginRound (pearls count down and may spawn), then every
  // dragon that is alive when its turn comes, then EndRound. The engine ticks
  // pearls *before* the turns -- a tile with gap (5,5) already reads 4 on the
  // first observation -- so a pearl planted this round is edible this round.
  void BeginRound();
  void TakeTurn(int dragon_index, const Action& action);
  void EndRound();

  Score TeamScore(uint8_t team) const;
  Outcome Result(bool forced = false) const;
  bool Finished() const { return Result() != Outcome::Running; }

  // Rules, exposed for testing. These mirror the engine's own functions.
  std::optional<Point> TileAfterStep(Point from, Dir dir) const;
  Dragon* AliveDragonOccupying(Point p);
  const Dragon* AliveDragonOccupying(Point p) const;
  // Index of the dragon standing on a tile, or -1. Kept incrementally, since
  // scanning every dragon's segments per tile dominates observation encoding.
  int32_t OccupantIndex(Point p) const { return occupant_[Index(p)]; }
  // The facing the engine reports for whatever segment stands here: a head
  // points where it is heading, a body segment at the segment ahead of it.
  Dir TileFacing(Point p) const { return tile_facing_[Index(p)]; }
  int AliveUnitCount(uint8_t team) const;
  void Kill(Dragon& dragon, Death reason);
  bool Step(Dragon& dragon, Dir dir, bool pay);
  void Move(Dragon& dragon, const std::vector<Dir>& dirs);
  void Split(Dragon& dragon, int size);
  void CastSonar(Dragon& dragon, Dir direction, uint64_t message);
  void PearlTick();

 private:
  size_t Index(Point p) const { return static_cast<size_t>(p.y) * width_ + p.x; }
  void Occupy(Point p, int32_t dragon_index, Dir facing);
  void Vacate(Point p);
  void RefreshFacings(const Dragon& dragon);
  void InitialisePearlCountdowns();
  int32_t DrawPearlGap(int32_t minimum, int32_t maximum);
  int32_t IndexOfDragon(const Dragon& dragon) const;
  Point Wrap(int x, int y) const;
  const Edge& EdgeOnTileSide(Point p, Dir dir) const;

  int width_ = 0, height_ = 0;
  int round_ = 0;
  int unit_limit_ = 64;
  int32_t next_id_ = 0;
  std::vector<Tile> tiles_;
  // Index of the tile sharing each tile's pearl countdown. Self when the map
  // has no symmetry or the tile lies on the symmetry axis.
  std::vector<int32_t> pearl_mirror_;
  std::vector<Edge> h_edges_;   // north edge of (x, y)
  std::vector<Edge> v_edges_;   // west edge of (x, y)
  std::vector<Dragon> dragons_;
  std::vector<int32_t> occupant_;
  std::vector<Dir> tile_facing_;
  std::vector<DeathEvent> deaths_;
  std::mt19937 rng_;
};

}  // namespace dragons
