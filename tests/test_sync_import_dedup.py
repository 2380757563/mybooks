#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Pure-logic tests for the M2 dedup helpers in
webserver/services/sync_import_service.py (`_anchor_unchanged`,
`partition_for_dedup`, `build_note_records`'s createdAt/updatedAt split).

Deliberately independent of the DB/Tornado app (unlike test_sync_import.py)
— `partition_for_dedup` calls `_load_existing_by_source_id`, which is
monkeypatched here rather than exercised against a real `MyReaderSyncService`
DB session, so these can run (and did run, during development) even when
the app-level test harness is unavailable.
"""

import unittest
from unittest.mock import patch

from webserver.services import sync_import_service as svc


class TestAnchorUnchanged(unittest.TestCase):
    def test_same_text_is_unchanged(self):
        self.assertTrue(svc._anchor_unchanged({"text": "abc"}, {"cfi": "x", "text": "abc"}))

    def test_different_text_is_changed(self):
        self.assertFalse(svc._anchor_unchanged({"text": "abc"}, {"cfi": "x", "text": "def"}))

    def test_missing_cfi_on_existing_is_never_reused(self):
        # See the docstring on _anchor_unchanged: /api/sync's own POST has no
        # field whitelist, so a wxread-id note could theoretically exist
        # with no cfi at all. Must not be treated as reusable.
        self.assertFalse(svc._anchor_unchanged({"text": "abc"}, {"text": "abc"}))

    def test_degraded_anchor_compares_chapter_hint(self):
        self.assertTrue(svc._anchor_unchanged({"chapterHint": "ch1"}, {"cfi": "x", "text": "", "chapterHint": "ch1"}))
        self.assertFalse(svc._anchor_unchanged({"chapterHint": "ch2"}, {"cfi": "x", "text": "", "chapterHint": "ch1"}))

    def test_degraded_anchor_with_no_hint_stored_ignores_hint_change_only_if_both_empty(self):
        self.assertTrue(svc._anchor_unchanged({}, {"cfi": "x", "text": "", "chapterHint": ""}))


class TestPartitionForDedup(unittest.TestCase):
    def setUp(self):
        self.fake_existing = {
            "keep-1": {"cfi": "epubcfi(A)", "text": "same text", "type": "annotation"},
            "changed-1": {"cfi": "epubcfi(B)", "text": "old text", "type": "annotation"},
            "deg-keep": {"cfi": "epubcfi(C)", "text": "", "chapterHint": "ch1", "type": "bookmark"},
        }
        self.anchors = [
            {"id": "keep-1", "text": "same text"},
            {"id": "changed-1", "text": "new text"},
            {"id": "brand-new", "text": "never seen"},
            {"id": "deg-keep", "chapterHint": "ch1"},
        ]

    def test_splits_into_resolve_and_reuse(self):
        with patch.object(svc, "_load_existing_by_source_id", return_value=self.fake_existing):
            to_resolve, reused = svc.partition_for_dedup(uid=1, book_hash="cloud-1-epub", anchors=self.anchors)

        self.assertEqual([a["id"] for a in to_resolve], ["changed-1", "brand-new"])
        reused_by_id = {r["id"]: r for r in reused}
        self.assertEqual(reused_by_id["keep-1"]["cfi"], "epubcfi(A)")
        self.assertTrue(reused_by_id["keep-1"]["reused"])
        self.assertEqual(reused_by_id["deg-keep"]["cfi"], "epubcfi(C)")
        self.assertEqual(reused_by_id["deg-keep"]["degraded"], "chapter_start")

    def test_force_sends_everything_to_resolve(self):
        with patch.object(svc, "_load_existing_by_source_id", return_value=self.fake_existing) as mocked:
            to_resolve, reused = svc.partition_for_dedup(uid=1, book_hash="cloud-1-epub", anchors=self.anchors, force=True)

        self.assertEqual(to_resolve, self.anchors)
        self.assertEqual(reused, [])
        mocked.assert_not_called()  # force must skip the lookup entirely, not just ignore its result


class TestBuildNoteRecordsTimestamps(unittest.TestCase):
    def test_updated_at_is_wall_clock_not_pinned_to_created_at(self):
        # Regression: an earlier version pinned updatedAt/updated_at to the
        # same value as createdAt, which would make two re-imports of the
        # same anchor (e.g. with an edited note) compare equal forever under
        # sync_service.py's LWW merge instead of the later one winning.
        records = svc.build_note_records(
            "cloud-1-epub",
            [{"id": "x1", "text": "t", "createdAt": 1000}],
            [{"id": "x1", "status": "ok", "cfi": "epubcfi(Z)"}],
            uid=1,
        )
        self.assertEqual(records[0]["createdAt"], 1000)
        self.assertNotEqual(records[0]["updatedAt"], 1000)
        self.assertEqual(records[0]["updatedAt"], records[0]["updated_at"])

    def test_chapter_hint_is_stored_for_future_dedup_comparisons(self):
        records = svc.build_note_records(
            "cloud-1-epub",
            [{"id": "x1", "chapterHint": "第一章"}],
            [{"id": "x1", "status": "ok", "cfi": "epubcfi(Z)", "degraded": "chapter_start"}],
            uid=1,
        )
        self.assertEqual(records[0]["chapterHint"], "第一章")
        self.assertEqual(records[0]["type"], "bookmark")


if __name__ == "__main__":
    unittest.main()
