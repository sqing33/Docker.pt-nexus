# api/routes_management.py

import logging
import copy
import uuid
import cloudscraper
import requests
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


def _get_proxy_downloader_info(client_config, config_manager):
    """通过代理获取下载器信息。"""
    try:
        # 从下载器配置的host中提取IP地址作为代理服务器地址
        host_value = client_config['host']

        # 如果host已经包含协议，直接解析；否则添加http://前缀
        if host_value.startswith(('http://', 'https://')):
            parsed_url = urlparse(host_value)
        else:
            parsed_url = urlparse(f"http://{host_value}")

        proxy_ip = parsed_url.hostname
        if not proxy_ip:
            # 如果无法解析，使用备用方法
            if '://' in host_value:
                proxy_ip = host_value.split('://')[1].split(':')[0].split('/')[0]
            else:
                proxy_ip = host_value.split(':')[0]

        proxy_port = client_config.get('proxy_port', 9090)  # 默认9090
        proxy_base_url = f"http://{proxy_ip}:{proxy_port}"
        logging.info(f"使用代理服务器: {proxy_base_url}")

        # 构造代理请求数据
        proxy_downloader_config = {
            "id": client_config['id'],
            "type": client_config['type'],
            "host": "http://127.0.0.1:" + str(parsed_url.port or 8080),
            "username": client_config.get('username', ''),
            "password": client_config.get('password', '')
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
            logging.warning(f"代理返回空的统计信息 for '{client_config['name']}'")
            return None

    except Exception as e:
        logging.error(f"通过代理获取 '{client_config['name']}' 统计信息失败: {e}")
        return None


# --- 依赖注入占位符 ---
# 在 run.py 中，management_bp.db_manager 和 management_bp.config_manager 将被赋值
# db_manager = None
# config_manager = None


def reconcile_and_start_tracker():
    """一个辅助函数，用于协调数据并启动追踪器，通常在配置更改后调用。"""
    # 检查是否在调试模式下运行
    import os
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        logging.info("检测到调试监控进程，跳过reconcile_and_start_tracker。")
        return

    db_manager = management_bp.db_manager
    config_manager = management_bp.config_manager
    reconcile_historical_data(db_manager, config_manager.get())
    services.start_data_tracker(db_manager, config_manager)
    # 启动IYUU线程
    try:
        from core.iyuu import start_iyuu_thread
        start_iyuu_thread(db_manager, config_manager)
    except Exception as e:
        logging.error(f"启动IYUU线程失败: {e}", exc_info=True)


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
        # 根据数据库类型使用正确的引号
        if db_manager.db_type == "postgresql":
            select_fields = """
                s.id, s.nickname, s.site, s.base_url, s.special_tracker_domain, s."group", s.proxy, s.speed_limit,
                CASE WHEN s.cookie IS NOT NULL AND s.cookie != '' THEN 1 ELSE 0 END as has_cookie,
                CASE WHEN s.passkey IS NOT NULL AND s.passkey != '' THEN 1 ELSE 0 END as has_passkey,
                s.cookie, s.passkey
            """
        else:
            select_fields = """
                s.id, s.nickname, s.site, s.base_url, s.special_tracker_domain, s.`group`, s.proxy, s.speed_limit,
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

    # 去除cookie字符串首尾的换行符和多余空白字符
    if cookie:
        cookie = cookie.strip()

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


@management_bp.route("/sites/fetch_all_passkeys", methods=["POST"])
def fetch_all_passkeys():
    """获取所有有Cookie且可发布站点的Passkey并保存到数据库。"""
    db_manager = management_bp.db_manager
    # 获取请求参数，判断是否使用代理
    use_proxy = request.json.get("use_proxy", False) if request.json else False

    try:
        # 获取所有有Cookie且为可发布站点的信息
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        cursor.execute(
            "SELECT * FROM sites WHERE cookie IS NOT NULL AND cookie != '' AND (migration = 2 OR migration = 3)"
        )
        sites_info = cursor.fetchall()

        if not sites_info:
            return jsonify({
                "success": False,
                "message": "没有配置Cookie且为可发布站点的信息。"
            }), 400

        sites_info = [dict(site) for site in sites_info]
        successful_count = 0
        failed_sites = []

        # 为每个站点获取Passkey
        for site_info in sites_info:
            try:
                cookie = site_info.get("cookie")
                base_url = site_info.get("base_url")
                site_id = site_info.get("id")
                site_nickname = site_info.get("nickname")

                if not cookie:
                    failed_sites.append(f"{site_nickname}(Cookie未配置)")
                    continue

                if not base_url:
                    failed_sites.append(f"{site_nickname}(基础URL未配置)")
                    continue

                # 确保URL有协议前缀
                if not base_url.startswith(("http://", "https://")):
                    base_url = "https://" + base_url

                # 构造请求头
                headers = {
                    "User-Agent":
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                    "Cookie": cookie,
                    "Referer": f"{base_url}/",
                }

                # 发送请求获取用户控制面板页面
                import cloudscraper
                scraper = cloudscraper.create_scraper()

                # 添加重试机制，类似uploaders/base.py中的实现
                max_retries = 3
                last_exception = None
                proxies = None

                # 如果明确要求使用代理，则获取代理配置
                if use_proxy:
                    try:
                        config_manager = management_bp.config_manager
                        conf = (config_manager.get() or {})
                        # 优先使用转种设置中的代理地址，其次兼容旧的 network.proxy_url
                        proxy_url = (conf.get("cross_seed", {})
                                     or {}).get("proxy_url") or (conf.get(
                                         "network", {}) or {}).get("proxy_url")
                        if proxy_url:
                            proxies = {"http": proxy_url, "https": proxy_url}
                            logging.info(f"Using proxy: {proxy_url}")
                    except Exception as e:
                        logging.warning(f"代理设置失败: {e}")

                for attempt in range(max_retries):
                    try:
                        # 检查是否是重试并且 Connection reset by peer 错误，强制使用代理
                        if attempt > 0 and last_exception and "Connection reset by peer" in str(
                                last_exception):
                            logging.info(
                                "检测到 Connection reset by peer 错误，强制使用代理重试...")
                            try:
                                config_manager = management_bp.config_manager
                                conf = (config_manager.get() or {})
                                # 优先使用转种设置中的代理地址，其次兼容旧的 network.proxy_url
                                proxy_url = (conf.get("cross_seed", {})
                                             or {}).get("proxy_url") or (
                                                 conf.get("network", {})
                                                 or {}).get("proxy_url")
                                if proxy_url:
                                    proxies = {
                                        "http": proxy_url,
                                        "https": proxy_url
                                    }
                                    logging.info(f"使用代理重试: {proxy_url}")
                            except Exception as proxy_error:
                                logging.warning(f"代理设置失败: {proxy_error}")

                        logging.info(
                            f"正在获取 {site_nickname} 的Passkey... (尝试 {attempt + 1}/{max_retries})"
                        )
                        response = scraper.get(f"{base_url}/usercp.php",
                                               headers=headers,
                                               timeout=30,
                                               proxies=proxies)
                        response.raise_for_status()

                        # 成功则跳出循环
                        last_exception = None
                        break

                    except Exception as e:
                        last_exception = e
                        logging.warning(
                            f"第 {attempt + 1} 次尝试获取 {site_nickname} 的Passkey失败: {e}"
                        )

                        # 如果不是最后一次尝试，等待一段时间后重试
                        if attempt < max_retries - 1:
                            import time
                            wait_time = 2**attempt  # 指数退避
                            logging.info(
                                f"等待 {wait_time} 秒后进行第 {attempt + 2} 次尝试...")
                            time.sleep(wait_time)
                        else:
                            logging.error(
                                f"获取 {site_nickname} 的Passkey所有重试均已失败")

                # 如果所有重试都失败了，处理错误
                if last_exception:
                    error_msg = str(last_exception)
                    if "403" in error_msg or "401" in error_msg:
                        failed_sites.append(f"{site_nickname}(Cookie已过期或无效)")
                    elif "timeout" in error_msg.lower(
                    ) or "timed out" in error_msg.lower():
                        failed_sites.append(f"{site_nickname}(请求超时)")
                    elif "dns" in error_msg.lower():
                        failed_sites.append(f"{site_nickname}(域名解析失败)")
                    elif "104" in error_msg and "Connection reset by peer" in error_msg:
                        failed_sites.append(
                            f"{site_nickname}(连接被重置: {error_msg})")
                    else:
                        failed_sites.append(
                            f"{site_nickname}(网络连接错误: {error_msg})")
                    continue

                # 从页面中提取Passkey
                import re
                passkey_pattern = r'<td[^>]*class="rowhead nowrap"[^>]*>\s*密钥\s*</td>\s*<td[^>]*class="rowfollow"[^>]*>\s*([a-f0-9]{32})\s*</td>'
                match = re.search(passkey_pattern, response.text)

                if not match:
                    # 检查是否是因为重定向到登录页面
                    if "login" in response.url or "login" in response.text.lower(
                    ):
                        failed_sites.append(
                            f"{site_nickname}(Cookie已过期，被重定向到登录页)")
                    else:
                        failed_sites.append(f"{site_nickname}(页面中未找到Passkey)")
                    continue

                passkey = match.group(1)

                # 更新数据库中的Passkey
                cursor.execute("UPDATE sites SET passkey = %s WHERE id = %s",
                               (passkey, site_id))
                successful_count += 1

            except Exception as e:
                failed_sites.append(
                    f"{site_info.get('nickname')}(处理异常: {str(e)})")
                continue

        conn.commit()

        # 构造返回消息
        message = f"成功获取 {successful_count} 个站点的 Passkey。"
        if failed_sites:
            message += f" 失败站点: {', '.join(failed_sites)}。"

        return jsonify({
            "success": True,
            "message": message,
            "successful_count": successful_count,
            "failed_count": len(failed_sites),
            "failed_sites": failed_sites
        })

    except Exception as e:
        logging.error(f"fetch_all_passkeys 发生意外错误: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "message": f"获取Passkey失败: {str(e)}"
        }), 500
    finally:
        if "conn" in locals() and conn:
            if "cursor" in locals() and cursor:
                cursor.close()
            conn.close()


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
                # 去除cookie字符串首尾的换行符和多余空白字符
                if cookie_str:
                    cookie_str = cookie_str.strip()
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

    if "network" in new_config:
        # 仅更新网络代理配置
        current_config.setdefault("network", {})
        current_config["network"]["proxy_url"] = new_config["network"].get(
            "proxy_url", "")

    # 处理 iyuu_token 配置
    if "iyuu_token" in new_config:
        current_config["iyuu_token"] = new_config["iyuu_token"]

    if config_manager.save(current_config):
        if restart_needed:
            logging.info("配置已更新，将重启数据追踪服务...")
            services.stop_data_tracker()
            # 停止IYUU线程
            try:
                from core.iyuu import stop_iyuu_thread
                stop_iyuu_thread()
            except Exception as e:
                logging.error(f"停止IYUU线程失败: {e}", exc_info=True)
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
    use_proxy = client_config.get("use_proxy", False)

    try:
        if client_config.get("type") == "qbittorrent":
            if use_proxy:
                # 使用代理测试连接
                logging.info(f"通过代理测试 '{name}' 的连接...")
                proxy_stats = _get_proxy_downloader_info(client_config, config_manager)
                if proxy_stats:
                    return jsonify({"success": True, "message": f"下载器 '{name}' 代理连接测试成功"})
                else:
                    return jsonify({"success": False, "message": f"'{name}' 代理连接测试失败，请检查代理服务器和下载器配置。"}), 200
            else:
                # 使用直连测试
                api_config = {
                    k: v
                    for k, v in client_config.items()
                    if k not in ["id", "name", "type", "enabled", "use_proxy", "proxy_port"]
                }
                client = Client(**api_config)
                client.auth_log_in()
        elif client_config.get("type") == "transmission":
            if use_proxy:
                return jsonify({"success": False, "message": "Transmission 暂不支持代理连接测试。"}), 200
            else:
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

        # 获取累计上传和下载量 - 使用最新的累计值
        cursor.execute(
            """SELECT downloader_id,
                      MAX(cumulative_downloaded) as total_dl,
                      MAX(cumulative_uploaded) as total_ul
               FROM traffic_stats
               WHERE cumulative_downloaded > 0 OR cumulative_uploaded > 0
               GROUP BY downloader_id"""
        )
        totals = {r["downloader_id"]: dict(r) for r in cursor.fetchall()}

        # 获取今日上传和下载量 - 使用和 InfoView.vue 相同的逻辑，计算今日内的总增量
        from datetime import datetime, timedelta

        # 查询今日内每个下载器的总增量，类似于 routes_stats.py 中的 chart_data 逻辑
        if db_manager.db_type == "postgresql":
            today_query = """SELECT
                                downloader_id,
                                GREATEST(0,
                                    (MAX(cumulative_downloaded) - MIN(cumulative_downloaded))::bigint
                                ) as today_dl,
                                GREATEST(0,
                                    (MAX(cumulative_uploaded) - MIN(cumulative_uploaded))::bigint
                                ) as today_ul
                             FROM traffic_stats
                             WHERE stat_datetime::date = CURRENT_DATE
                             GROUP BY downloader_id"""
            cursor.execute(today_query)
        else:
            today_query = """SELECT
                                downloader_id,
                                MAX(0,
                                    MAX(cumulative_downloaded) - MIN(cumulative_downloaded)
                                ) as today_dl,
                                MAX(0,
                                    MAX(cumulative_uploaded) - MIN(cumulative_uploaded)
                                ) as today_ul
                             FROM traffic_stats
                             WHERE """

            # 添加日期条件
            if db_manager.db_type == "mysql":
                today_query += "DATE(stat_datetime) = CURDATE()"
            else:  # SQLite
                today_query += "DATE(stat_datetime) = DATE('now', 'localtime')"

            today_query += " GROUP BY downloader_id"
            cursor.execute(today_query)

        today_stats = {r["downloader_id"]: dict(r) for r in cursor.fetchall()}
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

        # 确保从数据库获取的值是数字类型
        today_dl = today_stats.get(d_id, {}).get("today_dl", 0)
        today_ul = today_stats.get(d_id, {}).get("today_ul", 0)
        total_dl = totals.get(d_id, {}).get("total_dl", 0)
        total_ul = totals.get(d_id, {}).get("total_ul", 0)

        # 转换为整数（处理可能的字符串类型）
        try:
            today_dl = int(float(today_dl))
            today_ul = int(float(today_ul))
            total_dl = int(float(total_dl))
            total_ul = int(float(total_ul))
        except (ValueError, TypeError):
            today_dl = today_ul = total_dl = total_ul = 0

        d_info["details"] = {
            "今日下载量": format_bytes(today_dl),
            "今日上传量": format_bytes(today_ul),
            "累计下载量": format_bytes(total_dl),
            "累计上传量": format_bytes(total_ul),
        }
        try:
            # 检查是否需要使用代理
            use_proxy = client_config.get("use_proxy", False)

            if use_proxy and d_info["type"] == "qbittorrent":
                # 使用代理获取下载器信息
                proxy_stats = _get_proxy_downloader_info(
                    client_config, config_manager)
                if proxy_stats:
                    d_info["details"]["版本"] = proxy_stats.get("version", "未知")
                    d_info["status"] = "已连接"
                else:
                    d_info["status"] = "连接失败"
                    d_info["details"]["错误信息"] = "通过代理连接失败"
            elif d_info["type"] == "qbittorrent":
                api_config = {
                    k: v
                    for k, v in client_config.items()
                    if k not in ["id", "name", "type", "enabled", "use_proxy", "proxy_port"]
                }
                client = Client(**api_config)
                client.auth_log_in()
                d_info["details"]["版本"] = client.app.version
                d_info["status"] = "已连接"
            elif d_info["type"] == "transmission":
                api_config = services._prepare_api_config(client_config)
                client = TrClient(**api_config)
                d_info["details"]["版本"] = client.get_session().version
                d_info["status"] = "已连接"
        except Exception as e:
            d_info["status"] = "连接失败"
            d_info["details"]["错误信息"] = str(e)
    return jsonify(list(info.values()))


# --- [新增] UI 设置接口 ---


@management_bp.route("/ui_settings", methods=["GET"])
def get_ui_settings():
    """获取前端 UI 相关的设置。"""
    config_manager = management_bp.config_manager
    # 提供一个安全的默认值，以防配置文件损坏或字段缺失
    default_settings = {
        "page_size": 50,
        "sort_prop": "name",
        "sort_order": "ascending",
        "name_search": "",
        "active_filters": {
            "paths": [],
            "states": [],
            "siteExistence": "all",
            "siteNames": [],
            "downloaderIds": [],
        }
    }
    # 从配置中获取 torrents_view 的设置，如果不存在则使用默认值
    settings = config_manager.get().get("ui_settings",
                                        {}).get("torrents_view",
                                                default_settings)
    return jsonify(settings)


@management_bp.route("/ui_settings", methods=["POST"])
def save_ui_settings():
    """保存前端 UI 相关的设置。"""
    config_manager = management_bp.config_manager
    new_torrents_view_settings = request.json

    current_config = config_manager.get()

    # 使用 .setdefault 确保各层级都存在
    ui_settings = current_config.setdefault("ui_settings", {})
    ui_settings["torrents_view"] = new_torrents_view_settings

    if config_manager.save(current_config):
        return jsonify({"success": True, "message": "UI 设置已成功保存。"})
    else:
        return jsonify({"success": False, "message": "无法保存 UI 设置。"}), 500


@management_bp.route("/ui_settings/cross_seed", methods=["GET"])
def get_cross_seed_ui_settings():
    """获取 CrossSeedDataView 的 UI 设置。"""
    config_manager = management_bp.config_manager
    # 提供一个安全的默认值，以防配置文件损坏或字段缺失
    default_settings = {
        "page_size": 20,
        "search_query": "",
        "active_filters": {
            "savePath": "",
            "isDeleted": ""
        }
    }
    # 从配置中获取 cross_seed_view 的设置，如果不存在则使用默认值
    settings = config_manager.get().get("ui_settings",
                                        {}).get("cross_seed_view",
                                                default_settings)
    return jsonify(settings)


@management_bp.route("/ui_settings/cross_seed", methods=["POST"])
def save_cross_seed_ui_settings():
    """保存 CrossSeedDataView 的 UI 设置。"""
    config_manager = management_bp.config_manager
    new_cross_seed_view_settings = request.json

    current_config = config_manager.get()

    # 使用 .setdefault 确保各层级都存在
    ui_settings = current_config.setdefault("ui_settings", {})
    ui_settings["cross_seed_view"] = new_cross_seed_view_settings

    if config_manager.save(current_config):
        return jsonify({"success": True, "message": "Cross Seed UI 设置已成功保存。"})
    else:
        return jsonify({"success": False, "message": "无法保存 Cross Seed UI 设置。"}), 500


# --- [新增] IYUU 设置接口 ---
@management_bp.route("/iyuu/settings", methods=["GET"])
def get_iyuu_settings():
    """获取IYUU相关设置。"""
    config_manager = management_bp.config_manager
    # 提供一个安全的默认值
    default_settings = {"query_interval_hours": 72, "auto_query_enabled": True}
    # 从配置中获取IYUU设置，如果不存在则使用默认值
    settings = config_manager.get().get("iyuu_settings", default_settings)
    return jsonify(settings)


@management_bp.route("/iyuu/settings", methods=["POST"])
def save_iyuu_settings():
    """保存IYUU相关设置。"""
    config_manager = management_bp.config_manager
    new_settings = request.json

    current_config = config_manager.get()

    # 更新IYUU设置
    current_config["iyuu_settings"] = new_settings

    if config_manager.save(current_config):
        # 重启IYUU线程以应用新设置
        try:
            from core.iyuu import stop_iyuu_thread, start_iyuu_thread
            stop_iyuu_thread()
            start_iyuu_thread(management_bp.db_manager, config_manager)
        except Exception as e:
            logging.error(f"重启IYUU线程失败: {e}", exc_info=True)

        return jsonify({"success": True, "message": "IYUU 设置已成功保存。"})
    else:
        return jsonify({"success": False, "message": "无法保存 IYUU 设置。"}), 500


@management_bp.route("/iyuu/trigger_query", methods=["POST"])
def trigger_iyuu_query():
    """手动触发IYUU查询。"""
    db_manager = management_bp.db_manager
    config_manager = management_bp.config_manager

    try:
        # 导入并启动IYUU查询
        from core.iyuu import IYUUThread, log_iyuu_message
        log_iyuu_message("手动触发IYUU查询", "INFO")
        iyuu_thread = IYUUThread(db_manager, config_manager)
        # 手动触发查询，绕过自动查询检查
        iyuu_thread._process_torrents(is_manual_trigger=True)

        return jsonify({"success": True, "message": "IYUU 查询已成功触发。"})
    except Exception as e:
        logging.error(f"手动触发IYUU查询失败: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "message": f"触发IYUU查询失败: {str(e)}"
        }), 500


@management_bp.route("/iyuu/logs", methods=["GET"])
def get_iyuu_logs():
    """获取IYUU日志。"""
    try:
        from core.iyuu import iyuu_logs
        return jsonify({"success": True, "logs": iyuu_logs})
    except Exception as e:
        logging.error(f"获取IYUU日志失败: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "message": f"获取IYUU日志失败: {str(e)}"
        }), 500
