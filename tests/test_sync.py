#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import asyncio
import json
import os
import shutil
import tempfile
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from tests.test_main import TestWithUserLogin, get_db, setUpModule as init, main
from webserver import models
from webserver.models import ReadingRecord
from webserver.services.sync_service import MyReaderSyncService


def setUpModule():
    init()


class TestSyncServiceStorage(unittest.TestCase):
    """Unit tests against sync_service directly (no HTTP), DB-backed storage on the
    shared test DB (see tests/test_main.py). Each test uses a uid/book_hash unique
    to itself to avoid cross-test interference, since the DB isn't reset per test."""

    def setUp(self):
        MyReaderSyncService._locks.clear()
        MyReaderSyncService._buffer._pending.clear()

    def test_push_then_pull_roundtrip(self):
        async def run():
            payload = {
                "books": [{
                    "id": "b1", "book_hash": "sync-hash1", "updated_at": 1000, "deleted_at": None,
                    "title": "Title 1", "author": "Author 1", "format": "EPUB",
                }],
            }
            result = await MyReaderSyncService.push(101, payload)
            self.assertEqual(len(result["books"]), 1)
            self.assertEqual(result["books"][0]["title"], "Title 1")

            pulled = MyReaderSyncService.pull(101, since=0, type_="books")
            self.assertEqual(len(pulled["books"]), 1)
            self.assertIsNone(pulled["notes"])
            self.assertIsNone(pulled["configs"])

            # records not newer than `since` are excluded
            pulled_none = MyReaderSyncService.pull(101, since=1000, type_="books")
            self.assertEqual(pulled_none["books"], [])

        asyncio.get_event_loop().run_until_complete(run())

    def test_records_land_in_reading_records_table_after_flush(self):
        async def run():
            await MyReaderSyncService.push(102, {
                "books": [{"id": "b1", "book_hash": "sync-hashA", "updated_at": 1, "title": "A"}],
                "configs": [{"id": "c1", "book_hash": "sync-hashA", "updated_at": 1, "progress": [1, 10]}],
                "notes": [{"id": "n1", "book_hash": "sync-hashA", "updated_at": 1, "note": "hi"}],
            })
            MyReaderSyncService.flush_now()

            db = ReadingRecord._session()
            rows = db.query(ReadingRecord).filter_by(reader_id=102, book_hash="sync-hashA").all()
            self.assertEqual({r.kind for r in rows}, {"books", "configs", "notes"})
            notes_row = next(r for r in rows if r.kind == "notes")
            self.assertEqual(notes_row.payload["note"], "hi")
            self.assertEqual(notes_row.payload["uid"], 102)  # uid 兜底补齐，见 push() 实现

        asyncio.get_event_loop().run_until_complete(run())

    def test_pull_is_visible_before_flush(self):
        async def run():
            await MyReaderSyncService.push(103, {"books": [{"id": "b1", "book_hash": "sync-hashB", "updated_at": 1}]})
            # not flushed yet -- must still be visible via the buffer overlay
            pulled = MyReaderSyncService.pull(103, since=0, type_="books")
            self.assertEqual(len(pulled["books"]), 1)

            db = ReadingRecord._session()
            self.assertIsNone(db.query(ReadingRecord).filter_by(reader_id=103, book_hash="sync-hashB").one_or_none())

        asyncio.get_event_loop().run_until_complete(run())

    def test_pull_scans_all_book_directories(self):
        async def run():
            await MyReaderSyncService.push(104, {"books": [{"id": "b1", "book_hash": "sync-hashC1", "updated_at": 1}]})
            await MyReaderSyncService.push(104, {"books": [{"id": "b2", "book_hash": "sync-hashC2", "updated_at": 1}]})
            pulled = MyReaderSyncService.pull(104, since=0, type_="books")
            self.assertEqual({r["book_hash"] for r in pulled["books"]}, {"sync-hashC1", "sync-hashC2"})

            # filtering by `book` only returns that book's record
            pulled_one = MyReaderSyncService.pull(104, since=0, type_="books", book_hash="sync-hashC1")
            self.assertEqual([r["book_hash"] for r in pulled_one["books"]], ["sync-hashC1"])

        asyncio.get_event_loop().run_until_complete(run())

    def test_last_write_wins_merge(self):
        async def run():
            await MyReaderSyncService.push(105, {"configs": [
                {"id": "c1", "book_hash": "sync-hashD", "updated_at": 100, "progress": [1, 100]},
            ]})
            # stale update (lower updated_at) must be ignored
            stale = await MyReaderSyncService.push(105, {"configs": [
                {"id": "c1", "book_hash": "sync-hashD", "updated_at": 50, "progress": [99, 100]},
            ]})
            self.assertEqual(stale["configs"][0]["progress"], [1, 100])

            # newer update overwrites
            fresh = await MyReaderSyncService.push(105, {"configs": [
                {"id": "c1", "book_hash": "sync-hashD", "updated_at": 200, "progress": [5, 100]},
            ]})
            self.assertEqual(fresh["configs"][0]["progress"], [5, 100])

        asyncio.get_event_loop().run_until_complete(run())

    def test_multiple_notes_per_book(self):
        async def run():
            await MyReaderSyncService.push(106, {"notes": [
                {"id": "n1", "book_hash": "sync-hashE", "updated_at": 10, "note": "first"},
                {"id": "n2", "book_hash": "sync-hashE", "updated_at": 10, "note": "second"},
            ]})
            pulled = MyReaderSyncService.pull(106, since=0, type_="notes")
            self.assertEqual({r["id"] for r in pulled["notes"]}, {"n1", "n2"})

        asyncio.get_event_loop().run_until_complete(run())

    def test_tombstone_visible_via_deleted_at(self):
        async def run():
            await MyReaderSyncService.push(107, {"notes": [
                {"id": "n1", "book_hash": "sync-hashF", "updated_at": 10, "deleted_at": None, "note": "hi"},
            ]})
            await MyReaderSyncService.push(107, {"notes": [
                {"id": "n1", "book_hash": "sync-hashF", "updated_at": 20, "deleted_at": 20, "note": "hi"},
            ]})
            pulled = MyReaderSyncService.pull(107, since=15, type_="notes")
            self.assertEqual(len(pulled["notes"]), 1)
            self.assertEqual(pulled["notes"][0]["deleted_at"], 20)

        asyncio.get_event_loop().run_until_complete(run())

    def test_per_user_isolation(self):
        async def run():
            await MyReaderSyncService.push(108, {"books": [{"id": "b1", "book_hash": "sync-hashG1", "updated_at": 1}]})
            await MyReaderSyncService.push(109, {"books": [{"id": "b2", "book_hash": "sync-hashG2", "updated_at": 1}]})
            self.assertEqual(len(MyReaderSyncService.pull(108, 0, "books")["books"]), 1)
            self.assertEqual(len(MyReaderSyncService.pull(109, 0, "books")["books"]), 1)

        asyncio.get_event_loop().run_until_complete(run())

    def test_concurrent_push_same_user_is_serialized(self):
        """push() must wait for an in-flight push for the same uid before reading/writing."""
        async def run():
            lock = MyReaderSyncService._get_lock(110)
            await lock.acquire()
            try:
                task = asyncio.ensure_future(MyReaderSyncService.push(110, {
                    "books": [{"id": "b1", "book_hash": "sync-hashH", "updated_at": 1}],
                }))
                await asyncio.sleep(0.05)
                self.assertFalse(task.done(), "push() must block while another holder owns the per-uid lock")
            finally:
                lock.release()

            result = await task
            self.assertEqual(len(result["books"]), 1)

        asyncio.get_event_loop().run_until_complete(run())

    def test_concurrent_push_different_books_does_not_lose_updates(self):
        """Two concurrent pushes for the same user touching different books must both land."""
        async def run():
            await asyncio.gather(
                MyReaderSyncService.push(111, {"books": [{"id": "b1", "book_hash": "sync-hashI1", "updated_at": 1}]}),
                MyReaderSyncService.push(111, {"books": [{"id": "b2", "book_hash": "sync-hashI2", "updated_at": 1}]}),
            )
            pulled = MyReaderSyncService.pull(111, since=0, type_="books")
            self.assertEqual({r["book_hash"] for r in pulled["books"]}, {"sync-hashI1", "sync-hashI2"})

        asyncio.get_event_loop().run_until_complete(run())

    def test_own_param_excludes_others_notes_by_default(self):
        async def run():
            book_hash = "cloud-90001-epub"
            await MyReaderSyncService.push(112, {"notes": [{"id": "n1", "book_hash": book_hash, "updated_at": 10, "note": "mine"}]})
            await MyReaderSyncService.push(113, {"notes": [{"id": "n2", "book_hash": book_hash, "updated_at": 10, "note": "theirs"}]})
            MyReaderSyncService.flush_now()

            own_only = MyReaderSyncService.pull(112, since=0, type_="notes", book_hash=book_hash, own=1)
            self.assertEqual({r["id"] for r in own_only["notes"]}, {"n1"})

        asyncio.get_event_loop().run_until_complete(run())

    def test_own_param_zero_includes_shared_notes_for_same_book(self):
        async def run():
            book_hash = "cloud-90002-epub"
            await MyReaderSyncService.push(114, {"notes": [{"id": "n1", "book_hash": book_hash, "updated_at": 10, "note": "mine"}]})
            await MyReaderSyncService.push(115, {"notes": [{"id": "n2", "book_hash": book_hash, "updated_at": 10, "note": "theirs"}]})
            MyReaderSyncService.flush_now()  # 跨用户 notes 走 DB 查询，需要先 flush

            shared = MyReaderSyncService.pull(114, since=0, type_="notes", book_hash=book_hash, own=0)
            self.assertEqual({r["id"] for r in shared["notes"]}, {"n1", "n2"})
            other_note = next(r for r in shared["notes"] if r["id"] == "n2")
            self.assertEqual(other_note["uid"], 115)

        asyncio.get_event_loop().run_until_complete(run())

    def test_own_param_zero_excludes_local_books_from_cross_user_query(self):
        async def run():
            book_hash = "local-file-not-cloud-format"
            await MyReaderSyncService.push(116, {"notes": [{"id": "n1", "book_hash": book_hash, "updated_at": 10, "note": "mine"}]})
            await MyReaderSyncService.push(117, {"notes": [{"id": "n2", "book_hash": book_hash, "updated_at": 10, "note": "theirs"}]})
            MyReaderSyncService.flush_now()

            shared = MyReaderSyncService.pull(116, since=0, type_="notes", book_hash=book_hash, own=0)
            # 本地书籍（book_id 为负数占位值）不参与跨用户匹配，即使传 own=0 也只看到自己的
            self.assertEqual({r["id"] for r in shared["notes"]}, {"n1"})

        asyncio.get_event_loop().run_until_complete(run())

    def test_shared_notes_disabled_by_setting(self):
        async def run():
            book_hash = "cloud-90003-epub"
            await MyReaderSyncService.push(118, {"notes": [{"id": "n1", "book_hash": book_hash, "updated_at": 10, "note": "mine"}]})
            await MyReaderSyncService.push(119, {"notes": [{"id": "n2", "book_hash": book_hash, "updated_at": 10, "note": "theirs"}]})
            MyReaderSyncService.flush_now()

            main.CONF["ENABLE_SHARED_NOTES"] = False
            try:
                shared = MyReaderSyncService.pull(118, since=0, type_="notes", book_hash=book_hash, own=0)
                self.assertEqual({r["id"] for r in shared["notes"]}, {"n1"})
            finally:
                main.CONF["ENABLE_SHARED_NOTES"] = True

        asyncio.get_event_loop().run_until_complete(run())


