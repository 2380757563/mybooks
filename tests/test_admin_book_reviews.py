#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import json

from tests.test_main import BID_EPUB, BID_TXT, TestWithUserLogin, setUpModule as init, main
from webserver.services.book_review_service import BookReviewService


def setUpModule():
    init()


class TestAdminBookReviews(TestWithUserLogin):
    """`/api/admin/book-reviews`: 管理员分页列出所有评论 + 通过/屏蔽/恢复。Reader id=1（mocked
    current_user）在 fixture 库里是管理员，见 tests/test_main.py::TestWithAdminUser。"""

    def setUp(self):
        super().setUp()
        main.CONF["REVIEW_REQUIRES_APPROVAL"] = True
        BookReviewService.invalidate_stats(BID_EPUB)

    def tearDown(self):
        main.CONF["REVIEW_REQUIRES_APPROVAL"] = False
        super().tearDown()

    def test_list_filters_by_status(self):
        self.json("/api/book/%d/review" % BID_EPUB, method="POST", body=json.dumps({"rating": 8, "comment": "x"}))

        d = self.json("/api/admin/book-reviews?status=pending")
        self.assertGreaterEqual(d["total"], 1)
        self.assertTrue(all(r["status"] == "pending" for r in d["reviews"]))
        row = next(r for r in d["reviews"] if r["book_id"] == BID_EPUB)
        self.assertEqual(row["username"], "Rex")  # reader id=1 的用户名，见 tests/cases/users.db fixture

    def test_moderate_approve_hide_restore(self):
        d = self.json("/api/book/%d/review" % BID_TXT, method="POST", body=json.dumps({"rating": 5, "comment": ""}))
        review_id = d["review"]["id"]

        d = self.json("/api/admin/book-reviews", method="POST", body=json.dumps({"id": review_id, "action": "approve"}))
        self.assertEqual(d["err"], "ok")

        d = self.json("/api/admin/book-reviews", method="POST", body=json.dumps({"id": review_id, "action": "hide"}))
        self.assertEqual(d["err"], "ok")
        hidden = self.json("/api/admin/book-reviews?status=hidden")
        self.assertTrue(any(r["id"] == review_id for r in hidden["reviews"]))

        d = self.json("/api/admin/book-reviews", method="POST", body=json.dumps({"id": review_id, "action": "restore"}))
        self.assertEqual(d["err"], "ok")
        approved = self.json("/api/admin/book-reviews?status=approved")
        self.assertTrue(any(r["id"] == review_id for r in approved["reviews"]))

    def test_moderate_rejects_unknown_action(self):
        d = self.json("/api/book/%d/review" % BID_EPUB, method="POST", body=json.dumps({"rating": 5}))
        review_id = d["review"]["id"]
        d = self.json("/api/admin/book-reviews", method="POST", body=json.dumps({"id": review_id, "action": "bogus"}))
        self.assertEqual(d["err"], "params.invalid")


class TestAdminUserReviewBan(TestWithUserLogin):
    def test_toggle_review_banned(self):
        d = self.json("/api/admin/users", method="POST", body=json.dumps({"id": 2, "review_banned": True}))
        self.assertEqual(d["err"], "ok")

        d = self.json("/api/admin/users")
        user2 = next(u for u in d["users"]["items"] if u["id"] == 2)
        self.assertTrue(user2["review_banned"])

        d = self.json("/api/admin/users", method="POST", body=json.dumps({"id": 2, "review_banned": False}))
        self.assertEqual(d["err"], "ok")
        d = self.json("/api/admin/users")
        user2 = next(u for u in d["users"]["items"] if u["id"] == 2)
        self.assertFalse(user2["review_banned"])
