import asyncio
import time
from typing import Dict, List, Any, Optional
from fastapi import WebSocket


class ConnectionManager:
    """Manages WebSocket connections and facilitates real-time broadcasting."""

    def __init__(self):
        # Maps job_id -> list of active WebSocket connections
        self.active_connections: Dict[str, List[WebSocket]] = {}
        # Buffer messages for jobs that don't have connected clients yet
        self._message_buffer: Dict[str, List[Dict[str, Any]]] = {}
        self._buffer_created: Dict[str, float] = {}  # job_id -> creation timestamp
        self._max_buffer = 500
        self._buffer_ttl = 3600  # 1 hour TTL in seconds
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        """Set the event loop to be used for thread-safe scheduling."""
        self._loop = loop

    async def connect(self, job_id: str, websocket: WebSocket):
        await websocket.accept()
        if job_id not in self.active_connections:
            self.active_connections[job_id] = []
        self.active_connections[job_id].append(websocket)
        # Replay buffered messages
        if job_id in self._message_buffer:
            buffered = self._message_buffer.pop(job_id)
            self._buffer_created.pop(job_id, None)
            for msg in buffered:
                try:
                    await websocket.send_json(msg)
                except Exception:
                    break

    def disconnect(self, job_id: str, websocket: WebSocket):
        if job_id in self.active_connections:
            if websocket in self.active_connections[job_id]:
                self.active_connections[job_id].remove(websocket)
            if not self.active_connections[job_id]:
                del self.active_connections[job_id]

    async def _send_json(self, job_id: str, message: Dict[str, Any]):
        """Internal async sender."""
        if job_id not in self.active_connections:
            # Buffer message for later replay
            if job_id not in self._message_buffer:
                self._message_buffer[job_id] = []
                self._buffer_created[job_id] = time.time()
            if len(self._message_buffer[job_id]) < self._max_buffer:
                self._message_buffer[job_id].append(message)
            return

        # Snapshot to avoid mutation during iteration
        connections = list(self.active_connections.get(job_id, []))
        dead_connections = []
        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.append(connection)

        for dead in dead_connections:
            self.disconnect(job_id, dead)

    def cleanup_expired_buffers(self):
        """Remove message buffers that have exceeded TTL."""
        now = time.time()
        expired = [
            jid for jid, ts in self._buffer_created.items()
            if now - ts > self._buffer_ttl
        ]
        for jid in expired:
            self._message_buffer.pop(jid, None)
            self._buffer_created.pop(jid, None)
        if expired:
            print(f"[WS] Cleaned up {len(expired)} expired message buffers")

    def broadcast(self, job_id: str, message: Dict[str, Any]):
        """Thread-safe broadcast method to be called from synchronous code."""
        if not self._loop:
            print(f"[WS] WARNING: No event loop set, message dropped for job {job_id}")
            return

        try:
            # Schedule the async _send_json on the main event loop
            asyncio.run_coroutine_threadsafe(self._send_json(job_id, message), self._loop)
        except Exception as e:
            print(f"[WS] ERROR broadcasting to job {job_id}: {e}")


# Global instance
ws_manager = ConnectionManager()
