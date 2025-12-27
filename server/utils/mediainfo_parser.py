#!/usr/bin/env python3
"""
MediaInfo 解析模块
功能:
1. 集中管理 MediaInfo 和 BDInfo 的解析逻辑
2. 提供 HDR 信息提取功能
3. 提供音频信息提取功能
4. 提供统一的标签提取接口
"""

import re
import os
from typing import Dict, List, Optional, Tuple, Any

# ================= 音频编码层级定义 =================

CODEC_TIERS = {
    "AV3A": 0,
    "DTS:X": 1,
    "TRUEHD": 10,
    "DTS-HD MA": 11,
    "DTS-HD HR": 20,
    "FLAC": 21,
    "LPCM": 21,
    "PCM": 21,
    "ALAC": 21,
    "WAV": 21,
    "APE": 21,
    "DSD": 21,
    "DDP": 30,
    "E-AC-3": 30,
    "DTS": 31,
    "DD": 40,
    "AC-3": 40,
    "AC3": 40,
    "OPUS": 50,
    "AAC": 51,
    "VORBIS": 52,
    "MP3": 60,
    "MPEG AUDIO": 60,
}


# ================= HDR 解析函数 =================

def get_title_hdr_tags(title: str) -> List[str]:
    """
    提取标题中已有的 HDR 标签 (返回原始字符串)
    
    Args:
        title: 标题字符串
        
    Returns:
        HDR 标签列表
    """
    if not title:
        return []
    hdr_pattern = r"Dolby\s*Vision|DoVi|HDR10\+|HDRVivid|HDR10|HLG|HDR|SDR|DV|Vivid|EDR"
    matches = re.finditer(r"(?<!\w)(" + hdr_pattern + r")(?!\w)", title, re.IGNORECASE)
    tags = []
    for m in matches:
        tags.append(m.group(1).strip())  # 保持原始写法
    return list(set(tags))


def calculate_match_status(title_tags: List[str], verdict: str, standard_tag: str) -> str:
    """
    计算标题和参数的匹配状态
    
    Args:
        title_tags: 从标题提取的 HDR 标签
        verdict: 解析出的 HDR 类型
        standard_tag: 标准标签
        
    Returns:
        匹配状态描述
    """
    tags_upper = [t.upper() for t in title_tags]
    is_title_hdr = len(tags_upper) > 0 and "SDR" not in tags_upper and "EDR" not in tags_upper
    is_param_hdr = verdict != "SDR"
    
    has_hlg_title = "HLG" in tags_upper
    
    if has_hlg_title and standard_tag == "HLG":
        return "【 双重确认 (HLG) 】"
    elif is_title_hdr and is_param_hdr:
        return "【 双重确认 (HDR) 】"
    elif is_title_hdr and not is_param_hdr:
        return "【 ⚠️ 仅标题标识 (虚标?) 】"
    elif not is_title_hdr and is_param_hdr:
        return "【 仅参数有 (需补全) 】"
    else:
        return "【 SDR 】"


def determine_bdinfo_hdr(video_lines: List[str]) -> Tuple[str, str]:
    """
    解析 BDInfo Video 行
    
    Args:
        video_lines: BDInfo 视频行列表
        
    Returns:
        (详细描述, 标准标签) 元组
    """
    combined_desc = " ".join(video_lines).upper()
    
    has_dv = "DOLBY VISION" in combined_desc
    has_hdr10plus = "HDR10+" in combined_desc
    has_hdr10 = "HDR10" in combined_desc
    has_hlg = "HLG" in combined_desc
    
    # 1. 杜比视界
    if has_dv:
        if has_hdr10plus:
            return "Dolby Vision (兼容 HDR10+)", "DoVi HDR10+"
        elif has_hdr10:
            return "Dolby Vision (兼容 HDR10)", "DoVi HDR"
        else:
            return "Dolby Vision (单层/无兼容)", "DoVi"

    # 2. HDR10+
    if has_hdr10plus:
        return "HDR10+", "HDR10+"

    # 3. HDR10
    if has_hdr10:
        return "HDR10", "HDR"
    
    # 4. HLG
    if has_hlg:
        return "HLG", "HLG"

    # 5. SDR / 推断
    if "BT.2020" in combined_desc and not has_hdr10:
        return "HDR10 (仅BT.2020推断)", "HDR"
    
    return "SDR", ""


