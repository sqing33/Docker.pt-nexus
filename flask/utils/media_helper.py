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
from pymediainfo import MediaInfo
import time
import cloudscraper
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from config import TEMP_DIR, config_manager
from qbittorrentapi import Client as qbClient
from transmission_rpc import Client as TrClient
from utils import ensure_scheme


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
                print(f"上传成功！图片链接: {show_url}")
                return show_url
            else:
                print(f"上传失败，状态码: {response.status_code}")
                print(f"错误信息: {response.text}")
                return None
    except FileNotFoundError:
        print(f"错误: 找不到指定的图片文件: {image_path}")
        return None
    except Exception as e:
        print(f"上传过程中发生未知错误: {e}")
        return None


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
def upload_data_mediaInfo(mediaInfo: str, save_path: str):
    """
    检查传入的文本是有效的 MediaInfo 还是 BDInfo 格式。
    如果没有 MediaInfo 或 BDInfo 则尝试从 save_path 查找视频文件提取 MediaInfo。
    """
    print("开始检查 MediaInfo/BDInfo 格式")

    # 1. 标准 MediaInfo 格式的关键字
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

    # 2. BDInfo 格式的关键字
    bdinfo_keywords = [
        "DISC INFO",
        "PLAYLIST REPORT",
        "VIDEO:",
        "AUDIO:",
        "SUBTITLES:",
        "Disc Label",
        "Disc Size",
    ]

    is_standard_mediainfo = all(keyword in mediaInfo
                                for keyword in standard_mediainfo_keywords)
    is_bdinfo = all(keyword in mediaInfo for keyword in bdinfo_keywords)

    if is_standard_mediainfo:
        print("检测到标准 MediaInfo 格式，验证通过。")
        return mediaInfo
    elif is_bdinfo:
        print("检测到 BDInfo 格式，验证通过。")
        return mediaInfo
    else:
        print("提供的文本不是有效的 MediaInfo/BDInfo，将尝试从本地文件提取。")
        if not save_path:
            print("错误：未提供 save_path，无法从文件提取 MediaInfo。")
            return mediaInfo

        target_video_file = _find_target_video_file(save_path)

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
    main_part = ""

    # 2. 发布组解析
    special_groups = ["mUHD-FRDS", "MNHD-FRDS", "DMG&VCB-Studio", "VCB-Studio"]
    found_special_group = False
    for group in special_groups:
        if title.endswith(f" {group}") or title.endswith(f"-{group}"):
            params["release_info"] = group
            main_part = title[:-len(group) - 1].strip()
            found_special_group = True
            break

    if not found_special_group:
        general_regex = re.compile(
            r"^(?P<main_part>.+?)(?:-(?P<internal_tag>[A-Za-z0-9@]+))?-(?P<release_group>[A-Za-z0-9@]+)$",
            re.VERBOSE | re.IGNORECASE,
        )
        match = general_regex.match(title)
        if match:
            main_part = match.group("main_part").strip()
            release_group = match.group("release_group")
            internal_tag = match.group("internal_tag")
            params["release_info"] = (f"{internal_tag}-{release_group}" if
                                      internal_tag and "@" in internal_tag else
                                      (f"{release_group} ({internal_tag})"
                                       if internal_tag else release_group))
        else:
            main_part = title
            if title.upper().endswith("-NOGROUP"):
                params["release_info"] = "NOGROUP"
                main_part = title[:-8].strip()
            else:
                params["release_info"] = "N/A (无发布组)"

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

    # 4. 技术标签提取
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
        "quality_modifier": r"MAXPLUS|HQ|EXTENDED|REMUX|DIY|UNRATED|EE|MiniBD",
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
        filename_base = re.sub(r'(\.original)?\.torrent', '', torrent_filename, flags=re.IGNORECASE)
        filename_candidate = re.sub(r'[\._\[\]\(\)]', ' ', filename_base)

        # 再次遍历所有技术标签定义，以补充信息
        for key in priority_order:
            # 如果主标题中已解析出此参数，则跳过，优先使用主标题的结果
            if key in params and params.get(key):
                continue

            pattern = tech_patterns_definitions[key]
            search_pattern = (re.compile(r"(?<!\w)(" + pattern + r")(?!\w)", re.IGNORECASE)
                              if r"\b" not in pattern else re.compile(pattern, re.IGNORECASE))

            matches = list(search_pattern.finditer(filename_candidate))
            if matches:
                # 提取所有匹配到的值
                raw_values = [m.group(0).strip() if r"\b" in pattern else m.group(1).strip() for m in matches]
                
                # (复制主解析逻辑中的 audio 特殊处理)
                processed_values = ([re.sub(r"(DD)\\+", r"\1+", val, flags=re.I) for val in raw_values]
                                    if key == "audio" else raw_values)
                if key == "audio":
                    processed_values = [re.sub(r"((?:FLAC|DDP|AV3A|AAC|LPCM|AC3|DD))(\d(?:\.\d)?)", r"\1 \2", val, flags=re.I)
                                        for val in processed_values]
                
                # 取独一无二的值并按出现顺序排序
                unique_processed = sorted(list(set(processed_values)), key=lambda x: filename_candidate.find(x.replace(" ", "")))

                if unique_processed:
                    print(f"   [文件名补充] 找到缺失参数 '{key}': {unique_processed}")
                    # 将补充的参数存入 params 字典
                    params[key] = unique_processed[0] if len(unique_processed) == 1 else unique_processed
                    # 将新找到的标签也加入 all_found_tags，以便后续正确计算“无法识别”部分
                    all_found_tags.extend(unique_processed)
    # --- [新增] 结束 ---

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


