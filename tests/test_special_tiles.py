"""Test delle regole di piazzamento speciali e delle tessere speciali."""

from tm_sim.actions import Action, ActionType
from tm_sim.board import Board, PlacementRule, TilePlacement, TileType
from tm_sim.card_list import CARDS_BY_NAME
from tm_sim.corporations import CORPORATIONS_BY_NAME
from tm_sim.game import Game
from tm_sim.state import MAX_OCEANS, Resource

MC = Resource.MEGACREDITS


def ids(spaces) -> set[str]:
    return {s.id for s in spaces}


def spaces_for(board: Board, tile: TileType, rule: PlacementRule, owner: str = "Alice") -> set[str]:
    return ids(board.available_spaces(TilePlacement(tile, rule), owner))


def game_with(*hand: str) -> tuple[Game, object]:
    game = Game(["Alice", "Bob"], cards=[])
    alice = game.state.players[0]
    alice.hand = [CARDS_BY_NAME[c] for c in hand]
    alice.resources[MC] = 100
    return game, alice


def play(game: Game, name: str) -> None:
    game.apply(Action(ActionType.PLAY_CARD, name))


def place(game: Game, space: str) -> None:
    game.apply(Action(ActionType.PLACE_TILE, space=space))


def playable(game: Game) -> set[str]:
    return {a.card for a in game.legal_actions() if a.type is ActionType.PLAY_CARD}


# --- Regole di piazzamento ----------------------------------------------------------

def test_volcanic_spaces():
    board = Board()
    assert spaces_for(board, TileType.CITY, PlacementRule.VOLCANIC) == {"2-2", "3-1", "4-1", "5-1"}


def test_isolated_means_no_tile_around():
    board = Board()
    board.place(TileType.CITY, "7-3", "Bob")
    available = spaces_for(board, TileType.NATURAL_PRESERVE, PlacementRule.ISOLATED)
    assert "7-2" not in available and "7-4" not in available
    assert "7-6" in available


def test_next_to_two_cities():
    board = Board()
    assert spaces_for(board, TileType.CITY, PlacementRule.NEXT_TO_TWO_CITIES) == set()
    board.place(TileType.CITY, "7-2", "Bob")
    board.place(TileType.CITY, "7-4", "Bob")
    assert "7-3" in spaces_for(board, TileType.CITY, PlacementRule.NEXT_TO_TWO_CITIES)


def test_metal_bonus_spaces():
    board = Board()
    available = spaces_for(board, TileType.MINING_RIGHTS, PlacementRule.METAL_BONUS)
    assert {"1-1", "2-2", "4-1", "8-6"} <= available          # acciaio o titanio
    assert "5-1" not in available                              # solo piante
    # Mining Area: anche accanto a una tua tessera
    assert spaces_for(board, TileType.MINING_AREA, PlacementRule.METAL_BONUS_NEXT_TO_OWN) == set()
    board.place(TileType.CITY, "8-5", "Alice")
    assert spaces_for(board, TileType.MINING_AREA, PlacementRule.METAL_BONUS_NEXT_TO_OWN) == {"8-6"}


def test_greenery_on_ocean_space_and_ocean_on_land():
    board = Board()
    ocean_spaces = spaces_for(board, TileType.GREENERY, PlacementRule.OCEAN_SPACE)
    assert len(ocean_spaces) == 12
    assert "7-1" in spaces_for(board, TileType.OCEAN, PlacementRule.LAND)


def test_reserved_spaces():
    board = Board()
    assert spaces_for(board, TileType.CITY, PlacementRule.NOCTIS) == {"5-3"}
    assert spaces_for(board, TileType.CITY, PlacementRule.GANYMEDE) == {"ganymede"}
    assert spaces_for(board, TileType.CITY, PlacementRule.PHOBOS) == {"phobos"}
    # Le caselle riservate non sono mai disponibili con le regole normali.
    normal = ids(board.available_spaces(TileType.CITY, "Alice"))
    assert not {"5-3", "ganymede", "phobos"} & normal


# --- Carte con regole speciali -----------------------------------------------------------

def test_card_with_city_needs_a_valid_space():
    game, alice = game_with("Urbanized Area")
    alice.change_production(Resource.ENERGY, 1)
    assert "Urbanized Area" not in playable(game)              # nessuna casella tra 2 città
    board = game.state.board
    board.place(TileType.CITY, "7-2", "Bob")
    board.place(TileType.CITY, "7-4", "Bob")
    assert "Urbanized Area" in playable(game)


