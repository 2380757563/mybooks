#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Reading/download/push activity tracking, feeding webserver.models.Reading and
the Reader.total_reading_seconds/download_count aggregates.

Writes never hit the DB synchronously — heartbeat()/record_download()/
record_push() only touch an in-process memory buffer; a periodic
tornado.ioloop.PeriodicCallback flushes it in one batched transaction.
See document/Reading_Stats_Design.md §3, §9, §11 for the full design.
"""

import datetime
import logging
import re
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import tornado.ioloop
from sqlalchemy import text, update

from webserver import loader
from webserver.models import Item, Reader, Reading
from webserver.services.reader_cache import ReaderStatsCache

CONF = loader.get_settings()

HEARTBEAT_MAX_GAP = datetime.timedelta(seconds=60)

# MyBooks 云端书籍的 book_hash 形如 "cloud-8502-epub"，8502 是 book_id；
# 不匹配这个格式的视为本地书籍，本轮不统计。
_CLOUD_BOOK_HASH_RE = re.compile(r"^cloud-(\d+)-[a-zA-Z0-9]+$")


def parse_book_id_from_hash(book_hash: Optional[str]) -> Optional[int]:
    if not book_hash:
        return None
    m = _CLOUD_BOOK_HASH_RE.match(book_hash)
    if not m:
        return None
    return int(m.group(1))


@dataclass
class _PendingSession:
    session_start: datetime.datetime
    last_seen: datetime.datetime
    protocol: str
    duration_delta: int = 0
    dirty: bool = False
    # 是否已经确认过 Item.count_visit 的首次阅读计数（只需要判定一次，成功 flush 后置 True）
    visit_counted: bool = False


@dataclass
class _PendingEvent:
    reader_id: int
    book_id: int
    action: str
    protocol: str
    now_utc: datetime.datetime


class ReadingWriteBuffer:
    """In-memory buffer for reading heartbeats / download / push events.

    Flushed periodically (see ReadingStatsService.start()) in a single DB
    transaction, to avoid one SQLite commit per heartbeat under load.
    """

    def __init__(self):
        self._sessions: Dict[Tuple[int, int], _PendingSession] = {}
        self._events: List[_PendingEvent] = []
        self._reader_seconds_delta: Dict[int, int] = {}
        self._reader_download_delta: Dict[int, int] = {}
        self._lock = threading.Lock()

    def on_heartbeat(self, reader_id: int, book_id: int, protocol: str, now_utc: datetime.datetime) -> None:
        with self._lock:
            key = (reader_id, book_id)
            session = self._sessions.get(key)
            if session is None:
                # First heartbeat this process has seen for this book; whether a
                # Reading(action=read) row already exists in the DB is resolved
                # by the upsert in flush(), not here.
                self._sessions[key] = _PendingSession(
                    session_start=now_utc, last_seen=now_utc, protocol=protocol, duration_delta=0, dirty=True
                )
                delta = 0
            elif (now_utc - session.last_seen) <= HEARTBEAT_MAX_GAP:
                delta = int((now_utc - session.last_seen).total_seconds())
                session.duration_delta += delta
                session.last_seen = now_utc
                session.protocol = protocol
            else:
                # Gap too large: treat as a new reading session on the same row.
                delta = 0
                session.session_start = now_utc
                session.last_seen = now_utc
                session.protocol = protocol
                session.dirty = True
            if delta:
                self._reader_seconds_delta[reader_id] = self._reader_seconds_delta.get(reader_id, 0) + delta

    def on_event(self, reader_id: int, book_id: int, action: str, protocol: str, now_utc: datetime.datetime) -> None:
        with self._lock:
            self._events.append(_PendingEvent(reader_id, book_id, action, protocol, now_utc))
            if action == Reading.ACTION_DOWNLOAD:
                self._reader_download_delta[reader_id] = self._reader_download_delta.get(reader_id, 0) + 1

    def flush(self) -> None:
        with self._lock:
            pending = []
            visit_check_keys = []
            for key, s in self._sessions.items():
                if s.duration_delta or s.dirty:
                    pending.append((key, s.session_start, s.duration_delta, s.last_seen, s.protocol))
                    if not s.visit_counted:
                        visit_check_keys.append(key)
            for s in self._sessions.values():
                s.duration_delta = 0
                s.dirty = False
            events_snapshot, self._events = self._events, []
            seconds_delta, self._reader_seconds_delta = self._reader_seconds_delta, {}
            download_delta, self._reader_download_delta = self._reader_download_delta, {}

        if not (pending or events_snapshot or seconds_delta or download_delta):
            return

        db = Reading._session()
        try:
            # Item.count_visit = 首次阅读次数：只在这本书对这个 reader 第一次真正落库
            # action=read 记录时才 +1，需要在 upsert 前查一次是否已存在。
            book_visit_delta: Dict[int, int] = {}
            for reader_id, book_id in visit_check_keys:
                exists = (
                    db.query(Reading.id)
                    .filter(Reading.reader_id == reader_id, Reading.book_id == book_id, Reading.action == Reading.ACTION_READ)
                    .first()
                )
                if exists is None:
                    book_visit_delta[book_id] = book_visit_delta.get(book_id, 0) + 1

            for (reader_id, book_id), session_start, duration_delta, last_seen, protocol in pending:
                db.execute(
                    text(
                        """
                        INSERT INTO readings (reader_id, book_id, action, protocol, start_time, duration, update_time)
                        VALUES (:reader_id, :book_id, 'read', :protocol, :start_time, :duration, :update_time)
                        ON CONFLICT(reader_id, book_id) WHERE action='read' DO UPDATE SET
                            duration = duration + excluded.duration,
                            update_time = excluded.update_time,
                            start_time = excluded.start_time,
                            protocol = excluded.protocol
                        """
                    ),
                    dict(
                        reader_id=reader_id,
                        book_id=book_id,
                        protocol=protocol,
                        start_time=session_start,
                        duration=duration_delta,
                        update_time=last_seen,
                    ),
                )

            # Item.count_download = 下载 + 推送新增的 Reading 事件行数（两者都算，见
            # document/Reading_Stats_Design.md 与后续澄清；Reader.download_count 仍只算真实下载）
            book_download_delta: Dict[int, int] = {}
            for evt in events_snapshot:
                db.add(Reading(evt.reader_id, evt.book_id, evt.action, evt.protocol, evt.now_utc))
                if evt.action in (Reading.ACTION_DOWNLOAD, Reading.ACTION_PUSH):
                    book_download_delta[evt.book_id] = book_download_delta.get(evt.book_id, 0) + 1

            for reader_id, delta in seconds_delta.items():
                db.execute(
                    update(Reader).where(Reader.id == reader_id).values(total_reading_seconds=Reader.total_reading_seconds + delta)
                )
            for reader_id, delta in download_delta.items():
                db.execute(update(Reader).where(Reader.id == reader_id).values(download_count=Reader.download_count + delta))

            for book_id in set(book_visit_delta) | set(book_download_delta):
                item = db.query(Item).filter(Item.book_id == book_id).one_or_none()
                if item is None:
                    item = Item()
                    item.book_id = book_id
                item.count_visit += book_visit_delta.get(book_id, 0)
                item.count_download += book_download_delta.get(book_id, 0)
                db.add(item)

            db.commit()
            if visit_check_keys:
                with self._lock:
                    for key in visit_check_keys:
                        session = self._sessions.get(key)
                        if session is not None:
                            session.visit_counted = True
        except Exception:
            db.rollback()
            logging.error("[reading_stats] flush failed, data kept for retry on next tick", exc_info=True)
            with self._lock:
                for (reader_id, book_id), session_start, duration_delta, last_seen, protocol in pending:
                    key = (reader_id, book_id)
                    session = self._sessions.get(key)
                    if session is not None:
                        session.duration_delta += duration_delta
                        session.dirty = True
                self._events = events_snapshot + self._events
                for reader_id, delta in seconds_delta.items():
                    self._reader_seconds_delta[reader_id] = self._reader_seconds_delta.get(reader_id, 0) + delta
                for reader_id, delta in download_delta.items():
                    self._reader_download_delta[reader_id] = self._reader_download_delta.get(reader_id, 0) + delta


class ReadingStatsService:
    """Public entry points used by sync_service/book.py/webdav/mcp."""

    _buffer = ReadingWriteBuffer()
    _periodic_callback: Optional[tornado.ioloop.PeriodicCallback] = None

    @classmethod
    def heartbeat(cls, reader_id: int, book_id: int, protocol: str) -> None:
        if not ReaderStatsCache().get_allow_statistic(reader_id):
            return
        cls._buffer.on_heartbeat(reader_id, book_id, protocol, datetime.datetime.utcnow())

    @classmethod
    def record_download(cls, reader_id: int, book_id: int, protocol: str) -> None:
        if not ReaderStatsCache().get_allow_statistic(reader_id):
            return
        cls._buffer.on_event(reader_id, book_id, Reading.ACTION_DOWNLOAD, protocol, datetime.datetime.utcnow())

    @classmethod
    def record_push(cls, reader_id: int, book_id: int, protocol: str) -> None:
        if not ReaderStatsCache().get_allow_statistic(reader_id):
            return
        cls._buffer.on_event(reader_id, book_id, Reading.ACTION_PUSH, protocol, datetime.datetime.utcnow())

    @classmethod
    def flush_now(cls) -> None:
        cls._buffer.flush()

    @classmethod
    def start(cls) -> None:
        if cls._periodic_callback is not None:
            return
        interval_ms = CONF.get("READING_STATS_FLUSH_INTERVAL_SEC", 5) * 1000
        cls._periodic_callback = tornado.ioloop.PeriodicCallback(cls.flush_now, interval_ms)
        cls._periodic_callback.start()
        logging.info("[reading_stats] ReadingStatsService started, flushing every %sms", interval_ms)

    @classmethod
    def stop(cls) -> None:
        if cls._periodic_callback is not None:
            cls._periodic_callback.stop()
            cls._periodic_callback = None
        cls.flush_now()
        logging.info("[reading_stats] ReadingStatsService stopped, final flush done")
