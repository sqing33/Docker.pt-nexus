# api/routes_migrate.py

import logging
import uuid
import re
import os
import requests
import urllib.parse
from flask import Blueprint, jsonify, request
from bs4 import BeautifulSoup
from utils import upload_data_title, upload_data_screenshot, upload_data_poster, upload_data_movie_info, add_torrent_to_downloader, extract_tags_from_mediainfo, extract_origin_from_description, extract_resolution_from_mediainfo
from core.migrator import TorrentMigrator

# 导入种子参数模型
from models.seed_parameter import SeedParameter

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
#                         原有迁移 API
# ===================================================================


# 新增：从数据库读取种子信息的API接口
@migrate_bp.route("/migrate/get_db_seed_info", methods=["GET"])
def get_db_seed_info():
    """从数据库读取种子信息用于展示"""
    try:
        torrent_id = request.args.get('torrent_id')
        site_name = request.args.get('site_name')

        if not torrent_id or not site_name:
            return jsonify({
                "success": False,
                "message": "错误：torrent_id和site_name参数不能为空"
            }), 400

        db_manager = migrate_bp.db_manager

        # 从数据库读取
        try:
            # 初始化种子参数模型
            from models.seed_parameter import SeedParameter
            seed_param_model = SeedParameter(db_manager)
            parameters = seed_param_model.get_parameters(torrent_id, site_name)

            if parameters:
                logging.info(f"成功从数据库读取种子信息: {torrent_id} from {site_name}")

                # 生成反向映射表（从标准键到中文显示名称的映射）
                reverse_mappings = generate_reverse_mappings()

                # 生成task_id并存入缓存，以便发布时使用
                task_id = str(uuid.uuid4())

                # 获取站点信息
                source_info = db_manager.get_site_by_nickname(site_name)
                if not source_info:
                    # 如果通过昵称找不到，尝试通过英文站点名查找
                    try:
                        conn = db_manager._get_connection()
                        cursor = db_manager._get_cursor(conn)
                        cursor.execute("SELECT * FROM sites WHERE site = ?",
                                       (site_name, ))
                        source_info = cursor.fetchone()
                        if source_info:
                            source_info = dict(source_info)
                    except Exception as e:
                        logging.warning(f"获取站点信息失败: {e}")

                # 将数据存入缓存，以便发布时使用
                MIGRATION_CACHE[task_id] = {
                    "source_info": source_info,
                    "original_torrent_path": None,  # 将在发布时重新获取
                    "torrent_dir": None,  # 将在发布时重新确定
                    "source_site_name": site_name,
                    "source_torrent_id": torrent_id,
                    "requires_torrent_download": True,  # 需要下载种子文件
                }

                return jsonify({
                    "success": True,
                    "data": parameters,
                    "source": "database",
                    "task_id": task_id,  # 返回task_id给前端
                    "reverse_mappings": reverse_mappings
                })
            else:
                logging.info(f"数据库中未找到种子信息: {torrent_id} from {site_name}")
                return jsonify({
                    "success": False,
                    "message": "数据库中未找到种子信息"
                }), 404

        except Exception as e:
            logging.error(f"从数据库读取种子信息失败: {e}", exc_info=True)
            return jsonify({
                "success": False,
                "message": f"数据库读取失败: {str(e)}"
            }), 500

    except Exception as e:
        logging.error(f"get_db_seed_info发生意外错误: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "message": f"服务器内部错误: {str(e)}"
        }), 500


def generate_reverse_mappings():
    """生成从标准键到中文显示名称的反向映射"""
    try:
        # 读取全局映射配置
        import yaml
        import os

        # 首先尝试从global_mappings.yaml读取
        global_mappings_path = os.path.join(os.path.dirname(__file__),
                                            '../configs/global_mappings.yaml')
        global_mappings = {}

        if os.path.exists(global_mappings_path):
            try:
                with open(global_mappings_path, 'r', encoding='utf-8') as f:
                    config_data = yaml.safe_load(f)
                    global_mappings = config_data.get('global_standard_keys',
                                                      {})
                logging.info(
                    f"成功从global_mappings.yaml读取配置，包含{len(global_mappings)}个类别")
            except Exception as e:
                logging.warning(f"读取global_mappings.yaml失败: {e}，将使用配置文件中的设置")

        # 如果YAML文件读取失败，从配置管理器获取
        if not global_mappings:
            config = config_manager.get()
            global_mappings = config.get('global_standard_keys', {})

        reverse_mappings = {
            'type': {},
            'medium': {},
            'video_codec': {},
            'audio_codec': {},
            'resolution': {},
            'source': {},
            'team': {},
            'tags': {}
        }

        # 为每个类别生成反向映射
        categories_mapping = {
            'type': global_mappings.get('type', {}),
            'medium': global_mappings.get('medium', {}),
            'video_codec': global_mappings.get('video_codec', {}),
            'audio_codec': global_mappings.get('audio_codec', {}),
            'resolution': global_mappings.get('resolution', {}),
            'source': global_mappings.get('source', {}),
            'team': global_mappings.get('team', {}),
            'tags': global_mappings.get('tag', {})  # 注意这里YAML中是'tag'而不是'tags'
        }

        # 创建反向映射：从标准值到中文名称
        for category, mappings in categories_mapping.items():
            if category == 'tags':
                # 标签特殊处理，提取中文名作为键，标准值作为值
                for chinese_name, standard_value in mappings.items():
                    if standard_value:  # 过滤掉null值
                        reverse_mappings['tags'][standard_value] = chinese_name
            else:
                # 其他类别正常处理
                for chinese_name, standard_value in mappings.items():
                    if standard_value and standard_value not in reverse_mappings[
                            category]:
                        reverse_mappings[category][
                            standard_value] = chinese_name

        # 只在必要时添加固定映射项作为后备，避免覆盖YAML配置
        add_fallback_mappings(reverse_mappings)

        logging.info(
            f"成功生成反向映射表: { {k: len(v) for k, v in reverse_mappings.items()} }")
        return reverse_mappings

    except Exception as e:
        logging.error(f"生成反向映射表失败: {e}", exc_info=True)
        # 返回空的反向映射表作为后备
        return {
            'type': {},
            'medium': {},
            'video_codec': {},
            'audio_codec': {},
            'resolution': {},
            'source': {},
            'team': {},
            'tags': {}
        }


