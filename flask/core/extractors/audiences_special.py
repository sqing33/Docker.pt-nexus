# -*- coding: utf-8 -*-
"""
Audiences特殊站点种子详情参数提取器
用于处理包含BDInfo和特殊MediaInfo格式的种子详情页
"""

import re
from bs4 import BeautifulSoup
from utils import extract_tags_from_mediainfo
from config import TEMP_DIR


class AudiencesSpecialExtractor:
    """Audiences特殊站点提取器"""

    def __init__(self, soup):
        self.soup = soup

    def extract_mediainfo(self):
        """
        提取MediaInfo信息
        处理多种格式：
        1. <div class="hide">里的详细MediaInfo
        2. <fieldset>里的BDInfo格式
        3. <div class="spoiler-content">里的MediaInfo
        4. <div class="nexus-media-info-raw">里的BDInfo
        """
        mediainfo_text = ""

        # 尝试从多个标准位置提取 MediaInfo 或 BDInfo
        selectors = [
            "div.spoiler-content pre",
            "div.nexus-media-info-raw > pre",
            "div.hide div.codemain",
            "div.show div.codemain",
            "div.codemain",
            "pre"
        ]

        for selector in selectors:
            elements = self.soup.select(selector)
            for element in elements:
                content = element.get_text(strip=True)
                if content:
                    # 检查是否包含MediaInfo或BDInfo特征
                    if self._is_valid_mediainfo(content):
                        mediainfo_text = content
                        print(f"在 {selector} 中找到有效的MediaInfo/BDInfo，长度: {len(mediainfo_text)}")
                        return mediainfo_text

        # 如果标准位置没有找到，尝试在简介的引用中查找
        if not mediainfo_text:
            descr_container = self.soup.select_one("div#kdescr")
            if descr_container:
                # 查找所有可能包含MediaInfo的区域
                for element in descr_container.descendants:
                    if element.name in ['div', 'pre', 'code']:
                        content = element.get_text()
                        if content and self._is_valid_mediainfo(content):
                            mediainfo_text = content
                            print(f"在简介中找到有效的MediaInfo/BDInfo，长度: {len(mediainfo_text)}")
                            break

        return mediainfo_text

    def _is_valid_mediainfo(self, content):
        """
        检查内容是否为有效的MediaInfo或BDInfo格式
        """
        if not content or len(content) < 50:  # 太短的内容不考虑
            return False

        # MediaInfo 格式的必要关键字
        mediainfo_required_keywords = ["General", "Video", "Audio"]

        # BDInfo 格式的必要关键字
        bdinfo_required_keywords = ["DISC INFO", "PLAYLIST REPORT"]

        # BDInfo 格式的可选关键字 (扩展了关键字列表以更好地识别"人人"站点的BDInfo)
        bdinfo_optional_keywords = [
            "VIDEO:", "AUDIO:", "SUBTITLES:", "FILES:",
            "Disc Label", "Disc Size", "BDInfo:", "Protection:",
            "Codec", "Bitrate", "Language", "Description"
        ]

        content_lines = content.split('\n')

        # 检查是否为标准MediaInfo格式
        mediainfo_matches = sum(1 for keyword in mediainfo_required_keywords if any(keyword in line for line in content_lines))
        if mediainfo_matches >= 2:  # 至少匹配2个关键字
            return True

        # 检查是否为BDInfo格式
        bdinfo_required_matches = sum(1 for keyword in bdinfo_required_keywords if any(keyword in line for line in content_lines))
        bdinfo_optional_matches = sum(1 for keyword in bdinfo_optional_keywords if any(keyword in line for line in content_lines))

        # BDInfo需要匹配所有必要关键字，或者匹配部分必要关键字和足够的可选关键字
        # 为"人人"站点放宽条件，只需要匹配一个必要关键字和一个可选关键字即可
        if bdinfo_required_matches >= 1 and bdinfo_optional_matches >= 1:
            return True

        # 原始严格的匹配条件作为备选
        if bdinfo_required_matches == len(bdinfo_required_keywords) or \
           (bdinfo_required_matches >= 1 and bdinfo_optional_matches >= 2):
            return True

        return False

    def extract_intro(self):
        """
        提取简介信息，过滤多余内容
        """
        descr_container = self.soup.select_one("div#kdescr")
        if not descr_container:
            return {}

        intro = {}
        quotes = []
        images = []
        body = ""

        # 提取所有引用块
        quote_elements = descr_container.select("fieldset")
        for quote_element in quote_elements:
            # 检查是否是引用标题
            legend = quote_element.select_one("legend")
            if legend and "引用" in legend.get_text():
                # 获取引用内容（排除legend）
                quote_content = ""
                for child in quote_element.children:
                    if child != legend:
                        quote_content += str(child)

                # 清理引用内容
                quote_text = BeautifulSoup(quote_content, "html.parser").get_text().strip()
                if quote_text:
                    # 过滤掉不需要的声明和信息
                    if not self._is_unwanted_declaration(quote_text):
                        quotes.append(f"[quote]{quote_text}[/quote]")

        # 提取图片
        img_elements = descr_container.select("img")
        for img in img_elements:
            src = img.get("src")
            if src:
                images.append(f"[img]{src}[/img]")

        # 提取正文内容（排除引用和图片）
        body_content = str(descr_container)
        # 移除所有<fieldset>块
        body_content = re.sub(r"<fieldset>.*?</fieldset>", "", body_content, flags=re.DOTALL)
        # 移除所有<img>标签
        body_content = re.sub(r"<img[^>]*>", "", body_content)
        # 移除div.show和div.hide块中的技术信息
        body_content = re.sub(r'<div class="(?:show|hide|codetop|codemain)">.*?</div>', "", body_content, flags=re.DOTALL)

        # 清理HTML标签获取纯文本
        body_soup = BeautifulSoup(body_content, "html.parser")
        body = body_soup.get_text().strip()

        # 过滤掉ARUTU相关工具的声明信息
        body_lines = [line for line in body.split('\n') if not self._is_unwanted_declaration(line)]
        body = '\n'.join(body_lines).strip()

        intro = {
            "statement": "\n".join(quotes) if quotes else "",
            "poster": images[0] if images else "",
            "body": re.sub(r"\n{2,}", "\n", body),
            "screenshots": "\n".join(images[1:]) if len(images) > 1 else "",
        }

        return intro

    def _is_unwanted_declaration(self, text):
        """
        判断是否为不需要的声明信息
        """
        unwanted_patterns = [
            "ARDTU工具自动发布",
            "有错误请评论或举报",
            "郑重声明：",
            "本站提供的所有作品均是用户自行搜集并且上传",
            "禁止任何涉及商业盈利目的使用",
            "请在下载后24小时内尽快删除",
            "财神CSWEB提供的所有资源均是在网上搜集且由用户上传",
            "不可用于任何形式的商业盈利活动",
            "By ARDTU",
            ".Release.Info",  # 不规范的MediaInfo声明
            "| A | By ATU"  # 特定工具签名
        ]

        return any(pattern in text for pattern in unwanted_patterns)

    def extract_basic_info(self):
        """
        提取基本信息
        """
        basic_info_dict = {}
        basic_info_td = self.soup.find("td", string="基本信息")

        if basic_info_td and basic_info_td.find_next_sibling("td"):
            strings = list(basic_info_td.find_next_sibling("td").stripped_strings)
            basic_info_dict = {
                s.replace(":", "").strip(): strings[i + 1]
                for i, s in enumerate(strings)
                if ":" in s and i + 1 < len(strings)
            }

        return basic_info_dict

    def extract_tags(self):
        """
        提取标签
        """
        tags_td = self.soup.find("td", string="标签")
        if tags_td and tags_td.find_next_sibling("td"):
            return [
                s.get_text(strip=True)
                for s in tags_td.find_next_sibling("td").find_all("span")
            ]
        return []

    def extract_subtitle(self):
        """
        提取副标题并清理
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

    def extract_origin_info(self, full_description_text):
        """
        从完整描述中提取产地信息
        """
        # 实现产地信息提取逻辑
        patterns = [
            r"[产]\s*地[:\s]+([^，,\n\r]+)",
            r"[国]\s*家[:\s]+([^，,\n\r]+)",
            r"[地]\s*区[:\s]+([^，,\n\r]+)"
        ]

        for pattern in patterns:
            match = re.search(pattern, full_description_text)
            if match:
                return match.group(1).strip()

        return ""


    def extract_detailed_params(self):
        """
        提取详细的参数信息，以文本格式返回所有参数名和对应的值
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
        origin_info = self.extract_origin_info(full_description_text)

        # 构建详细的参数字典
        detailed_params = {
            "类型": basic_info.get("类型", ""),
            "媒介": basic_info.get("媒介", ""),
            "编码": basic_info.get("编码", ""),
            "音频编码": basic_info.get("音频编码", ""),
            "分辨率": basic_info.get("分辨率", ""),
            "制作组": basic_info.get("制作组", ""),
            "标签": tags,
            "产地": origin_info,
            "副标题": subtitle,
            "声明": intro.get("statement", ""),
            "海报": intro.get("poster", ""),
            "正文": intro.get("body", ""),
            "截图": intro.get("screenshots", ""),
            "MediaInfo": mediainfo,
        }

        return detailed_params

    def extract_all(self, torrent_id=None):
        """
        提取所有种子信息

        Args:
            torrent_id: 可选的种子ID，用于保存提取内容到本地文件
        """
        print(f"开始提取种子信息，种子ID: {torrent_id}")  # 添加调试信息

        # 提取基本信息
        basic_info = self.extract_basic_info()
        print(f"基本信息提取完成: {basic_info}")  # 添加调试信息

        # 提取标签
        tags = self.extract_tags()
        print(f"标签提取完成: {tags}")  # 添加调试信息

        # 提取副标题
        subtitle = self.extract_subtitle()
        print(f"副标题提取完成: {subtitle}")  # 添加调试信息

        # 提取简介
        intro = self.extract_intro()
        print(f"简介提取完成: {len(intro.get('statement', ''))} 字符声明, {len(intro.get('body', ''))} 字符正文")  # 添加调试信息

        # 提取MediaInfo
        mediainfo = self.extract_mediainfo()
        print(f"MediaInfo提取完成: {len(mediainfo)} 字符")  # 添加调试信息

        # 提取产地信息
        full_description_text = f"{intro.get('statement', '')}\n{intro.get('body', '')}"
        origin_info = self.extract_origin_info(full_description_text)
        print(f"产地信息提取完成: {origin_info}")  # 添加调试信息

        # 构建参数字典
        source_params = {
            "类型": basic_info.get("类型", ""),
            "媒介": basic_info.get("媒介"),
            "编码": basic_info.get("编码"),
            "音频编码": basic_info.get("音频编码"),
            "分辨率": basic_info.get("分辨率"),
            "制作组": basic_info.get("制作组"),
            "标签": tags,
            "产地": origin_info,
        }
        print(f"源参数构建完成: {source_params}")  # 添加调试信息

        extracted_data = {
            "source_params": source_params,
            "subtitle": subtitle,
            "intro": intro,
            "mediainfo": mediainfo,
        }
        print(f"提取数据构建完成")  # 添加调试信息

        # 如果提供了torrent_id，则打印调试信息
        if torrent_id:
            print(f"种子ID: {torrent_id}")  # 添加调试信息
        else:
            print("未提供种子ID")  # 添加调试信息

        return extracted_data