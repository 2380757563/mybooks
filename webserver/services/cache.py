#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Small process-in-memory TTL cache, for read-mostly data that's cheap to
recompute but too hot to query on every request (home recommendations,
per-book social stats, ...). Not distributed -- fine given MyBooks' current
single-process deployment model (same assumption as MyReaderSyncService's WS
connection registry / per-uid locks). See plan/Social_Reading_Plan.md §4.1.
"""

import threading
import time
from typing import Callable, Dict, Tuple


class TTLCache:
    def __init__(self):
        self._store: Dict[str, Tuple[float, object]] = {}
        self._lock = threading.Lock()

    def get_or_set(self, key: str, ttl_seconds: float, loader: Callable[[], object]):
        now = time.monotonic()
        with self._lock:
            cached = self._store.get(key)
            if cached is not None and cached[0] > now:
                return cached[1]
        value = loader()
        with self._lock:
            self._store[key] = (now + ttl_seconds, value)
        return value

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
