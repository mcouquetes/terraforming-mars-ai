"""Le lezioni del giocatore umano: accoppiate forti da verificare con le simulazioni.

COME FUNZIONA
1. Con insegna.py guardi delle mani iniziali (corporazioni, preludi, 10 carte) e
   dici cosa faresti, indicando le ACCOPPIATE che ti hanno fatto scegliere così
   (per esempio "Ecoline + Arctic Algae" o "Fish + Large Convoy").
   Le lezioni si salvano in risultati/insegnamenti.json.
2. learn.py trasforma ogni accoppiata in un'IPOTESI: "giocate insieme, valgono
   più delle due carte prese da sole". Per metterla alla prova:
   - il bot parte fidandosi di te: dà all'accoppiata un bonus iniziale (in PV),
     così la compra e la gioca davvero insieme;
   - in una parte delle partite di allenamento l'accoppiata viene messa apposta
     nella mano iniziale di un giocatore (altrimenti capiterebbe troppo di rado
     per misurarla);
   - la regressione (tm_sim/card_power.py) misura quanto vale davvero l'accoppiata
     IN PIÙ delle due carte da sole. Con pochi dati il bonus resta vicino alla
     tua fiducia, con tanti dati decidono le partite: se l'accoppiata non funziona,
     il bonus scende a zero (o sotto).
"""

from __future__ import annotations

import json
import random
from datetime import date
from pathlib import Path

from tm_sim.card_data import PRELUDE_CARDS
from tm_sim.card_list import CARDS_BY_NAME
from tm_sim.corporations import CORPORATIONS_BY_NAME

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEACH_FILE = PROJECT_ROOT / "risultati" / "insegnamenti.json"

EXPLICIT_HINT = 3.0     # PV di fiducia iniziale per un'accoppiata indicata da te
INFERRED_HINT = 1.5     # ...e per una dedotta (carta che compri tu e il bot no + tua corporazione)
PAIR_SEPARATOR = " + "

PRELUDES_BY_NAME = {p.name: p for p in PRELUDE_CARDS}


def pair_key(a: str, b: str) -> str:
    """Il nome di un'accoppiata, sempre nello stesso ordine: "Arctic Algae + EcoLine"."""
    first, second = sorted((a, b))
    return f"{first}{PAIR_SEPARATOR}{second}"


def split_pair(key: str) -> tuple[str, str]:
    a, _, b = key.partition(PAIR_SEPARATOR)
    return a, b


def load_lessons(path: Path = TEACH_FILE) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("lezioni", [])


def save_lessons(lessons: list[dict], path: Path = TEACH_FILE) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"lezioni": lessons}, ensure_ascii=False, indent=1),
                    encoding="utf-8")


def make_lesson(seed: int, offer: dict, mine: dict, bot: dict, explicit: list[str]) -> dict:
    """Una lezione: la mano offerta, la tua scelta, quella del bot e le accoppiate.

    Se non indichi accoppiate, ne deduce alcune: ogni carta che compri tu e il bot
    no, insieme alla corporazione che hai scelto (fiducia più bassa)."""
    inferred = []
    if not explicit:
        for card in mine["carte"]:
            if card not in bot["carte"]:
                inferred.append(pair_key(card, mine["corporazione"]))
    return {"seed": seed, "data": date.today().isoformat(), "offerta": offer,
            "scelta": mine, "bot": bot, "coppie": sorted(set(explicit)),
            "coppie_dedotte": sorted(set(inferred))}


def hypotheses(lessons: list[dict]) -> dict[str, float]:
    """Le accoppiate da verificare, con la fiducia iniziale (in PV).

    Indicata esplicitamente: EXPLICIT_HINT; solo dedotta: INFERRED_HINT. Se la stessa
    accoppiata compare in più lezioni, la fiducia cresce un po' (fino al doppio)."""
    counts: dict[str, list[float]] = {}
    for lesson in lessons:
        for key in lesson.get("coppie", []):
            counts.setdefault(key, []).append(EXPLICIT_HINT)
        for key in lesson.get("coppie_dedotte", []):
            counts.setdefault(key, []).append(INFERRED_HINT)
    result = {}
    for key, hints in counts.items():
        a, b = split_pair(key)
        if not (known(a) and known(b)):
            continue                      # carta rinominata o tolta: si ignora
        strongest = max(hints)
        result[key] = min(2 * strongest, strongest * (1 + 0.25 * (len(hints) - 1)))
    return result


def known(name: str) -> bool:
    return name in CARDS_BY_NAME or name in PRELUDES_BY_NAME or name in CORPORATIONS_BY_NAME


# ---------------------------------------------------------------------------
# Mani "truccate": mettere un'accoppiata nell'offerta iniziale di un giocatore
# ---------------------------------------------------------------------------

def plant_pair(game, player, key: str, rng: random.Random) -> bool:
    """Mette le due metà dell'accoppiata nell'offerta iniziale di `player`
    (corporazioni, preludi o 10 carte), scambiandole con altre: nessuna carta
    si crea o si perde. Una corporazione piantata diventa l'unica scelta, così
    viene presa davvero. Restituisce False se non si può (partita già iniziata)."""
    if player.corporation is not None or not player.drafted:
        return False
    names = split_pair(key)
    for name in names:
        if name in CORPORATIONS_BY_NAME:
            _swap_in(game, player, "corporation_choices", name, (), rng)
            chosen = next(c for c in player.corporation_choices if c.name == name)
            others = [c for c in player.corporation_choices if c is not chosen]
            game.corporation_deck.extend(others)      # le altre tornano nel mazzo
            player.corporation_choices = [chosen]
        elif name in PRELUDES_BY_NAME:
            if not player.prelude_choices:
                return False
            _swap_in(game, player, "prelude_choices", name, names, rng)
        elif name in CARDS_BY_NAME:
            _swap_in(game, player, "drafted", name, names, rng)
        else:
            return False
    return True


def _containers(game, attribute: str) -> list[list]:
    """Dove può trovarsi una carta di quel tipo prima che la partita inizi."""
    players = game.state.players
    if attribute == "corporation_choices":
        return [game.corporation_deck] + [p.corporation_choices for p in players]
    if attribute == "prelude_choices":
        return [game.prelude_deck] + [p.prelude_choices for p in players]
    return [game.deck, game.discard_pile] + [p.drafted for p in players] + [p.hand for p in players]


def _swap_in(game, player, attribute: str, name: str, keep: tuple, rng: random.Random) -> None:
    mine = getattr(player, attribute)
    if any(c.name == name for c in mine):
        return
    for container in _containers(game, attribute):
        if container is mine:
            continue
        for i, card in enumerate(container):
            if card.name == name:
                replaceable = [j for j, c in enumerate(mine) if c.name not in keep]
                j = rng.choice(replaceable)
                container[i], mine[j] = mine[j], card        # scambio: niente si perde
                return
