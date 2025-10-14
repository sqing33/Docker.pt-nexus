"""
Haidan站点特殊下载器
处理haidan.video站点的种子下载链接提取
"""
import re
from typing import Optional, Any
from bs4 import BeautifulSoup
from loguru import logger

from ..base_downloader import BaseDownloader


class HaidanDownloader(BaseDownloader):
    """
    Haidan站点下载器
    处理haidan.video站点的特殊下载链接提取逻辑
    """

    def extract_download_link(self, detail_page_html: str,
                              upload_title: str) -> Optional[str]:
        """
        从haidan详情页HTML中提取下载链接
        
        Args:
            detail_page_html: 详情页HTML内容
            upload_title: 上传的种子标题
            
        Returns:
            下载链接URL，如果未找到则返回None
        """
        try:
            soup = BeautifulSoup(detail_page_html, 'html.parser')

            # 方法1: 查找包含"新"标记的种子（最高优先级）
            download_link = self._find_new_torrent_in_torrents_container(soup)
            if download_link:
                print(f"通过新标记找到下载链接: {download_link}")
                return download_link

            # 方法2: 通过标题精确匹配
            download_link = self._find_torrent_by_title_match(
                soup, upload_title)
            if download_link:
                print(f"通过标题匹配找到下载链接: {download_link}")
                return download_link

            # 方法3: 查找最新的种子（通过发布时间）
            download_link = self._find_newest_torrent_by_time(soup)
            if download_link:
                print(f"通过时间排序找到最新下载链接: {download_link}")
                return download_link

            # 方法4: 查找第一个种子（作为最后备选）
            download_link = self._find_first_torrent(soup)
            if download_link:
                print(f"使用第一个种子作为备选: {download_link}")
                return download_link

            print("未能找到任何种子下载链接")
            return None

        except Exception as e:
            print(f"提取haidan下载链接时发生错误: {e}")
            return None

    def _find_torrent_by_title_match(self, soup: BeautifulSoup,
                                     target_title: str) -> Optional[str]:
        """
        通过标题匹配找到对应的种子下载链接
        
        Args:
            soup: BeautifulSoup对象
            target_title: 目标种子标题
            
        Returns:
            下载链接URL，如果未找到则返回None
        """
        try:
            # 查找所有种子条目
            torrent_wraps = soup.find_all('div', class_='torrent-wrap')

            target_normalized = self._normalize_title(target_title)
            print(f"目标标题标准化: {target_normalized}")

            for torrent_wrap in torrent_wraps:
                # 查找种子标题
                torrent_name_elem = torrent_wrap.find(
                    'a', href=re.compile(r'javascript: viewDetail\(\d+\)'))
                if not torrent_name_elem:
                    continue

                torrent_title = torrent_name_elem.get_text(strip=True)
                torrent_normalized = self._normalize_title(torrent_title)
                print(f"种子标题: {torrent_title} -> 标准化: {torrent_normalized}")

                # 检查标题匹配度
                if self._is_title_match(target_normalized, torrent_normalized):
                    # 找到匹配的种子，获取下载链接
                    download_link = self._extract_download_link_from_wrap(
                        torrent_wrap)
                    if download_link:
                        print(f"标题匹配成功: {torrent_title}")
                        return download_link

            return None

        except Exception as e:
            print(f"通过标题匹配查找下载链接时发生错误: {e}")
            return None

    def _find_new_torrent_in_torrents_container(
            self, soup: BeautifulSoup) -> Optional[str]:
        """
        在torrents容器内查找包含"新"标记的最新种子
        
        Args:
            soup: BeautifulSoup对象
            
        Returns:
            下载链接URL，如果未找到则返回None
        """
        try:
            # 首先查找torrents容器
            torrents_container = soup.find('div',
                                           class_='torrents content-color')
            if not torrents_container:
                print("未找到torrents容器，回退到全局搜索")
                return self._find_new_torrent_by_new_marker(soup)

            # 在容器内查找所有种子条目
            torrent_wraps = torrents_container.find_all('div',
                                                        class_='torrent-wrap')
            print(f"在torrents容器内找到 {len(torrent_wraps)} 个种子条目")

            # 优先查找包含"新"标记的种子
            new_torrents = []
            for torrent_wrap in torrent_wraps:
                # 查找包含"新"字样的元素
                new_marker = torrent_wrap.find('font', class_='new')
                if new_marker and new_marker.get_text(strip=True) == '新':
                    new_torrents.append(torrent_wrap)
                    print("找到包含'新'标记的种子")

            if new_torrents:
                # 如果有多个新种子，选择最后一个（通常是最新的）
                newest_torrent = new_torrents[-1]
                download_link = self._extract_download_link_from_wrap(
                    newest_torrent)
                if download_link:
                    print("在torrents容器内找到包含'新'标记的最新种子")
                    return download_link

            # 如果没有找到新标记的种子，查找最近发布的种子
            return self._find_newest_torrent_in_container(torrents_container)

        except Exception as e:
            print(f"在torrents容器内查找新标记种子时发生错误: {e}")
            return None

    def _find_newest_torrent_in_container(self, container) -> Optional[str]:
        """
        在指定容器内通过相对时间找到最新的种子
        
        Args:
            container: BeautifulSoup容器元素
            
        Returns:
            下载链接URL，如果未找到则返回None
        """
        try:
            torrent_wraps = container.find_all('div', class_='torrent-wrap')
            newest_torrent = None
            newest_relative_time = None

            for torrent_wrap in torrent_wraps:
                # 查找相对时间文本，如"2分前"、"1小时前"等
                time_elem = torrent_wrap.find(
                    'span',
                    title=re.compile(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}'))
                if not time_elem:
                    continue

                # 获取相对时间文本
                relative_time_text = time_elem.get_text(strip=True)
                print(f"找到相对时间: {relative_time_text}")

                # 解析相对时间，转换为分钟数
                minutes_ago = self._parse_relative_time(relative_time_text)
                if minutes_ago is None:
                    continue

                # 更新最新的种子（分钟数越小越新）
                if newest_relative_time is None or minutes_ago < newest_relative_time:
                    newest_relative_time = minutes_ago
                    newest_torrent = torrent_wrap

            if newest_torrent:
                download_link = self._extract_download_link_from_wrap(
                    newest_torrent)
                if download_link:
                    print(f"在容器内找到最新种子，相对时间: {newest_relative_time} 分钟前")
                    return download_link

            return None

        except Exception as e:
            print(f"在容器内查找最新种子时发生错误: {e}")
            return None

    def _parse_relative_time(self, relative_time_text: str) -> Optional[int]:
        """
        解析相对时间文本，转换为分钟数
        
        Args:
            relative_time_text: 相对时间文本，如"2分前"、"1小时前"、"3天前"
            
        Returns:
            分钟数，如果解析失败则返回None
        """
        try:
            # 匹配不同时间单位
            patterns = [
                (r'(\d+)分前', 1),  # 分钟
                (r'(\d+)分钟前', 1),  # 分钟
                (r'(\d+)小时前', 60),  # 小时
                (r'(\d+)天前', 60 * 24),  # 天
                (r'(\d+)周前', 60 * 24 * 7),  # 周
                (r'(\d+)月前', 60 * 24 * 30),  # 月
                (r'(\d+)年前', 60 * 24 * 365),  # 年
            ]

            for pattern, multiplier in patterns:
                match = re.search(pattern, relative_time_text)
                if match:
                    number = int(match.group(1))
                    return number * multiplier

            return None

        except Exception as e:
            print(f"解析相对时间时发生错误: {e}")
            return None

    def _find_new_torrent_by_new_marker(self,
                                        soup: BeautifulSoup) -> Optional[str]:
        """
        查找包含"新"标记的种子（全局搜索，作为备选方法）
        
        Args:
            soup: BeautifulSoup对象
            
        Returns:
            下载链接URL，如果未找到则返回None
        """
        try:
            # 查找包含"新"标记的种子条目
            torrent_wraps = soup.find_all('div', class_='torrent-wrap')

            for torrent_wrap in torrent_wraps:
                # 查找包含"新"字样的元素
                new_marker = torrent_wrap.find('font', class_='new')
                if new_marker and new_marker.get_text(strip=True) == '新':
                    # 找到新种子，获取下载链接
                    download_link = self._extract_download_link_from_wrap(
                        torrent_wrap)
                    if download_link:
                        print("通过全局搜索找到包含'新'标记的种子")
                        return download_link

            return None

        except Exception as e:
            print(f"全局查找新标记种子时发生错误: {e}")
            return None

    def _find_newest_torrent_by_time(self,
                                     soup: BeautifulSoup) -> Optional[str]:
        """
        通过发布时间找到最新的种子
        
        Args:
            soup: BeautifulSoup对象
            
        Returns:
            下载链接URL，如果未找到则返回None
        """
        try:
            torrent_wraps = soup.find_all('div', class_='torrent-wrap')
            newest_torrent = None
            newest_time = None

            for torrent_wrap in torrent_wraps:
                # 查找发布时间
                time_elem = torrent_wrap.find(
                    'span',
                    title=re.compile(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}'))
                if not time_elem:
                    continue

                time_text = time_elem.get('title', '')
                # 解析时间字符串
                time_match = re.search(
                    r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', time_text)
                if not time_match:
                    continue

                current_time = time_match.group(1)

                # 更新最新的种子
                if newest_time is None or current_time > newest_time:
                    newest_time = current_time
                    newest_torrent = torrent_wrap

            if newest_torrent:
                download_link = self._extract_download_link_from_wrap(
                    newest_torrent)
                if download_link:
                    print(f"找到最新种子，发布时间: {newest_time}")
                    return download_link

            return None

        except Exception as e:
            print(f"通过时间查找最新种子时发生错误: {e}")
            return None

    def _find_first_torrent(self, soup: BeautifulSoup) -> Optional[str]:
        """
        查找第一个种子（作为备选方案）
        
        Args:
            soup: BeautifulSoup对象
            
        Returns:
            下载链接URL，如果未找到则返回None
        """
        try:
            torrent_wrap = soup.find('div', class_='torrent-wrap')
            if torrent_wrap:
                download_link = self._extract_download_link_from_wrap(
                    torrent_wrap)
                if download_link:
                    print("使用第一个种子作为备选方案")
                    return download_link

            return None

        except Exception as e:
            print(f"查找第一个种子时发生错误: {e}")
            return None

    def _extract_download_link_from_wrap(self, torrent_wrap) -> Optional[str]:
        """
        从种子条目中提取下载链接
        
        Args:
            torrent_wrap: 种子条目元素
            
        Returns:
            下载链接URL，如果未找到则返回None
        """
        try:
            # 查找下载链接
            download_links = torrent_wrap.find_all(
                'a', href=re.compile(r'download\.php\?id=\d+'))

            for link in download_links:
                href = link.get('href', '')
                if 'download.php' in href and 'id=' in href:
                    # 确保是完整的URL
                    if href.startswith('http'):
                        return href
                    elif href.startswith('/'):
                        return f"https://www.haidan.video{href}"
                    else:
                        return f"https://www.haidan.video/{href}"

            return None

        except Exception as e:
            print(f"提取下载链接时发生错误: {e}")
            return None

    def _is_title_match(self, target: str, source: str) -> bool:
        """
        判断两个标题是否匹配
        
        Args:
            target: 目标标题（标准化后）
            source: 源标题（标准化后）
            
        Returns:
            是否匹配
        """
        # 完全匹配
        if target == source:
            return True

        # 包含关系匹配
        if target in source or source in target:
            return True

        # 分词匹配（检查主要关键词）
        target_words = set(target.split())
        source_words = set(source.split())

        # 如果有超过70%的词匹配，认为是同一个种子
        if target_words and source_words:
            intersection = target_words & source_words
            similarity = len(intersection) / max(len(target_words),
                                                 len(source_words))
            if similarity >= 0.7:
                return True

        return False

    def _normalize_title(self, title: str) -> str:
        """
        标准化标题用于匹配
        
        Args:
            title: 原始标题
            
        Returns:
            标准化后的标题
        """
        # 移除HTML标签
        title = re.sub(r'<[^>]+>', '', title)

        # 移除特殊字符，保留字母、数字、中文和空格
        title = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', title)

        # 转换为小写并去除多余空格
        title = title.lower().strip()

        # 压缩多个空格
        title = re.sub(r'\s+', ' ', title)

        return title
