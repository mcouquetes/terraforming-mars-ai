"""Test dei bot: giocano solo mosse legali, e il bot a regole gioca sensatamente."""

from tm_sim import heuristics as h
from tm_sim.actions import Action, ActionType
from tm_sim.bots import RandomBot, RuleBot
from tm_sim.card_list import CARDS_BY_NAME
from tm_sim.game import Game, Setup
from tm_sim.state import Resource


def play_game(bots: dict, seed: int, setup: Setup = Setup.PRELUDE) -> Game:
    game = Game(list(bots), seed=seed, setup=setup)
    while not game.is_over():
        actions = game.legal_actions()
        action = bots[game.current_player.name].choose(game, actions)
        assert action in actions, "il bot ha scelto una mossa illegale"
        game.apply(action)
    return game


def test_rule_bot_finishes_games_with_2_to_5_players():
    for n in (2, 3, 4, 5):
        for seed in range(3):
            names = [f"P{i}" for i in range(n)]
            game = play_game({name: RuleBot(seed * 10 + i) for i, name in enumerate(names)}, seed)
            assert game.state.planet.is_terraformed()
            assert game.state.generation < 30            # niente partite infinite


def test_rule_bot_beats_random_bot():
    wins = 0
    for seed in range(20):
        bots = {"R": RuleBot(seed), "C": RandomBot(seed)}
        if seed % 2:
            bots = {"C": RandomBot(seed), "R": RuleBot(seed)}
        wins += "R" in play_game(bots, seed).winners()
    assert wins >= 18


def test_rule_bot_always_converts_heat_and_plants():
    game = Game(["A", "B"], cards=[])
    game.current_player.gain(Resource.HEAT, 8)
    choice = RuleBot(0).choose(game, game.legal_actions())
    assert choice.type is ActionType.CONVERT_HEAT


def test_rule_bot_claims_milestones():
    game = Game(["A", "B"], cards=[])
    game.current_player.greeneries = 3
    choice = RuleBot(0).choose(game, game.legal_actions())
    assert choice == Action(ActionType.CLAIM_MILESTONE, target="Gardener")


def test_rule_bot_prefers_production_early():
    game = Game(["A", "B"], cards=[])
    alice = game.current_player
    alice.hand = [CARDS_BY_NAME["Sponsors"], CARDS_BY_NAME["Trans-Neptune Probe"]]
    choice = RuleBot(0).choose(game, game.legal_actions())
    assert choice == Action(ActionType.PLAY_CARD, "Sponsors")   # +2 M€ di produzione


def test_rule_bot_passes_when_nothing_is_worth_it():
    game = Game(["A", "B"], cards=[])
    game.current_player.resources[Resource.MEGACREDITS] = 0
    assert RuleBot(0).choose(game, game.legal_actions()).type is ActionType.PASS


def test_random_corporation_option_still_picks_a_legal_one():
    game = Game(["A", "B"], seed=1, setup=Setup.STANDARD)
    actions = game.legal_actions()
    assert RuleBot(0, random_corporation=True).choose(game, actions) in actions


# --- Le regole di valutazione ---------------------------------------------------------

def test_production_is_worth_less_late_in_the_game():
    game = Game(["A", "B"], cards=[])
    alice = game.current_player
    early = h.production_value(game, alice, Resource.MEGACREDITS)
    planet = game.state.planet
    planet.temperature, planet.oxygen, planet.oceans = 6, 14, 9    # quasi finita
    assert h.production_value(game, alice, Resource.MEGACREDITS) < early


def test_money_is_worth_less_when_you_have_a_lot():
    game = Game(["A", "B"], cards=[])
    alice = game.current_player
    alice.resources[Resource.MEGACREDITS] = 20
    poor = h.money_value(game, alice)
    alice.resources[Resource.MEGACREDITS] = 200
    assert h.money_value(game, alice) < poor


def test_milestone_race_rewards_progress_towards_free_milestones():
    game = Game(["A", "B"], cards=[])
    alice, bob = game.state.players
    alice.cities = 2                                              # a un passo da Mayor
    alone = h.milestone_race_value(game, alice, {"cities": 1})
    assert alone > 0
    bob.cities = 2                                                # anche il rivale è vicino
    assert h.milestone_race_value(game, alice, {"cities": 1}) > alone
    game.state.claimed_milestones = {"A": "x", "B": "y", "C": "z"}  # già 3 reclamati
    assert h.milestone_race_value(game, alice, {"cities": 1}) == 0
