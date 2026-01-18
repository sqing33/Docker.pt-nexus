# core/iyuu.py
import logging
import time
import os
import requests
import json
import hashlib
from threading import Thread, Event
from collections import defaultdict
from datetime import datetime, timedelta


class IYUUThread(Thread):
    """IYUU后台线程，定期聚合种子信息并进行相关处理。"""

    def __init__(self, db_manager, config_manager):
        super().__init__(daemon=True, name="IYUUThread")
        self.db_manager = db_manager
        self.config_manager = config_manager
        self._is_running = True
        # 设置为6小时运行一次
        self.interval = 21600  # 6小时
        # 用于优雅停止的event
        self.shutdown_event = Event()

    def run(self):
        print("IYUUThread 线程已启动，改为手动触发模式。")
        # 等待5秒再开始执行，避免与主程序启动冲突
        time.sleep(5)

        # 注释掉定时循环逻辑，改为手动触发
        # while self._is_running:
        #     start_time = time.monotonic()
        #     try:
        #         self.process_torrents()
        #     except Exception as e:
        #         logging.error(f"IYUUThread 执行出错: {e}", exc_info=True)

        #     # 等待下次执行，可以被shutdown_event中断
        #     elapsed = time.monotonic() - start_time
        #     remaining_time = max(0, self.interval - elapsed)
        #     if remaining_time > 0:
        #         # 使用Event.wait来等待，可以被中断
        #         if self.shutdown_event.wait(timeout=remaining_time):
        #             # 如果被事件唤醒，说明要停止
        #             break

        print("IYUUThread 线程进入等待状态，等待手动触发。")
        # 线程保持运行，但不执行定时任务，等待手动触发
        while self._is_running:
            # 简单等待，可以被停止事件中断
            if self.shutdown_event.wait(timeout=60):  # 每分钟检查一次是否需要停止
                break

    def _get_configured_sites(self):
        """获取torrents表中已存在的站点列表"""
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)

            # 查询torrents表中所有不同的站点
            cursor.execute(
                "SELECT DISTINCT sites FROM torrents WHERE sites IS NOT NULL AND sites != ''"
            )
            sites_result = cursor.fetchall()

            # 提取站点名称并去重
            sites = set()
            for row in sites_result:
                site = row['sites']
                if site:
                    # 如果站点字段包含多个站点（用逗号分隔），则分割它们
                    if ',' in site:
                        site_list = site.split(',')
                        sites.update(s.strip() for s in site_list if s.strip())
                    else:
                        sites.add(site.strip())

            cursor.close()
            conn.close()

            sites_list = list(sites)
            log_iyuu_message(f"获取到 {len(sites_list)} 个已存在的站点", "INFO")
            log_iyuu_message(f"站点列表: {', '.join(sites_list)}", "INFO")

            return sites_list
        except Exception as e:
            logging.error(f"获取torrents表中的站点信息时出错: {e}", exc_info=True)
            return []

    def process_torrents(self, is_manual_trigger=False):
        """处理种子数据，按name列进行聚合"""
        from datetime import datetime
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 检查是否启用自动查询（仅在自动触发时检查）
        if not is_manual_trigger:
            config = self.config_manager.get()
            iyuu_settings = config.get("iyuu_settings", {})
            auto_query_enabled = iyuu_settings.get("auto_query_enabled", True)

            # 如果未启用自动查询，则跳过
            if not auto_query_enabled:
                log_iyuu_message("IYUU自动查询已禁用，跳过本次查询任务", "INFO")
                return

        # 获取路径过滤设置
        config = self.config_manager.get()
        iyuu_settings = config.get("iyuu_settings", {})
        path_filter_enabled = iyuu_settings.get("path_filter_enabled", False)
        selected_paths = iyuu_settings.get("selected_paths", [])

        log_iyuu_message(f"[{current_time}] 开始执行IYUU种子聚合任务", "INFO")
        conn = None
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)

            # 构建查询条件
            query_conditions = [
                "name IS NOT NULL AND name != ''",
                "size > 207374182"  # 只筛选体积大于200MB的种子
            ]
            query_params = []

            # 如果启用路径过滤，添加路径条件
            if path_filter_enabled and selected_paths:
                placeholders = ','.join([self.db_manager.get_placeholder()] * len(selected_paths))
                query_conditions.append(f"save_path IN ({placeholders})")
                query_params.extend(selected_paths)
                log_iyuu_message(f"启用路径过滤，限定路径: {', '.join(selected_paths)}", "INFO")

            # 构建完整的SQL查询
            sql_query = f"SELECT hash, name, sites, size, save_path FROM torrents WHERE {' AND '.join(query_conditions)}"

            cursor.execute(sql_query, tuple(query_params))
            torrents_raw = [dict(row) for row in cursor.fetchall()]

            # 获取配置的站点列表（用于过滤支持的站点）
            configured_sites = self._get_configured_sites()

            # 按种子名称进行聚合，记录所有同名种子（包括不支持IYUU的站点）
            all_torrents = defaultdict(list)
            for t in torrents_raw:
                torrent_name = t['name']
                site = t.get('sites', None)
                all_torrents[torrent_name].append({
                    'hash': t['hash'],
                    'sites': site,
                    'size': t.get('size', 0)
                })

            # 为聚合创建一个只包含支持站点的版本（用于选择hash进行查询）
            agg_torrents = defaultdict(list)
            for t in torrents_raw:
                torrent_name = t['name']
                site = t.get('sites', None)
                # 只有当站点是IYUU支持的站点时才添加到聚合列表中（用于选择hash）
                # 过滤掉青蛙和柠檬两个站点
                if site and site in configured_sites and site not in [
                        '青蛙', '柠檬不甜'
                ]:
                    agg_torrents[torrent_name].append({
                        'hash': t['hash'],
                        'sites': site,
                        'size': t.get('size', 0)
                    })

            # 准备写入文件的内容
            output_lines = []
            output_lines.append("=== IYUU种子聚合结果 ===\n")
            output_lines.append(
                f"聚合时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            output_lines.append(f"共聚合了 {len(agg_torrents)} 个唯一种子组\n")
            output_lines.append("=" * 50 + "\n")

            # 生成聚合结果
            for name, torrents in agg_torrents.items():
                # 选择一个hash用于后续的IYUU搜索
                selected_hash = torrents[0]['hash'] if torrents else None
                sites_list = [t['sites'] for t in torrents if t['sites']]

                # 添加聚合信息到输出内容
                output_lines.append(f"[IYUU] 种子组: {name}\n")
                output_lines.append(f"  - 包含 {len(torrents)} 个种子\n")
                output_lines.append(f"  - 选择的hash: {selected_hash}\n")
                output_lines.append(
                    f"  - 存在于站点: {', '.join(sites_list) if sites_list else '无'}\n"
                )
                output_lines.append("---\n")

            output_lines.append("=" * 50 + "\n")
            output_lines.append("=== IYUU种子聚合任务执行完成 ===\n")

            # 获取已配置的站点列表
            configured_sites = self._get_configured_sites()
            log_iyuu_message(f"数据库中存在 {len(configured_sites)} 个配置站点", "INFO")

            # 执行IYUU搜索逻辑，传递已配置的站点列表和所有种子信息
            self._perform_iyuu_search(agg_torrents, configured_sites,
                                      all_torrents)

            log_iyuu_message("=== IYUU种子聚合任务执行完成 ===", "INFO")

        except Exception as e:
            logging.error(f"处理种子数据时出错: {e}", exc_info=True)
        finally:
            if conn:
                if 'cursor' in locals() and cursor:
                    cursor.close()
                conn.close()

    def _get_existing_sites(self):
        """获取数据库中配置的站点信息"""
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)

            # 查询所有已配置的站点
            cursor.execute("SELECT nickname, base_url, site FROM sites")
            sites = {}
            for row in cursor.fetchall():
                # 以昵称为键存储站点信息
                site_data = dict(row)
                sites[site_data['nickname']] = site_data

            cursor.close()
            conn.close()

            return sites
        except Exception as e:
            logging.error(f"获取数据库站点信息时出错: {e}", exc_info=True)
            return {}

    def _get_priority_hash_for_torrent_group(self, torrent_name,
                                             all_torrents_for_name,
                                             configured_sites):
        """为种子组获取优先使用的hash，优先选择IYUU支持站点的hash
        
        Args:
            torrent_name: 种子名称
            all_torrents_for_name: 同名种子的所有记录
            configured_sites: 配置的站点列表
            
        Returns:
            tuple: (优先hash列表, 过滤后的种子列表)
        """
        # 获取IYUU支持的站点列表
        try:
            config = self.config_manager.get()
            iyuu_token = config.get("iyuu_token", "")
            if not iyuu_token:
                return [], []

            # 获取IYUU支持的站点信息
            sid_sha1, all_sites = get_filtered_sid_sha1_and_sites(
                iyuu_token, self.db_manager)

            # 创建IYUU站点映射
            iyuu_supported_sites = set()
            for site in all_sites:
                iyuu_nickname = site.get('nickname')
                if iyuu_nickname:
                    iyuu_supported_sites.add(iyuu_nickname)

            # 过滤出IYUU支持的站点种子，并按优先级排序
            iyuu_supported_torrents = []
            other_torrents = []

            for torrent in all_torrents_for_name:
                site_name = torrent.get('sites')
                if (site_name and site_name in configured_sites
                        and site_name in iyuu_supported_sites
                        and site_name not in ['青蛙', '柠檬不甜']):
                    iyuu_supported_torrents.append(torrent)
                elif site_name and site_name in configured_sites and site_name not in [
                        '青蛙', '柠檬不甜'
                ]:
                    other_torrents.append(torrent)

            # 合并列表，IYUU支持的站点在前
            priority_torrents = iyuu_supported_torrents + other_torrents

            # 提取hash列表
            priority_hashes = [t['hash'] for t in priority_torrents]

            log_iyuu_message(
                f"种子组 '{torrent_name}': 找到 {len(iyuu_supported_torrents)} 个IYUU支持站点，{len(other_torrents)} 个其他支持站点",
                "INFO")

            return priority_hashes, priority_torrents

        except Exception as e:
            logging.error(f"获取优先hash时出错: {e}", exc_info=True)
            # 出错时返回所有支持站点的hash
            filtered_torrents = [
                t for t in all_torrents_for_name
                if t.get('sites') and t['sites'] in configured_sites
                and t['sites'] not in ['青蛙', '柠檬不甜']
            ]
            return [t['hash'] for t in filtered_torrents], filtered_torrents

    def _perform_iyuu_search(self,
                             agg_torrents,
                             configured_sites,
                             all_torrents,
                             force_query=False,
                             return_stats=False):
        """执行IYUU搜索逻辑
        
        Args:
            agg_torrents: 聚合的种子数据
            configured_sites: 配置的站点列表
            all_torrents: 所有种子数据
            force_query: 是否强制查询，忽略时间间隔限制（默认False）
            return_stats: 是否返回统计信息（默认False）
            
        Returns:
            dict: 如果return_stats为True，返回统计信息；否则返回None
        """
        # 初始化统计信息
        result_stats = {
            'total_found': 0,
            'new_records': 0,
            'updated_records': 0,
            'sites_found': []
        }

        try:
            # 获取IYUU token
            config = self.config_manager.get()
            iyuu_token = config.get("iyuu_token", "")

            if not iyuu_token:
                logging.warning("IYUU Token未配置，跳过IYUU搜索。")
                return result_stats if return_stats else None

            print(f"开始执行IYUU搜索，共 {len(agg_torrents)} 个种子组")

            # 获取过滤后的sid_sha1和站点列表，只包含在torrents表中存在的站点
            sid_sha1, all_sites = get_filtered_sid_sha1_and_sites(
                iyuu_token, self.db_manager)

            # 创建站点映射
            sites_map = {site['id']: site for site in all_sites}

            # 从数据库动态创建 IYUU 'site' 字段到本地 'nickname' 的映射
            try:
                conn = self.db_manager._get_connection()
                cursor = self.db_manager._get_cursor(conn)
                cursor.execute(
                    "SELECT site, nickname FROM sites WHERE site IS NOT NULL AND site != '' AND nickname IS NOT NULL AND nickname != ''"
                )
                # 主要映射：IYUU API 'site' field -> local 'nickname'
                iyuu_site_to_db_nickname_map = {
                    row['site']: row['nickname']
                    for row in cursor.fetchall()
                }
                cursor.close()
                conn.close()
            except Exception as e:
                logging.error(f"从数据库获取站点映射时出错: {e}", exc_info=True)
                iyuu_site_to_db_nickname_map = {}

            # 获取数据库中现有的站点信息 (keyed by nickname)
            existing_sites = self._get_existing_sites()
            print(f"数据库中存在 {len(existing_sites)} 个配置站点")

            # 处理所有种子组
            test_torrents = list(agg_torrents.items())

            # 获取总种子组数
            total_torrents = len(test_torrents)

            iyuu_supported_site_nicknames = {
                site.get('nickname')
                for site in all_sites
                if site.get('nickname')
            }
            excluded_sites = {'青蛙', '柠檬不甜'}

            def chunk_list(items, chunk_size):
                for idx in range(0, len(items), chunk_size):
                    yield items[idx:idx + chunk_size]

            # 需要查询的种子组状态（仅包含支持站点的种子组）
            group_states = {}
            ordered_group_names = []
            skipped_interval_count = 0
            skipped_no_supported_count = 0

            for i, (name, torrents) in enumerate(test_torrents):
                if not self._is_running:  # 检查线程是否应该停止
                    break

                # 如果不是强制查询，则检查时间间隔
                if not force_query:
                    config = self.config_manager.get()
                    iyuu_settings = config.get("iyuu_settings", {})
                    query_interval_hours = iyuu_settings.get(
                        "query_interval_hours", 72)

                    if not self._should_query_iyuu(name, query_interval_hours):
                        skipped_interval_count += 1
                        continue

                all_torrents_for_name = all_torrents.get(name, [])

                # 过滤出支持的站点，并按优先级排序（IYUU支持站点优先）
                iyuu_supported_torrents = []
                other_torrents = []
                for torrent in all_torrents_for_name:
                    site_name = torrent.get('sites')
                    if (not site_name or site_name not in configured_sites
                            or site_name in excluded_sites):
                        continue

                    if site_name in iyuu_supported_site_nicknames:
                        iyuu_supported_torrents.append(torrent)
                    else:
                        other_torrents.append(torrent)

                filtered_torrents = iyuu_supported_torrents + other_torrents
                priority_hashes = [t['hash'] for t in filtered_torrents]

                # 如果没有支持的站点，则跳过
                if not filtered_torrents:
                    skipped_no_supported_count += 1
                    self._update_iyuu_last_check(name, [], all_torrents_for_name)
                    continue

                total_attempts = min(3, len(priority_hashes))

                group_states[name] = {
                    'index': i,
                    'filtered_torrents': filtered_torrents,
                    'priority_hashes': priority_hashes,
                    'total_attempts': total_attempts,
                    'selected_hash': None,
                    'selected_torrent': None,
                    'results': [],
                    'found': False,
                    'resolved': False,
                }
                ordered_group_names.append(name)

            # 批量查询：每次最多200个hash
            max_hashes_per_request = 200
            log_iyuu_message(
                f"批量查询模式：每批最多 {max_hashes_per_request} 个hash，最多尝试3个hash",
                "INFO")
            log_iyuu_message(
                f"待查询种子组: {len(ordered_group_names)}（跳过：间隔未到 {skipped_interval_count}，无支持站点 {skipped_no_supported_count}）",
                "INFO")

            for attempt in range(3):
                if not self._is_running:
                    break

                hash_to_groups = defaultdict(list)

                for name in ordered_group_names:
                    state = group_states.get(name)
                    if not state or state['resolved']:
                        continue

                    if attempt >= state['total_attempts']:
                        # 没有更多hash可尝试
                        state['resolved'] = True
                        state['found'] = False
                        continue

                    selected_hash = state['priority_hashes'][attempt]
                    state['selected_hash'] = selected_hash
                    if state.get('filtered_torrents') and len(
                            state['filtered_torrents']) > attempt:
                        state['selected_torrent'] = state['filtered_torrents'][
                            attempt]
                    else:
                        state['selected_torrent'] = None

                    hash_to_groups[selected_hash.lower()].append(name)

                if not hash_to_groups:
                    continue

                unique_hashes = list(hash_to_groups.keys())
                total_batches = (len(unique_hashes) + max_hashes_per_request -
                                 1) // max_hashes_per_request
                groups_in_attempt = sum(
                    len(group_names) for group_names in hash_to_groups.values())
                log_iyuu_message(
                    f"批量查询 attempt {attempt+1}/3: {groups_in_attempt} 个种子组，{len(unique_hashes)} 个hash，共 {total_batches} 批",
                    "INFO")

                combined_results = {}
                for batch_index, batch_hashes in enumerate(
                        chunk_list(unique_hashes, max_hashes_per_request),
                        start=1):
                    if not self._is_running:
                        break
                    batch_start = time.time()
                    batch_results = query_cross_seed_batch(
                        iyuu_token, batch_hashes, sid_sha1)
                    combined_results.update(batch_results or {})
                    batch_cost = time.time() - batch_start

                    hit_hashes = [
                        h for h in batch_hashes
                        if (batch_results or {}).get(h, [])
                    ]
                    hit_hash_count = len(hit_hashes)
                    miss_hash_count = len(batch_hashes) - hit_hash_count

                    groups_total = sum(
                        len(hash_to_groups.get(h, [])) for h in batch_hashes)
                    groups_hit = sum(
                        len(hash_to_groups.get(h, [])) for h in hit_hashes)
                    groups_miss = groups_total - groups_hit

                    log_iyuu_message(
                        f"批量查询 attempt {attempt+1}/3, batch {batch_index}/{total_batches}: "
                        f"hash 命中 {hit_hash_count} 未命中 {miss_hash_count} / {len(batch_hashes)}；"
                        f"种子组 命中 {groups_hit} 未命中 {groups_miss} / {groups_total}；"
                        f"耗时 {batch_cost:.2f}s",
                        "INFO")

                # 根据本次结果更新每个种子组状态
                for h_lower, group_names in hash_to_groups.items():
                    attempt_results = combined_results.get(h_lower, []) or []
                    for name in group_names:
                        state = group_states.get(name)
                        if not state or state['resolved']:
                            continue

                        if attempt_results:
                            state['results'] = attempt_results
                            state['found'] = True
                            state['resolved'] = True
                        else:
                            if attempt >= state['total_attempts'] - 1:
                                state['results'] = []
                                state['found'] = False
                                state['resolved'] = True

                resolved_found = sum(
                    1 for state in group_states.values()
                    if state.get('resolved') and state.get('found'))
                resolved_empty = sum(
                    1 for state in group_states.values()
                    if state.get('resolved') and not state.get('found'))
                pending_retry = sum(
                    1 for state in group_states.values()
                    if not state.get('resolved'))
                log_iyuu_message(
                    f"attempt {attempt+1}/3 汇总：已命中 {resolved_found}，已无结果 {resolved_empty}，待重试 {pending_retry}",
                    "INFO")

                # 如果全部resolved，则提前结束
                if group_states and all(
                        state['resolved'] for state in group_states.values()):
                    break

            # 处理查询结果并写入数据库
            groups_with_results = 0
            groups_without_results = 0
            groups_with_matched_sites = 0
            for name in ordered_group_names:
                if not self._is_running:
                    break

                state = group_states.get(name)
                if not state:
                    continue

                i = state['index']
                selected_hash = state.get('selected_hash') or ''
                selected_torrent = state.get('selected_torrent') or {}
                results = state.get('results') or []
                filtered_torrents = state.get('filtered_torrents') or []

                matched_sites = []

                if not results:
                    groups_without_results += 1
                else:
                    groups_with_results += 1
                    # 筛选出现在数据库中的站点
                    for item in results:
                        sid = item.get("sid")
                        site_info = sites_map.get(sid)

                        if not site_info:
                            continue

                        scheme = "https" if site_info.get(
                            "is_https") != 0 else "http"
                        details_page = site_info.get(
                            "details_page", "details.php?id={}").replace(
                                "{}", str(item.get("torrent_id")))
                        full_url = f"{scheme}://{site_info.get('base_url', '')}/{details_page}"

                        # 将链接中的 api 替换为 kp（例如：api.m-team.cc -> kp.m-team.cc）
                        full_url = full_url.replace("://api.", "://kp.")

                        iyuu_site_field = site_info.get("site")
                        iyuu_nickname = site_info.get("nickname")
                        db_site_name = None

                        # 优先使用 'site' 字段进行映射
                        if iyuu_site_field and iyuu_site_field in iyuu_site_to_db_nickname_map:
                            db_site_name = iyuu_site_to_db_nickname_map[
                                iyuu_site_field]
                        # 否则，直接使用 IYUU 的 nickname 作为后备
                        elif iyuu_nickname:
                            db_site_name = iyuu_nickname

                        # 检查映射到的站点名称是否在 configured_sites 中
                        if db_site_name and db_site_name in configured_sites:
                            iyuu_display_name = iyuu_nickname or iyuu_site_field or f"SID {sid}"
                            site_info_dict = existing_sites.get(
                                db_site_name, {})
                            matched_sites.append({
                                'iyuu_name': iyuu_display_name,
                                'db_name': db_site_name,
                                'url': full_url,
                                'site_info': site_info_dict
                            })

                # 统计找到的站点
                if matched_sites:
                    groups_with_matched_sites += 1
                    result_stats['total_found'] += len(matched_sites)
                    result_stats['sites_found'].extend(
                        [site['db_name'] for site in matched_sites])

                # 为缺失站点添加种子记录
                new_count = 0
                updated_count = 0
                if matched_sites:
                    torrent_data = {
                        'hash': selected_hash,
                        'name': name,
                        'save_path': (selected_torrent.get('save_path', '')
                                      if isinstance(selected_torrent, dict) else
                                      ''),
                        'size': (selected_torrent.get('size', 0)
                                 if isinstance(selected_torrent, dict) else 0),
                    }

                    new_count, updated_count = self._add_missing_site_torrents(
                        name, torrent_data, matched_sites, return_count=True)
                    result_stats['new_records'] += new_count
                    result_stats['updated_records'] += updated_count

                # 更新所有同名种子记录的iyuu_last_check时间（包括不支持IYUU的站点）
                torrent_size_for_update = None
                if isinstance(selected_torrent, dict):
                    torrent_size_for_update = selected_torrent.get('size')
                updated_rows, filled_details_count = self._update_iyuu_last_check(
                    name,
                    matched_sites,
                    all_torrents.get(name, []),
                    torrent_size=torrent_size_for_update,
                )

                if new_count > 0 or filled_details_count > 0:
                    log_iyuu_message(
                        f"种子组 '{name}': 新增 {new_count}，更新 {updated_rows}（详情 {filled_details_count}）",
                        "INFO")

            log_iyuu_message(
                f"批量查询完成：种子组 {len(ordered_group_names)}，有结果 {groups_with_results}，无结果 {groups_without_results}，"
                f"匹配到已存在站点 {groups_with_matched_sites}；新增记录 {result_stats['new_records']}，更新记录 {result_stats['updated_records']}",
                "INFO")

            return result_stats if return_stats else None

        except Exception as e:
            logging.error(f"IYUU搜索执行出错: {e}", exc_info=True)
            return result_stats if return_stats else None

    def _should_query_iyuu(self, torrent_name, query_interval_hours=72):
        """检查是否需要进行IYUU查询（根据设置的时间间隔或从未查询过）"""
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)
            ph = self.db_manager.get_placeholder()

            # 查询该种子最近一次的iyuu_last_check时间
            if self.db_manager.db_type == "postgresql":
                cursor.execute(
                    f"SELECT MAX(iyuu_last_check) as last_check FROM torrents WHERE name = {ph}",
                    (torrent_name, ))
            else:
                cursor.execute(
                    f"SELECT MAX(iyuu_last_check) as last_check FROM torrents WHERE name = {ph}",
                    (torrent_name, ))

            result = cursor.fetchone()
            last_check_str = result['last_check'] if isinstance(
                result, dict) else (result[0] if result else None)

            # 如果从未查询过，则应该查询
            if not last_check_str:
                return True

            # 解析上次查询时间
            from datetime import datetime, timedelta
            # 处理不同的时间格式
            try:
                if isinstance(last_check_str, str):
                    # 尝试解析常见的日期时间格式
                    last_check = datetime.strptime(last_check_str,
                                                   "%Y-%m-%d %H:%M:%S")
                else:
                    last_check = last_check_str
            except ValueError:
                # 如果解析失败，假设需要重新查询
                return True

            # 计算距离现在的时间差
            now = datetime.now()
            time_diff = now - last_check

            # 如果超过设置的时间间隔，则应该查询
            return time_diff > timedelta(hours=query_interval_hours)

        except Exception as e:
            logging.error(f"检查IYUU查询条件时出错: {e}", exc_info=True)
            # 出错时默认进行查询
            return True
        finally:
            if 'cursor' in locals() and cursor:
                cursor.close()
            if 'conn' in locals() and conn:
                conn.close()

    def _update_iyuu_last_check(self,
                                torrent_name,
                                matched_sites,
                                all_torrents_for_name,
                                torrent_size=None):
        """更新所有同名种子记录的iyuu_last_check时间，并为没有details内容的记录填入详情链接"""
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)
            ph = self.db_manager.get_placeholder()

            # 获取当前时间
            from datetime import datetime
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # 获取数据库中该种子的所有现有记录（如果提供 size，则按 name + size 精确匹配）
            if torrent_size is not None:
                if self.db_manager.db_type == "postgresql":
                    cursor.execute(
                        f"SELECT hash, sites, details FROM torrents WHERE name = {ph} AND size = {ph}",
                        (torrent_name, torrent_size))
                else:
                    cursor.execute(
                        f"SELECT hash, sites, details FROM torrents WHERE name = {ph} AND size = {ph}",
                        (torrent_name, torrent_size))
            else:
                if self.db_manager.db_type == "postgresql":
                    cursor.execute(
                        f"SELECT hash, sites, details FROM torrents WHERE name = {ph}",
                        (torrent_name, ))
                else:
                    cursor.execute(
                        f"SELECT hash, sites, details FROM torrents WHERE name = {ph}",
                        (torrent_name, ))
            existing_records = [dict(row) for row in cursor.fetchall()]

            updated_count = 0
            filled_details_count = 0

            # 为每条记录更新iyuu_last_check时间，并为没有details的记录填入详情链接
            for record in existing_records:
                site_name = record['sites']
                current_details = record['details']
                hash_value = record['hash']

                # 构建更新参数
                update_params = [current_time]  # iyuu_last_check时间
                update_fields = [f"iyuu_last_check = {ph}"]

                # 查找该站点在matched_sites中的详情链接
                matched_site = next(
                    (s for s in matched_sites if s['db_name'] == site_name),
                    None)

                # 如果当前记录没有details且IYUU返回了详情链接，则填入
                if (not current_details
                        or current_details.strip() == '') and matched_site:
                    update_params.append(matched_site['url'])
                    update_fields.append(f"details = {ph}")
                    filled_details_count += 1

                # 添加WHERE条件参数
                if torrent_size is not None:
                    update_params.extend([hash_value, torrent_name, torrent_size])
                else:
                    update_params.extend([hash_value, torrent_name])

                # 执行更新
                if self.db_manager.db_type == "postgresql":
                    if torrent_size is not None:
                        cursor.execute(
                            f"UPDATE torrents SET {', '.join(update_fields)} WHERE hash = {ph} AND name = {ph} AND size = {ph}",
                            update_params)
                    else:
                        cursor.execute(
                            f"UPDATE torrents SET {', '.join(update_fields)} WHERE hash = {ph} AND name = {ph}",
                            update_params)
                else:
                    if torrent_size is not None:
                        cursor.execute(
                            f"UPDATE torrents SET {', '.join(update_fields)} WHERE hash = {ph} AND name = {ph} AND size = {ph}",
                            update_params)
                    else:
                        cursor.execute(
                            f"UPDATE torrents SET {', '.join(update_fields)} WHERE hash = {ph} AND name = {ph}",
                            update_params)

                updated_count += cursor.rowcount

            conn.commit()
            return updated_count, filled_details_count

        except Exception as e:
            logging.error(f"更新种子记录iyuu_last_check时间和详情链接时出错: {e}",
                          exc_info=True)
            return 0, 0
        finally:
            if 'cursor' in locals() and cursor:
                cursor.close()
            if 'conn' in locals() and conn:
                conn.close()

    def _add_missing_site_torrents(self,
                                   torrent_name,
                                   torrent_data,
                                   matched_sites,
                                   return_count=False):
        """为缺失站点添加种子记录
        
        Args:
            torrent_name: 种子名称
            torrent_data: 种子数据
            matched_sites: 匹配的站点列表
            return_count: 是否返回新增和更新的记录数
            
        Returns:
            tuple: 如果return_count为True，返回(new_count, updated_count)；否则返回None
        """
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)
            ph = self.db_manager.get_placeholder()

            torrent_size = None
            if isinstance(torrent_data, dict):
                torrent_size = torrent_data.get('size')

            # 获取数据库中该种子已存在的所有站点记录
            if torrent_size is not None:
                if self.db_manager.db_type == "postgresql":
                    cursor.execute(
                        f"SELECT hash, sites, save_path, size, \"group\", details, downloader_id, progress, state FROM torrents WHERE name = {ph} AND size = {ph}",
                        (torrent_name, torrent_size))
                else:
                    cursor.execute(
                        f"SELECT hash, sites, save_path, size, `group`, details, downloader_id, progress, state FROM torrents WHERE name = {ph} AND size = {ph}",
                        (torrent_name, torrent_size))
            else:
                if self.db_manager.db_type == "postgresql":
                    cursor.execute(
                        f"SELECT hash, sites, save_path, size, \"group\", details, downloader_id, progress, state FROM torrents WHERE name = {ph}",
                        (torrent_name, ))
                else:
                    cursor.execute(
                        f"SELECT hash, sites, save_path, size, `group`, details, downloader_id, progress, state FROM torrents WHERE name = {ph}",
                        (torrent_name, ))
            existing_torrents = [dict(row) for row in cursor.fetchall()]

            # 提取已存在的站点列表
            existing_sites = set()
            for t in existing_torrents:
                site = t['sites']
                if site:
                    if ',' in site:
                        site_list = site.split(',')
                        existing_sites.update(s.strip() for s in site_list
                                              if s.strip())
                    else:
                        existing_sites.add(site.strip())

            # 获取IYUU返回的站点列表
            iyuu_sites = {site['db_name'] for site in matched_sites}

            # 找出缺失的站点
            missing_sites = iyuu_sites - existing_sites
            if not missing_sites:
                if return_count:
                    return 0, 0
                return None

            # 为每个缺失的站点添加记录
            for site_name in missing_sites:
                # 找到该站点的匹配信息
                matched_site = next(
                    (s for s in matched_sites if s['db_name'] == site_name),
                    None)
                if not matched_site:
                    continue

                # 使用现有种子信息创建新记录
                existing_torrent = existing_torrents[
                    0] if existing_torrents else torrent_data

                # 获取当前时间
                from datetime import datetime
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # 为缺失站点的种子记录生成唯一hash
                # 使用原始hash+站点名称+时间戳的组合来生成新的唯一hash
                import hashlib
                unique_string = f"{torrent_data['hash']}_{site_name}_{current_time}"
                new_hash = hashlib.sha1(
                    unique_string.encode('utf-8')).hexdigest()

                if self.db_manager.db_type == "postgresql":
                    cursor.execute(
                        f"INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, \"group\", details, downloader_id, last_seen, iyuu_last_check) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})",
                        (
                            new_hash,  # 使用新生成的唯一hash
                            torrent_name,
                            existing_torrent.get('save_path', ''),  # 使用已存在种子的保存路径
                            existing_torrent.get('size', 0),
                            0.0,  # 进度设为0，表示未下载
                            '未做种',  # 状态设为未做种，表示未在客户端中
                            site_name,
                            existing_torrent.get('group', ''),
                            matched_site['url'],  # 使用IYUU提供的详情链接
                            existing_torrent.get('downloader_id', None),
                            current_time,  # last_seen设为当前时间
                            current_time  # iyuu_last_check设为当前时间
                        ))
                else:
                    cursor.execute(
                        f"INSERT INTO torrents (hash, name, save_path, size, progress, state, sites, `group`, details, downloader_id, last_seen, iyuu_last_check) VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})",
                        (
                            new_hash,  # 使用新生成的唯一hash
                            torrent_name,
                            existing_torrent.get('save_path', ''),
                            existing_torrent.get('size', 0),
                            0.0,  # 进度设为0，表示未下载
                            '未做种',  # 状态设为未做种，表示未在客户端中
                            site_name,
                            existing_torrent.get('group', ''),
                            matched_site['url'],  # 使用IYUU提供的详情链接
                            existing_torrent.get('downloader_id', None),
                            current_time,  # last_seen设为当前时间
                            current_time  # iyuu_last_check设为当前时间
                        ))

            conn.commit()

            # 返回统计信息
            if return_count:
                return len(missing_sites), 0  # 新增记录数，更新记录数（这里只有新增）
            return None

        except Exception as e:
            logging.error(f"处理缺失站点种子记录时出错: {e}", exc_info=True)
            if return_count:
                return 0, 0  # 出错时返回0
            return None
        finally:
            if 'cursor' in locals() and cursor:
                cursor.close()
            if 'conn' in locals() and conn:
                conn.close()

    def _process_single_torrent(self,
                                torrent_name,
                                torrent_size,
                                force_query=True):
        """处理单个种子的IYUU查询

        Args:
            torrent_name: 种子名称
            torrent_size: 种子大小（字节）
            force_query: 是否强制查询，忽略时间间隔限制（默认True）

        Returns:
            dict: 查询结果统计信息
        """
        from datetime import datetime
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        log_iyuu_message(
            f"[{current_time}] 开始执行单个种子的IYUU查询: {torrent_name} (大小: {torrent_size} 字节)",
            "INFO")
        if force_query:
            log_iyuu_message("强制查询模式：忽略时间间隔限制", "INFO")

        # 获取路径过滤设置
        config = self.config_manager.get()
        iyuu_settings = config.get("iyuu_settings", {})
        path_filter_enabled = iyuu_settings.get("path_filter_enabled", False)
        selected_paths = iyuu_settings.get("selected_paths", [])

        # 初始化结果统计
        result_stats = {
            'total_found': 0,
            'new_records': 0,
            'updated_records': 0,
            'sites_found': []
        }

        conn = None
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)
            ph = self.db_manager.get_placeholder()

            # 构建查询条件
            query_conditions = [
                f"name = {ph}",
                f"size = {ph}",
                "size > 207374182"  # 只筛选体积大于200MB的种子
            ]
            query_params = [torrent_name, torrent_size]

            # 如果启用路径过滤，添加路径条件
            if path_filter_enabled and selected_paths:
                placeholders = ','.join([ph] * len(selected_paths))
                query_conditions.append(f"save_path IN ({placeholders})")
                query_params.extend(selected_paths)
                log_iyuu_message(f"启用路径过滤，限定路径: {', '.join(selected_paths)}", "INFO")

            # 构建完整的SQL查询
            sql_query = f"SELECT hash, name, sites, size, save_path FROM torrents WHERE {' AND '.join(query_conditions)}"

            cursor.execute(sql_query, tuple(query_params))
            torrents_raw = [dict(row) for row in cursor.fetchall()]

            if not torrents_raw:
                log_iyuu_message(f"未找到种子: {torrent_name} (大小: {torrent_size})",
                                 "WARNING")
                return result_stats

            # 获取配置的站点列表
            configured_sites = self._get_configured_sites()

            # 按种子名称进行聚合
            all_torrents = defaultdict(list)

            for t in torrents_raw:
                site = t.get('sites', None)
                torrent_info = {
                    'hash': t['hash'],
                    'sites': site,
                    'size': t.get('size', 0),
                    'save_path': t.get('save_path', '')
                }
                all_torrents[torrent_name].append(torrent_info)

            # 获取优先hash列表和过滤后的种子列表
            priority_hashes, filtered_torrents = self._get_priority_hash_for_torrent_group(
                torrent_name, all_torrents[torrent_name], configured_sites)

            if not filtered_torrents:
                log_iyuu_message(f"种子 '{torrent_name}' 没有支持的站点可用于IYUU查询",
                                 "WARNING")
                return result_stats

            log_iyuu_message(
                f"找到种子 '{torrent_name}'，包含 {len(filtered_torrents)} 个支持的站点",
                "INFO")

            # 获取已配置的站点列表
            log_iyuu_message(f"数据库中存在 {len(configured_sites)} 个配置站点", "INFO")

            # 创建agg_torrents用于_perform_iyuu_search
            agg_torrents = defaultdict(list)
            agg_torrents[torrent_name] = filtered_torrents

            # 执行IYUU搜索逻辑，传入force_query参数和结果统计
            result_stats = self._perform_iyuu_search(agg_torrents,
                                                     configured_sites,
                                                     all_torrents,
                                                     force_query=force_query,
                                                     return_stats=True)

            log_iyuu_message(f"=== 种子 '{torrent_name}' 的IYUU查询任务执行完成 ===",
                             "INFO")
            log_iyuu_message(
                f"查询结果统计: 找到 {result_stats['total_found']} 条记录，新增 {result_stats['new_records']} 条，更新 {result_stats['updated_records']} 条",
                "INFO")

            return result_stats

        except Exception as e:
            logging.error(f"处理单个种子数据时出错: {e}", exc_info=True)
            log_iyuu_message(f"处理种子时出错: {str(e)}", "ERROR")
            return result_stats
        finally:
            if conn:
                if 'cursor' in locals() and cursor:
                    cursor.close()
                conn.close()

    def stop(self):
        """停止线程"""
        print("正在停止 IYUUThread 线程...")
        self._is_running = False
        self.shutdown_event.set()


