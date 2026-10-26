"""Ottimizzazioni (stessi risultati, più veloci) ed esplorazione di learn.py."""

import random

from tm_sim.card_list import CARDS_BY_NAME
from tm_sim.cards import Tag
from tm_sim.game import Game, Setup
from tm_sim.state import Player


def test_tag_count_updates_when_a_card_enters_play():
    player = Player("A")
    assert player.tag_count(Tag.SCIENCE) == 0
    player.played.append(CARDS_BY_NAME["Physics Complex"])          # 1 tag scienza
    assert player.tag_count(Tag.SCIENCE) == 1
    player.played.append(CARDS_BY_NAME["Research"])                 # 2 tag scienza
    assert player.tag_count(Tag.SCIENCE) == 3


def test_tag_count_of_a_copy_is_independent():
    game = Game(["A", "B"], seed=1, setup=Setup.STANDARD)
    player = game.state.players[0]
    player.played.append(CARDS_BY_NAME["Physics Complex"])
    assert player.tag_count(Tag.SCIENCE) == 1
    copy = game.clone()
    twin = copy.state.players[0]
    twin.played.append(CARDS_BY_NAME["Research"])                    # solo nella copia
    player.played.append(CARDS_BY_NAME["Power Plant"])               # solo nell'originale
    assert twin.tag_count(Tag.SCIENCE) == 3
    assert player.tag_count(Tag.SCIENCE) == 1
    assert player.tag_count(Tag.POWER) == 1 and twin.tag_count(Tag.POWER) == 0


def test_wild_tags_still_count():
    player = Player("A")
    player.played.append(CARDS_BY_NAME["Research Coordination"])     # tag jolly
    assert player.tag_count(Tag.SCIENCE) == 1
    assert player.tag_count(Tag.SCIENCE, wild=False) == 0


def test_hypothetical_copy_shares_only_the_map():
    game = Game(["A", "B"], seed=1, setup=Setup.STANDARD)
    copy = game.clone(share_board=True)
    assert copy.state.board is game.state.board
    assert copy.state.players[0] is not game.state.players[0]
    assert copy.deck is not game.deck


def test_unchecked_apply_plays_the_same_game():
    from tm_sim.bots import RuleBot
    results = []
    for check in (True, False):
        game = Game(["A", "B"], seed=4, setup=Setup.PRELUDE, draft=True)
        bots = {"A": RuleBot(1), "B": RuleBot(2)}
        while not game.is_over():
            game.apply(bots[game.current_player.name].choose(game, game.legal_actions()), check=check)
        results.append((game.scores(), game.move_count))
    assert results[0] == results[1]


def test_exploration_follows_uncertainty():
    from learn import UNSEEN_UNCERTAINTY, explored
    corrections = {"Fish": 2.0, "Birds": -1.0}
    uncertainty = {"Fish": 0.0, "Birds": 1.0}
    a = explored(corrections, uncertainty, 1.0, random.Random(1))
    b = explored(corrections, uncertainty, 1.0, random.Random(1))
    assert a == b                                       # stesso seed, stesso dubbio
    assert a["Fish"] == 2.0                             # stima certa: niente dubbio
    samples = [explored(corrections, uncertainty, 1.0, random.Random(s)) for s in range(400)]
    birds = [s["Birds"] for s in samples]
    unseen = [s["Lichen"] for s in samples]             # mai vista: dubbio grande
    assert abs(sum(birds) / len(birds) + 1.0) < 0.2
    spread = (sum(x * x for x in unseen) / len(unseen)) ** 0.5
    assert abs(spread - UNSEEN_UNCERTAINTY) < 0.3
    assert explored(corrections, uncertainty, 0.0, random.Random(1))["Birds"] == -1.0


def test_learning_game_with_exploration_runs():
    from learn import play_learning_game
    records = play_learning_game(1, 3, 2, Setup.PRELUDE, {"Fish": 1.0}, True, explore=1.0,
                                 uncertainty={"Fish": 0.5})
    assert len(records) == 2 and all(r.score > 0 for r in records)
