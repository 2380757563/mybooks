#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from tests.test_main import TestWithUserLogin, get_db, setUpModule as init, main
from webserver import models
from webserver.models import BookList, BookListBook, BookListLike, Reader
from webserver.services.booklist_service import BookListLimitExceeded, BookListService


def setUpModule():
    init()


class TestBookListService(unittest.TestCase):
    """Unit tests against BookListService directly, on an isolated in-memory DB
    (same pattern as tests/test_book_review.py)."""

    def setUp(self):
        self._shared_session = get_db()
        engine = create_engine("sqlite://")
        self.session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(self.session)
        models.Base.metadata.create_all(engine)

        r1, r2 = Reader(), Reader()
        r1.id, r1.username, r1.name = 1, "u1", "Alice"
        r2.id, r2.username, r2.name = 2, "u2", "Bob"
        self.session.add_all([r1, r2])
        self.session.commit()

    def tearDown(self):
        self.session.remove()
        models.bind_session(self._shared_session)

    def test_create_defaults(self):
        row = BookListService.create(self.session, reader_id=1, name="历史")
        self.assertEqual(row.color, BookList.DEFAULT_COLOR)
        self.assertFalse(row.is_public)
        self.assertEqual(row.book_count, 0)

    def test_create_rejects_invalid_color(self):
        row = BookListService.create(self.session, reader_id=1, name="历史", color="not-a-color")
        self.assertEqual(row.color, BookList.DEFAULT_COLOR)

    def test_create_enforces_per_user_limit(self):
        for i in range(BookList.MAX_PER_USER):
            BookListService.create(self.session, reader_id=1, name=f"list-{i}")
        with self.assertRaises(BookListLimitExceeded):
            BookListService.create(self.session, reader_id=1, name="one-too-many")
        # 另一个用户不受影响
        BookListService.create(self.session, reader_id=2, name="ok")

    def test_add_and_remove_books_maintains_count(self):
        row = BookListService.create(self.session, reader_id=1, name="历史")
        added = BookListService.add_books(self.session, row, [101, 102, 103])
        self.assertEqual(added, 3)
        self.assertEqual(row.book_count, 3)

        # 重复加入应幂等，不重复计数
        added_again = BookListService.add_books(self.session, row, [102, 104])
        self.assertEqual(added_again, 1)
        self.assertEqual(row.book_count, 4)

        self.assertTrue(BookListService.remove_book(self.session, row, 102))
        self.assertEqual(row.book_count, 3)
        self.assertFalse(BookListService.remove_book(self.session, row, 999))

    def test_book_order_desc_and_asc(self):
        row = BookListService.create(self.session, reader_id=1, name="历史")
        BookListService.add_books(self.session, row, [1])
        BookListService.add_books(self.session, row, [2])
        BookListService.add_books(self.session, row, [3])
        self.assertEqual(BookListService.list_book_ids(self.session, row.id, order="desc"), [3, 2, 1])
        self.assertEqual(BookListService.list_book_ids(self.session, row.id, order="asc"), [1, 2, 3])

    def test_toggle_like_and_like_count(self):
        row = BookListService.create(self.session, reader_id=1, name="历史", is_public=True)
        self.assertTrue(BookListService.toggle_like(self.session, row.id, reader_id=2))
        self.assertEqual(row.like_count, 1)
        self.assertTrue(BookListService.is_liked(self.session, row.id, 2))

        self.assertFalse(BookListService.toggle_like(self.session, row.id, reader_id=2))
        self.assertEqual(row.like_count, 0)
        self.assertFalse(BookListService.is_liked(self.session, row.id, 2))

    def test_list_liked_returns_only_liked_booklists(self):
        a = BookListService.create(self.session, reader_id=1, name="A", is_public=True)
        BookListService.create(self.session, reader_id=1, name="B", is_public=True)
        BookListService.toggle_like(self.session, a.id, reader_id=2)
        liked = BookListService.list_liked(self.session, reader_id=2)
        self.assertEqual([r.id for r in liked], [a.id])

    def test_delete_cascades_relations(self):
        row = BookListService.create(self.session, reader_id=1, name="历史", is_public=True)
        BookListService.add_books(self.session, row, [1, 2])
        BookListService.toggle_like(self.session, row.id, reader_id=2)

        BookListService.delete(self.session, row)
        self.assertIsNone(BookListService.get(self.session, row.id))
        self.assertEqual(self.session.query(BookListBook).filter_by(booklist_id=row.id).count(), 0)
        self.assertEqual(self.session.query(BookListLike).filter_by(booklist_id=row.id).count(), 0)

    def test_list_for_homepage_priority_sticky_then_liked_then_public(self):
        sticky = BookListService.create(self.session, reader_id=1, name="置顶", is_public=True)
        BookListService.set_sticky(self.session, sticky, True, sticky_order=0)

        liked = BookListService.create(self.session, reader_id=1, name="点赞", is_public=True)
        BookListService.toggle_like(self.session, liked.id, reader_id=2)

        BookListService.create(self.session, reader_id=1, name="公共1", is_public=True)
        BookListService.create(self.session, reader_id=1, name="公共2", is_public=True)

        result = BookListService.list_for_homepage(self.session, reader_id=2, limit=2)
        self.assertEqual([r.id for r in result], [sticky.id, liked.id])

    def test_list_for_homepage_anonymous_skips_liked_layer(self):
        sticky = BookListService.create(self.session, reader_id=1, name="置顶", is_public=True)
        BookListService.set_sticky(self.session, sticky, True, sticky_order=0)
        public2 = BookListService.create(self.session, reader_id=1, name="公共2", is_public=True)

        result = BookListService.list_for_homepage(self.session, reader_id=None, limit=2)
        self.assertEqual({r.id for r in result}, {sticky.id, public2.id})

    def test_booklists_containing_book(self):
        a = BookListService.create(self.session, reader_id=1, name="A")
        b = BookListService.create(self.session, reader_id=1, name="B")
        BookListService.add_books(self.session, a, [42])
        result = BookListService.booklists_containing_book(self.session, reader_id=1, book_id=42)
        self.assertEqual(result, {a.id})
        self.assertNotIn(b.id, result)


if __name__ == "__main__":
    main()
