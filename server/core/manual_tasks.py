# core/manual_tasks.py

import logging
import time
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