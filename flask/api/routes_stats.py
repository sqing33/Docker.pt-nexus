# api/routes_stats.py

import logging
import copy
from flask import Blueprint, jsonify, request
from datetime import datetime, timedelta
from collections import defaultdict

# 从项目根目录导入核心模块
from core import services

# --- Blueprint Setup ---
stats_bp = Blueprint("stats_api", __name__, url_prefix="/api")

# --- 依赖注入占位符 ---
# db_manager = None
# config_manager = None


def get_date_range_and_grouping(time_range_str, for_speed=False):
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_dt, end_dt = None, now
    group_by_format = "%Y-%m-%d"
    ranges = {
        "today": (today_start, "%Y-%m-%d %H:00"),
        "yesterday": (today_start - timedelta(days=1), "%Y-%m-%d %H:00"),
        "this_week": (today_start - timedelta(days=now.weekday()), "%Y-%m-%d"),
        "last_week":
        (today_start - timedelta(days=now.weekday() + 7), "%Y-%m-%d"),
        "this_month": (today_start.replace(day=1), "%Y-%m-%d"),
        "last_month": (
            (today_start.replace(day=1) - timedelta(days=1)).replace(day=1),
            "%Y-%m-%d",
        ),
        "last_6_months": (now - timedelta(days=180), "%Y-%m"),
        "this_year": (today_start.replace(month=1, day=1), "%Y-%m"),
        "all": (datetime(1970, 1, 1), "%Y-%m"),
        "last_12_hours": (now - timedelta(hours=12), None),
        "last_24_hours": (now - timedelta(hours=24), None),
    }
    if time_range_str in ranges:
        start_dt, group_by_format_override = ranges[time_range_str]
        if group_by_format_override is not None:  # Changed from "if group_by_format_override:" to handle empty string
            group_by_format = group_by_format_override

    if time_range_str == "yesterday":
        end_dt = today_start
    if time_range_str == "last_week":
        end_dt = today_start - timedelta(days=now.weekday())
    if time_range_str == "last_month":
        end_dt = today_start.replace(day=1)

    if for_speed:
        if time_range_str in [
                "last_12_hours", "last_24_hours", "today", "yesterday"
        ]:
            group_by_format = "%Y-%m-%d %H:%M"
        elif start_dt and (end_dt - start_dt).total_seconds() > 0:
            if group_by_format not in ["%Y-%m"]:
                group_by_format = "%Y-%m-%d %H:00"
    return start_dt, end_dt, group_by_format


def get_time_group_fn(db_type, format_str):
    if db_type == "mysql":
        return f"DATE_FORMAT(stat_datetime, '{format_str.replace('%M', '%i')}')"
    elif db_type == "postgresql":
        # Convert strftime format to PostgreSQL TO_CHAR format
        pg_format = format_str.replace('%Y', 'YYYY').replace('%m', 'MM').replace('%d', 'DD').replace('%H', 'HH24').replace('%M', 'MI')
        return f"TO_CHAR(stat_datetime, '{pg_format}')"
    else:  # sqlite
        return f"STRFTIME('{format_str}', stat_datetime)"


