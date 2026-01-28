# core/services.py

import collections
import logging
import os
import time
from datetime import datetime
from threading import Thread, Lock, Event
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
            cursor.execute('SELECT nickname, base_url, special_tracker_domain, "group" FROM sites')
        else:
            cursor.execute("SELECT nickname, base_url, special_tracker_domain, `group` FROM sites")
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
                            group_to_site_map_lower[clean_group_name.lower()] = {
                                "original_case": clean_group_name,
                                "site": nickname,
                            }

                base_hostname = _parse_hostname_from_url(f"http://{base_url}")
                if base_hostname:
                    core_domain_map[_extract_core_domain(base_hostname)] = nickname

                if special_tracker:
                    special_hostname = _parse_hostname_from_url(f"http://{special_tracker}")
                    if special_hostname:
                        core_domain_map[_extract_core_domain(special_hostname)] = nickname
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
    api_config = {k: v for k, v in downloader_config.items() if k in allowed_keys}

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
        self.TRAFFIC_BATCH_WRITE_SIZE = max(1, TARGET_WRITE_PERIOD_SECONDS // self.interval)
        logging.info(f"数据库批量写入大小设置为 {self.TRAFFIC_BATCH_WRITE_SIZE} 条记录。")
        self.traffic_buffer = []
        self.traffic_buffer_lock = Lock()
        self.latest_speeds = {}
        self.recent_speeds_buffer = collections.deque(maxlen=self.TRAFFIC_BATCH_WRITE_SIZE)
        self.torrent_update_counter = 0
        self.TORRENT_UPDATE_INTERVAL = 3600
        self.clients = {}
        # 用于优雅停止的event
        self.shutdown_event = Event()

        # 数据聚合任务相关变量
        self.aggregation_counter = 0  # 用于计时的计数器
        self.AGGREGATION_INTERVAL = 21600  # 聚合任务的执行间隔（秒），这里是6小时
        # 仅在后端启动后的“第一次刷新”完成后执行一次的清理/重建
        self._startup_agg_rebuild_done = False
        self._startup_agg_rebuild_lock = Lock()

    def _get_client(self, downloader_config):
        """智能获取或创建并缓存客户端实例，支持自动重连。"""
        client_id = downloader_config["id"]
        if client_id in self.clients:
            return self.clients[client_id]

        try:
            logging.info(f"正在为 '{downloader_config['name']}' 创建新的客户端连接...")
            api_config = _prepare_api_config(downloader_config)

            if downloader_config["type"] == "qbittorrent":
                client = Client(**api_config)
                client.auth_log_in()
            elif downloader_config["type"] == "transmission":
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
            host_value = downloader_config["host"]

            # 如果host已经包含协议，直接解析；否则添加http://前缀
            if host_value.startswith(("http://", "https://")):
                parsed_url = urlparse(host_value)
            else:
                parsed_url = urlparse(f"http://{host_value}")

            proxy_ip = parsed_url.hostname
            if not proxy_ip:
                # 如果无法解析，使用备用方法
                if "://" in host_value:
                    proxy_ip = host_value.split("://")[1].split(":")[0].split("/")[0]
                else:
                    proxy_ip = host_value.split(":")[0]

            proxy_port = downloader_config.get("proxy_port", 9090)  # 默认9090
            proxy_base_url = f"http://{proxy_ip}:{proxy_port}"

            # 构造代理请求数据
            proxy_downloader_config = {
                "id": downloader_config["id"],
                "type": downloader_config["type"],
                "host": "http://127.0.0.1:" + str(parsed_url.port or 8080),
                "username": downloader_config.get("username", ""),
                "password": downloader_config.get("password", ""),
            }

            # 发送请求到代理获取统计信息
            response = requests.post(
                f"{proxy_base_url}/api/stats/server", json=[proxy_downloader_config], timeout=30
            )
            response.raise_for_status()

            stats_data = response.json()
            if stats_data and len(stats_data) > 0:
                return stats_data[0]  # 返回第一个下载器的统计信息
            else:
                logging.warning(f"代理返回空的统计信息 for '{downloader_config['name']}'")
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
            host_value = downloader_config["host"]

            # 如果host已经包含协议，直接解析；否则添加http://前缀
            if host_value.startswith(("http://", "https://")):
                parsed_url = urlparse(host_value)
            else:
                parsed_url = urlparse(f"http://{host_value}")

            proxy_ip = parsed_url.hostname
            if not proxy_ip:
                # 如果无法解析，使用备用方法
                if "://" in host_value:
                    proxy_ip = host_value.split("://")[1].split(":")[0].split("/")[0]
                else:
                    proxy_ip = host_value.split(":")[0]

            proxy_port = downloader_config.get("proxy_port", 9090)  # 默认9090
            proxy_base_url = f"http://{proxy_ip}:{proxy_port}"

            # 构造代理请求数据
            proxy_downloader_config = {
                "id": downloader_config["id"],
                "type": downloader_config["type"],
                "host": "http://127.0.0.1:" + str(parsed_url.port or 8080),
                "username": downloader_config.get("username", ""),
                "password": downloader_config.get("password", ""),
            }

            # 构造请求数据，包含comment和trackers
            request_data = {
                "downloaders": [proxy_downloader_config],
                "include_comment": True,
                "include_trackers": True,
            }

            # 发送请求到代理获取种子信息
            response = requests.post(
                f"{proxy_base_url}/api/torrents/all",
                json=request_data,
                timeout=180,  # 种子信息可能需要更长的时间
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

        # --- 启动后仅执行一次：刷新并按聚合逻辑重建清理 ---
        try:
            # 仅避免 debug reloader 的父进程重复执行
            if os.environ.get("WERKZEUG_RUN_MAIN") != "true" and os.environ.get("WERKZEUG_RUN_MAIN") is not None:
                raise RuntimeError("Werkzeug reloader parent process: skip startup rebuild")

            config = self.config_manager.get()
            enabled_downloaders = [d for d in config.get("downloaders", []) if d.get("enabled")]
            if enabled_downloaders and not self._startup_agg_rebuild_done:
                logging.info("启动后首次：开始自动刷新种子并执行聚合重建清理（仅执行一次）...")
                active_hashes, enabled_downloaders = self.update_torrents_in_db()
                if active_hashes:
                    rebuilt = self._startup_rebuild_aggregated_groups_once(
                        active_hashes=active_hashes,
                        enabled_downloaders=enabled_downloaders,
                    )
                    logging.info(f"启动后聚合重建清理完成：处理了 {rebuilt} 个种子组。")
                self._startup_agg_rebuild_done = True
        except Exception as e:
            # 不影响主循环
            logging.info(f"启动后聚合重建清理跳过/失败: {e}")
        # --------------------

        # 注释掉初始化时的种子更新，改为手动触发
        try:
            config = self.config_manager.get()
            if any(d.get("enabled") for d in config.get("downloaders", [])):
                logging.info("种子数据更新已改为手动触发模式，跳过初始种子更新。")
            else:
                logging.info("所有下载器均未启用，跳过初始种子更新。")
        except Exception as e:
            logging.error(f"检查下载器状态时出错: {e}", exc_info=True)

        while self._is_running:
            start_time = time.monotonic()
            try:
                self._fetch_and_buffer_stats()
                # 注释掉定时更新种子数据的逻辑，改为手动触发
                # self.torrent_update_counter += self.interval
                # if self.torrent_update_counter >= self.TORRENT_UPDATE_INTERVAL:
                #     self.clients.clear()
                #     logging.info("客户端连接缓存已清空，将为种子更新任务重建连接。")
                #     self._update_torrents_in_db()
                #     self.torrent_update_counter = 0

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
            # 等待下次执行，可以被shutdown_event中断
            remaining_time = max(0, self.interval - elapsed)
            if remaining_time > 0:
                # 使用Event.wait来等待，可以被中断
                if self.shutdown_event.wait(timeout=remaining_time):
                    # 如果被事件唤醒，说明要停止
                    break

    def _fetch_and_buffer_stats(self):
        config = self.config_manager.get()
        enabled_downloaders = [d for d in config.get("downloaders", []) if d.get("enabled")]
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
                "ul_speed": 0,
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
                        if "server_state" in proxy_stats:
                            # 如果代理返回的是标准格式
                            server_state = proxy_stats.get("server_state", {})
                            data_point.update(
                                {
                                    "dl_speed": int(server_state.get("dl_info_speed", 0)),
                                    "ul_speed": int(server_state.get("up_info_speed", 0)),
                                    "total_dl": int(server_state.get("alltime_dl", 0)),
                                    "total_ul": int(server_state.get("alltime_ul", 0)),
                                }
                            )
                        else:
                            # 新的代理数据格式，直接从根级别获取数据
                            data_point.update(
                                {
                                    "dl_speed": int(proxy_stats.get("download_speed", 0)),
                                    "ul_speed": int(proxy_stats.get("upload_speed", 0)),
                                    "total_dl": int(proxy_stats.get("total_download", 0)),
                                    "total_ul": int(proxy_stats.get("total_upload", 0)),
                                }
                            )
                            logging.info(
                                f"代理数据: 上传速度={data_point['ul_speed']:,}, 下载速度={data_point['dl_speed']:,}, 总上传={data_point['total_ul']:,}, 总下载={data_point['total_dl']:,}"
                            )

                        # 更新 latest_speeds_update
                        latest_speeds_update[downloader["id"]] = {
                            "name": downloader["name"],
                            "type": downloader["type"],
                            "enabled": True,
                            "upload_speed": data_point["ul_speed"],
                            "download_speed": data_point["dl_speed"],
                        }
                        # 过滤掉累计上传量和下载量都为0的数据
                        if data_point["total_ul"] > 0 or data_point["total_dl"] > 0:
                            data_points.append(data_point)
                    else:
                        # 代理获取失败，跳过此下载器
                        logging.warning(f"通过代理获取 '{downloader['name']}' 统计信息失败")
                        continue
                else:
                    # 使用常规方式获取统计数据
                    client = self._get_client(downloader)
                    if not client:
                        continue

                    if downloader["type"] == "qbittorrent":
                        try:
                            main_data = client.sync_maindata()
                        except qb_exceptions.APIConnectionError:
                            logging.warning(
                                f"与 '{downloader['name']}' 的连接丢失，正在尝试重新连接..."
                            )
                            del self.clients[downloader["id"]]
                            client = self._get_client(downloader)
                            if not client:
                                continue
                            main_data = client.sync_maindata()

                        server_state = main_data.get("server_state", {})
                        data_point.update(
                            {
                                "dl_speed": int(server_state.get("dl_info_speed", 0)),
                                "ul_speed": int(server_state.get("up_info_speed", 0)),
                                "total_dl": int(server_state.get("alltime_dl", 0)),
                                "total_ul": int(server_state.get("alltime_ul", 0)),
                            }
                        )
                    elif downloader["type"] == "transmission":
                        stats = client.session_stats()
                        data_point.update(
                            {
                                "dl_speed": int(getattr(stats, "download_speed", 0)),
                                "ul_speed": int(getattr(stats, "upload_speed", 0)),
                                "total_dl": int(stats.cumulative_stats.downloaded_bytes),
                                "total_ul": int(stats.cumulative_stats.uploaded_bytes),
                            }
                        )
                latest_speeds_update[downloader["id"]] = {
                    "name": downloader["name"],
                    "type": downloader["type"],
                    "enabled": True,
                    "upload_speed": data_point["ul_speed"],
                    "download_speed": data_point["dl_speed"],
                }
                # 过滤掉累计上传量和下载量都为0的数据
                if data_point["total_ul"] > 0 or data_point["total_dl"] > 0:
                    data_points.append(data_point)
            except Exception as e:
                logging.warning(f"无法从客户端 '{downloader['name']}' 获取统计信息: {e}")
                if downloader["id"] in self.clients:
                    del self.clients[downloader["id"]]
                latest_speeds_update[downloader["id"]] = {
                    "name": downloader["name"],
                    "type": downloader["type"],
                    "enabled": True,
                    "upload_speed": 0,
                    "download_speed": 0,
                }

        with CACHE_LOCK:
            self.latest_speeds = latest_speeds_update
            speeds_for_buffer = {
                downloader_id: {
                    "upload_speed": data.get("upload_speed", 0),
                    "download_speed": data.get("download_speed", 0),
                }
                for downloader_id, data in latest_speeds_update.items()
            }
            self.recent_speeds_buffer.append(
                {"timestamp": current_timestamp, "speeds": speeds_for_buffer}
            )

        with self.traffic_buffer_lock:
            self.traffic_buffer.append({"timestamp": current_timestamp, "points": data_points})
            if len(self.traffic_buffer) >= self.TRAFFIC_BATCH_WRITE_SIZE:
                self._flush_traffic_buffer_to_db(self.traffic_buffer)
                self.traffic_buffer = []

    def _flush_traffic_buffer_to_db(self, buffer):
        if not buffer:
            return

        # 过滤掉累计上传量和下载量都为0的数据
        filtered_buffer = []
        for entry in buffer:
            filtered_points = []
            for data_point in entry["points"]:
                if data_point["total_ul"] > 0 or data_point["total_dl"] > 0:
                    filtered_points.append(data_point)
            if filtered_points:  # 只保留有有效数据的条目
                filtered_entry = entry.copy()
                filtered_entry["points"] = filtered_points
                filtered_buffer.append(filtered_entry)

        if not filtered_buffer:
            logging.info("过滤后的流量缓冲为空，跳过数据库写入")
            return

        conn = None
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)

            # 根据数据库类型设置占位符
            placeholder = "%s" if self.db_manager.db_type in ["mysql", "postgresql"] else "?"

            # 第一步：获取每个下载器的最后一条记录
            downloader_ids = set()
            for entry in filtered_buffer:
                for data_point in entry["points"]:
                    downloader_ids.add(data_point["downloader_id"])

            last_records = {}
            if downloader_ids:
                # 查询每个下载器的最后一条有效记录
                placeholders = ",".join([placeholder] * len(downloader_ids))
                query = f"""
                    SELECT downloader_id, cumulative_uploaded, cumulative_downloaded, stat_datetime
                    FROM traffic_stats
                    WHERE downloader_id IN ({placeholders})
                    AND cumulative_uploaded > 0 OR cumulative_downloaded > 0
                    ORDER BY stat_datetime DESC
                """
                cursor.execute(query, tuple(downloader_ids))
                rows = cursor.fetchall()

                # 为每个下载器保存最新的记录
                for row in rows:
                    downloader_id = row["downloader_id"]
                    if downloader_id not in last_records:
                        last_records[downloader_id] = {
                            "cumulative_uploaded": row["cumulative_uploaded"],
                            "cumulative_downloaded": row["cumulative_downloaded"],
                            "stat_datetime": row["stat_datetime"],
                        }

            # 第二步：验证并准备插入数据
            params_to_insert = []

            for entry in filtered_buffer:
                timestamp_str = entry["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
                for data_point in entry["points"]:
                    client_id = data_point["downloader_id"]
                    current_dl = data_point["total_dl"]
                    current_ul = data_point["total_ul"]

                    # 数据验证逻辑
                    should_insert = True

                    if client_id in last_records:
                        last_ul = last_records[client_id]["cumulative_uploaded"]
                        last_dl = last_records[client_id]["cumulative_downloaded"]

                        # 检测异常情况：累计值降低或变为0
                        if (
                            (current_ul > 0 and current_ul < last_ul)
                            or (current_dl > 0 and current_dl < last_dl)
                            or (current_ul == 0 and last_ul > 0)
                            or (current_dl == 0 and last_dl > 0)
                        ):
                            should_insert = False
                            logging.warning(
                                f"检测到下载器 {client_id} 的累计流量降低或归零，"
                                f"跳过插入。当前: 上传={format_bytes(current_ul)}, 下载={format_bytes(current_dl)}; "
                                f"上次: 上传={format_bytes(last_ul)}, 下载={format_bytes(last_dl)}"
                            )

                    if should_insert:
                        params_to_insert.append(
                            (
                                timestamp_str,
                                client_id,
                                0,
                                0,
                                data_point["ul_speed"],
                                data_point["dl_speed"],
                                current_ul,
                                current_dl,
                            )
                        )

                        # 更新本地缓存的最后记录，用于批次内的后续数据验证
                        last_records[client_id] = {
                            "cumulative_uploaded": current_ul,
                            "cumulative_downloaded": current_dl,
                            "stat_datetime": timestamp_str,
                        }

            if params_to_insert:
                # 根据数据库类型使用正确的占位符和冲突处理语法
                if self.db_manager.db_type == "mysql":
                    sql_insert = """INSERT INTO traffic_stats (stat_datetime, downloader_id, uploaded, downloaded, upload_speed, download_speed, cumulative_uploaded, cumulative_downloaded) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE uploaded = VALUES(uploaded), downloaded = VALUES(downloaded), upload_speed = VALUES(upload_speed), download_speed = VALUES(download_speed), cumulative_uploaded = VALUES(cumulative_uploaded), cumulative_downloaded = VALUES(cumulative_downloaded)"""
                elif self.db_manager.db_type == "postgresql":
                    sql_insert = """INSERT INTO traffic_stats (stat_datetime, downloader_id, uploaded, downloaded, upload_speed, download_speed, cumulative_uploaded, cumulative_downloaded) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT(stat_datetime, downloader_id) DO UPDATE SET uploaded = EXCLUDED.uploaded, downloaded = EXCLUDED.downloaded, upload_speed = EXCLUDED.upload_speed, download_speed = EXCLUDED.download_speed, cumulative_uploaded = EXCLUDED.cumulative_uploaded, cumulative_downloaded = EXCLUDED.cumulative_downloaded"""
                else:  # sqlite
                    sql_insert = """INSERT INTO traffic_stats (stat_datetime, downloader_id, uploaded, downloaded, upload_speed, download_speed, cumulative_uploaded, cumulative_downloaded) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(stat_datetime, downloader_id) DO UPDATE SET uploaded = excluded.uploaded, downloaded = excluded.downloaded, upload_speed = excluded.upload_speed, download_speed = excluded.download_speed, cumulative_uploaded = excluded.cumulative_uploaded, cumulative_downloaded = excluded.cumulative_downloaded"""
                cursor.executemany(sql_insert, params_to_insert)
                logging.info(f"成功插入 {len(params_to_insert)} 条流量记录（已过滤异常数据）")

            conn.commit()
        except Exception as e:
            logging.error(f"将流量缓冲刷新到数据库失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
        finally:
            if conn:
                cursor.close()
                conn.close()

    def _cleanup_duplicate_torrents(self):
        """[已废弃] 旧的启动清理逻辑，保留为空函数以防调用"""
        pass

    def _deduplicate_based_on_active(self, active_hashes):
        """基于活跃种子列表进行智能去重

        策略：
        1. 按 5 参数 (name, save_path, size, sites, group) 分组
        2. 只处理 “同组但 downloader_id 不同” 的重复（同一下载器内重复不处理）
        3. 在一个重复组里只保留一个 downloader（优先保留活跃且 last_seen 最新的那一份）
        2. 对于有重复的组：
           - 检查哪些种子在 active_hashes 中（即当前下载器中存在的）
           - 如果有活跃种子，则保留活跃种子，删除非活跃种子（解决ghost问题）
           - 如果没有活跃种子（都是离线或历史数据），则回退到保留 last_seen 最新的逻辑
        """
        conn = None
        deleted_total = 0
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)

            # 根据数据库类型使用正确的引号包围group字段
            if self.db_manager.db_type == "postgresql":
                group_field = '"group"'
            else:
                group_field = "`group`"

            query = (
                f"SELECT hash, downloader_id, name, save_path, size, sites, {group_field}, last_seen "
                f"FROM torrents"
            )
            cursor.execute(query)

            groups = {}
            for row in cursor.fetchall():
                row_dict = dict(row)
                group_val = row_dict.get("group") or ""

                # 统一做轻量规范化，避免 None/大小写/空白导致“看起来一样但键不相等”
                name_val = (row_dict.get("name") or "").strip()
                save_path_val = (row_dict.get("save_path") or "").strip()
                try:
                    size_val = int(row_dict.get("size") or 0)
                except Exception:
                    size_val = 0
                sites_val = (row_dict.get("sites") or "").strip().lower()
                group_val_norm = (group_val or "").strip().lower()

                attr_key = ("attrs", name_val, save_path_val, size_val, sites_val, group_val_norm)

                if attr_key not in groups:
                    groups[attr_key] = []
                groups[attr_key].append(row_dict)

            to_delete = []
            duplicate_groups = 0
            skipped_same_downloader_groups = 0

            for key, records in groups.items():
                if len(records) < 2:
                    continue

                downloader_ids = {r.get("downloader_id") for r in records if r.get("downloader_id") is not None}
                if len(downloader_ids) < 2:
                    skipped_same_downloader_groups += 1
                    continue

                duplicate_groups += 1

                keep_downloader_id = self._choose_keep_downloader_id_for_dedup(records, active_hashes)
                for r in records:
                    if r.get("downloader_id") != keep_downloader_id:
                        to_delete.append((r["hash"], r["downloader_id"]))
                        logging.info(
                            f"智能去重-跨下载器去重: 保留下载器 {keep_downloader_id}, "
                            f"删除 {r.get('downloader_id')} 的记录 (Hash: {r.get('hash')})"
                        )

            if to_delete:
                placeholder = "%s" if self.db_manager.db_type in ["mysql", "postgresql"] else "?"
                del_sql = f"DELETE FROM torrents WHERE hash={placeholder} AND downloader_id={placeholder}"
                cursor.executemany(del_sql, to_delete)

                stats_del_sql = f"DELETE FROM torrent_upload_stats WHERE hash={placeholder} AND downloader_id={placeholder}"
                cursor.executemany(stats_del_sql, to_delete)

                conn.commit()
                deleted_total = len(to_delete)

            print(
                f"【刷新线程】智能去重统计: 重复组 {duplicate_groups}, "
                f"删除 {deleted_total}, 同下载器重复而跳过 {skipped_same_downloader_groups}"
            )
            return deleted_total

        except Exception as e:
            logging.error(f"智能去重失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return 0
        finally:
            if conn:
                cursor.close()
                conn.close()

    def _choose_keep_downloader_id_for_dedup(self, records, active_hashes):
        """为跨下载器去重选择要保留的 downloader_id。

        规则：
        - 优先在 active_hashes 里的记录中选择（对应“当前启用下载器里实际存在的种子”）
        - 其次选择 last_seen 最新的
        - 再用 downloader_id/hash 做稳定排序避免随机性
        """
        if not records:
            return None

        active_records = [r for r in records if r.get("hash") in active_hashes]
        candidates = active_records or records

        def sort_key(r):
            return (
                str(r.get("last_seen") or ""),
                str(r.get("downloader_id") or ""),
                str(r.get("hash") or ""),
            )

        keep = max(candidates, key=sort_key)
        return keep.get("downloader_id")

    def _normalize_attr_key(self, name, save_path, size, sites, group):
        name_val = (name or "").strip()
        save_path_val = (save_path or "").strip()
        try:
            size_val = int(size or 0)
        except Exception:
            size_val = 0
        sites_val = (sites or "").strip().lower()
        group_val = (group or "").strip().lower()
        return (name_val, save_path_val, size_val, sites_val, group_val)

    def _build_torrents_attribute_index_from_db(self):
        """构建全库的 5 参数索引，用于跨下载器/跨 hash 寻找同一条目。

        key: (name, save_path, size, sites(lower), group(lower))
        value: list[(hash, downloader_id, last_seen)]
        """
        conn = None
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)

            group_field = '"group"' if self.db_manager.db_type == "postgresql" else "`group`"
            cursor.execute(
                f"SELECT hash, downloader_id, name, save_path, size, sites, {group_field}, last_seen FROM torrents"
            )

            index = collections.defaultdict(list)
            for row in cursor.fetchall():
                row_dict = dict(row)
                group_val = row_dict.get("group") or ""
                key = self._normalize_attr_key(
                    row_dict.get("name"),
                    row_dict.get("save_path"),
                    row_dict.get("size"),
                    row_dict.get("sites"),
                    group_val,
                )
                index[key].append(
                    (
                        row_dict.get("hash"),
                        row_dict.get("downloader_id"),
                        row_dict.get("last_seen"),
                    )
                )

            return index
        except Exception as e:
            logging.error(f"构建种子属性索引失败: {e}", exc_info=True)
            return collections.defaultdict(list)
        finally:
            if conn:
                cursor.close()
                conn.close()

    def _startup_rebuild_aggregated_groups_once(self, active_hashes, enabled_downloaders):
        """启动后首次刷新时执行一次的“聚合重建清理”。

        目标：对那些在数据库里残留了旧条目的“聚合种子组”（与前端 /api/data 的聚合一致：name+size），
        执行“整组清空 → 仅回填本次刷新得到的新数据（含上传统计）”。
        """
        enabled_downloader_ids = {d.get("id") for d in enabled_downloaders if d.get("id")}
        if not enabled_downloader_ids:
            return 0
        if not active_hashes:
            return 0

        conn = None
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)
            placeholder = "%s" if self.db_manager.db_type in ["mysql", "postgresql"] else "?"
            group_field = '"group"' if self.db_manager.db_type == "postgresql" else "`group`"

            # 1) 读取全表最小字段，找出“当前活跃的聚合组”（name+size）
            cursor.execute("SELECT hash, downloader_id, name, size FROM torrents")
            rows_min = [dict(r) for r in cursor.fetchall()]

            active_groups = set()
            for r in rows_min:
                if r.get("hash") in active_hashes:
                    try:
                        size_val = int(r.get("size") or 0)
                    except Exception:
                        size_val = 0
                    active_groups.add((r.get("name") or "", size_val))

            if not active_groups:
                return 0

            # 2) 找出需要重建的组：只要该组里存在“非活跃hash”或“非启用下载器”的行
            group_has_stale = {}
            for r in rows_min:
                try:
                    size_val = int(r.get("size") or 0)
                except Exception:
                    size_val = 0
                key = (r.get("name") or "", size_val)
                if key not in active_groups:
                    continue
                if (r.get("hash") not in active_hashes) or (
                    r.get("downloader_id") not in enabled_downloader_ids
                ):
                    group_has_stale[key] = True

            rebuild_groups = set(group_has_stale.keys())
            if not rebuild_groups:
                return 0

            # 3) 拉取这些组的完整 torrents 行（用于回填）并收集要删除的 (hash, downloader_id)
            cursor.execute(
                f"SELECT hash, downloader_id, name, save_path, size, progress, state, sites, details, "
                f"{group_field} AS group_value, last_seen, seeders "
                f"FROM torrents"
            )
            rows_full = [dict(r) for r in cursor.fetchall()]

            delete_pairs = []
            keep_torrent_params = []
            keep_pairs = set()
            for r in rows_full:
                try:
                    size_val = int(r.get("size") or 0)
                except Exception:
                    size_val = 0
                key = (r.get("name") or "", size_val)
                if key not in rebuild_groups:
                    continue

                pair = (r.get("hash"), r.get("downloader_id"))
                if pair[0] is None or pair[1] is None:
                    continue
                delete_pairs.append(pair)

                if pair[0] in active_hashes and pair[1] in enabled_downloader_ids:
                    keep_pairs.add(pair)
                    keep_torrent_params.append(
                        (
                            r.get("hash"),
                            r.get("name"),
                            r.get("save_path"),
                            r.get("size"),
                            r.get("progress"),
                            r.get("state"),
                            r.get("sites") or "",
                            r.get("details") or "",
                            r.get("group_value") or "",
                            r.get("downloader_id"),
                            r.get("last_seen"),
                            r.get("seeders") or 0,
                        )
                    )

            # 4) 备份要回填的上传统计（按 keep_pairs）
            cursor.execute("SELECT hash, downloader_id, uploaded FROM torrent_upload_stats")
            stats_rows = [dict(r) for r in cursor.fetchall()]
            keep_stats_params = []
            for r in stats_rows:
                pair = (r.get("hash"), r.get("downloader_id"))
                if pair in keep_pairs:
                    keep_stats_params.append((r.get("hash"), r.get("downloader_id"), r.get("uploaded") or 0))

            # 5) 删除整组（torrents + upload_stats）
            del_sql = f"DELETE FROM torrents WHERE hash={placeholder} AND downloader_id={placeholder}"
            del_stats_sql = (
                f"DELETE FROM torrent_upload_stats WHERE hash={placeholder} AND downloader_id={placeholder}"
            )
            batch_size = 500
            for i in range(0, len(delete_pairs), batch_size):
                batch = delete_pairs[i : i + batch_size]
                cursor.executemany(del_sql, batch)
                cursor.executemany(del_stats_sql, batch)

            # 6) 回填 torrents
            if self.db_manager.db_type == "mysql":
                insert_sql = (
                    "INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, `group`, downloader_id, last_seen, seeders) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                )
            elif self.db_manager.db_type == "postgresql":
                insert_sql = (
                    'INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, "group", downloader_id, last_seen, seeders) '
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                )
            else:
                insert_sql = (
                    'INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, "group", downloader_id, last_seen, seeders) '
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                )

            for i in range(0, len(keep_torrent_params), batch_size):
                cursor.executemany(insert_sql, keep_torrent_params[i : i + batch_size])

            # 7) 回填上传统计
            if keep_stats_params:
                if self.db_manager.db_type == "mysql":
                    stats_upsert = (
                        "INSERT INTO torrent_upload_stats (hash, downloader_id, uploaded) VALUES (%s, %s, %s) "
                        "ON DUPLICATE KEY UPDATE uploaded=VALUES(uploaded)"
                    )
                elif self.db_manager.db_type == "postgresql":
                    stats_upsert = (
                        "INSERT INTO torrent_upload_stats (hash, downloader_id, uploaded) VALUES (%s, %s, %s) "
                        "ON CONFLICT(hash, downloader_id) DO UPDATE SET uploaded=EXCLUDED.uploaded"
                    )
                else:
                    stats_upsert = (
                        "INSERT INTO torrent_upload_stats (hash, downloader_id, uploaded) VALUES (?, ?, ?) "
                        "ON CONFLICT(hash, downloader_id) DO UPDATE SET uploaded=excluded.uploaded"
                    )
                for i in range(0, len(keep_stats_params), batch_size):
                    cursor.executemany(stats_upsert, keep_stats_params[i : i + batch_size])

            conn.commit()

            print(
                f"【刷新线程】聚合重建统计: 需要重建组 {len(rebuild_groups)}, "
                f"删除行 {len(delete_pairs)}, 回填行 {len(keep_torrent_params)}, 回填上传统计 {len(keep_stats_params)}"
            )
            return len(rebuild_groups)

        except Exception as e:
            logging.error(f"聚合重建清理失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return 0
        finally:
            if conn:
                cursor.close()
                conn.close()

    def update_torrents_in_db(self):
        """优化版本：使用增量同步策略，只处理变化的种子"""
        from datetime import datetime

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logging.info("=== 开始增量更新数据库中的种子 ===")
        print(f"【刷新线程】[{current_time}] 开始增量更新数据库中的种子...")
        config = self.config_manager.get()
        enabled_downloaders = [d for d in config.get("downloaders", []) if d.get("enabled")]
        print(f"【刷新线程】找到 {len(enabled_downloaders)} 个启用的下载器")
        logging.info(f"找到 {len(enabled_downloaders)} 个启用的下载器")
        if not enabled_downloaders:
            logging.info("没有启用的下载器，跳过种子更新。")
            print("【刷新线程】没有启用的下载器，跳过种子更新。")
            return set(), []

        core_domain_map, _, group_to_site_map_lower = load_site_maps_from_db(self.db_manager)
        all_db_attribute_index = self._build_torrents_attribute_index_from_db()

        # 增量同步：按下载器单独处理，减少内存占用
        total_new = 0
        total_updated = 0
        total_deleted = 0
        all_active_hashes = set()

        for downloader in enabled_downloaders:
            print(f"【刷新线程】正在处理下载器: {downloader['name']} (类型: {downloader['type']})")
            try:
                new_count, updated_count, deleted_count, current_hashes = (
                    self._update_downloader_torrents_incremental(
                        downloader,
                        core_domain_map,
                        group_to_site_map_lower,
                        all_db_attribute_index,
                    )
                )
                total_new += new_count
                total_updated += updated_count
                total_deleted += deleted_count
                all_active_hashes.update(current_hashes)

                print(
                    f"【刷新线程】下载器 {downloader['name']} 处理完成: "
                    f"新增 {new_count}, 更新 {updated_count}, 删除 {deleted_count}"
                )
            except Exception as e:
                print(f"【刷新线程】处理下载器 {downloader['name']} 时出错: {e}")
                logging.error(f"处理下载器 {downloader['name']} 时出错: {e}", exc_info=True)
                continue

        # 清理已删除下载器的数据
        self._cleanup_deleted_downloaders(config)

        print(
            f"【刷新线程】=== 增量更新完成: 总新增 {total_new}, 总更新 {total_updated}, 总删除 {total_deleted} ==="
        )
        logging.info(
            f"增量更新完成: 总新增 {total_new}, 总更新 {total_updated}, 总删除 {total_deleted}"
        )
        return all_active_hashes, enabled_downloaders

    def _update_downloader_torrents_incremental(
        self, downloader, core_domain_map, group_to_site_map_lower, all_db_attribute_index
    ):
        """增量同步单个下载器的种子数据"""
        from datetime import datetime

        new_count = 0
        updated_count = 0
        deleted_count = 0

        # 1. 获取下载器中的种子列表
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
                else:
                    print(f"【刷新线程】通过代理获取 '{downloader['name']} 种子信息失败")
                    return 0, 0, 0, set()
            else:
                # 使用常规方式获取种子信息
                client_instance = self._get_client(downloader)
                if not client_instance:
                    print(f"【刷新线程】无法连接到下载器 {downloader['name']}")
                    return 0, 0, 0, set()

                print(f"【刷新线程】正在从 {downloader['name']} 获取种子列表...")
                if downloader["type"] == "qbittorrent":
                    torrents_list = client_instance.torrents_info(status_filter="all")
                elif downloader["type"] == "transmission":
                    fields = [
                        "id",
                        "name",
                        "hashString",
                        "downloadDir",
                        "totalSize",
                        "status",
                        "comment",
                        "trackers",
                        "percentDone",
                        "uploadedEver",
                        "peersGettingFromUs",
                        "trackerStats",
                        "peers",
                        "peersConnected",
                        "sizeWhenDone" # 添加 sizeWhenDone 字段
                    ]
                    torrents_list = client_instance.get_torrents(arguments=fields)

                print(
                    f"【刷新线程】从 '{downloader['name']}' 成功获取到 {len(torrents_list)} 个种子。"
                )
        except Exception as e:
            print(f"【刷新线程】未能从 '{downloader['name']}' 获取数据: {e}")
            logging.error(f"未能从 '{downloader['name']}' 获取数据: {e}")
            return 0, 0, 0, set()

        # 2. 构建当前种子的内存快照
        current_torrents = {}
        for t in torrents_list:
            t_info = self._normalize_torrent_info(t, downloader["type"], client_instance)
            current_torrents[t_info["hash"]] = t_info

        # 3. 查询数据库中该下载器的现有种子
        db_torrents = self._get_downloader_torrents_from_db(downloader["id"])

        # 4. 对比找出变化的种子
        new_torrents, updated_torrents, deleted_hashes = self._compare_torrent_changes(
            current_torrents,
            db_torrents,
            downloader,
            core_domain_map,
            group_to_site_map_lower,
            all_db_attribute_index,
        )

        print(
            f"【刷新线程】下载器 {downloader['name']} 变化分析: "
            f"新增 {len(new_torrents)}, 更新 {len(updated_torrents)}, 删除 {len(deleted_hashes)}"
        )

        # 5. 分批处理变化的数据
        if new_torrents or updated_torrents or deleted_hashes:
            new_count, updated_count, deleted_count = self._process_torrent_changes(
                downloader["id"], new_torrents, updated_torrents, deleted_hashes, current_torrents
            )

        return new_count, updated_count, deleted_count, set(current_torrents.keys())

    def _get_downloader_torrents_from_db(self, downloader_id):
        """从数据库获取指定下载器的所有种子信息"""
        conn = None
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)

            placeholder = "%s" if self.db_manager.db_type in ["mysql", "postgresql"] else "?"
            # 根据数据库类型使用正确的引号包围group字段
            if self.db_manager.db_type == "postgresql":
                group_field = '"group"'
            else:
                group_field = "`group`"

            cursor.execute(
                f"SELECT hash, name, save_path, size, progress, state, sites, details, "
                f"{group_field}, downloader_id, last_seen, seeders FROM torrents "
                f"WHERE downloader_id = {placeholder}",
                (downloader_id,),
            )

            db_torrents = {}
            for row in cursor.fetchall():
                # 处理不同数据库类型返回的字段名差异
                row_dict = dict(row)

                # PostgreSQL返回的字段名可能包含引号，需要处理
                group_key = "group" if "group" in row_dict else '"group"'

                db_torrents[row_dict["hash"]] = {
                    "name": row_dict["name"],
                    "save_path": row_dict["save_path"],
                    "size": row_dict["size"],
                    "progress": row_dict["progress"],
                    "state": row_dict["state"],
                    "sites": row_dict["sites"],
                    "details": row_dict["details"],
                    "group": row_dict.get(group_key),  # 处理可能的字段名差异
                    "downloader_id": row_dict["downloader_id"],
                    "last_seen": row_dict["last_seen"],
                    "seeders": row_dict["seeders"],
                }

            return db_torrents
        except Exception as e:
            logging.error(f"查询下载器 {downloader_id} 的种子数据失败: {e}")
            return {}
        finally:
            if conn:
                cursor.close()
                conn.close()

    def _compare_torrent_changes(
        self,
        current_torrents,
        db_torrents,
        downloader,
        core_domain_map,
        group_to_site_map_lower,
        all_db_attribute_index,
    ):
        """对比当前种子和数据库种子，找出变化的部分（支持基于属性的匹配）"""
        new_torrents = {}
        updated_torrents = {}
        deleted_hashes = set()

        # 预先为所有当前种子计算站点和发布组信息，以确保 fallback 比较逻辑正确
        for hash_value, torrent_info in current_torrents.items():
            site_name = self._find_site_nickname(
                torrent_info["trackers"], core_domain_map, torrent_info["comment"]
            )
            torrent_info["sites"] = site_name
            torrent_info["details"] = _extract_url_from_comment(torrent_info["comment"])
            torrent_info["group"] = self._find_torrent_group(
                torrent_info["name"], group_to_site_map_lower
            )
            torrent_info["downloader_id"] = downloader["id"]

        current_hashes = set(current_torrents.keys())
        db_hashes = set(db_torrents.keys())

        # 构建当前下载器内基于属性的映射，用于处理“同下载器内 hash 变化”的情况
        # key: (name, save_path, size, sites, group), value: hash
        db_attribute_to_hash = {}
        for hash_value, db_info in db_torrents.items():
            attr_key = self._generate_attribute_key(db_info)
            db_attribute_to_hash[attr_key] = hash_value

        # 找出新增和需要更新的种子
        for hash_value, current_info in current_torrents.items():
            if hash_value not in db_hashes:
                # 哈希不在数据库中，尝试用“6 参数”（hash + 5属性）来识别同一条目：
                # - 同下载器内：按 5 属性匹配，视为 hash 变化 -> 替换旧 hash
                # - 跨下载器：按 5 属性匹配，视为迁移覆盖 -> 删除旧 downloader 的记录，保留当前 downloader
                attr_key_raw = self._generate_attribute_key(current_info)
                norm_key = self._normalize_attr_key(
                    current_info.get("name"),
                    current_info.get("save_path"),
                    current_info.get("size"),
                    current_info.get("sites"),
                    current_info.get("group"),
                )

                old_rows_for_replacement = []
                old_hash_for_replacement = None

                # 同下载器内 hash 替换
                if attr_key_raw in db_attribute_to_hash:
                    matched_hash = db_attribute_to_hash[attr_key_raw]
                    old_hash_for_replacement = matched_hash
                    if matched_hash in deleted_hashes:
                        deleted_hashes.remove(matched_hash)

                # 跨下载器覆盖：删除其他 downloader_id 的旧记录（避免 A->B 迁移后产生重复）
                global_matches = (all_db_attribute_index or {}).get(norm_key, [])
                for old_hash, old_downloader_id, _last_seen in global_matches:
                    if old_downloader_id and old_downloader_id != downloader["id"]:
                        old_rows_for_replacement.append((old_hash, old_downloader_id))

                if old_rows_for_replacement or old_hash_for_replacement:
                    updated_torrents[hash_value] = current_info
                    if old_rows_for_replacement:
                        updated_torrents[hash_value]["old_rows_for_replacement"] = old_rows_for_replacement
                    if old_hash_for_replacement:
                        updated_torrents[hash_value]["old_hash_for_replacement"] = old_hash_for_replacement
                else:
                    new_torrents[hash_value] = current_info
            else:
                # 哈希在数据库中，检查是否需要更新
                db_info = db_torrents[hash_value]
                if self._should_update_torrent(current_info, db_info):
                    updated_torrents[hash_value] = current_info

        # 找出删除的种子（排除那些已经被新hash更新的种子）
        deleted_hashes = db_hashes - current_hashes - {
            t.get("old_hash_for_replacement") for t in updated_torrents.values() if "old_hash_for_replacement" in t
        }

        return new_torrents, updated_torrents, deleted_hashes

    def _generate_attribute_key(self, torrent_info):
        """
        生成基于种子属性的唯一键（不包括hash）
        用于处理hash变化的情况
        
        Args:
            torrent_info: 种子信息字典，包含 name, save_path, size, sites, group 等字段
            
        Returns:
            元组: (name, save_path, size, sites, group)
        """
        return (
            torrent_info.get("name", ""),
            torrent_info.get("save_path", ""),
            torrent_info.get("size", 0),
            torrent_info.get("sites", ""),
            torrent_info.get("group", ""),
        )

    def _should_update_torrent(self, current_info, db_info):
        """判断种子是否需要更新"""
        # 检查关键字段是否有变化
        current_progress = round(current_info["progress"] * 100, 1)
        current_state = format_state(current_info["state"])

        # 如果进度有变化，需要更新
        if abs(current_progress - db_info["progress"]) > 0.1:
            return True

        # 如果状态有变化，需要更新
        if current_state != db_info["state"]:
            return True

        # 如果大小有变化，需要更新
        if current_info["size"] != db_info["size"]:
            return True

        # 如果保存路径有变化，需要更新
        if current_info["save_path"] != db_info["save_path"]:
            return True

        # 做种人数变化也需要更新
        current_seeders = current_info.get("seeders", 0)
        if current_seeders != db_info.get("seeders", 0):
            return True

        return False

    def _process_torrent_changes(
        self, downloader_id, new_torrents, updated_torrents, deleted_hashes, current_torrents
    ):
        """处理种子的增删改操作"""
        from datetime import datetime

        new_count = 0
        updated_count = 0
        deleted_count = 0
        upload_count = 0

        conn = None
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            placeholder = "%s" if self.db_manager.db_type in ["mysql", "postgresql"] else "?"

            # 1. 处理删除的种子
            if deleted_hashes:
                deleted_count = self._delete_torrents_batch(
                    cursor, downloader_id, deleted_hashes, placeholder
                )
                print(f"【刷新线程】批量删除了 {deleted_count} 个种子")

            # 2. 处理新增和更新的种子
            all_to_insert = {**new_torrents, **updated_torrents}
            if all_to_insert:
                insert_count, update_count = self._upsert_torrents_batch(
                    cursor, all_to_insert, new_torrents.keys(), now_str, placeholder
                )
                new_count = insert_count
                updated_count = update_count
                print(f"【刷新线程】批量新增 {insert_count} 个，更新 {update_count} 个种子")

            # 3. 处理上传统计
            upload_stats = self._collect_upload_stats(current_torrents, downloader_id)
            if upload_stats:
                upload_count = self._upsert_upload_stats_batch(cursor, upload_stats, placeholder)
                print(f"【刷新线程】批量处理了 {upload_count} 条上传统计")

            conn.commit()
            return new_count, updated_count, deleted_count

        except Exception as e:
            logging.error(f"处理种子变化时出错: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return 0, 0, 0
        finally:
            if conn:
                cursor.close()
                conn.close()

    def _collect_upload_stats(self, current_torrents, downloader_id):
        """收集有上传量的种子统计"""
        upload_stats = []
        for hash_value, torrent_info in current_torrents.items():
            if torrent_info.get("uploaded", 0) > 0:
                upload_stats.append((hash_value, downloader_id, torrent_info["uploaded"]))
        return upload_stats

    def _upsert_upload_stats_batch(self, cursor, upload_stats, placeholder):
        """批量更新上传统计"""
        if not upload_stats:
            return 0

        # 分批处理，每批500条
        batch_size = 500
        total_count = 0

        for i in range(0, len(upload_stats), batch_size):
            batch_stats = upload_stats[i : i + batch_size]

            # 根据数据库类型使用正确的语法
            if self.db_manager.db_type == "mysql":
                sql_upload = """INSERT INTO torrent_upload_stats (hash, downloader_id, uploaded)
                                 VALUES (%s, %s, %s)
                                 ON DUPLICATE KEY UPDATE uploaded=VALUES(uploaded)"""
            elif self.db_manager.db_type == "postgresql":
                sql_upload = """INSERT INTO torrent_upload_stats (hash, downloader_id, uploaded)
                                 VALUES (%s, %s, %s)
                                 ON CONFLICT(hash, downloader_id) DO UPDATE SET uploaded=EXCLUDED.uploaded"""
            else:  # sqlite
                sql_upload = """INSERT INTO torrent_upload_stats (hash, downloader_id, uploaded)
                                 VALUES (?, ?, ?)
                                 ON CONFLICT(hash, downloader_id) DO UPDATE SET uploaded=excluded.uploaded"""

            cursor.executemany(sql_upload, batch_stats)
            total_count += len(batch_stats)

        return total_count

    def _delete_torrents_batch(self, cursor, downloader_id, deleted_hashes, placeholder):
        """批量删除种子"""
        if not deleted_hashes:
            return 0

        # 分类删除：非未做种的直接删除，未做种的检查是否有同名种子在做种
        # 先查询要删除种子的状态和名称
        placeholders = ",".join([placeholder] * len(deleted_hashes))
        cursor.execute(
            f"SELECT hash, name, state FROM torrents WHERE hash IN ({placeholders}) AND downloader_id = {placeholder}",
            tuple(list(deleted_hashes) + [downloader_id]),
        )
        torrents_to_check = cursor.fetchall()

        # 获取当前正在做种的种子名称
        cursor.execute(
            "SELECT DISTINCT name FROM torrents WHERE state NOT IN ('未做种', '已暂停', '已停止', '错误', '等待', '队列')"
        )
        seeding_names = {row["name"] for row in cursor.fetchall()}

        # 分类处理
        hashes_to_delete = []
        for torrent in torrents_to_check:
            if torrent["state"] != "未做种":
                hashes_to_delete.append(torrent["hash"])
            else:
                # 未做种的种子，检查是否有其他同名种子在做种
                if torrent["name"] not in seeding_names:
                    hashes_to_delete.append(torrent["hash"])

        # 执行删除
        if hashes_to_delete:
            delete_placeholders = ",".join([placeholder] * len(hashes_to_delete))
            cursor.execute(
                f"DELETE FROM torrents WHERE hash IN ({delete_placeholders}) AND downloader_id = {placeholder}",
                tuple(hashes_to_delete + [downloader_id]),
            )
            return cursor.rowcount

        return 0

    def _upsert_torrents_batch(
        self, cursor, torrents_to_process, new_hashes, now_str, placeholder
    ):
        """批量新增或更新种子（支持hash替换）"""
        if not torrents_to_process:
            return 0, 0

        # 先处理 hash / downloader 覆盖替换的情况
        for hash_value, torrent_info in list(torrents_to_process.items()):
            old_rows = []
            if "old_rows_for_replacement" in torrent_info:
                old_rows.extend(list(torrent_info["old_rows_for_replacement"]))
            if "old_hash_for_replacement" in torrent_info:
                old_rows.append((torrent_info["old_hash_for_replacement"], torrent_info["downloader_id"]))

            if old_rows:
                delete_sql = f"DELETE FROM torrents WHERE hash = {placeholder} AND downloader_id = {placeholder}"
                delete_upload_sql = (
                    f"DELETE FROM torrent_upload_stats WHERE hash = {placeholder} AND downloader_id = {placeholder}"
                )
                for old_hash, old_downloader_id in old_rows:
                    cursor.execute(delete_sql, (old_hash, old_downloader_id))
                    cursor.execute(delete_upload_sql, (old_hash, old_downloader_id))

                torrent_info.pop("old_rows_for_replacement", None)
                torrent_info.pop("old_hash_for_replacement", None)

                logging.info(
                    f"种子 '{torrent_info.get('name', 'unknown')[:50]}...' 覆盖旧记录 {len(old_rows)} 条 -> 新 (Hash: {hash_value}, DL: {torrent_info.get('downloader_id')})"
                )

        # 准备数据
        params = []
        new_count = 0
        update_count = 0

        for hash_value, torrent_info in torrents_to_process.items():
            param = (
                torrent_info["hash"],
                torrent_info["name"],
                torrent_info["save_path"],
                torrent_info["size"],
                round(torrent_info["progress"] * 100, 1),
                format_state(torrent_info["state"]),
                torrent_info.get("sites", ""),
                torrent_info.get("details", ""),
                torrent_info.get("group", ""),
                torrent_info["downloader_id"],
                now_str,
                torrent_info.get("seeders", 0),
            )
            params.append(param)

        # 分批处理，每批500条
        batch_size = 500
        for i in range(0, len(params), batch_size):
            batch_params = params[i : i + batch_size]

            # 根据数据库类型使用正确的语法
            if self.db_manager.db_type == "mysql":
                sql = """INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, `group`, downloader_id, last_seen, seeders)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                         ON DUPLICATE KEY UPDATE
                         name=VALUES(name), save_path=VALUES(save_path), size=VALUES(size),
                         progress=VALUES(progress), state=VALUES(state),
                         sites=COALESCE(NULLIF(VALUES(sites), ''), sites),
                         details=IF(VALUES(details) != '', VALUES(details), details),
                         `group`=COALESCE(NULLIF(VALUES(`group`), ''), `group`),
                         downloader_id=VALUES(downloader_id), last_seen=VALUES(last_seen),
                         seeders=VALUES(seeders)"""
            elif self.db_manager.db_type == "postgresql":
                sql = """INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, "group", downloader_id, last_seen, seeders)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                         ON CONFLICT(hash, downloader_id) DO UPDATE SET
                         name=excluded.name, save_path=excluded.save_path, size=excluded.size,
                         progress=excluded.progress, state=excluded.state,
                         sites=COALESCE(NULLIF(excluded.sites, ''), torrents.sites),
                         details=CASE WHEN excluded.details != '' THEN excluded.details ELSE torrents.details END,
                         "group"=COALESCE(NULLIF(excluded."group", ''), torrents."group"),
                         downloader_id=excluded.downloader_id, last_seen=excluded.last_seen,
                         seeders=excluded.seeders"""
            else:  # sqlite
                sql = """INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, "group", downloader_id, last_seen, seeders)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                         ON CONFLICT(hash, downloader_id) DO UPDATE SET
                         name=excluded.name, save_path=excluded.save_path, size=excluded.size,
                         progress=excluded.progress, state=excluded.state,
                         sites=COALESCE(NULLIF(excluded.sites, ''), torrents.sites),
                         details=CASE WHEN excluded.details != '' THEN excluded.details ELSE torrents.details END,
                         "group"=COALESCE(NULLIF(excluded."group", ''), torrents."group"),
                         downloader_id=excluded.downloader_id, last_seen=excluded.last_seen,
                         seeders=excluded.seeders"""

            cursor.executemany(sql, batch_params)

            # 统计新增和更新数量（简化统计）
            batch_new_hashes = set()
            for j, param in enumerate(batch_params):
                hash_val = param[0]
                if hash_val in new_hashes:
                    batch_new_hashes.add(hash_val)

            new_count += len(batch_new_hashes)
            update_count += len(batch_params) - len(batch_new_hashes)

        return new_count, update_count

    def _cleanup_deleted_downloaders(self, config):
        """清理已删除下载器的种子数据"""
        conn = None
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)
            placeholder = "%s" if self.db_manager.db_type in ["mysql", "postgresql"] else "?"

            # 获取配置中所有下载器的ID（包括启用和禁用的）
            all_configured_downloaders = {d["id"] for d in config.get("downloaders", [])}

            # 获取当前数据库中存在的所有下载器ID
            cursor.execute(
                "SELECT DISTINCT downloader_id FROM torrents WHERE downloader_id IS NOT NULL"
            )
            existing_downloader_ids = {row["downloader_id"] for row in cursor.fetchall()}

            # 计算应该删除种子数据的下载器ID（已从配置中删除的下载器）
            deleted_downloader_ids = existing_downloader_ids - all_configured_downloaders

            # 只删除已从配置中删除的下载器的种子数据
            if deleted_downloader_ids:
                downloader_placeholders = ",".join([placeholder] * len(deleted_downloader_ids))
                delete_query = (
                    f"DELETE FROM torrents WHERE downloader_id IN ({downloader_placeholders})"
                )
                cursor.execute(delete_query, tuple(deleted_downloader_ids))
                deleted_count = cursor.rowcount
                print(f"【刷新线程】从 torrents 表中移除了 {deleted_count} 个已删除下载器的种子。")
                logging.info(f"从 torrents 表中移除了 {deleted_count} 个已删除下载器的种子。")

            conn.commit()
        except Exception as e:
            logging.error(f"清理已删除下载器数据失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
        finally:
            if conn:
                cursor.close()
                conn.close()

    def _update_torrents_in_db_original(self):
        """原始版本：保留作为备份"""
        from datetime import datetime

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logging.info("=== 开始更新数据库中的种子 ===")
        print(f"【刷新线程】[{current_time}] 开始更新数据库中的种子...")
        config = self.config_manager.get()
        enabled_downloaders = [d for d in config.get("downloaders", []) if d.get("enabled")]
        print(f"【刷新线程】找到 {len(enabled_downloaders)} 个启用的下载器")
        logging.info(f"找到 {len(enabled_downloaders)} 个启用的下载器")
        if not enabled_downloaders:
            logging.info("没有启用的下载器，跳过种子更新。")
            print("【刷新线程】没有启用的下载器，跳过种子更新。")
            return

        core_domain_map, _, group_to_site_map_lower = load_site_maps_from_db(self.db_manager)
        all_current_hashes = set()
        torrents_to_upsert, upload_stats_to_upsert = {}, []
        is_mysql = self.db_manager.db_type == "mysql"

        for downloader in enabled_downloaders:
            print(f"【刷新线程】正在处理下载器: {downloader['name']} (类型: {downloader['type']})")
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
                        logging.warning(f"通过代理获取 '{downloader['name']}' 种子信息失败")
                        continue
                else:
                    # 使用常规方式获取种子信息
                    client_instance = self._get_client(downloader)
                    if not client_instance:
                        print(f"【刷新线程】无法连接到下载器 {downloader['name']}")
                        continue

                    print(f"【刷新线程】正在从 {downloader['name']} 获取种子列表...")
                    if downloader["type"] == "qbittorrent":
                        torrents_list = client_instance.torrents_info(status_filter="all")
                    elif downloader["type"] == "transmission":
                        fields = [
                            "id",
                            "name",
                            "hashString",
                            "downloadDir",
                            "totalSize",
                            "status",
                            "comment",
                            "trackers",
                            "percentDone",
                            "uploadedEver",
                            "peersGettingFromUs",
                            "trackerStats",
                            "peers",
                            "peersConnected",
                        ]
                        torrents_list = client_instance.get_torrents(arguments=fields)
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
                t_info = self._normalize_torrent_info(t, downloader["type"], client_instance)
                all_current_hashes.add(t_info["hash"])

                # 使用复合主键 (hash, downloader_id) 作为唯一标识
                composite_key = f"{t_info['hash']}_{downloader['id']}"
                if (
                    composite_key not in torrents_to_upsert
                    or t_info["progress"] > torrents_to_upsert[composite_key]["progress"]
                ):
                    site_name = self._find_site_nickname(
                        t_info["trackers"], core_domain_map, t_info["comment"]
                    )
                    torrents_to_upsert[composite_key] = {
                        "hash": t_info["hash"],
                        "name": t_info["name"],
                        "save_path": t_info["save_path"],
                        "size": t_info["size"],
                        "progress": round(t_info["progress"] * 100, 1),
                        "state": format_state(t_info["state"]),
                        "sites": site_name,
                        "details": _extract_url_from_comment(t_info["comment"]),
                        "group": self._find_torrent_group(t_info["name"], group_to_site_map_lower),
                        "downloader_id": downloader["id"],
                        "seeders": t_info.get("seeders", 0),
                    }
                if t_info["uploaded"] > 0:
                    upload_stats_to_upsert.append(
                        (t_info["hash"], downloader["id"], t_info["uploaded"])
                    )
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

            # 优化：预先构建下载器到种子的映射，避免每次都遍历所有复合键
            downloader_to_hashes = {}
            for composite_key, torrent_data in torrents_to_upsert.items():
                downloader_id = torrent_data["downloader_id"]
                hash_value = composite_key.rsplit("_", 1)[0]  # 从 "hash_downloader_id" 提取 hash

                if downloader_id not in downloader_to_hashes:
                    downloader_to_hashes[downloader_id] = set()
                downloader_to_hashes[downloader_id].add(hash_value)

            for downloader_id in enabled_downloader_ids:
                # 直接使用预构建的映射，避免O(n²)复杂度
                downloader_current_hashes = downloader_to_hashes.get(downloader_id, set())

                # 获取数据库中该下载器的历史种子哈希
                placeholder = "%s" if self.db_manager.db_type in ["mysql", "postgresql"] else "?"
                cursor.execute(
                    f"SELECT hash, name, state FROM torrents WHERE downloader_id = {placeholder}",
                    (downloader_id,),
                )
                db_torrents = {
                    row["hash"]: {"name": row["name"], "state": row["state"]}
                    for row in cursor.fetchall()
                }

                # 找出需要删除的种子（在数据库中但不在当前下载器中）
                hashes_to_delete = db_torrents.keys() - downloader_current_hashes

                if hashes_to_delete:
                    print(
                        f"【刷新线程】发现下载器 {downloader_id} 中有 {len(hashes_to_delete)} 个种子已被删除"
                    )

                    # 获取当前所有正在做种的种子名称（包括当前正在处理的种子和数据库中其他下载器的种子）
                    current_seeding_names = set()

                    # 添加当前正在处理的种子中正在做种的名称
                    for torrent_data in torrents_to_upsert.values():
                        if torrent_data["state"] not in [
                            "未做种",
                            "已暂停",
                            "已停止",
                            "错误",
                            "等待",
                            "队列",
                        ]:
                            current_seeding_names.add(torrent_data["name"])

                    # 添加数据库中其他下载器的正在做种的种子名称
                    other_downloaders_placeholders = ",".join(
                        [placeholder] * len(enabled_downloader_ids - {downloader_id})
                    )
                    if enabled_downloader_ids - {downloader_id}:  # 如果还有其他下载器
                        cursor.execute(
                            f"SELECT DISTINCT name FROM torrents WHERE downloader_id IN ({other_downloaders_placeholders}) AND state NOT IN ('未做种', '已暂停', '已停止', '错误', '等待', '队列')",
                            tuple(enabled_downloader_ids - {downloader_id}),
                        )
                        other_seeding_names = {row["name"] for row in cursor.fetchall()}
                        current_seeding_names.update(other_seeding_names)

                    # 分类要删除的种子
                    hashes_to_delete_normal = []  # 状态不是'未做种'的，直接删除
                    hashes_to_delete_inactive_seed = (
                        []
                    )  # 状态是'未做种'但没有其他同名种子在做种的，也要删除

                    for hash_value in hashes_to_delete:
                        torrent_info = db_torrents[hash_value]
                        if torrent_info["state"] != "未做种":
                            # 状态不是'未做种'，直接删除
                            hashes_to_delete_normal.append(hash_value)
                        else:
                            # 状态是'未做种'，检查是否有其他同名种子在做种
                            if torrent_info["name"] not in current_seeding_names:
                                # 没有其他同名种子在做种，删除这个'未做种'的种子
                                hashes_to_delete_inactive_seed.append(hash_value)

                    # 初始化删除计数器
                    deleted_count_normal = 0
                    deleted_count_inactive = 0

                    # 删除状态不是'未做种'的种子
                    if hashes_to_delete_normal:
                        delete_placeholders = ",".join(
                            [placeholder] * len(hashes_to_delete_normal)
                        )
                        delete_query = f"DELETE FROM torrents WHERE hash IN ({delete_placeholders}) AND downloader_id = {placeholder}"
                        cursor.execute(
                            delete_query, tuple(hashes_to_delete_normal) + (downloader_id,)
                        )
                        deleted_count_normal = cursor.rowcount
                        print(
                            f"【刷新线程】已删除下载器 {downloader_id} 中的 {deleted_count_normal} 个已移除的非未做种种子"
                        )

                    # 删除状态是'未做种'但没有其他同名种子在做种的种子
                    if hashes_to_delete_inactive_seed:
                        delete_placeholders = ",".join(
                            [placeholder] * len(hashes_to_delete_inactive_seed)
                        )
                        delete_query = f"DELETE FROM torrents WHERE hash IN ({delete_placeholders}) AND downloader_id = {placeholder}"
                        cursor.execute(
                            delete_query, tuple(hashes_to_delete_inactive_seed) + (downloader_id,)
                        )
                        deleted_count_inactive = cursor.rowcount
                        print(
                            f"【刷新线程】已删除下载器 {downloader_id} 中的 {deleted_count_inactive} 个已移除的未做种种子（没有其他同名种子在做种）"
                        )

                    total_deleted = deleted_count_normal + deleted_count_inactive
                    print(
                        f"【刷新线程】已删除下载器 {downloader_id} 中的 {total_deleted} 个已移除的种子记录"
                    )
                    logging.info(
                        f"已删除下载器 {downloader_id} 中的 {total_deleted} 个已移除的种子记录"
                    )

            if torrents_to_upsert:
                # 确保参数顺序与 SQL 语句完全匹配
                params = [
                    (
                        d["hash"],
                        d["name"],
                        d["save_path"],
                        d["size"],
                        d["progress"],
                        d["state"],
                        d["sites"],
                        d["details"],
                        d["group"],
                        d["downloader_id"],
                        now_str,
                        d["seeders"],
                    )
                    for d in torrents_to_upsert.values()
                ]
                print(f"【刷新线程】准备写入 {len(params)} 条种子主信息到数据库")
                # 根据数据库类型使用正确的引号和冲突处理语法
                # save_path 强制覆盖，其他字段保持原有的覆盖/保留逻辑
                # 注意：现在使用复合主键(hash, downloader_id)，所以冲突条件也要相应调整
                if self.db_manager.db_type == "mysql":
                    sql = """INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, `group`, downloader_id, last_seen, seeders) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE name=VALUES(name), save_path=VALUES(save_path), size=VALUES(size), progress=VALUES(progress), state=VALUES(state), sites=COALESCE(NULLIF(VALUES(sites), ''), sites), details=IF(VALUES(details) != '', VALUES(details), details), `group`=COALESCE(NULLIF(VALUES(`group`), ''), `group`), downloader_id=VALUES(downloader_id), last_seen=VALUES(last_seen), seeders=VALUES(seeders)"""
                elif self.db_manager.db_type == "postgresql":
                    sql = """INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, "group", downloader_id, last_seen, seeders) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT(hash, downloader_id) DO UPDATE SET name=excluded.name, save_path=excluded.save_path, size=excluded.size, progress=excluded.progress, state=excluded.state, sites=COALESCE(NULLIF(excluded.sites, ''), torrents.sites), details=CASE WHEN excluded.details != '' THEN excluded.details ELSE torrents.details END, "group"=COALESCE(NULLIF(excluded."group", ''), torrents."group"), downloader_id=excluded.downloader_id, last_seen=excluded.last_seen, seeders=excluded.seeders"""
                else:  # sqlite
                    sql = """INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, "group", downloader_id, last_seen, seeders) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(hash, downloader_id) DO UPDATE SET name=excluded.name, save_path=excluded.save_path, size=excluded.size, progress=excluded.progress, state=excluded.state, sites=COALESCE(NULLIF(excluded.sites, ''), torrents.sites), details=CASE WHEN excluded.details != '' THEN excluded.details ELSE torrents.details END, "group"=COALESCE(NULLIF(excluded."group", ''), torrents."group"), downloader_id=excluded.downloader_id, last_seen=excluded.last_seen, seeders=excluded.seeders"""
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
            placeholder = "%s" if self.db_manager.db_type in ["mysql", "postgresql"] else "?"

            print(f"【刷新线程】检查是否需要删除已移除下载器的种子数据...")
            # 修改删除逻辑：只删除已从配置中删除的下载器的种子数据，保留已禁用下载器的种子数据
            # 获取配置中所有下载器的ID（包括启用和禁用的）
            all_configured_downloaders = {d["id"] for d in config.get("downloaders", [])}

            # 获取当前数据库中存在的所有下载器ID
            cursor.execute(
                "SELECT DISTINCT downloader_id FROM torrents WHERE downloader_id IS NOT NULL"
            )
            existing_downloader_ids = {row["downloader_id"] for row in cursor.fetchall()}

            # 计算应该删除种子数据的下载器ID（已从配置中删除的下载器）
            deleted_downloader_ids = existing_downloader_ids - all_configured_downloaders

            # 只删除已从配置中删除的下载器的种子数据，保留已禁用下载器的种子数据
            if deleted_downloader_ids:
                print(
                    f"【刷新线程】发现 {len(deleted_downloader_ids)} 个已删除的下载器，将移除其种子数据"
                )
                # 构建 WHERE 子句
                downloader_placeholders = ",".join([placeholder] * len(deleted_downloader_ids))
                delete_query = (
                    f"DELETE FROM torrents WHERE downloader_id IN ({downloader_placeholders})"
                )
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
            if conn:
                conn.rollback()
        finally:
            if conn:
                cursor.close()
                conn.close()

    def _normalize_torrent_info(self, t, client_type, client_instance=None):
        if client_type == "qbittorrent":
            # --- DEBUG START ---
            try:
                # Handle both dict and object access for hash
                t_hash = t.get("hash") if isinstance(t, dict) else getattr(t, "hash", "")
                if t_hash and t_hash.lower() == "d68a9eefd16e335714afd59d85af8b532024de3d":
                    print(f"[DEBUG] _normalize_torrent_info hit for target hash: {t_hash}")
                    print(f"[DEBUG] type(t): {type(t)}")

                    val_total_size = t.get("total_size") if isinstance(t, dict) else getattr(t, "total_size", "N/A")
                    val_size = t.get("size") if isinstance(t, dict) else getattr(t, "size", "N/A")

                    print(f"[DEBUG] total_size: {val_total_size}")
                    print(f"[DEBUG] size: {val_size}")
            except Exception as e:
                print(f"[DEBUG] Exception in debug block: {e}")
            # --- DEBUG END ---

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

                # 计算真实的完成百分比
                # 如果是部分下载，t.progress可能显示1.0（100%），但实际上只下载了部分文件
                # 我们希望显示的是占整个种子大小的比例
                try:
                    total_size = t.get("total_size", 0) if isinstance(t, dict) else getattr(t, "total_size", 0)
                    size_selected = t.get("size", 0) if isinstance(t, dict) else getattr(t, "size", 0)
                    progress_raw = t.get("progress", 0) if isinstance(t, dict) else getattr(t, "progress", 0)

                    # 只有当勾选大小小于总大小时，才需要重新计算进度
                    if total_size > 0 and size_selected > 0 and size_selected < total_size:
                        # 计算当前已下载的大小
                        downloaded_size = size_selected * progress_raw
                        # 计算相对于总大小的进度
                        calculated_progress = downloaded_size / total_size
                        # print(f"[DEBUG] Recalculating progress for {t.get('name', 'unknown')}: {progress_raw:.4f} -> {calculated_progress:.4f} (selected: {size_selected}, total: {total_size})")
                        progress = calculated_progress
                    else:
                        progress = progress_raw
                except Exception as e:
                    logging.warning(f"Error calculating progress: {e}")
                    progress = t.get("progress", 0) if isinstance(t, dict) else getattr(t, "progress", 0)

                info = {
                    "name": t.get("name", "") if isinstance(t, dict) else getattr(t, "name", ""),
                    "hash": t.get("hash", "") if isinstance(t, dict) else getattr(t, "hash", ""),
                    "save_path": t.get("save_path", "") if isinstance(t, dict) else getattr(t, "save_path", ""),
                    "size": t.get("total_size", 0) if isinstance(t, dict) else getattr(t, "total_size", 0), # 使用 total_size 作为种子总大小
                    "progress": progress,
                    "state": t.get("state", "") if isinstance(t, dict) else getattr(t, "state", ""),
                    "comment": t.get("comment", "") if isinstance(t, dict) else t.get("comment", ""), # 对于对象，get("comment", "") 可能不适用，稍后处理
                    "trackers": trackers_list if isinstance(t, dict) else trackers_data,
                    "uploaded": t.get("uploaded", 0) if isinstance(t, dict) else getattr(t, "uploaded", 0),
                    "seeders": t.get("num_complete", 0) if isinstance(t, dict) else getattr(t, "num_complete", 0),
                }

                # 对于非字典类型，单独处理comment
                if not isinstance(t, dict):
                     info["comment"] = t.get("comment", "")

                # 移除之前的调试代码
                # ...


                # --- [核心修正] ---
                # 基于成功的测试脚本，实现可靠的备用方案
                if not info["comment"] and client_instance:
                    logging.debug(f"种子 '{t.name[:30]}...' 的注释为空，尝试备用接口获取。")
                    try:
                        # 1. 从客户端实例中提取 SID cookie
                        sid_cookie = client_instance._session.cookies.get("SID")
                        if sid_cookie:
                            cookies_for_request = {"SID": sid_cookie}

                            # 2. 构造请求
                            # 使用 client.host 属性，这是库提供的公共接口，比_host更稳定
                            base_url = client_instance.host
                            properties_url = f"{base_url}/api/v2/torrents/properties"
                            params = {"hash": t.hash}

                            # 3. 发送手动请求
                            response = requests.get(
                                properties_url,
                                params=params,
                                cookies=cookies_for_request,
                                timeout=10,
                            )
                            response.raise_for_status()

                            # 4. 解析并更新 comment
                            properties_data = response.json()
                            fallback_comment = properties_data.get("comment", "")

                            if fallback_comment:
                                logging.info(
                                    f"成功通过备用接口为种子 '{t.name[:30]}...' 获取到注释。"
                                )
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
                # 获取做种人数：tracker 统计中的网络种子数
                seeders = 0
                if t.get("trackerStats"):
                    # 从tracker统计中获取种子数，使用最大的有效值
                    valid_seeds = [
                        tracker.get("seederCount", 0)
                        for tracker in t.get("trackerStats", [])
                        if tracker.get("seederCount", 0) > 0
                    ]
                    if valid_seeds:
                        seeders = max(valid_seeds)  # 使用最大的有效种子数

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
                    "seeders": seeders,
                }
            else:
                # 从客户端获取的数据是对象格式
                # 获取做种人数：tracker 统计中的网络种子数
                seeders = 0
                try:
                    # 从 tracker_stats 获取种子数
                    if hasattr(t, "fields") and "trackerStats" in t.fields:
                        tracker_stats = t.fields.get("trackerStats", [])
                        if tracker_stats:
                            # 获取所有有效的种子数，使用最大的有效值
                            valid_seeds = [
                                tracker.get("seederCount", 0)
                                for tracker in tracker_stats
                                if tracker.get("seederCount", 0) > 0
                            ]
                            if valid_seeds:
                                seeders = max(valid_seeds)
                except Exception as e:
                    logging.debug(f"Failed to get tracker_stats: {e}")

                # 计算真实的完成百分比
                try:
                    total_size = getattr(t, "total_size", 0)
                    # 从fields中获取sizeWhenDone，或者直接获取
                    size_when_done = 0
                    if hasattr(t, "fields"):
                        size_when_done = t.fields.get("sizeWhenDone", 0)
                    elif hasattr(t, "size_when_done"):
                        size_when_done = t.size_when_done

                    progress_raw = t.get("percentDone", 0) if isinstance(t, dict) else getattr(t, "percent_done", 0)

                    # 只有当欲下载大小小于总大小时，才需要重新计算进度
                    # 注意：Transmission的progress通常已经是相对于sizeWhenDone的了，但如果我们要显示相对于总大小的进度：
                    # 下载进度 = 已下载大小 / 总大小
                    # 已下载大小 = sizeWhenDone * progress_raw (假设progress_raw是相对于sizeWhenDone的)
                    # 但实际上，如果只下载一部分，我们希望看到的进度是已完成部分占总大小的比例

                    if total_size > 0 and size_when_done > 0 and size_when_done < total_size:
                        # 计算当前已下载的大小 (Transmission的percentDone通常是针对sizeWhenDone的)
                        downloaded_size = size_when_done * progress_raw
                        # 计算相对于总大小的进度
                        calculated_progress = downloaded_size / total_size
                        progress = calculated_progress
                    else:
                        progress = progress_raw
                except Exception as e:
                    logging.warning(f"Error calculating transmission progress: {e}")
                    progress = t.get("percentDone", 0) if isinstance(t, dict) else getattr(t, "percent_done", 0)

                return {
                    "name": t.name,
                    "hash": t.hash_string,
                    "save_path": t.download_dir,
                    "size": t.total_size, # 使用 total_size 作为种子总大小
                    "progress": progress,
                    "state": t.status,
                    "comment": getattr(t, "comment", ""),
                    "trackers": [{"url": tracker.get("announce")} for tracker in t.trackers],
                    "uploaded": t.uploaded_ever,
                    "seeders": seeders,
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
                        logging.info(
                            f"通过 comment URL 匹配到站点: {matched_site} (域名: {core_domain})"
                        )
                        return matched_site

        return None

    def _find_torrent_group(self, name, group_to_site_map_lower):
        """查找种子的发布组名称，支持@符号前后匹配。

        对于包含@符号的种子名称，会分别检查@前后的部分是否匹配官组名称。
        支持多种格式：
        - FFans@leon -> 检查"FFans"和"leon"
        - AnimeF@ADE -> 优先精确匹配"ADE"，避免匹配到"ADEbook"
        - 7³ACG@OurBits -> 检查"7³acg"和"ourbits"
        - [xxx]@OurBits -> 先去除[]后检查"ourbits"
        """
        name_lower = name.lower()
        exact_matches = []  # 精确匹配结果
        partial_matches = []  # 部分匹配结果

        # 检查是否包含@符号
        if "@" in name_lower:
            # 分割@符号前后的部分
            parts = name_lower.split("@")
            logging.debug(f"种子名称包含@符号，分割为: {parts}")

            for part in parts:
                # 清理每个部分：
                # 1. 去除首尾空格
                # 2. 去除前导的-符号
                # 3. 去除方括号[]内的内容（处理[BDrip]这种格式）
                clean_part = part.strip().lstrip("-").strip()

                # 处理方括号：去除[xxx]格式，保留括号外的内容
                import re

                clean_part = re.sub(r"\[.*?\]", "", clean_part).strip()

                if clean_part:
                    logging.debug(f"检查部分: '{clean_part}'")

                    # 先检查精确匹配
                    for group_lower, group_info in group_to_site_map_lower.items():
                        # 去除官组名称前面的-（如果有）
                        group_lower_clean = group_lower.lstrip("-")

                        # 精确匹配（优先级最高）
                        if group_lower_clean == clean_part:
                            if group_info["original_case"] not in exact_matches:
                                exact_matches.append(group_info["original_case"])
                                logging.debug(f"精确匹配到官组: '{group_info['original_case']}'")
                        # 包含匹配（次优先级）
                        elif group_lower_clean in clean_part or clean_part in group_lower_clean:
                            if (
                                group_info["original_case"] not in partial_matches
                                and group_info["original_case"] not in exact_matches
                            ):
                                partial_matches.append(group_info["original_case"])
                                logging.debug(f"部分匹配到官组: '{group_info['original_case']}'")

        # 合并结果：精确匹配优先
        found_matches = exact_matches + partial_matches

        # 如果@符号匹配没有结果，或者名称中没有@符号，使用原来的全名匹配逻辑
        if not found_matches:
            logging.debug(f"@符号匹配无结果，尝试全名匹配: '{name_lower}'")
            for group_lower, group_info in group_to_site_map_lower.items():
                if group_lower in name_lower:
                    if group_info["original_case"] not in found_matches:
                        found_matches.append(group_info["original_case"])
                        logging.debug(
                            f"匹配到官组: '{group_info['original_case']}' (通过全名匹配)"
                        )

        if found_matches:
            # 如果有精确匹配，优先返回最短的精确匹配（最准确）
            # 如果没有精确匹配，返回最长的部分匹配（避免匹配到子串）
            if exact_matches:
                result = sorted(exact_matches, key=len)[0]  # 最短的精确匹配
                logging.info(f"种子 '{name[:50]}...' 精确匹配到官组: {result}")
            else:
                result = sorted(found_matches, key=len, reverse=True)[0]  # 最长的匹配
                logging.info(f"种子 '{name[:50]}...' 匹配到官组: {result}")
            return result

        logging.debug(f"种子 '{name[:50]}...' 未识别到官组")
        return None

    def stop(self):
        logging.info("正在停止 DataTracker 线程...")
        self._is_running = False
        self.shutdown_event.set()
        with self.traffic_buffer_lock:
            if self.traffic_buffer:
                self._flush_traffic_buffer_to_db(self.traffic_buffer)
                self.traffic_buffer = []


def start_data_tracker(db_manager, config_manager):
    """初始化并启动全局 DataTracker 线程实例。"""
    global data_tracker_thread
    # 检查是否在调试模式下运行，避免重复启动
    import os

    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
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
        # 使用更短的超时时间，因为现在有event驱动的优雅停止
        data_tracker_thread.join(timeout=2)  # 从10秒减少到2秒
        if data_tracker_thread.is_alive():
            print("DataTracker 线程仍在运行，但将强制清理引用")
        else:
            print("DataTracker 线程已优雅停止。")
        logging.info("DataTracker 线程已停止。")
    data_tracker_thread = None
