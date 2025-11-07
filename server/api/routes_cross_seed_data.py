# server/api/routes_cross_seed_data.py
from flask import Blueprint, jsonify, current_app, request
import logging
import yaml
import os
import time
import json
from datetime import datetime, timedelta

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
            unique_paths = [
                row['save_path'] for row in rows if row['save_path']
            ]
        else:
            # MySQL和SQLite返回的是元组列表
            unique_paths = [row[0] for row in rows if row[0]]

        cursor.close()
        conn.close()

        return jsonify({"success": True, "unique_paths": unique_paths})
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
        exclude_target_sites_filter = request.args.get('exclude_target_sites',
                                                       '').strip()

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
                    "(title ILIKE %s OR torrent_id ILIKE %s OR subtitle ILIKE %s)"
                )
                params.extend([
                    f"%{search_query}%", f"%{search_query}%",
                    f"%{search_query}%"
                ])
            else:
                where_conditions.append(
                    "(title LIKE ? OR torrent_id LIKE ? OR subtitle LIKE ?)")
                params.extend([
                    f"%{search_query}%", f"%{search_query}%",
                    f"%{search_query}%"
                ])

        # 保存路径筛选条件 - 支持多个路径筛选（精确匹配）
        if save_path_filter:
            # 将逗号分隔的路径转换为列表
            paths = [
                path.strip() for path in save_path_filter.split(',')
                if path.strip()
            ]
            if paths:
                if db_manager.db_type == "postgresql":
                    # PostgreSQL 使用 ANY 操作符进行精确匹配
                    placeholders = ', '.join(['%s'] * len(paths))
                    where_conditions.append(
                        f"save_path = ANY(ARRAY[{placeholders}])")
                    params.extend(paths)
                else:
                    # MySQL 和 SQLite 使用 IN 操作符进行精确匹配
                    placeholders = ', '.join(
                        ['%s' if db_manager.db_type == "mysql" else '?'] *
                        len(paths))
                    where_conditions.append(f"save_path IN ({placeholders})")
                    params.extend(paths)

        # 删除状态筛选条件
        if is_deleted_filter in ['0', '1']:
            if db_manager.db_type == "postgresql":
                # PostgreSQL handles boolean differently - convert '1' to True, '0' to False
                bool_value = True if is_deleted_filter == '1' else False
                where_conditions.append("is_deleted = %s")
                params.append(bool_value)
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
                    where_conditions.append(
                        f"seed_parameters.hash NOT IN ({subquery})")
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
                    where_conditions.append(
                        f"seed_parameters.hash NOT IN ({subquery})")
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
                       audio_codec, resolution, team, source, tags, title_components, is_deleted, is_reviewed, updated_at
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
                       audio_codec, resolution, team, source, tags, title_components, is_deleted, is_reviewed, updated_at
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

            # Ensure is_deleted field is boolean for consistent frontend handling
            # MySQL/SQLite return integers (0/1), PostgreSQL returns booleans (false/true)
            if 'is_deleted' in item:
                if isinstance(item['is_deleted'], int):
                    item['is_deleted'] = bool(item['is_deleted'])
                # PostgreSQL already returns boolean, no conversion needed

            # Ensure is_reviewed field is boolean for consistent frontend handling
            # MySQL/SQLite return integers (0/1), PostgreSQL returns booleans (false/true)
            if 'is_reviewed' in item:
                if isinstance(item['is_reviewed'], int):
                    item['is_reviewed'] = bool(item['is_reviewed'])
                # PostgreSQL already returns boolean, no conversion needed

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
        cursor.execute(
            "SELECT nickname FROM sites WHERE migration IN (2, 3) ORDER BY nickname"
        )
        target_sites_rows = cursor.fetchall()
        if isinstance(target_sites_rows, list):
            # PostgreSQL返回的是字典列表
            target_sites_list = [
                row['nickname'] for row in target_sites_rows if row['nickname']
            ]
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
            unique_paths = [
                row['save_path'] for row in path_rows if row['save_path']
            ]
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


@cross_seed_data_bp.route('/cross-seed-data/test-no-auth',
                          methods=['POST', 'GET'])
def test_no_auth():
    """测试无认证端点"""
    return jsonify({
        "success": True,
        "message": "无认证测试成功",
        "timestamp": str(time.time())
    })


@cross_seed_data_bp.route('/cross-seed-data/delete',
                          methods=['DELETE', 'POST'])
