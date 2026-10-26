"""Test della potenza delle carte (regressione) e delle correzioni del bot."""

import json
import random

from tm_sim.actions import Action, ActionType
from tm_sim.bots import RuleBot, load_corrections
from tm_sim.card_list import CARDS_BY_NAME
from tm_sim.card_power import PlayerRecord, fit
from tm_sim.game import Game

TRUE_POWER = {"Forte": 6.0, "Media": 0.0, "Debole": -6.0}


def synthetic_records(n_games: int = 600, seed: int = 1) -> list[PlayerRecord]:
    """Partite inventate in cui conosciamo la verità: ogni carta vale TRUE_POWER punti,
    più del rumore. Le carte "Forte" le gioca più spesso chi è già avanti (contesto!)."""
    rng = random.Random(seed)
    records = []
    for g in range(n_games):
        for seat in (1, 2):
            skill = rng.gauss(0, 5)                   # bravura/fortuna: il "contesto"
            cards = [c for c in TRUE_POWER if rng.random() < 0.5]
            if skill > 3 and "Forte" not in cards:    # chi è avanti gioca più spesso Forte
                cards.append("Forte")
            score = 60 + skill + sum(TRUE_POWER[c] for c in cards) + rng.gauss(0, 3)
            expected = 3.0 if "Debole" in cards else 0.0    # il bot sopravvaluta Debole di 3
            records.append(PlayerRecord(f"g{g}", seat, "Corp", [], cards, score, expected))
    return records


def test_regression_finds_the_true_power_order():
    table = fit(synthetic_records())
    power = {e.name: e.power for e in table.entries if e.kind == "carta"}
    assert power["Forte"] > power["Media"] > power["Debole"]
    # Differenza vera tra Forte e Debole: 12 punti. La stima è un po' più alta,
    # perché Forte la gioca più spesso chi è già avanti: il contesto che resta.
    assert 10 < power["Forte"] - power["Debole"] < 16


def test_corrections_detect_an_overrated_card():
    table = fit(synthetic_records())
    correction = {e.name: e.correction for e in table.entries if e.kind == "carta"}
    assert correction["Debole"] < correction["Media"] - 1.5      # il bot la sopravvaluta


def test_rare_cards_are_shrunk_towards_average():
    records = synthetic_records(300)
    records.append(PlayerRecord("rara", 1, "Corp", [], ["Rara"], 120, 0))   # 1 sola volta, enorme
    records.append(PlayerRecord("rara", 2, "Corp", [], [], 60, 0))
    table = fit(records)
    rare = next(e for e in table.entries if e.name == "Rara")
    common = next(e for e in table.entries if e.name == "Media")
    assert rare.power < 30                                # prudente: lo scarto osservato era 60
    assert rare.margin > 2 * common.margin                # e molto più incerta


def test_save_and_load_corrections(tmp_path):
    table = fit(synthetic_records(200))
    json_path, csv_path = table.save(tmp_path)
    loaded = load_corrections(json_path)
    assert set(loaded) >= {"Forte", "Media", "Debole"}
    assert "potenza_pv" in csv_path.read_text(encoding="utf-8-sig")
    assert json.loads(json_path.read_text(encoding="utf-8"))["giocatori_registrati"] == 400


def test_bot_uses_corrections():
    game = Game(["Alice", "Bob"], cards=[])
    alice = game.state.players[0]
    alice.hand = [CARDS_BY_NAME["Mine"]]
    alice.resources[next(iter(alice.resources))] = 50
    action = Action(ActionType.PLAY_CARD, "Mine")
    base = RuleBot(1).base_score(game, alice, action)
    boosted = RuleBot(1, card_power={"Mine": 2.0}).base_score(game, alice, action)
    halved = RuleBot(1, card_power={"Mine": 2.0}, power_weight=0.5).base_score(game, alice, action)
    assert boosted > halved > base


def test_learning_game_records_expectations():
    from learn import play_learning_game
    from tm_sim.game import Setup
    records = play_learning_game(1, seed=3, n_players=2, setup=Setup.PRELUDE, corrections={})
    assert len(records) == 2
    assert all(r.corporation and r.cards for r in records)
    assert any(r.expected != 0 for r in records)


# --- Ripartire da ciò che si è imparato ---------------------------------------

def test_prior_keeps_old_knowledge_when_new_data_is_scarce():
    few = synthetic_records(5)                       # pochissimi dati nuovi
    prior = {"Debole": -5.0, "Forte": 4.0, "Media": 0.0}
    with_prior = {e.name: e.correction for e in fit(few, prior=prior).entries}
    without = {e.name: e.correction for e in fit(few).entries}
    assert with_prior["Debole"] < without["Debole"]  # resta vicino a ciò che sapevamo


def test_find_corrections_prefers_progress_then_shipped_then_nearest(tmp_path, monkeypatch):
    from tm_sim import card_power
    shipped = tmp_path / "dati"
    shipped.mkdir()
    monkeypatch.setattr(card_power, "SHIPPED_FOLDER", shipped)
    learned = tmp_path / "apprendimento"
    learned.mkdir()
    assert card_power.find_corrections(2, learned) is None
    (shipped / "correzioni_2_giocatori.json").write_text('{"correzioni": {}}')
    assert card_power.find_corrections(2, learned).parent == shipped
    card_power.latest_file(2, learned).write_text('{"correzioni": {}}')
    assert card_power.find_corrections(2, learned).parent == learned       # i progressi vincono
    assert card_power.find_corrections(4, learned) is None
    assert card_power.find_nearest_corrections(4, learned) == card_power.latest_file(2, learned)
