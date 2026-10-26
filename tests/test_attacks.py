"""Test degli attacchi: bersagli, quantità, protezioni, e la scelta del bot."""

from tm_sim import heuristics as h
from tm_sim.actions import Action, ActionType
from tm_sim.board import TileType
from tm_sim.bots import RuleBot
from tm_sim.card_list import CARDS_BY_NAME
from tm_sim.cards import Card, CardType
from tm_sim.game import NOBODY, Game
from tm_sim.state import Resource

MC, PLANTS = Resource.MEGACREDITS, Resource.PLANTS


def setup(*hand: str, players=("Alice", "Bob")) -> tuple[Game, list]:
    game = Game(list(players), cards=[])
    for p in game.state.players:
        p.resources[MC] = 100
    game.state.players[0].hand = [CARDS_BY_NAME[c] for c in hand]
    return game, game.state.players


def protected_habitats() -> Card:
    """Protected Habitats non è ancora nel mazzo: la creiamo qui come carta blu
    senza altri effetti. La protezione la riconosce il motore dal nome."""
    return Card("Protected Habitats", 5, CardType.ACTIVE)


def play(game: Game, name: str) -> None:
    game.apply(Action(ActionType.PLAY_CARD, name))


def attack(game: Game, target: str, option: str | None = None) -> None:
    card = game.pending_attacks[0][1].name
    game.apply(Action(ActionType.ATTACK, card, target=target, option=option))


def targets(game: Game) -> set[tuple[str, str | None]]:
    return {(a.target, a.option) for a in game.legal_actions() if a.type is ActionType.ATTACK}


def playable(game: Game) -> set[str]:
    return {a.card for a in game.legal_actions() if a.type is ActionType.PLAY_CARD}


# --- Togliere piante ---------------------------------------------------------------

def test_asteroid_removes_up_to_3_plants():
    game, (alice, bob) = setup("Asteroid")
    bob.gain(PLANTS, 2)
    play(game, "Asteroid")
    assert targets(game) == {("Bob", "piante"), (NOBODY, None)}
    attack(game, "Bob", "piante")
    assert bob.resources[PLANTS] == 0                  # ne aveva solo 2
    assert game.current_player is alice                 # l'azione è completa


def test_attack_with_no_possible_target_is_skipped():
    game, (alice, bob) = setup("Asteroid")
    play(game, "Asteroid")                              # nessuno ha piante
    assert not game.pending_attacks
    assert ActionType.ATTACK not in {a.type for a in game.legal_actions()}


def test_comet_places_the_ocean_first():
    game, (alice, bob) = setup("Comet")
    bob.gain(PLANTS, 5)
    play(game, "Comet")
    assert all(a.type is ActionType.PLACE_TILE for a in game.legal_actions())
    game.apply(Action(ActionType.PLACE_TILE, space="1-5"))
    assert targets(game) == {("Bob", "piante"), (NOBODY, None)}


def test_protected_habitats_protects_plants():
    game, (alice, bob) = setup("Asteroid")
    bob.gain(PLANTS, 5)
    bob.played = [protected_habitats()]
    play(game, "Asteroid")
    assert not game.pending_attacks                     # niente bersagli validi


# --- Ridurre la produzione -------------------------------------------------------------

def test_production_attack_needs_a_valid_target():
    game, (alice, bob) = setup("Heat Trappers")         # -2 produzione di calore a qualcuno
    assert "Heat Trappers" not in playable(game)
    bob.change_production(Resource.HEAT, 2)
    assert "Heat Trappers" in playable(game)
    play(game, "Heat Trappers")
    assert targets(game) == {("Bob", "calore")}          # obbligatorio: niente "nessuno"
    attack(game, "Bob", "calore")
    assert bob.production[Resource.HEAT] == 0


def test_production_attack_can_force_you_to_hit_yourself():
    game, (alice, bob) = setup("Heat Trappers")
    alice.change_production(Resource.HEAT, 3)
    play(game, "Heat Trappers")
    assert targets(game) == {("Alice", "calore")}


def test_energy_tapping_steals_production():
    game, (alice, bob) = setup("Energy Tapping")
    bob.change_production(Resource.ENERGY, 2)
    play(game, "Energy Tapping")
    attack(game, "Bob", "energia")
    assert alice.production[Resource.ENERGY] == 1
    assert bob.production[Resource.ENERGY] == 1


