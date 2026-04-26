#!/usr/bin/env python3
"""Focused tests for summarize_run diagnostics."""

from __future__ import annotations

import unittest

import summarize_run


def state_payload(index: int, floor: int, screen: str, **overrides):
    game_state = {
        "act": 1,
        "floor": floor,
        "screen_type": screen,
        "room_type": "MonsterRoom",
        "room_phase": "COMPLETE",
        "current_hp": 80,
        "max_hp": 80,
        "gold": 99,
        "screen_state": {},
    }
    game_state.update(overrides)
    return {"_sts_ai_log_index": index, "game_state": game_state}


def combat_state(index: int, current_hp: int, block: int = 0, incoming: int = 18):
    return state_payload(
        index,
        6,
        "NONE",
        room_type="MonsterRoomElite",
        room_phase="COMBAT",
        current_hp=current_hp,
        combat_state={
            "turn": 4,
            "hand": [{"name": "Strike"}, {"name": "Defend"}],
            "player": {"current_hp": current_hp, "max_hp": 80, "block": block, "energy": 2},
            "monsters": [
                {
                    "name": "Lagavulin",
                    "current_hp": 22,
                    "intent": "ATTACK",
                    "move_adjusted_damage": incoming,
                    "move_hits": 1,
                }
            ],
        },
    )


class SummarizeRunTests(unittest.TestCase):
    def test_pairs_by_state_index_and_attaches_decision(self):
        states = [
            state_payload(1, 1, "MAP"),
            state_payload(2, 2, "COMBAT_REWARD"),
        ]
        actions = [{"time": 10.0, "state_index": 2, "command": "CHOOSE 1"}]
        decisions = [
            {
                "time": 9.9,
                "command": "CHOOSE 1",
                "model_command": "SKIP",
                "fallback": "CHOOSE 1",
                "override_reason": "low_heuristic_screen_score",
            }
        ]

        rows = summarize_run.build_rows(states, actions, decisions)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["state_index"], 2)
        self.assertEqual(rows[0]["decision"]["model_command"], "SKIP")

    def test_reward_loop_candidate_uses_card_identity(self):
        states = []
        actions = []
        for index in range(1, 9):
            states.append(
                state_payload(
                    index,
                    2,
                    "CARD_REWARD",
                    screen_state={"cards": [{"name": "Flex"}, {"name": "Warcry"}]},
                )
            )
            actions.append({"state_index": index, "command": "SKIP"})

        rows = summarize_run.build_rows(states, actions)
        findings = summarize_run.reward_loop_candidates(rows, threshold=4)

        self.assertEqual(len(findings), 1)
        self.assertIn("count=8", findings[0])
        self.assertIn("Flex", findings[0])

    def test_low_hp_dangerous_combat_marks_lethal(self):
        rows = summarize_run.build_rows(
            [combat_state(1, current_hp=12, block=0, incoming=18)],
            [{"state_index": 1, "command": "END"}],
        )

        findings = summarize_run.low_hp_dangerous_combat(rows, low_hp_ratio=0.35)

        self.assertEqual(len(findings), 1)
        self.assertIn("LETHAL", findings[0])
        self.assertIn("Lagavulin", findings[0])


if __name__ == "__main__":
    unittest.main()
