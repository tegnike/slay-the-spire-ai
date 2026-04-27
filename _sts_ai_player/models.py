"""Shared data models for the AI process."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Options:
    auto_start: bool
    character: str
    ascension: int
    seed: str | None
    stop_on_game_over: bool
    max_floor: int | None
    use_openai_api: bool
    openai_model: str
    openai_api_base: str
    openai_timeout: float
    use_codex: bool
    codex_model: str
    codex_command: str
    codex_timeout: float
    narration_ui: bool
    narration_url: str
    narration_speaker: str
    narration_wait: bool
    narration_timeout: float


@dataclass(frozen=True)
class LegalAction:
    action_id: str
    command: str
    description: str


class OpenAIDecisionError(RuntimeError):
    pass
