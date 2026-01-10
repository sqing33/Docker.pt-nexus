# api/routes_migrate.py

import logging
import uuid
import re
import os
import requests
import urllib.parse
import json
from datetime import datetime
from flask import Blueprint, jsonify, request, Response, stream_with_context
from bs4 import BeautifulSoup
from utils import (
    upload_data_title,
    upload_data_screenshot,
    upload_data_movie_info,
    add_torrent_to_downloader,
    extract_tags_from_mediainfo,
    extract_origin_from_description,
    extract_resolution_from_mediainfo,
)
from core.migrator import TorrentMigrator

# 导入种子参数模型
from models.seed_parameter import SeedParameter

# --- [新增] 导入 config_manager ---
# 确保能够访问到全局的 config_manager 实例
from config import config_manager, GLOBAL_MAPPINGS

# --- [新增] 导入日志流管理器 ---
from utils import log_streamer

# --- [新增] 导入SSE管理器 ---
from utils.sse_manager import sse_manager

migrate_bp = Blueprint("migrate_api", __name__, url_prefix="/api")

MIGRATION_CACHE = {}

INACTIVE_TORRENT_STATES = ("未做种", "已暂停", "已停止", "错误", "等待", "队列")


def get_seed_hash(db_manager, torrent_id, site_name):
    """根据torrent_id/site_name获取hash"""
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        ph = db_manager.get_placeholder()
        query = (
            f"SELECT hash FROM seed_parameters WHERE torrent_id = {ph} AND site_name = {ph} "
            f"ORDER BY updated_at DESC LIMIT 1"
        )
        cursor.execute(query, (torrent_id, site_name))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if not row:
            return None
        return row["hash"] if isinstance(row, dict) else row[0]
    except Exception as e:
        logging.warning(f"获取hash失败: {e}")
        return None


