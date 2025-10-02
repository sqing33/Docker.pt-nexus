"""
Extractor module for standardized parameter extraction from torrent sites.

This module implements a clean, modular architecture for:
1. Receiving HTML content and site name from migrator
2. Choosing between public or site-specific extractors
3. Extracting raw parameters from source sites
4. Returning standardized parameters to migrator for mapping
"""

import os
import yaml
from typing import Dict, Any, Optional
from bs4 import BeautifulSoup

import os

CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "configs")
from .sites.audiences import AudiencesSpecialExtractor

# 加载全局映射配置
GLOBAL_MAPPINGS = {}
try:
    global_mappings_path = os.path.join(CONFIG_DIR, "global_mappings.yaml")
    if os.path.exists(global_mappings_path):
        with open(global_mappings_path, 'r', encoding='utf-8') as f:
            global_config = yaml.safe_load(f)
            GLOBAL_MAPPINGS = global_config.get("global_standard_keys", {})
except Exception as e:
    print(f"警告：无法加载全局映射配置: {e}")
from .sites.ssd import SSDSpecialExtractor
from .sites.hhanclub import HHCLUBSpecialExtractor


class Extractor:
    """Main extractor class that orchestrates the extraction process"""

    def __init__(self):
        self.special_extractors = {
            "人人": AudiencesSpecialExtractor,
            "不可说": SSDSpecialExtractor,
            "憨憨": HHCLUBSpecialExtractor,
        }

    def extract(self,
                soup: BeautifulSoup,
                site_name: str,
                torrent_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Extract parameters from torrent page using appropriate extractor

        Args:
            soup: BeautifulSoup object of the torrent page
            site_name: Name of the source site
            torrent_id: Optional torrent ID for special extractors

        Returns:
            Dict with extracted data in standardized format
        """
        # Determine which extractor to use
        if site_name in self.special_extractors:
            # Use special extractor for specific sites
            extractor_class = self.special_extractors[site_name]
            extractor = extractor_class(soup)
            extracted_data = extractor.extract_all(torrent_id)
        else:
            # Use public extractor for general sites
            extracted_data = self._extract_with_public_extractor(soup)

        return extracted_data

    def _extract_with_public_extractor(self,
                                       soup: BeautifulSoup) -> Dict[str, Any]:
        """
        Extract data using the public/common extractor

        Args:
            soup: BeautifulSoup object of the torrent page

        Returns:
            Dict with extracted data in standardized format
        """
        # Initialize default data structure
        extracted_data = {
            "title": "",
            "subtitle": "",
            "intro": {
                "statement": "",
                "poster": "",
                "body": "",
                "screenshots": "",
                "removed_ardtudeclarations": [],
                "imdb_link": "",
                "douban_link": ""
            },
            "mediainfo": "",
            "source_params": {
                "类型": "",
                "媒介": None,
                "视频编码": None,
                "音频编码": None,
                "分辨率": None,
                "制作组": None,
                "标签": [],
                "产地": ""
            }
        }

        # Extract title from h1#top
        h1_top = soup.select_one("h1#top")
        if h1_top:
            title = list(
                h1_top.stripped_strings)[0] if h1_top.stripped_strings else ""
            # Normalize title (replace dots with spaces, but preserve decimal points and codec formats)
            import re
            title = re.sub(r'(?<!\d)(?<!H)(?<!x)\.|\.(?!\d\b)(?!264)(?!265)', ' ', title)
            title = re.sub(r'\s+', ' ', title).strip()
            extracted_data["title"] = title

        # Extract subtitle
        import re
        subtitle_td = soup.find("td", string=re.compile(r"\s*副标题\s*"))
        if subtitle_td and subtitle_td.find_next_sibling("td"):
            subtitle = subtitle_td.find_next_sibling("td").get_text(strip=True)
            # Clean subtitle from group information
            subtitle = re.sub(r"\s*\|\s*[Aa][Bb]y\s+\w+.*$", "", subtitle)
            subtitle = re.sub(r"\s*\|\s*[Bb]y\s+\w+.*$", "", subtitle)
            subtitle = re.sub(r"\s*\|\s*[Aa]\s+\w+.*$", "", subtitle)
            subtitle = re.sub(r"\s*\|\s*[Aa][Tt][Uu]\s*$", "", subtitle)
            subtitle = re.sub(r"\s*\|\s*[Dd][Tt][Uu]\s*$", "", subtitle)
            subtitle = re.sub(r"\s*\|\s*[Pp][Tt][Ee][Rr]\s*$", "", subtitle)
            extracted_data["subtitle"] = subtitle

        # Extract description information
        descr_container = soup.select_one("div#kdescr")
        if descr_container:
            # Extract IMDb and Douban links
            descr_text = descr_container.get_text()
            imdb_link = ""
            douban_link = ""

            if imdb_match := re.search(
                    r"(https?://www\.imdb\.com/title/tt\d+)", descr_text):
                imdb_link = imdb_match.group(1)

            if douban_match := re.search(
                    r"(https?://movie\.douban\.com/subject/\d+)", descr_text):
                douban_link = douban_match.group(1)

            extracted_data["intro"]["imdb_link"] = imdb_link
            extracted_data["intro"]["douban_link"] = douban_link

            # Process description content to extract quotes, images, and body text
            descr_html_string = str(descr_container)
            corrected_descr_html = re.sub(r'</?br\s*/?>',
                                          '<br/>',
                                          descr_html_string,
                                          flags=re.IGNORECASE)
            corrected_descr_html = re.sub(r'(<img[^>]*[^/])>', r'\1 />',
                                          corrected_descr_html)

            try:
                from bs4 import BeautifulSoup as BS
                descr_container_soup = BS(corrected_descr_html, "lxml")
            except ImportError:
                descr_container_soup = BS(corrected_descr_html, "html.parser")

            bbcode = self._html_to_bbcode(descr_container_soup)

            # Clean nested quotes
            original_bbcode = bbcode
            while True:
                bbcode = re.sub(r"\[quote\]\s*\[quote\]",
                                "[quote]",
                                bbcode,
                                flags=re.IGNORECASE)
                bbcode = re.sub(r"\[/quote\]\s*\[/quote\]",
                                "[/quote]",
                                bbcode,
                                flags=re.IGNORECASE)
                if bbcode == original_bbcode:
                    break
                original_bbcode = bbcode

            # Extract images
            images = re.findall(r"\[img\].*?\[/img\]", bbcode)

            # Extract quotes before and after poster
            poster_index = bbcode.find(images[0]) if images else -1
            quotes_before_poster = []
            quotes_after_poster = []

            for match in re.finditer(r"\[quote\].*?\[/quote\]", bbcode,
                                     re.DOTALL):
                quote_content = match.group(0)
                quote_start = match.start()

                if poster_index != -1 and quote_start < poster_index:
                    quotes_before_poster.append(quote_content)
                else:
                    quotes_after_poster.append(quote_content)

            # 辅助函数：检查是否为包含技术参数的quote（这些既不是mediainfo也不应该出现在正文中）
            def is_technical_params_quote(quote_text):
                return (
                    (".Release.Info" in quote_text and "ENCODER" in quote_text) or
                    ("ENCODER" in quote_text and "RELEASE NAME" in quote_text) or
                    (".Release.Info" in quote_text and ".Media.Info" in quote_text) or
                    ("ViDEO CODEC" in quote_text and "AUDiO CODEC" in quote_text) or
                    (".x265.Info" in quote_text and "x265" in quote_text)
                )

            # Process quotes
            final_statement_quotes = []
            ardtu_declarations = []
            mediainfo_from_quote = ""
            found_mediainfo_in_quote = False
            quotes_for_body = []

            # Process quotes before poster
            for quote in quotes_before_poster:
                is_mediainfo = ("General" in quote and "Video" in quote
                                and "Audio" in quote)
                is_bdinfo = ("DISC INFO" in quote
                             and "PLAYLIST REPORT" in quote)
                is_release_info_style = ".Release.Info" in quote and "ENCODER" in quote

                if not found_mediainfo_in_quote and (is_mediainfo or is_bdinfo
                                                     or is_release_info_style):
                    mediainfo_from_quote = re.sub(r"\[/?quote\]",
                                                  "",
                                                  quote,
                                                  flags=re.IGNORECASE).strip()
                    found_mediainfo_in_quote = True
                    # 将mediainfo/bdinfo quote也保存到removed_ardtudeclarations中
                    clean_content = re.sub(r"\[\/?quote\]", "", quote).strip()
                    ardtu_declarations.append(clean_content)
                    continue

                is_ardtutool_auto_publish = ("ARDTU工具自动发布" in quote)
                is_disclaimer = ("郑重声明：" in quote)
                is_csweb_disclaimer = ("财神CSWEB提供的所有资源均是在网上搜集且由用户上传" in quote)
                is_by_ardtu_group_info = "By ARDTU" in quote and "官组作品" in quote
                has_atu_tool_signature = "| A | By ATU" in quote

                if is_ardtutool_auto_publish or is_disclaimer or is_csweb_disclaimer or has_atu_tool_signature:
                    clean_content = re.sub(r"\[\/?quote\]", "", quote).strip()
                    ardtu_declarations.append(clean_content)
                elif is_by_ardtu_group_info:
                    filtered_quote = re.sub(r"\s*By ARDTU\s*", "", quote)
                    final_statement_quotes.append(filtered_quote)
                elif "ARDTU" in quote:
                    clean_content = re.sub(r"\[\/?quote\]", "", quote).strip()
                    ardtu_declarations.append(clean_content)
                elif is_technical_params_quote(quote):
                    # 将技术参数quote添加到ARDTU声明中，这样它们会被过滤掉不会出现在正文中
                    clean_content = re.sub(r"\[\/?quote\]", "", quote).strip()
                    ardtu_declarations.append(clean_content)
                else:
                    final_statement_quotes.append(quote)

            # Process quotes after poster
            for quote in quotes_after_poster:
                # 检查是否为mediainfo/bdinfo/技术参数的quote
                is_mediainfo_after = ("General" in quote and "Video" in quote and "Audio" in quote)
                is_bdinfo_after = ("DISC INFO" in quote and "PLAYLIST REPORT" in quote)
                is_release_info_after = ".Release.Info" in quote and "ENCODER" in quote
                is_technical_after = is_technical_params_quote(quote)

                if is_mediainfo_after or is_bdinfo_after or is_release_info_after or is_technical_after:
                    # 过滤掉并保存到ardtu_declarations
                    clean_content = re.sub(r"\[\/?quote\]", "", quote).strip()
                    ardtu_declarations.append(clean_content)
                else:
                    quotes_for_body.append(quote)

            # Extract body content
            body = (re.sub(r"\[quote\].*?\[/quote\]|\[img\].*?\[/img\]",
                           "",
                           bbcode,
                           flags=re.DOTALL).replace("\r", "").strip())

            # Add quotes after poster to body
            if quotes_for_body:
                body = body + "\n\n" + "\n".join(quotes_for_body)

            # Format statement string
            statement_string = "\n".join(final_statement_quotes)
            if statement_string:
                statement_string = re.sub(r'(\r?\n){3,}', r'\n\n',
                                          statement_string).strip()

            extracted_data["intro"]["statement"] = statement_string
            extracted_data["intro"]["poster"] = images[0] if images else ""
            extracted_data["intro"]["body"] = re.sub(r"\n{2,}", "\n", body)
            extracted_data["intro"]["screenshots"] = "\n".join(
                images[1:]) if len(images) > 1 else ""
            extracted_data["intro"][
                "removed_ardtudeclarations"] = ardtu_declarations

        # Extract MediaInfo
        mediainfo_pre = soup.select_one(
            "div.spoiler-content pre, div.nexus-media-info-raw > pre")
        mediainfo_text = mediainfo_pre.get_text(
            strip=True) if mediainfo_pre else ""

        if not mediainfo_text and mediainfo_from_quote:
            mediainfo_text = mediainfo_from_quote

        # Format mediainfo string
        if mediainfo_text:
            mediainfo_text = re.sub(r'(\r?\n){2,}', r'\n',
                                    mediainfo_text).strip()

        extracted_data["mediainfo"] = mediainfo_text

        # Extract basic info and tags
        basic_info_td = soup.find("td", string="基本信息")
        basic_info_dict = {}
        if basic_info_td and basic_info_td.find_next_sibling("td"):
            strings = list(
                basic_info_td.find_next_sibling("td").stripped_strings)
            basic_info_dict = {
                s.replace(":", "").strip(): strings[i + 1]
                for i, s in enumerate(strings)
                if ":" in s and i + 1 < len(strings)
            }

        tags_td = soup.find("td", string="标签")
        tags = ([
            s.get_text(strip=True)
            for s in tags_td.find_next_sibling("td").find_all("span")
        ] if tags_td and tags_td.find_next_sibling("td") else [])

        # 添加去重处理，保持顺序
        if tags:
            tags = list(dict.fromkeys(tags))

        type_text = basic_info_dict.get("类型", "")
        type_match = re.search(r"[\(（](.*?)[\)）]", type_text)

        extracted_data["source_params"]["类型"] = type_match.group(
            1) if type_match else type_text.split("/")[-1]
        extracted_data["source_params"]["媒介"] = basic_info_dict.get("媒介")
        # 视频编码：优先获取"视频编码"，如果没有则获取"编码"
        extracted_data["source_params"]["视频编码"] = basic_info_dict.get("视频编码") or basic_info_dict.get("编码")
        extracted_data["source_params"]["音频编码"] = basic_info_dict.get("音频编码")
        extracted_data["source_params"]["分辨率"] = basic_info_dict.get("分辨率")
        extracted_data["source_params"]["制作组"] = basic_info_dict.get("制作组")
        extracted_data["source_params"]["标签"] = tags

        # Extract origin information
        from utils import extract_origin_from_description
        full_description_text = f"{extracted_data['intro']['statement']}\n{extracted_data['intro']['body']}"
        origin_info = extract_origin_from_description(full_description_text)

        # Apply global mapping for origin information
        if origin_info and GLOBAL_MAPPINGS and "source" in GLOBAL_MAPPINGS:
            source_mappings = GLOBAL_MAPPINGS["source"]
            mapped_origin = None
            # Try to find a match in the global mappings
            for source_text, standardized_key in source_mappings.items():
                # 改进的匹配逻辑，支持部分匹配
                if (str(source_text).strip().lower()
                        == str(origin_info).strip().lower()
                        or str(source_text).strip().lower()
                        in str(origin_info).strip().lower()
                        or str(origin_info).strip().lower()
                        in str(source_text).strip().lower()):
                    mapped_origin = standardized_key
                    break

            # If we found a mapping, use it; otherwise keep the original
            if mapped_origin:
                extracted_data["source_params"]["产地"] = mapped_origin
            else:
                extracted_data["source_params"]["产地"] = origin_info
        else:
            extracted_data["source_params"]["产地"] = origin_info

        return extracted_data

    def _html_to_bbcode(self, tag) -> str:
        """
        Convert HTML to BBCode

        Args:
            tag: BeautifulSoup tag

        Returns:
            BBCode string
        """
        import re
        content = []
        if not hasattr(tag, "contents"):
            return ""
        for child in tag.contents:
            if isinstance(child, str):
                content.append(child.replace("\xa0", " "))
            elif child.name == "br":
                content.append("\n")
            elif child.name == "fieldset":
                content.append(
                    f"[quote]{self._html_to_bbcode(child).strip()}[/quote]")
            elif child.name == "legend":
                continue
            elif child.name == "b":
                content.append(f"[b]{self._html_to_bbcode(child)}[/b]")
            elif child.name == "img" and child.get("src"):
                content.append(f"[img]{child['src']}[/img]")
            elif child.name == "a" and child.get("href"):
                content.append(
                    f"[url={child['href']}]{self._html_to_bbcode(child)}[/url]"
                )
            elif (child.name == "span" and child.get("style") and
                  (match := re.search(r"color:\s*([^;]+)", child["style"]))):
                content.append(
                    f"[color={match.group(1).strip()}]{self._html_to_bbcode(child)}[/color]"
                )
            elif child.name == "font" and child.get("size"):
                content.append(
                    f"[size={child['size']}]{self._html_to_bbcode(child)}[/size]"
                )
            else:
                content.append(self._html_to_bbcode(child))
        return "".join(content)


# [新增] 定义音频编码的层级（权重），数字越大越优先
AUDIO_CODEC_HIERARCHY = {
    # Top Tier (最精确)
    "audio.truehd_atmos": 5,
    "audio.dtsx": 5,
    # High Tier (无损次世代)
    "audio.truehd": 4,
    "audio.dts_hd_ma": 4,
    # Mid Tier (有损次世代 / 无损)
    "audio.ddp": 3,
    "audio.dts": 3,
    "audio.flac": 3,
    "audio.lpcm": 3,
    # Standard Tier (核心/普通)
    "audio.ac3": 2,
    # Low Tier (有损)
    "audio.aac": 1,
    "audio.mp3": 1,
    "audio.alac": 1,
    "audio.ape": 1,
    "audio.m4a": 1,
    "audio.wav": 1,
    # Other/Default
    "audio.other": 0,
}


class ParameterMapper:
    """
    [修正] Handles mapping of extracted parameters to standardized formats,
    with corrected logic for global and site-specific mappings.
    """

    def __init__(self):
        pass

    def _map_tags(self, raw_tags, site_name: str):
        """
        将原始标签映射到站点特定格式
        """
        if not raw_tags:
            return []

        # 首先尝试使用站点特定配置
        site_config = self.load_site_config(site_name)
        site_mappings = site_config.get("mappings", {}).get("tag", {})

        # 确保我们总是有全局映射作为后备
        global_tag_mappings = GLOBAL_MAPPINGS.get("tag", {})

        mapped_tags = []
        unmapped_tags = []

        for raw_tag in raw_tags:
            mapped_tag = None
            # 首先尝试站点特定映射的精确匹配
            for source_text, standard_key in site_mappings.items():
                if source_text.lower() == raw_tag.lower():
                    mapped_tag = standard_key
                    break

            # 如果没有精确匹配，尝试站点特定映射的部分匹配
            if not mapped_tag:
                for source_text, standard_key in site_mappings.items():
                    if (source_text.lower() in raw_tag.lower()
                            or raw_tag.lower() in source_text.lower()
                        ) and standard_key is not None:
                        mapped_tag = standard_key
                        break

            # 如果站点特定映射没有找到，尝试全局映射
            if not mapped_tag:
                # 全局映射的精确匹配
                for source_text, standard_key in global_tag_mappings.items():
                    if source_text.lower() == raw_tag.lower(
                    ) and standard_key is not None:
                        mapped_tag = standard_key
                        break

                # 全局映射的部分匹配
                if not mapped_tag:
                    for source_text, standard_key in global_tag_mappings.items(
                    ):
                        if ((source_text.lower() in raw_tag.lower()
                             or raw_tag.lower() in source_text.lower())
                                and standard_key is not None):
                            mapped_tag = standard_key
                            break

            # 如果找到映射，使用映射值；否则保留原始值
            if mapped_tag:
                mapped_tags.append(mapped_tag)
            else:
                # 保留原始标签但记录未映射
                mapped_tags.append(raw_tag)
                unmapped_tags.append(raw_tag)

        # 记录未映射的标签
        if unmapped_tags:
            print(f"警告：站点 {site_name} 的以下标签未在配置中定义: {unmapped_tags}")

        return mapped_tags

    def load_site_config(self, site: str) -> Dict[str, Any]:
        """
        Load site configuration from YAML file
        """
        try:
            config_filename = f"{site.lower().replace(' ', '_').replace('-', '_')}.yaml"
            config_path = os.path.join(CONFIG_DIR, config_filename)
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    return yaml.safe_load(f) or {}
            else:
                return {}
        except Exception:
            return {}

    def map_parameters(self, site_name: str, site: str,
                       extracted_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        [修正] Map extracted parameters to standardized format.
        This version ensures that global_mappings are correctly applied.
        """
        site_config = self.load_site_config(site)
        source_parsers = site_config.get("source_parsers", {})
        site_standard_keys = source_parsers.get("standard_keys", {})

        source_params = extracted_params.get("source_params", {})
        title_components = extracted_params.get("title_components", [])

        # 辅助函数：将原始值转换为标准键的核心逻辑
        def get_standard_key_for_value(raw_value: str, param_key: str) -> str:
            if not raw_value:
                return None

            value_str = str(raw_value).strip()

            # 优先级 1: 尝试在全局映射中查找
            global_mappings = GLOBAL_MAPPINGS.get(param_key, {})
            for source_text, standard_key in global_mappings.items():
                # 使用精确匹配优先，然后是部分匹配
                if source_text.lower() == value_str.lower():
                    return standard_key
            # 如果没有精确匹配，再尝试部分匹配（防止WiKi匹配到WiKibbs等）
            for source_text, standard_key in global_mappings.items():
                if source_text.lower() in value_str.lower():
                    return standard_key

            # 优先级 2: 尝试在源站点特定的映射中查找
            site_mappings = site_standard_keys.get(param_key, {})
            for source_text, standard_key in site_mappings.items():
                if source_text.lower() in value_str.lower():
                    return standard_key

            # 如果都找不到，返回一个默认值或处理过的原始值
            if param_key == "team":
                return "team.other"  # 制作组找不到映射时，明确返回 team.other
            return value_str  # 其他参数返回原始值

        # 1. 分别从 source_params 和 title_components 提取并标准化
        source_standard_values = {}
        source_params_config = source_parsers.get("source_params", {})
        for param_key, config in source_params_config.items():
            raw_value = source_params.get(config.get("source_key"))
            if raw_value:
                source_standard_values[param_key] = get_standard_key_for_value(
                    raw_value, param_key)

        # [调试] 打印源站点提取到的标准化参数（标题补全之前）
        print(f"=== 源站点 {site_name} 提取到的参数（标题补全前） ===")
        print(f"原始source_params: {source_params}")
        print(f"标准化后的source_standard_values: {source_standard_values}")
        print("=" * 60)

        title_standard_values = {}
        title_components_config = source_parsers.get("title_components", {})
        title_params = {
            item["key"]: item["value"]
            for item in title_components
        }
        for param_key, config in title_components_config.items():
            raw_value = title_params.get(config.get("source_key"))
            if raw_value:
                title_standard_values[param_key] = get_standard_key_for_value(
                    raw_value, param_key)

        # 2. 合并决策
        final_standardized_params = source_standard_values.copy()

        for key, title_value in title_standard_values.items():
            if not title_value: continue

            # [核心修正] 制作组（team）总是优先使用标题中的信息
            if key == 'team':
                final_standardized_params[key] = title_value
                continue

            # 音频编码使用择优逻辑
            if key == 'audio_codec':
                source_value = final_standardized_params.get(key)
                title_rank = AUDIO_CODEC_HIERARCHY.get(title_value, 0)
                source_rank = AUDIO_CODEC_HIERARCHY.get(source_value, -1)
                if title_rank > source_rank:
                    final_standardized_params[key] = title_value
                continue

            # 其他参数作为补充
            if key not in final_standardized_params:
                final_standardized_params[key] = title_value

        # 添加processing参数到source参数的映射
        # 如果存在processing参数但没有source参数，则将processing映射为source
        if "processing" in final_standardized_params and "source" not in final_standardized_params:
            final_standardized_params["source"] = final_standardized_params[
                "processing"]
        elif "source" not in final_standardized_params:
            # 如果两者都不存在，尝试从原始参数中获取
            processing_value = source_params.get(
                "区域")  # 13city.yaml中定义的source_key
            if processing_value:
                final_standardized_params[
                    "source"] = get_standard_key_for_value(
                        processing_value, "source")

        # 处理标签映射 - 使用站点特定的标签映射
        final_standardized_params["tags"] = self._map_tags(
            source_params.get("标签", []), site_name)

        return final_standardized_params
