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
import yaml
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from pymediainfo import MediaInfo
from config import TEMP_DIR, config_manager, GLOBAL_MAPPINGS
from qbittorrentapi import Client as qbClient
from transmission_rpc import Client as TrClient
from utils import ensure_scheme


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
            sorted_mappings = sorted(
                path_mappings, key=lambda x: len(x.get("remote", "")), reverse=True
            )

            for mapping in sorted_mappings:
                remote = mapping.get("remote", "")
                local = mapping.get("local", "")

                if not remote or not local:
                    continue

                # 确保路径比较时统一处理末尾的斜杠
                remote = remote.rstrip("/")
                remote_path_normalized = remote_path.rstrip("/")

                # 检查是否匹配（完全匹配或前缀匹配）
                if remote_path_normalized == remote:
                    # 完全匹配
                    return local
                elif remote_path_normalized.startswith(remote + "/"):
                    # 前缀匹配，替换路径
                    relative_path = remote_path_normalized[len(remote) :].lstrip("/")
                    return os.path.join(local, relative_path)

            # 没有匹配的映射，返回原路径
            return remote_path

    # 没有找到对应的下载器，返回原路径
    return remote_path


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
    VIDEO_EXTENSIONS = {".mkv", ".mp4", ".ts", ".avi", ".wmv", ".mov", ".flv", ".m2ts"}

    if not os.path.exists(path):
        print(f"错误：提供的路径不存在: {path}")
        return None, False

    # 如果提供的路径本身就是一个视频文件，直接返回
    if os.path.isfile(path) and os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS:
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
        if (
            certificate_path
            and os.path.exists(certificate_path)
            and os.path.isdir(certificate_path)
        ):
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
                if not file.startswith(".") and not os.path.isdir(os.path.join(parent_dir, file)):
                    if os.path.splitext(file)[1].lower() in VIDEO_EXTENSIONS:
                        # 检查文件名是否匹配（忽略扩展名）
                        file_name_without_ext = os.path.splitext(file)[0]
                        if (
                            file_name in file_name_without_ext
                            or file_name_without_ext in file_name
                            or file_name.replace(" ", "") in file_name_without_ext.replace(" ", "")
                            or file_name_without_ext.replace(" ", "") in file_name.replace(" ", "")
                        ):
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


