"""Importa i dati delle carte dal progetto open source di Terraforming Mars.

Fonte: https://github.com/terraforming-mars/terraforming-mars (licenza GPL-3.0)

Lo script NON copia codice: legge i file delle carte, ne estrae i dati
(costo, tag, requisiti, effetti) e genera due file:

    tm_sim/card_data.py        le carte che il nostro motore sa già giocare
    tools/import_report.md     le carte escluse, con il motivo

Uso:
    1. Scarica il progetto (con git oppure "Code → Download ZIP" su GitHub)
    2. python tools/import_cards.py CARTELLA_DEL_PROGETTO

Espansioni importate: gioco base, Corporate Era, Prelude.

COME FUNZIONA
Le carte sono scritte in TypeScript, così:

    super({
      type: CardType.AUTOMATED,
      tags: [Tag.PLANT],
      cost: 13,
      behavior: { production: {plants: 3} },
      ...
    })

Il testo tra le graffe è quasi un dizionario Python. Lo leggiamo con un
piccolo "parser": prima lo spezzettiamo in token (parole, numeri, simboli),
poi ricostruiamo dizionari e liste. Quello che non capiamo (funzioni,
calcoli) lo segniamo come "non leggibile" e la carta va nel report.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:      # per poter importare tm_sim anche da qui
    sys.path.insert(0, str(PROJECT_ROOT))

from tm_sim.card_effects import CARD_TRIGGERS  # noqa: E402  (dopo aver sistemato sys.path)

OUTPUT_DATA = PROJECT_ROOT / "tm_sim" / "card_data.py"
OUTPUT_REPORT = PROJECT_ROOT / "tools" / "import_report.md"

# (file del manifesto, nome del manifesto, nome dell'espansione per noi)
MANIFESTS = [
    ("src/server/cards/StandardCardManifests.ts", "BASE_CARD_MANIFEST", "base"),
    ("src/server/cards/StandardCardManifests.ts", "CORP_ERA_CARD_MANIFEST", "corporate_era"),
    ("src/server/cards/prelude/PreludeCardManifest.ts", "PRELUDE_CARD_MANIFEST", "prelude"),
]
SECTIONS = {"projectCards": "progetto", "corporationCards": "corporazione", "preludeCards": "preludio"}

# Nomi usati dalla fonte -> nomi nel nostro codice
TAGS = {"BUILDING": "BUILDING", "SPACE": "SPACE", "SCIENCE": "SCIENCE", "POWER": "POWER",
        "EARTH": "EARTH", "JOVIAN": "JOVIAN", "PLANT": "PLANT", "MICROBE": "MICROBE",
        "ANIMAL": "ANIMAL", "CITY": "CITY", "EVENT": "EVENT", "WILD": "WILD"}
# Risorse scritte come Resource.PLANTS nella fonte
RESOURCE_REFS = {"MEGACREDITS": "MEGACREDITS", "STEEL": "STEEL", "TITANIUM": "TITANIUM",
                 "PLANTS": "PLANTS", "ENERGY": "ENERGY", "HEAT": "HEAT"}
RESOURCES = {"megacredits": "MEGACREDITS", "steel": "STEEL", "titanium": "TITANIUM",
             "plants": "PLANTS", "energy": "ENERGY", "heat": "HEAT"}
GLOBALS = {"temperature": "temperature_steps", "oxygen": "oxygen_steps"}
PARAMETER_REQUIREMENTS = {"temperature", "oxygen", "oceans"}
TILE_EFFECTS = {"ocean": "OCEAN", "city": "CITY", "greenery": "GREENERY"}
SPECIAL_TILE_TYPES = {"CAPITAL", "COMMERCIAL_DISTRICT", "ECOLOGICAL_ZONE", "LAVA_FLOWS",
                      "MINING_AREA", "MINING_RIGHTS", "MOHOLE_AREA", "NATURAL_PRESERVE",
                      "NUCLEAR_ZONE", "RESTRICTED_AREA", "INDUSTRIAL_CENTER", "CLAIM"}
# "on: ..." nella fonte (e nelle nostre correzioni) -> regola di piazzamento
ON_RULES = {"land": "LAND", "ocean": "OCEAN_SPACE", "isolated": "ISOLATED", "volcanic": "VOLCANIC",
            "city": "CITY_RULES", "next_to_two_cities": "NEXT_TO_TWO_CITIES",
            "next_to_greenery": "NEXT_TO_GREENERY", "next_to_city": "NEXT_TO_CITY",
            "metal_bonus": "METAL_BONUS",
            "metal_bonus_next_to_own": "METAL_BONUS_NEXT_TO_OWN"}
# "space: SpaceName...." -> caselle riservate
SPACE_RULES = {"NOCTIS_CITY": "NOCTIS", "GANYMEDE_COLONY": "GANYMEDE",
               "PHOBOS_SPACE_HAVEN": "PHOBOS"}
TILE_OPTION_KEYS = {"type", "count", "on", "space", "title", "adjacencyBonus"}
# Punti "per ogni X accanto a questa tessera": li calcola la mappa (board.py).
TILE_ADJACENCY_VP = {"oceans": "CAPITAL", "cities": "COMMERCIAL_DISTRICT"}
# Carte che sembrano semplici ma la cui regola vive altrove nella fonte.
NOT_YET_SUPPORTED: dict[str, str] = {}
# (Protected Habitats era qui finché non c'erano gli attacchi: la sua protezione
# è in Game.is_protected.)
CARD_RESOURCES = {"ANIMAL": "ANIMAL", "MICROBE": "MICROBE", "SCIENCE": "SCIENCE", "FIGHTER": "FIGHTER"}

# Preludi che "costano" M€: nella fonte il pagamento è scritto in codice,
# ma è l'unico codice che hanno, quindi li gestiamo noi come risorse negative.
# Aquifer Turbines piazza anche un oceano (sempre nel suo codice).
PAID_PRELUDES_EXTRA_TILES = {
    "Aquifer Turbines": ["TileType.OCEAN"],
    "Huge Asteroid": [],
    "Galilean Mining": [],
    "Business Empire": [],
}


# ---------------------------------------------------------------------------
# 1. Tokenizer: spezza il testo in pezzi elementari
# ---------------------------------------------------------------------------

TOKEN_RE = re.compile(r"""
    (?P<space>\s+|//[^\n]*|/\*.*?\*/)              # spazi e commenti: ignorati
  | (?P<string>'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"|`(?:\\.|[^`\\])*`)
  | (?P<number>\d+(?:\.\d+)?)
  | (?P<name>[A-Za-z_$][\w$]*)
  | (?P<punct>=>|\.\.\.|[{}\[\]():,.\-?=<>!&|+*/;%])
""", re.VERBOSE | re.DOTALL)


def tokenize(text: str) -> list[tuple[str, str]]:
    tokens = []
    pos = 0
    while pos < len(text):
        match = TOKEN_RE.match(text, pos)
        if not match:
            pos += 1          # carattere strano: lo saltiamo
            continue
        kind = match.lastgroup
        if kind != "space":
            tokens.append((kind, match.group()))
        pos = match.end()
    return tokens


# ---------------------------------------------------------------------------
# 2. Parser: ricostruisce dizionari, liste, numeri e riferimenti
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Ref:
    """Un riferimento come Tag.PLANT o CardType.EVENT."""
    path: str


@dataclass(frozen=True)
class Unreadable:
    """Qualcosa che il parser non sa interpretare (una funzione, un calcolo)."""
    text: str


class Parser:
    OPEN = {"{": "}", "[": "]", "(": ")"}

    def __init__(self, tokens: list[tuple[str, str]]):
        self.tokens = tokens
        self.i = 0

    def peek(self, offset: int = 0) -> str | None:
        j = self.i + offset
        return self.tokens[j][1] if j < len(self.tokens) else None

    def next(self) -> tuple[str, str]:
        token = self.tokens[self.i]
        self.i += 1
        return token

    def skip_value(self) -> Unreadable:
        """Salta un valore che non capiamo fino alla prossima virgola."""
        start, depth = self.i, 0
        while self.i < len(self.tokens):
            tok = self.peek()
            if tok in self.OPEN:
                depth += 1
            elif tok in ("}", "]", ")"):
                if depth == 0:
                    break
                depth -= 1
            elif tok == "," and depth == 0:
                break
            self.i += 1
        return Unreadable(" ".join(t for _, t in self.tokens[start:self.i]))

    def value(self):
        start = self.i
        tok = self.peek()
        if tok == "{":
            result = self.obj()
        elif tok == "[":
            result = self.array()
        elif tok == "-" and self.tokens[self.i + 1][0] == "number":
            self.next()
            result = -self.number(self.next()[1])
        elif self.tokens[self.i][0] == "number":
            result = self.number(self.next()[1])
        elif self.tokens[self.i][0] == "string":
            result = self.next()[1][1:-1]
        elif self.tokens[self.i][0] == "name":
            parts = [self.next()[1]]
            while self.peek() == "." and self.peek(1) is not None:
                self.next()
                parts.append(self.next()[1])
            if self.peek() == "(":                      # chiamata di funzione
                self.i = start
                return self.skip_value()
            name = ".".join(parts)
            result = {"true": True, "false": False, "undefined": None}.get(name, Ref(name))
        else:
            return self.skip_value()
        # Se dopo il valore c'è un operatore (es. 2 * x), non è un valore semplice.
        if self.peek() not in (",", "}", "]", ")", None):
            self.i = start
            return self.skip_value()
        return result

    @staticmethod
    def number(text: str) -> int | float:
        return float(text) if "." in text else int(text)

    def obj(self) -> dict:
        self.next()  # {
        result = {}
        while self.peek() != "}":
            if self.peek() == "...":                  # {...altro}: non lo gestiamo
                self.next()
                result["..."] = self.skip_value()
            else:
                key = self.next()[1].strip("'\"")
                if self.peek() == ":":
                    self.next()
                    result[key] = self.value()
                elif self.peek() in (",", "}"):       # forma abbreviata {max}
                    result[key] = True
                else:
                    result[key] = self.skip_value()
            if self.peek() == ",":
                self.next()
        self.next()  # }
        return result

    def array(self) -> list:
        self.next()  # [
        result = []
        while self.peek() != "]":
            result.append(self.value())
            if self.peek() == ",":
                self.next()
        self.next()  # ]
        return result


def extract_super_object(source: str) -> dict | None:
    """Trova super({...}) nel file e lo trasforma in un dizionario."""
    start = source.find("super({")
    if start < 0:
        return None
    tokens = tokenize(source[start + len("super("):])
    return Parser(tokens).obj()


def has_custom_code(source: str) -> bool:
    """La carta ha metodi oltre al costruttore? Allora ha effetti scritti in codice."""
    # Esempi da riconoscere:  "public override bespokePlay(player) {"
    #                          "protected getCardDiscount(player) {"
    modifiers = r"(?:(?:public|protected|private|override|static|async|get|set)\s+)+"
    return re.search(r"^\s+" + modifiers + r"\w+\s*[(<]", source, re.MULTILINE) is not None


# ---------------------------------------------------------------------------
# 3. Lettura dei manifesti e dei file delle carte
# ---------------------------------------------------------------------------

def read_card_names(repo: Path) -> dict[str, str]:
    """CardName.TREES -> 'Trees'"""
    text = (repo / "src/common/cards/CardName.ts").read_text(encoding="utf-8")
    names = re.findall(r"^\s*(\w+)\s*=\s*'((?:\\.|[^'])*)'", text, re.MULTILINE)
    # Nella fonte l'apostrofo è scritto \' (es. 'Inventors\' Guild'): lo togliamo.
    return {enum: name.replace("\\'", "'") for enum, name in names}


def read_manifest(repo: Path, file: str, const: str) -> dict[str, list[tuple[str, str]]]:
    """Restituisce {sezione: [(CardName, NomeClasse), ...]}."""
    text = (repo / file).read_text(encoding="utf-8")
    start = text.index(f"export const {const}")
    body = text[start:]
    end = body.index("\n});")
    body = body[:end]
    result: dict[str, list[tuple[str, str]]] = {}
    for section in SECTIONS:
        match = re.search(section + r":\s*\{(.*?)\n\s*\},", body + "\n  },", re.DOTALL)
        if match:
            result[section] = re.findall(
                r"\[CardName\.(\w+)\]:\s*\{\s*Factory:\s*(\w+)", match.group(1))
    return result


def read_manifest_imports(repo: Path, file: str) -> dict[str, Path]:
    """Da quale file il manifesto importa ogni classe.

    Serve perché alcune carte esistono in più versioni con lo stesso nome
    (per esempio Hackers del gioco base e quella dell'espansione Underworld):
    la versione giusta è quella che il manifesto importa.
    """
    manifest = repo / file
    imports = {}
    for names, rel in re.findall(r"import\s*\{([^}]*)\}\s*from\s*'([^']+)'",
                                 manifest.read_text(encoding="utf-8")):
        path = (manifest.parent / (rel + ".ts")).resolve()
        for name in names.split(","):
            imports[name.strip()] = path
    return imports


def find_class_files(repo: Path) -> dict[str, Path]:
    """NomeClasse -> file .ts che la definisce."""
    files = {}
    for path in (repo / "src/server/cards").rglob("*.ts"):
        for name in re.findall(r"export class (\w+)", path.read_text(encoding="utf-8")):
            files.setdefault(name, path)
    return files


# ---------------------------------------------------------------------------
# 4. Traduzione nel nostro formato
# ---------------------------------------------------------------------------

@dataclass
class ImportedCard:
    name: str
    expansion: str
    section: str
    reasons: list[str] = field(default_factory=list)
    code: str = ""          # riga Python per card_data.py (se supportata)


# ---------------------------------------------------------------------------
# CORREZIONI A MANO
# Alcune carte nella fonte usano codice al posto dei dati. Qui scriviamo, come
# dati, quello che fa il loro codice. Vengono "fuse" con i dati letti dalla
# fonte (per Mining Area e Mining Rights, che la fonte scrive in modo diverso,
# li diamo per intero). Ogni correzione è verificata leggendo il codice originale.
PATCHES: dict[str, dict] = {
    # Città sulla casella riservata; la produzione vera è -1 energia +3 M€.
    "Noctis City": {"behavior": {"production": {"energy": -1, "megacredits": 3},
                                 "city": {"space": Ref("SpaceName.NOCTIS_CITY")}}},
    # Città accanto ad almeno 2 città; -1 energia +2 M€.
    "Urbanized Area": {"behavior": {"production": {"energy": -1, "megacredits": 2},
                                    "city": {"on": "next_to_two_cities"}}},
    # Città su un vulcano (la produzione è già nei dati).
    "Lava Tube Settlement": {"behavior": {"city": {"on": "volcanic"}}},
    # Città normale; -1 energia -2 M€ (il resto è un effetto in card_effects.py).
    "Immigrant City": {"behavior": {"production": {"energy": -1, "megacredits": -2},
                                    "city": {}}},
    # Il suo codice dice solo "si può giocare anche a oceani finiti", come facciamo già.
    "Artificial Lake": {},
    "Mining Rights": {"type": Ref("CardType.AUTOMATED"), "tags": [Ref("Tag.BUILDING")],
                      "cost": 9, "behavior": {"tile": {"type": Ref("TileType.MINING_RIGHTS"),
                                                       "on": "metal_bonus"}}},
    "Mining Area": {"type": Ref("CardType.AUTOMATED"), "tags": [Ref("Tag.BUILDING")],
                    "cost": 4, "behavior": {"tile": {"type": Ref("TileType.MINING_AREA"),
                                                     "on": "metal_bonus_next_to_own"}}},
    # Tessera accanto a una foresta (gli animali sono in card_effects.py).
    "Ecological Zone": {"behavior": {"tile": {"type": Ref("TileType.ECOLOGICAL_ZONE"),
                                              "on": "next_to_greenery"}}},

    # --- Attacchi scritti in codice nella fonte ---------------------------------
    # "Riduci la produzione di qualcuno e alza la tua": la tua sale sempre, perché
    # il bersaglio deve avere quella produzione (al limite sei tu stesso: saldo zero).
    "Hackers": {"behavior": {"decreaseAnyProduction": {"type": Ref("Resource.MEGACREDITS"),
                                                       "count": 2}}},
    "Energy Tapping": {"behavior": {"production": {"energy": 1},
                                    "decreaseAnyProduction": {"type": Ref("Resource.ENERGY"),
                                                              "count": 1}}},
    "Power Supply Consortium": {"behavior": {"production": {"energy": 1},
                                             "decreaseAnyProduction": {
                                                 "type": Ref("Resource.ENERGY"), "count": 1}}},
    "Asteroid Mining Consortium": {"behavior": {"production": {"titanium": 1},
                                                "decreaseAnyProduction": {
                                                    "type": Ref("Resource.TITANIUM"), "count": 1}}},
    "Great Escarpment Consortium": {"behavior": {"production": {"steel": 1},
                                                 "decreaseAnyProduction": {
                                                     "type": Ref("Resource.STEEL"), "count": 1}}},
    # "Togli/ruba fino a N di una risorsa, a scelta tra più opzioni".
    "Hired Raiders": {"behavior": {"raid": {"steals": True,
                                            "options": [["STEEL", 2], ["MEGACREDITS", 3]]}}},
    "Sabotage": {"behavior": {"raid": {"steals": False,
                                       "options": [["TITANIUM", 3], ["STEEL", 4],
                                                   ["MEGACREDITS", 7]]}}},
    "Virus": {"behavior": {"raid": {"steals": False, "options": [["ANIMAL", 2], ["PLANTS", 5]]}}},
    # Oceano, poi "togli 4 M€ a chi ha una tessera accanto".
    "Flooding": {"behavior": {"ocean": {}, "floodRaid": 4}},

    # --- Azioni scritte in codice nella fonte -------------------------------------
    # "Guadagna 1 pianta, oppure aggiungi 2 microbi a un'ALTRA carta".
    "Extreme-Cold Fungus": {"action": {"or": {"behaviors": [
        {"stock": {"plants": 1}},
        {"addResourcesToAnyCard": {"type": Ref("CardResource.MICROBE"), "count": 2}}]}}},
    # Paga 1 M€ e scopri una carta (scritta a mano in card_effects.py); 3 PV con 1+ scienza.
    "Search For Life": {"action": {"spend": {"megacredits": 1}, "special": "search_for_life"},
                        "victoryPoints": 0, "vpIfAnyResource": 3},
    # Spendi X energia per X M€ (scritta a mano in card_effects.py).
    "Power Infrastructure": {"action": {"special": "power_infrastructure"}},
    # Il suo codice dice solo "si usa se l'ossigeno può ancora salire": lo controlla
    # già il motore (non permette azioni che non farebbero nulla).
    "Water Splitting Plant": {},
    # Tessera su terra accanto a una città (di chiunque).
    "Industrial Center": {"behavior": {"tile": {"type": Ref("TileType.INDUSTRIAL_CENTER"),
                                                "on": "next_to_city"}}},
    # Effetto scritto altrove nella fonte: i microbi qui valgono 2 M€ per le carte pianta.
    "Psychrophiles": {"resourcesAsPayment": {"tag": Ref("Tag.PLANT"), "value": 2}},

    # --- Carte con scelta scritte in codice nella fonte -----------------------------
    # Oceano, poi: 3 piante OPPURE 3 microbi su una tua carta OPPURE 2 animali.
    "Imported Hydrogen": {"behavior": {"or": {"behaviors": [
        {"stock": {"plants": 3}},
        {"addResourcesToAnyCard": {"type": Ref("CardResource.MICROBE"), "count": 3}},
        {"addResourcesToAnyCard": {"type": Ref("CardResource.ANIMAL"), "count": 2}}]}}},
    # Oceano, pesca 2, 2 PV, poi: 5 piante OPPURE 4 animali su una tua carta.
    "Large Convoy": {"behavior": {"or": {"behaviors": [
        {"stock": {"plants": 5}},
        {"addResourcesToAnyCard": {"type": Ref("CardResource.ANIMAL"), "count": 4}}]}}},
    # --- Carte "di potenziale" e altri effetti scritti in codice ----------------
    # La prossima carta che giochi in questa generazione costa 8 M€ in meno.
    "Indentured Workers": {"nextCardDiscount": 8},
    # Serve produzione di calore: scegli quanta trasformarne in produzione di M€.
    "Insulation": {"requirements": {"production": Ref("Resource.HEAT"), "count": 1},
                   "behavior": {"or": {"behaviors": [{"special": "insulation"}]}}},
    # Metti il tuo segnalino su una casella di terra: solo tu potrai piazzarci.
    "Land Claim": {"behavior": {"tile": {"type": Ref("TileType.CLAIM"), "on": "land"}}},
    # Perdi 1 (o 2) piante.
    "Moss": {"behavior": {"stock": {"plants": -1}}},
    "Nitrophilic Moss": {"behavior": {"stock": {"plants": -2}}},
    # +1 produzione di piante, +4 invece di +1 se hai almeno 3 tag pianta.
    "Nitrogen-Rich Asteroid": {"behavior": {
        "production": {"plants": 1},
        "extraProduction": {"plants": {"tag": Ref("Tag.PLANT"), "atLeast": 3, "step": 3}}}},
    # Copia la produzione di una tua carta edificio.
    "Robotic Workforce": {"behavior": {"or": {"behaviors": [{"special": "robotic_workforce"}]}}},
    # +1 TR per ogni tag gioviano (compreso il suo).
    "Terraforming Ganymede": {"behavior": {"trPerTag": Ref("Tag.JOVIAN")}},
    # Preludi: gioca subito una carta, con 25 M€ di sconto / ignorando i requisiti globali.
    "Eccentric Sponsor": {"nextCardDiscount": 25, "playCardNow": True},
    "Ecology Experts": {"nextCardLeeway": 50, "playCardNow": True},

    # Spendi 5 calore, poi: 4 piante OPPURE 2 animali su una tua carta.
    # (reserveUnits nella fonte serve solo per Helion: lo togliamo, None = cancella.)
    "Local Heat Trapping": {"reserveUnits": None, "behavior": {
        "stock": {"heat": -5},
        "or": {"behaviors": [
            {"stock": {"plants": 4}},
            {"addResourcesToAnyCard": {"type": Ref("CardResource.ANIMAL"), "count": 2}}]}}},
}


def apply_patch(data: dict | None, patch: dict) -> dict:
    """Fonde la correzione nei dati letti (i dizionari interni vengono uniti)."""
    result = dict(data or {})
    for key, value in patch.items():
        if value is None:                 # None nella correzione = togli il campo
            result.pop(key, None)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = apply_patch(result[key], value)
        else:
            result[key] = value
    return result



def tag_name(value) -> str | None:
    """Ref("Tag.EARTH") -> "EARTH" (se è un tag che conosciamo)."""
    if isinstance(value, Ref):
        name = value.path.split(".")[-1]
        return TAGS.get(name)
    return None


def parse_permanent_effects(data: dict, reasons: list[str]) -> list[str]:
    """Sconti, tolleranza sui requisiti e tipo di risorsa delle carte blu."""
    args: list[str] = []

    discounts = data.get("cardDiscount")
    if discounts is not None:
        # Nella fonte lo sconto vale per ogni tag, salvo per: 'card' (una volta per carta).
        entries = discounts if isinstance(discounts, list) else [discounts]
        per_tag, once = [], []
        for entry in entries:
            if not (isinstance(entry, dict) and isinstance(entry.get("amount"), int)
                    and set(entry) <= {"tag", "amount", "per"}
                    and entry.get("per", "tag") in ("tag", "card")):
                reasons.append("sconto non gestito")
                continue
            if "tag" in entry:
                tag = tag_name(entry["tag"])
                if tag is None:
                    reasons.append("sconto non gestito")
                    continue
                target = once if entry.get("per") == "card" else per_tag
                target.append(f"Tag.{tag}: {entry['amount']}")
            else:
                per_tag.append(f"None: {entry['amount']}")
        if per_tag:
            args.append("discounts={" + ", ".join(per_tag) + "}")
        if once:
            args.append("discounts_once={" + ", ".join(once) + "}")

    bonus = data.get("globalParameterRequirementBonus")
    if bonus is not None:
        if isinstance(bonus, dict) and set(bonus) == {"steps"} and isinstance(bonus["steps"], int):
            args.append(f"requirement_leeway={bonus['steps']}")
        elif (isinstance(bonus, dict) and set(bonus) == {"steps", "nextCardOnly"}
                and bonus["nextCardOnly"] is True):
            args.append(f"next_card_leeway={bonus['steps']}")      # Special Design
        else:
            reasons.append("tolleranza sui requisiti non gestita")

    resource = data.get("resourceType")
    if resource is not None:
        kind = resource.path.split(".")[-1] if isinstance(resource, Ref) else ""
        if kind in CARD_RESOURCES:
            args.append(f"resource_type=CardResource.{CARD_RESOURCES[kind]}")
        else:
            reasons.append(f"risorsa sulla carta non gestita: {kind}")
    return args


def parse_variable_vp(vp: dict, reasons: list[str]) -> list[str]:
    """Punti vittoria variabili: per risorse sulla carta, per tag, per città."""
    if "resourcesHere" in vp and set(vp) <= {"resourcesHere", "per", "each"}:
        return [f"resource_vp=({vp.get('each', 1)}, {vp.get('per', 1)})"]
    if set(vp) == {"tag"} and tag_name(vp["tag"]):
        return [f"vp_per_tag=Tag.{tag_name(vp['tag'])}"]
    if set(vp) == {"cities", "all", "per"} and vp["all"] is True and isinstance(vp["per"], int):
        return [f"vp_per_cities={vp['per']}"]
    reasons.append("punti vittoria speciali")
    return []


ACTION_KEYS = {"spend", "addResources", "stock", "production", "global", "tr", "ocean",
               "drawCard", "removeResourcesFromAnyCard", "addResourcesToAnyCard",
               "special", "title"}


def card_resource_name(value) -> str | None:
    """Ref("CardResource.MICROBE") -> "MICROBE" (se è una risorsa che conosciamo)."""
    if isinstance(value, Ref):
        return CARD_RESOURCES.get(value.path.split(".")[-1])
    return None


def scaled_code(value) -> str | None:
    """Una quantità variabile della fonte -> codice Scaled(...), o None se sconosciuta.

    {tag: Tag.SPACE}                    -> 1 per tag spazio
    {tag: Tag.BUILDING, per: 2}         -> 1 ogni 2 tag edificio
    {tag: Tag.SPACE, others: true}      -> 1 per tag spazio degli avversari
    {cities: {}}                        -> 1 per città in gioco
    {cities: {where: 'onmars'}}         -> 1 per città su Marte
    {eventsPlayed: true, all: true}     -> 1 per evento giocato da tutti
    {tag: Tag.PLANT, atLeast: 3, step: 3} -> 3 se hai almeno 3 tag pianta (correzione a mano)
    """
    if not isinstance(value, dict):
        return None
    if "tag" in value and tag_name(value["tag"]) and set(value) <= {"tag", "per", "others"}:
        what = "tag_others" if value.get("others") is True else "tag"
        per = value.get("per", 1)
        return f"Scaled({what!r}, Tag.{tag_name(value['tag'])}, per={per})"
    if "tag" in value and set(value) == {"tag", "atLeast", "step"}:
        return (f"Scaled('tag_at_least', Tag.{tag_name(value['tag'])}, "
                f"per={value['atLeast']}, step={value['step']})")
    if value == {"cities": {}}:
        return "Scaled('cities')"
    if value == {"cities": {"where": "onmars"}}:
        return "Scaled('cities_on_mars')"
    if value == {"eventsPlayed": True, "all": True}:
        return "Scaled('events')"
    return None


def add_to_cards_code(value) -> str | None:
    """addResourcesToAnyCard -> "((CardResource.MICROBE, 3), ...)", o None se non gestito.

    Tipo assente con min: 1 = "su una carta che ha già risorse" (CEO's Favorite Project).
    """
    entries = value if isinstance(value, list) else [value]
    parts = []
    for entry in entries:
        if not (isinstance(entry, dict) and isinstance(entry.get("count"), int)
                and set(entry) <= {"type", "count", "min", "mustHaveCard", "robotCards",
                                   "autoSelect"}):
            return None
        if "type" in entry:
            kind = card_resource_name(entry["type"])
            if kind is None:
                return None
            parts.append(f"(CardResource.{kind}, {entry['count']})")
        elif entry.get("min") == 1 and entry.get("mustHaveCard") is True:
            parts.append(f"(None, {entry['count']})")
        else:
            return None
    return "(" + "".join(f"{p}, " for p in parts).rstrip(" ") + ")"


def parse_action(action, reasons: list[str]) -> str | None:
    """L'azione di una carta blu -> codice Python "(CardAction(...), ...)".

    Nella fonte un'azione è come un "behavior" con in più "spend" (cosa paghi);
    "or: {behaviors: [...]}" elenca alternative tra cui scegliere.
    """
    if not isinstance(action, dict):
        reasons.append("azione non leggibile")
        return None
    if set(action) == {"or"}:
        alternatives = action["or"].get("behaviors") if isinstance(action["or"], dict) else None
        if not isinstance(alternatives, list):
            reasons.append("azione non leggibile")
            return None
    else:
        alternatives = [action]
    codes = [parse_action_alternative(a, reasons) for a in alternatives]
    if any(code is None for code in codes):
        return None
    return "(" + "".join(f"{code}, " for code in codes).rstrip(" ") + ")"


def parse_action_alternative(alt, reasons: list[str]) -> str | None:
    if not isinstance(alt, dict) or not set(alt) <= ACTION_KEYS:
        unknown = sorted(set(alt) - ACTION_KEYS) if isinstance(alt, dict) else ["?"]
        reasons.append(f"azione non gestita: {', '.join(unknown)}")
        return None
    args: list[str] = []
    ok = True

    def resources_dict(value) -> str | None:
        if isinstance(value, dict) and all(r in RESOURCES and isinstance(n, int)
                                           for r, n in value.items()):
            return "{" + ", ".join(f"R.{RESOURCES[r]}: {n}" for r, n in value.items()) + "}"
        return None

    for key, value in alt.items():
        if key == "title":
            continue
        if key == "spend" and isinstance(value, dict):
            plain = {r: n for r, n in value.items() if r in RESOURCES}
            code = resources_dict(plain)
            extra = set(value) - set(plain) - {"resourcesHere", "canUseSteel", "canUseTitanium"}
            if code is None or extra:
                ok = False
                continue
            if plain:
                args.append(f"spend={code}")
            if "resourcesHere" in value:
                args.append(f"spend_here={value['resourcesHere']}")
            if value.get("canUseSteel") is True:
                args.append("can_use_steel=True")
            if value.get("canUseTitanium") is True:
                args.append("can_use_titanium=True")
        elif key == "addResources" and isinstance(value, int):
            args.append(f"add_here={value}")
        elif key == "stock" and isinstance(value, dict):
            if value == {"megacredits": {"cities": {"where": "onmars"}}}:
                args.append("megacredits_per_city_on_mars=1")
            elif (code := resources_dict(value)) is not None:
                args.append(f"gain={code}")
            else:
                ok = False
        elif key == "production" and (code := resources_dict(value)) is not None:
            args.append(f"production={code}")
        elif key == "global" and isinstance(value, dict) and set(value) <= set(GLOBALS):
            args += [f"{GLOBALS[p]}={n}" for p, n in value.items()]
        elif key == "tr" and isinstance(value, int):
            args.append(f"terraform_rating={value}")
        elif key == "ocean" and value == {}:
            args.append("tiles=(TileType.OCEAN,)")
        elif key == "drawCard" and isinstance(value, int):
            args.append(f"draw_cards={value}")
        elif key == "drawCard" and isinstance(value, dict) and set(value) == {"count"}:
            args.append(f"draw_cards={value['count']}")
        elif key == "drawCard" and value == {"count": 1, "pay": True}:
            args.append("buy_card=True")
        elif (key == "removeResourcesFromAnyCard" and isinstance(value, dict)
                and card_resource_name(value.get("type")) and value.get("source") == "all"):
            args.append(f"remove_from_any_card=CardResource.{card_resource_name(value['type'])}")
        elif (key == "addResourcesToAnyCard" and isinstance(value, dict)
                and card_resource_name(value.get("type")) and isinstance(value.get("count"), int)):
            kind = card_resource_name(value["type"])
            args.append(f"add_to_other_card=(CardResource.{kind}, {value['count']})")
        elif key == "special" and isinstance(value, str):      # solo dalle correzioni a mano
            args.append(f"special={value!r}")
        else:
            ok = False
        if not ok:
            reasons.append(f"azione non gestita: {key}")
            return None
    return f"CardAction({', '.join(args)})"


def tile_code(tile: str, options: dict) -> str | None:
    """Codice Python di una tessera da piazzare, o None se ha opzioni sconosciute."""
    if not set(options) <= TILE_OPTION_KEYS:
        return None
    rule = None
    if "on" in options:
        rule = ON_RULES.get(options["on"])
        if rule is None:
            return None
    if "space" in options:
        space = options["space"]
        rule = SPACE_RULES.get(space.path.split(".")[-1]) if isinstance(space, Ref) else None
        if rule is None:
            return None
    if rule is None:
        return f"TileType.{tile}"
    return f"TilePlacement(TileType.{tile}, PlacementRule.{rule})"


def convert(name: str, data: dict, source: str, expansion: str,
            is_prelude: bool = False) -> tuple[str | None, list[str]]:
    """Traduce i dati di una carta. Restituisce (codice Python, motivi di esclusione)."""
    reasons: list[str] = []
    if name in NOT_YET_SUPPORTED:
        reasons.append(NOT_YET_SUPPORTED[name])
    paid_prelude = is_prelude and name in PAID_PRELUDES_EXTRA_TILES
    hand_coded = name in CARD_TRIGGERS          # effetti scritti in tm_sim/card_effects.py
    patched = name in PATCHES                   # codice tradotto in dati qui sopra
    if has_custom_code(source) and not (paid_prelude or hand_coded or patched):
        reasons.append("codice personalizzato")

    allowed = {"type", "name", "tags", "cost", "victoryPoints", "behavior", "requirements",
               "metadata", "cardDiscount", "globalParameterRequirementBonus", "resourceType",
               "action",              # azioni delle carte blu (vedi parse_action)
               "vpIfAnyResource", "resourcesAsPayment",   # solo dalle correzioni a mano
               "nextCardDiscount", "nextCardLeeway", "playCardNow",
               "protectedResources",  # protezione dagli attacchi: per ora nessuno attacca
               "adjacencyBonus",      # solo per l'espansione Ares: lo ignoriamo
               "tr"}                  # suggerimento sul TR guadagnato (lo calcoliamo noi)
    if paid_prelude:
        allowed.add("startingMegacredits")
    for key in data:
        if key not in allowed:
            reasons.append(f"campo non gestito: {key}")

    # Tipo (i preludi nella fonte spesso non lo scrivono: lo deduciamo dal manifesto)
    card_type = data.get("type", "CardType.PRELUDE" if is_prelude else None)
    card_type = card_type.path if isinstance(card_type, Ref) else str(card_type)
    if card_type not in ("CardType.AUTOMATED", "CardType.EVENT", "CardType.PRELUDE",
                         "CardType.ACTIVE"):
        reasons.append(f"tipo non gestito: {card_type}")
    is_event = card_type == "CardType.EVENT"
    is_active = card_type == "CardType.ACTIVE"

    effect_args = parse_permanent_effects(data, reasons)
    if "action" in data:
        actions = parse_action(data["action"], reasons)
        if actions:
            effect_args.append(f"actions={actions}")
    if "vpIfAnyResource" in data:
        effect_args.append(f"vp_if_any_resource={data['vpIfAnyResource']}")
    if "nextCardDiscount" in data:
        effect_args.append(f"next_card_discount={data['nextCardDiscount']}")
    if "nextCardLeeway" in data:
        effect_args.append(f"next_card_leeway={data['nextCardLeeway']}")
    if data.get("playCardNow"):
        effect_args.append("play_card_now=True")
    payment = data.get("resourcesAsPayment")
    if payment is not None:
        tag = tag_name(payment["tag"])
        effect_args.append(f"resources_as_payment=(Tag.{tag}, {payment['value']})")

    # Tag
    tags: Counter[str] = Counter()
    for tag in data.get("tags", []):
        raw_tag = tag.path.split(".")[-1] if isinstance(tag, Ref) else str(tag)
        if raw_tag in TAGS:
            tags[TAGS[raw_tag]] += 1
        else:
            reasons.append(f"tag non gestito: {raw_tag}")
    if is_event:
        tags["EVENT"] = 1   # la fonte non lo elenca, ma per noi l'evento ha il suo tag

    # Costo e punti vittoria (i preludi sono gratis)
    cost = data.get("cost", 0 if is_prelude else None)
    if cost is True:
        # Scritto come "cost," : il valore è nei parametri del costruttore ("cost = 10").
        match = re.search(r"\bcost\s*=\s*(\d+)", source)
        cost = int(match.group(1)) if match else None
    if not isinstance(cost, int):
        reasons.append("costo non numerico")
    vp = data.get("victoryPoints", 0)
    vp_args: list[str] = []
    needs_tile_for_vp = None
    if isinstance(vp, dict) and set(vp) == {"nextToThis"} | (set(vp) & set(TILE_ADJACENCY_VP)):
        needs_tile_for_vp = TILE_ADJACENCY_VP[next(iter(set(vp) & set(TILE_ADJACENCY_VP)))]
        vp = 0
    elif isinstance(vp, dict):
        vp_args = parse_variable_vp(vp, reasons)
        vp = 0
    elif not isinstance(vp, int):
        reasons.append("punti vittoria speciali")

    # Requisiti
    requirement_args: list[str] = []
    raw_requirements = data.get("requirements", [])
    if isinstance(raw_requirements, dict):
        raw_requirements = [raw_requirements]
    tag_requirements: dict[str, int] = {}
    for req in raw_requirements if isinstance(raw_requirements, list) else [raw_requirements]:
        if not isinstance(req, dict):
            reasons.append("requisito non leggibile")
            continue
        is_max = req.get("max", False) is True
        keys = set(req) - {"max"}
        if len(keys & PARAMETER_REQUIREMENTS) == 1 and keys <= PARAMETER_REQUIREMENTS:
            param = keys.pop()
            prefix = "max" if is_max else "min"
            requirement_args.append(f"{prefix}_{param}={req[param]}")
        elif (keys == {"production", "count"} and not is_max
                and isinstance(req["production"], Ref) and isinstance(req["count"], int)
                and req["production"].path.split(".")[-1] in RESOURCE_REFS):
            resource = RESOURCE_REFS[req["production"].path.split(".")[-1]]
            requirement_args.append(f"min_production={{R.{resource}: {req['count']}}}")
        elif keys == {"greeneries"} and not is_max and isinstance(req["greeneries"], int):
            requirement_args.append(f"min_greeneries={req['greeneries']}")
        elif keys == {"cities", "all"} and req["all"] is True and isinstance(req["cities"], int):
            requirement_args.append(f"min_cities={req['cities']}")
        elif "tag" in req and keys <= {"tag", "count"} and not is_max:
            raw_tag = req["tag"].path.split(".")[-1] if isinstance(req["tag"], Ref) else ""
            if raw_tag in TAGS:
                tag_requirements[TAGS[raw_tag]] = req.get("count", 1)
            else:
                reasons.append(f"requisito di tag non gestito: {raw_tag}")
        else:
            reasons.append(f"requisito non gestito: {sorted(keys)}")
    if tag_requirements:
        inner = ", ".join(f"Tag.{t}: {n}" for t, n in tag_requirements.items())
        requirement_args.append(f"tags={{{inner}}}")

    # Effetti
    behavior = data.get("behavior", {})
    production: dict[str, int] = {}
    stock: dict[str, int] = {}
    scaled_production: dict[str, str] = {}
    scaled_stock: dict[str, str] = {}
    global_args: list[str] = []
    other_args: list[str] = []
    tiles: list[str] = []
    if not isinstance(behavior, dict):
        reasons.append("effetto non leggibile")
        behavior = {}
    for key, value in behavior.items():
        if key in ("production", "stock", "extraProduction") and isinstance(value, dict):
            target = production if key == "production" else stock
            scaled_target = scaled_production if key != "stock" else scaled_stock
            for resource, amount in value.items():
                if resource in RESOURCES and isinstance(amount, int) and key != "extraProduction":
                    target[RESOURCES[resource]] = amount
                elif resource in RESOURCES and (code := scaled_code(amount)):
                    # Quantità che dipende dalla situazione (Satellites: per tag spazio).
                    scaled_target[RESOURCES[resource]] = code
                else:
                    reasons.append(f"effetto non gestito: {key}.{resource}")
        elif key == "trPerTag" and tag_name(value):        # solo dalle correzioni a mano
            other_args.append(f"scaled_tr=Scaled('tag', Tag.{tag_name(value)})")
        elif key == "global" and isinstance(value, dict):
            for param, steps in value.items():
                if param in GLOBALS and isinstance(steps, int):
                    global_args.append(f"{GLOBALS[param]}={steps}")
                else:
                    reasons.append(f"effetto non gestito: global.{param}")
        elif key in TILE_EFFECTS and isinstance(value, dict):
            # {} = una tessera, {count: 2} = due, {on: 'land'} = con una regola speciale.
            code = tile_code(TILE_EFFECTS[key], value)
            count = value.get("count", 1)
            if code and isinstance(count, int):
                tiles += [code] * count
            else:
                reasons.append(f"effetto non gestito: {key}")
        elif key == "tile" and isinstance(value, dict):
            # Tessera speciale: {type: TileType.MOHOLE_AREA, on: 'ocean'}
            kind = value.get("type")
            kind = kind.path.split(".")[-1] if isinstance(kind, Ref) else ""
            code = tile_code(kind, value) if kind in SPECIAL_TILE_TYPES else None
            if code:
                tiles.append(code)
            else:
                reasons.append(f"tessera non gestita: {kind or '?'}")
        elif key == "drawCard" and isinstance(value, int):
            other_args.append(f"draw_cards={value}")
        elif (key == "drawCard" and isinstance(value, dict) and set(value) == {"count", "tag"}
                and isinstance(value["tag"], Ref) and value["tag"].path.split(".")[-1] in TAGS):
            other_args.append(f"draw_cards={value['count']}")
            other_args.append(f"draw_tag=Tag.{TAGS[value['tag'].path.split('.')[-1]]}")
        elif key == "tr" and isinstance(value, int):
            other_args.append(f"terraform_rating={value}")
        elif key == "removeAnyPlants" and isinstance(value, int):
            other_args.append(f"remove_any_plants={value}")
        elif (key == "decreaseAnyProduction" and isinstance(value, dict)
                and set(value) == {"type", "count"} and isinstance(value["type"], Ref)
                and value["type"].path.split(".")[-1] in RESOURCE_REFS):
            resource = RESOURCE_REFS[value["type"].path.split(".")[-1]]
            other_args.append(f"decrease_any_production=(R.{resource}, {value['count']})")
        elif key == "raid":          # solo dalle correzioni a mano
            parts = []
            for what, amount in value["options"]:
                code = f"CardResource.{what}" if what in CARD_RESOURCES else f"R.{what}"
                parts.append(f"({code}, {amount})")
            other_args.append("raid=(" + ", ".join(parts) + ",)")
            if value["steals"]:
                other_args.append("raid_steals=True")
        elif key == "floodRaid":     # solo dalle correzioni a mano
            other_args.append(f"flood_raid={value}")
        elif key == "steelValue" and isinstance(value, int):
            other_args.append(f"steel_value_bonus={value}")
        elif key == "titanumValue" and isinstance(value, int):   # sic: nella fonte è scritto così
            other_args.append(f"titanium_value_bonus={value}")
        elif key == "addResources" and isinstance(value, int) and "resourceType" in data:
            other_args.append(f"starting_resources={value}")
        elif key == "addResourcesToAnyCard" and (code := add_to_cards_code(value)):
            other_args.append(f"add_to_cards={code}")
        elif (key == "drawCard" and isinstance(value, dict) and set(value) == {"count", "keep"}
                and isinstance(value["count"], int) and isinstance(value["keep"], int)):
            other_args.append(f"draw_cards={value['count']}")
            other_args.append(f"keep_cards={value['keep']}")
        elif (key == "or" and isinstance(value, dict)
                and isinstance(value.get("behaviors"), list)):
            # "Scegli uno": ogni alternativa si legge come un'azione senza costo.
            codes = [parse_action_alternative(b, reasons) for b in value["behaviors"]]
            if all(codes):
                other_args.append("choices=(" + "".join(f"{c}, " for c in codes).rstrip(" ") + ")")
        else:
            reasons.append(f"effetto non gestito: {key}")

    if paid_prelude:
        price = data.get("startingMegacredits")
        if isinstance(price, int) and price < 0:
            stock["MEGACREDITS"] = stock.get("MEGACREDITS", 0) + price
        tiles += PAID_PRELUDES_EXTRA_TILES[name]

    if needs_tile_for_vp and not any(f"TileType.{needs_tile_for_vp}" in t for t in tiles):
        reasons.append("punti vittoria speciali")

    if reasons:
        return None, sorted(set(reasons))

    # Costruzione della riga di codice
    args = [repr(name), str(cost)]
    if is_event:
        args.append("CardType.EVENT")
    elif is_active:
        args.append("CardType.ACTIVE")
    elif is_prelude:
        args.append("CardType.PRELUDE")
    if tags:
        args.append("tags={" + ", ".join(f"Tag.{t}: {n}" for t, n in tags.items()) + "}")
    if requirement_args:
        args.append("requirements=Requirements(" + ", ".join(requirement_args) + ")")
    if production:
        args.append("production={" + ", ".join(f"R.{r}: {n}" for r, n in production.items()) + "}")
    if stock:
        args.append("resources={" + ", ".join(f"R.{r}: {n}" for r, n in stock.items()) + "}")
    if scaled_production:
        args.append("scaled_production={" + ", ".join(
            f"R.{r}: {c}" for r, c in scaled_production.items()) + "}")
    if scaled_stock:
        args.append("scaled_resources={" + ", ".join(
            f"R.{r}: {c}" for r, c in scaled_stock.items()) + "}")
    args.extend(global_args)
    if tiles:
        args.append("tiles=(" + "".join(f"{t}, " for t in tiles).rstrip(" ") + ")")
    args.extend(other_args)
    args.extend(effect_args)
    if vp:
        args.append(f"victory_points={vp}")
    args.extend(vp_args)
    args.append(f"expansion={expansion!r}")
    return f"    Card({', '.join(args)}),", []


# ---------------------------------------------------------------------------
# 5. Programma principale
# ---------------------------------------------------------------------------

def source_version(repo: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "sconosciuta"


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    repo = Path(sys.argv[1]).resolve()
    if not (repo / "src/server/cards").is_dir():
        sys.exit(f"Non trovo src/server/cards dentro {repo}")

    card_names = read_card_names(repo)
    class_files = find_class_files(repo)
    cards: list[ImportedCard] = []

    for manifest_file, const, expansion in MANIFESTS:
        imports = read_manifest_imports(repo, manifest_file)
        for section, entries in read_manifest(repo, manifest_file, const).items():
            for enum_name, class_name in entries:
                name = card_names.get(enum_name, enum_name)
                card = ImportedCard(name, expansion, SECTIONS[section])
                cards.append(card)
                if section == "corporationCards":
                    card.reasons = ["corporazione: scritta a mano in tm_sim/corporations.py"]
                    continue
                path = imports.get(class_name) or class_files.get(class_name)
                if path is None:
                    card.reasons = ["file non trovato"]
                    continue
                source = path.read_text(encoding="utf-8")
                data = extract_super_object(source)
                if name in PATCHES:
                    data = apply_patch(data, PATCHES[name])
                if data is None:
                    card.reasons = ["formato non riconosciuto"]
                    continue
                card.code, card.reasons = convert(name, data, source, expansion,
                                                  is_prelude=(section == "preludeCards"))

    supported = [c for c in cards if not c.reasons]
    version = source_version(repo)
    write_card_data(supported, version)
    write_report(cards, version)

    projects = sum(1 for c in supported if c.section == "progetto")
    preludes = sum(1 for c in supported if c.section == "preludio")
    print(f"Elementi letti: {len(cards)}")
    print(f"Importati:      {projects} carte progetto e {preludes} preludi"
          f"  -> {OUTPUT_DATA.relative_to(PROJECT_ROOT)}")
    print(f"Esclusi:        {len(cards) - len(supported)}  -> {OUTPUT_REPORT.relative_to(PROJECT_ROOT)}")


def write_card_data(cards: list[ImportedCard], version: str) -> None:
    lines = [
        '"""FILE GENERATO AUTOMATICAMENTE da tools/import_cards.py: non modificarlo a mano.',
        "",
        "Dati estratti da https://github.com/terraforming-mars/terraforming-mars",
        f"(licenza GPL-3.0), versione {version}.",
        "Contiene solo le carte che il motore sa già giocare: le altre sono",
        "elencate in tools/import_report.md.",
        '"""',
        "",
        "from tm_sim.board import PlacementRule, TilePlacement, TileType",
        "from tm_sim.cards import Card, CardAction, CardResource, CardType, Requirements, Scaled, Tag",
        "from tm_sim.state import Resource as R",
        "",
        "# Carte progetto (il mazzo)",
        "IMPORTED_CARDS = [",
        *sorted(c.code for c in cards if c.section == "progetto"),
        "]",
        "",
        "# Preludi",
        "PRELUDE_CARDS = [",
        *sorted(c.code for c in cards if c.section == "preludio"),
        "]",
        "",
    ]
    OUTPUT_DATA.write_text("\n".join(lines), encoding="utf-8")


def write_report(cards: list[ImportedCard], version: str) -> None:
    lines = [
        "# Report di importazione delle carte",
        "",
        f"Fonte: progetto open source di Terraforming Mars, versione {version}.",
        "Generato da `tools/import_cards.py`.",
        "",
        "## Riepilogo",
        "",
        "| Espansione | Tipo | Totale | Importate | Escluse |",
        "|---|---|---:|---:|---:|",
    ]
    groups: dict[tuple[str, str], list[ImportedCard]] = defaultdict(list)
    for card in cards:
        groups[(card.expansion, card.section)].append(card)
    for (expansion, section), group in groups.items():
        ok = sum(1 for c in group if not c.reasons)
        lines.append(f"| {expansion} | {section} | {len(group)} | {ok} | {len(group) - ok} |")

    reason_counts = Counter(r for c in cards for r in c.reasons)
    lines += ["", "## Motivi di esclusione (una carta può averne più di uno)", "",
              "| Motivo | Carte |", "|---|---:|"]
    lines += [f"| {reason} | {n} |" for reason, n in reason_counts.most_common()]

    lines += ["", "## Carte escluse", ""]
    for card in sorted(cards, key=lambda c: (c.section, c.name)):
        if card.reasons:
            lines.append(f"- **{card.name}** ({card.expansion}, {card.section}): "
                         + "; ".join(card.reasons))
    lines.append("")
    OUTPUT_REPORT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
