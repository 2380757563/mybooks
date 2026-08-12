#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Server-side orchestration for `POST /api/sync/import` (see
plan/WeChatReading_Annotation_Import_Plan.md §5.3). This is the "third-party
annotation import" pipeline (currently WeChat Reading) — deliberately kept
out of `sync_service.py` so the regular `/api/sync` client sync contract
(`SyncHandler.get`/`post`) is never touched by anything import-specific.

Two phases, both go through `preview()`:
  - dry_run=True (default): only runs the CFI batch generator and returns a
    per-anchor report. Nothing is written.
  - dry_run=False: the caller (SyncImportHandler) takes that same report and
    calls `commit()`, which builds `BookNoteRecord`s and writes them through
    `MyReaderSyncService.push()` — the exact same storage/merge/broadcast
    code path `/api/sync` itself uses, so imported notes are indistinguishable
    from ones a client pushed directly (pullable via `GET /api/sync`, WS
    broadcast on write, etc.)

Resolving `book_id` to a local epub path and to `book_hash` is deliberately
NOT done here — that needs `self.calibre_db`, which only the handler has
(mirrors how webserver/handlers/book.py resolves `fpath` itself before
calling into webserver/services/converter.py). This module only deals with
already-resolved inputs.

Re-import / dedup (plan §7 "多次导入需要判重"): `preview()` always checks
the notes this pipeline previously wrote for the same (uid, book_hash)
before calling the CFI batch generator. An anchor whose `text`/`chapterHint`
haven't changed since the last import reuses its stored `cfi` instead of
being re-resolved — this is the *default*, not opt-in, because re-running
the (expensive, and never 100% guaranteed-identical-on-every-run when a
book has ambiguous matches) full-text search for annotations nothing has
changed about is both wasteful and a source of needless drift. `force=True`
bypasses this and re-resolves everything (e.g. the underlying epub file was
replaced). `clear()` is a separate, secondary escape hatch — see its
docstring — not the primary way to handle a re-sync.
@author: PoxenStudio, 2026-08
"""

import time
from typing import Any, Dict, List, Tuple, TypedDict

from webserver.services.cfi_gen.launcher import CfiAnchor, CfiBatchError, OnAmbiguous, generate_cfis
from webserver.services.sync_service import MyReaderSyncService

# All record ids this pipeline writes get this prefix — makes re-running the
# import idempotent (same id -> same LWW-merged record, see sync_service.py)
# and makes "every note this pipeline ever wrote" a simple prefix query for
# any future cleanup/undo tooling (plan §5.1, §8 M3).
ID_PREFIX = "wxread-"

DEFAULT_STYLE = "highlight"
DEFAULT_COLOR = "yellow"
DEFAULT_SOURCE = "wxread"


class ImportAnchor(TypedDict, total=False):
    id: str  # externally-stable id from the source (e.g. WeChat Reading bookmarkId/reviewId)
    text: str  # highlighted/anchor text; omit/empty for chapter- or book-level notes (§4.5)
    chapterHint: str
    note: str  # the user's own thought/comment text, if any
    color: str
    style: str
    createdAt: int  # ms epoch, from the source system
    source: str  # provenance tag; stored as-is, `sync_service.py` does not filter fields (§3.2/§9 Q4)


class ImportResultItem(TypedDict, total=False):
    id: str
    status: str  # "ok" | "no_match" | "ambiguous" | "error"
    cfi: str
    matchCount: int
    ambiguousResolution: str
    degraded: str
    error: str
    reused: bool  # True: cfi was reused from a previous import, CFI generator was not invoked for this anchor (dedup, see module docstring)


class SyncImportError(Exception):
    """A whole-request failure — the CFI batch subprocess failed outright.
    Distinct from a per-anchor `status` in the report; callers must not
    treat this as "every anchor was a no_match" (see plan §4.3)."""


def book_hash_for(book_id: int) -> str:
    """The `book_hash` for a book that lives in MyBooks' own library.

    NOT a partial-MD5 of the file — that scheme (`Book.hash` in MyReader) is
    only for books MyReader imported locally with no server-side identity.
    Books addressed by a MyBooks `book_id` already have a stable identity,
    so MyReader (and this codebase's own `webserver/models.py::
    _CLOUD_BOOK_HASH_RE` / `reading_stats_service.py::_CLOUD_BOOK_HASH_RE`)
    both use this exact `cloud-<book_id>-<fmt>` format instead. See plan
    §3.2 (this was corrected there after an earlier, wrong assumption).
    """
    return f"cloud-{book_id}-epub"


def _load_existing_by_source_id(uid: int, book_hash: str) -> Dict[str, Dict[str, Any]]:
    """Currently-live (non-tombstoned) notes this pipeline previously wrote
    for (uid, book_hash), keyed by the *source* anchor id (`wxread-` prefix
    stripped) so callers can look them up directly by the ids they were
    given. Read-only — reuses `MyReaderSyncService.pull()`, no new storage
    plumbing needed."""
    pulled = MyReaderSyncService.pull(uid, since=0, type_="notes", book_hash=book_hash, own=1)
    existing = {}
    for note in pulled.get("notes") or []:
        note_id = note.get("id") or ""
        if not note_id.startswith(ID_PREFIX):
            continue  # not ours — e.g. a note the user made natively in MyReader
        if note.get("deleted_at") or note.get("deletedAt"):
            continue  # tombstoned -> treat as if it never existed
        existing[note_id[len(ID_PREFIX):]] = note
    return existing


def _anchor_unchanged(anchor: ImportAnchor, existing: Dict[str, Any]) -> bool:
    """True if re-resolving this anchor's CFI would be redundant — i.e. the
    fields that actually drive CFI generation (§4.2/§4.3: the anchor text,
    or the chapter hint for a no-text/degraded anchor) haven't changed since
    the last import. Anything else changing (note text, color, ...) doesn't
    require touching the CFI at all — see `build_note_records()`, which
    still re-commits these anchors with their reused `cfi`.

    `existing` isn't necessarily something *this* pipeline wrote, even
    though its id starts with `ID_PREFIX` — `/api/sync`'s own POST has no
    field whitelist (§3.2), so nothing stops some other client from having
    pushed a `wxread-`-id note with no `cfi` at all. Never reuse that: treat
    a missing `cfi` the same as "no match" and fall through to a fresh
    resolution rather than propagating a KeyError/`None` cfi downstream."""
    if not existing.get("cfi"):
        return False
    if (anchor.get("text") or "") != (existing.get("text") or ""):
        return False
    if not (anchor.get("text") or ""):
        if (anchor.get("chapterHint") or "") != (existing.get("chapterHint") or ""):
            return False
    return True


def partition_for_dedup(
    uid: int, book_hash: str, anchors: List[ImportAnchor], force: bool = False
) -> Tuple[List[ImportAnchor], List[ImportResultItem]]:
    """Splits `anchors` into ones that actually need the CFI batch generator
    and ones that can reuse a previous import's `cfi` unchanged. See the
    module docstring for why this is the default behavior, not opt-in."""
    if force:
        return anchors, []

    existing_by_source_id = _load_existing_by_source_id(uid, book_hash)
    to_resolve: List[ImportAnchor] = []
    reused: List[ImportResultItem] = []
    for anchor in anchors:
        existing = existing_by_source_id.get(anchor["id"])
        if existing is not None and _anchor_unchanged(anchor, existing):
            item: ImportResultItem = {"id": anchor["id"], "status": "ok", "cfi": existing["cfi"], "reused": True}
            if existing.get("type") == "bookmark":
                item["degraded"] = "chapter_start"
            reused.append(item)
        else:
            to_resolve.append(anchor)
    return to_resolve, reused


async def preview(
    uid: int,
    book_hash: str,
    epub_path: str,
    anchors: List[ImportAnchor],
    on_ambiguous: OnAmbiguous = "error",
    force: bool = False,
) -> List[ImportResultItem]:
    to_resolve, reused = partition_for_dedup(uid, book_hash, anchors, force=force)

    resolved: List[ImportResultItem] = []
    if to_resolve:
        cfi_anchors: List[CfiAnchor] = [
            {"id": a["id"], "text": a.get("text") or "", "chapterHint": a.get("chapterHint") or ""} for a in to_resolve
        ]
        try:
            resolved = await generate_cfis(epub_path, cfi_anchors, on_ambiguous=on_ambiguous)
        except CfiBatchError as e:
            raise SyncImportError(str(e)) from e

    results_by_id = {r["id"]: r for r in (*resolved, *reused)}
    # preserve the caller's original anchor order in the response
    return [results_by_id[a["id"]] for a in anchors if a["id"] in results_by_id]


def build_note_records(book_hash: str, anchors: List[ImportAnchor], cfi_results: List[ImportResultItem], uid: int) -> List[Dict[str, Any]]:
    """Only anchors whose CFI resolution succeeded (`status: "ok"`) become a
    record — no_match/ambiguous/error anchors are silently excluded here;
    the caller is expected to have already shown those to the user via the
    dry_run report (plan §5 "预览报告 → 用户确认 → 实际写入")."""
    results_by_id = {r["id"]: r for r in cfi_results}
    now = int(time.time() * 1000)
    records = []
    for anchor in anchors:
        result = results_by_id.get(anchor["id"])
        if not result or result.get("status") != "ok" or not result.get("cfi"):
            continue
        record_id = anchor["id"] if anchor["id"].startswith(ID_PREFIX) else f"{ID_PREFIX}{anchor['id']}"
        created_at = anchor.get("createdAt") or now
        # `createdAt` preserves the source system's original timestamp (so
        # imported annotations keep their real chronological order in
        # MyReader); `updatedAt`/`updated_at` is THIS write's wall-clock
        # time, not `created_at` — re-importing the same anchor with edited
        # `note`/`color` text must produce a strictly newer `updated_at` than
        # the previous import for the LWW merge (sync_service.py::_merge_one)
        # to behave the same way a real client edit would, and pinning it to
        # `created_at` would make every re-import of the same anchor compare
        # equal forever. `chapterHint` is stored purely so a *later*
        # re-import's dedup check (`_anchor_unchanged`, above) has something
        # to compare a degraded/no-text anchor's chapter binding against.
        #
        # Both snake_case (top-level, read by sync_service.py's LWW merge)
        # and camelCase (spread into the opaque payload, read by MyReader's
        # own useNativeSync.ts merge on the client) are required for
        # updated/deleted — this mirrors exactly what the client's own push
        # code does (`updated_at: note.updatedAt, ...note`), not a guess.
        records.append({
            "id": record_id,
            "book_hash": book_hash,
            "bookHash": book_hash,
            "uid": uid,
            "type": "bookmark" if result.get("degraded") else "annotation",
            "cfi": result["cfi"],
            "text": anchor.get("text") or "",
            "chapterHint": anchor.get("chapterHint") or "",
            "note": anchor.get("note") or "",
            "style": anchor.get("style") or DEFAULT_STYLE,
            "color": anchor.get("color") or DEFAULT_COLOR,
            "source": anchor.get("source") or DEFAULT_SOURCE,
            "createdAt": created_at,
            "updatedAt": now,
            "deletedAt": None,
            "updated_at": now,
            "deleted_at": None,
        })
    return records


async def commit(uid: int, book_hash: str, anchors: List[ImportAnchor], cfi_results: List[ImportResultItem]) -> Dict[str, Any]:
    records = build_note_records(book_hash, anchors, cfi_results, uid)
    if not records:
        return {"notes": []}
    return await MyReaderSyncService.push(uid, {"notes": records})


async def clear(uid: int, book_hash: str) -> Dict[str, Any]:
    """Tombstones every note this pipeline previously wrote for (uid,
    book_hash). A secondary escape hatch for "start over" (e.g. the import
    was run with wrong data, or `on_ambiguous="first_match"` picked bad
    matches and the user wants a clean slate) — **not** the primary way to
    handle a routine re-sync, that's the automatic dedup in `preview()`
    (unchanged anchors reuse their existing `cfi` instead of being touched
    at all). See plan §7/§9.
    """
    existing_by_source_id = _load_existing_by_source_id(uid, book_hash)
    if not existing_by_source_id:
        return {"notes": []}
    now = int(time.time() * 1000)
    records = [
        {
            "id": f"{ID_PREFIX}{source_id}",
            "book_hash": book_hash,
            "bookHash": book_hash,
            "uid": uid,
            "updatedAt": now,
            "deletedAt": now,
            "updated_at": now,
            "deleted_at": now,
        }
        for source_id in existing_by_source_id
    ]
    return await MyReaderSyncService.push(uid, {"notes": records})
