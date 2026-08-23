# -*- coding: utf-8 -*-
"""EPUB 美化工具

对指定书籍的 EPUB 格式执行无损美化（目录样式 / 章节名样式 / 字体排版），
以「生成新书」模式入库，原书零改动：

- **目录**：书内已有目录页则注入统一样式；无目录页时从 NCX/nav 生成
  ``mb-toc.xhtml`` 目录页并注册进 OPF（spine 首条）；
- **章节名**：三层识别章节标题（h1-h6 / 已知标题类 / 段落文本章节正则，
  正则移植自 hehetoshang/txt2epub-next，MIT），标记 ``mb-ch`` 统一样式
  （居中、分页、标题字体、留白），章首段顶格；
- **字体**：注入 ``mb-beauty.css`` 覆盖层，正文/标题/引文三档系统字体栈
  （不嵌入字体文件），可选「保留原书字体」。

对外接口：
- :meth:`preview` 同步返回分析结果 + 可用预设列表；
- :meth:`run` 后台执行美化并入库。

@author: 黏菌, 2026
"""
import logging
import os
import threading
import time
import traceback
from typing import Optional

from webserver.i18n import _
from webserver.services import AsyncService
from webserver.services.background_service import BackgroundService, BackgroundTask
from webserver.toolbox.base_tool import BaseTool

from . import book_utils
from . import epub_beautify_lib
from .styles import get_preset_css, list_presets, list_toc_styles


