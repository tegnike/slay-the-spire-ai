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
    parser.add_argument("--floor-stall", type=int, default=None)
    parser.add_argument("--low-hp-ratio", type=float, default=0.35)
    parser.add_argument("--decision-log", default="openai_decisions.jsonl")
    parser.add_argument("--no-decisions", action="store_true")
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


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def living_monsters(combat: dict[str, Any]) -> list[dict[str, Any]]:
    monsters = combat.get("monsters") or []
    if not isinstance(monsters, list):
        return []
    living = []
    for monster in monsters:
        if not isinstance(monster, dict):
            continue
        if monster.get("is_gone") or monster.get("half_dead"):
            continue
        if to_int(monster.get("current_hp")) <= 0:
            continue
        living.append(monster)
    return living


def monster_incoming(monster: dict[str, Any]) -> int:
    intent = str(monster.get("intent") or "")
    if "ATTACK" not in intent:
        return 0
    damage = to_int(monster.get("move_adjusted_damage") or monster.get("move_base_damage"))
    hits = max(1, to_int(monster.get("move_hits"), 1))
    return max(0, damage) * hits


def list_key(values: Any) -> tuple[str, ...]:
    if not isinstance(values, list):
        return ()
    return tuple(str(value).lower() for value in values)


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
    current_hp = state.get("current_hp") if state.get("current_hp") is not None else player.get("current_hp")
    max_hp = state.get("max_hp") if state.get("max_hp") is not None else player.get("max_hp")
    summary: dict[str, Any] = {
        "floor": state.get("floor"),
        "act": state.get("act"),
        "screen": state.get("screen_type") or state.get("screen_name"),
        "room": state.get("room_type"),
        "phase": state.get("room_phase"),
        "hp": f"{current_hp}/{max_hp}",
        "current_hp": current_hp,
        "max_hp": max_hp,
        "gold": state.get("gold"),
    }
    if combat:
        summary["energy"] = player.get("energy")
        summary["block"] = player.get("block")
        hand = [compact_card(card) for card in combat.get("hand") or [] if isinstance(card, dict)]
        monsters = living_monsters(combat)
        incoming = sum(monster_incoming(monster) for monster in monsters)
        block = to_int(player.get("block"))
        summary["turn"] = combat.get("turn")
        summary["incoming"] = incoming
        summary["incoming_net"] = max(0, incoming - block)
        summary["hand"] = hand
        summary["hand_key"] = list_key(hand)
        summary["monsters"] = [compact_monster(monster) for monster in monsters]
    else:
        choices = screen_choices(state, screen_state)
        if choices:
            summary["choices"] = choices[:6]
            summary["choices_key"] = list_key(summary["choices"])
        rewards = screen_state.get("rewards") or []
        if isinstance(rewards, list) and rewards:
            summary["rewards"] = [str(item.get("reward_type") or item) for item in rewards if isinstance(item, dict)]
            summary["rewards_key"] = list_key(summary["rewards"])
        cards = screen_state.get("cards") or []
        if isinstance(cards, list) and cards:
            summary["cards"] = [compact_card(card) for card in cards[:8] if isinstance(card, dict)]
            summary["cards_key"] = list_key(summary["cards"])
        nodes = screen_state.get("next_nodes") or []
        if isinstance(nodes, list) and nodes:
            summary["nodes"] = [str(node.get("symbol") or "?") for node in nodes if isinstance(node, dict)]
    return summary


def build_rows(states: list[Any], actions: list[Any], decisions: list[Any] | None = None) -> list[dict[str, Any]]:
    rows = []
    for state_payload, action_payload in pair_state_actions(states, actions):
        if not isinstance(state_payload, dict) or not isinstance(action_payload, dict):
            continue
        summary = summarize_state(state_payload)
        command = str(action_payload.get("command") or "")
        summary["command"] = command
        summary["state_index"] = action_payload.get("state_index") or state_payload.get("_sts_ai_log_index")
        summary["process_id"] = action_payload.get("process_id") or state_payload.get("_sts_ai_process_id")
        summary["action_time"] = action_payload.get("time")
        rows.append(summary)
    attach_decisions(rows, decisions or [])
    return rows


