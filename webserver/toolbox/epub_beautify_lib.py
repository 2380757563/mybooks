# -*- coding: utf-8 -*-
"""EPUB 美化核心库。

对既有 EPUB 做无损美化（生成新书模式，原书零改动）：
1. **目录**：书内已有目录页时仅样式化；无目录页时从 NCX/nav（EPUB3 nav）
   生成 ``mb-toc.xhtml`` 目录页并注册进 OPF（manifest + spine，幂等）；
2. **章节名**：正文条目三层识别章节标题（h1-h6 / 已知标题类 / 段落文本
   章节正则，后者移植自 hehetoshang/txt2epub-next，MIT）并标记 ``mb-ch``，
   章首段标记 ``data-mb-first``；
3. **字体与排版**：注入 ``mb-beauty.css``（styles/ 预设模板插值），覆盖层
   方式追加，不删除原书任何文件与规则。

EPUB 容器读写（container → OPF → manifest/spine、mimetype 置首 ZIP_STORED
规范重写、编码兜底）沿用「正文查找替换」工具已验证的实现模式。
"""

import re
import zipfile
import xml.etree.ElementTree as ET
from urllib.parse import quote, unquote

from . import chapter_patterns

_NS_CONTAINER = 'urn:oasis:names:tc:opendocument:xmlns:container'
_NS_OPF = 'http://www.idpf.org/2007/opf'
_NS_XHTML = 'http://www.w3.org/1999/xhtml'
_NS_DTBNCX = 'http://www.daisy.org/z3986/2005/ncx/'

# 前置页文件名特征（跳过章节标题标记，避免把"书籍信息/作者简介"当章节名）
# 用 \b 避免 index 误伤 index_split_001.html 等分章文件
_FRONT_FILE_RE = re.compile(
    r'\b(?:cover|titlepage|title-page|title|banquan|copyright|colophon|imprint|'
    r'feiye|zuozhe|author|mulu|toc|nav|contents|index|description|introduction|'
    r'explanation|version|preface|foreword|afterword|half-title|halftitle|dedication)\b',
    re.IGNORECASE,
)
# body 上的 epub:type 前置标记（只匹配属性上下文，避免 id 名里的 toc 误伤）
_FRONT_TYPE_RE = re.compile(
    r'epub:type\s*=\s*["\'][^"\']*\b(cover|title-page|titlepage|copyright|colophon|frontmatter|toc|imprint)\b',
    re.IGNORECASE,
)
# 已知章节标题类名关键词（配合 h/p 块文本规则）
_TITLE_CLASS_RE = re.compile(
    r'(chapter-title|chaptertitle|contenttitle|pretxttitle|head|title-line|'
    r'title|caption-title|chapter)',
    re.IGNORECASE,
)
# 块级元素扫描（h1-6 / p / blockquote / li；div 单独处理无嵌套形式）
_BLOCK_RE = re.compile(
    r'<(h[1-6]|p|blockquote|li)\b([^>]*)>(.*?)</\1>',
    re.DOTALL | re.IGNORECASE,
)
# 无嵌套 div（内含标签但不含 div 层级）——Calibre 类汤书的标题段常是 div
_SIMPLE_DIV_RE = re.compile(
    r'<div\b([^>]*)>((?:(?!</?div)[\s\S])*?)</div>',
    re.DOTALL | re.IGNORECASE,
)
# 标签/注释（提取文本段用）
_TAG_RE = re.compile(
    r'(<(?:[^>"\']*|"[^"]*"|\'[^\']*\')*>|<!--[\s\S]*?-->)',
    re.DOTALL,
)
# 从块文本里剥掉内联标签
_INLINE_RE = re.compile(r'<[^>]+>')

MB_CSS_NAME = 'mb-beauty.css'
MB_TOC_NAME = 'mb-toc.xhtml'
# 生成目录页的最大条目数（超长 NCX 如网文 2137 条时截断）
MAX_TOC_ENTRIES = 500


# ── EPUB 容器基础（沿用 text_replace 模式）────────────────────────────────────

def _read_zip_entries(path: str) -> dict:
    """读取 zip 全部文件条目 {name: bytes}（跳过目录项）。"""
    entries = {}
    with zipfile.ZipFile(path, 'r') as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            entries[info.filename] = zf.read(info.filename)
    return entries


