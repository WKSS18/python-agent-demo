"""Minimal two-person WebRTC signaling rooms.

Audio stays peer-to-peer; this process only forwards offer/answer/ICE messages.
Rooms are intentionally in-memory for the first version and expire on restart.
"""
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import WebSocket


@dataclass
class VoiceRoom:
    room_id: str
    owner_id: int
    note_id: int
    expires_at: datetime
    peers: dict[int, WebSocket] = field(default_factory=dict)
    peer_names: dict[int, str] = field(default_factory=dict)


ROOMS: dict[str, VoiceRoom] = {}


def create_room(owner_id: int, note_id: int) -> VoiceRoom:
    room = VoiceRoom(
        room_id=uuid4().hex[:12], owner_id=owner_id, note_id=note_id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    ROOMS[room.room_id] = room
    return room


def get_room(room_id: str) -> VoiceRoom | None:
    room = ROOMS.get(room_id)
    if not room or room.expires_at <= datetime.now(UTC):
        ROOMS.pop(room_id, None)
        return None
    return room


async def broadcast(room: VoiceRoom, sender_id: int, payload: dict) -> None:
    for peer_id, socket in list(room.peers.items()):
        if peer_id != sender_id:
            await socket.send_json(payload)
