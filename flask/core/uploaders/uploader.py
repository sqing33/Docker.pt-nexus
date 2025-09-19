# uploaders/uploader.py

import os
import re
import traceback
import cloudscraper
import yaml
from loguru import logger
from abc import ABC, abstractmethod
from utils import cookies_raw2jar, ensure_scheme, extract_tags_from_mediainfo, extract_origin_from_description


class BaseUploader(ABC):
    """
    重构后的BaseUploader类，采用三层解耦模型：
    1. 数据层：原始数据（source_params, title_components等）
    2. 标准化层：标准化参数（通过source_parsers将原始数据转换为标准化键值对）
    3. 映射层：站点映射（通过mappings将标准化参数映射为站点特定值）
    """

    def __init__(self, site_name: str, site_info: dict, upload_data: dict):
        """
        通用的初始化方法
        """
        self.site_name = site_name
        self.site_info = site_info
        self.upload_data = upload_data
        self.scraper = cloudscraper.create_scraper()

        # 从站点信息动态生成URL和headers
        base_url = ensure_scheme(self.site_info.get("base_url") or "")
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

        # 加载该站点对应的配置文件
        self.config = self._load_site_config(site_name)

        # 从配置中提取source_parsers和mappings
        self.source_parsers = self.config.get("source_parsers", {})
        self.mappings = self.config.get("mappings", {})

    def _load_site_config(self, site_name: str) -> dict:
        """加载站点的YAML配置文件"""
        # 修改配置文件路径到新的位置
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'configs', f'{site_name}.yaml')
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            logger.warning(f"未找到站点 {site_name} 的配置文件 {config_path}，将使用空配置")
            return {}
        except Exception as e:
            logger.error(f"加载站点配置文件时出错: {e}")
            return {}

    def _parse_source_data(self) -> dict:
        """
        解析源数据，将其转换为标准化参数
        使用配置中的source_parsers规则进行解析
        """
        standardized_params = {}

        # 解析source_params
        source_params = self.upload_data.get("source_params", {})
        for key, parser_config in self.source_parsers.get("source_params",
                                                          {}).items():
            source_key = parser_config.get("source_key")
            if source_key and source_key in source_params:
                value = source_params[source_key]
                # 应用转换函数（如果定义了）
                transform = parser_config.get("transform")
                if transform:
                    value = self._apply_transform(value, transform)
                standardized_params[key] = value

        # 解析title_components (只在source_params中没有相应字段时才使用)
        title_components_list = self.upload_data.get("title_components", [])
        title_params = {
            item["key"]: item["value"]
            for item in title_components_list if item.get("value")
        }

        for key, parser_config in self.source_parsers.get(
                "title_components", {}).items():
            source_key = parser_config.get("source_key")
            if source_key and source_key in title_params:
                # 只有当source_params中没有该字段时才使用title_components中的值
                # 或者当source_params中的值为空/N/A时才使用title_components中的值
                # 但是对于制作组，总是使用title_components中的值（因为它更准确）
                standard_key = key  # 在source_parsers中，key就是standard_key
                source_value = standardized_params.get(standard_key)

                # 特殊处理制作组：总是使用title_components中的值
                if standard_key == "team" or source_value == "team.other":
                    value = title_params[source_key]
                    # 添加调试信息
                    print(
                        f"DEBUG: 使用title_components中的值 '{value}' 作为 '{standard_key}' (制作组特殊处理)"
                    )
                    # 应用转换函数（如果定义了）
                    transform = parser_config.get("transform")
                    if transform:
                        value = self._apply_transform(value, transform)
                    standardized_params[standard_key] = value
                elif not source_value or source_value == "N/A" or source_value == "None":
                    value = title_params[source_key]
                    # 添加调试信息
                    print(
                        f"DEBUG: 使用title_components中的值 '{value}' 作为 '{standard_key}'"
                    )
                    # 应用转换函数（如果定义了）
                    transform = parser_config.get("transform")
                    if transform:
                        value = self._apply_transform(value, transform)
                    standardized_params[standard_key] = value
                else:
                    # 添加调试信息
                    print(
                        f"DEBUG: 跳过title_components中的 '{source_key}'，因为source_params中已有值 '{source_value}'"
                    )

        # 应用标准化键映射（如果配置中定义了standard_keys）
        if "standard_keys" in self.source_parsers:
            self._apply_standard_key_mapping(standardized_params)

        return standardized_params

    def _apply_transform(self, value, transform: str):
        """
        应用转换函数到值
        """
        if transform == "upper":
            return str(value).upper() if value else value
        elif transform == "lower":
            return str(value).lower() if value else value
        elif transform == "strip":
            return str(value).strip() if value else value
        elif transform == "list_to_string":
            if isinstance(value, list):
                return " ".join(map(str, value))
            return value
        # 可以添加更多转换函数
        return value

    def _apply_standard_key_mapping(self, standardized_params: dict):
        """
        应用标准化键映射，将原始文本映射到标准化键
        实现"类型：动漫" -> "category.animation" -> "405"的完整映射流程的第一步
        """
        # 获取标准化键映射规则
        standard_keys = self.source_parsers.get("standard_keys", {})

        # 遍历所有需要标准化映射的字段
        for field, mapping_rules in standard_keys.items():
            if field in standardized_params:
                original_value = standardized_params[field]
                # 查找匹配的标准化键
                for source_text, standard_key in mapping_rules.items():
                    # 支持精确匹配和部分匹配
                    if (source_text.lower() == original_value.lower()
                            or source_text.lower() in original_value.lower()
                            or original_value.lower() in source_text.lower()):
                        # 找到匹配项，更新为标准化键
                        standardized_params[field] = standard_key
                        break

    def _find_mapping(self,
                      mapping_dict: dict,
                      key_to_find: str,
                      default_key: str = "default",
                      use_length_priority: bool = True) -> str:
        """
        通用的映射查找函数，支持精确匹配、部分匹配和默认值。
        支持优先级匹配：当key_to_find是列表时，按顺序尝试匹配。
        """
        # 处理 key_to_find 可能是列表的情况（优先级匹配）
        if not mapping_dict or not key_to_find:
            return mapping_dict.get(default_key, "")

        # 如果 key_to_find 是列表，按优先级顺序尝试匹配
        if isinstance(key_to_find, list):
            if not key_to_find:
                return mapping_dict.get(default_key, "")

            # 按顺序尝试列表中的每个元素
            for priority_key in key_to_find:
                if priority_key:  # 跳过空值
                    # 精确匹配
                    for key, value in mapping_dict.items():
                        if key.lower() == str(priority_key).lower().strip():
                            return value

                    # 部分匹配
                    if use_length_priority:
                        # 按 key 长度降序排列，优先匹配更长的 key
                        sorted_items = sorted(mapping_dict.items(),
                                              key=lambda x: len(x[0]),
                                              reverse=True)
                    else:
                        # 按 YAML 中的顺序匹配
                        sorted_items = list(mapping_dict.items())

                    for key, value in sorted_items:
                        # 双向部分匹配
                        if key.lower() in str(priority_key).lower() or str(
                                priority_key).lower() in key.lower():
                            return value

            # 如果所有优先级选项都未匹配，返回默认值
            return mapping_dict.get(default_key, "")

        # 如果 key_to_find 是字符串，使用原有的匹配逻辑
        # 精确匹配
        for key, value in mapping_dict.items():
            if key.lower() == key_to_find.lower().strip():
                return value

        # 部分匹配
        if use_length_priority:
            # 按 key 长度降序排列，优先匹配更长的 key (用于音频编码等场景)
            sorted_items = sorted(mapping_dict.items(),
                                  key=lambda x: len(x[0]),
                                  reverse=True)
        else:
            # 按 YAML 中的顺序匹配 (用于媒介等场景)
            sorted_items = list(mapping_dict.items())

        for key, value in sorted_items:
            # 修改为双向部分匹配：
            # 1. 如果 key 在 key_to_find 中 (例如 key="OurBits", key_to_find="7³ACG@OurBits")
            # 2. 如果 key_to_find 在 key 中 (例如 key="7³ACG@OurBits", key_to_find="OurBits")
            if key.lower() in key_to_find.lower() or key_to_find.lower(
            ) in key.lower():
                return value

        # 返回默认值
        return mapping_dict.get(default_key, "")

    def _map_standardized_params(self, standardized_params: dict) -> dict:
        """
        将标准化参数映射到站点特定参数
        """
        mapped_params = {}
        tags = []

        # 添加调试信息
        print(f"DEBUG: 标准化参数: {standardized_params}")

        # 处理类型映射
        content_type = standardized_params.get("type", "")
        type_mapping = self.mappings.get("type", {})
        mapped_params["type"] = self._find_mapping(type_mapping, content_type)

        # 处理媒介映射
        medium_str = standardized_params.get("medium", "")
        mediainfo_str = self.upload_data.get("mediainfo", "")
        is_standard_mediainfo = "General" in mediainfo_str and "Complete name" in mediainfo_str
        is_bdinfo = "DISC INFO" in mediainfo_str and "PLAYLIST REPORT" in mediainfo_str

        medium_field = self.config.get("form_fields",
                                       {}).get("medium", "medium_sel[4]")
        medium_mapping = self.mappings.get("medium", {})

        if is_standard_mediainfo and ('blu' in medium_str.lower()
                                      or 'dvd' in medium_str.lower()):
            # 从配置文件中获取Encode的映射值
            encode_value = medium_mapping.get("Encode", "7")  # 默认值为7
            mapped_params[medium_field] = encode_value
        elif is_bdinfo and ('blu' in medium_str.lower()
                            or 'dvd' in medium_str.lower()):
            # BDInfo格式的Blu-ray/DVD原盘应该映射为Blu-ray媒介
            mapped_params[medium_field] = self._find_mapping(
                medium_mapping, medium_str, use_length_priority=False)
        else:
            mapped_params[medium_field] = self._find_mapping(
                medium_mapping, medium_str, use_length_priority=False)

        # 处理视频编码映射
        codec_str = standardized_params.get("video_codec", "")
        codec_field = self.config.get("form_fields",
                                      {}).get("video_codec", "codec_sel[4]")
        codec_mapping = self.mappings.get("video_codec", {})

        # 对于视频编码，使用优先级匹配 ["x265", "h265"]
        if codec_str == "video.x265":
            # 创建优先级列表：先尝试x265，如果失败则回退到h265
            codec_priority = ["x265", "X265", "h265", "H.265", "HEVC"]
            codec_result = self._find_mapping(codec_mapping, codec_priority)
        else:
            codec_result = self._find_mapping(codec_mapping, codec_str)

        mapped_params[codec_field] = codec_result
        print(f"DEBUG: 视频编码映射 '{codec_str}' -> '{codec_result}'")

        # 处理音频编码映射
        audio_str = standardized_params.get("audio_codec", "")
        audio_field = self.config.get("form_fields",
                                      {}).get("audio_codec",
                                              "audiocodec_sel[4]")
        audio_mapping = self.mappings.get("audio_codec", {})
        mapped_params[audio_field] = self._find_mapping(
            audio_mapping, audio_str)

        # 处理分辨率映射
        resolution_str = standardized_params.get("resolution", "")
        resolution_field = self.config.get("form_fields",
                                           {}).get("resolution",
                                                   "standard_sel[4]")
        resolution_mapping = self.mappings.get("resolution", {})
        mapped_params[resolution_field] = self._find_mapping(
            resolution_mapping, resolution_str)

        # 处理制作组映射
        release_group_str = standardized_params.get("team", "")
        team_field = self.config.get("form_fields",
                                     {}).get("team", "team_sel[4]")
        team_mapping = self.mappings.get("team", {})
        mapped_params[team_field] = self._find_mapping(team_mapping,
                                                       release_group_str)

        # 处理地区/来源映射（如果配置文件中定义了source字段）
        source_str = standardized_params.get("source", "")
        source_field = self.config.get("form_fields", {}).get("source", None)
        if source_field:
            source_mapping = self.mappings.get("source", {})
            mapped_params[source_field] = self._find_mapping(
                source_mapping, source_str)

        # 处理标签映射
        tag_mapping = self.mappings.get("tag", {})
        combined_tags = self._collect_all_tags()

        for tag_str in combined_tags:
            tag_id = self._find_mapping(tag_mapping, tag_str)
            if tag_id:
                tags.append(tag_id)

        # 去重并格式化标签
        for i, tag_id in enumerate(sorted(list(set(tags)))):
            mapped_params[f"tags[4][{i}]"] = tag_id

        return mapped_params

    def _build_title(self, standardized_params: dict) -> str:
        """
        根据 title_components 参数，按照站点的规则拼接主标题。
        此方法现在直接使用传入的、已正确标准化的参数。
        """
        # 不再自己调用解析函数，因为这会导致使用错误的(目标站)配置进行二次标准化
        # standardized_params = self._parse_source_data()

        logger.info(f"开始拼接主标题，标准化参数: {standardized_params}")

        # 获取原始参数值用于标题构建
        source_params = self.upload_data.get("source_params", {})
        title_components_list = self.upload_data.get("title_components", [])

        # 构建原始值映射
        original_values = {}
        for component in title_components_list:
            key = component.get("key")
            value = component.get("value")
            if key and value:
                original_values[key] = value

        order = [
            "title",
            "season_episode",
            "year",
            "status",
            "edition",
            "resolution",
            "platform",
            "medium",
            "video_codec",
            "video_format",
            "hdr_format",
            "bit_depth",
            "frame_rate",
            "audio_codec",
        ]

        title_parts = []
        for key in order:
            # 优先使用原始值，如果没有则使用标准化值
            if key == "title":
                value = original_values.get("主标题") or original_values.get(
                    "标题") or standardized_params.get(key)
            elif key == "video_codec":
                value = original_values.get("视频编码") or original_values.get(
                    "视频编码") or standardized_params.get(key)
            elif key == "audio_codec":
                value = original_values.get("音频编码") or standardized_params.get(
                    key)
            elif key == "medium":
                value = original_values.get("媒介") or standardized_params.get(
                    key)
            elif key == "resolution":
                value = original_values.get("分辨率") or standardized_params.get(
                    key)
            elif key == "team":
                value = original_values.get("制作组") or standardized_params.get(
                    key)
            else:
                value = standardized_params.get(key)

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

        release_group = standardized_params.get("team", "NOGROUP")
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

    def _build_description(self) -> str:
        """
        根据 intro 数据构建完整的 BBCode 描述。
        """
        intro = self.upload_data.get("intro", {})
        return (f"{intro.get('statement', '')}\n"
                f"{intro.get('poster', '')}\n"
                f"{intro.get('body', '')}\n"
                f"{intro.get('screenshots', '')}")

    def _collect_all_tags(self) -> set:
        """
        收集所有可能的标签来源
        """
        # 从源站参数获取标签
        source_params = self.upload_data.get("source_params", {})
        source_tags = set(source_params.get("标签") or [])

        # 从 MediaInfo 提取标签
        mediainfo_str = self.upload_data.get("mediainfo", "")
        tags_from_mediainfo = set(extract_tags_from_mediainfo(mediainfo_str))

        # 从类型中补充 "中字"
        source_type = source_params.get("类型") or ""
        if "中字" in source_type:
            tags_from_mediainfo.add("中字")

        # 合并所有标签
        combined_tags = source_tags.union(tags_from_mediainfo)

        # 从标题组件中智能匹配HDR等信息
        title_components_list = self.upload_data.get("title_components", [])
        title_params = {
            item["key"]: item["value"]
            for item in title_components_list if item.get("value")
        }
        hdr_str = title_params.get("HDR格式", "").upper()
        if "VISION" in hdr_str or "DV" in hdr_str:
            combined_tags.add("Dolby Vision")
        if "HDR10+" in hdr_str:
            combined_tags.add("HDR10+")
        elif "HDR10" in hdr_str:
            combined_tags.add("HDR10")
        elif "HDR" in hdr_str:
            combined_tags.add("HDR")

        return combined_tags

    def execute_upload(self):
        """
        执行上传的核心逻辑。这是最核心的通用部分。
        """
        logger.info(f"正在为 {self.site_name} 站点适配上传参数...")
        try:
            # 1. 直接从 upload_data 中获取由 migrator 准备好的标准化参数
            standardized_params = self.upload_data.get("standardized_params",
                                                       {})

            # 添加回退和警告逻辑，以防 standardized_params 未被传递
            if not standardized_params:
                logger.warning(
                    "在 upload_data 中未找到 'standardized_params'，回退到旧的、可能不准确的解析逻辑。请检查前端请求。"
                )
                standardized_params = self._parse_source_data()

            # 2. 将标准化参数映射为站点特定参数
            mapped_params = self._map_standardized_params(standardized_params)

            description = self._build_description()
            final_main_title = self._build_title(standardized_params)
            logger.info("参数适配完成。")

            # 3. 准备通用的 form_data
            form_data = {
                "name": final_main_title,
                "small_descr": self.upload_data.get("subtitle", ""),
                "url": self.upload_data.get("imdb_link", "") or "",
                "descr": description,
                "technical_info": self.upload_data.get("mediainfo", ""),
                "uplver": "no",  # 默认匿名上传
                **mapped_params,  # 合并映射后的特殊参数
            }

            # 保存所有参数到文件用于测试
            import json
            import time
            from config import DATA_DIR

            # 创建 tmp 目录如果不存在
            tmp_dir = os.path.join(DATA_DIR, "tmp")
            os.makedirs(tmp_dir, exist_ok=True)

            # 生成唯一文件名
            timestamp = int(time.time())
            filename = f"upload_params_{self.site_name}_{timestamp}.json"
            filepath = os.path.join(tmp_dir, filename)

            # 准备要保存的数据
            save_data = {
                "site_name": self.site_name,
                "timestamp": timestamp,
                "form_data": form_data,
                "standardized_params": standardized_params,
                "final_main_title": final_main_title,
                "description": description,
                "upload_data_summary": {
                    "subtitle":
                    self.upload_data.get("subtitle", ""),
                    "imdb_link":
                    self.upload_data.get("imdb_link", ""),
                    "mediainfo_length":
                    len(self.upload_data.get("mediainfo", "")),
                    "modified_torrent_path":
                    self.upload_data.get("modified_torrent_path", ""),
                }
            }

            # 保存到文件
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(save_data, f, ensure_ascii=False, indent=2)
                logger.info(f"上传参数已保存到: {filepath}")
            except Exception as save_error:
                logger.error(f"保存参数到文件失败: {save_error}")

            # 执行实际发布 【已注释，用于测试模式】
            # torrent_path = self.upload_data["modified_torrent_path"]
            # with open(torrent_path, "rb") as torrent_file:
            #     files = {
            #         "file": (
            #             os.path.basename(torrent_path),
            #             torrent_file,
            #             "application/x-bittorent",
            #         ),
            #         "nfo": ("", b"", "application/octet-stream"),
            #     }
            #     cleaned_cookie_str = self.site_info.get("cookie", "").strip()
            #     if not cleaned_cookie_str:
            #         logger.error("目标站点 Cookie 为空，无法发布。")
            #         return False, "目标站点 Cookie 未配置。"
            #     cookie_jar = cookies_raw2jar(cleaned_cookie_str)
            #     # 添加重试机制
            #     max_retries = 3
            #     last_exception = None

            #     for attempt in range(max_retries):
            #         try:
            #             logger.info(
            #                 f"正在向 {self.site_name} 站点提交发布请求... (尝试 {attempt + 1}/{max_retries})"
            #             )
            #             # 若站点启用代理且配置了全局代理地址，则通过代理请求
            #             proxies = None
            #             try:
            #                 from config import config_manager
            #                 use_proxy = bool(self.site_info.get("proxy"))
            #                 conf = (config_manager.get() or {})
            #                 # 优先使用转种设置中的代理地址，其次兼容旧的 network.proxy_url
            #                 proxy_url = (conf.get("cross_seed", {})
            #                              or {}).get("proxy_url") or (
            #                                  conf.get("network", {})
            #                                  or {}).get("proxy_url")
            #                 if use_proxy and proxy_url:
            #                     proxies = {
            #                         "http": proxy_url,
            #                         "https": proxy_url
            #                     }
            #             except Exception:
            #                 proxies = None

            #             # 检查是否是重试并且 Connection reset by peer 错误，强制使用代理
            #             if attempt > 0 and last_exception and "Connection reset by peer" in str(
            #                     last_exception):
            #                 logger.info(
            #                     "检测到 Connection reset by peer 错误，强制使用代理重试...")
            #                 try:
            #                     from config import config_manager
            #                     conf = (config_manager.get() or {})
            #                     proxy_url = (conf.get("cross_seed", {})
            #                                  or {}).get("proxy_url") or (
            #                                      conf.get("network", {})
            #                                      or {}).get("proxy_url")
            #                     if proxy_url:
            #                         proxies = {
            #                             "http": proxy_url,
            #                             "https": proxy_url
            #                         }
            #                         logger.info(f"使用代理重试: {proxy_url}")
            #                 except Exception as proxy_error:
            #                     logger.warning(f"代理设置失败: {proxy_error}")

            #             response = self.scraper.post(
            #                 self.post_url,
            #                 headers=self.headers,
            #                 cookies=cookie_jar,
            #                 data=form_data,
            #                 files=files,
            #                 timeout=self.timeout,
            #                 proxies=proxies,
            #             )
            #             response.raise_for_status()

            #             # 成功则跳出循环
            #             last_exception = None
            #             break

            #         except Exception as e:
            #             last_exception = e
            #             logger.warning(f"第 {attempt + 1} 次尝试发布失败: {e}")

            #             # 如果不是最后一次尝试，等待一段时间后重试
            #             if attempt < max_retries - 1:
            #                 import time
            #                 wait_time = 2**attempt  # 指数退避
            #                 logger.info(
            #                     f"等待 {wait_time} 秒后进行第 {attempt + 2} 次尝试...")
            #                 time.sleep(wait_time)
            #             else:
            #                 logger.error("所有重试均已失败")

            #     # 如果所有重试都失败了，重新抛出最后一个异常
            #     if last_exception:
            #         raise last_exception

            # 测试模式：模拟成功响应
            logger.info("测试模式：跳过实际发布，模拟成功响应")
            success_url = f"https://demo.site.test/details.php?id=12345&uploaded=1&test=true"
            response = type(
                'MockResponse', (), {
                    'url': success_url,
                    'text':
                    f'<html><body>发布成功！种子ID: 12345 - TEST MODE</body></html>',
                    'raise_for_status': lambda: None
                })()

            # 4. 处理响应（这是通用的成功/失败判断逻辑）
            # 可以通过 "钩子" 方法处理个别站点的URL修正
            final_url = self._post_process_response_url(response.url)

            if "details.php" in final_url and "uploaded=1" in final_url:
                logger.success("发布成功！已跳转到种子详情页。")
                return True, f"发布成功！新种子页面: {final_url}"
            elif "details.php" in final_url and "existed=1" in final_url:
                logger.success("种子已存在！已跳转到种子详情页。")
                # 检查响应内容中是否包含"该种子已存在"的提示
                if "该种子已存在" in response.text:
                    logger.info("检测到种子已存在的提示信息。")
                return True, f"发布成功！种子已存在，详情页: {final_url}"
            elif "login.php" in final_url:
                logger.error("发布失败，Cookie 已失效，被重定向到登录页。")
                return False, "发布失败，Cookie 已失效或无效。"
            else:
                logger.error("发布失败，站点返回未知响应。")
                logger.debug(f"响应URL: {final_url}")
                logger.debug(f"响应内容: {response.text}")
                return False, f"发布失败，请检查站点返回信息。 URL: {final_url}"

        except Exception as e:
            logger.error(f"发布到 {self.site_name} 站点时发生错误: {e}")
            logger.error(traceback.format_exc())
            return False, f"请求异常: {e}"

    def _post_process_response_url(self, url: str) -> str:
        """
        一个 "钩子" 方法，用于处理个别站点的URL修正。
        默认情况下将URL中的大写字母转换为小写。
        子类可以按需重写它。
        """
        # 将URL中的大写字母转换为小写
        return url.lower()

    # ----------------------------------------------------
    # ↓↓↓↓ 以下是需要子类必须实现的核心差异化方法 ↓↓↓↓
    # ----------------------------------------------------

    @abstractmethod
    def _map_parameters(self) -> dict:
        """
        这是一个抽象方法。
        它不包含任何实现，强制要求每个继承BaseUploader的子类
        都必须自己实现这个方法，以提供该站点的参数映射逻辑。
        """
        raise NotImplementedError("每个子类都必须实现 _map_parameters 方法")

    @staticmethod
    def prepare_publish_params(site_name: str, site_info: dict,
                               upload_payload: dict):
        """
        预构建完整的发布参数供前端预览
        """
        try:
            # 添加项目根目录到Python路径
            import sys
            import os
            sys.path.append(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

            from .uploader import create_uploader
            uploader = create_uploader(site_name, site_info, upload_payload)

            # 直接从 payload 获取正确的 standardized_params，而不是重新解析
            standardized_params = upload_payload.get("standardized_params", {})
            if not standardized_params:
                logger.warning("预览参数构建：在 payload 中未找到 'standardized_params'。")
                # 在预览场景下，即使没有也继续，让用户在前端看到可能不完整的数据

            mapped_params = uploader._map_standardized_params(
                standardized_params)
            description = uploader._build_description()
            final_main_title = uploader._build_title(standardized_params)

            # 准备通用的 form_data（与execute_upload中一致）
            form_data = {
                "name": final_main_title,
                "small_descr": upload_payload.get("subtitle", ""),
                "url": upload_payload.get("imdb_link", "") or "",
                "descr": description,
                "technical_info": upload_payload.get("mediainfo", ""),
                "uplver": "no",  # 默认匿名上传
                **mapped_params,  # 合并子类映射的特殊参数
            }

            return {
                "form_data": form_data,
                "standardized_params": standardized_params,
                "final_main_title": final_main_title,
                "description": description
            }
        except Exception as e:
            from loguru import logger
            import traceback
            logger.error(f"{site_name}上传器预构建参数时发生错误: {e}")
            logger.error(traceback.format_exc())
            return {"error": f"参数构建异常: {e}"}

    @staticmethod
    def upload(site_name: str, site_info: dict, upload_payload: dict):
        """
        通用的上传接口
        """
        try:
            # 添加项目根目录到Python路径
            import sys
            import os
            sys.path.append(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

            from .uploader import create_uploader
            uploader = create_uploader(site_name, site_info, upload_payload)
            return uploader.execute_upload()
        except Exception as e:
            from loguru import logger
            import traceback
            logger.error(f"{site_name}上传器执行时发生错误: {e}")
            logger.error(traceback.format_exc())
            return False, f"请求异常: {e}"


class CommonUploader(BaseUploader):
    """
    公共上传器基类，用于处理通用的上传逻辑
    """

    def _map_parameters(self) -> dict:
        """
        实现抽象方法，使用基类的通用映射逻辑
        """
        # 这个方法在新的流程下，其内部逻辑已合并到 execute_upload 中
        # 它本身不应再被直接调用，但为保持结构完整性，我们让它返回正确映射后的参数
        standardized_params = self.upload_data.get("standardized_params", {})
        if not standardized_params:
            standardized_params = self._parse_source_data()  # Fallback
        mapped_params = self._map_standardized_params(standardized_params)
        return mapped_params

    def _should_use_special_handler(self) -> bool:
        """
        判断是否需要使用特殊处理逻辑
        """
        # 检查源站点是否为需要特殊处理的站点
        special_sites = ["人人", "不可说", "憨憨"]
        source_name = getattr(self, '_source_name',
                              None) or self.upload_data.get(
                                  'source_site_name', '')
        return source_name in special_sites

    def execute_upload(self):
        """
        执行上传，根据源站点决定是否使用特殊处理
        """
        if self._should_use_special_handler():
            logger.info(
                f"检测到源站点 {getattr(self, '_source_name', 'unknown')} 需要特殊处理")
            return self._execute_special_upload()
        else:
            logger.info("使用通用上传逻辑")
            return super().execute_upload()

    def _execute_special_upload(self):
        """
        特殊上传逻辑，子类可以重写此方法
        """
        # 默认情况下仍然使用通用逻辑
        return super().execute_upload()


class SpecialUploader(BaseUploader):
    """
    特殊上传器基类，用于处理需要特殊逻辑的站点
    """

    def _map_parameters(self) -> dict:
        """
        实现抽象方法，子类需要重写此方法以实现特殊映射逻辑
        """
        raise NotImplementedError("特殊上传器必须实现 _map_parameters 方法")

    def _should_use_special_handler(self) -> bool:
        """
        判断是否需要使用特殊处理逻辑（总是返回True）
        """
        return True

    def execute_upload(self):
        """
        执行特殊上传逻辑
        """
        logger.info(f"使用特殊上传逻辑处理 {self.site_name} 站点")
        return super().execute_upload()


def create_uploader(site_name: str, site_info: dict,
                    upload_data: dict) -> BaseUploader:
    """
    工厂函数，根据站点名称动态创建对应的上传器实例。

    :param site_name: 站点名称（如 'agsv', 'crabpt' 等）
    :param site_info: 站点信息字典
    :param upload_data: 上传数据字典
    :return: 对应站点的上传器实例
    """
    try:
        # 将站点名称转换为模块名（处理特殊字符）
        module_name = site_name.replace('-', '_').replace('.', '_')

        try:
            # 尝试动态导入站点模块
            site_module = __import__(f"core.uploaders.sites.{module_name}",
                                     fromlist=[module_name])

            # 获取上传器类名（通常是站点名+Uploader）
            class_name = f"{module_name.capitalize()}Uploader"
            # 特殊处理一些站点名称
            if site_name == "13city":
                class_name = "City13Uploader"
            elif site_name == "agsv":
                class_name = "AgsvUploader"
            elif site_name == "crabpt":
                class_name = "CrabptUploader"

            # 获取上传器类
            uploader_class = getattr(site_module, class_name)

            # 创建并返回实例
            return uploader_class(site_name, site_info, upload_data)

        except ImportError:
            # 如果找不到特定站点模块，使用公共上传器
            return CommonUploader(site_name, site_info, upload_data)

    except Exception as e:
        raise Exception(f"创建站点 {site_name} 的上传器时发生错误: {e}")


def get_available_sites() -> list:
    """
    获取所有可用的站点列表。

    :return: 可用站点名称列表
    """
    sites_dir = os.path.join(os.path.dirname(__file__), "sites")
    sites = []

    if os.path.exists(sites_dir):
        for filename in os.listdir(sites_dir):
            if filename.endswith(".py") and filename != "__init__.py":
                site_name = filename[:-3]  # 移除.py扩展名
                # 将模块名转换回站点名
                site_name = site_name.replace('_', '-')
                sites.append(site_name)

    return sites
