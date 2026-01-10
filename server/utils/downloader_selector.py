import logging
from typing import List, Dict, Optional, Any


def select_best_downloader(
    downloader_ids: List[str],
    config_manager: Any,
    torrent_list: Optional[List[Dict]] = None,
    inactive_torrent_states: Optional[List[str]] = None
) -> Optional[str]:
    """
    从下载器ID列表中选择最佳的下载器
    
    优先级：
    1. 优先选择 use_proxy=true 的下载器
    2. 如果有 torrent_list，按活跃状态排序（活跃 > 非活跃）
    3. 如果有 torrent_list，按 last_seen 排序（最近 > 最早）
    4. 如果没有 torrent_list，选择第一个 use_proxy=true 的下载器
    5. 如果都没有 use_proxy=true，选择第一个下载器
    
    Args:
        downloader_ids: 下载器ID列表
        config_manager: 配置管理器
        torrent_list: 可选，种子列表（包含 downloader_id, state, last_seen）
        inactive_torrent_states: 可选，非活跃状态列表
    
    Returns:
        最佳的下载器ID，如果没有则返回 None
    """
    if not downloader_ids:
        return None
    
    # 获取下载器配置
    try:
        config = config_manager.get()
        downloaders = config.get("downloaders", [])
        downloader_map = {
            downloader.get("id"): {
                "use_proxy": downloader.get("use_proxy", False),
                "enabled": downloader.get("enabled", True),
                "name": downloader.get("name", "")
            }
            for downloader in downloaders
        }
    except Exception as e:
        logging.error(f"获取下载器配置失败: {e}")
        return downloader_ids[0] if downloader_ids else None
    
    # 如果提供了 torrent_list，按完整逻辑排序
    if torrent_list:
        # 过滤出在 downloader_ids 中的种子
        filtered_torrents = [
            t for t in torrent_list
            if t.get("downloader_id") in downloader_ids
        ]
        
        if not filtered_torrents:
            return None
        
        # 排序：优先 use_proxy=true，然后按活跃状态，最后按 last_seen
        def sort_key(torrent):
            downloader_id = torrent.get("downloader_id")
            downloader_config = downloader_map.get(downloader_id, {})
            use_proxy = downloader_config.get("use_proxy", False)
            
            # 计算活跃状态排名（0=活跃，1=非活跃）
            state = torrent.get("state", "")
            if inactive_torrent_states:
                state_rank = 0 if state not in inactive_torrent_states else 1
            else:
                state_rank = 0  # 默认都认为是活跃的
            
            # 返回排序键：use_proxy（降序），state_rank（升序），last_seen（降序）
            return (-1 if use_proxy else 1, state_rank, -torrent.get("last_seen", 0))
        
        filtered_torrents.sort(key=sort_key)
        
        best_torrent = filtered_torrents[0]
        best_downloader_id = best_torrent.get("downloader_id")
        best_config = downloader_map.get(best_downloader_id, {})
        
        logging.info(
            f"[下载器选择] 选择最佳下载器: {best_downloader_id} "
            f"({best_config.get('name')}) - use_proxy={best_config.get('use_proxy')}"
        )
        
        return best_downloader_id
    
    # 如果没有提供 torrent_list，只根据 downloader_ids 选择
    # 优先选择 use_proxy=true 的下载器
    for dl_id in downloader_ids:
        dl_config = downloader_map.get(dl_id)
        if dl_config and dl_config.get("use_proxy") and dl_config.get("enabled"):
            logging.info(
                f"[下载器选择] 选择代理下载器: {dl_id} ({dl_config.get('name')})"
            )
            return dl_id
    
    # 如果没有 use_proxy=true 的下载器，选择第一个启用的下载器
    for dl_id in downloader_ids:
        dl_config = downloader_map.get(dl_id)
        if dl_config and dl_config.get("enabled"):
            logging.info(
                f"[下载器选择] 选择启用下载器: {dl_id} ({dl_config.get('name')})"
            )
            return dl_id
    
    # 如果都没有，返回第一个下载器ID
    logging.info(f"[下载器选择] 选择第一个下载器: {downloader_ids[0]}")
    return downloader_ids[0]
