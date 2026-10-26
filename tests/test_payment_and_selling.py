"""Test della scelta del pagamento, dei riconoscimenti da difendere e della vendita di brevetti."""

from tm_sim import heuristics as h
from tm_sim.actions import PAY_NO_METALS, PAY_NO_STEEL, PAY_NO_TITANIUM, Action, ActionType
from tm_sim.bots import RuleBot
from tm_sim.card_list import CARDS_BY_NAME
from tm_sim.game import Game
from tm_sim.milestones import points_from_scores
from tm_sim.state import MAX_OXYGEN, MAX_TEMPERATURE, Resource

MC, STEEL, TITANIUM, HEAT = (Resource.MEGACREDITS, Resource.STEEL, Resource.TITANIUM,
                             Resource.HEAT)


def new_game(hand: tuple[str, ...] = (), in_play: tuple[str, ...] = (), players: int = 2):
    game = Game(["Alice", "Bob", "Carla"][:players], cards=[])
    alice = game.state.players[0]
    alice.hand = [CARDS_BY_NAME[c] for c in hand]
    alice.played = [CARDS_BY_NAME[c] for c in in_play]
    return game, alice


def plays(game: Game, card: str) -> list[Action]:
    return [a for a in game.legal_actions() if a.type is ActionType.PLAY_CARD and a.card == card]


def near_the_end(game: Game) -> None:
    """Manca un solo oceano: è l'ultima generazione (secondo le stime del bot)."""
    planet = game.state.planet
    planet.temperature, planet.oxygen, planet.oceans = MAX_TEMPERATURE, MAX_OXYGEN, 8


# --- Scelta del pagamento ---------------------------------------------------

def test_building_card_can_be_paid_with_or_without_steel():
    game, alice = new_game(hand=("Mine",))
    alice.resources[MC], alice.resources[STEEL] = 10, 2
    assert {a.payment for a in plays(game, "Mine")} == {None, PAY_NO_METALS}
    game.apply(Action(ActionType.PLAY_CARD, "Mine", payment=PAY_NO_METALS))
    assert alice.resources[STEEL] == 2 and alice.resources[MC] == 6


def test_paying_with_metals_is_still_the_default():
    game, alice = new_game(hand=("Mine",))
    alice.resources[MC], alice.resources[STEEL] = 10, 2
    game.apply(Action(ActionType.PLAY_CARD, "Mine"))
    assert alice.resources[STEEL] == 0 and alice.resources[MC] == 10


def test_no_choice_without_metals_or_without_enough_money():
    game, alice = new_game(hand=("Mine",))
    alice.resources[MC] = 10
    assert [a.payment for a in plays(game, "Mine")] == [None]          # niente acciaio
    alice.resources[MC], alice.resources[STEEL] = 1, 2
    assert [a.payment for a in plays(game, "Mine")] == [None]          # senza acciaio non basta


def test_card_with_both_tags_offers_every_combination():
    game, alice = new_game(hand=("Space Elevator",))
    alice.resources[MC], alice.resources[STEEL], alice.resources[TITANIUM] = 30, 3, 3
    assert {a.payment for a in plays(game, "Space Elevator")} == {
        None, PAY_NO_METALS, PAY_NO_STEEL, PAY_NO_TITANIUM}
    game.apply(Action(ActionType.PLAY_CARD, "Space Elevator", payment=PAY_NO_TITANIUM))
    assert alice.resources[TITANIUM] == 3 and alice.resources[STEEL] == 0


def test_card_actions_can_be_paid_without_metals():
    game, alice = new_game(in_play=("Aquifer Pumping",))
    alice.resources[MC], alice.resources[STEEL] = 20, 4
    options = {a.payment for a in game.legal_actions() if a.card == "Aquifer Pumping"}
    assert options == {None, PAY_NO_METALS}
    game.apply(Action(ActionType.CARD_ACTION, "Aquifer Pumping", target="0", payment=PAY_NO_METALS))
    assert alice.resources[STEEL] == 4 and alice.resources[MC] == 12


# --- Riconoscimenti da difendere --------------------------------------------

def test_points_from_scores():
    assert points_from_scores({"A": 5, "B": 3}) == {"A": 5, "B": 0}
    assert points_from_scores({"A": 5, "B": 5}) == {"A": 5, "B": 5}
    assert points_from_scores({"A": 5, "B": 3, "C": 1}) == {"A": 5, "B": 2, "C": 0}


def test_award_loss_only_when_spending_costs_the_award():
    game, alice = new_game()
    bob = game.state.players[1]
    near_the_end(game)
    alice.resources[STEEL], bob.resources[STEEL] = 5, 4
    assert h.award_loss(game, alice, {STEEL: 2}) == 0       # Miner non finanziato
    game.state.funded_awards.append("Miner")
    assert h.award_loss(game, alice, {STEEL: 2}) > 0        # 3 contro 4: Bob vincerebbe
    bob.resources[STEEL] = 0
    assert h.award_loss(game, alice, {STEEL: 2}) == 0       # resto prima comunque


