"""Un bot che "pensa avanti": Monte Carlo Tree Search (MCTS), versione pratica.

L'IDEA
Il bot a regole sceglie la mossa che SEMBRA migliore secondo le sue stime.
MCTSBot invece le PROVA: per ogni mossa candidata gioca il seguito della
partita in tante simulazioni veloci, e sceglie quella che in media va meglio.
Così si accorge di cose che le regole non vedono (per esempio che una carta
fa finire prima la generazione, o che lascia all'avversario una mossa buona).

COME FUNZIONA UNA DECISIONE
1. Candidate: le `candidates` mosse migliori secondo il bot a regole (provarle
   tutte costerebbe troppo, e quelle pessime non serve provarle).
2. Simulazioni: a turno (con la regola UCB, vedi sotto) prende una candidata e:
   a) copia la partita (Game.clone);
   b) DETERMINIZZA: rimescola tutto ciò che il bot non può vedere (mazzo e
      carte in mano agli avversari): niente trucchi, gioca "con carte plausibili";
   c) fa la mossa e gioca il seguito con il bot a regole per TUTTI i giocatori,
      fino alla fine della generazione (simulare tutta la partita costerebbe troppo);
   d) VALUTA la posizione: i miei punti stimati meno quelli dell'avversario
      più forte (punti attuali + risorse, produzioni, TR e carte in mano, con le
      stesse stime del bot a regole, convertite in punti).
3. Sceglie la candidata con la media più alta.

CONFRONTO ALLA PARI (numeri casuali comuni)
Ogni simulazione rimescola le carte nascoste in modo diverso: una mossa potrebbe
sembrare migliore solo perché le sono toccate carte fortunate. Per questo tutte le
candidate vengono provate sugli STESSI rimescolamenti (come le partite a specchio
dei test A/B): la differenza tra le medie dipende dalle mosse, non dalla fortuna.

SIMULAZIONI DOVE SERVONO (prior e scarto progressivo)
Il bot a regole, che ha imparato da centinaia di migliaia di partite, dà già
un'idea di quanto vale ogni mossa (il "prior", come l'intuito di un giocatore
esperto). Invece di dare a tutte le candidate lo stesso numero di simulazioni:
- al primo giro le mosse stimate forti ricevono più simulazioni di quelle stimate
  scarse (in proporzione a exp(-distacco / prior_temperature));
- dopo ogni giro le candidate CHIARAMENTE peggiori della migliore (confrontate
  sugli stessi rimescolamenti, con un margine statistico) vengono scartate;
- le simulazioni risparmiate vanno a quelle ancora in gara;
- appena ne resta una sola, o quelle rimaste sono "praticamente uguali" (differenza
  sicuramente sotto `equivalence` punti), la ricerca si ferma.
Così le decisioni ovvie costano poche simulazioni e quelle difficili ne ricevono
di più. È un'opzione (smart=True): MISURATO faccia a faccia contro la divisione in
parti uguali (200 partite a specchio), -0,58 ± 1,55 punti, cioè nessun vantaggio;
per questo il predefinito resta la divisione in parti uguali.

Il bot pensa solo alle decisioni importanti della fase azioni; le scelte minori
(dove piazzare una tessera, chi attaccare, cosa comprare) le lascia al bot a regole.
"""

from __future__ import annotations

import math
import random
import statistics

from tm_sim import heuristics as h
from tm_sim.actions import Action
from tm_sim.bots import Bot, RuleBot
from tm_sim.game import Game, Phase
from tm_sim.state import Player, Resource

HAND_CARD_VALUE = 3.0     # una carta in mano vale circa quanto costa comprarla (M€)


def evaluate(game: Game, player: Player) -> float:
    """Quanto è messo bene `player` rispetto all'avversario più forte, in punti.

    Per ognuno: punti attuali + (risorse, produzioni, TR futuro, carte in mano)
    convertiti in punti. Se la partita è finita contano solo i punti veri.
    """
    def strength(p: Player) -> float:
        points = game.score(p)
        if game.is_over():
            return points + p.resources[Resource.MEGACREDITS] * 0.001   # spareggio sui M€
        money = 0.0
        for resource in Resource:
            money += p.resources[resource] * h.resource_value(game, p, resource)
            money += p.production[resource] * h.production_value(game, p, resource)
        money += p.terraform_rating * h.generations_left(game)          # reddito futuro del TR
        money += len(p.hand) * HAND_CARD_VALUE
        return points + money / h.vp_value(game)

    mine = strength(player)
    others = [strength(p) for p in game.state.players if p is not player]
    return mine - max(others)


