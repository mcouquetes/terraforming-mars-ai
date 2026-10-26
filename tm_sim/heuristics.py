"""Le regole di valutazione del bot a regole.

IDEA: tradurre tutto in megacrediti (M€). Per ogni mossa possibile il bot
si chiede "quanti M€ mi fa guadagnare, in tutto il resto della partita?"
e sceglie la mossa che rende di più. Le regole sono semplici stime, del
tipo che un giocatore esperto fa a occhio:

- La PRODUZIONE vale quanto le generazioni che restano: +1 M€ di
  produzione a inizio partita rende circa 10 M€, all'ultima generazione 1.
- Il TR vale 1 punto vittoria più 1 M€ per ogni generazione rimasta
  (perché il TR si aggiunge al reddito a ogni produzione).
- Un PUNTO VITTORIA vale circa 5 M€, un po' di più verso la fine
  (quando i soldi non servono più a niente).
- Le RISORSE valgono quanto ci si può comprare: un acciaio 2 M€, un
  titanio 3, una pianta 1/8 di foresta, un calore 1/8 di grado.

Non è un'IA: non impara e non prevede le mosse degli avversari. Serve come
avversario "ragionevole" e come metro di paragone per l'IA vera.

Questo file contiene solo funzioni che CALCOLANO valori: non cambiano mai
la partita. Le decisioni le prende RuleBot in bots.py.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tm_sim.actions import PAYMENT_CHOICES, ActionType
from tm_sim.board import Bonus, Space, SpaceType, TilePlacement, TileType, as_placement, is_city
from tm_sim.card_effects import CARD_TRIGGERS, SPECIAL_ACTIONS, copyable_production
from tm_sim.card_list import ALL_CARDS
from tm_sim.cards import Card, CardAction, CardResource, CardType, Payment, Scaled, Tag
from tm_sim.milestones import (
    AWARDS_BY_NAME,
    MAX_MILESTONES,
    MILESTONE_POINTS,
    MILESTONES,
    points_from_scores,
)
from tm_sim.state import (
    MAX_OCEANS,
    MAX_OXYGEN,
    MAX_TEMPERATURE,
    MIN_TEMPERATURE,
    TEMPERATURE_STEP,
    Player,
    Resource,
)

if TYPE_CHECKING:
    from tm_sim.corporations import Corporation
    from tm_sim.game import Game

TOTAL_STEPS = ((MAX_TEMPERATURE - MIN_TEMPERATURE) // TEMPERATURE_STEP) + MAX_OXYGEN + MAX_OCEANS
MIN_STEPS_PER_GENERATION = 4.0   # stima prudente a inizio partita
CARD_DRAW_VALUE = 3.0            # una carta pescata vale circa quanto costa comprarla
CARDS_PLAYED_PER_GENERATION = 2.0
TAG_SHARE = 0.15                 # circa una carta su 7 ha un certo tag
PLACEMENT_BONUS_VALUE = 2.0      # valore medio dei bonus di una casella (oceani vicini ecc.)
ACTION_USE_RATE = 0.8            # un'azione blu si usa in circa 4 generazioni su 5
KEEP_BONUS = 1.4                 # "guarda 4 carte e tienine 2": 2 carte scelte valgono di più
LOOK_AND_BUY_VALUE = 1.5         # "guarda una carta e comprala se ti serve"
MICROBE_TAG_SHARE = 0.12         # Search For Life: circa 1 carta su 8 ha il tag microbo


# ---------------------------------------------------------------------------
# Quanto manca alla fine, e quanto valgono le cose
# ---------------------------------------------------------------------------

def remaining_steps(game: Game) -> int:
    p = game.state.planet
    return ((MAX_TEMPERATURE - p.temperature) // TEMPERATURE_STEP
            + (MAX_OXYGEN - p.oxygen) + (MAX_OCEANS - p.oceans))


_generations_cache: dict[tuple[int, int, int, int], float] = {}


def generations_left(game: Game) -> float:
    """Stima delle generazioni rimaste, compresa quella in corso.

    Divide i passi di terraformazione che mancano per la velocità media
    osservata finora (passi per generazione). Dipende solo dai tre parametri
    e dalla generazione: la ricordiamo finché non cambiano (è chiesta
    centinaia di migliaia di volte per partita).
    """
    planet = game.state.planet
    key = (planet.temperature, planet.oxygen, planet.oceans, game.state.generation)
    cached = _generations_cache.get(key)
    if cached is None:
        _generations_cache.clear()
        cached = _generations_cache[key] = _compute_generations_left(game)
    return cached


def _compute_generations_left(game: Game) -> float:
    remaining = remaining_steps(game)
    done = TOTAL_STEPS - remaining
    played = max(1, game.state.generation - 1)
    speed = max(MIN_STEPS_PER_GENERATION, done / played)
    return max(1.0, remaining / speed)


def vp_value(game: Game) -> float:
    """Valore in M€ di un punto vittoria: cresce verso la fine della partita."""
    return 5.0 + max(0.0, 4.0 - generations_left(game))


def tr_value(game: Game) -> float:
    return vp_value(game) + generations_left(game)


COMFORTABLE_MONEY = 40   # oltre questa cifra, ogni M€ in più vale sempre meno
LAST_GENERATION_MONEY_VALUE = 0.3


def money_value(game: Game, player: Player) -> float:
    """Quanto vale per il giocatore spendere 1 M€ adesso.

    Di solito 1. Ma i soldi avanzati a fine partita non valgono niente,
    quindi: con tanti soldi in tasca un M€ vale meno (si può spendere
    con più leggerezza), e all'ultima generazione vale quasi zero.
    Senza questa regola il bot accumula centinaia di M€ e smette di
    terraformare, perché ogni spesa gli sembra "troppo cara".
    """
    money = player.resources[Resource.MEGACREDITS]
    value = COMFORTABLE_MONEY / max(COMFORTABLE_MONEY, money)
    if generations_left(game) <= 1.0:
        value *= LAST_GENERATION_MONEY_VALUE
    return value


def plants_per_greenery(game: Game, player: Player) -> int:
    return game.plants_per_greenery(player)


def resource_value(game: Game, player: Player, resource: Resource) -> float:
    """Quanto vale 1 unità di una risorsa in magazzino."""
    planet = game.state.planet
    if resource is Resource.MEGACREDITS:
        return 1.0
    if resource is Resource.STEEL:
        return game.payment_rules(player).steel_value * 0.8   # serve solo per gli edifici
    if resource is Resource.TITANIUM:
        return game.payment_rules(player).titanium_value * 0.8
    if resource is Resource.PLANTS:
        greenery = vp_value(game) + (tr_value(game) if planet.oxygen < MAX_OXYGEN else 0)
        return greenery / plants_per_greenery(game, player)
    if resource is Resource.HEAT:
        if player.corporation and player.corporation.heat_as_megacredits:
            return 1.0
        if planet.temperature < MAX_TEMPERATURE:
            return tr_value(game) / 8
        return 0.1
    if resource is Resource.ENERGY:
        return 1.0   # diventa calore, e alcune carte la consumano
    return 0.0


def production_value(game: Game, player: Player, resource: Resource, delay: float = 0) -> float:
    """Quanto vale +1 di produzione: una unità per ogni generazione rimasta."""
    gens = max(0.0, generations_left(game) - delay)
    if resource is Resource.ENERGY:
        return gens * 1.2
    return gens * resource_value(game, player, resource)


# ---------------------------------------------------------------------------
# Carte
# ---------------------------------------------------------------------------

def requirement_delay(game: Game, player: Player, card: Card) -> float | None:
    """Fra quante generazioni si potrà giocare la carta (0 = subito).

    None = mai (per esempio una carta che vuole freddo quando fa già caldo).
    """
    req = card.requirements
    planet = game.state.planet
    leeway = game.requirement_leeway(player)
    steps_missing = 0
    for value, minimum, maximum, step in [
        (planet.temperature, req.min_temperature, req.max_temperature, TEMPERATURE_STEP),
        (planet.oxygen, req.min_oxygen, req.max_oxygen, 1),
        (planet.oceans, req.min_oceans, req.max_oceans, 1),
    ]:
        if maximum is not None and value > maximum + leeway * step:
            return None
        if minimum is not None and value < minimum - leeway * step:
            steps_missing += (minimum - leeway * step - value) // step
    tags_missing = sum(max(0, n - player.tag_count(tag)) for tag, n in req.tags.items())
    if tags_missing > 3:
        return None
    # Ognuno dei tre parametri avanza più o meno a un terzo della velocità totale.
    done = TOTAL_STEPS - remaining_steps(game)
    speed_per_parameter = max(MIN_STEPS_PER_GENERATION, done / max(1, game.state.generation - 1)) / 3
    return steps_missing / speed_per_parameter + tags_missing * 1.5


# ---------------------------------------------------------------------------
# Valore effettivo e potenziale
# ---------------------------------------------------------------------------
# Alcune carte danno poco subito ma tanto nel tempo, SE ci costruisci intorno:
# Earth Catapult (-2 M€ su ogni carta) vale moltissimo a chi giocherà tante
# carte dopo. Per questo ogni carta ha due stime, fatte con le stesse formule
# ma con ipotesi diverse (Outlook):
#   - VALORE EFFETTIVO: le ipotesi realistiche di sempre;
#   - POTENZIALE: il massimo se la carta viene sfruttata bene (più carte giocate
#     dopo, azioni usate sempre, più tag in arrivo, un buon bersaglio per gli animali).
# Con RuleBot(potential_weight=0.4) il bot usa: valore = 60% effettivo + 40% potenziale.
# Per le carte senza potenziale (un asteroide) le due stime coincidono.
#
# MISURATO (test A/B a specchio, 3000 partite ciascuno, contro il bot con peso 0):
#   80/20 (peso 0,2): -1,81 ± 0,42 punti a partita
#   60/40 (peso 0,4): -3,49 ± 0,48 punti a partita
# Il bot di oggi NON sottovaluta le carte "motore": le sopravvaluta già (lo dice anche
# learn.py: Earth Catapult -3,5 PV, Steelworks -9 PV). Dar loro più peso gli fa comprare
# carte che poi non sa sfruttare. Per questo il peso predefinito è 0: l'opzione resta.

@dataclass(frozen=True)
class Outlook:
    """Le ipotesi con cui si stima una carta."""
    cards_per_generation: float      # carte giocate dopo questa, per generazione
    tag_share: float                 # quota di quelle carte con il tag giusto (sconti per tag)
    action_use_rate: float           # quante generazioni su una si usa l'azione blu
    action_supply: float             # produzione in più che si avrà per pagare le azioni
    trigger_per_generation: float    # valore (M€) di un effetto a scatto per generazione
    trigger_resources: float         # risorse a generazione sulle carte "a scatto" (Pets...)
    metal_bonus_per_generation: float
    leeway_value: float              # valore di "requisiti ±1 passo"
    tag_growth: float                # 0 = contano solo i tag di oggi; >0 = ne arriveranno altri
    good_target: bool                # True = per animali e microbi ci sarà un buon bersaglio


REALISTIC = Outlook(cards_per_generation=2.0, tag_share=0.15, action_use_rate=0.8,
                    action_supply=0.5, trigger_per_generation=1.5, trigger_resources=0.6,
                    metal_bonus_per_generation=0.5, leeway_value=1.5, tag_growth=0.0,
                    good_target=False)
CEILING = Outlook(cards_per_generation=3.5, tag_share=0.30, action_use_rate=1.0,
                  action_supply=2.0, trigger_per_generation=3.0, trigger_resources=1.2,
                  metal_bonus_per_generation=1.0, leeway_value=3.0, tag_growth=1.5,
                  good_target=True)

POTENTIAL_WEIGHT = 0.0          # predefinito: solo valore effettivo (vedi sopra); 0.4 = 60/40
_potential_weight = POTENTIAL_WEIGHT


@contextmanager
def potential_weight(weight: float):
    """Usa questo peso del potenziale per i calcoli dentro il blocco `with`.

    Ogni bot ha il suo (RuleBot(potential_weight=...)): lo imposta qui mentre
    valuta le mosse. 0 = solo il valore effettivo (il bot di prima).
    """
    global _potential_weight
    previous = _potential_weight
    _potential_weight = weight
    try:
        yield
    finally:
        _potential_weight = previous


def current_potential_weight() -> float:
    return _potential_weight


def has_potential(card: Card) -> bool:
    """La carta ha qualcosa che rende di più se ci costruisci intorno?"""
    return bool(card.discounts or card.discounts_once or card.actions or card.resource_vp
                or card.vp_per_tag or card.vp_per_cities or card.requirement_leeway
                or card.steel_value_bonus or card.titanium_value_bonus
                or card.name in CARD_TRIGGERS or has_scaled_effects(card)
                or card.vp_if_any_resource or card.add_to_cards
                or any(c.add_to_other_card for c in card.choices))


def card_value(game: Game, player: Player, card: Card, delay: float = 0) -> float:
    """Valore in M€ di quello che la carta dà (senza togliere il costo):
    (1 - peso) × valore effettivo + peso × potenziale."""
    realistic = card_value_with(game, player, card, delay, REALISTIC)
    weight = _potential_weight
    if weight <= 0 or not has_potential(card):
        return realistic
    ceiling = card_value_with(game, player, card, delay, CEILING)
    return realistic + weight * (max(ceiling, realistic) - realistic)


def card_potential(game: Game, player: Player, card: Card, delay: float = 0) -> float:
    """Il potenziale da solo: il valore se la carta viene sfruttata bene."""
    return card_value_with(game, player, card, delay, CEILING)


def card_value_with(game: Game, player: Player, card: Card, delay: float,
                    outlook: Outlook) -> float:
    """Valore in M€ di quello che la carta dà, con le ipotesi indicate."""
    planet = game.state.planet
    gens = max(0.0, generations_left(game) - delay)
    vp = vp_value(game)
    tr = tr_value(game)
    value = 0.0

    for resource, amount in card.production.items():
        value += amount * production_value(game, player, resource, delay)
    for resource, amount in card.resources.items():
        value += amount * resource_value(game, player, resource)

    temp_steps = min(card.temperature_steps, (MAX_TEMPERATURE - planet.temperature) // TEMPERATURE_STEP)
    oxygen_steps = min(card.oxygen_steps, MAX_OXYGEN - planet.oxygen)
    value += (temp_steps + oxygen_steps + card.terraform_rating) * tr

    for tile in card.tiles:
        value += tile_value(game, tile, player)
    if card.keep_cards:     # guardarne tante e tenere le migliori vale un po' di più
        value += card.keep_cards * CARD_DRAW_VALUE * KEEP_BONUS
    else:
        value += card.draw_cards * CARD_DRAW_VALUE
    value += card.victory_points * vp
    value += placements_value_now(game, player, card, outlook)
    value += combo_bonus(game, player, card)
    value += scaled_value(game, player, card, 0)
    if outlook.tag_growth:           # potenziale: il momento migliore, con più tag in arrivo
        value += potential_gain(game, player, card, outlook.tag_growth, risk=1.0)
    value += next_card_value(game, player, card)

    # Punti variabili: stima di quanto varranno a fine partita.
    if card.resource_vp:
        each, per = card.resource_vp
        rate = resources_per_generation(player, card, outlook)
        expected = card.starting_resources + gens * rate
        value += each * (expected / per) * vp
    if card.vp_per_tag:
        tags = player.tag_count(card.vp_per_tag, wild=False) + card.tags.get(card.vp_per_tag, 0)
        tags += gens * _TAG_SHARE[card.vp_per_tag] * outlook.cards_per_generation * outlook.tag_growth
        value += tags * vp
    if card.vp_per_cities:
        cities = game.state.board.count_tiles(TileType.CITY) + gens * (1 + outlook.tag_growth / 3)
        value += cities / card.vp_per_cities * vp

    # Effetti permanenti: valgono di più se restano in gioco a lungo.
    future_cards = gens * outlook.cards_per_generation
    for tag, amount in card.discounts.items():
        value += amount * future_cards * (1.0 if tag is None else outlook.tag_share)
    for tag, amount in card.discounts_once.items():
        value += amount * future_cards * outlook.tag_share
    value += card.requirement_leeway * outlook.leeway_value
    value += ((card.steel_value_bonus + card.titanium_value_bonus)
              * (1 + gens * outlook.metal_bonus_per_generation))
    if card.name in CARD_TRIGGERS:
        value += gens * outlook.trigger_per_generation
    if card.actions:
        value += future_actions_value(game, player, card, gens, outlook)
    if card.vp_if_any_resource:      # Search For Life: basta trovare un microbo
        chance = MICROBE_TAG_SHARE * gens * outlook.action_use_rate * (1 + outlook.tag_growth / 3)
        value += card.vp_if_any_resource * vp * min(1.0, chance)

    value += attack_value(game, player, card)

    # I tag in gioco aiutano traguardi, riconoscimenti e requisiti.
    if card.type is not CardType.EVENT:
        value += 0.5 * sum(n for tag, n in card.tags.items() if tag is not Tag.EVENT)
    return value


def tile_value(game: Game, tile: TileType | TilePlacement, player: Player | None = None) -> float:
    """Valore medio di una tessera, prima di sapere dove andrà."""
    tile = as_placement(tile).tile
    planet = game.state.planet
    vp = vp_value(game)
    if tile is TileType.OCEAN:
        return (tr_value(game) if planet.oceans < MAX_OCEANS else 0) + PLACEMENT_BONUS_VALUE
    if tile is TileType.GREENERY:
        oxygen = tr_value(game) if planet.oxygen < MAX_OXYGEN else 0
        return vp + oxygen + PLACEMENT_BONUS_VALUE
    if tile is TileType.CITY:
        return vp * 1.5 + PLACEMENT_BONUS_VALUE           # ~1,5 foreste vicine
    if tile is TileType.CAPITAL:
        return vp * 1.5 + vp * 1.5 + PLACEMENT_BONUS_VALUE  # foreste + ~1,5 oceani vicini
    if tile is TileType.COMMERCIAL_DISTRICT:
        return vp * 1.5 + PLACEMENT_BONUS_VALUE           # ~1,5 città vicine
    if tile in (TileType.MINING_AREA, TileType.MINING_RIGHTS) and player is not None:
        return production_value(game, player, Resource.STEEL) + PLACEMENT_BONUS_VALUE
    # Le altre tessere speciali: il loro effetto è già nei dati della carta.
    return PLACEMENT_BONUS_VALUE


METAL_DISCOUNT = 0.8      # un M€ pagato in metalli "pesa" un po' meno di uno in contanti


def payment_cost(game: Game, player: Player, payment: Payment) -> float:
    """Quanto "costa" davvero un pagamento, in M€.

    Acciaio e titanio servono solo a pagare: valgono quanto i M€ che
    sostituiscono, un po' meno (per questo di solito conviene usarli). Ma
    se a fine partita c'è in palio Miner (o Thermalist, per il calore di
    Helion), spenderli può costare un riconoscimento: lo aggiunge award_loss.
    """
    money = money_value(game, player)
    rules = game.payment_rules(player)
    cost = payment.megacredits * money
    cost += payment.heat * resource_value(game, player, Resource.HEAT)
    cost += payment.steel * rules.steel_value * money * METAL_DISCOUNT
    cost += payment.titanium * rules.titanium_value * money * METAL_DISCOUNT
    spent = {Resource.STEEL: payment.steel, Resource.TITANIUM: payment.titanium,
             Resource.HEAT: payment.heat}
    return cost + award_loss(game, player, spent)


def card_play_value(game: Game, player: Player, card: Card, payment_choice: str | None) -> float:
    """Valore di giocare la carta adesso, pagando in quel modo."""
    allow_steel, allow_titanium = PAYMENT_CHOICES[payment_choice]
    active = player.active_cards()
    payment = card.payment_for(player, game.card_cost(player, card, active),
                               game.payment_rules(player, active),
                               game.payment_microbes(player, card, active),
                               allow_steel, allow_titanium)
    if payment is None:
        return card_net_value(game, player, card)
    return current_card_value(game, player, card) - payment_cost(game, player, payment)


_card_value_cache: dict[tuple, float] = {}


def current_card_value(game: Game, player: Player, card: Card) -> float:
    """card_value "di adesso", ricordato fino alla prossima mossa: la stessa
    carta compare più volte tra le mosse (una per ogni modo di pagarla)."""
    key = (game.uid, game.move_count, player.name, card.name, _potential_weight)
    value = _card_value_cache.get(key)
    if value is None:
        if len(_card_value_cache) > 200:
            _card_value_cache.clear()
        value = _card_value_cache[key] = card_value(game, player, card)
    return value


def card_net_value(game: Game, player: Player, card: Card) -> float:
    """Valore della carta meno quello che costa giocarla adesso."""
    price = game.card_cost(player, card)
    price = max(0, price - 2 * game.payment_microbes(player, card))   # Psychrophiles
    return current_card_value(game, player, card) - price * money_value(game, player)


def buy_value(game: Game, player: Player, card: Card) -> float:
    """Conviene comprare questa carta? (valore futuro - costo - 3 M€ per comprarla)"""
    delay = requirement_delay(game, player, card)
    if delay is None:
        return -100.0
    value = card_value(game, player, card, delay)
    value += POTENTIAL_PATIENCE * potential_gain(game, player, card)    # vale anche ciò che può diventare
    return value - (game.card_cost(player, card) + 3) * money_value(game, player)


def corporation_value(game: Game, corp: Corporation) -> float:
    """Valore di una corporazione: soldi, produzioni e risorse iniziali + il potere."""
    player = Player("prova")
    value = float(corp.starting_megacredits)
    for resource, amount in corp.production.items():
        value += amount * production_value(game, player, resource)
    for resource, amount in corp.resources.items():
        value += amount * resource_value(game, player, resource)
    value += corp.starting_draw * CARD_DRAW_VALUE
    value += 10.0   # il potere speciale: stima uguale per tutti
    return value


# ---------------------------------------------------------------------------
# Azioni delle carte blu
# ---------------------------------------------------------------------------
# Due domande diverse:
# - giocare/comprare la carta: quanto renderanno le sue azioni da qui alla
#   fine? (circa: valore di un uso × generazioni rimaste × 0,8);
# - usare l'azione adesso: quanto vale QUESTA volta, con le risorse e il
#   bersaglio di oggi?

def card_resource_value(game: Game, player: Player, card: Card) -> float:
    """Quanto vale una risorsa (animale, microbo...) messa su questa carta."""
    vp = vp_value(game)
    if card.resource_vp:
        each, per = card.resource_vp
        return each / per * vp
    if card.vp_if_any_resource:     # Search For Life: conta solo la prima
        return 0.0
    if card.resources_as_payment:   # Psychrophiles: 2 M€ per le carte pianta
        return 1.0
    # Carte che trasformano le loro risorse (GHG Producing Bacteria: 2 microbi
    # = 1 grado): ogni risorsa vale una parte della trasformazione.
    for alternative in card.actions:
        if alternative.spend_here:
            gain = action_effects_value(game, player, card, alternative)
            return max(0.0, gain) / alternative.spend_here * 0.8
    return 0.3


def action_cost_value(game: Game, player: Player, card: Card, alternative: CardAction,
                      payment_choice: str | None = None) -> float:
    """Quanto costa usare l'azione, in M€ (compreso il rischio di perdere un riconoscimento)."""
    cost = 0.0
    money = money_value(game, player)
    spent: dict[Resource, int] = {}
    for resource, amount in alternative.spend.items():
        if resource is Resource.MEGACREDITS:
            payment = game.action_payment(player, alternative, None, payment_choice)
            if payment is None:
                cost += amount * money
            else:
                cost += payment_cost(game, player, payment)
        else:
            cost += amount * resource_value(game, player, resource)
            spent[resource] = amount
    cost += award_loss(game, player, spent)
    if alternative.spend_here:
        cost += alternative.spend_here * card_resource_value(game, player, card)
    for resource, amount in alternative.production.items():
        if amount < 0:
            cost += -amount * production_value(game, player, resource)
    return cost