def _write_zip(entries: dict, out_path: str) -> None:
    """规范重写 zip：mimetype 置首且 ZIP_STORED，其余 DEFLATED。"""
    order = [k for k in entries if k != 'mimetype']
    with zipfile.ZipFile(out_path, 'w') as zout:
        zout.writestr(
            zipfile.ZipInfo('mimetype'),
            entries.get('mimetype', b'application/epub+zip'),
            compress_type=zipfile.ZIP_STORED,
        )
        for name in order:
            zout.writestr(name, entries[name], compress_type=zipfile.ZIP_DEFLATED)


def _decode(data: bytes) -> str:
    """UTF-8 优先，失败用检测器兜底（复用 text_replace 思路的简化版）。"""
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        try:
            return data.decode('gb18030')
        except UnicodeDecodeError:
            return data.decode('utf-8', errors='replace')


# ── OPF 解析 ──────────────────────────────────────────────────────────────────

def _q(tag, ns=_NS_OPF):
    return '{%s}%s' % (ns, tag)


class OpfContext:
    """解析后的 OPF 上下文。"""

    def __init__(self):
        self.opf_path = ''
        self.opf_dir = ''
        self.title = ''
        self.manifest = {}       # id -> {'href','mt','props'}
        self.spine = []          # [(idref, linear_bool)]
        self.ncx_path = ''       # zip 内 NCX 路径（可能为空）
        self.nav_path = ''       # zip 内 EPUB3 nav 文档路径（可能为空）
        self.nav_id = ''         # nav 文档的 manifest id


def _parse_opf(entries: dict) -> OpfContext:
    """从 container.xml 定位 OPF 并解析 manifest/spine/NCX/nav。"""
    ctx = OpfContext()
    container = entries.get('META-INF/container.xml')
    if not container:
        raise RuntimeError('缺少 META-INF/container.xml')
    root = ET.fromstring(_decode(container))
    full_path = ''
    for rf in root.iter(_q('rootfile', _NS_CONTAINER)):
        full_path = rf.get('full-path') or ''
        break
    if not full_path or full_path not in entries:
        raise RuntimeError('无法定位 OPF 文件')
    ctx.opf_path = full_path
    ctx.opf_dir = full_path.rsplit('/', 1)[0] + '/' if '/' in full_path else ''

    opf = ET.fromstring(_decode(entries[full_path]))
    # 标题（dc:title，Dublin Core 命名空间）
    for t in opf.iter(_q('title', 'http://purl.org/dc/elements/1.1/')):
        ctx.title = (t.text or '').strip()
        break
    # manifest
    for item in opf.iter(_q('item')):
        iid = item.get('id') or ''
        href = item.get('href') or ''
        mt = (item.get('media-type') or '').lower()
        props = item.get('properties') or ''
        ctx.manifest[iid] = {'href': href, 'mt': mt, 'props': props}
        if mt == 'application/x-dtbncx+xml':
            ctx.ncx_path = _snap_entry(entries, _resolve_zip(ctx.opf_dir, href))
        if 'nav' in props.split():
            ctx.nav_path = _snap_entry(entries, _resolve_zip(ctx.opf_dir, href))
            ctx.nav_id = iid
    # spine
    spine = opf.find(_q('spine'))
    if spine is not None:
        for itemref in spine.iter(_q('itemref')):
            ctx.spine.append((itemref.get('idref') or '', itemref.get('linear', 'yes').lower() != 'no'))
    return ctx


def _resolve_zip(base_dir: str, href: str) -> str:
    """把 OPF 相对 href 解析为 zip 内绝对路径。"""
    href = href.split('#')[0].split('?')[0]
    if href.startswith('/'):
        return href.lstrip('/')
    return base_dir + href


def _snap_entry(entries: dict, path: str) -> str:
    """把解析出的路径对齐到 zip 实际条目名。

    部分制作工具（如掌书系）OPF manifest 的 href 为百分号编码
    （``%2A_%2A%3A…``），而 zip 条目名是原始字符（``*_ *:_|…``），
    直接用解析路径查 entries 会 KeyError；此处先精确匹配，
    再回退到解码名，均未命中则原样返回（保持旧行为）。
    """
    if path in entries:
        return path
    try:
        decoded = unquote(path)
    except Exception:
        return path
    if decoded in entries:
        return decoded
    return path


