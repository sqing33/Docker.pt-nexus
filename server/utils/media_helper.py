# utils/media_helper.py

import base64
import logging
import mimetypes
import re
import os
import shutil
import subprocess
import tempfile
import requests
import json
import time
import random
import cloudscraper
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from pymediainfo import MediaInfo
from config import TEMP_DIR, config_manager
from qbittorrentapi import Client as qbClient
from transmission_rpc import Client as TrClient
from utils import ensure_scheme
from PIL import Image


def translate_path(downloader_id: str, remote_path: str) -> str:
    """
    将下载器的远程路径转换为 PT Nexus 容器内的本地路径。

    :param downloader_id: 下载器ID
    :param remote_path: 下载器中的远程路径
    :return: PT Nexus 容器内可访问的本地路径
    """
    if not downloader_id or not remote_path:
        return remote_path

    # 获取下载器配置
    config = config_manager.get()
    downloaders = config.get("downloaders", [])

    for downloader in downloaders:
        if downloader.get("id") == downloader_id:
            path_mappings = downloader.get("path_mappings", [])
            if not path_mappings:
                # 没有配置路径映射，直接返回原路径
                return remote_path

            # 按远程路径长度降序排序，优先匹配最长的路径（更精确）
            sorted_mappings = sorted(path_mappings,
                                     key=lambda x: len(x.get('remote', '')),
                                     reverse=True)

            for mapping in sorted_mappings:
                remote = mapping.get('remote', '')
                local = mapping.get('local', '')

                if not remote or not local:
                    continue

                # 确保路径比较时统一处理末尾的斜杠
                remote = remote.rstrip('/')
                remote_path_normalized = remote_path.rstrip('/')

                # 检查是否匹配（完全匹配或前缀匹配）
                if remote_path_normalized == remote:
                    # 完全匹配
                    return local
                elif remote_path_normalized.startswith(remote + '/'):
                    # 前缀匹配，替换路径
                    relative_path = remote_path_normalized[len(remote
                                                               ):].lstrip('/')
                    return os.path.join(local, relative_path)

            # 没有匹配的映射，返回原路径
            return remote_path

    # 没有找到对应的下载器，返回原路径
    return remote_path


def _upload_to_pixhost(image_path: str):
    """
    将单个图片文件上传到 Pixhost.to。

    :param image_path: 本地图片文件的路径。
    :return: 成功时返回图片的展示URL，失败时返回None。
    """
    api_url = 'https://api.pixhost.to/images'
    params = {'content_type': 0}
    headers = {
        'User-Agent':
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    print(f"准备上传图片: {image_path}")

    if not os.path.exists(image_path):
        print(f"错误：文件不存在 {image_path}")
        return None

    # 直接上传，不使用全局代理
    return _upload_to_pixhost_direct(image_path, api_url, params, headers)


def _get_agsv_auth_token():
    """使用配置文件中的邮箱和密码获取 末日图床 的授权 Token。"""
    config = config_manager.get().get("cross_seed", {})
    email = config.get("agsv_email")
    password = config.get("agsv_password")

    if not email or not password:
        logging.warning("末日图床 邮箱或密码未配置，无法获取 Token。")
        return None

    token_url = "https://img.seedvault.cn/api/v1/tokens"
    payload = {"email": email, "password": password}
    headers = {"Accept": "application/json"}
    print("正在为 末日图床 获取授权 Token...")
    try:
        response = requests.post(token_url,
                                 headers=headers,
                                 json=payload,
                                 timeout=30)
        if response.status_code == 200 and response.json().get("status"):
            token = response.json().get("data", {}).get("token")
            if token:
                print("   ✅ 成功获取 末日图床 Token！")
                return token

        logging.error(
            f"获取 末日图床 Token 失败。状态码: {response.status_code}, 响应: {response.text}"
        )
        print(f"   ❌ 获取 末日图床 Token 失败: {response.text}")
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f"获取 末日图床 Token 时网络请求错误: {e}")
        print(f"   ❌ 获取 末日图床 Token 时网络请求错误: {e}")
        return None


def _upload_to_agsv(image_path: str, token: str):
    """使用给定的 Token 上传单个图片到 末日图床。"""
    upload_url = "https://img.seedvault.cn/api/v1/upload"
    headers = {
        "Authorization":
        f"Bearer {token}",
        "Accept":
        "application/json",
        "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    }

    mime_type = mimetypes.guess_type(
        image_path)[0] or 'application/octet-stream'
    image_name = os.path.basename(image_path)

    print(f"准备上传图片到 末日图床: {image_name}")
    try:
        with open(image_path, 'rb') as f:
            files = {'file': (image_name, f, mime_type)}
            response = requests.post(upload_url,
                                     headers=headers,
                                     files=files,
                                     timeout=180)

        data = response.json()
        if response.status_code == 200 and data.get("status"):
            image_url = data.get("data", {}).get("links", {}).get("url")
            print(f"   ✅ 末日图床 上传成功！URL: {image_url}")
            return image_url
        else:
            message = data.get('message', '无详细信息')
            logging.error(f"末日图床 上传失败。API 消息: {message}")
            print(f"   ❌ 末日图床 上传失败: {message}")
            return None
    except (requests.exceptions.RequestException,
            requests.exceptions.JSONDecodeError) as e:
        logging.error(f"上传到 末日图床 时发生错误: {e}")
        print(f"   ❌ 上传到 末日图床 时发生错误: {e}")
        return None


def _get_smart_screenshot_points(video_path: str,
                                 num_screenshots: int = 5) -> list[float]:
    """
    [优化版] 使用 ffprobe 智能分析视频字幕，选择最佳的截图时间点。
    - 通过 `-read_intervals` 参数实现分段读取，避免全文件扫描，大幅提升大文件处理速度。
    - 优先选择 ASS > SRT > PGS 格式的字幕。
    - 优先在视频的 30%-80% "黄金时段" 内随机选择。
    - 在所有智能分析失败时，优雅地回退到按百分比选择。
    """
    print("\n--- 开始智能截图时间点分析 (快速扫描模式) ---")
    if not shutil.which("ffprobe"):
        print("警告: 未找到 ffprobe，无法进行智能分析。")
        return []

    try:
        cmd_duration = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", video_path
        ]
        result = subprocess.run(cmd_duration,
                                capture_output=True,
                                text=True,
                                check=True,
                                encoding='utf-8')
        duration = float(result.stdout.strip())
        print(f"视频总时长: {duration:.2f} 秒")
    except Exception as e:
        print(f"错误：使用 ffprobe 获取视频时长失败。{e}")
        return []

    # 探测字幕流的部分保持不变，因为它本身速度很快
    try:
        cmd_probe_subs = [
            "ffprobe", "-v", "quiet", "-print_format", "json", "-show_entries",
            "stream=index,codec_name,disposition", "-select_streams", "s",
            video_path
        ]
        result = subprocess.run(cmd_probe_subs,
                                capture_output=True,
                                text=True,
                                check=True,
                                encoding='utf-8')
        sub_data = json.loads(result.stdout)

        best_ass, best_srt, best_pgs = None, None, None
        for stream in sub_data.get("streams", []):
            disposition = stream.get("disposition", {})
            is_normal = not any([
                disposition.get("comment"),
                disposition.get("hearing_impaired"),
                disposition.get("visual_impaired")
            ])
            if is_normal:
                codec_name = stream.get("codec_name")
                if codec_name == "ass" and not best_ass: best_ass = stream
                elif codec_name == "subrip" and not best_srt: best_srt = stream
                elif codec_name == "hdmv_pgs_subtitle" and not best_pgs:
                    best_pgs = stream

        chosen_sub_stream = best_ass or best_srt or best_pgs
        if not chosen_sub_stream:
            print("未找到合适的正常字幕流。")
            return []

        sub_index, sub_codec = chosen_sub_stream.get(
            "index"), chosen_sub_stream.get("codec_name")
        print(f"   ✅ 找到最优字幕流 (格式: {sub_codec.upper()})，流索引: {sub_index}")

    except Exception as e:
        print(f"探测字幕流失败: {e}")
        return []

    subtitle_events = []
    try:
        # --- 【核心修改】 ---
        # 1. 定义我们要探测的时间点（例如，视频的20%, 40%, 60%, 80%位置）
        probe_points = [0.2, 0.4, 0.6, 0.8]
        # 2. 定义在每个探测点附近扫描多长时间（例如，60秒），时间越长，找到字幕事件越多，但耗时也越长
        probe_duration = 60

        # 3. 构建 -read_intervals 参数
        # 格式为 "start1%+duration1,start2%+duration2,..."
        intervals = []
        for point in probe_points:
            start_time = duration * point
            end_time = start_time + probe_duration
            if end_time > duration:
                end_time = duration  # 确保不超过视频总长
            intervals.append(f"{start_time}%{end_time}")

        read_intervals_arg = ",".join(intervals)
        print(f"   🚀 将只扫描以下时间段来寻找字幕: {read_intervals_arg}")

        # 4. 将 -read_intervals 参数添加到 ffprobe 命令中
        cmd_extract = [
            "ffprobe",
            "-v",
            "quiet",
            "-read_intervals",
            read_intervals_arg,  # <--- 新增的参数
            "-print_format",
            "json",
            "-show_packets",
            "-select_streams",
            str(sub_index),
            video_path
        ]

        # 执行命令，现在它会快非常多
        result = subprocess.run(cmd_extract,
                                capture_output=True,
                                text=True,
                                check=True,
                                encoding='utf-8')
        # --- 【核心修改结束】 ---

        events_data = json.loads(result.stdout)
        packets = events_data.get("packets", [])

        # 后续处理逻辑基本不变
        if sub_codec in ["ass", "subrip"]:
            for packet in packets:
                try:
                    start, dur = float(packet.get("pts_time")), float(
                        packet.get("duration_time"))
                    if dur > 0.1:
                        subtitle_events.append({
                            "start": start,
                            "end": start + dur
                        })
                except (ValueError, TypeError):
                    continue
        elif sub_codec == "hdmv_pgs_subtitle":
            for i in range(0, len(packets) - 1, 2):
                try:
                    start, end = float(packets[i].get("pts_time")), float(
                        packets[i + 1].get("pts_time"))
                    if end > start and (end - start) > 0.1:
                        subtitle_events.append({"start": start, "end": end})
                except (ValueError, TypeError):
                    continue

        if not subtitle_events: raise ValueError("在指定区间内未能提取到任何有效的时间事件。")
        print(f"   ✅ 成功从指定区间提取到 {len(subtitle_events)} 条有效字幕事件。")
    except Exception as e:
        print(f"智能提取时间事件失败: {e}")
        return []

    # 后续的随机选择逻辑保持不变
    if len(subtitle_events) < num_screenshots:
        print("有效字幕数量不足，无法启动智能选择。")
        return []

    golden_start_time, golden_end_time = duration * 0.30, duration * 0.80
    golden_events = [
        e for e in subtitle_events
        if e["start"] >= golden_start_time and e["end"] <= golden_end_time
    ]
    print(
        f"   -> 在视频中部 ({(golden_start_time):.2f}s - {(golden_end_time):.2f}s) 找到 {len(golden_events)} 个黄金字幕事件。"
    )

    target_events = golden_events
    if len(target_events) < num_screenshots:
        print("   -> 黄金字幕数量不足，将从所有字幕事件中随机选择。")
        target_events = subtitle_events

    chosen_events = random.sample(target_events,
                                  min(num_screenshots, len(target_events)))

    screenshot_points = []
    for event in chosen_events:
        event_duration = event["end"] - event["start"]
        random_offset = event_duration * 0.1 + random.random() * (
            event_duration * 0.8)
        random_point = event["start"] + random_offset
        screenshot_points.append(random_point)
        print(
            f"   -> 选中时间段 [{(event['start']):.2f}s - {(event['end']):.2f}s], 随机截图点: {(random_point):.2f}s"
        )

    return sorted(screenshot_points)


