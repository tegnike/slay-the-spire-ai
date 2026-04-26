#!/usr/bin/env python3
"""Create a CommunicationMod config file on macOS."""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_DIR = Path.home() / "Library" / "Preferences" / "ModTheSpire" / "CommunicationMod"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.properties"
DEFAULT_COMMAND = f"python3 {ROOT / 'sts_ai_player.py'} --auto-start --use-openai-api --openai-model gpt-5.4-mini"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--command", default=DEFAULT_COMMAND)
    parser.add_argument("--config-path", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def escape_properties_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("=", "\\=")


def main() -> int:
    args = parse_args()
    body = "\n".join(
        [
            f"command={escape_properties_value(args.command)}",
            "runAtGameStart=true",
            "verbose=false",
            "maxInitializationTimeout=10",
            "",
        ]
    )

    print(f"Config path: {args.config_path}")
    print(f"Command: {args.command}")

    if args.dry_run:
        print(body, end="")
        return 0

    args.config_path.parent.mkdir(parents=True, exist_ok=True)
    args.config_path.write_text(body, encoding="utf-8")
    print("Wrote config.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
