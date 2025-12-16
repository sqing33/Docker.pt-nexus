import time
import datetime
import logging
from typing import Tuple, List, Dict

# 导入必要的客户端库
import qbittorrentapi
from transmission_rpc import Client as TransmissionClient


def format_speed(speed_bytes):
    """将字节速度转换为易读格式"""
    if speed_bytes < 1024:
        return f"{speed_bytes} B/s"
    elif speed_bytes < 1024 * 1024:
        return f"{speed_bytes / 1024:.2f} KB/s"
    else:
        return f"{speed_bytes / 1024 / 1024:.2f} MB/s"


def is_within_24h(added_time):
    """判断给定的时间是否在过去24小时内"""
    now = time.time()
    one_day_ago = now - 86400  # 24小时前的时间戳

    try:
        if isinstance(added_time, (int, float)):
            return added_time >= one_day_ago
        elif isinstance(added_time, datetime.datetime):
            # 将 datetime 对象转换为时间戳进行比较，避免时区报错
            return added_time.timestamp() >= one_day_ago
    except Exception:
        return False
    return False


def check_qbittorrent_status(downloader: Dict) -> Tuple[int, int]:
    """检查 qBittorrent 状态，返回 (活跃上传数, 24h内活跃数)"""
    try:
        host = downloader.get("host", "")
        if ":" not in host:
            raise ValueError(f"无效的host格式: {host}")

        ip, port = host.split(":")
        client = qbittorrentapi.Client(
            host=ip,
            port=int(port),
            username=downloader.get("username", ""),
            password=downloader.get("password", ""),
        )
        client.auth_log_in()

        # 获取所有正在上传的任务
        uploading_torrents = client.torrents_info(status_filter="seeding")
        # 获取所有暂停的任务
        paused_torrents = client.torrents_info(status_filter="paused")

        # 🚫 只统计有上传能力的种子：正在上传的 + 暂停的
        active_upload_count = 0  # 正在上传的任务
        paused_count = 0  # 暂停的任务
        recent_active_count = 0  # 24h内正在上传的
        recent_paused_count = 0  # 24h内暂停的

        # 统计正在上传的种子（只计算有上传速度的）
        for torrent in uploading_torrents:
            upspeed = torrent.get("upspeed", 0)
            added_on = torrent.get("added_on", 0)

            if upspeed > 0:  # 只统计真正有上传速度的
                active_upload_count += 1
                if is_within_24h(added_on):
                    recent_active_count += 1

        # 统计暂停的种子
        for torrent in paused_torrents:
            added_on = torrent.get("added_on", 0)
            paused_count += 1
            if is_within_24h(added_on):
                recent_paused_count += 1

        # 总数 = 正在上传的 + 暂停的
        total_uploading = active_upload_count + paused_count
        recent_total = recent_active_count + recent_paused_count

        logging.debug(
            f"qBittorrent {host}: 正在上传={active_upload_count}, 暂停={paused_count}, "
            f"总计={total_uploading}, 24h内总数={recent_total}"
        )
        return total_uploading, recent_total

        logging.debug(
            f"qBittorrent {host}: 活跃上传={active_upload_count}, 24h内活跃={recent_active_count}"
        )
        return active_upload_count, recent_active_count

    except Exception as e:
        logging.error(f"qBittorrent 状态检查失败 ({downloader.get('host', 'unknown')}): {e}")
        raise


def check_transmission_status(downloader: Dict) -> Tuple[int, int]:
    """检查 Transmission 状态，返回 (活跃上传数, 24h内活跃数)"""
    try:
        host = downloader.get("host", "")
        if ":" not in host:
            raise ValueError(f"无效的host格式: {host}")

        ip, port = host.split(":")
        client = TransmissionClient(
            host=ip,
            port=int(port),
            username=downloader.get("username", ""),
            password=downloader.get("password", ""),
        )

        torrents = client.get_torrents()

        active_upload_count = 0  # 正在上传的任务
        paused_count = 0  # 暂停的任务
        recent_active_count = 0  # 24h内正在上传的
        recent_paused_count = 0  # 24h内暂停的

        for t in torrents:
            # 统计正在上传的种子（只计算有上传速度的）
            if t.status == "seeding" and t.rate_upload > 0:
                active_upload_count += 1
                if is_within_24h(t.added_date):
                    recent_active_count += 1

            # 统计暂停的种子
            elif t.status == "stopped":
                paused_count += 1
                if is_within_24h(t.added_date):
                    recent_paused_count += 1

        # 总数 = 正在上传的 + 暂停的
        total_uploading = active_upload_count + paused_count
        recent_total = recent_active_count + recent_paused_count

        logging.debug(
            f"Transmission {host}: 正在上传={active_upload_count}, 暂停={paused_count}, "
            f"总计={total_uploading}, 24h内总数={recent_total}"
        )
        return total_uploading, recent_total

    except Exception as e:
        logging.error(f"Transmission 状态检查失败 ({downloader.get('host', 'unknown')}): {e}")
        raise