def _find_target_video_file(path: str) -> tuple[str | None, bool]:
    """
    根据路径智能查找目标视频文件，并检测是否为原盘文件。
    - 优先检查种子名称匹配的文件（处理电影直接放在下载目录根目录的情况）
    - 如果是电影目录，返回最大的视频文件。
    - 如果是剧集目录，返回按名称排序的第一个视频文件。
    - 检测是否为原盘文件（检查 BDMV/CERTIFICATE 目录）

    :param path: 要搜索的目录或文件路径。
    :return: 元组 (目标视频文件的完整路径, 是否为原盘文件)
    """
    print(f"开始在路径 '{path}' 中查找目标视频文件...")
    VIDEO_EXTENSIONS = {
        ".mkv", ".mp4", ".ts", ".avi", ".wmv", ".mov", ".flv", ".m2ts"
    }

    if not os.path.exists(path):
        print(f"错误：提供的路径不存在: {path}")
        return None, False

    # 如果提供的路径本身就是一个视频文件，直接返回
    if os.path.isfile(path) and os.path.splitext(
            path)[1].lower() in VIDEO_EXTENSIONS:
        print(f"路径直接指向一个视频文件，将使用: {path}")
        return path, False

    if not os.path.isdir(path):
        print(f"错误：路径不是一个有效的目录或视频文件: {path}")
        return None, False

    # 检查是否为原盘文件（检查 BDMV/CERTIFICATE 目录）
    is_bluray_disc = False
    bdmv_path = os.path.join(path, "BDMV")
    certificate_path = os.path.join(path, "CERTIFICATE")

    if os.path.exists(bdmv_path) and os.path.isdir(bdmv_path):
        print(f"检测到 BDMV 目录: {bdmv_path}")
        if certificate_path and os.path.exists(
                certificate_path) and os.path.isdir(certificate_path):
            print(f"检测到 CERTIFICATE 目录: {certificate_path}")
            is_bluray_disc = True
            print("确认：检测到原盘文件结构 (BDMV/CERTIFICATE)")
        else:
            print("警告：检测到 BDMV 目录但未找到 CERTIFICATE 目录，可能不是标准原盘")

    # 优先检查种子名称匹配的文件（处理电影直接放在根目录的情况）
    # 这种情况通常发生在没有文件夹包裹的电影文件
    parent_dir = os.path.dirname(path)
    file_name = os.path.basename(path)

    # 检查父目录中是否有匹配的文件名（不含扩展名）
    if parent_dir != path:  # 确保这不是根目录的情况
        try:
            for file in os.listdir(parent_dir):
                if not file.startswith('.') and not os.path.isdir(
                        os.path.join(parent_dir, file)):
                    if os.path.splitext(file)[1].lower() in VIDEO_EXTENSIONS:
                        # 检查文件名是否匹配（忽略扩展名）
                        file_name_without_ext = os.path.splitext(file)[0]
                        if (file_name in file_name_without_ext
                                or file_name_without_ext in file_name
                                or file_name.replace(' ', '')
                                in file_name_without_ext.replace(' ', '')
                                or file_name_without_ext.replace(
                                    ' ', '') in file_name.replace(' ', '')):
                            full_path = os.path.join(parent_dir, file)
                            print(f"找到匹配的视频文件: {full_path}")
                            return full_path, is_bluray_disc
        except OSError as e:
            print(f"读取父目录失败: {e}")

    # 如果没有找到匹配的文件，继续原来的查找逻辑
    video_files = []
    for root, _, files in os.walk(path):
        for file in files:
            if os.path.splitext(file)[1].lower() in VIDEO_EXTENSIONS:
                video_files.append(os.path.join(root, file))

    if not video_files:
        print(f"在目录 '{path}' 中未找到任何视频文件。")
        return None, is_bluray_disc

    # 如果只有一个视频文件，直接使用
    if len(video_files) == 1:
        print(f"找到唯一的视频文件: {video_files[0]}")
        return video_files[0], is_bluray_disc

    # 如果有多个视频文件，尝试找到最匹配的文件名
    best_match = ""
    best_score = -1
    for video_file in video_files:
        base_name = os.path.basename(video_file).lower()
        path_name = file_name.lower()

        # 计算匹配度
        score = 0
        if path_name in base_name:
            score += 10
        if base_name in path_name:
            score += 5

        # 长度越接近，得分越高
        if abs(len(base_name) - len(path_name)) < 5:
            score += 3

        if score > best_score:
            best_score = score
            best_match = video_file

    if best_match and best_score > 0:
        print(f"选择最佳匹配的视频文件: {best_match} (匹配度: {best_score})")
        return best_match, is_bluray_disc

    # 如果没有找到好的匹配，选择最大的文件
    largest_file = ""
    max_size = -1
    for f in video_files:
        try:
            size = os.path.getsize(f)
            if size > max_size:
                max_size = size
                largest_file = f
        except OSError as e:
            print(f"无法获取文件大小 '{f}': {e}")
            continue

    if largest_file:
        print(f"已选择最大文件 ({(max_size / 1024**3):.2f} GB): {largest_file}")
        return largest_file, is_bluray_disc
    else:
        print("无法确定最大的文件。")
        return None, is_bluray_disc


# --- [修改] 主函数，整合了新的文件查找逻辑 ---
def upload_data_mediaInfo(mediaInfo: str,
                          save_path: str,
                          content_name: str = None,
                          downloader_id: str = None,
                          torrent_name: str = None,
                          force_refresh: bool = False):
    """
    检查传入的文本是有效的 MediaInfo 还是 BDInfo 格式。
    如果没有 MediaInfo 或 BDInfo 则尝试从 save_path 查找视频文件提取 MediaInfo。
    【新增】支持传入 torrent_name (实际文件夹名) 或 content_name (解析后的标题) 来构建更精确的搜索路径。
    【新增】支持传入 downloader_id 来判断是否使用代理获取 MediaInfo
    【新增】支持传入 force_refresh 强制重新获取 MediaInfo，忽略已有的有效格式
    """
    print("开始检查 MediaInfo/BDInfo 格式")
    print(f"提供的 MediaInfo: {mediaInfo[:80]}...")  # 打印部分MediaInfo

    # 1. (此部分代码不变) ...
    standard_mediainfo_keywords = [
        "General",
        "Video",
        "Audio",
        "Complete name",
        "File size",
        "Duration",
        "Width",
        "Height",
    ]
    bdinfo_required_keywords = ["DISC INFO", "PLAYLIST REPORT"]
    bdinfo_optional_keywords = [
        "VIDEO:",
        "AUDIO:",
        "SUBTITLES:",
        "FILES:",
        "Disc Label",
        "Disc Size",
        "BDInfo:",
        "Protection:",
        "Codec",
        "Bitrate",
        "Language",
        "Description",
    ]
    mediainfo_matches = sum(1 for keyword in standard_mediainfo_keywords
                            if keyword in mediaInfo)
    is_standard_mediainfo = mediainfo_matches >= 3
    bdinfo_required_matches = sum(1 for keyword in bdinfo_required_keywords
                                  if keyword in mediaInfo)
    bdinfo_optional_matches = sum(1 for keyword in bdinfo_optional_keywords
                                  if keyword in mediaInfo)
    is_bdinfo = (bdinfo_required_matches == len(bdinfo_required_keywords)) or \
                (bdinfo_required_matches >= 1 and bdinfo_optional_matches >= 2)

    if is_standard_mediainfo:
        if force_refresh:
            print(f"检测到标准 MediaInfo 格式，但设置了强制刷新，将重新提取。")
            # 不return，继续执行下面的提取逻辑
        else:
            print(f"检测到标准 MediaInfo 格式，验证通过。(匹配关键字数: {mediainfo_matches})")
            return mediaInfo
    elif is_bdinfo:
        if force_refresh:
            print(f"检测到 BDInfo 格式，但设置了强制刷新，将重新提取。")
            # 不return，继续执行下面的提取逻辑
        else:
            print(
                f"检测到 BDInfo 格式，验证通过。(必要关键字: {bdinfo_required_matches}/{len(bdinfo_required_keywords)}, 可选关键字: {bdinfo_optional_matches})"
            )
            return mediaInfo
    elif not force_refresh:
        # 只有在不是强制刷新时才打印这个消息
        print("提供的文本不是有效的 MediaInfo/BDInfo，将尝试从本地文件提取。")

    # 如果执行到这里，说明需要重新提取（force_refresh=True 或者没有有效格式）
    if not save_path:
        print("错误：未提供 save_path，无法从文件提取 MediaInfo。")
        return mediaInfo

    # --- 【代理检查和处理逻辑】 ---
    proxy_config = _get_downloader_proxy_config(downloader_id)

    if proxy_config:
        print(f"使用代理处理 MediaInfo: {proxy_config['proxy_base_url']}")
        # 构建完整路径发送给代理
        remote_path = save_path
        if torrent_name:
            remote_path = os.path.join(save_path, torrent_name)
            print(f"已提供 torrent_name，将使用完整路径: '{remote_path}'")
        elif content_name:
            remote_path = os.path.join(save_path, content_name)
            print(f"已提供 content_name，将使用拼接路径: '{remote_path}'")

        try:
            response = requests.post(
                f"{proxy_config['proxy_base_url']}/api/media/mediainfo",
                json={"remote_path": remote_path},
                timeout=300)  # 5分钟超时
            response.raise_for_status()
            result = response.json()
            if result.get("success"):
                print("通过代理获取 MediaInfo 成功")
                proxy_mediainfo = result.get("mediainfo", mediaInfo)
                # 处理代理返回的 MediaInfo，只保留 Complete name 中的文件名
                proxy_mediainfo = re.sub(
                    r'(Complete name\s*:\s*)(.+)', lambda m:
                    f"{m.group(1)}{os.path.basename(m.group(2).strip())}",
                    proxy_mediainfo)
                return proxy_mediainfo
            else:
                print(f"通过代理获取 MediaInfo 失败: {result.get('message', '未知错误')}")
        except Exception as e:
            print(f"通过代理获取 MediaInfo 失败: {e}")

    # --- 【核心修改】仿照截图逻辑，构建精确的搜索路径 ---
    # 首先应用路径映射转换
    translated_save_path = translate_path(downloader_id, save_path)
    if translated_save_path != save_path:
        print(f"路径映射: {save_path} -> {translated_save_path}")

    path_to_search = translated_save_path  # 使用转换后的路径
    # 优先使用 torrent_name (实际文件夹名)，如果不存在再使用 content_name (解析后的标题)
    if torrent_name:
        path_to_search = os.path.join(translated_save_path, torrent_name)
        print(f"已提供 torrent_name，将在精确路径中搜索: '{path_to_search}'")
    elif content_name:
        # 如果提供了具体的内容名称（主标题），则拼接成一个更精确的路径
        path_to_search = os.path.join(translated_save_path, content_name)
        print(f"已提供 content_name，将在精确路径中搜索: '{path_to_search}'")

    # 使用新构建的路径来查找视频文件
    target_video_file, is_bluray_disc = _find_target_video_file(path_to_search)

    if not target_video_file:
        print("未能在指定路径中找到合适的视频文件，提取失败。")
        return mediaInfo

    # 检查是否为原盘文件
    if is_bluray_disc:
        print("检测到原盘文件结构 (BDMV/CERTIFICATE)，返回指定消息")
        return "bdinfo提取暂未实现，请手动获取。"

    try:
        print(f"准备使用 MediaInfo 工具从 '{target_video_file}' 提取...")
        media_info_parsed = MediaInfo.parse(target_video_file,
                                            output="text",
                                            full=False)
        # 处理 Complete name，只保留最后一个 / 之后的内容
        media_info_str = str(media_info_parsed)
        # 使用正则表达式替换 Complete name 行中的完整路径为文件名
        media_info_str = re.sub(
            r'(Complete name\s*:\s*)(.+)',
            lambda m: f"{m.group(1)}{os.path.basename(m.group(2).strip())}",
            media_info_str)
        print("从文件重新提取 MediaInfo 成功。")
        return media_info_str
    except Exception as e:
        print(f"从文件 '{target_video_file}' 处理时出错: {e}。将返回原始 mediainfo。")
        return mediaInfo


