"""Test delle carte: requisiti, pagamento, effetti, fase di ricerca."""

from tm_sim.actions import Action, ActionType
from tm_sim.card_list import ALL_CARDS, CARDS_BY_NAME
from tm_sim.cards import Card, CardType, Requirements, Tag
from tm_sim.game import Game, Phase
from tm_sim.state import Resource


def game_with_hand(*card_names: str) -> Game:
    """Una partita senza mazzo in cui Alice ha in mano solo le carte indicate."""
    game = Game(["Alice", "Bob"], cards=[])
    game.current_player.hand = [CARDS_BY_NAME[name] for name in card_names]
    return game


def play(game: Game, card_name: str) -> None:
    game.apply(Action(ActionType.PLAY_CARD, card_name))


def playable(game: Game) -> set[str]:
    return {a.card for a in game.legal_actions() if a.type is ActionType.PLAY_CARD}


# --- Dati delle carte -----------------------------------------------------------

def test_every_event_has_the_event_tag():
    for card in ALL_CARDS:
        if card.type is CardType.EVENT:
            assert card.tags.get(Tag.EVENT) == 1, card.name


def test_no_card_has_event_tag_unless_it_is_an_event():
    for card in ALL_CARDS:
        if card.type is not CardType.EVENT:
            assert Tag.EVENT not in card.tags, card.name


# --- Giocare una carta ----------------------------------------------------------

def test_play_simple_card():
    game = game_with_hand("Sponsors")
    alice = game.current_player
    play(game, "Sponsors")
    assert alice.resources[Resource.MEGACREDITS] == 42 - 6
    assert alice.production[Resource.MEGACREDITS] == 2
    assert alice.tag_count(Tag.EARTH) == 1
    assert alice.hand == []


def test_card_with_resources_production_and_victory_points():
    game = game_with_hand("Trees")
    game.state.planet.temperature = -4
    alice = game.current_player
    play(game, "Trees")
    assert alice.production[Resource.PLANTS] == 3
    assert alice.resources[Resource.PLANTS] == 1
    assert alice.victory_points() == 20 + 1


def test_card_that_raises_temperature_gives_tr():
    game = game_with_hand("Deep Well Heating")
    alice = game.current_player
    play(game, "Deep Well Heating")
    assert game.state.planet.temperature == -28
    assert alice.terraform_rating == 21


# --- Requisiti ------------------------------------------------------------------

def test_minimum_temperature_requirement():
    game = game_with_hand("Lichen")
    assert "Lichen" not in playable(game)       # -30 < -24
    game.state.planet.temperature = -24
    assert "Lichen" in playable(game)


def test_maximum_requirement():
    game = game_with_hand("Designed Microorganisms")
    game.state.planet.temperature = -14
    assert "Designed Microorganisms" in playable(game)
    game.state.planet.temperature = -12
    assert "Designed Microorganisms" not in playable(game)


def test_tag_requirement_counts_only_cards_already_played():
    game = game_with_hand("Tectonic Stress Power", "Solar Wind Power", "Trans-Neptune Probe")
    alice = game.current_player
    alice.gain(Resource.MEGACREDITS, 100)
    assert "Tectonic Stress Power" not in playable(game)
    play(game, "Solar Wind Power")
    play(game, "Trans-Neptune Probe")
    assert alice.tag_count(Tag.SCIENCE) == 2
    game.current = 0  # forziamo il turno di Alice per il test
    assert "Tectonic Stress Power" in playable(game)


def test_events_only_keep_the_event_tag():
    game = game_with_hand("Imported GHG")
    alice = game.current_player
    play(game, "Imported GHG")
    assert alice.tag_count(Tag.EVENT) == 1
    assert alice.tag_count(Tag.EARTH) == 0
    assert alice.tag_count(Tag.SPACE) == 0


def test_cannot_lower_production_below_minimum():
    game = game_with_hand("Building Industries")   # -1 produzione di energia
    assert "Building Industries" not in playable(game)
    game.current_player.change_production(Resource.ENERGY, 1)
    assert "Building Industries" in playable(game)


def test_megacredit_production_can_go_negative_with_a_card():
    game = game_with_hand("Nuclear Power")         # -2 produzione di M€
    play(game, "Nuclear Power")
    assert game.current_player.production[Resource.MEGACREDITS] == -2


