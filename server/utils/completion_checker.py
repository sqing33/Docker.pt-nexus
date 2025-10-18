# utils/completion_checker.py
"""
电视剧和动漫完结状态检查模块

提供多种策略判断电视剧/动漫是否完结：
1. 副标题关键词检查（全*集、全*期）
2. 主标题Complete关键词检查
3. 简介集数与本地文件数对比
4. 本地文件S01E01格式集数统计
"""

import re
import os
from typing import Dict, Optional, Tuple


def check_completion_status(title: str = "",
                            subtitle: str = "",
                            description: str = "",
                            local_path: str = "",
                            downloader_id: str = None,
                            torrent_name: str = None) -> Dict[str, any]:
    """
    综合判断电视剧/动漫是否完结
    
    Args:
        title: 主标题
        subtitle: 副标题
        description: 简介内容
        local_path: 本地保存路径
        downloader_id: 下载器ID（用于路径映射）
        torrent_name: 种子名称（用于拼接完整路径）
    
    Returns:
        Dict包含:
        - is_complete: bool, 是否完结
        - confidence: str, 判断置信度 (high/medium/low)
        - reason: str, 判断依据说明
        - details: Dict, 详细信息
    """

    result = {
        "is_complete": False,
        "confidence": "low",
        "reason": "",
        "details": {}
    }

    reasons = []

    # 策略1: 副标题关键词检查
    subtitle_check = _check_subtitle_keywords(subtitle)
    if subtitle_check["matched"]:
        result["is_complete"] = True
        result["confidence"] = "high"
        reasons.append(f"副标题包含完结关键词: {subtitle_check['keyword']}")
        result["details"]["subtitle_match"] = subtitle_check

    # 策略2: 主标题Complete检查
    title_check = _check_title_complete(title)
    if title_check["matched"]:
        result["is_complete"] = True
        # 如果已经有高置信度，保持；否则设为高
        if result["confidence"] != "high":
            result["confidence"] = "high"
        reasons.append(f"主标题包含Complete标识")
        result["details"]["title_match"] = title_check

    # 策略3: 简介集数对比（需要本地路径）
    if description and local_path:
        episode_check = _check_episode_count_match(description, local_path,
                                                   downloader_id, torrent_name)
        result["details"]["episode_check"] = episode_check

        if episode_check["total_episodes"] is not None and episode_check[
                "local_episodes"] is not None:
            if episode_check["is_match"]:
                result["is_complete"] = True
                # 只有在没有更高置信度时才设置
                if result["confidence"] == "low":
                    result["confidence"] = "medium"
                reasons.append(
                    f"本地集数({episode_check['local_episodes']})与简介总集数({episode_check['total_episodes']})匹配"
                )
            else:
                # 集数不匹配，可能未完结
                reasons.append(
                    f"本地集数({episode_check['local_episodes']})少于简介总集数({episode_check['total_episodes']})"
                )

    # 汇总原因
    if reasons:
        result["reason"] = "; ".join(reasons)
    else:
        result["reason"] = "未检测到完结标识"

    return result


def _check_subtitle_keywords(subtitle: str) -> Dict[str, any]:
    """
    检查副标题中的完结关键词
    
    支持的格式：
    - 全12集
    - 全24期
    - 全26话
    - 完结
    
    Args:
        subtitle: 副标题文本
    
    Returns:
        Dict包含matched和keyword
    """
    if not subtitle:
        return {"matched": False, "keyword": None}

    # 定义完结关键词模式
    patterns = [
        (r'全\s*(\d+)\s*集', '全{}集'),
        (r'全\s*(\d+)\s*期', '全{}期'),
        (r'全\s*(\d+)\s*话', '全{}话'),
        (r'完结', '完结'),
        (r'COMPLETE', 'COMPLETE'),
        (r'Complete', 'Complete'),
    ]

    for pattern, keyword_template in patterns:
        match = re.search(pattern, subtitle, re.IGNORECASE)
        if match:
            if '{}' in keyword_template and match.groups():
                keyword = keyword_template.format(match.group(1))
            else:
                keyword = keyword_template

            print(f"副标题完结检测: 找到关键词 '{keyword}'")
            return {"matched": True, "keyword": keyword, "pattern": pattern}

    return {"matched": False, "keyword": None}


def _check_title_complete(title: str) -> Dict[str, any]:
    """
    检查主标题中是否包含Complete标识
    
    Args:
        title: 主标题文本
    
    Returns:
        Dict包含matched信息
    """
    if not title:
        return {"matched": False}

    # 匹配Complete关键词（不区分大小写）
    pattern = r'\bCOMPLETE\b'
    match = re.search(pattern, title, re.IGNORECASE)

    if match:
        print(f"主标题完结检测: 找到Complete标识")
        return {"matched": True, "keyword": match.group(0)}

    return {"matched": False}


