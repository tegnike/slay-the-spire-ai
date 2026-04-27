"""WebSocket client for the external narration runtime UI."""

from __future__ import annotations

import base64
from collections import deque
import hashlib
import json
import logging
import os
import re
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
SPOKEN_NAME_REPLACEMENTS = {
    "Act": "アクト",
    "HP": "体力",
    "Ironclad": "アイアンクラッド",
    "Neow": "ネオー",
    "Neow's Lament": "ネオーの哀歌",
    "Burning Blood": "バーニングブラッド",
    "Golden Idol": "金の偶像",
    "Strike_R": "ストライク",
    "Strike_G": "ストライク",
    "Strike_B": "ストライク",
    "Strike_P": "ストライク",
    "Strike": "ストライク",
    "Defend_R": "防御",
    "Defend_G": "防御",
    "Defend_B": "防御",
    "Defend_P": "防御",
    "Defend": "防御",
    "Bash": "バッシュ",
    "Disarm": "武装解除",
    "Carnage": "カーネイジ",
    "Dropkick": "ドロップキック",
    "Thunderclap": "サンダークラップ",
    "Clash": "クラッシュ",
    "Rage": "激怒",
    "Body Slam": "ボディスラム",
    "Blood for Blood": "血には血を",
    "Bludgeon": "強打",
    "Barricade": "バリケード",
    "Brutality": "残虐性",
    "Combust": "燃焼",
    "Corruption": "堕落",
    "Dark Embrace": "ダークエンブレイス",
    "Demon Form": "悪魔化",
    "Double Tap": "ダブルタップ",
    "Dual Wield": "二刀流",
    "Entrench": "塹壕",
    "Evolve": "進化",
    "Exhume": "発掘",
    "Feel No Pain": "無痛",
    "Fiend Fire": "悪魔の炎",
    "Havoc": "荒廃",
    "Immolate": "焼却",
    "Impervious": "不動",
    "Intimidate": "威嚇",
    "Juggernaut": "ジャガーノート",
    "Limit Break": "リミットブレイク",
    "Metallicize": "金属化",
    "Offering": "供物",
    "Power Through": "やせ我慢",
    "Reaper": "死神",
    "Reckless Charge": "無謀なる突進",
    "Rupture": "破裂",
    "Seeing Red": "激昂",
    "Sentinel": "歩哨",
    "Spot Weakness": "弱点発見",
    "Pommel Strike": "ポンメルストライク",
    "Headbutt": "ヘッドバット",
    "Anger": "怒り",
    "Searing Blow": "焼身",
    "Hemokinesis": "ヘモキネシス",
    "Bloodletting": "流血",
    "Shrug It Off": "受け流し",
    "True Grit": "不屈の闘志",
    "Ghostly Armor": "ゴーストリーアーマー",
    "Armaments": "アーマメント",
    "Clothesline": "クローズライン",
    "Cleave": "なぎ払い",
    "Inflame": "発火",
    "Flex": "フレックス",
    "Warcry": "雄叫び",
    "Uppercut": "アッパーカット",
    "Whirlwind": "旋風刃",
    "Shockwave": "衝撃波",
    "Twin Strike": "ツインストライク",
    "Wild Strike": "ワイルドストライク",
    "Perfected Strike": "パーフェクトストライク",
    "Sword Boomerang": "ソードブーメラン",
    "Second Wind": "セカンドウィンド",
    "Heavy Blade": "ヘビーブレード",
    "Pummel": "ポンメル",
    "Battle Trance": "バトルトランス",
    "Mind Blast": "マインドブラスト",
    "Iron Wave": "アイアンウェーブ",
    "Take and Give": "受け取りと預け入れ",
    "Store a Card": "カードを預ける",
    "Receive": "受け取る",
    "Ignore": "無視",
    "Take": "取る",
    "Leave": "離れる",
    "Sever Soul": "セヴァーソウル",
    "Fire Breathing": "炎の吐息",
    "Flex Potion": "筋力ポーション",
    "Block Potion": "ブロックポーション",
    "Strength Potion": "筋力ポーション",
    "Attack Potion": "アタックポーション",
    "Skill Potion": "スキルポーション",
    "Power Potion": "パワーポーション",
    "Liquid Memories": "リキッドメモリーズ",
    "Fear Potion": "恐怖のポーション",
    "Slaver's Collar": "スレイバーの首輪",
    "Heart of Iron": "アイアンハート",
    "Potion Slot": "空きポーション枠",
    "Smith": "強化",
    "Rest": "休憩",
    "Purge": "削除",
    "Transform": "変化",
    "Upgrade": "強化",
    "Jaw Worm": "ジャウワーム",
    "Gremlin Nob": "グレムリンノブ",
    "Lagavulin": "ラガヴーリン",
    "Fungi Beast": "ファンガスビースト",
    "Acid Slime": "アシッドスライム",
    "Spike Slime": "スパイクスライム",
    "Looter": "ルーター",
    "Slaver": "スレイバー",
    "Hexaghost": "ヘクサゴースト",
    "The Guardian": "ガーディアン",
    "Slime Boss": "スライムボス",
    "Sentry": "セントリー",
    "Sentries": "セントリー",
    "Cultist": "カルト信者",
    "Louse": "ラウス",
}


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
    thought: str | None = None
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
        thought: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        self._last_status_reason = None
        text = text.strip()
        if not text:
            return "empty"
        text = sanitize_spoken_text(text)
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

        thought_text = _clean_thought_line(thought)
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
        if thought_text:
            message["thought"] = thought_text
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
        self._recent_openers: deque[str] = deque(maxlen=4)
        self._recent_motifs: deque[str] = deque(maxlen=6)
        self._recent_angles: deque[str] = deque(maxlen=5)
        self._skip_streak = 0
        self._last_suppression_reason: str | None = None
        self._last_suppression_text: str | None = None

    def recent_texts(self) -> list[str]:
        return list(self._recent_texts)

    def last_suppression_reason(self) -> str | None:
        return self._last_suppression_reason

    def last_suppression_text(self) -> str | None:
        return self._last_suppression_text

    def choose(
        self,
        raw: dict[str, Any],
        command: str,
        model_text: str | None = None,
        *,
        _record: bool = True,
    ) -> NarrationCue | None:
        self._last_suppression_reason = None
        self._last_suppression_text = None
        force_narration = bool(raw.get("_sts_ai_force_narration") or raw.get("_sts_ai_narration_event"))
        if not force_narration and not should_narrate_command(command):
            self._mark_suppressed("non_speech_command", f"{command} は実況対象外です。")
            return None

        context = _classify_context(raw, command)
        key = str(context["key"])
        importance = int(context["importance"])
        thought = _clean_thought_line(str(raw.get("_sts_ai_narration_thought") or "").strip() or None)
        if thought and _thought_conflicts_with_context(thought, command, context):
            thought = None
        if str(context.get("reason") or "") == "combat_victory":
            if model_text and _victory_model_text_conflicts(raw, model_text):
                model_text = None
            if thought and _victory_model_text_conflicts(raw, thought):
                thought = None
        if str(raw.get("_sts_ai_narration_mode") or "").lower() == "silent" and (force_narration or importance <= 2):
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
            if normalized and not self._was_recent(normalized) and not self._sounds_repetitive(text, context):
                cue = NarrationCue(
                    text=text,
                    emotion=str(context["emotion"]),
                    thought=thought or _thought_for_context(raw, command, context),
                    reason=str(context["reason"]),
                    importance=importance,
                    **_cue_style(context),
                )
                if _record:
                    self.record(cue, key)
                return cue

        if importance <= 1:
            self._recent_keys.append(key)
            self._skip_streak += 1
            self._mark_suppressed("repeat_or_low_value", "代替文も直近と似ていたため抑制しました。")
            return None
        if force_narration:
            self._recent_keys.append(key)
            self._skip_streak += 1
            self._mark_suppressed("repeat_or_low_value", "停止時実況が空、または直近と似ていたため抑制しました。")
            return None

        fallback = _clean_spoken_line(build_narration_text(raw, command)) or "流れを見て、次の判断に進みます。"
        if self._was_recent(_normalize_for_repeat(fallback)) or self._sounds_repetitive(fallback, context):
            fallback = (
                _pick_first_fresh(_bridge_lines(context), self._recent_texts)
                or _pick_first_fresh(_reaction_lines(context), self._recent_texts)
                or fallback
            )
        cue = NarrationCue(
            text=fallback,
            emotion=str(context["emotion"]),
            thought=thought or _thought_for_context(raw, command, context),
            reason="fresh_fallback",
            importance=importance,
            **_cue_style(context),
        )
        if _record:
            self.record(cue, key)
        return cue

    def choose_sequence(self, raw: dict[str, Any], command: str, model_text: str | None = None) -> list[NarrationCue]:
        cue = self.choose(raw, command, model_text, _record=False)
        if cue is None:
            return []
        context = _classify_context(raw, command)
        prelude_lines = _pre_action_lines(raw, command, context)
        if not prelude_lines:
            self.record(cue, str(context.get("key") or ""))
            return [cue]

        cues: list[NarrationCue] = []
        style = _staged_cue_style(context)
        for line in prelude_lines[:2]:
            text = _clean_spoken_line(line)
            if not text or text == cue.text:
                continue
            normalized = _normalize_for_repeat(text)
            if self._was_recent(normalized) or self._sounds_repetitive(text, context):
                continue
            prelude = NarrationCue(
                text=text,
                emotion="thinking",
                thought=_thought_for_context(raw, command, context),
                reason=f"{context.get('reason')}_deliberation",
                importance=max(1, min(int(context.get("importance") or 1), 3)),
                **style,
            )
            self.record(prelude, f"{context.get('key')}:prelude")
            cues.append(prelude)
        self.record(cue, str(context.get("key") or ""))
        return cues + [cue]

    def record(self, cue: NarrationCue, key: str | None = None) -> None:
        self._recent_texts.append(cue.text)
        opener = _line_opener(cue.text)
        motif = _line_motif(cue.text)
        if opener:
            self._recent_openers.append(opener)
        if motif:
            self._recent_motifs.append(motif)
        angle = _line_angle(cue.text)
        if angle:
            self._recent_angles.append(angle)
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

    def _sounds_repetitive(self, text: str, context: dict[str, Any]) -> bool:
        choice_label = sanitize_spoken_text(str(context.get("choice_label") or "")).strip()
        if choice_label and choice_label in text:
            return False
        card_name = sanitize_spoken_text(str(context.get("card_name") or "")).strip()
        if card_name and card_name in text:
            return False
        opener = _line_opener(text)
        motif = _line_motif(text)
        if opener and opener in self._recent_openers:
            return True
        if motif and motif in self._recent_motifs:
            return True
        angle = _line_angle(text)
        if angle and len(self._recent_angles) >= 2 and all(recent == angle for recent in list(self._recent_angles)[-2:]):
            return True
        return False

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
    if cleaned_model_text and _model_text_conflicts_with_context(raw, cleaned_model_text, context):
        cleaned_model_text = None
    model_is_bland = bool(cleaned_model_text and _is_bland_model_line(cleaned_model_text, context))
    if context.get("pause_event"):
        if context.get("pause_event") == "game_over":
            if cleaned_model_text:
                candidates.append(cleaned_model_text)
            candidates.extend(_failure_lines(raw, context))
        elif context.get("pause_event") == "max_floor":
            candidates.extend(_max_floor_lines(raw, context))
            if cleaned_model_text:
                candidates.append(cleaned_model_text)
        elif cleaned_model_text:
            candidates.append(cleaned_model_text)
        cleaned_candidates = [_clean_spoken_line(candidate) for candidate in candidates]
        return _dedupe_ordered([candidate for candidate in cleaned_candidates if candidate])
    if context.get("narration_event") == "combat_victory":
        factual_victory_first = _victory_has_damage_context(raw)
        if factual_victory_first:
            candidates.extend(_victory_lines(raw, context))
        if cleaned_model_text and not model_is_bland:
            candidates.append(cleaned_model_text)
        if not factual_victory_first:
            candidates.extend(_victory_lines(raw, context))
        if cleaned_model_text and model_is_bland:
            candidates.append(cleaned_model_text)
        cleaned_candidates = [_clean_spoken_line(candidate) for candidate in candidates]
        return _dedupe_ordered([candidate for candidate in cleaned_candidates if candidate])
    if cleaned_model_text and not model_is_bland:
        candidates.append(cleaned_model_text)
    candidates.extend(_commentary_lines(raw, command, context))
    if cleaned_model_text and model_is_bland:
        candidates.append(cleaned_model_text)
    candidates.extend(_reaction_lines(context))
    candidates.extend(_scene_lines(raw, command, context))
    candidates.extend(_bridge_lines(context))
    fallback = build_narration_text(raw, command)
    if fallback:
        candidates.append(fallback)
    cleaned_candidates = [_clean_spoken_line(candidate) for candidate in candidates]
    return _dedupe_ordered([candidate for candidate in cleaned_candidates if candidate])


