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

    # 读取代理配置
    config = config_manager.get()
    proxy_mode = config.get("cross_seed", {}).get("pixhost_proxy_mode",
                                                  "retry")
    global_proxy = config.get("network", {}).get("proxy_url")

    # 根据代理模式决定上传策略
    if proxy_mode == "always" and global_proxy:
        print(f"代理模式设置为总是使用代理，使用代理: {global_proxy}")
        return _upload_to_pixhost_with_proxy(image_path, api_url, params,
                                             headers, global_proxy)
    elif proxy_mode == "never":
        print("代理模式设置为不使用代理，直接上传")
        return _upload_to_pixhost_direct(image_path, api_url, params, headers)
    else:
        # 默认模式：失败时重试或没有配置代理时直接上传
        print("使用默认上传策略：先尝试直接上传")
        result = _upload_to_pixhost_direct(image_path, api_url, params,
                                           headers)

        # 如果直接上传失败且配置了代理，则尝试代理上传
        if not result and global_proxy and proxy_mode == "retry":
            print("直接上传失败，尝试使用代理上传...")
            result = _upload_to_pixhost_with_proxy(image_path, api_url, params,
                                                   headers, global_proxy)

        return result


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
                                     timeout=60)

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


def _find_target_video_file(path: str) -> str | None:
    """
    根据路径智能查找目标视频文件。
    - 如果是电影目录，返回最大的视频文件。
    - 如果是剧集目录，返回按名称排序的第一个视频文件。

    :param path: 要搜索的目录或文件路径。
    :return: 目标视频文件的完整路径，如果找不到则返回 None。
    """
    print(f"开始在路径 '{path}' 中查找目标视频文件...")
    VIDEO_EXTENSIONS = {
        ".mkv", ".mp4", ".ts", ".avi", ".wmv", ".mov", ".flv", ".m2ts"
    }

    if not os.path.exists(path):
        print(f"错误：提供的路径不存在: {path}")
        return None

    # 如果提供的路径本身就是一个视频文件，直接返回
    if os.path.isfile(path) and os.path.splitext(
            path)[1].lower() in VIDEO_EXTENSIONS:
        print(f"路径直接指向一个视频文件，将使用: {path}")
        return path

    if not os.path.isdir(path):
        print(f"错误：路径不是一个有效的目录或视频文件: {path}")
        return None

    video_files = []
    for root, _, files in os.walk(path):
        for file in files:
            if os.path.splitext(file)[1].lower() in VIDEO_EXTENSIONS:
                video_files.append(os.path.join(root, file))

    if not video_files:
        print(f"在目录 '{path}' 中未找到任何视频文件。")
        return None

    # --- 智能判断是剧集还是电影 ---
    # 匹配 S01E01, s01e01, season 1 episode 1 等格式
    series_pattern = re.compile(
        r'[._\s-](S\d{1,2}E\d{1,3}|Season[._\s-]?\d{1,2}|E\d{1,3})[._\s-]',
        re.IGNORECASE)
    is_series = any(series_pattern.search(f) for f in video_files)

    if is_series:
        print("检测到剧集命名格式，将选择第一集。")
        # 按文件名排序，通常第一集会在最前面
        video_files.sort()
        target_file = video_files[0]
        print(f"已选择剧集文件: {target_file}")
        return target_file
    else:
        print("未检测到剧集格式，将按电影处理（选择最大文件）。")
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
            return largest_file
        else:
            print("无法确定最大的文件。")
            return None


