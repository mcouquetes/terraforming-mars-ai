"""Gioca una partita da terminale contro i bot.

Uso (dalla cartella del progetto):
    python play.py                   # tu contro 1 bot, con corporazioni e preludi
    python play.py 4                 # partita a 4: tu contro 3 bot
    python play.py 3 standard        # corporazioni ma niente preludi
    python play.py 2 principiante    # 42 M€ e 10 carte gratis, niente corporazioni
    python play.py 2 prelude casuale # avversari casuali invece che a regole
    python play.py 2 prelude imparato        # contro il bot che ha imparato (learn.py)
    python play.py 2 prelude mcts            # contro il bot che "pensa avanti" (MCTS + ciò che ha imparato)
    python play.py 3 prelude dati/correzioni_2_giocatori.json   # ...o con un file preciso
    python play.py 3 prelude regole senza-draft   # il draft è predefinito: così lo togli
Scrivi il numero della mossa, oppure q per uscire.
"""

import sys

from tm_sim.actions import CARD_PRICE, PAYMENT_CHOICES, Action, ActionCategory, ActionType, group_by_category
from tm_sim.board import Board, Bonus, Space, SpaceType, TileType
from tm_sim.bots import RandomBot, RuleBot
from tm_sim.card_power import resolve_corrections
from tm_sim.mcts import MCTSBot
from tm_sim.card_data import PRELUDE_CARDS
from tm_sim.card_list import CARDS_BY_NAME
from tm_sim.cards import Tag
from tm_sim.corporations import CORPORATIONS_BY_NAME, Corporation
from tm_sim.game import MAX_PLAYERS, MIN_PLAYERS, NOBODY, Game, Phase, Setup
from tm_sim.milestones import (
    AWARDS,
    AWARDS_BY_NAME,
    MAX_AWARDS,
    MAX_MILESTONES,
    MILESTONE_COST,
    MILESTONES,
    MILESTONES_BY_NAME,
)
from tm_sim.state import MAX_OCEANS, MAX_OXYGEN, MAX_TEMPERATURE, Player, Resource

PRELUDES_BY_NAME = {p.name: p for p in PRELUDE_CARDS}

HUMAN = "Tu"
# Nomi dei bot: iniziali tutte diverse, così sulla mappa si distinguono
# (CA = città di Anna, FB = foresta di Bruno...).
BOT_NAMES = ["Anna", "Bruno", "Carla", "Dario"]

RESOURCE_LABELS = {
    Resource.MEGACREDITS: "M€",
    Resource.STEEL: "Acciaio",
    Resource.TITANIUM: "Titanio",
    Resource.PLANTS: "Piante",
    Resource.ENERGY: "Energia",
    Resource.HEAT: "Calore",
}


def describe_corporation(corp: Corporation) -> str:
    extras = [f"{corp.starting_megacredits} M€"]
    extras += [f"{n:+d} prod. {r.value}" for r, n in corp.production.items()]
    extras += [f"{n} {r.value}" for r, n in corp.resources.items()]
    if corp.tags:
        extras.append("tag: " + ", ".join(t.value for t, n in corp.tags.items() for _ in range(n)))
    return f"{corp.name} ({', '.join(extras)}) – {corp.description}"


def describe_player(game: Game, player: Player, show_hand: bool) -> str:
    corp = f" [{player.corporation.name}]" if player.corporation else ""
    lines = [f"  {player.name}{corp}: TR {player.terraform_rating}, "
             f"foreste {player.greeneries}, città {player.cities}, "
             f"carte giocate {len(player.played)}, in mano {len(player.hand)}, "
             f"punti {game.score(player)}"]
    if show_hand and player.corporation:
        lines.append(f"    Potere: {player.corporation.description}")
    for resource, label in RESOURCE_LABELS.items():
        lines.append(f"    {label:<8} {player.resources[resource]:>3}"
                     f"   (produzione {player.production[resource]:+d})")
    tags = [f"{tag.value} {player.tag_count(tag)}" for tag in Tag if player.tag_count(tag)]
    if tags:
        lines.append("    Tag: " + ", ".join(tags))
    blue = []
    for card in player.active_cards():
        stored = player.card_resources.get(card.name, 0)
        extra = f" ({stored} {card.resource_type.value})" if card.resource_type else ""
        blue.append(card.name + extra)
    if blue:
        lines.append("    Carte blu: " + ", ".join(blue))
    if show_hand and player.hand:
        lines.append("    Mano:")
        lines.extend(f"      - {card.describe()}" for card in player.hand)
    return "\n".join(lines)


