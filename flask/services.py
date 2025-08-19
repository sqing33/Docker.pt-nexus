# services.py

import collections
import logging
import time
from datetime import datetime
from threading import Thread, Lock
from qbittorrentapi import Client
from transmission_rpc import Client as TrClient

from config import load_config
from utils import _parse_hostname_from_url, _extract_core_domain, _extract_url_from_comment, format_state, format_bytes

# --- Global Cache & Thread Definitions ---
CACHE_LOCK = Lock()
data_tracker_thread = None


def load_site_maps_from_db(db_manager):
    """Loads site and release group mappings from the database."""
    core_domain_map, link_rules, group_to_site_map_lower = {}, {}, {}
    if db_manager.db_type != 'mysql':
        logging.warning("Site mapping is only supported for MySQL backend.")
        return core_domain_map, link_rules, group_to_site_map_lower

    try:
        conn = db_manager._get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT nickname, base_url, special_tracker_domain, `group` FROM sites"
        )
        for row in cursor.fetchall():
            nickname = row.get('nickname')
            base_url = row.get('base_url')
            special_tracker = row.get('special_tracker_domain')
            groups_str = row.get('group')

            if nickname and base_url:
                link_rules[nickname] = {"base_url": base_url.strip()}

                if groups_str:
                    for group_name in groups_str.split(','):
                        clean_group_name = group_name.strip()
                        if clean_group_name:
                            group_to_site_map_lower[
                                clean_group_name.lower()] = {
                                    'original_case': clean_group_name,
                                    'site': nickname
                                }

                base_hostname = _parse_hostname_from_url(f"http://{base_url}")
                base_core = _extract_core_domain(base_hostname)
                if base_core:
                    core_domain_map[base_core] = nickname

                if special_tracker:
                    special_hostname = _parse_hostname_from_url(
                        f"http://{special_tracker}")
                    special_core = _extract_core_domain(special_hostname)
                    if special_core:
                        core_domain_map[special_core] = nickname
        cursor.close()
        conn.close()
        logging.info(
            f"Loaded {len(link_rules)} sites, created {len(core_domain_map)} core domain mappings and a global map of {len(group_to_site_map_lower)} release groups (keys are lowercased)."
        )
    except Exception as e:
        logging.error(f"Could not load site info from DB: {e}", exc_info=True)

    return core_domain_map, link_rules, group_to_site_map_lower


