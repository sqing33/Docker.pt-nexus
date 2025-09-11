# sites/pandapt.py

import os
import re
import traceback
import cloudscraper
from loguru import logger
from utils import cookies_raw2jar, ensure_scheme, extract_tags_from_mediainfo


class PandaptUploader:

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
        将参数映射为 熊猫 站点所需的表单值。
        - 映射表根据站点 upload.php 的 HTML 源码进行最终校对。
        - 字典的顺序很重要，用于优先匹配更精确的关键词。
        - 任何未匹配到的项目都将自动归类于 'Other' 或不进行选择。
        """
        # 从源站原始参数中获取
        source_params = self.upload_data.get("source_params", {})

        # 从主标题解析结果中获取
        title_components_list = self.upload_data.get("title_components", [])
        title_params = {
            item["key"]: item["value"]
            for item in title_components_list if item.get("value")
        }

        mapped = {}
        tags = []

        # 1. 类型映射 (Type) - 根据站点HTML校对
        type_map = {
            "Movies": "401",
            "电影": "401",
            "Driver": "401",
            "Movie": "401",
            "TV Series": "402",
            "电视剧": "402",
            "Animations": "405",
            "动漫": "405",
            "动画": "405",
            "Anime": "405",
            "TV Shows": "403",
            "综艺": "403",
            "Documentaries": "404",
            "记录片": "404",
            "纪录片": "404",
            "Sports": "407",
            "体育": "407",
            "Software": "412",
            "软件": "412",
            "Games": "411",
            "游戏": "411",
            "MV": "413",
            "演唱会": "413",
            "音乐会": "413",
            "Music Video": "413",
            "Music": "409",
            "音乐": "409",
            "专辑": "409",
            "音轨": "409",
            "音频": "409",
            "短剧": "409",
            "图书": "409",
            "学习": "409",
            "资料": "409",
            "其他": "409",
            "Misc": "409",
            "未知": "409",
            "Unknown": "409",
        }
        source_type = source_params.get("类型") or ""
        # 优先完全匹配，然后部分匹配，最后使用默认值
        mapped["type"] = "409"  # 默认值: 其他

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

        # 2. 媒介映射 (Medium) - 根据站点HTML校对
        medium_map = {
            'UHD Blu-ray': '11',
            'BluRay': '1',
            'Blu-ray': '1',
            'BD': '1',
            'Remux': '3',
            'Encode': '7',
            'MiniBD': '4',
            'WEB-DL': '10',
            'WEBRip': '10',
            'WEB': '10',
            'HDTV': '5',
            'UHDTV': '12',
            'TVrip': '5',
            'DVD': '6',
            'DVDR': '6',
            'CD': '8',
            'Track': '9',
            'HD DVD': '2',
        }
        medium_str = title_params.get("媒介", "")
        mediainfo_str = self.upload_data.get("mediainfo", "")
        is_standard_mediainfo = "General" in mediainfo_str and "Complete name" in mediainfo_str
        
        # 站点规则：有mediainfo的Blu-ray/DVD源盘rip都算Encode
        if is_standard_mediainfo and ('blu' in medium_str.lower()
                                      or 'dvd' in medium_str.lower()):
            mapped["medium_sel[4]"] = "7"  # Encode
        else:
            mapped["medium_sel[4]"] = "13"  # 默认值: Other
            for key, value in medium_map.items():
                if key.lower() in medium_str.lower():
                    mapped["medium_sel[4]"] = value
                    break

        # 3. 视频编码映射 (Video Codec) - 根据站点HTML校对
        codec_map = {
            'H.265': '6',
            'HEVC': '6',
            'x265': '6',
            'H.264': '1',
            'AVC': '1',
            'x264': '1',
            'VP8': '7',
            'VP9': '7',
            'VC-1': '2',
            'XviD': '3',
            'MPEG-2': '4',
            'MPEG-4': '5',
            'AV1': '8',
        }
        codec_str = title_params.get("视频编码", "")
        mapped["codec_sel[4]"] = "5"  # 默认值: Other
        for key, value in codec_map.items():
            if key.lower() in codec_str.lower():
                mapped["codec_sel[4]"] = value
                break

        # 4. 音频编码映射 (Audio Codec) - 根据站点HTML校对
        audio_map = {
            'TrueHD Atmos': '8',
            'DTS:X': '2',
            'DTS-HD MA': '3',
            'DTS-HD': '3',
            'DTS-HR': '18',
            'DDP': '6',
            'DD+': '6',
            'E-AC3': '6',
            'Atmos': '8',
            'TrueHD': '1',
            'DTS': '4',
            'AC3': '5',
            'DD': '5',
            'AAC': '7',
            'FLAC': '11',
            'LPCM': '9',
            'PCM': '9',
            'APE': '12',
            'WAV': '13',
            'MP3': '14',
        }
        audio_str = title_params.get("音频编码", "")
        audio_str_normalized = audio_str.upper().replace(" ",
                                                         "").replace(".", "")
        mapped["audiocodec_sel[4]"] = "16"  # 默认值: Other
        for key, value in audio_map.items():
            key_normalized = key.upper().replace(" ", "").replace(".", "")
            if key_normalized in audio_str_normalized:
                mapped["audiocodec_sel[4]"] = value
                break

        # 5. 分辨率映射 (Resolution) - 根据站点HTML校对
        resolution_map = {
            '8K': '6',
            '4320p': '6',
            '4K': '5',
            '2160p': '5',
            'UHD': '5',
            '1080p': '1',
            '1080i': '2',
            '720p': '3',
            'SD': '7',  # 通用SD
            '480p': '7',
            '480i': '7',
        }
        resolution_str = title_params.get("分辨率", "")
        mapped["standard_sel[4]"] = "8"  # 默认值: Other
        for key, value in resolution_map.items():
            if key.lower() in resolution_str.lower():
                mapped["standard_sel[4]"] = value
                break

        # 6. 地区映射 (Source) - 默认设置为 'Other'
        mapped["source_sel[4]"] = "6"  # 默认值: Other

        # 7. 制作组映射 (Team) - 根据站点HTML校对
        team_map = {
            "Panda": "1",  # Panda(压制组)
            "AilMWeb": "7",  # AilMWeb(流媒体组)
            "AilMTV": "8",  # AilMTV(电视录制组)
            "AilMUpscale": "14",  # AilMUpscale(超分视频组)
            "CatEDU": "15",  # CatEDU(部分禁转)
            "Red Leaves": "22",  # Red Leaves (红叶)
        }
        release_group_str = str(title_params.get("制作组", "")).upper()
        mapped["team_sel[4]"] = team_map.get(release_group_str,
                                             "5")  # 默认值 Other

        # 8. 标签 (Tags) - 根据站点HTML校对
        tag_map = {
            "首发": 2,
            "DIY": 4,
            "国语": 5,
            "中字": 6,
            "Dolby Vision": 8,
            "DV": 8,
            "HDR10+": 9,
            "HDR10": 7,
            "HDR": 7,  # 将通用HDR默认映射到HDR10
            "完结": 10,
            "特效": 12,
            "粤语": 13,
            "纯净版": 16,
            "分集": 17,
        }

        # 从源站参数获取标签
        source_tags = source_params.get("标签") or []

        # 从 MediaInfo 提取标签
        mediainfo_str = self.upload_data.get("mediainfo", "")
        tags_from_mediainfo = extract_tags_from_mediainfo(mediainfo_str)

        # 合并所有标签
        combined_tags = set(source_tags)
        combined_tags.update(tags_from_mediainfo)

        # 从类型中补充 "中字"
        if "中字" in source_type:
            combined_tags.add("中字")

        # 映射标签到站点ID
        for tag_str in combined_tags:
            tag_id = tag_map.get(tag_str)
            if tag_id is not None:
                tags.append(tag_id)

        # 从标题组件中智能匹配HDR等信息 (保留原有逻辑作为补充)
        hdr_str = title_params.get("HDR格式", "").upper()
        if "VISION" in hdr_str or "DV" in hdr_str:
            tags.append(tag_map["Dolby Vision"])
        if "HDR10+" in hdr_str:
            tags.append(tag_map["HDR10+"])
        elif "HDR10" in hdr_str:
            tags.append(tag_map["HDR10"])
        elif "HDR" in hdr_str:
            tags.append(tag_map["HDR"])

        # 去重并格式化
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
        根据 title_components 参数，按照 熊猫 的规则拼接主标题。
        """
        components_list = self.upload_data.get("title_components", [])
        components = {
            item["key"]: item["value"]
            for item in components_list if item.get("value")
        }
        logger.info(f"开始为熊猫拼接主标题，源参数: {components}")

        order = [
            "主标题",
            "季集",
            "年份",
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
        logger.info("正在为 熊猫 站点适配上传参数...")
        try:
            mapped_params = self._map_parameters()
            description = self._build_description()
            final_main_title = self._build_title()
            logger.info("参数适配完成。")

            form_data = {
                "name": final_main_title,
                "small_descr": self.upload_data.get("subtitle", ""),
                "url": self.upload_data.get("imdb_link", "") or "",
                "pt_gen": self.upload_data.get("douban_link", "") or "",
                "descr": description,
                "technical_info": self.upload_data.get("mediainfo", ""),
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
                logger.info("正在向 熊猫 站点提交发布请求...")

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
            logger.error(f"发布到 熊猫 站点时发生错误: {e}")
            logger.error(traceback.format_exc())
            return False, f"请求异常: {e}"


def upload(site_info: dict, upload_payload: dict):
    uploader = PandaptUploader(site_info, upload_payload)
    return uploader.execute_upload()
