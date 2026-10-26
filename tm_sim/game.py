"""Il motore di gioco: fasi, turni, azioni legali, esecuzione delle azioni.

Questa è la classe con cui parlano tutti gli altri pezzi del progetto
(l'interfaccia da terminale, i bot, l'IA, le statistiche). Risponde sempre
a quattro domande:

    legal_actions()  -> quali mosse può fare adesso il giocatore di turno?
    apply(action)    -> esegui questa mossa e aggiorna la partita
    is_over()        -> la partita è finita?
    scores()         -> quanti punti ha ciascuno?

PREPARAZIONE (tre varianti, vedi Setup)
- PRINCIPIANTE: 42 M€ e 10 carte gratis, nessuna corporazione.
- STANDARD: ognuno sceglie 1 corporazione tra 2 e compra quante vuole
  delle 10 carte iniziali, a 3 M€ l'una.
- PRELUDE: come standard, più 2 preludi scelti tra 4, giocati prima
  della prima generazione.

UNA GENERAZIONE
1. RICERCA: ognuno pesca 4 carte e decide, una per una, se comprarla
   (3 M€) o scartarla. Nella prima generazione si salta.
   Con il DRAFT (Game(..., draft=True)): ognuno riceve 4 carte, ne tiene una
   e passa le altre al giocatore alla sua sinistra (il successivo nell'ordine
   di turno); poi ne riceve 3, ne tiene una e ne passa 2, e così via finché
   ognuno ha scelto 4 carte. Poi decide quali di queste comprare.
2. AZIONI: a turno, ogni giocatore fa 1 o 2 azioni, oppure passa.
   Nella prima generazione, alcune corporazioni hanno un'azione iniziale
   obbligatoria.
3. PRODUZIONE: quando tutti hanno passato.

La partita finisce alla fine della generazione in cui i tre parametri
globali hanno raggiunto il massimo. Poi c'è un'ultima fase in cui ognuno
può ancora trasformare le piante in foreste.

DECISIONI IN ATTESA
Alcune azioni chiedono una scelta in più prima di essere complete:
- tessere da piazzare (state.pending_tiles): le mosse legali diventano
  le caselle dove metterle;
- bersaglio di un attacco (pending_attacks);
- carta da comprare o scartare (Business Network, Inventors' Guild:
  "guarda la prima carta del mazzo e comprala se vuoi");
- carte da vendere (vendita di brevetti: si sceglie una carta alla volta,
  poi "basta così");
- effetti da scegliere (pending_choices): "3 piante OPPURE 2 animali su una
  tua carta", e su quale carta mettere le risorse. Se c'è una sola
  possibilità, il motore la applica da solo;
- carte da tenere tra quelle guardate (Business Contacts: guardane 4,
  tienine 2);
- una carta da giocare subito (preludi Eccentric Sponsor ed Ecology
  Experts: gioca una carta dalla mano, oppure rinuncia);
- preludio da scegliere (Valley Trust): le mosse legali diventano i
  preludi pescati.
L'azione conta come "completa" solo quando non resta nulla in attesa.

AZIONI DELLE CARTE BLU
Ogni carta blu con un'azione (Card.actions) si può usare una volta per
generazione: Action(CARD_ACTION, carta, target=numero dell'alternativa,
option=scelta in più, per esempio la carta da cui togliere un animale).

COME PAGARE
Giocare una carta (o un'azione che si paga anche in metalli) compare più
volte nella lista, una per ogni modo sensato di pagare: con i metalli
(payment=None) oppure tenendoli ("senza metalli", "senza acciaio",
"senza titanio"). Così il giocatore può conservarli, per esempio per il
riconoscimento Miner.
"""

import itertools
import copy
import random
from enum import Enum
from tm_sim.fastenum import FastEnum

from tm_sim.actions import (
    CARD_PRICE,
    CARDS_PER_RESEARCH,
    HEAT_PER_TEMPERATURE,
    PATENT_PRICE,
    PAY_NO_METALS,
    PAY_NO_STEEL,
    PAY_NO_TITANIUM,
    PAYMENT_CHOICES,
    STANDARD_PROJECT_COST,
    STARTING_HAND,
    Action,
    ActionType,
)
from tm_sim.board import Board, Space, TilePlacement, TileType, as_placement
from tm_sim.card_data import PRELUDE_CARDS
from tm_sim.card_effects import CARD_TRIGGERS, SPECIAL_ACTIONS
from tm_sim.card_list import ALL_CARDS
from tm_sim.cards import (
    STANDARD_PAYMENT,
    Card,
    CardAction,
    CardResource,
    CardType,
    Payment,
    PaymentRules,
    PendingChoice,
    Scaled,
    Tag,
    pay_megacredits,
    pay_with_metals,
)
from tm_sim.corporations import ALL_CORPORATIONS, Corporation, FirstAction
from tm_sim.milestones import (
    AWARD_COSTS,
    AWARDS,
    AWARDS_BY_NAME,
    MAX_AWARDS,
    MAX_MILESTONES,
    MILESTONE_COST,
    MILESTONE_POINTS,
    MILESTONES,
    award_points,
)
from tm_sim.state import MAX_OXYGEN, MAX_TEMPERATURE, MIN_MC_PRODUCTION, GameState, Player, Resource

# Rete di sicurezza: se per un bug la partita non finisse mai,
# la interrompiamo dopo questo numero di generazioni.
MAX_GENERATIONS = 100

ACTIONS_PER_TURN = 2

# Il gioco da tavolo prevede da 1 a 5 giocatori. La partita in solitario
# ha regole speciali (avversario neutrale, 14 generazioni): per ora no.
MIN_PLAYERS = 2
MAX_PLAYERS = 5

BEGINNER_MEGACREDITS = 42        # corporazione per principianti
CORPORATIONS_DEALT = 2           # corporazioni tra cui scegliere
PRELUDES_DEALT = 4               # preludi pescati...
PRELUDES_KEPT = 2                # ...e quelli che si tengono
UNPLAYABLE_PRELUDE_BONUS = 15    # se un preludio non si può giocare: scartalo e prendi 15 M€
VALLEY_TRUST_PRELUDES = 3

_GAME_IDS = itertools.count()

NOBODY = "nessuno"               # bersaglio di un attacco facoltativo a cui si rinuncia

# Valori vecchi, tenuti per compatibilità con i test della variante principiante.
STARTING_MEGACREDITS = BEGINNER_MEGACREDITS


_SHARED: dict[int, object] = {}


def _shared_objects() -> dict[int, object]:
    """Carte, preludi e corporazioni: oggetti che non cambiano, da non copiare."""
    if not _SHARED:
        for obj in list(ALL_CARDS) + list(PRELUDE_CARDS) + list(ALL_CORPORATIONS):
            _SHARED[id(obj)] = obj
    return _SHARED


# --- Copia veloce della partita (per le simulazioni di MCTS) --------------
# copy.deepcopy esamina ogni oggetto, anche quelli che non cambiano mai (le carte,
# la forma della mappa): è lento. Qui copiamo solo ciò che può cambiare.
# Le liste di carte si copiano "in superficie": le carte stesse sono condivise.
_CLONE_SHALLOW_LISTS = ("deck", "discard_pile", "corporation_deck", "prelude_deck",
                        "final_queue", "pending_attacks", "pending_choices", "revealed")
_CLONE_SETS = ("_draft_picked", "passed")
_CLONE_KNOWN = set(_CLONE_SHALLOW_LISTS) | set(_CLONE_SETS) | {
    "rng", "state", "card_log", "_placeable_cache",
    # valori semplici (numeri, testi, enum): si copiano da soli
    "setup", "draft", "drafting", "first_player", "current", "actions_this_turn",
    "last_placed_space", "keep_left", "bonus_play", "selling", "sold_this_action",
    "move_count", "uid", "finished", "phase", "messages"}
_PLAYER_LISTS = ("hand", "played", "drafted", "draft_hand", "corporation_choices",
                 "prelude_choices", "preludes")


def _clone_player(player: Player) -> Player:
    new = copy.copy(player)
    new.resources = dict(player.resources)
    new.production = dict(player.production)
    for name in _PLAYER_LISTS:
        setattr(new, name, list(getattr(player, name)))
    new.used_actions = set(player.used_actions)
    new.card_resources = dict(player.card_resources)
    return new


def _clone_board(board: Board) -> Board:
    new = copy.copy(board)
    new.spaces = {sid: copy.copy(space) for sid, space in board.spaces.items()}
    new._by_coords = {key: new.spaces[space.id] for key, space in board._by_coords.items()}
    new._neighbors = {sid: [new.spaces[n.id] for n in near]
                      for sid, near in board._neighbors.items()}
    return new


def _clone_state(state: GameState, share_board: bool = False) -> GameState:
    new = copy.copy(state)
    new.players = [_clone_player(p) for p in state.players]
    new.planet = copy.copy(state.planet)
    new.claimed_milestones = dict(state.claimed_milestones)
    new.funded_awards = list(state.funded_awards)
    new.board = state.board if share_board else _clone_board(state.board)
    new.pending_tiles = list(state.pending_tiles)
    return new


class Setup(FastEnum):
    BEGINNER = "principiante"
    STANDARD = "standard"
    PRELUDE = "prelude"


