# utils/media_helper.py

from pymediainfo import MediaInfo
import re


def upload_data_mediaInfo(mediaInfo: str):
    """
    检查传入的文本是有效的 MediaInfo 还是 BDInfo 格式。
    如果两种格式都不是，则认为其不完整或无法识别。
    """
    print("开始检查 MediaInfo/BDInfo 格式")

    # --- [核心修改] 定义两种不同格式的验证标准 ---

    # 1. 标准 MediaInfo 格式的关键字
    #    这种格式通常由 MediaInfo 工具直接生成，包含 General/Video/Audio 等区块。
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
    #    这种格式通常由 BDInfo 工具生成，用于描述蓝光原盘，包含 DISC INFO 等区块。
    bdinfo_keywords = [
        "DISC INFO",
        "PLAYLIST REPORT",
        "VIDEO:",
        "AUDIO:",
        "SUBTITLES:",
        "Disc Label",
        "Disc Size",
    ]

    # --- [核心修改] 依次进行格式检查 ---

    # 检查是否为标准 MediaInfo 格式
    is_standard_mediainfo = all(keyword in mediaInfo for keyword in standard_mediainfo_keywords)

    # 检查是否为 BDInfo 格式
    is_bdinfo = all(keyword in mediaInfo for keyword in bdinfo_keywords)

    if is_standard_mediainfo:
        print("检测到标准 MediaInfo 格式，验证通过。")
        return mediaInfo
    elif is_bdinfo:
        print("检测到 BDInfo 格式，验证通过。")
        return mediaInfo
    else:
        print("格式不完整或无法识别，将返回原始信息。")
        # 即使格式不符，也返回原始文本，以便用户可以在前端预览和手动修改。
        # 这里的备用逻辑（从本地文件重新解析）仅用于开发调试，不应在生产环境中使用。
        # try:
        #     print("尝试使用 MediaInfo 工具从示例文件路径重新提取...")
        #     # 示例路径，请替换为您自己的测试文件路径
        #     file_path = "/path/to/your/test/video.mkv"
        #     # 示例路径，请替换为您自己的 MediaInfo.dll 路径
        #     mediainfo_dll_path = "/path/to/your/MediaInfo.dll"
        #     media_info_parsed = MediaInfo.parse(
        #         file_path, library_file=mediainfo_dll_path, output="text", full=False
        #     )
        #     print("从文件重新提取成功。")
        #     return media_info_parsed
        # except Exception as e:
        #     print(f"从文件处理时出错: {e}。将返回原始 mediainfo。")
        return mediaInfo


import re


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
        title = original_title_str[: chinese_junk_match.start()].strip()
    else:
        title = original_title_str

    title = re.sub(r"[￡€]", "", title)
    title = re.sub(r"\s*剩餘時間.*$", "", title)
    title = re.sub(r"[\s\.]*(mkv|mp4)$", "", title, flags=re.IGNORECASE).strip()
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
            main_part = title[: -len(group) - 1].strip()
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
            params["release_info"] = (
                f"{internal_tag}-{release_group}"
                if internal_tag and "@" in internal_tag
                else (f"{release_group} ({internal_tag})" if internal_tag else release_group)
            )
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
        "medium": r"UHDTV|UHD\s*Blu-?ray|Blu-ray|WEB-DL|WEBrip|TVrip|DVDRip|HDTV|DVD9",
        "audio": r"DTS-HD(?:\s*MA)?(?:\s*\d\.\d)?|(?:Dolby\s*)?TrueHD(?:\s*Atmos)?(?:\s*\d\.\d)?|Atmos(?:\s*TrueHD)?(?:\s*\d\.\d)?|DTS(?:\s*\d\.\d)?|DDP(?:\s*\d\.\d)?|DD\+(?:\s*\d\.\d)?|DD(?:\s*\d\.\d)?|AC3(?:\s*\d\.\d)?|FLAC(?:\s*\d\.\d)?|AAC(?:\s*\d\.\d)?|LPCM(?:\s*\d\.\d)?|AV3A\s*\d\.\d|\d+\s*Audios?|MP2|DUAL",
        "hdr_format": r"Dolby Vision|DoVi|HDR10\+|HDRVivid|HDR10|HLG|HDR|SDR|DV|Vivid",
        "resolution": r"\d{3,4}[pi]|4K",
        "video_codec": r"HEVC|AVC|x265|H\s*\.?\s*265|x264|H\s*\.?\s*264|VC-1|AV1|MPEG-2",
        "source_platform": r"Apple TV\+|ViuTV|MyTVSuper|AMZN|Netflix|NF|DSNP|MAX|ATVP|iTunes|friDay|USA|EUR|JPN|CEE|FRA|LINETV|EDR|PCOK|Hami|GBR|NowPlayer|CR|SEEZN|GER|CHN|MA|Viu|Baha|KKTV|IQ|HKG|ITA|ESP",
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
        all_found_tags.extend(raw_values)
        processed_values = (
            [re.sub(r"(DD)\+", r"\1+", val, flags=re.I) for val in raw_values]
            if key == "audio"
            else raw_values
        )
        if key == "audio":
            processed_values = [
                re.sub(
                    r"((?:FLAC|DDP|AV3A|AAC|LPCM|AC3|DD))(\d(?:\.\d)?)", r"\1 \2", val, flags=re.I
                )
                for val in processed_values
            ]

        unique_processed = sorted(
            list(set(processed_values)), key=lambda x: title_candidate.find(x.replace(" ", ""))
        )
        if unique_processed:
            params[key] = unique_processed[0] if len(unique_processed) == 1 else unique_processed

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
    title_zone = title_part[:first_tech_tag_pos].strip()
    tech_zone = title_part[first_tech_tag_pos:].strip()
    params["title"] = re.sub(r"[\s\.]+", " ", title_zone).strip()

    cleaned_tech_zone = tech_zone
    for tag in sorted(all_found_tags, key=len, reverse=True):
        pattern_to_remove = r"\b" + re.escape(tag) + r"(?!\w)"
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
                sorted_audio = sorted(
                    params[key], key=lambda s: (s.upper().endswith("AUDIOS"), -len(s))
                )
                english_params[key] = " ".join(sorted_audio)
            else:
                english_params[key] = params[key]

    if "source_platform" in english_params and "audio" in english_params:
        is_sp_list = isinstance(english_params["source_platform"], list)
        sp_values = (
            english_params["source_platform"]
            if is_sp_list
            else [english_params["source_platform"]]
        )
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
        final_components_list.append({"key": key, "value": chinese_keyed_params.get(key, "")})

    print(f"主标题解析成功。")
    return final_components_list
