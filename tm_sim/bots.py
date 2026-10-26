"""I giocatori automatici.

Ogni bot ha un solo metodo: choose(game, actions), che riceve la partita
e la lista delle azioni legali e ne restituisce una. Tutti i futuri
giocatori (bot a regole, IA con MCTS, rete neurale, perfino tu dal
terminale) rispetteranno questa stessa forma: così sono intercambiabili.
"""

import json
import random
from pathlib import Path

from tm_sim import heuristics as h
from tm_sim.actions import CARD_PRICE, HEAT_PER_TEMPERATURE, STANDARD_PROJECT_COST, Action, ActionType
from tm_sim.board import TileType
from tm_sim.card_data import PRELUDE_CARDS
from tm_sim.card_list import CARDS_BY_NAME
from tm_sim.corporations import CORPORATIONS_BY_NAME
from tm_sim.game import UNPLAYABLE_PRELUDE_BONUS, Game
from tm_sim.milestones import MILESTONE_COST, MILESTONE_POINTS
from tm_sim.cards import CardType
from tm_sim.state import Player, Resource

PRELUDES_BY_NAME = {p.name: p for p in PRELUDE_CARDS}


def load_corrections(path: str | Path) -> dict[str, float]:
    """Le correzioni salvate da learn.py (file JSON)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {name: float(v) for name, v in data["correzioni"].items()}


def load_pairs(path: str | Path) -> dict[str, float]:
    """Le accoppiate imparate da learn.py (le tue lezioni verificate): "A + B" -> PV."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {name: float(v) for name, v in data.get("coppie", {}).items()}


