import re
import os
import yaml
import datetime
from bs4 import BeautifulSoup
from utils import extract_tags_from_mediainfo, extract_origin_from_description, validate_media_info_format
from utils.torrent_list_fetcher import TorrentListFetcher

# 加载内容过滤配置
CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(__file__)))), "configs")
CONTENT_FILTERING_CONFIG = {}
try:
    global_mappings_path = os.path.join(CONFIG_DIR, "global_mappings.yaml")
    if os.path.exists(global_mappings_path):
        with open(global_mappings_path, 'r', encoding='utf-8') as f:
            global_config = yaml.safe_load(f)
            CONTENT_FILTERING_CONFIG = global_config.get(
                "content_filtering", {})
except Exception as e:
    print(f"警告：无法加载内容过滤配置: {e}")


class KEEPFRDSSpecialExtractor:
    """KEEPFRDS特殊站点提取器"""

    def __init__(self, soup, base_url, cookie, torrent_id):
        print("KEEPFRDS特殊站点提取器初始化")
        self.soup = soup
        self.base_url = base_url
        self.cookie = cookie
        self.torrent_id = torrent_id

    def extract_mediainfo(self):
        """
        提取MediaInfo信息
        HTML结构: <div class="mediainfo">...<div class="codemain"><pre>...</pre></div></div>
        """
        mediainfo_text = ""

        # 1. 优先尝试最标准的路径
        mediainfo_div = self.soup.select_one("div.mediainfo div.codemain pre")
        if mediainfo_div:
            mediainfo_text = mediainfo_div.get_text(strip=True)

        # 2. 备用：尝试查找 toggle 链接附近的 pre
        else:
            toggle_link = self.soup.find("a",
                                         class_="codetop",
                                         string=re.compile("MediaInfo"))
            if toggle_link:
                container = toggle_link.find_next_sibling("div",
                                                          class_="codemain")
                if container:
                    pre = container.find("pre")
                    if pre:
                        mediainfo_text = pre.get_text(strip=True)

        return mediainfo_text

    def extract_intro(self, subtitle=""):
        """
        提取简介信息，针对KEEPFRDS特殊结构：
        1. 直接提取 fieldset 引用块作为声明 (处理嵌套情况，避免重复)
        2. 从固定位置获取豆瓣链接，使用 PT-Gen 生成正文和海报
        """
        intro = {
            "statement": "",
            "poster": "",
            "body": "",
            "screenshots": "",
            "douban_link": "",
            "imdb_link": ""
        }

        quotes = []

        # 1. 提取声明 (Statement) - 来自 fieldset 标签
        descr_container = self.soup.select_one("div#kdescr")
        if descr_container:
            # 查找该容器下所有的 fieldset
            all_fieldsets = descr_container.find_all("fieldset")

            for fs in all_fieldsets:
                # 【核心修复】检查当前 fieldset 是否被包含在另一个 fieldset 中
                # 如果它有父级 fieldset，说明它是嵌套的，外层处理时已经包含了它的文本
                # 因此这里直接跳过，防止重复
                if fs.find_parent("fieldset"):
                    continue

                # 使用 "\n" 分隔符获取文本，保留换行结构
                text_content = fs.get_text("\n", strip=True)

                lines = text_content.split('\n')
                # 过滤掉内容为 "引用" 的行 (HTML中的 <legend> 引用 </legend>)
                clean_lines = [line for line in lines if line.strip() != "引用"]
                clean_text = "\n".join(clean_lines).strip()

                if clean_text:
                    quotes.append(f"[quote]{clean_text}[/quote]")

        # 2. 提取豆瓣链接 (位置固定)
        douban_link = ""
        kdouban = self.soup.select_one("div#kdouban")
        if kdouban:
            d_link = kdouban.select_one("a[href*='movie.douban.com/subject/']")
            if d_link:
                douban_link = d_link.get("href", "").strip()

        # 如果没找到，尝试全局搜索
        if not douban_link:
            d_link = self.soup.select_one(
                "a[href*='movie.douban.com/subject/']")
            if d_link:
                douban_link = d_link.get("href", "").strip()

        # 3. 提取 IMDb 链接
        imdb_link = ""
        if descr_container:
            text = descr_container.get_text()
            imdb_match = re.search(r"https?://www\.imdb\.com/title/tt\d+",
                                   text)
            if imdb_match:
                imdb_link = imdb_match.group(0)

        intro["douban_link"] = douban_link
        intro["imdb_link"] = imdb_link

        # 4. 使用 ptgen 获取标准信息 (海报 + 正文)
        body = ""
        images = []

        try:
            from utils import upload_data_movie_info
            movie_status, poster_content, description_content, _, _ = upload_data_movie_info(
                "", douban_link, imdb_link, subtitle)

            if movie_status and description_content:
                body = description_content
                if poster_content:
                    images.append(poster_content)
            else:
                print(f"PT-Gen获取电影信息失败: {description_content}")
        except Exception as e:
            print(f"调用PT-Gen时发生错误: {e}")

        # 如果 PT-Gen 失败，尝试手动提取海报
        if not images:
            poster_img = self.soup.select_one("div#kdouban img")
            if poster_img and poster_img.get("src"):
                images.append(f"[img]{poster_img.get('src')}[/img]")

        # 5. 组装结果
        intro["statement"] = "\n\n".join(quotes)
        intro["poster"] = images[0] if images else ""
        intro["body"] = re.sub(r"\n{2,}", "\n", body).strip()

        return intro

    def extract_basic_info(self):
        """
        提取基本信息
        KEEPFRDS基本信息行: 大小, 类型, 来源, 媒介(UNK0), 编码, 分辨率, 处理(UNK0), 制作组
        """
        basic_info_dict = {}

        # 找到包含"基本信息"的行
        row_head = self.soup.find("td", string="基本信息", class_="rowhead")
        if row_head:
            row_follow = row_head.find_next_sibling("td", class_="rowfollow")
            if row_follow:
                elements = list(row_follow.stripped_strings)

                current_key = None
                for elem in elements:
                    # 移除冒号
                    clean_elem = elem.replace("：", "").replace(":", "").strip()

                    if elem.strip().endswith((":", "：")):
                        current_key = clean_elem
                    elif current_key:
                        basic_info_dict[current_key] = clean_elem
                        current_key = None  # 重置，等待下一个键

        # 字段映射与清洗
        mapped_info = {}

        # 1. 媒介处理：KEEPFRDS "来源" (Source) 对应标准 "媒介" (Medium)，忽略 "媒介: UNK0"
        if "来源" in basic_info_dict:
            mapped_info["媒介"] = basic_info_dict["来源"]
        elif "媒介" in basic_info_dict and "UNK" not in basic_info_dict["媒介"]:
            mapped_info["媒介"] = basic_info_dict["媒介"]

        # 2. 视频编码：KEEPFRDS "编码" 对应 "视频编码"
        if "编码" in basic_info_dict:
            mapped_info["视频编码"] = basic_info_dict["编码"]

        # 3. 其他字段直接映射
        mapped_info["类型"] = basic_info_dict.get("类型")
        mapped_info["分辨率"] = basic_info_dict.get("分辨率")
        mapped_info["大小"] = basic_info_dict.get("大小")
        mapped_info["制作组"] = basic_info_dict.get("制作组")

        return mapped_info

    def extract_time_elapsed(self):
        """
        提取发布时间并计算距今的小时数
        """
        try:
            # 查找"发布于"文本节点
            publish_text = self.soup.find(string=re.compile("发布于"))
            if publish_text:
                # 过滤出符合 YYYY-MM-DD HH:MM:SS 格式的 title
                spans = self.soup.find_all(
                    "span",
                    title=re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"))

                target_date = None
                for span in spans:
                    # 确保这个 span 在 "发布于" 附近
                    if span.parent and "发布于" in span.parent.get_text():
                        date_str = span['title']
                        target_date = datetime.datetime.strptime(
                            date_str, "%Y-%m-%d %H:%M:%S")
                        break

                if target_date:
                    now = datetime.datetime.now()
                    diff = now - target_date
                    hours = diff.total_seconds() / 3600
                    return round(hours, 2)

        except Exception as e:
            print(f"计算发布时间间隔出错: {e}")

        return 0

    def extract_titles(self):
        """
        提取标题并互换
        KEEPKEEPFRDS: 主标题(Top H1)是中文，副标题(Row)是英文文件名
        目标: title=英文文件名, subtitle=中文标题
        """
        # 1. 获取 HTML 中的主标题 (中文)
        h1_top = self.soup.select_one("h1#top")
        html_main_title = list(h1_top.stripped_strings)[0] if h1_top else ""
        html_main_title = re.sub(r'\s+', ' ', html_main_title).strip()

        # 2. 获取 HTML 中的副标题 (英文/文件名)
        html_subtitle = ""
        row_head = self.soup.find("td", string="副标题", class_="rowhead")
        if row_head:
            row_follow = row_head.find_next_sibling("td", class_="rowfollow")
            if row_follow:
                html_subtitle = row_follow.get_text(strip=True)

        # 3. 互换逻辑
        if html_subtitle:
            final_title = html_subtitle
            final_subtitle = html_main_title
        else:
            final_title = html_main_title
            final_subtitle = ""

        return final_title, final_subtitle

    def extract_all(self, torrent_id=None):
        """
        提取所有种子信息
        """
        # 1. 提取基本信息
        basic_info = self.extract_basic_info()

        # 2. 提取并互换标题
        main_title, subtitle = self.extract_titles()

        # 3. 提取标签
        tags = TorrentListFetcher.get_tags(self.base_url, self.cookie,
                                           main_title, self.torrent_id)

        if tags is False:
            error_msg = (f"在站点搜索结果中未找到 ID 为 {self.torrent_id} 的种子！"
                         f"可能搜索结果不匹配或种子不存在。停止处理。")
            print(error_msg)
            raise ValueError(error_msg)

        # 4. 提取简介、海报、声明
        intro = self.extract_intro(subtitle)

        # 5. 提取 MediaInfo
        mediainfo = self.extract_mediainfo()

        # 6. 计算发布时长
        hours_elapsed = self.extract_time_elapsed()
        print(f"发布时长: {hours_elapsed}小时")

        # 7. 提取产地
        full_description_text = f"{intro.get('statement', '')}\n{intro.get('body', '')}"
        origin_info = extract_origin_from_description(full_description_text)

        # 构建参数字典
        source_params = {
            "类型": basic_info.get("类型", ""),
            "媒介": basic_info.get("媒介"),
            "视频编码": basic_info.get("视频编码"),
            "音频编码": basic_info.get("音频编码"),
            "分辨率": basic_info.get("分辨率"),
            "制作组": basic_info.get("制作组"),
            # "标签": f"{tags} 至 {24 - hours_elapsed} 小时后",
            "标签": tags,
            "产地": origin_info,
            "__time_elapsed_hours__": hours_elapsed
        }

        extracted_data = {
            "source_params": source_params,
            "title": main_title,
            "subtitle": subtitle,
            "intro": intro,
            "mediainfo": mediainfo,
        }

        return extracted_data
