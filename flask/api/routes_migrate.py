# api/routes_migrate.py

import logging
import uuid
from flask import Blueprint, jsonify, request
from utils import upload_data_title, upload_data_screenshot
from core.migrator import TorrentMigrator

migrate_bp = Blueprint("migrate_api", __name__, url_prefix="/api")

MIGRATION_CACHE = {}


@migrate_bp.route("/migrate/fetch_info", methods=["POST"])
def migrate_fetch_info():
    db_manager = migrate_bp.db_manager
    data = request.json
    source_site_name, target_site_name, search_term = (
        data.get("sourceSite"),
        data.get("targetSite"),
        data.get("searchTerm"),
    )

    if not all([source_site_name, target_site_name, search_term]):
        return jsonify({"success": False, "logs": "错误：源站点、目标站点和搜索词不能为空。"}), 400

    try:
        source_info = db_manager.get_site_by_nickname(source_site_name)
        target_info = db_manager.get_site_by_nickname(target_site_name)

        if not source_info or not source_info.get("cookie"):
            return (
                jsonify({
                    "success": False,
                    "logs": f"错误：源站点 '{source_site_name}' 配置不完整。"
                }),
                404,
            )
        if not target_info or not target_info.get("passkey"):
            return (
                jsonify({
                    "success": False,
                    "logs": f"错误：目标站点 '{target_site_name}' 配置不完整。"
                }),
                404,
            )

        source_role = source_info.get("migration", 0)
        target_role = target_info.get("migration", 0)

        if source_role not in [1, 3]:
            return (
                jsonify({
                    "success": False,
                    "logs": f"错误：站点 '{source_site_name}' 不允许作为源站点进行迁移。"
                }),
                403, 
            )

        if target_role not in [2, 3]:
            return (
                jsonify({
                    "success": False,
                    "logs": f"错误：站点 '{target_site_name}' 不允许作为目标站点进行迁移。"
                }),
                403, 
            )

        migrator = TorrentMigrator(source_info, target_info, search_term)
        result = migrator.prepare_for_upload()

        if "review_data" in result:
            task_id = str(uuid.uuid4())
            MIGRATION_CACHE[task_id] = {
                "migrator": migrator,
                "modified_torrent_path": result["modified_torrent_path"],
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
    data = request.json
    task_id, upload_data = data.get("task_id"), data.get("upload_data")

    if not task_id or task_id not in MIGRATION_CACHE:
        return jsonify({"success": False, "logs": "错误：无效或已过期的任务ID。"}), 400

    context = MIGRATION_CACHE[task_id]
    migrator, modified_torrent_path = context["migrator"], context[
        "modified_torrent_path"]

    try:
        result = migrator.publish_prepared_torrent(upload_data,
                                                   modified_torrent_path)
        return jsonify(result)
    except Exception as e:
        logging.error(f"migrate_publish 发生意外错误: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "logs": f"服务器内部错误: {e}",
            "url": None
        }), 500
    finally:
        migrator.cleanup()
        del MIGRATION_CACHE[task_id]


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
    if not request.is_json:
        return jsonify({"success": False, "message": "请求格式错误，需要JSON。"}), 400

    data = request.get_json()

    image_type = data.get("type")  # e.g., 'poster', 'screenshot_batch'
    source_info = data.get("source_info")

    # 记录日志，方便调试
    logging.warning(f"收到失效图片报告 - 类型: {image_type}, "
                    f"来源信息: {source_info}")
    if image_type == "screenshot":
        screenshots = upload_data_screenshot(image_type, source_info)
        return jsonify({"success": True, "screenshots": screenshots}), 200
    else:
        print("上传海报功能尚未实现。")
        return jsonify({"success": False, "message": "上传海报功能尚未实现。"}), 501