def sanitize_spoken_text(text: str) -> str:
    text = str(text)
    text = text.replace("हट", "削除")
    for english, spoken in sorted(SPOKEN_NAME_REPLACEMENTS.items(), key=lambda item: len(item[0]), reverse=True):
        text = re.sub(re.escape(english), spoken, text, flags=re.IGNORECASE)
    text = re.sub(r"\s*[（(]\s*[A-Za-z0-9]{1,4}\s*[）)]", "", text)
    text = text.replace("/", "対").replace("_", "")
    text = re.sub(r"[A-Za-z][A-Za-z0-9' -]*", "", text)
    text = re.sub(r"[^0-9０-９ぁ-んァ-ンー・一-龥々〇零一二三四五六七八九十百千万、。！？!?.,:：対点階体力枚札番目円]+", " ", text)
    text = re.sub(r"\s*[（(]\s*[）)]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^は(?=残り(?:体力)?\d)", "敵は", text)
    text = re.sub(r"^を(?=(?:取|選|使|強化|削除|変化|スキップ))", "カードを", text)
    text = re.sub(r"^で(?=(?:攻撃|守|ブロック|倒|削|取り|押し))", "このカードで", text)
    text = re.sub(r"残り体力([0-9０-９]+)点", r"残り体力\1", text)
    text = re.sub(r"残り([0-9０-９]+)点", r"残り体力\1", text)
    text = re.sub(r"残り(?=[0-9０-９])", "残り体力", text)
    text = text.replace("体力体力", "体力")
    text = re.sub(r"で([。！？!?])?$", r"で動きます\1", text)
    text = text.replace("!", "！").replace("?", "？")
    text = re.sub(r"\s+([、。！？])", r"\1", text)
    text = re.sub(r"([ぁ-んァ-ンー・一-龥々])\s+([ぁ-んァ-ンー・一-龥々])", r"\1\2", text)
    text = re.sub(r"([ぁ-んァ-ン一-龥])\s+(\d)", r"\1\2", text)
    text = re.sub(r"(\d)\s+([ぁ-んァ-ン一-龥])", r"\1\2", text)
    text = text.replace(" 。", "。").replace(" 、", "、")
    text = _polite_spoken_text(text)
    text = re.sub(r"^[、。,. !！?？]+", "", text).strip()
    if len(text) > 90:
        text = text[:90].rstrip("、。,. ") + "。"
    return text


def _line_opener(text: str) -> str:
    normalized = text.strip()
    for opener in (
        "よし、",
        "さて、",
        "うわ、",
        "ここは",
        "まず",
        "いけます",
        "いいですね",
        "さあ",
        "痛いターン",
    ):
        if normalized.startswith(opener):
            return opener.rstrip("、")
    head = re.split(r"[、。！？]", normalized, maxsplit=1)[0]
    return head[:6]


def _line_motif(text: str) -> str:
    normalized = _normalize_for_repeat(text)
    motif_rules = (
        ("取り切", "finish"),
        ("倒し切", "finish"),
        ("仕留", "finish"),
        ("決め", "finish"),
        ("押し切", "push"),
        ("削", "chip"),
        ("攻め", "attack"),
        ("安定", "stabilize"),
        ("踏ん張", "danger"),
        ("集中", "danger"),
        ("デッキ方針", "deck_plan"),
        ("みなさん", "viewer"),
        ("どうでしょう", "viewer"),
        ("登塔", "start"),
    )
    for needle, motif in motif_rules:
        if needle in normalized:
            return motif
    return ""


