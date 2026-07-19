#!/usr/bin/env python3

import datetime
import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import scoped_session, sessionmaker

from webserver import models
from webserver.models import Item, Reader, Reading
from webserver.services.reading_stats_service import ReadingWriteBuffer


class TestReadingWriteBufferFlush(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        self.session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(self.session)
        models.Base.metadata.create_all(engine)
        self.session.execute(
            text("CREATE UNIQUE INDEX ux_readings_read ON readings (reader_id, book_id) WHERE action='read'")
        )
        reader = Reader()
        reader.id = 1
        reader.username = "u1"
        reader.total_reading_seconds = 0
        reader.download_count = 0
        self.session.add(reader)
        self.session.commit()
        self.buf = ReadingWriteBuffer()

    def tearDown(self):
        self.session.remove()

    def test_first_read_creates_row_and_bumps_item_visit_once(self):
        t0 = datetime.datetime(2026, 1, 1, 0, 0, 0)
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, t0)
        self.buf.flush()

        row = self.session.query(Reading).filter_by(reader_id=1, book_id=100, action=Reading.ACTION_READ).one()
        self.assertEqual(row.duration, 0)
        item = self.session.query(Item).filter_by(book_id=100).one()
        self.assertEqual(item.count_visit, 1)

        # Second heartbeat within the same session shouldn't bump count_visit again
        t1 = t0 + datetime.timedelta(seconds=5)
        self.buf.on_heartbeat(1, 100, Reading.PROTOCOL_APP, t1)
        self.buf.flush()

        row = self.session.query(Reading).filter_by(reader_id=1, book_id=100, action=Reading.ACTION_READ).one()
        self.assertEqual(row.duration, 5)
        item = self.session.query(Item).filter_by(book_id=100).one()
        self.assertEqual(item.count_visit, 1)  # not incremented twice

        reader = self.session.query(Reader).filter_by(id=1).one()
        self.assertEqual(reader.total_reading_seconds, 5)

    def test_download_and_push_events_both_bump_item_count_download(self):
        t0 = datetime.datetime(2026, 1, 1, 0, 0, 0)
        self.buf.on_event(1, 200, Reading.ACTION_DOWNLOAD, Reading.PROTOCOL_WEB, t0)
        self.buf.on_event(1, 200, Reading.ACTION_PUSH, Reading.PROTOCOL_DEVICE, t0)
        self.buf.flush()

        item = self.session.query(Item).filter_by(book_id=200).one()
        self.assertEqual(item.count_download, 2)  # download + push both count here

        reader = self.session.query(Reader).filter_by(id=1).one()
        self.assertEqual(reader.download_count, 1)  # Reader.download_count only counts real downloads

        rows = self.session.query(Reading).filter_by(reader_id=1, book_id=200).all()
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
