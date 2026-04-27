"""WebSocket client for the external narration runtime UI."""

from __future__ import annotations

import base64
from collections import deque
import hashlib
import json
import logging
import os
import socket
import ssl
import struct
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

OFFICIAL_EMOTIONS = {"neutral", "happy", "angry", "sad", "thinking"}
SUPPORTED_PACES = {"slow", "normal", "fast"}
SUPPORTED_INTENSITIES = {"low", "normal", "high"}
SUPPORTED_QUEUE_POLICIES = {"enqueue", "dropIfBusy", "replaceIfHigherPriority"}


@dataclass
class PendingUtterance:
    event: threading.Event
    status: str | None = None
    error: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class NarrationCue:
    text: str
    emotion: str = "neutral"
    reason: str = "fallback"
    importance: int = 1
    pace: str | float = "normal"
    intensity: str | float = "normal"
    priority: int = 0
    queue_policy: str = "enqueue"
    max_queue_ms: int | None = 5000
    subtitle_only: bool = False
    interrupt: bool = False


class NarrationUIClient:
    """Minimal producer client for ws://.../ws/narration.

    stdout is reserved for CommunicationMod, so all diagnostics are log-only.
    """

    def __init__(
        self,
        *,
        url: str,
        speaker: str = "nike",
        wait_for_completion: bool = True,
        timeout: float = 12.0,
        client_name: str = "slay-the-spire-ai",
    ) -> None:
        self.url = url
        self.speaker = speaker
        self.wait_for_completion = wait_for_completion
        self.timeout = timeout
        self.client_name = client_name
        self._sock: socket.socket | ssl.SSLSocket | None = None
        self._send_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[str, PendingUtterance] = {}
        self._receiver: threading.Thread | None = None
        self._closed = False
        self._retry_after = 0.0
        self._last_status_reason: str | None = None
        self.supported_emotions = set(OFFICIAL_EMOTIONS)
        self.supported_paces = set(SUPPORTED_PACES)
        self.supported_intensities = set(SUPPORTED_INTENSITIES)
        self.supported_queue_policies = set(SUPPORTED_QUEUE_POLICIES)

    @property
    def last_status_reason(self) -> str | None:
        return self._last_status_reason

    def say(
        self,
        text: str,
        *,
        emotion: str = "neutral",
        pace: str | float = "normal",
        intensity: str | float = "normal",
        priority: int = 0,
        queue_policy: str = "enqueue",
        max_queue_ms: int | None = 5000,
        subtitle_only: bool = False,
        interrupt: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        self._last_status_reason = None
        text = text.strip()
        if not text:
            return "empty"
        if emotion not in OFFICIAL_EMOTIONS:
            emotion = "neutral"
        pace = _normalize_pace(pace)
        intensity = _normalize_intensity(intensity)
        if queue_policy not in SUPPORTED_QUEUE_POLICIES:
            queue_policy = "enqueue"
        if not self._ensure_connected():
            self._last_status_reason = "connection_unavailable"
            return "disconnected"

        utterance_id = f"sts_{uuid.uuid4().hex}"
        pending = PendingUtterance(threading.Event())
        with self._pending_lock:
            self._pending[utterance_id] = pending

        message = {
            "type": "narration:say",
            "id": utterance_id,
            "text": text,
            "speaker": self.speaker,
            "emotion": emotion,
            "interrupt": interrupt,
            "pace": pace,
            "intensity": intensity,
            "priority": int(priority),
            "queuePolicy": queue_policy,
            "subtitleOnly": bool(subtitle_only),
            "metadata": metadata or {},
        }
        if max_queue_ms is not None:
            message["maxQueueMs"] = max(0, int(max_queue_ms))
        try:
            self._send_json(message)
        except OSError as error:
            logging.warning("narration send failed: %s", error)
            self._mark_disconnected()
            with self._pending_lock:
                self._pending.pop(utterance_id, None)
            self._last_status_reason = "send_failed"
            return "send_failed"

        if not self.wait_for_completion:
            return "sent"

        if not pending.event.wait(self.timeout):
            with self._pending_lock:
                self._pending.pop(utterance_id, None)
            logging.warning("narration timed out id=%s", utterance_id)
            self._last_status_reason = "timeout"
            return "timeout"
        self._last_status_reason = pending.reason
        return pending.status or "completed"

    def suppress(
        self,
        text: str,
        *,
        reason: str = "producer_suppressed",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        self._last_status_reason = reason
        text = text.strip()
        if not text:
            return "empty"
        if not self._ensure_connected():
            self._last_status_reason = "connection_unavailable"
            return "disconnected"
        message = {
            "type": "narration:suppressed",
            "id": f"sts_{uuid.uuid4().hex}",
            "text": text,
            "reason": reason,
            "metadata": metadata or {},
        }
        try:
            self._send_json(message)
        except OSError as error:
            logging.warning("narration suppress send failed: %s", error)
            self._mark_disconnected()
            self._last_status_reason = "send_failed"
            return "send_failed"
        return "suppressed"

    def close(self) -> None:
        self._closed = True
        sock = self._sock
        if sock is None:
            return
        try:
            self._send_frame(0x8, b"")
        except OSError:
            pass
        self._sock = None
        try:
            sock.close()
        except OSError:
            pass

    def _ensure_connected(self) -> bool:
        if self._sock is not None:
            return True
        if self._closed or time.time() < self._retry_after:
            return False
        try:
            self._connect()
        except OSError as error:
            logging.warning("narration connection unavailable url=%s error=%s", self.url, error)
            self._retry_after = time.time() + 5.0
            self._mark_disconnected()
            return False
        return True

    def _connect(self) -> None:
        parsed = urlparse(self.url)
        if parsed.scheme not in {"ws", "wss"}:
            raise OSError(f"unsupported WebSocket scheme: {parsed.scheme}")
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"

        raw_sock = socket.create_connection((host, port), timeout=3.0)
        sock: socket.socket | ssl.SSLSocket = raw_sock
        if parsed.scheme == "wss":
            sock = ssl.create_default_context().wrap_socket(raw_sock, server_hostname=host)
        sock.settimeout(3.0)

        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = self._read_http_response(sock)
        if " 101 " not in response.split("\r\n", 1)[0]:
            sock.close()
            raise OSError(f"websocket handshake failed: {response.splitlines()[0] if response else 'no response'}")
        accept = self._header_value(response, "sec-websocket-accept")
        expected = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")
        if accept != expected:
            sock.close()
            raise OSError("websocket handshake returned invalid accept key")

        sock.settimeout(None)
        self._sock = sock
        self._send_json({"type": "narration:hello", "role": "producer", "clientName": self.client_name})
        self._receiver = threading.Thread(target=self._receive_loop, name="narration-ui-receiver", daemon=True)
        self._receiver.start()
        logging.info("narration connected url=%s", self.url)

    def _receive_loop(self) -> None:
        while not self._closed and self._sock is not None:
            try:
                opcode, payload = self._read_frame()
            except OSError as error:
                if not self._closed:
                    logging.warning("narration receive failed: %s", error)
                self._mark_disconnected()
                return

            if opcode == 0x1:
                self._handle_message(payload.decode("utf-8", errors="replace"))
            elif opcode == 0x8:
                self._mark_disconnected()
                return
            elif opcode == 0x9:
                try:
                    self._send_frame(0xA, payload)
                except OSError:
                    self._mark_disconnected()
                    return

    def _handle_message(self, text: str) -> None:
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            logging.warning("narration returned non-json message=%s", text[-500:])
            return
        if not isinstance(message, dict):
            return
        self._record_supported_values(message)
        message_type = str(message.get("type") or "")
        utterance_id = str(message.get("id") or "")
        if not utterance_id:
            return
        if message_type not in {"narration:completed", "narration:skipped", "narration:failed"}:
            return
        with self._pending_lock:
            pending = self._pending.pop(utterance_id, None)
        if pending is None:
            return
        pending.status = message_type.removeprefix("narration:")
        if message.get("error"):
            pending.error = str(message.get("error"))
            logging.warning("narration failed id=%s error=%s", utterance_id, pending.error)
        if message.get("reason"):
            pending.reason = str(message.get("reason"))
        pending.event.set()

    def _record_supported_values(self, message: dict[str, Any]) -> None:
        self.supported_emotions = _supported_values(message.get("supportedEmotions"), self.supported_emotions)
        self.supported_paces = _supported_values(message.get("supportedPaces"), self.supported_paces)
        self.supported_intensities = _supported_values(message.get("supportedIntensities"), self.supported_intensities)
        self.supported_queue_policies = _supported_values(
            message.get("supportedQueuePolicies"),
            self.supported_queue_policies,
        )

    def _send_json(self, message: dict[str, Any]) -> None:
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send_frame(0x1, payload)

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        sock = self._sock
        if sock is None:
            raise OSError("websocket is not connected")
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < (1 << 16):
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        with self._send_lock:
            sock.sendall(bytes(header) + mask + masked)

    def _read_frame(self) -> tuple[int, bytes]:
        sock = self._sock
        if sock is None:
            raise OSError("websocket is not connected")
        first_two = self._read_exact(sock, 2)
        opcode = first_two[0] & 0x0F
        masked = bool(first_two[1] & 0x80)
        length = first_two[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._read_exact(sock, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read_exact(sock, 8))[0]
        mask = self._read_exact(sock, 4) if masked else b""
        payload = self._read_exact(sock, length) if length else b""
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return opcode, payload

    def _mark_disconnected(self) -> None:
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        with self._pending_lock:
            pending_items = list(self._pending.values())
            self._pending.clear()
        for pending in pending_items:
            pending.status = "disconnected"
            pending.reason = "connection_unavailable"
            pending.event.set()

    @staticmethod
    def _read_exact(sock: socket.socket | ssl.SSLSocket, size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            chunk = sock.recv(size - len(chunks))
            if not chunk:
                raise OSError("socket closed")
            chunks.extend(chunk)
        return bytes(chunks)

    @staticmethod
    def _read_http_response(sock: socket.socket | ssl.SSLSocket) -> str:
        chunks = bytearray()
        while b"\r\n\r\n" not in chunks:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.extend(chunk)
            if len(chunks) > 65536:
                raise OSError("websocket handshake response too large")
        return chunks.decode("iso-8859-1", errors="replace")

    @staticmethod
    def _header_value(response: str, name: str) -> str | None:
        prefix = name.lower() + ":"
        for line in response.split("\r\n")[1:]:
            if line.lower().startswith(prefix):
                return line.split(":", 1)[1].strip()
        return None


class NarrationDirector:
    """Chooses whether and how to send commentary for the current action."""

    def __init__(self, *, history_size: int = 8) -> None:
        self._recent_texts: deque[str] = deque(maxlen=history_size)
        self._recent_keys: deque[str] = deque(maxlen=history_size)
        self._skip_streak = 0
        self._last_suppression_reason: str | None = None
        self._last_suppression_text: str | None = None

    def recent_texts(self) -> list[str]:
        return list(self._recent_texts)

    def last_suppression_reason(self) -> str | None:
        return self._last_suppression_reason

    def last_suppression_text(self) -> str | None:
        return self._last_suppression_text

    def choose(self, raw: dict[str, Any], command: str, model_text: str | None = None) -> NarrationCue | None:
        self._last_suppression_reason = None
        self._last_suppression_text = None
        if not should_narrate_command(command):
            self._mark_suppressed("non_speech_command", f"{command} は実況対象外です。")
            return None

        context = _classify_context(raw, command)
        key = str(context["key"])
        importance = int(context["importance"])
        if str(raw.get("_sts_ai_narration_mode") or "").lower() == "silent" and importance <= 2:
            self._recent_keys.append(key)
            self._skip_streak += 1
            self._mark_suppressed("model_silent", "モデルが低価値な実況を抑制しました。")
            return None
        if self._should_skip(key, importance):
            self._recent_keys.append(key)
            self._skip_streak += 1
            self._mark_suppressed("repeat_or_low_value", "直近と似た低価値な実況を抑制しました。")
            return None

        candidates = build_narration_candidates(raw, command, model_text=model_text, context=context)
        for text in candidates:
            normalized = _normalize_for_repeat(text)
            if normalized and not self._was_recent(normalized):
                cue = NarrationCue(
                    text=text,
                    emotion=str(context["emotion"]),
                    reason=str(context["reason"]),
                    importance=importance,
                    **_cue_style(context),
                )
                self.record(cue, key)
                return cue

        if importance <= 1:
            self._recent_keys.append(key)
            self._skip_streak += 1
            self._mark_suppressed("repeat_or_low_value", "代替文も直近と似ていたため抑制しました。")
            return None

        fallback = build_narration_text(raw, command)
        if self._was_recent(_normalize_for_repeat(fallback)):
            fallback = _pick_first_fresh(_reaction_lines(context), self._recent_texts) or fallback
        cue = NarrationCue(
            text=fallback,
            emotion=str(context["emotion"]),
            reason="fresh_fallback",
            importance=importance,
            **_cue_style(context),
        )
        self.record(cue, key)
        return cue

    def record(self, cue: NarrationCue, key: str | None = None) -> None:
        self._recent_texts.append(cue.text)
        if key:
            self._recent_keys.append(key)
        self._skip_streak = 0

    def _should_skip(self, key: str, importance: int) -> bool:
        if importance >= 3:
            return False
        if self._skip_streak >= 1:
            return False
        if importance <= 0 and key in self._recent_keys:
            return True
        if importance == 1 and list(self._recent_keys).count(key) >= 2:
            return True
        return False

    def _was_recent(self, normalized_text: str) -> bool:
        return _was_recent_text(normalized_text, self._recent_texts)

    def _mark_suppressed(self, reason: str, text: str) -> None:
        self._last_suppression_reason = reason
        self._last_suppression_text = text


def build_narration_text(raw: dict[str, Any], command: str) -> str:
    state = raw.get("game_state") or {}
    if not isinstance(state, dict):
        return command_narration(command)

    action_description = str(raw.get("_sts_ai_action_description") or "").strip()
    screen_type = str(state.get("screen_type") or state.get("screen_name") or "").upper()
    combat = state.get("combat_state") or {}
    prefix = state_prefix(state)

    if combat and screen_type in {"", "NONE"}:
        return f"{prefix}{combat_narration(state, command)}"

    screen_text = screen_narration(state, command, action_description)
    return f"{prefix}{screen_text}"


def build_narration_candidates(
    raw: dict[str, Any],
    command: str,
    *,
    model_text: str | None = None,
    context: dict[str, Any] | None = None,
) -> list[str]:
    context = context or _classify_context(raw, command)
    candidates: list[str] = []
    cleaned_model_text = _clean_spoken_line(model_text)
    if cleaned_model_text:
        candidates.append(cleaned_model_text)
    candidates.extend(_reaction_lines(context))
    candidates.extend(_scene_lines(raw, command, context))
    fallback = build_narration_text(raw, command)
    if fallback:
        candidates.append(fallback)
    return _dedupe_ordered(candidates)


def should_narrate_command(command: str) -> bool:
    verb = command.split(" ", 1)[0].upper()
    return verb not in {"STATE", "WAIT", "KEY"}


def state_prefix(state: dict[str, Any]) -> str:
    floor = state.get("floor")
    act = state.get("act")
    hp = state.get("current_hp")
    max_hp = state.get("max_hp")
    parts = []
    if act and floor:
        parts.append(f"Act {act}、{floor}階。")
    elif floor:
        parts.append(f"{floor}階。")
    if hp is not None and max_hp is not None:
        parts.append(f"HPは{hp}/{max_hp}。")
    return "".join(parts)


def combat_narration(state: dict[str, Any], command: str) -> str:
    combat = state.get("combat_state") or {}
    player = combat.get("player") or {}
    monsters = [monster for monster in combat.get("monsters") or [] if isinstance(monster, dict)]
    incoming = _estimate_incoming_damage(monsters)
    block = int(player.get("block") or 0)
    damage_gap = max(incoming - block, 0)
    verb = command.split(" ", 1)[0].upper()

    if verb == "END":
        if damage_gap > 0:
            return f"ここでターン終了です。相手の攻撃は合計{incoming}点、ブロック後に{damage_gap}点受ける見込みです。"
        return "これ以上の有効手が少ないので、ターンを終了します。"
    if verb == "POTION":
        return potion_narration(command, state)
    if verb != "PLAY":
        return command_narration(command)

    play = _parse_play_command(command)
    if play is None:
        return command_narration(command)
    card_index, target_index = play
    hand = combat.get("hand") or []
    card = hand[card_index] if 0 <= card_index < len(hand) and isinstance(hand[card_index], dict) else {}
    card_name = str(card.get("name") or card.get("id") or f"{card_index + 1}枚目")
    if target_index is not None and 0 <= target_index < len(monsters):
        monster = monsters[target_index]
        monster_name = str(monster.get("name") or monster.get("id") or "敵")
        damage = _estimate_card_damage(card)
        hp = int(monster.get("current_hp") or 0) + int(monster.get("block") or 0)
        if damage >= hp and damage > 0:
            return f"{card_name}で{monster_name}を倒しにいきます。受けるダメージを減らせる大事な一手です。"
        if damage_gap > 0:
            return f"{card_name}で{monster_name}を攻撃します。ブロック不足は{damage_gap}点ありますが、先に敵を削ります。"
        return f"{card_name}で{monster_name}を攻撃します。今は攻める余裕があります。"

    block_gain = _estimate_card_block(card)
    if block_gain > 0:
        return f"{card_name}でブロックを積みます。相手の攻撃は合計{incoming}点なので、被弾を抑えます。"
    return f"{card_name}を使って、このターンの準備を進めます。"


def potion_narration(command: str, state: dict[str, Any]) -> str:
    parts = command.split()
    potions = state.get("potions") or []
    slot = None
    if len(parts) >= 3:
        try:
            slot = int(parts[2])
        except ValueError:
            slot = None
    potion = potions[slot] if slot is not None and 0 <= slot < len(potions) and isinstance(potions[slot], dict) else {}
    potion_name = str(potion.get("name") or potion.get("id") or "ポーション")
    return f"{potion_name}を使います。ここは消耗品で状況を安定させます。"


def screen_narration(state: dict[str, Any], command: str, action_description: str) -> str:
    screen_type = str(state.get("screen_type") or state.get("screen_name") or "").upper()
    if action_description:
        translated = _action_description_to_japanese(action_description)
        if translated:
            return translated
    if screen_type == "CARD_REWARD":
        return choice_narration(state, command, "カード報酬")
    if screen_type == "COMBAT_REWARD":
        return "戦闘報酬を回収します。次の部屋に向けてリソースを整えます。"
    if screen_type == "MAP":
        return choice_narration(state, command, "次のマス")
    if screen_type == "REST":
        return choice_narration(state, command, "休憩所")
    if screen_type == "SHOP_SCREEN":
        return choice_narration(state, command, "ショップ")
    if screen_type == "GRID":
        return choice_narration(state, command, "カード選択")
    if screen_type == "EVENT":
        return choice_narration(state, command, "イベント")
    return command_narration(command)


def choice_narration(state: dict[str, Any], command: str, label: str) -> str:
    parts = command.split()
    if parts and parts[0].upper() == "CHOOSE" and len(parts) >= 2:
        try:
            index = int(parts[1])
        except ValueError:
            index = None
        if index is not None:
            return f"{label}では、{index + 1}番目の選択肢を選びます。今のデッキとHPを見て一番期待値が高い判断です。"
    if command.upper() == "SKIP":
        return f"{label}はスキップします。今は無理に取らない判断です。"
    if command.upper() in {"PROCEED", "CONFIRM"}:
        return f"{label}の選択を確定して進みます。"
    if command.upper() in {"RETURN", "LEAVE"}:
        return f"{label}から離れます。リスクや出費を抑えます。"
    return command_narration(command)


def command_narration(command: str) -> str:
    verb = command.split(" ", 1)[0].upper()
    if verb == "START":
        return "新しいランを開始します。まずは序盤の安定を重視します。"
    if verb == "PROCEED":
        return "次の画面へ進みます。"
    if verb == "CONFIRM":
        return "選択を確定します。"
    if verb == "RETURN":
        return "前の画面に戻ります。"
    if verb == "LEAVE":
        return "この部屋を離れます。"
    if verb == "SKIP":
        return "ここはスキップします。"
    return f"{command}を実行します。"


def _classify_context(raw: dict[str, Any], command: str) -> dict[str, Any]:
    state = raw.get("game_state") or {}
    if not isinstance(state, dict):
        state = {}
    screen_type = str(state.get("screen_type") or state.get("screen_name") or "").upper()
    combat = state.get("combat_state") or {}
    if not isinstance(combat, dict):
        combat = {}
    verb = command.split(" ", 1)[0].upper()
    key = f"{screen_type or 'COMBAT'}:{verb}"
    emotion = "neutral"
    reason = "routine"
    importance = 1
    tags: set[str] = set()

    if verb == "START":
        return {
            "screen_type": screen_type,
            "verb": verb,
            "key": key,
            "emotion": "happy",
            "reason": "run_start",
            "importance": 3,
            "tags": {"start", "hype"},
        }

    if combat and screen_type in {"", "NONE"}:
        context = _classify_combat_context(state, command, verb)
        context["key"] = f"COMBAT:{context['key']}"
        return context

    if screen_type in {"CARD_REWARD", "COMBAT_REWARD", "MAP", "REST", "SHOP_SCREEN", "GRID", "EVENT"}:
        emotion = "thinking"
        importance = 2
        reason = "choice"
        tags.add("choice")
    if verb in {"PROCEED", "CONFIRM", "RETURN", "LEAVE"}:
        importance = 0 if screen_type not in {"CARD_REWARD", "MAP", "REST", "SHOP_SCREEN", "EVENT"} else 1
        reason = "transition"
    if verb == "SKIP":
        emotion = "thinking"
        importance = 2 if screen_type in {"CARD_REWARD", "SHOP_SCREEN", "GRID"} else 1
        reason = "skip"
        tags.add("skip")
    if state.get("current_hp") is not None and state.get("max_hp") is not None:
        try:
            hp = int(state.get("current_hp") or 0)
            max_hp = int(state.get("max_hp") or 0)
        except (TypeError, ValueError):
            hp = max_hp = 0
        if max_hp > 0 and hp / max_hp <= 0.25:
            emotion = "sad"
            importance = max(importance, 2)
            tags.add("low_hp")

    return {
        "screen_type": screen_type,
        "verb": verb,
        "key": key,
        "emotion": emotion,
        "reason": reason,
        "importance": importance,
        "tags": tags,
    }


def _classify_combat_context(state: dict[str, Any], command: str, verb: str) -> dict[str, Any]:
    combat = state.get("combat_state") or {}
    player = combat.get("player") or {}
    monsters = [monster for monster in combat.get("monsters") or [] if isinstance(monster, dict)]
    incoming = _estimate_incoming_damage(monsters)
    block = int(player.get("block") or 0)
    damage_gap = max(incoming - block, 0)
    emotion = "neutral"
    reason = "combat"
    importance = 2
    tags: set[str] = {"combat"}
    key = verb

    if damage_gap >= 18:
        emotion = "sad"
        importance = 3
        tags.add("danger")
    elif incoming > 0:
        emotion = "thinking"
        tags.add("incoming")

    if verb == "END":
        key = "END:DAMAGE" if damage_gap > 0 else "END:SAFE"
        if damage_gap > 0:
            reason = "taking_damage"
            emotion = "sad"
            importance = 3
            tags.add("danger")
        else:
            reason = "turn_end"
            importance = 1
        return _context("NONE", verb, key, emotion, reason, importance, tags)

    if verb == "POTION":
        tags.add("potion")
        return _context("NONE", verb, "POTION", "happy", "potion", 3, tags)

    if verb != "PLAY":
        return _context("NONE", verb, key, emotion, reason, importance, tags)

    play = _parse_play_command(command)
    if play is None:
        return _context("NONE", verb, key, emotion, reason, importance, tags)
    card_index, target_index = play
    hand = combat.get("hand") or []
    card = hand[card_index] if 0 <= card_index < len(hand) and isinstance(hand[card_index], dict) else {}
    key = f"PLAY:{str(card.get('id') or card.get('name') or card_index)}"

    if target_index is not None and 0 <= target_index < len(monsters):
        monster = monsters[target_index]
        damage = _estimate_card_damage(card)
        hp = int(monster.get("current_hp") or 0) + int(monster.get("block") or 0)
        key = f"{key}:TARGET"
        tags.add("attack")
        if damage >= hp and damage > 0:
            emotion = "happy"
            reason = "lethal"
            importance = 4
            tags.add("lethal")
        elif damage_gap >= 12:
            emotion = "angry"
            reason = "race"
            importance = 3
            tags.add("push")
        else:
            emotion = "happy"
            reason = "attack"
    else:
        block_gain = _estimate_card_block(card)
        if block_gain > 0:
            tags.add("block")
            key = f"{key}:BLOCK"
            if damage_gap > 0 and block + block_gain >= incoming:
                emotion = "happy"
                reason = "full_block"
                importance = 3
                tags.add("stabilize")
            else:
                emotion = "thinking"
                reason = "defend"
        else:
            tags.add("setup")
            emotion = "thinking"
            reason = "setup"
    return _context("NONE", verb, key, emotion, reason, importance, tags)


def _context(
    screen_type: str,
    verb: str,
    key: str,
    emotion: str,
    reason: str,
    importance: int,
    tags: set[str],
) -> dict[str, Any]:
    return {
        "screen_type": screen_type,
        "verb": verb,
        "key": key,
        "emotion": emotion,
        "reason": reason,
        "importance": importance,
        "tags": tags,
    }


def _reaction_lines(context: dict[str, Any]) -> list[str]:
    tags = set(context.get("tags") or set())
    reason = str(context.get("reason") or "")
    if "lethal" in tags:
        return ["よっしゃ、ここで取り切る！", "いけーー！倒し切れ！", "そこだ、決めにいく！"]
    if "danger" in tags:
        return ["うわ、ここは踏ん張りどころ！", "痛いターン、集中していこう。", "ここを越えればまだある！"]
    if "potion" in tags:
        return ["よし、ここで切る！", "出し惜しみなしでいこう。", "ポーション投入、勝負どころ！"]
    if "stabilize" in tags:
        return ["よっしゃ、受け切れる！", "ここは守りが光る！", "きれいに耐えにいく！"]
    if reason == "attack":
        return ["いけーー！まず削る！", "いいぞ、攻めていこう！", "ここは前のめりでいく！"]
    if "skip" in tags:
        return ["取らない勇気、あります。", "ここはスルーで締める。", "今のデッキには入れません。"]
    if "choice" in tags:
        return ["さて、ここは悩みどころ。", "この選択、大事です。", "次につながる方を選ぶ！"]
    if "start" in tags:
        return ["よっしゃ、登塔開始！", "さあ行こう、まずは一勝！", "開幕から集中していく！"]
    return ["よし、次いこう！", "テンポよく進めます。", "ここは迷わずいきます。"]


def _scene_lines(raw: dict[str, Any], command: str, context: dict[str, Any]) -> list[str]:
    state = raw.get("game_state") or {}
    if not isinstance(state, dict):
        return []
    combat = state.get("combat_state") or {}
    if isinstance(combat, dict) and combat and str(context.get("screen_type") or "").upper() in {"", "NONE"}:
        return _combat_scene_lines(state, command, context)
    screen_type = str(state.get("screen_type") or state.get("screen_name") or "").upper()
    if screen_type == "CARD_REWARD":
        return ["報酬選び、ここでデッキを締める！", "次の戦闘を見て選びます。"]
    if screen_type == "MAP":
        return ["ルート選択、勝負の分かれ目です。", "次の部屋、ここへ進む！"]
    if screen_type == "REST":
        return ["休憩所、ここは大事な判断。", "焚き火で立て直します。"]
    if screen_type == "SHOP_SCREEN":
        return ["買い物は勝ち筋づくりです。", "ここで必要なものだけ取る！"]
    if screen_type == "EVENT":
        return ["イベント判断、リスクを見ます。", "ここは展開を見て選ぶ！"]
    return []


def _combat_scene_lines(state: dict[str, Any], command: str, context: dict[str, Any]) -> list[str]:
    combat = state.get("combat_state") or {}
    monsters = [monster for monster in combat.get("monsters") or [] if isinstance(monster, dict)]
    tags = set(context.get("tags") or set())
    lines: list[str] = []
    play = _parse_play_command(command)
    if play is not None:
        card_index, target_index = play
        hand = combat.get("hand") or []
        card = hand[card_index] if 0 <= card_index < len(hand) and isinstance(hand[card_index], dict) else {}
        card_name = str(card.get("name") or card.get("id") or "")
        if card_name:
            if "lethal" in tags and target_index is not None and 0 <= target_index < len(monsters):
                monster_name = str(monsters[target_index].get("name") or "敵")
                lines.append(f"{card_name}で{monster_name}を仕留める！")
            elif "block" in tags:
                lines.append(f"{card_name}でしっかり受ける！")
            elif "attack" in tags:
                lines.append(f"{card_name}、ここで押し込む！")
            elif "setup" in tags:
                lines.append(f"{card_name}で次の形を作る。")
    if command.split(" ", 1)[0].upper() == "END":
        if "danger" in tags:
            lines.append("ターン終了、被弾は覚悟です。")
        else:
            lines.append("やることはやった、ターン終了。")
    return lines


def _cue_style(context: dict[str, Any]) -> dict[str, Any]:
    tags = set(context.get("tags") or set())
    importance = int(context.get("importance") or 0)
    reason = str(context.get("reason") or "")

    if "lethal" in tags:
        return {
            "pace": "fast",
            "intensity": "high",
            "priority": 9,
            "queue_policy": "replaceIfHigherPriority",
            "max_queue_ms": 900,
        }
    if "danger" in tags:
        return {
            "pace": "normal",
            "intensity": "high",
            "priority": 8,
            "queue_policy": "replaceIfHigherPriority",
            "max_queue_ms": 1200,
        }
    if "potion" in tags or "stabilize" in tags:
        return {
            "pace": "fast",
            "intensity": "high",
            "priority": 7,
            "queue_policy": "replaceIfHigherPriority",
            "max_queue_ms": 1200,
        }
    if reason == "attack" or "push" in tags:
        return {
            "pace": "fast",
            "intensity": "high",
            "priority": 5,
            "queue_policy": "dropIfBusy",
            "max_queue_ms": 900,
        }
    if "choice" in tags or reason in {"defend", "setup"}:
        return {
            "pace": "normal",
            "intensity": "low" if reason == "transition" else "normal",
            "priority": max(1, importance),
            "queue_policy": "dropIfBusy",
            "max_queue_ms": 1500,
        }
    if importance <= 1:
        return {
            "pace": "fast",
            "intensity": "low",
            "priority": 0,
            "queue_policy": "dropIfBusy",
            "max_queue_ms": 750,
        }
    return {
        "pace": "normal",
        "intensity": "normal",
        "priority": importance,
        "queue_policy": "enqueue",
        "max_queue_ms": 3000,
    }


def _normalize_pace(value: str | float) -> str | float:
    if isinstance(value, (int, float)):
        return min(max(float(value), 0.5), 2.0)
    text = str(value)
    return text if text in SUPPORTED_PACES else "normal"


def _normalize_intensity(value: str | float) -> str | float:
    if isinstance(value, (int, float)):
        return min(max(float(value), 0.0), 2.0)
    text = str(value)
    return text if text in SUPPORTED_INTENSITIES else "normal"


def _supported_values(value: Any, fallback: set[str]) -> set[str]:
    if not isinstance(value, list):
        return fallback
    values = {str(item) for item in value if isinstance(item, str)}
    return values or fallback


def _clean_spoken_line(value: str | None) -> str | None:
    if not value:
        return None
    text = " ".join(str(value).split()).strip()
    if not text:
        return None
    if len(text) > 60:
        text = text[:60].rstrip("、。,. ") + "。"
    return text


def _normalize_for_repeat(text: str) -> str:
    normalized = text.strip().lower()
    for mark in ("！", "!", "？", "?", "。", ".", "、", ",", " ", "　"):
        normalized = normalized.replace(mark, "")
    return normalized


def _was_too_similar(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    shorter, longer = sorted((left, right), key=len)
    return len(shorter) >= 8 and shorter in longer


def _pick_first_fresh(candidates: list[str], recent_texts: deque[str]) -> str | None:
    recent_normalized = [_normalize_for_repeat(text) for text in recent_texts]
    for candidate in candidates:
        normalized = _normalize_for_repeat(candidate)
        if normalized and not any(_was_too_similar(normalized, recent) for recent in recent_normalized):
            return candidate
    return None


def _dedupe_ordered(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = _clean_spoken_line(value)
        if not text:
            continue
        key = _normalize_for_repeat(text)
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _was_recent_text(text: str, recent_texts: deque[str]) -> bool:
    return any(_was_too_similar(text, _normalize_for_repeat(recent)) for recent in recent_texts)


def _action_description_to_japanese(description: str) -> str | None:
    cleaned = description.rstrip(".")
    replacements = {
        "Rule-based fallback action": "ルールベースの候補を選びます",
        "End the current turn": "このターンを終了します",
        "Proceed to the next screen": "次の画面へ進みます",
        "Confirm the current selection": "現在の選択を確定します",
        "Leave the shop": "ショップを離れます",
        "Skip this card reward": "このカード報酬はスキップします",
    }
    return replacements.get(cleaned)


def _parse_play_command(command: str) -> tuple[int, int | None] | None:
    parts = command.split()
    if len(parts) < 2 or parts[0].upper() != "PLAY":
        return None
    try:
        card_index = int(parts[1]) - 1
        target_index = int(parts[2]) if len(parts) >= 3 else None
    except ValueError:
        return None
    return card_index, target_index


def _estimate_incoming_damage(monsters: list[dict[str, Any]]) -> int:
    total = 0
    for monster in monsters:
        if monster.get("is_gone") or monster.get("half_dead"):
            continue
        intent = str(monster.get("intent") or "").upper()
        if "ATTACK" not in intent and intent not in {"DEBUG", "UNKNOWN"}:
            continue
        damage = int(monster.get("move_adjusted_damage") or monster.get("move_base_damage") or 0)
        hits = int(monster.get("move_hits") or 1)
        total += max(damage, 0) * max(hits, 1)
    return total


def _estimate_card_damage(card: dict[str, Any]) -> int:
    from . import engine

    return int(engine.estimate_card_damage(card))


def _estimate_card_block(card: dict[str, Any]) -> int:
    from . import engine

    return int(engine.estimate_card_block(card))
