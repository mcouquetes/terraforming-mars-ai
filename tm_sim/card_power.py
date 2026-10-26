"""La "potenza" delle carte, al netto del contesto, e le correzioni per il bot.

IL PROBLEMA DELLE STATISTICHE SEMPLICI
"Chi gioca Birds vince il 60%" non vuol dire che Birds sia forte: Birds si
gioca tardi, spesso da chi è già in vantaggio. E chi gioca Birds ha giocato
anche altre 20 carte, ha una corporazione, siede in un certo posto...

COME LO RISOLVIAMO: UNA REGRESSIONE
Per ogni giocatore di ogni partita guardiamo:
    punti relativi = i suoi punti meno la media del tavolo
e cerchiamo i numeri (uno per carta, preludio, corporazione e posto) che
spiegano meglio i punti relativi di tutti i giocatori di tutte le partite.
Anche le carte si confrontano con il tavolo: i punti relativi di un
giocatore dipendono dalle SUE carte meno la media delle carte del tavolo
(a 2 giocatori, una carta da +6 punti alza lo scarto di 6 rispetto
all'avversario, ma solo di 3 rispetto alla media, che include te). Il numero di una carta è il suo contributo medio in punti, a parità
di tutto il resto: è la sua POTENZA. La presentiamo rispetto a una carta
media: +3 = "giocarla vale 3 punti più di una carta qualsiasi".

È una "regressione ridge": la versione prudente della regressione lineare,
che avvicina a zero le stime delle carte giocate poche volte (con pochi
dati, meglio dire "nella media" che inventare un numero estremo).

LE CORREZIONI PER IL BOT
Con la stessa regressione, ma al posto dei punti relativi usiamo "punti
relativi meno quelli che le regole del bot si aspettavano", otteniamo per
ogni carta quanto il bot la SOTTOVALUTA (+) o SOPRAVVALUTA (-). learn.py
passa queste correzioni ai bot del round successivo.

LE ACCOPPIATE (le tue lezioni, vedi tm_sim/teaching.py)
Per ogni accoppiata da verificare c'è una colonna in più, che vale 1 quando il
giocatore ha giocato ENTRAMBE le metà (carta, preludio o corporazione). Il suo
numero è la SINERGIA: quanti punti in più fanno insieme, oltre a ciò che vale
ciascuna da sola. Anche qui una correzione: quanto il bot la sottovaluta.

ATTENZIONE: anche questa resta una stima su partite tra bot. Toglie molti
effetti del contesto (le altre carte, la corporazione, il posto), non tutti:
per esempio non sa se una carta viene giocata solo quando si è già in testa.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

KINDS = ("carta", "preludio", "corporazione")
PAIR_KIND = "coppia"
RIDGE = 20.0          # prudenza: una carta vista ~20 volte viene "dimezzata" verso la media

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEARN_FOLDER = PROJECT_ROOT / "risultati" / "apprendimento"   # dove learn.py salva i progressi
SHIPPED_FOLDER = PROJECT_ROOT / "dati"                         # correzioni incluse nel progetto


def latest_file(n_players: int, folder: Path = LEARN_FOLDER) -> Path:
    """Il file con le ultime correzioni imparate da learn.py per quel numero di giocatori."""
    return Path(folder) / f"ultime_correzioni_{n_players}_giocatori.json"


def shipped_folder_for(folder: Path) -> Path:
    """La cartella di dati/ che corrisponde a una cartella di apprendimento
    (risultati/apprendimento/draft -> dati/draft)."""
    try:
        return SHIPPED_FOLDER / Path(folder).resolve().relative_to(LEARN_FOLDER.resolve())
    except ValueError:
        return SHIPPED_FOLDER


def find_corrections(n_players: int, folder: Path = LEARN_FOLDER) -> Path | None:
    """Dove trovare il bot "più istruito" per quel numero di giocatori:
    prima i progressi di learn.py, poi le correzioni incluse nel progetto (dati/)."""
    for path in (latest_file(n_players, folder),
                 shipped_folder_for(folder) / f"correzioni_{n_players}_giocatori.json"):
        if path.exists():
            return path
    return None


def find_nearest_corrections(n_players: int, folder: Path = LEARN_FOLDER) -> Path | None:
    """Come find_corrections, ma se per quel numero di giocatori non c'è niente usa
    quelle del numero più vicino (le correzioni a 2 giocatori valgono anche a 3)."""
    for other in sorted(range(2, 6), key=lambda n: (abs(n - n_players), n)):
        path = find_corrections(other, folder)
        if path is not None:
            return path
    return None


def resolve_corrections(spec: str, n_players: int, draft: bool = False) -> Path:
    """"ultime" -> il file più recente per quel numero di giocatori (o il più vicino);
    altrimenti il percorso dato. Con il draft cerca prima quelle imparate con il draft."""
    if spec == "ultime" and draft:
        path = find_nearest_corrections(n_players, LEARN_FOLDER / "draft")
        if path is not None:
            return path
        print("(Nessuna correzione imparata con il draft: uso quelle senza draft)")
    if spec == "ultime":
        path = find_nearest_corrections(n_players)
        if path is None:
            raise SystemExit("Nessuna correzione imparata: lancia prima learn.py")
        if path != find_corrections(n_players):
            print(f"(Per {n_players} giocatori non ho ancora correzioni: uso {path.name})")
        return path
    path = Path(spec)
    if not path.exists():
        raise SystemExit(f"File di correzioni non trovato: {spec}")
    return path


@dataclass
class PlayerRecord:
    """Un giocatore in una partita: cosa ha preso e come è andata."""
    game: str                      # identificativo della partita (round e seed)
    seat: int
    corporation: str
    preludes: list[str]
    cards: list[str]               # carte progetto giocate
    score: float
    expected: float = 0.0          # PV che le regole del bot si aspettavano da tutto questo
    weight: float = 1.0            # peso nella regressione (i round vecchi pesano meno)


@dataclass
class PowerEntry:
    kind: str
    name: str
    plays: float                   # quante volte è stata giocata (in tutti i round)
    power: float                   # PV rispetto alla media del suo tipo
    margin: float                  # margine di errore (95%) della potenza
    correction: float              # PV in più (+) o in meno (-) di quanto stima il bot


@dataclass
class PowerTable:
    entries: list[PowerEntry] = field(default_factory=list)
    records: int = 0

    def corrections(self) -> dict[str, float]:
        return {e.name: round(e.correction, 3) for e in self.entries if e.kind in KINDS}

    def uncertainties(self) -> dict[str, float]:
        """Quanto è incerta ogni correzione (deviazione standard, in PV): serve a
        learn.py per esplorare di più le carte che conosce meno."""
        return {e.name: round(e.margin / 1.96, 3) for e in self.entries
                if e.kind in KINDS + (PAIR_KIND,) and e.plays > 0}

    def pair_corrections(self) -> dict[str, float]:
        """Accoppiate: quanti PV in più dà giocarle insieme, oltre a quanto stima il bot."""
        return {e.name: round(e.correction, 3) for e in self.entries if e.kind == PAIR_KIND}

    def ranking(self, kind: str, min_plays: float = 0) -> list[PowerEntry]:
        items = [e for e in self.entries if e.kind == kind and e.plays >= min_plays]
        return sorted(items, key=lambda e: (-e.power, e.name))

    def save(self, folder: Path, extra: dict | None = None) -> list[Path]:
        """Salva le correzioni (JSON, per il bot) e la classifica (CSV, per te)."""
        folder.mkdir(parents=True, exist_ok=True)
        json_path = folder / "correzioni.json"
        json_path.write_text(json.dumps(
            {"correzioni": self.corrections(), "coppie": self.pair_corrections(),
             "incertezze": self.uncertainties(),
             "giocatori_registrati": self.records,
             **(extra or {})}, ensure_ascii=False, indent=1), encoding="utf-8")
        csv_path = folder / "potenza_carte.csv"
        with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["tipo", "nome", "giocata", "potenza_pv", "margine", "correzione_pv"])
            for kind in KINDS + (PAIR_KIND,):
                for e in self.ranking(kind):
                    writer.writerow([e.kind, e.name, round(e.plays, 1), round(e.power, 2),
                                     round(e.margin, 2), round(e.correction, 2)])
        return [json_path, csv_path]


def fit(records: list[PlayerRecord], ridge: float = RIDGE,
        prior: dict[str, float] | None = None,
        pairs: dict[str, float] | None = None) -> PowerTable:
    """Calcola potenza e correzioni di ogni carta, preludio e corporazione.

    prior: correzioni già imparate in passato. Le stime partono da lì invece
    che da zero: una carta vista poche volte nei dati nuovi tiene (quasi) la
    correzione di prima, una vista spesso si aggiorna con i dati nuovi.
    pairs: le accoppiate da verificare ("A + B") con la stima di partenza (la
    fiducia data dalle lezioni, o quanto imparato nei round prima).
    """
    if not records:
        return PowerTable()

    # 1. Le "colonne": una per ogni carta, preludio, corporazione e posto.
    columns: dict[tuple[str, str], int] = {}

    def column(kind: str, name: str) -> int:
        return columns.setdefault((kind, name), len(columns))

    pair_index: dict[str, list[tuple[str, str]]] = defaultdict(list)   # nome -> [(compagna, coppia)]
    for key in (pairs or {}):
        a, _, b = key.partition(" + ")
        pair_index[a].append((b, key))

    rows_features = []
    for r in records:
        features = [column("carta", c) for c in r.cards]
        if pair_index:
            owned = set(r.cards) | set(r.preludes) | {r.corporation}
            for name in owned:
                for partner, key in pair_index.get(name, ()):
                    if partner in owned:
                        features.append(column(PAIR_KIND, key))
        features += [column("preludio", p) for p in r.preludes]
        if r.corporation:
            features.append(column("corporazione", r.corporation))
        if r.seat > 1:                       # il posto 1 è il riferimento
            features.append(column("posto", str(r.seat)))
        rows_features.append(features)

    # 2. Punti relativi alla media del tavolo (e lo stesso per le stime del bot).
    by_game: dict[str, list[PlayerRecord]] = defaultdict(list)
    for r in records:
        by_game[r.game].append(r)
    mean_score = {g: sum(p.score for p in ps) / len(ps) for g, ps in by_game.items()}
    mean_expected = {g: sum(p.expected for p in ps) / len(ps) for g, ps in by_game.items()}
    relative = np.array([r.score - mean_score[r.game] for r in records])
    surprise = relative - np.array([r.expected - mean_expected[r.game] for r in records])
    weights = np.array([r.weight for r in records])

    # 3. Le caratteristiche di ogni giocatore, meno la media del suo tavolo.
    n_cols = len(columns)
    table_sum: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for r, features in zip(records, rows_features):
        for j in features:
            table_sum[r.game][j] += 1.0
    table_size = {g: len(ps) for g, ps in by_game.items()}

    def block_matrix(start: int, stop: int) -> np.ndarray:
        x = np.zeros((stop - start, n_cols))
        for i in range(start, stop):
            for j in rows_features[i]:
                x[i - start, j] += 1.0
            game = records[i].game
            for j, total in table_sum[game].items():
                x[i - start, j] -= total / table_size[game]
        return x

    # 4. Regressione ridge, a blocchi per non occupare troppa memoria:
    #    (XᵀWX + ridge·I) · coefficienti = XᵀW·y
    xtx = np.zeros((n_cols, n_cols))
    xty = np.zeros((n_cols, 2))
    plays = np.zeros(n_cols)          # pesate: servono per la media del tipo
    counts = np.zeros(n_cols)         # vere: quelle che mostriamo
    for r, features in zip(records, rows_features):
        for j in features:
            plays[j] += r.weight
            counts[j] += 1
    targets = np.stack([relative, surprise], axis=1)
    block = 5000
    for start in range(0, len(records), block):
        stop = min(start + block, len(records))
        x = block_matrix(start, stop)
        w = weights[start:stop, None]
        xtx += x.T @ (x * w)
        xty += x.T @ (targets[start:stop] * w)
    system = xtx + ridge * np.eye(n_cols)
    if prior:
        # Ridge "verso ciò che sapevamo": (XᵀWX + ridge·I) b = XᵀWy + ridge·b_prima
        for (kind, name), j in columns.items():
            if kind in KINDS:
                xty[j, 1] += ridge * prior.get(name, 0.0)
    for (kind, name), j in columns.items():
        if kind == PAIR_KIND:      # accoppiate: si parte dalla fiducia (o da ciò che sapevamo)
            xty[j, 1] += ridge * pairs.get(name, 0.0)
    coefficients = np.linalg.solve(system, xty)

    # 5. Margine di errore: dispersione dei residui × incertezza di ogni coefficiente.
    residual_var = 0.0
    total_weight = weights.sum()
    for start in range(0, len(records), block):
        stop = min(start + block, len(records))
        x = block_matrix(start, stop)
        residual = relative[start:stop] - x @ coefficients[:, 0]
        residual_var += float((weights[start:stop] * residual ** 2).sum())
    sigma = (residual_var / max(total_weight, 1.0)) ** 0.5
    margins = 1.96 * sigma * np.sqrt(np.diag(np.linalg.inv(system)))

    # 6. Rispetto alla media del proprio tipo (carta media, preludio medio...).
    table = PowerTable(records=len(records))
    for kind in KINDS:
        idx = [j for (k, _), j in columns.items() if k == kind]
        if not idx:
            continue
        w = plays[idx]
        mean_power = float((coefficients[idx, 0] * w).sum() / max(w.sum(), 1e-9))
        mean_correction = float((coefficients[idx, 1] * w).sum() / max(w.sum(), 1e-9))
        for (k, name), j in columns.items():
            if k == kind:
                table.entries.append(PowerEntry(
                    kind, name, float(counts[j]), float(coefficients[j, 0]) - mean_power,
                    float(margins[j]), float(coefficients[j, 1]) - mean_correction))
    for (k, name), j in columns.items():
        if k == PAIR_KIND:         # la sinergia è già "in più": niente media da togliere
            table.entries.append(PowerEntry(PAIR_KIND, name, float(counts[j]),
                                            float(coefficients[j, 0]), float(margins[j]),
                                            float(coefficients[j, 1])))
    # Accoppiate mai giocate insieme in questi dati: restano alla stima di partenza.
    seen = {name for (k, name) in columns if k == PAIR_KIND}
    for key, value in (pairs or {}).items():
        if key not in seen:
            table.entries.append(PowerEntry(PAIR_KIND, key, 0.0, 0.0, 0.0, value))
    for (k, name), j in columns.items():
        if k == "posto":
            table.entries.append(PowerEntry("posto", name, float(counts[j]),
                                            float(coefficients[j, 0]), float(margins[j]), 0.0))
    return table
