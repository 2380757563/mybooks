#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
`/api/sync` — legacy record sync (books/notes/configs) and the matching
`/api/sync/events` WS change-notification channel. See
document/Sync_IMPLEMENT_PLAN.md for the full protocol/design.

All storage and merge logic lives in webserver/services/sync_service.py;
this module only does auth/feature-gate checks and request/response shaping.

`/api/sync/import` (SyncImportHandler, below) is a separate, later addition
— the server-side half of the WeChat-Reading-style annotation import
pipeline (plan/WeChatReading_Annotation_Import_Plan.md §5.3). It deliberately
does not touch SyncHandler's routes/params/response shape at all; it only
*writes through* MyReaderSyncService.push() at commit time, reusing that
same storage/merge/broadcast code so imported notes are indistinguishable
from ones a client pushed itself.
@author: PoxenStudio, 2026-06
"""

import logging
import os

import tornado.escape
import tornado.websocket

from webserver.handlers.base import BaseHandler, auth, js
from webserver.i18n import _
from webserver.services import sync_import_service
from webserver.services.sync_import_service import SyncImportError
from webserver.services.sync_service import MyReaderSyncService


class SyncHandler(BaseHandler):
    @js
    @auth
    def get(self):
        if not MyReaderSyncService.is_enabled():
            return {"err": "sync.disabled", "msg": _("数据同步功能未启用")}

        since = self.get_argument("since", None)
        if since is None or not since.lstrip("-").isdigit():
            return {"err": "params.invalid", "msg": _("缺少或非法的 since 参数")}
        type_ = self.get_argument("type", None)
        if type_ and type_ not in MyReaderSyncService.KINDS:
            return {"err": "params.invalid", "msg": _("非法的 type 参数")}
        book_hash = self.get_argument("book", None)
        own_arg = self.get_argument("own", None)
        if own_arg is None:
            # 客户端没传 own 时，表示为旧的客户端，按之前的逻辑只会返回自己的批注信息
            own = 1
        elif own_arg in ("0", "1"):
            own = int(own_arg)
        else:
            return {"err": "params.invalid", "msg": _("非法的 own 参数")}

        # own=1 只返回自己的记录；own=0 时额外并入其他用户的 notes（受
        # ENABLE_SHARED_NOTES 开关与 book 参数约束），具体组装逻辑都在 MyReaderSyncService
        # 内部完成，这里只是把参数原样透传下去。
        return MyReaderSyncService.pull(self.current_user.id, int(since), type_, book_hash, own)

    @js
    @auth
    async def post(self):
        if not MyReaderSyncService.is_enabled():
            return {"err": "sync.disabled", "msg": _("数据同步功能未启用")}
        logging.debug("[sync] push request from user %s: %s", self.current_user.id, self.request.body[:100])
        try:
            payload = tornado.escape.json_decode(self.request.body or b"{}")
        except ValueError:
            logging.error("[sync] invalid JSON payload from user %s: %s", self.current_user.id, self.request.body)
            return {"err": "params.invalid", "msg": _("请求体不是合法的 JSON")}
        if not isinstance(payload, dict):
            logging.error("[sync] invalid payload type from user %s: %s", self.current_user.id, type(payload))
            return {"err": "params.invalid", "msg": _("请求体格式错误")}

        return await MyReaderSyncService.push(self.current_user.id, payload)


class SyncImportHandler(BaseHandler):
    """`POST /api/sync/import` — server-side CFI resolution + (optional)
    commit for third-party annotation imports (see plan §5.3).

    Request body:
        book_id       int, required — MyBooks book id (must have an EPUB format)
        anchors       list[dict], required, non-empty — each `{id, text?, chapterHint?, note?, ...}`
        on_ambiguous  "error" (default) | "first_match"
        dry_run       bool, default true — true: only return the report, write nothing.
                      false: also write the resolved notes via MyReaderSyncService.push().
        force         bool, default false — true: re-resolve every anchor's CFI even if it
                      matches a previous import unchanged (bypasses the dedup described below).

    Re-import / dedup: every call first checks the notes this pipeline
    previously wrote for this (user, book) and skips re-resolving the CFI
    for any anchor whose text/chapterHint haven't changed — see
    `sync_import_service.py`'s module docstring and `partition_for_dedup()`.
    This is automatic, not opt-in; `force=true` is the escape hatch when you
    actually need everything re-resolved (e.g. the epub file was replaced).

    Response (both modes): `{ book_id, book_hash, dry_run, results: [...] }`
    — each `results[]` item may carry `"reused": true` if its `cfi` came
    from a previous import rather than a fresh resolution. Commit mode
    additionally includes `pushed` (MyReaderSyncService.push()'s own return
    value, same shape `GET /api/sync` would show for `notes`).
    """

    @js
    @auth
    async def post(self):
        if not MyReaderSyncService.is_enabled():
            return {"err": "sync.disabled", "msg": _("数据同步功能未启用")}
        try:
            payload = tornado.escape.json_decode(self.request.body or b"{}")
        except ValueError:
            return {"err": "params.invalid", "msg": _("请求体不是合法的 JSON")}
        if not isinstance(payload, dict):
            return {"err": "params.invalid", "msg": _("请求体格式错误")}

        book_id = payload.get("book_id")
        anchors = payload.get("anchors")
        on_ambiguous = payload.get("on_ambiguous", "error")
        dry_run = payload.get("dry_run", True)
        force = payload.get("force", False)

        if not isinstance(book_id, int) or book_id <= 0:
            return {"err": "params.invalid", "msg": _("缺少或非法的 book_id 参数")}
        if not isinstance(anchors, list) or not anchors:
            return {"err": "params.invalid", "msg": _("anchors 不能为空")}
        if not all(isinstance(a, dict) and a.get("id") for a in anchors):
            return {"err": "params.invalid", "msg": _("anchors 中每一项都需要 id 字段")}
        if on_ambiguous not in ("error", "first_match"):
            return {"err": "params.invalid", "msg": _("非法的 on_ambiguous 参数")}
        if not isinstance(dry_run, bool):
            return {"err": "params.invalid", "msg": _("非法的 dry_run 参数")}
        if not isinstance(force, bool):
            return {"err": "params.invalid", "msg": _("非法的 force 参数")}

        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _("书籍不存在")}

        formats = [f.strip().upper() for f in (self.calibre_db.formats(book_id, index_is_id=True) or "").split(",") if f.strip()]
        if "EPUB" not in formats:
            return {"err": "book.no_epub", "msg": _("该书籍没有 EPUB 格式，无法导入批注")}
        epub_path = self.calibre_db.format_abspath(book_id, "EPUB", index_is_id=True)
        if not epub_path or not os.path.exists(epub_path):
            logging.error("[sync.import] EPUB format listed but file missing for book %s: %s", book_id, epub_path)
            return {"err": "book.no_epub", "msg": _("找不到该书籍的 EPUB 文件")}

        uid = self.current_user.id
        book_hash = sync_import_service.book_hash_for(book_id)
        try:
            results = await sync_import_service.preview(uid, book_hash, epub_path, anchors, on_ambiguous, force)
        except SyncImportError as e:
            logging.error("[sync.import] cfi batch failed for user %s book %s: %s", uid, book_id, e)
            return {"err": "sync.import.failed", "msg": _("批注定位失败：%(error)s") % {"error": str(e)}}

        response = {"book_id": book_id, "book_hash": book_hash, "dry_run": dry_run, "results": results}
        if dry_run:
            return response

        response["pushed"] = await sync_import_service.commit(uid, book_hash, anchors, results)
        return response


class SyncImportClearHandler(BaseHandler):
    """`POST /api/sync/import/clear` — tombstones every note `/api/sync/import`
    previously wrote for (current user, book_id). A secondary escape hatch
    for "start over" (bad import, `first_match` picked wrong matches, ...) —
    **not** the primary way to handle a routine re-sync; that's the
    automatic dedup already built into `SyncImportHandler` (see its
    docstring). Only ever touches `wxread-`-prefixed notes belonging to the
    current user — never other notes on the book, and never other users'.

    Request body: `{ "book_id": int }`.
    Response: `{ book_id, book_hash, cleared: <int> }`.
    """

    @js
    @auth
    async def post(self):
        if not MyReaderSyncService.is_enabled():
            return {"err": "sync.disabled", "msg": _("数据同步功能未启用")}
        try:
            payload = tornado.escape.json_decode(self.request.body or b"{}")
        except ValueError:
            return {"err": "params.invalid", "msg": _("请求体不是合法的 JSON")}
        if not isinstance(payload, dict):
            return {"err": "params.invalid", "msg": _("请求体格式错误")}

        book_id = payload.get("book_id")
        if not isinstance(book_id, int) or book_id <= 0:
            return {"err": "params.invalid", "msg": _("缺少或非法的 book_id 参数")}

        book = self.get_book(book_id, raise_exception=False)
        if not book:
            return {"err": "params.book.invalid", "msg": _("书籍不存在")}

        book_hash = sync_import_service.book_hash_for(book_id)
        pushed = await sync_import_service.clear(self.current_user.id, book_hash)
        return {"book_id": book_id, "book_hash": book_hash, "cleared": len(pushed.get("notes") or [])}


class SyncWebSocketHandler(tornado.websocket.WebSocketHandler):
    def get_current_user(self):
        user_id = self.get_secure_cookie("user_id")
        if not user_id:
            return None
        return user_id

    def check_origin(self, origin):
        return True

    async def open(self):
        if not MyReaderSyncService.is_enabled():
            self.close(code=4004, reason="Sync service disabled")
            logging.warning("[sync] WebSocket connection attempt while sync service is disabled.")
            return
        user_id = self.get_current_user()
        if not user_id:
            logging.warning("[sync] WebSocket connection attempt without login.")
            self.close(code=4003, reason="Authentication required")
            return
        logging.debug("[sync] WebSocket connection opened for user %s", user_id)
        self.uid = int(user_id)
        MyReaderSyncService.register_connection(self.uid, self)

    def on_message(self, message):
        try:
            data = tornado.escape.json_decode(message)
        except ValueError:
            return
        msg_type = data.get("type")
        if msg_type == "ping":
            self.write_message(tornado.escape.json_encode({"type": "pong"}))
        logging.info(f"[WebSocket] message: {message}")
        # `hello` is accepted but ignored in this first version (see plan §11.8).

    def on_close(self):
        if hasattr(self, "uid"):
            MyReaderSyncService.unregister_connection(self.uid, self)


def routes():
    return [
        (r"/api/sync", SyncHandler),
        (r"/api/sync/import", SyncImportHandler),
        (r"/api/sync/import/clear", SyncImportClearHandler),
        (r"/api/sync/events", SyncWebSocketHandler),
    ]
