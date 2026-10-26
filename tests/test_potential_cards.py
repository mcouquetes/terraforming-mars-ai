"""Test delle ultime carte: effetti variabili, tag jolly, "prossima carta", Land Claim..."""

from tm_sim import heuristics as h
from tm_sim.actions import Action, ActionType
from tm_sim.board import TileType
from tm_sim.bots import RuleBot
from tm_sim.card_data import PRELUDE_CARDS
from tm_sim.card_list import CARDS_BY_NAME
from tm_sim.cards import Tag
from tm_sim.game import Game, Phase, Setup
from tm_sim.milestones import AWARDS_BY_NAME
from tm_sim.state import Resource

MC, PLANTS, HEAT, ENERGY = Resource.MEGACREDITS, Resource.PLANTS, Resource.HEAT, Resource.ENERGY
PRELUDES = {p.name: p for p in PRELUDE_CARDS}


def new_game(hand=(), in_play=(), bob_in_play=()):
    game = Game(["Alice", "Bob"], cards=[])
    alice, bob = game.state.players
    alice.hand = [CARDS_BY_NAME[c] for c in hand]
    alice.played = [CARDS_BY_NAME[c] for c in in_play]
    bob.played = [CARDS_BY_NAME[c] for c in bob_in_play]
    alice.resources[MC] = 100
    return game, alice


def play(game: Game, card: str) -> None:
    game.apply(Action(ActionType.PLAY_CARD, card))


def playable(game: Game) -> set[str]:
    return {a.card for a in game.legal_actions() if a.type is ActionType.PLAY_CARD}


# --- Effetti che dipendono dalla situazione ---------------------------------

def test_satellites_counts_space_tags_including_itself():
    game, alice = new_game(hand=("Satellites",), in_play=("Space Station", "Asteroid Mining"))
    play(game, "Satellites")
    assert alice.production[MC] == 3


def test_toll_station_counts_only_the_opponents():
    game, alice = new_game(hand=("Toll Station",), in_play=("Space Station",),
                           bob_in_play=("Space Station", "Asteroid Mining"))
    play(game, "Toll Station")
    assert alice.production[MC] == 2


def test_medical_lab_one_every_two_building_tags():
    game, alice = new_game(hand=("Medical Lab",), in_play=("Mine", "Mine"))
    alice.played[1] = CARDS_BY_NAME["Strip Mine"]
    play(game, "Medical Lab")                      # 3 tag edificio (compreso il suo) -> +1
    assert alice.production[MC] == 1


def test_cities_and_events_count_everyone():
    def game_with_two_cities(card: str):
        game, alice = new_game(hand=(card,), bob_in_play=("Comet", "Big Asteroid"))
        game.state.board.place(TileType.CITY, "5-1", "Bob")
        game.state.board.place(TileType.CITY, "ganymede", "Bob")    # città nello spazio
        game.state.planet.oxygen = 5
        play(game, card)
        return alice

    assert game_with_two_cities("Energy Saving").production[ENERGY] == 2   # tutte le città
    assert game_with_two_cities("Zeppelins").production[MC] == 1           # solo su Marte
    assert game_with_two_cities("Media Archives").resources[MC] == 100 - 8 + 2   # 2 eventi


def test_nitrogen_rich_asteroid_rewards_three_plant_tags():
    game, alice = new_game(hand=("Nitrogen-Rich Asteroid",), in_play=("Lichen", "Heather"))
    play(game, "Nitrogen-Rich Asteroid")
    assert alice.production[PLANTS] == 1
    game, alice = new_game(hand=("Nitrogen-Rich Asteroid",),
                           in_play=("Lichen", "Heather", "Grass"))
    play(game, "Nitrogen-Rich Asteroid")
    assert alice.production[PLANTS] == 4


def test_terraforming_ganymede_tr_per_jovian_tag():
    game, alice = new_game(hand=("Terraforming Ganymede",), in_play=("Io Mining Industries",))
    play(game, "Terraforming Ganymede")
    assert alice.terraform_rating == 22


# --- Tag jolly ----------------------------------------------------------------

def test_wild_tag_counts_for_requirements_but_not_for_awards():
    game, alice = new_game(hand=("AI Central",),
                           in_play=("Research Coordination", "Search For Life", "Physics Complex"))
    alice.change_production(ENERGY, 1)
    assert alice.tag_count(Tag.SCIENCE) == 3
    assert "AI Central" in playable(game)              # richiede 3 tag scienza
    assert AWARDS_BY_NAME["Scientist"].score(alice) == 2


