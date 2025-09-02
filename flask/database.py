# database.py

import logging
import sqlite3
import mysql.connector
import json
import os
from datetime import datetime

# 从项目根目录导入模块
from config import SITES_DATA_FILE, config_manager

# 外部库导入
from qbittorrentapi import Client
from transmission_rpc import Client as TrClient

# --- [重要修正] ---
# 直接从 core.services 导入正确的函数，移除了会导致错误的 try-except 占位符
from core.services import _prepare_api_config


class DatabaseManager:
    """处理与配置的数据库（MySQL 或 SQLite）的所有交互。"""

    def __init__(self, config):
        """根据提供的配置初始化 DatabaseManager。"""
        self.db_type = config.get("db_type", "sqlite")
        if self.db_type == "mysql":
            self.mysql_config = config.get("mysql", {})
            logging.info("数据库后端设置为 MySQL。")
        else:
            self.sqlite_path = config.get("path", "data/pt_stats.db")
            logging.info(f"数据库后端设置为 SQLite。路径: {self.sqlite_path}")

    def _get_connection(self):
        """返回一个新的数据库连接。"""
        if self.db_type == "mysql":
            return mysql.connector.connect(**self.mysql_config,
                                           autocommit=False)
        else:
            return sqlite3.connect(self.sqlite_path, timeout=20)

    def _get_cursor(self, conn):
        """从连接中返回一个游标。"""
        if self.db_type == "mysql":
            return conn.cursor(dictionary=True, buffered=True)
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

    def _migrate_torrents_table(self, conn, cursor):
        """检查并向 torrents 表添加 downloader_id 列。"""
        table_name = 'torrents'
        if self.db_type == 'mysql':
            cursor.execute(f"DESCRIBE {table_name}")
            columns = {row['Field'].lower() for row in cursor.fetchall()}
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

    def get_placeholder(self):
        """返回数据库类型对应的正确参数占位符。"""
        return "%s" if self.db_type == "mysql" else "?"

    def get_site_by_nickname(self, nickname):
        """通过站点昵称从数据库中获取站点的完整信息。"""
        conn = self._get_connection()
        cursor = self._get_cursor(conn)
        try:
            cursor.execute(
                f"SELECT * FROM sites WHERE nickname = {self.get_placeholder()}",
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
            sql = f"INSERT INTO sites (site, nickname, base_url, special_tracker_domain, `group`, cookie, passkey) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})"
            params = (
                site_data.get("site"),
                site_data.get("nickname"),
                site_data.get("base_url"),
                site_data.get("special_tracker_domain"),
                site_data.get("group"),
                site_data.get("cookie"),
                site_data.get("passkey"),
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
            sql = f"UPDATE sites SET nickname = {ph}, base_url = {ph}, special_tracker_domain = {ph}, `group` = {ph}, cookie = {ph}, passkey = {ph} WHERE id = {ph}"
            params = (
                site_data.get("nickname"),
                site_data.get("base_url"),
                site_data.get("special_tracker_domain"),
                site_data.get("group"),
                site_data.get("cookie"),
                site_data.get("passkey"),
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
        columns_to_add = [("cookie", "TEXT", "TEXT"),
                          ("passkey", "TEXT", "VARCHAR(255)"),
                          ("migration", "INTEGER DEFAULT 0",
                           "TINYINT DEFAULT 0")]

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
                        f"ALTER TABLE `sites` ADD COLUMN `{col_name}` {mysql_type} NOT NULL"
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

    def init_db(self):
        """确保数据库表存在，并根据 sites_data.json 同步站点数据。"""
        conn = self._get_connection()
        cursor = self._get_cursor(conn)

        logging.info("正在初始化并验证数据库表结构...")
        # 表创建逻辑 (MySQL) - [此部分保持不变]
        if self.db_type == "mysql":
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS traffic_stats (stat_datetime DATETIME NOT NULL, downloader_id VARCHAR(36) NOT NULL, uploaded BIGINT DEFAULT 0, downloaded BIGINT DEFAULT 0, upload_speed BIGINT DEFAULT 0, download_speed BIGINT DEFAULT 0, PRIMARY KEY (stat_datetime, downloader_id)) ENGINE=InnoDB ROW_FORMAT=Dynamic"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS downloader_clients (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255) NOT NULL, type VARCHAR(50) NOT NULL, last_total_dl BIGINT NOT NULL DEFAULT 0, last_total_ul BIGINT NOT NULL DEFAULT 0) ENGINE=InnoDB ROW_FORMAT=Dynamic"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS torrents (hash VARCHAR(40) PRIMARY KEY, name TEXT NOT NULL, save_path TEXT, size BIGINT, progress FLOAT, state VARCHAR(50), sites VARCHAR(255), `group` VARCHAR(255), details TEXT, downloader_id VARCHAR(36) NULL, last_seen DATETIME NOT NULL) ENGINE=InnoDB ROW_FORMAT=Dynamic"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS torrent_upload_stats (hash VARCHAR(40) NOT NULL, downloader_id VARCHAR(36) NOT NULL, uploaded BIGINT DEFAULT 0, PRIMARY KEY (hash, downloader_id)) ENGINE=InnoDB ROW_FORMAT=Dynamic"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS `sites` (`id` mediumint NOT NULL AUTO_INCREMENT, `site` varchar(255) UNIQUE DEFAULT NULL, `nickname` varchar(255) DEFAULT NULL, `base_url` varchar(255) DEFAULT NULL, `special_tracker_domain` varchar(255) DEFAULT NULL, `group` varchar(255) DEFAULT NULL, `cookie` TEXT DEFAULT NULL,`passkey` varchar(255) DEFAULT NULL,`migration` int(11) NOT NULL DEFAULT 1, PRIMARY KEY (`id`)) ENGINE=InnoDB ROW_FORMAT=DYNAMIC"
            )
        # 表创建逻辑 (SQLite) - [此部分保持不变]
        else:
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS traffic_stats (stat_datetime TEXT NOT NULL, downloader_id TEXT NOT NULL, uploaded INTEGER DEFAULT 0, downloaded INTEGER DEFAULT 0, upload_speed INTEGER DEFAULT 0, download_speed INTEGER DEFAULT 0, PRIMARY KEY (stat_datetime, downloader_id))"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS downloader_clients (id TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL, last_total_dl INTEGER NOT NULL DEFAULT 0, last_total_ul INTEGER NOT NULL DEFAULT 0)"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS torrents (hash TEXT PRIMARY KEY, name TEXT NOT NULL, save_path TEXT, size INTEGER, progress REAL, state TEXT, sites TEXT, `group` TEXT, details TEXT, downloader_id TEXT, last_seen TEXT NOT NULL)"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS torrent_upload_stats (hash TEXT NOT NULL, downloader_id TEXT NOT NULL, uploaded INTEGER DEFAULT 0, PRIMARY KEY (hash, downloader_id))"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS sites (id INTEGER PRIMARY KEY AUTOINCREMENT, site TEXT UNIQUE, nickname TEXT, base_url TEXT, special_tracker_domain TEXT, `group` TEXT, cookie TEXT, passkey TEXT, migration INTEGER NOT NULL DEFAULT 1)"
            )

        conn.commit()
        self._migrate_torrents_table(conn, cursor)
        self._run_schema_migrations(conn, cursor)
        self._add_missing_columns(conn, cursor)
        conn.commit()

        if os.path.exists(SITES_DATA_FILE):
            logging.info(f"正在从 {SITES_DATA_FILE} 检查并同步站点...")
            with open(SITES_DATA_FILE, "r", encoding="utf-8") as f:
                sites_from_json = json.load(f)

            # --- 步骤 1: 插入在数据库中不存在的新站点 (逻辑不变) ---
            cursor.execute("SELECT site FROM sites")
            sites_in_db = {row["site"] for row in cursor.fetchall()}
            sites_to_insert = [
                tuple(
                    s.get(k) for k in [
                        "site", "nickname", "base_url",
                        "special_tracker_domain", "group", "migration"
                    ]) for s in sites_from_json
                if s.get("site") not in sites_in_db
            ]

            if sites_to_insert:
                logging.info(
                    f"发现 {len(sites_to_insert)} 个新站点，将从 {SITES_DATA_FILE} 插入数据库。"
                )
                ph = self.get_placeholder()
                sql_insert = f"INSERT INTO sites (site, nickname, base_url, special_tracker_domain, `group`, migration) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph})"
                cursor.executemany(sql_insert, sites_to_insert)

            # --- 步骤 2: [新增逻辑] 更新所有站点的 migration 值 ---
            # 准备要更新的数据：(migration_value, site_domain)
            migration_data_to_update = [(s.get("migration", 1), s.get("site"))
                                        for s in sites_from_json
                                        if s.get("site")]

            if migration_data_to_update:
                logging.info(
                    f"正在根据 {SITES_DATA_FILE} 同步 {len(migration_data_to_update)} 个站点的 migration 值..."
                )
                ph = self.get_placeholder()
                # SQL语句的 WHERE site = ? 会确保只更新数据库中已存在的站点
                sql_update = f"UPDATE sites SET migration = {ph} WHERE site = {ph}"
                cursor.executemany(sql_update, migration_data_to_update)

            # 一次性提交所有更改
            conn.commit()

        self._sync_downloaders_from_config(cursor)
        conn.commit()
        cursor.close()
        conn.close()
        logging.info("数据库初始化和同步流程完成。")

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
                cursor.execute(
                    f"INSERT INTO downloader_clients (id, name, type) VALUES ({ph}, {ph}, {ph})",
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
                    for k, v in client_config.items()
                    if k not in ["id", "name", "type", "enabled"]
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
