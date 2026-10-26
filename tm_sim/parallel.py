"""Calcolo in parallelo: far giocare le partite su più core del processore.

Il processore ha più "core", unità di calcolo indipendenti. Un programma
Python normale ne usa uno solo. Siccome ogni partita è indipendente dalle
altre, possiamo dividerle in gruppi e far giocare ogni gruppo da una copia
del programma su un core diverso (libreria standard `multiprocessing`).
Alla fine si sommano i risultati.

Per lasciare il computer usabile mentre simula, teniamo sempre liberi
FREE_CORES core: con 8 core se ne usano al massimo 6.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from multiprocessing import Pool
from typing import TypeVar

# Core lasciati sempre liberi. Si può cambiare con la variabile d'ambiente
# TM_CORE_LIBERI (per esempio su un server dove non serve lasciarne).
FREE_CORES = int(os.environ.get("TM_CORE_LIBERI", "2"))

T = TypeVar("T")
R = TypeVar("R")


def max_processes() -> int:
    """Quanti processi al massimo: tutti i core meno FREE_CORES (almeno 1)."""
    return max(1, (os.cpu_count() or 1) - FREE_CORES)


def choose_processes(requested: int | None) -> int:
    """Il numero di processi da usare: quello chiesto, ma mai oltre il massimo."""
    limit = max_processes()
    if requested is None:
        return limit
    return max(1, min(requested, limit))


def split_seeds(seeds: list[int], n_chunks: int) -> list[list[int]]:
    """Divide i seed in gruppi: seed consecutivi nello stesso gruppo."""
    n_chunks = max(1, min(n_chunks, len(seeds)))
    size, extra = divmod(len(seeds), n_chunks)
    chunks, start = [], 0
    for i in range(n_chunks):
        end = start + size + (1 if i < extra else 0)
        chunks.append(seeds[start:end])
        start = end
    return [c for c in chunks if c]


def run_in_parallel(work: Callable[[T], R], jobs: list[T], processes: int) -> Iterator[R]:
    """Esegue work(job) per ogni job, su più processi; restituisce i risultati
    man mano che arrivano (in ordine qualsiasi).

    Con un solo processo non avvia nulla di speciale: esegue tutto qui, nel
    modo più semplice (utile anche per i test e per cercare bug).

    `work` deve essere una funzione definita al livello principale di un modulo
    (non dentro un'altra funzione): così le altre copie del programma la trovano.
    """
    if processes <= 1 or len(jobs) <= 1:
        for job in jobs:
            yield work(job)
        return
    with Pool(processes) as pool:
        yield from pool.imap_unordered(work, jobs)
