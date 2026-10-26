"""Test A/B: una modifica rende il bot migliore?

Fa giocare due versioni del bot a regole, A e B, che differiscono solo nelle
opzioni indicate, e dice se A è davvero più forte o se la differenza
potrebbe essere solo fortuna.

Uso (dalla cartella del progetto):
    python tools/ab_test.py 2000                             # A e B uguali (controllo)
    python tools/ab_test.py 2000 --a sell_patents=False      # A senza vendita di brevetti
    python tools/ab_test.py 2000 --a potential_patience=1.0 --b potential_patience=0.3
    python tools/ab_test.py 2000 --giocatori 4               # A contro 3 bot B
    python tools/ab_test.py 2000 --processi 4                # core da usare (max: tutti meno 2)
    python tools/ab_test.py 2000 --a card_power=ultime       # il bot che ha imparato (learn.py)
    python tools/ab_test.py 2000 --senza-draft               # partite senza draft (predefinito: con)
    python tools/ab_test.py 100 --a-bot mcts                 # il bot MCTS contro il bot a regole
    python tools/ab_test.py 100 --a-bot mcts --a simulations=64 candidates=6

Le opzioni sono quelle di RuleBot (tm_sim/bots.py): milestone_race, sell_patents,
smart_payment, combo_patience, combo_hope, potential_patience, card_power...

PERCHÉ È PRECISO
1. Partite "a specchio": ogni distribuzione di carte (seed) si gioca tante volte
   quanti sono i giocatori, con A che ruota in tutti i posti. Le stesse carte e
   le stesse corporazioni toccano una volta ad A e una volta a B: la fortuna
   delle carte si annulla quasi del tutto.
2. Oltre alla % di vittorie misuriamo lo SCARTO DI PUNTI (A meno la media dei B),
   che è molto più sensibile: una piccola differenza si vede con meno partite.
3. Il margine di errore (95%) si calcola sui gruppi a specchio, che sono
   indipendenti tra loro.
"""

from __future__ import annotations

import argparse
import inspect
import math
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simulate import play_game  # noqa: E402
from tm_sim.bots import RuleBot, corrections_potential_weight, load_corrections, load_pairs  # noqa: E402
from tm_sim.mcts import MCTSBot  # noqa: E402

BOT_KINDS = {"regole": RuleBot, "mcts": MCTSBot}
from tm_sim.card_power import resolve_corrections  # noqa: E402
from tm_sim.parallel import choose_processes, run_in_parallel, split_seeds  # noqa: E402


def parse_options(texts: list[str]) -> dict:
    """["potential_patience=1.0", "sell_patents=False"] -> dizionario di opzioni per RuleBot."""
    allowed = (set(inspect.signature(RuleBot).parameters)
               | set(inspect.signature(MCTSBot).parameters)) - {"seed", "rule_options"}
    options = {}
    for text in texts:
        name, _, raw = text.partition("=")
        if name not in allowed:
            raise SystemExit(f"Opzione sconosciuta: {name}. Possibili: {', '.join(sorted(allowed))}")
        if raw in ("True", "False"):
            value = raw == "True"
        elif name == "card_power":
            value = raw                      # nome di un file: lo carica RuleBot
        else:
            value = float(raw) if "." in raw else int(raw)
        options[name] = value
    return options


def play_mirrored(job: tuple) -> list[tuple[float, float]]:
    """Gioca i seed del gruppo a specchio. Per ogni seed: (vittorie di A, scarto medio di punti).

    Con N giocatori si giocano N partite: A nel posto 1, poi nel posto 2...
    I bot ricevono il seed in base al POSTO, non alla versione: così anche le
    scelte casuali (corporazione) sono le stesse per chiunque sieda lì.
    """
    seeds, n_players, a_options, b_options, draft = job[:5]
    a_kind, b_kind = job[5] if len(job) > 5 else ("regole", "regole")
    results = []
    for seed in seeds:
        wins = 0.0
        difference = 0.0
        for a_seat in range(n_players):
            bots = {}
            for seat in range(n_players):
                options = a_options if seat == a_seat else b_options
                kind = a_kind if seat == a_seat else b_kind
                name = "A" if seat == a_seat else f"B{seat}"
                # Corporazioni a caso (predefinito): ognuna giocata lo stesso numero di volte.
                # Con --a random_corporation=False il bot A la sceglie da solo.
                bots[name] = BOT_KINDS[kind](seed * 10 + seat, **{"random_corporation": True, **options})
            game = play_game(bots, seed, draft=draft)
            winners = game.winners()
            wins += ("A" in winners) / len(winners)
            scores = game.scores()
            others = [s for name, s in scores.items() if name != "A"]
            difference += scores["A"] - sum(others) / len(others)
        results.append((wins / n_players, difference / n_players))
    return results