BONUS_CODES = {Bonus.STEEL: "s", Bonus.TITANIUM: "t", Bonus.PLANT: "p", Bonus.CARD: "c"}
SPECIAL_CODES = {
    TileType.CAPITAL: "Ca", TileType.COMMERCIAL_DISTRICT: "Cd", TileType.ECOLOGICAL_ZONE: "Ez",
    TileType.LAVA_FLOWS: "Lf", TileType.MINING_AREA: "Ma", TileType.MINING_RIGHTS: "Mr",
    TileType.MOHOLE_AREA: "Mo", TileType.NATURAL_PRESERVE: "Np", TileType.NUCLEAR_ZONE: "Nz",
    TileType.RESTRICTED_AREA: "Ra", TileType.INDUSTRIAL_CENTER: "Ic",
}


def space_label(space: Space) -> str:
    """4 caratteri per casella.
    Vuote: bonus (s acciaio, t titanio, p pianta, c carta), ~ ai lati = casella oceano.
    Occupate: ≈≈ oceano, C+iniziale città, F+iniziale foresta. NC = riservata,
    R+iniziale = riservata a quel giocatore (Land Claim)."""
    if space.tile is TileType.OCEAN:
        return " ≈≈ "
    if space.tile is TileType.CITY:
        return f" C{space.owner[0]} "
    if space.tile is TileType.GREENERY:
        return f" F{space.owner[0]} "
    if space.tile is not None:                     # tessera speciale
        return f"{SPECIAL_CODES[space.tile]}{space.owner[0]} "
    if space.reserved:
        return " NC "
    if space.claimed_by:                           # segnalino di Land Claim
        return f" R{space.claimed_by[0]} "
    code = "".join(BONUS_CODES[b] for b in space.bonuses) or "·"
    if space.type is SpaceType.OCEAN:
        return f"~{code:^2}~"
    return f"{code:^4}"


def render_board(board: Board) -> str:
    rows = board.rows()
    longest = max(len(row) for row in rows)
    lines = []
    for row in rows:
        indent = " " * (2 * (longest - len(row)))
        cells = "".join(f"[{space_label(s)}]" for s in row)
        lines.append(f"  {row[0].row}  {indent}{cells}")
    off_map = [s for s in board.spaces.values() if not s.on_mars and s.tile]
    if off_map:
        lines.append("  Nello spazio: " + ", ".join(
            f"{s.id} [città di {s.owner}]" for s in off_map))
    lines.append("  Legenda: Ca Capital, Cd Commercial District, Ez Ecological Zone, "
                 "Lf Lava Flows, Ma/Mr Mining Area/Rights, Mo Mohole, Np Natural Preserve, "
                 "Nz Nuclear Zone, Ra Restricted Area, Ic Industrial Center, "
                 "R+iniziale casella riservata (Land Claim)")
    return "\n".join(lines)


def describe_space(board: Board, space: Space) -> str:
    bonuses = ", ".join(b.value for b in space.bonuses) or "nessun bonus"
    oceans = board.adjacent_oceans(space)
    extra = f", +{2 * oceans} M€ per {oceans} oceani vicini" if oceans else ""
    volcanic = ", vulcano" if space.volcanic else ""
    return f"casella {space.id} ({bonuses}{extra}{volcanic})"


def show_state(game: Game) -> None:
    planet = game.state.planet
    print()
    print("=" * 70)
    print(f"Generazione {game.state.generation}")
    print(render_board(game.state.board))
    print(f"  Temperatura {planet.temperature:+d}°C / {MAX_TEMPERATURE:+d}   "
          f"Ossigeno {planet.oxygen}% / {MAX_OXYGEN}%   "
          f"Oceani {planet.oceans} / {MAX_OCEANS}")
    print(describe_milestones_and_awards(game))
    for player in game.state.players:
        print(describe_player(game, player, show_hand=(player.name == HUMAN)))
    print("=" * 70)


