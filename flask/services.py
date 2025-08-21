# services.py

import collections
import logging
import time
from datetime import datetime
from threading import Thread, Lock
from qbittorrentapi import Client
from transmission_rpc import Client as TrClient

from utils import _parse_hostname_from_url, _extract_core_domain, _extract_url_from_comment, format_state, format_bytes

CACHE_LOCK = Lock()
data_tracker_thread = None


def load_site_maps_from_db(db_manager):
    """从数据库加载站点和发布组的映射关系。"""
    core_domain_map, link_rules, group_to_site_map_lower = {}, {}, {}
    conn = None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        cursor.execute(
            "SELECT nickname, base_url, special_tracker_domain, `group` FROM sites"
        )
        for row in cursor.fetchall():
            nickname = row['nickname']
            base_url = row['base_url']
            special_tracker = row['special_tracker_domain']
            groups_str = row['group']

            if nickname and base_url:
                link_rules[nickname] = {"base_url": base_url.strip()}

                if groups_str:
                    for group_name in groups_str.split(','):
                        clean_group_name = group_name.strip()
                        if clean_group_name:
                            group_to_site_map_lower[
                                clean_group_name.lower()] = {
                                    'original_case': clean_group_name,
                                    'site': nickname
                                }

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

        # 不再在此处记录日志，避免日志刷屏
    except Exception as e:
        logging.error(f"无法从数据库加载站点信息: {e}", exc_info=True)
    finally:
        if conn:
            if 'cursor' in locals() and cursor:
                cursor.close()
            conn.close()

    return core_domain_map, link_rules, group_to_site_map_lower


