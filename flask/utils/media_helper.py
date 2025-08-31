# utils/media_helper.py

import re
import os
import shutil
import subprocess
import tempfile
import requests
import json
from pymediainfo import MediaInfo
import time
from config import TEMP_DIR


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


def upload_data_title(title: str):
    """
    从种子主标题中提取所有参数。
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
        r"UHDTV|UHD\s*Blu-?ray|Blu-ray|BluRay|WEB-DL|WEBrip|TVrip|DVDRip|HDTV|DVD9",
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


def upload_data_screenshot(image_type, source_info, save_path):
    """
    使用ffmpeg从指定的视频文件中截取5张图片，上传到Pixhost图床，
    并返回一个包含所有图片BBCode链接的字符串。
    """
    print("开始执行截图和上传任务...")

    target_video_file = _find_target_video_file(save_path)

    # --- 1. 配置和环境检查 ---
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print("错误：找不到 ffmpeg 或 ffprobe。请确保它们已安装并已添加到系统环境变量 PATH 中。")
        return ""

    try:
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
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"错误：使用 ffprobe 获取视频时长失败。{e}")
        return ""
    except ValueError:
        print("错误：无法将 ffprobe 的输出解析为有效的时长。")
        return ""

    uploaded_urls = []
    screenshot_points = [0.20, 0.35, 0.65]

    try:
        for i, point in enumerate(screenshot_points):
            screenshot_time = duration * point
            output_filename = os.path.join(
                TEMP_DIR, f"screenshot_{i+1}_{source_info}_{time.time()}.jpg")

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
                    image_url = _upload_to_pixhost(output_filename)
                    if image_url:
                        uploaded_urls.append(image_url)
                else:
                    print(f"警告：ffmpeg 命令执行成功，但未找到输出文件 {output_filename}")

            except subprocess.CalledProcessError as e:
                print(f"错误：ffmpeg 截图失败。命令返回了非零退出码。")
                print(
                    f"FFMPEG Stderr: {e.stderr.decode('utf-8', errors='ignore')}"
                )
            except FileNotFoundError:
                print("错误: ffmpeg 命令未找到。请确认其已安装并位于系统 PATH。")
                break
    finally:
        # if os.path.exists(TEMP_DIR):
        #     print(f"正在清理临时目录: {TEMP_DIR}")
        #     shutil.rmtree(TEMP_DIR)
        print(f"正在清理临时目录: {TEMP_DIR}")

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


def upload_data_poster():
    pass