def print_summary(
    states: list[Any],
    actions: list[Any],
    loop_threshold: int,
    decisions: list[Any] | None = None,
    floor_stall_threshold: int | None = None,
    low_hp_ratio: float = 0.35,
) -> None:
    rows = build_rows(states, actions, decisions)

    for row in rows:
        prefix = (
            f"idx={row.get('state_index')} act={row.get('act')} floor={row.get('floor')} screen={row.get('screen')} "
            f"room={row.get('room')} phase={row.get('phase')} hp={row.get('hp')} "
            f"gold={row.get('gold')} -> {row.get('command')}"
        )
        details = []
        for key in ("energy", "block", "hand", "monsters", "choices", "rewards", "cards", "nodes"):
            if key in row:
                details.append(f"{key}={row[key]}")
        decision = compact_decision(row)
        if decision:
            details.append(decision)
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
    print_diagnostics(rows, loop_threshold, floor_stall_threshold, low_hp_ratio)


def attach_decisions(rows: list[dict[str, Any]], decisions: list[Any]) -> None:
    usable_decisions = [
        decision
        for decision in decisions
        if isinstance(decision, dict) and isinstance(decision.get("time"), (int, float))
    ]
    used: set[int] = set()
    for row in rows:
        row_index = row.get("state_index")
        row_process_id = row.get("process_id")
        if row_index is not None:
            for index, decision in enumerate(usable_decisions):
                if index in used:
                    continue
                if decision.get("state_index") != row_index:
                    continue
                if row_process_id is not None and decision.get("process_id") not in {None, row_process_id}:
                    continue
                if not decision_matches_action(decision, str(row.get("command") or "")):
                    continue
                used.add(index)
                row["decision"] = decision
                break
            if row.get("decision"):
                continue
        action_time = row.get("action_time")
        if not isinstance(action_time, (int, float)):
            continue
        best_index = None
        best_delta = None
        for index, decision in enumerate(usable_decisions):
            if index in used:
                continue
            delta = abs(float(action_time) - float(decision["time"]))
            if delta > 2.0:
                continue
            if not decision_matches_action(decision, str(row.get("command") or "")):
                continue
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best_index = index
        if best_index is None:
            continue
        used.add(best_index)
        row["decision"] = usable_decisions[best_index]


def decision_matches_action(decision: dict[str, Any], command: str) -> bool:
    candidates = [
        decision.get("command"),
        decision.get("model_command"),
        decision.get("fallback"),
    ]
    return command in {str(candidate) for candidate in candidates if candidate is not None}


def compact_decision(row: dict[str, Any]) -> str:
    decision = row.get("decision")
    if not isinstance(decision, dict):
        return ""
    command = str(row.get("command") or "")
    model_command = decision.get("model_command")
    fallback = decision.get("fallback")
    override_reason = decision.get("override_reason")
    interesting = bool(override_reason) or (
        model_command is not None and str(model_command) != command
    )
    if not interesting:
        return ""
    parts = []
    if model_command is not None:
        parts.append(f"model={model_command}")
    if fallback is not None:
        parts.append(f"fallback={fallback}")
    if decision.get("confidence") is not None:
        parts.append(f"conf={decision.get('confidence')}")
    if override_reason:
        parts.append(f"override={override_reason}")
    return "llm=(" + " ".join(parts) + ")"


def print_diagnostics(
    rows: list[dict[str, Any]],
    loop_threshold: int,
    floor_stall_threshold: int | None,
    low_hp_ratio: float,
) -> None:
    if not rows:
        return
    if floor_stall_threshold is None:
        floor_stall_threshold = max(12, loop_threshold * 3)

    diagnostics: list[tuple[str, list[str]]] = [
        ("Same screen/command repeats", same_screen_command_repeats(rows, loop_threshold)),
        ("Reward loop candidates", reward_loop_candidates(rows, loop_threshold)),
        ("Floor stall candidates", floor_stall_candidates(rows, floor_stall_threshold)),
        ("Low HP dangerous combat", low_hp_dangerous_combat(rows, low_hp_ratio)),
        ("OpenAI overrides", openai_override_summary(rows)),
    ]
    emitted = False
    for title, lines in diagnostics:
        if not lines:
            continue
        if not emitted:
            print("\nDiagnostics:")
            emitted = True
        print(f"  {title}:")
        for line in lines:
            print(f"    {line}")


