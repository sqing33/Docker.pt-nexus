# core/migrator.py

import cloudscraper
from bs4 import BeautifulSoup, Tag
from loguru import logger
import re
import json
import os
import sys
import time
import bencoder
import requests
import urllib3
import traceback
import importlib
from io import StringIO
from config import TEMP_DIR
from utils import ensure_scheme, upload_data_mediaInfo, upload_data_title, extract_tags_from_mediainfo, extract_origin_from_description

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class LoguruHandler(StringIO):
    """一个内存中的日志处理器，用于捕获日志并在 API 响应中返回。"""

    def __init__(self, site_name=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []
        self.site_name = site_name

    def write(self, message):
        # Add site name prefix to each log message if available
        if self.site_name:
            message = f"[{self.site_name}] {message}"
        self.records.append(message.strip())

    def get_logs(self):
        return "\n".join(self.records)


class TorrentMigrator:
    """一个用于将种子从一个PT站点迁移到另一个站点的工具类。"""

    def __init__(self,
                 source_site_info,
                 target_site_info,
                 search_term="",
                 save_path="",
                 config_manager=None):
        self.source_site = source_site_info
        self.target_site = target_site_info
        self.search_term = search_term
        self.save_path = save_path
        self.config_manager = config_manager

        self.SOURCE_BASE_URL = ensure_scheme(self.source_site.get("base_url"))
        self.SOURCE_NAME = self.source_site["nickname"]
        self.SOURCE_COOKIE = self.source_site["cookie"]
        self.SOURCE_PROXY = self.source_site.get("proxy", False)

        # 只有在 target_site_info 存在时才初始化目标相关属性
        if self.target_site:
            self.TARGET_BASE_URL = ensure_scheme(
                self.target_site.get("base_url"))
            self.TARGET_COOKIE = self.target_site.get("cookie")
            self.TARGET_PASSKEY = self.target_site.get("passkey")
            self.TARGET_UPLOAD_MODULE = self.target_site["site"]
            self.TARGET_TRACKER_URL = f"{self.TARGET_BASE_URL}/announce.php"
            self.TARGET_PROXY = self.target_site.get("proxy", False)

        # Initialize scraper and logger
        session = requests.Session()
        session.verify = False
        self.scraper = cloudscraper.create_scraper(sess=session)

        # Create a separate log handler for this instance with site name
        site_name = self.target_site[
            "nickname"] if self.target_site else self.SOURCE_NAME
        self.log_handler = LoguruHandler(site_name=site_name)
        self.logger = logger
        self.logger.remove()
        self.logger.add(self.log_handler,
                        format="{time:HH:mm:ss} - {level} - {message}",
                        level="DEBUG")

        self.temp_files = []

    def apply_special_extractor_if_needed(self, upload_data, torrent_id=None):
        """
        根据源站点名称决定是否使用特殊提取器处理数据

        Args:
            upload_data: 上传数据字典
            torrent_id: 种子ID，用于保存提取内容到本地文件

        Returns:
            处理后的upload_data
        """
        print(f"检查是否需要应用特殊提取器处理，源站点: {self.SOURCE_NAME}")
        # 检查是否需要使用特殊提取器处理"人人"、"不可说"或"憨憨"站点数据
        # 添加检查确保不会重复处理已标记的数据
        if self.SOURCE_NAME == "人人" or self.SOURCE_NAME == "不可说" or self.SOURCE_NAME == "憨憨":
            # 首先检查upload_data中是否已经有处理标志
            processed_flag = upload_data.get("special_extractor_processed",
                                             False)
            if not processed_flag:
                # 如果没有，检查实例变量
                processed_flag = getattr(self, '_special_extractor_processed',
                                         False)
            print(f"检测到源站点为{self.SOURCE_NAME}，已处理标记: {processed_flag}")
            if processed_flag:
                print(
                    f"检测到源站点为{self.SOURCE_NAME}，但已在prepare_review_data阶段处理过，跳过特殊提取器处理"
                )
                return upload_data
            else:
                try:
                    print(f"检测到源站点为{self.SOURCE_NAME}，尝试使用特殊提取器处理数据...")

                    # 从upload_data构造HTML内容用于提取器
                    html_parts = []
                    html_parts.append("<html><body>")

                    # 添加基本信息表格（模拟原始页面结构）
                    basic_info = upload_data.get("source_params", {})
                    if basic_info:
                        html_parts.append("<table>")
                        html_parts.append("<tr><td>基本信息</td><td>")
                        for key, value in basic_info.items():
                            if value:
                                html_parts.append(f"<div>{key}: {value}</div>")
                        html_parts.append("</td></tr>")
                        html_parts.append("</table>")

                    # 添加标签信息
                    tags = upload_data.get("source_params", {}).get("标签", [])
                    if tags:
                        html_parts.append("<table>")
                        html_parts.append("<tr><td>标签</td><td>")
                        for tag in tags:
                            html_parts.append(f"<span>{tag}</span>")
                        html_parts.append("</td></tr>")
                        html_parts.append("</table>")

                    # 添加副标题信息
                    subtitle = upload_data.get("subtitle", "")
                    if subtitle:
                        html_parts.append("<table>")
                        html_parts.append(
                            f"<tr><td>副标题</td><td>{subtitle}</td></tr>")
                        html_parts.append("</table>")

                    # 添加简介内容
                    intro_data = upload_data.get("intro", {})
                    html_parts.append(
                        f"<div id='kdescr'>{intro_data.get('statement', '')}{intro_data.get('body', '')}{intro_data.get('screenshots', '')}</div>"
                    )

                    # 添加MediaInfo内容
                    mediainfo = upload_data.get("mediainfo", "")
                    if mediainfo:
                        html_parts.append(
                            f"<div class='spoiler-content'><pre>{mediainfo}</pre></div>"
                        )

                    html_parts.append("</body></html>")

                    html_content = "".join(html_parts)
                    print(f"构造的HTML内容长度: {len(html_content)}")
                    soup = BeautifulSoup(html_content, "html.parser")

                    # 使用统一的数据提取方法
                    extracted_data = self._extract_data_by_site_type(
                        soup, torrent_id)
                    print(
                        f"特殊提取器返回数据键: {extracted_data.keys() if extracted_data else 'None'}"
                    )

                    # 使用特殊提取器的结果更新upload_data
                    if "source_params" in extracted_data and extracted_data[
                            "source_params"]:
                        print("更新source_params数据")
                        original_source_params = upload_data.get(
                            "source_params", {}).copy()
                        # 合并source_params，但优先使用特殊提取器的结果
                        merged_source_params = {
                            **original_source_params,
                            **extracted_data["source_params"]
                        }
                        upload_data["source_params"] = merged_source_params
                        print(f"source_params更新前: {original_source_params}")
                        print(
                            f"source_params更新后: {upload_data['source_params']}"
                        )

                    if "subtitle" in extracted_data and extracted_data[
                            "subtitle"]:
                        print("更新subtitle数据")
                        original_subtitle = upload_data.get("subtitle", "")
                        upload_data["subtitle"] = extracted_data["subtitle"]
                        print(f"subtitle更新前: {original_subtitle}")
                        print(f"subtitle更新后: {upload_data['subtitle']}")

                    if "intro" in extracted_data and extracted_data["intro"]:
                        print("更新intro数据")
                        # 合并intro数据，保留原有内容但用提取器的结果覆盖
                        original_intro = upload_data.get("intro", {}).copy()
                        upload_data["intro"] = {
                            **original_intro,
                            **extracted_data["intro"]
                        }
                        print(f"intro更新前: {original_intro}")
                        print(f"intro更新后: {upload_data['intro']}")

                    if "mediainfo" in extracted_data and extracted_data[
                            "mediainfo"]:
                        print("更新mediainfo数据")
                        original_mediainfo = upload_data.get("mediainfo", "")
                        upload_data["mediainfo"] = extracted_data["mediainfo"]
                        print(
                            f"mediainfo更新前长度: {len(original_mediainfo) if original_mediainfo else 0}"
                        )
                        print(
                            f"mediainfo更新后长度: {len(upload_data['mediainfo']) if upload_data['mediainfo'] else 0}"
                        )

                    if "title" in extracted_data and extracted_data["title"]:
                        print("更新title数据")
                        original_title = upload_data.get("title", "")
                        upload_data["title"] = extracted_data["title"]
                        print(f"title更新前: {original_title}")
                        print(f"title更新后: {upload_data['title']}")

                    # 移除了针对"不可说"站点的特殊主标题处理，现在统一处理所有站点

                    print(f"已使用特殊提取器处理来自{self.SOURCE_NAME}站点的数据")
                    # 标记已处理，避免重复处理
                    self._special_extractor_processed = True
                    # 同时在upload_data中添加标记
                    upload_data["special_extractor_processed"] = True
                except Exception as e:
                    print(f"使用特殊提取器处理{self.SOURCE_NAME}站点数据时发生错误: {e}")
                    import traceback
                    traceback.print_exc()
                    # 如果特殊提取器失败，继续使用默认处理
        else:
            print(f"源站点 {self.SOURCE_NAME} 不需要特殊提取器处理")

        return upload_data

    def cleanup(self):
        """清理所有临时文件"""
        for f in self.temp_files:
            try:
                os.remove(f)
                self.logger.info(f"已清理临时文件: {f}")
            except OSError as e:
                self.logger.warning(f"清理临时文件 {f} 失败: {e}")

    def _get_proxies(self, use_proxy):
        """获取代理配置"""
        if not use_proxy or not self.config_manager:
            return None

        try:
            conf = (self.config_manager.get() or {})
            # 优先使用转种设置中的代理地址，其次兼容旧的 network.proxy_url
            proxy_url = (conf.get("cross_seed", {})
                         or {}).get("proxy_url") or (conf.get("network", {})
                                                     or {}).get("proxy_url")
            if proxy_url:
                self.logger.info(f"使用代理: {proxy_url}")
                return {"http": proxy_url, "https": proxy_url}
        except Exception as e:
            self.logger.warning(f"代理设置失败: {e}")

        return None

    def _html_to_bbcode(self, tag):
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

    def search_and_get_torrent_id(self, torrent_name):
        search_url = f"{self.SOURCE_BASE_URL}/torrents.php"
        search_torrent_name = re.sub(r'(?<!\d)\.|\.(?!\d\b)', ' ',
                                     torrent_name)
        params = {
            "incldead": "1",
            "search": search_torrent_name,
            "search_area": "0",
            "search_mode": "2"
        }
        self.logger.info(f"正在源站 '{self.SOURCE_NAME}' 搜索种子: '{torrent_name}'")
        try:
            # 获取代理配置
            proxies = self._get_proxies(self.SOURCE_PROXY)
            if proxies:
                self.logger.info(f"使用代理进行搜索: {proxies}")

            response = self.scraper.get(search_url,
                                        headers={"Cookie": self.SOURCE_COOKIE},
                                        params=params,
                                        timeout=60,
                                        proxies=proxies)
            response.raise_for_status()
            response.encoding = "utf-8"
            self.logger.success("搜索请求成功！")
            soup = BeautifulSoup(response.text, "html.parser")
            link = soup.find("a", title=torrent_name) or soup.select_one(
                'table.torrentname a[href*="details.php?id="]')
            if (isinstance(link, Tag) and (href := link.get("href"))
                    and isinstance(href, str)
                    and (match := re.search(r"id=(\d+)", href))):
                torrent_id = match.group(1)
                self.logger.success(f"成功找到种子ID: {torrent_id}")
                return torrent_id
            self.logger.warning("未在搜索结果中找到完全匹配的种子。")
            return None
        except Exception as e:
            self.logger.opt(exception=True).error(f"搜索过程中发生错误: {e}")
            return None

    def modify_torrent_file(self, original_path, main_title):
        self.logger.info(f"正在使用 bencoder 修改 .torrent 文件: {original_path}...")
        try:
            with open(original_path, "rb") as f:
                decoded_torrent = bencoder.decode(f.read())
            self.logger.info("原始种子文件解码成功。")
            new_tracker_url_str = f"{self.TARGET_TRACKER_URL}?passkey={self.TARGET_PASSKEY}"
            decoded_torrent[b"announce"] = new_tracker_url_str.encode("utf-8")
            self.logger.info(f"将设置新的 Tracker URL 为: {new_tracker_url_str}")
            for key in [
                    b"announce-list",
                    b"comment",
                    b"publisher",
                    b"publisher.utf-8",
                    b"publisher-url",
                    b"publisher-url.utf-8",
            ]:
                if key in decoded_torrent:
                    del decoded_torrent[key]
                    self.logger.info(f"已移除 '{key.decode()}' 字段。")
            if b"info" in decoded_torrent:
                decoded_torrent[b"info"][b"private"] = 1
                self.logger.info("已确保 'private' 标记设置为 1。")
                if b"source" in decoded_torrent[b"info"]:
                    del decoded_torrent[b"info"][b"source"]
                    self.logger.info("已从 'info' 字典中移除 'source' 字段。")
            else:
                self.logger.error("'info' 字典未找到，任务终止。")
                return None
            modified_content = bencoder.encode(decoded_torrent)
            safe_filename = re.sub(r'[\\/*?:"<>|]', "_", main_title)[:150]
            modified_path = os.path.join(
                TEMP_DIR, f"{safe_filename}.modified.{time.time()}.torrent")
            with open(modified_path, "wb") as f:
                f.write(modified_content)
            self.logger.success(f"已成功生成新的种子文件: {modified_path}")
            self.temp_files.append(modified_path)
            return modified_path
        except Exception as e:
            self.logger.opt(
                exception=True).error(f"修改 .torrent 文件时发生严重错误: {e}")
            return None

    def _extract_data_by_site_type(self, soup, torrent_id):
        """
        根据站点类型选择对应的提取器提取数据

        Args:
            soup: BeautifulSoup对象，包含种子详情页的HTML
            torrent_id: 种子ID

        Returns:
            dict: 包含提取数据的字典
        """
        # 初始化默认数据结构
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
                "编码": None,
                "音频编码": None,
                "分辨率": None,
                "制作组": None,
                "标签": [],
                "产地": ""
            }
        }

        # 根据站点类型选择对应的提取器
        if self.SOURCE_NAME in ["人人", "不可说", "憨憨"]:
            try:
                print(f"使用特殊提取器处理 {self.SOURCE_NAME} 站点数据")
                if self.SOURCE_NAME == "人人":
                    from core.extractors.audiences import AudiencesSpecialExtractor
                    extractor = AudiencesSpecialExtractor(soup)
                elif self.SOURCE_NAME == "不可说":
                    from core.extractors.ssd import SSDSpecialExtractor
                    extractor = SSDSpecialExtractor(soup)
                elif self.SOURCE_NAME == "憨憨":
                    from core.extractors.hhanclub import HHCLUBSpecialExtractor
                    extractor = HHCLUBSpecialExtractor(soup)

                # 调用特殊提取器
                special_extracted_data = extractor.extract_all(
                    torrent_id=torrent_id)
                print(
                    f"特殊提取器返回数据键: {special_extracted_data.keys() if special_extracted_data else 'None'}"
                )

                # 合并特殊提取器的数据到默认结构中
                if special_extracted_data:
                    # 合并title
                    if "title" in special_extracted_data and special_extracted_data[
                            "title"]:
                        extracted_data["title"] = special_extracted_data[
                            "title"]

                    # 合并subtitle
                    if "subtitle" in special_extracted_data and special_extracted_data[
                            "subtitle"]:
                        extracted_data["subtitle"] = special_extracted_data[
                            "subtitle"]

                    # 合并intro
                    if "intro" in special_extracted_data and special_extracted_data[
                            "intro"]:
                        # 合并intro字典的各个字段
                        for key in extracted_data["intro"]:
                            if key in special_extracted_data[
                                    "intro"] and special_extracted_data[
                                        "intro"][key]:
                                extracted_data["intro"][
                                    key] = special_extracted_data["intro"][key]

                    # 合并mediainfo
                    if "mediainfo" in special_extracted_data and special_extracted_data[
                            "mediainfo"]:
                        extracted_data["mediainfo"] = special_extracted_data[
                            "mediainfo"]

                    # 合并source_params
                    if "source_params" in special_extracted_data and special_extracted_data[
                            "source_params"]:
                        for key in extracted_data["source_params"]:
                            if key in special_extracted_data[
                                    "source_params"] and special_extracted_data[
                                        "source_params"][key] is not None:
                                extracted_data["source_params"][
                                    key] = special_extracted_data[
                                        "source_params"][key]

                print(f"特殊提取器处理完成")
                return extracted_data

            except Exception as e:
                print(f"使用特殊提取器处理 {self.SOURCE_NAME} 站点数据时发生错误: {e}")
                import traceback
                traceback.print_exc()
                # 如果特殊提取器失败，继续使用公共提取器

        # 使用公共提取器（默认提取器）
        print(f"使用公共提取器处理 {self.SOURCE_NAME} 站点数据")
        return self._extract_data_common(soup)

    def _extract_data_common(self, soup):
        """
        使用公共方法提取数据

        Args:
            soup: BeautifulSoup对象，包含种子详情页的HTML

        Returns:
            dict: 包含提取数据的字典
        """
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
                "编码": None,
                "音频编码": None,
                "分辨率": None,
                "制作组": None,
                "标签": [],
                "产地": ""
            }
        }

        # 从h1#top提取标题
        h1_top = soup.select_one("h1#top")
        if h1_top:
            title = list(
                h1_top.stripped_strings)[0] if h1_top.stripped_strings else ""
            title = re.sub(r'(?<!\d)\.|\.(?!\d\b)', ' ', title)
            title = re.sub(r'\s+', ' ', title).strip()
            extracted_data["title"] = title

        # 提取副标题
        subtitle_td = soup.find("td", string=re.compile(r"\s*副标题\s*"))
        if subtitle_td and subtitle_td.find_next_sibling("td"):
            subtitle = subtitle_td.find_next_sibling("td").get_text(strip=True)
            subtitle = re.sub(r"\s*\|\s*[Aa][Bb]y\s+\w+.*$", "", subtitle)
            subtitle = re.sub(r"\s*\|\s*[Bb]y\s+\w+.*$", "", subtitle)
            subtitle = re.sub(r"\s*\|\s*[Aa]\s+\w+.*$", "", subtitle)
            subtitle = re.sub(r"\s*\|\s*[Aa][Tt][Uu]\s*$", "", subtitle)
            subtitle = re.sub(r"\s*\|\s*[Dd][Tt][Uu]\s*$", "", subtitle)
            subtitle = re.sub(r"\s*\|\s*[Pp][Tt][Ee][Rr]\s*$", "", subtitle)
            extracted_data["subtitle"] = subtitle

        # 提取简介信息
        descr_container = soup.select_one("div#kdescr")
        if descr_container:
            # 提取IMDb和豆瓣链接
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

            # 提取简介内容
            descr_html_string = str(descr_container)
            corrected_descr_html = re.sub(r'</?br\s*/?>',
                                          '<br/>',
                                          descr_html_string,
                                          flags=re.IGNORECASE)
            corrected_descr_html = re.sub(r'(<img[^>]*[^/])>', r'\1 />',
                                          corrected_descr_html)
            try:
                descr_container_soup = BeautifulSoup(corrected_descr_html,
                                                     "lxml")
            except ImportError:
                descr_container_soup = BeautifulSoup(corrected_descr_html,
                                                     "html.parser")

            bbcode = self._html_to_bbcode(descr_container_soup)

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

            images = re.findall(r"\[img\].*?\[/img\]", bbcode)

            # 新逻辑：区分海报前后的[quote]内容
            # 找到海报的位置
            poster_index = bbcode.find(images[0]) if images else -1

            # 分别提取海报前和海报后的引用内容
            quotes_before_poster = []
            quotes_after_poster = []

            # 使用正则表达式查找所有引用，同时记录它们的位置
            for match in re.finditer(r"\[quote\].*?\[/quote\]", bbcode, re.DOTALL):
                quote_content = match.group(0)
                quote_start = match.start()

                # 判断引用是在海报前还是海报后
                if poster_index != -1 and quote_start < poster_index:
                    # 海报前的引用
                    quotes_before_poster.append(quote_content)
                else:
                    # 海报后的引用或者是没有海报的情况
                    quotes_after_poster.append(quote_content)

            final_statement_quotes = []
            ardtu_declarations = []
            mediainfo_from_quote = ""
            found_mediainfo_in_quote = False
            quotes_for_body = []  # 用于存储应该放在简介和截图之间的引用

            # 处理海报前的引用（声明部分）
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

            # 处理海报后的引用（放在简介和截图之间）
            for quote in quotes_after_poster:
                # 这些引用将直接添加到body中合适的位置
                quotes_for_body.append(quote)

            # 移除所有引用和图片来获取body内容
            body = (re.sub(r"\[quote\].*?\[/quote\]|\[img\].*?\[/img\]",
                           "",
                           bbcode,
                           flags=re.DOTALL).replace("\r", "").strip())

            # 将海报后的引用内容添加到body的合适位置（在简介和截图之间）
            if quotes_for_body:
                # 简单地将这些引用添加到body的末尾
                # 实际项目中可能需要更复杂的逻辑来确定确切位置
                body = body + "\n\n" + "\n".join(quotes_for_body)

            # 【新增】格式化 statement 字符串，合并多余换行
            statement_string = "\n".join(final_statement_quotes)
            if statement_string:
                # 将3个及以上的换行符替换为2个（保留段落间距），然后去除首尾空白
                statement_string = re.sub(r'(\r?\n){3,}', r'\n\n',
                                          statement_string).strip()

            extracted_data["intro"]["statement"] = statement_string
            extracted_data["intro"]["poster"] = images[0] if images else ""
            extracted_data["intro"]["body"] = re.sub(r"\n{2,}", "\n", body)
            extracted_data["intro"]["screenshots"] = "\n".join(images[1:]) if len(images) > 1 else ""
            extracted_data["intro"][
                "removed_ardtudeclarations"] = ardtu_declarations

        # 提取MediaInfo
        mediainfo_pre = soup.select_one(
            "div.spoiler-content pre, div.nexus-media-info-raw > pre")
        mediainfo_text = mediainfo_pre.get_text(
            strip=True) if mediainfo_pre else ""

        if not mediainfo_text and mediainfo_from_quote:
            self.logger.info("在简介的引用(quote)中找到了MediaInfo。")
            mediainfo_text = mediainfo_from_quote

        # 【新增】格式化 mediainfo 字符串，去除所有空行
        if mediainfo_text:
            # 将2个及以上的换行符替换为1个，使其紧凑
            mediainfo_text = re.sub(r'(\r?\n){2,}', r'\n',
                                    mediainfo_text).strip()

        extracted_data["mediainfo"] = mediainfo_text

        # 提取基本信息和标签
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
        extracted_data["source_params"]["编码"] = basic_info_dict.get("编码")
        extracted_data["source_params"]["音频编码"] = basic_info_dict.get("音频编码")
        extracted_data["source_params"]["分辨率"] = basic_info_dict.get("分辨率")
        extracted_data["source_params"]["制作组"] = basic_info_dict.get("制作组")
        extracted_data["source_params"]["标签"] = tags

        # 提取产地信息
        full_description_text = f"{extracted_data['intro']['statement']}\n{extracted_data['intro']['body']}"
        origin_info = extract_origin_from_description(full_description_text)
        extracted_data["source_params"]["产地"] = origin_info

        return extracted_data

    def prepare_review_data(self):
        """第一步(新)：获取、解析信息，并下载原始种子文件，但不进行修改。"""
        try:
            self.logger.info(f"--- [步骤1] 开始获取种子信息 (源: {self.SOURCE_NAME}) ---")
            print(f"开始prepare_review_data处理，源站点: {self.SOURCE_NAME}")
            torrent_id = (self.search_term if self.search_term.isdigit() else
                          self.search_and_get_torrent_id(self.search_term))
            if not torrent_id:
                raise Exception("未能获取到种子ID，请检查种子名称或ID是否正确。")

            self.logger.info(f"正在获取种子(ID: {torrent_id})的详细信息...")
            # 获取代理配置
            proxies = self._get_proxies(self.SOURCE_PROXY)
            if proxies:
                self.logger.info(f"使用代理获取详情页: {proxies}")

            response = self.scraper.get(
                f"{self.SOURCE_BASE_URL}/details.php",
                headers={"Cookie": self.SOURCE_COOKIE},
                params={
                    "id": torrent_id,
                    "hit": "1"
                },
                timeout=60,
                proxies=proxies,
            )
            response.raise_for_status()
            response.encoding = "utf-8"

            self.logger.success("详情页请求成功！")

            soup = BeautifulSoup(response.text, "html.parser")

            # --- [核心修改 1] 开始 ---
            # 先下载种子文件，以便获取其准确的文件名
            download_link_tag = soup.select_one(
                f'a.index[href^="download.php?id={torrent_id}"]')
            if not download_link_tag:
                raise Exception("在详情页未找到种子下载链接。")
            torrent_response = self.scraper.get(
                f"{self.SOURCE_BASE_URL}/{download_link_tag['href']}",
                headers={"Cookie": self.SOURCE_COOKIE},
                timeout=60,
                proxies=proxies,
            )
            torrent_response.raise_for_status()

            # 从响应头中尝试获取文件名，这是最准确的方式
            content_disposition = torrent_response.headers.get(
                'content-disposition')
            torrent_filename = "default.torrent"  # 设置一个默认值
            if content_disposition:
                filename_match = re.search(r'filename="?([^"]+)"?',
                                           content_disposition)
                if filename_match:
                    torrent_filename = filename_match.group(1)

            # 使用统一的数据提取方法
            extracted_data = self._extract_data_by_site_type(soup, torrent_id)

            # 获取主标题
            original_main_title = extracted_data.get("title", "")
            if not original_main_title:
                # 如果提取器没有返回标题，则从h1#top获取
                h1_top = soup.select_one("h1#top")
                original_main_title = list(
                    h1_top.stripped_strings)[0] if h1_top else "未找到标题"
                # 统一处理标题中的点号，将点(.)替换为空格，但保留小数点格式(如 7.1)
                original_main_title = re.sub(r'(?<!\d)\.|\.(?!\d\b)', ' ',
                                             original_main_title)
                original_main_title = re.sub(r'\s+', ' ',
                                             original_main_title).strip()

            self.logger.info(f"获取到原始主标题: {original_main_title}")

            safe_filename_base = re.sub(r'[\\/*?:"<>|]', "_",
                                        original_main_title)[:150]
            original_torrent_path = os.path.join(
                TEMP_DIR, f"{safe_filename_base}.original.torrent")
            with open(original_torrent_path, "wb") as f:
                f.write(torrent_response.content)
            self.temp_files.append(original_torrent_path)

            # 调用 upload_data_title 时，传入主标题和种子文件名
            title_components = upload_data_title(original_main_title,
                                                 torrent_filename)
            # --- [核心修改 1] 结束 ---

            if not title_components:
                self.logger.warning("主标题解析失败，将使用原始标题作为回退。")
                title_components = {"主标题": original_main_title, "无法识别": "解析失败"}
            else:
                self.logger.success("主标题成功解析为参数。")

            # 从提取的数据中获取其他信息
            subtitle = extracted_data.get("subtitle", "")
            intro = extracted_data.get("intro", {})
            mediainfo_text = extracted_data.get("mediainfo", "")
            source_params = extracted_data.get("source_params", {})

            # 提取IMDb和豆瓣链接
            imdb_link = intro.get("imdb_link", "")
            douban_link = intro.get("douban_link", "")

            # 使用统一提取方法获取的数据
            descr_container = soup.select_one("div#kdescr")

            # 从提取的数据中获取简介信息
            intro_data = extracted_data.get("intro", {})
            quotes = intro_data.get(
                "statement",
                "").split('\n') if intro_data.get("statement") else []
            images = []
            if intro_data.get("poster"):
                images.append(intro_data.get("poster"))
            if intro_data.get("screenshots"):
                images.extend(intro_data.get("screenshots").split('\n'))
            body = intro_data.get("body", "")
            ardtu_declarations = intro_data.get("removed_ardtudeclarations",
                                                [])

            # 如果海报失效，尝试从豆瓣或IMDb获取新海报
            from utils import upload_data_movie_info

            # 检查当前海报是否有效（简单检查是否包含图片标签）
            current_poster_valid = bool(images and images[0]
                                        and "[img]" in images[0])

            if not current_poster_valid:
                self.logger.info("当前海报失效，尝试从豆瓣或IMDb获取新海报...")

                # 优先级1：如果有豆瓣链接，优先从豆瓣获取
                if douban_link:
                    self.logger.info(f"尝试从豆瓣链接获取海报: {douban_link}")
                    poster_status, poster_content, description_content, extracted_imdb = upload_data_movie_info(
                        douban_link, "")

                    if poster_status and poster_content:
                        # 成功获取到海报，更新images列表
                        if not images:
                            images = [poster_content]
                        else:
                            images[0] = poster_content
                        self.logger.success("成功从豆瓣获取到海报")

                        # 如果同时获取到IMDb链接且当前没有IMDb链接，也更新IMDb链接
                        if extracted_imdb and not imdb_link:
                            imdb_link = extracted_imdb
                            self.logger.info(f"通过豆瓣海报提取到IMDb链接: {imdb_link}")

                            # 将IMDb链接添加到简介中
                            imdb_info = f"◎IMDb链接　[url={imdb_link}]{imdb_link}[/url]"
                            douban_pattern = r"◎豆瓣链接　\[url=[^\]]+\][^\[]+\[/url\]"
                            if re.search(douban_pattern, body):
                                body = re.sub(
                                    douban_pattern,
                                    lambda m: m.group(0) + "\n" + imdb_info,
                                    body)
                            else:
                                if body:
                                    body = f"{body}\n\n{imdb_info}"
                                else:
                                    body = imdb_info
                    else:
                        self.logger.warning(f"从豆瓣链接获取海报失败: {poster_content}")

                # 优先级2：如果没有豆瓣链接或豆瓣获取失败，尝试从IMDb链接获取
                elif imdb_link and (not images or not images[0]
                                    or "[img]" not in images[0]):
                    self.logger.info(f"尝试从IMDb链接获取海报: {imdb_link}")
                    poster_status, poster_content, description_content, _ = upload_data_movie_info(
                        "", imdb_link)

                    if poster_status and poster_content:
                        # 成功获取到海报，更新images列表
                        if not images:
                            images = [poster_content]
                        else:
                            images[0] = poster_content
                        self.logger.success("成功从IMDb获取到海报")
                    else:
                        self.logger.warning(f"从IMDb链接获取海报失败: {poster_content}")

                # 如果两种方式都失败了，记录日志
                if not images or not images[0] or "[img]" not in images[0]:
                    self.logger.warning("无法从豆瓣或IMDb获取到有效的海报")
            else:
                self.logger.info("当前海报有效，无需重新获取")

                # 即使海报有效，如果有豆瓣链接也可以尝试获取IMDb链接
                if douban_link and not imdb_link:
                    poster_status, poster_content, description_content, extracted_imdb = upload_data_movie_info(
                        douban_link, "")
                    if extracted_imdb:
                        imdb_link = extracted_imdb
                        self.logger.info(f"通过豆瓣提取到IMDb链接: {imdb_link}")

                        # 将IMDb链接添加到简介中
                        imdb_info = f"◎IMDb链接　[url={imdb_link}]{imdb_link}[/url]"
                        douban_pattern = r"◎豆瓣链接　\[url=[^\]]+\][^\[]+\[/url\]"
                        if re.search(douban_pattern, body):
                            body = re.sub(
                                douban_pattern,
                                lambda m: m.group(0) + "\n" + imdb_info, body)
                        else:
                            if body:
                                body = f"{body}\n\n{imdb_info}"
                            else:
                                body = imdb_info

            # 重新组装intro字典
            intro = {
                "statement": "\n".join(quotes),
                "poster": images[0] if images else "",
                "body": re.sub(r"\n{2,}", "\n", body),
                "screenshots": "\n".join(images[1:]),
                "removed_ardtudeclarations": ardtu_declarations,
                "imdb_link": imdb_link,
                "douban_link": douban_link,
            }

            # 6. 提取产地信息并添加到source_params中
            full_description_text = f"{intro.get('statement', '')}\n{intro.get('body', '')}"
            origin_info = extract_origin_from_description(
                full_description_text)

            # --- [核心修改结束] ---

            # 处理torrent_filename，去除.torrent扩展名、URL解码并过滤站点信息，以便正确查找视频文件
            import urllib.parse
            processed_torrent_name = urllib.parse.unquote(torrent_filename)
            if processed_torrent_name.endswith('.torrent'):
                processed_torrent_name = processed_torrent_name[:-8]  # 去除.torrent扩展名

            # 过滤掉文件名中的站点信息（如[HDHome]、[HDSpace]等）
            processed_torrent_name = re.sub(r'^\[[^\]]+\]\.', '', processed_torrent_name)

            # 使用upload_data_mediaInfo处理mediainfo
            mediainfo = upload_data_mediaInfo(
                mediaInfo=mediainfo_text
                if mediainfo_text else "未找到 Mediainfo 或 BDInfo",
                save_path=self.save_path,
                content_name=processed_torrent_name)

            # 提取产地信息并更新到source_params中（如果还没有）
            if "产地" not in source_params or not source_params["产地"]:
                full_description_text = f"{intro.get('statement', '')}\n{intro.get('body', '')}"
                origin_info = extract_origin_from_description(
                    full_description_text)
                source_params["产地"] = origin_info

            # 如果source_params中缺少基本信息，从网页中提取
            if not source_params.get("类型") or not source_params.get("媒介"):
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

                # 只更新缺失的字段
                if not source_params.get("类型"):
                    source_params["类型"] = type_match.group(
                        1) if type_match else type_text.split("/")[-1]
                if not source_params.get("媒介"):
                    source_params["媒介"] = basic_info_dict.get("媒介")
                if not source_params.get("编码"):
                    source_params["编码"] = basic_info_dict.get("编码")
                if not source_params.get("音频编码"):
                    source_params["音频编码"] = basic_info_dict.get("音频编码")
                if not source_params.get("分辨率"):
                    source_params["分辨率"] = basic_info_dict.get("分辨率")
                if not source_params.get("制作组"):
                    source_params["制作组"] = basic_info_dict.get("制作组")
                if not source_params.get("标签"):
                    source_params["标签"] = tags
            # 确保source_params始终存在
            if "source_params" not in locals() or not source_params:
                source_params = {
                    "类型": "",
                    "媒介": None,
                    "编码": None,
                    "音频编码": None,
                    "分辨率": None,
                    "制作组": None,
                    "标签": [],
                    "产地": ""
                }

            # 此处已提前下载种子文件，无需重复下载

            # --- [新增] 开始: 构建最终发布参数预览对象 ---
            try:
                # 1. 将 title_components 列表转换为更易于使用的字典
                title_params = {
                    item["key"]: item["value"]
                    for item in title_components if item.get("value")
                }

                # 2. 模拟拼接最终的主标题 (逻辑与 sites/*.py 中的 _build_title 一致)
                order = [
                    "主标题",
                    "年份",
                    "季集",
                    "剧集状态",
                    "发布版本",
                    "分辨率",
                    "媒介",
                    "片源平台",
                    "视频编码",
                    "视频格式",
                    "HDR格式",
                    "色深",
                    "帧率",
                    "音频编码",
                ]
                title_parts = []
                for key in order:
                    value = title_params.get(key)
                    if value:
                        title_parts.append(
                            " ".join(map(str, value)) if isinstance(
                                value, list) else str(value))

                raw_main_part = " ".join(filter(None, title_parts))
                main_part = re.sub(r'(?<!\d)\.(?!\d)', ' ', raw_main_part)
                main_part = re.sub(r'\s+', ' ', main_part).strip()
                release_group = title_params.get("制作组", "NOGROUP")
                if "N/A" in release_group: release_group = "NOGROUP"

                # 对特殊制作组进行处理，不需要添加前缀连字符
                special_groups = ["MNHD-FRDS", "mUHD-FRDS"]
                if release_group in special_groups:
                    preview_title = f"{main_part} {release_group}"
                else:
                    preview_title = f"{main_part}-{release_group}"

                # 3. 组合最终的简介 (逻辑与 sites/*.py 中的 _build_description 一致)
                full_description = (f"{intro.get('statement', '')}\n"
                                    f"{intro.get('poster', '')}\n"
                                    f"{intro.get('body', '')}\n"
                                    f"{intro.get('screenshots', '')}")

                # 4. 整合所有来源的标签
                source_tags = set(source_params.get("标签") or [])
                mediainfo_tags = set(extract_tags_from_mediainfo(mediainfo))
                all_tags = sorted(list(source_tags.union(mediainfo_tags)))

                # 5. 组装最终的预览字典 (不包含Mediainfo和完整简介，保持简洁)
                final_publish_parameters = {
                    "主标题 (预览)": preview_title,
                    "副标题": subtitle,
                    "IMDb链接": imdb_link,
                    "类型": source_params.get("类型", "N/A"),
                    "媒介": title_params.get("媒介", "N/A"),
                    "视频编码": title_params.get("视频编码", "N/A"),
                    "音频编码": title_params.get("音频编码", "N/A"),
                    "分辨率": title_params.get("分辨率", "N/A"),
                    "制作组": title_params.get("制作组", "N/A"),
                    "产地": source_params.get("产地", "N/A"),
                    "标签 (综合)": all_tags,
                    # 注: 不包含Mediainfo和完整简介，保持预览简洁
                }

                # 6. 构建完整的发布参数用于预览
                # 创建一个模拟的upload_payload用于参数预构建
                upload_payload = {
                    "title_components": title_components,
                    "subtitle": subtitle,
                    "imdb_link": imdb_link,
                    "intro": intro,
                    "mediainfo": mediainfo,
                    "source_params": source_params,
                    "modified_torrent_path": ""  # 临时占位符
                }

                # 提取映射前的原始参数用于前端展示（无论是否有目标站点信息）
                raw_params_for_preview = {
                    "final_main_title":
                    final_publish_parameters.get("主标题 (预览)", ""),
                    "subtitle":
                    subtitle,
                    "imdb_link":
                    imdb_link,
                    "type":
                    source_params.get("类型", ""),
                    "medium":
                    title_params.get("媒介", ""),
                    "video_codec":
                    title_params.get("视频编码", ""),
                    "audio_codec":
                    title_params.get("音频编码", ""),
                    "resolution":
                    title_params.get("分辨率", ""),
                    "release_group":
                    title_params.get("制作组", ""),
                    "source":
                    source_params.get("产地", "")
                    or title_params.get("片源平台", ""),
                    "tags":
                    list(all_tags)
                }

                # 如果有目标站点信息，预构建完整的发布参数
                complete_publish_params = {}
                if self.target_site:
                    from uploaders.base import BaseUploader
                    complete_publish_params = BaseUploader.prepare_publish_params(
                        site_name=self.target_site["site"],
                        site_info=self.target_site,
                        upload_payload=upload_payload)
            except Exception as e:
                self.logger.error(f"构建发布参数预览时出错: {e}")
                final_publish_parameters = {"error": "构建预览失败，请检查日志。"}
                complete_publish_params = {"error": f"构建完整参数失败: {e}"}
            # --- [新增] 结束 ---

            self.logger.info("--- [步骤1] 种子信息获取和解析完成 ---")

            # 将新构建的预览对象添加到返回数据中
            review_data_payload = {
                "original_main_title":
                original_main_title,
                "title_components":
                title_components,
                "subtitle":
                subtitle,
                "imdb_link":
                imdb_link,
                "intro":
                intro,
                "mediainfo":
                mediainfo,
                "source_params":
                source_params,
                # --- [新增] ---
                "final_publish_parameters":
                final_publish_parameters,
                "complete_publish_params":
                complete_publish_params,
                "raw_params_for_preview":
                raw_params_for_preview,
                # 添加特殊提取器处理标志
                "special_extractor_processed":
                getattr(self, '_special_extractor_processed', False)
            }

            return {
                "review_data": review_data_payload,
                "original_torrent_path": original_torrent_path,
                "logs": self.log_handler.get_logs(),
            }
        except Exception as e:
            self.logger.error(f"获取信息过程中发生错误: {e}")
            self.logger.debug(traceback.format_exc())
            # self.cleanup() # 此处不清理，因为原始种子文件需要被缓存
            return {"logs": self.log_handler.get_logs()}

    def publish_prepared_torrent(self, upload_data, modified_torrent_path):
        """第二步：使用准备好的信息和文件执行上传。"""
        try:
            self.logger.info(
                f"--- [步骤2] 开始发布种子到 {self.target_site['nickname']} ---")
            upload_payload = upload_data.copy()
            upload_payload["modified_torrent_path"] = modified_torrent_path

            self.logger.info(
                f"正在加载目标站点上传模块: uploaders.sites.{self.TARGET_UPLOAD_MODULE}")
            # Use the base uploader's static upload method instead of calling directly on the module
            from uploaders.base import BaseUploader
            result, message = BaseUploader.upload(
                site_name=self.target_site["site"],
                site_info=self.target_site,
                upload_payload=upload_payload)
            if result:
                self.logger.success(f"发布成功！站点消息: {message}")
            else:
                self.logger.error(f"发布失败！站点消息: {message}")

            self.logger.info("--- [步骤2] 任务执行完毕 ---")
            final_url = None
            if url_match := re.search(r"(https?://[^\s]+details\.php\?id=\d+)",
                                      str(message)):
                final_url = url_match.group(1)

            return {
                "success": result,
                "logs": self.log_handler.get_logs(),
                "url": final_url
            }
        except Exception as e:
            self.logger.error(f"发布过程中发生致命错误: {e}")
            self.logger.debug(traceback.format_exc())
            return {
                "success": False,
                "logs": self.log_handler.get_logs(),
                "url": None
            }