def analyze_bdinfo_item(bdinfo_text: str) -> Dict[str, Any]:
    """
    分析 BDInfo 文本
    
    Args:
        bdinfo_text: BDInfo 文本内容
        
    Returns:
        包含 HDR 信息的字典
    """
    lines = bdinfo_text.split("\n")
    disc_label = ""
    disc_title = ""
    video_lines = []
    current_section = None

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Disc Label:"):
            disc_label = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("Disc Title:"):
            disc_title = stripped.split(":", 1)[1].strip()
        
        if stripped in ["VIDEO:", "AUDIO:", "SUBTITLES:", "FILES:", "DISC INFO:", "PLAYLIST REPORT:"]:
            current_section = stripped.replace(":", "")
            continue
            
        if current_section == "VIDEO" and stripped:
            if "-----" in stripped or stripped.lower().startswith("codec"):
                continue
            if "kbps" in stripped.lower() or "mbps" in stripped.lower():
                video_lines.append(stripped)

    filename = disc_label if disc_label else disc_title
    title_tags = get_title_hdr_tags(filename)
    mi_verdict, standard_tag = determine_bdinfo_hdr(video_lines)
    match_status = calculate_match_status(title_tags, mi_verdict, standard_tag)

    return {
        "filename": filename,
        "title_tags": title_tags,
        "raw_lines": video_lines,
        "mi_verdict": mi_verdict,
        "standard_tag": standard_tag,
        "match_status": match_status,
        "internal_title_general": "",  # BDInfo 无此项，保持结构一致
        "internal_title_video": ""     # BDInfo 无此项
    }


def determine_mediainfo_hdr(info_dict: Dict[str, str]) -> Tuple[str, str]:
    """
    解析 MediaInfo 参数字典
    
    Args:
        info_dict: 包含 HDR 参数的字典
        
    Returns:
        (详细描述, 标准标签) 元组
    """
    hdr_format = info_dict.get("hdr_format", "").upper()
    transfer = info_dict.get("transfer", "").upper()
    primaries = info_dict.get("primaries", "").upper()

    # 1. 杜比视界
    if "DOLBY VISION" in hdr_format:
        if "HDR10+" in hdr_format:
            return "Dolby Vision (兼容 HDR10+)", "DoVi HDR10+"
        elif "HDR10" in hdr_format:
            return "Dolby Vision (兼容 HDR10)", "DoVi HDR"
        else:
            return "Dolby Vision (单层/无兼容)", "DoVi"

    # 2. HDR10+
    if "HDR10+" in hdr_format or "SMPTE ST 2094" in hdr_format:
        return "HDR10+", "HDR10+"

    # 3. HDR Vivid
    if "VIVID" in hdr_format:
        return "HDR Vivid", "HDR Vivid"

    # 4. HDR10
    if "HDR10" in hdr_format or "SMPTE ST 2086" in hdr_format:
        return "HDR10", "HDR"
    
    # 5. HLG
    if "HLG" in transfer or "ARIB STD-B67" in transfer:
        return "HLG", "HLG"

    # 6. 隐式 HDR10
    if "BT.2020" in primaries and ("PQ" in transfer or "SMPTE ST 2084" in transfer):
        return "HDR10 (参数推断)", "HDR"

    return "SDR", ""


