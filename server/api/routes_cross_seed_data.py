# server/api/routes_cross_seed_data.py
from flask import Blueprint, jsonify, current_app, request
import logging
import yaml
import os

# 创建蓝图
cross_seed_data_bp = Blueprint('cross_seed_data', __name__, url_prefix="/api")


def generate_reverse_mappings():
    """Generate reverse mappings from standard keys to Chinese display names"""
    try:
        # Import config_manager
        from config import config_manager

        # First try to read from global_mappings.yaml
        global_mappings_path = os.path.join(os.path.dirname(__file__),
                                            '../configs/global_mappings.yaml')
        global_mappings = {}

        if os.path.exists(global_mappings_path):
            try:
                with open(global_mappings_path, 'r', encoding='utf-8') as f:
                    config_data = yaml.safe_load(f)
                    global_mappings = config_data.get('global_standard_keys',
                                                      {})
            except Exception as e:
                logging.warning(f"Failed to read global_mappings.yaml: {e}")

        # If YAML file read fails, get from config manager
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

        # Mapping categories
        categories_mapping = {
            'type': global_mappings.get('type', {}),
            'medium': global_mappings.get('medium', {}),
            'video_codec': global_mappings.get('video_codec', {}),
            'audio_codec': global_mappings.get('audio_codec', {}),
            'resolution': global_mappings.get('resolution', {}),
            'source': global_mappings.get('source', {}),
            'team': global_mappings.get('team', {}),
            'tags': global_mappings.get('tag',
                                        {})  # Note: YAML uses 'tag' not 'tags'
        }

        # Create reverse mappings: from standard value to Chinese name
        for category, mappings in categories_mapping.items():
            if category == 'tags':
                # Special handling for tags, extract Chinese name as key, standard value as value
                for chinese_name, standard_value in mappings.items():
                    if standard_value:  # Filter out null values
                        reverse_mappings['tags'][standard_value] = chinese_name
            else:
                # Normal handling for other categories
                for chinese_name, standard_value in mappings.items():
                    if standard_value and standard_value not in reverse_mappings[
                            category]:
                        reverse_mappings[category][
                            standard_value] = chinese_name

        return reverse_mappings

    except Exception as e:
        logging.error(f"Failed to generate reverse mappings: {e}",
                      exc_info=True)
        # Return empty reverse mappings as fallback
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


