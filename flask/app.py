# app.py

import collections
import json
import os
import math
import time
import sqlite3
import logging
import re
from datetime import datetime, timedelta
from functools import cmp_to_key
from threading import Thread, Lock
from urllib.parse import urlparse
from collections import defaultdict

# 核心改动：不再需要 render_template，引入 CORS
from flask import Flask, jsonify, request
from flask_cors import CORS
from qbittorrentapi import Client
from transmission_rpc import Client as TrClient
import mysql.connector

from dotenv import load_dotenv

load_dotenv()

# --- 全局配置 ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [PID:%(process)d] - %(levelname)s - %(message)s')

app = Flask(__name__)

# --- 核心改动：为所有 /api/ 开头的路由启用 CORS ---
CORS(app, resources={r"/api/*": {"origins": "*"}})

DATA_DIR = '.'
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')
DB_FILE = os.path.join(DATA_DIR, 'pt_stats.db')

# --- 缓存定义 ---
CACHE_LOCK = Lock()
data_tracker_thread = None


# --- 核心辅助函数 ---
def save_config(config_data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, indent=4, ensure_ascii=False)


def initialize_app_files():
    if not os.path.exists(CONFIG_FILE):
        logging.warning(
            f"Config file not found. Creating a default one at {CONFIG_FILE}")
        save_config({
            "qbittorrent": {
                "enabled": False,
                "host": "192.168.1.100:8080",
                "username": "",
                "password": ""
            },
            "transmission": {
                "enabled": False,
                "host": "192.168.1.100",
                "port": 9091,
                "username": "",
                "password": ""
            },
            "ui_settings": {
                "active_path_filters": [],
                "page_size": 50,
                "torrent_update_interval_seconds": 3600
            }
        })


def load_config():
    if not os.path.exists(CONFIG_FILE):
        initialize_app_files()
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        logging.error(
            f"Failed to load or create config file due to {e}. Using default empty config."
        )
        return {"qbittorrent": {}, "transmission": {}, "ui_settings": {}}


def get_char_type(c):
    c = c.lower()
    return 1 if 'a' <= c <= 'z' else 2 if '0' <= c <= '9' else 3


def custom_sort_compare(a, b):
    na, nb = a['name'].lower(), b['name'].lower()
    l = min(len(na), len(nb))
    for i in range(l):
        ta, tb = get_char_type(na[i]), get_char_type(nb[i])
        if ta != tb: return ta - tb
        if na[i] != nb[i]: return -1 if na[i] < nb[i] else 1
    return len(na) - len(nb)


def _extract_core_domain(hostname):
    """从完整域名中提取核心部分。"""
    if not hostname:
        return None
    hostname = re.sub(r'^(www|tracker|kp|pt|t|ipv4|ipv6|on|daydream)\.', '',
                      hostname)
    parts = hostname.split('.')
    if len(parts) > 2 and len(parts[-2]) <= 3 and len(parts[-1]) <= 3:
        return parts[-3]
    elif len(parts) > 1:
        return parts[-2]
    else:
        return parts[0]


# --- 数据库交互 ---
class DatabaseManager:

    def __init__(self, config):
        self.db_type = config.get('db_type', 'sqlite')
        if self.db_type == 'mysql':
            self.mysql_config = config.get('mysql', {})
            logging.info("Database backend set to MySQL.")
        else:
            self.sqlite_path = DB_FILE
            logging.info("Database backend set to SQLite.")

    def _get_connection(self):
        if self.db_type == 'mysql':
            return mysql.connector.connect(**self.mysql_config,
                                           autocommit=False)
        else:
            return sqlite3.connect(self.sqlite_path)

    def _get_cursor(self, conn):
        if self.db_type == 'mysql':
            return conn.cursor(dictionary=True)
        else:
            conn.row_factory = sqlite3.Row
            return conn.cursor()

    def init_db(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        if self.db_type == 'mysql':
            cursor.execute(
                '''CREATE TABLE IF NOT EXISTS traffic_stats (stat_datetime DATETIME PRIMARY KEY, qb_uploaded BIGINT DEFAULT 0, qb_downloaded BIGINT DEFAULT 0, tr_uploaded BIGINT DEFAULT 0, tr_downloaded BIGINT DEFAULT 0, qb_upload_speed BIGINT DEFAULT 0, qb_download_speed BIGINT DEFAULT 0, tr_upload_speed BIGINT DEFAULT 0, tr_download_speed BIGINT DEFAULT 0)'''
            )
        else:
            cursor.execute(
                '''CREATE TABLE IF NOT EXISTS traffic_stats (stat_datetime TEXT PRIMARY KEY, qb_uploaded INTEGER DEFAULT 0, qb_downloaded INTEGER DEFAULT 0, tr_uploaded INTEGER DEFAULT 0, tr_downloaded INTEGER DEFAULT 0, qb_upload_speed INTEGER DEFAULT 0, qb_download_speed INTEGER DEFAULT 0, tr_upload_speed INTEGER DEFAULT 0, tr_download_speed INTEGER DEFAULT 0)'''
            )
        cursor.execute(
            '''CREATE TABLE IF NOT EXISTS downloader_state (name VARCHAR(255) PRIMARY KEY, last_session_dl BIGINT NOT NULL DEFAULT 0, last_session_ul BIGINT NOT NULL DEFAULT 0, last_cumulative_dl BIGINT NOT NULL DEFAULT 0, last_cumulative_ul BIGINT NOT NULL DEFAULT 0)'''
        )
        if self.db_type == 'mysql':
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS torrents (
                    hash VARCHAR(40) PRIMARY KEY,
                    name TEXT NOT NULL,
                    save_path TEXT,
                    size BIGINT,
                    progress FLOAT,
                    state VARCHAR(50),
                    sites VARCHAR(255),
                    details TEXT,
                    qb_uploaded BIGINT DEFAULT 0,
                    tr_uploaded BIGINT DEFAULT 0,
                    last_seen DATETIME NOT NULL
                )
            ''')
        else:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS torrents (
                    hash TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    save_path TEXT,
                    size INTEGER,
                    progress REAL,
                    state TEXT,
                    sites TEXT,
                    details TEXT,
                    qb_uploaded INTEGER DEFAULT 0,
                    tr_uploaded INTEGER DEFAULT 0,
                    last_seen TEXT NOT NULL
                )
            ''')

        for downloader in ['qbittorrent', 'transmission']:
            sql = 'INSERT IGNORE INTO downloader_state (name) VALUES (%s)' if self.db_type == 'mysql' else 'INSERT OR IGNORE INTO downloader_state (name) VALUES (?)'
            cursor.execute(sql, (downloader, ))
        conn.commit()
        cursor.close()
        conn.close()
        logging.info("Database schemas verified.")