def upload_data_screenshot(source_info, save_path):
    """
    使用ffmpeg从指定的视频文件中截取多张图片，根据配置上传到指定图床，
    并返回一个包含所有图片BBCode链接的字符串。
    """
    print("开始执行截图和上传任务...")

    # --- [核心修改] 读取图床配置 ---
    config = config_manager.get()
    hoster = config.get("cross_seed", {}).get("image_hoster", "pixhost")
    print(f"已选择图床服务: {hoster}")
    # -----------------------------

    target_video_file = _find_target_video_file(save_path)
    if not target_video_file:
        print("错误：在指定路径中未找到视频文件。")
        return ""

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print("错误：找不到 ffmpeg 或 ffprobe。请确保它们已安装并已添加到系统环境变量 PATH 中。")
        return ""

    try:
        # ... (获取视频时长的代码保持不变) ...
        print("正在获取视频时长...")
        cmd_duration = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", target_video_file
        ]
        result = subprocess.run(cmd_duration,
                                capture_output=True,
                                text=True,
                                check=True)
        duration = float(result.stdout.strip())
        print(f"视频总时长: {duration:.2f} 秒")
    except Exception as e:
        print(f"错误：使用 ffprobe 获取视频时长失败。{e}")
        return ""

    auth_token = None
    if hoster == "agsv":
        auth_token = _get_agsv_auth_token()
        if not auth_token:
            print("❌ 无法获取 末日图床 Token，截图上传任务终止。")
            return ""

    uploaded_urls = []
    screenshot_points = [0.20, 0.35, 0.65]

    try:
        for i, point in enumerate(screenshot_points):
            screenshot_time = duration * point
            base_name = source_info.get('main_title', f'screenshot_{i+1}')
            safe_name = re.sub(r'[\\/*?:"<>|\'\s\.]+', '_', base_name)
            output_filename = os.path.join(
                TEMP_DIR, f"{safe_name}_{i+1}_{time.time()}.jpg")

            print(
                f"正在截取第 {i+1}/{len(screenshot_points)} 张图片 (时间点: {screenshot_time:.2f}s)..."
            )

            cmd_screenshot = [
                "ffmpeg", "-ss",
                str(screenshot_time), "-i", target_video_file, "-vframes", "1",
                "-q:v", "2", "-y", output_filename
            ]

            try:
                subprocess.run(cmd_screenshot, check=True, capture_output=True)

                if os.path.exists(output_filename):
                    print(f"截图 {output_filename} 生成成功，准备上传。")

                    # --- [核心修改] 根据配置选择上传函数，并添加重试机制 ---
                    max_retries = 3
                    image_url = None
                    
                    for attempt in range(max_retries):
                        try:
                            if hoster == "pixhost":
                                image_url = _upload_to_pixhost(output_filename)
                            elif hoster == "agsv":
                                image_url = _upload_to_agsv(output_filename,
                                                            auth_token)
                            else:
                                print(f"警告: 未知的图床 '{hoster}'，将默认使用 pixhost。")
                                image_url = _upload_to_pixhost(output_filename)
                            
                            if image_url:
                                uploaded_urls.append(image_url)
                                print(f"第 {i+1} 张图片上传成功 (尝试 {attempt+1}/{max_retries})")
                                break
                            else:
                                print(f"第 {i+1} 张图片上传失败 (尝试 {attempt+1}/{max_retries})")
                                if attempt < max_retries - 1:
                                    print(f"等待 2 秒后重试...")
                                    time.sleep(2)
                                
                        except Exception as e:
                            print(f"第 {i+1} 张图片上传出现异常 (尝试 {attempt+1}/{max_retries}): {e}")
                            if attempt < max_retries - 1:
                                print(f"等待 2 秒后重试...")
                                time.sleep(2)
                            continue
                    
                    if not image_url:
                        print(f"⚠️  第 {i+1} 张图片经过 {max_retries} 次尝试后仍然上传失败")

                else:
                    print(f"警告：ffmpeg 命令执行成功，但未找到输出文件 {output_filename}")

            except subprocess.CalledProcessError as e:
                print(f"错误：ffmpeg 截图失败。命令返回了非零退出码。")
                print(
                    f"FFMPEG Stderr: {e.stderr.decode('utf-8', errors='ignore')}"
                )

    finally:
        print(f"正在清理临时目录中的截图文件...")
        for item in os.listdir(TEMP_DIR):
            if item.endswith(".jpg"):
                try:
                    os.remove(os.path.join(TEMP_DIR, item))
                except OSError as e:
                    print(f"清理临时文件 {item} 失败: {e}")

    if not uploaded_urls:
        print("任务完成，但没有成功上传任何图片。")
        return ""

    print("正在将 Pixhost 网页链接转换为直接图片链接并生成BBCode...")
    bbcode_links = [
        f"[img]{url.replace('https://pixhost.to/show/', 'https://img1.pixhost.to/images/')}[/img]"
        for url in uploaded_urls
    ]
    screenshots = "\n".join(bbcode_links)

    print("所有截图已成功上传并已格式化为BBCode。")
    print("--- 返回内容 ---")
    print(screenshots)
    print("-----------------")

    return screenshots


