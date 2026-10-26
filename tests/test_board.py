"""Test della mappa e delle regole di piazzamento."""

import pytest

from tm_sim.actions import Action, ActionType
from tm_sim.board import Board, SpaceType, TileType
from tm_sim.game import Game
from tm_sim.state import GameState, Player, Resource


def ids(spaces) -> set[str]:
    return {s.id for s in spaces}


# --- Forma della mappa -----------------------------------------------------------

def test_tharsis_shape():
    board = Board()
    assert len(board.mars_spaces()) == 61
    assert len(board.spaces) == 61 + 2                  # + Ganymede e Phobos
    assert [len(row) for row in board.rows()] == [5, 6, 7, 8, 9, 8, 7, 6, 5]
    assert sum(s.type is SpaceType.OCEAN for s in board.spaces.values()) == 12
    assert sorted(s.id for s in board.spaces.values() if s.volcanic) == ["2-2", "3-1", "4-1", "5-1"]


def test_neighbors():
    board = Board()
    assert ids(board.neighbors(board.spaces["1-1"])) == {"1-2", "2-1", "2-2"}
    assert ids(board.neighbors(board.spaces["5-1"])) == {"4-1", "5-2", "6-1"}
    assert ids(board.neighbors(board.spaces["5-5"])) == {
        "4-4", "4-5", "5-4", "5-6", "6-4", "6-5"}


def test_adjacency_is_symmetric():
    board = Board()
    for space in board.spaces.values():
        for neighbor in board.neighbors(space):
            assert space in board.neighbors(neighbor)


# --- Regole di piazzamento ---------------------------------------------------------

def test_oceans_only_on_ocean_spaces():
    board = Board()
    available = board.available_spaces(TileType.OCEAN, "Alice")
    assert len(available) == 12
    assert all(s.type is SpaceType.OCEAN for s in available)


def test_city_never_next_to_another_city():
    board = Board()
    board.place(TileType.CITY, "5-5", "Bob")
    available = ids(board.available_spaces(TileType.CITY, "Alice"))
    assert "4-4" not in available and "6-5" not in available
    assert "5-5" not in available            # occupata
    assert "5-4" not in available            # casella oceano
    assert "7-1" in available


def test_reserved_space_is_not_available():
    board = Board()
    assert "5-3" not in ids(board.available_spaces(TileType.CITY, "Alice"))
    assert "5-3" not in ids(board.available_spaces(TileType.GREENERY, "Alice"))


def test_greenery_anywhere_if_you_have_no_tiles():
    board = Board()
    assert len(board.available_spaces(TileType.GREENERY, "Alice")) == 61 - 12 - 1


def test_greenery_next_to_your_tiles_if_possible():
    board = Board()
    board.place(TileType.CITY, "7-1", "Alice")
    assert ids(board.available_spaces(TileType.GREENERY, "Alice")) == {"6-1", "6-2", "7-2", "8-1"}
    # Per Bob, che non ha tessere, vale ancora tutta la mappa
    assert len(board.available_spaces(TileType.GREENERY, "Bob")) > 4


def test_oceans_do_not_count_as_your_tiles():
    board = Board()
    board.place(TileType.OCEAN, "1-5", "Alice")
    assert board.spaces["1-5"].owner is None
    assert len(board.available_spaces(TileType.GREENERY, "Alice")) == 61 - 12 - 1


# --- Bonus e punti ---------------------------------------------------------------

def test_placement_bonus_resources():
    alice = Player("Alice")
    state = GameState(players=[alice])
    state.place_tile(alice, TileType.CITY, "4-1")      # pianta + titanio
    assert alice.resources[Resource.PLANTS] == 1
    assert alice.resources[Resource.TITANIUM] == 1


def test_card_bonus_draws_cards():
    alice = Player("Alice")
    state = GameState(players=[alice])
    assert state.place_tile(alice, TileType.OCEAN, "2-6") == 2   # 2 carte


def test_two_megacredits_per_adjacent_ocean():
    alice = Player("Alice")
    state = GameState(players=[alice])
    state.board.place(TileType.OCEAN, "5-4", None)
    state.board.place(TileType.OCEAN, "6-6", None)
    state.place_tile(alice, TileType.GREENERY, "5-7")  # vicina a 6-6, lontana da 5-4
    assert alice.resources[Resource.MEGACREDITS] == 2


def test_city_points_count_adjacent_greeneries_of_anyone():
    board = Board()
    board.place(TileType.CITY, "7-3", "Alice")
    board.place(TileType.GREENERY, "7-2", "Alice")
    board.place(TileType.GREENERY, "7-4", "Bob")
    board.place(TileType.GREENERY, "9-1", "Bob")      # lontana
    assert board.city_points("Alice") == 2
    assert board.city_points("Bob") == 0


def test_city_points_in_game_score():
    game = Game(["Alice", "Bob"], cards=[])
    alice = game.current_player
    board = game.state.board
    board.place(TileType.CITY, "7-3", "Alice")
    board.place(TileType.GREENERY, "7-2", "Bob")
    assert game.score(alice) == alice.victory_points() + 1


# --- Integrazione col motore ----------------------------------------------------------

def test_ocean_at_zero_degrees_must_be_placed_by_the_player():
    game = Game(["Alice", "Bob"], cards=[])
    game.state.planet.temperature = -2
    game.apply(Action(ActionType.ASTEROID))
    actions = game.legal_actions()
    assert actions and all(a.type is ActionType.PLACE_TILE for a in actions)
    assert all(game.state.board.spaces[a.space].type is SpaceType.OCEAN for a in actions)
    game.apply(actions[0])
    assert game.state.planet.oceans == 1
    assert game.current_player.terraform_rating == 22   # +1 temperatura, +1 oceano


def test_illegal_space_is_rejected():
    game = Game(["Alice", "Bob"], cards=[])
    game.apply(Action(ActionType.AQUIFER))
    with pytest.raises(ValueError):
        game.apply(Action(ActionType.PLACE_TILE, space="7-1"))   # terra, non oceano