def check_downloader_status(downloader: Dict) -> Tuple[int, int]:
    """检查单个下载器状态，返回 (上传种子总数, 24h内添加总数)"""
    downloader_type = downloader.get("type", "").lower()

    if downloader_type == "qbittorrent":
        return check_qbittorrent_status(downloader)
    elif downloader_type == "transmission":
        return check_transmission_status(downloader)
    else:
        raise ValueError(f"不支持的下载器类型: {downloader_type}")


def group_local_downloaders_by_ip(downloaders: List[Dict]) -> Dict[str, List[Dict]]:
    """根据IP地址分组本地下载器"""
    groups = {}
    for downloader in downloaders:
        # 只处理本地下载器（use_proxy为false或未设置）
        if not downloader.get("use_proxy", False):
            host = downloader.get("host", "")
            if ":" in host:
                ip = host.split(":")[0]
                if ip not in groups:
                    groups[ip] = []
                groups[ip].append(downloader)
            else:
                logging.warning(
                    f"下载器 {downloader.get('name', 'unknown')} 的host格式无效: {host}"
                )

    return groups


def check_seeding_limit_for_ip(
    ip: str, downloaders: List[Dict], max_uploading: int = 10, max_recent: int = 10
) -> Tuple[bool, str]:
    """
    检查指定IP的下载器组是否触发限制

    Args:
        ip: IP地址
        downloaders: 该IP下的下载器列表
        max_uploading: 最大允许的上传种子总数（正在上传+暂停）
        max_recent: 最大允许的最近24小时内添加的种子总数

    Returns:
        (是否允许添加, 限制消息)
    """
    total_uploading = 0  # 上传种子总数（正在上传+暂停）
    recent_total_count = 0  # 24h内添加的总数
    downloader_names = []

    for downloader in downloaders:
        try:
            uploading_count, recent_count = check_downloader_status(downloader)
            total_uploading += uploading_count
            recent_total_count += recent_count
            downloader_names.append(downloader.get("name", "unknown"))

        except Exception as e:
            logging.warning(f"检查下载器 {downloader.get('name', 'unknown')} 状态失败: {e}")
            # 单个下载器检查失败不阻止整体检查
            continue

    # 🚫 修改限制条件：上传种子总数（正在上传+暂停）> max_uploading 且最近24小时添加的 >= max_recent
    if total_uploading > max_uploading and recent_total_count >= max_recent:
        message = (
            f"限制触发：本地IP {ip} 的下载器组（{', '.join(downloader_names)}）"
            f"共有 {total_uploading} 个上传种子（正在上传+暂停），其中 {recent_total_count} 个为最近24小时添加。"
            f"为避免过度占用资源及绕过限制，暂停后续种子添加。"
        )
        return False, message

    logging.debug(f"IP {ip} 检查通过：上传总数={total_uploading}, 24h内总数={recent_total_count}")
    return True, ""


def check_seeding_limit_for_downloader(
    downloader_id: str,
    all_downloaders: List[Dict],
    max_uploading: int = 99999999,
    max_recent: int = 99999999,
) -> Tuple[bool, str]:
    """
    为指定下载器检查发种限制

    Args:
        downloader_id: 目标下载器ID
        all_downloaders: 所有下载器配置列表
        max_uploading: 最大允许的上传种子总数（正在上传+暂停）
        max_recent: 最大允许的最近24小时内添加的种子总数

    Returns:
        (是否允许添加, 限制消息)
    """
    # 找到目标下载器
    target_downloader = None
    for downloader in all_downloaders:
        if downloader.get("id") == downloader_id:
            target_downloader = downloader
            break

    if not target_downloader:
        logging.warning(f"找不到下载器ID: {downloader_id}")
        return True, ""  # 找不到下载器，允许添加

    # 如果是远程下载器，不进行限制
    if target_downloader.get("use_proxy", False):
        logging.debug(f"下载器 {downloader_id} 是远程下载器，跳过限制检查")
        return True, ""

    # 获取目标下载器的IP
    host = target_downloader.get("host", "")
    if ":" not in host:
        logging.warning(f"下载器 {downloader_id} 的host格式无效: {host}")
        return True, ""  # 无法解析IP，允许添加

    target_ip = host.split(":")[0]

    # 找到所有相同IP的本地下载器
    local_downloaders_same_ip = []
    for downloader in all_downloaders:
        if not downloader.get("use_proxy", False) and downloader.get("enabled", True):
            downloader_host = downloader.get("host", "")
            if ":" in downloader_host:
                ip = downloader_host.split(":")[0]
                if ip == target_ip:
                    local_downloaders_same_ip.append(downloader)

    if not local_downloaders_same_ip:
        logging.debug(f"IP {target_ip} 没有找到本地下载器")
        return True, ""

    # 检查限制
    return check_seeding_limit_for_ip(
        target_ip, local_downloaders_same_ip, max_uploading, max_recent
    )
