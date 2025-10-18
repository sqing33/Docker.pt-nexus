# -*- coding: utf-8 -*-
"""
HHCLUB特殊站点种子详情参数提取器
用于处理HHCLUB站点特殊结构的种子详情页 (已修正)
"""

import re
import os
import yaml
from bs4 import BeautifulSoup
from utils import extract_tags_from_mediainfo, extract_origin_from_description

# 加载内容过滤配置
CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(__file__)))), "configs")
CONTENT_FILTERING_CONFIG = {}
try:
    global_mappings_path = os.path.join(CONFIG_DIR, "global_mappings.yaml")
    if os.path.exists(global_mappings_path):
        with open(global_mappings_path, 'r', encoding='utf-8') as f:
            global_config = yaml.safe_load(f)
            CONTENT_FILTERING_CONFIG = global_config.get(
                "content_filtering", {})
except Exception as e:
    print(f"警告：无法加载内容过滤配置: {e}")


class HHCLUBSpecialExtractor:
    """HHCLUB特殊站点提取器"""

    def __init__(self, soup):
        self.soup = soup

    def _find_section_container(self, header_text: str):
        """
        一个辅助函数，通过区块的标题文本找到对应的内容容器。
        它首先使用正则表达式找到包含标题的div，然后返回其紧邻的下一个div兄弟节点。
        """
        # 使用正则表达式模糊匹配标题，以应对文本前后可能存在的空格或嵌套标签
        header_div = self.soup.find(
            "div", string=re.compile(r"\s*" + re.escape(header_text) + r"\s*"))
        if header_div:
            # 内容通常在标题div的下一个兄弟div元素中
            return header_div.find_next_sibling("div")
        return None

    def extract_mediainfo(self):
        """
        提取MediaInfo信息。此方法在原脚本中有效，予以保留。
        根据提供的HTML，主要信息在 nexus-media-info-raw 容器中。
        """
        mediainfo_text = ""
        # 优先使用最精确的选择器
        mediainfo_element = self.soup.select_one(
            "div.nexus-media-info-raw pre code")
        if mediainfo_element:
            content = mediainfo_element.get_text(strip=True)
            if self._is_valid_mediainfo(content):
                return content

        # 保留原脚本中的备用逻辑作为后备方案
        mediainfo_header = self.soup.find(string="MediaInfo")
        if mediainfo_header:
            parent_div = mediainfo_header.parent.parent
            mediainfo_container = parent_div.find_next_sibling()
            if mediainfo_container:
                code_element = mediainfo_container.select_one("pre code")
                if code_element:
                    content = code_element.get_text(strip=True)
                    if self._is_valid_mediainfo(content):
                        return content
        return mediainfo_text

    def _is_valid_mediainfo(self, content):
        """
        检查内容是否为有效的MediaInfo或BDInfo格式。
        """
        if not content or len(content) < 50:
            return False
        # 根据HTML样本，BDInfo格式更常见
        bdinfo_keywords = [
            "DISC INFO", "PLAYLIST REPORT", "VIDEO:", "AUDIO:", "SUBTITLES:"
        ]
        matches = sum(1 for keyword in bdinfo_keywords if keyword in content)
        # 只要匹配到3个以上关键词，就认为是有效的
        return matches >= 3

    def extract_intro(self):
        """
        提取简介信息，针对HHCLUB站点的特殊结构。
        """
        intro = {}
        quotes = []
        images = []
        body = ""
        screenshots = []

        # 1. 从“其他信息”部分提取发布说明（通常在<blockquote>中）
        other_info_container = self.soup.select_one("div#details-container")
        if other_info_container:
            for blockquote in other_info_container.select("blockquote"):
                quote_content = blockquote.get_text("\n", strip=True)
                if quote_content and not self._is_unwanted_declaration(
                        quote_content):
                    quotes.append(f"[quote]{quote_content}[/quote]")

        # 2. 提取海报
        poster_container = self._find_section_container("海报")
        if poster_container:
            poster_img = poster_container.select_one("img")
            if poster_img and poster_img.get("src"):
                images.append(f"[img]{poster_img.get('src').strip()}[/img]")

        # 备用方法：如果通过区块标题找不到，直接搜索豆瓣图片链接
        if not images:
            poster_img = self.soup.select_one("img[src*='doubanio.com']")
            if poster_img and poster_img.get("src"):
                images.append(f"[img]{poster_img.get('src').strip()}[/img]")

        # 3. 提取截图
        screenshot_container = self.soup.select_one("div#screenshot-content")
        if screenshot_container:
            for img in screenshot_container.select("img"):
                src = img.get("src")
                if src:
                    screenshots.append(f"[img]{src.strip()}[/img]")

        # 4. 提取豆瓣/IMDb链接以供PT-Gen使用
        douban_link = self.extract_douban_info()
        imdb_link = self.extract_imdb_info()

        # 5. 使用ptgen获取电影信息正文
        if douban_link or imdb_link:
            try:
                from utils import upload_data_movie_info
                movie_status, poster_content, description_content, imdb_content = upload_data_movie_info(
                    douban_link, imdb_link)

                if movie_status and description_content:
                    body = description_content
                    # 如果页面上没找到海报，使用ptgen获取的海报
                    if not images and poster_content:
                        images.append(poster_content)
                else:
                    print(f"PT-Gen获取电影信息失败: {description_content}")
            except Exception as e:
                print(f"调用PT-Gen时发生错误: {e}")

        # 清理正文中的不必要声明
        body_lines = [
            line for line in body.split('\n')
            if not self._is_unwanted_declaration(line)
        ]
        body = '\n'.join(body_lines).strip()
        body = re.sub(r"\n{2,}", "\n", body)

        intro = {
            "statement": "\n".join(quotes),
            "poster": images[0] if images else "",
            "body": body,
            "screenshots": "\n".join(screenshots),
        }
        return intro

    def _is_unwanted_declaration(self, text):
        """
        判断是否为不需要的声明信息（使用配置文件中的规则）
        """
        if not CONTENT_FILTERING_CONFIG.get("enabled", False):
            return False

        unwanted_patterns = CONTENT_FILTERING_CONFIG.get(
            "unwanted_patterns", [])
        return any(pattern in text for pattern in unwanted_patterns)

    def extract_basic_info(self):
        """
        提取基本信息，使用新的辅助函数定位。
        """
        basic_info_dict = {}
        container = self._find_section_container("基本信息")
        if container:
            # 直接查找容器下的所有子div
            for div in container.find_all("div", recursive=False):
                spans = div.find_all("span")
                if len(spans) >= 2:
                    key = spans[0].get_text(strip=True).rstrip(":：")
                    value = spans[1].get_text(strip=True)

                    # 字段映射 - 修正字段名匹配，更具体的匹配优先
                    if "大小" in key: basic_info_dict["大小"] = value
                    elif "类型" in key: basic_info_dict["类型"] = value
                    elif "来源" in key: basic_info_dict["来源"] = value
                    elif "媒介" in key: basic_info_dict["媒介"] = value
                    elif "音频编码" in key:
                        basic_info_dict["音频编码"] = value  # 音频编码优先匹配
                    elif "编码" in key:
                        basic_info_dict["视频编码"] = value  # HTML中是"编码"而不是"视频编码"
                    elif "分辨率" in key:
                        basic_info_dict["分辨率"] = value
                    elif "处理" in key:
                        basic_info_dict["处理"] = value
                    elif "制作组" in key:
                        basic_info_dict["制作组"] = value
                    elif "发布者" in key:
                        basic_info_dict["发布者"] = value
                    elif "发布时间" in key:
                        basic_info_dict["发布时间"] = value

        # 如果没有提取到制作组信息，尝试从标题中提取
        if not basic_info_dict.get("制作组"):
            basic_info_dict["制作组"] = self._extract_group_from_title()

        return basic_info_dict

    def _extract_group_from_title(self):
        """
        从标题中提取制作组信息
        """
        # 提取主标题
        container = self._find_section_container("标题")
        original_main_title = container.get_text(
            strip=True) if container else ""

        # 从标题中提取制作组的正则表达式
        # 匹配常见的制作组格式，例如: [ABC] 或 -ABC 或 [ABC-RIP] 等
        group_patterns = [
            r'^\[(\w+(?:-\w+)*)\]',  # 开头的 [制作组] 格式
            r'-([A-Z]+(?:-[A-Z]+)*)$',  # 结尾的 -制作组 格式
            r'\[([A-Z]+(?:-[A-Z]+)*)\]$',  # 结尾的 [制作组] 格式
        ]

        for pattern in group_patterns:
            match = re.search(pattern, original_main_title)
            if match:
                return match.group(1)

        # 如果以上模式都不匹配，尝试查找标题中的制作组标识
        # 匹配常见的制作组缩写（大写字母组合）
        general_group_pattern = r'\b([A-Z]{2,}(?:-[A-Z]+)*)\b'
        matches = re.findall(general_group_pattern, original_main_title)
        if matches:
            # 返回第一个匹配的制作组（通常在标题开头的更可能是制作组）
            return matches[0]

        return None

    def extract_tags(self):
        """
        提取标签，优先在指定容器内查找，然后使用辅助函数定位。
        """
        tags = []

        # 优先在指定的容器内查找标签
        main_container = self.soup.select_one(
            "div.bg-content_bg.rounded-md.py-10.px-20.text-black")
        if main_container:
            # 在主容器内查找标签部分
            tag_section = main_container.find("div",
                                              string=re.compile(r"\s*标签\s*"))
            if tag_section:
                tag_container = tag_section.find_next_sibling("div")
                if tag_container:
                    for span in tag_container.select("a span"):
                        tag_text = span.get_text(strip=True)
                        if tag_text:
                            tags.append(tag_text)

        # 如果在指定容器内没找到，使用原来的方法作为备用
        if not tags:
            container = self._find_section_container("标签")
            if container:
                for span in container.select("a span"):
                    tag_text = span.get_text(strip=True)
                    if tag_text:
                        tags.append(tag_text)

        # 过滤掉指定的标签
        filtered_tags = []
        unwanted_tags = ["官方", "官种", "首发", "自购", "应求"]
        for tag in tags:
            if tag not in unwanted_tags:
                filtered_tags.append(tag)

        return filtered_tags

    def extract_subtitle(self):
        """
        提取副标题并清理，使用新的辅助函数定位。
        """
        container = self._find_section_container("副标题")
        if container:
            subtitle = container.get_text(strip=True)
            # 剔除制作组信息 (保持原逻辑)
            subtitle = re.sub(r"\s*\|\s*[Aa][Bb]y\s+\w+.*$", "", subtitle)
            subtitle = re.sub(r"\s*\|\s*[Bb]y\s+\w+.*$", "", subtitle)
            subtitle = re.sub(r"\s*\|\s*[Aa]\s+\w+.*$", "", subtitle)
            subtitle = re.sub(r"\s*\|\s*[Aa][Tt][Uu]\s*$", "", subtitle)
            subtitle = re.sub(r"\s*\|\s*[Dd][Tt][Uu]\s*$", "", subtitle)
            subtitle = re.sub(r"\s*\|\s*[Pp][Tt][Ee][Rr]\s*$", "", subtitle)
            return subtitle
        return ""

    def extract_douban_info(self):
        """
        提取豆瓣信息，直接在全文搜索链接。
        """
        douban_link_tag = self.soup.select_one(
            "a[href*='movie.douban.com/subject/']")
        return douban_link_tag.get("href", "") if douban_link_tag else ""

    def extract_imdb_info(self):
        """
        提取IMDb信息，直接在全文搜索链接。
        """
        imdb_link_tag = self.soup.select_one("a[href*='imdb.com/title/tt']")
        return imdb_link_tag.get("href", "") if imdb_link_tag else ""

    def extract_title(self):
        """
        提取主标题，使用新的辅助函数定位。
        """
        container = self._find_section_container("标题")
        if container:
            return container.get_text(strip=True)
        return ""

    def extract_all(self, torrent_id=None):
        """
        提取所有种子信息 (保持原逻辑)
        """
        basic_info = self.extract_basic_info()
        tags = self.extract_tags()
        subtitle = self.extract_subtitle()
        intro = self.extract_intro()
        mediainfo = self.extract_mediainfo()
        douban_info = self.extract_douban_info()
        imdb_info = self.extract_imdb_info()
        main_title = self.extract_title()

        full_description_text = f"{intro.get('statement', '')}\n{intro.get('body', '')}"
        origin_info = extract_origin_from_description(full_description_text)

        source_params = {
            "类型": basic_info.get("类型", ""),
            "媒介": basic_info.get("媒介"),
            "视频编码": basic_info.get("视频编码"),
            "音频编码": basic_info.get("音频编码"),
            "分辨率": basic_info.get("分辨率"),
            "制作组": basic_info.get("制作组"),
            "标签": tags,
            "产地": origin_info,
        }

        intro["douban_link"] = douban_info
        intro["imdb_link"] = imdb_info

        extracted_data = {
            "source_params": source_params,
            "subtitle": subtitle,
            "intro": intro,
            "mediainfo": mediainfo,
            "title": main_title  # 主标题也应包含在最终结果中
        }

        return extracted_data