def get_current_torrent_info(db_manager, hash_value):
    """根据hash获取当前种子的保存路径/下载器ID（优先活跃状态，优先use_proxy=true）"""
    if not hash_value:
        return None

    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        ph = db_manager.get_placeholder()
        states_sql = "', '".join(INACTIVE_TORRENT_STATES)
        state_rank = f"CASE WHEN state NOT IN ('{states_sql}') THEN 0 ELSE 1 END"
        query = f"""
            SELECT save_path, downloader_id, name, state, last_seen
            FROM torrents
            WHERE hash = {ph}
            ORDER BY {state_rank}, last_seen DESC
        """
        cursor.execute(query, (hash_value,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if not rows:
            return None

        # 获取下载器配置
        config = config_manager.get()
        downloaders = config.get("downloaders", [])
        downloader_map = {
            downloader.get("id"): downloader.get("use_proxy", False)
            for downloader in downloaders
        }

        # 将结果转换为列表
        torrent_list = []
        for row in rows:
            if isinstance(row, dict):
                last_seen = row.get("last_seen")
                torrent_list.append({
                    "save_path": row.get("save_path"),
                    "downloader_id": row.get("downloader_id"),
                    "name": row.get("name"),
                    "state": row.get("state"),
                    "last_seen": last_seen.timestamp() if last_seen else 0,
                })
            else:
                last_seen = row[4]
                torrent_list.append({
                    "save_path": row[0],
                    "downloader_id": row[1],
                    "name": row[2],
                    "state": row[3],
                    "last_seen": last_seen.timestamp() if last_seen else 0,
                })

        # 排序：优先 use_proxy=true，然后按活跃状态，最后按 last_seen
        def sort_key(torrent):
            downloader_id = torrent.get("downloader_id")
            use_proxy = downloader_map.get(downloader_id, False)

            # 计算活跃状态排名（0=活跃，1=非活跃）
            state = torrent.get("state", "")
            state_rank = 0 if state not in INACTIVE_TORRENT_STATES else 1

            # 返回排序键：use_proxy（降序），state_rank（升序），last_seen（降序）
            return (-1 if use_proxy else 1, state_rank, -torrent.get("last_seen", 0))

        torrent_list.sort(key=sort_key)

        # 返回排序后的第一个种子
        first_torrent = torrent_list[0]
        return {
            "save_path": first_torrent.get("save_path"),
            "downloader_id": first_torrent.get("downloader_id"),
            "name": first_torrent.get("name"),
        }
    except Exception as e:
        logging.warning(f"获取当前种子信息失败: {e}")
        return None


# ===================================================================
#                          转种设置 API (新整合)
# ===================================================================


@migrate_bp.route("/settings/cross_seed", methods=["GET"])
def get_cross_seed_settings():
    """获取转种相关的设置。"""
    try:
        config = config_manager.get()
        # 使用 .get() 提供默认值，防止配置文件损坏时出错
        cross_seed_config = config.get("cross_seed", {"image_hoster": "pixhost"})
        return jsonify(cross_seed_config)
    except Exception as e:
        logging.error(f"获取转种设置失败: {e}", exc_info=True)
        return jsonify({"error": "服务器内部错误"}), 500


@migrate_bp.route("/settings/cross_seed", methods=["POST"])
def save_cross_seed_settings():
    """保存转种相关的设置。"""
    try:
        new_settings = request.json
        if not isinstance(new_settings, dict) or "image_hoster" not in new_settings:
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
#                         原有迁移 API
# ===================================================================


# 新增：从数据库读取种子信息的API接口
@migrate_bp.route("/migrate/get_db_seed_info", methods=["GET"])
def get_db_seed_info():
    """从数据库读取种子信息用于展示"""
    try:
        torrent_id = request.args.get("torrent_id")
        site_name = request.args.get("site_name")
        task_id = request.args.get("task_id")  # 接收前端传来的task_id

        if not torrent_id or not site_name:
            return (
                jsonify({"success": False, "message": "错误：torrent_id和site_name参数不能为空"}),
                400,
            )

        # 如果前端提供了task_id，使用它；否则生成新的
        if task_id:
            log_streamer.create_stream(task_id)
            log_streamer.emit_log(
                task_id, "数据库查询", "正在从数据库读取种子信息...", "processing"
            )

        db_manager = migrate_bp.db_manager

        # 从数据库读取
        try:
            # 初始化种子参数模型
            from models.seed_parameter import SeedParameter

            seed_param_model = SeedParameter(db_manager)

            parameters = seed_param_model.get_parameters(torrent_id, site_name)

            if parameters:
                logging.info(f"成功从数据库读取种子信息: {torrent_id} from {site_name}")

                # 从torrents补充当前保存路径/下载器ID
                hash_value = parameters.get("hash")
                torrent_info = get_current_torrent_info(db_manager, hash_value)
                if torrent_info:
                    parameters["save_path"] = torrent_info.get("save_path") or ""
                    parameters["downloader_id"] = torrent_info.get("downloader_id")

                # 生成反向映射表（从标准键到中文显示名称的映射）
                reverse_mappings = generate_reverse_mappings()

                # 生成task_id并存入缓存，以便发布时使用
                cache_task_id = str(uuid.uuid4())

                # 获取站点信息
                source_info = db_manager.get_site_by_nickname(site_name)
                if not source_info:
                    # 如果通过昵称找不到，尝试通过英文站点名查找
                    try:
                        conn = db_manager._get_connection()
                        cursor = db_manager._get_cursor(conn)
                        cursor.execute("SELECT * FROM sites WHERE site = ?", (site_name,))
                        source_info = cursor.fetchone()
                        if source_info:
                            source_info = dict(source_info)
                    except Exception as e:
                        logging.warning(f"获取站点信息失败: {e}")

                # 将数据存入缓存，以便发布时使用
                MIGRATION_CACHE[cache_task_id] = {
                    "source_info": source_info,
                    "original_torrent_path": None,  # 将在发布时重新获取
                    "torrent_dir": None,  # 将在发布时重新确定
                    "source_site_name": site_name,
                    "source_torrent_id": torrent_id,
                    "requires_torrent_download": True,  # 需要下载种子文件
                }

                if task_id:
                    # 标记数据库查询步骤完成
                    log_streamer.emit_log(task_id, "数据库查询", "数据库读取完成", "success")
                    # 发送完成步骤
                    log_streamer.emit_log(task_id, "完成", "数据加载完成", "success")
                    # 关闭日志流
                    log_streamer.close_stream(task_id)
                    
                print("aaaaaaaaaaaaaaaaaaaa", parameters)

                return jsonify(
                    {
                        "success": True,
                        "data": parameters,
                        "source": "database",
                        "task_id": cache_task_id,  # 返回cache_task_id给前端
                        "reverse_mappings": reverse_mappings,
                    }
                )
            else:
                logging.info(
                    f"数据库中未找到种子信息: {torrent_id} from {site_name}，将从源站点抓取"
                )

                # 标记数据库查询为失败，准备从源站点抓取
                if task_id:
                    log_streamer.emit_log(task_id, "数据库查询", "数据库中未找到缓存", "error")

                return (
                    jsonify(
                        {
                            "success": False,
                            "message": "数据库中未找到种子信息",
                            "should_fetch": True,  # 标记需要从源站点抓取
                            "task_id": task_id,  # 返回task_id以便前端继续使用同一个日志流
                        }
                    ),
                    202,
                )  # 使用202状态码表示"已接受，但需要继续处理"

        except Exception as e:
            logging.error(f"从数据库读取种子信息失败: {e}", exc_info=True)
            return jsonify({"success": False, "message": f"数据库读取失败: {str(e)}"}), 500

    except Exception as e:
        logging.error(f"get_db_seed_info发生意外错误: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"服务器内部错误: {str(e)}"}), 500


def generate_reverse_mappings():
    """生成从标准键到中文显示名称的反向映射"""
    try:
        # 读取全局映射配置
        import yaml
        import os

        # 首先尝试从global_mappings.yaml读取
        global_mappings = {}

        if os.path.exists(GLOBAL_MAPPINGS):
            try:
                with open(GLOBAL_MAPPINGS, "r", encoding="utf-8") as f:
                    config_data = yaml.safe_load(f)
                    global_mappings = config_data.get("global_standard_keys", {})
                logging.info(
                    f"成功从global_mappings.yaml读取配置，包含{len(global_mappings)}个类别"
                )
            except Exception as e:
                logging.warning(f"读取global_mappings.yaml失败: {e}，将使用配置文件中的设置")

        # 如果YAML文件读取失败，从配置管理器获取
        if not global_mappings:
            config = config_manager.get()
            global_mappings = config.get("global_standard_keys", {})

        reverse_mappings = {
            "type": {},
            "medium": {},
            "video_codec": {},
            "audio_codec": {},
            "resolution": {},
            "source": {},
            "team": {},
            "tags": {},
        }

        # 为每个类别生成反向映射
        categories_mapping = {
            "type": global_mappings.get("type", {}),
            "medium": global_mappings.get("medium", {}),
            "video_codec": global_mappings.get("video_codec", {}),
            "audio_codec": global_mappings.get("audio_codec", {}),
            "resolution": global_mappings.get("resolution", {}),
            "source": global_mappings.get("source", {}),
            "team": global_mappings.get("team", {}),
            "tags": global_mappings.get("tag", {}),  # 注意这里YAML中是'tag'而不是'tags'
        }

        # 创建反向映射：从标准值到中文名称
        for category, mappings in categories_mapping.items():
            if category == "tags":
                # 标签特殊处理，提取中文名作为键，标准值作为值
                for chinese_name, standard_value in mappings.items():
                    if standard_value:  # 过滤掉null值
                        reverse_mappings["tags"][standard_value] = chinese_name
            else:
                # 其他类别正常处理
                for chinese_name, standard_value in mappings.items():
                    if standard_value and standard_value not in reverse_mappings[category]:
                        reverse_mappings[category][standard_value] = chinese_name

        # 只在必要时添加固定映射项作为后备，避免覆盖YAML配置
        add_fallback_mappings(reverse_mappings)

        logging.info(f"成功生成反向映射表: { {k: len(v) for k, v in reverse_mappings.items()} }")
        return reverse_mappings

    except Exception as e:
        logging.error(f"生成反向映射表失败: {e}", exc_info=True)
        # 返回空的反向映射表作为后备
        return {
            "type": {},
            "medium": {},
            "video_codec": {},
            "audio_codec": {},
            "resolution": {},
            "source": {},
            "team": {},
            "tags": {},
        }


def add_fallback_mappings(reverse_mappings):
    """添加后备映射项，仅在YAML配置缺失时使用"""

    # 检查各个类别是否为空，如果为空则添加基础映射
    if not reverse_mappings["type"]:
        logging.warning("type映射为空，添加基础后备映射")
        reverse_mappings["type"].update(
            {
                "category.movie": "电影",
                "category.tv_series": "剧集",
                "category.animation": "动画",
                "category.documentaries": "纪录片",
                "category.music": "音乐",
                "category.other": "其他",
            }
        )

    if not reverse_mappings["medium"]:
        logging.warning("medium映射为空，添加基础后备映射")
        reverse_mappings["medium"].update(
            {
                "medium.bluray": "Blu-ray",
                "medium.uhd_bluray": "UHD Blu-ray",
                "medium.remux": "Remux",
                "medium.encode": "Encode",
                "medium.webdl": "WEB-DL",
                "medium.webrip": "WebRip",
                "medium.hdtv": "HDTV",
                "medium.dvd": "DVD",
                "medium.other": "其他",
            }
        )

    if not reverse_mappings["video_codec"]:
        logging.warning("video_codec映射为空，添加基础后备映射")
        reverse_mappings["video_codec"].update(
            {
                "video.h264": "H.264/AVC",
                "video.h265": "H.265/HEVC",
                "video.x265": "x265",
                "video.vc1": "VC-1",
                "video.mpeg2": "MPEG-2",
                "video.av1": "AV1",
                "video.other": "其他",
            }
        )

    if not reverse_mappings["audio_codec"]:
        logging.warning("audio_codec映射为空，添加基础后备映射")
        reverse_mappings["audio_codec"].update(
            {
                "audio.flac": "FLAC",
                "audio.dts": "DTS",
                "audio.dts_hd_ma": "DTS-HD MA",
                "audio.dtsx": "DTS:X",
                "audio.truehd": "TrueHD",
                "audio.truehd_atmos": "TrueHD Atmos",
                "audio.ac3": "AC-3",
                "audio.ddp": "E-AC-3",
                "audio.aac": "AAC",
                "audio.mp3": "MP3",
                "audio.other": "其他",
            }
        )

    if not reverse_mappings["resolution"]:
        logging.warning("resolution映射为空，添加基础后备映射")
        reverse_mappings["resolution"].update(
            {
                "resolution.r8k": "8K",
                "resolution.r4k": "4K",
                "resolution.r2160p": "2160p",
                "resolution.r1080p": "1080p",
                "resolution.r1080i": "1080i",
                "resolution.r720p": "720p",
                "resolution.r480p": "480p",
                "resolution.other": "其他",
            }
        )

    if not reverse_mappings["source"]:
        logging.warning("source映射为空，添加基础后备映射")
        reverse_mappings["source"].update(
            {
                "source.china": "中国",
                "source.hongkong": "香港",
                "source.taiwan": "台湾",
                "source.western": "美国",
                "source.uk": "英国",
                "source.japan": "日本",
                "source.korea": "韩国",
                "source.other": "其他",
            }
        )

    if not reverse_mappings["team"]:
        logging.warning("team映射为空，添加基础后备映射")
        reverse_mappings["team"].update({"team.other": "其他"})

    if not reverse_mappings["tags"]:
        logging.warning("tags映射为空，添加基础后备映射")
        reverse_mappings["tags"].update(
            {
                "tag.DIY": "DIY",
                "tag.中字": "中字",
                "tag.HDR": "HDR",
            }
        )


@migrate_bp.route("/migrate/download_torrent_only", methods=["POST"])
def download_torrent_only():
    """仅下载种子文件，不进行数据解析或存储"""
    try:
        data = request.json
        torrent_id = data.get("torrent_id")
        site_name = data.get("site_name")

        if not all([torrent_id, site_name]):
            return (
                jsonify(
                    {"success": False, "message": "错误：缺少必要参数（torrent_id、site_name）"}
                ),
                400,
            )

        db_manager = migrate_bp.db_manager

        # 获取站点信息
        source_info = db_manager.get_site_by_nickname(site_name)
        if not source_info or not source_info.get("cookie"):
            return (
                jsonify({"success": False, "message": f"错误：源站点 '{site_name}' 配置不完整。"}),
                404,
            )

        # 获取英文站点名（用于文件名前缀）
        site_code = source_info.get("site", site_name.lower())

        # 使用统一的种子目录
        from config import TEMP_DIR
        import os
        import urllib.parse
        import re

        torrent_dir = os.path.join(TEMP_DIR, "torrents")
        os.makedirs(torrent_dir, exist_ok=True)

        # 创建TorrentMigrator实例仅用于下载种子文件
        migrator = TorrentMigrator(
            source_site_info=source_info,
            target_site_info=None,
            search_term=torrent_id,
            config_manager=config_manager,
            db_manager=db_manager,
        )

        # 下载种子文件（返回的是原始文件名）
        torrent_path = migrator._download_torrent_file(torrent_id, torrent_dir)

        if torrent_path and os.path.exists(torrent_path):
            # 获取原始文件名
            original_filename = os.path.basename(torrent_path)

            # 添加站点-ID-前缀，与prepare_review_data保持一致
            prefixed_filename = f"{site_code}-{torrent_id}-{original_filename}"
            prefixed_torrent_path = os.path.join(torrent_dir, prefixed_filename)

            # 重命名文件
            try:
                os.rename(torrent_path, prefixed_torrent_path)
                logging.info(f"种子文件已重命名: {original_filename} -> {prefixed_filename}")

                return jsonify(
                    {
                        "success": True,
                        "torrent_path": prefixed_torrent_path,
                        "torrent_dir": torrent_dir,
                        "message": "种子文件下载成功",
                    }
                )
            except Exception as rename_error:
                logging.error(f"重命名种子文件失败: {rename_error}")
                # 如果重命名失败，仍然返回原始路径
                return jsonify(
                    {
                        "success": True,
                        "torrent_path": torrent_path,
                        "torrent_dir": torrent_dir,
                        "message": "种子文件下载成功（未添加前缀）",
                    }
                )
        else:
            return jsonify({"success": False, "message": "种子文件下载失败"}), 500

    except Exception as e:
        logging.error(f"download_torrent_only 发生意外错误: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"服务器内部错误: {str(e)}"}), 500


# 新增：专门负责数据抓取和存储的API接口
@migrate_bp.route("/migrate/fetch_and_store", methods=["POST"])
def migrate_fetch_and_store():
    """专门负责种子信息抓取和存储，不返回预览数据"""
    db_manager = migrate_bp.db_manager
    data = request.json
    source_site_name, search_term, save_path, torrent_name, downloader_id = (
        data.get("sourceSite"),
        data.get("searchTerm"),
        data.get("savePath", ""),
        data.get("torrentName"),
        data.get("downloaderId"),
    )

    if not all([source_site_name, search_term]):
        return jsonify({"success": False, "message": "错误：源站点和搜索词不能为空。"}), 400

    # 接收前端传来的task_id，如果没有则生成新的
    task_id = data.get("task_id")
    if not task_id:
        task_id = str(uuid.uuid4())

    # 创建或获取日志流
    log_streamer.create_stream(task_id)
    log_streamer.emit_log(task_id, "开始抓取", "正在从源站点抓取种子信息...", "processing")

    try:
        # 获取站点信息并获取英文站点名
        source_info = db_manager.get_site_by_nickname(source_site_name)

        if not source_info or not source_info.get("cookie"):
            return (
                jsonify(
                    {
                        "success": False,
                        "message": f"错误：源站点 '{source_site_name}' 配置不完整。",
                    }
                ),
                404,
            )

        source_role = source_info.get("migration", 0)

        if source_role not in [1, 3]:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": f"错误：站点 '{source_site_name}' 不允许作为源站点进行迁移。",
                    }
                ),
                403,
            )

        # 获取英文站点名作为唯一标识符
        english_site_name = source_info.get("site", source_site_name.lower())

        # 初始化 Migrator 时不传入目标站点信息
        migrator = TorrentMigrator(
            source_site_info=source_info,
            target_site_info=None,
            search_term=search_term,
            save_path=save_path,
            torrent_name=torrent_name,
            config_manager=config_manager,
            db_manager=db_manager,
            downloader_id=downloader_id,
            task_id=task_id,
        )  # 传递task_id

        result = migrator.prepare_review_data()

        if "review_data" in result:
            new_task_id = str(uuid.uuid4())
            # 只缓存必要信息，包括种子目录路径用于发布时查找种子文件
            MIGRATION_CACHE[new_task_id] = {
                "source_info": source_info,
                "original_torrent_path": result["original_torrent_path"],
                "torrent_dir": result["torrent_dir"],  # 保存种子目录路径
                "source_site_name": english_site_name,  # 使用英文站点名作为唯一标识符
                "source_torrent_id": search_term,
            }

            logging.info(
                f"种子信息抓取并存储成功: {search_term} from {source_site_name} ({english_site_name})"
            )

            # 标记"开始抓取"步骤为成功
            log_streamer.emit_log(task_id, "开始抓取", "种子信息抓取完成", "success")
            # 关闭日志流
            log_streamer.close_stream(task_id)

            return jsonify(
                {
                    "success": True,
                    "task_id": new_task_id,
                    "message": "种子信息已成功保存到数据库",
                    "logs": result["logs"],
                }
            )
        else:
            # 抓取失败，标记为错误
            log_streamer.emit_log(task_id, "开始抓取", result.get("logs", "抓取失败"), "error")
            log_streamer.close_stream(task_id)

            return jsonify({"success": False, "message": result.get("logs", "未知错误")})
    except Exception as e:
        logging.error(f"migrate_fetch_and_store 发生意外错误: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"服务器内部错误: {e}"}), 500


# 新增：更新数据库种子参数并重新标准化的API接口
@migrate_bp.route("/migrate/update_db_seed_info", methods=["POST"])
def update_db_seed_info():
    """更新数据库中的参数并重新标准化"""
    try:
        data = request.json
        torrent_name = data.get("torrent_name")
        torrent_id = data.get("torrent_id")
        site_name = data.get("site_name")
        updated_parameters = data.get("updated_parameters")

        db_manager = migrate_bp.db_manager

        try:
            # 更新数据库
            from models.seed_parameter import SeedParameter

            seed_param_model = SeedParameter(db_manager)

            logging.info(f"开始更新种子参数: {torrent_id} from {site_name} ({site_name})")

            # 检查用户是否提供了修改的标准参数
            user_standardized_params = updated_parameters.get("standardized_params", {})

            if user_standardized_params:
                # 用户已经修改了标准参数，优先使用用户的修改
                logging.info("使用用户修改的标准参数")
                standardized_params = user_standardized_params
            else:
                # 用户没有修改标准参数，重新进行参数标准化
                logging.info("用户未修改标准参数，重新进行自动标准化")
                # 重新进行参数标准化（模拟ParameterMapper的处理）
                # 需要构造extracted_data格式用于映射
                extracted_data = {
                    "title": updated_parameters.get("title", ""),
                    "subtitle": updated_parameters.get("subtitle", ""),
                    "imdb_link": updated_parameters.get("imdb_link", ""),
                    "douban_link": updated_parameters.get("douban_link", ""),
                    "tmdb_link": updated_parameters.get("tmdb_link", ""),
                    "intro": {
                        "statement": updated_parameters.get("statement", ""),
                        "poster": updated_parameters.get("poster", ""),
                        "body": updated_parameters.get("body", ""),
                        "screenshots": updated_parameters.get("screenshots", ""),
                        "imdb_link": updated_parameters.get("imdb_link", ""),
                        "douban_link": updated_parameters.get("douban_link", ""),
                        "tmdb_link": updated_parameters.get("tmdb_link", ""),
                    },
                    "mediainfo": updated_parameters.get("mediainfo", ""),
                    "source_params": updated_parameters.get("source_params", {}),
                    "title_components": updated_parameters.get("title_components", []),
                }

                # 使用ParameterMapper重新标准化参数
                from core.extractors.extractor import ParameterMapper

                mapper = ParameterMapper()

                # 重新标准化参数
                standardized_params = mapper.map_parameters(site_name, site_name, extracted_data)

            # 从title_components中提取标题拆解的各项参数
            title_components = updated_parameters.get("title_components", [])

            # [新增] 开始：根据 title_components 拼接新标题
            # 1. 将 title_components 列表转换为字典，方便后续查找
            title_params = {
                item["key"]: item["value"] for item in title_components if item.get("value")
            }

            # 2. 从 global_mappings.yaml 读取拼接顺序
            import yaml

            global_mappings_path = GLOBAL_MAPPINGS

            # 默认顺序（如果读取配置失败时使用）
            order = [
                "主标题",
                "季集",
                "年份",
                "剧集状态",
                "发布版本",
                "分辨率",
                "片源平台",
                "媒介",
                "帧率",
                "视频编码",
                "视频格式",
                "HDR格式",
                "色深",
                "音频编码",
            ]

            try:
                if os.path.exists(global_mappings_path):
                    with open(global_mappings_path, "r", encoding="utf-8") as f:
                        global_config = yaml.safe_load(f)
                        default_title_components = global_config.get(
                            "default_title_components", {}
                        )

                        if default_title_components:
                            # 按照配置文件中的顺序构建 order 列表
                            order = []
                            for key, config in default_title_components.items():
                                if isinstance(config, dict) and "source_key" in config:
                                    order.append(config["source_key"])

                            logging.info(f"从配置文件读取到标题拼接顺序: {order}")
            except Exception as e:
                logging.warning(f"读取 global_mappings.yaml 失败，使用默认顺序: {e}")
            title_parts = []
            for key in order:
                value = title_params.get(key)
                if value:
                    title_parts.append(
                        " ".join(map(str, value)) if isinstance(value, list) else str(value)
                    )

            raw_main_part = " ".join(filter(None, title_parts))
            main_part = re.sub(r"(?<!\d)\.(?!\d)", " ", raw_main_part)
            main_part = re.sub(r"\s+", " ", main_part).strip()
            release_group = title_params.get("制作组", "NOGROUP")
            if "N/A" in release_group:
                release_group = "NOGROUP"

            # 对特殊制作组进行处理，不需要添加前缀连字符
            special_groups = ["MNHD-FRDS", "mUHD-FRDS"]
            if release_group in special_groups:
                preview_title = f"{main_part} {release_group}"
            else:
                preview_title = f"{main_part}-{release_group}"
            # [新增] 结束：标题拼接完成，结果保存在 preview_title 变量中

            # 构造完整的存储参数
            final_parameters = {
                # [修改] 将原来的 title 值替换为新生成的 preview_title
                "title": preview_title,
                "subtitle": updated_parameters.get("subtitle", ""),
                "imdb_link": updated_parameters.get("imdb_link", ""),
                "douban_link": updated_parameters.get("douban_link", ""),
                "tmdb_link": updated_parameters.get("tmdb_link", ""),
                "poster": updated_parameters.get("poster", ""),
                "screenshots": updated_parameters.get("screenshots", ""),
                "statement": updated_parameters.get("statement", ""),
                "body": updated_parameters.get("body", ""),
                "mediainfo": updated_parameters.get("mediainfo", ""),
                "type": standardized_params.get("type", ""),
                "medium": standardized_params.get("medium", ""),
                "video_codec": standardized_params.get("video_codec", ""),
                "audio_codec": standardized_params.get("audio_codec", ""),
                "resolution": standardized_params.get("resolution", ""),
                "team": standardized_params.get("team", ""),
                "source": standardized_params.get("source", ""),
                "tags": standardized_params.get("tags", []),
                "title_components": title_components,
                "standardized_params": standardized_params,
                "is_reviewed": True,  # 标记为已检查
                "final_publish_parameters": {
                    # [修改] 预览标题也使用新生成的标题
                    "主标题 (预览)": preview_title,
                    "副标题": updated_parameters.get("subtitle", ""),
                    "IMDb链接": standardized_params.get("imdb_link", ""),
                    "豆瓣链接": standardized_params.get("douban_link", ""),
                    "TMDb链接": standardized_params.get("tmdb_link", ""),
                    "类型": standardized_params.get("type", ""),
                    "媒介": standardized_params.get("medium", ""),
                    "视频编码": standardized_params.get("video_codec", ""),
                    "音频编码": standardized_params.get("audio_codec", ""),
                    "分辨率": standardized_params.get("resolution", ""),
                    "制作组": standardized_params.get("team", ""),
                    "产地": standardized_params.get("source", ""),
                    "标签": standardized_params.get("tags", []),
                },
                "complete_publish_params": {
                    "title_components": updated_parameters.get("title_components", []),
                    "subtitle": updated_parameters.get("subtitle", ""),
                    "imdb_link": standardized_params.get("imdb_link", ""),
                    "douban_link": standardized_params.get("douban_link", ""),
                    "tmdb_link": standardized_params.get("tmdb_link", ""),
                    "intro": {
                        "statement": updated_parameters.get("statement", ""),
                        "poster": updated_parameters.get("poster", ""),
                        "body": updated_parameters.get("body", ""),
                        "screenshots": updated_parameters.get("screenshots", ""),
                        "removed_ardtudeclarations": updated_parameters.get(
                            "removed_ardtudeclarations", []
                        ),
                        "imdb_link": updated_parameters.get("imdb_link", ""),
                        "douban_link": updated_parameters.get("douban_link", ""),
                    },
                    "mediainfo": updated_parameters.get("mediainfo", ""),
                    "source_params": updated_parameters.get("source_params", {}),
                    "standardized_params": standardized_params,
                },
                "raw_params_for_preview": {
                    # [修改] 原始预览参数也使用新标题
                    "final_main_title": preview_title,
                    "subtitle": updated_parameters.get("subtitle", ""),
                    "imdb_link": standardized_params.get("imdb_link", ""),
                    "douban_link": standardized_params.get("douban_link", ""),
                    "tmdb_link": standardized_params.get("tmdb_link", ""),
                    "type": standardized_params.get("type", ""),
                    "medium": standardized_params.get("medium", ""),
                    "video_codec": standardized_params.get("video_codec", ""),
                    "audio_codec": standardized_params.get("audio_codec", ""),
                    "resolution": standardized_params.get("resolution", ""),
                    "release_group": standardized_params.get("team", ""),
                    "source": standardized_params.get("source", ""),
                    "tags": standardized_params.get("tags", []),
                },
            }

            # 需要先获取hash值
            hash_value = seed_param_model.search_torrent_hash_by_torrentid(torrent_id, site_name)
            if hash_value:
                update_result = seed_param_model.update_parameters(hash_value, final_parameters)
            else:
                # 如果找不到hash，尝试插入新记录
                final_parameters["hash"] = f"manual_{torrent_id}_{site_name}"  # 临时hash
                final_parameters["torrent_id"] = torrent_id
                final_parameters["site_name"] = site_name
                # 确保传递正确的 torrent_id 和 site_name
                update_result = seed_param_model.save_parameters(
                    final_parameters["hash"], torrent_id, site_name, final_parameters
                )

            if update_result:
                logging.info(f"种子参数更新成功: {torrent_id} from {site_name} ({site_name})")

                # 生成反向映射表（从标准键到中文显示名称的映射）
                reverse_mappings = generate_reverse_mappings()

                return jsonify(
                    {
                        "success": True,
                        "standardized_params": standardized_params,
                        "final_publish_parameters": final_parameters["final_publish_parameters"],
                        "complete_publish_params": final_parameters["complete_publish_params"],
                        "raw_params_for_preview": final_parameters["raw_params_for_preview"],
                        "reverse_mappings": reverse_mappings,
                        "message": "参数更新并标准化成功",
                    }
                )
            else:
                logging.warning(f"种子参数更新失败: {torrent_id} from {site_name} ({site_name})")
                return jsonify({"success": False, "message": "参数更新失败"}), 500

        except Exception as e:
            logging.error(f"更新种子参数失败: {e}", exc_info=True)
            return jsonify({"success": False, "message": f"更新失败: {str(e)}"}), 500

    except Exception as e:
        logging.error(f"update_db_seed_info发生意外错误: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"服务器内部错误: {str(e)}"}), 500


@migrate_bp.route("/migrate/publish", methods=["POST"])
def migrate_publish():
    db_manager = migrate_bp.db_manager
    data = request.json
    task_id, upload_data, target_site_name, source_site_name = (
        data.get("task_id"),
        data.get("upload_data"),
        data.get("targetSite"),
        data.get("sourceSite"),
    )

    if not task_id or task_id not in MIGRATION_CACHE:
        return jsonify({"success": False, "logs": "错误：无效或已过期的任务ID。"}), 400

    if not target_site_name:
        return jsonify({"success": False, "logs": "错误：必须提供目标站点名称。"}), 400

    context = MIGRATION_CACHE[task_id]

    migrator = None  # 确保在 finally 中可用

    try:
        # 🚫 发布前标签限制检查：禁转/限转/分集直接拦截
        restricted_tag_map = {
            "禁转": "tag.禁转",
            "tag.禁转": "tag.禁转",
            "限转": "tag.限转",
            "tag.限转": "tag.限转",
            "分集": "tag.分集",
            "tag.分集": "tag.分集",
        }
        standardized_params = (upload_data or {}).get("standardized_params", {})
        raw_tags = (standardized_params.get("tags") or []) + (upload_data or {}).get("tags", [])
        restricted_tags = []
        for tag in raw_tags:
            mapped_tag = restricted_tag_map.get(tag)
            if mapped_tag and mapped_tag not in restricted_tags:
                restricted_tags.append(mapped_tag)

        if restricted_tags:
            return jsonify(
                {
                    "success": False,
                    "logs": f"🚫 发布前标签限制: 检测到禁转/限转/分集标签 {restricted_tags}",
                    "limit_reached": True,
                    "pre_check": True,
                }
            )

        target_info = db_manager.get_site_by_nickname(target_site_name)
        if not target_info:
            return (
                jsonify(
                    {"success": False, "logs": f"错误: 目标站点 '{target_site_name}' 配置不完整。"}
                ),
                404,
            )

        source_info = context["source_info"]
        original_torrent_path = context["original_torrent_path"]
        torrent_dir = context.get("torrent_dir", "")  # 获取种子目录

        # 从缓存中获取源站点名称（如果前端没有传递）
        if not source_site_name:
            source_site_name = context.get("source_site_name", "")

        # 🚫 发布前预检查发种限制 - 在任何发布逻辑之前进行
        downloader_id = data.get("downloaderId") or data.get("downloader_id")
        if downloader_id:
            try:
                from .internal_guard import check_downloader_gate

                can_continue, limit_message = check_downloader_gate(downloader_id)

                if not can_continue:
                    return jsonify(
                        {
                            "success": False,
                            "logs": f"🚫 发布前预检查触发限制: {limit_message}",
                            "limit_reached": True,
                            "pre_check": True,
                        }
                    )
                else:
                    print(f"✅ [发布前预检查] 通过，可以继续发布到 {target_site_name}")
            except Exception as e:
                print(f"⚠️ [发布前预检查] 检查失败，继续执行: {e}")

        # 创建 TorrentMigrator 实例用于发布
        migrator = TorrentMigrator(
            source_info,
            target_info,
            search_term=context.get("source_torrent_id", ""),
            save_path=upload_data.get("save_path", "") or upload_data.get("savePath", ""),
            config_manager=config_manager,
            db_manager=db_manager,
        )

        # 检查种子文件是否存在，如果不存在则重新下载
        # [核心修改] 优先在统一的 torrents 目录中查找
        source_torrent_id = context.get("source_torrent_id", "")
        source_site_code = source_info.get("site", source_site_name.lower())

        if original_torrent_path is None or not os.path.exists(original_torrent_path):
            logging.info("原始种子文件路径不存在，开始在统一目录中查找")

            from config import TEMP_DIR

            torrents_dir = os.path.join(TEMP_DIR, "torrents")

            # [新增] 首先在统一的 torrents 目录中查找以"站点-ID-"开头的种子文件
            if os.path.exists(torrents_dir) and source_torrent_id:
                prefix = f"{source_site_code}-{source_torrent_id}-"
                logging.info(f"在统一目录中查找种子文件，前缀: {prefix}")

                try:
                    for file in os.listdir(torrents_dir):
                        if file.startswith(prefix) and file.endswith(".torrent"):
                            original_torrent_path = os.path.join(torrents_dir, file)
                            logging.info(f"✅ 在统一目录中找到种子文件: {file}")
                            break
                except Exception as e:
                    logging.warning(f"遍历统一目录时出错: {e}")

            # 如果在统一目录中没找到，再检查旧格式目录
            if (
                original_torrent_path is None or not os.path.exists(original_torrent_path)
            ) and source_torrent_id:
                logging.info("统一目录中未找到，检查旧格式目录")
                # 检查旧格式目录
                old_torrent_dir = os.path.join(TEMP_DIR, f"torrent_{source_torrent_id}")
                if os.path.exists(old_torrent_dir):
                    try:
                        # 查找old_torrent_dir中的.torrent文件
                        for file in os.listdir(old_torrent_dir):
                            if file.endswith(".torrent"):
                                original_torrent_path = os.path.join(old_torrent_dir, file)
                                logging.info(
                                    f"在旧格式临时目录中找到种子文件: {original_torrent_path}"
                                )
                                break
                    except Exception as e:
                        logging.warning(f"查找旧格式临时目录中的种子文件时出错: {e}")

                # 如果在旧格式目录中没找到，检查以种子名称命名的目录（新格式）
                if original_torrent_path is None or not os.path.exists(original_torrent_path):
                    # 尝试从缓存中获取种子目录路径
                    cached_torrent_dir = context.get("torrent_dir")
                    if cached_torrent_dir and os.path.exists(cached_torrent_dir):
                        try:
                            # 查找cached_torrent_dir中的.torrent文件
                            for file in os.listdir(cached_torrent_dir):
                                if file.endswith(".torrent"):
                                    original_torrent_path = os.path.join(cached_torrent_dir, file)
                                    logging.info(
                                        f"在新格式临时目录中找到种子文件: {original_torrent_path}"
                                    )
                                    break
                        except Exception as e:
                            logging.warning(f"查找新格式临时目录中的种子文件时出错: {e}")
                    else:
                        # 如果缓存中没有torrent_dir或目录不存在，尝试重构路径
                        # 使用种子ID从数据库获取种子信息，然后重建目录路径
                        try:
                            from models.seed_parameter import SeedParameter
                            from flask import current_app

                            db_manager = current_app.config["DB_MANAGER"]
                            seed_param_model = SeedParameter(db_manager)

                            source_torrent_id = context.get("source_torrent_id", "")
                            source_site_name = context.get("source_site_name", "")

                            if source_torrent_id and source_site_name:
                                # 从数据库获取种子参数
                                parameters = seed_param_model.get_parameters(
                                    source_torrent_id, source_site_name
                                )
                                if parameters and parameters.get("title"):
                                    # 重建种子目录路径
                                    from config import TEMP_DIR
                                    import re

                                    original_main_title = parameters.get("title", "")
                                    safe_filename_base = re.sub(
                                        r'[\\/*?:"<>|]', "_", original_main_title
                                    )[:150]
                                    reconstructed_torrent_dir = os.path.join(
                                        TEMP_DIR, safe_filename_base
                                    )

                                    if os.path.exists(reconstructed_torrent_dir):
                                        try:
                                            # 查找reconstructed_torrent_dir中的.torrent文件
                                            for file in os.listdir(reconstructed_torrent_dir):
                                                if file.endswith(".torrent"):
                                                    original_torrent_path = os.path.join(
                                                        reconstructed_torrent_dir, file
                                                    )
                                                    logging.info(
                                                        f"在重构的目录中找到种子文件: {original_torrent_path}"
                                                    )
                                                    break
                                        except Exception as e:
                                            logging.warning(f"查找重构目录中的种子文件时出错: {e}")
                        except Exception as e:
                            logging.warning(f"尝试重构种子目录路径时出错: {e}")

            # 如果仍然没有找到，直接在TEMP_DIR中查找以种子名称命名的目录
            if original_torrent_path is None or not os.path.exists(original_torrent_path):
                try:
                    # 从数据库获取种子参数来确定目录名
                    from models.seed_parameter import SeedParameter
                    from flask import current_app

                    db_manager = current_app.config["DB_MANAGER"]
                    seed_param_model = SeedParameter(db_manager)

                    source_torrent_id = context.get("source_torrent_id", "")
                    source_site_name = context.get("source_site_name", "")

                    if source_torrent_id and source_site_name:
                        # 从数据库获取种子参数
                        parameters = seed_param_model.get_parameters(
                            source_torrent_id, source_site_name
                        )
                        if parameters and parameters.get("title"):
                            # 重建种子目录路径
                            from config import TEMP_DIR
                            import re

                            original_main_title = parameters.get("title", "")
                            safe_filename_base = re.sub(r'[\\/*?:"<>|]', "_", original_main_title)[
                                :150
                            ]
                            seed_name_dir = os.path.join(TEMP_DIR, safe_filename_base)

                            # 在该目录中查找.torrent文件
                            if os.path.exists(seed_name_dir):
                                for file in os.listdir(seed_name_dir):
                                    if file.endswith(".torrent"):
                                        original_torrent_path = os.path.join(seed_name_dir, file)
                                        logging.info(
                                            f"在种子名称目录中找到种子文件: {original_torrent_path}"
                                        )
                                        break
                except Exception as e:
                    logging.warning(f"查找种子名称目录中的种子文件时出错: {e}")

            # 如果仍然没有找到有效的种子文件，则重新下载
            if original_torrent_path is None or not os.path.exists(original_torrent_path):
                logging.info("需要重新下载种子文件")
                # 重新下载种子文件
                try:
                    import cloudscraper
                    import re
                    from config import TEMP_DIR

                    # 初始化scraper
                    session = requests.Session()
                    session.verify = False
                    scraper = cloudscraper.create_scraper(sess=session)

                    # 构造下载链接
                    SOURCE_BASE_URL = source_info.get("base_url", "").rstrip("/")
                    # 确保URL有正确的协议前缀
                    if SOURCE_BASE_URL and not SOURCE_BASE_URL.startswith(("http://", "https://")):
                        SOURCE_BASE_URL = "https://" + SOURCE_BASE_URL
                    SOURCE_COOKIE = source_info.get("cookie", "")
                    source_torrent_id = context.get("source_torrent_id", "")

                    if SOURCE_BASE_URL and SOURCE_COOKIE and source_torrent_id:
                        # 获取详情页以找到下载链接
                        response = scraper.get(
                            f"{SOURCE_BASE_URL}/details.php",
                            headers={
                                "Cookie": SOURCE_COOKIE,
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
                            },
                            params={"id": source_torrent_id, "hit": "1"},
                            timeout=180,
                        )
                        response.raise_for_status()
                        response.encoding = "utf-8"

                        from bs4 import BeautifulSoup

                        soup = BeautifulSoup(response.text, "html.parser")
                        download_link_tag = soup.select_one(
                            f'a.index[href^="download.php?id={source_torrent_id}"]'
                        )

                        if download_link_tag:
                            # 下载种子文件
                            torrent_response = scraper.get(
                                f"{SOURCE_BASE_URL}/{download_link_tag['href']}",
                                headers={
                                    "Cookie": SOURCE_COOKIE,
                                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
                                },
                                timeout=180,
                            )
                            torrent_response.raise_for_status()

                            # 从响应头中尝试获取文件名
                            content_disposition = torrent_response.headers.get(
                                "content-disposition"
                            )
                            torrent_filename = "unknown.torrent"
                            if content_disposition:
                                # 尝试匹配filename*（支持UTF-8编码）和filename
                                filename_match = re.search(
                                    r'filename\*="?UTF-8\'\'([^"]+)"?',
                                    content_disposition,
                                    re.IGNORECASE,
                                )
                                if filename_match:
                                    torrent_filename = filename_match.group(1)
                                    # URL解码文件名（UTF-8编码）
                                    torrent_filename = urllib.parse.unquote(
                                        torrent_filename, encoding="utf-8"
                                    )
                                else:
                                    # 尝试匹配普通的filename
                                    filename_match = re.search(
                                        r'filename="?([^"]+)"?', content_disposition
                                    )
                                    if filename_match:
                                        torrent_filename = filename_match.group(1)
                                        # URL解码文件名
                                        torrent_filename = urllib.parse.unquote(torrent_filename)

                            # 使用统一的种子目录
                            from config import TEMP_DIR

                            torrent_dir = os.path.join(TEMP_DIR, "torrents")
                            os.makedirs(torrent_dir, exist_ok=True)

                            # 获取站点代码用于文件名前缀
                            source_site_code = source_info.get("site", source_site_name.lower())

                            # 保存种子文件，添加站点-ID-前缀
                            try:
                                # 对文件名进行文件系统安全的处理
                                safe_filename = torrent_filename
                                # 移除或替换文件系统不支持的字符
                                safe_filename = re.sub(r'[<>:"/\\|?*]', "_", safe_filename)
                                # 确保文件名不超过文件系统限制
                                if len(safe_filename.encode("utf-8")) > 255:
                                    # 如果文件名太长，截断并保持扩展名
                                    name, ext = os.path.splitext(safe_filename)
                                    max_len = 255 - len(ext.encode("utf-8"))
                                    safe_filename = (
                                        name.encode("utf-8")[:max_len].decode("utf-8", "ignore")
                                        + ext
                                    )

                                # 添加站点-ID-前缀
                                prefixed_filename = (
                                    f"{source_site_code}-{source_torrent_id}-{safe_filename}"
                                )
                                original_torrent_path = os.path.join(
                                    torrent_dir, prefixed_filename
                                )
                                with open(original_torrent_path, "wb") as f:
                                    f.write(torrent_response.content)
                                logging.info(f"种子文件已保存: {prefixed_filename}")
                            except OSError as e:
                                # 如果文件名有问题，使用默认名称
                                logging.warning(f"使用原始文件名保存失败: {e}, 使用默认名称")
                                prefixed_filename = (
                                    f"{source_site_code}-{source_torrent_id}-torrent.torrent"
                                )
                                original_torrent_path = os.path.join(
                                    torrent_dir, prefixed_filename
                                )
                                with open(original_torrent_path, "wb") as f:
                                    f.write(torrent_response.content)

                            logging.info(f"重新下载种子文件成功: {original_torrent_path}")
                        else:
                            logging.error("未找到种子下载链接")
                            return (
                                jsonify({"success": False, "logs": "错误：未找到种子下载链接。"}),
                                404,
                            )
                    else:
                        logging.error("缺少必要的源站点信息")
                        return (
                            jsonify({"success": False, "logs": "错误：缺少必要的源站点信息。"}),
                            400,
                        )
                except Exception as e:
                    logging.error(f"重新下载种子文件失败: {e}")
                    return jsonify({"success": False, "logs": f"重新下载种子文件失败: {e}"}), 500

        # 1. 直接使用原始种子文件路径进行发布（不再修改种子）
        if not original_torrent_path or not os.path.exists(original_torrent_path):
            raise Exception("原始种子文件路径无效或文件不存在。")

        # 2. 发布 (传递 torrent_dir 给上传器)
        upload_data["torrent_dir"] = torrent_dir  # 确保上传器能获取到 torrent_dir
        result = migrator.publish_prepared_torrent(upload_data, original_torrent_path)

        # 3. 如果发布成功，自动添加到下载器
        if result.get("success") and result.get("url"):
            auto_add = data.get("auto_add_to_downloader", True)  # 默认自动添加
            print(f"[下载器添加] 发布成功, auto_add={auto_add}, url={result.get('url')}")

            if auto_add:
                # 先获取配置的默认下载器
                config = config_manager.get()
                default_downloader = config.get("cross_seed", {}).get("default_downloader")

                # 从请求中获取下载器ID和保存路径
                downloader_id = data.get("downloaderId") or data.get("downloader_id")
                save_path = upload_data.get("save_path") or upload_data.get("savePath")
                print(
                    f"[下载器添加] 初始参数: downloader_id={downloader_id}, save_path={save_path}"
                )
                print(f"[下载器添加] 配置的默认下载器: {default_downloader}")

                # 判断逻辑:
                # 1. 如果配置了具体的默认下载器(非空非None),使用它
                # 2. 如果配置为空或"使用源种子下载器",则从数据库查询源种子的下载器
                # 3. 无论哪种情况,如果缺少save_path,都尝试从数据库获取

                if default_downloader and default_downloader != "":
                    # 配置了具体的下载器,使用配置的下载器
                    downloader_id = default_downloader
                    print(f"[下载器添加] 使用配置的默认下载器: {downloader_id}")

                    # 如果没有save_path,尝试从数据库获取源种子的save_path
                    if not save_path:
                        print(f"[下载器添加] 缺少save_path,从数据库获取源种子的保存路径")
                        source_torrent_id = context.get("source_torrent_id")
                        if source_torrent_id and source_site_name:
                            hash_value = get_seed_hash(
                                db_manager, source_torrent_id, source_site_name
                            )
                            torrent_info = get_current_torrent_info(db_manager, hash_value)
                            if torrent_info and torrent_info.get("save_path"):
                                save_path = torrent_info["save_path"]
                                print(f"[下载器添加] 从数据库获取到保存路径: {save_path}")
                            else:
                                print(f"[下载器添加] 数据库中未找到保存路径")
                else:
                    # 配置为"使用源种子所在的下载器"或未配置
                    # 尝试从数据库查询原始种子的下载器和保存路径
                    print(f"[下载器添加] 配置为使用源种子下载器,从数据库查询")
                    source_torrent_id = context.get("source_torrent_id")
                    if source_torrent_id and source_site_name:
                        hash_value = get_seed_hash(db_manager, source_torrent_id, source_site_name)
                        torrent_info = get_current_torrent_info(db_manager, hash_value)
                        if torrent_info:
                            downloader_id = torrent_info.get("downloader_id")
                            if not save_path and torrent_info.get("save_path"):
                                save_path = torrent_info["save_path"]
                                print(f"[下载器添加] 从数据库获取到保存路径: {save_path}")
                            print(f"[下载器添加] 从数据库获取到源种子的下载器ID: {downloader_id}")
                        else:
                            print(f"[下载器添加] 数据库中未找到源种子信息")

                    if not downloader_id:
                        print(f"[下载器添加] 未找到源种子的下载器信息")

                # 调用添加到下载器
                if save_path and downloader_id:
                    try:
                        print(
                            f"[下载器添加] 准备同步添加到下载器: URL={result['url']}, Path={save_path}, DownloaderID={downloader_id}"
                        )
                        print(f"[下载器添加] 结果详情: {result}")
                        print(
                            f"[下载器添加] 直接下载链接: {result.get('direct_download_url', 'None')}"
                        )

                        # 🚫 发布前预检查发种限制
                        try:
                            from .internal_guard import check_downloader_gate

                            can_continue, limit_message = check_downloader_gate(downloader_id)

                            if not can_continue:
                                print(f"🚫 [下载器添加] 发布前预检查触发限制: {limit_message}")
                                result["auto_add_result"] = {
                                    "success": False,
                                    "message": limit_message,
                                    "sync": True,
                                    "downloader_id": None,
                                    "limit_reached": True,
                                    "pre_check": True,
                                }
                                return jsonify(result)
                            else:
                                print(f"✅ [下载器添加] 发布前预检查通过，可以继续添加")
                        except Exception as e:
                            print(f"⚠️ [下载器添加] 发布前预检查失败，继续执行: {e}")

                        # 同步调用 add_torrent_to_downloader 函数
                        success, message = add_torrent_to_downloader(
                            detail_page_url=result["url"],
                            save_path=save_path,
                            downloader_id=downloader_id,
                            db_manager=db_manager,
                            config_manager=config_manager,
                            direct_download_url=result.get("direct_download_url"),
                        )

                        # 检查是否触发发种限制
                        limit_reached = success == "LIMIT_REACHED"

                        result["auto_add_result"] = {
                            "success": not limit_reached,  # 限制触发时视为失败
                            "message": message,
                            "sync": True,
                            "downloader_id": downloader_id if not limit_reached else None,
                            "limit_reached": limit_reached,
                        }

                        if not limit_reached and success:
                            print(f"✅ [下载器添加] 同步添加成功: {message}")
                        elif limit_reached:
                            print(f"🚫 [下载器添加] 同步添加被限制: {message}")
                        else:
                            print(f"❌ [下载器添加] 同步添加失败: {message}")

                    except Exception as e:
                        print(f"❌ [下载器添加] 同步添加异常: {e}")
                        import traceback

                        traceback.print_exc()
                        result["auto_add_result"] = {
                            "success": False,
                            "message": f"添加到下载器失败: {str(e)}",
                        }
                else:
                    missing = []
                    if not save_path:
                        missing.append("save_path")
                    if not downloader_id:
                        missing.append("downloader_id")
                    print(f"⚠️ [下载器添加] 跳过: 缺少参数 {', '.join(missing)}")
                    result["auto_add_result"] = {
                        "success": False,
                        "message": f"缺少必要参数: {', '.join(missing)}",
                    }
            else:
                print(f"[下载器添加] auto_add=False, 跳过自动添加")
        else:
            if not result.get("success"):
                print(f"[下载器添加] 发布失败,跳过下载器添加")
            elif not result.get("url"):
                print(f"[下载器添加] 发布成功但未返回URL,跳过下载器添加")

        # 处理批量转种记录 - 创建 batch_enhance_records 表记录
        batch_id = data.get("batch_id")  # Go端传递的批次ID
        print(f"\n{'='*80}")
        print(f"[批量转种记录] 检测到batch_id参数: {batch_id}")

        if batch_id:
            try:
                # 从 context 中获取种子信息
                source_torrent_id = context.get("source_torrent_id")
                print(
                    f"[批量转种记录] 种子信息: torrent_id={source_torrent_id}, source_site={source_site_name}, target_site={target_site_name}"
                )

                if source_torrent_id and source_site_name and target_site_name:
                    # [修复] 从数据库获取种子标题
                    seed_title = "未知标题"
                    try:
                        from models.seed_parameter import SeedParameter

                        seed_param_model = SeedParameter(db_manager)
                        seed_parameters = seed_param_model.get_parameters(
                            source_torrent_id, source_site_name
                        )
                        if seed_parameters and seed_parameters.get("title"):
                            seed_title = seed_parameters.get("title")
                            print(f"[批量转种记录] 从数据库获取到种子标题: {seed_title}")
                        else:
                            print(f"[批量转种记录] ⚠️ 数据库中未找到种子标题，使用默认值")
                    except Exception as e:
                        print(f"[批量转种记录] ⚠️ 查询种子标题失败: {e}")

                    conn = db_manager._get_connection()
                    cursor = db_manager._get_cursor(conn)

                    # 准备记录数据
                    video_size_gb = data.get("video_size_gb")  # Go端可能传递的视频大小
                    status = "success" if result.get("success") else "failed"
                    success_url = result.get("url") if result.get("success") else None
                    error_detail = result.get("logs") if not result.get("success") else None

                    print(
                        f"[批量转种记录] 发布结果: status={status}, success_url={success_url}, video_size_gb={video_size_gb}"
                    )

                    # 生成下载器添加结果文本
                    downloader_result = None
                    if "auto_add_result" in result:
                        auto_result = result["auto_add_result"]
                        print(f"[批量转种记录] 下载器添加结果: {auto_result}")
                        if auto_result["success"]:
                            downloader_result = f"成功: {auto_result['message']}"
                        else:
                            downloader_result = f"失败: {auto_result['message']}"
                    else:
                        print(f"[批量转种记录] ⚠️ 未找到auto_add_result字段")
                        print(f"[批量转种记录] result所有键: {list(result.keys())}")
                        print(f"[批量转种记录] result完整内容: {result}")

                    print(f"[批量转种记录] 准备写入数据库: downloader_result={downloader_result}")

                    # 直接插入记录(发布的种子不会先被Go端插入,只有过滤的种子才会)
                    if db_manager.db_type == "mysql":
                        insert_sql = """INSERT INTO batch_enhance_records
                                      (batch_id, title, torrent_id, source_site, target_site, progress, video_size_gb, status, success_url, error_detail, downloader_add_result)
                                      VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
                    elif db_manager.db_type == "postgresql":
                        insert_sql = """INSERT INTO batch_enhance_records
                                      (batch_id, title, torrent_id, source_site, target_site, progress, video_size_gb, status, success_url, error_detail, downloader_add_result)
                                      VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
                    else:  # sqlite
                        insert_sql = """INSERT INTO batch_enhance_records
                                      (batch_id, title, torrent_id, source_site, target_site, progress, video_size_gb, status, success_url, error_detail, downloader_add_result)
                                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""

                    print(
                        f"[批量转种记录] 执行SQL插入: batch_id={batch_id}, torrent_id={source_torrent_id}, title={seed_title}"
                    )
                    cursor.execute(
                        insert_sql,
                        (
                            batch_id,
                            seed_title,
                            source_torrent_id,
                            data.get("nickname", source_site_name),
                            target_site_name,
                            data.get("batch_progress"),
                            video_size_gb,
                            status,
                            success_url,
                            error_detail,
                            downloader_result,
                        ),
                    )
                    conn.commit()
                    cursor.close()
                    conn.close()

                    print(
                        f"✅ [批量转种记录] 成功写入数据库: {source_torrent_id} -> {target_site_name}"
                    )
                    print(f"   状态: {status}")
                    print(f"   下载器结果: {downloader_result}")
                else:
                    print(f"❌ [批量转种记录] 缺少必要的种子信息:")
                    print(f"   torrent_id={source_torrent_id}")
                    print(f"   source_site={source_site_name}")
                    print(f"   target_site={target_site_name}")

            except Exception as e:
                print(f"❌ [批量转种记录] 记录时出错: {e}")
                import traceback

                traceback.print_exc()
        else:
            print(f"[批量转种记录] 未检测到batch_id参数,跳过记录到batch_enhance_records表")

        print(f"{'='*80}\n")

        return jsonify(result)

    except Exception as e:
        logging.error(f"migrate_publish to {target_site_name} 发生意外错误: {e}", exc_info=True)
        return jsonify({"success": False, "logs": f"服务器内部错误: {e}", "url": None}), 500
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
                jsonify(
                    {
                        "success": False,
                        "logs": f"错误：未找到源站点 '{source_site_name}' 或其缺少 Cookie 配置。",
                    }
                ),
                404,
            )
        if not target_info or not target_info.get("cookie"):
            return (
                jsonify(
                    {
                        "success": False,
                        "logs": f"错误：未找到目标站点 '{target_site_name}' 或其缺少 Cookie 配置。",
                    }
                ),
                404,
            )

        migrator = TorrentMigrator(
            source_info,
            target_info,
            search_term,
            config_manager=config_manager,
            db_manager=db_manager,
        )
        if hasattr(migrator, "run"):
            result = migrator.run()
            return jsonify(result)
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "logs": "错误：此服务器不支持一步式迁移，请使用新版迁移工具。",
                    }
                ),
                501,
            )

    except Exception as e:
        logging.error(f"migrate_torrent 发生意外错误: {e}", exc_info=True)
        return jsonify({"success": False, "logs": f"服务器内部错误: {e}"}), 500


@migrate_bp.route("/utils/parse_title", methods=["POST"])
def parse_title_utility():
    """接收一个标题字符串，返回解析后的参数字典。"""
    from utils.mediainfo_parser import (
        extract_hdr_info_from_mediainfo,
        extract_audio_info_from_mediainfo,
    )

    data = request.json
    title_to_parse = data.get("title")
    mediainfo = data.get("mediainfo", "")  # 可选的 mediaInfo 参数

    if not title_to_parse:
        return jsonify({"success": False, "error": "标题不能为空。"}), 400

    try:
        # 从 MediaInfo 提取 HDR 和音频信息
        mediainfo_hdr = None
        mediainfo_audio = None

        if mediainfo and mediainfo.strip():
            try:
                mediainfo_hdr = extract_hdr_info_from_mediainfo(mediainfo)
                mediainfo_audio = extract_audio_info_from_mediainfo(mediainfo)
                logging.info(f"从 MediaInfo 提取到 HDR 信息: {mediainfo_hdr}")
                logging.info(f"从 MediaInfo 提取到音频信息: {mediainfo_audio}")
            except Exception as e:
                logging.warning(f"从 MediaInfo 提取 HDR/音频信息失败: {e}")

        # 传递 mediaInfo 参数以便修正 Blu-ray/BluRay 格式，以及 HDR 和音频信息
        parsed_components = upload_data_title(
            title_to_parse,
            mediaInfo=mediainfo,
            mediainfo_hdr=mediainfo_hdr,
            mediainfo_audio=mediainfo_audio,
        )

        if not parsed_components:
            return jsonify(
                {
                    "success": False,
                    "message": "未能从此标题中解析出有效参数。",
                    "components": {
                        "主标题": title_to_parse,
                        "无法识别": "解析失败",
                    },
                }
            )

        return jsonify({"success": True, "components": parsed_components})

    except Exception as e:
        logging.error(f"parse_title_utility 发生意外错误: {e}", exc_info=True)
        return jsonify({"success": False, "error": f"服务器内部错误: {e}"}), 500


@migrate_bp.route("/media/validate", methods=["POST"])
def validate_media():
    """接收前端发送的失效图片信息或简介重新获取请求。"""
    data = request.json

    media_type = data.get("type")
    source_info = data.get("source_info")
    save_path = data.get("savePath")
    torrent_name = data.get("torrentName")
    downloader_id = data.get("downloaderId")  # 获取下载器ID
    subtitle = source_info.get("subtitle") if source_info else ""
    imdb_link = source_info.get("imdb_link", "") if source_info else ""
    douban_link = source_info.get("douban_link", "") if source_info else ""
    tmdb_link = source_info.get("tmdb_link", "") if source_info else ""
    content_name = data.get("content_name") or (
        source_info.get("main_title") if source_info else ""
    )

    logging.info(
        f"收到媒体处理请求 - 类型: {media_type}, "
        f"来源信息: {source_info}，视频路径: {save_path}，种子名称: {torrent_name}, 下载器ID: {downloader_id}"
    )

    if media_type == "screenshot":
        screenshots = upload_data_screenshot(source_info, save_path, torrent_name, downloader_id)
        return jsonify({"success": True, "screenshots": screenshots}), 200
    elif media_type == "poster":
        # 海报验证和转存已经在 upload_data_movie_info -> _parse_format_content 中自动完成
        (
            status,
            posters,
            description,
            extracted_imdb_link,
            extracted_douban_link,
            extracted_tmdb_link,
        ) = upload_data_movie_info(media_type, douban_link, imdb_link, tmdb_link, subtitle)
        if status:
            return (
                jsonify(
                    {
                        "success": True,
                        "posters": posters,
                        "extracted_imdb_link": extracted_imdb_link,
                        "extracted_douban_link": extracted_douban_link,
                        "extracted_tmdb_link": extracted_tmdb_link,
                    }
                ),
                200,
            )
        else:
            return jsonify({"success": False, "error": posters}), 400
    elif media_type == "intro":
        # 处理简介重新获取请求
        (
            status,
            posters,
            description,
            extracted_imdb_link,
            extracted_douban_link,
            extracted_tmdb_link,
        ) = upload_data_movie_info(media_type, douban_link, imdb_link, tmdb_link, subtitle)

        if status:
            response_data = {
                "success": True,
                "intro": description,
                "extracted_imdb_link": extracted_imdb_link,
                "extracted_douban_link": extracted_douban_link,
                "extracted_tmdb_link": extracted_tmdb_link,
            }
            return jsonify(response_data), 200
        else:
            return jsonify({"success": False, "error": description}), 400
    elif media_type == "mediainfo":
        # 处理媒体信息重新获取请求
        from utils import upload_data_mediaInfo

        # 获取当前的mediainfo（如果有的话）
        current_mediainfo = data.get("current_mediainfo", "")
        # 调用upload_data_mediaInfo函数重新生成mediainfo，设置force_refresh=True强制重新获取
        new_mediainfo, _, _ = upload_data_mediaInfo(
            current_mediainfo,
            save_path,
            torrent_name=torrent_name,
            content_name=content_name,
            downloader_id=downloader_id,
            force_refresh=True,
        )  # 强制重新获取
        if new_mediainfo:
            return jsonify({"success": True, "mediainfo": new_mediainfo}), 200
        else:
            return jsonify({"success": False, "error": "无法生成媒体信息"}), 400
    else:
        return jsonify({"success": False, "error": f"不支持的媒体类型: {media_type}"}), 400


@migrate_bp.route("/migrate/get_downloader_info", methods=["POST"])
def get_downloader_info():
    """获取种子的下载器信息（用于Go服务查询）"""
    db_manager = migrate_bp.db_manager
    data = request.json

    torrent_id = data.get("torrent_id")
    site_name = data.get("site_name")

    if not torrent_id or not site_name:
        return jsonify({"success": False, "message": "缺少必要参数: torrent_id 或 site_name"}), 400

    try:
        hash_value = get_seed_hash(db_manager, torrent_id, site_name)
        torrent_info = get_current_torrent_info(db_manager, hash_value)

        if torrent_info:
            return jsonify(
                {
                    "success": True,
                    "downloader_id": torrent_info.get("downloader_id"),
                    "save_path": torrent_info.get("save_path"),
                }
            )
        return jsonify({"success": False, "message": "未找到该种子信息"}), 404

    except Exception as e:
        logging.error(f"查询下载器信息失败: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"数据库查询失败: {str(e)}"}), 500


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
        return (
            jsonify(
                {"success": False, "message": "错误：缺少必要参数 (url, savePath, downloaderId)。"}
            ),
            400,
        )

    try:
        success, message = add_torrent_to_downloader(
            detail_page_url, save_path, downloader_id, db_manager, config_manager
        )

        # 处理发种限制状态
        if success == "LIMIT_REACHED":
            return jsonify(
                {
                    "success": False,
                    "limit_reached": True,
                    "message": message,
                    "should_stop_batch": True,
                    "code": "SEEDING_LIMIT_EXCEEDED",
                }
            )

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

        # 从数据库查询所有站点的关键信息，包括英文站点名
        cursor.execute(
            "SELECT nickname, site, cookie, passkey, migration FROM sites WHERE nickname IS NOT NULL AND nickname != ''"
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
                "site": row.get("site"),  # 添加英文站点名
                "has_cookie": bool(row.get("cookie")),
                "has_passkey": bool(row.get("passkey")),
                "is_source": migration_status in [1, 3],
                "is_target": migration_status in [2, 3],
            }
            sites_status.append(site_info)

        return jsonify(sorted(sites_status, key=lambda x: x["name"].lower()))

    except Exception as e:
        logging.error(f"获取站点状态列表失败: {e}", exc_info=True)
        return jsonify({"error": "服务器内部错误"}), 500
    finally:
        if "conn" in locals() and conn:
            if "cursor" in locals() and cursor:
                cursor.close()
            conn.close()


# 移除了与downloader_queue相关的API路由，因为现在使用同步方式


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
            "original_main_title", review_data.get("original_main_title", "")
        )
        review_data["title_components"] = updated_data.get(
            "title_components", review_data.get("title_components", [])
        )
        review_data["subtitle"] = updated_data.get("subtitle", review_data.get("subtitle", ""))
        review_data["imdb_link"] = updated_data.get("imdb_link", review_data.get("imdb_link", ""))
        review_data["intro"] = updated_data.get("intro", review_data.get("intro", {}))
        review_data["mediainfo"] = updated_data.get("mediainfo", review_data.get("mediainfo", ""))
        review_data["source_params"] = updated_data.get(
            "source_params", review_data.get("source_params", {})
        )

        # 重新提取产地信息
        full_description_text = (
            f"{review_data['intro'].get('statement', '')}\n{review_data['intro'].get('body', '')}"
        )
        origin_info = extract_origin_from_description(full_description_text)
        if origin_info and "source_params" in review_data:
            review_data["source_params"]["产地"] = origin_info

        # 重新生成预览参数
        # 这里我们需要重新构建完整的发布参数预览
        try:
            # 1. 重新解析标题组件
            title_components = review_data.get("title_components", [])
            if not title_components:
                # 传入mediainfo以便修正Blu-ray/BluRay格式
                mediainfo = review_data.get("mediainfo", "")
                title_components = upload_data_title(
                    review_data["original_main_title"], mediaInfo=mediainfo
                )

            # 2. 重新构建标题参数字典
            title_params = {
                item["key"]: item["value"] for item in title_components if item.get("value")
            }

            # 3. 如果分辨率为空，尝试从MediaInfo中提取分辨率
            resolution_from_title = title_params.get("分辨率")
            if not resolution_from_title or resolution_from_title == "N/A":
                resolution_from_mediainfo = extract_resolution_from_mediainfo(
                    review_data["mediainfo"]
                )
                if resolution_from_mediainfo:
                    # 更新标题参数中的分辨率
                    title_params["分辨率"] = resolution_from_mediainfo
                    # 同时更新title_components中的分辨率项
                    for component in title_components:
                        if component["key"] == "分辨率":
                            component["value"] = resolution_from_mediainfo
                            break
                    else:
                        # 如果没有找到分辨率项，添加一个新的
                        title_components.append(
                            {"key": "分辨率", "value": resolution_from_mediainfo}
                        )

            # 3. 重新拼接主标题
            order = [
                "主标题",
                "季集",
                "年份",
                "剧集状态",
                "发布版本",
                "分辨率",
                "片源平台",
                "媒介",
                "帧率",
                "HDR格式",
                "视频编码",
                "视频格式",
                "色深",
                "音频编码",
            ]
            title_parts = []
            for key in order:
                value = title_params.get(key)
                if value:
                    title_parts.append(
                        " ".join(map(str, value)) if isinstance(value, list) else str(value)
                    )

            raw_main_part = " ".join(filter(None, title_parts))
            main_part = re.sub(r"(?<!\d)\.(?!\d)", " ", raw_main_part)
            main_part = re.sub(r"\s+", " ", main_part).strip()
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
                f"{review_data['intro'].get('screenshots', '')}"
            )

            # 5. 重新收集标签
            source_tags = set(review_data["source_params"].get("标签") or [])
            mediainfo_tags = set(extract_tags_from_mediainfo(review_data["mediainfo"]))
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

            # 使用新的Extractor和ParameterMapper来处理参数映射
            source_site_name = context.get("source_site_name", "")

            # 创建一个模拟的HTML soup对象用于提取器
            # 由于我们已经有提取的数据，我们可以创建一个简单的soup对象
            from bs4 import BeautifulSoup

            mock_html = (
                f"<html><body><h1 id='top'>{review_data.get('title', '')}</h1></body></html>"
            )
            mock_soup = BeautifulSoup(mock_html, "html.parser")

            # 初始化提取器
            from core.extractors.extractor import Extractor, ParameterMapper

            extractor = Extractor()
            mapper = ParameterMapper()

            # 创建提取数据结构，模拟从网页提取的数据
            extracted_data = {
                "title": review_data.get("title", ""),
                "subtitle": review_data.get("subtitle", ""),
                "intro": review_data.get("intro", {}),
                "mediainfo": review_data.get("mediainfo", ""),
                "source_params": review_data.get("source_params", {}),
                "title_components": title_components,
            }

            # 使用ParameterMapper映射参数
            standardized_params = mapper.map_parameters(source_site_name, "", extracted_data)

            # 保存参数到文件用于调试
            import os

            tmp_dir = "data/tmp"
            os.makedirs(tmp_dir, exist_ok=True)

            # 保存标准化参数到文件
            with open(os.path.join(tmp_dir, "2.txt"), "w", encoding="utf-8") as f:
                f.write(f"源站点名称: {source_site_name}\n")
                f.write("最终标准化参数（使用新映射系统）:\n")
                for key, value in standardized_params.items():
                    f.write(f"{key}: {value}\n")
                # 添加调试信息
                f.write(f"\n调试信息:\n")
                f.write(f"video_codec值: {standardized_params.get('video_codec', '未找到')}\n")
                f.write(f"codec值: {standardized_params.get('codec', '未找到')}\n")

            # 用于预览显示标准化键对应的内容
            preview_video_codec = standardized_params.get("video_codec", "video.other")
            preview_audio_codec = standardized_params.get("audio_codec", "audio.other")
            preview_medium = standardized_params.get("medium", "medium.other")
            preview_resolution = standardized_params.get("resolution", "resolution.other")
            preview_team = standardized_params.get("team", "team.other")
            preview_type = standardized_params.get("type", "category.other")
            preview_source = standardized_params.get("source", "N/A")

            raw_params_for_preview = {
                "final_main_title": preview_title,
                "subtitle": review_data["subtitle"],
                "imdb_link": review_data["imdb_link"],
                "type": preview_type,
                "medium": preview_medium,
                "video_codec": preview_video_codec,
                "audio_codec": preview_audio_codec,
                "resolution": preview_resolution,
                "release_group": preview_team,
                "source": preview_source,
                "tags": list(all_tags),
            }

            # 更新 review_data 中的预览参数
            review_data["final_publish_parameters"] = final_publish_parameters
            review_data["raw_params_for_preview"] = raw_params_for_preview

            # 更新缓存中的 review_data
            MIGRATION_CACHE[task_id]["review_data"] = review_data

            return jsonify({"success": True, "data": review_data, "message": "预览数据更新成功"})
        except Exception as e:
            logging.error(f"重新生成预览数据时发生错误: {e}", exc_info=True)
            return jsonify({"success": False, "message": f"重新生成预览数据时发生错误: {e}"}), 500

    except Exception as e:
        logging.error(f"update_preview_data 发生意外错误: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"服务器内部错误: {e}"}), 500


# ===================================================================
#                    批量获取种子数据 API
# ===================================================================

# 存储批量任务的进度信息
BATCH_FETCH_TASKS = {}


@migrate_bp.route("/migrate/get_aggregated_torrents", methods=["POST"])
def get_aggregated_torrents():
    """获取按名称聚合的种子列表（用于批量获取数据）"""
    try:
        db_manager = migrate_bp.db_manager
        data = request.json

        # 获取分页参数
        page = data.get("page", 1)
        page_size = data.get("pageSize", 50)

        # 获取筛选条件
        name_search = data.get("nameSearch", "").lower()
        path_filters = data.get("pathFilters", [])
        state_filters = data.get("stateFilters", [])
        downloader_filters = data.get("downloaderFilters", [])

        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        # 获取所有站点配置信息
        cursor.execute("SELECT nickname, migration FROM sites")
        site_configs = {row["nickname"]: dict(row) for row in cursor.fetchall()}

        # 查询所有种子数据
        if db_manager.db_type == "postgresql":
            cursor.execute(
                'SELECT hash, name, save_path, size, progress, state, sites, "group", details, downloader_id FROM torrents WHERE state != %s',
                ("不存在",),
            )
        else:
            cursor.execute(
                "SELECT hash, name, save_path, size, progress, state, sites, `group`, details, downloader_id FROM torrents WHERE state != %s",
                ("不存在",),
            )
        torrents_raw = [dict(row) for row in cursor.fetchall()]

        # 查询 seed_parameters 表中已存在的种子名称
        # 去除 .torrent 后缀进行匹配
        cursor.execute(
            "SELECT DISTINCT name FROM seed_parameters WHERE name IS NOT NULL AND name != ''"
        )
        existing_seed_names = set(row["name"] for row in cursor.fetchall())
        logging.info(f"seed_parameters 表中已有 {len(existing_seed_names)} 个种子记录")

        # 按名称聚合种子
        from collections import defaultdict

        agg_torrents = defaultdict(
            lambda: {
                "name": "",
                "save_path": "",
                "size": 0,
                "progress": 0,
                "state": set(),
                "sites": defaultdict(dict),
                "downloader_ids": [],
            }
        )

        for t in torrents_raw:
            torrent_key = t["name"]
            agg = agg_torrents[torrent_key]
            if not agg["name"]:
                agg.update(
                    {
                        "name": t["name"],
                        "save_path": t.get("save_path", ""),
                        "size": t.get("size", 0),
                    }
                )
            downloader_id = t.get("downloader_id")
            if downloader_id and downloader_id not in agg["downloader_ids"]:
                agg["downloader_ids"].append(downloader_id)
            agg["progress"] = max(agg.get("progress", 0), t.get("progress", 0))
            agg["state"].add(t.get("state", "N/A"))
            if t.get("sites"):
                site_name = t.get("sites")
                agg["sites"][site_name]["comment"] = t.get("details")
                agg["sites"][site_name]["state"] = t.get("state", "N/A")
                agg["sites"][site_name]["migration"] = site_configs.get(site_name, {}).get(
                    "migration", 0
                )

        # 转换为列表并应用筛选
        filtered_list = []
        for name, data in agg_torrents.items():
            # 排除已在 seed_parameters 表中存在的种子
            # 去除 .torrent 后缀进行匹配
            name_without_ext = name
            if name_without_ext.lower().endswith(".torrent"):
                name_without_ext = name_without_ext[:-8]

            if name_without_ext in existing_seed_names:
                logging.debug(f"排除已存在的种子: {name}")
                continue

            # 名称搜索筛选
            if name_search and name_search not in name.lower():
                continue

            # 路径筛选
            if path_filters and data["save_path"] not in path_filters:
                continue

            # 状态筛选
            state_str = ", ".join(sorted(list(data["state"])))
            if state_filters and state_str not in state_filters:
                continue

            # 下载器筛选
            if downloader_filters:
                if not any(did in downloader_filters for did in data.get("downloader_ids", [])):
                    continue

            data.update({"state": state_str, "sites": dict(data["sites"])})  # 转换为普通字典
            filtered_list.append(data)

        # 计算总数
        total = len(filtered_list)

        # 应用分页
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_list = filtered_list[start_idx:end_idx]

        print(
            f"分页参数: page={page}, page_size={page_size}, total={total}, start_idx={start_idx}, end_idx={end_idx}, paginated_count={len(paginated_list)}"
        )

        cursor.close()
        conn.close()

        return jsonify({"success": True, "data": paginated_list, "total": total})

    except Exception as e:
        logging.error(f"get_aggregated_torrents 发生错误: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"服务器内部错误: {str(e)}"}), 500


@migrate_bp.route("/migrate/batch_fetch_seed_data", methods=["POST"])
def batch_fetch_seed_data():
    """批量获取种子数据并存储到数据库"""
    try:
        db_manager = migrate_bp.db_manager
        config_manager = migrate_bp.config_manager
        data = request.json

        torrent_names = data.get("torrentNames", [])
        # 从配置中读取源站点优先级
        config = config_manager.get()
        source_sites_priority = config.get("source_priority", [])

        if not torrent_names:
            return jsonify({"success": False, "message": "错误：种子名称列表不能为空"}), 400

        if not source_sites_priority:
            return (
                jsonify({"success": False, "message": "错误：请先在设置中配置源站点优先级"}),
                400,
            )

        # 生成任务ID
        task_id = str(uuid.uuid4())

        # 初始化任务进度
        BATCH_FETCH_TASKS[task_id] = {
            "total": len(torrent_names),
            "processed": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "isRunning": True,
            "results": [],
        }

        # 在后台线程中执行批量获取
        from threading import Thread

        thread = Thread(
            target=_process_batch_fetch,
            args=(task_id, torrent_names, source_sites_priority, db_manager),
        )
        thread.daemon = True
        thread.start()

        return jsonify({"success": True, "task_id": task_id, "message": "批量获取任务已启动"})

    except Exception as e:
        logging.error(f"batch_fetch_seed_data 发生错误: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"服务器内部错误: {str(e)}"}), 500


def _process_batch_fetch(task_id, torrent_names, source_sites_priority, db_manager):
    """后台处理批量获取任务"""
    import time

    # 记录每个站点的最后请求时间，用于控制请求间隔
    site_last_request_time = {}
    # 默认请求间隔（秒）
    REQUEST_INTERVAL = 5

    try:
        for torrent_name in torrent_names:
            if task_id not in BATCH_FETCH_TASKS:
                logging.warning(f"任务 {task_id} 已被取消")
                break

            try:
                # 查询该名称的所有种子记录
                conn = db_manager._get_connection()
                cursor = db_manager._get_cursor(conn)

                if db_manager.db_type == "sqlite":
                    cursor.execute(
                        "SELECT hash, name, save_path, size, sites, details, downloader_id FROM torrents WHERE name = ? AND state != ?",
                        (torrent_name, "不存在"),
                    )
                else:  # postgresql or mysql
                    cursor.execute(
                        "SELECT hash, name, save_path, size, sites, details, downloader_id FROM torrents WHERE name = %s AND state != %s",
                        (torrent_name, "不存在"),
                    )

                torrents = [dict(row) for row in cursor.fetchall()]
                cursor.close()
                conn.close()

                if not torrents:
                    BATCH_FETCH_TASKS[task_id]["results"].append(
                        {"name": torrent_name, "status": "skipped", "reason": "未找到种子记录"}
                    )
                    BATCH_FETCH_TASKS[task_id]["skipped"] += 1
                    BATCH_FETCH_TASKS[task_id]["processed"] += 1
                    continue

                # 按优先级查找可用的源站点
                source_found = None
                for priority_site in source_sites_priority:
                    # 获取站点信息
                    source_info = db_manager.get_site_by_nickname(priority_site)
                    if not source_info or not source_info.get("cookie"):
                        continue

                    # 检查该站点的migration状态
                    if source_info.get("migration", 0) not in [1, 3]:
                        continue

                    # 查找该站点的种子记录
                    for torrent in torrents:
                        if torrent.get("sites") == priority_site:
                            # 提取种子ID
                            comment = torrent.get("details", "")
                            torrent_id = None

                            if comment:
                                # 尝试从comment中提取ID
                                import re

                                id_match = re.search(r"id=(\d+)", comment)
                                if id_match:
                                    torrent_id = id_match.group(1)
                                elif re.match(r"^\d+$", comment.strip()):
                                    torrent_id = comment.strip()

                            if torrent_id:
                                source_found = {
                                    "site": priority_site,
                                    "site_info": source_info,
                                    "torrent_id": torrent_id,
                                    "torrent": torrent,
                                }
                                break

                    if source_found:
                        break

                # 第二阶段：如果优先级站点都没有找到，使用 IYUU 查询
                if not source_found:
                    try:
                        # 导入 IYUU 线程
                        from core.iyuu import iyuu_thread

                        if iyuu_thread and iyuu_thread.is_alive():
                            # 获取种子大小（使用第一个种子的大小，因为同名种子大小应该相同）
                            torrent_size = 0
                            if torrents:
                                torrent_size = torrents[0].get("size", 0)

                            logging.info(
                                f"优先级站点未找到，尝试使用 IYUU 查询: {torrent_name} (大小: {torrent_size} 字节)"
                            )

                            # 执行 IYUU 查询
                            result_stats = iyuu_thread._process_single_torrent(
                                torrent_name, torrent_size
                            )

                            if result_stats and result_stats.get("total_found", 0) > 0:
                                logging.info(
                                    f"IYUU 查询找到 {result_stats['total_found']} 条记录，重新查询数据库"
                                )

                                # 重新查询数据库，获取更新后的种子记录
                                conn = db_manager._get_connection()
                                cursor = db_manager._get_cursor(conn)

                                if db_manager.db_type == "sqlite":
                                    cursor.execute(
                                        "SELECT hash, name, save_path, sites, details, downloader_id FROM torrents WHERE name = ? AND state != ?",
                                        (torrent_name, "不存在"),
                                    )
                                else:  # postgresql or mysql
                                    cursor.execute(
                                        "SELECT hash, name, save_path, sites, details, downloader_id FROM torrents WHERE name = %s AND state != %s",
                                        (torrent_name, "不存在"),
                                    )

                                updated_torrents = [dict(row) for row in cursor.fetchall()]
                                cursor.close()
                                conn.close()

                                if updated_torrents:
                                    torrents = updated_torrents
                                    logging.info(f"IYUU 查询后重新检查优先级站点")

                                    # 重新按优先级查找可用的源站点
                                    for priority_site in source_sites_priority:
                                        # 获取站点信息
                                        source_info = db_manager.get_site_by_nickname(
                                            priority_site
                                        )
                                        if not source_info or not source_info.get("cookie"):
                                            continue

                                        # 检查该站点的migration状态
                                        if source_info.get("migration", 0) not in [1, 3]:
                                            continue

                                        # 查找该站点的种子记录（在更新后的torrents中）
                                        for torrent in torrents:
                                            if torrent.get("sites") == priority_site:
                                                # 提取种子ID
                                                comment = torrent.get("details", "")
                                                torrent_id = None

                                                if comment:
                                                    # 尝试从comment中提取ID
                                                    import re

                                                    id_match = re.search(r"id=(\d+)", comment)
                                                    if id_match:
                                                        torrent_id = id_match.group(1)
                                                    elif re.match(r"^\d+$", comment.strip()):
                                                        torrent_id = comment.strip()

                                                if torrent_id:
                                                    source_found = {
                                                        "site": priority_site,
                                                        "site_info": source_info,
                                                        "torrent_id": torrent_id,
                                                        "torrent": torrent,
                                                    }
                                                    logging.info(
                                                        f"IYUU 查询后在优先级站点中找到: {priority_site}"
                                                    )
                                                    break

                                        if source_found:
                                            break
                                else:
                                    logging.info(f"IYUU 查询未找到新的种子记录")
                        else:
                            logging.warning("IYUU 线程未运行，跳过 IYUU 查询")
                    except Exception as e:
                        logging.error(f"IYUU 查询失败: {e}", exc_info=True)

                # 第三阶段：如果 IYUU 查询后还是没有找到，在其他存在的源站点中查找
                if not source_found:
                    # 获取所有已存在的站点名称（排除已经在优先级列表中的）
                    existing_sites = set()
                    for torrent in torrents:
                        site_name = torrent.get("sites")
                        if site_name and site_name not in source_sites_priority:
                            existing_sites.add(site_name)

                    # 在这些其他站点中查找可用的源站点
                    for site_name in existing_sites:
                        # 获取站点信息
                        source_info = db_manager.get_site_by_nickname(site_name)
                        if not source_info or not source_info.get("cookie"):
                            continue
                        # 检查该站点的migration状态
                        if source_info.get("migration", 0) not in [1, 3]:
                            continue
                        # 查找该站点的种子记录
                        for torrent in torrents:
                            if torrent.get("sites") == site_name:
                                # 提取种子ID
                                comment = torrent.get("details", "")
                                torrent_id = None
                                if comment:
                                    # 尝试从comment中提取ID
                                    import re

                                    id_match = re.search(r"id=(\d+)", comment)
                                    if id_match:
                                        torrent_id = id_match.group(1)
                                    elif re.match(r"^\d+$", comment.strip()):
                                        torrent_id = comment.strip()
                                if torrent_id:
                                    source_found = {
                                        "site": site_name,
                                        "site_info": source_info,
                                        "torrent_id": torrent_id,
                                        "torrent": torrent,
                                    }
                                    break
                        if source_found:
                            break

                # 新增：自动重试和站点切换逻辑
                # 实现站点自动重试和智能切换功能
                max_retry_per_site = 2  # 每个站点最多重试2次
                fetch_success = False
                final_source = None
                attempted_sites_details = []

                # 排除"我堡"和"OurBits"站点
                excluded_sites = {"我堡", "OurBits"}

                # 构建所有可用站点列表（按优先级排序）
                all_available_sites = []

                # 1. 首先按配置的优先级顺序添加优先级站点
                for priority_site in source_sites_priority:
                    # 跳过被排除的站点
                    if priority_site in excluded_sites:
                        continue

                    source_info = db_manager.get_site_by_nickname(priority_site)
                    if not source_info or not source_info.get("cookie"):
                        continue
                    if source_info.get("migration", 0) not in [1, 3]:
                        continue

                    # 查找该优先级站点的种子记录
                    for torrent in torrents:
                        if torrent.get("sites") == priority_site:
                            comment = torrent.get("details", "")
                            torrent_id = None
                            if comment:
                                import re

                                id_match = re.search(r"id=(\d+)", comment)
                                if id_match:
                                    torrent_id = id_match.group(1)
                                elif re.match(r"^\d+$", comment.strip()):
                                    torrent_id = comment.strip()

                            if torrent_id:
                                all_available_sites.append(
                                    {
                                        "site_name": priority_site,
                                        "site_info": source_info,
                                        "torrent_id": torrent_id,
                                        "torrent": torrent,
                                        "priority": "configured",
                                    }
                                )
                                logging.info(f"✓ 添加优先级站点: {priority_site}")
                                break

                # 2. 然后添加其他可用站点作为后备
                # 获取所有在torrents中有记录的站点（排除已在优先级中的）
                priority_site_names = set(source_sites_priority)
                site_name_map = {}
                for torrent in torrents:
                    site_name = torrent.get("sites")
                    # 跳过被排除的站点
                    if site_name in excluded_sites:
                        continue
                    if site_name and site_name not in priority_site_names:
                        site_name_map[site_name] = torrent

                # 按迁移状态排序后备站点
                sorted_sites = []
                for site_name, torrent in site_name_map.items():
                    # 跳过被排除的站点
                    if site_name in excluded_sites:
                        continue

                    source_info = db_manager.get_site_by_nickname(site_name)
                    if source_info and source_info.get("cookie"):
                        migration_status = source_info.get("migration", 0)
                        # 优先级：可作为源(1,3) > 只作为目标(2) > 只配置不迁移(0)
                        priority = (
                            2 if migration_status in [1, 3] else 1 if migration_status == 2 else 0
                        )
                        sorted_sites.append((site_name, torrent, source_info, priority))

                # 按优先级降序排序
                sorted_sites.sort(key=lambda x: x[3], reverse=True)

                # 3. 将后备站点添加到可用站点列表
                for site_name, torrent, source_info, _ in sorted_sites:
                    # 提取种子ID
                    comment = torrent.get("details", "")
                    torrent_id = None
                    if comment:
                        import re

                        id_match = re.search(r"id=(\d+)", comment)
                        if id_match:
                            torrent_id = id_match.group(1)
                        elif re.match(r"^\d+$", comment.strip()):
                            torrent_id = comment.strip()

                    if torrent_id:
                        all_available_sites.append(
                            {
                                "site_name": site_name,
                                "site_info": source_info,
                                "torrent_id": torrent_id,
                                "torrent": torrent,
                                "priority": "fallback",
                            }
                        )
                        logging.info(f"  添加后备站点: {site_name}")

                logging.info(
                    f"为 {torrent_name} 构建可用站点列表完成，共 {len(all_available_sites)} 个站点"
                )

                # 遍历所有可用站点进行尝试
                for site_attempt in all_available_sites:
                    for attempt in range(1, max_retry_per_site + 1):
                        if fetch_success:
                            break

                        try:
                            site_name = site_attempt["site_name"]

                            # 检查站点请求间隔（批量模式下跳过）
                            if not os.getenv("BATCH_MODE") == "true":
                                if site_name in site_last_request_time:
                                    elapsed = time.time() - site_last_request_time[site_name]
                                    if elapsed < REQUEST_INTERVAL:
                                        wait_time = REQUEST_INTERVAL - elapsed
                                        logging.info(
                                            f"⏰ 站点 {site_name} 请求间隔控制，等待 {wait_time:.1f} 秒"
                                        )
                                        time.sleep(wait_time)

                            site_last_request_time[site_name] = time.time()

                            if attempt > 1:
                                logging.info(f"🔄 站点 {site_name} 第{attempt}次重试")
                            else:
                                priority_indicator = (
                                    "⭐" if site_attempt.get("priority") == "configured" else "📋"
                                )
                                logging.info(
                                    f"{priority_indicator} 正在从站点 {site_name} 获取 {torrent_name}"
                                )

                            # 初始化TorrentMigrator
                            migrator = TorrentMigrator(
                                source_site_info=site_attempt["site_info"],
                                target_site_info=None,
                                search_term=site_attempt["torrent_id"],
                                save_path=site_attempt["torrent"].get("save_path", ""),
                                torrent_name=torrent_name,
                                downloader_id=site_attempt["torrent"].get("downloader_id"),
                                config_manager=config_manager,
                                db_manager=db_manager,
                            )

                            # 尝试获取数据
                            result = migrator.prepare_review_data()

                            if "review_data" in result:
                                # 成功获取
                                final_source = site_attempt
                                fetch_success = True
                                logging.info(f"✅ 从站点 {site_name} 成功获取 {torrent_name}")
                                break
                            else:
                                # 获取失败，记录错误
                                error_detail = result.get("logs", "未知错误")

                                # 记录尝试过的站点
                                if site_name not in attempted_sites_details:
                                    attempted_sites_details.append(site_name)

                                # 判断是否需要重试
                                should_retry = False
                                if attempt < max_retry_per_site:
                                    # 对于网络相关错误和种子链接查找错误，使用指数退避重试
                                    if (
                                        "连接" in error_detail.lower()
                                        or "timeout" in error_detail.lower()
                                        or "网络" in error_detail.lower()
                                        or "placeholder" in error_detail.lower()
                                        or "429" in error_detail
                                        or "502" in error_detail
                                        or "503" in error_detail
                                        or "504" in error_detail
                                        or "未找到种子下载链接" in error_detail
                                    ):  # 新增：种子下载链接未找到错误

                                        wait_time = REQUEST_INTERVAL * (
                                            2 ** (attempt - 1)
                                        )  # 指数退避
                                        logging.warning(
                                            f"⚠️ 站点 {site_name} 第{attempt}次失败 ({error_detail})，{wait_time}秒后重试"
                                        )
                                        time.sleep(wait_time)
                                        should_retry = True
                                    else:
                                        logging.warning(
                                            f"❌ 站点 {site_name} 获取失败（非重试错误）: {error_detail}"
                                        )

                                if not should_retry:
                                    logging.info(f"⏭️ 站点 {site_name} 获取失败，尝试下一个站点")
                                    break

                        except Exception as attempt_error:
                            error_msg = str(attempt_error)
                            logging.error(
                                f"站点 {site_attempt['site_name']} 第{attempt}次尝试异常: {error_msg}"
                            )

                            # 记录尝试过的站点
                            if site_attempt["site_name"] not in attempted_sites_details:
                                attempted_sites_details.append(site_attempt["site_name"])

                            # 对于网络异常，如果还没到重试上限则重试
                            if attempt < max_retry_per_site and (
                                "连接" in error_msg.lower() or "timeout" in error_msg.lower()
                            ):
                                wait_time = REQUEST_INTERVAL * (2 ** (attempt - 1))
                                logging.warning(
                                    f"⚠️ 站点 {site_attempt['site_name']} 第{attempt}次异常，{wait_time}秒后重试"
                                )
                                time.sleep(wait_time)
                            else:
                                logging.info(
                                    f"⏭️ 站点 {site_attempt['site_name']} 异常，尝试下一个站点"
                                )
                                break

                    if fetch_success:
                        break  # 成功获取，退出站点循环

                # 处理最终结果
                if fetch_success and final_source:
                    BATCH_FETCH_TASKS[task_id]["results"].append(
                        {
                            "name": torrent_name,
                            "status": "success",
                            "source_site": final_source["site_name"],
                            "attempted_sites": len(attempted_sites_details),
                            "retries": max_retry_per_site,
                        }
                    )
                    BATCH_FETCH_TASKS[task_id]["success"] += 1
                    logging.info(
                        f"📊 {torrent_name} 批量获取成功 (尝试了{len(attempted_sites_details)}个站点，来自{final_source['site_name']})"
                    )
                else:
                    failure_reason = f"在{len(attempted_sites_details)}个站点全部尝试失败"
                    if attempted_sites_details:
                        failure_reason += f" (尝试站点: {', '.join(attempted_sites_details)})"

                    BATCH_FETCH_TASKS[task_id]["results"].append(
                        {
                            "name": torrent_name,
                            "status": "failed",
                            "reason": failure_reason,
                            "attempted_sites": len(attempted_sites_details),
                        }
                    )
                    BATCH_FETCH_TASKS[task_id]["failed"] += 1
                    logging.error(f"❌ {torrent_name} 批量获取失败: {failure_reason}")

                BATCH_FETCH_TASKS[task_id]["processed"] += 1

            except Exception as e:
                BATCH_FETCH_TASKS[task_id]["results"].append(
                    {"name": torrent_name, "status": "failed", "reason": str(e)}
                )
                BATCH_FETCH_TASKS[task_id]["failed"] += 1
                BATCH_FETCH_TASKS[task_id]["processed"] += 1
                logging.error(f"处理种子 {torrent_name} 时发生错误: {e}")

        # 标记任务完成
        if task_id in BATCH_FETCH_TASKS:
            BATCH_FETCH_TASKS[task_id]["isRunning"] = False
            logging.info(f"批量获取任务 {task_id} 完成")

    except Exception as e:
        logging.error(f"批量获取任务 {task_id} 发生严重错误: {e}", exc_info=True)
        if task_id in BATCH_FETCH_TASKS:
            BATCH_FETCH_TASKS[task_id]["isRunning"] = False


@migrate_bp.route("/migrate/batch_fetch_progress", methods=["GET"])
def batch_fetch_progress():
    """获取批量获取任务的进度"""
    try:
        task_id = request.args.get("task_id")

        if not task_id:
            return jsonify({"success": False, "message": "缺少task_id参数"}), 400

        if task_id not in BATCH_FETCH_TASKS:
            return jsonify({"success": False, "message": "任务不存在或已过期"}), 404

        progress = BATCH_FETCH_TASKS[task_id]

        return jsonify({"success": True, "progress": progress})

    except Exception as e:
        logging.error(f"batch_fetch_progress 发生错误: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"服务器内部错误: {str(e)}"}), 500


# ===================================================================
#                    实时日志流 API (SSE)
# ===================================================================


@migrate_bp.route("/migrate/logs/stream/<task_id>", methods=["GET"])
def stream_logs(task_id):
    """实时推送任务日志流 (Server-Sent Events)

    前端通过 EventSource 连接此端点，接收实时日志事件
    每个事件包含：step（步骤名）、message（消息）、status（状态）等信息
    """

    def generate():
        """生成 SSE 事件流"""
        try:
            # 获取或创建日志流
            stream = log_streamer.get_stream(task_id)
            if not stream:
                # 如果流不存在，创建一个新的
                stream = log_streamer.create_stream(task_id)
                logging.info(f"为任务 {task_id} 创建新的日志流")

            # 发送连接成功消息
            yield f"data: {json.dumps({'type': 'connected', 'task_id': task_id})}\n\n"

            # 持续从队列读取日志事件
            while True:
                try:
                    # 等待新的日志事件（超时1秒）
                    event = stream.get(timeout=1.0)

                    # None 表示流结束
                    if event is None:
                        yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                        logging.info(f"任务 {task_id} 日志流结束")
                        break

                    # 发送日志事件
                    event["type"] = "log"
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

                except Exception as queue_error:
                    # 队列超时或其他错误，发送心跳保持连接
                    if "Empty" in str(type(queue_error).__name__):
                        # 发送心跳
                        yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                    else:
                        logging.error(f"队列读取错误: {queue_error}")
                        break

        except Exception as e:
            logging.error(f"SSE流生成错误: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    # 返回 SSE 响应
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
            "Connection": "keep-alive",
        },
    )


@migrate_bp.route("/migrate/bdinfo_status/<seed_id>")
def get_bdinfo_status(seed_id):
    """获取 BDInfo 处理状态"""
    try:
        from core.bdinfo.bdinfo_manager import get_bdinfo_manager

        # 从数据库查询基本信息
        conn = migrate_bp.db_manager._get_connection()
        cursor = migrate_bp.db_manager._get_cursor(conn)

        # seed_id 格式为 "hash_torrentId_siteName"，需要解析
        if "_" in seed_id:
            # 解析复合 seed_id
            parts = seed_id.split("_")
            if len(parts) >= 3:
                # 最后一个部分是 site_name，中间是 torrent_id，前面是 hash
                site_name_val = parts[-1]
                torrent_id_val = parts[-2]
                hash_val = "_".join(parts[:-2])  # hash 可能包含下划线

                # 使用复合主键查询
                if migrate_bp.db_manager.db_type == "sqlite":
                    cursor.execute(
                        """
                        SELECT mediainfo_status, bdinfo_task_id, bdinfo_started_at, 
                               bdinfo_completed_at, mediainfo, bdinfo_error 
                        FROM seed_parameters 
                        WHERE hash = ? AND torrent_id = ? AND site_name = ?
                    """,
                        (hash_val, torrent_id_val, site_name_val),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT mediainfo_status, bdinfo_task_id, bdinfo_started_at, 
                               bdinfo_completed_at, mediainfo, bdinfo_error 
                        FROM seed_parameters 
                        WHERE hash = %s AND torrent_id = %s AND site_name = %s
                    """,
                        (hash_val, torrent_id_val, site_name_val),
                    )
            else:
                # 如果格式不对，尝试使用 CONCAT 查询
                if migrate_bp.db_manager.db_type == "sqlite":
                    cursor.execute(
                        """
                        SELECT mediainfo_status, bdinfo_task_id, bdinfo_started_at, 
                               bdinfo_completed_at, mediainfo, bdinfo_error 
                        FROM seed_parameters 
                        WHERE hash || '_' || torrent_id || '_' || site_name = ?
                    """,
                        (seed_id,),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT mediainfo_status, bdinfo_task_id, bdinfo_started_at, 
                               bdinfo_completed_at, mediainfo, bdinfo_error 
                        FROM seed_parameters 
                        WHERE CONCAT(hash, '_', torrent_id, '_', site_name) = %s
                    """,
                        (seed_id,),
                    )
        else:
            # 如果没有下划线，说明格式不对，返回错误
            return jsonify({"error": f"无效的种子ID格式: {seed_id}"}), 400

        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if not result:
            return jsonify({"error": "种子数据不存在"}), 404

        # 如果有任务ID，从任务管理器获取详细状态
        task_status = None
        progress_info = None
        if result["bdinfo_task_id"]:
            bdinfo_manager = get_bdinfo_manager()
            task_status = bdinfo_manager.get_task_status(result["bdinfo_task_id"])

            # 如果任务正在处理中，获取进度信息
            if task_status and task_status.get("status") in ["processing_bdinfo", "processing"]:
                progress_info = {
                    "progress_percent": task_status.get("progress_percent", 0.0),
                    "current_file": task_status.get("current_file", ""),
                    "elapsed_time": task_status.get("elapsed_time", ""),
                    "remaining_time": task_status.get("remaining_time", ""),
                }

        # 判断是否为BDInfo内容
        is_bdinfo = False
        if result["mediainfo"]:
            from utils.mediainfo import validate_media_info_format

            _, is_bdinfo, _, _, _, _ = validate_media_info_format(result["mediainfo"])

        response_data = {
            "seed_id": seed_id,
            "mediainfo_status": result["mediainfo_status"],
            "bdinfo_task_id": result["bdinfo_task_id"],
            "bdinfo_started_at": result["bdinfo_started_at"],
            "bdinfo_completed_at": result["bdinfo_completed_at"],
            "bdinfo_error": result["bdinfo_error"],
            "mediainfo": (
                result["mediainfo"] if result["mediainfo_status"] == "completed" else None
            ),
            "is_bdinfo": is_bdinfo,
            "task_status": task_status,
        }

        # 添加进度信息
        if progress_info:
            response_data["progress_info"] = progress_info

        return jsonify(response_data)

    except Exception as e:
        logging.error(f"获取 BDInfo 状态失败: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@migrate_bp.route("/migrate/refresh_bdinfo/<seed_id>", methods=["POST"])
def refresh_bdinfo(seed_id):
    """手动触发 BDInfo 重新获取"""
    try:
        db_manager = migrate_bp.db_manager
        hash_value = None

        if "_" in seed_id:
            parts = seed_id.split("_")
            if len(parts) >= 3:
                hash_value = "_".join(parts[:-2])
        else:
            try:
                conn = db_manager._get_connection()
                cursor = db_manager._get_cursor(conn)
                ph = db_manager.get_placeholder()
                cursor.execute(f"SELECT hash FROM seed_parameters WHERE id = {ph}", (seed_id,))
                row = cursor.fetchone()
                cursor.close()
                conn.close()
                if row:
                    hash_value = row["hash"] if isinstance(row, dict) else row[0]
            except Exception as e:
                logging.warning(f"通过id查询hash失败: {e}")

        torrent_info = get_current_torrent_info(db_manager, hash_value)
        if not torrent_info or not torrent_info.get("save_path"):
            return jsonify({"error": "无法获取保存路径"}), 404

        # 调用刷新函数
        from utils.mediainfo import refresh_bdinfo_for_seed

        refresh_result = refresh_bdinfo_for_seed(seed_id, torrent_info["save_path"], priority=1)

        if refresh_result["success"]:
            return jsonify(refresh_result)
        else:
            return jsonify(refresh_result), 500

    except Exception as e:
        logging.error(f"刷新 BDInfo 失败: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@migrate_bp.route("/migrate/bdinfo_tasks")
def get_bdinfo_tasks():
    """获取所有 BDInfo 任务状态（管理员接口）"""
    try:
        from core.bdinfo.bdinfo_manager import get_bdinfo_manager

        bdinfo_manager = get_bdinfo_manager()
        tasks = bdinfo_manager.get_all_tasks()
        stats = bdinfo_manager.get_stats()

        return jsonify({"tasks": tasks, "stats": stats})

    except Exception as e:
        logging.error(f"获取 BDInfo 任务列表失败: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@migrate_bp.route("/migrate/refresh_mediainfo_async", methods=["POST"])
def refresh_mediainfo_async():
    """异步版本的 MediaInfo 刷新接口"""
    try:
        data = request.json
        current_mediainfo = data.get("current_mediainfo", "")
        seed_id = data.get("seed_id")
        save_path = data.get("save_path")
        content_name = data.get("content_name")
        downloader_id = data.get("downloader_id")
        torrent_name = data.get("torrent_name")
        force_refresh = data.get("force_refresh", True)
        priority = data.get("priority", 1)  # 默认高优先级

        if not seed_id or not save_path or seed_id == "" or seed_id == None:
            return (
                jsonify({"success": False, "message": "缺少必要参数: seed_id 或 save_path"}),
                400,
            )

        # 调用异步版本的 MediaInfo 处理函数
        from utils.mediainfo import upload_data_mediaInfo_async

        # 解析 seed_id 获取复合主键组件
        hash_value = torrent_id = site_name = None
        if "_" in seed_id:
            parts = seed_id.split("_")
            if len(parts) >= 3:
                site_name = parts[-1]
                torrent_id = parts[-2]
                hash_value = "_".join(parts[:-2])

        # 获取站点中文名（如果需要的话）
        nickname = data.get("nickname")  # 从请求中获取站点中文名

        new_mediainfo, is_mediainfo, is_bdinfo, bdinfo_info = upload_data_mediaInfo_async(
            mediaInfo=current_mediainfo,
            save_path=save_path,
            seed_id=seed_id,
            content_name=content_name,
            downloader_id=downloader_id,
            torrent_name=torrent_name,
            force_refresh=force_refresh,
            priority=priority,
            # 新增参数：预写入所需的基本信息
            hash_value=hash_value,
            torrent_id=torrent_id,
            site_name=site_name,
            nickname=nickname,
        )

        # 即使 MediaInfo 提取失败，如果 BDInfo 任务已添加，也返回成功
        if bdinfo_info["bdinfo_status"] == "processing" and bdinfo_info["bdinfo_task_id"]:
            response_data = {
                "success": True,
                "mediainfo": new_mediainfo or "",
                "is_mediainfo": is_mediainfo,
                "is_bdinfo": is_bdinfo,
                "bdinfo_async": bdinfo_info,
                "message": "BDInfo 正在后台处理中",
            }
            return jsonify(response_data), 200
        elif new_mediainfo:
            response_data = {
                "success": True,
                "mediainfo": new_mediainfo,
                "is_mediainfo": is_mediainfo,
                "is_bdinfo": is_bdinfo,
                "bdinfo_async": bdinfo_info,
                "message": "MediaInfo 更新完成",
            }
            return jsonify(response_data), 200
        else:
            return jsonify({"success": False, "message": "MediaInfo 提取失败"}), 500

    except Exception as e:
        logging.error(f"异步 MediaInfo 刷新失败: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"服务器内部错误: {str(e)}"}), 500


@migrate_bp.route("/migrate/bdinfo_records", methods=["GET"])
def get_bdinfo_records():
    """获取BDInfo处理记录"""
    try:
        # 获取查询参数
        status_filter = request.args.get("status_filter", "")
        page = int(request.args.get("page", 1))
        page_size = int(request.args.get("pageSize", 20))

        # 构建查询条件
        where_conditions = ["bdinfo_task_id IS NOT NULL"]
        params = []

        # 添加状态筛选
        if status_filter:
            if status_filter == "processing":
                where_conditions.append("mediainfo_status IN ('processing_bdinfo', 'processing')")
            elif status_filter == "completed":
                where_conditions.append("mediainfo_status = 'completed'")
            elif status_filter == "failed":
                where_conditions.append(
                    "(mediainfo_status = 'failed' OR bdinfo_error IS NOT NULL)"
                )

        where_clause = " AND ".join(where_conditions)

        # 获取数据库管理器
        db_manager = migrate_bp.db_manager
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        # 获取总数
        count_sql = f"SELECT COUNT(*) as total FROM seed_parameters WHERE {where_clause}"
        cursor.execute(count_sql, params)
        total = cursor.fetchone()["total"]

        # 计算偏移量
        offset = (page - 1) * page_size

        # 获取记录
        if db_manager.db_type == "sqlite":
            records_sql = f"""
                SELECT 
                    sp.hash || '_' || sp.torrent_id || '_' || sp.site_name as seed_id,
                    sp.title,
                    sp.site_name,
                    COALESCE(s.nickname, sp.site_name) as nickname,
                    sp.mediainfo_status,
                    sp.bdinfo_task_id,
                    sp.bdinfo_started_at,
                    sp.bdinfo_completed_at,
                    sp.bdinfo_error,
                    sp.mediainfo,
                    sp.updated_at
                FROM seed_parameters sp
                LEFT JOIN sites s ON sp.site_name = s.site
                WHERE {where_clause}
                ORDER BY sp.bdinfo_started_at DESC
                LIMIT ? OFFSET ?
            """
            params.extend([page_size, offset])
        else:  # postgresql or mysql
            records_sql = f"""
                SELECT 
                    CONCAT(sp.hash, '_', sp.torrent_id, '_', sp.site_name) as seed_id,
                    sp.title,
                    sp.site_name,
                    COALESCE(s.nickname, sp.site_name) as nickname,
                    sp.mediainfo_status,
                    sp.bdinfo_task_id,
                    sp.bdinfo_started_at,
                    sp.bdinfo_completed_at,
                    sp.bdinfo_error,
                    sp.mediainfo,
                    sp.updated_at
                FROM seed_parameters sp
                LEFT JOIN sites s ON sp.site_name = s.site
                WHERE {where_clause}
                ORDER BY sp.bdinfo_started_at DESC
                LIMIT %s OFFSET %s
            """
            params.extend([page_size, offset])

        cursor.execute(records_sql, params)
        records = []

        for row in cursor.fetchall():
            # 判断是否为BDInfo内容
            is_bdinfo = False
            if row["mediainfo"]:
                from utils.mediainfo import validate_media_info_format

                _, is_bdinfo, _, _, _, _ = validate_media_info_format(row["mediainfo"])

            records.append(
                {
                    "seed_id": row["seed_id"],
                    "title": row["title"] or "未知标题",
                    "site_name": row["site_name"] or "未知站点",
                    "nickname": row["nickname"] or row["site_name"] or "未知站点",
                    "mediainfo_status": row["mediainfo_status"] or "unknown",
                    "bdinfo_task_id": row["bdinfo_task_id"],
                    "bdinfo_started_at": row["bdinfo_started_at"],
                    "bdinfo_completed_at": row["bdinfo_completed_at"],
                    "bdinfo_error": row["bdinfo_error"],
                    "mediainfo": row["mediainfo"],
                    "is_bdinfo": is_bdinfo,
                }
            )

        cursor.close()
        conn.close()

        return jsonify(
            {"success": True, "data": records, "total": total, "page": page, "pageSize": page_size}
        )

    except Exception as e:
        logging.error(f"获取BDInfo记录失败: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"服务器内部错误: {str(e)}"}), 500


@migrate_bp.route("/migrate/bdinfo_sse/<seed_id>")
def bdinfo_sse(seed_id):
    """BDInfo进度更新的SSE端点"""
    try:
        # 生成唯一的连接ID
        connection_id = str(uuid.uuid4())

        # 导入SSE响应生成器
        from utils.sse_manager import generate_sse_response

        # 返回SSE响应流
        return generate_sse_response(connection_id, seed_id)

    except Exception as e:
        logging.error(f"创建SSE连接失败: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@migrate_bp.route("/migrate/bdinfo/progress", methods=["POST"])
def bdinfo_progress_callback():
    """接收远程BDInfo进度回传"""
    try:
        data = request.json
        task_id = data.get("task_id")
        progress_percent = data.get("progress_percent", 0)
        current_file = data.get("current_file", "")
        elapsed_time = data.get("elapsed_time", "")
        remaining_time = data.get("remaining_time", "")

        if not task_id:
            return jsonify({"success": False, "message": "缺少 task_id 参数"}), 400

        from core.bdinfo.bdinfo_manager import get_bdinfo_manager

        bdinfo_manager = get_bdinfo_manager()

        # 使用新的回调处理方法
        progress_data = {
            "progress_percent": progress_percent,
            "current_file": current_file,
            "elapsed_time": elapsed_time,
            "remaining_time": remaining_time,
        }

        success = bdinfo_manager.handle_remote_progress_callback(task_id, progress_data)

        if not success:
            return jsonify({"success": False, "message": f"任务不存在: {task_id}"}), 404

        return jsonify({"success": True, "message": "进度更新成功"})

    except Exception as e:
        logging.error(f"处理BDInfo进度回传失败: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"服务器错误: {str(e)}"}), 500


@migrate_bp.route("/migrate/bdinfo/complete", methods=["POST"])
def bdinfo_complete_callback():
    """接收远程BDInfo完成回传"""
    try:
        data = request.json
        task_id = data.get("task_id")
        success = data.get("success", False)
        bdinfo_content = data.get("bdinfo", "")
        error_message = data.get("error_message", "")

        if not task_id:
            return jsonify({"success": False, "message": "缺少 task_id 参数"}), 400

        from core.bdinfo.bdinfo_manager import get_bdinfo_manager

        bdinfo_manager = get_bdinfo_manager()

        # 使用新的完成回调处理方法
        callback_success = bdinfo_manager.handle_remote_completion_callback(
            task_id, success, bdinfo_content, error_message
        )

        if not callback_success:
            return jsonify({"success": False, "message": f"任务不存在: {task_id}"}), 404

        return jsonify({"success": True, "message": "完成状态更新成功"})

    except Exception as e:
        logging.error(f"处理BDInfo完成回传失败: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"服务器错误: {str(e)}"}), 500


@migrate_bp.route("/migrate/cleanup_bdinfo_process", methods=["POST"])
def cleanup_bdinfo_process():
    """清理 BDInfo 残留进程"""
    try:
        data = request.json
        seed_id = data.get("seed_id")

        if not seed_id:
            return jsonify({"error": "缺少 seed_id 参数"}), 400

        from core.bdinfo.bdinfo_manager import get_bdinfo_manager

        bdinfo_manager = get_bdinfo_manager()

        # 查找并清理对应的任务
        cleaned = False
        with bdinfo_manager.lock:
            for task_id, task in bdinfo_manager.tasks.items():
                if task.seed_id == seed_id and task.status == "processing_bdinfo":
                    bdinfo_manager._cleanup_process(task)
                    cleaned = True
                    break

        if cleaned:
            return jsonify({"success": True, "message": "已清理残留进程"})
        else:
            return jsonify({"success": True, "message": "未找到需要清理的进程"})

    except Exception as e:
        logging.error(f"清理 BDInfo 进程失败: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@migrate_bp.route("/migrate/restart_bdinfo", methods=["POST"])
def restart_bdinfo():
    """重启卡死的 BDInfo 任务"""
    try:
        data = request.json
        seed_id = data.get("seed_id")

        if not seed_id:
            return jsonify({"error": "缺少 seed_id 参数"}), 400

        from core.bdinfo.bdinfo_manager import get_bdinfo_manager

        bdinfo_manager = get_bdinfo_manager()

        # 获取种子数据
        conn = migrate_bp.db_manager._get_connection()
        cursor = migrate_bp.db_manager._get_cursor(conn)

        # 解析复合 seed_id，使用完整复合主键查询以确保准确性
        hash_val = torrent_id = site_name = None
        result = None
        if "_" in seed_id:
            parts = seed_id.split("_")
            if len(parts) >= 3:
                # 最后一个部分是 site_name，中间是 torrent_id，前面是 hash
                site_name = parts[-1]
                torrent_id = parts[-2]
                hash_val = "_".join(parts[:-2])

                # 使用完整复合主键查询种子名称
                if migrate_bp.db_manager.db_type == "sqlite":
                    cursor.execute(
                        "SELECT name FROM seed_parameters WHERE hash = ? AND torrent_id = ? AND site_name = ?",
                        (hash_val, torrent_id, site_name),
                    )
                else:
                    cursor.execute(
                        "SELECT name FROM seed_parameters WHERE hash = %s AND torrent_id = %s AND site_name = %s",
                        (hash_val, torrent_id, site_name),
                    )
                result = cursor.fetchone()
            else:
                # 如果格式不对，尝试使用 CONCAT 查询
                if migrate_bp.db_manager.db_type == "sqlite":
                    cursor.execute(
                        "SELECT hash, torrent_id, site_name, name FROM seed_parameters WHERE hash || '_' || torrent_id || '_' || site_name = ?",
                        (seed_id,),
                    )
                else:
                    cursor.execute(
                        "SELECT hash, torrent_id, site_name, name FROM seed_parameters WHERE CONCAT(hash, '_', torrent_id, '_', site_name) = %s",
                        (seed_id,),
                    )
                result = cursor.fetchone()
        else:
            return jsonify({"error": "无效的 seed_id 格式"}), 400

        cursor.close()
        conn.close()

        if not result:
            return jsonify({"error": "种子数据不存在"}), 404

        if isinstance(result, dict):
            if result.get("hash"):
                hash_val = result.get("hash")
                torrent_id = result.get("torrent_id")
                site_name = result.get("site_name")
            torrent_name = result.get("name")
        else:
            if len(result) >= 4:
                hash_val = result[0]
                torrent_id = result[1]
                site_name = result[2]
                torrent_name = result[3]
            else:
                torrent_name = result[0] if len(result) > 0 else None

        torrent_info = get_current_torrent_info(migrate_bp.db_manager, hash_val)
        save_path = torrent_info.get("save_path") if torrent_info else None
        downloader_id = torrent_info.get("downloader_id") if torrent_info else None
        if not torrent_name and torrent_info:
            torrent_name = torrent_info.get("name")

        if not save_path:
            return jsonify({"error": "无法获取保存路径"}), 404

        # 1. 清理可能的残留进程
        bdinfo_manager.cleanup_orphaned_process(seed_id)

        # 2. 重置数据库状态
        bdinfo_manager.reset_task_status(seed_id)

        # 3. 构建完整的保存路径（如果有torrent_name）
        actual_save_path = save_path
        if torrent_name and save_path:
            # 检查save_path是否已经包含了torrent_name
            if not save_path.endswith(torrent_name):
                actual_save_path = os.path.join(save_path, torrent_name)
                logging.info(
                    f"重启BDInfo任务构建完整路径: {save_path} + {torrent_name} -> {actual_save_path}"
                )

        # 4. 应用路径映射（如果有下载器ID）
        if downloader_id:
            try:
                from utils.mediainfo import translate_path

                mapped_path = translate_path(downloader_id, actual_save_path)
                if mapped_path != actual_save_path:
                    logging.info(
                        f"重启BDInfo任务应用路径映射: {actual_save_path} -> {mapped_path}"
                    )
                    actual_save_path = mapped_path
            except Exception as e:
                logging.warning(f"路径映射失败，使用原始路径: {e}")
        # 5. 重新添加任务
        task_id = bdinfo_manager.add_task(
            seed_id=seed_id,
            save_path=actual_save_path,
            priority=1,
            downloader_id=downloader_id,  # 高优先级，传递下载器ID（可能为None）
        )

        return jsonify({"success": True, "task_id": task_id, "message": "BDInfo 任务已重启"})

    except Exception as e:
        logging.error(f"重启 BDInfo 任务失败: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
