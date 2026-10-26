"""Test di corporazioni, preludi e preparazione della partita."""

from tm_sim.actions import Action, ActionType
from tm_sim.board import TileType
from tm_sim.bots import RandomBot
from tm_sim.card_data import PRELUDE_CARDS
from tm_sim.card_list import CARDS_BY_NAME
from tm_sim.cards import Card, CardType, Requirements, Tag
from tm_sim.corporations import ALL_CORPORATIONS, CORPORATIONS_BY_NAME
from tm_sim.game import Game, Phase, Setup
from tm_sim.state import Resource

MC = Resource.MEGACREDITS
PRELUDES_BY_NAME = {p.name: p for p in PRELUDE_CARDS}


def with_corp(corp_name: str, *hand: str | Card) -> tuple[Game, object]:
    """Partita senza mazzo in cui Alice ha la corporazione indicata."""
    game = Game(["Alice", "Bob"], cards=[])
    alice = game.state.players[0]
    alice.resources[MC] = 0
    game._start_corporation(alice, CORPORATIONS_BY_NAME[corp_name])
    alice.hand = [CARDS_BY_NAME[c] if isinstance(c, str) else c for c in hand]
    return game, alice


def act(game: Game, action_type: ActionType, card=None, target=None, space=None) -> None:
    game.apply(Action(action_type, card, target, space))


def play(game: Game, card_name: str) -> None:
    act(game, ActionType.PLAY_CARD, card_name)


def place_anywhere(game: Game) -> None:
    game.apply(game.legal_actions()[0])


def playable(game: Game) -> set[str]:
    return {a.card for a in game.legal_actions() if a.type is ActionType.PLAY_CARD}


# --- Dati -------------------------------------------------------------------------

def test_seventeen_corporations():
    assert len(ALL_CORPORATIONS) == 17
    assert {c.expansion for c in ALL_CORPORATIONS} == {"base", "corporate_era", "prelude"}


def test_starting_resources_and_production():
    game, alice = with_corp("EcoLine")
    assert alice.resources[MC] == 36
    assert alice.production[Resource.PLANTS] == 2
    assert alice.resources[Resource.PLANTS] == 3
    assert alice.tag_count(Tag.PLANT) == 1          # i tag della corporazione contano


def test_mining_guild_has_two_building_tags():
    game, alice = with_corp("Mining Guild")
    assert alice.tag_count(Tag.BUILDING) == 2


# --- Modificatori ------------------------------------------------------------------

def test_teractor_discount_on_earth_cards():
    game, alice = with_corp("Teractor", "Sponsors")   # 6 M€, tag Terra
    play(game, "Sponsors")
    assert alice.resources[MC] == 60 - 3


def test_thorgate_power_plant_costs_8():
    game, alice = with_corp("Thorgate")
    act(game, ActionType.POWER_PLANT)
    assert alice.resources[MC] == 48 - 8


def test_helion_can_pay_with_heat():
    game, alice = with_corp("Helion", "Sponsors")
    alice.resources[MC] = 2
    alice.gain(Resource.HEAT, 10)
    play(game, "Sponsors")                          # 6 M€: 2 M€ + 4 calore
    assert alice.resources[MC] == 0
    assert alice.resources[Resource.HEAT] == 6


def test_phobolog_titanium_is_worth_4():
    game, alice = with_corp("PhoboLog", "Trans-Neptune Probe")   # 6 M€, spazio
    alice.resources[MC] = 0
    alice.resources[Resource.TITANIUM] = 2          # 2 × 4 = 8 ≥ 6
    assert "Trans-Neptune Probe" in playable(game)


def test_ecoline_greenery_costs_7_plants():
    game, alice = with_corp("EcoLine")
    alice.resources[Resource.PLANTS] = 7
    act(game, ActionType.CONVERT_PLANTS)
    place_anywhere(game)
    assert alice.greeneries == 1 and alice.resources[Resource.PLANTS] == 0


def test_inventrix_requirement_leeway():
    game, alice = with_corp("Inventrix", "Lichen")  # richiede -24°C
    alice.first_action_done = True
    game.state.planet.temperature = -28             # 2 passi sotto: ok
    assert "Lichen" in playable(game)
    game.state.planet.temperature = -30             # 3 passi sotto: no
    assert "Lichen" not in playable(game)


# --- Trigger --------------------------------------------------------------------------

def test_interplanetary_cinematics_gains_on_events():
    game, alice = with_corp("Interplanetary Cinematics", "Mineral Deposit")
    alice.resources[MC] = 5
    play(game, "Mineral Deposit")
    assert alice.resources[MC] == 0 + 2


