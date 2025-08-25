# database.py

import logging
import sqlite3
import mysql.connector
import json
import os
from datetime import datetime

from config import SITES_DATA_FILE, config_manager
from qbittorrentapi import Client
from transmission_rpc import Client as TrClient

try:
    from services import _prepare_api_config
except ImportError:

    def _prepare_api_config(downloader_config):
        logging.warning(
            "Could not import '_prepare_api_config' from services. Using a placeholder."
        )
        api_config = {
            k: v
            for k, v in downloader_config.items()
            if k not in ["id", "name", "type", "enabled"]
        }
        return api_config


class DatabaseManager:
    """Handles all interactions with the configured database (MySQL or SQLite)."""

    def __init__(self, config):
        """
        Initializes the DatabaseManager based on the provided configuration.
        """
        self.db_type = config.get("db_type", "sqlite")
        if self.db_type == "mysql":
            self.mysql_config = config.get("mysql", {})
            logging.info("Database backend set to MySQL.")
        else:
            self.sqlite_path = config.get("path", "data/pt_stats.db")
            logging.info(f"Database backend set to SQLite. Path: {self.sqlite_path}")

    def _get_connection(self):
        """Returns a new database connection."""
        if self.db_type == "mysql":
            return mysql.connector.connect(**self.mysql_config, autocommit=False)
        else:
            return sqlite3.connect(self.sqlite_path, timeout=20)

    def _get_cursor(self, conn):
        """Returns a cursor from a connection."""
        if self.db_type == "mysql":
            return conn.cursor(dictionary=True, buffered=True)
        else:
            conn.row_factory = sqlite3.Row
            return conn.cursor()

    def get_placeholder(self):
        """Returns the correct parameter placeholder for the database type."""
        return "%s" if self.db_type == "mysql" else "?"

    def get_site_by_nickname(self, nickname):
        """通过站点昵称从数据库中获取站点的完整信息。"""
        conn = self._get_connection()
        cursor = self._get_cursor(conn)
        ph = self.get_placeholder()
        try:
            cursor.execute(f"SELECT * FROM sites WHERE nickname = {ph}", (nickname,))
            site_data = cursor.fetchone()
            return dict(site_data) if site_data else None
        except Exception as e:
            logging.error(f"通过昵称 '{nickname}' 获取站点信息时出错: {e}")
            return None
        finally:
            cursor.close()
            conn.close()

    def _add_missing_columns(self, conn, cursor):
        """
        [修正] 检查并向 sites 表添加缺失的列，实现自动化的数据库迁移。
        现在接收 conn 对象以创建新的游标。
        """
        logging.info("正在检查 'sites' 表的结构完整性...")
        columns_to_add = [("cookie", "TEXT", "TEXT"), ("passkey", "TEXT", "VARCHAR(255)")]

        if self.db_type == "mysql":
            db_name = self.mysql_config.get("database")
            # [关键修复] 直接从 conn 对象创建新的、非字典型游标
            meta_cursor = conn.cursor()
            meta_cursor.execute(
                "SELECT column_name FROM INFORMATION_SCHEMA.COLUMNS WHERE table_schema = %s AND table_name = 'sites'",
                (db_name,),
            )
            existing_columns = {row[0].lower() for row in meta_cursor.fetchall()}
            meta_cursor.close()

            for col_name, _, mysql_type in columns_to_add:
                if col_name.lower() not in existing_columns:
                    logging.info(f"在 MySQL 'sites' 表中发现缺失列: '{col_name}'。正在添加...")
                    # 使用主游标执行修改操作
                    cursor.execute(f"ALTER TABLE `sites` ADD COLUMN `{col_name}` {mysql_type}")
                    logging.info(f"成功添加列: '{col_name}'。")

        else:  # SQLite
            cursor.execute("PRAGMA table_info(sites)")
            existing_columns = {row["name"].lower() for row in cursor.fetchall()}

            for col_name, sqlite_type, _ in columns_to_add:
                if col_name.lower() not in existing_columns:
                    logging.info(f"在 SQLite 'sites' 表中发现缺失列: '{col_name}'。正在添加...")
                    cursor.execute(f"ALTER TABLE sites ADD COLUMN {col_name} {sqlite_type}")
                    logging.info(f"成功添加列: '{col_name}'。")

    def init_db(self):
        """
        [MODIFIED] 确保数据库表存在，自动迁移表结构，并根据 sites_data.json 同步站点数据。
        """
        conn = self._get_connection()
        cursor = self._get_cursor(conn)

        # --- 步骤 1: 确保所有表结构都已创建 ---
        logging.info("正在初始化并验证数据库表结构...")
        if self.db_type == "mysql":
            cursor.execute(
                """CREATE TABLE IF NOT EXISTS traffic_stats (
                    stat_datetime DATETIME NOT NULL,
                    downloader_id VARCHAR(36) NOT NULL,
                    uploaded BIGINT DEFAULT 0,
                    downloaded BIGINT DEFAULT 0,
                    upload_speed BIGINT DEFAULT 0,
                    download_speed BIGINT DEFAULT 0,
                    PRIMARY KEY (stat_datetime, downloader_id)
                ) ENGINE=InnoDB ROW_FORMAT=Dynamic"""
            )
            cursor.execute(
                """CREATE TABLE IF NOT EXISTS downloader_clients (
                    id VARCHAR(36) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    type VARCHAR(50) NOT NULL,
                    last_session_dl BIGINT NOT NULL DEFAULT 0,
                    last_session_ul BIGINT NOT NULL DEFAULT 0,
                    last_cumulative_dl BIGINT NOT NULL DEFAULT 0,
                    last_cumulative_ul BIGINT NOT NULL DEFAULT 0
                ) ENGINE=InnoDB ROW_FORMAT=Dynamic"""
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS torrents (
                    hash VARCHAR(40) PRIMARY KEY,
                    name TEXT NOT NULL,
                    save_path TEXT,
                    size BIGINT,
                    progress FLOAT,
                    state VARCHAR(50),
                    sites VARCHAR(255),
                    `group` VARCHAR(255),
                    details TEXT,
                    last_seen DATETIME NOT NULL
                ) ENGINE=InnoDB ROW_FORMAT=Dynamic
            """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS torrent_upload_stats (
                    hash VARCHAR(40) NOT NULL,
                    downloader_id VARCHAR(36) NOT NULL,
                    uploaded BIGINT DEFAULT 0,
                    PRIMARY KEY (hash, downloader_id)
                ) ENGINE=InnoDB ROW_FORMAT=Dynamic
            """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS `sites` (
                    `id` mediumint NOT NULL AUTO_INCREMENT,
                    `site` varchar(255) UNIQUE DEFAULT NULL,
                    `nickname` varchar(255) DEFAULT NULL,
                    `base_url` varchar(255) DEFAULT NULL,
                    `special_tracker_domain` varchar(255) DEFAULT NULL,
                    `group` varchar(255) DEFAULT NULL,
                    PRIMARY KEY (`id`)
                ) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
            """
            )
        else:  # SQLite
            cursor.execute(
                """CREATE TABLE IF NOT EXISTS traffic_stats (
                    stat_datetime TEXT NOT NULL,
                    downloader_id TEXT NOT NULL,
                    uploaded INTEGER DEFAULT 0,
                    downloaded INTEGER DEFAULT 0,
                    upload_speed INTEGER DEFAULT 0,
                    download_speed INTEGER DEFAULT 0,
                    PRIMARY KEY (stat_datetime, downloader_id)
                )"""
            )
            cursor.execute(
                """CREATE TABLE IF NOT EXISTS downloader_clients (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    last_session_dl INTEGER NOT NULL DEFAULT 0,
                    last_session_ul INTEGER NOT NULL DEFAULT 0,
                    last_cumulative_dl INTEGER NOT NULL DEFAULT 0,
                    last_cumulative_ul INTEGER NOT NULL DEFAULT 0
                )"""
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS torrents (
                    hash TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    save_path TEXT,
                    size INTEGER,
                    progress REAL,
                    state TEXT,
                    sites TEXT,
                    `group` TEXT,
                    details TEXT,
                    last_seen TEXT NOT NULL
                )
            """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS torrent_upload_stats (
                    hash TEXT NOT NULL,
                    downloader_id TEXT NOT NULL,
                    uploaded INTEGER DEFAULT 0,
                    PRIMARY KEY (hash, downloader_id)
                )
            """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS sites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    site TEXT UNIQUE,
                    nickname TEXT,
                    base_url TEXT,
                    special_tracker_domain TEXT,
                    `group` TEXT
                )
            """
            )

        logging.info("基本表结构验证完成。")
        conn.commit()

        # --- 步骤 2: [新逻辑] 自动迁移数据库，添加缺失的列 ---
        # [关键修复] 将 conn 对象传递进去
        self._add_missing_columns(conn, cursor)
        conn.commit()

        # --- 步骤 3: 同步 sites_data.json 到数据库 ---
        try:
            if not os.path.exists(SITES_DATA_FILE):
                logging.warning(f"{SITES_DATA_FILE} 未找到，跳过站点数据同步。")
            else:
                logging.info(f"正在从 {SITES_DATA_FILE} 同步站点数据...")

                with open(SITES_DATA_FILE, "r", encoding="utf-8") as f:
                    sites_from_json = json.load(f)

                if not sites_from_json:
                    logging.info("sites_data.json 为空，无需同步。")
                else:
                    cursor.execute(
                        "SELECT site, nickname, base_url, special_tracker_domain, `group`, cookie, passkey FROM sites"
                    )
                    sites_in_db = {row["site"]: row for row in cursor.fetchall()}
                    logging.info(f"数据库中目前存在 {len(sites_in_db)} 条站点记录。")

                    sites_to_insert = []
                    sites_to_update = []

                    for site_data in sites_from_json:
                        site_name = site_data.get("site")
                        if not site_name:
                            continue

                        db_entry = sites_in_db.get(site_name)
                        json_tuple = (
                            site_data.get("site"),
                            site_data.get("nickname"),
                            site_data.get("base_url"),
                            site_data.get("special_tracker_domain"),
                            site_data.get("group"),
                            site_data.get("cookie"),
                            site_data.get("passkey"),
                        )

                        if db_entry is None:
                            sites_to_insert.append(json_tuple)
                        else:
                            update_params = (
                                json_tuple[1],  # nickname
                                json_tuple[2],  # base_url
                                json_tuple[3],  # special_tracker_domain
                                json_tuple[4],  # group
                                json_tuple[5],  # cookie
                                json_tuple[6],  # passkey
                                json_tuple[0],  # where site = ?
                            )
                            sites_to_update.append(update_params)

                    ph = self.get_placeholder()

                    if sites_to_insert:
                        logging.info(f"发现 {len(sites_to_insert)} 个新站点，将插入数据库。")
                        sql_insert = f"INSERT INTO sites (site, nickname, base_url, special_tracker_domain, `group`, cookie, passkey) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})"
                        cursor.executemany(sql_insert, sites_to_insert)

                    if sites_to_update:
                        logging.info(f"发现 {len(sites_to_update)} 个已有站点，将更新其信息。")
                        sql_update = f"UPDATE sites SET nickname = {ph}, base_url = {ph}, special_tracker_domain = {ph}, `group` = {ph}, cookie = {ph}, passkey = {ph} WHERE site = {ph}"
                        cursor.executemany(sql_update, sites_to_update)

                    if not sites_to_insert and not sites_to_update:
                        logging.info("站点数据已是最新，无需改动。")

                    conn.commit()
                    logging.info("站点数据同步完成。")

        except Exception as e:
            logging.error(f"同步站点数据时发生错误: {e}", exc_info=True)
            conn.rollback()

        # --- 步骤 4: 同步下载器配置 (逻辑保持不变) ---
        self._sync_downloaders_from_config(cursor)
        conn.commit()

        cursor.close()
        conn.close()
        logging.info("数据库初始化和同步流程完成。")

    def _sync_downloaders_from_config(self, cursor):
        """从配置文件同步下载器列表到 downloader_clients 表。"""
        config = config_manager.get()
        downloaders = config.get("downloaders", [])
        if not downloaders:
            return

        db_ids = set()
        cursor.execute("SELECT id FROM downloader_clients")
        for row in cursor.fetchall():
            db_ids.add(row["id"])

        config_ids = {d["id"] for d in downloaders}

        for d in downloaders:
            if d["id"] in db_ids:
                sql = (
                    "UPDATE downloader_clients SET name = %s, type = %s WHERE id = %s"
                    if self.db_type == "mysql"
                    else "UPDATE downloader_clients SET name = ?, type = ? WHERE id = ?"
                )
                cursor.execute(sql, (d["name"], d["type"], d["id"]))
            else:
                sql = (
                    "INSERT INTO downloader_clients (id, name, type) VALUES (%s, %s, %s)"
                    if self.db_type == "mysql"
                    else "INSERT INTO downloader_clients (id, name, type) VALUES (?, ?, ?)"
                )
                cursor.execute(sql, (d["id"], d["name"], d["type"]))

        ids_to_delete = db_ids - config_ids
        if ids_to_delete:
            placeholders = ", ".join([self.get_placeholder()] * len(ids_to_delete))
            sql = f"DELETE FROM downloader_clients WHERE id IN ({placeholders})"
            cursor.execute(sql, tuple(ids_to_delete))
            logging.info(
                f"Removed {len(ids_to_delete)} downloader(s) from DB that are no longer in config."
            )


