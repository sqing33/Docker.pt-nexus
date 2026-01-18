# core/manual_tasks.py

import logging
import time
from collections import defaultdict
from threading import Lock
from datetime import datetime

# 用于防止并发执行的锁
update_torrents_lock = Lock()
iyuu_query_lock = Lock()


def update_torrents_data(db_manager, config_manager):
    """
    手动更新数据库种子数据

    Args:
        db_manager: 数据库管理器实例
        config_manager: 配置管理器实例

    Returns:
        dict: 包含更新结果信息的字典
    """
    # 使用锁防止并发执行
    if not update_torrents_lock.acquire(blocking=False):
        return {
            "success": False,
            "message": "种子数据更新正在进行中，请稍后再试"
        }

    try:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logging.info(f"=== 开始手动更新数据库种子数据 [{current_time}] ===")
        print(f"【手动更新】[{current_time}] 开始更新数据库中的种子...")

        # 导入 DataTracker 类来使用其更新功能
        from .services import DataTracker

        # 创建临时的 DataTracker 实例来执行更新
        temp_tracker = DataTracker(db_manager, config_manager)

        # 执行更新
        temp_tracker.update_torrents_in_db()

        print("【手动更新】=== 种子数据库更新完成 ===")
        logging.info("=== 手动种子数据库更新完成 ===")

        return {
            "success": True,
            "message": "种子数据更新完成"
        }

    except Exception as e:
        error_msg = f"手动更新种子数据失败: {e}"
        logging.error(error_msg, exc_info=True)
        print(f"【手动更新】错误: {error_msg}")
        return {
            "success": False,
            "message": error_msg
        }
    finally:
        update_torrents_lock.release()


def trigger_iyuu_query(db_manager, config_manager, torrent_name=None, torrent_size=None):
    """
    手动触发IYUU查询

    Args:
        db_manager: 数据库管理器实例
        config_manager: 配置管理器实例
        torrent_name: 可选，指定种子的名称。如果为None，则查询所有种子
        torrent_size: 可选，指定种子的大小。当指定torrent_name时需要提供

    Returns:
        dict: 包含查询结果信息的字典
    """
    # 使用锁防止并发执行
    if not iyuu_query_lock.acquire(blocking=False):
        return {
            "success": False,
            "message": "IYUU查询正在进行中，请稍后再试"
        }

    try:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logging.info(f"=== 开始手动IYUU查询 [{current_time}] ===")
        print(f"【手动IYUU】[{current_time}] 开始执行IYUU查询...")

        # 导入IYUU相关功能
        from .iyuu import IYUUThread, log_iyuu_message

        # 创建临时的 IYUUThread 实例来执行查询
        temp_iyuu = IYUUThread(db_manager, config_manager)

        if torrent_name and torrent_size:
            # 查询单个种子
            log_iyuu_message(f"手动触发单个种子IYUU查询: {torrent_name}", "INFO")
            result_stats = temp_iyuu._process_single_torrent(
                torrent_name,
                torrent_size,
                force_query=True
            )

            # 根据查询结果生成更详细的消息
            if result_stats['total_found'] > 0:
                message = f"种子 '{torrent_name}' 的IYUU查询已完成，找到 {result_stats['total_found']} 条记录"
                if result_stats['new_records'] > 0:
                    message += f"，新增 {result_stats['new_records']} 条种子记录"
            else:
                message = f"种子 '{torrent_name}' 的IYUU查询已完成，未找到可辅种记录"

            result = {
                "success": True,
                "message": message,
                "stats": result_stats
            }
        else:
            # 查询所有种子
            log_iyuu_message("手动触发全部种子IYUU查询", "INFO")
            temp_iyuu.process_torrents(is_manual_trigger=True)

            result = {
                "success": True,
                "message": "IYUU查询已成功触发"
            }

        print("【手动IYUU】=== IYUU查询完成 ===")
        logging.info("=== 手动IYUU查询完成 ===")

        return result

    except Exception as e:
        error_msg = f"手动IYUU查询失败: {e}"
        logging.error(error_msg, exc_info=True)
        print(f"【手动IYUU】错误: {error_msg}")
        return {
            "success": False,
            "message": error_msg
        }
    finally:
        iyuu_query_lock.release()


