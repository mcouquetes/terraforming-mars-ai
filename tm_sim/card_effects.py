"""Gli effetti "a scatto" delle carte blu, scritti a mano.

Alcune carte blu reagiscono a quello che succede in partita:
"quando qualcuno piazza un oceano, guadagni 2 piante". Questo non si può
descrivere con semplici dati, quindi per ogni carta scriviamo una piccola
funzione, come per i poteri delle corporazioni.

Il motore chiama queste funzioni in tre momenti:
- on_card_played:  quando il PROPRIETARIO della carta gioca una carta
                   (compresa la carta stessa, se la regola dice "compresa questa");
- on_tile_placed:  quando QUALSIASI giocatore piazza una tessera;
- on_standard_project: quando il proprietario usa un progetto standard.

Lo script di importazione legge CARD_TRIGGERS: le carte elencate qui sono
considerate "gestite" anche se nella fonte hanno codice personalizzato.
I dati della carta (costo, tag, requisiti...) restano importati in automatico.

Alcuni effetti chiedono una SCELTA (Viral Enhancers, Mars University,
Olympus Conference): la funzione non decide, ma aggiunge una PendingChoice
alla partita, e la scelta la fa il giocatore come per le altre mosse.

In fondo al file ci sono anche le AZIONI che non si descrivono con
semplici dati (SPECIAL_ACTIONS): Search For Life, Power Infrastructure e
"scarta una carta per pescarne un'altra" (Mars University).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tm_sim.board import Space, TileType, is_city
from tm_sim.cards import EFFECT_TEXTS, Card, CardAction, CardResource, CardType, PendingChoice, Tag
from tm_sim.state import Player, Resource

if TYPE_CHECKING:
    from tm_sim.actions import ActionType
    from tm_sim.game import Game


@dataclass(frozen=True)
class CardTriggers:
    on_card_played: Callable[[Game, Player, Card, Card], None] | None = None
    on_tile_placed: Callable[[Game, Player, Player, Space, TileType, Card], None] | None = None
    on_standard_project: Callable[[Game, Player, ActionType, Card], None] | None = None


# --- Le funzioni -------------------------------------------------------------
# Convenzione dei parametri: owner = proprietario della carta blu,
# this = la carta blu stessa, played = la carta appena giocata.

def arctic_algae_tile(game, owner, placer, space, tile, this):
    """Quando chiunque piazza un oceano: +2 piante."""
    if tile is TileType.OCEAN:
        owner.gain(Resource.PLANTS, 2)


def decomposers_played(game, owner, played, this):
    """Quando giochi un tag pianta, microbo o animale (compresa questa): +1 microbo qui."""
    count = sum(played.tags.get(tag, 0) for tag in (Tag.PLANT, Tag.MICROBE, Tag.ANIMAL))
    if count:
        owner.add_card_resource(this.name, count)


def pets_tile(game, owner, placer, space, tile, this):
    """Quando chiunque piazza una città: +1 animale qui."""
    if is_city(tile):
        owner.add_card_resource(this.name, 1)


def media_group_played(game, owner, played, this):
    """Quando giochi un evento: +3 M€."""
    if played.type is CardType.EVENT:
        owner.gain(Resource.MEGACREDITS, 3)


def optimal_aerobraking_played(game, owner, played, this):
    """Quando giochi un evento spazio: +3 M€ e +3 calore."""
    if played.type is CardType.EVENT and Tag.SPACE in played.tags:
        owner.gain(Resource.MEGACREDITS, 3)
        owner.gain(Resource.HEAT, 3)


def rover_construction_tile(game, owner, placer, space, tile, this):
    """Quando chiunque piazza una città: +2 M€."""
    if is_city(tile):
        owner.gain(Resource.MEGACREDITS, 2)


def immigrant_city_tile(game, owner, placer, space, tile, this):
    """Quando chiunque piazza una città (compresa la sua): +1 produzione di M€."""
    if is_city(tile):
        owner.change_production(Resource.MEGACREDITS, 1)


def ecological_zone_played(game, owner, played, this):
    """Quando giochi un tag animale o pianta (compresi i suoi due): +1 animale qui."""
    count = sum(played.tags.get(tag, 0) for tag in (Tag.ANIMAL, Tag.PLANT))
    if count:
        owner.add_card_resource(this.name, count)


def herbivores_tile(game, owner, placer, space, tile, this):
    """Quando TU piazzi una foresta: +1 animale qui."""
    if placer is owner and tile is TileType.GREENERY:
        owner.add_card_resource(this.name, 1)


def viral_enhancers_played(game, owner, played, this):
    """Per ogni tag pianta, microbo o animale (compresa questa): +1 pianta, oppure
    +1 risorsa sulla carta appena giocata (se è una carta che accumula animali o microbi)."""
    count = sum(played.tags.get(tag, 0) for tag in (Tag.PLANT, Tag.MICROBE, Tag.ANIMAL))
    if not count:
        return
    if played.resource_type not in (CardResource.ANIMAL, CardResource.MICROBE):
        owner.gain(Resource.PLANTS, count)
        return
    for _ in range(count):
        game.pending_choices.append(PendingChoice(
            this, (CardAction(gain={Resource.PLANTS: 1}),
                   CardAction(add_to_other_card=(played.resource_type, 1))),
            only_target=played.name))


def mars_university_played(game, owner, played, this):
    """Per ogni tag scienza (compresa questa): puoi scartare una carta dalla mano e pescarne una."""
    for _ in range(played.tags.get(Tag.SCIENCE, 0)):
        game.pending_choices.append(PendingChoice(
            this, (CardAction(), CardAction(special="discard_draw"))))


def olympus_conference_played(game, owner, played, this):
    """Per ogni tag scienza (compresa questa): +1 scienza qui, oppure togline una per pescare.
    Senza risorse sulla carta non c'è scelta: si aggiunge."""
    for _ in range(played.tags.get(Tag.SCIENCE, 0)):
        game.pending_choices.append(PendingChoice(
            this, (CardAction(add_here=1), CardAction(spend_here=1, draw_cards=1))))


