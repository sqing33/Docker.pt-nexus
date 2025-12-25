import os
from loguru import logger
from ..uploader import SpecialUploader


class PtlgsUploader(SpecialUploader):
    """
    PTLGS站点特殊上传器
    处理海报、截图、MediaInfo单独字段的特殊逻辑
    简介主体内容删除，只保留声明内容放到descr字段
    """

    def _build_description(self) -> str:
        """
        PTLGS站点描述构建：
        - 只保留声明内容（如"xx出品"）放到 descr 字段
        - 删除简介主体内容（豆瓣信息等）
        - 海报、截图、MediaInfo 通过单独字段处理
        """
        intro = self.upload_data.get("intro", {})

        # 只保留声明部分，删除豆瓣信息等主体内容
        statement = intro.get("statement", "").strip()

        # 如果声明内容为空，返回空字符串
        if not statement:
            return ""

        return statement

    def _map_parameters(self) -> dict:
        """
        PTLGS站点参数映射：
        - 支持完整的媒介编码参数
        - 处理特殊的标签映射（支持全部22个标签）
        - 字段分离逻辑在 execute_upload 中处理
        """
        # 直接使用 migrator 准备好的标准化参数
        standardized_params = self.upload_data.get("standardized_params", {})

        # 降级处理：如果没有标准化参数才重新解析
        if not standardized_params:
            print("未找到标准化参数，回退到重新解析")
            standardized_params = self._parse_source_data()

        # 使用PTLGS特殊的映射逻辑
        mapped_params = self._map_ptlgs_parameters(standardized_params)

        # 处理标签映射 - PTLGS支持全部22个标签
        tags = self._collect_all_tags()
        tag_mapping = self.mappings.get("tag", {})

        for i, tag_str in enumerate(sorted(list(set(tags)))):
            tag_id = self._find_mapping(tag_mapping, tag_str)
            if tag_id:
                mapped_params[f"tags[4][{i}]"] = tag_id

        return mapped_params

    def _map_ptlgs_parameters(self, standardized_params: dict) -> dict:
        """
        PTLGS站点特殊的参数映射逻辑
        绕过基类的MediaInfo特殊处理，直接进行映射
        """
        mapped_params = {}

        # 处理类型映射
        content_type = standardized_params.get("type", "")
        type_mapping = self.mappings.get("type", {})
        mapped_params["type"] = self._find_mapping(type_mapping, content_type)

        # 处理媒介映射 - PTLGS直接映射，不需要MediaInfo特殊处理
        medium_str = standardized_params.get("medium", "")
        medium_field = self.config.get("form_fields", {}).get("medium", "medium_sel[4]")
        medium_mapping = self.mappings.get("medium", {})
        mapped_params[medium_field] = self._find_mapping(
            medium_mapping, medium_str, use_length_priority=False, mapping_type="medium"
        )

        # 处理视频编码映射
        codec_str = standardized_params.get("video_codec", "")
        codec_field = self.config.get("form_fields", {}).get("video_codec", "codec_sel[4]")
        codec_mapping = self.mappings.get("video_codec", {})
        mapped_params[codec_field] = self._find_mapping(
            codec_mapping, codec_str, mapping_type="video_codec"
        )

        # 处理音频编码映射
        audio_str = standardized_params.get("audio_codec", "")
        audio_field = self.config.get("form_fields", {}).get("audio_codec", "audiocodec_sel[4]")
        audio_mapping = self.mappings.get("audio_codec", {})
        mapped_params[audio_field] = self._find_mapping(
            audio_mapping, audio_str, mapping_type="audio_codec"
        )

        # 处理分辨率映射
        resolution_str = standardized_params.get("resolution", "")
        resolution_field = self.config.get("form_fields", {}).get("resolution", "standard_sel[4]")
        resolution_mapping = self.mappings.get("resolution", {})
        mapped_params[resolution_field] = self._find_mapping(
            resolution_mapping, resolution_str, mapping_type="resolution"
        )

        # 处理制作组映射
        release_group_str = standardized_params.get("team", "")
        team_field = self.config.get("form_fields", {}).get("team", "team_sel[4]")
        team_mapping = self.mappings.get("team", {})
        mapped_params[team_field] = self._find_mapping(team_mapping, release_group_str)

        return mapped_params

    def execute_upload(self):
        """
        执行PTLGS站点的特殊上传逻辑
        处理字段分离：海报→cover，截图→screenshots，MediaInfo→technical_info
        """
        logger.info(f"使用PTLGS特殊上传逻辑处理 {self.site_name} 站点")

        # 1. 获取标准化参数
        standardized_params = self.upload_data.get("standardized_params", {})
        if not standardized_params:
            logger.warning("未找到标准化参数，回退到重新解析")
            standardized_params = self._parse_source_data()

        # 2. 映射参数
        mapped_params = self._map_parameters()

        # 3. 构建标题
        final_main_title = self._build_title(standardized_params)

        # 4. 构建描述（只包含声明内容）
        description = self._build_description()

        # 5. PTLGS字段预处理 - 去掉[img][/img]标签
        intro = self.upload_data.get("intro", {})
        poster = intro.get("poster", "").strip()
        poster = poster.replace("[img]", "").replace("[/img]", "")
        screenshots = intro.get("screenshots", "").strip()
        screenshots = screenshots.replace("[img]", "").replace("[/img]", "")

        # 6. 准备通用的 form_data
        form_data = {
            "name": final_main_title,
            "small_descr": self.upload_data.get("subtitle", ""),
            "url": self.upload_data.get("imdb_link", "") or "",
            "dburl": self.upload_data.get("douban_link", "") or "",
            "pt_gen": self.upload_data.get("douban_link", "") or "",
            "descr": description,
            "technical_info": self.upload_data.get("mediainfo", "").strip(),  # MediaInfo单独字段
            "cover": poster,  # 海报单独字段（无[img]标签）
            "screenshots": screenshots,  # 截图单独字段（无[img]标签）
            **mapped_params,  # 合并映射后的特殊参数
        }

        # 6. 开发环境保存参数（如果启用）
        if os.getenv("DEV_ENV") == "true":
            self._save_dev_params(form_data, standardized_params, final_main_title, description)

        # 7. 执行实际发布或测试模式
        if os.getenv("UPLOAD_TEST_MODE") == "true":
            logger.info("测试模式：跳过实际发布，模拟成功响应")
            success_url = f"https://ptl.gs/details.php?id=999999999&uploaded=1&test=true"
            response = type(
                "MockResponse",
                (),
                {
                    "url": success_url,
                    "text": f"<html><body>发布成功！种子ID: 999999999 - TEST MODE</body></html>",
                    "raise_for_status": lambda: None,
                },
            )()
        else:
            # 实际发布逻辑
            response = self._execute_actual_upload(form_data)

        # 8. 处理响应
        return self._process_response(response)

    def _execute_actual_upload(self, form_data: dict):
        """
        执行实际的文件上传
        """
        import os
        from utils import cookies_raw2jar

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
                    logger.info(
                        f"正在向 {self.site_name} 站点提交发布请求... (尝试 {attempt + 1}/{max_retries})"
                    )
                    response = self.scraper.post(
                        self.post_url,
                        headers=self.headers,
                        cookies=cookie_jar,
                        data=form_data,
                        files=files,
                        timeout=self.timeout,
                    )
                    response.raise_for_status()
                    last_exception = None
                    break

                except Exception as e:
                    last_exception = e
                    logger.warning(f"第 {attempt + 1} 次尝试发布失败: {e}")

                    if attempt < max_retries - 1:
                        import time

                        wait_time = 2**attempt  # 指数退避
                        logger.info(f"等待 {wait_time} 秒后进行第 {attempt + 2} 次尝试...")
                        time.sleep(wait_time)
                    else:
                        logger.error("所有重试均已失败")

            if last_exception:
                raise last_exception

        return response

    def _save_dev_params(
        self, form_data: dict, standardized_params: dict, final_main_title: str, description: str
    ):
        """
        开发环境下保存参数到文件
        """
        import json
        import os
        import re
        from datetime import datetime
        from config import DATA_DIR

        # 使用统一的 torrents 目录
        torrent_dir = os.path.join(DATA_DIR, "tmp", "torrents")
        os.makedirs(torrent_dir, exist_ok=True)

        # 从 upload_data 中获取种子ID和源站点代码
        torrent_id = "unknown"
        source_site_code = "unknown"

        modified_torrent_path = self.upload_data.get("modified_torrent_path", "")
        if modified_torrent_path:
            torrent_filename = os.path.basename(modified_torrent_path)
            match = re.match(r"^([^-]+)-(\d+)-", torrent_filename)
            if match:
                source_site_code = match.group(1)
                torrent_id = match.group(2)

        timestamp = datetime.now().strftime("%Y-%m-%d-%H:%M:%S")
        filename = f"{source_site_code}-{torrent_id}-{self.site_name}-{timestamp}.json"
        filepath = os.path.join(torrent_dir, filename)

        save_data = {
            "site_name": self.site_name,
            "timestamp": timestamp,
            "form_data": form_data,
            "standardized_params": standardized_params,
            "final_main_title": final_main_title,
            "description": description,
            "upload_data_summary": {
                "subtitle": self.upload_data.get("subtitle", ""),
                "douban_link": self.upload_data.get("douban_link", ""),
                "imdb_link": self.upload_data.get("imdb_link", ""),
                "mediainfo_length": len(self.upload_data.get("mediainfo", "")),
                "modified_torrent_path": self.upload_data.get("modified_torrent_path", ""),
            },
        }

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)
            logger.info(f"上传参数已保存到: {filepath}")
        except Exception as save_error:
            logger.error(f"保存参数到文件失败: {save_error}")

    def _process_response(self, response):
        """
        处理上传响应
        """
        final_url = self._post_process_response_url(response.url)

        if "details.php" in final_url and "uploaded=1" in final_url:
            logger.success("发布成功！已跳转到种子详情页。")
            return True, f"发布成功！新种子页面: {final_url}"
        elif "offers.php" in final_url:
            logger.success("发布成功！已跳转到种子详情页。")
            import re

            pattern = r"offers\.php\?id=(\d+)(&off_details.*)?"
            replaced_url = re.sub(pattern, r"details.php?id=\1", final_url)
            return True, f"发布成功！新种子页面: {replaced_url}"
        elif "details.php" in final_url and "existed=1" in final_url:
            logger.success("种子已存在！已跳转到种子详情页。")
            if "该种子已存在" in response.text:
                logger.info("检测到种子已存在的提示信息。")
            return True, f"发布成功！种子已存在，详情页: {final_url}"
        elif "该种子已存在" in response.text:
            logger.success("种子已存在！在页面内容中检测到已存在提示。")
            import re

            url_pattern = r"url=([^&\s]+/details\.php\?id=\d+[^&\s]*)"
            url_match = re.search(url_pattern, response.text)
            if url_match:
                extracted_url = url_match.group(1)
                if not extracted_url.startswith(("http://", "https://")):
                    extracted_url = f"https://{extracted_url}"
                logger.info(f"从响应内容中提取到详情页URL: {extracted_url}")
                return True, f"发布成功！种子已存在，详情页: {extracted_url}"
            else:
                logger.info("未能从响应内容中提取到详情页URL")
                return True, "发布成功！种子已存在，但未能获取详情页链接。"
        elif "你的种子文件已经被人上传过了" in response.text:
            logger.success("种子已存在！PTLGS站点检测到种子已被上传。")
            import re

            url_pattern = r"url=([^&\s]+/details\.php\?id=\d+[^&\s]*)"
            url_match = re.search(url_pattern, response.text)
            if url_match:
                extracted_url = url_match.group(1)
                if not extracted_url.startswith(("http://", "https://")):
                    extracted_url = f"https://{extracted_url}"
                logger.info(f"从响应内容中提取到详情页URL: {extracted_url}")
                return True, f"发布成功！种子已存在，详情页: {extracted_url}"
            else:
                logger.info("未能从响应内容中提取到详情页URL")
                return True, "发布成功！种子已存在，但未能获取详情页链接。"

        # 如果没有匹配成功条件，记录失败信息
        logger.error(f"发布失败，响应URL: {final_url}")
        logger.error(f"响应内容片段: {response.text[:500]}")
        return False, f"发布失败，请检查日志了解详情。"
