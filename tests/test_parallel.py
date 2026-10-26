"""Test del calcolo in parallelo: stessi risultati di un core solo."""

import os

from simulate import ChunkResult, play_chunk
from tm_sim import parallel
from tm_sim.game import Setup
from tm_sim.stats import StatsCollector


def test_never_more_than_all_cores_minus_two(monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: 8)
    assert parallel.max_processes() == 6
    assert parallel.choose_processes(None) == 6
    assert parallel.choose_processes(20) == 6
    assert parallel.choose_processes(3) == 3
    monkeypatch.setattr(os, "cpu_count", lambda: 2)
    assert parallel.choose_processes(None) == 1          # almeno uno


def test_split_seeds_keeps_every_game_once():
    chunks = parallel.split_seeds(list(range(23)), 5)
    assert [s for c in chunks for s in c] == list(range(23))
    assert len(chunks) == 5
    assert parallel.split_seeds([1, 2], 10) == [[1], [2]]


def collect(processes: int, seeds: list[int], chunks: int) -> StatsCollector:
    jobs = [(c, 3, Setup.PRELUDE, "regole", "caso", None, False)   # niente correzioni, niente draft
            for c in parallel.split_seeds(seeds, chunks)]
    total = StatsCollector(3)
    for result in parallel.run_in_parallel(play_chunk, jobs, processes):
        assert isinstance(result, ChunkResult)
        total.merge(result.stats)
    return total


def test_parallel_gives_the_same_statistics(tmp_path):
    seeds = list(range(8))
    serial = collect(1, seeds, 1)
    parallel_ = collect(2, seeds, 4)             # 2 processi, 4 gruppi
    assert serial.games == parallel_.games == 8
    for kind in ("carta", "preludio", "corporazione"):
        a = [(i.name, i.played, i.wins, i.bought) for i in serial.ranking(kind)]
        b = [(i.name, i.played, i.wins, i.bought) for i in parallel_.ranking(kind)]
        assert a == b
    files_a = serial.write_csv(tmp_path / "a")
    files_b = parallel_.write_csv(tmp_path / "b")
    for fa, fb in zip(files_a, files_b):
        assert fa.read_text(encoding="utf-8-sig") == fb.read_text(encoding="utf-8-sig")
