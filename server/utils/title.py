"""
标题处理模块

提供从种子标题、副标题中提取参数和标签的功能。
"""

import re
from typing import Dict, Any
from config import config_manager, GLOBAL_MAPPINGS

SEASON_EPISODE_PATTERN = re.compile(
    r"(?<!\w)(S\d{1,2}(?:(?:[-–~]\s*S?\d{1,2})?|(?:\s*E\d{1,3}(?:[-–~]\s*(?:S\d{1,2})?E?\d{1,3})*)?))(?!\w)",
    re.I,
)


def _normalize_season_episode_value(season_str: str) -> str | None:
    cleaned = re.sub(r"\s", "", season_str.upper())
    match = re.search(r"(S\d{1,2}).*?E(\d{1,3})", cleaned, re.I)
    if match:
        return f"{match.group(1).upper()}E{match.group(2)}"
    match = re.search(r"(S\d{1,2})", cleaned, re.I)
    if match:
        return match.group(1).upper()
    return None


def extract_season_episode(text: str) -> str | None:
    """
    提取季集信息，支持多集格式并返回首集（如 S01E05-06 -> S01E05）。
    """
    if not text:
        return None

    season_match = SEASON_EPISODE_PATTERN.search(text)
    if season_match:
        return _normalize_season_episode_value(season_match.group(1))

    compact_match = re.search(
        r"(?i)S\d{1,2}E\d{1,3}(?:E\d{1,3}|[-~]\s*(?:S\d{1,2})?E?\d{1,3})",
        text,
    )
    if compact_match:
        return _normalize_season_episode_value(compact_match.group(0))

    simple_match = re.search(r"(?i)S\d{1,2}E\d{1,3}", text)
    if simple_match:
        return _normalize_season_episode_value(simple_match.group(0))

    season_only_match = re.search(r"(?i)S\d{1,2}", text)
    if season_only_match:
        return season_only_match.group(0).upper()

    return None


def get_title_components_order():
    """
    从 global_mappings.yaml 读取标题组件顺序
    返回 source_key 的列表，例如：["主标题", "季集", "年份", ...]
    """
    import yaml
    import os

    with open(GLOBAL_MAPPINGS, "r", encoding="utf-8") as f:
        global_config = yaml.safe_load(f)
        default_title_components = global_config.get("default_title_components", {})

        order = []
        for key, config in default_title_components.items():
            if isinstance(config, dict) and "source_key" in config:
                order.append(config["source_key"])

        # print(f"从配置文件读取到标题拼接顺序: {order}")
        return order


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


def _find_best_matching_audio_track(source_audio: str, mediainfo_tracks: list) -> dict:
    """
    从 MediaInfo 音轨中找到与源标题音频编码最匹配的音轨

    Args:
        source_audio: 源标题的音频编码字符串（如 "DTS-HD MA 7.1"）
        mediainfo_tracks: MediaInfo 提取的所有音轨列表

    Returns:
        最匹配的音轨信息字典，如果没有匹配则返回第一个音轨
    """
    if not mediainfo_tracks:
        return {}

    # 解析源标题的音频编码
    source_codec = ""
    source_channels = ""
    source_has_atmos = False

    # 提取音频编码
    codec_match = re.search(
        r"\b(DTS-?HD\s*MA|DTS-?HD\s*HR|DTS-?HD|DTS:X|DTS:D|DTS|TrueHD|DDP|DD\+|DD|E-AC-?3|AC3|FLAC|Opus|AAC|OGG|WAV|APE|ALAC|DSD|MP3|LPCM|PCM)\b",
        source_audio,
        re.IGNORECASE,
    )
    if codec_match:
        source_codec = codec_match.group(1)

    # 提取声道数
    channel_match = re.search(r"\b(\d{1,2}\.\d)\b", source_audio)
    if channel_match:
        source_channels = channel_match.group(1)

    # 提取 Atmos 标记
    source_has_atmos = bool(re.search(r"\bAtmos\b", source_audio, re.IGNORECASE))

    print(f"[音频匹配] 源标题音频: '{source_audio}'")
    print(
        f"[音频匹配] 提取结果 - 编码: '{source_codec}', 声道: '{source_channels}', Atmos: {source_has_atmos}"
    )

    # 打印所有 MediaInfo 音轨信息
    print(f"[音频匹配] MediaInfo 音轨列表 ({len(mediainfo_tracks)} 个):")
    for idx, track in enumerate(mediainfo_tracks, 1):
        print(
            f"  音轨{idx}: 编码='{track.get('codec', '')}', 声道='{track.get('channels', '')}', Atmos={track.get('has_atmos', False)}, 音轨数='{track.get('audio_count', '')}'"
        )

    # 如果没有提取到编码，返回第一个音轨
    if not source_codec:
        print(f"[音频匹配] 未提取到编码，返回第一个音轨")
        return mediainfo_tracks[0]

    # 计算每个音轨的匹配分数
    best_track = None
    best_score = -1

    for idx, track in enumerate(mediainfo_tracks, 1):
        track_codec = track.get("codec", "")
        track_channels = track.get("channels", "")
        track_has_atmos = track.get("has_atmos", False)

        score = 0
        score_details = []

        # 1. 编码类型匹配（50分）
        if track_codec == source_codec:
            score += 50
            score_details.append(f"编码完全匹配(+50)")
        elif _is_codec_compatible(source_codec, track_codec):
            score += 30
            score_details.append(f"编码兼容(+30)")
        else:
            score_details.append(f"编码不匹配(0)")

        # 2. 声道数匹配（30分）
        if source_channels and track_channels:
            if source_channels == track_channels:
                score += 30
                score_details.append(f"声道匹配(+30)")
            else:
                # 声道数越接近，分数越高
                # 处理声道数（如 "7.1" → 7.1, "5.1.2" → 5.12）
                def parse_channels(ch_str):
                    # 移除小数点后拼接，如 "7.1" → 71, "5.1.2" → 512
                    return float(ch_str.replace(".", ""))

                source_ch_num = parse_channels(source_channels)
                track_ch_num = parse_channels(track_channels)
                diff = abs(source_ch_num - track_ch_num)
                if diff <= 1:
                    score += 20
                    score_details.append(f"声道接近(+20)")
                elif diff <= 2:
                    score += 10
                    score_details.append(f"声道较近(+10)")
                elif diff <= 4:
                    score += 5
                    score_details.append(f"声道一般(+5)")
        elif not source_channels and track_channels:
            # 如果源标题没有声道数，优先选择声道数最高的音轨
            # 声道数越高，分数越高（最多20分）
            # 处理声道数（如 "7.1" → 7.1, "5.1.2" → 5.12）
            def parse_channels(ch_str):
                # 移除小数点后拼接，如 "7.1" → 71, "5.1.2" → 512
                return float(ch_str.replace(".", ""))

            track_ch_num = parse_channels(track_channels)
            if track_ch_num >= 71:  # 7.1 或更高
                score += 20
                score_details.append(f"声道优先级高(+20, {track_channels})")
            elif track_ch_num >= 51:  # 5.1 或更高
                score += 15
                score_details.append(f"声道优先级中(+15, {track_channels})")
            elif track_ch_num >= 31:  # 3.1 或更高
                score += 10
                score_details.append(f"声道优先级低(+10, {track_channels})")
            else:  # 2.0 或更低
                score += 5
                score_details.append(f"声道优先级最低(+5, {track_channels})")
        elif not source_channels and not track_channels:
            score_details.append(f"无声道信息(0)")

        # 3. Atmos 标记匹配（20分）
        if source_has_atmos == track_has_atmos:
            score += 20
            score_details.append(f"Atmos匹配(+20)")
        else:
            score_details.append(f"Atmos不匹配(0)")

        # 打印评分详情
        print(f"  音轨{idx}评分: {score}分 - {', '.join(score_details)}")

        # 更新最佳匹配
        if score > best_score:
            best_score = score
            best_track = track

    # 如果没有找到匹配的音轨（分数为0），返回第一个音轨
    if best_score == 0:
        print(f"[音频匹配] 没有找到匹配的音轨（分数为0），返回第一个音轨")
        return mediainfo_tracks[0]

    print(
        f"[音频匹配] 最佳匹配音轨: 编码='{best_track.get('codec', '')}', 声道='{best_track.get('channels', '')}', Atmos={best_track.get('has_atmos', False)}, 音轨数='{best_track.get('audio_count', '')}', 总分={best_score}"
    )
    return best_track if best_track else mediainfo_tracks[0]