# --- IYUU API 配置 ---
API_BASE = "https://2025.iyuu.cn"
CLIENT_VERSION = "8.2.0"

# --- 请求频率控制 ---
_last_request_time = 0
_rate_limit_delay = 5.0  # 请求间隔时间（秒）


# --- IYUU 缓存管理类 ---
class IYUUSiteCache:
    """IYUU站点数据缓存管理类"""

    CACHE_EXPIRY_DAYS = 7  # 缓存过期时间（天）

    def __init__(self, cache_dir):
        """初始化缓存管理器
        
        Args:
            cache_dir: 缓存文件存储目录
        """
        self.cache_dir = cache_dir
        self.cache_file = os.path.join(cache_dir, "iyuu_site_cache.json")
        os.makedirs(cache_dir, exist_ok=True)

    def _is_cache_valid(self, cache_data):
        """检查缓存是否有效（未过期）
        
        Args:
            cache_data: 缓存数据字典
            
        Returns:
            bool: 缓存是否有效
        """
        if not cache_data or "timestamp" not in cache_data:
            return False

        try:
            cache_time = datetime.fromisoformat(cache_data["timestamp"])
            current_time = datetime.now()
            time_diff = current_time - cache_time

            return time_diff < timedelta(days=self.CACHE_EXPIRY_DAYS)
        except (ValueError, TypeError):
            return False

    def _sites_list_changed(self, cached_sites, current_sites):
        """检查站点列表是否发生变化
        
        Args:
            cached_sites: 缓存的站点列表
            current_sites: 当前的站点列表
            
        Returns:
            bool: 站点列表是否发生变化
        """
        cached_set = set(cached_sites) if cached_sites else set()
        current_set = set(current_sites) if current_sites else set()

        return cached_set != current_set

    def load_cache(self, current_sites_list):
        """加载缓存数据
        
        Args:
            current_sites_list: 当前torrents表中的站点列表
            
        Returns:
            tuple: (sid_sha1, supported_sites, needs_update)
                   如果缓存有效且站点未变化，返回缓存的数据和False
                   否则返回None, None, True
        """
        try:
            if not os.path.exists(self.cache_file):
                log_iyuu_message("未找到IYUU缓存文件，需要重新获取", "INFO")
                return None, None, True

            with open(self.cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            # 检查缓存是否过期
            if not self._is_cache_valid(cache_data):
                log_iyuu_message("IYUU缓存已过期（超过7天），需要重新获取", "INFO")
                return None, None, True

            # 检查站点列表是否变化
            cached_sites_list = cache_data.get("sites_list", [])
            if self._sites_list_changed(cached_sites_list, current_sites_list):
                log_iyuu_message("站点列表发生变化，需要重新获取sid_sha1", "INFO")
                return None, None, True

            # 缓存有效，返回缓存的数据
            sid_sha1 = cache_data.get("sid_sha1")
            supported_sites = cache_data.get("supported_sites", [])

            log_iyuu_message(
                f"使用IYUU缓存数据（缓存时间: {cache_data.get('timestamp')}）", "INFO")
            log_iyuu_message(f"缓存的sid_sha1: {sid_sha1}", "INFO")
            log_iyuu_message(f"缓存的支持站点数量: {len(supported_sites)}", "INFO")

            return sid_sha1, supported_sites, False

        except Exception as e:
            logging.error(f"加载IYUU缓存时出错: {e}", exc_info=True)
            return None, None, True

    def save_cache(self, sid_sha1, supported_sites, sites_list):
        """保存缓存数据
        
        Args:
            sid_sha1: 站点校验哈希值
            supported_sites: 支持的站点列表
            sites_list: 当前torrents表中的站点列表
        """
        try:
            cache_data = {
                "timestamp": datetime.now().isoformat(),
                "sid_sha1": sid_sha1,
                "supported_sites": supported_sites,
                "sites_list": sites_list
            }

            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)

            log_iyuu_message(f"IYUU缓存已保存到: {self.cache_file}", "INFO")
            log_iyuu_message(f"缓存包含 {len(supported_sites)} 个支持的站点", "INFO")

        except Exception as e:
            logging.error(f"保存IYUU缓存时出错: {e}", exc_info=True)


