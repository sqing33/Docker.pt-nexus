import os
import yaml
from typing import Dict, Any, Optional
from bs4 import BeautifulSoup
import re
import logging
import requests
import urllib.parse

# 导入自定义工具函数
from utils import handle_incomplete_links, search_by_subtitle, normalize_imdb_link
from utils.content_filter import get_content_filter, get_unwanted_image_urls
from config import GLOBAL_MAPPINGS
from .sites.audiences import AudiencesSpecialExtractor

# 站点配置目录路径
CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "configs")

# 加载全局映射配置
GLOBAL_STANDARD_KEYS = {}
DEFAULT_TITLE_COMPONENTS = {}
try:
    if os.path.exists(GLOBAL_MAPPINGS):
        with open(GLOBAL_MAPPINGS, "r", encoding="utf-8") as f:
            global_config = yaml.safe_load(f)
            GLOBAL_STANDARD_KEYS = global_config.get("global_standard_keys", {})
            DEFAULT_TITLE_COMPONENTS = global_config.get("default_title_components", {})
    else:
        print(f"警告：配置文件不存在: {GLOBAL_MAPPINGS}")
except Exception as e:
    print(f"警告：无法加载全局映射配置: {e}")
from .sites.ssd import SSDSpecialExtractor
from .sites.hhanclub import HHCLUBSpecialExtractor
from .sites.keepfrds import KEEPFRDSSpecialExtractor
from .sites.chdbits import CHDBitsSpecialExtractor
from .sites.hdsky import HDSkySpecialExtractor
from .sites.pterclub import PTerClubSpecialExtractor