def describe_milestones_and_awards(game: Game) -> str:
    claimed = game.state.claimed_milestones
    milestones = ", ".join(
        f"{m.name} ({m.description})" + (f" → {claimed[m.name]}" if m.name in claimed else "")
        for m in MILESTONES)
    funded = game.state.funded_awards
    awards = ", ".join(
        f"{a.name} ({a.description})" + (" → finanziato" if a.name in funded else "")
        for a in AWARDS)
    cost = game.next_award_cost()
    cost_text = f"prossimo costa {cost} M€" if cost else "esauriti"
    return (f"  Traguardi [{len(claimed)}/{MAX_MILESTONES}]: {milestones}\n"
            f"  Riconoscimenti [{len(funded)}/{MAX_AWARDS}, {cost_text}]: {awards}")


# Categorie che contengono sempre una sola mossa: scegliendole si esegue
# subito l'azione, senza un sottomenu inutile.
DIRECT_CATEGORIES = {ActionCategory.RAISE_TEMPERATURE, ActionCategory.BUILD_GREENERY}


def read_choice(n: int, allow_back: bool) -> int | None:
    """Legge un numero da 1 a n e restituisce l'indice (da 0).

    Con allow_back=True accetta anche 0 e restituisce None ("indietro").
    Con q esce dal programma.
    """
    lowest = 0 if allow_back else 1
    while True:
        answer = input("> ").strip().lower()
        if answer == "q":
            print("Partita interrotta.")
            sys.exit()
        if answer.isdigit() and lowest <= int(answer) <= n:
            return None if int(answer) == 0 else int(answer) - 1
        print(f"Scrivi un numero da {lowest} a {n}, oppure q per uscire")


def describe_payment(payment) -> str:
    """Es. "paghi 6 M€ + 2 acciaio"."""
    parts = [f"{payment.megacredits} M€"] if payment.megacredits or not (
        payment.steel or payment.titanium or payment.heat or payment.microbes) else []
    for amount, what in [(payment.steel, "acciaio"), (payment.titanium, "titanio"),
                         (payment.heat, "calore"), (payment.microbes, "microbi")]:
        if amount:
            parts.append(f"{amount} {what}")
    return "paghi " + " + ".join(parts)


def describe_action(game: Game, action: Action) -> str:
    """Testo dettagliato di una mossa, per i sottomenu."""
    player = game.current_player
    if action.type is ActionType.PLAY_CARD:
        card = CARDS_BY_NAME[action.card]
        cost = game.card_cost(player, card)
        discount = f" [scontata a {cost} M€]" if cost != card.cost else ""
        steel, titanium = PAYMENT_CHOICES[action.payment]
        payment = card.payment_for(player, cost, game.payment_rules(player),
                                   game.payment_microbes(player, card), steel, titanium)
        return f"{card.describe()}{discount}  →  {describe_payment(payment)}"
    if action.type is ActionType.CARD_ACTION and action.card in CARDS_BY_NAME:
        card = CARDS_BY_NAME[action.card]
        alternative = card.actions[int(action.target)]
        text = f"{card.name}: {alternative.describe(card.resource_type)}"
        if action.option:
            text += f" [{action.option.replace(':', ': ')}]"
        if alternative.spend.get(Resource.MEGACREDITS):
            payment = game.action_payment(player, alternative, None, action.payment)
            text += f"  →  {describe_payment(payment)}"
        return text
    if action.type is ActionType.CHOOSE_EFFECT:
        pending = game.pending_choices[0]
        alternative = pending.alternatives[int(action.target)]
        text = alternative.describe(pending.card.resource_type)
        return f"{text} → su {action.option}" if action.option else text
    if action.type in (ActionType.SELL_CARD, ActionType.KEEP_CARD, ActionType.DRAFT_CARD):
        return CARDS_BY_NAME[action.card].describe()
    if action.type is ActionType.STOP_SELLING:
        return "basta così"
    if action.type is ActionType.SKIP_BONUS_PLAY:
        return "non giocare nessuna carta"
    if action.type is ActionType.CHOOSE_CORPORATION:
        return describe_corporation(CORPORATIONS_BY_NAME[action.card])
    if action.type in (ActionType.KEEP_PRELUDE, ActionType.PLAY_PRELUDE):
        return PRELUDES_BY_NAME[action.card].describe()
    if action.type is ActionType.DISCARD_PRELUDE:
        return f"{action.type.value}: {action.card}"
    if action.type is ActionType.ATTACK:
        if action.target == NOBODY:
            return "nessuno (rinuncio)"
        kind, card = game.pending_attacks[0]
        target = next(p for p in game.state.players if p.name == action.target)
        amount = game.attack_amount(kind, card, target, action.option or "")
        verb = "riduci la produzione di" if kind == "production" else (
            "ruba" if card.raid_steals else "togli")
        what = (action.option or "").replace(":", " da ")
        return f"{target.name}: {verb} {amount} {what}"
    if action.type is ActionType.FIRST_ACTION:
        first = CORPORATIONS_BY_NAME[action.card].first_action.value
        return f"{first}: {action.target}" if action.target else first
    if action.type is ActionType.CLAIM_MILESTONE:
        milestone = MILESTONES_BY_NAME[action.target]
        return f"{milestone.name} ({milestone.description}) – {MILESTONE_COST} M€"
    if action.type is ActionType.FUND_AWARD:
        award = AWARDS_BY_NAME[action.target]
        return f"{award.name} ({award.description}) – {game.next_award_cost()} M€"
    return str(action)


