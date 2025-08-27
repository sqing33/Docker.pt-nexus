# utils/media_helper.py

from pymediainfo import MediaInfo


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
