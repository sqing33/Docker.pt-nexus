# routes.py

import json
import logging
import copy
import uuid
from flask import Blueprint, jsonify, request
from threading import Thread
from datetime import datetime, timedelta
from collections import defaultdict
from functools import cmp_to_key

import services
from services import CACHE_LOCK, load_site_maps_from_db, start_data_tracker, stop_data_tracker
from utils import custom_sort_compare, format_bytes
from qbittorrentapi import Client, APIConnectionError
from transmission_rpc import Client as TrClient, TransmissionError

api_bp = Blueprint('api', __name__, url_prefix='/api')

db_manager = None
config_manager = None


def initialize_routes(manager, conf_manager):
    """注入实例以供路由使用。"""
    global db_manager, config_manager
    db_manager = manager
    config_manager = conf_manager


@api_bp.route('/settings', methods=['GET'])
def get_settings():
    """获取当前配置，包括所有下载器（不含密码）。"""
    config = copy.deepcopy(config_manager.get())
    if 'downloaders' in config:
        for downloader in config['downloaders']:
            if 'password' in downloader:
                downloader['password'] = ''
    return jsonify(config)


@api_bp.route('/settings', methods=['POST'])
def update_settings():
    """
    更新并保存整个下载器列表。
    请求体应为: {'downloaders': [{...}, {...}]}
    """
    new_config_data = request.json
    if 'downloaders' not in new_config_data:
        return jsonify({"error": "请求体必须包含 'downloaders' 列表。"}), 400

    current_config = config_manager.get()
    current_downloaders = {
        d['id']: d
        for d in current_config.get('downloaders', [])
    }

    final_downloaders = []
    for new_downloader in new_config_data['downloaders']:
        downloader_id = new_downloader.get('id')
        if downloader_id and not new_downloader.get('password'):
            if downloader_id in current_downloaders:
                new_downloader['password'] = current_downloaders[
                    downloader_id].get('password', '')

        if not downloader_id:
            new_downloader['id'] = str(uuid.uuid4())

        final_downloaders.append(new_downloader)

    full_config = {"downloaders": final_downloaders}

    if config_manager.save(full_config):
        stop_data_tracker()
        db_manager.init_db()
        reconcile_and_start_tracker()
        return jsonify({"message": "配置已成功保存和应用。"}), 200
    else:
        return jsonify({"error": "无法保存配置到文件。"}), 500


def reconcile_and_start_tracker():
    """一个辅助函数，用于协调数据并启动追踪器，通常在配置更改后调用。"""
    from database import reconcile_historical_data
    reconcile_historical_data(db_manager, config_manager.get())
    start_data_tracker(db_manager, config_manager)


@api_bp.route('/test_connection', methods=['POST'])
def test_connection():
    """测试与单个下载器的连接。"""
    client_config = request.json
    client_type = client_config.get('type')
    api_config = {
        k: v
        for k, v in client_config.items()
        if k not in ['id', 'name', 'type', 'enabled']
    }

    try:
        if client_type == 'qbittorrent':
            client = Client(**api_config)
            client.auth_log_in()
            version = client.app.version
            return jsonify({"success": True, "message": f"连接成功！版本: {version}"})
        elif client_type == 'transmission':
            from services import _prepare_api_config
            tr_api_config = _prepare_api_config(client_config)
            client = TrClient(**tr_api_config)
            version = client.get_session().version
            return jsonify({"success": True, "message": f"连接成功！版本: {version}"})
        else:
            return jsonify({"success": False, "message": "无效的客户端类型。"}), 400
    except APIConnectionError as e:
        return jsonify({
            "success": False,
            "message": f"连接失败: 无法连接到主机。 {e}"
        }), 200
    except TransmissionError as e:
        return jsonify({
            "success": False,
            "message": f"连接失败: {e.message}"
        }), 200
    except Exception as e:
        return jsonify({
            "success": False,
            "message": f"连接失败: 发生未知错误 - {str(e)}"
        }), 200