def ask_buy(game: Game, actions: list[Action]) -> Action:
    """Tutte le carte pescate insieme: scrivi i numeri di quelle che compri."""
    player = game.current_player
    cards = list(player.drafted)
    money = player.resources[Resource.MEGACREDITS]
    print(f"\nHai {money} M€: ogni carta comprata costa {CARD_PRICE} M€ "
          f"(puoi comprarne al massimo {min(len(cards), money // CARD_PRICE)}).")
    if player.corporation is not None:
        print(f"La tua corporazione: {player.corporation.name}")
    if player.preludes:
        print("I tuoi preludi: " + ", ".join(p.name for p in player.preludes))
    for i, card in enumerate(cards, start=1):
        print(f"  {i}. {card.describe()}")
    by_group = {frozenset(a.cards): a for a in actions}
    while True:
        print("Quali compri? Numeri separati da spazi (es. 1 4 7), invio = nessuna, q = esci")
        answer = input("> ").strip().lower()
        if answer == "q":
            print("Partita interrotta.")
            sys.exit()
        parts = answer.replace(",", " ").split()
        if not all(x.isdigit() and 1 <= int(x) <= len(cards) for x in parts):
            print(f"Scrivi numeri da 1 a {len(cards)}")
            continue
        group = frozenset(cards[int(x) - 1].name for x in parts)
        if group in by_group:
            return by_group[group]
        print(f"Non hai abbastanza M€ per {len(group)} carte")


def ask_research(game: Game, actions: list[Action]) -> Action:
    card = CARDS_BY_NAME[actions[0].card]
    player = game.current_player
    left = len(player.drafted)
    print(f"\nHai {player.resources[Resource.MEGACREDITS]} M€. Carta da valutare "
          f"({left} rimaste): {card.describe()}")
    for i, action in enumerate(actions, start=1):
        print(f"  {i}. {action}")
    return actions[read_choice(len(actions), allow_back=False)]


FLAT_HEADERS = {
    ActionType.CHOOSE_CORPORATION: "Scegli la tua corporazione:",
    ActionType.KEEP_PRELUDE: "Scegli un preludio da tenere (ne tieni 2):",
    ActionType.PLAY_PRELUDE: "Gioca un preludio:",
    ActionType.DISCARD_PRELUDE: "Nessun preludio si può giocare:",
    ActionType.FIRST_ACTION: "Azione iniziale obbligatoria della tua corporazione:",
    ActionType.ATTACK: "Chi vuoi attaccare?",
    ActionType.SELL_CARD: "Quale carta vendi? (1 M€ l'una; poi puoi venderne altre)",
    ActionType.DRAFT_CARD: "Draft: quale carta tieni?",
    ActionType.CHOOSE_EFFECT: "Scegli:",
    ActionType.KEEP_CARD: "Quale carta tieni?",
    ActionType.SKIP_BONUS_PLAY: "Puoi giocare subito una carta:",
}


