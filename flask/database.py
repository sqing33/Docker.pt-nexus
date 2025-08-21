# database.py

import logging
import sqlite3
import mysql.connector
import json
import os

from config import SITES_DATA_FILE
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
        """Ensures all required database tables exist and seeds the sites table if it's empty."""
        conn = self._get_connection()
        cursor = conn.cursor()

        if self.db_type == 'mysql':
            cursor.execute(
                '''CREATE TABLE IF NOT EXISTS traffic_stats (stat_datetime DATETIME PRIMARY KEY, qb_uploaded BIGINT DEFAULT 0, qb_downloaded BIGINT DEFAULT 0, tr_uploaded BIGINT DEFAULT 0, tr_downloaded BIGINT DEFAULT 0, qb_upload_speed BIGINT DEFAULT 0, qb_download_speed BIGINT DEFAULT 0, tr_upload_speed BIGINT DEFAULT 0, tr_download_speed BIGINT DEFAULT 0) ENGINE=InnoDB ROW_FORMAT=Dynamic'''
            )
            cursor.execute(
                '''CREATE TABLE IF NOT EXISTS downloader_state (name VARCHAR(255) PRIMARY KEY, last_session_dl BIGINT NOT NULL DEFAULT 0, last_session_ul BIGINT NOT NULL DEFAULT 0, last_cumulative_dl BIGINT NOT NULL DEFAULT 0, last_cumulative_ul BIGINT NOT NULL DEFAULT 0) ENGINE=InnoDB ROW_FORMAT=Dynamic'''
            )
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
                    qb_uploaded BIGINT DEFAULT 0,
                    tr_uploaded BIGINT DEFAULT 0,
                    last_seen DATETIME NOT NULL
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
        else:
            cursor.execute(
                '''CREATE TABLE IF NOT EXISTS traffic_stats (stat_datetime TEXT PRIMARY KEY, qb_uploaded INTEGER DEFAULT 0, qb_downloaded INTEGER DEFAULT 0, tr_uploaded INTEGER DEFAULT 0, tr_downloaded INTEGER DEFAULT 0, qb_upload_speed INTEGER DEFAULT 0, qb_download_speed INTEGER DEFAULT 0, tr_upload_speed INTEGER DEFAULT 0, tr_download_speed INTEGER DEFAULT 0)'''
            )
            cursor.execute(
                '''CREATE TABLE IF NOT EXISTS downloader_state (name TEXT PRIMARY KEY, last_session_dl INTEGER NOT NULL DEFAULT 0, last_session_ul INTEGER NOT NULL DEFAULT 0, last_cumulative_dl INTEGER NOT NULL DEFAULT 0, last_cumulative_ul INTEGER NOT NULL DEFAULT 0)'''
            )
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
                    qb_uploaded INTEGER DEFAULT 0,
                    tr_uploaded INTEGER DEFAULT 0,
                    last_seen TEXT NOT NULL
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
            count = result[0] if isinstance(result,
                                            tuple) else result['COUNT(*)']

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
                    sql = f'''INSERT INTO sites (site, nickname, base_url, special_tracker_domain, `group`) 
                              VALUES ({ph}, {ph}, {ph}, {ph}, {ph})'''

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

        for downloader in ['qbittorrent', 'transmission']:
            sql = 'INSERT IGNORE INTO downloader_state (name) VALUES (%s)' if self.db_type == 'mysql' else 'INSERT OR IGNORE INTO downloader_state (name) VALUES (?)'
            cursor.execute(sql, (downloader, ))
        conn.commit()

        cursor.close()
        conn.close()
        logging.info("Database schemas verified.")


