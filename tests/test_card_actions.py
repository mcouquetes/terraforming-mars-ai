"""Test delle azioni delle carte blu ("Azione: spendi X per ottenere Y")."""

from tm_sim import heuristics as h
from tm_sim.actions import Action, ActionType
from tm_sim.board import TileType
from tm_sim.bots import RuleBot
from tm_sim.card_list import CARDS_BY_NAME
from tm_sim.game import Game
from tm_sim.state import MAX_OCEANS, MAX_OXYGEN, Resource

MC = Resource.MEGACREDITS


def game_with(*in_play: str, hand: tuple[str, ...] = (), bob_in_play: tuple[str, ...] = ()):
    """Partita in cui Alice ha già in gioco queste carte (senza averle pagate)."""
    game = Game(["Alice", "Bob"], cards=[])
    alice, bob = game.state.players
    alice.played = [CARDS_BY_NAME[c] for c in in_play]
    bob.played = [CARDS_BY_NAME[c] for c in bob_in_play]
    alice.hand = [CARDS_BY_NAME[c] for c in hand]
    alice.resources[MC] = 100
    return game, alice


def card_actions(game: Game, card: str | None = None) -> list[Action]:
    """Le azioni di carte blu che Alice può usare adesso."""
    return [a for a in game.legal_actions()
            if a.type is ActionType.CARD_ACTION and (card is None or a.card == card)]


def use(game: Game, card: str, alternative: int = 0, option: str | None = None) -> None:
    game.apply(Action(ActionType.CARD_ACTION, card, target=str(alternative), option=option))


# --- Regole generali --------------------------------------------------------

def test_action_once_per_generation_and_counts_as_an_action():
    game, alice = game_with("Birds")
    use(game, "Birds")
    assert alice.card_resources["Birds"] == 1
    assert game.actions_this_turn == 1
    assert card_actions(game, "Birds") == []           # già usata in questa generazione
    game.state.end_generation()
    assert card_actions(game, "Birds") != []          # nuova generazione: di nuovo disponibile


def test_cards_in_hand_have_no_actions():
    game, _ = game_with(hand=("Birds",))
    assert card_actions(game) == []


def test_actions_appear_in_the_card_action_category():
    from tm_sim.actions import ActionCategory, group_by_category
    game, _ = game_with("Tardigrades")
    groups = group_by_category(game.legal_actions())
    assert [a.card for a in groups[ActionCategory.CARD_ACTION]] == ["Tardigrades"]


# --- Pagamento ----------------------------------------------------------------

def test_aquifer_pumping_can_be_paid_with_steel():
    game, alice = game_with("Aquifer Pumping")
    alice.resources[MC] = 0
    alice.resources[Resource.STEEL] = 4                # 4 acciaio × 2 = 8 M€
    tr = alice.terraform_rating
    use(game, "Aquifer Pumping")
    assert alice.resources[Resource.STEEL] == 0
    assert game.pending_tile.tile is TileType.OCEAN
    ocean_space = game.legal_actions()[0].space
    game.apply(Action(ActionType.PLACE_TILE, space=ocean_space))
    assert alice.terraform_rating == tr + 1


def test_water_import_can_be_paid_with_titanium_but_not_steel():
    game, alice = game_with("Water Import From Europa")
    alice.resources[MC] = 0
    alice.resources[Resource.STEEL] = 10
    assert card_actions(game) == []
    alice.resources[Resource.TITANIUM] = 4             # 4 × 3 = 12 M€
    assert len(card_actions(game)) == 1


def test_resources_to_spend_are_required():
    game, alice = game_with("Ironworks", "Caretaker Contract", "Space Elevator")
    assert card_actions(game) == []                    # niente energia, calore, acciaio
    alice.resources[Resource.ENERGY] = 4
    alice.resources[Resource.HEAT] = 8
    alice.resources[Resource.STEEL] = 1
    assert {a.card for a in card_actions(game)} == {"Ironworks", "Caretaker Contract",
                                                    "Space Elevator"}
    use(game, "Ironworks")
    assert alice.resources[Resource.ENERGY] == 0
    assert alice.resources[Resource.STEEL] == 2        # 1 + 1 guadagnato
    assert game.state.planet.oxygen == 1


def test_production_cost_needs_enough_production():
    game, alice = game_with("Equatorial Magnetizer")
    assert card_actions(game) == []                    # serve 1 di produzione di energia
    alice.change_production(Resource.ENERGY, 1)
    tr = alice.terraform_rating
    use(game, "Equatorial Magnetizer")
    assert alice.production[Resource.ENERGY] == 0
    assert alice.terraform_rating == tr + 1


# --- Azioni che non farebbero nulla --------------------------------------------

def test_no_ocean_action_when_oceans_are_finished():
    game, _ = game_with("Aquifer Pumping")
    game.state.planet.oceans = MAX_OCEANS
    assert card_actions(game) == []


def test_water_splitting_plant_needs_oxygen_to_raise():
    game, alice = game_with("Water Splitting Plant")
    alice.resources[Resource.ENERGY] = 3
    assert len(card_actions(game)) == 1
    game.state.planet.oxygen = MAX_OXYGEN
    assert card_actions(game) == []


