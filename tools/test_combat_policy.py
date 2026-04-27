#!/usr/bin/env python3
"""Focused tests for combat helper policy logic."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
import os


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sts_ai_player
from _sts_ai_player.models import Options


def attack(name: str, damage_id: str | None = None, cost: int = 1, upgrades: int = 0) -> dict:
    return {
        "id": damage_id or name,
        "name": name,
        "type": "ATTACK",
        "cost": cost,
        "upgrades": upgrades,
        "is_playable": True,
        "has_target": True,
    }


def skill(name: str, block_id: str | None = None, cost: int = 1, upgrades: int = 0) -> dict:
    return {
        "id": block_id or name,
        "name": name,
        "type": "SKILL",
        "cost": cost,
        "upgrades": upgrades,
        "is_playable": True,
        "has_target": False,
    }


def options(**overrides) -> Options:
    defaults = {
        "auto_start": False,
        "character": "IRONCLAD",
        "ascension": 0,
        "seed": None,
        "stop_on_game_over": True,
        "max_floor": None,
        "use_openai_api": False,
        "openai_model": "gpt-5.4-mini",
        "openai_api_base": "https://api.openai.com/v1",
        "openai_timeout": 20.0,
        "use_codex": False,
        "codex_model": "gpt-5.4-mini",
        "codex_command": "codex",
        "codex_timeout": 30.0,
        "narration_ui": False,
        "narration_url": "ws://localhost:5175/ws/narration",
        "narration_speaker": "nike",
        "narration_wait": False,
        "narration_timeout": 12.0,
    }
    defaults.update(overrides)
    return Options(**defaults)


class CombatPolicyTests(unittest.TestCase):
    def test_estimate_card_damage_uses_known_base_and_upgrade_rules(self):
        self.assertEqual(sts_ai_player.estimate_card_damage(attack("Strike", "Strike_R")), 6)
        self.assertEqual(sts_ai_player.estimate_card_damage(attack("Bash+", "Bash", upgrades=1)), 10)
        self.assertEqual(sts_ai_player.estimate_card_damage(attack("Pommel Strike", upgrades=1)), 12)
        self.assertEqual(sts_ai_player.estimate_card_damage(attack("Unknown Attack")), 6)

    def test_estimate_card_block_uses_known_base_and_upgrade_rules(self):
        self.assertEqual(sts_ai_player.estimate_card_block(skill("Defend", "Defend_R")), 5)
        self.assertEqual(sts_ai_player.estimate_card_block(skill("Defend+", "Defend_R", upgrades=1)), 8)
        self.assertEqual(sts_ai_player.estimate_card_block(skill("Shrug It Off", upgrades=1)), 11)
        self.assertEqual(sts_ai_player.estimate_card_block(skill("Unknown Skill")), 0)

    def test_parse_play_command_converts_card_index_and_preserves_target_index(self):
        self.assertEqual(sts_ai_player.parse_play_command("PLAY 2 0"), (1, 0))
        self.assertEqual(sts_ai_player.parse_play_command("play 1"), (0, None))
        self.assertIsNone(sts_ai_player.parse_play_command("END"))
        self.assertIsNone(sts_ai_player.parse_play_command("PLAY Strike 0"))
        self.assertIsNone(sts_ai_player.parse_play_command("PLAY 1 target"))

    def test_model_command_attack_damage_requires_targeted_card_and_target(self):
        combat = {
            "hand": [
                skill("Defend", "Defend_R"),
                attack("Bash", "Bash"),
            ],
            "monsters": [{"name": "Jaw Worm", "current_hp": 8, "block": 0}],
        }

        self.assertEqual(sts_ai_player.model_command_attack_damage("PLAY 2 0", combat), 8)
        self.assertEqual(sts_ai_player.model_command_attack_damage("PLAY 2", combat), 0)
        self.assertEqual(sts_ai_player.model_command_attack_damage("PLAY 1 0", combat), 0)
        self.assertEqual(sts_ai_player.model_command_attack_damage("PLAY 9 0", combat), 0)

    def test_model_command_is_lethal_attack_counts_monster_block(self):
        combat = {
            "hand": [
                attack("Strike", "Strike_R"),
                attack("Bash+", "Bash", upgrades=1),
            ],
            "monsters": [
                {"name": "Cultist", "current_hp": 6, "block": 5},
                {"name": "Louse", "current_hp": 10, "block": 0},
            ],
        }

        self.assertFalse(sts_ai_player.model_command_is_lethal_attack("PLAY 1 0", combat))
        self.assertTrue(sts_ai_player.model_command_is_lethal_attack("PLAY 2 1", combat))
        self.assertFalse(sts_ai_player.model_command_is_lethal_attack("PLAY 2", combat))

    def test_model_command_is_lethal_attack_counts_vulnerable(self):
        combat = {
            "hand": [attack("Bludgeon", cost=3)],
            "player": {"energy": 3, "powers": []},
            "monsters": [
                {
                    "name": "Lagavulin",
                    "current_hp": 37,
                    "block": 0,
                    "powers": [{"name": "Vulnerable", "id": "Vulnerable", "amount": 2}],
                }
            ],
        }

        self.assertTrue(sts_ai_player.model_command_is_lethal_attack("PLAY 1 0", combat))

    def test_choose_lethal_attack_prefers_lethal_enemy_with_highest_incoming_damage(self):
        hand = [
            attack("Strike", "Strike_R"),
            attack("Bash", "Bash", cost=2),
            {**attack("Carnage", cost=2), "is_playable": False},
        ]
        monsters = [
            {"name": "Non-attacker", "current_hp": 6, "block": 0, "intent": "BUFF"},
            {
                "name": "Attacker",
                "current_hp": 6,
                "block": 0,
                "intent": "ATTACK",
                "move_adjusted_damage": 7,
                "move_hits": 1,
            },
            {
                "name": "Bigger attacker",
                "current_hp": 8,
                "block": 0,
                "intent": "ATTACK",
                "move_adjusted_damage": 12,
                "move_hits": 1,
            },
        ]

        self.assertEqual(sts_ai_player.choose_lethal_attack(hand, monsters, energy=2), (1, 2))

    def test_choose_lethal_attack_ignores_unplayable_gone_and_blocked_survivors(self):
        hand = [
            attack("Strike", "Strike_R"),
            {**attack("Bash", "Bash", cost=2), "is_playable": False},
        ]
        monsters = [
            {"name": "Gone", "current_hp": 4, "block": 0, "is_gone": True},
            {"name": "Blocked", "current_hp": 5, "block": 2},
        ]

        self.assertIsNone(sts_ai_player.choose_lethal_attack(hand, monsters, energy=1))

    def test_choose_turn_lethal_attack_finds_multi_card_lagavulin_kill(self):
        hand = [
            skill("Defend", "Defend_R"),
            attack("Pommel Strike"),
            attack("Twin Strike"),
            attack("Strike", "Strike_R"),
            attack("Strike", "Strike_R"),
        ]
        monsters = [
            {
                "name": "Lagavulin",
                "current_hp": 25,
                "block": 0,
                "intent": "ATTACK",
                "move_adjusted_damage": 18,
                "move_hits": 1,
            }
        ]

        self.assertEqual(sts_ai_player.choose_turn_lethal_attack(hand, monsters, energy=3), (2, 0))

    def test_combat_policy_prefers_turn_lethal_over_block(self):
        hand = [
            skill("Defend", "Defend_R"),
            attack("Pommel Strike"),
            attack("Twin Strike"),
            attack("Strike", "Strike_R"),
            attack("Strike", "Strike_R"),
        ]
        state = {
            "act": 1,
            "floor": 8,
            "current_hp": 23,
            "combat_state": {
                "hand": hand,
                "player": {"energy": 3, "block": 0, "current_hp": 23},
                "monsters": [
                    {
                        "name": "Lagavulin",
                        "current_hp": 25,
                        "block": 0,
                        "intent": "ATTACK",
                        "move_adjusted_damage": 18,
                        "move_hits": 1,
                    }
                ],
            },
        }

        self.assertEqual(sts_ai_player.choose_combat_command(state, {"end"}), "PLAY 3 0")

    def test_model_command_starts_turn_lethal_allows_attack_override(self):
        combat = {
            "hand": [
                skill("Defend", "Defend_R"),
                attack("Pommel Strike"),
                attack("Twin Strike"),
                attack("Strike", "Strike_R"),
                attack("Strike", "Strike_R"),
            ],
            "player": {"energy": 3},
            "monsters": [{"name": "Lagavulin", "current_hp": 25, "block": 0}],
        }

        self.assertTrue(sts_ai_player.model_command_starts_turn_lethal("PLAY 2 0", combat))
        self.assertTrue(sts_ai_player.model_command_starts_turn_lethal("PLAY 3 0", combat))
        self.assertFalse(sts_ai_player.model_command_starts_turn_lethal("PLAY 1", combat))

    def test_openai_override_never_replaces_valid_llm_strategy(self):
        state = {
            "screen_type": "NONE",
            "current_hp": 20,
            "combat_state": {
                "hand": [
                    skill("Defend", "Defend_R"),
                    attack("Strike", "Strike_R"),
                ],
                "player": {"energy": 2, "block": 0, "current_hp": 20},
                "monsters": [
                    {
                        "name": "Lagavulin",
                        "current_hp": 30,
                        "block": 0,
                        "intent": "ATTACK",
                        "move_adjusted_damage": 18,
                        "move_hits": 1,
                    }
                ],
            },
        }

        self.assertIsNone(
            sts_ai_player.openai_override_reason(
                state,
                model_command="PLAY 2 0",
                fallback_command="PLAY 1",
                decision={"confidence": 0.05},
            )
        )

    def test_openai_override_never_replaces_valid_screen_choice(self):
        state = {
            "screen_type": "CARD_REWARD",
            "screen_state": {
                "cards": [
                    {"id": "Perfected Strike", "name": "Perfected Strike", "type": "ATTACK", "rarity": "COMMON"},
                    {"id": "Feed", "name": "Feed", "type": "ATTACK", "rarity": "RARE"},
                ]
            },
        }

        self.assertIsNone(
            sts_ai_player.openai_override_reason(
                state,
                model_command="CHOOSE 0",
                fallback_command="CHOOSE 1",
                decision={"confidence": 0.1},
            )
        )

    def test_openai_legal_actions_do_not_expose_rule_fallback(self):
        state = {
            "screen_type": "NONE",
            "combat_state": {
                "hand": [
                    skill("Defend", "Defend_R"),
                    attack("Strike", "Strike_R"),
                ],
                "player": {"energy": 2},
                "monsters": [{"name": "Jaw Worm", "current_hp": 40}],
            },
        }

        actions = sts_ai_player.build_legal_actions(
            state,
            {"play", "end"},
            "PLAY 1",
            include_fallback_action=False,
        )
        payload = sts_ai_player.build_decision_payload(state, actions)

        self.assertNotIn("fallback", {action.action_id for action in actions})
        self.assertNotIn("fallback_action", payload)
        self.assertNotIn("narration", payload)

    def test_narration_prompt_only_when_enabled(self):
        state = {
            "screen_type": "NONE",
            "combat_state": {
                "hand": [attack("Strike", "Strike_R")],
                "player": {"energy": 1},
                "monsters": [{"name": "Jaw Worm", "current_hp": 40}],
            },
        }
        actions = sts_ai_player.build_legal_actions(state, {"play", "end"}, "PLAY 1 0", include_fallback_action=False)

        without_narration = sts_ai_player.build_decision_payload(state, actions)
        with_narration = sts_ai_player.build_decision_payload(state, actions, include_narration=True)
        codex_without = sts_ai_player.build_codex_prompt(
            state,
            [{"action_id": action.action_id, "command": action.command, "description": action.description} for action in actions],
            "PLAY 1 0",
        )
        codex_with = sts_ai_player.build_codex_prompt(
            state,
            [{"action_id": action.action_id, "command": action.command, "description": action.description} for action in actions],
            "PLAY 1 0",
            include_narration=True,
        )

        self.assertNotIn("narration", without_narration)
        self.assertIn("narration", with_narration)
        self.assertNotIn("narration_text", codex_without)
        self.assertIn("narration_text", codex_with)

    def test_shop_room_with_insufficient_gold_only_exposes_proceed(self):
        sts_ai_player.SHOP_VISITED_KEYS.clear()
        state = {
            "seed": 123,
            "act": 1,
            "floor": 11,
            "screen_type": "SHOP_ROOM",
            "choice_list": ["shop"],
            "screen_state": {},
            "gold": 2,
        }

        actions = sts_ai_player.build_legal_actions(
            state,
            {"choose", "proceed"},
            "PROCEED",
            include_fallback_action=False,
        )

        self.assertEqual({action.command for action in actions}, {"PROCEED"})

    def test_shop_room_does_not_reenter_after_shop_screen_was_seen(self):
        sts_ai_player.SHOP_VISITED_KEYS.clear()
        shop_state = {
            "seed": 123,
            "act": 1,
            "floor": 11,
            "screen_type": "SHOP_SCREEN",
            "screen_state": {"cards": [], "relics": [], "potions": [], "purge_available": False},
            "gold": 200,
        }
        room_state = {
            "seed": 123,
            "act": 1,
            "floor": 11,
            "screen_type": "SHOP_ROOM",
            "choice_list": ["shop"],
            "screen_state": {},
            "gold": 200,
        }

        sts_ai_player.build_legal_actions(shop_state, {"leave"}, "LEAVE", include_fallback_action=False)
        actions = sts_ai_player.build_legal_actions(
            room_state,
            {"choose", "proceed"},
            "PROCEED",
            include_fallback_action=False,
        )

        self.assertEqual({action.command for action in actions}, {"PROCEED"})

    def test_game_over_pause_requests_one_shot_openai_narration(self):
        sts_ai_player.PAUSE_NARRATION_KEYS.clear()
        previous_key = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = "test-key"
        calls: list[dict] = []
        original = sts_ai_player.run_openai_narration_api

        def fake_run_openai_narration_api(payload, option_values, api_key):
            calls.append(payload)
            return {
                "rationale": "terminal narration",
                "narration_mode": "say",
                "narration_text": "ここで倒れましたが、最後まで攻め切りました。",
                "narration_emotion": "sad",
                "confidence": 0.9,
            }

        raw = {
            "in_game": True,
            "available_commands": ["proceed", "wait", "state"],
            "_sts_ai_log_index": 138,
            "_sts_ai_recent_narrations": ["次のターンへつなげます。"],
            "game_state": {
                "seed": 123,
                "act": 1,
                "floor": 16,
                "screen_type": "GAME_OVER",
                "screen_name": "DEATH",
                "current_hp": 0,
                "max_hp": 80,
            },
        }

        try:
            sts_ai_player.run_openai_narration_api = fake_run_openai_narration_api
            command = sts_ai_player.choose_command(
                raw,
                options(use_openai_api=True, narration_ui=True),
            )
            repeated_raw = {
                **raw,
                "_sts_ai_narration_text": "",
                "_sts_ai_narration_mode": "",
                "_sts_ai_narration_emotion": "",
            }
            repeated_command = sts_ai_player.choose_command(
                repeated_raw,
                options(use_openai_api=True, narration_ui=True),
            )
        finally:
            sts_ai_player.run_openai_narration_api = original
            if previous_key is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = previous_key

        self.assertEqual(command, "WAIT 300")
        self.assertEqual(raw["_sts_ai_narration_event"], "game_over")
        self.assertEqual(raw["_sts_ai_narration_mode"], "say")
        self.assertEqual(raw["_sts_ai_narration_text"], "ここで倒れましたが、最後まで攻め切りました。")
        self.assertEqual(raw["_sts_ai_narration_emotion"], "sad")
        self.assertEqual(calls[0]["event"]["type"], "game_over")
        self.assertEqual(calls[0]["narration"]["recent_examples"], ["次のターンへつなげます。"])
        self.assertEqual(repeated_command, "WAIT 300")
        self.assertEqual(len(calls), 1)
        self.assertEqual(repeated_raw["_sts_ai_narration_mode"], "silent")

    def test_rest_prefers_heal_before_forced_elite_route(self):
        state = {
            "current_hp": 58,
            "max_hp": 80,
            "map": [
                {"symbol": "R", "x": 1, "y": 5, "children": [{"x": 2, "y": 6}]},
                {"symbol": "?", "x": 2, "y": 6, "children": [{"x": 3, "y": 7}]},
                {"symbol": "E", "x": 3, "y": 7, "children": []},
            ],
        }
        sts_ai_player.LAST_CHOSEN_MAP_NODE = {"symbol": "R", "x": 1, "y": 5, "children": [{"x": 2, "y": 6}]}

        self.assertGreater(sts_ai_player.rest_option_score("rest", state), sts_ai_player.rest_option_score("smith", state))

    def test_seed_long_to_string_accepts_signed_logged_seed(self):
        self.assertEqual(sts_ai_player.seed_long_to_string(-1), "5G24A25UXKXFF")


if __name__ == "__main__":
    unittest.main()
