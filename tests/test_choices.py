"""Test delle carte con scelta, delle risorse messe su altre carte e delle combo."""

from tm_sim import heuristics as h
from tm_sim.actions import Action, ActionType
from tm_sim.bots import RuleBot
from tm_sim.card_list import CARDS_BY_NAME
from tm_sim.game import Game
from tm_sim.state import Resource

MC, PLANTS, HEAT, ENERGY = Resource.MEGACREDITS, Resource.PLANTS, Resource.HEAT, Resource.ENERGY


def new_game(hand=(), in_play=(), deck=()):
    game = Game(["Alice", "Bob"], cards=[])
    game.deck = [CARDS_BY_NAME[c] for c in reversed(deck)]   # si pesca dalla fine
    alice = game.state.players[0]
    game.state.players[1].change_production(PLANTS, 1)      # Fish e Birds devono colpire qualcuno
    alice.hand = [CARDS_BY_NAME[c] for c in hand]
    alice.played = [CARDS_BY_NAME[c] for c in in_play]
    alice.resources[MC] = 100
    return game, alice


def play(game: Game, card: str) -> None:
    game.apply(Action(ActionType.PLAY_CARD, card))


def choose(game: Game, index: int, option: str | None = None) -> None:
    card = game.pending_choices[0].card.name
    game.apply(Action(ActionType.CHOOSE_EFFECT, card, target=str(index), option=option))


def choices(game: Game) -> set[tuple[str, str | None]]:
    return {(a.target, a.option) for a in game.legal_actions()
            if a.type is ActionType.CHOOSE_EFFECT}


# --- Scegli uno ---------------------------------------------------------------

def test_artificial_photosynthesis_choose_one():
    game, alice = new_game(hand=("Artificial Photosynthesis",))
    play(game, "Artificial Photosynthesis")
    assert choices(game) == {("0", None), ("1", None)}
    choose(game, 1)
    assert alice.production[PLANTS] == 1 and alice.production[ENERGY] == 0
    assert game.actions_this_turn == 1 and not game.pending_choices


def test_imported_hydrogen_without_targets_gives_plants_automatically():
    game, alice = new_game(hand=("Imported Hydrogen",))
    play(game, "Imported Hydrogen")
    game.apply(game.legal_actions()[0])              # l'oceano
    assert alice.resources[PLANTS] >= 3 and not game.pending_choices


def test_imported_hydrogen_can_feed_an_animal_card():
    game, alice = new_game(hand=("Imported Hydrogen",), in_play=("Fish", "Tardigrades"))
    play(game, "Imported Hydrogen")
    game.apply(game.legal_actions()[0])              # prima l'oceano, poi la scelta
    assert choices(game) == {("0", None), ("1", "Tardigrades"), ("2", "Fish")}
    choose(game, 2, "Fish")
    assert alice.card_resources["Fish"] == 2


def test_local_heat_trapping_spends_heat():
    game, alice = new_game(hand=("Local Heat Trapping",))
    alice.resources[HEAT] = 4
    assert not any(a.card == "Local Heat Trapping" for a in game.legal_actions())
    alice.resources[HEAT] = 5
    play(game, "Local Heat Trapping")
    assert alice.resources[HEAT] == 0 and alice.resources[PLANTS] == 4


def test_helion_cannot_pay_local_heat_trapping_with_the_reserved_heat():
    game, alice = new_game(hand=("Local Heat Trapping",))
    from tm_sim.corporations import CORPORATIONS_BY_NAME
    alice.corporation = CORPORATIONS_BY_NAME["Helion"]
    alice.resources[MC], alice.resources[HEAT] = 0, 5     # 5 calore: non basta anche per il costo
    assert not any(a.card == "Local Heat Trapping" for a in game.legal_actions())


# --- Risorse su altre carte ------------------------------------------------------

def test_imported_nitrogen_asks_where_to_put_each_resource():
    game, alice = new_game(hand=("Imported Nitrogen",),
                           in_play=("Tardigrades", "Decomposers", "Fish"))
    play(game, "Imported Nitrogen")
    assert choices(game) == {("0", "Tardigrades"), ("0", "Decomposers")}   # 3 microbi
    choose(game, 0, "Decomposers")
    assert alice.card_resources["Decomposers"] == 3
    assert alice.card_resources["Fish"] == 2         # unico bersaglio: in automatico
    assert alice.terraform_rating == 21 and alice.resources[PLANTS] == 4


def test_resources_are_lost_without_a_target():
    game, alice = new_game(hand=("Imported Nitrogen",))
    play(game, "Imported Nitrogen")
    assert not game.pending_choices and alice.resources[PLANTS] == 4


