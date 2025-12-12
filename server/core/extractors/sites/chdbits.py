from bs4 import BeautifulSoup
from typing import Dict, Any
from utils import TorrentListFetcher


class CHDBitsSpecialExtractor:
    """CHDBits 站点的特殊提取器 - 仅用于特殊的 tag 提取，其他信息使用公共提取器"""

    def __init__(self, soup: BeautifulSoup, base_url: str, cookie: str,
                 torrent_id: str):
        """
        初始化 CHDBits 特殊提取器
        
        Args:
            soup: BeautifulSoup 对象
            base_url: 站点基础 URL
            cookie: 站点 Cookie
            torrent_id: 种子 ID
        """
        print("CHDBits 特殊站点提取器初始化")
        self.soup = soup
        self.base_url = base_url
        self.cookie = cookie
        self.torrent_id = torrent_id

    def extract_tags(self, main_title: str):
        """
        使用特殊方法提取标签
        
        Args:
            main_title: 主标题（用于在搜索结果中定位种子）
            
        Returns:
            标签列表或 False（如果未找到种子）
        """
        tags = TorrentListFetcher.get_tags(self.base_url, self.cookie,
                                           main_title, self.torrent_id, "彩虹岛")

        if tags is False:
            error_msg = (f"在站点搜索结果中未找到 ID 为 {self.torrent_id} 的种子！"
                         f"可能搜索结果不匹配或种子不存在。停止处理。")
            print(error_msg)
            raise ValueError(error_msg)

        return tags

    def extract_all(self, torrent_id=None):
        """
        提取所有种子信息
        这个方法会被 extractor.py 调用
        
        优化逻辑：先提取标题和标签，如果标签提取失败则立即停止，避免浪费资源
        
        Returns:
            包含提取数据的字典，其中 tags 使用特殊方法获取
        """
        # 导入公共提取器
        from ..extractor import Extractor

        # [优化] 步骤1: 先只提取标题（最小开销）
        print("[CHDBits] 步骤1: 提取标题...")
        h1_top = self.soup.select_one("h1#top")
        if not h1_top:
            error_msg = "未找到标题元素"
            print(f"[CHDBits] 错误: {error_msg}")
            return {"error": True, "message": error_msg}

        main_title = list(
            h1_top.stripped_strings)[0] if h1_top.stripped_strings else ""
        if not main_title:
            error_msg = "标题为空"
            print(f"[CHDBits] 错误: {error_msg}")
            return {"error": True, "message": error_msg}

        # 标准化标题
        import re
        main_title = re.sub(r'(?<!\d)(?<!H)(?<!x)\.|\.(?!\d\b)(?!264)(?!265)',
                            ' ', main_title)
        main_title = re.sub(r'\s+', ' ', main_title).strip()
        print(f"[CHDBits] 成功提取标题: {main_title}")

        # [优化] 步骤2: 立即提取标签，如果失败则停止
        print("[CHDBits] 步骤2: 提取标签...")
        try:
            special_tags = self.extract_tags(main_title)

            # 过滤掉指定的标签
            filtered_tags = []
            unwanted_tags = ["官方", "官种", "首发", "自购", "自抓", "应求"]
            for tag in special_tags:
                if tag not in unwanted_tags:
                    filtered_tags.append(tag)

            # 去重处理，保持顺序
            if filtered_tags:
                filtered_tags = list(dict.fromkeys(filtered_tags))

            print(f"[CHDBits] 成功提取标签: {filtered_tags}")

        except ValueError as e:
            # 如果标签提取失败，立即返回错误，不再继续提取其他信息
            print(f"[CHDBits] 标签提取失败，停止处理: {e}")
            return {"error": True, "message": str(e)}

        # [优化] 步骤3: 标签验证成功后，才提取其他所有信息
        print("[CHDBits] 步骤3: 标签验证成功，开始提取其他信息...")
        public_extractor = Extractor()
        extracted_data = public_extractor._extract_with_public_extractor(
            self.soup)

        # 更新标题（使用已经提取并标准化的标题）
        extracted_data["title"] = main_title

        # 更新标签（使用特殊方法提取的标签）
        extracted_data["source_params"]["标签"] = filtered_tags

        print(f"[CHDBits] 所有信息提取完成")

        return extracted_data
