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
        self.assertFalse(r["garbage"])  # 空文件不是垃圾，绝不报错拒绝

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

    def test_mid_signal_mojibake_still_recovered(self):
        # 中信号乱码：原文常用字率中等（ratio~0.4，如古文/专业书）被 BIG5-as-GBK
        # 误读，恢复差值仅 ~+16——受保护门槛（+10）不得误伤，仍须恢复
        mid = "昔者莊周夢為胡蝶，栩栩然胡蝶也，自喻適志與！不知周也。"
        data = mid.encode("big5").decode("gb18030").encode("utf-8")
        r = detect_encoding(data)
        self.assertTrue(r["mojibake"], r["reasons"])
        self.assertEqual(r["encoding"], "big5")
        text, _ = decode_with_report(data)
        self.assertEqual(text, mid)


class TestIdempotency(unittest.TestCase):
    """幂等性：正常 UTF-8 中文必须原样输出，绝不能反转成乱码。

    UTF-8 中文的字节组合（如 E4 BD A0）在 GBK 字典中可能恰好合法，
    反转候选必须无法胜过 UTF-8 直解（常用字保护 + 总分打平直解优先）。
    """

    def _assert_idempotent(self, text):
        data = text.encode("utf-8")
        r = detect_encoding(data)
        self.assertEqual(r["encoding"], "utf-8", r["reasons"])
        self.assertFalse(r["mojibake"], r["reasons"])
        self.assertFalse(r["garbage"])
        out, _ = fix_to_utf8(data)
        self.assertEqual(out.decode("utf-8"), text)

    def test_utf8_ni_hao_shi_jie(self):
        # 你好世界 UTF-8（E4 BD A0 E5 A5 BD 在 GBK 中全合法）
        self._assert_idempotent("你好世界")

    def test_utf8_mixed_ascii_chinese(self):
        self._assert_idempotent("The quick brown fox 跳过了 lazy dog，12345。")

    def test_utf8_novel_paragraph(self):
        # 简体小说段落
        self._assert_idempotent(
            "第一章　序章\n夜色渐深，他站在窗前，望着远处灯火阑珊的城市。"
            "这一去，不知何时才能回来。")
        # 繁体小说段落
        self._assert_idempotent(
            "第一章　序章\n夜色漸深，他站在窗前，望著遠處燈火闌珊的城市。"
            "這一去，不知何時才能回來。")

    def test_utf8_long_text(self):
        self._assert_idempotent(
            "人工智能的发展历程，包括机器学习与深度学习。" * 50
            + "这是对幂等性的长文回归验证。" * 30)

    def test_utf8_rare_chars(self):
        # 僻字密集（常用字占比为 0）：不得因评分低/反转候选微胜而误判 GBK/BIG5
        self._assert_idempotent("龘靐齉爨癵籱饢驫麣纞")

    def test_utf8_rare_chars_long(self):
        self._assert_idempotent("龘靐齉爨癵籱饢驫麣纞" * 20)

    def test_utf8_repeated_rare_char(self):
        # 低熵 + 零常用字：重复生僻字不得误判
        self._assert_idempotent("龘" * 50000)

    def test_ascii_punctuation_only(self):
        # 纯 ASCII 符号全集：所有编码等价，锁死 utf-8 直解
        self._assert_idempotent("""1234567890!@#$%^&*()_+-=[]{};':",./<>?""")

    def test_repeated_single_byte(self):
        # 低熵重复单字节：不弃权、不误判
        self._assert_idempotent("A" * 100000)


class TestSamplingBoundary(unittest.TestCase):
    """采样边界：多字节字符横跨 2MB 采样边界时检测不得失败或损坏。"""

    def test_utf8_emoji_across_boundary(self):
        line = ("人工智能的发展历程" * 100000).encode("utf-8")  # 27 字节/行
        head = line[:27 * 77672] + b"abcdef"  # 2097150 字节，完整合法
        data = head + "😊".encode("utf-8") + "后续内容".encode("utf-8")
        self.assertGreater(len(data), 2 * 1024 * 1024)
        r = detect_encoding(data)
        self.assertEqual(r["encoding"], "utf-8")
        self.assertFalse(r["garbage"])
        text, _ = decode_with_report(data)
        self.assertEqual(text, data.decode("utf-8"))

    def test_gb18030_4byte_across_boundary(self):
        line = ("人工智能的发展历程" * 200000).encode("gb18030")  # 18 字节/行
        head = line[:2097150]  # 完整合法
        data = head + "𠀀".encode("gb18030") + "GBK内容".encode("gb18030")
        self.assertGreater(len(data), 2 * 1024 * 1024)
        r = detect_encoding(data)
        self.assertEqual(r["encoding"], "gb18030")
        self.assertFalse(r["garbage"])
        text, _ = decode_with_report(data)
        self.assertIn("𠀀", text)


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

    def test_single_long_line_no_newline(self):
        # 超长单行（>2MB、无换行符）：检测不依赖 \n 统计
        line = ("ACGT" * 400000 + "中间中文段落" + "TGC" * 400000).encode("utf-8")
        self.assertGreater(len(line), 2 * 1024 * 1024)
        self.assertNotIn(b"\n", line)
        r = detect_encoding(line)
        self.assertEqual(r["encoding"], "utf-8")
        self.assertFalse(r["garbage"])
        text, _ = decode_with_report(line)
        self.assertIn("中间中文段落", text)

    def test_nul_byte_utf8(self):
        # NUL 混入：判垃圾拒绝（不静默截断 NUL 之后的内容）
        r = detect_encoding("你好\x00世界".encode("utf-8"))
        self.assertTrue(r["garbage"])

    def test_nul_byte_gb18030(self):
        r = detect_encoding("你好\x00世界".encode("gb18030"))
        self.assertTrue(r["garbage"])


if __name__ == "__main__":
    unittest.main()
