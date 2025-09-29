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

    def _run_schema_migrations(self, conn, cursor):
        """检查并执行必要的数据库结构变更。"""
        logging.info("正在运行数据库结构迁移检查...")

        # --- 迁移 downloader_clients 表 ---
        table_name = 'downloader_clients'
        # 获取当前表的列信息
        if self.db_type == 'mysql':
            cursor.execute(f"DESCRIBE {table_name}")
            columns = {row['Field'].lower() for row in cursor.fetchall()}
        elif self.db_type == 'postgresql':
            cursor.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s AND table_schema = 'public'",
                (table_name, ))
            columns = {row['column_name'].lower() for row in cursor.fetchall()}
        else:  # sqlite
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = {row['name'].lower() for row in cursor.fetchall()}

        # 检查是否需要新的统一列
        if 'last_total_dl' not in columns:
            logging.info(
                f"在 '{table_name}' 表中添加 'last_total_dl' 和 'last_total_ul' 列..."
            )
            if self.db_type == 'mysql':
                cursor.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN last_total_dl BIGINT NOT NULL DEFAULT 0"
                )
                cursor.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN last_total_ul BIGINT NOT NULL DEFAULT 0"
                )
            else:
                cursor.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN last_total_dl INTEGER NOT NULL DEFAULT 0"
                )
                cursor.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN last_total_ul INTEGER NOT NULL DEFAULT 0"
                )
            conn.commit()
            logging.info("新列添加成功。")

        # 检查并移除旧的、不再使用的列
        old_columns_to_drop = [
            'last_session_dl', 'last_session_ul', 'last_cumulative_dl',
            'last_cumulative_ul'
        ]
        for col in old_columns_to_drop:
            if col in columns:
                logging.info(f"正在从 '{table_name}' 表中移除已过时的列: '{col}'...")
                # SQLite 在较新版本才支持 DROP COLUMN，MySQL 支持
                if self.db_type == 'mysql':
                    cursor.execute(
                        f"ALTER TABLE {table_name} DROP COLUMN {col}")
                else:
                    # 对于 SQLite，需要重建表的复杂操作在这里不演示，
                    # 较新版本 (3.35.0+) 直接支持 DROP COLUMN
                    cursor.execute(
                        f"ALTER TABLE {table_name} DROP COLUMN {col}")
                conn.commit()
                logging.info(f"'{col}' 列移除成功。")

        # --- 迁移 seed_parameters 表，添加 nickname 列 ---
        table_name = 'seed_parameters'
        # 获取当前表的列信息
        if self.db_type == 'mysql':
            cursor.execute(f"DESCRIBE {table_name}")
            columns = {row['Field'].lower() for row in cursor.fetchall()}
        elif self.db_type == 'postgresql':
            cursor.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s AND table_schema = 'public'",
                (table_name, ))
            columns = {row['column_name'].lower() for row in cursor.fetchall()}
        else:  # sqlite
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = {row['name'].lower() for row in cursor.fetchall()}

        # 检查是否需要添加 nickname 列
        if 'nickname' not in columns:
            logging.info(f"在 '{table_name}' 表中添加 'nickname' 列...")
            if self.db_type == 'mysql':
                cursor.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN nickname VARCHAR(255)"
                )
            elif self.db_type == 'postgresql':
                cursor.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN nickname VARCHAR(255)"
                )
            else:  # sqlite
                cursor.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN nickname TEXT")
            conn.commit()
            logging.info("'nickname' 列添加成功。")

        # 检查是否需要添加 is_deleted 列
        if 'is_deleted' not in columns:
            logging.info(f"在 '{table_name}' 表中添加 'is_deleted' 列...")
            if self.db_type == 'mysql':
                cursor.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN is_deleted TINYINT(1) NOT NULL DEFAULT 0"
                )
            elif self.db_type == 'postgresql':
                cursor.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN is_deleted BOOLEAN NOT NULL DEFAULT FALSE"
                )
            else:  # sqlite
                cursor.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0")
            conn.commit()
            logging.info("'is_deleted' 列添加成功。")

    def _migrate_torrents_table(self, conn, cursor):
        """检查并向 torrents 表添加 downloader_id 和 iyuu_last_check 列。"""
        table_name = 'torrents'
        if self.db_type == 'mysql':
            cursor.execute(f"DESCRIBE {table_name}")
            columns = {row['Field'].lower() for row in cursor.fetchall()}
        elif self.db_type == 'postgresql':
            cursor.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s AND table_schema = 'public'",
                (table_name, ))
            columns = {row['column_name'].lower() for row in cursor.fetchall()}
        else:  # sqlite
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = {row['name'].lower() for row in cursor.fetchall()}

        if 'downloader_id' not in columns:
            logging.info(f"正在向 '{table_name}' 表添加 'downloader_id' 列...")
            if self.db_type == 'mysql':
                cursor.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN downloader_id VARCHAR(36) NULL"
                )
            else:
                cursor.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN downloader_id TEXT NULL"
                )
            conn.commit()
            logging.info("'downloader_id' 列添加成功。")

        if 'iyuu_last_check' not in columns:
            logging.info(f"正在向 '{table_name}' 表添加 'iyuu_last_check' 列...")
            if self.db_type == 'mysql':
                cursor.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN iyuu_last_check DATETIME NULL"
                )
            elif self.db_type == 'postgresql':
                cursor.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN iyuu_last_check TIMESTAMP NULL"
                )
            else:  # sqlite
                cursor.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN iyuu_last_check TEXT NULL"
                )
            conn.commit()
            logging.info("'iyuu_last_check' 列添加成功。")

        # --- 迁移/创建 batch_enhance_records 表 ---
        batch_records_table = 'batch_enhance_records'

        # 检查batch_enhance_records表是否存在
        table_exists = False
        if self.db_type == 'mysql':
            cursor.execute("SHOW TABLES LIKE %s", (batch_records_table,))
            table_exists = cursor.fetchone() is not None
        elif self.db_type == 'postgresql':
            cursor.execute(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = %s AND table_schema = 'public')",
                (batch_records_table,)
            )
            result = cursor.fetchone()
            table_exists = result[0] if isinstance(result, tuple) else result['exists']
        else:  # sqlite
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (batch_records_table,)
            )
            table_exists = cursor.fetchone() is not None

        # 如果表不存在，创建它
        if not table_exists:
            logging.info(f"批量转种记录表 '{batch_records_table}' 不存在，正在创建...")
            if self.db_type == 'mysql':
                cursor.execute(
                    "CREATE TABLE batch_enhance_records (id INT AUTO_INCREMENT PRIMARY KEY, batch_id VARCHAR(255) NOT NULL, torrent_id VARCHAR(255) NOT NULL, source_site VARCHAR(255) NOT NULL, target_site VARCHAR(255) NOT NULL, video_size_gb DECIMAL(8,2), status VARCHAR(50) NOT NULL, success_url TEXT, error_detail TEXT, processed_at DATETIME DEFAULT CURRENT_TIMESTAMP, INDEX idx_batch_records_batch_id (batch_id), INDEX idx_batch_records_torrent_id (torrent_id), INDEX idx_batch_records_status (status), INDEX idx_batch_records_processed_at (processed_at)) ENGINE=InnoDB ROW_FORMAT=DYNAMIC"
                )
            elif self.db_type == 'postgresql':
                cursor.execute(
                    "CREATE TABLE batch_enhance_records (id SERIAL PRIMARY KEY, batch_id VARCHAR(255) NOT NULL, torrent_id VARCHAR(255) NOT NULL, source_site VARCHAR(255) NOT NULL, target_site VARCHAR(255) NOT NULL, video_size_gb DECIMAL(8,2), status VARCHAR(50) NOT NULL, success_url TEXT, error_detail TEXT, processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
                )
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_batch_records_batch_id ON batch_enhance_records(batch_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_batch_records_torrent_id ON batch_enhance_records(torrent_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_batch_records_status ON batch_enhance_records(status)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_batch_records_processed_at ON batch_enhance_records(processed_at)")
            else:  # sqlite
                cursor.execute(
                    "CREATE TABLE batch_enhance_records (id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id TEXT NOT NULL, torrent_id TEXT NOT NULL, source_site TEXT NOT NULL, target_site TEXT NOT NULL, video_size_gb REAL, status TEXT NOT NULL, success_url TEXT, error_detail TEXT, processed_at TEXT DEFAULT CURRENT_TIMESTAMP)"
                )
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_batch_records_batch_id ON batch_enhance_records(batch_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_batch_records_torrent_id ON batch_enhance_records(torrent_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_batch_records_status ON batch_enhance_records(status)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_batch_records_processed_at ON batch_enhance_records(processed_at)")

            conn.commit()
            logging.info(f"批量转种记录表 '{batch_records_table}' 创建成功。")

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
                sql = f"INSERT INTO sites (site, nickname, base_url, special_tracker_domain, \"group\", cookie, passkey, proxy, speed_limit) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})"
            else:
                sql = f"INSERT INTO sites (site, nickname, base_url, special_tracker_domain, `group`, cookie, passkey, proxy, speed_limit) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})"
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
                cookie,
                site_data.get("passkey"),
                int(site_data.get("proxy", 0)),
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
                sql = f"UPDATE sites SET nickname = {ph}, base_url = {ph}, special_tracker_domain = {ph}, \"group\" = {ph}, cookie = {ph}, passkey = {ph}, proxy = {ph}, speed_limit = {ph} WHERE id = {ph}"
            else:
                sql = f"UPDATE sites SET nickname = {ph}, base_url = {ph}, special_tracker_domain = {ph}, `group` = {ph}, cookie = {ph}, passkey = {ph}, proxy = {ph}, speed_limit = {ph} WHERE id = {ph}"
            # 去除cookie字符串首尾的换行符和多余空白字符
            cookie = site_data.get("cookie")
            if cookie:
                cookie = cookie.strip()

            params = (
                site_data.get("nickname"),
                site_data.get("base_url"),
                site_data.get("special_tracker_domain"),
                site_data.get("group"),
                cookie,
                site_data.get("passkey"),
                int(site_data.get("proxy", 0)),
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

    def _add_missing_columns(self, conn, cursor):
        """检查并向 sites 表添加缺失的列，实现自动化的数据库迁移。"""
        logging.info("正在检查 'sites' 表的结构完整性...")
        columns_to_add = [
            ("cookie", "TEXT", "TEXT"), ("passkey", "TEXT", "VARCHAR(255)"),
            ("migration", "INTEGER DEFAULT 0", "TINYINT DEFAULT 0"),
            ("proxy", "INTEGER NOT NULL DEFAULT 0",
             "TINYINT NOT NULL DEFAULT 0"),
            ("speed_limit", "INTEGER DEFAULT 0", "INTEGER DEFAULT 0")
        ]

        if self.db_type == "mysql":
            meta_cursor = conn.cursor()
            meta_cursor.execute(
                "SELECT column_name FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = %s AND table_name = 'sites'",
                (self.mysql_config.get("database"), ),
            )
            existing_columns = {
                row[0].lower()
                for row in meta_cursor.fetchall()
            }
            meta_cursor.close()
            for col_name, _, mysql_type in columns_to_add:
                if col_name.lower() not in existing_columns:
                    logging.info(
                        f"在 MySQL 'sites' 表中发现缺失列: '{col_name}'。正在添加...")
                    cursor.execute(
                        f"ALTER TABLE `sites` ADD COLUMN `{col_name}` {mysql_type}"
                    )
        elif self.db_type == "postgresql":
            meta_cursor = conn.cursor(cursor_factory=RealDictCursor)
            meta_cursor.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'sites'"
            )
            existing_columns = {
                row["column_name"].lower()
                for row in meta_cursor.fetchall()
            }
            meta_cursor.close()
            for col_name, _, mysql_type in columns_to_add:
                if col_name.lower() not in existing_columns:
                    # PostgreSQL type mappings
                    postgresql_type = {
                        "TINYINT DEFAULT 0":
                        "SMALLINT DEFAULT 0",
                        "TINYINT NOT NULL DEFAULT 0":
                        "SMALLINT NOT NULL DEFAULT 0",
                    }.get(mysql_type, mysql_type)
                    logging.info(
                        f"在 PostgreSQL 'sites' 表中发现缺失列: '{col_name}'。正在添加...")
                    cursor.execute(
                        f"ALTER TABLE sites ADD COLUMN {col_name} {postgresql_type}"
                    )
        else:  # SQLite
            cursor.execute("PRAGMA table_info(sites)")
            existing_columns = {
                row["name"].lower()
                for row in cursor.fetchall()
            }
            for col_name, sqlite_type, _ in columns_to_add:
                if col_name.lower() not in existing_columns:
                    logging.info(
                        f"在 SQLite 'sites' 表中发现缺失列: '{col_name}'。正在添加...")
                    cursor.execute(
                        f"ALTER TABLE sites ADD COLUMN {col_name} {sqlite_type}"
                    )

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

                        # 构建更新语句，不包含 cookie, passkey, proxy
                        if self.db_type == "postgresql":
                            update_sql = """
                                UPDATE sites
                                SET site = %s, nickname = %s, base_url = %s, special_tracker_domain = %s,
                                    "group" = %s, migration = %s, speed_limit = %s
                                WHERE id = %s
                            """
                        else:
                            update_sql = """
                                UPDATE sites
                                SET site = %s, nickname = %s, base_url = %s, special_tracker_domain = %s,
                                    `group` = %s, migration = %s, speed_limit = %s
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
                                (site, nickname, base_url, special_tracker_domain, "group", migration, speed_limit)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """, (site_info.get('site'),
                                  site_info.get('nickname'),
                                  site_info.get('base_url'),
                                  site_info.get('special_tracker_domain'),
                                  site_info.get('group'),
                                  site_info.get('migration', 0),
                                  site_info.get('speed_limit', 0)))
                        else:
                            # 添加新站点
                            cursor.execute(
                                """
                                INSERT INTO sites 
                                (site, nickname, base_url, special_tracker_domain, `group`, migration, speed_limit)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """, (site_info.get('site'),
                                  site_info.get('nickname'),
                                  site_info.get('base_url'),
                                  site_info.get('special_tracker_domain'),
                                  site_info.get('group'),
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
                "CREATE TABLE IF NOT EXISTS traffic_stats (stat_datetime DATETIME NOT NULL, downloader_id VARCHAR(36) NOT NULL, uploaded BIGINT DEFAULT 0, downloaded BIGINT DEFAULT 0, upload_speed BIGINT DEFAULT 0, download_speed BIGINT DEFAULT 0, PRIMARY KEY (stat_datetime, downloader_id)) ENGINE=InnoDB ROW_FORMAT=Dynamic"
            )
            # 创建小时聚合表 (MySQL)
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS traffic_stats_hourly (stat_datetime DATETIME NOT NULL, downloader_id VARCHAR(36) NOT NULL, uploaded BIGINT DEFAULT 0, downloaded BIGINT DEFAULT 0, avg_upload_speed BIGINT DEFAULT 0, avg_download_speed BIGINT DEFAULT 0, samples INTEGER DEFAULT 0, PRIMARY KEY (stat_datetime, downloader_id)) ENGINE=InnoDB ROW_FORMAT=Dynamic"
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
                "CREATE TABLE IF NOT EXISTS `sites` (`id` mediumint NOT NULL AUTO_INCREMENT, `site` varchar(255) UNIQUE DEFAULT NULL, `nickname` varchar(255) DEFAULT NULL, `base_url` varchar(255) DEFAULT NULL, `special_tracker_domain` varchar(255) DEFAULT NULL, `group` varchar(255) DEFAULT NULL, `cookie` TEXT DEFAULT NULL,`passkey` varchar(255) DEFAULT NULL,`migration` int(11) NOT NULL DEFAULT 1, `speed_limit` int(11) NOT NULL DEFAULT 0, PRIMARY KEY (`id`)) ENGINE=InnoDB ROW_FORMAT=DYNAMIC"
            )
            # 创建种子参数表，用于存储从源站点提取的种子参数
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS seed_parameters (hash VARCHAR(40) NOT NULL, torrent_id VARCHAR(255) NOT NULL, site_name VARCHAR(255) NOT NULL, nickname VARCHAR(255), save_path TEXT, title TEXT, subtitle TEXT, imdb_link TEXT, douban_link TEXT, type VARCHAR(100), medium VARCHAR(100), video_codec VARCHAR(100), audio_codec VARCHAR(100), resolution VARCHAR(100), team VARCHAR(100), source VARCHAR(100), tags TEXT, poster TEXT, screenshots TEXT, statement TEXT, body TEXT, mediainfo TEXT, title_components TEXT, is_deleted TINYINT(1) NOT NULL DEFAULT 0, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, PRIMARY KEY (hash, torrent_id, site_name)) ENGINE=InnoDB ROW_FORMAT=DYNAMIC"
            )
            # 创建批量转种记录表
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS batch_enhance_records (id INT AUTO_INCREMENT PRIMARY KEY, batch_id VARCHAR(255) NOT NULL, torrent_id VARCHAR(255) NOT NULL, source_site VARCHAR(255) NOT NULL, target_site VARCHAR(255) NOT NULL, video_size_gb DECIMAL(8,2), status VARCHAR(50) NOT NULL, success_url TEXT, error_detail TEXT, processed_at DATETIME DEFAULT CURRENT_TIMESTAMP, INDEX idx_batch_records_batch_id (batch_id), INDEX idx_batch_records_torrent_id (torrent_id), INDEX idx_batch_records_status (status), INDEX idx_batch_records_processed_at (processed_at)) ENGINE=InnoDB ROW_FORMAT=DYNAMIC"
            )
        # 表创建逻辑 (PostgreSQL)
        elif self.db_type == "postgresql":
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS traffic_stats (stat_datetime TIMESTAMP NOT NULL, downloader_id VARCHAR(36) NOT NULL, uploaded BIGINT DEFAULT 0, downloaded BIGINT DEFAULT 0, upload_speed BIGINT DEFAULT 0, download_speed BIGINT DEFAULT 0, PRIMARY KEY (stat_datetime, downloader_id))"
            )
            # 创建小时聚合表 (PostgreSQL)
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS traffic_stats_hourly (stat_datetime TIMESTAMP NOT NULL, downloader_id VARCHAR(36) NOT NULL, uploaded BIGINT DEFAULT 0, downloaded BIGINT DEFAULT 0, avg_upload_speed BIGINT DEFAULT 0, avg_download_speed BIGINT DEFAULT 0, samples INTEGER DEFAULT 0, PRIMARY KEY (stat_datetime, downloader_id))"
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
                "CREATE TABLE IF NOT EXISTS sites (id SERIAL PRIMARY KEY, site VARCHAR(255) UNIQUE, nickname VARCHAR(255), base_url VARCHAR(255), special_tracker_domain VARCHAR(255), \"group\" VARCHAR(255), cookie TEXT, passkey VARCHAR(255), migration INTEGER NOT NULL DEFAULT 1, speed_limit INTEGER NOT NULL DEFAULT 0)"
            )
            # 创建种子参数表，用于存储从源站点提取的种子参数
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS seed_parameters (hash VARCHAR(40) NOT NULL, torrent_id VARCHAR(255) NOT NULL, site_name VARCHAR(255) NOT NULL, nickname VARCHAR(255), save_path TEXT, title TEXT, subtitle TEXT, imdb_link TEXT, douban_link TEXT, type VARCHAR(100), medium VARCHAR(100), video_codec VARCHAR(100), audio_codec VARCHAR(100), resolution VARCHAR(100), team VARCHAR(100), source VARCHAR(100), tags TEXT, poster TEXT, screenshots TEXT, statement TEXT, body TEXT, mediainfo TEXT, title_components TEXT, is_deleted BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMP NOT NULL, updated_at TIMESTAMP NOT NULL, PRIMARY KEY (hash, torrent_id, site_name))"
            )
            # 创建批量转种记录表
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS batch_enhance_records (id SERIAL PRIMARY KEY, batch_id VARCHAR(255) NOT NULL, torrent_id VARCHAR(255) NOT NULL, source_site VARCHAR(255) NOT NULL, target_site VARCHAR(255) NOT NULL, video_size_gb DECIMAL(8,2), status VARCHAR(50) NOT NULL, success_url TEXT, error_detail TEXT, processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_batch_records_batch_id ON batch_enhance_records(batch_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_batch_records_torrent_id ON batch_enhance_records(torrent_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_batch_records_status ON batch_enhance_records(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_batch_records_processed_at ON batch_enhance_records(processed_at)")
        # 表创建逻辑 (SQLite)
        else:
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS traffic_stats (stat_datetime TEXT NOT NULL, downloader_id TEXT NOT NULL, uploaded INTEGER DEFAULT 0, downloaded INTEGER DEFAULT 0, upload_speed INTEGER DEFAULT 0, download_speed INTEGER DEFAULT 0, PRIMARY KEY (stat_datetime, downloader_id))"
            )
            # 创建小时聚合表 (SQLite)
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS traffic_stats_hourly (stat_datetime TEXT NOT NULL, downloader_id TEXT NOT NULL, uploaded INTEGER DEFAULT 0, downloaded INTEGER DEFAULT 0, avg_upload_speed INTEGER DEFAULT 0, avg_download_speed INTEGER DEFAULT 0, samples INTEGER DEFAULT 0, PRIMARY KEY (stat_datetime, downloader_id))"
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
                "CREATE TABLE IF NOT EXISTS sites (id INTEGER PRIMARY KEY AUTOINCREMENT, site TEXT UNIQUE, nickname TEXT, base_url TEXT, special_tracker_domain TEXT, `group` TEXT, cookie TEXT, passkey TEXT, migration INTEGER NOT NULL DEFAULT 1, speed_limit INTEGER NOT NULL DEFAULT 0)"
            )
            # 创建种子参数表，用于存储从源站点提取的种子参数
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS seed_parameters (hash TEXT NOT NULL, torrent_id TEXT NOT NULL, site_name TEXT NOT NULL, nickname TEXT, save_path TEXT, title TEXT, subtitle TEXT, imdb_link TEXT, douban_link TEXT, type TEXT, medium TEXT, video_codec TEXT, audio_codec TEXT, resolution TEXT, team TEXT, source TEXT, tags TEXT, poster TEXT, screenshots TEXT, statement TEXT, body TEXT, mediainfo TEXT, title_components TEXT, is_deleted INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY (hash, torrent_id, site_name))"
            )
            # 创建批量转种记录表
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS batch_enhance_records (id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id TEXT NOT NULL, torrent_id TEXT NOT NULL, source_site TEXT NOT NULL, target_site TEXT NOT NULL, video_size_gb REAL, status TEXT NOT NULL, success_url TEXT, error_detail TEXT, processed_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_batch_records_batch_id ON batch_enhance_records(batch_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_batch_records_torrent_id ON batch_enhance_records(torrent_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_batch_records_status ON batch_enhance_records(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_batch_records_processed_at ON batch_enhance_records(processed_at)")

        conn.commit()
        self._migrate_torrents_table(conn, cursor)
        self._run_schema_migrations(conn, cursor)
        self._add_missing_columns(conn, cursor)
        conn.commit()

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
            aggregate_query = f"""
                SELECT 
                    {time_group_fn} AS hour_group,
                    downloader_id,
                    SUM(uploaded) AS total_uploaded,
                    SUM(downloaded) AS total_downloaded,
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
                    (stat_datetime, downloader_id, uploaded, downloaded, avg_upload_speed, avg_download_speed, samples)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                    ON DUPLICATE KEY UPDATE
                    uploaded = uploaded + VALUES(uploaded),
                    downloaded = downloaded + VALUES(downloaded),
                    avg_upload_speed = ((avg_upload_speed * samples) + (VALUES(avg_upload_speed) * VALUES(samples))) / (samples + VALUES(samples)),
                    avg_download_speed = ((avg_download_speed * samples) + (VALUES(avg_download_speed) * VALUES(samples))) / (samples + VALUES(samples)),
                    samples = samples + VALUES(samples)
                """
            elif self.db_type == "postgresql":
                upsert_sql = f"""
                    INSERT INTO traffic_stats_hourly 
                    (stat_datetime, downloader_id, uploaded, downloaded, avg_upload_speed, avg_download_speed, samples)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                    ON CONFLICT (stat_datetime, downloader_id) 
                    DO UPDATE SET
                    uploaded = traffic_stats_hourly.uploaded + EXCLUDED.uploaded,
                    downloaded = traffic_stats_hourly.downloaded + EXCLUDED.downloaded,
                    avg_upload_speed = ((traffic_stats_hourly.avg_upload_speed * traffic_stats_hourly.samples) + (EXCLUDED.avg_upload_speed * EXCLUDED.samples)) / (traffic_stats_hourly.samples + EXCLUDED.samples),
                    avg_download_speed = ((traffic_stats_hourly.avg_download_speed * traffic_stats_hourly.samples) + (EXCLUDED.avg_download_speed * EXCLUDED.samples)) / (traffic_stats_hourly.samples + EXCLUDED.samples),
                    samples = traffic_stats_hourly.samples + EXCLUDED.samples
                """
            else:  # sqlite
                upsert_sql = f"""
                    INSERT INTO traffic_stats_hourly 
                    (stat_datetime, downloader_id, uploaded, downloaded, avg_upload_speed, avg_download_speed, samples)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                    ON CONFLICT (stat_datetime, downloader_id) 
                    DO UPDATE SET
                    uploaded = traffic_stats_hourly.uploaded + excluded.uploaded,
                    downloaded = traffic_stats_hourly.downloaded + excluded.downloaded,
                    avg_upload_speed = ((traffic_stats_hourly.avg_upload_speed * traffic_stats_hourly.samples) + (excluded.avg_upload_speed * excluded.samples)) / (traffic_stats_hourly.samples + excluded.samples),
                    avg_download_speed = ((traffic_stats_hourly.avg_download_speed * traffic_stats_hourly.samples) + (excluded.avg_download_speed * excluded.samples)) / (traffic_stats_hourly.samples + excluded.samples),
                    samples = traffic_stats_hourly.samples + excluded.samples
                """

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
                 int(row["samples"] if isinstance(row, dict) else row[6]))
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
    """在启动时与下载客户端同步状态，建立后续增量计算的基线。"""
    logging.info("正在同步下载器状态以建立新的基线...")
    conn = db_manager._get_connection()
    cursor = db_manager._get_cursor(conn)
    ph = db_manager.get_placeholder()

    zero_point_records = []
    current_timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for client_config in config.get("downloaders", []):
        if not client_config.get("enabled"):
            continue
        client_id = client_config["id"]
        try:
            total_dl, total_ul = 0, 0
            if client_config["type"] == "qbittorrent":
                api_config = {
                    k: v
                    for k, v in client_config.items() if k not in [
                        "id", "name", "type", "enabled", "use_proxy",
                        "proxy_port"
                    ]
                }
                client = Client(**api_config)
                client.auth_log_in()
                # --- 修改：获取累计值 ---
                server_state = client.sync_maindata().get('server_state', {})
                total_dl = int(server_state.get('alltime_dl', 0))
                total_ul = int(server_state.get('alltime_ul', 0))
                # -------------------------
            elif client_config["type"] == "transmission":
                api_config = _prepare_api_config(client_config)
                client = TrClient(**api_config)
                stats = client.session_stats()
                total_dl = int(stats.cumulative_stats.downloaded_bytes)
                total_ul = int(stats.cumulative_stats.uploaded_bytes)

            # --- 修改：更新新的统一列 ---
            cursor.execute(
                f"UPDATE downloader_clients SET last_total_dl = {ph}, last_total_ul = {ph} WHERE id = {ph}",
                (total_dl, total_ul, client_id),
            )
            # ---------------------------

            zero_point_records.append(
                (current_timestamp_str, client_id, 0, 0, 0, 0))
            logging.info(f"客户端 '{client_config['name']}' 的基线已成功设置。")
        except Exception as e:
            logging.error(f"[{client_config['name']}] 启动时设置基线失败: {e}")

    if zero_point_records:
        try:
            sql_insert_zero = (
                f"INSERT INTO traffic_stats (stat_datetime, downloader_id, uploaded, downloaded, upload_speed, download_speed) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}) ON CONFLICT(stat_datetime, downloader_id) DO UPDATE SET uploaded = EXCLUDED.uploaded, downloaded = EXCLUDED.downloaded"
                if db_manager.db_type == "postgresql" else
                f"INSERT INTO traffic_stats (stat_datetime, downloader_id, uploaded, downloaded, upload_speed, download_speed) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}) ON DUPLICATE KEY UPDATE uploaded = VALUES(uploaded), downloaded = VALUES(downloaded)"
                if db_manager.db_type == "mysql" else
                f"INSERT INTO traffic_stats (stat_datetime, downloader_id, uploaded, downloaded, upload_speed, download_speed) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(stat_datetime, downloader_id) DO UPDATE SET uploaded = excluded.uploaded, downloaded = excluded.downloaded"
            )
            cursor.executemany(sql_insert_zero, zero_point_records)
            logging.info(
                f"已成功插入 {len(zero_point_records)} 条零点记录到 traffic_stats。")
        except Exception as e:
            logging.error(f"插入零点记录失败: {e}")
            conn.rollback()

    conn.commit()
    cursor.close()
    conn.close()
