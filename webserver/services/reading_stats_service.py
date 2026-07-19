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
    """跟踪一个 (reader_id, book_id) 当前"打开中"的 Reading(action=read) 天级行。

    current_date 标识现在缓冲的是哪一天的行；日期变化（跨天）或心跳间隔超过
    HEARTBEAT_MAX_GAP 都会重置为一行新的天级记录（duration_delta 清零、dirty=True）。
    """

    current_date: datetime.date
    session_start: datetime.datetime
    last_seen: datetime.datetime
    protocol: str
    duration_delta: int = 0
    dirty: bool = False
    # 是否已经确认过 Item.count_visit 的首次阅读计数（按 current_date 这一天判定一次，
    # 跨天/新开一行时会随 current_date 一起重置为 False）
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
        self._reader_push_delta: Dict[int, int] = {}
        self._lock = threading.Lock()

    def on_heartbeat(self, reader_id: int, book_id: int, protocol: str, now_utc: datetime.datetime) -> None:
        with self._lock:
            key = (reader_id, book_id)
            session = self._sessions.get(key)
            today = now_utc.date()
            # 三种情况都视为"开启一行新的天级记录"：从未见过这本书的心跳、日期跨天了、
            # 或者心跳间隔超过阈值（新的一次阅读会话）。跨天时丢弃这次心跳的 delta（最多
            # 相当于一个心跳周期的误差，可接受，见 document/Reading_Stats_Design.md §11.4）。
            is_new_bucket = session is None or session.current_date != today or (now_utc - session.last_seen) > HEARTBEAT_MAX_GAP
            if is_new_bucket:
                self._sessions[key] = _PendingSession(
                    current_date=today, session_start=now_utc, last_seen=now_utc, protocol=protocol, duration_delta=0, dirty=True
                )
                return
            delta = int((now_utc - session.last_seen).total_seconds())
            session.duration_delta += delta
            session.last_seen = now_utc
            session.protocol = protocol
            if delta:
                self._reader_seconds_delta[reader_id] = self._reader_seconds_delta.get(reader_id, 0) + delta

    def on_event(self, reader_id: int, book_id: int, action: str, protocol: str, now_utc: datetime.datetime) -> None:
        with self._lock:
            self._events.append(_PendingEvent(reader_id, book_id, action, protocol, now_utc))
            if action == Reading.ACTION_DOWNLOAD:
                self._reader_download_delta[reader_id] = self._reader_download_delta.get(reader_id, 0) + 1
            elif action == Reading.ACTION_PUSH:
                self._reader_push_delta[reader_id] = self._reader_push_delta.get(reader_id, 0) + 1

    def flush(self) -> None:
        with self._lock:
            pending = []  # (reader_id, book_id, date, session_start, duration_delta, last_seen, protocol)
            visit_check_keys = []  # (reader_id, book_id, date)
            for (reader_id, book_id), s in self._sessions.items():
                if s.duration_delta or s.dirty:
                    pending.append((reader_id, book_id, s.current_date, s.session_start, s.duration_delta, s.last_seen, s.protocol))
                    if not s.visit_counted:
                        visit_check_keys.append((reader_id, book_id, s.current_date))
            for s in self._sessions.values():
                s.duration_delta = 0
                s.dirty = False
            events_snapshot, self._events = self._events, []
            seconds_delta, self._reader_seconds_delta = self._reader_seconds_delta, {}
            download_delta, self._reader_download_delta = self._reader_download_delta, {}
            push_delta, self._reader_push_delta = self._reader_push_delta, {}

        if not (pending or events_snapshot or seconds_delta or download_delta or push_delta):
            return

        db = Reading._session()
        try:
            # Item.count_visit = 唯一打开次数：这本书对这个 reader 在这一天第一次真正
            # 落库 action=read 记录时才 +1（不同天再打开也各算一次），需要在 upsert
            # 前查一次这一天的行是否已存在。
            book_visit_delta: Dict[int, int] = {}
            for reader_id, book_id, date in visit_check_keys:
                exists = (
                    db.query(Reading.id)
                    .filter(
                        Reading.reader_id == reader_id,
                        Reading.book_id == book_id,
                        Reading.action == Reading.ACTION_READ,
                        Reading.date == date,
                    )
                    .first()
                )
                if exists is None:
                    book_visit_delta[book_id] = book_visit_delta.get(book_id, 0) + 1

            for reader_id, book_id, date, session_start, duration_delta, last_seen, protocol in pending:
                db.execute(
                    text(
                        """
                        INSERT INTO readings (reader_id, book_id, action, protocol, date, start_time, duration, update_time)
                        VALUES (:reader_id, :book_id, 'read', :protocol, :date, :start_time, :duration, :update_time)
                        ON CONFLICT(reader_id, book_id, date) WHERE action='read' DO UPDATE SET
                            duration = duration + excluded.duration,
                            update_time = excluded.update_time,
                            start_time = excluded.start_time,
                            protocol = excluded.protocol
                        """
                    ),
                    dict(
                        reader_id=reader_id,
                        book_id=book_id,
                        date=date,
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
            for reader_id, delta in push_delta.items():
                db.execute(update(Reader).where(Reader.id == reader_id).values(push_count=Reader.push_count + delta))

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
                    for reader_id, book_id, date in visit_check_keys:
                        session = self._sessions.get((reader_id, book_id))
                        # 只有 flush 期间没有再被心跳跨天/开新会话覆盖时才标记，
                        # 否则这个 date 对应的 bucket 已经不是当前打开的那个了。
                        if session is not None and session.current_date == date:
                            session.visit_counted = True
        except Exception:
            db.rollback()
            logging.error("[reading_stats] flush failed, data kept for retry on next tick", exc_info=True)
            with self._lock:
                for reader_id, book_id, date, session_start, duration_delta, last_seen, protocol in pending:
                    session = self._sessions.get((reader_id, book_id))
                    if session is not None and session.current_date == date:
                        session.duration_delta += duration_delta
                        session.dirty = True
                    # 否则这一天的 bucket 已经因为跨天/新会话被覆盖，这次失败的增量随之丢弃
                    # （见 document/Reading_Stats_Design.md §11.4，属于已知的、有界的近似误差）
                self._events = events_snapshot + self._events
                for reader_id, delta in seconds_delta.items():
                    self._reader_seconds_delta[reader_id] = self._reader_seconds_delta.get(reader_id, 0) + delta
                for reader_id, delta in download_delta.items():
                    self._reader_download_delta[reader_id] = self._reader_download_delta.get(reader_id, 0) + delta
                for reader_id, delta in push_delta.items():
                    self._reader_push_delta[reader_id] = self._reader_push_delta.get(reader_id, 0) + delta


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