# --- La prossima carta --------------------------------------------------------

def test_indentured_workers_discounts_only_the_next_card():
    game, alice = new_game(hand=("Indentured Workers", "Space Station", "Mine"))
    play(game, "Indentured Workers")
    assert game.card_cost(alice, CARDS_BY_NAME["Space Station"]) == 2
    play(game, "Space Station")
    assert alice.next_card_discount == 0
    assert game.card_cost(alice, CARDS_BY_NAME["Mine"]) == 4


def test_next_card_effects_end_with_the_generation():
    game, alice = new_game(hand=("Indentured Workers",))
    play(game, "Indentured Workers")
    game.state.end_generation()
    assert alice.next_card_discount == 0


def test_special_design_relaxes_requirements_of_the_next_card():
    game, alice = new_game(hand=("Special Design", "Lichen"))
    game.state.planet.temperature = -28                # Lichen vuole -24: mancano 2 passi
    assert "Lichen" not in playable(game)
    play(game, "Special Design")
    assert "Lichen" in playable(game)


def test_rad_suits_needs_two_cities_in_play():
    game, _ = new_game(hand=("Rad-Suits",))
    game.state.board.place(TileType.CITY, "5-1", "Bob")
    assert "Rad-Suits" not in playable(game)
    game.state.board.place(TileType.CITY, "9-1", "Bob")
    assert "Rad-Suits" in playable(game)


# --- Scelte particolari --------------------------------------------------------

def test_insulation_turns_heat_production_into_money_production():
    game, alice = new_game(hand=("Insulation",))
    assert "Insulation" not in playable(game)
    alice.change_production(HEAT, 3)
    play(game, "Insulation")
    game.apply(Action(ActionType.CHOOSE_EFFECT, "Insulation", target="0", option="2"))
    assert alice.production[HEAT] == 1 and alice.production[MC] == 2


def test_robotic_workforce_copies_a_building_production():
    game, alice = new_game(hand=("Robotic Workforce",))
    assert "Robotic Workforce" not in playable(game)    # niente da copiare
    alice.played = [CARDS_BY_NAME["Mine"]]
    play(game, "Robotic Workforce")                     # unica possibilità: in automatico
    assert alice.production[Resource.STEEL] == 1


def test_moss_costs_a_plant():
    game, alice = new_game(hand=("Moss",))
    game.state.planet.oceans = 3
    assert "Moss" not in playable(game)
    alice.resources[PLANTS] = 1
    play(game, "Moss")
    assert alice.resources[PLANTS] == 0 and alice.production[PLANTS] == 1


# --- Land Claim -----------------------------------------------------------------

def test_land_claim_reserves_a_space_for_its_owner():
    game, alice = new_game(hand=("Land Claim",))
    play(game, "Land Claim")
    game.apply(Action(ActionType.PLACE_TILE, space="1-1"))     # casella con 2 acciaio
    space = game.state.board.spaces["1-1"]
    assert space.claimed_by == "Alice" and space.is_empty
    assert alice.resources[Resource.STEEL] == 0                 # niente bonus per il segnalino
    board = game.state.board
    assert space not in board.available_spaces(TileType.GREENERY, "Bob")
    assert space in board.available_spaces(TileType.CITY, "Alice")


# --- Preludi che fanno giocare una carta -----------------------------------------

def prelude_game(prelude: str, hand: tuple[str, ...]):
    game = Game(["Alice", "Bob"], cards=[], setup=Setup.PRELUDE, preludes=[])
    alice = game.state.players[0]
    for player in game.state.players:
        player.corporation_choices, player.prelude_choices, player.drafted = [], [], []
        player.first_action_done = True
    alice.preludes = [PRELUDES[prelude]]
    alice.hand = [CARDS_BY_NAME[c] for c in hand]
    game.phase, game.current = Phase.PRELUDES, 0
    return game, alice


def test_eccentric_sponsor_plays_a_card_with_25_discount():
    game, alice = prelude_game("Eccentric Sponsor", ("Space Station",))
    alice.resources[MC] = 0
    game.apply(Action(ActionType.PLAY_PRELUDE, "Eccentric Sponsor"))
    options = {a.type for a in game.legal_actions()}
    assert options == {ActionType.PLAY_CARD, ActionType.SKIP_BONUS_PLAY}
    play(game, "Space Station")                            # costa 10: gratis con lo sconto
    assert any(c.name == "Space Station" for c in alice.played)
    assert alice.next_card_discount == 0