def reconcile_historical_data(db_manager, config):
    """
    Corrected function:
    1. (One-time only) If needed, create a historical baseline/genesis record.
    2. (On every start) Force synchronization of current state with download clients to prevent data spikes after a restart.
    """
    logging.info("Starting data reconciliation and state synchronization...")
    conn = db_manager._get_connection()
    cursor = db_manager._get_cursor(conn)
    is_mysql = db_manager.db_type == 'mysql'
    genesis_datetime = '1970-01-01 00:00:00'

    genesis_check_sql = "SELECT COUNT(*) FROM traffic_stats WHERE stat_datetime = %s" if is_mysql else "SELECT COUNT(*) FROM traffic_stats WHERE stat_datetime = ?"
    cursor.execute(genesis_check_sql, (genesis_datetime, ))
    result = cursor.fetchone()
    genesis_exists = result['COUNT(*)'] > 0 if is_mysql else result[0] > 0

    if not genesis_exists:
        logging.info(
            "Genesis record not found. Performing one-time data backfill.")
        manual_hist = {'qb_ul': 0, 'qb_dl': 0}
        initial_total = {'qb_ul': 0, 'qb_dl': 0, 'tr_ul': 0, 'tr_dl': 0}
        dl_val, ul_val = None, None
        if dl_val is not None and ul_val is not None:
            manual_hist['qb_dl'], manual_hist['qb_ul'] = int(
                dl_val * 1024**3), int(ul_val * 1024**3)

        if config.get('qbittorrent', {}).get('enabled'):
            try:
                client = Client(
                    **{
                        k: v
                        for k, v in config['qbittorrent'].items()
                        if k != 'enabled'
                    })
                client.auth_log_in()
                info = client.transfer_info()
                initial_total['qb_dl'], initial_total['qb_ul'] = int(
                    getattr(info, 'dl_info_data',
                            0)), int(getattr(info, 'up_info_data', 0))
            except Exception as e:
                logging.error(
                    f"[qB] Failed to get initial session data for genesis record: {e}"
                )

        if config.get('transmission', {}).get('enabled'):
            try:
                client = TrClient(
                    **{
                        k: v
                        for k, v in config['transmission'].items()
                        if k != 'enabled'
                    })
                stats = client.session_stats()
                initial_total['tr_dl'], initial_total['tr_ul'] = int(
                    stats.cumulative_stats.downloaded_bytes), int(
                        stats.cumulative_stats.uploaded_bytes)
            except Exception as e:
                logging.error(
                    f"[Tr] Failed to get initial cumulative data for genesis record: {e}"
                )

        final_qb_dl = manual_hist['qb_dl'] + initial_total['qb_dl']
        final_qb_ul = manual_hist['qb_ul'] + initial_total['qb_ul']
        final_tr_dl, final_tr_ul = initial_total['tr_dl'], initial_total[
            'tr_ul']

        if any(v > 0
               for v in [final_qb_dl, final_qb_ul, final_tr_dl, final_tr_ul]):
            insert_sql = 'INSERT INTO traffic_stats (stat_datetime, qb_uploaded, qb_downloaded, tr_uploaded, tr_downloaded) VALUES (%s, %s, %s, %s, %s)' if is_mysql else 'INSERT INTO traffic_stats (stat_datetime, qb_uploaded, qb_downloaded, tr_uploaded, tr_downloaded) VALUES (?, ?, ?, ?, ?)'
            cursor.execute(insert_sql, (genesis_datetime, final_qb_ul,
                                        final_qb_dl, final_tr_ul, final_tr_dl))

        conn.commit()
        logging.info("Genesis record creation finished.")

    logging.info(
        "Synchronizing downloader state with current client values...")

    if config.get('qbittorrent', {}).get('enabled'):
        try:
            client = Client(**{
                k: v
                for k, v in config['qbittorrent'].items() if k != 'enabled'
            })
            client.auth_log_in()
            info = client.transfer_info()
            current_session_dl = int(getattr(info, 'dl_info_data', 0))
            current_session_ul = int(getattr(info, 'up_info_data', 0))

            update_qb_sql = "UPDATE downloader_state SET last_session_dl = %s, last_session_ul = %s WHERE name = %s" if is_mysql else "UPDATE downloader_state SET last_session_dl = ?, last_session_ul = ? WHERE name = ?"
            cursor.execute(
                update_qb_sql,
                (current_session_dl, current_session_ul, 'qbittorrent'))
            logging.info(
                f"qBittorrent state synchronized: last_session_dl set to {current_session_dl}, last_session_ul set to {current_session_ul}."
            )
        except Exception as e:
            logging.error(f"[qB] Failed to synchronize state at startup: {e}")

    if config.get('transmission', {}).get('enabled'):
        try:
            client = TrClient(**{
                k: v
                for k, v in config['transmission'].items() if k != 'enabled'
            })
            stats = client.session_stats()
            current_cumulative_dl = int(
                stats.cumulative_stats.downloaded_bytes)
            current_cumulative_ul = int(stats.cumulative_stats.uploaded_bytes)

            update_tr_sql = "UPDATE downloader_state SET last_cumulative_dl = %s, last_cumulative_ul = %s WHERE name = %s" if is_mysql else "UPDATE downloader_state SET last_cumulative_dl = ?, last_cumulative_ul = ? WHERE name = ?"
            cursor.execute(
                update_tr_sql,
                (current_cumulative_dl, current_cumulative_ul, 'transmission'))
            logging.info(
                f"Transmission state synchronized: last_cumulative_dl set to {current_cumulative_dl}, last_cumulative_ul set to {current_cumulative_ul}."
            )
        except Exception as e:
            logging.error(f"[Tr] Failed to synchronize state at startup: {e}")

    conn.commit()
    cursor.close()
    conn.close()
    logging.info("Data reconciliation and state synchronization finished.")
