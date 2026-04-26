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
    "Reaper": 115,
    "Corruption": 105,
    "Demon Form": 100,
    "Inflame": 96,
    "Disarm": 94,
    "Carnage": 92,
    "Uppercut": 90,
    "Shrug It Off": 88,
    "Battle Trance": 86,
    "Pommel Strike": 82,
    "Hemokinesis": 80,
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

    lethal = choose_lethal_attack(hand, monsters, energy)
    if lethal is not None:
        card_index, monster_index = lethal
        return f"PLAY {card_index + 1} {monster_index}"

    if incoming > current_block:
        block = best_block_card(hand, energy)
        if block is not None:
            return f"PLAY {block + 1}"

    if target_index is not None:
        attack = best_attack_card(hand, energy, monsters[target_index])
        if attack is not None:
            return f"PLAY {attack + 1} {target_index}"

    any_skill = first_playable_without_target(hand, energy)
    if any_skill is not None:
        return f"PLAY {any_skill + 1}"

    return "END"


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

    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("STS_AI_OPENAI_API_KEY")
    if not api_key:
        logging.warning("OPENAI_API_KEY is not set; using rule command")
        return fallback_command

    available = normalize_available(raw)
    state = raw.get("game_state") or {}
    legal_actions = build_legal_actions(state, available, fallback_command)
    if not legal_actions:
        return fallback_command

    decision = run_openai_responses_api(
        build_decision_payload(state, legal_actions, fallback_command),
        [action.action_id for action in legal_actions],
        options,
        api_key,
    )
    action_id = str(decision.get("action_id") or "")
    by_id = {action.action_id: action for action in legal_actions}
    action = by_id.get(action_id)
    if action is None:
        logging.warning("OpenAI API returned illegal action_id=%s", action_id)
        return fallback_command

    append_jsonl(
        "openai_decisions.jsonl",
        {
            "time": time.time(),
            "model": options.openai_model,
            "action_id": action.action_id,
            "command": action.command,
            "rationale": decision.get("rationale"),
            "confidence": decision.get("confidence"),
            "fallback": fallback_command,
        },
    )
    return action.command