def upload_data_poster(douban_link: str, imdb_link: str):
    """
    通过PT-Gen API获取电影信息的海报和IMDb链接。
    """
    pt_gen_api_url = 'https://api.iyuu.cn/App.Movie.Ptgen'

    resource_url = douban_link or imdb_link

    if not resource_url:
        return False, "未提供豆瓣或IMDb链接。", ""

    try:
        response = requests.get(f'{pt_gen_api_url}?url={resource_url}',
                                timeout=30)
        response.raise_for_status()

        data = response.json()

        format_data = data.get('format') or data.get('data', {}).get(
            'format', '')

        extracted_imdb_link = ""
        poster = ""
        
        if format_data:
            # 提取IMDb链接
            imdb_match = re.search(r'◎IMDb链接\s*(https?://www\.imdb\.com/title/tt\d+/)', format_data)
            if imdb_match:
                extracted_imdb_link = imdb_match.group(1)
            
            # 提取海报图片
            img_match = re.search(r'(\[img\].*?\[/img\])', format_data)
            if img_match:
                poster = img_match.group(1)
                return True, poster, extracted_imdb_link
            else:
                return False, "PT-Gen返回的简介中未找到图片标签。", extracted_imdb_link
        else:
            return False, "PT-Gen接口未返回有效的简介内容。", ""

    except Exception as e:
        error_message = f"请求PT-Gen接口时发生错误: {e}"
        print(error_message)
        return False, error_message, ""


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
    cursor.execute("SELECT nickname, base_url, cookie FROM sites")
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

        details_response = scraper.get(detail_page_url,
                                       headers=common_headers,
                                       timeout=60)
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
        torrent_response = scraper.get(full_download_url,
                                       headers=common_headers,
                                       timeout=60)
        torrent_response.raise_for_status()

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

    # 4. 添加到下载器 (核心修改在此！)
    try:
        from core.services import _prepare_api_config

        api_config = _prepare_api_config(downloader_config)
        client_name = downloader_config['name']

        if downloader_config['type'] == 'qbittorrent':
            client = qbClient(**api_config)
            client.auth_log_in()
            result = client.torrents_add(torrent_files=torrent_content,
                                         save_path=save_path,
                                         is_paused=False,
                                         skip_checking=True)
            logging.info(f"已将种子添加到 qBitorrent '{client_name}': {result}")

        elif downloader_config['type'] == 'transmission':
            client = TrClient(**api_config)
            result = client.add_torrent(torrent=torrent_content,
                                        download_dir=save_path,
                                        paused=False)
            logging.info(
                f"已将种子添加到 Transmission '{client_name}': ID={result.id}")

        return True, f"成功将种子添加到下载器 '{client_name}'。"

    except Exception as e:
        msg = f"添加到下载器 '{downloader_config['name']}' 时失败: {e}"
        logging.error(msg, exc_info=True)
        return False, msg