def _quote_href(path: str) -> str:
    """把 zip 内路径转为可写入 XHTML href 的百分号编码形式（保留 / 与锚点）。"""
    if '#' in path:
        body, anchor = path.split('#', 1)
        return quote(body, safe='/') + '#' + anchor
    return quote(path, safe='/')


def _snap_with_anchor(entries: dict, ref: str) -> str:
    """_snap_entry 的带锚点版本：仅对路径主体对齐，锚点原样保留。"""
    if '#' in ref:
        body, anchor = ref.split('#', 1)
        return _snap_entry(entries, body) + '#' + anchor
    return _snap_entry(entries, ref)


def _relative_href(from_zip_path: str, to_zip_path: str) -> str:
    """计算 zip 内两文件间的相对 URL（复用 curie 思路）。"""
    from_parts = from_zip_path.split('/')
    to_parts = to_zip_path.split('/')
    from_dirs = from_parts[:-1]
    to_dirs = to_parts[:-1]
    common = 0
    for a, b in zip(from_dirs, to_dirs):
        if a == b:
            common += 1
        else:
            break
    up = len(from_dirs) - common
    return '../' * up + '/'.join(to_parts[common:])


def _text_entries(ctx: OpfContext, entries: dict = None) -> list:
    """按 spine 顺序返回正文（xhtml/html）条目 zip 路径列表（linear=yes）。

    entries 提供时对解析路径做条目名对齐（兼容百分号编码 href 的书）。
    """
    out = []
    for idref, linear in ctx.spine:
        if not linear:
            continue
        item = ctx.manifest.get(idref)
        if not item:
            continue
        if item['mt'] not in ('application/xhtml+xml', 'text/html'):
            continue
        path = _resolve_zip(ctx.opf_dir, item['href'])
        if entries is not None:
            path = _snap_entry(entries, path)
        out.append(path)
    return out


def _is_front_file(zip_path: str) -> bool:
    """文件名是否疑似前置页（封面/版权/目录等）。"""
    base = zip_path.rsplit('/', 1)[-1]
    return bool(_FRONT_FILE_RE.search(base))


# ── NCX / nav 解析 ────────────────────────────────────────────────────────────

def _parse_ncx(data: bytes) -> list:
    """解析 NCX 为 [(level, title, src)] 扁平列表（navPoint 嵌套 = 层级）。"""
    items = []
    root = ET.fromstring(_decode(data))

    def walk(elem, level):
        for nav_point in elem:
            if nav_point.tag != _q('navPoint', _NS_DTBNCX):
                continue
            label = nav_point.find(_q('navLabel', _NS_DTBNCX))
            title = ''
            if label is not None:
                t = label.find(_q('text', _NS_DTBNCX))
                title = (t.text or '').strip() if t is not None else ''
            content = nav_point.find(_q('content', _NS_DTBNCX))
            src = content.get('src', '') if content is not None else ''
            items.append((level, title, src))
            walk(nav_point, level + 1)

    nav_map = root.find(_q('navMap', _NS_DTBNCX))
    if nav_map is not None:
        walk(nav_map, 0)
    return items


def _parse_nav_doc(data: bytes) -> list:
    """解析 EPUB3 nav 文档（epub:type=toc 的 nav）为 [(level, title, href)]。"""
    items = []
    root = ET.fromstring(_decode(data))
    nav = None
    for n in root.iter(_q('nav', _NS_XHTML)):
        ntype = n.get('{%s}type' % 'http://www.idpf.org/2007/ops') or ''
        if 'toc' in ntype:
            nav = n
            break
    if nav is None:
        return items

    def walk(ul, level):
        for li in list(ul):
            if li.tag != _q('li', _NS_XHTML):
                continue
            a = li.find(_q('a', _NS_XHTML))
            title = ''
            href = ''
            if a is not None:
                title = ''.join(a.itertext()).strip()
                href = a.get('href', '')
            items.append((level, title, href))
            child = li.find(_q('ol', _NS_XHTML))
            if child is None:
                child = li.find(_q('ul', _NS_XHTML))
            if child is not None:
                walk(child, level + 1)

    first_ul = nav.find(_q('ol', _NS_XHTML)) or nav.find(_q('ul', _NS_XHTML))
    if first_ul is not None:
        walk(first_ul, 0)
    return items


# ── 目录页生成 ────────────────────────────────────────────────────────────────

