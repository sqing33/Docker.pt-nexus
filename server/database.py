# database.py

import logging
import sqlite3
import mysql.connector
import psycopg2
import json
import os
from datetime import datetime
from psycopg2.extras import RealDictCursor

# 从项目根目录导入模块
from config import SITES_DATA_FILE, config_manager

# 外部库导入
from qbittorrentapi import Client
from transmission_rpc import Client as TrClient

# --- [重要修正] ---
# 直接从 core.services 导入正确的函数，移除了会导致错误的 try-except 占位符
from core.services import _prepare_api_config


class DatabaseManager:
    """处理与配置的数据库（MySQL、PostgreSQL 或 SQLite）的所有交互。"""

    def __init__(self, config):
        """根据提供的配置初始化 DatabaseManager。"""
        self.db_type = config.get("db_type", "sqlite")
        if self.db_type == "mysql":
            self.mysql_config = config.get("mysql", {})
            logging.info("数据库后端设置为 MySQL。")
        elif self.db_type == "postgresql":
            self.postgresql_config = config.get("postgresql", {})
            logging.info("数据库后端设置为 PostgreSQL。")
        else:
            self.sqlite_path = config.get("path", "data/pt_stats.db")
            logging.info(f"数据库后端设置为 SQLite。路径: {self.sqlite_path}")

    def _get_connection(self):
        """返回一个新的数据库连接。"""
        if self.db_type == "mysql":
            return mysql.connector.connect(**self.mysql_config,
                                           autocommit=False)
        elif self.db_type == "postgresql":
            return psycopg2.connect(**self.postgresql_config)
        else:
            return sqlite3.connect(self.sqlite_path, timeout=20)

    def _get_cursor(self, conn):
        """从连接中返回一个游标。"""
        if self.db_type == "mysql":
            return conn.cursor(dictionary=True, buffered=True)
        elif self.db_type == "postgresql":
            return conn.cursor(cursor_factory=RealDictCursor)
        else:
            conn.row_factory = sqlite3.Row
            return conn.cursor()

    def get_placeholder(self):
        """返回数据库类型对应的正确参数占位符。"""
        return "%s" if self.db_type in ["mysql", "postgresql"] else "?"

    def get_site_by_nickname(self, nickname):
        """通过站点昵称从数据库中获取站点的完整信息。"""
        conn = self._get_connection()
        cursor = self._get_cursor(conn)
        try:
            # 首先尝试通过nickname查询
            cursor.execute(
                f"SELECT * FROM sites WHERE nickname = {self.get_placeholder()}",
                (nickname, ))
            site_data = cursor.fetchone()

            # 如果通过nickname没有找到，尝试通过site字段查询
            if not site_data:
                cursor.execute(
                    f"SELECT * FROM sites WHERE site = {self.get_placeholder()}",
                    (nickname, ))
                site_data = cursor.fetchone()

            return dict(site_data) if site_data else None
        except Exception as e:
            logging.error(f"通过昵称 '{nickname}' 获取站点信息时出错: {e}")
            return None
        finally:
            cursor.close()
            conn.close()

    def add_site(self, site_data):
        """向数据库中添加一个新站点。"""
        conn = self._get_connection()
        cursor = self._get_cursor(conn)
        ph = self.get_placeholder()
        try:
            # 根据数据库类型使用正确的标识符引用符
            if self.db_type == "postgresql":
                sql = f"INSERT INTO sites (site, nickname, base_url, special_tracker_domain, \"group\", description, cookie, speed_limit) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})"
            else:
                sql = f"INSERT INTO sites (site, nickname, base_url, special_tracker_domain, `group`, description, cookie, speed_limit) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})"
            # 去除cookie字符串首尾的换行符和多余空白字符
            cookie = site_data.get("cookie")
            if cookie:
                cookie = cookie.strip()

            params = (
                site_data.get("site"),
                site_data.get("nickname"),
                site_data.get("base_url"),
                site_data.get("special_tracker_domain"),
                site_data.get("group"),
                site_data.get("description"),
                cookie,
                int(site_data.get("speed_limit", 0)),
            )
            cursor.execute(sql, params)
            conn.commit()
            return True
        except Exception as e:
            if "UNIQUE constraint failed" in str(
                    e) or "Duplicate entry" in str(e):
                logging.error(f"添加站点失败：站点域名 '{site_data.get('site')}' 已存在。")
            else:
                logging.error(f"添加站点 '{site_data.get('nickname')}' 失败: {e}",
                              exc_info=True)
            conn.rollback()
            return False
        finally:
            cursor.close()
            conn.close()

    def update_site_details(self, site_data):
        """根据站点 ID 更新其所有可编辑的详细信息。"""
        conn = self._get_connection()
        cursor = self._get_cursor(conn)
        ph = self.get_placeholder()
        try:
            # 根据数据库类型使用正确的标识符引用符
            if self.db_type == "postgresql":
                sql = f"UPDATE sites SET nickname = {ph}, base_url = {ph}, special_tracker_domain = {ph}, \"group\" = {ph}, description = {ph}, cookie = {ph}, speed_limit = {ph} WHERE id = {ph}"
            else:
                sql = f"UPDATE sites SET nickname = {ph}, base_url = {ph}, special_tracker_domain = {ph}, `group` = {ph}, description = {ph}, cookie = {ph}, speed_limit = {ph} WHERE id = {ph}"
            # 去除cookie字符串首尾的换行符和多余空白字符
            cookie = site_data.get("cookie")
            if cookie:
                cookie = cookie.strip()

            params = (
                site_data.get("nickname"),
                site_data.get("base_url"),
                site_data.get("special_tracker_domain"),
                site_data.get("group"),
                site_data.get("description"),
                cookie,
                int(site_data.get("speed_limit", 0)),
                site_data.get("id"),
            )
            cursor.execute(sql, params)
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logging.error(f"更新站点ID '{site_data.get('id')}' 失败: {e}",
                          exc_info=True)
            conn.rollback()
            return False
        finally:
            cursor.close()
            conn.close()

    def delete_site(self, site_id):
        """根据站点 ID 从数据库中删除一个站点。"""
        conn = self._get_connection()
        cursor = self._get_cursor(conn)
        try:
            cursor.execute(
                f"DELETE FROM sites WHERE id = {self.get_placeholder()}",
                (site_id, ))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logging.error(f"删除站点ID '{site_id}' 失败: {e}", exc_info=True)
            conn.rollback()
            return False
        finally:
            cursor.close()
            conn.close()

    def update_site_cookie(self, nickname, cookie):
        """按昵称更新指定站点的 Cookie (主要由CookieCloud使用)。"""
        conn = self._get_connection()
        cursor = self._get_cursor(conn)
        try:
            # 去除cookie字符串首尾的换行符和多余空白字符
            if cookie:
                cookie = cookie.strip()
            cursor.execute(
                f"UPDATE sites SET cookie = {self.get_placeholder()} WHERE nickname = {self.get_placeholder()}",
                (cookie, nickname),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logging.error(f"更新站点 '{nickname}' 的 Cookie 失败: {e}", exc_info=True)
            conn.rollback()
            return False
        finally:
            cursor.close()
            conn.close()

    def sync_sites_from_json(self):
        """从 sites_data.json 同步站点数据到数据库"""
        try:
            # 读取 JSON 文件
            with open(SITES_DATA_FILE, 'r', encoding='utf-8') as f:
                sites_data = json.load(f)

            logging.info(f"从 {SITES_DATA_FILE} 加载了 {len(sites_data)} 个站点")

            # 获取数据库连接
            conn = self._get_connection()
            cursor = self._get_cursor(conn)

            try:
                # [修改] 查询时额外获取 speed_limit 字段，用于后续逻辑判断
                cursor.execute(
                    "SELECT id, site, nickname, base_url, speed_limit FROM sites"
                )
                existing_sites = {}
                for row in cursor.fetchall():
                    # 以site、nickname、base_url为键存储现有站点
                    # 将整行数据存起来，方便后续获取 speed_limit
                    row_dict = dict(row)
                    existing_sites[row['site']] = row_dict
                    if row['nickname']:
                        existing_sites[row['nickname']] = row_dict
                    if row['base_url']:
                        existing_sites[row['base_url']] = row_dict

                updated_count = 0
                added_count = 0

                # 遍历 JSON 中的站点数据
                for site_info in sites_data:
                    site_name = site_info.get('site')
                    nickname = site_info.get('nickname')
                    base_url = site_info.get('base_url')

                    if not site_name or not nickname or not base_url:
                        logging.warning(f"跳过无效的站点数据: {site_info}")
                        continue

                    # 检查站点是否已存在（基于site、nickname或base_url中的任何一个）
                    existing_site = None
                    if site_name in existing_sites:
                        existing_site = existing_sites[site_name]
                    elif nickname in existing_sites:
                        existing_site = existing_sites[nickname]
                    elif base_url in existing_sites:
                        existing_site = existing_sites[base_url]

                    if existing_site:
                        # --- [核心修改逻辑] ---
                        # 获取数据库中当前的 speed_limit
                        db_speed_limit = existing_site.get('speed_limit', 0)
                        # 获取 JSON 文件中的 speed_limit
                        json_speed_limit = site_info.get('speed_limit', 0)

                        # 默认使用数据库中现有的值
                        final_speed_limit = db_speed_limit

                        # 如果数据库值为0，且JSON值不为0，则采纳JSON的值
                        if db_speed_limit == 0 and json_speed_limit != 0:
                            final_speed_limit = json_speed_limit
                        # --- [核心修改逻辑结束] ---

                        # 构建更新语句，不包含 cookie
                        if self.db_type == "postgresql":
                            update_sql = """
                                UPDATE sites
                                SET site = %s, nickname = %s, base_url = %s, special_tracker_domain = %s,
                                    "group" = %s, description = %s, migration = %s, speed_limit = %s
                                WHERE id = %s
                            """
                        else:
                            update_sql = """
                                UPDATE sites
                                SET site = %s, nickname = %s, base_url = %s, special_tracker_domain = %s,
                                    `group` = %s, description = %s, migration = %s, speed_limit = %s
                                WHERE id = %s
                            """

                        # 执行更新，传入经过逻辑判断后的 final_speed_limit
                        cursor.execute(
                            update_sql,
                            (
                                site_info.get('site'),
                                site_info.get('nickname'),
                                site_info.get('base_url'),
                                site_info.get('special_tracker_domain'),
                                site_info.get('group'),
                                site_info.get('description'),
                                site_info.get('migration', 0),
                                final_speed_limit,  # 使用条件判断后的最终值
                                existing_site['id']))
                        updated_count += 1
                        logging.debug(f"更新了站点: {site_name}")
                    else:
                        # 根据数据库类型使用正确的标识符引用符
                        if self.db_type == "postgresql":
                            # 添加新站点
                            cursor.execute(
                                """
                                INSERT INTO sites
                                (site, nickname, base_url, special_tracker_domain, "group", description, migration, speed_limit)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """, (site_info.get('site'),
                                  site_info.get('nickname'),
                                  site_info.get('base_url'),
                                  site_info.get('special_tracker_domain'),
                                  site_info.get('group'),
                                  site_info.get('description'),
                                  site_info.get('migration', 0),
                                  site_info.get('speed_limit', 0)))
                        else:
                            # 添加新站点
                            cursor.execute(
                                """
                                INSERT INTO sites
                                (site, nickname, base_url, special_tracker_domain, `group`, description, migration, speed_limit)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """, (site_info.get('site'),
                                  site_info.get('nickname'),
                                  site_info.get('base_url'),
                                  site_info.get('special_tracker_domain'),
                                  site_info.get('group'),
                                  site_info.get('description'),
                                  site_info.get('migration', 0),
                                  site_info.get('speed_limit', 0)))
                        added_count += 1
                        logging.debug(f"添加了新站点: {site_name}")

                conn.commit()
                logging.info(f"站点同步完成: {updated_count} 个更新, {added_count} 个新增")
                return True

            except Exception as e:
                conn.rollback()
                logging.error(f"同步站点数据时出错: {e}", exc_info=True)
                return False
            finally:
                if cursor:
                    cursor.close()
                if conn:
                    conn.close()

        except Exception as e:
            logging.error(f"读取站点数据文件时出错: {e}", exc_info=True)
            return False

    def init_db(self):
        """确保数据库表存在，并根据 sites_data.json 同步站点数据。"""
        conn = self._get_connection()
        cursor = self._get_cursor(conn)

        logging.info("正在初始化并验证数据库表结构...")
        # 表创建逻辑 (MySQL)
        if self.db_type == "mysql":
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS traffic_stats (stat_datetime DATETIME NOT NULL, downloader_id VARCHAR(36) NOT NULL, uploaded BIGINT DEFAULT 0, downloaded BIGINT DEFAULT 0, upload_speed BIGINT DEFAULT 0, download_speed BIGINT DEFAULT 0, cumulative_uploaded BIGINT NOT NULL DEFAULT 0, cumulative_downloaded BIGINT NOT NULL DEFAULT 0, PRIMARY KEY (stat_datetime, downloader_id)) ENGINE=InnoDB ROW_FORMAT=Dynamic"
            )
            # 创建小时聚合表 (MySQL)
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS traffic_stats_hourly (stat_datetime DATETIME NOT NULL, downloader_id VARCHAR(36) NOT NULL, uploaded BIGINT DEFAULT 0, downloaded BIGINT DEFAULT 0, avg_upload_speed BIGINT DEFAULT 0, avg_download_speed BIGINT DEFAULT 0, samples INTEGER DEFAULT 0, cumulative_uploaded BIGINT NOT NULL DEFAULT 0, cumulative_downloaded BIGINT NOT NULL DEFAULT 0, PRIMARY KEY (stat_datetime, downloader_id)) ENGINE=InnoDB ROW_FORMAT=Dynamic"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS downloader_clients (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255) NOT NULL, type VARCHAR(50) NOT NULL, last_total_dl BIGINT NOT NULL DEFAULT 0, last_total_ul BIGINT NOT NULL DEFAULT 0) ENGINE=InnoDB ROW_FORMAT=Dynamic"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS torrents (hash VARCHAR(40) PRIMARY KEY, name TEXT NOT NULL, save_path TEXT, size BIGINT, progress FLOAT, state VARCHAR(50), sites VARCHAR(255), `group` VARCHAR(255), details TEXT, downloader_id VARCHAR(36) NULL, last_seen DATETIME NOT NULL, iyuu_last_check DATETIME NULL) ENGINE=InnoDB ROW_FORMAT=Dynamic"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS torrent_upload_stats (hash VARCHAR(40) NOT NULL, downloader_id VARCHAR(36) NOT NULL, uploaded BIGINT DEFAULT 0, PRIMARY KEY (hash, downloader_id)) ENGINE=InnoDB ROW_FORMAT=Dynamic"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS `sites` (`id` mediumint NOT NULL AUTO_INCREMENT, `site` varchar(255) UNIQUE DEFAULT NULL, `nickname` varchar(255) DEFAULT NULL, `base_url` varchar(255) DEFAULT NULL, `special_tracker_domain` varchar(255) DEFAULT NULL, `group` varchar(255) DEFAULT NULL, `description` varchar(255) DEFAULT NULL, `cookie` TEXT DEFAULT NULL, `migration` int(11) NOT NULL DEFAULT 1, `speed_limit` int(11) NOT NULL DEFAULT 0, PRIMARY KEY (`id`)) ENGINE=InnoDB ROW_FORMAT=DYNAMIC"
            )
            # 创建种子参数表，用于存储从源站点提取的种子参数
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS seed_parameters (hash VARCHAR(40) NOT NULL, torrent_id VARCHAR(255) NOT NULL, site_name VARCHAR(255) NOT NULL, nickname VARCHAR(255), save_path TEXT, name TEXT, title TEXT, subtitle TEXT, imdb_link TEXT, douban_link TEXT, type VARCHAR(100), medium VARCHAR(100), video_codec VARCHAR(100), audio_codec VARCHAR(100), resolution VARCHAR(100), team VARCHAR(100), source VARCHAR(100), tags TEXT, poster TEXT, screenshots TEXT, statement TEXT, body TEXT, mediainfo TEXT, title_components TEXT, removed_ardtudeclarations TEXT, downloader_id VARCHAR(36), is_deleted TINYINT(1) NOT NULL DEFAULT 0, is_reviewed TINYINT(1) NOT NULL DEFAULT 0, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, PRIMARY KEY (hash, torrent_id, site_name)) ENGINE=InnoDB ROW_FORMAT=DYNAMIC"
            )
            # 创建批量转种记录表
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS batch_enhance_records (id INT AUTO_INCREMENT PRIMARY KEY, title TEXT, batch_id VARCHAR(255) NOT NULL, torrent_id VARCHAR(255) NOT NULL, source_site VARCHAR(255) NOT NULL, target_site VARCHAR(255) NOT NULL, video_size_gb DECIMAL(8,2), status VARCHAR(50) NOT NULL, success_url TEXT, error_detail TEXT, downloader_add_result TEXT, processed_at DATETIME DEFAULT CURRENT_TIMESTAMP, progress VARCHAR(20), INDEX idx_batch_records_batch_id (batch_id), INDEX idx_batch_records_torrent_id (torrent_id), INDEX idx_batch_records_status (status), INDEX idx_batch_records_processed_at (processed_at)) ENGINE=InnoDB ROW_FORMAT=DYNAMIC"
            )
        # 表创建逻辑 (PostgreSQL)
        elif self.db_type == "postgresql":
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS traffic_stats (stat_datetime TIMESTAMP NOT NULL, downloader_id VARCHAR(36) NOT NULL, uploaded BIGINT DEFAULT 0, downloaded BIGINT DEFAULT 0, upload_speed BIGINT DEFAULT 0, download_speed BIGINT DEFAULT 0, cumulative_uploaded BIGINT NOT NULL DEFAULT 0, cumulative_downloaded BIGINT NOT NULL DEFAULT 0, PRIMARY KEY (stat_datetime, downloader_id))"
            )
            # 创建小时聚合表 (PostgreSQL)
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS traffic_stats_hourly (stat_datetime TIMESTAMP NOT NULL, downloader_id VARCHAR(36) NOT NULL, uploaded BIGINT DEFAULT 0, downloaded BIGINT DEFAULT 0, avg_upload_speed BIGINT DEFAULT 0, avg_download_speed BIGINT DEFAULT 0, samples INTEGER DEFAULT 0, cumulative_uploaded BIGINT NOT NULL DEFAULT 0, cumulative_downloaded BIGINT NOT NULL DEFAULT 0, PRIMARY KEY (stat_datetime, downloader_id))"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS downloader_clients (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255) NOT NULL, type VARCHAR(50) NOT NULL, last_total_dl BIGINT NOT NULL DEFAULT 0, last_total_ul BIGINT NOT NULL DEFAULT 0)"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS torrents (hash VARCHAR(40) PRIMARY KEY, name TEXT NOT NULL, save_path TEXT, size BIGINT, progress REAL, state VARCHAR(50), sites VARCHAR(255), \"group\" VARCHAR(255), details TEXT, downloader_id VARCHAR(36), last_seen TIMESTAMP NOT NULL, iyuu_last_check TIMESTAMP NULL)"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS torrent_upload_stats (hash VARCHAR(40) NOT NULL, downloader_id VARCHAR(36) NOT NULL, uploaded BIGINT DEFAULT 0, PRIMARY KEY (hash, downloader_id))"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS sites (id SERIAL PRIMARY KEY, site VARCHAR(255) UNIQUE, nickname VARCHAR(255), base_url VARCHAR(255), special_tracker_domain VARCHAR(255), \"group\" VARCHAR(255), description VARCHAR(255), cookie TEXT, migration INTEGER NOT NULL DEFAULT 1, speed_limit INTEGER NOT NULL DEFAULT 0)"
            )
            # 创建种子参数表，用于存储从源站点提取的种子参数
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS seed_parameters (hash VARCHAR(40) NOT NULL, torrent_id VARCHAR(255) NOT NULL, site_name VARCHAR(255) NOT NULL, nickname VARCHAR(255), save_path TEXT, name TEXT, title TEXT, subtitle TEXT, imdb_link TEXT, douban_link TEXT, type VARCHAR(100), medium VARCHAR(100), video_codec VARCHAR(100), audio_codec VARCHAR(100), resolution VARCHAR(100), team VARCHAR(100), source VARCHAR(100), tags TEXT, poster TEXT, screenshots TEXT, statement TEXT, body TEXT, mediainfo TEXT, title_components TEXT, removed_ardtudeclarations TEXT, downloader_id VARCHAR(36), is_deleted BOOLEAN NOT NULL DEFAULT FALSE, is_reviewed BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMP NOT NULL, updated_at TIMESTAMP NOT NULL, PRIMARY KEY (hash, torrent_id, site_name))"
            )
            # 创建批量转种记录表
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS batch_enhance_records (id SERIAL PRIMARY KEY, title TEXT, batch_id VARCHAR(255) NOT NULL, torrent_id VARCHAR(255) NOT NULL, source_site VARCHAR(255) NOT NULL, target_site VARCHAR(255) NOT NULL, video_size_gb DECIMAL(8,2), status VARCHAR(50) NOT NULL, success_url TEXT, error_detail TEXT, downloader_add_result TEXT, processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, progress VARCHAR(20))"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_batch_records_batch_id ON batch_enhance_records(batch_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_batch_records_torrent_id ON batch_enhance_records(torrent_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_batch_records_status ON batch_enhance_records(status)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_batch_records_processed_at ON batch_enhance_records(processed_at)"
            )
        # 表创建逻辑 (SQLite)
        else:
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS traffic_stats (stat_datetime TEXT NOT NULL, downloader_id TEXT NOT NULL, uploaded INTEGER DEFAULT 0, downloaded INTEGER DEFAULT 0, upload_speed INTEGER DEFAULT 0, download_speed INTEGER DEFAULT 0, cumulative_uploaded INTEGER NOT NULL DEFAULT 0, cumulative_downloaded INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (stat_datetime, downloader_id))"
            )
            # 创建小时聚合表 (SQLite)
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS traffic_stats_hourly (stat_datetime TEXT NOT NULL, downloader_id TEXT NOT NULL, uploaded INTEGER DEFAULT 0, downloaded INTEGER DEFAULT 0, avg_upload_speed INTEGER DEFAULT 0, avg_download_speed INTEGER DEFAULT 0, samples INTEGER DEFAULT 0, cumulative_uploaded INTEGER NOT NULL DEFAULT 0, cumulative_downloaded INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (stat_datetime, downloader_id))"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS downloader_clients (id TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL, last_total_dl INTEGER NOT NULL DEFAULT 0, last_total_ul INTEGER NOT NULL DEFAULT 0)"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS torrents (hash TEXT PRIMARY KEY, name TEXT NOT NULL, save_path TEXT, size INTEGER, progress REAL, state TEXT, sites TEXT, `group` TEXT, details TEXT, downloader_id TEXT, last_seen TEXT NOT NULL, iyuu_last_check TEXT NULL)"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS torrent_upload_stats (hash TEXT NOT NULL, downloader_id TEXT NOT NULL, uploaded INTEGER DEFAULT 0, PRIMARY KEY (hash, downloader_id))"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS sites (id INTEGER PRIMARY KEY AUTOINCREMENT, site TEXT UNIQUE, nickname TEXT, base_url TEXT, special_tracker_domain TEXT, `group` TEXT, description TEXT, cookie TEXT, migration INTEGER NOT NULL DEFAULT 1, speed_limit INTEGER NOT NULL DEFAULT 0)"
            )
            # 创建种子参数表，用于存储从源站点提取的种子参数
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS seed_parameters (hash TEXT NOT NULL, torrent_id TEXT NOT NULL, site_name TEXT NOT NULL, nickname TEXT, save_path TEXT, name TEXT, title TEXT, subtitle TEXT, imdb_link TEXT, douban_link TEXT, type TEXT, medium TEXT, video_codec TEXT, audio_codec TEXT, resolution TEXT, team TEXT, source TEXT, tags TEXT, poster TEXT, screenshots TEXT, statement TEXT, body TEXT, mediainfo TEXT, title_components TEXT, removed_ardtudeclarations TEXT, downloader_id TEXT, is_deleted INTEGER NOT NULL DEFAULT 0, is_reviewed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY (hash, torrent_id, site_name))"
            )
            # 创建批量转种记录表
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS batch_enhance_records (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, batch_id TEXT NOT NULL, torrent_id TEXT NOT NULL, source_site TEXT NOT NULL, target_site TEXT NOT NULL, video_size_gb REAL, status TEXT NOT NULL, success_url TEXT, error_detail TEXT, downloader_add_result TEXT, processed_at TEXT DEFAULT CURRENT_TIMESTAMP, progress TEXT)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_batch_records_batch_id ON batch_enhance_records(batch_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_batch_records_torrent_id ON batch_enhance_records(torrent_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_batch_records_status ON batch_enhance_records(status)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_batch_records_processed_at ON batch_enhance_records(processed_at)"
            )

        conn.commit()

        # 执行数据库迁移：删除 proxy 列
        self._migrate_remove_proxy_column(conn, cursor)

        # 同步站点数据
        self.sync_sites_from_json()

    def aggregate_hourly_traffic(self, retention_hours=48):
        """
        聚合小时流量数据并清理原始数据。
        
        此函数是数据聚合策略的核心，它将 traffic_stats 表中的原始数据按小时聚合到 
        traffic_stats_hourly 表中，然后删除已聚合的原始数据以控制数据库大小。
        
        Args:
            retention_hours (int): 保留原始数据的时间（小时）。
                                  在此时间之前的原始数据将被聚合和删除。
        """
        from datetime import datetime, timedelta

        # 计算聚合和清理的边界时间
        cutoff_time = datetime.now() - timedelta(hours=retention_hours)

        # 添加特殊日期保护逻辑
        # 确保不会聚合最近3天的数据，以防止数据丢失
        # 修改为按日计算，聚合到三天前的00:00:00
        now = datetime.now()
        safe_cutoff = (now - timedelta(days=3)).replace(hour=0,
                                                        minute=0,
                                                        second=0,
                                                        microsecond=0)
        if cutoff_time > safe_cutoff:
            logging.info(f"为防止数据丢失，调整聚合截止时间为 {safe_cutoff}")
            cutoff_time = safe_cutoff

        cutoff_time_str = cutoff_time.strftime("%Y-%m-%d %H:%M:%S")
        ph = self.get_placeholder()

        conn = None
        cursor = None

        try:
            conn = self._get_connection()
            cursor = self._get_cursor(conn)

            # 开始事务
            if self.db_type == "postgresql":
                # PostgreSQL 需要显式开始事务
                cursor.execute("BEGIN")

            # 根据数据库类型生成时间截断函数
            if self.db_type == "mysql":
                time_group_fn = "DATE_FORMAT(stat_datetime, '%Y-%m-%d %H:00:00')"
            elif self.db_type == "postgresql":
                time_group_fn = "DATE_TRUNC('hour', stat_datetime)"
            else:  # sqlite
                time_group_fn = "STRFTIME('%Y-%m-%d %H:00:00', stat_datetime)"

            # 执行聚合查询：从原始表中按小时分组计算聚合值
            # 对于累计存储方式，我们需要计算每个时间段的累计值差值作为该时间段的流量
            if self.db_type == "postgresql":
                aggregate_query = f"""
                    SELECT
                        {time_group_fn} AS hour_group,
                        downloader_id,
                        GREATEST(0, (MAX(cumulative_uploaded) - MIN(cumulative_uploaded))::bigint) AS total_uploaded,
                        GREATEST(0, (MAX(cumulative_downloaded) - MIN(cumulative_downloaded))::bigint) AS total_downloaded,
                        AVG(upload_speed) AS avg_upload_speed,
                        AVG(download_speed) AS avg_download_speed,
                        COUNT(*) AS samples
                    FROM traffic_stats
                    WHERE stat_datetime < {ph}
                    GROUP BY hour_group, downloader_id
                """
            else:
                aggregate_query = f"""
                    SELECT
                        {time_group_fn} AS hour_group,
                        downloader_id,
                        GREATEST(0, MAX(cumulative_uploaded) - MIN(cumulative_uploaded)) AS total_uploaded,
                        GREATEST(0, MAX(cumulative_downloaded) - MIN(cumulative_downloaded)) AS total_downloaded,
                        AVG(upload_speed) AS avg_upload_speed,
                        AVG(download_speed) AS avg_download_speed,
                        COUNT(*) AS samples
                    FROM traffic_stats
                    WHERE stat_datetime < {ph}
                    GROUP BY hour_group, downloader_id
                """

            cursor.execute(aggregate_query, (cutoff_time_str, ))
            aggregated_rows = cursor.fetchall()

            # 如果没有数据需要聚合，则直接返回
            if not aggregated_rows:
                logging.info("没有需要聚合的数据。")
                conn.commit()
                return

            # 批量插入聚合数据到 traffic_stats_hourly 表中
            # 使用 UPSERT 机制处理重复数据
            if self.db_type == "mysql":
                upsert_sql = f"""
                    INSERT INTO traffic_stats_hourly
                    (stat_datetime, downloader_id, uploaded, downloaded, avg_upload_speed, avg_download_speed, samples, cumulative_uploaded, cumulative_downloaded)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                    ON DUPLICATE KEY UPDATE
                    uploaded = uploaded + VALUES(uploaded),
                    downloaded = downloaded + VALUES(downloaded),
                    avg_upload_speed = ((avg_upload_speed * samples) + (VALUES(avg_upload_speed) * VALUES(samples))) / (samples + VALUES(samples)),
                    avg_download_speed = ((avg_download_speed * samples) + (VALUES(avg_download_speed) * VALUES(samples))) / (samples + VALUES(samples)),
                    samples = samples + VALUES(samples),
                    cumulative_uploaded = GREATEST(cumulative_uploaded, VALUES(cumulative_uploaded)),
                    cumulative_downloaded = GREATEST(cumulative_downloaded, VALUES(cumulative_downloaded))
                """
            elif self.db_type == "postgresql":
                upsert_sql = f"""
                    INSERT INTO traffic_stats_hourly
                    (stat_datetime, downloader_id, uploaded, downloaded, avg_upload_speed, avg_download_speed, samples, cumulative_uploaded, cumulative_downloaded)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                    ON CONFLICT (stat_datetime, downloader_id)
                    DO UPDATE SET
                    uploaded = traffic_stats_hourly.uploaded + EXCLUDED.uploaded,
                    downloaded = traffic_stats_hourly.downloaded + EXCLUDED.downloaded,
                    avg_upload_speed = ((traffic_stats_hourly.avg_upload_speed * traffic_stats_hourly.samples) + (EXCLUDED.avg_upload_speed * EXCLUDED.samples)) / (traffic_stats_hourly.samples + EXCLUDED.samples),
                    avg_download_speed = ((traffic_stats_hourly.avg_download_speed * traffic_stats_hourly.samples) + (EXCLUDED.avg_download_speed * EXCLUDED.samples)) / (traffic_stats_hourly.samples + EXCLUDED.samples),
                    samples = traffic_stats_hourly.samples + EXCLUDED.samples,
                    cumulative_uploaded = GREATEST(traffic_stats_hourly.cumulative_uploaded, EXCLUDED.cumulative_uploaded),
                    cumulative_downloaded = GREATEST(traffic_stats_hourly.cumulative_downloaded, EXCLUDED.cumulative_downloaded)
                """
            else:  # sqlite
                upsert_sql = f"""
                    INSERT INTO traffic_stats_hourly
                    (stat_datetime, downloader_id, uploaded, downloaded, avg_upload_speed, avg_download_speed, samples, cumulative_uploaded, cumulative_downloaded)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                    ON CONFLICT (stat_datetime, downloader_id)
                    DO UPDATE SET
                    uploaded = traffic_stats_hourly.uploaded + excluded.uploaded,
                    downloaded = traffic_stats_hourly.downloaded + excluded.downloaded,
                    avg_upload_speed = ((traffic_stats_hourly.avg_upload_speed * traffic_stats_hourly.samples) + (excluded.avg_upload_speed * excluded.samples)) / (traffic_stats_hourly.samples + excluded.samples),
                    avg_download_speed = ((traffic_stats_hourly.avg_download_speed * traffic_stats_hourly.samples) + (excluded.avg_download_speed * excluded.samples)) / (traffic_stats_hourly.samples + excluded.samples),
                    samples = traffic_stats_hourly.samples + excluded.samples,
                    cumulative_uploaded = MAX(traffic_stats_hourly.cumulative_uploaded, excluded.cumulative_uploaded),
                    cumulative_downloaded = MAX(traffic_stats_hourly.cumulative_downloaded, excluded.cumulative_downloaded)
                """

            # 准备插入参数
            # 对于累计值，我们需要获取每个时间段内最后一个记录的累计值
            # 重新查询以获取累计值
            if self.db_type == "mysql":
                time_group_fn = "DATE_FORMAT(stat_datetime, '%Y-%m-%d %H:00:00')"
            elif self.db_type == "postgresql":
                time_group_fn = "DATE_TRUNC('hour', stat_datetime)"
            else:  # sqlite
                time_group_fn = "STRFTIME('%Y-%m-%d %H:00:00', stat_datetime)"

            cumulative_query = f"""
                SELECT
                    {time_group_fn} AS hour_group,
                    downloader_id,
                    MAX(cumulative_uploaded) AS final_cumulative_uploaded,
                    MAX(cumulative_downloaded) AS final_cumulative_downloaded
                FROM traffic_stats
                WHERE stat_datetime < {ph}
                GROUP BY hour_group, downloader_id
            """

            cursor.execute(cumulative_query, (cutoff_time_str, ))
            cumulative_rows = cursor.fetchall()

            # 创建累计值映射字典
            cumulative_map = {}
            for row in cumulative_rows:
                key = (row["hour_group"] if isinstance(row, dict) else row[0],
                       row["downloader_id"]
                       if isinstance(row, dict) else row[1])
                cumulative_map[key] = (
                    int(row["final_cumulative_uploaded"] if isinstance(
                        row, dict) else row[2]),
                    int(row["final_cumulative_downloaded"] if isinstance(
                        row, dict) else row[3]))

            # 准备插入参数
            upsert_params = [
                (row["hour_group"] if isinstance(row, dict) else row[0],
                 row["downloader_id"] if isinstance(row, dict) else row[1],
                 int(row["total_uploaded"] if isinstance(row, dict) else row[2]
                     ),
                 int(row["total_downloaded"] if isinstance(row, dict
                                                           ) else row[3]),
                 int(row["avg_upload_speed"] if isinstance(row, dict
                                                           ) else row[4]),
                 int(row["avg_download_speed"] if isinstance(row, dict
                                                             ) else row[5]),
                 int(row["samples"] if isinstance(row, dict) else row[6]),
                 cumulative_map.get(
                     (row["hour_group"] if isinstance(row, dict) else row[0],
                      row["downloader_id"]
                      if isinstance(row, dict) else row[1]), (0, 0))[0],
                 cumulative_map.get(
                     (row["hour_group"] if isinstance(row, dict) else row[0],
                      row["downloader_id"]
                      if isinstance(row, dict) else row[1]), (0, 0))[1])
                for row in aggregated_rows
            ]

            cursor.executemany(upsert_sql, upsert_params)

            # 删除已聚合的原始数据
            delete_query = f"DELETE FROM traffic_stats WHERE stat_datetime < {ph}"
            cursor.execute(delete_query, (cutoff_time_str, ))

            # 提交事务
            conn.commit()

            logging.info(
                f"成功聚合 {len(aggregated_rows)} 条小时数据，并清理了 {cursor.rowcount} 条原始数据。"
            )
        except Exception as e:
            # 回滚事务
            if conn:
                conn.rollback()
            logging.error(f"聚合小时流量数据时出错: {e}", exc_info=True)
            raise
        finally:
            # 关闭游标和连接
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def _migrate_remove_proxy_column(self, conn, cursor):
        """数据库迁移：删除 sites 表中的 proxy 列"""
        try:
            logging.info("检查是否需要删除 sites 表中的 proxy 列...")
            
            # 检查 proxy 列是否存在
            column_exists = False
            
            if self.db_type == "mysql":
                cursor.execute("SHOW COLUMNS FROM sites LIKE 'proxy'")
                column_exists = cursor.fetchone() is not None
                
                if column_exists:
                    logging.info("检测到 proxy 列，正在删除...")
                    cursor.execute("ALTER TABLE sites DROP COLUMN proxy")
                    conn.commit()
                    logging.info("✓ 成功删除 sites 表中的 proxy 列 (MySQL)")
                    
            elif self.db_type == "postgresql":
                cursor.execute("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='sites' AND column_name='proxy'
                """)
                column_exists = cursor.fetchone() is not None
                
                if column_exists:
                    logging.info("检测到 proxy 列，正在删除...")
                    cursor.execute('ALTER TABLE sites DROP COLUMN proxy')
                    conn.commit()
                    logging.info("✓ 成功删除 sites 表中的 proxy 列 (PostgreSQL)")
                    
            else:  # SQLite
                # SQLite 不支持 DROP COLUMN（旧版本），需要重建表
                cursor.execute("PRAGMA table_info(sites)")
                columns = cursor.fetchall()
                column_exists = any(col[1] == 'proxy' for col in columns)
                
                if column_exists:
                    logging.info("检测到 proxy 列，正在重建表以删除该列...")
                    
                    # 创建新表（不包含 proxy 列）
                    cursor.execute("""
                        CREATE TABLE sites_new (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            site TEXT UNIQUE,
                            nickname TEXT,
                            base_url TEXT,
                            special_tracker_domain TEXT,
                            `group` TEXT,
                            description TEXT,
                            cookie TEXT,
                            migration INTEGER NOT NULL DEFAULT 1,
                            speed_limit INTEGER NOT NULL DEFAULT 0
                        )
                    """)
                    
                    # 复制数据（排除 proxy 列）
                    cursor.execute("""
                        INSERT INTO sites_new 
                        (id, site, nickname, base_url, special_tracker_domain, `group`, 
                         description, cookie, migration, speed_limit)
                        SELECT id, site, nickname, base_url, special_tracker_domain, `group`,
                               description, cookie, migration, speed_limit
                        FROM sites
                    """)
                    
                    # 删除旧表
                    cursor.execute("DROP TABLE sites")
                    
                    # 重命名新表
                    cursor.execute("ALTER TABLE sites_new RENAME TO sites")
                    
                    conn.commit()
                    logging.info("✓ 成功删除 sites 表中的 proxy 列 (SQLite)")
            
            if not column_exists:
                logging.info("proxy 列不存在，无需迁移")
                
        except Exception as e:
            logging.warning(f"迁移删除 proxy 列时出错（可能已经删除）: {e}")
            # 不要因为迁移失败而中断初始化
            conn.rollback()

    def _sync_downloaders_from_config(self, cursor):
        """从配置文件同步下载器列表到 downloader_clients 表。"""
        downloaders = config_manager.get().get("downloaders", [])
        if not downloaders:
            return

        cursor.execute("SELECT id FROM downloader_clients")
        db_ids = {row["id"] for row in cursor.fetchall()}
        config_ids = {d["id"] for d in downloaders}
        ph = self.get_placeholder()

        for d in downloaders:
            if d["id"] in db_ids:
                cursor.execute(
                    f"UPDATE downloader_clients SET name = {ph}, type = {ph} WHERE id = {ph}",
                    (d["name"], d["type"], d["id"]),
                )
            else:
                # 修复：在插入新下载器时初始化last_total_dl和last_total_ul字段
                cursor.execute(
                    f"INSERT INTO downloader_clients (id, name, type, last_total_dl, last_total_ul) VALUES ({ph}, {ph}, {ph}, 0, 0)",
                    (d["id"], d["name"], d["type"]),
                )

        ids_to_delete = db_ids - config_ids
        if ids_to_delete:
            cursor.execute(
                f"DELETE FROM downloader_clients WHERE id IN ({', '.join([ph] * len(ids_to_delete))})",
                tuple(ids_to_delete),
            )


def reconcile_historical_data(db_manager, config):
    """在启动时同步下载器状态到数据库。"""
    logging.info("正在同步下载器状态...")
    conn = db_manager._get_connection()
    cursor = db_manager._get_cursor(conn)
    ph = db_manager.get_placeholder()

    records = []
    current_timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for client_config in config.get("downloaders", []):
        if not client_config.get("enabled"):
            continue
        client_id = client_config["id"]
        try:
            total_dl, total_ul = 0, 0
            if client_config["type"] == "qbittorrent":
                api_config = _prepare_api_config(client_config)
                client = Client(**api_config)
                client.auth_log_in()
                server_state = client.sync_maindata().get('server_state', {})
                total_dl = int(server_state.get('alltime_dl', 0))
                total_ul = int(server_state.get('alltime_ul', 0))
            elif client_config["type"] == "transmission":
                api_config = _prepare_api_config(client_config)
                client = TrClient(**api_config)
                stats = client.session_stats()
                total_dl = int(stats.cumulative_stats.downloaded_bytes)
                total_ul = int(stats.cumulative_stats.uploaded_bytes)

            records.append((current_timestamp_str, client_id, 0, 0, 0, 0,
                            total_ul, total_dl))
            logging.info(f"客户端 '{client_config['name']}' 的状态已同步。")
        except Exception as e:
            logging.error(f"[{client_config['name']}] 状态同步失败: {e}")

    if records:
        try:
            sql_insert = (
                f"INSERT INTO traffic_stats (stat_datetime, downloader_id, uploaded, downloaded, upload_speed, download_speed, cumulative_uploaded, cumulative_downloaded) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}) ON CONFLICT(stat_datetime, downloader_id) DO UPDATE SET uploaded = EXCLUDED.uploaded, downloaded = EXCLUDED.downloaded, cumulative_uploaded = EXCLUDED.cumulative_uploaded, cumulative_downloaded = EXCLUDED.cumulative_downloaded"
                if db_manager.db_type == "postgresql" else
                f"INSERT INTO traffic_stats (stat_datetime, downloader_id, uploaded, downloaded, upload_speed, download_speed, cumulative_uploaded, cumulative_downloaded) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}) ON DUPLICATE KEY UPDATE uploaded = VALUES(uploaded), downloaded = VALUES(downloaded), cumulative_uploaded = VALUES(cumulative_uploaded), cumulative_downloaded = VALUES(cumulative_downloaded)"
                if db_manager.db_type == "mysql" else
                f"INSERT INTO traffic_stats (stat_datetime, downloader_id, uploaded, downloaded, upload_speed, download_speed, cumulative_uploaded, cumulative_downloaded) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(stat_datetime, downloader_id) DO UPDATE SET uploaded = excluded.uploaded, downloaded = excluded.downloaded, cumulative_uploaded = excluded.cumulative_uploaded, cumulative_downloaded = excluded.cumulative_downloaded"
            )
            cursor.executemany(sql_insert, records)
            logging.info(f"已成功插入 {len(records)} 条初始记录到 traffic_stats。")
        except Exception as e:
            logging.error(f"插入初始记录失败: {e}")
            conn.rollback()

    conn.commit()
    cursor.close()
    conn.close()
