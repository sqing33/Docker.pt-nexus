# uploaders/factory.py

import os
import importlib
from typing import Dict, Any
from .base import BaseUploader


def create_uploader(site_name: str, site_info: Dict[str, Any], upload_data: Dict[str, Any]) -> BaseUploader:
    """
    工厂函数，根据站点名称动态创建对应的上传器实例。
    
    :param site_name: 站点名称（如 'agsv', 'crabpt' 等）
    :param site_info: 站点信息字典
    :param upload_data: 上传数据字典
    :return: 对应站点的上传器实例
    """
    try:
        # 将站点名称转换为模块名（处理特殊字符）
        module_name = site_name.replace('-', '_').replace('.', '_')
        
        # 动态导入站点模块
        site_module = importlib.import_module(f"uploaders.sites.{module_name}")
        
        # 获取上传器类名（通常是站点名+Uploader）
        class_name = f"{module_name.capitalize()}Uploader"
        # 特殊处理一些站点名称
        if site_name == "13city":
            class_name = "City13Uploader"
        elif site_name == "agsv":
            class_name = "AgsvUploader"
        elif site_name == "crabpt":
            class_name = "CrabptUploader"
            
        # 获取上传器类
        uploader_class = getattr(site_module, class_name)
        
        # 创建并返回实例
        return uploader_class(site_name, site_info, upload_data)
        
    except ImportError as e:
        raise ImportError(f"无法导入站点 {site_name} 的模块: {e}")
    except AttributeError as e:
        raise AttributeError(f"站点 {site_name} 的模块中未找到上传器类: {e}")
    except Exception as e:
        raise Exception(f"创建站点 {site_name} 的上传器时发生错误: {e}")


def get_available_sites() -> list:
    """
    获取所有可用的站点列表。
    
    :return: 可用站点名称列表
    """
    sites_dir = os.path.join(os.path.dirname(__file__), "sites")
    sites = []
    
    if os.path.exists(sites_dir):
        for filename in os.listdir(sites_dir):
            if filename.endswith(".py") and filename != "__init__.py":
                site_name = filename[:-3]  # 移除.py扩展名
                # 将模块名转换回站点名
                site_name = site_name.replace('_', '-')
                sites.append(site_name)
    
    return sites