def upload_data_title(title: str, torrent_filename: str = "", mediaInfo: str = ""):
    """
    从种子主标题中提取所有参数，并可选地从种子文件名中补充缺失参数。
    【新增】根据 MediaInfo/BDInfo 格式修正标题中的 Blu-ray/BluRay 格式
    【新增】强制将音频参数中的声道数（如 7.1, 5.1）移动到音频名称的最末尾
    【修正】修复 DTS 7.1 Atmos 等乱序格式的抓取问题
    """
    from .mediainfo import validate_media_info_format

    print(f"开始从主标题解析参数: {title}")

    # [新增] 根据MediaInfo/BDInfo类型修正标题中的Blu-ray/BluRay格式
    if mediaInfo and mediaInfo.strip():  # 确保不是空字符串
        # 使用验证函数判断格式
        is_mediainfo, is_bdinfo, _, _, _, _ = validate_media_info_format(mediaInfo)

        if is_mediainfo or is_bdinfo:
            print(
                f"检测到{'MediaInfo' if is_mediainfo else 'BDInfo'}格式，开始修正标题中的Blu-ray格式..."
            )

            # 修正主标题
            if title:
                if is_mediainfo:
                    # MediaInfo格式使用BluRay
                    title = re.sub(r"(?i)blu-?ray", "BluRay", title)
                elif is_bdinfo:
                    # BDInfo格式使用Blu-ray
                    title = re.sub(r"(?i)blu-?ray", "Blu-ray", title)

            print(f"已根据{'MediaInfo' if is_mediainfo else 'BDInfo'}修正标题格式")

    # 1. 预处理
    original_title_str = title.strip()
    params = {}
    unrecognized_parts = []

    # 保持原始标题，让后续的制作组提取逻辑来处理
    title = original_title_str

    title = re.sub(r"[￡€]", "", title)
    title = re.sub(r"\s*剩餘時間.*$", "", title)
    title = re.sub(r"[\s\.]*(mkv|mp4)$", "", title, flags=re.IGNORECASE).strip()
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
            main_part = title[: -len(group) - 1].strip()
            found_special_group = True
            break

    # 如果不是特殊制作组，先尝试匹配 VCB-Studio 变体
    if not found_special_group:
        vcb_variant_pattern = re.compile(
            r"^(?P<main_part>.+?)[-](?P<release_group>[\w\s]+&VCB-Studio)$", re.IGNORECASE
        )
        vcb_match = vcb_variant_pattern.match(title)
        if vcb_match:
            main_part = vcb_match.group("main_part").strip()
            release_group = vcb_match.group("release_group")
            found_special_group = True
            print(f"检测到 VCB-Studio 变体制作组: {release_group}")

    # 如果还不是特殊制作组，使用通用模式匹配
    if not found_special_group:
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
        r"(?<!\w)(Theatrical[\s\.]?Cut|Directors?[\s\.]?Cut|DC|Extended[\s\.]?(?:Cut|Edition)|Final[\s\.]?Cut|Anniversary[\s\.]?Edition|Restored|Remastered|Criterion[\s\.]?(?:Edition|Collection)|Ultimate[\s\.]?Cut|IMAX[\s\.]?Edition|Open[\s\.]?Matte|Unrated[\s\.]?Cut)(?!\w)",
        re.IGNORECASE,
    )
    cut_version_match = cut_version_pattern.search(title_part)
    if cut_version_match:
        cut_version = re.sub(r"[\s\.]+", " ", cut_version_match.group(1).strip())
        if "year" in params:
            params["year"] = f"{params['year']} {cut_version}"
        else:
            params["year"] = cut_version
        title_part = title_part.replace(cut_version_match.group(0), " ", 1).strip()
        print(f"检测到剪辑版本: {cut_version}，已拼接到年份")

    # 4. 预处理标题：修复音频参数格式
    # 增加更多音频格式到预处理列表
    # 【修改】扩展关键词列表，确保 DTS-HD MA 5 1 这种中间有单词的格式也能被识别
    # 注意：必须把长的词（如 DTS-HD MA）放在短的词（如 DTS）前面
    audio_keywords_str = (
        r"DTS-?HD\s*MA|DTS-?HD\s*HR|DTS-?HD|DTS-?X|DTS\s*X|"  # DTS 复合格式
        r"E-?AC-?3|DD\+|"  # 杜比 复合格式
        r"DTS|FLAC|DDP|AV3A|AAC|LPCM|AC3|DD|TrueHD|Opus|OGG|WAV|APE|ALAC|DSD|MP3"  # 基础格式
    )

    # 修复 "DTS-HD MA 5 1" -> "DTS-HD MA 5.1"
    title_part = re.sub(
        rf"((?:{audio_keywords_str}))\s*(\d)\s*(\d)",
        r"\1 \2.\3",
        title_part,
        flags=re.I,
    )
    # 修复 "DTS-HD MA 5.1" -> "DTS-HD MA 5.1" (去除中间多余空格如果存在)
    title_part = re.sub(
        rf"((?:{audio_keywords_str}))(\d(?:\.\d)?)", r"\1 \2", title_part, flags=re.I
    )

    # 技术标签提取（排除已识别的制作组名称）
    tech_patterns_definitions = {
        "medium": r"UHDTV|UHD\s*Blu-?ray|Blu-?ray\s+DIY|Blu-ray|BluRay\s+DIY|BluRay|BDrip|BD-?rip|WEB-DL|WEBrip|TVrip|DVDRip|HDTV|\bUHD\b",
        # 【修改】核心修复：将所有编码和后缀(Atmos/X)合并处理，支持任意顺序
        "audio": (
            # 第一部分：匹配音频编码前缀（最长的放前面）
            r"(?:DTS-?HD\s*MA|DTS-?HD\s*HR|DTS-?HD|DTS-?X|DTS\s*X|DTS|"
            r"(?:Dolby\s*)?TrueHD|DDP|DD\+|DD|E-?AC-?3|AC3|"
            r"FLAC|Opus|AAC|OGG|WAV|APE|ALAC|DSD|MP3|LPCM|PCM)"
            # 第二部分：匹配后续内容，允许 (Atmos/X + 声道) 或 (声道 + Atmos/X)
            # 这里的 ?: 表示不单独捕获组，确保整体作为一个字符串被提取
            r"(?:"
            r"(?:\s*(?:Atmos|X))(?:\s*\d\.\d)?|"  # 模式A: Atmos 7.1
            r"(?:\s*\d\.\d)(?:\s*(?:Atmos|X))?"  # 模式B: 7.1 Atmos (这就是你需要修复的格式)
            r")?|"
            # 第三部分：兜底匹配（单独的 Atmos 开头或其他）
            r"Atmos(?:\s*TrueHD)?(?:\s*\d\.\d)?|"
            r"AV3A\s*\d\.\d|"
            r"\d+\s*Audios?|"
            r"MP2|"
            r"DUAL"
        ),
        "hdr_format": r"Dolby Vision|DoVi|HDR10\+|HDRVivid|HDR10|HLG|HDR|SDR|DV|Vivid",
        "resolution": r"\d{3,4}[pi]|4K",
        "video_codec": r"HEVC|AVC|x265|H\s*[\s\.]?\s*265|x264|H\s*[\s\.]?\s*264|VC-1|AV1|MPEG-2",
        "source_platform": r"Apple TV\+|ViuTV|MyTVSuper|MyVideo|AMZN|Netflix|NF|DSNP|MAX|ATVP|iTunes|friDay|USA|EUR|JPN|CEE|FRA|LINETV|EDR|PCOK|Hami|GBR|NowPlayer|CR|SEEZN|GER|CHN|MA|Viu|Baha|KKTV|IQ|HKG|ITA|ESP",
        "bit_depth": r"\b(?:8|10)bit\b",
        "framerate": r"\d{2,3}fps",
        "completion_status": r"Complete|COMPLETE",
        "video_format": r"3D|HSBS",
        "release_version": r"REMASTERED|REPACK|RERIP|PROPER|REPOST|V\d+",
        "cut_version": r"Theatrical[\s\.]?Cut|Directors?[\s\.]?Cut|DC|Extended[\s\.]?(?:Cut|Edition)|Final[\s\.]?Cut|Anniversary[\s\.]?Edition|Restored|Remastered|Criterion[\s\.]?(?:Edition|Collection)|Ultimate[\s\.]?Cut|IMAX[\s\.]?Edition|Open[\s\.]?Matte|Unrated[\s\.]?Cut",
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

    release_group_keywords = []
    if release_group and release_group != "N/A (无发布组)":
        release_group_keywords = re.split(r"[@\-\s]+", release_group)
        release_group_keywords = [kw.strip() for kw in release_group_keywords if kw.strip()]
        print(f"[调试] 制作组关键词列表: {release_group_keywords}")

    for key in priority_order:
        pattern = tech_patterns_definitions[key]
        search_pattern = (
            re.compile(r"(?<!\w)(" + pattern + r")(?!\w)", re.IGNORECASE)
            if r"\b" not in pattern
            else re.compile(pattern, re.IGNORECASE)
        )
        matches = list(search_pattern.finditer(title_candidate))
        if not matches:
            continue

        first_tech_tag_pos = min(first_tech_tag_pos, matches[0].start())
        raw_values = [
            m.group(0).strip() if r"\b" in pattern else m.group(1).strip() for m in matches
        ]

        filtered_values = []
        for val in raw_values:
            is_release_group_part = any(val.upper() == kw.upper() for kw in release_group_keywords)
            if is_release_group_part:
                print(f"[调试] 过滤掉制作组关键词: {val} (属于 {key})")
            if not is_release_group_part:
                filtered_values.append(val)

        all_found_tags.extend(filtered_values)
        if filtered_values:
            print(f"[调试] '{key}' 字段提取到技术标签: {filtered_values}")

        raw_values = filtered_values

        # --- 修改开始：统一处理逻辑 ---
        processed_values = raw_values

        # 1. 音频特殊处理
        if key == "audio":
            # 先进行基础的格式修正
            processed_values = [re.sub(r"(DD)\+", r"\1+", val, flags=re.I) for val in raw_values]

            # 预处理：修复 DDP 5 1 -> DDP 5.1 这种空格分隔的情况
            audio_keywords = (
                r"DTS|FLAC|DDP|AV3A|AAC|LPCM|AC3|DD|TrueHD|Opus|OGG|WAV|APE|ALAC|DSD|MP3"
            )
            processed_values = [
                re.sub(
                    rf"((?:{audio_keywords}))\s*(\d)\s*(\d)",
                    r"\1 \2.\3",
                    val,
                    flags=re.I,
                )
                for val in processed_values
            ]
            processed_values = [
                re.sub(
                    rf"((?:{audio_keywords}))(\d(?:\.\d)?)",
                    r"\1 \2",
                    val,
                    flags=re.I,
                )
                for val in processed_values
            ]

            # 具体的文本标准化规则
            audio_standardization_rules = [
                (r"DTS-?HD\s*MA", r"DTS-HD MA"),
                (r"DTS-?HD\s*HR", r"DTS-HD HR"),
                (r"True-?HD", r"TrueHD"),  # 先统一 TrueHD 写法
                (r"DDP\s*Atmos", r"DDP Atmos"),
                (r"DTS-?X", r"DTS:X"),
                (r"DTS\s*X", r"DTS:X"),
                (r"E[-\s]?AC[-\s]?3", r"E-AC-3"),
                (r"DD\+", r"DD+"),
                (r"LPCM\s*/\s*PCM", r"LPCM"),
            ]
            for pattern_rgx, replacement in audio_standardization_rules:
                processed_values = [
                    re.sub(pattern_rgx, replacement, val, flags=re.I) for val in processed_values
                ]

            # 【新增核心逻辑】强制将声道数移动到最后
            # 此时因为正则的改进，val 应该是 "DTS 7.1 Atmos" 这样完整的字符串
            final_audio_values = []
            for val in processed_values:
                # 查找类似 2.0, 5.1, 7.1 的模式
                channel_match = re.search(r"\b(\d{1,2}\.\d)\b", val)
                if channel_match:
                    channels = channel_match.group(1)
                    # 1. 从原字符串中移除声道数 (DTS 7.1 Atmos -> DTS  Atmos)
                    temp_val = val.replace(channels, " ")
                    # 2. 清理多余的空格 (DTS  Atmos -> DTS Atmos)
                    temp_val = re.sub(r"\s+", " ", temp_val).strip()
                    # 3. 将声道数拼接到最后 (DTS Atmos -> DTS Atmos 7.1)
                    new_val = f"{temp_val} {channels}"
                    final_audio_values.append(new_val)
                else:
                    # 如果没找到声道数，保持原样
                    final_audio_values.append(val)
            processed_values = final_audio_values

        # 2. 视频编码特殊处理（补充缺失的点）
        elif key == "video_codec":
            # 修复 H 265 / H265 -> H.265
            processed_values = [
                re.sub(r"H\s*[\s\.]?\s*265", r"H.265", val, flags=re.I) for val in processed_values
            ]
            # 修复 H 264 / H264 -> H.264
            processed_values = [
                re.sub(r"H\s*[\s\.]?\s*264", r"H.264", val, flags=re.I) for val in processed_values
            ]
        # --- 修改结束 ---

        unique_processed = sorted(
            list(set(processed_values)), key=lambda x: title_candidate.find(x.replace(" ", ""))
        )
        if unique_processed:
            params[key] = unique_processed[0] if len(unique_processed) == 1 else unique_processed

    # --- [新增] UHD 媒介后处理：判断 UHD 是否为媒介 ---
    if "medium" in params:
        medium_value = params["medium"]
        uhd_in_title = False

        # 处理列表形式的媒介
        if isinstance(medium_value, list):
            # 如果同时有 UHD 和 Blu-ray，需要判断 UHD 是否为媒介
            if "UHD" in medium_value and ("Blu-ray" in medium_value or "BluRay" in medium_value):
                # 检查 UHD 是否在合适的位置（作为媒介而不是电影名）
                if is_uhd_as_medium(title):
                    params["medium"] = "UHD Blu-ray"
                    print(f"[调试] UHD 确认为媒介，与 Blu-ray 合并为: {params['medium']}")
                else:
                    # UHD 是电影名的一部分，只保留 Blu-ray
                    params["medium"] = "Blu-ray"
                    print(f"[调试] UHD 是电影名称的一部分，只保留媒介: {params['medium']}")
                    uhd_in_title = True
            # 如果只有单独的 UHD，需要判断是否为媒介
            elif "UHD" in medium_value:
                if is_uhd_as_medium(title):
                    params["medium"] = "UHD Blu-ray"
                    print(f"[调试] UHD 确认为媒介，补充为: {params['medium']}")
                else:
                    # UHD 不是媒介，移除它
                    params.pop("medium")
                    print(f"[调试] UHD 是电影名称的一部分，已移除媒介字段")
                    uhd_in_title = True

        # 处理字符串形式的媒介
        elif medium_value == "UHD":
            if is_uhd_as_medium(title):
                params["medium"] = "UHD Blu-ray"
                print(f"[调试] UHD 确认为媒介，补充为: {params['medium']}")
            else:
                # UHD 不是媒介，移除它
                params.pop("medium")
                print(f"[调试] UHD 是电影名称的一部分，已移除媒介字段")
                uhd_in_title = True

        # 如果 UHD 是电影名的一部分，需要从已识别标签中移除 UHD
        if uhd_in_title:
            # 从 all_found_tags 中移除 UHD，这样它就不会被从技术区域清理掉
            if "UHD" in all_found_tags:
                all_found_tags.remove("UHD")
                print(f"[调试] 从已识别标签中移除 UHD，保留在标题中")

            # 标记需要重新计算标题区域
            params["_uhd_in_title"] = True

    # --- [新增] 开始: 从种子文件名补充缺失的参数 ---
    if torrent_filename:
        print(f"开始从种子文件名补充参数: {torrent_filename}")
        filename_base = re.sub(
            r"(\.original)?\.torrent", "", torrent_filename, flags=re.IGNORECASE
        )
        filename_candidate = re.sub(r"[\._\[\]\(\)]", " ", filename_base)

        for key in priority_order:
            if key in params and params.get(key):
                continue

            pattern = tech_patterns_definitions[key]
            search_pattern = (
                re.compile(r"(?<!\w)(" + pattern + r")(?!\w)", re.IGNORECASE)
                if r"\b" not in pattern
                else re.compile(pattern, re.IGNORECASE)
            )

            matches = list(search_pattern.finditer(filename_candidate))
            if matches:
                raw_values = [
                    m.group(0).strip() if r"\b" in pattern else m.group(1).strip() for m in matches
                ]

                # --- 修改开始：文件名补充逻辑中也添加 video_codec 标准化 ---
                processed_values = raw_values

                if key == "audio":
                    # 同样的预处理逻辑
                    processed_values = [
                        re.sub(r"(DD)\\+", r"\1+", val, flags=re.I) for val in raw_values
                    ]

                    audio_keywords = (
                        r"DTS|FLAC|DDP|AV3A|AAC|LPCM|AC3|DD|TrueHD|Opus|OGG|WAV|APE|ALAC|DSD|MP3"
                    )
                    processed_values = [
                        re.sub(
                            rf"((?:{audio_keywords}))\s*(\d)\s*(\d)",
                            r"\1 \2.\3",
                            val,
                            flags=re.I,
                        )
                        for val in processed_values
                    ]
                    processed_values = [
                        re.sub(
                            rf"((?:{audio_keywords}))(\d(?:\.\d)?)",
                            r"\1 \2",
                            val,
                            flags=re.I,
                        )
                        for val in processed_values
                    ]

                    # 同样的标准化规则
                    audio_standardization_rules = [
                        (r"DTS-?HD\s*MA", r"DTS-HD MA"),
                        (r"DTS-?HD\s*HR", r"DTS-HD HR"),
                        (r"True-?HD", r"TrueHD"),
                        (r"DDP\s*Atmos", r"DDP Atmos"),
                        (r"DTS-?X", r"DTS:X"),
                        (r"DTS\s*X", r"DTS:X"),
                        (r"E[-\s]?AC[-\s]?3", r"E-AC-3"),
                        (r"DD\+", r"DD+"),
                        (r"LPCM\s*/\s*PCM", r"LPCM"),
                    ]
                    for pattern_rgx, replacement in audio_standardization_rules:
                        processed_values = [
                            re.sub(pattern_rgx, replacement, val, flags=re.I)
                            for val in processed_values
                        ]

                    # 【新增核心逻辑】强制将声道数移动到最后 (与上面相同)
                    final_audio_values = []
                    for val in processed_values:
                        channel_match = re.search(r"\b(\d{1,2}\.\d)\b", val)
                        if channel_match:
                            channels = channel_match.group(1)
                            temp_val = val.replace(channels, " ")
                            temp_val = re.sub(r"\s+", " ", temp_val).strip()
                            new_val = f"{temp_val} {channels}"
                            final_audio_values.append(new_val)
                        else:
                            final_audio_values.append(val)
                    processed_values = final_audio_values

                elif key == "video_codec":
                    # 修复 H 265 / H265 -> H.265
                    processed_values = [
                        re.sub(r"H\s*[\s\.]?\s*265", r"H.265", val, flags=re.I)
                        for val in processed_values
                    ]
                    # 修复 H 264 / H264 -> H.264
                    processed_values = [
                        re.sub(r"H\s*[\s\.]?\s*264", r"H.264", val, flags=re.I)
                        for val in processed_values
                    ]
                # --- 修改结束 ---

                unique_processed = sorted(
                    list(set(processed_values)),
                    key=lambda x: filename_candidate.find(x.replace(" ", "")),
                )

                if unique_processed:
                    print(f"   [文件名补充] 找到缺失参数 '{key}': {unique_processed}")
                    params[key] = (
                        unique_processed[0] if len(unique_processed) == 1 else unique_processed
                    )
                    all_found_tags.extend(unique_processed)
    # --- [新增] 结束 ---

    # --- [新增] UHD 媒介后处理（再次检查，包括从文件名补充的参数） ---
    if "medium" in params:
        medium_value = params["medium"]
        # 检查是否是单独的 UHD（没有跟随 Blu-ray）
        if medium_value == "UHD" or (isinstance(medium_value, list) and "UHD" in medium_value):
            # 验证 UHD 出现在合适的位置（技术标签区域，而不是电影名称中）
            # 使用完整的标题信息（包括文件名）进行验证
            full_title_for_check = f"{title} {torrent_filename}" if torrent_filename else title
            title_upper = full_title_for_check.upper()

            # 先提取标题部分（排除制作组等信息）
            # 找到第一个技术标签的位置
            first_tech_pos = len(title_upper)
            tech_patterns = [
                r"\d{3,4}PI?",
                r"\d{3,4}X?",
                r"X26[45]",
                r"HEVC",
                r"H\.?26[45]",
                r"X264",
                r"AVC",
                r"VC-?1",
                r"VP9",
                r"AV1",
                r"WEB-DL",
                r"WEBRIP",
                r"BDRIP",
                r"DVDRIP",
                r"HDTV",
                r"TVRIP",
                r"BLU-?RAY",
                r"BLURAY",
                r"DTS",
                r"DD",
                r"TRUEHD",
                r"FLAC",
                r"AAC",
                r"LPCM",
                r"HDR",
                r"SDR",
            ]

            for pattern in tech_patterns:
                match = re.search(pattern, title_upper, re.IGNORECASE)
                if match:
                    first_tech_pos = min(first_tech_pos, match.start())

            # 查找所有 UHD 的位置
            uhd_positions = [m.start() for m in re.finditer(r"\bUHD\b", title_upper)]

            # 定义分辨率标签，UHD 应该和分辨率一起出现才可能是媒介
            resolution_patterns = [r"\b2160P\b", r"\b4K\b", r"\b1080P\b", r"\b720P\b"]

            is_valid_uhd_medium = False
            for uhd_pos in uhd_positions:
                # 如果 UHD 出现在第一个技术标签之前，可能是在标题中
                if uhd_pos < first_tech_pos - 20:  # 给一些容错空间
                    # 检查是否紧跟着分辨率标签
                    context_after = title_upper[uhd_pos + 3 : uhd_pos + 20]
                    has_resolution = any(
                        re.search(rp, context_after, re.IGNORECASE) for rp in resolution_patterns
                    )

                    # 如果没有分辨率，很可能是标题的一部分
                    if not has_resolution:
                        print(f"[调试] UHD 出现在标题区域且无分辨率标签，跳过")
                        continue

                    # 检查 UHD 前面是否是冠词或介词，表明可能是标题的一部分
                    context_before_uhd = title_upper[max(0, uhd_pos - 10) : uhd_pos]
                    title_indicators = [r"\bTHE\b", r"\bA\b", r"\bAN\b", r"\bMY\b", r"\bOUR\b"]
                    is_title_part = any(
                        re.search(indicator, context_before_uhd, re.IGNORECASE)
                        for indicator in title_indicators
                    )

                    # 如果是标题的一部分，跳过
                    if is_title_part:
                        print(f"[调试] UHD 前面有标题冠词，可能是电影名称的一部分，跳过")
                        continue

                    # 检查 UHD 后面是否跟着名词性词汇（如 Adventure, Life, Story 等），表明可能是标题的一部分
                    context_after_uhd = title_upper[uhd_pos + 3 : uhd_pos + 30]
                    title_nouns = [
                        r"\bADVENTURE\b",
                        r"\bLIFE\b",
                        r"\bSTORY\b",
                        r"\bCHRONICLES\b",
                        r"\bTALE\b",
                        r"\bLEGEND\b",
                        r"\bQUEST\b",
                        r"\bJOURNEY\b",
                    ]
                    is_title_noun = any(
                        re.search(noun, context_after_uhd, re.IGNORECASE) for noun in title_nouns
                    )

                    # 如果后面跟着标题性名词，很可能是标题的一部分
                    if is_title_noun:
                        print(f"[调试] UHD 后面发现标题性名词，可能是电影名称的一部分，跳过")
                        continue

                # 检查 UHD 后面是否紧跟着标题性名词（即使有分辨率）
                # 这个检查在所有情况下都执行
                context_after_uhd = title_upper[uhd_pos + 3 : uhd_pos + 30]
                title_nouns = [
                    r"\bADVENTURE\b",
                    r"\bLIFE\b",
                    r"\bSTORY\b",
                    r"\bCHRONICLES\b",
                    r"\bTALE\b",
                    r"\bLEGEND\b",
                    r"\bQUEST\b",
                    r"\bJOURNEY\b",
                ]
                is_title_noun = any(
                    re.search(noun, context_after_uhd, re.IGNORECASE) for noun in title_nouns
                )

                # 如果后面跟着标题性名词，很可能是标题的一部分
                if is_title_noun:
                    print(f"[调试] UHD 后面发现标题性名词，可能是电影名称的一部分，跳过")
                    continue

                # 检查 UHD 周围的技术标签密度
                context_before = title_upper[:uhd_pos]
                context_after = title_upper[uhd_pos + 3 :]

                # 在前后30个字符内查找技术标签
                search_context = context_before[-30:] + " UHD " + context_after[:30]

                # 计算技术标签的数量
                tech_count = 0
                for indicator in tech_patterns:
                    matches = re.findall(indicator, search_context, re.IGNORECASE)
                    tech_count += len(matches)

                # 如果周围有足够多的技术标签（至少2个），才认为是媒介信息
                # 但是如果 UHD 在标题区域，需要更高的技术标签要求（至少4个）
                min_tech_required = 4 if uhd_pos < first_tech_pos - 20 else 2

                if tech_count >= min_tech_required:
                    is_valid_uhd_medium = True
                    print(f"[调试] UHD 周围发现 {tech_count} 个技术标签，确认为媒介")
                    break

            # 如果验证通过，将 UHD 补充为 UHD Blu-ray
            if is_valid_uhd_medium:
                if medium_value == "UHD":
                    params["medium"] = "UHD Blu-ray"
                elif isinstance(medium_value, list):
                    params["medium"] = ["UHD Blu-ray" if v == "UHD" else v for v in medium_value]
                print(f"[调试] 检测到单独的 UHD 媒介，已补充为: {params['medium']}")
            else:
                print(
                    f"[调试] UHD 出现在非技术标签区域或周围技术标签不足，保持原样: {medium_value}"
                )

    # 将制作组信息添加到最后的参数中
    params["release_info"] = release_group

    if "quality_modifier" in params:
        modifiers = params.pop("quality_modifier")
        if not isinstance(modifiers, list):
            modifiers = [modifiers]
        if "medium" in params:
            medium_str = (
                params["medium"] if isinstance(params["medium"], str) else params["medium"][0]
            )
            params["medium"] = f"{medium_str} {' '.join(sorted(modifiers))}"

    # 5. 最终标题和未识别内容确定
    # 如果 UHD 在标题中，需要重新计算标题区域
    if params.get("_uhd_in_title"):
        # 找到年份位置
        year_match = re.search(r"\b(19|20)\d{2}\b", title_part)
        if year_match:
            # 标题到年份为止
            title_zone = title_part[: year_match.end()].strip()
            # 移除年份后的技术标签
            title_zone = re.sub(
                r"\s+(Blu-ray|2160p|x265|10bit|HDR|FLAC|[\d.]+|DTS|DDP|AAC|MP2|LPCM|PCM|Audios?).*$",
                "",
                title_zone,
                flags=re.IGNORECASE,
            )
            # 技术区域从年份后开始
            tech_zone = title_part[year_match.end() :].strip()
        else:
            # 如果没有年份，保持原逻辑但排除 UHD 的影响
            # 找到第一个真正的技术标签（排除 UHD）
            first_real_tech_pos = len(title_part)
            for tag in all_found_tags:
                if tag != "UHD":
                    pos = title_part.find(tag)
                    if pos != -1:
                        first_real_tech_pos = min(first_real_tech_pos, pos)
            title_zone = title_part[:first_real_tech_pos].strip()
            tech_zone = title_part[first_real_tech_pos:].strip()

        params["title"] = re.sub(r"[\s\.]+", " ", title_zone).strip()
        # 清理临时标记
        params.pop("_uhd_in_title", None)
    else:
        title_zone = title_part[:first_tech_tag_pos].strip()
        params["title"] = re.sub(r"[\s\.]+", " ", title_zone).strip()
        tech_zone = title_part[first_tech_tag_pos:].strip()

    print(f"[调试] 开始清理技术区域，原始技术区: '{tech_zone}'")
    print(f"[调试] 所有已识别标签: {all_found_tags}")

    cleaned_tech_zone = tech_zone
    for tag in sorted(all_found_tags, key=len, reverse=True):
        if re.search(r"[\u4e00-\u9fa5]", tag):
            pattern_to_remove = re.escape(tag)
        else:
            pattern_to_remove = r"\b" + re.escape(tag) + r"(?!\w)"

        before = cleaned_tech_zone
        cleaned_tech_zone = re.sub(pattern_to_remove, " ", cleaned_tech_zone, flags=re.IGNORECASE)

    remains = re.split(r"[\s\.]+", cleaned_tech_zone)
    unrecognized_parts.extend([part for part in remains if part])
    if unrecognized_parts:
        params["unrecognized"] = " ".join(sorted(list(set(unrecognized_parts))))

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
                processed_audio = []
                for audio_item in params[key]:
                    match = re.match(r"^(\d+)\s*(Audio[s]?)\s+(.+)$", audio_item, re.IGNORECASE)
                    if match:
                        number = match.group(1)
                        audio_word = match.group(2)
                        codec = match.group(3)
                        processed_audio.append(f"{codec} {number}{audio_word}")
                    else:
                        processed_audio.append(audio_item)

                sorted_audio = sorted(
                    processed_audio,
                    key=lambda s: (
                        bool(re.search(r"\d+\s*Audio[s]?$", s, re.IGNORECASE)),
                        -len(s),
                    ),
                )
                english_params[key] = " ".join(sorted_audio)
            else:
                english_params[key] = params[key]

    if "source_platform" in english_params and "audio" in english_params:
        sp_value = english_params["source_platform"]
        if isinstance(sp_value, list):
            sp_value = sp_value[0] if sp_value else ""
        if sp_value == "MA" and "MA" in str(english_params["audio"]):
            del english_params["source_platform"]
        else:
            english_params["source_platform"] = sp_value

    # 6. 有效性质检
    is_valid = bool(english_params.get("title"))
    if is_valid:
        if not any(
            key in english_params for key in ["resolution", "medium", "video_codec", "audio"]
        ):
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
        final_components_list.append({"key": key, "value": chinese_keyed_params.get(key, "")})

    # [新增] 再次根据MediaInfo/BDInfo类型修正标题组件中的Blu-ray/BluRay格式
    if mediaInfo and mediaInfo.strip():  # 确保不是空字符串
        # 使用验证函数判断格式
        is_mediainfo, is_bdinfo, _, _, _, _ = validate_media_info_format(mediaInfo)

        if is_mediainfo or is_bdinfo:
            # 修正标题组件中的值
            for component in final_components_list:
                if isinstance(component, dict) and "value" in component:
                    value = component["value"]
                    if value and isinstance(value, str):
                        if is_mediainfo:
                            # MediaInfo格式使用BluRay
                            component["value"] = re.sub(r"(?i)blu-?ray", "BluRay", value)
                        elif is_bdinfo:
                            # BDInfo格式使用Blu-ray
                            component["value"] = re.sub(r"(?i)blu-?ray", "Blu-ray", value)

            print(f"已根据{'MediaInfo' if is_mediainfo else 'BDInfo'}修正标题组件格式")

    print(f"主标题解析成功。")
    return final_components_list


def add_torrent_to_downloader(
    detail_page_url: str,
    save_path: str,
    downloader_id: str,
    db_manager,
    config_manager,
    direct_download_url: str = "",
):
    """
    从种子详情页下载 .torrent 文件并添加到指定的下载器。
    [最终修复版] 修正了向 Transmission 发送数据时的双重编码问题。
    """
    logging.info(
        f"开始自动添加任务: URL='{detail_page_url}', Path='{save_path}', DownloaderID='{downloader_id}'"
    )

    # 检查环境变量，如果设置为false则跳过种子下载和添加
    if os.getenv("ADD_DOWNLOADS_TORRENTS") == "false":
        msg = f"模拟成功: 环境变量ADD_DOWNLOADS_TORRENTS=false，跳过种子下载和添加"
        logging.info(msg)
        return True, msg

    # 1. 查找对应的站点配置
    conn = db_manager._get_connection()
    cursor = db_manager._get_cursor(conn)
    cursor.execute("SELECT nickname, base_url, cookie, speed_limit FROM sites")
    site_info = None
    for site in cursor.fetchall():
        # [修复] 确保 base_url 存在且不为空
        if site["base_url"] and site["base_url"] in detail_page_url:
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
            "Cookie": site_info["cookie"],
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
        }
        scraper = cloudscraper.create_scraper()

        # 站点级别的代理已不使用全局代理配置
        proxies = None
        torrent_content = None

        # 如果提供了直接下载链接，优先使用直接下载，避免请求详情页
        if direct_download_url:
            try:
                logging.info(f"使用直接下载链接: {direct_download_url}")

                # 使用直接下载链接下载种子文件
                direct_headers = common_headers.copy()
                scraper = cloudscraper.create_scraper()

                # Add retry logic for direct torrent download
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        torrent_response = scraper.get(
                            direct_download_url,
                            headers=direct_headers,
                            timeout=180,
                            proxies=proxies,
                        )
                        torrent_response.raise_for_status()
                        break  # Success, exit retry loop
                    except Exception as e:
                        if attempt < max_retries - 1:
                            logging.warning(
                                f"Attempt {attempt + 1} failed to download torrent directly: {e}. Retrying..."
                            )
                            time.sleep(2**attempt)  # Exponential backoff
                        else:
                            raise  # Re-raise the exception if all retries failed

                torrent_content = torrent_response.content
                logging.info("已通过直接下载链接成功下载种子文件内容。")

            except Exception as e:
                msg = f"使用直接下载链接下载种子文件失败: {e}"
                logging.warning(msg)
                # 如果直接下载失败，继续走详情页逻辑

        # 如果没有直接下载链接或直接下载失败，则请求详情页
        if not torrent_content:
            logging.info("未提供直接下载链接或直接下载失败，开始请求详情页")

            # Add retry logic for network requests
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    details_response = scraper.get(
                        detail_page_url, headers=common_headers, timeout=180, proxies=proxies
                    )
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
            site_base_url = ensure_scheme(site_info["base_url"])
            full_download_url = None  # 初始化full_download_url

            print(f"站点基础URL: {site_base_url}")

            # 检查是否为haidan站点
            if "haidan" in site_base_url:
                # Haidan站点需要提取torrent_id而不是id
                torrent_id_match = re.search(r"torrent_id=(\d+)", detail_page_url)
                if not torrent_id_match:
                    raise ValueError("无法从详情页URL中提取种子ID（torrent_id）。")
                torrent_id = torrent_id_match.group(1)
                # Haidan站点的特殊逻辑
                download_link_tag = soup.find("a", href=re.compile(r"download.php\?id="))

                if not download_link_tag:
                    raise RuntimeError("在详情页HTML中未能找到下载链接！")

                download_url_part = str(download_link_tag["href"])  # 显式转换为str

                # 替换下载链接中的id为从detail_page_url中提取的torrent_id
                download_url_part = re.sub(r"id=\d+", f"id={torrent_id}", download_url_part)

                full_download_url = f"{site_base_url}/{download_url_part}"
            else:
                # 其他站点的通用逻辑 - 提取id参数
                torrent_id_match = re.search(r"id=(\d+)", detail_page_url)
                if not torrent_id_match:
                    raise ValueError("无法从详情页URL中提取种子ID。")
                torrent_id = torrent_id_match.group(1)

                download_link_tag = soup.select_one(
                    f'a.index[href^="download.php?id={torrent_id}"]'
                )
                if not download_link_tag:
                    raise RuntimeError("在详情页HTML中未能找到下载链接！")

                download_url_part = str(download_link_tag["href"])  # 显式转换为str
                full_download_url = f"{site_base_url}/{download_url_part}"

            # 确保full_download_url已被赋值
            if not full_download_url:
                raise RuntimeError("未能成功构建种子下载链接！")

            print(f"种子下载链接: {full_download_url}")

            common_headers["Referer"] = detail_page_url
            # Add retry logic for torrent download
            for attempt in range(max_retries):
                try:
                    torrent_response = scraper.get(
                        full_download_url, headers=common_headers, timeout=180, proxies=proxies
                    )
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
            logging.info("已通过详情页成功下载种子文件内容。")

    except Exception as e:
        msg = f"在下载种子文件步骤发生错误: {e}"
        logging.error(msg, exc_info=True)
        return False, msg

    # 3. 找到下载器配置
    config = config_manager.get()
    downloader_config = next(
        (
            d
            for d in config.get("downloaders", [])
            if d.get("id") == downloader_id and d.get("enabled")
        ),
        None,
    )

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
            client_name = downloader_config["name"]

            if downloader_config["type"] == "qbittorrent":
                client = qbClient(**api_config)
                client.auth_log_in()

                # 准备 qBittorrent 参数
                qb_params = {
                    "torrent_files": torrent_content,
                    "save_path": save_path,
                    "is_paused": False,
                    "skip_checking": True,
                }

                # 如果站点设置了速度限制，则添加速度限制参数
                # 数据库中存储的是MB/s，需要转换为bytes/s传递给下载器API
                if site_info and site_info.get("speed_limit", 0) > 0:
                    speed_limit = int(site_info["speed_limit"]) * 1024 * 1024  # 转换为 bytes/s
                    qb_params["upload_limit"] = speed_limit
                    logging.info(
                        f"为站点 '{site_info['nickname']}' 设置上传速度限制: {site_info['speed_limit']} MB/s"
                    )

                result = client.torrents_add(**qb_params)
                logging.info(f"已将种子添加到 qBittorrent '{client_name}': {result}")

            elif downloader_config["type"] == "transmission":
                client = TrClient(**api_config)

                # 准备 Transmission 参数
                tr_params = {
                    "torrent": torrent_content,
                    "download_dir": save_path,
                    "paused": False,
                }

                # 先添加种子
                result = client.add_torrent(**tr_params)
                logging.info(f"已将种子添加到 Transmission '{client_name}': ID={result.id}")

                # 如果站点设置了速度限制，则在添加后设置速度限制
                # add_torrent 方法不支持速度限制参数，需要使用 change_torrent 方法
                if site_info and site_info.get("speed_limit", 0) > 0:
                    # 转换为 KBps: MB/s * 1024 = KBps
                    speed_limit_kbps = int(site_info["speed_limit"]) * 1024
                    try:
                        client.change_torrent(
                            result.id, upload_limit=speed_limit_kbps, upload_limited=True
                        )
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
    title_dict = {item.get("key"): item.get("value", "") for item in title_components}

    # 定义需要检查的字段和对应的标签映射
    # 格式：字段名 -> [(正则模式, 原始标签名), ...]
    # 注意：这里返回的是原始标签名（如 "DIY"），而不是标准化键（如 "tag.diy"）
    tag_extraction_rules = {
        "媒介": [
            (r"\bDIY\b", "DIY"),
            (r"\bBlu-?ray\s+DIY\b", "DIY"),
            (r"\bBluRay\s+DIY\b", "DIY"),
            (r"\bRemux\b", "Remux"),
        ],
        "制作组": [
            (r"\bDIY\b", "DIY"),
            (r"\bVCB-Studio\b", "VCB-Studio"),
            (r"\bVCB\b", "VCB-Studio"),
        ],
    }

    # 遍历需要检查的字段
    for field_name, patterns in tag_extraction_rules.items():
        field_value = title_dict.get(field_name, "")

        if not field_value:
            continue

        # 如果字段值是列表，转换为字符串
        if isinstance(field_value, list):
            field_value = " ".join(str(v) for v in field_value)
        else:
            field_value = str(field_value)

        # 检查每个正则模式
        for pattern, tag_name in patterns:
            if re.search(pattern, field_value, re.IGNORECASE):
                found_tags.add(tag_name)
                print(f"从标题参数 '{field_name}' 中提取到标签: {tag_name} (匹配: {pattern})")

    result_tags = list(found_tags)
    if result_tags:
        print(f"从标题参数中提取到的标签: {result_tags}")
    else:
        print("从标题参数中未提取到任何标签")

    return result_tags


