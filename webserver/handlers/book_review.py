#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
`/api/book/:id/review`, `/api/book/:id/reviews`, `/api/book/:id/social-stats`
-- user ratings/reviews ("共读" 评价 = 推荐). Business logic lives in
webserver/services/book_review_service.py; see plan/Social_Reading_Plan.md
§2.4/§5.1. Admin moderation endpoints are in webserver/handlers/admin.py.
"""

import datetime
import logging

import tornado.escape

from webserver.handlers.base import BaseHandler, auth, js
from webserver.i18n import _
from webserver.models import BookReview, Reader
from webserver.services.book_review_service import BookReviewService

_RANGE_TO_DAYS = {"7d": 7, "30d": 30, "90d": 90}


def _serialize_review(row: BookReview, reader) -> dict:
    return {
        "id": row.id,
        "book_id": row.book_id,
        "reader_id": row.reader_id,
        "nickname": (getattr(reader, "name", None) or getattr(reader, "username", None) or "") if reader else "",
        "avatar": getattr(reader, "avatar", "") if reader else "",
        "rating": row.rating,
        "comment": row.comment or "",
        "status": row.status,
        "update_time": row.update_time.isoformat() if row.update_time else None,
    }


def _get_int_argument(handler, name, default):
    try:
        return int(handler.get_argument(name, default))
    except (TypeError, ValueError):
        return default


class BookSocialStatsHandler(BaseHandler):
    @js
    def get(self, id):
        """在读/收藏/推荐人数，见 plan §2.4a。不要求登录（游客也能看）。"""
        book_id = int(id)
        stats = BookReviewService.get_stats(self.sqlite_session, book_id)
        return {"err": "ok", **stats}


class BookReviewHandler(BaseHandler):
    @js
    @auth
    def get(self, id):
        """取当前用户对该书的评价，用于评价对话框预填充/判断编辑态。"""
        row = BookReviewService.get_own(self.sqlite_session, int(id), self.user_id())
        if row is None:
            return {"err": "ok", "review": None}
        return {"err": "ok", "review": _serialize_review(row, self.current_user)}

    @js
    @auth
    def post(self, id):
        if not BookReviewService.is_enabled():
            return {"err": "review.disabled", "msg": _("评论功能未启用")}
        if getattr(self.current_user, "review_banned", False):
            return {"err": "review.banned", "msg": _("你已被禁止发表评论")}
        book = self.get_book(int(id), raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _("书籍已不存在")}

        try:
            data = tornado.escape.json_decode(self.request.body or b"{}")
        except ValueError:
            return {"err": "params.invalid", "msg": _("请求体不是合法的 JSON")}
        rating = data.get("rating")
        if not isinstance(rating, int) or not (0 <= rating <= 10):
            return {"err": "params.invalid", "msg": _("评分不合法")}
        comment = (data.get("comment") or "").strip()

        row = BookReviewService.upsert(self.sqlite_session, int(id), self.user_id(), rating, comment)
        logging.info("[book_review] user %s reviewed book %s: rating=%s", self.user_id(), id, rating)
        return {"err": "ok", "review": _serialize_review(row, self.current_user), "msg": _("评价已提交")}

    @js
    @auth
    def delete(self, id):
        ok = BookReviewService.soft_delete(self.sqlite_session, int(id), self.user_id())
        if not ok:
            return {"err": "params.invalid", "msg": _("没有可删除的评价")}
        return {"err": "ok", "msg": _("已删除")}


class BookReviewListHandler(BaseHandler):
    @js
    def get(self, id):
        """评论卡片列表，见 plan §2.4c：支持日期范围筛选 + 分页，当前用户置顶。"""
        book_id = int(id)
        page = max(1, _get_int_argument(self, "page", 1))
        page_size = min(50, max(1, _get_int_argument(self, "page_size", 20)))
        range_ = self.get_argument("range", "all")
        since = None
        if range_ in _RANGE_TO_DAYS:
            since = datetime.datetime.now() - datetime.timedelta(days=_RANGE_TO_DAYS[range_])
        elif range_ != "all":
            return {"err": "params.invalid", "msg": _("非法的 range 参数")}

        viewer_id = self.current_user.id if self.current_user else None
        rows, total = BookReviewService.list_for_book(
            self.sqlite_session, book_id, viewer_reader_id=viewer_id, since=since, page=page, page_size=page_size
        )
        readers = {}
        if rows:
            reader_ids = {r.reader_id for r in rows}
            for reader in self.sqlite_session.query(Reader).filter(Reader.id.in_(reader_ids)).all():
                readers[reader.id] = reader
        reviews = [_serialize_review(r, readers.get(r.reader_id)) for r in rows]
        return {"err": "ok", "total": total, "page": page, "page_size": page_size, "reviews": reviews}


def routes():
    return [
        (r"/api/book/([0-9]+)/social-stats", BookSocialStatsHandler),
        (r"/api/book/([0-9]+)/review", BookReviewHandler),
        (r"/api/book/([0-9]+)/reviews", BookReviewListHandler),
    ]
