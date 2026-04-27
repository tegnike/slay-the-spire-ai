#!/usr/bin/env python3
"""Tests for narration cue and prompt behavior."""

from __future__ import annotations

import inspect
import json
import sys
import threading
import unittest
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sts_ai_player
from _sts_ai_player import narration


def attack(name: str, damage_id: str | None = None, cost: int = 1) -> dict[str, Any]:
    return {
        "id": damage_id or name,
        "name": name,
        "type": "ATTACK",
        "cost": cost,
        "is_playable": True,
        "has_target": True,
    }


def combat_raw() -> dict[str, Any]:
    return {
        "game_state": {
            "act": 1,
            "floor": 3,
            "screen_type": "NONE",
            "current_hp": 64,
            "max_hp": 80,
            "combat_state": {
                "hand": [attack("Strike", "Strike_R")],
                "player": {"energy": 1, "block": 0, "current_hp": 64},
                "monsters": [
                    {
                        "name": "Jaw Worm",
                        "current_hp": 6,
                        "block": 0,
                        "intent": "ATTACK",
                        "move_adjusted_damage": 7,
                        "move_hits": 1,
                    }
                ],
            },
        },
        "_sts_ai_action_description": "Play Strike targeting Jaw Worm.",
    }


def screen_raw(screen_type: str = "COMBAT_REWARD") -> dict[str, Any]:
    return {
        "game_state": {
            "act": 1,
            "floor": 4,
            "screen_type": screen_type,
            "current_hp": 62,
            "max_hp": 80,
        },
        "_sts_ai_action_description": "Proceed to the next screen",
    }


def cue_to_dict(cue: Any) -> dict[str, Any] | None:
    if cue is None:
        return None
    if isinstance(cue, dict):
        return cue
    if is_dataclass(cue):
        return asdict(cue)
    if hasattr(cue, "to_dict"):
        return cue.to_dict()
    return {
        "text": getattr(cue, "text", None),
        "emotion": getattr(cue, "emotion", None),
        "metadata": getattr(cue, "metadata", None),
    }


def require_director(test_case: unittest.TestCase) -> Any:
    director_cls = getattr(narration, "NarrationDirector", None)
    test_case.assertIsNotNone(director_cls, "NarrationDirector should provide stateful narration cue behavior.")
    return director_cls


def next_cue(director: Any, raw: dict[str, Any], command: str) -> dict[str, Any] | None:
    for method_name in ("choose", "next_cue", "build_cue"):
        method = getattr(director, method_name, None)
        if method is not None:
            return cue_to_dict(method(raw, command))
    raise AssertionError("NarrationDirector should expose choose(raw, command), next_cue(raw, command), or build_cue(raw, command).")


