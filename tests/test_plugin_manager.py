# -*- coding: utf-8 -*-
"""plugin_manager 集成测试（M1 验收标准的自动化版本）。

覆盖 document/Toolbox_Dynamic_Design.md 第三节 + 第八节 M1 milestone 描述的整条链路：

    打包 zip -> 开发者模式安装 -> "重启"(重新调用 load_all()) 生效 -> 出现在 ToolSet /
    service_type 带 plugin:<tool_id> 前缀 -> 禁用立即生效（不需要重启）-> 卸载后重启彻底清除

以及 builtin 工具的"更新覆盖"路径（3.3 节）。

用轻量内存 SQLite（与 tests/test_reading_stats_flush.py 同一模式）+ 临时目录当
PLUGIN_ROOT，不依赖 tests/test_main.py 里那套完整的 Calibre 测试库 fixture。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from webserver import models
from webserver.loader import get_settings
from webserver.models import InstalledTool
from webserver.toolbox import plugin_manager
from webserver.toolbox.toolset import ToolSet

CONF = get_settings()

# ToolSet.collect_tools() 会真的 import 全部 14 个内置工具模块，其中几个（text_replace /
# book_utils 等）顶层 import calibre.ebooks.*，需要 webserver.main.init_calibre() 先把真实
# Calibre 安装路径塞进 sys.path 才能用（见 webserver/main.py）。这不是 plugin_manager 自身
# 的逻辑，本测试文件只关心 plugin_manager 对"已注册工具"的处理是否正确，所以把
# ToolSet.collect_tools() 替换成注册两个假 builtin 工具，绕开真实 Calibre 依赖 —— 与
# tests/test_text_replace_core.py 对 webserver 依赖的 stub 思路一致。
_FAKE_BUILTIN_TOOLS = (
    {
        "tool_id": "merge_formats_tool", "name": "格式合并", "description": "...",
        "revision": "0.1.0", "author": "PoxenStudio",
    },
    {
        "tool_id": "rare_book_downloader", "name": "古书下载器", "description": "...",
        "revision": "0.1.0", "author": "PoxenStudio",
    },
)


def _fake_collect_tools():
    for info in _FAKE_BUILTIN_TOOLS:
        ToolSet.register(info)


DEMO_BACKEND_SRC = '''
from webserver.toolbox.base_tool import BaseTool
from webserver.services import AsyncService
from webserver.handlers.base import BaseHandler, js


class DemoTool(BaseTool):
    service_item_name = "Demo Tool Task"

    @staticmethod
    def info():
        return {{
            "tool_id": "{tool_id}",
            "name": "Demo Tool",
            "description": "A demo external plugin for tests",
            "revision": "{revision}",
            "author": "Tester",
            "publish_date": "2026-01-01",
            "repo_url": "https://example.com/{tool_id}",
        }}

    @AsyncService.register_function
    def ping(self):
        task_id = self.api.tasks.create_task(progress_data={{"stage": "ping"}})
        self.api.tasks.complete_task(task_id)
        return "pong"


# manifest 里 api_routes 声明的自定义 handler，和上面的工具类同在一个文件里——这是插件作者
# 最自然的写法，也是曾经触发过"两次 import 出两个不同类对象"这个 bug 的具体场景，见
# test_collect_plugin_routes_shares_module_with_entry_backend()。
class PingHandler(BaseHandler):
    @js
    def get(self):
        return {{"err": "ok", "msg": DemoTool().ping()}}
'''


def _write_demo_plugin(tool_id="demo_tool", revision="1.0.0", entry_backend="tool.DemoTool", extra_manifest=None):
    """在临时目录里搭建一个符合 3.1 节结构的插件源码树，打成 zip，返回 zip 路径。"""
    src_dir = tempfile.mkdtemp(prefix="mybooks_demo_plugin_src_")
    manifest = {
        "tool_id": tool_id,
        "name": "Demo Tool",
        "description": "A demo external plugin for tests",
        "revision": revision,
        "author": "Tester",
        "publish_date": "2026-01-01",
        "core_api_version": "1.0.0",
        "entry_backend": entry_backend,
        "entry_frontend": "index.html",
        "page": tool_id,
        "repo_url": f"https://example.com/{tool_id}",
    }
    if extra_manifest:
        manifest.update(extra_manifest)

    with open(os.path.join(src_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f)

    backend_dir = os.path.join(src_dir, "backend")
    os.makedirs(backend_dir, exist_ok=True)
    open(os.path.join(backend_dir, "__init__.py"), "w").close()
    with open(os.path.join(backend_dir, "tool.py"), "w", encoding="utf-8") as f:
        class_name = entry_backend.rsplit(".", 1)[-1]
        code = DEMO_BACKEND_SRC.format(tool_id=tool_id, revision=revision)
        # 连带 PingHandler 里 `DemoTool()` 的引用一起改名，保持类名 <-> 引用一致
        code = code.replace("DemoTool", class_name)
        f.write(code)

    frontend_dir = os.path.join(src_dir, "frontend")
    os.makedirs(frontend_dir, exist_ok=True)
    with open(os.path.join(frontend_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write("<html><body>demo</body></html>")

    zip_path = os.path.join(tempfile.mkdtemp(prefix="mybooks_demo_plugin_zip_"), f"{tool_id}-{revision}.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        for root, _dirs, files in os.walk(src_dir):
            for name in files:
                abs_path = os.path.join(root, name)
                rel_path = os.path.relpath(abs_path, src_dir)
                zf.write(abs_path, rel_path)

    shutil.rmtree(src_dir, ignore_errors=True)
    return zip_path


class TestPluginManager(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        self.session = scoped_session(sessionmaker(bind=engine, autoflush=True, autocommit=False))
        models.bind_session(self.session)
        models.Base.metadata.create_all(engine)

        self._plugin_root = tempfile.mkdtemp(prefix="mybooks_plugin_root_")
        self._orig_plugin_root = CONF.get("PLUGIN_ROOT")
        CONF["PLUGIN_ROOT"] = self._plugin_root

        # 模块级状态，测试间要重置，避免互相污染
        ToolSet._tool_set.clear()
        plugin_manager._loaded_classes.clear()
        plugin_manager._loaded_at_startup.clear()

        self._collect_tools_patcher = patch.object(ToolSet, "collect_tools", side_effect=_fake_collect_tools)
        self._collect_tools_patcher.start()

        self._tmp_files = []

    def tearDown(self):
        self._collect_tools_patcher.stop()
        self.session.remove()
        shutil.rmtree(self._plugin_root, ignore_errors=True)
        if self._orig_plugin_root is not None:
            CONF["PLUGIN_ROOT"] = self._orig_plugin_root
        for path in self._tmp_files:
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)
        ToolSet._tool_set.clear()
        plugin_manager._loaded_classes.clear()
        plugin_manager._loaded_at_startup.clear()

    def _install(self, **kwargs):
        zip_path = _write_demo_plugin(**kwargs)
        self._tmp_files.append(zip_path)
        return zip_path

    # ---- 安装（全新外部插件）----

    def test_install_new_plugin_creates_record_and_dir(self):
        zip_path = self._install(tool_id="demo_tool")
        record = plugin_manager.install_from_zip(zip_path, is_update=False, installed_by=1)

        self.assertEqual(record.type, InstalledTool.TYPE_PLUGIN)
        self.assertEqual(record.source, InstalledTool.SOURCE_DEV)
        self.assertEqual(record.installed_revision, "1.0.0")
        self.assertTrue(record.enabled)
        self.assertTrue(os.path.isdir(plugin_manager._tool_dir("demo_tool")))
        self.assertIsNotNone(InstalledTool.get("demo_tool"))

    def test_install_duplicate_tool_id_rejected(self):
        zip_path = self._install(tool_id="demo_tool")
        plugin_manager.install_from_zip(zip_path, is_update=False)
        with self.assertRaises(plugin_manager.ToolStateError):
            plugin_manager.install_from_zip(zip_path, is_update=False)

    def test_update_nonexistent_tool_rejected(self):
        zip_path = self._install(tool_id="never_installed")
        with self.assertRaises(plugin_manager.ToolStateError):
            plugin_manager.install_from_zip(zip_path, is_update=True, expected_tool_id="never_installed")

    def test_update_tool_id_mismatch_rejected(self):
        zip_path = self._install(tool_id="demo_tool")
        plugin_manager.install_from_zip(zip_path, is_update=False)
        with self.assertRaises(plugin_manager.ToolValidationError):
            plugin_manager.install_from_zip(zip_path, is_update=True, expected_tool_id="some_other_tool")

    def test_validate_manifest_missing_fields(self):
        with self.assertRaises(plugin_manager.ToolValidationError):
            plugin_manager.validate_manifest({"tool_id": "x"})

    def test_zip_slip_is_rejected(self):
        # 构造一个内含路径穿越条目的恶意 zip
        evil_zip = os.path.join(tempfile.mkdtemp(prefix="mybooks_evil_zip_"), "evil.zip")
        with zipfile.ZipFile(evil_zip, "w") as zf:
            zf.writestr("../../etc/evil.txt", "pwned")
        self._tmp_files.append(evil_zip)
        with self.assertRaises(plugin_manager.ToolValidationError):
            plugin_manager.install_from_zip(evil_zip, is_update=False)

    # ---- 重启生效：load_all() ----

    def test_load_all_registers_plugin_with_service_type_prefix(self):
        zip_path = self._install(tool_id="demo_tool")
        plugin_manager.install_from_zip(zip_path, is_update=False)

        # 模拟进程重启：重新调用 load_all()
        plugin_manager.load_all()

        tool = ToolSet.get_tool("demo_tool")
        self.assertIsNotNone(tool)
        self.assertEqual(tool.name, "Demo Tool")

        cls = plugin_manager.get_tool_class("demo_tool")
        self.assertIsNotNone(cls)
        self.assertEqual(cls.PLUGIN_SERVICE_TYPE, "plugin:demo_tool")

        state = plugin_manager.tool_state("demo_tool")
        self.assertEqual(state["type"], "plugin")
        self.assertEqual(state["status"], "enabled")
        self.assertFalse(state["pending_restart"])

    def test_collect_plugin_routes_shares_module_with_entry_backend(self):
        # 回归测试：曾经真实发生过的 bug——entry_backend 和 manifest 里 api_routes 声明的
        # handler 同在一个 backend/tool.py 文件里时，如果各自单独 import 了一次，会得到两个
        # 不同的模块对象、两份不同的 DemoTool 类定义，handler 里 `DemoTool()` 实例化出来的
        # 对象读不到 load_all() 设在"另一份" DemoTool 类上的 PLUGIN_SERVICE_TYPE，
        # 表现为后台任务面板的 service_type 悄悄退回 "other"。在真实容器里用一个会custom
        # api_routes 的 demo 插件手工验证时发现的，见对话记录。
        zip_path = self._install(
            tool_id="demo_tool",
            extra_manifest={"api_routes": [{"path": "ping", "handler": "tool.PingHandler"}]},
        )
        plugin_manager.install_from_zip(zip_path, is_update=False)
        plugin_manager.load_all()

        routes = plugin_manager.collect_plugin_routes()
        self.assertEqual(len(routes), 1)
        route_path, wrapped_handler_cls = routes[0]
        self.assertEqual(route_path, "/api/toolbox/plugin/demo_tool/ping")

        real_handler_cls = wrapped_handler_cls.__bases__[0]
        handler_module = sys.modules[real_handler_cls.__module__]
        tool_cls_seen_by_handler = getattr(handler_module, "DemoTool")

        entry_cls = plugin_manager.get_tool_class("demo_tool")
        self.assertIs(
            tool_cls_seen_by_handler, entry_cls,
            "handler 模块里的 DemoTool 必须和 entry_backend 解析出来的是同一个类对象，"
            "否则 PLUGIN_SERVICE_TYPE 对 handler 不可见",
        )
        self.assertEqual(entry_cls.PLUGIN_SERVICE_TYPE, "plugin:demo_tool")

    def test_pending_restart_before_next_load_all(self):
        zip_path = self._install(tool_id="demo_tool")
        plugin_manager.install_from_zip(zip_path, is_update=False)
        # 还没有"重启"（没有调用 load_all()）：装了但还没生效
        self.assertTrue(plugin_manager.is_pending_restart("demo_tool"))

        plugin_manager.load_all()
        self.assertFalse(plugin_manager.is_pending_restart("demo_tool"))

    # ---- 启用 / 禁用：立即生效，不需要重启 ----

    def test_disable_takes_effect_without_reload(self):
        zip_path = self._install(tool_id="demo_tool")
        plugin_manager.install_from_zip(zip_path, is_update=False)
        plugin_manager.load_all()

        plugin_manager.disable_tool("demo_tool")
        self.assertFalse(plugin_manager.is_tool_enabled("demo_tool"))
        self.assertEqual(plugin_manager.tool_state("demo_tool")["status"], "disabled")

        plugin_manager.enable_tool("demo_tool")
        self.assertTrue(plugin_manager.is_tool_enabled("demo_tool"))

    def test_disable_enable_rejected_for_builtin(self):
        plugin_manager.sync_builtin_records()
        builtin_id = ToolSet.all_tools()[0].id
        with self.assertRaises(plugin_manager.ToolPermissionError):
            plugin_manager.disable_tool(builtin_id)
        with self.assertRaises(plugin_manager.ToolPermissionError):
            plugin_manager.enable_tool(builtin_id)

    # ---- 卸载：仅 plugin，重启后彻底清除 ----

    def test_uninstall_removes_dir_and_record(self):
        zip_path = self._install(tool_id="demo_tool")
        plugin_manager.install_from_zip(zip_path, is_update=False)
        plugin_manager.load_all()

        plugin_manager.uninstall_tool("demo_tool")
        self.assertIsNone(InstalledTool.get("demo_tool"))
        self.assertFalse(os.path.isdir(plugin_manager._tool_dir("demo_tool")))

        # 卸载后重新"重启"：ToolSet 里也不再有它
        plugin_manager.load_all()
        self.assertIsNone(ToolSet.get_tool("demo_tool"))

    def test_uninstall_rejected_for_builtin(self):
        plugin_manager.sync_builtin_records()
        builtin_id = ToolSet.all_tools()[0].id
        with self.assertRaises(plugin_manager.ToolPermissionError):
            plugin_manager.uninstall_tool(builtin_id)

    # ---- builtin 工具的更新覆盖机制（3.3 节）----

    def test_builtin_update_overrides_repo_implementation(self):
        plugin_manager.sync_builtin_records()
        builtin_id = "merge_formats_tool"
        self.assertIsNotNone(InstalledTool.get(builtin_id))
        self.assertEqual(InstalledTool.get(builtin_id).type, InstalledTool.TYPE_BUILTIN)

        zip_path = self._install(
            tool_id=builtin_id, revision="9.9.9", entry_backend="tool.MergeFormatsOverride"
        )
        record = plugin_manager.install_from_zip(zip_path, is_update=True, expected_tool_id=builtin_id)
        self.assertEqual(record.type, InstalledTool.TYPE_BUILTIN)  # type 不因为走了 update 而改变
        self.assertEqual(record.source, InstalledTool.SOURCE_DEV)
        self.assertEqual(record.installed_revision, "9.9.9")

        plugin_manager.load_all()

        cls = plugin_manager.get_tool_class(builtin_id)
        self.assertIsNotNone(cls)
        self.assertEqual(cls.__name__, "MergeFormatsOverride")
        # builtin 即使被更新覆盖，也不使用 plugin: 前缀（2.2 节决策，只有 type=plugin 才前缀）
        self.assertIsNone(cls.PLUGIN_SERVICE_TYPE)

        tool = ToolSet.get_tool(builtin_id)
        self.assertEqual(tool.revision, "9.9.9")

    def test_builtin_records_synced_on_first_load(self):
        plugin_manager.load_all()
        installed = {r.tool_id: r for r in InstalledTool.all()}
        # 至少覆盖几个已知的内置工具，全部 14 个逐一断言太啰嗦
        for tool_id in ("merge_formats_tool", "rare_book_downloader"):
            self.assertIn(tool_id, installed)
            self.assertEqual(installed[tool_id].type, InstalledTool.TYPE_BUILTIN)
            self.assertEqual(installed[tool_id].source, InstalledTool.SOURCE_BUNDLED)
            self.assertTrue(installed[tool_id].enabled)


if __name__ == "__main__":
    unittest.main()
