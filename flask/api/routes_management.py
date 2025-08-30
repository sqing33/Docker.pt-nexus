# api/routes_management.py

import logging
import copy
import uuid
import cloudscraper
from flask import Blueprint, jsonify, request
from urllib.parse import urlparse

# 从项目根目录导入核心模块
from core import services
from database import reconcile_historical_data

# 导入下载器客户端 API
from qbittorrentapi import Client, APIConnectionError
from transmission_rpc import Client as TrClient, TransmissionError

# --- Blueprint Setup ---
management_bp = Blueprint("management_api", __name__, url_prefix="/api")

# --- 依赖注入占位符 ---
# 在 run.py 中，management_bp.db_manager 和 management_bp.config_manager 将被赋值
# db_manager = None
# config_manager = None


def reconcile_and_start_tracker():
    """一个辅助函数，用于协调数据并启动追踪器，通常在配置更改后调用。"""
    db_manager = management_bp.db_manager
    config_manager = management_bp.config_manager
    reconcile_historical_data(db_manager, config_manager.get())
    services.start_data_tracker(db_manager, config_manager)


# --- 站点管理 ---


@management_bp.route("/sites_list", methods=["GET"])
def get_sites_list():
    """获取可用于迁移的源站点和目标站点列表。"""
    db_manager = management_bp.db_manager
    conn = None
    cursor = None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        # --- 修改后的逻辑 ---
        # 获取源站点 (migration 为 1 或 3，且必须有 cookie)
        cursor.execute("""
            SELECT nickname FROM sites 
            WHERE (migration = 1 OR migration = 3) 
            AND cookie IS NOT NULL AND cookie != '' 
            ORDER BY nickname
            """)
        source_sites = [row["nickname"] for row in cursor.fetchall()]

        # 获取目标站点 (migration 为 2 或 3，且必须有 passkey)
        cursor.execute("""
            SELECT nickname FROM sites 
            WHERE (migration = 2 OR migration = 3) 
            AND passkey IS NOT NULL AND passkey != '' 
            ORDER BY nickname
            """)
        target_sites = [row["nickname"] for row in cursor.fetchall()]

        return jsonify({
            "source_sites": source_sites,
            "target_sites": target_sites
        })
    except Exception as e:
        logging.error(f"get_sites_list 出错: {e}", exc_info=True)
        return jsonify({"error": "获取站点列表失败"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@management_bp.route("/sites", methods=["GET"])
def get_sites():
    """获取所有站点的完整详细列表，可根据种子存在情况进行筛选。"""
    db_manager = management_bp.db_manager
    filter_by_torrents = request.args.get("filter_by_torrents", "all")
    conn, cursor = None, None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        select_fields = """
            s.id, s.nickname, s.site, s.base_url, s.special_tracker_domain, s.`group`,
            CASE WHEN s.cookie IS NOT NULL AND s.cookie != '' THEN 1 ELSE 0 END as has_cookie,
            CASE WHEN s.passkey IS NOT NULL AND s.passkey != '' THEN 1 ELSE 0 END as has_passkey,
            s.cookie, s.passkey
        """
        if filter_by_torrents == "active":
            sql = f"""
                SELECT DISTINCT {select_fields}
                FROM sites s
                JOIN torrents t ON LOWER(s.nickname) = LOWER(t.sites)
                ORDER BY s.nickname
            """
        else:
            sql = f"SELECT {select_fields} FROM sites s ORDER BY s.nickname"
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


@management_bp.route("/sites/add", methods=["POST"])
def add_site():
    """添加一个新站点。"""
    db_manager = management_bp.db_manager
    site_data = request.json
    if not site_data.get("nickname") or not site_data.get("site"):
        return jsonify({"success": False, "message": "站点昵称和站点域名不能为空。"}), 400
    if db_manager.add_site(site_data):
        return jsonify({"success": True, "message": "站点已成功添加。"})
    else:
        return jsonify({
            "success": False,
            "message": "添加站点失败，可能是站点域名已存在。"
        }), 500


@management_bp.route("/sites/update", methods=["POST"])
def update_site_details():
    """更新一个已有站点的所有信息。"""
    db_manager = management_bp.db_manager
    site_data = request.json
    if not site_data.get("id"):
        return jsonify({"success": False, "message": "必须提供站点ID。"}), 400
    if db_manager.update_site_details(site_data):
        return jsonify({
            "success": True,
            "message": f"站点 '{site_data.get('nickname')}' 的信息已成功更新。"
        })
    else:
        return (
            jsonify({
                "success": False,
                "message": f"未找到站点ID '{site_data.get('id')}' 或更新失败。"
            }),
            404,
        )


@management_bp.route("/sites/delete", methods=["POST"])
def delete_site():
    """根据 ID 删除一个站点。"""
    db_manager = management_bp.db_manager
    site_id = request.json.get("id")
    if not site_id:
        return jsonify({"success": False, "message": "必须提供站点ID。"}), 400
    if db_manager.delete_site(site_id):
        return jsonify({"success": True, "message": "站点已成功删除。"})
    else:
        return jsonify({
            "success": False,
            "message": f"删除站点ID '{site_id}' 失败。"
        }), 404


@management_bp.route("/sites/update_cookie", methods=["POST"])
def update_site_cookie():
    """根据站点昵称更新其 Cookie。"""
    db_manager = management_bp.db_manager
    data = request.json
    nickname, cookie = data.get("nickname"), data.get("cookie")
    if not nickname or cookie is None:
        return jsonify({"success": False, "message": "必须提供站点昵称和 Cookie。"}), 400
    try:
        if db_manager.update_site_cookie(nickname, cookie):
            return jsonify({
                "success": True,
                "message": f"站点 '{nickname}' 的 Cookie 已成功更新。"
            })
        else:
            return (
                jsonify({
                    "success": False,
                    "message": f"未找到站点 '{nickname}' 或更新失败。"
                }),
                404,
            )
    except Exception as e:
        logging.error(f"update_site_cookie 发生意外错误: {e}", exc_info=True)
        return jsonify({"success": False, "message": "服务器内部错误。"}), 500


# --- CookieCloud ---


@management_bp.route("/cookiecloud/sync", methods=["POST"])
def cookiecloud_sync():
    """连接到 CookieCloud，获取所有 Cookies，并更新匹配站点的 Cookie。"""
    db_manager = management_bp.db_manager
    data = request.json
    cc_url, cc_key, e2e_password = data.get("url"), data.get("key"), data.get(
        "e2e_password")
    if not cc_url or not cc_key:
        return jsonify({
            "success": False,
            "message": "CookieCloud URL 和 KEY 不能为空。"
        }), 400

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
        payload = {"password": e2e_password} if e2e_password else {}
        response = cloudscraper.create_scraper().post(target_url,
                                                      json=payload,
                                                      timeout=20)
        response.raise_for_status()
        response_data = response.json()
        cookie_data_dict = response_data.get("cookie_data")
        if not isinstance(cookie_data_dict, dict):
            if "encrypted" in response_data:
                return (
                    jsonify({
                        "success": False,
                        "message": "获取到加密数据。请确保端对端加密密码已填写并正确。",
                    }),
                    400,
                )
            raise ValueError("从 CookieCloud 返回的数据格式不正确或为空。")
    except Exception as e:
        error_message = str(e)
        if "404" in error_message:
            error_message = "连接成功，但未找到资源 (404)。请检查 KEY (UUID) 是否正确。"
        logging.error(f"CookieCloud 同步失败: {e}", exc_info=True)
        return (
            jsonify({
                "success": False,
                "message": f"请求 CookieCloud 时出错: {error_message}"
            }),
            500,
        )

    updated_count, matched_cc_domains = 0, set()
    for site_in_app in app_sites:
        if not site_in_app.get("nickname"):
            continue
        identifiers = {
            site_in_app["nickname"].lower(), site_in_app["site"].lower()
        }
        if site_in_app.get("base_url"):
            try:
                identifiers.add(
                    urlparse(
                        f'http://{site_in_app["base_url"]}').hostname.lower())
            except Exception:
                pass
        for cc_domain, cookie_value in cookie_data_dict.items():
            if cc_domain.lstrip(".").lower() in identifiers:
                cookie_str = ("; ".join([
                    f"{c['name']}={c['value']}" for c in cookie_value
                ]) if isinstance(cookie_value, list) else cookie_value)
                if db_manager.update_site_cookie(site_in_app["nickname"],
                                                 cookie_str):
                    updated_count += 1
                    matched_cc_domains.add(cc_domain)
                break

    unmatched_count = len(cookie_data_dict) - len(matched_cc_domains)
    message = f"同步完成！成功更新 {updated_count} 个站点的 Cookie。在 CookieCloud 中另有 {unmatched_count} 个未匹配的 Cookie。"
    return jsonify({
        "success": True,
        "message": message,
        "updated_count": updated_count,
        "unmatched_count": unmatched_count,
    })


# --- 应用与下载器设置 ---


@management_bp.route("/settings", methods=["GET"])
def get_settings():
    """获取当前配置（密码字段已置空）。"""
    config_manager = management_bp.config_manager
    config = copy.deepcopy(config_manager.get())
    for downloader in config.get("downloaders", []):
        downloader["password"] = ""
    if "cookiecloud" in config:
        config["cookiecloud"]["e2e_password"] = ""
    return jsonify(config)


@management_bp.route("/settings", methods=["POST"])
def update_settings():
    """更新并保存配置。如果需要，会自动重启后台服务。"""
    config_manager = management_bp.config_manager
    new_config = request.json
    current_config = config_manager.get().copy()
    restart_needed = False

    if "downloaders" in new_config:
        restart_needed = True
        current_passwords = {
            d["id"]: d.get("password", "")
            for d in current_config.get("downloaders", [])
        }
        for d in new_config["downloaders"]:
            if not d.get("id"):
                d["id"] = str(uuid.uuid4())
            if not d.get("password"):
                d["password"] = current_passwords.get(d["id"], "")
        current_config["downloaders"] = new_config["downloaders"]

    if "realtime_speed_enabled" in new_config and current_config.get(
            "realtime_speed_enabled") != bool(
                new_config["realtime_speed_enabled"]):
        restart_needed = True
        current_config["realtime_speed_enabled"] = bool(
            new_config["realtime_speed_enabled"])

    if "cookiecloud" in new_config:
        current_config["cookiecloud"] = new_config["cookiecloud"]

    if config_manager.save(current_config):
        if restart_needed:
            logging.info("配置已更新，将重启数据追踪服务...")
            services.stop_data_tracker()
            management_bp.db_manager.init_db()
            reconcile_and_start_tracker()
            return jsonify({"message": "配置已成功保存和应用。"}), 200
        else:
            return jsonify({"message": "配置已成功保存。"}), 200
    else:
        return jsonify({"error": "无法保存配置到文件。"}), 500


@management_bp.route("/test_connection", methods=["POST"])
def test_connection():
    """测试与单个下载器的连接。"""
    config_manager = management_bp.config_manager
    client_config = request.json
    if client_config.get("id") and not client_config.get("password"):
        current_dl = next(
            (d for d in config_manager.get().get("downloaders", [])
             if d["id"] == client_config["id"]),
            None,
        )
        if current_dl:
            client_config["password"] = current_dl.get("password", "")

    name = client_config.get("name", "下载器")
    try:
        if client_config.get("type") == "qbittorrent":
            api_config = {
                k: v
                for k, v in client_config.items()
                if k not in ["id", "name", "type", "enabled"]
            }
            client = Client(**api_config)
            client.auth_log_in()
        elif client_config.get("type") == "transmission":
            api_config = services._prepare_api_config(client_config)
            client = TrClient(**api_config)
            client.get_session()
        else:
            return jsonify({"success": False, "message": "无效的客户端类型。"}), 400
        return jsonify({"success": True, "message": f"下载器 '{name}' 连接测试成功"})
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "Unauthorized" in error_msg:
            error_msg = "认证失败，请检查用户名和密码。"
        elif "403" in error_msg:
            error_msg = "禁止访问，请检查权限设置。"
        return jsonify({
            "success": False,
            "message": f"'{name}' 连接失败: {error_msg}"
        }), 200


@management_bp.route("/downloader_info")
def get_downloader_info_api():
    """获取所有已配置下载器的状态和统计信息。"""
    db_manager = management_bp.db_manager
    config_manager = management_bp.config_manager
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

    conn, cursor = None, None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        cursor.execute(
            "SELECT downloader_id, SUM(downloaded) as total_dl, SUM(uploaded) as total_ul FROM traffic_stats GROUP BY downloader_id"
        )
        totals = {r["downloader_id"]: r for r in cursor.fetchall()}
        today_query = f"SELECT downloader_id, SUM(downloaded) as today_dl, SUM(uploaded) as today_ul FROM traffic_stats WHERE stat_datetime >= {db_manager.get_placeholder()} GROUP BY downloader_id"
        from datetime import datetime

        cursor.execute(today_query,
                       (datetime.now().strftime("%Y-%m-%d 00:00:00"), ))
        today_stats = {r["downloader_id"]: r for r in cursor.fetchall()}
    except Exception as e:
        logging.error(f"获取下载器统计信息时数据库出错: {e}", exc_info=True)
        totals, today_stats = {}, {}
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    from utils import format_bytes

    for d_id, d_info in info.items():
        if not d_info["enabled"]:
            continue
        client_config = next(
            (item for item in cfg_downloaders if item["id"] == d_id), None)
        d_info["details"] = {
            "今日下载量":
            format_bytes(today_stats.get(d_id, {}).get("today_dl", 0)),
            "今日上传量":
            format_bytes(today_stats.get(d_id, {}).get("today_ul", 0)),
            "累计下载量": format_bytes(totals.get(d_id, {}).get("total_dl", 0)),
            "累计上传量": format_bytes(totals.get(d_id, {}).get("total_ul", 0)),
        }
        try:
            if d_info["type"] == "qbittorrent":
                api_config = {
                    k: v
                    for k, v in client_config.items()
                    if k not in ["id", "name", "type", "enabled"]
                }
                client = Client(**api_config)
                client.auth_log_in()
                d_info["details"]["版本"] = client.app.version
            elif d_info["type"] == "transmission":
                api_config = services._prepare_api_config(client_config)
                client = TrClient(**api_config)
                d_info["details"]["版本"] = client.get_session().version
            d_info["status"] = "已连接"
        except Exception as e:
            d_info["status"] = "连接失败"
            d_info["details"]["错误信息"] = str(e)
    return jsonify(list(info.values()))
