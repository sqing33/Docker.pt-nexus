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


def _ensure_scheme(url):
    """
    智能处理 URL 字符串，如果缺少协议头则添加 https:// 作为安全默认值。
    如果 URL 已包含 http:// 或 https://，则保持不变。
    """
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return f"https://{url}"


class TorrentMigrator:
    """
    一个用于将种子从一个PT站点迁移到另一个站点的工具类。
    """

    def __init__(self, source_site_info, target_site_info, search_term=""):
        self.source_site = source_site_info
        self.target_site = target_site_info
        self.search_term = search_term

        self.SOURCE_BASE_URL = _ensure_scheme(self.source_site.get("base_url"))
        self.TARGET_BASE_URL = _ensure_scheme(self.target_site.get("base_url"))

        self.SOURCE_NAME = self.source_site["nickname"]
        self.SOURCE_COOKIE = self.source_site["cookie"]
        self.TARGET_COOKIE = self.target_site.get("cookie")
        self.TARGET_PASSKEY = self.target_site.get("passkey")
        self.TARGET_UPLOAD_MODULE = self.target_site["site"]

        self.TARGET_TRACKER_URL = f"{self.TARGET_BASE_URL}/announce.php"

        self.temp_files = []
        session = requests.Session()
        session.verify = False
        self.scraper = cloudscraper.create_scraper(sess=session)

        self.log_handler = LoguruHandler()
        self.logger = logger
        self.logger.remove()
        self.logger.add(
            self.log_handler, format="{time:HH:mm:ss} - {level} - {message}", level="DEBUG"
        )

    def cleanup(self):
        """清理所有临时文件"""
        for f in self.temp_files:
            try:
                os.remove(f)
                self.logger.info(f"已清理临时文件: {f}")
            except OSError as e:
                self.logger.warning(f"清理临时文件 {f} 失败: {e}")

    def _html_to_bbcode(self, tag):
        # ... (This function remains unchanged)
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

    def search_and_get_torrent_id(self, torrent_name):
        # ... (This function remains unchanged)
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

    def modify_torrent_file(self, original_path, main_title):
        # ... (This function remains mostly unchanged)
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

            safe_filename = re.sub(r'[\\/*?:"<>|]', "_", main_title)[:150]
            modified_path = f"{safe_filename}.modified.torrent"

            with open(modified_path, "wb") as f:
                f.write(modified_content)

            self.logger.success(f"已成功生成新的种子文件: {modified_path}")
            self.temp_files.append(modified_path)
            return modified_path

        except Exception as e:
            self.logger.opt(exception=True).error(f"修改 .torrent 文件时发生严重错误: {e}")
            return None

    def prepare_for_upload(self):
        """
        第一步：获取、解析和准备所有信息，但不上传。
        """
        try:
            self.logger.info("--- [步骤1] 开始获取种子信息 ---")
            self.logger.info(f"源站: {self.SOURCE_NAME}, 目标站: {self.target_site['nickname']}")

            torrent_id = (
                self.search_term
                if self.search_term.isdigit()
                else self.search_and_get_torrent_id(self.search_term)
            )
            if not torrent_id:
                raise Exception("未能获取到种子ID，请检查种子名称或ID是否正确。")

            self.logger.info(f"正在获取种子(ID: {torrent_id})的详细信息并下载...")
            details_url = f"{self.SOURCE_BASE_URL}/details.php"
            params = {"id": torrent_id, "hit": "1"}
            response = self.scraper.get(
                details_url, headers={"Cookie": self.SOURCE_COOKIE}, params=params, timeout=60
            )
            response.raise_for_status()
            response.encoding = "utf-8"
            self.logger.success("详情页请求成功！")
            soup = BeautifulSoup(response.text, "html.parser")

            # --- 解析所有需要的信息 ---
            h1_top = soup.select_one("h1#top")
            main_title = (
                list(h1_top.stripped_strings)[0]
                if h1_top and hasattr(h1_top, "stripped_strings")
                else "未找到标题"
            )

            subtitle_td = soup.find("td", class_="rowhead", string="副标题")
            subtitle = (
                subtitle_td.find_next_sibling("td").get_text(strip=True)
                if subtitle_td and subtitle_td.find_next_sibling("td")
                else ""
            )

            descr_container = soup.select_one("div#kdescr")
            imdb_match = (
                re.search(r"(https?://www\.imdb\.com/title/tt\d+)", descr_container.get_text())
                if descr_container
                else None
            )
            imdb_link = imdb_match.group(1) if imdb_match else ""

            intro = {}
            if descr_container:
                full_bbcode = self._html_to_bbcode(descr_container)
                statements = re.findall(r"\[quote\].*?\[/quote\]", full_bbcode, re.DOTALL)
                images = re.findall(r"\[img\].*?\[/img\]", full_bbcode)
                body_text = re.sub(
                    r"\[quote\].*?\[/quote\]|\[img\].*?\[/img\]", "", full_bbcode, flags=re.DOTALL
                )
                body_text = re.sub(r"\n{2,}", "\n", body_text.replace("\r", "")).strip()
                intro = {
                    "statement": "\n".join(statements).strip(),
                    "poster": images[0] if images else "",
                    "body": body_text,
                    "screenshots": "\n".join(images[1:]).strip(),
                }

            mediainfo_pre = soup.select_one("div.spoiler-content pre")
            mediainfo = mediainfo_pre.get_text(strip=True) if mediainfo_pre else "未找到Mediainfo"

            basic_info_header = soup.find("td", string="基本信息")
            basic_info_dict = {}
            if basic_info_header and basic_info_header.find_next_sibling("td"):
                strings = list(basic_info_header.find_next_sibling("td").stripped_strings)
                basic_info_dict = {
                    s.replace(":", "").replace("：", "").strip(): strings[i + 1]
                    for i, s in enumerate(strings)
                    if (":" in s or "：" in s) and i + 1 < len(strings)
                }

            tags_header = soup.find("td", string="标签")
            tags = (
                [
                    s.get_text(strip=True)
                    for s in tags_header.find_next_sibling("td").find_all("span")
                ]
                if tags_header and tags_header.find_next_sibling("td")
                else []
            )

            type_text = basic_info_dict.get("类型", "")
            type_match = re.search(r"[\(（](.*?)[\)）]", type_text)

            # [修正] 将 source_params 字典的键名从英文改为中文，以匹配上传脚本的期望
            source_params = {
                "类型": type_match.group(1) if type_match else type_text.split("/")[-1],
                "媒介": basic_info_dict.get("媒介"),
                "编码": basic_info_dict.get("编码"),
                "音频编码": basic_info_dict.get("音频编码"),
                "分辨率": basic_info_dict.get("分辨率"),
                "制作组": basic_info_dict.get("制作组"),
                "标签": tags,
            }

            # --- 下载并修改种子文件 ---
            download_link_tag = soup.select_one(f'a.index[href^="download.php?id={torrent_id}"]')
            if not download_link_tag:
                raise Exception("在详情页未找到种子下载链接。")

            torrent_download_url = f"{self.SOURCE_BASE_URL}/{download_link_tag['href']}"
            torrent_response = self.scraper.get(
                torrent_download_url, headers={"Cookie": self.SOURCE_COOKIE}, timeout=60
            )
            torrent_response.raise_for_status()

            safe_filename = re.sub(r'[\\/*?:"<>|]', "_", main_title)[:150]
            original_torrent_path = f"{safe_filename}.original.torrent"
            with open(original_torrent_path, "wb") as f:
                f.write(torrent_response.content)
            self.temp_files.append(original_torrent_path)

            modified_torrent_path = self.modify_torrent_file(original_torrent_path, main_title)
            if not modified_torrent_path:
                raise Exception("修改种子文件失败。")

            self.logger.info("--- [步骤1] 种子信息获取和解析完成 ---")

            return {
                "review_data": {
                    "main_title": main_title,
                    "subtitle": subtitle,
                    "imdb_link": imdb_link,
                    "intro": intro,
                    "mediainfo": mediainfo,
                    "source_params": source_params,
                },
                "modified_torrent_path": modified_torrent_path,
                "logs": self.log_handler.get_logs(),
            }
        except Exception as e:
            self.logger.error(f"获取信息过程中发生错误: {e}")
            self.logger.debug(traceback.format_exc())
            self.cleanup()
            return {"logs": self.log_handler.get_logs()}

    def publish_prepared_torrent(self, upload_data, modified_torrent_path):
        """
        第二步：使用准备好的信息和文件执行上传。
        """
        try:
            self.logger.info("--- [步骤2] 开始发布种子 ---")

            # 从前端接收的数据构造上传所需的参数
            main_title = upload_data.get("main_title")
            subtitle = upload_data.get("subtitle")
            imdb_link = upload_data.get("imdb_link")
            intro = upload_data.get("intro")
            mediainfo = upload_data.get("mediainfo")
            source_params = upload_data.get("source_params")

            self.logger.info(f"正在加载目标站点上传模块: sites.{self.TARGET_UPLOAD_MODULE}")
            upload_module = importlib.import_module(f"sites.{self.TARGET_UPLOAD_MODULE}")
            self.logger.success("上传模块加载成功！")

            # 调用站点专属的上传函数
            result, message = upload_module.upload(
                site_info=self.target_site,
                source_params=source_params,
                modified_torrent_path=modified_torrent_path,
                main_title=main_title,
                subtitle=subtitle,
                imdb_link=imdb_link,
                intro=intro,
                mediainfo=mediainfo,
            )

            if result:
                self.logger.success(f"发布成功！站点消息: {message}")
            else:
                self.logger.error(f"发布失败！站点消息: {message}")

            self.logger.info("--- [步骤2] 任务执行完毕 ---")

            # 从日志消息中提取种子URL
            url_match = re.search(r"(https?://[^\s]+details\.php\?id=\d+)", message)
            final_url = url_match.group(1) if url_match else None

            return {"success": result, "logs": self.log_handler.get_logs(), "url": final_url}

        except Exception as e:
            self.logger.error(f"发布过程中发生致命错误: {e}")
            self.logger.debug(traceback.format_exc())
            return {"success": False, "logs": self.log_handler.get_logs(), "url": None}
