"""Runtime loop and CLI entrypoints for the Slay the Spire AI."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time

from . import engine
from .models import Options


def run_protocol(options: Options) -> int:
    engine.setup_logging()
    process_id = os.getpid()
    logging.info("AI process started pid=%s", process_id)
    print("ready", flush=True)

    state_index = 0
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
            state_index += 1
            payload["_sts_ai_log_index"] = state_index
            payload["_sts_ai_process_id"] = process_id
            payload["_sts_ai_received_at"] = time.time()
            engine.append_jsonl("states.jsonl", payload)
            command = engine.choose_command(payload, options)
            engine.remember_potion_use(command, payload)

        action = {"time": time.time(), "state_index": state_index, "process_id": process_id, "command": command}
        engine.append_jsonl("actions.jsonl", action)
        logging.info("command=%s", command)
        print(command, flush=True)

    logging.info("AI process stopped")
    return 0


def default_codex_command() -> str:
    if engine.CODEX_APP_COMMAND.exists():
        return str(engine.CODEX_APP_COMMAND)
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
    engine.setup_logging()
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
        stop_on_game_over=False,
        max_floor=None,
        use_openai_api=use_openai_api,
        openai_model=openai_model,
        openai_api_base=openai_api_base,
        openai_timeout=openai_timeout,
        use_codex=use_codex,
        codex_model=codex_model,
        codex_command=codex_command or default_codex_command(),
        codex_timeout=codex_timeout,
    )
    try:
        command = engine.choose_command(sample, options)
    except Exception as error:
        if use_openai_api:
            print(f"OpenAI API error: {error}", file=sys.stderr)
            return 2
        raise
    print(command)
    if use_openai_api:
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("STS_AI_OPENAI_API_KEY")
        if not api_key or engine.OPENAI_API_DISABLED_REASON or engine.OPENAI_API_LAST_ERROR:
            return 2
    return 0 if command == "PLAY 1" else 1


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Run a local decision smoke test.")
    parser.add_argument("--auto-start", action="store_true", help="Start a new run from the main menu.")
    parser.add_argument("--character", default="IRONCLAD", help="Character for START command.")
    parser.add_argument("--ascension", type=int, default=0, help="Ascension level for START command.")
    parser.add_argument("--seed", default=None, help="Optional user-facing seed string for START command.")
    parser.add_argument("--seed-long", default=None, help="Optional numeric game_state.seed value converted to a user-facing seed.")
    parser.add_argument("--stop-on-game-over", action="store_true", help="Pause instead of starting another run after death.")
    parser.add_argument("--max-floor", type=int, default=None, help="Pause once this floor or later is reached.")
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
    try:
        start_seed = engine.normalize_start_seed(args.seed, args.seed_long)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    options = Options(
        auto_start=args.auto_start,
        character=args.character,
        ascension=args.ascension,
        seed=start_seed,
        stop_on_game_over=args.stop_on_game_over,
        max_floor=args.max_floor,
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
