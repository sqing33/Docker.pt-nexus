# sites/lucky.py

import os
import traceback
import cloudscraper
from loguru import logger
from utils import cookies_raw2jar, ensure_scheme
import re


class LuckyUploader:

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
            "origin":
            base_url,
            "referer":
            f"{base_url}/upload.php",
            "user-agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        }

    def _map_parameters(self) -> dict:
        """
        将参数映射为 lucky 站点所需的表单值。
        - 新逻辑：优先从主标题解析出的参数 (title_components) 获取技术规格。
        - 类型和标签: 继续从源站的原始参数 (source_params) 获取。
        """
        # 从源站原始参数中获取
        source_params = self.upload_data.get("source_params", {})

        # 从主标题解析结果中获取，并转换为更易于访问的字典
        title_components_list = self.upload_data.get("title_components", [])
        title_params = {
            item["key"]: item["value"]
            for item in title_components_list if item.get("value")
        }

        mapped = {}
        tags = []

        # 1. 类型
        source_type = source_params.get("类型") or "电影"
        if "电影" in source_type:
            mapped["type"] = "401"
        elif "电视剧" in source_type:
            mapped["type"] = "402"
        elif "动画" in source_type or "动漫" in source_type or "Anime" in source_type or "Animations" in source_type:
            mapped["type"] = "405"
        elif "MV" in source_type:
            mapped["type"] = "406"
        elif "音乐" in source_type:
            mapped["type"] = "406"
        elif "综艺" in source_type:
            mapped["type"] = "410"
        elif "纪录片" in source_type:
            mapped["type"] = "411"
        elif "体育" in source_type:
            mapped["type"] = "412"
        elif "短剧" in source_type:
            mapped["type"] = "413"
        else:
            mapped["type"] = "409"

        # 2. 媒介
        medium_str = title_params.get("媒介", "").lower()
        mediainfo_str = self.upload_data.get("mediainfo", "")

        # 检查MediaInfo是否为文件类型（非原盘）
        is_standard_mediainfo = "General" in mediainfo_str and "Complete name" in mediainfo_str

        # 新增判断逻辑：
        # 如果是标准文件类MediaInfo，且原始媒介是蓝光或DVD，则判定为Encode
        if is_standard_mediainfo and ('blu' in medium_str
                                      or 'dvd' in medium_str):
            mapped["medium_sel[4]"] = "7"  # Encode
        elif "web" in medium_str:
            mapped["medium_sel[4]"] = "11"  # WEB-DL
        elif "uhd" in medium_str and "blu" in medium_str:
            mapped["medium_sel[4]"] = "10"  # UHD Blu-ray
        elif "blu" in medium_str:
            mapped["medium_sel[4]"] = "1"  # Blu-ray
        elif "remux" in medium_str:
            mapped["medium_sel[4]"] = "3"  # Remux
        elif "minibd" in medium_str:
            mapped["medium_sel[4]"] = "4"  # MiniBD
        elif "hdtv" in medium_str:
            mapped["medium_sel[4]"] = "5"  # HDTV
        elif "dvd" in medium_str:
            mapped["medium_sel[4]"] = "6"  # DVD
        elif "cd" in medium_str:
            mapped["medium_sel[4]"] = "8"  # CD
        elif "track" in medium_str:
            mapped["medium_sel[4]"] = "9"  # Track
        elif "encode" in medium_str:  # 保留作为备用
            mapped["medium_sel[4]"] = "7"  # Encode
        else:
            mapped["medium_sel[4]"] = "13"  # Other
        # 3. 视频编码
        codec_str = title_params.get("视频编码", "H.264").lower()
        if "264" in codec_str:
            mapped["codec_sel[4]"] = "1"  # H.264/AVC
        elif "av1" in codec_str:
            mapped["codec_sel[4]"] = "2"  # AV1
        elif "vc-1" in codec_str or "vc1" in codec_str:
            mapped["codec_sel[4]"] = "3"  # VC-1
        elif "mpeg-2" in codec_str or "mpeg2" in codec_str:
            mapped["codec_sel[4]"] = "4"  # MPEG-2
        elif "hevc" in codec_str or "265" in codec_str:
            mapped["codec_sel[4]"] = "6"  # H.265/HEVC
        elif "mpeg-4" in codec_str or "mpeg4" in codec_str or "xvid" in codec_str:
            mapped["codec_sel[4]"] = "12"  # MPEG-4/XviD
        elif "other" in codec_str:
            mapped["codec_sel[4]"] = "5"  # Other
        else:
            mapped["codec_sel[4]"] = "1"  # 默认 H.264/AVC

        # 4. 音频编码 (使用 title_params)
        audio_str = str(title_params.get("音频编码", "DTS")).upper()
        if "FLAC" in audio_str:
            mapped["audiocodec_sel[4]"] = "1"
        elif "APE" in audio_str:
            mapped["audiocodec_sel[4]"] = "2"
        elif "DTS:X" in audio_str:
            mapped["audiocodec_sel[4]"] = "15"
        elif "DTS-HD MA" in audio_str:
            mapped["audiocodec_sel[4]"] = "16"
        elif "DTS" in audio_str:
            mapped["audiocodec_sel[4]"] = "3"
        elif "AAC" in audio_str:
            mapped["audiocodec_sel[4]"] = "6"
        elif "DDP" in audio_str or "E-AC3" in audio_str:
            mapped["audiocodec_sel[4]"] = "12"
        elif "TRUEHD ATMOS" in audio_str:
            mapped["audiocodec_sel[4]"] = "11"
        elif "TRUEHD" in audio_str:
            mapped["audiocodec_sel[4]"] = "14"
        elif "LPCM" in audio_str:
            mapped["audiocodec_sel[4]"] = "13"
        elif "OGG" in audio_str:
            mapped["audiocodec_sel[4]"] = "5"
        elif "MP3" in audio_str:
            mapped["audiocodec_sel[4]"] = "4"
        elif "AC3" in audio_str or "DD" in audio_str:
            mapped["audiocodec_sel[4]"] = "8"
        elif "M4A" in audio_str:
            mapped["audiocodec_sel[4]"] = "17"
        elif "WAV" in audio_str:
            mapped["audiocodec_sel[4]"] = "18"
        else:
            mapped["audiocodec_sel[4]"] = "7"  # Other

        # 5. 分辨率 (使用 title_params)
        resolution_str = str(title_params.get("分辨率", "1080p")).upper()
        if "8K" in resolution_str or "4320" in resolution_str:
            mapped["standard_sel[4]"] = "7"
        elif "2160" in resolution_str or "4K" in resolution_str:
            mapped["standard_sel[4]"] = "6"
        elif "2K" in resolution_str or "1440" in resolution_str:
            mapped["standard_sel[4]"] = "5"
        elif "1080" in resolution_str:
            mapped["standard_sel[4]"] = "1"
        elif "720" in resolution_str:
            mapped["standard_sel[4]"] = "3"
        elif "480" in resolution_str:
            mapped["standard_sel[4]"] = "4"
        else:
            mapped["standard_sel[4]"] = "8"  # Other

        # 6. 制作组 (使用 title_params)
        release_group_str = str(title_params.get("制作组", "")).upper()
        if "LUCKWEB" in release_group_str:
            mapped["team_sel[4]"] = "7"
        elif "LUCKMUSIC" in release_group_str:
            mapped["team_sel[4]"] = "8"
        elif "FRDS" in release_group_str:
            mapped["team_sel[4]"] = "9"
        elif "STARFALLWEB" in release_group_str:
            mapped["team_sel[4]"] = "10"
        else:
            mapped["team_sel[4]"] = "5"  # Other

        # 7. 标签 (继续使用 source_params)
        source_tags = source_params.get("标签") or []
        if "国语" in source_tags:
            tags.append(5)
        # 同时检查类型中是否包含“中字”信息
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
        return (f"{intro.get('statement', '')}\n"
                f"{intro.get('poster', '')}\n"
                f"{intro.get('body', '')}\n"
                f"{intro.get('screenshots', '')}")

    def _build_title(self) -> str:
        """
        根据 title_components 参数，按照 lucky 的规则拼接主标题。
        """
        components_list = self.upload_data.get("title_components", [])
        components = {
            item["key"]: item["value"]
            for item in components_list if item.get("value")
        }
        logger.info(f"开始拼接主标题，源参数: {components}")

        # 主标题拼接顺序
        order = [
            "主标题",
            "年份",
            "季集",
            "剧集状态",
            "发布版本",
            "分辨率",
            "媒介",
            "片源平台",
            "视频编码",
            "视频格式",
            "HDR格式",
            "色深",
            "帧率",
            "音频编码",
            "无法识别",
        ]

        title_parts = []
        for key in order:
            value = components.get(key)
            if value:
                if isinstance(value, list):
                    title_parts.append(" ".join(map(str, value)))
                else:
                    title_parts.append(str(value))

        main_part = ".".join(filter(None, title_parts)).replace(" ", ".")

        release_group = components.get("制作组", "NOGROUP")
        if "N/A" in release_group:
            release_group = "NOGROUP"

        final_title = f"{main_part}-{release_group}"

        final_title = re.sub(r"\.{2,}", ".", final_title).strip()

        logger.info(f"拼接完成的主标题: {final_title}")
        return final_title

    def execute_upload(self):
        """
        执行上传的核心逻辑。
        """
        logger.info("正在为 lucky 站点适配上传参数...")

        try:
            mapped_params = self._map_parameters()
            description = self._build_description()
            final_main_title = self._build_title()
            logger.info("参数适配完成。")

            form_data = {
                "name": final_main_title,
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

                logger.info("正在向 lucky 站点提交发布请求...")
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
            logger.error(f"发布到 lucky 站点时发生错误: {e}")
            logger.error(traceback.format_exc())
            return False, f"请求异常: {e}"


def upload(site_info: dict, upload_payload: dict):
    uploader = LuckyUploader(site_info, upload_payload)
    return uploader.execute_upload()