def _line_angle(text: str) -> str:
    normalized = _normalize_for_repeat(text)
    if any(word in normalized for word in ("次の", "次ターン", "次に", "つなげ", "ドロー")):
        return "forecast"
    if any(word in normalized for word in ("点", "残り", "体力", "ブロック", "被弾")):
        return "analysis"
    if any(word in normalized for word in ("よし", "うわ", "いいですね", "いけます", "強い")):
        return "reaction"
    if any(word in normalized for word in ("前の", "流れ", "さっき", "ここまで")):
        return "recap"
    if any(word in normalized for word in ("みなさん", "コメント", "どうでしょう")):
        return "viewer"
    if any(word in normalized for word in ("デッキ方針", "山札", "カード選択", "報酬")):
        return "planning"
    return "play_by_play"


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
        parts.append(f"アクト{act}、{floor}階です。")
    elif floor:
        parts.append(f"{floor}階です。")
    if hp is not None and max_hp is not None:
        parts.append(f"体力は{hp}、最大{max_hp}です。")
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

    pause_event = str(raw.get("_sts_ai_narration_event") or "").strip().lower()
    requested_emotion = str(raw.get("_sts_ai_narration_emotion") or "").strip().lower()
    requested_emotion = requested_emotion if requested_emotion in OFFICIAL_EMOTIONS else ""
    if pause_event == "game_over":
        return {
            "screen_type": screen_type,
            "verb": verb,
            "key": f"PAUSE:{pause_event}",
            "emotion": requested_emotion or "sad",
            "reason": "game_over",
            "importance": 4,
            "tags": {"terminal", "pause", "game_over"},
            "pause_event": pause_event,
            "floor": state.get("floor"),
            "hp": state.get("current_hp"),
            "max_hp": state.get("max_hp"),
        }
    if pause_event == "max_floor":
        return {
            "screen_type": screen_type,
            "verb": verb,
            "key": f"PAUSE:{pause_event}",
            "emotion": requested_emotion or "thinking",
            "reason": "max_floor",
            "importance": 3,
            "tags": {"terminal", "pause", "max_floor"},
            "pause_event": pause_event,
            "floor": state.get("floor"),
            "hp": state.get("current_hp"),
            "max_hp": state.get("max_hp"),
        }
    if pause_event == "combat_victory":
        return {
            "screen_type": screen_type,
            "verb": verb,
            "key": f"EVENT:{pause_event}:{state.get('floor') or 0}",
            "emotion": requested_emotion or "happy",
            "reason": "combat_victory",
            "importance": 4,
            "tags": {"victory", "hype"},
            "narration_event": pause_event,
            "floor": state.get("floor"),
            "hp": state.get("current_hp"),
            "max_hp": state.get("max_hp"),
        }

    if verb == "START":
        return {
            "screen_type": screen_type,
            "verb": verb,
            "key": key,
            "emotion": "happy",
            "reason": "run_start",
            "importance": 3,
            "tags": {"start", "hype"},
            "floor": state.get("floor"),
            "hp": state.get("current_hp"),
            "max_hp": state.get("max_hp"),
        }

    if combat and screen_type in {"", "NONE"}:
        context = _classify_combat_context(state, command, verb)
        context["key"] = f"COMBAT:{context['key']}"
        return context

    screen_details: dict[str, Any] = {}
    if screen_type in {"CARD_REWARD", "COMBAT_REWARD", "MAP", "REST", "SHOP_SCREEN", "GRID", "EVENT"}:
        screen_details = _screen_context_details(state, command, screen_type)
        emotion = "thinking"
        importance = 2
        reason = "choice"
        tags.add("choice")
        screen_tags = {
            "CARD_REWARD": {"reward", "deck_plan", "card_pick"},
            "COMBAT_REWARD": {"reward"},
            "MAP": {"map", "route"},
            "REST": {"rest", "deck_plan"},
            "SHOP_SCREEN": {"shop", "deck_plan"},
            "GRID": {"grid", "card_select", "deck_plan"},
            "EVENT": {"event"},
        }
        tags.update(screen_tags.get(screen_type, set()))
        if screen_type == "COMBAT_REWARD":
            reason = "reward"
        elif screen_type == "MAP":
            reason = "route"
        elif screen_type == "REST":
            reason = "rest"
        elif screen_type == "GRID":
            reason = "card_select"
    if verb in {"PROCEED", "CONFIRM", "RETURN", "LEAVE"}:
        importance = 0 if screen_type not in {"CARD_REWARD", "MAP", "REST", "SHOP_SCREEN", "EVENT", "GRID"} else 1
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

    key_detail = str(screen_details.get("choice_key") or screen_details.get("purpose") or "").strip()
    if key_detail:
        key = f"{key}:{key_detail}"

    result = {
        "screen_type": screen_type,
        "verb": verb,
        "key": key,
        "emotion": emotion,
        "reason": reason,
        "importance": importance,
        "tags": tags,
        "floor": state.get("floor"),
        "hp": state.get("current_hp"),
        "max_hp": state.get("max_hp"),
    }
    result.update(screen_details)
    return result


def _classify_combat_context(state: dict[str, Any], command: str, verb: str) -> dict[str, Any]:
    combat = state.get("combat_state") or {}
    player = combat.get("player") or {}
    monsters = [monster for monster in combat.get("monsters") or [] if isinstance(monster, dict)]
    incoming = _estimate_incoming_damage(monsters)
    block = int(player.get("block") or 0)
    damage_gap = max(incoming - block, 0)
    base_details: dict[str, Any] = {
        "incoming": incoming,
        "block": block,
        "damage_gap": damage_gap,
        "monster_count": len(monsters),
        "energy": player.get("energy"),
        "floor": state.get("floor"),
        "hp": state.get("current_hp"),
        "max_hp": state.get("max_hp"),
    }
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
        return _context("NONE", verb, key, emotion, reason, importance, tags, base_details)

    if verb == "POTION":
        tags.add("potion")
        potion = _potion_for_command(state, command)
        if potion:
            base_details["potion_name"] = str(potion.get("name") or potion.get("id") or "")
        return _context("NONE", verb, "POTION", "happy", "potion", 3, tags, base_details)

    if verb != "PLAY":
        return _context("NONE", verb, key, emotion, reason, importance, tags, base_details)

    play = _parse_play_command(command)
    if play is None:
        return _context("NONE", verb, key, emotion, reason, importance, tags, base_details)
    card_index, target_index = play
    hand = combat.get("hand") or []
    card = hand[card_index] if 0 <= card_index < len(hand) and isinstance(hand[card_index], dict) else {}
    key = f"PLAY:{str(card.get('id') or card.get('name') or card_index)}"
    details = dict(base_details)
    details["card_name"] = str(card.get("name") or card.get("id") or "")
    details["card_damage"] = _estimate_card_damage(card)
    details["card_block"] = _estimate_card_block(card)

    if target_index is not None and 0 <= target_index < len(monsters):
        monster = monsters[target_index]
        damage = _estimate_card_damage_against(card, monster, player)
        hp = int(monster.get("current_hp") or 0) + int(monster.get("block") or 0)
        details.update(
            {
                "target_name": str(monster.get("name") or monster.get("id") or "敵"),
                "target_hp": int(monster.get("current_hp") or 0),
                "target_effective_hp": hp,
                "target_block": int(monster.get("block") or 0),
                "card_damage": damage,
            }
        )
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
    return _context("NONE", verb, key, emotion, reason, importance, tags, details)