def add_fallback_mappings(reverse_mappings):
    """添加后备映射项，仅在YAML配置缺失时使用"""

    # 检查各个类别是否为空，如果为空则添加基础映射
    if not reverse_mappings['type']:
        logging.warning("type映射为空，添加基础后备映射")
        reverse_mappings['type'].update({
            'category.movie': '电影',
            'category.tv_series': '剧集',
            'category.animation': '动画',
            'category.documentaries': '纪录片',
            'category.music': '音乐',
            'category.other': '其他'
        })

    if not reverse_mappings['medium']:
        logging.warning("medium映射为空，添加基础后备映射")
        reverse_mappings['medium'].update({
            'medium.bluray': 'Blu-ray',
            'medium.uhd_bluray': 'UHD Blu-ray',
            'medium.remux': 'Remux',
            'medium.encode': 'Encode',
            'medium.webdl': 'WEB-DL',
            'medium.webrip': 'WebRip',
            'medium.hdtv': 'HDTV',
            'medium.dvd': 'DVD',
            'medium.other': '其他'
        })

    if not reverse_mappings['video_codec']:
        logging.warning("video_codec映射为空，添加基础后备映射")
        reverse_mappings['video_codec'].update({
            'video.h264': 'H.264/AVC',
            'video.h265': 'H.265/HEVC',
            'video.x265': 'x265',
            'video.vc1': 'VC-1',
            'video.mpeg2': 'MPEG-2',
            'video.av1': 'AV1',
            'video.other': '其他'
        })

    if not reverse_mappings['audio_codec']:
        logging.warning("audio_codec映射为空，添加基础后备映射")
        reverse_mappings['audio_codec'].update({
            'audio.flac': 'FLAC',
            'audio.dts': 'DTS',
            'audio.dts_hd_ma': 'DTS-HD MA',
            'audio.dtsx': 'DTS:X',
            'audio.truehd': 'TrueHD',
            'audio.truehd_atmos': 'TrueHD Atmos',
            'audio.ac3': 'AC-3',
            'audio.ddp': 'E-AC-3',
            'audio.aac': 'AAC',
            'audio.mp3': 'MP3',
            'audio.other': '其他'
        })

    if not reverse_mappings['resolution']:
        logging.warning("resolution映射为空，添加基础后备映射")
        reverse_mappings['resolution'].update({
            'resolution.r8k': '8K',
            'resolution.r4k': '4K',
            'resolution.r2160p': '2160p',
            'resolution.r1080p': '1080p',
            'resolution.r1080i': '1080i',
            'resolution.r720p': '720p',
            'resolution.r480p': '480p',
            'resolution.other': '其他'
        })

    if not reverse_mappings['source']:
        logging.warning("source映射为空，添加基础后备映射")
        reverse_mappings['source'].update({
            'source.china': '中国',
            'source.hongkong': '香港',
            'source.taiwan': '台湾',
            'source.usa': '美国',
            'source.uk': '英国',
            'source.japan': '日本',
            'source.korea': '韩国',
            'source.other': '其他'
        })

    if not reverse_mappings['team']:
        logging.warning("team映射为空，添加基础后备映射")
        reverse_mappings['team'].update({'team.other': '其他'})

    if not reverse_mappings['tags']:
        logging.warning("tags映射为空，添加基础后备映射")
        reverse_mappings['tags'].update({
            'tag.DIY': 'DIY',
            'tag.中字': '中字',
            'tag.HDR': 'HDR',
            'tag.官种': '官种',
            'tag.首发': '首发'
        })


@migrate_bp.route("/migrate/download_torrent_only", methods=["POST"])
def download_torrent_only():
    """仅下载种子文件，不进行数据解析或存储"""
    try:
        data = request.json
        torrent_id = data.get('torrent_id')
        site_name = data.get('site_name')

        if not all([torrent_id, site_name]):
            return jsonify({
                "success": False,
                "message": "错误：缺少必要参数（torrent_id、site_name）"
            }), 400

        db_manager = migrate_bp.db_manager

        # 获取站点信息
        source_info = db_manager.get_site_by_nickname(site_name)
        if not source_info or not source_info.get("cookie"):
            return jsonify({
                "success": False,
                "message": f"错误：源站点 '{site_name}' 配置不完整。"
            }), 404

        # 从数据库获取种子标题以确定目录名
        from models.seed_parameter import SeedParameter
        seed_param_model = SeedParameter(db_manager)
        parameters = seed_param_model.get_parameters(torrent_id, site_name)

        if not parameters or not parameters.get("title"):
            return jsonify({"success": False, "message": "无法从数据库获取种子标题"}), 404

        # 创建种子目录
        from config import TEMP_DIR
        import re
        import os

        original_main_title = parameters.get("title", "")
        safe_filename_base = re.sub(r'[\\/*?:"<>|]', "_",
                                    original_main_title)[:150]
        torrent_dir = os.path.join(TEMP_DIR, safe_filename_base)
        os.makedirs(torrent_dir, exist_ok=True)

        # 创建TorrentMigrator实例仅用于下载种子文件
        migrator = TorrentMigrator(source_site_info=source_info,
                                   target_site_info=None,
                                   search_term=torrent_id,
                                   config_manager=config_manager,
                                   db_manager=db_manager)

        # 下载种子文件
        torrent_path = migrator._download_torrent_file(torrent_id, torrent_dir)

        if torrent_path and os.path.exists(torrent_path):
            return jsonify({
                "success": True,
                "torrent_path": torrent_path,
                "torrent_dir": torrent_dir,
                "message": "种子文件下载成功"
            })
        else:
            return jsonify({"success": False, "message": "种子文件下载失败"}), 500

    except Exception as e:
        logging.error(f"download_torrent_only 发生意外错误: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "message": f"服务器内部错误: {str(e)}"
        }), 500