def load_site_maps_from_db(db_manager):
    core_domain_map, link_rules = {}, {}
    if db_manager.db_type != 'mysql':
        logging.warning("Site mapping is only supported for MySQL backend.")
        return core_domain_map, link_rules

    try:
        conn = db_manager._get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT nickname, base_url, special_tracker_domain FROM sites")
        for row in cursor.fetchall():
            nickname = row.get('nickname')
            base_url = row.get('base_url')
            special_tracker = row.get('special_tracker_domain')

            if nickname and base_url:
                link_rules[nickname] = {"base_url": base_url.strip()}

                base_hostname = _parse_hostname_from_url(f"http://{base_url}")
                base_core = _extract_core_domain(base_hostname)
                if base_core:
                    core_domain_map[base_core] = nickname

                if special_tracker:
                    special_hostname = _parse_hostname_from_url(
                        f"http://{special_tracker}")
                    special_core = _extract_core_domain(special_hostname)
                    if special_core:
                        core_domain_map[special_core] = nickname

        cursor.close()
        conn.close()
        logging.info(
            f"Loaded {len(link_rules)} sites, created {len(core_domain_map)} core domain mappings."
        )
    except Exception as e:
        logging.error(f"Could not load site info from DB: {e}", exc_info=True)

    return core_domain_map, link_rules


def _parse_hostname_from_url(url_string):
    try:
        return urlparse(url_string).hostname if url_string else None
    except Exception:
        return None


def _extract_url_from_comment(comment):
    if not comment or not isinstance(comment, str):
        return comment
    match = re.search(r'https?://[^\s/$.?#].[^\s]*', comment)
    if match:
        return match.group(0)
    return comment


def placeholder():
    return '%s'


def reconcile_historical_data(db_manager):
    """
    修正后的函数：
    1.  (仅一次) 如果需要，创建历史基线/创世记录。
    2.  (每次启动) 强制与下载客户端同步当前状态，以防止重启后出现数据尖峰。
    """
    logging.info("Starting data reconciliation and state synchronization...")
    config = load_config()
    conn = db_manager._get_connection()
    cursor = db_manager._get_cursor(conn)
    is_mysql = db_manager.db_type == 'mysql'
    genesis_datetime = '1970-01-01 00:00:00'

    # --- 步骤 1: 一次性的创世记录创建 ---
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

    # --- 步骤 2: 每次启动时都执行的状态同步 ---
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


