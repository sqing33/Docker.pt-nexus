#!/usr/bin/env python3
"""
TMDB API 封装模块
从 ptgen/main.py 提取的 TMDB 功能
提供一次请求获取完整信息的能力
"""

import html as html_module
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

NONE_EXIST_ERROR = "The corresponding resource does not exist."
TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_WEB_BASE = "https://www.themoviedb.org"
TMDB_IMAGE_ORIGINAL_BASE = "https://image.tmdb.org/t/p/original"
IMDB_WEB_BASE = "https://www.imdb.com"

DEFAULT_USER_AGENT = os.environ.get(
    "PT_GEN_USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36",
)


def _http_get_bytes(url: str, *, timeout: float, headers: dict[str, str] | None = None) -> bytes:
    """HTTP GET 请求，返回字节"""
    request_headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "*/*",
    }
    if headers:
        request_headers.update(headers)

    request = urllib.request.Request(url, headers=request_headers, method="GET")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        raise RuntimeError(f"HTTP {exc.code} {exc.reason} {err_body}".strip()) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(str(exc.reason) if exc.reason else str(exc)) from exc


def _http_get_text(url: str, *, timeout: float, headers: dict[str, str] | None = None) -> str:
    """HTTP GET 请求，返回文本"""
    body = _http_get_bytes(url, timeout=timeout, headers=headers)
    return body.decode("utf-8", errors="replace")