def ask_flat(game: Game, actions: list[Action]) -> Action:
    """Una scelta semplice da un elenco, senza menu a due livelli."""
    print()
    header = FLAT_HEADERS[actions[0].type]
    if actions[0].type is ActionType.ATTACK:
        header = f"Chi vuoi attaccare con {actions[0].card}?"
    elif actions[0].type is ActionType.CHOOSE_EFFECT:
        header = f"{actions[0].card}: scegli un effetto"
    elif actions[0].type is ActionType.KEEP_CARD:
        header = f"Quale carta tieni? (ancora {game.keep_left})"
    elif actions[0].type is ActionType.DRAFT_CARD:
        player = game.current_player
        players = game.state.players
        left = players[(players.index(player) + 1) % len(players)].name
        kept = ", ".join(c.name for c in player.drafted) or "nessuna"
        passing = (f"le altre {len(actions) - 1} passano a {left}" if len(actions) > 1
                   else "è l'ultima del giro")
        header = (f"DRAFT (generazione {game.state.generation}): tieni una carta, {passing}. "
                  f"Hai {player.resources[Resource.MEGACREDITS]} M€. Già scelte: {kept}")
    elif (actions[0].type is ActionType.CHOOSE_CORPORATION
          or (actions[0].type is ActionType.KEEP_PRELUDE and not game.current_player.preludes)):
        show_starting_offer(game)
    print(header)
    for i, action in enumerate(actions, start=1):
        print(f"  {i}. {describe_action(game, action)}")
    return actions[read_choice(len(actions), allow_back=False)]


def show_starting_offer(game: Game) -> None:
    """Inizio partita: come al tavolo, vedi tutto insieme (corporazioni, preludi e
    le 10 carte) prima di decidere. Le carte le comprerai dopo, tutte in una volta."""
    player = game.current_player
    if player.prelude_choices:
        print("Preludi offerti: " + ", ".join(c.name for c in player.prelude_choices))
    if player.drafted:
        print(f"Le tue {len(player.drafted)} carte iniziali (le comprerai dopo, 3 M€ l'una):")
        for card in player.drafted:
            print(f"   - {card.describe()}")
    print()


def ask_placement(game: Game, actions: list[Action]) -> Action:
    board = game.state.board
    print()
    print(render_board(board))
    print(f"Dove vuoi piazzare la tessera {game.pending_tile.describe()}?")
    for i, action in enumerate(actions, start=1):
        print(f"  {i}. {describe_space(board, board.spaces[action.space])}")
    return actions[read_choice(len(actions), allow_back=False)]


def ask_human(game: Game, actions: list[Action]) -> Action:
    """Menu a due livelli: prima la categoria, poi la mossa."""
    if game.pending_tile is not None:
        return ask_placement(game, actions)
    if game.bonus_play:            # Eccentric Sponsor, Ecology Experts: elenco semplice
        actions = sorted(actions, key=lambda a: a.type is not ActionType.SKIP_BONUS_PLAY)
    if actions[0].type in FLAT_HEADERS:
        return ask_flat(game, actions)
    if actions[0].type is ActionType.BUY_CARDS:
        return ask_buy(game, actions)
    if actions[0].type in (ActionType.BUY_CARD, ActionType.SKIP_CARD):
        return ask_research(game, actions)
    if game.phase is Phase.FINAL_GREENERY:
        print("Fine partita: puoi ancora trasformare le piante in foreste.")

    groups = group_by_category(actions)
    turn_actions = groups.pop(ActionCategory.TURN, [])  # passa / fine turno

    while True:
        # Livello 1: le categorie disponibili, più passa/fine turno.
        entries: list[ActionCategory | Action] = list(groups) + turn_actions
        print("Cosa vuoi fare?")
        for i, entry in enumerate(entries, start=1):
            if isinstance(entry, ActionCategory):
                print(f"  {i}. {entry.value} ({len(groups[entry])})")
            else:
                print(f"  {i}. {str(entry).capitalize()}")
        chosen = entries[read_choice(len(entries), allow_back=False)]

        if isinstance(chosen, Action):
            return chosen
        options = groups[chosen]
        if chosen in DIRECT_CATEGORIES:
            return options[0]

        # Livello 2: solo le mosse possibili in quella categoria.
        print(f"{chosen.value}:")
        for i, action in enumerate(options, start=1):
            print(f"  {i}. {describe_action(game, action)}")
        print("  0. Indietro")
        index = read_choice(len(options), allow_back=True)
        if index is not None:
            return options[index]