class DataTracker(Thread):

    def __init__(self, db_manager, interval=1):
        super().__init__(daemon=True, name="DataTracker")
        self.db_manager = db_manager
        self.interval = interval
        self._is_running = True

        self.TRAFFIC_BATCH_WRITE_SIZE = 60
        self.traffic_buffer = []
        self.traffic_buffer_lock = Lock()

        self.latest_speeds = {
            'qb_ul_speed': 0,
            'qb_dl_speed': 0,
            'tr_ul_speed': 0,
            'tr_dl_speed': 0
        }
        self.recent_speeds_buffer = collections.deque(
            maxlen=self.TRAFFIC_BATCH_WRITE_SIZE)

        self.torrent_update_counter = 0
        config = load_config()
        self.TORRENT_UPDATE_INTERVAL = config.get('ui_settings', {}).get(
            'torrent_update_interval_seconds', 3600)

    @staticmethod
    def format_bytes(b):
        if not isinstance(b, (int, float)) or b < 0: return "0 B"
        if b == 0: return "0 B"
        s = ("B", "KB", "MB", "GB", "TB", "PB")
        i = int(math.floor(math.log(b, 1024))) if b > 0 else 0
        p = math.pow(1024, i)
        return f"{round(b/p,2)} {s[i]}"

    @staticmethod
    def format_state(s):
        sl = str(s).lower()
        a = {
            'downloading': '下载中',
            'uploading': '做种中',
            'stalledup': '做种中',
            'seed': '做种中',
            'seeding': '做种中',
            'paused': '暂停',
            'stopped': '暂停',
            'stalleddl': '暂停',
            'checking': '校验中',
            'check': '校验中',
            'error': '错误',
            'missingfiles': '文件丢失'
        }
        return next((v for k, v in a.items() if k in sl), str(s).capitalize())

    def run(self):
        logging.info(
            f"DataTracker thread started. Traffic update interval: {self.interval}s, Torrent update interval: {self.TORRENT_UPDATE_INTERVAL}s."
        )
        time.sleep(5)

        try:
            self._update_torrents_in_db()
        except Exception as e:
            logging.error(f"Initial torrents DB update failed: {e}",
                          exc_info=True)

        while self._is_running:
            start_time = time.monotonic()
            try:
                self._fetch_and_buffer_stats()

                self.torrent_update_counter += self.interval
                if self.torrent_update_counter >= self.TORRENT_UPDATE_INTERVAL:
                    self._update_torrents_in_db()
                    self.torrent_update_counter = 0

            except Exception as e:
                logging.error(f"Error in DataTracker loop: {e}", exc_info=True)

            elapsed = time.monotonic() - start_time
            time.sleep(max(0, self.interval - elapsed))

    def _fetch_and_buffer_stats(self):
        config = load_config()

        current_data = {
            'timestamp': datetime.now(),
            'qb_dl': 0,
            'qb_ul': 0,
            'qb_dl_speed': 0,
            'qb_ul_speed': 0,
            'tr_dl': 0,
            'tr_ul': 0,
            'tr_dl_speed': 0,
            'tr_ul_speed': 0
        }

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
                current_data['qb_dl_speed'] = int(
                    getattr(info, 'dl_info_speed', 0))
                current_data['qb_ul_speed'] = int(
                    getattr(info, 'up_info_speed', 0))
                current_data['qb_dl'] = int(getattr(info, 'dl_info_data', 0))
                current_data['qb_ul'] = int(getattr(info, 'up_info_data', 0))
            except Exception as e:
                logging.warning(f"Could not fetch qB stats: {e}")

        if config.get('transmission', {}).get('enabled'):
            try:
                client = TrClient(
                    **{
                        k: v
                        for k, v in config['transmission'].items()
                        if k != 'enabled'
                    })
                stats = client.session_stats()
                current_data['tr_dl_speed'] = int(
                    getattr(stats, 'download_speed', 0))
                current_data['tr_ul_speed'] = int(
                    getattr(stats, 'upload_speed', 0))
                current_data['tr_dl'] = int(
                    stats.cumulative_stats.downloaded_bytes)
                current_data['tr_ul'] = int(
                    stats.cumulative_stats.uploaded_bytes)
            except Exception as e:
                logging.warning(f"Could not fetch Tr stats: {e}")

        with CACHE_LOCK:
            self.latest_speeds = {
                'qb_dl_speed': current_data['qb_dl_speed'],
                'qb_ul_speed': current_data['qb_ul_speed'],
                'tr_dl_speed': current_data['tr_dl_speed'],
                'tr_ul_speed': current_data['tr_ul_speed']
            }
            self.recent_speeds_buffer.append(current_data)

        buffer_to_flush = []
        with self.traffic_buffer_lock:
            self.traffic_buffer.append(current_data)
            if len(self.traffic_buffer) >= self.TRAFFIC_BATCH_WRITE_SIZE:
                buffer_to_flush = self.traffic_buffer
                self.traffic_buffer = []

        if buffer_to_flush:
            self._flush_traffic_buffer_to_db(buffer_to_flush)

    def _flush_traffic_buffer_to_db(self, buffer):
        if not buffer:
            return

        logging.info(
            f"Flushing {len(buffer)} traffic data points to the database...")
        conn = None
        try:
            # --- 步骤 1: 获取连接和单个游标，开启事务 ---
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)
            is_mysql = self.db_manager.db_type == 'mysql'

            # --- 步骤 2: 在事务开始时，获取一次基准状态 ---
            qb_state_sql = 'SELECT last_session_dl, last_session_ul FROM downloader_state WHERE name = %s' if is_mysql else 'SELECT last_session_dl, last_session_ul FROM downloader_state WHERE name = ?'
            tr_state_sql = 'SELECT last_cumulative_dl, last_cumulative_ul FROM downloader_state WHERE name = %s' if is_mysql else 'SELECT last_cumulative_dl, last_cumulative_ul FROM downloader_state WHERE name = ?'

            cursor.execute(qb_state_sql, ('qbittorrent', ))
            qb_row = cursor.fetchone()
            # 强制转换为 int，避免任何类型问题
            last_qb_dl = int(qb_row['last_session_dl']) if qb_row else 0
            last_qb_ul = int(qb_row['last_session_ul']) if qb_row else 0

            cursor.execute(tr_state_sql, ('transmission', ))
            tr_row = cursor.fetchone()
            last_tr_dl = int(tr_row['last_cumulative_dl']) if tr_row else 0
            last_tr_ul = int(tr_row['last_cumulative_ul']) if tr_row else 0

            params_to_insert = []

            # --- 步骤 3: 循环计算所有增量 ---
            for data_point in buffer:
                current_qb_dl = data_point['qb_dl']
                current_qb_ul = data_point['qb_ul']

                # 正确的增量计算逻辑
                if current_qb_dl < last_qb_dl:
                    qb_dl_inc = current_qb_dl
                else:
                    qb_dl_inc = current_qb_dl - last_qb_dl

                if current_qb_ul < last_qb_ul:
                    qb_ul_inc = current_qb_ul
                else:
                    qb_ul_inc = current_qb_ul - last_qb_ul

                tr_dl_inc = data_point['tr_dl'] - last_tr_dl
                tr_ul_inc = data_point['tr_ul'] - last_tr_ul

                params_to_insert.append(
                    (data_point['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                     max(0, qb_dl_inc), max(0, qb_ul_inc), max(0, tr_dl_inc),
                     max(0, tr_ul_inc), data_point['qb_dl_speed'],
                     data_point['qb_ul_speed'], data_point['tr_dl_speed'],
                     data_point['tr_ul_speed']))

                # 在循环内部更新基准值，为下一次迭代做准备
                last_qb_dl = current_qb_dl
                last_qb_ul = current_qb_ul
                last_tr_dl = data_point['tr_dl']
                last_tr_ul = data_point['tr_ul']

            # --- 步骤 4: 批量写入所有计算出的增量 ---
            if params_to_insert:
                if is_mysql:
                    sql_insert = '''
                        INSERT INTO traffic_stats (stat_datetime, qb_downloaded, qb_uploaded, tr_downloaded, tr_uploaded, qb_download_speed, qb_upload_speed, tr_download_speed, tr_upload_speed)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            qb_downloaded = VALUES(qb_downloaded), qb_uploaded = VALUES(qb_uploaded),
                            tr_downloaded = VALUES(tr_downloaded), tr_uploaded = VALUES(tr_uploaded),
                            qb_download_speed = VALUES(qb_download_speed), qb_upload_speed = VALUES(qb_upload_speed),
                            tr_download_speed = VALUES(tr_download_speed), tr_upload_speed = VALUES(tr_upload_speed)
                    '''
                else:  # SQLite
                    sql_insert = '''
                        INSERT INTO traffic_stats (stat_datetime, qb_downloaded, qb_uploaded, tr_downloaded, tr_uploaded, qb_download_speed, qb_upload_speed, tr_download_speed, tr_upload_speed)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(stat_datetime) DO UPDATE SET
                            qb_downloaded = excluded.qb_downloaded, qb_uploaded = excluded.qb_uploaded,
                            tr_downloaded = excluded.tr_downloaded, tr_uploaded = excluded.tr_uploaded,
                            qb_download_speed = excluded.qb_download_speed, qb_upload_speed = excluded.qb_upload_speed,
                            tr_download_speed = excluded.tr_download_speed, tr_upload_speed = excluded.tr_upload_speed
                    '''
                cursor.executemany(sql_insert, params_to_insert)

            # --- 步骤 5: 更新 downloader_state 为批次处理完后的最终状态 ---
            final_data_point = buffer[-1]
            update_qb_sql = "UPDATE downloader_state SET last_session_dl = %s, last_session_ul = %s WHERE name = %s" if is_mysql else "UPDATE downloader_state SET last_session_dl = ?, last_session_ul = ? WHERE name = ?"
            update_tr_sql = "UPDATE downloader_state SET last_cumulative_dl = %s, last_cumulative_ul = %s WHERE name = %s" if is_mysql else "UPDATE downloader_state SET last_cumulative_dl = ?, last_cumulative_ul = ? WHERE name = ?"

            cursor.execute(update_qb_sql,
                           (final_data_point['qb_dl'],
                            final_data_point['qb_ul'], 'qbittorrent'))
            cursor.execute(update_tr_sql,
                           (final_data_point['tr_dl'],
                            final_data_point['tr_ul'], 'transmission'))

            # --- 步骤 6: 提交整个事务 ---
            conn.commit()
            logging.info("Traffic data batch write successful.")

        except Exception as e:
            logging.error(f"Failed to flush traffic buffer to DB: {e}",
                          exc_info=True)
            if conn: conn.rollback()
        finally:
            if conn:
                cursor.close()
                conn.close()

    def _update_torrents_in_db(self):
        logging.info("Starting to update torrents in the database...")
        config = load_config()
        core_domain_map, _ = load_site_maps_from_db(self.db_manager)
        if not core_domain_map:
            logging.warning(
                "Core domain map is empty. Site identification will likely fail."
            )

        all_current_hashes = set()
        is_mysql = self.db_manager.db_type == 'mysql'

        conn = None
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)  # 使用字典游标
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            if config.get('qbittorrent', {}).get('enabled'):
                try:
                    q = Client(
                        **{
                            k: v
                            for k, v in config['qbittorrent'].items()
                            if k != 'enabled'
                        })
                    q.auth_log_in()
                    qb_torrents = q.torrents_info(status_filter='all')
                    logging.info(
                        f"Found {len(qb_torrents)} torrents in qBittorrent.")

                    for t in qb_torrents:
                        all_current_hashes.add(t.hash)

                        site_nickname = None
                        site_detail_url = None
                        if t.trackers:
                            for tracker_entry in t.trackers:
                                hostname = _parse_hostname_from_url(
                                    tracker_entry.get('url'))
                                core_domain = _extract_core_domain(hostname)
                                if core_domain in core_domain_map:
                                    site_nickname = core_domain_map[
                                        core_domain]
                                    site_detail_url = _extract_url_from_comment(
                                        t.comment)
                                    break

                        params = (t.hash, t.name, t.save_path, t.size,
                                  round(t.progress * 100, 1),
                                  self.format_state(t.state), site_nickname,
                                  site_detail_url, t.uploaded, now_str)

                        if is_mysql:
                            sql = '''INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, qb_uploaded, last_seen)
                                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                     ON DUPLICATE KEY UPDATE
                                     name=VALUES(name), save_path=VALUES(save_path), size=VALUES(size), progress=VALUES(progress),
                                     state=VALUES(state), sites=VALUES(sites), details=VALUES(details),
                                     qb_uploaded=GREATEST(VALUES(qb_uploaded), torrents.qb_uploaded),
                                     last_seen=VALUES(last_seen)'''
                        else:
                            sql = '''INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, qb_uploaded, last_seen)
                                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                     ON CONFLICT(hash) DO UPDATE SET
                                     name=excluded.name, save_path=excluded.save_path, size=excluded.size, progress=excluded.progress,
                                     state=excluded.state, sites=excluded.sites, details=excluded.details,
                                     qb_uploaded=max(excluded.qb_uploaded, torrents.qb_uploaded),
                                     last_seen=excluded.last_seen'''
                        cursor.execute(sql, params)

                except Exception as e:
                    logging.error(
                        f"Failed to get or update torrents from qB: {e}",
                        exc_info=True)

            if config.get('transmission', {}).get('enabled'):
                try:
                    tr = TrClient(
                        **{
                            k: v
                            for k, v in config['transmission'].items()
                            if k != 'enabled'
                        })
                    fields = [
                        'id', 'name', 'hashString', 'downloadDir', 'totalSize',
                        'status', 'comment', 'trackers', 'percentDone',
                        'uploadedEver'
                    ]
                    tr_torrents = tr.get_torrents(arguments=fields)
                    logging.info(
                        f"Found {len(tr_torrents)} torrents in Transmission.")

                    for t in tr_torrents:
                        all_current_hashes.add(t.hash_string)

                        site_nickname = None
                        site_detail_url = None
                        if t.trackers:
                            for tracker_info in t.trackers:
                                hostname = _parse_hostname_from_url(
                                    tracker_info.get('announce'))
                                core_domain = _extract_core_domain(hostname)
                                if core_domain in core_domain_map:
                                    site_nickname = core_domain_map[
                                        core_domain]
                                    site_detail_url = _extract_url_from_comment(
                                        t.comment)
                                    break

                        params = (t.hash_string, t.name, t.download_dir,
                                  t.total_size, round(t.percent_done * 100, 1),
                                  self.format_state(t.status), site_nickname,
                                  site_detail_url, t.uploaded_ever, now_str)

                        if is_mysql:
                            sql = '''INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, tr_uploaded, last_seen)
                                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                     ON DUPLICATE KEY UPDATE
                                     name=VALUES(name), save_path=VALUES(save_path), size=VALUES(size), progress=VALUES(progress),
                                     state=VALUES(state), sites=VALUES(sites), details=VALUES(details),
                                     tr_uploaded=GREATEST(VALUES(tr_uploaded), torrents.tr_uploaded),
                                     last_seen=VALUES(last_seen)'''
                        else:
                            sql = '''INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, tr_uploaded, last_seen)
                                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                     ON CONFLICT(hash) DO UPDATE SET
                                     name=excluded.name, save_path=excluded.save_path, size=excluded.size, progress=excluded.progress,
                                     state=excluded.state, sites=excluded.sites, details=excluded.details,
                                     tr_uploaded=max(excluded.tr_uploaded, torrents.tr_uploaded),
                                     last_seen=excluded.last_seen'''
                        cursor.execute(sql, params)

                except Exception as e:
                    logging.error(
                        f"Failed to get or update torrents from Tr: {e}",
                        exc_info=True)

            if all_current_hashes:
                placeholders = ', '.join(['%s' if is_mysql else '?'] *
                                         len(all_current_hashes))
                sql_delete = f"DELETE FROM torrents WHERE hash NOT IN ({placeholders})"
                # 再次获取非字典游标用于删除
                non_dict_cursor = conn.cursor()
                non_dict_cursor.execute(sql_delete, tuple(all_current_hashes))
                logging.info(
                    f"Removed {non_dict_cursor.rowcount} stale torrents from DB."
                )
                non_dict_cursor.close()

            else:
                non_dict_cursor = conn.cursor()
                non_dict_cursor.execute("DELETE FROM torrents")
                logging.info(
                    "No torrents found in any client, cleared torrents table.")
                non_dict_cursor.close()

            conn.commit()
            logging.info(
                "Torrents database update cycle completed successfully.")

        except Exception as e:
            logging.error(f"Failed to update torrents in DB: {e}",
                          exc_info=True)
            if conn: conn.rollback()
        finally:
            if conn:
                cursor.close()
                conn.close()

    def stop(self):
        with self.traffic_buffer_lock:
            self._flush_traffic_buffer_to_db(self.traffic_buffer)
        self._is_running = False