def delete_cross_seed_data():
    """统一的删除API - 支持单个删除和批量删除"""
    cursor = None
    conn = None
    try:
        data = request.get_json()
        print(data)

        # 判断是批量删除还是单个删除
        if data and 'items' in data:
            # 批量删除
            items = data['items']
            if not isinstance(items, list):
                return jsonify({"success": False, "error": "items 必须是数组"}), 400

            if not items:
                return jsonify({"success": False, "error": "项目列表不能为空"}), 400

            # 获取数据库管理器
            db_manager = current_app.config['DB_MANAGER']
            conn = db_manager._get_connection()
            cursor = db_manager._get_cursor(conn)

            deleted_count = 0

            # 处理每个要删除的项目
            for item in items:
                if 'torrent_id' not in item or 'site_name' not in item:
                    logging.warning(f"缺少必要的参数: {item}")
                    continue

                torrent_id = item['torrent_id']
                site_name = item['site_name']

                # 执行删除
                if db_manager.db_type == "sqlite":
                    delete_query = "DELETE FROM seed_parameters WHERE torrent_id = ? AND site_name = ?"
                    print(delete_query, (torrent_id, site_name))
                    cursor.execute(delete_query, (torrent_id, site_name))
                else:  # postgresql
                    delete_query = "DELETE FROM seed_parameters WHERE torrent_id = %s AND site_name = %s"
                    print(delete_query, (torrent_id, site_name))
                    cursor.execute(delete_query, (torrent_id, site_name))

                deleted_count += 1

            conn.commit()

            return jsonify({
                "success": True,
                "message": f"成功删除 {deleted_count} 条数据",
                "deleted_count": deleted_count
            })

        elif data and 'torrent_id' in data and 'site_name' in data:
            # 单个删除
            torrent_id = data['torrent_id']
            site_name = data['site_name']

            # 获取数据库管理器
            db_manager = current_app.config['DB_MANAGER']
            conn = db_manager._get_connection()
            cursor = db_manager._get_cursor(conn)

            # 执行删除
            if db_manager.db_type == "sqlite":
                delete_query = "DELETE FROM seed_parameters WHERE torrent_id = ? AND site_name = ?"
                print(delete_query, (torrent_id, site_name))
                cursor.execute(delete_query, (torrent_id, site_name))
            else:  # postgresql
                delete_query = "DELETE FROM seed_parameters WHERE torrent_id = %s AND site_name = %s"
                print(delete_query, (torrent_id, site_name))
                cursor.execute(delete_query, (torrent_id, site_name))

            conn.commit()

            return jsonify({
                "success": True,
                "message": f"种子数据 {torrent_id} from {site_name} 已删除"
            })

        else:
            return jsonify({
                "success":
                False,
                "error":
                "缺少必需参数: 单个删除需要 torrent_id 和 site_name，批量删除需要 items 数组"
            }), 400

    except Exception as e:
        logging.error(f"删除种子数据时出错: {e}")
        if conn:
            conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# ============= 批量转种记录API =============