# ... [时间范围和分组函数保持不变] ...
def get_date_range_and_grouping(time_range_str, for_speed=False):
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_dt, end_dt = None, now
    group_by_format = '%Y-%m-%d'
    ranges = {
        'today': (today_start, '%Y-%m-%d %H:00'),
        'yesterday': (today_start - timedelta(days=1), '%Y-%m-%d %H:00'),
        'this_week': (today_start - timedelta(days=now.weekday()), '%Y-%m-%d'),
        'last_week':
        (today_start - timedelta(days=now.weekday() + 7), '%Y-%m-%d'),
        'this_month': (today_start.replace(day=1), '%Y-%m-%d'),
        'last_month':
        ((today_start.replace(day=1) - timedelta(days=1)).replace(day=1),
         '%Y-%m-%d'),
        'last_6_months': (now - timedelta(days=180), '%Y-%m'),
        'this_year': (today_start.replace(month=1, day=1), '%Y-%m'),
        'all': (datetime(1970, 1, 2), '%Y-%m'),
        'last_12_hours': (now - timedelta(hours=12), None),
        'last_24_hours': (now - timedelta(hours=24), None)
    }
    if time_range_str in ranges:
        start_dt, group_by_format_override = ranges[time_range_str]
        if group_by_format_override: group_by_format = group_by_format_override

    if time_range_str == 'yesterday': end_dt = today_start
    if time_range_str == 'last_week':
        end_dt = today_start - timedelta(days=now.weekday())
    if time_range_str == 'last_month': end_dt = today_start.replace(day=1)

    if for_speed:
        if time_range_str in [
                'last_12_hours', 'last_24_hours', 'today', 'yesterday'
        ]:
            group_by_format = '%Y-%m-%d %H:%M'
        elif start_dt and (end_dt - start_dt).total_seconds() > 0:
            if group_by_format not in ['%Y-%m', 'CUSTOM_5_SEC_INTERVAL']:
                interval_seconds = (end_dt - start_dt).total_seconds() / 600
                if interval_seconds <= 5400: group_by_format = '%Y-%m-%d %H:00'
    return start_dt, end_dt, group_by_format


def get_time_group_fn(db_type, format_str):
    if format_str == 'CUSTOM_5_SEC_INTERVAL':
        if db_type == 'mysql':
            return "FROM_UNIXTIME(FLOOR(UNIX_TIMESTAMP(stat_datetime) / 5) * 5, '%Y-%m-%d %H:%i:%s')"
        else:
            return "STRFTIME('%Y-%m-%d %H:%M:%S', CAST(strftime('%s', stat_datetime) / 5 AS INTEGER) * 5, 'unixepoch')"
    return f"DATE_FORMAT(stat_datetime, '{format_str.replace('%M', '%i')}')" if db_type == 'mysql' else f"STRFTIME('{format_str}', stat_datetime)"