# --- IYUU API 辅助函数 ---


def get_sha1_hex(text: str) -> str:
    """计算字符串的 SHA-1 哈希值"""
    return hashlib.sha1(text.encode('utf-8')).hexdigest()


def make_api_request(method: str,
                     url: str,
                     token: str,
                     max_retries: int = 3,
                     **kwargs) -> dict:
    """
    封装 API 请求，统一处理 headers 和错误，支持重试机制。
    
    Args:
        method: HTTP方法 (GET, POST)
        url: 请求URL
        token: IYUU Token
        max_retries: 最大重试次数，默认3次
        **kwargs: 其他请求参数
    
    Returns:
        dict: API响应数据
    """
    global _last_request_time, _rate_limit_delay

    for attempt in range(max_retries):
        try:
            # 请求频率控制 - 确保请求之间有适当的延迟
            current_time = time.time()
            time_since_last_request = current_time - _last_request_time
            if time_since_last_request < _rate_limit_delay:
                sleep_time = _rate_limit_delay - time_since_last_request
                print(f"请求频率控制: 等待 {sleep_time:.2f} 秒")
                time.sleep(sleep_time)

            # 更新最后请求时间
            _last_request_time = time.time()

            # 基础 headers，包含 Token
            final_headers = {'Token': token}

            # 如果调用时传入了额外的 headers (如 Content-Type)，则进行合并
            if 'headers' in kwargs:
                # 使用 update 方法将传入的 headers 合并进来
                final_headers.update(kwargs.pop('headers'))

            if method.upper() == 'GET':
                response = requests.get(url,
                                        headers=final_headers,
                                        timeout=20,
                                        **kwargs)
            elif method.upper() == 'POST':
                response = requests.post(url,
                                         headers=final_headers,
                                         timeout=20,
                                         **kwargs)
            else:
                raise ValueError("Unsupported HTTP method")

            response.raise_for_status()  # 如果状态码不是 2xx，则抛出异常

            data = response.json()
            if data.get("code") != 0:
                error_msg = data.get("msg", "未知 API 错误")
                raise Exception(
                    f"API 错误: {error_msg} (代码: {data.get('code')})")

            return data

        except requests.exceptions.RequestException as e:
            error_msg = f"网络请求失败: {e}"
            if attempt < max_retries - 1:
                wait_time = 5 * (attempt + 1)  # 递增等待时间：5秒、10秒、15秒
                log_iyuu_message(
                    f"请求失败 (尝试 {attempt + 1}/{max_retries}): {error_msg}",
                    "WARNING")
                log_iyuu_message(f"等待 {wait_time} 秒后重试...", "INFO")
                time.sleep(wait_time)
            else:
                raise Exception(error_msg)
        except json.JSONDecodeError as e:
            error_msg = f"无法解析服务器返回的 JSON 数据: {e}"
            if attempt < max_retries - 1:
                wait_time = 5 * (attempt + 1)
                log_iyuu_message(
                    f"JSON解析失败 (尝试 {attempt + 1}/{max_retries}): {error_msg}",
                    "WARNING")
                log_iyuu_message(f"等待 {wait_time} 秒后重试...", "INFO")
                time.sleep(wait_time)
            else:
                raise Exception(error_msg)
        except Exception as e:
            error_msg = str(e)
            # 对于API错误（如token无效等），不进行重试，直接抛出
            if "API 错误" in error_msg or "Token" in error_msg:
                raise e
            # 对于其他错误，进行重试
            if attempt < max_retries - 1:
                wait_time = 5 * (attempt + 1)
                log_iyuu_message(
                    f"请求失败 (尝试 {attempt + 1}/{max_retries}): {error_msg}",
                    "WARNING")
                log_iyuu_message(f"等待 {wait_time} 秒后重试...", "INFO")
                time.sleep(wait_time)
            else:
                raise e


