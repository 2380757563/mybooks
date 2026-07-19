import ftplib
import socket
import requests
from webserver.i18n import _
from webserver.plugins.sending.base_uploader import BaseUploader


class DuokanUploader(BaseUploader):
    def get_upload_url(self, base_url):
        """构建多看设备的上传URL"""
        if not base_url.endswith('/'):
            base_url += '/'
        return base_url + 'files'

    def upload(self, server_url):
        try:
            upload_url = self.get_upload_url(server_url)
            with open(self.file_path, 'rb') as file:
                files = {
                    'newfile': (self.filename, file, self.content_type)
                }
                response = requests.post(upload_url, files=files, timeout=self.timeout)
                response.raise_for_status()
                try:
                    return {'success': True, 'data': response.json()}
                except Exception:
                    return {'success': True, 'data': response.text}
        except Exception as e:
            return self.handle_exception(e, server_url)

    def default_port(self):
        return 12121


class BooxUploader(BaseUploader):
    def get_upload_url(self, base_url):
        """构建Boox设备的上传URL"""
        if not base_url.endswith('/'):
            base_url += '/'
        return base_url + 'api/library/upload'

    def upload(self, server_url):
        try:
            upload_url = self.get_upload_url(server_url)
            with open(self.file_path, 'rb') as file:
                files = {
                    'parent': (None, 'null'),
                    'sender': (None, 'web'),
                    'file': (self.filename, file, self.content_type),
                }
                response = requests.post(upload_url, files=files, timeout=self.timeout)
                response.raise_for_status()
                result = response.json()
                if result.get("code") != 0 or not result.get("successful"):
                    raise Exception(f"上传失败: {result}")
                return {'success': True, 'data': result}
        except Exception as e:
            return self.handle_exception(e, server_url)

    def default_port(self):
        return 8085


class HanwangUploader(BaseUploader):
    def get_upload_url(self, base_url):
        """构建汉王设备的上传URL"""
        if not base_url.endswith('/'):
            base_url += '/'
        return base_url + 'files'

    def upload(self, server_url):
        from urllib.parse import quote
        try:
            upload_url = self.get_upload_url(server_url)
            with open(self.file_path, 'rb') as file:
                files = {
                    'newfile': (self.filename, file, self.content_type)
                }
                data = {
                    'fileName': quote(self.filename)
                }
                response = requests.post(upload_url, files=files, data=data, timeout=self.timeout)
                response.raise_for_status()
                try:
                    return {'success': True, 'data': response.json()}
                except Exception:
                    return {'success': True, 'data': response.text}
        except Exception as e:
            return self.handle_exception(e, server_url)

    def default_port(self):
        return 9310


class IReaderUploader(BaseUploader):
    def get_upload_url(self, base_url):
        """构建iReader设备的上传URL"""
        if not base_url.endswith('/'):
            base_url += '/'
        return base_url + '?action=addBook'

    def upload(self, server_url):
        from requests_toolbelt.multipart.encoder import MultipartEncoder
        try:
            upload_url = self.get_upload_url(server_url)
            with open(self.file_path, 'rb') as file:
                m = MultipartEncoder(
                    fields={
                        'Filename': self.filename,
                        'Filedata': (self.filename, file, self.content_type),
                        'Upload': 'Submit Query'
                    }
                )
                headers = {'Content-Type': 'application/octet-stream'}
                response = requests.post(upload_url, data=m, headers=headers, timeout=self.timeout)
                response.raise_for_status()
                try:
                    return {'success': True, 'data': response.json()}
                except Exception:
                    return {'success': True, 'data': response.text}
        except Exception as e:
            return self.handle_exception(e, server_url)

    def default_port(self):
        return 10123


class DangdangUploader(BaseUploader):
    def get_upload_url(self, base_url):
        """构建当当设备的上传URL"""
        return base_url

    def upload(self, server_url):
        try:
            upload_url = self.get_upload_url(server_url)
            with open(self.file_path, 'rb') as file:
                files = {
                    'files[]': (self.filename, file, self.content_type)
                }
                response = requests.post(upload_url, files=files, timeout=self.timeout)
                response.raise_for_status()
                try:
                    return {'success': True, 'data': response.json()}
                except Exception:
                    return {'success': True, 'data': response.text}
        except Exception as e:
            return self.handle_exception(e, server_url)

    def default_port(self):
        return 11111


class PureLibroUploader(BaseUploader):
    def default_port(self):
        return 80


class FtpUploader(BaseUploader):
    """通过FTP协议上传书籍到设备。每个实例持有独立连接，多个请求并发时互不影响。"""

    def __init__(self, file_path, file_name=None, timeout=60, username=None, password=None, path="/"):
        super().__init__(file_path, file_name, timeout)
        self.username = username or ""
        self.password = password or ""
        self.path = path or "/"

    def handle_exception(self, e, server_url=None):
        if isinstance(e, ftplib.error_perm) and str(e).startswith("530"):
            return {
                "success": False,
                "error_type": "auth",
                "status_code": None,
                "message": _("FTP认证失败"),
                "response_text": str(e),
            }
        if isinstance(e, ftplib.error_perm):
            return {
                "success": False,
                "error_type": "ftp_perm",
                "status_code": None,
                "message": _("FTP路径不存在: %s") % self.path,
                "response_text": str(e),
            }
        if isinstance(e, ftplib.error_temp):
            return {
                "success": False,
                "error_type": "ftp_temp",
                "status_code": None,
                "message": _("FTP上传失败: %s") % e,
                "response_text": str(e),
            }
        if isinstance(e, (ConnectionRefusedError, OSError, socket.gaierror)):
            return {
                "success": False,
                "error_type": "connection",
                "status_code": None,
                "message": _("FTP连接失败: %s") % server_url,
                "response_text": str(e),
            }
        if isinstance(e, socket.timeout):
            return {
                "success": False,
                "error_type": "timeout",
                "status_code": None,
                "message": _("FTP上传失败: %s") % e,
                "response_text": str(e),
            }
        return {
            "success": False,
            "error_type": "other",
            "status_code": None,
            "message": _("FTP上传失败: %s") % e,
            "response_text": str(e),
        }

    def upload(self, server_url):
        """
        连接 FTP 服务器并上传文件。每次调用创建独立连接，并发请求互不影响。
        server_url: 形如 "192.168.1.1:21" 或 "192.168.1.1"（不含协议头）
        """
        # 解析 host 和 port
        url = server_url
        for prefix in ("ftp://", "http://", "https://"):
            if url.startswith(prefix):
                url = url[len(prefix):]
                break
        if ":" in url:
            host, port_str = url.rsplit(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                port = 21
        else:
            host = url
            port = 21

        ftp = ftplib.FTP(encoding='utf-8')
        try:
            ftp.connect(host, port, timeout=self.timeout)
            if self.username:
                ftp.login(self.username, self.password)
            else:
                ftp.login()  # 匿名登录

            # 通知服务器使用 UTF-8 编码（不是所有服务器都支持，忽略失败）
            try:
                ftp.sendcmd('OPTS UTF8 ON')
            except ftplib.Error:
                pass

            ftp.cwd(self.path)

            with open(self.file_path, "rb") as f:
                ftp.storbinary(f"STOR {self.filename}", f)

            ftp.quit()
            return {"success": True, "data": f"已上传到 {host}:{port}{self.path}/{self.filename}"}
        except Exception as e:
            try:
                ftp.close()
            except Exception:
                pass
            return self.handle_exception(e, server_url)

    def default_port(self):
        return 21