# --- 全局初始化 ---
initialize_app_files()
config = load_config()

# 1. 直接从环境变量构建 MySQL 配置
mysql_config = {
    'host': os.getenv('MYSQL_HOST'),
    'user': os.getenv('MYSQL_USER'),
    'password': os.getenv('MYSQL_PASSWORD'),
    'database': os.getenv('MYSQL_DATABASE'),
    'port': int(os.getenv('MYSQL_PORT', 3306))
}

# 2. 检查必要的环境变量是否存在
if not all([
        mysql_config['host'], mysql_config['user'], mysql_config['password'],
        mysql_config['database']
]):
    logging.error(
        "关键的 MySQL 环境变量 (HOST, USER, PASSWORD, DATABASE) 未设置！请检查你的 .env 文件或环境变量。"
    )
    exit(1)

# 3. 创建强制使用 MySQL 的配置
db_config = {'db_type': 'mysql', 'mysql': mysql_config}

# 4. 实例化 DatabaseManager
db_manager = DatabaseManager(db_config)
db_manager.init_db()
reconcile_historical_data(db_manager)

if data_tracker_thread is None:
    data_tracker_thread = DataTracker(db_manager)
    data_tracker_thread.start()

# --- Web 服务及辅助函数 ---


def get_date_range_and_grouping(time_range_str, for_speed=False):
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_dt, end_dt = None, now
    group_by_format = '%Y-%m-%d'
    ranges = {
        'today': (today_start, '%Y-%m-%d %H:00'),
        'yesterday': (today_start - timedelta(days=1), '%Y-%m-%d %H:00'),
        'this_week': (today_start - timedelta(days=now.weekday()), '%Y-%m-%d'),
        'last_week':
        (today_start - timedelta(days=now.weekday() + 7), '%Y-%m-%d'),
        'this_month': (today_start.replace(day=1), '%Y-%m-%d'),
        'last_month':
        ((today_start.replace(day=1) - timedelta(days=1)).replace(day=1),
         '%Y-%m-%d'),
        'last_6_months': (now - timedelta(days=180), '%Y-%m'),
        'this_year': (today_start.replace(month=1, day=1), '%Y-%m'),
        'all': (datetime(1970, 1, 2), '%Y-%m'),
        'last_1_hour': (now - timedelta(hours=1), 'CUSTOM_5_SEC_INTERVAL'),
        'last_12_hours': (now - timedelta(hours=12), None),
        'last_24_hours': (now - timedelta(hours=24), None)
    }
    if time_range_str in ranges:
        start_dt, group_by_format_override = ranges[time_range_str]
        if group_by_format_override: group_by_format = group_by_format_override

    if time_range_str == 'yesterday': end_dt = today_start
    if time_range_str == 'last_week':
        end_dt = today_start - timedelta(days=now.weekday())
    if time_range_str == 'last_month': end_dt = today_start.replace(day=1)

    if for_speed:
        if time_range_str in [
                'last_12_hours', 'last_24_hours', 'today', 'yesterday'
        ]:
            group_by_format = '%Y-%m-%d %H:%M'
        elif start_dt and (end_dt - start_dt).total_seconds() > 0:
            if group_by_format not in ['%Y-%m', 'CUSTOM_5_SEC_INTERVAL']:
                interval_seconds = (end_dt - start_dt).total_seconds() / 600
                if interval_seconds <= 5400: group_by_format = '%Y-%m-%d %H:00'

    return start_dt, end_dt, group_by_format


