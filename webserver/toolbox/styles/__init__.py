# -*- coding: utf-8 -*-
"""样式预设加载器：presets.json 元数据 + css 模板插值。

预设 CSS 模板占位符：{{FONT_BODY}} / {{FONT_HEAD}} / {{FONT_KAI}} / {{FONT_CODE}} /
{{LINE_HEIGHT}} / {{TITLE_SIZE}} / {{ACCENT}} / {{ACCENT_LIGHT}} / {{ACCENT_DARK}} /
{{MUTED}} / {{BORDER}} / {{QUOTE_BG}} / {{CODE_BG}} / {{TOC_GRADIENT}}；
目录样式独立为 toc_{style}.css（elegant 精致版 / cool 酷炫版 / seal 朱印版 / minimal 极简版），
通过 {{TOC_STYLE}} 嵌入主模板；响应式与特殊元素由 responsive.css 通过 {{RESPONSIVE}} 注入。
先对 toc/responsive 文件插值，再整体插值。

use_system_fonts=False 时 FONT_* 占位符替换为空（保留原书字体声明）。
font_overrides 可细粒度控制：{"body":bool,"head":bool,"kai":bool,"code":bool}，
None 时回落到 use_system_fonts。
"""

import json
import os
import re

_PRESETS_DIR = os.path.dirname(os.path.abspath(__file__))

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Z_]+)\s*\}\}")

# 模板占位符 -> presets.json 参数键
_PLACEHOLDER_MAP = {
    "FONT_BODY": "font_body",
    "FONT_HEAD": "font_head",
    "FONT_KAI": "font_kai",
    "FONT_CODE": "font_code",
    "LINE_HEIGHT": "line_height",
    "TITLE_SIZE": "title_size",
    "ACCENT": "accent",
    "ACCENT_LIGHT": "accent_light",
    "ACCENT_DARK": "accent_dark",
    "MUTED": "muted",
    "BORDER": "border",
    "QUOTE_BG": "quote_bg",
    "CODE_BG": "code_bg",
    "TOC_GRADIENT": "toc_gradient",
}

# 可选目录风格
TOC_STYLES = ("elegant", "cool", "seal", "minimal")
DEFAULT_TOC_STYLE = "elegant"


def list_presets() -> dict:
    """返回 {preset_id: 元数据 dict}（不含 css 内容）。"""
    with open(os.path.join(_PRESETS_DIR, "presets.json"), encoding="utf-8") as f:
        return json.load(f)


def list_toc_styles() -> list:
    """返回目录风格列表 [{id, name, name_en}]。"""
    return [
        {"id": "elegant", "name": "精致", "name_en": "Elegant"},
        {"id": "cool", "name": "酷炫", "name_en": "Cool"},
        {"id": "seal", "name": "朱印", "name_en": "Seal"},
        {"id": "minimal", "name": "极简", "name_en": "Minimal"},
    ]


def _interpolate(template: str, params: dict, use_system_fonts: bool,
                 font_overrides: dict = None) -> str:
    """插值模板，支持细粒度字体开关。

    font_overrides: {"body":bool,"head":bool,"kai":bool,"code":bool}，True=用系统字体，False=保留原书。
    优先级高于 use_system_fonts。
    """
    overrides = font_overrides or {}

    def _should_use_font(key: str) -> bool:
        # key like FONT_BODY -> body
        suffix = key.split("_", 1)[1].lower() if "_" in key else key.lower()
        if suffix in overrides:
            return bool(overrides[suffix])
        return bool(use_system_fonts)

    def _replace(match):
        key = match.group(1)
        if key not in _PLACEHOLDER_MAP:
            return match.group(0)
        if key in ("TOC_STYLE", "RESPONSIVE"):
            return match.group(0)  # 已在调用处替换
        if key.startswith("FONT_") and not _should_use_font(key):
            return ""
        value = params.get(_PLACEHOLDER_MAP[key], "")
        return 'font-family: %s;' % value if key.startswith("FONT_") else value

    return _PLACEHOLDER_RE.sub(_replace, template)


def get_preset_css(preset_id: str, use_system_fonts: bool = True,
                   toc_style: str = DEFAULT_TOC_STYLE,
                   font_overrides: dict = None) -> str:
    """加载指定预设模板并插值；preset_id / toc_style 非法时抛 ValueError。

    font_overrides: 细粒度字体开关，见 _interpolate。
    """
    presets = list_presets()
    if preset_id not in presets:
        raise ValueError("unknown preset: %s" % preset_id)
    if toc_style not in TOC_STYLES:
        raise ValueError("unknown toc_style: %s" % toc_style)
    params = presets[preset_id]

    css_path = os.path.join(_PRESETS_DIR, "%s.css" % preset_id)
    if not os.path.exists(css_path):
        raise ValueError("preset css missing: %s" % css_path)
    with open(css_path, encoding="utf-8") as f:
        template = f.read()

    # 目录样式：先对 toc 文件插值（含 FONT/ACCENT/GRADIENT），再嵌入主模板
    toc_path = os.path.join(_PRESETS_DIR, "toc_%s.css" % toc_style)
    if not os.path.exists(toc_path):
        raise ValueError("toc css missing: %s" % toc_path)
    with open(toc_path, encoding="utf-8") as f:
        toc_css = _interpolate(f.read(), params, use_system_fonts, font_overrides)
    template = template.replace("{{TOC_STYLE}}", toc_css)

    # 响应式与特殊元素补齐
    responsive_path = os.path.join(_PRESETS_DIR, "responsive.css")
    if os.path.exists(responsive_path):
        with open(responsive_path, encoding="utf-8") as f:
            responsive_css = _interpolate(f.read(), params, use_system_fonts, font_overrides)
        if "{{RESPONSIVE}}" in template:
            template = template.replace("{{RESPONSIVE}}", responsive_css)
        else:
            template = template.rstrip() + "\n\n/* ── responsive injected ── */\n" + responsive_css

    return _interpolate(template, params, use_system_fonts, font_overrides)
