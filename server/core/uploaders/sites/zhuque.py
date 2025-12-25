from ..uploader import SpecialUploader
from loguru import logger
import os
import sys
import re
import json
import requests
import logging

sys.path.append(
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
)
from utils import get_tmdb_url_from_any_source


class ZhuqueUploader(SpecialUploader):
    """
    朱雀站点特殊上传器 (适配 TNode 架构 / API模式)
    """

    def __init__(self, site_name: str, site_info: dict, upload_data: dict):
        super().__init__(site_name, site_info, upload_data)

        base_url = ensure_scheme(self.site_info.get("base_url") or "")
        self.post_url = f"{base_url}/api/torrent/upload"

        # [修复] 初始化 Session
        self.session = requests.Session()

        # [修复] 加载 Cookie
        cookie_str = self.site_info.get("cookie", "")
        if cookie_str:
            self.session.headers.update({"cookie": cookie_str})

        # 设置基础 Headers
        self.session.headers.update(
            {
                "referer": f"{base_url}/torrent/upload",
                "origin": base_url,  # 补充 origin 头，有时防跨站检查需要
                "x-requested-with": "XMLHttpRequest",
                "accept": "application/json, text/plain, */*",
                "user-agent": self.site_info.get("user_agent")
                or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }
        )

        self.headers.update(self.session.headers)

    def _fetch_csrf_token(self) -> str:
        """从页面提取 CSRF Token"""
        try:
            base_url = ensure_scheme(self.site_info.get("base_url") or "")
            # 访问 /torrent/upload 页面获取 Token
            page_url = f"{base_url}/torrent/upload"

            logger.info(f"正在获取 CSRF Token: {page_url}")
            resp = self.session.get(page_url, timeout=30)

            if resp.status_code == 200:
                match = re.search(r'<meta name="x-csrf-token" content="([^"]+)">', resp.text)
                if match:
                    token = match.group(1)
                    logger.success(f"成功获取 CSRF Token: {token[:8]}...")
                    return token
            logger.warning("页面中未找到 CSRF Token Meta 标签")
            return ""
        except Exception as e:
            logger.warning(f"获取 CSRF Token 失败: {e}")
            return ""

    def _get_torrent_key(self) -> str:
        """获取用户的 torrentKey 用于下载链接构造"""
        try:
            base_url = ensure_scheme(self.site_info.get("base_url") or "")
            api_url = f"{base_url}/api/user/getSecurityInfo"

            # 设置 Referer
            headers = {"Referer": f"{base_url}/user/rss"}

            logger.info(f"正在获取 torrentKey: {api_url}")
            resp = self.session.get(api_url, headers=headers, timeout=30)

            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == 200:
                    user_data = data.get("data", {})
                    torrent_key = user_data.get("torrentKey")
                    if torrent_key:
                        logger.success(f"成功获取 torrentKey: {torrent_key[:8]}...")
                        return torrent_key
                    else:
                        logger.warning("响应数据中未找到 torrentKey 字段")
                else:
                    logger.warning(f"API 返回非成功状态: {data}")
            else:
                logger.warning(f"获取 torrentKey 失败，状态码: {resp.status_code}")

        except Exception as e:
            logger.warning(f"获取 torrentKey 发生错误: {e}")

        return ""

    def _map_parameters(self) -> dict:
        """参数映射"""
        mapped = {}
        tags = []

        standardized_params = self.upload_data.get("standardized_params", {})
        if not standardized_params:
            standardized_params = self._parse_source_data()

        # 1. 基础映射
        mapping_config = self.config.get("mappings", {})

        mapped["category"] = self._find_mapping(
            mapping_config.get("type", {}), standardized_params.get("type", "")
        )
        mapped["medium"] = self._find_mapping(
            mapping_config.get("medium", {}),
            standardized_params.get("medium", ""),
            use_length_priority=False,
            mapping_type="medium",
        )
        mapped["videoCoding"] = self._find_mapping(
            mapping_config.get("video_codec", {}),
            standardized_params.get("video_codec", ""),
            mapping_type="video_codec",
        )
        mapped["resolution"] = self._find_mapping(
            mapping_config.get("resolution", {}),
            standardized_params.get("resolution", ""),
            mapping_type="resolution",
        )

        # 2. 标签映射
        combined_tags = self._collect_all_tags()
        tag_mapping = mapping_config.get("tag", {})
        tag_value_mapping = {
            "官方": "601",
            "禁转": "602",
            "国语": "603",
            "中字": "604",
            "杜比视界": "611",
            "HDR10": "613",
            "特效字幕": "614",
            "完结": "621",
            "分集": "622",
        }

        for tag_str in combined_tags:
            tag_id = self._find_mapping(tag_mapping, tag_str)
            if not tag_id:
                tag_id = tag_value_mapping.get(tag_str)
            if tag_id:
                tags.append(tag_id)

        if tags:
            # 将标签数组改为逗号分隔的字符串
            mapped["tags"] = ",".join(sorted(list(set(tags))))

        # 3. TMDB 信息
        tmdb_id, tmdb_type = self._extract_tmdb_info()
        mapped["tmdbid"] = tmdb_id if tmdb_id else ""  # 即使为空也发送空字符串，保持字段存在
        mapped["tmdbtype"] = tmdb_type

        # 4. 截图
        screenshots = self._extract_screenshots_for_zhuque()
        if screenshots:
            mapped["screenshot"] = screenshots

        # 5. 备注
        note = self._build_combined_note()
        if note:
            mapped["note"] = note

        # 6. [关键修复] 补充缺失的固定参数
        mapped["zwex"] = "0"

        return mapped

    def _extract_tmdb_info(self) -> tuple:
        """提取 TMDB ID 和 Type"""
        tmdb_link = self.upload_data.get("tmdb_link", "") or ""
        imdb_link = self.upload_data.get("imdb_link", "") or ""
        douban_link = self.upload_data.get("douban_link", "") or ""

        tmdb_result = get_tmdb_url_from_any_source(imdb_link, douban_link, tmdb_link)

        # Handle different return types from get_tmdb_url_from_any_source
        if tmdb_result:
            if isinstance(tmdb_result, tuple):
                tmdb_url, media_type = tmdb_result
            else:
                tmdb_url = tmdb_result
                # Extract media type from the URL
                if "/tv/" in tmdb_url:
                    media_type = "tv"
                else:
                    media_type = "movie"
        else:
            tmdb_url = ""
            media_type = "movie"

        if tmdb_url:
            match = re.search(r"themoviedb\.org/(?:movie|tv)/(\d+)", tmdb_url)
            if match:
                return match.group(1), "1" if media_type == "tv" else "0"
        return "", "0"

    def _extract_screenshots_for_zhuque(self) -> str:
        intro = self.upload_data.get("intro", {})
        screenshots = intro.get("screenshots", "")
        if not screenshots:
            return ""

        img_urls = re.findall(r"\[img\](.*?)\[/img\]", screenshots)
        if img_urls:
            return "\n".join(img_urls)

        lines = screenshots.strip().split("\n")
        url_lines = []
        for line in lines:
            line = line.strip()
            if line.startswith(("http://", "https://")):
                clean_url = re.search(r"https?://[^\s\[\]]+", line)
                if clean_url:
                    url_lines.append(clean_url.group(0))
        return "\n".join(url_lines)

    def _build_combined_note(self) -> str:
        parts = []
        intro = self.upload_data.get("intro", {})

        # 声明
        if statement := intro.get("statement", "").strip():
            # 过滤掉所有的BBCode标签 [tag] [/tag] [tag=...] 等
            filtered_statement = re.sub(r"\[[^\]]*\]", "", statement)
            parts.append(filtered_statement)

        if imdb := self.upload_data.get("imdb_link", ""):
            parts.append(f"资源IMDB链接: {imdb}")

        if douban := self.upload_data.get("douban_link", ""):
            parts.append(f"资源豆瓣链接: {douban}")

        return "\n\n".join(parts)

    def execute_upload(self):
        """
        手动执行上传请求
        """
        logger.info(f"正在为 {self.site_name} 站点适配上传参数...")
        try:
            # 1. 获取 CSRF Token
            csrf_token = self._fetch_csrf_token()
            if csrf_token:
                self.session.headers.update({"x-csrf-token": csrf_token})
            else:
                logger.error("无法获取 x-csrf-token，上传请求可能会失败！")

            # 2. 准备参数
            standardized_params = self.upload_data.get("standardized_params", {})
            mapped_params = self._map_parameters()
            final_main_title = super()._build_title(standardized_params)

            from config import config_manager

            anonymous_upload = (
                config_manager.get().get("upload_settings", {}).get("anonymous_upload", True)
            )

            # 3. 构造 Data
            data = {
                "title": final_main_title,
                "subtitle": self.upload_data.get("subtitle", ""),
                "mediainfo": self.upload_data.get("mediainfo", ""),
                "anonymous": "true" if anonymous_upload else "false",
                "confirm": "true",
                **mapped_params,
            }

            # 3.1 验证必需参数
            required_fields = ["title", "category", "medium", "videoCoding", "resolution"]
            missing_fields = []
            for field in required_fields:
                if field not in data or not data[field]:
                    missing_fields.append(field)

            if missing_fields:
                logger.error(f"缺少必需参数: {missing_fields}")
                logger.error(f"当前数据: {json.dumps(data, ensure_ascii=False, indent=2)}")
                return False, f"缺少必需参数: {', '.join(missing_fields)}", None

            # 4. 保存参数用于调试
            if os.getenv("DEV_ENV") == "true":
                self._save_upload_parameters(data, mapped_params, final_main_title)

            # ================= [新增] 测试模式检查开始 =================
            if os.getenv("UPLOAD_TEST_MODE") == "true":
                logger.info("测试模式：跳过实际发布，模拟成功响应")

                # 模拟一个成功的返回
                dummy_id = "999999999"
                base_url = ensure_scheme(self.site_info.get("base_url") or "")
                details_url = f"demo.site.test/torrent/info/{dummy_id}"

                # 尝试获取 key 用于模拟下载链接（保持逻辑完整性）
                torrent_key = self._get_torrent_key() or "TEST_KEY"
                download_url = f"demo.site.test/api/torrent/download/{dummy_id}/{torrent_key}"

                logger.success(f"发布成功！(测试模式) 种子ID: {dummy_id}")
                return (
                    True,
                    f"发布成功！(测试模式) 链接: {details_url}",
                    {
                        "torrent_id": dummy_id,
                        "details_url": details_url,
                        "download_url": download_url,
                    },
                )
            # ================= [新增] 测试模式检查结束 =================

            # 5. 构造 File
            torrent_path = self.upload_data.get("modified_torrent_path")
            if not torrent_path or not os.path.exists(torrent_path):
                return False, "种子文件路径不存在", None

            file_name = os.path.basename(torrent_path)

            # 使用 open 打开文件 (注意: requests 会自动管理 multipart boundary)
            files = {"torrent": (file_name, open(torrent_path, "rb"), "application/octet-stream")}

            # 7. 发送请求
            logger.info(f"正在向 {self.site_name} 提交发布请求...")

            response = self.session.post(self.post_url, data=data, files=files, timeout=120)

            # 关闭文件
            files["torrent"][1].close()

            # 8. 响应处理
            if response.status_code == 400:
                # 尝试解析JSON响应以获取具体错误码
                try:
                    error_json = response.json()
                    error_code = error_json.get("code", "")

                    if error_code == "TORRENT_ALREADY_UPLOAD":
                        logger.success("种子已存在！该资源已经在站点上发布过。")
                        return True, "发布成功！种子已存在，该资源可能已经在站点上发布过", None
                    elif error_code:
                        logger.error(f"站点返回错误码: {error_code}")
                        return False, f"站点错误: {error_code}", None

                except json.JSONDecodeError:
                    logger.error("无法解析错误响应JSON")

                return False, f"参数错误 (400)，请查看详细信息", None
            elif response.status_code == 500:
                logger.error(f"服务器返回内容: {response.text[:500]}")
                return False, "站点内部错误 (500)，请查看日志详情", None

            response.raise_for_status()

            try:
                resp_json = response.json()
                logger.debug(f"站点响应: {resp_json}")

                # 检查响应成功状态
                is_success = False

                # 情况1: status 200 + data.code UPLOAD_SUCCESS
                if resp_json.get("status") == 200:
                    d = resp_json.get("data", {})
                    if isinstance(d, dict) and d.get("code") == "UPLOAD_SUCCESS":
                        is_success = True
                # 情况2: code 0
                elif resp_json.get("code") == 0:
                    is_success = True
                # 情况3: success true
                elif resp_json.get("success") is True:
                    is_success = True

                if is_success:
                    torrent_id = None
                    if resp_json.get("data") and isinstance(resp_json["data"], dict):
                        torrent_id = resp_json["data"].get("id")
                    elif resp_json.get("id"):
                        torrent_id = resp_json.get("id")

                    if torrent_id:
                        base_url = ensure_scheme(self.site_info.get("base_url") or "")
                        details_url = f"{base_url}/torrent/info/{torrent_id}"
                        logger.success(f"发布成功！种子ID: {torrent_id}")

                        # 获取 torrentKey 并构造下载链接
                        torrent_key = self._get_torrent_key()
                        if torrent_key:
                            download_url = (
                                f"{base_url}/api/torrent/download/{torrent_id}/{torrent_key}"
                            )
                            print(f"种子下载链接: {download_url}")
                        else:
                            logger.warning("无法获取 torrentKey，无法构造下载链接")

                        return (
                            True,
                            f"发布成功！链接: {details_url}",
                            {
                                "torrent_id": torrent_id,
                                "details_url": details_url,
                                "download_url": download_url,
                            },
                        )
                    else:
                        return True, "发布成功，但未获取到ID", None
                else:
                    msg = resp_json.get("message") or resp_json.get("msg") or "未知错误"
                    if resp_json.get("data") and isinstance(resp_json["data"], dict):
                        msg = resp_json["data"].get("message") or msg
                    return False, f"发布失败: {msg}", None

            except json.JSONDecodeError:
                if "success" in response.text.lower():
                    return True, "发布成功(非JSON响应)", None
                return False, f"响应解析失败: {response.text[:200]}", None

        except Exception as e:
            logger.error(f"发布到 {self.site_name} 发生错误: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return False, f"请求异常: {e}", None

    def _save_upload_parameters(self, data, mapped_params, final_main_title):
        """
        保存上传参数到tmp目录，用于调试和测试
        """
        try:
            from datetime import datetime
            from config import DATA_DIR

            # 使用统一的 torrents 目录
            torrent_dir = os.path.join(DATA_DIR, "tmp", "torrents")
            os.makedirs(torrent_dir, exist_ok=True)

            # 从 upload_data 中获取种子ID和源站点代码
            torrent_id = "unknown"
            source_site_code = "unknown"

            modified_torrent_path = self.upload_data.get("modified_torrent_path", "")
            if modified_torrent_path:
                torrent_filename = os.path.basename(modified_torrent_path)
                # 尝试从文件名中提取站点代码和种子ID（格式: 站点代码-种子ID-xxx.torrent）
                match = re.match(r"^([^-]+)-(\d+)-", torrent_filename)
                if match:
                    source_site_code = match.group(1)
                    torrent_id = match.group(2)

            # 生成可读的时间戳格式: YYYY-MM-DD-HH:MM:SS
            timestamp = datetime.now().strftime("%Y-%m-%d-%H:%M:%S")

            # 格式: {站点代码}-{种子ID}-{目标站点self.site_name}-{时间戳}
            filename = f"{source_site_code}-{torrent_id}-{self.site_name}-{timestamp}.json"
            filepath = os.path.join(torrent_dir, filename)

            # 准备要保存的数据
            save_data = {
                "site_name": self.site_name,
                "timestamp": timestamp,
                "form_data": data,
                "mapped_params": mapped_params,
                "final_main_title": final_main_title,
                "upload_data_summary": {
                    "subtitle": self.upload_data.get("subtitle", ""),
                    "douban_link": self.upload_data.get("douban_link", ""),
                    "imdb_link": self.upload_data.get("imdb_link", ""),
                    "tmdb_link": self.upload_data.get("tmdb_link", ""),
                    "mediainfo_length": len(self.upload_data.get("mediainfo", "")),
                    "modified_torrent_path": self.upload_data.get("modified_torrent_path", ""),
                },
            }

            # 保存到文件
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)
            logger.info(f"朱雀上传参数已保存到: {filepath}")
        except Exception as save_error:
            logger.error(f"保存参数到文件失败: {save_error}")


def ensure_scheme(url: str) -> str:
    if not url:
        return ""
    return f"https://{url}" if not url.startswith(("http://", "https://")) else url
