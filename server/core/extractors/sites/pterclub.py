import re
import os
import yaml
import datetime
import uuid
from bs4 import BeautifulSoup
from utils import extract_tags_from_mediainfo, extract_origin_from_description, validate_media_info_format
from utils import TorrentListFetcher
from config import GLOBAL_MAPPINGS

# 加载内容过滤配置
CONTENT_FILTERING_CONFIG = {}
try:
    if os.path.exists(GLOBAL_MAPPINGS):
        with open(GLOBAL_MAPPINGS, 'r', encoding='utf-8') as f:
            global_config = yaml.safe_load(f)
            CONTENT_FILTERING_CONFIG = global_config.get(
                "content_filtering", {})
    else:
        print(f"警告：配置文件不存在: {GLOBAL_MAPPINGS}")
except Exception as e:
    print(f"警告：无法加载内容过滤配置: {e}")


class PTerClubSpecialExtractor:
    """PTerClub特殊站点提取器 - 修复版"""

    def __init__(self, soup, base_url, cookie, torrent_id):
        print("PTerClub特殊站点提取器初始化")
        self.soup = soup
        self.base_url = base_url
        self.cookie = cookie
        self.torrent_id = torrent_id

    def save_html_for_debug(self):
        """保存详情页完整HTML到临时目录用于调试"""
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            unique_id = str(uuid.uuid4())[:8]
            filename = f"pterclub_{self.torrent_id}_{timestamp}_{unique_id}.html"
            tmp_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "data", "tmp")
            filepath = os.path.join(tmp_dir, filename)
            os.makedirs(tmp_dir, exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(str(self.soup))
            print(f"调试：详情页HTML已保存到 {filepath}")
            return filepath
        except Exception as e:
            print(f"保存HTML文件时出错: {e}")
            return None

    def extract_mediainfo(self):
        """
        提取MediaInfo信息 - 针对无<pre>标签的情况进行修复
        HTML结构: 
        <div class="codetop"><a>mediainfo - ...</a></div>
        <div class="hide"><div class="codemain">Line1<br>Line2...</div></div>
        """
        mediainfo_text = ""

        # 1. 查找包含 "mediainfo" 字样的 codetop 头部
        # 使用 lambda 函数进行更宽泛的搜索，防止因标签嵌套导致 string 匹配失败
        mt_header = self.soup.find(
            lambda tag: tag.name == "div" and "codetop" in tag.get(
                "class", []) and "mediainfo" in tag.get_text().lower())

        if mt_header:
            # 找到头部后，查找紧接着的隐藏区域
            hide_div = mt_header.find_next_sibling("div", class_="hide")
            if hide_div:
                codemain = hide_div.find("div", class_="codemain")
                if codemain:
                    # 【核心修复】PTerClub 此处没有使用 <pre>，而是使用 <br> 换行
                    # 使用 separator="\n" 将 <br> 转换为换行符提取纯文本
                    mediainfo_text = codemain.get_text(separator="\n",
                                                       strip=True)

        # 2. 如果方法1失败，尝试全局搜索包含 MediaInfo 关键词的 codemain
        if not mediainfo_text:
            codemains = self.soup.find_all("div", class_="codemain")
            for div in codemains:
                text = div.get_text(separator="\n", strip=True)
                # 简单的特征检测
                if "Unique ID" in text and "Video" in text:
                    mediainfo_text = text
                    break

        return mediainfo_text

    def extract_intro(self, subtitle=""):
        """
        提取简介信息 - 修复 AttributeError 问题，增加防御性判断
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
        descr_container = self.soup.select_one("div#kdescr")

        if descr_container:
            # 提取 fieldset 引用
            all_fieldsets = descr_container.find_all("fieldset")
            for fs in all_fieldsets:
                if fs.find_parent("fieldset"):
                    continue
                text_content = fs.get_text("\n", strip=True)
                lines = text_content.split('\n')
                clean_lines = [line for line in lines if line.strip() != "引用"]
                clean_text = "\n".join(clean_lines).strip()
                if clean_text:
                    quotes.append(f"[quote]{clean_text}[/quote]")

        # --- 修复开始：提取豆瓣/IMDb链接 (增加防御性逻辑) ---
        douban_link = ""
        imdb_link = ""

        # 1. 提取豆瓣链接
        # 增加条件：必须包含"豆瓣链接"，且文本长度较短（防止匹配到大段文本容器），最好有 rowhead 类
        douban_row = self.soup.find(
            lambda tag: tag.name == "td" and "豆瓣链接" in tag.get_text() and len(
                tag.get_text(strip=True)) < 10)

        if douban_row:
            # 分步获取，防止 None.find() 报错
            douban_value_td = douban_row.find_next_sibling("td")
            if douban_value_td:
                link_a = douban_value_td.find("a", href=True)
                if link_a:
                    douban_link = link_a['href']

        # 2. 提取 IMDb 链接
        imdb_row = self.soup.find(
            lambda tag: tag.name == "td" and "IMDb链接" in tag.get_text(
            ) and len(tag.get_text(strip=True)) < 10)

        if imdb_row:
            imdb_value_td = imdb_row.find_next_sibling("td")
            if imdb_value_td:
                link_a = imdb_value_td.find("a", href=True)
                if link_a:
                    imdb_link = link_a['href']

        # 如果没找到，尝试在全文链接中搜索兜底
        if not douban_link:
            d_link = self.soup.select_one(
                "a[href*='movie.douban.com/subject/']")
            if d_link:
                douban_link = d_link.get("href", "").strip()

        if not imdb_link:
            i_link = self.soup.select_one("a[href*='imdb.com/title/tt']")
            if i_link:
                imdb_link = i_link.get("href", "").strip()
        # --- 修复结束 ---

        intro["douban_link"] = douban_link
        intro["imdb_link"] = imdb_link

        # 使用 ptgen 获取标准信息
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
        except Exception as e:
            print(f"PT-Gen错误: {e}")

        # 手动提取海报作为备用
        if not images and descr_container:
            first_img = descr_container.find("img")
            if first_img and first_img.get("src"):
                images.append(f"[img]{first_img.get('src')}[/img]")

        # 提取截图
        screenshots = []
        if descr_container:
            imgs = descr_container.find_all("img")
            for img in imgs[1:]:
                src = img.get("src") or img.get("data-src")
                if src:
                    screenshots.append(f"[img]{src}[/img]")

        intro["statement"] = "\n\n".join(quotes)
        intro["poster"] = images[0] if images else ""
        intro["body"] = re.sub(r"\n{2,}", "\n", body).strip()
        intro["screenshots"] = "\n".join(screenshots)

        return intro

    def extract_basic_info(self):
        """提取基本信息"""
        basic_info_dict = {}
        # 更精确的定位：查找包含"基本信息"且class为rowhead的td
        row_head = self.soup.find("td",
                                  class_="rowhead",
                                  string=re.compile("基本信息"))

        if row_head:
            row_follow = row_head.find_next_sibling("td", class_="rowfollow")
            if row_follow:
                text = row_follow.get_text(" ", strip=True)  # 使用空格连接文本
                # 解析类似 "大小：7.30 GB 类型: 电影..." 的字符串
                # 处理冒号不同的情况
                parts = re.split(r'\s+([^\s：:]+[:：])', text)

                current_key = None
                for part in parts:
                    part = part.strip()
                    if not part: continue

                    if part.endswith((":", "：")):
                        current_key = part[:-1]
                    elif current_key:
                        basic_info_dict[current_key] = part
                        current_key = None

        mapped_info = {}
        mapped_info["类型"] = basic_info_dict.get("类型")
        mapped_info["媒介"] = basic_info_dict.get("质量")
        mapped_info["视频编码"] = basic_info_dict.get("视频编码")  # PTer通常不直接在基本信息显示编码
        mapped_info["音频编码"] = basic_info_dict.get("音频编码")
        mapped_info["分辨率"] = basic_info_dict.get("分辨率")
        mapped_info["大小"] = basic_info_dict.get("大小")
        mapped_info["制作组"] = basic_info_dict.get("制作组")

        return mapped_info

    def extract_titles(self):
        """提取标题"""
        h1_top = self.soup.select_one("h1#top")
        main_title = h1_top.get_text(strip=True) if h1_top else ""

        subtitle = ""
        row_head = self.soup.find("td", class_="rowhead", string="副标题")
        if row_head:
            row_follow = row_head.find_next_sibling("td")
            if row_follow:
                subtitle = row_follow.get_text(strip=True)

        return main_title, subtitle

    def extract_tags(self):
        """
        提取标签信息 - 修复版
        目标 HTML: <td class="rowfollow">...<a class="chs_tag chs_tag-sub details-tag">中字</a></td>
        """
        tags = []

        # 1. 定位 "类别与标签" 行
        # 使用更灵活的查找方式
        tags_row_head = self.soup.find("td",
                                       class_="rowhead",
                                       string=re.compile(r"类别与标签"))

        if tags_row_head:
            tags_td = tags_row_head.find_next_sibling("td", class_="rowfollow")
            if tags_td:
                # 方法 A: 提取带有 chs_tag 类的链接文本 (如: 中字, 官方, 国语)
                tag_links = tags_td.find_all("a", class_=re.compile("chs_tag"))
                for link in tag_links:
                    tags.append(link.get_text(strip=True))

                # 方法 B (可选): 提取图片的 alt 信息作为标签 (如: KOR, Encode)
                # 根据需要决定是否开启，通常这里包含地区和媒介信息
                imgs = tags_td.find_all("img")
                for img in imgs:
                    alt = img.get("alt", "").strip()
                    # 过滤掉纯分类图片 (如 "电影 (Movie)")，保留一些特殊的标识
                    if alt and "Movie" not in alt and "TV" not in alt:
                        # 比如提取 "KOR"
                        tags.append(alt)

        # 去重并清理空值
        unique_tags = []
        for tag in tags:
            t = tag.strip()
            if t and t not in unique_tags:
                unique_tags.append(t)

        return unique_tags

    def extract_category(self):
        """
        提取分类、质量、地区
        PTerClub 在"类别与标签"行使用图片 alt 属性来展示这些信息
        """
        category = ""
        quality = ""
        region = ""

        # 定位行
        cat_row = self.soup.find("td",
                                 class_="rowhead",
                                 string=re.compile(r"类别与标签"))
        if cat_row:
            cat_td = cat_row.find_next_sibling("td")
            if cat_td:
                # 遍历该单元格内的所有图片，根据 href 或 alt 判断
                links = cat_td.find_all("a")
                for link in links:
                    href = link.get("href", "")
                    img = link.find("img")
                    alt_text = img.get("alt", "") if img else ""

                    if "cat=" in href:
                        # 提取分类，例如 "电影 (Movie)" -> "电影"
                        category = alt_text.split("(")[0].strip()
                    elif "source" in href:
                        # 提取质量/媒介，例如 "Encode"
                        quality = alt_text
                    elif "team" in href:
                        # 提取地区，例如 "KOR"
                        region = alt_text

        # 如果上方未提取到，尝试从"基本信息"文本中补全
        if not quality or not region:
            basic_row = self.soup.find("td", class_="rowhead", string="基本信息")
            if basic_row:
                text = basic_row.find_next_sibling("td").get_text()
                if not quality:
                    m = re.search(r"质量:\s*([^\s]+)", text)
                    if m: quality = m.group(1)
                if not region:
                    m = re.search(r"地区:\s*([^\s]+)", text)
                    if m: region = m.group(1)

        return {"类型": category, "质量": quality, "地区": region}

    def extract_all(self, torrent_id=None):
        """提取所有种子信息"""
        self.save_html_for_debug()  # 保存以备查错

        basic_info = self.extract_basic_info()
        main_title, subtitle = self.extract_titles()
        tags = self.extract_tags()
        category = self.extract_category()
        intro = self.extract_intro(subtitle)
        mediainfo = self.extract_mediainfo()

        # 尝试从标题中补充解析编码信息，因为PTerClub基本信息里可能没有详细编码
        video_codec = basic_info.get("视频编码", "")
        if not video_codec:
            if "x265" in main_title.lower() or "hevc" in main_title.lower():
                video_codec = "x265"
            elif "x264" in main_title.lower() or "avc" in main_title.lower():
                video_codec = "x264"

        full_description_text = f"{intro.get('statement', '')}\n{intro.get('body', '')}"
        origin_info = extract_origin_from_description(full_description_text)

        source_params = {
            "类型": basic_info.get("类型", category.get("类型")),
            "媒介": basic_info.get("媒介", category.get("质量")),
            "视频编码": video_codec,
            "音频编码": basic_info.get("音频编码"),
            "分辨率": basic_info.get("分辨率"),
            "制作组": basic_info.get("制作组"),
            "标签": tags,
            "分类": category,
            "产地": origin_info,
        }

        extracted_data = {
            "source_params": source_params,
            "title": main_title,
            "subtitle": subtitle,
            "intro": intro,
            "mediainfo": mediainfo,
        }

        return extracted_data
