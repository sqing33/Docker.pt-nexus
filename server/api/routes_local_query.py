import logging
import os
from pathlib import Path
from flask import Blueprint, jsonify
from collections import defaultdict
from config import config_manager

logger = logging.getLogger(__name__)

local_query_bp = Blueprint("local_query_api",
                           __name__,
                           url_prefix="/api/local_query")

# --- 依赖注入占位符 ---
# db_manager = None


def get_downloader_name_from_config(downloader_id):
    """从配置文件中获取下载器名称"""
    try:
        config = config_manager.get()
        downloaders = config.get("downloaders", [])
        for dl in downloaders:
            if dl.get("id") == downloader_id:
                return dl.get("name", "未知")
        return "未知"
    except Exception as e:
        logger.error(f"从配置获取下载器名称失败: {str(e)}")
        return "未知"


@local_query_bp.route("/paths", methods=["GET"])
def get_paths():
    """获取数据库中所有唯一的保存路径"""
    try:
        db_manager = local_query_bp.db_manager
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        cursor.execute("""
            SELECT DISTINCT save_path
            FROM torrents
            WHERE save_path IS NOT NULL AND TRIM(save_path) != ''
            ORDER BY save_path
        """)

        rows = cursor.fetchall()
        paths = [
            row['save_path'] if isinstance(row, dict) else row[0]
            for row in rows
        ]

        conn.close()

        return jsonify({"paths": paths, "total": len(paths)})
    except Exception as e:
        logger.error(f"获取路径列表失败: {str(e)}")
        return jsonify({"error": str(e)}), 500


@local_query_bp.route("/downloaders_with_paths", methods=["GET"])
def get_downloaders_with_paths():
    """按下载器分组显示路径"""
    try:
        db_manager = local_query_bp.db_manager
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        cursor.execute("SELECT id, name FROM downloader_clients ORDER BY id")
        downloaders = cursor.fetchall()

        result = []
        for downloader in downloaders:
            downloader_id = downloader['id'] if isinstance(
                downloader, dict) else downloader[0]
            downloader_name = downloader['name'] if isinstance(
                downloader, dict) else downloader[1]

            ph = db_manager.get_placeholder()
            cursor.execute(
                f"""
                SELECT save_path, COUNT(*) as torrent_count
                FROM torrents
                WHERE downloader_id = {ph} AND save_path IS NOT NULL AND TRIM(save_path) != ''
                GROUP BY save_path ORDER BY save_path
            """, (downloader_id, ))

            paths_data = cursor.fetchall()
            paths = [{
                "path": row['save_path'],
                "count": row['torrent_count']
            } if isinstance(row, dict) else {
                "path": row[0],
                "count": row[1]
            } for row in paths_data]

            if paths:
                result.append({
                    "id": downloader_id,
                    "name": downloader_name,
                    "paths": paths
                })

        conn.close()
        return jsonify({"downloaders": result})
    except Exception as e:
        logger.error(f"获取下载器路径统计失败: {str(e)}")
        return jsonify({"error": str(e)}), 500


