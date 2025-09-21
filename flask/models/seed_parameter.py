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
        保存种子参数到数据库（优先）和JSON文件（后备）

        Args:
            torrent_id: 种子ID
            site_name: 站点名称
            parameters: 参数字典

        Returns:
            bool: 保存是否成功
        """
        try:
            # 添加时间戳
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            parameters["created_at"] = current_time
            parameters["updated_at"] = current_time
            parameters["torrent_id"] = torrent_id
            parameters["site_name"] = site_name

            # 优先保存到数据库
            if self.db_manager:
                db_success = self._save_to_database(torrent_id, site_name, parameters)
                if db_success:
                    logging.info(f"种子参数已保存到数据库: {torrent_id} from {site_name}")
                    return True
                else:
                    logging.warning(f"保存种子参数到数据库失败，回退到JSON文件: {torrent_id} from {site_name}")

            # 回退到JSON文件存储
            return self._save_to_json_file(torrent_id, site_name, parameters)

        except Exception as e:
            logging.error(f"保存种子参数失败: {e}", exc_info=True)
            return False

    def _save_to_database(self, torrent_id: str, site_name: str, parameters: Dict[str, Any]) -> bool:
        """
        保存种子参数到数据库（使用UPSERT避免重复键冲突）

        Args:
            torrent_id: 种子ID
            site_name: 站点名称
            parameters: 参数字典

        Returns:
            bool: 保存是否成功
        """
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)
            ph = self.db_manager.get_placeholder()

            # 处理tags字段（列表转换为字符串）
            tags = parameters.get("tags", [])
            if isinstance(tags, list):
                tags = json.dumps(tags, ensure_ascii=False)
            else:
                tags = str(tags) if tags else ""

            # 根据数据库类型构建UPSERT SQL
            if self.db_manager.db_type == "postgresql":
                # PostgreSQL使用ON CONFLICT DO UPDATE
                insert_sql = f"""
                    INSERT INTO seed_parameters
                    (torrent_id, site_name, title, subtitle, imdb_link, douban_link, type, medium,
                     video_codec, audio_codec, resolution, team, source, tags, poster, screenshots,
                     statement, body, mediainfo, created_at, updated_at)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                    ON CONFLICT (torrent_id, site_name)
                    DO UPDATE SET
                        title = EXCLUDED.title,
                        subtitle = EXCLUDED.subtitle,
                        imdb_link = EXCLUDED.imdb_link,
                        douban_link = EXCLUDED.douban_link,
                        type = EXCLUDED.type,
                        medium = EXCLUDED.medium,
                        video_codec = EXCLUDED.video_codec,
                        audio_codec = EXCLUDED.audio_codec,
                        resolution = EXCLUDED.resolution,
                        team = EXCLUDED.team,
                        source = EXCLUDED.source,
                        tags = EXCLUDED.tags,
                        poster = EXCLUDED.poster,
                        screenshots = EXCLUDED.screenshots,
                        statement = EXCLUDED.statement,
                        body = EXCLUDED.body,
                        mediainfo = EXCLUDED.mediainfo,
                        updated_at = EXCLUDED.updated_at
                """
            elif self.db_manager.db_type == "mysql":
                # MySQL使用ON DUPLICATE KEY UPDATE
                insert_sql = f"""
                    INSERT INTO seed_parameters
                    (torrent_id, site_name, title, subtitle, imdb_link, douban_link, type, medium,
                     video_codec, audio_codec, resolution, team, source, tags, poster, screenshots,
                     statement, body, mediainfo, created_at, updated_at)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                    ON DUPLICATE KEY UPDATE
                        title = VALUES(title),
                        subtitle = VALUES(subtitle),
                        imdb_link = VALUES(imdb_link),
                        douban_link = VALUES(douban_link),
                        type = VALUES(type),
                        medium = VALUES(medium),
                        video_codec = VALUES(video_codec),
                        audio_codec = VALUES(audio_codec),
                        resolution = VALUES(resolution),
                        team = VALUES(team),
                        source = VALUES(source),
                        tags = VALUES(tags),
                        poster = VALUES(poster),
                        screenshots = VALUES(screenshots),
                        statement = VALUES(statement),
                        body = VALUES(body),
                        mediainfo = VALUES(mediainfo),
                        updated_at = VALUES(updated_at)
                """
            else:  # SQLite
                # SQLite使用ON CONFLICT DO UPDATE
                insert_sql = f"""
                    INSERT INTO seed_parameters
                    (torrent_id, site_name, title, subtitle, imdb_link, douban_link, type, medium,
                     video_codec, audio_codec, resolution, team, source, tags, poster, screenshots,
                     statement, body, mediainfo, created_at, updated_at)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                    ON CONFLICT (torrent_id, site_name)
                    DO UPDATE SET
                        title = excluded.title,
                        subtitle = excluded.subtitle,
                        imdb_link = excluded.imdb_link,
                        douban_link = excluded.douban_link,
                        type = excluded.type,
                        medium = excluded.medium,
                        video_codec = excluded.video_codec,
                        audio_codec = excluded.audio_codec,
                        resolution = excluded.resolution,
                        team = excluded.team,
                        source = excluded.source,
                        tags = excluded.tags,
                        poster = excluded.poster,
                        screenshots = excluded.screenshots,
                        statement = excluded.statement,
                        body = excluded.body,
                        mediainfo = excluded.mediainfo,
                        updated_at = excluded.updated_at
                """

            # 准备参数
            params = (
                torrent_id,
                site_name,
                parameters.get("title", ""),
                parameters.get("subtitle", ""),
                parameters.get("imdb_link", ""),
                parameters.get("douban_link", ""),
                parameters.get("type", ""),
                parameters.get("medium", ""),
                parameters.get("video_codec", ""),
                parameters.get("audio_codec", ""),
                parameters.get("resolution", ""),
                parameters.get("team", ""),
                parameters.get("source", ""),
                tags,
                parameters.get("poster", ""),
                parameters.get("screenshots", ""),
                parameters.get("statement", ""),
                parameters.get("body", ""),
                parameters.get("mediainfo", ""),
                parameters["created_at"],
                parameters["updated_at"]
            )

            cursor.execute(insert_sql, params)
            conn.commit()

            return True

        except Exception as e:
            logging.error(f"保存种子参数到数据库失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return False
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def _save_to_json_file(self, torrent_id: str, site_name: str, parameters: Dict[str, Any]) -> bool:
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
        从数据库（优先）或JSON文件获取种子参数

        Args:
            torrent_id: 种子ID
            site_name: 站点名称

        Returns:
            Dict[str, Any]: 参数字典，如果未找到则返回None
        """
        try:
            # 优先从数据库读取
            if self.db_manager:
                db_params = self._get_from_database(torrent_id, site_name)
                if db_params:
                    logging.info(f"种子参数已从数据库加载: {torrent_id} from {site_name}")
                    return db_params
                else:
                    logging.warning(f"从数据库未找到种子参数，尝试从JSON文件读取: {torrent_id} from {site_name}")

            # 回退到JSON文件读取
            return self._get_from_json_file(torrent_id, site_name)

        except Exception as e:
            logging.error(f"获取种子参数失败: {e}", exc_info=True)
            return None

    def _get_from_database(self, torrent_id: str, site_name: str) -> Optional[Dict[str, Any]]:
        """
        从数据库获取种子参数

        Args:
            torrent_id: 种子ID
            site_name: 站点名称

        Returns:
            Dict[str, Any]: 参数字典，如果未找到则返回None
        """
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)
            ph = self.db_manager.get_placeholder()

            select_sql = f"""
                SELECT * FROM seed_parameters
                WHERE torrent_id = {ph} AND site_name = {ph}
                ORDER BY updated_at DESC LIMIT 1
            """

            cursor.execute(select_sql, (torrent_id, site_name))
            row = cursor.fetchone()

            if row:
                parameters = dict(row)

                # 解析tags字段（如果存在）
                if "tags" in parameters and isinstance(parameters["tags"], str):
                    try:
                        parameters["tags"] = json.loads(parameters["tags"])
                    except json.JSONDecodeError:
                        parameters["tags"] = []

                return parameters

            return None

        except Exception as e:
            logging.error(f"从数据库获取种子参数失败: {e}", exc_info=True)
            return None
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def _get_from_json_file(self, torrent_id: str, site_name: str) -> Optional[Dict[str, Any]]:
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