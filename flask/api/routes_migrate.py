# api/routes_migrate.py

import logging
import uuid
import re
from flask import Blueprint, jsonify, request
from bs4 import BeautifulSoup
from utils import upload_data_title, upload_data_screenshot, upload_data_poster, add_torrent_to_downloader, extract_tags_from_mediainfo, extract_origin_from_description
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
                                   save_path=save_path,
                                   config_manager=config_manager)
        # 调用只获取信息和原始种子的方法
        result = migrator.prepare_review_data()

        if "review_data" in result:
            task_id = str(uuid.uuid4())
            # 缓存必要信息，而不是整个 migrator 实例
            MIGRATION_CACHE[task_id] = {
                "source_info": source_info,
                "original_torrent_path": result["original_torrent_path"],
                "review_data": result["review_data"],
                "source_site_name": source_site_name,  # 添加源站点名称到缓存中
                "source_torrent_id": search_term,  # 添加源种子ID到缓存中
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
    task_id, upload_data, target_site_name, source_site_name = (
        data.get("task_id"), data.get("upload_data"), data.get("targetSite"),
        data.get("sourceSite"))

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

        # 从缓存中获取源站点名称（如果前端没有传递）
        if not source_site_name:
            source_site_name = context.get("source_site_name", "")

        # 特殊提取器处理已移至 migrator.py 中

        # 动态创建针对本次发布的 Migrator 实例
        migrator = TorrentMigrator(source_info,
                                   target_info,
                                   config_manager=config_manager)

        # 使用特殊提取器处理数据（如果需要）
        source_torrent_id = context.get("source_torrent_id", "unknown")
        print(f"在publish阶段处理数据，源站点: {source_site_name}, 种子ID: {source_torrent_id}")
        print(f"调用apply_special_extractor_if_needed前，upload_data中的mediainfo长度: {len(upload_data.get('mediainfo', '')) if upload_data.get('mediainfo') else 0}")
        upload_data = migrator.apply_special_extractor_if_needed(upload_data, source_torrent_id)
        print(f"publish阶段数据处理完成")
        print(f"调用apply_special_extractor_if_needed后，upload_data中的mediainfo长度: {len(upload_data.get('mediainfo', '')) if upload_data.get('mediainfo') else 0}")

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

        migrator = TorrentMigrator(source_info,
                                   target_info,
                                   search_term,
                                   config_manager=config_manager)
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
    torrent_name = data.get("torrentName")
    imdb_link = source_info.get("imdb_link", '')
    douban_link = source_info.get("douban_link", '')

    logging.warning(
        f"收到失效图片报告 - 类型: {image_type}, "
        f"来源信息: {source_info}，视频路径: {save_path}，种子名称: {torrent_name}")
    if image_type == "screenshot":
        screenshots = upload_data_screenshot(source_info, save_path,
                                             torrent_name)
        return jsonify({"success": True, "screenshots": screenshots}), 200
    else:
        status, posters, extracted_imdb_link = upload_data_poster(
            douban_link, imdb_link)
        if status:
            return jsonify({
                "success": True,
                "posters": posters,
                "extracted_imdb_link": extracted_imdb_link
            }), 200
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
        default_downloader_id = config.get("cross_seed",
                                           {}).get("default_downloader")
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


@migrate_bp.route("/migrate/search_torrent_id", methods=["POST"])
def search_torrent_id():
    """通过种子名称搜索获取种子ID"""
    db_manager = migrate_bp.db_manager
    data = request.json
    source_site_name = data.get("sourceSite")
    torrent_name = data.get("torrentName")

    if not source_site_name or not torrent_name:
        return jsonify({"success": False, "message": "源站点和种子名称不能为空"}), 400

    try:
        # 获取源站点信息
        source_info = db_manager.get_site_by_nickname(source_site_name)
        if not source_info or not source_info.get("cookie"):
            return jsonify({
                "success": False,
                "message": f"源站点 '{source_site_name}' 配置不完整"
            }), 404

        # 使用TorrentMigrator的搜索功能
        migrator = TorrentMigrator(source_site_info=source_info,
                                   target_site_info=None,
                                   search_term=torrent_name,
                                   config_manager=config_manager)

        # 调用搜索方法获取种子ID
        torrent_id = migrator.search_and_get_torrent_id(torrent_name)

        if torrent_id:
            return jsonify({
                "success": True,
                "torrent_id": torrent_id,
                "message": "搜索成功"
            })
        else:
            return jsonify({"success": False, "message": "未找到匹配的种子"}), 404

    except Exception as e:
        logging.error(f"search_torrent_id 发生意外错误: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"服务器内部错误: {e}"}), 500


@migrate_bp.route("/migrate/update_preview_data", methods=["POST"])
def update_preview_data():
    """更新预览数据"""
    data = request.json
    task_id = data.get("task_id")
    updated_data = data.get("updated_data")

    if not task_id or task_id not in MIGRATION_CACHE:
        return jsonify({"success": False, "message": "错误：无效或已过期的任务ID。"}), 400

    if not updated_data:
        return jsonify({"success": False, "message": "错误：缺少更新数据。"}), 400

    try:
        # 获取缓存中的上下文
        context = MIGRATION_CACHE[task_id]
        source_info = context["source_info"]
        original_torrent_path = context["original_torrent_path"]

        # 更新 review_data 中的相关字段
        review_data = context["review_data"].copy()
        review_data["original_main_title"] = updated_data.get(
            "original_main_title", review_data.get("original_main_title", ""))
        review_data["title_components"] = updated_data.get(
            "title_components", review_data.get("title_components", []))
        review_data["subtitle"] = updated_data.get(
            "subtitle", review_data.get("subtitle", ""))
        review_data["imdb_link"] = updated_data.get(
            "imdb_link", review_data.get("imdb_link", ""))
        review_data["intro"] = updated_data.get("intro",
                                                review_data.get("intro", {}))
        review_data["mediainfo"] = updated_data.get(
            "mediainfo", review_data.get("mediainfo", ""))
        review_data["source_params"] = updated_data.get(
            "source_params", review_data.get("source_params", {}))

        # 重新提取产地信息
        full_description_text = f"{review_data['intro'].get('statement', '')}\n{review_data['intro'].get('body', '')}"
        origin_info = extract_origin_from_description(full_description_text)
        if origin_info and "source_params" in review_data:
            review_data["source_params"]["产地"] = origin_info

        # 重新生成预览参数
        # 这里我们需要重新构建完整的发布参数预览
        try:
            # 1. 重新解析标题组件
            title_components = review_data.get("title_components", [])
            if not title_components:
                title_components = upload_data_title(
                    review_data["original_main_title"])

            # 2. 重新构建标题参数字典
            title_params = {
                item["key"]: item["value"]
                for item in title_components if item.get("value")
            }

            # 3. 重新拼接主标题
            order = [
                "主标题",
                "年份",
                "季集",
                "剧集状态",
                "发布版本",
                "分辨率",
                "片源平台",
                "媒介",
                "视频编码",
                "视频格式",
                "HDR格式",
                "色深",
                "帧率",
                "音频编码",
            ]
            title_parts = []
            for key in order:
                value = title_params.get(key)
                if value:
                    title_parts.append(" ".join(map(str, value)) if isinstance(
                        value, list) else str(value))

            raw_main_part = " ".join(filter(None, title_parts))
            main_part = re.sub(r'(?<!\d)\.(?!\d)', ' ', raw_main_part)
            main_part = re.sub(r'\s+', ' ', main_part).strip()
            release_group = title_params.get("制作组", "NOGROUP")
            if "N/A" in release_group:
                release_group = "NOGROUP"

            # 对特殊制作组进行处理，不需要添加前缀连字符
            special_groups = ["MNHD-FRDS", "mUHD-FRDS"]
            if release_group in special_groups:
                preview_title = f"{main_part} {release_group}"
            else:
                preview_title = f"{main_part}-{release_group}"

            # 4. 重新组合简介
            full_description = (
                f"{review_data['intro'].get('statement', '')}\n"
                f"{review_data['intro'].get('poster', '')}\n"
                f"{review_data['intro'].get('body', '')}\n"
                f"{review_data['intro'].get('screenshots', '')}")

            # 5. 重新收集标签
            source_tags = set(review_data["source_params"].get("标签") or [])
            mediainfo_tags = set(
                extract_tags_from_mediainfo(review_data["mediainfo"]))
            all_tags = sorted(list(source_tags.union(mediainfo_tags)))

            # 6. 重新组装预览字典
            final_publish_parameters = {
                "主标题 (预览)": preview_title,
                "副标题": review_data["subtitle"],
                "IMDb链接": review_data["imdb_link"],
                "类型": review_data["source_params"].get("类型", "N/A"),
                "媒介": title_params.get("媒介", "N/A"),
                "视频编码": title_params.get("视频编码", "N/A"),
                "音频编码": title_params.get("音频编码", "N/A"),
                "分辨率": title_params.get("分辨率", "N/A"),
                "制作组": title_params.get("制作组", "N/A"),
                "产地": review_data["source_params"].get("产地", "N/A"),
                "标签 (综合)": all_tags,
            }

            # 7. 提取映射前的原始参数用于前端展示
            raw_params_for_preview = {
                "final_main_title":
                preview_title,
                "subtitle":
                review_data["subtitle"],
                "imdb_link":
                review_data["imdb_link"],
                "type":
                review_data["source_params"].get("类型", ""),
                "medium":
                title_params.get("媒介", ""),
                "video_codec":
                title_params.get("视频编码", ""),
                "audio_codec":
                title_params.get("音频编码", ""),
                "resolution":
                title_params.get("分辨率", ""),
                "release_group":
                title_params.get("制作组", ""),
                "source":
                review_data["source_params"].get("产地", "")
                or title_params.get("片源平台", ""),
                "tags":
                list(all_tags)
            }

            # 更新 review_data 中的预览参数
            review_data["final_publish_parameters"] = final_publish_parameters
            review_data["raw_params_for_preview"] = raw_params_for_preview

            # 更新缓存中的 review_data
            MIGRATION_CACHE[task_id]["review_data"] = review_data

            return jsonify({
                "success": True,
                "data": review_data,
                "message": "预览数据更新成功"
            })
        except Exception as e:
            logging.error(f"重新生成预览数据时发生错误: {e}", exc_info=True)
            return jsonify({
                "success": False,
                "message": f"重新生成预览数据时发生错误: {e}"
            }), 500

    except Exception as e:
        logging.error(f"update_preview_data 发生意外错误: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"服务器内部错误: {e}"}), 500