def _extract_total_episodes_from_description(
        description: str) -> Optional[int]:
    """
    从简介中提取总集数
    
    支持的格式：
    - ◎集　　数　12
    - ◎集　数　24
    - ◎集数 12
    - 集数: 12
    - Episodes: 12
    
    Args:
        description: 简介文本
    
    Returns:
        总集数（int）或None
    """
    if not description:
        return None

    # 定义提取模式（按优先级排序）
    patterns = [
        r'◎\s*集\s*数\s+(\d+)',  # ◎集　　数　12
        r'◎\s*集\s*数\s*[:：]\s*(\d+)',  # ◎集数：12
        r'集\s*数\s*[:：]\s*(\d+)',  # 集数：12
        r'Episodes?\s*[:：]\s*(\d+)',  # Episodes: 12
        r'Total\s+Episodes?\s*[:：]\s*(\d+)',  # Total Episodes: 12
    ]

    for pattern in patterns:
        match = re.search(pattern, description, re.IGNORECASE)
        if match:
            episode_count = int(match.group(1))
            print(f"从简介提取到总集数: {episode_count}")
            return episode_count

    return None


def _count_local_episodes(local_path: str,
                          downloader_id: str = None,
                          torrent_name: str = None) -> Optional[int]:
    """
    统计本地S01E01格式的剧集文件数量
    
    仿照 media_helper.py 中的路径处理逻辑：
    1. 使用 translate_path 进行路径映射
    2. 如果提供了 torrent_name，拼接完整路径
    3. 检查是否需要使用代理
    4. 遍历目录统计集数（本地）或调用远程API
    
    Args:
        local_path: 本地路径
        downloader_id: 下载器ID（用于路径映射和代理判断）
        torrent_name: 种子名称（用于拼接完整路径）
    
    Returns:
        本地集数（int）或None
    """
    if not local_path:
        print("未提供本地路径")
        return None

    # 步骤1: 检查是否需要使用远程代理（仿照 media_helper.py）
    proxy_config = _get_downloader_proxy_config(downloader_id)

    # 步骤2: 构建完整路径
    remote_path = local_path
    if torrent_name:
        remote_path = os.path.join(local_path, torrent_name)
        print(f"已提供 torrent_name，将使用完整路径: '{remote_path}'")

    # 步骤3: 如果需要使用代理，调用远程API
    if proxy_config:
        print(f"使用代理统计集数: {proxy_config['proxy_base_url']}")
        try:
            import requests
            response = requests.post(
                f"{proxy_config['proxy_base_url']}/api/media/episode-count",
                json={"remote_path": remote_path},
                timeout=180)
            response.raise_for_status()
            result = response.json()
            if result.get("success"):
                episode_count = result.get("episode_count", 0)
                season_number = result.get("season_number", 1)
                print(f"通过代理统计到第{season_number}季共 {episode_count} 集")
                return episode_count
            else:
                print(f"通过代理统计集数失败: {result.get('message', '未知错误')}")
                return None
        except Exception as e:
            print(f"通过代理统计集数失败: {e}")
            return None

    # 步骤4: 本地统计 - 应用路径映射
    try:
        from utils.media_helper import translate_path
        translated_path = translate_path(downloader_id, local_path)
        if translated_path != local_path:
            print(f"路径映射: {local_path} -> {translated_path}")
    except Exception as e:
        print(f"路径映射失败: {e}，使用原始路径")
        translated_path = local_path

    # 步骤5: 如果提供了 torrent_name，拼接完整路径
    if torrent_name:
        full_path = os.path.join(translated_path, torrent_name)
        print(f"使用完整路径: {full_path}")
    else:
        full_path = translated_path
        print(f"使用基础路径: {full_path}")

    # 步骤6: 检查路径是否存在
    if not os.path.exists(full_path):
        print(f"本地路径不存在: {full_path}")
        return None

    # 视频文件扩展名
    video_extensions = {
        '.mkv', '.mp4', '.ts', '.avi', '.wmv', '.mov', '.flv', '.m2ts'
    }

    # 剧集文件名模式
    # 支持: S01E01, S01E02, s01e01, S1E1等格式
    episode_pattern = re.compile(r'[Ss](\d{1,2})[Ee](\d{1,3})', re.IGNORECASE)

    episode_numbers = set()

    try:
        # 遍历目录查找视频文件
        for root, dirs, files in os.walk(full_path):
            for filename in files:
                # 检查是否是视频文件
                _, ext = os.path.splitext(filename)
                if ext.lower() not in video_extensions:
                    continue

                # 匹配剧集编号
                match = episode_pattern.search(filename)
                if match:
                    season = int(match.group(1))
                    episode = int(match.group(2))
                    episode_numbers.add((season, episode))

        if episode_numbers:
            # 通常只统计第一季的集数
            season_1_episodes = [ep for s, ep in episode_numbers if s == 1]
            if season_1_episodes:
                local_count = len(season_1_episodes)
                print(f"本地第1季找到 {local_count} 集")
                return local_count
            else:
                # 如果没有第一季，返回所有集数
                local_count = len(episode_numbers)
                print(f"本地找到 {local_count} 集（多季）")
                return local_count

    except Exception as e:
        print(f"统计本地集数时出错: {e}")
        return None

    return None