# --- [修改] 主函数，整合了新的文件查找逻辑 ---
def upload_data_mediaInfo(mediaInfo: str,
                          save_path: str,
                          content_name: str = None):
    """
    检查传入的文本是有效的 MediaInfo 还是 BDInfo 格式。
    如果没有 MediaInfo 或 BDInfo 则尝试从 save_path 查找视频文件提取 MediaInfo。
    【新增】支持传入 content_name 来构建更精确的搜索路径。
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
        print(f"检测到标准 MediaInfo 格式，验证通过。(匹配关键字数: {mediainfo_matches})")
        return mediaInfo
    elif is_bdinfo:
        print(
            f"检测到 BDInfo 格式，验证通过。(必要关键字: {bdinfo_required_matches}/{len(bdinfo_required_keywords)}, 可选关键字: {bdinfo_optional_matches})"
        )
        return mediaInfo
    else:
        print("提供的文本不是有效的 MediaInfo/BDInfo，将尝试从本地文件提取。")
        # ... (打印匹配信息的代码不变) ...

        if not save_path:
            print("错误：未提供 save_path，无法从文件提取 MediaInfo。")
            return mediaInfo

        # --- 【核心修改】仿照截图逻辑，构建精确的搜索路径 ---
        path_to_search = save_path  # 默认使用基础路径
        if content_name:
            # 如果提供了具体的内容名称（主标题），则拼接成一个更精确的路径
            path_to_search = os.path.join(save_path, content_name)
            print(f"已提供 content_name，将在精确路径中搜索: '{path_to_search}'")

        # 使用新构建的路径来查找视频文件
        target_video_file = _find_target_video_file(path_to_search)

        if not target_video_file:
            print("未能在指定路径中找到合适的视频文件，提取失败。")
            return mediaInfo

        try:
            print(f"准备使用 MediaInfo 工具从 '{target_video_file}' 提取...")
            media_info_parsed = MediaInfo.parse(target_video_file,
                                                output="text",
                                                full=False)
            print("从文件重新提取 MediaInfo 成功。")
            return str(media_info_parsed)
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

    chinese_junk_match = re.search(r"([\u4e00-\u9fa5].*)$", original_title_str)
    if chinese_junk_match:
        unrecognized_parts.append(chinese_junk_match.group(1).strip())
        title = original_title_str[:chinese_junk_match.start()].strip()
    else:
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

    # 检查特殊制作组
    special_groups = ["mUHD-FRDS", "MNHD-FRDS", "DMG&VCB-Studio", "VCB-Studio"]
    found_special_group = False
    for group in special_groups:
        if title.endswith(f" {group}") or title.endswith(f"-{group}"):
            release_group = group
            main_part = title[:-len(group) - 1].strip()
            found_special_group = True
            break

    # 如果不是特殊制作组，使用通用模式匹配
    if not found_special_group:
        general_regex = re.compile(
            r"^(?P<main_part>.+?)(?:-(?P<internal_tag>[A-Za-z0-9@²³⁴⁵⁶⁷⁸⁹]+))?-(?P<release_group>[A-Za-z0-9@²³⁴⁵⁶⁷⁸⁹]+)$",
            re.VERBOSE | re.IGNORECASE,
        )
        match = general_regex.match(title)
        if match:
            main_part = match.group("main_part").strip()
            release_group_name = match.group("release_group")
            internal_tag = match.group("internal_tag")
            release_group = (f"{internal_tag}-{release_group_name}"
                             if internal_tag and "@" in internal_tag else
                             (f"{release_group_name} ({internal_tag})"
                              if internal_tag else release_group_name))
        else:
            # 检查是否以-NOGROUP结尾
            if title.upper().endswith("-NOGROUP"):
                release_group = "NOGROUP"
                main_part = title[:-8].strip()
            else:
                release_group = "N/A (无发布组)"

    # 3. 季集、年份提取
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

    # 4. 技术标签提取（排除已识别的制作组名称）
    tech_patterns_definitions = {
        "medium":
        r"UHDTV|UHD\s*Blu-?ray|Blu-ray|BluRay|WEB-DL|WEBrip|TVrip|DVDRip|HDTV",
        "audio":
        r"DTS-HD(?:\s*MA)?(?:\s*\d\.\d)?|(?:Dolby\s*)?TrueHD(?:\s*Atmos)?(?:\s*\d\.\d)?|Atmos(?:\s*TrueHD)?(?:\s*\d\.\d)?|DTS(?:\s*\d\.\d)?|DDP(?:\s*\d\.\d)?|DD\+(?:\s*\d\.\d)?|DD(?:\s*\d\.\d)?|AC3(?:\s*\d\.\d)?|FLAC(?:\s*\d\.\d)?|AAC(?:\s*\d\.\d)?|LPCM(?:\s*\d\.\d)?|AV3A\s*\d\.\d|\d+\s*Audios?|MP2|DUAL",
        "hdr_format":
        r"Dolby Vision|DoVi|HDR10\+|HDRVivid|HDR10|HLG|HDR|SDR|DV|Vivid",
        "resolution": r"\d{3,4}[pi]|4K",
        "video_codec":
        r"HEVC|AVC|x265|H\s*\.?\s*265|x264|H\s*\.?\s*264|VC-1|AV1|MPEG-2",
        "source_platform":
        r"Apple TV\+|ViuTV|MyTVSuper|AMZN|Netflix|NF|DSNP|MAX|ATVP|iTunes|friDay|USA|EUR|JPN|CEE|FRA|LINETV|EDR|PCOK|Hami|GBR|NowPlayer|CR|SEEZN|GER|CHN|MA|Viu|Baha|KKTV|IQ|HKG|ITA|ESP",
        "bit_depth": r"\b(?:8|10)bit\b",
        "framerate": r"\d{2,3}fps",
        "completion_status": r"Complete|COMPLETE",
        "video_format": r"3D|HSBS",
        "release_version": r"REMASTERED|REPACK|RERIP|PROPER|REPOST",
        "quality_modifier": r"MAXPLUS|HQ|EXTENDED|REMUX|UNRATED|EE|MiniBD",
    }
    priority_order = [
        "completion_status",
        "release_version",
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
        all_found_tags.extend(raw_values)
        processed_values = (
            [re.sub(r"(DD)\+", r"\1+", val, flags=re.I)
             for val in raw_values] if key == "audio" else raw_values)
        if key == "audio":
            processed_values = [
                re.sub(r"((?:FLAC|DDP|AV3A|AAC|LPCM|AC3|DD))(\d(?:\.\d)?)",
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

    cleaned_tech_zone = tech_zone
    for tag in sorted(all_found_tags, key=len, reverse=True):
        pattern_to_remove = r"\b" + re.escape(tag) + r"(?!\w)"
        cleaned_tech_zone = re.sub(pattern_to_remove,
                                   " ",
                                   cleaned_tech_zone,
                                   flags=re.IGNORECASE)

    remains = re.split(r"[\s\.]+", cleaned_tech_zone)
    unrecognized_parts.extend([part for part in remains if part])
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
                sorted_audio = sorted(params[key],
                                      key=lambda s:
                                      (s.upper().endswith("AUDIOS"), -len(s)))
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
    [JPEG优化顺序版] 使用 mpv 从视频文件中截取多张图片，并上传到图床。
    - 按顺序一张一张处理，移除了并发逻辑以简化流程和调试。
    - 先用 mpv 截取高质量 PNG 作为源，再转换为体积更小的 JPEG 上传。
    - 采用先进的智能时间点分析，优先截取带字幕的画面。
    """
    if Image is None:
        print("错误：Pillow 库未安装，无法执行截图任务。")
        return ""

    print("开始执行截图和上传任务 (引擎: mpv, 输出格式: JPEG, 模式: 顺序执行)...")
    config = config_manager.get()
    hoster = config.get("cross_seed", {}).get("image_hoster", "pixhost")
    num_screenshots = 5
    print(f"已选择图床服务: {hoster}, 截图数量: {num_screenshots}")

    if torrent_name:
        full_video_path = os.path.join(save_path, torrent_name)
        print(f"使用完整视频路径: {full_video_path}")
    else:
        full_video_path = save_path
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
                timeout=300)  # 延长超时时间
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
    target_video_file = _find_target_video_file(full_video_path)
    if not target_video_file:
        print("错误：在指定路径中未找到视频文件。")
        return ""

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

    # --- [核心修改] 使用简单的 for 循环代替并发处理 ---
    for i, screenshot_time in enumerate(screenshot_points):
        print(f"\n--- 开始处理第 {i+1}/{len(screenshot_points)} 张截图 ---")

        safe_name = re.sub(r'[\\/*?:"<>|\'\s\.]+', '_',
                           source_info.get('main_title', f'screenshot_{i+1}'))

        timestamp = f"{time.time():.0f}"
        intermediate_png_path = os.path.join(
            TEMP_DIR, f"{safe_name}_{i+1}_{timestamp}_temp.png")
        final_jpeg_path = os.path.join(TEMP_DIR,
                                       f"{safe_name}_{i+1}_{timestamp}.jpg")

        temp_files_to_cleanup.extend([intermediate_png_path, final_jpeg_path])

        # 步骤1: 使用mpv截取高质量的PNG作为源文件
        cmd_screenshot = [
            "mpv", "--no-audio", f"--start={screenshot_time:.2f}",
            "--frames=1", f"--o={intermediate_png_path}", target_video_file
        ]

        try:
            subprocess.run(cmd_screenshot,
                           check=True,
                           capture_output=True,
                           timeout=45)

            if not os.path.exists(intermediate_png_path):
                print(f"❌ 错误: mpv 命令执行成功，但未找到输出文件 {intermediate_png_path}")
                continue  # 继续处理下一张图片

            print(
                f"   -> 中间PNG图 {os.path.basename(intermediate_png_path)} 生成成功。"
            )

            # 步骤2: 使用Pillow将PNG转换为JPEG
            try:
                with Image.open(intermediate_png_path) as img:
                    rgb_img = img.convert('RGB')
                    rgb_img.save(final_jpeg_path, 'jpeg', quality=85)
                print(
                    f"   -> JPEG压缩成功 (质量: 85) -> {os.path.basename(final_jpeg_path)}"
                )
            except Exception as e:
                print(f"   ❌ 错误: 图片从PNG转换为JPEG失败: {e}")
                continue  # 转换失败，继续处理下一张图片

            # 步骤3: 上传压缩后的JPEG文件
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
                        break  # 上传成功，跳出重试循环
                    else:
                        # 如果上传函数返回None但没有抛出异常，等待后重试
                        time.sleep(2)
                except Exception as e:
                    print(f"   -> 上传尝试 {attempt+1} 出现异常: {e}")
                    time.sleep(2)  # 发生异常后也等待重试

            if not image_url:
                print(f"⚠️  第 {i+1} 张图片经过 {max_retries} 次尝试后仍然上传失败。")

        except subprocess.CalledProcessError as e:
            error_output = e.stderr.decode('utf-8', errors='ignore')
            print(f"❌ 错误: mpv 截图失败。命令: '{' '.join(cmd_screenshot)}'")
            print(f"   -> Stderr: {error_output}")
            continue  # mpv失败，继续处理下一张
        except subprocess.TimeoutExpired:
            print(f"❌ 错误: mpv 截图超时 (超过45秒)。")
            continue  # 超时，继续处理下一张

    # --- [核心修改结束] ---

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
    # 对URL进行排序，确保每次生成的BBCode顺序一致
    for url in sorted(uploaded_urls):
        if "pixhost.to/show/" in url:
            # 转换为直接的图片链接
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
    通过PT-Gen API获取电影信息的完整内容，包括海报、简介和IMDb链接。
    支持从豆瓣链接或IMDb链接获取信息。
    返回: (状态, 海报, 简介, IMDb链接)
    """
    pt_gen_api_url = 'https://api.iyuu.cn/App.Movie.Ptgen'

    # 确定要使用的资源URL（豆瓣优先）
    resource_url = douban_link or imdb_link

    if not resource_url:
        return False, "", "", "未提供豆瓣或IMDb链接。"

    try:
        response = requests.get(f'{pt_gen_api_url}?url={resource_url}',
                                timeout=30)
        response.raise_for_status()

        data = response.json()

        format_data = data.get('format') or data.get('data', {}).get(
            'format', '')

        extracted_imdb_link = ""
        poster = ""
        description = ""

        if format_data:
            # 提取IMDb链接
            imdb_match = re.search(
                r'◎IMDb链接\s*(https?://www\.imdb\.com/title/tt\d+/)',
                format_data)
            if imdb_match:
                extracted_imdb_link = imdb_match.group(1)

            # 提取海报图片
            img_match = re.search(r'(\[img\].*?\[/img\])', format_data)
            if img_match:
                poster = img_match.group(1)

            # 提取简介内容（去除海报部分）
            description = re.sub(r'\[img\].*?\[/img\]', '',
                                 format_data).strip()
            # 清理多余的空行
            description = re.sub(r'\n{3,}', '\n\n', description)

            return True, poster, description, extracted_imdb_link
        else:
            return False, "", "", "PT-Gen接口未返回有效的简介内容。"

    except Exception as e:
        error_message = f"请求PT-Gen接口时发生错误: {e}"
        print(error_message)
        return False, "", "", error_message


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
    cursor.execute(
        "SELECT nickname, base_url, cookie, proxy, speed_limit FROM sites")
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

        # Add proxy support for downloading torrent
        proxies = None
        if site_info.get("proxy"):
            try:
                conf = (config_manager.get() or {})
                # 优先使用转种设置中的代理地址，其次兼容旧的 network.proxy_url
                proxy_url = (conf.get("cross_seed", {})
                             or {}).get("proxy_url") or (conf.get(
                                 "network", {}) or {}).get("proxy_url")
                if proxy_url:
                    proxies = {"http": proxy_url, "https": proxy_url}
                    logging.info(f"使用代理下载种子: {proxy_url}")
            except Exception as e:
                logging.warning(f"代理设置失败: {e}")
                proxies = None

        # Add retry logic for network requests
        max_retries = 3
        for attempt in range(max_retries):
            try:
                details_response = scraper.get(detail_page_url,
                                               headers=common_headers,
                                               timeout=60,
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
        torrent_id_match = re.search(r"id=(\d+)", detail_page_url)
        if not torrent_id_match: raise ValueError("无法从详情页URL中提取种子ID。")
        torrent_id = torrent_id_match.group(1)

        download_link_tag = soup.select_one(
            f'a.index[href^="download.php?id={torrent_id}"]')
        if not download_link_tag: raise RuntimeError("在详情页HTML中未能找到下载链接！")

        download_url_part = download_link_tag['href']
        full_download_url = f"{ensure_scheme(site_info['base_url'])}/{download_url_part}"

        common_headers["Referer"] = detail_page_url
        # Add retry logic for torrent download
        for attempt in range(max_retries):
            try:
                torrent_response = scraper.get(full_download_url,
                                               headers=common_headers,
                                               timeout=60,
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

                # 如果站点设置了速度限制，则添加速度限制参数
                # 数据库中存储的是MB/s，需要转换为bytes/s传递给下载器API
                if site_info and site_info.get('speed_limit', 0) > 0:
                    speed_limit = int(
                        site_info['speed_limit']) * 1024 * 1024  # 转换为 bytes/s
                    tr_params['uploadLimit'] = speed_limit
                    tr_params['uploadLimited'] = True
                    logging.info(
                        f"为站点 '{site_info['nickname']}' 设置上传速度限制: {site_info['speed_limit']} MB/s"
                    )

                result = client.add_torrent(**tr_params)
                logging.info(
                    f"已将种子添加到 Transmission '{client_name}': ID={result.id}")

            return True, f"成功将种子添加到下载器 '{client_name}'。"

        except Exception as e:
            logging.warning(f"第 {attempt + 1} 次尝试添加种子到下载器失败: {e}")

            # 如果不是最后一次尝试，等待一段时间后重试
            if attempt < max_retries - 1:
                import time
                wait_time = 2**attempt  # 指数退避
                logging.info(f"等待 {wait_time} 秒后进行第 {attempt + 2} 次尝试...")
                time.sleep(wait_time)
            else:
                msg = f"添加到下载器 '{downloader_config['name']}' 时失败: {e}"
                logging.error(msg, exc_info=True)
                return False, msg


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
        # 字幕标签
        '中字': ['中字', 'chinese', 'chs', 'cht', '简', '繁'],
        # HDR 格式标签
        'Dolby Vision': ['dolby vision', '杜比视界'],
        'HDR10+': ['hdr10+'],
        'HDR10': ['hdr10'],
        'HDR': ['hdr'],  # 作为通用 HDR 的备用选项
        'HDRVivid': ['hdr vivid'],
    }

    # 定义检查范围，减少不必要的扫描
    # is_audio_section/is_text_section 用于限定语言和字幕的检查范围
    is_audio_section = False
    is_text_section = False
    audio_section_lines = []

    for line in lines:
        line_stripped = line.strip()

        # 判定当前是否处于特定信息块中
        if 'audio' in line_stripped.lower() and '#' in line_stripped:
            is_audio_section = True
            is_text_section = False
            audio_section_lines = [line_stripped]  # 开始新的音频块
            continue
        if 'text' in line_stripped.lower() and '#' in line_stripped:
            is_text_section = True
            is_audio_section = False
            continue
        if 'video' in line_stripped.lower() and '#' in line_stripped:
            is_audio_section = False
            is_text_section = False
            # 处理音频块中的国语检测
            if audio_section_lines:
                if _check_mandarin_in_audio_section(audio_section_lines):
                    found_tags.add('tag.国语')
                audio_section_lines = []  # 清空音频块
            continue

        # 收集音频块的行
        if is_audio_section:
            audio_section_lines.append(line_stripped)

        # 检查字幕标签 (仅在 Text 块中)
        if is_text_section:
            line_lower = line_stripped.lower()
            if '中字' in tag_keywords_map and any(
                    kw in line_lower for kw in tag_keywords_map['中字']):
                found_tags.add('tag.中字')

        # 检查 HDR 格式标签 (全局检查)
        line_lower = line_stripped.lower()
        if 'dolby vision' in tag_keywords_map and any(
                kw in line_lower for kw in tag_keywords_map['Dolby Vision']):
            found_tags.add('tag.Dolby Vision')
        if 'hdr10+' in tag_keywords_map and any(
                kw in line_lower for kw in tag_keywords_map['HDR10+']):
            found_tags.add('tag.HDR10+')
        # HDR10 要放在 HDR 之前检查，以获得更精确匹配
        if 'hdr10' in tag_keywords_map and any(
                kw in line_lower for kw in tag_keywords_map['HDR10']):
            found_tags.add('tag.HDR10')
        elif 'hdr' in tag_keywords_map and any(
                kw in line_lower for kw in tag_keywords_map['HDR']):
            # 避免重复添加，如果已有更具体的HDR格式，则不添加通用的'HDR'
            if not any(hdr_tag in found_tags for hdr_tag in
                       ['tag.Dolby Vision', 'tag.HDR10+', 'tag.HDR10']):
                found_tags.add('tag.HDR')
        if 'hdrvivid' in tag_keywords_map and any(
                kw in line_lower for kw in tag_keywords_map['HDRVivid']):
            # 注意：站点可能没有 HDRVivid 标签，但我们先提取出来
            found_tags.add('tag.HDRVivid')

    # 处理最后一个音频块（如果文件末尾没有video块）
    if audio_section_lines:
        if _check_mandarin_in_audio_section(audio_section_lines):
            found_tags.add('tag.国语')

    # 为所有标签添加 tag. 前缀
    prefixed_tags = set()
    for tag in found_tags:
        if not tag.startswith('tag.'):
            prefixed_tags.add(f'tag.{tag}')
        else:
            prefixed_tags.add(tag)

    print(f"从 MediaInfo 中提取到的标签: {list(prefixed_tags)}")
    return list(prefixed_tags)


def _check_mandarin_in_audio_section(audio_lines):
    """
    检查音频块中是否包含国语相关标识。
    
    :param audio_lines: 音频块的所有行
    :return: 如果检测到国语返回True，否则返回False
    """
    for line in audio_lines:
        # 检查 Title: 中文 或 Language: Chinese
        if 'title:' in line.lower() and '中文' in line:
            return True
        if 'language:' in line.lower() and ('chinese' in line.lower()
                                            or 'mandarin' in line.lower()):
            return True
        # 检查其他可能的国语标识
        if 'mandarin' in line.lower():
            return True

    return False


def extract_origin_from_description(description_text: str) -> str:
    """
    从简介详情中提取产地信息。

    :param description_text: 简介详情文本
    :return: 产地信息，例如 "日本"、"中国" 等
    """
    if not description_text:
        return ""

    # 使用正则表达式匹配 "◎产　　地　日本" 这种格式
    # 支持多种变体：◎产地、◎产　　地、◎国　　家等
    patterns = [
        r"◎\s*产\s*地\s*(.+?)(?:\s|$)",  # 匹配 ◎产地 日本
        r"◎\s*国\s*家\s*(.+?)(?:\s|$)",  # 匹配 ◎国家 日本
        r"◎\s*地\s*区\s*(.+?)(?:\s|$)",  # 匹配 ◎地区 日本
        r"制片国家/地区[:\s]+(.+?)(?:\s|$)",  # 匹配 制片国家/地区: 日本
        r"制片国家[:\s]+(.+?)(?:\s|$)",  # 匹配 制片国家: 日本
        r"国家[:\s]+(.+?)(?:\s|$)",  # 匹配 国家: 日本
        r"产地[:\s]+(.+?)(?:\s|$)",  # 匹配 产地: 日本
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
        if len(w_groups) >= 2 and w_groups[1]:
            width = int(f"{w_groups[0]}{w_groups[1]}")
        else:
            width = int(w_groups[0]) if w_groups[0] else None

    if height_match:
        # 处理带空格的数字格式，如 "1 080" -> "1080"
        h_groups = height_match.groups()
        if len(h_groups) >= 2 and h_groups[1]:
            height = int(f"{h_groups[0]}{h_groups[1]}")
        else:
            height = int(h_groups[0]) if h_groups[0] else None

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
                                     headers=headers)

            if response.status_code == 200:
                data = response.json()
                show_url = data.get('show_url')
                print(f"直接上传成功！图片链接: {show_url}")
                return show_url
            else:
                print(f"直接上传失败，状态码: {response.status_code}")
                print(f"错误信息: {response.text}")
                return None
    except FileNotFoundError:
        print(f"错误: 找不到指定的图片文件: {image_path}")
        return None
    except Exception as e:
        print(f"直接上传过程中发生未知错误: {e}")
        return None


def _upload_to_pixhost_with_proxy(image_path: str, api_url: str, params: dict,
                                  headers: dict, proxy_url: str):
    """通过代理上传图片到Pixhost"""
    if not proxy_url:
        print("未配置全局代理，跳过代理上传")
        return None

    print(f"使用代理: {proxy_url}")
    print(f"目标URL: {api_url}")
    print(f"上传文件: {image_path}")

    try:
        # 使用标准HTTP代理方式
        with open(image_path, 'rb') as f:
            files = {'img': f}

            # 设置代理
            proxies = {'http': proxy_url, 'https': proxy_url}

            print(f"代理配置: {proxies}")

            response = requests.post(api_url,
                                     data=params,
                                     files=files,
                                     headers=headers,
                                     proxies=proxies,
                                     timeout=30)

            print(f"代理方式响应状态码: {response.status_code}")
            if response.status_code == 200:
                try:
                    data = response.json()
                    show_url = data.get('show_url')
                    if show_url:
                        print(f"代理上传成功！图片链接: {show_url}")
                        return show_url
                    else:
                        print(f"代理上传成功但无法解析返回的URL: {response.text}")
                        return None
                except Exception as json_error:
                    print(f"解析JSON响应时出错: {json_error}")
                    if response.text and 'pixhost' in response.text:
                        print(f"代理上传成功！图片链接: {response.text}")
                        return response.text.strip()
                    else:
                        print(f"代理上传成功但返回了无效响应: {response.text}")
                        return None
            else:
                print(f"代理上传失败，状态码: {response.status_code}")
                if response.text:
                    print(f"响应内容: {response.text[:500]}...")  # 显示更多内容用于调试
                return None
    except Exception as e:
        print(f"代理上传过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return None
