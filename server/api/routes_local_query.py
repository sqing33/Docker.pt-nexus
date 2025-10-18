import logging
import os
import json
from pathlib import Path
from flask import Blueprint, jsonify
from collections import defaultdict
from config import config_manager, DATA_DIR
from utils.media_helper import _get_downloader_proxy_config
import requests

logger = logging.getLogger(__name__)

local_query_bp = Blueprint("local_query_api",
                           __name__,
                           url_prefix="/api/local_query")

# 缓存文件路径
SCAN_CACHE_FILE = os.path.join(DATA_DIR, "local_scan_cache.json")

# --- 依赖注入占位符 ---
# db_manager = None


def save_scan_cache(scan_result):
    """保存扫描结果到缓存文件"""
    try:
        with open(SCAN_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(scan_result, f, ensure_ascii=False, indent=2)
        logger.info(f"扫描结果已保存到缓存: {SCAN_CACHE_FILE}")
    except Exception as e:
        logger.error(f"保存扫描缓存失败: {str(e)}")


def load_scan_cache():
    """从缓存文件读取扫描结果"""
    try:
        if os.path.exists(SCAN_CACHE_FILE):
            with open(SCAN_CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            logger.info(f"从缓存加载扫描结果: {SCAN_CACHE_FILE}")
            return data
        return None
    except Exception as e:
        logger.error(f"加载扫描缓存失败: {str(e)}")
        return None


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


def check_remote_file_exists(proxy_config, remote_path):
    """
    通过代理检查远程文件是否存在

    :param proxy_config: 代理配置字典，包含 proxy_base_url
    :param remote_path: 远程路径
    :return: (exists, is_file, size) 元组
    """
    try:
        response = requests.post(
            f"{proxy_config['proxy_base_url']}/api/file/check",
            json={"remote_path": remote_path},
            timeout=30)
        response.raise_for_status()
        result = response.json()

        if result.get("success"):
            exists = result.get("exists", False)
            is_file = result.get("is_file", False)
            size = result.get("size", 0)
            return exists, is_file, size
        else:
            logger.error(f"代理文件检查失败: {result.get('message', '未知错误')}")
            return False, False, 0
    except Exception as e:
        logger.error(f"调用代理检查文件失败: {e}")
        return False, False, 0


def batch_check_remote_files(proxy_config, remote_paths):
    """
    通过代理批量检查远程文件是否存在

    :param proxy_config: 代理配置字典，包含 proxy_base_url
    :param remote_paths: 远程路径列表
    :return: 字典 {path: (exists, is_file, size)}
    """
    if not remote_paths:
        return {}

    try:
        response = requests.post(
            f"{proxy_config['proxy_base_url']}/api/file/batch-check",
            json={"remote_paths": remote_paths},
            timeout=180  # 批量检查可能需要更长时间
        )
        response.raise_for_status()
        result = response.json()

        if result.get("success"):
            results_dict = {}
            for item in result.get("results", []):
                path = item.get("path")
                exists = item.get("exists", False)
                is_file = item.get("is_file", False)
                size = item.get("size", 0)
                results_dict[path] = (exists, is_file, size)
            return results_dict
        else:
            logger.error(f"代理批量文件检查失败: {result.get('message', '未知错误')}")
            return {}
    except Exception as e:
        logger.error(f"调用代理批量检查文件失败: {e}")
        return {}


@local_query_bp.route("/scan/cache", methods=["GET"])
def get_scan_cache():
    """获取上次扫描的缓存结果"""
    try:
        cached_result = load_scan_cache()
        if cached_result:
            return jsonify(cached_result)
        else:
            return jsonify({"error": "No cached scan result"}), 404
    except Exception as e:
        logger.error(f"获取扫描缓存失败: {str(e)}")
        return jsonify({"error": str(e)}), 500


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
    """按下载器分组显示路径（从配置文件获取下载器信息）"""
    try:
        # 从配置文件获取下载器列表
        config = config_manager.get()
        downloaders_config = config.get("downloaders", [])

        if not downloaders_config:
            return jsonify({"downloaders": []})

        db_manager = local_query_bp.db_manager
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        result = []
        for downloader in downloaders_config:
            downloader_id = downloader.get("id")
            downloader_name = downloader.get("name", "未知")
            path_mappings = downloader.get("path_mappings", [])

            # 查询该下载器的所有唯一路径
            ph = db_manager.get_placeholder()
            cursor.execute(
                f"""
                SELECT save_path, COUNT(*) as torrent_count
                FROM torrents
                WHERE downloader_id = {ph} AND save_path IS NOT NULL AND TRIM(save_path) != ''
                GROUP BY save_path ORDER BY save_path
            """, (downloader_id, ))

            paths_data = cursor.fetchall()
            paths_set = {}  # 使用字典来合并相同路径的计数

            # 处理原始路径
            for row in paths_data:
                save_path = row['save_path'] if isinstance(row,
                                                           dict) else row[0]
                count = row['torrent_count'] if isinstance(row,
                                                           dict) else row[1]

                # 原始路径
                if save_path not in paths_set:
                    paths_set[save_path] = 0
                paths_set[save_path] += count

                # 应用路径映射，生成映射后的路径
                # 从本地路径映射到远程路径，用于补充筛选选项
                for mapping in path_mappings:
                    remote = mapping.get("remote", "").rstrip("/")
                    local = mapping.get("local", "").rstrip("/")
                    if remote and local:
                        # 确保完整匹配路径段，避免 /pt 匹配 /pt2
                        if save_path == local or save_path.startswith(local +
                                                                      "/"):
                            # 将本地路径映射到远程路径
                            mapped_path = save_path.replace(local, remote, 1)
                            if mapped_path not in paths_set:
                                paths_set[mapped_path] = 0
                            paths_set[mapped_path] += count

            # 转换为列表格式
            paths = [{
                "path": path,
                "count": count
            } for path, count in sorted(paths_set.items())]

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
    - 缺失文件:返回极简聚合信息。
    - 孤立文件和正常同步：逻辑已恢复。
    - 支持通过查询参数 path 指定要扫描的特定路径
    - 应用路径映射，将远程路径转换为本地可访问路径
    - 判断下载器是否为远程，远程下载器跳过本地文件检查
    - **优化：检测并扫描所有路径映射中的目录，即使数据库中没有对应种子**
    """
    from flask import request

    # 获取查询参数中的路径
    target_path = request.args.get('path', None)

    try:
        # 从配置文件获取下载器路径映射
        config = config_manager.get()
        downloaders_config = config.get("downloaders", [])
        path_mappings_by_downloader = {}
        remote_downloaders = set()  # 存储使用代理的远程下载器ID

        for dl in downloaders_config:
            dl_id = dl.get("id")
            path_mappings_by_downloader[dl_id] = dl.get("path_mappings", [])
            # 使用已有的函数判断是否为远程下载器
            proxy_config = _get_downloader_proxy_config(dl_id)
            if proxy_config:
                remote_downloaders.add(dl_id)
                logger.info(
                    f"下载器 {dl.get('name')} (ID: {dl_id}) 使用代理，将跳过本地文件检查")
            print(
                f"[DEBUG] 下载器: {dl.get('name')} (ID: {dl_id}), 远程: {dl_id in remote_downloaders}, 映射数: {len(dl.get('path_mappings', []))}"
            )

        db_manager = local_query_bp.db_manager
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        # 1. 查询所有需要扫描的种子数据
        if target_path:
            # 如果指定了路径，只查询该路径下的种子
            ph = db_manager.get_placeholder()
            cursor.execute(
                f"""
                SELECT t.name, t.save_path, t.size, t.downloader_id
                FROM torrents t
                WHERE t.save_path = {ph}
            """, (target_path, ))
        else:
            # 否则查询所有路径
            cursor.execute("""
                SELECT t.name, t.save_path, t.size, t.downloader_id
                FROM torrents t
                WHERE t.save_path IS NOT NULL AND TRIM(t.save_path) != ''
            """)
        torrents = cursor.fetchall()
        conn.close()

        # 辅助函数：应用路径映射
        def apply_path_mapping(remote_path, downloader_id):
            """将远程路径映射为本地路径"""
            mappings = path_mappings_by_downloader.get(downloader_id, [])
            print(
                f"[DEBUG] apply_path_mapping: 远程路径={remote_path}, 下载器ID={downloader_id}, 映射规则数={len(mappings)}"
            )
            for mapping in mappings:
                remote = mapping.get("remote", "").rstrip("/")
                local = mapping.get("local", "").rstrip("/")
                print(f"[DEBUG]   检查映射: remote={remote}, local={local}")
                if remote and local:
                    # 确保完整匹配路径段，避免 /pt 匹配 /pt2
                    if remote_path == remote or remote_path.startswith(remote +
                                                                       "/"):
                        mapped = remote_path.replace(remote, local, 1)
                        print(f"[DEBUG]   ✓ 匹配成功! 映射后={mapped}")
                        return mapped
            print(f"[DEBUG]   ✗ 无匹配映射，返回原路径={remote_path}")
            return remote_path  # 如果没有匹配的映射，返回原路径

        # 2. 按 save_path 进行初次分组，并应用路径映射
        # 分别处理本地和远程下载器
        local_torrents_by_path = defaultdict(list)
        remote_torrents_by_path = defaultdict(list)

        for torrent in torrents:
            row_data = dict(torrent)
            downloader_id = row_data.get("downloader_id")
            # 从配置文件获取下载器名称
            row_data["downloader_name"] = get_downloader_name_from_config(
                downloader_id)

            # 判断是否为远程下载器
            is_remote = downloader_id in remote_downloaders

            if is_remote:
                # 远程下载器：不进行路径映射，直接使用原路径
                original_path = row_data['save_path']
                row_data['is_remote'] = True
                remote_torrents_by_path[original_path].append(row_data)
                print(
                    f"[DEBUG] 远程种子: {row_data['name'][:50]} | 路径: {original_path}"
                )
            else:
                # 本地下载器：应用路径映射
                original_path = row_data['save_path']
                mapped_path = apply_path_mapping(original_path, downloader_id)
                row_data['local_path'] = mapped_path  # 保存映射后的本地路径
                row_data['is_remote'] = False
                local_torrents_by_path[mapped_path].append(row_data)
                print(
                    f"[DEBUG] 本地种子: {row_data['name'][:50]} | 原始: {original_path} | 映射: {mapped_path}"
                )

        # 3. 初始化扫描结果
        missing_files = []
        orphaned_files = []
        synced_torrents = []
        total_local_items = 0
        total_torrents_count = len(torrents)
        remote_torrents_count = sum(
            len(torrents) for torrents in remote_torrents_by_path.values())

        # 3.5. 收集所有应该扫描的本地路径（包括映射中配置的但数据库中没有种子的路径）
        all_local_paths_to_scan = set(local_torrents_by_path.keys())

        # 遍历所有下载器的路径映射，添加本地路径到扫描列表
        for downloader_id, mappings in path_mappings_by_downloader.items():
            # 跳过远程下载器
            if downloader_id in remote_downloaders:
                continue

            for mapping in mappings:
                local_root = mapping.get("local", "").rstrip("/")
                if local_root and os.path.exists(local_root):
                    # 如果指定了target_path，只添加匹配的路径
                    if target_path:
                        # 检查target_path是否在这个映射的远程路径下
                        remote_root = mapping.get("remote", "").rstrip("/")
                        if target_path == remote_root or target_path.startswith(
                                remote_root + "/"):
                            # 将target_path映射到本地路径
                            mapped_local = apply_path_mapping(
                                target_path, downloader_id)
                            if os.path.exists(mapped_local):
                                all_local_paths_to_scan.add(mapped_local)
                    else:
                        # 扫描本地根目录下的所有子目录
                        try:
                            for item in os.listdir(local_root):
                                subdir_path = os.path.join(local_root, item)
                                if os.path.isdir(subdir_path):
                                    all_local_paths_to_scan.add(subdir_path)
                            # 也添加根目录本身
                            all_local_paths_to_scan.add(local_root)
                        except Exception as e:
                            logger.warning(f"无法列出目录 {local_root}: {str(e)}")

        logger.info(f"总共需要扫描 {len(all_local_paths_to_scan)} 个本地路径")

        # 4. 遍历所有路径进行扫描（包括没有种子的路径）
        for local_path in all_local_paths_to_scan:
            path_torrents = local_torrents_by_path.get(local_path, [])
            print(f"[DEBUG] 扫描本地路径: {local_path} | 种子数: {len(path_torrents)}")

            # 如果路径不存在，记录缺失的种子
            if not os.path.exists(local_path):
                print(f"[DEBUG] 路径不存在: {local_path}")
                if path_torrents:  # 只有当有种子记录时才报告缺失
                    missing_groups_by_name = defaultdict(list)
                    for torrent in path_torrents:
                        missing_groups_by_name[torrent['name']].append(torrent)

                    for name, torrent_group in missing_groups_by_name.items():
                        # 使用第一个种子的信息
                        first_torrent = torrent_group[0]
                        missing_files.append({
                            "name":
                            name,
                            "save_path":
                            first_torrent['save_path'],  # 显示原始远程路径
                            "expected_path":
                            os.path.join(local_path, name),
                            "size":
                            first_torrent.get('size') or 0,
                            "downloader_name":
                            first_torrent.get('downloader_name', '未知')
                        })
                continue

            try:
                local_items = set(os.listdir(local_path))
                total_local_items += len(local_items)
                print(
                    f"[DEBUG] 路径存在，找到 {len(local_items)} 个项目: {list(local_items)[:3]}..."
                )

                torrents_by_name_in_path = defaultdict(list)
                for torrent in path_torrents:
                    torrents_by_name_in_path[torrent['name']].append(torrent)

                torrent_names_in_path = set(torrents_by_name_in_path.keys())
                print(f"[DEBUG] 期望的种子名称: {list(torrent_names_in_path)[:3]}...")

                # 找出缺失的文件组
                missing_names = torrent_names_in_path - local_items
                print(f"[DEBUG] 缺失的文件: {len(missing_names)} 个")
                for name in missing_names:
                    torrent_group = torrents_by_name_in_path[name]
                    # 使用第一个种子的信息
                    first_torrent = torrent_group[0]
                    missing_files.append({
                        "name":
                        name,
                        "save_path":
                        first_torrent['save_path'],  # 显示原始远程路径
                        "expected_path":
                        os.path.join(local_path, name),
                        "size":
                        first_torrent.get('size') or 0,
                        "downloader_name":
                        first_torrent.get('downloader_name', '未知')
                    })

                # 找出孤立的文件 (名字在本地有，但数据库没有)
                orphaned_names = local_items - torrent_names_in_path
                for item_name in orphaned_names:
                    full_path = os.path.join(local_path, item_name)
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

                    # 尝试找到原始的远程路径
                    # 优先从该路径下的种子获取，否则尝试反向映射本地路径到远程路径
                    original_save_path = local_path
                    if path_torrents:
                        original_save_path = path_torrents[0]['save_path']
                    else:
                        # 尝试反向映射：从本地路径推断远程路径
                        for downloader_id, mappings in path_mappings_by_downloader.items(
                        ):
                            if downloader_id in remote_downloaders:
                                continue
                            for mapping in mappings:
                                local_root = mapping.get("local",
                                                         "").rstrip("/")
                                remote_root = mapping.get("remote",
                                                          "").rstrip("/")
                                if local_root and remote_root:
                                    if local_path == local_root or local_path.startswith(
                                            local_root + "/"):
                                        original_save_path = local_path.replace(
                                            local_root, remote_root, 1)
                                        break

                    orphaned_files.append({
                        "name": item_name,
                        "path": original_save_path,  # 显示原始远程路径或推断的路径
                        "full_path": full_path,
                        "is_file": is_file,
                        "size": size
                    })

                # 找出正常同步的文件组 (两边都有)
                synced_names = local_items & torrent_names_in_path
                for name in synced_names:
                    torrent_group = torrents_by_name_in_path[name]
                    # 找到原始的远程路径
                    original_save_path = torrent_group[0][
                        'save_path'] if torrent_group else local_path
                    synced_torrents.append({
                        "name":
                        name,
                        "path":
                        original_save_path,  # 显示原始远程路径
                        "torrents_count":
                        len(torrent_group),
                        "downloader_names":
                        list(set(t["downloader_name"] for t in torrent_group))
                    })

            except Exception as e:
                logger.error(f"扫描路径 {local_path} 时出错: {str(e)}")

        # 5. 处理远程下载器的路径（通过代理批量检查文件）
        proxy_configs = {}  # 缓存代理配置
        for remote_path, path_torrents in remote_torrents_by_path.items():
            # 获取第一个种子的下载器ID和代理配置
            first_torrent = path_torrents[0]
            downloader_id = first_torrent.get('downloader_id')

            # 获取或缓存代理配置
            if downloader_id not in proxy_configs:
                proxy_configs[downloader_id] = _get_downloader_proxy_config(
                    downloader_id)

            proxy_config = proxy_configs[downloader_id]
            if not proxy_config:
                logger.warning(f"下载器 {downloader_id} 没有代理配置，跳过检查")
                continue

            # 按名称分组，用于后续检查
            torrents_by_name_in_path = defaultdict(list)
            for torrent in path_torrents:
                torrents_by_name_in_path[torrent['name']].append(torrent)

            # 构建需要检查的路径列表
            paths_to_check = []
            for name in torrents_by_name_in_path.keys():
                full_remote_path = os.path.join(remote_path, name)
                paths_to_check.append(full_remote_path)

            # 批量检查所有文件
            logger.info(f"批量检查远程路径 {remote_path} 下的 {len(paths_to_check)} 个文件")
            check_results = batch_check_remote_files(proxy_config,
                                                     paths_to_check)

            # 处理检查结果
            for name, torrent_group in torrents_by_name_in_path.items():
                full_remote_path = os.path.join(remote_path, name)
                exists, is_file, size = check_results.get(
                    full_remote_path, (False, False, 0))

                if not exists:
                    # 文件不存在，添加到缺失列表
                    first = torrent_group[0]
                    missing_files.append({
                        "name":
                        name,
                        "save_path":
                        remote_path,
                        "expected_path":
                        full_remote_path,
                        "size":
                        first.get('size') or 0,
                        "downloader_name":
                        first.get('downloader_name', '未知')
                    })
                else:
                    # 文件存在，添加到正常同步列表
                    synced_torrents.append({
                        "name":
                        name,
                        "path":
                        remote_path,
                        "torrents_count":
                        len(torrent_group),
                        "downloader_names":
                        list(set(t["downloader_name"] for t in torrent_group))
                    })

        # 6. 统计信息
        scan_summary = {
            "total_torrents": total_torrents_count,
            "total_local_items": total_local_items,
            "missing_count": len(missing_files),
            "orphaned_count": len(orphaned_files),
            "synced_count": len(synced_torrents),
            "remote_torrents_count": remote_torrents_count,  # 添加远程种子计数
            "skipped_remote": remote_torrents_count > 0  # 标记是否跳过了远程种子
        }

        result = {
            "scan_summary": scan_summary,
            "missing_files": missing_files,
            "orphaned_files": orphaned_files,
            "synced_torrents": synced_torrents
        }

        # 保存到缓存
        save_scan_cache(result)

        return jsonify(result)

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
                "hash":
                inst['hash'],
                "downloader_name":
                get_downloader_name_from_config(inst.get('downloader_id')),
                "path":
                inst.get('save_path') or "未知"
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