# --- Pagamento ------------------------------------------------------------------

def test_steel_pays_for_building_cards():
    game = game_with_hand("Strip Mine")             # 25 M€, edificio
    alice = game.current_player
    alice.resources[Resource.MEGACREDITS] = 5
    alice.change_production(Resource.ENERGY, 2)
    assert "Strip Mine" not in playable(game)
    alice.gain(Resource.STEEL, 10)                  # 10 acciaio = 20 M€
    play(game, "Strip Mine")
    assert alice.resources[Resource.STEEL] == 0
    assert alice.resources[Resource.MEGACREDITS] == 0


def test_titanium_is_not_wasted():
    card = CARDS_BY_NAME["Trans-Neptune Probe"]     # 6 M€, spazio
    game = game_with_hand()
    alice = game.current_player
    alice.gain(Resource.TITANIUM, 5)
    payment = card.payment_for(alice)
    assert payment.titanium == 2                    # 2 × 3 = 6: basta così
    assert payment.megacredits == 0


def test_overpaying_with_metal_when_megacredits_are_not_enough():
    card = CARDS_BY_NAME["Trans-Neptune Probe"]     # 6 M€
    game = game_with_hand()
    alice = game.current_player
    alice.resources[Resource.MEGACREDITS] = 0
    alice.gain(Resource.TITANIUM, 1)
    assert card.payment_for(alice) is None          # 3 M€ di valore non bastano
    alice.gain(Resource.TITANIUM, 1)
    assert card.payment_for(alice).titanium == 2


def test_steel_does_not_pay_for_non_building_cards():
    card = Card("Prova", 5, tags={Tag.EARTH: 1})
    game = game_with_hand()
    alice = game.current_player
    alice.resources[Resource.MEGACREDITS] = 0
    alice.gain(Resource.STEEL, 10)
    assert card.payment_for(alice) is None


def test_requirements_object_without_limits_is_always_met():
    game = game_with_hand()
    assert Requirements().are_met(game.state, game.current_player)


# --- Mazzo e fase di ricerca -------------------------------------------------------

def test_players_start_with_10_cards():
    game = Game(["Alice", "Bob"], seed=1)
    for player in game.state.players:
        assert len(player.hand) == 10
    # La variante principiante usa solo gioco base e Corporate Era.
    base_cards = [c for c in ALL_CARDS if c.expansion in ("base", "corporate_era")]
    assert len(game.deck) == len(base_cards) - 20


def test_same_seed_same_deck():
    a = Game(["Alice", "Bob"], seed=42)
    b = Game(["Alice", "Bob"], seed=42)
    assert [c.name for c in a.deck] == [c.name for c in b.deck]


def test_research_phase_after_first_generation():
    game = Game(["Alice", "Bob"], seed=1)
    game.apply(Action(ActionType.PASS))
    game.apply(Action(ActionType.PASS))
    assert game.phase is Phase.RESEARCH
    bob, alice = game.state.players[1], game.state.players[0]
    assert game.current_player is bob               # il primo giocatore è ruotato
    assert len(bob.drafted) == 4 and len(alice.drafted) == 4

    # Bob vede le 4 carte insieme: 16 gruppi possibili (da nessuna a tutte)
    assert len(game.legal_actions()) == 16
    first = bob.drafted[0].name
    game.apply(Action(ActionType.BUY_CARDS, cards=(first,)))   # compra la prima, scarta le altre
    assert [c.name for c in bob.hand][-1] == first and not bob.drafted
    assert bob.resources[Resource.MEGACREDITS] == 42 + 20 - 3
    assert len(game.discard_pile) >= 3

    # Ora tocca ad Alice, che scarta tutto
    assert game.current_player is alice
    game.apply(Action(ActionType.BUY_CARDS))
    assert game.phase is Phase.ACTION
    assert game.current_player is bob


def test_cannot_buy_without_money():
    game = Game(["Alice", "Bob"], seed=1)
    for player in game.state.players:
        player.spend(Resource.MEGACREDITS, 42)
        player.terraform_rating = 0                    # così la produzione dà 0 M€
    game.apply(Action(ActionType.PASS))
    game.apply(Action(ActionType.PASS))
    assert game.legal_actions() == [Action(ActionType.BUY_CARDS)]     # solo "niente"
