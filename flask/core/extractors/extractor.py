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
            # Normalize title (replace dots with spaces, but preserve decimal points)
            import re
            title = re.sub(r'(?<!\d)\.|\.(?!\d\b)', ' ', title)
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
                else:
                    final_statement_quotes.append(quote)

            # Process quotes after poster
            for quote in quotes_after_poster:
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

        type_text = basic_info_dict.get("类型", "")
        type_match = re.search(r"[\(（](.*?)[\)）]", type_text)

        extracted_data["source_params"]["类型"] = type_match.group(
            1) if type_match else type_text.split("/")[-1]
        extracted_data["source_params"]["媒介"] = basic_info_dict.get("媒介")
        extracted_data["source_params"]["视频编码"] = basic_info_dict.get("编码")
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


class ParameterMapper:
    """Handles mapping of extracted parameters to standardized formats using the three-layer decoupling model"""

    def __init__(self):
        pass

    def load_site_config(self, site_name: str) -> Dict[str, Any]:
        """
        Load site configuration from YAML file

        Args:
            site_name: Name of the site

        Returns:
            Dict with site configuration
        """
        try:
            # 站点名称映射，处理中文名称到配置文件名的映射
            site_name_mapping = {
                "财神": "cspt",
                "财神站": "cspt",
                "Cspt": "cspt",
                "LuckPT": "luckpt",
                "幸运": "luckpt",
                "Audiences": "audiences",
                "HHClub": "hhclub",
                "13City": "13city",
                "Qingwapt": "qingwapt",
                "青蛙": "qingwapt"
            }

            # 获取实际的配置文件名
            actual_site_name = site_name_mapping.get(site_name, site_name)

            # Convert site name to config file name
            config_filename = f"{actual_site_name.lower().replace(' ', '_').replace('-', '_')}.yaml"
            config_path = os.path.join(CONFIG_DIR, config_filename)

            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    return yaml.safe_load(f) or {}
            else:
                # 如果特定站点配置不存在，尝试加载默认配置
                return {}
        except Exception:
            return {}

    def map_parameters(self, site_name: str,
                       extracted_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Map extracted parameters to standardized format using site configuration with three-layer decoupling model

        Args:
            site_name: Name of the target site
            extracted_params: Raw parameters extracted from source site

        Returns:
            Dict with standardized parameters
        """
        # Load site configuration
        site_config = self.load_site_config(site_name)

        # 保存调试信息
        import os
        tmp_dir = "data/tmp"
        os.makedirs(tmp_dir, exist_ok=True)
        with open(os.path.join(tmp_dir, "3_mapping_debug.txt"),
                  "w",
                  encoding="utf-8") as f:
            f.write(f"源站点名称: {site_name}\n")
            f.write(
                f"实际加载的配置文件名: {site_name.lower().replace(' ', '_').replace('-', '_')}.yaml\n"
            )
            f.write(f"站点配置是否存在: {bool(site_config)}\n")
            if site_config:
                f.write("站点配置内容:\n")
                import yaml
                f.write(yaml.dump(site_config, allow_unicode=True))
            else:
                f.write("未找到站点配置\n")

        # Check if the config uses the new three-layer structure
        source_parsers = site_config.get("source_parsers", {})
        mappings = site_config.get("mappings", {})
        standard_keys = source_parsers.get("standard_keys", {})

        # Initialize standardized parameters
        standardized_params = {}

        # Get source_params from extracted_params
        source_params = extracted_params.get("source_params", {})

        def standardize_raw_value(raw_value, param_key):
            """
            标准化原始值，主要用于视频编码、音频编码等参数的大小写统一
            """
            if not raw_value or not str(raw_value).strip():
                return raw_value

            value_str = str(raw_value).strip()

            # 对于视频编码相关的参数，统一转换为标准格式
            if param_key in ["video_codec", "codec"]:
                # 常见的编码格式标准化
                value_lower = value_str.lower()
                # 特殊处理一些常见的编码格式，保持标准写法
                if value_lower in ["h.264", "h264", "avc"]:
                    return "H.264"
                elif value_lower in ["h.265", "h265", "hevc"]:
                    return "H.265"
                elif value_lower in ["x264"]:
                    return "x264"
                elif value_lower in ["x265"]:
                    return "x265"
                else:
                    return value_lower  # 其他情况转换为小写

            # 对于音频编码相关的参数，转换为标准格式
            elif param_key in ["audio_codec"]:
                value_lower = value_str.lower()
                if value_lower in ["ac3", "dd"]:
                    return "AC3"
                elif value_lower in ["ddp", "e-ac3"]:
                    return "DDP"
                elif value_lower in ["truehd"]:
                    return "TrueHD"
                elif value_lower in ["dts"]:
                    return "DTS"
                elif value_lower in ["dtshd", "dts-hd"]:
                    return "DTS-HD"
                elif value_lower in ["flac"]:
                    return "FLAC"
                elif value_lower in ["aac"]:
                    return "AAC"
                else:
                    return value_str  # 保持原样

            # 对于制作组参数，保持原始大小写用于全局映射匹配
            elif param_key in ["team"]:
                return value_str  # 保持原始值，不进行大小写转换

            # 其他参数保持原样
            return value_str

        # Get title components from extracted_params
        title_components = extracted_params.get("title_components", [])

        # 如果配置文件使用新的三层结构，则使用新的映射逻辑
        if source_parsers and mappings:
            # 处理 source_params
            source_params_config = source_parsers.get("source_params", {})
            for param_key, param_config in source_params_config.items():
                source_key = param_config.get("source_key")
                if source_key and source_key in source_params:
                    raw_value = source_params[source_key]
                    # 保存原始值用于预览和标题构建
                    if isinstance(raw_value, str):
                        original_value = raw_value
                    else:
                        original_value = str(
                            raw_value) if raw_value is not None else ""

                    # 标准化原始值用于映射
                    standardized_raw_value = standardize_raw_value(
                        raw_value, param_key)
                    if standardized_raw_value and str(
                            standardized_raw_value).strip():
                        # 应用标准化键映射
                        if param_key in standard_keys:
                            param_mappings = standard_keys[param_key]
                            mapped = False
                            for source_text, standardized_key in param_mappings.items(
                            ):
                                # 改进的匹配逻辑，支持部分匹配
                                if (str(source_text).strip().lower()
                                        == str(standardized_raw_value).strip(
                                        ).lower()
                                        or str(source_text).strip().lower()
                                        in str(standardized_raw_value).strip(
                                        ).lower() or str(standardized_raw_value
                                                         ).strip().lower()
                                        in str(source_text).strip().lower()):
                                    standardized_params[
                                        param_key] = standardized_key
                                    mapped = True
                                    break
                            if not mapped:
                                # 如果没有找到匹配项，尝试使用全局映射
                                if param_key in GLOBAL_MAPPINGS:
                                    global_mappings = GLOBAL_MAPPINGS[
                                        param_key]
                                    for source_text, standardized_key in global_mappings.items(
                                    ):
                                        if (str(source_text).strip().lower()
                                                == str(standardized_raw_value
                                                       ).strip().lower() or
                                                str(source_text).strip().lower(
                                                ) in str(standardized_raw_value
                                                         ).strip().lower()
                                                or str(standardized_raw_value
                                                       ).strip().lower()
                                                in str(source_text).strip(
                                                ).lower()):
                                            standardized_params[
                                                param_key] = standardized_key
                                            mapped = True
                                            break

                                if not mapped:
                                    # 为不同字段类型提供默认标准键
                                    default_keys = {
                                        "type": "category.other",
                                        "medium": "medium.other",
                                        "video_codec": "codec.other",
                                        "audio_codec": "audio.other",
                                        "resolution": "resolution.other",
                                        "team": "team.other",
                                        "source": "source.other",
                                        "processing": "processing.other"
                                    }
                                    standardized_params[
                                        param_key] = default_keys.get(
                                            param_key, standardized_raw_value)
                        else:
                            # 如果没有standard_keys配置，尝试使用全局映射
                            mapped = False
                            if param_key in GLOBAL_MAPPINGS:
                                global_mappings = GLOBAL_MAPPINGS[param_key]
                                for source_text, standardized_key in global_mappings.items(
                                ):
                                    if (str(source_text).strip().lower()
                                            == str(standardized_raw_value
                                                   ).strip().lower() or
                                            str(source_text).strip().lower()
                                            in str(standardized_raw_value
                                                   ).strip().lower()
                                            or str(standardized_raw_value).
                                            strip().lower() in str(
                                                source_text).strip().lower()):
                                        standardized_params[
                                            param_key] = standardized_key
                                        mapped = True
                                        break

                            if not mapped:
                                # 如果没有找到匹配项，使用标准化后的原始值
                                standardized_params[
                                    param_key] = standardized_raw_value

            # 处理 title_components
            title_components_config = source_parsers.get(
                "title_components", {})
            title_key_mapping = {}
            for param_key, param_config in title_components_config.items():
                source_key = param_config.get("source_key")
                if source_key:
                    title_key_mapping[source_key] = param_key

            # 应用标题组件参数（补充模式）
            for component in title_components:
                key = component.get("key")
                value = component.get("value")
                if key and value and key in title_key_mapping:
                    standard_key = title_key_mapping[key]

                    # 只有当source_params中没有该字段时才使用title_components中的值
                    # 或者当source_params中的值为空/N/A时才使用title_components中的值
                    source_value = standardized_params.get(standard_key)
                    if not source_value or source_value == "N/A" or source_value == "None":
                        # 标准化原始值
                        standardized_value = standardize_raw_value(
                            value, standard_key)
                        # 应用标准化键映射
                        if standard_key in standard_keys:
                            param_mappings = standard_keys[standard_key]
                            mapped = False
                            for source_text, standardized_key in param_mappings.items(
                            ):
                                # 改进的匹配逻辑，支持部分匹配
                                if (str(source_text).strip().lower() == str(
                                        standardized_value).strip().lower()
                                        or str(source_text).strip().lower()
                                        in str(standardized_value).strip(
                                        ).lower() or
                                        str(standardized_value).strip().lower(
                                        ) in str(source_text).strip().lower()):
                                    # 添加调试信息
                                    standardized_params[
                                        standard_key] = standardized_key
                                    mapped = True
                                    break
                            if not mapped:
                                # 如果没有找到匹配项，尝试使用全局映射
                                if standard_key in GLOBAL_MAPPINGS:
                                    global_mappings = GLOBAL_MAPPINGS[
                                        standard_key]
                                    for source_text, standardized_key in global_mappings.items(
                                    ):
                                        if (str(source_text).strip().lower()
                                                == str(standardized_value
                                                       ).strip().lower() or
                                                str(source_text).strip().lower(
                                                ) in str(standardized_value
                                                         ).strip().lower() or
                                                str(standardized_value).strip(
                                                ).lower() in str(source_text).
                                                strip().lower()):
                                            standardized_params[
                                                standard_key] = standardized_key
                                            mapped = True
                                            break

                                if not mapped:
                                    # 如果仍然没有找到匹配项，使用标准化后的值
                                    standardized_params[
                                        standard_key] = standardized_value
                        else:
                            # 如果没有standard_keys配置，尝试使用全局映射
                            mapped = False
                            if standard_key in GLOBAL_MAPPINGS:
                                global_mappings = GLOBAL_MAPPINGS[standard_key]
                                for source_text, standardized_key in global_mappings.items(
                                ):
                                    if (str(source_text).strip().lower()
                                            == str(standardized_value).strip(
                                            ).lower() or
                                            str(source_text).strip().lower()
                                            in str(standardized_value).strip(
                                            ).lower()
                                            or str(standardized_value).strip(
                                            ).lower() in str(
                                                source_text).strip().lower()):
                                        standardized_params[
                                            standard_key] = standardized_key
                                        mapped = True
                                        break

                            if not mapped:
                                # 如果没有找到匹配项，使用标准化后的值
                                standardized_params[
                                    standard_key] = standardized_value

        else:
            # 如果配置文件使用旧的结构，则使用旧的映射逻辑（为了向后兼容）
            # Get extractors configuration
            extractors_config = site_config.get("extractors", {})

            # 中文字段名到英文字段名的映射
            chinese_to_english_mapping = {
                "类型": "type",
                "媒介": "medium",
                "视频编码": "codec",
                "音频编码": "audio_codec",
                "分辨率": "resolution",
                "制作组": "team",
                "标签": "tags",
                "产地": "source"
            }

            # Map source parameters
            for chinese_key, english_key in chinese_to_english_mapping.items():
                # Look for the parameter in source_params
                raw_value = source_params.get(chinese_key)
                if raw_value and str(raw_value).strip():
                    # Find matching mapping in extractors_config
                    if english_key in extractors_config:
                        mappings = extractors_config[english_key]
                        # Find matching mapping
                        mapped = False
                        for source_text, standardized_key in mappings.items():
                            # 改进的匹配逻辑，支持部分匹配
                            if (str(source_text).strip().lower()
                                    == str(raw_value).strip().lower()
                                    or str(source_text).strip().lower()
                                    in str(raw_value).strip().lower()
                                    or str(raw_value).strip().lower()
                                    in str(source_text).strip().lower()):
                                standardized_params[
                                    english_key] = standardized_key
                                mapped = True
                                break
                        # 如果没有找到匹配项，根据字段类型提供默认的标准键值
                        if not mapped:
                            # 为不同字段类型提供默认标准键
                            default_keys = {
                                "type": "category.other",
                                "medium": "medium.other",
                                "codec": "codec.other",
                                "audio_codec": "audio.other",
                                "resolution": "resolution.other",
                                "team": "team.other",
                                "source": "source.other"
                            }
                            standardized_params[
                                english_key] = default_keys.get(
                                    english_key, raw_value)
                    else:
                        # 如果没有对应的extractors配置，根据字段类型提供默认标准键
                        default_keys = {
                            "type": "category.other",
                            "medium": "medium.other",
                            "codec": "codec.other",
                            "audio_codec": "audio.other",
                            "resolution": "resolution.other",
                            "team": "team.other",
                            "source": "source.other"
                        }
                        standardized_params[english_key] = default_keys.get(
                            english_key, raw_value)

            # Map title components to standardized parameters (补充模式)
            title_key_mapping = {
                "主标题": "title",
                "季集": "season_episode",
                "年份": "year",
                "剧集状态": "status",
                "发布版本": "edition",
                "分辨率": "resolution",
                "媒介": "medium",
                "片源平台": "platform",
                "视频编码": "video_codec",  # 映射到video_codec
                "视频格式": "video_format",
                "HDR格式": "hdr_format",
                "色深": "bit_depth",
                "帧率": "frame_rate",
                "音频编码": "audio_codec",
                "制作组": "team"
            }

            # Apply title component parameter as补充 (只补充source_params中没有的字段)
            for component in title_components:
                key = component.get("key")
                value = component.get("value")
                if key and value and key in title_key_mapping:
                    standard_key = title_key_mapping[key]

                    # 只有当source_params中没有该字段时才使用title_components中的值
                    # 或者当source_params中的值为空/N/A时才使用title_components中的值
                    source_value = standardized_params.get(standard_key)
                    if not source_value or source_value == "N/A" or source_value == "None":
                        # Apply special transformations
                        if key == "视频编码":
                            value = str(value).upper() if value else value
                        elif key == "制作组":
                            value = str(value).upper() if value else value

                        # 如果有extractors配置，进行映射
                        if standard_key in extractors_config:
                            mappings = extractors_config[standard_key]
                            mapped = False
                            for source_text, standardized_key in mappings.items(
                            ):
                                if (str(source_text).strip().lower()
                                        == str(value).strip().lower()
                                        or str(source_text).strip().lower()
                                        in str(value).strip().lower()
                                        or str(value).strip().lower()
                                        in str(source_text).strip().lower()):
                                    standardized_params[
                                        standard_key] = standardized_key
                                    mapped = True
                                    break
                            if not mapped:
                                # 如果没有找到匹配项，尝试使用全局映射
                                if standard_key in GLOBAL_MAPPINGS:
                                    global_mappings = GLOBAL_MAPPINGS[
                                        standard_key]
                                    for source_text, standardized_key in global_mappings.items(
                                    ):
                                        if (str(source_text).strip().lower()
                                                == str(value).strip().lower()
                                                or str(source_text).strip(
                                                ).lower()
                                                in str(value).strip().lower()
                                                or str(value).strip().lower()
                                                in str(source_text).strip(
                                                ).lower()):
                                            standardized_params[
                                                standard_key] = standardized_key
                                            mapped = True
                                            break

                                if not mapped:
                                    # 如果仍然没有找到匹配项，根据字段类型提供默认的标准键值
                                    default_keys = {
                                        "type": "category.other",
                                        "medium": "medium.other",
                                        "codec": "codec.other",
                                        "audio_codec": "audio.other",
                                        "resolution": "resolution.other",
                                        "team": "team.other",
                                        "source": "source.other"
                                    }
                                    standardized_params[
                                        standard_key] = default_keys.get(
                                            standard_key, value)
                        else:
                            # 在新的三层解耦模型中，需要应用standard_keys映射
                            if standard_key in standard_keys:
                                param_mappings = standard_keys[standard_key]
                                mapped = False
                                for source_text, standardized_key in param_mappings.items(
                                ):
                                    # 改进的匹配逻辑，支持部分匹配
                                    if (str(source_text).strip().lower()
                                            == str(value).strip().lower() or
                                            str(source_text).strip().lower()
                                            in str(value).strip().lower()
                                            or str(value).strip().lower() in
                                            str(source_text).strip().lower()):
                                        # 添加调试信息
                                        standardized_params[
                                            standard_key] = standardized_key
                                        mapped = True
                                        break
                                if not mapped:
                                    # 如果没有找到匹配项，尝试使用全局映射
                                    if standard_key in GLOBAL_MAPPINGS:
                                        global_mappings = GLOBAL_MAPPINGS[
                                            standard_key]
                                        for source_text, standardized_key in global_mappings.items(
                                        ):
                                            if (str(source_text).strip().lower(
                                            ) == str(value).strip().lower()
                                                    or str(source_text).strip(
                                                    ).lower() in str(
                                                        value).strip().lower()
                                                    or
                                                    str(value).strip().lower()
                                                    in str(source_text).strip(
                                                    ).lower()):
                                                standardized_params[
                                                    standard_key] = standardized_key
                                                mapped = True
                                                break

                                    if not mapped:
                                        # 如果仍然没有找到匹配项，应用默认标准化键
                                        default_keys = {
                                            "type": "category.other",
                                            "medium": "medium.other",
                                            "video_codec": "codec.other",
                                            "audio_codec": "audio.other",
                                            "resolution": "resolution.other",
                                            "team": "team.other",
                                            "source": "source.other",
                                            "processing": "processing.other"
                                        }
                                        default_key = default_keys.get(
                                            standard_key, value)
                                        standardized_params[
                                            standard_key] = default_key
                            else:
                                # 如果没有standard_keys配置，尝试使用全局映射
                                mapped = False
                                if standard_key in GLOBAL_MAPPINGS:
                                    global_mappings = GLOBAL_MAPPINGS[
                                        standard_key]
                                    for source_text, standardized_key in global_mappings.items(
                                    ):
                                        if (str(source_text).strip().lower()
                                                == str(value).strip().lower()
                                                or str(source_text).strip(
                                                ).lower()
                                                in str(value).strip().lower()
                                                or str(value).strip().lower()
                                                in str(source_text).strip(
                                                ).lower()):
                                            standardized_params[
                                                standard_key] = standardized_key
                                            mapped = True
                                            break

                                if not mapped:
                                    # 如果没有找到匹配项，应用默认标准化键
                                    default_keys = {
                                        "type": "category.other",
                                        "medium": "medium.other",
                                        "video_codec": "codec.other",
                                        "audio_codec": "audio.other",
                                        "resolution": "resolution.other",
                                        "team": "team.other",
                                        "source": "source.other",
                                        "processing": "processing.other"
                                    }
                                    default_key = default_keys.get(
                                        standard_key, value)
                                    standardized_params[
                                        standard_key] = default_key

        # Special handling for tags - combine from different sources
        combined_tags = set()

        # Add tags from source_params
        source_tags = source_params.get("标签", [])
        if source_tags:
            if isinstance(source_tags, list):
                combined_tags.update(source_tags)
            else:
                combined_tags.add(source_tags)

        # Add tags from mediainfo if available
        mediainfo_text = extracted_params.get("mediainfo", "")
        if mediainfo_text:
            from utils import extract_tags_from_mediainfo
            tags_from_mediainfo = set(
                extract_tags_from_mediainfo(mediainfo_text))
            combined_tags.update(tags_from_mediainfo)

        if combined_tags:
            standardized_params["tags"] = list(combined_tags)

        # Handle IMDb and Douban links
        intro_data = extracted_params.get("intro", {})
        if intro_data.get("imdb_link"):
            standardized_params["imdb_link"] = intro_data["imdb_link"]
        if intro_data.get("douban_link"):
            standardized_params["douban_link"] = intro_data["douban_link"]

        # Handle description information
        standardized_params["description"] = {
            "statement": intro_data.get("statement", ""),
            "poster": intro_data.get("poster", ""),
            "body": intro_data.get("body", ""),
            "screenshots": intro_data.get("screenshots", "")
        }

        return standardized_params
