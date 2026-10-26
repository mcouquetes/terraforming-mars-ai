"""Test delle regole di base.

Per eseguirli, dalla cartella del progetto:
    pytest
pytest trova da solo i file che iniziano con test_ e, al loro interno,
le funzioni che iniziano con test_.
"""

import pytest

from tm_sim.board import TileType

from tm_sim.state import (
    MAX_OCEANS,
    MAX_TEMPERATURE,
    GameState,
    Planet,
    Player,
    Resource,
)


def make_game() -> tuple[GameState, Player, Player]:
    """Funzione di comodo: una partita nuova con due giocatori."""
    alice = Player("Alice")
    bob = Player("Bob")
    return GameState(players=[alice, bob]), alice, bob


# --- Giocatore --------------------------------------------------------------

def test_new_player_starts_with_20_tr_and_nothing_else():
    player = Player("Alice")
    assert player.terraform_rating == 20
    assert all(amount == 0 for amount in player.resources.values())
    assert all(amount == 0 for amount in player.production.values())


def test_players_do_not_share_resources():
    # Se avessimo scritto resources: dict = {} senza default_factory,
    # questo test fallirebbe: i due giocatori condividerebbero il dizionario.
    alice, bob = Player("Alice"), Player("Bob")
    alice.gain(Resource.STEEL, 5)
    assert bob.resources[Resource.STEEL] == 0


def test_cannot_spend_more_than_you_have():
    player = Player("Alice")
    player.gain(Resource.MEGACREDITS, 10)
    with pytest.raises(ValueError):
        player.spend(Resource.MEGACREDITS, 11)
    assert player.resources[Resource.MEGACREDITS] == 10


def test_megacredit_production_can_go_down_to_minus_5():
    player = Player("Alice")
    player.change_production(Resource.MEGACREDITS, -5)
    assert player.production[Resource.MEGACREDITS] == -5
    with pytest.raises(ValueError):
        player.change_production(Resource.MEGACREDITS, -1)


def test_other_productions_cannot_go_below_zero():
    player = Player("Alice")
    with pytest.raises(ValueError):
        player.change_production(Resource.STEEL, -1)


def test_production_phase():
    player = Player("Alice")
    player.change_production(Resource.MEGACREDITS, 3)
    player.change_production(Resource.PLANTS, 2)
    player.gain(Resource.ENERGY, 4)
    player.gain(Resource.HEAT, 1)

    player.production_phase()

    assert player.resources[Resource.MEGACREDITS] == 3 + 20  # produzione + TR
    assert player.resources[Resource.PLANTS] == 2
    assert player.resources[Resource.ENERGY] == 0            # convertita in calore
    assert player.resources[Resource.HEAT] == 1 + 4


# --- Parametri globali -------------------------------------------------------

def test_raising_temperature_gives_tr():
    game, alice, _ = make_game()
    done = game.raise_temperature(alice, 2)
    assert done == 2
    assert game.planet.temperature == -26
    assert alice.terraform_rating == 22


def test_temperature_stops_at_max_and_gives_no_extra_tr():
    game, alice, _ = make_game()
    game.planet.temperature = MAX_TEMPERATURE - 2
    done = game.raise_temperature(alice, 3)
    assert done == 1
    assert game.planet.temperature == MAX_TEMPERATURE
    assert alice.terraform_rating == 21


def test_temperature_bonus_gives_heat_production():
    game, alice, _ = make_game()
    game.raise_temperature(alice, 5)  # da -30 a -20: passa per -24 e -20
    assert alice.production[Resource.HEAT] == 2


def test_reaching_8_percent_oxygen_also_raises_temperature():
    game, alice, _ = make_game()
    game.planet.oxygen = 7
    game.raise_oxygen(alice)
    assert game.planet.oxygen == 8
    assert game.planet.temperature == -28
    assert alice.terraform_rating == 22  # +1 ossigeno, +1 temperatura


def test_no_more_than_9_oceans_can_be_queued():
    game, alice, _ = make_game()
    for _ in range(MAX_OCEANS + 2):
        game.queue_tile(TileType.OCEAN)
    assert [p.tile for p in game.pending_tiles] == [TileType.OCEAN] * MAX_OCEANS
    assert game.oceans_remaining() == 0


def test_reaching_zero_degrees_queues_an_ocean():
    game, alice, _ = make_game()
    game.planet.temperature = -2
    game.raise_temperature(alice, 1)
    assert [p.tile for p in game.pending_tiles] == [TileType.OCEAN]


def test_placing_an_ocean_gives_tr():
    game, alice, _ = make_game()
    game.place_tile(alice, TileType.OCEAN, "1-5")   # casella oceano senza bonus
    assert game.planet.oceans == 1
    assert alice.terraform_rating == 21


def test_planet_terraformed_only_when_all_parameters_are_maxed():
    planet = Planet(temperature=8, oxygen=14, oceans=8)
    assert not planet.is_terraformed()
    planet.oceans = 9
    assert planet.is_terraformed()


def test_end_generation_produces_for_everyone():
    game, alice, bob = make_game()
    game.end_generation()
    assert game.generation == 2
    assert alice.resources[Resource.MEGACREDITS] == 20
    assert bob.resources[Resource.MEGACREDITS] == 20
