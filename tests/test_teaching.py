"""Le lezioni dell'umano: accoppiate, mani "truccate", regressione e bonus del bot."""

import random

from tm_sim.bots import RuleBot, load_pairs
from tm_sim.card_list import CARDS_BY_NAME
from tm_sim.card_power import PlayerRecord, fit
from tm_sim.game import Game, Setup
from tm_sim.teaching import (
    EXPLICIT_HINT,
    INFERRED_HINT,
    hypotheses,
    load_lessons,
    make_lesson,
    pair_key,
    plant_pair,
    save_lessons,
    split_pair,
)


def test_pair_key_is_order_independent():
    assert pair_key("Fish", "Large Convoy") == pair_key("Large Convoy", "Fish") == "Fish + Large Convoy"
    assert split_pair("Fish + Large Convoy") == ("Fish", "Large Convoy")


def test_lessons_become_hypotheses(tmp_path):
    offer = {"corporazioni": [], "preludi": [], "carte": []}
    explicit = make_lesson(1, offer, {"corporazione": "EcoLine", "preludi": [], "carte": ["Fish"]},
                           {"corporazione": "EcoLine", "preludi": [], "carte": []},
                           [pair_key("Fish", "Large Convoy")])
    inferred = make_lesson(2, offer, {"corporazione": "EcoLine", "preludi": [], "carte": ["Lichen", "Fish"]},
                           {"corporazione": "EcoLine", "preludi": [], "carte": ["Fish"]}, [])
    assert inferred["coppie_dedotte"] == [pair_key("EcoLine", "Lichen")]   # solo quella "mia"
    path = tmp_path / "lezioni.json"
    save_lessons([explicit, inferred], path)
    hints = hypotheses(load_lessons(path))
    assert hints == {"Fish + Large Convoy": EXPLICIT_HINT, "EcoLine + Lichen": INFERRED_HINT}


def test_repeated_pairs_get_more_trust_but_capped():
    lesson = {"coppie": ["Fish + Large Convoy"], "coppie_dedotte": []}
    assert hypotheses([lesson] * 2)["Fish + Large Convoy"] == EXPLICIT_HINT * 1.25
    assert hypotheses([lesson] * 20)["Fish + Large Convoy"] == 2 * EXPLICIT_HINT


def all_names(game):
    names = [c.name for c in game.deck + game.discard_pile]
    for p in game.state.players:
        names += [c.name for c in p.drafted + p.hand]
    return sorted(names)


def test_planting_puts_the_pair_in_the_offer_without_losing_cards():
    for seed in range(5):
        game = Game(["A", "B"], seed=seed, setup=Setup.PRELUDE, draft=True)
        before = all_names(game)
        corps_before = sorted(c.name for c in game.corporation_deck) + sorted(
            c.name for p in game.state.players for c in p.corporation_choices)
        player = game.state.players[1]
        assert plant_pair(game, player, pair_key("EcoLine", "Arctic Algae"), random.Random(seed))
        assert [c.name for c in player.corporation_choices] == ["EcoLine"]   # unica scelta
        assert "Arctic Algae" in [c.name for c in player.drafted]
        assert len(player.drafted) == 10
        assert all_names(game) == before                                     # niente perso
        corps_after = sorted(c.name for c in game.corporation_deck) + sorted(
            c.name for p in game.state.players for c in p.corporation_choices)
        assert sorted(corps_after) == sorted(corps_before)


def test_planting_two_cards_keeps_both():
    game = Game(["A", "B"], seed=3, setup=Setup.PRELUDE, draft=True)
    player = game.state.players[0]
    plant_pair(game, player, pair_key("Fish", "Large Convoy"), random.Random(1))
    names = [c.name for c in player.drafted]
    assert "Fish" in names and "Large Convoy" in names


def test_regression_finds_a_real_synergy():
    """Dati finti: chi gioca A e B insieme fa 6 punti in più; A e B da sole niente."""
    rng = random.Random(0)
    records = []
    for g in range(1500):
        for seat in (1, 2):
            cards = [c for c in ("A", "B", "C", "D") if rng.random() < 0.5]
            score = 50 + rng.gauss(0, 3) + (6 if "A" in cards and "B" in cards else 0)
            records.append(PlayerRecord(f"g{g}", seat, "", [], cards, score))
    table = fit(records, pairs={"A + B": 0.0, "C + D": 0.0})
    pairs = {e.name: e for e in table.entries if e.kind == "coppia"}
    # La regressione è prudente (ridge): sottostima un po', ma la sinergia è chiara.
    assert 4.0 < pairs["A + B"].power < 7.0 and pairs["A + B"].power > pairs["A + B"].margin
    assert abs(pairs["C + D"].power) < pairs["C + D"].margin
    assert 4.0 < table.pair_corrections()["A + B"] < 7.0


def test_untested_pairs_keep_their_starting_value():
    records = [PlayerRecord("g", s, "", [], ["A"], 50.0 + s) for s in (1, 2)]
    table = fit(records, pairs={"X + Y": 2.5})
    assert table.pair_corrections() == {"X + Y": 2.5}


def test_bot_pair_bonus_full_if_played_half_if_in_hand():
    game = Game(["A", "B"], seed=1, setup=Setup.STANDARD)
    player = game.state.players[0]
    bot = RuleBot(1, pair_power={"Fish + Large Convoy": 2.0})
    assert bot.pair_bonus(game, player, "Fish") == 0.0
    player.hand.append(CARDS_BY_NAME["Large Convoy"])
    half = bot.pair_bonus(game, player, "Fish")
    player.hand.pop()
    player.played.append(CARDS_BY_NAME["Large Convoy"])
    full = bot.pair_bonus(game, player, "Fish")
    assert half > 0 and abs(full - 2 * half) < 1e-9
    assert bot.correction(game, "Fish", player) == full          # entra nelle valutazioni
    assert bot.correction(game, "Fish") == 0.0                   # senza giocatore: niente


def test_pairs_are_saved_and_loaded(tmp_path):
    records = [PlayerRecord("g", s, "", [], ["A", "B"], 50.0 + s) for s in (1, 2)]
    table = fit(records, pairs={"A + B": 1.0})
    json_path, _ = table.save(tmp_path)
    assert "A + B" in load_pairs(json_path)
    bot = RuleBot(1, card_power=str(json_path))
    assert bot.pairs["A"][0][0] == "B" or not bot.pairs     # (0 = nessun bonus: non serve)


def test_learning_game_with_planted_pairs_runs():
    from learn import play_learning_game
    records = play_learning_game(1, 5, 2, Setup.PRELUDE, {}, True, 0.0,
                                 {"EcoLine + Arctic Algae": 3.0}, ["EcoLine + Arctic Algae"], 1.0)
    # Una corporazione esiste in una copia sola: la riceve uno dei due giocatori.
    assert [r.corporation for r in records].count("EcoLine") == 1
