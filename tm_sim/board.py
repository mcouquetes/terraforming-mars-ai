"""La mappa di Marte: caselle esagonali, bonus, regole di piazzamento.

COORDINATE ESAGONALI
La mappa è un grande esagono di 9 righe (5, 6, 7, 8, 9, 8, 7, 6, 5 caselle).
Per sapere quali caselle sono vicine usiamo le "coordinate assiali":
ogni casella ha due numeri (q, r). r è la riga (da -4 a +4, 0 è quella
centrale) e q la posizione nella riga. Con queste coordinate i 6 vicini
di una casella (q, r) sono SEMPRE:

    (q+1, r)   (q-1, r)        stessa riga, a destra e a sinistra
    (q, r-1)   (q+1, r-1)      riga sopra
    (q-1, r+1) (q, r+1)        riga sotto

Nessuna tabella di adiacenze da scrivere a mano: è tutto calcolato.

Per i giocatori umani le caselle si chiamano invece "riga-posto",
contando da 1: "1-1" è la prima casella in alto a sinistra, "5-9"
l'ultima della riga centrale. Ci sono poi due caselle FUORI da Marte,
"ganymede" e "phobos", riservate a due carte che piazzano città nello spazio.

REGOLE DI PIAZZAMENTO
Ogni tessera in attesa ha un tipo (città, foresta, oceano, o una tessera
speciale) e una regola (PlacementRule) che dice dove può andare: la regola
normale del suo tipo, oppure una regola particolare scritta sulla carta
("su un vulcano", "lontano da tutto", "accanto ad almeno 2 città"...).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from tm_sim.fastenum import FastEnum


class SpaceType(FastEnum):
    LAND = "terra"
    OCEAN = "oceano"        # casella riservata agli oceani
    OFF_MAP = "spazio"      # fuori da Marte (Ganymede, Phobos)


class Bonus(FastEnum):
    """I bonus stampati sulle caselle."""
    STEEL = "acciaio"
    TITANIUM = "titanio"
    PLANT = "pianta"
    CARD = "carta"


class TileType(FastEnum):
    OCEAN = "oceano"
    GREENERY = "foresta"
    CITY = "città"
    # Tessere speciali: hanno un proprietario ma non sono né città né foreste
    # (tranne Capital, che è anche una città).
    CAPITAL = "Capital"
    COMMERCIAL_DISTRICT = "Commercial District"
    ECOLOGICAL_ZONE = "Ecological Zone"
    LAVA_FLOWS = "Lava Flows"
    MINING_AREA = "Mining Area"
    MINING_RIGHTS = "Mining Rights"
    MOHOLE_AREA = "Mohole Area"
    NATURAL_PRESERVE = "Natural Preserve"
    NUCLEAR_ZONE = "Nuclear Zone"
    RESTRICTED_AREA = "Restricted Area"
    INDUSTRIAL_CENTER = "Industrial Center"
    # Non è una tessera: il segnalino di Land Claim, che riserva una casella.
    CLAIM = "segnalino Land Claim"


CITY_TILES = {TileType.CITY, TileType.CAPITAL}
# Tessere speciali che NON sono città (Capital conta già come città).
SPECIAL_TILES = set(TileType) - {TileType.OCEAN, TileType.GREENERY, TileType.CLAIM} - CITY_TILES


def is_city(tile: TileType | None) -> bool:
    return tile in CITY_TILES


class PlacementRule(FastEnum):
    """Dove si può mettere una tessera."""
    DEFAULT = "regola normale"            # quella del tipo di tessera
    LAND = "su terra"                     # qualsiasi casella di terra libera
    OCEAN_SPACE = "su una casella oceano"
    ISOLATED = "lontano da altre tessere"
    VOLCANIC = "su un vulcano"
    NEXT_TO_TWO_CITIES = "accanto ad almeno 2 città"
    NEXT_TO_GREENERY = "accanto a una foresta"
    NEXT_TO_CITY = "accanto a una città"
    METAL_BONUS = "su una casella con acciaio o titanio"
    METAL_BONUS_NEXT_TO_OWN = "su acciaio o titanio, accanto a una tua tessera"
    CITY_RULES = "con le regole delle città"
    NOCTIS = "sulla casella di Noctis City"
    GANYMEDE = "su Ganymede (fuori da Marte)"
    PHOBOS = "su Phobos (fuori da Marte)"


@dataclass(frozen=True)
class TilePlacement:
    """Una tessera da piazzare, con la sua regola."""
    tile: TileType
    rule: PlacementRule = PlacementRule.DEFAULT

    def describe(self) -> str:
        if self.rule is PlacementRule.DEFAULT:
            return self.tile.value
        return f"{self.tile.value} {self.rule.value}"


def as_placement(tile: TileType | TilePlacement) -> TilePlacement:
    return tile if isinstance(tile, TilePlacement) else TilePlacement(tile)


@dataclass
class Space:
    id: str                       # "riga-posto", es. "5-3"
    row: int                      # da 1 a 9 (0 = fuori da Marte)
    pos: int                      # da 1 alla lunghezza della riga
    q: int                        # coordinate assiali (vedi sopra)
    r: int
    type: SpaceType
    bonuses: tuple[Bonus, ...] = ()
    reserved: str | None = None   # casella riservata a una carta specifica
    volcanic: bool = False
    tile: TileType | None = None
    owner: str | None = None      # nome del giocatore (gli oceani non hanno proprietario)
    claimed_by: str | None = None # Land Claim: solo questo giocatore può piazzarci

    @property
    def is_empty(self) -> bool:
        return self.tile is None

    @property
    def on_mars(self) -> bool:
        return self.type is not SpaceType.OFF_MAP


# ---------------------------------------------------------------------------
# La mappa Tharsis
# ---------------------------------------------------------------------------
# Una riga di testo per ogni riga della mappa, una "parola" per ogni casella:
#   L = terra, V = terra vulcanica, O = casella oceano,
#   N = terra riservata (Noctis City)
#   dopo i due punti, i bonus: s = acciaio, t = titanio, p = pianta, c = carta
# Esempio: "L:pp" è una casella di terra con 2 piante di bonus.
#
# Verificata casella per casella sulla fonte open source (TharsisBoard.ts).

THARSIS = [
    "L:ss  O:ss  L     O:c   O",
    "L     V:s   L     L     L     O:cc",
    "V:c   L     L     L     L     L     L:s",
    "V:pt  L:p   L:p   L:p   L:pp  L:p   L:p   O:pp",
    "V:pp  L:pp  N:pp  O:pp  O:pp  O:pp  L:pp  L:pp  L:pp",
    "L:p   L:pp  L:p   L:p   L:p   O:p   O:p   O:p",
    "L     L     L     L     L     L:p   L",
    "L:ss  L     L:c   L:c   L     L:t",
    "L:s   L:ss  L     L     O:tt",
]

NOCTIS_CITY = "Noctis City"
GANYMEDE = "ganymede"
PHOBOS = "phobos"

BONUS_CODES = {"s": Bonus.STEEL, "t": Bonus.TITANIUM, "p": Bonus.PLANT, "c": Bonus.CARD}

# Le 6 direzioni dei vicini, in coordinate assiali.
NEIGHBOR_OFFSETS = [(1, 0), (-1, 0), (0, -1), (1, -1), (-1, 1), (0, 1)]


class Board:
    def __init__(self, layout: list[str] = THARSIS):
        # Cresce a ogni tessera piazzata: chi ricorda risposte sulla mappa
        # (per andare più veloce) sa così quando non valgono più.
        self.version = 0
        self.spaces: dict[str, Space] = {}
        self._by_coords: dict[tuple[int, int], Space] = {}
        radius = len(layout) // 2

        for row_index, line in enumerate(layout):
            r = row_index - radius
            q_start = max(-radius, -radius - r)
            for pos_index, token in enumerate(line.split()):
                kind, _, codes = token.partition(":")
                space = Space(
                    id=f"{row_index + 1}-{pos_index + 1}",
                    row=row_index + 1,
                    pos=pos_index + 1,
                    q=q_start + pos_index,
                    r=r,
                    type=SpaceType.OCEAN if kind == "O" else SpaceType.LAND,
                    bonuses=tuple(BONUS_CODES[c] for c in codes),
                    reserved=NOCTIS_CITY if kind == "N" else None,
                    volcanic=(kind == "V"),
                )
                self.spaces[space.id] = space
                self._by_coords[(space.q, space.r)] = space

        # Le due caselle fuori da Marte: nessun vicino, nessun bonus.
        for space_id in (GANYMEDE, PHOBOS):
            self.spaces[space_id] = Space(space_id, 0, 0, 99, 99, SpaceType.OFF_MAP,
                                          reserved=space_id)

        # Calcoliamo i vicini una volta sola: servono di continuo.
        self._neighbors: dict[str, list[Space]] = {
            space.id: [self._by_coords[(space.q + dq, space.r + dr)]
                       for dq, dr in NEIGHBOR_OFFSETS
                       if (space.q + dq, space.r + dr) in self._by_coords]
            for space in self.spaces.values()
        }

    # --- Domande sulla mappa ------------------------------------------------

    def mars_spaces(self) -> list[Space]:
        return [s for s in self.spaces.values() if s.on_mars]

    def rows(self) -> list[list[Space]]:
        """Le caselle di Marte riga per riga (per disegnare la mappa)."""
        result: list[list[Space]] = []
        for space in self.mars_spaces():
            if len(result) < space.row:
                result.append([])
            result[-1].append(space)
        return result

    def neighbors(self, space: Space) -> list[Space]:
        return self._neighbors[space.id]

    def adjacent_oceans(self, space: Space) -> int:
        return sum(1 for n in self.neighbors(space) if n.tile is TileType.OCEAN)

    def count_tiles(self, tile: TileType) -> int:
        if tile is TileType.CITY:     # "città in gioco": comprese Capital e quelle nello spazio
            return sum(1 for s in self.spaces.values() if is_city(s.tile))
        return sum(1 for s in self.spaces.values() if s.tile is tile)

    def cities_on_mars(self) -> int:
        """Città su Marte, di chiunque (senza quelle nello spazio)."""
        return sum(1 for s in self.spaces.values() if s.on_mars and is_city(s.tile))

    def tiles_of(self, owner: str) -> list[Space]:
        return [s for s in self.spaces.values() if s.owner == owner]

    def city_points(self, owner: str) -> int:
        """Ogni città vale 1 PV per ogni foresta adiacente (di chiunque)."""
        return sum(
            1
            for space in self.spaces.values()
            if is_city(space.tile) and space.owner == owner
            for n in self.neighbors(space)
            if n.tile is TileType.GREENERY
        )

    def special_tile_points(self, owner: str) -> int:
        """Punti delle tessere speciali che dipendono dai vicini.

        Capital: 1 PV per ogni oceano adiacente.
        Commercial District: 1 PV per ogni città adiacente (di chiunque).
        """
        points = 0
        for space in self.tiles_of(owner):
            if space.tile is TileType.CAPITAL:
                points += self.adjacent_oceans(space)
            elif space.tile is TileType.COMMERCIAL_DISTRICT:
                points += sum(1 for n in self.neighbors(space) if is_city(n.tile))
        return points

    # --- Regole di piazzamento ------------------------------------------------

    def available_spaces(self, tile: TileType | TilePlacement, owner: str) -> list[Space]:
        """Le caselle dove il giocatore può piazzare questa tessera."""
        placement = as_placement(tile)
        rule = placement.rule
        if rule is PlacementRule.DEFAULT:
            if placement.tile is TileType.OCEAN:
                rule = PlacementRule.OCEAN_SPACE
            elif is_city(placement.tile):
                rule = PlacementRule.CITY_RULES
            elif placement.tile is TileType.GREENERY:
                return self._greenery_spaces(owner)
            else:
                rule = PlacementRule.LAND

        free_land = [s for s in self.spaces.values()
                     if s.type is SpaceType.LAND and s.is_empty and s.reserved is None
                     and s.claimed_by in (None, owner)]

        if placement.tile is TileType.CLAIM:
            return [s for s in free_land if s.claimed_by is None]
        if rule is PlacementRule.OCEAN_SPACE:
            return [s for s in self.spaces.values() if s.type is SpaceType.OCEAN and s.is_empty
                    and s.claimed_by in (None, owner)]
        if rule is PlacementRule.LAND:
            return free_land
        if rule is PlacementRule.CITY_RULES:
            # Mai accanto a un'altra città.
            return [s for s in free_land if not any(is_city(n.tile) for n in self.neighbors(s))]
        if rule is PlacementRule.ISOLATED:
            return [s for s in free_land if all(n.is_empty for n in self.neighbors(s))]
        if rule is PlacementRule.VOLCANIC:
            return [s for s in free_land if s.volcanic]
        if rule is PlacementRule.NEXT_TO_TWO_CITIES:
            return [s for s in free_land
                    if sum(1 for n in self.neighbors(s) if is_city(n.tile)) >= 2]
        if rule is PlacementRule.NEXT_TO_CITY:
            return [s for s in free_land if any(is_city(n.tile) for n in self.neighbors(s))]
        if rule is PlacementRule.NEXT_TO_GREENERY:
            return [s for s in free_land
                    if any(n.tile is TileType.GREENERY for n in self.neighbors(s))]
        if rule in (PlacementRule.METAL_BONUS, PlacementRule.METAL_BONUS_NEXT_TO_OWN):
            metal = [s for s in free_land
                     if Bonus.STEEL in s.bonuses or Bonus.TITANIUM in s.bonuses]
            if rule is PlacementRule.METAL_BONUS_NEXT_TO_OWN:
                metal = [s for s in metal if any(n.owner == owner for n in self.neighbors(s))]
            return metal
        reserved = {PlacementRule.NOCTIS: NOCTIS_CITY,
                    PlacementRule.GANYMEDE: GANYMEDE,
                    PlacementRule.PHOBOS: PHOBOS}[rule]
        return [s for s in self.spaces.values() if s.reserved == reserved and s.is_empty]

    def _greenery_spaces(self, owner: str) -> list[Space]:
        """Foresta: accanto a una tua tessera se possibile, altrimenti ovunque."""
        free_land = [s for s in self.spaces.values()
                     if s.type is SpaceType.LAND and s.is_empty and s.reserved is None
                     and s.claimed_by in (None, owner)]
        near_own = [s for s in free_land if any(n.owner == owner for n in self.neighbors(s))]
        return near_own or free_land

    def place(self, tile: TileType, space_id: str, owner: str | None) -> Space:
        """Mette la tessera sulla casella. Non controlla le regole:
        quello lo fa il motore, offrendo solo caselle valide."""
        space = self.spaces[space_id]
        if not space.is_empty:
            raise ValueError(f"La casella {space_id} è già occupata")
        # Ogni cambiamento della mappa cambia la "versione": il motore ricorda le
        # caselle libere finché la versione non cambia (vedi Game._can_place).
        self.version += 1
        if tile is TileType.CLAIM:        # solo il segnalino: la casella resta vuota
            space.claimed_by = owner
            return space
        space.tile = tile
        space.owner = None if tile is TileType.OCEAN else owner
        return space
