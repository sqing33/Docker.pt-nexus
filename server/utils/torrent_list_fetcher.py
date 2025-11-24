# server/core/list_fetcher/torrent_list_fetcher.py

import os
import cloudscraper
from bs4 import BeautifulSoup
import time
import urllib3
import re
import copy
import json
from loguru import logger

# 禁用 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class TorrentListFetcher:
    """用于获取站点种子列表页面并提取种子信息的类"""

    def __init__(self, site_info: dict):
        """
        初始化种子列表获取器
        Args:
            site_info: 包含站点信息的字典，包括基础URL和Cookie等
        """
        self.site_info = site_info
        self.base_url = site_info.get("base_url")
        self.cookie = site_info.get("cookie")
        self.nickname = site_info.get("nickname", "Unknown")

        # 创建 HTTP 请求会话
        import requests
        session = requests.Session()
        session.verify = False
        self.scraper = cloudscraper.create_scraper(sess=session)

        # 配置logger
        self.logger = logger

    @classmethod
    def get_tags(cls,
                 base_url: str,
                 cookie: str,
                 main_title: str,
                 torrent_id: str = ''):
        """
        静态调用方法：通过搜索标题获取种子的 Tags
        
        Args:
            base_url: 站点地址
            cookie: 用户 Cookie
            main_title: 搜索关键词（通常是主标题）
            torrent_id: 种子ID（可选）。
                        如果传入此参数，将开启严格模式：
                        - 搜索结果中有此 ID -> 返回 tags list
                        - 搜索结果中无此 ID -> 返回 False
            
        Returns:
            list | bool: 成功找到时返回标签列表(list)；如果开启严格模式且ID不匹配返回 False(bool)
        """
        # 1. 构造临时的 site_info
        site_info = {
            "base_url": base_url,
            "cookie": cookie,
            "nickname": "TagFetcher",
            "site": "temp_site"
        }

        # 2. 初始化实例
        fetcher = cls(site_info)

        # 3. 构造搜索参数
        # 这里的 search_mode 设为 0 (AND/与)，以防标点符号差异导致搜不到
        search_params = {
            'search': main_title,
            'search_area': 0,  # 标题
            'search_mode': 0,  # 0=AND
            'incldead': 1,  # 包括死种
            'spstate': 0  # 促销状态：全部
        }

        try:
            # 4. 获取并解析列表
            torrents = fetcher.fetch_torrents_page(params=search_params)

            # ================== 逻辑分支 A: 严格模式 (传入了 ID) ==================
            if torrent_id is not None:
                if not torrents:
                    print(f"搜索 '{main_title}' 无结果，无法验证 ID: {torrent_id}")
                    return False

                # 遍历结果查找精确匹配的 ID
                for t in torrents:
                    if str(t.get('id')) == str(torrent_id):
                        print(
                            f"已精确匹配种子 ID: {torrent_id}, Tags: {t.get('tags')}")
                        return t.get('tags', [])

                # 循环结束仍未找到匹配 ID
                print(
                    f"在站点搜索结果中未找到 ID 为 {torrent_id} 的种子 (搜索关键词: {main_title})")
                return False

            # ================== 逻辑分支 B: 模糊模式 (未传入 ID) ==================
            if not torrents:
                print(f"未搜索到关于 '{main_title}' 的种子")
                return []

            # 5. 筛选匹配结果
            target_torrent = None

            # 5.1 尝试精确匹配标题
            for t in torrents:
                if t.get('main_title') == main_title:
                    target_torrent = t
                    break

            # 5.2 如果还是没找到，且列表有结果，默认取第一个（假设搜索很精准）
            if not target_torrent and torrents:
                target_torrent = torrents[0]

            if target_torrent:
                print(
                    f"已模糊匹配种子 ID: {target_torrent.get('id')}, Tags: {target_torrent.get('tags')}"
                )
                return target_torrent.get('tags', [])

            return []

        except Exception as e:
            print(f"获取 Tags 失败: {e}")
            print(f"获取 Tags 失败: {e}")
            return []

    def fetch_torrents_page(self, params: dict = None) -> str:
        """
        获取站点的种子列表页面
        """
        if not self.base_url:
            raise ValueError("站点基础URL未设置")

        try:
            # 构建请求URL
            url = f"{self.base_url}/torrents.php"

            # 设置请求头
            headers = {"Cookie": self.cookie} if self.cookie else {}
            if "User-Agent" not in headers:
                headers[
                    "User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

            if params is None:
                params = {}

            self.logger.info(f"正在获取站点 {self.nickname} 的种子列表页面...")

            # 发送请求
            response = self.scraper.get(
                url,
                headers=headers,
                params=params,
                timeout=60,
            )

            response.raise_for_status()
            response.encoding = "utf-8"
            page_content = response.text

            self.logger.success(f"成功获取站点 {self.nickname} 的种子列表页面")

            # 解析提取种子信息
            torrents = self.parse_torrent_list(page_content)
            return torrents

        except Exception as e:
            self.logger.error(f"获取站点 {self.nickname} 种子列表页面时发生错误: {e}")
            raise

    def parse_torrent_list(self, html_content: str) -> list:
        """
        从HTML内容中精确解析种子列表
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        torrents = []

        # 1. 定位主表格
        main_table = soup.find('table', class_='torrents')
        if not main_table:
            self.logger.warning("未找到 class='torrents' 的主表格")
            return []

        # 2. 遍历行
        rows = main_table.find_all('tr', recursive=False)

        for row in rows:
            # 跳过表头
            if row.find('td', class_='colhead'):
                continue

            cols = row.find_all('td', recursive=False)
            if not cols or len(cols) < 2:
                continue

            try:
                # === 1. 提取类型 (Type) ===
                type_name = ""
                type_img = cols[0].find(
                    'img', class_=lambda x: x and x.startswith('c_'))
                if type_img:
                    type_name = type_img.get('title') or type_img.get(
                        'alt') or ""

                # === 2. 定位核心信息区 ===
                content_col = cols[1]
                torrent_name_table = content_col.find('table',
                                                      class_='torrentname')

                target_container = None
                if torrent_name_table:
                    embedded_tds = torrent_name_table.find_all(
                        'td', class_='embedded')
                    for td in embedded_tds:
                        if td.find('a', href=re.compile(r'details\.php')):
                            target_container = td
                            break
                    if not target_container and embedded_tds:
                        target_container = embedded_tds[-1]
                else:
                    target_container = content_col

                if not target_container:
                    continue

                # === 3. 提取主标题和详情链接 ===
                details_link_node = target_container.find(
                    'a', href=re.compile(r'details\.php'))
                if not details_link_node:
                    continue

                details_href = details_link_node.get('href', '')

                # ID
                torrent_id = ""
                id_match = re.search(r'id=(\d+)', details_href)
                if id_match:
                    torrent_id = id_match.group(1)

                # 主标题
                main_title = details_link_node.get('title')
                if not main_title:
                    main_title = details_link_node.get_text(strip=True)

                # === 4. 提取标签 (Tags) ===
                tags = []

                # 4.1 提取 <span class="optiontag"> (HDSky 风格)
                for opt in target_container.find_all('span',
                                                     class_='optiontag'):
                    tag_text = opt.get_text(strip=True)
                    if tag_text:
                        tags.append(tag_text)

                # 4.2 提取 <div class="tag"> (FRDS/其他 风格)
                for tag_div in target_container.find_all(
                        'div', class_=re.compile(r'\btag\b')):
                    tags.append(tag_div.get_text(strip=True))

                # 4.3 提取带样式的 span (通用)
                if not tags:
                    for span in target_container.find_all('span'):
                        if span.get('class') and 'optiontag' in span.get(
                                'class'):
                            continue
                        style = span.get('style', '')
                        if 'background-color' in style or 'border' in style:
                            tags.append(span.get_text(strip=True))

                # 4.4 通过图片类名提取标签
                if target_container.find('img', class_='sticky'):
                    tags.append('置顶')
                if target_container.find('img', class_='pro_free'):
                    tags.append('免费')
                if target_container.find('img', class_='pro_2up'):
                    tags.append('2x')
                if target_container.find('img', class_='pro_50pctdown'):
                    tags.append('50%')
                if target_container.find('img', class_='pro_30pctdown'):
                    tags.append('30%')
                if target_container.find('img', class_='pro_free2up'):
                    tags.append('免费2x')

                # 4.5 通过特殊 Font 标签提取
                for font_tag in target_container.find_all('font'):
                    font_class = font_tag.get('class', [])
                    font_text = font_tag.get_text(strip=True)
                    if 'hot' in font_class:
                        tags.append('热门')
                    elif 'classic' in font_class:
                        tags.append('经典')
                    elif 'recommended' in font_class:
                        tags.append(font_text)

                # 4.6 文本匹配补漏
                full_text = target_container.get_text()
                if "限时禁转" in full_text and "限时禁转" not in tags:
                    tags.append("限时禁转")

                tags = list(set(tags))

                # === 5. 提取中文名/副标题 (Description) ===
                chinese_name = ""

                # 策略 A: 优先查找 <font class="subtitle">
                subtitle_font = target_container.find('font',
                                                      class_='subtitle')
                if subtitle_font:
                    temp_sub = copy.copy(subtitle_font)
                    for child in temp_sub.find_all(['div', 'span']):
                        child.decompose()
                    for br in temp_sub.find_all('br'):
                        br.replace_with(" ")
                    chinese_name = temp_sub.get_text(" ", strip=True)

                # 策略 B: “减法”提取
                if not chinese_name:
                    temp_soup = copy.copy(target_container)

                    link_in_temp = temp_soup.find(
                        'a', href=re.compile(r'details\.php'))
                    if link_in_temp:
                        link_in_temp.decompose()

                    for img in temp_soup.find_all('img'):
                        img.decompose()

                    for opt in temp_soup.find_all('span', class_='optiontag'):
                        opt.decompose()

                    for div in temp_soup.find_all('div'):
                        div.decompose()

                    for font in temp_soup.find_all('font'):
                        font.decompose()

                    for input_tag in temp_soup.find_all('input'):
                        input_tag.decompose()

                    for b_tag in temp_soup.find_all('b'):
                        if b_tag.find('div') or "限时禁转" in b_tag.get_text():
                            b_tag.decompose()

                    for span in temp_soup.find_all('span'):
                        style = span.get('style', '')
                        if 'background-color' in style or 'border' in style:
                            span.decompose()
                        else:
                            span.unwrap()

                    for a_tag in temp_soup.find_all('a'):
                        a_tag.decompose()

                    for br in temp_soup.find_all('br'):
                        br.replace_with(" ")

                    chinese_name = temp_soup.get_text(" ", strip=True)

                chinese_name = re.sub(r'\[优惠剩余时间：.*?\]', '', chinese_name)
                chinese_name = chinese_name.replace("[ ]", "").strip()
                chinese_name = re.sub(r'^\s+', '', chinese_name)

                torrent_data = {
                    "id": torrent_id,
                    "type": type_name.strip(),
                    "main_title": main_title.strip(),
                    "chinese_name": chinese_name,
                    "tags": tags,
                    "details_href": details_href
                }

                torrents.append(torrent_data)

            except Exception as e:
                self.logger.warning(f"解析行数据时出错: {e}")
                continue

        return torrents


if __name__ == "__main__":
    # 站点配置
    base_url = "https://hdsky.me"
    cookie = "c_secure_uid=MTA5Mzg0; c_secure_pass=...; filterParam=...; cf_clearance=..."  # 你的Cookie

    # 搜索关键词
    search_title = "Those Days S01E01-E03 2025 2160p WEB-DL DDP5.1 H265-Pure@HDSWEB"

    # 调用方式：直接通过类名调用 get_tags
    print(f"正在获取 '{search_title}' 的标签...")

    # torrent_id 暂时设为 None
    tags = TorrentListFetcher.get_tags(base_url,
                                       cookie,
                                       search_title,
                                       torrent_id=None)

    print("-" * 30)
    print(f"获取到的 Tags: {tags}")
    print("-" * 30)