def _context(
    screen_type: str,
    verb: str,
    key: str,
    emotion: str,
    reason: str,
    importance: int,
    tags: set[str],
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = {
        "screen_type": screen_type,
        "verb": verb,
        "key": key,
        "emotion": emotion,
        "reason": reason,
        "importance": importance,
        "tags": tags,
    }
    if details:
        context.update(details)
    return context


ROOM_SYMBOL_NAMES = {
    "M": "通常戦闘",
    "E": "エリート",
    "R": "休憩所",
    "$": "ショップ",
    "?": "イベント",
    "T": "宝箱",
    "B": "ボス",
}

REST_CHOICE_NAMES = {
    "rest": "休憩",
    "smith": "強化",
    "dig": "発掘",
    "lift": "筋力アップ",
    "recall": "鍵の回収",
    "purge": "削除",
}

EVENT_CHOICE_NAMES = {
    "talk": "ネオーと話す",
    "leave": "離れる",
    "take": "取る",
    "reach inside": "中を探る",
    "deeper": "さらに奥へ進む",
    "pray": "祈る",
    "enemies in your next three combats have 1 hp": "最初の三戦を敵体力1にする祝福",
    "max hp +8": "最大体力8アップ",
    "ignore": "無視する",
    "take and give": "アイアンウェーブを受け取りカードを預ける",
    "take and give: receive iron wave and store a card": "アイアンウェーブを受け取りカードを預ける",
}


def _screen_context_details(state: dict[str, Any], command: str, screen_type: str) -> dict[str, Any]:
    screen_state = state.get("screen_state") or {}
    if not isinstance(screen_state, dict):
        screen_state = {}
    index = _command_choice_index(command)
    details: dict[str, Any] = {
        "choice_index": index,
        "deck_plan": _deck_plan_line(state, screen_type),
    }
    if screen_type in {"CARD_REWARD", "GRID"}:
        purpose = _grid_purpose(screen_state) if screen_type == "GRID" else "reward"
        details["purpose"] = purpose
        cards = [card for card in screen_state.get("cards") or [] if isinstance(card, dict)]
        details["card_options"] = [_card_label(card) for card in cards if _card_label(card)]
        details["card_option_summaries"] = [_card_option_summary(card) for card in cards if _card_label(card)]
        if index is not None and 0 <= index < len(cards):
            card = cards[index]
            details.update(
                {
                    "choice_label": _card_label(card),
                    "choice_key": str(card.get("id") or card.get("name") or index),
                    "choice_card_type": str(card.get("type") or "").upper(),
                    "choice_card_cost": card.get("cost"),
                    "choice_card_name": str(card.get("name") or card.get("id") or ""),
                    "choice_card_rarity": str(card.get("rarity") or "").upper(),
                    "choice_card_exhausts": bool(card.get("exhausts")),
                    "choice_card_ethereal": bool(card.get("ethereal")),
                    "choice_card_damage": card.get("estimated_damage"),
                    "choice_card_block": card.get("estimated_block"),
                }
            )
        selected = [_card_label(card) for card in screen_state.get("selected_cards") or [] if isinstance(card, dict)]
        details["selected_cards"] = [card for card in selected if card]
    elif screen_type == "COMBAT_REWARD":
        rewards = [reward for reward in screen_state.get("rewards") or [] if isinstance(reward, dict)]
        if index is not None and 0 <= index < len(rewards):
            details["choice_label"] = _reward_label(rewards[index])
            details["choice_key"] = str(rewards[index].get("reward_type") or index)
    elif screen_type == "MAP":
        nodes = [node for node in screen_state.get("next_nodes") or [] if isinstance(node, dict)]
        route_options = []
        for node in nodes:
            symbol = str(node.get("symbol") or "")
            route_options.append(ROOM_SYMBOL_NAMES.get(symbol, "次の部屋"))
        details["route_options"] = route_options
        if index is not None and 0 <= index < len(nodes):
            symbol = str(nodes[index].get("symbol") or "")
            details["choice_label"] = ROOM_SYMBOL_NAMES.get(symbol, "次の部屋")
            details["choice_key"] = f"{symbol}:{nodes[index].get('x')}:{nodes[index].get('y')}"
            details["map_symbol"] = symbol
    elif screen_type == "REST":
        choices = _screen_choices(state, screen_state) or [str(option) for option in screen_state.get("rest_options") or []]
        details["choice_options"] = [_choice_label(choice) for choice in choices]
        if index is not None and 0 <= index < len(choices):
            details["choice_label"] = _choice_label(choices[index])
            details["choice_key"] = str(choices[index])
            details["purpose"] = str(choices[index]).strip().lower()
    else:
        choices = _screen_choices(state, screen_state)
        details["choice_options"] = [_choice_label(choice) for choice in choices]
        if index is not None and 0 <= index < len(choices):
            details["choice_label"] = _choice_label(choices[index])
            details["choice_key"] = str(choices[index])
    return details


def _command_choice_index(command: str) -> int | None:
    parts = command.split()
    if not parts or parts[0].upper() != "CHOOSE" or len(parts) < 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def _potion_for_command(state: dict[str, Any], command: str) -> dict[str, Any]:
    parts = command.split()
    if len(parts) < 3 or parts[0].upper() != "POTION":
        return {}
    try:
        slot = int(parts[2])
    except ValueError:
        return {}
    potions = state.get("potions") or []
    if isinstance(potions, list) and 0 <= slot < len(potions) and isinstance(potions[slot], dict):
        return potions[slot]
    return {}


def _screen_choices(state: dict[str, Any], screen_state: dict[str, Any]) -> list[str]:
    raw_choices = state.get("choice_list") or screen_state.get("options") or screen_state.get("choices") or []
    if not isinstance(raw_choices, list):
        return []
    choices: list[str] = []
    for choice in raw_choices:
        if isinstance(choice, str):
            choices.append(choice)
        elif isinstance(choice, dict):
            choices.append(str(choice.get("name") or choice.get("text") or choice.get("label") or ""))
        else:
            choices.append(str(choice))
    return [choice for choice in choices if choice]


def _card_label(card: dict[str, Any]) -> str:
    return sanitize_spoken_text(str(card.get("name") or card.get("id") or "")).strip() or "カード"


def _reward_label(reward: dict[str, Any]) -> str:
    reward_type = str(reward.get("reward_type") or "").upper()
    if reward_type == "GOLD":
        gold = reward.get("gold")
        return f"ゴールド{gold}" if gold is not None else "ゴールド"
    if reward_type == "CARD":
        return "カード報酬"
    if reward_type == "POTION":
        potion = reward.get("potion")
        if isinstance(potion, dict):
            return sanitize_spoken_text(str(potion.get("name") or potion.get("id") or "")).strip() or "ポーション"
        return "ポーション"
    if reward_type == "RELIC":
        relic = reward.get("relic")
        if isinstance(relic, dict):
            return sanitize_spoken_text(str(relic.get("name") or relic.get("id") or "")).strip() or "レリック"
        return "レリック"
    return _choice_label(reward_type) or "報酬"


def _card_pick_reason(context: dict[str, Any]) -> str:
    raw_name = str(context.get("choice_card_name") or context.get("choice_key") or "").strip()
    normalized = raw_name.lower()
    card_type = str(context.get("choice_card_type") or "").upper()
    cost = context.get("choice_card_cost")
    rarity = str(context.get("choice_card_rarity") or "").upper()
    exhausts = bool(context.get("choice_card_exhausts"))
    ethereal = bool(context.get("choice_card_ethereal"))
    known_reasons = {
        "disarm": "敵の筋力を下げられるので、ボスやエリートの大きな攻撃を軽くできます。",
        "carnage": "序盤に欲しい大きな火力です。戦闘を短くして被弾を減らします。",
        "shrug it off": "ブロックしながら一枚引けるので、守りと手札の両方が安定します。",
        "perfected strike": "ストライクが多い今なら打点が伸びます。序盤火力として見ます。",
        "sword boomerang": "攻撃回数が多いので、筋力が増えるほど伸びます。今は火力候補として見ます。",
        "second wind": "不要な手札をブロックに変えられます。守りながら山札をきれいに使う札です。",
        "heavy blade": "筋力が乗ると一気に伸びる攻撃です。筋力札が見えた時の伸びしろを取ります。",
        "headbutt": "9点の打点に加えて、使ったバッシュなどを山札上に戻せます。次ターンの形まで作れる一枚です。",
        "battle trance": "一気に手札を増やせるので、欲しい攻撃や防御に届きやすくなります。",
        "anger": "エナジーなしで撃てるので、序盤の手数を増やせます。ただし山札に増える点は注意です。",
        "ghostly armor": "大きく守れるカードです。消える前に使う必要はありますが、危ないターンを支えます。",
        "clothesline": "12点の攻撃に脱力が付くので、敵の次の攻撃を弱めながら削れます。",
        "searing blow": "育てれば主役になりますが、強化回数が必要なので少し覚悟がいります。",
        "flex": "このターンだけ筋力を上げます。手数が多い構成なら火力に変わります。",
        "twin strike": "二回攻撃なので筋力が乗ると伸びます。序盤の削り役です。",
        "thunderclap": "全体に弱体を付けられるので、この後の攻撃が通しやすくなります。",
    }
    if normalized in known_reasons:
        return known_reasons[normalized]
    if card_type == "ATTACK":
        if cost == 0:
            return "エナジーを使わずに打点を足せるので、手札事故を減らせます。"
        if cost is not None and _safe_int(cost) >= 2:
            return "重いぶん一枚の打点が欲しい場面で頼れます。序盤の決定力を補います。"
        return "攻撃札を増やして、序盤の戦闘を長引かせない狙いです。"
    if card_type == "SKILL":
        if exhausts:
            return "使い切りですが効果が大きい札です。危ないターンを一回きれいに受けます。"
        return "守りを厚くして、事故った手札でも体力を守りやすくします。"
    if card_type == "POWER":
        return "早めに置けるとラン全体の方針になります。長い戦闘ほど価値が出ます。"
    if rarity == "RARE":
        return "レアらしく一枚で方針を作れる可能性があります。ここは軸候補として見ます。"
    if ethereal:
        return "手札に来たターンで使う判断が必要ですが、そのぶん瞬間的な価値があります。"
    return "今のデッキに足りない役割を埋めにいきます。"


def _choice_label(choice: str) -> str:
    normalized = choice.strip().lower()
    if normalized in REST_CHOICE_NAMES:
        return REST_CHOICE_NAMES[normalized]
    if normalized in EVENT_CHOICE_NAMES:
        return EVENT_CHOICE_NAMES[normalized]
    return sanitize_spoken_text(choice).strip() or "この選択肢"


def _grid_purpose(screen_state: dict[str, Any]) -> str:
    if screen_state.get("for_purge"):
        return "purge"
    if screen_state.get("for_upgrade"):
        return "upgrade"
    if screen_state.get("for_transform"):
        return "transform"
    return "select"


def _commentary_lines(raw: dict[str, Any], command: str, context: dict[str, Any]) -> list[str]:
    tags = set(context.get("tags") or set())
    if "combat" in tags:
        return _combat_commentary_lines(command, context)
    return _screen_commentary_lines(raw, command, context)


def _combat_commentary_lines(command: str, context: dict[str, Any]) -> list[str]:
    verb = str(context.get("verb") or command.split(" ", 1)[0]).upper()
    incoming = _safe_int(context.get("incoming"))
    block = _safe_int(context.get("block"))
    damage_gap = _safe_int(context.get("damage_gap"))
    card_name = sanitize_spoken_text(str(context.get("card_name") or "")).strip()
    target_name = sanitize_spoken_text(str(context.get("target_name") or "敵")).strip() or "敵"
    target_hp = _safe_int(context.get("target_hp"))
    effective_hp = _safe_int(context.get("target_effective_hp")) or target_hp
    damage = _safe_int(context.get("card_damage"))
    block_gain = _safe_int(context.get("card_block"))
    potion_name = sanitize_spoken_text(str(context.get("potion_name") or "")).strip() or "ポーション"
    tags = set(context.get("tags") or set())
    reason = str(context.get("reason") or "")
    lines: list[str] = []

    if verb == "END":
        if damage_gap > 0:
            lines.append(f"ここで{damage_gap}点ほど受けます。次の手札で立て直したいですね。")
            lines.append(f"ブロックは{block}点です。被弾込みで次のターンを迎えます。")
        else:
            lines.append("被弾は抑えました。次のドローを見て攻め直します。")
        return lines

    if verb == "POTION":
        if incoming > 0:
            lines.append(f"{potion_name}を使います。相手の{incoming}点に備えて、ここは消耗品で安定させます。")
        else:
            lines.append(f"{potion_name}を使います。今のターンを強くして戦闘を短くします。")
        lines.append("ポーションは温存も大事ですが、使いどころを逃さない判断です。")
        return lines

    if verb != "PLAY":
        if incoming > 0:
            return [f"相手は合計{incoming}点を構えています。ここは判断が重いですね。"]
        return []

    if "lethal" in tags:
        if target_hp > 0:
            lines.append(f"{target_name}は残り体力{target_hp}です。ここで落とせると被弾がぐっと楽になります。")
        lines.append(f"{card_name or 'この一手'}で取り切ります。ここは逃したくない場面です。")
        lines.append("みなさんもここは討伐優先でよさそうですかね。")
        return lines

    if "block" in tags:
        if incoming > 0:
            covered = min(incoming, block + block_gain)
            lines.append(f"相手の攻撃は合計{incoming}点です。ここで{covered}点ぶん受けを作ります。")
            if damage_gap > 0 and block + block_gain < incoming:
                lines.append(f"全部は止まりませんが、被弾を{max(incoming - block - block_gain, 0)}点まで抑えます。")
            else:
                lines.append("ここを守り切れれば、次のターンに攻め直せます。")
            lines.append("ここは守りでよさそうですかね、次に反撃します。")
        else:
            lines.append(f"{card_name or '防御札'}で守りを厚くします。次の展開を待ちます。")
        return lines

    if reason == "race" or "push" in tags:
        lines.append(f"相手は{incoming}点を構えていますが、先に倒す圧をかけます。")
        if target_hp > 0 and damage > 0:
            lines.append(f"{target_name}は残り体力{target_hp}です。{damage}点を入れて勝負を急ぎます。")
        lines.append("被弾は残りますが、次のリーサルを近づける一手です。")
        lines.append("攻め切る判断、みなさんならどう見ますか。")
        return lines

    if reason == "attack":
        if incoming == 0:
            lines.append(f"今は被弾がありません。{card_name or '攻撃'}で先に形を作ります。")
        elif target_hp > 0 and damage > 0:
            lines.append(
                f"{target_name}は残り体力{target_hp}です。{damage}点入れて残り体力{max(effective_hp - damage, 0)}まで縮めます。"
            )
        if effective_hp > damage > 0:
            lines.append(f"この一撃で残り体力{max(effective_hp - damage, 0)}まで近づきます。次が見えてきますね。")
        else:
            lines.append("小さな打点でも、後のリーサルを作る一手です。")
        lines.append("ここは削り優先で見ています、どうでしょう。")
        return lines

    if "setup" in tags:
        return ["今すぐの打点より、次の形を整えます。", "ここは後の強いターンを作る準備です。"]
    return []


def _screen_commentary_lines(raw: dict[str, Any], command: str, context: dict[str, Any]) -> list[str]:
    state = raw.get("game_state") or {}
    if not isinstance(state, dict):
        return []
    screen_type = str(state.get("screen_type") or state.get("screen_name") or "").upper()
    hp = state.get("current_hp")
    max_hp = state.get("max_hp")
    verb = str(context.get("verb") or command.split(" ", 1)[0]).upper()
    choice_label = sanitize_spoken_text(str(context.get("choice_label") or "")).strip()
    deck_plan = sanitize_spoken_text(str(context.get("deck_plan") or "")).strip()
    purpose = str(context.get("purpose") or "")
    lines: list[str] = []
    if screen_type == "MAP":
        if choice_label:
            lines.append(f"みなさんなら安全寄りもありですが、次は{choice_label}へ向かいます。")
        lines.extend(
            [
                "次の戦闘まで見据えてルートを選びます。",
                "ここから先の休憩所とエリート位置が大事になります。",
                "みなさんなら安全寄りにしますか、それともエリートを見ますか。",
            ]
        )
        return lines
    if screen_type == "CARD_REWARD":
        card_options = [
            sanitize_spoken_text(str(card)).strip()
            for card in context.get("card_options") or []
            if sanitize_spoken_text(str(card)).strip()
        ]
        if verb == "SKIP":
            lines.append("ここはカードを増やしません。デッキの濁りを避ける判断です。")
        elif choice_label:
            if len(card_options) >= 2:
                lines.append(
                    f"候補は{'、'.join(card_options[:3])}です。みなさんなら別候補もありですが、今回は{choice_label}。{_card_pick_reason(context)}"
                )
            else:
                lines.append(f"みなさんなら別候補もありですが、今回は{choice_label}。{_card_pick_reason(context)}")
        lines.extend(
            [
                "この報酬は、次の数戦を楽にできるかで見ます。",
                deck_plan,
                "みなさんなら取りたいカードありますかね、今回はデッキの方向性を優先します。",
            ]
        )
        return [line for line in lines if line]
    if screen_type == "COMBAT_REWARD":
        if choice_label:
            lines.append(f"{choice_label}を回収します。次の部屋に向けたリソース補充です。")
        lines.extend(
            [
                "戦闘後の回収です。ここで次の部屋への準備を整えます。",
                "報酬は勝ち筋に近いものから拾います。ここはテンポよくいきます。",
            ]
        )
        return lines
    if screen_type == "EVENT":
        choice_options = [
            sanitize_spoken_text(str(option)).strip()
            for option in context.get("choice_options") or []
            if sanitize_spoken_text(str(option)).strip()
        ]
        if choice_label:
            alternatives = [option for option in choice_options if option != choice_label]
            if alternatives:
                lines.append(f"{_join_short(alternatives[:2])}もありますが、今回は{choice_label}を選びます。")
            else:
                lines.append(f"イベントでは{choice_label}を選びます。")
        if hp is not None and max_hp is not None:
            lines.append(f"体力は{hp}、最大{max_hp}です。イベントのリスクは慎重に見ます。")
        lines.append("イベントはリターンだけでなく、失うものも見て判断します。")
        lines.append("ここはコメントでも意見が割れそうですが、リスクを先に見ます。")
        return lines
    if screen_type == "REST":
        if choice_label:
            lines.append(f"みなさんなら回復も見そうですが、休憩所では{choice_label}を選びます。")
        if purpose == "upgrade":
            lines.append("回復より強化を優先して、デッキの出力を上げます。")
        lines.extend(
            [
                "ここは強化か回復か、ラン全体の分かれ目です。",
                deck_plan,
                "みなさんなら回復しますかね、ここは先の戦闘を見て決めます。",
            ]
        )
        return [line for line in lines if line]
    if screen_type == "SHOP_SCREEN":
        if choice_label:
            lines.append(f"{choice_label}を選びます。今のデッキに足りないところへお金を使います。")
        lines.extend(
            [
                "お金の使い道で、この先の安定感がかなり変わります。",
                deck_plan,
                "ここは買い過ぎず、勝ち筋に近いものだけ見ます。",
            ]
        )
        return [line for line in lines if line]
    if screen_type == "GRID":
        if verb in {"CONFIRM", "PROCEED"}:
            selected = [sanitize_spoken_text(str(card)).strip() for card in context.get("selected_cards") or []]
            if selected:
                lines.append(f"{'、'.join(selected[:2])}で確定します。目的に合うカードを選べました。")
            else:
                lines.append("カード選択を確定します。ここからデッキを整えます。")
        elif choice_label:
            if purpose == "purge":
                lines.append(f"{choice_label}を削除候補にします。山札の弱い引きを減らす方針です。")
            elif purpose == "upgrade":
                lines.append(f"{choice_label}を強化候補にします。よく使う札の効率を上げます。")
            elif purpose == "transform":
                lines.append(f"{choice_label}を変化候補にします。弱い札を伸びしろに変えます。")
            else:
                lines.append(f"{choice_label}を選びます。今の方針に合うカードを優先します。")
        lines.extend(
            [
                deck_plan,
                "カード選択は、山札の完成形から逆算します。",
                "みなさんならどれを触りますかね、ここはデッキの弱点を減らします。",
            ]
        )
        return [line for line in lines if line]
    return []


def _pre_action_lines(raw: dict[str, Any], command: str, context: dict[str, Any]) -> list[str]:
    verb = str(context.get("verb") or command.split(" ", 1)[0]).upper()
    if verb not in {"CHOOSE", "SKIP", "CONFIRM"}:
        return []
    screen_type = str(context.get("screen_type") or "").upper()
    choice_label = sanitize_spoken_text(str(context.get("choice_label") or "")).strip()
    if screen_type == "CARD_REWARD":
        options = [str(option) for option in context.get("card_options") or [] if str(option).strip()]
        summaries = [str(summary) for summary in context.get("card_option_summaries") or [] if str(summary).strip()]
        if options:
            if summaries:
                return [
                    f"うーん、ここは悩みますね。{_join_short(summaries[:3])}で見比べます。",
                ]
            return [f"うーん、候補は{_join_short(options[:3])}です。どれを伸ばすか迷いますね。"]
    if screen_type == "EVENT":
        options = [str(option) for option in context.get("choice_options") or [] if str(option).strip()]
        if len(options) >= 2:
            return [f"イベント選択です。{_join_short(options[:3])}、どれも一長一短ですね。"]
        return ["イベント選択です。リターンと失うものを見てから決めます。"]
    if screen_type == "MAP":
        options = [str(option) for option in context.get("route_options") or [] if str(option).strip()]
        if len(options) >= 2:
            return [f"ルートは{_join_short(options[:4])}が見えます。安全に行くか、強くなる部屋を見るかですね。"]
        return ["ルート選択です。休憩所とエリート位置を先に見ます。"]
    if screen_type == "REST":
        options = [str(option) for option in context.get("choice_options") or [] if str(option).strip()]
        if choice_label and len(options) >= 2:
            return [f"焚き火は{_join_short(options[:3])}で悩みます。体力と火力のどちらを優先するかですね。"]
    if screen_type in {"SHOP_SCREEN", "GRID"} and choice_label:
        return [f"ここは{choice_label}に触るか悩みます。今の山札に本当に必要かで見ます。"]
    return []


def _join_short(items: list[str]) -> str:
    cleaned = [sanitize_spoken_text(str(item)).strip("、。 ") for item in items if sanitize_spoken_text(str(item)).strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    return "、".join(cleaned[:-1]) + "、そして" + cleaned[-1]


def _card_option_summary(card: dict[str, Any]) -> str:
    label = _card_label(card)
    normalized = str(card.get("name") or card.get("id") or "").strip().lower()
    if normalized == "anger":
        return f"{label}は0コスト火力"
    if normalized == "ghostly armor":
        return f"{label}は大きな守り"
    if normalized == "clothesline":
        return f"{label}は攻撃しながら脱力"
    if normalized == "perfected strike":
        return f"{label}はストライク枚数で火力"
    if normalized == "second wind":
        return f"{label}は不要札を守りに変える"
    if normalized == "headbutt":
        return f"{label}は打点と山札操作"
    card_type = str(card.get("type") or "").upper()
    cost = card.get("cost")
    if card_type == "ATTACK":
        return f"{label}は{cost}コスト攻撃" if cost is not None else f"{label}は攻撃札"
    if card_type == "SKILL":
        return f"{label}は守りや補助"
    if card_type == "POWER":
        return f"{label}は長期戦の軸"
    return label


def _deck_plan_line(state: dict[str, Any], screen_type: str = "") -> str:
    cards = _deck_cards(state)
    deck_size = len(cards)
    if deck_size <= 0:
        return "デッキ方針は、今ある強い動きを伸ばして次の戦闘を楽にすることです。"
    attack_count = sum(1 for card in cards if str(card.get("type") or "").upper() == "ATTACK")
    skill_count = sum(1 for card in cards if str(card.get("type") or "").upper() == "SKILL")
    power_count = sum(1 for card in cards if str(card.get("type") or "").upper() == "POWER")
    floor = _safe_int(state.get("floor"))
    act = _safe_int(state.get("act"), 1)
    hp = _safe_int(state.get("current_hp"))
    max_hp = _safe_int(state.get("max_hp"))

    if screen_type == "REST" and max_hp > 0 and hp / max_hp <= 0.45:
        return "デッキ方針は攻めたいですが、今は体力を残す判断もかなり大事です。"
    if floor <= 6 and attack_count <= 5:
        return "デッキ方針は、序盤の打点を厚くして早めに敵を倒すことです。"
    if deck_size >= 22:
        return "デッキ方針は、山札が膨らみすぎないように有効札だけを増やすことです。"
    if skill_count >= attack_count + 3:
        return "デッキ方針は、守りに寄りすぎないよう決定力を足すことです。"
    if power_count >= 2 or act >= 2:
        return "デッキ方針は、長期戦の強さを保ちながら初動の遅さを補うことです。"
    return "デッキ方針は、軽い打点と受けをそろえて事故を減らすことです。"


def _deck_cards(state: dict[str, Any]) -> list[dict[str, Any]]:
    deck = state.get("deck")
    if isinstance(deck, dict):
        cards = deck.get("cards") or []
    else:
        cards = deck or []
    if not isinstance(cards, list):
        return []
    return [card for card in cards if isinstance(card, dict)]


def _is_bland_model_line(text: str, context: dict[str, Any]) -> bool:
    if context.get("pause_event") or str(context.get("reason") or "") in {"game_over", "max_floor", "combat_victory"}:
        return False
    normalized = _normalize_for_repeat(text)
    specific_values = [
        context.get("card_name"),
        context.get("target_name"),
        context.get("choice_label"),
        context.get("target_hp"),
        context.get("incoming"),
        context.get("damage_gap"),
    ]
    if "potion" in set(context.get("tags") or set()) and context.get("potion_name"):
        potion_name = sanitize_spoken_text(str(context.get("potion_name") or ""))
        if potion_name and _normalize_for_repeat(potion_name) not in normalized:
            return True
    for value in specific_values:
        if value is None or value == "":
            continue
        spoken = sanitize_spoken_text(str(value))
        if spoken and _normalize_for_repeat(spoken) in normalized:
            return False
    if re.search(r"\d", text):
        return False
    if context.get("choice_label") and any(word in text for word in ("カード", "報酬", "選び", "取ります", "回収")):
        return True
    bland_words = ("ここは", "よし", "まず", "攻め", "押し", "削", "テンポ", "大事", "選択", "前のめり", "カード", "報酬")
    return len(normalized) <= 24 or any(word in text for word in bland_words)


def _model_text_conflicts_with_context(raw: dict[str, Any], text: str, context: dict[str, Any]) -> bool:
    normalized = _normalize_for_repeat(text)
    reason = str(context.get("reason") or "")
    if reason == "combat_victory":
        return _victory_model_text_conflicts(raw, text)

    tags = set(context.get("tags") or set())
    if "combat" in tags:
        incoming = _safe_int(context.get("incoming"))
        damage_gap = _safe_int(context.get("damage_gap"))
        block = _safe_int(context.get("block"))
        if incoming > 0 and any(word in normalized for word in ("被弾がありません", "被弾なし", "ノーダメ", "安全です")):
            return True
        if damage_gap > 0 and any(word in normalized for word in ("受け切", "防ぎ切", "守り切")) and block <= 0:
            return True
    return False


def _victory_model_text_conflicts(raw: dict[str, Any], text: str) -> bool:
    victory = raw.get("_sts_ai_victory_context") or {}
    if not isinstance(victory, dict):
        victory = {}
    hp_after = _safe_int(victory.get("hp_after_reward"))
    hp_before = _safe_int(victory.get("hp_before_reward"))
    max_hp = _safe_int(victory.get("max_hp"))
    took_damage = (max_hp > 0 and 0 < hp_after < max_hp) or (max_hp > 0 and 0 < hp_before < max_hp)
    if not took_damage:
        return False
    normalized = _normalize_for_repeat(text)
    conflict_words = ("無傷", "ノーダメ", "被弾なし", "体力を守って", "体力守って", "守って勝て")
    return any(word in normalized for word in conflict_words)


def _victory_has_damage_context(raw: dict[str, Any]) -> bool:
    victory = raw.get("_sts_ai_victory_context") or {}
    if not isinstance(victory, dict):
        return False
    hp_before = _safe_int(victory.get("hp_before_reward"))
    max_hp = _safe_int(victory.get("max_hp"))
    return max_hp > 0 and 0 < hp_before < max_hp


def _reaction_lines(context: dict[str, Any]) -> list[str]:
    tags = set(context.get("tags") or set())
    reason = str(context.get("reason") or "")
    if "lethal" in tags:
        return ["よし、ここで取り切ります！", "いけます、倒し切りましょう！", "そこです、決めにいきます！"]
    if "danger" in tags:
        return ["うわ、ここは踏ん張りどころです！", "痛いターンです、集中しましょう。", "ここを越えればまだあります！"]
    if "potion" in tags:
        return ["よし、ここで使います！", "出し惜しみなしでいきましょう。", "ポーション投入、勝負どころです！"]
    if "stabilize" in tags:
        return ["よし、受け切れます！", "ここは守りが光ります！", "きれいに耐えにいきます！"]
    if reason == "attack":
        return ["いけます、まず削ります！", "いいですね、攻めていきましょう！", "ここは前のめりでいきます！"]
    if "skip" in tags:
        return ["取らない勇気も大事です。", "ここはスルーで締めます。", "今のデッキには入れません。"]
    if "choice" in tags:
        return ["さて、ここは悩みどころです。", "この選択、大事です。", "次につながる方を選びます！"]
    if "start" in tags:
        return ["よし、登塔開始です！", "さあ行きましょう、まずは一勝です！", "開幕から集中していきます！"]
    return ["よし、次へ行きましょう！", "テンポよく進めます。", "ここは迷わずいきます。"]


def _victory_lines(raw: dict[str, Any], context: dict[str, Any]) -> list[str]:
    victory = raw.get("_sts_ai_victory_context") or {}
    if not isinstance(victory, dict):
        victory = {}
    enemies = [enemy for enemy in victory.get("enemies") or [] if isinstance(enemy, dict)]
    enemy_names = [str(enemy.get("name") or "").strip() for enemy in enemies if enemy.get("name")]
    enemy_label = enemy_names[0] if len(enemy_names) == 1 else "敵"
    hp_after = victory.get("hp_after_reward")
    max_hp = victory.get("max_hp")
    floor = victory.get("floor") or context.get("floor")
    hp_before = victory.get("hp_before_reward")
    hp_after_int = _safe_int(hp_after)
    hp_before_int = _safe_int(hp_before)
    max_hp_int = _safe_int(max_hp)
    took_damage = max_hp_int > 0 and 0 < hp_before_int < max_hp_int
    lines: list[str] = []
    if took_damage and hp_after is not None and max_hp is not None:
        if _has_relic(raw, "Burning Blood") and hp_before_int > 0 and hp_after_int > hp_before_int:
            lines.append(
                f"被弾はありましたが、バーニングブラッドで体力{hp_after}、最大{max_hp}まで戻して勝利です。"
            )
        else:
            lines.append(f"被弾はありましたが、体力{hp_after}、最大{max_hp}で勝利です。まだ進めます。")
    lines.extend(
        [
            f"やりました！{enemy_label}戦を突破しました。",
            "勝利です、報酬の前に一息つけますね。",
            "きっちり倒し切りました。次へつながります。",
        ]
    )
    if hp_after is not None and max_hp is not None:
        lines.append(f"体力{hp_after}、最大{max_hp}で勝利です。まだ進めます。")
    if hp_before is not None and hp_after is not None and _has_relic(raw, "Burning Blood") and hp_after > hp_before:
        lines.append(f"バーニングブラッドで体力が{hp_after}まで戻りました。アイアンクラッドらしく前に出られます。")
    if floor:
        lines.append(f"{floor}階を突破です。この勝ちは大きいですね。")
    if len(enemy_names) > 1:
        lines.append("複数相手をさばき切りました。いい勝利です。")
    return lines


def _failure_lines(raw: dict[str, Any], context: dict[str, Any]) -> list[str]:
    state = raw.get("game_state") or {}
    if not isinstance(state, dict):
        state = {}
    floor = state.get("floor") or context.get("floor")
    hp = state.get("current_hp")
    max_hp = state.get("max_hp")
    lines = [
        "ここで倒れました。かなり粘りましたが、今回はここまでです。",
        "うーん、届きませんでした。次は被弾を減らすルート取りから見直します。",
        "悔しいですね。デッキの方向性は悪くなかったので、次は序盤の安定を上げたいです。",
    ]
    if floor:
        lines.append(f"{floor}階で終了です。ここまでの判断を次のランに持ち帰ります。")
    if hp is not None and max_hp is not None:
        lines.append(f"体力{hp}、最大{max_hp}でラン終了です。危険ターンの受け方が課題でした。")
    return lines


def _max_floor_lines(raw: dict[str, Any], context: dict[str, Any]) -> list[str]:
    state = raw.get("game_state") or {}
    if not isinstance(state, dict):
        state = {}
    screen_state = state.get("screen_state") or {}
    if not isinstance(screen_state, dict):
        screen_state = {}
    if str(state.get("screen_type") or state.get("screen_name") or "").upper() == "EVENT":
        event_name = sanitize_spoken_text(str(screen_state.get("event_name") or screen_state.get("event_id") or "")).strip()
        choices = [_choice_label(choice) for choice in _screen_choices(state, screen_state)]
        if event_name and len(choices) >= 2:
            return [
                f"{event_name}イベントで区切ります。{_join_short(choices[:3])}で迷う、おいしい場面ですね。",
                "ここはコメントで相談したい選択です。リスクを取るか、安全に離れるかを見ます。",
            ]
    floor = context.get("floor")
    if floor:
        return [
            f"{floor}階まで到達しました。設定した区切りなので、ここで一度止めます。",
            "ここまでの方針は確認できました。続きはルートと報酬を見て再開します。",
        ]
    return ["設定した区切りに到達しました。ここで一度止めます。"]


def _bridge_lines(context: dict[str, Any]) -> list[str]:
    tags = set(context.get("tags") or set())
    reason = str(context.get("reason") or "")
    if "lethal" in tags:
        return ["決め手は見えています。落ち着いて処理します。", "盤面の圧を一つ減らします。"]
    if "danger" in tags:
        return ["苦しい場面ですが、次のターンを残します。", "今は崩れないことを優先します。"]
    if "potion" in tags:
        return ["温存よりも、この場面の解決を優先します。"]
    if "stabilize" in tags:
        return ["守りの形が整います。次の手番につなげます。"]
    if reason == "attack":
        return ["テンポを保って前に出ます。", "相手の体力を見ながら詰めます。"]
    if "choice" in tags:
        return ["次の展開を見据えた選択です。", "リスクと伸びしろを見比べます。"]
    if "skip" in tags:
        return ["余計なノイズを増やさない判断です。"]
    return ["流れを崩さず進めます。", "次の判断につながる一手です。"]


def _scene_lines(raw: dict[str, Any], command: str, context: dict[str, Any]) -> list[str]:
    state = raw.get("game_state") or {}
    if not isinstance(state, dict):
        return []
    combat = state.get("combat_state") or {}
    if isinstance(combat, dict) and combat and str(context.get("screen_type") or "").upper() in {"", "NONE"}:
        return _combat_scene_lines(state, command, context)
    screen_type = str(state.get("screen_type") or state.get("screen_name") or "").upper()
    if screen_type == "CARD_REWARD":
        return ["報酬選びです。ここでデッキを整えます！", "次の戦闘を見て選びます。"]
    if screen_type == "MAP":
        return ["ルート選択、勝負の分かれ目です。", "次の部屋はここへ進みます！"]
    if screen_type == "REST":
        return ["休憩所、ここは大事な判断。", "焚き火で立て直します。"]
    if screen_type == "SHOP_SCREEN":
        return ["買い物は勝ち筋づくりです。", "ここで必要なものだけ取ります！"]
    if screen_type == "EVENT":
        return ["イベント判断、リスクを見ます。", "ここは展開を見て選びます！"]
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
                lines.append(f"{card_name}で{monster_name}を仕留めます！")
            elif "block" in tags:
                lines.append(f"{card_name}でしっかり受けます！")
            elif "attack" in tags:
                lines.append(f"{card_name}、ここで押し込みます！")
            elif "setup" in tags:
                lines.append(f"{card_name}で次の形を作る。")
    if command.split(" ", 1)[0].upper() == "END":
        if "danger" in tags:
            lines.append("ターン終了です。被弾は覚悟します。")
        else:
            lines.append("やることはやりました。ターン終了です。")
    return lines


def _staged_cue_style(context: dict[str, Any]) -> dict[str, Any]:
    importance = max(1, min(int(context.get("importance") or 1), 3))
    return {
        "pace": "normal",
        "intensity": "normal",
        "priority": max(1, importance - 1),
        "queue_policy": "enqueue",
        "max_queue_ms": 6000,
    }


def _cue_style(context: dict[str, Any]) -> dict[str, Any]:
    tags = set(context.get("tags") or set())
    importance = int(context.get("importance") or 0)
    reason = str(context.get("reason") or "")

    if "victory" in tags:
        return {
            "pace": "fast",
            "intensity": "high",
            "priority": 8,
            "queue_policy": "replaceIfHigherPriority",
            "max_queue_ms": 1400,
        }
    if "terminal" in tags or reason in {"game_over", "max_floor"}:
        return {
            "pace": "slow" if reason == "game_over" else "normal",
            "intensity": "normal",
            "priority": 10 if reason == "game_over" else 7,
            "queue_policy": "replaceIfHigherPriority",
            "max_queue_ms": 3000,
        }
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
    if "card_pick" in tags:
        return {
            "pace": "normal",
            "intensity": "normal",
            "priority": 4,
            "queue_policy": "enqueue",
            "max_queue_ms": 3500,
        }
    if "reward" in tags:
        return {
            "pace": "fast",
            "intensity": "low",
            "priority": 1,
            "queue_policy": "dropIfBusy",
            "max_queue_ms": 750,
            "subtitle_only": True,
        }
    if reason == "attack" or "push" in tags:
        return {
            "pace": "normal" if reason == "attack" else "fast",
            "intensity": "normal",
            "priority": 3 if reason == "attack" else 5,
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


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean_spoken_line(value: str | None) -> str | None:
    if not value:
        return None
    text = " ".join(str(value).split()).strip()
    if not text:
        return None
    return sanitize_spoken_text(text)


def _clean_thought_line(value: str | None) -> str | None:
    if not value:
        return None
    text = " ".join(str(value).split()).strip()
    if not text:
        return None
    for english, spoken in sorted(SPOKEN_NAME_REPLACEMENTS.items(), key=lambda item: len(item[0]), reverse=True):
        text = re.sub(re.escape(english), spoken, text, flags=re.IGNORECASE)
    text = text.replace("/", "対").replace("_", "")
    text = re.sub(r"[A-Za-z][A-Za-z0-9' -]*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^[、。,. !！?？]+", "", text).strip()
    if len(text) > 90:
        text = text[:90].rstrip("、。,. ") + "。"
    return text or None


def _thought_conflicts_with_context(thought: str, command: str, context: dict[str, Any]) -> bool:
    verb = command.split(" ", 1)[0].upper()
    normalized = _normalize_for_repeat(thought)
    if verb == "PLAY" and any(word in normalized for word in ("終了", "使わず", "切らず", "温存")):
        return True
    if verb == "END" and any(word in normalized for word in ("使います", "攻撃", "倒して", "取ります")):
        return True
    if (
        verb == "END"
        and _safe_int(context.get("damage_gap")) > 0
        and _safe_int(context.get("block")) <= 0
        and any(word in normalized for word in ("防御を優先", "守りを優先", "受けを優先"))
    ):
        return True
    if verb == "POTION" and any(word in normalized for word in ("温存", "残します", "使わず")):
        return True
    if "block" in set(context.get("tags") or set()) and "防御は切らず" in normalized:
        return True
    return False


def _thought_for_context(raw: dict[str, Any], command: str, context: dict[str, Any]) -> str | None:
    reason = str(context.get("reason") or "")
    if reason == "combat_victory":
        return "戦闘勝利を報酬処理の前に区切りとして記録します。"
    if reason == "game_over":
        return "ラン終了時の状況を、停止前に短く振り返ります。"
    if reason == "max_floor":
        return "設定された停止地点に到達したため、進行を区切ります。"
    tags = set(context.get("tags") or set())
    if "lethal" in tags:
        return "敵を倒せる場面なので、勝ち筋を優先します。"
    if "danger" in tags:
        return "被弾が重い場面なので、次のターンを残す判断です。"
    if "map" in tags:
        return "休憩所、エリート、次の報酬を見てルートを選びます。"
    if "rest" in tags:
        return "現在の体力とデッキの出力を比べて、回復か強化を決めます。"
    if "card_select" in tags:
        return "山札の弱い引きを減らすか、重要札を伸ばすかを優先します。"
    if "card_pick" in tags or "deck_plan" in tags:
        return "現在の体力と次の部屋を見て、デッキ方針に合う価値があるかで選びます。"
    if "choice" in tags:
        return "現在の体力と次の部屋を見て、価値の高い選択を探します。"
    if command.split(" ", 1)[0].upper() in {"PROCEED", "CONFIRM", "LEAVE"}:
        return None
    return "盤面のリスクと次の展開を見て判断します。"


def _polite_spoken_text(text: str) -> str:
    replacements = {
        "いけーー": "いけます",
        "いけー": "いけます",
        "行こう": "行きましょう",
        "いこう": "いきましょう",
        "行く！": "行きます！",
        "いく！": "いきます！",
        "進むぞ！": "進みます！",
        "進むぞ": "進みます",
        "倒し切れ": "倒し切りましょう",
        "取り切る": "取り切ります",
        "受け切れる": "受け切れます",
        "まず削る": "まず削ります",
        "押し込む": "押し込みます",
        "選ぶ！": "選びます！",
        "取る！": "取ります！",
        "締める": "締めます",
        "作る。": "作ります。",
        "ターン終了。": "ターン終了です。",
        "覚悟です。": "覚悟します。",
        "チャンス！": "チャンスです！",
    }
    for before, after in replacements.items():
        text = text.replace(before, after)
    if text.endswith("だ！"):
        text = text[:-2] + "です！"
    if text.endswith("だ。"):
        text = text[:-2] + "です。"
    if text.endswith("ぞ！"):
        text = text[:-2] + "ます！"
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
        adjusted = _safe_int(monster.get("move_adjusted_damage"), -1)
        base = _safe_int(monster.get("move_base_damage"))
        damage = adjusted if adjusted > 0 else base
        hits = int(monster.get("move_hits") or 1)
        total += max(damage, 0) * max(hits, 1)
    return total


def _estimate_card_damage(card: dict[str, Any]) -> int:
    from . import engine

    return int(engine.estimate_card_damage(card))


def _estimate_card_damage_against(card: dict[str, Any], monster: dict[str, Any], player: dict[str, Any]) -> int:
    damage = _estimate_card_damage(card)
    damage += _power_amount(player, "Strength")
    if _has_power(player, "Weak"):
        damage = int(damage * 0.75)
    if _has_power(monster, "Vulnerable"):
        damage = int(damage * 1.5)
    return max(damage, 0)


def _estimate_card_block(card: dict[str, Any]) -> int:
    from . import engine

    return int(engine.estimate_card_block(card))


def _has_power(entity: dict[str, Any], name: str) -> bool:
    return _power_amount(entity, name) > 0


def _power_amount(entity: dict[str, Any], name: str) -> int:
    normalized_name = name.lower()
    for power in entity.get("powers") or []:
        if not isinstance(power, dict):
            continue
        power_name = str(power.get("name") or power.get("id") or "").lower()
        if power_name == normalized_name:
            return int(power.get("amount") or 1)
    return 0


def _has_relic(raw: dict[str, Any], name: str) -> bool:
    state = raw.get("game_state") or {}
    if not isinstance(state, dict):
        return False
    normalized_name = name.lower()
    for relic in state.get("relics") or []:
        if not isinstance(relic, dict):
            continue
        relic_name = str(relic.get("name") or relic.get("id") or "").lower()
        if relic_name == normalized_name:
            return True
    return False
