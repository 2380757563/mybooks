#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""mybooks.top 工具商店客户端 —— ToolboxStoreClient

对应 document/Toolbox_Dynamic_Design.md 3.4 节。风格对齐
`webserver.services.book_barn.BookBarnClient`（同一个 `mybooks.top/api/` 调用惯例、同样
用 `MyBooks-Client` 请求头上报客户端版本、不强制鉴权）。

mybooks.top 目前还没有实现 `toolbox/*` 这组接口（3.4 节仍是设计草案），所以本客户端从一开
始就受 `ENABLE_TOOLBOX_STORE` 开关控制（3.4.1 节）：开关为 `False`（默认）时，
`get_index()`/`check_update()` 不发起任何网络请求，直接返回空结果；`download()` 直接拒绝。
mybooks.top 一方把接口实现上线后，把这个 settings 项改成 `True` 即可，不需要改代码。
"""
import hashlib
import logging
import os
import tempfile
import time

import requests

from webserver import loader
from webserver.i18n import _
from webserver.version import VERSION

CONF = loader.get_settings()

# 索引缓存 TTL（秒）：管理员打开 /admin/toolbox 时不必每次都请求外网，见 3.4 节。
INDEX_CACHE_TTL = 60 * 60


class ToolboxStoreError(Exception):
    """商店请求失败（网络错误、非 200、sha256 校验失败等），供上层 handler 捕获后转成友好错误。"""


class ToolboxStoreClient:
    HOST_BASE = "https://mybooks.top/api/"
    INDEX_API = "toolbox/index"                  # 可安装工具目录
    CHECK_UPDATE_API = "toolbox/release/check"    # 检查某个已安装工具是否有新版本
    DOWNLOAD_API = "toolbox/download"             # 下载指定版本的 zip 包

    def __init__(self):
        self.headers = {"MyBooks-Client": f"MyBooks/{VERSION}"}

    @staticmethod
    def enabled() -> bool:
        return bool(CONF.get("ENABLE_TOOLBOX_STORE", False))

    def get_index(self) -> list:
        """返回商店当前可安装的全部工具列表（3.4 节 `GET toolbox/index`）。

        `ENABLE_TOOLBOX_STORE=False` 时直接返回空列表，不发起任何网络请求。
        """
        if not self.enabled():
            return []
        try:
            resp = requests.get(
                self.HOST_BASE + self.INDEX_API, headers=self.headers, timeout=30, verify=True
            )
            resp.raise_for_status()
            tools = resp.json().get("tools", [])
            return tools if isinstance(tools, list) else []
        except Exception as err:
            logging.error("[ToolboxStore] get_index failed: %s", err)
            return []

    def check_update(self, tool_id: str, installed_revision: str) -> dict:
        """检查某个已安装工具是否有新版本（3.4 节 `GET toolbox/release/check`）。

        `ENABLE_TOOLBOX_STORE=False` 时直接返回 ``{"has_update": False}``，不发起网络请求。
        """
        if not self.enabled():
            return {"has_update": False}
        try:
            params = {"tool_id": tool_id, "revision": installed_revision}
            resp = requests.get(
                self.HOST_BASE + self.CHECK_UPDATE_API, headers=self.headers,
                params=params, timeout=30, verify=True,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, dict) else {"has_update": False}
        except Exception as err:
            logging.error("[ToolboxStore] check_update(%s) failed: %s", tool_id, err)
            return {"has_update": False}

    def download(self, download_url: str, expected_sha256: str) -> str:
        """下载 zip 到本地临时文件并校验 sha256（**必须**校验，3.4 节），返回临时文件路径。

        调用方负责在用完（无论成功还是失败）后删除返回的临时文件。
        :raises ToolboxStoreError: 商店未开启 / 下载失败 / sha256 校验不通过。
        """
        if not self.enabled():
            raise ToolboxStoreError(_("工具商店未开启"))
        if not expected_sha256:
            raise ToolboxStoreError(_("商店索引缺少 sha256 校验码，拒绝安装"))

        fd, path = tempfile.mkstemp(prefix="mybooks_tool_store_", suffix=".zip")
        try:
            with os.fdopen(fd, "wb") as f:
                with requests.get(
                    download_url, headers=self.headers, timeout=60, stream=True, verify=True
                ) as resp:
                    resp.raise_for_status()
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

            actual = _sha256_of(path)
            if actual.lower() != expected_sha256.lower():
                raise ToolboxStoreError(_("下载文件的 sha256 校验失败，已拒绝安装"))
            return path
        except ToolboxStoreError:
            _remove_quietly(path)
            raise
        except Exception as err:
            _remove_quietly(path)
            raise ToolboxStoreError(_("下载失败：%s") % err) from err


def _sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _remove_quietly(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 索引缓存（3.4 节：TTL 1 小时，避免每次打开 /admin/toolbox 都请求外网）
# ---------------------------------------------------------------------------

_index_cache = {"tools": [], "ts": 0.0}


def get_cached_index(force: bool = False) -> list:
    """带 TTL 缓存的商店索引；`ENABLE_TOOLBOX_STORE=False` 时缓存内容恒为空列表。"""
    now = time.time()
    if force or now - _index_cache["ts"] > INDEX_CACHE_TTL:
        _index_cache["tools"] = ToolboxStoreClient().get_index()
        _index_cache["ts"] = now
    return _index_cache["tools"]


def find_in_index(tool_id: str) -> dict:
    """从缓存索引里按 tool_id 查找一条记录，找不到返回空 dict。"""
    for entry in get_cached_index():
        if entry.get("tool_id") == tool_id:
            return entry
    return {}