def reconcile_historical_data(db_manager, config):
    """
    在每次启动时，与下载客户端同步状态，将当前状态设为后续增量计算的“零点基线”，
    并立即在 traffic_stats 表中为每个客户端写入一条初始的零值记录。
    这确保所有统计都从应用启动这一刻的零开始。
    """
    logging.info(
        "Synchronizing downloader states to establish a new baseline and writing initial zero-point records..."
    )
    conn = db_manager._get_connection()
    cursor = db_manager._get_cursor(conn)
    ph = db_manager.get_placeholder()

    zero_point_records = []
    current_timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    downloaders = config.get("downloaders", [])
    for client_config in downloaders:
        if not client_config.get("enabled"):
            continue

        client_id = client_config["id"]
        client_type = client_config["type"]

        try:
            if client_type == "qbittorrent":
                api_config = {
                    k: v
                    for k, v in client_config.items()
                    if k not in ["id", "name", "type", "enabled"]
                }
                client = Client(**api_config)
                client.auth_log_in()
                info = client.transfer_info()
                current_session_dl = int(getattr(info, "dl_info_data", 0))
                current_session_ul = int(getattr(info, "up_info_data", 0))

                sql = f"UPDATE downloader_clients SET last_session_dl = {ph}, last_session_ul = {ph} WHERE id = {ph}"
                cursor.execute(sql, (current_session_dl, current_session_ul, client_id))
                logging.info(
                    f"qBittorrent client '{client_config['name']}' baseline set for future calculations."
                )

            elif client_type == "transmission":
                api_config = _prepare_api_config(client_config)
                client = TrClient(**api_config)
                stats = client.session_stats()
                current_cumulative_dl = int(stats.cumulative_stats.downloaded_bytes)
                current_cumulative_ul = int(stats.cumulative_stats.uploaded_bytes)

                sql_update_baseline = f"UPDATE downloader_clients SET last_cumulative_dl = {ph}, last_cumulative_ul = {ph} WHERE id = {ph}"
                cursor.execute(
                    sql_update_baseline, (current_cumulative_dl, current_cumulative_ul, client_id)
                )
                logging.info(
                    f"Transmission client '{client_config['name']}' baseline set for future calculations."
                )

            zero_point_records.append((current_timestamp_str, client_id, 0, 0, 0, 0))

        except Exception as e:
            logging.error(f"[{client_config['name']}] Failed to set baseline at startup: {e}")

    if zero_point_records:
        try:
            if db_manager.db_type == "mysql":
                sql_insert_zero = """
                    INSERT INTO traffic_stats (stat_datetime, downloader_id, uploaded, downloaded, upload_speed, download_speed) 
                    VALUES (%s, %s, %s, %s, %s, %s) 
                    ON DUPLICATE KEY UPDATE uploaded = VALUES(uploaded), downloaded = VALUES(downloaded)
                """
            else:  # SQLite
                sql_insert_zero = """
                    INSERT INTO traffic_stats (stat_datetime, downloader_id, uploaded, downloaded, upload_speed, download_speed) 
                    VALUES (?, ?, ?, ?, ?, ?) 
                    ON CONFLICT(stat_datetime, downloader_id) DO UPDATE SET uploaded = excluded.uploaded, downloaded = excluded.downloaded
                """
            cursor.executemany(sql_insert_zero, zero_point_records)
            logging.info(
                f"Successfully inserted {len(zero_point_records)} zero-point records into traffic_stats."
            )
        except Exception as e:
            logging.error(f"Failed to insert zero-point records: {e}")
            conn.rollback()

    conn.commit()
    cursor.close()
    conn.close()
    logging.info("All client baselines synchronized and initial zero-points recorded.")