def test_ocean_cards_are_playable_even_with_all_oceans_placed():
    game, alice = game_with("Artificial Lake")
    game.state.planet.temperature = -6
    game.state.planet.oceans = MAX_OCEANS
    assert "Artificial Lake" in playable(game)


def test_noctis_city_goes_on_its_space():
    game, alice = game_with("Noctis City")
    alice.change_production(Resource.ENERGY, 1)
    play(game, "Noctis City")
    assert [a.space for a in game.legal_actions()] == ["5-3"]
    place(game, "5-3")
    assert alice.cities == 1 and alice.production[Resource.ENERGY] == 0


def test_ganymede_colony_is_a_city_in_space():
    game, alice = game_with("Ganymede Colony")
    alice.corporation = CORPORATIONS_BY_NAME["Tharsis Republic"]
    play(game, "Ganymede Colony")
    place(game, "ganymede")
    assert alice.cities == 1                                  # conta per Mayor
    assert alice.production[MC] == 0                          # Tharsis: niente, non è su Marte
    assert alice.resources[MC] == 100 - 20 + 3                # ...ma +3 M€ perché è sua


def test_mohole_area_on_ocean_space_is_not_an_ocean():
    game, alice = game_with("Mohole Area")
    play(game, "Mohole Area")
    place(game, "1-5")
    assert game.state.planet.oceans == 0
    assert game.state.oceans_remaining() == MAX_OCEANS
    assert alice.production[Resource.HEAT] == 4


# --- Tessere speciali: effetti e punti ------------------------------------------------

def test_mining_rights_gives_production_of_the_space_metal():
    game, alice = game_with("Mining Rights")
    play(game, "Mining Rights")
    place(game, "8-6")                                        # titanio
    assert alice.production[Resource.TITANIUM] == 1
    assert alice.resources[Resource.TITANIUM] == 1            # più il bonus della casella


def test_capital_points_for_adjacent_oceans_and_greeneries():
    game, alice = game_with()
    board = game.state.board
    board.place(TileType.CAPITAL, "5-7", "Alice")             # vicina a 5-6, 6-6
    board.place(TileType.OCEAN, "5-6", None)
    board.place(TileType.OCEAN, "6-6", None)
    board.place(TileType.GREENERY, "4-6", "Bob")
    base = alice.victory_points()
    assert game.score(alice) == base + 2 + 1                  # 2 oceani + 1 foresta


def test_commercial_district_points_for_adjacent_cities():
    game, alice = game_with()
    board = game.state.board
    board.place(TileType.COMMERCIAL_DISTRICT, "7-3", "Alice")
    board.place(TileType.CITY, "7-2", "Bob")
    board.place(TileType.CITY, "7-4", "Alice")
    assert board.special_tile_points("Alice") == 2


def test_landlord_counts_special_tiles_once():
    game, alice = game_with()
    game.state.place_tile(alice, TileType.CAPITAL, "7-1")
    game.state.place_tile(alice, TileType.NUCLEAR_ZONE, "9-3")
    assert alice.cities == 1 and alice.special_tiles == 1     # Capital è una città


def test_special_tiles_count_as_your_tiles_for_greeneries():
    game, alice = game_with()
    board = game.state.board
    zone = board.place(TileType.NUCLEAR_ZONE, "7-3", "Alice")
    near = ids(board.available_spaces(TileType.GREENERY, "Alice"))
    assert near == ids(board.neighbors(zone))                 # solo accanto alla sua tessera


# --- Carte blu legate alle tessere -------------------------------------------------------

def test_immigrant_city_counts_its_own_city():
    game, alice = game_with("Immigrant City")
    alice.change_production(Resource.ENERGY, 1)
    play(game, "Immigrant City")
    place(game, "7-1")
    assert alice.production[MC] == -2 + 1                     # -2 della carta, +1 per la città


def test_ecological_zone_needs_a_greenery_and_gets_animals():
    game, alice = game_with("Ecological Zone")
    assert "Ecological Zone" not in playable(game)
    game.state.place_tile(alice, TileType.GREENERY, "7-1")
    assert "Ecological Zone" in playable(game)
    play(game, "Ecological Zone")
    assert {a.space for a in game.legal_actions()} <= {"6-1", "6-2", "7-2", "8-1"}
    place(game, "7-2")
    assert alice.card_resources["Ecological Zone"] == 2       # i suoi tag animale e pianta
