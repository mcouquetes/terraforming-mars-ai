"""Test dello script di importazione, con carte d'esempio nel formato della fonte."""

from tools.import_cards import Parser, Ref, Unreadable, convert, extract_super_object, tokenize


def parse(text: str):
    return Parser(tokenize(text)).value()


# --- Parser -----------------------------------------------------------------------

def test_parse_simple_values():
    assert parse("{cost: 13, tags: [Tag.PLANT], name: 'Trees'}") == {
        "cost": 13, "tags": [Ref("Tag.PLANT")], "name": "Trees"}


def test_parse_negative_numbers_and_nesting():
    assert parse("{production: {energy: -2, steel: 2}}") == {
        "production": {"energy": -2, "steel": 2}}


def test_parse_shorthand_key():
    assert parse("{temperature: -12, max}") == {"temperature": -12, "max": True}


def test_function_calls_are_unreadable_but_do_not_break_parsing():
    result = parse("{a: CardRenderer.builder((b) => { b.plants(1); }), cost: 5}")
    assert isinstance(result["a"], Unreadable)
    assert result["cost"] == 5


def test_comments_are_ignored():
    assert parse("{cost: 4, // commento\n /* altro */ tags: []}") == {"cost": 4, "tags": []}


# --- Conversione ---------------------------------------------------------------------

TREES = """
export class Trees extends Card implements IProjectCard {
  constructor() {
    super({
      type: CardType.AUTOMATED,
      name: CardName.TREES,
      tags: [Tag.PLANT],
      cost: 13,
      victoryPoints: 1,
      behavior: {
        production: {plants: 3},
        stock: {plants: 1},
      },
      requirements: {temperature: -4},
      metadata: {
        renderData: CardRenderer.builder((b) => {
          b.production((pb) => pb.plants(3)).plants(1);
        }),
      },
    });
  }
}
"""


def test_convert_simple_card():
    code, reasons = convert("Trees", extract_super_object(TREES), TREES, "base")
    assert reasons == []
    assert code == ("    Card('Trees', 13, tags={Tag.PLANT: 1}, "
                    "requirements=Requirements(min_temperature=-4), "
                    "production={R.PLANTS: 3}, resources={R.PLANTS: 1}, "
                    "victory_points=1, expansion='base'),")


def test_events_get_the_event_tag():
    source = """super({ type: CardType.EVENT, name: CardName.X, tags: [Tag.EARTH], cost: 3,
                behavior: {stock: {megacredits: 10}}, metadata: {} })"""
    code, reasons = convert("X", extract_super_object(source), source, "base")
    assert reasons == []
    assert "Tag.EVENT: 1" in code


def test_card_with_custom_code_is_excluded():
    source = TREES.replace(
        "  }\n}", "  }\n  public override bespokePlay(player: IPlayer) {\n    return undefined;\n  }\n}")
    _, reasons = convert("Trees", extract_super_object(source), source, "base")
    assert "codice personalizzato" in reasons


def test_blue_card_actions_are_imported():
    source = """super({ type: CardType.ACTIVE, name: CardName.X, tags: [], cost: 3,
                action: {spend: {megacredits: 8, canUseSteel: true}, ocean: {}}, metadata: {} })"""
    code, reasons = convert("X", extract_super_object(source), source, "base")
    assert reasons == []
    assert ("actions=(CardAction(spend={R.MEGACREDITS: 8}, can_use_steel=True, "
            "tiles=(TileType.OCEAN,)),)") in code


def test_alternative_actions_with_or():
    source = """super({ type: CardType.ACTIVE, name: CardName.X, tags: [], cost: 3,
                resourceType: CardResource.MICROBE,
                action: {or: {autoSelect: true, behaviors: [
                    {spend: {resourcesHere: 2}, global: {temperature: 1}, title: 'Remove'},
                    {addResources: 1, title: 'Add'}]}},
                metadata: {} })"""
    code, reasons = convert("X", extract_super_object(source), source, "base")
    assert reasons == []
    assert "actions=(CardAction(spend_here=2, temperature_steps=1), CardAction(add_here=1),)" in code


def test_look_and_buy_and_card_targets():
    source = """super({ type: CardType.ACTIVE, name: CardName.X, tags: [], cost: 3,
                action: {drawCard: {count: 1, pay: true}}, metadata: {} })"""
    code, _ = convert("X", extract_super_object(source), source, "base")
    assert "CardAction(buy_card=True)" in code
    source = """super({ type: CardType.ACTIVE, name: CardName.X, tags: [], cost: 3,
                action: {removeResourcesFromAnyCard: {type: CardResource.ANIMAL, source: 'all'},
                         addResources: 1}, metadata: {} })"""
    code, _ = convert("X", extract_super_object(source), source, "base")
    assert "CardAction(remove_from_any_card=CardResource.ANIMAL, add_here=1)" in code


def test_unknown_actions_are_excluded():
    source = """super({ type: CardType.ACTIVE, name: CardName.X, tags: [], cost: 3,
                action: {colonies: {addTradeFleet: 1}}, metadata: {} })"""
    _, reasons = convert("X", extract_super_object(source), source, "base")
    assert reasons == ["azione non gestita: colonies"]


