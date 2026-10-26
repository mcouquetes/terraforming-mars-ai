"""Test delle categorie di azioni usate dai menu."""

from tm_sim.actions import CATEGORY_OF, Action, ActionCategory, ActionType, group_by_category
from tm_sim.game import Game
from tm_sim.state import Resource


def test_every_action_type_has_a_category():
    for action_type in ActionType:
        assert action_type in CATEGORY_OF, action_type


def test_only_categories_with_actions_appear():
    game = Game(["Alice", "Bob"], cards=[])
    groups = group_by_category(game.legal_actions())
    # Senza carte, piante, calore e traguardi raggiunti:
    assert list(groups) == [
        ActionCategory.FUND_AWARD,
        ActionCategory.STANDARD_PROJECT,
        ActionCategory.TURN,
    ]


def test_standard_projects_show_only_what_you_can_afford():
    game = Game(["Alice", "Bob"], cards=[])
    alice = game.current_player
    alice.spend(Resource.MEGACREDITS, 30)  # restano 12: basta solo la centrale
    groups = group_by_category(game.legal_actions())
    assert groups[ActionCategory.STANDARD_PROJECT] == [Action(ActionType.POWER_PLANT)]


def test_conversions_appear_as_their_own_categories():
    game = Game(["Alice", "Bob"], cards=[])
    alice = game.current_player
    alice.gain(Resource.PLANTS, 8)
    alice.gain(Resource.HEAT, 8)
    groups = group_by_category(game.legal_actions())
    assert groups[ActionCategory.BUILD_GREENERY] == [Action(ActionType.CONVERT_PLANTS)]
    assert groups[ActionCategory.RAISE_TEMPERATURE] == [Action(ActionType.CONVERT_HEAT)]


def test_grouping_does_not_lose_or_add_actions():
    game = Game(["Alice", "Bob"], seed=3)
    actions = game.legal_actions()
    grouped = [a for group in group_by_category(actions).values() for a in group]
    assert sorted(map(str, grouped)) == sorted(map(str, actions))
