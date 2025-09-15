# -*- coding: utf-8 -*-
"""
HDHome特殊站点种子详情参数提取器
用于处理HDHome站点特殊结构的种子详情页
"""

import re
from bs4 import BeautifulSoup
from utils import extract_tags_from_mediainfo, extract_origin_from_description


class HDHOMESpecialExtractor:
    """HDHome特殊站点提取器"""

    def __init__(self, soup):
        self.soup = soup

    def extract_mediainfo(self):
        """
        提取MediaInfo信息
        """
        mediainfo_text = ""

        # 查找包含MediaInfo的div元素，具有spoiler-content类
        mediainfo_div = self.soup.find('div', class_='spoiler-content')
        if mediainfo_div:
            # 查找其中的pre标签
            pre_tag = mediainfo_div.find('pre')
            if pre_tag:
                mediainfo_text = pre_tag.get_text().strip()
                return mediainfo_text

        # 如果上面的方法没找到，查找kdescr中的MediaInfo信息
        descr_div = self.soup.find('div', id='kdescr')
        if descr_div:
            # 查找包含MediaInfo的fieldset元素
            mediainfo_fieldsets = descr_div.find_all('fieldset')
            for fieldset in mediainfo_fieldsets:
                legend = fieldset.find('legend')
                if legend and '引用' in legend.get_text():
                    # 获取fieldset中的文本内容
                    mediainfo_text = fieldset.get_text('\n', strip=True)
                    # 移除"引用"标题部分
                    mediainfo_text = mediainfo_text.replace('引用', '', 1).strip()
                    if mediainfo_text.startswith('General'):
                        return mediainfo_text

        # 如果还是没找到，尝试查找所有包含MediaInfo的文本
        if descr_div:
            text_content = descr_div.get_text('\n', strip=False)
            # 查找从General开始到Menu结束的完整MediaInfo内容
            mediainfo_match = re.search(r'General\s[\s\S]*?Menu\s[\s\S]*?(?=\s*◎|\s*其它版本|\s*种子文件|\Z)', text_content)
            if mediainfo_match:
                mediainfo_text = mediainfo_match.group(0).strip()
                return mediainfo_text
            else:
                # 备用方法：查找包含特定格式的文本（如Video ID, Audio ID等）
                mediainfo_match = re.search(r'General[\s\S]*?(?=◎|$)', text_content)
                if mediainfo_match:
                    mediainfo_text = mediainfo_match.group(0).strip()
                    return mediainfo_text

        # 最后的备用方法：在整个页面中查找
        text_content = self.soup.get_text()
        # 查找从General开始到Menu结束的完整MediaInfo内容
        mediainfo_match = re.search(r'General\s[\s\S]*?Menu\s[\s\S]*?(?=\s*◎|\s*其它版本|\s*种子文件|\Z)', text_content)
        if mediainfo_match:
            mediainfo_text = mediainfo_match.group(0).strip()
        else:
            # 备用方法：查找包含特定格式的文本（如Video ID, Audio ID等）
            mediainfo_match = re.search(r'General[\s\S]*?(?=◎|$)', text_content)
            if mediainfo_match:
                mediainfo_text = mediainfo_match.group(0).strip()

        return mediainfo_text

    def extract_intro(self):
        """
        提取简介信息
        """
        intro = {}
        quotes = []
        images = []
        body = ""
        screenshots = []

        # 查找描述div
        description_div = self.soup.find('div', id='kdescr')
        if not description_div:
            # 如果没有找到kdescr，直接返回空的intro
            return {
                "statement": "",
                "poster": "",
                "body": "",
                "screenshots": "",
            }

        # 1. 提取声明信息（blockquote和fieldset）
        # 提取blockquote元素
        for blockquote in description_div.find_all('blockquote'):
            quote_content = blockquote.get_text("\n", strip=True)
            if quote_content:
                quotes.append(f"[quote]{quote_content}[/quote]")

        # 提取包含"引用"的fieldset元素作为声明
        for fieldset in description_div.find_all('fieldset'):
            legend = fieldset.find('legend')
            if legend and '引用' in legend.get_text():
                # 排除MediaInfo的fieldset（通过检查是否包含General）
                fieldset_text = fieldset.get_text("\n", strip=True)
                if 'General' not in fieldset_text:
                    # 获取fieldset内容，移除"引用"标题
                    quote_content = fieldset_text.replace('引用', '', 1).strip()
                    if quote_content:
                        quotes.append(f"[quote]{quote_content}[/quote]")

        # 2. 提取海报
        # 查找所有具有douban链接的图片
        poster_imgs = description_div.find_all('img', src=re.compile(r'doubanio\.com'))
        for img in poster_imgs:
            src = img.get('src')
            if src:
                images.append(f"[img]{src.strip()}[/img]")

        # 如果没有找到豆瓣图片，查找其他可能的海报图片（第一个img标签）
        if not images:
            first_img = description_div.find('img')
            if first_img and first_img.get('src'):
                images.append(f"[img]{first_img['src'].strip()}[/img]")

        # 3. 提取截图
        # 查找所有vlcsnap开头的图片链接
        screenshot_imgs = description_div.find_all('img', src=re.compile(r'vlcsnap'))
        for img in screenshot_imgs:
            src = img.get('src')
            if src:
                screenshots.append(f"[img]{src.strip()}[/img]")

        # 4. 提取IMDb和豆瓣链接
        imdb_link = self.extract_imdb_info()
        douban_link = self.extract_douban_info()

        # 5. 提取完整的正文内容（不包括MediaInfo和截图）
        # 克隆description_div以避免修改原始DOM
        from copy import deepcopy
        description_div_clone = deepcopy(description_div)

        # 如果deepcopy不可用，创建新的BeautifulSoup对象
        if not description_div_clone:
            description_div_clone = BeautifulSoup(str(description_div), 'html.parser')

        # 移除blockquote元素
        for blockquote in description_div_clone.find_all('blockquote'):
            blockquote.decompose()

        # 移除包含MediaInfo的fieldset元素
        for fieldset in description_div_clone.find_all('fieldset'):
            legend = fieldset.find('legend')
            if legend and '引用' in legend.get_text():
                fieldset_text = fieldset.get_text("\n", strip=True)
                if 'General' in fieldset_text:
                    fieldset.decompose()

        # 移除图片标签（但保留截图信息）
        # 先收集截图信息
        vlcsnap_imgs = description_div_clone.find_all('img', src=re.compile(r'vlcsnap'))
        for img in vlcsnap_imgs:
            img.decompose()

        # 移除其他图片标签
        for img in description_div_clone.find_all('img'):
            img.decompose()

        # 移除br标签
        for br in description_div_clone.find_all('br'):
            br.decompose()

        # 获取剩余的文本内容
        remaining_text = description_div_clone.get_text("\n", strip=False)

        # 清理文本内容
        lines = remaining_text.split('\n')
        cleaned_lines = []
        for line in lines:
            stripped_line = line.strip()
            # 过滤掉空行和只包含符号的行
            if stripped_line and not re.match(r'^[■◆●▲▼▶◀◀■◆●▲▼▶]*$', stripped_line):
                cleaned_lines.append(stripped_line)

        body = '\n'.join(cleaned_lines)

        # 移除可能残留的"引用"字样
        body = re.sub(r'^引用\s*', '', body).strip()

        # 移除多余的空行
        body = re.sub(r"\n{2,}", "\n", body).strip()

        # 确保获取从"◎译　　名"开始的完整内容
        intro_start_match = re.search(r'◎译　　名', body)
        if intro_start_match:
            body = body[intro_start_match.start():]

        # 如果没有找到标准格式，尝试其他方法获取内容
        if not body or '◎译　　名' not in body:
            # 获取description_div中的所有文本内容
            full_text = description_div.get_text("\n", strip=False)
            # 查找简介开始位置
            intro_start_match = re.search(r'◎译　　名', full_text)
            if intro_start_match:
                body = full_text[intro_start_match.start():].strip()
            else:
                # 最后的备用方法
                body = full_text.strip()

        intro = {
            "statement": "\n".join(quotes),
            "poster": "\n".join(images) if images else "",
            "body": body,
            "screenshots": "\n".join(screenshots),
        }
        return intro

    def extract_basic_info(self):
        """
        提取基本信息
        """
        basic_info_dict = {}

        # 查找包含基本信息的表格行
        rows = self.soup.find_all('tr')
        for row in rows:
            cells = row.find_all(['td', 'th'])
            if len(cells) >= 2:
                key = cells[0].get_text(strip=True)
                value = cells[1].get_text(strip=True)

                # 字段映射
                if "大小" in key: basic_info_dict["大小"] = value
                elif "类型" in key: basic_info_dict["类型"] = value
                elif "来源" in key: basic_info_dict["来源"] = value
                elif "媒介" in key: basic_info_dict["媒介"] = value
                elif "编码" in key: basic_info_dict["编码"] = value
                elif "音频编码" in key: basic_info_dict["音频编码"] = value
                elif "分辨率" in key: basic_info_dict["分辨率"] = value
                elif "制作组" in key: basic_info_dict["制作组"] = value

        return basic_info_dict

    def extract_tags(self):
        """
        提取标签
        """
        tags = []
        # 查找具有tags类的span元素
        tag_elements = self.soup.find_all('span', class_=re.compile(r'tags|tag'))
        for tag_element in tag_elements:
            tag_text = tag_element.get_text(strip=True)
            if tag_text and tag_text not in tags:
                tags.append(tag_text)
        return tags

    def extract_subtitle(self):
        """
        提取副标题
        """
        # 查找副标题行
        subtitle_rows = self.soup.find_all('td', string=re.compile(r'副标题'))
        for row in subtitle_rows:
            next_td = row.find_next_sibling('td')
            if next_td:
                return next_td.get_text(strip=True)
        return ""

    def extract_douban_info(self):
        """
        提取豆瓣信息
        """
        # 查找豆瓣链接
        douban_link_tag = self.soup.find('a', href=re.compile(r'movie\.douban\.com/subject'))
        if douban_link_tag:
            return douban_link_tag.get('href', '')

        # 备用方法：在文本中搜索
        text_content = self.soup.get_text()
        douban_match = re.search(r'https?://movie\.douban\.com/subject/\d+', text_content)
        if douban_match:
            return douban_match.group(0)
        return ""

    def extract_imdb_info(self):
        """
        提取IMDb信息
        """
        # 查找IMDb链接
        imdb_link_tag = self.soup.find('a', href=re.compile(r'imdb\.com/title/tt'))
        if imdb_link_tag:
            return imdb_link_tag.get('href', '')

        # 备用方法：在文本中搜索
        text_content = self.soup.get_text()
        imdb_match = re.search(r'https?://www\.imdb\.com/title/tt\d+', text_content)
        if imdb_match:
            return imdb_match.group(0)
        return ""

    def extract_title(self):
        """
        提取主标题
        """
        # 查找h1标题
        h1_title = self.soup.find('h1')
        if h1_title:
            return h1_title.get_text(strip=True)
        return ""

    def extract_all(self, torrent_id=None):
        """
        提取所有种子信息
        """
        basic_info = self.extract_basic_info()
        tags = self.extract_tags()
        subtitle = self.extract_subtitle()
        intro = self.extract_intro()
        mediainfo = self.extract_mediainfo()
        douban_info = self.extract_douban_info()
        imdb_info = self.extract_imdb_info()
        main_title = self.extract_title()

        full_description_text = f"{intro.get('statement', '')}\n{intro.get('body', '')}"
        origin_info = extract_origin_from_description(full_description_text)

        source_params = {
            "类型": basic_info.get("类型", ""),
            "媒介": basic_info.get("媒介"),
            "编码": basic_info.get("编码"),
            "音频编码": basic_info.get("音频编码"),
            "分辨率": basic_info.get("分辨率"),
            "制作组": basic_info.get("制作组"),
            "标签": tags,
            "产地": origin_info,
        }

        intro["douban_link"] = douban_info
        intro["imdb_link"] = imdb_info

        extracted_data = {
            "source_params": source_params,
            "subtitle": subtitle,
            "intro": intro,
            "mediainfo": mediainfo,
            "title": main_title
        }

        if torrent_id:
            try:
                import os, json
                from config import TEMP_DIR
                save_dir = os.path.join(TEMP_DIR, "extracted_data")
                os.makedirs(save_dir, exist_ok=True)
                save_path = os.path.join(
                    save_dir, f"hdhome_extracted_{torrent_id}.json")
                with open(save_path, "w", encoding="utf-8") as f:
                    json.dump(extracted_data, f, ensure_ascii=False, indent=2)
                print(f"提取的数据已保存到: {save_path}")
            except Exception as e:
                print(f"保存提取数据时出错: {e}")

        return extracted_data