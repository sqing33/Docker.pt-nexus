# routes.py

import json
import logging
import copy
import uuid
import cloudscraper
from flask import Blueprint, jsonify, request
from threading import Thread
from datetime import datetime, timedelta
from collections import defaultdict
from functools import cmp_to_key
from urllib.parse import urlparse

# 导入迁移服务
from migrator_service import TorrentMigrator

import services
from services import CACHE_LOCK, load_site_maps_from_db, start_data_tracker, stop_data_tracker
from utils import custom_sort_compare, format_bytes
from qbittorrentapi import Client, APIConnectionError
from transmission_rpc import Client as TrClient, TransmissionError

api_bp = Blueprint("api", __name__, url_prefix="/api")

db_manager = None
config_manager = None


def initialize_routes(manager, conf_manager):
    """注入实例以供路由使用。"""
    global db_manager, config_manager
    db_manager = manager
    config_manager = conf_manager


# --- [修改] 获取站点列表的 API (迁移工具用) ---
@api_bp.route("/sites_list", methods=["GET"])
def get_sites_list():
    """获取可用于迁移的源站点和目标站点列表。"""
    conn = None
    cursor = None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        # 获取源站点 (必须有Cookie)
        cursor.execute(
            "SELECT nickname FROM sites WHERE cookie IS NOT NULL AND cookie != '' ORDER BY nickname"
        )
        source_sites = [row["nickname"] for row in cursor.fetchall()]

        # 获取目标站点 (必须有Passkey)
        cursor.execute(
            "SELECT nickname FROM sites WHERE passkey IS NOT NULL AND passkey != '' ORDER BY nickname"
        )
        target_sites = [row["nickname"] for row in cursor.fetchall()]

        return jsonify({"source_sites": source_sites, "target_sites": target_sites})
    except Exception as e:
        logging.error(f"get_sites_list 出错: {e}", exc_info=True)
        return jsonify({"error": "获取站点列表失败"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# --- [修改] 获取站点详细信息的 API ---
@api_bp.route("/sites", methods=["GET"])
def get_sites():
    """获取所有站点的完整详细列表，可根据种子存在情况进行筛选。"""
    # 新增：从请求参数获取筛选条件，默认为 'all'
    filter_by_torrents = request.args.get("filter_by_torrents", "all")

    conn = None
    cursor = None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        # 基础查询字段
        select_fields = """
            s.id, s.nickname, s.site, s.base_url, s.special_tracker_domain, s.`group`,
            CASE WHEN s.cookie IS NOT NULL AND s.cookie != '' THEN 1 ELSE 0 END as has_cookie,
            CASE WHEN s.passkey IS NOT NULL AND s.passkey != '' THEN 1 ELSE 0 END as has_passkey,
            s.cookie, s.passkey
        """

        if filter_by_torrents == "active":
            # [修正] 使用 LOWER() 函数进行大小写不敏感的 JOIN
            sql = f"""
                SELECT DISTINCT {select_fields}
                FROM sites s
                JOIN torrents t ON LOWER(s.nickname) = LOWER(t.sites)
                ORDER BY s.nickname
            """
        else:
            # 默认情况，获取所有站点
            sql = f"""
                SELECT {select_fields}
                FROM sites s
                ORDER BY s.nickname
            """

        cursor.execute(sql)
        sites = [dict(row) for row in cursor.fetchall()]
        return jsonify(sites)
    except Exception as e:
        logging.error(f"get_sites 出错: {e}", exc_info=True)
        return jsonify({"error": "获取站点列表失败"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# --- [新增] 添加新站点的 API ---
@api_bp.route("/sites/add", methods=["POST"])
def add_site():
    """添加一个新站点。"""
    site_data = request.json
    if not site_data.get("nickname") or not site_data.get("site"):
        return jsonify({"success": False, "message": "站点昵称和站点域名不能为空。"}), 400
    if db_manager.add_site(site_data):
        return jsonify({"success": True, "message": "站点已成功添加。"})
    else:
        return jsonify({"success": False, "message": "添加站点失败，可能是站点域名已存在。"}), 500


# --- [修改] 更新站点详情的 API ---
@api_bp.route("/sites/update", methods=["POST"])
def update_site_details():
    """更新一个已有站点的所有信息。"""
    site_data = request.json
    if not site_data.get("id"):
        return jsonify({"success": False, "message": "必须提供站点ID。"}), 400
    if db_manager.update_site_details(site_data):
        return jsonify(
            {"success": True, "message": f"站点 '{site_data.get('nickname')}' 的信息已成功更新。"}
        )
    else:
        return (
            jsonify(
                {"success": False, "message": f"未找到站点ID '{site_data.get('id')}' 或更新失败。"}
            ),
            404,
        )


# --- [新增] 删除站点的 API ---
@api_bp.route("/sites/delete", methods=["POST"])
def delete_site():
    """根据 ID 删除一个站点。"""
    data = request.json
    site_id = data.get("id")
    if not site_id:
        return jsonify({"success": False, "message": "必须提供站点ID。"}), 400
    if db_manager.delete_site(site_id):
        return jsonify({"success": True, "message": "站点已成功删除。"})
    else:
        return jsonify({"success": False, "message": f"删除站点ID '{site_id}' 失败。"}), 404


# --- 更新站点 Cookie 的 API (由CookieCloud专用) ---
@api_bp.route("/sites/update_cookie", methods=["POST"])
def update_site_cookie():
    """根据站点昵称更新其 Cookie。"""
    data = request.json
    nickname = data.get("nickname")
    cookie = data.get("cookie")

    if not nickname or cookie is None:
        return jsonify({"success": False, "message": "必须提供站点昵称和 Cookie。"}), 400

    try:
        if db_manager.update_site_cookie(nickname, cookie):
            return jsonify(
                {"success": True, "message": f"站点 '{nickname}' 的 Cookie 已成功更新。"}
            )
        else:
            return (
                jsonify({"success": False, "message": f"未找到站点 '{nickname}' 或更新失败。"}),
                404,
            )
    except Exception as e:
        logging.error(f"update_site_cookie 发生意外错误: {e}", exc_info=True)
        return jsonify({"success": False, "message": "服务器内部错误。"}), 500


# --- 从 CookieCloud 同步的 API ---
@api_bp.route("/cookiecloud/sync", methods=["POST"])
def cookiecloud_sync():
    """
    连接到 CookieCloud，获取所有 Cookies，并更新匹配站点的 Cookie。
    """
    data = request.json
    cc_url = data.get("url")
    cc_key = data.get("key")
    e2e_password = data.get("e2e_password")

    if not cc_url or not cc_key:
        return jsonify({"success": False, "message": "CookieCloud URL 和 KEY 不能为空。"}), 400

    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        cursor.execute("SELECT nickname, site, base_url FROM sites")
        app_sites = [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logging.error(f"cookiecloud_sync: 获取本地站点列表失败: {e}", exc_info=True)
        return jsonify({"success": False, "message": "从数据库获取站点列表失败。"}), 500
    finally:
        if "conn" in locals() and conn:
            if "cursor" in locals() and cursor:
                cursor.close()
            conn.close()

    try:
        target_url = f"{cc_url.rstrip('/')}/get/{cc_key}"
        payload = {}
        if e2e_password:
            payload["password"] = e2e_password

        scraper = cloudscraper.create_scraper()
        response = scraper.post(target_url, json=payload, timeout=20)
        response.raise_for_status()
        response_data = response.json()

        cookie_data_dict = response_data.get("cookie_data")
        if not isinstance(cookie_data_dict, dict):
            if "encrypted" in response_data:
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": "获取到加密数据。请确保端对端加密密码已填写并正确。",
                        }
                    ),
                    400,
                )
            raise ValueError("从 CookieCloud 返回的数据格式不正确或为空。")

    except Exception as e:
        error_message = str(e)
        if "404" in error_message:
            error_message = f"连接成功，但未找到资源 (404 Not Found)。请检查 KEY (UUID) 是否正确，以及 URL 是否为 CookieCloud 根地址。"
        logging.error(f"CookieCloud 同步失败: {e}", exc_info=True)
        return (
            jsonify({"success": False, "message": f"请求 CookieCloud 时出错: {error_message}"}),
            500,
        )

    updated_count = 0
    matched_cc_domains = set()

    for site_in_app in app_sites:
        nickname = site_in_app.get("nickname")
        if not nickname:
            continue

        identifiers = {site_in_app["nickname"].lower(), site_in_app["site"].lower()}
        if site_in_app.get("base_url"):
            try:
                hostname = urlparse(f'http://{site_in_app["base_url"]}').hostname
                if hostname:
                    identifiers.add(hostname.lower())
            except Exception:
                pass

        for cc_domain, cookie_value in cookie_data_dict.items():
            cleaned_cc_domain = cc_domain.lstrip(".").lower()
            if cleaned_cc_domain in identifiers:
                cookie_to_save = (
                    "; ".join([f"{c.get('name')}={c.get('value')}" for c in cookie_value])
                    if isinstance(cookie_value, list)
                    else cookie_value
                )
                if db_manager.update_site_cookie(nickname, cookie_to_save):
                    updated_count += 1
                    matched_cc_domains.add(cc_domain)
                break

    unmatched_count = len(cookie_data_dict) - len(matched_cc_domains)
    message = f"同步完成！成功更新 {updated_count} 个站点的 Cookie。在 CookieCloud 中另有 {unmatched_count} 个未匹配的 Cookie。"

    return jsonify(
        {
            "success": True,
            "message": message,
            "updated_count": updated_count,
            "unmatched_count": unmatched_count,
        }
    )


# --- 执行种子迁移的 API ---
@api_bp.route("/migrate_torrent", methods=["POST"])
def migrate_torrent():
    """执行种子迁移任务。"""
    data = request.json
    source_site_name = data.get("sourceSite")
    target_site_name = data.get("targetSite")
    search_term = data.get("searchTerm")

    if not all([source_site_name, target_site_name, search_term]):
        return jsonify({"success": False, "logs": "错误：源站点、目标站点和搜索词不能为空。"}), 400

    if source_site_name == target_site_name:
        return jsonify({"success": False, "logs": "错误：源站点和目标站点不能相同。"}), 400

    try:
        source_info = db_manager.get_site_by_nickname(source_site_name)
        target_info = db_manager.get_site_by_nickname(target_site_name)

        if not source_info or not source_info.get("cookie"):
            return (
                jsonify(
                    {
                        "success": False,
                        "logs": f"错误：未找到源站点 '{source_site_name}' 或其缺少 Cookie 配置。",
                    }
                ),
                404,
            )
        if not target_info or not target_info.get("cookie") or not target_info.get("passkey"):
            return (
                jsonify(
                    {
                        "success": False,
                        "logs": f"错误：未找到目标站点 '{target_site_name}' 或其缺少 Cookie/Passkey 配置。",
                    }
                ),
                404,
            )

        migrator = TorrentMigrator(source_info, target_info, search_term)
        result = migrator.run()

        return jsonify(result)

    except Exception as e:
        logging.error(f"migrate_torrent 发生意外错误: {e}", exc_info=True)
        return jsonify({"success": False, "logs": f"服务器内部错误: {e}"}), 500


@api_bp.route("/settings", methods=["GET"])
def get_settings():
    """获取当前配置，包括所有下载器（不含密码）和 CookieCloud 设置。"""
    config = copy.deepcopy(config_manager.get())
    if "downloaders" in config:
        for downloader in config["downloaders"]:
            if "password" in downloader:
                downloader["password"] = ""
    if "cookiecloud" in config and "e2e_password" in config["cookiecloud"]:
        config["cookiecloud"]["e2e_password"] = ""
    return jsonify(config)


@api_bp.route("/settings", methods=["POST"])
def update_settings():
    """
    更新并保存配置。
    """
    new_config_data = request.json
    current_config = config_manager.get().copy()

    restart_needed = False

    if "downloaders" in new_config_data:
        restart_needed = True
        current_downloaders = {d["id"]: d for d in current_config.get("downloaders", [])}
        final_downloaders = []
        for new_downloader in new_config_data["downloaders"]:
            downloader_id = new_downloader.get("id")
            if downloader_id and not new_downloader.get("password"):
                if downloader_id in current_downloaders:
                    new_downloader["password"] = current_downloaders[downloader_id].get(
                        "password", ""
                    )
            if not downloader_id:
                new_downloader["id"] = str(uuid.uuid4())
            final_downloaders.append(new_downloader)
        current_config["downloaders"] = final_downloaders

    if "realtime_speed_enabled" in new_config_data:
        if current_config.get("realtime_speed_enabled") != bool(
            new_config_data["realtime_speed_enabled"]
        ):
            restart_needed = True
        current_config["realtime_speed_enabled"] = bool(new_config_data["realtime_speed_enabled"])

    if "cookiecloud" in new_config_data:
        current_config["cookiecloud"] = new_config_data["cookiecloud"]

    if config_manager.save(current_config):
        if restart_needed:
            logging.info("配置已更新，将重启数据追踪服务以应用更改...")
            stop_data_tracker()
            db_manager.init_db()
            reconcile_and_start_tracker()
            return jsonify({"message": "配置已成功保存和应用。"}), 200
        else:
            logging.info("配置已更新，无需重启服务。")
            return jsonify({"message": "配置已成功保存。"}), 200
    else:
        return jsonify({"error": "无法保存配置到文件。"}), 500


def reconcile_and_start_tracker():
    """一个辅助函数，用于协调数据并启动追踪器，通常在配置更改后调用。"""
    from database import reconcile_historical_data

    reconcile_historical_data(db_manager, config_manager.get())
    start_data_tracker(db_manager, config_manager)


@api_bp.route("/test_connection", methods=["POST"])
def test_connection():
    """
    测试与单个下载器的连接。
    """
    client_config = request.json
    downloader_id = client_config.get("id")
    downloader_name = client_config.get("name", "下载器")

    if downloader_id and not client_config.get("password"):
        current_config = config_manager.get()
        current_downloaders = {d["id"]: d for d in current_config.get("downloaders", [])}
        if downloader_id in current_downloaders:
            client_config["password"] = current_downloaders[downloader_id].get("password", "")

    client_type = client_config.get("type")
    api_config = {
        k: v for k, v in client_config.items() if k not in ["id", "name", "type", "enabled"]
    }

    try:
        if client_type == "qbittorrent":
            client = Client(**api_config)
            client.auth_log_in()
            return jsonify(
                {"success": True, "message": f"下载器 '{downloader_name}' 连接测试成功"}
            )
        elif client_type == "transmission":
            from services import _prepare_api_config

            tr_api_config = _prepare_api_config(client_config)
            client = TrClient(**tr_api_config)
            client.get_session()
            return jsonify(
                {"success": True, "message": f"下载器 '{downloader_name}' 连接测试成功"}
            )
        else:
            return jsonify({"success": False, "message": "无效的客户端类型。"}), 400
    except Exception as e:
        error_message = str(e)
        if "401" in error_message or "Unauthorized" in error_message:
            error_message = "认证失败，请检查用户名和密码。"
        elif "403" in error_message:
            error_message = "禁止访问，请检查权限设置。"
        return (
            jsonify(
                {"success": False, "message": f"'{downloader_name}' 连接失败: {error_message}"}
            ),
            200,
        )


def get_date_range_and_grouping(time_range_str, for_speed=False):
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_dt, end_dt = None, now
    group_by_format = "%Y-%m-%d"
    ranges = {
        "today": (today_start, "%Y-%m-%d %H:00"),
        "yesterday": (today_start - timedelta(days=1), "%Y-%m-%d %H:00"),
        "this_week": (today_start - timedelta(days=now.weekday()), "%Y-%m-%d"),
        "last_week": (today_start - timedelta(days=now.weekday() + 7), "%Y-%m-%d"),
        "this_month": (today_start.replace(day=1), "%Y-%m-%d"),
        "last_month": (
            (today_start.replace(day=1) - timedelta(days=1)).replace(day=1),
            "%Y-%m-%d",
        ),
        "last_6_months": (now - timedelta(days=180), "%Y-%m"),
        "this_year": (today_start.replace(month=1, day=1), "%Y-%m"),
        "all": (datetime(1970, 1, 1), "%Y-%m"),
        "last_12_hours": (now - timedelta(hours=12), None),
        "last_24_hours": (now - timedelta(hours=24), None),
    }
    if time_range_str in ranges:
        start_dt, group_by_format_override = ranges[time_range_str]
        if group_by_format_override:
            group_by_format = group_by_format_override

    if time_range_str == "yesterday":
        end_dt = today_start
    if time_range_str == "last_week":
        end_dt = today_start - timedelta(days=now.weekday())
    if time_range_str == "last_month":
        end_dt = today_start.replace(day=1)

    if for_speed:
        if time_range_str in ["last_12_hours", "last_24_hours", "today", "yesterday"]:
            group_by_format = "%Y-%m-%d %H:%M"
        elif start_dt and (end_dt - start_dt).total_seconds() > 0:
            if group_by_format not in ["%Y-%m", "CUSTOM_5_SEC_INTERVAL"]:
                interval_seconds = (end_dt - start_dt).total_seconds() / 600
                if interval_seconds <= 5400:
                    group_by_format = "%Y-%m-%d %H:00"
    return start_dt, end_dt, group_by_format


def get_time_group_fn(db_type, format_str):
    if format_str == "CUSTOM_5_SEC_INTERVAL":
        if db_type == "mysql":
            return (
                "FROM_UNIXTIME(FLOOR(UNIX_TIMESTAMP(stat_datetime) / 5) * 5, '%Y-%m-%d %H:%i:%s')"
            )
        else:
            return "STRFTIME('%Y-%m-%d %H:%M:%S', CAST(strftime('%s', stat_datetime) / 5 AS INTEGER) * 5, 'unixepoch')"
    return (
        f"DATE_FORMAT(stat_datetime, '{format_str.replace('%M', '%i')}')"
        if db_type == "mysql"
        else f"STRFTIME('{format_str}', stat_datetime)"
    )


@api_bp.route("/chart_data")
def get_chart_data_api():
    time_range = request.args.get("range", "this_week")
    start_dt, end_dt, group_by_format = get_date_range_and_grouping(time_range)
    time_group_fn = get_time_group_fn(db_manager.db_type, group_by_format)
    ph = db_manager.get_placeholder()

    query = f"SELECT {time_group_fn} AS time_group, SUM(uploaded) AS total_ul, SUM(downloaded) AS total_dl FROM traffic_stats WHERE stat_datetime >= {ph}"
    params = [start_dt.strftime("%Y-%m-%d %H:%M:%S")]
    if end_dt:
        query += f" AND stat_datetime < {ph}"
        params.append(end_dt.strftime("%Y-%m-%d %H:%M:%S"))
    query += " GROUP BY time_group ORDER BY time_group"

    conn = None
    cursor = None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()

        labels = [r["time_group"] for r in rows]
        datasets = [
            {
                "time": r["time_group"],
                "uploaded": int(r["total_ul"] or 0),
                "downloaded": int(r["total_dl"] or 0),
            }
            for r in rows
        ]
        return jsonify({"labels": labels, "datasets": datasets})
    except Exception as e:
        logging.error(f"get_chart_data_api 出错: {e}", exc_info=True)
        return jsonify({"error": "获取图表数据失败"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@api_bp.route("/speed_data")
def get_speed_data_api():
    speeds_by_client = {}
    if services.data_tracker_thread:
        with CACHE_LOCK:
            speeds_by_client = copy.deepcopy(services.data_tracker_thread.latest_speeds)

    return jsonify(speeds_by_client)


@api_bp.route("/recent_speed_data")
def get_recent_speed_data_api():
    try:
        seconds_to_fetch = int(request.args.get("seconds", "60"))
    except ValueError:
        return jsonify({"error": "无效的秒数参数"}), 400

    cfg_downloaders = config_manager.get().get("downloaders", [])
    enabled_downloaders = [
        {"id": d["id"], "name": d["name"]} for d in cfg_downloaders if d.get("enabled")
    ]

    buffer_data = []
    if services.data_tracker_thread:
        with CACHE_LOCK:
            buffer_data = list(services.data_tracker_thread.recent_speeds_buffer)

    results_from_buffer = []
    for r in sorted(buffer_data, key=lambda x: x["timestamp"]):
        renamed_speeds = {}
        for d in enabled_downloaders:
            original_speed_data = r["speeds"].get(d["id"], {})
            renamed_speeds[d["id"]] = {
                "ul_speed": original_speed_data.get("upload_speed", 0),
                "dl_speed": original_speed_data.get("download_speed", 0),
            }

        results_from_buffer.append(
            {"time": r["timestamp"].strftime("%H:%M:%S"), "speeds": renamed_speeds}
        )

    seconds_missing = seconds_to_fetch - len(results_from_buffer)
    results_from_db = []
    if seconds_missing > 0:
        conn = None
        cursor = None
        try:
            end_dt = buffer_data[0]["timestamp"] if buffer_data else datetime.now()
            ph = db_manager.get_placeholder()
            conn = db_manager._get_connection()
            cursor = db_manager._get_cursor(conn)

            query = f"SELECT stat_datetime, downloader_id, upload_speed, download_speed FROM traffic_stats WHERE stat_datetime < {ph} ORDER BY stat_datetime DESC LIMIT {ph}"
            limit = (
                seconds_missing * len(enabled_downloaders)
                if enabled_downloaders
                else seconds_missing
            )
            params = [end_dt.strftime("%Y-%m-%d %H:%M:%S"), limit]
            cursor.execute(query, tuple(params))

            db_rows_by_time = defaultdict(dict)
            for row in reversed(cursor.fetchall()):
                dt_obj = row["stat_datetime"]
                if isinstance(dt_obj, str):
                    try:
                        dt_obj = datetime.strptime(dt_obj, "%Y-%m-%d %H:%M:%S.%f")
                    except ValueError:
                        dt_obj = datetime.strptime(dt_obj, "%Y-%m-%d %H:%M:%S")

                time_str = dt_obj.strftime("%H:%M:%S")
                db_rows_by_time[time_str][row["downloader_id"]] = {
                    "ul_speed": row["upload_speed"] or 0,
                    "dl_speed": row["download_speed"] or 0,
                }

            for time_str, speeds_dict in sorted(db_rows_by_time.items()):
                results_from_db.append({"time": time_str, "speeds": speeds_dict})

        except Exception as e:
            logging.error(f"获取历史速度数据失败: {e}", exc_info=True)
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    final_results = (results_from_db + results_from_buffer)[-seconds_to_fetch:]
    labels = [r["time"] for r in final_results]

    return jsonify(
        {"labels": labels, "datasets": final_results, "downloaders": enabled_downloaders}
    )


@api_bp.route("/speed_chart_data")
def get_speed_chart_data_api():
    time_range = request.args.get("range", "last_12_hours")
    conn = None
    cursor = None

    cfg_downloaders = config_manager.get().get("downloaders", [])
    enabled_downloaders = [
        {"id": d["id"], "name": d["name"]} for d in cfg_downloaders if d.get("enabled")
    ]

    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        start_dt, end_dt, group_by_format = get_date_range_and_grouping(time_range, for_speed=True)
        time_group_fn = get_time_group_fn(db_manager.db_type, group_by_format)

        query = f"SELECT {time_group_fn} AS time_group, downloader_id, AVG(upload_speed) AS ul_speed, AVG(download_speed) AS dl_speed FROM traffic_stats WHERE stat_datetime >= {db_manager.get_placeholder()}"
        params = [start_dt.strftime("%Y-%m-%d %H:%M:%S")]
        if end_dt:
            query += f" AND stat_datetime < {db_manager.get_placeholder()}"
            params.append(end_dt.strftime("%Y-%m-%d %H:%M:%S"))
        query += " GROUP BY time_group, downloader_id ORDER BY time_group"

        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()

        results_by_time = defaultdict(lambda: {"time": "", "speeds": {}})
        for r in rows:
            time_group = r["time_group"]
            entry = results_by_time[time_group]
            entry["time"] = time_group
            entry["speeds"][r["downloader_id"]] = {
                "ul_speed": float(r["ul_speed"] or 0),
                "dl_speed": float(r["dl_speed"] or 0),
            }

        sorted_datasets = sorted(results_by_time.values(), key=lambda x: x["time"])
        labels = [d["time"] for d in sorted_datasets]

        return jsonify(
            {"labels": labels, "datasets": sorted_datasets, "downloaders": enabled_downloaders}
        )
    except Exception as e:
        logging.error(f"get_speed_chart_data_api 出错: {e}", exc_info=True)
        return jsonify({"error": "获取速度图表数据失败"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@api_bp.route("/downloader_info")
def get_downloader_info_api():
    cfg_downloaders = config_manager.get().get("downloaders", [])
    info = {
        d["id"]: {
            "name": d["name"],
            "type": d["type"],
            "enabled": d.get("enabled", False),
            "status": "未配置",
            "details": {},
        }
        for d in cfg_downloaders
    }

    conn = None
    cursor = None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        cursor.execute(
            "SELECT downloader_id, SUM(downloaded) as total_dl, SUM(uploaded) as total_ul FROM traffic_stats GROUP BY downloader_id"
        )
        totals = {r["downloader_id"]: r for r in cursor.fetchall()}

        today_query = f"SELECT downloader_id, SUM(downloaded) as today_dl, SUM(uploaded) as today_ul FROM traffic_stats WHERE stat_datetime >= {db_manager.get_placeholder()} GROUP BY downloader_id"
        cursor.execute(today_query, (datetime.now().strftime("%Y-%m-%d 00:00:00"),))
        today_stats = {r["downloader_id"]: r for r in cursor.fetchall()}

    except Exception as e:
        logging.error(f"获取下载器统计信息时数据库出错: {e}", exc_info=True)
        totals, today_stats = {}, {}
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    for d_id, d_info in info.items():
        if not d_info["enabled"]:
            continue

        total_dl = totals.get(d_id, {}).get("total_dl", 0)
        total_ul = totals.get(d_id, {}).get("total_ul", 0)
        today_dl = today_stats.get(d_id, {}).get("today_dl", 0)
        today_ul = today_stats.get(d_id, {}).get("today_ul", 0)

        details = {
            "今日下载量": format_bytes(today_dl),
            "今日上传量": format_bytes(today_ul),
            "累计下载量": format_bytes(total_dl),
            "累计上传量": format_bytes(total_ul),
        }

        client_config = next((item for item in cfg_downloaders if item["id"] == d_id), None)
        api_config = {
            k: v for k, v in client_config.items() if k not in ["id", "name", "type", "enabled"]
        }

        try:
            if d_info["type"] == "qbittorrent":
                client = Client(**api_config)
                client.auth_log_in()
                details["版本"] = client.app.version
            elif d_info["type"] == "transmission":
                from services import _prepare_api_config

                tr_api_config = _prepare_api_config(client_config)
                client = TrClient(**tr_api_config)
                details["版本"] = client.get_session().version
            d_info["status"] = "已连接"
        except Exception as e:
            d_info["status"] = "连接失败"
            details["错误信息"] = str(e)
        d_info["details"] = details

    return jsonify(list(info.values()))


@api_bp.route("/data")
def get_data_api():
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("pageSize", 50))

    try:
        path_filters_str = request.args.get("path_filters", "[]")
        path_filters = json.loads(path_filters_str) if path_filters_str else []
    except json.JSONDecodeError:
        path_filters = []

    try:
        state_filters_str = request.args.get("state_filters", "[]")
        state_filters = json.loads(state_filters_str) if state_filters_str else []
    except json.JSONDecodeError:
        state_filters = []

    site_filter_existence = request.args.get("siteFilterExistence", "all")
    try:
        site_filters_str = request.args.get("siteFilterNames", "[]")
        site_filter_names = json.loads(site_filters_str) if site_filters_str else []
    except json.JSONDecodeError:
        site_filter_names = []

    name_search = request.args.get("nameSearch", "").lower()
    sort_prop = request.args.get("sortProp")
    sort_order = request.args.get("sortOrder")

    conn = None
    cursor = None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        cursor.execute(
            "SELECT DISTINCT sites FROM torrents WHERE sites IS NOT NULL AND sites != ''"
        )
        all_discovered_sites = sorted([row["sites"] for row in cursor.fetchall()])

        cursor.execute("SELECT * FROM torrents")
        torrents_raw = [dict(row) for row in cursor.fetchall()]

        cursor.execute(
            "SELECT hash, SUM(uploaded) as total_uploaded FROM torrent_upload_stats GROUP BY hash"
        )
        uploads_by_hash = {
            row["hash"]: int(row["total_uploaded"] or 0) for row in cursor.fetchall()
        }

        agg_torrents = defaultdict(
            lambda: {
                "name": "",
                "save_path": "",
                "size": 0,
                "progress": 0,
                "state": set(),
                "sites": defaultdict(lambda: {"comment": "", "uploaded": 0}),
                "total_uploaded": 0,
            }
        )

        for t in torrents_raw:
            name = t["name"]
            agg = agg_torrents[name]

            if not agg["name"]:
                agg["name"] = name
                agg["save_path"] = t.get("save_path", "")
                agg["size"] = t.get("size", 0)

            agg["progress"] = max(agg.get("progress", 0), t.get("progress", 0))
            agg["state"].add(t.get("state", "N/A"))

            upload_for_this_hash = uploads_by_hash.get(t["hash"], 0)
            agg["total_uploaded"] += upload_for_this_hash

            site_name = t.get("sites")
            if site_name:
                agg["sites"][site_name]["uploaded"] += upload_for_this_hash
                agg["sites"][site_name]["comment"] = t.get("details")

        final_torrent_list = []
        for name, data in agg_torrents.items():
            data["state"] = ", ".join(sorted(list(data["state"])))
            data["size_formatted"] = format_bytes(data["size"])
            data["total_uploaded_formatted"] = format_bytes(data["total_uploaded"])
            data["site_count"] = len(data.get("sites", {}))
            data["total_site_count"] = len(all_discovered_sites)
            final_torrent_list.append(data)

        filtered_list = final_torrent_list
        if name_search:
            filtered_list = [t for t in filtered_list if name_search in t["name"].lower()]
        if path_filters:
            filtered_list = [t for t in filtered_list if t.get("save_path") in path_filters]
        if state_filters:
            filtered_list = [
                t
                for t in filtered_list
                for s in t.get("state", "").split(", ")
                if s in state_filters
            ]

        if site_filter_existence != "all" and site_filter_names:
            site_filter_set = set(site_filter_names)

            if site_filter_existence == "exists":
                filtered_list = [
                    t
                    for t in filtered_list
                    if site_filter_set.intersection(t.get("sites", {}).keys())
                ]
            elif site_filter_existence == "not-exists":
                filtered_list = [
                    t
                    for t in filtered_list
                    if not site_filter_set.intersection(t.get("sites", {}).keys())
                ]

        if sort_prop and sort_order:
            reverse = sort_order == "descending"
            sort_key_map = {
                "size_formatted": "size",
                "progress": "progress",
                "total_uploaded_formatted": "total_uploaded",
                "site_count": "site_count",
            }
            sort_key = sort_key_map.get(sort_prop)
            if sort_key:
                filtered_list.sort(key=lambda x: x.get(sort_key, 0), reverse=reverse)
            else:
                filtered_list.sort(
                    key=cmp_to_key(lambda a, b: custom_sort_compare(a, b)), reverse=reverse
                )
        else:
            filtered_list.sort(key=cmp_to_key(custom_sort_compare))

        total_items = len(filtered_list)
        paginated_data = filtered_list[(page - 1) * page_size : page * page_size]

        unique_paths = sorted(
            list(set(row.get("save_path") for row in torrents_raw if row.get("save_path")))
        )
        unique_states = sorted(
            list(set(row.get("state") for row in torrents_raw if row.get("state")))
        )
        _, site_link_rules_from_db, _ = load_site_maps_from_db(db_manager)

        return jsonify(
            {
                "data": paginated_data,
                "total": total_items,
                "page": page,
                "pageSize": page_size,
                "unique_paths": unique_paths,
                "unique_states": unique_states,
                "all_discovered_sites": all_discovered_sites,
                "site_link_rules": site_link_rules_from_db,
                "active_path_filters": path_filters,
                "error": None,
            }
        )

    except Exception as e:
        logging.error(f"get_data_api 出错: {e}", exc_info=True)
        return jsonify({"error": "从数据库检索种子数据失败"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@api_bp.route("/refresh_data", methods=["POST"])
def refresh_data_api():
    try:
        if services.data_tracker_thread:
            Thread(target=services.data_tracker_thread._update_torrents_in_db).start()
            return jsonify({"message": "后台刷新已触发"}), 202
        else:
            return jsonify({"message": "数据追踪服务未运行，无法刷新。"}), 400
    except Exception as e:
        logging.error(f"触发刷新失败: {e}")
        return jsonify({"error": "触发刷新失败"}), 500


@api_bp.route("/site_stats")
def get_site_stats_api():
    conn = None
    cursor = None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        query = "SELECT sites, SUM(size) as total_size, COUNT(name) as torrent_count FROM (SELECT DISTINCT name, size, sites FROM torrents WHERE sites IS NOT NULL AND sites != '') AS unique_torrents GROUP BY sites;"
        cursor.execute(query)
        rows = cursor.fetchall()
        results = sorted(
            [
                {
                    "site_name": row["sites"],
                    "total_size": int(row["total_size"] or 0),
                    "torrent_count": int(row["torrent_count"] or 0),
                }
                for row in rows
            ],
            key=lambda x: x["site_name"],
        )
        return jsonify(results)
    except Exception as e:
        logging.error(f"get_site_stats_api 出错: {e}", exc_info=True)
        return jsonify({"error": "从数据库获取站点统计信息失败"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@api_bp.route("/group_stats")
def get_group_stats_api():
    conn = None
    cursor = None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        is_mysql = db_manager.db_type == "mysql"
        if is_mysql:
            group_col_quoted, group_concat_expr, join_condition = (
                "`group`",
                "GROUP_CONCAT(DISTINCT ut.`group` ORDER BY ut.`group` SEPARATOR ', ')",
                "FIND_IN_SET(ut.`group`, s.`group`) > 0",
            )
        else:
            group_col_quoted, group_concat_expr, join_condition = (
                '"group"',
                'GROUP_CONCAT(DISTINCT ut."group")',
                "',' || s.\"group\" || ',' LIKE '%,' || ut.\"group\" || ',%'",
            )
        query = f"""SELECT s.nickname AS site_name, {group_concat_expr} AS group_suffix, COUNT(ut.name) AS torrent_count, SUM(ut.size) AS total_size FROM (SELECT name, {group_col_quoted} AS "group", MAX(size) AS size FROM torrents WHERE {group_col_quoted} IS NOT NULL AND {group_col_quoted} != '' GROUP BY name, {group_col_quoted}) AS ut JOIN sites AS s ON {join_condition} GROUP BY s.nickname ORDER BY s.nickname;"""
        cursor.execute(query)
        rows = cursor.fetchall()

        results = [
            {
                "site_name": row["site_name"],
                "group_suffix": (
                    row["group_suffix"].replace("-", "")
                    if row["group_suffix"]
                    else row["group_suffix"]
                ),
                "torrent_count": int(row["torrent_count"] or 0),
                "total_size": int(row["total_size"] or 0),
            }
            for row in rows
        ]

        return jsonify(results)
    except Exception as e:
        logging.error(f"get_group_stats_api 出错: {e}", exc_info=True)
        return jsonify({"error": "从数据库获取发布组统计信息失败"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