def base_screen_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("act"),
        row.get("floor"),
        row.get("screen"),
        row.get("room"),
        row.get("phase"),
    )


def detailed_screen_key(row: dict[str, Any]) -> tuple[Any, ...]:
    if row.get("screen") == "NONE" and row.get("phase") == "COMBAT":
        return base_screen_key(row) + (
            row.get("turn"),
            row.get("energy"),
            tuple(row.get("hand_key") or ()),
            tuple(row.get("monsters") or ()),
        )
    return base_screen_key(row) + (
        tuple(row.get("choices_key") or ()),
        tuple(row.get("rewards_key") or ()),
        tuple(row.get("cards_key") or ()),
        tuple(row.get("nodes") or ()),
    )


def same_screen_command_repeats(rows: list[dict[str, Any]], threshold: int) -> list[str]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        key = detailed_screen_key(row) + (row.get("command"),)
        grouped.setdefault(key, []).append(row)

    findings = []
    for key, matching_rows in grouped.items():
        if len(matching_rows) < threshold:
            continue
        first = matching_rows[0]
        last = matching_rows[-1]
        findings.append(
            (
                len(matching_rows),
                f"count={len(matching_rows)} idx={first.get('state_index')}..{last.get('state_index')} "
                f"act={first.get('act')} floor={first.get('floor')} screen={first.get('screen')} "
                f"command={first.get('command')} detail={short_detail(first)}",
            )
        )
    return [line for _, line in sorted(findings, reverse=True)[:8]]


def reward_loop_candidates(rows: list[dict[str, Any]], threshold: int) -> list[str]:
    reward_screens = {"COMBAT_REWARD", "CARD_REWARD", "BOSS_REWARD"}
    reward_rows = [row for row in rows if row.get("screen") in reward_screens]
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in reward_rows:
        key = detailed_screen_key(row) + (row.get("command"),)
        grouped.setdefault(key, []).append(row)

    findings = []
    for _, matching_rows in grouped.items():
        if len(matching_rows) < threshold:
            continue
        first = matching_rows[0]
        last = matching_rows[-1]
        findings.append(
            (
                len(matching_rows),
                f"count={len(matching_rows)} idx={first.get('state_index')}..{last.get('state_index')} "
                f"floor={first.get('floor')} screen={first.get('screen')} command={first.get('command')} "
                f"detail={short_detail(first)}",
            )
        )
    return [line for _, line in sorted(findings, reverse=True)[:8]]


def floor_stall_candidates(rows: list[dict[str, Any]], threshold: int) -> list[str]:
    findings = []
    run: list[dict[str, Any]] = []
    previous_key: tuple[Any, Any] | None = None
    for row in rows + [{}]:
        key = (row.get("act"), row.get("floor"))
        if row and key == previous_key:
            run.append(row)
            continue
        if previous_key is not None and len(run) >= threshold and previous_key[1] is not None:
            findings.append(format_floor_stall(run))
        run = [row] if row else []
        previous_key = key if row else None
    return findings[:8]


def format_floor_stall(run: list[dict[str, Any]]) -> str:
    first = run[0]
    last = run[-1]
    screens = sorted({str(row.get("screen")) for row in run})
    commands = Counter(str(row.get("command")) for row in run)
    top_commands = ", ".join(f"{command}x{count}" for command, count in commands.most_common(4))
    return (
        f"count={len(run)} idx={first.get('state_index')}..{last.get('state_index')} "
        f"act={first.get('act')} floor={first.get('floor')} screens={screens} commands={top_commands}"
    )