def test_megacredit_production_attack_respects_minus_5():
    game, (alice, bob) = setup("Hackers")
    alice.change_production(Resource.ENERGY, 1)
    alice.production[MC] = -5                          # non può scendere: niente bersaglio su di sé
    bob.production[MC] = -4                            # -4 - 2 = -6: non valido
    assert "Hackers" not in playable(game)
    bob.production[MC] = -3                            # -3 - 2 = -5: valido
    assert "Hackers" in playable(game)


def test_production_requirement():
    game, (alice, bob) = setup("Asteroid Mining Consortium")
    bob.change_production(Resource.TITANIUM, 1)
    assert "Asteroid Mining Consortium" not in playable(game)    # serve LA TUA produzione
    alice.change_production(Resource.TITANIUM, 1)
    assert "Asteroid Mining Consortium" in playable(game)


# --- Rubare e togliere risorse -------------------------------------------------------

def test_hired_raiders_steals_what_the_target_has():
    game, (alice, bob) = setup("Hired Raiders")
    bob.gain(Resource.STEEL, 1)
    play(game, "Hired Raiders")
    assert ("Bob", "acciaio") in targets(game) and ("Bob", "megacrediti") in targets(game)
    attack(game, "Bob", "acciaio")
    assert bob.resources[Resource.STEEL] == 0
    assert alice.resources[Resource.STEEL] == 1          # ne aveva solo 1


def test_sabotage_removes_without_stealing():
    game, (alice, bob) = setup("Sabotage")
    play(game, "Sabotage")
    attack(game, "Bob", "megacrediti")
    assert bob.resources[MC] == 100 - 7
    assert alice.resources[MC] == 100 - 1               # solo il costo della carta


def test_virus_removes_animals_from_a_card_but_not_from_pets():
    game, (alice, bob) = setup("Virus")
    bob.played = [CARDS_BY_NAME["Pets"], CARDS_BY_NAME["Ecological Zone"]]
    bob.card_resources = {"Pets": 4, "Ecological Zone": 3}
    play(game, "Virus")
    options = targets(game)
    assert ("Bob", "animali:Ecological Zone") in options
    assert ("Bob", "animali:Pets") not in options        # gli animali di Pets sono protetti
    attack(game, "Bob", "animali:Ecological Zone")
    assert bob.card_resources["Ecological Zone"] == 1


def test_flooding_hits_the_owner_of_an_adjacent_tile():
    game, (alice, bob) = setup("Flooding")
    game.state.board.place(TileType.CITY, "1-3", "Bob")   # vicina alla casella oceano 1-4
    play(game, "Flooding")
    game.apply(Action(ActionType.PLACE_TILE, space="1-4"))
    assert targets(game) == {("Bob", "megacrediti"), (NOBODY, None)}
    attack(game, "Bob", "megacrediti")
    assert bob.resources[MC] == 100 - 4


def test_herbivores_grow_with_your_greeneries():
    game, (alice, bob) = setup("Herbivores")
    game.state.planet.oxygen = 8
    bob.change_production(PLANTS, 1)
    play(game, "Herbivores")
    attack(game, "Bob", "piante")
    assert alice.card_resources["Herbivores"] == 1
    alice.gain(PLANTS, 8)
    game.current, game.actions_this_turn = 0, 0
    game.apply(Action(ActionType.CONVERT_PLANTS))
    game.apply(game.legal_actions()[0])
    assert alice.card_resources["Herbivores"] == 2


# --- L'indice di sensatezza del bot -----------------------------------------------------

def test_bot_prefers_real_damage_over_hitting_the_leader():
    # Esempio: posso togliere 8 piante; il primo ne ha 1, il secondo 8.
    game, (alice, leader, second) = setup("Deimos Down", players=("Alice", "Leader", "Secondo"))
    leader.terraform_rating = 30
    leader.gain(PLANTS, 1)
    second.gain(PLANTS, 8)
    game.state.planet.temperature = -30
    play(game, "Deimos Down")
    choice = RuleBot(0).choose(game, game.legal_actions())
    assert choice.target == "Secondo"


def test_bot_hits_the_leader_when_damage_is_similar():
    game, (alice, leader, second) = setup("Deimos Down", players=("Alice", "Leader", "Secondo"))
    leader.terraform_rating = 30
    leader.gain(PLANTS, 8)
    second.gain(PLANTS, 8)
    play(game, "Deimos Down")
    choice = RuleBot(0).choose(game, game.legal_actions())
    assert choice.target == "Leader"


def test_threat_weight_is_higher_for_the_leader():
    game, (alice, leader, second) = setup(players=("Alice", "Leader", "Secondo"))
    leader.terraform_rating = 35
    assert h.threat_weight(game, alice, leader) > 1 > h.threat_weight(game, alice, second)
