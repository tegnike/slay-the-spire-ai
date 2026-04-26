#!/usr/bin/env python3
"""Summarize CommunicationMod state/action logs for quick debugging."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_DIR = ROOT / "logs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--last", type=int, default=60)
    parser.add_argument("--detect-loop", type=int, default=8)
    return parser.parse_args()


def tail_jsonl(path: Path, count: int) -> list[Any]:
    if not path.exists():
        return []
    lines = tail_lines(path, count)
    rows = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def tail_lines(path: Path, count: int) -> list[str]:
    chunk_size = 64 * 1024
    data = b""
    with path.open("rb") as handle:
        handle.seek(0, 2)
        position = handle.tell()
        while position > 0 and data.count(b"\n") <= count:
            read_size = min(chunk_size, position)
            position -= read_size
            handle.seek(position)
            data = handle.read(read_size) + data
    return data.decode("utf-8", errors="replace").splitlines()[-count:]


def compact_card(card: dict[str, Any]) -> str:
    name = str(card.get("name") or card.get("id") or "?")
    upgrades = int(card.get("upgrades") or 0)
    return f"{name}+{upgrades}" if upgrades else name


def compact_monster(monster: dict[str, Any]) -> str:
    name = str(monster.get("name") or monster.get("id") or "?")
    hp = int(monster.get("current_hp") or 0)
    block = int(monster.get("block") or 0)
    intent = str(monster.get("intent") or "?")
    damage = int(monster.get("move_adjusted_damage") or monster.get("move_base_damage") or 0)
    hits = int(monster.get("move_hits") or 1)
    attack = f" {damage}x{hits}" if damage else ""
    block_text = f"+{block}" if block else ""
    return f"{name}({hp}{block_text},{intent}{attack})"


def screen_choices(state: dict[str, Any], screen_state: dict[str, Any]) -> list[str]:
    raw = state.get("choice_list") or screen_state.get("options") or screen_state.get("choices") or []
    if not isinstance(raw, list):
        return []
    return [str(item.get("name") or item.get("text") or item) if isinstance(item, dict) else str(item) for item in raw]


def summarize_state(payload: dict[str, Any]) -> dict[str, Any]:
    state = payload.get("game_state") or {}
    screen_state = state.get("screen_state") or {}
    combat = state.get("combat_state") or {}
    player = combat.get("player") or {}
    summary: dict[str, Any] = {
        "floor": state.get("floor"),
        "act": state.get("act"),
        "screen": state.get("screen_type") or state.get("screen_name"),
        "room": state.get("room_type"),
        "phase": state.get("room_phase"),
        "hp": f"{state.get('current_hp')}/{state.get('max_hp')}",
        "gold": state.get("gold"),
    }
    if combat:
        summary["energy"] = player.get("energy")
        summary["block"] = player.get("block")
        summary["hand"] = [compact_card(card) for card in combat.get("hand") or [] if isinstance(card, dict)]
        summary["monsters"] = [
            compact_monster(monster) for monster in combat.get("monsters") or [] if isinstance(monster, dict)
        ]
    else:
        choices = screen_choices(state, screen_state)
        if choices:
            summary["choices"] = choices[:6]
        rewards = screen_state.get("rewards") or []
        if isinstance(rewards, list) and rewards:
            summary["rewards"] = [str(item.get("reward_type") or item) for item in rewards if isinstance(item, dict)]
        cards = screen_state.get("cards") or []
        if isinstance(cards, list) and cards:
            summary["cards"] = [compact_card(card) for card in cards[:8] if isinstance(card, dict)]
        nodes = screen_state.get("next_nodes") or []
        if isinstance(nodes, list) and nodes:
            summary["nodes"] = [str(node.get("symbol") or "?") for node in nodes if isinstance(node, dict)]
    return summary


def print_summary(states: list[Any], actions: list[Any], loop_threshold: int) -> None:
    rows = []
    for state_payload, action_payload in zip(states, actions):
        if not isinstance(state_payload, dict) or not isinstance(action_payload, dict):
            continue
        summary = summarize_state(state_payload)
        command = str(action_payload.get("command") or "")
        summary["command"] = command
        rows.append(summary)

    for row in rows:
        prefix = (
            f"act={row.get('act')} floor={row.get('floor')} screen={row.get('screen')} "
            f"room={row.get('room')} phase={row.get('phase')} hp={row.get('hp')} "
            f"gold={row.get('gold')} -> {row.get('command')}"
        )
        details = []
        for key in ("energy", "block", "hand", "monsters", "choices", "rewards", "cards", "nodes"):
            if key in row:
                details.append(f"{key}={row[key]}")
        print(prefix)
        if details:
            print("  " + " ".join(details))

    signatures = Counter(
        (
            row.get("act"),
            row.get("floor"),
            row.get("screen"),
            row.get("room"),
            row.get("phase"),
            row.get("command"),
        )
        for row in rows
    )
    repeated = [(signature, count) for signature, count in signatures.items() if count >= loop_threshold]
    if repeated:
        print("\nPotential loops:")
        for signature, count in repeated:
            print(f"  count={count} signature={signature}")


def main() -> int:
    args = parse_args()
    states = tail_jsonl(args.log_dir / "states.jsonl", args.last)
    actions = tail_jsonl(args.log_dir / "actions.jsonl", args.last)
    pair_count = min(len(states), len(actions))
    print_summary(states[-pair_count:], actions[-pair_count:], args.detect_loop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