def get_supported_sites(token: str) -> list:
    """获取 IYUU 支持的所有可辅种站点列表"""
    print("正在获取 IYUU 支持的可辅种站点列表...")
    url = f"{API_BASE}/reseed/sites/index"
    response_data = make_api_request("GET", url, token)
    sites = response_data.get("data", {}).get("sites", [])
    print(f"从API获取到的可辅种站点数量: {len(sites) if response_data.get('data') else 0}")
    if not sites:
        raise Exception("未能获取到可辅种站点列表，请检查 Token 或 IYUU 服务状态。")
    print(f"成功获取到 {len(sites)} 个可辅种站点信息。")
    return sites


def get_sid_sha1(token: str, all_sites: list) -> str:
    """根据站点列表上报并获取 sid_sha1"""
    print("正在生成站点校验哈希 (sid_sha1)...")
    print(f"接收到的站点数量: {len(all_sites)}")

    # 打印前几个站点的信息用于调试
    for i, site in enumerate(all_sites[:5]):
        print(f"站点 {i+1}: ID={site.get('id')}, 名称={site.get('nickname')}")

    site_ids = [site['id'] for site in all_sites]
    print(f"提取的站点ID数量: {len(site_ids)}")

    if not site_ids:
        raise Exception("站点ID列表为空，无法生成sid_sha1")

    payload = {"sid_list": site_ids}
    print(f"发送的payload: {payload}")

    url = f"{API_BASE}/reseed/sites/reportExisting"

    # 这里的 headers 会被正确合并
    headers = {'Content-Type': 'application/json'}
    response_data = make_api_request("POST",
                                     url,
                                     token,
                                     json=payload,
                                     headers=headers)

    sid_sha1 = response_data.get("data", {}).get("sid_sha1")
    if not sid_sha1:
        raise Exception("未能从 API 获取 sid_sha1。")
    print("成功生成 sid_sha1。")
    return sid_sha1


