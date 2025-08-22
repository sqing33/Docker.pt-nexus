# services.py

import collections
import logging
import time
from datetime import datetime
from threading import Thread, Lock
from urllib.parse import urlparse
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

    except Exception as e:
        logging.error(f"无法从数据库加载站点信息: {e}", exc_info=True)
    finally:
        if conn:
            if 'cursor' in locals() and cursor:
                cursor.close()
            conn.close()

    return core_domain_map, link_rules, group_to_site_map_lower


def _prepare_api_config(downloader_config):
    """
    [NEW] 准备用于API客户端的配置字典，智能处理host和port。
    """
    # 移除我们自己的元数据字段
    api_config = {
        k: v
        for k, v in downloader_config.items()
        if k not in ['id', 'name', 'type', 'enabled']
    }

    if downloader_config['type'] == 'transmission':
        # 从 host 字段解析出 ip 和 port
        if api_config.get('host'):
            # 为 urlparse 添加一个临时的 scheme
            parsed_url = urlparse(f"http://{api_config['host']}")
            api_config['host'] = parsed_url.hostname
            api_config['port'] = parsed_url.port or 9091  # 如果未指定端口，使用默认值

    elif downloader_config['type'] == 'qbittorrent':
        # qb 的 host 字段应为 ip:port，库会自己处理。我们只需确保不传递多余的 port 字段。
        if 'port' in api_config:
            del api_config['port']

    return api_config