def trigger_iyuu_query_sync(db_manager, config_manager, torrent_name, torrent_size):
    """
    手动触发指定种子的IYUU查询（同步执行）

    Args:
        db_manager: 数据库管理器实例
        config_manager: 配置管理器实例
        torrent_name: 种子名称
        torrent_size: 种子大小

    Returns:
        dict: 包含查询结果信息的字典
    """
    return trigger_iyuu_query(db_manager, config_manager, torrent_name, torrent_size)


def trigger_iyuu_query_by_path(db_manager, config_manager, save_path, limit=200, anchor_name=None):
    """手动触发指定路径下的 IYUU 查询（同步执行）"""
    # 使用锁防止并发执行
    if not iyuu_query_lock.acquire(blocking=False):
        return {
            "success": False,
            "message": "IYUU查询正在进行中，请稍后再试"
        }

    try:
        if not save_path:
            return {
                "success": False,
                "message": "缺少保存路径参数"
            }

        try:
            limit_int = int(limit)
        except Exception:
            limit_int = 200

        if limit_int <= 0:
            limit_int = 200

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logging.info(f"=== 开始手动路径IYUU查询 [{current_time}] ===")
        print(f"【手动IYUU】[{current_time}] 开始执行路径IYUU查询: {save_path} ...")

        from .iyuu import IYUUThread, log_iyuu_message

        temp_iyuu = IYUUThread(db_manager, config_manager)

        conn = None
        cursor = None
        try:
            conn = db_manager._get_connection()
            cursor = db_manager._get_cursor(conn)
            ph = db_manager.get_placeholder()

            query_conditions = [
                f"save_path = {ph}",
                "name IS NOT NULL AND name != ''",
                "size > 207374182",
                f"state != {ph}",
            ]
            query_params = [save_path, "不存在"]

            sql_query = (
                f"SELECT hash, name, sites, size, save_path FROM torrents WHERE {' AND '.join(query_conditions)}"
            )
            cursor.execute(sql_query, tuple(query_params))
            torrents_raw = [dict(row) for row in cursor.fetchall()]

        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

        if not torrents_raw:
            return {
                "success": True,
                "message": f"路径 '{save_path}' 下未找到可查询的种子（需大于200MB且状态不为不存在）",
                "stats": {
                    "total_found": 0,
                    "new_records": 0,
                    "updated_records": 0,
                    "sites_found": []
                },
            }

        all_torrents = defaultdict(list)
        for t in torrents_raw:
            name = t.get("name")
            if not name:
                continue
            all_torrents[name].append({
                "hash": t.get("hash"),
                "sites": t.get("sites"),
                "size": t.get("size", 0),
                "save_path": t.get("save_path", ""),
            })

        total_groups = len(all_torrents)
        group_names = sorted(all_torrents.keys())

        if total_groups > limit_int:
            selected = []
            if anchor_name and anchor_name in all_torrents:
                selected.append(anchor_name)
            for name in group_names:
                if name == anchor_name:
                    continue
                selected.append(name)
                if len(selected) >= limit_int:
                    break
            group_names = selected

        agg_torrents = {name: all_torrents[name] for name in group_names}
        configured_sites = temp_iyuu._get_configured_sites()

        log_iyuu_message(
            f"手动触发路径IYUU查询: {save_path}；种子组 {len(group_names)} / {total_groups}",
            "INFO"
        )

        result_stats = temp_iyuu._perform_iyuu_search(
            agg_torrents,
            configured_sites,
            all_torrents,
            force_query=True,
            return_stats=True
        ) or {
            "total_found": 0,
            "new_records": 0,
            "updated_records": 0,
            "sites_found": []
        }

        message = (
            f"路径 '{save_path}' 的IYUU查询已完成，处理 {len(group_names)} / {total_groups} 个种子组"
            f"，找到 {result_stats.get('total_found', 0)} 条记录"
            f"，新增 {result_stats.get('new_records', 0)} 条，更新 {result_stats.get('updated_records', 0)} 条"
        )

        print("【手动IYUU】=== 路径IYUU查询完成 ===")
        logging.info("=== 手动路径IYUU查询完成 ===")

        return {
            "success": True,
            "message": message,
            "stats": result_stats,
            "query_info": {
                "save_path": save_path,
                "total_groups": total_groups,
                "processed_groups": len(group_names),
                "limit": limit_int,
            },
        }

    except Exception as e:
        error_msg = f"手动路径IYUU查询失败: {e}"
        logging.error(error_msg, exc_info=True)
        print(f"【手动IYUU】错误: {error_msg}")
        return {
            "success": False,
            "message": error_msg
        }
    finally:
        iyuu_query_lock.release()