def test_award_is_ignored_far_from_the_end():
    game, alice = new_game()
    game.state.funded_awards.append("Miner")
    alice.resources[STEEL], game.state.players[1].resources[STEEL] = 5, 4
    assert h.award_loss(game, alice, {STEEL: 2}) == 0       # inizio partita: troppo presto


def test_bot_keeps_steel_to_win_miner():
    game, alice = new_game(hand=("Mine",))
    near_the_end(game)
    game.state.funded_awards.append("Miner")
    alice.resources[MC], alice.resources[STEEL] = 10, 2
    game.state.players[1].resources[STEEL] = 1
    bot = RuleBot(1)
    paid_with_steel = Action(ActionType.PLAY_CARD, "Mine")
    kept_steel = Action(ActionType.PLAY_CARD, "Mine", payment=PAY_NO_METALS)
    assert bot.score(game, alice, kept_steel) > bot.score(game, alice, paid_with_steel)


def test_bot_keeps_heat_to_win_thermalist():
    game, alice = new_game()
    near_the_end(game)
    game.state.planet.temperature = MAX_TEMPERATURE - 2     # c'è ancora un grado da alzare
    alice.resources[HEAT] = 10
    game.state.players[1].resources[HEAT] = 5
    bot = RuleBot(1)
    convert = Action(ActionType.CONVERT_HEAT)
    assert bot.base_score(game, alice, convert) == bot.ALWAYS_GOOD   # nessun riconoscimento
    game.state.funded_awards.append("Thermalist")
    assert bot.base_score(game, alice, convert) < 0      # 2 contro 5: perderei Thermalist


# --- Vendita di brevetti -----------------------------------------------------

def test_selling_patents_one_card_at_a_time():
    game, alice = new_game(hand=("Mine", "Lichen", "Heather"))
    alice.resources[MC] = 0
    game.apply(Action(ActionType.SELL_PATENTS))
    choices = game.legal_actions()
    assert {a.type for a in choices} == {ActionType.SELL_CARD}       # almeno una carta
    game.apply(Action(ActionType.SELL_CARD, "Lichen"))
    assert ActionType.STOP_SELLING in {a.type for a in game.legal_actions()}
    game.apply(Action(ActionType.SELL_CARD, "Heather"))
    game.apply(Action(ActionType.STOP_SELLING))
    assert [c.name for c in alice.hand] == ["Mine"]
    assert alice.resources[MC] == 2
    assert game.actions_this_turn == 1                              # una sola azione in tutto
    assert {c.name for c in game.discard_pile} == {"Lichen", "Heather"}
    assert ("Alice", "Lichen", "venduta", 1) in game.card_log


def test_selling_the_last_card_ends_the_sale():
    game, alice = new_game(hand=("Mine",))
    game.apply(Action(ActionType.SELL_PATENTS))
    game.apply(Action(ActionType.SELL_CARD, "Mine"))
    assert not game.selling and not alice.hand
    assert ActionType.END_TURN in {a.type for a in game.legal_actions()}


def test_no_selling_with_an_empty_hand():
    game, _ = new_game()
    assert ActionType.SELL_PATENTS not in {a.type for a in game.legal_actions()}


def test_bot_sells_useless_cards_to_play_a_great_one():
    # Arctic Algae vuole temperatura ≤ -12 °C, e qui fa già 0 °C: non si giocherà mai.
    game, alice = new_game(hand=("Lake Marineris", "Arctic Algae"))
    game.state.planet.temperature = 0                  # Lake Marineris (2 oceani) si può giocare
    price = game.card_cost(alice, CARDS_BY_NAME["Lake Marineris"])
    alice.resources[MC] = price - 1                     # manca 1 M€
    plan = h.sell_plan(game, alice)
    assert plan is not None and plan[0] == ["Arctic Algae"]
    bot = RuleBot(1)
    assert bot.choose(game, game.legal_actions()) == Action(ActionType.SELL_PATENTS)


def test_bot_does_not_sell_without_a_reason():
    game, alice = new_game(hand=("Arctic Algae",))
    game.state.planet.temperature = 0
    alice.resources[MC] = 5
    assert h.sell_plan(game, alice) is None             # non serve a giocare niente


def test_bot_sells_everything_in_the_last_generation():
    game, alice = new_game(hand=("Mine", "Arctic Algae"))
    planet = game.state.planet
    planet.temperature, planet.oxygen, planet.oceans = MAX_TEMPERATURE, MAX_OXYGEN, 9
    alice.resources[MC] = 0                             # non può più giocare niente
    plan = h.sell_plan(game, alice)
    assert plan is not None and set(plan[0]) == {"Mine", "Arctic Algae"}
    bot = RuleBot(1)
    assert bot.choose(game, game.legal_actions()) == Action(ActionType.SELL_PATENTS)
    game.apply(Action(ActionType.SELL_PATENTS))
    while game.selling:
        game.apply(bot.choose(game, game.legal_actions()))
    assert not alice.hand and alice.resources[MC] == 2