def upload_data_title(title: str, torrent_filename: str = ""):
    """
    从种子主标题中提取所有参数，并可选地从种子文件名中补充缺失参数。
    """
    print(f"开始从主标题解析参数: {title}")

    # 1. 预处理
    original_title_str = title.strip()
    params = {}
    unrecognized_parts = []

    # 注释掉原有的粗暴截断逻辑，因为它会错误地移除制作组名称中的中文部分
    # 例如 "-FFans@ws林小凡" 会被错误截断
    # 现在只在标题中存在独立的中文片段（不与制作组相连）时才标记为无法识别
    # chinese_junk_match = re.search(r"([\u4e00-\u9fa5].*)$", original_title_str)
    # if chinese_junk_match:
    #     unrecognized_parts.append(chinese_junk_match.group(1).strip())
    #     title = original_title_str[:chinese_junk_match.start()].strip()
    # else:
    #     title = original_title_str

    # 保持原始标题，让后续的制作组提取逻辑来处理
    title = original_title_str

    title = re.sub(r"[￡€]", "", title)
    title = re.sub(r"\s*剩餘時間.*$", "", title)
    title = re.sub(r"[\s\.]*(mkv|mp4)$", "", title,
                   flags=re.IGNORECASE).strip()
    title = re.sub(r"\[.*?\]|【.*?】", "", title).strip()
    title = title.replace("（", "(").replace("）", ")")
    title = title.replace("'", "")
    title = re.sub(r"(\d+[pi])([A-Z])", r"\1 \2", title)

    # 2. 优先提取制作组信息
    release_group = ""
    main_part = title

    # 检查特殊制作组（完整匹配）
    special_groups = ["mUHD-FRDS", "MNHD-FRDS", "DMG&VCB-Studio", "VCB-Studio"]
    found_special_group = False
    for group in special_groups:
        if title.endswith(f" {group}") or title.endswith(f"-{group}"):
            release_group = group
            main_part = title[:-len(group) - 1].strip()
            found_special_group = True
            break

    # 如果不是特殊制作组，先尝试匹配 VCB-Studio 变体
    if not found_special_group:
        # 匹配类似 -Nekomoe kissaten&VCB-Studio, -LoliHouse&VCB-Studio 等格式
        # 这个正则会匹配 - 开头，中间可能有多个单词（包含空格）、&符号，最后以 VCB-Studio 结尾
        vcb_variant_pattern = re.compile(
            r"^(?P<main_part>.+?)[-](?P<release_group>[\w\s]+&VCB-Studio)$",
            re.IGNORECASE)
        vcb_match = vcb_variant_pattern.match(title)
        if vcb_match:
            main_part = vcb_match.group("main_part").strip()
            release_group = vcb_match.group("release_group")
            found_special_group = True
            print(f"检测到 VCB-Studio 变体制作组: {release_group}")

    # 如果还不是特殊制作组，使用通用模式匹配
    if not found_special_group:
        # 修复：改用贪婪匹配，直接提取最后一个 - 或 @ 之后的所有内容作为制作组
        # 这样可以正确处理包含中文、@、- 等复杂字符的制作组名称
        general_regex = re.compile(
            r"^(?P<main_part>.+?)[-@](?P<release_group>[^\s]+)$",
            re.IGNORECASE,
        )
        print(f"[调试] 尝试匹配制作组，标题: {title}")
        match = general_regex.match(title)
        if match:
            main_part = match.group("main_part").strip()
            release_group = match.group("release_group").strip()
            print(f"[调试] 正则匹配成功!")
            print(f"[调试]   - main_part: {main_part}")
            print(f"[调试]   - release_group: {release_group}")
            print(f"[调试] 最终制作组: {release_group}")
        else:
            # 检查是否以-NOGROUP结尾
            if title.upper().endswith("-NOGROUP"):
                release_group = "NOGROUP"
                main_part = title[:-8].strip()
            else:
                release_group = "N/A (无发布组)"

    # 3. 季集、年份、剪辑版本提取
    season_match = re.search(
        r"(?<!\w)(S\d{1,2}(?:(?:[-–~]\s*S?\d{1,2})?|(?:\s*E\d{1,3}(?:[-–~]\s*(?:S\d{1,2})?E?\d{1,3})*)?))(?!\w)",
        main_part,
        re.I,
    )
    if season_match:
        season_str = season_match.group(1)
        main_part = main_part.replace(season_str, " ").strip()
        params["season_episode"] = re.sub(r"\s", "", season_str.upper())

    title_part = main_part
    year_match = re.search(r"[\s\.\(]((?:19|20)\d{2})([\s\.\)]|$)", title_part)
    if year_match:
        params["year"] = year_match.group(1)
        title_part = title_part.replace(year_match.group(0), " ", 1).strip()

    # 4.1 提取剪辑版本并拼接到年份
    cut_version_pattern = re.compile(
        r"(?<!\w)(Theatrical[\s\.]?Cut|Directors?[\s\.]?Cut|DC|Extended[\s\.]?(?:Cut|Edition)|Special[\s\.]?Edition|SE|Final[\s\.]?Cut|Anniversary[\s\.]?Edition|Restored|Remastered|Criterion[\s\.]?(?:Edition|Collection)|Ultimate[\s\.]?Cut|IMAX[\s\.]?Edition|Open[\s\.]?Matte|Unrated[\s\.]?Cut)(?!\w)",
        re.IGNORECASE)
    cut_version_match = cut_version_pattern.search(title_part)
    if cut_version_match:
        cut_version = re.sub(r'[\s\.]+', ' ',
                             cut_version_match.group(1).strip())
        # 将剪辑版本拼接到年份
        if "year" in params:
            params["year"] = f"{params['year']} {cut_version}"
        else:
            # 如果没有年份，单独作为年份字段
            params["year"] = cut_version
        # 从标题部分移除剪辑版本
        title_part = title_part.replace(cut_version_match.group(0), " ",
                                        1).strip()
        print(f"检测到剪辑版本: {cut_version}，已拼接到年份")

    # 4. 预处理标题：修复音频参数格式
    # 先处理缺少点的情况，如 FLAC 20 -> FLAC 2.0, FLAC 2 0 -> FLAC 2.0
    title_part = re.sub(r"((?:DTS|FLAC|DDP|AV3A|AAC|LPCM|AC3|DD))\s*(\d)\s*(\d)",
                        r"\1 \2.\3",
                        title_part,
                        flags=re.I)
    # 再处理没有空格的情况，如 FLAC2.0 -> FLAC 2.0, DTS5.1 -> DTS 5.1
    title_part = re.sub(r"((?:DTS|FLAC|DDP|AV3A|AAC|LPCM|AC3|DD))(\d(?:\.\d)?)",
                        r"\1 \2",
                        title_part,
                        flags=re.I)

    # 技术标签提取（排除已识别的制作组名称）
    tech_patterns_definitions = {
        "medium":
        r"UHDTV|UHD\s*Blu-?ray|Blu-?ray\s+DIY|Blu-ray|BluRay\s+DIY|BluRay|BDrip|BD-?rip|WEB-DL|WEBrip|TVrip|DVDRip|HDTV",
        "audio":
        r"DTS-HD(?:\s*MA)?(?:\s*\d\.\d)?|(?:Dolby\s*)?TrueHD(?:\s*Atmos)?(?:\s*\d\.\d)?|Atmos(?:\s*TrueHD)?(?:\s*\d\.\d)?|DTS(?:\s*\d\.\d)?|DDP(?:\s*\d\.\d)?|DD\+(?:\s*\d\.\d)?|DD(?:\s*\d\.\d)?|AC3(?:\s*\d\.\d)?|FLAC(?:\s*\d\.\d)?|AAC(?:\s*\d\.\d)?|LPCM(?:\s*\d\.\d)?|AV3A\s*\d\.\d|\d+\s*Audios?|MP2|DUAL",
        "hdr_format":
        r"Dolby Vision|DoVi|HDR10\+|HDRVivid|HDR10|HLG|HDR|SDR|DV|Vivid",
        "resolution": r"\d{3,4}[pi]|4K",
        "video_codec":
        r"HEVC|AVC|x265|H\s*[\s\.]?\s*265|x264|H\s*[\s\.]?\s*264|VC-1|AV1|MPEG-2",
        "source_platform":
        r"Apple TV\+|ViuTV|MyTVSuper|MyVideo|AMZN|Netflix|NF|DSNP|MAX|ATVP|iTunes|friDay|USA|EUR|JPN|CEE|FRA|LINETV|EDR|PCOK|Hami|GBR|NowPlayer|CR|SEEZN|GER|CHN|MA|Viu|Baha|KKTV|IQ|HKG|ITA|ESP",
        "bit_depth": r"\b(?:8|10)bit\b",
        "framerate": r"\d{2,3}fps",
        "completion_status": r"Complete|COMPLETE",
        "video_format": r"3D|HSBS",
        "release_version": r"REMASTERED|REPACK|RERIP|PROPER|REPOST|V\d+",
        "cut_version":
        r"Theatrical[\s\.]?Cut|Directors?[\s\.]?Cut|DC|Extended[\s\.]?(?:Cut|Edition)|Special[\s\.]?Edition|SE|Final[\s\.]?Cut|Anniversary[\s\.]?Edition|Restored|Remastered|Criterion[\s\.]?(?:Edition|Collection)|Ultimate[\s\.]?Cut|IMAX[\s\.]?Edition|Open[\s\.]?Matte|Unrated[\s\.]?Cut",
        "quality_modifier": r"MAXPLUS|HQ|EXTENDED|REMUX|EE|MiniBD",
    }
    priority_order = [
        "completion_status",
        "release_version",
        "cut_version",
        "medium",
        "resolution",
        "video_codec",
        "bit_depth",
        "hdr_format",
        "video_format",
        "framerate",
        "source_platform",
        "audio",
        "quality_modifier",
    ]

    title_candidate = title_part
    first_tech_tag_pos = len(title_candidate)
    all_found_tags = []

    # 构建制作组的关键词列表，用于后续过滤
    release_group_keywords = []
    if release_group and release_group != "N/A (无发布组)":
        # 将制作组名称按@和其他分隔符拆分，获取所有组成部分
        # 例如 "DIY@Audies" -> ["DIY", "Audies"]
        release_group_keywords = re.split(r'[@\-\s]+', release_group)
        release_group_keywords = [
            kw.strip() for kw in release_group_keywords if kw.strip()
        ]
        print(f"[调试] 制作组关键词列表: {release_group_keywords}")

    for key in priority_order:
        pattern = tech_patterns_definitions[key]
        search_pattern = (re.compile(r"(?<!\w)(" + pattern + r")(?!\w)",
                                     re.IGNORECASE) if r"\b" not in pattern
                          else re.compile(pattern, re.IGNORECASE))
        matches = list(search_pattern.finditer(title_candidate))
        if not matches:
            continue

        first_tech_tag_pos = min(first_tech_tag_pos, matches[0].start())
        raw_values = [
            m.group(0).strip() if r"\b" in pattern else m.group(1).strip()
            for m in matches
        ]

        # 过滤掉属于制作组名称的部分
        filtered_values = []
        for val in raw_values:
            # 检查这个值是否是制作组关键词之一
            is_release_group_part = any(val.upper() == kw.upper()
                                        for kw in release_group_keywords)
            if is_release_group_part:
                print(f"[调试] 过滤掉制作组关键词: {val} (属于 {key})")
            if not is_release_group_part:
                filtered_values.append(val)

        all_found_tags.extend(filtered_values)
        if filtered_values:
            print(f"[调试] '{key}' 字段提取到技术标签: {filtered_values}")
        raw_values = filtered_values
        processed_values = (
            [re.sub(r"(DD)\+", r"\1+", val, flags=re.I)
             for val in raw_values] if key == "audio" else raw_values)
        if key == "audio":
            processed_values = [
                # 先处理缺少点的情况，如 FLAC 20 -> FLAC 2.0, FLAC 2 0 -> FLAC 2.0, DTS 51 -> DTS 5.1
                re.sub(r"((?:DTS|FLAC|DDP|AV3A|AAC|LPCM|AC3|DD))\s*(\d)\s*(\d)",
                       r"\1 \2.\3",
                       val,
                       flags=re.I) for val in processed_values
            ]
            processed_values = [
                # 再处理没有空格的情况，如 FLAC2.0 -> FLAC 2.0, DTS5.1 -> DTS 5.1
                re.sub(r"((?:DTS|FLAC|DDP|AV3A|AAC|LPCM|AC3|DD))(\d(?:\.\d)?)",
                       r"\1 \2",
                       val,
                       flags=re.I) for val in processed_values
            ]

        unique_processed = sorted(
            list(set(processed_values)),
            key=lambda x: title_candidate.find(x.replace(" ", "")))
        if unique_processed:
            params[key] = unique_processed[0] if len(
                unique_processed) == 1 else unique_processed

    # --- [新增] 开始: 从种子文件名补充缺失的参数 ---
    if torrent_filename:
        print(f"开始从种子文件名补充参数: {torrent_filename}")
        # 预处理文件名：移除后缀，用空格替换点和其他常用分隔符
        filename_base = re.sub(r'(\.original)?\.torrent',
                               '',
                               torrent_filename,
                               flags=re.IGNORECASE)
        filename_candidate = re.sub(r'[\._\[\]\(\)]', ' ', filename_base)

        # 再次遍历所有技术标签定义，以补充信息
        for key in priority_order:
            # 如果主标题中已解析出此参数，则跳过，优先使用主标题的结果
            if key in params and params.get(key):
                continue

            pattern = tech_patterns_definitions[key]
            search_pattern = (re.compile(r"(?<!\w)(" + pattern + r")(?!\w)",
                                         re.IGNORECASE) if r"\b" not in pattern
                              else re.compile(pattern, re.IGNORECASE))

            matches = list(search_pattern.finditer(filename_candidate))
            if matches:
                # 提取所有匹配到的值
                raw_values = [
                    m.group(0).strip()
                    if r"\b" in pattern else m.group(1).strip()
                    for m in matches
                ]

                # (复制主解析逻辑中的 audio 特殊处理)
                processed_values = ([
                    re.sub(r"(DD)\\+", r"\1+", val, flags=re.I)
                    for val in raw_values
                ] if key == "audio" else raw_values)
                if key == "audio":
                    processed_values = [
                        # 先处理缺少点的情况，如 FLAC 20 -> FLAC 2.0, FLAC 2 0 -> FLAC 2.0
                        re.sub(
                            r"((?:FLAC|DDP|AV3A|AAC|LPCM|AC3|DD))\s*(\d)\s*(\d)",
                            r"\1 \2.\3",
                            val,
                            flags=re.I) for val in processed_values
                    ]
                    processed_values = [
                        # 再处理没有空格的情况，如 FLAC2.0 -> FLAC 2.0
                        re.sub(
                            r"((?:FLAC|DDP|AV3A|AAC|LPCM|AC3|DD))(\d(?:\.\d)?)",
                            r"\1 \2",
                            val,
                            flags=re.I) for val in processed_values
                    ]

                # 取独一无二的值并按出现顺序排序
                unique_processed = sorted(
                    list(set(processed_values)),
                    key=lambda x: filename_candidate.find(x.replace(" ", "")))

                if unique_processed:
                    print(f"   [文件名补充] 找到缺失参数 '{key}': {unique_processed}")
                    # 将补充的参数存入 params 字典
                    params[key] = unique_processed[0] if len(
                        unique_processed) == 1 else unique_processed
                    # 将新找到的标签也加入 all_found_tags，以便后续正确计算"无法识别"部分
                    all_found_tags.extend(unique_processed)
    # --- [新增] 结束 ---

    # 将制作组信息添加到最后的参数中
    params["release_info"] = release_group

    if "quality_modifier" in params:
        modifiers = params.pop("quality_modifier")
        if not isinstance(modifiers, list):
            modifiers = [modifiers]
        if "medium" in params:
            medium_str = (params["medium"] if isinstance(
                params["medium"], str) else params["medium"][0])
            params["medium"] = f"{medium_str} {' '.join(sorted(modifiers))}"

    # 5. 最终标题和未识别内容确定
    title_zone = title_part[:first_tech_tag_pos].strip()
    tech_zone = title_part[first_tech_tag_pos:].strip()
    params["title"] = re.sub(r"[\s\.]+", " ", title_zone).strip()

    print(f"[调试] 开始清理技术区域，原始技术区: '{tech_zone}'")
    print(f"[调试] 所有已识别标签: {all_found_tags}")

    cleaned_tech_zone = tech_zone
    for tag in sorted(all_found_tags, key=len, reverse=True):
        # 对于包含中文的标签，不使用 \b 词边界
        # 使用更通用的模式：(?<!\w) 和 (?!\w) 来匹配非字母数字边界
        # 但中文字符不被 \w 匹配，所以需要特殊处理
        if re.search(r'[\u4e00-\u9fa5]', tag):
            # 包含中文，直接使用字面匹配
            pattern_to_remove = re.escape(tag)
            print(f"[调试] 清理中文标签: '{tag}' (使用字面匹配)")
        else:
            # 纯英文/数字，使用词边界
            pattern_to_remove = r"\b" + re.escape(tag) + r"(?!\w)"
            print(f"[调试] 清理英文标签: '{tag}' (使用词边界)")

        before = cleaned_tech_zone
        cleaned_tech_zone = re.sub(pattern_to_remove,
                                   " ",
                                   cleaned_tech_zone,
                                   flags=re.IGNORECASE)
        if before != cleaned_tech_zone:
            print(f"[调试]   已从技术区移除: '{tag}'")

    print(f"[调试] 清理后的技术区: '{cleaned_tech_zone}'")
    remains = re.split(r"[\s\.]+", cleaned_tech_zone)
    unrecognized_parts.extend([part for part in remains if part])
    print(f"[调试] 最终无法识别部分: {unrecognized_parts}")
    if unrecognized_parts:
        params["unrecognized"] = " ".join(sorted(list(
            set(unrecognized_parts))))

    english_params = {}
    key_order = [
        "title",
        "year",
        "season_episode",
        "completion_status",
        "release_version",
        "resolution",
        "medium",
        "source_platform",
        "video_codec",
        "video_format",
        "hdr_format",
        "bit_depth",
        "framerate",
        "audio",
        "release_info",
        "unrecognized",
    ]
    for key in key_order:
        if key in params and params[key]:
            if key == "audio" and isinstance(params[key], list):
                # 处理音频编码列表，将 "数字Audio" 格式移到编码格式后面
                processed_audio = []
                for audio_item in params[key]:
                    # 检查是否包含 "数字Audio" 模式（如 "3Audio DTS" 或 "DTS 3Audio"）
                    # 匹配模式：(\d+)\s*(Audio[s]?)\s+(.+) 或 (.+)\s+(\d+)\s*(Audio[s]?)
                    match = re.match(r'^(\d+)\s*(Audio[s]?)\s+(.+)$', audio_item, re.IGNORECASE)
                    if match:
                        # 如果是 "3Audio DTS" 格式，重排为 "DTS 3Audio"
                        number = match.group(1)
                        audio_word = match.group(2)
                        codec = match.group(3)
                        processed_audio.append(f"{codec} {number}{audio_word}")
                    else:
                        # 检查是否已经是正确格式 "DTS 3Audio"
                        match_correct = re.match(r'^(.+?)\s+(\d+)\s*(Audio[s]?)$', audio_item, re.IGNORECASE)
                        if match_correct:
                            # 已经是正确格式，直接使用
                            processed_audio.append(audio_item)
                        else:
                            # 其他格式不变
                            processed_audio.append(audio_item)
                
                # 排序：先按是否以数字Audio结尾，再按长度
                sorted_audio = sorted(processed_audio,
                                      key=lambda s:
                                      (bool(re.search(r'\d+\s*Audio[s]?$', s, re.IGNORECASE)), -len(s)))
                english_params[key] = " ".join(sorted_audio)
            else:
                english_params[key] = params[key]

    if "source_platform" in english_params and "audio" in english_params:
        is_sp_list = isinstance(english_params["source_platform"], list)
        sp_values = (english_params["source_platform"]
                     if is_sp_list else [english_params["source_platform"]])
        if "MA" in sp_values and "MA" in str(english_params["audio"]):
            sp_values.remove("MA")
            if not sp_values:
                del english_params["source_platform"]
            elif len(sp_values) == 1 and not is_sp_list:
                english_params["source_platform"] = sp_values[0]
            elif is_sp_list:
                english_params["source_platform"] = sp_values

    # 6. 有效性质检
    is_valid = bool(english_params.get("title"))
    if is_valid:
        if not any(
                key in english_params
                for key in ["resolution", "medium", "video_codec", "audio"]):
            is_valid = False
        release_info = english_params.get("release_info", "")
        if "N/A" in release_info and "NOGROUP" not in release_info:
            core_tech_keys = ["resolution", "medium", "video_codec"]
            if sum(1 for key in core_tech_keys if key in english_params) < 2:
                is_valid = False

    if not is_valid:
        print("主标题解析失败或未通过质检。")
        english_params = {"title": original_title_str, "unrecognized": "解析失败"}

    translation_map = {
        "title": "主标题",
        "year": "年份",
        "season_episode": "季集",
        "resolution": "分辨率",
        "medium": "媒介",
        "source_platform": "片源平台",
        "video_codec": "视频编码",
        "hdr_format": "HDR格式",
        "bit_depth": "色深",
        "framerate": "帧率",
        "audio": "音频编码",
        "release_info": "制作组",
        "completion_status": "剧集状态",
        "unrecognized": "无法识别",
        "video_format": "视频格式",
        "release_version": "发布版本",
    }

    chinese_keyed_params = {}
    for key, value in english_params.items():
        chinese_key = translation_map.get(key)
        if chinese_key:
            chinese_keyed_params[chinese_key] = value

    # 定义前端显示的完整参数列表和固定顺序
    all_possible_keys_ordered = [
        "主标题",
        "年份",
        "季集",
        "剧集状态",
        "发布版本",
        "分辨率",
        "媒介",
        "片源平台",
        "视频编码",
        "视频格式",
        "HDR格式",
        "色深",
        "帧率",
        "音频编码",
        "制作组",
        "无法识别",
    ]

    final_components_list = []
    for key in all_possible_keys_ordered:
        final_components_list.append({
            "key": key,
            "value": chinese_keyed_params.get(key, "")
        })

    print(f"主标题解析成功。")
    return final_components_list


