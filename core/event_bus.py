"""SSE Event Bus — 스레드 안전 pub/sub 시스템"""
import json
import queue
import threading
import time
from datetime import datetime


class EventBus:
    def __init__(self):
        self._subscribers: dict[str, queue.Queue] = {}
        self._lock = threading.Lock()

    def subscribe(self, client_id: str):
        with self._lock:
            self._subscribers[client_id] = queue.Queue(maxsize=500)

    def unsubscribe(self, client_id: str):
        with self._lock:
            self._subscribers.pop(client_id, None)

    def publish(self, event_type: str, data: dict, job_id: str = None):
        payload = {
            "type": event_type,
            "data": {**data, "job_id": job_id, "timestamp": datetime.now().isoformat()},
        }
        with self._lock:
            dead = []
            for cid, q in self._subscribers.items():
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    dead.append(cid)
            for cid in dead:
                self._subscribers.pop(cid, None)

    def listen(self, client_id: str):
        """Generator that yields SSE-formatted strings."""
        while True:
            try:
                q = self._subscribers.get(client_id)
                if q is None:
                    return
                payload = q.get(timeout=30)
                yield f"event: {payload['type']}\ndata: {json.dumps(payload['data'], ensure_ascii=False)}\n\n"
            except queue.Empty:
                yield ": heartbeat\n\n"
            except Exception:
                return


event_bus = EventBus()