def test_ceos_favorite_project_needs_a_card_with_resources():
    game, alice = new_game(hand=("CEO's Favorite Project",), in_play=("Fish",))
    assert not any(a.card == "CEO's Favorite Project" for a in game.legal_actions())
    alice.add_card_resource("Fish", 1)
    play(game, "CEO's Favorite Project")
    assert alice.card_resources["Fish"] == 2


# --- Effetti con scelta ------------------------------------------------------------

def test_viral_enhancers_resource_or_plant():
    game, alice = new_game(hand=("Fish",), in_play=("Viral Enhancers",))
    game.state.planet.temperature = 2
    play(game, "Fish")
    assert choices(game) == {("0", None), ("1", "Fish")}       # solo sulla carta appena giocata
    choose(game, 1, "Fish")
    assert alice.card_resources["Fish"] == 1
    assert game.legal_actions()[0].type is ActionType.ATTACK  # poi l'attacco di Fish


def test_viral_enhancers_gives_plants_for_cards_without_resources():
    game, alice = new_game(hand=("Lichen",), in_play=("Viral Enhancers",))
    game.state.planet.temperature = -24
    play(game, "Lichen")
    assert alice.resources[PLANTS] == 1 and not game.pending_choices


def test_mars_university_discard_to_draw():
    game, alice = new_game(hand=("Mars University", "Lichen"), deck=("Heather",))
    play(game, "Mars University")                     # il suo tag scienza la attiva
    assert choices(game) == {("0", None), ("1", "Lichen")}
    choose(game, 1, "Lichen")
    assert [c.name for c in alice.hand] == ["Heather"]


def test_olympus_conference_adds_then_can_draw():
    game, alice = new_game(hand=("Olympus Conference", "Search For Life"), deck=("Lichen",))
    play(game, "Olympus Conference")                  # nessuna scienza: si aggiunge da sola
    assert alice.card_resources["Olympus Conference"] == 1
    play(game, "Search For Life")
    choose(game, 1)                                   # togli la scienza e pesca
    assert alice.card_resources["Olympus Conference"] == 0 and alice.hand[0].name == "Lichen"


def test_business_contacts_keep_two_of_four():
    game, alice = new_game(hand=("Business Contacts",),
                           deck=("Lichen", "Heather", "Fish", "Birds"))
    play(game, "Business Contacts")
    keep = [a for a in game.legal_actions() if a.type is ActionType.KEEP_CARD]
    assert len(keep) == 4
    game.apply(Action(ActionType.KEEP_CARD, "Fish"))
    game.apply(Action(ActionType.KEEP_CARD, "Birds"))
    assert {c.name for c in alice.hand} == {"Fish", "Birds"}
    assert {c.name for c in game.discard_pile} == {"Lichen", "Heather"}
    assert not game.revealed


# --- Il bot e le combo -------------------------------------------------------------

def test_bot_puts_animals_where_they_score():
    game, alice = new_game(hand=("Imported Hydrogen",), in_play=("Fish", "Tardigrades"))
    play(game, "Imported Hydrogen")
    game.apply(game.legal_actions()[0])
    assert RuleBot(1).choose(game, game.legal_actions()).option == "Fish"


def test_bot_waits_more_with_a_target_in_hand():
    game, alice = new_game(hand=("Imported Nitrogen", "Fish"))
    game.state.planet.temperature, game.state.generation = -4, 4
    nitrogen = CARDS_BY_NAME["Imported Nitrogen"]
    with_fish = h.combo_wait_value(game, alice, nitrogen)
    alice.hand = [nitrogen]
    alone = h.combo_wait_value(game, alice, nitrogen)
    assert with_fish > alone > 0
    assert h.combo_wait_value(game, alice, nitrogen, patience=0, hope=0) == 0


def test_no_waiting_when_the_target_is_already_in_play():
    game, alice = new_game(hand=("Large Convoy",), in_play=("Fish",))
    game.state.generation = 4
    assert h.combo_wait_value(game, alice, CARDS_BY_NAME["Large Convoy"]) == 0


def test_target_card_is_worth_more_with_feeders_in_hand():
    game, alice = new_game(hand=("Fish",))
    game.state.planet.temperature = 2
    fish = CARDS_BY_NAME["Fish"]
    alone = h.card_value(game, alice, fish)
    alice.hand.append(CARDS_BY_NAME["Imported Nitrogen"])
    assert h.card_value(game, alice, fish) > alone