def _is_codec_compatible(codec1: str, codec2: str) -> bool:
    """
    判断两个音频编码是否兼容

    Args:
        codec1: 第一个音频编码
        codec2: 第二个音频编码

    Returns:
        是否兼容
    """

    # 标准化编码名称
    def normalize(codec):
        return re.sub(r"[-\s]", "", codec).upper()

    norm1 = normalize(codec1)
    norm2 = normalize(codec2)

    # DTS 系列兼容性
    dts_variants = ["DTS", "DTSHDMA", "DTSHDHR", "DTSHD", "DTSX", "DTS:D"]
    if any(dts in norm1 for dts in dts_variants) and any(dts in norm2 for dts in dts_variants):
        return True

    # DD 系列兼容性
    dd_variants = ["DD", "DDP", "DD+", "EAC3", "AC3"]
    if any(dd in norm1 for dd in dd_variants) and any(dd in norm2 for dd in dd_variants):
        return True

    # TrueHD 系列兼容性
    if "TRUEHD" in norm1 and "TRUEHD" in norm2:
        return True

    return False


def _supplement_audio_info(source_audio: str, mediainfo_track: dict) -> str:
    """
    使用 MediaInfo 音轨信息补充源标题音频编码缺失的信息

    Args:
        source_audio: 源标题的音频编码字符串（如 "DTS-HD MA"）
        mediainfo_track: MediaInfo 匹配的音轨信息

    Returns:
        补充后的音频编码字符串
    """
    if not mediainfo_track:
        return source_audio

    # 解析源标题的音频编码
    source_parts = {"codec": "", "channels": "", "atmos": "", "audio_count": ""}

    # 提取音频编码
    codec_match = re.search(
        r"\b(DTS-?HD\s*MA|DTS-?HD\s*HR|DTS-?HD|DTS:X|DTS:D|DTS|TrueHD|DDP|DD\+|DD|E-AC-?3|AC3|FLAC|Opus|AAC|OGG|WAV|APE|ALAC|DSD|MP3|LPCM|PCM)\b",
        source_audio,
        re.IGNORECASE,
    )
    if codec_match:
        source_parts["codec"] = codec_match.group(1)

    # 提取声道数
    channel_match = re.search(r"\b(\d{1,2}\.\d)\b", source_audio)
    if channel_match:
        source_parts["channels"] = channel_match.group(1)

    # 提取 Atmos 标记
    atmos_match = re.search(r"\b(Atmos|X)\b", source_audio, re.IGNORECASE)
    if atmos_match:
        source_parts["atmos"] = atmos_match.group(1)

    # 提取音轨数
    audio_count_match = re.search(r"\b(\d+Audios?)\b", source_audio, re.IGNORECASE)
    if audio_count_match:
        source_parts["audio_count"] = audio_count_match.group(1)

    print(
        f"[音频补充] 源标题解析结果 - 编码: '{source_parts['codec']}', 声道: '{source_parts['channels']}', Atmos: '{source_parts['atmos']}', 音轨数: '{source_parts['audio_count']}'"
    )
    print(
        f"[音频补充] MediaInfo 匹配音轨 - 编码: '{mediainfo_track.get('codec', '')}', 声道: '{mediainfo_track.get('channels', '')}', Atmos: {mediainfo_track.get('has_atmos', False)}, 音轨数: '{mediainfo_track.get('audio_count', '')}'"
    )

    # 补充缺失的信息（按顺序：声道数 → Atmos → 音轨数）

    # 1. 补充声道数
    if not source_parts["channels"] and mediainfo_track.get("channels"):
        source_parts["channels"] = mediainfo_track["channels"]
        print(f"[音频补充] ✓ 补充声道数: '{mediainfo_track['channels']}'")

    # 2. 补充 Atmos（如果源标题没有 Atmos，但 MediaInfo 有，则补充）
    if not source_parts["atmos"] and mediainfo_track.get("has_atmos"):
        source_parts["atmos"] = "Atmos"
        print(f"[音频补充] ✓ 补充 Atmos")

    # 3. 补充音轨数（如果源标题没有音轨数，但 MediaInfo 有，则补充）
    if not source_parts["audio_count"] and mediainfo_track.get("audio_count"):
        source_parts["audio_count"] = mediainfo_track["audio_count"]
        print(f"[音频补充] ✓ 补充音轨数: '{mediainfo_track['audio_count']}'")

    # 构建补充后的音频编码字符串
    # 拼接顺序：编码 → 声道 → Atmos → 音轨数
    parts = []
    if source_parts["codec"]:
        parts.append(source_parts["codec"])
    if source_parts["channels"]:
        parts.append(source_parts["channels"])
    if source_parts["atmos"]:
        parts.append(source_parts["atmos"])
    if source_parts["audio_count"]:
        parts.append(source_parts["audio_count"])

    result = " ".join(parts) if parts else source_audio
    print(f"[音频补充] 补充后结果: '{result}'")
    return result


