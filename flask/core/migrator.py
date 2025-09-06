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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []

    def write(self, message):
        self.records.append(message.strip())

    def get_logs(self):
        return "\n".join(self.records)


class TorrentMigrator:
    """一个用于将种子从一个PT站点迁移到另一个站点的工具类。"""

    def __init__(self,
                 source_site_info,
                 target_site_info,
                 search_term="",
                 save_path=""):
        self.source_site = source_site_info
        self.target_site = target_site_info
        self.search_term = search_term
        self.save_path = save_path

        self.SOURCE_BASE_URL = ensure_scheme(self.source_site.get("base_url"))
        self.SOURCE_NAME = self.source_site["nickname"]
        self.SOURCE_COOKIE = self.source_site["cookie"]

        # 只有在 target_site_info 存在时才初始化目标相关属性
        if self.target_site:
            self.TARGET_BASE_URL = ensure_scheme(
                self.target_site.get("base_url"))
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
        self.logger.add(self.log_handler,
                        format="{time:HH:mm:ss} - {level} - {message}",
                        level="DEBUG")

    def cleanup(self):
        """清理所有临时文件"""
        for f in self.temp_files:
            try:
                os.remove(f)
                self.logger.info(f"已清理临时文件: {f}")
            except OSError as e:
                self.logger.warning(f"清理临时文件 {f} 失败: {e}")

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
        params = {"incldead": "1", "search": torrent_name, "search_area": "0"}
        self.logger.info(f"正在源站 '{self.SOURCE_NAME}' 搜索种子: '{torrent_name}'")
        try:
            response = self.scraper.get(search_url,
                                        headers={"Cookie": self.SOURCE_COOKIE},
                                        params=params,
                                        timeout=60)
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

    def prepare_review_data(self):
        """第一步(新)：获取、解析信息，并下载原始种子文件，但不进行修改。"""
        try:
            self.logger.info(f"--- [步骤1] 开始获取种子信息 (源: {self.SOURCE_NAME}) ---")
            torrent_id = (self.search_term if self.search_term.isdigit() else
                          self.search_and_get_torrent_id(self.search_term))
            if not torrent_id:
                raise Exception("未能获取到种子ID，请检查种子名称或ID是否正确。")

            self.logger.info(f"正在获取种子(ID: {torrent_id})的详细信息...")
            response = self.scraper.get(
                f"{self.SOURCE_BASE_URL}/details.php",
                headers={"Cookie": self.SOURCE_COOKIE},
                params={
                    "id": torrent_id,
                    "hit": "1"
                },
                timeout=60,
            )
            response.raise_for_status()
            response.encoding = "utf-8"

            self.logger.success("详情页请求成功！")

            soup = BeautifulSoup(response.text, "html.parser")

            h1_top = soup.select_one("h1#top")
            original_main_title = list(
                h1_top.stripped_strings)[0] if h1_top else "未找到标题"
            self.logger.info(f"获取到原始主标题: {original_main_title}")

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
            )
            torrent_response.raise_for_status()

            # 从响应头中尝试获取文件名，这是最准确的方式
            content_disposition = torrent_response.headers.get('content-disposition')
            torrent_filename = "default.torrent" # 设置一个默认值
            if content_disposition:
                filename_match = re.search(r'filename="?([^"]+)"?', content_disposition)
                if filename_match:
                    torrent_filename = filename_match.group(1)

            safe_filename_base = re.sub(r'[\\/*?:"<>|]', "_", original_main_title)[:150]
            original_torrent_path = os.path.join(
                TEMP_DIR, f"{safe_filename_base}.original.torrent")
            with open(original_torrent_path, "wb") as f:
                f.write(torrent_response.content)
            self.temp_files.append(original_torrent_path)

            # 调用 upload_data_title 时，传入主标题和种子文件名
            title_components = upload_data_title(original_main_title, torrent_filename)
            # --- [核心修改 1] 结束 ---

            if not title_components:
                self.logger.warning("主标题解析失败，将使用原始标题作为回退。")
                title_components = {"主标题": original_main_title, "无法识别": "解析失败"}
            else:
                self.logger.success("主标题成功解析为参数。")

            subtitle_td = soup.find("td", string=re.compile(r"\s*副标题\s*"))

            # 检查是否找到了标签，并且其后紧跟着一个 td 兄弟节点
            if subtitle_td and subtitle_td.find_next_sibling("td"):
                subtitle = subtitle_td.find_next_sibling("td").get_text(
                    strip=True)
                # 剔除以 "| ARDTU" 开始及之后的所有内容
                subtitle = re.sub(r"\s*\|\s*ARDTU.*", "", subtitle)
            else:
                subtitle = ""
            descr_container = soup.select_one("div#kdescr")

            imdb_link = ""
            douban_link = ""
            if descr_container:
                descr_text = descr_container.get_text()
                if imdb_match := re.search(
                        r"(https?://www\.imdb\.com/title/tt\d+)",
                        descr_text):
                    imdb_link = imdb_match.group(1)
                
                # 提取豆瓣链接（从源站）
                if douban_match := re.search(
                        r"(https?://movie\.douban\.com/subject/\d+)",
                        descr_text):
                    douban_link = douban_match.group(1)

            # --- [核心修改] MediaInfo 提取逻辑 ---

            # 1. 首先尝试从标准位置提取 MediaInfo
            mediainfo_pre = soup.select_one("div.spoiler-content pre")
            if not mediainfo_pre:
                self.logger.info("未找到常规 MediaInfo 结构，尝试解析 BDInfo 结构...")
                mediainfo_pre = soup.select_one(
                    "div.nexus-media-info-raw > pre")

            mediainfo_text = mediainfo_pre.get_text(
                strip=True) if mediainfo_pre else ""

            # 2. 解析简介内容，并准备提取简介中的元素
            intro = {}
            quotes = []
            images = []
            body = ""
            
            # 提取简介中的IMDb和豆瓣链接
            intro_imdb_link = ""
            intro_douban_link = ""
            
            if descr_container:
                descr_text = descr_container.get_text()
                
                # 提取IMDb链接
                imdb_link_match = re.search(r'◎IMDb链接\s*\[url=([^\]]+)\]([^\[]+)\[/url\]', descr_text)
                if imdb_link_match:
                    intro_imdb_link = imdb_link_match.group(1)  # 获取URL部分
                
                # 提取豆瓣链接
                douban_link_match = re.search(r'◎豆瓣链接\s*\[url=([^\]]+)\]([^\[]+)\[/url\]', descr_text)
                if douban_link_match:
                    intro_douban_link = douban_link_match.group(1)  # 获取URL部分
            
            # 检查IMDb链接处理逻辑：源站提取的优先，不存在则使用简介中的
            if not imdb_link and intro_imdb_link:
                imdb_link = intro_imdb_link
                self.logger.info(f"从简介中提取到IMDb链接: {imdb_link}")
            elif imdb_link and not intro_imdb_link:
                # 如果在简介中没有找到IMDb链接但源站提取到了，添加到简介中
                self.logger.info(f"源站提取到IMDb链接但简介中缺失，将在简介中添加: {imdb_link}")
                # 在body中添加IMDb链接信息
                imdb_info = f"◎IMDb链接　[url={imdb_link}]{imdb_link}[/url]"
                if body:
                    body = f"{body}\n\n{imdb_info}"
                else:
                    body = imdb_info
            
            # 处理豆瓣链接：源站提取的优先，不存在则使用简介中的
            if not douban_link and intro_douban_link:
                douban_link = intro_douban_link
                self.logger.info(f"从简介中提取到豆瓣链接: {douban_link}")
            elif douban_link and not intro_douban_link:
                # 如果在简介中没有找到豆瓣链接但源站提取到了，添加到简介中
                self.logger.info(f"源站提取到豆瓣链接但简介中缺失，将在简介中添加: {douban_link}")
                # 在body中添加豆瓣链接信息
                douban_info = f"◎豆瓣链接　[url={douban_link}]{douban_link}[/url]"
                if body:
                    body = f"{body}\n\n{douban_info}"
                else:
                    body = douban_info

            if descr_container:
                descr_html_string = str(descr_container)
                corrected_descr_html = re.sub(r'(<img[^>]*[^/])>', r'\1 />',
                                              descr_html_string)
                descr_container_soup = BeautifulSoup(corrected_descr_html,
                                                     "html.parser")
                bbcode = self._html_to_bbcode(descr_container_soup)
                
                # --- [新增修复代码] 开始 ---
                # 清理连续的、中间无内容的 [quote] 标签，以修正源站错误的嵌套。
                # 例如将 [quote][quote]...[/quote][/quote] 简化为 [quote]...[/quote]。
                # 使用循环是为了处理可能存在的三层或更多层的连续嵌套。
                original_bbcode = bbcode
                while True:
                    # 将连续的开标签 [quote][quote] 合并为一个
                    bbcode = re.sub(r"\[quote\]\s*\[quote\]", "[quote]", bbcode, flags=re.IGNORECASE)
                    # 将连续的闭标签 [/quote][/quote] 合并为一个
                    bbcode = re.sub(r"\[/quote\]\s*\[/quote\]", "[/quote]", bbcode, flags=re.IGNORECASE)
                    # 如果经过一轮替换后内容没有变化，说明已经清理干净，退出循环
                    if bbcode == original_bbcode:
                        break
                    # 更新原始文本以进行下一轮检查
                    original_bbcode = bbcode
                # --- [新增修复代码] 结束 ---
                
                quotes = re.findall(r"\[quote\].*?\[/quote\]", bbcode,
                                    re.DOTALL)
                images = re.findall(r"\[img\].*?\[/img\]", bbcode)

                # 过滤掉 ARDTU 工具自动发布的声明和免责声明，但保留包含 "By ARDTU" 的组信息
                filtered_quotes = []
                ardtu_declarations = []

                for quote in quotes:
                    # 检查是否为完整的 ARDTU 工具自动发布声明
                    is_ardtutool_auto_publish = (
                        "ARDTU工具自动发布" in quote and "有错误请评论或举报" in quote
                        and any(tag in quote
                                for tag in ["[size=7]", "[color=Red]"]))

                    # 检查是否为免责声明模板
                    is_disclaimer = (
                        "郑重声明：" in quote and "本站提供的所有作品均是用户自行搜集并且上传" in quote
                        and "禁止任何涉及商业盈利目的使用" in quote
                        and any(tag in quote
                                for tag in ["[size=3]", "[color=Red]"]))

                    # 检查是否为财神CSWEB免责声明
                    is_csweb_disclaimer = (
                        "财神CSWEB提供的所有资源均是在网上搜集且由用户上传" in quote
                        and "不可用于任何形式的商业盈利活动" in quote
                        and "请在下载后24小时内尽快删除" in quote)

                    # 检查是否为 "By ARDTU" 结尾的组信息（需要过滤掉 "By ARDTU" 部分）
                    is_by_ardtu_group_info = "By ARDTU" in quote and "官组作品" in quote

                    if is_ardtutool_auto_publish or is_disclaimer or is_csweb_disclaimer:
                        # --- [核心修改] ---
                        # 将整个 quote 块（去除首尾的 [quote] 标签）作为一个整体添加到声明列表
                        clean_content = re.sub(r"\[\/?quote\]", "",
                                               quote).strip()
                        ardtu_declarations.append(
                            clean_content)  # 使用 append 添加完整内容
                    elif is_by_ardtu_group_info:
                        # 过滤掉 "By ARDTU" 部分，保留官方组内容
                        filtered_quote = re.sub(r"\s*By ARDTU\s*", "", quote)
                        filtered_quotes.append(filtered_quote)
                    elif "ARDTU" in quote:
                        # --- [核心修改] ---
                        # 其他包含 ARDTU 的声明也过滤掉，同样作为一个整体
                        clean_content = re.sub(r"\[\/?quote\]", "",
                                               quote).strip()
                        ardtu_declarations.append(
                            clean_content)  # 使用 append 添加完整内容
                    else:
                        filtered_quotes.append(quote)

                quotes = filtered_quotes
                body = (re.sub(r"\[quote\].*?\[/quote\]|\[img\].*?\[/img\]",
                               "",
                               bbcode,
                               flags=re.DOTALL).replace("\r", "").strip())

            # 3. 如果标准位置没有 MediaInfo，则在简介的引用中查找
            if not mediainfo_text and quotes:
                self.logger.info("标准位置未找到 MediaInfo，正在尝试从简介的 [quote] 区块中提取...")
                remaining_quotes = []
                found_mediainfo_in_quote = False
                for quote in quotes:
                    # 检查 quote 内容是否符合 MediaInfo 或 BDInfo 的特征
                    is_mediainfo = ("General" in quote and "Video" in quote
                                    and "Audio" in quote)
                    is_bdinfo = ("DISC INFO" in quote
                                 and "PLAYLIST REPORT" in quote)

                    if not found_mediainfo_in_quote and (is_mediainfo
                                                         or is_bdinfo):
                        # 去掉 [quote] 和 [/quote] 标签
                        mediainfo_text = re.sub(r"\[/?quote\]", "",
                                                quote).strip()
                        self.logger.success("成功在简介中提取到 MediaInfo/BDInfo。")
                        found_mediainfo_in_quote = True  # 确保只提取第一个匹配项
                    else:
                        remaining_quotes.append(quote)

                # 更新 quotes 列表，移除已作为 mediainfo 的内容
                quotes = remaining_quotes

            # 4. 海报失效处理：优先尝试从豆瓣链接获取，如果没有豆瓣链接则尝试IMDb链接
            from utils import upload_data_poster
            
            # 检查当前海报是否有效（简单检查是否包含图片标签）
            current_poster_valid = bool(images and images[0] and "[img]" in images[0])
            
            if not current_poster_valid:
                self.logger.info("当前海报失效，尝试从豆瓣或IMDb获取新海报...")
                
                # 优先级1：如果有豆瓣链接，优先从豆瓣获取
                if douban_link:
                    self.logger.info(f"尝试从豆瓣链接获取海报: {douban_link}")
                    poster_status, poster_content, extracted_imdb = upload_data_poster(douban_link, "")
                    
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
                                body = re.sub(douban_pattern, lambda m: m.group(0) + "\n" + imdb_info, body)
                            else:
                                if body:
                                    body = f"{body}\n\n{imdb_info}"
                                else:
                                    body = imdb_info
                    else:
                        self.logger.warning(f"从豆瓣链接获取海报失败: {poster_content}")
                
                # 优先级2：如果没有豆瓣链接或豆瓣获取失败，尝试从IMDb链接获取
                elif imdb_link and (not images or not images[0] or "[img]" not in images[0]):
                    self.logger.info(f"尝试从IMDb链接获取海报: {imdb_link}")
                    poster_status, poster_content, _ = upload_data_poster("", imdb_link)
                    
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
                    poster_status, poster_content, extracted_imdb = upload_data_poster(douban_link, "")
                    if extracted_imdb:
                        imdb_link = extracted_imdb
                        self.logger.info(f"通过豆瓣提取到IMDb链接: {imdb_link}")
                        
                        # 将IMDb链接添加到简介中
                        imdb_info = f"◎IMDb链接　[url={imdb_link}]{imdb_link}[/url]"
                        douban_pattern = r"◎豆瓣链接　\[url=[^\]]+\][^\[]+\[/url\]"
                        if re.search(douban_pattern, body):
                            body = re.sub(douban_pattern, lambda m: m.group(0) + "\n" + imdb_info, body)
                        else:
                            if body:
                                body = f"{body}\n\n{imdb_info}"
                            else:
                                body = imdb_info
            
            # 5. 组装最终的 intro 字典
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
            origin_info = extract_origin_from_description(full_description_text)

            # 7. 最后调用验证函数处理 mediainfo_text
            mediainfo = upload_data_mediaInfo(
                mediainfo_text if mediainfo_text else "未找到 Mediainfo 或 BDInfo",
                self.save_path)
            
            # --- [核心修改结束] ---

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
            source_params = {
                "类型":
                type_match.group(1)
                if type_match else type_text.split("/")[-1],
                "媒介":
                basic_info_dict.get("媒介"),
                "编码":
                basic_info_dict.get("编码"),
                "音频编码":
                basic_info_dict.get("音频编码"),
                "分辨率":
                basic_info_dict.get("分辨率"),
                "制作组":
                basic_info_dict.get("制作组"),
                "标签":
                tags,
                "产地":
                origin_info,  # 添加产地信息
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
                    "主标题", "年份", "季集", "剧集状态", "发布版本", "分辨率", "媒介",
                    "片源平台", "视频编码", "视频格式", "HDR格式", "色深", "帧率", "音频编码",
                ]
                title_parts = []
                for key in order:
                    value = title_params.get(key)
                    if value:
                        title_parts.append(" ".join(map(str, value)) if isinstance(value, list) else str(value))
                
                raw_main_part = " ".join(filter(None, title_parts))
                main_part = re.sub(r'(?<!\d)\.(?!\d)', ' ', raw_main_part)
                main_part = re.sub(r'\s+', ' ', main_part).strip()
                release_group = title_params.get("制作组", "NOGROUP")
                if "N/A" in release_group: release_group = "NOGROUP"
                preview_title = f"{main_part}-{release_group}"

                # 3. 组合最终的简介 (逻辑与 sites/*.py 中的 _build_description 一致)
                full_description = (
                    f"{intro.get('statement', '')}\n"
                    f"{intro.get('poster', '')}\n"
                    f"{intro.get('body', '')}\n"
                    f"{intro.get('screenshots', '')}"
                )

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
            except Exception as e:
                self.logger.error(f"构建发布参数预览时出错: {e}")
                final_publish_parameters = {"error": "构建预览失败，请检查日志。"}
            # --- [新增] 结束 ---

            self.logger.info("--- [步骤1] 种子信息获取和解析完成 ---")
            
            # 将新构建的预览对象添加到返回数据中
            review_data_payload = {
                "original_main_title": original_main_title,
                "title_components": title_components,
                "subtitle": subtitle,
                "imdb_link": imdb_link,
                "intro": intro,
                "mediainfo": mediainfo,
                "source_params": source_params,
                # --- [新增] ---
                "final_publish_parameters": final_publish_parameters 
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
                f"正在加载目标站点上传模块: sites.{self.TARGET_UPLOAD_MODULE}")
            upload_module = importlib.import_module(
                f"sites.{self.TARGET_UPLOAD_MODULE}")
            self.logger.success("上传模块加载成功！")

            result, message = upload_module.upload(
                site_info=self.target_site, upload_payload=upload_payload)
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