@stats_bp.route("/chart_data")
def get_chart_data_api():
    """获取历史流量图表数据，按下载器分组。"""
    db_manager = stats_bp.db_manager
    config_manager = stats_bp.config_manager  # 需要 config_manager 来获取下载器名称

    time_range = request.args.get("range", "this_week")
    start_dt, end_dt, group_by_format = get_date_range_and_grouping(time_range)
    # 如果 group_by_format 为 None，设置默认值
    if not group_by_format:
        group_by_format = "%Y-%m-%d %H:00"
    time_group_fn = get_time_group_fn(db_manager.db_type, group_by_format)
    ph = db_manager.get_placeholder()

    # --- 修改 SQL 查询，增加 downloader_id 分组 ---
    query = f"SELECT {time_group_fn} AS time_group, downloader_id, SUM(uploaded) AS total_ul, SUM(downloaded) AS total_dl FROM traffic_stats WHERE stat_datetime >= {ph}"
    params = [start_dt.strftime("%Y-%m-%d %H:%M:%S")] if start_dt else []
    if end_dt and start_dt:
        query += f" AND stat_datetime < {ph}"
        params.append(end_dt.strftime("%Y-%m-%d %H:%M:%S"))
    query += " GROUP BY time_group, downloader_id ORDER BY time_group"
    
    # 获取下载器信息（移到前面以便在早期返回中使用）
    enabled_downloaders = [{
        "id": d["id"],
        "name": d["name"]
    } for d in config_manager.get().get("downloaders", [])
                            if d.get("enabled")]
    
    # 如果没有参数但查询中有占位符，则返回空数据
    if not params:
        logging.info("No params for chart data query, returning empty data")
        return jsonify({
            "labels": [],
            "datasets": {},
            "downloaders": enabled_downloaders
        })
    
    # 添加调试日志
    logging.info(f"Chart data query: {query}")
    logging.info(f"Chart data params: {params}")
    logging.info(f"Number of placeholders in query: {query.count(ph)}")
    logging.info(f"Number of params: {len(params)}")

    conn, cursor = None, None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()

        # --- 获取下载器信息 ---
        enabled_downloaders = [{
            "id": d["id"],
            "name": d["name"]
        } for d in config_manager.get().get("downloaders", [])
                               if d.get("enabled")]
        downloader_ids = {d['id'] for d in enabled_downloaders}

        # --- 重构数据处理逻辑 ---
        # 1. 获取所有时间标签
        labels = sorted(list(set(r['time_group'] for r in rows)))
        label_map = {label: i for i, label in enumerate(labels)}

        # 2. 初始化数据集结构
        datasets = {
            dl['id']: {
                'uploaded': [0] * len(labels),
                'downloaded': [0] * len(labels)
            }
            for dl in enabled_downloaders
        }

        # 3. 填充数据
        for row in rows:
            downloader_id = row['downloader_id']
            # 只处理在当前配置中启用的下载器
            if downloader_id not in downloader_ids:
                continue

            time_group = row['time_group']
            if time_group in label_map:
                idx = label_map[time_group]
                datasets[downloader_id]['uploaded'][idx] = int(row['total_ul']
                                                               or 0)
                datasets[downloader_id]['downloaded'][idx] = int(
                    row['total_dl'] or 0)

        return jsonify({
            "labels": labels,
            "datasets": datasets,
            "downloaders": enabled_downloaders
        })
        # --- 结束 ---

    except Exception as e:
        logging.error(f"get_chart_data_api 出错: {e}", exc_info=True)
        return jsonify({"error": "获取图表数据失败"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@stats_bp.route("/speed_data")
def get_speed_data_api():
    """获取所有下载器当前的实时速度。"""
    speeds_by_client = {}
    if services.data_tracker_thread:
        with services.CACHE_LOCK:
            speeds_by_client = copy.deepcopy(
                services.data_tracker_thread.latest_speeds)
    return jsonify(speeds_by_client)


@stats_bp.route("/recent_speed_data")
def get_recent_speed_data_api():
    """获取最近一段时间（默认60秒）的速度数据，用于实时速度曲线。"""
    config_manager = stats_bp.config_manager
    db_manager = stats_bp.db_manager
    try:
        seconds_to_fetch = int(request.args.get("seconds", "60"))
    except ValueError:
        return jsonify({"error": "无效的秒数参数"}), 400

    enabled_downloaders = [{
        "id": d["id"],
        "name": d["name"]
    } for d in config_manager.get().get("downloaders", []) if d.get("enabled")]

    with services.CACHE_LOCK:
        buffer_data = (list(services.data_tracker_thread.recent_speeds_buffer)
                       if services.data_tracker_thread else [])

    results_from_buffer = []
    for r in sorted(buffer_data, key=lambda x: x["timestamp"]):
        renamed_speeds = {
            d["id"]: {
                "ul_speed": r["speeds"].get(d["id"],
                                            {}).get("upload_speed", 0),
                "dl_speed": r["speeds"].get(d["id"],
                                            {}).get("download_speed", 0),
            }
            for d in enabled_downloaders
        }
        results_from_buffer.append({
            "time": r["timestamp"].strftime("%H:%M:%S"),
            "speeds": renamed_speeds
        })

    seconds_missing = seconds_to_fetch - len(results_from_buffer)
    results_from_db = []
    if seconds_missing > 0:
        conn, cursor = None, None
        try:
            end_dt = buffer_data[0][
                "timestamp"] if buffer_data else datetime.now()
            conn = db_manager._get_connection()
            cursor = db_manager._get_cursor(conn)
            query = f"SELECT stat_datetime, downloader_id, upload_speed, download_speed FROM traffic_stats WHERE stat_datetime < {db_manager.get_placeholder()} ORDER BY stat_datetime DESC LIMIT {db_manager.get_placeholder()}"
            limit = max(1, seconds_missing * len(enabled_downloaders))
            cursor.execute(query,
                           (end_dt.strftime("%Y-%m-%d %H:%M:%S"), limit))

            db_rows_by_time = defaultdict(dict)
            for row in reversed(cursor.fetchall()):
                dt_obj = (datetime.strptime(
                    row["stat_datetime"], "%Y-%m-%d %H:%M:%S") if isinstance(
                        row["stat_datetime"], str) else row["stat_datetime"])
                db_rows_by_time[dt_obj.strftime("%H:%M:%S")][
                    row["downloader_id"]] = {
                        "ul_speed": row["upload_speed"] or 0,
                        "dl_speed": row["download_speed"] or 0,
                    }
            for time_str, speeds_dict in sorted(db_rows_by_time.items()):
                results_from_db.append({
                    "time": time_str,
                    "speeds": speeds_dict
                })
        except Exception as e:
            logging.error(f"获取历史速度数据失败: {e}", exc_info=True)
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    final_results = (results_from_db + results_from_buffer)[-seconds_to_fetch:]
    labels = [r["time"] for r in final_results]
    return jsonify({
        "labels": labels,
        "datasets": final_results,
        "downloaders": enabled_downloaders
    })


@stats_bp.route("/speed_chart_data")
def get_speed_chart_data_api():
    """获取历史速度图表数据。"""
    db_manager = stats_bp.db_manager
    config_manager = stats_bp.config_manager
    time_range = request.args.get("range", "last_12_hours")
    enabled_downloaders = [{
        "id": d["id"],
        "name": d["name"]
    } for d in config_manager.get().get("downloaders", []) if d.get("enabled")]

    conn, cursor = None, None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        start_dt, end_dt, group_by_format = get_date_range_and_grouping(
            time_range, for_speed=True)
        # 如果 group_by_format 为 None，设置默认值
        if not group_by_format:
            group_by_format = "%Y-%m-%d %H:00" if not for_speed else "%Y-%m-%d %H:%M"
        time_group_fn = get_time_group_fn(db_manager.db_type, group_by_format)

        query = f"SELECT {time_group_fn} AS time_group, downloader_id, AVG(upload_speed) AS ul_speed, AVG(download_speed) AS dl_speed FROM traffic_stats WHERE stat_datetime >= {db_manager.get_placeholder()}"
        params = [start_dt.strftime("%Y-%m-%d %H:%M:%S")] if start_dt else []
        if end_dt and start_dt:
            query += f" AND stat_datetime < {db_manager.get_placeholder()}"
            params.append(end_dt.strftime("%Y-%m-%d %H:%M:%S"))
        query += " GROUP BY time_group, downloader_id ORDER BY time_group"
        
        # 如果没有参数但查询中有占位符，则返回空数据
        if not params:
            logging.info("No params for speed chart data query, returning empty data")
            return jsonify({
                "labels": [],
                "datasets": [],
                "downloaders": enabled_downloaders
            })
            
        # 添加调试日志
        logging.info(f"Speed chart data query: {query}")
        logging.info(f"Speed chart data params: {params}")
        logging.info(f"Number of placeholders in speed query: {query.count(db_manager.get_placeholder())}")
        logging.info(f"Number of speed params: {len(params)}")

        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()

        results_by_time = defaultdict(lambda: {"time": "", "speeds": {}})
        for r in rows:
            results_by_time[r["time_group"]]["time"] = r["time_group"]
            results_by_time[r["time_group"]]["speeds"][r["downloader_id"]] = {
                "ul_speed": float(r["ul_speed"] or 0),
                "dl_speed": float(r["dl_speed"] or 0),
            }

        sorted_datasets = sorted(results_by_time.values(),
                                 key=lambda x: x["time"])
        labels = [d["time"] for d in sorted_datasets]
        return jsonify({
            "labels": labels,
            "datasets": sorted_datasets,
            "downloaders": enabled_downloaders
        })
    except Exception as e:
        logging.error(f"get_speed_chart_data_api 出错: {e}", exc_info=True)
        return jsonify({"error": "获取速度图表数据失败"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@stats_bp.route("/site_stats")
def get_site_stats_api():
    """按站点分组统计种子数量和总体积。"""
    db_manager = stats_bp.db_manager
    conn, cursor = None, None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        query = "SELECT sites, SUM(size) as total_size, COUNT(name) as torrent_count FROM (SELECT DISTINCT name, size, sites FROM torrents WHERE sites IS NOT NULL AND sites != '') AS unique_torrents GROUP BY sites;"
        cursor.execute(query)
        results = sorted(
            [{
                "site_name": r["sites"],
                "total_size": int(r["total_size"] or 0),
                "torrent_count": int(r["torrent_count"] or 0),
            } for r in cursor.fetchall()],
            key=lambda x: x["site_name"],
        )
        return jsonify(results)
    except Exception as e:
        logging.error(f"get_site_stats_api 出错: {e}", exc_info=True)
        return jsonify({"error": "获取站点统计信息失败"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@stats_bp.route("/group_stats")
def get_group_stats_api():
    """按发布组和站点关联进行统计。"""
    db_manager = stats_bp.db_manager
    conn, cursor = None, None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        group_col_quoted = "`group`" if db_manager.db_type == "mysql" else '"group"'
        site_nickname = request.args.get("site", "").strip()

        if site_nickname:
            # 统计：先筛选做种站点为指定站点的种子，再按官组与“官组所属站点”聚合
            if db_manager.db_type == "mysql":
                query = f"""
                    SELECT s.nickname AS site_name,
                           ut.`group` AS group_suffix,
                           COUNT(ut.name) AS torrent_count,
                           SUM(ut.size) AS total_size
                    FROM (
                        SELECT name, `group`, MAX(size) AS size
                        FROM torrents
                        WHERE `group` IS NOT NULL AND `group` != '' AND sites = %s
                        GROUP BY name, `group`
                    ) AS ut
                    JOIN sites AS s ON FIND_IN_SET(ut.`group`, s.`group`) > 0
                    GROUP BY s.nickname, ut.`group`
                    ORDER BY torrent_count DESC;
                """
                cursor.execute(query, (site_nickname, ))
            else:
                query = f"""
                    SELECT s.nickname AS site_name,
                           ut.{group_col_quoted} AS group_suffix,
                           COUNT(ut.name) AS torrent_count,
                           SUM(ut.size) AS total_size
                    FROM (
                        SELECT name, {group_col_quoted}, MAX(size) AS size
                        FROM torrents
                        WHERE {group_col_quoted} IS NOT NULL AND {group_col_quoted} != '' AND sites = ?
                        GROUP BY name, {group_col_quoted}
                    ) AS ut
                    JOIN sites AS s ON (',' || s.`group` || ',' LIKE '%,' || ut.{group_col_quoted} || ',%')
                    GROUP BY s.nickname, ut.{group_col_quoted}
                    ORDER BY torrent_count DESC;
                """
                cursor.execute(query, (site_nickname, ))

            results = [{
                "site_name":
                r["site_name"],
                "group_suffix": (r["group_suffix"].replace("-", "")
                                 if r["group_suffix"] else r["group_suffix"]),
                "torrent_count":
                int(r["torrent_count"] or 0),
                "total_size":
                int(r["total_size"] or 0),
            } for r in cursor.fetchall()]
        else:
            # 原逻辑：按站点聚合整体展示
            query = f"""
                SELECT s.nickname AS site_name, 
                       GROUP_CONCAT(DISTINCT ut.{group_col_quoted}) AS group_suffix, 
                       COUNT(ut.name) AS torrent_count, 
                       SUM(ut.size) AS total_size 
                FROM (
                    SELECT name, {group_col_quoted}, MAX(size) AS size 
                    FROM torrents 
                    WHERE {group_col_quoted} IS NOT NULL AND {group_col_quoted} != '' 
                    GROUP BY name, {group_col_quoted}
                ) AS ut 
                JOIN sites AS s ON (',' || s.`group` || ',' LIKE '%,' || ut.{group_col_quoted} || ',%')
                GROUP BY s.nickname ORDER BY s.nickname;
            """
            if db_manager.db_type == "mysql":
                query = f"""
                    SELECT s.nickname AS site_name, 
                           GROUP_CONCAT(DISTINCT ut.`group` ORDER BY ut.`group` SEPARATOR ', ') AS group_suffix, 
                           COUNT(ut.name) AS torrent_count, SUM(ut.size) AS total_size 
                    FROM (
                        SELECT name, `group`, MAX(size) AS size FROM torrents 
                        WHERE `group` IS NOT NULL AND `group` != '' GROUP BY name, `group`
                    ) AS ut 
                    JOIN sites AS s ON FIND_IN_SET(ut.`group`, s.`group`) > 0 
                    GROUP BY s.nickname ORDER BY s.nickname;
                 """
            cursor.execute(query)
            results = [{
                "site_name":
                r["site_name"],
                "group_suffix": (r["group_suffix"].replace("-", "")
                                 if r["group_suffix"] else r["group_suffix"]),
                "torrent_count":
                int(r["torrent_count"] or 0),
                "total_size":
                int(r["total_size"] or 0),
            } for r in cursor.fetchall()]
        return jsonify(results)
    except Exception as e:
        logging.error(f"get_group_stats_api 出错: {e}", exc_info=True)
        return jsonify({"error": "获取发布组统计信息失败"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
