# routes.py

import json
import logging
from flask import Blueprint, jsonify, request
from threading import Thread
from datetime import datetime, timedelta
from collections import defaultdict
from functools import cmp_to_key

from config import load_config
import services
from services import CACHE_LOCK, load_site_maps_from_db
from utils import custom_sort_compare, format_bytes
from qbittorrentapi import Client
from transmission_rpc import Client as TrClient

api_bp = Blueprint('api', __name__, url_prefix='/api')

db_manager = None


def initialize_routes(manager):
    """注入 DatabaseManager 实例以供路由使用。"""
    global db_manager
    db_manager = manager


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
    query = f"SELECT {time_group_fn} AS time_group, SUM(qb_uploaded) AS qb_ul, SUM(qb_downloaded) AS qb_dl, SUM(tr_uploaded) AS tr_ul, SUM(tr_downloaded) AS tr_dl FROM traffic_stats WHERE stat_datetime >= {ph}"
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
        datasets = [{
            "time": r['time_group'],
            "qb_ul": int(r['qb_ul'] or 0),
            "qb_dl": int(r['qb_dl'] or 0),
            "tr_ul": int(r['tr_ul'] or 0),
            "tr_dl": int(r['tr_dl'] or 0)
        } for r in rows]
        return jsonify({"labels": labels, "datasets": datasets})
    except Exception as e:
        logging.error(f"get_chart_data_api 出错: {e}", exc_info=True)
        return jsonify({"error": "获取图表数据失败"}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@api_bp.route('/speed_data')
def get_speed_data_api():
    with CACHE_LOCK:
        speeds = services.data_tracker_thread.latest_speeds
    cfg = load_config()
    return jsonify({
        'qbittorrent': {
            'enabled': cfg.get('qbittorrent', {}).get('enabled', False),
            'upload_speed': speeds['qb_ul_speed'],
            'download_speed': speeds['qb_dl_speed']
        },
        'transmission': {
            'enabled': cfg.get('transmission', {}).get('enabled', False),
            'upload_speed': speeds['tr_ul_speed'],
            'download_speed': speeds['tr_dl_speed']
        }
    })


@api_bp.route('/recent_speed_data')
def get_recent_speed_data_api():
    try:
        seconds_to_fetch = int(request.args.get('seconds', '60'))
    except ValueError:
        return jsonify({"error": "无效的秒数参数"}), 400

    with CACHE_LOCK:
        buffer_data = list(services.data_tracker_thread.recent_speeds_buffer)

    results = [{
        "time": r['timestamp'].strftime('%H:%M:%S'),
        "qb_ul_speed": r['qb_ul_speed'],
        "qb_dl_speed": r['qb_dl_speed'],
        "tr_ul_speed": r['tr_ul_speed'],
        "tr_dl_speed": r['tr_dl_speed']
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
            query = f"SELECT stat_datetime, qb_upload_speed, qb_download_speed, tr_upload_speed, tr_download_speed FROM traffic_stats WHERE stat_datetime < {ph} ORDER BY stat_datetime DESC LIMIT {ph}"
            params = [end_dt.strftime('%Y-%m-%d %H:%M:%S'), seconds_missing]
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            for row in reversed(rows):
                dt_obj = row['stat_datetime']
                if isinstance(dt_obj, str):
                    dt_obj = datetime.strptime(dt_obj, '%Y-%m-%d %H:%M:%S')

                db_data.append({
                    "time": dt_obj.strftime('%H:%M:%S'),
                    "qb_ul_speed": row['qb_upload_speed'] or 0,
                    "qb_dl_speed": row['qb_download_speed'] or 0,
                    "tr_ul_speed": row['tr_upload_speed'] or 0,
                    "tr_dl_speed": row['tr_download_speed'] or 0
                })
        except Exception as e:
            logging.error(f"获取历史速度数据失败: {e}", exc_info=True)
        finally:
            if cursor: cursor.close()
            if conn: conn.close()

    final_results = db_data + results
    if (pad_count := seconds_to_fetch - len(final_results)) > 0:
        last_time = datetime.now() - timedelta(seconds=len(final_results))
        padding = [{
            "time":
            (last_time - timedelta(seconds=i + 1)).strftime('%H:%M:%S'),
            "qb_ul_speed":
            0,
            "qb_dl_speed":
            0,
            "tr_ul_speed":
            0,
            "tr_dl_speed":
            0
        } for i in range(pad_count)]
        final_results = padding + final_results

    cfg = load_config()
    qb_enabled = cfg.get('qbittorrent', {}).get('enabled', False)
    tr_enabled = cfg.get('transmission', {}).get('enabled', False)
    for r in final_results:
        r['qb_enabled'], r['tr_enabled'] = qb_enabled, tr_enabled
    return jsonify(final_results[-seconds_to_fetch:])


@api_bp.route('/speed_chart_data')
def get_speed_chart_data_api():
    time_range = request.args.get('range', 'last_12_hours')
    conn = None
    cursor = None
    try:
        ph = db_manager.get_placeholder()
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        start_dt, end_dt, group_by_format = get_date_range_and_grouping(
            time_range, for_speed=True)
        time_group_fn = get_time_group_fn(db_manager.db_type, group_by_format)
        query = f"SELECT {time_group_fn} AS time_group, AVG(qb_upload_speed) AS qb_ul_speed, AVG(qb_download_speed) AS qb_dl_speed, AVG(tr_upload_speed) AS tr_ul_speed, AVG(tr_download_speed) AS tr_dl_speed FROM traffic_stats WHERE stat_datetime >= {ph}"
        params = [start_dt.strftime('%Y-%m-%d %H:%M:%S')]
        if end_dt:
            query += f" AND stat_datetime < {ph}"
            params.append(end_dt.strftime('%Y-%m-%d %H:%M:%S'))
        query += " GROUP BY time_group ORDER BY time_group"
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        labels = [r['time_group'] for r in rows]
        datasets = [{
            "time": r['time_group'],
            "qb_ul_speed": float(r['qb_ul_speed'] or 0),
            "qb_dl_speed": float(r['qb_dl_speed'] or 0),
            "tr_ul_speed": float(r['tr_ul_speed'] or 0),
            "tr_dl_speed": float(r['tr_dl_speed'] or 0)
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
    cfg = load_config()
    info = {
        'qbittorrent': {
            'enabled': cfg.get('qbittorrent', {}).get('enabled', False),
            'status': '未配置',
            'details': {}
        },
        'transmission': {
            'enabled': cfg.get('transmission', {}).get('enabled', False),
            'status': '未配置',
            'details': {}
        }
    }

    conn = None
    cursor = None
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        cursor.execute(
            'SELECT SUM(qb_downloaded) as qb_dl, SUM(qb_uploaded) as qb_ul, SUM(tr_downloaded) as tr_dl, SUM(tr_uploaded) as tr_ul FROM traffic_stats'
        )
        totals = cursor.fetchone() or {
            'qb_dl': 0,
            'qb_ul': 0,
            'tr_dl': 0,
            'tr_ul': 0
        }
        today_query = f"SELECT SUM(qb_downloaded) as qb_dl, SUM(qb_uploaded) as qb_ul, SUM(tr_downloaded) as tr_dl, SUM(tr_uploaded) as tr_ul FROM traffic_stats WHERE stat_datetime >= {db_manager.get_placeholder()}"
        cursor.execute(today_query,
                       (datetime.now().strftime('%Y-%m-%d 00:00:00'), ))
        today_stats = cursor.fetchone() or {
            'qb_dl': 0,
            'qb_ul': 0,
            'tr_dl': 0,
            'tr_ul': 0
        }
    except Exception as e:
        logging.error(f"获取下载器统计信息时数据库出错: {e}", exc_info=True)
        totals, today_stats = {}, {}
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

    if info['qbittorrent']['enabled']:
        details = {
            '今日下载量': format_bytes(today_stats.get('qb_dl')),
            '今日上传量': format_bytes(today_stats.get('qb_ul')),
            '累计下载量': format_bytes(totals.get('qb_dl')),
            '累计上传量': format_bytes(totals.get('qb_ul'))
        }
        try:
            client = Client(**{
                k: v
                for k, v in cfg['qbittorrent'].items() if k != 'enabled'
            })
            client.auth_log_in()
            details['版本'] = client.app.version
            info['qbittorrent']['status'] = '已连接'
        except Exception as e:
            info['qbittorrent']['status'] = '连接失败'
            details['错误信息'] = str(e)
        info['qbittorrent']['details'] = details

    if info['transmission']['enabled']:
        details = {
            '今日下载量': format_bytes(today_stats.get('tr_dl')),
            '今日上传量': format_bytes(today_stats.get('tr_ul')),
            '累计下载量': format_bytes(totals.get('tr_dl')),
            '累计上传量': format_bytes(totals.get('tr_ul'))
        }
        try:
            client = TrClient(**{
                k: v
                for k, v in cfg['transmission'].items() if k != 'enabled'
            })
            details['版本'] = client.get_session().version
            info['transmission']['status'] = '已连接'
        except Exception as e:
            info['transmission']['status'] = '连接失败'
            details['错误信息'] = str(e)
        info['transmission']['details'] = details

    return jsonify(info)


@api_bp.route('/data')
def get_data_api():
    try:
        page = int(request.args.get('page', 1))
        page_size_req = request.args.get('pageSize')
    except (TypeError, ValueError):
        page, page_size_req = 1, None

    page_size = 50
    if page_size_req:
        try:
            page_size = int(page_size_req)
        except (TypeError, ValueError):
            pass

    try:
        path_filters = json.loads(request.args.get('path_filters', '[]'))
        state_filters = json.loads(request.args.get('state_filters', '[]'))
    except json.JSONDecodeError:
        path_filters, state_filters = [], []

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
        total_site_count = len(all_discovered_sites)

        cursor.execute("SELECT * FROM torrents")
        torrents_raw = [dict(row) for row in cursor.fetchall()]

        agg_torrents = defaultdict(
            lambda: {
                'name':
                '',
                'save_path':
                '',
                'size':
                0,
                'progress':
                0,
                'state':
                set(),
                'sites':
                defaultdict(lambda: {
                    'qb_ul': 0,
                    'tr_ul': 0,
                    'comment': ''
                }),
                'qb_uploaded':
                0,
                'tr_uploaded':
                0
            })

        for t in torrents_raw:
            name = t['name']
            agg = agg_torrents[name]
            agg['name'] = name
            if not agg['save_path']: agg['save_path'] = t.get('save_path', '')
            if not agg['size']: agg['size'] = t.get('size', 0)
            agg['progress'] = max(agg.get('progress', 0), t.get('progress', 0))
            agg['state'].add(t.get('state', 'N/A'))
            agg['qb_uploaded'] += t.get('qb_uploaded', 0)
            agg['tr_uploaded'] += t.get('tr_uploaded', 0)
            site_name = t.get('sites')
            detail_url = t.get('details')
            if site_name:
                agg['sites'][site_name]['qb_ul'] += t.get('qb_uploaded', 0)
                agg['sites'][site_name]['tr_ul'] += t.get('tr_uploaded', 0)
                agg['sites'][site_name]['comment'] = detail_url

        final_torrent_list = []
        for name, data in agg_torrents.items():
            data['state'] = ', '.join(sorted(list(data['state'])))
            data['size_formatted'] = format_bytes(data.get('size', 0))
            data['qb_uploaded_formatted'] = format_bytes(
                data.get('qb_uploaded', 0))
            data['tr_uploaded_formatted'] = format_bytes(
                data.get('tr_uploaded', 0))
            data['total_uploaded'] = data.get('qb_uploaded', 0) + data.get(
                'tr_uploaded', 0)
            data['total_uploaded_formatted'] = format_bytes(
                data['total_uploaded'])
            data['site_count'] = len(data.get('sites', {}))
            data['total_site_count'] = total_site_count
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
                'qb_uploaded_formatted': 'qb_uploaded',
                'tr_uploaded_formatted': 'tr_uploaded',
                'total_uploaded_formatted': 'total_uploaded',
                'site_count': 'site_count'
            }
            sort_key = sort_key_map.get(sort_prop)
            if sort_key:
                filtered_list.sort(key=lambda x: x.get(sort_key, 0),
                                   reverse=reverse)
            else:
                filtered_list.sort(key=cmp_to_key(custom_sort_compare),
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
            'active_path_filters': [],
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
        Thread(target=services.data_tracker_thread._update_torrents_in_db
               ).start()
        return jsonify({"message": "后台刷新已触发"}), 202
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

        query = """
            SELECT sites, SUM(size) as total_size, COUNT(name) as torrent_count 
            FROM (SELECT DISTINCT name, size, sites FROM torrents WHERE sites IS NOT NULL AND sites != '') AS unique_torrents 
            GROUP BY sites;
        """
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
            group_col_quoted = '`group`'
            group_concat_expr = "GROUP_CONCAT(DISTINCT ut.`group` ORDER BY ut.`group` SEPARATOR ', ')"
            join_condition = "FIND_IN_SET(ut.`group`, s.`group`) > 0"
        else:  
            group_col_quoted = '"group"'
            group_concat_expr = 'GROUP_CONCAT(DISTINCT ut."group")'
            join_condition = "',' || s.\"group\" || ',' LIKE '%,' || ut.\"group\" || ',%'"

        query = f"""
            SELECT 
                s.nickname AS site_name, 
                {group_concat_expr} AS group_suffix, 
                COUNT(ut.name) AS torrent_count, 
                SUM(ut.size) AS total_size
            FROM (
                SELECT 
                    name, 
                    {group_col_quoted} AS "group", 
                    MAX(size) AS size 
                FROM torrents 
                WHERE {group_col_quoted} IS NOT NULL AND {group_col_quoted} != '' 
                GROUP BY name, {group_col_quoted}
            ) AS ut
            JOIN sites AS s ON {join_condition}
            GROUP BY s.nickname 
            ORDER BY s.nickname;
        """

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
