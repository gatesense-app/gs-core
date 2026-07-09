"""
Realtime fan-out for live session updates (WebSockets).

The visitor pipeline runs in sync request handlers (FastAPI runs `def` endpoints
in a threadpool), but WebSocket sends are async and must happen on the app's
event loop. ConnectionManager bridges the two: `publish()` is safe to call from
sync code and schedules the async broadcast onto the loop captured at startup.

Connections are bucketed by society so a broadcast only reaches that tenant's
viewers; platform_admins (no society_id) subscribe to a wildcard bucket that
receives every society's events.
"""

import asyncio

from starlette.websockets import WebSocket


class ConnectionManager:
    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._by_society: dict[str, set[WebSocket]] = {}
        self._all: set[WebSocket] = set()  # platform_admin: every society

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Capture the running event loop so sync publish() can reach it."""
        self._loop = loop

    async def connect(self, ws: WebSocket, society_id: str | None) -> None:
        await ws.accept()
        if society_id:
            self._by_society.setdefault(str(society_id), set()).add(ws)
        else:
            self._all.add(ws)

    def disconnect(self, ws: WebSocket, society_id: str | None) -> None:
        if society_id:
            conns = self._by_society.get(str(society_id))
            if conns:
                conns.discard(ws)
                if not conns:
                    self._by_society.pop(str(society_id), None)
        else:
            self._all.discard(ws)

    async def _broadcast(self, society_id, payload: dict) -> None:
        targets = set(self._all) | set(self._by_society.get(str(society_id), set()))
        for ws in targets:
            try:
                await ws.send_json(payload)
            except Exception:
                # A failed send means the socket is gone; its disconnect handler
                # will remove it. Don't let one dead peer block the rest.
                pass

    def publish(self, society_id, payload: dict) -> None:
        """Sync-callable: schedule an async broadcast onto the app event loop."""
        if self._loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._broadcast(society_id, payload), self._loop)
        except RuntimeError:
            # Loop not running (e.g. during teardown) — drop the event.
            pass


manager = ConnectionManager()