def standard_technology_project(game, owner, project, this):
    """Dopo aver pagato un progetto standard (non la vendita di brevetti): +3 M€."""
    owner.gain(Resource.MEGACREDITS, 3)


CARD_TRIGGERS: dict[str, CardTriggers] = {
    "Arctic Algae": CardTriggers(on_tile_placed=arctic_algae_tile),
    "Decomposers": CardTriggers(on_card_played=decomposers_played),
    "Pets": CardTriggers(on_tile_placed=pets_tile),
    "Media Group": CardTriggers(on_card_played=media_group_played),
    "Optimal Aerobraking": CardTriggers(on_card_played=optimal_aerobraking_played),
    "Rover Construction": CardTriggers(on_tile_placed=rover_construction_tile),
    "Standard Technology": CardTriggers(on_standard_project=standard_technology_project),
    "Immigrant City": CardTriggers(on_tile_placed=immigrant_city_tile),
    "Ecological Zone": CardTriggers(on_card_played=ecological_zone_played),
    "Herbivores": CardTriggers(on_tile_placed=herbivores_tile),
    "Viral Enhancers": CardTriggers(on_card_played=viral_enhancers_played),
    "Mars University": CardTriggers(on_card_played=mars_university_played),
    "Olympus Conference": CardTriggers(on_card_played=olympus_conference_played),
}

# Il testo degli effetti, mostrato nelle descrizioni delle carte (play.py, insegna.py).
EFFECT_TEXTS.update({
    "Arctic Algae": "quando chiunque piazza un oceano, +2 piante",
    "Decomposers": "quando giochi un tag pianta, microbo o animale (compresa questa), +1 microbo qui",
    "Pets": "quando chiunque piazza una città, +1 animale qui; i suoi animali non si possono togliere",
    "Protected Habitats": "gli avversari non possono toglierti piante, animali e microbi",
    "Media Group": "quando giochi un evento, +3 M€",
    "Optimal Aerobraking": "quando giochi un evento spazio, +3 M€ e +3 calore",
    "Rover Construction": "quando chiunque piazza una città, +2 M€",
    "Standard Technology": "dopo aver usato un progetto standard (non la vendita di brevetti), +3 M€",
    "Immigrant City": "quando chiunque piazza una città (compresa questa), +1 produzione di M€",
    "Ecological Zone": "quando giochi un tag animale o pianta (compresi i suoi), +1 animale qui",
    "Herbivores": "quando piazzi una foresta, +1 animale qui",
    "Viral Enhancers": "per ogni tag pianta, microbo o animale che giochi (compresa questa): "
                       "+1 pianta oppure +1 risorsa sulla carta giocata",
    "Mars University": "per ogni tag scienza che giochi (compresa questa): puoi scartare una "
                       "carta dalla mano e pescarne una",
    "Olympus Conference": "quando giochi un tag scienza (compresa questa) SCEGLI: aggiungi 1 "
                          "scienza a questa carta OPPURE togline 1 per pescare una carta",
})


