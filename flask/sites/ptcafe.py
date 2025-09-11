# sites/ptcafe.py

import os
import re
import traceback
import cloudscraper
from loguru import logger
from utils import cookies_raw2jar, ensure_scheme, extract_tags_from_mediainfo


class PtcafeUploader:

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
        将参数映射为 Ptcafe 站点所需的表单值。
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

        # 1. 类型映射 (Type) - 根据站点HTML校对
        type_map = {
            "Movies": "401",
            "电影": "401",
            "Driver": "401",
            "Movie": "401",
            "TV Series": "402",
            "电视剧": "402",
            "剧集": "402",
            "TV Shows": "403",
            "综艺": "403",
            "Documentaries": "404",
            "记录片": "404",
            "纪录片": "404",
            "纪录": "404",
            "Animations": "405",
            "动漫": "405",
            "动画": "405",
            "Anime": "405",
            "MV": "406",
            "演唱会": "406",
            "演唱": "406",
            "Sports": "407",
            "体育": "407",
            "Music": "408",
            "音乐": "408",
            "专辑": "408",
            "音轨": "408",
            "音频": "408",
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

        # 2. 来源映射 (Source) - 根据站点HTML校对
        # 站点默认值 '其他': 7
        source_map = {
            "中国": "1",
            "CN": "1",
            "大陆": "1",
            "香港": "2",
            "HK": "2",
            "台湾": "2",
            "TW": "2",
            "港台": "2",
            "美国": "3",
            "US": "3",
            "欧美": "3",
            "欧洲": "3",
            "EU": "3",
            "日本": "4",
            "JPN": "4",
            "JP": "4",
            "韩国": "5",
            "KR": "5",
            "印度": "6",
            "IN": "6",
        }
        # 优先使用从简介中提取的产地信息，如果没有则使用片源平台
        origin_str = source_params.get("产地", "")
        source_str = origin_str if origin_str else title_params.get("片源平台", "")
        mapped["source_sel[4]"] = "7"  # 默认值: 其他
        for key, value in source_map.items():
            if key.lower() in source_str.lower():
                mapped["source_sel[4]"] = value
                break

        # 3. 媒介映射 (Medium) - 根据站点HTML校对
        # 站点默认值 'Other': 13
        medium_map = {
            'UHD Blu-ray': '1',  # 原盘
            'UHD BD': '1',
            'UHD Blu-ray DIY': '2',
            'UHD Remux': '3',
            'Blu-ray': '4',  # 原盘
            'BD': '4',
            'Blu-ray DIY': '5',
            'Remux': '6',
            'Encode': '7',
            'WEB-DL': '8',
            'WEBRip': '8',
            'WEB': '8',
            'HDTV': '9',
            'TV': '9',
            'TVrip': '9',
            'DVD': '10',
            'CD': '11',
            'Track': '12',
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

        # 4. 视频编码映射 (Video Codec) - 根据站点HTML校对
        # 站点默认值 'Other': 11
        codec_map = {
            'H.265': '1',
            'HEVC': '1',
            'H.264': '2',
            'AVC': '2',
            'x265': '3',
            'x264': '4',
            'VC-1': '5',
            'MPEG-2': '6',
            'MPEG-4': '7',
            'XVID': '8',
            'VP9': '9',
            'DIVX': '10',
        }
        codec_str = title_params.get("视频编码", "")
        mapped["codec_sel[4]"] = "11"  # 默认值: Other
        for key, value in codec_map.items():
            if key.lower() in codec_str.lower():
                mapped["codec_sel[4]"] = value
                break

        # 5. 音频编码映射 (Audio Codec) - 根据站点HTML校对
        # 站点默认值 'Other': 18
        audio_map = {
            'DTS-HD MA': '2',
            'DTS-HDMA': '2',
            'DTS-HD HR': '3',
            'DTS-HDHR': '3',
            'DTS-HD': '4',
            'DTS:X': '5',
            'DTS-X': '5',
            'LPCM': '6',
            'AC3': '7',
            'DD': '7',
            'Atmos': '8',
            'AAC': '9',
            'TrueHD': '10',
            'DTS': '11',
            'FLAC': '12',
            'APE': '13',
            'MP3': '14',
            'WAV': '15',
            'OPUS': '16',
            'OGG': '17',
        }
        audio_str = title_params.get("音频编码", "")
        audio_str_normalized = audio_str.upper().replace(" ",
                                                         "").replace(".", "")
        mapped["audiocodec_sel[4]"] = "18"  # 默认值: Other
        for key, value in audio_map.items():
            key_normalized = key.upper().replace(" ", "").replace(".", "")
            if key_normalized in audio_str_normalized:
                mapped["audiocodec_sel[4]"] = value
                break

        # 6. 分辨率映射 (Resolution) - 根据站点HTML校对
        # 站点默认值 'Other': 6
        resolution_map = {
            '8K': '1',
            '4320p': '1',
            'FUHD': '1',
            '4K': '2',
            '2160p': '2',
            'UHD': '2',
            '1080p': '3',
            '1080i': '3',
            'FHD': '3',
            '720p': '4',
            '720i': '4',
            'HD': '4',
            '360p': '5',
            '360i': '5',
            'SD': '5',
        }
        resolution_str = title_params.get("分辨率", "")
        mapped["standard_sel[4]"] = "6"  # 默认值: Other
        for key, value in resolution_map.items():
            if key.lower() in resolution_str.lower():
                mapped["standard_sel[4]"] = value
                break

        # 7. 制作组映射 (Team) - 根据站点HTML校对
        # 站点默认值 'Other': 30
        team_map = {
            "ADE": "1",
            "ADWeb": "2",
            "Audies": "3",
            "beAst": "4",
            "BeiTai": "5",
            "BeyondHD": "6",
            "BtsTV": "7",
            "CafeTV": "8",
            "CafeWEB": "9",
            "CHDBits": "10",
            "CHDWEB": "11",
            "CMCT": "12",
            "DJWEB": "13",
            "FRDS": "14",
            "HDCTV": "15",
            "HDH": "16",
            "HDHome": "17",
            "HDSky": "18",
            "HDSWEB": "19",
            "HHWEB": "20",
            "MTeam": "21",
            "MWeb": "22",
            "OurBits": "23",
            "OurTV": "24",
            "PTCafe": "25",
            "PTerWEB": "26",
            "QHstudIo": "27",
            "TTG": "28",
            "WiKi": "29",
        }
        release_group_str = str(title_params.get("制作组", "")).upper()
        mapped["team_sel[4]"] = team_map.get(release_group_str,
                                             "30")  # 默认值 Other

        # 8. 标签 (Tags) - 根据站点HTML校对
        tag_map = {
            "官方": 1,
            "首发": 2,
            "完结": 3,
            "原创": 4,
            "禁转": 5,
            "国语": 7,
            "粤语": 8,
            "中字": 9,
            "备胎": 10,
            "杜比视界": 11,
            "HDR": 12,
            "DIY": 13,
            "应求": 14,
            "高码高帧": 15,
            "月月": 16,
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
            combined_tags.add("杜比视界")
        if "HDR10+" in hdr_str:
            combined_tags.add("HDR")
        elif "HDR10" in hdr_str:
            combined_tags.add("HDR")
        elif "HDR" in hdr_str:
            combined_tags.add("HDR")

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
        根据 title_components 参数，按照 Ptcafe 的规则拼接主标题。
        """
        components_list = self.upload_data.get("title_components", [])
        components = {
            item["key"]: item["value"]
            for item in components_list if item.get("value")
        }
        logger.info(f"开始拼接主标题，源参数: {components}")

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
        logger.info("正在为 Ptcafe 站点适配上传参数...")
        try:
            mapped_params = self._map_parameters()
            description = self._build_description()
            final_main_title = self._build_title()
            logger.info("参数适配完成。")

            form_data = {
                "name": final_main_title,
                "small_descr": self.upload_data.get("subtitle", ""),
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
                logger.info("正在向 Ptcafe 站点提交发布请求...")
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
                # 将URL转换为小写以避免后续步骤失败
                corrected_url = response.url.lower()
                return True, f"发布成功！新种子页面: {corrected_url}"
            elif "details.php" in response.url and "existed=1" in response.url:
                logger.success("种子已存在！已跳转到种子详情页。")
                # 检查响应内容中是否包含"该种子已存在"的提示
                if "该种子已存在" in response.text:
                    logger.info("检测到种子已存在的提示信息。")
                return True, f"发布成功！种子已存在，详情页: {response.url}"
            elif "login.php" in response.url:
                logger.error("发布失败，Cookie 已失效，被重定向到登录页。")
                return False, "发布失败，Cookie 已失效或无效。"
            else:
                logger.error("发布失败，站点返回未知响应。")
                logger.debug(f"响应URL: {response.url}")
                logger.debug(f"响应内容: {response.text}")
                return False, f"发布失败，请检查站点返回信息。 URL: {response.url}"

        except Exception as e:
            logger.error(f"发布到 Ptcafe 站点时发生错误: {e}")
            logger.error(traceback.format_exc())
            return False, f"请求异常: {e}"


def upload(site_info: dict, upload_payload: dict):
    uploader = PtcafeUploader(site_info, upload_payload)
    return uploader.execute_upload()