def action_effects_value(game: Game, player: Player, card: Card, alternative: CardAction) -> float:
    """Quanto vale ciò che l'azione dà (senza bersagli né costi)."""
    planet = game.state.planet
    a = alternative
    tr = tr_value(game)
    value = sum(n * resource_value(game, player, r) for r, n in a.gain.items())
    if a.megacredits_per_city_on_mars:
        value += a.megacredits_per_city_on_mars * game.state.board.cities_on_mars()
    value += sum(n * production_value(game, player, r) for r, n in a.production.items() if n > 0)
    value += min(a.temperature_steps, (MAX_TEMPERATURE - planet.temperature) // TEMPERATURE_STEP) * tr
    value += min(a.oxygen_steps, MAX_OXYGEN - planet.oxygen) * tr
    value += a.terraform_rating * tr
    value += sum(tile_value(game, tile, player) for tile in a.tiles)
    value += a.draw_cards * CARD_DRAW_VALUE
    value += LOOK_AND_BUY_VALUE if a.buy_card else 0.0
    if a.special == "search_for_life" and player.card_resources.get(card.name, 0) == 0:
        value += MICROBE_TAG_SHARE * card.vp_if_any_resource * vp_value(game)
    return value


def uses_per_generation(player: Player, alternative: CardAction,
                        outlook: Outlook = REALISTIC) -> float:
    """Quante volte per generazione si riuscirà a pagare l'azione (al massimo 1).

    Le azioni che consumano energia, calore o metalli dipendono da quanto se
    ne produce: Physics Complex vuole 6 energia, e con 1 di produzione
    energetica si usa una volta ogni 6 generazioni. (I M€ li diamo per
    disponibili: si guadagnano in tanti modi.)
    """
    rate = 1.0
    for resource, amount in alternative.spend.items():
        if resource is Resource.MEGACREDITS:
            continue
        supply = player.production[resource]
        if resource is Resource.HEAT:
            supply += player.production[Resource.ENERGY]   # l'energia avanzata diventa calore
        # Realistico: +0,5 (qualcosa arriva sempre). Potenziale: +2, cioè ci costruisci
        # intorno un po' di produzione (che però va pagata: non è infinita).
        rate = min(rate, (supply + outlook.action_supply) / amount)
    if alternative.remove_from_any_card:
        rate *= 0.5 if outlook.action_supply < 1 else 0.8   # serve qualcuno da cui prendere
    return rate


def resources_per_generation(player: Player, card: Card, outlook: Outlook = REALISTIC) -> float:
    """Quante risorse riceverà la carta a ogni generazione (per stimarne i punti)."""
    adds = [a for a in card.actions if a.add_here]
    if not adds:
        return outlook.trigger_resources    # le riceve da un effetto a scatto (Pets, Decomposers...)
    return max(a.add_here * uses_per_generation(player, a, outlook)
               for a in adds) * outlook.action_use_rate


def future_actions_value(game: Game, player: Player, card: Card, gens: float,
                         outlook: Outlook = REALISTIC) -> float:
    """Valore di tutti gli usi futuri delle azioni di una carta non ancora in gioco."""
    best = 0.0
    converts = any(a.spend_here for a in card.actions)
    for alternative in card.actions:
        if alternative.spend_here:
            continue        # si contano già le risorse che la carta accumula (qui sotto)
        value = action_effects_value(game, player, card, alternative)
        value -= action_cost_value(game, player, card, alternative)
        if alternative.add_here and not card.resource_vp:
            # I punti degli animali sono già contati in card_value; qui le altre risorse.
            unit = card_resource_value(game, player, card) / (0.8 if converts else 1.0)
            value += alternative.add_here * unit
        if alternative.remove_from_any_card:
            value += 0.3            # c'è quasi sempre qualcosa da prendere
        if alternative.add_to_other_card:
            value += alternative.add_to_other_card[1] * 1.5
        if alternative.special == "power_infrastructure":
            value += 0.5
        rate = uses_per_generation(player, alternative, outlook) * outlook.action_use_rate
        production = sum(n * production_value(game, player, r)
                         for r, n in alternative.production.items() if n > 0)
        if production:
            # Comprare produzione rende meno a ogni generazione che passa: sommiamo
            # un uso per generazione rimasta, tenendo solo quelli che convengono.
            per_generation = production / max(1.0, generations_left(game))
            rest = value - production
            total = sum(max(0.0, per_generation * m + rest) for m in range(1, int(gens) + 1))
        else:
            total = max(0.0, value) * gens
        best = max(best, total * rate)
    starting = card.starting_resources * card_resource_value(game, player, card) if converts else 0.0
    return best + starting


def card_action_value(game: Game, player: Player, card: Card, alternative: CardAction,
                      option: str | None, payment_choice: str | None = None) -> float:
    """Quanto conviene usare adesso questa azione, con questa scelta."""
    value = action_effects_value(game, player, card, alternative)
    value -= action_cost_value(game, player, card, alternative, payment_choice)
    if alternative.add_here:
        value += alternative.add_here * card_resource_value(game, player, card)
    if alternative.remove_from_any_card and option:
        owner_name, _, card_name = option.partition(":")
        owner = next(p for p in game.state.players if p.name == owner_name)
        source = next(c for c in owner.played if c.name == card_name)
        loss = card_resource_value(game, owner, source)
        if owner is player:
            value -= loss
        else:   # come un attacco: conta di più togliere al giocatore messo meglio
            rivals = len(game.state.players) - 1
            value += loss * threat_weight(game, player, owner) / rivals
    if alternative.add_to_other_card and option:
        target = next(c for c in player.played if c.name == option)
        value += alternative.add_to_other_card[1] * card_resource_value(game, player, target)
    if alternative.special == "discard_draw" and option:
        discarded = next(c for c in player.hand if c.name == option)
        value += CARD_DRAW_VALUE - keep_value(game, player, discarded)
    if alternative.special in ("insulation", "robotic_workforce"):
        value += special_choice_value(game, player, alternative.special, option)
    return value


def special_choice_value(game: Game, player: Player, special: str, option: str | None) -> float:
    """Valore delle scelte "strane" quando giochi la carta. option None = la migliore."""
    if option is None:
        options = SPECIAL_ACTIONS[special].options(game, player, None)
        return max((special_choice_value(game, player, special, o) for o in options), default=0.0)
    if special == "insulation":        # X calore → X M€ di produzione
        x = int(option)
        return x * (production_value(game, player, Resource.MEGACREDITS)
                    - production_value(game, player, Resource.HEAT))
    source = next(c for c in player.played if c.name == option)    # Robotic Workforce
    return sum(n * production_value(game, player, r)
               for r, n in copyable_production(game, player, source).items())


# ---------------------------------------------------------------------------
# Scelte e risorse su altre carte (combo)
# ---------------------------------------------------------------------------
# Carte come Imported Nitrogen ("+2 animali su una tua carta") valgono molto
# se hai in gioco una carta dove ogni animale vale 1 PV (Fish, Birds...), e
# quasi niente se non ce l'hai. Quindi:
# - il loro valore "adesso" dipende dal miglior bersaglio che hai in gioco;
# - conviene ASPETTARE a giocarle se in mano hai un buon bersaglio non ancora
#   giocato (combo_patience), un po' meno se speri solo di pescarne uno
#   (combo_hope). Più ci si avvicina alla fine, meno si aspetta;
# - un bersaglio (Fish) vale di più se in mano hai carte che lo riempiranno.

COMBO_PATIENCE = 0.8     # quanto aspettare se in mano c'è un bersaglio (es. Fish)
COMBO_HOPE = 0.25        # quanto aspettare se non c'è: si spera di pescarlo
COMBO_SHARE = 0.5        # quanto del valore della combo si attribuisce al bersaglio
# Valore tipico (in PV) di una risorsa su un buon bersaglio: animali quasi
# sempre 1 PV l'uno, microbi di solito 1 PV ogni 2-4.
TYPICAL_VP_PER_RESOURCE = {CardResource.ANIMAL: 1.0, CardResource.MICROBE: 0.33}


def best_target_value(game: Game, player: Player, kind: CardResource | None,
                      exclude: Card | None = None) -> float:
    """Valore di UNA risorsa sul miglior bersaglio che hai già in gioco (0 = nessuno)."""
    best = 0.0
    for target in player.played:
        if target is exclude:
            continue
        if kind is None:      # qualsiasi carta che ha già risorse
            if player.card_resources.get(target.name, 0) <= 0:
                continue
        elif target.resource_type is not kind:
            continue
        best = max(best, card_resource_value(game, player, target))
    return best


def hand_target_value(game: Game, player: Player, kind: CardResource | None,
                      exclude: Card) -> float:
    """Valore di UNA risorsa sul miglior bersaglio che hai IN MANO e farai in
    tempo a giocare (0 = nessuno)."""
    if kind is None:
        return 0.0
    gens = generations_left(game)
    best = 0.0
    for target in player.hand:
        if target is exclude or target.resource_type is not kind or not target.resource_vp:
            continue
        delay = requirement_delay(game, player, target)
        if delay is not None and delay < gens - 1:
            best = max(best, card_resource_value(game, player, target))
    return best


def placements(card: Card) -> list[tuple[CardResource | None, int]]:
    """Tutte le risorse che la carta può mettere su altre carte (anche nelle scelte)."""
    result = list(card.add_to_cards)
    result += [c.add_to_other_card for c in card.choices if c.add_to_other_card]
    return result


def choice_value(game: Game, player: Player, card: Card, alternative: CardAction,
                 unit: float | None = None) -> float:
    """Valore di un'alternativa di una scelta. unit: valore di una risorsa sul
    bersaglio (None = il miglior bersaglio in gioco adesso)."""
    value = action_effects_value(game, player, card, alternative)
    if alternative.special in ("insulation", "robotic_workforce"):
        value += special_choice_value(game, player, alternative.special, None)
    if alternative.add_to_other_card:
        kind, amount = alternative.add_to_other_card
        if unit is None:
            unit = best_target_value(game, player, kind, exclude=card)
        value += amount * unit
    return value


def placements_value_now(game: Game, player: Player, card: Card,
                         outlook: Outlook = REALISTIC) -> float:
    """Valore di risorse su altre carte e scelte, con i bersagli che hai in gioco ora
    (potenziale: con un buon bersaglio, quello che avresti costruendoci intorno)."""
    vp = vp_value(game)

    def unit(kind):
        now = best_target_value(game, player, kind, exclude=card)
        if outlook.good_target:
            return max(now, TYPICAL_VP_PER_RESOURCE.get(kind, 0.5) * vp)
        return now

    value = sum(amount * unit(kind) for kind, amount in card.add_to_cards)
    if card.choices:
        value += max(choice_value(game, player, card, c,
                                  unit(c.add_to_other_card[0]) if c.add_to_other_card else None)
                     for c in card.choices)
    return value


def combo_bonus(game: Game, player: Player, card: Card) -> float:
    """Un bersaglio (Fish) vale di più se in mano ci sono carte che lo riempiranno."""
    if card.resource_type is None or not card.resource_vp:
        return 0.0
    unit = card_resource_value(game, player, card)
    incoming = sum(amount for other in player.hand if other is not card
                   for kind, amount in placements(other) if kind is card.resource_type)
    return incoming * unit * COMBO_SHARE


def combo_wait_value(game: Game, player: Player, card: Card,
                     patience: float = COMBO_PATIENCE, hope: float = COMBO_HOPE) -> float:
    """Quanto conviene NON giocare adesso la carta, aspettando un bersaglio migliore.

    È la differenza tra quanto renderanno le sue risorse "più avanti" (con il
    bersaglio che hai in mano, o con uno che speri di pescare) e quanto
    rendono adesso, pesata dalla pazienza. Vicino alla fine non si aspetta.
    """
    if not placements(card):
        return 0.0
    gens = generations_left(game)
    if gens <= 1.0:
        return 0.0
    vp = vp_value(game)

    def expected_unit(kind: CardResource | None) -> tuple[float, float]:
        """(valore di una risorsa adesso, valore atteso se aspetto)."""
        now = best_target_value(game, player, kind, exclude=card)
        in_hand = hand_target_value(game, player, kind, exclude=card)
        if in_hand > now:
            return now, now + patience * (in_hand - now)
        typical = TYPICAL_VP_PER_RESOURCE.get(kind, 0.0) * vp
        return now, now + hope * max(0.0, typical - now)

    wait = 0.0
    for kind, amount in card.add_to_cards:
        now, later = expected_unit(kind)
        wait += amount * (later - now)
    if card.choices:
        best_now = max(choice_value(game, player, card, c) for c in card.choices)
        best_later = max(choice_value(game, player, card, c,
                                      expected_unit(c.add_to_other_card[0])[1]
                                      if c.add_to_other_card else None)
                         for c in card.choices)
        wait += max(0.0, best_later - best_now)
    return wait * min(1.0, (gens - 1.0) / 2.0)


# ---------------------------------------------------------------------------
# Carte "di potenziale": effetti che crescono con tag, città, eventi
# ---------------------------------------------------------------------------
# Satellites dà +1 produzione di M€ per ogni tag spazio. Con 1 tag spazio
# vale poco; con 5 vale moltissimo. Sono carte "discrete" adesso, ma che
# possono dare tanto nel tempo. Il bot stima:
# - quanto renderebbe giocarla ADESSO (con i tag di oggi);
# - quanto renderebbe giocarla fra k generazioni: i tag crescono (quelli in
#   mano, più quelli che arriveranno dal mazzo), ma una produzione presa
#   più tardi rende per meno generazioni, e il futuro è incerto;
# - se aspettare rende di più, la tiene in mano (potential_patience) e, quando
#   la compra, ne conta una parte del potenziale.
# Con i bot che imparano da soli potremo stimare questo potenziale meglio.

POTENTIAL_PATIENCE = 0.6     # quanto del guadagno "aspettando" il bot considera
FUTURE_RISK = 0.9            # ogni generazione di attesa vale il 10% in meno (incertezza)
CITIES_PER_PLAYER_PER_GENERATION = 0.4   # stime di partenza, prima di vedere la partita
EVENTS_PER_PLAYER_PER_GENERATION = 0.6

# Quante carte del mazzo hanno ciascun tag: da qui, a che ritmo arrivano.
_TAG_SHARE = {tag: sum(1 for c in ALL_CARDS if tag in c.tags) / max(1, len(ALL_CARDS))
              for tag in Tag}


def has_scaled_effects(card: Card) -> bool:
    return bool(card.scaled_production or card.scaled_resources or card.scaled_tr)


def expected_scaled_count(game: Game, player: Player, card: Card, scaled: Scaled,
                          k: float, growth: float = 1.0) -> float:
    """Quante "unità" conterà la quantità se la carta si gioca fra k generazioni."""
    state = game.state
    played_gens = max(1, state.generation - 1)
    n_players = len(state.players)
    if scaled.what in ("tag", "tag_at_least"):
        now = player.tag_count(scaled.tag) + card.tags.get(scaled.tag, 0)   # compresa questa
        in_hand = sum(c.tags.get(scaled.tag, 0) for c in player.hand
                      if c is not card and c.type is not CardType.EVENT)
        rate = _TAG_SHARE[scaled.tag] * CARDS_PLAYED_PER_GENERATION * growth
        return now + in_hand * min(1.0, k / 2) + rate * k
    if scaled.what == "tag_others":
        rivals = [p for p in state.players if p is not player]
        now = sum(p.tag_count(scaled.tag) for p in rivals)
        return now + len(rivals) * _TAG_SHARE[scaled.tag] * CARDS_PLAYED_PER_GENERATION * k
    if scaled.what in ("cities", "cities_on_mars"):
        now = (state.board.count_tiles(TileType.CITY) if scaled.what == "cities"
               else state.board.cities_on_mars())
        rate = max(now / played_gens if state.generation > 1 else 0.0,
                   CITIES_PER_PLAYER_PER_GENERATION * n_players)
        return now + rate * k
    if scaled.what == "events":
        now = sum(p.tag_count(Tag.EVENT, wild=False) for p in state.players)
        rate = max(now / played_gens if state.generation > 1 else 0.0,
                   EVENTS_PER_PLAYER_PER_GENERATION * n_players)
        return now + rate * k
    return 0.0


def scaled_amount_at(game: Game, player: Player, card: Card, scaled: Scaled, k: float,
                     growth: float = 1.0) -> float:
    count = expected_scaled_count(game, player, card, scaled, k, growth)
    if scaled.what == "tag_at_least":
        return scaled.step if count >= scaled.per else 0.0
    return (count // scaled.per if k == 0 else count / scaled.per) * scaled.step


def scaled_value(game: Game, player: Player, card: Card, k: float, growth: float = 1.0) -> float:
    """Valore delle parti variabili della carta se giocata fra k generazioni."""
    if not has_scaled_effects(card):
        return 0.0
    gens = generations_left(game)
    remaining = max(0.0, gens - k)
    value = 0.0
    for resource, scaled in card.scaled_production.items():
        unit = production_value(game, player, resource) / max(1.0, gens)   # per generazione
        value += scaled_amount_at(game, player, card, scaled, k, growth) * unit * remaining
    for resource, scaled in card.scaled_resources.items():
        value += (scaled_amount_at(game, player, card, scaled, k, growth)
                  * resource_value(game, player, resource))
    if card.scaled_tr:
        tr_later = vp_value(game) + remaining
        value += scaled_amount_at(game, player, card, card.scaled_tr, k, growth) * tr_later
    return value


def potential_gain(game: Game, player: Player, card: Card, growth: float = 1.0,
                   risk: float = FUTURE_RISK) -> float:
    """Quanto in più renderebbe la carta giocandola al momento migliore, invece che adesso.

    growth: quanto più in fretta arrivano i tag (1 = al ritmo del mazzo; di più se
    ci costruisci intorno). risk: quanto vale ogni generazione di attesa (incertezza).
    """
    if not has_scaled_effects(card):
        return 0.0
    gens = generations_left(game)
    now = scaled_value(game, player, card, 0)
    best = now
    for k in range(1, int(gens)):
        best = max(best, scaled_value(game, player, card, k, growth) * risk ** k)
    return best - now


def next_card_value(game: Game, player: Player, card: Card) -> float:
    """Indentured Workers, Special Design, Eccentric Sponsor, Ecology Experts:
    valgono solo se c'è una carta in mano che ne approfitta subito."""
    if not (card.next_card_discount or card.next_card_leeway):
        return 0.0
    others = [c for c in player.hand if c is not card]
    value = 0.0
    if card.next_card_discount and others:
        best_price = max(game.card_cost(player, c) for c in others)
        value += min(card.next_card_discount, best_price) * 0.8 * money_value(game, player)
    if card.next_card_leeway:
        blocked = [c for c in others if requirement_delay(game, player, c) not in (None, 0)]
        value += min(len(blocked), 1) * (6.0 if card.next_card_leeway >= 50 else 3.0)
    return value


# ---------------------------------------------------------------------------
# Tenere le risorse per i riconoscimenti (Miner, Thermalist)
# ---------------------------------------------------------------------------
# Miner premia chi ha più acciaio + titanio a fine partita, Thermalist chi ha
# più calore. Se sono finanziati, nelle ultime generazioni spendere queste
# risorse (pagando una carta o alzando la temperatura) può far perdere il
# primo posto: prima di spenderle, il bot guarda quanto ne hanno gli altri.

AWARD_RESOURCES = {"Miner": (Resource.STEEL, Resource.TITANIUM),
                   "Thermalist": (Resource.HEAT,)}
AWARD_WATCH_GENERATIONS = 2.0     # da quando iniziare a controllare


def projected_award_amount(player: Player, resources: tuple[Resource, ...], productions: int) -> int:
    """Quanto ne avrà a fine partita se non spende niente (produzioni comprese).

    Per il calore conta anche l'energia: a ogni produzione diventa calore.
    """
    total = sum(player.resources[r] + player.production[r] * productions for r in resources)
    if Resource.HEAT in resources:
        total += (player.resources[Resource.ENERGY]
                  + player.production[Resource.ENERGY] * (productions - 1))
    return total


def award_loss(game: Game, player: Player, spend: dict[Resource, int]) -> float:
    """Quanto rischio di perdere (in M€) nei riconoscimenti spendendo queste risorse.

    Confronta i punti del riconoscimento "se non spendo" e "se spendo", con
    le quantità previste a fine partita per tutti. Conta anche quanto
    guadagnano gli avversari (a 2 giocatori, se perdo il primo posto lo prende
    l'altro). Lontano dalla fine vale poco: gli altri possono ancora cambiare.
    """
    funded = game.state.funded_awards
    if not funded or not any(spend.values()):
        return 0.0
    gens = generations_left(game)
    if gens > AWARD_WATCH_GENERATIONS:
        return 0.0
    certainty = 1.0 if gens <= 1.0 else 0.5
    productions = max(1, round(gens))
    players = game.state.players
    rivals = len(players) - 1
    loss = 0.0
    for name in funded:
        resources = AWARD_RESOURCES.get(name)
        if resources is None:
            continue
        spent = sum(spend.get(r, 0) for r in resources)
        if spent <= 0:
            continue
        before = {p.name: projected_award_amount(p, resources, productions) for p in players}
        after = dict(before)
        after[player.name] -= spent
        points_before, points_after = points_from_scores(before), points_from_scores(after)
        mine = points_before[player.name] - points_after[player.name]
        theirs = sum(points_after[n] - points_before[n] for n in before if n != player.name)
        loss += mine + theirs / rivals
    return loss * vp_value(game) * certainty


# ---------------------------------------------------------------------------
# Vendita di brevetti
# ---------------------------------------------------------------------------
# Vendere una carta rende solo 1 M€ e costa un'azione, quindi il bot lo fa
# in due casi:
# 1. vendendo carte che non gli servono (valore quasi nullo) riesce a giocare
#    SUBITO una carta che vale molto;
# 2. all'ultima generazione, prima di passare: le carte rimaste in mano non
#    serviranno più, e in caso di parità di punti vince chi ha più M€.

USELESS_CARD = 1.5          # sotto questo valore (M€) una carta in mano è "inutile"
GREAT_CARD = 8.0            # sopra questo valore netto (M€) una carta vale una vendita
SELLING_TEMPO = 2.0         # l'azione spesa per vendere ha un costo


def is_last_generation(game: Game) -> bool:
    """Di sicuro l'ultima: i parametri sono al massimo, la partita finisce
    quando tutti avranno passato."""
    return game.state.planet.is_terraformed()


def keep_value(game: Game, player: Player, card: Card) -> float:
    """Quanto vale tenere una carta in mano (0 = non si giocherà mai)."""
    delay = requirement_delay(game, player, card)
    if delay is None or delay >= generations_left(game):
        return 0.0
    value = card_value(game, player, card, delay) + POTENTIAL_PATIENCE * potential_gain(game, player, card)
    return max(0.0, value - game.card_cost(player, card) * money_value(game, player))


def worth_playing_now(game: Game, player: Player, card: Card) -> bool:
    return (game.playable_except_cost(player, card) and game.shortfall(player, card) == 0
            and card_net_value(game, player, card) > 0)


_sell_plan_cache: dict[tuple[int, int, str], tuple[list[str], float] | None] = {}


def sell_plan(game: Game, player: Player) -> tuple[list[str], float] | None:
    """Quali carte vendere adesso e quanto conviene, oppure None.

    Restituisce le carte nell'ordine in cui venderle (le meno utili prima).
    Il risultato non cambia finché non si gioca una mossa: lo ricordiamo.
    """
    key = (game.uid, game.move_count, player.name, _potential_weight)
    if key not in _sell_plan_cache:
        _sell_plan_cache.clear()
        _sell_plan_cache[key] = _compute_sell_plan(game, player)
    return _sell_plan_cache[key]


def _compute_sell_plan(game: Game, player: Player) -> tuple[list[str], float] | None:
    hand = player.hand
    if not hand:
        return None

    # Caso 1: vendere carte inutili per giocare subito una carta forte.
    # Prima i controlli veloci: una carta a cui mancano pochi M€ e che,
    # soldi a parte, si potrebbe giocare. Se non c'è, niente calcoli pesanti.
    candidates = []
    active = player.active_cards()
    cash = player.resources[Resource.MEGACREDITS]
    for target in hand:
        if target.cost <= cash:      # gli sconti abbassano il prezzo: te la puoi già permettere
            continue
        missing = game.shortfall(player, target, active)
        if 0 < missing < len(hand) and game.playable_except_cost(player, target, active):
            net = card_net_value(game, player, target)
            if net >= GREAT_CARD:
                candidates.append((target, missing, net))
    best: tuple[list[str], float] | None = None
    if candidates:
        keep = {c.name: keep_value(game, player, c) for c in hand}
        junk = sorted((c for c in hand if keep[c.name] < USELESS_CARD),
                      key=lambda c: keep[c.name])
        for target, missing, net in candidates:
            sellable = [c for c in junk if c is not target]
            if missing > len(sellable):
                continue
            to_sell = sellable[:missing]
            value = net - sum(keep[c.name] for c in to_sell) - SELLING_TEMPO
            if value > 0 and (best is None or value > best[1]):
                best = ([c.name for c in to_sell], value)
    if best:
        return best

    # Caso 2: ultima generazione, vendo tutto quello che non giocherò più.
    if is_last_generation(game):
        leftovers = [c.name for c in hand if not worth_playing_now(game, player, c)]
        if leftovers:
            # Poco più di zero: lo fa solo quando non c'è niente di meglio, cioè per ultimo.
            return leftovers, 0.1 + 0.01 * len(leftovers)
    return None


# ---------------------------------------------------------------------------
# Mappa
# ---------------------------------------------------------------------------

BONUS_VALUES = {Bonus.STEEL: 2.0, Bonus.TITANIUM: 3.0, Bonus.PLANT: 1.5, Bonus.CARD: CARD_DRAW_VALUE}


def space_value(game: Game, player: Player, tile: TileType | TilePlacement, space: Space) -> float:
    """Quanto conviene piazzare questa tessera su questa casella."""
    tile = as_placement(tile).tile
    board = game.state.board
    vp = vp_value(game)
    neighbors = board.neighbors(space)
    value = sum(BONUS_VALUES[b] for b in space.bonuses)
    value += 2 * board.adjacent_oceans(space)

    if tile is TileType.GREENERY:
        for n in neighbors:
            if is_city(n.tile):
                value += vp if n.owner == player.name else -vp * 0.5   # regalo un PV all'avversario
    elif is_city(tile):
        greeneries = sum(1 for n in neighbors if n.tile is TileType.GREENERY)
        free_land = sum(1 for n in neighbors
                        if n.is_empty and n.type is SpaceType.LAND and n.reserved is None)
        value += greeneries * vp + free_land * vp * 0.3   # spazio per foreste future
        if tile is TileType.CAPITAL:
            value += board.adjacent_oceans(space) * vp   # 1 PV per oceano vicino
    elif tile is TileType.COMMERCIAL_DISTRICT:
        value += sum(1 for n in neighbors if is_city(n.tile)) * vp
    elif tile in (TileType.MINING_AREA, TileType.MINING_RIGHTS):
        metal = Resource.TITANIUM if Bonus.TITANIUM in space.bonuses else Resource.STEEL
        value += production_value(game, player, metal)
    return value


# ---------------------------------------------------------------------------
# Corsa ai traguardi
# ---------------------------------------------------------------------------
# Un traguardo vale più dei suoi 5 PV: se lo prendo io, un avversario non
# lo prenderà più. In una partita a 2 la differenza tra "lo prendo io" e
# "lo prende lui" è di 10 PV. Per questo il bot premia le mosse che lo
# AVVICINANO a un traguardo libero, tanto più se un rivale è vicino anche lui.

def card_metric_deltas(game: Game, card: Card) -> dict[str, int]:
    """Di quanto una carta fa avanzare ciò che contano i traguardi."""
    planet = game.state.planet
    tiles = [p.tile for p in card.tiles]
    tr = (min(card.temperature_steps, (MAX_TEMPERATURE - planet.temperature) // TEMPERATURE_STEP)
          + min(card.oxygen_steps, MAX_OXYGEN - planet.oxygen)
          + card.terraform_rating
          + (tiles.count(TileType.OCEAN) if planet.oceans < MAX_OCEANS else 0)
          + (tiles.count(TileType.GREENERY) if planet.oxygen < MAX_OXYGEN else 0))
    building = card.tags.get(Tag.BUILDING, 0) if card.type is not CardType.EVENT else 0
    return {"tr": tr, "cities": sum(1 for t in tiles if is_city(t)),
            "greeneries": tiles.count(TileType.GREENERY), "building_tags": building,
            "hand": card.draw_cards - 1}


def tile_metric_deltas(game: Game, tile: TileType) -> dict[str, int]:
    """Di quanto una tessera fa avanzare ciò che contano i traguardi."""
    planet = game.state.planet
    if tile is TileType.OCEAN:
        return {"tr": 1 if planet.oceans < MAX_OCEANS else 0}
    if tile is TileType.GREENERY:
        return {"greeneries": 1, "tr": 1 if planet.oxygen < MAX_OXYGEN else 0}
    return {"cities": 1}


def milestone_race_value(game: Game, player: Player, deltas: dict[str, int]) -> float:
    """Bonus in M€ per i passi avanti verso traguardi ancora liberi."""
    claimed = game.state.claimed_milestones
    if len(claimed) >= MAX_MILESTONES:
        return 0.0
    vp = vp_value(game)
    rivals = [p for p in game.state.players if p is not player]
    total = 0.0
    for milestone in MILESTONES:
        step = deltas.get(milestone.metric, 0)
        if milestone.name in claimed or step <= 0:
            continue
        mine = milestone.progress(player)
        missing = milestone.target - mine
        if missing <= 0:
            continue          # già raggiunto: ci pensa la mossa "reclama"
        # Quanto è vicino il rivale più avanti (0 = lontanissimo, 1 = ce l'ha quasi).
        rival = max(min(1.0, milestone.progress(r) / milestone.target) for r in rivals)
        # Il premio della corsa: i miei 5 PV più quelli che toglierei al rivale.
        prize = MILESTONE_POINTS * vp * (1 + rival)
        # Contano solo i progressi verso traguardi a portata: chi è a metà strada
        # riceve metà del peso, chi è a un passo quasi tutto.
        closeness = mine / milestone.target
        total += prize * (min(step, missing) / missing) * closeness
    return total


# ---------------------------------------------------------------------------
# Riconoscimenti
# ---------------------------------------------------------------------------

def award_lead(game: Game, player: Player, award_name: str) -> float:
    """Di quanto il giocatore è davanti agli altri in un riconoscimento (negativo = dietro)."""
    award = AWARDS_BY_NAME[award_name]
    mine = award.score(player)
    others = [award.score(p) for p in game.state.players if p is not player]
    return mine - max(others)


def standard_project_value(game: Game, player: Player, project: ActionType) -> float:
    """Valore di un progetto standard (senza il costo)."""
    if project is ActionType.POWER_PLANT:
        return production_value(game, player, Resource.ENERGY)
    if project is ActionType.ASTEROID:
        return tr_value(game)
    if project is ActionType.AQUIFER:
        return tile_value(game, TileType.OCEAN)
    if project is ActionType.GREENERY:
        return tile_value(game, TileType.GREENERY)
    if project is ActionType.CITY:
        return tile_value(game, TileType.CITY) + production_value(game, player, Resource.MEGACREDITS)
    return 0.0



# ---------------------------------------------------------------------------
# Attacchi: chi colpire, e quanto vale
# ---------------------------------------------------------------------------
# L'"indice di sensatezza" di un bersaglio è:
#
#     danno reale × peso del bersaglio
#
# - DANNO REALE: quanto vale per il bersaglio ciò che gli togli davvero
#   ("fino a 8 piante" a chi ne ha 1 = 1 pianta, non 8).
# - PESO: quanto il bersaglio è messo bene rispetto agli altri avversari.
#   Il leader pesa più di 1, chi è indietro meno di 1.

MONEY_PER_VP = 8.0   # circa quanti M€ di reddito futuro valgono 1 PV


_strength_cache: dict[tuple[int, int], dict[str, float]] = {}   # (partita, mossa) -> forze


def player_strength(game: Game, player: Player) -> float:
    """Quanto è messo bene un giocatore: punti attuali + reddito futuro in PV.

    Calcolarlo richiede il punteggio completo, che è lento; ma non cambia
    finché nessuno fa una mossa. Quindi lo calcoliamo una volta per mossa
    (per tutti i giocatori) e lo ricordiamo: è una "cache".
    """
    key = (game.uid, game.move_count)
    strengths = _strength_cache.get(key)
    if strengths is None:
        _strength_cache.clear()           # teniamo solo l'ultima: le vecchie non servono più
        gens = generations_left(game)
        strengths = {
            p.name: game.score(p)
            + (p.terraform_rating + p.production[Resource.MEGACREDITS]) * gens / MONEY_PER_VP
            for p in game.state.players
        }
        _strength_cache[key] = strengths
    return strengths[player.name]


def threat_weight(game: Game, attacker: Player, target: Player) -> float:
    """Peso del bersaglio: la sua forza divisa per la forza media degli avversari."""
    rivals = [p for p in game.state.players if p is not attacker]
    average = sum(player_strength(game, p) for p in rivals) / len(rivals)
    if average <= 0:
        return 1.0
    return max(0.5, min(2.0, player_strength(game, target) / average))


def unit_value(game: Game, target: Player, card: Card, kind: str, what: str | None) -> float:
    """Quanto vale per il bersaglio UNA unità di quello che gli togli."""
    if kind == "plants":
        return resource_value(game, target, Resource.PLANTS)
    if kind == "production":
        return production_value(game, target, card.decrease_any_production[0])
    if kind == "flood":
        return 1.0
    resource_name, _, card_name = (what or "").partition(":")
    if card_name:       # risorsa su una carta: vale i punti che fa fare
        stored_on = next((c for c in target.played if c.name == card_name), None)
        if stored_on and stored_on.resource_vp:
            each, per = stored_on.resource_vp
            return each / per * vp_value(game)
        return 0.5
    return resource_value(game, target, Resource(resource_name))


def damage_value(game: Game, attacker: Player, target: Player, card: Card,
                 kind: str, what: str | None) -> float:
    """Valore in M€ del danno reale (più quello che rubi, se rubi)."""
    amount = game.attack_amount(kind, card, target, what or "")
    value = amount * unit_value(game, target, card, kind, what)
    if kind == "raid" and card.raid_steals:
        value += amount * resource_value(game, attacker, Resource(what))
    return value


def attack_target_score(game: Game, attacker: Player, kind: str, card: Card,
                        target: Player | None, what: str | None) -> float:
    """L'indice di sensatezza di un bersaglio (0 = rinuncio, negativo = colpisco me stesso)."""
    if target is None:
        return 0.0
    damage = damage_value(game, attacker, target, card, kind, what)
    if target is attacker:
        return -damage
    rivals = len(game.state.players) - 1
    # Con più avversari, danneggiarne uno aiuta meno: gli altri ne approfittano.
    return damage * threat_weight(game, attacker, target) / rivals


def attack_value(game: Game, player: Player, card: Card) -> float:
    """Valore stimato degli attacchi di una carta, prima di giocarla."""
    rivals = [p for p in game.state.players if p is not player]
    value = 0.0

    def best(kind: str, options: list[tuple[Player, str | None]]) -> float:
        scores = [attack_target_score(game, player, kind, card, t, w) for t, w in options]
        return max(scores, default=0.0)

    if card.remove_any_plants:
        value += max(0.0, best("plants", [(p, "piante") for p in rivals
                                         if not game.is_protected(p, Resource.PLANTS)]))
    if card.decrease_any_production:
        resource, amount = card.decrease_any_production
        targets = [p for p in rivals if game.can_lose_production(p, resource, amount)]
        if targets:
            value += best("production", [(p, resource.value) for p in targets])
        else:   # l'unico bersaglio possibile sono io
            value -= amount * production_value(game, player, resource)
    if card.raid:
        options = [(p, what.value) for what, _ in card.raid if isinstance(what, Resource)
                   for p in rivals if not game.is_protected(p, what)]
        value += max(0.0, best("raid", options))
    if card.flood_raid:
        value += card.flood_raid * 0.5    # non sappiamo ancora dove andrà l'oceano
    return value
