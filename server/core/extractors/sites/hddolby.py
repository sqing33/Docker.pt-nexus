# -*- coding: utf-8 -*-
"""
HDDolby特殊站点种子详情参数提取器
用于处理HDDolby站点的种子详情页
"""

import re
import os
import yaml
from bs4 import BeautifulSoup
from utils import extract_origin_from_description
from config import GLOBAL_MAPPINGS

# 加载内容过滤配置
CONTENT_FILTERING_CONFIG = {}
try:
    if os.path.exists(GLOBAL_MAPPINGS):
        with open(GLOBAL_MAPPINGS, 'r', encoding='utf-8') as f:
            global_config = yaml.safe_load(f)
            CONTENT_FILTERING_CONFIG = global_config.get(
                "content_filtering", {})
    else:
        print(f"警告：配置文件不存在: {GLOBAL_MAPPINGS}")
except Exception as e:
    print(f"警告：无法加载内容过滤配置: {e}")


class HDDolbySpecialExtractor:
    """HDDolby特殊站点提取器"""

    def __init__(self, soup, base_url='', cookie='', torrent_id=''):
        self.soup = soup
        self.base_url = base_url
        self.cookie = cookie
        self.torrent_id = torrent_id

    def extract_mediainfo(self):
        """
        提取MediaInfo信息，针对HDDolby站点从div.mediainfo-full或div.mediainfo-container提取
        """
        mediainfo_text = ""

        # 优先尝试从完整BDInfo/MediaInfo容器提取 (HDDolby特定)
        # ID通常是 full_bdinfo_xxxxx
        full_info_divs = self.soup.select("div.mediainfo-full")
        for div in full_info_divs:
            pre = div.find("pre")
            if pre:
                content = pre.get_text(strip=True)
                if content:
                    return content
            # 如果没有pre标签，尝试直接获取文本
            content = div.get_text(strip=True)
            if content:
                return content

        # 如果没有找到full，尝试simplified (虽然通常不想要simplified，但有总比没有好)
        # 或者尝试其他常见位置
        selectors = [
            "div.mediainfo-container pre",
            "div.spoiler-content pre",
            "div.nexus-media-info-raw > pre",
            "div.codemain",
            "pre"
        ]

        for selector in selectors:
            elements = self.soup.select(selector)
            for element in elements:
                content = element.get_text(strip=True)
                if content and ("General" in content or "DISC INFO" in content):
                    return content

        return mediainfo_text

    def extract_intro(self):
        """
        提取简介信息，过滤多余内容
        """
        intro = {}
        quotes = []
        images = []
        body = ""

        # 1. 处理简介容器中的内容
        descr_container = self.soup.select_one("div#kdescr")
        if descr_container:
            # 提取所有引用块 (fieldset)
            quote_elements = descr_container.select("fieldset")
            for quote_element in quote_elements:
                # 检查是否是引用标题
                legend = quote_element.select_one("legend")
                legend_text = legend.get_text() if legend else ""

                # 获取引用内容（排除legend）
                quote_content = ""
                for child in quote_element.children:
                    if child != legend:
                        quote_content += str(child)

                # 清理引用内容
                quote_soup = BeautifulSoup(quote_content, "html.parser")
                quote_text = quote_soup.get_text().strip()

                if quote_text:
                    # 过滤掉不需要的声明和信息 (如"郑重声明")
                    if "郑重声明" in legend_text or "郑重声明" in quote_text:
                        continue

                    if not self._is_unwanted_declaration(quote_text):
                        quotes.append(f"[quote]{quote_text}[/quote]")

            # 提取图片 (从简介中)
            img_elements = descr_container.select("img")
            for img in img_elements:
                src = img.get("src")
                # 过滤掉一些UI图标，只保留内容图片
                if src and not src.endswith("trans.gif") and "pic/" not in src:
                    images.append(f"[img]{src}[/img]")

            # 提取正文内容（排除引用和图片）
            body_content = str(descr_container)
            # 移除所有<fieldset>块
            body_content = re.sub(r"<fieldset>.*?</fieldset>", "", body_content, flags=re.DOTALL)
            # 移除所有<img>标签
            body_content = re.sub(r"<img[^>]*>", "", body_content)
            # 移除广告 div
            body_content = re.sub(r'<div[^>]*id="ad_torrentdetail"[^>]*>.*?</div>', "", body_content, flags=re.DOTALL)

            # 清理HTML标签获取纯文本
            body_soup = BeautifulSoup(body_content, "html.parser")
            body = body_soup.get_text().strip()

            # 过滤掉不需要的声明信息
            body_lines = [
                line for line in body.splitlines()
                if not self._is_unwanted_declaration(line)
            ]
            body = '\n'.join(body_lines).strip()

            # 处理 body 中的空行
            body = re.sub(r"\n{3,}", "\n\n", body)

        # 2. 额外尝试从 div#kscreenshots 提取截图
        screenshot_container = self.soup.select_one("div#kscreenshots")
        if screenshot_container:
            screenshot_imgs = screenshot_container.select("img")
            for img in screenshot_imgs:
                src = img.get("src")
                if src and not src.endswith("trans.gif") and "pic/" not in src:
                    img_tag = f"[img]{src}[/img]"
                    # 避免重复添加
                    if img_tag not in images:
                        images.append(img_tag)

        intro = {
            "statement": "\n".join(quotes) if quotes else "",
            "poster": images[0] if images else "",
            "body": body,
            "screenshots": "\n".join(images[1:]) if len(images) > 1 else "",
        }

        # 尝试提取 IMDb 和 豆瓣链接
        imdb_link = ""
        douban_link = ""

        # 1. 尝试从 kimdb div 获取 (如果有)
        kimdb = self.soup.select_one("div#kimdb")
        if kimdb:
            imdb_a = kimdb.find("a", href=re.compile(r"imdb\.com/title/tt\d+"))
            if imdb_a:
                imdb_link = imdb_a['href']

        # 2. 如果没有，从文本中正则提取 (从简介容器中查找)
        if not imdb_link and descr_container:
            imdb_match = re.search(r"https?://(?:www\.)?imdb\.com/title/tt\d+", str(descr_container))
            if imdb_match:
                imdb_link = imdb_match.group(0)

        if not douban_link and descr_container:
            douban_match = re.search(r"https?://(?:movie\.)?douban\.com/subject/\d+", str(descr_container))
            if douban_match:
                douban_link = douban_match.group(0)

        intro["imdb_link"] = imdb_link
        intro["douban_link"] = douban_link

        return intro

    def _is_unwanted_declaration(self, text):
        """
        判断是否为不需要的声明信息
        """
        if not CONTENT_FILTERING_CONFIG.get("enabled", False):
            return False

        unwanted_patterns = CONTENT_FILTERING_CONFIG.get("unwanted_patterns", [])
        return any(pattern in text for pattern in unwanted_patterns)

    def extract_basic_info(self):
        """
        提取基本信息
        """
        basic_info_dict = {}
        basic_info_td = self.soup.find("td", string="基本信息")

        if basic_info_td and basic_info_td.find_next_sibling("td"):
            # 获取所有文本节点
            strings = list(basic_info_td.find_next_sibling("td").stripped_strings)
            # 解析 Key: Value 对
            # 格式通常是 "Key:", "Value", "Key:", "Value"
            # 但 hddolby 可能是 <b><b>Key：</b></b>Value

            # 使用简单的迭代器处理
            i = 0
            while i < len(strings):
                s = strings[i].strip()
                # 检查是否是键（以冒号结尾）
                if s.endswith(":") or s.endswith("："):
                    key = s[:-1].strip()
                    # 检查下一个元素是否是值
                    if i + 1 < len(strings):
                        value = strings[i + 1].strip()
                        # 确保值不是下一个键
                        if not (value.endswith(":") or value.endswith("：")):
                            basic_info_dict[key] = value
                            i += 2
                            continue
                        else:
                            # 值为空，下一个是键
                            basic_info_dict[key] = ""
                            i += 1
                            continue
                i += 1

        # 如果没有提取到制作组信息，尝试从标题中提取
        if not basic_info_dict.get("制作组"):
            basic_info_dict["制作组"] = self._extract_group_from_title()

        return basic_info_dict

    def _extract_group_from_title(self):
        """
        从标题中提取制作组信息
        """
        h1_top = self.soup.select_one("h1#top")
        original_main_title = list(h1_top.stripped_strings)[0] if h1_top and h1_top.stripped_strings else ""

        # 匹配结尾的 -Group 或 @Group
        match = re.search(r"[-@]([a-zA-Z0-9]+)(?:\s*\[.*?\])?$", original_main_title)
        if match:
            return match.group(1)
        return "Other"

    def extract_tags(self):
        """
        提取标签
        """
        tags_td = self.soup.find("td", string="标签")
        tags = []
        if tags_td and tags_td.find_next_sibling("td"):
            tag_spans = tags_td.find_next_sibling("td").find_all("span", class_="tags")
            tags = [s.get_text(strip=True) for s in tag_spans]

        # 过滤掉指定的标签
        filtered_tags = []
        unwanted_tags = ["官方", "官种", "首发", "自购", "自抓", "应求", "热门", "推荐"]
        for tag in tags:
            if tag not in unwanted_tags:
                filtered_tags.append(tag)

        return filtered_tags

    def extract_subtitle(self):
        """
        提取副标题
        """
        subtitle_td = self.soup.find("td", string=re.compile(r"\s*副标题\s*"))
        if subtitle_td and subtitle_td.find_next_sibling("td"):
            subtitle = subtitle_td.find_next_sibling("td").get_text(strip=True)
            return subtitle
        return ""

    def extract_all(self, torrent_id=None):
        """
        提取所有种子信息
        """
        # 提取基本信息
        basic_info = self.extract_basic_info()

        # 提取标签
        tags = self.extract_tags()

        # 提取副标题
        subtitle = self.extract_subtitle()

        # 提取简介
        intro = self.extract_intro()

        # 提取MediaInfo
        mediainfo = self.extract_mediainfo()

        # 提取产地信息
        full_description_text = f"{intro.get('statement', '')}\n{intro.get('body', '')}"
        origin_info = extract_origin_from_description(full_description_text)

        # 构建参数字典
        source_params = {
            "类型": basic_info.get("类型", ""),
            "媒介": basic_info.get("媒介"),
            "视频编码": basic_info.get("编码") or basic_info.get("视频编码"),
            "音频编码": basic_info.get("音频编码"),
            "分辨率": basic_info.get("分辨率"),
            "制作组": basic_info.get("制作组"),
            "标签": tags,
            "产地": origin_info,
        }

        extracted_data = {
            "source_params": source_params,
            "subtitle": subtitle,
            "intro": intro,
            "mediainfo": mediainfo,
        }

        return extracted_data