def upload_data_screenshot(source_info,
                           save_path,
                           torrent_name=None,
                           downloader_id=None):
    """
    [最终HDR优化版] 使用 mpv 从视频文件中截取多张图片，并上传到图床。
    - 新增HDR色调映射参数，确保HDR视频截图颜色正常。
    - 按顺序一张一张处理，简化流程。
    - 采用智能时间点分析。
    """
    if Image is None:
        print("错误：Pillow 库未安装，无法执行截图任务。")
        return ""

    print("开始执行截图和上传任务 (引擎: mpv, 输出格式: JPEG, 模式: 顺序执行)...")
    config = config_manager.get()
    hoster = config.get("cross_seed", {}).get("image_hoster", "pixhost")
    num_screenshots = 5
    print(f"已选择图床服务: {hoster}, 截图数量: {num_screenshots}")

    # 首先应用路径映射转换
    translated_save_path = translate_path(downloader_id, save_path)
    if translated_save_path != save_path:
        print(f"路径映射: {save_path} -> {translated_save_path}")

    if torrent_name:
        full_video_path = os.path.join(translated_save_path, torrent_name)
        print(f"使用完整视频路径: {full_video_path}")
    else:
        full_video_path = translated_save_path
        print(f"使用原始路径: {full_video_path}")

    # --- 代理检查和处理逻辑 (此部分保持不变) ---
    use_proxy = False
    proxy_config = None
    if downloader_id:
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
                break

    if use_proxy and proxy_config:
        print(f"使用代理处理截图: {proxy_config['proxy_base_url']}")
        try:
            response = requests.post(
                f"{proxy_config['proxy_base_url']}/api/media/screenshot",
                json={"remote_path": full_video_path},
                timeout=300)
            response.raise_for_status()
            result = response.json()
            if result.get("success"):
                print("代理截图上传成功")
                return result.get("bbcode", "")
            else:
                print(f"代理截图上传失败: {result.get('message', '未知错误')}")
                return ""
        except Exception as e:
            print(f"通过代理获取截图失败: {e}")
            return ""

    # --- 本地截图逻辑 ---
    target_video_file, is_bluray_disc = _find_target_video_file(
        full_video_path)
    if not target_video_file:
        print("错误：在指定路径中未找到视频文件。")
        return ""

    # 对于原盘文件，仍然进行截图处理（保持原有逻辑）
    if is_bluray_disc:
        print("检测到原盘文件结构，但仍将进行截图处理")

    if not shutil.which("mpv"):
        print("错误：找不到 mpv。请确保它已安装并已添加到系统环境变量 PATH 中。")
        return ""

    screenshot_points = _get_smart_screenshot_points(target_video_file,
                                                     num_screenshots)
    if len(screenshot_points) < num_screenshots:
        print("警告: 智能分析失败或字幕不足，回退到按百分比截图。")
        try:
            cmd_duration = [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", target_video_file
            ]
            result = subprocess.run(cmd_duration,
                                    capture_output=True,
                                    text=True,
                                    check=True,
                                    encoding='utf-8')
            duration = float(result.stdout.strip())
            screenshot_points = [
                duration * p for p in [0.15, 0.30, 0.50, 0.70, 0.85]
            ]
        except Exception as e:
            print(f"错误: 连获取视频时长都失败了，无法截图。{e}")
            return ""

    auth_token = _get_agsv_auth_token() if hoster == "agsv" else None
    if hoster == "agsv" and not auth_token:
        print("❌ 无法获取 末日图床 Token，截图上传任务终止。")
        return ""

    uploaded_urls = []
    temp_files_to_cleanup = []

    for i, screenshot_time in enumerate(screenshot_points):
        print(f"\n--- 开始处理第 {i+1}/{len(screenshot_points)} 张截图 ---")

        safe_name = re.sub(r'[\\/*?:"<>|\'\s\.]+', '_',
                           source_info.get('main_title', f's_{i+1}'))  # 更短的文件名
        timestamp = f"{int(time.time()) % 1000000}"  # 更短的时间戳
        intermediate_png_path = os.path.join(
            TEMP_DIR, f"s_{i+1}_{timestamp}.png")  # 更短的文件名
        final_jpeg_path = os.path.join(TEMP_DIR,
                                       f"s_{i+1}_{timestamp}.jpg")  # 更短的文件名
        temp_files_to_cleanup.extend([intermediate_png_path, final_jpeg_path])

        # --- [核心修改] ---
        # 为 mpv 命令添加 HDR 色调映射参数
        cmd_screenshot = [
            "mpv",
            "--no-audio",
            f"--start={screenshot_time:.2f}",
            "--frames=1",

            # --- HDR 色调映射参数 ---
            # 指定输出为标准的sRGB色彩空间，这是所有SDR图片的基础
            "--target-trc=srgb",
            # 使用 'hable' 算法进行色调映射，它能在保留高光和阴影细节方面取得良好平衡
            "--tone-mapping=hable",
            # 如果色彩依然不准，可以尝试更现代的 'bt.2390' 算法
            # "--tone-mapping=bt.2390",
            f"--o={intermediate_png_path}",
            target_video_file
        ]
        # --- [核心修改结束] ---

        try:
            subprocess.run(cmd_screenshot,
                           check=True,
                           capture_output=True,
                           timeout=180)

            if not os.path.exists(intermediate_png_path):
                print(f"❌ 错误: mpv 命令执行成功，但未找到输出文件 {intermediate_png_path}")
                continue

            print(
                f"   -> 中间PNG图 {os.path.basename(intermediate_png_path)} 生成成功。"
            )

            try:
                with Image.open(intermediate_png_path) as img:
                    rgb_img = img.convert('RGB')
                    rgb_img.save(final_jpeg_path, 'jpeg', quality=85)
                print(
                    f"   -> JPEG压缩成功 (质量: 85) -> {os.path.basename(final_jpeg_path)}"
                )
            except Exception as e:
                print(f"   ❌ 错误: 图片从PNG转换为JPEG失败: {e}")
                continue

            max_retries = 3
            image_url = None
            for attempt in range(max_retries):
                print(f"   -> 正在上传 (第 {attempt+1}/{max_retries} 次尝试)...")
                try:
                    if hoster == "agsv":
                        image_url = _upload_to_agsv(final_jpeg_path,
                                                    auth_token)
                    else:
                        image_url = _upload_to_pixhost(final_jpeg_path)
                    if image_url:
                        uploaded_urls.append(image_url)
                        break
                    else:
                        time.sleep(2)
                except Exception as e:
                    print(f"   -> 上传尝试 {attempt+1} 出现异常: {e}")
                    time.sleep(2)

            if not image_url:
                print(f"⚠️  第 {i+1} 张图片经过 {max_retries} 次尝试后仍然上传失败。")

        except subprocess.CalledProcessError as e:
            error_output = e.stderr.decode('utf-8', errors='ignore')
            print(f"❌ 错误: mpv 截图失败。")
            print(f"   -> Stderr: {error_output}")
            continue
        except subprocess.TimeoutExpired:
            print(f"❌ 错误: mpv 截图超时 (超过60秒)。")
            continue

    print("\n--- 所有截图处理完毕 ---")
    print(f"正在清理临时目录中的 {len(temp_files_to_cleanup)} 个截图文件...")
    for item_path in temp_files_to_cleanup:
        try:
            if os.path.exists(item_path):
                os.remove(item_path)
        except OSError as e:
            print(f"清理临时文件 {item_path} 失败: {e}")

    if not uploaded_urls:
        print("任务完成，但没有成功上传任何图片。")
        return ""

    bbcode_links = []
    for url in sorted(uploaded_urls):
        if "pixhost.to/show/" in url:
            bbcode_links.append(
                f"[img]{url.replace('https://pixhost.to/show/', 'https://img1.pixhost.to/images/')}[/img]"
            )
        else:
            bbcode_links.append(f"[img]{url}[/img]")

    screenshots = "\n".join(bbcode_links)
    print("所有截图已成功上传并已格式化为BBCode。")
    return screenshots


