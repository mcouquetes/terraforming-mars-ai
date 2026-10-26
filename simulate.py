"""Fa giocare tra loro dei bot e stampa le statistiche su carte, preludi e corporazioni.

Uso (dalla cartella del progetto):
    python simulate.py                        # 1000 partite a 2 giocatori
    python simulate.py 5000                   # 5000 partite
    python simulate.py 1000 5                 # 1000 partite a 5 giocatori
    python simulate.py 1000 3 standard        # variante: principiante, standard, prelude
    python simulate.py 1000 4 prelude casuale # bot: regole (predefinito), casuale o mcts
    python simulate.py 10000 --processi 4     # usa 4 core (predefinito: tutti meno 2)
    python simulate.py 1000 2 --correzioni ultime   # con il bot che ha imparato (learn.py)
    python simulate.py 1000 3 --senza-draft   # il draft è predefinito: così lo togli
    python simulate.py --help                 # spiega tutte le opzioni

Le partite si giocano IN PARALLELO su più core del processore (vedi
tm_sim/parallel.py): i risultati sono identici a quelli su un core solo,
solo più veloci.

I risultati completi finiscono in CSV nella cartella "risultati" (apribili con
Excel: Dati → Da testo/CSV).

ATTENZIONE: le statistiche valgono quanto i bot che giocano, e sono
correlazioni, non cause (vedi tm_sim/stats.py).
"""

import argparse
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from tm_sim.bots import RandomBot, RuleBot
from tm_sim.mcts import MCTSBot
from tm_sim.card_power import resolve_corrections
from tm_sim.game import MAX_GENERATIONS, MAX_PLAYERS, MIN_PLAYERS, Game, Setup
from tm_sim.parallel import choose_processes, max_processes, run_in_parallel, split_seeds
from tm_sim.stats import StatsCollector, margin_of_error

BOTS = {"regole": RuleBot, "casuale": RandomBot, "mcts": MCTSBot}

# "Posto 1" è il primo giocatore della prima generazione, e così via.
SEAT_NAMES = ["Posto 1", "Posto 2", "Posto 3", "Posto 4", "Posto 5"]
SETUPS = {s.value: s for s in Setup}


def play_game(bots: dict, seed: int | None = None, setup: Setup = Setup.PRELUDE,
              draft: bool = True) -> Game:
    """Gioca una partita completa tra i bot indicati (nome -> bot)."""
    game = Game(list(bots), seed=seed, setup=setup, draft=draft)
    while not game.is_over():
        bot = bots[game.current_player.name]
        action = bot.choose(game, game.legal_actions())
        game.apply(action, check=False)      # i bot scelgono sempre dalla lista legale
    return game


def parse_arguments() -> argparse.Namespace:
    """Legge le opzioni dalla riga di comando.

    argparse è la libreria standard di Python per questo: genera da sola
    il messaggio di --help e controlla che i valori siano validi.
    """
    parser = argparse.ArgumentParser(description="Simula partite tra bot di Terraforming Mars.")
    parser.add_argument("partite", nargs="?", type=int, default=1000,
                        help="quante partite simulare (predefinito: 1000)")
    parser.add_argument("giocatori", nargs="?", type=int, default=2,
                        choices=range(MIN_PLAYERS, MAX_PLAYERS + 1),
                        help="giocatori per partita, da 2 a 5 (predefinito: 2)")
    parser.add_argument("variante", nargs="?", default="prelude", choices=list(SETUPS),
                        help="variante di preparazione (predefinito: prelude)")
    parser.add_argument("bot", nargs="?", default="regole", choices=list(BOTS),
                        help="tipo di bot (predefinito: regole)")
    parser.add_argument("--corporazioni", default="caso", choices=["caso", "bot"],
                        help="chi sceglie la corporazione: 'caso' (predefinito, giusto per "
                             "le statistiche: ognuna viene giocata alla pari) oppure 'bot' "
                             "(la sceglie il bot, più realistico ma falsa i confronti)")
    parser.add_argument("--minimo", type=int, default=None,
                        help="nelle classifiche, solo carte giocate almeno tante volte "
                             "(predefinito: il 3%% delle partite, minimo 20)")
    parser.add_argument("--mostra", type=int, default=15,
                        help="quante carte mostrare in cima e in fondo alla classifica (predefinito: 15)")
    parser.add_argument("--cartella", default="risultati",
                        help="dove salvare i CSV (predefinito: risultati)")
    parser.add_argument("--senza-draft", dest="draft", action="store_false",
                        help="senza il draft (predefinito: con il draft: 4 carte, se ne tiene "
                             "una e si passano le altre)")
    parser.add_argument("--draft", dest="draft", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--correzioni", default=None,
                        help="usa il bot che ha imparato da learn.py: 'ultime' (le più recenti "
                             "per questo numero di giocatori) oppure il percorso di un file JSON")
    parser.add_argument("--processi", type=int, default=None,
                        help=f"quanti core usare in parallelo (predefinito e massimo: tutti "
                             f"meno 2, qui {max_processes()}; 1 = senza parallelo)")
    return parser.parse_args()


