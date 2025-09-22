# api/routes_migrate.py

import logging
import uuid
import re
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

                return jsonify({
                    "success": True,
                    "data": parameters,
                    "source": "database",
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
        return jsonify({"success": False, "message": f"服务器内部错误: {str(e)}"}), 500


def generate_reverse_mappings():
    """生成从标准键到中文显示名称的反向映射"""
    try:
        # 读取全局映射配置
        import yaml
        import os

        # 首先尝试从global_mappings.yaml读取
        global_mappings_path = os.path.join(os.path.dirname(__file__), '../configs/global_mappings.yaml')
        global_mappings = {}

        if os.path.exists(global_mappings_path):
            try:
                with open(global_mappings_path, 'r', encoding='utf-8') as f:
                    config_data = yaml.safe_load(f)
                    global_mappings = config_data.get('global_standard_keys', {})
                logging.info(f"成功从global_mappings.yaml读取配置，包含{len(global_mappings)}个类别")
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
        reverse_mappings['team'].update({
            'team.other': '其他'
        })

    if not reverse_mappings['tags']:
        logging.warning("tags映射为空，添加基础后备映射")
        reverse_mappings['tags'].update({
            'tag.DIY': 'DIY',
            'tag.中字': '中字',
            'tag.HDR': 'HDR',
            'tag.官种': '官种',
            'tag.首发': '首发'
        })




# 新增：专门负责数据抓取和存储的API接口
@migrate_bp.route("/migrate/fetch_and_store", methods=["POST"])
def migrate_fetch_and_store():
    """专门负责种子信息抓取和存储，不返回预览数据"""
    db_manager = migrate_bp.db_manager
    data = request.json
    source_site_name, search_term, save_path = (data.get("sourceSite"),
                                                data.get("searchTerm"),
                                                data.get("savePath", ""))

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
                                   config_manager=config_manager)

        # 调用数据抓取和信息提取（这会自动保存到数据库）
        result = migrator.prepare_review_data()

        if "review_data" in result:
            task_id = str(uuid.uuid4())
            # 只缓存必要信息，包括原始种子路径用于发布
            MIGRATION_CACHE[task_id] = {
                "source_info": source_info,
                "original_torrent_path": result["original_torrent_path"],
                "source_site_name": english_site_name,  # 使用英文站点名作为唯一标识符
                "source_torrent_id": search_term,
            }

            logging.info(f"种子信息抓取并存储成功: {search_term} from {source_site_name} ({english_site_name})")
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
                "success": False,
                "message": "错误：缺少必要参数（torrent_id、site_name、updated_parameters）"
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
                english_site_name = site_mapping.get(site_name, site_name.lower())

            logging.info(f"开始更新种子参数: {torrent_id} from {site_name} ({english_site_name})")

            # 检查用户是否提供了修改的标准参数
            user_standardized_params = updated_parameters.get('standardized_params', {})

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
                    'title': updated_parameters.get('title', ''),
                    'subtitle': updated_parameters.get('subtitle', ''),
                    'imdb_link': updated_parameters.get('imdb_link', ''),
                    'douban_link': updated_parameters.get('douban_link', ''),
                    'intro': {
                        'statement': updated_parameters.get('statement', ''),
                        'poster': updated_parameters.get('poster', ''),
                        'body': updated_parameters.get('body', ''),
                        'screenshots': updated_parameters.get('screenshots', ''),
                        'imdb_link': updated_parameters.get('imdb_link', ''),
                        'douban_link': updated_parameters.get('douban_link', '')
                    },
                    'mediainfo': updated_parameters.get('mediainfo', ''),
                    'source_params': updated_parameters.get('source_params', {}),
                    'title_components': updated_parameters.get('title_components', [])
                }

                # 使用ParameterMapper重新标准化参数
                from core.extractors.extractor import ParameterMapper
                mapper = ParameterMapper()

                # 重新标准化参数
                standardized_params = mapper.map_parameters(site_name, english_site_name, extracted_data)

            # 保存标准化后的参数到数据库
            # 从title_components中提取标题拆解的各项参数
            title_components = updated_parameters.get('title_components', [])

            # 构造完整的存储参数
            final_parameters = {
                "title": updated_parameters.get('title', ''),
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

                # 保存完整的标题组件数据
                "title_components": title_components,

                # 添加标准化后的参数
                "standardized_params": standardized_params,
                "final_publish_parameters": {
                    "主标题 (预览)": standardized_params.get("title", ""),
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
                    "title_components": updated_parameters.get('title_components', []),
                    "subtitle": updated_parameters.get('subtitle', ''),
                    "imdb_link": standardized_params.get("imdb_link", ""),
                    "douban_link": standardized_params.get("douban_link", ""),
                    "intro": {
                        "statement": updated_parameters.get('statement', ''),
                        "poster": updated_parameters.get('poster', ''),
                        "body": updated_parameters.get('body', ''),
                        "screenshots": updated_parameters.get('screenshots', ''),
                        "removed_ardtudeclarations": updated_parameters.get('removed_ardtudeclarations', []),
                        "imdb_link": updated_parameters.get('imdb_link', ''),
                        "douban_link": updated_parameters.get('douban_link', '')
                    },
                    "mediainfo": updated_parameters.get('mediainfo', ''),
                    "source_params": updated_parameters.get('source_params', {}),
                    "standardized_params": standardized_params
                },
                "raw_params_for_preview": {
                    "final_main_title": standardized_params.get("title", ""),
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

            update_result = seed_param_model.update_parameters(torrent_id, english_site_name, final_parameters)

            if update_result:
                logging.info(f"种子参数更新成功: {torrent_id} from {site_name} ({english_site_name})")

                # 生成反向映射表（从标准键到中文显示名称的映射）
                reverse_mappings = generate_reverse_mappings()

                return jsonify({
                    "success": True,
                    "standardized_params": standardized_params,
                    "final_publish_parameters": final_parameters["final_publish_parameters"],
                    "complete_publish_params": final_parameters["complete_publish_params"],
                    "raw_params_for_preview": final_parameters["raw_params_for_preview"],
                    "reverse_mappings": reverse_mappings,
                    "message": "参数更新并标准化成功"
                })
            else:
                logging.warning(f"种子参数更新失败: {torrent_id} from {site_name} ({english_site_name})")
                return jsonify({
                    "success": False,
                    "message": "参数更新失败"
                }), 500

        except Exception as e:
            logging.error(f"更新种子参数失败: {e}", exc_info=True)
            return jsonify({
                "success": False,
                "message": f"更新失败: {str(e)}"
            }), 500

    except Exception as e:
        logging.error(f"update_db_seed_info发生意外错误: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"服务器内部错误: {str(e)}"}), 500


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
        with flask_request._fake_request('/api/migrate/fetch_and_store', 'POST', data=json.dumps(store_data),
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
        parameters = seed_param_model.get_parameters(search_term, source_site_name)

        if parameters:
            task_id = store_response_data.get("task_id")

            # 缓存必要信息用于发布
            MIGRATION_CACHE[task_id] = {
                "source_info": db_manager.get_site_by_nickname(source_site_name),
                "original_torrent_path": None,  # 将在发布时重新获取
                "source_site_name": source_site_name,
                "source_torrent_id": search_term,
            }

            # 构造兼容原有格式的响应
            return jsonify({
                "success": True,
                "task_id": task_id,
                "data": {
                    "original_main_title": parameters.get("title", ""),
                    "title_components": parameters.get("title_components", []),
                    "subtitle": parameters.get("subtitle", ""),
                    "imdb_link": parameters.get("imdb_link", ""),
                    "douban_link": parameters.get("douban_link", ""),
                    "intro": {
                        "statement": parameters.get("statement", ""),
                        "poster": parameters.get("poster", ""),
                        "body": parameters.get("body", ""),
                        "screenshots": parameters.get("screenshots", ""),
                        "removed_ardtudeclarations": parameters.get("removed_ardtudeclarations", []),
                        "imdb_link": parameters.get("imdb_link", ""),
                        "douban_link": parameters.get("douban_link", "")
                    },
                    "mediainfo": parameters.get("mediainfo", ""),
                    "source_params": parameters.get("source_params", {}),
                    "standardized_params": parameters.get("standardized_params", {}),
                    "final_publish_parameters": parameters.get("final_publish_parameters", {}),
                    "complete_publish_params": parameters.get("complete_publish_params", {}),
                    "raw_params_for_preview": parameters.get("raw_params_for_preview", {}),
                },
                "logs": store_response_data.get("logs", "")
            })
        else:
            return jsonify({
                "success": False,
                "logs": "数据抓取成功但从数据库读取失败"
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
        # 修复：添加缺失的search_term和save_path参数
        migrator = TorrentMigrator(source_info,
                                   target_info,
                                   search_term=context.get(
                                       "source_torrent_id", ""),
                                   save_path=upload_data.get("save_path", "")
                                   or upload_data.get("savePath", ""),
                                   config_manager=config_manager)

        # 使用特殊提取器处理数据（如果需要）
        source_torrent_id = context.get("source_torrent_id", "unknown")
        print(
            f"在publish阶段处理数据，源站点: {source_site_name}, 种子ID: {source_torrent_id}"
        )
        print(
            f"调用apply_special_extractor_if_needed前，upload_data中的mediainfo长度: {len(upload_data.get('mediainfo', '')) if upload_data.get('mediainfo') else 0}"
        )
        upload_data = migrator.apply_special_extractor_if_needed(
            upload_data, source_torrent_id)
        print(f"publish阶段数据处理完成")
        print(
            f"调用apply_special_extractor_if_needed后，upload_data中的mediainfo长度: {len(upload_data.get('mediainfo', '')) if upload_data.get('mediainfo') else 0}"
        )

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
    """接收前端发送的失效图片信息或简介重新获取请求。"""
    data = request.json

    media_type = data.get("type")
    source_info = data.get("source_info")
    save_path = data.get("savePath")
    torrent_name = data.get("torrentName")
    imdb_link = source_info.get("imdb_link", '') if source_info else ''
    douban_link = source_info.get("douban_link", '') if source_info else ''

    logging.info(
        f"收到媒体处理请求 - 类型: {media_type}, "
        f"来源信息: {source_info}，视频路径: {save_path}，种子名称: {torrent_name}")

    if media_type == "screenshot":
        screenshots = upload_data_screenshot(source_info, save_path,
                                             torrent_name)
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
    else:
        return jsonify({"success": False, "error": f"不支持的媒体类型: {media_type}"}), 400


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