# 标题已自带中文序号（第X章）或数字前缀（01.）时不再注入编号
_NUM_PREFIX_RE = re.compile(
    r'^(?:第\s*[0-9零〇一二三四五六七八九十百千万兩两]+\s*[章节回篇卷部集]|\d{1,4}\s*[.、．]?)',
)


def _build_toc_page(toc_items: list, ref_dir: str, truncated: bool = False,
                    toc_style: str = 'elegant') -> bytes:
    """生成 mb-toc.xhtml。toc_items = [(level, title, zip_href)]。

    zip_href 为条目目标文件在 zip 内的路径（可含 #锚点）。
    ref_dir 为 toc 页所在目录（opf_dir），条目 href 相对它计算。
    toc_style: elegant/cool/minimal 用 ol/li 结构；seal（朱印风）用双栏表格。

    注意：使用**普通 div 结构而非 <nav epub:type="toc">**——nav 文档会被
    手机阅读器（多看/KOReader/微信读书等）当作目录数据源特殊处理（跳过
    渲染或不应用书内 CSS），普通 div 目录页在所有阅读器都当普通页面渲染。
    装饰元素（副题/印章/收尾符）用真实元素生成，不依赖 ::before/::after 伪元素。
    """
    num = 0
    entries = []
    for level, title, zip_href in toc_items:
        if not title:
            continue
        if '#' in zip_href:
            zip_path, anchor = zip_href.split('#', 1)
            anchor = '#' + anchor
        else:
            zip_path, anchor = zip_href, ''
        rel = _quote_href(_relative_href(ref_dir + MB_TOC_NAME, zip_path)) + anchor
        lv = 'lv1' if level <= 1 else 'lv2'
        num_span = ''
        if lv == 'lv1':
            num += 1
            if not _NUM_PREFIX_RE.match(title):
                num_span = '<span class="mb-toc-num">%02d</span>' % num
        if toc_style == 'seal':
            # 朱印式：双栏表格行（编号在链接内，右列装饰标记）
            td_cls = ' class="mb-toc-l2"' if lv == 'lv2' else ''
            entries.append(
                '<tr><td%s><a href="%s">%s %s</a></td>'
                '<td class="mb-toc-mark">\\　✦</td></tr>'
                % (td_cls, rel, num_span, _esc(title))
            )
        else:
            entries.append(
                '<li class="%s">%s<a href="%s">%s</a></li>'
                % (lv, num_span, rel, _esc(title))
            )
    trunc = ('<p class="mb-toc-truncated">……（目录过长，仅显示前 %d 条）</p>' % MAX_TOC_ENTRIES) if truncated else ''

    if toc_style == 'seal':
        head = (
            '<h1>目 录<span class="mb-toc-seal">隐</span>'
            '<span class="mb-toc-sub">CONTENT</span></h1>'
        )
        body_rows = '<table class="mulu"><tbody>\n%s\n</tbody></table>' % '\n'.join(entries)
    else:
        head = '<h1>目　录<span class="mb-toc-sub">C O N T E N T S</span></h1>'
        body_rows = '<ol>%s</ol>' % '\n'.join(entries)

    xhtml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        '<head><title>目录</title>'
        '<link rel="stylesheet" type="text/css" href="%s"/></head>\n'
        '<body class="mb-toc-page" id="mb-toc">\n'
        '<div class="mb-toc">\n'
        '%s\n'
        '%s\n'
        '%s\n'
        '<p class="mb-toc-end">◆</p>\n'
        '</div>\n'
        '</body>\n'
        '</html>'
    ) % (MB_CSS_NAME, head, body_rows, trunc)
    return xhtml.encode('utf-8')


def _esc(text: str) -> str:
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


# ── 章节标题标记 ──────────────────────────────────────────────────────────────

def _block_text(inner_html: str) -> str:
    """块内纯文本（剥内联标签 + 压空白）。"""
    text = _INLINE_RE.sub('', inner_html)
    text = text.replace('&nbsp;', ' ').replace('&#160;', ' ')
    return ' '.join(text.split())


def _looks_like_title(text: str) -> bool:
    """块文本是否像标题（配合类名关键词时用更宽松的长度）。"""
    if not text or len(text) > 80:
        return False
    if text.endswith(('。', '！', '？', '；', '.', '!', '?', ';')):
        return False
    return True


