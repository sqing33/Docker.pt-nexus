# models/seed_parameter.py
"""
种子参数模型，用于处理从源站点提取并存储在数据库或JSON文件中的种子参数
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, Any, Optional, List
from flask import g
from config import TEMP_DIR


class SeedParameter:
    """种子参数模型类"""

    def __init__(self, db_manager):
        self.db_manager = db_manager

    def _get_json_file_path(self, torrent_id: str, site_name: str) -> str:
        """
        获取参数JSON文件路径

        Args:
            torrent_id: 种子ID
            site_name: 站点名称

        Returns:
            str: JSON文件路径
        """
        # 创建站点目录
        site_dir = os.path.join(TEMP_DIR, "seed_params", site_name)
        os.makedirs(site_dir, exist_ok=True)

        # 返回文件路径
        return os.path.join(site_dir, f"{torrent_id}.json")

    def save_parameters(self, torrent_id: str, site_name: str, parameters: Dict[str, Any]) -> bool:
        """
        保存种子参数到JSON文件

        Args:
            torrent_id: 种子ID
            site_name: 站点名称
            parameters: 参数字典

        Returns:
            bool: 保存是否成功
        """
        try:
            # 获取文件路径
            json_file_path = self._get_json_file_path(torrent_id, site_name)

            # 添加时间戳
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            parameters["created_at"] = current_time
            parameters["updated_at"] = current_time
            parameters["torrent_id"] = torrent_id
            parameters["site_name"] = site_name

            # 保存到JSON文件
            with open(json_file_path, 'w', encoding='utf-8') as f:
                json.dump(parameters, f, ensure_ascii=False, indent=2)

            logging.info(f"种子参数已保存到JSON文件: {json_file_path}")
            return True

        except Exception as e:
            logging.error(f"保存种子参数到JSON文件失败: {e}", exc_info=True)
            return False

    def get_parameters(self, torrent_id: str, site_name: str) -> Optional[Dict[str, Any]]:
        """
        从JSON文件获取种子参数

        Args:
            torrent_id: 种子ID
            site_name: 站点名称

        Returns:
            Dict[str, Any]: 参数字典，如果未找到则返回None
        """
        try:
            # 获取文件路径
            json_file_path = self._get_json_file_path(torrent_id, site_name)

            # 检查文件是否存在
            if not os.path.exists(json_file_path):
                logging.info(f"种子参数文件不存在: {json_file_path}")
                return None

            # 从JSON文件读取
            with open(json_file_path, 'r', encoding='utf-8') as f:
                parameters = json.load(f)

            # 解析tags字段（如果存在）
            if "tags" in parameters and isinstance(parameters["tags"], str):
                try:
                    parameters["tags"] = json.loads(parameters["tags"])
                except json.JSONDecodeError:
                    parameters["tags"] = []

            logging.info(f"种子参数已从JSON文件加载: {json_file_path}")
            return parameters

        except Exception as e:
            logging.error(f"从JSON文件获取种子参数失败: {e}", exc_info=True)
            return None

    def update_parameters(self, torrent_id: str, site_name: str, parameters: Dict[str, Any]) -> bool:
        """
        更新种子参数

        Args:
            torrent_id: 种子ID
            site_name: 站点名称
            parameters: 要更新的参数字典

        Returns:
            bool: 更新是否成功
        """
        # 先获取现有参数
        existing_params = self.get_parameters(torrent_id, site_name) or {}

        # 合并参数（新参数覆盖旧参数）
        updated_params = {**existing_params, **parameters}

        # 更新时间戳
        updated_params["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return self.save_parameters(torrent_id, site_name, updated_params)

    def delete_parameters(self, torrent_id: str, site_name: str) -> bool:
        """
        删除种子参数

        Args:
            torrent_id: 种子ID
            site_name: 站点名称

        Returns:
            bool: 删除是否成功
        """
        try:
            # 获取文件路径
            json_file_path = self._get_json_file_path(torrent_id, site_name)

            # 检查文件是否存在
            if not os.path.exists(json_file_path):
                logging.info(f"种子参数文件不存在: {json_file_path}")
                return False

            # 删除文件
            os.remove(json_file_path)
            logging.info(f"种子参数文件已删除: {json_file_path}")

            # 尝试删除空的站点目录
            site_dir = os.path.dirname(json_file_path)
            try:
                os.rmdir(site_dir)
                logging.info(f"空的站点目录已删除: {site_dir}")
            except OSError:
                # 目录不为空，忽略错误
                pass

            return True

        except Exception as e:
            logging.error(f"删除种子参数文件失败: {e}", exc_info=True)
            return False