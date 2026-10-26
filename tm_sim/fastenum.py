"""Enum un po' più veloci, per le simulazioni.

In Python 3.13 l'hash di un Enum è scritto in Python (hash del nome), e le
risorse, i tag e le tessere si usano come chiavi di dizionario milioni di volte
per partita. Ogni valore di un Enum esiste in una sola copia e si confronta per
identità: usare l'hash "di identità" scritto in C è equivalente, solo più veloce.
"""

from enum import Enum


class FastEnum(Enum):
    __hash__ = object.__hash__
