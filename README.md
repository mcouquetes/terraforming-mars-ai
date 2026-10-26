# Terraforming Mars AI

[![Test](https://github.com/mcouquetes/terraforming-mars-ai/actions/workflows/test.yml/badge.svg)](https://github.com/mcouquetes/terraforming-mars-ai/actions/workflows/test.yml)
[![Licenza: GPL v3](https://img.shields.io/badge/licenza-GPLv3-blue.svg)](LICENSE)

**In English:** a Python game engine for the board game *Terraforming Mars*
(base game + Corporate Era + Prelude, 2–5 players, with draft), built to simulate
millions of games. It includes a rule-based bot, an MCTS bot that tests its moves
with simulations, a learning loop (`learn.py`) that estimates the real strength of
every card, prelude and corporation with a ridge regression, and a tool to teach the
bot card combos as hypotheses to be verified by simulation (`insegna.py`).
The documentation below is in Italian.

---

Un motore di gioco per Terraforming Mars scritto in Python, pensato per
simulare moltissime partite e ricavare **statistiche su carte, corporazioni
e preludi**: quali carte vincono di più, e quanto. Contiene anche i bot per
giocarci contro: a regole, MCTS (che prova le mosse con simulazioni) e uno che
impara dalle simulazioni e dalle tue lezioni.

> Progetto amatoriale, non affiliato a FryxGames, Stronghold Games o Asmodee.
> Il repository contiene solo codice che implementa le regole, i dati numerici
> delle carte e brevi descrizioni scritte per il gioco da terminale: nessuna
> immagine né testo ufficiale delle carte.

## Stato del progetto

- [x] Stato della partita: giocatori, risorse, produzioni, parametri globali
- [x] Azioni e turni (`legal_actions` / `apply`): progetti standard, conversioni, passa
- [x] Da 2 a 5 giocatori
- [x] Mappa Tharsis: piazzamento di oceani, città e foreste, bonus, punti delle città
- [x] Traguardi e riconoscimenti (mappa Tharsis)
- [x] Importazione automatica delle carte: **tutte** (215 carte progetto e 35 preludi)
- [x] Le 17 corporazioni di base, Corporate Era e Prelude, con i loro poteri
- [x] Preparazione vera: scelta di corporazione, preludi e carte iniziali
- [x] Carte che piazzano oceani, città e foreste "normali"
- [x] Tessere speciali (Capital, Mohole Area, Lava Flows...) e piazzamenti particolari
      (vulcani, città isolate, Noctis City, Ganymede e Phobos fuori da Marte)
- [x] Carte blu con effetti permanenti (sconti, metalli, requisiti, effetti a scatto)
- [x] Risorse sulle carte e punti vittoria variabili
- [x] Attacchi agli avversari (togliere piante, ridurre produzioni, rubare) e protezioni
- [x] Carte con scelte (Imported Hydrogen, Large Convoy, Artificial Photosynthesis...),
      risorse su altre carte (Imported Nitrogen...), "guarda N carte e tienine K",
      effetti con scelta (Viral Enhancers, Mars University, Olympus Conference)
- [x] Carte "di potenziale" con effetti variabili (Satellites, Insects, Toll Station...),
      tag jolly, effetti sulla carta successiva (Indentured Workers, Special Design),
      Land Claim, Robotic Workforce, Insulation, Eccentric Sponsor, Ecology Experts
- [x] Draft nella fase di ricerca (predefinito; `--senza-draft` per toglierlo)
- [x] Acquisto delle carte come al tavolo: le 10 carte iniziali (e le 4 di ogni
      generazione) si guardano tutte insieme e si decide in un colpo solo quali comprare
- [x] Vendita di brevetti
- [x] Scelta del pagamento: con acciaio e titanio oppure tenendoli (per esempio per Miner)
- [x] Azioni delle carte blu (una volta per generazione), comprese Restricted Area e Industrial Center
- [x] Bot a regole (batte il bot casuale nel 100% delle partite): difende i riconoscimenti
      Miner e Thermalist a fine partita, vende brevetti quando serve e all'ultima generazione; aspetta a giocare
      le carte che mettono animali e microbi se in mano ha un buon bersaglio
      (parametri `combo_patience` e `combo_hope` di RuleBot) e quelle "di potenziale"
      finché più avanti renderanno chiaramente di più (`potential_patience`)
- [x] IA che "pensa avanti" (MCTS: `tm_sim/mcts.py`), più forte del bot a regole
- [x] Statistiche su carte, preludi e corporazioni (prima versione: correlazioni)
- [x] Simulazioni in parallelo su più core (sempre 2 core lasciati liberi)
- [x] Statistiche che separano l'effetto della carta dal contesto (regressione: `learn.py`)
- [x] Simulazioni a round che si passano le stime sulle carte: il bot corregge i suoi errori
- [x] Lezioni da un giocatore umano (`insegna.py`): accoppiate forti messe alla prova da `learn.py`

Il resoconto dell'importazione è in [`tools/import_report.md`](tools/import_report.md)
(le uniche "escluse" sono le corporazioni, scritte a mano in `tm_sim/corporations.py`).

## Installazione

```bash
git clone https://github.com/mcouquetes/terraforming-mars-ai.git
cd terraforming-mars-ai
python -m venv .venv
source .venv/bin/activate      # su Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

Serve Python 3.10 o più recente; l'unica libreria esterna è NumPy (più pytest per i test).

## Uso

```bash
python play.py 3                     # gioca dal terminale contro 2 bot
python play.py 2 standard            # varianti: principiante, standard, prelude
python simulate.py 1000 5            # 1000 partite tra 5 bot a regole, con statistiche
python simulate.py 1000 2 standard   # varianti: principiante, standard, prelude
python simulate.py 10000 --processi 4   # quanti core usare (predefinito: tutti meno 2)
python simulate.py 1000 3 --senza-draft   # il draft è predefinito ovunque: così lo togli
python play.py 3 prelude regole senza-draft   # ...anche nel gioco da terminale
python simulate.py --help            # tutte le opzioni (tipo di bot, scelta corporazioni...)
python learn.py --round 5 --partite 3000   # potenza delle carte, imparata a round
python insegna.py                    # insegna al bot le accoppiate forti (20 mani iniziali)
python tools/ab_test.py 2000 --a potential_patience=1.2   # test A/B: una modifica aiuta?
python play.py 2 prelude mcts        # gioca contro il bot MCTS (il più forte, più lento)
```

## Le statistiche

`simulate.py` stampa, alla fine, le classifiche di corporazioni, preludi e carte
progetto e salva i dati completi nella cartella `risultati/`:

- `carte.csv`, `preludi.csv`, `corporazioni.csv`: una riga per elemento, con
  quante volte è stato offerto, comprato e giocato, la % di vittorie di chi l'ha
  giocato, il **vantaggio** (rispetto alla % attesa), il **margine** di errore,
  la generazione media e la % di vittorie di chi l'ha comprato senza giocarlo;
- `giocatori.csv`: i dati grezzi, una riga per giocatore per partita.

Sono **correlazioni**: una carta giocata soprattutto da chi è già in vantaggio
sembra più forte di quanto è. Il confronto con "comprata ma non giocata" aiuta
a riconoscere questi casi.

Le partite si giocano **in parallelo** su tutti i core del processore tranne 2
(che restano liberi per usare il computer): con 8 core, 6 partite alla volta.
I risultati sono identici a quelli su un core solo, solo più veloci.

## La potenza delle carte (learn.py)

Le percentuali di vittoria di `simulate.py` sono correlazioni: una carta giocata
soprattutto da chi è già in vantaggio sembra forte anche se non lo è.
`learn.py` fa un passo in più:

1. **Regressione** (`tm_sim/card_power.py`): per ogni carta stima quanti punti
   vale *a parità di contesto* (le altre carte giocate, la corporazione, il posto).
   Il risultato è la **potenza**: "+3" = vale 3 punti più di una carta media.
2. **Round che si parlano**: dopo ogni round confronta i punti che il bot si
   aspettava da ogni carta con quelli ottenuti davvero. Le **correzioni** passano
   ai bot del round dopo, che sopravvalutano e sottovalutano meno le carte.
3. **Verifica**: dopo ogni round, un test A/B a specchio misura se il bot con le
   correzioni batte quello di base.

I risultati di ogni round sono in `risultati/apprendimento/G_giocatori/round_N/`
(`potenza_carte.csv` e `correzioni.json`).

**Il bot continua a imparare.** Ogni volta che lanci `learn.py` riparte da dove era
arrivato per quel numero di giocatori (la prima volta, dalle correzioni in `dati/`),
e i round continuano la numerazione. Ciò che sapeva fa da punto di partenza: le carte
viste poche volte nelle partite nuove tengono la stima di prima. `--da-zero`
ricomincia dal bot di base. A un numero di giocatori mai provato parte dalle
correzioni del numero più vicino.

**Gli altri programmi usano il bot istruito solo se glielo chiedi**, così il bot di
base resta un riferimento fisso per i confronti:

```bash
python simulate.py 1000 2 --correzioni ultime     # statistiche con il bot che ha imparato
python play.py 2 prelude imparato                 # gioca contro il bot che ha imparato
python tools/ab_test.py 2000 --a card_power=ultime   # quanto è più forte del bot di base?
```

**Velocità.** Una partita di apprendimento dura circa 115 ms per core (prima ~200):
nelle simulazioni il motore non ricontrolla la legalità di mosse scelte dalla lista
delle mosse legali appena calcolata (`apply(..., check=False)`); le ipotesi "e se
comprassi queste carte?" copiano la partita senza la mappa; i tag in gioco si
ricontano solo quando entra in gioco una carta nuova. Le ottimizzazioni non cambiano
nessuna decisione: 40 partite di controllo danno risultati identici prima e dopo.
La regressione di fine round pesa poco (circa 20 secondi con 100.000 partite).

**Esplorazione (`--esplorazione`).** Con il campionamento di Thompson, in ogni partita
di allenamento il bot aggiunge a ogni correzione un "dubbio" casuale grande quanto la
sua incertezza, così prova anche le carte che conosce poco. Misurato (3 round da 2000
partite da zero, poi 4000 partite a specchio contro lo stesso allenamento senza
esplorazione): le carte meno viste ricevono il 30% di dati in più, ma il bot non
diventa più forte (esplorazione 1: −1,00 ± 0,41 punti; 0,3: −0,18 ± 0,41). Una carta
comprata "per curiosità" spesso si gioca nel momento sbagliato, e la regressione la
scambia per debole. Per questo è spenta di default (0).

"ultime" = le correzioni più recenti per quel numero di giocatori (o del più vicino).
Il draft è predefinito: l'apprendimento con il draft si salva in
`risultati/apprendimento/draft/`, quello senza (`--senza-draft`) in `risultati/apprendimento/`.
Con `--potenziale 0.4` i bot giocano 60/40 (valore effettivo/potenziale) e l'apprendimento,
salvato in `risultati/apprendimento/potenziale_0.4/`, impara carta per carta quanto di quel
potenziale si realizza davvero. Il file di correzioni ricorda il peso con cui è stato
imparato, e il bot che lo carica usa lo stesso peso.

### Risultati con il draft (2 giocatori, variante Prelude) — quelli predefiniti

> **Da aggiornare.** Questi risultati (e le correzioni in `dati/`) sono stati
> calcolati prima che l'acquisto delle carte diventasse "tutte insieme": verranno
> rifatti con un nuovo allenamento (`learn.py --da-zero`).

5 round da 3000 partite, partendo dalle correzioni senza draft. Registro completo in
[`dati/draft/apprendimento_2_giocatori.txt`](dati/draft/apprendimento_2_giocatori.txt),
classifica in [`dati/draft/potenza_carte_2_giocatori.csv`](dati/draft/potenza_carte_2_giocatori.csv).

| Round | Bot con le correzioni contro bot di base |
|---|---|
| 1 | +10,52 ± 0,99 punti a partita (vince il 74,6%) |
| 2 | +10,93 ± 1,01 |
| 3 | +11,91 ± 0,90 (77,0%) |
| 4 | +11,33 ± 0,91 |
| 5 | +10,92 ± 1,01 |

Con il draft saper valutare le carte conta il doppio: prendi la migliore e la togli
all'avversario. Lo stesso apprendimento con `--potenziale 0.4` (60/40) arriva a
+9,00 ± 1,01 contro il bot di base, ma contro il bot che ha imparato senza potenziale
perde: −1,46 ± 0,47 punti a partita (3000 partite a specchio). File in `dati/potenziale_0.4/draft/`.

### Primi risultati senza draft (2 giocatori, variante Prelude)

5 round da 3000 partite (`python learn.py --round 5 --partite 3000 --verifica 500`).
Il registro completo è in [`dati/apprendimento_2_giocatori.txt`](dati/apprendimento_2_giocatori.txt).

| Round | Bot con le correzioni contro bot di base |
|---|---|
| 1 | +0,99 ± 0,83 punti a partita |
| 2 | +3,00 ± 0,91 |
| 3 | +4,26 ± 0,86 |
| 4 | +4,13 ± 0,89 |
| 5 | +5,58 ± 0,88 (vince il 64,5% delle partite) |

Le correzioni imparate a 2 giocatori (senza draft) funzionano anche a 3: +3,92 ± 0,46 punti,
48,6% di vittorie (la parte "giusta" sarebbe il 33,3%).

La classifica completa di carte, preludi e corporazioni è in
[`dati/potenza_carte_2_giocatori.csv`](dati/potenza_carte_2_giocatori.csv), le
correzioni in [`dati/correzioni_2_giocatori.json`](dati/correzioni_2_giocatori.json):

```python
from tm_sim.bots import RuleBot
bot = RuleBot(card_power="dati/correzioni_2_giocatori.json")
```

## Valore effettivo e potenziale delle carte

Ogni carta ha due stime: il **valore effettivo** (ipotesi realistiche) e il
**potenziale**, cioè quanto può dare se ci costruisci intorno (più carte giocate dopo
uno sconto, azioni blu usate ogni generazione, più tag in arrivo, un buon bersaglio
per gli animali). Con `RuleBot(potential_weight=0.4)` il bot usa 60% valore effettivo
+ 40% potenziale; da riga di comando: `tools/ab_test.py --a potential_weight=0.4`.

Misurato contro il bot con solo il valore effettivo (3000 partite a specchio ciascuno):

| Valore effettivo / potenziale | Scarto di punti a partita |
|---|---|
| 80 / 20 | −1,81 ± 0,42 |
| 60 / 40 | −3,49 ± 0,48 |
| 40 / 60 | −4,11 ± 0,47 |

Per ora il potenziale peggiora il bot: le carte "motore" il bot le sopravvaluta già
(lo conferma `learn.py`), e dar loro più peso gliele fa comprare senza saperle
sfruttare. Per questo il peso predefinito è 0, e l'opzione resta disponibile.

## I test A/B (tools/ab_test.py)

Per sapere se una modifica rende il bot più forte: due versioni del bot (A e B)
giocano partite **a specchio** (la stessa distribuzione di carte giocata con A in
ogni posto, così la fortuna si annulla), e si misura lo **scarto di punti** con il
suo margine di errore. Le opzioni dei bot si danno da riga di comando, per esempio
`--a sell_patents=False`.

## Le tue lezioni: accoppiate forti (insegna.py)

Le simulazioni imparano bene quanto vale ogni carta *da sola*; le combinazioni
sono più difficili da scoprire, perché una coppia precisa capita raramente nella
stessa mano. Qui entra in gioco l'esperienza di un giocatore umano:

```bash
python insegna.py              # 20 mani iniziali: scegli corporazione, preludi e carte
python insegna.py --elenco     # le lezioni salvate e le accoppiate da verificare
python learn.py                # mette alla prova le tue accoppiate
```

Per ogni mano vedi 2 corporazioni (C1, C2), 4 preludi (P1-P4) e 10 carte, scegli
cosa faresti, vedi cosa avrebbe fatto il bot e indichi le **accoppiate** che ti
hanno guidato (per esempio `C1+3 3+7 P2+5`). Se non ne indichi, il programma ne
deduce alcune: le carte che compri tu e il bot no, insieme alla tua corporazione.
Le lezioni si salvano in `risultati/insegnamenti.json` dopo ogni mano.

`learn.py` tratta ogni accoppiata come un'**ipotesi da verificare**:

1. il bot parte fidandosi di te (bonus iniziale di 3 PV, 1,5 per quelle dedotte),
   così compra e gioca davvero l'accoppiata;
2. nel 30% dei casi (`--prova-coppie`) un giocatore riceve apposta un'accoppiata
   nella mano iniziale: senza questo aiuto capiterebbe troppo di rado;
3. la regressione misura la **sinergia**: quanti punti in più fanno le due metà
   giocate insieme, oltre a quanto vale ciascuna da sola. Con pochi dati il bonus
   resta vicino alla tua fiducia, con tanti dati decidono le partite.

Dopo ogni round una tabella dice, per ogni accoppiata, quante volte è stata
giocata insieme, la sinergia misurata con il suo margine e il verdetto:
CONFERMATA, SMENTITA o da verificare. Il bot usa il bonus imparato quando valuta
le carte: per intero se l'altra metà è già giocata (o è la tua corporazione o
un tuo preludio), per metà se è solo in mano o tra le carte che sta comprando.

## L'acquisto delle carte: tutte insieme

Come al tavolo, le carte pescate (10 a inizio partita, 4 a ogni generazione dopo
il draft) si guardano **tutte insieme** e si decide in un colpo solo quali
comprare: per il motore è un'unica mossa, "compra queste carte", scelta tra tutti
i gruppi che ci si può permettere (fino a 1024 con 10 carte). Dal terminale
scrivi i numeri delle carte che vuoi, per esempio `2 5 7`; prima di scegliere la
corporazione vedi già preludi e carte.

Il bot a regole sceglie il gruppo così: valuta ogni carta come se in mano ci
fossero anche le altre (Fish vale di più insieme a Large Convoy), le ordina e
tiene le migliori finché convengono, tenendo conto dei soldi e della mano già
piena, poi ricalcola con il gruppo scelto finché la scelta è stabile. Se i soldi
non bastano restano fuori le peggiori, non le ultime arrivate. Nel draft ogni
carta si valuta insieme a quelle già scelte nei giri precedenti.

Opzioni di RuleBot per i test A/B: `joint_buying=False` (il vecchio metodo, una
carta alla volta) e `setup_package=True` (scegliere la corporazione pensando
anche a preludi e carte: per ora non aiuta, −0,23 ± 0,37 punti, quindi è spenta).

**Dopo questa modifica conviene ri-allenare** il bot (`learn.py --da-zero`, vedi
sotto): le correzioni in `dati/` sono state imparate con il vecchio acquisto.

## Il bot MCTS (tm_sim/mcts.py)

Il bot a regole sceglie la mossa che *sembra* migliore secondo le sue stime.
Il bot MCTS invece le **prova**: per ogni decisione importante della fase azioni
prende le 5 mosse migliori secondo il bot a regole e, per ognuna, gioca il
seguito fino alla fine della generazione in tante simulazioni veloci (30 in tutto).
Sceglie la mossa che in media lascia la posizione migliore: i suoi punti più
risorse, produzioni, TR e carte convertiti in punti, meno quelli dell'avversario
più forte.

Due accorgimenti lo rendono onesto e preciso:

- **niente trucchi**: prima di ogni simulazione rimescola tutto ciò che non può
  vedere (il mazzo e le mani degli avversari), quindi gioca "con carte plausibili";
- **confronto alla pari**: tutte le mosse candidate si provano sugli *stessi*
  rimescolamenti, come le partite a specchio dei test A/B.

Risultati (test A/B a specchio, 2 giocatori, Prelude, con draft):

| Confronto | Scarto di punti | Vittorie |
|---|---|---|
| MCTS contro il bot a regole di base (80 partite) | **+4.83 ± 2.65** | 58.8% |
| MCTS con le correzioni imparate contro il bot che ha imparato (320 partite) | **+2.1 ± 1.5** | 55.8% |

Per ogni simulazione la partita va copiata: la copia è scritta a mano
(`Game.clone`), copia solo ciò che può cambiare e condivide carte e forma della
mappa, ed è 7 volte più veloce della copia generica di Python. Una partita contro
MCTS dura così circa 9 secondi per core (prima ~20-30). Resta comunque molto più
lento del bot a regole, per questo si usa per giocare e per test A/B da poche centinaia di
partite, non per le statistiche da milioni di partite.

Con `--a smart=True` le simulazioni si distribuiscono secondo l'"intuito" del bot a
regole: più simulazioni alle mosse che stima forti, scarto progressivo di quelle
chiaramente peggiori, stop quando le rimaste sono praticamente uguali. Misurato
faccia a faccia contro la divisione in parti uguali: −0,58 ± 1,55 punti (nessun
vantaggio), quindi è spento di default. I risultati della tabella sono stati
misurati prima dell'acquisto "tutto insieme": vanno rifatti dopo il ri-allenamento.

```bash
python play.py 2 prelude mcts                                   # gioca contro MCTS
python tools/ab_test.py 200 --a-bot mcts                        # MCTS contro le regole
python tools/ab_test.py 200 --a-bot mcts --a card_power=ultime --b card_power=ultime
python tools/ab_test.py 100 --a-bot mcts --a simulations=60 candidates=6   # più "riflessivo"
python simulate.py 200 2 prelude mcts                           # statistiche giocate da MCTS
```

## Aggiornare le carte

I dati delle carte vengono estratti dal progetto open source
[terraforming-mars/terraforming-mars](https://github.com/terraforming-mars/terraforming-mars):

```bash
git clone --depth 1 https://github.com/terraforming-mars/terraforming-mars.git ../tm-source
python tools/import_cards.py ../tm-source
```

Lo script rigenera `tm_sim/card_data.py` e `tools/import_report.md`.

## Struttura

```
tm_sim/
  state.py       stato della partita: giocatori, risorse, pianeta
  actions.py     descrizione delle azioni possibili e loro categorie
  cards.py       com'è fatta una carta e quando si può giocare
  card_data.py   le carte importate (file generato, non modificare)
  card_list.py   il mazzo usato dal motore
  corporations.py le corporazioni e i loro poteri
  card_effects.py gli effetti a scatto delle carte blu e due azioni speciali
  milestones.py  traguardi e riconoscimenti
  board.py       la mappa: caselle esagonali, bonus, regole di piazzamento
  game.py        il motore: fasi, turni, azioni legali, esecuzione
  bots.py        i giocatori automatici (casuale e a regole)
  heuristics.py  le regole di valutazione del bot a regole
  stats.py       le statistiche raccolte durante le simulazioni
  parallel.py    il calcolo in parallelo (più partite insieme, una per core)
  card_power.py  la potenza delle carte al netto del contesto (regressione)
  mcts.py        il bot che prova le mosse con simulazioni (MCTS)
  teaching.py    lezioni dell'umano: accoppiate, fiducia iniziale, mani "truccate"
tools/
  import_cards.py   importazione delle carte dalla fonte open source
  import_report.md  carte escluse e motivo
  ab_test.py        confronto tra due versioni del bot
tests/           i test automatici (pytest)
play.py          gioca dal terminale contro i bot
simulate.py      fa giocare i bot tra loro e stampa statistiche
learn.py         simulazioni a round: potenza delle carte e correzioni per il bot
insegna.py       le tue lezioni: mani iniziali e accoppiate da mettere alla prova
```

## Licenza

Copyright © 2026 mcouquetes.

Questo programma è software libero: puoi ridistribuirlo e/o modificarlo secondo i
termini della **GNU General Public License** pubblicata dalla Free Software
Foundation, versione 3 o (a tua scelta) qualsiasi versione successiva. È distribuito
nella speranza che sia utile, ma SENZA ALCUNA GARANZIA. Il testo completo è nel
file [LICENSE](LICENSE).

In breve: chiunque può usarlo, studiarlo, modificarlo e ridistribuirlo, anche
modificato, purché lo faccia con la stessa licenza e rendendo disponibile il codice.

## Crediti

I dati numerici delle carte (costi, tag, requisiti, effetti) provengono dal
progetto open source
[terraforming-mars/terraforming-mars](https://github.com/terraforming-mars/terraforming-mars),
distribuito con licenza GPL-3.0. Terraforming Mars è un gioco di FryxGames.
