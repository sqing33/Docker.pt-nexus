# api/routes_torrents.py

import logging
import json
from flask import Blueprint, jsonify, request
from collections import defaultdict
from functools import cmp_to_key
from threading import Thread

# 从项目根目录导入核心模块和工具函数
from core import services
from utils import custom_sort_compare, format_bytes

# --- Blueprint Setup ---
torrents_bp = Blueprint("torrents_api", __name__, url_prefix="/api")

# --- 依赖注入占位符 ---
# db_manager = None
# config_manager = None


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
        site_filter_existence = request.args.get("siteFilterExistence", "all")
        site_filter_names = json.loads(
            request.args.get("siteFilterNames", "[]"))
        name_search = request.args.get("nameSearch", "").lower()
        sort_prop = request.args.get("sortProp")
        sort_order = request.args.get("sortOrder")
    except (ValueError, json.JSONDecodeError):
        return jsonify({"error": "无效的查询参数"}), 400

    conn, cursor = None, None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        # --- [新增] 开始: 一次性获取所有站点配置信息 ---
        cursor.execute("SELECT nickname, migration FROM sites")
        # [修复] 将 sqlite3.Row 对象转换为标准的 dict，以支持 .get() 方法
        site_configs = {row["nickname"]: dict(row) for row in cursor.fetchall()}
        # --- [新增] 结束 ---

        cursor.execute(
            "SELECT DISTINCT sites FROM torrents WHERE sites IS NOT NULL AND sites != ''"
        )
        all_discovered_sites = sorted(
            [row["sites"] for row in cursor.fetchall()])

        cursor.execute("SELECT * FROM torrents")
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
                "sites": defaultdict(dict),
                "total_uploaded": 0,
                "downloader_id": None,
            })
        for t in torrents_raw:
            agg = agg_torrents[t["name"]]
            if not agg["name"]:
                agg.update({
                    "name": t["name"],
                    "save_path": t.get("save_path", ""),
                    "size": t.get("size", 0),
                    "downloader_id": t.get("downloader_id"),
                })
            agg["progress"] = max(agg.get("progress", 0), t.get("progress", 0))
            agg["state"].add(t.get("state", "N/A"))
            upload_for_this_hash = uploads_by_hash.get(t["hash"], 0)
            agg["total_uploaded"] += upload_for_this_hash
            if t.get("sites"):
                site_name = t.get("sites")
                agg["sites"][site_name]["uploaded"] = (
                    agg["sites"][site_name].get("uploaded", 0) +
                    upload_for_this_hash)
                agg["sites"][site_name]["comment"] = t.get("details")

                # --- [修改] 开始: 附加 migration 状态 ---
                # 从预加载的配置中获取 migration 值，如果站点不存在则默认为 0
                # 此处现在可以安全地使用 .get()
                agg["sites"][site_name]["migration"] = site_configs.get(
                    site_name, {}).get("migration", 0)
                # --- [修改] 结束 ---

        final_torrent_list = []
        for name, data in agg_torrents.items():
            data.update({
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
                "downloaderId":
                data.get("downloader_id")
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
                t for t in filtered_list if t.get("save_path") in path_filters
            ]
        if state_filters:
            filtered_list = [
                t for t in filtered_list if any(
                    s in state_filters for s in t.get("state", "").split(", "))
            ]
        if downloader_filters:
            filtered_list = [
                t for t in filtered_list
                if t.get("downloaderId") in downloader_filters
            ]
        if site_filter_existence != "all" and site_filter_names:
            site_filter_set = set(site_filter_names)
            if site_filter_existence == "exists":
                filtered_list = [
                    t for t in filtered_list
                    if site_filter_set.intersection(t.get("sites", {}).keys())
                ]
            elif site_filter_existence == "not-exists":
                filtered_list = [
                    t for t in filtered_list
                    if not site_filter_set.intersection(
                        t.get("sites", {}).keys())
                ]

        # Sorting logic
        if sort_prop and sort_order:
            reverse = sort_order == "descending"
            sort_key_map = {
                "size_formatted": "size",
                "total_uploaded_formatted": "total_uploaded"
            }
            sort_key = sort_key_map.get(sort_prop, sort_prop)
            if sort_key in [
                    "size", "progress", "total_uploaded", "site_count"
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
    """触发后台任务，立即刷新所有下载器的种子列表。"""
    try:
        if services.data_tracker_thread and services.data_tracker_thread.is_alive(
        ):
            Thread(target=services.data_tracker_thread._update_torrents_in_db
                   ).start()
            return jsonify({"message": "后台刷新已触发"}), 202
        else:
            return jsonify({"message": "数据追踪服务未运行，无法刷新。"}), 400
    except Exception as e:
        logging.error(f"触发刷新失败: {e}")
        return jsonify({"error": "触发刷新失败"}), 500