@local_query_bp.route("/scan", methods=["POST"])
def scan_local_files():
    """
    [最终版-已修正] 扫描所有路径，对比种子与本地文件。
    - 缺失文件：返回极简聚合信息。
    - 孤立文件和正常同步：逻辑已恢复。
    """
    try:
        db_manager = local_query_bp.db_manager
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        # 1. 查询所有需要扫描的种子数据 (已简化)
        cursor.execute("""
            SELECT t.name, t.save_path, t.size, t.downloader_id
            FROM torrents t
            WHERE t.save_path IS NOT NULL AND TRIM(t.save_path) != ''
        """)
        torrents = cursor.fetchall()
        conn.close()

        # 2. 按 save_path 进行初次分组
        torrents_by_path = defaultdict(list)
        for torrent in torrents:
            row_data = dict(torrent)
            # 从配置文件获取下载器名称
            row_data["downloader_name"] = get_downloader_name_from_config(
                row_data.get("downloader_id")
            )
            torrents_by_path[row_data['save_path']].append(row_data)

        # 3. 初始化扫描结果
        missing_files = []
        orphaned_files = []
        synced_torrents = []
        total_local_items = 0
        total_torrents_count = len(torrents)

        # 4. 遍历每个路径进行扫描
        for save_path, path_torrents in torrents_by_path.items():
            if not os.path.exists(save_path):
                missing_groups_by_name = defaultdict(list)
                for torrent in path_torrents:
                    missing_groups_by_name[torrent['name']].append(torrent)

                for name, torrent_group in missing_groups_by_name.items():
                    # 使用第一个种子的信息
                    first_torrent = torrent_group[0]
                    missing_files.append({
                        "name": name,
                        "save_path": save_path,
                        "expected_path": os.path.join(save_path, name),
                        "size": first_torrent.get('size') or 0,
                        "downloader_name": first_torrent.get('downloader_name', '未知')
                    })
                continue

            try:
                local_items = set(os.listdir(save_path))
                total_local_items += len(local_items)

                torrents_by_name_in_path = defaultdict(list)
                for torrent in path_torrents:
                    torrents_by_name_in_path[torrent['name']].append(torrent)

                torrent_names_in_path = set(torrents_by_name_in_path.keys())

                # 找出缺失的文件组
                missing_names = torrent_names_in_path - local_items
                for name in missing_names:
                    torrent_group = torrents_by_name_in_path[name]
                    # 使用第一个种子的信息
                    first_torrent = torrent_group[0]
                    missing_files.append({
                        "name": name,
                        "save_path": save_path,
                        "expected_path": os.path.join(save_path, name),
                        "size": first_torrent.get('size') or 0,
                        "downloader_name": first_torrent.get('downloader_name', '未知')
                    })

                # --- CORRECTED-LOGIC-START: 恢复孤立文件和同步文件的检索逻辑 ---

                # 找出孤立的文件 (名字在本地有，但数据库没有)
                orphaned_names = local_items - torrent_names_in_path
                for item_name in orphaned_names:
                    full_path = os.path.join(save_path, item_name)
                    is_file = os.path.isfile(full_path)
                    size = None
                    try:
                        if is_file:
                            size = os.path.getsize(full_path)
                        else:  # 文件夹大小计算
                            size = sum(f.stat().st_size
                                       for f in Path(full_path).glob('**/*')
                                       if f.is_file())
                    except Exception as e:
                        logger.debug(f"无法获取大小 {full_path}: {str(e)}")

                    orphaned_files.append({
                        "name": item_name,
                        "path": save_path,
                        "full_path": full_path,
                        "is_file": is_file,
                        "size": size
                    })

                # 找出正常同步的文件组 (两边都有)
                synced_names = local_items & torrent_names_in_path
                for name in synced_names:
                    torrent_group = torrents_by_name_in_path[name]
                    synced_torrents.append({
                        "name":
                        name,
                        "path":
                        save_path,
                        "torrents_count":
                        len(torrent_group),
                        "downloader_names":
                        list(set(t["downloader_name"] for t in torrent_group))
                    })

                # --- CORRECTED-LOGIC-END ---

            except Exception as e:
                logger.error(f"扫描路径 {save_path} 时出错: {str(e)}")

        # 5. 统计信息
        scan_summary = {
            "total_torrents": total_torrents_count,
            "total_local_items": total_local_items,
            "missing_count": len(missing_files),
            "orphaned_count": len(orphaned_files),
            "synced_count": len(synced_torrents)
        }

        return jsonify({
            "scan_summary": scan_summary,
            "missing_files": missing_files,
            "orphaned_files": orphaned_files,
            "synced_torrents": synced_torrents
        })

    except Exception as e:
        logger.error(f"扫描失败: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@local_query_bp.route("/analyze_duplicates", methods=["GET"])
def analyze_duplicates():
    """查找同名种子（可能在不同下载器/路径）"""
    try:
        db_manager = local_query_bp.db_manager
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        # 查找重复的种子名称
        cursor.execute("""
            SELECT name, COUNT(*) as count
            FROM torrents
            WHERE name IS NOT NULL AND TRIM(name) != ''
            GROUP BY name
            HAVING count > 1
            ORDER BY count DESC
        """)
        duplicate_names = cursor.fetchall()

        duplicates = []
        total_wasted_space = 0

        for dup_row in duplicate_names:
            name, count = dict(dup_row).get('name'), dict(dup_row).get('count')

            ph = db_manager.get_placeholder()
            cursor.execute(
                f"""
                SELECT t.hash, t.save_path, t.size, t.downloader_id
                FROM torrents t
                WHERE t.name = {ph}
            """, (name, ))
            instances = [dict(row) for row in cursor.fetchall()]

            locations = [{
                "hash": inst['hash'],
                "downloader_name": get_downloader_name_from_config(inst.get('downloader_id')),
                "path": inst.get('save_path') or "未知"
            } for inst in instances]

            total_size = sum(inst.get('size') or 0 for inst in instances)

            # 假设副本中至少有一个是有效存储，浪费的空间是其他副本的大小总和
            # 如果大小都一样，浪费空间 = (n-1) * size
            # 如果大小不一样，为简化计算，我们假设最大的那个是保留的，其余是浪费的
            sizes = [inst.get('size') or 0 for inst in instances]
            wasted = total_size - (max(sizes) if sizes else 0)
            total_wasted_space += wasted

            duplicates.append({
                "name": name,
                "count": count,
                "locations": locations,
                "total_size": total_size,
                "wasted_size": wasted
            })

        conn.close()

        return jsonify({
            "duplicates": duplicates,
            "total_duplicates": len(duplicates),
            "wasted_space": total_wasted_space
        })

    except Exception as e:
        logger.error(f"分析重复种子失败: {str(e)}")
        return jsonify({"error": str(e)}), 500