def analyze_mediainfo_item(media_info: str) -> Dict[str, Any]:
    """
    分析 MediaInfo 文本
    
    Args:
        media_info: MediaInfo 文本内容
        
    Returns:
        包含 HDR 信息的字典
    """
    lines = media_info.split("\n")
    filename = ""
    general_title = ""
    video_title = ""
    
    for line in lines:
        if m := re.match(r"^\s*Complete\s+name\s*:\s*(.+?)\s*$", line, re.IGNORECASE):
            full_path = m.group(1).strip()
            filename = os.path.basename(full_path.replace("\\", "/"))
            break
            
    title_tags = get_title_hdr_tags(filename)
    
    current_section = "General"
    extracted_lines = []
    video_params = {
        "hdr_format": "", "primaries": "", "transfer": "", "mastering_lum": ""
    }
    target_keys_video = {
        "hdr format": "hdr_format",
        "color primaries": "primaries",
        "transfer characteristics": "transfer",
        "mastering display luminance": "mastering_lum",
        "encoding settings": "encoding_settings"
    }

    for line in lines:
        stripped = line.strip()
        
        # 区块检测
        if stripped.startswith("Video"):
            if re.match(r"^Video(\s*#\d+)?$", stripped):
                current_section = "Video"
                continue
        elif re.match(r"^(Audio|Text|Menu|Chapters|General)(\s*#\d+)?$", stripped):
             current_section = stripped.split()[0]
             continue

        # 参数提取
        if ":" in line:
            parts = line.split(":", 1)
            if len(parts) == 2:
                raw_key = parts[0].strip().lower()
                val = parts[1].strip()

                if raw_key == "title":
                    if current_section == "General":
                        general_title = val
                    elif current_section == "Video":
                        video_title = val

                if current_section == "Video":
                    matched_key = None
                    if raw_key in target_keys_video:
                        matched_key = raw_key
                    else:
                        for tk in target_keys_video:
                            if tk == raw_key:
                                matched_key = tk
                                break
                    
                    if matched_key:
                        param_name = target_keys_video[matched_key]
                        if param_name == "encoding_settings":
                            if "no-hdr" in val:
                                extracted_lines.append(f"Encoding settings: ...no-hdr...")
                        else:
                            video_params[param_name] = val
                            extracted_lines.append(line.strip())

    mi_verdict, standard_tag = determine_mediainfo_hdr(video_params)
    match_status = calculate_match_status(title_tags, mi_verdict, standard_tag)

    return {
        "filename": filename,
        "title_tags": title_tags,
        "raw_lines": extracted_lines,
        "mi_verdict": mi_verdict,
        "standard_tag": standard_tag,
        "match_status": match_status,
        "internal_title_general": general_title,
        "internal_title_video": video_title
    }


# ================= 音频解析函数 =================

def get_codec_tier(codec_name: str) -> int:
    """
    获取音频编码的层级分数
    
    Args:
        codec_name: 音频编码名称
        
    Returns:
        层级分数（越低越好）
    """
    if not codec_name:
        return 999
    c = codec_name.upper()
    if "DTS-HD" in c and "MA" in c:
        return CODEC_TIERS["DTS-HD MA"]
    if "DTS-HD" in c and "HR" in c:
        return CODEC_TIERS["DTS-HD HR"]
    if "HE-AAC" in c:
        return CODEC_TIERS["AAC"]
    return CODEC_TIERS.get(c, 100)


def parse_channel_count(layout_str: str) -> float:
    """
    解析声道数量
    
    Args:
        layout_str: 声道布局字符串
        
    Returns:
        声道数量
    """
    if not layout_str:
        return 0.0
    parts = [float(p) for p in re.findall(r"\d+", layout_str)]
    return sum(parts) if parts else 0.0