def get_time_group_fn(db_type, format_str):
    if format_str == 'CUSTOM_5_SEC_INTERVAL':
        if db_type == 'mysql':
            return "FROM_UNIXTIME(FLOOR(UNIX_TIMESTAMP(stat_datetime) / 5) * 5, '%Y-%m-%d %H:%i:%s')"
        else:
            return "STRFTIME('%Y-%m-%d %H:%M:%S', CAST(strftime('%s', stat_datetime) / 5 AS INTEGER) * 5, 'unixepoch')"
    return f"DATE_FORMAT(stat_datetime, '{format_str.replace('%M', '%i')}')" if db_type == 'mysql' else f"STRFTIME('{format_str}', stat_datetime)"


@app.route('/api/chart_data')
def get_chart_data_api():
    time_range = request.args.get('range', 'this_week')
    start_dt, end_dt, group_by_format = get_date_range_and_grouping(time_range)
    time_group_fn = get_time_group_fn(db_manager.db_type, group_by_format)
    ph = placeholder()
    is_mysql = db_manager.db_type == 'mysql'
    query = f"SELECT {time_group_fn} AS time_group, SUM(qb_uploaded) AS qb_ul, SUM(qb_downloaded) AS qb_dl, SUM(tr_uploaded) AS tr_ul, SUM(tr_downloaded) AS tr_dl FROM traffic_stats WHERE stat_datetime >= {ph}"
    params = [start_dt.strftime('%Y-%m-%d %H:%M:%S')]
    if end_dt:
        query += f" AND stat_datetime < {ph}"
        params.append(end_dt.strftime('%Y-%m-%d %H:%M:%S'))
    query += " GROUP BY time_group ORDER BY time_group"
    conn = None
    try:
        conn = db_manager._get_connection()
        cursor = conn.cursor(dictionary=is_mysql)
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        labels = [r['time_group'] for r in rows]
        datasets = [{
            "time": r['time_group'],
            "qb_ul": int(r['qb_ul'] or 0),
            "qb_dl": int(r['qb_dl'] or 0),
            "tr_ul": int(r['tr_ul'] or 0),
            "tr_dl": int(r['tr_dl'] or 0)
        } for r in rows]
        return jsonify({"labels": labels, "datasets": datasets})
    except Exception as e:
        logging.error(f"Error in get_chart_data_api: {e}", exc_info=True)
        return jsonify({"error": "Failed to fetch chart data"}), 500
    finally:
        if conn:
            cursor.close()
            conn.close()