def _add_class(attrs: str, cls: str) -> str:
    """给开标签属性串追加 class（已含 class 则合并）。"""
    m = re.search(r'\bclass\s*=\s*"([^"]*)"', attrs)
    if m:
        existing = m.group(1)
        if cls in existing.split():
            return attrs
        return attrs[:m.start(1)] + (existing + ' ' + cls) + attrs[m.end(1):]
    return attrs + ' class="%s"' % cls


def _inject_css_link(html_str: str, rel_href: str) -> str:
    """在 <head> 末尾注入 mb-beauty.css 引用（幂等）。"""
    if 'mb-beauty.css' in html_str:
        return html_str
    link = '<link rel="stylesheet" type="text/css" href="%s"/>' % rel_href
    m = re.search(r'</head>', html_str, re.IGNORECASE)
    if m:
        return html_str[:m.start()] + link + html_str[m.start():]
    # 无 head：在 <body> 前补一个
    m = re.search(r'<body\b', html_str, re.IGNORECASE)
    if m:
        return html_str[:m.start()] + '<head>' + link + '</head>' + html_str[m.start():]
    return html_str


# 目录页文件名特征（书内目录文档）
_TOC_FILE_RE = re.compile(r'(mulu|toc|contents|nav)', re.IGNORECASE)
# 目录文档标记（body 上打 mb-toc-page 供 CSS 精确作用）
_TOC_BODY_CLASS = 'mb-toc-page'


def _is_toc_doc(zip_path: str, html_str: str = '') -> bool:
    """判断条目是否为书内目录页：文件名（mulu/toc/nav/contents）或
    ``<nav epub:type="toc">`` 结构。"""
    base = zip_path.rsplit('/', 1)[-1]
    if _TOC_FILE_RE.search(base):
        return True
    return bool(re.search(r'<nav\b[^>]*epub:type\s*=\s*["\']toc', html_str, re.IGNORECASE))


def _mark_toc_page_body(html_str: str) -> str:
    """给目录页 <body> 打 mb-toc-page 类（幂等）。"""
    if _TOC_BODY_CLASS in html_str:
        return html_str
    m = re.search(r'<body\b([^>]*)>', html_str, re.IGNORECASE)
    if not m:
        return html_str
    new_attrs = _add_class(m.group(1), _TOC_BODY_CLASS)
    return html_str[:m.start()] + '<body%s>' % new_attrs + html_str[m.end():]


def _decorate_toc_page(html_str: str) -> str:
    """给书内普通目录页注入真实装饰元素（幂等）：标题英文副题 + 收尾 ◆。

    使用真实元素而非 ::before/::after content（移动阅读器兼容性差）。
    """
    if 'mb-toc-sub' in html_str and 'mb-toc-end' in html_str:
        return html_str
    # 标题内注入英文副题 span（朱印式双行标题）
    m = re.search(r'(<h[12]\b[^>]*>)(.*?)(</h[12]>)', html_str, re.S | re.IGNORECASE)
    if m and 'mb-toc-sub' not in m.group(2):
        sub = '<span class="mb-toc-sub">C O N T E N T S</span>'
        html_str = html_str[:m.end(2)] + sub + html_str[m.start(3):]
    # body 末尾注入收尾装饰符
    if 'mb-toc-end' not in html_str:
        m2 = re.search(r'</body>', html_str, re.IGNORECASE)
        if m2:
            html_str = html_str[:m2.start()] + '<p class="mb-toc-end">◆</p>' + html_str[m2.start():]
    return html_str


_MB_SEP = '<div class="mb-ch-sep"></div>'


