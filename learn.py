"""Simulazioni a round che si passano ciò che hanno imparato sulle carte.

Uso (dalla cartella del progetto):
    python learn.py                               # 5 round da 2000 partite a 2 giocatori
    python learn.py --round 8 --partite 5000      # più round, più partite
    python learn.py --giocatori 3 --verifica 500  # a 3 giocatori; verifica più precisa
    python learn.py --da-zero                     # dimentica tutto e ricomincia
    python learn.py --senza-draft                 # partite senza draft (predefinito: con il draft;
                                                  # i due apprendimenti si salvano separati)
    python learn.py --potenziale 0.4              # bot 60/40 valore effettivo/potenziale:
                                                  # impara quanto potenziale si realizza, carta per carta
    python learn.py --continua un_file.json       # riparti da un file di correzioni preciso
    python learn.py --prova-coppie 0.5            # quante partite "truccate" per le tue accoppiate
    python learn.py --senza-insegnamenti          # ignora le lezioni di insegna.py
    python learn.py --esplorazione 0.3            # prova di più le carte poco conosciute
    python learn.py --help

LE TUE LEZIONI (insegna.py)
Se hai insegnato delle accoppiate con insegna.py, learn.py le mette alla prova:
il bot parte fidandosi di te (bonus iniziale), in una parte delle partite
(--prova-coppie, predefinito 30% dei giocatori) l'accoppiata viene messa apposta
nella mano iniziale, e la regressione misura quanto vale davvero giocarla
insieme. Alla fine di ogni round vedi quali accoppiate sono confermate.

IL BOT CONTINUA A IMPARARE
Ogni volta che lanci learn.py riparte da dove era arrivato l'ultima volta per
quel numero di giocatori (file risultati/apprendimento/ultime_correzioni_N_giocatori.json;
la prima volta, dalle correzioni incluse nel progetto in dati/, se ci sono).
I round continuano la numerazione: round_6, round_7... Con --da-zero si
ricomincia dal bot di base.

Gli altri programmi possono usare il bot "istruito" quando glielo chiedi:
    python simulate.py 1000 2 --correzioni ultime
    python play.py 2 prelude imparato
    python tools/ab_test.py 1000 --a card_power=ultime

COME FUNZIONA
Round 1: i bot a regole giocano N partite. Ogni volta che un bot gioca una
carta (o un preludio, o prende una corporazione) registriamo quanti punti le
regole del bot si ASPETTAVANO da quella carta.
Fine del round: la regressione di tm_sim/card_power.py stima, per ogni carta:
  - la sua POTENZA: quanti punti vale davvero, al netto di corporazione, posto
    e altre carte giocate (la classifica che ci interessa);
  - la sua CORREZIONE: quanto il bot la sottovaluta o sopravvaluta.
Round 2: i bot ricevono le correzioni (giocano meglio, si spera), giocano N
nuove partite, e la regressione - con tutti i dati raccolti, ma dando più
peso ai round recenti - aggiorna potenza e correzioni. E così via.

Dopo ogni round una VERIFICA (test A/B a specchio) misura se il bot con le
correzioni batte quello di base: è la prova che le stime stanno migliorando.

I risultati di ogni round finiscono in risultati/apprendimento/G_giocatori/round_N/:
  potenza_carte.csv  la classifica (apribile con Excel)
  correzioni.json    le correzioni, da usare con RuleBot(card_power=...) o
                     con tools/ab_test.py --a card_power=...
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import time
from pathlib import Path

from tm_sim.bots import RuleBot, load_corrections, load_pairs
from tm_sim.actions import ActionType
from tm_sim.card_data import PRELUDE_CARDS
from tm_sim.card_power import (
    PlayerRecord,
    PowerTable,
    find_corrections,
    find_nearest_corrections,
    fit,
    latest_file,
)
from tm_sim.cards import CardType
from tm_sim.corporations import CORPORATIONS_BY_NAME
from tm_sim.game import Game, Setup
from tm_sim.parallel import choose_processes, run_in_parallel, split_seeds
from tm_sim.teaching import TEACH_FILE, hypotheses, load_lessons, plant_pair
from tools.ab_test import play_mirrored

PRELUDES_BY_NAME = {p.name: p for p in PRELUDE_CARDS}
SEAT_NAMES = ["Posto 1", "Posto 2", "Posto 3", "Posto 4", "Posto 5"]
DECAY = 0.7              # i dati di ogni round precedente pesano il 70% di quelli del round dopo
MAX_CORRECTION = 8.0     # correzione massima (PV), per prudenza
MAX_PAIR = 8.0           # sinergia massima di un'accoppiata (PV)
UNSEEN_UNCERTAINTY = 2.0  # incertezza (PV) di una carta mai vista: si esplora parecchio

ALL_NAMES = None          # tutti i nomi di carte, preludi e corporazioni (calcolati al primo uso)


def all_names() -> list[str]:
    global ALL_NAMES
    if ALL_NAMES is None:
        from tm_sim.card_list import ALL_CARDS
        ALL_NAMES = sorted({c.name for c in ALL_CARDS} | set(PRELUDES_BY_NAME)
                           | set(CORPORATIONS_BY_NAME))
    return ALL_NAMES


def explored(corrections: dict[str, float], uncertainty: dict[str, float], scale: float,
             rng: random.Random) -> dict[str, float]:
    """Campionamento di Thompson: ogni correzione + un "dubbio" casuale grande quanto
    la sua incertezza. Le carte ben conosciute restano quasi uguali; quelle poco
    viste ogni tanto sembrano migliori e vengono provate (e così si impara)."""
    return {name: corrections.get(name, 0.0)
            + rng.gauss(0.0, scale * uncertainty.get(name, UNSEEN_UNCERTAINTY))
            for name in all_names()}
SEEDS_PER_ROUND = 1_000_000   # i seed di ogni round sono diversi: partite sempre nuove


def play_learning_game(round_number: int, seed: int, n_players: int, setup: Setup,
                       corrections: dict[str, float], draft: bool = False,
                       potential: float = 0.0, pairs: dict[str, float] | None = None,
                       to_test: list[str] = (), plant: float = 0.0, explore: float = 0.0,
                       uncertainty: dict[str, float] | None = None) -> list[PlayerRecord]:
    """Gioca una partita tra bot con le correzioni attuali, e registra le stime.

    pairs: le accoppiate con il loro bonus attuale; to_test: quelle da mettere alla
    prova; plant: probabilità che un giocatore riceva apposta un'accoppiata da provare;
    explore: quanto esplorare (0 = niente; 1 = campionamento di Thompson, vedi explored)."""
    seats = SEAT_NAMES[:n_players]
    noise = random.Random(seed * 17 + 3)
    bots = {seat: RuleBot(seed * 10 + i, random_corporation=True,
                          card_power=(explored(corrections, uncertainty or {}, explore, noise)
                                      if explore else corrections),
                          potential_weight=potential, pair_power=pairs or {})
            for i, seat in enumerate(seats)}
    game = Game(seats, seed=seed, setup=setup, draft=draft)
    if to_test and plant:
        rng = random.Random(seed * 31 + 7)
        for player in game.state.players:
            if rng.random() < plant:
                plant_pair(game, player, rng.choice(list(to_test)), rng)
    expected = dict.fromkeys(seats, 0.0)
    while not game.is_over():
        player = game.current_player
        action = bots[player.name].choose(game, game.legal_actions())
        # Prima di giocare: quanto si aspettavano le regole di base?
        if action.type is ActionType.PLAY_CARD:
            card = next(c for c in player.hand if c.name == action.card)
            expected[player.name] += RuleBot.base_estimate(game, player, card, weight=potential)
        elif action.type is ActionType.PLAY_PRELUDE:
            card = PRELUDES_BY_NAME[action.card]
            expected[player.name] += RuleBot.base_estimate(game, player, card, weight=potential)
        elif action.type is ActionType.CHOOSE_CORPORATION:
            corp = CORPORATIONS_BY_NAME[action.card]
            expected[player.name] += RuleBot.base_estimate(game, player, corporation=corp)
        game.apply(action, check=False)     # scelta dalla lista legale appena calcolata

    records = []
    for seat_index, player in enumerate(game.state.players):
        played = player.played
        records.append(PlayerRecord(
            game=f"{round_number}-{seed}", seat=seat_index + 1,
            corporation=player.corporation.name if player.corporation else "",
            preludes=[c.name for c in played if c.type is CardType.PRELUDE],
            cards=[c.name for c in played if c.type is not CardType.PRELUDE],
            score=game.score(player), expected=expected[player.name]))
    return records


def play_learning_chunk(job: tuple) -> list[PlayerRecord]:
    """Un gruppo di partite di apprendimento (gira in un processo separato)."""
    seeds, round_number, n_players, setup, corrections, draft, potential = job[:7]
    pairs, to_test, plant = job[7:10] if len(job) > 7 else ({}, (), 0.0)
    explore, uncertainty = job[10:12] if len(job) > 10 else (0.0, {})
    records = []
    for seed in seeds:
        records += play_learning_game(round_number, seed, n_players, setup, corrections, draft,
                                      potential, pairs, to_test, plant, explore, uncertainty)
    return records


def verify(corrections: dict[str, float], n_seeds: int, n_players: int, processes: int,
           first_seed: int, draft: bool = False, potential: float = 0.0,
           pairs: dict[str, float] | None = None) -> tuple[float, float, float, float]:
    """Test A/B a specchio: bot con correzioni (A) contro bot di base (B).
    Restituisce (% vittorie A, margine, scarto di punti, margine)."""
    seeds = list(range(first_seed, first_seed + n_seeds))
    jobs = [(chunk, n_players, {"card_power": corrections, "potential_weight": potential,
                                "pair_power": pairs or {}},
             {"potential_weight": 0.0}, draft)
            for chunk in split_seeds(seeds, max(processes * 8, 1))]
    results = [r for chunk in run_in_parallel(play_mirrored, jobs, processes) for r in chunk]
    wins = [w for w, _ in results]
    diffs = [d for _, d in results]

    def margin(values):
        return 1.96 * statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else 0.0

    return 100 * statistics.mean(wins), 100 * margin(wins), statistics.mean(diffs), margin(diffs)


def print_table(table: PowerTable, kind: str, title: str, min_plays: float, show: int) -> None:
    ranking = table.ranking(kind, min_plays)
    if not ranking:
        return
    print(f"\n{title} (potenza in punti rispetto alla media, giocate almeno {min_plays:.0f} volte)")
    print(f"  {'nome':<32} {'giocata':>8} {'potenza':>8} {'margine':>8} {'correzione':>11}")
    shown = ranking if len(ranking) <= 2 * show else ranking[:show] + [None] + ranking[-show:]
    for e in shown:
        if e is None:
            print(f"  {'...':<32}")
            continue
        print(f"  {e.name:<32} {e.plays:>8.0f} {e.power:>+8.2f} {'±' + format(e.margin, '.2f'):>8} "
              f"{e.correction:>+11.2f}")


def print_pairs(table: PowerTable, show: int) -> None:
    """Le accoppiate messe alla prova: quanto valgono insieme e cosa ne pensa ora il bot."""
    entries = table.ranking("coppia")
    if not entries:
        return
    print(f"  Accoppiate ({len(entries)}): sinergia = punti in più giocandole insieme")
    print(f"    {'accoppiata':<52} {'insieme':>8} {'sinergia':>9} {'margine':>8} {'bonus bot':>10}")
    shown = entries if len(entries) <= 2 * show else entries[:show] + [None] + entries[-show:]
    for e in shown:
        if e is None:
            print("    ...")
            continue
        if e.plays == 0:
            verdict = "mai giocata insieme: resta la tua fiducia"
            print(f"    {e.name:<52} {0:>8} {'':>9} {'':>8} {e.correction:>+10.2f}  {verdict}")
            continue
        verdict = ("CONFERMATA" if e.power > e.margin else "SMENTITA" if e.power < -e.margin
                   else "da verificare")
        print(f"    {e.name:<52} {e.plays:>8.0f} {e.power:>+9.2f} {'±' + format(e.margin, '.2f'):>8} "
              f"{e.correction:>+10.2f}  {verdict}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulazioni a round che imparano la potenza delle carte.")
    parser.add_argument("--round", type=int, default=5, help="quanti round (predefinito: 5)")
    parser.add_argument("--partite", type=int, default=2000, help="partite per round (predefinito: 2000)")
    parser.add_argument("--giocatori", type=int, default=2, choices=range(2, 6))
    parser.add_argument("--verifica", type=int, default=300,
                        help="distribuzioni a specchio per la verifica A/B di ogni round (0 = niente)")
    parser.add_argument("--processi", type=int, default=None)
    parser.add_argument("--continua", default=None,
                        help="riparti dalle correzioni salvate in questo file JSON "
                             "(predefinito: le ultime imparate per questo numero di giocatori)")
    parser.add_argument("--senza-draft", dest="draft", action="store_false",
                        help="partite senza draft (predefinito: con il draft; si salvano a parte)")
    parser.add_argument("--draft", dest="draft", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--potenziale", type=float, default=0.0,
                        help="peso del potenziale nel valore delle carte (0,4 = 60/40); "
                             "l'apprendimento si salva a parte per ogni peso")
    parser.add_argument("--da-zero", action="store_true",
                        help="non ripartire da niente: ricomincia dal bot di base")
    parser.add_argument("--insegnamenti", default=str(TEACH_FILE),
                        help="il file delle tue lezioni (insegna.py)")
    parser.add_argument("--senza-insegnamenti", action="store_true",
                        help="non mettere alla prova le accoppiate delle lezioni")
    parser.add_argument("--prova-coppie", type=float, default=0.3,
                        help="probabilità che un giocatore riceva apposta un'accoppiata da "
                             "provare nella mano iniziale (predefinito 0,3)")
    # Misurato (3 round da 2000 partite da zero, poi 4000 partite a specchio contro lo
    # stesso apprendimento senza esplorazione): 1,0 -> -1,00 ± 0,41 punti; 0,3 -> -0,18 ± 0,41.
    # Più dati sulle carte poco viste (+30%), ma il bot non diventa più forte: spenta.
    parser.add_argument("--esplorazione", type=float, default=0.0,
                        help="quanto il bot prova le carte di cui è incerto (campionamento di "
                             "Thompson): 0 = mai (predefinito), 1 = quanto l'incertezza")
    parser.add_argument("--cartella", default="risultati/apprendimento")
    parser.add_argument("--mostra", type=int, default=10, help="righe in cima e in fondo alle classifiche")
    args = parser.parse_args()

    processes = choose_processes(args.processi)
    base_folder = Path(args.cartella)
    folder = base_folder
    if args.potenziale:
        folder = folder / f"potenziale_{args.potenziale:g}"
    if args.draft:
        folder = folder / "draft"
    start_file = None
    same_players = True       # il file di partenza è per lo stesso numero di giocatori?
    if not args.da_zero:
        if args.continua:
            start_file = Path(args.continua)
        else:
            start_file = find_corrections(args.giocatori, folder)
            if start_file is None:            # mai fatto così: parti dal più vicino
                start_file = find_nearest_corrections(args.giocatori, folder)
            # Prima volta con draft/potenziale: parti dall'apprendimento più simile
            # (stesso draft senza potenziale, poi quello di base).
            fallbacks = [base_folder / "draft"] if args.draft else []
            for other in fallbacks + [base_folder]:
                if start_file is None and other != folder:
                    start_file = find_nearest_corrections(args.giocatori, other)
        if start_file is not None:
            info = json.loads(start_file.read_text(encoding="utf-8"))
            same_players = (info.get("giocatori", args.giocatori) == args.giocatori
                            and info.get("draft", False) == args.draft
                            and (info.get("potential_weight") or 0.0) == args.potenziale)
    corrections: dict[str, float] = load_corrections(start_file) if start_file else {}
    prior = dict(corrections)             # ciò che sapevamo prima di questa esecuzione
    # Accoppiate: quelle già verificate nei round passati + le ipotesi delle lezioni.
    pairs: dict[str, float] = load_pairs(start_file) if start_file else {}
    uncertainty: dict[str, float] = {}
    if start_file:
        uncertainty = json.loads(start_file.read_text(encoding="utf-8")).get("incertezze", {})
    lessons = [] if args.senza_insegnamenti else load_lessons(Path(args.insegnamenti))
    hints = hypotheses(lessons)
    new_hints = {k: v for k, v in hints.items() if k not in pairs}
    pairs.update(new_hints)               # le nuove partono dalla tua fiducia
    pair_prior = dict(pairs)
    to_test = sorted(hints) if hints else []
    if lessons:
        print(f"Lezioni: {len(lessons)} mani insegnate, {len(hints)} accoppiate da mettere "
              f"alla prova ({len(new_hints)} nuove).")
    rounds_done, games_done = 0, 0
    if start_file and same_players:
        rounds_done = info.get("round_totali", 0)
        games_done = info.get("partite_totali", 0)
        print(f"Riparto da {start_file} ({rounds_done} round e {games_done} partite già fatti).")
    elif start_file:
        print(f"Prima volta così ({args.giocatori} giocatori{', draft' if args.draft else ''}"
              f"{f', potenziale {args.potenziale:g}' if args.potenziale else ''}): "
              f"parto dalle correzioni di {start_file} ({info.get('giocatori')} giocatori"
              f"{', draft' if info.get('draft') else ''}) come punto di partenza.")
    else:
        print("Parto dal bot di base, senza correzioni.")
    records: list[PlayerRecord] = []
    min_plays = max(20, args.partite * args.round * args.giocatori // 200)
    table = PowerTable()
    print(f"{args.round} round da {args.partite} partite a {args.giocatori} giocatori"
          f"{' con draft' if args.draft else ''}"
          f"{f', potenziale {args.potenziale:g}' if args.potenziale else ''}, "
          f"{processes} {'processo' if processes == 1 else 'processi'}.")

    for round_number in range(rounds_done + 1, rounds_done + args.round + 1):
        start = time.perf_counter()
        first = round_number * SEEDS_PER_ROUND
        seeds = list(range(first, first + args.partite))
        jobs = [(chunk, round_number, args.giocatori, Setup.PRELUDE, corrections, args.draft,
                 args.potenziale, pairs, to_test, args.prova_coppie if to_test else 0.0,
                 args.esplorazione, uncertainty)
                for chunk in split_seeds(seeds, max(processes * 8, 1))]
        new_records = [r for chunk in run_in_parallel(play_learning_chunk, jobs, processes)
                       for r in chunk]
        for r in records:                     # i round passati contano un po' meno
            r.weight *= DECAY
        records += new_records

        table = fit(records, prior=prior, pairs=pair_prior)
        corrections = {name: max(-MAX_CORRECTION, min(MAX_CORRECTION, value))
                       for name, value in table.corrections().items()}
        pairs = {name: max(-MAX_PAIR, min(MAX_PAIR, value))
                 for name, value in table.pair_corrections().items()}
        uncertainty = table.uncertainties()
        games_done += len(new_records) // args.giocatori
        progress = {"round": round_number, "round_totali": round_number,
                    "partite_totali": games_done, "giocatori": args.giocatori,
                    "draft": args.draft, "potential_weight": args.potenziale}
        saved = table.save(folder / f"{args.giocatori}_giocatori" / f"round_{round_number}", progress)
        # Il "segnalibro": la prossima esecuzione (e gli altri programmi) ripartono da qui.
        latest_file(args.giocatori, folder).write_text(json.dumps(
            {"correzioni": corrections, "coppie": pairs, "incertezze": uncertainty, **progress},
            ensure_ascii=False, indent=1),
            encoding="utf-8")
        elapsed = time.perf_counter() - start

        print(f"\n=== Round {round_number}: {len(new_records) // args.giocatori} partite in "
              f"{elapsed:.0f} s, {table.records} giocatori registrati in tutto")
        reliable = [e for e in table.entries if e.kind == "carta" and e.plays >= min_plays]
        if reliable:
            mean_abs = sum(abs(e.correction) for e in reliable) / len(reliable)
            print(f"  Errore medio delle stime del bot sulle carte: {mean_abs:.2f} PV")
            worst = sorted(reliable, key=lambda e: e.correction)
            print("  Più sopravvalutate:  " + ", ".join(
                f"{e.name} ({e.correction:+.1f})" for e in worst[:4]))
            print("  Più sottovalutate:   " + ", ".join(
                f"{e.name} ({e.correction:+.1f})" for e in reversed(worst[-4:])))
        if pairs:
            print_pairs(table, args.mostra)
        if args.verifica:
            win, win_m, diff, diff_m = verify(corrections, args.verifica, args.giocatori,
                                              processes, first + SEEDS_PER_ROUND // 2, args.draft,
                                              args.potenziale, pairs)
            verdict = ("meglio" if diff > diff_m else "peggio" if diff < -diff_m
                       else "differenza non dimostrata")
            print(f"  Verifica, bot con le correzioni contro bot di base: vittorie {win:.1f}% ± {win_m:.1f}, "
                  f"scarto {diff:+.2f} ± {diff_m:.2f} punti ({verdict})")
        print(f"  Salvati: {', '.join(str(p) for p in saved)}")

    print_table(table, "corporazione", "CORPORAZIONI", 0, 20)
    print_table(table, "preludio", "PRELUDI", min_plays, args.mostra // 2)
    print_table(table, "carta", "CARTE PROGETTO", min_plays, args.mostra)
    print("\n'potenza' = punti in più (o in meno) rispetto a una carta media, a parità di contesto.")
    print("Se il margine è più grande della potenza, la carta non si distingue dalla media.")


if __name__ == "__main__":
    main()
