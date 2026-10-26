"""Test del motore dei turni e delle azioni."""

import pytest

from tm_sim.actions import Action, ActionType
from tm_sim.bots import RandomBot
from tm_sim.game import STARTING_MEGACREDITS, Game, Phase
from tm_sim.state import MAX_OCEANS, MAX_OXYGEN, MAX_TEMPERATURE, Resource


def act(game: Game, action_type: ActionType) -> None:
    """Scorciatoia per scrivere test più leggibili."""
    game.apply(Action(action_type))


def place(game: Game, space_id: str) -> None:
    game.apply(Action(ActionType.PLACE_TILE, space=space_id))


def types(actions: list[Action]) -> set[ActionType]:
    return {a.type for a in actions}


# --- Inizio partita ---------------------------------------------------------

def test_new_game():
    game = Game(["Alice", "Bob"])
    assert game.state.generation == 1
    assert game.current_player.name == "Alice"
    for player in game.state.players:
        assert player.resources[Resource.MEGACREDITS] == STARTING_MEGACREDITS


def test_first_action_options():
    game = Game(["Alice", "Bob"], cards=[])  # senza carte in mano
    # 42 M€: può permettersi tutti i progetti standard e finanziare un
    # riconoscimento, ma niente conversioni né traguardi.
    assert types(game.legal_actions()) == {
        ActionType.PASS,
        ActionType.POWER_PLANT,
        ActionType.ASTEROID,
        ActionType.AQUIFER,
        ActionType.GREENERY,
        ActionType.CITY,
        ActionType.FUND_AWARD,
    }


# --- Turni --------------------------------------------------------------------

def test_two_actions_then_next_player():
    game = Game(["Alice", "Bob"])
    act(game, ActionType.POWER_PLANT)
    assert game.current_player.name == "Alice"
    act(game, ActionType.POWER_PLANT)
    assert game.current_player.name == "Bob"


def test_after_one_action_you_can_end_turn_but_not_pass():
    game = Game(["Alice", "Bob"])
    act(game, ActionType.POWER_PLANT)
    options = types(game.legal_actions())
    assert ActionType.END_TURN in options
    assert ActionType.PASS not in options
    act(game, ActionType.END_TURN)
    assert game.current_player.name == "Bob"


def test_illegal_action_is_rejected():
    game = Game(["Alice", "Bob"])
    with pytest.raises(ValueError):
        act(game, ActionType.CONVERT_HEAT)  # non ha calore


def test_passed_player_is_skipped():
    game = Game(["Alice", "Bob"])
    act(game, ActionType.PASS)               # Alice passa
    act(game, ActionType.POWER_PLANT)        # Bob
    act(game, ActionType.END_TURN)
    assert game.current_player.name == "Bob"  # Alice è fuori: tocca ancora a Bob


def test_generation_ends_when_everyone_passed():
    game = Game(["Alice", "Bob"])
    act(game, ActionType.PASS)
    act(game, ActionType.PASS)
    assert game.state.generation == 2
    # Produzione: 42 iniziali + 20 di TR
    alice = game.state.players[0]
    assert alice.resources[Resource.MEGACREDITS] == STARTING_MEGACREDITS + 20


def test_first_player_rotates_each_generation():
    game = Game(["Alice", "Bob"])
    act(game, ActionType.PASS)
    act(game, ActionType.PASS)
    assert game.current_player.name == "Bob"


# --- Effetti delle azioni ------------------------------------------------------

def test_standard_project_costs_and_effects():
    game = Game(["Alice", "Bob"])
    alice = game.current_player
    act(game, ActionType.ASTEROID)
    assert alice.resources[Resource.MEGACREDITS] == STARTING_MEGACREDITS - 14
    assert game.state.planet.temperature == -28
    assert alice.terraform_rating == 21


def test_city_project_then_choose_where():
    game = Game(["Alice", "Bob"])
    alice = game.current_player
    act(game, ActionType.CITY)
    assert alice.production[Resource.MEGACREDITS] == 1   # effetto del progetto
    assert alice.cities == 0                             # la tessera è in attesa
    assert all(a.type is ActionType.PLACE_TILE for a in game.legal_actions())
    place(game, "3-3")
    assert alice.cities == 1
    assert game.current_player is alice                  # le resta ancora un'azione


def test_convert_plants_into_greenery():
    game = Game(["Alice", "Bob"])
    alice = game.current_player
    alice.gain(Resource.PLANTS, 9)
    act(game, ActionType.CONVERT_PLANTS)
    place(game, "7-1")                                   # nessun bonus
    assert alice.resources[Resource.PLANTS] == 1
    assert alice.greeneries == 1
    assert game.state.planet.oxygen == 1
    assert alice.victory_points() == 20 + 1 + 1  # TR base + ossigeno + foresta