def test_credicor_bonus_only_for_expensive_things():
    game, alice = with_corp("CrediCor")
    act(game, ActionType.ASTEROID)                  # 14: niente bonus
    assert alice.resources[MC] == 57 - 14
    act(game, ActionType.GREENERY)                  # 23: +4
    assert alice.resources[MC] == 57 - 14 - 23 + 4


def test_mining_guild_steel_production_on_steel_spaces():
    game, alice = with_corp("Mining Guild")
    act(game, ActionType.CITY)
    act(game, ActionType.PLACE_TILE, space="1-1")   # acciaio ×2
    assert alice.production[Resource.STEEL] == 1 + 1


def test_tharsis_first_action_is_mandatory_city():
    game, alice = with_corp("Tharsis Republic")
    assert [a.type for a in game.legal_actions()] == [ActionType.FIRST_ACTION]
    act(game, ActionType.FIRST_ACTION, "Tharsis Republic")
    act(game, ActionType.PLACE_TILE, space="3-3")
    assert alice.cities == 1
    assert alice.production[MC] == 1                # +1 per la città
    assert alice.resources[MC] == 40 + 3            # +3 perché è sua


def test_tharsis_gains_production_from_other_cities():
    game, alice = with_corp("Tharsis Republic")
    alice.first_action_done = True
    game.current = 1                                 # turno di Bob
    act(game, ActionType.CITY)
    act(game, ActionType.PLACE_TILE, space="7-1")
    assert alice.production[MC] == 1
    assert alice.resources[MC] == 40                 # niente +3: non è sua


def test_saturn_systems_any_jovian_tag():
    game, alice = with_corp("Saturn Systems")
    assert alice.production[MC] == 1                 # il suo stesso tag gioviano
    bob = game.state.players[1]
    bob.hand = [CARDS_BY_NAME["Asteroid Mining"]]
    bob.gain(MC, 100)
    game.current = 1
    play(game, "Asteroid Mining")
    assert alice.production[MC] == 2


def test_point_luna_draws_for_earth_tags():
    sponsors = CARDS_BY_NAME["Sponsors"]
    game = Game(["Alice", "Bob"], cards=[])
    game.deck = [CARDS_BY_NAME["Mine"]] * 5          # un piccolo mazzo da cui pescare
    alice = game.state.players[0]
    alice.hand = [sponsors]
    hand_before = len(alice.hand)
    game._start_corporation(alice, CORPORATIONS_BY_NAME["Point Luna"])
    assert len(alice.hand) == hand_before + 1        # il suo tag Terra
    play(game, "Sponsors")
    assert len(alice.hand) == hand_before + 1 - 1 + 1


def test_vitor_bonus_for_cards_with_victory_points():
    game, alice = with_corp("Vitor", "Trans-Neptune Probe", "Sponsors")
    alice.first_action_done = True
    play(game, "Trans-Neptune Probe")                # 1 PV: +3
    assert alice.resources[MC] == 48 - 6 + 3
    play(game, "Sponsors")                           # nessun PV
    assert alice.resources[MC] == 48 - 6 + 3 - 6


def test_vitor_first_action_funds_an_award_for_free():
    game, alice = with_corp("Vitor")
    actions = game.legal_actions()
    assert all(a.type is ActionType.FIRST_ACTION for a in actions) and len(actions) == 5
    act(game, ActionType.FIRST_ACTION, "Vitor", target="Banker")
    assert game.state.funded_awards == ["Banker"]
    assert alice.resources[MC] == 48


# --- Azioni delle corporazioni ------------------------------------------------------

def test_unmi_action_needs_tr_raised_this_generation():
    game, alice = with_corp("United Nations Mars Initiative")
    assert not any(a.type is ActionType.CARD_ACTION for a in game.legal_actions())
    act(game, ActionType.ASTEROID)                   # +1 TR
    act(game, ActionType.CARD_ACTION, "United Nations Mars Initiative", target="+1 TR")
    assert alice.terraform_rating == 22
    assert alice.resources[MC] == 40 - 14 - 3


def test_corporation_action_once_per_generation():
    game, alice = with_corp("Robinson Industries")
    options = {a.target for a in game.legal_actions() if a.type is ActionType.CARD_ACTION}
    assert len(options) == 6                         # tutte le produzioni sono a 0
    act(game, ActionType.CARD_ACTION, "Robinson Industries", target="acciaio")
    assert alice.production[Resource.STEEL] == 1
    act(game, ActionType.END_TURN) if game.current_player is alice else None
    game.current, game.actions_this_turn = 0, 0
    assert not any(a.type is ActionType.CARD_ACTION for a in game.legal_actions())


