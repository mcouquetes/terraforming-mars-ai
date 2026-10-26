"""Test di traguardi e riconoscimenti."""

import pytest

from tm_sim.actions import Action, ActionType
from tm_sim.card_list import ALL_CARDS
from tm_sim.game import Game
from tm_sim.milestones import AWARDS_BY_NAME, award_points
from tm_sim.state import Player, Resource


def new_game(*names: str) -> Game:
    return Game(list(names) or ["Alice", "Bob"], cards=[])


def claim(game: Game, name: str) -> None:
    game.apply(Action(ActionType.CLAIM_MILESTONE, target=name))


def fund(game: Game, name: str) -> None:
    game.apply(Action(ActionType.FUND_AWARD, target=name))


def legal_targets(game: Game, action_type: ActionType) -> set[str]:
    return {a.target for a in game.legal_actions() if a.type is action_type}


# --- Traguardi -----------------------------------------------------------------

def test_milestone_not_available_until_reached():
    game = new_game()
    assert "Gardener" not in legal_targets(game, ActionType.CLAIM_MILESTONE)
    game.current_player.greeneries = 3
    assert "Gardener" in legal_targets(game, ActionType.CLAIM_MILESTONE)


def test_claiming_a_milestone_costs_8_and_gives_5_points():
    game = new_game()
    alice = game.current_player
    alice.greeneries = 3
    before = game.score(alice)
    claim(game, "Gardener")
    assert alice.resources[Resource.MEGACREDITS] == 42 - 8
    assert game.score(alice) == before + 5
    assert game.state.claimed_milestones == {"Gardener": "Alice"}


def test_a_milestone_can_be_claimed_only_once():
    game = new_game()
    alice, bob = game.state.players
    alice.greeneries = bob.greeneries = 3
    claim(game, "Gardener")
    game.apply(Action(ActionType.END_TURN))
    assert "Gardener" not in legal_targets(game, ActionType.CLAIM_MILESTONE)


def test_only_three_milestones_per_game():
    game = new_game()
    alice, bob = game.state.players
    alice.greeneries = 3
    alice.cities = 3
    alice.terraform_rating = 35
    bob.greeneries = 3  # ininfluente: Gardener sarà già preso
    bob.hand = ALL_CARDS[:16]  # 16 carte in mano per Planner
    claim(game, "Gardener")
    claim(game, "Mayor")
    claim(game, "Planner")  # turno di Bob
    assert len(game.state.claimed_milestones) == 3
    game.apply(Action(ActionType.END_TURN))
    assert legal_targets(game, ActionType.CLAIM_MILESTONE) == set()  # Terraformer non più disponibile


def test_cannot_claim_without_money():
    game = new_game()
    alice = game.current_player
    alice.greeneries = 3
    alice.spend(Resource.MEGACREDITS, 35)  # restano 7
    assert legal_targets(game, ActionType.CLAIM_MILESTONE) == set()


# --- Riconoscimenti ----------------------------------------------------------------

def test_award_costs_grow_8_14_20():
    game = new_game()
    alice = game.current_player
    alice.gain(Resource.MEGACREDITS, 100)
    fund(game, "Banker")
    assert alice.resources[Resource.MEGACREDITS] == 142 - 8
    fund(game, "Miner")
    assert alice.resources[Resource.MEGACREDITS] == 142 - 8 - 14
    assert game.next_award_cost() == 20


def test_only_three_awards_per_game():
    game = new_game()
    for player in game.state.players:
        player.gain(Resource.MEGACREDITS, 100)
    fund(game, "Banker")
    fund(game, "Miner")
    fund(game, "Scientist")   # Bob
    assert game.next_award_cost() is None
    assert legal_targets(game, ActionType.FUND_AWARD) == set()


def test_anyone_can_fund_an_award_even_if_losing_it():
    game = new_game()
    alice, bob = game.state.players
    bob.change_production(Resource.MEGACREDITS, 5)
    assert "Banker" in legal_targets(game, ActionType.FUND_AWARD)
    fund(game, "Banker")
    assert game.score(bob) == bob.victory_points() + 5
    assert game.score(alice) == alice.victory_points()


def test_award_tie_for_first_gives_5_to_everyone_tied():
    a, b, c = Player("A"), Player("B"), Player("C")
    a.gain(Resource.HEAT, 10)
    b.gain(Resource.HEAT, 10)
    c.gain(Resource.HEAT, 3)
    points = award_points(AWARDS_BY_NAME["Thermalist"], [a, b, c])
    assert points == {"A": 5, "B": 5, "C": 0}   # niente secondo posto


def test_award_second_place_with_three_players():
    a, b, c = Player("A"), Player("B"), Player("C")
    a.gain(Resource.HEAT, 10)
    b.gain(Resource.HEAT, 5)
    c.gain(Resource.HEAT, 5)
    points = award_points(AWARDS_BY_NAME["Thermalist"], [a, b, c])
    assert points == {"A": 5, "B": 2, "C": 2}


def test_no_second_place_with_two_players():
    a, b = Player("A"), Player("B")
    a.gain(Resource.HEAT, 10)
    b.gain(Resource.HEAT, 5)
    points = award_points(AWARDS_BY_NAME["Thermalist"], [a, b])
    assert points == {"A": 5, "B": 0}


@pytest.mark.parametrize("award, setup", [
    ("Landlord", lambda p: setattr(p, "cities", 2)),
    ("Banker", lambda p: p.change_production(Resource.MEGACREDITS, 1)),
    ("Thermalist", lambda p: p.gain(Resource.HEAT, 1)),
    ("Miner", lambda p: p.gain(Resource.TITANIUM, 1)),
])
def test_each_award_measures_the_right_thing(award, setup):
    a, b = Player("A"), Player("B")
    setup(a)
    assert award_points(AWARDS_BY_NAME[award], [a, b]) == {"A": 5, "B": 0}
