import logging
import os
import re
import subprocess
import tempfile
import requests
import yaml
from pymediainfo import MediaInfo
from config import GLOBAL_MAPPINGS
from .media_helper import _find_target_video_file, _get_downloader_proxy_config, translate_path

# 根据环境变量设置BDInfo相关路径
if os.getenv("DEV_ENV") == "true":
    # 开发环境
    BDINFO_DIR = "/home/sqing/Codes/Docker.pt-nexus-dev/server/core/bdinfo"
else:
    # 生产环境（Docker容器内）
    BDINFO_DIR = "/app/bdinfo"

# BDInfo相关路径
BDINFO_PATH = os.path.join(BDINFO_DIR, "BDInfo")
BDINFO_SUBSTRACTOR_PATH = os.path.join(BDINFO_DIR, "BDInfoDataSubstractor")


def upload_data_mediaInfo(
    mediaInfo: str,
    save_path: str,
    content_name: str = None,
    downloader_id: str = None,
    torrent_name: str = None,
    force_refresh: bool = False,
    skip_bdinfo: bool = False,
):
    """
    检查传入的文本是有效的 MediaInfo 还是 BDInfo 格式。
    如果没有 MediaInfo 或 BDInfo 则尝试从 save_path 查找视频文件提取 MediaInfo。
    【新增】支持传入 torrent_name (实际文件夹名) 或 content_name (解析后的标题) 来构建更精确的搜索路径。
    【新增】支持传入 downloader_id 来判断是否使用代理获取 MediaInfo
    【新增】支持传入 force_refresh 强制重新获取 MediaInfo，忽略已有的有效格式
    """
    print("开始检查 MediaInfo/BDInfo 格式")

    # 使用新的验证函数进行格式验证
    (
        is_mediainfo,
        is_bdinfo,
        mediainfo_required_matches,
        mediainfo_optional_matches,
        bdinfo_required_matches,
        bdinfo_optional_matches,
    ) = validate_media_info_format(mediaInfo)

    if is_mediainfo:
        if force_refresh:
            print(f"检测到标准 MediaInfo 格式，但设置了强制刷新，将重新提取。")
            # 不return，继续执行下面的提取逻辑
        else:
            print(
                f"检测到标准 MediaInfo 格式，验证通过。(必要关键字: {mediainfo_required_matches}/2, 匹配关键字数: {mediainfo_required_matches + mediainfo_optional_matches})"
            )
            return mediaInfo, True, False
    elif is_bdinfo:
        if force_refresh:
            print(f"检测到 BDInfo 格式，但设置了强制刷新，将重新提取。")
            # 不return，继续执行下面的提取逻辑
        else:
            print(
                f"检测到 BDInfo 格式，验证通过。(必要关键字: {bdinfo_required_matches}/2, 可选关键字: {bdinfo_required_matches + bdinfo_optional_matches})"
            )
            return mediaInfo, False, True
    elif not force_refresh:
        # 只有在不是强制刷新时才打印这个消息
        print("提供的文本不是有效的 MediaInfo/BDInfo，将尝试从本地文件提取。")

    # 如果执行到这里，说明需要重新提取（force_refresh=True 或者没有有效格式）
    if not save_path:
        print("错误：未提供 save_path，无法从文件提取 MediaInfo。")
        return mediaInfo, False, False

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
                json={"remote_path": remote_path, "content_name": content_name},
                timeout=300,
            )  # 5分钟超时
            response.raise_for_status()
            result = response.json()
            if result.get("success"):
                # --- [核心修改] ---
                # 如果代理返回 is_bdmv=True，说明是远程原盘
                if result.get("is_bdmv"):
                    print(f"代理检测到远程路径为蓝光原盘: {remote_path}")
                    # 返回一个特殊标记，告诉 async 函数这是原盘，但还没有内容
                    return "REMOTE_BDMV_PLACEHOLDER", False, False
                # -----------------

                print("通过代理获取 MediaInfo 成功")
                proxy_mediainfo = result.get("mediainfo", mediaInfo)
                # 处理代理返回的 MediaInfo，只保留 Complete name 中的文件名
                proxy_mediainfo = re.sub(
                    r"(Complete name\s*:\s*)(.+)",
                    lambda m: f"{m.group(1)}{os.path.basename(m.group(2).strip())}",
                    proxy_mediainfo,
                )
                return proxy_mediainfo, True, False
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
    target_video_file, is_bluray_disc = _find_target_video_file(
        path_to_search, content_name=content_name
    )

    if not target_video_file:
        print("未能在指定路径中找到合适的视频文件，提取失败。")
        return mediaInfo, False, False

    # 检查是否为原盘文件
    if is_bluray_disc:
        if skip_bdinfo:
            print("检测到原盘文件结构，但设置了跳过 BDInfo 提取")
            return mediaInfo, False, False
        else:
            print("检测到原盘文件结构 (BDMV/CERTIFICATE)，尝试使用 BDInfo 提取信息")
            return _extract_bdinfo(path_to_search)

    try:
        print(f"准备使用 MediaInfo 工具从 '{target_video_file}' 提取...")
        media_info_parsed = MediaInfo.parse(target_video_file, output="text", full=False)
        # 处理 Complete name，只保留最后一个 / 之后的内容
        media_info_str = str(media_info_parsed)
        # 使用正则表达式替换 Complete name 行中的完整路径为文件名
        media_info_str = re.sub(
            r"(Complete name\s*:\s*)(.+)",
            lambda m: f"{m.group(1)}{os.path.basename(m.group(2).strip())}",
            media_info_str,
        )
        print("从文件重新提取 MediaInfo 成功。")
        return media_info_str, True, False
    except Exception as e:
        print(f"从文件 '{target_video_file}' 处理时出错: {e}。将返回原始 mediainfo。")
        return mediaInfo, False, False


