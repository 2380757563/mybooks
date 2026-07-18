#!/usr/bin/python
# -*- coding: UTF-8 -*-

import re
import logging
import requests
from bs4 import BeautifulSoup
from collections import OrderedDict

from webserver.constants import CHROME_MOBILE_HEADERS
from webserver.plugins.meta.baike.baidubaike.baiduexception import PageError, DisambiguationError, VerifyError


CLASS_DISAMBIGUATION = ["nslog:519"]
CLASS_TAG = []
CLASS_SUMMARY = ["J-summary"]
CLASS_INFO = ["basicInfo"]
CLASS_SUMMARY_PIC = ["summary-img"]
CLASS_CARD_ITEM = re.compile(r"^index_cardItem__")
CLASS_CARD_NAME = re.compile(r"^index_cardName__")
CLASS_CARD_VALUE = re.compile(r"^index_cardItemValue__")
OUTPUT_FOR_DEBUG = False


class Page(object):
    def __init__(self, book_name, encoding="utf-8"):
        url = "https://baike.baidu.com/search/word"
        payload = None
        self.valid = False  # 标记请求是否成功

        # An url or a word to be Paged
        pattern = re.compile(r"^https?:\/\/baike\.baidu\.com\/.*", re.IGNORECASE)
        if re.match(pattern, book_name):
            url = book_name
        else:
            payload = {"pic": 1, "enc": encoding, "word": book_name}

        self.http = requests.get(url, timeout=10, headers=CHROME_MOBILE_HEADERS, params=payload, allow_redirects=True)
        logging.debug(f"Fetching URL: {self.http.url}, Status: {self.http.status_code}")

        # 检查HTTP响应状态码
        if self.http.status_code != 200:
            logging.warning(f"HTTP request failed with status code: {self.http.status_code}")
            return

        # write to file for debug
        if OUTPUT_FOR_DEBUG:
            with open("./baidu_baike_debug.html", "w", encoding="utf-8") as f:
                f.write(self.http.text)

        self.html = self.http.text
        self.soup = BeautifulSoup(self.html, "lxml")

        # Exceptions
        if self.soup.find(class_=CLASS_DISAMBIGUATION):
            raise DisambiguationError(book_name, self.get_inurls())
        if u"百度百科尚未收录词条" in self.html:
            raise PageError(book_name)
        if self.soup.find(id="vf"):
            raise VerifyError(book_name)

        self.valid = True  # 标记为成功

    def parse_basic_info(self):
        """Get basic info of a page"""
        if not self.valid:
            return {}
        info = {}
        divs = self.soup.find_all(class_=CLASS_INFO)
        for div in divs:
            # Find all list items containing info-title and info-content pairs
            list_items = div.find_all("li")
            for item in list_items:
                title_div = item.find(class_="info-title")
                content_div = item.find(class_="info-content")
                if title_div and content_div:
                    name = title_div.get_text(strip=True).replace(u"\xa0", "").strip()
                    direct_text = "".join(
                        text for text in content_div.find_all(string=True, recursive=False)
                    )
                    value = direct_text.replace(u"\xa0", "").strip()
                    info[name] = value
        if info:
            return info

        # Newer page layout: basic info lives in a "lemmaCard" region as
        # <name>/<value> pairs instead of the old info-title/info-content <li> list.
        card = self.soup.find(attrs={"data-region": "lemmaCard"})
        if card:
            for item in card.find_all(class_=CLASS_CARD_ITEM):
                name_div = item.find(class_=CLASS_CARD_NAME)
                value_div = item.find(class_=CLASS_CARD_VALUE)
                if name_div and value_div:
                    name = name_div.get_text(strip=True).replace(u"\xa0", "").strip()
                    value = value_div.get_text(strip=True).replace(u"\xa0", "").strip()
                    info[name] = value
        return info

    def get_info(self):
        """Get informations of the page"""
        if not self.valid:
            return {}

        info = self.parse_basic_info()
        title = self.soup.title.get_text()
        info["title"] = title[: title.rfind("_")]
        info["url"] = self.http.url

        if info["title"] == '验证':
            logging.warning(f"[百度百科]需要通过验证才可以正常访问，请使用浏览访问并通过验证: {self.http.url}")

        return info

    def get_image(self):
        if not self.valid:
            return ""
        normal_type = True
        url = ""
        divs = self.soup.find_all(class_=CLASS_SUMMARY_PIC)
        for div in divs:
            url = div.attrs.get("data-src", "")
            if not url:
                continue
            break
        if not url:
            normal_type = False
            # 查找页面的meta如下信息，获取图片url
            # <meta property="og:image" content="https://xxx" />
            og_images = self.soup.find_all("meta", property="og:image")
            for og_image in og_images:
                if og_image and og_image.has_attr("content") \
                   and og_image["content"].lower().startswith("https://bkimg.cdn.bcebos.com/"):
                    url = og_image["content"]
                    break
        return normal_type, url

    def get_summary(self):
        """Get summary infomation of a page"""
        if not self.valid:
            return ""
        divs = self.soup.find_all(class_=CLASS_SUMMARY)

        # Get the description from meta properties
        descriptions = self.soup.find_all("meta", property="og:description")
        for description in descriptions:
            if description and description.has_attr("content"):
                return description["content"]

        summary_parts = []
        for div in divs:
            # Remove citation markers (sup tags) before extracting text
            for sup in div.find_all("sup"):
                sup.decompose()
            text = div.get_text(strip=True)
            if text:
                summary_parts.append(text)
        return "\n".join(summary_parts)

    def get_inurls(self):
        """Get links inside a page"""
        if not self.valid:
            return OrderedDict()
        inurls = OrderedDict()
        href = self.soup.find_all(href=re.compile(r"\/(sub)?view(\/[0-9]*)+.htm"))

        for url in href:
            inurls[url.get_text()] = "https://baike.baidu.com%s" % url.get("href")

        return inurls

    def get_tags(self):
        """Get tags of the page"""
        if not self.valid or len(CLASS_TAG) == 0:
            return []
        tags = []
        for tag in self.soup.find_all(class_=CLASS_TAG):
            tags.append(tag.get_text(strip=True))

        return tags

    def get_id(self):
        """Get unique identifier from URL"""
        if not self.valid:
            return ""
        # Extract item name from URL like https://baike.baidu.com/item/词条名
        url = self.http.url
        match = re.search(r'/item/([^/?]+)', url)
        if match:
            return match.group(1)
        return url


if __name__ == "__main__":
    page = Page("一品美食")  # 绝命毒尸
    print(page.get_info())
    print(page.get_summary())