def test_ironworks_still_gives_steel_at_max_oxygen():
    game, alice = game_with("Ironworks")
    alice.resources[Resource.ENERGY] = 4
    game.state.planet.oxygen = MAX_OXYGEN
    assert len(card_actions(game)) == 1


# --- Risorse sulla carta e alternative ---------------------------------------------

def test_ghg_bacteria_add_or_convert():
    game, alice = game_with("GHG Producing Bacteria")
    assert [a.target for a in card_actions(game)] == ["1"]     # solo "aggiungi"
    alice.add_card_resource("GHG Producing Bacteria", 2)
    assert [a.target for a in card_actions(game)] == ["0", "1"]
    temperature = game.state.planet.temperature
    use(game, "GHG Producing Bacteria", 0)
    assert alice.card_resources["GHG Producing Bacteria"] == 0
    assert game.state.planet.temperature == temperature + 2


def test_nitrite_bacteria_start_with_three_microbes_to_convert():
    game = Game(["Alice", "Bob"], cards=[])
    alice = game.current_player
    alice.hand = [CARDS_BY_NAME["Nitrite Reducing Bacteria"]]
    alice.resources[MC] = 100
    game.apply(Action(ActionType.PLAY_CARD, "Nitrite Reducing Bacteria"))
    game.apply(Action(ActionType.END_TURN))
    game.apply(Action(ActionType.PASS))                # Bob passa, tocca di nuovo ad Alice
    tr = alice.terraform_rating
    use(game, "Nitrite Reducing Bacteria", 0)
    assert alice.terraform_rating == tr + 1


def test_physics_complex_science_is_worth_two_points_each():
    game, alice = game_with("Physics Complex")
    alice.resources[Resource.ENERGY] = 6
    points = game.score(alice)
    use(game, "Physics Complex")
    assert game.score(alice) == points + 2


def test_electro_catapult_plant_or_steel():
    game, alice = game_with("Electro Catapult")
    alice.resources[Resource.PLANTS] = 1
    assert [a.target for a in card_actions(game)] == ["0"]
    alice.resources[MC] = 0
    use(game, "Electro Catapult", 0)
    assert alice.resources[MC] == 7 and alice.resources[Resource.PLANTS] == 0


# --- Prendere e dare risorse ad altre carte ---------------------------------------

def test_predators_take_animals_from_any_card_but_pets_and_itself():
    game, alice = game_with("Predators", bob_in_play=("Birds", "Pets"))
    bob = game.state.players[1]
    alice.add_card_resource("Predators", 3)
    bob.add_card_resource("Birds", 2)
    bob.add_card_resource("Pets", 5)
    assert [a.option for a in card_actions(game)] == ["Bob:Birds"]
    use(game, "Predators", option="Bob:Birds")
    assert bob.card_resources["Birds"] == 1
    assert alice.card_resources["Predators"] == 4


def test_predators_need_a_target():
    game, _ = game_with("Predators", "Birds")          # Birds di Alice è vuota
    assert card_actions(game, "Predators") == []


def test_ants_can_take_from_your_own_cards():
    game, alice = game_with("Ants", "Tardigrades")
    alice.add_card_resource("Tardigrades", 2)
    assert "Alice:Tardigrades" in {a.option for a in card_actions(game, "Ants")}


def test_symbiotic_fungus_adds_to_your_other_microbe_cards():
    game, alice = game_with("Symbiotic Fungus")
    assert card_actions(game) == []                    # nessuna carta microbi
    alice.played.append(CARDS_BY_NAME["Tardigrades"])
    use(game, "Symbiotic Fungus", option="Tardigrades")
    assert alice.card_resources["Tardigrades"] == 1


def test_extreme_cold_fungus_plant_or_two_microbes():
    game, alice = game_with("Extreme-Cold Fungus", "Decomposers")
    options = {(a.target, a.option) for a in card_actions(game, "Extreme-Cold Fungus")}
    assert options == {("0", None), ("1", "Decomposers")}
    use(game, "Extreme-Cold Fungus", 1, "Decomposers")
    assert alice.card_resources["Decomposers"] == 2


# --- Pescare e comprare carte ------------------------------------------------------

def test_development_center_draws_a_card():
    game, alice = game_with("Development Center")
    game.deck = [CARDS_BY_NAME["Lichen"]]
    alice.resources[Resource.ENERGY] = 1
    use(game, "Development Center")
    assert [c.name for c in alice.hand] == ["Lichen"]


def test_business_network_look_and_buy():
    game, alice = game_with("Business Network")
    game.deck = [CARDS_BY_NAME["Heather"], CARDS_BY_NAME["Lichen"]]   # si pesca dalla fine
    use(game, "Business Network")
    assert game.legal_actions() == [Action(ActionType.SKIP_CARD, "Lichen"),
                                    Action(ActionType.BUY_CARD, "Lichen")]
    game.apply(Action(ActionType.BUY_CARD, "Lichen"))
    assert [c.name for c in alice.hand] == ["Lichen"]
    assert alice.resources[MC] == 97
    assert game.actions_this_turn == 1 and game.current_player is alice   # azione completa