class DataTracker(Thread):
    """A background thread that periodically fetches stats and torrents from clients."""

    def __init__(self, db_manager, interval=1):
        super().__init__(daemon=True, name="DataTracker")
        self.db_manager = db_manager
        self.interval = interval
        self._is_running = True

        self.TRAFFIC_BATCH_WRITE_SIZE = 60
        self.traffic_buffer = []
        self.traffic_buffer_lock = Lock()

        self.latest_speeds = {
            'qb_ul_speed': 0,
            'qb_dl_speed': 0,
            'tr_ul_speed': 0,
            'tr_dl_speed': 0
        }
        self.recent_speeds_buffer = collections.deque(
            maxlen=self.TRAFFIC_BATCH_WRITE_SIZE)

        self.torrent_update_counter = 0
        config = load_config()
        self.TORRENT_UPDATE_INTERVAL = config.get('ui_settings', {}).get(
            'torrent_update_interval_seconds', 3600)

    def run(self):
        """The main loop for the data fetching thread."""
        logging.info(
            f"DataTracker thread started. Traffic update interval: {self.interval}s, Torrent update interval: {self.TORRENT_UPDATE_INTERVAL}s."
        )
        time.sleep(5)

        try:
            self._update_torrents_in_db()
        except Exception as e:
            logging.error(f"Initial torrents DB update failed: {e}",
                          exc_info=True)

        while self._is_running:
            start_time = time.monotonic()
            try:
                self._fetch_and_buffer_stats()

                self.torrent_update_counter += self.interval
                if self.torrent_update_counter >= self.TORRENT_UPDATE_INTERVAL:
                    self._update_torrents_in_db()
                    self.torrent_update_counter = 0
            except Exception as e:
                logging.error(f"Error in DataTracker loop: {e}", exc_info=True)

            elapsed = time.monotonic() - start_time
            time.sleep(max(0, self.interval - elapsed))

    def _fetch_and_buffer_stats(self):
        """Fetches speed and session data from clients and buffers it."""
        config = load_config()
        current_data = {
            'timestamp': datetime.now(),
            'qb_dl': 0,
            'qb_ul': 0,
            'qb_dl_speed': 0,
            'qb_ul_speed': 0,
            'tr_dl': 0,
            'tr_ul': 0,
            'tr_dl_speed': 0,
            'tr_ul_speed': 0
        }

        if config.get('qbittorrent', {}).get('enabled'):
            try:
                client = Client(
                    **{
                        k: v
                        for k, v in config['qbittorrent'].items()
                        if k != 'enabled'
                    })
                client.auth_log_in()
                info = client.transfer_info()
                current_data['qb_dl_speed'] = int(
                    getattr(info, 'dl_info_speed', 0))
                current_data['qb_ul_speed'] = int(
                    getattr(info, 'up_info_speed', 0))
                current_data['qb_dl'] = int(getattr(info, 'dl_info_data', 0))
                current_data['qb_ul'] = int(getattr(info, 'up_info_data', 0))
            except Exception as e:
                logging.warning(f"Could not fetch qB stats: {e}")

        if config.get('transmission', {}).get('enabled'):
            try:
                client = TrClient(
                    **{
                        k: v
                        for k, v in config['transmission'].items()
                        if k != 'enabled'
                    })
                stats = client.session_stats()
                current_data['tr_dl_speed'] = int(
                    getattr(stats, 'download_speed', 0))
                current_data['tr_ul_speed'] = int(
                    getattr(stats, 'upload_speed', 0))
                current_data['tr_dl'] = int(
                    stats.cumulative_stats.downloaded_bytes)
                current_data['tr_ul'] = int(
                    stats.cumulative_stats.uploaded_bytes)
            except Exception as e:
                logging.warning(f"Could not fetch Tr stats: {e}")

        with CACHE_LOCK:
            self.latest_speeds = {
                'qb_dl_speed': current_data['qb_dl_speed'],
                'qb_ul_speed': current_data['qb_ul_speed'],
                'tr_dl_speed': current_data['tr_dl_speed'],
                'tr_ul_speed': current_data['tr_ul_speed']
            }
            self.recent_speeds_buffer.append(current_data)

        buffer_to_flush = []
        with self.traffic_buffer_lock:
            self.traffic_buffer.append(current_data)
            if len(self.traffic_buffer) >= self.TRAFFIC_BATCH_WRITE_SIZE:
                buffer_to_flush = self.traffic_buffer
                self.traffic_buffer = []

        if buffer_to_flush:
            self._flush_traffic_buffer_to_db(buffer_to_flush)

    def _flush_traffic_buffer_to_db(self, buffer):
        """Writes the buffered traffic data to the database in a batch."""
        if not buffer: return

        logging.info(
            f"Flushing {len(buffer)} traffic data points to the database...")
        conn = None
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)
            is_mysql = self.db_manager.db_type == 'mysql'

            qb_state_sql = 'SELECT last_session_dl, last_session_ul FROM downloader_state WHERE name = %s' if is_mysql else 'SELECT last_session_dl, last_session_ul FROM downloader_state WHERE name = ?'
            tr_state_sql = 'SELECT last_cumulative_dl, last_cumulative_ul FROM downloader_state WHERE name = %s' if is_mysql else 'SELECT last_cumulative_dl, last_cumulative_ul FROM downloader_state WHERE name = ?'

            cursor.execute(qb_state_sql, ('qbittorrent', ))
            qb_row = cursor.fetchone()
            last_qb_dl = int(qb_row['last_session_dl']) if qb_row else 0
            last_qb_ul = int(qb_row['last_session_ul']) if qb_row else 0

            cursor.execute(tr_state_sql, ('transmission', ))
            tr_row = cursor.fetchone()
            last_tr_dl = int(tr_row['last_cumulative_dl']) if tr_row else 0
            last_tr_ul = int(tr_row['last_cumulative_ul']) if tr_row else 0

            params_to_insert = []
            for data_point in buffer:
                current_qb_dl = data_point['qb_dl']
                current_qb_ul = data_point['qb_ul']

                qb_dl_inc = current_qb_dl if current_qb_dl < last_qb_dl else current_qb_dl - last_qb_dl
                qb_ul_inc = current_qb_ul if current_qb_ul < last_qb_ul else current_qb_ul - last_qb_ul
                tr_dl_inc = data_point['tr_dl'] - last_tr_dl
                tr_ul_inc = data_point['tr_ul'] - last_tr_ul

                params_to_insert.append(
                    (data_point['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                     max(0, qb_dl_inc), max(0, qb_ul_inc), max(0, tr_dl_inc),
                     max(0, tr_ul_inc), data_point['qb_dl_speed'],
                     data_point['qb_ul_speed'], data_point['tr_dl_speed'],
                     data_point['tr_ul_speed']))

                last_qb_dl, last_qb_ul = current_qb_dl, current_qb_ul
                last_tr_dl, last_tr_ul = data_point['tr_dl'], data_point[
                    'tr_ul']

            if params_to_insert:
                if is_mysql:
                    sql_insert = '''INSERT INTO traffic_stats (stat_datetime, qb_downloaded, qb_uploaded, tr_downloaded, tr_uploaded, qb_download_speed, qb_upload_speed, tr_download_speed, tr_upload_speed) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE qb_downloaded = VALUES(qb_downloaded), qb_uploaded = VALUES(qb_uploaded), tr_downloaded = VALUES(tr_downloaded), tr_uploaded = VALUES(tr_uploaded), qb_download_speed = VALUES(qb_download_speed), qb_upload_speed = VALUES(qb_upload_speed), tr_download_speed = VALUES(tr_download_speed), tr_upload_speed = VALUES(tr_upload_speed)'''
                else:  # SQLite
                    sql_insert = '''INSERT INTO traffic_stats (stat_datetime, qb_downloaded, qb_uploaded, tr_downloaded, tr_uploaded, qb_download_speed, qb_upload_speed, tr_download_speed, tr_upload_speed) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(stat_datetime) DO UPDATE SET qb_downloaded = excluded.qb_downloaded, qb_uploaded = excluded.qb_uploaded, tr_downloaded = excluded.tr_downloaded, tr_uploaded = excluded.tr_uploaded, qb_download_speed = excluded.qb_download_speed, qb_upload_speed = excluded.qb_upload_speed, tr_download_speed = excluded.tr_download_speed, tr_upload_speed = excluded.tr_upload_speed'''
                cursor.executemany(sql_insert, params_to_insert)

            final_data_point = buffer[-1]
            update_qb_sql = "UPDATE downloader_state SET last_session_dl = %s, last_session_ul = %s WHERE name = %s" if is_mysql else "UPDATE downloader_state SET last_session_dl = ?, last_session_ul = ? WHERE name = ?"
            update_tr_sql = "UPDATE downloader_state SET last_cumulative_dl = %s, last_cumulative_ul = %s WHERE name = %s" if is_mysql else "UPDATE downloader_state SET last_cumulative_dl = ?, last_cumulative_ul = ? WHERE name = ?"
            cursor.execute(update_qb_sql,
                           (final_data_point['qb_dl'],
                            final_data_point['qb_ul'], 'qbittorrent'))
            cursor.execute(update_tr_sql,
                           (final_data_point['tr_dl'],
                            final_data_point['tr_ul'], 'transmission'))

            conn.commit()
            logging.info("Traffic data batch write successful.")
        except Exception as e:
            logging.error(f"Failed to flush traffic buffer to DB: {e}",
                          exc_info=True)
            if conn: conn.rollback()
        finally:
            if conn:
                cursor.close()
                conn.close()

    def _update_torrents_in_db(self):
        """Fetches the full torrent list from clients and updates the database."""
        logging.info("Starting to update torrents in the database...")
        config = load_config()
        core_domain_map, _, group_to_site_map_lower = load_site_maps_from_db(
            self.db_manager)

        all_current_hashes = set()
        is_mysql = self.db_manager.db_type == 'mysql'
        conn = None
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            clients_config = {
                'qbittorrent': config.get('qbittorrent', {}),
                'transmission': config.get('transmission', {})
            }
            for client_name, cfg in clients_config.items():
                if not cfg.get('enabled'): continue
                torrents_list = []
                try:
                    if client_name == 'qbittorrent':
                        q = Client(**{
                            k: v
                            for k, v in cfg.items() if k != 'enabled'
                        })
                        q.auth_log_in()
                        torrents_list = q.torrents_info(status_filter='all')
                    elif client_name == 'transmission':
                        tr = TrClient(**{
                            k: v
                            for k, v in cfg.items() if k != 'enabled'
                        })
                        fields = [
                            'id', 'name', 'hashString', 'downloadDir',
                            'totalSize', 'status', 'comment', 'trackers',
                            'percentDone', 'uploadedEver'
                        ]
                        torrents_list = tr.get_torrents(arguments=fields)
                except Exception as e:
                    logging.error(
                        f"Failed to connect or fetch from {client_name}: {e}")
                    continue

                logging.info(
                    f"Found {len(torrents_list)} torrents in {client_name}.")
                for t in torrents_list:
                    t_info = {
                        'name':
                        t.name,
                        'hash':
                        t.hash
                        if client_name == 'qbittorrent' else t.hash_string,
                        'save_path':
                        t.save_path
                        if client_name == 'qbittorrent' else t.download_dir,
                        'size':
                        t.size
                        if client_name == 'qbittorrent' else t.total_size,
                        'progress':
                        t.progress
                        if client_name == 'qbittorrent' else t.percent_done,
                        'state':
                        t.state if client_name == 'qbittorrent' else t.status,
                        'comment':
                        t.comment,
                        'trackers':
                        t.trackers if client_name == 'qbittorrent' else [{
                            'url':
                            tracker.get('announce')
                        } for tracker in t.trackers],
                        'uploaded':
                        t.uploaded
                        if client_name == 'qbittorrent' else t.uploaded_ever
                    }

                    all_current_hashes.add(t_info['hash'])
                    site_nickname = None
                    if t_info['trackers']:
                        for tracker_entry in t_info['trackers']:
                            hostname = _parse_hostname_from_url(
                                tracker_entry.get('url'))
                            core_domain = _extract_core_domain(hostname)
                            if core_domain in core_domain_map:
                                site_nickname = core_domain_map[core_domain]
                                break

                    torrent_group = None
                    name_lower = t_info['name'].lower()
                    found_matches = [
                        group_info['original_case'] for group_lower, group_info
                        in group_to_site_map_lower.items()
                        if group_lower in name_lower
                    ]
                    if found_matches:
                        torrent_group = sorted(found_matches,
                                               key=len,
                                               reverse=True)[0]

                    params = (t_info['hash'], t_info['name'],
                              t_info['save_path'], t_info['size'],
                              round(t_info['progress'] * 100, 1),
                              format_state(t_info['state']), site_nickname,
                              _extract_url_from_comment(t_info['comment']),
                              torrent_group, t_info['uploaded'], now_str)

                    uploaded_col = 'qb_uploaded' if client_name == 'qbittorrent' else 'tr_uploaded'
                    if is_mysql:
                        sql = f'''INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, `group`, {uploaded_col}, last_seen) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE name=VALUES(name), save_path=VALUES(save_path), size=VALUES(size), progress=VALUES(progress), state=VALUES(state), sites=VALUES(sites), details=VALUES(details), `group`=VALUES(`group`), {uploaded_col}=GREATEST(VALUES({uploaded_col}), torrents.{uploaded_col}), last_seen=VALUES(last_seen)'''
                    else:
                        sql = f'''INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, details, `group`, {uploaded_col}, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(hash) DO UPDATE SET name=excluded.name, save_path=excluded.save_path, size=excluded.size, progress=excluded.progress, state=excluded.state, sites=excluded.sites, details=excluded.details, `group`=excluded.`group`, {uploaded_col}=max(excluded.{uploaded_col}, torrents.{uploaded_col}), last_seen=excluded.last_seen'''
                    cursor.execute(sql, params)

            if all_current_hashes:
                placeholders = ', '.join(['%s' if is_mysql else '?'] *
                                         len(all_current_hashes))
                sql_delete = f"DELETE FROM torrents WHERE hash NOT IN ({placeholders})"
                non_dict_cursor = conn.cursor()
                non_dict_cursor.execute(sql_delete, tuple(all_current_hashes))
                logging.info(
                    f"Removed {non_dict_cursor.rowcount} stale torrents from DB."
                )
                non_dict_cursor.close()
            else:
                non_dict_cursor = conn.cursor()
                non_dict_cursor.execute("DELETE FROM torrents")
                logging.info(
                    "No torrents found in any client, cleared torrents table.")
                non_dict_cursor.close()

            conn.commit()
            logging.info(
                "Torrents database update cycle completed successfully.")
        except Exception as e:
            logging.error(f"Failed to update torrents in DB: {e}",
                          exc_info=True)
            if conn: conn.rollback()
        finally:
            if conn:
                cursor.close()
                conn.close()

    def stop(self):
        """Stops the thread and flushes any remaining data."""
        with self.traffic_buffer_lock:
            self._flush_traffic_buffer_to_db(self.traffic_buffer)
        self._is_running = False


def start_data_tracker(db_manager):
    """Initializes and starts the global DataTracker thread instance."""
    global data_tracker_thread
    if data_tracker_thread is None:
        data_tracker_thread = DataTracker(db_manager)
        data_tracker_thread.start()
    return data_tracker_thread
