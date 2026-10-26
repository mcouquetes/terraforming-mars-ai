"""Test delle statistiche: conti coerenti, classifiche, file CSV."""

import csv

from simulate import play_game
from tm_sim.bots import RuleBot
from tm_sim.stats import ItemStats, StatsCollector, margin_of_error


def collect(n_games: int = 3, n_players: int = 2) -> StatsCollector:
    stats = StatsCollector(n_players)
    for seed in range(n_games):
        names = [f"P{i}" for i in range(n_players)]
        game = play_game({name: RuleBot(seed * 10 + i) for i, name in enumerate(names)}, seed)
        stats.add_game(game, seed)
    return stats


def test_margin_of_error():
    assert margin_of_error(0, 0) == 0
    assert round(margin_of_error(50, 100), 1) == 9.8        # 1,96 × √(0,25/100) = 9,8 punti
    assert margin_of_error(500, 1000) < margin_of_error(50, 100)   # più partite, meno incertezza


def test_one_row_per_player_per_game():
    stats = collect(n_games=3, n_players=3)
    assert len(stats.rows) == 9
    assert sum(r["vittoria"] for r in stats.rows) == 3      # una vittoria (divisa) per partita


def test_counts_are_consistent():
    stats = collect()
    for (kind, _), item in stats.items.items():
        if kind == "carta":
            assert item.offered >= item.bought                # si compra solo ciò che è offerto
        assert 0 <= item.wins <= item.played


def test_corporations_are_counted_once_per_player():
    stats = collect(n_games=4, n_players=2)
    assert sum(i.played for (k, _), i in stats.items.items() if k == "corporazione") == 8


def test_bought_but_not_played():
    item = ItemStats("Prova", "carta", bought=4, played=1, bought_not_played=3,
                     wins_bought_not_played=1.0)
    assert round(item.win_rate_unplayed(), 1) == 33.3
    assert item.play_rate() == 25.0


def test_advantage_compares_with_expected_win_rate():
    stats = StatsCollector(n_players=4)
    item = ItemStats("Prova", "carta", played=10, wins=5)
    assert stats.expected_win_rate == 25
    assert stats.advantage(item) == 50 - 25


def test_ranking_is_sorted_and_filtered():
    stats = collect()
    ranking = stats.ranking("carta", min_played=1)
    rates = [i.win_rate() for i in ranking]
    assert rates == sorted(rates, reverse=True)
    assert all(i.played >= 2 for i in stats.ranking("carta", min_played=2))


def test_csv_files(tmp_path):
    stats = collect()
    files = stats.write_csv(tmp_path)
    assert {f.name for f in files} == {"carte.csv", "preludi.csv", "corporazioni.csv",
                                       "giocatori.csv"}
    with (tmp_path / "carte.csv").open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert rows and "vantaggio" in rows[0] and "margine" in rows[0]