def test_placement_completes_the_second_action():
    game = Game(["Alice", "Bob"])
    act(game, ActionType.POWER_PLANT)
    act(game, ActionType.AQUIFER)
    assert game.current_player.name == "Alice"           # deve ancora piazzare
    place(game, "1-5")
    assert game.current_player.name == "Bob"


def test_no_asteroid_when_temperature_is_maxed():
    game = Game(["Alice", "Bob"])
    game.state.planet.temperature = MAX_TEMPERATURE
    game.current_player.gain(Resource.HEAT, 8)
    options = types(game.legal_actions())
    assert ActionType.ASTEROID not in options
    assert ActionType.CONVERT_HEAT not in options


# --- Fine partita -------------------------------------------------------------

def test_game_ends_after_the_generation_that_completes_terraforming():
    game = Game(["Alice", "Bob"])
    planet = game.state.planet
    planet.temperature = MAX_TEMPERATURE
    planet.oxygen = MAX_OXYGEN
    planet.oceans = MAX_OCEANS - 1

    act(game, ActionType.AQUIFER)            # ultimo oceano
    place(game, "1-5")
    assert not game.is_over()                # la generazione non è ancora finita
    act(game, ActionType.END_TURN)
    act(game, ActionType.PASS)               # Bob
    act(game, ActionType.PASS)               # Alice
    assert game.is_over()
    assert game.legal_actions() == []


def test_leftover_plants_become_greeneries_at_the_end():
    game = Game(["Alice", "Bob"])
    planet = game.state.planet
    planet.temperature, planet.oxygen, planet.oceans = MAX_TEMPERATURE, MAX_OXYGEN, MAX_OCEANS
    alice = game.state.players[0]
    alice.gain(Resource.PLANTS, 17)
    act(game, ActionType.PASS)
    act(game, ActionType.PASS)
    # Partita terminata, ma prima c'è la fase delle ultime foreste.
    assert not game.is_over()
    assert game.phase is Phase.FINAL_GREENERY
    assert game.current_player is alice
    for _ in range(2):
        act(game, ActionType.CONVERT_PLANTS)
        game.apply(game.legal_actions()[0])  # una casella qualsiasi
    assert alice.greeneries == 2
    assert game.is_over()                    # 1 pianta rimasta: non basta più


def test_player_can_skip_final_greeneries():
    game = Game(["Alice", "Bob"])
    planet = game.state.planet
    planet.temperature, planet.oxygen, planet.oceans = MAX_TEMPERATURE, MAX_OXYGEN, MAX_OCEANS
    game.state.players[0].gain(Resource.PLANTS, 8)
    act(game, ActionType.PASS)
    act(game, ActionType.PASS)
    act(game, ActionType.PASS)               # Alice rinuncia
    assert game.is_over()


def test_player_count_limits():
    with pytest.raises(ValueError):
        Game(["Alice"])
    with pytest.raises(ValueError):
        Game(["A", "B", "C", "D", "E", "F"])
    with pytest.raises(ValueError):
        Game(["Alice", "Alice"])
    assert len(Game(["A", "B", "C", "D", "E"]).state.players) == 5


def test_five_players_take_turns_in_order():
    names = ["A", "B", "C", "D", "E"]
    game = Game(names, cards=[])
    for name in names:
        assert game.current_player.name == name
        act(game, ActionType.PASS)
    # Tutti hanno passato: nuova generazione, inizia B.
    assert game.state.generation == 2
    assert game.current_player.name == "B"


def test_random_games_with_3_to_5_players_finish():
    for n in (3, 4, 5):
        for seed in range(15):
            names = [f"P{i}" for i in range(n)]
            game = Game(names, seed=seed)
            bots = {name: RandomBot(seed * 10 + i) for i, name in enumerate(names)}
            while not game.is_over():
                action = bots[game.current_player.name].choose(game, game.legal_actions())
                game.apply(action)
            assert game.state.planet.is_terraformed()


def test_random_games_always_finish():
    """Il test più importante: 200 partite casuali senza errori."""
    for seed in range(200):
        game = Game(["Alice", "Bob"], seed=seed)
        bots = {"Alice": RandomBot(seed), "Bob": RandomBot(-seed - 1)}
        while not game.is_over():
            action = bots[game.current_player.name].choose(game, game.legal_actions())
            game.apply(action)
        assert game.state.planet.is_terraformed()
        assert game.winners()
