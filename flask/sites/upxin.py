# sites/hdupt.py

import os
import re
import traceback
import cloudscraper
from loguru import logger
from utils import cookies_raw2jar, ensure_scheme, extract_tags_from_mediainfo


class HduptUploader:

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
        将参数映射为 Hdupt 站点所需的表单值。
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

        # 1. 类型映射 (Type) - 根据站点HTML校对
        type_map = {
            "Movies": "401",
            "电影": "401",
            "Driver": "401",
            "Movie": "401",
            "TV Series": "402",
            "电视剧": "402",
            "TV Shows": "403",
            "综艺": "403",
            "Documentaries": "404",
            "记录片": "404",
            "纪录片": "404",
            "Animations": "405",
            "动漫": "405",
            "动画": "405",
            "Anime": "405",
            "MV": "406",
            "Music Videos": "406",
            "演唱会": "406",
            "Sports": "407",
            "体育": "407",
            "HQ Audio": "408",
            "音乐": "408",
            "无损音乐": "408",
            "音频": "408",
            "Games": "410",
            "游戏": "410",
            "其他": "411",
            "Misc": "411",
            "未知": "411",
            "Unknown": "411",
        }
        source_type = source_params.get("类型") or ""
        # 优先完全匹配，然后部分匹配，最后使用默认值
        mapped["type"] = "411"  # 默认值: Misc/其他

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
        # 站点默认值 'Other': 0
        medium_map = {
            'UHD Blu-ray': '11',
            'Blu-ray': '1',
            'BD': '1',
            'Remux': '3',
            'UHD Remux': '15',
            'UHD Remux TV': '16',
            'Remux TV': '12',
            'Encode': '7',
            'Encode TV': '14',
            'WEB-DL': '10',
            'WEBRip': '10',
            'WEB': '10',
            'WEB-DL TV': '13',
            'WEBRip TV': '13',
            'HDTV': '5',
            'TVrip': '5',
            'DVD': '6',
            'MiniBD': '4',
            'CD': '8',
            'Track': '9',
        }
        medium_str = title_params.get("媒介", "")
        mediainfo_str = self.upload_data.get("mediainfo", "")
        is_standard_mediainfo = "General" in mediainfo_str and "Complete name" in mediainfo_str

        # 站点规则：有mediainfo的Blu-ray/DVD源盘rip都算Encode
        if is_standard_mediainfo and ('blu' in medium_str.lower()
                                      or 'dvd' in medium_str.lower()):
            mapped["medium_sel"] = "7"  # Encode
        else:
            mapped["medium_sel"] = "0"  # 默认值: 请选择
            for key, value in medium_map.items():
                if key.lower() in medium_str.lower():
                    mapped["medium_sel"] = value
                    break

        # 3. 视频编码映射 (Video Codec) - 根据站点HTML校对
        # 站点默认值 'Other': 5
        codec_map = {
            'H.265': '14',
            'HEVC': '14',
            'x265': '14',
            'H.264': '1',
            'AVC': '1',
            'x264': '16',
            'VC-1': '2',
            'XviD': '3',
            'MPEG-2': '18',
            'MPEG': '18',
        }
        codec_str = title_params.get("视频编码", "")
        mapped["codec_sel"] = "5"  # 默认值: Other
        for key, value in codec_map.items():
            if key.lower() in codec_str.lower():
                mapped["codec_sel"] = value
                break

        # 4. 音频编码映射 (Audio Codec) - 根据站点HTML校对
        # 站点默认值 'Other': 13
        audio_map = {
            'DTS:X': '16',
            'DTS-HD MA': '1',
            'DTS-HDMA': '1',
            'TrueHD': '3',
            'LPCM': '11',
            'DTS': '4',
            'AC3': '2',
            'EAC3': '2',
            'DD+': '2',
            'DD': '2',
            'AAC': '6',
            'FLAC': '7',
            'APE': '10',
            'WAV': '17',
            'MPEG': '18',
            'MP3': '18',
        }
        audio_str = title_params.get("音频编码", "")
        audio_str_normalized = audio_str.upper().replace(" ",
                                                         "").replace(".", "")
        mapped["audiocodec_sel"] = "13"  # 默认值: Other
        for key, value in audio_map.items():
            key_normalized = key.upper().replace(" ", "").replace(".", "")
            if key_normalized in audio_str_normalized:
                mapped["audiocodec_sel"] = value
                break

        # 5. 分辨率映射 (Resolution) - 根据站点HTML校对
        # 站点默认值 'Other': 0
        resolution_map = {
            '8K': '5',
            '4320p': '5',
            '4K': '5',
            '2160p': '5',
            'UHD': '5',
            '1080p': '1',
            '1080i': '2',
            '720p': '3',
            '720i': '3',
            '480p': '4',
            '480i': '4',
            'SD': '4',
            'iPad': '6',
        }
        resolution_str = title_params.get("分辨率", "")
        mapped["standard_sel"] = "0"  # 默认值: 请选择
        for key, value in resolution_map.items():
            if key.lower() in resolution_str.lower():
                mapped["standard_sel"] = value
                break

        # 6. 处理映射 (Processing) - 根据站点HTML校对
        # 站点默认值 'Other': 7
        processing_map = {
            "中国": "1",
            "CN": "1",
            "大陆": "1",
            "中国内地": "1",
            "香港": "3",
            "HK": "3",
            "台湾": "3",
            "TW": "3",
            "港台": "3",
            "美国": "2",
            "US": "2",
            "欧美": "2",
            "欧洲": "2",
            "EU": "2",
            "日本": "4",
            "JPN": "4",
            "JP": "4",
            "韩国": "5",
            "KR": "5",
            "印度": "6",
            "IN": "6",
            "东南亚": "8",
            "SEA": "8",
        }
        # 优先使用从简介中提取的产地信息，如果没有则使用片源平台
        origin_str = source_params.get("产地", "")
        source_str = origin_str if origin_str else title_params.get("片源平台", "")
        mapped["processing_sel"] = "7"  # 默认值: Other
        for key, value in processing_map.items():
            if key.lower() in source_str.lower():
                mapped["processing_sel"] = value
                break

        # 7. 制作组映射 (Team) - 根据站点HTML校对
        # 站点默认值 'Other': 5
        team_map = {
            "HDU": "2",
        }
        release_group_str = str(title_params.get("制作组", "")).upper()
        mapped["team_sel"] = team_map.get(release_group_str, "5")  # 默认值 Other

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
        根据 title_components 参数，按照 Hdupt 的规则拼接主标题。
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
        logger.info("正在为 好多油 站点适配上传参数...")
        try:
            mapped_params = self._map_parameters()
            description = self._build_description()
            final_main_title = self._build_title()
            logger.info("参数适配完成。")

            form_data = {
                "name": final_main_title,
                "small_descr": self.upload_data.get("subtitle", ""),
                "descr": description,
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
                logger.info("正在向 好多油 站点提交发布请求...")
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
            elif "该种子已存在" in response.text:
                # 特殊处理：好多油站点在种子已存在时可能不会重定向到details.php
                logger.success("种子已存在！")
                logger.info("检测到种子已存在的提示信息。")
                # 尝试从响应中提取种子ID并构造详情页URL
                torrent_id = None
                
                # 方法1: 从响应文本中查找ID
                id_match = re.search(r'id=(\d+)', response.text)
                if not id_match:
                    # 方法2: 从响应URL中查找ID
                    id_match = re.search(r'id=(\d+)', response.url)
                
                if not id_match:
                    # 方法3: 从原始种子文件名中提取
                    original_filename = os.path.basename(self.upload_data.get("original_torrent_path", ""))
                    id_match = re.search(r'id=(\d+)', original_filename)
                
                if not id_match:
                    # 方法4: 尝试更广泛的模式匹配
                    patterns = [
                        r'details\.php\?id=(\d+)',
                        r'"id"\s*:\s*"(\d+)"',
                        r'id["\']\s*:\s*(\d+)',
                        r'href\s*=\s*["\'][^"\']*details\.php\?id=(\d+)',
                    ]
                    for pattern in patterns:
                        id_match = re.search(pattern, response.text, re.IGNORECASE)
                        if id_match:
                            break
                
                if id_match:
                    torrent_id = id_match.group(1)
                    base_url = ensure_scheme(self.site_info.get("base_url"))
                    details_url = f"{base_url}/details.php?id={torrent_id}"
                    logger.info(f"成功构造种子详情页URL: {details_url}")
                    return True, f"发布成功！种子已存在，详情页: {details_url}"
                else:
                    # 如果无法提取ID，仍然返回成功状态以便触发下载器添加
                    logger.warning("无法提取种子ID，将使用基本成功消息。")
                    return True, "发布成功！种子已存在。"
            elif "login.php" in response.url:
                logger.error("发布失败，Cookie 已失效，被重定向到登录页。")
                return False, "发布失败，Cookie 已失效或无效。"
            else:
                logger.error("发布失败，站点返回未知响应。")
                logger.debug(f"响应URL: {response.url}")
                logger.debug(f"响应内容: {response.text}")
                return False, f"发布失败，请检查站点返回信息。 URL: {response.url}"

        except Exception as e:
            logger.error(f"发布到 好多油 站点时发生错误: {e}")
            logger.error(traceback.format_exc())
            return False, f"请求异常: {e}"


def upload(site_info: dict, upload_payload: dict):
    uploader = HduptUploader(site_info, upload_payload)
    return uploader.execute_upload()
