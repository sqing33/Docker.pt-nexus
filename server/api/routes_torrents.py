# api/routes_torrents.py

import logging
import json
import uuid
from datetime import datetime
from flask import Blueprint, jsonify, request
from collections import defaultdict
from functools import cmp_to_key
from threading import Thread

# 从项目根目录导入核心模块和工具函数
from core import services
from utils import custom_sort_compare, format_bytes
from utils.downloader_selector import select_best_downloader

# --- Blueprint Setup ---
torrents_bp = Blueprint("torrents_api", __name__, url_prefix="/api")

# --- 依赖注入占位符 ---
# db_manager = None
# config_manager = None

# --- IYUU 批量查询任务（用于前端轮询进度） ---
IYUU_BATCH_QUERY_TASKS = {}


@torrents_bp.route("/downloaders_list")
def get_downloaders_list():
    """获取已配置且启用的下载器列表。"""
    config_manager = torrents_bp.config_manager
    try:
        downloaders = config_manager.get().get("downloaders", [])
        downloader_list = [{
            "id": d["id"],
            "name": d["name"]
        } for d in downloaders if d.get("enabled")]
        return jsonify(downloader_list)
    except Exception as e:
        logging.error(f"get_downloaders_list 出错: {e}", exc_info=True)
        return jsonify({"error": "获取下载器列表失败"}), 500


@torrents_bp.route("/all_downloaders")
def get_all_downloaders():
    """获取所有已配置的下载器列表（包括启用和禁用的）。"""
    config_manager = torrents_bp.config_manager
    try:
        downloaders = config_manager.get().get("downloaders", [])
        downloader_list = [{
            "id": d["id"],
            "name": d["name"],
            "enabled": d.get("enabled", True)
        } for d in downloaders]
        return jsonify(downloader_list)
    except Exception as e:
        logging.error(f"get_all_downloaders 出错: {e}", exc_info=True)
        return jsonify({"error": "获取所有下载器列表失败"}), 500