EXPANSIONS = {
    Setup.BEGINNER: {"base", "corporate_era"},
    Setup.STANDARD: {"base", "corporate_era"},
    Setup.PRELUDE: {"base", "corporate_era", "prelude"},
}


class Phase(FastEnum):
    SETUP = "preparazione"
    PRELUDES = "preludi"
    RESEARCH = "ricerca"
    ACTION = "azioni"
    FINAL_GREENERY = "ultime foreste"


class Game:
    def __init__(self, player_names: list[str], seed: int | None = None,
                 cards: list[Card] | None = None, setup: Setup = Setup.BEGINNER,
                 corporations: list[Corporation] | None = None,
                 preludes: list[Card] | None = None, draft: bool = False):
        """Crea una nuova partita.

        seed: con lo stesso seed il mazzo viene mescolato sempre allo stesso
              modo, così una partita si può riprodurre esattamente.
        cards: le carte del mazzo. None = quelle delle espansioni in uso;
               [] = nessuna (utile nei test).
        setup: la variante di preparazione (vedi Setup).
        corporations, preludes: per i test, si possono imporre quelle in gioco.
        draft: True = variante con il draft nella fase di ricerca.
        """
        if not MIN_PLAYERS <= len(player_names) <= MAX_PLAYERS:
            raise ValueError(f"Servono da {MIN_PLAYERS} a {MAX_PLAYERS} giocatori")
        if len(set(player_names)) != len(player_names):
            raise ValueError("I nomi dei giocatori devono essere diversi")

        self.setup = setup
        self.draft = draft
        self.drafting = False                 # draft in corso
        self._draft_picked: set[int] = set()  # chi ha già scelto in questo giro del draft
        self.card_log: list[tuple[str, str, str, int]] = []   # vedi sotto
        # Messaggi sugli effetti "a scatto" (es. "Optimal Aerobraking: +3 M€, +3 calore").
        # None = non raccoglierli (simulazioni); play.py mette una lista e li mostra.
        self.messages: list[str] | None = None
        expansions = EXPANSIONS[setup]
        self.rng = random.Random(seed)

        if cards is None:
            cards = [c for c in ALL_CARDS if c.expansion in expansions]
        self.deck: list[Card] = list(cards)
        self.rng.shuffle(self.deck)
        self.discard_pile: list[Card] = []

        if corporations is None:
            corporations = [c for c in ALL_CORPORATIONS if c.expansion in expansions]
        self.corporation_deck = list(corporations)
        self.rng.shuffle(self.corporation_deck)

        if preludes is None:
            preludes = list(PRELUDE_CARDS) if setup is Setup.PRELUDE else []
        self.prelude_deck = list(preludes)
        self.rng.shuffle(self.prelude_deck)

        players = [Player(name) for name in player_names]
        self.state = GameState(players=players)
        self.first_player = 0          # indice del primo giocatore della generazione
        self.current = 0               # indice del giocatore di turno
        self.actions_this_turn = 0     # azioni già fatte in questo turno (0 o 1)
        self.passed: set[int] = set()  # indici di chi ha passato
        self.final_queue: list[int] = []  # chi deve ancora fare le ultime foreste
        # Attacchi in attesa di un bersaglio: (tipo, carta). Tipi: "plants",
        # "production", "raid", "flood". Si risolvono dopo le tessere.
        self.pending_attacks: list[tuple[str, Card]] = []
        self.last_placed_space: str | None = None   # serve a Flooding
        self.pending_choices: list[PendingChoice] = []   # vedi "DECISIONI IN ATTESA"
        self.revealed: list[Card] = []  # carte guardate, tra cui sceglierne da tenere
        self.keep_left = 0              # quante tenerne ancora
        self.bonus_play = False        # Eccentric Sponsor: giocare subito una carta
        self.selling = False           # vendita di brevetti in corso
        self.sold_this_action = 0      # carte vendute finora in questa vendita
        # Quante mosse sono state giocate: cambia a ogni apply(). Permette a chi
        # fa calcoli pesanti (i bot) di riusarli finché la partita non cambia.
        self.move_count = 0
        self._placeable_cache: dict = {}   # vedi _can_place
        self.uid = next(_GAME_IDS)          # identifica la partita nelle cache dei bot
        # Registro per le statistiche: cosa succede a ogni carta.
        #   card_log: (giocatore, carta, evento, generazione)
        #   evento: "offerta" (pescata in ricerca o all'inizio), "comprata", "giocata",
        #           "venduta" (vendita di brevetti)
        #   (la lista è creata all'inizio di __init__, prima della preparazione)
        self.finished = False

        if setup is Setup.BEGINNER:
            for player in players:
                player.gain(Resource.MEGACREDITS, BEGINNER_MEGACREDITS)
                player.hand.extend(self._draw(STARTING_HAND))
                for card in player.hand:   # gratis, ma per le statistiche contano come comprate
                    self.card_log.append((player.name, card.name, "offerta", 1))
                    self.card_log.append((player.name, card.name, "comprata", 1))
            self.phase = Phase.ACTION
        else:
            for player in players:
                player.corporation_choices = self._deal(self.corporation_deck, CORPORATIONS_DEALT)
                player.prelude_choices = self._deal(self.prelude_deck, PRELUDES_DEALT)
                player.drafted = self._draw(STARTING_HAND)
            self.phase = Phase.SETUP

    # ------------------------------------------------------------------
    # Copia della partita (per i bot che "pensano avanti", come MCTS)
    # ------------------------------------------------------------------

    def clone(self, share_board: bool = False) -> "Game":
        """Una copia indipendente della partita: le mosse sulla copia non toccano l'originale.

        Le carte e le corporazioni non si copiano (non cambiano mai: sono le stesse
        per tutte le partite), e il registro delle statistiche riparte vuoto.
        La copia ha un nuovo uid, così le memorie dei bot non la confondono con l'originale.

        share_board=True: la mappa NON si copia (è la parte più costosa). Solo per le
        copie su cui si fanno ipotesi senza piazzare tessere ("e se comprassi queste
        carte?"): piazzare una tessera sulla copia cambierebbe anche l'originale.
        """
        new = object.__new__(Game)
        attributes = dict(self.__dict__)
        for name in _CLONE_SHALLOW_LISTS:
            attributes[name] = list(attributes[name])
        for name in _CLONE_SETS:
            attributes[name] = set(attributes[name])
        attributes["rng"] = random.Random()
        attributes["rng"].setstate(self.rng.getstate())
        attributes["state"] = _clone_state(self.state, share_board)
        attributes["card_log"] = []
        attributes["_placeable_cache"] = {}
        attributes["messages"] = None          # le copie (simulazioni) non raccontano
        unknown = set(attributes) - _CLONE_KNOWN
        if unknown:      # un attributo nuovo che la copia veloce non conosce: copia completa
            memo = dict(_shared_objects())
            memo[id(self.state)] = attributes["state"]
            for name in unknown:
                attributes[name] = copy.deepcopy(attributes[name], memo)
        new.__dict__ = attributes
        new.uid = next(_GAME_IDS)
        return new

    def slow_clone(self) -> "Game":
        """La copia "generica" (lenta) di Python: serve ai test per controllare clone()."""
        memo = dict(_shared_objects())
        memo[id(self.card_log)] = []
        memo[id(self._placeable_cache)] = {}
        new = copy.deepcopy(self, memo)
        new.uid = next(_GAME_IDS)
        return new

    # ------------------------------------------------------------------
    # Le quattro domande
    # ------------------------------------------------------------------

    @property
    def current_player(self) -> Player:
        return self.state.players[self.current]

    @property
    def pending_tile(self) -> TilePlacement | None:
        """La prossima tessera da piazzare, se ce n'è una."""
        return self.state.pending_tiles[0] if self.state.pending_tiles else None

    def legal_actions(self) -> list[Action]:
        """Tutte le azioni che il giocatore di turno può fare adesso."""
        if self.finished:
            return []
        if self.state.pending_tiles:
            return self._legal_placements()
        if self.pending_choices:
            return self._choice_options(self.pending_choices[0])
        if self.revealed:
            return [Action(ActionType.KEEP_CARD, c.name) for c in self.revealed]
        if self.pending_attacks:
            return self._attack_options(*self.pending_attacks[0])
        if self.bonus_play:
            return self._legal_bonus_play()
        if self.phase is Phase.ACTION and self.current_player.drafted:   # Business Network
            return self._buy_one_choices(self.current_player)
        if self.selling:
            return self._legal_selling_actions()
        if self.phase is Phase.SETUP:
            return self._legal_setup_actions()
        if self.phase is Phase.PRELUDES:
            return self._legal_prelude_actions(self.current_player.preludes)
        if self.phase is Phase.RESEARCH:
            return self._legal_research_actions()
        if self.phase is Phase.FINAL_GREENERY:
            return self._legal_final_actions()
        if self.current_player.prelude_choices:          # Valley Trust
            return self._legal_prelude_actions(self.current_player.prelude_choices)
        return self._legal_action_phase_actions()

    def apply(self, action: Action, check: bool = True) -> None:
        """Esegue un'azione del giocatore di turno.

        check=False salta il controllo "è una mossa legale?": serve alle simulazioni,
        dove il bot sceglie SEMPRE dalla lista di legal_actions() appena calcolata
        (ricalcolarla solo per controllare raddoppierebbe il lavoro)."""
        if check and action not in self.legal_actions():
            raise ValueError(f"Azione non legale adesso: {action}")
        self.move_count += 1

        t = action.type
        if self.bonus_play and t in (ActionType.PLAY_CARD, ActionType.SKIP_BONUS_PLAY):
            self._apply_bonus_play(action)
        elif t is ActionType.PLACE_TILE:
            self._apply_placement(action)
        elif t is ActionType.CHOOSE_EFFECT:
            self._perform_choice(self.pending_choices.pop(0), action)
            self._resolve_pending()
        elif t is ActionType.KEEP_CARD:
            self._keep_card(action.card)
            self._resolve_pending()
        elif t is ActionType.ATTACK:
            self._apply_attack(action)
        elif self.phase is Phase.SETUP:
            self._apply_setup(action)
        elif t in (ActionType.PLAY_PRELUDE, ActionType.DISCARD_PRELUDE):
            self._apply_prelude(action)
        elif self.phase is Phase.RESEARCH:
            self._apply_research(action)
        elif t in (ActionType.BUY_CARD, ActionType.SKIP_CARD):    # durante un'azione
            self._buy_or_skip(self.current_player, action)
            self._resolve_pending()
        elif t in (ActionType.SELL_CARD, ActionType.STOP_SELLING):
            self._apply_selling(action)
        elif t is ActionType.PASS and self.phase is Phase.FINAL_GREENERY:
            self.final_queue.pop(0)
            self._advance_final()
        elif t is ActionType.PASS:
            self.passed.add(self.current)
            self._next_turn()
        elif t is ActionType.END_TURN:
            self._next_turn()
        else:
            self._execute(action)
            self.actions_this_turn += 1
            self._resolve_pending()

    def is_over(self) -> bool:
        return self.finished

    def score(self, player: Player) -> int:
        """Punti vittoria totali di un giocatore.

        Durante la partita i riconoscimenti sono calcolati sulla situazione
        attuale: è una stima, il valore vero si sa solo alla fine.
        """
        milestones = sum(1 for owner in self.state.claimed_milestones.values()
                         if owner == player.name)
        awards = sum(award_points(AWARDS_BY_NAME[name], self.state.players)[player.name]
                     for name in self.state.funded_awards)
        board = self.state.board
        map_points = board.city_points(player.name) + board.special_tile_points(player.name)
        total_cities = board.count_tiles(TileType.CITY)
        variable = sum(card.variable_points(player, player.card_resources.get(card.name, 0),
                                            total_cities)
                       for card in player.played)
        return (player.victory_points() + milestones * MILESTONE_POINTS + awards
                + map_points + variable)

    def scores(self) -> dict[str, int]:
        """Punti vittoria di ogni giocatore, per nome."""
        return {p.name: self.score(p) for p in self.state.players}

    def winners(self) -> list[str]:
        """Chi ha più punti. In caso di parità vince chi ha più megacrediti.

        Restituisce una lista perché può esserci ancora parità.
        """
        def key(p: Player) -> tuple[int, int]:
            return (self.score(p), p.resources[Resource.MEGACREDITS])

        best = max(key(p) for p in self.state.players)
        return [p.name for p in self.state.players if key(p) == best]

    # ------------------------------------------------------------------
    # Soldi, sconti e poteri: domande che dipendono dalla corporazione
    # ------------------------------------------------------------------

    # Ogni modificatore somma l'effetto della corporazione e quello delle
    # carte blu in gioco (per esempio Teractor + Earth Office: -6 sulle carte Terra).

    # Il parametro facoltativo `active` (le carte blu del giocatore) serve solo
    # a non ricalcolarle centinaia di volte quando elenchiamo le mosse legali.

    def payment_rules(self, player: Player, active: list[Card] | None = None) -> PaymentRules:
        corp = player.corporation
        base = corp.payment_rules if corp else STANDARD_PAYMENT
        if active is None:
            active = player.active_cards()
        steel_bonus = sum(c.steel_value_bonus for c in active)
        titanium_bonus = sum(c.titanium_value_bonus for c in active)
        if not steel_bonus and not titanium_bonus:
            return base
        return PaymentRules(steel_value=base.steel_value + steel_bonus,
                            titanium_value=base.titanium_value + titanium_bonus,
                            heat_as_megacredits=base.heat_as_megacredits)

    @staticmethod
    def rules_for_card(card: Card, rules: PaymentRules) -> PaymentRules:
        """Le carte che consumano calore (Local Heat Trapping) non si pagano con
        quello stesso calore: per Helion, niente calore come M€ su quelle carte."""
        if rules.heat_as_megacredits and card.resources.get(Resource.HEAT, 0) < 0:
            return PaymentRules(rules.steel_value, rules.titanium_value, heat_as_megacredits=False)
        return rules

    def card_cost(self, player: Player, card: Card, active: list[Card] | None = None) -> int:
        if active is None:
            active = player.active_cards()
        discount = player.corporation.card_discount(card) if player.corporation else 0
        discount += sum(c.card_discount(card) for c in active)
        discount += player.next_card_discount        # Indentured Workers, Eccentric Sponsor
        return max(0, card.cost - discount)

    def requirement_leeway(self, player: Player, active: list[Card] | None = None) -> int:
        if active is None:
            active = player.active_cards()
        leeway = player.corporation.requirement_leeway if player.corporation else 0
        return leeway + sum(c.requirement_leeway for c in active) + player.next_card_leeway

    def standard_project_cost(self, player: Player, action_type: ActionType) -> int:
        cost = STANDARD_PROJECT_COST[action_type]
        if player.corporation:
            cost -= player.corporation.standard_project_discounts.get(action_type, 0)
        return max(0, cost)

    def plants_per_greenery(self, player: Player) -> int:
        return player.corporation.plants_per_greenery if player.corporation else 8

    def can_pay(self, player: Player, amount: int, rules: PaymentRules | None = None) -> bool:
        rules = rules or self.payment_rules(player)
        return pay_megacredits(player, amount, rules) is not None

    def pay(self, player: Player, amount: int) -> None:
        """Paga una somma in M€ (con il calore, se la corporazione lo permette)."""
        payment = pay_megacredits(player, amount, self.payment_rules(player))
        player.spend(Resource.MEGACREDITS, payment.megacredits)
        player.spend(Resource.HEAT, payment.heat)

    def payment_microbes(self, player: Player, card: Card, active: list[Card] | None = None) -> int:
        """Microbi utilizzabili per pagare questa carta (Psychrophiles: carte pianta)."""
        if active is None:
            active = player.active_cards()
        return sum(player.card_resources.get(c.name, 0) for c in active
                   if c.resources_as_payment and c.resources_as_payment[0] in card.tags)

    def _spend_payment(self, player: Player, payment: Payment, card: Card | None = None,
                       active: list[Card] | None = None) -> None:
        player.spend(Resource.MEGACREDITS, payment.megacredits)
        player.spend(Resource.HEAT, payment.heat)
        player.spend(Resource.STEEL, payment.steel)
        player.spend(Resource.TITANIUM, payment.titanium)
        left = payment.microbes
        for source in (active or []):
            if left and source.resources_as_payment and card and source.resources_as_payment[0] in card.tags:
                used = min(left, player.card_resources.get(source.name, 0))
                player.add_card_resource(source.name, -used)
                left -= used

    def _payment_choices(self, player: Player, card: Card, cost: int, rules: PaymentRules,
                         microbes: int) -> list[str | None]:
        """I modi sensati di pagare una carta (già verificato: con i metalli si può).

        None = usa i metalli che servono. Le alternative compaiono solo se
        cambiano davvero qualcosa e se te le puoi permettere.
        """
        choices: list[str | None] = [None]
        default = card.payment_for(player, cost, rules, microbes)
        if not (default.steel or default.titanium):
            return choices
        options = [(PAY_NO_METALS, False, False)]
        if default.steel and default.titanium:
            options += [(PAY_NO_STEEL, False, True), (PAY_NO_TITANIUM, True, False)]
        for label, steel, titanium in options:
            if card.payment_for(player, cost, rules, microbes, steel, titanium) is not None:
                choices.append(label)
        return choices

    def shortfall(self, player: Player, card: Card, active: list[Card] | None = None) -> int:
        """Quanti M€ mancano per pagare la carta (0 = te la puoi già permettere)."""
        if active is None:
            active = player.active_cards()
        rules = self.payment_rules(player, active)
        budget = player.resources[Resource.MEGACREDITS]
        if rules.heat_as_megacredits:
            budget += player.resources[Resource.HEAT]
        if Tag.BUILDING in card.tags:
            budget += player.resources[Resource.STEEL] * rules.steel_value
        if Tag.SPACE in card.tags:
            budget += player.resources[Resource.TITANIUM] * rules.titanium_value
        budget += 2 * self.payment_microbes(player, card, active)
        return max(0, self.card_cost(player, card, active) - budget)

    def playable_except_cost(self, player: Player, card: Card,
                             active: list[Card] | None = None) -> bool:
        """La carta si potrebbe giocare, se solo avessi i soldi?"""
        leeway = self.requirement_leeway(player, active)
        return (card.requirements.are_met(self.state, player, leeway)
                and card.production_change_is_possible(player)
                and card.resource_loss_is_possible(player)
                and self._tiles_placeable(card) and self._attack_possible(card)
                and self._card_targets_exist(player, card) and self._choices_possible(card))

    def reveal_card(self) -> Card | None:
        """Gira la prima carta del mazzo (chi la chiede decide dove finisce)."""
        drawn = self._draw(1)
        return drawn[0] if drawn else None

    def draw_cards(self, player: Player, n: int, tag=None) -> None:
        """Il giocatore pesca n carte (con tag: solo carte con quel tag;
        le altre girate nel frattempo vanno negli scarti)."""
        if tag is None:
            player.hand.extend(self._draw(n))
            return
        found = 0
        max_reveals = len(self.deck) + len(self.discard_pile)
        for _ in range(max_reveals):
            if found == n:
                break
            revealed = self._draw(1)
            if not revealed:
                break
            if tag in revealed[0].tags:
                player.hand.append(revealed[0])
                found += 1
            else:
                self.discard_pile.append(revealed[0])

    def _corporation_triggers(self):
        """(giocatore, corporazione) per chi ha una corporazione."""
        return [(p, p.corporation) for p in self.state.players if p.corporation]

    # ------------------------------------------------------------------
    # Preparazione: corporazione, preludi, carte iniziali
    # ------------------------------------------------------------------

    def _legal_setup_actions(self) -> list[Action]:
        player = self.current_player
        if player.corporation is None:
            return [Action(ActionType.CHOOSE_CORPORATION, c.name) for c in player.corporation_choices]
        if player.prelude_choices and len(player.preludes) < PRELUDES_KEPT:
            return [Action(ActionType.KEEP_PRELUDE, c.name) for c in player.prelude_choices]
        return self._legal_research_actions()

    def _apply_setup(self, action: Action) -> None:
        player = self.current_player
        if action.type is ActionType.CHOOSE_CORPORATION:
            corp = next(c for c in player.corporation_choices if c.name == action.card)
            player.corporation_choices = []
            self._start_corporation(player, corp)
        elif action.type is ActionType.KEEP_PRELUDE:
            prelude = next(c for c in player.prelude_choices if c.name == action.card)
            player.prelude_choices.remove(prelude)
            player.preludes.append(prelude)
            if len(player.preludes) == PRELUDES_KEPT:
                player.prelude_choices = []
        else:
            self._buy_cards(player, action)
        self._advance_setup()

    def _start_corporation(self, player: Player, corp: Corporation) -> None:
        player.corporation = corp
        player.gain(Resource.MEGACREDITS, corp.starting_megacredits)
        for resource, amount in corp.production.items():
            player.change_production(resource, amount)
        for resource, amount in corp.resources.items():
            player.gain(resource, amount)
        if corp.starting_draw:
            self.draw_cards(player, corp.starting_draw)
        player.first_action_done = corp.first_action is None

    def _setup_done(self, player: Player) -> bool:
        return (player.corporation is not None
                and not (player.prelude_choices and len(player.preludes) < PRELUDES_KEPT)
                and not player.drafted)

    def _advance_setup(self) -> None:
        """Resta sul giocatore finché non ha finito, poi passa al prossimo."""
        n = len(self.state.players)
        for offset in range(n):
            index = (self.current + offset) % n
            if not self._setup_done(self.state.players[index]):
                self.current = index
                return
        if any(p.preludes for p in self.state.players):
            self.phase = Phase.PRELUDES
            self.current = self.first_player
            self._advance_preludes()
        else:
            self._start_first_generation()

    def _start_first_generation(self) -> None:
        self.phase = Phase.ACTION
        self.current = self.first_player
        self.actions_this_turn = 0

    # ------------------------------------------------------------------
    # Preludi
    # ------------------------------------------------------------------

    def _legal_prelude_actions(self, preludes: list[Card]) -> list[Action]:
        player = self.current_player
        actions = [Action(ActionType.PLAY_PRELUDE, p.name)
                   for p in preludes if p.can_be_played(self.state, player, cost=0)
                   and self._tiles_placeable(p)]
        if not actions:
            # Nessuno si può giocare: si scarta e si prendono 15 M€.
            actions = [Action(ActionType.DISCARD_PRELUDE, p.name) for p in preludes]
        return actions

    def _apply_prelude(self, action: Action) -> None:
        player = self.current_player
        from_valley_trust = self.phase is Phase.ACTION
        source = player.prelude_choices if from_valley_trust else player.preludes
        prelude = next(c for c in source if c.name == action.card)
        source.remove(prelude)

        if action.type is ActionType.PLAY_PRELUDE:
            player.played.append(prelude)
            self._log(player, prelude, "giocata")
            self._apply_card_effects(player, prelude)
            self._card_played_triggers(player, prelude)
        else:
            player.gain(Resource.MEGACREDITS, UNPLAYABLE_PRELUDE_BONUS)

        if from_valley_trust:
            player.prelude_choices = []   # gli altri due si scartano
        self._resolve_pending()

    def _advance_preludes(self) -> None:
        """Ogni giocatore, in ordine, gioca i suoi preludi."""
        n = len(self.state.players)
        for offset in range(n):
            index = (self.current + offset) % n
            if self.state.players[index].preludes:
                self.current = index
                return
        self._start_first_generation()

    # ------------------------------------------------------------------
    # Piazzamento delle tessere e azioni "in attesa"
    # ------------------------------------------------------------------

    def _legal_placements(self) -> list[Action]:
        spaces = self.state.board.available_spaces(self.pending_tile, self.current_player.name)
        return [Action(ActionType.PLACE_TILE, space=s.id) for s in spaces]

    def _can_place(self, tile: TileType | TilePlacement) -> bool:
        """C'è almeno una casella valida? La risposta cambia solo quando cambia
        la mappa: la ricordiamo finché non viene piazzata un'altra tessera
        (è una domanda che il motore si fa migliaia di volte per partita)."""
        key = (self.state.board.version, as_placement(tile), self.current_player.name)
        cached = self._placeable_cache.get(key)
        if cached is None:
            if len(self._placeable_cache) > 64:
                self._placeable_cache.clear()
            cached = bool(self.state.board.available_spaces(tile, self.current_player.name))
            self._placeable_cache[key] = cached
        return cached

    def _tiles_placeable(self, card: Card) -> bool:
        """Una carta che piazza città, foreste o tessere speciali si gioca solo
        se c'è una casella valida. Gli oceani fanno eccezione: a oceani finiti
        (o senza caselle) la carta si gioca lo stesso, senza la tessera."""
        return all(self._can_place(p) for p in card.tiles if p.tile is not TileType.OCEAN)

    def _attack_possible(self, card: Card) -> bool:
        """Una riduzione di produzione è obbligatoria: serve almeno un bersaglio
        (anche te stesso) che ne abbia abbastanza. Gli altri attacchi sono "fino a"."""
        if card.decrease_any_production is None:
            return True
        resource, amount = card.decrease_any_production
        return any(self.can_lose_production(p, resource, amount) for p in self.state.players)

    @staticmethod
    def can_lose_production(player: Player, resource: Resource, amount: int) -> bool:
        minimum = MIN_MC_PRODUCTION if resource is Resource.MEGACREDITS else 0
        return player.production[resource] - amount >= minimum

    def _apply_placement(self, action: Action) -> None:
        player = self.current_player
        placement = self.state.pending_tiles.pop(0)
        tile = placement.tile
        cards_to_draw = self.state.place_tile(player, placement, action.space)
        if tile is TileType.CLAIM:            # solo un segnalino: niente bonus né effetti
            self._resolve_pending()
            return
        self.last_placed_space = action.space
        self.draw_cards(player, cards_to_draw)
        space = self.state.board.spaces[action.space]
        self._tile_placed_triggers(player, space, tile)
        self._resolve_pending()

    def _resolve_pending(self) -> None:
        """Da chiamare dopo ogni azione, piazzamento o scelta.

        Scarta le tessere in attesa che non hanno più posto sulla mappa
        (succede di rado, a mappa quasi piena). Se non resta nulla da
        decidere, l'azione è completa.
        """
        # Qui niente memoria (cache): ricalcoliamo, per sicurezza, se c'è ancora posto.
        while self.state.pending_tiles and not self.state.board.available_spaces(
                self.pending_tile, self.current_player.name):
            self.state.pending_tiles.pop(0)
        if self.state.pending_tiles:
            return
        # Le scelte con una sola possibilità (o nessuna) si fanno da sole.
        while self.pending_choices:
            options = self._choice_options(self.pending_choices[0])
            if len(options) > 1:
                return
            pending = self.pending_choices.pop(0)
            if options:
                self._perform_choice(pending, options[0])
            if self.state.pending_tiles:          # (non succede con le carte attuali)
                return
        if self.revealed:
            if len(self.revealed) > self.keep_left:
                return
            for card in list(self.revealed):      # meno carte di quante se ne tengono
                self._keep_card(card.name)
        # Un attacco senza nessun bersaglio possibile si salta da solo.
        while self.pending_attacks and self._no_real_target(*self.pending_attacks[0]):
            self.pending_attacks.pop(0)
        player = self.current_player
        if self.bonus_play and not self._legal_bonus_play()[:-1]:
            self._end_bonus_play()            # nessuna carta giocabile: il preludio "fallisce"
        if self.pending_attacks or self.selling or self.bonus_play or (
                self.phase is Phase.ACTION and (player.prelude_choices or player.drafted)):
            return
        self._action_completed()

    def _action_completed(self) -> None:
        if self.phase is Phase.PRELUDES:
            self._advance_preludes()
        elif self.phase is Phase.FINAL_GREENERY:
            self._advance_final()
        elif self.actions_this_turn >= ACTIONS_PER_TURN:
            self._next_turn()

    # ------------------------------------------------------------------
    # Attacchi
    # ------------------------------------------------------------------

    @staticmethod
    def is_protected(player: Player, what, card_name: str | None = None) -> bool:
        """Protected Habitats protegge piante, animali e microbi; Pets i suoi animali."""
        if card_name == "Pets":
            return True
        has_habitats = any(c.name == "Protected Habitats" for c in player.active_cards())
        return has_habitats and what in (Resource.PLANTS, CardResource.ANIMAL, CardResource.MICROBE)

    def _attack_options(self, kind: str, card: Card) -> list[Action]:
        """I bersagli possibili di un attacco in attesa.

        "nessuno" è sempre possibile, tranne per la riduzione di produzione
        (obbligatoria: lì si può essere costretti a colpire sé stessi).
        """
        attacker = self.current_player
        others = [p for p in self.state.players if p is not attacker]
        options: list[Action] = []

        def option(target: Player, what: str | None = None) -> Action:
            return Action(ActionType.ATTACK, card.name, target=target.name, option=what)

        if kind == "plants":
            options = [option(p, Resource.PLANTS.value) for p in others
                       if p.resources[Resource.PLANTS] > 0 and not self.is_protected(p, Resource.PLANTS)]
        elif kind == "production":
            resource, amount = card.decrease_any_production
            # Prima gli avversari, poi (solo se possibile) sé stessi.
            options = [option(p, resource.value) for p in others + [attacker]
                       if self.can_lose_production(p, resource, amount)]
            return options
        elif kind == "raid":
            for what, _amount in card.raid:
                for p in others:
                    if isinstance(what, Resource):
                        if p.resources[what] > 0 and not self.is_protected(p, what):
                            options.append(option(p, what.value))
                    else:   # risorsa su una carta, es. animali
                        for c in p.played:
                            if (c.resource_type is what and p.card_resources.get(c.name, 0) > 0
                                    and not self.is_protected(p, what, c.name)):
                                options.append(option(p, f"{what.value}:{c.name}"))
        elif kind == "flood":
            space = self.state.board.spaces.get(self.last_placed_space or "")
            if space is not None:
                owners = {n.owner for n in self.state.board.neighbors(space)
                          if n.owner and n.owner != attacker.name}
                options = [option(p, Resource.MEGACREDITS.value) for p in others
                           if p.name in owners and p.resources[Resource.MEGACREDITS] > 0]
        return options + [Action(ActionType.ATTACK, card.name, target=NOBODY)]

    def _no_real_target(self, kind: str, card: Card) -> bool:
        options = self._attack_options(kind, card)
        return all(o.target == NOBODY for o in options)   # vale anche per "nessuna opzione"

    def attack_amount(self, kind: str, card: Card, target: Player, what: str) -> int:
        """Quanto viene davvero tolto al bersaglio ("fino a N": non più di quanto ha)."""
        if kind == "plants":
            return min(card.remove_any_plants, target.resources[Resource.PLANTS])
        if kind == "production":
            return card.decrease_any_production[1]
        if kind == "flood":
            return min(card.flood_raid, target.resources[Resource.MEGACREDITS])
        resource_name, _, card_name = what.partition(":")
        for res, cap in card.raid:
            if res.value == resource_name:
                have = (target.card_resources.get(card_name, 0) if card_name
                        else target.resources[res])
                return min(cap, have)
        return 0

    def _apply_attack(self, action: Action) -> None:
        kind, card = self.pending_attacks.pop(0)
        attacker = self.current_player
        if action.target != NOBODY:
            target = next(p for p in self.state.players if p.name == action.target)
            amount = self.attack_amount(kind, card, target, action.option)
            if kind == "plants":
                target.spend(Resource.PLANTS, amount)
            elif kind == "production":
                target.change_production(card.decrease_any_production[0], -amount)
            elif kind == "flood":
                target.spend(Resource.MEGACREDITS, amount)
            else:
                resource_name, _, card_name = action.option.partition(":")
                if card_name:
                    target.add_card_resource(card_name, -amount)
                else:
                    resource = Resource(resource_name)
                    target.spend(resource, amount)
                    if card.raid_steals:
                        attacker.gain(resource, amount)
        self._resolve_pending()

    # ------------------------------------------------------------------
    # Fase di ricerca
    # ------------------------------------------------------------------

    def _legal_research_actions(self) -> list[Action]:
        player = self.current_player
        if self.drafting:
            return [Action(ActionType.DRAFT_CARD, c.name) for c in player.draft_hand]
        return self._buy_choices(player)

    def _buy_choices(self, player: Player) -> list[Action]:
        """Tutte le carte pescate si guardano INSIEME e si decide in un colpo solo
        quali comprare: una mossa per ogni gruppo che ci si può permettere
        (con 10 carte fino a 1024 gruppi, con 4 carte 16)."""
        names = [c.name for c in player.drafted]
        affordable = player.resources[Resource.MEGACREDITS] // CARD_PRICE
        actions = []
        for k in range(min(len(names), affordable) + 1):
            for group in itertools.combinations(names, k):
                actions.append(Action(ActionType.BUY_CARDS, cards=group))
        return actions

    def _buy_one_choices(self, player: Player) -> list[Action]:
        """Durante un'azione (Business Network): una sola carta, comprala o scartala."""
        card = player.drafted[0]
        actions = [Action(ActionType.SKIP_CARD, card.name)]
        if player.resources[Resource.MEGACREDITS] >= CARD_PRICE:
            actions.append(Action(ActionType.BUY_CARD, card.name))
        return actions

    def _buy_cards(self, player: Player, action: Action) -> None:
        """Compra le carte scelte (3 M€ l'una), scarta le altre."""
        chosen = set(action.cards)
        if not chosen <= {c.name for c in player.drafted} or len(chosen) != len(action.cards):
            raise ValueError(f"Carte non disponibili: {action.cards}")
        if len(chosen) * CARD_PRICE > player.resources[Resource.MEGACREDITS]:
            raise ValueError("Non hai abbastanza M€ per comprare tutte queste carte")
        for card in player.drafted:
            self._log(player, card, "offerta")
            if card.name in chosen:
                self._log(player, card, "comprata")
                player.spend(Resource.MEGACREDITS, CARD_PRICE)
                player.hand.append(card)
            else:
                self.discard_pile.append(card)
        player.drafted = []

    # ------------------------------------------------------------------
    # Vendita di brevetti
    # ------------------------------------------------------------------

    def _legal_selling_actions(self) -> list[Action]:
        """Una carta alla volta; "basta così" dopo averne venduta almeno una."""
        actions = [Action(ActionType.SELL_CARD, c.name) for c in self.current_player.hand]
        if self.sold_this_action:
            actions.append(Action(ActionType.STOP_SELLING))
        return actions

    def _apply_selling(self, action: Action) -> None:
        player = self.current_player
        if action.type is ActionType.SELL_CARD:
            card = next(c for c in player.hand if c.name == action.card)
            player.hand.remove(card)
            self.discard_pile.append(card)
            player.gain(Resource.MEGACREDITS, PATENT_PRICE)
            self._log(player, card, "venduta")
            self.sold_this_action += 1
            if not player.hand:
                self.selling = False
        else:
            self.selling = False
        self._resolve_pending()

    def _log(self, player: Player, card: Card, event: str) -> None:
        self.card_log.append((player.name, card.name, event, self.state.generation))

    def _buy_or_skip(self, player: Player, action: Action) -> None:
        card = player.drafted.pop(0)
        self._log(player, card, "offerta")
        if action.type is ActionType.BUY_CARD:
            self._log(player, card, "comprata")
            player.spend(Resource.MEGACREDITS, CARD_PRICE)
            player.hand.append(card)
        else:
            self.discard_pile.append(card)

    def _apply_research(self, action: Action) -> None:
        if action.type is ActionType.DRAFT_CARD:
            player = self.current_player
            card = next(c for c in player.draft_hand if c.name == action.card)
            player.draft_hand.remove(card)
            player.drafted.append(card)              # la terrà fino alla scelta di comprarla
            self._draft_picked.add(self.current)
        else:
            self._buy_cards(self.current_player, action)
        self._advance_research()

    def _start_research(self) -> None:
        self.phase = Phase.RESEARCH
        for player in self.state.players:
            cards = self._draw(CARDS_PER_RESEARCH)
            if self.draft:
                player.draft_hand = cards
            else:
                player.drafted = cards
        self.drafting = self.draft
        self._draft_picked = set()
        self.current = self.first_player
        self._advance_research()

    def _pass_draft_hands(self) -> None:
        """Ognuno passa le carte rimaste al giocatore alla sua sinistra (il successivo)."""
        players = self.state.players
        hands = [p.draft_hand for p in players]
        for i, player in enumerate(players):
            player.draft_hand = hands[(i - 1) % len(players)]   # le riceve da destra

    def _advance_research(self) -> None:
        """Passa al prossimo giocatore che ha ancora qualcosa da decidere.

        Con il draft: a ogni giro tutti scelgono una carta (nell'ordine di turno),
        poi le carte rimaste passano a sinistra. Finito il draft, ognuno decide
        quali carte comprare. Se nessuno ha più niente, inizia la fase delle azioni.
        """
        n = len(self.state.players)
        while self.drafting:
            for offset in range(n):
                index = (self.first_player + offset) % n
                if index not in self._draft_picked and self.state.players[index].draft_hand:
                    self.current = index
                    return
            self._pass_draft_hands()             # tutti hanno scelto: si passa
            self._draft_picked = set()
            if not any(p.draft_hand for p in self.state.players):
                self.drafting = False
                self.current = self.first_player
        for offset in range(n):
            index = (self.current + offset) % n
            if self.state.players[index].drafted:
                self.current = index
                return
        self.phase = Phase.ACTION
        self.current = self.first_player

    def _draw(self, n: int) -> list[Card]:
        """Pesca n carte dal mazzo. Se il mazzo finisce, rimescola gli scarti."""
        drawn = []
        for _ in range(n):
            if not self.deck:
                if not self.discard_pile:
                    break  # non ci sono proprio più carte
                self.deck = self.discard_pile
                self.discard_pile = []
                self.rng.shuffle(self.deck)
            drawn.append(self.deck.pop())
        return drawn

    @staticmethod
    def _deal(deck: list, n: int) -> list:
        """Prende n elementi da un mazzo che non si rimescola (corporazioni, preludi)."""
        dealt = deck[-n:] if n else []
        del deck[len(deck) - len(dealt):]
        return dealt

    # ------------------------------------------------------------------
    # Fase delle azioni
    # ------------------------------------------------------------------

    def _legal_action_phase_actions(self) -> list[Action]:
        player = self.current_player
        if not player.first_action_done:
            return self._legal_first_actions(player)

        planet = self.state.planet
        actions: list[Action] = []

        # Passare è possibile solo come prima azione del turno; dopo
        # un'azione si può invece chiudere il turno senza fare la seconda.
        if self.actions_this_turn == 0:
            actions.append(Action(ActionType.PASS))
        else:
            actions.append(Action(ActionType.END_TURN))

        # Calcoliamo una volta sola ciò che serve per valutare tutte le mosse.
        active = player.active_cards()
        rules = self.payment_rules(player, active)
        leeway = self.requirement_leeway(player, active)
        actions += self._playable_card_actions(player, active, rules, leeway)

        corp = player.corporation
        if corp and corp.action_options and corp.name not in player.used_actions:
            for option in corp.action_options(self, player):
                actions.append(Action(ActionType.CARD_ACTION, corp.name, target=option))

        for card in active:
            if card.actions and card.name not in player.used_actions:
                actions.extend(self._card_action_options(player, card, rules))

        if self._can_convert_plants(player):
            actions.append(Action(ActionType.CONVERT_PLANTS))

        if (player.resources[Resource.HEAT] >= HEAT_PER_TEMPERATURE
                and planet.temperature < MAX_TEMPERATURE):
            actions.append(Action(ActionType.CONVERT_HEAT))

        if player.hand:
            actions.append(Action(ActionType.SELL_PATENTS))
        for action_type in STANDARD_PROJECT_COST:
            if (self.can_pay(player, self.standard_project_cost(player, action_type), rules)
                    and self._project_has_effect(action_type)):
                actions.append(Action(action_type))

        # Traguardi: liberi, posti ancora disponibili, condizione raggiunta, soldi.
        claimed = self.state.claimed_milestones
        if len(claimed) < MAX_MILESTONES and self.can_pay(player, MILESTONE_COST, rules):
            for milestone in MILESTONES:
                if milestone.name not in claimed and milestone.is_reached(player):
                    actions.append(Action(ActionType.CLAIM_MILESTONE, target=milestone.name))

        # Riconoscimenti: non ancora finanziati, posti disponibili, soldi.
        award_cost = self.next_award_cost()
        if award_cost is not None and self.can_pay(player, award_cost, rules):
            for award in AWARDS:
                if award.name not in self.state.funded_awards:
                    actions.append(Action(ActionType.FUND_AWARD, target=award.name))

        return actions

    def _playable_card_actions(self, player: Player, active: list[Card], rules: PaymentRules,
                               leeway: int) -> list[Action]:
        """Le carte della mano che si possono giocare adesso (una mossa per modo di pagare)."""
        actions = []
        for card in player.hand:
            cost = self.card_cost(player, card, active)
            microbes = self.payment_microbes(player, card, active)
            card_rules = self.rules_for_card(card, rules)
            if (card.can_be_played(self.state, player, cost, card_rules, leeway, microbes)
                    and self._tiles_placeable(card) and self._attack_possible(card)
                    and self._card_targets_exist(player, card)
                    and self._choices_possible(card)):
                for payment in self._payment_choices(player, card, cost, card_rules, microbes):
                    actions.append(Action(ActionType.PLAY_CARD, card.name, payment=payment))
        return actions

    # --- Giocare subito una carta (Eccentric Sponsor, Ecology Experts) -------------

    def _legal_bonus_play(self) -> list[Action]:
        player = self.current_player
        active = player.active_cards()
        actions = self._playable_card_actions(player, active, self.payment_rules(player, active),
                                              self.requirement_leeway(player, active))
        return actions + [Action(ActionType.SKIP_BONUS_PLAY)]

    def _apply_bonus_play(self, action: Action) -> None:
        self.bonus_play = False
        if action.type is ActionType.PLAY_CARD:
            self._play_card(self.current_player, action.card, action.payment)
        else:
            self._end_bonus_play()
        self._resolve_pending()

    def _end_bonus_play(self) -> None:
        """Se non giochi la carta, lo sconto non resta per la carta dopo."""
        self.bonus_play = False
        player = self.current_player
        player.next_card_discount = player.next_card_leeway = 0

    def _legal_first_actions(self, player: Player) -> list[Action]:
        """L'azione iniziale obbligatoria della corporazione."""
        corp = player.corporation
        if corp.first_action is FirstAction.FUND_AWARD_FREE:
            options = [Action(ActionType.FIRST_ACTION, corp.name, target=a.name)
                       for a in AWARDS if a.name not in self.state.funded_awards]
            if self.next_award_cost() is not None and options:
                return options
        return [Action(ActionType.FIRST_ACTION, corp.name)]

    def next_award_cost(self) -> int | None:
        """Quanto costa finanziare il prossimo riconoscimento (None se finiti)."""
        funded = len(self.state.funded_awards)
        return AWARD_COSTS[funded] if funded < MAX_AWARDS else None

    def _can_convert_plants(self, player: Player) -> bool:
        return (player.resources[Resource.PLANTS] >= self.plants_per_greenery(player)
                and self._can_place(TileType.GREENERY))

    def _project_has_effect(self, action_type: ActionType) -> bool:
        """Non permettiamo progetti che non farebbero nulla.

        Per esempio un asteroide quando la temperatura è già al massimo,
        o una città quando sulla mappa non c'è più posto.
        """
        planet = self.state.planet
        if action_type is ActionType.ASTEROID:
            return planet.temperature < MAX_TEMPERATURE
        if action_type is ActionType.AQUIFER:
            return self.state.oceans_remaining() > 0
        if action_type is ActionType.GREENERY:
            return self._can_place(TileType.GREENERY)
        if action_type is ActionType.CITY:
            return self._can_place(TileType.CITY)
        return True

    def _execute(self, action: Action) -> None:
        """Applica gli effetti di un'azione (già verificata come legale)."""
        player = self.current_player
        state = self.state
        t = action.type

        if t is ActionType.PLAY_CARD:
            self._play_card(player, action.card, action.payment)
        elif t is ActionType.SELL_PATENTS:
            self.selling = True             # le carte si scelgono una alla volta
            self.sold_this_action = 0
        elif t is ActionType.FIRST_ACTION:
            self._first_action(player, action)
        elif t is ActionType.CARD_ACTION:
            player.used_actions.add(action.card)
            if player.corporation and action.card == player.corporation.name:
                player.corporation.perform_action(self, player, action.target)
            else:
                self._use_card_action(player, action)
        elif t is ActionType.CLAIM_MILESTONE:
            self.pay(player, MILESTONE_COST)
            state.claimed_milestones[action.target] = player.name
        elif t is ActionType.FUND_AWARD:
            self.pay(player, self.next_award_cost())
            state.funded_awards.append(action.target)
        elif t is ActionType.CONVERT_PLANTS:
            player.spend(Resource.PLANTS, self.plants_per_greenery(player))
            state.queue_tile(TileType.GREENERY)
        elif t is ActionType.CONVERT_HEAT:
            player.spend(Resource.HEAT, HEAT_PER_TEMPERATURE)
            state.raise_temperature(player, 1)
        elif t in STANDARD_PROJECT_COST:
            self.pay(player, self.standard_project_cost(player, t))
            self._payment_triggers(player, STANDARD_PROJECT_COST[t])
            self._standard_project_triggers(player, t)
            if t is ActionType.POWER_PLANT:
                player.change_production(Resource.ENERGY, 1)
            elif t is ActionType.ASTEROID:
                state.raise_temperature(player, 1)
            elif t is ActionType.AQUIFER:
                state.queue_tile(TileType.OCEAN)
            elif t is ActionType.GREENERY:
                state.queue_tile(TileType.GREENERY)
            elif t is ActionType.CITY:
                # Il +1 di produzione è un effetto del progetto standard,
                # non della tessera città.
                player.change_production(Resource.MEGACREDITS, 1)
                state.queue_tile(TileType.CITY)
        else:
            raise NotImplementedError(f"Azione non ancora implementata: {t}")

    def _first_action(self, player: Player, action: Action) -> None:
        player.first_action_done = True
        first = player.corporation.first_action
        if first is FirstAction.PLACE_CITY:
            self.state.queue_tile(TileType.CITY)
        elif first is FirstAction.DRAW_3_CARDS:
            self.draw_cards(player, 3)
        elif first is FirstAction.FUND_AWARD_FREE and action.target:
            self.state.funded_awards.append(action.target)
        elif first is FirstAction.PLAY_PRELUDE_FROM_3:
            player.prelude_choices = self._deal(self.prelude_deck, VALLEY_TRUST_PRELUDES)

    def _play_card(self, player: Player, card_name: str, payment_choice: str | None = None) -> None:
        """Gioca una carta: paga, sposta in gioco, applica gli effetti.

        Questo è l'unico codice che serve per TUTTE le carte semplici:
        legge i dati della carta e li applica uno per uno.
        """
        card = next(c for c in player.hand if c.name == card_name)

        active = player.active_cards()
        allow_steel, allow_titanium = PAYMENT_CHOICES[payment_choice]
        payment = card.payment_for(player, self.card_cost(player, card, active),
                                   self.rules_for_card(card, self.payment_rules(player, active)),
                                   self.payment_microbes(player, card, active),
                                   allow_steel, allow_titanium)
        self._spend_payment(player, payment, card, active)
        self._payment_triggers(player, card.cost)
        player.next_card_discount = player.next_card_leeway = 0   # valevano solo per questa

        player.hand.remove(card)
        player.played.append(card)
        self._log(player, card, "giocata")
        self.last_placed_space = None
        self._apply_card_effects(player, card)
        self._card_played_triggers(player, card)

    def _apply_card_effects(self, player: Player, card: Card) -> None:
        """Gli effetti "di dati" di una carta o di un preludio."""
        for resource, amount in card.production.items():
            player.change_production(resource, amount)
        for resource, amount in card.resources.items():
            if amount >= 0:
                player.gain(resource, amount)
            else:
                player.spend(resource, -amount)
        if card.temperature_steps:
            self.state.raise_temperature(player, card.temperature_steps)
        if card.oxygen_steps:
            self.state.raise_oxygen(player, card.oxygen_steps)
        if card.terraform_rating:
            player.raise_tr(card.terraform_rating)
        for tile in card.tiles:
            self.state.queue_tile(tile)
        if card.draw_cards and card.keep_cards:
            self.revealed = self._draw(card.draw_cards)     # decisione in attesa: quali tenere
            self.keep_left = card.keep_cards
        elif card.draw_cards:
            self.draw_cards(player, card.draw_cards, card.draw_tag)
        for kind, amount in card.add_to_cards:
            self.pending_choices.append(
                PendingChoice(card, (CardAction(add_to_other_card=(kind, amount)),)))
        if card.choices:
            self.pending_choices.append(PendingChoice(card, card.choices))
        for resource, scaled in card.scaled_production.items():
            player.change_production(resource, self.scaled_amount(player, scaled))
        for resource, scaled in card.scaled_resources.items():
            player.gain(resource, self.scaled_amount(player, scaled))
        if card.scaled_tr:
            player.raise_tr(self.scaled_amount(player, card.scaled_tr))
        if card.next_card_discount:
            player.next_card_discount = card.next_card_discount
        if card.next_card_leeway:
            player.next_card_leeway = card.next_card_leeway
        if card.play_card_now:
            self.bonus_play = True
        if card.starting_resources:
            player.add_card_resource(card.name, card.starting_resources)
        # Gli attacchi si risolvono dopo le tessere (Comet: prima l'oceano, poi le piante).
        if card.remove_any_plants:
            self.pending_attacks.append(("plants", card))
        if card.decrease_any_production:
            self.pending_attacks.append(("production", card))
        if card.raid:
            self.pending_attacks.append(("raid", card))
        if card.flood_raid:
            self.pending_attacks.append(("flood", card))

    # --- Azioni delle carte blu ---------------------------------------------------

    def _card_action_options(self, player: Player, card: Card,
                             rules: PaymentRules | None = None) -> list[Action]:
        """Le mosse possibili con l'azione di una carta blu (già controllato:
        è in gioco e non è stata usata in questa generazione)."""
        rules = rules or self.payment_rules(player)
        result = []
        for index, alternative in enumerate(card.actions):
            if not self._can_use_alternative(player, card, alternative, rules):
                continue
            payments = [None]
            default = self.action_payment(player, alternative, rules)
            if (default and (default.steel or default.titanium)
                    and self.action_payment(player, alternative, rules, PAY_NO_METALS)):
                payments.append(PAY_NO_METALS)
            for option in self._alternative_choices(player, card, alternative):
                for payment in payments:
                    result.append(Action(ActionType.CARD_ACTION, card.name,
                                         target=str(index), option=option, payment=payment))
        return result

    def action_payment(self, player: Player, alternative: CardAction,
                       rules: PaymentRules | None = None,
                       payment_choice: str | None = None) -> Payment | None:
        """Come pagare la parte in M€ di un'azione (anche con metalli, se permesso)."""
        allow_steel, allow_titanium = PAYMENT_CHOICES[payment_choice]
        return pay_with_metals(player, alternative.spend.get(Resource.MEGACREDITS, 0),
                               rules or self.payment_rules(player),
                               use_steel=alternative.can_use_steel and allow_steel,
                               use_titanium=alternative.can_use_titanium and allow_titanium)

    def _can_use_alternative(self, player: Player, card: Card, alternative: CardAction,
                             rules: PaymentRules) -> bool:
        for resource, amount in alternative.spend.items():
            if resource is not Resource.MEGACREDITS and player.resources[resource] < amount:
                return False
        if (Resource.MEGACREDITS in alternative.spend
                and self.action_payment(player, alternative, rules) is None):
            return False
        if player.card_resources.get(card.name, 0) < alternative.spend_here:
            return False
        for resource, amount in alternative.production.items():
            if amount < 0 and not self.can_lose_production(player, resource, -amount):
                return False
        return self._alternative_has_effect(alternative)

    def _alternative_has_effect(self, alternative: CardAction) -> bool:
        """Non permettiamo azioni che non farebbero nulla (come per i progetti
        standard): per esempio pompare un oceano quando sono finiti."""
        a = alternative
        if a.megacredits_per_city_on_mars and self.state.board.cities_on_mars() > 0:
            return True
        if (a.gain or any(n > 0 for n in a.production.values()) or a.terraform_rating
                or a.draw_cards or a.buy_card or a.add_here or a.remove_from_any_card
                or a.add_to_other_card or a.special):
            return True
        planet = self.state.planet
        if a.temperature_steps and planet.temperature < MAX_TEMPERATURE:
            return True
        if a.oxygen_steps and planet.oxygen < MAX_OXYGEN:
            return True
        for tile in a.tiles:
            if tile.tile is TileType.OCEAN:
                if self.state.oceans_remaining() > 0:
                    return True
            elif self._can_place(tile):
                return True
        return False

    def _alternative_choices(self, player: Player, card: Card,
                             alternative: CardAction) -> list[str | None]:
        """Le scelte in più di un'azione. [None] = nessuna scelta; [] = impossibile."""
        if alternative.remove_from_any_card is not None:
            kind = alternative.remove_from_any_card
            choices = []
            for owner in self.state.players:
                for other in owner.played:
                    if (other is not card and other.resource_type is kind
                            and owner.card_resources.get(other.name, 0) > 0
                            and not (other.name == "Pets"
                                     or owner is not player and self.is_protected(owner, kind))):
                        choices.append(f"{owner.name}:{other.name}")
            return choices
        if alternative.add_to_other_card is not None:
            kind, _ = alternative.add_to_other_card
            if kind is None:      # qualsiasi tua carta che ha già almeno una risorsa
                return [c.name for c in player.played
                        if c is not card and player.card_resources.get(c.name, 0) > 0]
            return [c.name for c in player.played if c is not card and c.resource_type is kind]
        if alternative.special:
            return SPECIAL_ACTIONS[alternative.special].options(self, player, card)
        if alternative.buy_card and not (self.deck or self.discard_pile):
            return []
        return [None]

    def _use_card_action(self, player: Player, action: Action) -> None:
        card = next(c for c in player.played if c.name == action.card)
        a = card.actions[int(action.target)]

        # Pagamento
        if Resource.MEGACREDITS in a.spend:
            self._spend_payment(player, self.action_payment(player, a, None, action.payment))
        for resource, amount in a.spend.items():
            if resource is not Resource.MEGACREDITS:
                player.spend(resource, amount)
        self._apply_alternative(player, card, a, action.option)

    def _apply_alternative(self, player: Player, card: Card, a: CardAction,
                           option: str | None) -> None:
        """Gli effetti di un'azione blu o di una scelta (pagamento in M€ escluso)."""
        state = self.state
        if a.spend_here:
            player.add_card_resource(card.name, -a.spend_here)

        # Effetti, nell'ordine in cui sono stampati
        for resource, amount in a.gain.items():
            player.gain(resource, amount)
        if a.megacredits_per_city_on_mars:
            player.gain(Resource.MEGACREDITS,
                        a.megacredits_per_city_on_mars * state.board.cities_on_mars())
        for resource, amount in a.production.items():
            player.change_production(resource, amount)
        if a.temperature_steps:
            state.raise_temperature(player, a.temperature_steps)
        if a.oxygen_steps:
            state.raise_oxygen(player, a.oxygen_steps)
        if a.terraform_rating:
            player.raise_tr(a.terraform_rating)
        for tile in a.tiles:
            state.queue_tile(tile)
        if a.draw_cards:
            self.draw_cards(player, a.draw_cards)
        if a.buy_card:
            player.drafted = self._draw(1)      # decisione in attesa: comprala o scartala
        if a.remove_from_any_card is not None:
            owner_name, _, card_name = option.partition(":")
            owner = next(p for p in state.players if p.name == owner_name)
            owner.add_card_resource(card_name, -1)
        if a.add_here:
            player.add_card_resource(card.name, a.add_here)
        if a.add_to_other_card is not None:
            player.add_card_resource(option, a.add_to_other_card[1])
        if a.special:
            SPECIAL_ACTIONS[a.special].perform(self, player, card, option)

    # --- Scelte in attesa ---------------------------------------------------------

    def _choice_options(self, pending: PendingChoice) -> list[Action]:
        """Le possibilità di una scelta in attesa (alternativa + eventuale carta)."""
        player = self.current_player
        rules = self.payment_rules(player)
        options = []
        for index, alternative in enumerate(pending.alternatives):
            if alternative.is_empty():
                choices: list[str | None] = [None]
            elif not self._can_use_alternative(player, pending.card, alternative, rules):
                continue
            else:
                choices = self._alternative_choices(player, pending.card, alternative)
                if pending.only_target is not None and alternative.add_to_other_card:
                    choices = [c for c in choices if c == pending.only_target]
            options += [Action(ActionType.CHOOSE_EFFECT, pending.card.name, target=str(index),
                               option=choice) for choice in choices]
        return options

    def _perform_choice(self, pending: PendingChoice, action: Action) -> None:
        alternative = pending.alternatives[int(action.target)]
        self._apply_alternative(self.current_player, pending.card, alternative, action.option)

    def _keep_card(self, card_name: str) -> None:
        """Tieni una delle carte guardate; quando hai finito, le altre si scartano."""
        card = next(c for c in self.revealed if c.name == card_name)
        self.revealed.remove(card)
        self.current_player.hand.append(card)
        self.keep_left -= 1
        if self.keep_left <= 0:
            self.discard_pile.extend(self.revealed)
            self.revealed = []

    def scaled_amount(self, player: Player, scaled: Scaled) -> int:
        """Quanto vale adesso una quantità variabile (Satellites: i tuoi tag spazio)."""
        what = scaled.what
        if what == "tag":
            count = player.tag_count(scaled.tag)
        elif what == "tag_others":
            count = sum(p.tag_count(scaled.tag) for p in self.state.players if p is not player)
        elif what == "tag_at_least":
            return scaled.step if player.tag_count(scaled.tag) >= scaled.per else 0
        elif what == "cities":
            count = self.state.board.count_tiles(TileType.CITY)
        elif what == "cities_on_mars":
            count = self.state.board.cities_on_mars()
        elif what == "events":
            count = sum(p.tag_count(Tag.EVENT, wild=False) for p in self.state.players)
        else:
            raise ValueError(f"Quantità sconosciuta: {what}")
        return count // scaled.per * scaled.step

    def _choices_possible(self, card: Card) -> bool:
        """Una carta con scelta si gioca solo se almeno una scelta è possibile
        (Robotic Workforce: serve una tua carta edificio con produzione da copiare)."""
        if not card.choices:
            return True
        return bool(self._choice_options(PendingChoice(card, card.choices)))

    def _card_targets_exist(self, player: Player, card: Card) -> bool:
        """CEO's Favorite Project si gioca solo se hai una carta con risorse sopra."""
        for kind, _ in card.add_to_cards:
            if kind is None and not any(player.card_resources.get(c.name, 0) > 0
                                        for c in player.played):
                return False
        return True

    # --- I momenti in cui scattano i poteri di corporazioni e carte blu ---------

    def _card_triggers(self, player: Player):
        """(carta blu, suoi trigger) per le carte blu del giocatore che ne hanno."""
        return [(card, CARD_TRIGGERS[card.name]) for card in player.active_cards()
                if card.name in CARD_TRIGGERS]

    def _card_played_triggers(self, player: Player, card: Card) -> None:
        for owner, corp in self._corporation_triggers():
            if owner is player and corp.on_card_played:
                self._triggered(owner, corp.name, corp.on_card_played, owner, card)
            if corp.on_any_card_played:
                self._triggered(owner, corp.name, corp.on_any_card_played, owner, player, card)
        # Le carte blu reagiscono solo alle carte giocate dal loro proprietario.
        # La carta appena giocata è già in gioco: così vale "compresa questa".
        for blue, triggers in self._card_triggers(player):
            if triggers.on_card_played:
                self._triggered(player, blue.name, triggers.on_card_played, player, card, blue)

    def _payment_triggers(self, player: Player, base_cost: int) -> None:
        corp = player.corporation
        if corp and corp.on_payment:
            self._triggered(player, corp.name, corp.on_payment, player, base_cost)

    def _standard_project_triggers(self, player: Player, project: ActionType) -> None:
        for blue, triggers in self._card_triggers(player):
            if triggers.on_standard_project:
                self._triggered(player, blue.name, triggers.on_standard_project, player, project, blue)

    def _tile_placed_triggers(self, player: Player, space: Space, tile: TileType) -> None:
        for owner, corp in self._corporation_triggers():
            if corp.on_tile_placed:
                self._triggered(owner, corp.name, corp.on_tile_placed, owner, player, space, tile)
        for owner in self.state.players:
            for blue, triggers in self._card_triggers(owner):
                if triggers.on_tile_placed:
                    self._triggered(owner, blue.name, triggers.on_tile_placed,
                                    owner, player, space, tile, blue)

    def _triggered(self, owner: Player, source: str, effect, *args) -> None:
        """Fa scattare un effetto; se qualcuno guarda (play.py), dice cosa ha dato."""
        if self.messages is None:
            effect(self, *args)
            return
        before = (dict(owner.resources), dict(owner.production), dict(owner.card_resources))
        effect(self, *args)
        changes = []
        for resource, amount in owner.resources.items():
            if amount != before[0][resource]:
                changes.append(f"{amount - before[0][resource]:+d} {resource.value}")
        for resource, amount in owner.production.items():
            if amount != before[1][resource]:
                changes.append(f"{amount - before[1][resource]:+d} produzione di {resource.value}")
        for name, amount in owner.card_resources.items():
            if amount != before[2].get(name, 0):
                changes.append(f"{amount - before[2].get(name, 0):+d} risorse su {name}")
        if changes:
            self.messages.append(f"{owner.name} – {source}: {', '.join(changes)}")

    def _next_turn(self) -> None:
        """Passa al prossimo giocatore che non ha passato."""
        self.actions_this_turn = 0
        n = len(self.state.players)

        if len(self.passed) == n:
            self._end_generation()
            return

        index = self.current
        while True:
            index = (index + 1) % n
            if index not in self.passed:
                break
        self.current = index

    # ------------------------------------------------------------------
    # Fine generazione e fine partita
    # ------------------------------------------------------------------

    def _end_generation(self) -> None:
        self.state.end_generation()

        if (self.state.planet.is_terraformed()
                or self.state.generation > MAX_GENERATIONS):
            self._start_final_greenery()
            return

        # Nuova generazione: tutti di nuovo in gioco, il primo giocatore ruota.
        self.passed.clear()
        self.first_player = (self.first_player + 1) % len(self.state.players)
        self._start_research()

    def _start_final_greenery(self) -> None:
        """Ultima fase: a turno, a partire dal primo giocatore, ognuno può
        trasformare le piante rimaste in foreste (e sceglie dove metterle)."""
        self.phase = Phase.FINAL_GREENERY
        n = len(self.state.players)
        self.final_queue = [(self.first_player + i) % n for i in range(n)]
        self._advance_final()

    def _legal_final_actions(self) -> list[Action]:
        actions = [Action(ActionType.PASS)]
        if self._can_convert_plants(self.current_player):
            actions.append(Action(ActionType.CONVERT_PLANTS))
        return actions

    def _advance_final(self) -> None:
        """Salta chi non può più convertire; quando non resta nessuno, fine."""
        while self.final_queue and not self._can_convert_plants(
                self.state.players[self.final_queue[0]]):
            self.final_queue.pop(0)
        if self.final_queue:
            self.current = self.final_queue[0]
        else:
            self.finished = True