def build_decision_payload(
    state: dict[str, Any],
    legal_actions: list[LegalAction],
    fallback_command: str,
) -> dict[str, Any]:
    return {
        "policy": {
            "objective": "Win the run, prioritizing survival over greed.",
            "constraints": [
                "Choose exactly one legal action_id.",
                "Prefer actions that preserve HP when immediate lethal is not available.",
                "For Ironclad Act 1, value efficient attacks, block against large incoming damage, strong cards, relics, and path flexibility.",
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
    if "play" in available and combat:
        add_combat_actions(actions, combat, available)
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

    for card_index, card in enumerate(hand):
        if not is_playable(card, energy):
            continue
        card_desc = describe_card(card)
        if card.get("has_target"):
            for target_index, monster in live_monsters:
                actions.append(
                    LegalAction(
                        f"play_{card_index + 1}_{target_index}",
                        f"PLAY {card_index + 1} {target_index}",
                        f"Play {card_desc} on {describe_monster(monster)}.",
                    )
                )
        else:
            actions.append(
                LegalAction(
                    f"play_{card_index + 1}",
                    f"PLAY {card_index + 1}",
                    f"Play {card_desc}.",
                )
            )

    if "end" in available:
        actions.append(LegalAction("end", "END", "End the current turn."))


def add_screen_actions(actions: list[LegalAction], state: dict[str, Any], available: set[str]) -> None:
    screen_type = str(state.get("screen_type") or state.get("screen_name") or "").upper()
    screen_state = state.get("screen_state") or {}

    if screen_type == "GRID":
        add_grid_actions(actions, screen_state, available)
        return
    if screen_type == "CARD_REWARD":
        add_card_reward_actions(actions, screen_state, available)
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


def add_card_reward_actions(actions: list[LegalAction], screen_state: dict[str, Any], available: set[str]) -> None:
    cards = screen_state.get("cards") or []
    if "choose" in available:
        for index, card in enumerate(cards):
            if not isinstance(card, dict):
                continue
            score = card_reward_score(card)
            actions.append(
                LegalAction(
                    f"reward_card_{index}",
                    f"CHOOSE {index}",
                    f"Take card reward {index}: {describe_card(card)}; heuristic score {score}.",
                )
            )
    if "skip" in available:
        actions.append(LegalAction("skip_reward", "SKIP", "Skip this card reward."))


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
    candidates: list[tuple[int, int]] = []
    for index, monster in enumerate(monsters):
        if monster.get("is_gone") or monster.get("half_dead"):
            continue
        hp = int(monster.get("current_hp") or 0)
        if hp > 0:
            candidates.append((hp, index))
    if not candidates:
        return None
    return sorted(candidates)[0][1]


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
        return choose_card_reward_command(screen_state, available)

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


def choose_card_reward_command(screen_state: dict[str, Any], available: set[str]) -> str:
    cards = screen_state.get("cards") or []
    if "choose" in available and isinstance(cards, list) and cards:
        index = choose_card_reward_index(cards)
        if index is not None:
            score = card_reward_score(cards[index])
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


def choose_combat_reward_command(state: dict[str, Any], screen_state: dict[str, Any], available: set[str]) -> str:
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
        elif hp_ratio < 0.55:
            score -= 30
    if symbol == "R":
        if hp_ratio < 0.5:
            score += 40
        elif hp_ratio < 0.65:
            score += 25
    return score


def choose_rest_command(state: dict[str, Any], screen_state: dict[str, Any], available: set[str]) -> str:
    if "choose" in available:
        options = screen_choices(state, screen_state) or [str(option) for option in screen_state.get("rest_options") or []]
        if options:
            current_hp = int(state.get("current_hp") or 0)
            max_hp = int(state.get("max_hp") or 1)
            wants_rest = current_hp / max(max_hp, 1) < 0.45
            preferred = "rest" if wants_rest else "smith"
            for index, option in enumerate(options):
                if normalize_name(option) == preferred:
                    return f"CHOOSE {index}"
            return "CHOOSE 0"

    if "proceed" in available:
        return "PROCEED"
    if "state" in available:
        time.sleep(0.25)
        return "STATE"
    return "WAIT 30"


def choose_event_command(state: dict[str, Any], screen_state: dict[str, Any], available: set[str]) -> str:
    choices = screen_choices(state, screen_state)
    if "choose" in available and choices:
        current_hp = int(state.get("current_hp") or 0)
        max_hp = int(state.get("max_hp") or 1)
        hp_ratio = current_hp / max(max_hp, 1)
        gold = int(state.get("gold") or 0)
        candidates: list[tuple[int, int]] = []
        for index, choice in enumerate(choices):
            key = normalize_name(choice)
            score = 50
            if key in {"talk", "leave"}:
                score = 100
            elif "next three combats have 1 hp" in key or "enemies in your next three combats have 1 hp" in key:
                score = 130
            elif "grow" in key or "upgrade" in key or "smith" in key:
                score = 95
            elif "forget" in key or "remove" in key:
                score = 92
            elif "transform" in key or "change" in key:
                score = 80
            elif "fight" in key or "attack" in key:
                score = 85 if hp_ratio >= 0.65 else 35
            elif "heal" in key:
                score = 90 if hp_ratio <= 0.55 else 45
            elif "max hp" in key:
                score = 75
            elif "give gold" in key or "lose gold" in key:
                score = 55 if gold >= 120 else 25
            elif "curse" in key:
                score = 10
            candidates.append((score, index))
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


def choose_card_reward_index(cards: list[Any]) -> int | None:
    candidates: list[tuple[int, int]] = []
    for index, card in enumerate(cards):
        if isinstance(card, dict):
            candidates.append((card_reward_score(card), index))
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: (candidate[0], -candidate[1]))[1]


def card_reward_score(card: dict[str, Any]) -> int:
    card_id = str(card.get("id") or "")
    name = str(card.get("name") or card_id)
    rarity = str(card.get("rarity") or "").upper()
    card_type = str(card.get("type") or "").upper()
    cost = int(card.get("cost") if card.get("cost") is not None else 1)

    score = CARD_REWARD_PRIORITY.get(card_id, CARD_REWARD_PRIORITY.get(name, 0))
    if not score:
        score = {"RARE": 68, "UNCOMMON": 58, "COMMON": 48}.get(rarity, 35)
        if card_type == "ATTACK":
            score += 8
        elif card_type == "POWER":
            score += 6
        if cost >= 3:
            score -= 8
    return score


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
