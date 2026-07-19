"""
KoReader 设备上传器。

KoReader 常运行在预装了 FileBrowser 插件的设备上（如刷机 Kindle），其 WiFi 接收
接口就是 FileBrowser 的 tus 上传接口，协议与 webserver/test/upload_to_filebrowser.py
中验证过的一致：
1. POST /api/login（用户名密码留空即可免密登录，响应正文即 token）
2. POST /api/tus/mnt/us/documents/<filename>?override=true 创建文件
3. PATCH /api/tus/mnt/us/documents/<filename> 上传文件内容

若 /api/login 不可用（如 FileBrowser 未启用鉴权），登录会被静默忽略，后续请求
不带鉴权信息继续尝试。
@author: PoxenStudio, 2026
"""
from urllib.parse import quote

import requests

from webserver.plugins.sending.base_uploader import BaseUploader


class KoReaderUploader(BaseUploader):
    REMOTE_DIR = "mnt/us/documents"

    def default_port(self):
        return 80

    def get_upload_url(self, base_url):
        """构建 KoReader（FileBrowser）设备的目标文件 URL（不含 override 参数）"""
        base = base_url.rstrip('/')
        return f"{base}/api/tus/{self.REMOTE_DIR}/{quote(self.filename)}"

    def _login(self, base_url):
        """尝试免密登录获取 token，失败时返回 None（不阻断后续上传）"""
        try:
            response = requests.post(
                f"{base_url}/api/login",
                json={"username": "", "password": "", "recaptcha": ""},
                headers={"Accept": "*/*", "Content-Type": "application/json"},
                timeout=self.timeout,
            )
            if response.ok and response.text.strip():
                return response.text.strip()
        except requests.exceptions.RequestException:
            pass
        return None

    def upload(self, server_url):
        try:
            base_url = server_url.rstrip('/')
            file_size = self.file_path.stat().st_size

            token = self._login(base_url)
            auth_headers = {}
            cookies = {}
            if token:
                auth_headers["X-Auth"] = token
                cookies["auth"] = token

            file_url = self.get_upload_url(base_url)

            create_response = requests.post(
                f"{file_url}?override=true",
                headers={
                    "Accept": "*/*",
                    "Content-Length": "0",
                    "Tus-Resumable": "1.0.0",
                    "Upload-Length": str(file_size),
                    **auth_headers,
                },
                cookies=cookies or None,
                timeout=self.timeout,
            )
            create_response.raise_for_status()

            with open(self.file_path, 'rb') as file:
                patch_response = requests.patch(
                    file_url,
                    data=file,
                    headers={
                        "Accept": "*/*",
                        "Content-Type": "application/offset+octet-stream",
                        "Tus-Resumable": "1.0.0",
                        "Upload-Offset": "0",
                        **auth_headers,
                    },
                    cookies=cookies or None,
                    timeout=self.timeout,
                )
            patch_response.raise_for_status()

            try:
                return {'success': True, 'data': patch_response.json()}
            except Exception:
                return {'success': True, 'data': patch_response.text}
        except Exception as e:
            return self.handle_exception(e, server_url)
