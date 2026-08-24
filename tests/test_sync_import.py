#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Integration tests for `POST /api/sync/import` (plan/WeChatReading_Annotation_Import_Plan.md
§5.3), over real HTTP against the test library (mocked user_id=1).

`book_id=1` ("百年孤独 - 加西亚·马尔克斯") is the same fixture used by
tests/test_cfi_gen.py — it has an EPUB format and its known passages
(including the `<br>` hard-wrap regression case) are already characterized
there. `book_id=2` has only a TXT format, used for the no-epub-format path.
"""

import json

from tests.test_main import TestWithUserLogin, setUpModule as init, main
from webserver.services.sync_service import MyReaderSyncService

EPUB_BOOK_ID = 1
NO_EPUB_BOOK_ID = 2
UNIQUE_TEXT = "他手里拿着两大块磁铁，从一座农舍走到另一座农舍"
BR_WRAPPED_TEXT = "他手里拿着两大块磁铁，从一座农舍走到另一座农舍"  # same sentence, resolves across a mid-sentence <br>
OTHER_UNIQUE_TEXT = "满脸络腮胡子，手指瘦得象鸟的爪子"  # a different, also-unique passage in the same book


def setUpModule():
    init()


class TestSyncImportHandler(TestWithUserLogin):
    def setUp(self):
        super().setUp()
        main.CONF["ENABLE_DATA_SYNC"] = True
        MyReaderSyncService._locks.clear()
        MyReaderSyncService._buffer._pending.clear()

    def post_import(self, **body):
        return self.json("/api/sync/import", method="POST", body=json.dumps(body))

    # ---------------------------------------------------------- validation

    def test_missing_book_id_is_rejected(self):
        d = self.post_import(anchors=[{"id": "a1", "text": "x"}])
        self.assertEqual(d["err"], "params.invalid")

    def test_empty_anchors_is_rejected(self):
        d = self.post_import(book_id=EPUB_BOOK_ID, anchors=[])
        self.assertEqual(d["err"], "params.invalid")

    def test_anchor_without_id_is_rejected(self):
        d = self.post_import(book_id=EPUB_BOOK_ID, anchors=[{"text": "x"}])
        self.assertEqual(d["err"], "params.invalid")

    def test_invalid_on_ambiguous_is_rejected(self):
        d = self.post_import(book_id=EPUB_BOOK_ID, anchors=[{"id": "a1", "text": "x"}], on_ambiguous="whatever")
        self.assertEqual(d["err"], "params.invalid")

    def test_nonexistent_book_id(self):
        d = self.post_import(book_id=999999, anchors=[{"id": "a1", "text": "x"}])
        self.assertEqual(d["err"], "params.book.invalid")

    def test_book_without_epub_format(self):
        d = self.post_import(book_id=NO_EPUB_BOOK_ID, anchors=[{"id": "a1", "text": "x"}])
        self.assertEqual(d["err"], "book.no_epub")

    # -------------------------------------------------------------- preview

    def test_dry_run_default_does_not_write(self):
        d = self.post_import(book_id=EPUB_BOOK_ID, anchors=[{"id": "prev-1", "text": UNIQUE_TEXT}])
        self.assertEqual(d["dry_run"], True)
        self.assertEqual(d["results"][0]["status"], "ok")
        self.assertTrue(d["results"][0]["cfi"].startswith("epubcfi("))
        self.assertNotIn("pushed", d)

        book_hash = d["book_hash"]
        self.assertEqual(book_hash, f"cloud-{EPUB_BOOK_ID}-epub")
        MyReaderSyncService.flush_now()
        pulled = self.json(f"/api/sync?since=0&type=notes&book={book_hash}")
        self.assertEqual(pulled["notes"], [])

    def test_no_match_is_reported_not_errored(self):
        d = self.post_import(book_id=EPUB_BOOK_ID, anchors=[{"id": "nm-1", "text": "这段文字绝对不会出现在书里_zzz"}])
        self.assertEqual(d["results"][0]["status"], "no_match")

    def test_br_wrapped_sentence_still_resolves(self):
        d = self.post_import(book_id=EPUB_BOOK_ID, anchors=[{"id": "br-1", "text": BR_WRAPPED_TEXT}])
        self.assertEqual(d["results"][0]["status"], "ok")

    def test_no_anchor_text_degrades_to_chapter_start(self):
        d = self.post_import(book_id=EPUB_BOOK_ID, anchors=[{"id": "deg-1"}])
        self.assertEqual(d["results"][0]["status"], "ok")
        self.assertEqual(d["results"][0]["degraded"], "chapter_start")

    # --------------------------------------------------------------- commit

    def test_commit_writes_a_note_pullable_via_get_sync(self):
        d = self.post_import(
            book_id=EPUB_BOOK_ID,
            dry_run=False,
            anchors=[{"id": "commit-1", "text": UNIQUE_TEXT, "note": "这句话很有意思"}],
        )
        self.assertEqual(d["dry_run"], False)
        self.assertEqual(d["results"][0]["status"], "ok")
        self.assertEqual(len(d["pushed"]["notes"]), 1)
        pushed = d["pushed"]["notes"][0]
        self.assertEqual(pushed["id"], "wxread-commit-1")
        self.assertEqual(pushed["type"], "annotation")
        self.assertEqual(pushed["note"], "这句话很有意思")
        self.assertEqual(pushed["source"], "wxread")

        MyReaderSyncService.flush_now()
        pulled = self.json(f"/api/sync?since=0&type=notes&book={d['book_hash']}")
        self.assertEqual([n["id"] for n in pulled["notes"]], ["wxread-commit-1"])

    def test_id_already_prefixed_is_not_double_prefixed(self):
        d = self.post_import(book_id=EPUB_BOOK_ID, dry_run=False, anchors=[{"id": "wxread-already", "text": UNIQUE_TEXT}])
        self.assertEqual(d["pushed"]["notes"][0]["id"], "wxread-already")

    def test_ambiguous_anchor_is_not_committed(self):
        # The book title/running-header text repeats многократно across
        # new.epub-style books; use a passage this book repeats too — the
        # exact count doesn't matter, only that it's >1 and therefore never
        # written even with dry_run=False.
        d = self.post_import(book_id=EPUB_BOOK_ID, dry_run=False, anchors=[{"id": "amb-1", "text": "百年孤独"}])
        status = d["results"][0]["status"]
        if status == "ambiguous":
            self.assertEqual(d["pushed"]["notes"], [])
        else:
            # If this particular string happens to be unique in this fixture,
            # the test doesn't exercise what it's meant to — fail loudly
            # rather than silently pass.
            self.fail(f"expected an ambiguous match to set up this test, got status={status!r}")

    def test_degraded_chapter_bookmark_is_committed_as_bookmark_type(self):
        d = self.post_import(book_id=EPUB_BOOK_ID, dry_run=False, anchors=[{"id": "deg-commit-1"}])
        self.assertEqual(d["pushed"]["notes"][0]["type"], "bookmark")

    def test_rerunning_commit_is_idempotent(self):
        anchors = [{"id": "idem-1", "text": UNIQUE_TEXT}]
        first = self.post_import(book_id=EPUB_BOOK_ID, dry_run=False, anchors=anchors)
        second = self.post_import(book_id=EPUB_BOOK_ID, dry_run=False, anchors=anchors)
        self.assertEqual(first["pushed"]["notes"][0]["id"], second["pushed"]["notes"][0]["id"])

        MyReaderSyncService.flush_now()
        pulled = self.json(f"/api/sync?since=0&type=notes&book={first['book_hash']}")
        self.assertEqual(len([n for n in pulled["notes"] if n["id"] == "wxread-idem-1"]), 1)

    # ----------------------------------------------------------- dedup (M2)

    def test_unchanged_reimport_reuses_cfi_without_reresolving(self):
        anchor = {"id": "dedup-1", "text": UNIQUE_TEXT}
        first = self.post_import(book_id=EPUB_BOOK_ID, dry_run=False, anchors=[anchor])
        self.assertNotIn("reused", first["results"][0])  # first time: freshly resolved
        first_cfi = first["results"][0]["cfi"]

        second = self.post_import(book_id=EPUB_BOOK_ID, anchors=[anchor])  # dry_run default, doesn't matter for the read
        self.assertEqual(second["results"][0]["status"], "ok")
        self.assertTrue(second["results"][0]["reused"])
        self.assertEqual(second["results"][0]["cfi"], first_cfi)

    def test_changed_text_triggers_fresh_resolution_not_reuse(self):
        first = self.post_import(book_id=EPUB_BOOK_ID, dry_run=False, anchors=[{"id": "dedup-2", "text": UNIQUE_TEXT}])
        first_cfi = first["results"][0]["cfi"]

        # Same source id, but the highlighted text itself changed (e.g. the
        # user re-selected a different span on WeChat Reading) — must NOT
        # be treated as unchanged.
        second = self.post_import(book_id=EPUB_BOOK_ID, dry_run=False, anchors=[{"id": "dedup-2", "text": OTHER_UNIQUE_TEXT}])
        self.assertNotIn("reused", second["results"][0])
        self.assertNotEqual(second["results"][0]["cfi"], first_cfi)
        self.assertEqual(second["pushed"]["notes"][0]["text"], OTHER_UNIQUE_TEXT)

    def test_changed_note_reuses_cfi_but_updates_note_text(self):
        first = self.post_import(
            book_id=EPUB_BOOK_ID, dry_run=False, anchors=[{"id": "dedup-3", "text": UNIQUE_TEXT, "note": "第一次想法"}]
        )
        first_cfi = first["results"][0]["cfi"]

        # Same highlighted text, but the user edited their thought on the
        # source system — must reuse the cfi (no re-search) while still
        # picking up the new note text on commit.
        second = self.post_import(
            book_id=EPUB_BOOK_ID, dry_run=False, anchors=[{"id": "dedup-3", "text": UNIQUE_TEXT, "note": "改过的想法"}]
        )
        self.assertTrue(second["results"][0]["reused"])
        self.assertEqual(second["results"][0]["cfi"], first_cfi)
        self.assertEqual(second["pushed"]["notes"][0]["cfi"], first_cfi)
        self.assertEqual(second["pushed"]["notes"][0]["note"], "改过的想法")

    def test_force_bypasses_dedup(self):
        anchor = {"id": "dedup-4", "text": UNIQUE_TEXT}
        self.post_import(book_id=EPUB_BOOK_ID, dry_run=False, anchors=[anchor])

        forced = self.post_import(book_id=EPUB_BOOK_ID, anchors=[anchor], force=True)
        self.assertNotIn("reused", forced["results"][0])  # re-resolved despite being unchanged

    def test_invalid_force_is_rejected(self):
        d = self.post_import(book_id=EPUB_BOOK_ID, anchors=[{"id": "a1", "text": "x"}], force="yes")
        self.assertEqual(d["err"], "params.invalid")

    def test_dedup_unaffected_ambiguous_and_no_match_are_still_reresolved(self):
        # Neither of these ever gets committed, so there's never an existing
        # record to dedup against — every call re-resolves them. Not a very
        # interesting assertion beyond "doesn't crash", but documents the
        # expectation explicitly.
        anchors = [{"id": "amb-dedup-1", "text": "百年孤独"}, {"id": "nm-dedup-1", "text": "这段文字绝对不会出现在书里_zzz"}]
        first = self.post_import(book_id=EPUB_BOOK_ID, anchors=anchors)
        second = self.post_import(book_id=EPUB_BOOK_ID, anchors=anchors)
        self.assertEqual([r["status"] for r in first["results"]], [r["status"] for r in second["results"]])
        self.assertNotIn("reused", second["results"][0])
        self.assertNotIn("reused", second["results"][1])

    # ---------------------------------------------------------- clear (M2)

    def post_clear(self, **body):
        return self.json("/api/sync/import/clear", method="POST", body=json.dumps(body))

    def test_clear_missing_book_id_is_rejected(self):
        d = self.post_clear()
        self.assertEqual(d["err"], "params.invalid")

    def test_clear_nonexistent_book_id(self):
        d = self.post_clear(book_id=999999)
        self.assertEqual(d["err"], "params.book.invalid")

    def test_clear_tombstones_previously_imported_notes(self):
        self.post_import(
            book_id=EPUB_BOOK_ID, dry_run=False, anchors=[{"id": "clr-1", "text": UNIQUE_TEXT}, {"id": "clr-2"}]
        )
        cleared = self.post_clear(book_id=EPUB_BOOK_ID)
        self.assertEqual(cleared["book_hash"], f"cloud-{EPUB_BOOK_ID}-epub")
        self.assertEqual(cleared["cleared"], 2)

        MyReaderSyncService.flush_now()
        pulled = self.json(f"/api/sync?since=0&type=notes&book={cleared['book_hash']}")
        cleared_ids = {n["id"] for n in pulled["notes"] if n["id"] in ("wxread-clr-1", "wxread-clr-2")}
        self.assertEqual(cleared_ids, {"wxread-clr-1", "wxread-clr-2"})
        for n in pulled["notes"]:
            if n["id"] in cleared_ids:
                self.assertTrue(n.get("deleted_at"))

    def test_clear_on_book_with_no_imports_is_a_noop(self):
        d = self.post_clear(book_id=EPUB_BOOK_ID)
        self.assertEqual(d["cleared"], 0)

    def test_reimport_after_clear_is_treated_as_new_not_reused(self):
        anchor = {"id": "clr-reimport-1", "text": UNIQUE_TEXT}
        self.post_import(book_id=EPUB_BOOK_ID, dry_run=False, anchors=[anchor])
        self.post_clear(book_id=EPUB_BOOK_ID)
        MyReaderSyncService.flush_now()

        again = self.post_import(book_id=EPUB_BOOK_ID, dry_run=False, anchors=[anchor])
        self.assertNotIn("reused", again["results"][0])  # tombstoned -> not "existing" for dedup purposes
        self.assertFalse(again["pushed"]["notes"][0].get("deleted_at"))