def _apply_priority_override(
    title_components: list, mediainfo_hdr: dict = None, mediainfo_audio: dict = None
) -> list:
    """
    辅助函数：实现参数优先级逻辑，用 MediaInfo 解析结果覆盖标题解析结果。

    :param title_components: 标题组件列表
    :param mediainfo_hdr: 从 MediaInfo 解析的 HDR 信息字典
    :param mediainfo_audio: 从 MediaInfo 解析的音频信息字典
    :return: 更新后的标题组件列表
    """
    if not title_components:
        return title_components

    # 将 title_components 转换为字典以便查找和修改
    title_dict = {item.get("key"): item.get("value", "") for item in title_components}

    # 处理 HDR 格式优先级
    if mediainfo_hdr and mediainfo_hdr.get("standard_tag"):
        hdr_tag = mediainfo_hdr["standard_tag"]
        title_dict["HDR格式"] = hdr_tag
        print(f"[优先级覆盖] 使用 MediaInfo 解析的 HDR 格式: {hdr_tag}")

    # 处理音频编码优先级（智能匹配和补充）
    if mediainfo_audio:
        # 检查是否有源标题的音频编码
        source_audio = title_dict.get("音频编码", "")

        if source_audio and mediainfo_audio.get("all_tracks"):
            # 智能匹配：找到最接近的音轨
            best_track = _find_best_matching_audio_track(
                source_audio, mediainfo_audio["all_tracks"]
            )

            # 补充：使用 MediaInfo 信息补充缺失的部分
            supplemented_audio = _supplement_audio_info(source_audio, best_track)

            if supplemented_audio != source_audio:
                title_dict["音频编码"] = supplemented_audio
                print(f"[智能匹配和补充] 原音频: {source_audio} -> 补充后: {supplemented_audio}")
        elif mediainfo_audio.get("codec"):
            # 如果没有源标题音频编码，使用 MediaInfo 的最佳音轨
            audio_info = mediainfo_audio
            audio_parts = [audio_info["codec"]]

            if audio_info.get("channels"):
                audio_parts.append(audio_info["channels"])

            if audio_info.get("has_atmos"):
                audio_parts.append("Atmos")

            audio_str = " ".join(audio_parts)
            title_dict["音频编码"] = audio_str
            print(f"[优先级覆盖] 使用 MediaInfo 解析的音频编码: {audio_str}")

    # 将字典转换回列表格式
    result_components = []
    for item in title_components:
        key = item.get("key")
        if key in title_dict:
            result_components.append({"key": key, "value": title_dict[key]})

    return result_components