@api_bp.route('/chart_data')
def get_chart_data_api():
    time_range = request.args.get('range', 'this_week')
    start_dt, end_dt, group_by_format = get_date_range_and_grouping(time_range)
    time_group_fn = get_time_group_fn(db_manager.db_type, group_by_format)
    ph = db_manager.get_placeholder()
    # [COMPATIBILITY FIX] 查询总和，但为了前端兼容性，仍然使用旧的别名
    query = f"SELECT {time_group_fn} AS time_group, SUM(uploaded) AS qb_ul, SUM(downloaded) AS qb_dl FROM traffic_stats WHERE stat_datetime >= {ph}"
    params = [start_dt.strftime('%Y-%m-%d %H:%M:%S')]
    if end_dt:
        query += f" AND stat_datetime < {ph}"
        params.append(end_dt.strftime('%Y-%m-%d %H:%M:%S'))
    query += " GROUP BY time_group ORDER BY time_group"

    conn = None
    cursor = None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        labels = [r['time_group'] for r in rows]
        # [COMPATIBILITY FIX] 返回旧的前端期望的数据结构
        datasets = [
            {
                "time": r['time_group'],
                "qb_ul": int(r['qb_ul'] or 0),
                "qb_dl": int(r['qb_dl'] or 0),
                "tr_ul": 0,  # 将 tr 数据设为0
                "tr_dl": 0,  # 将 tr 数据设为0
            } for r in rows
        ]
        return jsonify({"labels": labels, "datasets": datasets})
    except Exception as e:
        logging.error(f"get_chart_data_api 出错: {e}", exc_info=True)
        return jsonify({"error": "获取图表数据失败"}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@api_bp.route('/speed_data')
def get_speed_data_api():
    speeds_by_client = {}
    if services.data_tracker_thread:
        with CACHE_LOCK:
            speeds_by_client = services.data_tracker_thread.latest_speeds

    total_upload_speed = sum(
        s.get('upload_speed', 0) for s in speeds_by_client.values())
    total_download_speed = sum(
        s.get('download_speed', 0) for s in speeds_by_client.values())

    # [COMPATIBILITY FIX] 伪装成旧的数据结构返回
    return jsonify({
        'qbittorrent': {
            'enabled':
            any(
                d.get('enabled')
                for d in config_manager.get().get('downloaders', [])),
            'upload_speed':
            total_upload_speed,
            'download_speed':
            total_download_speed
        },
        'transmission': {
            'enabled': False,  # 假装 transmission 未启用
            'upload_speed': 0,
            'download_speed': 0
        }
    })


@api_bp.route('/recent_speed_data')
def get_recent_speed_data_api():
    try:
        seconds_to_fetch = int(request.args.get('seconds', '60'))
    except ValueError:
        return jsonify({"error": "无效的秒数参数"}), 400

    buffer_data = []
    if services.data_tracker_thread:
        with CACHE_LOCK:
            buffer_data = list(
                services.data_tracker_thread.recent_speeds_buffer)

    # [COMPATIBILITY FIX] 适配旧前端的键名
    results = [{
        "time": r['timestamp'].strftime('%H:%M:%S'),
        "qb_ul_speed": r['total_ul_speed'],
        "qb_dl_speed": r['total_dl_speed'],
        "tr_ul_speed": 0,
        "tr_dl_speed": 0,
    } for r in sorted(buffer_data, key=lambda x: x['timestamp'])]

    seconds_missing = seconds_to_fetch - len(results)
    db_data = []
    if seconds_missing > 0:
        conn = None
        cursor = None
        try:
            end_dt = buffer_data[0][
                'timestamp'] if buffer_data else datetime.now()
            ph = db_manager.get_placeholder()
            conn = db_manager._get_connection()
            cursor = db_manager._get_cursor(conn)
            query = f"SELECT stat_datetime, SUM(upload_speed) as ul_speed, SUM(download_speed) as dl_speed FROM traffic_stats WHERE stat_datetime < {ph} GROUP BY stat_datetime ORDER BY stat_datetime DESC LIMIT {ph}"
            params = [end_dt.strftime('%Y-%m-%d %H:%M:%S'), seconds_missing]
            cursor.execute(query, tuple(params))
            for row in reversed(cursor.fetchall()):
                dt_obj = row['stat_datetime']
                if isinstance(dt_obj, str):
                    dt_obj = datetime.strptime(dt_obj, '%Y-%m-%d %H:%M:%S')
                # [COMPATIBILITY FIX] 适配旧前端的键名
                db_data.append({
                    "time": dt_obj.strftime('%H:%M:%S'),
                    "qb_ul_speed": row['ul_speed'] or 0,
                    "qb_dl_speed": row['dl_speed'] or 0,
                    "tr_ul_speed": 0,
                    "tr_dl_speed": 0
                })
        except Exception as e:
            logging.error(f"获取历史速度数据失败: {e}", exc_info=True)
        finally:
            if cursor: cursor.close()
            if conn: conn.close()

    final_results = db_data + results
    return jsonify(final_results[-seconds_to_fetch:])


@api_bp.route('/speed_chart_data')
def get_speed_chart_data_api():
    time_range = request.args.get('range', 'last_12_hours')
    conn = None
    cursor = None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        start_dt, end_dt, group_by_format = get_date_range_and_grouping(
            time_range, for_speed=True)
        time_group_fn = get_time_group_fn(db_manager.db_type, group_by_format)

        # [COMPATIBILITY FIX] 查询总和，但为了前端兼容性，仍然使用旧的别名
        query = f"SELECT {time_group_fn} AS time_group, AVG(total_ul_speed) AS qb_ul_speed, AVG(total_dl_speed) AS qb_dl_speed FROM (SELECT stat_datetime, SUM(upload_speed) AS total_ul_speed, SUM(download_speed) AS total_dl_speed FROM traffic_stats GROUP BY stat_datetime) AS aggregated_speeds WHERE stat_datetime >= {db_manager.get_placeholder()}"
        params = [start_dt.strftime('%Y-%m-%d %H:%M:%S')]
        if end_dt:
            query += f" AND stat_datetime < {db_manager.get_placeholder()}"
            params.append(end_dt.strftime('%Y-%m-%d %H:%M:%S'))
        query += " GROUP BY time_group ORDER BY time_group"

        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        labels = [r['time_group'] for r in rows]
        # [COMPATIBILITY FIX] 返回旧的前端期望的数据结构
        datasets = [{
            "time": r['time_group'],
            "qb_ul_speed": float(r['qb_ul_speed'] or 0),
            "qb_dl_speed": float(r['qb_dl_speed'] or 0),
            "tr_ul_speed": 0,
            "tr_dl_speed": 0,
        } for r in rows]
        return jsonify({"labels": labels, "datasets": datasets})
    except Exception as e:
        logging.error(f"get_speed_chart_data_api 出错: {e}", exc_info=True)
        return jsonify({"error": "获取速度图表数据失败"}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@api_bp.route('/downloader_info')
def get_downloader_info_api():
    cfg_downloaders = config_manager.get().get('downloaders', [])
    info = {
        d['id']: {
            'name': d['name'],
            'type': d['type'],
            'enabled': d.get('enabled', False),
            'status': '未配置',
            'details': {}
        }
        for d in cfg_downloaders
    }

    conn = None
    cursor = None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        cursor.execute(
            'SELECT downloader_id, SUM(downloaded) as total_dl, SUM(uploaded) as total_ul FROM traffic_stats GROUP BY downloader_id'
        )
        totals = {r['downloader_id']: r for r in cursor.fetchall()}

        today_query = f"SELECT downloader_id, SUM(downloaded) as today_dl, SUM(uploaded) as today_ul FROM traffic_stats WHERE stat_datetime >= {db_manager.get_placeholder()} GROUP BY downloader_id"
        cursor.execute(today_query,
                       (datetime.now().strftime('%Y-%m-%d 00:00:00'), ))
        today_stats = {r['downloader_id']: r for r in cursor.fetchall()}

    except Exception as e:
        logging.error(f"获取下载器统计信息时数据库出错: {e}", exc_info=True)
        totals, today_stats = {}, {}
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

    for d_id, d_info in info.items():
        if not d_info['enabled']: continue

        total_dl = totals.get(d_id, {}).get('total_dl', 0)
        total_ul = totals.get(d_id, {}).get('total_ul', 0)
        today_dl = today_stats.get(d_id, {}).get('today_dl', 0)
        today_ul = today_stats.get(d_id, {}).get('today_ul', 0)

        details = {
            '今日下载量': format_bytes(today_dl),
            '今日上传量': format_bytes(today_ul),
            '累计下载量': format_bytes(total_dl),
            '累计上传量': format_bytes(total_ul)
        }

        client_config = next(
            (item for item in cfg_downloaders if item["id"] == d_id), None)
        api_config = {
            k: v
            for k, v in client_config.items()
            if k not in ['id', 'name', 'type', 'enabled']
        }

        try:
            if d_info['type'] == 'qbittorrent':
                client = Client(**api_config)
                client.auth_log_in()
                details['版本'] = client.app.version
            elif d_info['type'] == 'transmission':
                from services import _prepare_api_config
                tr_api_config = _prepare_api_config(client_config)
                client = TrClient(**tr_api_config)
                details['版本'] = client.get_session().version
            d_info['status'] = '已连接'
        except Exception as e:
            d_info['status'] = '连接失败'
            details['错误信息'] = str(e)
        d_info['details'] = details

    return jsonify(list(info.values()))


@api_bp.route('/data')
def get_data_api():
    page = int(request.args.get('page', 1))
    page_size = int(request.args.get('pageSize', 50))

    try:
        path_filters_str = request.args.get('path_filters', '[]')
        path_filters = json.loads(path_filters_str) if path_filters_str else []
    except json.JSONDecodeError:
        path_filters = []

    try:
        state_filters_str = request.args.get('state_filters', '[]')
        state_filters = json.loads(
            state_filters_str) if state_filters_str else []
    except json.JSONDecodeError:
        state_filters = []

    site_filter_existence = request.args.get('siteFilterExistence', 'all')
    site_filter_name = request.args.get('siteFilterName')
    name_search = request.args.get('nameSearch', '').lower()
    sort_prop = request.args.get('sortProp')
    sort_order = request.args.get('sortOrder')

    conn = None
    cursor = None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        cursor.execute(
            "SELECT DISTINCT sites FROM torrents WHERE sites IS NOT NULL AND sites != ''"
        )
        all_discovered_sites = sorted(
            [row['sites'] for row in cursor.fetchall()])

        cursor.execute("SELECT * FROM torrents")
        torrents_raw = [dict(row) for row in cursor.fetchall()]

        cursor.execute(
            "SELECT hash, SUM(uploaded) as total_uploaded FROM torrent_upload_stats GROUP BY hash"
        )
        uploads_by_hash = {
            row['hash']: row['total_uploaded']
            for row in cursor.fetchall()
        }

        agg_torrents = defaultdict(
            lambda: {
                'name': '',
                'save_path': '',
                'size': 0,
                'progress': 0,
                'state': set(),
                'sites': defaultdict(lambda: {
                    'comment': '',
                    'uploaded': 0
                }),
                'total_uploaded': 0
            })

        for t in torrents_raw:
            name = t['name']
            agg = agg_torrents[name]

            if not agg['name']:
                agg['name'] = name
                agg['save_path'] = t.get('save_path', '')
                agg['size'] = t.get('size', 0)

            agg['progress'] = max(agg.get('progress', 0), t.get('progress', 0))
            agg['state'].add(t.get('state', 'N/A'))

            upload_for_this_hash = uploads_by_hash.get(t['hash'], 0)
            agg['total_uploaded'] += upload_for_this_hash

            site_name = t.get('sites')
            if site_name:
                agg['sites'][site_name]['uploaded'] += upload_for_this_hash
                agg['sites'][site_name]['comment'] = t.get('details')

        final_torrent_list = []
        for name, data in agg_torrents.items():
            data['state'] = ', '.join(sorted(list(data['state'])))
            data['size_formatted'] = format_bytes(data['size'])
            data['total_uploaded_formatted'] = format_bytes(
                data['total_uploaded'])
            data['site_count'] = len(data.get('sites', {}))
            data['total_site_count'] = len(all_discovered_sites)
            final_torrent_list.append(data)

        filtered_list = final_torrent_list
        if name_search:
            filtered_list = [
                t for t in filtered_list if name_search in t['name'].lower()
            ]
        if path_filters:
            filtered_list = [
                t for t in filtered_list if t.get('save_path') in path_filters
            ]
        if state_filters:
            filtered_list = [
                t for t in filtered_list
                for s in t.get('state', '').split(', ') if s in state_filters
            ]
        if site_filter_existence != 'all' and site_filter_name:
            if site_filter_existence == 'exists':
                filtered_list = [
                    t for t in filtered_list
                    if site_filter_name in t.get('sites', {})
                ]
            elif site_filter_existence == 'not-exists':
                filtered_list = [
                    t for t in filtered_list
                    if site_filter_name not in t.get('sites', {})
                ]

        if sort_prop and sort_order:
            reverse = sort_order == 'descending'
            sort_key_map = {
                'size_formatted': 'size',
                'progress': 'progress',
                'total_uploaded_formatted': 'total_uploaded',
                'site_count': 'site_count'
            }
            sort_key = sort_key_map.get(sort_prop)
            if sort_key:
                filtered_list.sort(key=lambda x: x.get(sort_key, 0),
                                   reverse=reverse)
            else:
                filtered_list.sort(
                    key=cmp_to_key(lambda a, b: custom_sort_compare(a, b)),
                    reverse=reverse)
        else:
            filtered_list.sort(key=cmp_to_key(custom_sort_compare))

        total_items = len(filtered_list)
        paginated_data = filtered_list[(page - 1) * page_size:page * page_size]

        unique_paths = sorted(
            list(
                set(
                    row.get('save_path') for row in torrents_raw
                    if row.get('save_path'))))
        unique_states = sorted(
            list(
                set(
                    row.get('state') for row in torrents_raw
                    if row.get('state'))))
        _, site_link_rules_from_db, _ = load_site_maps_from_db(db_manager)

        return jsonify({
            'data': paginated_data,
            'total': total_items,
            'page': page,
            'pageSize': page_size,
            'unique_paths': unique_paths,
            'unique_states': unique_states,
            'all_discovered_sites': all_discovered_sites,
            'site_link_rules': site_link_rules_from_db,
            'active_path_filters': path_filters,
            'error': None
        })

    except Exception as e:
        logging.error(f"get_data_api 出错: {e}", exc_info=True)
        return jsonify({"error": "从数据库检索种子数据失败"}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@api_bp.route('/refresh_data', methods=['POST'])
def refresh_data_api():
    try:
        if services.data_tracker_thread:
            Thread(target=services.data_tracker_thread._update_torrents_in_db
                   ).start()
            return jsonify({"message": "后台刷新已触发"}), 202
        else:
            return jsonify({"message": "数据追踪服务未运行，无法刷新。"}), 400
    except Exception as e:
        logging.error(f"触发刷新失败: {e}")
        return jsonify({"error": "触发刷新失败"}), 500


@api_bp.route('/site_stats')
def get_site_stats_api():
    conn = None
    cursor = None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        query = "SELECT sites, SUM(size) as total_size, COUNT(name) as torrent_count FROM (SELECT DISTINCT name, size, sites FROM torrents WHERE sites IS NOT NULL AND sites != '') AS unique_torrents GROUP BY sites;"
        cursor.execute(query)
        rows = cursor.fetchall()
        results = sorted([{
            "site_name": row['sites'],
            "total_size": int(row['total_size'] or 0),
            "torrent_count": int(row['torrent_count'] or 0)
        } for row in rows],
                         key=lambda x: x['site_name'])
        return jsonify(results)
    except Exception as e:
        logging.error(f"get_site_stats_api 出错: {e}", exc_info=True)
        return jsonify({"error": "从数据库获取站点统计信息失败"}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@api_bp.route('/group_stats')
def get_group_stats_api():
    conn = None
    cursor = None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        is_mysql = db_manager.db_type == 'mysql'
        if is_mysql:
            group_col_quoted, group_concat_expr, join_condition = '`group`', "GROUP_CONCAT(DISTINCT ut.`group` ORDER BY ut.`group` SEPARATOR ', ')", "FIND_IN_SET(ut.`group`, s.`group`) > 0"
        else:
            group_col_quoted, group_concat_expr, join_condition = '"group"', 'GROUP_CONCAT(DISTINCT ut."group")', "',' || s.\"group\" || ',' LIKE '%,' || ut.\"group\" || ',%'"
        query = f"""SELECT s.nickname AS site_name, {group_concat_expr} AS group_suffix, COUNT(ut.name) AS torrent_count, SUM(ut.size) AS total_size FROM (SELECT name, {group_col_quoted} AS "group", MAX(size) AS size FROM torrents WHERE {group_col_quoted} IS NOT NULL AND {group_col_quoted} != '' GROUP BY name, {group_col_quoted}) AS ut JOIN sites AS s ON {join_condition} GROUP BY s.nickname ORDER BY s.nickname;"""
        cursor.execute(query)
        rows = cursor.fetchall()
        results = [{
            "site_name": row['site_name'],
            "group_suffix": row['group_suffix'],
            "torrent_count": int(row['torrent_count'] or 0),
            "total_size": int(row['total_size'] or 0)
        } for row in rows]
        return jsonify(results)
    except Exception as e:
        logging.error(f"get_group_stats_api 出错: {e}", exc_info=True)
        return jsonify({"error": "从数据库获取发布组统计信息失败"}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()
