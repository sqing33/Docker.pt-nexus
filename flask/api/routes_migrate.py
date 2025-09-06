# api/routes_migrate.py

import logging
import uuid
from flask import Blueprint, jsonify, request
from utils import upload_data_title, upload_data_screenshot, upload_data_poster, add_torrent_to_downloader
from core.migrator import TorrentMigrator

# --- [新增] 导入 config_manager ---
# 确保能够访问到全局的 config_manager 实例
from config import config_manager

migrate_bp = Blueprint("migrate_api", __name__, url_prefix="/api")

MIGRATION_CACHE = {}

# ===================================================================
#                          转种设置 API (新整合)
# ===================================================================


@migrate_bp.route("/settings/cross_seed", methods=["GET"])
def get_cross_seed_settings():
    """获取转种相关的设置。"""
    try:
        config = config_manager.get()
        # 使用 .get() 提供默认值，防止配置文件损坏时出错
        cross_seed_config = config.get("cross_seed",
                                       {"image_hoster": "pixhost"})
        return jsonify(cross_seed_config)
    except Exception as e:
        logging.error(f"获取转种设置失败: {e}", exc_info=True)
        return jsonify({"error": "服务器内部错误"}), 500


@migrate_bp.route("/settings/cross_seed", methods=["POST"])
def save_cross_seed_settings():
    """保存转种相关的设置。"""
    try:
        new_settings = request.json
        if not isinstance(new_settings,
                          dict) or "image_hoster" not in new_settings:
            return jsonify({"error": "无效的设置数据格式。"}), 400

        current_config = config_manager.get()
        # 更新配置中的 cross_seed 部分
        current_config["cross_seed"] = new_settings

        if config_manager.save(current_config):
            return jsonify({"message": "转种设置已成功保存！"})
        else:
            return jsonify({"error": "无法将设置写入配置文件。"}), 500

    except Exception as e:
        logging.error(f"保存转种设置失败: {e}", exc_info=True)
        return jsonify({"error": "服务器内部错误"}), 500


# ===================================================================
#                          原有迁移 API
# ===================================================================


@migrate_bp.route("/migrate/fetch_info", methods=["POST"])
def migrate_fetch_info():
    db_manager = migrate_bp.db_manager
    data = request.json
    source_site_name, search_term, save_path = (data.get("sourceSite"),
                                                data.get("searchTerm"),
                                                data.get("savePath", ""))

    if not all([source_site_name, search_term]):
        return jsonify({"success": False, "logs": "错误：源站点和搜索词不能为空。"}), 400

    try:
        source_info = db_manager.get_site_by_nickname(source_site_name)

        if not source_info or not source_info.get("cookie"):
            return (
                jsonify({
                    "success": False,
                    "logs": f"错误：源站点 '{source_site_name}' 配置不完整。"
                }),
                404,
            )

        source_role = source_info.get("migration", 0)

        if source_role not in [1, 3]:
            return (
                jsonify({
                    "success": False,
                    "logs": f"错误：站点 '{source_site_name}' 不允许作为源站点进行迁移。"
                }),
                403,
            )

        # 初始化 Migrator 时不传入目标站点信息
        migrator = TorrentMigrator(source_site_info=source_info,
                                   target_site_info=None,
                                   search_term=search_term,
                                   save_path=save_path)
        # 调用只获取信息和原始种子的方法
        result = migrator.prepare_review_data()

        if "review_data" in result:
            task_id = str(uuid.uuid4())
            # 缓存必要信息，而不是整个 migrator 实例
            MIGRATION_CACHE[task_id] = {
                "source_info": source_info,
                "original_torrent_path": result["original_torrent_path"],
                "review_data": result["review_data"],
            }
            return jsonify({
                "success": True,
                "task_id": task_id,
                "data": result["review_data"],
                "logs": result["logs"],
            })
        else:
            return jsonify({
                "success": False,
                "logs": result.get("logs", "未知错误")
            })
    except Exception as e:
        logging.error(f"migrate_fetch_info 发生意外错误: {e}", exc_info=True)
        return jsonify({"success": False, "logs": f"服务器内部错误: {e}"}), 500