class EpubBeautifyTool(BaseTool):
    """对指定书籍的 EPUB 执行美化并生成新书。"""

    service_item_name = "EPUB美化"

    _run_lock = threading.Lock()
    _last_task_id: Optional[int] = None

    @classmethod
    def is_running(cls) -> bool:
        task = cls.get_last_task()
        return bool(task and task.get("status") == BackgroundTask.STATUS_RUNNING)

    @classmethod
    def get_last_task(cls) -> Optional[dict]:
        if cls._last_task_id is None:
            return None
        return BackgroundService().get_task(cls._last_task_id)

    @staticmethod
    def info() -> dict:
        return {
            "tool_id": "epub_beautify",
            "name": "EPUB美化",
            "description": "美化 EPUB 的目录、章节名与字体排版（12 套风格预设，含宣纸墨韵/墨碑/航海纪事/竖排古籍；内容清理与目录深度可调），生成新书",
            "revision": "0.2.0",
            "author": "黏菌",
            "publish_date": "2026-08-22",
        }

    # ------------------------------------------------------------ 预览（同步）

    # 预设卡片可视化所需的色板字段（presets.json 元数据直通）
    _PRESET_PALETTE_KEYS = (
        "scene", "line_height", "title_size",
        "accent", "accent_light", "accent_dark", "muted", "border",
        "quote_bg", "code_bg", "toc_gradient", "page_progression",
    )

    @AsyncService.register_function
    def preview(self, book_id: int) -> dict:
        """同步返回书籍分析 + 预设列表。

        :param book_id: Calibre 书籍 ID。
        :return dict: ``analysis``（目录形态/标题统计/字体现状）与 ``presets``。
        :raises RuntimeError: 书籍不存在 / 无 EPUB / 文件缺失。
        """
        epub_path = book_utils.get_book_file(self, book_id, "EPUB")
        analysis = epub_beautify_lib.analyze_epub(epub_path)
        presets = []
        for pid, meta in list_presets().items():
            item = {
                "id": pid,
                "name": meta.get("name", pid),
                "name_en": meta.get("name_en", pid),
                "description": meta.get("description", ""),
            }
            for key in self._PRESET_PALETTE_KEYS:
                if key in meta:
                    item[key] = meta[key]
            presets.append(item)
        return {"analysis": analysis, "presets": presets, "toc_styles": list_toc_styles()}

    # ------------------------------------------------------------- 后台执行

    @staticmethod
    def _normalize_font_overrides(use_system_fonts: bool, font_overrides) -> Optional[dict]:
        """归一化字体子开关：兼容旧 use_system_fonts 布尔与新细粒度 dict。"""
        if isinstance(font_overrides, dict):
            # 仅保留合法键，缺省回落到 use_system_fonts
            norm = {}
            for k in ("body", "head", "kai", "code"):
                if k in font_overrides:
                    norm[k] = bool(font_overrides[k])
                else:
                    norm[k] = bool(use_system_fonts)
            return norm
        if use_system_fonts is None:
            return None
        return {
            "body": bool(use_system_fonts),
            "head": bool(use_system_fonts),
            "kai": bool(use_system_fonts),
            "code": bool(use_system_fonts),
        }

    @AsyncService.register_service
    def run(self, book_id: int, preset: str, use_system_fonts: bool,
            toc_style: str, suffix: str, user_id: int,
            font_overrides: Optional[dict] = None,
            toc_depth: Optional[int] = None,
            cleanup: Optional[dict] = None) -> None:
        """后台执行美化并生成新书。

        :param preset:           预设 id（classic/modern/webnovel/classical/navy/youth/children/refined/xuanzhi/inkstone/voyage/vertclassical）。
        :param use_system_fonts: 是否统一系统字体栈（False 保留原书字体，兼容旧接口）。
        :param toc_style:        目录风格（elegant 精致 / cool 酷炫 / seal 朱印 / minimal 极简）。
        :param suffix:           新书标题后缀（默认「（精排版）」）。
        :param user_id:          操作用户 ID。
        :param font_overrides:   细粒度字体开关 {"body":bool,"head":bool,"kai":bool,"code":bool}，覆盖 use_system_fonts。
        :param toc_depth:        目录收录层级上限（None=全部；1/2/3=只收前 N 级）。
        :param cleanup:          内容清理开关 {"leading":bool,"empty":bool,"meta":bool}，
                                 默认 段首空格归一开 / 空段清理关 / 冗余 meta 移除开。

        预设元数据含 ``page_progression`` 时（如 vertclassical 竖排古籍 = rtl），
        自动把 spine 设为对应翻页方向。
        """
        if not EpubBeautifyTool._run_lock.acquire(blocking=False):
            logging.warning(
                "[EpubBeautifyTool] Already running, skipping run for book_id=%d [uid:%d]",
                book_id, user_id,
            )
            return

        task_id = None
        error_message = None
        book_title = "Unknown"
        new_book_id = None

        try:
            task_id = self.create_task(progress_data={"status": "starting", "book_id": book_id})
            EpubBeautifyTool._last_task_id = task_id
            progress_callback = self.make_progress_callback(task_id)

            books = self.db.get_data_as_dict(ids=[book_id])
            if not books:
                error_message = _("书籍不存在：ID=%d") % book_id
                logging.error("[EpubBeautifyTool] Book not found: ID=%d [uid:%d]", book_id, user_id)
                return
            book = books[0]
            book_title = book.get("title", "Unknown")

            epub_path = book_utils.get_book_file(self, book_id, "EPUB")

            self.update_task_progress(task_id, 10, {"status": "running", "stage": "analyzing"})
            progress_callback(10)

            # 校验预设（含细粒度字体开关）
            try:
                overrides = self._normalize_font_overrides(use_system_fonts, font_overrides)
                preset_css = get_preset_css(preset, use_system_fonts, toc_style, overrides)
            except ValueError as err:
                error_message = _("预设或目录风格不存在：%s") % err
                logging.error("[EpubBeautifyTool] Bad preset/toc_style %r/%r [uid:%d]", preset, toc_style, user_id)
                return

            # 竖排等预设可声明翻页方向（page_progression: rtl）
            page_progression = (list_presets().get(preset) or {}).get("page_progression") or None

            work_dir = self.get_work_dir(str(book_id))
            out_path = os.path.join(work_dir, "beautified_%d.epub" % int(time.time()))

            self.update_task_progress(task_id, 30, {"status": "running", "stage": "processing"})
            progress_callback(30)

            stats = epub_beautify_lib.beautify(
                epub_path, out_path, preset_css,
                toc_style=toc_style, page_progression=page_progression,
                toc_depth=toc_depth, cleanup=cleanup,
            )

            self.update_task_progress(task_id, 80, {"status": "running", "stage": "saving"})
            progress_callback(80)

            new_book_id = book_utils.import_as_new_book(
                self, book_id, out_path, suffix or _("（精排版）"), user_id,
            )
            self.update_task_progress(
                task_id, 90,
                {"status": "running", "stage": "saving",
                 "book_id": book_id, "new_book_id": new_book_id},
            )
            logging.info(
                "[EpubBeautifyTool] Beautified book_id=%d (headers=%d, toc=%s, rtl=%s) -> new book_id=%d [uid:%d]",
                book_id, stats.get("marked_headers", 0), stats.get("toc_generated"),
                stats.get("page_progression") or "-", new_book_id, user_id,
            )
            self.cleanup_work_dir(work_dir)

            self.add_msg(
                user_id, "success",
                _(u"书籍 [%s] 美化成功！已生成新书（章节标题 %d 处，目录页 %s）")
                % (book_title, stats.get("marked_headers", 0),
                   _("已生成") if stats.get("toc_generated") else _("保留原样")),
            )

        except Exception as err:
            error_message = str(err)
            self.add_msg(user_id, "danger", _(u"书籍 [%s] 美化失败！") % book_title)
            logging.error("[EpubBeautifyTool] Unexpected error for book_id=%d: %s", book_id, err)
            logging.error(traceback.format_exc())
        finally:
            if task_id is not None:
                self.complete_task(task_id, error_message=error_message)
                if error_message is None:
                    self.update_task_progress(
                        task_id, 100,
                        {"status": "completed", "book_id": book_id, "new_book_id": new_book_id},
                    )
            EpubBeautifyTool._run_lock.release()