def test_eccentric_sponsor_fizzles_without_playable_cards():
    game, alice = prelude_game("Eccentric Sponsor", ())
    game.apply(Action(ActionType.PLAY_PRELUDE, "Eccentric Sponsor"))
    assert not game.bonus_play and alice.next_card_discount == 0


def test_ecology_experts_ignores_global_requirements():
    game, alice = prelude_game("Ecology Experts", ("Fish",))   # Fish vuole +2 °C
    alice.resources[MC] = 20
    game.state.players[1].change_production(PLANTS, 1)
    game.apply(Action(ActionType.PLAY_PRELUDE, "Ecology Experts"))
    assert ActionType.PLAY_CARD in {a.type for a in game.legal_actions()}


# --- Protected Habitats -------------------------------------------------------------

def test_protected_habitats_blocks_plant_attacks():
    game, alice = new_game(hand=("Comet",), bob_in_play=("Protected Habitats",))
    bob = game.state.players[1]
    bob.resources[PLANTS] = 5
    assert not game.is_protected(alice, PLANTS)
    assert game.is_protected(bob, PLANTS)


# --- Il bot e il potenziale -----------------------------------------------------------

def test_satellites_has_potential_with_space_cards_in_hand():
    game, alice = new_game(hand=("Satellites",))
    satellites = CARDS_BY_NAME["Satellites"]
    alone = h.potential_gain(game, alice, satellites)
    alice.hand += [CARDS_BY_NAME["Asteroid Mining"], CARDS_BY_NAME["Space Station"]]
    assert h.potential_gain(game, alice, satellites) > alone
    bot, patient = RuleBot(1, potential_patience=0), RuleBot(1)
    action = Action(ActionType.PLAY_CARD, "Satellites")
    assert patient.base_score(game, alice, action) < bot.base_score(game, alice, action)


def test_no_potential_once_the_tags_are_in_play():
    game, alice = new_game(hand=("Satellites",),
                           in_play=("Asteroid Mining", "Space Station", "Io Mining Industries"))
    assert h.potential_gain(game, alice, CARDS_BY_NAME["Satellites"]) < 1.0


def test_land_claim_updates_what_others_can_place():
    """Bug trovato da learn.py: dopo un Land Claim il motore ricordava ancora la
    casella come libera per l'avversario, e la sua Mining Area restava senza posto."""
    game, alice = new_game(hand=("Land Claim",))
    board = game.state.board
    bob = game.state.players[1]
    from tm_sim.board import PlacementRule, TilePlacement
    mining = TilePlacement(TileType.MINING_AREA, PlacementRule.METAL_BONUS_NEXT_TO_OWN)
    board.place(TileType.CITY, "8-5", "Bob")              # accanto a 8-6 (titanio)
    game.current = 1
    assert game._can_place(mining)                         # Bob potrebbe usare 8-6...
    game.current = 0
    play(game, "Land Claim")
    game.apply(Action(ActionType.PLACE_TILE, space="8-6")) # ...ma Alice la riserva
    game.current = 1
    assert [s.id for s in board.available_spaces(mining, "Bob")] == []
    assert not game._can_place(mining)


# --- Valore effettivo e potenziale (60/40) ----------------------------------------

def test_potential_raises_engine_cards_but_not_plain_ones():
    game, alice = new_game()
    game.state.generation = 2
    catapult, asteroid = CARDS_BY_NAME["Earth Catapult"], CARDS_BY_NAME["Big Asteroid"]
    with h.potential_weight(0.0):
        plain_catapult, plain_asteroid = (h.card_value(game, alice, catapult),
                                          h.card_value(game, alice, asteroid))
    with h.potential_weight(0.4):
        blended = h.card_value(game, alice, catapult)
        assert h.card_value(game, alice, asteroid) == plain_asteroid     # niente potenziale
    potential = h.card_potential(game, alice, catapult)
    assert potential > plain_catapult
    assert abs(blended - (0.6 * plain_catapult + 0.4 * potential)) < 1e-6


def test_each_bot_uses_its_own_potential_weight():
    game, alice = new_game(hand=("Earth Catapult",))
    action = Action(ActionType.PLAY_CARD, "Earth Catapult")
    plain = RuleBot(1).base_score(game, alice, action)                  # predefinito: 0
    blended = RuleBot(1, potential_weight=0.4).base_score(game, alice, action)
    assert blended > plain
    assert RuleBot(1).base_score(game, alice, action) == plain          # nessun "residuo"
