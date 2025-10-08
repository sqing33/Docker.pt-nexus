# models/seed_parameter.py
"""
种子参数模型，用于处理从源站点提取并存储在数据库或JSON文件中的种子参数
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from flask import g


class SeedParameter:
    """种子参数模型类"""

    def __init__(self, db_manager):
        self.db_manager = db_manager

    def save_parameters(self, hash: str, torrent_id: str, site_name: str,
                        parameters: Dict[str, Any]) -> bool:
        """
        保存种子参数到数据库

        Args:
            hash: 种子hash值
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

            # 保存到数据库
            if self.db_manager:
                db_success = self._save_to_database(hash, torrent_id,
                                                    site_name, parameters)
                if db_success:
                    logging.info(f"种子参数已保存到数据库: {torrent_id} from {site_name}")
                    return True
                else:
                    logging.error(f"保存种子参数到数据库失败: {torrent_id} from {site_name}")
                    return False
            else:
                logging.error("数据库管理器未初始化")
                return False

        except Exception as e:
            logging.error(f"保存种子参数失败: {e}", exc_info=True)
            return False

    def _save_to_database(self, hash: str, torrent_id: str, site_name: str,
                          parameters: Dict[str, Any]) -> bool:
        """
        保存种子参数到数据库（使用UPSERT避免重复键冲突）

        Args:
            hash: 种子hash值
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

            # 处理title_components字段（列表转换为字符串）
            title_components = parameters.get("title_components", [])
            if isinstance(title_components, list):
                title_components = json.dumps(title_components,
                                              ensure_ascii=False)
            else:
                title_components = str(
                    title_components) if title_components else ""

            # 根据数据库类型构建UPSERT SQL
            if self.db_manager.db_type == "postgresql":
                # PostgreSQL使用ON CONFLICT DO UPDATE
                insert_sql = f"""
                    INSERT INTO seed_parameters
                    (hash, torrent_id, site_name, nickname, save_path, name, title, subtitle, imdb_link, douban_link, type, medium,
                     video_codec, audio_codec, resolution, team, source, tags, poster, screenshots,
                     statement, body, mediainfo, title_components, removed_ardtudeclarations, downloader_id, created_at, updated_at)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                    ON CONFLICT (hash, torrent_id, site_name)
                    DO UPDATE SET
                        nickname = EXCLUDED.nickname,
                        save_path = EXCLUDED.save_path,
                        name = EXCLUDED.name,
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
                        title_components = EXCLUDED.title_components,
                        removed_ardtudeclarations = EXCLUDED.removed_ardtudeclarations,
                        downloader_id = EXCLUDED.downloader_id,
                        updated_at = EXCLUDED.updated_at
                """
            elif self.db_manager.db_type == "mysql":
                # MySQL使用ON DUPLICATE KEY UPDATE
                insert_sql = f"""
                    INSERT INTO seed_parameters
                    (hash, torrent_id, site_name, nickname, save_path, name, title, subtitle, imdb_link, douban_link, type, medium,
                     video_codec, audio_codec, resolution, team, source, tags, poster, screenshots,
                     statement, body, mediainfo, title_components, removed_ardtudeclarations, downloader_id, created_at, updated_at)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                    ON DUPLICATE KEY UPDATE
                        torrent_id = VALUES(torrent_id),
                        nickname = VALUES(nickname),
                        save_path = VALUES(save_path),
                        name = VALUES(name),
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
                        title_components = VALUES(title_components),
                        removed_ardtudeclarations = VALUES(removed_ardtudeclarations),
                        downloader_id = VALUES(downloader_id),
                        updated_at = VALUES(updated_at)
                """
            else:  # SQLite
                # SQLite使用ON CONFLICT DO UPDATE
                insert_sql = f"""
                    INSERT INTO seed_parameters
                    (hash, torrent_id, site_name, nickname, save_path, name, title, subtitle, imdb_link, douban_link, type, medium,
                     video_codec, audio_codec, resolution, team, source, tags, poster, screenshots,
                     statement, body, mediainfo, title_components, removed_ardtudeclarations, downloader_id, created_at, updated_at)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                    ON CONFLICT (hash, torrent_id, site_name)
                    DO UPDATE SET
                        torrent_id = excluded.torrent_id,
                        nickname = excluded.nickname,
                        save_path = excluded.save_path,
                        name = excluded.name,
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
                        title_components = excluded.title_components,
                        removed_ardtudeclarations = excluded.removed_ardtudeclarations,
                        downloader_id = excluded.downloader_id,
                        updated_at = excluded.updated_at
                """

            # 准备参数
            # 处理mediainfo字段（可能为字典，需要转换为字符串）
            mediainfo = parameters.get("mediainfo", "")
            if isinstance(mediainfo, dict):
                mediainfo = json.dumps(mediainfo, ensure_ascii=False)
            elif not isinstance(mediainfo, str):
                mediainfo = str(mediainfo) if mediainfo else ""

            # 处理removed_ardtudeclarations字段（列表转换为字符串）
            removed_ardtudeclarations = parameters.get("removed_ardtudeclarations", [])
            if isinstance(removed_ardtudeclarations, list):
                removed_ardtudeclarations = json.dumps(removed_ardtudeclarations, ensure_ascii=False)
            else:
                removed_ardtudeclarations = str(removed_ardtudeclarations) if removed_ardtudeclarations else ""

            params = (hash, torrent_id, site_name,
                      parameters.get("nickname",
                                     ""), parameters.get("save_path", ""),
                      parameters.get("name", ""),
                      parameters.get("title",
                                     ""), parameters.get("subtitle", ""),
                      parameters.get("imdb_link",
                                     ""), parameters.get("douban_link", ""),
                      parameters.get("type", ""), parameters.get("medium", ""),
                      parameters.get("video_codec",
                                     ""), parameters.get("audio_codec", ""),
                      parameters.get("resolution",
                                     ""), parameters.get("team", ""),
                      parameters.get("source",
                                     ""), tags, parameters.get("poster", ""),
                      parameters.get("screenshots",
                                     ""), parameters.get("statement", ""),
                      parameters.get("body", ""), mediainfo, title_components,
                      removed_ardtudeclarations, parameters.get("downloader_id"), parameters["created_at"], parameters["updated_at"])

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

    def get_parameters(self, torrent_id: str,
                       site_name: str) -> Optional[Dict[str, Any]]:
        """
        从数据库获取种子参数

        Args:
            torrent_id: 种子ID
            site_name: 站点名称

        Returns:
            Dict[str, Any]: 参数字典，如果未找到则返回None
        """
        try:
            # 从数据库读取
            if self.db_manager:
                db_params = self._get_from_database(torrent_id, site_name)
                if db_params:
                    logging.info(f"种子参数已从数据库加载: {torrent_id} from {site_name}")
                    return db_params
                else:
                    logging.info(f"从数据库未找到种子参数: {torrent_id} from {site_name}")
                    return None
            else:
                logging.error("数据库管理器未初始化")
                return None

        except Exception as e:
            logging.error(f"获取种子参数失败: {e}", exc_info=True)
            return None

    def _get_from_database(self, torrent_id: str,
                           site_name: str) -> Optional[Dict[str, Any]]:
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
                if "tags" in parameters and isinstance(parameters["tags"],
                                                       str):
                    try:
                        parameters["tags"] = json.loads(parameters["tags"])
                    except json.JSONDecodeError:
                        parameters["tags"] = []

                # 解析title_components字段（如果存在）
                if "title_components" in parameters and isinstance(
                        parameters["title_components"], str):
                    try:
                        parameters["title_components"] = json.loads(
                            parameters["title_components"])
                    except json.JSONDecodeError:
                        parameters["title_components"] = []

                # 解析removed_ardtudeclarations字段（如果存在）
                if "removed_ardtudeclarations" in parameters and isinstance(
                        parameters["removed_ardtudeclarations"], str):
                    try:
                        parameters["removed_ardtudeclarations"] = json.loads(
                            parameters["removed_ardtudeclarations"])
                    except json.JSONDecodeError:
                        parameters["removed_ardtudeclarations"] = []

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

    def update_parameters(self, torrent_id: str, site_name: str,
                          parameters: Dict[str, Any]) -> bool:
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
        updated_params["updated_at"] = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S")

        # 从现有参数中获取hash值，如果不存在则使用空字符串
        hash_value = existing_params.get("hash", "")

        return self.save_parameters(hash_value, torrent_id, site_name, updated_params)

    def delete_parameters(self, torrent_id: str, site_name: str) -> bool:
        """
        删除种子参数（数据库记录）

        Args:
            torrent_id: 种子ID
            site_name: 站点名称

        Returns:
            bool: 删除是否成功
        """
        try:
            # 删除数据库记录
            if self.db_manager:
                conn = self.db_manager._get_connection()
                cursor = self.db_manager._get_cursor(conn)
                ph = self.db_manager.get_placeholder()

                # 构建删除查询
                if self.db_manager.db_type == "postgresql":
                    cursor.execute(
                        "DELETE FROM seed_parameters WHERE torrent_id = %s AND site_name = %s",
                        (torrent_id, site_name))
                else:
                    cursor.execute(
                        "DELETE FROM seed_parameters WHERE torrent_id = ? AND site_name = ?",
                        (torrent_id, site_name))

                deleted_count = cursor.rowcount
                conn.commit()
                cursor.close()
                conn.close()

                logging.info(f"种子参数数据库记录已删除: {torrent_id} from {site_name}, count: {deleted_count}")

                if deleted_count <= 0:
                    logging.warning(f"在数据库中未找到要删除的种子参数: {torrent_id} from {site_name}")
                
                return True
            else:
                logging.error("数据库管理器未初始化")
                return False

        except Exception as e:
            logging.error(f"删除种子参数失败: {e}", exc_info=True)
            return False

    def search_torrent_hash(self, name: str, sites: str = None) -> str:
        """
        根据种子名称和站点信息搜索对应的hash值。

        Args:
            name (str): 种子名称
            sites (str, optional): 站点信息

        Returns:
            str: hash字符串，如果未找到则返回空字符串
        """
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)
            ph = self.db_manager.get_placeholder()

            # 根据数据库类型构建查询语句
            if self.db_manager.db_type == "postgresql":
                if sites:
                    cursor.execute(
                        "SELECT hash FROM torrents WHERE name = %s AND sites = %s",
                        (name, sites))
                else:
                    cursor.execute("SELECT hash FROM torrents WHERE name = %s",
                                   (name, ))
            else:
                if sites:
                    cursor.execute(
                        "SELECT hash FROM torrents WHERE name = ? AND sites = ?",
                        (name, sites))
                else:
                    cursor.execute("SELECT hash FROM torrents WHERE name = ?",
                                   (name, ))

            results = cursor.fetchall()
            if results:
                return results[0]["hash"]
            else:
                return ""

        except Exception as e:
            logging.error(f"search_torrent_hash 出错: {e}", exc_info=True)
            return ""
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