def get_filtered_sid_sha1_and_sites(token: str, db_manager) -> tuple:
    """获取过滤后的sid_sha1和站点列表，只包含在torrents表中存在的站点"""
    print("=== 开始获取过滤后的sid_sha1和站点列表 ===")

    # 初始化缓存管理器
    from config import DATA_DIR
    cache = IYUUSiteCache(DATA_DIR)

    # 1. 获取torrents表中存在的站点列表
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        # 查询torrents表中所有不同的站点
        cursor.execute(
            "SELECT DISTINCT sites FROM torrents WHERE sites IS NOT NULL AND sites != ''"
        )
        sites_result = cursor.fetchall()

        # 提取站点名称并去重
        torrent_sites = set()
        for row in sites_result:
            site = row['sites'] if isinstance(row, dict) else row[0]
            if site:
                # 如果站点字段包含多个站点（用逗号分隔），则分割它们
                if ',' in site:
                    site_list = site.split(',')
                    torrent_sites.update(s.strip() for s in site_list
                                         if s.strip())
                else:
                    torrent_sites.add(site.strip())

        cursor.close()
        conn.close()

        torrent_sites_list = list(torrent_sites)
        print(f"torrents表中存在的站点数量: {len(torrent_sites_list)}")
        print(f"站点列表: {', '.join(torrent_sites_list)}")

    except Exception as e:
        logging.error(f"获取torrents表中的站点信息时出错: {e}", exc_info=True)
        raise

    # 2. 尝试从缓存加载数据
    cached_sid_sha1, cached_sites, needs_update = cache.load_cache(
        torrent_sites_list)

    if not needs_update:
        # 缓存有效，直接返回缓存的数据
        return cached_sid_sha1, cached_sites

    # 3. 缓存无效或需要更新，重新获取IYUU支持的所有可辅种站点
    try:
        supported_sites = get_supported_sites(token)
        print(f"获取到 {len(supported_sites)} 个IYUU支持的可辅种站点")
    except Exception as e:
        logging.error(f"获取IYUU支持站点列表失败: {e}")
        raise

    # 在获取站点列表和后续请求之间添加额外延迟
    print("等待额外延迟以避免请求频率过快...")
    time.sleep(2)

    # 4. 从数据库获取 site -> nickname 映射
    try:
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        cursor.execute(
            "SELECT site, nickname FROM sites WHERE site IS NOT NULL AND site != '' AND nickname IS NOT NULL AND nickname != ''"
        )
        db_site_to_nickname_map = {
            row['site']: row['nickname']
            for row in cursor.fetchall()
        }
        cursor.close()
        conn.close()
    except Exception as e:
        logging.error(f"从数据库获取站点映射时出错: {e}", exc_info=True)
        db_site_to_nickname_map = {}

    # 5. 过滤出IYUU支持且在torrents表中存在的站点
    filtered_site_ids = []
    filtered_sites = []

    # 使用集合以优化查找性能
    processed_site_ids = set()

    for site in supported_sites:
        iyuu_id = site.get('id')
        if not iyuu_id or iyuu_id in processed_site_ids:
            continue

        # 根据用户反馈：IYUU API的'site'字段与数据库'sites'表的'site'列相同
        iyuu_site_field = site.get('site')

        if iyuu_site_field and iyuu_site_field in db_site_to_nickname_map:
            # 根据 'sites.site' -> 'sites.nickname' 的映射关系，找到对应的本地昵称
            db_nickname = db_site_to_nickname_map[iyuu_site_field]

            # 根据用户反馈：'torrents.sites'列的内容与'sites.nickname'列相同
            # 所以检查这个昵称是否在 torrents 表中存在
            if db_nickname in torrent_sites:
                filtered_site_ids.append(iyuu_id)
                filtered_sites.append(site)
                processed_site_ids.add(iyuu_id)
                continue

        # 作为后备方案，如果上述逻辑不匹配，直接用IYUU的nickname匹配torrents表中的sites字段
        # (因为torrents.sites 就是 nickname)
        iyuu_nickname = site.get('nickname')
        if iyuu_nickname and iyuu_nickname in torrent_sites:
            filtered_site_ids.append(iyuu_id)
            filtered_sites.append(site)
            processed_site_ids.add(iyuu_id)

    print(f"过滤后得到 {len(filtered_site_ids)} 个支持的站点ID")
    print(f"站点ID列表: {filtered_site_ids}")

    if not filtered_site_ids:
        raise Exception("没有找到在torrents表中存在的IYUU支持站点")

    # 在发送reportExisting请求前添加额外延迟
    print("准备发送reportExisting请求，等待额外延迟...")
    time.sleep(2)

    # 5. 构建sid_sha1
    try:
        payload = {"sid_list": filtered_site_ids}
        url = f"{API_BASE}/reseed/sites/reportExisting"

        headers = {'Content-Type': 'application/json'}
        response_data = make_api_request("POST",
                                         url,
                                         token,
                                         json=payload,
                                         headers=headers)

        sid_sha1 = response_data.get("data", {}).get("sid_sha1")
        if not sid_sha1:
            raise Exception("未能从 API 获取 sid_sha1。")
        print(f"成功生成过滤后的 sid_sha1: {sid_sha1}")

        # 6. 保存缓存
        cache.save_cache(sid_sha1, filtered_sites, torrent_sites_list)

        return sid_sha1, filtered_sites
    except Exception as e:
        logging.error(f"生成sid_sha1时出错: {e}")
        raise