def upload_data_poster(douban_link: str, imdb_link: str):
    """
    通过PT-Gen API获取电影信息的海报和IMDb链接。
    支持从豆瓣链接或IMDb链接获取信息。
    注意：此函数已废弃，请使用upload_data_movie_info替代。
    """
    # 调用新的统一函数获取所有信息
    status, poster, description, imdb_link_result = upload_data_movie_info(
        douban_link, imdb_link)

    if status:
        return True, poster, imdb_link_result
    else:
        return False, description, imdb_link_result


def upload_data_movie_info(douban_link: str, imdb_link: str):
    """
    通过多个PT-Gen API获取电影信息的完整内容，包括海报、简介和IMDb链接。
    支持从豆瓣链接或IMDb链接获取信息，失败时自动切换API。
    返回: (状态, 海报, 简介, IMDb链接)
    """
    # API配置列表，按优先级排序
    api_configs = [
        {
            'name': 'ptn-ptgen.sqing33.dpdns.org',
            'base_url': 'https://ptn-ptgen.sqing33.dpdns.org',
            'type': 'url_format'
        },
        {
            'name': 'ptgen.tju.pt',
            'base_url': 'https://ptgen.tju.pt/infogen',
            'type': 'tju_format',
            'force_douban': True  # 强制使用site=douban模式
        },
        {
            'name': 'ptgen.homeqian.top',
            'base_url': 'https://ptgen.homeqian.top',
            'type': 'url_format'
        },
        {
            'name': 'api.iyuu.cn',
            'base_url': 'https://api.iyuu.cn/App.Movie.Ptgen',
            'type': 'iyuu_format'
        }
    ]

    # 确定要使用的资源URL（豆瓣优先）
    if not douban_link and not imdb_link:
        return False, "", "", "未提供豆瓣或IMDb链接。"

    # 尝试每个API
    last_error = ""
    for api_config in api_configs:
        try:
            print(f"尝试使用API: {api_config['name']}")

            if api_config['type'] == 'tju_format':
                # TJU格式API (ptgen.tju.pt) - 强制使用豆瓣模式
                success, poster, description, imdb_link_result = _call_tju_format_api(
                    api_config, douban_link, imdb_link)
            elif api_config['type'] == 'url_format':
                # URL格式API (workers.dev, homeqian.top)
                success, poster, description, imdb_link_result = _call_url_format_api(
                    api_config, douban_link, imdb_link)
            elif api_config['type'] == 'iyuu_format':
                # IYUU格式API (api.iyuu.cn)
                success, poster, description, imdb_link_result = _call_iyuu_format_api(
                    api_config, douban_link, imdb_link)
            else:
                continue

            if success:
                print(f"API {api_config['name']} 调用成功")
                return True, poster, description, imdb_link_result
            else:
                last_error = description  # 错误信息存储在description中
                print(f"API {api_config['name']} 返回失败: {last_error}")

        except Exception as e:
            last_error = f"API {api_config['name']} 请求异常: {e}"
            print(last_error)
            continue

    # 所有API都失败
    return False, "", "", f"所有PT-Gen API都失败。最后错误: {last_error}"


def _call_tju_format_api(api_config: dict, douban_link: str, imdb_link: str):
    """
    调用TJU格式API (ptgen.tju.pt) - 强制使用site=douban模式
    """
    try:
        # 强制使用site=douban，这样IMDb链接也会被转换查询豆瓣
        if douban_link:
            # 从豆瓣链接提取ID
            douban_id = _extract_douban_id(douban_link)
            if douban_id:
                url = f"{api_config['base_url']}?site=douban&sid={douban_id}"
            else:
                raise ValueError("无法从豆瓣链接提取ID")
        elif imdb_link:
            # 从IMDb链接提取ID，但强制使用douban模式
            imdb_id = _extract_imdb_id(imdb_link)
            if imdb_id:
                url = f"{api_config['base_url']}?site=douban&sid={imdb_id}"
            else:
                raise ValueError("无法从IMDb链接提取ID")
        else:
            raise ValueError("没有可用的链接")

        response = requests.get(url, timeout=30)
        response.raise_for_status()

        data = response.json()

        if not data.get('success', False):
            error_msg = data.get('error', '未知错误')
            return False, "", f"API返回失败: {error_msg}", ""

        format_data = data.get('format', '')
        if not format_data:
            return False, "", "API未返回有效的格式化内容", ""

        # 提取信息
        extracted_imdb_link = data.get('imdb_link', '')
        poster = ""
        description = ""

        # 提取海报图片
        img_match = re.search(r'(\[img\].*?\[/img\])', format_data)
        if img_match:
            poster = re.sub(r'img1', 'img9', img_match.group(1))

        # 提取简介内容（去除海报部分）
        description = re.sub(r'\[img\].*?\[/img\]', '', format_data).strip()
        description = re.sub(r'\n{3,}', '\n\n', description)

        return True, poster, description, extracted_imdb_link

    except Exception as e:
        return False, "", f"TJU格式API调用失败: {e}", ""


def _call_url_format_api(api_config: dict, douban_link: str, imdb_link: str):
    """
    调用URL格式API (workers.dev, homeqian.top)
    """
    try:
        resource_url = douban_link or imdb_link
        url = f"{api_config['base_url']}/?url={resource_url}"

        response = requests.get(url, timeout=30)
        response.raise_for_status()

        # 尝试解析为JSON
        try:
            data = response.json()
        except:
            # 如果不是JSON，可能是直接返回的文本格式
            text_content = response.text.strip()
            if text_content and ('[img]' in text_content
                                 or '◎' in text_content):
                # 直接返回文本内容作为format
                return _parse_format_content(text_content)
            else:
                return False, "", "API返回了无效的内容格式", ""

        # JSON格式处理
        if isinstance(data, dict):
            # 检查是否有错误
            if data.get('success') is False:
                error_msg = data.get('message', data.get('error', '未知错误'))
                return False, "", f"API返回失败: {error_msg}", ""

            # 获取格式化内容
            format_data = data.get('format', data.get('content', ''))
            if format_data:
                return _parse_format_content(format_data,
                                             data.get('imdb_link', ''))
            else:
                return False, "", "API未返回有效的格式化内容", ""
        else:
            return False, "", "API返回了无效的数据格式", ""

    except Exception as e:
        return False, "", f"URL格式API调用失败: {e}", ""


def _call_iyuu_format_api(api_config: dict, douban_link: str, imdb_link: str):
    """
    调用IYUU格式API (api.iyuu.cn)
    """
    try:
        resource_url = douban_link or imdb_link
        url = f"{api_config['base_url']}?url={resource_url}"

        response = requests.get(url, timeout=30)
        response.raise_for_status()

        data = response.json()

        # 检查业务状态码
        if data.get('ret') != 200 and data.get('ret') != 0:
            error_msg = data.get('msg', '未知错误')
            return False, "", f"API返回错误(状态码{data.get('ret')}): {error_msg}", ""

        format_data = data.get('format') or data.get('data', {}).get(
            'format', '')
        if not format_data:
            return False, "", "API未返回有效的简介内容", ""

        return _parse_format_content(format_data)

    except Exception as e:
        return False, "", f"IYUU格式API调用失败: {e}", ""


def _parse_format_content(format_data: str, provided_imdb_link: str = ""):
    """
    解析格式化内容，提取海报、简介和IMDb链接
    自动对海报进行智能验证和转存到pixhost
    """
    try:
        # 提取信息
        extracted_imdb_link = provided_imdb_link
        poster = ""
        description = ""

        # 如果没有提供IMDb链接，尝试从格式化内容中提取
        if not extracted_imdb_link:
            imdb_match = re.search(
                r'◎IMDb链接\s*(https?://www\.imdb\.com/title/tt\d+/)',
                format_data)
            if imdb_match:
                extracted_imdb_link = imdb_match.group(1)

        # 提取海报图片并进行智能验证和转存
        img_match = re.search(r'\[img\](.*?)\[/img\]', format_data)
        if img_match:
            original_poster_url = img_match.group(1)
            
            # 检查是否已经是pixhost图床
            if 'pixhost.to' in original_poster_url or 'img1.pixhost.to' in original_poster_url:
                # 已经是pixhost，直接使用
                print(f"[*] 海报已是pixhost图床，直接使用: {original_poster_url}")
                poster = f"[img]{original_poster_url}[/img]"
            else:
                # 非pixhost，进行智能验证和转存
                print(f"[*] 海报非pixhost图床，执行智能验证和转存...")
                smart_poster_url = _get_smart_poster_url(original_poster_url)
                
                if smart_poster_url:
                    poster = f"[img]{smart_poster_url}[/img]"
                    print(f"[*] 智能验证和转存成功: {smart_poster_url}")
                else:
                    # 智能获取失败，保留原URL
                    print(f"[*] 智能验证失败，使用原始URL")
                    poster = f"[img]{original_poster_url}[/img]"

        # 提取简介内容（去除海报部分）
        description = re.sub(r'\[img\].*?\[/img\]', '', format_data).strip()
        description = re.sub(r'\n{3,}', '\n\n', description)

        return True, poster, description, extracted_imdb_link

    except Exception as e:
        return False, "", f"解析格式化内容失败: {e}", ""


def _extract_douban_id(douban_link: str) -> str:
    """
    从豆瓣链接中提取ID
    例如: https://movie.douban.com/subject/34832354/ -> 34832354
    """
    match = re.search(r'/subject/(\d+)', douban_link)
    return match.group(1) if match else ""


def _extract_imdb_id(imdb_link: str) -> str:
    """
    从IMDb链接中提取ID
    例如: https://www.imdb.com/title/tt13721828/ -> tt13721828
    """
    match = re.search(r'/title/(tt\d+)', imdb_link)
    return match.group(1) if match else ""


# (确保文件顶部有 import bencoder, import json)

# utils/media_helper.py


