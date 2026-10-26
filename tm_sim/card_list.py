"""L'elenco delle carte usate dal motore.

Le carte NON sono più scritte a mano: vengono importate automaticamente
dal progetto open source di Terraforming Mars con

    python tools/import_cards.py CARTELLA_DEL_PROGETTO

che genera tm_sim/card_data.py. Le carte che il motore non sa ancora
giocare sono elencate, con il motivo, in tools/import_report.md.
Quando il motore impara un nuovo tipo di effetto, si aggiorna lo script
di importazione e lo si rilancia: le nuove carte compaiono da sole.
"""

from tm_sim.card_data import IMPORTED_CARDS
from tm_sim.cards import Card
import tm_sim.card_effects  # noqa: F401  (riempie i testi degli effetti a scatto)

ALL_CARDS: list[Card] = IMPORTED_CARDS

# Dizionario nome -> carta, per trovare una carta dal suo nome.
CARDS_BY_NAME: dict[str, Card] = {card.name: card for card in ALL_CARDS}

# Controllo di sicurezza: due carte con lo stesso nome sarebbero un errore.
assert len(CARDS_BY_NAME) == len(ALL_CARDS), "Nomi di carte duplicati!"