# 新增：专门负责数据抓取和存储的API接口
@migrate_bp.route("/migrate/fetch_and_store", methods=["POST"])
def migrate_fetch_and_store():
    """专门负责种子信息抓取和存储，不返回预览数据"""
    db_manager = migrate_bp.db_manager
    data = request.json
    source_site_name, search_term, save_path, torrent_name, downloader_id = (
        data.get("sourceSite"), data.get("searchTerm"),
        data.get("savePath",
                 ""), data.get("torrentName"), data.get("downloaderId"))

    if not all([source_site_name, search_term]):
        return jsonify({"success": False, "message": "错误：源站点和搜索词不能为空。"}), 400

    try:
        # 获取站点信息并获取英文站点名
        source_info = db_manager.get_site_by_nickname(source_site_name)

        if not source_info or not source_info.get("cookie"):
            return (
                jsonify({
                    "success": False,
                    "message": f"错误：源站点 '{source_site_name}' 配置不完整。"
                }),
                404,
            )

        source_role = source_info.get("migration", 0)

        if source_role not in [1, 3]:
            return (
                jsonify({
                    "success": False,
                    "message": f"错误：站点 '{source_site_name}' 不允许作为源站点进行迁移。"
                }),
                403,
            )

        # 获取英文站点名作为唯一标识符
        english_site_name = source_info.get("site", source_site_name.lower())

        # 初始化 Migrator 时不传入目标站点信息
        migrator = TorrentMigrator(source_site_info=source_info,
                                   target_site_info=None,
                                   search_term=search_term,
                                   save_path=save_path,
                                   torrent_name=torrent_name,
                                   config_manager=config_manager,
                                   db_manager=db_manager,
                                   downloader_id=downloader_id)

        # 调用数据抓取和信息提取（这会自动保存到数据库）
        result = migrator.prepare_review_data()

        if "review_data" in result:
            task_id = str(uuid.uuid4())
            # 只缓存必要信息，包括种子目录路径用于发布时查找种子文件
            MIGRATION_CACHE[task_id] = {
                "source_info": source_info,
                "original_torrent_path": result["original_torrent_path"],
                "torrent_dir": result["torrent_dir"],  # 保存种子目录路径
                "source_site_name": english_site_name,  # 使用英文站点名作为唯一标识符
                "source_torrent_id": search_term,
            }

            logging.info(
                f"种子信息抓取并存储成功: {search_term} from {source_site_name} ({english_site_name})"
            )
            return jsonify({
                "success": True,
                "task_id": task_id,
                "message": "种子信息已成功保存到数据库",
                "logs": result["logs"],
            })
        else:
            return jsonify({
                "success": False,
                "message": result.get("logs", "未知错误")
            })
    except Exception as e:
        logging.error(f"migrate_fetch_and_store 发生意外错误: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"服务器内部错误: {e}"}), 500


# 新增：更新数据库种子参数并重新标准化的API接口
@migrate_bp.route("/migrate/update_db_seed_info", methods=["POST"])
def update_db_seed_info():
    """更新数据库中的参数并重新标准化"""
    try:
        data = request.json
        torrent_id = data.get('torrent_id')
        site_name = data.get('site_name')
        updated_parameters = data.get('updated_parameters')

        if not all([torrent_id, site_name, updated_parameters]):
            return jsonify({
                "success":
                False,
                "message":
                "错误：缺少必要参数（torrent_id、site_name、updated_parameters）"
            }), 400

        db_manager = migrate_bp.db_manager

        try:
            # 更新数据库
            from models.seed_parameter import SeedParameter
            seed_param_model = SeedParameter(db_manager)

            # 获取站点信息以获取英文站点名
            source_info = db_manager.get_site_by_nickname(site_name)
            if source_info:
                english_site_name = source_info.get("site", site_name.lower())
            else:
                # 如果找不到站点信息，使用映射关系
                site_mapping = {
                    '人人': 'audiences',
                    '不可说': 'ssd',
                    '憨憨': 'hhanclub'
                }
                english_site_name = site_mapping.get(site_name,
                                                     site_name.lower())

            logging.info(
                f"开始更新种子参数: {torrent_id} from {site_name} ({english_site_name})"
            )

            # 检查用户是否提供了修改的标准参数
            user_standardized_params = updated_parameters.get(
                'standardized_params', {})

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
                    'title':
                    updated_parameters.get('title', ''),
                    'subtitle':
                    updated_parameters.get('subtitle', ''),
                    'imdb_link':
                    updated_parameters.get('imdb_link', ''),
                    'douban_link':
                    updated_parameters.get('douban_link', ''),
                    'intro': {
                        'statement': updated_parameters.get('statement', ''),
                        'poster': updated_parameters.get('poster', ''),
                        'body': updated_parameters.get('body', ''),
                        'screenshots':
                        updated_parameters.get('screenshots', ''),
                        'imdb_link': updated_parameters.get('imdb_link', ''),
                        'douban_link':
                        updated_parameters.get('douban_link', '')
                    },
                    'mediainfo':
                    updated_parameters.get('mediainfo', ''),
                    'source_params':
                    updated_parameters.get('source_params', {}),
                    'title_components':
                    updated_parameters.get('title_components', [])
                }

                # 使用ParameterMapper重新标准化参数
                from core.extractors.extractor import ParameterMapper
                mapper = ParameterMapper()

                # 重新标准化参数
                standardized_params = mapper.map_parameters(
                    site_name, english_site_name, extracted_data)

            # 从title_components中提取标题拆解的各项参数
            title_components = updated_parameters.get('title_components', [])

            # [新增] 开始：根据 title_components 拼接新标题
            # 1. 将 title_components 列表转换为字典，方便后续查找
            title_params = {
                item["key"]: item["value"]
                for item in title_components if item.get("value")
            }

            # 2. 使用您提供的逻辑来拼接标题
            order = [
                "主标题",
                "季集",
                "年份",
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
            # [新增] 结束：标题拼接完成，结果保存在 preview_title 变量中

            # 构造完整的存储参数
            final_parameters = {
                # [修改] 将原来的 title 值替换为新生成的 preview_title
                "title": preview_title,
                "subtitle": updated_parameters.get('subtitle', ''),
                "imdb_link": updated_parameters.get('imdb_link', ''),
                "douban_link": updated_parameters.get('douban_link', ''),
                "poster": updated_parameters.get('poster', ''),
                "screenshots": updated_parameters.get('screenshots', ''),
                "statement": updated_parameters.get('statement', ''),
                "body": updated_parameters.get('body', ''),
                "mediainfo": updated_parameters.get('mediainfo', ''),
                "type": standardized_params.get('type', ''),
                "medium": standardized_params.get('medium', ''),
                "video_codec": standardized_params.get('video_codec', ''),
                "audio_codec": standardized_params.get('audio_codec', ''),
                "resolution": standardized_params.get('resolution', ''),
                "team": standardized_params.get('team', ''),
                "source": standardized_params.get('source', ''),
                "tags": standardized_params.get('tags', []),
                "title_components": title_components,
                "standardized_params": standardized_params,
                "final_publish_parameters": {
                    # [修改] 预览标题也使用新生成的标题
                    "主标题 (预览)": preview_title,
                    "副标题": updated_parameters.get('subtitle', ''),
                    "IMDb链接": standardized_params.get("imdb_link", ""),
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
                    "title_components":
                    updated_parameters.get('title_components', []),
                    "subtitle":
                    updated_parameters.get('subtitle', ''),
                    "imdb_link":
                    standardized_params.get("imdb_link", ""),
                    "douban_link":
                    standardized_params.get("douban_link", ""),
                    "intro": {
                        "statement":
                        updated_parameters.get('statement', ''),
                        "poster":
                        updated_parameters.get('poster', ''),
                        "body":
                        updated_parameters.get('body', ''),
                        "screenshots":
                        updated_parameters.get('screenshots', ''),
                        "removed_ardtudeclarations":
                        updated_parameters.get('removed_ardtudeclarations',
                                               []),
                        "imdb_link":
                        updated_parameters.get('imdb_link', ''),
                        "douban_link":
                        updated_parameters.get('douban_link', '')
                    },
                    "mediainfo":
                    updated_parameters.get('mediainfo', ''),
                    "source_params":
                    updated_parameters.get('source_params', {}),
                    "standardized_params":
                    standardized_params
                },
                "raw_params_for_preview": {
                    # [修改] 原始预览参数也使用新标题
                    "final_main_title": preview_title,
                    "subtitle": updated_parameters.get('subtitle', ''),
                    "imdb_link": standardized_params.get("imdb_link", ""),
                    "type": standardized_params.get("type", ""),
                    "medium": standardized_params.get("medium", ""),
                    "video_codec": standardized_params.get("video_codec", ""),
                    "audio_codec": standardized_params.get("audio_codec", ""),
                    "resolution": standardized_params.get("resolution", ""),
                    "release_group": standardized_params.get("team", ""),
                    "source": standardized_params.get("source", ""),
                    "tags": standardized_params.get("tags", [])
                }
            }

            update_result = seed_param_model.update_parameters(
                torrent_id, english_site_name, final_parameters)

            # 后续代码保持不变...
            if update_result:
                logging.info(
                    f"种子参数更新成功: {torrent_id} from {site_name} ({english_site_name})"
                )

                # 生成反向映射表（从标准键到中文显示名称的映射）
                reverse_mappings = generate_reverse_mappings()

                return jsonify({
                    "success":
                    True,
                    "standardized_params":
                    standardized_params,
                    "final_publish_parameters":
                    final_parameters["final_publish_parameters"],
                    "complete_publish_params":
                    final_parameters["complete_publish_params"],
                    "raw_params_for_preview":
                    final_parameters["raw_params_for_preview"],
                    "reverse_mappings":
                    reverse_mappings,
                    "message":
                    "参数更新并标准化成功"
                })
            else:
                logging.warning(
                    f"种子参数更新失败: {torrent_id} from {site_name} ({english_site_name})"
                )
                return jsonify({"success": False, "message": "参数更新失败"}), 500

        except Exception as e:
            logging.error(f"更新种子参数失败: {e}", exc_info=True)
            return jsonify({
                "success": False,
                "message": f"更新失败: {str(e)}"
            }), 500

    except Exception as e:
        logging.error(f"update_db_seed_info发生意外错误: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "message": f"服务器内部错误: {str(e)}"
        }), 500


