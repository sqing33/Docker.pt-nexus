# server/api/routes_cross_seed_data.py
from flask import Blueprint, jsonify, current_app, request
import logging
import yaml
import os

# 创建蓝图
cross_seed_data_bp = Blueprint('cross_seed_data', __name__)


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


@cross_seed_data_bp.route('/api/cross-seed-data', methods=['GET'])
def get_cross_seed_data():
    """获取seed_parameters表中的所有数据（支持分页和搜索）"""
    try:
        # 获取分页参数
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 20))
        search_query = request.args.get('search', '').strip()

        # 限制页面大小
        page_size = min(page_size, 100)

        # 计算偏移量
        offset = (page - 1) * page_size

        # 获取数据库管理器
        db_manager = current_app.config['DB_MANAGER']
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        # 构建查询条件
        where_clause = ""
        params = []
        if search_query:
            if db_manager.db_type == "postgresql":
                where_clause = "WHERE title ILIKE %s OR torrent_id ILIKE %s"
                params = [f"%{search_query}%", f"%{search_query}%"]
            else:
                where_clause = "WHERE title LIKE ? OR torrent_id LIKE ?"
                params = [f"%{search_query}%", f"%{search_query}%"]

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
                SELECT hash, torrent_id, site_name, nickname, title, subtitle, type, medium, video_codec,
                       audio_codec, resolution, team, source, tags, title_components, updated_at
                FROM seed_parameters
                {where_clause}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """
            cursor.execute(query, params + [page_size, offset])
        else:
            placeholder = "?" if db_manager.db_type == "sqlite" else "%s"
            query = f"""
                SELECT hash, torrent_id, site_name, nickname, title, subtitle, type, medium, video_codec,
                       audio_codec, resolution, team, source, tags, title_components, updated_at
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
                    if isinstance(component, dict) and component.get('key') == '无法识别':
                        unrecognized_value = component.get('value', '')
                        break

            # Add unrecognized field to item
            item['unrecognized'] = unrecognized_value

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
            "reverse_mappings": reverse_mappings
        })
    except Exception as e:
        logging.error(f"获取转种数据时出错: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
