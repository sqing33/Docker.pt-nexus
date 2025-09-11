# sites/gtkpw.py

import os
import re
import traceback
import cloudscraper
from loguru import logger
from utils import cookies_raw2jar, ensure_scheme, extract_tags_from_mediainfo


class GtkpwUploader:

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
        将参数映射为 GTK 站点所需的表单值。
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
            "演唱会": "406",
            "Music Video": "406",
            "Sports": "407",
            "体育": "407",
            "Music": "409",
            "音乐": "409",
            "专辑": "409",
            "音轨": "409",
            "音频": "409",
            "Audio": "409",
            "短剧": "410",
            "软件": "410",
            "图书": "410",
            "学习": "410",
            "游戏": "410",
            "音乐会": "410",
            "资料": "410",
            "其他": "410",
            "Misc": "410",
            "未知": "410",
            "Unknown": "410",
        }
        source_type = source_params.get("类型") or ""
        # 优先完全匹配，然后部分匹配，最后使用默认值
        mapped["type"] = "410"  # 默认值: 其他

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

        # 2. 媒介映射 (Medium)
        medium_map = {
            'UHD Blu-ray': '10',
            'Blu-ray': '1',
            'BluRay': '1',
            'HD DVD': '2',
            'Remux': '3',
            'Encode': '7',
            'MiniBD': '4',
            'WEB-DL': '11',
            'WEB': '11',
            'WEBRip': '11',
            'HDTV': '5',
            'DVDR': '6',
            'CD': '8',
            'Track': '9',
        }
        medium_str = title_params.get("媒介", "")
        mediainfo_str = self.upload_data.get("mediainfo", "")
        is_standard_mediainfo = "General" in mediainfo_str and "Complete name" in mediainfo_str
        
        # 站点规则：有mediainfo的Blu-ray/DVD源盘rip都算Encode
        if is_standard_mediainfo and ('blu' in medium_str.lower()
                                      or 'dvd' in medium_str.lower()):
            mapped["medium_sel[4]"] = "7"  # Encode
        else:
            for key, value in medium_map.items():
                if key.lower() in medium_str.lower():
                    mapped["medium_sel[4]"] = value
                    break

        # 3. 视频编码映射 (Video Codec)
        codec_map = {
            'H.265': '6',
            'HEVC': '6',
            'x265': '6',
            'H.264': '1',
            'AVC': '1',
            'x264': '1',
            'VC-1': '2',
            'XviD': '3',
            'MPEG-2': '4',
            'AV1': '7',
            'VP9': '8',
        }
        codec_str = title_params.get("视频编码", "")
        mapped["codec_sel[4]"] = "5"  # 默认值: Other
        for key, value in codec_map.items():
            if key.lower() in codec_str.lower():
                mapped["codec_sel[4]"] = value
                break

        # GTK 没有音频编码选项，故注释掉
        # # 4. 音频编码映射 (Audio Codec)
        # audio_map = {}
        # audio_str = title_params.get("音频编码", "")

        # 5. 分辨率映射 (Resolution)
        resolution_map = {
            '8K': '6',
            '4320p': '6',
            '4K': '5',
            '2160p': '5',
            '1080p': '1',
            '1080i': '2',
            '720p': '3',
            'SD': '4',
        }
        resolution_str = title_params.get("分辨率", "")
        for key, value in resolution_map.items():
            if key.lower() in resolution_str.lower():
                mapped["standard_sel[4]"] = value
                break

        # 6. 制作组映射 (Team)
        team_map = {
            "CMCT": "6",
            "HDS": "1",
            "CHD": "2",
            "MYSILU": "3",
            "WIKI": "4",
            "MARK": "7",
            "MTEAM": "8",
            "FRDS": "9",
            "PTHOME": "10",
            "BEAST": "11",
        }
        release_group_str = str(title_params.get("制作组", "")).upper()
        mapped["team_sel[4]"] = team_map.get(release_group_str,
                                             "5")  # 默认值 Other

        # 7. 标签 (Tags) - 根据站点HTML校对
        tag_map = {
            "首发": 2,
            "完结": 9,
            "分集": 8,
            "粤语": 13,
            "多语": 10,
            "国语": 5,
            "中字": 6,
            "中英双字": 14,
            "4K": 12,
            "1080p": 11,
            "HDR": 7,
            "DIY": 4,
            "红叶转载": 19,
            "有声图书": 15,
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

        # 从标题组件中智能匹配HDR等信息
        hdr_str = title_params.get("HDR格式", "").upper()
        if "VISION" in hdr_str or "DV" in hdr_str:
            combined_tags.add("HDR")
        if "HDR10+" in hdr_str:
            combined_tags.add("HDR")
        elif "HDR10" in hdr_str:
            combined_tags.add("HDR")
        elif "HDR" in hdr_str:
            combined_tags.add("HDR")

        # 映射标签到站点ID
        for tag_str in combined_tags:
            tag_id = tag_map.get(tag_str)
            if tag_id is not None:
                tags.append(tag_id)

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
        根据 title_components 参数，按照 GTK 的规则拼接主标题。
        """
        components_list = self.upload_data.get("title_components", [])
        components = {
            item["key"]: item["value"]
            for item in components_list if item.get("value")
        }
        logger.info(f"开始为 GTK 拼接主标题，源参数: {components}")

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
        logger.info("正在为 GTK 站点适配上传参数...")
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
                logger.info("正在向 GTK 站点提交发布请求...")

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
            elif "details.php" in response.url and "existed=1" in response.url:
                logger.success("种子已存在！已跳转到种子详情页。")
                # 检查响应内容中是否包含"该种子已存在"的提示
                if "该种子已存在" in response.text:
                    logger.info("检测到种子已存在的提示信息。")
                return True, f"发布成功！种子已存在，详情页: {response.url}"
            elif "该种子已存在" in response.text:
                # 特殊处理：GTK站点在种子已存在时可能不会重定向到details.php
                logger.success("种子已存在！")
                logger.info("检测到种子已存在的提示信息。")
                # 尝试从响应中提取种子ID并构造详情页URL
                torrent_id = None
                
                # 方法1: 从响应URL中查找ID
                id_match = re.search(r'id=(\d+)', response.url)
                
                if not id_match:
                    # 方法2: 从响应文本中查找ID
                    id_match = re.search(r'id=(\d+)', response.text)
                
                if not id_match:
                    # 方法3: 从下载链接中提取ID
                    download_match = re.search(r'download\.php\?id=(\d+)', response.text)
                    if download_match:
                        torrent_id = download_match.group(1)
                
                if id_match:
                    torrent_id = id_match.group(1)
                
                if torrent_id:
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
            logger.error(f"发布到 GTK 站点时发生错误: {e}")
            logger.error(traceback.format_exc())
            return False, f"请求异常: {e}"


def upload(site_info: dict, upload_payload: dict):
    uploader = GtkpwUploader(site_info, upload_payload)
    return uploader.execute_upload()
