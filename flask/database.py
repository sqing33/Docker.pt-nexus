# database.py

import logging
import sqlite3
import mysql.connector
import json
import os

from config import SITES_DATA_FILE, config_manager
from qbittorrentapi import Client
from transmission_rpc import Client as TrClient

DB_FILE = 'pt_stats.db'


class DatabaseManager:
    """Handles all interactions with the configured database (MySQL or SQLite)."""

    def __init__(self, config):
        self.db_type = config.get('db_type', 'sqlite')
        if self.db_type == 'mysql':
            self.mysql_config = config.get('mysql', {})
            logging.info("Database backend set to MySQL.")
        else:
            self.sqlite_path = DB_FILE
            logging.info("Database backend set to SQLite.")

    def _get_connection(self):
        """Returns a new database connection."""
        if self.db_type == 'mysql':
            return mysql.connector.connect(**self.mysql_config,
                                           autocommit=False)
        else:
            # 增加 timeout 参数以减少 "database is locked" 错误
            return sqlite3.connect(self.sqlite_path, timeout=20)

    def _get_cursor(self, conn):
        """Returns a cursor from a connection."""
        if self.db_type == 'mysql':
            return conn.cursor(dictionary=True)
        else:
            conn.row_factory = sqlite3.Row
            return conn.cursor()

    def get_placeholder(self):
        """Returns the correct parameter placeholder for the database type."""
        return '%s' if self.db_type == 'mysql' else '?'

    def init_db(self):
        """确保所有必需的数据库表都存在，并根据需要填充站点表。"""
        conn = self._get_connection()
        # [FIXED] 始终使用 _get_cursor 来确保 row_factory 被设置
        cursor = self._get_cursor(conn)

        if self.db_type == 'mysql':
            # 流量统计表 (新)
            cursor.execute('''CREATE TABLE IF NOT EXISTS traffic_stats (
                    stat_datetime DATETIME NOT NULL,
                    downloader_id VARCHAR(36) NOT NULL,
                    uploaded BIGINT DEFAULT 0,
                    downloaded BIGINT DEFAULT 0,
                    upload_speed BIGINT DEFAULT 0,
                    download_speed BIGINT DEFAULT 0,
                    PRIMARY KEY (stat_datetime, downloader_id)
                ) ENGINE=InnoDB ROW_FORMAT=Dynamic''')
            # 下载器客户端状态表 (新)
            cursor.execute('''CREATE TABLE IF NOT EXISTS downloader_clients (
                    id VARCHAR(36) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    type VARCHAR(50) NOT NULL,
                    last_session_dl BIGINT NOT NULL DEFAULT 0,
                    last_session_ul BIGINT NOT NULL DEFAULT 0,
                    last_cumulative_dl BIGINT NOT NULL DEFAULT 0,
                    last_cumulative_ul BIGINT NOT NULL DEFAULT 0
                ) ENGINE=InnoDB ROW_FORMAT=Dynamic''')
            # 种子主信息表 (修改)
            cursor.execute('''
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
            ''')
            # 种子上传量统计表 (新)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS torrent_upload_stats (
                    hash VARCHAR(40) NOT NULL,
                    downloader_id VARCHAR(36) NOT NULL,
                    uploaded BIGINT DEFAULT 0,
                    PRIMARY KEY (hash, downloader_id)
                ) ENGINE=InnoDB ROW_FORMAT=Dynamic
            ''')
            # 站点信息表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS `sites` (
                    `id` mediumint NOT NULL AUTO_INCREMENT,
                    `site` varchar(255) DEFAULT NULL,
                    `nickname` varchar(255) DEFAULT NULL,
                    `base_url` varchar(255) DEFAULT NULL,
                    `special_tracker_domain` varchar(255) DEFAULT NULL,
                    `group` varchar(255) DEFAULT NULL,
                    PRIMARY KEY (`id`)
                ) ENGINE=InnoDB ROW_FORMAT=DYNAMIC
            ''')
        else:  # SQLite
            cursor.execute('''CREATE TABLE IF NOT EXISTS traffic_stats (
                    stat_datetime TEXT NOT NULL,
                    downloader_id TEXT NOT NULL,
                    uploaded INTEGER DEFAULT 0,
                    downloaded INTEGER DEFAULT 0,
                    upload_speed INTEGER DEFAULT 0,
                    download_speed INTEGER DEFAULT 0,
                    PRIMARY KEY (stat_datetime, downloader_id)
                )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS downloader_clients (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    last_session_dl INTEGER NOT NULL DEFAULT 0,
                    last_session_ul INTEGER NOT NULL DEFAULT 0,
                    last_cumulative_dl INTEGER NOT NULL DEFAULT 0,
                    last_cumulative_ul INTEGER NOT NULL DEFAULT 0
                )''')
            cursor.execute('''
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
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS torrent_upload_stats (
                    hash TEXT NOT NULL,
                    downloader_id TEXT NOT NULL,
                    uploaded INTEGER DEFAULT 0,
                    PRIMARY KEY (hash, downloader_id)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    site TEXT,
                    nickname TEXT,
                    base_url TEXT,
                    special_tracker_domain TEXT,
                    `group` TEXT
                )
            ''')

        # 迁移旧数据
        self._migrate_legacy_data(cursor)

        conn.commit()

        # 填充站点表逻辑 (不变)
        try:
            cursor.execute("SELECT COUNT(*) FROM sites")
            result = cursor.fetchone()
            # 适配 sqlite3.Row 和 dict
            count = result[0] if isinstance(
                result, (tuple, sqlite3.Row)) else result['COUNT(*)']

            if count == 0 and os.path.exists(SITES_DATA_FILE):
                logging.info(
                    "Sites table is empty. Seeding data from sites_data.json..."
                )
                with open(SITES_DATA_FILE, 'r', encoding='utf-8') as f:
                    sites_data = json.load(f)
                if not sites_data:
                    logging.warning(
                        "sites_data.json is empty. Skipping seeding.")
                else:
                    ph = self.get_placeholder()
                    sql = f'''INSERT INTO sites (site, nickname, base_url, special_tracker_domain, `group`) VALUES ({ph}, {ph}, {ph}, {ph}, {ph})'''
                    params_to_insert = [
                        (s.get('site'), s.get('nickname'), s.get('base_url'),
                         s.get('special_tracker_domain'), s.get('group'))
                        for s in sites_data
                    ]
                    cursor.executemany(sql, params_to_insert)
                    conn.commit()
                    logging.info(
                        f"Successfully inserted {len(params_to_insert)} records into the sites table."
                    )
            elif count > 0:
                logging.info(
                    "Sites table already contains data. Skipping seeding.")
        except Exception as e:
            logging.error(
                f"An error occurred while seeding the sites table: {e}",
                exc_info=True)
            conn.rollback()

        # 同步配置文件中的下载器到数据库
        self._sync_downloaders_from_config(cursor)
        conn.commit()

        cursor.close()
        conn.close()
        logging.info("Database schemas verified.")

    def _sync_downloaders_from_config(self, cursor):
        """从配置文件同步下载器列表到 downloader_clients 表。"""
        config = config_manager.get()
        downloaders = config.get('downloaders', [])
        if not downloaders:
            return

        db_ids = set()
        cursor.execute("SELECT id FROM downloader_clients")
        for row in cursor.fetchall():
            db_ids.add(row['id'])

        config_ids = {d['id'] for d in downloaders}

        # 添加或更新
        for d in downloaders:
            if d['id'] in db_ids:
                # 更新名称和类型
                sql = "UPDATE downloader_clients SET name = %s, type = %s WHERE id = %s" if self.db_type == 'mysql' else "UPDATE downloader_clients SET name = ?, type = ? WHERE id = ?"
                cursor.execute(sql, (d['name'], d['type'], d['id']))
            else:
                # 插入新的
                sql = 'INSERT INTO downloader_clients (id, name, type) VALUES (%s, %s, %s)' if self.db_type == 'mysql' else 'INSERT INTO downloader_clients (id, name, type) VALUES (?, ?, ?)'
                cursor.execute(sql, (d['id'], d['name'], d['type']))

        # 删除不存在于配置文件的
        ids_to_delete = db_ids - config_ids
        if ids_to_delete:
            placeholders = ', '.join([self.get_placeholder()] *
                                     len(ids_to_delete))
            sql = f"DELETE FROM downloader_clients WHERE id IN ({placeholders})"
            cursor.execute(sql, tuple(ids_to_delete))
            logging.info(
                f"Removed {len(ids_to_delete)} downloader(s) from DB that are no longer in config."
            )

    def _migrate_legacy_data(self, cursor):
        """检查并迁移旧的数据库表结构数据到新结构。"""
        try:
            # 检查旧的 downloader_state 表是否存在
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='downloader_state'"
            ) if self.db_type != 'mysql' else cursor.execute(
                "SHOW TABLES LIKE 'downloader_state'")
            if not cursor.fetchone():
                return  # 不是旧版本，无需迁移

            logging.warning(
                "Legacy tables detected. Attempting to migrate data to the new schema. This is a one-time operation."
            )

            config = config_manager.get()
            qb_downloader = next((d for d in config.get('downloaders', [])
                                  if d.get('type') == 'qbittorrent'), None)
            tr_downloader = next((d for d in config.get('downloaders', [])
                                  if d.get('type') == 'transmission'), None)

            # 1. 迁移 downloader_state
            if qb_downloader:
                cursor.execute(
                    "SELECT * FROM downloader_state WHERE name = 'qbittorrent'"
                )
                row = cursor.fetchone()
                if row:
                    sql = "INSERT INTO downloader_clients (id, name, type, last_session_dl, last_session_ul) VALUES (%s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE last_session_dl=VALUES(last_session_dl), last_session_ul=VALUES(last_session_ul)" if self.db_type == 'mysql' else "INSERT INTO downloader_clients (id, name, type, last_session_dl, last_session_ul) VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET last_session_dl=excluded.last_session_dl, last_session_ul=excluded.last_session_ul"
                    cursor.execute(sql,
                                   (qb_downloader['id'], qb_downloader['name'],
                                    'qbittorrent', row['last_session_dl'],
                                    row['last_session_ul']))

            if tr_downloader:
                cursor.execute(
                    "SELECT * FROM downloader_state WHERE name = 'transmission'"
                )
                row = cursor.fetchone()
                if row:
                    sql = "INSERT INTO downloader_clients (id, name, type, last_cumulative_dl, last_cumulative_ul) VALUES (%s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE last_cumulative_dl=VALUES(last_cumulative_dl), last_cumulative_ul=VALUES(last_cumulative_ul)" if self.db_type == 'mysql' else "INSERT INTO downloader_clients (id, name, type, last_cumulative_dl, last_cumulative_ul) VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET last_cumulative_dl=excluded.last_cumulative_dl, last_cumulative_ul=excluded.last_cumulative_ul"
                    cursor.execute(sql,
                                   (tr_downloader['id'], tr_downloader['name'],
                                    'transmission', row['last_cumulative_dl'],
                                    row['last_cumulative_ul']))

            # 2. 迁移 torrents 表中的上传量
            if qb_downloader:
                cursor.execute(
                    "SELECT hash, qb_uploaded FROM torrents WHERE qb_uploaded > 0"
                )
                params = [(row['hash'], qb_downloader['id'],
                           row['qb_uploaded']) for row in cursor.fetchall()]
                if params:
                    sql = "INSERT INTO torrent_upload_stats (hash, downloader_id, uploaded) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE uploaded=VALUES(uploaded)" if self.db_type == 'mysql' else "INSERT INTO torrent_upload_stats (hash, downloader_id, uploaded) VALUES (?, ?, ?) ON CONFLICT(hash, downloader_id) DO UPDATE SET uploaded=excluded.uploaded"
                    cursor.executemany(sql, params)

            if tr_downloader:
                cursor.execute(
                    "SELECT hash, tr_uploaded FROM torrents WHERE tr_uploaded > 0"
                )
                params = [(row['hash'], tr_downloader['id'],
                           row['tr_uploaded']) for row in cursor.fetchall()]
                if params:
                    sql = "INSERT INTO torrent_upload_stats (hash, downloader_id, uploaded) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE uploaded=VALUES(uploaded)" if self.db_type == 'mysql' else "INSERT INTO torrent_upload_stats (hash, downloader_id, uploaded) VALUES (?, ?, ?) ON CONFLICT(hash, downloader_id) DO UPDATE SET uploaded=excluded.uploaded"
                    cursor.executemany(sql, params)

            # 3. 删除旧表和旧列 (仅限SQLite，MySQL需要手动ALTER)
            if self.db_type != 'mysql':
                logging.info(
                    "Dropping legacy 'downloader_state' table for SQLite.")
                cursor.execute("DROP TABLE IF EXISTS downloader_state")
                logging.info(
                    "Recreating 'torrents' table to remove legacy columns for SQLite."
                )
                cursor.execute("ALTER TABLE torrents RENAME TO torrents_old")
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS torrents (
                        hash TEXT PRIMARY KEY, name TEXT NOT NULL, save_path TEXT, size INTEGER, progress REAL,
                        state TEXT, sites TEXT, `group` TEXT, details TEXT, last_seen TEXT NOT NULL
                    )
                ''')
                cursor.execute('''
                    INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, `group`, details, last_seen)
                    SELECT hash, name, save_path, size, progress, state, sites, `group`, details, last_seen FROM torrents_old
                ''')
                cursor.execute("DROP TABLE torrents_old")
            else:
                logging.warning(
                    "For MySQL, please manually drop the 'downloader_state' table and the 'qb_uploaded', 'tr_uploaded' columns from the 'torrents' table after migration is confirmed."
                )

            logging.info("Data migration completed successfully.")
        except Exception as e:
            # 如果迁移失败，可能是因为列/表不存在，这不是一个严重错误
            logging.debug(
                f"Could not perform legacy data migration. This is expected on new installs. Details: {e}"
            )
            pass  # 忽略错误，因为这很可能意味着它是一个新的安装


def reconcile_historical_data(db_manager, config):
    """
    在每次启动时，强制与下载客户端同步当前状态，以防止重启后出现数据峰值。
    不再创建创世纪录，因为新的增量逻辑不再需要它。
    """
    logging.info("Starting downloader state synchronization...")
    conn = db_manager._get_connection()
    cursor = db_manager._get_cursor(conn)
    is_mysql = db_manager.db_type == 'mysql'

    downloaders = config.get('downloaders', [])
    for client_config in downloaders:
        if not client_config.get('enabled'):
            continue

        client_id = client_config['id']
        client_type = client_config['type']

        # 剥离我们自己添加的元数据字段
        api_config = {
            k: v
            for k, v in client_config.items()
            if k not in ['id', 'name', 'type', 'enabled']
        }

        if client_type == 'qbittorrent':
            try:
                client = Client(**api_config)
                client.auth_log_in()
                info = client.transfer_info()
                current_session_dl = int(getattr(info, 'dl_info_data', 0))
                current_session_ul = int(getattr(info, 'up_info_data', 0))

                sql = "UPDATE downloader_clients SET last_session_dl = %s, last_session_ul = %s WHERE id = %s" if is_mysql else "UPDATE downloader_clients SET last_session_dl = ?, last_session_ul = ? WHERE id = ?"
                cursor.execute(
                    sql, (current_session_dl, current_session_ul, client_id))
                logging.info(
                    f"qBittorrent client '{client_config['name']}' state synchronized: last_session_dl set to {current_session_dl}, last_session_ul set to {current_session_ul}."
                )
            except Exception as e:
                logging.error(
                    f"[{client_config['name']}] Failed to synchronize state at startup: {e}"
                )

        elif client_type == 'transmission':
            try:
                client = TrClient(**api_config)
                stats = client.session_stats()
                current_cumulative_dl = int(
                    stats.cumulative_stats.downloaded_bytes)
                current_cumulative_ul = int(
                    stats.cumulative_stats.uploaded_bytes)

                sql = "UPDATE downloader_clients SET last_cumulative_dl = %s, last_cumulative_ul = %s WHERE id = %s" if is_mysql else "UPDATE downloader_clients SET last_cumulative_dl = ?, last_cumulative_ul = ? WHERE id = ?"
                cursor.execute(
                    sql,
                    (current_cumulative_dl, current_cumulative_ul, client_id))
                logging.info(
                    f"Transmission client '{client_config['name']}' state synchronized: last_cumulative_dl set to {current_cumulative_dl}, last_cumulative_ul set to {current_cumulative_ul}."
                )
            except Exception as e:
                logging.error(
                    f"[{client_config['name']}] Failed to synchronize state at startup: {e}"
                )

    conn.commit()
    cursor.close()
    conn.close()
    logging.info("State synchronization finished.")
