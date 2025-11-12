# -*- coding: utf-8 -*-
"""
SSD("不可说")特殊站点种子详情参数提取器
用于处理"不可说"站点特殊结构的种子详情页
"""

import re
import os
import yaml
from bs4 import BeautifulSoup
from utils import extract_tags_from_mediainfo, extract_origin_from_description

# 加载内容过滤配置
CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "configs")
CONTENT_FILTERING_CONFIG = {}
try:
    global_mappings_path = os.path.join(CONFIG_DIR, "global_mappings.yaml")
    if os.path.exists(global_mappings_path):
        with open(global_mappings_path, 'r', encoding='utf-8') as f:
            global_config = yaml.safe_load(f)
            CONTENT_FILTERING_CONFIG = global_config.get("content_filtering", {})
except Exception as e:
    print(f"警告：无法加载内容过滤配置: {e}")


class SSDSpecialExtractor:
    """SSD("不可说")特殊站点提取器"""

    def __init__(self, soup):
        self.soup = soup

    def extract_mediainfo(self):
        """
        提取MediaInfo信息，针对"不可说"站点的特殊结构
        """
        mediainfo_text = ""

        # 在"不可说"站点中，MediaInfo信息在特定的section中
        mediainfo_sections = self.soup.select("[data-group='mediainfo']")

        for section in mediainfo_sections:
            # 优先选择完整版本的MediaInfo（未显示的版本）
            codemain_div = section.select_one("div.codemain")
            if codemain_div:
                content = codemain_div.get_text(strip=True)
                if content and len(content) > 50:  # 确保有足够的内容
                    # 检查是否包含MediaInfo或BDInfo特征
                    if self._is_valid_mediainfo(content):
                        mediainfo_text = content
                        return mediainfo_text

        # 如果没有找到完整版本，尝试简短版本
        mediainfo_short_sections = self.soup.select(
            "[data-group='mediainfo_toggle']")
        for section in mediainfo_short_sections:
            codemain_div = section.select_one("div.codemain")
            if codemain_div:
                content = codemain_div.get_text(strip=True)
                if content and len(content) > 50:
                    if self._is_valid_mediainfo(content):
                        mediainfo_text = content
                        return mediainfo_text

        # 最后的备选方案
        selectors = [
            "div.codemain", "div.spoiler-content pre",
            "div.nexus-media-info-raw > pre", "pre"
        ]

        for selector in selectors:
            elements = self.soup.select(selector)
            for element in elements:
                content = element.get_text(strip=True)
                if content and len(content) > 50:
                    if self._is_valid_mediainfo(content):
                        mediainfo_text = content
                        return mediainfo_text

        return mediainfo_text

    def _is_valid_mediainfo(self, content):
        """
        检查内容是否为有效的MediaInfo或BDInfo格式
        """
        if not content or len(content) < 50:
            return False

        # MediaInfo 格式的必要关键字
        mediainfo_required_keywords = ["General", "Video", "Audio"]

        # BDInfo 格式的必要关键字
        bdinfo_required_keywords = ["DISC INFO", "PLAYLIST REPORT"]

        content_lines = content.split('\n')

        # 检查是否为标准MediaInfo格式
        mediainfo_matches = sum(1 for keyword in mediainfo_required_keywords
                                if any(
                                    keyword in line for line in content_lines))
        if mediainfo_matches >= 2:  # 至少匹配2个关键字
            return True

        # 检查是否为BDInfo格式
        bdinfo_matches = sum(1 for keyword in bdinfo_required_keywords
                             if any(keyword in line for line in content_lines))
        if bdinfo_matches == len(bdinfo_required_keywords):
            return True

        return False

    def extract_intro(self):
        """
        提取简介信息，针对"不可说"站点的特殊结构
        完全使用ptgen来获取简介信息，并去掉海报部分
        """
        intro = {}
        quotes = []
        images = []
        body = ""

        # 在"不可说"站点中，信息分布在不同的section中
        # 豆瓣信息部分
        douban_section = self.soup.select_one("[data-group='douban']")
        # IMDb信息部分
        imdb_section = self.soup.select_one("[data-group='imdb']")
        # 额外文本BBCode部分（包含声明）
        extra_text_bbcode = self.soup.select_one("#torrent-extra-text-bbcode")

        # 提取声明信息（引用块）
        if extra_text_bbcode:
            # 从BBCode格式中提取引用块
            bbcode_text = extra_text_bbcode.get_text().strip()
            # 提取所有[quote]...[/quote]块
            quote_blocks = re.findall(r'\[quote\].*?\[/quote\]', bbcode_text,
                                      re.DOTALL)
            for quote_block in quote_blocks:
                # 清理引用块内容
                quote_content = re.sub(r'\[\/?quote\]', '',
                                       quote_block).strip()
                if quote_content and not self._is_unwanted_declaration(
                        quote_content):
                    quotes.append(quote_block)  # 保留原始的BBCode格式

        # 提取海报图片
        poster_img = self.soup.select_one("img[src*='doubanio.com']")
        if not poster_img:
            # 尝试其他海报选择器
            poster_img = self.soup.select_one("div.poster-preview img")
        if poster_img:
            src = poster_img.get("src")
            if src:
                images.append(f"[img]{src}[/img]")

        # 提取截图信息
        screenshots = []
        screenshots_section = self.soup.select_one(
            "[data-group='screenshots']")
        if screenshots_section:
            screenshot_imgs = screenshots_section.select("div.screenshot img")
            for img in screenshot_imgs:
                src = img.get("src")
                if src:
                    # 清理src中的换行符
                    src = src.strip()
                    screenshots.append(f"[img]{src}[/img]")

        # 提取豆瓣或IMDb链接以使用ptgen获取简介
        douban_link = ""
        imdb_link = ""

        # 首先在整个文档中查找链接
        douban_link_tag = self.soup.select_one(
            "a[href*='movie.douban.com/subject/']")
        if douban_link_tag:
            douban_link = douban_link_tag.get("href", "")

        imdb_link_tag = self.soup.select_one("a[href*='imdb.com/title/tt']")
        if imdb_link_tag:
            imdb_link = imdb_link_tag.get("href", "")

        # 如果在全局没找到，尝试从特定部分查找
        if not douban_link and douban_section:
            # 从豆瓣部分提取豆瓣链接
            douban_link_tag = douban_section.select_one(
                "a[href*='movie.douban.com/subject/']")
            if not douban_link_tag:
                # 最后尝试从文本中提取豆瓣链接
                douban_text = douban_section.get_text()
                douban_match = re.search(
                    r'https?://movie\.douban\.com/subject/\d+', douban_text)
                if douban_match:
                    douban_link = douban_match.group(0)

        if not imdb_link and imdb_section:
            # 从IMDb部分提取IMDb链接
            imdb_link_tag = imdb_section.select_one(
                "a[href*='imdb.com/title/tt']")
            if not imdb_link_tag:
                # 最后尝试从文本中提取IMDb链接
                imdb_text = imdb_section.get_text() if imdb_section else ""
                imdb_match = re.search(r'https?://www\.imdb\.com/title/tt\d+',
                                       imdb_text)
                if imdb_match:
                    imdb_link = imdb_match.group(0)

        if douban_link or imdb_link:
            try:
                from utils import upload_data_movie_info
                # 使用upload_data_movie_info函数同时获取海报和简介
                movie_status, poster_content, description_content, imdb_content = upload_data_movie_info(
                    douban_link, imdb_link)

                if movie_status and description_content:
                    body = description_content
                    # 如果还没有海报，可以使用从ptgen获取的海报
                    if not images and poster_content:
                        images.append(poster_content)
                else:
                    print(f"PT-Gen获取电影信息失败: {description_content}")
            except Exception as e:
                print(f"调用PT-Gen时发生错误: {e}")

        # 过滤掉不需要的声明信息
        body_lines = [
            line for line in body.split('\n')
            if not self._is_unwanted_declaration(line)
        ]
        body = '\n'.join(body_lines).strip()

        intro = {
            "statement": "\n".join(quotes) if quotes else "",  # 声明对应的是声明
            "poster": images[0] if images else "",  # 海报
            "body": re.sub(r"\n{2,}", "\n", body),  # 正文内容
            "screenshots":
            "\n".join(screenshots) if screenshots else "",  # 截图信息
        }

        return intro

    def _is_unwanted_declaration(self, text):
        """
        判断是否为不需要的声明信息（使用配置文件中的规则）
        """
        if not CONTENT_FILTERING_CONFIG.get("enabled", False):
            return False
            
        unwanted_patterns = CONTENT_FILTERING_CONFIG.get("unwanted_patterns", [])
        return any(pattern in text for pattern in unwanted_patterns)

    def extract_basic_info(self):
        """
        提取基本信息，针对"不可说"站点的特殊结构
        """
        basic_info_dict = {}
        basic_info_td = self.soup.find("td", string="基本信息")

        if basic_info_td and basic_info_td.find_next_sibling("td"):
            # 获取td中的所有span元素
            span_elements = basic_info_td.find_next_sibling("td").find_all(
                "span")
            for span in span_elements:
                title = span.get("title")
                text = span.get_text().strip()
                if title and text:
                    # 根据title映射到标准字段名
                    if title == "类型":
                        # 从文本中提取括号内的内容作为类型
                        type_match = re.search(r'\((.*?)\)', text)
                        basic_info_dict["类型"] = type_match.group(
                            1) if type_match else text
                    elif title == "格式":
                        basic_info_dict["媒介"] = text
                    elif title == "视频编码":
                        basic_info_dict["视频编码"] = text
                    elif title == "音频编码":
                        basic_info_dict["音频编码"] = text
                    elif title == "分辨率":
                        basic_info_dict["分辨率"] = text
                    elif title == "大小":
                        basic_info_dict["大小"] = text
                    elif title == "地区":
                        basic_info_dict["产地"] = text

        # 如果没有提取到制作组信息，尝试从标题中提取
        if not basic_info_dict.get("制作组"):
            basic_info_dict["制作组"] = self._extract_group_from_title()

        return basic_info_dict

    def _extract_group_from_title(self):
        """
        从标题中提取制作组信息
        """
        # 提取主标题
        title_span = self.soup.select_one("span#torrent-name")
        original_main_title = title_span.get_text().strip(
        ) if title_span else ""

        # 如果没有找到span#torrent-name，尝试从h1#top中提取
        if not title_span:
            h1_top = self.soup.select_one("h1#top")
            if h1_top:
                # 获取h1标签中的直接文本内容，跳过子元素
                original_main_title = h1_top.get_text().strip()
                # 移除"已审"等无关信息
                original_main_title = re.sub(r'\(.*?\)', '',
                                             original_main_title).strip()

        # 从标题中提取制作组的正则表达式
        # 修正：优先匹配 -制作组 或 @制作组 格式，这样可以正确识别包含特殊字符的制作组
        group_patterns = [
            r'^\[(\w+(?:-\w+)*)\]',  # 开头的 [制作组] 格式
            r'[-@]([^\s]+)$',  # 结尾的 -制作组 或 @制作组 格式（匹配任意非空白字符）
            r'\[([A-Z]+(?:-[A-Z]+)*)\]$',  # 结尾的 [制作组] 格式
        ]

        for pattern in group_patterns:
            match = re.search(pattern, original_main_title)
            if match:
                return match.group(1)

        return None

    def extract_tags(self):
        """
        提取标签,针对"不可说"站点的特殊结构
        """
        tags_td = self.soup.find("td", string="标签")
        if tags_td and tags_td.find_next_sibling("td"):
            tags = [
                s.get_text(strip=True)
                for s in tags_td.find_next_sibling("td").find_all("span")
            ]
            
            # 过滤掉指定的标签
            filtered_tags = []
            unwanted_tags = ["官方", "官种", "首发", "自购", "应求"]
            for tag in tags:
                if tag not in unwanted_tags:
                    # 将"合集"替换成"完结"
                    if tag == "合集":
                        filtered_tags.append("完结")
                    else:
                        filtered_tags.append(tag)
            
            return filtered_tags
        return []

    def extract_subtitle(self):
        """
        提取副标题并清理，针对"不可说"站点的特殊结构
        """
        subtitle_td = self.soup.find("td", string=re.compile(r"\s*副标题\s*"))
        if subtitle_td and subtitle_td.find_next_sibling("td"):
            subtitle = subtitle_td.find_next_sibling("td").get_text(strip=True)
            # 剔除制作组信息
            subtitle = re.sub(r"\s*\|\s*[Aa][Bb]y\s+\w+.*$", "", subtitle)
            subtitle = re.sub(r"\s*\|\s*[Bb]y\s+\w+.*$", "", subtitle)
            subtitle = re.sub(r"\s*\|\s*[Aa]\s+\w+.*$", "", subtitle)
            # 剔除结尾的制作组标识
            subtitle = re.sub(r"\s*\|\s*[Aa][Tt][Uu]\s*$", "", subtitle)
            subtitle = re.sub(r"\s*\|\s*[Dd][Tt][Uu]\s*$", "", subtitle)
            subtitle = re.sub(r"\s*\|\s*[Pp][Tt][Ee][Rr]\s*$", "", subtitle)
            return subtitle
        return ""

    def extract_douban_info(self):
        """
        提取豆瓣信息，针对"不可说"站点的特殊结构
        """
        douban_info = ""

        # 在"不可说"站点中，豆瓣链接在特定的a标签中
        douban_link = self.soup.select_one(
            "a[href*='movie.douban.com/subject/']")
        if douban_link:
            douban_info = douban_link.get("href", "")
        else:
            # 如果没有找到特定链接，尝试从文本中提取
            descr_container = self.soup.select_one("div#kdescr")
            if not descr_container:
                # 在"不可说"站点中，简介信息可能在其他地方
                # 检查是否有豆瓣信息部分
                douban_section = self.soup.select_one("[data-group='douban']")
                if douban_section:
                    descr_text = douban_section.get_text()
                else:
                    return douban_info
            else:
                descr_text = descr_container.get_text()

            # 提取豆瓣链接
            douban_match = re.search(
                r"(https?://movie\.douban\.com/subject/\d+)", descr_text)
            if douban_match:
                douban_info = douban_match.group(1)

        return douban_info

    def extract_imdb_info(self):
        """
        提取IMDb信息，针对"不可说"站点的特殊结构
        """
        imdb_info = ""

        # 在"不可说"站点中，IMDb链接在特定的a标签中
        imdb_link = self.soup.select_one("a[href*='imdb.com/title/tt']")
        if imdb_link:
            imdb_info = imdb_link.get("href", "")
        else:
            # 如果没有找到特定链接，尝试从文本中提取
            descr_container = self.soup.select_one("div#kdescr")
            if not descr_container:
                # 在"不可说"站点中，简介信息可能在其他地方
                # 检查是否有IMDb信息部分
                imdb_section = self.soup.select_one("[data-group='imdb']")
                if imdb_section:
                    descr_text = imdb_section.get_text()
                else:
                    # 检查额外信息部分
                    extra_text_section = self.soup.select_one(
                        "[data-group='extra_text']")
                    if extra_text_section:
                        descr_text = extra_text_section.get_text()
                    else:
                        return imdb_info
            else:
                descr_text = descr_container.get_text()

            # 提取IMDb链接
            imdb_match = re.search(r"(https?://www\.imdb\.com/title/tt\d+)",
                                   descr_text)
            if imdb_match:
                imdb_info = imdb_match.group(1)

        return imdb_info

    def extract_title(self):
        """
        提取主标题，针对"不可说"站点的特殊结构
        只做基本的预处理（移除已审），点号处理由公共解析器统一处理
        """
        # 在"不可说"站点中，主标题在span#torrent-name中
        title_span = self.soup.select_one("span#torrent-name")
        original_main_title = title_span.get_text().strip(
        ) if title_span else "未找到标题"

        # 如果没有找到span#torrent-name，尝试从h1#top中提取
        if not title_span:
            h1_top = self.soup.select_one("h1#top")
            if h1_top:
                # 获取h1标签中的直接文本内容，跳过子元素
                original_main_title = h1_top.get_text().strip()
                # 移除"已审"等无关信息
                original_main_title = re.sub(r'\(.*?\)', '',
                                             original_main_title).strip()

        # 返回原始提取的标题，让公共解析器处理点号
        return original_main_title

    def extract_all(self, torrent_id=None):
        """
        提取所有种子信息

        Args:
            torrent_id: 可选的种子ID，用于保存提取内容到本地文件
        """
        # 提取基本信息
        basic_info = self.extract_basic_info()

        # 提取标签
        tags = self.extract_tags()

        # 添加去重处理，保持顺序
        if tags:
            tags = list(dict.fromkeys(tags))

        # 提取副标题
        subtitle = self.extract_subtitle()

        # 提取简介
        intro = self.extract_intro()

        # 提取MediaInfo
        mediainfo = self.extract_mediainfo()

        # 提取豆瓣信息
        douban_info = self.extract_douban_info()

        # 提取IMDb信息
        imdb_info = self.extract_imdb_info()

        # 提取主标题
        main_title = self.extract_title()

        # 提取产地信息（使用公共方法）
        full_description_text = f"{intro.get('statement', '')}\n{intro.get('body', '')}"
        origin_info = extract_origin_from_description(full_description_text)

        # 构建参数字典
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

        # 更新intro中的豆瓣和IMDb链接信息
        # 过滤豆瓣链接，只保留ID部分
        if douban_info:
            douban_match = re.match(r'(https?://movie\.douban\.com/subject/\d+)', douban_info)
            intro["douban_link"] = douban_match.group(1) if douban_match else douban_info
        else:
            intro["douban_link"] = douban_info
        intro["imdb_link"] = imdb_info

        extracted_data = {
            "source_params": source_params,
            "subtitle": subtitle,
            "intro": intro,
            "mediainfo": mediainfo,
        }

        return extracted_data