def _check_episode_count_match(description: str,
                               local_path: str,
                               downloader_id: str = None,
                               torrent_name: str = None) -> Dict[str, any]:
    """
    检查简介中的总集数是否与本地文件数量匹配
    
    Args:
        description: 简介文本
        local_path: 本地路径
        downloader_id: 下载器ID
        torrent_name: 种子名称
    
    Returns:
        Dict包含匹配结果和详细信息
    """
    result = {
        "total_episodes": None,
        "local_episodes": None,
        "is_match": False,
        "reason": ""
    }

    # 提取总集数
    total_episodes = _extract_total_episodes_from_description(description)
    result["total_episodes"] = total_episodes

    if total_episodes is None:
        result["reason"] = "简介中未找到总集数信息"
        return result

    # 统计本地集数
    local_episodes = _count_local_episodes(local_path, downloader_id,
                                           torrent_name)
    result["local_episodes"] = local_episodes

    if local_episodes is None:
        result["reason"] = "无法统计本地集数"
        return result

    # 比对
    if local_episodes >= total_episodes:
        result["is_match"] = True
        result["reason"] = f"本地集数({local_episodes})达到或超过总集数({total_episodes})"
    else:
        result["is_match"] = False
        result["reason"] = f"本地集数({local_episodes})少于总集数({total_episodes})"

    return result


def _get_downloader_proxy_config(downloader_id: str = None):
    """
    根据下载器ID获取代理配置（仿照 media_helper.py）
    
    Args:
        downloader_id: 下载器ID
    
    Returns:
        代理配置字典，如果不需要代理则返回None
    """
    if not downloader_id:
        return None

    try:
        from config import config_manager
        from urllib.parse import urlparse

        config = config_manager.get()
        downloaders = config.get("downloaders", [])

        for downloader in downloaders:
            if downloader.get("id") == downloader_id:
                use_proxy = downloader.get("use_proxy", False)
                if use_proxy:
                    host_value = downloader.get('host', '')
                    proxy_port = downloader.get('proxy_port', 9090)
                    if host_value.startswith(('http://', 'https://')):
                        parsed_url = urlparse(host_value)
                    else:
                        parsed_url = urlparse(f"http://{host_value}")
                    proxy_ip = parsed_url.hostname
                    if not proxy_ip:
                        if '://' in host_value:
                            proxy_ip = host_value.split('://')[1].split(
                                ':')[0].split('/')[0]
                        else:
                            proxy_ip = host_value.split(':')[0]
                    proxy_config = {
                        "proxy_base_url": f"http://{proxy_ip}:{proxy_port}",
                    }
                    return proxy_config
                break
    except Exception as e:
        print(f"获取代理配置失败: {e}")

    return None


def add_completion_tag_if_needed(tags: list,
                                 completion_status: Dict[str, any]) -> list:
    """
    根据完结状态，向标签列表添加完结标签
    
    Args:
        tags: 现有标签列表
        completion_status: 完结状态检查结果
    
    Returns:
        更新后的标签列表
    """
    if not isinstance(tags, list):
        tags = []

    # 定义完结标签的标准化键
    completion_tag = "tag.完结"

    # 检查是否已存在完结标签
    has_completion_tag = any(
        tag in ["完结", "tag.完结", "Complete", "tag.Complete"] for tag in tags)

    # 如果判断为完结且置信度不低，且没有完结标签，则添加
    if (completion_status.get("is_complete")
            and completion_status.get("confidence") in ["high", "medium"]
            and not has_completion_tag):

        tags.append(completion_tag)
        print(
            f"已添加完结标签: {completion_tag} (置信度: {completion_status['confidence']})"
        )

    return tags
