"""Le azioni che un giocatore può fare nel suo turno.

Un'azione è solo una DESCRIZIONE di cosa vuoi fare ("costruisci una
centrale elettrica"), non il codice che la esegue. Il codice che la
esegue sta in game.py.

Perché separarle? Perché così l'IA può ricevere una lista di azioni,
confrontarle, salvarle, contarle per le statistiche... senza eseguirle.
"""

from dataclasses import dataclass
from enum import Enum
from tm_sim.fastenum import FastEnum


class ActionType(FastEnum):
    # Gestione del turno
    PASS = "passa"                  # esci dalla generazione corrente
    END_TURN = "fine turno"         # dopo 1 azione, rinunci alla seconda

    # Carte
    PLAY_CARD = "gioca"             # gioca una carta dalla mano
    DRAFT_CARD = "scegli nel draft"  # draft: tieni questa carta, passa le altre
    BUY_CARDS = "compra"            # ricerca e inizio partita: le carte scelte, tutte insieme
    BUY_CARD = "compra (3 M€)"      # durante un'azione (Business Network): tieni la carta pescata
    SKIP_CARD = "scarta"            # fase di ricerca: scarta la carta pescata

    # Preparazione della partita e preludi
    CHOOSE_CORPORATION = "scegli la corporazione"
    KEEP_PRELUDE = "tieni il preludio"
    PLAY_PRELUDE = "gioca il preludio"
    DISCARD_PRELUDE = "scarta il preludio ingiocabile (+15 M€)"

    # Corporazioni
    FIRST_ACTION = "azione iniziale"  # obbligatoria, come prima azione della partita
    CARD_ACTION = "usa l'azione di"   # azione ripetibile (una per generazione)

    # Mappa
    PLACE_TILE = "piazza su"        # scegli la casella per una tessera in attesa

    # Attacchi
    ATTACK = "attacca"              # scegli chi colpire (o "nessuno", quando è facoltativo)

    # Traguardi e riconoscimenti
    CLAIM_MILESTONE = "reclama il traguardo (8 M€)"
    FUND_AWARD = "finanzia il riconoscimento"

    # Conversioni di risorse
    CONVERT_PLANTS = "8 piante → foresta"
    CONVERT_HEAT = "8 calore → +1 temperatura"

    # Progetti standard
    SELL_PATENTS = "Vendi brevetti (1 M€ a carta)"
    POWER_PLANT = "Centrale elettrica (11 M€)"
    ASTEROID = "Asteroide (14 M€)"
    AQUIFER = "Acquifero (18 M€)"
    GREENERY = "Foresta (23 M€)"
    CITY = "Città (25 M€)"

    # Scelte in attesa
    CHOOSE_EFFECT = "scegli"         # quale effetto di una carta (e su quale carta)
    SKIP_BONUS_PLAY = "non giocare nessuna carta"   # Eccentric Sponsor: rinuncia
    KEEP_CARD = "tieni"              # quale carta tenere tra quelle guardate

    # Durante la vendita di brevetti: quali carte vendere
    SELL_CARD = "vendi"
    STOP_SELLING = "basta così"


# Costo in megacrediti di ogni progetto standard.
STANDARD_PROJECT_COST = {
    ActionType.POWER_PLANT: 11,
    ActionType.ASTEROID: 14,
    ActionType.AQUIFER: 18,
    ActionType.GREENERY: 23,
    ActionType.CITY: 25,
}

CARD_PRICE = 3          # costo per comprare una carta nella fase di ricerca
CARDS_PER_RESEARCH = 4  # carte pescate a ogni fase di ricerca
STARTING_HAND = 10      # carte iniziali (corporazione per principianti: gratis)

PLANTS_PER_GREENERY = 8
HEAT_PER_TEMPERATURE = 8
PATENT_PRICE = 1        # M€ per ogni carta venduta

# COME PAGARE (Action.payment). Di solito si usano acciaio e titanio quando la
# carta lo permette (None). Ma a volte conviene tenerli: per esempio a fine
# partita, se il riconoscimento Miner premia chi ne ha di più.
PAY_NO_METALS = "senza metalli"
PAY_NO_STEEL = "senza acciaio"
PAY_NO_TITANIUM = "senza titanio"
# scelta -> (si può usare l'acciaio?, si può usare il titanio?)
PAYMENT_CHOICES: dict[str | None, tuple[bool, bool]] = {
    None: (True, True),
    PAY_NO_METALS: (False, False),
    PAY_NO_STEEL: (False, True),
    PAY_NO_TITANIUM: (True, False),
}


class ActionCategory(FastEnum):
    """Le 7 azioni del regolamento, più le categorie "di servizio".

    Le categorie servono a raggruppare le mosse nei menu: il motore e
    l'IA continuano a lavorare con la lista piatta di tutte le azioni.
    L'ordine qui sotto è l'ordine in cui compaiono nel menu.
    """
    PLAY_CARD = "Giocare una carta"
    RAISE_TEMPERATURE = "Aumentare la temperatura (8 calore)"
    BUILD_GREENERY = "Costruire una foresta (8 piante)"
    CLAIM_MILESTONE = "Reclamare un traguardo"
    FUND_AWARD = "Finanziare un riconoscimento"
    CARD_ACTION = "Usare l'azione di una carta"   # carte blu: arriveranno più avanti
    STANDARD_PROJECT = "Progetti standard"
    # Non sono "azioni" del regolamento, ma mosse comunque possibili:
    TURN = "Gestione del turno"
    RESEARCH = "Fase di ricerca"
    PLACE_TILE = "Piazzare una tessera"
    SETUP = "Preparazione della partita"
    ATTACK = "Scegliere chi attaccare"
    FIRST_ACTION = "Azione iniziale della corporazione"
    SELLING = "Vendere brevetti"
    CHOICE = "Scegliere un effetto"


