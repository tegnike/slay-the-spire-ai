"""State compaction helpers for prompts and diagnostics."""

from __future__ import annotations

from .engine import *  # noqa: F401,F403


def summarize_state(state: dict[str, Any]) -> dict[str, Any]:
    combat = state.get("combat_state") or {}
    screen_state = state.get("screen_state") or {}
    summary: dict[str, Any] = {
        "screen_type": state.get("screen_type"),
        "screen_name": state.get("screen_name"),
        "room_phase": state.get("room_phase"),
        "room_type": state.get("room_type"),
        "floor": state.get("floor"),
        "act": state.get("act"),
        "act_boss": state.get("act_boss"),
        "ascension_level": state.get("ascension_level"),
        "class": state.get("class"),
        "current_hp": state.get("current_hp"),
        "max_hp": state.get("max_hp"),
        "gold": state.get("gold"),
        "relics": [compact_relic(relic) for relic in state.get("relics") or [] if isinstance(relic, dict)],
        "potions": [compact_potion(potion) for potion in state.get("potions") or [] if isinstance(potion, dict)],
        "deck": deck_summary(state.get("deck") or []),
    }
    if combat:
        player = combat.get("player") or {}
        summary["combat"] = {
            "energy": player.get("energy"),
            "block": player.get("block"),
            "player_powers": compact_powers(player.get("powers") or []),
            "incoming_damage": estimate_incoming_damage(combat.get("monsters") or []),
            "turn": combat.get("turn"),
            "hand": [compact_card(card) for card in combat.get("hand") or [] if isinstance(card, dict)],
            "draw_pile": [compact_card(card) for card in (combat.get("draw_pile") or [])[:20] if isinstance(card, dict)],
            "discard_pile": [compact_card(card) for card in (combat.get("discard_pile") or [])[:20] if isinstance(card, dict)],
            "exhaust_pile": [compact_card(card) for card in (combat.get("exhaust_pile") or [])[:20] if isinstance(card, dict)],
            "monsters": [compact_monster(monster) for monster in combat.get("monsters") or [] if isinstance(monster, dict)],
        }
    else:
        summary["screen_state"] = {
            "for_purge": screen_state.get("for_purge"),
            "for_upgrade": screen_state.get("for_upgrade"),
            "for_transform": screen_state.get("for_transform"),
            "num_cards": screen_state.get("num_cards"),
            "any_number": screen_state.get("any_number"),
            "confirm_up": screen_state.get("confirm_up"),
            "selected_cards": [
                compact_card(card) for card in screen_state.get("selected_cards") or [] if isinstance(card, dict)
            ],
            "cards": [compact_card(card) for card in (screen_state.get("cards") or [])[:30] if isinstance(card, dict)],
            "rewards": compact_rewards(screen_state.get("rewards") or []),
            "rest_options": screen_state.get("rest_options") or [],
            "current_node": screen_state.get("current_node"),
            "next_nodes": screen_state.get("next_nodes") or [],
            "shop": compact_shop(screen_state),
            "choices": screen_choices(state, screen_state),
        }
    return summary


def compact_card(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": card.get("id"),
        "name": card.get("name"),
        "type": card.get("type"),
        "rarity": card.get("rarity"),
        "cost": card.get("cost"),
        "upgrades": card.get("upgrades"),
        "is_playable": card.get("is_playable"),
        "has_target": card.get("has_target"),
        "exhausts": card.get("exhausts"),
        "ethereal": card.get("ethereal"),
        "estimated_damage": estimate_card_damage(card),
        "estimated_block": estimate_card_block(card),
    }


def compact_monster(monster: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": monster.get("id"),
        "name": monster.get("name"),
        "current_hp": monster.get("current_hp"),
        "max_hp": monster.get("max_hp"),
        "block": monster.get("block") or 0,
        "intent": monster.get("intent"),
        "move_base_damage": monster.get("move_base_damage"),
        "move_adjusted_damage": monster.get("move_adjusted_damage"),
        "move_hits": monster.get("move_hits"),
        "incoming_damage": monster_incoming_damage(monster),
        "is_gone": monster.get("is_gone"),
        "half_dead": monster.get("half_dead"),
        "powers": compact_powers(monster.get("powers") or []),
    }