def test_inventors_guild_skip_discards():
    game, alice = game_with("Inventors' Guild")
    game.deck = [CARDS_BY_NAME["Lichen"]]
    use(game, "Inventors' Guild")
    game.apply(Action(ActionType.SKIP_CARD, "Lichen"))
    assert alice.hand == [] and [c.name for c in game.discard_pile] == ["Lichen"]


def test_search_for_life_finds_life_only_with_microbe_tag():
    game, alice = game_with("Search For Life")
    game.deck = [CARDS_BY_NAME["Tardigrades"], CARDS_BY_NAME["Lichen"]]
    points = game.score(alice)
    use(game, "Search For Life")                       # Lichen: niente vita
    assert alice.card_resources.get("Search For Life", 0) == 0
    assert alice.resources[MC] == 99
    game.state.end_generation()
    use(game, "Search For Life")                       # Tardigrades: tag microbo
    assert alice.card_resources["Search For Life"] == 1
    assert game.score(alice) == points + 3
    assert {c.name for c in game.discard_pile} == {"Lichen", "Tardigrades"}


# --- Le altre carte particolari ---------------------------------------------------

def test_power_infrastructure_any_amount_of_energy():
    game, alice = game_with("Power Infrastructure")
    alice.resources[Resource.ENERGY] = 3
    assert [a.option for a in card_actions(game)] == ["1", "2", "3"]
    alice.resources[MC] = 0
    use(game, "Power Infrastructure", option="2")
    assert alice.resources[MC] == 2 and alice.resources[Resource.ENERGY] == 1


def test_martian_rails_counts_cities_on_mars_only():
    game, alice = game_with("Martian Rails")
    alice.resources[Resource.ENERGY] = 1
    assert card_actions(game) == []                    # nessuna città: inutile
    board = game.state.board
    board.place(TileType.CITY, "5-1", "Bob")
    board.place(TileType.CITY, "9-1", "Alice")
    board.place(TileType.CITY, "ganymede", "Bob")      # nello spazio: non conta
    alice.resources[MC] = 0
    use(game, "Martian Rails")
    assert alice.resources[MC] == 2


def test_psychrophiles_microbes_pay_for_plant_cards():
    game, alice = game_with("Psychrophiles", hand=("Lichen", "Tardigrades"))
    alice.add_card_resource("Psychrophiles", 3)
    alice.resources[MC] = 1
    game.state.planet.temperature = -24                # requisito di Lichen
    playable = {a.card for a in game.legal_actions() if a.type is ActionType.PLAY_CARD}
    assert playable == {"Lichen"}                      # 3 microbi = 6 M€, + 1 M€ = 7
    game.apply(Action(ActionType.PLAY_CARD, "Lichen"))
    assert alice.card_resources["Psychrophiles"] == 0 and alice.resources[MC] == 0


def test_industrial_center_tile_next_to_a_city():
    game, alice = game_with(hand=("Industrial Center",))
    playable = {a.card for a in game.legal_actions() if a.type is ActionType.PLAY_CARD}
    assert "Industrial Center" not in playable         # nessuna città sulla mappa
    game.state.board.place(TileType.CITY, "5-1", "Bob")
    game.apply(Action(ActionType.PLAY_CARD, "Industrial Center"))
    spaces = {a.space for a in game.legal_actions()}
    neighbors = {s.id for s in game.state.board.neighbors(game.state.board.spaces["5-1"])}
    assert spaces and spaces <= neighbors
    game.apply(Action(ActionType.PLACE_TILE, space=sorted(spaces)[0]))
    use(game, "Industrial Center")
    assert alice.production[Resource.STEEL] == 1


def test_restricted_area_tile_and_draw():
    game, alice = game_with(hand=("Restricted Area",))
    game.apply(Action(ActionType.PLAY_CARD, "Restricted Area"))
    assert game.pending_tile.tile is TileType.RESTRICTED_AREA


# --- Il bot ----------------------------------------------------------------------------

def test_bot_uses_free_point_actions():
    game, alice = game_with("Birds")
    game.state.planet.oxygen = 13
    alice.resources[MC] = 5                            # niente progetti standard: solo l'azione gratis
    choice = RuleBot(1).choose(game, game.legal_actions())
    assert choice == Action(ActionType.CARD_ACTION, "Birds", target="0")


def test_bot_takes_animals_from_the_opponent_not_from_itself():
    game, alice = game_with("Predators", "Fish", bob_in_play=("Birds",))
    alice.add_card_resource("Fish", 2)
    game.state.players[1].add_card_resource("Birds", 2)
    options = card_actions(game, "Predators")
    best = max(options, key=lambda a: h.card_action_value(
        game, alice, CARDS_BY_NAME["Predators"], CARDS_BY_NAME["Predators"].actions[0], a.option))
    assert best.option == "Bob:Birds"


def test_energy_hungry_action_cards_are_worth_less_without_energy():
    game, alice = game_with()
    card = CARDS_BY_NAME["Physics Complex"]
    without = h.card_value(game, alice, card)
    alice.change_production(Resource.ENERGY, 6)
    assert h.card_value(game, alice, card) > without