def _http_get_json(url: str, *, timeout: float, headers: dict[str, str] | None = None) -> Any:
    """HTTP GET 请求，返回 JSON"""
    request_headers = {"Accept": "application/json"}
    if headers:
        request_headers.update(headers)

    body = _http_get_bytes(url, timeout=timeout, headers=request_headers)
    try:
        return json.loads(body.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Invalid JSON response: {exc}") from exc


def _tmdb_url(
    path: str, *, api_key: str, language: str | None = None, query: dict[str, str] | None = None
) -> str:
    """构造 TMDB API URL"""
    query_params: dict[str, str] = {"api_key": api_key}
    if language:
        query_params["language"] = language
    if query:
        query_params.update(query)

    return f"{TMDB_API_BASE}{path}?{urllib.parse.urlencode(query_params)}"


def _parse_tmdb_sid(sid: str) -> tuple[str, str, str, str | None]:
    """
    解析 TMDB ID
    
    Returns: (normalized_sid, media_type, tmdb_id, error)
    """
    original_input = sid

    if sid.startswith("http"):
        try:
            parsed = urllib.parse.urlparse(sid)
            segments = [segment for segment in parsed.path.split("/") if segment]
            if len(segments) < 2:
                return original_input, "", "", "无效的 TMDB URL 格式"

            media_type = segments[0]
            id_part = segments[1]
            if "-" in id_part:
                id_part = id_part.split("-")[0]

            return f"{media_type}-{id_part}", media_type, id_part, None
        except Exception as exc:
            return original_input, "", "", f"URL 解析失败: {exc}"

    parts = sid.split("-")
    if len(parts) >= 2 and parts[0] in {"movie", "tv"}:
        media_type = parts[0]
        id_part = parts[1]
        return sid, media_type, id_part, None

    if re.fullmatch(r"\d+", sid):
        return sid, "movie", sid, None

    return (
        original_input,
        "",
        "",
        "无效的 TMDB ID 格式（支持 movie-123 / tv-456 / 纯数字 / TMDB URL）",
    )


def _jsonp_parser(response_text: str) -> Any:
    """解析 JSONP 响应"""
    try:
        response_text = response_text.replace("\n", "")
        match = re.search(r"[^\(]+\((.+)\)", response_text)
        if not match:
            return {}
        return json.loads(match.group(1))
    except Exception:
        return {}


def _normalize_rating(rating_raw: Any, votes_raw: Any) -> dict[str, Any] | None:
    """标准化评分格式"""
    if rating_raw in (None, "", 0) and votes_raw in (None, "", 0):
        return None

    rating_str = str(rating_raw)
    try:
        rating_average = float(rating_raw)
    except Exception:
        rating_average = 0.0

    try:
        votes = int(votes_raw)
    except Exception:
        try:
            votes = int(str(votes_raw).replace(",", ""))
        except Exception:
            votes = 0

    if rating_str.strip() == "":
        rating_str = str(rating_average)

    return {
        "imdb_rating_average": rating_average,
        "imdb_votes": votes,
        "imdb_rating": f"{rating_str}/10 from {votes} users",
    }


def _fetch_imdb_rating(imdb_id: str, *, timeout: float) -> dict[str, Any] | None:
    """获取 IMDb 评分"""
    imdb_id = (imdb_id or "").strip()
    if not imdb_id:
        return None

    if not imdb_id.startswith("tt"):
        imdb_id = "tt" + imdb_id.lstrip("t")

    # 优先使用 IMDb 的轻量级 JSONP 端点
    jsonp_url = (
        "https://p.media-imdb.com/static-content/documents/v1/title/"
        f"{imdb_id}/ratings%3Fjsonp=imdb.rating.run:imdb.api.title.ratings/data.json"
    )
    try:
        raw = _http_get_text(jsonp_url, timeout=timeout, headers={"Referer": IMDB_WEB_BASE + "/"})
        payload = _jsonp_parser(raw)
        resource = payload.get("resource") if isinstance(payload, dict) else None
        if isinstance(resource, dict):
            normalized = _normalize_rating(resource.get("rating"), resource.get("ratingCount"))
            if normalized:
                return normalized
    except Exception:
        pass

    # 备用方案：从标题页面解析 JSON-LD
    try:
        title_url = f"{IMDB_WEB_BASE}/title/{imdb_id}/"
        html = _http_get_text(
            title_url,
            timeout=timeout,
            headers={
                "Accept": "text/html",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": IMDB_WEB_BASE + "/",
            },
        )
        json_ld_raw = _re_group(
            r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>\s*(\{.*?\})\s*</script>',
            html,
            flags=re.S | re.I,
        )
        if not json_ld_raw:
            return None
        page_json = json.loads(json_ld_raw)
        aggregate_rating = page_json.get("aggregateRating") if isinstance(page_json, dict) else None
        if not isinstance(aggregate_rating, dict):
            return None
        return _normalize_rating(aggregate_rating.get("ratingValue"), aggregate_rating.get("ratingCount"))
    except Exception:
        return None


def _re_group(pattern: str, text: str, *, flags: int = re.S | re.I) -> str | None:
    """正则表达式提取"""
    match = re.search(pattern, text, flags)
    return match.group(1) if match else None


def gen_tmdb(sid: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    生成 TMDB BBCode 格式内容
    
    Args:
        sid: TMDB ID（movie-123 / tv-456 / 纯数字 / TMDB URL）
        config: 配置字典，包含：
            - tmdbApiKey: TMDB API Key
            - language: API 语言
            - timeout: 超时时间
            - fetch_imdb: 是否获取 IMDb 评分
    
    Returns:
        dict: 包含以下字段的字典：
            - success: 是否成功
            - format: BBCode 格式内容
            - poster: 海报 URL
            - imdb_link: IMDb 链接
            - tmdb_link: TMDB 链接
            - error: 错误信息（如果失败）
    """
    api_key = (config or {}).get("tmdbApiKey") or os.environ.get("TMDB_API_KEY") or ""
    language = (config or {}).get("language") or "zh-CN"
    timeout = float((config or {}).get("timeout") or 10.0)
    fetch_imdb = bool((config or {}).get("fetch_imdb", True))

    data: dict[str, Any] = {"site": "tmdb", "sid": sid}

    if not api_key:
        data["error"] = (
            "TMDB API key is required. Please set TMDB_API_KEY in your environment variables."
        )
        data["success"] = False
        return data

    normalized_sid, media_type, tmdb_id, parse_error = _parse_tmdb_sid(sid)
    if parse_error:
        data["error"] = parse_error
        data["success"] = False
        return data

    data["sid"] = normalized_sid
    tmdb_link = f"{TMDB_WEB_BASE}/{media_type}/{tmdb_id}"

    # 一次请求获取所有信息（包括演职员、外部ID、图片、关键词等）
    details_url = _tmdb_url(
        f"/{media_type}/{tmdb_id}",
        api_key=api_key,
        language=language,
        query={
            "append_to_response": "credits,external_ids,images,keywords,release_dates,content_ratings,videos",
        },
    )

    try:
        tmdb_json = _http_get_json(details_url, timeout=timeout)
    except Exception as exc:
        data["error"] = f"TMDB API 请求失败: {exc}"
        data["success"] = False
        return data

    if tmdb_json.get("success") is False:
        data["error"] = NONE_EXIST_ERROR
        data["success"] = False
        return data

    data["tmdb_link"] = tmdb_link
    data["title"] = tmdb_json.get("title") or tmdb_json.get("name") or ""
    data["original_title"] = (
        tmdb_json.get("original_title") or tmdb_json.get("original_name") or ""
    )

    release_date = tmdb_json.get("release_date") or ""
    first_air_date = tmdb_json.get("first_air_date") or ""
    data["year"] = (
        release_date[:4] if release_date else (first_air_date[:4] if first_air_date else "")
    ) or ""

    poster_path = tmdb_json.get("poster_path")
    if poster_path:
        data["poster"] = f"{TMDB_IMAGE_ORIGINAL_BASE}{poster_path}"

    data["tmdb_rating_average"] = tmdb_json.get("vote_average") or 0
    data["tmdb_votes"] = tmdb_json.get("vote_count") or 0
    data["tmdb_rating"] = f"{data['tmdb_rating_average']}/10 from {data['tmdb_votes']} users"

    data["genre"] = [g.get("name") for g in (tmdb_json.get("genres") or []) if g.get("name")]
    data["region"] = [
        c.get("name") for c in (tmdb_json.get("production_countries") or []) if c.get("name")
    ]
    data["playdate"] = tmdb_json.get("release_date") or tmdb_json.get("first_air_date") or ""
    data["language"] = [
        l.get("name") for l in (tmdb_json.get("spoken_languages") or []) if l.get("name")
    ]

    if media_type == "tv":
        episodes = tmdb_json.get("number_of_episodes")
        seasons = tmdb_json.get("number_of_seasons")
        data["episodes"] = str(episodes) if episodes else ""
        data["seasons"] = str(seasons) if seasons else ""

    runtime = tmdb_json.get("runtime")
    if runtime:
        data["duration"] = f"{runtime} 分钟"
    else:
        episode_run_time = tmdb_json.get("episode_run_time") or []
        data["duration"] = f"{episode_run_time[0]} 分钟" if episode_run_time else ""

    data["introduction"] = tmdb_json.get("overview") or "暂无相关剧情介绍"

    # 提取演职员信息
    credits = tmdb_json.get("credits") or {}
    if credits:
        if media_type == "movie":
            directors = [p for p in (credits.get("crew") or []) if p.get("job") == "Director"]
        else:
            directors = tmdb_json.get("created_by") or []
        data["director"] = [{"name": p.get("name")} for p in directors if p.get("name")]

        writers = [
            p
            for p in (credits.get("crew") or [])
            if p.get("job") in {"Writer", "Screenplay", "Story"} and p.get("name")
        ]
        data["writer"] = [{"name": p.get("name")} for p in writers]

        cast = credits.get("cast") or []
        data["cast"] = [{"name": p.get("name")} for p in cast[:20] if p.get("name")]

    # 提取外部 ID（IMDb）
    external_ids = tmdb_json.get("external_ids") or {}
    imdb_id = external_ids.get("imdb_id")
    if not imdb_id:
        try:
            external_ids_url = _tmdb_url(
                f"/{media_type}/{tmdb_id}/external_ids", api_key=api_key, language=None
            )
            external_ids = _http_get_json(external_ids_url, timeout=timeout)
            if isinstance(external_ids, dict):
                imdb_id = external_ids.get("imdb_id")
        except Exception:
            imdb_id = None

    if imdb_id:
        data["imdb_id"] = imdb_id
        data["imdb_link"] = f"{IMDB_WEB_BASE}/title/{imdb_id}/"
        if fetch_imdb:
            imdb_rating_info = _fetch_imdb_rating(imdb_id, timeout=timeout)
            if imdb_rating_info:
                data.update(imdb_rating_info)

    # 提取关键词
    keywords = tmdb_json.get("keywords") or {}
    keyword_list = keywords.get("keywords") or keywords.get("results") or []
    data["tags"] = [k.get("name") for k in keyword_list if k.get("name")]

    # 提取别名
    data["aka"] = []
    alt = tmdb_json.get("alternative_titles") or {}
    if alt.get("titles"):
        data["aka"] = [t.get("title") for t in (alt.get("titles") or []) if t.get("title")]

    # 获取英文/中文别名
    is_chinese_title = bool(re.search(r"[\u4e00-\u9fa5]", data["original_title"] or ""))
    if media_type == "tv" or not data["aka"]:
        alt_titles_url = _tmdb_url(
            f"/{media_type}/{tmdb_id}/alternative_titles", api_key=api_key, language=None
        )
        try:
            alt_titles_json = _http_get_json(alt_titles_url, timeout=timeout)
            titles = alt_titles_json.get("titles") or alt_titles_json.get("results") or []

            if is_chinese_title:
                english_titles = [
                    t.get("title")
                    for t in titles
                    if t.get("title")
                    and (t.get("iso_3166_1") in {"US", "GB"} or t.get("iso_639_1") == "en")
                ]
                if english_titles:
                    data["aka"] = english_titles
                else:
                    data["aka"] = [
                        t.get("title")
                        for t in titles
                        if t.get("title") and t.get("iso_3166_1") not in {"CN", "TW", "HK"}
                    ]
            else:
                chinese_titles = [
                    t.get("title")
                    for t in titles
                    if t.get("title") and t.get("iso_3166_1") in {"CN", "TW", "HK"}
                ]
                if chinese_titles:
                    data["aka"] = chinese_titles
        except Exception:
            pass

    # 生成 BBCode 格式
    descr = f"[img]{data['poster']}[/img]\n\n" if data.get("poster") else ""

    # 译名
    trans_title = ""
    if data.get("title") != data.get("original_title"):
        trans_title = data.get("title") or ""
        if data.get("aka"):
            trans_title += " / " + " / ".join(data["aka"])
        if trans_title:
            descr += f"◎译　名　{trans_title}\n"
    elif data.get("aka"):
        trans_title = " / ".join(data["aka"])
        descr += f"◎译　名　{trans_title}\n"

    # 片名
    if data.get("original_title"):
        descr += f"◎片　　名　{data['original_title']}\n"

    # 年代
    if data.get("year"):
        descr += f"◎年　　代　{data['year']}\n"

    # 产地
    if data.get("region"):
        descr += f"◎产　　地　{' / '.join(data['region'])}\n"

    # 类别
    if data.get("genre"):
        descr += f"◎类　　别　{' / '.join(data['genre'])}\n"

    # 语言
    if data.get("language"):
        descr += f"◎语　　言　{' / '.join(data['language'])}\n"

    # 上映日期
    if data.get("playdate"):
        descr += f"◎上映日期　{data['playdate']}\n"

    # TMDB 评分和链接
    descr += f"◎TMDB评分　{data['tmdb_rating']}\n"
    descr += f"◎TMDB链接　{data['tmdb_link']}\n"

    # IMDb 评分和链接
    if data.get("imdb_rating"):
        descr += f"◎IMDb评分　{data['imdb_rating']}\n"
    if data.get("imdb_link"):
        descr += f"◎IMDb链接　{data['imdb_link']}\n"

    # 剧集信息（电视剧）
    if data.get("episodes"):
        descr += f"◎集　　数　{data['episodes']}\n"
    if data.get("seasons"):
        descr += f"◎季　　数　{data['seasons']}\n"

    # 片长
    if data.get("duration"):
        descr += f"◎片　　长　{data['duration']}\n"

    # 导演
    if data.get("director"):
        descr += (
            "◎导　　演　" + " / ".join([p["name"] for p in data["director"] if p.get("name")]) + "\n"
        )

    # 编剧
    if data.get("writer"):
        descr += (
            "◎编　　剧　" + " / ".join([p["name"] for p in data["writer"] if p.get("name")]) + "\n"
        )

    # 主演
    if data.get("cast"):
        names = [p["name"] for p in data["cast"] if p.get("name")]
        if names:
            descr += "◎主　　演　" + ("\n" + (" " * 4) + " ").join(names).strip() + "\n"

    # 标签
    if data.get("tags"):
        descr += "\n◎标　　签　" + " | ".join([t for t in data["tags"] if t]) + "\n"

    # 简介
    if data.get("introduction"):
        intro = str(data["introduction"]).replace("\n", "\n" + (" " * 2))
        descr += f"\n◎简　　介\n\n {intro}\n"

    data["format"] = descr.strip()
    data["success"] = True
    return data


def get_tmdb_info(sid: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    获取 TMDB 信息的对外接口
    
    Args:
        sid: TMDB ID（movie-123 / tv-456 / 纯数字 / TMDB URL）
        config: 配置字典，包含：
            - tmdbApiKey: TMDB API Key
            - language: API 语言（可选，默认 zh-CN）
            - timeout: 超时时间（可选，默认 10.0）
            - fetch_imdb: 是否获取 IMDb 评分（可选，默认 True）
    
    Returns:
        dict: 包含以下字段的字典：
            - success: 是否成功
            - format: BBCode 格式内容
            - poster: 海报 URL
            - imdb_link: IMDb 链接
            - tmdb_link: TMDB 链接
            - title: 标题
            - original_title: 原始标题
            - year: 年代
            - genre: 类别列表
            - region: 产地列表
            - language: 语言列表
            - playdate: 上映日期
            - tmdb_rating: TMDB 评分
            - imdb_rating: IMDb 评分（如果获取成功）
            - director: 导演列表
            - writer: 编剧列表
            - cast: 主演列表
            - tags: 标签列表
            - introduction: 简介
            - error: 错误信息（如果失败）
    """
    return gen_tmdb(sid, config)