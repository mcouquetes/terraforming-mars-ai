"""Come è fatta una carta, e come si verifica se si può giocare.

L'idea: ogni carta è solo un insieme di DATI (tag, costo, risorse,
produzioni, requisiti...). Non scriviamo codice diverso per ogni carta:
un unico pezzo di codice (in game.py) sa giocare qualsiasi carta
descritta in questo modo.

Anche le AZIONI delle carte blu ("Azione: spendi 8 M€ per piazzare un
oceano") sono dati: vedi CardAction. Restano scritti a mano solo gli effetti
che reagiscono a qualcosa (card_effects.py) e poche azioni davvero strane.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from tm_sim.fastenum import FastEnum
from typing import TYPE_CHECKING

from tm_sim.board import TilePlacement, TileType, as_placement
from tm_sim.state import MIN_MC_PRODUCTION, TEMPERATURE_STEP, Resource

# TYPE_CHECKING è falso quando il programma gira: questi import servono
# solo per i suggerimenti di tipo dell'editor, ed evitano un "import
# circolare" (state.py e cards.py che si importano a vicenda).
if TYPE_CHECKING:
    from tm_sim.state import GameState, Player


class Tag(FastEnum):
    """I simboli in alto a destra delle carte."""
    BUILDING = "edificio"
    SPACE = "spazio"
    SCIENCE = "scienza"
    POWER = "energia"
    EARTH = "terra"
    JOVIAN = "gioviano"
    PLANT = "pianta"
    MICROBE = "microbo"
    ANIMAL = "animale"
    CITY = "città"
    EVENT = "evento"
    WILD = "jolly"        # vale come qualsiasi tag (Research Coordination)


class CardType(FastEnum):
    AUTOMATED = "automatica"   # bordo verde: effetto immediato, resta in gioco
    EVENT = "evento"           # bordo rosso: effetto immediato, poi conta solo il tag evento
    ACTIVE = "attiva"          # bordo blu: effetto permanente (e/o azione)
    PRELUDE = "preludio"       # si gioca all'inizio della partita, gratis


class CardResource(FastEnum):
    """Risorse che si accumulano SOPRA una carta (non nel magazzino)."""
    ANIMAL = "animali"
    MICROBE = "microbi"
    SCIENCE = "scienza"
    FIGHTER = "caccia"


# Valore in megacrediti di acciaio e titanio quando paghi una carta.
STEEL_VALUE = 2      # solo per carte con tag edificio
TITANIUM_VALUE = 3   # solo per carte con tag spazio



# Testo degli effetti "a scatto" delle carte blu, per le descrizioni. Lo riempie
# tm_sim/card_effects.py (dove gli effetti sono scritti a mano).
EFFECT_TEXTS: dict[str, str] = {}

@dataclass(frozen=True)
class PaymentRules:
    """Come può pagare un giocatore. Di solito i valori standard, ma
    alcune corporazioni li cambiano (PhoboLog: titanio da 4; Helion:
    il calore vale come M€)."""
    steel_value: int = STEEL_VALUE
    titanium_value: int = TITANIUM_VALUE
    heat_as_megacredits: bool = False


STANDARD_PAYMENT = PaymentRules()


@dataclass
class Requirements:
    """I requisiti per giocare una carta. None significa "nessun limite".

    I tag richiesti sono quelli GIÀ in gioco: la carta che stai giocando
    non conta per il proprio requisito.
    """

    min_temperature: int | None = None
    max_temperature: int | None = None
    min_oxygen: int | None = None
    max_oxygen: int | None = None
    min_oceans: int | None = None
    max_oceans: int | None = None
    tags: dict[Tag, int] = field(default_factory=dict)
    min_greeneries: int | None = None       # foreste TUE sulla mappa
    min_cities: int | None = None           # città in gioco, di chiunque (Rad-Suits)
    min_production: dict[Resource, int] = field(default_factory=dict)   # tua produzione

    def are_met(self, state: GameState, player: Player, leeway: int = 0) -> bool:
        """leeway: di quanti "passi" si possono sforare i requisiti dei
        parametri globali (Inventrix: 2). Un passo di temperatura = 2°C."""
        planet = state.planet
        checks = [
            (planet.temperature, self.min_temperature, self.max_temperature, TEMPERATURE_STEP),
            (planet.oxygen, self.min_oxygen, self.max_oxygen, 1),
            (planet.oceans, self.min_oceans, self.max_oceans, 1),
        ]
        for value, minimum, maximum, step in checks:
            if minimum is not None and value < minimum - leeway * step:
                return False
            if maximum is not None and value > maximum + leeway * step:
                return False
        for tag, needed in self.tags.items():
            if player.tag_count(tag) < needed:
                return False
        if self.min_greeneries is not None and player.greeneries < self.min_greeneries:
            return False
        if self.min_cities is not None and state.board.count_tiles(TileType.CITY) < self.min_cities:
            return False
        for resource, needed in self.min_production.items():
            if player.production[resource] < needed:
                return False
        return True

    def describe(self) -> str:
        """Testo breve, es. "temperatura ≥ -14, 2 tag scienza"."""
        parts = []
        for label, unit, minimum, maximum in [
            ("temperatura", "°C", self.min_temperature, self.max_temperature),
            ("ossigeno", "%", self.min_oxygen, self.max_oxygen),
            ("oceani", "", self.min_oceans, self.max_oceans),
        ]:
            if minimum is not None:
                parts.append(f"{label} ≥ {minimum}{unit}")
            if maximum is not None:
                parts.append(f"{label} ≤ {maximum}{unit}")
        for tag, needed in self.tags.items():
            parts.append(f"{needed} tag {tag.value}")
        if self.min_greeneries:
            parts.append(f"{self.min_greeneries} tue foreste")
        if self.min_cities:
            parts.append(f"{self.min_cities} città in gioco")
        for resource, needed in self.min_production.items():
            parts.append(f"produzione di {resource.value} ≥ {needed}")
        return ", ".join(parts)


@dataclass(frozen=True)
class Scaled:
    """Una quantità che dipende dalla situazione quando giochi la carta.

    what:
      "tag"            1 ogni `per` tag `tag` che hai (compresa la carta stessa)
      "tag_others"     1 ogni `per` tag `tag` degli AVVERSARI (Toll Station)
      "tag_at_least"   `step` se hai almeno `per` tag `tag` (Nitrogen-Rich Asteroid)
      "cities"         1 ogni `per` città in gioco, di chiunque (anche nello spazio)
      "cities_on_mars" 1 ogni `per` città su Marte
      "events"         1 per ogni evento giocato da tutti i giocatori (Media Archives)
    step: quanto vale ogni unità (di solito 1).
    """
    what: str
    tag: Tag | None = None
    per: int = 1
    step: int = 1

    def describe(self) -> str:
        unit = {"tag": f"tag {self.tag.value if self.tag else ''}",
                "tag_others": f"tag {self.tag.value if self.tag else ''} degli avversari",
                "cities": "città in gioco", "cities_on_mars": "città su Marte",
                "events": "evento giocato (da tutti)"}.get(self.what, "")
        if self.what == "tag_at_least":
            return f"{self.step} se hai almeno {self.per} tag {self.tag.value}"
        each = f"ogni {self.per}" if self.per > 1 else "per"
        return f"{self.step} {each} {unit}"


@dataclass
class Payment:
    """Come il giocatore paga una carta."""
    megacredits: int = 0
    steel: int = 0
    titanium: int = 0
    heat: int = 0          # solo con Helion
    microbes: int = 0      # solo con Psychrophiles, per le carte pianta


def pay_megacredits(player: Player, amount: int, rules: PaymentRules = STANDARD_PAYMENT) -> Payment | None:
    """Come pagare una somma in M€ (per progetti standard, traguardi...).

    Si usano prima i M€; il calore solo se permesso e se i M€ non bastano.
    Restituisce None se il giocatore non può pagare.
    """
    megacredits = min(amount, player.resources[Resource.MEGACREDITS])
    heat = amount - megacredits
    if heat > 0 and not (rules.heat_as_megacredits and player.resources[Resource.HEAT] >= heat):
        return None
    return Payment(megacredits=megacredits, heat=heat)


def pay_with_metals(player: Player, cost: int, rules: PaymentRules = STANDARD_PAYMENT,
                    use_steel: bool = False, use_titanium: bool = False,
                    microbes: int = 0, microbe_value: int = 2) -> Payment | None:
    """Come pagare `cost` M€ potendo usare anche acciaio e/o titanio.

    Strategia: usa prima le risorse che non servono ad altro (i microbi di
    Psychrophiles), poi titanio e acciaio senza sprecarli, poi megacrediti,
    poi calore (solo Helion). Se non basta, aggiunge un'altra unità di
    metallo anche se si paga un po' di più (il regolamento lo consente, ma
    non dà resto). Restituisce None se non si può pagare.
    """
    remaining = cost
    available_titanium = player.resources[Resource.TITANIUM] if use_titanium else 0
    available_steel = player.resources[Resource.STEEL] if use_steel else 0

    used_microbes = min(microbes, remaining // microbe_value)
    remaining -= used_microbes * microbe_value
    titanium = min(available_titanium, remaining // rules.titanium_value)
    remaining -= titanium * rules.titanium_value
    steel = min(available_steel, remaining // rules.steel_value)
    remaining -= steel * rules.steel_value

    money = player.resources[Resource.MEGACREDITS]
    if rules.heat_as_megacredits:
        money += player.resources[Resource.HEAT]
    while remaining > money:
        if used_microbes < microbes:
            used_microbes += 1
            remaining = max(0, remaining - microbe_value)
        elif titanium < available_titanium:
            titanium += 1
            remaining = max(0, remaining - rules.titanium_value)
        elif steel < available_steel:
            steel += 1
            remaining = max(0, remaining - rules.steel_value)
        else:
            return None
    rest = pay_megacredits(player, remaining, rules)
    return Payment(megacredits=rest.megacredits, heat=rest.heat, steel=steel,
                   titanium=titanium, microbes=used_microbes)


@dataclass
class CardAction:
    """L'azione di una carta blu: si può usare una volta per generazione.

    Un'azione è "paga questo, ottieni quello". Una carta può avere più
    alternative (GHG Producing Bacteria: "aggiungi 1 microbo qui OPPURE
    togline 2 per alzare la temperatura"): ognuna è un CardAction.
    """
    # --- Cosa paghi ---
    spend: dict[Resource, int] = field(default_factory=dict)  # anche M€
    spend_here: int = 0               # risorse da togliere da QUESTA carta
    can_use_steel: bool = False       # i M€ si possono pagare con acciaio...
    can_use_titanium: bool = False    # ...o con titanio

    # --- Cosa ottieni ---
    gain: dict[Resource, int] = field(default_factory=dict)
    megacredits_per_city_on_mars: int = 0     # Martian Rails: 1 M€ per città su Marte
    production: dict[Resource, int] = field(default_factory=dict)   # anche negativa
    temperature_steps: int = 0
    oxygen_steps: int = 0
    terraform_rating: int = 0
    tiles: tuple[TileType | TilePlacement, ...] = ()
    draw_cards: int = 0
    buy_card: bool = False            # guarda la prima carta del mazzo: comprala (3 M€) o scartala
    add_here: int = 0                 # risorse da aggiungere a QUESTA carta
    # Togli 1 risorsa di questo tipo da una carta qualsiasi (anche di un avversario).
    remove_from_any_card: CardResource | None = None
    # Aggiungi N risorse di questo tipo a un'ALTRA tua carta.
    # Tipo None = a una qualsiasi tua carta che ha già almeno una risorsa (CEO's Favorite Project).
    add_to_other_card: tuple[CardResource | None, int] | None = None
    # Nome di un'azione scritta a mano (card_effects.SPECIAL_ACTIONS).
    special: str | None = None

    def __post_init__(self) -> None:
        self.tiles = tuple(as_placement(t) for t in self.tiles)

    def is_empty(self) -> bool:
        """Un'alternativa "non fare niente" (Mars University: puoi anche rinunciare)."""
        return self == CardAction()

    def describe(self, resource_type: CardResource | None = None) -> str:
        """Testo breve, es. "8 M€ (anche acciaio) → oceano"."""
        if self.is_empty():
            return "niente"
        here = resource_type.value if resource_type else "risorse"
        cost = []
        for resource, amount in self.spend.items():
            metals = [m for m, ok in (("acciaio", self.can_use_steel),
                                      ("titanio", self.can_use_titanium)) if ok]
            extra = f" (anche {'/'.join(metals)})" if metals else ""
            cost.append(f"{amount} {resource.value}{extra}")
        if self.spend_here:
            cost.append(f"{self.spend_here} {here} da qui")
        if self.production and any(n < 0 for n in self.production.values()):
            cost += [f"{n} produzione di {r.value}" for r, n in self.production.items() if n < 0]

        effects = [f"+{n} {r.value}" for r, n in self.gain.items()]
        if self.megacredits_per_city_on_mars:
            effects.append(f"{self.megacredits_per_city_on_mars} M€ per città su Marte")
        effects += [f"+{n} produzione di {r.value}" for r, n in self.production.items() if n > 0]
        if self.temperature_steps:
            effects.append(f"temperatura +{self.temperature_steps}")
        if self.oxygen_steps:
            effects.append(f"ossigeno +{self.oxygen_steps}")
        if self.terraform_rating:
            effects.append(f"TR +{self.terraform_rating}")
        effects += [t.describe() for t in self.tiles]
        if self.draw_cards:
            effects.append(f"pesca {self.draw_cards} {'carta' if self.draw_cards == 1 else 'carte'}")
        if self.buy_card:
            effects.append("guarda 1 carta e comprala se vuoi")
        if self.add_here:
            effects.append(f"+{self.add_here} {here} qui")
        if self.remove_from_any_card:
            effects.append(f"togli 1 {self.remove_from_any_card.value} da una carta")
        if self.add_to_other_card:
            kind, n = self.add_to_other_card
            if kind is None:
                effects.append(f"+{n} risorsa su una tua carta che ne ha già")
            else:
                effects.append(f"+{n} {kind.value} su un'altra tua carta")
        if self.special == "search_for_life":
            effects.append("scopri 1 carta: se ha tag microbo, +1 scienza qui")
        if self.special == "power_infrastructure":
            effects.append("X energia → X M€")
        if self.special == "discard_draw":
            effects.append("scarta una carta dalla mano e pescane una")
        if self.special == "insulation":
            effects.append("X produzione di calore → X produzione di M€")
        if self.special == "robotic_workforce":
            effects.append("copia la produzione di una tua carta edificio")
        if not cost:      # effetto gratuito (scelte quando giochi una carta): solo cosa dà
            return ", ".join(effects) or "niente"
        return ", ".join(cost) + " → " + (", ".join(effects) or "niente")


@dataclass
class PendingChoice:
    """Una scelta che il giocatore deve fare prima che la sua azione sia completa.

    Per esempio "3 piante OPPURE 3 microbi su una tua carta" (Imported
    Hydrogen), o "aggiungi 1 risorsa alla carta che hai appena giocato
    OPPURE prendi 1 pianta" (Viral Enhancers).
    """
    card: Card                                  # la carta che chiede la scelta
    alternatives: tuple[CardAction, ...]
    only_target: str | None = None              # le risorse possono andare solo su questa carta


@dataclass
class Card:
    """Una carta progetto (o un preludio), descritta solo da dati."""

    name: str
    cost: int
    type: CardType = CardType.AUTOMATED
    tags: dict[Tag, int] = field(default_factory=dict)
    requirements: Requirements = field(default_factory=Requirements)
    # Risorse che ottieni subito (valori negativi = le perdi).
    resources: dict[Resource, int] = field(default_factory=dict)
    # Variazioni di produzione (valori negativi = diminuzioni).
    production: dict[Resource, int] = field(default_factory=dict)
    temperature_steps: int = 0
    oxygen_steps: int = 0
    terraform_rating: int = 0                  # TR guadagnato direttamente
    # Tessere da piazzare, in ordine. Si può scrivere solo il tipo (TileType.CITY)
    # oppure tipo + regola (TilePlacement(TileType.CITY, PlacementRule.VOLCANIC)).
    tiles: tuple[TileType | TilePlacement, ...] = ()
    draw_cards: int = 0                        # carte da pescare
    draw_tag: Tag | None = None                # ...solo carte con questo tag

    # --- Attacchi agli altri giocatori -------------------------------------
    remove_any_plants: int = 0                 # togli fino a N piante a un giocatore
    # Riduci di N la produzione di un giocatore (obbligatorio: se nessuno
    # ne ha abbastanza, la carta non si gioca). Es. (Resource.PLANTS, 1).
    decrease_any_production: tuple[Resource, int] | None = None
    # Togli FINO A N di una risorsa a un giocatore, scegliendo tra queste opzioni.
    # Es. Sabotage: ((Resource.TITANIUM, 3), (Resource.STEEL, 4), (Resource.MEGACREDITS, 7)).
    # La risorsa può anche essere una risorsa su carta (CardResource.ANIMAL).
    raid: tuple[tuple[Resource | CardResource, int], ...] = ()
    raid_steals: bool = False                  # True: quello che togli lo prendi tu
    flood_raid: int = 0                        # Flooding: togli N M€ a chi ha una tessera vicino all'oceano
    victory_points: int = 0
    expansion: str = "base"     # "base", "corporate_era" o "prelude"

    # --- Effetti permanenti (carte blu) ---------------------------------
    # Sconto sulle carte giocate dopo: tag -> M€ PER OGNI TAG di quel tipo
    # sulla carta giocata. None = su tutte le carte (una volta).
    discounts: dict[Tag | None, int] = field(default_factory=dict)
    # Come sopra, ma una volta sola per carta anche se ha più tag (Mass Converter).
    discounts_once: dict[Tag, int] = field(default_factory=dict)
    requirement_leeway: int = 0     # come Inventrix: requisiti ±N passi
    steel_value_bonus: int = 0      # Advanced Alloys: l'acciaio vale 1 in più
    titanium_value_bonus: int = 0

    # --- Risorse sopra la carta e punti vittoria variabili -----------------
    resource_type: CardResource | None = None
    starting_resources: int = 0     # risorse messe sulla carta quando la giochi
    # PV per risorse: (punti, ogni_quante). (1, 2) = 1 PV ogni 2 risorse.
    resource_vp: tuple[int, int] | None = None
    vp_per_tag: Tag | None = None   # 1 PV per ogni tag di questo tipo che hai
    vp_per_cities: int = 0          # 1 PV ogni N città su Marte (di chiunque)
    vp_if_any_resource: int = 0     # Search For Life: 3 PV se hai almeno 1 risorsa qui
    # Psychrophiles: le risorse qui valgono N M€ per pagare le carte con quel tag.
    resources_as_payment: tuple[Tag, int] | None = None

    # --- Scelte e risorse su altre carte ------------------------------------------
    # Quando giochi la carta scegli UNA di queste alternative (Artificial
    # Photosynthesis: +2 produzione di energia OPPURE +1 di piante).
    choices: tuple[CardAction, ...] = ()
    # Risorse da mettere su tue carte: (tipo, quante). Imported Nitrogen:
    # ((MICROBE, 3), (ANIMAL, 2)). Tipo None = su una carta che ha già risorse.
    add_to_cards: tuple[tuple[CardResource | None, int], ...] = ()
    keep_cards: int = 0             # pesca draw_cards carte e ne tieni solo queste

    # --- Effetti che dipendono dalla situazione (carte "di potenziale") ------------
    # Satellites: +1 produzione di M€ per ogni tag spazio. Valgono poco
    # all'inizio e molto più avanti, quando i tag (o le città) sono di più.
    scaled_production: dict[Resource, Scaled] = field(default_factory=dict)
    scaled_resources: dict[Resource, Scaled] = field(default_factory=dict)
    scaled_tr: Scaled | None = None               # Terraforming Ganymede
    # Effetti sulla PROSSIMA carta che giochi in questa generazione.
    next_card_discount: int = 0                   # Indentured Workers: -8 M€
    next_card_leeway: int = 0                     # Special Design: requisiti ±2
    play_card_now: bool = False                   # Eccentric Sponsor: gioca subito una carta

    # --- Azioni (carte blu) ---------------------------------------------------
    # Le alternative tra cui scegliere quando usi l'azione (di solito una sola).
    actions: tuple[CardAction, ...] = ()

    # Calcolato una volta alla creazione (non si passa al costruttore): il motore
    # chiede "è una carta blu?" centinaia di migliaia di volte, e leggere un
    # vero/falso è molto più veloce che confrontare ogni volta il tipo.
    is_active: bool = field(init=False, default=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.is_active = self.type is CardType.ACTIVE
        # Da qui in poi le tessere sono sempre TilePlacement, anche se scritte come TileType.
        self.tiles = tuple(as_placement(t) for t in self.tiles)

    def card_discount(self, other: Card) -> int:
        """Lo sconto che QUESTA carta (in gioco) concede alla carta `other`."""
        total = 0
        for tag, amount in self.discounts.items():
            total += amount if tag is None else amount * other.tags.get(tag, 0)
        for tag, amount in self.discounts_once.items():
            if tag in other.tags:
                total += amount
        return total

    def variable_points(self, player: Player, resources_here: int, total_cities: int) -> int:
        """Punti vittoria che dipendono dalla situazione a fine partita."""
        points = 0
        if self.resource_vp:
            each, per = self.resource_vp
            points += each * (resources_here // per)
        if self.vp_per_tag:
            points += player.tag_count(self.vp_per_tag, wild=False)
        if self.vp_per_cities:
            points += total_cities // self.vp_per_cities
        if self.vp_if_any_resource and resources_here > 0:
            points += self.vp_if_any_resource
        return points

    def counted_tags(self) -> dict[Tag, int]:
        """I tag che contano una volta che la carta è in gioco.

        Un evento viene girato a faccia in giù: resta solo il tag evento.
        """
        if self.type is CardType.EVENT:
            return {Tag.EVENT: self.tags.get(Tag.EVENT, 0)}
        return self.tags

    # --- Si può giocare? ---------------------------------------------------

    def payment_for(self, player: Player, cost: int | None = None,
                    rules: PaymentRules = STANDARD_PAYMENT, microbes: int = 0,
                    allow_steel: bool = True, allow_titanium: bool = True) -> Payment | None:
        """Calcola come pagare la carta, o None se non te la puoi permettere.

        cost: il prezzo da pagare, se diverso da quello stampato (sconti).
        microbes: microbi di Psychrophiles utilizzabili (solo per carte pianta:
        lo decide il motore). Acciaio solo per tag edificio, titanio per tag spazio.
        allow_steel / allow_titanium: False se il giocatore preferisce tenerli.
        """
        return pay_with_metals(player, self.cost if cost is None else cost, rules,
                               use_steel=allow_steel and Tag.BUILDING in self.tags,
                               use_titanium=allow_titanium and Tag.SPACE in self.tags,
                               microbes=microbes)

    def production_change_is_possible(self, player: Player) -> bool:
        """Le diminuzioni di produzione non possono scendere sotto il minimo."""
        for resource, amount in self.production.items():
            minimum = MIN_MC_PRODUCTION if resource is Resource.MEGACREDITS else 0
            if player.production[resource] + amount < minimum:
                return False
        return True

    def resource_loss_is_possible(self, player: Player) -> bool:
        """Se la carta ti fa perdere risorse, devi averle."""
        return all(player.resources[r] + amount >= 0
                   for r, amount in self.resources.items())

    def can_be_played(self, state: GameState, player: Player, cost: int | None = None,
                      rules: PaymentRules = STANDARD_PAYMENT, leeway: int = 0,
                      microbes: int = 0) -> bool:
        """Verifica tutte le condizioni: è la "verifica di azione legale".

        cost, rules e leeway servono per sconti e poteri delle corporazioni:
        li calcola il motore (Game) e li passa qui.
        """
        return (
            self.requirements.are_met(state, player, leeway)
            and self.payment_for(player, cost, rules, microbes) is not None
            and self.production_change_is_possible(player)
            and self.resource_loss_is_possible(player)
        )

    # --- Descrizione per il terminale --------------------------------------

    def describe(self) -> str:
        parts = [self.name if self.type is CardType.PRELUDE else f"{self.name} ({self.cost} M€)"]
        if self.type is CardType.EVENT:
            parts.append("EVENTO")
        requirements = self.requirements.describe()
        if requirements:
            parts.append("richiede " + requirements)
        if self.tags:
            parts.append("tag: " + ", ".join(
                f"{tag.value}" + (f"×{n}" if n > 1 else "") for tag, n in self.tags.items()))
        if self.production:
            parts.append("produzione: " + ", ".join(
                f"{n:+d} {r.value}" for r, n in self.production.items()))
        if self.resources:
            parts.append("subito: " + ", ".join(
                f"{n:+d} {r.value}" for r, n in self.resources.items()))
        if self.temperature_steps:
            parts.append(f"temperatura +{self.temperature_steps}")
        if self.oxygen_steps:
            parts.append(f"ossigeno +{self.oxygen_steps}")
        if self.terraform_rating:
            parts.append(f"TR +{self.terraform_rating}")
        if self.tiles:
            parts.append("piazza: " + ", ".join(tile.describe() for tile in self.tiles))
        if self.draw_cards and self.keep_cards:
            parts.append(f"guarda {self.draw_cards} carte e tienine {self.keep_cards}")
        elif self.draw_cards:
            which = f" con tag {self.draw_tag.value}" if self.draw_tag else ""
            parts.append(f"pesca {self.draw_cards} carte{which}")
        for kind, n in self.add_to_cards:
            what = kind.value if kind else "risorsa (su una carta che ne ha già)"
            parts.append(f"+{n} {what} su una tua carta")
        if self.choices:
            parts.append("SCEGLI: " + " OPPURE ".join(c.describe() for c in self.choices))
        for resource, scaled in self.scaled_production.items():
            parts.append(f"produzione di {resource.value}: +{scaled.describe()}")
        for resource, scaled in self.scaled_resources.items():
            parts.append(f"{resource.value}: +{scaled.describe()}")
        if self.scaled_tr:
            parts.append(f"TR: +{self.scaled_tr.describe()}")
        if self.next_card_discount:
            parts.append(f"la prossima carta costa {self.next_card_discount} M€ in meno")
        if self.next_card_leeway:
            parts.append("la prossima carta ignora i requisiti globali" if self.next_card_leeway >= 50
                         else f"la prossima carta: requisiti ±{self.next_card_leeway}")
        if self.play_card_now:
            parts.append("gioca subito una carta dalla mano")
        if self.remove_any_plants:
            parts.append(f"togli fino a {self.remove_any_plants} piante a un giocatore")
        if self.decrease_any_production:
            resource, amount = self.decrease_any_production
            parts.append(f"-{amount} produzione di {resource.value} a un giocatore")
        if self.raid:
            verb = "ruba" if self.raid_steals else "togli"
            parts.append(f"{verb} fino a " + " oppure ".join(
                f"{amount} {what.value}" for what, amount in self.raid) + " a un giocatore")
        if self.flood_raid:
            parts.append(f"togli {self.flood_raid} M€ a chi ha una tessera vicina all'oceano")
        if self.victory_points:
            parts.append(f"{self.victory_points} PV")
        if self.type is CardType.ACTIVE:
            parts.append("BLU")
        if self.name in EFFECT_TEXTS:          # effetti "a scatto" (tm_sim/card_effects.py)
            parts.append("effetto: " + EFFECT_TEXTS[self.name])
        for tag, amount in self.discounts.items():
            parts.append(f"sconto {amount} M€ " + (f"per tag {tag.value}" if tag else "su tutte le carte"))
        for tag, amount in self.discounts_once.items():
            parts.append(f"sconto {amount} M€ sulle carte {tag.value}")
        if self.requirement_leeway:
            parts.append(f"requisiti ±{self.requirement_leeway} passi")
        if self.steel_value_bonus or self.titanium_value_bonus:
            parts.append("acciaio e titanio valgono 1 in più")
        if self.resource_type:
            parts.append(f"accumula {self.resource_type.value}")
        if self.resource_vp:
            each, per = self.resource_vp
            parts.append(f"{each} PV ogni {per} {self.resource_type.value}")
        if self.vp_per_tag:
            parts.append(f"1 PV per tag {self.vp_per_tag.value}")
        if self.vp_per_cities:
            parts.append(f"1 PV ogni {self.vp_per_cities} città")
        if self.vp_if_any_resource:
            parts.append(f"{self.vp_if_any_resource} PV se ha almeno 1 {self.resource_type.value}")
        if self.resources_as_payment:
            tag, value = self.resources_as_payment
            parts.append(f"{self.resource_type.value} qui = {value} M€ per carte {tag.value}")
        if self.actions:
            parts.append("AZIONE: " + " OPPURE ".join(a.describe(self.resource_type)
                                                      for a in self.actions))
        return " | ".join(parts)
