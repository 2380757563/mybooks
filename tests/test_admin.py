#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

from types import SimpleNamespace
from unittest import mock
from tests.test_main import TestWithUserLogin, setUpModule as init

def setUpModule():
    init()

class TestAdmin(TestWithUserLogin):
    def test_book_list(self):
        d = self.json("/api/admin/book/list?sort=id&num=10")
        self.assertEqual(d["err"], "ok")
        self.assertEqual(len(d["items"]), 10)


class TestAdminTrashBooks(TestWithUserLogin):
    def new_api(self):
        from tests.test_main import _app
        return _app.settings["legacy"].new_api

    def test_list_trash_books(self):
        entries = [
            SimpleNamespace(book_id=1, title="Book One", author="Author A", mtime=100.0),
            SimpleNamespace(book_id=2, title="Book Two", author="Author B", mtime=200.0),
        ]
        with mock.patch.object(self.new_api(), "list_trash_entries", return_value=(entries, [])):
            d = self.json("/api/admin/trash/books")
        self.assertEqual(d["err"], "ok")
        self.assertEqual(len(d["books"]), 2)
        # sorted by mtime desc: book_id=2 first
        self.assertEqual(d["books"][0]["book_id"], 2)
        self.assertEqual(d["books"][0]["title"], "Book Two")
        self.assertEqual(d["books"][0]["author"], "Author B")

    def test_restore_trash_books_requires_ids(self):
        d = self.json("/api/admin/trash/books/restore", method="POST", body="{}")
        self.assertEqual(d["err"], "params.error")

    def test_restore_trash_books_success(self):
        with mock.patch.object(self.new_api(), "move_book_from_trash", return_value=None) as m:
            d = self.json(
                "/api/admin/trash/books/restore",
                method="POST",
                body='{"book_ids": [1, 2]}',
            )
        self.assertEqual(d["err"], "ok")
        self.assertEqual(sorted(d["restored"]), [1, 2])
        self.assertEqual(m.call_count, 2)

    def test_restore_trash_books_partial_failure(self):
        def fake_restore(book_id):
            if book_id == 2:
                raise ValueError("A book with the id 2 already exists")

        with mock.patch.object(self.new_api(), "move_book_from_trash", side_effect=fake_restore):
            d = self.json(
                "/api/admin/trash/books/restore",
                method="POST",
                body='{"book_ids": [1, 2]}',
            )
        self.assertEqual(d["err"], "partial")
        self.assertEqual(d["restored"], [1])
        self.assertIn(2, [int(k) for k in d["failed"].keys()])

    def test_purge_trash_books_requires_ids(self):
        d = self.json("/api/admin/trash/books/purge", method="POST", body="{}")
        self.assertEqual(d["err"], "params.error")

    def test_purge_trash_books_success(self):
        with mock.patch.object(self.new_api(), "delete_trash_entry", return_value=None) as m:
            d = self.json(
                "/api/admin/trash/books/purge",
                method="POST",
                body='{"book_ids": [1]}',
            )
        self.assertEqual(d["err"], "ok")
        self.assertEqual(d["purged"], [1])
        m.assert_called_once_with(1, "b")