def margin(values: list[float]) -> float:
    """Margine di errore al 95% della media."""
    if len(values) < 2:
        return 0.0
    return 1.96 * statistics.stdev(values) / math.sqrt(len(values))


def main() -> None:
    parser = argparse.ArgumentParser(description="Test A/B tra due versioni del bot a regole.")
    parser.add_argument("seed", type=int, nargs="?", default=500,
                        help="quante distribuzioni di carte (ognuna si gioca a specchio)")
    # (con MCTS ogni partita dura molto di più: meglio poche centinaia di distribuzioni)
    parser.add_argument("--a", nargs="*", default=[], help="opzioni del bot A (nome=valore)")
    parser.add_argument("--b", nargs="*", default=[], help="opzioni del bot B (nome=valore)")
    parser.add_argument("--giocatori", type=int, default=2, choices=range(2, 6))
    parser.add_argument("--a-bot", default="regole", choices=list(BOT_KINDS),
                        help="tipo del bot A (predefinito: regole)")
    parser.add_argument("--b-bot", default="regole", choices=list(BOT_KINDS),
                        help="tipo del bot B (predefinito: regole)")
    parser.add_argument("--processi", type=int, default=None)
    parser.add_argument("--senza-draft", dest="draft", action="store_false",
                        help="partite senza draft (predefinito: con il draft)")
    parser.add_argument("--draft", dest="draft", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--primo-seed", type=int, default=0,
                        help="da quale seed partire (per non riusare le stesse partite)")
    args = parser.parse_args()

    a_options, b_options = parse_options(args.a), parse_options(args.b)
    for options in (a_options, b_options):        # "ultime" o un file -> le correzioni
        if isinstance(options.get("card_power"), str):
            path = resolve_corrections(options["card_power"], args.giocatori, args.draft)
            options["card_power"] = load_corrections(path)
            options.setdefault("pair_power", load_pairs(path))      # le accoppiate verificate
            # Le correzioni valgono con il peso del potenziale con cui sono state imparate.
            options.setdefault("potential_weight", corrections_potential_weight(path) or 0.0)
            print(f"Correzioni: {path}")
    n, players = args.seed, args.giocatori
    processes = choose_processes(args.processi)
    def describe(options: dict) -> str:
        shown = {k: (f"{len(v)} correzioni" if k == "card_power" else
                     f"{len(v)} accoppiate" if k == "pair_power" else v) for k, v in options.items()}
        return str(shown) if shown else "(standard)"

    print(f"A [{args.a_bot}] {describe(a_options)} contro B [{args.b_bot}] {describe(b_options)}")
    print(f"{n} distribuzioni a specchio x {players} posti = {n * players} partite, "
          f"{processes} {'processo' if processes == 1 else 'processi'}...")

    seeds = list(range(args.primo_seed, args.primo_seed + n))
    jobs = [(chunk, players, a_options, b_options, args.draft, (args.a_bot, args.b_bot))
            for chunk in split_seeds(seeds, max(processes * 8, 1))]
    start = time.perf_counter()
    results = [r for chunk in run_in_parallel(play_mirrored, jobs, processes) for r in chunk]
    elapsed = time.perf_counter() - start

    wins = [w for w, _ in results]
    differences = [d for _, d in results]
    expected = 100 / players
    win_rate, win_margin = 100 * statistics.mean(wins), 100 * margin(wins)
    diff, diff_margin = statistics.mean(differences), margin(differences)
    print(f"Tempo: {elapsed:.0f} s")
    print(f"Vittorie di A: {win_rate:.1f}% ± {win_margin:.1f} (atteso se uguali: {expected:.1f}%)")
    print(f"Scarto di punti (A meno B): {diff:+.2f} ± {diff_margin:.2f}")
    if abs(diff) > diff_margin:
        better = "A" if diff > 0 else "B"
        print(f"La differenza è DIMOSTRATA (95%): {better} è più forte.")
    else:
        print("La differenza NON è dimostrata: potrebbe essere solo fortuna.")


if __name__ == "__main__":
    main()
