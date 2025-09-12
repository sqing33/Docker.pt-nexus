# core/services.py

import collections
import logging
import time
from datetime import datetime
from threading import Thread, Lock
from urllib.parse import urlparse

# 外部库导入
import requests  # <-- [新增] 导入 requests 库，用于手动发送HTTP请求
from qbittorrentapi import Client, exceptions as qb_exceptions
from transmission_rpc import Client as TrClient

# 从项目根目录的 utils 包导入工具函数
from utils import (
    _parse_hostname_from_url,
    _extract_core_domain,
    _extract_url_from_comment,
    format_state,
    format_bytes,
)

# --- 全局变量和锁 ---
CACHE_LOCK = Lock()
data_tracker_thread = None


def load_site_maps_from_db(db_manager):
    """从数据库加载站点和发布组的映射关系。"""
    core_domain_map, link_rules, group_to_site_map_lower = {}, {}, {}
    conn = None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        # 根据数据库类型使用正确的引号
        if db_manager.db_type == "postgresql":
            cursor.execute(
                "SELECT nickname, base_url, special_tracker_domain, \"group\" FROM sites"
            )
        else:
            cursor.execute(
                "SELECT nickname, base_url, special_tracker_domain, `group` FROM sites"
            )
        for row in cursor.fetchall():
            nickname, base_url, special_tracker, groups_str = (
                row["nickname"],
                row["base_url"],
                row["special_tracker_domain"],
                row["group"],
            )
            if nickname and base_url:
                link_rules[nickname] = {"base_url": base_url.strip()}
                if groups_str:
                    for group_name in groups_str.split(","):
                        clean_group_name = group_name.strip()
                        if clean_group_name:
                            group_to_site_map_lower[
                                clean_group_name.lower()] = {
                                    "original_case": clean_group_name,
                                    "site": nickname,
                                }

                base_hostname = _parse_hostname_from_url(f"http://{base_url}")
                if base_hostname:
                    core_domain_map[_extract_core_domain(
                        base_hostname)] = nickname

                if special_tracker:
                    special_hostname = _parse_hostname_from_url(
                        f"http://{special_tracker}")
                    if special_hostname:
                        core_domain_map[_extract_core_domain(
                            special_hostname)] = nickname
    except Exception as e:
        logging.error(f"无法从数据库加载站点信息: {e}", exc_info=True)
    finally:
        if conn:
            if "cursor" in locals() and cursor:
                cursor.close()
            conn.close()
    return core_domain_map, link_rules, group_to_site_map_lower


def _prepare_api_config(downloader_config):
    """准备用于API客户端的配置字典，智能处理host和port。"""
    api_config = {
        k: v
        for k, v in downloader_config.items()
        if k not in ["id", "name", "type", "enabled"]
    }
    if downloader_config["type"] == "transmission":
        if api_config.get("host"):
            host_value = api_config["host"]
            if not host_value.startswith(("http://", "https://")):
                host_value = f"http://{host_value}"
            parsed_url = urlparse(host_value)
            api_config["host"] = parsed_url.hostname
            api_config["port"] = parsed_url.port or 9091
    elif downloader_config["type"] == "qbittorrent" and "port" in api_config:
        del api_config["port"]
    return api_config