@app.route('/api/speed_data')
def get_speed_data_api():
    with CACHE_LOCK:
        speeds = data_tracker_thread.latest_speeds
    cfg = load_config()
    return jsonify({
        'qbittorrent': {
            'enabled': cfg.get('qbittorrent', {}).get('enabled', False),
            'upload_speed': speeds['qb_ul_speed'],
            'download_speed': speeds['qb_dl_speed']
        },
        'transmission': {
            'enabled': cfg.get('transmission', {}).get('enabled', False),
            'upload_speed': speeds['tr_ul_speed'],
            'download_speed': speeds['tr_dl_speed']
        }
    })


@app.route('/api/recent_speed_data')
def get_recent_speed_data_api():
    try:
        seconds_to_fetch = int(request.args.get('seconds', '60'))
    except ValueError:
        return jsonify({"error": "Invalid seconds parameter"}), 400

    with CACHE_LOCK:
        buffer_data = list(data_tracker_thread.recent_speeds_buffer)

    results = [{
        "time": r['timestamp'].strftime('%H:%M:%S'),
        "qb_ul_speed": r['qb_ul_speed'],
        "qb_dl_speed": r['qb_dl_speed'],
        "tr_ul_speed": r['tr_ul_speed'],
        "tr_dl_speed": r['tr_dl_speed'],
    } for r in sorted(buffer_data, key=lambda x: x['timestamp'])]

    seconds_missing = seconds_to_fetch - len(results)
    db_data = []

    if seconds_missing > 0:
        conn = None
        try:
            end_dt = buffer_data[0][
                'timestamp'] if buffer_data else datetime.now()
            is_mysql = db_manager.db_type == 'mysql'
            ph = placeholder()
            conn = db_manager._get_connection()
            cursor = db_manager._get_cursor(conn)
            query = f"""
                SELECT stat_datetime, qb_upload_speed, qb_download_speed, tr_upload_speed, tr_download_speed
                FROM traffic_stats
                WHERE stat_datetime < {ph}
                ORDER BY stat_datetime DESC
                LIMIT {ph}
            """
            params = [end_dt.strftime('%Y-%m-%d %H:%M:%S'), seconds_missing]
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            for row in reversed(rows):
                dt_obj = row[
                    'stat_datetime'] if is_mysql else datetime.strptime(
                        row['stat_datetime'], '%Y-%m-%d %H:%M:%S')
                db_data.append({
                    "time": dt_obj.strftime('%H:%M:%S'),
                    "qb_ul_speed": row['qb_upload_speed'] or 0,
                    "qb_dl_speed": row['qb_download_speed'] or 0,
                    "tr_ul_speed": row['tr_upload_speed'] or 0,
                    "tr_dl_speed": row['tr_download_speed'] or 0,
                })
        except Exception as e:
            logging.error(
                f"Failed to fetch historical speed data for pre-fill: {e}",
                exc_info=True)
        finally:
            if conn:
                cursor.close()
                conn.close()

    final_results = db_data + results
    if (pad_count := seconds_to_fetch - len(final_results)) > 0:
        last_time = datetime.now() - timedelta(seconds=len(final_results))
        padding = [{
            "time":
            (last_time - timedelta(seconds=i + 1)).strftime('%H:%M:%S'),
            "qb_ul_speed":
            0,
            "qb_dl_speed":
            0,
            "tr_ul_speed":
            0,
            "tr_dl_speed":
            0,
        } for i in range(pad_count)]
        final_results = padding + final_results

    cfg = load_config()
    qb_enabled = cfg.get('qbittorrent', {}).get('enabled', False)
    tr_enabled = cfg.get('transmission', {}).get('enabled', False)
    for r in final_results:
        r['qb_enabled'] = qb_enabled
        r['tr_enabled'] = tr_enabled

    return jsonify(final_results[-seconds_to_fetch:])


@app.route('/api/speed_chart_data')
def get_speed_chart_data_api():
    time_range = request.args.get('range', 'last_1_hour')
    conn = None
    try:
        is_mysql = db_manager.db_type == 'mysql'
        ph = placeholder()
        conn = db_manager._get_connection()
        cursor = conn.cursor(dictionary=is_mysql)

        start_dt, end_dt, group_by_format = get_date_range_and_grouping(
            time_range, for_speed=True)
        time_group_fn = get_time_group_fn(db_manager.db_type, group_by_format)

        query = f"""
            SELECT
                {time_group_fn} AS time_group,
                AVG(qb_upload_speed) AS qb_ul_speed,
                AVG(qb_download_speed) AS qb_dl_speed,
                AVG(tr_upload_speed) AS tr_ul_speed,
                AVG(tr_download_speed) AS tr_dl_speed
            FROM traffic_stats
            WHERE stat_datetime >= {ph}
        """
        params = [start_dt.strftime('%Y-%m-%d %H:%M:%S')]

        if end_dt:
            query += f" AND stat_datetime < {ph}"
            params.append(end_dt.strftime('%Y-%m-%d %H:%M:%S'))

        query += " GROUP BY time_group ORDER BY time_group"

        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()

        labels = [r['time_group'] for r in rows]
        datasets = [{
            "time": r['time_group'],
            "qb_ul_speed": float(r['qb_ul_speed'] or 0),
            "qb_dl_speed": float(r['qb_dl_speed'] or 0),
            "tr_ul_speed": float(r['tr_ul_speed'] or 0),
            "tr_dl_speed": float(r['tr_dl_speed'] or 0)
        } for r in rows]

        return jsonify({"labels": labels, "datasets": datasets})

    except Exception as e:
        logging.error(f"Error in get_speed_chart_data_api: {e}", exc_info=True)
        return jsonify({"error": "Failed to fetch speed chart data"}), 500
    finally:
        if conn:
            cursor.close()
            conn.close()


