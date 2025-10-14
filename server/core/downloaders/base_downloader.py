"""
基础下载器类
定义下载器的通用接口和方法
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import re
from loguru import logger


class BaseDownloader(ABC):
    """
    基础下载器抽象类
    定义下载器的通用接口
    """

    def __init__(self, site_name: str, session: Any):
        """
        初始化下载器
        
        Args:
            site_name: 站点名称
            session: 会话对象
        """
        self.site_name = site_name
        self.session = session

    @abstractmethod
    def extract_download_link(self, detail_page_html: str, upload_title: str) -> Optional[str]:
        """
        从详情页HTML中提取下载链接
        
        Args:
            detail_page_html: 详情页HTML内容
            upload_title: 上传的种子标题
            
        Returns:
            下载链接URL，如果未找到则返回None
        """
        pass

    def _find_torrent_by_title(self, html: str, target_title: str) -> Optional[str]:
        """
        通过标题匹配找到对应的种子下载链接
        
        Args:
            html: 详情页HTML内容
            target_title: 目标种子标题
            
        Returns:
            下载链接URL，如果未找到则返回None
        """
        # 默认实现，子类可以重写
        return None

    def _find_newest_torrent(self, html: str) -> Optional[str]:
        """
        找到最新的种子下载链接
        
        Args:
            html: 详情页HTML内容
            
        Returns:
            下载链接URL，如果未找到则返回None
        """
        # 默认实现，子类可以重写
        return None

    def _normalize_title(self, title: str) -> str:
        """
        标准化标题用于匹配
        
        Args:
            title: 原始标题
            
        Returns:
            标准化后的标题
        """
        # 移除特殊字符，转换为小写
        normalized = re.sub(r'[^\w\s]', '', title.lower())
        return normalized.strip()

    def _extract_torrent_id_from_link(self, link: str) -> Optional[str]:
        """
        从下载链接中提取种子ID
        
        Args:
            link: 下载链接
            
        Returns:
            种子ID，如果未找到则返回None
        """
        # 匹配 download.php?id=数字 格式
        match = re.search(r'download\.php\?id=(\d+)', link)
        if match:
            return match.group(1)
        return None
