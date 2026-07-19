#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通过 FileBrowser 插件接口上传文件（如上传到 Kindle 的 documents 目录）。

参考 curl 请求（登录，免密时 username/password 均为空，响应正文即为 token）：
    curl 'http://<host>/api/login' \
      -H 'Content-Type: application/json' \
      --data-raw '{"username":"","password":"","recaptcha":""}' \
      --insecure

参考 curl 请求（第一步，POST 创建文件，仅携带 Tus-Resumable / Upload-Length，不带正文）：
    curl 'http://<host>/api/tus/mnt/us/documents/<filename>?override=false' \
      -X POST \
      -H 'Content-Length: 0' \
      -H 'Tus-Resumable: 1.0.0' \
      -H 'Upload-Length: <文件字节数>' \
      -b 'auth=<jwt>' \
      -H 'X-Auth: <jwt>' \
      --insecure

参考 curl 请求（第二步，PATCH 上传内容，URL 不带 override 参数）：
    curl 'http://<host>/api/tus/mnt/us/documents/<filename>' \
      -X PATCH \
      -H 'Content-Type: application/offset+octet-stream' \
      -H 'Tus-Resumable: 1.0.0' \
      -H 'Upload-Offset: 0' \
      -b 'auth=<jwt>' \
      -H 'X-Auth: <jwt>' \
      --insecure \
      --data-raw <文件内容>