class DataTracker(Thread):
    """一个后台线程，定期从客户端获取统计信息和种子。"""

    def __init__(self, db_manager, config_manager, interval=1):
        super().__init__(daemon=True, name="DataTracker")
        self.db_manager = db_manager
        self.config_manager = config_manager
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
        self.TORRENT_UPDATE_INTERVAL = 900

    def run(self):
        """数据获取线程的主循环。"""
        logging.info(
            f"DataTracker 线程已启动。流量更新间隔: {self.interval}秒, 种子列表更新间隔: {self.TORRENT_UPDATE_INTERVAL}秒。"
        )
        time.sleep(5)
        try:
            config = self.config_manager.get()
            if config.get('qbittorrent', {}).get('enabled') or config.get(
                    'transmission', {}).get('enabled'):
                self._update_torrents_in_db()
            else:
                logging.info("所有下载器均未启用，跳过初始种子更新。")
        except Exception as e:
            logging.error(f"初始种子数据库更新失败: {e}", exc_info=True)

        while self._is_running:
            start_time = time.monotonic()
            try:
                self._fetch_and_buffer_stats()
                self.torrent_update_counter += self.interval
                if self.torrent_update_counter >= self.TORRENT_UPDATE_INTERVAL:
                    self._update_torrents_in_db()
                    self.torrent_update_counter = 0
            except Exception as e:
                logging.error(f"DataTracker 循环出错: {e}", exc_info=True)
            elapsed = time.monotonic() - start_time
            time.sleep(max(0, self.interval - elapsed))

    def _fetch_and_buffer_stats(self):
        """从客户端获取速度和会话数据并进行缓冲。"""
        config = self.config_manager.get()
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

        qb_enabled = config.get('qbittorrent', {}).get('enabled', False)
        tr_enabled = config.get('transmission', {}).get('enabled', False)

        if not qb_enabled and not tr_enabled:
            time.sleep(self.interval)
            return

        if qb_enabled:
            try:
                client = Client(
                    **{
                        k: v
                        for k, v in config['qbittorrent'].items()
                        if k != 'enabled'
                    })
                client.auth_log_in()
                info = client.transfer_info()
                current_data.update({
                    'qb_dl_speed':
                    int(getattr(info, 'dl_info_speed', 0)),
                    'qb_ul_speed':
                    int(getattr(info, 'up_info_speed', 0)),
                    'qb_dl':
                    int(getattr(info, 'dl_info_data', 0)),
                    'qb_ul':
                    int(getattr(info, 'up_info_data', 0))
                })
            except Exception as e:
                logging.warning(f"无法获取 qB 统计信息: {e}")
        if tr_enabled:
            try:
                client = TrClient(
                    **{
                        k: v
                        for k, v in config['transmission'].items()
                        if k != 'enabled'
                    })
                stats = client.session_stats()
                current_data.update({
                    'tr_dl_speed':
                    int(getattr(stats, 'download_speed', 0)),
                    'tr_ul_speed':
                    int(getattr(stats, 'upload_speed', 0)),
                    'tr_dl':
                    int(stats.cumulative_stats.downloaded_bytes),
                    'tr_ul':
                    int(stats.cumulative_stats.uploaded_bytes)
                })
            except Exception as e:
                logging.warning(f"无法获取 Tr 统计信息: {e}")

        with CACHE_LOCK:
            self.latest_speeds = {
                k: v
                for k, v in current_data.items() if 'speed' in k
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
        """将缓冲的流量数据批量写入数据库。"""
        if not buffer: return

        conn = None
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)
            is_mysql = self.db_manager.db_type == 'mysql'

            qb_state_sql = 'SELECT last_session_dl, last_session_ul FROM downloader_state WHERE name = %s' if is_mysql else 'SELECT last_session_dl, last_session_ul FROM downloader_state WHERE name = ?'
            tr_state_sql = 'SELECT last_cumulative_dl, last_cumulative_ul FROM downloader_state WHERE name = %s' if is_mysql else 'SELECT last_cumulative_dl, last_cumulative_ul FROM downloader_state WHERE name = ?'

            cursor.execute(qb_state_sql, ('qbittorrent', ))
            qb_row = cursor.fetchone()
            last_qb_dl = int(qb_row['last_session_dl']) if qb_row else 0
            last_qb_ul = int(qb_row['last_session_ul']) if qb_row else 0

            cursor.execute(tr_state_sql, ('transmission', ))
            tr_row = cursor.fetchone()
            last_tr_dl = int(tr_row['last_cumulative_dl']) if tr_row else 0
            last_tr_ul = int(tr_row['last_cumulative_ul']) if tr_row else 0

            params_to_insert = []
            for data_point in buffer:
                current_qb_dl, current_qb_ul = data_point['qb_dl'], data_point[
                    'qb_ul']
                qb_dl_inc = current_qb_dl if current_qb_dl < last_qb_dl else current_qb_dl - last_qb_dl
                qb_ul_inc = current_qb_ul if current_qb_ul < last_qb_ul else current_qb_ul - last_qb_ul
                tr_dl_inc = data_point['tr_dl'] - last_tr_dl
                tr_ul_inc = data_point['tr_ul'] - last_tr_ul
                params_to_insert.append(
                    (data_point['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                     max(0, qb_dl_inc), max(0, qb_ul_inc), max(0, tr_dl_inc),
                     max(0, tr_ul_inc), data_point['qb_dl_speed'],
                     data_point['qb_ul_speed'], data_point['tr_dl_speed'],
                     data_point['tr_ul_speed']))
                last_qb_dl, last_qb_ul = current_qb_dl, current_qb_ul
                last_tr_dl, last_tr_ul = data_point['tr_dl'], data_point[
                    'tr_ul']

            if params_to_insert:
                if is_mysql:
                    sql_insert = '''INSERT INTO traffic_stats (stat_datetime, qb_downloaded, qb_uploaded, tr_downloaded, tr_uploaded, qb_download_speed, qb_upload_speed, tr_download_speed, tr_upload_speed) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE qb_downloaded = VALUES(qb_downloaded), qb_uploaded = VALUES(qb_uploaded), tr_downloaded = VALUES(tr_downloaded), tr_uploaded = VALUES(tr_uploaded), qb_download_speed = VALUES(qb_download_speed), qb_upload_speed = VALUES(qb_upload_speed), tr_download_speed = VALUES(tr_download_speed), tr_upload_speed = VALUES(tr_upload_speed)'''
                else:
                    sql_insert = '''INSERT INTO traffic_stats (stat_datetime, qb_downloaded, qb_uploaded, tr_downloaded, tr_uploaded, qb_download_speed, qb_upload_speed, tr_download_speed, tr_upload_speed) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(stat_datetime) DO UPDATE SET qb_downloaded = excluded.qb_downloaded, qb_uploaded = excluded.qb_uploaded, tr_downloaded = excluded.tr_downloaded, tr_uploaded = excluded.tr_uploaded, qb_download_speed = excluded.qb_download_speed, qb_upload_speed = excluded.qb_upload_speed, tr_download_speed = excluded.tr_download_speed, tr_upload_speed = excluded.tr_upload_speed'''
                cursor.executemany(sql_insert, params_to_insert)

            final_data_point = buffer[-1]
            update_qb_sql = "UPDATE downloader_state SET last_session_dl = %s, last_session_ul = %s WHERE name = %s" if is_mysql else "UPDATE downloader_state SET last_session_dl = ?, last_session_ul = ? WHERE name = ?"
            update_tr_sql = "UPDATE downloader_state SET last_cumulative_dl = %s, last_cumulative_ul = %s WHERE name = %s" if is_mysql else "UPDATE downloader_state SET last_cumulative_dl = ?, last_cumulative_ul = ? WHERE name = ?"
            cursor.execute(update_qb_sql,
                           (final_data_point['qb_dl'],
                            final_data_point['qb_ul'], 'qbittorrent'))
            cursor.execute(update_tr_sql,
                           (final_data_point['tr_dl'],
                            final_data_point['tr_ul'], 'transmission'))

            conn.commit()
        except Exception as e:
            logging.error(f"将流量缓冲刷新到数据库失败: {e}", exc_info=True)
            if conn: conn.rollback()
        finally:
            if conn:
                cursor.close()
                conn.close()

    def _update_torrents_in_db(self):
        """从客户端获取完整的种子列表并批量更新数据库。"""
        logging.info("开始更新数据库中的种子...")
        config = self.config_manager.get()
        core_domain_map, _, group_to_site_map_lower = load_site_maps_from_db(
            self.db_manager)

        all_current_hashes = set()
        is_mysql = self.db_manager.db_type == 'mysql'
        conn = None

        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            params_to_update_qb = []
            params_to_update_tr = []

            for client_name, cfg in config.items():
                if client_name not in ['qbittorrent', 'transmission'
                                       ] or not cfg.get('enabled'):
                    continue

                torrents_list = []
                try:
                    if client_name == 'qbittorrent':
                        q = Client(**{
                            k: v
                            for k, v in cfg.items() if k != 'enabled'
                        })
                        q.auth_log_in()
                        torrents_list = q.torrents_info(status_filter='all')
                    elif client_name == 'transmission':
                        tr = TrClient(**{
                            k: v
                            for k, v in cfg.items() if k != 'enabled'
                        })
                        fields = [
                            'id', 'name', 'hashString', 'downloadDir',
                            'totalSize', 'status', 'comment', 'trackers',
                            'percentDone', 'uploadedEver'
                        ]
                        torrents_list = tr.get_torrents(arguments=fields)
                except Exception as e:
                    logging.error(f"未能连接或从 {client_name} 获取数据: {e}")
                    continue

                logging.info(
                    f"从 {client_name} 成功获取到 {len(torrents_list)} 个种子。")

                for t in torrents_list:
                    t_info = {
                        'name':
                        t.name,
                        'hash':
                        t.hash
                        if client_name == 'qbittorrent' else t.hash_string,
                        'save_path':
                        t.save_path
                        if client_name == 'qbittorrent' else t.download_dir,
                        'size':
                        t.size
                        if client_name == 'qbittorrent' else t.total_size,
                        'progress':
                        t.progress
                        if client_name == 'qbittorrent' else t.percent_done,
                        'state':
                        t.state if client_name == 'qbittorrent' else t.status,
                        'comment':
                        t.comment,
                        'trackers':
                        t.trackers if client_name == 'qbittorrent' else [{
                            'url':
                            tracker.get('announce')
                        } for tracker in t.trackers],
                        'uploaded':
                        t.uploaded
                        if client_name == 'qbittorrent' else t.uploaded_ever
                    }
                    all_current_hashes.add(t_info['hash'])

                    site_nickname = None
                    if t_info['trackers']:
                        for tracker_entry in t_info['trackers']:
                            hostname = _parse_hostname_from_url(
                                tracker_entry.get('url'))
                            core_domain = _extract_core_domain(hostname)
                            if core_domain in core_domain_map:
                                site_nickname = core_domain_map[core_domain]
                                break

                    torrent_group = None
                    name_lower = t_info['name'].lower()
                    found_matches = [
                        group_info['original_case'] for group_lower, group_info
                        in group_to_site_map_lower.items()
                        if group_lower in name_lower
                    ]
                    if found_matches:
                        torrent_group = sorted(found_matches,
                                               key=len,
                                               reverse=True)[0]

                    params = (t_info['hash'], t_info['name'],
                              t_info['save_path'], t_info['size'],
                              round(t_info['progress'] * 100, 1),
                              format_state(t_info['state']), site_nickname,
                              _extract_url_from_comment(t_info['comment']),
                              torrent_group, t_info['uploaded'], now_str)
                    if client_name == 'qbittorrent':
                        params_to_update_qb.append(params)
                    else:  # transmission
                        params_to_update_tr.append(params)

            # --- 批量更新 ---
            if params_to_update_qb:
                if is_mysql:
                    sql_qb = '''INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, `group`, qb_uploaded, last_seen) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE name=VALUES(name), save_path=VALUES(save_path), size=VALUES(size), progress=VALUES(progress), state=VALUES(state), sites=VALUES(sites), details=VALUES(details), `group`=VALUES(`group`), qb_uploaded=GREATEST(VALUES(qb_uploaded), torrents.qb_uploaded), last_seen=VALUES(last_seen)'''
                else:
                    sql_qb = '''INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, `group`, qb_uploaded, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(hash) DO UPDATE SET name=excluded.name, save_path=excluded.save_path, size=excluded.size, progress=excluded.progress, state=excluded.state, sites=excluded.sites, details=excluded.details, `group`=excluded.`group`, qb_uploaded=max(excluded.qb_uploaded, torrents.qb_uploaded), last_seen=excluded.last_seen'''
                cursor.executemany(sql_qb, params_to_update_qb)
                logging.info(
                    f"已批量处理 {len(params_to_update_qb)} 个 qBittorrent 种子。")

            if params_to_update_tr:
                if is_mysql:
                    sql_tr = '''INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, `group`, tr_uploaded, last_seen) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE name=VALUES(name), save_path=VALUES(save_path), size=VALUES(size), progress=VALUES(progress), state=VALUES(state), sites=VALUES(sites), details=VALUES(details), `group`=VALUES(`group`), tr_uploaded=GREATEST(VALUES(tr_uploaded), torrents.tr_uploaded), last_seen=VALUES(last_seen)'''
                else:
                    sql_tr = '''INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, `group`, tr_uploaded, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(hash) DO UPDATE SET name=excluded.name, save_path=excluded.save_path, size=excluded.size, progress=excluded.progress, state=excluded.state, sites=excluded.sites, details=excluded.details, `group`=excluded.`group`, tr_uploaded=max(excluded.tr_uploaded, torrents.tr_uploaded), last_seen=excluded.last_seen'''
                cursor.executemany(sql_tr, params_to_update_tr)
                logging.info(
                    f"已批量处理 {len(params_to_update_tr)} 个 Transmission 种子。")

            if all_current_hashes:
                placeholders = ', '.join(['%s' if is_mysql else '?'] *
                                         len(all_current_hashes))
                sql_delete = f"DELETE FROM torrents WHERE hash NOT IN ({placeholders})"
                # 使用不带字典的游标进行删除操作以获取正确的 rowcount
                non_dict_cursor = conn.cursor()
                non_dict_cursor.execute(sql_delete, tuple(all_current_hashes))
                logging.info(f"从数据库中移除了 {non_dict_cursor.rowcount} 个陈旧的种子。")
                non_dict_cursor.close()
            else:
                cursor.execute("DELETE FROM torrents")
                logging.info("在任何客户端中都未找到种子，已清空 torrents 表。")

            conn.commit()
            logging.info("种子数据库更新周期成功完成。")
        except Exception as e:
            logging.error(f"更新数据库中的种子失败: {e}", exc_info=True)
            if conn: conn.rollback()
        finally:
            if conn:
                if 'cursor' in locals() and cursor:
                    cursor.close()
                conn.close()

    def stop(self):
        """停止线程并刷新所有剩余数据。"""
        logging.info("正在停止 DataTracker 线程...")
        self._is_running = False
        with self.traffic_buffer_lock:
            if self.traffic_buffer:
                self._flush_traffic_buffer_to_db(self.traffic_buffer)


def start_data_tracker(db_manager, config_manager):
    """初始化并启动全局 DataTracker 线程实例。"""
    global data_tracker_thread
    if data_tracker_thread is None or not data_tracker_thread.is_alive():
        data_tracker_thread = DataTracker(db_manager, config_manager)
        data_tracker_thread.start()
        logging.info("已创建并启动新的 DataTracker 实例。")
    return data_tracker_thread


def stop_data_tracker():
    """停止并清理当前的 DataTracker 线程实例。"""
    global data_tracker_thread
    if data_tracker_thread and data_tracker_thread.is_alive():
        data_tracker_thread.stop()
        data_tracker_thread.join(timeout=10)
        logging.info("DataTracker 线程已停止。")
    data_tracker_thread = None