@migrate_bp.route("/migrate/publish", methods=["POST"])
def migrate_publish():
    db_manager = migrate_bp.db_manager
    data = request.json
    task_id, upload_data, target_site_name = (data.get("task_id"),
                                              data.get("upload_data"),
                                              data.get("targetSite"))

    if not task_id or task_id not in MIGRATION_CACHE:
        return jsonify({"success": False, "logs": "错误：无效或已过期的任务ID。"}), 400

    if not target_site_name:
        return jsonify({"success": False, "logs": "错误：必须提供目标站点名称。"}), 400

    context = MIGRATION_CACHE[task_id]
    migrator = None  # 确保在 finally 中可用

    try:
        target_info = db_manager.get_site_by_nickname(target_site_name)
        if not target_info or not target_info.get("passkey"):
            return jsonify({
                "success": False,
                "logs": f"错误: 目标站点 '{target_site_name}' 配置不完整。"
            }), 404

        source_info = context["source_info"]
        original_torrent_path = context["original_torrent_path"]

        # 动态创建针对本次发布的 Migrator 实例
        migrator = TorrentMigrator(source_info, target_info)

        # 1. 修改种子文件
        main_title = upload_data.get("original_main_title", "torrent")
        modified_torrent_path = migrator.modify_torrent_file(
            original_torrent_path, main_title)
        if not modified_torrent_path:
            raise Exception("修改种子文件失败。")

        # 2. 发布
        result = migrator.publish_prepared_torrent(upload_data,
                                                   modified_torrent_path)
        return jsonify(result)

    except Exception as e:
        logging.error(f"migrate_publish to {target_site_name} 发生意外错误: {e}",
                      exc_info=True)
        return jsonify({
            "success": False,
            "logs": f"服务器内部错误: {e}",
            "url": None
        }), 500
    finally:
        if migrator:
            migrator.cleanup()
        # 注意：此处不删除 MIGRATION_CACHE[task_id]，因为它可能被用于发布到其他站点。
        # 建议设置一个独立的定时任务来清理过期的缓存。


@migrate_bp.route("/migrate_torrent", methods=["POST"])
def migrate_torrent():
    """执行一步式种子迁移任务 (不推荐使用)。"""
    db_manager = migrate_bp.db_manager
    data = request.json
    source_site_name, target_site_name, search_term = (
        data.get("sourceSite"),
        data.get("targetSite"),
        data.get("searchTerm"),
    )

    if not all([source_site_name, target_site_name, search_term]):
        return jsonify({"success": False, "logs": "错误：源站点、目标站点和搜索词不能为空。"}), 400
    if source_site_name == target_site_name:
        return jsonify({"success": False, "logs": "错误：源站点和目标站点不能相同。"}), 400

    try:
        source_info = db_manager.get_site_by_nickname(source_site_name)
        target_info = db_manager.get_site_by_nickname(target_site_name)

        if not source_info or not source_info.get("cookie"):
            return (
                jsonify({
                    "success":
                    False,
                    "logs":
                    f"错误：未找到源站点 '{source_site_name}' 或其缺少 Cookie 配置。",
                }),
                404,
            )
        if not target_info or not target_info.get(
                "cookie") or not target_info.get("passkey"):
            return (
                jsonify({
                    "success":
                    False,
                    "logs":
                    f"错误：未找到目标站点 '{target_site_name}' 或其缺少 Cookie/Passkey 配置。",
                }),
                404,
            )

        migrator = TorrentMigrator(source_info, target_info, search_term)
        if hasattr(migrator, "run"):
            result = migrator.run()
            return jsonify(result)
        else:
            return (
                jsonify({
                    "success": False,
                    "logs": "错误：此服务器不支持一步式迁移，请使用新版迁移工具。",
                }),
                501,
            )

    except Exception as e:
        logging.error(f"migrate_torrent 发生意外错误: {e}", exc_info=True)
        return jsonify({"success": False, "logs": f"服务器内部错误: {e}"}), 500


@migrate_bp.route("/utils/parse_title", methods=["POST"])
def parse_title_utility():
    """接收一个标题字符串，返回解析后的参数字典。"""
    data = request.json
    title_to_parse = data.get("title")

    if not title_to_parse:
        return jsonify({"success": False, "error": "标题不能为空。"}), 400

    try:
        parsed_components = upload_data_title(title_to_parse)

        if not parsed_components:
            return jsonify({
                "success": False,
                "message": "未能从此标题中解析出有效参数。",
                "components": {
                    "主标题": title_to_parse,
                    "无法识别": "解析失败",
                },
            })

        return jsonify({"success": True, "components": parsed_components})

    except Exception as e:
        logging.error(f"parse_title_utility 发生意外错误: {e}", exc_info=True)
        return jsonify({"success": False, "error": f"服务器内部错误: {e}"}), 500