def low_hp_dangerous_combat(rows: list[dict[str, Any]], low_hp_ratio: float) -> list[str]:
    findings = []
    for row in rows:
        current_hp = to_int(row.get("current_hp"))
        max_hp = to_int(row.get("max_hp"))
        if current_hp <= 0 or max_hp <= 0:
            continue
        if row.get("phase") != "COMBAT":
            continue
        incoming_net = to_int(row.get("incoming_net"))
        incoming = to_int(row.get("incoming"))
        hp_ratio = current_hp / max_hp
        lethal = incoming_net >= current_hp and incoming > 0
        low_and_hit = hp_ratio <= low_hp_ratio and incoming_net > 0
        elite_or_boss = row.get("room") in {"MonsterRoomElite", "MonsterRoomBoss", "BossRoom"} and hp_ratio <= low_hp_ratio
        if not (lethal or low_and_hit or elite_or_boss):
            continue
        marker = "LETHAL" if lethal else "danger"
        decision = compact_decision(row)
        suffix = f" {decision}" if decision else ""
        findings.append(
            f"{marker} idx={row.get('state_index')} act={row.get('act')} floor={row.get('floor')} "
            f"hp={row.get('hp')} incoming={incoming} net={incoming_net} block={row.get('block')} "
            f"room={row.get('room')} command={row.get('command')} monsters={row.get('monsters')}{suffix}"
        )
    return findings[-8:]


def openai_override_summary(rows: list[dict[str, Any]]) -> list[str]:
    findings = []
    for row in rows:
        decision = row.get("decision")
        if not isinstance(decision, dict):
            continue
        override_reason = decision.get("override_reason")
        model_command = decision.get("model_command")
        command = row.get("command")
        if not override_reason and (model_command is None or str(model_command) == str(command)):
            continue
        findings.append(
            f"idx={row.get('state_index')} floor={row.get('floor')} screen={row.get('screen')} "
            f"model={model_command} final={command} fallback={decision.get('fallback')} "
            f"override={override_reason}"
        )
    return findings[-8:]


def short_detail(row: dict[str, Any]) -> str:
    for key in ("cards", "rewards", "choices", "monsters", "nodes"):
        if key in row:
            return f"{key}={row[key]}"
    return f"hp={row.get('hp')}"


def pair_state_actions(states: list[Any], actions: list[Any]) -> list[tuple[Any, Any]]:
    states_by_index = {}
    for state in states:
        if not isinstance(state, dict) or state.get("_sts_ai_log_index") is None:
            continue
        key = state_action_key(state.get("_sts_ai_log_index"), state.get("_sts_ai_process_id"))
        states_by_index[key] = state
        states_by_index.setdefault(state_action_key(state.get("_sts_ai_log_index"), None), state)
    if states_by_index and any(isinstance(action, dict) and action.get("state_index") is not None for action in actions):
        pairs = []
        for action in actions:
            if not isinstance(action, dict):
                continue
            state = states_by_index.get(state_action_key(action.get("state_index"), action.get("process_id")))
            if state is None:
                state = states_by_index.get(state_action_key(action.get("state_index"), None))
            if state is not None:
                pairs.append((state, action))
        if pairs:
            return pairs

    timed_states = [
        state for state in states if isinstance(state, dict) and isinstance(state.get("_sts_ai_received_at"), (int, float))
    ]
    if timed_states and any(isinstance(action, dict) and isinstance(action.get("time"), (int, float)) for action in actions):
        pairs = []
        state_cursor = 0
        for action in actions:
            if not isinstance(action, dict) or not isinstance(action.get("time"), (int, float)):
                continue
            while (
                state_cursor + 1 < len(timed_states)
                and timed_states[state_cursor + 1].get("_sts_ai_received_at") <= action["time"]
            ):
                state_cursor += 1
            pairs.append((timed_states[state_cursor], action))
        if pairs:
            return pairs

    pair_count = min(len(states), len(actions))
    return list(zip(states[-pair_count:], actions[-pair_count:]))


def state_action_key(state_index: Any, process_id: Any) -> tuple[Any, Any]:
    return state_index, process_id


def main() -> int:
    args = parse_args()
    states = tail_jsonl(args.log_dir / "states.jsonl", args.last)
    actions = tail_jsonl(args.log_dir / "actions.jsonl", args.last)
    decisions = []
    if not args.no_decisions:
        decision_tail = max(args.last * 3, args.last + 100)
        decisions = tail_jsonl(args.log_dir / args.decision_log, decision_tail)
    print_summary(
        states,
        actions,
        args.detect_loop,
        decisions=decisions,
        floor_stall_threshold=args.floor_stall,
        low_hp_ratio=args.low_hp_ratio,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
