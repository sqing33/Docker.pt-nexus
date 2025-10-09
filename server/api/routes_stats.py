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
        "this_year": (today_start.replace(month=1, day=1), "%Y-%m"),
        "all": (datetime(1970, 1, 1), "%Y-%m"),
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
        # For speed data, we need higher resolution for shorter time ranges
        if time_range_str in ["today", "yesterday"]:
            group_by_format = "%Y-%m-%d %H:%M"
        elif time_range_str in [
                "this_week", "last_week"
        ] and (end_dt - start_dt).total_seconds() <= 7 * 24 * 3600:
            # For week ranges, use hourly grouping (168 points) for better resolution
            group_by_format = "%Y-%m-%d %H:00"
        elif start_dt and (end_dt - start_dt).total_seconds() > 0:
            if group_by_format not in ["%Y-%m"]:
                group_by_format = "%Y-%m-%d %H:00"
    return start_dt, end_dt, group_by_format


def get_time_group_fn(db_type, format_str):
    if db_type == "mysql":
        return f"DATE_FORMAT(stat_datetime, '{format_str.replace('%M', '%i')}')"
    elif db_type == "postgresql":
        # Convert strftime format to PostgreSQL TO_CHAR format
        pg_format = format_str.replace('%Y', 'YYYY').replace(
            '%m', 'MM').replace('%d',
                                'DD').replace('%H',
                                              'HH24').replace('%M', 'MI')
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

    # 获取下载器信息
    enabled_downloaders = [{
        "id": d["id"],
        "name": d["name"]
    } for d in config_manager.get().get("downloaders", []) if d.get("enabled")]
    downloader_ids = {d['id'] for d in enabled_downloaders}

    # 设定决策边界：48小时
    from datetime import datetime, timedelta
    long_period_threshold = datetime.now() - timedelta(hours=48)

    # 判断是否为长周期查询
    is_long_period_query = start_dt and start_dt < long_period_threshold

    conn, cursor = None, None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        if is_long_period_query:
            # 长周期查询：同时查询聚合表 traffic_stats_hourly 和原始表 traffic_stats
            logging.info(f"使用聚合表和原始表查询长时间范围数据: {time_range}")

            # 对于长周期查询，使用更粗的分组粒度（按天或月）
            if "%H" in group_by_format:
                coarse_group_format = group_by_format.split(" %H")[0]  # 去掉小时部分
            else:
                coarse_group_format = group_by_format

            time_group_fn = get_time_group_fn(db_manager.db_type,
                                              coarse_group_format)
            ph = db_manager.get_placeholder()

            # 查询聚合表 traffic_stats_hourly - 使用累计字段计算差值
            # 修改逻辑：使用更简单的方法计算时间段内的累计差值
            if db_manager.db_type == "postgresql":
                query_hourly = f"""
                    SELECT
                        {time_group_fn} AS time_group,
                        downloader_id,
                        GREATEST(0, (MAX(cumulative_uploaded) - MIN(cumulative_uploaded))::bigint) AS total_ul,
                        GREATEST(0, (MAX(cumulative_downloaded) - MIN(cumulative_downloaded))::bigint) AS total_dl
                    FROM traffic_stats_hourly
                    WHERE stat_datetime >= {ph}
                """
            else:
                query_hourly = f"""
                    SELECT
                        {time_group_fn} AS time_group,
                        downloader_id,
                        MAX(0, MAX(cumulative_uploaded) - MIN(cumulative_uploaded)) AS total_ul,
                        MAX(0, MAX(cumulative_downloaded) - MIN(cumulative_downloaded)) AS total_dl
                    FROM traffic_stats_hourly
                    WHERE stat_datetime >= {ph}
                """
            params_hourly = [start_dt.strftime("%Y-%m-%d %H:%M:%S")
                             ] if start_dt else []
            if end_dt and start_dt:
                query_hourly += f" AND stat_datetime < {ph}"
                params_hourly.append(end_dt.strftime("%Y-%m-%d %H:%M:%S"))
            query_hourly += """
                    GROUP BY time_group, downloader_id
                    ORDER BY time_group
            """

            cursor.execute(query_hourly, tuple(params_hourly))
            rows_hourly = cursor.fetchall()

            # 计算最近3天的开始时间（这部分数据可能在聚合表中不完整）
            from datetime import datetime, timedelta
            recent_threshold = datetime.now() - timedelta(days=3)
            recent_start = max(
                start_dt, recent_threshold
            ) if start_dt > recent_threshold else recent_threshold

            # 查询原始表 traffic_stats 中最近3天的数据 - 使用累计字段计算差值
            if recent_start < end_dt:
                time_group_fn_fine = get_time_group_fn(db_manager.db_type,
                                                       group_by_format)

                if db_manager.db_type == "postgresql":
                    query_fine = f"""
                        SELECT
                            {time_group_fn_fine} AS time_group,
                            downloader_id,
                            GREATEST(0, (MAX(cumulative_uploaded) - MIN(cumulative_uploaded))::bigint) AS total_ul,
                            GREATEST(0, (MAX(cumulative_downloaded) - MIN(cumulative_downloaded))::bigint) AS total_dl
                        FROM traffic_stats
                        WHERE stat_datetime >= {ph}
                    """
                else:
                    query_fine = f"""
                        SELECT
                            {time_group_fn_fine} AS time_group,
                            downloader_id,
                            MAX(0, MAX(cumulative_uploaded) - MIN(cumulative_uploaded)) AS total_ul,
                            MAX(0, MAX(cumulative_downloaded) - MIN(cumulative_downloaded)) AS total_dl
                        FROM traffic_stats
                        WHERE stat_datetime >= {ph}
                    """
                params_fine = [recent_start.strftime("%Y-%m-%d %H:%M:%S")]
                if end_dt and recent_start:
                    query_fine += f" AND stat_datetime < {ph}"
                    params_fine.append(end_dt.strftime("%Y-%m-%d %H:%M:%S"))
                query_fine += """
                        GROUP BY time_group, downloader_id
                        ORDER BY time_group
                """

                cursor.execute(query_fine, tuple(params_fine))
                rows_fine = cursor.fetchall()

                # 合并两个查询结果
                rows = rows_hourly + rows_fine
            else:
                rows = rows_hourly
        else:
            # 短周期查询：使用原始表 traffic_stats
            logging.info(f"使用原始表查询短时间范围数据: {time_range}")

            # 如果 group_by_format 为 None，设置默认值
            if not group_by_format:
                group_by_format = "%Y-%m-%d %H:00"
            time_group_fn = get_time_group_fn(db_manager.db_type,
                                              group_by_format)
            ph = db_manager.get_placeholder()

            # --- 修改 SQL 查询，使用累计字段计算差值 ---
            # 简化的累计差值计算方法
            if db_manager.db_type == "postgresql":
                query = f"""
                    SELECT
                        {time_group_fn} AS time_group,
                        downloader_id,
                        GREATEST(0, (MAX(cumulative_uploaded) - MIN(cumulative_uploaded))::bigint) AS total_ul,
                        GREATEST(0, (MAX(cumulative_downloaded) - MIN(cumulative_downloaded))::bigint) AS total_dl
                    FROM traffic_stats
                    WHERE stat_datetime >= {ph}
                """
            else:
                query = f"""
                    SELECT
                        {time_group_fn} AS time_group,
                        downloader_id,
                        MAX(0, MAX(cumulative_uploaded) - MIN(cumulative_uploaded)) AS total_ul,
                        MAX(0, MAX(cumulative_downloaded) - MIN(cumulative_downloaded)) AS total_dl
                    FROM traffic_stats
                    WHERE stat_datetime >= {ph}
                """
            params = [start_dt.strftime("%Y-%m-%d %H:%M:%S")
                      ] if start_dt else []
            if end_dt and start_dt:
                query += f" AND stat_datetime < {ph}"
                params.append(end_dt.strftime("%Y-%m-%d %H:%M:%S"))
            query += """
                    GROUP BY time_group, downloader_id
                    ORDER BY time_group
            """

            # 如果没有参数但查询中有占位符，则返回空数据
            if not params:
                logging.info(
                    "No params for chart data query, returning empty data")
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

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()

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

        # 3. 填充数据 - 修复聚合表和原始表数据覆盖问题
        # 使用累加方式处理相同时间段的数据，避免后者覆盖前者
        processed_data = {}  # 记录已处理的(time_group, downloader_id)组合

        for row in rows:
            downloader_id = row['downloader_id']
            # 只处理在当前配置中启用的下载器
            if downloader_id not in downloader_ids:
                continue

            time_group = row['time_group']
            if time_group in label_map:
                idx = label_map[time_group]
                key = (time_group, downloader_id)

                # 获取当前行的数据
                uploaded = int(row['total_ul'] or 0)
                downloaded = int(row['total_dl'] or 0)

                # 如果该时间段和下载器的组合已经处理过，则累加数据
                if key in processed_data:
                    datasets[downloader_id]['uploaded'][idx] += uploaded
                    datasets[downloader_id]['downloaded'][idx] += downloaded
                else:
                    # 首次处理该组合，直接赋值
                    datasets[downloader_id]['uploaded'][idx] = uploaded
                    datasets[downloader_id]['downloaded'][idx] = downloaded
                    processed_data[key] = True

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

    # 设定决策边界：48小时
    from datetime import datetime, timedelta
    start_dt, end_dt, group_by_format = get_date_range_and_grouping(
        time_range, for_speed=True)
    long_period_threshold = datetime.now() - timedelta(hours=48)

    # 判断是否为长周期查询
    is_long_period_query = start_dt and start_dt < long_period_threshold

    conn, cursor = None, None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        if is_long_period_query:
            # 长周期查询：同时查询聚合表 traffic_stats_hourly 和原始表 traffic_stats
            logging.info(f"使用聚合表和原始表查询长时间范围速度数据: {time_range}")

            # 对于长周期查询，检查是否需要保持小时级别的分组
            # 特别处理本周和上周的时间范围，保持小时级别的分组以提供更好的分辨率
            use_coarse_grouping = True
            if time_range in ["this_week", "last_week"
                              ] and "%H" in group_by_format:
                use_coarse_grouping = False

            if use_coarse_grouping and "%H" in group_by_format:
                coarse_group_format = group_by_format.split(" %H")[0]  # 去掉小时部分
            else:
                coarse_group_format = group_by_format

            time_group_fn = get_time_group_fn(db_manager.db_type,
                                              coarse_group_format)
            ph = db_manager.get_placeholder()

            # 查询聚合表 traffic_stats_hourly
            query_hourly = f"SELECT {time_group_fn} AS time_group, downloader_id, AVG(avg_upload_speed) AS ul_speed, AVG(avg_download_speed) AS dl_speed FROM traffic_stats_hourly WHERE stat_datetime >= {ph}"
            params_hourly = [start_dt.strftime("%Y-%m-%d %H:%M:%S")
                             ] if start_dt else []
            if end_dt and start_dt:
                query_hourly += f" AND stat_datetime < {ph}"
                params_hourly.append(end_dt.strftime("%Y-%m-%d %H:%M:%S"))
            query_hourly += " GROUP BY time_group, downloader_id ORDER BY time_group"

            cursor.execute(query_hourly, tuple(params_hourly))
            rows_hourly = cursor.fetchall()

            # 计算最近3天的开始时间（这部分数据可能在聚合表中不完整）
            from datetime import datetime, timedelta
            recent_threshold = datetime.now() - timedelta(days=3)
            recent_start = max(
                start_dt, recent_threshold
            ) if start_dt > recent_threshold else recent_threshold

            # 查询原始表 traffic_stats 中最近3天的数据
            if recent_start < end_dt:
                time_group_fn_fine = get_time_group_fn(db_manager.db_type,
                                                       group_by_format)
                query_fine = f"SELECT {time_group_fn_fine} AS time_group, downloader_id, AVG(upload_speed) AS ul_speed, AVG(download_speed) AS dl_speed FROM traffic_stats WHERE stat_datetime >= {ph}"
                params_fine = [recent_start.strftime("%Y-%m-%d %H:%M:%S")]
                if end_dt and recent_start:
                    query_fine += f" AND stat_datetime < {ph}"
                    params_fine.append(end_dt.strftime("%Y-%m-%d %H:%M:%S"))
                query_fine += " GROUP BY time_group, downloader_id ORDER BY time_group"

                cursor.execute(query_fine, tuple(params_fine))
                rows_fine = cursor.fetchall()

                # 合并两个查询结果
                rows = rows_hourly + rows_fine
            else:
                rows = rows_hourly
        else:
            # 短周期查询：使用原始表 traffic_stats
            logging.info(f"使用原始表查询短时间范围速度数据: {time_range}")

            # 如果 group_by_format 为 None，设置默认值
            if not group_by_format:
                group_by_format = "%Y-%m-%d %H:00" if not for_speed else "%Y-%m-%d %H:%M"
            time_group_fn = get_time_group_fn(db_manager.db_type,
                                              group_by_format)

            query = f"SELECT {time_group_fn} AS time_group, downloader_id, AVG(upload_speed) AS ul_speed, AVG(download_speed) AS dl_speed FROM traffic_stats WHERE stat_datetime >= {db_manager.get_placeholder()}"
            params = [start_dt.strftime("%Y-%m-%d %H:%M:%S")
                      ] if start_dt else []
            if end_dt and start_dt:
                query += f" AND stat_datetime < {db_manager.get_placeholder()}"
                params.append(end_dt.strftime("%Y-%m-%d %H:%M:%S"))
            query += " GROUP BY time_group, downloader_id ORDER BY time_group"

            # 如果没有参数但查询中有占位符，则返回空数据
            if not params:
                logging.info(
                    "No params for speed chart data query, returning empty data"
                )
                return jsonify({
                    "labels": [],
                    "datasets": [],
                    "downloaders": enabled_downloaders
                })

            # 添加调试日志
            logging.info(f"Speed chart data query: {query}")
            logging.info(f"Speed chart data params: {params}")
            logging.info(
                f"Number of placeholders in speed query: {query.count(db_manager.get_placeholder())}"
            )
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
            # 统计：先筛选做种站点为指定站点的种子，再按官组与"官组所属站点"聚合
            ph = db_manager.get_placeholder()
            if db_manager.db_type == "mysql":
                # MySQL 的查询不受影响，无需修改
                query = f"""
                    SELECT s.nickname AS site_name,
                           ut.`group` AS group_suffix,
                           COUNT(ut.name) AS torrent_count,
                           SUM(ut.size) AS total_size
                    FROM (
                        SELECT name, `group`, MAX(size) AS size
                        FROM torrents
                        WHERE `group` IS NOT NULL AND `group` != '' AND sites = {ph}
                        GROUP BY name, `group`
                    ) AS ut
                    JOIN sites AS s ON FIND_IN_SET(ut.`group`, s.`group`) > 0
                    GROUP BY s.nickname, ut.`group`
                    ORDER BY torrent_count DESC;
                """
            elif db_manager.db_type == "postgresql":
                # --- 修改开始 ---
                # 将 LIKE '%,...' 中的 % 替换为 %%
                query = f"""
                    SELECT s.nickname AS site_name,
                           ut.{group_col_quoted} AS group_suffix,
                           COUNT(ut.name) AS torrent_count,
                           SUM(ut.size) AS total_size
                    FROM (
                        SELECT name, {group_col_quoted}, MAX(size) AS size
                        FROM torrents
                        WHERE {group_col_quoted} IS NOT NULL AND {group_col_quoted} != '' AND sites = {ph}
                        GROUP BY name, {group_col_quoted}
                    ) AS ut
                    JOIN sites AS s ON (',' || s."group" || ',' LIKE '%%,' || ut.{group_col_quoted} || ',%%')
                    GROUP BY s.nickname, ut.{group_col_quoted}
                    ORDER BY torrent_count DESC;
                """
                # --- 修改结束 ---
            else:  # sqlite
                # --- 修改开始 ---
                # 将 LIKE '%,...' 中的 % 替换为 %%
                query = f"""
                    SELECT s.nickname AS site_name,
                           ut.{group_col_quoted} AS group_suffix,
                           COUNT(ut.name) AS torrent_count,
                           SUM(ut.size) AS total_size
                    FROM (
                        SELECT name, {group_col_quoted}, MAX(size) AS size
                        FROM torrents
                        WHERE {group_col_quoted} IS NOT NULL AND {group_col_quoted} != '' AND sites = {ph}
                        GROUP BY name, {group_col_quoted}
                    ) AS ut
                    JOIN sites AS s ON (',' || s."group" || ',' LIKE '%%,' || ut.{group_col_quoted} || ',%%')
                    GROUP BY s.nickname, ut.{group_col_quoted}
                    ORDER BY torrent_count DESC;
                """
                # --- 修改结束 ---

            # 同时，确保执行时使用正确的元组格式
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
            elif db_manager.db_type == "postgresql":
                query = f"""
                    SELECT s.nickname AS site_name, 
                           STRING_AGG(DISTINCT ut."group", ', ') AS group_suffix, 
                           COUNT(ut.name) AS torrent_count, SUM(ut.size) AS total_size 
                    FROM (
                        SELECT name, "group", MAX(size) AS size FROM torrents 
                        WHERE "group" IS NOT NULL AND "group" != '' GROUP BY name, "group"
                    ) AS ut 
                    JOIN sites AS s ON (',' || s."group" || ',' LIKE '%,' || ut."group" || ',%') 
                    GROUP BY s.nickname ORDER BY s.nickname;
                 """
            else:  # sqlite
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
                    JOIN sites AS s ON (',' || s."group" || ',' LIKE '%,' || ut.{group_col_quoted} || ',%')
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
