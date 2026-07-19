#!/usr/bin/env python3

import unittest

from webserver.services.reader_cache import ReaderStatsCache


class TestReaderStatsCache(unittest.TestCase):
    def setUp(self):
        self.cache = ReaderStatsCache()
        self.cache._cache.clear()

    def test_set_then_get_hits_cache_without_db(self):
        self.cache.set_allow_statistic(42, False)
        self.assertFalse(self.cache.get_allow_statistic(42))

    def test_default_true(self):
        self.cache.set_allow_statistic(1, True)
        self.assertTrue(self.cache.get_allow_statistic(1))

    def test_invalidate_removes_entry(self):
        self.cache.set_allow_statistic(7, False)
        self.cache.invalidate(7)
        self.assertNotIn(7, self.cache._cache)

    def test_is_singleton(self):
        self.assertIs(ReaderStatsCache(), self.cache)


if __name__ == "__main__":
    unittest.main()