class TestLegacyMigration(unittest.TestCase):
    """Migration from <MYREADER_SYNC_PATH>/<uid>/<book_hash>/{kind}.json into
    reading_records, on an isolated in-memory DB (see tests/test_reading_stats_flush.py
    for the same pattern)."""

    def setUp(self):
        self._shared_session = get_db()
        engine = create_engine("sqlite://")
        self.session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(self.session)
        models.Base.metadata.create_all(engine)

        self._tmp_dir = tempfile.mkdtemp()
        main.CONF["MYREADER_SYNC_PATH"] = self._tmp_dir
        main.CONF["SYNC_LEGACY_MIGRATION_DONE"] = False
        MyReaderSyncService._locks.clear()
        MyReaderSyncService._buffer._pending.clear()

    def tearDown(self):
        self.session.remove()
        models.bind_session(self._shared_session)  # 恢复共享 app 的 DB 绑定，避免影响其它测试
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def _write_legacy_file(self, uid, book_hash, kind, data):
        book_dir = os.path.join(self._tmp_dir, str(uid), book_hash)
        os.makedirs(book_dir, exist_ok=True)
        with open(os.path.join(book_dir, f"{kind}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_migrates_all_three_kinds_and_removes_directories(self):
        self._write_legacy_file(201, "cloud-1-epub", "books", {
            "id": "b1", "book_hash": "cloud-1-epub", "updated_at": 1, "title": "A",
        })
        self._write_legacy_file(201, "cloud-1-epub", "configs", {
            "id": "c1", "book_hash": "cloud-1-epub", "updated_at": 1,
        })
        self._write_legacy_file(201, "cloud-1-epub", "notes", {
            "n1": {"id": "n1", "book_hash": "cloud-1-epub", "updated_at": 1, "note": "hi"},
        })

        MyReaderSyncService.migrate_legacy_data()

        rows = self.session.query(ReadingRecord).filter_by(reader_id=201).all()
        self.assertEqual({r.kind for r in rows}, {"books", "configs", "notes"})
        note_row = next(r for r in rows if r.kind == "notes")
        self.assertEqual(note_row.payload["uid"], 201)  # 迁移历史数据时补齐 uid
        book_row = next(r for r in rows if r.kind == "books")
        self.assertEqual(book_row.book_id, 1)  # 从 book_hash 提取的整型 book_id

        self.assertFalse(os.path.isdir(os.path.join(self._tmp_dir, "201")))
        self.assertTrue(main.CONF["SYNC_LEGACY_MIGRATION_DONE"])

    def test_no_dirs_marks_migration_done_immediately(self):
        MyReaderSyncService.migrate_legacy_data()
        self.assertTrue(main.CONF["SYNC_LEGACY_MIGRATION_DONE"])

    def test_migration_is_resumable_across_runs(self):
        self._write_legacy_file(202, "cloud-2-epub", "books", {
            "id": "b1", "book_hash": "cloud-2-epub", "updated_at": 5, "title": "X",
        })
        MyReaderSyncService.migrate_legacy_data()
        self.assertFalse(os.path.isdir(os.path.join(self._tmp_dir, "202")))

        # 新增一个"还没迁移"的目录（模拟迁移完成后又有旧文件残留/新用户目录出现），
        # 重新触发迁移应当只处理新增部分，此前已迁移的数据不受影响
        self._write_legacy_file(202, "cloud-3-epub", "books", {
            "id": "b2", "book_hash": "cloud-3-epub", "updated_at": 5, "title": "Y",
        })
        main.CONF["SYNC_LEGACY_MIGRATION_DONE"] = False
        MyReaderSyncService.migrate_legacy_data()

        rows = self.session.query(ReadingRecord).filter_by(reader_id=202).all()
        self.assertEqual({r.book_hash for r in rows}, {"cloud-2-epub", "cloud-3-epub"})

    def test_migration_keeps_newer_live_push_over_stale_legacy_file(self):
        """不停机迁移：迁移开始前，该用户已经通过新路径 push 了一条更新的数据，
        迁移不能用旧文件覆盖它（last-write-wins，见 plan §7.1 第 3 点）。"""
        async def push_live():
            await MyReaderSyncService.push(203, {
                "books": [{"id": "b1", "book_hash": "cloud-4-epub", "updated_at": 100, "title": "Live"}],
            })

        asyncio.get_event_loop().run_until_complete(push_live())
        MyReaderSyncService.flush_now()

        self._write_legacy_file(203, "cloud-4-epub", "books", {
            "id": "b1", "book_hash": "cloud-4-epub", "updated_at": 10, "title": "Stale",
        })
        MyReaderSyncService.migrate_legacy_data()

        row = self.session.query(ReadingRecord).filter_by(reader_id=203, book_hash="cloud-4-epub").one()
        self.assertEqual(row.payload["title"], "Live")


class TestSyncHandler(TestWithUserLogin):
    """Integration tests for GET/POST /api/sync over real HTTP, mocked user_id=1."""

    def setUp(self):
        super().setUp()
        main.CONF["ENABLE_DATA_SYNC"] = True
        MyReaderSyncService._locks.clear()
        MyReaderSyncService._buffer._pending.clear()

    def test_get_requires_since(self):
        d = self.json("/api/sync")
        self.assertEqual(d["err"], "params.invalid")

    def test_post_then_get(self):
        body = json.dumps({"books": [{
            "id": "b1", "book_hash": "http-hash1", "updated_at": 1000, "title": "T", "author": "A", "format": "EPUB",
        }]})
        d = self.json("/api/sync", method="POST", body=body)
        self.assertEqual(len(d["books"]), 1)

        d = self.json("/api/sync?since=0&type=books&book=http-hash1")
        self.assertEqual(len(d["books"]), 1)
        self.assertEqual(d["books"][0]["book_hash"], "http-hash1")

    def test_own_param_via_http(self):
        # own=1（默认）只看自己（uid=1，见 mock）；own=0 且 ENABLE_SHARED_NOTES=True 时
        # 还能看到其他用户对同一本书提交的 notes。
        book_hash = "cloud-90010-epub"
        asyncio.get_event_loop().run_until_complete(
            MyReaderSyncService.push(999, {"notes": [{"id": "nX", "book_hash": book_hash, "updated_at": 1, "note": "other"}]})
        )
        MyReaderSyncService.flush_now()

        d = self.json(f"/api/sync?since=0&type=notes&book={book_hash}&own=1")
        self.assertEqual(d["notes"], [])

        d = self.json(f"/api/sync?since=0&type=notes&book={book_hash}&own=0")
        self.assertEqual([r["id"] for r in d["notes"]], ["nX"])

    def test_disabled_feature_blocks_requests(self):
        main.CONF["ENABLE_DATA_SYNC"] = False
        d = self.json("/api/sync?since=0")
        self.assertEqual(d["err"], "sync.disabled")