def get_standard_code(fmt: str, commercial: str, codec_id: str, profile: str) -> Optional[Tuple[str, str]]:
    """
    根据格式信息获取标准编码和后缀标签
    
    Args:
        fmt: 格式名称
        commercial: 商业名称
        codec_id: 编码 ID
        profile: 配置文件
        
    Returns:
        (标准编码, 后缀标签) 元组，如果无法识别则返回 None
    """
    f = fmt.upper().strip() if fmt else ""
    c = commercial.upper().strip() if commercial else ""
    cid = codec_id.upper().strip() if codec_id else ""
    p = profile.upper().strip() if profile else ""
    full_info = f"{f} {c} {cid} {p}"

    if any(k in full_info for k in ["JPEG", "PNG", "COVER", "ASS", "SSA", "S_TEXT", "TIMECODE", "MENU", "PGS"]):
        return None
    if "VIDEO" in full_info and not any(x in full_info for x in ["AUDIO", "DTS", "DOLBY", "LPCM", "AAC", "FLAC", "PCM", "OPUS", "MPEG", "AV3A", "VIVID"]):
        return None

    if "AV3A" in full_info or "AUDIO VIVID" in full_info or cid == "AV3A":
        return ("AV3A", "")
    if "DTS" in full_info:
        if "DTS:X" in full_info or "DTSX" in full_info:
            return ("DTS:X", "")
        if "MA" in p or "MASTER AUDIO" in full_info or "XLL" in full_info:
            return ("DTS-HD MA", "")
        if "HRA" in p or "HIGH RESOLUTION" in full_info:
            return ("DTS-HD HR", "")
        return ("DTS", "")
    if "TRUEHD" in full_info or "MLP" in f or "MLPA" in cid:
        return ("TrueHD", "Atmos") if "ATMOS" in full_info else ("TrueHD", "")
    if "E-AC-3" in full_info or "EC-3" in full_info or "DDP" in full_info or "DIGITAL PLUS" in full_info:
        return ("DDP", "Atmos") if ("ATMOS" in full_info or "JOC" in full_info) else ("DDP", "")
    if "AC-3" in full_info or "AC3" in full_info or "DOLBY DIGITAL" in full_info:
        return ("DD", "")
    if "LPCM" in full_info:
        return ("LPCM", "")
    if "PCM" in full_info:
        return ("PCM", "")
    if "FLAC" in full_info:
        return ("FLAC", "")
    if "APE" in full_info:
        return ("APE", "")
    if "WAV" in full_info:
        return ("WAV", "")
    if "ALAC" in full_info:
        return ("ALAC", "")
    if "DSD" in full_info:
        return ("DSD", "")
    if "AAC" in full_info or "MP4A" in cid:
        return ("AAC", "")
    if "OPUS" in full_info:
        return ("Opus", "")
    if "VORBIS" in full_info or "OGG" in full_info:
        return ("Vorbis", "")
    if "MPEG AUDIO" in full_info or "MP3" in full_info:
        return ("MP3", "")
    return None


def is_bdinfo_format(media_info: str) -> bool:
    """
    判断是否为 BDInfo 格式
    
    Args:
        media_info: MediaInfo/BDInfo 文本
        
    Returns:
        是否为 BDInfo 格式
    """
    if not media_info:
        return False
    keywords = ["DISC INFO", "PLAYLIST REPORT", "AUDIO:", "Audio:", "DISC TITLE"]
    return sum(1 for k in keywords if k.upper() in media_info.upper()) >= 2


def clean_bbcode(text: str) -> str:
    """
    清理 BBCode 标签
    
    Args:
        text: 包含 BBCode 的文本
        
    Returns:
        清理后的文本
    """
    return re.sub(r"\[/?\w+\]", "", text).strip()


def get_channel_layout_from_mediainfo(layout_line: str, count_line: str) -> str:
    """
    从 MediaInfo 获取声道布局
    
    Args:
        layout_line: 声道布局行
        count_line: 声道数量行
        
    Returns:
        声道布局字符串（如 "5.1"）
    """
    if layout_line:
        components = layout_line.strip().upper().split()
        num_components = len(components)
        return f"{num_components - 1}.1" if "LFE" in components else f"{num_components}.0"
    if count_line:
        m = re.search(r"(\d+)", count_line)
        if m:
            count = int(m.group(1))
            mapping = {8: "7.1", 6: "5.1", 2: "2.0", 1: "1.0"}
            return mapping.get(count, f"{count}.0")
    return "2.0"


def select_best_track_dynamic(track_list: List[Dict[str, Any]], total_tracks_count: int, is_mediainfo: bool) -> Optional[Dict[str, Any]]:
    """
    动态选择最佳音轨
    
    Args:
        track_list: 音轨列表
        total_tracks_count: 总音轨数
        is_mediainfo: 是否为 MediaInfo 格式
        
    Returns:
        最佳音轨信息
    """
    if not track_list:
        return None
    for track in track_list:
        tier = get_codec_tier(track["base_codec"])
        ch_count = parse_channel_count(track["channel_layout"])
        has_feature = 0 if (track["suffix_tag"] == "Atmos" or track["base_codec"] in ["AV3A", "DTS:X"]) else 1
        track["sort_key"] = (tier, -ch_count, has_feature)

        display_ch = track["channel_layout"] if track["channel_layout"] != "1.0" else ""
        parts = [track["base_codec"], display_ch, track["suffix_tag"]]
        track["display_title"] = " ".join([p for p in parts if p])

    track_list.sort(key=lambda x: x["sort_key"])
    best_track = track_list[0]

    final_parts = [best_track["display_title"]]
    if is_mediainfo and total_tracks_count > 1:
        final_parts.append(f"{total_tracks_count}Audios")
    best_track["final_title"] = " ".join(final_parts)
    return best_track