def make_bot(kind: str, seed: int, corporations: str, corrections: dict | None = None):
    if kind == "regole":
        return RuleBot(seed, random_corporation=(corporations == "caso"), card_power=corrections)
    if kind == "mcts":      # circa 100 volte più lento: per poche centinaia di partite
        return MCTSBot(seed, random_corporation=(corporations == "caso"), card_power=corrections)
    return RandomBot(seed)


def print_ranking(stats: StatsCollector, kind: str, title: str, minimum: int, show: int) -> None:
    ranking = stats.ranking(kind, minimum)
    if not ranking:
        return
    print()
    # Generazione e "se non giocata" hanno senso solo per le carte progetto.
    details = kind == "carta"
    print(f"{title} (giocate almeno {minimum} volte: {len(ranking)})")
    header = (f"  {'nome':<30} {'giocata':>7} {'vittorie':>9} {'vantaggio':>10} {'margine':>8}")
    print(header + (f" {'gen.':>5} {'se non giocata':>15}" if details else ""))

    def row(item) -> str:
        text = (f"  {item.name:<30} {item.played:>7} {item.win_rate():>8.1f}% "
                f"{stats.advantage(item):>+9.1f} {'±' + format(item.margin(), '.1f'):>8}")
        if details:
            unplayed = item.win_rate_unplayed()
            unplayed_text = "" if unplayed is None else f"{unplayed:.1f}%"
            text += f" {item.average_generation():>5.1f} {unplayed_text:>15}"
        return text

    if len(ranking) <= 2 * show:
        for item in ranking:
            print(row(item))
    else:
        for item in ranking[:show]:
            print(row(item))
        print(f"  {'...':<30}")
        for item in ranking[-show:]:
            print(row(item))


@dataclass
class ChunkResult:
    """Quello che un processo restituisce dopo aver giocato il suo gruppo di partite."""
    stats: StatsCollector
    seat_wins: Counter = field(default_factory=Counter)
    seat_scores: Counter = field(default_factory=Counter)
    generations: int = 0
    unfinished: int = 0
    games: int = 0


def play_chunk(job: tuple) -> ChunkResult:
    """Gioca un gruppo di partite (gira in un processo separato, vedi tm_sim/parallel.py)."""
    seeds, n_players, setup, bot_kind, corporations, corrections, draft = job
    seats = SEAT_NAMES[:n_players]
    result = ChunkResult(StatsCollector(n_players))
    for seed in seeds:
        # Ogni bot ha un seed diverso, ma riproducibile.
        bots = {seat: make_bot(bot_kind, seed * 10 + i, corporations, corrections)
                for i, seat in enumerate(seats)}
        game = play_game(bots, seed, setup, draft)
        result.stats.add_game(game, seed)
        result.games += 1
        result.generations += game.state.generation - 1
        if game.state.generation > MAX_GENERATIONS:
            result.unfinished += 1
        winners = game.winners()
        for name, score in game.scores().items():
            result.seat_scores[name] += score
        for name in winners:
            result.seat_wins[name] += 1 / len(winners)   # in caso di parità, la vittoria si divide
    return result