def add_torrent_to_downloader(detail_page_url: str, save_path: str,
                              downloader_id: str, db_manager, config_manager):
    """
    从种子详情页下载 .torrent 文件并添加到指定的下载器。
    [最终修复版] 修正了向 Transmission 发送数据时的双重编码问题。
    """
    logging.info(
        f"开始自动添加任务: URL='{detail_page_url}', Path='{save_path}', DownloaderID='{downloader_id}'"
    )

    # 1. 查找对应的站点配置
    conn = db_manager._get_connection()
    cursor = db_manager._get_cursor(conn)
    cursor.execute("SELECT nickname, base_url, cookie, speed_limit FROM sites")
    site_info = None
    for site in cursor.fetchall():
        # [修复] 确保 base_url 存在且不为空
        if site['base_url'] and site['base_url'] in detail_page_url:
            site_info = dict(site)  # [修复] 将 sqlite3.Row 转换为 dict
            break
    conn.close()

    if not site_info or not site_info.get("cookie"):
        msg = f"未能找到与URL '{detail_page_url}' 匹配的站点配置或该站点缺少Cookie。"
        logging.error(msg)
        return False, msg

    try:
        # 2. 下载种子文件
        common_headers = {
            "Cookie":
            site_info["cookie"],
            "User-Agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
        }
        scraper = cloudscraper.create_scraper()

        # 站点级别的代理已不使用全局代理配置
        proxies = None

        # Add retry logic for network requests
        max_retries = 3
        for attempt in range(max_retries):
            try:
                details_response = scraper.get(detail_page_url,
                                               headers=common_headers,
                                               timeout=180,
                                               proxies=proxies)
                break  # Success, exit retry loop
            except Exception as e:
                if attempt < max_retries - 1:
                    logging.warning(
                        f"Attempt {attempt + 1} failed to fetch details page: {e}. Retrying..."
                    )
                    time.sleep(2**attempt)  # Exponential backoff
                else:
                    raise  # Re-raise the exception if all retries failed
        details_response.raise_for_status()

        soup = BeautifulSoup(details_response.text, "html.parser")

        # 检查是否需要使用特殊下载器
        site_base_url = ensure_scheme(site_info['base_url'])
        full_download_url = None  # 初始化full_download_url

        print(f"站点基础URL: {site_base_url}")

        # 检查是否为haidan站点
        if 'haidan' in site_base_url:
            # Haidan站点需要提取torrent_id而不是id
            torrent_id_match = re.search(r"torrent_id=(\d+)", detail_page_url)
            if not torrent_id_match:
                raise ValueError("无法从详情页URL中提取种子ID（torrent_id）。")
            torrent_id = torrent_id_match.group(1)
            # Haidan站点的特殊逻辑
            download_link_tag = soup.find(
                'a', href=re.compile(r"download.php\?id="))

            if not download_link_tag: raise RuntimeError("在详情页HTML中未能找到下载链接！")

            download_url_part = str(download_link_tag['href'])  # 显式转换为str

            # 替换下载链接中的id为从detail_page_url中提取的torrent_id
            download_url_part = re.sub(r"id=\d+", f"id={torrent_id}",
                                       download_url_part)

            full_download_url = f"{site_base_url}/{download_url_part}"
        else:
            # 其他站点的通用逻辑 - 提取id参数
            torrent_id_match = re.search(r"id=(\d+)", detail_page_url)
            if not torrent_id_match: raise ValueError("无法从详情页URL中提取种子ID。")
            torrent_id = torrent_id_match.group(1)

            download_link_tag = soup.select_one(
                f'a.index[href^="download.php?id={torrent_id}"]')
            if not download_link_tag: raise RuntimeError("在详情页HTML中未能找到下载链接！")

            download_url_part = str(download_link_tag['href'])  # 显式转换为str
            full_download_url = f"{site_base_url}/{download_url_part}"

        # 确保full_download_url已被赋值
        if not full_download_url:
            raise RuntimeError("未能成功构建种子下载链接！")

        print(f"种子下载链接: {full_download_url}")

        common_headers["Referer"] = detail_page_url
        # Add retry logic for torrent download
        for attempt in range(max_retries):
            try:
                torrent_response = scraper.get(full_download_url,
                                               headers=common_headers,
                                               timeout=180,
                                               proxies=proxies)
                torrent_response.raise_for_status()
                break  # Success, exit retry loop
            except Exception as e:
                if attempt < max_retries - 1:
                    logging.warning(
                        f"Attempt {attempt + 1} failed to download torrent: {e}. Retrying..."
                    )
                    time.sleep(2**attempt)  # Exponential backoff
                else:
                    raise  # Re-raise the exception if all retries failed

        torrent_content = torrent_response.content
        logging.info("已成功下载有效的种子文件内容。")

    except Exception as e:
        msg = f"在下载种子文件步骤发生错误: {e}"
        logging.error(msg, exc_info=True)
        return False, msg

    # 3. 找到下载器配置
    config = config_manager.get()
    downloader_config = next(
        (d for d in config.get("downloaders", [])
         if d.get("id") == downloader_id and d.get("enabled")), None)

    if not downloader_config:
        msg = f"未找到ID为 '{downloader_id}' 的已启用下载器配置。"
        logging.error(msg)
        return False, msg

    # 4. 添加到下载器 (核心修改在此！) - 添加重试机制
    max_retries = 3
    for attempt in range(max_retries):
        try:
            from core.services import _prepare_api_config

            api_config = _prepare_api_config(downloader_config)
            client_name = downloader_config['name']

            if downloader_config['type'] == 'qbittorrent':
                client = qbClient(**api_config)
                client.auth_log_in()

                # 准备 qBittorrent 参数
                qb_params = {
                    'torrent_files': torrent_content,
                    'save_path': save_path,
                    'is_paused': False,
                    'skip_checking': True
                }

                # 如果站点设置了速度限制，则添加速度限制参数
                # 数据库中存储的是MB/s，需要转换为bytes/s传递给下载器API
                if site_info and site_info.get('speed_limit', 0) > 0:
                    speed_limit = int(
                        site_info['speed_limit']) * 1024 * 1024  # 转换为 bytes/s
                    qb_params['upload_limit'] = speed_limit
                    logging.info(
                        f"为站点 '{site_info['nickname']}' 设置上传速度限制: {site_info['speed_limit']} MB/s"
                    )

                result = client.torrents_add(**qb_params)
                logging.info(f"已将种子添加到 qBittorrent '{client_name}': {result}")

            elif downloader_config['type'] == 'transmission':
                client = TrClient(**api_config)

                # 准备 Transmission 参数
                tr_params = {
                    'torrent': torrent_content,
                    'download_dir': save_path,
                    'paused': False
                }

                # 先添加种子
                result = client.add_torrent(**tr_params)
                logging.info(
                    f"已将种子添加到 Transmission '{client_name}': ID={result.id}")

                # 如果站点设置了速度限制，则在添加后设置速度限制
                # add_torrent 方法不支持速度限制参数，需要使用 change_torrent 方法
                if site_info and site_info.get('speed_limit', 0) > 0:
                    # 转换为 KBps: MB/s * 1024 = KBps
                    speed_limit_kbps = int(site_info['speed_limit']) * 1024
                    try:
                        client.change_torrent(result.id,
                                              upload_limit=speed_limit_kbps,
                                              upload_limited=True)
                        logging.info(
                            f"为站点 '{site_info['nickname']}' 设置上传速度限制: {site_info['speed_limit']} MB/s ({speed_limit_kbps} KBps)"
                        )
                    except Exception as e:
                        logging.warning(f"设置速度限制失败，但种子已添加成功: {e}")

            return True, f"成功添加到 '{client_name}'"

        except Exception as e:
            logging.warning(f"第 {attempt + 1} 次尝试添加种子到下载器失败: {e}")

            # 如果不是最后一次尝试，等待一段时间后重试
            if attempt < max_retries - 1:
                wait_time = 2**attempt  # 指数退避
                logging.info(f"等待 {wait_time} 秒后进行第 {attempt + 2} 次尝试...")
                time.sleep(wait_time)
            else:
                msg = f"添加到下载器 '{downloader_config['name']}' 时失败: {e}"
                logging.error(msg, exc_info=True)
                return False, msg


def extract_tags_from_title(title_components: list) -> list:
    """
    从标题参数中提取标签，主要从媒介和制作组字段提取 DIY 和 VCB-Studio 标签。
    
    返回原始标签名称（如 "DIY", "VCB-Studio"），而不是标准化键。
    这样可以被 ParameterMapper 正确映射到 global_mappings.yaml 中定义的标准化键。

    :param title_components: 标题组件列表，格式为 [{"key": "主标题", "value": "..."}, ...]
    :return: 一个包含原始标签名称的列表，例如 ['DIY', 'VCB-Studio']
    """
    if not title_components:
        return []

    found_tags = set()

    # 将 title_components 转换为字典以便查找
    title_dict = {
        item.get('key'): item.get('value', '')
        for item in title_components
    }

    # 定义需要检查的字段和对应的标签映射
    # 格式：字段名 -> [(正则模式, 原始标签名), ...]
    # 注意：这里返回的是原始标签名（如 "DIY"），而不是标准化键（如 "tag.diy"）
    tag_extraction_rules = {
        '媒介': [
            (r'\bDIY\b', 'DIY'),
            (r'\bBlu-?ray\s+DIY\b', 'DIY'),
            (r'\bBluRay\s+DIY\b', 'DIY'),
        ],
        '制作组': [
            (r'\bDIY\b', 'DIY'),
            (r'\bVCB-Studio\b', 'VCB-Studio'),
            (r'\bVCB\b', 'VCB-Studio'),
        ]
    }

    # 遍历需要检查的字段
    for field_name, patterns in tag_extraction_rules.items():
        field_value = title_dict.get(field_name, '')

        if not field_value:
            continue

        # 如果字段值是列表，转换为字符串
        if isinstance(field_value, list):
            field_value = ' '.join(str(v) for v in field_value)
        else:
            field_value = str(field_value)

        # 检查每个正则模式
        for pattern, tag_name in patterns:
            if re.search(pattern, field_value, re.IGNORECASE):
                found_tags.add(tag_name)
                print(
                    f"从标题参数 '{field_name}' 中提取到标签: {tag_name} (匹配: {pattern})")

    result_tags = list(found_tags)
    if result_tags:
        print(f"从标题参数中提取到的标签: {result_tags}")
    else:
        print("从标题参数中未提取到任何标签")

    return result_tags


def extract_tags_from_subtitle(subtitle: str) -> list:
    """
    从副标题中提取标签，目前主要检测"特效"关键词。
    
    :param subtitle: 副标题文本
    :return: 标签列表，例如 ['特效']
    """
    if not subtitle:
        return []

    found_tags = []

    # 检查副标题中是否包含"特效"关键词
    if "特效" in subtitle:
        found_tags.append("tag.特效")
        print(f"从副标题中提取到标签: 特效")

    if found_tags:
        print(f"从副标题中提取到的标签: {found_tags}")
    else:
        print("从副标题中未提取到任何标签")

    return found_tags


def extract_tags_from_description(description_text: str) -> list:
    """
    从简介文本的"类别"字段中提取标签。
    
    :param description_text: 简介文本内容（包括statement和body）
    :return: 标签列表，例如 ['tag.喜剧', 'tag.动画']
    """
    if not description_text:
        return []

    found_tags = []

    # 从简介中提取类别字段
    category_match = re.search(r"◎\s*类\s*别\s*(.+?)(?:\n|$)", description_text)
    if category_match:
        category_text = category_match.group(1).strip()
        print(f"从简介中提取到类别: {category_text}")

        # 定义类别关键词到标签的映射
        category_tag_map = {
            '喜剧': 'tag.喜剧',
            'Comedy': 'tag.喜剧',
            '动画': 'tag.动画',
            'Animation': 'tag.动画',
            '动作': 'tag.动作',
            'Action': 'tag.动作',
            '爱情': 'tag.爱情',
            'Romance': 'tag.爱情',
            '科幻': 'tag.科幻',
            'Sci-Fi': 'tag.科幻',
            '恐怖': 'tag.恐怖',
            'Horror': 'tag.恐怖',
            '惊悚': 'tag.惊悚',
            'Thriller': 'tag.惊悚',
            '悬疑': 'tag.悬疑',
            'Mystery': 'tag.悬疑',
            '犯罪': 'tag.犯罪',
            'Crime': 'tag.犯罪',
            '战争': 'tag.战争',
            'War': 'tag.战争',
            '冒险': 'tag.冒险',
            'Adventure': 'tag.冒险',
            '奇幻': 'tag.奇幻',
            'Fantasy': 'tag.奇幻',
            '家庭': 'tag.家庭',
            'Family': 'tag.家庭',
            '剧情': 'tag.剧情',
            'Drama': 'tag.剧情',
        }

        # 检查类别文本中是否包含关键词
        for keyword, tag in category_tag_map.items():
            if keyword in category_text:
                found_tags.append(tag)
                print(f"   从类别中提取到标签: {tag} (匹配关键词: {keyword})")

    if found_tags:
        print(f"从简介类别中提取到的标签: {found_tags}")
    else:
        print("从简介类别中未提取到任何标签")

    return found_tags


def check_animation_type_from_description(description_text: str) -> bool:
    """
    检查简介的类别字段中是否包含"动画"，用于判断是否需要修正类型为动漫。
    
    :param description_text: 简介文本内容（包括statement和body）
    :return: 如果包含"动画"返回True，否则返回False
    """
    if not description_text:
        return False

    # 从简介中提取类别字段
    category_match = re.search(r"◎\s*类\s*别\s*(.+?)(?:\n|$)", description_text)
    if category_match:
        category_text = category_match.group(1).strip()

        # 检查类别中是否包含"动画"关键词
        if "动画" in category_text or "Animation" in category_text:
            print(f"检测到类别中包含'动画': {category_text}")
            return True

    return False


def extract_tags_from_mediainfo(mediainfo_text: str) -> list:
    """
    从 MediaInfo 文本中提取关键词，并返回一个标准化的标签列表。

    :param mediainfo_text: 完整的 MediaInfo 报告字符串。
    :return: 一个包含识别出的标签字符串的列表，例如 ['tag.国语', 'tag.中字', 'tag.HDR10']。
    """
    if not mediainfo_text:
        return []

    found_tags = set()
    lines = mediainfo_text.split('\n')  # 不转小写，保持原始大小写

    # 定义关键词到标准化标签的映射
    tag_keywords_map = {
        # 语言标签
        '国语': ['国语', 'mandarin'],
        '粤语': ['粤语', 'cantonese'],
        '英语': ['英语', 'english'],
        '日语': ['日语', 'Japanese', 'japanese'],
        '韩语': ['韩语', 'korean'],
        '法语': ['法语', 'french'],
        '德语': ['德语', 'german'],
        '俄语': ['俄语', 'russian'],
        '印地语': ['印地语', 'hindi'],
        '西班牙语': ['西班牙语', 'spanish'],
        '葡萄牙语': ['葡萄牙语', 'portuguese'],
        '意大利语': ['意大利语', 'italian'],
        '泰语': ['泰语', 'thai'],
        '阿拉伯语': ['阿拉伯语', 'arabic'],
        '外语': ['外语', 'foreign'],
        # 字幕标签
        '中字': ['中字', 'chinese', '简', '繁'],
        '英字': ['英字', 'english'],
        # HDR 格式标签
        'Dolby Vision': ['dolby vision', '杜比视界'],
        'HDR10+': ['hdr10+'],
        'HDR10': ['hdr10'],
        'HDR': ['hdr'],  # 作为通用 HDR 的备用选项
        'HDRVivid': ['hdr vivid'],
    }

    # 定义检查范围
    # current_section 用于记录当前 MediaInfo 正在处理的 Section 类型 (General, Video, Audio, Text)
    current_section = None
    # 用于收集当前 Audio Section 的所有行，以便后续语言检测
    current_audio_section_lines = []
    # 用于收集当前 Video Section 的所有行，以便后续语言检测
    current_video_section_lines = []

    for line in lines:
        line_stripped = line.strip()
        line_lower = line_stripped.lower()

        # 判定当前处于哪个信息块
        if line_lower.startswith('general'):
            current_section = 'general'
            # 在 General Section 结束时处理之前的 Audio/Video Section
            if current_audio_section_lines:
                _process_audio_section_languages(current_audio_section_lines,
                                                 found_tags)
                current_audio_section_lines = []
            if current_video_section_lines:
                _process_video_section_languages(current_video_section_lines,
                                                 found_tags)
                current_video_section_lines = []
            continue
        elif line_lower.startswith('video'):
            current_section = 'video'
            if current_audio_section_lines:
                _process_audio_section_languages(current_audio_section_lines,
                                                 found_tags)
                current_audio_section_lines = []
            current_video_section_lines = [line_stripped]  # 开始新的 Video 块
            continue
        elif line_lower.startswith('audio'):
            current_section = 'audio'
            if current_video_section_lines:
                _process_video_section_languages(current_video_section_lines,
                                                 found_tags)
                current_video_section_lines = []
            current_audio_section_lines = [line_stripped]  # 开始新的 Audio 块
            continue
        elif line_lower.startswith('text'):
            current_section = 'text'
            if current_audio_section_lines:
                _process_audio_section_languages(current_audio_section_lines,
                                                 found_tags)
                current_audio_section_lines = []
            if current_video_section_lines:
                _process_video_section_languages(current_video_section_lines,
                                                 found_tags)
                current_video_section_lines = []
            continue
        # 其他 Section 暂不处理，直接跳过或者可以定义为 'other'
        elif not line_stripped:  # 空行表示一个Section的结束，可以触发处理
            if current_audio_section_lines and current_section != 'audio':  # 如果是空行且之前是音频块，则处理
                _process_audio_section_languages(current_audio_section_lines,
                                                 found_tags)
                current_audio_section_lines = []
            if current_video_section_lines and current_section != 'video':  # 如果是空行且之前是视频块，则处理
                _process_video_section_languages(current_video_section_lines,
                                                 found_tags)
                current_video_section_lines = []
            current_section = None  # 重置当前section
            continue

        # 收集当前 Section 的行
        if current_section == 'audio':
            current_audio_section_lines.append(line_stripped)
        elif current_section == 'video':
            current_video_section_lines.append(line_stripped)
        elif current_section == 'text':
            # 仅在 Text 块中检查字幕标签
            if '中字' in tag_keywords_map and any(
                    kw in line_lower for kw in tag_keywords_map['中字']):
                found_tags.add('中字')
            if '英字' in tag_keywords_map and any(
                    kw in line_lower for kw in tag_keywords_map['英字']):
                found_tags.add('英字')

        # 检查 HDR 格式标签 (全局检查)
        # 注意：这里保持全局检查是因为 HDR 格式可能出现在 General/Video 等多个地方
        if 'dolby vision' in tag_keywords_map and any(
                kw in line_lower for kw in tag_keywords_map['Dolby Vision']):
            found_tags.add('Dolby Vision')
        if 'hdr10+' in tag_keywords_map and any(
                kw in line_lower for kw in tag_keywords_map['HDR10+']):
            found_tags.add('HDR10+')
        if 'hdr10' in tag_keywords_map and any(
                kw in line_lower for kw in tag_keywords_map['HDR10']):
            found_tags.add('HDR10')
        elif 'hdr' in tag_keywords_map and any(
                kw in line_lower for kw in tag_keywords_map['HDR']):
            if not any(hdr_tag in found_tags
                       for hdr_tag in ['Dolby Vision', 'HDR10+', 'HDR10']):
                found_tags.add('HDR')
        if 'hdrvivid' in tag_keywords_map and any(
                kw in line_lower for kw in tag_keywords_map['HDRVivid']):
            found_tags.add('HDRVivid')

    # 处理文件末尾可能存在的 Audio/Video Section
    if current_audio_section_lines:
        _process_audio_section_languages(current_audio_section_lines,
                                         found_tags)
    if current_video_section_lines:
        _process_video_section_languages(current_video_section_lines,
                                         found_tags)

    # 为所有标签添加 tag. 前缀
    prefixed_tags = set()
    for tag in found_tags:
        if not tag.startswith('tag.'):  # 避免重复添加 tag.
            prefixed_tags.add(f'tag.{tag}')
        else:
            prefixed_tags.add(tag)

    print(f"从 MediaInfo 中提取到的标签: {list(prefixed_tags)}")
    return list(prefixed_tags)


