# sites/cspt.py

import os
import re
import traceback
import cloudscraper
from loguru import logger
from utils import cookies_raw2jar, ensure_scheme, extract_tags_from_mediainfo


class CsptUploader:

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
        将参数映射为 财神 站点所需的表单值。
        - 映射表根据站点 upload.php 的 HTML 源码进行最终校对。
        - 字典的顺序很重要，用于优先匹配更精确的关键词。
        - 任何未匹配到的项目都将自动归类于 'Other'。
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

        # 1. 类型映射 (Type)
        type_map = {
            "Music": "408",
            "音乐": "408",
            "HQ音乐": "408",
            "专辑": "408",
            "音轨": "408",
            "音频": "408",
            "Audio": "408",
            "Sports": "407",
            "体育": "407",
            "MV": "406",
            "演唱会": "406",
            "Music Video": "406",
            "Documentaries": "404",
            "记录片": "404",
            "纪录片": "404",
            "TV Shows": "403",
            "综艺": "403",
            "TV Series": "402",
            "电视剧": "402",
            "Movies": "401",
            "电影": "401",
            "Driver": "401",
            "Movie": "401",
            "Animations": "405",
            "动漫": "405",
            "动画": "405",
            "Anime": "405",
            "软件": "409",
            "图书": "409",
            "学习": "409",
            "游戏": "409",
            "音乐会": "409",
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
        # 站点默认值 'Other': 16
        medium_map = {
            'UHD Blu-ray': '8',
            'BluRay': '7',
            'Blu-ray': '7',
            'BD': '7',
            'Remux': '9',
            'Encode': '10',
            'WEB-DL': '11',
            'WEBRip': '11',
            'WEB': '11',
            'HDTV': '12',
            'TVrip': '12',
            'DVD': '13',
            'CD': '14',
            'Track': '15',
        }
        medium_str = title_params.get("媒介", "")
        mediainfo_str = self.upload_data.get("mediainfo", "")
        is_standard_mediainfo = "General" in mediainfo_str and "Complete name" in mediainfo_str

        # 站点规则：有mediainfo的Blu-ray/DVD源盘rip都算Encode
        if is_standard_mediainfo and ('blu' in medium_str.lower()
                                      or 'dvd' in medium_str.lower()):
            mapped["source_sel[4]"] = "10"  # Encode
        else:
            mapped["source_sel[4]"] = "16"  # 默认值: Other
            for key, value in medium_map.items():
                if key.lower() in medium_str.lower():
                    mapped["source_sel[4]"] = value
                    break

        # 3. 视频编码映射 (Video Codec) - 根据站点HTML校对
        # 站点默认值 'Other': 5
        codec_map = {
            'H.265': '2',
            'HEVC': '2',
            'x265': '2',
            'H.264': '1',
            'AVC': '1',
            'x264': '1',
            'VC-1': '3',
            'MPEG-2': '4',
            'AV1': '6',
        }
        codec_str = title_params.get("视频编码", "")
        mapped["codec_sel[4]"] = "5"  # 默认值: Other
        for key, value in codec_map.items():
            if key.lower() in codec_str.lower():
                mapped["codec_sel[4]"] = value
                break

        # 4. 音频编码映射 (Audio Codec) - 根据站点HTML校对
        # 站点默认值 'Other': 23
        audio_map = {
            'TrueHD Atmos': '11',
            'DTS:X': '16',
            'DTS-HD MA': '17',
            'DDP': '12',
            'DD+': '12',
            'E-AC3': '12',
            'Atmos': '11',
            'TrueHD': '15',
            'DTS': '18',
            'AC3': '13',
            'DD': '13',
            'LPCM': '14',
            'FLAC': '22',
            'AAC': '9',
            'ALAC': '8',
            'APE': '10',
            'M4A': '19',
            'WAV': '20',
            'MP3': '21',
        }
        audio_str = title_params.get("音频编码", "")
        audio_str_normalized = audio_str.upper().replace(" ",
                                                         "").replace(".", "")
        mapped["audiocodec_sel[4]"] = "23"  # 默认值: Other
        for key, value in audio_map.items():
            key_normalized = key.upper().replace(" ", "").replace(".", "")
            if key_normalized in audio_str_normalized:
                mapped["audiocodec_sel[4]"] = value
                break

        # 5. 分辨率映射 (Resolution) - 根据站点HTML校对
        # 站点默认值 'Other': 9
        resolution_map = {
            '8K': '8',
            '4320p': '8',
            '4K': '7',
            '2160p': '7',
            'UHD': '7',
            '2K': '10',
            '1440p': '10',
            '1080p': '6',
            '1080i': '6',
            '720p': '5',
            '480p': '4',
            '480i': '4',
        }
        resolution_str = title_params.get("分辨率", "")
        mapped["standard_sel[4]"] = "9"  # 默认值: Other
        for key, value in resolution_map.items():
            if key.lower() in resolution_str.lower():
                mapped["standard_sel[4]"] = value
                break

        # 6. 制作组映射 (Team) - 根据站点HTML校对
        # 站点默认值 'Other': 5
        team_map = {
            "CSPT": "19",
            "CSWEB": "18",
            "HSPT": "8",
            "HSWEB": "9",
        }
        release_group_str = str(title_params.get("制作组", "")).upper()
        mapped["team_sel[4]"] = team_map.get(release_group_str,
                                             "5")  # 默认值 Other

        # 7. 标签 (Tags)
        source_tags = source_params.get("标签") or []
        tag_map = {
            "驻站": 23,
            "首发": 2,
            "DIY": 4,
            "国语": 5,
            "中字": 6,
            "HDR": 7,
            "独家": 13,
            "自压": 14,
            "重制": 15,
            "外挂字幕": 16,
            "Remux": 10,
            "大包": 17,
            "超分": 18,
            "补帧": 19,
            "粤语": 12,
            "特效": 20,
            "杜比": 11,
            "喜剧": 8,
            "分集": 21,
            "完结": 9,
            "儿童": 24,
        }

        # --- [核心修改] 开始: 整合来自多源的标签 ---
        # 1. 从源站参数获取标签
        combined_tags = set(source_params.get("标签") or [])

        # 2. 从 MediaInfo 提取标签
        mediainfo_str = self.upload_data.get("mediainfo", "")
        tags_from_mediainfo = extract_tags_from_mediainfo(mediainfo_str)
        for tag in tags_from_mediainfo:
            # 特殊处理：将 'Dolby Vision' 映射到财神的 '杜比' 标签
            if tag == 'Dolby Vision':
                combined_tags.add('杜比')
            else:
                combined_tags.add(tag)

        # 3. 从类型中补充 "中字"
        if "中字" in source_type:
            combined_tags.add("中字")

        # 4. 将所有收集到的标签字符串映射为站点ID
        for tag_str in combined_tags:
            tag_id = tag_map.get(tag_str)
            if tag_id is not None:
                tags.append(tag_id)
        # --- [核心修改] 结束 ---

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
        根据 title_components 参数，按照 财神 的规则拼接主标题。
        """
        components_list = self.upload_data.get("title_components", [])
        components = {
            item["key"]: item["value"]
            for item in components_list if item.get("value")
        }
        logger.info(f"开始拼接主标题，源参数: {components}")

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

        # [修改] 使用正则表达式替换分隔符，以保护数字中的小数点（例如 5.1）
        raw_main_part = " ".join(filter(None, title_parts))
        # r'(?<!\d)\.(?!\d)' 的意思是：匹配一个点，但前提是它的前面和后面都不是数字
        main_part = re.sub(r'(?<!\d)\.(?!\d)', ' ', raw_main_part)
        # 额外清理，将可能产生的多个空格合并为一个
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
        logger.info("正在为 财神 站点适配上传参数...")
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
                logger.info("正在向 财神 站点提交发布请求...")
                # 若站点启用代理且配置了全局代理地址，则通过代理请求
                proxies = None
                try:
                    from config import config_manager
                    use_proxy = bool(self.site_info.get("proxy"))
                    conf = (config_manager.get() or {})
                    # 优先使用转种设置中的代理地址，其次兼容旧的 network.proxy_url
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
            logger.error(f"发布到 财神 站点时发生错误: {e}")
            logger.error(traceback.format_exc())
            return False, f"请求异常: {e}"


def upload(site_info: dict, upload_payload: dict):
    uploader = CsptUploader(site_info, upload_payload)
    return uploader.execute_upload()