@cross_seed_data_bp.route('/cross-seed-data/unique-paths', methods=['GET'])
def get_unique_save_paths():
    """获取seed_parameters表中所有唯一的保存路径"""
    try:
        # 获取数据库管理器
        db_manager = current_app.config['DB_MANAGER']
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        # 查询所有唯一的保存路径
        if db_manager.db_type == "postgresql":
            query = "SELECT DISTINCT save_path FROM seed_parameters WHERE save_path IS NOT NULL AND save_path != '' ORDER BY save_path"
            cursor.execute(query)
        else:
            query = "SELECT DISTINCT save_path FROM seed_parameters WHERE save_path IS NOT NULL AND save_path != '' ORDER BY save_path"
            cursor.execute(query)

        rows = cursor.fetchall()

        # 将结果转换为列表
        if isinstance(rows, list):
            # PostgreSQL返回的是字典列表
            unique_paths = [row['save_path'] for row in rows if row['save_path']]
        else:
            # MySQL和SQLite返回的是元组列表
            unique_paths = [row[0] for row in rows if row[0]]

        cursor.close()
        conn.close()

        return jsonify({
            "success": True,
            "unique_paths": unique_paths
        })
    except Exception as e:
        logging.error(f"获取唯一保存路径时出错: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@cross_seed_data_bp.route('/cross-seed-data', methods=['GET'])
def get_cross_seed_data():
    """获取seed_parameters表中的所有数据（支持分页和搜索）"""
    try:
        # 获取分页参数
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 20))
        search_query = request.args.get('search', '').strip()

        # 获取筛选参数
        save_path_filter = request.args.get('save_path', '').strip()
        is_deleted_filter = request.args.get('is_deleted', '').strip()

        # 限制页面大小
        page_size = min(page_size, 100)

        # 计算偏移量
        offset = (page - 1) * page_size

        # 获取数据库管理器
        db_manager = current_app.config['DB_MANAGER']
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        # 构建查询条件
        where_conditions = []
        params = []

        # 搜索查询条件
        if search_query:
            if db_manager.db_type == "postgresql":
                where_conditions.append(
                    "(title ILIKE %s OR torrent_id ILIKE %s OR subtitle ILIKE %s)")
                params.extend([f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"])
            else:
                where_conditions.append("(title LIKE ? OR torrent_id LIKE ? OR subtitle LIKE ?)")
                params.extend([f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"])

        # 保存路径筛选条件 - 支持多个路径筛选
        if save_path_filter:
            # 将逗号分隔的路径转换为列表
            paths = [path.strip() for path in save_path_filter.split(',') if path.strip()]
            if paths:
                if db_manager.db_type == "postgresql":
                    # PostgreSQL 使用 ANY 操作符
                    placeholders = ', '.join(['%s'] * len(paths))
                    where_conditions.append(f"save_path = ANY(ARRAY[{placeholders}])")
                    params.extend(paths)
                else:
                    # MySQL 和 SQLite 使用 IN 操作符
                    placeholders = ', '.join(['%s' if db_manager.db_type == "mysql" else '?'] * len(paths))
                    where_conditions.append(f"save_path IN ({placeholders})")
                    params.extend(paths)

        # 删除状态筛选条件
        if is_deleted_filter in ['0', '1']:
            if db_manager.db_type == "postgresql":
                where_conditions.append("is_deleted = %s")
            else:
                where_conditions.append("is_deleted = ?")
            params.append(int(is_deleted_filter))

        # 组合WHERE子句
        where_clause = ""
        if where_conditions:
            where_clause = "WHERE " + " AND ".join(where_conditions)

        # 先查询总数
        count_query = f"SELECT COUNT(*) as total FROM seed_parameters {where_clause}"
        if db_manager.db_type == "postgresql":
            cursor.execute(count_query, params)
        else:
            cursor.execute(count_query, params)
        total_result = cursor.fetchone()
        total_count = total_result[0] if isinstance(
            total_result, tuple) else total_result['total']

        # 查询当前页的数据，只获取前端需要显示的列
        if db_manager.db_type == "postgresql":
            query = f"""
                SELECT hash, torrent_id, site_name, nickname, save_path, title, subtitle, type, medium, video_codec,
                       audio_codec, resolution, team, source, tags, title_components, is_deleted, updated_at
                FROM seed_parameters
                {where_clause}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """
            cursor.execute(query, params + [page_size, offset])
        else:
            placeholder = "?" if db_manager.db_type == "sqlite" else "%s"
            query = f"""
                SELECT hash, torrent_id, site_name, nickname, save_path, title, subtitle, type, medium, video_codec,
                       audio_codec, resolution, team, source, tags, title_components, is_deleted, updated_at
                FROM seed_parameters
                {where_clause}
                ORDER BY created_at DESC
                LIMIT {placeholder} OFFSET {placeholder}
            """
            cursor.execute(query, params + [page_size, offset])

        rows = cursor.fetchall()

        # 将结果转换为字典列表
        if isinstance(rows, list):
            # PostgreSQL返回的是字典列表
            data = [dict(row) for row in rows]
        else:
            # MySQL和SQLite返回的是元组列表，需要手动转换
            columns = [desc[0] for desc in cursor.description]
            data = [dict(zip(columns, row)) for row in rows]

        # Process tags data to ensure it's in the correct format
        for item in data:
            tags = item.get('tags', [])
            if isinstance(tags, str):
                try:
                    # Try to parse as JSON list
                    import json
                    tags = json.loads(tags)
                except:
                    # If parsing fails, split by comma
                    tags = [tag.strip()
                            for tag in tags.split(',')] if tags else []
                item['tags'] = tags

            # Extract "无法识别" field from title_components
            title_components = item.get('title_components', [])
            unrecognized_value = ''
            if isinstance(title_components, str):
                try:
                    # Try to parse as JSON list
                    import json
                    title_components = json.loads(title_components)
                except:
                    # If parsing fails, keep as is
                    title_components = []

            # Find the "无法识别" entry in title_components
            if isinstance(title_components, list):
                for component in title_components:
                    if isinstance(component,
                                  dict) and component.get('key') == '无法识别':
                        unrecognized_value = component.get('value', '')
                        break

            # Add unrecognized field to item
            item['unrecognized'] = unrecognized_value

        # 获取所有唯一的保存路径（用于路径树）
        if db_manager.db_type == "postgresql":
            path_query = "SELECT DISTINCT save_path FROM seed_parameters WHERE save_path IS NOT NULL AND save_path != '' ORDER BY save_path"
            cursor.execute(path_query)
        else:
            path_query = "SELECT DISTINCT save_path FROM seed_parameters WHERE save_path IS NOT NULL AND save_path != '' ORDER BY save_path"
            cursor.execute(path_query)

        path_rows = cursor.fetchall()

        # 将结果转换为列表
        if isinstance(path_rows, list):
            # PostgreSQL返回的是字典列表
            unique_paths = [row['save_path'] for row in path_rows if row['save_path']]
        else:
            # MySQL和SQLite返回的是元组列表
            unique_paths = [row[0] for row in path_rows if row[0]]

        cursor.close()
        conn.close()

        # Generate reverse mappings
        reverse_mappings = generate_reverse_mappings()

        return jsonify({
            "success": True,
            "data": data,
            "count": len(data),
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "reverse_mappings": reverse_mappings,
            "unique_paths": unique_paths  # 添加唯一路径数据
        })
    except Exception as e:
        logging.error(f"获取转种数据时出错: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@cross_seed_data_bp.route('/cross-seed-data/batch-cross-seed', methods=['POST'])
def batch_cross_seed():
    """处理批量转种请求"""
    try:
        # 获取JSON数据
        data = request.get_json()

        # 提取目标站点名称和种子列表
        target_site_name = data.get('target_site_name')
        seeds = data.get('seeds', [])

        if not target_site_name:
            return jsonify({"success": False, "error": "目标站点名称不能为空"}), 400

        if not seeds:
            return jsonify({"success": False, "error": "种子列表不能为空"}), 400

        # 获取数据库管理器
        db_manager = current_app.config['DB_MANAGER']

        # 获取目标站点信息
        target_site_info = db_manager.get_site_by_nickname(target_site_name)
        if not target_site_info or not target_site_info.get("passkey"):
            return jsonify({
                "success": False,
                "error": f"目标站点 '{target_site_name}' 配置不完整或缺少Passkey"
            }), 404

        # 导入必要的模块
        from core.migrator import TorrentMigrator
        from models.seed_parameter import SeedParameter
        import os
        from config import config_manager

        # 处理每个种子
        processed_seeds = []
        failed_seeds = []

        for seed in seeds:
            try:
                hash_value = seed.get('hash')
                torrent_id = seed.get('torrent_id')
                site_name = seed.get('site_name')

                if not all([hash_value, torrent_id, site_name]):
                    failed_seeds.append({
                        "torrent_id": torrent_id or "未知",
                        "error": "缺少必要的种子信息"
                    })
                    continue

                # 从数据库获取种子详细信息
                conn = db_manager._get_connection()
                cursor = db_manager._get_cursor(conn)

                try:
                    # 查询种子参数
                    if db_manager.db_type == "postgresql":
                        query = """
                            SELECT * FROM seed_parameters
                            WHERE hash = %s AND torrent_id = %s AND site_name = %s
                        """
                    else:
                        placeholder = "?" if db_manager.db_type == "sqlite" else "%s"
                        query = f"""
                            SELECT * FROM seed_parameters
                            WHERE hash = {placeholder} AND torrent_id = {placeholder} AND site_name = {placeholder}
                        """

                    cursor.execute(query, (hash_value, torrent_id, site_name))
                    seed_data = cursor.fetchone()

                    if not seed_data:
                        failed_seeds.append({
                            "torrent_id": torrent_id,
                            "error": "在数据库中未找到种子信息"
                        })
                        continue

                    # 将seed_data转换为字典（如果需要）
                    if not isinstance(seed_data, dict):
                        columns = [desc[0] for desc in cursor.description]
                        seed_data = dict(zip(columns, seed_data))

                    # 获取源站点信息
                    source_site_info = db_manager.get_site_by_nickname(site_name)
                    if not source_site_info:
                        failed_seeds.append({
                            "torrent_id": torrent_id,
                            "error": f"源站点 '{site_name}' 信息未找到"
                        })
                        continue

                    # 创建种子参数模型
                    seed_param_model = SeedParameter(db_manager)

                    # 获取种子参数
                    parameters = seed_param_model.get_parameters(torrent_id, site_name)
                    if not parameters:
                        failed_seeds.append({
                            "torrent_id": torrent_id,
                            "error": "无法获取种子参数"
                        })
                        continue

                    # 创建TorrentMigrator实例
                    migrator = TorrentMigrator(
                        source_site_info=source_site_info,
                        target_site_info=target_site_info,
                        search_term=torrent_id,
                        save_path=parameters.get("save_path", ""),
                        torrent_name=parameters.get("title", ""),
                        config_manager=config_manager
                    )

                    # 准备上传数据
                    upload_data = {
                        "title": parameters.get("title", ""),
                        "subtitle": parameters.get("subtitle", ""),
                        "imdb_link": parameters.get("imdb_link", ""),
                        "douban_link": parameters.get("douban_link", ""),
                        "intro": {
                            "statement": parameters.get("statement", ""),
                            "poster": parameters.get("poster", ""),
                            "body": parameters.get("body", ""),
                            "screenshots": parameters.get("screenshots", "")
                        },
                        "mediainfo": parameters.get("mediainfo", ""),
                        "source_params": {
                            "类型": parameters.get("type", ""),
                            "媒介": parameters.get("medium", ""),
                            "视频编码": parameters.get("video_codec", ""),
                            "音频编码": parameters.get("audio_codec", ""),
                            "分辨率": parameters.get("resolution", ""),
                            "制作组": parameters.get("team", ""),
                            "产地": parameters.get("source", ""),
                            "标签": parameters.get("tags", [])
                        },
                        "title_components": parameters.get("title_components", []),
                        "standardized_params": {
                            "title": parameters.get("title", ""),
                            "subtitle": parameters.get("subtitle", ""),
                            "imdb_link": parameters.get("imdb_link", ""),
                            "douban_link": parameters.get("douban_link", ""),
                            "type": parameters.get("type", ""),
                            "medium": parameters.get("medium", ""),
                            "video_codec": parameters.get("video_codec", ""),
                            "audio_codec": parameters.get("audio_codec", ""),
                            "resolution": parameters.get("resolution", ""),
                            "team": parameters.get("team", ""),
                            "source": parameters.get("source", ""),
                            "tags": parameters.get("tags", [])
                        }
                    }

                    # 创建临时目录用于存储种子文件
                    import tempfile
                    import shutil
                    temp_dir = tempfile.mkdtemp()

                    try:
                        # 1. 创建以种子标题命名的目录
                        from config import TEMP_DIR
                        import re
                        original_main_title = parameters.get("title", "")
                        safe_filename_base = re.sub(r'[\\/*?:"<>|]', "_", original_main_title)[:150]
                        torrent_dir = os.path.join(TEMP_DIR, safe_filename_base)
                        os.makedirs(torrent_dir, exist_ok=True)

                        # 2. 从源站点下载原始种子文件到指定目录
                        original_torrent_path = migrator._download_torrent_file(torrent_id, torrent_dir)

                        if not original_torrent_path or not os.path.exists(original_torrent_path):
                            failed_seeds.append({
                                "torrent_id": torrent_id,
                                "error": "无法从源站点下载种子文件"
                            })
                            continue

                        # 3. 直接使用原始种子文件进行发布（不再修改种子）
                        # 传递 torrent_dir 给上传器以确保参数文件保存在同一目录
                        upload_data["torrent_dir"] = torrent_dir
                        result = migrator.publish_prepared_torrent(upload_data, original_torrent_path)
                    finally:
                        # 清理临时目录
                        if os.path.exists(temp_dir):
                            shutil.rmtree(temp_dir)

                    if result.get("success"):
                        processed_seeds.append({
                            "torrent_id": torrent_id,
                            "title": parameters.get("title", ""),
                            "status": "success",
                            "url": result.get("url", "")
                        })
                    else:
                        failed_seeds.append({
                            "torrent_id": torrent_id,
                            "error": result.get("logs", "发布失败")
                        })

                finally:
                    cursor.close()
                    conn.close()

            except Exception as e:
                failed_seeds.append({
                    "torrent_id": seed.get("torrent_id", "未知"),
                    "error": str(e)
                })
                logging.error(f"处理种子 {seed.get('torrent_id')} 时出错: {e}")

        return jsonify({
            "success": True,
            "message": f"批量转种请求已处理，成功 {len(processed_seeds)} 个，失败 {len(failed_seeds)} 个",
            "data": {
                "target_site_name": target_site_name,
                "seeds_processed": len(processed_seeds),
                "seeds_failed": len(failed_seeds),
                "processed_seeds": processed_seeds,
                "failed_seeds": failed_seeds
            }
        })
    except Exception as e:
        logging.error(f"处理批量转种请求时出错: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