@migrate_bp.route("/media/validate", methods=["POST"])
def validate_media():
    """接收前端发送的失效图片信息。"""
    data = request.json

    image_type = data.get("type")
    source_info = data.get("source_info")
    save_path = data.get("savePath")
    imdb_link = source_info.get("imdb_link", '')
    douban_link = source_info.get("douban_link", '')

    logging.warning(f"收到失效图片报告 - 类型: {image_type}, "
                    f"来源信息: {source_info}，视频路径: {save_path}")
    if image_type == "screenshot":
        screenshots = upload_data_screenshot(source_info, save_path)
        return jsonify({"success": True, "screenshots": screenshots}), 200
    else:
        status, posters, extracted_imdb_link = upload_data_poster(douban_link, imdb_link)
        if status:
            return jsonify({"success": True, "posters": posters, "extracted_imdb_link": extracted_imdb_link}), 200
        else:
            return jsonify({"success": False, "error": posters}), 400


@migrate_bp.route("/migrate/add_to_downloader", methods=["POST"])
def migrate_add_to_downloader():
    """接收发布成功的种子信息，并将其添加到指定的下载器。"""
    db_manager = migrate_bp.db_manager
    # config_manager 在文件顶部已导入，可以直接使用
    data = request.json

    detail_page_url = data.get("url")
    save_path = data.get("savePath")
    downloader_path = data.get("downloaderPath")
    downloader_id = data.get("downloaderId")

    # 检查是否使用默认下载器
    use_default_downloader = data.get("useDefaultDownloader", False)
    
    # 如果需要使用默认下载器，从配置中获取
    if use_default_downloader:
        config = config_manager.get()
        default_downloader_id = config.get("cross_seed", {}).get("default_downloader")
        # 只有当默认下载器ID不为空时才使用默认下载器
        if default_downloader_id:
            downloader_id = default_downloader_id
            logging.info(f"使用默认下载器: {default_downloader_id}")
        # 如果 default_downloader_id 为空，则使用源种子所在的下载器（保持 downloader_id 不变）

    if not all([detail_page_url, save_path, downloader_id]):
        return jsonify({
            "success": False,
            "message": "错误：缺少必要参数 (url, savePath, downloaderId)。"
        }), 400

    try:
        success, message = add_torrent_to_downloader(detail_page_url,
                                                     downloader_path,
                                                     downloader_id, db_manager,
                                                     config_manager)
        return jsonify({"success": success, "message": message})
    except Exception as e:
        logging.error(f"add_to_downloader 路由发生意外错误: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"服务器内部错误: {e}"}), 500


@migrate_bp.route("/sites/status", methods=["GET"])
def get_sites_status():
    """获取所有站点的详细配置状态。"""
    db_manager = migrate_bp.db_manager
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        # 从数据库查询所有站点的关键信息
        cursor.execute(
            "SELECT nickname, cookie, passkey, migration FROM sites WHERE nickname IS NOT NULL AND nickname != ''"
        )
        sites_from_db = cursor.fetchall()

        sites_status = []
        for row_obj in sites_from_db:
            # [修复] 将 sqlite3.Row 对象转换为标准的 dict，以支持 .get() 方法
            row = dict(row_obj)
            nickname = row.get("nickname")
            if not nickname:
                continue

            migration_status = row.get("migration", 0)

            site_info = {
                "name": nickname,
                "has_cookie": bool(row.get("cookie")),
                "has_passkey": bool(row.get("passkey")),
                "is_source": migration_status in [1, 3],
                "is_target": migration_status in [2, 3]
            }
            sites_status.append(site_info)

        return jsonify(sorted(sites_status, key=lambda x: x['name'].lower()))

    except Exception as e:
        logging.error(f"获取站点状态列表失败: {e}", exc_info=True)
        return jsonify({"error": "服务器内部错误"}), 500
    finally:
        if 'conn' in locals() and conn:
            if 'cursor' in locals() and cursor:
                cursor.close()
            conn.close()
