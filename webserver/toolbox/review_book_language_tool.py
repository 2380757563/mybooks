"""
书名语言检测工具

遍历所有书籍，检测 title 字段的语言（简体中文 / 繁体中文 / 日文），
若检测结果与书籍当前的 languages 字段不一致，则更新为检测出的语言代码。

语言检测逻辑见 `webserver.utils.detect_title_language`。

@author: PoxenStudio, 2026
"""
import logging
import time
import traceback
from typing import Callable, Optional

from webserver import utils
from webserver.services import AsyncService
from webserver.toolbox.base_tool import BaseTool


class ReviewBookLanguageTool(BaseTool):
    """遍历所有书籍，检测书名语言并更新对应书籍的 languages 字段。"""

    service_item_name = "书名语言检测"

    @staticmethod
    def info() -> dict:
        return {
            "tool_id": "review_book_language",
            "name": "书名语言检测",
            "description": "遍历所有书籍，检测书名的语言（简体中文/繁体中文/日文），并将对应书籍的语言字段更新为检测结果",
            "revision": "0.2.0",
            "author": "PoxenStudio",
            "publish_date": "2026-07-18",
        }

    @AsyncService.register_service
    def review(
        self,
        user_id,
        callback: Optional[Callable[[int], None]] = None,
    ) -> Optional[dict]:
        """异步遍历所有书籍，检测书名语言并更新 languages 字段。

        :param user_id:  操作关联的用户 ID（保留字段，目前仅记录日志）。
        :param callback: 进度回调，参数为 0-100 的整数进度值。
        :return:         同步模式下返回统计 dict；异步模式下返回 None。
        """
        task_id = self.create_task(progress_data={"status": "starting"})
        total_checked = 0
        total_updated = 0
        error_message = None

        try:
            book_ids = self.get_all_book_ids()
            total = len(book_ids)
            logging.info("[ReviewBookLanguageTool] Total books to check: %d [uid:%d]", total, user_id)

            self.update_task_progress(
                task_id, 0,
                {"status": "running", "total": total, "checked": 0, "updated": 0},
            )

            for idx, book_id in enumerate(book_ids, start=1):
                try:
                    mi = self.get_book_metadata(book_id)
                    title = (mi.title or "").strip()
                    language = utils.detect_title_language(title)

                    if language and (not mi.languages or mi.languages[0] != language):
                        self.set_book_language(book_id, language)
                        total_updated += 1
                        logging.info(
                            "[ReviewBookLanguageTool] book_id=%d title=%r → language=%s",
                            book_id, title, language,
                        )
                except Exception as err:
                    logging.warning(
                        "[ReviewBookLanguageTool] Failed to process book_id=%d: %s",
                        book_id, err,
                    )

                total_checked += 1
                progress = int(idx * 100 / total) if total else 100
                if total_checked % 20 == 0:
                    self.update_task_progress(
                        task_id, progress,
                        {
                            "status": "running",
                            "total": total,
                            "checked": total_checked,
                            "updated": total_updated,
                        },
                    )
                    time.sleep(0.5)

        except Exception as err:
            logging.error("[ReviewBookLanguageTool] review failed: %s", err)
            error_message = str(err)
            logging.error(traceback.format_exc())

        self.complete_task(
            task_id,
            error_message=error_message,
        )

        return {
            "total": len(book_ids) if error_message is None else total_checked,
            "checked": total_checked,
            "updated": total_updated,
        }
