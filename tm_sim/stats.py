"""Statistiche su carte, preludi e corporazioni, raccolte durante le simulazioni.

COSA MISURIAMO (per ogni carta, preludio o corporazione)
- offerta / comprata / giocata: quante volte;
- % vittorie: di chi l'ha giocata (in caso di parità la vittoria si divide);
- vantaggio: % vittorie meno quella attesa se la carta non contasse nulla
  (50% a 2 giocatori, 33% a 3, ...). Positivo = chi la gioca vince più spesso;
- margine: l'incertezza della % vittorie (intervallo al 95%). Se il vantaggio
  è più piccolo del margine, NON possiamo dire che la carta sia forte o debole;
- generazione media in cui viene giocata;
- % vittorie se comprata ma NON giocata: un confronto utile. Se è molto più
  bassa, la carta "vince" anche perché la gioca chi è già messo bene.

ATTENZIONE: queste sono CORRELAZIONI, non cause. Una carta giocata soprattutto
da chi è già in vantaggio sembra forte anche se non lo è. Per questo salviamo
anche i dati grezzi (una riga per giocatore per partita) in CSV: con quelli si
potranno usare metodi che separano l'effetto della carta dal resto.
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import TYPE_CHECKING

from tm_sim.cards import CardType

if TYPE_CHECKING:
    from tm_sim.game import Game


def margin_of_error(wins: float, games: int) -> float:
    """Margine di errore (95%) di una percentuale di vittorie, in punti percentuali.

    È la formula dell'"intervallo di confidenza" di una proporzione:
    1,96 × radice(p × (1 - p) / n). Con poche partite è grande.
    """
    if games == 0:
        return 0.0
    p = wins / games
    return 100 * 1.96 * math.sqrt(p * (1 - p) / games)


@dataclass
class ItemStats:
    """Le statistiche di una carta, di un preludio o di una corporazione."""
    name: str
    kind: str                    # "carta", "preludio", "corporazione"
    offered: int = 0
    bought: int = 0
    played: int = 0
    wins: float = 0.0            # vittorie di chi l'ha giocata
    score_sum: int = 0
    generation_sum: int = 0
    bought_not_played: int = 0
    wins_bought_not_played: float = 0.0

    def win_rate(self) -> float:
        return 100 * self.wins / self.played if self.played else 0.0

    def margin(self) -> float:
        return margin_of_error(self.wins, self.played)

    def average_score(self) -> float:
        return self.score_sum / self.played if self.played else 0.0

    def average_generation(self) -> float:
        return self.generation_sum / self.played if self.played else 0.0

    def play_rate(self) -> float:
        """% di volte che viene giocata, su quelle in cui è stata comprata."""
        return 100 * self.played / self.bought if self.bought else 0.0

    def win_rate_unplayed(self) -> float | None:
        if not self.bought_not_played:
            return None
        return 100 * self.wins_bought_not_played / self.bought_not_played

    def add(self, other: ItemStats) -> None:
        """Somma i conteggi di un altro gruppo di partite (calcolo in parallelo)."""
        for f in fields(self):
            if f.name not in ("name", "kind"):
                setattr(self, f.name, getattr(self, f.name) + getattr(other, f.name))


@dataclass
class StatsCollector:
    """Raccoglie i dati partita dopo partita (si chiama add_game alla fine di ognuna)."""
    n_players: int
    games: int = 0
    items: dict[tuple[str, str], ItemStats] = field(default_factory=dict)
    rows: list[dict] = field(default_factory=list)      # una riga per giocatore per partita

    @property
    def expected_win_rate(self) -> float:
        return 100 / self.n_players

    def _item(self, kind: str, name: str) -> ItemStats:
        key = (kind, name)
        if key not in self.items:
            self.items[key] = ItemStats(name, kind)
        return self.items[key]

    def add_game(self, game: Game, seed: int | None = None) -> None:
        self.games += 1
        scores = game.scores()
        winners = game.winners()

        # Il registro della partita, diviso per giocatore.
        offered = defaultdict(list)
        bought = defaultdict(set)
        played = defaultdict(dict)                      # carta -> generazione
        for player_name, card, event, generation in game.card_log:
            if event == "offerta":
                offered[player_name].append(card)
            elif event == "comprata":
                bought[player_name].add(card)
            elif event == "giocata":
                played[player_name][card] = generation

        for seat, player in enumerate(game.state.players):
            won = 1 / len(winners) if player.name in winners else 0.0
            score = scores[player.name]
            kinds = {c.name: ("preludio" if c.type is CardType.PRELUDE else "carta")
                     for c in player.played}

            if player.corporation:
                corp = self._item("corporazione", player.corporation.name)
                corp.played += 1
                corp.wins += won
                corp.score_sum += score

            for card in offered[player.name]:
                self._item("carta", card).offered += 1
            for card in bought[player.name]:
                item = self._item("carta", card)
                item.bought += 1
                if card not in played[player.name]:
                    item.bought_not_played += 1
                    item.wins_bought_not_played += won
            for card, generation in played[player.name].items():
                item = self._item(kinds.get(card, "carta"), card)
                item.played += 1
                item.wins += won
                item.score_sum += score
                item.generation_sum += generation

            self.rows.append({
                "partita": seed if seed is not None else self.games,
                "posto": seat + 1,
                "giocatori": self.n_players,
                "corporazione": player.corporation.name if player.corporation else "",
                "preludi": "|".join(c for c, k in kinds.items() if k == "preludio"),
                "punti": score,
                "vittoria": round(won, 3),
                "generazioni": game.state.generation - 1,
                "carte_giocate": "|".join(f"{c}@{g}" for c, g in played[player.name].items()
                                          if kinds.get(c) != "preludio"),
            })

    def merge(self, other: StatsCollector) -> None:
        """Unisce le statistiche raccolte da un altro processo (vedi tm_sim/parallel.py)."""
        self.games += other.games
        for key, item in other.items.items():
            if key in self.items:
                self.items[key].add(item)
            else:
                self.items[key] = item
        self.rows.extend(other.rows)

    # --- Classifiche ---------------------------------------------------------

    def ranking(self, kind: str, min_played: int = 1) -> list[ItemStats]:
        """Ordinata per vantaggio (dal migliore), solo con abbastanza partite."""
        items = [i for (k, _), i in self.items.items() if k == kind and i.played >= min_played]
        # A parità di % vittorie, in ordine alfabetico: così l'ordine non dipende
        # da come sono arrivati i risultati (per esempio dal calcolo in parallelo).
        return sorted(items, key=lambda i: (-round(i.win_rate(), 9), i.name))

    def advantage(self, item: ItemStats) -> float:
        return item.win_rate() - self.expected_win_rate

    # --- Esportazione ----------------------------------------------------------

    def write_csv(self, folder: Path) -> list[Path]:
        """Salva le classifiche complete e i dati grezzi. Restituisce i file scritti."""
        folder.mkdir(parents=True, exist_ok=True)
        written = []
        for kind, filename in [("carta", "carte.csv"), ("preludio", "preludi.csv"),
                               ("corporazione", "corporazioni.csv")]:
            path = folder / filename
            with path.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["nome", "offerta", "comprata", "giocata", "perc_vittorie",
                                 "vantaggio", "margine", "punti_medi", "generazione_media",
                                 "perc_giocata_su_comprata", "perc_vittorie_se_non_giocata"])
                for item in self.ranking(kind):
                    unplayed = item.win_rate_unplayed()
                    writer.writerow([
                        item.name, item.offered, item.bought, item.played,
                        round(item.win_rate(), 2), round(self.advantage(item), 2),
                        round(item.margin(), 2), round(item.average_score(), 2),
                        round(item.average_generation(), 2), round(item.play_rate(), 2),
                        "" if unplayed is None else round(unplayed, 2)])
            written.append(path)

        path = folder / "giocatori.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            if self.rows:
                writer = csv.DictWriter(f, fieldnames=list(self.rows[0]))
                writer.writeheader()
                # In ordine di partita e posto, anche se sono arrivate in parallelo.
                writer.writerows(sorted(self.rows, key=lambda r: (r["partita"], r["posto"])))
        written.append(path)
        return written