SETUPS = {s.value: s for s in Setup}


def main() -> None:
    draft = "senza-draft" not in sys.argv[1:]          # il draft è predefinito
    argv = [a for a in sys.argv[1:] if a not in ("draft", "senza-draft")]
    n_players = int(argv[0]) if len(argv) > 0 else 2
    setup = SETUPS.get(argv[1] if len(argv) > 1 else "prelude")
    kind = argv[2] if len(argv) > 2 else "regole"
    if not MIN_PLAYERS <= n_players <= MAX_PLAYERS or setup is None:
        print(__doc__)
        return
    if kind == "casuale":
        bots = {name: RandomBot() for name in BOT_NAMES[:n_players - 1]}
    elif kind == "regole":
        bots = {name: RuleBot() for name in BOT_NAMES[:n_players - 1]}
    elif kind == "mcts":
        # Il bot che simula le mosse prima di sceglierle, con le correzioni imparate se ci sono.
        try:
            path = str(resolve_corrections("ultime", n_players, draft))
        except SystemExit:
            path = None
        print("Avversari: bot MCTS" + (f" (con le correzioni di {path})" if path else ""))
        bots = {name: MCTSBot(card_power=path) for name in BOT_NAMES[:n_players - 1]}
    elif kind == "imparato" or kind.endswith(".json"):
        # Il bot "istruito" da learn.py: le ultime correzioni per questo numero di giocatori.
        path = resolve_corrections("ultime" if kind == "imparato" else kind, n_players, draft)
        print(f"Avversari: bot con le correzioni di {path}")
        bots = {name: RuleBot(card_power=str(path)) for name in BOT_NAMES[:n_players - 1]}
    else:
        print(__doc__)
        return
    game = Game([HUMAN, *bots], setup=setup, draft=draft)
    game.messages = []      # così il motore racconta gli effetti a scatto (carte blu, corporazioni)
    last_generation = 0
    print(f"\nPartita a {n_players} giocatori, variante {setup.value}"
          f"{', con il draft' if draft else ''}.")

    while not game.is_over():
        if game.phase is Phase.ACTION and game.state.generation != last_generation:
            last_generation = game.state.generation
            print(f"\n*** Generazione {last_generation}: fase delle azioni ***")

        actions = game.legal_actions()
        if game.current_player.name == HUMAN:
            # Lo stato completo serve solo quando si gioca, non mentre si sceglie.
            if (game.pending_tile is None
                    and game.phase in (Phase.PRELUDES, Phase.ACTION, Phase.FINAL_GREENERY)):
                show_state(game)
            action = ask_human(game, actions)
        else:
            name = game.current_player.name
            action = bots[name].choose(game, actions)
            if action.type is ActionType.BUY_CARD:
                print(f"{name} compra una carta")
            elif action.type is ActionType.BUY_CARDS:
                n = len(action.cards)
                print(f"{name} compra {n} {'carta' if n == 1 else 'carte'}")
            elif action.type in (ActionType.SKIP_CARD, ActionType.KEEP_PRELUDE,
                                 ActionType.DRAFT_CARD, ActionType.KEEP_CARD):
                pass   # scelte segrete: non le mostriamo
            elif action.type is ActionType.CHOOSE_CORPORATION:
                print(f"{name} ha scelto la corporazione {action.card}")
            else:
                print(f"{name} sceglie: {action}")
        game.apply(action)
        for message in game.messages:
            print(f"   ✦ {message}")
        game.messages.clear()

    show_state(game)
    print("\nPartita finita!")
    for name, score in game.scores().items():
        print(f"  {name}: {score} punti")
    winners = game.winners()
    print("Vince: " + " e ".join(winners) if len(winners) == 1
          else "Pareggio tra " + " e ".join(winners))


if __name__ == "__main__":
    main()
