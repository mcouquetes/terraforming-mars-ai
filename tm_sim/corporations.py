"""Le corporazioni del gioco base, di Corporate Era e di Prelude.

Ogni corporazione è fatta di:
- DATI: soldi iniziali, tag, produzioni e risorse di partenza;
- MODIFICATORI: sconti, valore del titanio, piante per una foresta...;
- POTERI: piccole funzioni che il motore chiama nei momenti giusti
  (quando giochi una carta, quando qualcuno piazza una tessera, quando
  paghi). Si chiamano "trigger", cioè "inneschi".

I numeri sono verificati sulla fonte open source (vedi README).
Le regole "compresa questa" sono già conteggiate nei valori di partenza:
per esempio Saturn Systems parte con +1 produzione di M€ perché il suo
stesso tag gioviano attiva il suo potere.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from tm_sim.fastenum import FastEnum
from typing import TYPE_CHECKING

from tm_sim.actions import ActionType
from tm_sim.board import Bonus, Space, TileType, is_city
from tm_sim.cards import STANDARD_PAYMENT, Card, CardType, PaymentRules, Tag
from tm_sim.state import Player, Resource

if TYPE_CHECKING:
    from tm_sim.game import Game

MC = Resource.MEGACREDITS


class FirstAction(FastEnum):
    """Azioni che alcune corporazioni DEVONO fare come prima azione."""
    PLACE_CITY = "piazza una città"
    DRAW_3_CARDS = "pesca 3 carte"
    FUND_AWARD_FREE = "finanzia gratis un riconoscimento"
    PLAY_PRELUDE_FROM_3 = "pesca 3 preludi e giocane 1"


@dataclass
class Corporation:
    name: str
    starting_megacredits: int
    expansion: str
    description: str
    tags: dict[Tag, int] = field(default_factory=dict)
    production: dict[Resource, int] = field(default_factory=dict)
    resources: dict[Resource, int] = field(default_factory=dict)
    starting_draw: int = 0

    # Modificatori
    card_discounts: dict[Tag, int] = field(default_factory=dict)
    standard_project_discounts: dict[ActionType, int] = field(default_factory=dict)
    plants_per_greenery: int = 8
    titanium_value: int = 3
    heat_as_megacredits: bool = False
    requirement_leeway: int = 0

    # Azione iniziale obbligatoria e azione ripetibile (una per generazione)
    first_action: FirstAction | None = None
    action_options: Callable[[Game, Player], list[str]] | None = None
    perform_action: Callable[[Game, Player, str], None] | None = None

    # Trigger
    on_card_played: Callable[[Game, Player, Card], None] | None = None
    on_any_card_played: Callable[[Game, Player, Player, Card], None] | None = None
    on_tile_placed: Callable[[Game, Player, Player, Space, TileType], None] | None = None
    on_payment: Callable[[Game, Player, int], None] | None = None

    @property
    def payment_rules(self) -> PaymentRules:
        if self.titanium_value == 3 and not self.heat_as_megacredits:
            return STANDARD_PAYMENT
        return PaymentRules(titanium_value=self.titanium_value,
                            heat_as_megacredits=self.heat_as_megacredits)

    def card_discount(self, card: Card) -> int:
        """Lo sconto vale per ogni tag: una carta con 2 tag Terra, con Teractor, costa 6 in meno."""
        return sum(amount * card.tags.get(tag, 0) for tag, amount in self.card_discounts.items())


# ---------------------------------------------------------------------------
# I poteri, uno per corporazione
# ---------------------------------------------------------------------------

def credicor_payment(game: Game, owner: Player, base_cost: int) -> None:
    """Dopo aver pagato una carta o un progetto standard da 20 M€ o più: +4 M€."""
    if base_cost >= 20:
        owner.gain(MC, 4)


def interplanetary_card_played(game: Game, owner: Player, card: Card) -> None:
    """Quando giochi un evento: +2 M€."""
    if card.type is CardType.EVENT:
        owner.gain(MC, 2)


def mining_guild_tile_placed(game: Game, owner: Player, placer: Player,
                             space: Space, tile: TileType) -> None:
    """Quando piazzi una tessera su una casella con acciaio o titanio: +1 produzione di acciaio."""
    if placer is owner and any(b in (Bonus.STEEL, Bonus.TITANIUM) for b in space.bonuses):
        owner.change_production(Resource.STEEL, 1)


def tharsis_tile_placed(game: Game, owner: Player, placer: Player,
                        space: Space, tile: TileType) -> None:
    """Ogni città su Marte: +1 produzione di M€. Se l'hai piazzata tu: anche +3 M€
    (anche se è nello spazio, come Ganymede Colony)."""
    if is_city(tile):
        if space.on_mars:
            owner.change_production(MC, 1)
        if placer is owner:
            owner.gain(MC, 3)


def saturn_any_card_played(game: Game, owner: Player, player: Player, card: Card) -> None:
    """Ogni tag gioviano giocato da chiunque: +1 produzione di M€."""
    jovian = card.tags.get(Tag.JOVIAN, 0)
    if jovian:
        owner.change_production(MC, jovian)


def point_luna_card_played(game: Game, owner: Player, card: Card) -> None:
    """Ogni tag Terra che giochi: peschi 1 carta."""
    earth = card.tags.get(Tag.EARTH, 0)
    if earth:
        game.draw_cards(owner, earth)


def vitor_card_played(game: Game, owner: Player, card: Card) -> None:
    """Quando giochi una carta che dà punti vittoria: +3 M€."""
    if card.victory_points > 0:
        owner.gain(MC, 3)


UNMI_COST = 3


def unmi_options(game: Game, player: Player) -> list[str]:
    """Se hai alzato il TR in questa generazione, puoi pagare 3 M€ per +1 TR."""
    if player.tr_raised_this_generation and game.can_pay(player, UNMI_COST):
        return ["+1 TR"]
    return []


def unmi_action(game: Game, player: Player, option: str) -> None:
    game.pay(player, UNMI_COST)
    player.raise_tr(1)


ROBINSON_COST = 4


def robinson_options(game: Game, player: Player) -> list[str]:
    """Paga 4 M€ per alzare di 1 la tua produzione più bassa (a scelta, se pari)."""
    if not game.can_pay(player, ROBINSON_COST):
        return []
    lowest = min(player.production.values())
    return [r.value for r, amount in player.production.items() if amount == lowest]


def robinson_action(game: Game, player: Player, option: str) -> None:
    game.pay(player, ROBINSON_COST)
    player.change_production(Resource(option), 1)


# ---------------------------------------------------------------------------
# L'elenco
# ---------------------------------------------------------------------------

ALL_CORPORATIONS: list[Corporation] = [
    # --- Gioco base ---------------------------------------------------------
    Corporation("CrediCor", 57, "base",
                "+4 M€ dopo aver pagato una carta o un progetto standard da 20 M€ o più",
                on_payment=credicor_payment),
    Corporation("EcoLine", 36, "base",
                "una foresta costa 7 piante invece di 8",
                tags={Tag.PLANT: 1}, production={Resource.PLANTS: 2},
                resources={Resource.PLANTS: 3}, plants_per_greenery=7),
    Corporation("Helion", 42, "base",
                "puoi usare il calore come M€",
                tags={Tag.SPACE: 1}, production={Resource.HEAT: 3}, heat_as_megacredits=True),
    Corporation("Interplanetary Cinematics", 30, "base",
                "+2 M€ quando giochi un evento",
                tags={Tag.BUILDING: 1}, resources={Resource.STEEL: 20},
                on_card_played=interplanetary_card_played),
    Corporation("Inventrix", 45, "base",
                "requisiti dei parametri globali ±2 passi; prima azione: pesca 3 carte",
                tags={Tag.SCIENCE: 1}, requirement_leeway=2,
                first_action=FirstAction.DRAW_3_CARDS),
    Corporation("Mining Guild", 30, "base",
                "+1 produzione di acciaio quando piazzi una tessera su acciaio o titanio",
                tags={Tag.BUILDING: 2}, production={Resource.STEEL: 1},
                resources={Resource.STEEL: 5}, on_tile_placed=mining_guild_tile_placed),
    Corporation("PhoboLog", 23, "base",
                "il titanio vale 4 M€ invece di 3",
                tags={Tag.SPACE: 1}, resources={Resource.TITANIUM: 10}, titanium_value=4),
    Corporation("Tharsis Republic", 40, "base",
                "ogni città: +1 produzione di M€ (+3 M€ se è tua); prima azione: piazza una città",
                tags={Tag.BUILDING: 1}, first_action=FirstAction.PLACE_CITY,
                on_tile_placed=tharsis_tile_placed),
    Corporation("Thorgate", 48, "base",
                "carte energia e centrale elettrica costano 3 M€ in meno",
                tags={Tag.POWER: 1}, production={Resource.ENERGY: 1},
                card_discounts={Tag.POWER: 3},
                standard_project_discounts={ActionType.POWER_PLANT: 3}),
    Corporation("United Nations Mars Initiative", 40, "base",
                "azione: se hai alzato il TR in questa generazione, paga 3 M€ per +1 TR",
                tags={Tag.EARTH: 1}, action_options=unmi_options, perform_action=unmi_action),

    # --- Corporate Era ------------------------------------------------------
    Corporation("Saturn Systems", 42, "corporate_era",
                "+1 produzione di M€ per ogni tag gioviano giocato da chiunque",
                tags={Tag.JOVIAN: 1},
                production={Resource.TITANIUM: 1, MC: 1},   # +1 M€: il suo stesso tag gioviano
                on_any_card_played=saturn_any_card_played),
    Corporation("Teractor", 60, "corporate_era",
                "le carte Terra costano 3 M€ in meno",
                tags={Tag.EARTH: 1}, card_discounts={Tag.EARTH: 3}),

    # --- Prelude --------------------------------------------------------------
    Corporation("Cheung Shing MARS", 44, "prelude",
                "le carte edificio costano 2 M€ in meno",
                tags={Tag.BUILDING: 1}, production={MC: 3}, card_discounts={Tag.BUILDING: 2}),
    Corporation("Point Luna", 38, "prelude",
                "peschi 1 carta per ogni tag Terra che giochi",
                tags={Tag.SPACE: 1, Tag.EARTH: 1}, production={Resource.TITANIUM: 1},
                starting_draw=1,                            # il suo stesso tag Terra
                on_card_played=point_luna_card_played),
    Corporation("Robinson Industries", 47, "prelude",
                "azione: paga 4 M€ per +1 alla tua produzione più bassa",
                action_options=robinson_options, perform_action=robinson_action),
    Corporation("Valley Trust", 37, "prelude",
                "le carte scienza costano 2 M€ in meno; prima azione: pesca 3 preludi e giocane 1",
                tags={Tag.EARTH: 1}, card_discounts={Tag.SCIENCE: 2},
                first_action=FirstAction.PLAY_PRELUDE_FROM_3),
    Corporation("Vitor", 48, "prelude",                  # 45 + 3 per sé stessa
                "+3 M€ quando giochi una carta con punti vittoria; "
                "prima azione: finanzia gratis un riconoscimento",
                tags={Tag.EARTH: 1}, first_action=FirstAction.FUND_AWARD_FREE,
                on_card_played=vitor_card_played),
]

CORPORATIONS_BY_NAME = {c.name: c for c in ALL_CORPORATIONS}
