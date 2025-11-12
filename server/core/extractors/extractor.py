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
import re
import logging
import requests
import os
import urllib.parse

CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "configs")
from .sites.audiences import AudiencesSpecialExtractor

# 加载全局映射配置
GLOBAL_MAPPINGS = {}
DEFAULT_TITLE_COMPONENTS = {}
CONTENT_FILTERING_CONFIG = {}
try:
    global_mappings_path = os.path.join(CONFIG_DIR, "global_mappings.yaml")
    if os.path.exists(global_mappings_path):
        with open(global_mappings_path, 'r', encoding='utf-8') as f:
            global_config = yaml.safe_load(f)
            GLOBAL_MAPPINGS = global_config.get("global_standard_keys", {})
            DEFAULT_TITLE_COMPONENTS = global_config.get(
                "default_title_components", {})
            CONTENT_FILTERING_CONFIG = global_config.get(
                "content_filtering", {})
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

    def _is_unwanted_content(self, text: str) -> bool:
        """
        检查文本是否包含不需要的内容模式（使用配置文件中的规则）
        
        Args:
            text: 要检查的文本
            
        Returns:
            如果文本包含不需要的模式则返回True
        """
        if not CONTENT_FILTERING_CONFIG.get("enabled", False):
            return False

        unwanted_patterns = CONTENT_FILTERING_CONFIG.get(
            "unwanted_patterns", [])
        return any(pattern in text for pattern in unwanted_patterns)

    def _clean_subtitle(self, subtitle: str) -> str:
        """
        清理副标题，移除制作组信息和不需要的内容
        
        Args:
            subtitle: 原始副标题
            
        Returns:
            清理后的副标题
        """
        if not subtitle:
            return subtitle

        # 首先使用硬编码的规则（兼容性）
        subtitle = re.sub(r"\s*\|\s*[Aa][Bb]y\s+\w+.*$", "", subtitle)
        subtitle = re.sub(r"\s*\|\s*[Bb]y\s+\w+.*$", "", subtitle)
        subtitle = re.sub(r"\s*\|\s*[Aa]\s+\w+.*$", "", subtitle)
        subtitle = re.sub(r"\s*\|\s*[Aa]\s*\|.*$", "", subtitle)
        subtitle = re.sub(r"\s*\|\s*[Aa][Tt][Uu]\s*$", "", subtitle)
        subtitle = re.sub(r"\s*\|\s*[Dd][Tt][Uu]\s*$", "", subtitle)
        subtitle = re.sub(r"\s*\|\s*[Pp][Tt][Ee][Rr]\s*$", "", subtitle)

        # 然后使用配置文件中的规则
        # 对于副标题：删除匹配到的模式及其之后的所有内容
        if CONTENT_FILTERING_CONFIG.get("enabled", False):
            unwanted_patterns = CONTENT_FILTERING_CONFIG.get(
                "unwanted_patterns", [])

            for pattern in unwanted_patterns:
                if pattern in subtitle:
                    # 找到模式的位置，删除该模式及其之后的内容
                    pattern_index = subtitle.find(pattern)
                    if pattern_index != -1:
                        subtitle = subtitle[:pattern_index].strip()
                        # 如果删除后没有内容了，返回空字符串
                        if not subtitle:
                            return ""

        return subtitle.strip()

    def _extract_with_public_extractor(self,
                                       soup: BeautifulSoup) -> Dict[str, Any]:
        """
        Extract data using the public/common extractor

        Args:
            soup: BeautifulSoup object of the torrent page

        Returns:
            Dict with extracted data in standardized format
        """
        # [新增] 图片链接验证辅助函数
        from utils import extract_origin_from_description, check_intro_completeness, upload_data_movie_info
        from utils.image_validator import is_image_url_valid_robust
        from utils.media_helper import extract_audio_codec_from_mediainfo
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
            title = re.sub(r'(?<!\d)(?<!H)(?<!x)\.|\.(?!\d\b)(?!264)(?!265)',
                           ' ', title)
            title = re.sub(r'\s+', ' ', title).strip()
            extracted_data["title"] = title

        # Extract subtitle
        import re
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
            kimdb_div = soup.select_one(
                "div#kimdb a[href*='imdb.com/title/tt']")
            if kimdb_div and kimdb_div.get('href'):
                imdb_link = kimdb_div.get('href')

            # 优先级 2 (后备): 在主简介容器(div#kdescr)的文本中搜索
            descr_text = descr_container.get_text()
            # 如果还没找到 IMDb 链接, 则在简介中搜索
            if not imdb_link:
                if imdb_match := re.search(
                        r"(https?://www\.imdb\.com/title/tt\d+)", descr_text):
                    imdb_link = imdb_match.group(1)

            # 在简介中搜索豆瓣链接
            if not douban_link:
                if douban_match := re.search(
                        r"(https?://movie\.douban\.com/subject/\d+)",
                        descr_text):
                    douban_link = douban_match.group(1)

            # 优先级 3 (全局后备): 如果链接仍然缺失, 则搜索整个页面的文本
            if not imdb_link or not douban_link:
                page_text = soup.get_text()
                if not imdb_link:
                    if imdb_match := re.search(
                            r"(https?://www\.imdb\.com/title/tt\d+)",
                            page_text):
                        imdb_link = imdb_match.group(1)
                if not douban_link:
                    if douban_match := re.search(
                            r"(https?://movie\.douban\.com/subject/\d+)",
                            page_text):
                        douban_link = douban_match.group(1)

            # --- [新方案] 使用远程 API 服务互补缺失的 IMDb/豆瓣 链接 ---

            # [新增] Fallback: 如果两个链接都没有，尝试使用副标题进行名称搜索
            if not imdb_link and not douban_link:
                subtitle = extracted_data.get("subtitle", "")
                if subtitle:
                    # 提取第一个 / 或 | 之前的内容作为电影名
                    search_name = re.split(r'\s*[|/]\s*', subtitle,
                                           1)[0].strip()
                    if search_name:
                        logging.info(
                            f"未找到链接，尝试使用副标题 '{search_name}' 进行名称搜索...")
                        print(f"[*] 未找到链接，尝试使用副标题 '{search_name}' 进行名称搜索...")
                        try:
                            encoded_name = urllib.parse.quote_plus(search_name)
                            api_base_url = "https://ptn-douban.sqing33.dpdns.org/"
                            api_url = f"{api_base_url}?name={encoded_name}"

                            response = requests.get(api_url, timeout=10)
                            if response.status_code == 200:
                                data = response.json().get('data', [])
                                if data and data[0]:
                                    found_record = data[0]
                                    found_imdb_id = found_record.get('imdbid')
                                    found_douban_id = found_record.get(
                                        'doubanid')

                                    if found_imdb_id:
                                        imdb_link = f"https://www.imdb.com/title/{found_imdb_id}/"
                                        logging.info(
                                            f"✅ 成功通过名称搜索补充 IMDb 链接: {imdb_link}"
                                        )
                                        print(
                                            f"  [+] 成功通过名称搜索补充 IMDb 链接: {imdb_link}"
                                        )

                                    if found_douban_id:
                                        douban_link = f"https://movie.douban.com/subject/{found_douban_id}/"
                                        logging.info(
                                            f"✅ 成功通过名称搜索补充豆瓣链接: {douban_link}")
                                        print(
                                            f"  [+] 成功通过名称搜索补充豆瓣链接: {douban_link}"
                                        )
                            else:
                                logging.warning(
                                    f"名称搜索 API 查询失败, 状态码: {response.status_code}"
                                )
                                print(
                                    f"  [-] 名称搜索 API 查询失败, 状态码: {response.status_code}"
                                )

                        except requests.exceptions.RequestException as e:
                            logging.error(f"使用名称搜索 API 时发生网络错误: {e}")
                            print(f"  [!] 使用名称搜索 API 时发生网络错误: {e}")
                        except Exception as e:
                            logging.error(f"使用名称搜索时发生错误: {e}")
                            print(f"  [!] 使用名称搜索时发生错误: {e}")

            try:
                if (imdb_link and not douban_link) or (douban_link
                                                       and not imdb_link):
                    logging.info("检测到 IMDb/豆瓣 链接不完整，尝试使用远程 API 补充...")
                    print("检测到 IMDb/豆瓣 链接不完整，尝试使用远程 API 补充...")

                    api_base_url = "https://ptn-douban.sqing33.dpdns.org/"

                    if imdb_link and not douban_link:
                        if imdb_id_match := re.search(r'(tt\d+)', imdb_link):
                            imdb_id = imdb_id_match.group(1)
                            api_url = f"{api_base_url}?imdbid={imdb_id}"
                            logging.info(f"使用 IMDb ID 查询远程 API: {api_url}")
                            print(f"[*] 正在使用 IMDb ID 查询 API: {api_url}")

                            response = requests.get(api_url, timeout=10)
                            if response.status_code == 200:
                                data = response.json().get('data', [])
                                if data and data[0].get('doubanid'):
                                    douban_id = data[0]['doubanid']
                                    douban_link = f"https://movie.douban.com/subject/{douban_id}/"
                                    logging.info(
                                        f"✅ 成功从 API 补充豆瓣链接: {douban_link}")
                                    print(f"  [+] 成功补充豆瓣链接: {douban_link}")
                                else:
                                    logging.warning(
                                        f"API 响应中未找到与 {imdb_id} 匹配的豆瓣ID")
                                    print(
                                        f"  [-] API 响应中未找到与 {imdb_id} 匹配的豆瓣ID")
                            else:
                                logging.warning(
                                    f"API 查询失败, 状态码: {response.status_code}, 响应: {response.text}"
                                )
                                print(
                                    f"  [-] API 查询失败, 状态码: {response.status_code}"
                                )

                    elif douban_link and not imdb_link:
                        if douban_id_match := re.search(
                                r'subject/(\d+)', douban_link):
                            douban_id = douban_id_match.group(1)
                            api_url = f"{api_base_url}?doubanid={douban_id}"
                            logging.info(f"使用 Douban ID 查询远程 API: {api_url}")
                            print(f"[*] 正在使用 Douban ID 查询 API: {api_url}")

                            response = requests.get(api_url, timeout=10)
                            if response.status_code == 200:
                                data = response.json().get('data', [])
                                if data and data[0].get('imdbid'):
                                    imdb_id = data[0]['imdbid']
                                    imdb_link = f"https://www.imdb.com/title/{imdb_id}/"
                                    logging.info(
                                        f"✅ 成功从 API 补充 IMDb 链接: {imdb_link}")
                                    print(f"  [+] 成功补充 IMDb 链接: {imdb_link}")
                                else:
                                    logging.warning(
                                        f"API 响应中未找到与 {douban_id} 匹配的IMDb ID")
                                    print(
                                        f"  [-] API 响应中未找到与 {douban_id} 匹配的IMDb ID"
                                    )
                            else:
                                logging.warning(
                                    f"API 查询失败, 状态码: {response.status_code}, 响应: {response.text}"
                                )
                                print(
                                    f"  [-] API 查询失败, 状态码: {response.status_code}"
                                )

            except requests.exceptions.RequestException as e:
                logging.error(f"访问远程链接补充 API 时发生网络错误: {e}")
                print(f"  [!] 访问远程链接补充 API 时发生网络错误: {e}")
            except Exception as e:
                logging.error(f"处理远程链接补充 API 响应时发生错误: {e}", exc_info=True)
                print(f"  [!] 处理远程链接补充 API 响应时发生错误: {e}")

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

        # Extract images - 同时处理[img]和[url]格式的图片链接
        images = re.findall(r"\[img\].*?\[/img\]", bbcode, re.IGNORECASE)

        # [新增] 提取[url=图片链接][/url]格式的图片并转换为[img]格式
        url_images = re.findall(
            r'\[url=([^\]]*\.(?:jpg|jpeg|png|gif|bmp|webp)(?:[^\]]*))\]\s*\[/url\]',
            bbcode, re.IGNORECASE)
        print(f"[调试extractor] 提取到的[img]格式图片数量: {len(images)}")
        print(f"[调试extractor] 提取到的[url]格式图片数量: {len(url_images)}")
        for url_img in url_images:
            images.append(f"[img]{url_img}[/img]")
            print(f"[调试extractor] 添加转换后的图片: {url_img[:80]}")

        # [新增] 从配置文件读取并过滤掉指定的不需要的图片URL
        unwanted_image_urls = CONTENT_FILTERING_CONFIG.get("unwanted_image_urls", [])
        
        if unwanted_image_urls:
            filtered_images = []
            for img_tag in images:
                # 从[img]标签中提取URL
                url_match = re.search(r'\[img\](.*?)\[/img\]', img_tag, re.IGNORECASE)
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
        from utils.formatters import process_bbcode_images_and_cleanup
        bbcode = process_bbcode_images_and_cleanup(bbcode)

        # 注意：海报验证和转存逻辑已移至 _parse_format_content 函数中统一处理
        # 视频截图的验证将在 migrator.py 的 prepare_review_data 中单独进行

        if descr_container:
            # Extract quotes before and after poster
            # [修复] 改进判断逻辑：即使没有海报，也要正确区分感谢声明和正文内容
            poster_index = bbcode.find(images[0]) if (images
                                                      and images[0]) else -1
            quotes_before_poster = []
            quotes_after_poster = []

            for match in re.finditer(r"\[quote\].*?\[/quote\]", bbcode,
                                     re.DOTALL):
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
                        "官组" in quote_content or "感谢" in quote_content
                        or "原制作者" in quote_content or "FRDS" in quote_content
                        or "FraMeSToR" in quote_content
                        or "CHD" in quote_content or "字幕组" in quote_content
                        or len(quote_content) < 200  # 短quote更可能是声明
                    )

                    if is_acknowledgment:
                        quotes_before_poster.append(quote_content)
                    else:
                        quotes_after_poster.append(quote_content)

            # 辅助函数：检查是否为包含技术参数的quote（这些既不是mediainfo也不应该出现在正文中）
            def is_technical_params_quote(quote_text):
                """
                使用配置文件中的 technical_params_detection 规则检查是否为技术参数 quote
                """
                if not CONTENT_FILTERING_CONFIG.get("enabled", False):
                    return False
                
                # 转换为大写进行不区分大小写的匹配
                quote_upper = quote_text.upper()
                
                # 从配置文件读取技术参数检测规则
                tech_params_config = CONTENT_FILTERING_CONFIG.get(
                    "technical_params_detection", {})
                patterns = tech_params_config.get("patterns", [])
                
                for pattern in patterns:
                    keywords = pattern.get("keywords", [])
                    min_dots = pattern.get("min_dots", 0)
                    has_underscores = pattern.get("has_underscores", False)
                    
                    # 检查是否所有关键词都存在（不区分大小写）
                    if keywords:
                        all_keywords_present = all(
                            keyword in quote_text or keyword.upper() in quote_upper
                            for keyword in keywords
                        )
                        
                        if all_keywords_present:
                            # 检查额外条件
                            if min_dots > 0 and quote_text.count(".") < min_dots:
                                continue
                            if has_underscores and ("___" not in quote_text and "____" not in quote_text):
                                continue
                            
                            # 所有条件都满足
                            logging.info(f"根据配置规则 '{pattern.get('description', '')}' 识别为技术参数quote")
                            return True
                
                return False

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
                    # MediaInfo/BDInfo是技术信息，不应该被过滤掉，直接跳过处理
                    continue

                # [修复] 使用配置文件中的 unwanted_patterns 检查 quote 是否包含不需要的内容
                quote_text_without_tags = re.sub(r"\[/?quote\]",
                                                 "",
                                                 quote,
                                                 flags=re.IGNORECASE).strip()
                if self._is_unwanted_content(quote_text_without_tags):
                    logging.info(
                        f"根据配置文件过滤掉不需要的声明: {quote_text_without_tags[:50]}...")
                    ardtu_declarations.append(quote_text_without_tags)
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

            # Helper function to identify movie description quotes
            def is_movie_intro_quote(quote_text):
                keywords = [
                    "◎片　　名", "◎译　　名", "◎年　　代", "◎产　　地", "◎类　　别", "◎语　　言",
                    "◎导　　演", "◎主　　演", "◎简　　介", "◎演　　员", "◎演  员", "◎IMDB评分",
                    "◎IMDb评分", "◎获奖情况", "制片国家/地区"
                ]
                return any(keyword in quote_text for keyword in keywords)

            # Process quotes after poster
            for quote in quotes_after_poster:
                # 检查是否为mediainfo/bdinfo/技术参数的quote
                is_mediainfo_after = ("General" in quote and "Video" in quote
                                      and "Audio" in quote)
                is_bdinfo_after = ("DISC INFO" in quote
                                   and "PLAYLIST REPORT" in quote)
                is_release_info_after = ".Release.Info" in quote and "ENCODER" in quote
                is_technical_after = is_technical_params_quote(quote)

                if is_mediainfo_after or is_bdinfo_after or is_release_info_after:
                    # MediaInfo/BDInfo是技术信息，不应该被过滤掉，需要提取
                    if not found_mediainfo_in_quote:
                        mediainfo_from_quote = re.sub(
                            r"\[/?quote\]", "", quote,
                            flags=re.IGNORECASE).strip()
                        found_mediainfo_in_quote = True
                    continue
                elif is_technical_after:
                    # 只有技术参数quote才被过滤掉
                    clean_content = re.sub(r"\[\/?quote\]", "", quote).strip()
                    ardtu_declarations.append(clean_content)
                elif is_movie_intro_quote(quote):
                    # 如果quote看起来像电影简介的一部分，则将其添加到正文
                    quotes_for_body.append(quote)
                else:
                    # 海报后的其他quote应该添加到正文后面，而不是声明区域
                    quotes_for_body.append(quote)

            # Extract body content (先移除quote和图片标签)
            body = (re.sub(r"\[quote\].*?\[/quote\]|\[img\].*?\[/img\]",
                           "",
                           bbcode,
                           flags=re.DOTALL).replace("\r", "").strip())

            # [新增] 在构建body后，应用BBCode清理函数处理残留的空标签和列表标记
            from utils.formatters import process_bbcode_images_and_cleanup
            body = process_bbcode_images_and_cleanup(body)

            # [新增] 在BBCode层面过滤对比说明（包含BBCode标签的情况）
            # 移除包含Comparison和Source/Encode的行（不管是否有[b][size]等标签包裹）
            lines = body.split('\n')
            filtered_lines = []
            skip_next_line = False

            for i, line in enumerate(lines):
                if skip_next_line:
                    skip_next_line = False
                    continue

                # 去除BBCode标签后的纯文本用于检测
                line_without_bbcode = re.sub(r'\[/?[^\]]+\]', '', line)
                line_upper = line_without_bbcode.upper().strip()

                # 检测1: Comparison行
                if 'COMPARISON' in line_upper and ('RIGHT' in line_upper
                                                   or 'CLICK' in line_upper):
                    logging.info(f"过滤掉Comparison行: {line[:80]}...")
                    # 检查下一行是否是Source/Encode行
                    if i + 1 < len(lines):
                        next_line = lines[i + 1]
                        next_line_without_bbcode = re.sub(
                            r'\[/?[^\]]+\]', '', next_line)
                        if ('SOURCE' in next_line_without_bbcode.upper() and
                                'ENCODE' in next_line_without_bbcode.upper()
                                and next_line.count('_') >= 10):
                            skip_next_line = True
                    continue

                # 检测2: Source___Encode行（单独出现）
                if (line_upper.startswith('SOURCE')
                        and line_upper.endswith('ENCODE')
                        and line.count('_') >= 10):
                    logging.info(f"过滤掉Source/Encode行: {line[:80]}...")
                    continue

                # 检测3: 同一行包含Comparison和Source/Encode的情况
                if ('COMPARISON' in line_upper and 'SOURCE' in line_upper
                        and 'ENCODE' in line_upper and line.count('_') >= 5):
                    logging.info(f"过滤掉完整对比说明行: {line[:80]}...")
                    continue

                filtered_lines.append(line)

            body = '\n'.join(filtered_lines)

            # [新增] 检查简介完整性
            logging.info("开始简介完整性检测...")
            completeness_check = check_intro_completeness(body)

            if not completeness_check["is_complete"]:
                logging.warning(
                    f"检测到简介不完整，缺少字段: {completeness_check['missing_fields']}")
                print(f"检测到简介不完整，缺少字段: {completeness_check['missing_fields']}")
                logging.info(f"已找到字段: {completeness_check['found_fields']}")
                logging.info("尝试从豆瓣/IMDb重新获取完整简介...")
                print("尝试从豆瓣/IMDb重新获取完整简介...")

                # 获取已提取的链接
                imdb_link = extracted_data["intro"].get("imdb_link", "")
                douban_link = extracted_data["intro"].get("douban_link", "")

                # 如果有链接,尝试重新获取
                if imdb_link or douban_link:
                    try:
                        status, posters, new_description, new_imdb = upload_data_movie_info(
                            douban_link, imdb_link)

                        if status and new_description:
                            # 重新检查新简介的完整性
                            new_check = check_intro_completeness(
                                new_description)

                            if new_check["is_complete"]:
                                logging.info(
                                    f"✅ 重新获取的简介完整，包含字段: {new_check['found_fields']}"
                                )

                                # --- [新逻辑] 根据原简介内容决定是替换还是保留 ---
                                num_found_fields = len(
                                    completeness_check.get('found_fields', []))

                                if num_found_fields <= 2 and body.strip():
                                    # 场景 B: 原简介字段少于等于2个，视为补充信息（如发布说明），用[quote]包裹并保留
                                    logging.info(
                                        f"原简介仅包含 {num_found_fields} 个字段，视为补充信息并保留。"
                                    )
                                    print(
                                        f"[*] 原简介仅包含 {num_found_fields} 个字段，视为补充信息并保留。"
                                    )

                                    original_body_as_quote = f"[quote]{body.strip()}[/quote]"
                                    # 添加到待追加的quote列表开头
                                    quotes_for_body.insert(
                                        0, original_body_as_quote)

                                    # 将body主体替换为新获取的完整简介
                                    body = new_description

                                else:
                                    # 场景 A: 原简介字段多于2个但不完整，视为不完整的电影简介，直接替换
                                    logging.info(
                                        f"原简介包含 {num_found_fields} 个字段，不完整，将直接替换。"
                                    )
                                    print(
                                        f"[*] 原简介包含 {num_found_fields} 个字段，不完整，将直接替换。"
                                    )
                                    body = new_description

                                # --- [新逻辑结束] ---

                                # 同时更新IMDb链接(如果新获取的链接存在)
                                if new_imdb:
                                    extracted_data["intro"][
                                        "imdb_link"] = new_imdb

                                # 重新提取产地信息并更新
                                new_origin = extract_origin_from_description(
                                    new_description)
                                if new_origin:
                                    # 应用全局映射
                                    if GLOBAL_MAPPINGS and "source" in GLOBAL_MAPPINGS:
                                        source_mappings = GLOBAL_MAPPINGS[
                                            "source"]
                                        mapped_origin = None
                                        for source_text, standardized_key in source_mappings.items(
                                        ):
                                            if (str(source_text).strip().lower(
                                            ) == str(new_origin).strip().lower(
                                            ) or str(source_text).strip(
                                            ).lower() in str(new_origin).strip(
                                            ).lower() or str(new_origin).strip(
                                            ).lower() in str(source_text).
                                                    strip().lower()):
                                                mapped_origin = standardized_key
                                                break

                                        if mapped_origin:
                                            extracted_data["source_params"][
                                                "产地"] = mapped_origin
                                            logging.info(
                                                f"✅ 从新简介中提取并映射产地: {new_origin} -> {mapped_origin}"
                                            )
                                        else:
                                            extracted_data["source_params"][
                                                "产地"] = new_origin
                                            logging.info(
                                                f"✅ 从新简介中提取到产地: {new_origin}")
                                    else:
                                        extracted_data["source_params"][
                                            "产地"] = new_origin
                                        logging.info(
                                            f"✅ 从新简介中提取到产地: {new_origin}")
                            else:
                                logging.warning(
                                    f"重新获取的简介仍不完整，缺少: {new_check['missing_fields']}，保留原简介"
                                )
                        else:
                            logging.warning(f"重新获取简介失败: {posters}")

                    except Exception as e:
                        logging.error(f"重新获取简介时发生错误: {e}", exc_info=True)
                else:
                    logging.warning("未找到豆瓣或IMDb链接，无法重新获取简介")
            else:
                logging.info(
                    f"✅ 简介完整性检测通过，包含字段: {completeness_check['found_fields']}")

            # [新增] 额外检查：即使简介完整，也检查是否缺少集数/IMDb/豆瓣链接
            from utils.description_enhancer import enhance_description_if_needed

            enhanced_body, enhanced_imdb, description_changed = enhance_description_if_needed(
                body, extracted_data["intro"].get("imdb_link", ""),
                extracted_data["intro"].get("douban_link", ""))

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
            words_to_remove = {'mediainfo', 'screenshot', 'source', 'encode'}
            lines = body.split('\n')
            cleaned_lines = []
            for line in lines:
                # 检查是否为独立关键词行
                if line.strip().lower() in words_to_remove:
                    continue

                # [新增] 检查是否为对比截图说明行
                line_upper = line.upper()
                line_stripped = line.strip()

                # 条件1: 包含 Comparison 和 Source/Encode 且有下划线分隔
                if ('COMPARISON' in line_upper and 'SOURCE' in line_upper
                        and 'ENCODE' in line_upper and
                    ('___' in line or '____' in line or '_______' in line)):
                    logging.info(f"过滤掉对比说明行(带下划线): {line[:50]}...")
                    continue

                # 条件2: 只有 Source 和 Encode 且中间有大量下划线的单行
                # 例如: "Source________________________Encode"
                if (line_stripped.upper().startswith('SOURCE')
                        and line_stripped.upper().endswith('ENCODE')
                        and line.count('_') >= 10):  # 至少10个下划线
                    logging.info(f"过滤掉对比说明行(纯下划线): {line[:50]}...")
                    continue

                # 条件3: 单独的 "Comparison" 行（通常出现在对比说明前）
                if line_stripped.lower().startswith('comparison') and len(
                        line_stripped) < 100:
                    # 检查是否包含典型的对比说明文本
                    if 'right' in line_stripped.lower(
                    ) or 'click' in line_stripped.lower():
                        logging.info(f"过滤掉对比说明行(Comparison): {line[:50]}...")
                        continue

                cleaned_lines.append(line)

            body = '\n'.join(cleaned_lines)

            # Format statement string
            statement_string = "\n".join(final_statement_quotes)
            if statement_string:
                statement_string = re.sub(r'(\r?\n){3,}', r'\n\n',
                                          statement_string).strip()

            extracted_data["intro"]["statement"] = statement_string
            # 直接使用提取到的第一张图片作为海报（验证和转存在 _parse_format_content 中处理）
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

        # 过滤掉指定的标签
        filtered_tags = []
        unwanted_tags = ["官方", "官种", "首发", "自购", "应求"]
        for tag in tags:
            if tag not in unwanted_tags:
                filtered_tags.append(tag)

        # 添加去重处理，保持顺序
        if filtered_tags:
            filtered_tags = list(dict.fromkeys(filtered_tags))

        tags = filtered_tags

        type_text = basic_info_dict.get("类型", "")
        type_match = re.search(r"[\(（](.*?)[\)）]", type_text)

        extracted_data["source_params"]["类型"] = type_match.group(
            1) if type_match else type_text.split("/")[-1]
        extracted_data["source_params"]["媒介"] = basic_info_dict.get("媒介")
        # 视频编码：优先获取"视频编码"，如果没有则获取"编码"
        extracted_data["source_params"]["视频编码"] = basic_info_dict.get(
            "视频编码") or basic_info_dict.get("编码")
        extracted_data["source_params"]["音频编码"] = basic_info_dict.get("音频编码")
        # 如果页面上没有音频编码，则尝试从mediainfo中提取
        if not extracted_data["source_params"]["音频编码"] and extracted_data.get(
                "mediainfo"):
            logging.info("页面未提供音频编码，尝试从MediaInfo中提取...")
            audio_codec_from_mediainfo = extract_audio_codec_from_mediainfo(
                extracted_data["mediainfo"])
            if audio_codec_from_mediainfo:
                extracted_data["source_params"][
                    "音频编码"] = audio_codec_from_mediainfo
                logging.info(
                    f"成功从MediaInfo中提取到音频编码: {audio_codec_from_mediainfo}")

        extracted_data["source_params"]["分辨率"] = basic_info_dict.get("分辨率")
        extracted_data["source_params"]["制作组"] = basic_info_dict.get("制作组")
        extracted_data["source_params"]["标签"] = tags

        # Extract origin information
        from utils import extract_origin_from_description, check_intro_completeness, upload_data_movie_info
        full_description_text = f"{extracted_data['intro']['statement']}\n{extracted_data['intro']['body']}"
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
        # [修复] 应该使用 source_parsers.standard_keys.tag 而不是 mappings.tag
        site_mappings = site_config.get("source_parsers",
                                        {}).get("standard_keys",
                                                {}).get("tag", {})

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
                # [修复] 只有当原始值是明确的无效值时才返回 team.other
                # 否则保留原始完整的制作组名称（包括合作制作组）
                if original_value_str.lower() in [
                        "other", "未知", "unknown", ""
                ]:
                    return "team.other"
                else:
                    # 保留原始完整制作组名称（如 "Nest@ADE"）
                    return original_value_str
            return value_str  # 其他参数返回原始值

        # 1. 分别从 source_params 和 title_components 提取并标准化
        source_standard_values = {}
        source_params_config = source_parsers.get("source_params", {})
        for param_key, config in source_params_config.items():
            raw_value = source_params.get(config.get("source_key"))
            if raw_value:
                source_standard_values[param_key] = get_standard_key_for_value(
                    raw_value, param_key)

        title_standard_values = {}
        # 使用默认的 title_components 配置，如果站点配置中没有定义
        title_components_config = source_parsers.get("title_components",
                                                     DEFAULT_TITLE_COMPONENTS)
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

        # 如果source参数不存在，尝试从原始参数中获取
        # 注意：现在统一使用source映射，不再有单独的processing映射
        if "source" not in final_standardized_params:
            # 尝试从原始参数中获取（兼容使用"区域"等字段的站点）
            source_value = source_params.get("产地") or source_params.get("区域")
            if source_value:
                final_standardized_params[
                    "source"] = get_standard_key_for_value(
                        source_value, "source")

        # 处理标签映射 - 使用站点特定的标签映射
        final_standardized_params["tags"] = self._map_tags(
            source_params.get("标签", []), site_name)

        # [新增] 从简介和副标题中提取标签和进行类型修正
        from utils.media_helper import extract_tags_from_description, check_animation_type_from_description, extract_tags_from_subtitle

        intro_statement = extracted_params.get("intro",
                                               {}).get("statement", "")
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
            global_type_mappings = GLOBAL_MAPPINGS.get("type", {})
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

        return final_standardized_params
