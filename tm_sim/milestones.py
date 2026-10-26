"""Traguardi (milestones) e riconoscimenti (awards) della mappa Tharsis.

Come per le carte, sono DATI: ogni traguardo ha un nome e una funzione
che dice se il giocatore lo ha raggiunto; ogni riconoscimento ha un nome
e una funzione che calcola il punteggio del giocatore in quella categoria.

Le altre mappe (Hellas, Elysium) hanno traguardi e riconoscimenti
diversi: basterà aggiungere altri elenchi come questi.
"""

from collections.abc import Callable
from dataclasses import dataclass

from tm_sim.cards import Tag
from tm_sim.state import Player, Resource

# --- Regole ------------------------------------------------------------------

MILESTONE_COST = 8
MAX_MILESTONES = 3          # in totale nella partita, non a testa
MILESTONE_POINTS = 5

AWARD_COSTS = (8, 14, 20)   # il primo costa 8, il secondo 14, il terzo 20
MAX_AWARDS = len(AWARD_COSTS)
AWARD_FIRST_PLACE_POINTS = 5
AWARD_SECOND_PLACE_POINTS = 2


@dataclass(frozen=True)
class Milestone:
    """Un traguardo: "hai almeno `target` di qualcosa".

    metric è il nome di ciò che si conta ("cities", "tr"...): serve al bot
    per capire quali mosse lo avvicinano al traguardo.
    progress dice a che punto è un giocatore.
    """
    name: str
    description: str
    metric: str
    target: int
    progress: Callable[[Player], int]

    def is_reached(self, player: Player) -> bool:
        return self.progress(player) >= self.target


@dataclass(frozen=True)
class Award:
    name: str
    description: str
    score: Callable[[Player], int]


# "lambda p: ..." è una funzione senza nome scritta in una riga:
# lambda p: p.cities  equivale a
#     def f(p):
#         return p.cities

MILESTONES = [
    Milestone("Terraformer", "TR almeno 35", "tr", 35,
              lambda p: p.terraform_rating),
    Milestone("Mayor", "almeno 3 città", "cities", 3,
              lambda p: p.cities),
    Milestone("Gardener", "almeno 3 foreste", "greeneries", 3,
              lambda p: p.greeneries),
    Milestone("Builder", "almeno 8 tag edificio", "building_tags", 8,
              lambda p: p.tag_count(Tag.BUILDING)),
    Milestone("Planner", "almeno 16 carte in mano", "hand", 16,
              lambda p: len(p.hand)),
]

AWARDS = [
    Award("Landlord", "più tessere (città, foreste e tessere speciali)",
          lambda p: p.cities + p.greeneries + p.special_tiles),
    Award("Banker", "più produzione di M€",
          lambda p: p.production[Resource.MEGACREDITS]),
    Award("Scientist", "più tag scienza",
          lambda p: p.tag_count(Tag.SCIENCE, wild=False)),     # i riconoscimenti non contano il jolly
    Award("Thermalist", "più calore",
          lambda p: p.resources[Resource.HEAT]),
    Award("Miner", "più acciaio + titanio",
          lambda p: p.resources[Resource.STEEL] + p.resources[Resource.TITANIUM]),
]

MILESTONES_BY_NAME = {m.name: m for m in MILESTONES}
AWARDS_BY_NAME = {a.name: a for a in AWARDS}


def award_points(award: Award, players: list[Player]) -> dict[str, int]:
    """Punti che ogni giocatore riceve da un riconoscimento finanziato.

    - Tutti i primi a pari merito: 5 punti.
    - Secondo posto (2 punti) solo se il primo è uno solo
      e solo con più di 2 giocatori.
    """
    return points_from_scores({p.name: award.score(p) for p in players})


def points_from_scores(scores: dict[str, float]) -> dict[str, int]:
    """Come award_points, ma partendo dai valori già calcolati (nome -> valore).

    Serve al bot per chiedersi "e se spendessi 8 calore, resterei primo?".
    """
    points = {name: 0 for name in scores}
    best = max(scores.values())
    first = [name for name, s in scores.items() if s == best]
    for name in first:
        points[name] = AWARD_FIRST_PLACE_POINTS

    if len(first) == 1 and len(scores) > 2:
        others = [s for name, s in scores.items() if name not in first]
        second_best = max(others)
        for name, s in scores.items():
            if s == second_best and name not in first:
                points[name] = AWARD_SECOND_PLACE_POINTS

    return points
