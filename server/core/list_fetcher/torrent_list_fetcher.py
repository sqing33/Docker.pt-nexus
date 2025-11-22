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

    def fetch_torrents_page(self,
                            params: dict = None,
                            save_to_file: bool = False) -> str:
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
            if "User-Agent" not not in headers:
                headers[
                    "User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

            if params is None:
                params = {}

            self.logger.info(f"正在获取站点 {self.nickname} 的种子列表页面...")
            self.logger.info(f"请求URL: {url}")
            self.logger.info(f"搜索参数: {params}")

            # 发送请求
            # requests 会自动将 params 字典转换为 URL 查询字符串（例如空格自动转为 + 或 %20）
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

            # 直接解析并返回JSON数据
            if save_to_file:
                saved_html_path = self._save_page_content(page_content, params)
                self.logger.success(f"页面内容已保存到: {saved_html_path}")

                # 自动解析并保存为JSON
                try:
                    json_path = self.save_torrents_to_json(saved_html_path)
                    self.logger.success(f"种子列表已解析并保存为JSON: {json_path}")
                except Exception as e:
                    self.logger.error(f"解析种子列表失败: {e}")
                    import traceback
                    self.logger.error(traceback.format_exc())
            
            # 直接使用响应内容提取种子信息为JSON
            torrents = self.parse_torrent_list(page_content)
            return torrents

        except Exception as e:
            self.logger.error(f"获取站点 {self.nickname} 种子列表页面时发生错误: {e}")
            raise

    def _save_page_content(self, content: str, params: dict = None) -> str:
        """保存HTML内容到文件"""
        timestamp = int(time.time())
        site_name = self.site_info.get("site", "unknown").replace(" ",
                                                                  "_").replace(
                                                                      "-", "_")

        # 确保目录存在
        save_dir = "/root/Code/Docker.pt-nexus-dev/server/data"
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

        # 如果有搜索词，加到文件名里方便区分
        search_keyword = ""
        if params and 'search' in params:
            # 简单的文件名净化
            safe_keyword = re.sub(r'[^\w\-_]', '_', params['search'])[:50]
            search_keyword = f"_search_{safe_keyword}"

        filename = f"{site_name}_torrents{search_keyword}_{timestamp}.html"
        filepath = os.path.join(save_dir, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        return filepath

    def save_torrents_to_fixed_json(self, torrents: list, json_file_path: str = None) -> str:
        """
        将种子信息保存到固定文件名的JSON文件中
        """
        # 确保目录存在
        save_dir = "/root/Code/Docker.pt-nexus-dev/server/data"
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
        
        # 生成固定文件名
        if json_file_path is None:
            site_name = self.site_info.get("site", "unknown").replace(" ", "_").replace("-", "_")
            json_file_path = os.path.join(save_dir, f"{site_name}_torrents.json")
        
        # 保存为JSON文件
        with open(json_file_path, 'w', encoding='utf-8') as f:
            json.dump(torrents, f, ensure_ascii=False, indent=2)
        
        self.logger.success(f"种子列表已保存到固定文件: {json_file_path}")
        return json_file_path

    def parse_torrent_list(self, html_content: str) -> list:
        """
        从HTML内容中精确解析种子列表
        针对 NexusPHP 结构进行深度优化
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        torrents = []

        # 1. 定位主表格 (class="torrents")
        main_table = soup.find('table', class_='torrents')
        if not main_table:
            self.logger.warning("未找到 class='torrents' 的主表格，尝试备用解析方式...")
            # 备用：查找所有包含 .torrentname 的行的父级
            rows = [
                t.find_parent('tr').find_parent('table').find_parent(
                    'td').find_parent('tr')
                for t in soup.find_all('table', class_='torrentname') if t
            ]
            # 去重
            rows = list(set([r for r in rows if r]))
        else:
            # 2. 遍历主表格的直接子行 (recursive=False)
            rows = main_table.find_all('tr', recursive=False)

        for row in rows:
            # 跳过表头 (class="colhead")
            if row.find('td', class_='colhead'):
                continue

            # 获取当前行的所有列
            cols = row.find_all('td', recursive=False)
            if not cols or len(cols) < 2:
                continue

            try:
                # === 1. 提取类型 (Type) ===
                # 通常在第1列 (index 0)
                type_name = ""
                # 查找类似 <img class="c_tvseries" title="电视剧"> 的标签
                type_img = cols[0].find(
                    'img', class_=lambda x: x and x.startswith('c_'))
                if type_img:
                    type_name = type_img.get('title') or type_img.get(
                        'alt') or ""

                # === 2. 定位核心信息区 ===
                # 通常在第2列 (index 1)，里面包含一个 class="torrentname" 的 table
                content_col = cols[1]
                torrent_name_table = content_col.find('table',
                                                      class_='torrentname')

                if not torrent_name_table:
                    # 如果没有嵌套表格，直接在列中查找(某些简化模板)
                    target_container = content_col
                else:
                    # 在嵌套表格中，信息通常在 td.embedded 中
                    # 可能有两个 td.embedded (海报+文字)，我们要找有链接的那个
                    embedded_tds = torrent_name_table.find_all(
                        'td', class_='embedded')
                    target_container = None

                    for td in embedded_tds:
                        # 查找包含 details.php 的链接，作为特征
                        if td.find('a', href=re.compile(r'details\.php')):
                            target_container = td
                            break

                    if not target_container and embedded_tds:
                        # 兜底：取最后一个 embedded
                        target_container = embedded_tds[-1]

                if not target_container:
                    continue

                # === 3. 提取主标题和详情链接 ===
                details_link_node = target_container.find(
                    'a', href=re.compile(r'details\.php'))
                if not details_link_node:
                    continue

                # 链接后缀
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
                for span in target_container.find_all('span'):
                    style = span.get('style', '')
                    if 'background-color' in style:
                        tags.append(span.get_text(strip=True))

                # === 5. 提取中文名/副标题 (Description) ===
                # 使用减法逻辑：克隆节点 -> 移除已知元素 -> 获取剩余文本

                temp_soup = copy.copy(target_container)

                # 移除主标题链接
                link_in_temp = temp_soup.find('a',
                                              href=re.compile(r'details\.php'))
                if link_in_temp:
                    link_in_temp.decompose()

                # 移除所有图片 (置顶图标、促销图标、新种图标等)
                for img in temp_soup.find_all('img'):
                    img.decompose()

                # 移除所有标签 span (国语、中字等)
                for span in temp_soup.find_all('span'):
                    span.decompose()  # 这里直接移除所有span，通常副标题只是纯文本

                # 移除 <font> (剩余时间、促销文字)
                for font in temp_soup.find_all('font'):
                    font.decompose()

                # 移除其他功能链接 (收藏、下载、评论数链接等)
                for a_tag in temp_soup.find_all('a'):
                    a_tag.decompose()

                # 移除 input (有时有打钩框)
                for input_tag in temp_soup.find_all('input'):
                    input_tag.decompose()

                # 移除 div (进度条等)
                for div in temp_soup.find_all('div'):
                    div.decompose()

                # 替换换行符为空格
                for br in temp_soup.find_all('br'):
                    br.replace_with(" ")

                # 提取纯文本
                chinese_name = temp_soup.get_text(" ", strip=True)

                # 额外的字符串清理
                chinese_name = chinese_name.replace("[ ]", "").strip()

                # 组装数据
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

    def save_torrents_to_json(self,
                              html_file_path: str,
                              json_file_path: str = None) -> str:
        """
        从HTML文件读取并保存提取的种子信息为JSON文件
        """
        if not os.path.exists(html_file_path):
            raise FileNotFoundError(f"HTML文件未找到: {html_file_path}")

        # 读取HTML文件
        with open(html_file_path, 'r', encoding='utf-8') as f:
            html_content = f.read()

        # 解析种子列表
        self.logger.info("开始解析HTML内容...")
        torrents = self.parse_torrent_list(html_content)

        # 生成JSON路径
        if json_file_path is None:
            dir_name = os.path.dirname(html_file_path)
            base_name = os.path.basename(html_file_path).replace('.html', '')
            json_file_path = os.path.join(dir_name, f"{base_name}_parsed.json")

        # 保存为JSON文件
        with open(json_file_path, 'w', encoding='utf-8') as f:
            json.dump(torrents, f, ensure_ascii=False, indent=2)

        self.logger.success(f"解析完成，共提取 {len(torrents)} 个种子")
        self.logger.success(f"结果已保存到: {json_file_path}")

        return json_file_path


if __name__ == "__main__":
    # 直接使用 Site Info 进行实时抓取
    site_info = {
        "base_url":
        "https://pandapt.net",
        "nickname":
        "LuckPT",
        "site":
        "example",
        # 你的 Cookie
        "cookie":
        "c_secure_uid=MTA2NjA4; c_secure_pass=b4f9cccf6b68ce7ce6c91829a6cc02c5; c_secure_ssl=eWVhaA%3D%3D; c_secure_tracker_ssl=eWVhaA%3D%3D; c_secure_login=bm9wZQ%3D%3D"
    }

    # === 在这里配置搜索关键词 ===
    search_keyword = "The Demon Hunter 2023 S01E55 2160p V2 WEB-DL H.265 AAC-AilMWeb"
    # =========================

    print("开始从站点获取种子列表...")
    fetcher = TorrentListFetcher(site_info)

    # 构建参数字典，完全映射自你截图中的 URL 参数
    search_params = {
        'incldead': 1,
        'spstate': 0,
        'inclbookmarked': 0,
        'approval_status': '',
        'size_begin': '',
        'size_end': '',
        'seeders_begin': '',
        'seeders_end': '',
        'leechers_begin': '',
        'leechers_end': '',
        'times_completed_begin': '',
        'times_completed_end': '',
        'added_begin': '',
        'added_end': '',
        'search':
        search_keyword,  # 直接填字符串，Requests会自动转义为 Fullmetal+Alchemist+...
        'search_area': 0,  # 范围：标题
        'search_mode': 2  # 匹配模式：准确
    }

    try:
        # 1. 发起网络请求获取 HTML
        # 2. 保存 HTML 到 server/data/
        # 3. 自动调用解析逻辑，生成 JSON
        torrents = fetcher.fetch_torrents_page(params=search_params, save_to_file=False)
        print(f"成功提取 {len(torrents)} 个种子:")
        for torrent in torrents:
            print(torrent)
        
        # 保存到固定文件名的JSON文件
        json_path = fetcher.save_torrents_to_fixed_json(torrents)
        print(f"种子列表已保存到固定文件: {json_path}")
    except Exception as e:
        print(f"运行出错: {e}")