@app.route('/api/downloader_info')
def get_downloader_info_api():
    cfg = load_config()
    info = {
        'qbittorrent': {
            'enabled': cfg.get('qbittorrent', {}).get('enabled', False),
            'status': '未配置',
            'details': {}
        },
        'transmission': {
            'enabled': cfg.get('transmission', {}).get('enabled', False),
            'status': '未配置',
            'details': {}
        }
    }
    conn = db_manager._get_connection()
    is_mysql = db_manager.db_type == 'mysql'
    cursor = conn.cursor(dictionary=is_mysql)
    cursor.execute(
        'SELECT SUM(qb_downloaded) as qb_dl, SUM(qb_uploaded) as qb_ul, SUM(tr_downloaded) as tr_dl, SUM(tr_uploaded) as tr_ul FROM traffic_stats'
    )
    totals = cursor.fetchone() or {
        'qb_dl': 0,
        'qb_ul': 0,
        'tr_dl': 0,
        'tr_ul': 0
    }

    today_query = f"SELECT SUM(qb_downloaded) as qb_dl, SUM(qb_uploaded) as qb_ul, SUM(tr_downloaded) as tr_dl, SUM(tr_uploaded) as tr_ul FROM traffic_stats WHERE stat_datetime >= {placeholder()}"
    cursor.execute(today_query,
                   (datetime.now().strftime('%Y-%m-%d 00:00:00'), ))
    today_stats = cursor.fetchone() or {
        'qb_dl': 0,
        'qb_ul': 0,
        'tr_dl': 0,
        'tr_ul': 0
    }

    cursor.close()
    conn.close()

    if info['qbittorrent']['enabled']:
        details = {
            '今日下载量': DataTracker.format_bytes(today_stats.get('qb_dl')),
            '今日上传量': DataTracker.format_bytes(today_stats.get('qb_ul')),
            '累计下载量': DataTracker.format_bytes(totals.get('qb_dl')),
            '累计上传量': DataTracker.format_bytes(totals.get('qb_ul'))
        }
        try:
            client = Client(**{
                k: v
                for k, v in cfg['qbittorrent'].items() if k != 'enabled'
            })
            client.auth_log_in()
            details['版本'] = client.app.version
            info['qbittorrent']['status'] = '已连接'
        except Exception as e:
            info['qbittorrent']['status'] = '连接失败'
            details['错误信息'] = str(e)
        info['qbittorrent']['details'] = details
    if info['transmission']['enabled']:
        details = {
            '今日下载量': DataTracker.format_bytes(today_stats.get('tr_dl')),
            '今日上传量': DataTracker.format_bytes(today_stats.get('tr_ul')),
            '累计下载量': DataTracker.format_bytes(totals.get('tr_dl')),
            '累计上传量': DataTracker.format_bytes(totals.get('tr_ul'))
        }
        try:
            client = TrClient(**{
                k: v
                for k, v in cfg['transmission'].items() if k != 'enabled'
            })
            details['版本'] = client.get_session().version
            info['transmission']['status'] = '已连接'
        except Exception as e:
            info['transmission']['status'] = '连接失败'
            details['错误信息'] = str(e)
        info['transmission']['details'] = details
    return jsonify(info)


