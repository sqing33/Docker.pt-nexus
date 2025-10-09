# core/iyuu.py
import logging
import time
import os
import requests
import json
import hashlib
from threading import Thread
from collections import defaultdict
from datetime import datetime


class IYUUThread(Thread):
    """IYUU后台线程，定期聚合种子信息并进行相关处理。"""

    def __init__(self, db_manager, config_manager):
        super().__init__(daemon=True, name="IYUUThread")
        self.db_manager = db_manager
        self.config_manager = config_manager
        self._is_running = True
        # 设置为6小时运行一次
        self.interval = 21600  # 6小时

    def run(self):
        print("IYUUThread 线程已启动，每6小时执行一次查询任务。")
        # 等待5秒再开始执行，避免与主程序启动冲突
        time.sleep(5)

        while self._is_running:
            start_time = time.monotonic()
            try:
                self._process_torrents()
            except Exception as e:
                logging.error(f"IYUUThread 执行出错: {e}", exc_info=True)

            # 等待下次执行
            elapsed = time.monotonic() - start_time
            time.sleep(max(0, self.interval - elapsed))

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

    def _process_torrents(self, is_manual_trigger=False):
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

        log_iyuu_message(f"[{current_time}] 开始执行IYUU种子聚合任务", "INFO")
        conn = None
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)

            # 查询所有种子数据，只筛选体积大于1GB的种子（1GB = 1073741824字节）
            cursor.execute(
                "SELECT hash, name, sites, size FROM torrents WHERE name IS NOT NULL AND name != '' AND size > 207374182"
            )
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

            # 从配置获取tmp目录，如果未设置则使用系统默认临时目录
            config = self.config_manager.get()
            iyuu_settings = config.get("iyuu_settings", {})
            tmp_dir = iyuu_settings.get("tmp_dir", "")

            # 如果配置中未指定tmp_dir，则使用系统默认临时目录
            if not tmp_dir:
                from config import TEMP_DIR
                tmp_dir = TEMP_DIR

            if not os.path.exists(tmp_dir):
                os.makedirs(tmp_dir)

            # 写入文件
            timestamp = int(time.time())
            output_file = os.path.join(tmp_dir,
                                       f"iyuu_aggregation_{timestamp}.txt")
            with open(output_file, 'w', encoding='utf-8') as f:
                f.writelines(output_lines)

            log_iyuu_message(f"IYUU种子聚合结果已保存到: {output_file}", "INFO")

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

    def _perform_iyuu_search(self, agg_torrents, configured_sites,
                             all_torrents, force_query=False):
        """执行IYUU搜索逻辑
        
        Args:
            agg_torrents: 聚合的种子数据
            configured_sites: 配置的站点列表
            all_torrents: 所有种子数据
            force_query: 是否强制查询，忽略时间间隔限制（默认False）
        """
        try:
            # 获取IYUU token
            config = self.config_manager.get()
            iyuu_token = config.get("iyuu_token", "")

            if not iyuu_token:
                logging.warning("IYUU Token未配置，跳过IYUU搜索。")
                return

            print(f"开始执行IYUU搜索，共 {len(agg_torrents)} 个种子组")

            # 获取过滤后的sid_sha1和站点列表，只包含在torrents表中存在的站点
            sid_sha1, all_sites = get_filtered_sid_sha1_and_sites(
                iyuu_token, self.db_manager)

            # 创建站点映射
            sites_map = {site['id']: site for site in all_sites}

            # 创建IYUU站点名称到数据库站点昵称的映射表
            # 只包含需要映射的站点（IYUU名称与数据库昵称不同的情况）
            site_name_mapping = {
                # IYUU名称 -> 数据库昵称
                "优堡": "我堡",
                "观众": "人人",
                "柠檬": "柠檬不酸",
                "hdclone": "HDClone",
                "我的PT(CC)": "我的PT",
                "LongPT": "龙PT",
                "March": "三月传媒",
                "hdbao": "红豆包",
                "LuckPT": "幸运",
                "13city": "13City",
                "PTSKit": "PTSkit",
                "时光": "时光HDT",
                "春天": "不可说",
            }

            # 获取数据库中现有的站点信息
            existing_sites = self._get_existing_sites()
            print(f"数据库中存在 {len(existing_sites)} 个配置站点")

            # 只处理前3个种子组用于测试
            test_torrents = list(agg_torrents.items())

            # 获取总种子组数
            total_torrents = len(test_torrents)

            for i, (name, torrents) in enumerate(test_torrents):
                if not self._is_running:  # 检查线程是否应该停止
                    break

                # 如果不是强制查询，则检查时间间隔
                if not force_query:
                    # 检查是否需要进行IYUU查询（距离上次查询超过设置的时间间隔或从未查询过）
                    # 获取设置的查询间隔时间（默认为72小时）
                    config = self.config_manager.get()
                    iyuu_settings = config.get("iyuu_settings", {})
                    query_interval_hours = iyuu_settings.get("query_interval_hours", 72)

                    if not self._should_query_iyuu(name, query_interval_hours):
                        skip_message = f"[{i+1}/{total_torrents}] 🔄 种子组 '{name}' 距离上次查询不足{query_interval_hours}小时，跳过查询"
                        log_iyuu_message(skip_message, "INFO")
                        continue

                print(f"[{i+1}/{total_torrents}] 🔍 正在处理种子组: {name}")

                # 尝试最多3个不同的hash进行查询
                max_attempts = 3
                results = None
                selected_hash = None

                # 获取当前种子组的所有torrents，按站点过滤
                filtered_torrents = [
                    t for t in torrents
                    if t.get('sites') and t['sites'] in configured_sites
                    and t['sites'] not in ['青蛙', '柠檬不甜']
                ]

                # 如果没有支持的站点，则跳过
                if not filtered_torrents:
                    log_iyuu_message(
                        f"[{i+1}/{total_torrents}] ⚠️ 种子组 '{name}' 没有支持的站点，跳过查询", "INFO"
                    )
                    # 更新所有同名种子记录的iyuu_last_check时间（包括不支持IYUU的站点）
                    self._update_iyuu_last_check(name, [],
                                                 all_torrents.get(name, []))
                    continue

                for attempt in range(min(max_attempts,
                                         len(filtered_torrents))):
                    if attempt >= len(filtered_torrents):
                        break

                    selected_hash = filtered_torrents[attempt]['hash']
                    site_name = filtered_torrents[attempt]['sites']
                    log_iyuu_message(
                        f"使用的hash [{attempt+1}/{min(max_attempts, len(filtered_torrents))}]: {selected_hash} (站点: {site_name})", "INFO"
                    )

                    try:
                        # 执行搜索
                        results = query_cross_seed(iyuu_token, selected_hash,
                                                   sid_sha1)
                        # 如果成功查询到结果，则跳出循环
                        log_iyuu_message(
                            f"[{i+1}/{total_torrents}] ✅ Hash {selected_hash[:8]}... 查询成功，停止尝试其他hash", "INFO"
                        )
                        break
                    except Exception as e:
                        error_msg = str(e)
                        # 如果是"未查询到可辅种数据"错误，则尝试下一个hash
                        if "未查询到可辅种数据" in error_msg or "400" in error_msg:
                            log_iyuu_message(
                                f"[{i+1}/{total_torrents}] ⚠️  Hash {selected_hash[:8]}... 未查询到可辅种数据，尝试下一个hash...", "INFO"
                            )
                            continue
                        else:
                            # 其他错误则重新抛出
                            raise e

                # 如果所有尝试都失败了
                if results is None:
                    log_iyuu_message(
                        f"[{i+1}/{total_torrents}] ❌ 种子组 '{name}' 所有hash都未查询到可辅种数据", "INFO"
                    )
                    # 更新所有同名种子记录的iyuu_last_check时间（包括不支持IYUU的站点）
                    self._update_iyuu_last_check(name, [],
                                                 all_torrents.get(name, []))
                    continue

                # 如果成功查询到结果，继续处理
                # 打印搜索结果并筛选现有站点
                if not results:
                    print(
                        f"[{i+1}/{total_torrents}] 种子 {selected_hash[:8]}... 未在其他站点发现。"
                    )
                else:
                    # 筛选出现在数据库中的站点
                    matched_sites = []
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

                        # 获取IYUU站点名称
                        iyuu_site_name = site_info.get(
                            "nickname") or site_info.get(
                                "site") or f"SID {sid}"

                        # 尝试映射到数据库中的站点名称
                        db_site_name = site_name_mapping.get(
                            iyuu_site_name, iyuu_site_name)

                        # 检查站点是否在torrents表中存在的站点列表中
                        if db_site_name in configured_sites:
                            # 如果站点在数据库中也有配置信息，则使用它
                            site_info_dict = existing_sites.get(
                                db_site_name, {})
                            matched_sites.append({
                                'iyuu_name': iyuu_site_name,
                                'db_name': db_site_name,
                                'url': full_url,
                                'site_info': site_info_dict
                            })

                    # 只显示匹配到的已配置站点
                    if matched_sites:
                        log_iyuu_message(
                            f"[{i+1}/{total_torrents}] 种子 {selected_hash[:8]}... 在 {len(matched_sites)} 个已存在的站点发现！", "INFO"
                        )
                        for site in matched_sites:
                            iyuu_site_name = site['iyuu_name']
                            db_site_name = site['db_name']
                            full_url = site['url']

                            if iyuu_site_name != db_site_name:
                                log_iyuu_message(
                                    f"✅ 匹配站点: {iyuu_site_name} -> {db_site_name}", "INFO"
                                )
                            else:
                                log_iyuu_message(f"✅ 匹配站点: {iyuu_site_name}", "INFO")
                            log_iyuu_message(f"   链接: {full_url}", "INFO")
                    else:
                        log_iyuu_message(
                            f"[{i+1}/{total_torrents}] 种子 {selected_hash[:8]}... 未在任何已存在的站点发现。", "INFO"
                        )

                    log_iyuu_message(f"在torrents表中找到 {len(matched_sites)} 个已存在的站点", "INFO")

                    # 为缺失站点添加种子记录
                    if matched_sites:
                        torrent_data = {
                            'hash': selected_hash,
                            'name': name,
                            'save_path': filtered_torrents[0].get('save_path', ''),
                            'size': filtered_torrents[0].get('size', 0),
                        }
                        self._add_missing_site_torrents(name, torrent_data, matched_sites)

                    # 更新所有同名种子记录的iyuu_last_check时间（包括不支持IYUU的站点）
                    self._update_iyuu_last_check(name, matched_sites,
                                                 all_torrents.get(name, []))

                # 每次查询之间间隔5秒（除了最后一个）
                if i < len(test_torrents) - 1:
                    log_iyuu_message(f"[{i+1}/{total_torrents}] 等待5秒后进行下一次查询...", "INFO")
                    for _ in range(5):  # 每秒检查一次是否需要停止
                        if not self._is_running:
                            return
                        time.sleep(1)

        except Exception as e:
            logging.error(f"IYUU搜索执行出错: {e}", exc_info=True)

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

    def _update_iyuu_last_check(self, torrent_name, matched_sites,
                                all_torrents_for_name):
        """更新所有同名种子记录的iyuu_last_check时间，并为没有details内容的记录填入详情链接"""
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)
            ph = self.db_manager.get_placeholder()

            # 获取当前时间
            from datetime import datetime
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # 获取数据库中该种子的所有现有记录
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
                update_params.extend([hash_value, torrent_name])

                # 执行更新
                if self.db_manager.db_type == "postgresql":
                    cursor.execute(
                        f"UPDATE torrents SET {', '.join(update_fields)} WHERE hash = {ph} AND name = {ph}",
                        update_params)
                else:
                    cursor.execute(
                        f"UPDATE torrents SET {', '.join(update_fields)} WHERE hash = {ph} AND name = {ph}",
                        update_params)

                updated_count += cursor.rowcount

            conn.commit()
            print(f"🔄 已更新 {updated_count} 条种子记录的iyuu_last_check时间")
            if filled_details_count > 0:
                print(f"✅ 已为 {filled_details_count} 条种子记录填入详情链接")

        except Exception as e:
            logging.error(f"更新种子记录iyuu_last_check时间和详情链接时出错: {e}",
                          exc_info=True)
        finally:
            if 'cursor' in locals() and cursor:
                cursor.close()
            if 'conn' in locals() and conn:
                conn.close()

    def _add_missing_site_torrents(self, torrent_name, torrent_data,
                                   matched_sites):
        """为缺失站点添加种子记录"""
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)
            ph = self.db_manager.get_placeholder()

            # 获取数据库中该种子已存在的所有站点记录
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

            print(
                f"发现 {len(missing_sites)} 个缺失的站点: {', '.join(missing_sites)}")

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
                print(f"✅ 已为站点 '{site_name}' 添加种子记录")

            conn.commit()
            print(f"成功处理 {len(missing_sites)} 个缺失站点的种子记录")

        except Exception as e:
            logging.error(f"处理缺失站点种子记录时出错: {e}", exc_info=True)
        finally:
            if 'cursor' in locals() and cursor:
                cursor.close()
            if 'conn' in locals() and conn:
                conn.close()

    def _process_single_torrent(self, torrent_name, torrent_size, force_query=True):
        """处理单个种子的IYUU查询
        
        Args:
            torrent_name: 种子名称
            torrent_size: 种子大小（字节）
            force_query: 是否强制查询，忽略时间间隔限制（默认True）
        """
        from datetime import datetime
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        log_iyuu_message(f"[{current_time}] 开始执行单个种子的IYUU查询: {torrent_name} (大小: {torrent_size} 字节)", "INFO")
        if force_query:
            log_iyuu_message("强制查询模式：忽略时间间隔限制", "INFO")
        
        conn = None
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)
            ph = self.db_manager.get_placeholder()
            
            # 查询指定名称和大小的种子数据，只筛选体积大于200MB的种子
            cursor.execute(
                f"SELECT hash, name, sites, size, save_path FROM torrents WHERE name = {ph} AND size = {ph} AND size > 207374182",
                (torrent_name, torrent_size)
            )
            torrents_raw = [dict(row) for row in cursor.fetchall()]
            
            if not torrents_raw:
                log_iyuu_message(f"未找到种子: {torrent_name} (大小: {torrent_size})", "WARNING")
                return
            
            # 获取配置的站点列表
            configured_sites = self._get_configured_sites()
            
            # 按种子名称进行聚合
            all_torrents = defaultdict(list)
            agg_torrents = defaultdict(list)
            
            for t in torrents_raw:
                site = t.get('sites', None)
                torrent_info = {
                    'hash': t['hash'],
                    'sites': site,
                    'size': t.get('size', 0),
                    'save_path': t.get('save_path', '')
                }
                all_torrents[torrent_name].append(torrent_info)
                
                # 只有当站点是IYUU支持的站点时才添加到聚合列表中
                if site and site in configured_sites and site not in ['青蛙', '柠檬不甜']:
                    agg_torrents[torrent_name].append(torrent_info)
            
            if not agg_torrents:
                log_iyuu_message(f"种子 '{torrent_name}' 没有支持的站点可用于IYUU查询", "WARNING")
                return
            
            log_iyuu_message(f"找到种子 '{torrent_name}'，包含 {len(agg_torrents[torrent_name])} 个支持的站点", "INFO")
            
            # 获取已配置的站点列表
            log_iyuu_message(f"数据库中存在 {len(configured_sites)} 个配置站点", "INFO")
            
            # 执行IYUU搜索逻辑，传入force_query参数
            self._perform_iyuu_search(agg_torrents, configured_sites, all_torrents, force_query=force_query)
            
            log_iyuu_message(f"=== 种子 '{torrent_name}' 的IYUU查询任务执行完成 ===", "INFO")
            
        except Exception as e:
            logging.error(f"处理单个种子数据时出错: {e}", exc_info=True)
            log_iyuu_message(f"处理种子时出错: {str(e)}", "ERROR")
        finally:
            if conn:
                if 'cursor' in locals() and cursor:
                    cursor.close()
                conn.close()

    def stop(self):
        """停止线程"""
        print("正在停止 IYUUThread 线程...")
        self._is_running = False