def extract_tags_from_title(
    title_components: list, mediainfo_hdr: dict = None, mediainfo_audio: dict = None
) -> list:
    """
    从标题参数中提取标签，主要从媒介、制作组和HDR格式字段提取标签。

    返回原始标签名称（如 "DIY", "VCB-Studio", "HDR10+"），而不是标准化键。
    这样可以被 ParameterMapper 正确映射到 global_mappings.yaml 中定义的标准化键。

    【新增】支持 MediaInfo 解析结果的优先级覆盖：
    - 如果提供 mediainfo_hdr 参数，将使用 MediaInfo 解析的 HDR 格式覆盖标题解析结果
    - 如果提供 mediainfo_audio 参数，将使用 MediaInfo 解析的音频编码覆盖标题解析结果

    :param title_components: 标题组件列表，格式为 [{"key": "主标题", "value": "..."}, ...]
    :param mediainfo_hdr: 从 MediaInfo 解析的 HDR 信息字典（可选）
    :param mediainfo_audio: 从 MediaInfo 解析的音频信息字典（可选）
    :return: 一个包含原始标签名称的列表，例如 ['DIY', 'VCB-Studio', 'HDR10+']
    """
    if not title_components:
        return []

    # 【新增】应用优先级覆盖逻辑
    if mediainfo_hdr or mediainfo_audio:
        title_components = _apply_priority_override(
            title_components, mediainfo_hdr, mediainfo_audio
        )

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
            (r"\bWEB-DL\b", "WEB-DL"),
        ],
        "制作组": [
            (r"\bDIY\b", "DIY"),
            (r"\bVCB-Studio\b", "VCB-Studio"),
            (r"\bVCB\b", "VCB-Studio"),
        ],
        "HDR格式": [
            (r"\bDolby\s+Vision\b|\bDV\b", "Dolby Vision"),
            (r"\bHDR10\+", "HDR10+"),
            (r"\bHDR10\b(?!\+)", "HDR10"),
            (r"\bHDR\b(?!10)", "HDR"),
            (r"\bSDR\b", "SDR"),
            (r"\b菁彩HDR\b", "菁彩HDR"),
            (r"\bVivid\b", "Vivid"),
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

                # 对于HDR格式字段，找到第一个匹配后就停止
                if field_name == "HDR格式":
                    break

    result_tags = list(found_tags)
    if result_tags:
        print(f"从标题参数中提取到的标签: {result_tags}")
    else:
        print("从标题参数中未提取到任何标签")

    return result_tags


def extract_tags_from_subtitle(
    subtitle: str, mediainfo_hdr: dict = None, mediainfo_audio: dict = None
) -> list:
    """
    从副标题中提取语言、字幕和特效标签。
    支持的标签：中字、粤语、国语、台配、特效

    【新增】支持 MediaInfo 解析结果的优先级覆盖（虽然副标题通常不包含 HDR 和音频信息，
    但为了保持接口一致性，仍提供这些参数）：
    - 如果提供 mediainfo_hdr 参数，可以用于后续处理
    - 如果提供 mediainfo_audio 参数，可以用于后续处理

    :param subtitle: 副标题文本
    :param mediainfo_hdr: 从 MediaInfo 解析的 HDR 信息字典（可选，预留接口）
    :param mediainfo_audio: 从 MediaInfo 解析的音频信息字典（可选，预留接口）
    :return: 标签列表，例如 ['tag.中字', 'tag.粤语', 'tag.特效']
    """
    if not subtitle:
        return []

    # 【新增】虽然副标题通常不涉及 HDR 和音频信息，但为了接口一致性保留参数
    # 这些参数可以用于未来的扩展或特殊处理
    if mediainfo_hdr:
        print(f"[调试] extract_tags_from_subtitle 收到 mediainfo_hdr 参数（副标题处理中暂不使用）")
    if mediainfo_audio:
        print(
            f"[调试] extract_tags_from_subtitle 收到 mediainfo_audio 参数（副标题处理中暂不使用）"
        )

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


def upload_data_title(
    title: str,
    torrent_filename: str = "",
    mediaInfo: str = "",
    mediainfo_hdr: Dict[str, Any] = None,
    mediainfo_audio: Dict[str, Any] = None,
):
    """
    从种子主标题中提取所有参数，并可选地从种子文件名中补充缺失参数。
    【新增】根据 MediaInfo/BDInfo 格式修正标题中的 Blu-ray/BluRay 格式
    【新增】强制将音频参数中的声道数（如 7.1, 5.1）移动到音频名称的最末尾
    【修正】修复 DTS 7.1 Atmos 等乱序格式的抓取问题
    【新增】使用 MediaInfo 提取的 HDR 和音频信息补充标题解析结果
    """
    from .mediainfo import validate_media_info_format

    # print(f"开始从主标题解析参数: {title}")
    # if mediainfo_hdr:
    #     print(f"[MediaInfo HDR] {mediainfo_hdr}")
    # if mediainfo_audio:
    #     print(f"[MediaInfo Audio] {mediainfo_audio}")

    # [新增] 根据MediaInfo/BDInfo类型修正标题中的Blu-ray/BluRay格式
    if mediaInfo and mediaInfo.strip():  # 确保不是空字符串
        # 使用验证函数判断格式
        is_mediainfo, is_bdinfo, _, _, _, _ = validate_media_info_format(mediaInfo)

        if is_mediainfo or is_bdinfo:
            print(
                # f"检测到{'MediaInfo' if is_mediainfo else 'BDInfo'}格式，开始修正标题中的Blu-ray格式..."
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

    # 匹配范围：汉字 (\u4e00-\u9fa5) + CJK标点 (\u3000-\u303f) + 全角字符/标点 (\uff00-\uffef)
    # 这可以覆盖 "黑客帝国"、"【测试】"、"（完）" 等包含中文的情况
    chinese_pattern = re.compile(r"[\u4e00-\u9fa5\u3000-\u303f\uff00-\uffef]+")

    # 查找所有中文片段
    chinese_matches = chinese_pattern.findall(original_title_str)
    if chinese_matches:
        # 将找到的中文片段合并成字符串
        chinese_text = " ".join([m.strip() for m in chinese_matches if m.strip()])
        if chinese_text:
            # 添加到未识别列表中
            unrecognized_parts.append(chinese_text)
            # print(f"[调试] 提取到中文标题: {chinese_text}")

    # 从后续处理用的 title 变量中移除中文，防止干扰正则（例如全角数字或字符）
    # 注意：这里我们使用替换后的 title 进行后续的技术参数解析
    title = chinese_pattern.sub(" ", original_title_str)

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
        # print(f"[调试] 尝试匹配制作组，标题: {title}")
        match = general_regex.match(title)
        if match:
            main_part = match.group("main_part").strip()
            release_group = match.group("release_group").strip()
            # print(f"[调试] 正则匹配成功!")
            # print(f"[调试]   - main_part: {main_part}")
            # print(f"[调试]   - release_group: {release_group}")
            # print(f"[调试] 最终制作组: {release_group}")
        else:
            release_group = ""

    # 3. 季集、年份、剪辑版本提取
    season_match = SEASON_EPISODE_PATTERN.search(main_part)
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
        r"(?<!\w)(Theatrical[\s\.]?Cut|Directors?[\s\.]?Cut|DC|Extended(?:[\s\.]?(?:Cut|Edition))?|Final[\s\.]?Cut|Anniversary[\s\.]?Edition|Restored|Remastered|Criterion[\s\.]?(?:Edition|Collection)|Ultimate[\s\.]?Cut|IMAX[\s\.]?Edition|Open[\s\.]?Matte|Unrated[\s\.]?Cut)(?!\w)",
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
        # print(f"检测到剪辑版本: {cut_version}，已拼接到年份")

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
        # 【修改】添加 DVD5/DVD9
        "medium": r"UHDTV|UHD\s*Blu-?ray|Blu-?ray\s+DIY|Blu-ray|BluRay\s+DIY|BluRay|BDrip|BD-?rip|WEB-DL|WEBrip|TVrip|DVDRip|DVD[59]|HDTV|\bUHD\b",
        # 【修改】核心修复：
        # 1. 声道匹配逻辑升级为 \d+[\.。]\d+(?:[\.。]\d+)? 以支持 7.1.4 和 5。1
        # 2. AV3A 保持在列表内
        "audio": (
            # 第一部分：音频编码
            r"(?:DTS-?HD\s*MA|DTS-?HD\s*HR|DTS-?HD|DTS-?X|DTS\s*X|DTS|"
            r"(?:Dolby\s*)?TrueHD|DDP|DD\+|DD|E-?AC-?3|AC3|"
            r"FLAC|Opus|AAC|OGG|WAV|APE|ALAC|DSD|MP3|LPCM|PCM|AV3A)"
            # 第二部分：后缀（声道、Atmos/X、音轨数）
            r"(?:"
            # 模式A: Atmos/X + 声道 (如 Atmos 7.1.4)
            r"(?:\s*(?:Atmos|X))(?:\s*\d+[\.。]\d+(?:[\.。]\d+)?)?|"
            # 模式B: 声道 + Atmos/X (如 7.1.4 Atmos, 5。1)
            r"(?:\s*\d+[\.。]\d+(?:[\.。]\d+)?)(?:\s*(?:Atmos|X))?"
            r")?"
            # 模式C: 音轨数
            r"(?:\s*\d+\s*Audios?)?"
            # 模式D: 再次允许 Atmos/X (防止顺序混乱)
            r"(?:\s*(?:Atmos|X)(?:\s*\d+[\.。]\d+(?:[\.。]\d+)?)?)?"
            r"|"
            # 第三部分：兜底匹配
            r"Atmos(?:\s*TrueHD)?(?:\s*\d+[\.。]\d+(?:[\.。]\d+)?)?|"
            r"\d+\s*Audios?|"
            r"MP2|"
            r"DUAL"
        ),
        "hdr_format": r"Dolby Vision|DoVi|HDR10\+|HDRVivid|HDR10|HLG|HDR|SDR|EDR|DV|Vivid",
        "resolution": r"\d{3,4}[pi]|4K",
        # 【修改】添加 AVS2
        "video_codec": r"HEVC|AVC|x265|H\s*[\s\.]?\s*265|x264|H\s*[\s\.]?\s*264|VC-1|AV1|VP9|AVS2|MPEG-2",
        # 【修改】添加 Amazon, HULU, AppleTV+(无空格), AMC+, Crunchyroll, HMAX, TVING
        "source_platform": r"Apple\s?TV\+|ViuTV|MyTVSuper|MyTVS|DNSP|iT|NowE|MyVideo|TWN|LiTV|TVBAnywhere|DMM|iPad|TX|iQIYI|MUBI|TVB|YOUKU|NowPlay|AMZN|Amazon|Netflix|NF|DSNP|MAX|HMAX|HULU|ATVP|iTunes|friDay|USA|EUR|JPN|CEE|FRA|LINETV|PCOK|Hami|GBR|NowPlayer|CR|Crunchyroll|SEEZN|GER|CAN|CHN|Viu|WeTV|meWATCH|CATCHPLAY|AMC\+|TVING|Baha|KKTV|IQ|HKG|ITA|ESP|Disney\+|Disney",
        "bit_depth": r"\b(?:8|10|12|16|24)bit\b",
        "framerate": r"\d{2,3}fps",
        "completion_status": r"Complete|COMPLETE",
        "video_format": r"3D|HSBS",
        "release_version": r"REMASTERED|REPACK|RERIP|PROPER|REPOST|V\d+",
        # 【修改】允许 Unrated 单独出现
        "cut_version": r"Theatrical[\s\.]?Cut|Directors?[\s\.]?Cut|DC|Extended(?:[\s\.]?(?:Cut|Edition))?|Final[\s\.]?Cut|(?:\d+th\s*)?Anniv(?:ersary)?(?:\s*Edition)?|Restored|Remastered|Criterion[\s\.]?(?:Edition|Collection)|Ultimate[\s\.]?Cut|IMAX(?:\s*Edition)?|Open[\s\.]?Matte|Unrated(?:\s*Cut)?",
        "quality_modifier": r"MAXPLUS|HQ|REMUX|MiniBD|HFR",
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
    if release_group and release_group != "":
        release_group_keywords = re.split(r"[@\-\s]+", release_group)
        release_group_keywords = [kw.strip() for kw in release_group_keywords if kw.strip()]
        # print(f"[调试] 制作组关键词列表: {release_group_keywords}")

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
            # if is_release_group_part:
            # print(f"[调试] 过滤掉制作组关键词: {val} (属于 {key})")
            if not is_release_group_part:
                filtered_values.append(val)

        all_found_tags.extend(filtered_values)
        # if filtered_values:
        # print(f"[调试] '{key}' 字段提取到技术标签: {filtered_values}")

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
                # 【新增】修复 Atmos 和声道数之间没有空格的情况，如 Atmos7.1 -> Atmos 7.1
                (r"(Atmos|X)(\d\.\d)", r"\1 \2"),
                # 【新增】修复 Audio（单数）为 Audios（复数），如 4Audio -> 4Audios
                (r"(\d+)Audio\b", r"\1Audios"),
            ]
            for pattern_rgx, replacement in audio_standardization_rules:
                processed_values = [
                    re.sub(pattern_rgx, replacement, val, flags=re.I) for val in processed_values
                ]

            # 【新增】Atmos 格式特殊处理
            # 将 "Atmos TrueHD" 调整为 "TrueHD Atmos"
            # 将 "DDP Atmos" 保持不变，将 "DTS Atmos" 调整为 "DTS:X"
            atmos_processed_values = []
            for val in processed_values:
                # 处理 Atmos TrueHD -> TrueHD Atmos
                if re.search(r"Atmos\s+TrueHD", val, re.IGNORECASE):
                    val = re.sub(r"Atmos\s+TrueHD", r"TrueHD Atmos", val, flags=re.I)
                    # print(f"[调试] 音频格式调整: Atmos TrueHD -> TrueHD Atmos")

                # 处理单独的 Atmos（通常前面应该有编码）
                elif re.search(r"\bAtmos\b(?!\s+TrueHD)", val, re.IGNORECASE):
                    # 如果 Atmos 前面是 DTS，转换为 DTS:X
                    if re.search(r"DTS.*Atmos", val, re.IGNORECASE):
                        val = re.sub(r"DTS.*Atmos", r"DTS:X", val, flags=re.I)
                        # print(f"[调试] 音频格式调整: DTS Atmos -> DTS:X")
                    # 其他情况保持 Atmos 在正确位置

                atmos_processed_values.append(val)
            processed_values = atmos_processed_values

            # 【新增核心逻辑】重新排列音频信息顺序
            # 目标顺序：编码 → 声道 → Atmos → 音轨数
            final_audio_values = []
            for val in processed_values:
                # 1. 先提取音轨数（如 4Audios）并从原字符串中移除
                audio_count_match = re.search(r"\b(\d+Audios?)\b", val, re.IGNORECASE)
                audio_count = audio_count_match.group(1) if audio_count_match else ""

                # 移除音轨数，得到剩余部分
                temp_val = val
                if audio_count:
                    temp_val = temp_val.replace(audio_count, " ")
                    temp_val = re.sub(r"\s+", " ", temp_val).strip()

                # 2. 从剩余部分提取音频编码（使用单词边界）
                codec_match = re.search(
                    r"\b(DTS-?HD\s*MA|DTS-?HD\s*HR|DTS-?HD|DTS:X|DTS:D|DTS|TrueHD|DDP|DD\+|DD|E-AC-?3|AC3|FLAC|Opus|AAC|OGG|WAV|APE|ALAC|DSD|MP3|LPCM|PCM)\b",
                    temp_val,
                    re.IGNORECASE,
                )
                codec = codec_match.group(1) if codec_match else ""

                # 3. 从剩余部分提取声道数
                channel_match = re.search(r"\b(\d{1,2}\.\d)\b", temp_val)
                channels = channel_match.group(1) if channel_match else ""

                # 4. 从剩余部分提取 Atmos 或 X（排除已经匹配到 DTS:X 的情况）
                atmos_match = None
                if codec and "DTS:X" not in codec.upper():
                    atmos_match = re.search(r"\b(Atmos|X)\b", temp_val, re.IGNORECASE)
                elif not codec:
                    atmos_match = re.search(r"\b(Atmos|X)\b", temp_val, re.IGNORECASE)
                atmos = atmos_match.group(1) if atmos_match else ""

                # 5. 按正确顺序拼接：编码 → 声道 → Atmos → 音轨数
                parts = []
                if codec:
                    parts.append(codec.strip())
                if channels:
                    parts.append(channels)
                if atmos:
                    parts.append(atmos)
                if audio_count:
                    parts.append(audio_count)

                new_val = " ".join(parts) if parts else val
                final_audio_values.append(new_val)
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

        # 3. 帧率特殊处理（统一格式化为 fps）
        elif key == "framerate":
            # 统一格式化为 fps（三个小写字母）
            processed_values = [re.sub(r"(?i)FPS", r"fps", val) for val in processed_values]

        # 4. HDR 格式特殊处理（多个格式合并为字符串）
        elif key == "hdr_format":
            # 如果有多个 HDR 格式，将它们合并为一个字符串，用空格分隔
            if len(processed_values) > 1:
                processed_values = [" ".join(processed_values)]
                # print(f"[调试] HDR 格式合并: {processed_values[0]}")
        # --- 修改结束 ---

        unique_processed = sorted(
            list(set(processed_values)), key=lambda x: title_candidate.find(x.replace(" ", ""))
        )
        if unique_processed:
            # 所有参数都使用字符串，如果有多个值则用空格连接
            if len(unique_processed) == 1:
                params[key] = unique_processed[0]
            else:
                # 【特殊处理】音频字段需要先标准化再合并
                if key == "audio":
                    # 合并所有音频标签，然后进行标准化处理
                    merged_audio = " ".join(unique_processed)
                    # 应用标准化规则（修复空格问题）
                    merged_audio = re.sub(r"(Atmos|X)(\d\.\d)", r"\1 \2", merged_audio)
                    # 【新增】修复 Audio（单数）为 Audios（复数）
                    merged_audio = re.sub(r"(\d+)Audio\b", r"\1Audios", merged_audio)
                    # print(f"[调试] {key} 多个值合并为字符串: {merged_audio}")
                    params[key] = merged_audio
                else:
                    params[key] = " ".join(unique_processed)
                    # print(f"[调试] {key} 多个值合并为字符串: {params[key]}")

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
                    # print(f"[调试] UHD 确认为媒介，与 Blu-ray 合并为: {params['medium']}")
                else:
                    # UHD 是电影名的一部分，只保留 Blu-ray
                    params["medium"] = "Blu-ray"
                    # print(f"[调试] UHD 是电影名称的一部分，只保留媒介: {params['medium']}")
                    uhd_in_title = True
            # 如果只有单独的 UHD，需要判断是否为媒介
            elif "UHD" in medium_value:
                if is_uhd_as_medium(title):
                    params["medium"] = "UHD Blu-ray"
                    # print(f"[调试] UHD 确认为媒介，补充为: {params['medium']}")
                else:
                    # UHD 不是媒介，移除它
                    params.pop("medium")
                    # print(f"[调试] UHD 是电影名称的一部分，已移除媒介字段")
                    uhd_in_title = True

        # 处理字符串形式的媒介
        elif medium_value == "UHD":
            if is_uhd_as_medium(title):
                params["medium"] = "UHD Blu-ray"
                # print(f"[调试] UHD 确认为媒介，补充为: {params['medium']}")
            else:
                # UHD 不是媒介，移除它
                params.pop("medium")
                # print(f"[调试] UHD 是电影名称的一部分，已移除媒介字段")
                uhd_in_title = True

        # 如果 UHD 是电影名的一部分，需要从已识别标签中移除 UHD
        if uhd_in_title:
            # 从 all_found_tags 中移除 UHD，这样它就不会被从技术区域清理掉
            if "UHD" in all_found_tags:
                all_found_tags.remove("UHD")
                # print(f"[调试] 从已识别标签中移除 UHD，保留在标题中")

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
                        # 【新增】修复 Atmos 和声道数之间没有空格的情况，如 Atmos7.1 -> Atmos 7.1
                        (r"(Atmos|X)(\d\.\d)", r"\1 \2"),
                        # 【新增】修复 Audio（单数）为 Audios（复数），如 4Audio -> 4Audios
                        (r"(\d+)Audio\b", r"\1Audios"),
                    ]
                    for pattern_rgx, replacement in audio_standardization_rules:
                        processed_values = [
                            re.sub(pattern_rgx, replacement, val, flags=re.I)
                            for val in processed_values
                        ]

                    # 【新增】Atmos 格式特殊处理（与主处理逻辑相同）
                    atmos_processed_values = []
                    for val in processed_values:
                        # 处理 Atmos TrueHD -> TrueHD Atmos
                        if re.search(r"Atmos\s+TrueHD", val, re.IGNORECASE):
                            val = re.sub(r"Atmos\s+TrueHD", r"TrueHD Atmos", val, flags=re.I)
                            print(f"   [文件名补充] 音频格式调整: Atmos TrueHD -> TrueHD Atmos")

                        # 处理单独的 Atmos
                        elif re.search(r"\bAtmos\b(?!\s+TrueHD)", val, re.IGNORECASE):
                            # 如果 Atmos 前面是 DTS，转换为 DTS:X
                            if re.search(r"DTS.*Atmos", val, re.IGNORECASE):
                                val = re.sub(r"DTS.*Atmos", r"DTS:X", val, flags=re.I)
                                print(f"   [文件名补充] 音频格式调整: DTS Atmos -> DTS:X")

                        atmos_processed_values.append(val)
                    processed_values = atmos_processed_values

                    # 【新增核心逻辑】重新排列音频信息顺序 (与上面相同)
                    # 目标顺序：编码 → 声道 → Atmos → 音轨数
                    final_audio_values = []
                    for val in processed_values:
                        # 1. 先提取音轨数（如 4Audios）并从原字符串中移除
                        audio_count_match = re.search(r"\b(\d+Audios?)\b", val, re.IGNORECASE)
                        audio_count = audio_count_match.group(1) if audio_count_match else ""

                        # 移除音轨数，得到剩余部分
                        temp_val = val
                        if audio_count:
                            temp_val = temp_val.replace(audio_count, " ")
                            temp_val = re.sub(r"\s+", " ", temp_val).strip()

                        # 2. 从剩余部分提取音频编码（使用单词边界）
                        codec_match = re.search(
                            r"\b(DTS-?HD\s*MA|DTS-?HD\s*HR|DTS-?HD|DTS:X|DTS:D|DTS|TrueHD|DDP|DD\+|DD|E-AC-?3|AC3|FLAC|Opus|AAC|OGG|WAV|APE|ALAC|DSD|MP3|LPCM|PCM)\b",
                            temp_val,
                            re.IGNORECASE,
                        )
                        codec = codec_match.group(1) if codec_match else ""

                        # 3. 从剩余部分提取声道数
                        channel_match = re.search(r"\b(\d{1,2}\.\d)\b", temp_val)
                        channels = channel_match.group(1) if channel_match else ""

                        # 4. 从剩余部分提取 Atmos 或 X（排除已经匹配到 DTS:X 的情况）
                        atmos_match = None
                        if codec and "DTS:X" not in codec.upper():
                            atmos_match = re.search(r"\b(Atmos|X)\b", temp_val, re.IGNORECASE)
                        elif not codec:
                            atmos_match = re.search(r"\b(Atmos|X)\b", temp_val, re.IGNORECASE)
                        atmos = atmos_match.group(1) if atmos_match else ""

                        # 5. 按正确顺序拼接：编码 → 声道 → Atmos → 音轨数
                        parts = []
                        if codec:
                            parts.append(codec.strip())
                        if channels:
                            parts.append(channels)
                        if atmos:
                            parts.append(atmos)
                        if audio_count:
                            parts.append(audio_count)

                        new_val = " ".join(parts) if parts else val
                        final_audio_values.append(new_val)
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

                elif key == "framerate":
                    # 统一格式化为 fps（三个小写字母）
                    processed_values = [
                        re.sub(r"(?i)FPS", r"fps", val) for val in processed_values
                    ]
                # --- 修改结束 ---

                unique_processed = sorted(
                    list(set(processed_values)),
                    key=lambda x: filename_candidate.find(x.replace(" ", "")),
                )

                if unique_processed:
                    print(f"   [文件名补充] 找到缺失参数 '{key}': {unique_processed}")
                    # 所有参数都使用字符串，如果有多个值则用空格连接
                    if len(unique_processed) == 1:
                        params[key] = unique_processed[0]
                    else:
                        # 【特殊处理】音频字段需要先标准化再合并
                        if key == "audio":
                            # 合并所有音频标签，然后进行标准化处理
                            merged_audio = " ".join(unique_processed)
                            # 应用标准化规则（修复空格问题）
                            merged_audio = re.sub(r"(Atmos|X)(\d\.\d)", r"\1 \2", merged_audio)
                            # 【新增】修复 Audio（单数）为 Audios（复数）
                            merged_audio = re.sub(r"(\d+)Audio\b", r"\1Audios", merged_audio)
                            print(f"   [文件名补充] {key} 多个值合并为字符串: {merged_audio}")
                            params[key] = merged_audio
                        else:
                            params[key] = " ".join(unique_processed)
                            print(f"   [文件名补充] {key} 多个值合并为字符串: {params[key]}")
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
                        # print(f"[调试] UHD 出现在标题区域且无分辨率标签，跳过")
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
                        # print(f"[调试] UHD 前面有标题冠词，可能是电影名称的一部分，跳过")
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
                        # print(f"[调试] UHD 后面发现标题性名词，可能是电影名称的一部分，跳过")
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
                    # print(f"[调试] UHD 后面发现标题性名词，可能是电影名称的一部分，跳过")
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
                    # print(f"[调试] UHD 周围发现 {tech_count} 个技术标签，确认为媒介")
                    break

            # 如果验证通过，将 UHD 补充为 UHD Blu-ray
            if is_valid_uhd_medium:
                if medium_value == "UHD":
                    params["medium"] = "UHD Blu-ray"
                # 由于现在所有参数都是字符串，不再需要处理列表情况
                # print(f"[调试] 检测到单独的 UHD 媒介，已补充为: {params['medium']}")
            else:
                print(
                    # f"[调试] UHD 出现在非技术标签区域或周围技术标签不足，保持原样: {medium_value}"
                )

    # 将制作组信息添加到最后的参数中
    params["release_info"] = release_group

    if "quality_modifier" in params:
        modifiers = params.pop("quality_modifier")
        # 确保 modifiers 是字符串形式
        if isinstance(modifiers, list):
            modifiers_str = " ".join(modifiers)
        else:
            modifiers_str = modifiers
        if "medium" in params:
            medium_str = params["medium"]  # 现在所有参数都是字符串
            params["medium"] = f"{medium_str} {modifiers_str}"

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

    # print(f"[调试] 开始清理技术区域，原始技术区: '{tech_zone}'")
    # print(f"[调试] 所有已识别标签: {all_found_tags}")

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
        # print("主标题解析失败或未通过质检。")
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

    # 从 global_mappings.yaml 读取标准标题组件顺序
    standard_order = get_title_components_order()

    # 添加额外的字段（不在 default_title_components 中）
    all_possible_keys_ordered = standard_order + ["制作组", "无法识别"]

    final_components_list = []
    for key in all_possible_keys_ordered:
        final_components_list.append({"key": key, "value": chinese_keyed_params.get(key, "")})

    # [新增] 使用 MediaInfo 提取的 HDR 和音频信息补充标题解析结果
    if mediainfo_hdr and isinstance(mediainfo_hdr, dict):
        # 补充 HDR 格式信息
        hdr_format = mediainfo_hdr.get("standard_tag", "")
        if hdr_format:
            # 检查是否已存在 HDR 格式
            existing_hdr = None
            for component in final_components_list:
                if component.get("key") == "HDR格式":
                    existing_hdr = component.get("value", "")
                    break

            # 【修改】使用 MediaInfo 的 standard_tag 覆盖标题解析的 HDR 格式
            # 这样可以确保使用 MediaInfo 提取的标准标签（如 HDR 而不是 HDR10）
            if existing_hdr:
                print(
                    # f"[MediaInfo 覆盖] 使用 MediaInfo HDR 格式: {hdr_format} (覆盖标题解析: {existing_hdr})"
                )
                for component in final_components_list:
                    if component.get("key") == "HDR格式":
                        component["value"] = hdr_format
                        break
            else:
                # print(f"[MediaInfo 补充] 添加 HDR 格式: {hdr_format}")
                for component in final_components_list:
                    if component.get("key") == "HDR格式":
                        component["value"] = hdr_format
                        break

    if mediainfo_audio and isinstance(mediainfo_audio, dict):
        # 检查是否已存在音频编码
        existing_audio = None
        for component in final_components_list:
            if component.get("key") == "音频编码":
                existing_audio = component.get("value", "")
                break

        if existing_audio and mediainfo_audio.get("all_tracks"):
            # 智能匹配：找到最接近的音轨
            best_track = _find_best_matching_audio_track(
                existing_audio, mediainfo_audio["all_tracks"]
            )

            # 补充：使用 MediaInfo 信息补充缺失的部分
            supplemented_audio = _supplement_audio_info(existing_audio, best_track)

            if supplemented_audio != existing_audio:
                print(
                    f"[MediaInfo 智能补充] 原音频: {existing_audio} -> 补充后: {supplemented_audio}"
                )
                for component in final_components_list:
                    if component.get("key") == "音频编码":
                        component["value"] = supplemented_audio
                        break
        elif mediainfo_audio.get("codec"):
            # 如果没有源标题音频编码，使用 MediaInfo 的最佳音轨
            audio_codec = mediainfo_audio.get("codec", "")
            audio_channels = mediainfo_audio.get("channels", "")
            has_atmos = mediainfo_audio.get("has_atmos", False)

            # 从 channels 字段中分离声道数和音轨数
            channel_layout = audio_channels
            audio_count = ""
            if "Audios" in audio_channels:
                parts = audio_channels.split()
                if parts:
                    channel_layout = parts[0]  # 提取声道数，如 "7.1"
                    audio_count = " ".join(parts[1:])  # 提取音轨数，如 "4Audios"

            # 构建完整的音频信息字符串
            audio_info = ""
            if audio_codec:
                audio_info = audio_codec
                if channel_layout:
                    audio_info += f" {channel_layout}"
                if has_atmos:
                    audio_info += " Atmos"
                if audio_count:
                    audio_info += f" {audio_count}"

            if audio_info:
                print(f"[MediaInfo 补充] 添加音频编码: {audio_info}")
                for component in final_components_list:
                    if component.get("key") == "音频编码":
                        component["value"] = audio_info
                        break

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

            # print(f"已根据{'MediaInfo' if is_mediainfo else 'BDInfo'}修正标题组件格式")

    # print(f"主标题解析成功。")
    return final_components_list
