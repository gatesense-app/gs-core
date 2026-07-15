"""
Realtime fan-out for live session updates (WebSockets).

The visitor pipeline runs in sync request handlers (FastAPI runs `def` endpoints
in a threadpool), but WebSocket sends are async and must happen on the app's
event loop. ConnectionManager bridges the two: `publish()` is safe to call from
sync code and schedules the async broadcast onto the loop captured at startup.

Connections are bucketed so a broadcast only reaches who may see it:
  - staff (guard / society_admin) -> per-society bucket, see the whole society
  - platform_admin (no society_id) -> wildcard bucket, sees every society
  - resident -> per-(society, flat) bucket, sees only their own flat

The resident bucket mirrors the HTTP rule (main._assert_flat_access): RLS scopes
to the society, but a resident must never see a neighbour's visitor.
"""

import asyncio

from starlette.websockets import WebSocket


class ConnectionManager:
    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._by_society: dict[str, set[WebSocket]] = {}
        self._all: set[WebSocket] = set()  # platform_admin: every society
        self._by_flat: dict[tuple[str, str], set[WebSocket]] = {}  # residents

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Capture the running event loop so sync publish() can reach it."""
        self._loop = loop

    async def connect(self, ws: WebSocket, society_id: str | None, flat_number: str | None = None) -> None:
        await ws.accept()
        if flat_number and society_id:
            self._by_flat.setdefault((str(society_id), flat_number), set()).add(ws)
        elif society_id:
            self._by_society.setdefault(str(society_id), set()).add(ws)
        else:
            self._all.add(ws)

    def disconnect(self, ws: WebSocket, society_id: str | None, flat_number: str | None = None) -> None:
        if flat_number and society_id:
            key = (str(society_id), flat_number)
            conns = self._by_flat.get(key)
            if conns:
                conns.discard(ws)
                if not conns:
                    self._by_flat.pop(key, None)
        elif society_id:
            conns = self._by_society.get(str(society_id))
            if conns:
                conns.discard(ws)
                if not conns:
                    self._by_society.pop(str(society_id), None)
        else:
            self._all.discard(ws)

    async def _broadcast(self, society_id, payload: dict) -> None:
        targets = set(self._all) | set(self._by_society.get(str(society_id), set()))
        # Residents only hear about their own flat.
        flat = (payload.get("session") or {}).get("flat_number")
        if flat:
            targets |= self._by_flat.get((str(society_id), flat), set())
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
