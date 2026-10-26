"""Test del draft nella fase di ricerca."""

from tm_sim.actions import Action, ActionType
from tm_sim.bots import RandomBot, RuleBot
from tm_sim.card_list import CARDS_BY_NAME
from tm_sim.game import Game, Phase, Setup
from tm_sim.state import Resource

MC = Resource.MEGACREDITS

NAMES = ["Lichen", "Heather", "Mine", "Comet", "Fish", "Birds", "Space Station", "Satellites",
         "Ants", "Moss", "Insects", "Worms"]


def research_game(n_players: int = 3, draft: bool = True) -> Game:
    """Partita appena entrata nella fase di ricerca della generazione 2, con un mazzo noto."""
    game = Game(["Anna", "Bruno", "Carla"][:n_players], cards=[], draft=draft)
    game.deck = [CARDS_BY_NAME[n] for n in reversed(NAMES)]      # si pesca dalla fine
    for p in game.state.players:
        p.hand = []
        p.resources[Resource.MEGACREDITS] = 50
    game._start_research()
    return game


def pick(game: Game, card: str) -> None:
    game.apply(Action(ActionType.DRAFT_CARD, card))


def test_everyone_sees_four_cards_first():
    game = research_game()
    assert game.phase is Phase.RESEARCH and game.drafting
    assert [c.name for c in game.state.players[0].draft_hand] == NAMES[0:4]
    assert [c.name for c in game.state.players[1].draft_hand] == NAMES[4:8]
    assert {a.type for a in game.legal_actions()} == {ActionType.DRAFT_CARD}


def test_cards_pass_to_the_left_after_everyone_picked():
    game = research_game()
    anna, bruno, carla = game.state.players
    pick(game, "Lichen")                     # Anna tiene Lichen
    pick(game, "Fish")                       # Bruno tiene Fish
    pick(game, "Ants")                       # Carla tiene Ants
    # Le 3 carte rimaste ad Anna passano a Bruno, quelle di Carla ad Anna.
    assert [c.name for c in bruno.draft_hand] == ["Heather", "Mine", "Comet"]
    assert [c.name for c in anna.draft_hand] == ["Moss", "Insects", "Worms"]
    assert len(carla.draft_hand) == 3


def test_after_four_picks_each_player_decides_what_to_buy():
    game = research_game()
    bots = {p.name: RandomBot(i) for i, p in enumerate(game.state.players)}
    picks = 0
    while game.drafting:
        game.apply(bots[game.current_player.name].choose(game, game.legal_actions()))
        picks += 1
    assert picks == 12                                       # 4 scelte a testa
    assert all(len(p.drafted) == 4 for p in game.state.players)
    assert {a.type for a in game.legal_actions()} == {ActionType.BUY_CARDS}
    seen = sorted(c.name for p in game.state.players for c in p.drafted)
    assert seen == sorted(NAMES)                             # nessuna carta persa o duplicata


def test_two_players_pass_to_each_other():
    game = research_game(n_players=2)
    anna, bruno = game.state.players
    pick(game, "Lichen")
    pick(game, "Fish")
    assert [c.name for c in anna.draft_hand] == ["Birds", "Space Station", "Satellites"]


def test_without_draft_nothing_changes():
    game = research_game(draft=False)
    assert not game.drafting
    assert len(game.state.players[0].drafted) == 4
    assert {a.type for a in game.legal_actions()} == {ActionType.BUY_CARDS}


def test_bot_keeps_the_card_it_most_wants_to_buy():
    game = research_game()
    game.state.planet.temperature = 2                        # Fish e Birds giocabili presto
    choice = RuleBot(1).choose(game, game.legal_actions())
    from tm_sim import heuristics as h
    anna = game.state.players[0]
    best = max(anna.draft_hand, key=lambda c: h.buy_value(game, anna, c))
    assert choice.card == best.name


def test_full_games_with_draft():
    from simulate import play_game
    for seed in range(3):
        game = play_game({n: RuleBot(seed * 10 + i) for i, n in enumerate("ABC")}, seed,
                         Setup.PRELUDE, draft=True)
        assert game.is_over()


# --- Acquisto delle carte: tutte insieme ------------------------------------

def test_buying_is_one_decision_over_all_the_cards():
    game = research_game(draft=False)
    player = game.current_player
    names = [c.name for c in player.drafted]
    actions = game.legal_actions()
    assert len(actions) == 16                                # tutti i gruppi di 4 carte
    assert {frozenset(a.cards) for a in actions} == {
        frozenset(n for i, n in enumerate(names) if mask >> i & 1) for mask in range(16)}
    money = player.resources[MC]
    game.apply(Action(ActionType.BUY_CARDS, cards=(names[1], names[3])))
    assert [c.name for c in player.hand[-2:]] == [names[1], names[3]]
    assert player.resources[MC] == money - 6 and not player.drafted
    assert names[0] in [c.name for c in game.discard_pile]


def test_only_affordable_groups_are_offered():
    game = research_game(draft=False)
    player = game.current_player
    player.resources[MC] = 7                                 # bastano per 2 carte
    sizes = {len(a.cards) for a in game.legal_actions()}
    assert sizes == {0, 1, 2}


def test_bot_buys_the_best_cards_when_money_is_short():
    """Con soldi per una carta sola, il bot sceglie la migliore, non la prima che vede."""
    game = research_game(draft=False)
    player = game.current_player
    player.resources[MC] = 3
    bot = RuleBot(1)
    action = bot.choose(game, game.legal_actions())
    from tm_sim import heuristics as h
    values = {c.name: h.buy_value(game, player, c) for c in player.drafted}
    best = max(values, key=values.get)
    assert action.cards in ((), (best,))
    if values[best] > 0:
        assert action.cards == (best,)


def test_bot_values_cards_together():
    """Fish vale di più se nello stesso gruppo c'è una carta che gli mette animali."""
    from tm_sim.card_list import CARDS_BY_NAME
    game = research_game(draft=False)
    player = game.current_player
    fish = CARDS_BY_NAME["Fish"]
    bot = RuleBot(1)
    sim, me = bot._hypothetical(game, player)
    bot._base_hand = list(me.hand)
    alone = bot._purchase_value(sim, me, fish, [], 40)
    with_feeder = bot._purchase_value(sim, me, fish, [CARDS_BY_NAME["Large Convoy"]], 40)
    assert with_feeder > alone
