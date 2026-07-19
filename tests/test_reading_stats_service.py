#!/usr/bin/env python3

import datetime
import unittest

from webserver.models import Reading
from webserver.services.reading_stats_service import (
    HEARTBEAT_MAX_GAP,
    ReadingWriteBuffer,
    parse_book_id_from_hash,
)


class TestParseBookIdFromHash(unittest.TestCase):
    def test_cloud_hash_extracts_book_id(self):
        self.assertEqual(parse_book_id_from_hash("cloud-8502-epub"), 8502)

    def test_local_hash_returns_none(self):
        self.assertIsNone(parse_book_id_from_hash("a1b2c3d4e5f6"))

    def test_empty_or_none_returns_none(self):
        self.assertIsNone(parse_book_id_from_hash(None))
        self.assertIsNone(parse_book_id_from_hash(""))

    def test_malformed_cloud_prefix_returns_none(self):
        self.assertIsNone(parse_book_id_from_hash("cloud-notanumber-epub"))


class TestReadingWriteBuffer(unittest.TestCase):
    def setUp(self):
        self.buf = ReadingWriteBuffer()
        self.t0 = datetime.datetime(2026, 1, 1, 0, 0, 0)

    def test_first_heartbeat_creates_dirty_session_with_zero_delta(self):
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, self.t0)
        session = self.buf._sessions[(1, 100)]
        self.assertEqual(session.duration_delta, 0)
        self.assertTrue(session.dirty)
        self.assertEqual(session.session_start, self.t0)
        self.assertEqual(self.buf._reader_seconds_delta, {})

    def test_heartbeat_within_gap_accumulates_duration(self):
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, self.t0)
        t1 = self.t0 + datetime.timedelta(seconds=3)
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, t1)
        session = self.buf._sessions[(1, 100)]
        self.assertEqual(session.duration_delta, 3)
        self.assertEqual(session.session_start, self.t0)  # same session, start unchanged
        self.assertEqual(self.buf._reader_seconds_delta[1], 3)

    def test_heartbeat_beyond_gap_starts_new_session_without_duration(self):
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, self.t0)
        t_gap = self.t0 + HEARTBEAT_MAX_GAP + datetime.timedelta(seconds=1)
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, t_gap)
        session = self.buf._sessions[(1, 100)]
        self.assertEqual(session.duration_delta, 0)
        self.assertEqual(session.session_start, t_gap)  # new session start
        self.assertTrue(session.dirty)
        self.assertNotIn(1, self.buf._reader_seconds_delta)

    def test_flush_snapshot_clears_pending_but_keeps_session_state(self):
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, self.t0)
        t1 = self.t0 + datetime.timedelta(seconds=5)
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, t1)
        with self.buf._lock:
            pending = [
                (key, s.session_start, s.duration_delta, s.last_seen, s.protocol)
                for key, s in self.buf._sessions.items()
                if s.duration_delta or s.dirty
            ]
            for s in self.buf._sessions.values():
                s.duration_delta = 0
                s.dirty = False
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0][2], 5)
        session = self.buf._sessions[(1, 100)]
        self.assertEqual(session.duration_delta, 0)
        self.assertFalse(session.dirty)
        self.assertEqual(session.session_start, self.t0)  # session identity survives flush

    def test_download_event_increments_reader_download_delta(self):
        self.buf.on_event(1, 100, Reading.ACTION_DOWNLOAD, Reading.PROTOCOL_WEB, self.t0)
        self.buf.on_event(1, 200, Reading.ACTION_DOWNLOAD, Reading.PROTOCOL_OPDS, self.t0)
        self.assertEqual(self.buf._reader_download_delta[1], 2)
        self.assertEqual(len(self.buf._events), 2)

    def test_push_event_does_not_affect_download_delta(self):
        self.buf.on_event(1, 100, Reading.ACTION_PUSH, Reading.PROTOCOL_DEVICE, self.t0)
        self.assertNotIn(1, self.buf._reader_download_delta)
        self.assertEqual(len(self.buf._events), 1)


if __name__ == "__main__":
    unittest.main()
