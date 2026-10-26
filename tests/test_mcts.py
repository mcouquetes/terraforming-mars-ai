"""Test della copia della partita e del bot MCTS."""

import random

from tm_sim.bots import RuleBot
from tm_sim.game import Game, Phase, Setup
from tm_sim.mcts import MCTSBot, determinize, evaluate


def mid_game(seed: int = 5, generation: int = 3) -> tuple[Game, dict]:
    bots = {n: RuleBot(i) for i, n in enumerate("AB")}
    game = Game(list(bots), seed=seed, setup=Setup.PRELUDE, draft=True)
    while not (game.phase is Phase.ACTION and game.state.generation == generation):
        game.apply(bots[game.current_player.name].choose(game, game.legal_actions()))
    return game, bots


def test_clone_is_independent():
    game, bots = mid_game()
    copy = game.clone()
    assert copy.card_log == [] and game.card_log    # il registro non si copia
    before = (game.move_count, game.state.planet.temperature, len(game.deck))
    for _ in range(10):
        copy.apply(bots[copy.current_player.name].choose(copy, copy.legal_actions()))
    assert (game.move_count, game.state.planet.temperature, len(game.deck)) == before
    assert copy.uid != game.uid                     # le memorie dei bot non si confondono
    assert copy.state.players[0].played[0] is game.state.players[0].played[0]   # carte condivise


def test_determinize_hides_only_what_i_cannot_see():
    game, _ = mid_game()
    me, rival = game.state.players
    my_hand = [c.name for c in me.hand]
    hidden = sorted(c.name for c in game.deck + rival.hand)
    copy = game.clone()
    determinize(copy, copy.state.players[0], random.Random(1))
    me2, rival2 = copy.state.players
    assert [c.name for c in me2.hand] == my_hand                         # la mia mano non cambia
    assert len(rival2.hand) == len(rival.hand)                           # stesse quantità
    assert sorted(c.name for c in copy.deck + rival2.hand) == hidden     # niente perso o inventato


def test_evaluate_at_the_end_is_the_score_difference():
    game, bots = mid_game()
    while not game.is_over():
        game.apply(bots[game.current_player.name].choose(game, game.legal_actions()))
    a, b = game.state.players
    assert abs(evaluate(game, a) - (game.score(a) - game.score(b))) < 0.5


def test_mcts_bot_chooses_a_legal_move_without_touching_the_game():
    game, _ = mid_game()
    bot = MCTSBot(seed=1, simulations=6, candidates=3)
    actions = game.legal_actions()
    before = (game.move_count, game.state.generation, [p.resources.copy() for p in game.state.players])
    choice = bot.choose(game, actions)
    assert choice in actions
    assert (game.move_count, game.state.generation,
            [p.resources.copy() for p in game.state.players]) == before


def test_mcts_bot_plays_a_whole_game():
    from simulate import play_game
    game = play_game({"M": MCTSBot(seed=2, simulations=4, candidates=2), "R": RuleBot(3)}, seed=7)
    assert game.is_over()


def test_fast_clone_plays_exactly_like_the_slow_copy():
    """La copia veloce deve comportarsi esattamente come la copia completa di Python."""
    for seed, generation in ((5, 3), (8, 6), (21, 2)):
        game, _ = mid_game(seed, generation)
        results = []
        for copy in (game.clone(), game.slow_clone()):
            bots = {n: RuleBot(i + 40) for i, n in enumerate("AB")}
            while not copy.is_over():
                copy.apply(bots[copy.current_player.name].choose(copy, copy.legal_actions()))
            results.append((copy.scores(), copy.move_count, len(copy.deck),
                            sorted(s.id for s in copy.state.board.spaces.values() if s.tile)))
        assert results[0] == results[1]
        assert game.state.generation == generation and not game.is_over()   # originale intatto


def test_fast_clone_shares_nothing_that_changes():
    game, _ = mid_game()
    copy = game.clone()
    for a, b in zip(game.state.players, copy.state.players):
        assert a is not b and a.resources is not b.resources and a.hand is not b.hand
        assert a.card_resources is not b.card_resources and a.used_actions is not b.used_actions
    board, board2 = game.state.board, copy.state.board
    assert all(board.spaces[k] is not board2.spaces[k] for k in board.spaces)
    some = next(iter(board2.spaces.values()))
    assert all(n is board2.spaces[n.id] for n in board2.neighbors(some))   # vicini della copia
    assert copy.deck is not game.deck and copy.rng is not game.rng
    assert copy.rng.random() == game.rng.random()                          # stesso futuro casuale


def test_smart_search_chooses_a_legal_move_and_saves_simulations_when_obvious():
    game, _ = mid_game()
    bot = MCTSBot(seed=3, simulations=20, candidates=4, smart=True)
    actions = game.legal_actions()
    choice = bot.choose(game, actions)
    assert choice in actions
    assert bot.simulations_used <= 20 * max(1, bot.searches)
