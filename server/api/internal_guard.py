import logging
import os
from typing import Tuple

import requests

_GO_SERVICE_URL = os.getenv("GO_SERVICE_URL", "http://localhost:5276")
_GUARD_ENDPOINT = f"{_GO_SERVICE_URL}/seeding-limit/check"
_REQUEST_TIMEOUT = 15


def check_downloader_gate(downloader_id: str, *_args, **_kwargs) -> Tuple[bool, str]:
    if not downloader_id:
        return True, ""

    try:
        response = requests.post(
            _GUARD_ENDPOINT,
            json={"downloader_id": downloader_id},
            timeout=_REQUEST_TIMEOUT,
        )
    except Exception as exc:
        logging.warning(f"内部校验请求失败: {exc}")
        return True, ""

    if response.status_code != 200:
        logging.warning(f"内部校验失败(HTTP {response.status_code}): {response.text[:200]}")
        return True, ""

    try:
        payload = response.json()
    except ValueError as exc:
        logging.warning(f"内部校验响应解析失败: {exc}")
        return True, ""

    if not payload.get("success", False):
        logging.warning(f"内部校验返回失败: {payload.get('error', 'unknown error')}")
        return True, ""

    return bool(payload.get("can_continue", True)), payload.get("message", "")
