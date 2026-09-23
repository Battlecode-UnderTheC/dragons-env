#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "dragons/game.hpp"

namespace py = pybind11;
using namespace dragons;

namespace {

void SetSonars(Action& action, const py::dict& sonars) {
  for (const auto& item : sonars) {
    const std::string direction = py::cast<std::string>(item.first);
    if (direction.size() != 1) throw std::invalid_argument("bad sonar direction");
    const char* found = std::strchr("NESW", direction[0]);
    if (!found) throw std::invalid_argument("bad sonar direction");
    action.sonars[static_cast<size_t>(found - "NESW")] =
        py::cast<uint64_t>(item.second);
  }
}

py::dict DragonToDict(const Dragon& dragon) {
  py::list segments;
  for (const Point& p : dragon.segments) segments.append(py::make_tuple(p.x, p.y));
  py::dict out;
  out["id"] = dragon.id;
  out["team"] = dragon.team;
  out["alive"] = dragon.alive;
  out["facing"] = std::string(1, "NESW"[static_cast<int>(dragon.facing)]);
  out["segments"] = segments;
  out["length"] = dragon.length();
  out["inbox"] = dragon.inbox;
  py::dict echoes;
  echoes["kelp"] = dragon.echoes.kelp;
  echoes["ally"] = dragon.echoes.ally;
  echoes["ally_head"] = dragon.echoes.ally_head;
  echoes["enemy"] = dragon.echoes.enemy;
  echoes["enemy_head"] = dragon.echoes.enemy_head;
  out["echoes"] = echoes;
  return out;
}

}  // namespace

PYBIND11_MODULE(_dragons, m) {
  m.doc() = "Native reimplementation of the UNSW Battlecode dragons engine";

  py::class_<Action>(m, "Action")
      .def(py::init<>())
      .def_static("move", [](const std::string& dirs, bool sonar, uint32_t payload,
                             const py::dict& sonars) {
        Action action;
        action.kind = Action::Kind::Move;
        for (char c : dirs) {
          const char* found = std::strchr("NESW", c);
          if (!found) throw std::invalid_argument("bad direction");
          action.dirs.push_back(static_cast<Dir>(found - "NESW"));
        }
        action.sonar = sonar;
        action.payload = payload;
        SetSonars(action, sonars);
        return action;
      }, py::arg("dirs"), py::arg("sonar") = false, py::arg("payload") = 0,
         py::arg("sonars") = py::dict())
      .def_static("split", [](int size, bool sonar, uint32_t payload,
                              const py::dict& sonars) {
        Action action;
        action.kind = Action::Kind::Split;
        action.split_size = size;
        action.sonar = sonar;
        action.payload = payload;
        SetSonars(action, sonars);
        return action;
      }, py::arg("size"), py::arg("sonar") = false, py::arg("payload") = 0,
         py::arg("sonars") = py::dict())
      .def_static("none", [] { return Action{}; });

  py::class_<Game>(m, "Game")
      .def_static("from_map_text", &Game::FromMapText,
                  py::arg("text"), py::arg("seed") = Game::kOfficialPearlSeed)
      .def_property_readonly("width", &Game::width)
      .def_property_readonly("height", &Game::height)
      .def_property_readonly("round", &Game::round)
      .def("turn_order", &Game::TurnOrder)
      .def("next_turn", &Game::NextTurn, py::arg("after_index") = -1)
      .def("begin_round", &Game::BeginRound)
      .def("take_turn", &Game::TakeTurn)
      .def("end_round", &Game::EndRound)
      .def("finished", &Game::Finished)
      .def("result", [](const Game& game) {
        switch (game.Result()) {
          case Outcome::TeamA: return std::string("A");
          case Outcome::TeamB: return std::string("B");
          case Outcome::Draw: return std::string("draw");
          default: return std::string("running");
        }
      })
      .def("team_score", [](const Game& game, int team) {
        const Score score = game.TeamScore(static_cast<uint8_t>(team));
        return py::make_tuple(score.max_length, score.total_length, score.dragons);
      })
      .def("dragons", [](const Game& game) {
        py::list out;
        for (const Dragon& dragon : game.dragons()) out.append(DragonToDict(dragon));
        return out;
      })
      .def("pearls", [](const Game& game) {
        py::list out;
        for (int y = 0; y < game.height(); ++y) {
          for (int x = 0; x < game.width(); ++x) {
            if (game.TileAt(Point{static_cast<int16_t>(x), static_cast<int16_t>(y)}).pearl) {
              out.append(py::make_tuple(x, y));
            }
          }
        }
        return out;
      })
      .def("pearl_countdowns", [](const Game& game) {
        py::list out;
        for (const Tile& tile : game.tiles()) out.append(tile.countdown);
        return out;
      })
      .def("deaths", [](const Game& game) {
        py::list out;
        for (const DeathEvent& death : game.deaths()) {
          out.append(py::make_tuple(death.dragon_id, death.round,
                                    std::string(1, static_cast<char>(death.reason))));
        }
        return out;
      });
}