def mark_chapters_in_html(html_str: str) -> tuple:
    """正文条目内标记章节标题（mb-ch）与章首段（data-mb-first）。

    幂等：已含 mb-ch 的条目直接返回原样。
    :return: (new_html, marked_count)
    """
    if 'mb-ch' in html_str or '<html' not in html_str.lower():
        return html_str, 0
    if _FRONT_TYPE_RE.search(html_str[:4000]):
        # body 声明为前置类型（cover/title-page/copyright…）——不标记
        return html_str, 0

    marked = 0
    first_done = False
    heading_seen = False

    def _handle_block(tag, attrs, inner, is_div=False):
        nonlocal marked, heading_seen, first_done
        cls_attr = attrs or ''
        text = _block_text(inner)
        if not text.strip():
            return None
        is_heading = False
        if _TITLE_CLASS_RE.search(cls_attr) and _looks_like_title(text):
            is_heading = True
        elif chapter_patterns.paragraph_is_heading(text):
            is_heading = True
        if is_heading:
            new_attrs = _add_class(cls_attr, 'mb-ch')
            marked += 1
            heading_seen = True
            # 下方长线分隔（实色卡片外，兼容所有阅读器）
            return '<%s%s>%s</%s>%s' % (tag, new_attrs, inner, tag, _MB_SEP)
        if heading_seen and not first_done and not is_div:
            new_attrs = cls_attr + ' data-mb-first="true"'
            first_done = True
            return '<%s%s>%s</%s>' % (tag, new_attrs, inner, tag)
        return None

    # 第一遍：替换 h/p/blockquote/li 块
    def _replace_block(m):
        tag, attrs, inner = m.group(1), m.group(2), m.group(3)
        out = _handle_block(tag, attrs, inner)
        return out if out is not None else m.group(0)

    new_html = _BLOCK_RE.sub(_replace_block, html_str)
    if not first_done:
        # 第二遍：无嵌套 div（Calibre 类汤）
        def _replace_div(m):
            attrs, inner = m.group(1), m.group(2)
            out = _handle_block('div', attrs, inner, is_div=True)
            return out if out is not None else m.group(0)

        new_html = _SIMPLE_DIV_RE.sub(_replace_div, new_html)
    return new_html, marked


# ── 分析（preview 用）─────────────────────────────────────────────────────────

def analyze_epub(epub_path: str, sample_limit: int = 20) -> dict:
    """扫描 EPUB，返回美化方案分析（不写文件）。

    :param sample_limit: 标题统计采样的正文文件数上限（防超大书卡死）。
    """
    entries = _read_zip_entries(epub_path)
    ctx = _parse_opf(entries)
    text_entries = _text_entries(ctx, entries)
    css_names = [n for n in entries if n.lower().endswith('.css')]
    has_fontface = False
    calibre_soup = False
    for n in css_names:
        css = _decode(entries[n])
        if '@font-face' in css:
            has_fontface = True
        if '.calibre' in css or 'class="calibre' in _decode(entries.get('META-INF/container.xml', b'')):
            pass
    for n in css_names:
        if '.calibre' in _decode(entries[n]):
            calibre_soup = True
            break

    ncx_count = 0
    if ctx.ncx_path and ctx.ncx_path in entries:
        ncx_count = len(_parse_ncx(entries[ctx.ncx_path]))
    nav_count = 0
    if ctx.nav_path and ctx.nav_path in entries:
        nav_count = len(_parse_nav_doc(entries[ctx.nav_path]))

    has_inbook_toc = any(
        _is_front_file(t) and any(k in t.lower() for k in ('mulu', 'toc', 'nav', 'contents'))
        for t in text_entries
    )

    h_stats = {'h1': 0, 'h2': 0, 'h3': 0, 'h4': 0, 'h5': 0, 'h6': 0}
    text_headings = 0
    sampled = 0
    for t in text_entries:
        if _is_front_file(t):
            continue
        if sampled >= sample_limit:
            break
        sampled += 1
        html = _decode(entries[t])
        for tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            h_stats[tag] += len(re.findall(r'<%s\b' % tag, html, re.IGNORECASE))
        for m in _BLOCK_RE.finditer(html):
            if chapter_patterns.paragraph_is_heading(_block_text(m.group(3))):
                text_headings += 1

    return {
        'title': ctx.title,
        'text_entries': len(text_entries),
        'css_files': css_names,
        'has_fontface': has_fontface,
        'calibre_soup': calibre_soup,
        'has_inbook_toc': has_inbook_toc,
        'ncx_entries': ncx_count,
        'nav_entries': nav_count,
        'heading_stats': h_stats,
        'text_headings': text_headings,
    }


# ── 主流程 ────────────────────────────────────────────────────────────────────

def _set_page_progression(opf_str: str, direction: str) -> str:
    """幂等设置 spine 的 page-progression-direction（竖排书右翻的标准信号）。

    已有该属性则更新其值，没有则追加；找不到 spine 标签时原样返回。
    """
    m = re.search(r'<spine\b[^>]*>', opf_str)
    if not m:
        return opf_str
    tag = m.group(0)
    if re.search(r'page-progression-direction\s*=', tag):
        new_tag = re.sub(
            r'page-progression-direction\s*=\s*(["\'])[^"\']*\1',
            'page-progression-direction="%s"' % direction,
            tag, count=1,
        )
    else:
        # 插到闭合符前（兼容 <spine> 与 <spine toc="ncx">）
        new_tag = tag[:-1].rstrip() + ' page-progression-direction="%s">' % direction
    if new_tag == tag:
        return opf_str
    return opf_str[:m.start()] + new_tag + opf_str[m.end():]


