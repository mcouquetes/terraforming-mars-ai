"""Insegna al bot: guardi delle mani iniziali e dici cosa faresti.

Uso (dalla cartella del progetto):
    python insegna.py                 # 20 mani iniziali
    python insegna.py --mani 5        # quante mani
    python insegna.py --elenco        # le lezioni salvate e le accoppiate
    python learn.py                   # poi learn.py mette alla prova le tue accoppiate

Per ogni mano vedi, come al tavolo, 2 corporazioni (C1, C2), 4 preludi (P1-P4)
e 10 carte (1-10). Scegli corporazione, 2 preludi e le carte da comprare; poi
vedi cosa avrebbe fatto il bot. Infine indichi le ACCOPPIATE che ti hanno fatto
scegliere così, per esempio:
    C1+3      la corporazione C1 con la carta 3
    3+7       la carta 3 con la carta 7
    P2+5      il preludio P2 con la carta 5
Se non ne indichi, il programma ne deduce alcune: ogni carta che compri tu e il
bot no, insieme alla corporazione che hai scelto (con meno fiducia).

Le lezioni si salvano dopo ogni mano in risultati/insegnamenti.json: puoi
interrompere con q e riprendere quando vuoi (le mani già fatte non tornano).
Come le usa learn.py: vedi tm_sim/teaching.py.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from play import describe_corporation
from tm_sim.actions import CARD_PRICE
from tm_sim.bots import RuleBot
from tm_sim.card_power import find_nearest_corrections, LEARN_FOLDER
from tm_sim.game import Game, Phase, Setup
from tm_sim.teaching import TEACH_FILE, hypotheses, load_lessons, make_lesson, pair_key, save_lessons

FIRST_SEED = 900_000       # le mani delle lezioni: sempre le stesse, in ordine
HUMAN, OTHER = "Tu", "Avversario"


class Quit(Exception):
    pass


def ask(prompt: str) -> str:
    answer = input(prompt + "\n> ").strip()
    if answer.lower() == "q":
        raise Quit
    return answer


def ask_numbers(prompt: str, low: int, high: int, count: int | None = None,
                allow_empty: bool = False) -> list[int]:
    while True:
        parts = ask(prompt).replace(",", " ").split()
        if not parts and allow_empty:
            return []
        if all(p.isdigit() and low <= int(p) <= high for p in parts) and len(set(parts)) == len(parts):
            if count is None or len(parts) == count:
                return [int(p) for p in parts]
        need = f"{count} numeri" if count else "numeri"
        print(f"Scrivi {need} da {low} a {high}, separati da spazi (q = esci)")


def bot_choice(game: Game, corrections: str | None) -> dict:
    """Cosa sceglierebbe il bot a regole (con le correzioni imparate, se ci sono)."""
    sim = game.clone()
    me = sim.state.players[0]
    bot = RuleBot(1, card_power=corrections)
    while sim.phase is Phase.SETUP and sim.current_player is me:
        sim.apply(bot.choose(sim, sim.legal_actions()))
    return {"corporazione": me.corporation.name, "preludi": [p.name for p in me.preludes],
            "carte": [c.name for c in me.hand]}


def parse_pairs(text: str, labels: dict[str, str]) -> list[str] | None:
    """"C1+3 3+7" -> ["EcoLine + Fish", ...]; None se qualcosa non va."""
    pairs = []
    for token in text.replace(",", " ").split():
        left, plus, right = token.upper().partition("+")
        if not plus or left not in labels or right not in labels or left == right:
            return None
        pairs.append(pair_key(labels[left], labels[right]))
    return pairs


def teach_hand(seed: int, n_players: int, number: int, total: int,
               corrections: str | None) -> dict:
    names = [HUMAN] + [f"{OTHER} {i}" for i in range(1, n_players)]
    game = Game(names, seed=seed, setup=Setup.PRELUDE, draft=True)
    me = game.state.players[0]
    corps, preludes, cards = me.corporation_choices, me.prelude_choices, me.drafted
    labels = {f"C{i}": c.name for i, c in enumerate(corps, 1)}
    labels |= {f"P{i}": p.name for i, p in enumerate(preludes, 1)}
    labels |= {str(i): c.name for i, c in enumerate(cards, 1)}

    print(f"\n{'=' * 70}\nMANO {number} di {total}   (seed {seed})")
    print("\nCORPORAZIONI")
    for i, corp in enumerate(corps, 1):
        print(f"  C{i}. {describe_corporation(corp)}")
    print("\nPRELUDI (ne tieni 2)")
    for i, prelude in enumerate(preludes, 1):
        print(f"  P{i}. {prelude.describe()}")
    print(f"\nCARTE ({CARD_PRICE} M€ l'una per comprarle)")
    for i, card in enumerate(cards, 1):
        print(f"  {i:>2}. {card.describe()}")
    print()

    corp = corps[ask_numbers("Quale corporazione? (1 o 2)", 1, len(corps), 1)[0] - 1]
    chosen_preludes = [preludes[i - 1] for i in
                       ask_numbers("Quali 2 preludi? (es. 1 3)", 1, len(preludes), 2)]
    while True:
        picks = ask_numbers("Quali carte compri? (es. 2 5 7; invio = nessuna)", 1, len(cards),
                            allow_empty=True)
        if len(picks) * CARD_PRICE <= corp.starting_megacredits:
            break
        print(f"Con {corp.name} hai {corp.starting_megacredits} M€: al massimo "
              f"{corp.starting_megacredits // CARD_PRICE} carte")
    mine = {"corporazione": corp.name, "preludi": [p.name for p in chosen_preludes],
            "carte": [cards[i - 1].name for i in picks]}

    bot = bot_choice(game, corrections)
    print("\nIL BOT AVREBBE SCELTO:")
    print(f"  {bot['corporazione']}, preludi {', '.join(bot['preludi'])}")
    print(f"  carte: {', '.join(bot['carte']) or 'nessuna'}")
    only_mine = [c for c in mine["carte"] if c not in bot["carte"]]
    only_bot = [c for c in bot["carte"] if c not in mine["carte"]]
    if only_mine:
        print(f"  Tu sì, il bot no: {', '.join(only_mine)}")
    if only_bot:
        print(f"  Il bot sì, tu no: {', '.join(only_bot)}")
    if not only_mine and not only_bot and mine["corporazione"] == bot["corporazione"]:
        print("  Stesse scelte!")

    print("\nQuali ACCOPPIATE ti hanno fatto scegliere così? Usa C1/C2, P1-P4 e i numeri delle")
    print("carte, per esempio: C1+3 3+7 P2+5   (invio = nessuna, le deduco dalle differenze)")
    while True:
        pairs = parse_pairs(ask(""), labels)
        if pairs is not None:
            break
        print("Non ho capito: scrivi coppie come C1+3 o 3+7, separate da spazi")
    for key in pairs:
        print(f"  Accoppiata: {key}")
    offer = {"corporazioni": [c.name for c in corps], "preludi": [p.name for p in preludes],
             "carte": [c.name for c in cards]}
    lesson = make_lesson(seed, offer, mine, bot, pairs)
    if not pairs and lesson["coppie_dedotte"]:
        print("  Dedotte: " + ", ".join(lesson["coppie_dedotte"]))
    return lesson


def show_lessons(path: Path) -> None:
    lessons = load_lessons(path)
    if not lessons:
        print("Nessuna lezione salvata: lancia python insegna.py")
        return
    print(f"{len(lessons)} lezioni in {path}")
    for lesson in lessons:
        mine = lesson["scelta"]
        print(f"  seed {lesson['seed']}: {mine['corporazione']} + {', '.join(mine['preludi'])}; "
              f"carte: {', '.join(mine['carte']) or 'nessuna'}")
    hints = hypotheses(lessons)
    print(f"\nAccoppiate da mettere alla prova con learn.py ({len(hints)}), con la fiducia iniziale:")
    for key, value in sorted(hints.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {value:+.1f} PV  {key}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Insegna al bot le accoppiate forti delle mani iniziali.")
    parser.add_argument("--mani", type=int, default=20, help="quante mani (predefinito: 20)")
    parser.add_argument("--giocatori", type=int, default=2, choices=range(2, 6),
                        help="giocatori al tavolo (cambia solo le carte distribuite)")
    parser.add_argument("--file", default=str(TEACH_FILE), help="dove salvare le lezioni")
    parser.add_argument("--elenco", action="store_true", help="mostra le lezioni salvate ed esci")
    args = parser.parse_args()
    path = Path(args.file)
    if args.elenco:
        show_lessons(path)
        return

    lessons = load_lessons(path)
    done = {lesson["seed"] for lesson in lessons}
    found = find_nearest_corrections(args.giocatori, LEARN_FOLDER / "draft")
    corrections = str(found) if found else None
    print(f"Lezioni già salvate: {len(lessons)}. Ora {args.mani} mani nuove (q per uscire).")
    seed = FIRST_SEED
    taught = 0
    try:
        while taught < args.mani:
            if seed not in done:
                lessons.append(teach_hand(seed, args.giocatori, taught + 1, args.mani, corrections))
                save_lessons(lessons, path)       # salvata subito: si può interrompere
                taught += 1
            seed += 1
    except (Quit, EOFError):
        print("\nInterrotto.")
    print(f"\n{taught} mani insegnate in questa sessione, {len(lessons)} in tutto ({path}).")
    print(f"Accoppiate da mettere alla prova: {len(hypotheses(lessons))}. Ora lancia: python learn.py")


if __name__ == "__main__":
    sys.exit(main())