def compact_powers(powers: list[Any]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for power in powers:
        if not isinstance(power, dict):
            continue
        compact.append(
            {
                "id": power.get("id"),
                "name": power.get("name"),
                "amount": power.get("amount"),
                "damage": power.get("damage"),
                "misc": power.get("misc"),
            }
        )
    return compact


def compact_relic(relic: dict[str, Any]) -> dict[str, Any]:
    return {"id": relic.get("id"), "name": relic.get("name"), "counter": relic.get("counter")}


def compact_potion(potion: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": potion.get("id"),
        "name": potion.get("name"),
        "can_use": potion.get("can_use"),
        "can_discard": potion.get("can_discard"),
        "requires_target": potion.get("requires_target"),
    }


def deck_summary(deck: list[Any]) -> dict[str, Any]:
    cards = [compact_card(card) for card in deck if isinstance(card, dict)]
    return {
        "size": len(cards),
        "cards": cards[:40],
        "counts": count_cards(deck),
    }


def count_cards(deck: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for card in deck:
        if not isinstance(card, dict):
            continue
        name = str(card.get("name") or card.get("id") or "Unknown")
        counts[name] = counts.get(name, 0) + 1
    return counts


def compact_rewards(rewards: list[Any]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for reward in rewards:
        if not isinstance(reward, dict):
            continue
        item: dict[str, Any] = {"reward_type": reward.get("reward_type"), "gold": reward.get("gold")}
        if isinstance(reward.get("potion"), dict):
            item["potion"] = compact_potion(reward["potion"])
        if isinstance(reward.get("relic"), dict):
            item["relic"] = compact_relic(reward["relic"])
        compact.append(item)
    return compact


def compact_shop(screen_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "purge_available": screen_state.get("purge_available"),
        "purge_cost": screen_state.get("purge_cost"),
        "cards": [compact_shop_item(item) for item in screen_state.get("cards") or [] if isinstance(item, dict)],
        "relics": [compact_shop_item(item) for item in screen_state.get("relics") or [] if isinstance(item, dict)],
        "potions": [compact_shop_item(item) for item in screen_state.get("potions") or [] if isinstance(item, dict)],
    }


def compact_shop_item(item: dict[str, Any]) -> dict[str, Any]:
    compact = compact_card(item) if ("type" in item or "rarity" in item) else {"id": item.get("id"), "name": item.get("name")}
    compact["price"] = item.get("price")
    return compact


def describe_card(card: dict[str, Any]) -> str:
    name = card.get("name") or card.get("id") or "Unknown"
    upgrades = int(card.get("upgrades") or 0)
    plus = f"+{upgrades}" if upgrades else ""
    card_type = card.get("type") or "CARD"
    cost = card.get("cost")
    return f"{name}{plus} ({card_type}, cost {cost})"


def describe_monster(monster: dict[str, Any]) -> str:
    name = monster.get("name") or monster.get("id") or "Monster"
    hp = monster.get("current_hp")
    block = monster.get("block") or 0
    intent = monster.get("intent")
    damage = int(monster.get("move_adjusted_damage") or monster.get("move_base_damage") or 0)
    hits = int(monster.get("move_hits") or 1)
    attack = f", attack {damage}x{hits}" if damage > 0 else ""
    return f"{name} (hp {hp}, block {block}, intent {intent}{attack})"


def screen_choices(state: dict[str, Any], screen_state: dict[str, Any]) -> list[str]:
    raw_choices = state.get("choice_list") or screen_state.get("options") or screen_state.get("choices") or []
    choices: list[str] = []
    if not isinstance(raw_choices, list):
        return choices
    for choice in raw_choices:
        if isinstance(choice, str):
            choices.append(choice)
        elif isinstance(choice, dict):
            choices.append(str(choice.get("name") or choice.get("text") or choice.get("label") or choice))
        else:
            choices.append(str(choice))
    return choices