def query_cross_seed(token: str,
                     infohash: str,
                     sid_sha1: str,
                     max_retries: int = 3) -> list:
    """查询指定 infohash 的辅种信息，支持重试机制
    
    Args:
        token: IYUU Token
        infohash: 种子哈希值
        sid_sha1: 站点校验哈希值
        max_retries: 最大重试次数，默认3次
    
    Returns:
        list: 辅种信息列表
    """
    print(f"正在为种子 {infohash[:8]}... 查询辅种信息...")
    url = f"{API_BASE}/reseed/index/index"

    for attempt in range(max_retries):
        try:
            hashes_json_str = json.dumps([infohash.lower()])
            form_data = {
                "hash": hashes_json_str,
                "sha1": get_sha1_hex(hashes_json_str),
                "sid_sha1": sid_sha1,
                "timestamp": str(int(time.time())),
                "version": CLIENT_VERSION
            }

            # 这里的 headers 也会被正确合并
            headers = {'Content-Type': 'application/x-www-form-urlencoded'}
            response_data = make_api_request("POST",
                                             url,
                                             token,
                                             data=form_data,
                                             headers=headers)

            data = response_data.get("data", {})
            if not data or infohash.lower() not in data:
                return []

            results = data[infohash.lower()].get("torrent", [])
            return results

        except Exception as e:
            error_msg = str(e)
            # 如果是"未查询到可辅种数据"错误，不进行重试，直接返回空列表
            if "未查询到可辅种数据" in error_msg or "400" in error_msg:
                return []

            # 对于API错误（如token无效等），不进行重试，直接抛出
            if "API 错误" in error_msg or "Token" in error_msg:
                raise e

            # 对于其他错误，进行重试
            if attempt < max_retries - 1:
                wait_time = 5 * (attempt + 1)  # 递增等待时间：5秒、10秒、15秒
                log_iyuu_message(
                    f"查询辅种信息失败 (尝试 {attempt + 1}/{max_retries}): {error_msg}",
                    "WARNING")
                log_iyuu_message(f"等待 {wait_time} 秒后重试...", "INFO")
                time.sleep(wait_time)
            else:
                log_iyuu_message(f"查询辅种信息失败，已达到最大重试次数: {error_msg}", "ERROR")
                raise e

    return []  # 理论上不会执行到这里，但为了安全起见