def main() -> None:
    args = parse_arguments()
    n_games, n_players = args.partite, args.giocatori
    setup = SETUPS[args.variante]
    seats = SEAT_NAMES[:n_players]
    minimum = args.minimo if args.minimo is not None else max(20, n_games * 3 // 100)
    processes = choose_processes(args.processi)
    if args.processi and args.processi > processes:
        print(f"(Chiesti {args.processi} processi: ne uso {processes}, "
              f"per lasciare sempre 2 core liberi.)")

    print(f"Simulo {n_games} partite a {n_players} giocatori "
          f"(variante {setup.value}{' con draft' if args.draft else ''}, bot {args.bot}, "
          f"corporazioni scelte da: {args.corporazioni}, "
          f"{processes} {'processo' if processes == 1 else 'processi in parallelo'})...")

    # Tanti gruppi piccoli invece di uno per processo: così i processi finiscono
    # più o meno insieme, e possiamo mostrare l'avanzamento.
    chunks = split_seeds(list(range(n_games)), max(processes * 8, 10))
    corrections = None
    if args.correzioni:
        path = resolve_corrections(args.correzioni, n_players, args.draft)
        corrections = str(path)      # RuleBot legge anche il peso del potenziale dal file
        print(f"Bot con le correzioni imparate: {path}")
    jobs = [(chunk, n_players, setup, args.bot, args.corporazioni, corrections, args.draft)
            for chunk in chunks]

    total = ChunkResult(StatsCollector(n_players))
    start = time.perf_counter()
    last_shown = 0
    for result in run_in_parallel(play_chunk, jobs, processes):
        total.stats.merge(result.stats)
        total.seat_wins.update(result.seat_wins)
        total.seat_scores.update(result.seat_scores)
        total.generations += result.generations
        total.unfinished += result.unfinished
        total.games += result.games
        done = 100 * total.games // n_games
        if n_games >= 100 and done // 10 > last_shown // 10 and total.games < n_games:
            print(f"  {done}% fatto")
            last_shown = done
    stats, seat_wins, seat_scores = total.stats, total.seat_wins, total.seat_scores
    total_generations, unfinished = total.generations, total.unfinished

    elapsed = time.perf_counter() - start

    print()
    print(f"Partite giocate:       {n_games} a {n_players} giocatori, variante {setup.value}, bot {args.bot}")
    print(f"Tempo totale:          {elapsed:.1f} s ({1000 * elapsed / n_games:.1f} ms a partita)")
    print(f"Generazioni medie:     {total_generations / n_games:.1f}")
    print(f"Partite interrotte:    {unfinished}")
    print()
    print(f"Vittorie attese se l'ordine non contasse: {stats.expected_win_rate:.1f}%")
    for seat in seats:
        print(f"  {seat}: punti medi {seat_scores[seat] / n_games:5.1f}, "
              f"vittorie {100 * seat_wins[seat] / n_games:4.1f}% "
              f"(± {margin_of_error(seat_wins[seat], n_games):.1f})")

    print_ranking(stats, "corporazione", "CORPORAZIONI", 1, 50)
    print_ranking(stats, "preludio", "PRELUDI", minimum, args.mostra // 2)
    print_ranking(stats, "carta", "CARTE PROGETTO", minimum, args.mostra)

    print()
    print("Come leggere le tabelle: 'vantaggio' = % vittorie di chi la gioca meno quella attesa.")
    print("Se il vantaggio è più piccolo del margine, la differenza potrebbe essere solo fortuna.")
    print("'se non giocata' = % vittorie di chi l'ha comprata ma non è riuscito a giocarla.")

    files = stats.write_csv(Path(args.cartella))
    print()
    print("Risultati completi salvati in: " + ", ".join(str(f) for f in files))


if __name__ == "__main__":
    main()