def extract_tags_from_subtitle(subtitle: str) -> list:
    """
    从副标题中提取语言、字幕和特效标签。
    支持的标签：中字、粤语、国语、台配、特效

    :param subtitle: 副标题文本
    :return: 标签列表，例如 ['tag.中字', 'tag.粤语', 'tag.特效']
    """
    if not subtitle:
        return []

    found_tags = set()

    # 首先检查"特效"关键词（优先级最高，独立检测）
    if "特效" in subtitle:
        found_tags.add("特效")
        print(f"从副标题中提取到标签: 特效")

    # 定义分隔符，用于拆分副标题
    # 支持：[]、【】、|、*、/等符号
    # 注意：对于"| 内封官译简繁"这种只有左边有|的情况，需要特殊处理
    delimiter_pattern = r"[\[\]【】\|\*\/]"

    # 首先处理特殊的"|"分隔符情况
    # 例如："| 内封官译简繁+简英繁英双语字幕" 或 "| 汉语普通话"
    special_pipe_parts = []
    if "|" in subtitle:
        # 按|分割，保留左边|的内容作为独立部分
        pipe_parts = subtitle.split("|")
        for part in pipe_parts:
            if part.strip():
                special_pipe_parts.append(part.strip())

    # 使用正则表达式分割副标题
    parts = re.split(delimiter_pattern, subtitle)

    # 合并两种分割方式的结果
    all_parts = list(set(parts + special_pipe_parts))

    # 定义关键词到标签的映射
    tag_patterns = {
        "中字": [
            r"中[字幕]",
            r"简[体中繁]",
            r"繁[体中简]",
            r"中英",
            r"简英",
            r"繁英",
            r"简繁",
            r"中日",
            r"简日",
            r"繁日",
            r"官译",
            r"内封.*[简繁]",
            r"[简繁].*字幕",
            r"双语字幕",
            r"多国.*字幕",
            r"软字幕",
        ],
        "粤语": [
            r"粤[语配]",
            r"粤音",
            r"粤.*配音",
            r"港版",
            r"港.*配音",
            r"\b粤\b",  # 匹配独立的"粤"字，如"陆/日/台/粤/闽五语"中的"粤"
        ],
        "国语": [
            r"国[语配]",
            r"国.*配音",
            r"汉语",
            r"普通话",
            r"中文配音",
            r"华语",
            r"台配国语",  # 特殊处理：台配国语会匹配国语，但后续会被台配覆盖
            r"\b陆\b",
            r"\b国\b",  # 匹配独立的"陆"或"国"字，如"陆/日/台/粤/闽五语"中的"陆"
        ],
        "台配": [
            r"台[配音]",
            r"台.*配音",
            r"东森",
            r"纬来",
            r"台配国语",
            r"台配.*国语",
            r"\b台\b",  # 匹配独立的"台"字，如"陆/日/台/粤/闽五语"中的"台"
        ],
    }

    # 遍历每个分割后的部分进行关键词匹配
    for part in all_parts:
        if not part.strip():
            continue

        part_clean = part.strip()

        # 检查每个标签的模式
        for tag_name, patterns in tag_patterns.items():
            for pattern in patterns:
                if re.search(pattern, part_clean, re.IGNORECASE):
                    found_tags.add(tag_name)
                    print(
                        f"从副标题段落 '{part_clean}' 中提取到标签: {tag_name} (匹配: {pattern})"
                    )
                    # 找到匹配后跳出当前标签的模式循环
                    break

    # 为所有标签添加 tag. 前缀
    prefixed_tags = [f"tag.{tag}" for tag in found_tags]

    if prefixed_tags:
        print(f"从副标题中提取到的标签: {prefixed_tags}")
    else:
        print("从副标题中未提取到任何标签")

    return prefixed_tags


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
    category_match = re.search(r"[◎❁]\s*类\s*别\s*(.+?)(?:\n|$)", description_text)
    if category_match:
        category_text = category_match.group(1).strip()
        print(f"从简介中提取到类别: {category_text}")

        # 定义类别关键词到标签的映射
        category_tag_map = {
            "喜剧": "tag.喜剧",
            "Comedy": "tag.喜剧",
            "儿童": "tag.儿童",
            "Children": "tag.儿童",
            "动画": "tag.动画",
            "Animation": "tag.动画",
            "动作": "tag.动作",
            "Action": "tag.动作",
            "爱情": "tag.爱情",
            "Romance": "tag.爱情",
            "科幻": "tag.科幻",
            "Sci-Fi": "tag.科幻",
            "恐怖": "tag.恐怖",
            "Horror": "tag.恐怖",
            "惊悚": "tag.惊悚",
            "Thriller": "tag.惊悚",
            "悬疑": "tag.悬疑",
            "Mystery": "tag.悬疑",
            "犯罪": "tag.犯罪",
            "Crime": "tag.犯罪",
            "战争": "tag.战争",
            "War": "tag.战争",
            "冒险": "tag.冒险",
            "Adventure": "tag.冒险",
            "奇幻": "tag.奇幻",
            "Fantasy": "tag.奇幻",
            "家庭": "tag.家庭",
            "Family": "tag.家庭",
            "剧情": "tag.剧情",
            "Drama": "tag.剧情",
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


def extract_origin_from_description(description_text: str) -> str:
    """
    从简介详情中提取产地信息，并检查是否能在 global_mappings.yaml 的 source 映射中找到对应的标准键。
    如果找不到映射，则设置为'其他'。

    :param description_text: 简介详情文本
    :return: 产地信息，例如 "日本"、"中国" 等，如果无法映射则返回 "其他"
    """
    if not description_text:
        return ""

    # 使用正则表达式匹配 "◎产　　地　日本" 这种格式
    # 支持多种变体：◎产地、◎产　　地、◎国　　家、◎国家地区等
    # 修复：使用 [^\n\r]+ 而不是 .+? 来正确匹配包含空格的产地名称（如"中国大陆"）
    patterns = [
        r"[◎❁]\s*产\s*地\s*([^\n\r]+?)(?:\n|$)",  # 匹配 ◎产地 中国大陆
        r"[◎❁]\s*国\s*家\s*([^\n\r]+?)(?:\n|$)",  # 匹配 ◎国家 中国大陆
        r"[◎❁]\s*地\s*区\s*([^\n\r]+?)(?:\n|$)",  # 匹配 ◎地区 中国大陆
        r"[◎❁]\s*国家地区\s*([^\n\r]+?)(?:\n|$)",  # 匹配 ◎国家地区 中国大陆
        r"制片国家/地区[:\s]+([^\n\r]+?)(?:\n|$)",  # 匹配 制片国家/地区: 中国大陆
        r"制片国家[:\s]+([^\n\r]+?)(?:\n|$)",  # 匹配 制片国家: 中国大陆
        r"国家[:\s]+([^\n\r]+?)(?:\n|$)",  # 匹配 国家: 中国大陆
        r"产地[:\s]+([^\n\r]+?)(?:\n|$)",  # 匹配 产地: 中国大陆
        r"[产]\s*地[:\s]+([^，,\n\r]+)",
        r"[国]\s*家[:\s]+([^，,\n\r]+)",
        r"[地]\s*区[:\s]+([^，,\n\r]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, description_text)
        if match:
            origin = match.group(1).strip()
            # 清理可能的多余字符
            origin = re.sub(r"[\[\]【】\(\)]", "", origin).strip()
            # 添加额外的清理步骤，去除前置的冒号、空格等字符
            origin = re.sub(r"^[:\s\u3000]+", "", origin).strip()
            # 移除常见的分隔符，如" / "、","等
            origin = re.split(r"\s*/\s*|\s*,\s*|\s*;\s*|\s*&\s*", origin)[0].strip()
            print("提取到产地信息:", origin)

            # 检查产地是否能在 global_mappings.yaml 的 source 映射中找到对应的标准键
            if _check_origin_mapping(origin):
                return origin
            else:
                print(f"产地 '{origin}' 无法在 source 映射中找到对应的标准键，设置为'其他'")
                return "其他"

    return ""


def _check_origin_mapping(origin: str) -> bool:
    """
    检查产地是否能在 global_mappings.yaml 的 source 映射中找到对应的标准键。

    :param origin: 产地字符串
    :return: 如果能找到映射返回 True，否则返回 False
    """
    try:
        # 读取 global_mappings.yaml 文件
        with open(GLOBAL_MAPPINGS, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # 获取 source 映射
        source_mappings = config.get("global_standard_keys", {}).get("source", {})

        # 检查产地是否在映射中
        if origin in source_mappings:
            print(f"产地 '{origin}' 在 source 映射中找到对应的标准键: {source_mappings[origin]}")
            return True
        else:
            print(f"产地 '{origin}' 在 source 映射中未找到对应的标准键")
            return False

    except Exception as e:
        print(f"检查产地映射时出错: {e}")
        # 如果检查失败，为了安全起见，返回 True（保持原产地）
        return True


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
        import re

        # 方案1: 直接替换域名和路径
        direct_url = show_url.replace(
            "https://pixhost.to/show/", "https://img1.pixhost.to/images/"
        ).replace("https://pixhost.to/th/", "https://img1.pixhost.to/images/")

        # 移除缩略图后缀（如 _cover.jpg -> .jpg）
        direct_url = re.sub(r"_..\.jpg$", ".jpg", direct_url)

        # 方案2: 如果方案1失败，使用正则提取重建URL
        if not direct_url.startswith("https://img1.pixhost.to/images/"):
            match = re.search(r"(\d+)/([^/]+\.(jpg|png|gif))", show_url)
            if match:
                direct_url = f"https://img1.pixhost.to/images/{match.group(1)}/{match.group(2)}"

        # 最终验证
        if re.match(r"^https://img1\.pixhost\.to/images/\d+/[^/]+\.(jpg|png|gif)$", direct_url):
            return direct_url
        else:
            print(f"   URL格式验证失败: {direct_url}")
            return ""

    except Exception as e:
        print(f"   URL转换异常: {e}")
        return ""


def _get_downloader_proxy_config(downloader_id: str):
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
                host_value = downloader.get("host", "")
                proxy_port = downloader.get("proxy_port", 9090)
                if host_value.startswith(("http://", "https://")):
                    parsed_url = urlparse(host_value)
                else:
                    parsed_url = urlparse(f"http://{host_value}")
                proxy_ip = parsed_url.hostname
                if not proxy_ip:
                    if "://" in host_value:
                        proxy_ip = host_value.split("://")[1].split(":")[0].split("/")[0]
                    else:
                        proxy_ip = host_value.split(":")[0]
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
        return {"is_complete": False, "missing_fields": ["所有字段"], "found_fields": []}

    # 定义必要字段的匹配模式
    # 每个字段可以有多个匹配模式（正则表达式）
    required_patterns = {
        "片名": [
            r"[◎❁]\s*片\s*名",
            r"[◎❁]\s*译\s*名",
            r"[◎❁]\s*标\s*题",
            r"片名\s*[:：]",
            r"译名\s*[:：]",
            r"Title\s*[:：]",
        ],
        "年代": [
            r"[◎❁]\s*年\s*代",
            r"[◎❁]\s*年\s*份",
            r"年份\s*[:：]",
            r"年代\s*[:：]",
            r"Year\s*[:：]",
        ],
        "产地": [
            r"[◎❁]\s*产\s*地",
            r"[◎❁]\s*国\s*家",
            r"[◎❁]\s*地\s*区",
            r"制片国家/地区\s*[:：]",
            r"制片国家\s*[:：]",
            r"国家\s*[:：]",
            r"产地\s*[:：]",
            r"Country\s*[:：]",
        ],
        "类别": [
            r"[◎❁]\s*类\s*别",
            r"[◎❁]\s*类\s*型",
            r"类型\s*[:：]",
            r"类别\s*[:：]",
            r"Genre\s*[:：]",
        ],
        "语言": [r"[◎❁]\s*语\s*言", r"语言\s*[:：]", r"Language\s*[:：]"],
        "导演": [r"[◎❁]\s*导\s*演", r"导演\s*[:：]", r"Director\s*[:：]"],
        "简介": [
            r"[◎❁]\s*简\s*介",
            r"[◎❁]\s*剧\s*情",
            r"[◎❁]\s*内\s*容",
            r"简介\s*[:：]",
            r"剧情\s*[:：]",
            r"内容简介\s*[:：]",
            r"Plot\s*[:：]",
            r"Synopsis\s*[:：]",
        ],
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
        "found_fields": found_fields,
    }


def is_uhd_as_medium(title_str):
    """
    判断 UHD 是否作为媒介而不是电影名称的一部分
    返回 True 表示 UHD 是媒介，False 表示是电影名
    """
    title_upper = title_str.upper()

    # 查找所有 UHD 的位置
    uhd_positions = [m.start() for m in re.finditer(r"\bUHD\b", title_upper)]

    if not uhd_positions:
        return False

    # 查找年份位置，年份通常是标题和技术标签的分界点
    year_match = re.search(r"\b(19|20)\d{2}\b", title_upper)

    for uhd_pos in uhd_positions:
        # 如果找到年份
        if year_match:
            # 如果 UHD 在年份之前，很可能是电影名的一部分
            if uhd_pos < year_match.start():
                print(f"[调试] UHD 在年份之前，判断为电影名称")
                return False

        # 检查 UHD 周围的上下文
        context_before = title_upper[max(0, uhd_pos - 10) : uhd_pos]
        context_after = title_upper[uhd_pos + 3 : uhd_pos + 10]

        # 如果前后都有字母（不是数字或标点），很可能是标题的一部分
        has_letter_before = bool(re.search(r"[A-Z]$", context_before))
        has_letter_after = bool(re.search(r"^[A-Z]", context_after))

        # 检查后面是否跟着分辨率（这是媒介的标志）
        has_resolution_after = bool(re.search(r"\b(2160P|4K|1080P|720P)\b", context_after))

        # 如果前后有字母且没有跟着分辨率，很可能是电影名
        if (has_letter_before or has_letter_after) and not has_resolution_after:
            print(f"[调试] UHD 周围有字母且无分辨率，判断为电影名称")
            return False

        # 如果跟着分辨率，肯定是媒介
        if has_resolution_after:
            print(f"[调试] UHD 后面跟着分辨率，判断为媒介")
            return True

    # 默认情况下，认为 UHD 是媒介（保守策略）
    return True
