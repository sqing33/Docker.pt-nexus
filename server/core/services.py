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
    """准备用于API客户端的配置字典，只包含客户端需要的字段。"""
    # 定义客户端实际需要的字段
    if downloader_config["type"] == "qbittorrent":
        # qBittorrent 客户端需要的字段
        allowed_keys = ["host", "username", "password"]
    elif downloader_config["type"] == "transmission":
        # Transmission 客户端需要的字段
        allowed_keys = ["host", "port", "username", "password"]
    else:
        allowed_keys = ["host", "username", "password"]

    # 只提取需要的字段
    api_config = {
        k: v
        for k, v in downloader_config.items() if k in allowed_keys
    }

    # Transmission 特殊处理：智能解析 host 和 port
    if downloader_config["type"] == "transmission":
        if api_config.get("host"):
            host_value = api_config["host"]
            if not host_value.startswith(("http://", "https://")):
                host_value = f"http://{host_value}"
            parsed_url = urlparse(host_value)
            api_config["host"] = parsed_url.hostname
            api_config["port"] = parsed_url.port or 9091

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

    def _get_proxy_stats(self, downloader_config):
        """通过代理获取下载器的统计信息。"""
        try:
            # 从下载器配置的host中提取IP地址作为代理服务器地址
            host_value = downloader_config['host']

            # 如果host已经包含协议，直接解析；否则添加http://前缀
            if host_value.startswith(('http://', 'https://')):
                parsed_url = urlparse(host_value)
            else:
                parsed_url = urlparse(f"http://{host_value}")

            proxy_ip = parsed_url.hostname
            if not proxy_ip:
                # 如果无法解析，使用备用方法
                if '://' in host_value:
                    proxy_ip = host_value.split('://')[1].split(':')[0].split(
                        '/')[0]
                else:
                    proxy_ip = host_value.split(':')[0]

            proxy_port = downloader_config.get('proxy_port', 9090)  # 默认9090
            proxy_base_url = f"http://{proxy_ip}:{proxy_port}"

            # 构造代理请求数据
            proxy_downloader_config = {
                "id": downloader_config['id'],
                "type": downloader_config['type'],
                "host": "http://127.0.0.1:" + str(parsed_url.port or 8080),
                "username": downloader_config.get('username', ''),
                "password": downloader_config.get('password', '')
            }

            # 发送请求到代理获取统计信息
            response = requests.post(f"{proxy_base_url}/api/stats/server",
                                     json=[proxy_downloader_config],
                                     timeout=30)
            response.raise_for_status()

            stats_data = response.json()
            if stats_data and len(stats_data) > 0:
                return stats_data[0]  # 返回第一个下载器的统计信息
            else:
                logging.warning(
                    f"代理返回空的统计信息 for '{downloader_config['name']}'")
                return None

        except Exception as e:
            logging.error(f"通过代理获取 '{downloader_config['name']}' 统计信息失败: {e}")
            return None

    def _should_use_proxy(self, downloader_id):
        """根据下载器ID检查是否应该使用代理。"""
        try:
            config = self.config_manager.get()
            downloaders = config.get("downloaders", [])
            for downloader in downloaders:
                if downloader.get("id") == downloader_id:
                    return downloader.get("use_proxy", False)
            return False
        except Exception as e:
            logging.error(f"检查下载器 {downloader_id} 是否使用代理时出错: {e}")
            return False

    def _get_proxy_torrents(self, downloader_config):
        """通过代理获取下载器的完整种子信息。"""
        try:
            # 从下载器配置的host中提取IP地址作为代理服务器地址
            host_value = downloader_config['host']

            # 如果host已经包含协议，直接解析；否则添加http://前缀
            if host_value.startswith(('http://', 'https://')):
                parsed_url = urlparse(host_value)
            else:
                parsed_url = urlparse(f"http://{host_value}")

            proxy_ip = parsed_url.hostname
            if not proxy_ip:
                # 如果无法解析，使用备用方法
                if '://' in host_value:
                    proxy_ip = host_value.split('://')[1].split(':')[0].split(
                        '/')[0]
                else:
                    proxy_ip = host_value.split(':')[0]

            proxy_port = downloader_config.get('proxy_port', 9090)  # 默认9090
            proxy_base_url = f"http://{proxy_ip}:{proxy_port}"

            # 构造代理请求数据
            proxy_downloader_config = {
                "id": downloader_config['id'],
                "type": downloader_config['type'],
                "host": "http://127.0.0.1:" + str(parsed_url.port or 8080),
                "username": downloader_config.get('username', ''),
                "password": downloader_config.get('password', '')
            }

            # 构造请求数据，包含comment和trackers
            request_data = {
                "downloaders": [proxy_downloader_config],
                "include_comment": True,
                "include_trackers": True
            }

            # 发送请求到代理获取种子信息
            response = requests.post(
                f"{proxy_base_url}/api/torrents/all",
                json=request_data,
                timeout=120  # 种子信息可能需要更长的时间
            )
            response.raise_for_status()

            torrents_data = response.json()
            return torrents_data

        except Exception as e:
            logging.error(f"通过代理获取 '{downloader_config['name']}' 种子信息失败: {e}")
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
                # 检查是否需要使用代理
                use_proxy = downloader.get("use_proxy", False)

                if use_proxy and downloader["type"] == "qbittorrent":
                    # 使用代理获取统计数据
                    logging.info(f"通过代理获取 '{downloader['name']}' 的统计信息...")
                    proxy_stats = self._get_proxy_stats(downloader)

                    if proxy_stats:
                        # 代理返回的数据格式与直连不同，需要适配
                        if 'server_state' in proxy_stats:
                            # 如果代理返回的是标准格式
                            server_state = proxy_stats.get('server_state', {})
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
                        else:
                            # 新的代理数据格式，直接从根级别获取数据
                            data_point.update({
                                'dl_speed':
                                int(proxy_stats.get('download_speed', 0)),
                                'ul_speed':
                                int(proxy_stats.get('upload_speed', 0)),
                                'total_dl':
                                int(proxy_stats.get('total_download', 0)),
                                'total_ul':
                                int(proxy_stats.get('total_upload', 0))
                            })
                            logging.info(
                                f"代理数据: 上传速度={data_point['ul_speed']:,}, 下载速度={data_point['dl_speed']:,}, 总上传={data_point['total_ul']:,}, 总下载={data_point['total_dl']:,}"
                            )

                        # 更新 latest_speeds_update
                        latest_speeds_update[downloader["id"]] = {
                            "name": downloader["name"],
                            "type": downloader["type"],
                            "enabled": True,
                            "upload_speed": data_point["ul_speed"],
                            "download_speed": data_point["dl_speed"]
                        }
                        data_points.append(data_point)
                    else:
                        # 代理获取失败，跳过此下载器
                        logging.warning(
                            f"通过代理获取 '{downloader['name']}' 统计信息失败")
                        continue
                else:
                    # 使用常规方式获取统计数据
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
            params_to_insert = []

            for entry in buffer:
                timestamp_str = entry["timestamp"].strftime(
                    "%Y-%m-%d %H:%M:%S")
                for data_point in entry["points"]:
                    client_id = data_point["downloader_id"]
                    current_dl = data_point["total_dl"]
                    current_ul = data_point["total_ul"]

                    # 直接存储累计值
                    params_to_insert.append(
                        (timestamp_str, client_id, 0, 0,
                         data_point["ul_speed"], data_point["dl_speed"],
                         current_ul, current_dl))

            if params_to_insert:
                # 根据数据库类型使用正确的占位符和冲突处理语法
                if self.db_manager.db_type == "mysql":
                    sql_insert = """INSERT INTO traffic_stats (stat_datetime, downloader_id, uploaded, downloaded, upload_speed, download_speed, cumulative_uploaded, cumulative_downloaded) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE uploaded = VALUES(uploaded), downloaded = VALUES(downloaded), upload_speed = VALUES(upload_speed), download_speed = VALUES(download_speed), cumulative_uploaded = VALUES(cumulative_uploaded), cumulative_downloaded = VALUES(cumulative_downloaded)"""
                elif self.db_manager.db_type == "postgresql":
                    sql_insert = """INSERT INTO traffic_stats (stat_datetime, downloader_id, uploaded, downloaded, upload_speed, download_speed, cumulative_uploaded, cumulative_downloaded) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT(stat_datetime, downloader_id) DO UPDATE SET uploaded = EXCLUDED.uploaded, downloaded = EXCLUDED.downloaded, upload_speed = EXCLUDED.upload_speed, download_speed = EXCLUDED.download_speed, cumulative_uploaded = EXCLUDED.cumulative_uploaded, cumulative_downloaded = EXCLUDED.cumulative_downloaded"""
                else:  # sqlite
                    sql_insert = """INSERT INTO traffic_stats (stat_datetime, downloader_id, uploaded, downloaded, upload_speed, download_speed, cumulative_uploaded, cumulative_downloaded) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(stat_datetime, downloader_id) DO UPDATE SET uploaded = excluded.uploaded, downloaded = excluded.downloaded, upload_speed = excluded.upload_speed, download_speed = excluded.download_speed, cumulative_uploaded = excluded.cumulative_uploaded, cumulative_downloaded = excluded.cumulative_downloaded"""
                cursor.executemany(sql_insert, params_to_insert)

            conn.commit()
        except Exception as e:
            logging.error(f"将流量缓冲刷新到数据库失败: {e}", exc_info=True)
            if conn: conn.rollback()
        finally:
            if conn:
                cursor.close()
                conn.close()

    def _update_torrents_in_db(self):
        from datetime import datetime
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logging.info("=== 开始更新数据库中的种子 ===")
        print(f"【刷新线程】[{current_time}] 开始更新数据库中的种子...")
        config = self.config_manager.get()
        enabled_downloaders = [
            d for d in config.get("downloaders", []) if d.get("enabled")
        ]
        print(f"【刷新线程】找到 {len(enabled_downloaders)} 个启用的下载器")
        logging.info(f"找到 {len(enabled_downloaders)} 个启用的下载器")
        if not enabled_downloaders:
            logging.info("没有启用的下载器，跳过种子更新。")
            print("【刷新线程】没有启用的下载器，跳过种子更新。")
            return

        core_domain_map, _, group_to_site_map_lower = load_site_maps_from_db(
            self.db_manager)
        all_current_hashes = set()
        torrents_to_upsert, upload_stats_to_upsert = {}, []
        is_mysql = self.db_manager.db_type == "mysql"

        for downloader in enabled_downloaders:
            print(
                f"【刷新线程】正在处理下载器: {downloader['name']} (类型: {downloader['type']})"
            )
            torrents_list = []
            client_instance = None
            try:
                # 检查是否需要使用代理
                use_proxy = downloader.get("use_proxy", False)

                if use_proxy and downloader["type"] == "qbittorrent":
                    # 使用代理获取种子信息
                    logging.info(f"通过代理获取 '{downloader['name']}' 的种子信息...")
                    proxy_torrents = self._get_proxy_torrents(downloader)

                    if proxy_torrents is not None:
                        torrents_list = proxy_torrents
                        print(
                            f"【刷新线程】通过代理从 '{downloader['name']}' 成功获取到 {len(torrents_list)} 个种子。"
                        )
                        logging.info(
                            f"通过代理从 '{downloader['name']}' 成功获取到 {len(torrents_list)} 个种子。"
                        )
                    else:
                        # 代理获取失败，跳过此下载器
                        print(f"【刷新线程】通过代理获取 '{downloader['name']}' 种子信息失败")
                        logging.warning(
                            f"通过代理获取 '{downloader['name']}' 种子信息失败")
                        continue
                else:
                    # 使用常规方式获取种子信息
                    client_instance = self._get_client(downloader)
                    if not client_instance:
                        print(f"【刷新线程】无法连接到下载器 {downloader['name']}")
                        continue

                    print(f"【刷新线程】正在从 {downloader['name']} 获取种子列表...")
                    if downloader["type"] == "qbittorrent":
                        torrents_list = client_instance.torrents_info(
                            status_filter="all")
                    elif downloader["type"] == "transmission":
                        fields = [
                            "id", "name", "hashString", "downloadDir",
                            "totalSize", "status", "comment", "trackers",
                            "percentDone", "uploadedEver"
                        ]
                        torrents_list = client_instance.get_torrents(
                            arguments=fields)
                    print(
                        f"【刷新线程】从 '{downloader['name']}' 成功获取到 {len(torrents_list)} 个种子。"
                    )
                    logging.info(
                        f"从 '{downloader['name']}' 成功获取到 {len(torrents_list)} 个种子。"
                    )
            except Exception as e:
                print(f"【刷新线程】未能从 '{downloader['name']}' 获取数据: {e}")
                logging.error(f"未能从 '{downloader['name']}' 获取数据: {e}")
                continue

            print(f"【刷新线程】开始处理 {len(torrents_list)} 个种子...")
            for t in torrents_list:
                t_info = self._normalize_torrent_info(t, downloader["type"],
                                                      client_instance)
                all_current_hashes.add(t_info["hash"])
                if (t_info["hash"] not in torrents_to_upsert
                        or t_info["progress"]
                        > torrents_to_upsert[t_info["hash"]]["progress"]):
                    site_name = self._find_site_nickname(
                        t_info["trackers"], core_domain_map, t_info["comment"])
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
                        site_name,
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
            print(
                f"【刷新线程】完成处理下载器 {downloader['name']} 的种子，共收集到 {len(torrents_to_upsert)} 个唯一种子"
            )

        print(
            f"【刷新线程】开始将 {len(torrents_to_upsert)} 个种子和 {len(upload_stats_to_upsert)} 条上传统计写入数据库..."
        )
        conn = None
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # 先清理启用下载器中已删除的种子
            print(f"【刷新线程】开始清理启用下载器中已删除的种子...")
            enabled_downloader_ids = {d["id"] for d in enabled_downloaders}
            for downloader_id in enabled_downloader_ids:
                # 获取该下载器当前的种子哈希
                downloader_current_hashes = {
                    h
                    for h in all_current_hashes if torrents_to_upsert.get(
                        h, {}).get("downloader_id") == downloader_id
                }

                # 获取数据库中该下载器的历史种子哈希
                placeholder = "%s" if self.db_manager.db_type in [
                    "mysql", "postgresql"
                ] else "?"
                cursor.execute(
                    f"SELECT hash FROM torrents WHERE downloader_id = {placeholder}",
                    (downloader_id, ))
                db_hashes = {row["hash"] for row in cursor.fetchall()}

                # 找出需要删除的种子（在数据库中但不在当前下载器中）
                hashes_to_delete = db_hashes - downloader_current_hashes

                if hashes_to_delete:
                    print(
                        f"【刷新线程】发现下载器 {downloader_id} 中有 {len(hashes_to_delete)} 个种子已被删除"
                    )
                    # 从torrents表中删除这些种子，但保护IYUU添加的未做种种子
                    delete_placeholders = ",".join([placeholder] *
                                                   len(hashes_to_delete))
                    # 修改删除逻辑：只删除状态不是'未做种'的种子，保护IYUU添加的未做种记录
                    delete_query = f"DELETE FROM torrents WHERE hash IN ({delete_placeholders}) AND downloader_id = {placeholder} AND state != '未做种'"
                    cursor.execute(delete_query,
                                   tuple(hashes_to_delete) + (downloader_id, ))
                    deleted_count = cursor.rowcount
                    print(
                        f"【刷新线程】已删除下载器 {downloader_id} 中的 {deleted_count} 个已移除的种子记录（保护了未做种种子）"
                    )
                    logging.info(
                        f"已删除下载器 {downloader_id} 中的 {deleted_count} 个已移除的种子记录（保护了未做种种子）")

            # 更新seed_parameters表中的is_deleted字段
            print("【刷新线程】开始更新seed_parameters表中的is_deleted字段...")
            # 获取所有seed_parameters表中的hash值
            cursor.execute("SELECT DISTINCT hash FROM seed_parameters")
            seed_hashes = {row["hash"] for row in cursor.fetchall()}

            # 获取所有torrents表中的hash值
            cursor.execute("SELECT DISTINCT hash FROM torrents")
            torrent_hashes = {row["hash"] for row in cursor.fetchall()}

            # 找出在torrents表中存在的hash值和不存在的hash值
            hashes_in_torrents = seed_hashes & torrent_hashes
            hashes_not_in_torrents = seed_hashes - torrent_hashes

            # 更新在torrents表中存在的hash值的is_deleted字段为0
            if hashes_in_torrents:
                print(f"【刷新线程】发现 {len(hashes_in_torrents)} 个种子在torrents表中存在")
                update_placeholders = ",".join([placeholder] *
                                               len(hashes_in_torrents))
                # 根据数据库类型使用正确的布尔值
                if self.db_manager.db_type == 'postgresql':
                    update_query = f"UPDATE seed_parameters SET is_deleted = FALSE WHERE hash IN ({update_placeholders})"
                else:
                    update_query = f"UPDATE seed_parameters SET is_deleted = 0 WHERE hash IN ({update_placeholders})"
                cursor.execute(update_query, tuple(hashes_in_torrents))
                print(
                    f"【刷新线程】已更新 {len(hashes_in_torrents)} 个种子的is_deleted字段为0")
                logging.info(
                    f"已更新 {len(hashes_in_torrents)} 个种子的is_deleted字段为0")

            # 更新在torrents表中不存在的hash值的is_deleted字段为1
            if hashes_not_in_torrents:
                print(
                    f"【刷新线程】发现 {len(hashes_not_in_torrents)} 个种子在torrents表中不存在"
                )
                update_placeholders = ",".join([placeholder] *
                                               len(hashes_not_in_torrents))
                # 根据数据库类型使用正确的布尔值
                if self.db_manager.db_type == 'postgresql':
                    update_query = f"UPDATE seed_parameters SET is_deleted = TRUE WHERE hash IN ({update_placeholders})"
                else:
                    update_query = f"UPDATE seed_parameters SET is_deleted = 1 WHERE hash IN ({update_placeholders})"
                cursor.execute(update_query, tuple(hashes_not_in_torrents))
                print(
                    f"【刷新线程】已更新 {len(hashes_not_in_torrents)} 个种子的is_deleted字段为1"
                )
                logging.info(
                    f"已更新 {len(hashes_not_in_torrents)} 个种子的is_deleted字段为1")

            if torrents_to_upsert:
                params = [(*d.values(), now_str)
                          for d in torrents_to_upsert.values()]
                print(f"【刷新线程】准备写入 {len(params)} 条种子主信息到数据库")
                # 根据数据库类型使用正确的引号和冲突处理语法
                if self.db_manager.db_type == "mysql":
                    sql = """INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, `group`, downloader_id, last_seen) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE name=VALUES(name), save_path=VALUES(save_path), size=VALUES(size), progress=VALUES(progress), state=VALUES(state), sites=VALUES(sites), details=IF(VALUES(details) != '', VALUES(details), details), `group`=VALUES(`group`), downloader_id=VALUES(downloader_id), last_seen=VALUES(last_seen)"""
                elif self.db_manager.db_type == "postgresql":
                    sql = """INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, "group", downloader_id, last_seen) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT(hash) DO UPDATE SET name=excluded.name, save_path=excluded.save_path, size=excluded.size, progress=excluded.progress, state=excluded.state, sites=excluded.sites, details=CASE WHEN excluded.details != '' THEN excluded.details ELSE excluded.details END, "group"=excluded."group", downloader_id=excluded.downloader_id, last_seen=excluded.last_seen"""
                else:  # sqlite
                    sql = """INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, "group", downloader_id, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(hash) DO UPDATE SET name=excluded.name, save_path=excluded.save_path, size=excluded.size, progress=excluded.progress, state=excluded.state, sites=excluded.sites, details=CASE WHEN excluded.details != '' THEN excluded.details ELSE excluded.details END, "group"=excluded."group", downloader_id=excluded.downloader_id, last_seen=excluded.last_seen"""
                cursor.executemany(sql, params)
                print(f"【刷新线程】已批量处理 {len(params)} 条种子主信息。")
                logging.info(f"已批量处理 {len(params)} 条种子主信息。")
            if upload_stats_to_upsert:
                print(f"【刷新线程】准备写入 {len(upload_stats_to_upsert)} 条种子上传数据到数据库")
                # 根据数据库类型使用正确的占位符和冲突处理语法
                if self.db_manager.db_type == "mysql":
                    sql_upload = """INSERT INTO torrent_upload_stats (hash, downloader_id, uploaded) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE uploaded=VALUES(uploaded)"""
                elif self.db_manager.db_type == "postgresql":
                    sql_upload = """INSERT INTO torrent_upload_stats (hash, downloader_id, uploaded) VALUES (%s, %s, %s) ON CONFLICT(hash, downloader_id) DO UPDATE SET uploaded=EXCLUDED.uploaded"""
                else:  # sqlite
                    sql_upload = """INSERT INTO torrent_upload_stats (hash, downloader_id, uploaded) VALUES (?, ?, ?) ON CONFLICT(hash, downloader_id) DO UPDATE SET uploaded=excluded.uploaded"""
                cursor.executemany(sql_upload, upload_stats_to_upsert)
                print(f"【刷新线程】已批量处理 {len(upload_stats_to_upsert)} 条种子上传数据。")
                logging.info(f"已批量处理 {len(upload_stats_to_upsert)} 条种子上传数据。")
            # 根据数据库类型使用正确的占位符
            placeholder = "%s" if self.db_manager.db_type in [
                "mysql", "postgresql"
            ] else "?"

            print(f"【刷新线程】检查是否需要删除已移除下载器的种子数据...")
            # 修改删除逻辑：只删除已从配置中删除的下载器的种子数据，保留已禁用下载器的种子数据
            # 获取配置中所有下载器的ID（包括启用和禁用的）
            all_configured_downloaders = {
                d["id"]
                for d in config.get("downloaders", [])
            }

            # 获取当前数据库中存在的所有下载器ID
            cursor.execute(
                "SELECT DISTINCT downloader_id FROM torrents WHERE downloader_id IS NOT NULL"
            )
            existing_downloader_ids = {
                row["downloader_id"]
                for row in cursor.fetchall()
            }

            # 计算应该删除种子数据的下载器ID（已从配置中删除的下载器）
            deleted_downloader_ids = existing_downloader_ids - all_configured_downloaders

            # 只删除已从配置中删除的下载器的种子数据，保留已禁用下载器的种子数据
            if deleted_downloader_ids:
                print(
                    f"【刷新线程】发现 {len(deleted_downloader_ids)} 个已删除的下载器，将移除其种子数据"
                )
                # 构建 WHERE 子句
                downloader_placeholders = ",".join([placeholder] *
                                                   len(deleted_downloader_ids))
                delete_query = f"DELETE FROM torrents WHERE downloader_id IN ({downloader_placeholders})"
                cursor.execute(delete_query, tuple(deleted_downloader_ids))
                deleted_count = cursor.rowcount
                print(f"【刷新线程】从 torrents 表中移除了 {deleted_count} 个已删除下载器的种子。")
                logging.info(f"从 torrents 表中移除了 {deleted_count} 个已删除下载器的种子。")
            else:
                deleted_count = 0
                print("【刷新线程】没有需要删除的已删除下载器的种子数据。")
                logging.info("没有需要删除的已删除下载器的种子数据。")
            conn.commit()
            print("【刷新线程】=== 种子数据库更新周期成功完成 ===")
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
            # 检查数据是从代理获取的还是从客户端获取的
            if isinstance(t, dict):
                # 从代理获取的数据是字典格式
                # 处理 tracker 信息：代理可能返回 tracker (单数) 字段而不是 trackers (复数)
                trackers_list = []
                if "trackers" in t and t["trackers"]:
                    # 如果有 trackers 字段（复数）
                    trackers_list = t["trackers"]
                elif "tracker" in t and t["tracker"]:
                    # 如果只有 tracker 字段（单数），将其转换为列表格式
                    trackers_list = [{"url": t["tracker"]}]
                
                info = {
                    "name": t.get("name", ""),
                    "hash": t.get("hash", ""),
                    "save_path": t.get("save_path", ""),
                    "size": t.get("size", 0),
                    "progress": t.get("progress", 0),
                    "state": t.get("state", ""),
                    "comment": t.get("comment", ""),
                    "trackers": trackers_list,
                    "uploaded": t.get("uploaded", 0),
                }
            else:
                # 从客户端获取的数据是对象格式
                # 获取 trackers 信息
                trackers_data = []
                try:
                    # 尝试获取 trackers 属性
                    if hasattr(t, 'trackers'):
                        trackers_data = t.trackers
                    # 如果 trackers 为空，尝试通过 API 获取
                    if not trackers_data and client_instance:
                        try:
                            torrent_trackers = client_instance.torrents_trackers(t.hash)
                            trackers_data = torrent_trackers if torrent_trackers else []
                        except Exception as e:
                            logging.warning(f"无法通过API获取种子 {t.hash} 的trackers: {e}")
                except Exception as e:
                    logging.warning(f"获取种子 {t.hash} 的trackers时出错: {e}")
                
                info = {
                    "name": t.name,
                    "hash": t.hash,
                    "save_path": t.save_path,
                    "size": t.size,
                    "progress": t.progress,
                    "state": t.state,
                    "comment": t.get("comment", ""),
                    "trackers": trackers_data,
                    "uploaded": t.uploaded,
                }

                # --- [核心修正] ---
                # 基于成功的测试脚本，实现可靠的备用方案
                if not info["comment"] and client_instance:
                    logging.debug(f"种子 '{t.name[:30]}...' 的注释为空，尝试备用接口获取。")
                    try:
                        # 1. 从客户端实例中提取 SID cookie
                        sid_cookie = client_instance._session.cookies.get(
                            'SID')
                        if sid_cookie:
                            cookies_for_request = {'SID': sid_cookie}

                            # 2. 构造请求
                            # 使用 client.host 属性，这是库提供的公共接口，比_host更稳定
                            base_url = client_instance.host
                            properties_url = f"{base_url}/api/v2/torrents/properties"
                            params = {'hash': t.hash}

                            # 3. 发送手动请求
                            response = requests.get(
                                properties_url,
                                params=params,
                                cookies=cookies_for_request,
                                timeout=10)
                            response.raise_for_status()

                            # 4. 解析并更新 comment
                            properties_data = response.json()
                            fallback_comment = properties_data.get(
                                "comment", "")

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
            # 检查数据是从代理获取的还是从客户端获取的
            if isinstance(t, dict):
                # 从代理获取的数据是字典格式
                return {
                    "name": t.get("name", ""),
                    "hash": t.get("hashString", ""),
                    "save_path": t.get("downloadDir", ""),
                    "size": t.get("totalSize", 0),
                    "progress": t.get("percentDone", 0),
                    "state": t.get("status", ""),
                    "comment": t.get("comment", ""),
                    "trackers": t.get("trackers", []),
                    "uploaded": t.get("uploadedEver", 0),
                }
            else:
                # 从客户端获取的数据是对象格式
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

    def _find_site_nickname(self, trackers, core_domain_map, comment=None):
        # 首先尝试从 trackers 匹配
        if trackers:
            for tracker_entry in trackers:
                tracker_url = tracker_entry.get("url")
                hostname = _parse_hostname_from_url(tracker_url)
                core_domain = _extract_core_domain(hostname)
                if core_domain in core_domain_map:
                    matched_site = core_domain_map[core_domain]
                    return matched_site
        
        # 如果 trackers 为空或未匹配到，尝试从 comment 中提取 URL 并匹配
        if comment:
            comment_url = _extract_url_from_comment(comment)
            if comment_url:
                hostname = _parse_hostname_from_url(comment_url)
                if hostname:
                    core_domain = _extract_core_domain(hostname)
                    if core_domain in core_domain_map:
                        matched_site = core_domain_map[core_domain]
                        logging.info(f"通过 comment URL 匹配到站点: {matched_site} (域名: {core_domain})")
                        return matched_site
        
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
    # 检查是否在调试模式下运行，避免重复启动
    import os
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        # 在调试模式下，这是监控进程，不需要启动线程
        logging.info("检测到调试监控进程，跳过DataTracker线程启动。")
        return data_tracker_thread

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
