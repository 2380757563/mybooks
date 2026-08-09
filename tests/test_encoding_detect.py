# -*- coding: utf-8 -*-
"""encoding_detect 核心单元测试（standalone，不依赖 MyBooks）。

运行：python -m unittest discover -s tests 或 python tests/test_encoding_detect.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "webserver", "toolbox"))

from encoding_detect import (  # noqa: E402
    detect_encoding,
    decode_with_report,
    fix_to_utf8,
)

BIG5_TEXT = "第一章\u3000序章\n這是一本關於人工智慧發展的書籍，內容涵蓋機器學習與深度學習。"
GBK_TEXT = "第一章\u3000序章\n人工智能的发展历程，包括机器学习与深度学习。"


class TestDetectBasic(unittest.TestCase):
    """常规编码检测。"""

    def test_utf8(self):
        data = GBK_TEXT.encode("utf-8")
        r = detect_encoding(data)
        self.assertEqual(r["encoding"], "utf-8")
        self.assertGreaterEqual(r["confidence"], 0.9)
        self.assertFalse(r["mojibake"])
        self.assertFalse(r["garbage"])

    def test_gb18030(self):
        data = GBK_TEXT.encode("gb18030")
        r = detect_encoding(data)
        self.assertEqual(r["encoding"], "gb18030")
        self.assertFalse(r["mojibake"])

    def test_big5(self):
        data = BIG5_TEXT.encode("big5")
        r = detect_encoding(data)
        self.assertEqual(r["encoding"], "big5")
        self.assertFalse(r["mojibake"])

    def test_utf8_bom(self):
        data = b"\xef\xbb\xbf" + GBK_TEXT.encode("utf-8")
        r = detect_encoding(data)
        self.assertEqual(r["encoding"], "utf-8-sig")
        self.assertEqual(r["confidence"], 1.0)
        self.assertFalse(r["mojibake"])

    def test_english_text(self):
        data = "Hello world, this is a plain English book sample.\n".encode("utf-8")
        r = detect_encoding(data)
        self.assertEqual(r["encoding"], "utf-8")
        self.assertFalse(r["garbage"])

    def test_binary_garbage(self):
        data = bytes(range(256)) * 4
        r = detect_encoding(data)
        self.assertTrue(r["garbage"])

    def test_empty(self):
        r = detect_encoding(b"")
        self.assertEqual(r["encoding"], "utf-8")
        self.assertEqual(r["confidence"], 0.0)

    def test_str_input_guard(self):
        # str 输入自动按 UTF-8 编码，不应抛 TypeError
        r = detect_encoding(GBK_TEXT)
        self.assertIn("encoding", r)


class TestDecodeRoundtrip(unittest.TestCase):
    """decode_with_report / fix_to_utf8 解码一致性。"""

    def test_gb18030_roundtrip(self):
        data = GBK_TEXT.encode("gb18030")
        text, report = decode_with_report(data)
        self.assertEqual(text, GBK_TEXT)
        out, _ = fix_to_utf8(data)
        self.assertEqual(out.decode("utf-8"), GBK_TEXT)

    def test_big5_roundtrip(self):
        data = BIG5_TEXT.encode("big5")
        text, report = decode_with_report(data)
        self.assertEqual(text, BIG5_TEXT)
        out, _ = fix_to_utf8(data)
        self.assertEqual(out.decode("utf-8"), BIG5_TEXT)

    def test_bom_stripped(self):
        data = b"\xef\xbb\xbf" + GBK_TEXT.encode("utf-8")
        text, report = decode_with_report(data)
        self.assertEqual(text, GBK_TEXT)
        self.assertFalse(text.startswith("\ufeff"))


class TestMojibake(unittest.TestCase):
    """乱码反转恢复：BIG5 字节被按 GB18030 误读后以 UTF-8 存盘。"""

    def test_big5_as_gbk_saved_utf8(self):
        mojibake_str = BIG5_TEXT.encode("big5").decode("gb18030")
        data = mojibake_str.encode("utf-8")  # 乱码以 UTF-8 写入文件
        r = detect_encoding(data)
        self.assertTrue(r["mojibake"])
        self.assertEqual(r["encoding"], "big5")
        text, _ = decode_with_report(data)
        self.assertEqual(text, BIG5_TEXT)
        out, _ = fix_to_utf8(data)
        self.assertEqual(out.decode("utf-8"), BIG5_TEXT)

    def test_big5_as_gbk_high_readability_variant(self):
        # 变体：误读文本全部落在合法 CJK 区（直解可读性 96/100），
        # 统计可读性无法区分——依赖常用字占比识别并反转恢复
        BIG5_BOOK = "第一章\u3000序章\n這是一本關於人工智慧的書籍。"
        data = BIG5_BOOK.encode("big5").decode("gb18030").encode("utf-8")
        r = detect_encoding(data)
        self.assertTrue(r["mojibake"])
        self.assertEqual(r["encoding"], "big5")
        text, _ = decode_with_report(data)
        self.assertEqual(text, BIG5_BOOK)

    def test_utf8_as_gbk_all_cjk_mojibake(self):
        # UTF-8 被按 GB18030 误读后以 UTF-8 存盘，误读字全为合法 CJK
        # （浜哄伐鏅鸿兘鏈哄櫒瀛︿範）——统计可读性满分，靠常用字占比识别
        data = "人工智能机器学习\n".encode("utf-8").decode("gb18030").encode("utf-8")
        r = detect_encoding(data)
        self.assertTrue(r["mojibake"])
        text, _ = decode_with_report(data)
        self.assertEqual(text, "人工智能机器学习\n")

    def test_double_mojibake_cycle_not_loop(self):
        # 双重乱码 A→B→A 反转循环：必须标记 unrecoverable 且不进入死循环、
        # 不误采纳反转中间态（鍙岄噸 ↔ 锛堥崣）
        data = "（鍙岄噸涔辩爜鍚庣殑鏂囨湰）".encode("utf-8")
        r = detect_encoding(data)
        self.assertTrue(r["unrecoverable"])
        self.assertFalse(r["mojibake"])


class TestRobustness(unittest.TestCase):
    """真实世界的边界输入。"""

    def test_gb2312_text(self):
        # GB2312 是 GB18030 子集，应判 gb18030 而非二进制垃圾
        data = "人工智能的发展历程".encode("gb2312")
        r = detect_encoding(data)
        self.assertEqual(r["encoding"], "gb18030")
        self.assertFalse(r["garbage"])

    def test_ascii_only(self):
        # 纯 ASCII：所有编码等价，必须判 utf-8 且不误报乱码/循环
        r = detect_encoding(b"abc123")
        self.assertEqual(r["encoding"], "utf-8")
        self.assertFalse(r["mojibake"])
        self.assertFalse(r["unrecoverable"])

    def test_truncated_gbk_byte(self):
        # GBK "你好" 截断只剩首字节 0xC4：拒绝而非崩溃
        r = detect_encoding(b"\xc4")
        self.assertTrue(r["garbage"])

    def test_truncated_utf8_emoji(self):
        # UTF-8 emoji（F0 9F 98 8A）截断为 F0 9F 98：拒绝而非崩溃
        r = detect_encoding(b"\xf0\x9f\x98")
        self.assertTrue(r["garbage"])

    def test_utf16be_without_bom(self):
        # UTF-16BE 无 BOM（高位 0x00）：判垃圾拒绝，不崩溃
        r = detect_encoding("你好世界".encode("utf-16-be"))
        self.assertTrue(r["garbage"])

    def test_large_input_sampled(self):
        # 大输入：检测在 2MB 采样上进行，结果正确且不慢
        big = ("人工智能的发展历程，" * 400000).encode("utf-8")
        self.assertGreater(len(big), 3 * 1024 * 1024)
        r = detect_encoding(big)
        self.assertEqual(r["encoding"], "utf-8")
        self.assertFalse(r["garbage"])


if __name__ == "__main__":
    unittest.main()
