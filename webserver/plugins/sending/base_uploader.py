import requests
from pathlib import Path


class BaseUploader:
    def __init__(self, file_path, file_name=None, timeout=60):
        self.file_path = Path(file_path)
        self.filename = self.file_path.name if file_name is None else file_name
        self.file_extension = self.file_path.suffix.lower()
        self.content_type = self._get_content_type()
        self.timeout = timeout
        self._check_file()

    def _check_file(self):
        if not self.file_path.exists():
            raise FileNotFoundError(f"文件不存在: {self.file_path}")
        if self.file_extension not in ['.epub', '.azw3', '.pdf', '.txt']:
            raise ValueError(f"不支持的文件格式: {self.file_extension}, 只支持epub, azw3和pdf文件")

    def _get_content_type(self):
        if self.file_extension == '.epub':
            return 'application/epub+zip'
        elif self.file_extension == '.pdf':
            return 'application/pdf'
        return 'application/octet-stream'

    def handle_exception(self, e, server_url=None):
        # 统一异常处理，返回结构化错误信息
        if hasattr(e, 'response') and e.response is not None:
            # HTTP错误
            return {
                'success': False,
                'error_type': 'http',
                'status_code': e.response.status_code,
                'message': f"HTTP错误: {e.response.status_code}",
                'response_text': e.response.text
            }
        if isinstance(e, requests.exceptions.Timeout):
            return {
                'success': False,
                'error_type': 'timeout',
                'status_code': None,
                'message': f"上传超时: {self.file_path}",
                'response_text': str(e)
            }
        elif isinstance(e, requests.exceptions.ConnectionError):
            return {
                'success': False,
                'error_type': 'connection',
                'status_code': None,
                'message': f"连接服务器失败: {server_url}",
                'response_text': str(e)
            }
        else:
            return {
                'success': False,
                'error_type': 'other',
                'status_code': None,
                'message': f"上传失败: {str(e)}",
                'response_text': str(e)
            }

    def get_upload_url(self, base_url):
        """
        子类可重写此方法来构建特定的上传URL

        Args:
            base_url: 基础URL（如 http://192.168.1.1:8080）

        Returns:
            完整的上传URL
        """
        return base_url

    def upload(self, server_url):
        raise NotImplementedError("子类需实现 upload 方法")

    def default_port(self):
        """子类可重写此方法来指定默认端口"""
        return 12121