def query_cross_seed_batch(token: str,
                           infohashes: list,
                           sid_sha1: str,
                           max_retries: int = 3) -> dict:
    """批量查询多个 infohash 的辅种信息（单次请求传入 hash 数组）

    Args:
        token: IYUU Token
        infohashes: 种子哈希列表
        sid_sha1: 站点校验哈希值
        max_retries: 最大重试次数，默认3次

    Returns:
        dict: {infohash_lower: torrent_list}
    """
    if not infohashes:
        return {}

    unique_hashes = []
    seen = set()
    for h in infohashes:
        if not h:
            continue
        h_lower = str(h).strip().lower()
        if not h_lower or h_lower in seen:
            continue
        seen.add(h_lower)
        unique_hashes.append(h_lower)

    if not unique_hashes:
        return {}

    print(f"正在批量查询 {len(unique_hashes)} 个种子辅种信息...")
    url = f"{API_BASE}/reseed/index/index"

    for attempt in range(max_retries):
        try:
            hashes_json_str = json.dumps(unique_hashes)
            form_data = {
                "hash": hashes_json_str,
                "sha1": get_sha1_hex(hashes_json_str),
                "sid_sha1": sid_sha1,
                "timestamp": str(int(time.time())),
                "version": CLIENT_VERSION
            }

            headers = {'Content-Type': 'application/x-www-form-urlencoded'}
            response_data = make_api_request("POST",
                                             url,
                                             token,
                                             data=form_data,
                                             headers=headers)

            data = response_data.get("data", {}) or {}
            result_map = {}
            for h in unique_hashes:
                entry = data.get(h) or {}
                result_map[h] = entry.get("torrent", []) or []
            return result_map

        except Exception as e:
            error_msg = str(e)
            # 对于“未查询到可辅种数据/400”等情况，视为全部无结果
            if "未查询到可辅种数据" in error_msg or "400" in error_msg:
                return {h: [] for h in unique_hashes}

            # 对于API错误（如token无效等），不进行重试，直接抛出
            if "API 错误" in error_msg or "Token" in error_msg:
                raise e

            # 对于其他错误，进行重试
            if attempt < max_retries - 1:
                wait_time = 5 * (attempt + 1)
                log_iyuu_message(
                    f"批量查询辅种信息失败 (尝试 {attempt + 1}/{max_retries}): {error_msg}",
                    "WARNING")
                log_iyuu_message(f"等待 {wait_time} 秒后重试...", "INFO")
                time.sleep(wait_time)
            else:
                log_iyuu_message(f"批量查询辅种信息失败，已达到最大重试次数: {error_msg}",
                                 "ERROR")
                raise e

    return {h: [] for h in unique_hashes}