@app.route('/api/data')
def get_data_api():
    cfg_local = load_config()
    ui_settings = cfg_local.setdefault('ui_settings', {})
    try:
        page = int(request.args.get('page', 1))
        page_size_req = request.args.get('pageSize')
    except (TypeError, ValueError):
        page, page_size_req = 1, None

    page_size_config = ui_settings.get('page_size', 50)
    if page_size_req:
        try:
            page_size = int(page_size_req)
            if page_size != page_size_config:
                ui_settings['page_size'] = page_size
                save_config(cfg_local)
        except (TypeError, ValueError):
            page_size = page_size_config
    else:
        page_size = page_size_config

    try:
        path_filters = json.loads(request.args.get('path_filters', '[]'))
        state_filters = json.loads(request.args.get('state_filters', '[]'))
    except json.JSONDecodeError:
        path_filters, state_filters = [], []

    site_filter_existence = request.args.get('siteFilterExistence', 'all')
    site_filter_name = request.args.get('siteFilterName')
    name_search = request.args.get('nameSearch', '').lower()
    sort_prop = request.args.get('sortProp')
    sort_order = request.args.get('sortOrder')

    conn = None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        cursor.execute("SELECT * FROM torrents")
        torrents_raw = [dict(row) for row in cursor.fetchall()]

        agg_torrents = defaultdict(
            lambda: {
                'name':
                '',
                'save_path':
                '',
                'size':
                0,
                'progress':
                0,
                'state':
                set(),
                'sites':
                defaultdict(lambda: {
                    'qb_ul': 0,
                    'tr_ul': 0,
                    'comment': ''
                }),
                'qb_uploaded':
                0,
                'tr_uploaded':
                0
            })

        for t in torrents_raw:
            name = t['name']
            agg = agg_torrents[name]
            agg['name'] = name
            if not agg['save_path']: agg['save_path'] = t.get('save_path', '')
            if not agg['size']: agg['size'] = t.get('size', 0)
            agg['progress'] = max(agg['progress'], t.get('progress', 0))
            agg['state'].add(t.get('state', 'N/A'))
            agg['qb_uploaded'] += t.get('qb_uploaded', 0)
            agg['tr_uploaded'] += t.get('tr_uploaded', 0)

            site_name = t.get('sites')
            detail_url = t.get('details')

            if site_name:
                agg['sites'][site_name]['qb_ul'] += t.get('qb_uploaded', 0)
                agg['sites'][site_name]['tr_ul'] += t.get('tr_uploaded', 0)
                agg['sites'][site_name]['comment'] = detail_url

        final_torrent_list = []
        for name, data in agg_torrents.items():
            data['state'] = ', '.join(sorted(list(data['state'])))
            data['size_formatted'] = DataTracker.format_bytes(data['size'])
            data['qb_uploaded_formatted'] = DataTracker.format_bytes(
                data['qb_uploaded'])
            data['tr_uploaded_formatted'] = DataTracker.format_bytes(
                data['tr_uploaded'])
            data['total_uploaded'] = data['qb_uploaded'] + data['tr_uploaded']
            data['total_uploaded_formatted'] = DataTracker.format_bytes(
                data['total_uploaded'])
            final_torrent_list.append(data)

        filtered_list = final_torrent_list
        if name_search:
            filtered_list = [
                t for t in filtered_list if name_search in t['name'].lower()
            ]
        if path_filters:
            filtered_list = [
                t for t in filtered_list if t.get('save_path') in path_filters
            ]
        if state_filters:
            filtered_list = [
                t for t in filtered_list
                for s in t.get('state', '').split(', ') if s in state_filters
            ]
        if site_filter_existence != 'all' and site_filter_name:
            if site_filter_existence == 'exists':
                filtered_list = [
                    t for t in filtered_list
                    if site_filter_name in t.get('sites', {})
                ]
            elif site_filter_existence == 'not-exists':
                filtered_list = [
                    t for t in filtered_list
                    if site_filter_name not in t.get('sites', {})
                ]

        if sort_prop and sort_order:
            reverse = sort_order == 'descending'
            sort_key_map = {
                'size_formatted': 'size',
                'progress': 'progress',
                'qb_uploaded_formatted': 'qb_uploaded',
                'tr_uploaded_formatted': 'tr_uploaded',
                'total_uploaded_formatted': 'total_uploaded'
            }
            sort_key = sort_key_map.get(sort_prop)
            if sort_key:
                filtered_list.sort(key=lambda x: x.get(sort_key, 0),
                                   reverse=reverse)
            else:
                filtered_list.sort(key=cmp_to_key(custom_sort_compare),
                                   reverse=reverse)
        else:
            filtered_list.sort(key=cmp_to_key(custom_sort_compare))

        total_items = len(filtered_list)
        paginated_data = filtered_list[(page - 1) * page_size:page * page_size]

        unique_paths = sorted(
            list(
                set(row['save_path'] for row in torrents_raw
                    if row['save_path'])))
        all_states = set()
        for row in torrents_raw:
            all_states.add(row['state'])
        unique_states = sorted(list(all_states))

        cursor.execute(
            "SELECT DISTINCT sites FROM torrents WHERE sites IS NOT NULL AND sites != ''"
        )
        all_discovered_sites = sorted(
            [row['sites'] for row in cursor.fetchall()])

        _, site_link_rules_from_db = load_site_maps_from_db(db_manager)

        return jsonify({
            'data':
            paginated_data,
            'total':
            total_items,
            'page':
            page,
            'pageSize':
            page_size,
            'unique_paths':
            unique_paths,
            'unique_states':
            unique_states,
            'all_discovered_sites':
            all_discovered_sites,
            'site_link_rules':
            site_link_rules_from_db,
            'active_path_filters':
            ui_settings.get('active_path_filters', []),
            'error':
            None
        })

    except Exception as e:
        logging.error(f"Error in get_data_api: {e}", exc_info=True)
        return jsonify({"error": "从数据库获取种子数据失败"}), 500
    finally:
        if conn:
            cursor.close()
            conn.close()


@app.route('/api/refresh_data', methods=['POST'])
def refresh_data_api():
    try:
        Thread(target=data_tracker_thread._update_torrents_in_db).start()
        return jsonify({"message": "后台刷新已触发"}), 202
    except Exception as e:
        logging.error(f"Failed to trigger refresh: {e}")
        return jsonify({"error": "触发刷新失败"}), 500


@app.route('/api/site_stats')
def get_site_stats_api():
    """
    新增的 API 端点：按站点聚合种子体积和数量。
    *** 最终修正版：使用 SQL 直接进行精确的去重和聚合 ***
    """
    conn = None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        is_mysql = db_manager.db_type == 'mysql'

        if is_mysql:
            query = """
                SELECT
                    sites,
                    SUM(size) as total_size,
                    COUNT(name) as torrent_count
                FROM
                    (SELECT DISTINCT name, size, sites FROM torrents WHERE sites IS NOT NULL AND sites != '') AS unique_torrents
                GROUP BY
                    sites;
            """
            cursor.execute(query)
        else:  # SQLite
            query = """
                SELECT
                    sites,
                    SUM(size) as total_size,
                    COUNT(name) as torrent_count
                FROM
                    (SELECT name, size, sites FROM torrents WHERE sites IS NOT NULL AND sites != '' GROUP BY name) AS unique_torrents
                GROUP BY
                    sites;
            """
            cursor.execute(query)

        rows = cursor.fetchall()

        # 直接构建适合表格的JSON数组结构
        results = sorted([{
            "site_name": row['sites'],
            "total_size": int(row['total_size'] or 0),
            "torrent_count": int(row['torrent_count'] or 0)
        } for row in rows],
                         key=lambda x: x['site_name'])

        return jsonify(results)  # <--- 关键：这里直接返回一个数组

    except Exception as e:
        logging.error(f"Error in get_site_stats_api: {e}", exc_info=True)
        return jsonify({"error": "从数据库获取站点统计数据失败"}), 500
    finally:
        if conn:
            cursor.close()
            conn.close()


@app.route('/api/save_filters', methods=['POST'])
def save_filters_api():
    data = request.get_json()
    cfg_local = load_config()
    cfg_local.setdefault('ui_settings', {})
    if 'paths' in data:
        cfg_local['ui_settings']['active_path_filters'] = data['paths']
    save_config(cfg_local)
    return jsonify({"message": "设置已保存"})


if __name__ == '__main__':
    logging.info("Starting Flask development server as a pure API backend...")
    # 添加 use_reloader=False 来防止调试模式下启动两个进程
    app.run(host='0.0.0.0', port=15001, debug=True, use_reloader=False)
