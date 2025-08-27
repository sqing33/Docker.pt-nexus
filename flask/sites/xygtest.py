# sites/星陨阁.py

import os
import traceback
import cloudscraper
from loguru import logger
from utils import cookies_raw2jar, ensure_scheme


class XygUploader:

    def __init__(self, site_info: dict, upload_data: dict):
        """
        :param site_info: 包含站点URL、Cookie等基本信息的字典。
        :param upload_data: 包含待上传种子所有详细信息的字典 (即 upload_payload)。
        """
        self.site_info = site_info
        self.upload_data = upload_data
        self.scraper = cloudscraper.create_scraper()

        base_url = ensure_scheme(self.site_info.get("base_url"))

        self.post_url = f"{base_url}/takeupload.php"
        self.timeout = 40
        self.headers = {
            "origin": base_url,
            "referer": f"{base_url}/upload.php",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        }

    def _map_parameters(self) -> dict:
        """
        将源站点的参数映射为 星陨阁 站点所需的表单值。
        """
        params = self.upload_data.get("source_params", {})
        mapped = {}
        tags = []

        # 类型
        source_type = params.get("类型") or "电影"
        mapped["type"] = "401" if "电影" in source_type else "405"

        # 媒介
        medium_lower = (params.get("媒介") or "bluray").lower()
        if "web" in medium_lower and "dl" in medium_lower:
            mapped["medium_sel[4]"] = "11"
        elif "blu" in medium_lower:
            mapped["medium_sel[4]"] = "1"
        else:
            mapped["medium_sel[4]"] = "7"  # Remux

        # 编码
        codec_lower = (params.get("编码") or "H.264").lower()
        if "264" in codec_lower:
            mapped["codec_sel[4]"] = "1"
        elif "265" in codec_lower:
            mapped["codec_sel[4]"] = "6"
        else:
            mapped["codec_sel[4]"] = "1"

        # 音频编码
        audio_upper = (params.get("音频编码") or "DTS").upper()
        if "AAC" in audio_upper:
            mapped["audiocodec_sel[4]"] = "6"
        elif "DDP" in audio_upper:
            mapped["audiocodec_sel[4]"] = "12"
        else:
            mapped["audiocodec_sel[4]"] = "7"  # DTS

        # 分辨率
        resolution = params.get("分辨率") or "1080p"
        if "8K" in resolution:
            mapped["standard_sel[4]"] = "7"
        elif "2160" in resolution:
            mapped["standard_sel[4]"] = "6"
        elif "1080" in resolution:
            mapped["standard_sel[4]"] = "1"
        elif "720" in resolution:
            mapped["standard_sel[4]"] = "3"
        elif "480" in resolution:
            mapped["standard_sel[4]"] = "4"
        else:
            mapped["standard_sel[4]"] = "8"  # Other

        # 制作组
        source_team = params.get("制作组")
        if source_team and "MTeam" in source_team:
            mapped["team_sel[4]"] = "1"
        else:
            mapped["team_sel[4]"] = "5"

        # 标签
        source_tags = params.get("标签") or []
        if "国语" in source_tags:
            tags.append(5)
        if "中字" in source_type:
            tags.append(6)

        # 将标签ID添加到映射字典中
        for i, tag_id in enumerate(sorted(list(set(tags)))):
            mapped[f"tags[4][{i}]"] = tag_id

        return mapped

    def _build_description(self) -> str:
        """
        根据 intro 数据构建完整的 BBCode 描述。
        """
        intro = self.upload_data.get("intro", {})
        return (
            f"{intro.get('statement', '')}\n"
            f"{intro.get('poster', '')}\n"
            f"{intro.get('body', '')}\n"
            f"{intro.get('screenshots', '')}"
        )

    def execute_upload(self):
        """
        执行上传的核心逻辑。
        """
        logger.info("正在为 星陨阁 站点适配上传参数...")

        try:
            mapped_params = self._map_parameters()
            description = self._build_description()
            logger.info("参数适配完成。")

            form_data = {
                "name": self.upload_data.get("main_title", ""),
                "small_descr": self.upload_data.get("subtitle", ""),
                "url": self.upload_data.get("imdb_link", "") or "",
                "color": "0",
                "font": "0",
                "size": "0",
                "descr": description,
                "technical_info": self.upload_data.get("mediainfo", ""),
                "uplver": "yes",
                **mapped_params,
            }

            torrent_path = self.upload_data["modified_torrent_path"]
            with open(torrent_path, "rb") as torrent_file:
                files = {
                    "file": (
                        os.path.basename(torrent_path),
                        torrent_file,
                        "application/x-bittorrent",
                    ),
                    "nfo": ("", b"", "application/octet-stream"),
                }

                cleaned_cookie_str = self.site_info.get("cookie", "").strip()
                if not cleaned_cookie_str:
                    logger.error("目标站点 Cookie 为空，无法发布。")
                    return False, "目标站点 Cookie 未配置。"

                cookie_jar = cookies_raw2jar(cleaned_cookie_str)

                logger.info("正在向 星陨阁 站点提交发布请求...")
                response = self.scraper.post(
                    self.post_url,
                    headers=self.headers,
                    cookies=cookie_jar,
                    data=form_data,
                    files=files,
                    timeout=self.timeout,
                )
                response.raise_for_status()

            if "details.php" in response.url and "uploaded=1" in response.url:
                logger.success("发布成功！已跳转到种子详情页。")
                return True, f"发布成功！新种子页面: {response.url}"
            elif "login.php" in response.url:
                logger.error("发布失败，Cookie 已失效，被重定向到登录页。")
                return False, "发布失败，Cookie 已失效或无效。"
            else:
                logger.error(f"发布失败，站点返回未知响应。")
                logger.debug(f"响应URL: {response.url}")
                logger.debug(f"响应内容前500字符: {response.text[:500]}")
                return False, f"发布失败，请检查站点返回信息。 URL: {response.url}"

        except Exception as e:
            logger.error(f"发布到 星陨阁 站点时发生错误: {e}")
            logger.error(traceback.format_exc())
            return False, f"请求异常: {e}"


def upload(site_info: dict, upload_payload: dict):
    uploader = XygUploader(site_info, upload_payload)
    return uploader.execute_upload()