# 全局变量
iyuu_thread = None

# IYUU日志存储
iyuu_logs = []


def log_iyuu_message(message, level="INFO"):
    """记录IYUU日志消息"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = {"timestamp": timestamp, "level": level, "message": message}
    iyuu_logs.append(log_entry)

    # 限制日志数量，只保留最近100条
    if len(iyuu_logs) > 100:
        iyuu_logs.pop(0)

    # 同时打印到控制台
    print(f"[IYUU-{level}] {timestamp} {message}")


def start_iyuu_thread(db_manager, config_manager):
    """初始化并启动全局 IYUUThread 线程实例。"""
    global iyuu_thread
    # 检查是否在调试模式下运行，避免重复启动
    import os
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        # 在调试模式下，这是监控进程，不需要启动线程
        print("检测到调试监控进程，跳过IYUU线程启动。")
        return iyuu_thread

    if iyuu_thread is None or not iyuu_thread.is_alive():
        iyuu_thread = IYUUThread(db_manager, config_manager)
        iyuu_thread.start()
        print("已创建并启动新的 IYUUThread 实例。")
    return iyuu_thread


def stop_iyuu_thread():
    """停止并清理当前的 IYUUThread 线程实例。"""
    global iyuu_thread
    if iyuu_thread and iyuu_thread.is_alive():
        iyuu_thread.stop()
        # 使用更短的超时时间，因为现在有event驱动的优雅停止
        iyuu_thread.join(timeout=2)  # 从10秒减少到2秒
        if iyuu_thread.is_alive():
            print("IYUUThread 线程仍在运行，但将强制清理引用")
        else:
            print("IYUUThread 线程已优雅停止。")
    iyuu_thread = None