def beautify(
    epub_path: str,
    out_path: str,
    preset_css: str,
    max_toc_entries: int = MAX_TOC_ENTRIES,
    toc_style: str = 'elegant',
    page_progression: str = None,
) -> dict:
    """执行美化并写新 EPUB。

    :param preset_css: 已插值的 mb-beauty.css 内容（styles.get_preset_css）。
    :param page_progression: 'rtl' 时把 spine 设为从左向右翻页（竖排预设用），
        None 保持原书设置。
    :return: 统计 dict（marked_headers / toc_generated / toc_entries /
        injected_css / chapters / rtl）
    """
    entries = _read_zip_entries(epub_path)
    ctx = _parse_opf(entries)
    text_entries = _text_entries(ctx, entries)

    # ── 1. 目录：生成普通结构目录页 / 替换 nav 语义目录页 / 保留普通目录页 ──
    # 手机阅读器（多看/KOReader/微信读书等）把 <nav epub:type="toc"> 文档当
    # 目录数据源特殊处理（跳过渲染或不应用书内 CSS），因此：
    #   - 无书内目录页 → 生成 mb-toc.xhtml（普通 div 结构）插入 spine 首条；
    #   - 书内目录页是 nav 语义且在 spine → 生成普通结构目录页**替换** spine
    #     中的 nav 条目（原 nav 文件保留在 manifest，properties="nav" 不动，
    #     阅读器侧边栏目录数据源不丢）；
    #   - 书内目录页是普通结构（mulu.xhtml 等）→ 保留原页，仅注入样式与装饰。
    toc_generated = False
    toc_entries = 0
    toc_items = []

    def _abs_with_anchor(base_dir, ref):
        """把目录条目引用解析为 zip 绝对路径（保留 #锚点）。"""
        if '#' in ref:
            path, anchor = ref.split('#', 1)
            return _resolve_zip(base_dir, path) + '#' + anchor
        return _resolve_zip(base_dir, ref)

    # 目录数据源：NCX 优先，其次 EPUB3 nav 文档
    if ctx.ncx_path and ctx.ncx_path in entries:
        ncx_dir = ctx.ncx_path.rsplit('/', 1)[0] + '/' if '/' in ctx.ncx_path else ''
        toc_items = [
            (lv, title, _snap_with_anchor(entries, _abs_with_anchor(ncx_dir, src)))
            for lv, title, src in _parse_ncx(entries[ctx.ncx_path])
        ]
    elif ctx.nav_path and ctx.nav_path in entries:
        nav_dir = ctx.nav_path.rsplit('/', 1)[0] + '/' if '/' in ctx.nav_path else ''
        toc_items = [
            (lv, title, _snap_with_anchor(entries, _abs_with_anchor(nav_dir, href)))
            for lv, title, href in _parse_nav_doc(entries[ctx.nav_path])
        ]

    # 书内目录页：spine 中文件名为目录特征或含 <nav epub:type="toc">
    inbook_toc_paths = [
        t for t in text_entries
        if _is_toc_doc(t, _decode(entries[t])[:2000] if t in entries else '')
    ]
    # nav 语义目录页（内容含 <nav epub:type="toc">）：手机阅读器当目录数据源
    # 特殊处理，spine 中无论 manifest 是否标 properties 都需替换为普通结构
    nav_semantic_paths = [
        t for t in text_entries
        if t in entries
        and re.search(r'<nav\b[^>]*epub:type\s*=\s*["\']toc', _decode(entries[t])[:4000], re.IGNORECASE)
    ]
    nav_semantic_in_spine = bool(nav_semantic_paths)
    # spine 条目 zip 路径 → idref 映射（用于替换 itemref）
    path_to_idref = {}
    for t, idref in zip(text_entries, [r[0] for r in ctx.spine if r[1]]):
        path_to_idref.setdefault(t, idref)

    if (not inbook_toc_paths or nav_semantic_in_spine) and toc_items:
        truncated = len(toc_items) > max_toc_entries
        toc_items = toc_items[:max_toc_entries]
        toc_path = ctx.opf_dir + MB_TOC_NAME
        entries[toc_path] = _build_toc_page(toc_items, ctx.opf_dir, truncated, toc_style)
        toc_entries = len(toc_items)
        # OPF 注册（幂等）
        opf_str = _decode(entries[ctx.opf_path])
        if 'mb-toc.xhtml' not in opf_str:
            mb_id = 'mb-toc'
            opf_str = re.sub(
                r'(</manifest>)',
                '\n<item id="%s" href="%s" media-type="application/xhtml+xml"/>'
                % (mb_id, MB_TOC_NAME) + r'\1',
                opf_str, count=1,
            )
            # 找出 spine 中待替换的 idref：有 nav 语义时只替换 nav 页，否则为无目录时的插入
            if nav_semantic_in_spine:
                replace_ids = [
                    path_to_idref[t] for t in nav_semantic_paths
                    if path_to_idref.get(t) and path_to_idref[t] != mb_id
                ]
            else:
                replace_ids = []
            if replace_ids:
                # 替换第一个 nav 语义目录页条目；其余的直接移除
                opf_str = re.sub(
                    r'\s*<itemref\b[^>]*idref="%s"[^>]*/?>' % re.escape(replace_ids[0]),
                    '\n<itemref idref="%s" linear="yes"/>' % mb_id,
                    opf_str, count=1,
                )
                for extra in replace_ids[1:]:
                    opf_str = re.sub(
                        r'\s*<itemref\b[^>]*idref="%s"[^>]*/?>' % re.escape(extra),
                        '', opf_str, count=1,
                    )
            else:
                # 插入 spine 第一个 linear 条目之前
                spine_m = re.search(r'<spine[^>]*>', opf_str)
                if spine_m:
                    insert_at = spine_m.end()
                    opf_str = (
                        opf_str[:insert_at]
                        + '\n<itemref idref="%s" linear="yes"/>' % mb_id
                        + opf_str[insert_at:]
                    )
            entries[ctx.opf_path] = opf_str.encode('utf-8')
            toc_generated = True

    # ── 2. mb-beauty.css 注入 ──
    css_zip_path = ctx.opf_dir + MB_CSS_NAME
    entries[css_zip_path] = preset_css.encode('utf-8')
    # 注册到 OPF manifest（部分阅读器要求 CSS 在 manifest 中才生效）
    opf_raw = _decode(entries[ctx.opf_path])
    if MB_CSS_NAME not in opf_raw:
        opf_raw = re.sub(
            r'(</manifest>)',
            '\n<item id="mb-beauty" href="%s" media-type="text/css"/>' % MB_CSS_NAME + r'\1',
            opf_raw, count=1,
        )
        entries[ctx.opf_path] = opf_raw.encode('utf-8')

    # ── 3. 逐正文条目：目录页标记 + 章节名标记 + 注入 CSS 引用 ──
    marked_headers = 0
    injected = 0
    for t in text_entries:
        if t not in entries:
            continue
        html = _decode(entries[t])
        changed = False
        # 目录页：body 打 mb-toc-page 标记 + 注入真实装饰元素，不做章节标记
        if _is_toc_doc(t, html):
            new_html = _mark_toc_page_body(html)
            if new_html != html:
                changed = True
                html = new_html
            new_html = _decorate_toc_page(html)
            if new_html != html:
                changed = True
                html = new_html
        elif not _is_front_file(t):
            new_html, count = mark_chapters_in_html(html)
            if count:
                marked_headers += count
                changed = True
                html = new_html
        new_html = _inject_css_link(html, _relative_href(t, css_zip_path))
        if new_html != html:
            changed = True
            html = new_html
        if changed:
            entries[t] = html.encode('utf-8')
            injected += 1

    # ── 4. 翻页方向：竖排预设把 spine 设为 rtl（从左向右翻）──
    rtl_set = False
    if page_progression:
        opf_now = _decode(entries[ctx.opf_path])
        opf_new = _set_page_progression(opf_now, page_progression)
        if opf_new != opf_now:
            entries[ctx.opf_path] = opf_new.encode('utf-8')
        rtl_set = 'page-progression-direction="%s"' % page_progression in opf_new

    _write_zip(entries, out_path)
    return {
        'marked_headers': marked_headers,
        'toc_generated': toc_generated,
        'toc_entries': toc_entries,
        'css_injected_chapters': injected,
        'chapters': len(text_entries),
        'page_progression': page_progression if rtl_set else '',
    }
