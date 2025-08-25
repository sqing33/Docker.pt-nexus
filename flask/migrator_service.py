# migrator_service.py

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


# --- 禁用 InsecureRequestWarning 警告 ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class LoguruHandler(StringIO):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []

    def write(self, message):
        self.records.append(message.strip())

    def get_logs(self):
        return "\n".join(self.records)


# [关键修改] 辅助函数，智能处理 URL 协议头
def _ensure_scheme(url):
    """
    智能处理 URL 字符串，如果缺少协议头则添加 https:// 作为安全默认值。
    如果 URL 已包含 http:// 或 https://，则保持不变。
    """
    if not url:
        return ""
    # 如果用户在配置中明确指定了 http:// 或 https://，则尊重该配置
    if url.startswith("http://") or url.startswith("https://"):
        return url
    # 否则，对于没有指定协议的域名，默认添加 https://
    return f"https://{url}"


class TorrentMigrator:
    """
    一个用于将种子从一个PT站点迁移到另一个站点的工具类。
    """

    def __init__(self, source_site_info, target_site_info, search_term):
        self.source_site = source_site_info
        self.target_site = target_site_info
        self.search_term = search_term

        # 使用新的 _ensure_scheme 函数来规范化 URL，它现在会保留 http://
        self.SOURCE_BASE_URL = _ensure_scheme(self.source_site.get("base_url"))
        self.TARGET_BASE_URL = _ensure_scheme(self.target_site.get("base_url"))

        self.SOURCE_NAME = self.source_site["nickname"]
        self.SOURCE_COOKIE = self.source_site["cookie"]
        self.TARGET_COOKIE = self.target_site["cookie"]
        self.TARGET_PASSKEY = self.target_site["passkey"]

        self.TARGET_UPLOAD_MODULE = self.target_site["nickname"]
        # [关键修改] 移除强制替换，确保 tracker URL 的协议与 base_url 一致
        self.TARGET_TRACKER_URL = f"{self.TARGET_BASE_URL}/announce.php"

        self.main_title = None
        self.basic_info = None
        self.tags = None
        self.mediainfo = None
        self.subtitle = None
        self.imdb_link = None
        self.intro = None
        self.source_params = None
        self.temp_files = []

        session = requests.Session()
        session.verify = False
        self.scraper = cloudscraper.create_scraper(sess=session)

        self.log_handler = LoguruHandler()
        self.logger = logger
        self.logger.remove()
        self.logger.add(
            self.log_handler, format="{time:HH:mm:ss} - {level} - {message}", level="INFO"
        )

    def cleanup(self):
        """清理所有临时文件"""
        for f in self.temp_files:
            try:
                os.remove(f)
                self.logger.info(f"已清理临时文件: {f}")
            except OSError as e:
                self.logger.warning(f"清理临时文件 {f} 失败: {e}")

    # 将HTML标签转换为BBCode
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

    # 在源站点搜索并获取种子ID
    def search_and_get_torrent_id(self, torrent_name):
        search_url = f"{self.SOURCE_BASE_URL}/torrents.php"
        params = {"incldead": "1", "search": torrent_name, "search_area": "0"}
        self.logger.info(f"正在源站 '{self.SOURCE_NAME}' 搜索种子: '{torrent_name}'")
        try:
            response = self.scraper.get(
                search_url, headers={"Cookie": self.SOURCE_COOKIE}, params=params, timeout=60
            )
            response.raise_for_status()
            response.encoding = "utf-8"
            self.logger.success("搜索请求成功！")

            soup = BeautifulSoup(response.text, "html.parser")
            link = soup.find("a", title=torrent_name) or soup.select_one(
                'table.torrentname a[href*="details.php?id="]'
            )
            if isinstance(link, Tag):
                href = link.get("href")
                if isinstance(href, str) and (match := re.search(r"id=(\d+)", href)):
                    torrent_id = match.group(1)
                    self.logger.success(f"成功找到种子ID: {torrent_id}")
                    return torrent_id

            self.logger.warning("未在搜索结果中找到完全匹配的种子。")
            return None
        except Exception as e:
            self.logger.opt(exception=True).error(f"搜索过程中发生错误: {e}")
            return None

    # 获取种子详情并下载种子文件
    def get_details_and_download(self, torrent_id):
        details_url = f"{self.SOURCE_BASE_URL}/details.php"
        params = {"id": torrent_id, "hit": "1"}
        self.logger.info(f"正在获取种子(ID: {torrent_id})的详细信息并下载...")
        try:
            response = self.scraper.get(
                details_url, headers={"Cookie": self.SOURCE_COOKIE}, params=params, timeout=60
            )
            response.raise_for_status()
            response.encoding = "utf-8"
            self.logger.success("详情页请求成功！")
            soup = BeautifulSoup(response.text, "html.parser")

            # --- 解析详情 ---
            h1_top = soup.select_one("h1#top")
            if h1_top and hasattr(h1_top, "stripped_strings"):
                stripped = list(h1_top.stripped_strings)
                self.main_title = stripped[0] if stripped else "未找到"
            else:
                self.main_title = "未找到"

            basic_info_header = soup.find("td", string="基本信息")
            basic_info_dict = {}
            if basic_info_header:
                next_td = basic_info_header.find_next_sibling("td")
                if next_td and hasattr(next_td, "stripped_strings"):
                    strings = list(next_td.stripped_strings)
                    basic_info_dict = {
                        s.replace(":", "").replace("：", "").strip(): strings[i + 1]
                        for i, s in enumerate(strings)
                        if (":" in s or "：" in s) and i + 1 < len(strings)
                    }
            self.basic_info = basic_info_dict

            tags_header = soup.find("td", string="标签")
            self.tags = []
            if tags_header:
                next_td = tags_header.find_next_sibling("td")
                if next_td and isinstance(next_td, Tag):
                    self.tags = [s.get_text(strip=True) for s in next_td.find_all("span")]

            mediainfo_pre = soup.select_one("div.spoiler-content pre")
            self.mediainfo = (
                mediainfo_pre.get_text(strip=True)
                if mediainfo_pre and hasattr(mediainfo_pre, "get_text")
                else "未找到"
            )

            descr_container = soup.select_one("div#kdescr")
            self.subtitle = ""
            self.imdb_link = ""
            self.intro = None
            if descr_container:
                full_bbcode = self._html_to_bbcode(descr_container)
                statements = re.findall(r"\[quote\].*?\[/quote\]", full_bbcode, re.DOTALL)
                images = re.findall(r"\[img\].*?\[/img\]", full_bbcode)
                body_text = re.sub(
                    r"\[quote\].*?\[/quote\]|\[img\].*?\[/img\]", "", full_bbcode, flags=re.DOTALL
                )
                body_text = re.sub(r"\n{2,}", "\n", body_text.replace("\r", "")).strip()

                subtitle_td = soup.find("td", class_="rowhead", string="副标题")
                if subtitle_td:
                    next_td = subtitle_td.find_next_sibling("td")
                    if next_td and hasattr(next_td, "get_text"):
                        self.subtitle = next_td.get_text(strip=True)
                imdb_match = re.search(
                    r"(https?://www\.imdb\.com/title/tt\d+)",
                    descr_container.get_text() if hasattr(descr_container, "get_text") else "",
                )
                self.imdb_link = imdb_match.group(1) if imdb_match else ""
                self.intro = {
                    "声明": "\n".join(statements).strip(),
                    "海报": images[0] if images else "",
                    "正文": body_text,
                    "截图": "\n".join(images[1:]).strip(),
                }

            type_text = basic_info_dict.get("类型", "")
            type_match = re.search(r"[\(（](.*?)[\)）]", type_text)
            self.source_params = {
                "类型": type_match.group(1) if type_match else type_text.split("/")[-1],
                "媒介": basic_info_dict.get("媒介"),
                "编码": basic_info_dict.get("编码"),
                "音频编码": basic_info_dict.get("音频编码"),
                "分辨率": basic_info_dict.get("分辨率"),
                "制作组": basic_info_dict.get("制作组"),
                "标签": self.tags,
            }

            # --- 下载种子文件 ---
            download_link_tag = soup.select_one(f'a.index[href^="download.php?id={torrent_id}"]')
            if not download_link_tag:
                self.logger.error("在详情页未找到种子下载链接。")
                return None

            torrent_download_url = f"{self.SOURCE_BASE_URL}/{download_link_tag['href']}"
            self.logger.info("正在下载原始 .torrent 文件...")
            torrent_response = self.scraper.get(
                torrent_download_url, headers={"Cookie": self.SOURCE_COOKIE}, timeout=60
            )
            torrent_response.raise_for_status()

            safe_filename = re.sub(r'[\\/*?:"<>|]', "_", self.main_title)[:150]
            original_torrent_path = f"{safe_filename}.original.torrent"
            with open(original_torrent_path, "wb") as f:
                f.write(torrent_response.content)
            self.logger.success(f"原始种子已保存到: {original_torrent_path}")
            self.temp_files.append(original_torrent_path)

            return original_torrent_path

        except Exception as e:
            self.logger.opt(exception=True).error(f"解析详情或下载种子时发生错误: {e}")
            return None

    def modify_torrent_file(self, original_path):
        self.logger.info(f"正在使用 bencoder 修改 .torrent 文件: {original_path}...")
        try:
            with open(original_path, "rb") as f:
                decoded_torrent = bencoder.decode(f.read())
            self.logger.info("原始种子文件解码成功。")

            new_tracker_url_str = f"{self.TARGET_TRACKER_URL}?passkey={self.TARGET_PASSKEY}"
            new_tracker_url_bytes = new_tracker_url_str.encode("utf-8")
            self.logger.info(f"将设置新的 Tracker URL 为: {new_tracker_url_str}")

            decoded_torrent[b"announce"] = new_tracker_url_bytes
            if b"announce-list" in decoded_torrent:
                del decoded_torrent[b"announce-list"]
                self.logger.info("已移除 'announce-list' (备用Tracker列表) 字段。")
            if b"comment" in decoded_torrent:
                del decoded_torrent[b"comment"]
                self.logger.info("已移除 'comment' (备注) 字段。")

            if b"info" in decoded_torrent:
                info_dict = decoded_torrent[b"info"]
                info_dict[b"private"] = 1
                self.logger.info("已确保 'info' 字典中的 'private' 标记设置为 1。")
                if b"source" in info_dict:
                    del info_dict[b"source"]
                    self.logger.info("已从 'info' 字典中移除 'source' 字段。")
            else:
                self.logger.error("'info' 字典未找到或格式不正确，任务终止。")
                return None

            modified_content = bencoder.encode(decoded_torrent)
            modified_path = original_path.replace(".original.torrent", ".modified.torrent")
            with open(modified_path, "wb") as f:
                f.write(modified_content)

            self.logger.success(f"已成功生成新的种子文件: {modified_path}")
            self.temp_files.append(modified_path)
            return modified_path

        except Exception as e:
            self.logger.opt(exception=True).error(f"修改 .torrent 文件时发生严重错误: {e}")
            return None

    def run(self):
        """执行完整的迁移流程"""
        try:
            self.logger.info("--- 种子迁移任务启动 ---")
            self.logger.info(f"源站: {self.SOURCE_NAME}, 目标站: {self.target_site['nickname']}")

            torrent_id = None
            if self.search_term.isdigit():
                self.logger.info(f"输入的是种子ID: {self.search_term}")
                torrent_id = self.search_term
            else:
                self.logger.info(f"输入的是种子名称，开始搜索...")
                torrent_id = self.search_and_get_torrent_id(torrent_name=self.search_term)

            if not torrent_id:
                raise Exception("未能获取到种子ID，请检查种子名称或ID是否正确。")

            original_torrent_path = self.get_details_and_download(torrent_id)
            if not original_torrent_path:
                raise Exception("获取详情或下载种子失败。")

            modified_torrent_path = self.modify_torrent_file(original_torrent_path)
            if not modified_torrent_path:
                raise Exception("修改种子文件失败。")

            self.logger.info("种子信息解析和文件修改完成，准备上传...")

            try:
                self.logger.info(f"正在加载目标站点上传模块: sites.{self.TARGET_UPLOAD_MODULE}")
                upload_module = importlib.import_module(f"sites.{self.TARGET_UPLOAD_MODULE}")
                self.logger.success("上传模块加载成功！")
            except ImportError:
                raise Exception(f"未找到名为 'sites/{self.TARGET_UPLOAD_MODULE}.py' 的上传脚本。")

            result, message = upload_module.upload(
                site_info=self.target_site,
                source_params=self.source_params,
                modified_torrent_path=modified_torrent_path,
                main_title=self.main_title,
                subtitle=self.subtitle,
                imdb_link=self.imdb_link,
                intro=self.intro,
                mediainfo=self.mediainfo,
            )

            if result:
                self.logger.success(f"发布成功！站点消息: {message}")
            else:
                self.logger.error(f"发布失败！站点消息: {message}")

            self.logger.info("--- 任务执行完毕 ---")
            return {"success": True, "logs": self.log_handler.get_logs()}

        except Exception as e:
            self.logger.error(f"迁移过程中发生致命错误: {e}")
            self.logger.debug(traceback.format_exc())
            self.logger.info("--- 任务异常终止 ---")
            return {"success": False, "logs": self.log_handler.get_logs()}
        finally:
            self.cleanup()
