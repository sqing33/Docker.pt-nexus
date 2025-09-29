# server/api/routes_cross_seed_data.py
from flask import Blueprint, jsonify, current_app, request
import logging
import yaml
import os
import time

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
        exclude_target_sites_filter = request.args.get('exclude_target_sites', '').strip()

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

        # 目标站点排除筛选条件
        if exclude_target_sites_filter:
            # 现在是单选，不需要分割逗号
            exclude_site = exclude_target_sites_filter.strip()
            if exclude_site:
                logging.info(f"排除目标站点筛选: {exclude_site}")

                # 构建子查询：
                # 1. 从torrents表中找到在指定站点存在的种子名称
                # 2. 然后找到这些种子名称对应的hash
                # 3. 最后排除seed_parameters表中具有这些hash的记录
                if db_manager.db_type == "postgresql":
                    subquery = f"""
                        SELECT DISTINCT sp.hash
                        FROM seed_parameters sp
                        WHERE sp.hash IN (
                            SELECT DISTINCT t1.hash
                            FROM torrents t1
                            WHERE t1.name IN (
                                SELECT DISTINCT t2.name
                                FROM torrents t2
                                WHERE t2.sites = %s
                            )
                        )
                    """
                    where_conditions.append(f"seed_parameters.hash NOT IN ({subquery})")
                    params.append(exclude_site)
                else:
                    # MySQL 和 SQLite
                    placeholder = '%s' if db_manager.db_type == "mysql" else '?'
                    subquery = f"""
                        SELECT DISTINCT sp.hash
                        FROM seed_parameters sp
                        WHERE sp.hash IN (
                            SELECT DISTINCT t1.hash
                            FROM torrents t1
                            WHERE t1.name IN (
                                SELECT DISTINCT t2.name
                                FROM torrents t2
                                WHERE t2.sites = {placeholder}
                            )
                        )
                    """
                    where_conditions.append(f"seed_parameters.hash NOT IN ({subquery})")
                    params.append(exclude_site)

                logging.info(f"排除子查询SQL: {subquery}")
                logging.info(f"排除站点参数: {exclude_site}")

        # 组合WHERE子句
        where_clause = ""
        if where_conditions:
            where_clause = "WHERE " + " AND ".join(where_conditions)

        # 记录完整的SQL查询用于调试
        if exclude_target_sites_filter:
            logging.info(f"完整WHERE子句: {where_clause}")
            logging.info(f"所有查询参数: {params}")

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

        # 获取所有目标站点（用于前端筛选选项）
        cursor.execute("SELECT nickname FROM sites WHERE migration IN (2, 3) ORDER BY nickname")
        target_sites_rows = cursor.fetchall()
        if isinstance(target_sites_rows, list):
            # PostgreSQL返回的是字典列表
            target_sites_list = [row['nickname'] for row in target_sites_rows if row['nickname']]
        else:
            # MySQL和SQLite返回的是元组列表
            target_sites_list = [row[0] for row in target_sites_rows if row[0]]

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
            "unique_paths": unique_paths,  # 添加唯一路径数据
            "target_sites": target_sites_list  # 添加目标站点列表
        })
    except Exception as e:
        logging.error(f"获取转种数据时出错: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@cross_seed_data_bp.route('/cross-seed-data/test-no-auth', methods=['POST', 'GET'])
def test_no_auth():
    """测试无认证端点"""
    return jsonify({
        "success": True,
        "message": "无认证测试成功",
        "timestamp": str(time.time())
    })

