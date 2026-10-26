"""Stato della partita: risorse, giocatori, pianeta.

Questo modulo contiene SOLO dati e regole di base, nessuna interfaccia
e nessuna IA. Tutto il resto del progetto si appoggerà su queste classi.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from tm_sim.fastenum import FastEnum
from typing import TYPE_CHECKING

from tm_sim.board import CITY_TILES, SPECIAL_TILES, Board, Bonus, TilePlacement, TileType, as_placement

if TYPE_CHECKING:
    from tm_sim.cards import Card, Tag
    from tm_sim.corporations import Corporation


# ---------------------------------------------------------------------------
# Costanti delle regole
# ---------------------------------------------------------------------------

STARTING_TR = 20            # Terraform Rating iniziale di ogni giocatore
MIN_MC_PRODUCTION = -5      # la produzione di megacrediti può scendere fino a -5

MIN_TEMPERATURE = -30
MAX_TEMPERATURE = 8
TEMPERATURE_STEP = 2        # la temperatura sale di 2 gradi per volta
MAX_OXYGEN = 14
MAX_OCEANS = 9

# Bonus sul tracciato della temperatura: raggiungendo questi valori
# il giocatore che alza la temperatura ottiene +1 produzione di calore.
HEAT_PRODUCTION_BONUS_AT = (-24, -20)
# Raggiungendo l'8% di ossigeno, la temperatura sale di uno step.
OXYGEN_TEMPERATURE_BONUS_AT = 8
# Raggiungendo 0°C, chi ha alzato la temperatura piazza un oceano.
OCEAN_BONUS_AT_TEMPERATURE = 0
# Piazzando una tessera accanto a un oceano si guadagnano 2 M€ per oceano.
OCEAN_ADJACENCY_BONUS = 2


# ---------------------------------------------------------------------------
# Risorse
# ---------------------------------------------------------------------------

class Resource(FastEnum):
    """I sei tipi di risorsa standard.

    Usare un Enum invece di stringhe come "acciaio" evita errori di battitura:
    se scrivi Resource.STEL, Python ti segnala subito l'errore.
    """
    MEGACREDITS = "megacrediti"
    STEEL = "acciaio"
    TITANIUM = "titanio"
    PLANTS = "piante"
    ENERGY = "energia"
    HEAT = "calore"


def _zero_per_resource() -> dict[Resource, int]:
    """Crea un dizionario {risorsa: 0} per tutte le risorse."""
    return {resource: 0 for resource in Resource}


# ---------------------------------------------------------------------------
# Giocatore
# ---------------------------------------------------------------------------

@dataclass
class Player:
    """Un giocatore: TR, risorse in magazzino e produzioni."""

    name: str
    terraform_rating: int = STARTING_TR
    # field(default_factory=...) serve perché ogni giocatore deve avere
    # il SUO dizionario: la funzione viene chiamata a ogni nuovo Player.
    # Con "= {}" tutti i giocatori condividerebbero lo stesso dizionario.
    resources: dict[Resource, int] = field(default_factory=_zero_per_resource)
    production: dict[Resource, int] = field(default_factory=_zero_per_resource)
    # Finché non abbiamo la mappa, contiamo solo quante tessere possiede.
    greeneries: int = 0
    special_tiles: int = 0     # tessere speciali (Capital conta anche come città)
    cities: int = 0
    hand: list[Card] = field(default_factory=list)      # carte in mano
    played: list[Card] = field(default_factory=list)    # carte giocate (eventi inclusi)
    drafted: list[Card] = field(default_factory=list)   # carte pescate da comprare o scartare
    draft_hand: list[Card] = field(default_factory=list)  # draft: carte tra cui sceglierne una
    corporation: Corporation | None = None
    # Preparazione della partita: corporazioni e preludi tra cui scegliere,
    # e preludi tenuti ma non ancora giocati.
    corporation_choices: list[Corporation] = field(default_factory=list)
    prelude_choices: list[Card] = field(default_factory=list)
    preludes: list[Card] = field(default_factory=list)
    first_action_done: bool = True
    # Per UNMI: ha alzato il TR in questa generazione?
    tr_raised_this_generation: bool = False
    # Azioni di carte/corporazioni già usate in questa generazione.
    used_actions: set[str] = field(default_factory=set)
    # Risorse sopra le carte: nome della carta -> quante (animali, microbi...).
    card_resources: dict[str, int] = field(default_factory=dict)
    # Effetti sulla PROSSIMA carta giocata in questa generazione (Indentured
    # Workers: -8 M€; Special Design: requisiti ±2; Eccentric Sponsor...).
    next_card_discount: int = 0
    next_card_leeway: int = 0
    # Memoria dei tag in gioco (vedi tag_count): si ricalcola solo quando entra in
    # gioco una carta nuova o cambia la corporazione. Il dizionario non si modifica
    # mai, si sostituisce: così anche le copie della partita restano corrette.
    _tag_key: tuple | None = field(default=None, repr=False, compare=False)
    _tag_totals: dict = field(default_factory=dict, repr=False, compare=False)

    def add_card_resource(self, card_name: str, amount: int = 1) -> None:
        self.card_resources[card_name] = self.card_resources.get(card_name, 0) + amount

    def active_cards(self) -> list[Card]:
        """Le carte blu in gioco: le loro regole valgono per tutta la partita."""
        return [card for card in self.played if card.is_active]

    def tag_count(self, tag: Tag, wild: bool = True) -> int:
        """Quanti tag di un certo tipo hai in gioco (corporazione compresa).

        Il tag jolly (Research Coordination) vale come qualsiasi tag: per i
        requisiti, i traguardi e gli effetti. Non vale per i riconoscimenti né
        per i punti "1 PV per tag": lì si chiede wild=False.
        """
        key = (len(self.played), id(self.corporation))
        if self._tag_key != key:            # è entrata in gioco una carta: si ricontano
            totals: dict = {}
            for card in self.played:
                for counted, amount in card.counted_tags().items():
                    totals[counted] = totals.get(counted, 0) + amount
            self._tag_totals, self._tag_key = totals, key
        count = self._tag_totals.get(tag, 0)
        if self.corporation is not None:
            count += self.corporation.tags.get(tag, 0)
        wild_tag = type(tag).WILD
        if wild and tag is not wild_tag:
            count += self._tag_totals.get(wild_tag, 0)
        return count

    def raise_tr(self, steps: int = 1) -> None:
        """Alza il Terraform Rating. Usare sempre questo metodo, così
        teniamo traccia di chi ha alzato il TR in questa generazione."""
        if steps > 0:
            self.terraform_rating += steps
            self.tr_raised_this_generation = True

    def victory_points(self) -> int:
        """Punti vittoria attuali.

        Per ora: TR + 1 punto per ogni foresta + i PV delle carte giocate.
        Più avanti aggiungeremo i punti delle città (foreste adiacenti).
        Traguardi e riconoscimenti dipendono anche dagli avversari, quindi
        li somma Game.score().
        """
        card_points = sum(card.victory_points for card in self.played)
        return self.terraform_rating + self.greeneries + card_points

    def gain(self, resource: Resource, amount: int) -> None:
        """Aggiunge risorse al magazzino."""
        if amount < 0:
            raise ValueError("Per togliere risorse usa spend()")
        self.resources[resource] += amount

    def spend(self, resource: Resource, amount: int) -> None:
        """Toglie risorse dal magazzino; errore se non bastano."""
        if amount < 0:
            raise ValueError("La quantità da spendere non può essere negativa")
        if self.resources[resource] < amount:
            raise ValueError(
                f"{self.name} non ha abbastanza {resource.value}: "
                f"ne ha {self.resources[resource]}, servono {amount}"
            )
        self.resources[resource] -= amount

    def change_production(self, resource: Resource, amount: int) -> None:
        """Modifica una produzione (amount può essere negativo).

        Regola: la produzione di megacrediti non scende sotto -5,
        tutte le altre non scendono sotto 0. Una mossa che violerebbe
        questo limite è illegale, quindi solleviamo un errore.
        """
        minimum = MIN_MC_PRODUCTION if resource is Resource.MEGACREDITS else 0
        new_value = self.production[resource] + amount
        if new_value < minimum:
            raise ValueError(
                f"La produzione di {resource.value} non può scendere sotto {minimum}"
            )
        self.production[resource] = new_value

    def production_phase(self) -> None:
        """Fase di produzione di fine generazione, nell'ordine del regolamento."""
        # 1. Tutta l'energia rimasta diventa calore.
        self.resources[Resource.HEAT] += self.resources[Resource.ENERGY]
        self.resources[Resource.ENERGY] = 0

        # 2. Megacrediti = produzione di megacrediti + Terraform Rating.
        self.resources[Resource.MEGACREDITS] += (
            self.production[Resource.MEGACREDITS] + self.terraform_rating
        )

        # 3. Tutte le altre risorse ricevono la loro produzione.
        for resource in Resource:
            if resource is not Resource.MEGACREDITS:
                self.resources[resource] += self.production[resource]