# 保留原fetch_info接口作为向后兼容，但内部调用新的fetch_and_store + get_db_seed_info
@migrate_bp.route("/migrate/fetch_info", methods=["POST"])
def migrate_fetch_info():
    """原接口，保持向后兼容（现在内部调用新的断点架构）"""
    db_manager = migrate_bp.db_manager
    data = request.json
    source_site_name, search_term, save_path = (data.get("sourceSite"),
                                                data.get("searchTerm"),
                                                data.get("savePath", ""))

    if not all([source_site_name, search_term]):
        return jsonify({"success": False, "logs": "错误：源站点和搜索词不能为空。"}), 400

    try:
        # 第一步：调用fetch_and_store抓取并存储数据
        from flask import request as flask_request
        import json

        # 模拟调用fetch_and_store
        store_data = {
            "sourceSite": source_site_name,
            "searchTerm": search_term,
            "savePath": save_path
        }

        # 直接调用fetch_and_store函数
        with flask_request._fake_request(
                '/api/migrate/fetch_and_store',
                'POST',
                data=json.dumps(store_data),
                headers={'Content-Type': 'application/json'}):
            store_result = migrate_fetch_and_store()

        store_response_data = store_result.get_json()

        if not store_response_data.get("success"):
            return jsonify({
                "success": False,
                "logs": store_response_data.get("message", "数据抓取失败")
            })

        # 第二步：从数据库读取数据
        from models.seed_parameter import SeedParameter
        seed_param_model = SeedParameter(db_manager)
        parameters = seed_param_model.get_parameters(search_term,
                                                     source_site_name)

        if parameters:
            task_id = store_response_data.get("task_id")

            # 缓存必要信息用于发布
            MIGRATION_CACHE[task_id] = {
                "source_info":
                db_manager.get_site_by_nickname(source_site_name),
                "original_torrent_path": None,  # 将在发布时重新获取
                "torrent_dir": None,  # 将在发布时重新确定
                "source_site_name": source_site_name,
                "source_torrent_id": search_term,
                "requires_torrent_download": False,  # 不再强制重新下载，改为根据实际文件存在情况判断
            }

            # 构造兼容原有格式的响应
            return jsonify({
                "success": True,
                "task_id": task_id,
                "data": {
                    "original_main_title":
                    parameters.get("title", ""),
                    "title_components":
                    parameters.get("title_components", []),
                    "subtitle":
                    parameters.get("subtitle", ""),
                    "imdb_link":
                    parameters.get("imdb_link", ""),
                    "douban_link":
                    parameters.get("douban_link", ""),
                    "intro": {
                        "statement":
                        parameters.get("statement", ""),
                        "poster":
                        parameters.get("poster", ""),
                        "body":
                        parameters.get("body", ""),
                        "screenshots":
                        parameters.get("screenshots", ""),
                        "removed_ardtudeclarations":
                        parameters.get("removed_ardtudeclarations", []),
                        "imdb_link":
                        parameters.get("imdb_link", ""),
                        "douban_link":
                        parameters.get("douban_link", "")
                    },
                    "mediainfo":
                    parameters.get("mediainfo", ""),
                    "source_params":
                    parameters.get("source_params", {}),
                    "standardized_params":
                    parameters.get("standardized_params", {}),
                    "final_publish_parameters":
                    parameters.get("final_publish_parameters", {}),
                    "complete_publish_params":
                    parameters.get("complete_publish_params", {}),
                    "raw_params_for_preview":
                    parameters.get("raw_params_for_preview", {}),
                },
                "logs": store_response_data.get("logs", "")
            })
        else:
            return jsonify({"success": False, "logs": "数据抓取成功但从数据库读取失败"})
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
        if not target_info:
            return jsonify({
                "success": False,
                "logs": f"错误: 目标站点 '{target_site_name}' 配置不完整。"
            }), 404

        source_info = context["source_info"]
        original_torrent_path = context["original_torrent_path"]
        torrent_dir = context.get("torrent_dir", "")  # 获取种子目录

        # 从缓存中获取源站点名称（如果前端没有传递）
        if not source_site_name:
            source_site_name = context.get("source_site_name", "")

        # 创建 TorrentMigrator 实例用于发布
        migrator = TorrentMigrator(source_info,
                                   target_info,
                                   search_term=context.get(
                                       "source_torrent_id", ""),
                                   save_path=upload_data.get("save_path", "")
                                   or upload_data.get("savePath", ""),
                                   config_manager=config_manager,
                                   db_manager=db_manager)

        # 检查种子文件是否存在，如果不存在则重新下载
        # 首先检查原始路径
        if original_torrent_path is None or not os.path.exists(
                original_torrent_path):
            logging.info("原始种子文件路径不存在，检查临时目录")
            # 如果原始路径不存在，检查临时目录中是否已有种子文件
            # 首先检查以种子ID命名的目录（旧格式）
            source_torrent_id = context.get("source_torrent_id", "")
            if source_torrent_id:
                from config import TEMP_DIR
                # 检查旧格式目录
                old_torrent_dir = os.path.join(TEMP_DIR,
                                               f"torrent_{source_torrent_id}")
                if os.path.exists(old_torrent_dir):
                    try:
                        # 查找old_torrent_dir中的.torrent文件
                        for file in os.listdir(old_torrent_dir):
                            if file.endswith('.torrent'):
                                original_torrent_path = os.path.join(
                                    old_torrent_dir, file)
                                logging.info(
                                    f"在旧格式临时目录中找到种子文件: {original_torrent_path}"
                                )
                                break
                    except Exception as e:
                        logging.warning(f"查找旧格式临时目录中的种子文件时出错: {e}")

                # 如果在旧格式目录中没找到，检查以种子名称命名的目录（新格式）
                if original_torrent_path is None or not os.path.exists(
                        original_torrent_path):
                    # 尝试从缓存中获取种子目录路径
                    cached_torrent_dir = context.get("torrent_dir")
                    if cached_torrent_dir and os.path.exists(
                            cached_torrent_dir):
                        try:
                            # 查找cached_torrent_dir中的.torrent文件
                            for file in os.listdir(cached_torrent_dir):
                                if file.endswith('.torrent'):
                                    original_torrent_path = os.path.join(
                                        cached_torrent_dir, file)
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
                            db_manager = current_app.config['DB_MANAGER']
                            seed_param_model = SeedParameter(db_manager)

                            source_torrent_id = context.get(
                                "source_torrent_id", "")
                            source_site_name = context.get(
                                "source_site_name", "")

                            if source_torrent_id and source_site_name:
                                # 从数据库获取种子参数
                                parameters = seed_param_model.get_parameters(
                                    source_torrent_id, source_site_name)
                                if parameters and parameters.get("title"):
                                    # 重建种子目录路径
                                    from config import TEMP_DIR
                                    import re
                                    original_main_title = parameters.get(
                                        "title", "")
                                    safe_filename_base = re.sub(
                                        r'[\\/*?:"<>|]', "_",
                                        original_main_title)[:150]
                                    reconstructed_torrent_dir = os.path.join(
                                        TEMP_DIR, safe_filename_base)

                                    if os.path.exists(
                                            reconstructed_torrent_dir):
                                        try:
                                            # 查找reconstructed_torrent_dir中的.torrent文件
                                            for file in os.listdir(
                                                    reconstructed_torrent_dir):
                                                if file.endswith('.torrent'):
                                                    original_torrent_path = os.path.join(
                                                        reconstructed_torrent_dir,
                                                        file)
                                                    logging.info(
                                                        f"在重构的目录中找到种子文件: {original_torrent_path}"
                                                    )
                                                    break
                                        except Exception as e:
                                            logging.warning(
                                                f"查找重构目录中的种子文件时出错: {e}")
                        except Exception as e:
                            logging.warning(f"尝试重构种子目录路径时出错: {e}")

            # 如果仍然没有找到，直接在TEMP_DIR中查找以种子名称命名的目录
            if original_torrent_path is None or not os.path.exists(
                    original_torrent_path):
                try:
                    # 从数据库获取种子参数来确定目录名
                    from models.seed_parameter import SeedParameter
                    from flask import current_app
                    db_manager = current_app.config['DB_MANAGER']
                    seed_param_model = SeedParameter(db_manager)

                    source_torrent_id = context.get("source_torrent_id", "")
                    source_site_name = context.get("source_site_name", "")

                    if source_torrent_id and source_site_name:
                        # 从数据库获取种子参数
                        parameters = seed_param_model.get_parameters(
                            source_torrent_id, source_site_name)
                        if parameters and parameters.get("title"):
                            # 重建种子目录路径
                            from config import TEMP_DIR
                            import re
                            original_main_title = parameters.get("title", "")
                            safe_filename_base = re.sub(
                                r'[\\/*?:"<>|]', "_",
                                original_main_title)[:150]
                            seed_name_dir = os.path.join(
                                TEMP_DIR, safe_filename_base)

                            # 在该目录中查找.torrent文件
                            if os.path.exists(seed_name_dir):
                                for file in os.listdir(seed_name_dir):
                                    if file.endswith('.torrent'):
                                        original_torrent_path = os.path.join(
                                            seed_name_dir, file)
                                        logging.info(
                                            f"在种子名称目录中找到种子文件: {original_torrent_path}"
                                        )
                                        break
                except Exception as e:
                    logging.warning(f"查找种子名称目录中的种子文件时出错: {e}")

            # 如果仍然没有找到有效的种子文件，则重新下载
            if original_torrent_path is None or not os.path.exists(
                    original_torrent_path):
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
                    SOURCE_BASE_URL = source_info.get("base_url",
                                                      "").rstrip('/')
                    # 确保URL有正确的协议前缀
                    if SOURCE_BASE_URL and not SOURCE_BASE_URL.startswith(
                        ('http://', 'https://')):
                        SOURCE_BASE_URL = 'https://' + SOURCE_BASE_URL
                    SOURCE_COOKIE = source_info.get("cookie", "")
                    source_torrent_id = context.get("source_torrent_id", "")

                    if SOURCE_BASE_URL and SOURCE_COOKIE and source_torrent_id:
                        # 获取详情页以找到下载链接
                        response = scraper.get(
                            f"{SOURCE_BASE_URL}/details.php",
                            headers={"Cookie": SOURCE_COOKIE},
                            params={
                                "id": source_torrent_id,
                                "hit": "1"
                            },
                            timeout=60)
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
                                headers={"Cookie": SOURCE_COOKIE},
                                timeout=60,
                            )
                            torrent_response.raise_for_status()

                            # 从响应头中尝试获取文件名
                            content_disposition = torrent_response.headers.get(
                                'content-disposition')
                            torrent_filename = "unknown.torrent"
                            if content_disposition:
                                # 尝试匹配filename*（支持UTF-8编码）和filename
                                filename_match = re.search(
                                    r'filename\*="?UTF-8\'\'([^"]+)"?',
                                    content_disposition, re.IGNORECASE)
                                if filename_match:
                                    torrent_filename = filename_match.group(1)
                                    # URL解码文件名（UTF-8编码）
                                    torrent_filename = urllib.parse.unquote(
                                        torrent_filename, encoding='utf-8')
                                else:
                                    # 尝试匹配普通的filename
                                    filename_match = re.search(
                                        r'filename="?([^"]+)"?',
                                        content_disposition)
                                    if filename_match:
                                        torrent_filename = filename_match.group(
                                            1)
                                        # URL解码文件名
                                        torrent_filename = urllib.parse.unquote(
                                            torrent_filename)

                            # 如果 torrent_dir 还没有确定，尝试从数据库获取种子标题来创建目录
                            if not torrent_dir:
                                try:
                                    # 从数据库获取种子参数来确定目录名
                                    from models.seed_parameter import SeedParameter
                                    from flask import current_app
                                    db_manager = current_app.config[
                                        'DB_MANAGER']
                                    seed_param_model = SeedParameter(
                                        db_manager)

                                    if source_torrent_id and source_site_name:
                                        # 从数据库获取种子参数
                                        parameters = seed_param_model.get_parameters(
                                            source_torrent_id,
                                            source_site_name)
                                        if parameters and parameters.get(
                                                "title"):
                                            # 重建种子目录路径
                                            from config import TEMP_DIR
                                            import re
                                            original_main_title = parameters.get(
                                                "title", "")
                                            safe_filename_base = re.sub(
                                                r'[\\/*?:"<>|]', "_",
                                                original_main_title)[:150]
                                            torrent_dir = os.path.join(
                                                TEMP_DIR, safe_filename_base)
                                            os.makedirs(torrent_dir,
                                                        exist_ok=True)
                                except Exception as e:
                                    logging.warning(f"尝试从数据库获取标题创建目录时出错: {e}")

                            # 如果 still 没有 torrent_dir，则回退到原来的以ID命名的目录
                            if not torrent_dir:
                                torrent_dir = os.path.join(
                                    TEMP_DIR, f"torrent_{source_torrent_id}")
                                os.makedirs(torrent_dir, exist_ok=True)

                            # 保存种子文件
                            # 确保文件名在文件系统中是有效的，并正确处理中文字符
                            try:
                                # 对文件名进行文件系统安全的处理
                                safe_filename = torrent_filename
                                # 移除或替换文件系统不支持的字符
                                safe_filename = re.sub(r'[<>:"/\\|?*]', '_',
                                                       safe_filename)
                                # 确保文件名不超过文件系统限制
                                if len(safe_filename.encode('utf-8')) > 255:
                                    # 如果文件名太长，截断并保持扩展名
                                    name, ext = os.path.splitext(safe_filename)
                                    max_len = 255 - len(ext.encode('utf-8'))
                                    safe_filename = name.encode(
                                        'utf-8')[:max_len].decode(
                                            'utf-8', 'ignore') + ext

                                original_torrent_path = os.path.join(
                                    torrent_dir, safe_filename)
                                with open(original_torrent_path, "wb") as f:
                                    f.write(torrent_response.content)
                            except OSError as e:
                                # 如果文件名有问题，使用默认名称
                                logging.warning(f"使用原始文件名保存失败: {e}, 使用默认名称")
                                original_torrent_path = os.path.join(
                                    torrent_dir, "torrent.torrent")
                                with open(original_torrent_path, "wb") as f:
                                    f.write(torrent_response.content)

                            logging.info(
                                f"重新下载种子文件成功: {original_torrent_path}")
                        else:
                            logging.error("未找到种子下载链接")
                            return jsonify({
                                "success": False,
                                "logs": "错误：未找到种子下载链接。"
                            }), 404
                    else:
                        logging.error("缺少必要的源站点信息")
                        return jsonify({
                            "success": False,
                            "logs": "错误：缺少必要的源站点信息。"
                        }), 400
                except Exception as e:
                    logging.error(f"重新下载种子文件失败: {e}")
                    return jsonify({
                        "success": False,
                        "logs": f"重新下载种子文件失败: {e}"
                    }), 500

        # 1. 直接使用原始种子文件路径进行发布（不再修改种子）
        if not original_torrent_path or not os.path.exists(
                original_torrent_path):
            raise Exception("原始种子文件路径无效或文件不存在。")

        # 2. 发布 (传递 torrent_dir 给上传器)
        upload_data["torrent_dir"] = torrent_dir  # 确保上传器能获取到 torrent_dir
        result = migrator.publish_prepared_torrent(upload_data,
                                                   original_torrent_path)

        # 3. 如果发布成功，自动添加到下载器
        if result.get("success") and result.get("url"):
            auto_add = data.get("auto_add_to_downloader", True)  # 默认自动添加
            print(
                f"[下载器添加] 发布成功, auto_add={auto_add}, url={result.get('url')}")

            if auto_add:
                # 先获取配置的默认下载器
                config = config_manager.get()
                default_downloader = config.get("cross_seed",
                                                {}).get("default_downloader")

                # 从请求中获取下载器ID和保存路径
                downloader_id = data.get("downloaderId") or data.get(
                    "downloader_id")
                save_path = upload_data.get("save_path") or upload_data.get(
                    "savePath")
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
                            try:
                                conn = db_manager._get_connection()
                                cursor = db_manager._get_cursor(conn)
                                placeholder = db_manager.get_placeholder()
                                query = f"SELECT save_path FROM seed_parameters WHERE torrent_id = {placeholder} AND site_name = {placeholder}"
                                cursor.execute(
                                    query,
                                    (source_torrent_id, source_site_name))
                                row = cursor.fetchone()
                                if row and row['save_path']:
                                    save_path = row['save_path']
                                    print(f"[下载器添加] 从数据库获取到保存路径: {save_path}")
                                else:
                                    print(f"[下载器添加] 数据库中未找到保存路径")
                                conn.close()
                            except Exception as e:
                                print(f"[下载器添加] 从数据库查询保存路径失败: {e}")
                else:
                    # 配置为"使用源种子所在的下载器"或未配置
                    # 尝试从数据库查询原始种子的下载器和保存路径
                    print(f"[下载器添加] 配置为使用源种子下载器,从数据库查询")
                    source_torrent_id = context.get("source_torrent_id")
                    if source_torrent_id and source_site_name:
                        try:
                            conn = db_manager._get_connection()
                            cursor = db_manager._get_cursor(conn)

                            # 使用 db_manager 的占位符方法
                            placeholder = db_manager.get_placeholder()
                            query = f"SELECT downloader_id, save_path FROM seed_parameters WHERE torrent_id = {placeholder} AND site_name = {placeholder}"

                            cursor.execute(
                                query, (source_torrent_id, source_site_name))
                            row = cursor.fetchone()
                            if row:
                                downloader_id = row['downloader_id']
                                # 同时获取 save_path
                                if not save_path and row['save_path']:
                                    save_path = row['save_path']
                                    print(f"[下载器添加] 从数据库获取到保存路径: {save_path}")
                                print(
                                    f"[下载器添加] 从数据库获取到源种子的下载器ID: {downloader_id}"
                                )
                            else:
                                print(f"[下载器添加] 数据库中未找到源种子信息")
                            conn.close()
                        except Exception as e:
                            print(f"[下载器添加] 从数据库查询下载器ID失败: {e}")

                    if not downloader_id:
                        print(f"[下载器添加] 未找到源种子的下载器信息")

                # 调用添加到下载器
                if save_path and downloader_id:
                    try:
                        from utils import add_torrent_to_downloader
                        print(
                            f"[下载器添加] 准备调用add_torrent_to_downloader: URL={result['url']}, Path={save_path}, DownloaderID={downloader_id}"
                        )
                        success, message = add_torrent_to_downloader(
                            result["url"], save_path, downloader_id,
                            db_manager, config_manager)
                        result["auto_add_result"] = {
                            "success": success,
                            "message": message
                        }
                        if success:
                            print(f"✅ [下载器添加] 成功: {message}")
                        else:
                            print(f"❌ [下载器添加] 失败: {message}")
                    except Exception as e:
                        print(f"❌ [下载器添加] 异常: {e}")
                        import traceback
                        traceback.print_exc()
                        result["auto_add_result"] = {
                            "success": False,
                            "message": f"添加失败: {str(e)}"
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
                        "message": f"缺少必要参数: {', '.join(missing)}"
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
                    conn = db_manager._get_connection()
                    cursor = db_manager._get_cursor(conn)

                    # 准备记录数据
                    video_size_gb = data.get("video_size_gb")  # Go端可能传递的视频大小
                    status = "success" if result.get("success") else "failed"
                    success_url = result.get("url") if result.get(
                        "success") else None
                    error_detail = result.get(
                        "logs") if not result.get("success") else None

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

                    print(
                        f"[批量转种记录] 准备写入数据库: downloader_result={downloader_result}"
                    )

                    # 直接插入记录(发布的种子不会先被Go端插入,只有过滤的种子才会)
                    if db_manager.db_type == "mysql":
                        insert_sql = """INSERT INTO batch_enhance_records
                                      (batch_id, title, torrent_id, source_site, target_site, progress, video_size_gb, status, success_url, error_detail, downloader_add_result)
                                      VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
                    elif db_manager.db_type == "postgresql":
                        insert_sql = """INSERT INTO batch_enhance_records
                                      (batch_id, title, torrent_id, source_site, target_site, progress, video_size_gb, status, success_url, error_detail, downloader_add_result)
                                      VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
                    else:  # sqlite
                        insert_sql = """INSERT INTO batch_enhance_records
                                      (batch_id, title, torrent_id, source_site, target_site, progress, video_size_gb, status, success_url, error_detail, downloader_add_result)
                                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""

                    print(
                        f"[批量转种记录] 执行SQL插入: batch_id={batch_id}, torrent_id={source_torrent_id}"
                    )
                    cursor.execute(
                        insert_sql,
                        (batch_id, parameters.get("title"),source_torrent_id,
                         data.get("nickname",
                                  source_site_name), target_site_name,
                         data.get("batch_progress"), video_size_gb, status,
                         success_url, error_detail, downloader_result))
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
        if not target_info or not target_info.get("cookie"):
            return (
                jsonify({
                    "success":
                    False,
                    "logs":
                    f"错误：未找到目标站点 '{target_site_name}' 或其缺少 Cookie 配置。",
                }),
                404,
            )

        migrator = TorrentMigrator(source_info,
                                   target_info,
                                   search_term,
                                   config_manager=config_manager,
                                   db_manager=db_manager)
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
    """接收前端发送的失效图片信息或简介重新获取请求。"""
    data = request.json

    media_type = data.get("type")
    source_info = data.get("source_info")
    save_path = data.get("savePath")
    torrent_name = data.get("torrentName")
    downloader_id = data.get("downloaderId")  # 获取下载器ID
    imdb_link = source_info.get("imdb_link", '') if source_info else ''
    douban_link = source_info.get("douban_link", '') if source_info else ''

    logging.info(
        f"收到媒体处理请求 - 类型: {media_type}, "
        f"来源信息: {source_info}，视频路径: {save_path}，种子名称: {torrent_name}, 下载器ID: {downloader_id}"
    )

    if media_type == "screenshot":
        screenshots = upload_data_screenshot(source_info, save_path,
                                             torrent_name, downloader_id)
        return jsonify({"success": True, "screenshots": screenshots}), 200
    elif media_type == "poster":
        status, posters, description, extracted_imdb_link = upload_data_movie_info(
            douban_link, imdb_link)
        if status:
            return jsonify({
                "success": True,
                "posters": posters,
                "extracted_imdb_link": extracted_imdb_link
            }), 200
        else:
            return jsonify({"success": False, "error": posters}), 400
    elif media_type == "intro":
        # 处理简介重新获取请求
        status, posters, description, extracted_imdb_link = upload_data_movie_info(
            douban_link, imdb_link)
        if status:
            return jsonify({
                "success": True,
                "intro": description,
                "extracted_imdb_link": extracted_imdb_link
            }), 200
        else:
            return jsonify({"success": False, "error": description}), 400
    elif media_type == "mediainfo":
        # 处理媒体信息重新获取请求
        from utils.media_helper import upload_data_mediaInfo
        # 获取当前的mediainfo（如果有的话）
        current_mediainfo = data.get("current_mediainfo", "")
        # 调用upload_data_mediaInfo函数重新生成mediainfo，设置force_refresh=True强制重新获取
        new_mediainfo = upload_data_mediaInfo(current_mediainfo,
                                              save_path,
                                              torrent_name=torrent_name,
                                              downloader_id=downloader_id,
                                              force_refresh=True)  # 强制重新获取
        if new_mediainfo:
            return jsonify({"success": True, "mediainfo": new_mediainfo}), 200
        else:
            return jsonify({"success": False, "error": "无法生成媒体信息"}), 400
    else:
        return jsonify({
            "success": False,
            "error": f"不支持的媒体类型: {media_type}"
        }), 400


@migrate_bp.route("/migrate/get_downloader_info", methods=["POST"])
def get_downloader_info():
    """获取种子的下载器信息（用于Go服务查询）"""
    db_manager = migrate_bp.db_manager
    data = request.json

    torrent_id = data.get("torrent_id")
    site_name = data.get("site_name")

    if not torrent_id or not site_name:
        return jsonify({
            "success": False,
            "message": "缺少必要参数: torrent_id 或 site_name"
        }), 400

    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        # 使用 db_manager 的占位符方法
        placeholder = db_manager.get_placeholder()
        query = f"SELECT downloader_id, save_path FROM seed_parameters WHERE torrent_id = {placeholder} AND site_name = {placeholder}"

        cursor.execute(query, (torrent_id, site_name))
        row = cursor.fetchone()
        conn.close()

        if row:
            return jsonify({
                "success": True,
                "downloader_id": row['downloader_id'],
                "save_path": row['save_path']
            })
        else:
            return jsonify({"success": False, "message": "未找到该种子信息"}), 404

    except Exception as e:
        logging.error(f"查询下载器信息失败: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "message": f"数据库查询失败: {str(e)}"
        }), 500


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

        # 从数据库查询所有站点的关键信息，包括英文站点名
        cursor.execute(
            "SELECT nickname, site, cookie, migration FROM sites WHERE nickname IS NOT NULL AND nickname != ''"
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
                                   config_manager=config_manager,
                                   db_manager=db_manager)

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

            # 3. 如果分辨率为空，尝试从MediaInfo中提取分辨率
            resolution_from_title = title_params.get("分辨率")
            if not resolution_from_title or resolution_from_title == "N/A":
                resolution_from_mediainfo = extract_resolution_from_mediainfo(
                    review_data["mediainfo"])
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
                        title_components.append({
                            "key":
                            "分辨率",
                            "value":
                            resolution_from_mediainfo
                        })

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

            # 使用新的Extractor和ParameterMapper来处理参数映射
            source_site_name = context.get("source_site_name", "")

            # 创建一个模拟的HTML soup对象用于提取器
            # 由于我们已经有提取的数据，我们可以创建一个简单的soup对象
            from bs4 import BeautifulSoup
            mock_html = f"<html><body><h1 id='top'>{review_data.get('title', '')}</h1></body></html>"
            mock_soup = BeautifulSoup(mock_html, 'html.parser')

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
                "title_components": title_components
            }

            # 使用ParameterMapper映射参数
            standardized_params = mapper.map_parameters(
                source_site_name, '', extracted_data)

            # 保存参数到文件用于调试
            import os
            tmp_dir = "data/tmp"
            os.makedirs(tmp_dir, exist_ok=True)

            # 保存标准化参数到文件
            with open(os.path.join(tmp_dir, "2.txt"), "w",
                      encoding="utf-8") as f:
                f.write(f"源站点名称: {source_site_name}\n")
                f.write("最终标准化参数（使用新映射系统）:\n")
                for key, value in standardized_params.items():
                    f.write(f"{key}: {value}\n")
                # 添加调试信息
                f.write(f"\n调试信息:\n")
                f.write(
                    f"video_codec值: {standardized_params.get('video_codec', '未找到')}\n"
                )
                f.write(f"codec值: {standardized_params.get('codec', '未找到')}\n")

            # 用于预览显示标准化键对应的内容
            preview_video_codec = standardized_params.get(
                "video_codec", "video.other")
            preview_audio_codec = standardized_params.get(
                "audio_codec", "audio.other")
            preview_medium = standardized_params.get("medium", "medium.other")
            preview_resolution = standardized_params.get(
                "resolution", "resolution.other")
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
                "tags": list(all_tags)
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
        site_configs = {
            row["nickname"]: dict(row)
            for row in cursor.fetchall()
        }

        # 查询所有种子数据
        if db_manager.db_type == "postgresql":
            cursor.execute(
                "SELECT hash, name, save_path, size, progress, state, sites, \"group\", details, downloader_id FROM torrents WHERE state != %s",
                ("不存在", ))
        else:
            cursor.execute(
                "SELECT hash, name, save_path, size, progress, state, sites, `group`, details, downloader_id FROM torrents WHERE state != %s",
                ("不存在", ))
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
            })

        for t in torrents_raw:
            torrent_key = t['name']
            agg = agg_torrents[torrent_key]
            if not agg["name"]:
                agg.update({
                    "name": t["name"],
                    "save_path": t.get("save_path", ""),
                    "size": t.get("size", 0),
                })
            downloader_id = t.get("downloader_id")
            if downloader_id and downloader_id not in agg["downloader_ids"]:
                agg["downloader_ids"].append(downloader_id)
            agg["progress"] = max(agg.get("progress", 0), t.get("progress", 0))
            agg["state"].add(t.get("state", "N/A"))
            if t.get("sites"):
                site_name = t.get("sites")
                agg["sites"][site_name]["comment"] = t.get("details")
                agg["sites"][site_name]["state"] = t.get("state", "N/A")
                agg["sites"][site_name]["migration"] = site_configs.get(
                    site_name, {}).get("migration", 0)

        # 转换为列表并应用筛选
        filtered_list = []
        for name, data in agg_torrents.items():
            # 排除已在 seed_parameters 表中存在的种子
            # 去除 .torrent 后缀进行匹配
            name_without_ext = name
            if name_without_ext.lower().endswith('.torrent'):
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
                if not any(did in downloader_filters
                           for did in data.get("downloader_ids", [])):
                    continue

            data.update({
                "state": state_str,
                "sites": dict(data["sites"])  # 转换为普通字典
            })
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

        return jsonify({
            "success": True,
            "data": paginated_list,
            "total": total
        })

    except Exception as e:
        logging.error(f"get_aggregated_torrents 发生错误: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "message": f"服务器内部错误: {str(e)}"
        }), 500


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
            return jsonify({
                "success": False,
                "message": "错误：请先在设置中配置源站点优先级"
            }), 400

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
            "results": []
        }

        # 在后台线程中执行批量获取
        from threading import Thread
        thread = Thread(target=_process_batch_fetch,
                        args=(task_id, torrent_names, source_sites_priority,
                              db_manager))
        thread.daemon = True
        thread.start()

        return jsonify({
            "success": True,
            "task_id": task_id,
            "message": "批量获取任务已启动"
        })

    except Exception as e:
        logging.error(f"batch_fetch_seed_data 发生错误: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "message": f"服务器内部错误: {str(e)}"
        }), 500


def _process_batch_fetch(task_id, torrent_names, source_sites_priority,
                         db_manager):
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

                if db_manager.db_type == "postgresql":
                    cursor.execute(
                        "SELECT hash, name, save_path, sites, details FROM torrents WHERE name = %s AND state != %s",
                        (torrent_name, "不存在"))
                else:
                    cursor.execute(
                        "SELECT hash, name, save_path, sites, details FROM torrents WHERE name = ? AND state != ?",
                        (torrent_name, "不存在"))

                torrents = [dict(row) for row in cursor.fetchall()]
                cursor.close()
                conn.close()

                if not torrents:
                    BATCH_FETCH_TASKS[task_id]["results"].append({
                        "name":
                        torrent_name,
                        "status":
                        "skipped",
                        "reason":
                        "未找到种子记录"
                    })
                    BATCH_FETCH_TASKS[task_id]["skipped"] += 1
                    BATCH_FETCH_TASKS[task_id]["processed"] += 1
                    continue

                # 按优先级查找可用的源站点
                source_found = None
                for priority_site in source_sites_priority:
                    # 获取站点信息
                    source_info = db_manager.get_site_by_nickname(
                        priority_site)
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
                                id_match = re.search(r'id=(\d+)', comment)
                                if id_match:
                                    torrent_id = id_match.group(1)
                                elif re.match(r'^\d+$', comment.strip()):
                                    torrent_id = comment.strip()

                            if torrent_id:
                                source_found = {
                                    "site": priority_site,
                                    "site_info": source_info,
                                    "torrent_id": torrent_id,
                                    "torrent": torrent
                                }
                                break

                    if source_found:
                        break

                if not source_found:
                    BATCH_FETCH_TASKS[task_id]["results"].append({
                        "name":
                        torrent_name,
                        "status":
                        "failed",
                        "reason":
                        "未找到可用的源站点"
                    })
                    BATCH_FETCH_TASKS[task_id]["failed"] += 1
                    BATCH_FETCH_TASKS[task_id]["processed"] += 1
                    continue

                # 获取种子数据
                try:
                    # 检查该站点的最后请求时间，如果间隔不足则等待
                    current_site = source_found["site"]
                    if current_site in site_last_request_time:
                        elapsed = time.time(
                        ) - site_last_request_time[current_site]
                        if elapsed < REQUEST_INTERVAL:
                            wait_time = REQUEST_INTERVAL - elapsed
                            logging.info(
                                f"站点 {current_site} 请求间隔不足，等待 {wait_time:.1f} 秒..."
                            )
                            time.sleep(wait_time)

                    # 记录本次请求时间
                    site_last_request_time[current_site] = time.time()

                    migrator = TorrentMigrator(
                        source_site_info=source_found["site_info"],
                        target_site_info=None,
                        search_term=source_found["torrent_id"],
                        save_path=source_found["torrent"].get("save_path", ""),
                        torrent_name=torrent_name,
                        config_manager=config_manager,
                        db_manager=db_manager)

                    result = migrator.prepare_review_data()

                    if "review_data" in result:
                        BATCH_FETCH_TASKS[task_id]["results"].append({
                            "name":
                            torrent_name,
                            "status":
                            "success",
                            "source_site":
                            source_found["site"]
                        })
                        BATCH_FETCH_TASKS[task_id]["success"] += 1
                        logging.info(
                            f"批量获取成功: {torrent_name} from {source_found['site']}"
                        )
                    else:
                        BATCH_FETCH_TASKS[task_id]["results"].append({
                            "name":
                            torrent_name,
                            "status":
                            "failed",
                            "reason":
                            result.get("logs", "未知错误")
                        })
                        BATCH_FETCH_TASKS[task_id]["failed"] += 1

                except Exception as e:
                    BATCH_FETCH_TASKS[task_id]["results"].append({
                        "name":
                        torrent_name,
                        "status":
                        "failed",
                        "reason":
                        str(e)
                    })
                    BATCH_FETCH_TASKS[task_id]["failed"] += 1
                    logging.error(f"批量获取失败: {torrent_name}, 错误: {e}")

                BATCH_FETCH_TASKS[task_id]["processed"] += 1

            except Exception as e:
                BATCH_FETCH_TASKS[task_id]["results"].append({
                    "name": torrent_name,
                    "status": "failed",
                    "reason": str(e)
                })
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
        return jsonify({
            "success": False,
            "message": f"服务器内部错误: {str(e)}"
        }), 500
