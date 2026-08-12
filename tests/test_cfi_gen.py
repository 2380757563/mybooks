#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
M0 spike coverage for webserver/services/cfi_gen/ — see
plan/WeChatReading_Annotation_Import_Plan.md §4.3/§8. Pure round-trip checks
against launcher.generate_cfis(): given real EPUB fixtures already in
tests/cases/, do known passages resolve to the right CFI, does an unknown
passage come back no_match, and do the tombstone/chapter-fallback paths
behave. This does not touch HTTP handlers, the DB, or `/api/sync` — that's
covered separately once §5.3's `/api/sync/import` lands.
"""

import asyncio
import os
import unittest

from webserver.services.cfi_gen.launcher import CfiBatchError, generate_cfis

TESTDIR = os.path.dirname(os.path.abspath(__file__))
OLD_EPUB = os.path.join(TESTDIR, "cases", "old.epub")
NEW_EPUB = os.path.join(TESTDIR, "cases", "new.epub")
# A Calibre-converted book that hard-wraps every printed line with
# `<br class="calibre1"/>` mid-sentence — see the BLOCK_TAGS/`<br>` comment
# in cfi_batch.mjs. Used specifically to lock in that behavior.
HUNDRED_YEARS_EPUB = os.path.join(TESTDIR, "library", "加西亚·马尔克斯", "百年孤独 (1)", "百年孤独 - 加西亚·马尔克斯.epub")


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestCfiBatchGenerator(unittest.TestCase):
    def test_unique_text_match_produces_a_cfi(self):
        anchors = [{"id": "a1", "text": "献给在二十世纪后半叶中国大地上默默苦行的民间英雄"}]
        results = run(generate_cfis(OLD_EPUB, anchors))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "a1")
        self.assertEqual(results[0]["status"], "ok")
        self.assertTrue(results[0]["cfi"].startswith("epubcfi("))
        self.assertEqual(results[0].get("matchCount"), 1)

    def test_no_match_for_text_not_in_book(self):
        anchors = [{"id": "a2", "text": "这段文字绝对不会出现在任何一本书里_zzz_不存在"}]
        results = run(generate_cfis(OLD_EPUB, anchors))
        self.assertEqual(results[0]["status"], "no_match")

    def test_whitespace_normalization_still_matches(self):
        # new.epub's chapter body has "...形状各异。 骄阳悬空..." (a single
        # space after the sentence-ending period, straight from the source
        # XHTML). Feeding an anchor with different whitespace there still has
        # to match after normalization — both sides collapse whitespace runs
        # to a single space (§4.4) — so this exercises that path against a
        # real, already-whitespace-containing passage instead of one we've
        # artificially split.
        anchors = [{"id": "a3", "text": "形状各异。  \n 骄阳悬空，炙烤着大地"}]
        results = run(generate_cfis(NEW_EPUB, anchors))
        self.assertEqual(results[0]["status"], "ok")

    def test_no_anchor_falls_back_to_whole_book_start(self):
        # No `text`, no `chapterHint` -> whole-book review, pinned to the
        # very first spine item (plan §4.5).
        anchors = [{"id": "a4"}]
        results = run(generate_cfis(OLD_EPUB, anchors))
        self.assertEqual(results[0]["status"], "ok")
        self.assertEqual(results[0].get("degraded"), "chapter_start")

    def test_batch_is_one_process_for_multiple_anchors(self):
        # Not a strict process-count assertion (that would require mocking
        # asyncio.create_subprocess_exec), but a same-order/same-length
        # sanity check that one generate_cfis() call handles a mixed batch.
        anchors = [
            {"id": "b1", "text": "献给在二十世纪后半叶中国大地上默默苦行的民间英雄"},
            {"id": "b2", "text": "这段文字绝对不会出现在任何一本书里_zzz_不存在"},
            {"id": "b3"},
        ]
        results = run(generate_cfis(OLD_EPUB, anchors))
        self.assertEqual([r["id"] for r in results], ["b1", "b2", "b3"])
        self.assertEqual(results[0]["status"], "ok")
        self.assertEqual(results[1]["status"], "no_match")
        self.assertEqual(results[2]["status"], "ok")

    def test_second_fixture_book_also_resolves(self):
        anchors = [{"id": "c1", "text": "除了杂草灌木，便是随处可见的灰白色石头，大小不一，形状各异。"}]
        results = run(generate_cfis(NEW_EPUB, anchors))
        self.assertEqual(results[0]["status"], "ok")

    def test_repeated_text_is_ambiguous_by_default(self):
        # The book title shows up 5 times within <body> content across
        # new.epub (running header/footer-style repetition, common in real
        # EPUBs — two more occurrences sit in <title> elements in <head>,
        # correctly excluded since that's never visible reading content).
        # This is the ≥2-hit case from plan §4.5, not a bug.
        anchors = [{"id": "e1", "text": "凡人修仙之仙界篇"}]
        results = run(generate_cfis(NEW_EPUB, anchors))
        self.assertEqual(results[0]["status"], "ambiguous")
        self.assertEqual(results[0]["matchCount"], 5)

    def test_on_ambiguous_first_match_picks_one_deterministically(self):
        anchors = [{"id": "e2", "text": "凡人修仙之仙界篇"}]
        results = run(generate_cfis(NEW_EPUB, anchors, on_ambiguous="first_match"))
        self.assertEqual(results[0]["status"], "ok")
        self.assertEqual(results[0]["matchCount"], 5)
        self.assertEqual(results[0]["ambiguousResolution"], "first_match")

    def test_missing_epub_raises_whole_book_error_not_no_match(self):
        anchors = [{"id": "d1", "text": "无所谓"}]
        with self.assertRaises(CfiBatchError):
            run(generate_cfis("/no/such/file.epub", anchors))

    def test_empty_anchors_short_circuits_without_spawning_node(self):
        self.assertEqual(run(generate_cfis(OLD_EPUB, [])), [])

    def test_br_hard_wrap_mid_sentence_does_not_break_the_match(self):
        # Regression test for a real bug found while building this pipeline:
        # this book's source XHTML has
        #   "...从一座农舍走到另<br class="calibre1"/>一座农舍..."
        # — a mid-clause line-wrap `<br>`, not a real break. An anchor with
        # the sentence written normally (no gap where the `<br>` sits) must
        # still match; if `<br>` were treated like a block-level boundary
        # (inserting a separator) this would wrongly become a no_match. See
        # the BLOCK_TAGS/`<br>` comment in cfi_batch.mjs for the full story.
        if not os.path.exists(HUNDRED_YEARS_EPUB):
            self.skipTest("library fixture not present in this checkout")
        anchors = [{"id": "f1", "text": "他手里拿着两大块磁铁，从一座农舍走到另一座农舍"}]
        results = run(generate_cfis(HUNDRED_YEARS_EPUB, anchors))
        self.assertEqual(results[0]["status"], "ok")
        self.assertEqual(results[0]["matchCount"], 1)


if __name__ == "__main__":
    unittest.main()