def trigger_iyuu_query_by_path_sync(db_manager, config_manager, save_path, limit=200, anchor_name=None):
    """手动触发指定路径下的 IYUU 查询（同步执行）"""
    return trigger_iyuu_query_by_path(db_manager, config_manager, save_path, limit, anchor_name)


def trigger_iyuu_query_torrents_batch(db_manager,
                                      config_manager,
                                      torrents,
                                      max_groups=200,
                                      force_query=True):
    """手动触发一批指定种子组的 IYUU 查询（同步执行）.

    Args:
        db_manager: 数据库管理器实例
        config_manager: 配置管理器实例
        torrents: 种子组列表，元素包含 name/size（可选 save_path）
        max_groups: 最多处理的种子组数（默认 200）
        force_query: 是否强制查询（默认 True）

    Returns:
        dict: 包含查询结果信息的字典
    """
    if not iyuu_query_lock.acquire(blocking=False):
        return {"success": False, "message": "IYUU查询正在进行中，请稍后再试"}

    try:
        if not torrents or not isinstance(torrents, list):
            return {"success": False, "message": "缺少种子列表参数"}

        try:
            max_groups_int = int(max_groups)
        except Exception:
            max_groups_int = 200
        if max_groups_int <= 0:
            max_groups_int = 200

        # 规范化/去重
        normalized = []
        seen = set()
        for item in torrents:
            if not isinstance(item, dict):
                continue
            name = (item.get("name") or "").strip()
            size = item.get("size")
            if not name:
                continue
            try:
                size_int = int(size)
            except Exception:
                continue
            if size_int <= 0:
                continue
            key = (name, size_int)
            if key in seen:
                continue
            seen.add(key)
            normalized.append({"name": name, "size": size_int})
            if len(normalized) >= max_groups_int:
                break

        if not normalized:
            return {"success": False, "message": "未找到可用的种子组（需包含 name/size）"}

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logging.info(f"=== 开始手动批量IYUU查询 [{current_time}] ===")
        print(f"【手动IYUU】[{current_time}] 开始执行批量IYUU查询，共 {len(normalized)} 个种子组...")

        from .iyuu import IYUUThread, log_iyuu_message

        temp_iyuu = IYUUThread(db_manager, config_manager)
        configured_sites = temp_iyuu._get_configured_sites()

        # 预拉取每个组的全部站点记录（按 name + size）
        group_rows = []
        skipped = 0
        for g in normalized:
            conn = None
            cursor = None
            try:
                conn = db_manager._get_connection()
                cursor = db_manager._get_cursor(conn)
                ph = db_manager.get_placeholder()

                cursor.execute(
                    f"SELECT hash, name, sites, size, save_path FROM torrents WHERE name = {ph} AND size = {ph} AND state != {ph} AND size > 207374182",
                    (g["name"], g["size"], "不存在"),
                )
                rows = [dict(r) for r in cursor.fetchall()]
                if not rows:
                    skipped += 1
                    continue
                group_rows.append({
                    "name": g["name"],
                    "size": g["size"],
                    "rows": rows,
                })
            except Exception as e:
                logging.error(f"批量IYUU查询预拉取失败: {g.get('name')} ({g.get('size')}): {e}",
                              exc_info=True)
                skipped += 1
            finally:
                if cursor:
                    cursor.close()
                if conn:
                    conn.close()

        if not group_rows:
            return {"success": True, "message": "未找到可查询的种子记录（需大于200MB且状态不为不存在）", "stats": {}}

        # 如果存在同名不同 size 的情况，拆分为多轮执行，确保每轮 name 唯一（避免 dict key 冲突）
        groups_by_name = defaultdict(list)
        ordered_names = []
        for g in group_rows:
            name = g["name"]
            if name not in groups_by_name:
                ordered_names.append(name)
            groups_by_name[name].append(g)

        total_groups = len(group_rows)
        rounds = 0
        accumulated = {"total_found": 0, "new_records": 0, "updated_records": 0, "sites_found": []}

        while any(groups_by_name.values()):
            round_groups = []
            for name in ordered_names:
                if groups_by_name[name]:
                    round_groups.append(groups_by_name[name].pop(0))

            if not round_groups:
                break

            rounds += 1
            agg_torrents = {}
            all_torrents = {}

            for g in round_groups:
                name = g["name"]
                torrents_for_name = [
                    {
                        "hash": r.get("hash"),
                        "sites": r.get("sites"),
                        "size": r.get("size", 0),
                        "save_path": r.get("save_path", ""),
                    }
                    for r in g["rows"]
                ]
                all_torrents[name] = torrents_for_name
                agg_torrents[name] = torrents_for_name

            log_iyuu_message(
                f"手动触发批量IYUU查询：第 {rounds} 轮，种子组 {len(round_groups)}",
                "INFO",
            )

            stats = temp_iyuu._perform_iyuu_search(
                agg_torrents,
                configured_sites,
                all_torrents,
                force_query=force_query,
                return_stats=True,
            ) or {}

            accumulated["total_found"] += int(stats.get("total_found", 0) or 0)
            accumulated["new_records"] += int(stats.get("new_records", 0) or 0)
            accumulated["updated_records"] += int(stats.get("updated_records", 0) or 0)
            accumulated["sites_found"].extend(stats.get("sites_found", []) or [])

        message = (
            f"批量IYUU查询已完成，处理 {total_groups} 个种子组"
            f"（跳过 {skipped}，轮次 {rounds}）"
            f"，找到 {accumulated['total_found']} 条记录"
            f"，新增 {accumulated['new_records']} 条，更新 {accumulated['updated_records']} 条"
        )

        print("【手动IYUU】=== 批量IYUU查询完成 ===")
        logging.info("=== 手动批量IYUU查询完成 ===")

        return {
            "success": True,
            "message": message,
            "stats": accumulated,
            "query_info": {
                "total_groups": total_groups,
                "processed_groups": total_groups,
                "skipped_groups": skipped,
                "rounds": rounds,
                "limit": max_groups_int,
            },
        }

    except Exception as e:
        error_msg = f"手动批量IYUU查询失败: {e}"
        logging.error(error_msg, exc_info=True)
        print(f"【手动IYUU】错误: {error_msg}")
        return {"success": False, "message": error_msg}
    finally:
        iyuu_query_lock.release()


def trigger_iyuu_query_torrents_batch_sync(db_manager,
                                           config_manager,
                                           torrents,
                                           max_groups=200,
                                           force_query=True):
    """手动触发一批指定种子组的 IYUU 查询（同步执行）"""
    return trigger_iyuu_query_torrents_batch(db_manager,
                                             config_manager,
                                             torrents,
                                             max_groups=max_groups,
                                             force_query=force_query)


def trigger_iyuu_query_all(db_manager, config_manager):
    """
    手动触发全部种子的IYUU查询

    Args:
        db_manager: 数据库管理器实例
        config_manager: 配置管理器实例

    Returns:
        dict: 包含查询结果信息的字典
    """
    return trigger_iyuu_query(db_manager, config_manager)
