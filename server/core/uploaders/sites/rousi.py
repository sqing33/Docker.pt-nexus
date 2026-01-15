import base64
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from loguru import logger

from ..uploader import SpecialUploader
from utils import ensure_scheme


class RousiUploader(SpecialUploader):
    """
    Rousi 站点上传器（API v1 模式）

    通过 `POST /api/v1/torrents` 上传新种子，使用站点 `passkey` 作为 Bearer Token。
    """

    def __init__(self, site_name: str, site_info: dict, upload_data: dict):
        super().__init__(site_name, site_info, upload_data)

        self.base_url = ensure_scheme(self.site_info.get("base_url") or "")
        self.post_url = f"{self.base_url}/api/v1/torrents"
        self.timeout = 120

        self.session = requests.Session()
        self.session.headers.update(
            {
                "accept": "application/json",
                "content-type": "application/json",
                "origin": self.base_url,
                "referer": f"{self.base_url}/",
                "user-agent": self.site_info.get("user_agent")
                or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }
        )

        passkey = (self.site_info.get("passkey") or "").strip()
        if not passkey:
            logger.warning("RousiUploader: 站点未配置 passkey，API v1 上传会失败")
        else:
            self.session.headers.update({"authorization": f"Bearer {passkey}"})

        self._temp_image_work_dirs: List[str] = []

    def _map_parameters(self) -> dict:
        """
        实现Rousi站点的参数映射逻辑

        Rousi 是 API JSON 上传（非表单字段）。
        这里需要输出“API payload 会读取的键”，而不是通用表单 uploader 的 form_fields 键。

        - type -> payload.category（在 _build_api_payload 里使用）
        - region/resolution/source -> payload.attributes（在 _build_api_payload 里写入）
        """
        standardized_params = self.upload_data.get("standardized_params") or {}
        if not standardized_params:
            logger.warning("未找到标准化参数，回退到重新解析")
            standardized_params = self._parse_source_data()

        mapped: Dict[str, Any] = {}

        # type：标准键 -> 站点需要的 category/type
        content_type = standardized_params.get("type") or ""
        mapped["type"] = self._find_mapping(
            self.mappings.get("type", {}),
            content_type,
            mapping_type="type",
        )

        # resolution：标准键 -> 站点显示值
        resolution_key = standardized_params.get("resolution") or ""
        mapped["resolution"] = self._find_mapping(
            self.mappings.get("resolution", {}),
            resolution_key,
            mapping_type="resolution",
        )

        # source：API attributes.source 约定为“媒介/片源”（从 standardized_params.medium 来）
        medium_key = standardized_params.get("medium") or ""
        mapped["source"] = self._find_mapping(
            self.mappings.get("source", {}),
            medium_key,
            mapping_type="medium",
        )

        # region：优先 region；兼容旧流程里“产地”落到 standardized_params.source
        region_key = standardized_params.get("region") or standardized_params.get("source") or ""
        mapped["region"] = self._find_mapping(
            self.mappings.get("region", {}),
            region_key,
            mapping_type="source",
        )

        return mapped

    def _read_torrent_base64(self) -> str:
        torrent_value = self.upload_data.get("torrent")
        if isinstance(torrent_value, str) and torrent_value.strip():
            return torrent_value.strip()

        torrent_path = self.upload_data.get("modified_torrent_path")
        if not torrent_path or not os.path.exists(torrent_path):
            raise FileNotFoundError("种子文件路径不存在，无法构造 API 上传参数")

        with open(torrent_path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")

    @staticmethod
    def _normalize_category(category_value: Any) -> Optional[str]:
        if not category_value:
            return None

        value = str(category_value).strip()
        if not value:
            return None

        if value.startswith("category."):
            return value.split(".", 1)[1].strip() or None

        lowered = value.lower()
        if "movie" in lowered or "电影" in value:
            return "movie"
        if "tv" in lowered or "电视剧" in value or "剧集" in value:
            return "tv"
        if "animation" in lowered or "anime" in lowered or "动漫" in value:
            return "animation"
        if "music" in lowered or "音乐" in value:
            return "music"
        if "game" in lowered or "游戏" in value:
            return "game"
        if "book" in lowered or "电子书" in value:
            return "book"

        return value

    @staticmethod
    def _sanitize_markdown_no_images(text: str) -> str:
        if not text:
            return ""

        cleaned = text
        cleaned = re.sub(r"\[img[^\]]*\].*?\[/img\]", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r"<img[^>]*>", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", cleaned)

        # 删除“单独一行的图片链接”，避免触发图片链接禁令
        lines: List[str] = []
        image_url_re = re.compile(r"https?://\S+\.(?:png|jpe?g|gif|webp)\S*", re.IGNORECASE)
        for line in cleaned.splitlines():
            stripped = line.strip()
            if stripped and image_url_re.fullmatch(stripped):
                continue
            lines.append(line)

        return "\n".join(lines).strip()

    @staticmethod
    def _bbcode_to_markdown(text: str) -> str:
        """
        将常见 BBCode 转为 Markdown（不使用 HTML）。
        - [b]/[i] -> **/** 与 * *
        - [url] / [url=] -> Markdown 链接
        - [color=] / [size=] -> 仅保留文本（丢弃样式）
        - [quote] -> Markdown 引用块 `>`（每行加前缀，避免 HTML <br>）
        - [list][*] -> Markdown 列表
        - [code] -> ``` 代码块
        其余未识别 BBCode 标签会被尽量剥离（保留文本）。
        """
        if not text:
            return ""

        # 统一换行
        source = text.replace("\r\n", "\n").replace("\r", "\n")

        def _convert_inline(s: str) -> str:
            out = s

            # code（先处理）
            out = re.sub(
                r"\[code\](.*?)\[/code\]",
                lambda m: f"\n```\n{(m.group(1) or '').strip('\\n')}\n```\n",
                out,
                flags=re.IGNORECASE | re.DOTALL,
            )

            # url
            out = re.sub(
                r"\[url=(.*?)\](.*?)\[/url\]",
                lambda m: f"[{(m.group(2) or '').strip()}]({(m.group(1) or '').strip()})",
                out,
                flags=re.IGNORECASE | re.DOTALL,
            )
            out = re.sub(
                r"\[url\](.*?)\[/url\]",
                lambda m: f"[{(m.group(1) or '').strip()}]({(m.group(1) or '').strip()})",
                out,
                flags=re.IGNORECASE | re.DOTALL,
            )

            # color / size：只保留文本
            out = re.sub(
                r"\[color=([^\]]+)\](.*?)\[/color\]",
                lambda m: m.group(2),
                out,
                flags=re.IGNORECASE | re.DOTALL,
            )
            out = re.sub(
                r"\[size=([^\]]+)\](.*?)\[/size\]",
                lambda m: m.group(2),
                out,
                flags=re.IGNORECASE | re.DOTALL,
            )

            # b / i / u
            out = re.sub(r"\[b\](.*?)\[/b\]", r"**\1**", out, flags=re.IGNORECASE | re.DOTALL)
            out = re.sub(r"\[i\](.*?)\[/i\]", r"*\1*", out, flags=re.IGNORECASE | re.DOTALL)
            out = re.sub(r"\[u\](.*?)\[/u\]", r"\1", out, flags=re.IGNORECASE | re.DOTALL)

            # list
            out = re.sub(r"\[list\]", "", out, flags=re.IGNORECASE)
            out = re.sub(r"\[/list\]", "", out, flags=re.IGNORECASE)
            out = re.sub(r"\[\*\]", "- ", out)

            # 兜底：移除未识别 BBCode 标签
            # 注意：不要误删 Markdown 链接的 `[text](url)` 里的 `[text]`
            # 因此当 `]` 后面紧跟 `(` 时，视为 Markdown 链接的一部分，跳过剥离。
            out = re.sub(r"\[/?[a-zA-Z0-9]+[^\]]*\](?!\()", "", out)
            return out

        # 将 [quote] 转为 Markdown blockquote（每个 quote 块一段），quote 内每行加前缀 `> `
        parts: List[str] = []
        last_end = 0
        for match in re.finditer(r"\[quote\](.*?)\[/quote\]", source, flags=re.IGNORECASE | re.DOTALL):
            before = source[last_end : match.start()]
            if before.strip():
                parts.append(_convert_inline(before).strip())

            quote_body = (match.group(1) or "").strip("\n")
            quote_converted = _convert_inline(quote_body).strip()
            quote_lines = quote_converted.split("\n")
            quote_lines = [f"> {line}".rstrip() for line in quote_lines]
            parts.append("\n".join(quote_lines).rstrip())

            last_end = match.end()

        tail = source[last_end:]
        if tail.strip():
            parts.append(_convert_inline(tail).strip())

        out = "\n\n".join([p for p in parts if p])
        out = re.sub(r"\n{3,}", "\n\n", out).strip()
        return out

    @staticmethod
    def _remove_explicit_image_urls(text: str, image_urls: List[str]) -> str:
        if not text or not image_urls:
            return text

        cleaned = text
        for url in image_urls:
            if not url:
                continue
            cleaned = cleaned.replace(url, "")

        # 清理多余空行
        cleaned_lines = [line.rstrip() for line in cleaned.splitlines()]
        while cleaned_lines and not cleaned_lines[0].strip():
            cleaned_lines.pop(0)
        while cleaned_lines and not cleaned_lines[-1].strip():
            cleaned_lines.pop()
        return "\n".join(cleaned_lines).strip()

    def _build_description_markdown(self) -> str:
        # 强制过滤海报/截图的链接（即使 description 里意外包含）
        intro = self.upload_data.get("intro") or {}
        poster_screenshot_urls: List[str] = []
        if isinstance(intro, dict):
            poster_screenshot_urls.extend(
                [i["url"] for i in self._extract_image_sources_from_text(str(intro.get("poster") or ""))]
            )
            poster_screenshot_urls.extend(
                [
                    i["url"]
                    for i in self._extract_image_sources_from_text(str(intro.get("screenshots") or ""))
                ]
            )

        description_value = self.upload_data.get("description")
        if isinstance(description_value, str) and description_value.strip():
            converted = self._bbcode_to_markdown(description_value)
            sanitized = self._sanitize_markdown_no_images(converted)
            return self._remove_explicit_image_urls(sanitized, poster_screenshot_urls)

        if isinstance(intro, dict):
            statement = (intro.get("statement") or "").strip()
            body = (intro.get("body") or "").strip()
            text = "\n\n".join([p for p in [statement, body] if p])
            converted = self._bbcode_to_markdown(text)
            sanitized = self._sanitize_markdown_no_images(converted)
            return self._remove_explicit_image_urls(sanitized, poster_screenshot_urls)

        return ""

    @staticmethod
    def _is_probable_image_url(url: str) -> bool:
        u = (url or "").lower()
        if not u.startswith(("http://", "https://")):
            return False
        if re.search(r"\.(png|jpe?g|gif|webp)(\?.*)?$", u):
            return True
        # pixhost 常见直链路径
        if "pixhost.to" in u and ("/images/" in u or "/thumbs/" in u):
            return True
        return False

    @staticmethod
    def _extract_image_sources_from_text(text: str) -> List[Dict[str, str]]:
        if not text:
            return []

        items: List[Dict[str, str]] = []

        # BBCode: [url=PAGE][img]IMG[/img][/url] -> 使用 IMG 直链，但带上 referer=PAGE
        for match in re.finditer(
            r"\[url=([^\]]+)\]\s*\[img[^\]]*\](.*?)\[/img\]\s*\[/url\]",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            page = (match.group(1) or "").strip()
            img = (match.group(2) or "").strip()
            if img and img.startswith(("http://", "https://")):
                items.append({"url": img, "referer": page})

        # BBCode: [img]url[/img] / [img=...]url[/img]
        for match in re.finditer(
            r"\[img[^\]]*\](.*?)\[/img\]", text, flags=re.IGNORECASE | re.DOTALL
        ):
            candidate = (match.group(1) or "").strip()
            if candidate.startswith(("http://", "https://")):
                items.append({"url": candidate, "referer": ""})

        # Markdown: ![](url)
        for match in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", text):
            candidate = (match.group(1) or "").strip()
            if candidate.startswith(("http://", "https://")):
                items.append({"url": candidate, "referer": ""})

        # HTML: <img src="...">
        for match in re.finditer(
            r"<img[^>]+src=[\"']([^\"']+)[\"']", text, flags=re.IGNORECASE
        ):
            candidate = (match.group(1) or "").strip()
            if candidate.startswith(("http://", "https://")):
                items.append({"url": candidate, "referer": ""})

        # Keep order, de-dup
        seen = set()
        result: List[Dict[str, str]] = []
        for item in items:
            url = (item.get("url") or "").strip()
            if not url:
                continue

            # pixhost 缩略图：只保留推断出来的 /images/ 直链，避免把 /thumbs/ 当作一张额外图片下载
            if "pixhost.to" in url and "/thumbs/" in url:
                m = re.match(r"^https?://t(\d+)\.pixhost\.to/thumbs/(.+)$", url)
                if m:
                    url = f"https://img{m.group(1)}.pixhost.to/images/{m.group(2)}"

            if not RousiUploader._is_probable_image_url(url):
                continue

            key = url
            if key in seen:
                continue
            seen.add(key)

            result.append({"url": url, "referer": item.get("referer", "")})

        return result

    def _collect_image_sources(self) -> List[Dict[str, str]]:
        sources: List[Dict[str, str]] = []

        images = self.upload_data.get("images")
        has_data_urls = False
        if isinstance(images, list):
            for item in images:
                if isinstance(item, str) and item.strip():
                    if item.strip().startswith("data:image/"):
                        sources.append({"url": item.strip(), "referer": ""})
                        has_data_urls = True
                    elif self._is_probable_image_url(item.strip()):
                        sources.append({"url": item.strip(), "referer": ""})

        # 如果上游已经给了 base64(data url)，则避免再从 intro 里抓取，
        # 防止出现“同一张图两个来源，其中一个是图床占位图”导致顺序错乱。
        if not has_data_urls:
            intro = self.upload_data.get("intro") or {}
            if isinstance(intro, dict):
                poster_text = intro.get("poster") or ""
                screenshots_text = intro.get("screenshots") or ""
                sources.extend(self._extract_image_sources_from_text(str(poster_text)))
                sources.extend(self._extract_image_sources_from_text(str(screenshots_text)))

        # De-dup while preserving order
        seen = set()
        result: List[Dict[str, str]] = []
        for s in sources:
            key = s.get("url", "")
            if key and key not in seen:
                seen.add(key)
                result.append(s)
        return result

    @staticmethod
    def _parse_data_url(data_url: str) -> Optional[Dict[str, Any]]:
        if not data_url.startswith("data:image/"):
            return None
        if ";base64," not in data_url:
            return None
        header, b64 = data_url.split(";base64,", 1)
        mime = header.split(":", 1)[1] if ":" in header else ""
        try:
            raw = base64.b64decode(b64, validate=False)
        except Exception:
            return None
        ext = mime.split("/", 1)[1] if "/" in mime else "bin"
        return {"mime": mime, "ext": ext, "bytes": raw}

    @staticmethod
    def _ffmpeg_convert_to_jpeg_under_limit(
        input_path: str, output_path: str, max_bytes: int
    ) -> bool:
        """
        使用 ffmpeg 转为 JPG 并尽量压缩到 max_bytes 以内。
        返回 True 表示最终输出满足 max_bytes。
        """
        # 两阶段压缩：先尽量保持清晰度，如果仍超限则进一步降质/缩放
        scales_primary = [None, 1920, 1600, 1280, 1024, 800]
        q_values_primary = [3, 5, 7, 9, 11, 13, 15, 17, 20, 24, 28, 32]

        scales_secondary = [720, 640, 576, 512, 480]
        q_values_secondary = [28, 32, 36, 40, 45]

        def _try(scales: List[Optional[int]], q_values: List[int]) -> bool:
            for scale in scales:
                for qv in q_values:
                    vf = []
                    if scale:
                        vf.append(f"scale='min({scale},iw)':-2:flags=lanczos")
                    vf_arg = ",".join(vf) if vf else "null"

                    cmd = [
                        "ffmpeg",
                        "-y",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-i",
                        input_path,
                        "-an",
                        "-sn",
                        "-dn",
                        "-frames:v",
                        "1",
                        "-vf",
                        vf_arg,
                        "-pix_fmt",
                        "yuvj420p",
                        "-q:v",
                        str(qv),
                        output_path,
                    ]
                    subprocess.run(
                        cmd,
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    if not os.path.exists(output_path):
                        continue
                    if os.path.getsize(output_path) <= max_bytes:
                        return True
            return False

        if _try(scales_primary, q_values_primary):
            return True

        # 二次压缩：对“png->jpg 仍 >5MB”的大图继续压缩
        if _try(scales_secondary, q_values_secondary):
            return True

        return os.path.exists(output_path) and os.path.getsize(output_path) <= max_bytes

    def _default_referer_for_url(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return ""
            return f"{parsed.scheme}://{parsed.netloc}/"
        except Exception:
            return ""

    def _download_to_bytes(self, url: str, referer: str = "") -> bytes:
        # 避免把 Bearer Token 带到第三方图床：仅当同域时才使用带鉴权的 session
        if url.startswith(self.base_url):
            resp = self.session.get(url, timeout=60)
        else:
            headers = {
                "user-agent": self.session.headers.get("user-agent", ""),
                "accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            }
            chosen_referer = referer if referer and referer.startswith(("http://", "https://")) else ""
            if not chosen_referer:
                chosen_referer = self._default_referer_for_url(url)
            if chosen_referer:
                headers["referer"] = chosen_referer
            resp = requests.get(
                url,
                headers=headers,
                timeout=60,
            )
        resp.raise_for_status()
        content = resp.content

        return content

    def _build_images_data_urls(self) -> Optional[List[str]]:
        sources = self._collect_image_sources()
        if not sources:
            return None

        from config import DATA_DIR

        images_root = os.path.join(DATA_DIR, "tmp", "torrents", "images")
        os.makedirs(images_root, exist_ok=True)

        # 与参数 JSON 一致的命名信息，用于本地缓存目录
        torrent_id = "unknown"
        source_site_code = "unknown"
        modified_torrent_path = self.upload_data.get("modified_torrent_path", "")
        if modified_torrent_path:
            torrent_filename = os.path.basename(modified_torrent_path)
            match = re.match(r"^([^-]+)-(\d+)-", torrent_filename)
            if match:
                source_site_code = match.group(1)
                torrent_id = match.group(2)

        timestamp = datetime.now().strftime("%Y-%m-%d-%H:%M:%S")
        work_dir = os.path.join(images_root, f"{source_site_code}-{torrent_id}-{self.site_name}-{timestamp}")
        os.makedirs(work_dir, exist_ok=True)
        self._temp_image_work_dirs.append(work_dir)

        per_image_limit = 5 * 1024 * 1024
        total_limit = 20 * 1024 * 1024
        total_used = 0

        images_data_urls: List[str] = []
        debug_manifest: List[Dict[str, Any]] = []

        for idx, item in enumerate(sources):
            if len(images_data_urls) >= 6:
                break

            try:
                source_url = (item.get("url") or "").strip()
                referer = (item.get("referer") or "").strip()
                if not source_url:
                    continue

                if source_url.startswith("data:image/"):
                    parsed = self._parse_data_url(source_url)
                    if not parsed:
                        logger.warning(f"无法解析 data URL 图片，已跳过: index={idx}")
                        continue
                    original_bytes = parsed["bytes"]
                    original_ext = str(parsed.get("ext") or "bin")
                    original_path = os.path.join(work_dir, f"{idx:02d}.original.{original_ext}")
                    with open(original_path, "wb") as f:
                        f.write(original_bytes)
                elif source_url.startswith(("http://", "https://")):
                    original_bytes = self._download_to_bytes(source_url, referer=referer)
                    original_path = os.path.join(work_dir, f"{idx:02d}.downloaded")
                    with open(original_path, "wb") as f:
                        f.write(original_bytes)
                else:
                    # 不认识的格式（例如本地路径），直接跳过
                    logger.warning(f"图片源格式不支持，已跳过: {source_url[:120]}")
                    continue

                try:
                    host = urlparse(source_url).netloc.lower()
                except Exception:
                    host = ""
                original_size = os.path.getsize(original_path) if os.path.exists(original_path) else 0
                jpeg_path = os.path.join(work_dir, f"{idx:02d}.final.jpg")
                ok = self._ffmpeg_convert_to_jpeg_under_limit(
                    original_path, jpeg_path, per_image_limit
                )
                if not ok:
                    if os.path.exists(jpeg_path):
                        logger.warning(
                            f"图片压缩后仍超过 5MB，已跳过: index={idx} size={os.path.getsize(jpeg_path)}"
                        )
                    else:
                        logger.warning(f"图片转换失败，已跳过: index={idx}")
                    continue

                jpeg_size = os.path.getsize(jpeg_path)
                if total_used + jpeg_size > total_limit:
                    logger.warning(
                        f"图片总大小将超过 20MB，已停止添加更多图片: current={total_used} next={jpeg_size}"
                    )
                    break

                with open(jpeg_path, "rb") as f:
                    jpeg_bytes = f.read()

                total_used += jpeg_size
                images_data_urls.append(
                    "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode("ascii")
                )

                debug_manifest.append(
                    {
                        "index": idx,
                        "source_url": source_url,
                        "referer": referer,
                        "original_path": original_path,
                        "original_size": original_size,
                        "jpeg_path": jpeg_path,
                        "jpeg_size": jpeg_size,
                    }
                )
            except Exception as e:
                logger.warning(f"处理图片失败，已跳过: index={idx} err={e}")
                continue

        if os.getenv("DEV_ENV") == "true":
            try:
                manifest_path = os.path.join(work_dir, "images.manifest.json")
                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump(debug_manifest, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

        return images_data_urls or None

    def _cleanup_temp_images(self) -> None:
        if not self._temp_image_work_dirs:
            return

        try:
            from config import DATA_DIR

            images_root = os.path.abspath(os.path.join(DATA_DIR, "tmp", "torrents", "images"))
        except Exception:
            return

        # De-dup while preserving order
        seen = set()
        work_dirs: List[str] = []
        for d in self._temp_image_work_dirs:
            if d and d not in seen:
                seen.add(d)
                work_dirs.append(d)
        self._temp_image_work_dirs = []

        for d in work_dirs:
            try:
                abs_d = os.path.abspath(d)
                if not abs_d.startswith(images_root + os.sep):
                    continue
                shutil.rmtree(abs_d, ignore_errors=True)
            except Exception:
                continue

    def _build_attributes(self) -> Optional[Dict[str, Any]]:
        attributes = self.upload_data.get("attributes")
        if isinstance(attributes, dict) and attributes:
            return attributes

        standardized_params = self.upload_data.get("standardized_params") or {}
        result: Dict[str, Any] = {}

        # resolution（优先走映射；否则兜底去掉前缀）
        resolution = self.upload_data.get("resolution") or standardized_params.get("resolution")
        if resolution:
            mapped_resolution = self._find_mapping(
                self.mappings.get("resolution", {}),
                str(resolution),
                mapping_type="resolution",
            )
            result["resolution"] = mapped_resolution or str(resolution).split(".", 1)[-1]

        # API v1 约定：source 应放在 attributes 中；这里尽量从媒介推断
        medium = (
            self.upload_data.get("source")
            or self.upload_data.get("medium")
            or standardized_params.get("medium")
        )
        if medium:
            mapped_source = self._find_mapping(
                self.mappings.get("source", {}),
                str(medium),
                mapping_type="medium",
            )
            result["source"] = mapped_source or str(medium).split(".", 1)[-1]

        # region（优先走映射；兼容旧流程 region 从 standardized_params.source 来）
        region = (
            self.upload_data.get("region")
            or standardized_params.get("region")
            or standardized_params.get("source")
        )
        if region:
            mapped_region = self._find_mapping(
                self.mappings.get("region", {}),
                str(region),
                mapping_type="source",
            )
            result["region"] = mapped_region or str(region).split(".", 1)[-1]

        genre = self.upload_data.get("genre") or standardized_params.get("genre")
        if isinstance(genre, list) and genre:
            result["genre"] = genre
        elif isinstance(genre, str) and genre.strip():
            result["genre"] = [g.strip() for g in genre.split(",") if g.strip()]

        return result or None

    def _normalize_tags(self) -> Optional[str]:
        tags = self.upload_data.get("tags")
        if tags is None:
            standardized_params = self.upload_data.get("standardized_params") or {}
            tags = standardized_params.get("tags")

        if isinstance(tags, str):
            raw_tags = [t.strip() for t in tags.split(",") if t.strip()]
        elif isinstance(tags, list):
            raw_tags = [str(t).strip() for t in tags if str(t).strip()]
        else:
            return None

        normalized: List[str] = []
        for tag in raw_tags:
            tag_text = str(tag).strip()
            if not tag_text:
                continue
            # 去掉类似 tag.xxx / tags.xxx / 任意 xxx.yyy 的前缀
            if "." in tag_text:
                tag_text = tag_text.split(".", 1)[1].strip()
            if tag_text:
                normalized.append(tag_text)

        # 去重保持顺序
        seen = set()
        dedup: List[str] = []
        for t in normalized:
            if t not in seen:
                seen.add(t)
                dedup.append(t)

        return ",".join(dedup) if dedup else None

    def _normalize_images(self) -> Optional[List[str]]:
        # 按站点要求：图片必须 base64(data url) 提交，并满足 6张/5MB/20MB 限制
        return self._build_images_data_urls()

    def _build_api_payload(self, mapped_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        构建 API v1 上传所需的 JSON payload

        :param mapped_params: 通过标准映射流程处理后的参数字典
        """
        standardized_params = self.upload_data.get("standardized_params") or {}

        title = self.upload_data.get("title")
        if not title:
            title = super()._build_title(standardized_params)

        category_value = (
            self.upload_data.get("category")
            or self.upload_data.get("type")
            or standardized_params.get("category")
            or standardized_params.get("type")
        )

        payload: Dict[str, Any] = {
            "torrent": self._read_torrent_base64(),
            "title": str(title).strip(),
            "description": self._build_description_markdown(),
        }

        subtitle = self.upload_data.get("subtitle")
        if subtitle:
            payload["subtitle"] = str(subtitle).strip()

        normalized_category = self._normalize_category(category_value)
        if normalized_category:
            # 使用映射后的值（优先级：type 映射 > category 映射 > 原始值）
            payload["category"] = (
                mapped_params.get("type")
                or mapped_params.get("category")
                or normalized_category
            )

        if attributes := self._build_attributes():
            payload["attributes"] = attributes

        media_info = self.upload_data.get("mediaInfo") or self.upload_data.get("media_info")
        if not media_info:
            media_info = (
                self.upload_data.get("mediainfo")
                or self.upload_data.get("mediainfo_text")
                or self.upload_data.get("mediainfo_str")
            )
        if media_info:
            payload["media_info"] = str(media_info)

        if images := self._normalize_images():
            payload["images"] = images

        anonymous_value = self.upload_data.get("anonymous")
        if isinstance(anonymous_value, bool):
            payload["anonymous"] = anonymous_value
        else:
            from config import config_manager

            anonymous_upload = (
                config_manager.get().get("upload_settings", {}).get("anonymous_upload", True)
            )
            payload["anonymous"] = bool(anonymous_upload)

        if "price" in self.upload_data:
            payload["price"] = self.upload_data.get("price")

        # 本站要求：region/resolution/source/genre 仅放在 attributes 内；tmdb/imdb/douban 也放在 attributes 内
        attributes_data: Dict[str, Any] = {}
        if isinstance(payload.get("attributes"), dict):
            attributes_data.update(payload["attributes"])

        # region/resolution/source/genre（兼容 a.json 顶层写法，但最终只写入 attributes）
        for key in ("region", "resolution", "source"):
            # 优先使用映射后的值（否则会出现“只有 type 映射生效”的现象）
            value = mapped_params.get(key)
            if value is None:
                value = self.upload_data.get(key)
            if value is None:
                value = attributes_data.get(key)
            if value is None and key == "region":
                # region 的另一种来源：旧流程里“产地”会落到 standardized_params.source
                value = standardized_params.get("source")
            if value is None:
                continue

            if isinstance(value, str):
                text = value.strip()
                # 仅对标准键（如 source.china / resolution.r1080p）做去前缀兜底；映射后的中文/枚举值不处理
                if "." in text and text.split(".", 1)[0] in {"source", "resolution", "medium"}:
                    text = text.split(".", 1)[-1].strip()
                attributes_data[key] = text
            else:
                attributes_data[key] = value

        # genre：
        # 1) 先从 tags 构造（去掉类似 tag.xxx / 任意前缀*. 的前缀），写入 attributes.genre
        # 2) 再合并 upload_data.genre / attributes.genre（如果有）
        genre_list: List[str] = []

        tags_value = self.upload_data.get("tags")
        if tags_value is None:
            tags_value = standardized_params.get("tags")

        raw_tag_items: List[str] = []
        if isinstance(tags_value, str):
            raw_tag_items = [t.strip() for t in tags_value.split(",") if t.strip()]
        elif isinstance(tags_value, list):
            raw_tag_items = [str(t).strip() for t in tags_value if str(t).strip()]

        for t in raw_tag_items:
            text = t
            if "." in text:
                text = text.split(".", 1)[1].strip()
            if text:
                genre_list.append(text)

        # 兼容：从 upload_data.genre / attributes.genre 获取（并入 genre_list）
        genre_value = self.upload_data.get("genre")
        if genre_value is None:
            genre_value = attributes_data.get("genre")
        if isinstance(genre_value, list):
            genre_list.extend([str(g).split(".", 1)[-1].strip() for g in genre_value if str(g).strip()])
        elif isinstance(genre_value, str) and genre_value.strip():
            genre_list.extend([g.strip() for g in genre_value.split(",") if g.strip()])

        if genre_list:
            seen = set()
            dedup_genre: List[str] = []
            for g in genre_list:
                if g and g not in seen:
                    seen.add(g)
                    dedup_genre.append(g)
            attributes_data["genre"] = dedup_genre

        # 三方链接：从 *_link 或同名字段提取，但写入 attributes
        link_sources = {
            "tmdb": ["tmdb", "tmdb_link"],
            "imdb": ["imdb", "imdb_link"],
            "douban": ["douban", "douban_link"],
        }
        for key, candidates in link_sources.items():
            value = None
            for candidate in candidates:
                candidate_value = self.upload_data.get(candidate) or standardized_params.get(candidate)
                if isinstance(candidate_value, str) and candidate_value.strip():
                    value = candidate_value.strip()
                    break
            if value:
                attributes_data[key] = value

        if attributes_data:
            payload["attributes"] = attributes_data

        # 清理空字符串字段，避免触发参数校验错误
        for key in list(payload.keys()):
            if payload[key] == "":
                payload.pop(key, None)

        return payload

    def _save_upload_parameters(self, payload: Dict[str, Any]) -> None:
        try:
            from config import DATA_DIR

            torrent_dir = os.path.join(DATA_DIR, "tmp", "torrents")
            os.makedirs(torrent_dir, exist_ok=True)

            torrent_id = "unknown"
            source_site_code = "unknown"
            modified_torrent_path = self.upload_data.get("modified_torrent_path", "")
            if modified_torrent_path:
                torrent_filename = os.path.basename(modified_torrent_path)
                match = re.match(r"^([^-]+)-(\d+)-", torrent_filename)
                if match:
                    source_site_code = match.group(1)
                    torrent_id = match.group(2)

            timestamp = datetime.now().strftime("%Y-%m-%d-%H:%M:%S")
            filename = f"{source_site_code}-{torrent_id}-{self.site_name}-{timestamp}.json"
            filepath = os.path.join(torrent_dir, filename)

            standardized_params = self.upload_data.get("standardized_params", {})
            save_data = {
                "site_name": self.site_name,
                "timestamp": timestamp,
                "form_data": payload,
                "standardized_params": standardized_params,
                "final_main_title": payload.get("title", ""),
                "description": payload.get("description", ""),
                "upload_data_summary": {
                    "subtitle": self.upload_data.get("subtitle", ""),
                    "douban_link": self.upload_data.get("douban_link", ""),
                    "imdb_link": self.upload_data.get("imdb_link", ""),
                    "mediainfo_length": len(
                        str(
                            self.upload_data.get("media_info")
                            or self.upload_data.get("mediaInfo")
                            or self.upload_data.get("mediainfo")
                            or ""
                        )
                    ),
                    "modified_torrent_path": modified_torrent_path,
                },
            }

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)
            logger.info(f"上传参数已保存到: {filepath}")
        except Exception as e:
            logger.error(f"保存参数到文件失败: {e}")

    def _save_publish_response(self, response: requests.Response) -> None:
        """
        保存发布响应内容（用于站点 API 行为排查）。
        Rousi：默认不落盘，避免产生大量 tmp 文件。
        """
        try:
            if os.getenv("DEV_ENV") != "true" or os.getenv("ROUSI_SAVE_PUBLISH_RESPONSE") != "true":
                return

            from config import DATA_DIR

            torrent_dir = os.path.join(DATA_DIR, "tmp", "torrents")
            os.makedirs(torrent_dir, exist_ok=True)

            torrent_id = "unknown"
            source_site_code = "unknown"
            modified_torrent_path = self.upload_data.get("modified_torrent_path", "")
            if modified_torrent_path:
                torrent_filename = os.path.basename(modified_torrent_path)
                match = re.match(r"^([^-]+)-(\d+)-", torrent_filename)
                if match:
                    source_site_code = match.group(1)
                    torrent_id = match.group(2)

            timestamp = datetime.now().strftime("%Y-%m-%d-%H:%M:%S")

            content_type = (response.headers.get("content-type") or "").lower()
            ext = "json" if "json" in content_type else "html"
            filename = f"{source_site_code}-{torrent_id}-{self.site_name}-{timestamp}.response.{ext}"
            filepath = os.path.join(torrent_dir, filename)

            meta_filename = (
                f"{source_site_code}-{torrent_id}-{self.site_name}-{timestamp}.response.meta.json"
            )
            meta_path = os.path.join(torrent_dir, meta_filename)

            # 保存原始响应内容
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(response.text or "")

            # 保存元信息（状态码、headers、最终URL等）
            meta = {
                "site_name": self.site_name,
                "timestamp": timestamp,
                "status_code": response.status_code,
                "url": response.url,
                "headers": dict(response.headers),
                "content_type": response.headers.get("content-type"),
                "body_preview": (response.text or "")[:2000],
            }
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)

            logger.info(f"发布响应已保存到: {filepath}")
        except Exception as e:
            logger.error(f"保存发布响应失败: {e}")

    def execute_upload(self):
        logger.info(f"正在向 {self.site_name} (API v1) 提交发布请求...")
        try:
            # 使用标准映射流程获取映射后的参数
            mapped_params = self._map_parameters()

            # 构建上传 payload
            payload = self._build_api_payload(mapped_params)

            if os.getenv("DEV_ENV") == "true":
                self._save_upload_parameters(payload)

            if os.getenv("UPLOAD_TEST_MODE") == "true":
                dummy_uuid = "550e8400-e29b-41d4-a716-446655440000"
                logger.info("测试模式：跳过实际发布，模拟成功响应")
                return True, f"发布成功！(测试模式) UUID: {dummy_uuid}"

            resp = self.session.post(self.post_url, json=payload, timeout=self.timeout)
            self._save_publish_response(resp)
            resp.raise_for_status()

            try:
                data = resp.json()
            except Exception:
                return False, f"API 返回非 JSON 响应: {resp.text[:500]}"

            if data.get("code") != 0:
                return False, f"API 错误: {data.get('message') or data}"

            result = data.get("data") or {}
            uuid = result.get("uuid") or ""
            status = result.get("status") or ""
            base_url = ensure_scheme(self.site_info.get("base_url") or "")
            details_page_url = f"{base_url}/torrent/{uuid}" if uuid else ""

            message = f"发布成功！UUID: {uuid} 状态: {status}"
            if details_page_url:
                message = f"{message} 链接: {details_page_url}"

            return True, message
        except requests.HTTPError as e:
            text = ""
            try:
                text = e.response.text[:500] if e.response is not None else ""
            except Exception:
                text = ""
            return False, f"HTTP错误: {e} {text}".strip()
        except Exception as e:
            logger.error(f"RousiUploader 上传异常: {e}")
            return False, f"请求异常: {e}"
        finally:
            # 清理本次上传过程产生的临时图片目录（已转换为 base64 后即可删除）
            self._cleanup_temp_images()
