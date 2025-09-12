# uploaders/base.py

import os
import re
import traceback
import cloudscraper
import yaml  # 需要安装 PyYAML 库
from loguru import logger
from abc import ABC, abstractmethod  # 用于定义抽象方法
from utils import cookies_raw2jar, ensure_scheme, extract_tags_from_mediainfo, extract_origin_from_description


class BaseUploader(ABC):

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

    def _load_site_config(self, site_name: str) -> dict:
        """加载站点的YAML配置文件"""
        config_path = os.path.join('configs', f'{site_name}.yaml')
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            logger.warning(f"未找到站点 {site_name} 的配置文件 {config_path}，将使用空配置")
            return {}

    # ----------------------------------------------------
    # ↓↓↓↓ 以下是完全通用的方法，直接从原脚本复制过来 ↓↓↓↓
    # ----------------------------------------------------

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
        根据 title_components 参数，按照站点的规则拼接主标题。
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

    def _find_mapping(self,
                      mapping_dict: dict,
                      key_to_find: str,
                      default_key: str = "default") -> str:
        """
        通用的映射查找函数，支持精确匹配、部分匹配和默认值。
        """
        # 处理 key_to_find 可能是列表的情况
        if not mapping_dict or not key_to_find:
            return mapping_dict.get(default_key, "")
        
        # 如果 key_to_find 是列表，取第一个元素或将其转换为字符串
        if isinstance(key_to_find, list):
            if not key_to_find:
                return mapping_dict.get(default_key, "")
            # 取列表中的第一个非空元素，或者将整个列表转换为字符串
            key_to_find = key_to_find[0] if key_to_find and key_to_find[0] else str(key_to_find)

        # 精确匹配
        for key, value in mapping_dict.items():
            if key.lower() == key_to_find.lower().strip():
                return value

        # 部分匹配 (按 key 长度降序排列，优先匹配更长的 key)
        sorted_items = sorted(mapping_dict.items(), key=lambda x: len(x[0]), reverse=True)
        for key, value in sorted_items:
            if key.lower() in key_to_find.lower():
                return value

        # 返回默认值
        return mapping_dict.get(default_key, "")

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
            # 1. 调用由子类实现的 _map_parameters 方法
            mapped_params = self._map_parameters()
            description = self._build_description()
            final_main_title = self._build_title()
            logger.info("参数适配完成。")

            # 2. 准备通用的 form_data
            form_data = {
                "name": final_main_title,
                "small_descr": self.upload_data.get("subtitle", ""),
                "url": self.upload_data.get("imdb_link", "") or "",
                "descr": description,
                "technical_info": self.upload_data.get("mediainfo", ""),
                "uplver": "yes",  # 默认匿名上传
                **mapped_params,  # 合并子类映射的特殊参数
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
                # 添加重试机制
                max_retries = 3
                last_exception = None
                
                for attempt in range(max_retries):
                    try:
                        logger.info(f"正在向 {self.site_name} 站点提交发布请求... (尝试 {attempt + 1}/{max_retries})")
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
                        
                        # 检查是否是重试并且 Connection reset by peer 错误，强制使用代理
                        if attempt > 0 and last_exception and "Connection reset by peer" in str(last_exception):
                            logger.info("检测到 Connection reset by peer 错误，强制使用代理重试...")
                            try:
                                from config import config_manager
                                conf = (config_manager.get() or {})
                                proxy_url = (conf.get("cross_seed", {})
                                             or {}).get("proxy_url") or (conf.get(
                                                 "network", {}) or {}).get("proxy_url")
                                if proxy_url:
                                    proxies = {"http": proxy_url, "https": proxy_url}
                                    logger.info(f"使用代理重试: {proxy_url}")
                            except Exception as proxy_error:
                                logger.warning(f"代理设置失败: {proxy_error}")
                        
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
                        
                        # 成功则跳出循环
                        last_exception = None
                        break
                        
                    except Exception as e:
                        last_exception = e
                        logger.warning(f"第 {attempt + 1} 次尝试发布失败: {e}")
                        
                        # 如果不是最后一次尝试，等待一段时间后重试
                        if attempt < max_retries - 1:
                            import time
                            wait_time = 2 ** attempt  # 指数退避
                            logger.info(f"等待 {wait_time} 秒后进行第 {attempt + 2} 次尝试...")
                            time.sleep(wait_time)
                        else:
                            logger.error("所有重试均已失败")
                        
                # 如果所有重试都失败了，重新抛出最后一个异常
                if last_exception:
                    raise last_exception

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
        默认情况下什么都不做，子类可以按需重写它。
        """
        return url

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