@cross_seed_data_bp.route('/batch-enhance/records', methods=['POST'])
def add_batch_enhance_record():
    """添加批量转种记录（给Go服务调用）"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "缺少请求数据"}), 400

        # 验证必需字段
        required_fields = [
            'batch_id', 'torrent_id', 'source_site', 'target_site', 'status'
        ]
        for field in required_fields:
            if field not in data:
                return jsonify({
                    "success": False,
                    "error": f"缺少必需字段: {field}"
                }), 400

        # 获取数据库管理器
        db_manager = current_app.config['DB_MANAGER']
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        # ✨ START: 修改SQL语句，增加 title 列
        if db_manager.db_type in ["mysql", "postgresql"]:
            sql = """INSERT INTO batch_enhance_records
                     (batch_id, torrent_id, title, source_site, target_site, video_size_gb, status, success_url, error_detail, downloader_add_result)
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
        else:  # sqlite
            sql = """INSERT INTO batch_enhance_records
                     (batch_id, torrent_id, title, source_site, target_site, video_size_gb, status, success_url, error_detail, downloader_add_result)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        # ✨ END: 修改SQL语句

        # ✨ START: 修改参数元组，增加 title 的值
        params = (
            data['batch_id'],
            data['torrent_id'],
            data.get('title'),  # 从请求数据中获取 title
            data['source_site'],
            data['target_site'],
            data.get('video_size_gb'),
            data['status'],
            data.get('success_url'),
            data.get('error_detail'),
            data.get('downloader_add_result'))
        # ✨ END: 修改参数元组

        cursor.execute(sql, params)
        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({"success": True, "message": "记录添加成功"})

    except Exception as e:
        logging.error(f"添加批量转种记录时出错: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@cross_seed_data_bp.route('/batch-enhance/records', methods=['GET'])
def get_batch_enhance_records():
    """获取批量转种记录（给前端调用）"""
    try:
        # 获取查询参数
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 50))
        status = request.args.get('status', '').strip()
        batch_id = request.args.get('batch_id', '').strip()
        search = request.args.get('search', '').strip()
        start_time = request.args.get('start_time', '').strip()
        end_time = request.args.get('end_time', '').strip()

        # 限制页面大小
        page_size = min(page_size, 200)
        offset = (page - 1) * page_size

        # 获取数据库管理器
        db_manager = current_app.config['DB_MANAGER']
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        # 构建查询条件
        where_conditions = []
        params = []

        # 状态筛选
        if status:
            if db_manager.db_type == "postgresql":
                where_conditions.append("status = %s")
            else:
                where_conditions.append("status = ?")
            params.append(status)

        # 批次ID筛选
        if batch_id:
            if db_manager.db_type == "postgresql":
                where_conditions.append("batch_id = %s")
            else:
                where_conditions.append("batch_id = ?")
            params.append(batch_id)

        # 搜索条件
        if search:
            if db_manager.db_type == "postgresql":
                where_conditions.append(
                    "(torrent_id ILIKE %s OR source_site ILIKE %s OR target_site ILIKE %s)"
                )
                params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
            else:
                where_conditions.append(
                    "(torrent_id LIKE ? OR source_site LIKE ? OR target_site LIKE ?)"
                )
                params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

        # 时间范围筛选
        if start_time:
            try:
                start_dt = datetime.fromisoformat(
                    start_time.replace('Z', '+00:00'))
                if db_manager.db_type == "postgresql":
                    where_conditions.append("processed_at >= %s")
                else:
                    where_conditions.append("processed_at >= ?")
                params.append(start_dt)
            except ValueError:
                pass

        if end_time:
            try:
                end_dt = datetime.fromisoformat(end_time.replace(
                    'Z', '+00:00'))
                if db_manager.db_type == "postgresql":
                    where_conditions.append("processed_at <= %s")
                else:
                    where_conditions.append("processed_at <= ?")
                params.append(end_dt)
            except ValueError:
                pass

        # 组合WHERE子句
        where_clause = ""
        if where_conditions:
            where_clause = "WHERE " + " AND ".join(where_conditions)

        # 查询总数
        count_query = f"SELECT COUNT(*) as total FROM batch_enhance_records {where_clause}"
        cursor.execute(count_query, params)
        total_result = cursor.fetchone()
        total_count = total_result[0] if isinstance(
            total_result, tuple) else total_result['total']

        # 查询数据
        if db_manager.db_type == "postgresql":
            query = f"""
                SELECT id, title, batch_id, torrent_id, source_site, target_site, video_size_gb, status, success_url, error_detail, downloader_add_result, processed_at, progress
                FROM batch_enhance_records
                {where_clause}
                ORDER BY processed_at DESC
                LIMIT %s OFFSET %s
            """
            cursor.execute(query, params + [page_size, offset])
        else:
            placeholder = "?" if db_manager.db_type == "sqlite" else "%s"
            query = f"""
                SELECT id, title, batch_id, torrent_id, source_site, target_site, video_size_gb, status, success_url, error_detail, downloader_add_result, processed_at, progress
                FROM batch_enhance_records
                {where_clause}
                ORDER BY processed_at DESC
                LIMIT {placeholder} OFFSET {placeholder}
            """
            cursor.execute(query, params + [page_size, offset])

        rows = cursor.fetchall()

        # 转换结果为字典列表
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            # PostgreSQL返回字典列表
            records = [dict(row) for row in rows]
        else:
            # MySQL和SQLite返回元组列表
            columns = [desc[0] for desc in cursor.description]
            records = [dict(zip(columns, row)) for row in rows]

        # 获取所有唯一的批次ID（用于前端筛选）
        batch_query = "SELECT DISTINCT batch_id FROM batch_enhance_records ORDER BY batch_id DESC LIMIT 100"
        cursor.execute(batch_query)
        batch_rows = cursor.fetchall()
        if isinstance(batch_rows, list) and batch_rows and isinstance(
                batch_rows[0], dict):
            batch_ids = [row['batch_id'] for row in batch_rows]
        else:
            batch_ids = [row[0] for row in batch_rows]

        cursor.close()
        conn.close()

        return jsonify({
            "success": True,
            "records": records,
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "batch_ids": batch_ids
        })

    except Exception as e:
        logging.error(f"获取批量转种记录时出错: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@cross_seed_data_bp.route('/batch-enhance/records', methods=['DELETE'])
def clear_batch_enhance_records():
    """清空批量转种记录（给前端调用）"""
    try:
        # 获取数据库管理器
        db_manager = current_app.config['DB_MANAGER']
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        # 清空记录表
        cursor.execute("DELETE FROM batch_enhance_records")
        deleted_count = cursor.rowcount
        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({
            "success": True,
            "message": f"记录已清空，删除了 {deleted_count} 条记录"
        })

    except Exception as e:
        logging.error(f"清空批量转种记录时出错: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@cross_seed_data_bp.route('/batch-enhance/records/batch/<batch_id>',
                          methods=['DELETE'])
def clear_batch_records_by_id(batch_id):
    """根据批次ID清空特定批次的记录"""
    try:
        # 获取数据库管理器
        db_manager = current_app.config['DB_MANAGER']
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        # 删除指定批次的记录
        if db_manager.db_type == "postgresql":
            cursor.execute(
                "DELETE FROM batch_enhance_records WHERE batch_id = %s",
                (batch_id, ))
        else:
            cursor.execute(
                "DELETE FROM batch_enhance_records WHERE batch_id = ?",
                (batch_id, ))

        deleted_count = cursor.rowcount
        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({
            "success":
            True,
            "message":
            f"批次 {batch_id} 的记录已清空，删除了 {deleted_count} 条记录"
        })

    except Exception as e:
        logging.error(f"清空批次记录时出错: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