def analyze_audio_from_mediainfo(media_info: str) -> Dict[str, Any]:
    """
    从 MediaInfo 分析音频信息
    
    Args:
        media_info: MediaInfo 文本内容
        
    Returns:
        包含音频信息的字典
    """
    lines = media_info.split("\n")
    parsed_tracks = []
    title = ""

    for line in lines:
        if m := re.match(r"^\s*Complete\s+name\s*:\s*(.+?)\s*$", line, re.IGNORECASE):
            title = m.group(1).strip().split("\\")[-1].split("/")[-1]
            break

    i = 0
    while i < len(lines):
        if re.match(r"^Audio\s*(#\d+)?\s*$", lines[i].strip()):
            curr = {
                "fmt": "",
                "commercial": "",
                "codec": "",
                "profile": "",
                "ch_count_str": "",
                "ch_layout_str": "",
                "title": "",
                "section_lines": [],
            }
            j = i + 1
            while j < len(lines) and j < i + 30:
                line = lines[j]
                stripped = line.strip()
                if m := re.match(r"^\s*Format\s*:\s*(.+?)\s*$", line):
                    curr["fmt"] = m.group(1)
                elif m := re.match(r"^\s*Commercial\s+name\s*:\s*(.+?)\s*$", line):
                    curr["commercial"] = m.group(1)
                elif m := re.match(r"^\s*Codec\s+ID\s*:\s*(.+?)\s*$", line):
                    curr["codec"] = m.group(1)
                elif m := re.match(r"^\s*Format\s+profile\s*:\s*(.+?)\s*$", line):
                    curr["profile"] = m.group(1)
                elif m := re.match(r"^\s*Title\s*:\s*(.+?)\s*$", line):
                    curr["title"] = m.group(1)
                elif m := re.match(r"^\s*Channel\(s\)\s*:\s*(.+?)\s*$", line, re.IGNORECASE):
                    curr["ch_count_str"] = m.group(1)
                elif m := re.match(r"^\s*Channel\s+layout\s*:\s*(.+?)\s*$", line, re.IGNORECASE):
                    curr["ch_layout_str"] = m.group(1)

                curr["section_lines"].append(line)

                if stripped and not line.startswith((" ", "\t")):
                    if any(stripped.startswith(sec) for sec in ["Video", "Text", "Menu", "General", "Chapters", "Audio"]):
                        break
                j += 1

            ch_layout = get_channel_layout_from_mediainfo(curr["ch_layout_str"], curr["ch_count_str"])
            if not ch_layout and curr["title"]:
                if m := re.search(r"(\d+\.\d+(?:\.\d+)?)", curr["title"]):
                    ch_layout = m.group(1)

            if any([curr["fmt"], curr["commercial"], curr["codec"], curr["profile"]]):
                codec_info = get_standard_code(curr["fmt"], curr["commercial"], curr["codec"], curr["profile"])
                if codec_info:
                    base, suffix = codec_info
                    parsed_tracks.append({
                        "base_codec": base,
                        "suffix_tag": suffix,
                        "channel_layout": ch_layout,
                        "audio_section": "\n".join(curr["section_lines"]),
                        "original_fmt": curr["fmt"],
                    })
            i = j - 1
        i += 1

    best_track = select_best_track_dynamic(parsed_tracks, len(parsed_tracks), is_mediainfo=True)
    return {
        "title": title,
        "best_track": best_track,
        "total_tracks": len(parsed_tracks),
        "all_tracks": parsed_tracks,
    }