# --- IYUU API 配置 ---
API_BASE = "https://2025.iyuu.cn"
CLIENT_VERSION = "8.2.0"

# --- 请求频率控制 ---
_last_request_time = 0
_rate_limit_delay = 5.0  # 请求间隔时间（秒）

# --- IYUU API 辅助函数 ---


def get_sha1_hex(text: str) -> str:
    """计算字符串的 SHA-1 哈希值"""
    return hashlib.sha1(text.encode('utf-8')).hexdigest()


def make_api_request(method: str, url: str, token: str, **kwargs) -> dict:
    """
    封装 API 请求，统一处理 headers 和错误。
    【已修正】此函数现在能正确合并 headers。
    """
    global _last_request_time, _rate_limit_delay

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

    try:
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
            raise Exception(f"API 错误: {error_msg} (代码: {data.get('code')})")

        return data

    except requests.exceptions.RequestException as e:
        raise Exception(f"网络请求失败: {e}")
    except json.JSONDecodeError:
        raise Exception("无法解析服务器返回的 JSON 数据")


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

    # 1. 获取IYUU支持的所有可辅种站点
    try:
        supported_sites = get_supported_sites(token)
        print(f"获取到 {len(supported_sites)} 个IYUU支持的可辅种站点")
    except Exception as e:
        logging.error(f"获取IYUU支持站点列表失败: {e}")
        raise

    # 在获取站点列表和后续请求之间添加额外延迟
    print("等待额外延迟以避免请求频率过快...")
    time.sleep(2)

    # 2. 获取torrents表中存在的站点列表
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

    # 3. 使用site_name_mapping映射替换nickname
    site_name_mapping = {
        # IYUU名称 -> 数据库昵称
        "优堡": "我堡",
        "观众": "人人",
        "柠檬": "柠檬不酸",
        "hdclone": "HDClone",
        "我的PT(CC)": "我的PT",
        "LongPT": "龙PT",
        "March": "三月传媒",
        "hdbao": "红豆包",
        "LuckPT": "幸运",
        "13city": "13City",
        "PTSKit": "PTSkit",
        "时光": "时光HDT",
        "春天": "不可说",
    }

    # 创建反向映射 (数据库昵称 -> IYUU名称)
    reverse_mapping = {v: k for k, v in site_name_mapping.items()}

    # 4. 过滤出IYUU支持且在torrents表中存在的站点
    filtered_site_ids = []
    site_id_mapping = {}  # 用于存储站点ID映射
    filtered_sites = []  # 用于存储过滤后的站点信息

    for site in supported_sites:
        iyuu_nickname = site.get('nickname')
        iyuu_id = site.get('id')

        if not iyuu_nickname or not iyuu_id:
            continue

        # 检查站点是否在torrents表中存在
        # 先检查原始名称
        if iyuu_nickname in torrent_sites_list:
            filtered_site_ids.append(iyuu_id)
            site_id_mapping[iyuu_nickname] = iyuu_id
            filtered_sites.append(site)
            continue

        # 再检查映射后的名称
        if iyuu_nickname in site_name_mapping:
            db_nickname = site_name_mapping[iyuu_nickname]
            if db_nickname in torrent_sites_list:
                filtered_site_ids.append(iyuu_id)
                site_id_mapping[db_nickname] = iyuu_id
                filtered_sites.append(site)
                continue

        # 检查反向映射 (数据库中的名称是否需要映射到IYUU)
        for db_site in torrent_sites_list:
            if db_site in reverse_mapping and reverse_mapping[
                    db_site] == iyuu_nickname:
                filtered_site_ids.append(iyuu_id)
                site_id_mapping[db_site] = iyuu_id
                filtered_sites.append(site)
                break

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
        return sid_sha1, filtered_sites
    except Exception as e:
        logging.error(f"生成sid_sha1时出错: {e}")
        raise


def query_cross_seed(token: str, infohash: str, sid_sha1: str) -> list:
    """查询指定 infohash 的辅种信息"""
    print(f"正在为种子 {infohash[:8]}... 查询辅种信息...")
    url = f"{API_BASE}/reseed/index/index"

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


# 全局变量
iyuu_thread = None

# IYUU日志存储
iyuu_logs = []


def log_iyuu_message(message, level="INFO"):
    """记录IYUU日志消息"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = {
        "timestamp": timestamp,
        "level": level,
        "message": message
    }
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
        iyuu_thread.join(timeout=10)
        print("IYUUThread 线程已停止。")
    iyuu_thread = None