def test_blue_card_with_discounts():
    source = """super({ type: CardType.ACTIVE, name: CardName.X, tags: [Tag.SPACE], cost: 3,
                cardDiscount: [{tag: Tag.SPACE, amount: 2}, {tag: Tag.EARTH, amount: 1, per: 'card'}],
                metadata: {} })"""
    code, reasons = convert("X", extract_super_object(source), source, "base")
    assert reasons == []
    assert "CardType.ACTIVE" in code
    assert "discounts={Tag.SPACE: 2}" in code and "discounts_once={Tag.EARTH: 1}" in code


def test_resources_on_card_and_variable_points():
    source = """super({ type: CardType.ACTIVE, name: CardName.X, tags: [Tag.ANIMAL], cost: 3,
                resourceType: CardResource.ANIMAL, victoryPoints: {resourcesHere: {}, per: 2},
                behavior: {addResources: 1}, metadata: {} })"""
    code, reasons = convert("X", extract_super_object(source), source, "base")
    assert reasons == []
    assert "resource_type=CardResource.ANIMAL" in code
    assert "resource_vp=(1, 2)" in code and "starting_resources=1" in code


def test_points_per_tag():
    source = """super({ type: CardType.AUTOMATED, name: CardName.X, tags: [Tag.JOVIAN], cost: 3,
                victoryPoints: {tag: Tag.JOVIAN}, metadata: {} })"""
    code, reasons = convert("X", extract_super_object(source), source, "base")
    assert reasons == [] and "vp_per_tag=Tag.JOVIAN" in code


def test_hand_coded_cards_accept_custom_code():
    source = """super({ type: CardType.ACTIVE, name: CardName.X, tags: [Tag.EARTH], cost: 6,
                metadata: {} })
                public onCardPlayed(player: IPlayer, card: ICard) { return; }"""
    assert convert("Media Group", extract_super_object(source), source, "base")[1] == []
    assert "codice personalizzato" in convert("Altro", extract_super_object(source), source, "base")[1]


def test_unknown_effects_are_excluded():
    source = """super({ type: CardType.AUTOMATED, name: CardName.X, tags: [], cost: 3,
                behavior: {addResourcesToAnyCard: {count: 2}}, metadata: {} })"""
    _, reasons = convert("X", extract_super_object(source), source, "base")
    assert reasons == ["effetto non gestito: addResourcesToAnyCard"]


def test_attacks_are_imported():
    source = """super({ type: CardType.EVENT, name: CardName.X, tags: [], cost: 3,
                behavior: {removeAnyPlants: 3,
                           decreaseAnyProduction: {type: Resource.HEAT, count: 2}},
                metadata: {} })"""
    code, reasons = convert("X", extract_super_object(source), source, "base")
    assert reasons == []
    assert "remove_any_plants=3" in code and "decrease_any_production=(R.HEAT, 2)" in code


def test_tiles_draw_and_tr_effects():
    source = """super({ type: CardType.AUTOMATED, name: CardName.X, tags: [], cost: 3,
                behavior: {ocean: {count: 2}, city: {}, drawCard: 1, tr: 2}, metadata: {} })"""
    code, reasons = convert("X", extract_super_object(source), source, "base")
    assert reasons == []
    assert "tiles=(TileType.OCEAN, TileType.OCEAN, TileType.CITY,)" in code
    assert "draw_cards=1" in code and "terraform_rating=2" in code


def test_tiles_with_special_options_are_excluded():
    source = """super({ type: CardType.AUTOMATED, name: CardName.X, tags: [], cost: 3,
                behavior: {city: {on: 'away-from-cities'}}, metadata: {} })"""
    _, reasons = convert("X", extract_super_object(source), source, "base")
    assert reasons == ["effetto non gestito: city"]


def test_preludes_have_no_type_and_no_cost_in_the_source():
    source = """super({ name: CardName.X, tags: [Tag.EARTH],
                behavior: {production: {megacredits: 4}}, metadata: {} })"""
    code, reasons = convert("X", extract_super_object(source), source, "prelude", is_prelude=True)
    assert reasons == []
    assert code.startswith("    Card('X', 0, CardType.PRELUDE,")


def test_paid_prelude_becomes_negative_megacredits():
    source = """super({ name: CardName.X, startingMegacredits: -5,
                behavior: {global: {temperature: 3}}, metadata: {} })
                public override bespokePlay(player: IPlayer) { return undefined; }"""
    code, reasons = convert("Huge Asteroid", extract_super_object(source), source,
                            "prelude", is_prelude=True)
    assert reasons == []
    assert "resources={R.MEGACREDITS: -5}" in code


def test_max_and_tag_requirements():
    source = """super({ type: CardType.AUTOMATED, name: CardName.X, tags: [], cost: 3,
                requirements: [{oxygen: 5, max}, {tag: Tag.SCIENCE, count: 2}], metadata: {} })"""
    code, reasons = convert("X", extract_super_object(source), source, "base")
    assert reasons == []
    assert "Requirements(max_oxygen=5, tags={Tag.SCIENCE: 2})" in code
