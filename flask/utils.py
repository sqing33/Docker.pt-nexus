# utils.py

import re
import math
from urllib.parse import urlparse
from functools import cmp_to_key
from http.cookies import SimpleCookie
from pymediainfo import MediaInfo


def get_char_type(c):
    """Determines if a character is a letter, number, or other symbol."""
    c = c.lower()
    return 1 if "a" <= c <= "z" else 2 if "0" <= c <= "9" else 3


def custom_sort_compare(a, b):
    """Custom comparison function for sorting strings naturally (letters > numbers > symbols)."""
    na, nb = a["name"].lower(), b["name"].lower()
    l = min(len(na), len(nb))
    for i in range(l):
        ta, tb = get_char_type(na[i]), get_char_type(nb[i])
        if ta != tb:
            return ta - tb
        if na[i] != nb[i]:
            return -1 if na[i] < nb[i] else 1
    return len(na) - len(nb)


def _extract_core_domain(hostname):
    """Extracts the core part of a domain name from a full hostname."""
    if not hostname:
        return None
    hostname = re.sub(r"^(www|tracker|kp|pt|t|ipv4|ipv6|on|daydream)\.", "", hostname)
    parts = hostname.split(".")
    if len(parts) > 2 and len(parts[-2]) <= 3 and len(parts[-1]) <= 3:
        return parts[-3]
    elif len(parts) > 1:
        return parts[-2]
    else:
        return parts[0]


def _parse_hostname_from_url(url_string):
    """Safely parses a hostname from a URL string."""
    try:
        return urlparse(url_string).hostname if url_string else None
    except Exception:
        return None


def _extract_url_from_comment(comment):
    """Extracts the first URL found in a comment string."""
    if not comment or not isinstance(comment, str):
        return comment
    match = re.search(r"https?://[^\s/$.?#].[^\s]*", comment)
    if match:
        return match.group(0)
    return comment


def format_bytes(b):
    """Formats bytes into a human-readable string (KB, MB, GB, etc.)."""
    if not isinstance(b, (int, float)) or b < 0:
        return "0 B"
    if b == 0:
        return "0 B"
    s = ("B", "KB", "MB", "GB", "TB", "PB")
    i = int(math.floor(math.log(b, 1024))) if b > 0 else 0
    p = math.pow(1024, i)
    return f"{round(b/p,2)} {s[i]}"


def format_state(s):
    """Translates torrent state strings into a consistent, readable format."""
    sl = str(s).lower()
    state_map = {
        "downloading": "下载中",
        "uploading": "做种中",
        "stalledup": "做种中",
        "seed": "做种中",
        "seeding": "做种中",
        "paused": "暂停",
        "stopped": "暂停",
        "stalleddl": "暂停",
        "checking": "校验中",
        "check": "校验中",
        "error": "错误",
        "missingfiles": "文件丢失",
    }
    return next((v for k, v in state_map.items() if k in sl), str(s).capitalize())


def cookies_raw2jar(raw: str) -> dict:
    """
    使用 SimpleCookies 将原始 Cookie 字符串解析为字典，以适配 requests 库。
    """
    if not raw:
        raise ValueError("Cookie 字符串不能为空。")
    cookie = SimpleCookie(raw)
    return {key: morsel.value for key, morsel in cookie.items()}


def ensure_scheme(url: str, default_scheme: str = "https://") -> str:
    """
    智能处理 URL 字符串，如果缺少协议头则添加指定的默认协议头。
    如果 URL 已包含 http:// 或 https://，则保持不变。
    """
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return f"{default_scheme}{url.lstrip('/')}"


def upload_data_mediaInfo(mediaInfo: str):
    """
    检查 MediaInfo 格式是否符合要求。
    如果不符合，则尝试使用 MediaInfo 工具从提供的文件路径重新提取。
    """
    print("开始检查 MediaInfo 格式")

    # 1. 定义判断格式是否正确的标准
    required_sections = ["General", "Video", "Audio"]
    required_keywords = [
        "Complete name",
        "Format",
        "File size",
        "Duration",
        "Width",
        "Height",
        "Codec ID",
        "Bit rate",
        "Channel(s)",
        "Frame rate",
    ]

    # 2. 判断格式是否正确

    is_valid = all(section in mediaInfo for section in required_sections) and all(
        keyword in mediaInfo for keyword in required_keywords
    )

    if is_valid:
        print("格式符合要求，验证通过。")
        return mediaInfo

    else:
        print(
            "格式不完整或不正确，尝试使用 MediaInfo 工具从提供的文件路径重新提取 MediaInfo 格式。"
        )
        try:
            file_path = "D:/Code/Docker.pt-nexus/flask/a.mkv"
            mediainfo_dll_path = "D:/Code/Docker.pt-nexus/flask/MediaInfo/MediaInfo.dll"
            media_info = MediaInfo.parse(
                file_path, library_file=mediainfo_dll_path, output="text", full=False
            )
            return media_info
        except Exception as e:
            print(f"处理文件时出错: {e}")
            return None
