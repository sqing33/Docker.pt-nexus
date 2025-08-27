# utils/formatters.py

import re
import math
from urllib.parse import urlparse
from functools import cmp_to_key
from http.cookies import SimpleCookie


def get_char_type(c):
    """判断字符是字母、数字还是其他符号。"""
    c = c.lower()
    if "a" <= c <= "z":
        return 1
    if "0" <= c <= "9":
        return 2
    return 3


def custom_sort_compare(a, b):
    """
    自定义的字符串自然排序比较函数 (字母 > 数字 > 符号)。
    用于对种子名称等进行更符合人类直觉的排序。
    """
    na, nb = a["name"].lower(), b["name"].lower()
    min_len = min(len(na), len(nb))
    for i in range(min_len):
        type_a, type_b = get_char_type(na[i]), get_char_type(nb[i])
        if type_a != type_b:
            return type_a - type_b  # 类型不同时，按 字母 > 数字 > 符号 排序
        if na[i] != nb[i]:
            return -1 if na[i] < nb[i] else 1
    return len(na) - len(nb)


def _extract_core_domain(hostname):
    """从完整主机名中提取核心域名部分。"""
    if not hostname:
        return None
    # 移除常见的前缀
    hostname = re.sub(r"^(www|tracker|kp|pt|t|ipv4|ipv6|on|daydream)\.", "", hostname)
    parts = hostname.split(".")
    # 处理如 .co.uk, .com.cn 等双后缀域名
    if len(parts) > 2 and len(parts[-2]) <= 3 and len(parts[-1]) <= 3:
        return parts[-3]
    if len(parts) > 1:
        return parts[-2]
    return parts[0]


def _parse_hostname_from_url(url_string):
    """安全地从 URL 字符串中解析出主机名。"""
    try:
        return urlparse(url_string).hostname if url_string else None
    except Exception:
        return None


def _extract_url_from_comment(comment):
    """从注释字符串中提取找到的第一个 URL。"""
    if not isinstance(comment, str):
        return comment
    match = re.search(r"https?://[^\s/$.?#].[^\s]*", comment)
    return match.group(0) if match else comment


def format_bytes(b):
    """将字节数格式化为人类可读的字符串 (KB, MB, GB 等)。"""
    if not isinstance(b, (int, float)) or b <= 0:
        return "0 B"
    sizes = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(b, 1024)))
    return f"{round(b / math.pow(1024, i), 2)} {sizes[i]}"


def format_state(s):
    """将不同下载客户端的种子状态翻译为统一的、可读的格式。"""
    state_lower = str(s).lower()
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
        "moving": "移动中",
        "allocating": "分配空间",
    }
    # 查找第一个匹配的关键字
    for key, value in state_map.items():
        if key in state_lower:
            return value
    # 如果没有匹配的，返回首字母大写的原始状态
    return str(s).capitalize()


def cookies_raw2jar(raw: str) -> dict:
    """使用 SimpleCookie 将原始 Cookie 字符串解析为字典，以适配 requests 库。"""
    if not raw:
        raise ValueError("Cookie 字符串不能为空。")
    cookie = SimpleCookie()
    cookie.load(raw)
    return {key: morsel.value for key, morsel in cookie.items()}


def ensure_scheme(url: str, default_scheme: str = "https://") -> str:
    """确保 URL 字符串包含协议头 (http:// 或 https://)。"""
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    return f"{default_scheme}{url.lstrip('/')}"
