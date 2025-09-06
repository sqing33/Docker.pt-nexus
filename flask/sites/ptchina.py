# sites/ptchina.py

import os
import re
import traceback
import cloudscraper
from loguru import logger
from utils import cookies_raw2jar, ensure_scheme


class PtchinaUploader:

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
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/5.0 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        }

    def _map_parameters(self) -> dict:
        """
        将参数映射为 铂金学院 站点所需的表单值。
        - 映射表根据站点 upload.php 的 HTML 源码进行最终校对。
        - 字典的顺序很重要，用于优先匹配更精确的关键词。
        """
        source_params = self.upload_data.get("source_params", {})
        title_components_list = self.upload_data.get("title_components", [])
        title_params = {
            item["key"]: item["value"]
            for item in title_components_list if item.get("value")
        }

        mapped = {}
        tags = []

        # 1. 类型映射 (Type)
        type_map = {
            "Movies": "401",
            "电影": "401",
            "Driver": "401",
            "Movie": "401",
            "TV Series": "402",
            "电视剧": "402",
            "TV Shows": "402",
            "综艺": "402",
            "Documentaries": "404",
            "记录片": "404",
            "纪录片": "404",
        }
        # 扩展映射，将其他类型映射到最接近的选项
        fallback_map = {
            "Animations": "402",
            "动漫": "402",
            "动画": "402",
            "Anime": "402",
            "MV": "402",
            "演唱会": "402",
            "Music Video": "402",
            "Sports": "402",
            "体育": "402",
            "Music": "402",
            "音乐": "402",
            "专辑": "402",
            "音轨": "402",
            "音频": "402",
            "短剧": "402",
            "软件": "402",
            "图书": "402",
            "学习": "402",
            "游戏": "402",
            "音乐会": "402",
            "资料": "402",
            "其他": "401",
            "Misc": "401",
            "未知": "401",
            "Unknown": "401",
        }

        source_type = source_params.get("类型") or ""
        mapped["type"] = "401"  # 默认值: 电影

        # 精确匹配
        for key, value in type_map.items():
            if key.lower() == source_type.lower().strip():
                mapped["type"] = value
                break
        else:
            # 如果没有精确匹配，尝试部分匹配
            for key, value in type_map.items():
                if key.lower() in source_type.lower():
                    mapped["type"] = value
                    break
            else:
                # 最后尝试回退映射
                for key, value in fallback_map.items():
                    if key.lower() in source_type.lower():
                        mapped["type"] = value
                        break

        # 2. 媒介映射 (Medium) - 根据站点HTML校对
        # 站点默认值 'Other': 13
        source_tags = source_params.get("标签") or []
        resolution_str = title_params.get("分辨率", "")
        medium_map = {
            'UHD Blu-ray': '1',
            'BluRay': '5',
            'Blu-ray': '5',
            'BD': '5',
            'Remux': '3',
            'Encode': '8',
            'WEB-DL': '9',
            'WEBRip': '8',
            'WEB': '9',
            'HDTV': '12',
            'TVrip': '12',
            'DVD': '11',
        }
        medium_str = title_params.get("媒介", "")
        mapped["medium_sel[4]"] = "13"  # 默认值: Other
        for key, value in medium_map.items():
            if key.lower() in medium_str.lower():
                mapped["medium_sel[4]"] = value
                break

        # 3. 视频编码映射 (Video Codec)
        codec_map = {
            'H.265': '3',
            'HEVC': '3',
            'x265': '4',
            'H.264': '1',
            'AVC': '1',
            'x264': '2',
            'VC-1': '5',
            'MPEG-2': '11',
            'MPEG-4': '12',
            'XviD': '13',
            'AV1': '14',
        }
        codec_str = title_params.get("视频编码", "")
        mapped["codec_sel[4]"] = "15"  # 默认值: Other
        for key, value in codec_map.items():
            if key.lower() in codec_str.lower():
                mapped["codec_sel[4]"] = value
                break

        # 4. 音频编码映射 (Audio Codec)
        audio_map = {
            'TrueHD Atmos': '1',
            'DDP Atmos': '15',
            'Atmos': '1',
            'DTS:X': '3',
            'DTS X': '3',
            'DTS-HD MA': '4',
            'DTS-HDMA': '4',
            'DTS-HD HR': '5',
            'TrueHD': '6',
            'True-HD': '6',
            'LPCM': '7',
            'DDP': '16',
            'DD+': '16',
            'EAC3': '16',
            'AC3': '18',
            'DD': '18',
            'DTS': '2',
            'AAC': '19',
            'FLAC': '20',
            'APE': '21',
            'WAV': '22',
            'MP3': '23',
        }
        audio_str = title_params.get("音频编码", "")
        audio_str_normalized = audio_str.upper().replace(" ",
                                                         "").replace(".", "")
        mapped["audiocodec_sel[4]"] = "24"  # 默认值: Other
        for key, value in audio_map.items():
            key_normalized = key.upper().replace(" ", "").replace(".", "")
            if key_normalized in audio_str_normalized:
                mapped["audiocodec_sel[4]"] = value
                break

        # 5. 分辨率映射 (Resolution)
        resolution_map = {
            '4K': '1',
            'UHD': '1',
            '2160p': '1',
            '2K': '2',
            '1440p': '2',
            '1080p': '3',
            '1080i': '4',
        }
        mapped["standard_sel[4]"] = "6"  # 默认值: Other
        for key, value in resolution_map.items():
            if key.lower() in resolution_str.lower():
                mapped["standard_sel[4]"] = value
                break

        # 6. 地区映射 (Processing)
        mapped["processing_sel[4]"] = "12"  # 默认值: Other

        # 7. 制作组映射 (Team)
        team_map = {
            "PTChina": "1",
            "CHD": "2",
            "CHDBits": "2",
            "HDC": "3",
            "HDChina": "3",
            "TTG": "4",
            "WiKi": "5",
            "beAst": "21",
            "CMCT": "22",
            "FRDS": "23",
            "HDS": "24",
            "HDSky": "24",
            "OurBits": "25",
            "PTer": "26",
            "PTHome": "29",
            "HDHome": "28",
            "Audiences": "30",
        }
        release_group_str = str(title_params.get("制作组", "")).upper()
        mapped["team_sel[4]"] = team_map.get(release_group_str,
                                             "35")  # 默认值 Other

        # 8. 标签 (Tags)
        tag_map = {
            "首发": 2,
            "DIY": 4,
            "国语": 5,
            "中字": 6,
            "HDR": 7,
            "Dolby Vision": 8,
            "DV": 8,
        }
        for tag in source_tags:
            tag_id = tag_map.get(tag)
            if tag_id is not None:
                tags.append(tag_id)

        hdr_str = title_params.get("HDR格式", "").upper()
        if "VISION" in hdr_str or "DV" in hdr_str:
            tags.append(tag_map["Dolby Vision"])
        elif "HDR" in hdr_str:
            tags.append(tag_map["HDR"])

        if "中字" in source_type:
            tags.append(tag_map["中字"])

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
        根据 title_components 参数，按照 铂金学院 的规则拼接主标题。
        """
        components_list = self.upload_data.get("title_components", [])
        components = {
            item["key"]: item["value"]
            for item in components_list if item.get("value")
        }
        logger.info(f"开始为铂金学院拼接主标题，源参数: {components}")

        order = [
            "主标题",
            "年份",
            "季集",
            "剧集状态",
            "发布版本",
            "分辨率",
            "片源平台",
            "媒介",
            "视频编码",
            "视频格式",
            "HDR格式",
            "色深",
            "帧率",
            "音频编码",
        ]
        title_parts = []
        for key in order:
            value = components.get(key)
            if value:
                if isinstance(value, list):
                    title_parts.append(" ".join(map(str, value)))
                else:
                    title_parts.append(str(value))

        raw_main_part = " ".join(filter(None, title_parts))
        main_part = re.sub(r'(?<!\d)\.(?!\d)', ' ', raw_main_part)
        main_part = re.sub(r'\s+', ' ', main_part).strip()

        release_group = components.get("制作组", "NOGROUP")
        if "N/A" in release_group:
            release_group = "NOGROUP"

        # 对特殊制作组进行处理，不需要添加前缀连字符
        special_groups = ["MNHD-FRDS", "mUHD-FRDS"]
        if release_group in special_groups:
            final_title = f"{main_part} {release_group}"
        else:
            final_title = f"{main_part}-{release_group}"
        final_title = re.sub(r"\s{2,}", " ", final_title).strip()
        logger.info(f"拼接完成的主标题: {final_title}")
        return final_title

    def execute_upload(self):
        """
        执行上传的核心逻辑。
        """
        logger.info("正在为 铂金学院 站点适配上传参数...")
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
                "uplver": "yes",  # 默认匿名上传
                **mapped_params,
            }

            torrent_path = self.upload_data["modified_torrent_path"]
            with open(torrent_path, "rb") as torrent_file:
                files = {
                    "file": (
                        os.path.basename(torrent_path),
                        torrent_file,
                        "application/x-bittorent",
                    ),
                    "nfo": ("", b"", "application/octet-stream"),
                }
                cleaned_cookie_str = self.site_info.get("cookie", "").strip()
                if not cleaned_cookie_str:
                    logger.error("目标站点 Cookie 为空，无法发布。")
                    return False, "目标站点 Cookie 未配置。"
                cookie_jar = cookies_raw2jar(cleaned_cookie_str)
                logger.info("正在向 铂金学院 站点提交发布请求...")

                proxies = None
                try:
                    from config import config_manager
                    use_proxy = bool(self.site_info.get("proxy"))
                    conf = (config_manager.get() or {})
                    proxy_url = (conf.get("cross_seed", {})
                                 or {}).get("proxy_url") or (conf.get(
                                     "network", {}) or {}).get("proxy_url")
                    if use_proxy and proxy_url:
                        proxies = {"http": proxy_url, "https": proxy_url}
                except Exception:
                    proxies = None

                response = self.scraper.post(
                    self.post_url,
                    headers=self.headers,
                    cookies=cookie_jar,
                    data=form_data,
                    files=files,
                    timeout=self.timeout,
                    proxies=proxies,
                )
                response.raise_for_status()

            if "details.php" in response.url and "uploaded=1" in response.url:
                logger.success("发布成功！已跳转到种子详情页。")
                return True, f"发布成功！新种子页面: {response.url}"
            elif "login.php" in response.url:
                logger.error("发布失败，Cookie 已失效，被重定向到登录页。")
                return False, "发布失败，Cookie 已失效或无效。"
            else:
                logger.error("发布失败，站点返回未知响应。")
                logger.debug(f"响应URL: {response.url}")
                logger.debug(f"响应内容: {response.text}")
                return False, f"发布失败，请检查站点返回信息。 URL: {response.url}"

        except Exception as e:
            logger.error(f"发布到 铂金学院 站点时发生错误: {e}")
            logger.error(traceback.format_exc())
            return False, f"请求异常: {e}"


def upload(site_info: dict, upload_payload: dict):
    uploader = PtchinaUploader(site_info, upload_payload)
    return uploader.execute_upload()