class DataTracker(Thread):
    """一个后台线程，定期从所有已配置的客户端获取统计信息和种子。"""

    def __init__(self, db_manager, config_manager, interval=1):
        super().__init__(daemon=True, name="DataTracker")
        self.db_manager = db_manager
        self.config_manager = config_manager
        self.interval = interval
        self._is_running = True
        self.TRAFFIC_BATCH_WRITE_SIZE = 60
        self.traffic_buffer = []
        self.traffic_buffer_lock = Lock()
        self.latest_speeds = {}
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
            if any(d.get('enabled') for d in config.get('downloaders', [])):
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
        """从所有启用的客户端获取速度和会话数据并进行缓冲。"""
        config = self.config_manager.get()
        enabled_downloaders = [
            d for d in config.get('downloaders', []) if d.get('enabled')
        ]

        if not enabled_downloaders:
            time.sleep(self.interval)
            return

        current_timestamp = datetime.now()

        data_points = []
        latest_speeds_update = {}

        for downloader in enabled_downloaders:
            downloader_id = downloader['id']
            api_config = _prepare_api_config(downloader)

            data_point = {
                'downloader_id': downloader_id,
                'session_dl': 0,
                'session_ul': 0,
                'dl_speed': 0,
                'ul_speed': 0
            }

            try:
                if downloader['type'] == 'qbittorrent':
                    client = Client(**api_config)
                    client.auth_log_in()
                    info = client.transfer_info()
                    data_point.update({
                        'dl_speed':
                        int(getattr(info, 'dl_info_speed', 0)),
                        'ul_speed':
                        int(getattr(info, 'up_info_speed', 0)),
                        'session_dl':
                        int(getattr(info, 'dl_info_data', 0)),
                        'session_ul':
                        int(getattr(info, 'up_info_data', 0))
                    })
                elif downloader['type'] == 'transmission':
                    client = TrClient(**api_config)
                    stats = client.session_stats()
                    data_point.update({
                        'dl_speed':
                        int(getattr(stats, 'download_speed', 0)),
                        'ul_speed':
                        int(getattr(stats, 'upload_speed', 0)),
                        'session_dl':
                        int(stats.cumulative_stats.downloaded_bytes),
                        'session_ul':
                        int(stats.cumulative_stats.uploaded_bytes)
                    })

                latest_speeds_update[downloader_id] = {
                    'name': downloader['name'],
                    'type': downloader['type'],
                    'enabled': True,
                    'upload_speed': data_point['ul_speed'],
                    'download_speed': data_point['dl_speed']
                }
                data_points.append(data_point)

            except Exception as e:
                logging.warning(f"无法从客户端 '{downloader['name']}' 获取统计信息: {e}")
                latest_speeds_update[downloader_id] = {
                    'name': downloader['name'],
                    'type': downloader['type'],
                    'enabled': True,
                    'upload_speed': 0,
                    'download_speed': 0
                }

        with CACHE_LOCK:
            self.latest_speeds = latest_speeds_update
            # --- MODIFICATION START ---
            # 不再缓存总速度，而是缓存每个客户端的速度
            speeds_for_buffer = {
                downloader_id: {
                    'upload_speed': data.get('upload_speed', 0),
                    'download_speed': data.get('download_speed', 0)
                }
                for downloader_id, data in latest_speeds_update.items()
            }
            self.recent_speeds_buffer.append({
                'timestamp': current_timestamp,
                'speeds': speeds_for_buffer,
            })
            # --- MODIFICATION END ---

        buffer_to_flush = []
        with self.traffic_buffer_lock:
            self.traffic_buffer.append({
                'timestamp': current_timestamp,
                'points': data_points
            })
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

            cursor.execute(
                'SELECT id, type, last_session_dl, last_session_ul, last_cumulative_dl, last_cumulative_ul FROM downloader_clients'
            )
            last_states = {row['id']: dict(row) for row in cursor.fetchall()}

            params_to_insert = []
            for entry in buffer:
                timestamp_str = entry['timestamp'].strftime(
                    '%Y-%m-%d %H:%M:%S')
                for data_point in entry['points']:
                    client_id = data_point['downloader_id']
                    last_state = last_states.get(client_id)
                    if not last_state: continue

                    dl_inc, ul_inc = 0, 0
                    if last_state['type'] == 'qbittorrent':
                        last_dl, last_ul = int(
                            last_state['last_session_dl']), int(
                                last_state['last_session_ul'])
                        current_dl, current_ul = data_point[
                            'session_dl'], data_point['session_ul']
                        dl_inc = current_dl if current_dl < last_dl else current_dl - last_dl
                        ul_inc = current_ul if current_ul < last_ul else current_ul - last_ul
                        last_state['last_session_dl'], last_state[
                            'last_session_ul'] = current_dl, current_ul
                    elif last_state['type'] == 'transmission':
                        last_dl, last_ul = int(
                            last_state['last_cumulative_dl']), int(
                                last_state['last_cumulative_ul'])
                        current_dl, current_ul = data_point[
                            'session_dl'], data_point['session_ul']
                        dl_inc = current_dl - last_dl
                        ul_inc = current_ul - last_ul
                        last_state['last_cumulative_dl'], last_state[
                            'last_cumulative_ul'] = current_dl, current_ul

                    params_to_insert.append(
                        (timestamp_str, client_id, max(0,
                                                       ul_inc), max(0, dl_inc),
                         data_point['ul_speed'], data_point['dl_speed']))

            if params_to_insert:
                if is_mysql:
                    sql_insert = '''INSERT INTO traffic_stats (stat_datetime, downloader_id, uploaded, downloaded, upload_speed, download_speed) VALUES (%s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE uploaded = VALUES(uploaded), downloaded = VALUES(downloaded), upload_speed = VALUES(upload_speed), download_speed = VALUES(download_speed)'''
                else:
                    sql_insert = '''INSERT INTO traffic_stats (stat_datetime, downloader_id, uploaded, downloaded, upload_speed, download_speed) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(stat_datetime, downloader_id) DO UPDATE SET uploaded = excluded.uploaded, downloaded = excluded.downloaded, upload_speed = excluded.upload_speed, download_speed = excluded.download_speed'''
                cursor.executemany(sql_insert, params_to_insert)

            for client_id, state in last_states.items():
                if state['type'] == 'qbittorrent':
                    sql = "UPDATE downloader_clients SET last_session_dl = %s, last_session_ul = %s WHERE id = %s" if is_mysql else "UPDATE downloader_clients SET last_session_dl = ?, last_session_ul = ? WHERE id = ?"
                    cursor.execute(sql, (state['last_session_dl'],
                                         state['last_session_ul'], client_id))
                elif state['type'] == 'transmission':
                    sql = "UPDATE downloader_clients SET last_cumulative_dl = %s, last_cumulative_ul = %s WHERE id = %s" if is_mysql else "UPDATE downloader_clients SET last_cumulative_dl = ?, last_cumulative_ul = ? WHERE id = ?"
                    cursor.execute(sql,
                                   (state['last_cumulative_dl'],
                                    state['last_cumulative_ul'], client_id))

            conn.commit()
        except Exception as e:
            logging.error(f"将流量缓冲刷新到数据库失败: {e}", exc_info=True)
            if conn: conn.rollback()
        finally:
            if conn:
                cursor.close()
                conn.close()

    def _update_torrents_in_db(self):
        """从所有启用的客户端获取完整的种子列表并批量更新数据库。"""
        logging.info("开始更新数据库中的种子...")
        config = self.config_manager.get()
        enabled_downloaders = [
            d for d in config.get('downloaders', []) if d.get('enabled')
        ]
        if not enabled_downloaders:
            logging.info("没有启用的下载器，跳过种子更新。")
            return

        core_domain_map, _, group_to_site_map_lower = load_site_maps_from_db(
            self.db_manager)

        all_current_hashes = set()
        torrents_to_upsert = {}
        upload_stats_to_upsert = []
        is_mysql = self.db_manager.db_type == 'mysql'

        for downloader in enabled_downloaders:
            downloader_id = downloader['id']
            client_name = downloader['name']
            api_config = _prepare_api_config(downloader)
            torrents_list = []
            try:
                if downloader['type'] == 'qbittorrent':
                    q = Client(**api_config)
                    q.auth_log_in()
                    torrents_list = q.torrents_info(status_filter='all')
                elif downloader['type'] == 'transmission':
                    tr = TrClient(**api_config)
                    fields = [
                        'id', 'name', 'hashString', 'downloadDir', 'totalSize',
                        'status', 'comment', 'trackers', 'percentDone',
                        'uploadedEver'
                    ]
                    torrents_list = tr.get_torrents(arguments=fields)
            except Exception as e:
                logging.error(f"未能从 '{client_name}' 获取数据: {e}")
                continue

            logging.info(f"从 '{client_name}' 成功获取到 {len(torrents_list)} 个种子。")

            for t in torrents_list:
                t_info = self._normalize_torrent_info(t, downloader['type'])
                all_current_hashes.add(t_info['hash'])

                site_nickname = self._find_site_nickname(
                    t_info['trackers'], core_domain_map)
                torrent_group = self._find_torrent_group(
                    t_info['name'], group_to_site_map_lower)

                if t_info['hash'] not in torrents_to_upsert or t_info[
                        'progress'] > torrents_to_upsert[
                            t_info['hash']]['progress']:
                    torrents_to_upsert[t_info['hash']] = {
                        'hash': t_info['hash'],
                        'name': t_info['name'],
                        'save_path': t_info['save_path'],
                        'size': t_info['size'],
                        'progress': round(t_info['progress'] * 100, 1),
                        'state': format_state(t_info['state']),
                        'sites': site_nickname,
                        'details':
                        _extract_url_from_comment(t_info['comment']),
                        'group': torrent_group
                    }

                if t_info['uploaded'] > 0:
                    upload_stats_to_upsert.append(
                        (t_info['hash'], downloader_id, t_info['uploaded']))

        conn = None
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            if torrents_to_upsert:
                params = [(*d.values(), now_str)
                          for d in torrents_to_upsert.values()]
                if is_mysql:
                    sql = '''INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, `group`, last_seen) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE name=VALUES(name), save_path=VALUES(save_path), size=VALUES(size), progress=VALUES(progress), state=VALUES(state), sites=VALUES(sites), details=VALUES(details), `group`=VALUES(`group`), last_seen=VALUES(last_seen)'''
                else:
                    sql = '''INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, `group`, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(hash) DO UPDATE SET name=excluded.name, save_path=excluded.save_path, size=excluded.size, progress=excluded.progress, state=excluded.state, sites=excluded.sites, details=excluded.details, `group`=excluded.`group`, last_seen=excluded.last_seen'''
                cursor.executemany(sql, params)
                logging.info(f"已批量处理 {len(params)} 条种子主信息。")

            if upload_stats_to_upsert:
                if is_mysql:
                    sql_upload = '''INSERT INTO torrent_upload_stats (hash, downloader_id, uploaded) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE uploaded=VALUES(uploaded)'''
                else:
                    sql_upload = '''INSERT INTO torrent_upload_stats (hash, downloader_id, uploaded) VALUES (?, ?, ?) ON CONFLICT(hash, downloader_id) DO UPDATE SET uploaded=excluded.uploaded'''
                cursor.executemany(sql_upload, upload_stats_to_upsert)
                logging.info(f"已批量处理 {len(upload_stats_to_upsert)} 条种子上传数据。")

            if all_current_hashes:
                placeholders = ', '.join(['%s' if is_mysql else '?'] *
                                         len(all_current_hashes))
                sql_delete = f"DELETE FROM torrents WHERE hash NOT IN ({placeholders})"
                non_dict_cursor = conn.cursor()
                non_dict_cursor.execute(sql_delete, tuple(all_current_hashes))
                logging.info(
                    f"从 torrents 表中移除了 {non_dict_cursor.rowcount} 个陈旧的种子。")
                non_dict_cursor.close()
            else:
                cursor.execute("DELETE FROM torrents")
                logging.info("在任何启用的客户端中都未找到种子，已清空 torrents 表。")

            conn.commit()
            logging.info("种子数据库更新周期成功完成。")
        except Exception as e:
            logging.error(f"更新数据库中的种子失败: {e}", exc_info=True)
            if conn: conn.rollback()
        finally:
            if conn:
                if 'cursor' in locals() and cursor: cursor.close()
                conn.close()

    def _normalize_torrent_info(self, t, client_type):
        """将不同客户端的种子对象标准化为统一的字典格式。"""
        if client_type == 'qbittorrent':
            return {
                'name': t.name,
                'hash': t.hash,
                'save_path': t.save_path,
                'size': t.size,
                'progress': t.progress,
                'state': t.state,
                'comment': t.get('comment', ''),
                'trackers': t.trackers,
                'uploaded': t.uploaded
            }
        elif client_type == 'transmission':
            return {
                'name':
                t.name,
                'hash':
                t.hash_string,
                'save_path':
                t.download_dir,
                'size':
                t.total_size,
                'progress':
                t.percent_done,
                'state':
                t.status,
                'comment':
                getattr(t, 'comment', ''),
                'trackers': [{
                    'url': tracker.get('announce')
                } for tracker in t.trackers],
                'uploaded':
                t.uploaded_ever
            }
        return {}

    def _find_site_nickname(self, trackers, core_domain_map):
        """根据 tracker 列表确定站点昵称。"""
        if trackers:
            for tracker_entry in trackers:
                hostname = _parse_hostname_from_url(tracker_entry.get('url'))
                core_domain = _extract_core_domain(hostname)
                if core_domain in core_domain_map:
                    return core_domain_map[core_domain]
        return None

    def _find_torrent_group(self, name, group_to_site_map_lower):
        """根据种子名称确定发布组。"""
        name_lower = name.lower()
        found_matches = [
            group_info['original_case']
            for group_lower, group_info in group_to_site_map_lower.items()
            if group_lower in name_lower
        ]
        if found_matches:
            return sorted(found_matches, key=len, reverse=True)[0]
        return None

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
