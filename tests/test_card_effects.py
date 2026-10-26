"""Test di effetti permanenti, risorse sulle carte e punti vittoria variabili."""

from tm_sim.actions import Action, ActionType
from tm_sim.board import TileType
from tm_sim.card_list import CARDS_BY_NAME
from tm_sim.cards import Card, CardType, Tag
from tm_sim.corporations import CORPORATIONS_BY_NAME
from tm_sim.game import Game
from tm_sim.state import Resource

MC = Resource.MEGACREDITS


def game_with(*hand: str | Card, in_play: tuple[str, ...] = ()) -> tuple[Game, object]:
    """Alice con certe carte in mano e certe carte blu già in gioco."""
    game = Game(["Alice", "Bob"], cards=[])
    alice = game.state.players[0]
    alice.hand = [CARDS_BY_NAME[c] if isinstance(c, str) else c for c in hand]
    alice.played = [CARDS_BY_NAME[c] for c in in_play]
    alice.resources[MC] = 100
    return game, alice


def play(game: Game, name: str) -> None:
    game.apply(Action(ActionType.PLAY_CARD, name))


def place(game: Game, space: str) -> None:
    game.apply(Action(ActionType.PLACE_TILE, space=space))


# --- Sconti -------------------------------------------------------------------------

def test_discount_from_blue_card():
    game, alice = game_with("Sponsors", in_play=("Earth Office",))   # -3 per tag Terra
    assert game.card_cost(alice, CARDS_BY_NAME["Sponsors"]) == 6 - 3


def test_discounts_are_per_tag():
    double_earth = Card("Prova", 10, tags={Tag.EARTH: 2})
    game, alice = game_with(in_play=("Earth Office",))
    assert game.card_cost(alice, double_earth) == 10 - 6


def test_mass_converter_discount_is_once_per_card():
    double_space = Card("Prova", 10, tags={Tag.SPACE: 2})
    game, alice = game_with(in_play=("Mass Converter",))
    assert game.card_cost(alice, double_space) == 10 - 2


def test_discounts_add_up_with_corporation():
    game, alice = game_with(in_play=("Earth Office", "Earth Catapult"))   # -3 Terra, -2 tutte
    alice.corporation = CORPORATIONS_BY_NAME["Teractor"]                  # -3 Terra
    assert game.card_cost(alice, CARDS_BY_NAME["Sponsors"]) == 0          # 6 - 8, non sotto 0


def test_discount_does_not_apply_to_the_card_itself():
    game, alice = game_with("Earth Office")
    play(game, "Earth Office")
    assert alice.resources[MC] == 100 - 1


# --- Metalli e requisiti ------------------------------------------------------------

def test_advanced_alloys_metal_values():
    game, alice = game_with(in_play=("Advanced Alloys",))
    rules = game.payment_rules(alice)
    assert rules.steel_value == 3 and rules.titanium_value == 4


def test_adaptation_technology_leeway():
    game, alice = game_with("Lichen", in_play=("Adaptation Technology",))   # Lichen: -24°C
    game.state.planet.temperature = -28
    assert Action(ActionType.PLAY_CARD, "Lichen") in game.legal_actions()


# --- Effetti a scatto ------------------------------------------------------------------

def test_arctic_algae_plants_when_anyone_places_an_ocean():
    game, alice = game_with(in_play=("Arctic Algae",))
    game.current = 1                                     # è Bob a piazzare
    game.apply(Action(ActionType.AQUIFER))
    place(game, "1-5")
    assert alice.resources[Resource.PLANTS] == 2


def test_media_group_and_optimal_aerobraking():
    game, alice = game_with("Imported GHG", in_play=("Media Group", "Optimal Aerobraking"))
    play(game, "Imported GHG")                           # evento spazio, 7 M€
    assert alice.resources[MC] == 100 - 7 + 3 + 3
    assert alice.resources[Resource.HEAT] == 3 + 3       # 3 dalla carta, 3 dall'effetto


def test_rover_construction_money_for_any_city():
    game, alice = game_with(in_play=("Rover Construction",))
    game.current = 1
    game.apply(Action(ActionType.CITY))
    place(game, "7-1")
    assert alice.resources[MC] == 100 + 2


def test_standard_technology_refund():
    game, alice = game_with(in_play=("Standard Technology",))
    game.apply(Action(ActionType.ASTEROID))
    assert alice.resources[MC] == 100 - 14 + 3


