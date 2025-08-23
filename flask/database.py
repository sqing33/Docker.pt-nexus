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
            if k not in ['id', 'name', 'type', 'enabled']
        }
        return api_config


class DatabaseManager:
    """Handles all interactions with the configured database (MySQL or SQLite)."""

    def __init__(self, config):
        """
        Initializes the DatabaseManager based on the provided configuration.
        """
        self.db_type = config.get('db_type', 'sqlite')
        if self.db_type == 'mysql':
            self.mysql_config = config.get('mysql', {})
            logging.info("Database backend set to MySQL.")
        else:
            self.sqlite_path = config.get('path', 'data/pt_stats.db')
            logging.info(
                f"Database backend set to SQLite. Path: {self.sqlite_path}")

    def _get_connection(self):
        """Returns a new database connection."""
        if self.db_type == 'mysql':
            return mysql.connector.connect(**self.mysql_config,
                                           autocommit=False)
        else:
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
        cursor = self._get_cursor(conn)

        if self.db_type == 'mysql':
            cursor.execute('''CREATE TABLE IF NOT EXISTS traffic_stats (
                    stat_datetime DATETIME NOT NULL,
                    downloader_id VARCHAR(36) NOT NULL,
                    uploaded BIGINT DEFAULT 0,
                    downloaded BIGINT DEFAULT 0,
                    upload_speed BIGINT DEFAULT 0,
                    download_speed BIGINT DEFAULT 0,
                    PRIMARY KEY (stat_datetime, downloader_id)
                ) ENGINE=InnoDB ROW_FORMAT=Dynamic''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS downloader_clients (
                    id VARCHAR(36) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    type VARCHAR(50) NOT NULL,
                    last_session_dl BIGINT NOT NULL DEFAULT 0,
                    last_session_ul BIGINT NOT NULL DEFAULT 0,
                    last_cumulative_dl BIGINT NOT NULL DEFAULT 0,
                    last_cumulative_ul BIGINT NOT NULL DEFAULT 0
                ) ENGINE=InnoDB ROW_FORMAT=Dynamic''')
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
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS torrent_upload_stats (
                    hash VARCHAR(40) NOT NULL,
                    downloader_id VARCHAR(36) NOT NULL,
                    uploaded BIGINT DEFAULT 0,
                    PRIMARY KEY (hash, downloader_id)
                ) ENGINE=InnoDB ROW_FORMAT=Dynamic
            ''')
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
        conn.commit()

        try:
            cursor.execute("SELECT COUNT(*) FROM sites")
            result = cursor.fetchone()
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

        for d in downloaders:
            if d['id'] in db_ids:
                sql = "UPDATE downloader_clients SET name = %s, type = %s WHERE id = %s" if self.db_type == 'mysql' else "UPDATE downloader_clients SET name = ?, type = ? WHERE id = ?"
                cursor.execute(sql, (d['name'], d['type'], d['id']))
            else:
                sql = 'INSERT INTO downloader_clients (id, name, type) VALUES (%s, %s, %s)' if self.db_type == 'mysql' else 'INSERT INTO downloader_clients (id, name, type) VALUES (?, ?, ?)'
                cursor.execute(sql, (d['id'], d['name'], d['type']))

        ids_to_delete = db_ids - config_ids
        if ids_to_delete:
            placeholders = ', '.join([self.get_placeholder()] *
                                     len(ids_to_delete))
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
    current_timestamp_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    downloaders = config.get('downloaders', [])
    for client_config in downloaders:
        if not client_config.get('enabled'):
            continue

        client_id = client_config['id']
        client_type = client_config['type']

        try:
            if client_type == 'qbittorrent':
                api_config = {
                    k: v
                    for k, v in client_config.items()
                    if k not in ['id', 'name', 'type', 'enabled']
                }
                client = Client(**api_config)
                client.auth_log_in()
                info = client.transfer_info()
                current_session_dl = int(getattr(info, 'dl_info_data', 0))
                current_session_ul = int(getattr(info, 'up_info_data', 0))

                sql = f"UPDATE downloader_clients SET last_session_dl = {ph}, last_session_ul = {ph} WHERE id = {ph}"
                cursor.execute(
                    sql, (current_session_dl, current_session_ul, client_id))
                logging.info(
                    f"qBittorrent client '{client_config['name']}' baseline set for future calculations."
                )

            elif client_type == 'transmission':
                api_config = _prepare_api_config(client_config)
                client = TrClient(**api_config)
                stats = client.session_stats()
                current_cumulative_dl = int(
                    stats.cumulative_stats.downloaded_bytes)
                current_cumulative_ul = int(
                    stats.cumulative_stats.uploaded_bytes)

                sql_update_baseline = f"UPDATE downloader_clients SET last_cumulative_dl = {ph}, last_cumulative_ul = {ph} WHERE id = {ph}"
                cursor.execute(
                    sql_update_baseline,
                    (current_cumulative_dl, current_cumulative_ul, client_id))
                logging.info(
                    f"Transmission client '{client_config['name']}' baseline set for future calculations."
                )

            zero_point_records.append(
                (current_timestamp_str, client_id, 0, 0, 0, 0))

        except Exception as e:
            logging.error(
                f"[{client_config['name']}] Failed to set baseline at startup: {e}"
            )

    if zero_point_records:
        try:
            if db_manager.db_type == 'mysql':
                sql_insert_zero = '''
                    INSERT INTO traffic_stats (stat_datetime, downloader_id, uploaded, downloaded, upload_speed, download_speed) 
                    VALUES (%s, %s, %s, %s, %s, %s) 
                    ON DUPLICATE KEY UPDATE uploaded = VALUES(uploaded), downloaded = VALUES(downloaded)
                '''
            else:  # SQLite
                sql_insert_zero = '''
                    INSERT INTO traffic_stats (stat_datetime, downloader_id, uploaded, downloaded, upload_speed, download_speed) 
                    VALUES (?, ?, ?, ?, ?, ?) 
                    ON CONFLICT(stat_datetime, downloader_id) DO UPDATE SET uploaded = excluded.uploaded, downloaded = excluded.downloaded
                '''
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
    logging.info(
        "All client baselines synchronized and initial zero-points recorded.")