def analyze_audio_from_bdinfo(media_info: str) -> Dict[str, Any]:
    """
    从 BDInfo 分析音频信息
    
    Args:
        media_info: BDInfo 文本内容
        
    Returns:
        包含音频信息的字典
    """
    lines = media_info.split("\n")
    parsed_tracks = []
    title = ""
    for line in lines:
        if m := re.match(r"^\s*Disc\s+Label\s*:\s*(.+?)\s*$", line, re.IGNORECASE):
            title = m.group(1).strip()
            break

    audio_start = -1
    for i, line in enumerate(lines):
        clean = clean_bbcode(line).upper()
        if "AUDIO:" in clean or "* AUDIO" in clean:
            audio_start = i
            break

    if audio_start != -1:
        i = audio_start
        if clean_bbcode(lines[i]).upper() in ["AUDIO:", "AUDIO"]:
            i += 1
        while i < len(lines):
            line = lines[i]
            clean = clean_bbcode(line)
            upper = clean.upper()
            if not clean:
                i += 1
                continue
            if any(upper.startswith(s) for s in ["SUBTITLES", "FILES", "VIDEO", "DISC INFO"]):
                break
            if re.match(r"^(Codec|Language|Bitrate|Description|-+)", clean, re.IGNORECASE):
                i += 1
                continue

            raw_str = re.sub(r"^(\*|\s)*Audio:\s*", "", clean, flags=re.IGNORECASE) if "AUDIO" in upper else clean
            if raw_str:
                codec_info = get_standard_code(raw_str, "", "", "")
                ch_str = ""
                if m := re.search(r"(\d+\.\d+)", raw_str, re.IGNORECASE):
                    ch_str = m.group(1)

                if codec_info:
                    base, suffix = codec_info
                    parsed_tracks.append({
                        "base_codec": base,
                        "suffix_tag": suffix,
                        "channel_layout": ch_str or "2.0",
                        "audio_section": clean,
                        "original_fmt": raw_str,
                    })
            i += 1

    best_track = select_best_track_dynamic(parsed_tracks, len(parsed_tracks), is_mediainfo=False)
    return {
        "title": title,
        "best_track": best_track,
        "total_tracks": len(parsed_tracks),
        "all_tracks": parsed_tracks,
    }


# ================= 主要接口函数 =================

def extract_tags_from_mediainfo(mediainfo_text: str, bdinfo_text: str = None) -> Dict[str, Any]:
    """
    从 MediaInfo/BDInfo 提取简单标签
    
    Args:
        mediainfo_text: MediaInfo 文本
        bdinfo_text: BDInfo 文本（可选）
        
    Returns:
        包含简单标签的字典，字段包括：
        - resolution: 分辨率
        - video_codec: 视频编码
        - audio_codec: 音频编码
        - hdr_tag: HDR 标签
        - audio_channels: 音频声道数
    """
    result = {
        "resolution": "",
        "video_codec": "",
        "audio_codec": "",
        "hdr_tag": "",
        "audio_channels": ""
    }
    
    # 优先使用 BDInfo，否则使用 MediaInfo
    text_to_parse = bdinfo_text if bdinfo_text else mediainfo_text
    if not text_to_parse:
        return result
    
    is_bd = is_bdinfo_format(text_to_parse)
    
    # 提取 HDR 标签
    if is_bd:
        hdr_info = analyze_bdinfo_item(text_to_parse)
    else:
        hdr_info = analyze_mediainfo_item(text_to_parse)
    
    result["hdr_tag"] = hdr_info.get("standard_tag", "")
    
    # 提取音频信息
    if is_bd:
        audio_info = analyze_audio_from_bdinfo(text_to_parse)
    else:
        audio_info = analyze_audio_from_mediainfo(text_to_parse)
    
    if audio_info.get("best_track"):
        best_track = audio_info["best_track"]
        result["audio_codec"] = best_track.get("base_codec", "")
        result["audio_channels"] = best_track.get("channel_layout", "")
    
    # 提取分辨率和视频编码（从 MediaInfo）
    if not is_bd and mediainfo_text:
        lines = mediainfo_text.split("\n")
        for line in lines:
            if m := re.match(r"^\s*Width\s*:\s*(\d+)\s*pixel", line, re.IGNORECASE):
                width = m.group(1)
                if width == "3840":
                    result["resolution"] = "4K"
                elif width == "1920":
                    result["resolution"] = "1080p"
            elif m := re.match(r"^\s*Format\s*:\s*(.+?)\s*$", line):
                if "Video" in line or "VIDEO" in line:
                    video_fmt = m.group(1).strip()
                    if video_fmt.upper() not in ["AAC", "FLAC", "MP3", "OPUS"]:
                        result["video_codec"] = video_fmt
    
    return result


