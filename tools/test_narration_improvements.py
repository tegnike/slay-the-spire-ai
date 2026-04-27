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
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sts_ai_player
from _sts_ai_player import runtime
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


def combat_raw_with_incoming() -> dict[str, Any]:
    raw = combat_raw()
    combat = raw["game_state"]["combat_state"]
    combat["hand"] = [attack("Strike", "Strike_R")]
    combat["player"]["block"] = 0
    combat["monsters"][0]["current_hp"] = 30
    combat["monsters"][0]["move_adjusted_damage"] = 12
    return raw


def combat_raw_with_unknown_adjusted_incoming() -> dict[str, Any]:
    raw = combat_raw()
    monster = raw["game_state"]["combat_state"]["monsters"][0]
    monster["current_hp"] = 42
    monster["intent"] = "DEBUG"
    monster["move_base_damage"] = 11
    monster["move_adjusted_damage"] = -1
    raw["game_state"]["combat_state"]["player"]["block"] = 0
    return raw


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


def cue_sequence_to_dicts(cues: list[Any]) -> list[dict[str, Any]]:
    return [cue for cue in (cue_to_dict(cue) for cue in cues) if cue is not None]


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

    def test_runtime_force_queue_keeps_audio_narration_from_being_dropped(self):
        cue = narration.NarrationCue(
            "ここは音声で確認します。",
            queue_policy="dropIfBusy",
            max_queue_ms=900,
            subtitle_only=False,
        )

        with patch.dict("os.environ", {"STS_AI_NARRATION_FORCE_QUEUE": "1"}, clear=False):
            subtitle_only, queue_policy, max_queue_ms = runtime.narration_delivery_options(cue)

        self.assertFalse(subtitle_only)
        self.assertEqual(queue_policy, "enqueue")
        self.assertGreaterEqual(max_queue_ms or 0, 15000)

    def test_runtime_subtitle_only_mode_still_forces_queue_without_audio(self):
        cue = narration.NarrationCue(
            "字幕だけで流します。",
            queue_policy="dropIfBusy",
            max_queue_ms=900,
            subtitle_only=False,
        )

        with patch.dict("os.environ", {"STS_AI_NARRATION_SUBTITLE_ONLY": "1"}, clear=False):
            subtitle_only, queue_policy, max_queue_ms = runtime.narration_delivery_options(cue)

        self.assertTrue(subtitle_only)
        self.assertEqual(queue_policy, "enqueue")
        self.assertGreaterEqual(max_queue_ms or 0, 6000)

    def test_runtime_force_audio_overrides_low_value_subtitle_only_cues(self):
        cue = narration.NarrationCue(
            "報酬回収も音声で確認します。",
            queue_policy="dropIfBusy",
            max_queue_ms=750,
            subtitle_only=True,
        )

        with patch.dict(
            "os.environ",
            {"STS_AI_NARRATION_FORCE_AUDIO": "1", "STS_AI_NARRATION_FORCE_QUEUE": "1"},
            clear=False,
        ):
            subtitle_only, queue_policy, max_queue_ms = runtime.narration_delivery_options(cue)

        self.assertFalse(subtitle_only)
        self.assertEqual(queue_policy, "enqueue")
        self.assertGreaterEqual(max_queue_ms or 0, 15000)

    def test_director_emits_json_serializable_metadata_friendly_cue(self):
        director_cls = require_director(self)
        cue = next_cue(director_cls(), combat_raw(), "PLAY 1 0")

        self.assertIsNotNone(cue)
        assert cue is not None
        self.assertIsInstance(cue.get("text"), str)
        self.assertIn(cue.get("emotion"), narration.OFFICIAL_EMOTIONS)
        self.assertIsInstance(cue.get("thought"), str)
        self.assertIsInstance(cue.get("reason"), str)
        self.assertIsInstance(cue.get("importance"), int)
        self.assertIn(cue.get("pace"), narration.SUPPORTED_PACES)
        self.assertIn(cue.get("intensity"), narration.SUPPORTED_INTENSITIES)
        self.assertIn(cue.get("queue_policy"), narration.SUPPORTED_QUEUE_POLICIES)
        self.assertIsInstance(cue.get("priority"), int)
        json.dumps(cue, ensure_ascii=False)
        self.assertNotIn("game_state", cue)
        self.assertNotIn("combat_state", cue)

    def test_spoken_text_rewrites_english_names_and_keeps_polite_tone(self):
        text = narration.sanitize_spoken_text("Pommel StrikeでJaw Wormを倒し切れ！")
        card_text = narration.sanitize_spoken_text("CarnageとMind Blastを見ます。")

        self.assertNotRegex(text, r"[A-Za-z]")
        self.assertIn("ポンメルストライク", text)
        self.assertIn("ジャウワーム", text)
        self.assertIn("倒し切りましょう", text)
        self.assertEqual(card_text, "カーネイジとマインドブラストを見ます。")

    def test_spoken_text_removes_leading_punctuation_after_english_cleanup(self):
        text = narration.sanitize_spoken_text("Dropkick、ここで押し込みます！")

        self.assertNotRegex(text, r"^[、。,.]")
        self.assertIn("ドロップキック", text)

    def test_spoken_text_removes_enemy_size_parentheses(self):
        text = narration.sanitize_spoken_text("Spike Slime (M)は残り25です。")

        self.assertNotIn("()", text)
        self.assertNotIn("(M)", text)
        self.assertEqual(text, "スパイクスライムは残り体力25です。")

    def test_spoken_text_falls_back_when_enemy_name_is_removed(self):
        text = narration.sanitize_spoken_text("()は残り45です。")
        unknown_text = narration.sanitize_spoken_text("Unknown Bossは残り12です。")
        mixed_script_text = narration.sanitize_spoken_text("ここは不要札を一枚 हटしていきます。")

        self.assertEqual(text, "敵は残り体力45です。")
        self.assertEqual(unknown_text, "敵は残り体力12です。")
        self.assertEqual(mixed_script_text, "ここは不要札を一枚削除していきます。")

    def test_director_sanitizes_model_text_before_speaking(self):
        director_cls = require_director(self)
        cue = cue_to_dict(director_cls().choose(combat_raw(), "PLAY 1 0", "StrikeでJaw Wormを倒し切れ！"))

        self.assertIsNotNone(cue)
        assert cue is not None
        self.assertNotRegex(cue["text"], r"[A-Za-z]")
        self.assertIn("ストライク", cue["text"])
        self.assertIn("ジャウワーム", cue["text"])
        self.assertRegex(cue["text"], r"(ます|です|ましょう|！|。)$")

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

    def test_director_blocks_repeated_opening_phrase_from_model_text(self):
        director_cls = require_director(self)
        director = director_cls()
        director.record(
            narration.NarrationCue("よし、まずは一体ずつ削っていきます！", importance=3),
            "COMBAT:PLAY",
        )

        cue = cue_to_dict(director.choose(combat_raw(), "PLAY 1 0", "よし、まず一体を倒し切ります！"))

        self.assertIsNotNone(cue)
        assert cue is not None
        self.assertFalse(cue["text"].startswith("よし、"), cue["text"])

    def test_director_varies_repeated_model_battle_calls(self):
        director_cls = require_director(self)
        director = director_cls()
        proposals = [
            "よし、まずは一体ずつ削っていきます！",
            "よし、まず一体を倒し切ります！",
            "よし、ここで取り切ります！",
        ]

        lines = [cue_to_dict(director.choose(combat_raw(), "PLAY 1 0", text))["text"] for text in proposals]

        self.assertNotEqual(lines[0], "よし、まずは一体ずつ削っていきます！")
        self.assertIn("ジャウワーム", lines[0])
        self.assertFalse(lines[1].startswith("よし、"), lines)
        self.assertFalse(lines[2].startswith("よし、"), lines)
        self.assertNotIn("倒し切", lines[2])
        self.assertNotIn("取り切", lines[2])

    def test_director_prefers_concrete_commentary_over_bland_model_text(self):
        director_cls = require_director(self)
        cue = cue_to_dict(director_cls().choose(combat_raw_with_incoming(), "PLAY 1 0", "よし、まずは一発入れていきます！"))

        self.assertIsNotNone(cue)
        assert cue is not None
        self.assertNotEqual(cue["text"], "よし、まずは一発入れていきます！")
        self.assertRegex(cue["text"], r"(12|残り|被弾|次)")

    def test_director_prefers_named_card_over_generic_model_choice_text(self):
        director_cls = require_director(self)
        raw = screen_raw("CARD_REWARD")
        raw["game_state"]["screen_state"] = {
            "cards": [
                {"id": "Twin Strike", "name": "Twin Strike", "type": "ATTACK", "cost": 1},
                {"id": "Thunderclap", "name": "Thunderclap", "type": "ATTACK", "cost": 1},
            ]
        }

        cue = cue_to_dict(director_cls().choose(raw, "CHOOSE 0", "カードを取ります。"))

        self.assertIsNotNone(cue)
        assert cue is not None
        self.assertIn("ツインストライク", cue["text"])
        self.assertNotEqual(cue["text"], "カードを取ります。")

    def test_director_asks_viewers_on_named_card_reward(self):
        director_cls = require_director(self)
        raw = screen_raw("CARD_REWARD")
        raw["game_state"]["screen_state"] = {
            "cards": [
                {"id": "Disarm", "name": "Disarm", "type": "SKILL", "cost": 1, "exhausts": True},
                {"id": "Bloodletting", "name": "Bloodletting", "type": "SKILL", "cost": 0},
            ]
        }

        cue = cue_to_dict(director_cls().choose(raw, "CHOOSE 0", "カードを取ります。"))

        self.assertIsNotNone(cue)
        assert cue is not None
        self.assertIn("みなさん", cue["text"])
        self.assertIn("武装解除", cue["text"])
        self.assertRegex(cue["text"], r"(筋力|攻撃|軽く|守)")

    def test_director_lists_card_reward_candidates_and_selected_reason(self):
        director_cls = require_director(self)
        raw = screen_raw("CARD_REWARD")
        raw["game_state"]["screen_state"] = {
            "cards": [
                {"id": "Sword Boomerang", "name": "Sword Boomerang", "type": "ATTACK", "cost": 1},
                {"id": "Perfected Strike", "name": "Perfected Strike", "type": "ATTACK", "cost": 2},
                {"id": "Second Wind", "name": "Second Wind", "type": "SKILL", "cost": 1, "exhausts": True},
            ]
        }

        cue = cue_to_dict(director_cls().choose(raw, "CHOOSE 1", "カードを取ります。"))

        self.assertIsNotNone(cue)
        assert cue is not None
        self.assertIn("ソードブーメラン", cue["text"])
        self.assertIn("パーフェクトストライク", cue["text"])
        self.assertIn("セカンドウィンド", cue["text"])
        self.assertRegex(cue["text"], r"(ストライク|打点|序盤火力)")
        self.assertNotRegex(cue["text"], r"[A-Za-z]")

    def test_director_can_stage_card_reward_deliberation_before_choice(self):
        director_cls = require_director(self)
        raw = screen_raw("CARD_REWARD")
        raw["game_state"]["screen_state"] = {
            "cards": [
                {"id": "Anger", "name": "Anger", "type": "ATTACK", "cost": 0},
                {"id": "Ghostly Armor", "name": "Ghostly Armor", "type": "SKILL", "cost": 1, "ethereal": True},
                {"id": "Clothesline", "name": "Clothesline", "type": "ATTACK", "cost": 2},
            ]
        }

        cues = cue_sequence_to_dicts(director_cls().choose_sequence(raw, "CHOOSE 2", "カードを取ります。"))

        self.assertGreaterEqual(len(cues), 2)
        self.assertRegex(cues[0]["text"], r"(悩|候補|見比べ)")
        joined = "\n".join(cue["text"] for cue in cues)
        self.assertIn("怒り", joined)
        self.assertIn("ゴーストリーアーマー", joined)
        self.assertIn("クローズライン", joined)
        self.assertRegex(cues[-1]["text"], r"(脱力|攻撃|削)")

    def test_director_uses_specific_names_for_uncommon_ironclad_reward(self):
        director_cls = require_director(self)
        raw = screen_raw("CARD_REWARD")
        raw["game_state"]["screen_state"] = {
            "cards": [
                {"id": "Feel No Pain", "name": "Feel No Pain", "type": "POWER", "cost": 1},
                {"id": "Dual Wield", "name": "Dual Wield", "type": "SKILL", "cost": 1},
                {"id": "Heavy Blade", "name": "Heavy Blade", "type": "ATTACK", "cost": 2},
            ]
        }

        cues = cue_sequence_to_dicts(director_cls().choose_sequence(raw, "CHOOSE 2", "カードを取ります。"))
        joined = "\n".join(cue["text"] for cue in cues)

        self.assertGreaterEqual(len(cues), 2)
        self.assertIn("無痛", joined)
        self.assertIn("二刀流", joined)
        self.assertIn("ヘビーブレード", joined)
        self.assertNotIn("カード、カード", joined)
        self.assertNotRegex(joined, r"[A-Za-z]")

    def test_director_records_staged_cues_in_spoken_order(self):
        director_cls = require_director(self)
        director = director_cls()
        raw = screen_raw("CARD_REWARD")
        raw["game_state"]["screen_state"] = {
            "cards": [
                {"id": "Headbutt", "name": "Headbutt", "type": "ATTACK", "cost": 1},
                {"id": "Warcry", "name": "Warcry", "type": "SKILL", "cost": 0, "exhausts": True},
                {"id": "Armaments", "name": "Armaments", "type": "SKILL", "cost": 1},
            ]
        }

        cues = cue_sequence_to_dicts(director.choose_sequence(raw, "CHOOSE 0", "カードを取ります。"))
        recent = director.recent_texts()

        self.assertGreaterEqual(len(cues), 2)
        self.assertEqual(recent[-2], cues[0]["text"])
        self.assertEqual(recent[-1], cues[-1]["text"])

    def test_director_rejects_model_line_that_denies_incoming_damage(self):
        director_cls = require_director(self)

        cue = cue_to_dict(
            director_cls().choose(
                combat_raw_with_unknown_adjusted_incoming(),
                "PLAY 1 0",
                "今は被弾がありません。ストライクで先に形を作ります。",
            )
        )

        self.assertIsNotNone(cue)
        assert cue is not None
        self.assertNotIn("被弾がありません", cue["text"])
        self.assertIn("ジャウワーム", cue["text"])

    def test_director_rejects_victory_model_line_that_claims_no_damage(self):
        director_cls = require_director(self)
        raw = {
            "game_state": {
                "screen_type": "COMBAT_REWARD",
                "floor": 1,
                "current_hp": 76,
                "max_hp": 88,
                "relics": [{"name": "Burning Blood", "id": "Burning Blood"}],
            },
            "_sts_ai_narration_event": "combat_victory",
            "_sts_ai_narration_thought": "序盤の戦闘を無傷で抜け、次の強化判断へ進めます。",
            "_sts_ai_victory_context": {
                "floor": 1,
                "hp_before_reward": 70,
                "hp_after_reward": 76,
                "max_hp": 88,
                "enemies": [{"name": "Jaw Worm"}],
            },
        }

        cue = cue_to_dict(director_cls().choose(raw, "CHOOSE 1", "やりました、体力を守って勝てました。"))

        self.assertIsNotNone(cue)
        assert cue is not None
        self.assertIn("被弾", cue["text"])
        self.assertIn("バーニングブラッド", cue["text"])
        self.assertNotIn("無傷", cue["text"] + (cue["thought"] or ""))
        self.assertNotIn("体力を守って", cue["text"])

    def test_max_floor_pause_names_event_and_choices_before_generic_model_text(self):
        director_cls = require_director(self)
        raw = {
            "game_state": {
                "screen_type": "EVENT",
                "floor": 2,
                "choice_list": ["take", "leave"],
                "screen_state": {
                    "event_name": "Golden Idol",
                    "options": [
                        {"label": "Take", "text": "[Take] Obtain Golden Idol. Trigger a trap."},
                        {"label": "Leave", "text": "[Leave]"},
                    ],
                },
            },
            "_sts_ai_narration_event": "max_floor",
            "_sts_ai_narration_mode": "say",
        }

        cue = cue_to_dict(director_cls().choose(raw, "WAIT 300", "第一区切りです、ここからは少し様子を見たい場面ですね。"))

        self.assertIsNotNone(cue)
        assert cue is not None
        self.assertIn("金の偶像", cue["text"])
        self.assertIn("取る", cue["text"])
        self.assertIn("離れる", cue["text"])

    def test_director_can_stage_event_choice_with_named_options(self):
        director_cls = require_director(self)
        raw = screen_raw("EVENT")
        raw["game_state"]["choice_list"] = [
            "Take and Give: Receive Iron Wave and Store a Card",
            "Ignore",
        ]

        cues = cue_sequence_to_dicts(director_cls().choose_sequence(raw, "CHOOSE 1", "この選択肢を選びます。"))

        self.assertGreaterEqual(len(cues), 2)
        joined = "\n".join(cue["text"] for cue in cues)
        self.assertIn("アイアンウェーブ", joined)
        self.assertIn("無視", joined)
        self.assertNotIn("この選択肢", cues[-1]["text"])

    def test_combat_damage_commentary_accounts_for_vulnerable(self):
        director_cls = require_director(self)
        raw = combat_raw()
        raw["game_state"]["combat_state"]["monsters"][0]["current_hp"] = 18
        raw["game_state"]["combat_state"]["monsters"][0]["powers"] = [
            {"id": "Vulnerable", "name": "Vulnerable", "amount": 2}
        ]

        cue = cue_to_dict(director_cls().choose(raw, "PLAY 1 0", None))

        self.assertIsNotNone(cue)
        assert cue is not None
        self.assertIn("9", cue["text"])

    def test_potion_narration_names_potion_and_discards_conflicting_thought(self):
        director_cls = require_director(self)
        raw = combat_raw_with_incoming()
        raw["game_state"]["potions"] = [
            {"id": "Block Potion", "name": "Block Potion", "can_use": True, "can_discard": True}
        ]
        raw["_sts_ai_narration_thought"] = "ポーションは温存して次に残します。"

        cue = cue_to_dict(director_cls().choose(raw, "POTION Use 0", "相手は合計12点です。"))

        self.assertIsNotNone(cue)
        assert cue is not None
        self.assertIn("ブロックポーション", cue["text"])
        self.assertNotIn("温存", cue["thought"] or "")

    def test_director_rotates_commentary_angles_for_combat(self):
        director_cls = require_director(self)
        director = director_cls()
        lines = [
            cue_to_dict(director.choose(combat_raw_with_incoming(), "PLAY 1 0", "よし、まずは一発入れていきます！"))[
                "text"
            ]
            for _ in range(3)
        ]

        self.assertGreaterEqual(len(set(lines)), 3)
        self.assertTrue(any("12" in line or "被弾" in line for line in lines), lines)
        self.assertTrue(any("次" in line for line in lines), lines)

    def test_director_rotates_choice_cues_for_consultation_reason_and_deck_policy(self):
        director_cls = require_director(self)
        director = director_cls()
        cues = [cue_to_dict(director.choose(screen_raw("CARD_REWARD"), "CHOOSE 0", None)) for _ in range(4)]

        self.assertTrue(all(cue is not None for cue in cues), cues)
        lines = [cue["text"] for cue in cues if cue is not None]
        thoughts = [cue["thought"] for cue in cues if cue is not None]
        joined = "\n".join(lines + thoughts)

        self.assertTrue(any("悩みどころ" in line for line in lines), lines)
        self.assertTrue(any("次の数戦" in line or "次につながる" in line for line in lines), lines)
        self.assertTrue(any("デッキ" in line or "役割" in line for line in lines), lines)
        self.assertTrue(all(thought for thought in thoughts), thoughts)
        self.assertRegex(joined, r"(体力|次の部屋|価値)")
        self.assertNotRegex(joined, r"[A-Za-z]")

    def test_director_speaks_for_forced_game_over_wait_event(self):
        director_cls = require_director(self)
        raw = {
            "game_state": {
                "act": 1,
                "floor": 16,
                "screen_type": "GAME_OVER",
                "screen_name": "DEATH",
                "current_hp": 0,
                "max_hp": 80,
            },
            "_sts_ai_narration_event": "game_over",
            "_sts_ai_narration_mode": "say",
            "_sts_ai_narration_text": "ここで倒れましたが、最後まで攻め切りました。",
            "_sts_ai_narration_emotion": "sad",
            "_sts_ai_narration_thought": "ゲームオーバーなので、停止前に結末を記録します。",
        }

        cue = cue_to_dict(director_cls().choose(raw, "WAIT 300", raw["_sts_ai_narration_text"]))

        self.assertIsNotNone(cue)
        assert cue is not None
        self.assertEqual(cue["text"], "ここで倒れましたが、最後まで攻め切りました。")
        self.assertEqual(cue["emotion"], "sad")
        self.assertEqual(cue["thought"], "ゲームオーバーなので、停止前に結末を記録します。")
        self.assertEqual(cue["reason"], "game_over")
        self.assertEqual(cue["queue_policy"], "replaceIfHigherPriority")

    def test_director_honors_silent_for_forced_pause_event(self):
        director_cls = require_director(self)
        director = director_cls()
        raw = {
            "game_state": {"screen_type": "GAME_OVER", "screen_name": "DEATH", "floor": 16},
            "_sts_ai_narration_event": "game_over",
            "_sts_ai_narration_mode": "silent",
        }

        cue = cue_to_dict(director.choose(raw, "WAIT 300", None))

        self.assertIsNone(cue)
        self.assertEqual(director.last_suppression_reason(), "model_silent")

    def test_director_speaks_combat_victory_before_reward_work(self):
        director_cls = require_director(self)
        raw = {
            "game_state": {
                "act": 1,
                "floor": 5,
                "screen_type": "COMBAT_REWARD",
                "current_hp": 26,
                "max_hp": 80,
            },
            "_sts_ai_narration_event": "combat_victory",
            "_sts_ai_narration_mode": "say",
            "_sts_ai_narration_text": "やりました！きっちり勝ち切りました。",
            "_sts_ai_narration_emotion": "happy",
            "_sts_ai_narration_thought": "戦闘勝利に入ったので、報酬処理の前に反応します。",
            "_sts_ai_victory_context": {
                "floor": 5,
                "hp_after_reward": 26,
                "max_hp": 80,
                "enemies": [{"name": "Fungi Beast"}],
            },
        }

        cue = cue_to_dict(director_cls().choose(raw, "CHOOSE 0", raw["_sts_ai_narration_text"]))

        self.assertIsNotNone(cue)
        assert cue is not None
        self.assertEqual(cue["text"], "やりました！きっちり勝ち切りました。")
        self.assertEqual(cue["emotion"], "happy")
        self.assertEqual(cue["thought"], "戦闘勝利に入ったので、報酬処理の前に反応します。")
        self.assertEqual(cue["reason"], "combat_victory")
        self.assertEqual(cue["queue_policy"], "replaceIfHigherPriority")

    def test_director_has_local_victory_fallback_without_english(self):
        director_cls = require_director(self)
        raw = {
            "game_state": {"screen_type": "COMBAT_REWARD", "floor": 5, "current_hp": 26, "max_hp": 80},
            "_sts_ai_narration_event": "combat_victory",
            "_sts_ai_victory_context": {
                "floor": 5,
                "hp_after_reward": 26,
                "max_hp": 80,
                "enemies": [{"name": "Fungi Beast"}],
            },
        }

        cue = cue_to_dict(director_cls().choose(raw, "CHOOSE 0", None))

        self.assertIsNotNone(cue)
        assert cue is not None
        self.assertNotRegex(cue["text"], r"[A-Za-z]")
        self.assertRegex(cue["text"], r"(やりました|勝利|突破|倒し切)")
        self.assertIn("戦闘勝利", cue["thought"])

    def test_director_blocks_recent_low_importance_motif(self):
        director_cls = require_director(self)
        director = director_cls()
        director.record(
            narration.NarrationCue("相手の体力を削っておきます。", importance=2),
            "COMBAT:PLAY",
        )
        raw = combat_raw()
        raw["game_state"]["combat_state"]["monsters"][0]["current_hp"] = 30

        cue = cue_to_dict(director.choose(raw, "PLAY 1 0", "ここで削ります！"))

        self.assertIsNotNone(cue)
        assert cue is not None
        self.assertNotIn("削", cue["text"])

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
            "Strikeでいけーー！",
            emotion="happy",
            pace="fast",
            intensity="high",
            priority=9,
            queue_policy="replaceIfHigherPriority",
            max_queue_ms=900,
            thought="攻撃で倒せるので、ここは前に出ます。",
            metadata={"command": "PLAY 1 0"},
        )

        self.assertEqual(status, "sent")
        self.assertEqual(sent[0]["type"], "narration:say")
        self.assertNotRegex(sent[0]["text"], r"[A-Za-z]")
        self.assertIn("ストライク", sent[0]["text"])
        self.assertEqual(sent[0]["thought"], "攻撃で倒せるので、ここは前に出ます。")
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