class NarrationImprovementTests(unittest.TestCase):
    def test_official_emotions_are_supported_and_default_to_neutral(self):
        self.assertEqual(
            set(narration.OFFICIAL_EMOTIONS),
            {"neutral", "happy", "angry", "sad", "thinking"},
        )
        self.assertEqual(set(narration.SUPPORTED_PACES), {"slow", "normal", "fast"})
        self.assertEqual(set(narration.SUPPORTED_INTENSITIES), {"low", "normal", "high"})
        self.assertEqual(
            set(narration.SUPPORTED_QUEUE_POLICIES),
            {"enqueue", "dropIfBusy", "replaceIfHigherPriority"},
        )
        self.assertEqual(
            inspect.signature(narration.NarrationUIClient.say).parameters["emotion"].default,
            "neutral",
        )

    def test_director_emits_json_serializable_metadata_friendly_cue(self):
        director_cls = require_director(self)
        cue = next_cue(director_cls(), combat_raw(), "PLAY 1 0")

        self.assertIsNotNone(cue)
        assert cue is not None
        self.assertIsInstance(cue.get("text"), str)
        self.assertIn(cue.get("emotion"), narration.OFFICIAL_EMOTIONS)
        self.assertIsInstance(cue.get("reason"), str)
        self.assertIsInstance(cue.get("importance"), int)
        self.assertIn(cue.get("pace"), narration.SUPPORTED_PACES)
        self.assertIn(cue.get("intensity"), narration.SUPPORTED_INTENSITIES)
        self.assertIn(cue.get("queue_policy"), narration.SUPPORTED_QUEUE_POLICIES)
        self.assertIsInstance(cue.get("priority"), int)
        json.dumps(cue, ensure_ascii=False)
        self.assertNotIn("game_state", cue)
        self.assertNotIn("combat_state", cue)

    def test_director_avoids_repeating_recent_combat_lines(self):
        director_cls = require_director(self)
        director = director_cls()

        first = next_cue(director, combat_raw(), "PLAY 1 0")
        second = next_cue(director, combat_raw(), "PLAY 1 0")

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None
        assert second is not None
        self.assertNotEqual(second.get("text"), first.get("text"))

    def test_director_may_skip_low_value_repeated_commands(self):
        director_cls = require_director(self)
        director = director_cls()

        first = next_cue(director, screen_raw(), "PROCEED")
        second = next_cue(director, screen_raw(), "PROCEED")

        self.assertIsNotNone(first)
        self.assertIsNone(second)

        reason = getattr(director, "last_suppression_reason")()
        self.assertIn(reason, {"repeat_or_low_value", "model_silent"})

    def test_high_importance_cue_uses_runtime_queue_controls(self):
        director_cls = require_director(self)
        cue = next_cue(director_cls(), combat_raw(), "PLAY 1 0")

        self.assertIsNotNone(cue)
        assert cue is not None
        self.assertEqual(cue.get("pace"), "fast")
        self.assertEqual(cue.get("intensity"), "high")
        self.assertEqual(cue.get("queue_policy"), "replaceIfHigherPriority")
        self.assertGreaterEqual(cue.get("priority"), 7)

    def test_client_say_sends_runtime_style_controls(self):
        sent: list[dict[str, Any]] = []
        client = narration.NarrationUIClient(
            url="ws://localhost:3010/ws/narration",
            wait_for_completion=False,
        )
        client._ensure_connected = lambda: True  # type: ignore[method-assign]
        client._send_json = sent.append  # type: ignore[method-assign]

        status = client.say(
            "いけーー！",
            emotion="happy",
            pace="fast",
            intensity="high",
            priority=9,
            queue_policy="replaceIfHigherPriority",
            max_queue_ms=900,
            metadata={"command": "PLAY 1 0"},
        )

        self.assertEqual(status, "sent")
        self.assertEqual(sent[0]["type"], "narration:say")
        self.assertEqual(sent[0]["pace"], "fast")
        self.assertEqual(sent[0]["intensity"], "high")
        self.assertEqual(sent[0]["priority"], 9)
        self.assertEqual(sent[0]["queuePolicy"], "replaceIfHigherPriority")
        self.assertEqual(sent[0]["maxQueueMs"], 900)
        self.assertFalse(sent[0]["subtitleOnly"])

    def test_client_suppress_sends_observer_visible_event(self):
        sent: list[dict[str, Any]] = []
        client = narration.NarrationUIClient(
            url="ws://localhost:3010/ws/narration",
            wait_for_completion=False,
        )
        client._ensure_connected = lambda: True  # type: ignore[method-assign]
        client._send_json = sent.append  # type: ignore[method-assign]

        status = client.suppress(
            "直近と似た実況を抑制しました。",
            reason="repeat_or_low_value",
            metadata={"command": "PROCEED"},
        )

        self.assertEqual(status, "suppressed")
        self.assertEqual(client.last_status_reason, "repeat_or_low_value")
        self.assertEqual(sent[0]["type"], "narration:suppressed")
        self.assertEqual(sent[0]["reason"], "repeat_or_low_value")

    def test_client_records_terminal_status_reason(self):
        client = narration.NarrationUIClient(url="ws://localhost:3010/ws/narration")
        pending = narration.PendingUtterance(event=threading.Event())
        client._pending["utt_1"] = pending

        client._handle_message(
            json.dumps({"type": "narration:skipped", "id": "utt_1", "reason": "queue_drop_busy"})
        )

        self.assertTrue(pending.event.is_set())
        self.assertEqual(pending.status, "skipped")
        self.assertEqual(pending.reason, "queue_drop_busy")

    def test_client_records_supported_values_from_ready_messages(self):
        client = narration.NarrationUIClient(url="ws://localhost:3010/ws/narration")

        client._handle_message(
            json.dumps(
                {
                    "type": "narration:ready",
                    "supportedEmotions": ["neutral", "happy"],
                    "supportedPaces": ["slow", "fast"],
                    "supportedIntensities": ["low", "high"],
                    "supportedQueuePolicies": ["enqueue", "dropIfBusy"],
                }
            )
        )

        self.assertEqual(client.supported_emotions, {"neutral", "happy"})
        self.assertEqual(client.supported_paces, {"slow", "fast"})
        self.assertEqual(client.supported_intensities, {"low", "high"})
        self.assertEqual(client.supported_queue_policies, {"enqueue", "dropIfBusy"})

    def test_prompts_include_recent_narration_examples_when_provided(self):
        state = combat_raw()["game_state"]
        actions = sts_ai_player.build_legal_actions(
            state,
            {"play", "end"},
            "PLAY 1 0",
            include_fallback_action=False,
        )
        legal_action_dicts = [
            {"action_id": action.action_id, "command": action.command, "description": action.description}
            for action in actions
        ]
        recent_examples = ["ストライクで押し切ります。", "ここは素早く次へ進みます。"]

        payload = sts_ai_player.build_decision_payload(
            state,
            actions,
            include_narration=True,
            recent_narration_examples=recent_examples,
        )
        prompt = sts_ai_player.build_codex_prompt(
            state,
            legal_action_dicts,
            "PLAY 1 0",
            include_narration=True,
            recent_narration_examples=recent_examples,
        )

        self.assertEqual(payload["narration"]["recent_examples"], recent_examples)
        self.assertIn("recent_examples", prompt)
        for example in recent_examples:
            self.assertIn(example, prompt)


if __name__ == "__main__":
    unittest.main()