def _process_audio_section_languages(audio_lines, found_tags):
    """辅助函数：处理音频块中的语言检测"""
    language = _check_language_in_section(audio_lines)
    if language:
        if language == '国语':
            found_tags.add('国语')
        elif language == '粤语':
            found_tags.add('粤语')
        else:  # 其他语言
            found_tags.add(language)
            found_tags.add('外语')
        print(f"   -> 从音频块中提取到语言: {language}")


def _process_video_section_languages(video_lines, found_tags):
    """辅助函数：处理视频块中的语言检测"""
    language = _check_language_in_section(video_lines)
    if language:
        if language == '国语':
            found_tags.add('国语')
        elif language == '粤语':
            found_tags.add('粤语')
        else:  # 其他语言
            found_tags.add(language)
            found_tags.add('外语')
        print(f"   -> 从视频块中提取到语言: {language}")


def _check_language_in_section(section_lines) -> str | None:
    """
    通用函数：检查指定 Section 块中是否包含语言相关标识。

    :param section_lines: Section 块的所有行
    :return: 如果检测到语言返回具体语言名称，否则返回None
    """
    language_keywords_map = {
        '国语': ['中文', 'chinese', 'mandarin', '国语'],
        '粤语': ['cantonese', '粤语'],
        '英语': ['english', '英语'],
        '日语': ['japanese', '日语'],
        '韩语': ['korean', '韩语'],
        '法语': ['french', '法语'],
        '德语': ['german', '德语'],
        '俄语': ['russian', '俄语'],
        '印地语': ['hindi', '印地语'],
        '西班牙语': ['spanish', '西班牙语', 'latin america'],  # 添加 Latin America
        '葡萄牙语': ['portuguese', '葡萄牙语', 'br'],  # 添加 BR
        '意大利语': ['italian', '意大利语'],
        '泰语': ['thai', '泰语'],
        '阿拉伯语': ['arabic', '阿拉伯语', 'sa'],  # 添加 SA
    }

    for line in section_lines:
        if not line:
            continue
        line_lower = line.lower()
        if 'language:' in line_lower:
            for lang, keywords in language_keywords_map.items():
                for keyword in keywords:
                    if keyword.lower() in line_lower:
                        return lang
        # 尝试从 Title: 中提取
        if 'title:' in line_lower:
            for lang, keywords in language_keywords_map.items():
                for keyword in keywords:
                    if keyword.lower() in line_lower:
                        return lang
    return None


# 删除这两个不再使用的辅助函数
def _check_mandarin_in_audio_section(audio_lines):
    return False  # Placeholder to avoid errors during diff application


def _check_other_language_in_audio_section(audio_lines) -> str | None:
    return None  # Placeholder to avoid errors during diff application


def extract_origin_from_description(description_text: str) -> str:
    """
    从简介详情中提取产地信息。

    :param description_text: 简介详情文本
    :return: 产地信息，例如 "日本"、"中国" 等
    """
    if not description_text:
        return ""

    # 使用正则表达式匹配 "◎产　　地　日本" 这种格式
    # 支持多种变体：◎产地、◎产　　地、◎国　　家、◎国家地区等
    # 修复：使用 [^\n\r]+ 而不是 .+? 来正确匹配包含空格的产地名称（如"中国大陆"）
    patterns = [
        r"◎\s*产\s*地\s*([^\n\r]+?)(?:\n|$)",  # 匹配 ◎产地 中国大陆
        r"◎\s*国\s*家\s*([^\n\r]+?)(?:\n|$)",  # 匹配 ◎国家 中国大陆
        r"◎\s*地\s*区\s*([^\n\r]+?)(?:\n|$)",  # 匹配 ◎地区 中国大陆
        r"◎\s*国家地区\s*([^\n\r]+?)(?:\n|$)",  # 匹配 ◎国家地区 中国大陆
        r"制片国家/地区[:\s]+([^\n\r]+?)(?:\n|$)",  # 匹配 制片国家/地区: 中国大陆
        r"制片国家[:\s]+([^\n\r]+?)(?:\n|$)",  # 匹配 制片国家: 中国大陆
        r"国家[:\s]+([^\n\r]+?)(?:\n|$)",  # 匹配 国家: 中国大陆
        r"产地[:\s]+([^\n\r]+?)(?:\n|$)",  # 匹配 产地: 中国大陆
        r"[产]\s*地[:\s]+([^，,\n\r]+)",
        r"[国]\s*家[:\s]+([^，,\n\r]+)",
        r"[地]\s*区[:\s]+([^，,\n\r]+)"
    ]

    for pattern in patterns:
        match = re.search(pattern, description_text)
        if match:
            origin = match.group(1).strip()
            # 清理可能的多余字符
            origin = re.sub(r'[\[\]【】\(\)]', '', origin).strip()
            # 移除常见的分隔符，如" / "、","等
            origin = re.split(r'\s*/\s*|\s*,\s*|\s*;\s*|\s*&\s*',
                              origin)[0].strip()
            print("提取到产地信息:", origin)

            return origin

    return ""


def extract_resolution_from_mediainfo(mediainfo_text: str) -> str:
    """
    从 MediaInfo 文本中提取分辨率信息。

    :param mediainfo_text: 完整的 MediaInfo 报告字符串。
    :return: 分辨率信息，例如 "720p"、"1080p"、"2160p" 等
    """
    if not mediainfo_text:
        return ""

    # 查找 Video 部分
    video_section_match = re.search(r"Video[\s\S]*?(?=\n\n|\Z)",
                                    mediainfo_text)
    if not video_section_match:
        return ""

    video_section = video_section_match.group(0)

    # 查找分辨率信息
    # 匹配格式如：Width                                 : 1 920 pixels
    #            Height                                : 1 080 pixels
    # 处理带空格的数字格式，如 "1 920" -> "1920"
    width_match = re.search(r"[Ww]idth\s*:\s*(\d+)\s*(\d*)\s*pixels?",
                            video_section)
    height_match = re.search(r"[Hh]eight\s*:\s*(\d+)\s*(\d*)\s*pixels?",
                             video_section)

    width = None
    height = None

    if width_match:
        # 处理带空格的数字格式，如 "1 920" -> "1920"
        w_groups = width_match.groups()
        if w_groups and len(w_groups) >= 2 and w_groups[1]:
            width = int(f"{w_groups[0]}{w_groups[1]}")
        elif w_groups and len(w_groups) >= 1 and w_groups[0]:
            width = int(w_groups[0])
        else:
            width = None

    if height_match:
        # 处理带空格的数字格式，如 "1 080" -> "1080"
        h_groups = height_match.groups()
        if h_groups and len(h_groups) >= 2 and h_groups[1]:
            height = int(f"{h_groups[0]}{h_groups[1]}")
        elif h_groups and len(h_groups) >= 1 and h_groups[0]:
            height = int(h_groups[0])
        else:
            height = None

    # 如果没有找到标准格式，尝试其他格式
    if not width or not height:
        # 备用方法：查找类似 "1920 / 1080" 的格式
        resolution_match = re.search(r"(\d{3,4})\s*/\s*(\d{3,4})",
                                     video_section)
        if resolution_match:
            width = int(resolution_match.group(1))
            height = int(resolution_match.group(2))
        else:
            # 查找其他格式的分辨率信息
            other_resolution_match = re.search(r"(\d{3,4})\s*[xX]\s*(\d{3,4})",
                                               mediainfo_text)
            if other_resolution_match:
                width = int(other_resolution_match.group(1))
                height = int(other_resolution_match.group(2))

    # 如果找到了宽度和高度，转换为标准格式
    if width and height:
        # 根据高度确定标准分辨率
        if height <= 480:
            return "480p"
        elif height <= 576:
            return "576p"
        elif height <= 720:
            return "720p"
        elif height <= 1080:
            return "1080p"
        elif height <= 1440:
            return "1440p"
        elif height <= 2160:
            return "2160p"
        else:
            # 对于其他非标准分辨率，返回原始高度加p
            return f"{height}p"

    return ""


def _upload_to_pixhost_direct(image_path: str, api_url: str, params: dict,
                              headers: dict):
    """直接上传图片到Pixhost"""
    try:
        with open(image_path, 'rb') as f:
            files = {'img': f}
            print("正在发送上传请求到 Pixhost...")
            response = requests.post(api_url,
                                     data=params,
                                     files=files,
                                     headers=headers,
                                     timeout=30)

            if response.status_code == 200:
                data = response.json()
                show_url = data.get('show_url')
                print(f"直接上传成功！图片链接: {show_url}")
                return show_url
            else:
                print(f"   ❌ 直接上传失败 (状态码: {response.status_code})")
                return None
    except FileNotFoundError:
        print(f"   ❌ 错误: 找不到图片文件")
        return None
    except requests.exceptions.SSLError as e:
        print(f"   ❌ 直接上传失败: SSL连接错误")
        return None
    except requests.exceptions.ConnectionError as e:
        print(f"   ❌ 直接上传失败: 网络连接被重置")
        return None
    except requests.exceptions.Timeout:
        print(f"   ❌ 直接上传失败: 请求超时")
        return None
    except Exception as e:
        # 只打印异常类型和简短描述，不打印完整堆栈
        error_type = type(e).__name__
        print(f"   ❌ 直接上传失败: {error_type}")
        return None


def _get_downloader_proxy_config(downloader_id: str = None):
    """
    根据下载器ID获取代理配置。

    :param downloader_id: 下载器ID
    :return: 代理配置字典，如果不需要代理则返回None
    """
    if not downloader_id:
        return None

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

    return None