@torrents_bp.route("/data")
def get_data_api():
    """获取种子列表数据，支持分页、排序和多种筛选。"""
    db_manager = torrents_bp.db_manager
    try:
        page = int(request.args.get("page", 1))
        page_size = int(request.args.get("pageSize", 50))
        path_filters = json.loads(request.args.get("path_filters", "[]"))
        state_filters = json.loads(request.args.get("state_filters", "[]"))
        downloader_filters = json.loads(
            request.args.get("downloader_filters", "[]"))
        source_availability_filters = json.loads(
            request.args.get("source_availability_filters") or "[]")
        exist_site_names = json.loads(request.args.get("existSiteNames", "[]"))
        not_exist_site_names = json.loads(
            request.args.get("notExistSiteNames", "[]"))
        name_search = request.args.get("nameSearch", "").lower()
        sort_prop = request.args.get("sortProp")
        sort_order = request.args.get("sortOrder")
        # 新增：获取 exclude_existing 参数
        exclude_existing = request.args.get("exclude_existing", "false").lower() == "true"
    except (ValueError, json.JSONDecodeError):
        return jsonify({"error": "无效的查询参数"}), 400

    conn, cursor = None, None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        # --- [新增] 开始: 一次性获取所有站点配置信息 ---
        cursor.execute("SELECT nickname, migration, cookie FROM sites")
        # [修复] 将 sqlite3.Row 对象转换为标准的 dict，以支持 .get() 方法
        site_configs = {
            row["nickname"]: dict(row)
            for row in cursor.fetchall()
        }
        # --- [新增] 结束 ---

        # 获取所有目标站点（migration 为 2 或 3 的站点）
        target_sites = {
            name
            for name, config in site_configs.items()
            if config.get("migration", 0) in [2, 3]
        }

        # 修改后的逻辑：all_discovered_sites = 数据库中有做种记录的站点 + 配置了cookie的站点
        cursor.execute(
            "SELECT DISTINCT sites FROM torrents WHERE sites IS NOT NULL AND sites != ''"
        )
        sites_from_torrents = {row["sites"] for row in cursor.fetchall()}
        
        # 获取配置了cookie的站点
        cursor.execute(
            "SELECT nickname FROM sites WHERE cookie IS NOT NULL AND cookie != ''"
        )
        sites_with_cookie = {row["nickname"] for row in cursor.fetchall()}
        
        # 合并两个集合并排序
        all_discovered_sites = sorted(sites_from_torrents | sites_with_cookie)

        # 明确指定查询列，确保包含新添加的列，并排除状态为"不存在"的记录
        placeholder = "%s" if db_manager.db_type in ["mysql", "postgresql"] else "?"
        if db_manager.db_type == "postgresql":
            cursor.execute(
                "SELECT hash, name, save_path, size, progress, state, sites, \"group\", details, downloader_id, last_seen, iyuu_last_check, seeders FROM torrents WHERE state != " + placeholder,
                ("不存在", ))
        else:
            cursor.execute(
                "SELECT hash, name, save_path, size, progress, state, sites, `group`, details, downloader_id, last_seen, iyuu_last_check, seeders FROM torrents WHERE state != " + placeholder,
                ("不存在", ))
        torrents_raw = [dict(row) for row in cursor.fetchall()]

        cursor.execute(
            "SELECT hash, SUM(uploaded) as total_uploaded FROM torrent_upload_stats GROUP BY hash"
        )
        uploads_by_hash = {
            row["hash"]: int(row["total_uploaded"] or 0)
            for row in cursor.fetchall()
        }

        agg_torrents = defaultdict(
            lambda: {
                "name": "",
                "save_path": "",
                "size": 0,
                "progress": 0,
                "state": set(),
                "sites": defaultdict(lambda: {"uploaded": 0, "comment": "", "migration": 0, "state": "N/A", "seeders": 0}),
                "total_uploaded": 0,
                "seeders": 0,  # 添加做种人数字段
                "downloader_ids": [],  # 修改为数组以支持多个下载器
            })
        for t in torrents_raw:
            # 使用种子名称和大小作为唯一标识，以区分同名但不同大小的种子
            torrent_key = (t['name'], t.get('size', 0))
            agg = agg_torrents[torrent_key]
            if not agg["name"]:
                agg.update({
                    "name": t["name"],
                    "save_path": t.get("save_path", ""),
                    "size": t.get("size", 0),
                })
            # 如果当前save_path为空，但新记录有非空的save_path，则更新它
            elif not agg["save_path"] and t.get("save_path"):
                agg["save_path"] = t.get("save_path", "")
            # 添加下载器ID到数组中（去重）
            downloader_id = t.get("downloader_id")
            if downloader_id and downloader_id not in agg["downloader_ids"]:
                agg["downloader_ids"].append(downloader_id)
            agg["progress"] = max(agg.get("progress", 0), t.get("progress", 0))
            agg["state"].add(t.get("state", "N/A"))
            upload_for_this_hash = uploads_by_hash.get(t["hash"], 0)
            agg["total_uploaded"] += upload_for_this_hash
            # 更新做种人数：取所有记录中的最大值
            agg["seeders"] = max(agg.get("seeders", 0), t.get("seeders", 0))
            if t.get("sites"):
                site_name = t.get("sites")
                agg["sites"][site_name]["uploaded"] = (
                    agg["sites"][site_name].get("uploaded", 0) +
                    upload_for_this_hash)
                agg["sites"][site_name]["comment"] = t.get("details")
                # 添加站点状态
                agg["sites"][site_name]["state"] = t.get("state", "N/A")
                # 添加做种人数
                agg["sites"][site_name]["seeders"] = max(
                    agg["sites"][site_name].get("seeders", 0),
                    t.get("seeders", 0))

                # --- [修改] 开始: 附加 migration 状态 ---
                # 从预加载的配置中获取 migration 值，如果站点不存在则默认为 0
                # 此处现在可以安全地使用 .get()
                agg["sites"][site_name]["migration"] = site_configs.get(
                    site_name, {}).get("migration", 0)
                # --- [修改] 结束 ---

        final_torrent_list = []
        for key, data in agg_torrents.items():
            name, size = key
            # 计算可以转种到的目标站点数量
            # 目标站点是那些当前种子未存在于其上的目标站点
            existing_sites = set(data.get("sites", {}).keys())
            target_sites_count = len(target_sites - existing_sites)

            data.update({
                "unique_id": f"{name}_{size}",
                "state":
                ", ".join(sorted(list(data["state"]))),
                "size_formatted":
                format_bytes(data["size"]),
                "total_uploaded_formatted":
                format_bytes(data["total_uploaded"]),
                "site_count":
                len(data.get("sites", {})),
                "total_site_count":
                len(all_discovered_sites),
                "target_sites_count":
                target_sites_count,
                "seeders": data.get("seeders", 0),  # 添加做种人数
                "downloaderIds":
                data.get("downloader_ids", []),
                "downloaderId":
                select_best_downloader(
                    downloader_ids=data.get("downloader_ids", []),
                    config_manager=torrents_bp.config_manager
                )
            })
            final_torrent_list.append(data)

        # Filtering logic
        filtered_list = final_torrent_list
        if name_search:
            filtered_list = [
                t for t in filtered_list if name_search in t["name"].lower()
            ]
        if path_filters:
            filtered_list = [
                t for t in filtered_list 
                if any(
                    t.get("save_path", "") == path
                    for path in path_filters
                )
            ]
        if state_filters:
            filtered_list = [
                t for t in filtered_list if any(
                    s in state_filters for s in t.get("state", "").split(", "))
            ]
        if downloader_filters:
            filtered_list = [
                t for t in filtered_list
                if any(downloader_id in downloader_filters
                       for downloader_id in t.get("downloaderIds", []))
            ]
        # 源站点可用性筛选（只计算有cookie的源站点）
        if "存在源站点" in source_availability_filters and "无可用源站点" in source_availability_filters:
            # 包含所有（默认）
            pass
        elif "存在源站点" in source_availability_filters:
            filtered_list = [
                t for t in filtered_list
                if len([site_name for site_name, site_data in t.get("sites", {}).items()
                        if site_data.get("migration", 0) in [1, 3] and
                           site_configs.get(site_name, {}).get("cookie", "") != ""]) > 0
            ]
        elif "无可用源站点" in source_availability_filters:
            filtered_list = [
                t for t in filtered_list
                if len([site_name for site_name, site_data in t.get("sites", {}).items()
                        if site_data.get("migration", 0) in [1, 3] and
                           site_configs.get(site_name, {}).get("cookie", "") != ""]) == 0
            ]
        # 站点筛选逻辑：同时支持存在于和不存在于的筛选
        # 种子必须存在于exist_site_names中的所有站点
        if exist_site_names:
            exist_site_set = set(exist_site_names)
            filtered_list = [
                t for t in filtered_list
                if exist_site_set.issubset(set(t.get("sites", {}).keys()))
            ]

        # 种子必须不存在于not_exist_site_names中的任何站点
        if not_exist_site_names:
            not_exist_site_set = set(not_exist_site_names)
            filtered_list = [
                t for t in filtered_list
                if not not_exist_site_set.intersection(
                    set(t.get("sites", {}).keys()))
            ]
        
        # 新增：如果 exclude_existing 为 True，则排除已存在于 seed_parameters 表中的种子
        if exclude_existing:
            try:
                # 查询 seed_parameters 表中所有唯一的种子名称
                cursor.execute("SELECT DISTINCT name FROM seed_parameters")
                existing_seed_names = {row["name"] for row in cursor.fetchall()}
                
                # 过滤掉已存在的种子
                filtered_list = [
                    t for t in filtered_list
                    if t["name"] not in existing_seed_names
                ]
            except Exception as e:
                logging.error(f"查询 seed_parameters 表失败: {e}", exc_info=True)
                # 如果查询失败，可以选择返回错误或继续执行而不进行排除
                # 这里我们选择继续执行，以保证接口的可用性
                pass


        # Sorting logic
        if sort_prop and sort_order:
            reverse = sort_order == "descending"
            sort_key_map = {
                "size_formatted": "size",
                "total_uploaded_formatted": "total_uploaded"
            }
            sort_key = sort_key_map.get(sort_prop, sort_prop)
            if sort_key in [
                    "size", "progress", "total_uploaded", "site_count",
                    "target_sites_count"
            ]:
                filtered_list.sort(key=lambda x: x.get(sort_key, 0),
                                   reverse=reverse)
            else:
                filtered_list.sort(
                    key=cmp_to_key(lambda a, b: custom_sort_compare(a, b)),
                    reverse=reverse)
        else:
            filtered_list.sort(key=cmp_to_key(custom_sort_compare))

        # Pagination
        total_items = len(filtered_list)
        paginated_data = filtered_list[(page - 1) * page_size:page * page_size]

        unique_paths = sorted(
            list(
                set(
                    r.get("save_path") for r in torrents_raw
                    if r.get("save_path"))))
        unique_states = sorted(
            list(set(r.get("state") for r in torrents_raw if r.get("state"))))

        _, site_link_rules, _ = services.load_site_maps_from_db(db_manager)

        return jsonify({
            "data": paginated_data,
            "total": total_items,
            "page": page,
            "pageSize": page_size,
            "unique_paths": unique_paths,
            "unique_states": unique_states,
            "all_discovered_sites": all_discovered_sites,
            "site_link_rules": site_link_rules,
            "active_path_filters": path_filters,
        })
    except Exception as e:
        logging.error(f"get_data_api 出错: {e}", exc_info=True)
        return jsonify({"error": "从数据库检索种子数据失败"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@torrents_bp.route("/refresh_data", methods=["POST"])
def refresh_data_api():
    """手动触发种子数据刷新。"""
    print("【API】收到刷新种子数据的请求")
    try:
        # 导入手动任务模块
        from core.manual_tasks import update_torrents_data
        db_manager = torrents_bp.db_manager
        config_manager = torrents_bp.config_manager

        # 调用手动更新函数
        result = update_torrents_data(db_manager, config_manager)

        if result["success"]:
            print("【API】数据刷新完成")
            return jsonify({"message": result["message"]}), 200
        else:
            print(f"【API】数据刷新失败: {result['message']}")
            return jsonify({"error": result["message"]}), 400

    except Exception as e:
        print(f"【API】触发刷新失败: {e}")
        logging.error(f"触发刷新失败: {e}")
        return jsonify({"error": "触发刷新失败"}), 500


@torrents_bp.route("/iyuu_query", methods=["POST"])
def iyuu_query_api():
    """手动触发指定种子的IYUU查询（同步执行）"""
    db_manager = torrents_bp.db_manager
    config_manager = torrents_bp.config_manager

    try:
        data = request.get_json() or {}

        save_path = data.get("save_path") or data.get("path")
        if save_path:
            # 路径批量查询模式：优先确保包含当前选中种子（anchor_name）
            limit = data.get("limit", 200)
            anchor_name = data.get("anchor_name") or data.get("name")

            from core.manual_tasks import trigger_iyuu_query_by_path_sync

            result = trigger_iyuu_query_by_path_sync(
                db_manager,
                config_manager,
                save_path,
                limit=limit,
                anchor_name=anchor_name,
            )
        else:
            torrent_name = data.get("name")
            torrent_size = data.get("size")

            if not torrent_name:
                return jsonify({"error": "缺少种子名称参数"}), 400

            if not torrent_size:
                return jsonify({"error": "缺少种子大小参数"}), 400

            # 导入手动任务模块
            from core.manual_tasks import trigger_iyuu_query_sync

            # 同步执行IYUU查询，等待完成后返回
            result = trigger_iyuu_query_sync(db_manager, config_manager, torrent_name, torrent_size)

        if result["success"]:
            return jsonify({
                "message": result["message"],
                "success": True,
                "stats": result.get("stats", {}),
                "query_info": result.get("query_info", {}),
            }), 200
        else:
            return jsonify({"error": result["message"], "success": False}), 500

    except Exception as e:
        logging.error(f"iyuu_query_api 出错: {e}", exc_info=True)
        return jsonify({"error": "触发IYUU查询失败", "success": False}), 500


@torrents_bp.route("/iyuu_query_batch", methods=["POST"])
def iyuu_query_batch_api():
    """批量触发 IYUU 查询（异步执行），用于前端对筛选结果批量补全站点信息。"""
    db_manager = torrents_bp.db_manager
    config_manager = torrents_bp.config_manager

    try:
        data = request.get_json() or {}
        torrents = data.get("torrents") or []
        max_groups = data.get("max_groups", 200)
        force_query = bool(data.get("force_query", True))

        if not isinstance(torrents, list) or not torrents:
            return jsonify({"success": False, "message": "缺少种子列表参数"}), 400

        try:
            max_groups_int = int(max_groups)
        except Exception:
            max_groups_int = 200
        if max_groups_int <= 0:
            max_groups_int = 200

        # 生成任务ID
        task_id = str(uuid.uuid4())
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        IYUU_BATCH_QUERY_TASKS[task_id] = {
            "task_id": task_id,
            "created_at": now,
            "finished_at": None,
            "isRunning": True,
            "success": None,
            "message": "任务已启动",
            "total": min(len(torrents), max_groups_int),
            "processed": 0,
            "stats": {},
            "query_info": {},
        }

        def _run_task():
            try:
                from core.manual_tasks import trigger_iyuu_query_torrents_batch_sync

                result = trigger_iyuu_query_torrents_batch_sync(
                    db_manager,
                    config_manager,
                    torrents,
                    max_groups=max_groups,
                    force_query=force_query,
                )

                IYUU_BATCH_QUERY_TASKS[task_id].update({
                    "isRunning": False,
                    "success": bool(result.get("success")),
                    "message": result.get("message", ""),
                    "processed": int(result.get("query_info", {}).get("processed_groups", 0) or 0),
                    "stats": result.get("stats", {}) or {},
                    "query_info": result.get("query_info", {}) or {},
                    "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
            except Exception as e:
                logging.error(f"iyuu_query_batch_api 任务执行出错: {e}", exc_info=True)
                IYUU_BATCH_QUERY_TASKS[task_id].update({
                    "isRunning": False,
                    "success": False,
                    "message": f"任务执行失败: {str(e)}",
                    "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })

        thread = Thread(target=_run_task)
        thread.daemon = True
        thread.start()

        return jsonify({"success": True, "task_id": task_id})

    except Exception as e:
        logging.error(f"iyuu_query_batch_api 出错: {e}", exc_info=True)
        return jsonify({"success": False, "message": "启动批量IYUU查询失败"}), 500


@torrents_bp.route("/iyuu_query_batch_progress", methods=["GET"])
def iyuu_query_batch_progress_api():
    """获取批量 IYUU 查询任务进度。"""
    task_id = request.args.get("task_id")
    if not task_id:
        return jsonify({"success": False, "message": "缺少 task_id 参数"}), 400

    task = IYUU_BATCH_QUERY_TASKS.get(task_id)
    if not task:
        return jsonify({"success": False, "message": "任务不存在或已过期"}), 404

    return jsonify({"success": True, "task": task})


@torrents_bp.route("/paths", methods=["GET"])
def get_all_paths_api():
    """获取所有种子保存路径列表"""
    db_manager = torrents_bp.db_manager

    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        # 查询所有非空的保存路径
        if db_manager.db_type == "postgresql":
            cursor.execute(
                'SELECT DISTINCT save_path FROM torrents WHERE save_path IS NOT NULL AND save_path != \'\' ORDER BY save_path'
            )
        else:
            cursor.execute(
                "SELECT DISTINCT save_path FROM torrents WHERE save_path IS NOT NULL AND save_path != '' ORDER BY save_path"
            )

        paths = [row['save_path'] for row in cursor.fetchall()]

        cursor.close()
        conn.close()

        return jsonify({
            "success": True,
            "paths": paths
        })

    except Exception as e:
        logging.error(f"get_all_paths_api 出错: {e}", exc_info=True)
        return jsonify({"error": "获取路径列表失败", "success": False}), 500


@torrents_bp.route("/cached_sites", methods=["GET"])
def get_cached_sites_api():
    """查询指定种子在seed_parameters表中的缓存站点（使用name+size精确匹配）"""
    db_manager = torrents_bp.db_manager
    
    try:
        # 获取查询参数：种子名称和大小
        torrent_name = request.args.get("name", "").strip()
        torrent_size = request.args.get("size", "").strip()
        
        if not torrent_name:
            return jsonify({"error": "缺少必要参数：name"}), 400
        
        if not torrent_size:
            return jsonify({"error": "缺少必要参数：size"}), 400
        
        try:
            torrent_size = int(torrent_size)
        except ValueError:
            return jsonify({"error": "size参数必须是整数"}), 400
        
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        
        # 1. 先从seed_parameters表中根据name查询所有相同名称的记录的hash
        placeholder = "%s" if db_manager.db_type in ["mysql", "postgresql"] else "?"
        cursor.execute(
            f"SELECT DISTINCT hash FROM seed_parameters WHERE name = {placeholder}",
            (torrent_name,)
        )
        
        seed_hashes = [row["hash"] for row in cursor.fetchall()]
        
        if not seed_hashes:
            cursor.close()
            conn.close()
            return jsonify({
                "success": True,
                "cached_sites": [],
                "message": "未找到该种子的缓存信息"
            })
        
        # 2. 用这些hash去torrents表中查询，找出size匹配的hash
        if db_manager.db_type == "postgresql":
            placeholders = ', '.join(['%s'] * len(seed_hashes))
            cursor.execute(
                f"SELECT DISTINCT hash FROM torrents WHERE hash = ANY(ARRAY[{placeholders}]) AND size = %s",
                (*seed_hashes, torrent_size)
            )
        else:
            placeholders = ', '.join([placeholder] * len(seed_hashes))
            cursor.execute(
                f"SELECT DISTINCT hash FROM torrents WHERE hash IN ({placeholders}) AND size = {placeholder}",
                (*seed_hashes, torrent_size)
            )
        
        matched_hashes = [row["hash"] for row in cursor.fetchall()]
        
        if not matched_hashes:
            cursor.close()
            conn.close()
            return jsonify({
                "success": True,
                "cached_sites": [],
                "message": "未找到匹配大小的种子缓存"
            })
        
        # 3. 查询这些匹配的hash对应的所有缓存站点
        if db_manager.db_type == "postgresql":
            placeholders = ', '.join(['%s'] * len(matched_hashes))
            cursor.execute(
                f"SELECT DISTINCT nickname FROM seed_parameters WHERE hash = ANY(ARRAY[{placeholders}])",
                tuple(matched_hashes)
            )
        else:
            placeholders = ', '.join([placeholder] * len(matched_hashes))
            cursor.execute(
                f"SELECT DISTINCT nickname FROM seed_parameters WHERE hash IN ({placeholders})",
                tuple(matched_hashes)
            )
        
        cached_sites = [row["nickname"] for row in cursor.fetchall()]
        
        cursor.close()
        conn.close()
        
        return jsonify({
            "success": True,
            "cached_sites": cached_sites,
            "matched_hashes": matched_hashes
        })
        
    except Exception as e:
        logging.error(f"get_cached_sites_api 出错: {e}", exc_info=True)
        return jsonify({"error": "查询缓存站点失败", "success": False}), 500
