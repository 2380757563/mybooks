#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
In-process cache of Reader.allow_statistic, so the high-frequency reading
heartbeat/download/push paths don't have to hit SQLite on every event.
See document/Reading_Stats_Design.md §10.
"""

import logging
import threading
from typing import Dict

from webserver.services.async_service import SingletonType


class _RWLock:
    """Simple readers-writer lock: many concurrent readers, one exclusive writer.

    The project has no existing RWLock dependency (checked requirements.txt),
    only plain threading.Lock usage elsewhere (BaseHandler.db_lock,
    webdav/handler.py, etc.), so this is a small hand-rolled version instead
    of adding a new dependency for a single call site.
    """

    def __init__(self):
        self._read_ready = threading.Condition(threading.Lock())
        self._readers = 0

    def acquire_read(self):
        with self._read_ready:
            self._readers += 1

    def release_read(self):
        with self._read_ready:
            self._readers -= 1
            if self._readers == 0:
                self._read_ready.notify_all()

    def acquire_write(self):
        self._read_ready.acquire()
        while self._readers > 0:
            self._read_ready.wait()

    def release_write(self):
        self._read_ready.release()


class ReaderStatsCache(metaclass=SingletonType):
    """reader_id -> allow_statistic, lazily populated, updated by Reader.save()."""

    _cache: Dict[int, bool] = {}
    _lock = _RWLock()

    def get_allow_statistic(self, reader_id: int) -> bool:
        self._lock.acquire_read()
        try:
            if reader_id in self._cache:
                return self._cache[reader_id]
        finally:
            self._lock.release_read()

        value = self._load_from_db(reader_id)
        self.set_allow_statistic(reader_id, value)
        return value

    def set_allow_statistic(self, reader_id: int, value: bool) -> None:
        self._lock.acquire_write()
        try:
            self._cache[reader_id] = bool(value)
        finally:
            self._lock.release_write()

    def invalidate(self, reader_id: int) -> None:
        self._lock.acquire_write()
        try:
            self._cache.pop(reader_id, None)
        finally:
            self._lock.release_write()

    @staticmethod
    def _load_from_db(reader_id: int) -> bool:
        from webserver.models import Reader

        try:
            session = Reader._session()
            reader = session.query(Reader).filter(Reader.id == reader_id).one_or_none()
            return bool(reader.allow_statistic) if reader is not None else True
        except Exception:
            logging.warning("[reader_cache] failed to load allow_statistic for reader %s, default True", reader_id, exc_info=True)
            return True
