"""WebSocket client for the external narration runtime UI."""

from __future__ import annotations

import base64
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


@dataclass
class PendingUtterance:
    event: threading.Event
    status: str | None = None
    error: str | None = None


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

    def say(self, text: str, *, emotion: str = "normal", metadata: dict[str, Any] | None = None) -> str:
        text = text.strip()
        if not text:
            return "empty"
        if not self._ensure_connected():
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
            "interrupt": False,
            "metadata": metadata or {},
        }
        try:
            self._send_json(message)
        except OSError as error:
            logging.warning("narration send failed: %s", error)
            self._mark_disconnected()
            with self._pending_lock:
                self._pending.pop(utterance_id, None)
            return "send_failed"

        if not self.wait_for_completion:
            return "sent"

        if not pending.event.wait(self.timeout):
            with self._pending_lock:
                self._pending.pop(utterance_id, None)
            logging.warning("narration timed out id=%s", utterance_id)
            return "timeout"
        return pending.status or "completed"

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
        pending.event.set()

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