class DataTracker(Thread):
    """一个后台线程，定期从所有已配置的客户端获取统计信息和种子。"""

    def __init__(self, db_manager, config_manager):
        super().__init__(daemon=True, name="DataTracker")
        self.db_manager = db_manager
        self.config_manager = config_manager
        config = self.config_manager.get()
        is_realtime_enabled = config.get("realtime_speed_enabled", True)
        self.interval = 1 if is_realtime_enabled else 60
        logging.info(
            f"实时速率显示已 {'启用' if is_realtime_enabled else '禁用'}。数据获取间隔设置为 {self.interval} 秒。"
        )
        self._is_running = True
        TARGET_WRITE_PERIOD_SECONDS = 60
        self.TRAFFIC_BATCH_WRITE_SIZE = max(
            1, TARGET_WRITE_PERIOD_SECONDS // self.interval)
        logging.info(f"数据库批量写入大小设置为 {self.TRAFFIC_BATCH_WRITE_SIZE} 条记录。")
        self.traffic_buffer = []
        self.traffic_buffer_lock = Lock()
        self.latest_speeds = {}
        self.recent_speeds_buffer = collections.deque(
            maxlen=self.TRAFFIC_BATCH_WRITE_SIZE)
        self.torrent_update_counter = 0
        self.TORRENT_UPDATE_INTERVAL = 900
        self.clients = {}
        
        # 数据聚合任务相关变量
        self.aggregation_counter = 0  # 用于计时的计数器
        self.AGGREGATION_INTERVAL = 21600  # 聚合任务的执行间隔（秒），这里是6小时

    def _get_client(self, downloader_config):
        """智能获取或创建并缓存客户端实例，支持自动重连。"""
        client_id = downloader_config['id']
        if client_id in self.clients:
            return self.clients[client_id]

        try:
            logging.info(f"正在为 '{downloader_config['name']}' 创建新的客户端连接...")
            api_config = _prepare_api_config(downloader_config)

            if downloader_config['type'] == 'qbittorrent':
                client = Client(**api_config)
                client.auth_log_in()
            elif downloader_config['type'] == 'transmission':
                client = TrClient(**api_config)
                client.get_session()

            self.clients[client_id] = client
            logging.info(f"客户端 '{downloader_config['name']}' 连接成功并已缓存。")
            return client
        except Exception as e:
            logging.error(f"为 '{downloader_config['name']}' 初始化客户端失败: {e}")
            if client_id in self.clients:
                del self.clients[client_id]
            return None

    def run(self):
        logging.info(
            f"DataTracker 线程已启动。流量更新间隔: {self.interval}秒, 种子列表更新间隔: {self.TORRENT_UPDATE_INTERVAL}秒。"
        )
        time.sleep(5)
        try:
            config = self.config_manager.get()
            if any(d.get("enabled") for d in config.get("downloaders", [])):
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
                    self.clients.clear()
                    logging.info("客户端连接缓存已清空，将为种子更新任务重建连接。")
                    self._update_torrents_in_db()
                    self.torrent_update_counter = 0
                    
                # 累加计数器并检查是否达到执行条件
                self.aggregation_counter += self.interval
                if self.aggregation_counter >= self.AGGREGATION_INTERVAL:
                    try:
                        logging.info("开始执行小时数据聚合任务...")
                        self.db_manager.aggregate_hourly_traffic()
                        logging.info("小时数据聚合任务执行完成。")
                    except Exception as e:
                        logging.error(f"执行小时数据聚合任务时出错: {e}", exc_info=True)
                    # 重置计数器
                    self.aggregation_counter = 0
            except Exception as e:
                logging.error(f"DataTracker 循环出错: {e}", exc_info=True)
            elapsed = time.monotonic() - start_time
            time.sleep(max(0, self.interval - elapsed))

    def _fetch_and_buffer_stats(self):
        config = self.config_manager.get()
        enabled_downloaders = [
            d for d in config.get("downloaders", []) if d.get("enabled")
        ]
        if not enabled_downloaders:
            time.sleep(self.interval)
            return

        current_timestamp = datetime.now()
        data_points = []
        latest_speeds_update = {}

        for downloader in enabled_downloaders:
            data_point = {
                "downloader_id": downloader["id"],
                "total_dl": 0,
                "total_ul": 0,
                "dl_speed": 0,
                "ul_speed": 0
            }
            try:
                client = self._get_client(downloader)
                if not client: continue

                if downloader["type"] == "qbittorrent":
                    try:
                        main_data = client.sync_maindata()
                    except qb_exceptions.APIConnectionError:
                        logging.warning(
                            f"与 '{downloader['name']}' 的连接丢失，正在尝试重新连接...")
                        del self.clients[downloader['id']]
                        client = self._get_client(downloader)
                        if not client: continue
                        main_data = client.sync_maindata()

                    server_state = main_data.get('server_state', {})
                    data_point.update({
                        'dl_speed':
                        int(server_state.get('dl_info_speed', 0)),
                        'ul_speed':
                        int(server_state.get('up_info_speed', 0)),
                        'total_dl':
                        int(server_state.get('alltime_dl', 0)),
                        'total_ul':
                        int(server_state.get('alltime_ul', 0))
                    })
                elif downloader["type"] == "transmission":
                    stats = client.session_stats()
                    data_point.update({
                        "dl_speed":
                        int(getattr(stats, "download_speed", 0)),
                        "ul_speed":
                        int(getattr(stats, "upload_speed", 0)),
                        "total_dl":
                        int(stats.cumulative_stats.downloaded_bytes),
                        "total_ul":
                        int(stats.cumulative_stats.uploaded_bytes),
                    })
                latest_speeds_update[downloader["id"]] = {
                    "name": downloader["name"],
                    "type": downloader["type"],
                    "enabled": True,
                    "upload_speed": data_point["ul_speed"],
                    "download_speed": data_point["dl_speed"]
                }
                data_points.append(data_point)
            except Exception as e:
                logging.warning(f"无法从客户端 '{downloader['name']}' 获取统计信息: {e}")
                if downloader['id'] in self.clients:
                    del self.clients[downloader['id']]
                latest_speeds_update[downloader["id"]] = {
                    "name": downloader["name"],
                    "type": downloader["type"],
                    "enabled": True,
                    "upload_speed": 0,
                    "download_speed": 0
                }

        with CACHE_LOCK:
            self.latest_speeds = latest_speeds_update
            speeds_for_buffer = {
                downloader_id: {
                    "upload_speed": data.get("upload_speed", 0),
                    "download_speed": data.get("download_speed", 0)
                }
                for downloader_id, data in latest_speeds_update.items()
            }
            self.recent_speeds_buffer.append({
                "timestamp": current_timestamp,
                "speeds": speeds_for_buffer
            })

        with self.traffic_buffer_lock:
            self.traffic_buffer.append({
                "timestamp": current_timestamp,
                "points": data_points
            })
            if len(self.traffic_buffer) >= self.TRAFFIC_BATCH_WRITE_SIZE:
                self._flush_traffic_buffer_to_db(self.traffic_buffer)
                self.traffic_buffer = []

    def _flush_traffic_buffer_to_db(self, buffer):
        if not buffer: return
        conn = None
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)
            is_mysql = self.db_manager.db_type == "mysql"
            cursor.execute(
                "SELECT id, last_total_dl, last_total_ul FROM downloader_clients"
            )
            last_states = {row["id"]: dict(row) for row in cursor.fetchall()}
            params_to_insert = []
            for entry in buffer:
                timestamp_str = entry["timestamp"].strftime(
                    "%Y-%m-%d %H:%M:%S")
                for data_point in entry["points"]:
                    client_id = data_point["downloader_id"]
                    if not last_states.get(client_id): continue
                    last_dl, last_ul = int(
                        last_states[client_id]["last_total_dl"]), int(
                            last_states[client_id]["last_total_ul"])
                    current_dl, current_ul = data_point[
                        "total_dl"], data_point["total_ul"]
                    dl_inc, ul_inc = (current_dl -
                                      last_dl if current_dl >= last_dl else
                                      0), (current_ul - last_ul
                                           if current_ul >= last_ul else 0)
                    last_states[client_id]["last_total_dl"], last_states[
                        client_id]["last_total_ul"] = current_dl, current_ul
                    params_to_insert.append(
                        (timestamp_str, client_id, max(0,
                                                       ul_inc), max(0, dl_inc),
                         data_point["ul_speed"], data_point["dl_speed"]))

            if params_to_insert:
                # 根据数据库类型使用正确的占位符和冲突处理语法
                if self.db_manager.db_type == "mysql":
                    sql_insert = """INSERT INTO traffic_stats (stat_datetime, downloader_id, uploaded, downloaded, upload_speed, download_speed) VALUES (%s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE uploaded = VALUES(uploaded), downloaded = VALUES(downloaded), upload_speed = VALUES(upload_speed), download_speed = VALUES(download_speed)"""
                elif self.db_manager.db_type == "postgresql":
                    sql_insert = """INSERT INTO traffic_stats (stat_datetime, downloader_id, uploaded, downloaded, upload_speed, download_speed) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT(stat_datetime, downloader_id) DO UPDATE SET uploaded = EXCLUDED.uploaded, downloaded = EXCLUDED.downloaded, upload_speed = EXCLUDED.upload_speed, download_speed = EXCLUDED.download_speed"""
                else:  # sqlite
                    sql_insert = """INSERT INTO traffic_stats (stat_datetime, downloader_id, uploaded, downloaded, upload_speed, download_speed) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(stat_datetime, downloader_id) DO UPDATE SET uploaded = excluded.uploaded, downloaded = excluded.downloaded, upload_speed = excluded.upload_speed, download_speed = excluded.download_speed"""
                cursor.executemany(sql_insert, params_to_insert)

            update_params = [(state["last_total_dl"], state["last_total_ul"],
                              client_id)
                             for client_id, state in last_states.items()]
            if update_params:
                # 根据数据库类型使用正确的占位符
                if self.db_manager.db_type == "mysql" or self.db_manager.db_type == "postgresql":
                    sql = "UPDATE downloader_clients SET last_total_dl = %s, last_total_ul = %s WHERE id = %s"
                else:  # sqlite
                    sql = "UPDATE downloader_clients SET last_total_dl = ?, last_total_ul = ? WHERE id = ?"
                cursor.executemany(sql, update_params)
            conn.commit()
        except Exception as e:
            logging.error(f"将流量缓冲刷新到数据库失败: {e}", exc_info=True)
            if conn: conn.rollback()
        finally:
            if conn:
                cursor.close()
                conn.close()

    def _update_torrents_in_db(self):
        logging.info("开始更新数据库中的种子...")
        config = self.config_manager.get()
        enabled_downloaders = [
            d for d in config.get("downloaders", []) if d.get("enabled")
        ]
        if not enabled_downloaders:
            logging.info("没有启用的下载器，跳过种子更新。")
            return

        core_domain_map, _, group_to_site_map_lower = load_site_maps_from_db(
            self.db_manager)
        all_current_hashes = set()
        torrents_to_upsert, upload_stats_to_upsert = {}, []
        is_mysql = self.db_manager.db_type == "mysql"

        for downloader in enabled_downloaders:
            torrents_list = []
            client_instance = None
            try:
                client_instance = self._get_client(downloader)
                if not client_instance: continue

                if downloader["type"] == "qbittorrent":
                    torrents_list = client_instance.torrents_info(
                        status_filter="all")
                elif downloader["type"] == "transmission":
                    fields = [
                        "id", "name", "hashString", "downloadDir", "totalSize",
                        "status", "comment", "trackers", "percentDone",
                        "uploadedEver"
                    ]
                    torrents_list = client_instance.get_torrents(
                        arguments=fields)
                logging.info(
                    f"从 '{downloader['name']}' 成功获取到 {len(torrents_list)} 个种子。"
                )
            except Exception as e:
                logging.error(f"未能从 '{downloader['name']}' 获取数据: {e}")
                continue

            for t in torrents_list:
                t_info = self._normalize_torrent_info(t, downloader["type"],
                                                      client_instance)
                all_current_hashes.add(t_info["hash"])
                if (t_info["hash"] not in torrents_to_upsert
                        or t_info["progress"]
                        > torrents_to_upsert[t_info["hash"]]["progress"]):
                    torrents_to_upsert[t_info["hash"]] = {
                        "hash":
                        t_info["hash"],
                        "name":
                        t_info["name"],
                        "save_path":
                        t_info["save_path"],
                        "size":
                        t_info["size"],
                        "progress":
                        round(t_info["progress"] * 100, 1),
                        "state":
                        format_state(t_info["state"]),
                        "sites":
                        self._find_site_nickname(t_info["trackers"],
                                                 core_domain_map),
                        "details":
                        _extract_url_from_comment(t_info["comment"]),
                        "group":
                        self._find_torrent_group(t_info["name"],
                                                 group_to_site_map_lower),
                        "downloader_id":
                        downloader["id"],
                    }
                if t_info["uploaded"] > 0:
                    upload_stats_to_upsert.append(
                        (t_info["hash"], downloader["id"], t_info["uploaded"]))

        conn = None
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if torrents_to_upsert:
                params = [(*d.values(), now_str)
                          for d in torrents_to_upsert.values()]
                # 根据数据库类型使用正确的引号和冲突处理语法
                if self.db_manager.db_type == "mysql":
                    sql = """INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, `group`, downloader_id, last_seen) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE name=VALUES(name), save_path=VALUES(save_path), size=VALUES(size), progress=VALUES(progress), state=VALUES(state), sites=VALUES(sites), details=VALUES(details), `group`=VALUES(`group`), downloader_id=VALUES(downloader_id), last_seen=VALUES(last_seen)"""
                elif self.db_manager.db_type == "postgresql":
                    sql = """INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, "group", downloader_id, last_seen) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT(hash) DO UPDATE SET name=excluded.name, save_path=excluded.save_path, size=excluded.size, progress=excluded.progress, state=excluded.state, sites=excluded.sites, details=excluded.details, "group"=excluded."group", downloader_id=excluded.downloader_id, last_seen=excluded.last_seen"""
                else:  # sqlite
                    sql = """INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, `group`, downloader_id, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(hash) DO UPDATE SET name=excluded.name, save_path=excluded.save_path, size=excluded.size, progress=excluded.progress, state=excluded.state, sites=excluded.sites, details=excluded.details, `group`=excluded.`group`, downloader_id=excluded.downloader_id, last_seen=excluded.last_seen"""
                cursor.executemany(sql, params)
                logging.info(f"已批量处理 {len(params)} 条种子主信息。")
            if upload_stats_to_upsert:
                # 根据数据库类型使用正确的占位符和冲突处理语法
                if self.db_manager.db_type == "mysql":
                    sql_upload = """INSERT INTO torrent_upload_stats (hash, downloader_id, uploaded) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE uploaded=VALUES(uploaded)"""
                elif self.db_manager.db_type == "postgresql":
                    sql_upload = """INSERT INTO torrent_upload_stats (hash, downloader_id, uploaded) VALUES (%s, %s, %s) ON CONFLICT(hash, downloader_id) DO UPDATE SET uploaded=EXCLUDED.uploaded"""
                else:  # sqlite
                    sql_upload = """INSERT INTO torrent_upload_stats (hash, downloader_id, uploaded) VALUES (?, ?, ?) ON CONFLICT(hash, downloader_id) DO UPDATE SET uploaded=excluded.uploaded"""
                cursor.executemany(sql_upload, upload_stats_to_upsert)
                logging.info(f"已批量处理 {len(upload_stats_to_upsert)} 条种子上传数据。")
            # 根据数据库类型使用正确的占位符
            placeholder = "%s" if self.db_manager.db_type in ["mysql", "postgresql"] else "?"
            (cursor.execute(
                "DELETE FROM torrents WHERE hash NOT IN ({})".format(",".join(
                    [placeholder] *
                    len(all_current_hashes))), tuple(all_current_hashes))
             if all_current_hashes else cursor.execute("DELETE FROM torrents"))
            logging.info(f"从 torrents 表中移除了 {cursor.rowcount} 个陈旧的种子。")
            conn.commit()
            logging.info("种子数据库更新周期成功完成。")
        except Exception as e:
            logging.error(f"更新数据库中的种子失败: {e}", exc_info=True)
            if conn: conn.rollback()
        finally:
            if conn:
                cursor.close()
                conn.close()

    def _normalize_torrent_info(self, t, client_type, client_instance=None):
        if client_type == "qbittorrent":
            info = {
                "name": t.name,
                "hash": t.hash,
                "save_path": t.save_path,
                "size": t.size,
                "progress": t.progress,
                "state": t.state,
                "comment": t.get("comment", ""),
                "trackers": t.trackers,
                "uploaded": t.uploaded,
            }

            # --- [核心修正] ---
            # 基于成功的测试脚本，实现可靠的备用方案
            if not info["comment"] and client_instance:
                logging.debug(f"种子 '{t.name[:30]}...' 的注释为空，尝试备用接口获取。")
                try:
                    # 1. 从客户端实例中提取 SID cookie
                    sid_cookie = client_instance._session.cookies.get('SID')
                    if sid_cookie:
                        cookies_for_request = {'SID': sid_cookie}

                        # 2. 构造请求
                        # 使用 client.host 属性，这是库提供的公共接口，比_host更稳定
                        base_url = client_instance.host
                        properties_url = f"{base_url}/api/v2/torrents/properties"
                        params = {'hash': t.hash}

                        # 3. 发送手动请求
                        response = requests.get(properties_url,
                                                params=params,
                                                cookies=cookies_for_request,
                                                timeout=10)
                        response.raise_for_status()

                        # 4. 解析并更新 comment
                        properties_data = response.json()
                        fallback_comment = properties_data.get("comment", "")

                        if fallback_comment:
                            logging.info(
                                f"成功通过备用接口为种子 '{t.name[:30]}...' 获取到注释。")
                            info["comment"] = fallback_comment
                    else:
                        logging.warning(f"无法为备用请求提取 SID cookie，跳过。")

                except Exception as e:
                    logging.warning(f"为种子HASH {t.hash} 调用备用接口获取注释失败: {e}")

            return info
        # --- [修正结束] ---
        elif client_type == "transmission":
            return {
                "name":
                t.name,
                "hash":
                t.hash_string,
                "save_path":
                t.download_dir,
                "size":
                t.total_size,
                "progress":
                t.percent_done,
                "state":
                t.status,
                "comment":
                getattr(t, "comment", ""),
                "trackers": [{
                    "url": tracker.get("announce")
                } for tracker in t.trackers],
                "uploaded":
                t.uploaded_ever,
            }
        return {}

    def _find_site_nickname(self, trackers, core_domain_map):
        if trackers:
            for tracker_entry in trackers:
                hostname = _parse_hostname_from_url(tracker_entry.get("url"))
                core_domain = _extract_core_domain(hostname)
                if core_domain in core_domain_map:
                    return core_domain_map[core_domain]
        return None

    def _find_torrent_group(self, name, group_to_site_map_lower):
        name_lower = name.lower()
        found_matches = [
            group_info["original_case"]
            for group_lower, group_info in group_to_site_map_lower.items()
            if group_lower in name_lower
        ]
        if found_matches:
            return sorted(found_matches, key=len, reverse=True)[0]
        return None

    def stop(self):
        logging.info("正在停止 DataTracker 线程...")
        self._is_running = False
        with self.traffic_buffer_lock:
            if self.traffic_buffer:
                self._flush_traffic_buffer_to_db(self.traffic_buffer)
                self.traffic_buffer = []


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
