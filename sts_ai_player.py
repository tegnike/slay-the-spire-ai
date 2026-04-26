#!/usr/bin/env python3
"""Minimal Slay the Spire AI process for CommunicationMod.

Protocol rule: stdout is reserved for CommunicationMod messages only.
All diagnostics go to files under logs/.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
LOG_DIR = Path(os.environ.get("STS_AI_LOG_DIR", ROOT / "logs"))
CODEX_APP_COMMAND = Path("/Applications/Codex.app/Contents/Resources/codex")
OPENAI_API_DISABLED_REASON: str | None = None
POTION_USED_TURNS: set[tuple[str, int, int, int]] = set()


ATTACK_PRIORITY = {
    "Bash": 100,
    "Strike_R": 80,
    "Strike_G": 80,
    "Strike_B": 80,
    "Strike_P": 80,
    "Strike": 75,
}

BLOCK_PRIORITY = {
    "Defend_R": 90,
    "Defend_G": 90,
    "Defend_B": 90,
    "Defend_P": 90,
    "Defend": 85,
}

CARD_REWARD_PRIORITY = {
    "Shockwave": 140,
    "Offering": 135,
    "Immolate": 130,
    "Feed": 125,
    "Bludgeon": 122,
    "Fiend Fire": 120,
    "Reaper": 115,
    "Corruption": 105,
    "Demon Form": 100,
    "Inflame": 96,
    "Disarm": 94,
    "Carnage": 92,
    "Whirlwind": 91,
    "Uppercut": 90,
    "Shrug It Off": 88,
    "Battle Trance": 86,
    "Pommel Strike": 82,
    "Hemokinesis": 80,
    "Twin Strike": 78,
    "Wild Strike": 77,
    "Clothesline": 76,
    "Headbutt": 74,
    "True Grit": 72,
    "Thunderclap": 70,
    "Anger": 68,
    "Cleave": 66,
    "Armaments": 64,
    "Seeing Red": 62,
    "Body Slam": 35,
    "Dual Wield": 30,
}

SHOP_CARD_PRIORITY = {
    **CARD_REWARD_PRIORITY,
    "Membership Card": 120,
    "Pen Nib": 115,
    "Pocketwatch": 95,
    "Gambler's Brew": 70,
    "Explosive Potion": 58,
    "Dexterity Potion": 45,
}

SHOP_VISITED_KEYS: set[tuple[str, int, int]] = set()


CARD_BASE_DAMAGE = {
    "Strike_R": 6,
    "Strike_G": 6,
    "Strike_B": 6,
    "Strike_P": 6,
    "Strike": 6,
    "Bash": 8,
    "Anger": 6,
    "Pommel Strike": 9,
    "Headbutt": 9,
    "Clothesline": 12,
    "Cleave": 8,
    "Thunderclap": 4,
    "Uppercut": 13,
    "Carnage": 20,
    "Hemokinesis": 15,
    "Immolate": 21,
    "Bludgeon": 32,
    "Fiend Fire": 21,
    "Whirlwind": 15,
    "Twin Strike": 10,
    "Wild Strike": 12,
    "Clash": 14,
    "Sword Boomerang": 9,
    "Perfected Strike": 12,
    "Iron Wave": 5,
    "Searing Blow": 12,
    "Sever Soul": 16,
}

CARD_BASE_BLOCK = {
    "Defend_R": 5,
    "Defend_G": 5,
    "Defend_B": 5,
    "Defend_P": 5,
    "Defend": 5,
    "Shrug It Off": 8,
    "True Grit": 7,
    "Armaments": 5,
    "Iron Wave": 5,
    "Flame Barrier": 12,
    "Power Through": 15,
    "Ghostly Armor": 10,
    "Impervious": 30,
    "Entrench": 0,
    "Second Wind": 10,
}

FRONTLOAD_ATTACKS = {
    "Anger",
    "Bludgeon",
    "Carnage",
    "Cleave",
    "Clothesline",
    "Feed",
    "Hemokinesis",
    "Immolate",
    "Pommel Strike",
    "Sever Soul",
    "Thunderclap",
    "Twin Strike",
    "Uppercut",
    "Whirlwind",
    "Wild Strike",
}

SPECULATIVE_SYNERGY_CARDS = {
    "Barricade",
    "Body Slam",
    "Corruption",
    "Dark Embrace",
    "Dual Wield",
    "Feel No Pain",
    "Fire Breathing",
    "Juggernaut",
    "Rupture",
}

REWARD_PRIORITY = {
    "RELIC": 120,
    "CARD": 100,
    "GOLD": 90,
    "STOLEN_GOLD": 88,
    "POTION": 70,
    "EMERALD_KEY": 30,
    "SAPPHIRE_KEY": 25,
}


@dataclass(frozen=True)
class Options:
    auto_start: bool
    character: str
    ascension: int
    seed: str | None
    use_openai_api: bool
    openai_model: str
    openai_api_base: str
    openai_timeout: float
    use_codex: bool
    codex_model: str
    codex_command: str
    codex_timeout: float


@dataclass(frozen=True)
class LegalAction:
    action_id: str
    command: str
    description: str


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_DIR / "session.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def append_jsonl(name: str, payload: Any) -> None:
    path = LOG_DIR / name
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        handle.write("\n")


def normalize_available(raw: dict[str, Any]) -> set[str]:
    return {str(command).lower() for command in raw.get("available_commands", [])}


def choose_command(raw: dict[str, Any], options: Options) -> str:
    rule_command = choose_rule_command(raw, options)
    if should_skip_codex(raw):
        return rule_command

    if options.use_openai_api:
        try:
            return choose_openai_api_command(raw, options, rule_command)
        except Exception:
            logging.exception("OpenAI API decision failed; falling back to rule command")
            return rule_command

    if options.use_codex:
        try:
            return choose_codex_command(raw, options, rule_command)
        except Exception:
            logging.exception("Codex decision failed; falling back to rule command")
            return rule_command

    return rule_command


def should_skip_codex(raw: dict[str, Any]) -> bool:
    state = raw.get("game_state") or {}
    screen_name = str(state.get("screen_name") or "").upper()
    if screen_name == "FTUE":
        return True
    return False


def choose_rule_command(raw: dict[str, Any], options: Options) -> str:
    if "error" in raw:
        logging.warning("CommunicationMod error: %s", raw.get("error"))
        return "STATE"

    available = normalize_available(raw)
    state = raw.get("game_state") or {}
    in_game = bool(raw.get("in_game"))

    if not in_game:
        if options.auto_start and "start" in available:
            parts = ["START", options.character.upper(), str(options.ascension)]
            if options.seed:
                parts.append(options.seed)
            return " ".join(parts)
        time.sleep(1)
        return "STATE"

    if "end" in available and state.get("combat_state"):
        return choose_combat_command(state, available)

    return choose_screen_command(state, available)


def choose_combat_command(state: dict[str, Any], available: set[str]) -> str:
    combat = state.get("combat_state") or {}
    hand = combat.get("hand") or []
    player = combat.get("player") or {}
    monsters = combat.get("monsters") or []

    energy = int(player.get("energy") or 0)
    incoming = estimate_incoming_damage(monsters)
    current_block = int(player.get("block") or 0)
    target_index = choose_target(monsters)
    current_hp = int(player.get("current_hp") or state.get("current_hp") or 0)

    lethal = choose_lethal_attack(hand, monsters, energy)
    if lethal is not None:
        card_index, monster_index = lethal
        return f"PLAY {card_index + 1} {monster_index}"

    potion = choose_potion_command(state, available)
    if potion is not None:
        return potion

    utility = best_targeted_utility_card(hand, energy, monsters, state, incoming, current_block)
    if utility is not None:
        card_index, monster_index = utility
        return f"PLAY {card_index + 1} {monster_index}"

    setup = best_setup_card(hand, energy, state, incoming, current_block)
    if setup is not None:
        return f"PLAY {setup + 1}"

    if target_index is not None:
        attack = best_attack_card(hand, energy, monsters[target_index])
        if attack is not None and should_attack_over_block(
            hand[attack],
            monsters[target_index],
            incoming,
            current_block,
            current_hp,
            state,
        ):
            return f"PLAY {attack + 1} {target_index}"

    if incoming > current_block:
        block = best_block_card(hand, energy)
        if block is not None and should_play_block_card(hand[block], state, incoming, current_block, current_hp):
            return f"PLAY {block + 1}"

    if target_index is not None:
        attack = best_attack_card(hand, energy, monsters[target_index])
        if attack is not None:
            return f"PLAY {attack + 1} {target_index}"

    setup = best_setup_card(hand, energy, state, incoming, current_block, allow_slow=True)
    if setup is not None:
        return f"PLAY {setup + 1}"

    return "END"


def should_attack_over_block(
    card: dict[str, Any],
    target: dict[str, Any],
    incoming: int,
    current_block: int,
    current_hp: int,
    state: dict[str, Any],
) -> bool:
    damage_gap = max(incoming - current_block, 0)
    if damage_gap <= 0:
        return True
    target_hp = int(target.get("current_hp") or 0) + int(target.get("block") or 0)
    damage = estimate_card_damage(card)
    if damage >= target_hp:
        return True
    act = int(state.get("act") or 1)
    floor = int(state.get("floor") or 0)
    room_type = str(state.get("room_type") or "")
    if act == 1 and "Elite" in room_type and damage_gap <= 10 and current_hp > damage_gap + 35 and damage >= 8:
        return True
    if act == 1 and floor <= 8 and damage_gap <= 7 and current_hp > damage_gap + 18:
        return True
    if damage >= max(target_hp - 6, 1) and damage_gap <= 10 and current_hp > damage_gap + 14:
        return True
    return False


def should_play_block_card(
    card: dict[str, Any],
    state: dict[str, Any],
    incoming: int,
    current_block: int,
    current_hp: int,
) -> bool:
    damage_gap = max(incoming - current_block, 0)
    if damage_gap <= 0:
        return False
    if is_gremlin_nob_fight(state):
        # Skills make Nob stronger. Block only when the HP loss is genuinely dangerous.
        return current_hp <= damage_gap + 18 or damage_gap >= 16
    if is_lagavulin_fight(state) and lagavulin_is_debuffing(state):
        return False
    return estimate_card_block(card) > 0


def best_setup_card(
    hand: list[dict[str, Any]],
    energy: int,
    state: dict[str, Any],
    incoming: int,
    current_block: int,
    *,
    allow_slow: bool = False,
) -> int | None:
    candidates: list[tuple[int, int]] = []
    damage_gap = max(incoming - current_block, 0)
    dangerous_room = is_dangerous_combat(state)
    for index, card in enumerate(hand):
        if not is_playable(card, energy) or card.get("has_target"):
            continue
        if estimate_card_block(card) > 0:
            continue
        score = setup_card_score(card, state, damage_gap, dangerous_room, allow_slow)
        if score > 0:
            candidates.append((score, index))
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: (candidate[0], -candidate[1]))[1]


def setup_card_score(
    card: dict[str, Any],
    state: dict[str, Any],
    damage_gap: int,
    dangerous_room: bool,
    allow_slow: bool,
) -> int:
    name = normalize_card_name(card)
    card_type = str(card.get("type") or "").upper()
    if is_gremlin_nob_fight(state) and card_type == "SKILL" and name not in {"Offering"}:
        return 0
    if is_lagavulin_fight(state) and lagavulin_is_sleeping(state) and name in {"Shockwave"}:
        return 0

    deck = state.get("deck") or []
    priorities = {
        "Inflame": 120,
        "Demon Form": 105 if dangerous_room else 50,
        "Metallicize": 90,
        "Shockwave": 95 if damage_gap > 0 or dangerous_room else 45,
        "Offering": 90,
        "Feel No Pain": 85 if deck_has_exhaust_support(deck) else 35,
        "Dark Embrace": 70 if deck_has_exhaust_support(deck) else 20,
        "Corruption": 78 if deck_has_exhaust_support(deck) or dangerous_room else 20,
        "Brutality": 42 if allow_slow and dangerous_room else 0,
        "Barricade": 20 if allow_slow else 0,
    }
    score = priorities.get(name, 0)
    if card_type == "POWER" and score == 0 and (dangerous_room or allow_slow):
        score = 30
    return score


def is_dangerous_combat(state: dict[str, Any]) -> bool:
    room_type = str(state.get("room_type") or "")
    return room_type in {"MonsterRoomElite", "BossRoom"} or "Elite" in room_type or "Boss" in room_type


def is_gremlin_nob_fight(state: dict[str, Any]) -> bool:
    return any("gremlin nob" in normalize_name(str(monster.get("name") or monster.get("id") or "")) for monster in combat_monsters(state))


def is_lagavulin_fight(state: dict[str, Any]) -> bool:
    return any("lagavulin" in normalize_name(str(monster.get("name") or monster.get("id") or "")) for monster in combat_monsters(state))


def lagavulin_is_sleeping(state: dict[str, Any]) -> bool:
    for monster in combat_monsters(state):
        if "lagavulin" not in normalize_name(str(monster.get("name") or monster.get("id") or "")):
            continue
        intent = str(monster.get("intent") or "").upper()
        return "SLEEP" in intent
    return False


def lagavulin_is_debuffing(state: dict[str, Any]) -> bool:
    for monster in combat_monsters(state):
        if "lagavulin" not in normalize_name(str(monster.get("name") or monster.get("id") or "")):
            continue
        intent = str(monster.get("intent") or "").upper()
        return "DEBUFF" in intent
    return False


def combat_monsters(state: dict[str, Any]) -> list[dict[str, Any]]:
    combat = state.get("combat_state") or {}
    return [monster for monster in combat.get("monsters") or [] if isinstance(monster, dict)]


def choose_codex_command(raw: dict[str, Any], options: Options, fallback_command: str) -> str:
    if "error" in raw or not raw.get("in_game"):
        return fallback_command

    available = normalize_available(raw)
    state = raw.get("game_state") or {}
    legal_actions = build_legal_actions(state, available, fallback_command)
    if not legal_actions:
        return fallback_command

    action_payload = [
        {"action_id": action.action_id, "command": action.command, "description": action.description}
        for action in legal_actions
    ]
    prompt = build_codex_prompt(state, action_payload, fallback_command)
    decision = run_codex_cli(prompt, options)
    action_id = str(decision.get("action_id") or "")
    by_id = {action.action_id: action for action in legal_actions}
    action = by_id.get(action_id)
    if action is None:
        logging.warning("Codex returned illegal action_id=%s", action_id)
        return fallback_command

    append_jsonl(
        "codex_decisions.jsonl",
        {
            "time": time.time(),
            "model": options.codex_model,
            "action_id": action.action_id,
            "command": action.command,
            "rationale": decision.get("rationale"),
            "fallback": fallback_command,
        },
    )
    return action.command


def choose_openai_api_command(raw: dict[str, Any], options: Options, fallback_command: str) -> str:
    if "error" in raw or not raw.get("in_game"):
        return fallback_command

    global OPENAI_API_DISABLED_REASON
    if OPENAI_API_DISABLED_REASON:
        return fallback_command

    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("STS_AI_OPENAI_API_KEY")
    if not api_key:
        logging.warning("OPENAI_API_KEY is not set; using rule command")
        return fallback_command

    available = normalize_available(raw)
    state = raw.get("game_state") or {}
    legal_actions = build_legal_actions(state, available, fallback_command)
    if not legal_actions:
        return fallback_command

    try:
        decision = run_openai_responses_api(
            build_decision_payload(state, legal_actions, fallback_command),
            [action.action_id for action in legal_actions],
            options,
            api_key,
        )
    except urllib.error.HTTPError as error:
        if error.code in {401, 403}:
            OPENAI_API_DISABLED_REASON = f"http_{error.code}"
            logging.warning("OpenAI API disabled for this process after authentication failure: %s", OPENAI_API_DISABLED_REASON)
            return fallback_command
        raise
    action_id = str(decision.get("action_id") or "")
    by_id = {action.action_id: action for action in legal_actions}
    action = by_id.get(action_id)
    if action is None:
        logging.warning("OpenAI API returned illegal action_id=%s", action_id)
        return fallback_command

    final_command = action.command
    override_reason = openai_override_reason(state, action.command, fallback_command, decision)
    if override_reason:
        logging.warning(
            "OpenAI API decision overridden: reason=%s model_command=%s fallback=%s",
            override_reason,
            action.command,
            fallback_command,
        )
        final_command = fallback_command

    append_jsonl(
        "openai_decisions.jsonl",
        {
            "time": time.time(),
            "model": options.openai_model,
            "action_id": action.action_id,
            "command": final_command,
            "model_command": action.command,
            "rationale": decision.get("rationale"),
            "confidence": decision.get("confidence"),
            "fallback": fallback_command,
            "override_reason": override_reason,
        },
    )
    return final_command


def openai_override_reason(
    state: dict[str, Any],
    model_command: str,
    fallback_command: str,
    decision: dict[str, Any],
) -> str | None:
    if model_command == fallback_command:
        return None

    try:
        confidence = float(decision.get("confidence"))
    except (TypeError, ValueError):
        confidence = 1.0
    if confidence < 0.25:
        return "low_confidence"

    combat = state.get("combat_state") or {}
    if not combat:
        return screen_override_reason(state, model_command, fallback_command)

    screen_type = str(state.get("screen_type") or state.get("screen_name") or "").upper()
    if screen_type not in {"", "NONE"}:
        reason = screen_override_reason(state, model_command, fallback_command)
        if reason:
            return reason

    if fallback_command.upper().startswith("POTION ") and not model_command.upper().startswith("POTION "):
        return "ignored_rule_potion"

    monsters = combat.get("monsters") or []
    player = combat.get("player") or {}
    incoming = estimate_incoming_damage(monsters)
    current_block = int(player.get("block") or 0)
    current_hp = int(player.get("current_hp") or state.get("current_hp") or 0)
    damage_gap = max(incoming - current_block, 0)
    if damage_gap <= 0 and model_command_is_pure_block_play(model_command, combat):
        return "no_incoming_avoid_block"

    if not fallback_is_defensive_play(fallback_command, combat):
        if model_command.upper().startswith("POTION USE") and potion_used_this_combat_turn(state):
            return "second_potion_same_turn"
        return None

    if damage_gap < 10 and current_hp > damage_gap + 18:
        return None

    if (
        is_dangerous_combat(state)
        and current_hp > damage_gap + 30
        and model_command_attack_damage(model_command, combat) >= 10
    ):
        return None

    if model_command_is_lethal_attack(model_command, combat):
        return None
    if model_command_is_defensive_play(model_command, combat):
        if model_command.upper().startswith("POTION USE") and potion_used_this_combat_turn(state):
            return "second_potion_same_turn"
        return None

    return "high_incoming_prefers_defense"


def screen_override_reason(state: dict[str, Any], model_command: str, fallback_command: str) -> str | None:
    model_score = screen_command_score(state, model_command)
    fallback_score = screen_command_score(state, fallback_command)
    if model_score is None or fallback_score is None:
        return None
    if model_score + screen_override_margin(state) < fallback_score:
        return "low_heuristic_screen_score"
    return None


def screen_override_margin(state: dict[str, Any]) -> int:
    screen_type = str(state.get("screen_type") or state.get("screen_name") or "").upper()
    if screen_type == "CARD_REWARD":
        return 10
    if screen_type == "EVENT":
        return 14
    return 18


def screen_command_score(state: dict[str, Any], command: str) -> int | None:
    parts = command.split()
    if not parts:
        return None
    verb = parts[0].upper()
    screen_type = str(state.get("screen_type") or state.get("screen_name") or "").upper()
    screen_state = state.get("screen_state") or {}

    if screen_type == "CARD_REWARD":
        if verb == "SKIP":
            return 55
        index = command_choice_index(parts)
        cards = screen_state.get("cards") or []
        if index is not None and 0 <= index < len(cards) and isinstance(cards[index], dict):
            if state.get("combat_state"):
                return combat_generated_card_score(cards[index], state)
            return card_reward_score(cards[index], state)
    if screen_type == "EVENT":
        index = command_choice_index(parts)
        choices = screen_choices(state, screen_state)
        if index is not None and 0 <= index < len(choices):
            return event_choice_score(choices[index], state)
    if screen_type == "MAP":
        index = command_choice_index(parts)
        nodes = screen_state.get("next_nodes") or []
        if index is not None and 0 <= index < len(nodes) and isinstance(nodes[index], dict):
            return map_node_score(nodes[index], state)
    if screen_type == "GRID":
        index = command_choice_index(parts)
        if verb in {"CONFIRM", "PROCEED"} and grid_selection_is_ready(screen_state):
            return 100
        cards = screen_state.get("cards") or []
        if index is not None and 0 <= index < len(cards) and isinstance(cards[index], dict):
            return grid_card_score(cards[index], screen_state)
    if screen_type == "REST":
        index = command_choice_index(parts)
        options = screen_choices(state, screen_state) or [str(option) for option in screen_state.get("rest_options") or []]
        if index is not None and 0 <= index < len(options):
            return rest_option_score(options[index], state)
    return None


def command_choice_index(parts: list[str]) -> int | None:
    if len(parts) < 2 or parts[0].upper() != "CHOOSE":
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def build_decision_payload(
    state: dict[str, Any],
    legal_actions: list[LegalAction],
    fallback_command: str,
) -> dict[str, Any]:
    return {
        "policy": {
            "objective": "Win the run. Preserve HP, but recognize that faster kills are often the best HP preservation in Act 1.",
            "constraints": [
                "Choose exactly one legal action_id.",
                "Take immediate lethal and enemy-killing lines over passive blocking.",
                "Avoid overblocking low incoming damage when a strong attack advances a kill.",
                "Do not play pure block cards when there is no incoming damage.",
                "When unblocked incoming damage is high, block or use a defensive potion unless an attack kills an attacker immediately.",
                "For Ironclad Act 1, value frontloaded damage, Bash/Vulnerable setup, premium attacks, and strong relics.",
                "Do not take speculative synergy cards unless the current deck already supports them.",
                "Use potions for lethal, elite/boss danger, or to prevent a large HP loss; do not waste them on easy turns.",
                "Use the fallback action if it is clearly reasonable and no better legal action exists.",
            ],
        },
        "state": summarize_state(state),
        "legal_actions": [
            {"action_id": action.action_id, "command": action.command, "description": action.description}
            for action in legal_actions
        ],
        "fallback_action": fallback_command,
    }


def build_codex_prompt(
    state: dict[str, Any],
    legal_actions: list[dict[str, str]],
    fallback_command: str,
) -> str:
    payload = {
        "state": summarize_state(state),
        "legal_actions": legal_actions,
        "fallback_action": fallback_command,
    }
    return (
        "You are choosing one Slay the Spire action from a fixed legal action list.\n"
        "Return only JSON with this exact shape: "
        '{"action_id":"<one legal action_id>","rationale":"<brief reason>"}.\n'
        "The action_id must exactly match one legal_actions entry. Do not invent commands.\n\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )


def run_codex_cli(prompt: str, options: Options) -> dict[str, Any]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    schema_path = write_codex_output_schema()
    output_path = tempfile.NamedTemporaryFile(
        prefix="sts-codex-output-",
        suffix=".json",
        dir=LOG_DIR,
        delete=False,
    ).name
    command = [
        options.codex_command,
        "exec",
        "--skip-git-repo-check",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "-c",
        'model_reasoning_effort="low"',
        "--output-schema",
        schema_path,
        "-o",
        output_path,
        "-m",
        options.codex_model,
        "-",
    ]
    started = time.time()
    result = subprocess.run(
        command,
        input=prompt,
        text=True,
        capture_output=True,
        timeout=options.codex_timeout,
        cwd=str(ROOT),
        check=False,
    )
    elapsed = time.time() - started
    stdout_tail = result.stdout[-4000:]
    stderr_tail = result.stderr[-4000:]
    logging.info("codex_cli exit=%s elapsed=%.2f", result.returncode, elapsed)
    if result.returncode != 0:
        logging.warning("codex_cli stderr=%s stdout=%s", stderr_tail, stdout_tail)
        raise RuntimeError(f"codex exec failed with exit code {result.returncode}")

    output_text = Path(output_path).read_text(encoding="utf-8").strip()
    if not output_text:
        output_text = stdout_tail.strip()
    return parse_codex_json(output_text)


def run_openai_responses_api(
    payload: dict[str, Any],
    action_ids: list[str],
    options: Options,
    api_key: str,
) -> dict[str, Any]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action_id": {"type": "string", "enum": action_ids},
            "rationale": {"type": "string"},
            "confidence": {"type": "number"},
        },
        "required": ["action_id", "rationale", "confidence"],
    }
    request_body = {
        "model": options.openai_model,
        "input": [
            {
                "role": "system",
                "content": (
                    "You are a Slay the Spire policy engine. Choose one action_id from the provided "
                    "legal_actions. Return only the structured JSON object. Do not invent actions."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "sts_action_decision",
                "strict": True,
                "schema": schema,
            }
        },
        "max_output_tokens": 300,
        "store": False,
    }

    url = options.openai_api_base.rstrip("/") + "/responses"
    started = time.time()
    request = urllib.request.Request(
        url,
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=options.openai_timeout) as response:
            response_text = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[-2000:]
        logging.warning("openai_api http_status=%s body=%s", error.code, detail)
        raise

    elapsed = time.time() - started
    parsed = json.loads(response_text)
    output_text = extract_response_text(parsed)
    logging.info("openai_api elapsed=%.2f model=%s", elapsed, options.openai_model)
    if not output_text:
        raise ValueError("OpenAI API response did not contain output text")
    decision = json.loads(output_text)
    if not isinstance(decision, dict):
        raise ValueError("OpenAI API decision was not a JSON object")
    return decision


def extract_response_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return str(response["output_text"])
    texts: list[str] = []
    for item in response.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str):
                texts.append(text)
    return "".join(texts).strip()


def fallback_is_defensive_play(command: str, combat: dict[str, Any]) -> bool:
    play = parse_play_command(command)
    if play is None:
        return False
    card = combat_card_at(combat, play[0])
    return bool(card and not card.get("has_target") and estimate_card_block(card) > 0)


def model_command_is_defensive_play(command: str, combat: dict[str, Any]) -> bool:
    play = parse_play_command(command)
    if play is None:
        return command.upper().startswith("POTION ")
    card = combat_card_at(combat, play[0])
    if not card:
        return False
    name = normalize_card_name(card)
    if name in {"Disarm", "Shockwave", "Intimidate"}:
        return True
    return bool(not card.get("has_target") and estimate_card_block(card) > 0)


def model_command_is_pure_block_play(command: str, combat: dict[str, Any]) -> bool:
    play = parse_play_command(command)
    if play is None:
        return False
    card = combat_card_at(combat, play[0])
    return bool(card and not card.get("has_target") and estimate_card_block(card) > 0)


def model_command_is_lethal_attack(command: str, combat: dict[str, Any]) -> bool:
    play = parse_play_command(command)
    if play is None or play[1] is None:
        return False
    card = combat_card_at(combat, play[0])
    monster = combat_monster_at(combat, play[1])
    if card is None or monster is None or not card.get("has_target"):
        return False
    damage = estimate_card_damage(card)
    hp_with_block = int(monster.get("current_hp") or 0) + int(monster.get("block") or 0)
    return damage > 0 and damage >= hp_with_block


def model_command_attack_damage(command: str, combat: dict[str, Any]) -> int:
    play = parse_play_command(command)
    if play is None or play[1] is None:
        return 0
    card = combat_card_at(combat, play[0])
    if card is None or not card.get("has_target"):
        return 0
    return estimate_card_damage(card)


def parse_play_command(command: str) -> tuple[int, int | None] | None:
    parts = command.split()
    if len(parts) < 2 or parts[0].upper() != "PLAY":
        return None
    try:
        card_index = int(parts[1]) - 1
        target_index = int(parts[2]) if len(parts) >= 3 else None
    except ValueError:
        return None
    return card_index, target_index


def combat_card_at(combat: dict[str, Any], index: int) -> dict[str, Any] | None:
    hand = combat.get("hand") or []
    if index < 0 or index >= len(hand):
        return None
    card = hand[index]
    return card if isinstance(card, dict) else None


def combat_monster_at(combat: dict[str, Any], index: int) -> dict[str, Any] | None:
    monsters = combat.get("monsters") or []
    if index < 0 or index >= len(monsters):
        return None
    monster = monsters[index]
    return monster if isinstance(monster, dict) else None


def write_codex_output_schema() -> str:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action_id": {"type": "string"},
            "rationale": {"type": "string"},
        },
        "required": ["action_id", "rationale"],
    }
    path = LOG_DIR / "codex_action_schema.json"
    path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
    return str(path)


def parse_codex_json(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    for match in reversed(re.findall(r"\{[^{}]*\"action_id\"[^{}]*\}", text, flags=re.DOTALL)):
        parsed = json.loads(match)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("Codex output did not contain a JSON action")


def build_legal_actions(
    state: dict[str, Any],
    available: set[str],
    fallback_command: str,
) -> list[LegalAction]:
    actions: list[LegalAction] = []

    combat = state.get("combat_state") or {}
    screen_type = str(state.get("screen_type") or state.get("screen_name") or "").upper()
    if combat and screen_type in {"", "NONE"} and ({"play", "end", "potion"} & available):
        add_combat_actions(actions, combat, available)
        add_potion_actions(actions, state, combat, available)
    else:
        add_screen_actions(actions, state, available)

    if command_is_available(fallback_command, available):
        prepend_action(actions, LegalAction("fallback", fallback_command, "Rule-based fallback action."))

    if "state" in available and not has_non_passive_action(actions):
        actions.append(LegalAction("state", "STATE", "Refresh the game state without taking a gameplay action."))

    return dedupe_actions(actions)


def has_non_passive_action(actions: list[LegalAction]) -> bool:
    passive_verbs = {"STATE", "WAIT"}
    return any(action.command.split(" ", 1)[0].upper() not in passive_verbs for action in actions)


def add_combat_actions(actions: list[LegalAction], combat: dict[str, Any], available: set[str]) -> None:
    hand = combat.get("hand") or []
    player = combat.get("player") or {}
    monsters = combat.get("monsters") or []
    energy = int(player.get("energy") or 0)
    live_monsters = [
        (index, monster)
        for index, monster in enumerate(monsters)
        if not monster.get("is_gone") and not monster.get("half_dead") and int(monster.get("current_hp") or 0) > 0
    ]

    if "play" in available:
        for card_index, card in enumerate(hand):
            if not is_playable(card, energy):
                continue
            card_desc = describe_card(card)
            if card.get("has_target"):
                for target_index, monster in live_monsters:
                    damage = estimate_card_damage(card)
                    monster_hp = int(monster.get("current_hp") or 0) + int(monster.get("block") or 0)
                    lethal = " lethal" if damage >= monster_hp and damage > 0 else ""
                    actions.append(
                        LegalAction(
                            f"play_{card_index + 1}_{target_index}",
                            f"PLAY {card_index + 1} {target_index}",
                            f"Play {card_desc} on {describe_monster(monster)}; estimated damage {damage}{lethal}.",
                        )
                    )
            else:
                block = estimate_card_block(card)
                damage = estimate_card_damage(card)
                effect = f"estimated block {block}" if block else f"estimated damage {damage}" if damage else "non-damage utility"
                actions.append(
                    LegalAction(
                        f"play_{card_index + 1}",
                        f"PLAY {card_index + 1}",
                        f"Play {card_desc}; {effect}.",
                    )
                )

    if "end" in available:
        actions.append(LegalAction("end", "END", "End the current turn."))


def add_potion_actions(
    actions: list[LegalAction],
    state: dict[str, Any],
    combat: dict[str, Any],
    available: set[str],
) -> None:
    if "potion" not in available:
        return
    potions = state.get("potions") or []
    monsters = combat.get("monsters") or []
    live_monsters = [
        (index, monster)
        for index, monster in enumerate(monsters)
        if isinstance(monster, dict)
        and not monster.get("is_gone")
        and not monster.get("half_dead")
        and int(monster.get("current_hp") or 0) > 0
    ]
    for slot, potion in enumerate(potions):
        if not isinstance(potion, dict) or not potion.get("can_use"):
            continue
        potion_name = str(potion.get("name") or potion.get("id") or "Potion")
        if is_smoke_bomb(potion):
            actions.append(
                LegalAction(
                    f"potion_use_{slot}",
                    f"POTION Use {slot}",
                    "Use Smoke Bomb to escape a dangerous normal combat. Never use it in elite or boss fights.",
                )
            )
        elif potion.get("requires_target"):
            for target_index, monster in live_monsters:
                actions.append(
                    LegalAction(
                        f"potion_use_{slot}_{target_index}",
                        f"POTION Use {slot} {target_index}",
                        f"Use {potion_name} on {describe_monster(monster)}.",
                    )
                )
        else:
            actions.append(
                LegalAction(
                    f"potion_use_{slot}",
                    f"POTION Use {slot}",
                    f"Use {potion_name}. Save potions unless this prevents major damage, creates lethal, or handles an elite/boss danger.",
                )
            )


def choose_potion_command(state: dict[str, Any], available: set[str]) -> str | None:
    if "potion" not in available:
        return None
    if potion_used_this_combat_turn(state):
        return None
    combat = state.get("combat_state") or {}
    potions = state.get("potions") or []
    monsters = combat.get("monsters") or []
    player = combat.get("player") or {}
    incoming = estimate_incoming_damage(monsters)
    current_block = int(player.get("block") or 0)
    current_hp = int(state.get("current_hp") or player.get("current_hp") or 0)
    room_type = str(state.get("room_type") or "")
    is_dangerous_room = is_dangerous_combat(state)
    damage_gap = incoming - current_block

    live_monsters = [
        (index, monster)
        for index, monster in enumerate(monsters)
        if isinstance(monster, dict)
        and not monster.get("is_gone")
        and not monster.get("half_dead")
        and int(monster.get("current_hp") or 0) > 0
    ]

    for slot, potion in enumerate(potions):
        if not isinstance(potion, dict) or not potion.get("can_use"):
            continue
        name = normalize_name(str(potion.get("name") or potion.get("id") or ""))
        if "fire" in name:
            target = potion_damage_lethal_target(live_monsters, 20)
            if target is not None:
                return f"POTION Use {slot} {target}"
        if "explosive" in name and potion_damage_kills_any(live_monsters, 10):
            return f"POTION Use {slot}"

    if damage_gap < 12 and current_hp > damage_gap + 12 and not is_dangerous_room:
        return None

    for slot, potion in enumerate(potions):
        if not isinstance(potion, dict) or not potion.get("can_use"):
            continue
        name = normalize_name(str(potion.get("name") or potion.get("id") or ""))
        if "block" in name or "essence of steel" in name or "ghost in a jar" in name:
            return f"POTION Use {slot}"
        if ("skill" in name or "attack" in name or "power" in name) and should_use_card_potion(
            state,
            damage_gap,
            current_hp,
            is_dangerous_room,
        ):
            return f"POTION Use {slot}"
        if ("strength" in name or "flex" in name) and is_dangerous_room:
            return f"POTION Use {slot}"
        if "duplication" in name and should_use_duplication_potion(state, damage_gap, is_dangerous_room):
            return f"POTION Use {slot}"
        if "weak" in name:
            target = highest_incoming_monster(live_monsters)
            if target is not None and damage_gap >= 10:
                return f"POTION Use {slot} {target}"
        if "smoke bomb" in name and should_use_smoke_bomb(state, damage_gap, current_hp, is_dangerous_room):
            return f"POTION Use {slot}"
    return None


def potion_used_this_combat_turn(state: dict[str, Any]) -> bool:
    key = combat_turn_key(state)
    return key is not None and key in POTION_USED_TURNS


def remember_potion_use(command: str, payload: dict[str, Any]) -> None:
    if not command.upper().startswith("POTION USE"):
        return
    state = payload.get("game_state") or {}
    key = combat_turn_key(state)
    if key is not None:
        POTION_USED_TURNS.add(key)


def combat_turn_key(state: dict[str, Any]) -> tuple[str, int, int, int] | None:
    combat = state.get("combat_state") or {}
    if not combat:
        return None
    return (
        str(state.get("seed") or ""),
        int(state.get("act") or 0),
        int(state.get("floor") or 0),
        int(combat.get("turn") or 0),
    )


def should_use_card_potion(
    state: dict[str, Any],
    damage_gap: int,
    current_hp: int,
    is_dangerous_room: bool,
) -> bool:
    if is_dangerous_room:
        return damage_gap >= 8 or current_hp <= 45
    act = int(state.get("act") or 1)
    if act >= 2 and damage_gap >= 14 and current_hp <= damage_gap + 28:
        return True
    return current_hp <= 24 and damage_gap >= max(current_hp - 8, 10)


def should_use_duplication_potion(state: dict[str, Any], damage_gap: int, is_dangerous_room: bool) -> bool:
    if not is_dangerous_room and damage_gap < 16:
        return False
    combat = state.get("combat_state") or {}
    hand = combat.get("hand") or []
    player = combat.get("player") or {}
    energy = int(player.get("energy") or 0)
    monsters = combat.get("monsters") or []
    target_index = choose_target(monsters)
    if target_index is None:
        return False
    attack_index = best_attack_card(hand, energy, monsters[target_index])
    if attack_index is None:
        return False
    damage = estimate_card_damage(hand[attack_index])
    target_hp = int(monsters[target_index].get("current_hp") or 0) + int(monsters[target_index].get("block") or 0)
    if damage >= 16 and (is_dangerous_room or target_hp <= damage * 2):
        return True
    return damage_gap >= 20 and damage >= 12


def is_smoke_bomb(potion: dict[str, Any]) -> bool:
    return "smoke bomb" in normalize_name(str(potion.get("name") or potion.get("id") or ""))


def should_use_smoke_bomb(
    state: dict[str, Any],
    damage_gap: int,
    current_hp: int,
    is_dangerous_room: bool,
) -> bool:
    if is_dangerous_room:
        return False
    room_type = str(state.get("room_type") or "")
    if "MonsterRoom" not in room_type:
        return False
    return current_hp <= 18 and damage_gap >= max(current_hp - 6, 8)


def potion_damage_lethal_target(live_monsters: list[tuple[int, dict[str, Any]]], damage: int) -> int | None:
    candidates: list[tuple[int, int]] = []
    for index, monster in live_monsters:
        hp_with_block = int(monster.get("current_hp") or 0) + int(monster.get("block") or 0)
        if hp_with_block <= damage:
            candidates.append((monster_incoming_damage(monster), index))
    if not candidates:
        return None
    return max(candidates)[1]


def potion_damage_kills_any(live_monsters: list[tuple[int, dict[str, Any]]], damage: int) -> bool:
    return any(int(monster.get("current_hp") or 0) + int(monster.get("block") or 0) <= damage for _, monster in live_monsters)


def highest_incoming_monster(live_monsters: list[tuple[int, dict[str, Any]]]) -> int | None:
    candidates = [(monster_incoming_damage(monster), index) for index, monster in live_monsters]
    if not candidates:
        return None
    damage, index = max(candidates)
    return index if damage > 0 else None


def add_screen_actions(actions: list[LegalAction], state: dict[str, Any], available: set[str]) -> None:
    screen_type = str(state.get("screen_type") or state.get("screen_name") or "").upper()
    screen_state = state.get("screen_state") or {}

    if screen_type == "GRID":
        add_grid_actions(actions, screen_state, available)
        return
    if screen_type == "CARD_REWARD":
        add_card_reward_actions(actions, state, screen_state, available)
        return
    if screen_type == "MAP":
        add_map_actions(actions, state, screen_state, available)
        return
    if screen_type in {"SHOP_SCREEN", "SHOP_ROOM"}:
        add_shop_actions(actions, state, screen_state, available)
        return

    if "choose" in available:
        choices = screen_choices(state, screen_state)
        if choices:
            for index, choice in enumerate(choices):
                actions.append(LegalAction(f"choose_{index}", f"CHOOSE {index}", f"Choose option {index}: {choice}."))
        else:
            actions.append(LegalAction("choose_0", "CHOOSE 0", "Choose the first available option."))

    if "confirm" in available:
        actions.append(LegalAction("confirm", "CONFIRM", "Confirm the current selection."))
    if "proceed" in available:
        actions.append(LegalAction("proceed", "PROCEED", "Proceed to the next screen."))
    if "return" in available:
        actions.append(LegalAction("return", "RETURN", "Return, leave, cancel, or skip this screen."))
    if "leave" in available:
        actions.append(LegalAction("leave", "LEAVE", "Leave the current room or shop."))
    if "skip" in available:
        actions.append(LegalAction("skip", "SKIP", "Skip the current reward or optional choice."))
    if "cancel" in available:
        actions.append(LegalAction("cancel", "RETURN", "Cancel the current screen."))


def add_card_reward_actions(
    actions: list[LegalAction],
    state: dict[str, Any],
    screen_state: dict[str, Any],
    available: set[str],
) -> None:
    cards = screen_state.get("cards") or []
    if "choose" in available:
        for index, card in enumerate(cards):
            if not isinstance(card, dict):
                continue
            score = combat_generated_card_score(card, state) if state.get("combat_state") else card_reward_score(card, state)
            reward_kind = "combat generated card" if state.get("combat_state") else "card reward"
            actions.append(
                LegalAction(
                    f"reward_card_{index}",
                    f"CHOOSE {index}",
                    f"Take {reward_kind} {index}: {describe_card(card)}; heuristic score {score}.",
                )
            )
    if "skip" in available:
        actions.append(LegalAction("skip_reward", "SKIP", "Skip this card reward."))


def add_map_actions(
    actions: list[LegalAction],
    state: dict[str, Any],
    screen_state: dict[str, Any],
    available: set[str],
) -> None:
    if "choose" in available:
        nodes = screen_state.get("next_nodes") or []
        if isinstance(nodes, list) and nodes:
            for index, node in enumerate(nodes):
                if not isinstance(node, dict):
                    continue
                symbol = str(node.get("symbol") or "?")
                score = map_node_score(node, state)
                x = node.get("x")
                y = node.get("y")
                actions.append(
                    LegalAction(
                        f"map_node_{index}",
                        f"CHOOSE {index}",
                        f"Choose map node {index}: symbol {symbol}, x={x}, y={y}, route score {score}.",
                    )
                )
        else:
            actions.append(LegalAction("map_choose_0", "CHOOSE 0", "Choose the first available map node."))
    if "proceed" in available:
        actions.append(LegalAction("map_proceed", "PROCEED", "Proceed on the map."))


def add_shop_actions(
    actions: list[LegalAction],
    state: dict[str, Any],
    screen_state: dict[str, Any],
    available: set[str],
) -> None:
    if "choose" in available:
        choices = screen_choices(state, screen_state)
        for index, choice in enumerate(choices):
            actions.append(LegalAction(f"shop_choose_{index}", f"CHOOSE {index}", f"Buy or select shop option: {choice}."))
    if "leave" in available:
        actions.append(LegalAction("leave_shop", "LEAVE", "Leave the shop."))
    if "cancel" in available:
        actions.append(LegalAction("cancel_shop", "RETURN", "Cancel the current shop screen."))


def add_grid_actions(actions: list[LegalAction], screen_state: dict[str, Any], available: set[str]) -> None:
    selected = screen_state.get("selected_cards") or []
    selected_count = len(selected) if isinstance(selected, list) else 0
    required = int(screen_state.get("num_cards") or 1)
    any_number = bool(screen_state.get("any_number"))

    if grid_should_confirm(screen_state, selected_count, required, any_number):
        if "confirm" in available:
            actions.append(LegalAction("grid_confirm", "CONFIRM", "Confirm the grid selection."))
        elif "proceed" in available:
            actions.append(LegalAction("grid_proceed", "PROCEED", "Proceed with the grid selection."))
        return

    if "choose" not in available:
        return

    cards = screen_state.get("cards") or []
    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            continue
        purpose = grid_purpose(screen_state)
        command = f"CHOOSE {index}"
        actions.append(
            LegalAction(
                f"grid_card_{index}",
                command,
                f"Select grid card {index}: {describe_card(card)} for {purpose}.",
            )
        )


def grid_card_coordinates(index: int, total_cards: int) -> tuple[int, int]:
    columns = 5 if total_cards <= 25 else 6
    if columns == 5:
        x_positions = [450, 705, 960, 1215, 1470]
    else:
        x_positions = [350, 600, 850, 1100, 1350, 1600]
    row = index // columns
    column = index % columns
    return x_positions[column], 345 + row * 315


def grid_should_confirm(screen_state: dict[str, Any], selected_count: int, required: int, any_number: bool) -> bool:
    if screen_state.get("confirm_up"):
        return True
    return selected_count >= required or (any_number and selected_count > 0)


def grid_selection_is_ready(screen_state: dict[str, Any]) -> bool:
    selected = screen_state.get("selected_cards") or []
    selected_count = len(selected) if isinstance(selected, list) else 0
    required = int(screen_state.get("num_cards") or 1)
    any_number = bool(screen_state.get("any_number"))
    return grid_should_confirm(screen_state, selected_count, required, any_number)


def grid_purpose(screen_state: dict[str, Any]) -> str:
    if screen_state.get("for_purge"):
        return "removal"
    if screen_state.get("for_upgrade"):
        return "upgrade"
    if screen_state.get("for_transform"):
        return "transform"
    return "selection"


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


def command_is_available(command: str, available: set[str]) -> bool:
    verb = command.split(" ", 1)[0].lower()
    if verb in available:
        return True
    aliases = {
        "confirm": {"confirm", "proceed"},
        "proceed": {"proceed", "confirm"},
        "return": {"return", "cancel"},
        "cancel": {"cancel", "return"},
        "leave": {"leave", "return", "cancel"},
        "skip": {"skip", "return", "cancel"},
    }
    return bool(aliases.get(verb, set()) & available)


def prepend_action(actions: list[LegalAction], action: LegalAction) -> None:
    if all(existing.command != action.command for existing in actions):
        actions.insert(0, action)


def dedupe_actions(actions: list[LegalAction]) -> list[LegalAction]:
    seen_commands: set[str] = set()
    result: list[LegalAction] = []
    for action in actions:
        if action.command in seen_commands:
            continue
        seen_commands.add(action.command)
        result.append(action)
    return result


def estimate_incoming_damage(monsters: list[dict[str, Any]]) -> int:
    total = 0
    for monster in monsters:
        total += monster_incoming_damage(monster)
    return total


def monster_incoming_damage(monster: dict[str, Any]) -> int:
    if monster.get("is_gone") or monster.get("half_dead"):
        return 0
    intent = str(monster.get("intent") or "").upper()
    if "ATTACK" not in intent and intent not in {"DEBUG", "UNKNOWN"}:
        return 0
    damage = int(monster.get("move_adjusted_damage") or monster.get("move_base_damage") or 0)
    hits = int(monster.get("move_hits") or 1)
    if damage <= 0:
        return 0
    return damage * max(hits, 1)


def choose_target(monsters: list[dict[str, Any]]) -> int | None:
    candidates: list[tuple[int, int, int]] = []
    sentries = is_sentries_monster_list(monsters)
    for index, monster in enumerate(monsters):
        if monster.get("is_gone") or monster.get("half_dead"):
            continue
        hp = int(monster.get("current_hp") or 0)
        if hp > 0:
            incoming = monster_incoming_damage(monster)
            score = incoming * 4 - hp
            if "MINION" in str(monster.get("type") or "").upper():
                score += 12
            if sentries and index != 1:
                score += 18
            candidates.append((score, -hp, index))
    if not candidates:
        return None
    return max(candidates)[2]


def is_sentries_monster_list(monsters: list[dict[str, Any]]) -> bool:
    names = [normalize_name(str(monster.get("name") or monster.get("id") or "")) for monster in monsters]
    return len(names) >= 3 and sum(1 for name in names if "sentry" in name) >= 3


def best_targeted_utility_card(
    hand: list[dict[str, Any]],
    energy: int,
    monsters: list[dict[str, Any]],
    state: dict[str, Any],
    incoming: int,
    current_block: int,
) -> tuple[int, int] | None:
    candidates: list[tuple[int, int, int]] = []
    damage_gap = max(incoming - current_block, 0)
    dangerous = is_dangerous_combat(state)
    for card_index, card in enumerate(hand):
        if not is_playable(card, energy) or not card.get("has_target"):
            continue
        name = normalize_card_name(card)
        utility_score = targeted_utility_score(name, state, damage_gap, dangerous)
        if utility_score <= 0:
            continue
        for monster_index, monster in enumerate(monsters):
            if monster.get("is_gone") or monster.get("half_dead") or int(monster.get("current_hp") or 0) <= 0:
                continue
            score = utility_score + monster_incoming_damage(monster) * 2 + int(monster.get("current_hp") or 0) // 5
            candidates.append((score, card_index, monster_index))
    if not candidates:
        return None
    _, card_index, monster_index = max(candidates, key=lambda candidate: (candidate[0], -candidate[1], -candidate[2]))
    return card_index, monster_index


def targeted_utility_score(card_name: str, state: dict[str, Any], damage_gap: int, dangerous: bool) -> int:
    if card_name == "Disarm":
        if is_lagavulin_fight(state) and lagavulin_is_sleeping(state):
            return 0
        if dangerous or damage_gap >= 8 or int(state.get("act") or 1) >= 2:
            return 92
        return 45
    return 0


def best_card(
    hand: list[dict[str, Any]],
    priority: dict[str, int],
    energy: int,
    *,
    needs_target: bool,
) -> int | None:
    candidates: list[tuple[int, int]] = []
    for index, card in enumerate(hand):
        if not is_playable(card, energy):
            continue
        if bool(card.get("has_target")) != needs_target:
            continue
        card_id = str(card.get("id") or "")
        name = str(card.get("name") or "")
        score = priority.get(card_id, priority.get(name, 0))
        if score:
            candidates.append((-score, index))
    if not candidates:
        return None
    return sorted(candidates)[0][1]


def choose_lethal_attack(
    hand: list[dict[str, Any]],
    monsters: list[dict[str, Any]],
    energy: int,
) -> tuple[int, int] | None:
    candidates: list[tuple[int, int, int]] = []
    for card_index, card in enumerate(hand):
        if not is_playable(card, energy) or not card.get("has_target"):
            continue
        damage = estimate_card_damage(card)
        if damage <= 0:
            continue
        cost = effective_card_cost(card)
        for monster_index, monster in enumerate(monsters):
            if monster.get("is_gone") or monster.get("half_dead"):
                continue
            hp = int(monster.get("current_hp") or 0)
            block = int(monster.get("block") or 0)
            if hp > 0 and damage >= hp + block:
                incoming = monster_incoming_damage(monster)
                candidates.append((incoming, -cost, card_index, monster_index))
    if not candidates:
        return None
    _, _, card_index, monster_index = max(candidates)
    return card_index, monster_index


def best_attack_card(hand: list[dict[str, Any]], energy: int, target: dict[str, Any]) -> int | None:
    candidates: list[tuple[int, int]] = []
    target_hp = int(target.get("current_hp") or 0) + int(target.get("block") or 0)
    for index, card in enumerate(hand):
        if not is_playable(card, energy) or not card.get("has_target"):
            continue
        damage = estimate_card_damage(card)
        cost = max(effective_card_cost(card), 1)
        card_id = str(card.get("id") or "")
        name = str(card.get("name") or "")
        priority = ATTACK_PRIORITY.get(card_id, ATTACK_PRIORITY.get(name, 0))
        overkill_penalty = max(damage - target_hp, 0)
        score = damage * 10 // cost + priority - overkill_penalty * 3
        candidates.append((score, index))
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: (candidate[0], -candidate[1]))[1]


def best_block_card(hand: list[dict[str, Any]], energy: int) -> int | None:
    candidates: list[tuple[int, int]] = []
    for index, card in enumerate(hand):
        if not is_playable(card, energy) or card.get("has_target"):
            continue
        block = estimate_card_block(card)
        card_id = str(card.get("id") or "")
        name = str(card.get("name") or "")
        priority = BLOCK_PRIORITY.get(card_id, BLOCK_PRIORITY.get(name, 0))
        if block <= 0 and priority <= 0:
            continue
        score = block * 10 + priority
        candidates.append((score, index))
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: (candidate[0], -candidate[1]))[1]


def estimate_card_damage(card: dict[str, Any]) -> int:
    card_id = str(card.get("id") or "")
    name = str(card.get("name") or "")
    base = CARD_BASE_DAMAGE.get(card_id, CARD_BASE_DAMAGE.get(name.replace("+", ""), 0))
    upgrades = int(card.get("upgrades") or 0)
    if base and upgrades:
        if card_id == "Bash" or name.startswith("Bash"):
            return base + 2 * upgrades
        return base + 3 * upgrades
    if not base and str(card.get("type") or "").upper() == "ATTACK":
        base = 6
    return base


def estimate_card_block(card: dict[str, Any]) -> int:
    card_id = str(card.get("id") or "")
    name = str(card.get("name") or "")
    base = CARD_BASE_BLOCK.get(card_id, CARD_BASE_BLOCK.get(name.replace("+", ""), 0))
    upgrades = int(card.get("upgrades") or 0)
    if base and upgrades:
        return base + 3 * upgrades
    if not base and str(card.get("type") or "").upper() == "SKILL":
        base = 0
    return base


def effective_card_cost(card: dict[str, Any]) -> int:
    cost = int(card.get("cost") if card.get("cost") is not None else 0)
    return max(cost, 0)


def first_playable_without_target(hand: list[dict[str, Any]], energy: int) -> int | None:
    for index, card in enumerate(hand):
        if is_playable(card, energy) and not card.get("has_target"):
            return index
    return None


def is_playable(card: dict[str, Any], energy: int) -> bool:
    if not card.get("is_playable"):
        return False
    cost = int(card.get("cost") if card.get("cost") is not None else 0)
    return cost < 0 or cost <= energy


def choose_screen_command(state: dict[str, Any], available: set[str]) -> str:
    screen_type = str(state.get("screen_type") or state.get("screen_name") or "").upper()
    screen_name = str(state.get("screen_name") or "").upper()
    screen_state = state.get("screen_state") or {}

    if screen_type == "GRID":
        return choose_grid_command(screen_state, available)

    if screen_type == "COMBAT_REWARD":
        return choose_combat_reward_command(state, screen_state, available)

    if screen_type == "CARD_REWARD":
        return choose_card_reward_command(state, screen_state, available)

    if screen_type == "MAP":
        return choose_map_command(state, screen_state, available)

    if screen_type == "REST":
        return choose_rest_command(state, screen_state, available)

    if screen_type == "EVENT":
        return choose_event_command(state, screen_state, available)

    if screen_name in {"FTUE"}:
        logging.warning("FTUE screen detected; sending in-game confirm key")
        if "key" in available:
            return "KEY Confirm 30"
        if "wait" in available:
            return "WAIT 60"
        if "state" in available:
            time.sleep(1)
            return "STATE"

    if "proceed" in available and screen_type in {"COMBAT_REWARD", "COMPLETE", "NONE"}:
        return "PROCEED"

    if screen_type == "SHOP_ROOM":
        if "proceed" in available and not should_enter_shop_room(state):
            return "PROCEED"
        if "choose" in available:
            return "CHOOSE 0"
        if "proceed" in available:
            return "PROCEED"

    if screen_type == "SHOP_SCREEN":
        return choose_shop_command(state, screen_state, available)

    if "return" in available and screen_type in {"CARD_REWARD", "SHOP_SCREEN"}:
        return "RETURN"

    if "leave" in available and screen_type in {"SHOP_SCREEN", "NONE"}:
        return "LEAVE"

    if "choose" in available:
        if state.get("choice_list") or screen_state.get("options"):
            return "CHOOSE 0"
        choice = first_choice_name(screen_state)
        if choice:
            return f"CHOOSE {choice}"
        return "CHOOSE 0"

    if "proceed" in available:
        return "PROCEED"

    if "return" in available:
        return "RETURN"

    if "leave" in available:
        return "LEAVE"

    if "skip" in available:
        return "SKIP"

    if "state" in available:
        time.sleep(0.25)
        return "STATE"

    return "WAIT 30"


def choose_card_reward_command(state: dict[str, Any], screen_state: dict[str, Any], available: set[str]) -> str:
    cards = screen_state.get("cards") or []
    if "choose" in available and isinstance(cards, list) and cards:
        if state.get("combat_state"):
            index = choose_combat_generated_card_index(cards, state)
        else:
            index = choose_card_reward_index(cards, state)
        if index is not None:
            score = combat_generated_card_score(cards[index], state) if state.get("combat_state") else card_reward_score(cards[index], state)
            if score >= 55 or "skip" not in available:
                return f"CHOOSE {index}"

    if "skip" in available:
        return "SKIP"
    if "return" in available:
        return "RETURN"
    if "state" in available:
            time.sleep(0.25)
            return "STATE"
    return "WAIT 30"


def choose_combat_generated_card_index(cards: list[Any], state: dict[str, Any]) -> int | None:
    candidates: list[tuple[int, int]] = []
    for index, card in enumerate(cards):
        if isinstance(card, dict):
            candidates.append((combat_generated_card_score(card, state), index))
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: (candidate[0], -candidate[1]))[1]


def combat_generated_card_score(card: dict[str, Any], state: dict[str, Any]) -> int:
    combat = state.get("combat_state") or {}
    monsters = combat.get("monsters") or []
    player = combat.get("player") or {}
    incoming = estimate_incoming_damage(monsters)
    current_block = int(player.get("block") or 0)
    damage_gap = max(incoming - current_block, 0)
    name = normalize_card_name(card)
    card_type = str(card.get("type") or "").upper()
    damage = estimate_card_damage(card)
    block = estimate_card_block(card)

    score = 35
    if card.get("has_target") or card_type == "ATTACK":
        score = 50 + damage * 2
        target = choose_target(monsters)
        if target is not None:
            target_hp = int(monsters[target].get("current_hp") or 0) + int(monsters[target].get("block") or 0)
            if damage >= target_hp and damage > 0:
                score += 45 + monster_incoming_damage(monsters[target])
    if block > 0:
        score = max(score, 45 + min(block, damage_gap) * 4 + max(block - damage_gap, 0))
    if name in {"Impervious", "Flame Barrier", "Power Through"} and damage_gap > 0:
        score += 25
    if name in {"Inflame", "Shockwave", "Offering", "Disarm"}:
        score += 35 if is_dangerous_combat(state) or damage_gap > 0 else 15
    if name in {"Brutality", "Barricade", "Fire Breathing"}:
        score -= 30
    if is_gremlin_nob_fight(state) and card_type == "SKILL" and damage_gap < 16:
        score -= 22
    return score


def choose_combat_reward_command(state: dict[str, Any], screen_state: dict[str, Any], available: set[str]) -> str:
    potion_room_action = choose_potion_reward_room_action(state, screen_state, available)
    if potion_room_action is not None:
        return potion_room_action

    if "choose" in available:
        reward_index = choose_reward_index(state, screen_state)
        if reward_index is not None:
            return f"CHOOSE {reward_index}"

    if "proceed" in available:
        return "PROCEED"
    if "return" in available:
        return "RETURN"
    if "state" in available:
        time.sleep(0.25)
        return "STATE"
    return "WAIT 30"


def choose_potion_reward_room_action(
    state: dict[str, Any],
    screen_state: dict[str, Any],
    available: set[str],
) -> str | None:
    if not combat_reward_has_potion(screen_state):
        return None
    if has_empty_potion_slot(state):
        return None
    if "potion" in available:
        usable_slot = usable_reward_room_potion_slot(state)
        if usable_slot is not None:
            return f"POTION Use {usable_slot}"
        discard_slot = discard_slot_for_potion_reward(state, screen_state)
        if discard_slot is not None:
            return f"POTION Discard {discard_slot}"
    if "choose" in available and combat_reward_has_non_potion(screen_state):
        reward_index = choose_non_potion_reward_index(state, screen_state)
        if reward_index is not None:
            return f"CHOOSE {reward_index}"
    if "proceed" in available:
        return "PROCEED"
    return None


def combat_reward_has_potion(screen_state: dict[str, Any]) -> bool:
    return any(
        isinstance(reward, dict) and str(reward.get("reward_type") or "").upper() == "POTION"
        for reward in screen_state.get("rewards") or []
    )


def combat_reward_has_non_potion(screen_state: dict[str, Any]) -> bool:
    return any(
        isinstance(reward, dict) and str(reward.get("reward_type") or "").upper() != "POTION"
        for reward in screen_state.get("rewards") or []
    )


def usable_reward_room_potion_slot(state: dict[str, Any]) -> int | None:
    candidates: list[tuple[int, int]] = []
    for slot, potion in enumerate(state.get("potions") or []):
        if not isinstance(potion, dict) or not potion.get("can_use") or potion.get("requires_target"):
            continue
        name = normalize_name(str(potion.get("name") or potion.get("id") or ""))
        if "fruit juice" in name:
            candidates.append((100, slot))
        elif "regen" in name or "blood" in name:
            candidates.append((45, slot))
    if not candidates:
        return None
    return max(candidates)[1]


def discard_slot_for_potion_reward(state: dict[str, Any], screen_state: dict[str, Any]) -> int | None:
    reward_value = best_reward_potion_value(screen_state)
    candidates: list[tuple[int, int]] = []
    for slot, potion in enumerate(state.get("potions") or []):
        if not isinstance(potion, dict) or not potion.get("can_discard"):
            continue
        candidates.append((potion_value(potion), slot))
    if not candidates:
        return None
    worst_value, worst_slot = min(candidates)
    return worst_slot if reward_value >= worst_value + 8 else None


def best_reward_potion_value(screen_state: dict[str, Any]) -> int:
    values = []
    for reward in screen_state.get("rewards") or []:
        if not isinstance(reward, dict) or str(reward.get("reward_type") or "").upper() != "POTION":
            continue
        potion = reward.get("potion")
        if isinstance(potion, dict):
            values.append(potion_value(potion))
    return max(values) if values else 0


def potion_value(potion: dict[str, Any]) -> int:
    name = normalize_name(str(potion.get("name") or potion.get("id") or ""))
    if "fruit juice" in name:
        return 95
    if "fairy" in name:
        return 92
    if "ghost in a jar" in name:
        return 90
    if "fire" in name or "explosive" in name:
        return 78
    if "heart of iron" in name:
        return 76
    if "fear" in name or "weak" in name or "vulnerable" in name:
        return 68
    if "strength" in name or "flex" in name or "duplication" in name:
        return 66
    if "skill" in name or "attack" in name or "power" in name:
        return 58
    if "smoke bomb" in name:
        return 45
    if "potion slot" in name:
        return -100
    return 50


def choose_non_potion_reward_index(state: dict[str, Any], screen_state: dict[str, Any]) -> int | None:
    rewards = screen_state.get("rewards") or []
    candidates: list[tuple[int, int]] = []
    for index, reward in enumerate(rewards):
        if not isinstance(reward, dict):
            continue
        reward_type = str(reward.get("reward_type") or "").upper()
        if reward_type == "POTION":
            continue
        candidates.append((REWARD_PRIORITY.get(reward_type, 50), index))
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: (candidate[0], -candidate[1]))[1]


def choose_reward_index(state: dict[str, Any], screen_state: dict[str, Any]) -> int | None:
    rewards = screen_state.get("rewards") or []
    choices = screen_choices(state, screen_state)
    candidates: list[tuple[int, int]] = []

    if isinstance(rewards, list) and rewards:
        for index, reward in enumerate(rewards):
            if not isinstance(reward, dict):
                continue
            reward_type = str(reward.get("reward_type") or "").upper()
            score = REWARD_PRIORITY.get(reward_type, 50)
            if reward_type == "POTION" and not has_empty_potion_slot(state):
                score = 20
            candidates.append((score, index))

    if not candidates and choices:
        for index, choice in enumerate(choices):
            key = normalize_name(choice).upper().replace(" ", "_")
            score = REWARD_PRIORITY.get(key, 50)
            candidates.append((score, index))

    if not candidates:
        return None
    return max(candidates, key=lambda candidate: (candidate[0], -candidate[1]))[1]


def has_empty_potion_slot(state: dict[str, Any]) -> bool:
    for potion in state.get("potions") or []:
        if not isinstance(potion, dict):
            continue
        if str(potion.get("id") or potion.get("name") or "").lower() == "potion slot":
            return True
    return False


def choose_map_command(state: dict[str, Any], screen_state: dict[str, Any], available: set[str]) -> str:
    if "choose" in available:
        nodes = screen_state.get("next_nodes") or []
        if isinstance(nodes, list) and nodes:
            scores = [(map_node_score(node, state), index) for index, node in enumerate(nodes) if isinstance(node, dict)]
            if scores:
                return f"CHOOSE {max(scores, key=lambda item: (item[0], -item[1]))[1]}"
        return "CHOOSE 0"

    if "proceed" in available:
        return "PROCEED"
    if "return" in available:
        return "RETURN"
    if "state" in available:
        time.sleep(0.25)
        return "STATE"
    return "WAIT 30"


def map_node_score(node: dict[str, Any], state: dict[str, Any]) -> int:
    symbol = str(node.get("symbol") or "")
    current_hp = int(state.get("current_hp") or 0)
    max_hp = int(state.get("max_hp") or 1)
    hp_ratio = current_hp / max(max_hp, 1)
    gold = int(state.get("gold") or 0)
    deck = state.get("deck") or []
    deck_size = len(deck) if isinstance(deck, list) else 0
    upgraded_bash = any(isinstance(card, dict) and card.get("id") == "Bash" and int(card.get("upgrades") or 0) > 0 for card in deck)

    score_by_symbol = {
        "M": 70,
        "?": 66,
        "R": 63,
        "T": 58,
        "$": 45,
        "E": 30,
    }
    score = score_by_symbol.get(symbol, 50)
    if symbol == "$":
        score += min(gold // 20, 10)
        if gold < 75:
            score -= 30
    if symbol == "E":
        if hp_ratio >= 0.72 and (deck_size >= 12 or upgraded_bash):
            score += 35
        elif hp_ratio < 0.65:
            score -= 55
        elif hp_ratio < 0.55:
            score -= 30
    if symbol == "R":
        if hp_ratio < 0.5:
            score += 40
        elif hp_ratio < 0.65:
            score += 25
    score += route_lookahead_score(node, state, hp_ratio, gold, depth=5)
    return score


def route_lookahead_score(node: dict[str, Any], state: dict[str, Any], hp_ratio: float, gold: int, depth: int) -> int:
    full_map = state.get("map") or []
    if not isinstance(full_map, list) or depth <= 0:
        return 0
    by_position = {
        (int(item.get("x")), int(item.get("y"))): item
        for item in full_map
        if isinstance(item, dict) and item.get("x") is not None and item.get("y") is not None
    }
    root = node
    node_pos = child_position(node)
    if node_pos is not None:
        root = by_position.get(node_pos, node)
    children = root.get("children") or []
    child_scores = []
    for child in children:
        if not isinstance(child, dict):
            continue
        child_pos = child_position(child)
        if child_pos is None:
            continue
        child_node = by_position.get(child_pos)
        if child_node is not None:
            child_scores.append(route_future_score(child_node, by_position, hp_ratio, gold, depth - 1))
    if not child_scores:
        return 0
    return max(child_scores)


def route_future_score(
    node: dict[str, Any],
    by_position: dict[tuple[int, int], dict[str, Any]],
    hp_ratio: float,
    gold: int,
    depth: int,
) -> int:
    symbol = str(node.get("symbol") or "")
    score = future_symbol_score(symbol, hp_ratio, gold)
    if depth <= 0:
        return score

    children = node.get("children") or []
    child_scores = []
    for child in children:
        if not isinstance(child, dict):
            continue
        child_pos = child_position(child)
        if child_pos is None:
            continue
        child_node = by_position.get(child_pos)
        if child_node is not None:
            child_scores.append(route_future_score(child_node, by_position, hp_ratio, gold, depth - 1))
    if child_scores:
        score += max(child_scores)
    return score


def child_position(child: dict[str, Any]) -> tuple[int, int] | None:
    if child.get("x") is None or child.get("y") is None:
        return None
    try:
        return int(child.get("x")), int(child.get("y"))
    except (TypeError, ValueError):
        return None


def future_symbol_score(symbol: str, hp_ratio: float, gold: int) -> int:
    if symbol == "E":
        if hp_ratio < 0.65:
            return -80
        if hp_ratio < 0.75:
            return -45
        return -20
    if symbol == "R":
        if hp_ratio < 0.55:
            return 55
        if hp_ratio < 0.70:
            return 35
        return 8
    if symbol == "$":
        return 16 if gold >= 150 else -8
    if symbol == "?":
        return 6
    if symbol == "M":
        return 3 if hp_ratio >= 0.55 else -8
    if symbol == "T":
        return 10
    return 0


def choose_rest_command(state: dict[str, Any], screen_state: dict[str, Any], available: set[str]) -> str:
    if "choose" in available:
        options = screen_choices(state, screen_state) or [str(option) for option in screen_state.get("rest_options") or []]
        if options:
            scores = [(rest_option_score(option, state), index) for index, option in enumerate(options)]
            return f"CHOOSE {max(scores, key=lambda candidate: (candidate[0], -candidate[1]))[1]}"

    if "proceed" in available:
        return "PROCEED"
    if "state" in available:
        time.sleep(0.25)
        return "STATE"
    return "WAIT 30"


def rest_option_score(option: str, state: dict[str, Any]) -> int:
    current_hp = int(state.get("current_hp") or 0)
    max_hp = int(state.get("max_hp") or 1)
    hp_ratio = current_hp / max(max_hp, 1)
    key = normalize_name(option)
    if key == "rest":
        if hp_ratio <= 0.55:
            return 120
        if hp_ratio < 0.68 and next_known_node_is_boss_or_elite(state):
            return 105
        if hp_ratio < 0.65:
            return 92
        return 45
    if key == "smith":
        if hp_ratio <= 0.55:
            return 35
        if hp_ratio < 0.65:
            return 75
        return 100
    if key in {"recall", "dig", "lift", "toke"}:
        return 30
    return 50


def next_known_node_is_boss_or_elite(state: dict[str, Any]) -> bool:
    screen_state = state.get("screen_state") or {}
    next_nodes = screen_state.get("next_nodes") or []
    if not isinstance(next_nodes, list):
        return False
    for node in next_nodes:
        if isinstance(node, dict) and str(node.get("symbol") or "") in {"E", "B"}:
            return True
    return False


def choose_event_command(state: dict[str, Any], screen_state: dict[str, Any], available: set[str]) -> str:
    choices = screen_choices(state, screen_state)
    if "choose" in available and choices:
        candidates: list[tuple[int, int]] = []
        for index, choice in enumerate(choices):
            candidates.append((event_choice_score(choice, state), index))
        return f"CHOOSE {max(candidates, key=lambda candidate: (candidate[0], -candidate[1]))[1]}"

    if "choose" in available:
        return "CHOOSE 0"
    if "proceed" in available:
        return "PROCEED"
    if "return" in available:
        return "RETURN"
    if "state" in available:
        time.sleep(0.25)
        return "STATE"
    return "WAIT 30"


def event_choice_score(choice: str, state: dict[str, Any]) -> int:
    current_hp = int(state.get("current_hp") or 0)
    max_hp = int(state.get("max_hp") or 1)
    hp_ratio = current_hp / max(max_hp, 1)
    gold = int(state.get("gold") or 0)
    key = normalize_name(choice)

    if key in {"talk", "leave", "continue"}:
        return 100
    if key in {"play"}:
        return 80
    if key == "pain" or "curse" in key or "regret" in key or "doubt" in key:
        return 5
    if key.startswith("card"):
        return 25
    named_card_score = event_named_card_score(key, state)
    if named_card_score is not None:
        return named_card_score
    if "next three combats have 1 hp" in key or "enemies in your next three combats have 1 hp" in key:
        return 130
    if "pray" in key:
        return 105
    if "desecrate" in key:
        return 45 if hp_ratio >= 0.75 else 15
    if "grow" in key or "upgrade" in key or "smith" in key:
        return 95
    if "forget" in key or "remove" in key:
        return 92
    if "transform" in key or "change" in key:
        return 80
    if "fight" in key or "attack" in key:
        return 85 if hp_ratio >= 0.65 else 35
    if "heal" in key:
        return 90 if hp_ratio <= 0.55 else 45
    if "max hp" in key:
        return 75
    if "give gold" in key or "lose gold" in key:
        return 55 if gold >= 120 else 25
    if "box" in key:
        return 55
    return 50


def event_named_card_score(normalized_choice: str, state: dict[str, Any]) -> int | None:
    card_names = set(CARD_REWARD_PRIORITY) | set(CARD_BASE_DAMAGE) | set(CARD_BASE_BLOCK)
    for name in card_names:
        if normalize_name(name) == normalized_choice:
            return max(card_reward_score({"name": name, "id": name}, state), 35)
    return None


def choose_shop_command(state: dict[str, Any], screen_state: dict[str, Any], available: set[str]) -> str:
    mark_shop_visited(state)

    if "choose" in available:
        choice_index = choose_shop_choice_index(state, screen_state)
        if choice_index is not None:
            return f"CHOOSE {choice_index}"

    if "leave" in available:
        return "LEAVE"
    if "return" in available:
        return "RETURN"
    if "state" in available:
        time.sleep(0.25)
        return "STATE"
    return "WAIT 30"


def should_enter_shop_room(state: dict[str, Any]) -> bool:
    if not screen_choices(state, state.get("screen_state") or {}):
        return False
    if shop_visit_key(state) in SHOP_VISITED_KEYS:
        return False
    return int(state.get("gold") or 0) >= 75


def mark_shop_visited(state: dict[str, Any]) -> None:
    SHOP_VISITED_KEYS.add(shop_visit_key(state))


def shop_visit_key(state: dict[str, Any]) -> tuple[str, int, int]:
    return (str(state.get("seed") or ""), int(state.get("act") or 0), int(state.get("floor") or 0))


def choose_card_reward_index(cards: list[Any], state: dict[str, Any] | None = None) -> int | None:
    candidates: list[tuple[int, int]] = []
    for index, card in enumerate(cards):
        if isinstance(card, dict):
            candidates.append((card_reward_score(card, state), index))
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: (candidate[0], -candidate[1]))[1]


def card_reward_score(card: dict[str, Any], state: dict[str, Any] | None = None) -> int:
    card_id = str(card.get("id") or "")
    name = str(card.get("name") or card_id)
    rarity = str(card.get("rarity") or "").upper()
    card_type = str(card.get("type") or "").upper()
    cost = int(card.get("cost") if card.get("cost") is not None else 1)
    normalized = normalize_card_name(card)
    deck = (state or {}).get("deck") or []
    act = int((state or {}).get("act") or 1)
    floor = int((state or {}).get("floor") or 0)

    score = CARD_REWARD_PRIORITY.get(card_id, CARD_REWARD_PRIORITY.get(name, 0))
    if not score:
        score = {"RARE": 68, "UNCOMMON": 58, "COMMON": 48}.get(rarity, 35)
        if card_type == "ATTACK":
            score += 8
        elif card_type == "POWER":
            score += 6
        if cost >= 3:
            score -= 8
    if act == 1 and floor <= 8:
        if normalized in FRONTLOAD_ATTACKS:
            score += 14
        elif card_type == "ATTACK":
            score += 6
        if normalized in SPECULATIVE_SYNERGY_CARDS and not deck_supports_synergy(normalized, deck):
            score -= 22
        if card_type == "POWER" and count_non_basic_attacks(deck) < 2:
            score -= 8
    if normalized == "Clash" and deck_has_many_non_attacks(deck):
        score -= 28
    if normalized == "Sword Boomerang" and not deck_has_strength_scaling(deck):
        score -= 10
    if normalized == "Searing Blow":
        score -= 18
    if normalized == "Body Slam" and count_block_cards(deck) < 5:
        score -= 20
    return score


def normalize_card_name(card: dict[str, Any]) -> str:
    return str(card.get("name") or card.get("id") or "").replace("+", "").strip()


def count_non_basic_attacks(deck: list[Any]) -> int:
    total = 0
    for card in deck:
        if not isinstance(card, dict):
            continue
        card_type = str(card.get("type") or "").upper()
        name = normalize_card_name(card)
        if card_type == "ATTACK" and name not in {"Strike", "Bash"}:
            total += 1
    return total


def deck_has_many_non_attacks(deck: list[Any]) -> bool:
    non_attacks = 0
    for card in deck:
        if not isinstance(card, dict):
            continue
        card_type = str(card.get("type") or "").upper()
        if card_type != "ATTACK":
            non_attacks += 1
    return non_attacks >= 4


def count_block_cards(deck: list[Any]) -> int:
    total = 0
    for card in deck:
        if not isinstance(card, dict):
            continue
        if estimate_card_block(card) > 0:
            total += 1
    return total


def deck_has_strength_scaling(deck: list[Any]) -> bool:
    strength_cards = {"Demon Form", "Inflame", "Spot Weakness", "Flex", "Limit Break"}
    return any(isinstance(card, dict) and normalize_card_name(card) in strength_cards for card in deck)


def deck_has_exhaust_support(deck: list[Any]) -> bool:
    exhaust_cards = {
        "Burning Pact",
        "Corruption",
        "Exhume",
        "Fiend Fire",
        "Havoc",
        "Power Through",
        "Second Wind",
        "Sever Soul",
        "Seeing Red",
        "Sentinel",
        "True Grit",
    }
    for card in deck:
        if not isinstance(card, dict):
            continue
        if normalize_card_name(card) in exhaust_cards or bool(card.get("exhausts")):
            return True
    return False


def deck_supports_synergy(card_name: str, deck: list[Any]) -> bool:
    if card_name in {"Feel No Pain", "Dark Embrace", "Corruption"}:
        return deck_has_exhaust_support(deck)
    if card_name == "Body Slam":
        return count_block_cards(deck) >= 5
    if card_name == "Fire Breathing":
        return deck_has_status_or_curse(deck)
    if card_name == "Rupture":
        return deck_has_self_damage(deck)
    if card_name == "Juggernaut":
        return count_block_cards(deck) >= 6
    return False


def deck_has_status_or_curse(deck: list[Any]) -> bool:
    for card in deck:
        if not isinstance(card, dict):
            continue
        if str(card.get("type") or "").upper() in {"CURSE", "STATUS"}:
            return True
    return False


def deck_has_self_damage(deck: list[Any]) -> bool:
    self_damage_cards = {"Bloodletting", "Brutality", "Combust", "Hemokinesis", "Offering", "Rupture"}
    return any(isinstance(card, dict) and normalize_card_name(card) in self_damage_cards for card in deck)


def choose_shop_choice_index(state: dict[str, Any], screen_state: dict[str, Any]) -> int | None:
    choices = screen_choices(state, screen_state)
    if not choices:
        return None

    gold = int(state.get("gold") or 0)
    candidates: list[tuple[int, int]] = []
    purge_index = find_choice_index(choices, "purge")
    purge_cost = int(screen_state.get("purge_cost") or 9999)
    if (
        purge_index is not None
        and screen_state.get("purge_available")
        and purge_cost <= gold
        and deck_has_low_value_removal_target(state.get("deck") or [])
    ):
        candidates.append((92 - purge_cost // 10, purge_index))

    shop_items = collect_shop_items(screen_state)
    for index, choice in enumerate(choices):
        key = normalize_name(choice)
        item = shop_items.get(key)
        if item is None:
            continue
        price = int(item.get("price") or 0)
        if price <= 0 or price > gold:
            continue
        score = shop_item_score(item) - price // 5
        if score >= 60:
            candidates.append((score, index))

    if not candidates:
        return None
    return max(candidates, key=lambda candidate: (candidate[0], -candidate[1]))[1]


def collect_shop_items(screen_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}
    for group in ("cards", "relics", "potions"):
        for item in screen_state.get(group) or []:
            if isinstance(item, dict):
                items[normalize_name(str(item.get("name") or item.get("id") or ""))] = item
    return items


def shop_item_score(item: dict[str, Any]) -> int:
    name = str(item.get("name") or item.get("id") or "")
    score = SHOP_CARD_PRIORITY.get(name, SHOP_CARD_PRIORITY.get(str(item.get("id") or ""), 0))
    if score:
        return score
    if "rarity" in item or "type" in item:
        return card_reward_score(item)
    return 50


def deck_has_low_value_removal_target(deck: list[Any]) -> bool:
    for card in deck:
        if not isinstance(card, dict):
            continue
        card_id = str(card.get("id") or "")
        name = str(card.get("name") or "")
        card_type = str(card.get("type") or "").upper()
        if card_type == "CURSE" or card_id.startswith("Strike") or name == "Strike":
            return True
    return False


def find_choice_index(choices: list[str], wanted: str) -> int | None:
    wanted_key = normalize_name(wanted)
    for index, choice in enumerate(choices):
        if normalize_name(choice) == wanted_key:
            return index
    return None


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def choose_grid_command(screen_state: dict[str, Any], available: set[str]) -> str:
    selected = screen_state.get("selected_cards") or []
    selected_count = len(selected) if isinstance(selected, list) else 0
    required = int(screen_state.get("num_cards") or 1)
    any_number = bool(screen_state.get("any_number"))

    if grid_should_confirm(screen_state, selected_count, required, any_number):
        if "confirm" in available:
            return "CONFIRM"
        if "proceed" in available:
            return "PROCEED"

    cards = screen_state.get("cards") or []
    if isinstance(cards, list) and cards:
        index = choose_grid_card_index(cards, screen_state)
        if "choose" in available:
            return f"CHOOSE {index}"

    if "confirm" in available:
        return "CONFIRM"
    if "state" in available:
        time.sleep(0.25)
        return "STATE"
    return "WAIT 30"


def choose_grid_card_index(cards: list[Any], screen_state: dict[str, Any]) -> int:
    candidates: list[tuple[int, int]] = []
    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            continue
        candidates.append((grid_card_score(card, screen_state), index))
    if not candidates:
        return 0
    return max(candidates, key=lambda candidate: (candidate[0], -candidate[1]))[1]


def grid_card_score(card: dict[str, Any], screen_state: dict[str, Any]) -> int:
    card_id = str(card.get("id") or "")
    name = str(card.get("name") or "")
    card_type = str(card.get("type") or "")
    upgrades = int(card.get("upgrades") or 0)

    if screen_state.get("for_purge") or screen_state.get("for_transform"):
        if card_id.startswith("Strike") or name == "Strike":
            return 100 - upgrades
        if card_id.startswith("Defend") or name == "Defend":
            return 70 - upgrades
        if card_type == "CURSE":
            return 120
        return 10

    if screen_state.get("for_upgrade"):
        if card_id == "Bash" or name == "Bash":
            return 100 - upgrades
        if card_type == "ATTACK":
            return 60 - upgrades
        if card_type == "SKILL":
            return 50 - upgrades
        return 20 - upgrades

    if card_id == "Bash" or name == "Bash":
        return 80 - upgrades
    if card_id.startswith("Strike") or name == "Strike":
        return 60 - upgrades
    return 40 - upgrades


def first_choice_name(screen_state: dict[str, Any]) -> str | None:
    for key in ("choice_list", "choices", "options"):
        choices = screen_state.get(key)
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, str):
                return quote_choice(first)
            if isinstance(first, dict):
                name = first.get("name") or first.get("text") or first.get("label")
                if name:
                    return quote_choice(str(name))
    return None


def quote_choice(choice: str) -> str:
    if " " not in choice:
        return choice
    return json.dumps(choice, ensure_ascii=False)


def run_protocol(options: Options) -> int:
    setup_logging()
    logging.info("AI process started")
    print("ready", flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            logging.exception("Invalid JSON from CommunicationMod")
            command = "STATE"
        else:
            append_jsonl("states.jsonl", payload)
            command = choose_command(payload, options)
            remember_potion_use(command, payload)

        action = {"time": time.time(), "command": command}
        append_jsonl("actions.jsonl", action)
        logging.info("command=%s", command)
        print(command, flush=True)

    logging.info("AI process stopped")
    return 0


def default_codex_command() -> str:
    if CODEX_APP_COMMAND.exists():
        return str(CODEX_APP_COMMAND)
    return "codex"


def run_test(
    *,
    use_openai_api: bool = False,
    openai_model: str = "gpt-5-mini",
    openai_api_base: str = "https://api.openai.com/v1",
    openai_timeout: float = 20.0,
    use_codex: bool = False,
    codex_model: str = "gpt-5.3-codex",
    codex_command: str | None = None,
    codex_timeout: float = 45.0,
) -> int:
    setup_logging()
    sample = {
        "available_commands": ["play", "end", "state"],
        "ready_for_command": True,
        "in_game": True,
        "game_state": {
            "screen_type": "NONE",
            "combat_state": {
                "hand": [
                    {"id": "Defend_R", "name": "Defend", "cost": 1, "is_playable": True, "has_target": False},
                    {"id": "Strike_R", "name": "Strike", "cost": 1, "is_playable": True, "has_target": True},
                ],
                "player": {"energy": 3, "block": 0},
                "monsters": [
                    {
                        "name": "Jaw Worm",
                        "current_hp": 40,
                        "is_gone": False,
                        "half_dead": False,
                        "intent": "ATTACK",
                        "move_adjusted_damage": 12,
                        "move_hits": 1,
                    }
                ],
            },
        },
    }
    options = Options(
        auto_start=False,
        character="IRONCLAD",
        ascension=0,
        seed=None,
        use_openai_api=use_openai_api,
        openai_model=openai_model,
        openai_api_base=openai_api_base,
        openai_timeout=openai_timeout,
        use_codex=use_codex,
        codex_model=codex_model,
        codex_command=codex_command or default_codex_command(),
        codex_timeout=codex_timeout,
    )
    command = choose_command(sample, options)
    print(command)
    return 0 if command == "PLAY 1" else 1


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Run a local decision smoke test.")
    parser.add_argument("--auto-start", action="store_true", help="Start a new run from the main menu.")
    parser.add_argument("--character", default="IRONCLAD", help="Character for START command.")
    parser.add_argument("--ascension", type=int, default=0, help="Ascension level for START command.")
    parser.add_argument("--seed", default=None, help="Optional seed for START command.")
    parser.add_argument("--use-openai-api", action="store_true", help="Ask the OpenAI Responses API to choose from legal actions.")
    parser.add_argument(
        "--openai-model",
        default=os.environ.get("STS_AI_OPENAI_MODEL", "gpt-5-mini"),
        help="OpenAI API model used when --use-openai-api is enabled.",
    )
    parser.add_argument(
        "--openai-api-base",
        default=os.environ.get("STS_AI_OPENAI_API_BASE", "https://api.openai.com/v1"),
        help="Base URL for the OpenAI API.",
    )
    parser.add_argument(
        "--openai-timeout",
        type=float,
        default=float(os.environ.get("STS_AI_OPENAI_TIMEOUT", "20")),
        help="OpenAI API timeout in seconds.",
    )
    parser.add_argument("--use-codex", action="store_true", help="Ask an OpenAI Codex model to choose from legal actions.")
    parser.add_argument(
        "--codex-model",
        default=os.environ.get("STS_AI_CODEX_MODEL", "gpt-5.3-codex"),
        help="Codex CLI model used when --use-codex is enabled.",
    )
    parser.add_argument(
        "--codex-command",
        default=os.environ.get("STS_AI_CODEX_COMMAND", default_codex_command()),
        help="Path to the codex executable.",
    )
    parser.add_argument(
        "--codex-timeout",
        type=float,
        default=float(os.environ.get("STS_AI_CODEX_TIMEOUT", "45")),
        help="Codex CLI timeout in seconds.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.test:
        return run_test(
            use_openai_api=args.use_openai_api,
            openai_model=args.openai_model,
            openai_api_base=args.openai_api_base,
            openai_timeout=args.openai_timeout,
            use_codex=args.use_codex,
            codex_model=args.codex_model,
            codex_command=args.codex_command,
            codex_timeout=args.codex_timeout,
        )
    options = Options(
        auto_start=args.auto_start,
        character=args.character,
        ascension=args.ascension,
        seed=args.seed,
        use_openai_api=args.use_openai_api,
        openai_model=args.openai_model,
        openai_api_base=args.openai_api_base,
        openai_timeout=args.openai_timeout,
        use_codex=args.use_codex,
        codex_model=args.codex_model,
        codex_command=args.codex_command,
        codex_timeout=args.codex_timeout,
    )
    return run_protocol(options)


if __name__ == "__main__":
    raise SystemExit(main())