# A quale categoria appartiene ogni tipo di azione.
CATEGORY_OF: dict[ActionType, ActionCategory] = {
    ActionType.PASS: ActionCategory.TURN,
    ActionType.END_TURN: ActionCategory.TURN,
    ActionType.PLAY_CARD: ActionCategory.PLAY_CARD,
    ActionType.BUY_CARD: ActionCategory.RESEARCH,
    ActionType.BUY_CARDS: ActionCategory.RESEARCH,
    ActionType.DRAFT_CARD: ActionCategory.RESEARCH,
    ActionType.SKIP_CARD: ActionCategory.RESEARCH,
    ActionType.PLACE_TILE: ActionCategory.PLACE_TILE,
    ActionType.CHOOSE_CORPORATION: ActionCategory.SETUP,
    ActionType.KEEP_PRELUDE: ActionCategory.SETUP,
    ActionType.PLAY_PRELUDE: ActionCategory.SETUP,
    ActionType.DISCARD_PRELUDE: ActionCategory.SETUP,
    ActionType.FIRST_ACTION: ActionCategory.FIRST_ACTION,
    ActionType.ATTACK: ActionCategory.ATTACK,
    ActionType.CARD_ACTION: ActionCategory.CARD_ACTION,
    ActionType.CLAIM_MILESTONE: ActionCategory.CLAIM_MILESTONE,
    ActionType.FUND_AWARD: ActionCategory.FUND_AWARD,
    ActionType.CONVERT_PLANTS: ActionCategory.BUILD_GREENERY,
    ActionType.CONVERT_HEAT: ActionCategory.RAISE_TEMPERATURE,
    ActionType.POWER_PLANT: ActionCategory.STANDARD_PROJECT,
    ActionType.ASTEROID: ActionCategory.STANDARD_PROJECT,
    ActionType.AQUIFER: ActionCategory.STANDARD_PROJECT,
    ActionType.GREENERY: ActionCategory.STANDARD_PROJECT,
    ActionType.CITY: ActionCategory.STANDARD_PROJECT,
    ActionType.SELL_PATENTS: ActionCategory.STANDARD_PROJECT,
    ActionType.SELL_CARD: ActionCategory.SELLING,
    ActionType.STOP_SELLING: ActionCategory.SELLING,
    ActionType.CHOOSE_EFFECT: ActionCategory.CHOICE,
    ActionType.KEEP_CARD: ActionCategory.CHOICE,
    ActionType.SKIP_BONUS_PLAY: ActionCategory.CHOICE,
}


@dataclass(frozen=True)
class Action:
    """Un'azione concreta.

    frozen=True rende l'oggetto immutabile: una volta creato non si può
    modificare. Questo permette di usarlo come chiave di un dizionario,
    cosa che ci servirà per l'IA (es. "quante volte ho provato questa mossa?").

    Per le azioni sulle carte, card dice QUALE carta (con il suo nome).
    Per traguardi e riconoscimenti, target dice quale (con il suo nome).
    Per il piazzamento, space dice su quale casella ("riga-posto").
    Per gli attacchi, target è il giocatore colpito e option cosa gli togli
    (per esempio "acciaio", oppure "animali:Birds" per gli animali di una carta).
    payment dice come pagare (vedi PAYMENT_CHOICES): None = come d'abitudine.
    cards: per "compra" (BUY_CARDS), le carte comprate tutte insieme (vuoto = nessuna).
    """

    type: ActionType
    card: str | None = None
    target: str | None = None
    space: str | None = None
    option: str | None = None
    payment: str | None = None
    cards: tuple[str, ...] = ()

    @property
    def category(self) -> ActionCategory:
        return CATEGORY_OF[self.type]

    def __str__(self) -> str:
        text = self._text()
        return f"{text} ({self.payment})" if self.payment else text

    def _text(self) -> str:
        if self.type is ActionType.BUY_CARDS:
            return f"compra {', '.join(self.cards)}" if self.cards else "non comprare niente"
        if self.type is ActionType.ATTACK:
            what = f" ({self.option})" if self.option else ""
            return f"{self.card}: attacca {self.target}{what}"
        if self.card is not None and self.target is not None:
            return f"{self.type.value} {self.card}: {self.target}"
        if self.card is not None:
            return f"{self.type.value} {self.card}"
        if self.target is not None:
            return f"{self.type.value} {self.target}"
        if self.space is not None:
            return f"{self.type.value} {self.space}"
        return self.type.value


def group_by_category(actions: list[Action]) -> dict[ActionCategory, list[Action]]:
    """Raggruppa le azioni per categoria, nell'ordine di ActionCategory.

    Compaiono solo le categorie con almeno un'azione: se non puoi fare
    nessun progetto standard, la voce "Progetti standard" non c'è.
    """
    groups: dict[ActionCategory, list[Action]] = {}
    for category in ActionCategory:
        in_category = [a for a in actions if a.category is category]
        if in_category:
            groups[category] = in_category
    return groups