FileBrowser 若完全未启用鉴权，登录接口可能不存在，此时可用 --no-login 跳过登录直接上传。
"""

import argparse
import os
import sys
from urllib.parse import quote

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class FileBrowserUploader:
    """通过 FileBrowser 的 /api/tus 接口上传文件到指定目录。"""

    def __init__(self, file_path):
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件未找到: {file_path}")
        self.file_path = file_path
        self.file_name = os.path.basename(file_path)

    @staticmethod
    def _normalize_base(host):
        base = host
        if not base.startswith("http://") and not base.startswith("https://"):
            base = f"http://{base}"
        return base.rstrip("/")

    def _build_url(self, host, remote_dir, override=None):
        base = self._normalize_base(host)
        remote_dir = remote_dir.strip("/")
        encoded_name = quote(self.file_name)
        path = f"{remote_dir}/{encoded_name}" if remote_dir else encoded_name
        url = f"{base}/api/tus/{path}"
        if override is not None:
            url += f"?override={'true' if override else 'false'}"
        return url

    @staticmethod
    def _auth_headers_and_cookies(auth_token):
        headers = {}
        cookies = {}
        if auth_token:
            headers["X-Auth"] = auth_token
            cookies["auth"] = auth_token
        return headers, cookies

    @classmethod
    def login(cls, host, username="", password="", timeout=60):
        """
        调用 FileBrowser 的 /api/login 接口获取 token。免密登录时用户名密码留空即可。

        响应正文本身就是 token，同时用于后续请求的 auth cookie 和 X-Auth 请求头。

        :param host:     FileBrowser 地址。
        :param username: 用户名，免密登录留空。
        :param password: 密码，免密登录留空。
        :param timeout:  请求超时时间（秒）。
        :return:         token 字符串；登录失败返回 None。
        """
        url = f"{cls._normalize_base(host)}/api/login"
        payload = {"username": username, "password": password, "recaptcha": ""}
        headers = {"Accept": "*/*", "Content-Type": "application/json"}

        print(f"[FileBrowserUploader] POST {url}")
        print(f"[FileBrowserUploader] login payload: {payload}")

        response = requests.post(url, json=payload, headers=headers, timeout=timeout, verify=False)

        print(f"[FileBrowserUploader] login status_code: {response.status_code}")
        print("[FileBrowserUploader] login response headers:")
        for key, value in response.headers.items():
            print(f"    {key}: {value}")
        print(f"[FileBrowserUploader] login response body: {response.text if response.text else '(empty)'}")

        if not response.ok:
            return None

        token = response.text.strip()
        return token or None

    def upload(self, host, remote_dir="mnt/us/documents", override=True, auth_token="", timeout=800):
        """
        按 tus 协议分两步执行上传，并打印详细的请求/响应信息，方便调试：
        1. POST 创建文件（带 override 参数，不带正文，仅声明 Upload-Length）。
        2. PATCH 上传文件内容（URL 不带 override 参数，带 Upload-Offset: 0）。

        :param host:        FileBrowser 地址，例如 "192.168.31.120" 或 "192.168.31.120:8080"，可带 http(s):// 前缀。
        :param remote_dir:  FileBrowser 中的目标目录（相对于其配置的根目录），默认 "mnt/us/documents"。
        :param override:    是否覆盖同名文件（仅影响创建文件这一步）。
        :param auth_token:  FileBrowser 登录后获取的 JWT。留空表示无密启动/匿名上传测试。
        :param timeout:     请求超时时间（秒）。
        :return:            PATCH 请求的 requests.Response 对象。
        :raises RuntimeError: 创建文件（POST）失败时抛出，此时不会继续执行 PATCH。
        """
        file_size = os.path.getsize(self.file_path)
        auth_headers, cookies = self._auth_headers_and_cookies(auth_token)
        print(f"[FileBrowserUploader] auth: {'(set)' if auth_token else '(empty, testing no-auth mode)'}")

        create_response = self._create(host, remote_dir, override, file_size, auth_headers, cookies, timeout)
        if not create_response.ok:
            raise RuntimeError(f"创建文件失败: HTTP {create_response.status_code}")

        return self._patch_content(host, remote_dir, auth_headers, cookies, timeout)

    def _create(self, host, remote_dir, override, file_size, auth_headers, cookies, timeout):
        url = self._build_url(host, remote_dir, override)
        headers = {
            "Accept": "*/*",
            "Content-Length": "0",
            "Tus-Resumable": "1.0.0",
            "Upload-Length": str(file_size),
            **auth_headers,
        }

        print(f"[FileBrowserUploader] POST {url}")
        print(f"[FileBrowserUploader] request headers: {headers}")

        response = requests.post(
            url,
            headers=headers,
            cookies=cookies or None,
            timeout=timeout,
            verify=False,
        )

        self._print_response(response)
        return response

    def _patch_content(self, host, remote_dir, auth_headers, cookies, timeout):
        url = self._build_url(host, remote_dir)
        headers = {
            "Accept": "*/*",
            "Content-Type": "application/offset+octet-stream",
            "Tus-Resumable": "1.0.0",
            "Upload-Offset": "0",
            **auth_headers,
        }

        print(f"[FileBrowserUploader] PATCH {url}")
        print(f"[FileBrowserUploader] request headers: {headers}")

        with open(self.file_path, "rb") as f:
            response = requests.patch(
                url,
                data=f,
                headers=headers,
                cookies=cookies or None,
                timeout=timeout,
                verify=False,
            )

        self._print_response(response)
        return response

    @staticmethod
    def _print_response(response):
        print(f"[FileBrowserUploader] status_code: {response.status_code}")
        print("[FileBrowserUploader] response headers:")
        for key, value in response.headers.items():
            print(f"    {key}: {value}")
        print("[FileBrowserUploader] response body:")
        print(response.text if response.text else "(empty)")


def main():
    parser = argparse.ArgumentParser(
        description="通过 FileBrowser 插件接口上传文件（如上传到 Kindle 的 documents 目录）"
    )
    parser.add_argument("file_path", help="要上传的文件路径")
    parser.add_argument("host", help="FileBrowser 地址，如 192.168.31.120 或 192.168.31.120:8080")
    parser.add_argument("--dir", default="mnt/us/documents", help="FileBrowser 中的目标目录，默认 mnt/us/documents")
    parser.add_argument("--auth", default="", help="直接指定 JWT，跳过自动登录步骤")
    parser.add_argument("--username", default="", help="登录用户名，免密登录留空")
    parser.add_argument("--password", default="", help="登录密码，免密登录留空")
    parser.add_argument("--no-login", action="store_true", help="跳过登录步骤，不携带任何鉴权信息直接上传")
    parser.add_argument("--no-override", action="store_true", help="不覆盖已存在的同名文件")
    parser.add_argument("--timeout", type=int, default=60, help="请求超时时间（秒），默认 60")

    args = parser.parse_args()

    try:
        uploader = FileBrowserUploader(args.file_path)

        auth_token = args.auth
        if not auth_token and not args.no_login:
            print(f"未指定 --auth，尝试通过 {args.host}/api/login 免密登录获取 token ...")
            auth_token = FileBrowserUploader.login(
                host=args.host,
                username=args.username,
                password=args.password,
                timeout=args.timeout,
            )
            if auth_token:
                print("登录成功，已获取 token")
            else:
                print("登录未返回有效 token，将不携带鉴权信息继续上传")

        print(f"开始上传文件: {args.file_path} -> {args.host}:/{args.dir}")
        response = uploader.upload(
            host=args.host,
            remote_dir=args.dir,
            override=not args.no_override,
            auth_token=auth_token,
            timeout=args.timeout,
        )
        if response.ok:
            print("上传成功!")
        else:
            print(f"上传失败: HTTP {response.status_code}")
            sys.exit(1)
    except FileNotFoundError as e:
        print(f"错误: {e}")
        sys.exit(1)
    except RuntimeError as e:
        print(f"错误: {e}")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"网络请求失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