def determinize(game: Game, me: Player, rng: random.Random) -> None:
    """Rimescola le informazioni nascoste per `me`: il mazzo e le carte che gli
    avversari hanno in mano (o stanno scegliendo). Ognuno tiene lo stesso numero di carte."""
    opponents = [p for p in game.state.players if p is not me]
    pool = list(game.deck)
    for p in opponents:
        pool += p.hand + p.drafted + p.draft_hand
    rng.shuffle(pool)
    for p in opponents:
        n_hand, n_drafted, n_draft = len(p.hand), len(p.drafted), len(p.draft_hand)
        p.hand = [pool.pop() for _ in range(n_hand)]
        p.drafted = [pool.pop() for _ in range(n_drafted)]
        p.draft_hand = [pool.pop() for _ in range(n_draft)]
    game.deck = pool
    game.rng = random.Random(rng.random())


class MCTSBot(Bot):
    """Bot che prova le mosse migliori con simulazioni (vedi la spiegazione in cima al file).

    simulations: simulazioni per ogni decisione importante (più = più forte e più lento);
                 si dividono tra le candidate: con 30 e 5 candidate, 6 rimescolamenti a testa.
    candidates:  quante mosse provare (le migliori secondo il bot a regole).
    smart:       simulazioni dove servono (vedi in cima al file); False = parti uguali.
    prior_temperature: quanto si fida del bot a regole al primo giro (in M€ di
                 distacco: più è basso, meno simulazioni alle mosse stimate scarse).
    prune_z:     prudenza nello scartare (2 = scarta solo se peggiore "al 95%").
    equivalence: punti sotto cui due mosse sono "praticamente uguali" (ci si ferma).
    Le altre opzioni (card_power, random_corporation...) vanno al bot a regole
    che usa per le candidate, per le scelte minori e per giocare le simulazioni.
    """

    name = "mcts"
    ALWAYS_TAKE = RuleBot.ALWAYS_GOOD    # mosse sempre giuste: niente simulazioni

    def __init__(self, seed: int | None = None, simulations: int = 30, candidates: int = 5,
                 smart: bool = False, prior_temperature: float = 8.0, prune_z: float = 2.0,
                 equivalence: float = 1.0,
                 **rule_options):
        self.rng = random.Random(seed)
        self.rules = RuleBot(seed, **rule_options)
        # I giocatori delle simulazioni: bot a regole con le stesse opzioni.
        rollout_options = {k: v for k, v in rule_options.items() if k != "random_corporation"}
        self.rollout_bot = RuleBot(self.rng.randrange(10 ** 9), **rollout_options)
        self.simulations = simulations
        self.candidates = candidates
        self.smart = smart
        self.prior_temperature = prior_temperature
        self.prune_z = prune_z
        self.equivalence = equivalence
        self.searches = 0                  # quante decisioni ha "pensato" (statistica)
        self.simulations_used = 0          # quante simulazioni ha giocato (statistica)

    # ------------------------------------------------------------------

    def choose(self, game: Game, actions: list[Action]) -> Action:
        if len(actions) == 1 or not self._worth_thinking(game):
            return self.rules.choose(game, actions)
        player = game.current_player
        ranked = sorted(actions, key=lambda a: self.rules.score(game, player, a), reverse=True)
        best_rule_score = self.rules.score(game, player, ranked[0])
        if best_rule_score >= self.ALWAYS_TAKE:
            return ranked[0]
        candidates = ranked[:self.candidates]
        if len(candidates) == 1:
            return candidates[0]
        self.searches += 1
        if self.smart:
            priors = [self.rules.score(game, player, a) for a in candidates]
            return self._smart_search(game, player, candidates, priors)
        return self._search(game, player, candidates)

    @staticmethod
    def _worth_thinking(game: Game) -> bool:
        """Solo le decisioni "vere" della fase azioni (non tessere, attacchi, scelte in attesa)."""
        return (game.phase is Phase.ACTION and not game.state.pending_tiles
                and not game.pending_choices and not game.pending_attacks and not game.revealed
                and not game.selling and not game.bonus_play
                and not game.current_player.drafted and not game.current_player.prelude_choices)

    def _search(self, game: Game, player: Player, candidates: list[Action]) -> Action:
        worlds = max(1, self.simulations // len(candidates))      # rimescolamenti per candidata
        seeds = [self.rng.randrange(10 ** 9) for _ in range(worlds)]
        means = []
        for action in candidates:
            total = sum(self._simulate(game, player, action, seed) for seed in seeds)
            means.append(total / worlds)
        self.simulations_used += worlds * len(candidates)
        # A parità, vince la candidata che il bot a regole preferiva (è la prima).
        best = max(range(len(candidates)), key=lambda k: (means[k], -k))
        return candidates[best]

    MIN_WORLDS = 2          # simulazioni minime per candidata al primo giro
    MIN_EVIDENCE = 4        # rimescolamenti in comune prima di scartare o fermarsi:
                            # con 2 soli, due risultati uguali "per caso" sembrano certezze
    NOISE_FLOOR = 1.0       # punti: incertezza minima, anche se i risultati coincidono

    def _smart_search(self, game: Game, player: Player, candidates: list[Action],
                      priors: list[float]) -> Action:
        """Simulazioni dove servono: prior al primo giro, poi scarto progressivo."""
        budget = self.simulations
        seeds: list[int] = []
        results: list[list[float]] = [[] for _ in candidates]   # risultati per seed, in ordine

        def run(k: int, n: int) -> None:
            """Porta la candidata k a `n` rimescolamenti (gli stessi per tutte)."""
            nonlocal budget
            while len(seeds) < n:
                seeds.append(self.rng.randrange(10 ** 9))
            for seed in seeds[len(results[k]):n]:
                results[k].append(self._simulate(game, player, candidates[k], seed))
                budget -= 1

        # 1) Primo giro: metà del budget, divisa secondo il prior (il bot a regole).
        best_prior = max(priors)
        weights = [math.exp(-(best_prior - p) / self.prior_temperature) for p in priors]
        first_round = budget / 2
        for k, w in enumerate(weights):
            run(k, max(self.MIN_WORLDS, round(first_round * w / sum(weights))))
        alive = list(range(len(candidates)))

        # 2) Giri successivi: scarta le chiaramente peggiori, rinforza le altre.
        while True:
            alive, settled = self._prune(alive, results)
            if len(alive) == 1 or settled or budget <= 0:
                break
            target = max(self.MIN_EVIDENCE, max(len(results[k]) for k in alive))
            if all(len(results[k]) >= target for k in alive):
                target += max(1, min(budget // len(alive), target))  # raddoppia, se c'è budget
            for k in alive:
                if budget <= 0:
                    break
                run(k, target)

        self.simulations_used += self.simulations - budget
        # 3) Scelta: la media più alta sui rimescolamenti comuni a tutte le rimaste;
        #    a parità, la preferita dal bot a regole (ordine delle candidate).
        common = min(len(results[k]) for k in alive)
        best = max(alive, key=lambda k: (statistics.fmean(results[k][:common]), -k))
        return candidates[best]

    def _prune(self, alive: list[int], results: list[list[float]]) -> tuple[list[int], bool]:
        """Tiene le candidate che non sono chiaramente peggiori della migliore.

        Il confronto è "a coppie" sugli stessi rimescolamenti: la fortuna delle carte
        è la stessa per entrambe, quindi conta solo la differenza tra le mosse.
        Dice anche se la decisione è "chiusa": tutte le rimaste sono sicuramente
        entro `equivalence` punti dalla migliore, quindi altre simulazioni non servono."""
        def mean(k):
            return statistics.fmean(results[k])
        leader = max(alive, key=lambda k: (mean(k), -k))
        keep = []
        settled = True
        for k in alive:
            if k == leader:
                keep.append(k)
                continue
            n = min(len(results[k]), len(results[leader]))
            if n < self.MIN_EVIDENCE:        # troppo presto per giudicare
                keep.append(k)
                settled = False
                continue
            diffs = [results[k][i] - results[leader][i] for i in range(n)]
            spread = statistics.stdev(diffs) if n > 1 else float("inf")
            uncertainty = max(spread, self.NOISE_FLOOR) / math.sqrt(n)
            difference = statistics.fmean(diffs)
            if difference + self.prune_z * uncertainty >= 0:
                keep.append(k)
                if abs(difference) + self.prune_z * uncertainty > self.equivalence:
                    settled = False
        return sorted(keep), settled

    def _simulate(self, game: Game, player: Player, action: Action, seed: int) -> float:
        """Una simulazione: copia, rimescola il nascosto (sempre allo stesso modo per lo
        stesso seed), fa la mossa, gioca fino a fine generazione e valuta."""
        sim = game.clone()
        me = sim.state.players[game.state.players.index(player)]
        world = random.Random(seed)
        determinize(sim, me, world)
        self.rollout_bot.rng = random.Random(seed + 1)
        # La generazione si legge PRIMA della mossa: se la mossa stessa chiude la
        # generazione (per esempio "passa" quando l'avversario ha già passato), la
        # simulazione deve fermarsi lì, come per le altre candidate. Altrimenti si
        # giocherebbe una generazione in più e le valutazioni non sarebbero confrontabili.
        generation = sim.state.generation
        sim.apply(action, check=False)
        bot = self.rollout_bot
        while not sim.is_over() and sim.state.generation == generation:
            sim.apply(bot.choose(sim, sim.legal_actions()), check=False)
        return evaluate(sim, me)
