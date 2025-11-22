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

            if save_to_file:
                self._save_page_content(page_content, params)

            # 解析提取种子信息
            torrents = self.parse_torrent_list(page_content)
            return torrents

        except Exception as e:
            self.logger.error(f"获取站点 {self.nickname} 种子列表页面时发生错误: {e}")
            raise

    def save_torrents_to_fixed_json(self,
                                    torrents: list,
                                    json_file_path: str = None) -> str:
        """将种子信息保存到固定文件名的JSON文件中"""
        save_dir = "/root/Code/Docker.pt-nexus-dev/server/data"
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

        if json_file_path is None:
            site_name = self.site_info.get("site", "unknown").replace(
                " ", "_").replace("-", "_")
            json_file_path = os.path.join(save_dir,
                                          f"{site_name}_torrents.json")

        with open(json_file_path, 'w', encoding='utf-8') as f:
            json.dump(torrents, f, ensure_ascii=False, indent=2)

        self.logger.success(f"种子列表已保存到固定文件: {json_file_path}")
        return json_file_path

    def parse_torrent_list(self, html_content: str) -> list:
        """
        从HTML内容中精确解析种子列表
        已适配：NexusPHP 标准版, KeepFRDS 变体, HDSky 变体
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
                # 注意：需排除 optiontag (已处理) 和 description span (通常无背景色或不同样式)
                # 这里只作为补充，如果之前没找到 tag
                if not tags:
                    for span in target_container.find_all('span'):
                        if span.get('class') and 'optiontag' in span.get(
                                'class'):
                            continue
                        style = span.get('style', '')
                        if 'background-color' in style or 'border' in style:
                            tags.append(span.get_text(strip=True))

                # 4.4 通过图片类名提取标签 (Sticky, Free, etc.)
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

                # 4.5 通过特殊 Font 标签提取 (热门, 推荐, 限时禁转)
                # HDSky 使用 <font class="hot">, <font class="recommended">, <font class="classic">
                for font_tag in target_container.find_all('font'):
                    font_class = font_tag.get('class', [])
                    font_text = font_tag.get_text(strip=True)
                    if 'hot' in font_class:
                        tags.append('热门')
                    elif 'classic' in font_class:
                        tags.append('经典')
                    elif 'recommended' in font_class:
                        # 有些站点的"限时禁转"在这里
                        tags.append(font_text)

                # 4.6 文本匹配补漏 (针对没有特定 Class 的情况)
                full_text = target_container.get_text()
                if "限时禁转" in full_text and "限时禁转" not in tags:
                    tags.append("限时禁转")

                # 去重
                tags = list(set(tags))

                # === 5. 提取中文名/副标题 (Description) ===
                chinese_name = ""

                # 策略 A: 优先查找 <font class="subtitle"> (KeepFRDS 等)
                subtitle_font = target_container.find('font',
                                                      class_='subtitle')
                if subtitle_font:
                    temp_sub = copy.copy(subtitle_font)
                    for child in temp_sub.find_all(['div', 'span']):  # 移除内部标签
                        child.decompose()
                    for br in temp_sub.find_all('br'):
                        br.replace_with(" ")
                    chinese_name = temp_sub.get_text(" ", strip=True)

                # 策略 B: “减法”提取 (HDSky / 通用)
                if not chinese_name:
                    temp_soup = copy.copy(target_container)

                    # 移除主标题链接
                    link_in_temp = temp_soup.find(
                        'a', href=re.compile(r'details\.php'))
                    if link_in_temp:
                        link_in_temp.decompose()

                    # 移除所有图片 (置顶、免费、IMDb条)
                    for img in temp_soup.find_all('img'):
                        img.decompose()

                    # 移除所有 optiontag (HDSky 特有标签)
                    for opt in temp_soup.find_all('span', class_='optiontag'):
                        opt.decompose()

                    # 移除 div (进度条、悬浮海报容器等)
                    for div in temp_soup.find_all('div'):
                        div.decompose()

                    # 移除 font 标签 (热门、推荐、经典等)
                    for font in temp_soup.find_all('font'):
                        font.decompose()

                    # 移除 input
                    for input_tag in temp_soup.find_all('input'):
                        input_tag.decompose()

                    # 移除 FRDS 风格的包含图标的 b 标签
                    for b_tag in temp_soup.find_all('b'):
                        if b_tag.find('div') or "限时禁转" in b_tag.get_text():
                            b_tag.decompose()

                    # 处理剩余的 span
                    # HDSky 的副标题有时在 <span style="color:..."> 中，有时直接是文本
                    # 我们只移除那些肯定是 UI 标签的 span
                    for span in temp_soup.find_all('span'):
                        style = span.get('style', '')
                        # 如果有背景色或边框，视为标签移除
                        if 'background-color' in style or 'border' in style:
                            span.decompose()
                        else:
                            # 否则可能是副标题的高亮色（如红色），保留文字
                            span.unwrap()

                    # 移除剩余的功能链接 (下载、收藏)
                    for a_tag in temp_soup.find_all('a'):
                        a_tag.decompose()

                    # 替换换行符
                    for br in temp_soup.find_all('br'):
                        br.replace_with(" ")

                    # 获取文本
                    chinese_name = temp_soup.get_text(" ", strip=True)

                # 清理副标题中的杂质
                # 去除 HDSky 可能存在的 "[优惠剩余时间：...]" 文本
                chinese_name = re.sub(r'\[优惠剩余时间：.*?\]', '', chinese_name)
                chinese_name = chinese_name.replace("[ ]", "").strip()
                chinese_name = re.sub(r'^\s+', '', chinese_name)

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


if __name__ == "__main__":
    # 直接使用 Site Info 进行实时抓取
    b1 = "https://ptchdbits.co"
    b2 = "c_secure_uid=MTM2ODky; c_secure_pass=5b9c18a380063efeba9d80eaf0381aeb; c_secure_ssl=eWVhaA%3D%3D; c_secure_tracker_ssl=eWVhaA%3D%3D; c_secure_login=bm9wZQ%3D%3D"
    c1 = "https://pt.keepfrds.com"
    c2 = "c_secure_uid=NDMzNTE%3D; c_secure_pass=654ec7cea5e0ff1366adf0c5fc3881a9; c_secure_ssl=eWVhaA%3D%3D; c_secure_tracker_ssl=eWVhaA%3D%3D; c_secure_login=bm9wZQ%3D%3D; filterParam=minimdb=0&maximdb=10&sizerange=&titleregex=&descregex=&titleinclude=&titledescinclude=&seeding=false&downloaded=false&chnsub=false&nochnlang=false; _gid=GA1.2.1990403695.1763870468; _ga_K4W7MM7ZDQ=GS2.1.s1763913549$o33$g1$t1763913552$j57$l0$h0; _ga=GA1.1.975743663.1760788705"
    d1 = "https://hdsky.me"
    d2 = "c_secure_uid=MTA5Mzg0; c_secure_pass=2905b55544eb44717f3d8f937874e0f6; c_secure_ssl=eWVhaA%3D%3D; c_secure_tracker_ssl=eWVhaA%3D%3D; c_secure_login=bm9wZQ%3D%3D; filterParam=minimdb=0&maximdb=10&sizerange=&titleregex=&descregex=&titleinclude=hds&titledescinclude=&seeding=false&downloaded=false&chnsub=false&nochnlang=false; cf_clearance=BhtNRxeHt11X1CtEizVLsKLrcfrHyL8TYqq4Ke5ZZx8-1763915273-1.2.1.1-53OV3lgGFnPoLZhaHCKHGuz221gzUnYX7.oF6_At4dwHAFd00CosHknQz_ugZKp3dcEu8.0kQSTE375uKak2q1I7M90q6ljcf8fYAVKYkkP1lRJ16UuTcVItpVRPA3_kPOaPAVFPgaxJZWdGh2ruxkIWiBpPX816ZhTxQ.uvkZl_7PnETHEWB0MQWjw0XW7HvaAKGlzri8IFTo8M3ZIogWTA43K6CHqsgNM0aFdbDUg"

    site_info = {
        "base_url": d1,
        "nickname": "LuckPT",
        "site": "example",
        # 你的 Cookie
        "cookie": d2
    }

    # === 在这里配置搜索关键词 ===
    search_keyword = "Fast Five 2011 2in1 2160p UHD Blu-ray HEVC DTS-X-x-man@HDSky"
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
        torrents = fetcher.fetch_torrents_page(params=search_params,
                                               save_to_file=False)
        print(f"成功提取 {len(torrents)} 个种子:")
        for torrent in torrents:
            print(torrent)

        # 保存到固定文件名的JSON文件
        json_path = fetcher.save_torrents_to_fixed_json(torrents)
        print(f"种子列表已保存到固定文件: {json_path}")
    except Exception as e:
        print(f"运行出错: {e}")