def check_intro_completeness(body_text: str) -> dict:
    """
    检查简介是否完整，包含必要的影片信息字段。
    
    :param body_text: 简介正文内容
    :return: 包含检测结果的字典 {
        "is_complete": bool,      # 是否完整
        "missing_fields": list,   # 缺失的字段列表
        "found_fields": list      # 已找到的字段列表
    }
    
    示例:
        >>> result = check_intro_completeness(intro_body)
        >>> if not result["is_complete"]:
        >>>     print(f"缺少字段: {result['missing_fields']}")
    """
    if not body_text:
        return {
            "is_complete": False,
            "missing_fields": ["所有字段"],
            "found_fields": []
        }

    # 定义必要字段的匹配模式
    # 每个字段可以有多个匹配模式（正则表达式）
    required_patterns = {
        "片名": [
            r"◎\s*片\s*名", r"◎\s*译\s*名", r"◎\s*标\s*题", r"片名\s*[:：]",
            r"译名\s*[:：]", r"Title\s*[:：]"
        ],
        "年代": [
            r"◎\s*年\s*代", r"◎\s*年\s*份", r"年份\s*[:：]", r"年代\s*[:：]",
            r"Year\s*[:：]"
        ],
        "产地": [
            r"◎\s*产\s*地", r"◎\s*国\s*家", r"◎\s*地\s*区", r"制片国家/地区\s*[:：]",
            r"制片国家\s*[:：]", r"国家\s*[:：]", r"产地\s*[:：]", r"Country\s*[:：]"
        ],
        "类别": [
            r"◎\s*类\s*别", r"◎\s*类\s*型", r"类型\s*[:：]", r"类别\s*[:：]",
            r"Genre\s*[:：]"
        ],
        "语言": [r"◎\s*语\s*言", r"语言\s*[:：]", r"Language\s*[:：]"],
        "导演": [r"◎\s*导\s*演", r"导演\s*[:：]", r"Director\s*[:：]"],
        "简介": [
            r"◎\s*简\s*介", r"◎\s*剧\s*情", r"◎\s*内\s*容", r"简介\s*[:：]",
            r"剧情\s*[:：]", r"内容简介\s*[:：]", r"Plot\s*[:：]", r"Synopsis\s*[:：]"
        ]
    }

    found_fields = []
    missing_fields = []

    # 检查每个必要字段
    for field_name, patterns in required_patterns.items():
        field_found = False
        for pattern in patterns:
            if re.search(pattern, body_text, re.IGNORECASE):
                field_found = True
                break

        if field_found:
            found_fields.append(field_name)
        else:
            missing_fields.append(field_name)

    # 判断完整性：必须包含以下关键字段
    # 片名、产地、导演、简介 这4个字段是最关键的
    critical_fields = ["片名", "产地", "导演", "简介"]
    is_complete = all(field in found_fields for field in critical_fields)

    return {
        "is_complete": is_complete,
        "missing_fields": missing_fields,
        "found_fields": found_fields
    }


def is_image_url_valid_robust(url: str) -> bool:
    """
    一个更稳健的方法，当HEAD请求失败时，会尝试使用GET请求（流式）进行验证。
    如果直接请求失败，会尝试使用全局代理重试一次。
    """
    if not url:
        return False

    # 第一次尝试：不使用代理
    try:
        # 首先尝试HEAD请求，允许重定向
        response = requests.head(url, timeout=5, allow_redirects=True)
        response.raise_for_status()  # 如果状态码不是2xx，则抛出异常

        # 检查Content-Type
        content_type = response.headers.get('Content-Type')
        if content_type and content_type.startswith('image/'):
            return True
        else:
            logging.warning(
                f"链接有效但内容可能不是图片: {url} (Content-Type: {content_type})")
            return False

    except requests.exceptions.RequestException:
        # 如果HEAD请求失败，尝试GET请求
        try:
            response = requests.get(url,
                                    stream=True,
                                    timeout=5,
                                    allow_redirects=True)
            response.raise_for_status()

            # 检查Content-Type
            content_type = response.headers.get('Content-Type')
            if content_type and content_type.startswith('image/'):
                return True
            else:
                logging.warning(
                    f"链接有效但内容可能不是图片: {url} (Content-Type: {content_type})")
                return False

        except requests.exceptions.RequestException as e:
            logging.warning(f"图片链接GET请求也失败了: {url} - {e}")

            # 不使用全局代理重试，直接返回失败
            return False


def extract_audio_codec_from_mediainfo(mediainfo_text: str) -> str:
    """
    从 MediaInfo 文本中提取第一个音频流的格式。

    :param mediainfo_text: 完整的 MediaInfo 报告字符串。
    :return: 音频格式字符串 (例如 "DTS", "AC-3", "FLAC")，如果找不到则返回空字符串。
    """
    if not mediainfo_text:
        return ""

    # 查找第一个 Audio 部分 (支持 "Audio" 和 "Audio #1")
    audio_section_match = re.search(r"Audio(?: #1)?[\s\S]*?(?=\n\n|\Z)",
                                    mediainfo_text)
    if not audio_section_match:
        logging.warning("在MediaInfo中未找到 'Audio' 部分。")
        return ""

    audio_section = audio_section_match.group(0)

    # 在 Audio 部分查找 Format
    format_match = re.search(r"Format\s*:\s*(.+)", audio_section)
    if format_match:
        audio_format = format_match.group(1).strip()
        logging.info(f"从MediaInfo的'Audio'部分提取到格式: {audio_format}")
        return audio_format

    logging.warning("在MediaInfo的'Audio'部分未找到 'Format' 信息。")
    return ""


def _get_smart_poster_url(original_url: str) -> str:
    """
    智能海报URL获取和验证，并自动转存到pixhost
    参考油猴插件逻辑：
    1. 优先尝试豆瓣官方高清图（多域名轮询 img1-img9）
    2. 尝试两种清晰度路径（l_ratio_poster 高清，m_ratio_poster 中清）
    3. 如果豆瓣全失败，尝试第三方托管（dou.img.lithub.cc）
    4. 验证成功后自动转存到pixhost
    
    :param original_url: 原始海报URL
    :return: pixhost直链URL，失败返回空字符串
    """
    if not original_url:
        return ""

    print(f"[*] 开始验证海报链接...")
    print(f"[*] 检测到非pixhost图片，执行智能海报获取...")
    print(f"开始智能海报URL验证: {original_url}")

    # 检查是否为豆瓣图片
    douban_match = re.search(r'https?://img(\d+)\.doubanio\.com.*?/(p\d+)',
                             original_url)

    if douban_match:
        original_domain_num = douban_match.group(1)
        image_id = douban_match.group(2)

        print(f"检测到豆瓣图片: 域名img{original_domain_num}, 图片ID={image_id}")

        # 生成候选URL列表
        candidates = []

        # 优先原始域名
        domain_numbers = [original_domain_num]
        # 添加其他域名1-9
        for i in range(1, 10):
            if str(i) != original_domain_num:
                domain_numbers.append(str(i))

        # 路径优先级：先高清，后中清
        paths = [
            'view/photo/l_ratio_poster/public',  # 高清
            'view/photo/m_ratio_poster/public'  # 中清
        ]

        # 生成候选URL矩阵
        for domain_num in domain_numbers:
            for path in paths:
                candidate_url = f"https://img{domain_num}.doubanio.com/{path}/{image_id}.jpg"
                candidates.append(candidate_url)

        print(f"生成 {len(candidates)} 个候选URL")

        # 依次验证候选URL
        for i, candidate_url in enumerate(candidates):
            domain_info = re.search(r'img(\d+)\.doubanio\.com', candidate_url)
            path_info = '高清' if 'l_ratio_poster' in candidate_url else '中清'
            domain_num = domain_info.group(1) if domain_info else '?'

            print(
                f"测试 [{i+1}/{len(candidates)}] img{domain_num} ({path_info}): {candidate_url}"
            )

            if _validate_image_url(candidate_url):
                print(f"✓ 验证成功！使用 img{domain_num} 域名")
                print(f"[*] 智能海报获取成功: {candidate_url}")
                
                # 转存到pixhost
                pixhost_url = _transfer_poster_to_pixhost(candidate_url)
                if pixhost_url:
                    return pixhost_url
                else:
                    print("[!] pixhost转存失败，使用原始验证URL")
                    return candidate_url
            else:
                print(f"✗ img{domain_num} 验证失败")

        # 豆瓣全部失败，尝试第三方托管
        print("豆瓣官方图片全部失败，尝试第三方托管...")

        # 从原始URL中提取豆瓣ID
        douban_id_match = re.search(r'/subject/(\d+)', original_url)
        if not douban_id_match:
            # 尝试从图片ID推测（这通常不可行，但作为备选）
            print("无法提取豆瓣ID，跳过第三方托管")
        else:
            douban_id = douban_id_match.group(1)
            third_party_url = f"https://dou.img.lithub.cc/movie/{douban_id}.jpg"
            print(f"测试第三方URL: {third_party_url}")

            if _validate_image_url(third_party_url):
                print("✓ 第三方URL验证成功")
                print(f"[*] 智能海报获取成功: {third_party_url}")
                
                # 转存到pixhost
                pixhost_url = _transfer_poster_to_pixhost(third_party_url)
                if pixhost_url:
                    return pixhost_url
                else:
                    print("[!] pixhost转存失败，使用原始验证URL")
                    return third_party_url
            else:
                print("✗ 第三方URL验证失败")

    else:
        # 非豆瓣图片，直接验证原始URL
        print("非豆瓣图片，直接验证原始URL")
        if _validate_image_url(original_url):
            print("✓ 原始URL验证成功")
            print(f"[*] 智能海报获取成功: {original_url}")
            
            # 转存到pixhost
            pixhost_url = _transfer_poster_to_pixhost(original_url)
            if pixhost_url:
                return pixhost_url
            else:
                print("[!] pixhost转存失败，使用原始验证URL")
                return original_url
        else:
            print("✗ 原始URL验证失败")

    print("所有URL验证都失败")
    return ""


def _validate_image_url(url: str) -> bool:
    """
    验证图片URL是否有效
    使用HEAD请求验证URL是否可访问且返回有效图片
    
    :param url: 图片URL
    :return: URL有效返回True，否则返回False
    """
    if not url:
        return False

    try:
        headers = {
            'User-Agent':
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': 'https://movie.douban.com/'
        }

        response = requests.head(url,
                                 headers=headers,
                                 timeout=10,
                                 allow_redirects=True)

        if response.status_code == 200:
            # 检查Content-Type
            content_type = response.headers.get('Content-Type', '').lower()
            if 'image/' in content_type:
                # 检查Content-Length（至少大于1KB）
                content_length = response.headers.get('Content-Length')
                if content_length:
                    file_size = int(content_length)
                    if file_size > 1024:
                        return True
                    else:
                        print(f"   文件太小: {file_size} bytes")
                        return False
                else:
                    # 如果没有Content-Length，认为有效
                    return True
            else:
                print(f"   无效的Content-Type: {content_type}")
                return False
        else:
            print(f"   HTTP状态码: {response.status_code}")
            return False

    except Exception as e:
        print(f"   验证异常: {type(e).__name__}")
        return False


def _transfer_poster_to_pixhost(poster_url: str) -> str:
    """
    将海报图片转存到pixhost
    
    :param poster_url: 海报图片URL
    :return: pixhost直链URL，失败返回空字符串
    """
    if not poster_url:
        return ""

    print(f"开始转存海报到pixhost: {poster_url}")

    try:
        # 1. 下载图片到临时文件
        headers = {
            'User-Agent':
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': 'https://movie.douban.com/'
        }

        response = requests.get(poster_url, headers=headers, timeout=30)
        response.raise_for_status()

        # 检查文件大小
        if len(response.content) == 0:
            print("   下载的图片文件为空")
            return ""

        if len(response.content) > 10 * 1024 * 1024:
            print("   图片文件过大 (>10MB)")
            return ""

        print(f"   图片下载成功，大小: {len(response.content)} bytes")

        # 2. 保存到临时文件
        temp_file = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as f:
                f.write(response.content)
                temp_file = f.name

            print(f"   临时文件已保存: {temp_file}")

            # 3. 上传到pixhost
            api_url = 'https://api.pixhost.to/images'
            params = {'content_type': 0, 'max_th_size': 420}
            upload_headers = {
                'User-Agent':
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json'
            }

            with open(temp_file, 'rb') as f:
                files = {'img': ('poster.jpg', f, 'image/jpeg')}
                upload_response = requests.post(api_url,
                                                data=params,
                                                files=files,
                                                headers=upload_headers,
                                                timeout=30)

            if upload_response.status_code == 200:
                data = upload_response.json()
                show_url = data.get('show_url')

                if not show_url:
                    print("   API未返回有效URL")
                    return ""

                # 转换为直链URL
                direct_url = _convert_pixhost_url_to_direct(show_url)

                if direct_url:
                    print(f"   上传成功！直链: {direct_url}")
                    return direct_url
                else:
                    print("   URL转换失败")
                    return ""
            else:
                print(f"   上传失败，状态码: {upload_response.status_code}")
                return ""

        finally:
            # 清理临时文件
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                    print(f"   临时文件已清理: {temp_file}")
                except:
                    pass

    except Exception as e:
        print(f"   转存失败: {type(e).__name__} - {e}")
        return ""


def _convert_pixhost_url_to_direct(show_url: str) -> str:
    """
    将pixhost的show URL转换为直链URL
    参考油猴插件的convertToDirectUrl函数
    
    :param show_url: pixhost show URL
    :return: 直链URL，失败返回空字符串
    """
    if not show_url:
        return ""

    try:
        # 方案1: 直接替换域名和路径
        direct_url = show_url.replace(
            'https://pixhost.to/show/',
            'https://img1.pixhost.to/images/').replace(
                'https://pixhost.to/th/', 'https://img1.pixhost.to/images/')

        # 移除缩略图后缀（如 _cover.jpg -> .jpg）
        direct_url = re.sub(r'_..\.jpg$', '.jpg', direct_url)

        # 方案2: 如果方案1失败，使用正则提取重建URL
        if not direct_url.startswith('https://img1.pixhost.to/images/'):
            match = re.search(r'(\d+)/([^/]+\.(jpg|png|gif))', show_url)
            if match:
                direct_url = f"https://img1.pixhost.to/images/{match.group(1)}/{match.group(2)}"

        # 最终验证
        if re.match(
                r'^https://img1\.pixhost\.to/images/\d+/[^/]+\.(jpg|png|gif)$',
                direct_url):
            return direct_url
        else:
            print(f"   URL格式验证失败: {direct_url}")
            return ""

    except Exception as e:
        print(f"   URL转换异常: {e}")
        return ""
