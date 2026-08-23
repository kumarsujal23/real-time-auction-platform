"""
WebSocket connection manager backed by Redis Pub/Sub.

Why Redis is in the loop at all: a naive in-process manager (a dict of
auction_id -> set[WebSocket]) only works if there's exactly one backend
process. The moment you run two+ uvicorn workers (or two containers) behind
a load balancer, a bid handled by worker A never reaches a buyer whose
socket is held by worker B.

The fix: every backend instance keeps only its *local* sockets in memory,
but instead of writing to them directly, publishes the event to a Redis
channel named after the auction. Every instance also subscribes to that
channel and fans out to whichever local sockets it owns. This makes the
in-memory dict correct again because "all sockets for this auction, across
all instances" collapses into "all sockets for this auction, on this
instance, triggered by a Redis message" - which is exactly what a single
instance would have done anyway.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict

import redis.asyncio as aioredis
from fastapi import WebSocket

from app.core.config import settings

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self, redis_url: str = settings.REDIS_URL) -> None:
        self._redis_url = redis_url
        # auction_id (str) -> set of live local sockets watching it
        self._local_connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._redis: aioredis.Redis | None = None
        self._pubsub: aioredis.client.PubSub | None = None
        # one asyncio task per auction_id currently being listened to
        self._listener_tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    def _channel(self, auction_id: str) -> str:
        return f"{settings.REDIS_BID_CHANNEL_PREFIX}{auction_id}"

    async def connect(self) -> None:
        if self._redis is None:
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)

    async def disconnect(self) -> None:
        for task in self._listener_tasks.values():
            task.cancel()
        self._listener_tasks.clear()
        if self._redis:
            await self._redis.close()
            self._redis = None

    async def register(self, auction_id: str, websocket: WebSocket) -> None:
        """Attach a socket to an auction room and ensure a Redis listener
        exists for that room on this instance."""
        await websocket.accept()
        async with self._lock:
            self._local_connections[auction_id].add(websocket)
            if auction_id not in self._listener_tasks:
                self._listener_tasks[auction_id] = asyncio.create_task(
                    self._listen(auction_id)
                )

    async def unregister(self, auction_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            conns = self._local_connections.get(auction_id)
            if conns and websocket in conns:
                conns.discard(websocket)
            if conns is not None and not conns:
                task = self._listener_tasks.pop(auction_id, None)
                if task:
                    task.cancel()
                self._local_connections.pop(auction_id, None)

    async def publish(self, auction_id: str, message: dict) -> None:
        """Publish an event so every backend instance (including this one)
        broadcasts it to its local sockets. This is the ONLY way bid_service
        / the worker should push live updates - never write to sockets
        directly, or multi-instance deployments silently break."""
        await self.connect()
        assert self._redis is not None
        await self._redis.publish(self._channel(auction_id), json.dumps(message, default=str))

    async def _listen(self, auction_id: str) -> None:
        await self.connect()
        assert self._redis is not None
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(self._channel(auction_id))
        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                await self._broadcast_local(auction_id, message["data"])
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(self._channel(auction_id))
            await pubsub.close()

    async def _broadcast_local(self, auction_id: str, raw_data: str) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._local_connections.get(auction_id, set())):
            try:
                await ws.send_text(raw_data)
            except Exception:  # noqa: BLE001 - socket may already be closed
                dead.append(ws)
        for ws in dead:
            await self.unregister(auction_id, ws)


# One process-wide singleton, imported wherever a broadcast needs to happen.
connection_manager = ConnectionManager()