# --- Risorse sulle carte e punti variabili ---------------------------------------------

def test_decomposers_counts_itself_and_later_cards():
    game, alice = game_with("Decomposers", "Lichen")
    game.state.planet.oxygen = 3
    game.state.planet.temperature = -24
    play(game, "Decomposers")                            # tag microbo: compresa questa
    assert alice.card_resources["Decomposers"] == 1
    play(game, "Lichen")                                 # tag pianta
    assert alice.card_resources["Decomposers"] == 2


def test_decomposers_points_one_every_three_microbes():
    game, alice = game_with(in_play=("Decomposers",))
    base = game.score(alice)
    alice.card_resources["Decomposers"] = 5
    assert game.score(alice) == base + 1
    alice.card_resources["Decomposers"] = 6
    assert game.score(alice) == base + 2


def test_pets_start_with_an_animal_and_grow_with_cities():
    game, alice = game_with("Pets")
    play(game, "Pets")
    assert alice.card_resources["Pets"] == 1
    game.apply(Action(ActionType.CITY))
    place(game, "7-1")
    assert alice.card_resources["Pets"] == 2


def test_points_per_jovian_tag():
    io_mining = CARDS_BY_NAME["Io Mining Industries"]    # 1 PV per tag gioviano
    game, alice = game_with(in_play=("Io Mining Industries",))
    assert io_mining.variable_points(alice, 0, 0) == 1   # il suo stesso tag
    alice.played.append(CARDS_BY_NAME["Asteroid Mining"])
    assert io_mining.variable_points(alice, 0, 0) == 2


def test_points_per_three_cities_in_play():
    game, alice = game_with(in_play=("Immigration Shuttles",))   # 1 PV ogni 3 città
    base = game.score(alice)
    for space in ("1-1", "3-3", "7-1"):
        game.state.board.place(TileType.CITY, space, "Bob")
    assert game.score(alice) == base + 1


def test_blue_cards_are_active_type():
    for name in ("Earth Office", "Pets", "Decomposers", "Arctic Algae"):
        assert CARDS_BY_NAME[name].type is CardType.ACTIVE


# --- Optimal Aerobraking: effetto e messaggi --------------------------------

def _action_game():
    from tm_sim.bots import RuleBot
    from tm_sim.game import Game, Phase, Setup
    game = Game(["A", "B"], seed=1, setup=Setup.STANDARD)
    bot = RuleBot(1)
    while game.phase is not Phase.ACTION:
        game.apply(bot.choose(game, game.legal_actions()))
    return game


def test_optimal_aerobraking_gives_3_mc_and_3_heat_for_space_events():
    from tm_sim.actions import Action, ActionType
    from tm_sim.card_list import CARDS_BY_NAME
    from tm_sim.state import Resource
    game = _action_game()
    game.messages = []
    player = game.current_player
    player.played.append(CARDS_BY_NAME["Optimal Aerobraking"])
    player.hand.append(CARDS_BY_NAME["Asteroid"])
    player.resources[Resource.MEGACREDITS] = 50
    player.resources[Resource.TITANIUM] = 0
    heat = player.resources[Resource.HEAT]
    game.apply(Action(ActionType.PLAY_CARD, "Asteroid"))
    assert player.resources[Resource.MEGACREDITS] == 50 - 14 + 3
    assert player.resources[Resource.HEAT] == heat + 3
    assert any("Optimal Aerobraking" in m and "+3 megacrediti" in m and "+3 calore" in m
               for m in game.messages)


def test_optimal_aerobraking_ignores_non_space_events_and_space_non_events():
    from tm_sim.actions import Action, ActionType
    from tm_sim.card_list import CARDS_BY_NAME
    from tm_sim.state import Resource
    game = _action_game()
    player = game.current_player
    player.played.append(CARDS_BY_NAME["Optimal Aerobraking"])
    player.hand.append(CARDS_BY_NAME["Investment Loan"])     # evento senza tag spazio
    heat = player.resources[Resource.HEAT]
    game.apply(Action(ActionType.PLAY_CARD, "Investment Loan"))
    assert player.resources[Resource.HEAT] == heat


def test_trigger_cards_describe_their_effect():
    from tm_sim.card_effects import CARD_TRIGGERS
    from tm_sim.card_list import CARDS_BY_NAME
    for name in CARD_TRIGGERS:
        assert "effetto:" in CARDS_BY_NAME[name].describe(), name