def corrections_potential_weight(path: str | Path) -> float | None:
    """Con quale peso del potenziale sono state imparate (None = file vecchio, quindi 0)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data.get("potential_weight")


class Bot:
    """Classe base: definisce la forma che ogni bot deve avere."""

    name = "bot"

    def choose(self, game: Game, actions: list[Action]) -> Action:
        raise NotImplementedError


class RandomBot(Bot):
    """Sceglie un'azione legale a caso.

    È il bot più stupido possibile, ma è utilissimo per due motivi:
    1. fa da tester: gioca migliaia di partite provando di tutto, e se
       il motore ha un bug prima o poi ci inciampa;
    2. fa da riferimento: qualunque IA seria deve batterlo quasi sempre.
    """

    name = "casuale"

    def __init__(self, seed: int | None = None):
        # Un generatore di numeri casuali tutto suo. Con lo stesso seed
        # il bot farà sempre le stesse scelte: utile per riprodurre un bug.
        self.rng = random.Random(seed)

    def choose(self, game: Game, actions: list[Action]) -> Action:
        return self.rng.choice(actions)


class RuleBot(Bot):
    """Un giocatore che segue regole di buon senso.

    Per ogni mossa legale calcola un punteggio in M€ ("quanto mi conviene?")
    usando le stime di heuristics.py, e sceglie la mossa migliore.
    Passare vale 0: se nessuna mossa rende più di quanto costa, passa.

    Le regole, in breve:
    - gioca la carta che rende di più rispetto al suo costo;
    - trasforma sempre piante e calore appena può (è guadagno gratis);
    - reclama un traguardo appena può (5 PV per 8 M€, e gli altri lo vogliono);
    - corsa ai traguardi: premia le mosse che lo avvicinano a un traguardo
      libero, di più se un rivale è vicino (i suoi 5 PV mancati valgono anche per me);
    - finanzia un riconoscimento solo verso la fine e solo se è in testa;
    - compra una carta solo se vale più di quanto costa (prezzo + 3 M€);
    - piazza le tessere dove prende più bonus, foreste vicino alle sue città,
      città vicino a foreste e spazi liberi;
    - attacca il bersaglio con l'indice di sensatezza più alto: danno reale
      (quello che può davvero togliere) × quanto il bersaglio è messo bene;
    - usa le azioni delle carte blu quando ciò che danno vale più di ciò che
      costano (e toglie animali e microbi al giocatore messo meglio);
    - paga con acciaio e titanio, tranne quando a fine partita gli servono per
      vincere Miner (lo stesso per il calore e Thermalist);
    - vende brevetti se le carte inutili gli permettono di giocare subito una
      carta forte, e all'ultima generazione vende tutto ciò che non giocherà
      (in caso di parità di punti vince chi ha più M€);
    - nelle carte con scelta prende l'alternativa che vale di più, e mette
      animali e microbi sulla carta dove valgono più punti;
    - aspetta a giocare le carte che mettono risorse su altre carte se in mano
      ha un buon bersaglio non ancora giocato (combo_patience), un po' meno se
      spera solo di pescarne uno (combo_hope);
    - tiene in mano le carte "di potenziale" (Satellites, Insects...) finché
      giocarle più avanti, con più tag, rende chiaramente di più
      (potential_patience);
    - se gli si danno le correzioni imparate dalle simulazioni (card_power),
      corregge le sue stime carta per carta (vedi learn.py);
    - su richiesta (potential_weight=0.4) valuta ogni carta 60% per quanto dà
      davvero e 40% per il suo POTENZIALE, cioè quanto può dare se ci costruisci intorno;
    - decide gli acquisti guardando TUTTE le carte offerte insieme (joint_buying):
      sinergie tra loro, soldi disponibili, mano troppo piena (su richiesta,
      setup_package, sceglie anche la corporazione pensando a preludi e carte).
    """

    name = "regole"

    # Priorità alte per le mosse che conviene fare sempre e subito.
    ALWAYS_GOOD = 100.0
    # Penalità per non riempirsi la mano di carte che non si riusciranno a giocare.
    HAND_LIMIT = 8
    HAND_PENALTY = 1.5

    def __init__(self, seed: int | None = None, milestone_race: bool = True,
                 random_corporation: bool = False, sell_patents: bool = True,
                 smart_payment: bool = True, combo_patience: float = h.COMBO_PATIENCE,
                 combo_hope: float = h.COMBO_HOPE,
                 potential_patience: float = h.POTENTIAL_PATIENCE,
                 card_power: dict[str, float] | str | None = None, power_weight: float = 1.0,
                 potential_weight: float | None = None, joint_buying: bool = True,
                 setup_package: bool = False, pair_power: dict[str, float] | None = None):
        # Il caso serve solo a scegliere tra mosse con lo stesso punteggio.
        self.rng = random.Random(seed)
        # Si può spegnere la corsa ai traguardi per misurare quanto aiuta.
        self.milestone_race = milestone_race
        # Per le statistiche sulle corporazioni: sceglierle a caso, così
        # ognuna viene giocata lo stesso numero di volte e nelle stesse
        # condizioni (vedi simulate.py).
        self.random_corporation = random_corporation
        # Si possono spegnere vendita di brevetti e scelta del pagamento
        # (metalli e calore tenuti per i riconoscimenti), per i test A/B.
        self.sell_patents = sell_patents
        self.smart_payment = smart_payment
        # Quanto aspettare a giocare le carte che mettono risorse su altre carte
        # (Imported Nitrogen...): con un bersaglio in mano (Fish) e senza.
        # 0 = non aspettare mai. Vedi heuristics.combo_wait_value.
        self.combo_patience = combo_patience
        self.combo_hope = combo_hope
        # Quanto aspettare a giocare le carte "di potenziale" (Satellites...),
        # che rendono di più quando avrai più tag. 0 = giocarle appena conviene.
        self.potential_patience = potential_patience
        # Correzioni imparate dalle simulazioni (learn.py): per ogni carta, preludio
        # o corporazione, quanti PV rende in più (o in meno) di quanto il bot stima.
        # Si può passare il dizionario o il nome del file JSON salvato da learn.py.
        file_weight = None
        if isinstance(card_power, (str, Path)):
            file_weight = corrections_potential_weight(card_power)
            if pair_power is None:
                pair_power = load_pairs(card_power)
            card_power = load_corrections(card_power)
        self.corrections: dict[str, float] = card_power or {}
        # Accoppiate (tm_sim/teaching.py): "A + B" -> PV in più se giocate insieme.
        # Per ogni nome, le sue compagne: così il calcolo resta veloce.
        self.pairs: dict[str, list[tuple[str, float]]] = {}
        for key, value in (pair_power or {}).items():
            a, _, b = key.partition(" + ")
            if value:
                self.pairs.setdefault(a, []).append((b, value))
                self.pairs.setdefault(b, []).append((a, value))
        self.power_weight = power_weight
        # Peso del POTENZIALE nel valore delle carte: 0,4 = 60% valore effettivo +
        # 40% "quanto può dare se sfruttata bene" (vedi heuristics.Outlook).
        # Predefinito 0 = solo il valore effettivo: misurato, dare peso al potenziale
        # senza correzioni rende il bot più debole (vedi heuristics.py).
        # Se le correzioni vengono da un file imparato con un certo peso (learn.py
        # --potenziale), il bot usa quel peso: correzioni e peso vanno insieme.
        if potential_weight is None:
            potential_weight = file_weight if file_weight is not None else h.POTENTIAL_WEIGHT
        self.potential_weight = potential_weight
        # Acquisti decisi guardando tutte le carte offerte insieme (False = come
        # prima: una carta alla volta, nell'ordine in cui arrivano). Vedi buy_plan.
        self.joint_buying = joint_buying
        # Scegliere la corporazione pensando anche a preludi e 10 carte (pacchetto).
        # Misurato (3000 partite a specchio): -0,23 ± 0,37 punti, cioè non aiuta
        # ancora (le stime del pacchetto sono rumorose). Spento, resta come opzione.
        self.setup_package = setup_package
        self._plans: dict[tuple, tuple] = {}

    def choose(self, game: Game, actions: list[Action]) -> Action:
        player = game.current_player
        if actions[0].type is ActionType.BUY_CARDS:
            # Le carte pescate si comprano tutte insieme: il bot decide il gruppo
            # (buy_plan) invece di dare un punteggio a ognuna delle combinazioni.
            plan = self.buy_plan(game, player)
            for action in actions:
                if set(action.cards) == plan:
                    return action
        best = max(actions, key=lambda a: (self.score(game, player, a), self.rng.random()))
        return best

    # ------------------------------------------------------------------

    def correction(self, game: Game, name: str, player: Player | None = None,
                   extra: tuple | list = ()) -> float:
        """La correzione imparata per questa carta, in M€ (0 se non ne abbiamo),
        più il bonus delle accoppiate se si dice di quale giocatore (vedi pair_bonus)."""
        value = 0.0
        if self.corrections:
            value = self.power_weight * self.corrections.get(name, 0.0) * h.vp_value(game)
        if player is not None and name in self.pairs:
            value += self.pair_bonus(game, player, name, extra)
        return value

    def pair_bonus(self, game: Game, player: Player, name: str, extra: tuple | list = ()) -> float:
        """Bonus delle accoppiate di questa carta, in M€.

        Conta per intero se l'altra metà è già giocata (o è la tua corporazione, o un
        tuo preludio): la sinergia si realizza giocando questa. Per metà se l'altra metà
        è solo in mano o tra le carte che stai valutando insieme (`extra`): forse le
        giocherai entrambe, e il merito si divide tra le due."""
        links = self.pairs.get(name)
        if not links:
            return 0.0
        full = {c.name for c in player.played} | {c.name for c in player.preludes}
        if player.corporation is not None:
            full.add(player.corporation.name)
        half = {c.name for c in player.hand} | set(extra)
        total = 0.0
        for partner, value in links:
            if partner in full:
                total += value
            elif partner in half:
                total += 0.5 * value
        return self.power_weight * total * h.vp_value(game)

    @staticmethod
    def base_estimate(game: Game, player: Player, card=None, corporation=None,
                      weight: float = 0.0) -> float:
        """Quanti PV le regole di base si aspettano da una carta (o corporazione)
        presa adesso, al netto del costo. SENZA le correzioni imparate.

        Serve a learn.py: confronta ciò che le regole si aspettavano con ciò che è
        successo davvero, e da lì calcola le correzioni. weight = peso del potenziale
        con cui giocano i bot (0 = solo valore effettivo): le correzioni impareranno
        quanto di quel valore, potenziale compreso, si realizza davvero.
        """
        with h.potential_weight(weight):
            if corporation is not None:
                value = h.corporation_value(game, corporation)
            elif card.type is CardType.PRELUDE:
                value = h.card_value(game, player, card)
            else:
                value = h.card_net_value(game, player, card)
        return value / h.vp_value(game)

    # ------------------------------------------------------------------
    # Acquisti decisi guardando tutte le carte insieme
    # ------------------------------------------------------------------
    # Le carte pescate (10 all'inizio, 4 a ogni generazione) si guardano TUTTE
    # e si decide in un colpo solo quali comprare (mossa "compra" del motore).
    # Il bot sceglie il gruppo così (buy_plan / plan_purchase):
    # - le carte si valutano INSIEME: Fish vale di più se compri anche Imported
    #   Nitrogen, una carta Giove vale di più con altre carte Giove...;
    # - se i soldi non bastano per tutte, restano fuori le peggiori, non le ultime;
    # - il valore dei soldi tiene conto di quanto resterà dopo gli acquisti.

    PLAN_PASSES = 3      # ricalcoli del gruppo (di solito si stabilizza al secondo)

    def _hypothetical(self, game: Game, player: Player) -> tuple[Game, Player]:
        """Una copia della partita su cui provare "e se avessi queste carte in mano?".
        La mappa è condivisa con l'originale (non si piazzano tessere): molto più veloce."""
        sim = game.clone(share_board=True)
        return sim, sim.state.players[game.state.players.index(player)]

    def _purchase_value(self, sim: Game, me: Player, card, others: list, money: int) -> float:
        """Valore di comprare `card` se in mano ci fossero anche `others` e avessi `money` M€."""
        me.hand = self._base_hand + [c for c in others if c is not card]
        me.resources[Resource.MEGACREDITS] = money
        sim.move_count += 1          # le memorie dei calcoli non devono confondere i casi
        return h.buy_value(sim, me, card) + self.correction(sim, card.name, me)

    def plan_purchase(self, sim: Game, me: Player, offered: list) -> tuple[list, float]:
        """Quali carte comprare tra `offered` (e il valore totale del gruppo).

        1. valuta ogni carta come se in mano ci fossero anche tutte le altre offerte;
        2. le ordina e tiene le migliori finché convengono (soldi e mano piena);
        3. rivaluta con il solo gruppo scelto e ripete finché la scelta non cambia.
        `sim` è una copia della partita: viene modificata."""
        self._base_hand = list(me.hand)
        money = me.resources[Resource.MEGACREDITS]
        affordable = money // CARD_PRICE
        context = list(offered)
        chosen: list = []
        total = 0.0
        with h.potential_weight(self.potential_weight):
            for _ in range(self.PLAN_PASSES):
                spend = CARD_PRICE * min(len(context), affordable)
                values = {c.name: self._purchase_value(sim, me, c, context, money - spend)
                          for c in offered}
                ranked = sorted(offered, key=lambda c: values[c.name], reverse=True)
                new, total = [], 0.0
                for card in ranked[:affordable]:
                    crowded = max(0, len(self._base_hand) + len(new) - self.HAND_LIMIT)
                    gain = values[card.name] - crowded * self.HAND_PENALTY
                    if gain <= 0:
                        break
                    new.append(card)
                    total += gain
                if new == chosen:
                    break
                chosen = context = new
        return chosen, total

    def buy_plan(self, game: Game, player: Player) -> set[str]:
        """Le carte da comprare tra quelle pescate, decise tutte insieme."""
        key = (game.uid, game.move_count, player.name, "buy")
        plan = self._plans.get(key)
        if plan is None:
            sim, me = self._hypothetical(game, player)
            if self.joint_buying:
                chosen, _ = self.plan_purchase(sim, me, list(me.drafted))
            else:
                chosen = self.plan_one_by_one(sim, me, list(me.drafted))
            plan = {c.name for c in chosen}
            if len(self._plans) > 500:
                self._plans.clear()
            self._plans[key] = plan
        return plan

    def plan_one_by_one(self, sim: Game, me: Player, offered: list) -> list:
        """Il vecchio metodo (joint_buying=False, per i test A/B): una carta alla
        volta, nell'ordine in cui sono arrivate, guardando solo la mano attuale."""
        chosen = []
        with h.potential_weight(self.potential_weight):
            for card in offered:
                if me.resources[Resource.MEGACREDITS] < CARD_PRICE:
                    break
                sim.move_count += 1
                crowded = max(0, len(me.hand) - self.HAND_LIMIT) * self.HAND_PENALTY
                if h.buy_value(sim, me, card) - crowded + self.correction(sim, card.name, me) > 0:
                    chosen.append(card)
                    me.hand.append(card)
                    me.resources[Resource.MEGACREDITS] -= CARD_PRICE
        return chosen

    def draft_value(self, game: Game, player: Player, card) -> float:
        """Draft: valore della carta insieme a quelle già scelte nei giri precedenti."""
        key = (game.uid, game.move_count, player.name, "draft")
        cached = self._plans.get(key)
        if cached is None:
            sim, me = self._hypothetical(game, player)
            self._base_hand = list(me.hand)
            cached = (sim, me, list(me.drafted))
            if len(self._plans) > 500:
                self._plans.clear()
            self._plans[key] = cached
        sim, me, picked = cached
        self._base_hand = list(player.hand)
        money = player.resources[Resource.MEGACREDITS] - CARD_PRICE * len(picked)
        with h.potential_weight(self.potential_weight):
            return self._purchase_value(sim, me, card, picked, max(0, money))

    def setup_package_value(self, game: Game, player: Player, corporation) -> float:
        """Inizio partita: quanto valgono preludi e carte iniziali SE prendo questa
        corporazione (sconti, tag, soldi di partenza cambiano cosa conviene)."""
        sim, me = self._hypothetical(game, player)
        hand = list(me.hand)
        me.corporation_choices = []
        sim._start_corporation(me, corporation)
        me.hand = hand                    # le carte pescate dal potere non si conoscono ancora
        # I soldi di partenza sono già contati nel valore della corporazione: qui non
        # devono far sembrare le carte "più economiche" (sopra i 40 M€ il bot dà meno
        # valore ai soldi, regola pensata per la fine partita). Così il pacchetto misura
        # solo come la corporazione cambia preludi e carte (sconti, tag, produzioni).
        me.resources[Resource.MEGACREDITS] = min(me.resources[Resource.MEGACREDITS],
                                                 h.COMFORTABLE_MONEY)
        value = 0.0
        if me.prelude_choices:
            with h.potential_weight(self.potential_weight):
                offered = [c.name for c in me.drafted]
                preludes = sorted((h.card_value(sim, me, p) + self.correction(sim, p.name, me, offered)
                                   for p in me.prelude_choices), reverse=True)
            value += sum(preludes[:2])
        _, cards = self.plan_purchase(sim, me, list(me.drafted))
        return value + cards

    def score(self, game: Game, player: Player, action: Action) -> float:
        """Punteggio della mossa = suo valore + bonus della corsa ai traguardi."""
        if not self.milestone_race:
            return self.base_score(game, player, action)
        deltas = self.milestone_deltas(game, action)
        race = h.milestone_race_value(game, player, deltas) if deltas else 0.0
        return self.base_score(game, player, action) + race

    def milestone_deltas(self, game: Game, action: Action) -> dict[str, int] | None:
        """Di quanto la mossa avanza ciò che contano i traguardi (None = per niente)."""
        t = action.type
        if t is ActionType.PLAY_CARD:
            return h.card_metric_deltas(game, CARDS_BY_NAME[action.card])
        # Niente bonus per comprare carte verso Planner: misurato con un test A/B,
        # il bot comprava carte inutili solo per tenerle in mano, e non vinceva di più.
        if t in (ActionType.CONVERT_PLANTS, ActionType.GREENERY):
            return h.tile_metric_deltas(game, TileType.GREENERY)
        if t is ActionType.AQUIFER:
            return h.tile_metric_deltas(game, TileType.OCEAN)
        if t is ActionType.CITY:
            return h.tile_metric_deltas(game, TileType.CITY)
        if t in (ActionType.ASTEROID, ActionType.CONVERT_HEAT):
            return {"tr": 1}
        if t is ActionType.CARD_ACTION and action.card in CARDS_BY_NAME:
            alternative = CARDS_BY_NAME[action.card].actions[int(action.target)]
            tr = alternative.terraform_rating + alternative.temperature_steps + alternative.oxygen_steps
            tr += sum(1 for tile in alternative.tiles if tile.tile is TileType.OCEAN)
            return {"tr": tr} if tr else None
        return None

    def base_score(self, game: Game, player: Player, action: Action) -> float:
        """Quanto vale la mossa (in M€), con il peso del potenziale di questo bot."""
        with h.potential_weight(self.potential_weight):
            return self._base_score(game, player, action)

    def _base_score(self, game: Game, player: Player, action: Action) -> float:
        t = action.type

        if t in (ActionType.PASS, ActionType.END_TURN, ActionType.SKIP_CARD,
                 ActionType.STOP_SELLING):
            return 0.0

        if t is ActionType.SELL_PATENTS:
            plan = h.sell_plan(game, player) if self.sell_patents else None
            return plan[1] if plan else -1.0
        if t is ActionType.SELL_CARD:
            # Si ricalcola il piano a ogni carta: vende solo quelle previste.
            plan = h.sell_plan(game, player)
            return 1.0 if plan and action.card in plan[0] else -1.0

        if t is ActionType.PLACE_TILE:
            space = game.state.board.spaces[action.space]
            return h.space_value(game, player, game.pending_tile, space)

        if t is ActionType.CHOOSE_CORPORATION:
            if self.random_corporation:
                return self.rng.random()
            corporation = CORPORATIONS_BY_NAME[action.card]
            offered = [c.name for c in player.drafted] + [c.name for c in player.prelude_choices]
            value = (h.corporation_value(game, corporation)
                     + self.correction(game, action.card, player, offered))
            if self.setup_package:
                value += self.setup_package_value(game, player, corporation)
            return value

        if t in (ActionType.KEEP_PRELUDE, ActionType.PLAY_PRELUDE):
            offered = [c.name for c in player.drafted]
            return (h.card_value(game, player, PRELUDES_BY_NAME[action.card])
                    + self.correction(game, action.card, player, offered))
        if t is ActionType.DISCARD_PRELUDE:
            return float(UNPLAYABLE_PRELUDE_BONUS)

        if t is ActionType.DRAFT_CARD:
            # Nel draft si tiene la carta che conviene di più comprare (le altre passano).
            card = CARDS_BY_NAME[action.card]
            if self.joint_buying:       # insieme a quelle già scelte nei giri precedenti
                return self.draft_value(game, player, card)
            picked = [c.name for c in player.drafted]
            return h.buy_value(game, player, card) + self.correction(game, card.name, player, picked)

        if t is ActionType.BUY_CARDS:
            # Quanto il gruppo si discosta da quello deciso (0 = è proprio quello).
            plan = self.buy_plan(game, player)
            return -float(len(plan.symmetric_difference(action.cards)))

        if t is ActionType.BUY_CARD:        # durante un'azione (Business Network): una carta
            card = CARDS_BY_NAME[action.card]
            crowded = max(0, len(player.hand) - self.HAND_LIMIT) * self.HAND_PENALTY
            return h.buy_value(game, player, card) - crowded + self.correction(game, card.name, player)

        if t is ActionType.PLAY_CARD:
            card = CARDS_BY_NAME[action.card]
            bonus = self.correction(game, card.name, player)
            wait = h.combo_wait_value(game, player, card, self.combo_patience, self.combo_hope)
            wait += self.potential_patience * h.potential_gain(game, player, card)
            if not self.smart_payment:      # come prima: paga sempre con i metalli
                if action.payment is not None:
                    return -100.0
                return h.card_net_value(game, player, card) - wait + bonus
            return h.card_play_value(game, player, card, action.payment) - wait + bonus

        if t is ActionType.CHOOSE_EFFECT:
            pending = game.pending_choices[0]
            alternative = pending.alternatives[int(action.target)]
            if alternative.is_empty():
                return 0.0
            return h.card_action_value(game, player, pending.card, alternative, action.option)
        if t is ActionType.SKIP_BONUS_PLAY:
            return 0.0
        if t is ActionType.KEEP_CARD:
            card = CARDS_BY_NAME[action.card]
            return (h.buy_value(game, player, card) + CARD_PRICE * h.money_value(game, player)
                    + self.correction(game, card.name, player))

        if t is ActionType.CONVERT_PLANTS:
            return self.ALWAYS_GOOD
        if t is ActionType.CONVERT_HEAT:
            # Di solito sempre; ma se 8 calore in meno mi fanno perdere Thermalist, conto.
            if not self.smart_payment:
                return self.ALWAYS_GOOD
            loss = h.award_loss(game, player, {Resource.HEAT: HEAT_PER_TEMPERATURE})
            return self.ALWAYS_GOOD if loss == 0 else h.tr_value(game) - loss

        money = h.money_value(game, player)

        if t in STANDARD_PROJECT_COST:
            return (h.standard_project_value(game, player, t)
                    - game.standard_project_cost(player, t) * money)

        if t is ActionType.CLAIM_MILESTONE:
            return self.ALWAYS_GOOD + MILESTONE_POINTS * h.vp_value(game) - MILESTONE_COST * money

        if t is ActionType.FUND_AWARD:
            return self.award_score(game, player, action.target, game.next_award_cost())

        if t is ActionType.FIRST_ACTION:
            # Vitor: sceglie il riconoscimento in cui è più avanti.
            return h.award_lead(game, player, action.target) if action.target else 0.0

        if t is ActionType.CARD_ACTION:
            if player.corporation and action.card == player.corporation.name:
                return self.corporation_action_score(game, player, action)
            card = CARDS_BY_NAME[action.card]
            alternative = card.actions[int(action.target)]
            return h.card_action_value(game, player, card, alternative, action.option,
                                       action.payment)

        if t is ActionType.ATTACK:
            kind, card = game.pending_attacks[0]
            target = next((p for p in game.state.players if p.name == action.target), None)
            return h.attack_target_score(game, player, kind, card, target, action.option)

        return 0.0

    def award_score(self, game: Game, player: Player, award: str, cost: int) -> float:
        """Finanziare conviene solo verso la fine e solo se si è in testa."""
        lead = h.award_lead(game, player, award)
        if lead <= 0 or h.generations_left(game) > 5:
            return -10.0
        chance_to_win = min(1.0, 0.4 + 0.15 * lead)
        return 5 * h.vp_value(game) * chance_to_win - cost * h.money_value(game, player)

    def corporation_action_score(self, game: Game, player: Player, action: Action) -> float:
        money = h.money_value(game, player)
        if action.card == "United Nations Mars Initiative":
            return h.tr_value(game) - 3 * money
        if action.card == "Robinson Industries":
            return h.production_value(game, player, Resource(action.target)) - 4 * money
        return 0.0
