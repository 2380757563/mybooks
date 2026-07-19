"""
作者清理工具

输入一个现有作者名，对该作者名下的所有书籍执行：
- 清理（clean）：从作者列表中删除该作者，仅当书籍还有其他作者时才执行，避免书籍变成无作者。
- 替换（replace）：将该作者名替换为一个新的作者名。

@author: PoxenStudio, 2026
"""
import logging
import time
import traceback
from typing import Callable, List, Optional

from webserver.services import AsyncService
from webserver.toolbox.base_tool import BaseTool

ACTION_CLEAN = "clean"
ACTION_REPLACE = "replace"


class AuthorCleanTool(BaseTool):
    """清理或替换指定作者名，遍历该作者名下的所有书籍并更新作者字段。"""

    service_item_name = "作者清理"

    @staticmethod
    def info() -> dict:
        return {
            "tool_id": "author_clean",
            "name": "作者清理",
            "description": "输入一个现有作者名，清理（从多作者书籍中移除）或替换为新的作者名",
            "revision": "0.1.0",
            "author": "PoxenStudio",
            "publish_date": "2026-07-19",
        }

    @staticmethod
    def validate_new_author_name(name: str) -> bool:
        """校验新作者名：仅允许任意语言的字母/数字，以及 '.' 和 '·'，不允许空格、引号等其他符号。"""
        if not name:
            return False
        return all(c.isalnum() or c in ".·" for c in name)

    def _find_book_ids_by_author(self, author_name: str) -> List[int]:
        escaped = author_name.replace('"', '\\"')
        query = f'authors:="{escaped}"'
        ids = self.db.new_api.search(query)
        return sorted(ids)

    @AsyncService.register_service
    def clean(
        self,
        author_name: str,
        user_id,
        callback: Optional[Callable[[int], None]] = None,
    ) -> Optional[dict]:
        """异步清理：从多作者书籍中删除指定作者，单作者书籍保持不变。"""
        return self._run(ACTION_CLEAN, author_name, None, user_id)

    @AsyncService.register_service
    def replace(
        self,
        author_name: str,
        new_author_name: str,
        user_id,
        callback: Optional[Callable[[int], None]] = None,
    ) -> Optional[dict]:
        """异步替换：将指定作者名替换为新作者名。"""
        return self._run(ACTION_REPLACE, author_name, new_author_name, user_id)

    def _run(
        self,
        action: str,
        author_name: str,
        new_author_name: Optional[str],
        user_id,
    ) -> Optional[dict]:
        task_id = self.create_task(progress_data={"status": "starting"})
        total_checked = 0
        total_updated = 0
        total_skipped = 0
        error_message = None
        book_ids: List[int] = []

        try:
            book_ids = self._find_book_ids_by_author(author_name)
            total = len(book_ids)
            logging.info(
                "[AuthorCleanTool] action=%s author=%r matched %d books [uid:%s]",
                action, author_name, total, user_id,
            )

            self.update_task_progress(
                task_id, 0,
                {"status": "running", "total": total, "checked": 0, "updated": 0, "skipped": 0},
            )

            target = author_name.strip().lower()
            for idx, book_id in enumerate(book_ids, start=1):
                try:
                    mi = self.get_book_metadata(book_id)
                    authors = list(mi.authors or [])
                    matched = any(a.strip().lower() == target for a in authors)

                    if matched:
                        if action == ACTION_CLEAN:
                            if len(authors) <= 1:
                                total_skipped += 1
                            else:
                                new_authors = [a for a in authors if a.strip().lower() != target]
                                self._set_book_authors(book_id, new_authors)
                                total_updated += 1
                        else:
                            new_authors = [new_author_name if a.strip().lower() == target else a for a in authors]
                            self._set_book_authors(book_id, new_authors)
                            total_updated += 1
                except Exception as err:
                    logging.warning(
                        "[AuthorCleanTool] Failed to process book_id=%d: %s", book_id, err,
                    )

                total_checked += 1
                progress = int(idx * 100 / total) if total else 100
                if total_checked % 20 == 0 or total_checked == total:
                    self.update_task_progress(
                        task_id, progress,
                        {
                            "status": "running",
                            "total": total,
                            "checked": total_checked,
                            "updated": total_updated,
                            "skipped": total_skipped,
                        },
                    )
                    time.sleep(0.2)

        except Exception as err:
            logging.error("[AuthorCleanTool] run failed: %s", err)
            error_message = str(err)
            logging.error(traceback.format_exc())

        self.complete_task(task_id, error_message=error_message)

        return {
            "total": len(book_ids),
            "checked": total_checked,
            "updated": total_updated,
            "skipped": total_skipped,
        }

    def _set_book_authors(self, book_id: int, authors: List[str]) -> None:
        mi = self.get_book_metadata(book_id)
        mi.authors = authors
        self.db.set_metadata(book_id, mi, force_changes=True)
        logging.info(
            "[AuthorCleanTool] Set authors of book_id=%d to %s", book_id, authors,
        )