def test_robinson_only_lowest_productions():
    game, alice = with_corp("Robinson Industries")
    for resource in Resource:
        alice.production[resource] = 1
    alice.production[Resource.HEAT] = 0
    options = {a.target for a in game.legal_actions() if a.type is ActionType.CARD_ACTION}
    assert options == {"calore"}


# --- Preparazione della partita --------------------------------------------------------

def finish_setup(game: Game, keep_cards: int = 0) -> None:
    """Fa la preparazione: prima corporazione, primi preludi, compra le prime N carte."""
    while game.phase is Phase.SETUP:
        player = game.current_player
        actions = game.legal_actions()
        if actions[0].type in (ActionType.CHOOSE_CORPORATION, ActionType.KEEP_PRELUDE):
            game.apply(actions[0])
        else:
            # Le 10 carte si guardano insieme e si comprano in un colpo solo.
            assert len(actions) == 2 ** 10 or len(player.drafted) * 3 > player.resources[MC]
            group = tuple(c.name for c in player.drafted[:keep_cards])
            game.apply(next(a for a in actions if a.cards == group))


def test_standard_setup_choose_corporation_and_buy_cards():
    game = Game(["Alice", "Bob"], seed=1, setup=Setup.STANDARD)
    alice = game.state.players[0]
    assert game.phase is Phase.SETUP
    assert len(alice.corporation_choices) == 2 and len(alice.drafted) == 10
    assert alice.prelude_choices == []
    finish_setup(game, keep_cards=4)
    assert game.phase is Phase.ACTION
    assert len(alice.hand) == 4
    expected = alice.corporation.starting_megacredits - 4 * 3
    assert alice.resources[MC] == expected


def test_prelude_setup_keep_two_then_play_them():
    game = Game(["Alice", "Bob"], seed=2, setup=Setup.PRELUDE)
    alice = game.state.players[0]
    assert len(alice.prelude_choices) == 4
    finish_setup(game)
    assert len(alice.preludes) == 2
    assert game.phase is Phase.PRELUDES
    assert game.current_player is alice
    # Ognuno gioca i suoi due preludi (piazzando tessere se serve).
    while game.phase is Phase.PRELUDES:
        game.apply(game.legal_actions()[0])
    assert game.phase is Phase.ACTION
    assert all(len([c for c in p.played if c.type is CardType.PRELUDE]) == 2
               for p in game.state.players)


def test_prelude_with_a_city_asks_where_to_place_it():
    game = Game(["Alice", "Bob"], cards=[], setup=Setup.PRELUDE,
                preludes=[PRELUDES_BY_NAME["Early Settlement"]] * 8)
    finish_setup(game)
    act(game, ActionType.PLAY_PRELUDE, "Early Settlement")
    assert game.pending_tile.tile is TileType.CITY


def test_unplayable_prelude_gives_15_megacredits():
    expensive = Card("Prova costosa", 0, CardType.PRELUDE, resources={MC: -999})
    game = Game(["Alice", "Bob"], cards=[], setup=Setup.PRELUDE, preludes=[expensive] * 8)
    finish_setup(game)
    alice = game.current_player
    before = alice.resources[MC]
    assert {a.type for a in game.legal_actions()} == {ActionType.DISCARD_PRELUDE}
    act(game, ActionType.DISCARD_PRELUDE, "Prova costosa")
    assert alice.resources[MC] == before + 15


def test_valley_trust_first_action_plays_one_of_three_preludes():
    game, alice = with_corp("Valley Trust")
    game.prelude_deck = [PRELUDES_BY_NAME["Donation"], PRELUDES_BY_NAME["Loan"],
                         PRELUDES_BY_NAME["Power Generation"]]
    act(game, ActionType.FIRST_ACTION, "Valley Trust")
    assert {a.card for a in game.legal_actions()} == {"Donation", "Loan", "Power Generation"}
    act(game, ActionType.PLAY_PRELUDE, "Donation")
    assert alice.resources[MC] == 37 + 21
    assert alice.prelude_choices == []
    assert game.current_player is alice              # le resta la seconda azione


def test_random_prelude_games_finish_with_2_to_5_players():
    for n in (2, 3, 4, 5):
        for seed in range(8):
            names = [f"P{i}" for i in range(n)]
            game = Game(names, seed=seed, setup=Setup.PRELUDE)
            bots = {name: RandomBot(seed * 10 + i) for i, name in enumerate(names)}
            steps = 0
            while not game.is_over():
                action = bots[game.current_player.name].choose(game, game.legal_actions())
                game.apply(action)
                steps += 1
                assert steps < 20_000, "partita bloccata"
            assert game.state.planet.is_terraformed()
            assert all(p.corporation is not None for p in game.state.players)