class Extractor:
    """Main extractor class that orchestrates the extraction process"""

    def __init__(self):
        self.special_extractors = {
            "人人": AudiencesSpecialExtractor,
            "不可说": SSDSpecialExtractor,
            "憨憨": HHCLUBSpecialExtractor,
            "月月": KEEPFRDSSpecialExtractor,
            "彩虹岛": CHDBitsSpecialExtractor,
            "天空": HDSkySpecialExtractor,
            "猫站": PTerClubSpecialExtractor,
        }

    def extract(
        self,
        soup: BeautifulSoup,
        site_name: str,
        base_url: str,
        cookie: str,
        torrent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
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
            extractor = extractor_class(soup, base_url, cookie, torrent_id)
            extracted_data = extractor.extract_all(torrent_id)

            # Check if the extractor returned an error for this special site
            if isinstance(extracted_data, dict) and extracted_data.get("error") == True:
                # Return the error as-is so it propagates up to the calling code
                return extracted_data

            # Apply content filtering to special extractor results
            extracted_data = self._apply_content_filtering(extracted_data)
        else:
            # Use public extractor for general sites
            extracted_data = self._extract_with_public_extractor(soup)

        return extracted_data

    def _is_unwanted_content(self, text: str) -> bool:
        """
        检查文本是否包含不需要的内容模式（使用配置文件中的规则）

        Args:
            text: 要检查的文本

        Returns:
            如果文本包含不需要的模式则返回True
        """
        content_filter = get_content_filter()
        return content_filter.is_unwanted_pattern(text)

    def _clean_subtitle(self, subtitle: str) -> str:
        """
        清理副标题，移除制作组信息和不需要的内容

        Args:
            subtitle: 原始副标题

        Returns:
            清理后的副标题
        """
        content_filter = get_content_filter()
        return content_filter.clean_subtitle(subtitle)

    def _apply_content_filtering(self, extracted_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply content filtering to extracted data from special extractors

        Args:
            extracted_data: Data extracted from special extractors

        Returns:
            Filtered data with unwanted content removed
        """
        content_filter = get_content_filter()

        # Filter subtitle if it exists
        if extracted_data.get("subtitle"):
            extracted_data["subtitle"] = content_filter.clean_subtitle(extracted_data["subtitle"])

        # Filter intro content if it exists
        if extracted_data.get("intro"):
            intro = extracted_data["intro"]

            # Process statement section for ARDTU declarations and technical parameters
            if intro.get("statement"):
                result = content_filter.filter_quotes_in_statement(intro["statement"])
                intro["statement"] = result["filtered_statement"]
                intro["removed_ardtudeclarations"] = result["removed_declarations"]

        return extracted_data

    def _extract_with_public_extractor(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """
        Extract data using the public/common extractor

        Args:
            soup: BeautifulSoup object of the torrent page

        Returns:
            Dict with extracted data in standardized format
        """
        # [新增] 图片链接验证辅助函数
        from utils import (
            extract_origin_from_description,
            check_intro_completeness,
            upload_data_movie_info,
            is_image_url_valid_robust,
            extract_audio_codec_from_mediainfo,
        )

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
                "douban_link": "",
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
                "产地": "",
            },
        }

        # Extract title from h1#top
        h1_top = soup.select_one("h1#top")
        if h1_top:
            title = list(h1_top.stripped_strings)[0] if h1_top.stripped_strings else ""
            # Normalize title (replace dots with spaces, but preserve decimal points and codec formats)
            title = re.sub(r"(?<!\d)(?<!H)(?<!x)\.|\.(?!\d\b)(?!264)(?!265)", " ", title)
            title = re.sub(r"\s+", " ", title).strip()
            extracted_data["title"] = title

        # Extract subtitle
        subtitle_td = soup.find("td", string=re.compile(r"\s*副标题\s*"))
        if subtitle_td and subtitle_td.find_next_sibling("td"):
            subtitle = subtitle_td.find_next_sibling("td").get_text(strip=True)
            # Clean subtitle from group information using both hardcoded rules and config
            subtitle = self._clean_subtitle(subtitle)
            extracted_data["subtitle"] = subtitle

        # Extract description information
        descr_container = soup.select_one("div#kdescr")
        if descr_container:
            # --- [增强] 鲁棒的IMDb和豆瓣链接提取 ---
            imdb_link = ""
            douban_link = ""

            # 优先级 1: 查找专用的 div#kimdb 容器
            kimdb_div = soup.select_one("div#kimdb a[href*='imdb.com/title/tt']")
            if kimdb_div and kimdb_div.get("href"):
                imdb_link = normalize_imdb_link(kimdb_div.get("href"))

            # 优先级 2 (后备): 在主简介容器(div#kdescr)的文本中搜索
            descr_text = descr_container.get_text()
            # 如果还没找到 IMDb 链接, 则在简介中搜索
            if not imdb_link:
                if imdb_match := re.search(r"(https?://www\.imdb\.com/title/tt\d+)", descr_text):
                    imdb_link = imdb_match.group(1)

            # 在简介中搜索豆瓣链接
            if not douban_link:
                if douban_match := re.search(
                    r"(https?://movie\.douban\.com/subject/\d+)", descr_text
                ):
                    douban_link = douban_match.group(1)

            # 优先级 3 (全局后备): 如果链接仍然缺失, 则搜索整个页面的文本
            if not imdb_link or not douban_link:
                page_text = soup.get_text()
                if not imdb_link:
                    if imdb_match := re.search(
                        r"(https?://www\.imdb\.com/title/tt\d+)", page_text
                    ):
                        imdb_link = imdb_match.group(1)
                if not douban_link:
                    if douban_match := re.search(
                        r"(https?://movie\.douban\.com/subject/\d+)", page_text
                    ):
                        douban_link = douban_match.group(1)

            # --- [新方案] 使用远程 API 服务互补缺失的 IMDb/豆瓣/TMDb 链接 ---
            # 使用工具函数处理不完整的链接
            tmdb_link = ""  # 初始化 tmdb_link
            imdb_link, douban_link, tmdb_link, _ = handle_incomplete_links(imdb_link, douban_link, tmdb_link, subtitle)

            extracted_data["intro"]["imdb_link"] = imdb_link
            extracted_data["intro"]["douban_link"] = douban_link
            extracted_data["intro"]["tmdb_link"] = tmdb_link

            # Process description content to extract quotes, images, and body text
            descr_html_string = str(descr_container)
            corrected_descr_html = re.sub(
                r"</?br\s*/?>", "<br/>", descr_html_string, flags=re.IGNORECASE
            )
            corrected_descr_html = re.sub(r"(<img[^>]*[^/])>", r"\1 />", corrected_descr_html)

            try:
                from bs4 import BeautifulSoup as BS

                descr_container_soup = BS(corrected_descr_html, "lxml")
            except ImportError:
                descr_container_soup = BS(corrected_descr_html, "html.parser")

            bbcode = self._html_to_bbcode(descr_container_soup)

            # Clean nested quotes
            original_bbcode = bbcode
            while True:
                bbcode = re.sub(r"\[quote\]\s*\[quote\]", "[quote]", bbcode, flags=re.IGNORECASE)
                bbcode = re.sub(
                    r"\[/quote\]\s*\[/quote\]", "[/quote]", bbcode, flags=re.IGNORECASE
                )
                if bbcode == original_bbcode:
                    break
                original_bbcode = bbcode

        # Extract images - 同时处理[img]和[url]格式的图片链接
        images = re.findall(r"\[img\].*?\[/img\]", bbcode, re.IGNORECASE)

        # [新增] 提取[url=图片链接][/url]格式的图片并转换为[img]格式
        url_images = re.findall(
            r"\[url=([^\]]*\.(?:jpg|jpeg|png|gif|bmp|webp)(?:[^\]]*))\]\s*\[/url\]",
            bbcode,
            re.IGNORECASE,
        )
        print(f"[调试extractor] 提取到的[img]格式图片数量: {len(images)}")
        print(f"[调试extractor] 提取到的[url]格式图片数量: {len(url_images)}")
        for url_img in url_images:
            images.append(f"[img]{url_img}[/img]")
            print(f"[调试extractor] 添加转换后的图片: {url_img[:80]}")

        # [新增] 从配置文件读取并过滤掉指定的不需要的图片URL
        unwanted_image_urls = get_unwanted_image_urls()

        if unwanted_image_urls:
            filtered_images = []
            for img_tag in images:
                # 从[img]标签中提取URL
                url_match = re.search(r"\[img\](.*?)\[/img\]", img_tag, re.IGNORECASE)
                if url_match:
                    img_url = url_match.group(1)
                    # 检查是否在过滤列表中
                    if img_url not in unwanted_image_urls:
                        filtered_images.append(img_tag)
                    else:
                        logging.info(f"过滤掉不需要的图片: {img_url}")
                        print(f"[过滤] 移除图片: {img_url}")
                else:
                    # 如果无法提取URL，保留原图片标签
                    filtered_images.append(img_tag)

            images = filtered_images
            print(f"[调试extractor] 过滤后剩余图片数量: {len(images)}")
        else:
            print(f"[调试extractor] 未配置图片过滤列表，跳过过滤")

        # [新增] 应用BBCode清理函数到bbcode，移除[url]格式的图片和其他需要清理的标签
        from utils import process_bbcode_images_and_cleanup

        bbcode = process_bbcode_images_and_cleanup(bbcode)

        # 注意：海报验证和转存逻辑已移至 _parse_format_content 函数中统一处理
        # 视频截图的验证将在 migrator.py 的 prepare_review_data 中单独进行

        if descr_container:
            # Extract quotes before and after poster
            # [修复] 改进判断逻辑：即使没有海报，也要正确区分感谢声明和正文内容
            poster_index = bbcode.find(images[0]) if (images and images[0]) else -1
            quotes_before_poster = []
            quotes_after_poster = []

            for match in re.finditer(r"\[quote\].*?\[/quote\]", bbcode, re.DOTALL):
                quote_content = match.group(0)
                quote_start = match.start()

                # [修复] 当没有海报时，通过内容特征判断是否为感谢声明
                if poster_index != -1:
                    # 有海报：使用位置判断
                    if quote_start < poster_index:
                        quotes_before_poster.append(quote_content)
                    else:
                        quotes_after_poster.append(quote_content)
                else:
                    # 无海报：通过关键词判断是否为感谢声明
                    # 感谢声明通常包含这些特征
                    is_acknowledgment = (
                        "官组" in quote_content
                        or "感谢" in quote_content
                        or "原制作者" in quote_content
                        or "FRDS" in quote_content
                        or "FraMeSToR" in quote_content
                        or "CHD" in quote_content
                        or "字幕组" in quote_content
                        or len(quote_content) < 200  # 短quote更可能是声明
                    )

                    if is_acknowledgment:
                        quotes_before_poster.append(quote_content)
                    else:
                        quotes_after_poster.append(quote_content)

            # 获取内容过滤器实例
            content_filter = get_content_filter()

            # Process quotes
            final_statement_quotes = []
            ardtu_declarations = []
            mediainfo_from_quote = ""
            found_mediainfo_in_quote = False
            quotes_for_body = []

            # Process quotes before poster
            for quote in quotes_before_poster:
                is_mediainfo = "General" in quote and "Video" in quote and "Audio" in quote
                is_bdinfo = "DISC INFO" in quote and "PLAYLIST REPORT" in quote
                is_release_info_style = ".Release.Info" in quote and "ENCODER" in quote

                if not found_mediainfo_in_quote and (
                    is_mediainfo or is_bdinfo or is_release_info_style
                ):
                    mediainfo_from_quote = re.sub(
                        r"\[/?quote\]", "", quote, flags=re.IGNORECASE
                    ).strip()
                    found_mediainfo_in_quote = True
                    # MediaInfo/BDInfo是技术信息，不应该被过滤掉，直接跳过处理
                    continue

                # [修复] 使用配置文件中的 unwanted_patterns 检查 quote 是否包含不需要的内容
                quote_text_without_tags = re.sub(
                    r"\[/?quote\]", "", quote, flags=re.IGNORECASE
                ).strip()
                if self._is_unwanted_content(quote_text_without_tags):
                    logging.info(
                        f"根据配置文件过滤掉不需要的声明: {quote_text_without_tags[:50]}..."
                    )
                    ardtu_declarations.append(quote_text_without_tags)
                    continue

                is_ardtutool_auto_publish = "ARDTU工具自动发布" in quote
                is_disclaimer = "郑重声明：" in quote
                is_csweb_disclaimer = "财神CSWEB提供的所有资源均是在网上搜集且由用户上传" in quote
                is_by_ardtu_group_info = "By ARDTU" in quote and "官组作品" in quote
                has_atu_tool_signature = "| A | By ATU" in quote

                if (
                    is_ardtutool_auto_publish
                    or is_disclaimer
                    or is_csweb_disclaimer
                    or has_atu_tool_signature
                ):
                    clean_content = re.sub(r"\[\/?quote\]", "", quote).strip()
                    ardtu_declarations.append(clean_content)
                elif is_by_ardtu_group_info:
                    filtered_quote = re.sub(r"\s*By ARDTU\s*", "", quote)
                    final_statement_quotes.append(filtered_quote)
                elif "ARDTU" in quote:
                    clean_content = re.sub(r"\[\/?quote\]", "", quote).strip()
                    ardtu_declarations.append(clean_content)
                elif content_filter.is_technical_params_quote(quote):
                    # 将技术参数quote添加到ARDTU声明中，这样它们会被过滤掉不会出现在正文中
                    clean_content = re.sub(r"\[\/?quote\]", "", quote).strip()
                    ardtu_declarations.append(clean_content)
                else:
                    final_statement_quotes.append(quote)

            # Helper function to identify movie description quotes
            def is_movie_intro_quote(quote_text):
                # 定义正则模式列表：用 [◎❁] 兼容两种符号，保留原有文字/空格格式
                regex_patterns = [
                    r"[◎❁]片　　名",
                    r"[◎❁]译　　名",
                    r"[◎❁]年　　代",
                    r"[◎❁]产　　地",
                    r"[◎❁]类　　别",
                    r"[◎❁]语　　言",
                    r"[◎❁]导　　演",
                    r"[◎❁]主　　演",
                    r"[◎❁]简　　介",
                    r"[◎❁]演　　员",
                    r"[◎❁]演  员",
                    r"[◎❁]IMDB评分",
                    r"[◎❁]IMDb评分",
                    r"[◎❁]获奖情况",
                    r"制片国家/地区",  # 最后一个无符号，直接作为正则串
                ]
                # 遍历所有正则模式，只要有一个匹配成功就返回 True
                return any(re.search(pattern, quote_text) for pattern in regex_patterns)

            # Process quotes after poster
            for quote in quotes_after_poster:
                # 检查是否为mediainfo/bdinfo/技术参数的quote
                is_mediainfo_after = "General" in quote and "Video" in quote and "Audio" in quote
                is_bdinfo_after = "DISC INFO" in quote and "PLAYLIST REPORT" in quote
                is_release_info_after = ".Release.Info" in quote and "ENCODER" in quote
                is_technical_after = content_filter.is_technical_params_quote(quote)
                is_unwanted_pattern = content_filter.is_unwanted_pattern(quote)

                if is_mediainfo_after or is_bdinfo_after or is_release_info_after:
                    # MediaInfo/BDInfo是技术信息，不应该被过滤掉，需要提取
                    if not found_mediainfo_in_quote:
                        mediainfo_from_quote = re.sub(
                            r"\[/?quote\]", "", quote, flags=re.IGNORECASE
                        ).strip()
                        found_mediainfo_in_quote = True
                    continue
                elif is_technical_after or is_unwanted_pattern:
                    # 技术参数quote或不需要的模式被过滤掉
                    clean_content = re.sub(r"\[\/?quote\]", "", quote).strip()
                    ardtu_declarations.append(clean_content)
                elif is_movie_intro_quote(quote):
                    # 如果quote看起来像电影简介的一部分，则将其添加到正文
                    quotes_for_body.append(quote)
                else:
                    # 海报后的其他quote应该添加到正文后面，而不是声明区域
                    quotes_for_body.append(quote)

            # Extract body content (先移除quote和图片标签)
            body = (
                re.sub(r"\[quote\].*?\[/quote\]|\[img\].*?\[/img\]", "", bbcode, flags=re.DOTALL)
                .replace("\r", "")
                .strip()
            )

            # [新增] 在构建body后，应用BBCode清理函数处理残留的空标签和列表标记
            from utils import process_bbcode_images_and_cleanup

            body = process_bbcode_images_and_cleanup(body)

            # [新增] 在BBCode层面过滤对比说明（包含BBCode标签的情况）
            # 移除包含Comparison和Source/Encode的行（不管是否有[b][size]等标签包裹）
            lines = body.split("\n")
            filtered_lines = []
            skip_next_line = False

            for i, line in enumerate(lines):
                if skip_next_line:
                    skip_next_line = False
                    continue

                # 去除BBCode标签后的纯文本用于检测
                line_without_bbcode = re.sub(r"\[/?[^\]]+\]", "", line)
                line_upper = line_without_bbcode.upper().strip()

                # 检测1: Comparison行
                if "COMPARISON" in line_upper and ("RIGHT" in line_upper or "CLICK" in line_upper):
                    logging.info(f"过滤掉Comparison行: {line[:80]}...")
                    # 检查下一行是否是Source/Encode行
                    if i + 1 < len(lines):
                        next_line = lines[i + 1]
                        next_line_without_bbcode = re.sub(r"\[/?[^\]]+\]", "", next_line)
                        if (
                            "SOURCE" in next_line_without_bbcode.upper()
                            and "ENCODE" in next_line_without_bbcode.upper()
                            and next_line.count("_") >= 10
                        ):
                            skip_next_line = True
                    continue

                # 检测2: Source___Encode行（单独出现）
                if (
                    line_upper.startswith("SOURCE")
                    and line_upper.endswith("ENCODE")
                    and line.count("_") >= 10
                ):
                    logging.info(f"过滤掉Source/Encode行: {line[:80]}...")
                    continue

                # 检测3: 同一行包含Comparison和Source/Encode的情况
                if (
                    "COMPARISON" in line_upper
                    and "SOURCE" in line_upper
                    and "ENCODE" in line_upper
                    and line.count("_") >= 5
                ):
                    logging.info(f"过滤掉完整对比说明行: {line[:80]}...")
                    continue

                filtered_lines.append(line)

            body = "\n".join(filtered_lines)

            # [合并] 统一检查简介完整性和缺失信息（集数/IMDb/豆瓣链接）
            from utils import enhance_description_if_needed

            logging.info("开始简介完整性和缺失信息检测...")

            enhanced_body, enhanced_poster, enhanced_imdb, description_changed = (
                enhance_description_if_needed(
                    body,
                    extracted_data["intro"].get("imdb_link", ""),
                    extracted_data["intro"].get("douban_link", ""),
                    subtitle,
                    images[0] if images else "",
                )
            )

            if description_changed:
                body = enhanced_body
                if enhanced_imdb:
                    extracted_data["intro"]["imdb_link"] = enhanced_imdb
                    logging.info(f"✅ 简介已增强，更新了IMDb链接: {enhanced_imdb}")

            # Add quotes after poster to body (在完整性检测和可能的重新获取之后)
            if quotes_for_body:
                body = body + "\n\n" + "\n".join(quotes_for_body)

            # [新逻辑] 清理简介中残留的独立关键词行和对比说明行
            logging.info("清理简介中残留的独立关键词行 (Mediainfo, Screenshot, etc.)...")
            words_to_remove = {"mediainfo", "screenshot", "source", "encode"}
            lines = body.split("\n")
            cleaned_lines = []
            for line in lines:
                # 检查是否为独立关键词行
                if line.strip().lower() in words_to_remove:
                    continue

                # [新增] 检查是否为对比截图说明行
                line_upper = line.upper()
                line_stripped = line.strip()

                # 条件1: 包含 Comparison 和 Source/Encode 且有下划线分隔
                if (
                    "COMPARISON" in line_upper
                    and "SOURCE" in line_upper
                    and "ENCODE" in line_upper
                    and ("___" in line or "____" in line or "_______" in line)
                ):
                    logging.info(f"过滤掉对比说明行(带下划线): {line[:50]}...")
                    continue

                # 条件2: 只有 Source 和 Encode 且中间有大量下划线的单行
                # 例如: "Source________________________Encode"
                if (
                    line_stripped.upper().startswith("SOURCE")
                    and line_stripped.upper().endswith("ENCODE")
                    and line.count("_") >= 10
                ):  # 至少10个下划线
                    logging.info(f"过滤掉对比说明行(纯下划线): {line[:50]}...")
                    continue

                # 条件3: 单独的 "Comparison" 行（通常出现在对比说明前）
                if line_stripped.lower().startswith("comparison") and len(line_stripped) < 100:
                    # 检查是否包含典型的对比说明文本
                    if "right" in line_stripped.lower() or "click" in line_stripped.lower():
                        logging.info(f"过滤掉对比说明行(Comparison): {line[:50]}...")
                        continue

                cleaned_lines.append(line)

            body = "\n".join(cleaned_lines)

            # Format statement string
            statement_string = "\n".join(final_statement_quotes)
            if statement_string:
                statement_string = re.sub(r"(\r?\n){3,}", r"\n\n", statement_string).strip()

            extracted_data["intro"]["statement"] = statement_string
            # 直接使用提取到的第一张图片作为海报（验证和转存在 _parse_format_content 中处理）
            extracted_data["intro"]["poster"] = (
                enhanced_poster if enhanced_poster else (images[0] if images else "")
            )
            extracted_data["intro"]["body"] = re.sub(r"\n{2,}", "\n", body)
            extracted_data["intro"]["screenshots"] = (
                "\n".join(images[1:]) if len(images) > 1 else ""
            )
            extracted_data["intro"]["removed_ardtudeclarations"] = ardtu_declarations

        # Extract MediaInfo
        mediainfo_pre = soup.select_one("div.spoiler-content pre, div.nexus-media-info-raw > pre")
        mediainfo_text = mediainfo_pre.get_text(strip=True) if mediainfo_pre else ""

        if not mediainfo_text and mediainfo_from_quote:
            mediainfo_text = mediainfo_from_quote

        # Format mediainfo string
        if mediainfo_text:
            mediainfo_text = re.sub(r"(\r?\n){2,}", r"\n", mediainfo_text).strip()

        extracted_data["mediainfo"] = mediainfo_text

        # Extract basic info and tags
        basic_info_td = soup.find("td", string="基本信息")
        basic_info_dict = {}
        if basic_info_td and basic_info_td.find_next_sibling("td"):
            strings = list(basic_info_td.find_next_sibling("td").stripped_strings)
            basic_info_dict = {
                s.replace(":", "").strip(): strings[i + 1]
                for i, s in enumerate(strings)
                if ":" in s and i + 1 < len(strings)
            }

        tags_td = soup.find("td", string=re.compile(r"^\s*(?:标签|Tags)\s*$", re.IGNORECASE))

        tags = []
        if tags_td and tags_td.find_next_sibling("td"):
            # 优先查找 span 标签 (OurBits 使用 <span class="tag ...">)
            tag_spans = tags_td.find_next_sibling("td").find_all("span")
            if tag_spans:
                tags = [s.get_text(strip=True) for s in tag_spans]
            else:
                # 如果没有 span，尝试直接获取文本并按逗号或空格分割 (作为后备方案)
                tags_text = tags_td.find_next_sibling("td").get_text(strip=True)
                if tags_text:
                    # 替换常见的全角分隔符
                    tags_text = tags_text.replace("，", ",").replace("、", ",")
                    tags = [t.strip() for t in re.split(r"[,/ ]+", tags_text) if t.strip()]

        # 过滤掉指定的标签
        filtered_tags = []
        unwanted_tags = ["官方", "官种", "首发", "自购", "自抓", "应求"]
        for tag in tags:
            if tag not in unwanted_tags:
                filtered_tags.append(tag)

        # 添加去重处理，保持顺序
        if filtered_tags:
            filtered_tags = list(dict.fromkeys(filtered_tags))

        tags = filtered_tags

        type_text = basic_info_dict.get("类型", "")
        type_match = re.search(r"[\(（](.*?)[\)）]", type_text)

        extracted_data["source_params"]["类型"] = (
            type_match.group(1) if type_match else type_text.split("/")[-1]
        )
        extracted_data["source_params"]["媒介"] = basic_info_dict.get("媒介")
        # 视频编码：优先获取"视频编码"，如果没有则获取"编码"
        extracted_data["source_params"]["视频编码"] = basic_info_dict.get(
            "视频编码"
        ) or basic_info_dict.get("编码")
        extracted_data["source_params"]["音频编码"] = basic_info_dict.get("音频编码")
        # 如果页面上没有音频编码，则尝试从mediainfo中提取
        if not extracted_data["source_params"]["音频编码"] and extracted_data.get("mediainfo"):
            logging.info("页面未提供音频编码，尝试从MediaInfo中提取...")
            audio_codec_from_mediainfo = extract_audio_codec_from_mediainfo(
                extracted_data["mediainfo"]
            )
            if audio_codec_from_mediainfo:
                extracted_data["source_params"]["音频编码"] = audio_codec_from_mediainfo
                logging.info(f"成功从MediaInfo中提取到音频编码: {audio_codec_from_mediainfo}")

        extracted_data["source_params"]["分辨率"] = basic_info_dict.get("分辨率")
        extracted_data["source_params"]["制作组"] = basic_info_dict.get("制作组")
        extracted_data["source_params"]["标签"] = tags

        # Extract origin information
        from utils import (
            extract_origin_from_description,
            check_intro_completeness,
            upload_data_movie_info,
        )

        full_description_text = (
            f"{extracted_data['intro']['statement']}\n{extracted_data['intro']['body']}"
        )
        origin_info = extract_origin_from_description(full_description_text)

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
        content = []
        if not hasattr(tag, "contents"):
            return ""
        for child in tag.contents:
            if isinstance(child, str):
                content.append(child.replace("\xa0", " "))
            elif child.name == "br":
                content.append("\n")
            elif child.name == "fieldset":
                content.append(f"[quote]{self._html_to_bbcode(child).strip()}[/quote]")
            elif child.name == "legend":
                continue
            elif child.name == "b":
                content.append(f"[b]{self._html_to_bbcode(child)}[/b]")
            elif child.name == "img" and child.get("src"):
                content.append(f"[img]{child['src']}[/img]")
            elif child.name == "a" and child.get("href"):
                content.append(f"[url={child['href']}]{self._html_to_bbcode(child)}[/url]")
            elif (
                child.name == "span"
                and child.get("style")
                and (match := re.search(r"color:\s*([^;]+)", child["style"]))
            ):
                content.append(
                    f"[color={match.group(1).strip()}]{self._html_to_bbcode(child)}[/color]"
                )
            elif child.name == "font" and child.get("size"):
                content.append(f"[size={child['size']}]{self._html_to_bbcode(child)}[/size]")
            else:
                content.append(self._html_to_bbcode(child))
        return "".join(content)


class ParameterMapper:
    """
    [修正] Handles mapping of extracted parameters to standardized formats,
    with corrected logic for global and site-specific mappings.
    """

    def __init__(self):
        pass

    def _deduplicate_hdr_tags(self, tags_list):
        """
        HDR标签去重：当tag.HDR和tag.HDR10+同时存在时，只保留tag.HDR10+
        """
        if "tag.HDR" in tags_list and "tag.HDR10+" in tags_list:
            tags_list.remove("tag.HDR")
            print(f"[HDR标签去重] 移除tag.HDR，保留tag.HDR10+")
        return tags_list

    def _map_tags(self, raw_tags, site_name: str):
        """
        将原始标签映射到站点特定格式
        """
        if not raw_tags:
            return []

        # 首先尝试使用站点特定配置
        site_config = self.load_site_config(site_name)
        # [修复] 应该使用 source_parsers.standard_keys.tag 而不是 mappings.tag
        site_mappings = (
            site_config.get("source_parsers", {}).get("standard_keys", {}).get("tag", {})
        )

        # 确保我们总是有全局映射作为后备
        global_tag_mappings = GLOBAL_STANDARD_KEYS.get("tag", {})

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
                    if (
                        source_text.lower() in raw_tag.lower()
                        or raw_tag.lower() in source_text.lower()
                    ) and standard_key is not None:
                        mapped_tag = standard_key
                        break

            # 如果站点特定映射没有找到，尝试全局映射
            if not mapped_tag:
                # 全局映射的精确匹配
                for source_text, standard_key in global_tag_mappings.items():
                    if source_text.lower() == raw_tag.lower() and standard_key is not None:
                        mapped_tag = standard_key
                        break

                # 全局映射的部分匹配
                if not mapped_tag:
                    for source_text, standard_key in global_tag_mappings.items():
                        if (
                            source_text.lower() in raw_tag.lower()
                            or raw_tag.lower() in source_text.lower()
                        ) and standard_key is not None:
                            mapped_tag = standard_key
                            break

            # 如果找到映射，使用映射值；否则过滤掉
            if mapped_tag:
                mapped_tags.append(mapped_tag)
            else:
                # 记录未映射的标签，但不会添加到最终列表中
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
                with open(config_path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            else:
                return {}
        except Exception:
            return {}

    def map_parameters(
        self, site_name: str, site: str, extracted_params: Dict[str, Any]
    ) -> Dict[str, Any]:
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
            original_value_str = value_str  # 保存原始值，用于后续处理

            # 处理合作制作组：如果包含@符号，优先使用@后面的制作组名称
            if "@" in value_str:
                # 分割字符串，@后面的部分作为主要制作组
                parts = value_str.split("@")
                if len(parts) >= 2 and parts[1].strip():
                    # 使用@后面的制作组名称进行映射
                    value_str = parts[1].strip()
                    logging.info(
                        f"检测到合作制作组 '{raw_value}'，使用 '@' 后的制作组 '{value_str}' 进行映射"
                    )

            # 媒介特殊预处理：确保 BluRay Remux 能正确映射
            if param_key == "medium":
                # 将所有 UHD BluRay Remux, BluRay Remux, Blu-ray Remux 映射为 BD Remux
                if re.match(r"^(UHD\s+)?Blu-?ray\s*Remux$", value_str, re.IGNORECASE):
                    value_str = "BD Remux"
                    print(
                        f"[调试-标题解析参数] 媒介预处理: '{original_value_str}' -> '{value_str}'"
                    )

            # [修正] 合并全局映射和站点映射，统一进行长匹配优先查找
            # 获取映射表
            global_mappings = GLOBAL_STANDARD_KEYS.get(param_key, {})
            site_mappings = site_standard_keys.get(param_key, {})

            # 合并映射：站点映射优先于全局映射（如果源文本相同）
            # 使用 merged_mappings 统一处理
            merged_mappings = global_mappings.copy()
            if site_mappings:
                merged_mappings.update(site_mappings)

            # 1. 精确匹配优先
            for source_text, standard_key in merged_mappings.items():
                if source_text.lower() == value_str.lower():
                    print(
                        f"[调试-标题解析参数] {param_key} 精确匹配: '{value_str}' -> '{standard_key}'"
                    )
                    return standard_key

            # 2. 部分匹配：按键长度降序排列，确保匹配最长的关键词
            # 例如：确保 '音乐视频' (len=4) 优先于 '音乐' (len=2) 被匹配
            sorted_mappings = sorted(
                merged_mappings.items(),
                key=lambda x: len(x[0]),
                reverse=True,
            )

            # audio_codec 特殊处理：允许多词条在原始值中按顺序“隔空匹配”
            # 例如 TrueHD 7.1 Atmos -> TrueHD Atmos
            if param_key == "audio_codec":
                for source_text, standard_key in sorted_mappings:
                    if not standard_key:
                        continue
                    tokens = [t for t in source_text.split() if t]
                    if len(tokens) < 2:
                        continue
                    pattern = ".*".join(re.escape(token) for token in tokens)
                    if re.search(pattern, value_str, re.IGNORECASE):
                        print(
                            f"[调试-标题解析参数] {param_key} 组合匹配: "
                            f"'{value_str}' -> '{source_text}' -> '{standard_key}'"
                        )
                        return standard_key

            for source_text, standard_key in sorted_mappings:
                # 只有当 standard_key 存在时才匹配（避免配置为 null 的项）
                if standard_key and source_text.lower() in value_str.lower():
                    print(
                        f"[调试-标题解析参数] {param_key} 部分匹配: '{value_str}' 包含 '{source_text}' -> '{standard_key}'"
                    )
                    return standard_key

            # 如果都找不到，返回一个默认值或处理过的原始值
            if param_key == "team":
                # [修改] 无论原始值是什么，只要无法映射就返回 team.other
                print(f"[调试-标题解析参数] {param_key} 无法映射，返回 team.other")
                return "team.other"

            print(f"[调试-标题解析参数] {param_key} 无法映射，返回原始值: '{value_str}'")
            return value_str  # 其他参数返回原始值

        # 1. 分别从 source_params 和 title_components 提取并标准化
        source_standard_values = {}
        source_params_config = source_parsers.get("source_params", {})
        for param_key, config in source_params_config.items():
            raw_value = source_params.get(config.get("source_key"))
            if raw_value:
                source_standard_values[param_key] = get_standard_key_for_value(
                    raw_value, param_key
                )

        print(f"[调试-ParameterMapper] 源站点标准化参数: {source_standard_values}")

        title_standard_values = {}
        # 使用默认的 title_components 配置，如果站点配置中没有定义
        title_components_config = source_parsers.get("title_components", DEFAULT_TITLE_COMPONENTS)
        title_params = {item["key"]: item["value"] for item in title_components}
        print(f"[调试-ParameterMapper] 标题组件原始参数: {title_params}")

        for param_key, config in title_components_config.items():
            raw_value = title_params.get(config.get("source_key"))
            if raw_value:
                title_standard_values[param_key] = get_standard_key_for_value(raw_value, param_key)

        print(f"[调试-ParameterMapper] 标题拆解标准化参数: {title_standard_values}")

        # 2. 合并决策 - 优先使用标题拆解参数
        final_standardized_params = title_standard_values.copy()
        print(f"[调试-ParameterMapper] 初始最终参数（来自标题）: {final_standardized_params}")

        for key, source_value in source_standard_values.items():
            if not source_value:
                continue

            # [修改] 音频编码也优先使用标题拆解参数，不再进行择优比较
            if key == "audio_codec":
                title_value = final_standardized_params.get(key)
                print(
                    f"[调试-ParameterMapper] 音频编码优先使用标题: {title_value} (忽略源站点: {source_value})"
                )
                continue

            # 其他参数：如果标题中没有，才从源站点补充
            if key not in final_standardized_params:
                final_standardized_params[key] = source_value
                print(f"[调试-ParameterMapper] 从源站点补充参数 {key}: {source_value}")
            else:
                print(f"[调试-ParameterMapper] 跳过源站点参数 {key}（标题中已存在）")

        print(f"[调试-ParameterMapper] 最终标准化参数: {final_standardized_params}")

        # 如果source参数不存在，尝试从原始参数中获取
        # 注意：现在统一使用source映射，不再有单独的processing映射
        if "source" not in final_standardized_params:
            # 尝试从原始参数中获取（兼容使用"区域"等字段的站点）
            source_value = source_params.get("产地") or source_params.get("区域")
            if source_value:
                final_standardized_params["source"] = get_standard_key_for_value(
                    source_value, "source"
                )

        # 处理标签映射 - 使用站点特定的标签映射
        final_standardized_params["tags"] = self._map_tags(
            source_params.get("标签", []), site_name
        )

        # [新增] 从简介和副标题中提取标签和进行类型修正
        from utils import (
            extract_tags_from_description,
            check_animation_type_from_description,
            extract_tags_from_subtitle,
        )

        intro_statement = extracted_params.get("intro", {}).get("statement", "")
        intro_body = extracted_params.get("intro", {}).get("body", "")
        full_description_text = f"{intro_statement}\n{intro_body}"

        # 1. 从副标题中提取标签（如特效）
        subtitle = extracted_params.get("subtitle", "")
        subtitle_tags = extract_tags_from_subtitle(subtitle)
        if subtitle_tags:
            # 将提取到的标签添加到现有标签列表中
            existing_tags = set(final_standardized_params.get("tags", []))
            existing_tags.update(subtitle_tags)
            final_standardized_params["tags"] = list(existing_tags)
            logging.info(f"从副标题中补充标签: {subtitle_tags}")

        # 2. 从简介类别中提取标签（如喜剧、动画等）
        description_tags = extract_tags_from_description(full_description_text)
        if description_tags:
            # 将提取到的标签添加到现有标签列表中，使用集合去重
            existing_tags = set(final_standardized_params.get("tags", []))
            existing_tags.update(description_tags)
            final_standardized_params["tags"] = list(existing_tags)
            logging.info(f"从简介中补充标签: {description_tags}")

        # 3. 检查是否需要修正类型为动漫
        if check_animation_type_from_description(full_description_text):
            current_type = final_standardized_params.get("type", "")
            logging.info(f"检测到类别中包含'动画'，当前标准类型: {current_type}")

            # 获取动漫的标准键
            anime_standard_key = None
            global_type_mappings = GLOBAL_STANDARD_KEYS.get("type", {})
            for source_text, standard_key in global_type_mappings.items():
                if source_text in ["动漫", "Anime"]:
                    anime_standard_key = standard_key
                    break

            if anime_standard_key:
                # 只要检测到动画，就修正为动漫
                final_standardized_params["type"] = anime_standard_key
                logging.info(f"类型已从'{current_type}'修正为'{anime_standard_key}'")
                print(
                    f"[*] 类型修正: {current_type} -> {anime_standard_key} (检测到简介类别包含'动画')"
                )
            else:
                logging.warning("未在全局映射中找到'动漫'的标准键，无法修正类型")

        # HDR标签去重处理
        if "tags" in final_standardized_params:
            deduplicated_tags = self._deduplicate_hdr_tags(final_standardized_params["tags"])
            final_standardized_params["tags"] = deduplicated_tags

        return final_standardized_params