# ---------------------------------------------------------------------------
# Pianeta
# ---------------------------------------------------------------------------

@dataclass
class Planet:
    """I tre parametri globali di Marte."""

    temperature: int = MIN_TEMPERATURE
    oxygen: int = 0
    oceans: int = 0

    def is_terraformed(self) -> bool:
        """La partita finisce (a fine generazione) quando tutti e tre sono al massimo."""
        return (
            self.temperature >= MAX_TEMPERATURE
            and self.oxygen >= MAX_OXYGEN
            and self.oceans >= MAX_OCEANS
        )


# ---------------------------------------------------------------------------
# Stato completo della partita
# ---------------------------------------------------------------------------

@dataclass
class GameState:
    """Tutto ciò che serve per descrivere una partita in un dato momento.

    I metodi che alzano i parametri globali stanno qui, e non in Planet,
    perché devono toccare sia il pianeta sia il giocatore (TR e bonus).
    """

    players: list[Player]
    planet: Planet = field(default_factory=Planet)
    generation: int = 1
    # nome del traguardo -> nome del giocatore che lo ha reclamato
    claimed_milestones: dict[str, str] = field(default_factory=dict)
    # nomi dei riconoscimenti finanziati, nell'ordine in cui sono stati pagati
    funded_awards: list[str] = field(default_factory=list)
    board: Board = field(default_factory=Board)
    # Tessere che il giocatore di turno deve ancora piazzare, in ordine.
    pending_tiles: list[TilePlacement] = field(default_factory=list)

    def raise_temperature(self, player: Player, steps: int = 1) -> int:
        """Alza la temperatura di `steps` step (2 gradi ciascuno).

        Ogni step effettivamente fatto dà +1 TR al giocatore.
        Se la temperatura è già al massimo, non succede nulla.
        Restituisce quanti step sono stati fatti davvero.
        """
        done = 0
        for _ in range(steps):
            if self.planet.temperature >= MAX_TEMPERATURE:
                break
            self.planet.temperature += TEMPERATURE_STEP
            player.raise_tr(1)
            done += 1
            if self.planet.temperature in HEAT_PRODUCTION_BONUS_AT:
                player.change_production(Resource.HEAT, 1)
            if self.planet.temperature == OCEAN_BONUS_AT_TEMPERATURE:
                self.queue_tile(TileType.OCEAN)
        return done

    def raise_oxygen(self, player: Player, steps: int = 1) -> int:
        """Alza l'ossigeno di `steps` punti percentuali (+1 TR ciascuno).

        Raggiungendo l'8% scatta anche un aumento di temperatura,
        che dà a sua volta TR al giocatore.
        """
        done = 0
        for _ in range(steps):
            if self.planet.oxygen >= MAX_OXYGEN:
                break
            self.planet.oxygen += 1
            player.raise_tr(1)
            done += 1
            if self.planet.oxygen == OXYGEN_TEMPERATURE_BONUS_AT:
                self.raise_temperature(player, 1)
        return done

    def oceans_remaining(self) -> int:
        """Quanti oceani si possono ancora piazzare (contando quelli in attesa)."""
        waiting = sum(1 for p in self.pending_tiles if p.tile is TileType.OCEAN)
        return MAX_OCEANS - self.planet.oceans - waiting

    def queue_tile(self, tile: TileType | TilePlacement) -> None:
        """Mette una tessera "in attesa": il giocatore di turno dovrà
        scegliere dove piazzarla. Un oceano oltre il nono viene ignorato."""
        placement = as_placement(tile)
        if placement.tile is TileType.OCEAN and self.oceans_remaining() <= 0:
            return
        self.pending_tiles.append(placement)

    def place_tile(self, player: Player, tile: TileType | TilePlacement, space_id: str) -> int:
        """Piazza una tessera sulla mappa e applica tutti i suoi effetti.

        Restituisce quante carte il giocatore deve pescare (bonus della
        casella): il mazzo lo gestisce Game, non lo stato.
        """
        tile = as_placement(tile).tile
        space = self.board.place(tile, space_id, player.name)
        if tile is TileType.CLAIM:        # Land Claim: nessun bonus, nessun effetto
            return 0

        # Bonus di piazzamento: risorse stampate + 2 M€ per oceano adiacente.
        cards_to_draw = 0
        for bonus in space.bonuses:
            if bonus is Bonus.STEEL:
                player.gain(Resource.STEEL, 1)
            elif bonus is Bonus.TITANIUM:
                player.gain(Resource.TITANIUM, 1)
            elif bonus is Bonus.PLANT:
                player.gain(Resource.PLANTS, 1)
            elif bonus is Bonus.CARD:
                cards_to_draw += 1
        player.gain(Resource.MEGACREDITS, OCEAN_ADJACENCY_BONUS * self.board.adjacent_oceans(space))

        # Effetti della tessera.
        if tile is TileType.OCEAN:
            self.planet.oceans += 1
            player.raise_tr(1)
        elif tile is TileType.GREENERY:
            player.greeneries += 1
            self.raise_oxygen(player, 1)
        elif tile in CITY_TILES:
            player.cities += 1
        if tile in SPECIAL_TILES:
            player.special_tiles += 1
        if tile in (TileType.MINING_AREA, TileType.MINING_RIGHTS):
            # Le miniere danno +1 alla produzione del metallo stampato sulla casella.
            metal = Resource.TITANIUM if Bonus.TITANIUM in space.bonuses else Resource.STEEL
            player.change_production(metal, 1)

        return cards_to_draw

    def end_generation(self) -> None:
        """Fase di produzione per tutti, poi si passa alla generazione successiva."""
        for player in self.players:
            player.production_phase()
            player.tr_raised_this_generation = False
            player.used_actions.clear()
            player.next_card_discount = player.next_card_leeway = 0
        self.generation += 1