def extract_hdr_info_from_mediainfo(mediainfo_text: str, bdinfo_text: str = None) -> Dict[str, Any]:
    """
    从 MediaInfo/BDInfo 提取 HDR 详细信息
    
    Args:
        mediainfo_text: MediaInfo 文本
        bdinfo_text: BDInfo 文本（可选）
        
    Returns:
        包含 HDR 详细信息的字典，字段包括：
        - format: HDR 格式详细描述
        - standard_tag: 标准标签
        - match_status: 匹配状态
        - details: 详细信息字典
    """
    result = {
        "format": "",
        "standard_tag": "",
        "match_status": "",
        "details": {}
    }
    
    # 优先使用 BDInfo，否则使用 MediaInfo
    text_to_parse = bdinfo_text if bdinfo_text else mediainfo_text
    if not text_to_parse:
        return result
    
    is_bd = is_bdinfo_format(text_to_parse)
    
    if is_bd:
        hdr_info = analyze_bdinfo_item(text_to_parse)
    else:
        hdr_info = analyze_mediainfo_item(text_to_parse)
    
    result["format"] = hdr_info.get("mi_verdict", "")
    result["standard_tag"] = hdr_info.get("standard_tag", "")
    result["match_status"] = hdr_info.get("match_status", "")
    result["details"] = {
        "filename": hdr_info.get("filename", ""),
        "title_tags": hdr_info.get("title_tags", []),
        "raw_lines": hdr_info.get("raw_lines", []),
        "internal_title_general": hdr_info.get("internal_title_general", ""),
        "internal_title_video": hdr_info.get("internal_title_video", "")
    }
    
    return result


def extract_audio_info_from_mediainfo(mediainfo_text: str, bdinfo_text: str = None) -> Dict[str, Any]:
    """
    从 MediaInfo/BDInfo 提取音频详细信息
    
    Args:
        mediainfo_text: MediaInfo 文本
        bdinfo_text: BDInfo 文本（可选）
        
    Returns:
        包含音频详细信息的字典，字段包括：
        - codec: 音频编码
        - channels: 声道布局（包含音轨数，如 "5.1 4Audios"）
        - has_atmos: 是否包含 Atmos
        - details: 详细信息字典
    """
    result = {
        "codec": "",
        "channels": "",
        "has_atmos": False,
        "details": {}
    }
    
    # 优先使用 BDInfo，否则使用 MediaInfo
    text_to_parse = bdinfo_text if bdinfo_text else mediainfo_text
    if not text_to_parse:
        return result
    
    is_bd = is_bdinfo_format(text_to_parse)
    
    if is_bd:
        audio_info = analyze_audio_from_bdinfo(text_to_parse)
    else:
        audio_info = analyze_audio_from_mediainfo(text_to_parse)
    
    if audio_info.get("best_track"):
        best_track = audio_info["best_track"]
        total_tracks = audio_info.get("total_tracks", 0)
        
        # 构建channels字段，包含音轨数（当音轨数大于1时才添加音轨数标记）
        channel_layout = best_track.get("channel_layout", "")
        if total_tracks > 1:
            result["channels"] = f"{channel_layout} {total_tracks}Audios"
        else:
            result["channels"] = channel_layout
        
        result["codec"] = best_track.get("base_codec", "")
        result["has_atmos"] = best_track.get("suffix_tag") == "Atmos"
        result["details"] = {
            "title": audio_info.get("title", ""),
            "total_tracks": total_tracks,
            "all_tracks": audio_info.get("all_tracks", []),
            "final_title": best_track.get("final_title", ""),
            "display_title": best_track.get("display_title", ""),
            "sort_key": best_track.get("sort_key", (999, 0, 1))
        }
    
    return result