# --- Azioni scritte a mano ----------------------------------------------------
# Quasi tutte le azioni delle carte blu sono dati (CardAction in cards.py).
# Queste due no: le collega alla carta il campo CardAction.special.
#   options(game, player, card) -> le scelte possibili ([None] = nessuna scelta,
#                                  [] = l'azione adesso non si può usare)
#   perform(game, player, card, scelta)

@dataclass(frozen=True)
class SpecialAction:
    options: Callable[[Game, Player, Card], list[str | None]]
    perform: Callable[[Game, Player, Card, str | None], None]


def search_for_life_options(game, player, card):
    """Serve almeno una carta da scoprire (nel mazzo o negli scarti)."""
    return [None] if game.deck or game.discard_pile else []


def search_for_life_perform(game, player, card, option):
    """Scopri la prima carta del mazzo: se ha un tag microbo, +1 scienza qui. Poi scartala."""
    revealed = game.reveal_card()
    if revealed is None:
        return
    if Tag.MICROBE in revealed.tags:
        player.add_card_resource(card.name, 1)
    game.discard_pile.append(revealed)


def power_infrastructure_options(game, player, card):
    """Spendi X energia (da 1 a tutta quella che hai) per X M€."""
    return [str(x) for x in range(1, player.resources[Resource.ENERGY] + 1)]


def power_infrastructure_perform(game, player, card, option):
    amount = int(option)
    player.spend(Resource.ENERGY, amount)
    player.gain(Resource.MEGACREDITS, amount)


def discard_draw_options(game, player, card):
    """Quale carta scartare (una qualsiasi della mano)."""
    return [c.name for c in player.hand]


def discard_draw_perform(game, player, card, option):
    discarded = next(c for c in player.hand if c.name == option)
    player.hand.remove(discarded)
    game.discard_pile.append(discarded)
    game.draw_cards(player, 1)


def insulation_options(game, player, card):
    """Insulation: X da 1 a tutta la produzione di calore."""
    return [str(x) for x in range(1, player.production[Resource.HEAT] + 1)]


def insulation_perform(game, player, card, option):
    amount = int(option)
    player.change_production(Resource.HEAT, -amount)
    player.change_production(Resource.MEGACREDITS, amount)


def copyable_production(game, player, source: Card) -> dict[Resource, int]:
    """La produzione stampata su una carta, con le parti variabili calcolate adesso."""
    total = dict(source.production)
    for resource, scaled in source.scaled_production.items():
        total[resource] = total.get(resource, 0) + game.scaled_amount(player, scaled)
    return {r: n for r, n in total.items() if n}


def robotic_workforce_options(game, player, card):
    """Le tue carte edificio con una produzione da copiare (che puoi permetterti:
    una produzione negativa non deve scendere sotto il minimo)."""
    options = []
    for source in player.played:
        if source is card or Tag.BUILDING not in source.tags:
            continue
        production = copyable_production(game, player, source)
        if production and all(n > 0 or game.can_lose_production(player, r, -n)
                              for r, n in production.items()):
            options.append(source.name)
    return options


def robotic_workforce_perform(game, player, card, option):
    source = next(c for c in player.played if c.name == option)
    for resource, amount in copyable_production(game, player, source).items():
        player.change_production(resource, amount)


SPECIAL_ACTIONS: dict[str, SpecialAction] = {
    "insulation": SpecialAction(insulation_options, insulation_perform),
    "robotic_workforce": SpecialAction(robotic_workforce_options, robotic_workforce_perform),
    "discard_draw": SpecialAction(discard_draw_options, discard_draw_perform),
    "search_for_life": SpecialAction(search_for_life_options, search_for_life_perform),
    "power_infrastructure": SpecialAction(power_infrastructure_options,
                                          power_infrastructure_perform),
}
