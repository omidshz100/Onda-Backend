import asyncio
from collections import defaultdict
from uuid import UUID

from fastapi import WebSocket


class RealtimeConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[UUID, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, user_id: UUID, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[user_id].add(websocket)

    async def disconnect(self, user_id: UUID, websocket: WebSocket) -> None:
        async with self._lock:
            connections = self._connections.get(user_id)
            if connections is None:
                return
            connections.discard(websocket)
            if not connections:
                self._connections.pop(user_id, None)

    async def send_to_users(self, user_ids: set[UUID], event: dict[str, object]) -> None:
        async with self._lock:
            targets = [
                (user_id, websocket)
                for user_id in user_ids
                for websocket in self._connections.get(user_id, set())
            ]
        stale: list[tuple[UUID, WebSocket]] = []
        for user_id, websocket in targets:
            try:
                await websocket.send_json(event)
            except RuntimeError:
                stale.append((user_id, websocket))
        for user_id, websocket in stale:
            await self.disconnect(user_id, websocket)


realtime_manager = RealtimeConnectionManager()