def validate_media_info_format(mediaInfo: str):
    """
    验证 MediaInfo 或 BDInfo 格式的有效性
    从 global_mappings.yaml 读取配置的关键字进行验证
    """
    # 从配置文件加载关键字配置
    try:
        with open(GLOBAL_MAPPINGS, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        mediainfo_keywords = config.get("content_filtering", {}).get("mediainfo_keywords", {})
        bdinfo_keywords = config.get("content_filtering", {}).get("bdinfo_keywords", {})
        forbidden_patterns_list = config.get("content_filtering", {}).get("forbidden_patterns", [])

        mediainfo_required = mediainfo_keywords.get("required", [])
        mediainfo_optional = mediainfo_keywords.get("optional", [])
        bdinfo_required = bdinfo_keywords.get("required", [])
        bdinfo_optional = bdinfo_keywords.get("optional", [])
    except Exception as e:
        print(f"读取配置文件失败: {e}")
        # 使用默认配置
        mediainfo_required = ["General", "Video", "Audio"]
        mediainfo_optional = ["Complete name", "File size", "Duration", "Width", "Height"]
        bdinfo_required = ["DISC INFO", "PLAYLIST REPORT"]
        bdinfo_optional = [
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
        forbidden_patterns_list = []

    # 验证 MediaInfo 格式
    mediainfo_required_matches = sum(1 for keyword in mediainfo_required if keyword in mediaInfo)
    mediainfo_optional_matches = sum(1 for keyword in mediainfo_optional if keyword in mediaInfo)
    is_mediainfo = (
        len(mediainfo_required) > 0
        and mediainfo_required_matches == len(mediainfo_required)
        and mediainfo_optional_matches >= 0
    ) or (mediainfo_required_matches >= 2 and mediainfo_optional_matches >= 1)

    # 验证 BDInfo 格式
    bdinfo_required_matches = sum(1 for keyword in bdinfo_required if keyword in mediaInfo)
    bdinfo_optional_matches = sum(1 for keyword in bdinfo_optional if keyword in mediaInfo)
    is_bdinfo = (len(bdinfo_required) > 0 and bdinfo_required_matches == len(bdinfo_required)) or (
        bdinfo_required_matches >= 1 and bdinfo_optional_matches >= 2
    )

    # 检查禁止模式（只在关键字验证通过后才检查）
    if is_mediainfo or is_bdinfo:
        for pattern_item in forbidden_patterns_list:
            pattern = pattern_item.get("pattern", "")
            if pattern:
                try:
                    if re.search(pattern, mediaInfo):
                        description = pattern_item.get("description", pattern)
                        print(f"检测到禁止模式: {description}")
                        # 如果检测到禁止模式，返回无效
                        return (False, False, 0, 0, 0, 0)
                except re.error as e:
                    print(f"正则表达式错误: {pattern}, 错误: {e}")

    return (
        is_mediainfo,
        is_bdinfo,
        mediainfo_required_matches,
        mediainfo_optional_matches,
        bdinfo_required_matches,
        bdinfo_optional_matches,
    )


def _extract_bdinfo(bluray_path: str) -> str:
    """
    使用 BDInfo 工具从蓝光原盘目录提取 BDInfo 信息

    :param bluray_path: 蓝光原盘目录路径
    :return: BDInfo 文本信息
    """
    try:
        print(f"准备使用 BDInfo 工具从 '{bluray_path}' 提取 BDInfo 信息...")

        # 检查路径是否存在
        if not os.path.exists(bluray_path):
            print(f"错误：指定的路径不存在: {bluray_path}")
            return "bdinfo提取失败：指定的路径不存在。"

        # 检查BDInfo工具是否存在
        # 根据环境变量区分开发环境和生产环境
        if os.getenv("DEV_ENV") == "true":
            # 开发环境路径
            bdinfo_path = BDINFO_PATH
        else:
            # 生产环境路径（Docker容器内）
            bdinfo_path = "/app/bdinfo/BDInfo"

        if not os.path.exists(bdinfo_path):
            print(f"错误：BDInfo工具不存在: {bdinfo_path}")
            return "bdinfo提取失败：BDInfo工具未找到。"

        # 创建临时文件存储 BDInfo 输出
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".txt", delete=False) as temp_file:
            temp_filename = temp_file.name

        try:
            # 构建 BDInfo 命令
            bdinfo_cmd = [bdinfo_path, "-p", bluray_path, "-o", temp_filename, "-m"]  # 生成摘要

            print(f"执行 BDInfo 命令: {' '.join(bdinfo_cmd)}")

            # 执行 BDInfo 命令
            result = subprocess.run(
                bdinfo_cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10分钟超时（BDInfo可能需要较长时间）
            )

            print(f"BDInfo执行完成，返回码: {result.returncode}")
            if result.stdout:
                print(f"标准输出: {result.stdout}")
            if result.stderr:
                print(f"错误输出: {result.stderr}")

            if result.returncode != 0:
                print(f"BDInfo 执行失败，返回码: {result.returncode}")
                print(f"错误输出: {result.stderr}")
                return f"bdinfo提取失败，返回码: {result.returncode}，错误: {result.stderr}"

            # 检查临时文件是否存在
            if not os.path.exists(temp_filename):
                print("BDInfo 未创建输出文件")
                return "bdinfo提取失败：BDInfo未创建输出文件。"

            # 检查临时文件的修改时间
            file_mod_time = os.path.getmtime(temp_filename)
            print(f"输出文件最后修改时间: {file_mod_time}")

            # 读取 BDInfo 输出文件
            with open(temp_filename, "r", encoding="utf-8") as f:
                bdinfo_content = f.read()

            if not bdinfo_content:
                print("BDInfo 输出为空")
                # 检查文件大小
                file_size = os.path.getsize(temp_filename)
                print(f"输出文件大小: {file_size} 字节")
                return "bdinfo提取结果为空，请手动获取。"

            print("BDInfo 提取成功")
            return bdinfo_content

        finally:
            # 清理临时文件
            if os.path.exists(temp_filename):
                os.unlink(temp_filename)

    except subprocess.TimeoutExpired:
        print("BDInfo 执行超时")
        return "bdinfo提取超时，请手动获取。"
    except Exception as e:
        print(f"BDInfo 提取过程中发生错误: {e}")
        import traceback

        traceback.print_exc()
        return f"bdinfo提取失败: {str(e)}"


def extract_tags_from_mediainfo(mediainfo_text: str) -> list:
    """
    从 MediaInfo 文本中提取关键词，并返回一个标准化的标签列表。

    :param mediainfo_text: 完整的 MediaInfo 报告字符串。
    :return: 一个包含识别出的标签字符串的列表，例如 ['tag.国语', 'tag.中字', 'tag.HDR10']。
    """
    if not mediainfo_text:
        return []

    found_tags = set()
    lines = mediainfo_text.split("\n")  # 不转小写，保持原始大小写

    # 定义关键词到标准化标签的映射
    tag_keywords_map = {
        # 语言标签
        "国语": ["国语", "mandarin"],
        "粤语": ["粤语", "cantonese"],
        "英语": ["英语", "english"],
        "日语": ["日语", "Japanese", "japanese"],
        "韩语": ["韩语", "korean"],
        "法语": ["法语", "french"],
        "德语": ["德语", "german"],
        "俄语": ["俄语", "russian"],
        "印地语": ["印地语", "hindi"],
        "西班牙语": ["西班牙语", "spanish"],
        "葡萄牙语": ["葡萄牙语", "portuguese"],
        "意大利语": ["意大利语", "italian"],
        "泰语": ["泰语", "thai"],
        "阿拉伯语": ["阿拉伯语", "arabic"],
        "外语": ["外语", "foreign"],
        # 字幕标签
        "中字": ["中字", "chinese", "简", "繁"],
        "英字": ["英字", "english"],
        # HDR 格式标签
        "Dolby Vision": ["dolby vision", "杜比视界"],
        "HDR10+": ["hdr10+"],
        "HDR": ["hdr", "hdr10"],
        "菁彩HDR": ["hdr vivid"],
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
        if line_lower.startswith("general"):
            current_section = "general"
            # 在 General Section 结束时处理之前的 Audio/Video Section
            if current_audio_section_lines:
                _process_audio_section_languages(current_audio_section_lines, found_tags)
                current_audio_section_lines = []
            if current_video_section_lines:
                _process_video_section_languages(current_video_section_lines, found_tags)
                current_video_section_lines = []
            continue
        elif line_lower.startswith("video"):
            current_section = "video"
            if current_audio_section_lines:
                _process_audio_section_languages(current_audio_section_lines, found_tags)
                current_audio_section_lines = []
            current_video_section_lines = [line_stripped]  # 开始新的 Video 块
            continue
        elif line_lower.startswith("audio"):
            # 先处理之前的 Audio 块
            if current_audio_section_lines:
                _process_audio_section_languages(current_audio_section_lines, found_tags)
            # 处理之前的 Video 块
            if current_video_section_lines:
                _process_video_section_languages(current_video_section_lines, found_tags)
                current_video_section_lines = []
            # 开始新的 Audio 块
            current_section = "audio"
            current_audio_section_lines = [line_stripped]
            continue
        elif line_lower.startswith("text"):
            current_section = "text"
            if current_audio_section_lines:
                _process_audio_section_languages(current_audio_section_lines, found_tags)
                current_audio_section_lines = []
            if current_video_section_lines:
                _process_video_section_languages(current_video_section_lines, found_tags)
                current_video_section_lines = []
            continue
        # 其他 Section 暂不处理，直接跳过或者可以定义为 'other'
        elif not line_stripped:  # 空行表示一个Section的结束，可以触发处理
            if (
                current_audio_section_lines and current_section != "audio"
            ):  # 如果是空行且之前是音频块，则处理
                _process_audio_section_languages(current_audio_section_lines, found_tags)
                current_audio_section_lines = []
            if (
                current_video_section_lines and current_section != "video"
            ):  # 如果是空行且之前是视频块，则处理
                _process_video_section_languages(current_video_section_lines, found_tags)
                current_video_section_lines = []
            current_section = None  # 重置当前section
            continue

        # 收集当前 Section 的行
        if current_section == "audio":
            current_audio_section_lines.append(line_stripped)
        elif current_section == "video":
            current_video_section_lines.append(line_stripped)
        elif current_section == "text":
            # 仅在 Text 块中检查字幕标签
            if "中字" in tag_keywords_map and any(
                kw in line_lower for kw in tag_keywords_map["中字"]
            ):
                found_tags.add("中字")
            if "英字" in tag_keywords_map and any(
                kw in line_lower for kw in tag_keywords_map["英字"]
            ):
                found_tags.add("英字")

        # 检查 HDR 格式标签 (全局检查)
        # 注意：这里保持全局检查是因为 HDR 格式可能出现在 General/Video 等多个地方
        if "dolby vision" in tag_keywords_map and any(
            kw in line_lower for kw in tag_keywords_map["Dolby Vision"]
        ):
            found_tags.add("Dolby Vision")
        if "hdr10+" in tag_keywords_map and any(
            kw in line_lower for kw in tag_keywords_map["HDR10+"]
        ):
            found_tags.add("HDR10+")
        if "hdr10" in tag_keywords_map and any(
            kw in line_lower for kw in tag_keywords_map["HDR10"]
        ):
            found_tags.add("HDR10")
        elif "hdr" in tag_keywords_map and any(kw in line_lower for kw in tag_keywords_map["HDR"]):
            if not any(hdr_tag in found_tags for hdr_tag in ["Dolby Vision", "HDR10+", "HDR10"]):
                found_tags.add("HDR")
        if "hdrvivid" in tag_keywords_map and any(
            kw in line_lower for kw in tag_keywords_map["HDRVivid"]
        ):
            found_tags.add("HDRVivid")

    # 处理文件末尾可能存在的 Audio/Video Section
    if current_audio_section_lines:
        _process_audio_section_languages(current_audio_section_lines, found_tags)
    if current_video_section_lines:
        _process_video_section_languages(current_video_section_lines, found_tags)

    # 为所有标签添加 tag. 前缀
    prefixed_tags = set()
    for tag in found_tags:
        if not tag.startswith("tag."):  # 避免重复添加 tag.
            prefixed_tags.add(f"tag.{tag}")
        else:
            prefixed_tags.add(tag)

    print(f"从 MediaInfo 中提取到的标签: {list(prefixed_tags)}")
    return list(prefixed_tags)


def _process_audio_section_languages(audio_lines, found_tags):
    """辅助函数：处理音频块中的语言检测"""
    language = _check_language_in_section(audio_lines)

    if language:
        if language == "国语":
            found_tags.add("国语")
        elif language == "粤语":
            found_tags.add("粤语")
        else:  # 其他语言
            found_tags.add(language)
            found_tags.add("外语")
        print(f"   -> 从音频块中提取到语言: {language}")


def _process_video_section_languages(video_lines, found_tags):
    """辅助函数：处理视频块中的语言检测"""
    language = _check_language_in_section(video_lines)
    if language:
        if language == "国语":
            found_tags.add("国语")
        elif language == "粤语":
            found_tags.add("粤语")
        else:  # 其他语言
            found_tags.add(language)
            found_tags.add("外语")
        print(f"   -> 从视频块中提取到语言: {language}")


def _check_language_in_section(section_lines) -> str | None:
    """
    通用函数:检查指定 Section 块中是否包含语言相关标识。

    :param section_lines: Section 块的所有行
    :return: 如果检测到语言返回具体语言名称,否则返回None
    """
    language_keywords_map = {
        "国语": ["中文", "chinese", "mandarin", "国语", "普通话", "mandrin", "cmn", "mainland"],
        "粤语": ["cantonese", "粤语", "广东话", "香港话", "canton", "hk", "hongkong"],
        "台配": [
            "台配国语",
            "台配",
            "tw",
            "taiwan",
            "twi",
            "台湾",
            "台语",
            "闽南语",
            "taiwanese",
            "taiwan mandarin",
        ],
        "英语": ["english", "英语"],
        "日语": ["japanese", "日语"],
        "韩语": ["korean", "韩语"],
        "法语": ["french", "法语"],
        "德语": ["german", "德语"],
        "俄语": ["russian", "俄语"],
        "印地语": ["hindi", "印地语"],
        "西班牙语": ["spanish", "西班牙语", "latin america"],
        "葡萄牙语": ["portuguese", "葡萄牙语", "br"],
        "意大利语": ["italian", "意大利语"],
        "泰语": ["thai", "泰语"],
        "阿拉伯语": ["arabic", "阿拉伯语", "sa"],
    }

    for line in section_lines:
        if not line:
            continue
        line_lower = line.lower()

        # 优先检查 Title: 字段（因为中文音轨常在这里标注）
        if "title" in line_lower and ":" in line_lower:
            # 提取 Title 字段的值
            title_match = re.search(r"title\s*:\s*(.+)", line_lower, re.IGNORECASE)
            if title_match:
                title_value = title_match.group(1).strip()
                # 检查 Title 值中是否包含语言关键词
                for lang, keywords in language_keywords_map.items():
                    for keyword in keywords:
                        keyword_lower = keyword.lower()
                        if keyword_lower in title_value:
                            return lang

        # 其次检查 Language: 字段
        if "language" in line_lower and ":" in line_lower:
            # 提取 Language 字段的值
            lang_match = re.search(r"language\s*:\s*(.+)", line_lower, re.IGNORECASE)
            if lang_match:
                lang_value = lang_match.group(1).strip()
                # 检查 Language 值中是否包含语言关键词
                for lang, keywords in language_keywords_map.items():
                    for keyword in keywords:
                        keyword_lower = keyword.lower()
                        if keyword_lower in lang_value:
                            return lang

    return None


def extract_resolution_from_mediainfo(mediainfo_text: str) -> str:
    """
    从 MediaInfo 文本中提取分辨率信息。

    :param mediainfo_text: 完整的 MediaInfo 报告字符串。
    :return: 分辨率信息，例如 "720p"、"1080p"、"2160p" 等
    """
    if not mediainfo_text:
        return ""

    # 查找 Video 部分
    video_section_match = re.search(r"Video[\s\S]*?(?=\n\n|\Z)", mediainfo_text)
    if not video_section_match:
        return ""

    video_section = video_section_match.group(0)

    # 查找分辨率信息
    # 匹配格式如：Width                                 : 1 920 pixels
    #            Height                                : 1 080 pixels
    # 处理带空格的数字格式，如 "1 920" -> "1920"
    width_match = re.search(r"[Ww]idth\s*:\s*(\d+)\s*(\d*)\s*pixels?", video_section)
    height_match = re.search(r"[Hh]eight\s*:\s*(\d+)\s*(\d*)\s*pixels?", video_section)

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
        resolution_match = re.search(r"(\d{3,4})\s*/\s*(\d{3,4})", video_section)
        if resolution_match:
            width = int(resolution_match.group(1))
            height = int(resolution_match.group(2))
        else:
            # 查找其他格式的分辨率信息
            other_resolution_match = re.search(r"(\d{3,4})\s*[xX]\s*(\d{3,4})", mediainfo_text)
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


def extract_audio_codec_from_mediainfo(mediainfo_text: str) -> str:
    """
    从 MediaInfo 文本中提取第一个音频流的格式。

    :param mediainfo_text: 完整的 MediaInfo 报告字符串。
    :return: 音频格式字符串 (例如 "DTS", "AC-3", "FLAC")，如果找不到则返回空字符串。
    """
    if not mediainfo_text:
        return ""

    # 查找第一个 Audio 部分 (支持 "Audio" 和 "Audio #1")
    audio_section_match = re.search(r"Audio(?: #1)?[\s\S]*?(?=\n\n|\Z)", mediainfo_text)
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


def upload_data_mediaInfo_async(
    mediaInfo: str,
    save_path: str,
    seed_id: str = None,
    content_name: str = None,
    downloader_id: str = None,
    torrent_name: str = None,
    force_refresh: bool = False,
    priority: int = 2,  # 1=单个种子高优先级, 2=批量普通优先级
    # 新增参数：预写入所需的基本信息
    hash_value: str = None,
    torrent_id: str = None,
    site_name: str = None,
    nickname: str = None,  # 站点中文名
):
    """
    异步版本的 MediaInfo/BDInfo 获取函数
    """
    print("开始异步 MediaInfo/BDInfo 处理")

    # 1. 先尝试快速获取 MediaInfo（跳过 BDInfo）
    # 这里如果远程检测到原盘，mediainfo 就会变成 "REMOTE_BDMV_PLACEHOLDER"
    mediainfo, is_mediainfo, is_bdinfo = upload_data_mediaInfo(
        mediaInfo=mediaInfo,
        save_path=save_path,
        content_name=content_name,
        downloader_id=downloader_id,
        torrent_name=torrent_name,
        force_refresh=force_refresh,
        skip_bdinfo=True,
    )

    # 2. 准备路径（无论本地还是远程都需要这个路径）
    path_to_search = ""
    if save_path:
        from .media_helper import _find_target_video_file  # 确保导入

        translated_save_path = translate_path(downloader_id, save_path)

        # 构建搜索路径
        if torrent_name:
            path_to_search = os.path.join(translated_save_path, torrent_name)
        elif content_name:
            path_to_search = os.path.join(translated_save_path, content_name)
        else:
            path_to_search = translated_save_path

    is_bluray_disc = False

    # --- [核心修改] 优先检查是否为远程原盘占位符 ---
    if mediainfo == "REMOTE_BDMV_PLACEHOLDER":
        print(f"检测到远程原盘标记，跳过本地文件查找，直接标记为原盘。路径: {path_to_search}")
        is_bluray_disc = True
        # 清空 mediainfo，因为 "REMOTE_BDMV_PLACEHOLDER" 不是有效的 mediainfo 文本，
        # 我们希望后续 BDInfo 任务完成后填入真正的内容
        mediainfo = ""
    # ---------------------------------------------
    elif path_to_search:
        # 只有不是远程原盘时，才尝试在本地查找视频文件
        target_video_file, is_bluray_disc = _find_target_video_file(
            path_to_search, content_name=content_name
        )
    # --------------------------------

    bdinfo_async_info = {
        "bdinfo_status": "skipped",
        "bdinfo_task_id": None,
        "is_bluray": is_bluray_disc,
    }

    # 3. 如果检测到是原盘且需要 BDInfo，则添加到后台队列
    if is_bluray_disc and (force_refresh or not is_bdinfo):
        if seed_id:
            try:
                # 预写入占位记录到数据库（如果提供了必要的参数）
                if hash_value:
                    try:
                        from database import DatabaseManager
                        from config import get_db_config

                        # 获取数据库配置并创建数据库管理器
                        config = get_db_config()
                        db_manager = DatabaseManager(config)

                        # 创建最小化的占位记录
                        placeholder_data = {
                            "nickname": nickname,  # 站点中文名
                            "mediainfo_status": "queued",
                            "save_path": save_path,
                            "downloader_id": downloader_id,
                        }
                        # 如果有torrent_id和正确的site_name也保存，但不作为主键
                        if torrent_id:
                            placeholder_data["torrent_id"] = torrent_id
                        # site_name应该使用英文站点名，而不是中文名
                        if site_name:
                            placeholder_data["site_name"] = site_name

                        # 先保存占位记录，仅使用hash作为主键
                        from models.seed_parameter import SeedParameter

                        seed_param = SeedParameter(db_manager)
                        # 确保传递正确的 torrent_id 和 site_name
                        actual_torrent_id = torrent_id if torrent_id else ""
                        actual_site_name = site_name if site_name else ""
                        success = seed_param.save_parameters(
                            hash_value, actual_torrent_id, actual_site_name, placeholder_data
                        )

                        if success:
                            print(f"已预写入占位记录到数据库: {hash_value}")
                        else:
                            print(f"预写入占位记录失败，但继续尝试添加 BDInfo 任务")

                    except Exception as e:
                        print(f"预写入占位记录失败: {e}，但继续尝试添加 BDInfo 任务")

                from core.bdinfo.bdinfo_manager import get_bdinfo_manager

                bdinfo_manager = get_bdinfo_manager()

                # 添加 BDInfo 任务到后台队列，使用已经构建好的完整路径
                # BDInfo管理器会自动根据downloader_id判断是否使用远程执行
                print(
                    f"[DEBUG] 准备添加 BDInfo 任务: seed_id={seed_id}, path={path_to_search}, priority={priority}, downloader_id={downloader_id}"
                )
                task_id = bdinfo_manager.add_task(seed_id, path_to_search, priority, downloader_id)

                # 获取任务信息以确定执行模式
                task_status = bdinfo_manager.get_task_status(task_id)
                execution_mode = (
                    task_status.get("execution_mode", "local") if task_status else "local"
                )

                bdinfo_async_info.update(
                    {
                        "bdinfo_status": "processing",
                        "bdinfo_task_id": task_id,
                        "execution_mode": execution_mode,
                    }
                )

                print(
                    f"BDInfo 已添加到后台队列: {task_id} (优先级: {priority}, 执行模式: {execution_mode})"
                )

                # 返回 MediaInfo，标记 BDInfo 为异步处理中，is_bdinfo设为True表示这是BDInfo任务
                return mediainfo, is_mediainfo, True, bdinfo_async_info

            except Exception as e:
                print(f"添加 BDInfo 任务失败: {e}")
                # 如果添加任务失败，继续使用同步方式
                pass

    # 4. 如果不是原盘或已有 BDInfo，直接返回
    if is_bdinfo:
        bdinfo_async_info["bdinfo_status"] = "completed"

    return mediainfo, is_mediainfo, is_bdinfo, bdinfo_async_info


def _extract_bdinfo_with_progress(bluray_path: str, task_id: str, bdinfo_manager) -> str:
    """
    使用 BDInfo 工具从蓝光原盘目录提取 BDInfo 信息，并实时更新进度
    """
    import re
    import time
    import uuid
    import sys  # 引入 sys 以便 flush stdout

    try:
        print(f"准备使用 BDInfo 工具从 '{bluray_path}' 提取 BDInfo 信息...")

        # 检查路径是否存在
        if not os.path.exists(bluray_path):
            print(f"错误：指定的路径不存在: {bluray_path}")
            return "bdinfo提取失败：指定的路径不存在。"

        # 检查BDInfo工具是否存在
        bdinfo_path = BDINFO_PATH
        if not os.path.exists(bdinfo_path):
            print(f"错误：BDInfo工具不存在: {bdinfo_path}")
            return "bdinfo提取失败：BDInfo工具未找到。"

        # 导入TEMP_DIR配置
        from config import TEMP_DIR

        # 在server/data/tmp目录下创建临时文件
        unique_id = str(uuid.uuid4())[:8]
        timestamp = int(time.time())
        temp_filename = os.path.join(TEMP_DIR, f"bdinfo_{task_id}_{unique_id}_{timestamp}.txt")

        print(f"创建临时文件: {temp_filename}")

        try:
            # 构建 BDInfo 命令
            bdinfo_cmd = [bdinfo_path, "-p", bluray_path, "-o", temp_filename, "-m"]  # 生成摘要

            print(f"执行 BDInfo 命令: {' '.join(bdinfo_cmd)}")

            # 执行 BDInfo 命令，实时捕获输出
            process = subprocess.Popen(
                bdinfo_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                universal_newlines=True,
            )

            # 将进程对象设置到任务中
            with bdinfo_manager.lock:
                task = bdinfo_manager.tasks.get(task_id)
                if task:
                    task.process = process
                    task.process_pid = process.pid
                    task.temp_file_path = temp_filename
                    print(f"[DEBUG] 设置进程对象: PID={process.pid}, 临时文件={temp_filename}")

            # 实时解析输出
            progress_pattern = re.compile(
                r"Scanning (.+?)\s+\|\s+Progress:\s+([\d.]+)%\s+\|\s+Elapsed:\s+([\d:]+)\s+\|\s+Remaining:\s+([\d:]+)"
            )
            disc_size_pattern = re.compile(r"Disc Size:\s+([\d,]+)\s+bytes")
            disc_size = 0

            # 【新增】记录上一行是否为进度条，用于控制换行
            last_line_was_progress = False

            while True:
                output = process.stdout.readline()
                if output == "" and process.poll() is not None:
                    break

                if output:
                    line = output.strip()
                    if not line:
                        continue

                    # 检查是否是进度条信息
                    match = progress_pattern.search(line)

                    if match:
                        # === 进度条处理 ===
                        # 使用 \r 回到行首，end="" 不换行，flush=True 立即输出
                        print(f"\r{line}", end="", flush=True)
                        last_line_was_progress = True

                        # 提取进度数据用于更新任务状态
                        current_file = match.group(1)
                        progress_percent = float(match.group(2))
                        elapsed_time = match.group(3)
                        remaining_time = match.group(4)

                        # 更新任务进度
                        bdinfo_manager.update_task_progress(
                            task_id,
                            progress_percent,
                            current_file,
                            elapsed_time,
                            remaining_time,
                            disc_size,
                        )

                        # 【注意】这里不再打印 [DEBUG] 进度更新 日志，否则会破坏单行显示
                        # print(f"[DEBUG] ...")

                    else:
                        # === 普通日志处理 ===
                        # 如果上一行是进度条，说明光标还在行尾，需要先换行
                        if last_line_was_progress:
                            print()
                            last_line_was_progress = False

                        # 正常打印当前行
                        print(line)

                        # 提取Disc Size (保持原有逻辑)
                        if not disc_size:
                            disc_match = disc_size_pattern.search(line)
                            if disc_match:
                                disc_size = int(disc_match.group(1).replace(",", ""))
                                print(f"[DEBUG] Disc Size: {disc_size} bytes")

            # 循环结束后的清理
            if last_line_was_progress:
                print()  # 补一个换行

            # 获取返回码
            return_code = process.poll()
            print(f"BDInfo执行完成，返回码: {return_code}")

            if return_code != 0:
                print(f"BDInfo 执行失败，返回码: {return_code}")
                return f"bdinfo提取失败，返回码: {return_code}"

            # 检查临时文件是否存在
            if not os.path.exists(temp_filename):
                print("BDInfo 未创建输出文件")
                return "bdinfo提取失败：BDInfo未创建输出文件。"

            # 检查 BDInfoDataSubstractor 工具是否存在
            substractor_path = BDINFO_SUBSTRACTOR_PATH
            if not os.path.exists(substractor_path):
                print(f"错误：BDInfoDataSubstractor工具不存在: {substractor_path}")
                return "bdinfo提取失败：BDInfoDataSubstractor工具未找到。"

            # 读取原始 BDInfo 输出文件
            with open(temp_filename, "r", encoding="utf-8") as f:
                bdinfo_content_raw = f.read()

            if not bdinfo_content_raw:
                print("BDInfo 输出为空")
                # 检查文件大小
                file_size = os.path.getsize(temp_filename)
                print(f"输出文件大小: {file_size} 字节")
                return "bdinfo提取结果为空，请手动获取。"

            try:
                # BDInfoDataSubstractor会在输入文件所在目录生成输出文件
                # 我们需要确保输出文件也保存在TEMP_DIR下
                temp_dir = os.path.dirname(temp_filename)
                temp_basename = os.path.basename(temp_filename)

                # 构建 BDInfoDataSubstractor 命令（使用绝对路径）
                substractor_cmd = [substractor_path, temp_filename]
                print(f"执行 BDInfoDataSubstractor 命令: {' '.join(substractor_cmd)}")

                # 执行命令（不需要切换工作目录）
                process = subprocess.run(
                    substractor_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    universal_newlines=True,
                )

                # 计算输出文件名
                base_without_ext = os.path.splitext(temp_basename)[0]
                bdinfo_output_filename = os.path.join(temp_dir, base_without_ext + ".bdinfo.txt")

                if process.returncode != 0:
                    print(f"BDInfoDataSubstractor 执行失败，返回码: {process.returncode}")
                    print(f"标准错误输出: {process.stderr}")
                    print("警告：BDInfoDataSubstractor 处理失败，使用原始 BDInfo 内容")
                    bdinfo_content = bdinfo_content_raw
                else:
                    if not os.path.exists(bdinfo_output_filename):
                        print(f"BDInfoDataSubstractor 未创建输出文件: {bdinfo_output_filename}")
                        bdinfo_content = bdinfo_content_raw
                    else:
                        with open(bdinfo_output_filename, "r", encoding="utf-8") as f:
                            bdinfo_content = f.read()

                        if not bdinfo_content:
                            print("警告：BDInfoDataSubstractor 输出为空，使用原始 BDInfo 内容")
                            bdinfo_content = bdinfo_content_raw
                        else:
                            # 处理多余空行
                            bdinfo_content = re.sub(r"\n{3,}", "\n\n", bdinfo_content)
                            bdinfo_content = re.sub(r":\s*\n\s*\n", ":\n", bdinfo_content)
                            bdinfo_content = bdinfo_content.strip()
                            print(
                                f"BDInfoDataSubstractor 处理成功，读取 {bdinfo_output_filename} 文件"
                            )
            except Exception as e:
                print(f"BDInfoDataSubstractor 处理异常: {e}")
                bdinfo_content = bdinfo_content_raw
            finally:
                # 清理所有相关文件
                try:
                    if os.path.exists(temp_filename):
                        os.unlink(temp_filename)
                        print(f"已清理文件: {temp_filename}")

                    temp_dir = os.path.dirname(temp_filename)
                    base_without_ext = os.path.splitext(os.path.basename(temp_filename))[0]
                    bdinfo_output_filename = os.path.join(
                        temp_dir, base_without_ext + ".bdinfo.txt"
                    )
                    quicksummary_filename = os.path.join(
                        temp_dir, base_without_ext + ".quicksummary.txt"
                    )

                    if os.path.exists(bdinfo_output_filename):
                        os.unlink(bdinfo_output_filename)
                        print(f"已清理文件: {bdinfo_output_filename}")
                    if os.path.exists(quicksummary_filename):
                        os.unlink(quicksummary_filename)
                        print(f"已清理文件: {quicksummary_filename}")
                except Exception as e:
                    print(f"清理临时文件时发生错误: {e}")

            print("BDInfo 提取成功")
            return bdinfo_content

        except subprocess.TimeoutExpired:
            print("BDInfo 执行超时")
            return "bdinfo提取失败：执行超时。"
        except Exception as e:
            print(f"BDInfo 提取异常: {e}")
            return f"bdinfo提取失败：{str(e)}"
        finally:
            # 清理临时文件
            if os.path.exists(temp_filename):
                os.unlink(temp_filename)

    except subprocess.TimeoutExpired:
        print("BDInfo 执行超时")
        return "bdinfo提取失败：执行超时。"
    except Exception as e:
        print(f"BDInfo 提取异常: {e}")
        return f"bdinfo提取失败：{str(e)}"


def check_bdinfo_task_status(task_id: str):
    """检查 BDInfo 任务状态

    Args:
        task_id: 任务ID

    Returns:
        dict: 任务状态信息
    """
    try:
        from core.bdinfo.bdinfo_manager import get_bdinfo_manager

        bdinfo_manager = get_bdinfo_manager()

        return bdinfo_manager.get_task_status(task_id)

    except Exception as e:
        print(f"检查 BDInfo 任务状态失败: {e}")
        return None


def refresh_bdinfo_for_seed(seed_id: str, save_path: str, priority: int = 1):
    """为指定种子重新获取 BDInfo

    Args:
        seed_id: 种子ID
        save_path: 保存路径
        priority: 任务优先级

    Returns:
        dict: 包含任务ID的结果
    """
    try:
        from core.bdinfo.bdinfo_manager import get_bdinfo_manager

        bdinfo_manager = get_bdinfo_manager()

        # 添加新的 BDInfo 任务
        task_id = bdinfo_manager.add_task(seed_id, save_path, priority)

        return {"success": True, "task_id": task_id, "message": "BDInfo 重新获取任务已启动"}

    except Exception as e:
        print(f"刷新 BDInfo 失败: {e}")
        return {"success": False, "error": str(e)}
