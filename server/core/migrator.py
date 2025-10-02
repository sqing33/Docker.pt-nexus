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
import yaml
import urllib.parse
from io import StringIO
from typing import Dict, Any, Optional, List
from config import TEMP_DIR, DATA_DIR
from utils import ensure_scheme, upload_data_mediaInfo, upload_data_title, extract_tags_from_mediainfo, extract_origin_from_description

# 导入种子参数模型
from models.seed_parameter import SeedParameter

# 导入新的Extractor和ParameterMapper
from core.extractors.extractor import Extractor, ParameterMapper

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
    """重构后的TorrentMigrator类，使用三层解耦模型实现参数标准化。"""

    def __init__(self,
                 source_site_info,
                 target_site_info,
                 search_term="",
                 save_path="",
                 torrent_name="",
                 config_manager=None,
                 db_manager=None,
                 downloader_id=None):
        self.source_site = source_site_info
        self.target_site = target_site_info
        self.search_term = search_term
        self.save_path = save_path
        self.torrent_name = torrent_name
        self.config_manager = config_manager
        self.db_manager = db_manager
        self.downloader_id = downloader_id

        self.SOURCE_BASE_URL = ensure_scheme(self.source_site.get("base_url"))
        self.SOURCE_NAME = self.source_site["nickname"]
        self.SOURCE_SITE_CODE = self.source_site["site"]  # 添加英文站点名
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

        # 初始化新的Extractor和ParameterMapper
        self.extractor = Extractor()
        self.parameter_mapper = ParameterMapper()

        # 加载源站点配置（如果存在）
        self.source_config = self._load_source_site_config()

    def _load_source_site_config(self) -> Dict[str, Any]:
        """
        加载源站点的YAML配置文件，用于解析source_parsers
        """
        try:
            # 使用英文站点名构造配置文件名
            config_path = os.path.join(
                DATA_DIR,
                f"{self.SOURCE_SITE_CODE.lower().replace(' ', '_').replace('-', '_')}.yaml"
            )
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    return yaml.safe_load(f) or {}
            else:
                self.logger.warning(
                    f"未找到源站点 {self.SOURCE_NAME} ({self.SOURCE_SITE_CODE}) 的配置文件 {config_path}"
                )
                return {}
        except Exception as e:
            self.logger.warning(f"加载源站点配置文件时出错: {e}")
            return {}

    def _download_torrent_file(self, torrent_id: str, temp_dir: str) -> str:
        """
        从源站点下载种子文件并保存到指定目录

        Args:
            torrent_id: 种子ID
            temp_dir: 临时目录路径

        Returns:
            str: 下载的种子文件路径
        """
        try:
            self.logger.info(f"正在从源站点 {self.SOURCE_NAME} 下载种子文件 (ID: {torrent_id})...")

            # 获取代理配置
            proxies = self._get_proxies(self.SOURCE_PROXY)
            if proxies:
                self.logger.info(f"使用代理下载种子文件: {proxies}")

            # 构造下载链接
            download_url = f"{self.SOURCE_BASE_URL}/download.php?id={torrent_id}"

            # 下载种子文件
            torrent_response = self.scraper.get(
                download_url,
                headers={"Cookie": self.SOURCE_COOKIE},
                timeout=60,
                proxies=proxies,
            )
            torrent_response.raise_for_status()

            # 从响应头中尝试获取文件名，这是最准确的方式
            content_disposition = torrent_response.headers.get('content-disposition')
            torrent_filename = f"{torrent_id}.torrent"  # 默认文件名
            if content_disposition:
                # 尝试匹配filename*（支持UTF-8编码）和filename
                filename_match = re.search(r'filename\*="?UTF-8\'\'([^"]+)"?',
                                           content_disposition, re.IGNORECASE)
                if filename_match:
                    torrent_filename = filename_match.group(1)
                    # URL解码文件名（UTF-8编码）
                    torrent_filename = urllib.parse.unquote(torrent_filename,
                                                            encoding='utf-8')
                else:
                    # 尝试匹配普通的filename
                    filename_match = re.search(r'filename="?([^"]+)"?',
                                               content_disposition)
                    if filename_match:
                        torrent_filename = filename_match.group(1)
                        # URL解码文件名
                        torrent_filename = urllib.parse.unquote(
                            torrent_filename)

            # 保存种子文件到临时目录
            torrent_path = os.path.join(temp_dir, torrent_filename)
            with open(torrent_path, "wb") as f:
                f.write(torrent_response.content)

            self.logger.success(f"种子文件已下载并保存到: {torrent_path}")
            return torrent_path

        except Exception as e:
            self.logger.error(f"下载种子文件时出错: {e}")
            self.logger.debug(traceback.format_exc())
            return ""

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
        special_sites = ["人人", "不可说", "憨憨"]
        if self.SOURCE_NAME in special_sites:
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
        # 使用新的Extractor类来处理提取
        return self.extractor.extract(soup, self.SOURCE_NAME, torrent_id)

    def _standardize_parameters(
            self, extracted_data: Dict[str, Any],
            title_components: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        使用ParameterMapper将提取的数据映射为标准化参数

        Args:
            extracted_data: 从源站点提取的原始数据
            title_components: 解析后的标题组件

        Returns:
            standardized_params: 标准化后的参数字典
        """
        # 将标题组件添加到提取的数据中，以便ParameterMapper可以处理
        extracted_data_with_components = extracted_data.copy()
        extracted_data_with_components["title_components"] = title_components

        # 使用ParameterMapper进行参数映射
        standardized_params = self.parameter_mapper.map_parameters(
            self.SOURCE_NAME, self.SOURCE_SITE_CODE,
            extracted_data_with_components)

        return standardized_params

    def prepare_review_data(self):
        """重构后的方法：获取、解析信息，并输出标准化参数。"""
        try:
            self.logger.info(f"--- [步骤1] 开始获取种子信息 (源: {self.SOURCE_NAME}) ---")
            print(f"开始prepare_review_data处理，源站点: {self.SOURCE_NAME}")
            torrent_id = (self.search_term if self.search_term.isdigit() else
                          self.search_and_get_torrent_id(self.search_term))
            if not torrent_id:
                raise Exception("未能获取到种子ID，请检查种子名称或ID是否正确。")

            # 初始化种子参数模型
            # 使用构造函数传入的 db_manager
            if not self.db_manager:
                raise Exception("数据库管理器未初始化，无法保存种子参数。")
            seed_param_model = SeedParameter(self.db_manager)

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
                # 尝试匹配filename*（支持UTF-8编码）和filename
                filename_match = re.search(r'filename\*="?UTF-8\'\'([^"]+)"?',
                                           content_disposition, re.IGNORECASE)
                if filename_match:
                    torrent_filename = filename_match.group(1)
                    # URL解码文件名（UTF-8编码）
                    torrent_filename = urllib.parse.unquote(torrent_filename,
                                                            encoding='utf-8')
                else:
                    # 尝试匹配普通的filename
                    filename_match = re.search(r'filename="?([^"]+)"?',
                                               content_disposition)
                    if filename_match:
                        torrent_filename = filename_match.group(1)
                        # URL解码文件名
                        torrent_filename = urllib.parse.unquote(
                            torrent_filename)

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

            # 创建以种子名称命名的子目录来保存种子文件和参数
            safe_filename_base = re.sub(r'[\\/*?:"<>|]', "_",
                                        original_main_title)[:150]
            torrent_dir = os.path.join(TEMP_DIR, safe_filename_base)
            os.makedirs(torrent_dir, exist_ok=True)

            # 保存原始种子文件到指定文件夹
            original_torrent_path = os.path.join(torrent_dir,
                                                 f"{torrent_filename}")
            with open(original_torrent_path, "wb") as f:
                f.write(torrent_response.content)
            self.temp_files.append(original_torrent_path)

            self.logger.info(f"种子文件已保存到: {original_torrent_path}")

            # 调用 upload_data_title 时，传入主标题和种子文件名
            title_components = upload_data_title(original_main_title,
                                                 torrent_filename)
            # --- [核心修改 1] 结束 ---

            if not title_components:
                self.logger.warning("主标题解析失败，将使用原始标题作为回退。")
                title_components = [{
                    "key": "主标题",
                    "value": original_main_title
                }]
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
            processed_torrent_name = urllib.parse.unquote(torrent_filename)
            if processed_torrent_name.endswith('.torrent'):
                processed_torrent_name = processed_torrent_name[:
                                                                -8]  # 去除.torrent扩展名

            # 过滤掉文件名中的站点信息（如[HDHome]、[HDSpace]等）
            processed_torrent_name = re.sub(r'^\[[^\]]+\]\.', '',
                                            processed_torrent_name)

            # 使用upload_data_mediaInfo处理mediainfo
            mediainfo = upload_data_mediaInfo(
                mediaInfo=mediainfo_text
                if mediainfo_text else "未找到 Mediainfo 或 BDInfo",
                save_path=self.save_path,
                torrent_name=processed_torrent_name)

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
                if not source_params.get("视频编码"):
                    # 优先获取"视频编码"，如果没有则获取"编码"
                    source_params["视频编码"] = basic_info_dict.get("视频编码") or basic_info_dict.get("编码")
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
                    "视频编码": None,
                    "音频编码": None,
                    "分辨率": None,
                    "制作组": None,
                    "标签": [],
                    "产地": ""
                }

            # 此处已提前下载种子文件，无需重复下载

            # --- [三层解耦模型核心实现] 开始: 构建标准化参数 ---
            # 使用三层解耦模型标准化参数
            standardized_params = self._standardize_parameters(
                extracted_data, title_components)

            # [新增] 音频编码择优逻辑
            try:
                # 1. 单独为标题组件中的音频编码进行一次标准化
                audio_from_title_raw = next(
                    (item['value'] for item in title_components
                     if item.get('key') == '音频编码'), None)
                if audio_from_title_raw:
                    # 借用 ParameterMapper 的能力来标准化这个单独的值
                    temp_extracted = {
                        'source_params': {
                            '音频编码': audio_from_title_raw
                        }
                    }
                    temp_standardized = self.parameter_mapper.map_parameters(
                        self.SOURCE_NAME, self.SOURCE_SITE_CODE,
                        temp_extracted)
                    audio_from_title_standard = temp_standardized.get(
                        'audio_codec')

                    # 2. 对比层级并覆盖
                    if audio_from_title_standard:
                        audio_from_params_standard = standardized_params.get(
                            'audio_codec')

                        title_rank = AUDIO_CODEC_HIERARCHY.get(
                            audio_from_title_standard, 0)
                        params_rank = AUDIO_CODEC_HIERARCHY.get(
                            audio_from_params_standard, -1)

                        if title_rank > params_rank:
                            self.logger.info(
                                f"音频编码优化：使用标题中的 '{audio_from_title_standard}' (层级 {title_rank}) 覆盖了参数中的 '{audio_from_params_standard}' (层级 {params_rank})。"
                            )
                            standardized_params[
                                'audio_codec'] = audio_from_title_standard
            except Exception as e:
                self.logger.warning(f"音频编码择优处理时发生错误: {e}")
            # [新增结束]

            # 输出标准化参数以供前端预览
            final_publish_parameters = {
                "主标题 (预览)": standardized_params.get("title", ""),
                "副标题": subtitle,
                "IMDb链接": standardized_params.get("imdb_link", ""),
                "类型": standardized_params.get("type", ""),
                "媒介": standardized_params.get("medium", ""),
                "视频编码": standardized_params.get("video_codec", ""),
                "音频编码": standardized_params.get("audio_codec",
                                                ""),  # [注意] 这里现在会使用优化后的值
                "分辨率": standardized_params.get("resolution", ""),
                "制作组": standardized_params.get("team", ""),
                "产地": standardized_params.get("source", ""),
                "标签": standardized_params.get("tags", []),
            }

            # 构建完整的发布参数用于预览（兼容现有BaseUploader）
            complete_publish_params = {
                "title_components": title_components,
                "subtitle": subtitle,
                "imdb_link": standardized_params.get("imdb_link", ""),
                "douban_link": standardized_params.get("douban_link", ""),
                "intro": standardized_params.get("description", {}),
                "mediainfo": mediainfo,
                "source_params": source_params,
                "modified_torrent_path": "",  # 临时占位符
                # 添加标准化参数供预览
                "standardized_params": standardized_params
            }

            # 创建前端预览参数
            raw_params_for_preview = {
                "final_main_title": standardized_params.get("title", ""),
                "subtitle": subtitle,
                "imdb_link": standardized_params.get("imdb_link", ""),
                "type": standardized_params.get("type", ""),
                "medium": standardized_params.get("medium", ""),
                "video_codec": standardized_params.get("video_codec", ""),
                "audio_codec": standardized_params.get("audio_codec", ""),
                "resolution": standardized_params.get("resolution", ""),
                "release_group": standardized_params.get("team", ""),
                "source": standardized_params.get("source", ""),
                "tags": standardized_params.get("tags", [])
            }
            # --- [三层解耦模型核心实现] 结束 ---

            self.logger.info("--- [步骤1] 种子信息获取和解析完成 ---")

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
                # 标准化参数
                "standardized_params":
                standardized_params,
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

            # 获取源站点种子的 hash 值
            hash = seed_param_model.search_torrent_hash(
                self.torrent_name, self.SOURCE_NAME)

            # 从torrents表中获取下载器ID
            downloader_id_from_db = None
            if hash and self.db_manager:
                try:
                    conn = self.db_manager._get_connection()
                    cursor = self.db_manager._get_cursor(conn)
                    ph = self.db_manager.get_placeholder()

                    # 查询torrents表中对应的下载器ID
                    if self.db_manager.db_type == "postgresql":
                        cursor.execute(
                            "SELECT downloader_id FROM torrents WHERE hash = %s",
                            (hash,)
                        )
                    else:  # mysql and sqlite
                        cursor.execute(
                            f"SELECT downloader_id FROM torrents WHERE hash = {ph}",
                            (hash,)
                        )

                    result = cursor.fetchone()
                    if result:
                        downloader_id_from_db = dict(result).get("downloader_id")

                    cursor.close()
                    conn.close()
                except Exception as e:
                    self.logger.error(f"获取下载器ID时出错: {e}")

            # 如果从数据库未获取到下载器ID，尝试使用构造函数中传入的下载器ID
            final_downloader_id = downloader_id_from_db or self.downloader_id

            # 处理种子名称：去除 .torrent 后缀
            torrent_name_without_ext = self.torrent_name
            if torrent_name_without_ext.lower().endswith('.torrent'):
                torrent_name_without_ext = torrent_name_without_ext[:-8]  # 去除 .torrent (8个字符)

            # 从title_components中提取标题拆解的各项参数（title_components已在方法开头定义）

            # 1. 先构建包含非标准化信息的字典
            seed_parameters = {
                "name": torrent_name_without_ext,  # 添加去除后缀的种子名称
                "title": original_main_title,
                "subtitle": subtitle,
                "imdb_link": imdb_link,
                "douban_link": douban_link,
                "poster": intro.get("poster"),
                "screenshots": intro.get("screenshots"),
                "statement": intro.get("statement", "").strip(),
                "body": intro.get("body", "").strip(),
                "mediainfo": mediainfo,
                # [修正] 从 standardized_params 获取已经标准化的标签
                "tags": standardized_params.get("tags", []),

                # 保存完整的标题组件数据
                "title_components": title_components,

                # 保存被过滤掉的ARDTU声明内容
                "removed_ardtudeclarations": intro.get("removed_ardtudeclarations", []),
            }

            # 2. 将 standardized_params 中所有标准化的键值对合并进来。
            #    这里的 .get() 会返回 'category.movie' 这样的完整字符串。
            seed_parameters.update({
                "nickname":
                self.SOURCE_NAME,
                "save_path":
                self.save_path,
                "type":
                standardized_params.get("type"),
                "medium":
                standardized_params.get("medium"),
                "video_codec":
                standardized_params.get("video_codec"),
                "audio_codec":
                standardized_params.get("audio_codec"),
                "resolution":
                standardized_params.get("resolution"),
                "team":
                standardized_params.get("team"),
                "source":
                standardized_params.get("source"),
                # 移除单独的processing参数保存，统一使用source参数
                "downloader_id":
                final_downloader_id  # 添加下载器ID
            })
            # ------------------------------------------------------------------------------------------

            # 保存到数据库（优先）和JSON文件（后备），使用英文站点名作为标识
            save_result = seed_param_model.save_parameters(
                hash, torrent_id, self.SOURCE_SITE_CODE, seed_parameters)
            if save_result:
                self.logger.info(
                    f"种子参数(使用标准化键)已保存: {hash} from {self.SOURCE_NAME} ({self.SOURCE_SITE_CODE})"
                )
            else:
                self.logger.warning(
                    f"种子参数(使用标准化键)保存失败: {hash} from {self.SOURCE_NAME} ({self.SOURCE_SITE_CODE})"
                )

            return {
                "review_data": review_data_payload,
                "original_torrent_path": original_torrent_path,
                "torrent_dir": torrent_dir,  # 返回种子目录路径以便发种时查找文件
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
            from core.uploaders.uploader import BaseUploader
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
