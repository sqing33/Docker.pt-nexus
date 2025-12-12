from ..uploader import SpecialUploader
from loguru import logger
import os
import sys

sys.path.append(
    os.path.join(
        os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))))))
from utils import get_tmdb_url_from_any_source


class HddolbyUploader(SpecialUploader):
    """
    HDDolby站点特殊上传器
    处理hddolby站点的特殊上传逻辑，主要包括：
    - TMDb链接为必填字段（tmdb_url）
    - MediaInfo有单独字段（media_info）
    - 截图有单独字段（screenshots），不是拼接在简介里的
    - 标签使用checkbox格式（tags[]）
    """

    def _map_parameters(self) -> dict:
        """
        实现HDDolby站点的参数映射逻辑
        基于HTML表单分析，hddolby站点有以下特殊字段：
        - TMDb链接: tmdb_url (必填)
        - MediaInfo: media_info (单独字段)
        - 截图: screenshots (单独字段，每行一个URL)
        - 标签: tags[] (checkbox格式)
        """
        mapped = {}
        tags = []

        # ✅ 直接使用 migrator 准备好的标准化参数
        standardized_params = self.upload_data.get("standardized_params", {})

        # 降级处理：如果没有标准化参数才重新解析
        if not standardized_params:
            logger.warning("未找到标准化参数，回退到重新解析")
            standardized_params = self._parse_source_data()

        # 1. 类型映射 - 使用标准化参数
        content_type = standardized_params.get("type", "")
        type_mapping = self.config.get("mappings", {}).get("type", {})
        mapped["type"] = self._find_mapping(type_mapping, content_type)
        logger.debug(f"HDDolby类型映射: '{content_type}' -> '{mapped['type']}'")

        # 2. 媒介映射 - 使用标准化参数
        medium_str = standardized_params.get("medium", "")
        mapped["medium_sel"] = self._find_mapping(self.config.get(
            "mappings", {}).get("medium", {}),
                                                  medium_str,
                                                  use_length_priority=False,
                                                  mapping_type="medium")
        logger.debug(
            f"HDDolby媒介映射: '{medium_str}' -> '{mapped['medium_sel']}'")

        # 3. 视频编码映射 - 使用标准化参数
        codec_str = standardized_params.get("video_codec", "")
        codec_mapping = self.config.get("mappings", {}).get("video_codec", {})
        mapped["codec_sel"] = self._find_mapping(codec_mapping,
                                                 codec_str,
                                                 mapping_type="video_codec")
        logger.debug(
            f"HDDolby视频编码映射: '{codec_str}' -> '{mapped['codec_sel']}'")

        # 4. 音频编码映射 - 使用标准化参数
        audio_str = standardized_params.get("audio_codec", "")
        audio_mapping = self.config.get("mappings", {}).get("audio_codec", {})
        mapped["audiocodec_sel"] = self._find_mapping(
            audio_mapping, audio_str, mapping_type="audio_codec")
        logger.debug(
            f"HDDolby音频编码映射: '{audio_str}' -> '{mapped['audiocodec_sel']}'")

        # 5. 分辨率映射 - 使用标准化参数
        resolution_str = standardized_params.get("resolution", "")
        resolution_mapping = self.config.get("mappings",
                                             {}).get("resolution", {})
        mapped["standard_sel"] = self._find_mapping(resolution_mapping,
                                                    resolution_str,
                                                    mapping_type="resolution")
        logger.debug(
            f"HDDolby分辨率映射: '{resolution_str}' -> '{mapped['standard_sel']}'")

        # 6. 制作组映射 - 使用标准化参数
        team_str = standardized_params.get("team", "")
        team_mapping = self.config.get("mappings", {}).get("team", {})
        mapped["team_sel"] = self._find_mapping(team_mapping, team_str)
        logger.debug(f"HDDolby制作组映射: '{team_str}' -> '{mapped['team_sel']}'")

        # 7. TMDb链接处理（必填字段）
        tmdb_url = self._extract_tmdb_url()
        if tmdb_url:
            mapped["tmdb_url"] = tmdb_url
            logger.debug(f"HDDolby TMDb链接: {tmdb_url}")
        else:
            logger.warning("HDDolby站点要求TMDb链接为必填，但未找到有效的TMDb链接")

        # 8. MediaInfo处理（单独字段）
        mediainfo_text = self.upload_data.get("mediainfo", "")
        if mediainfo_text:
            mapped["media_info"] = mediainfo_text
            logger.debug("HDDolby MediaInfo已添加到单独字段")

        # 9. 截图处理（单独字段，每行一个URL）
        screenshots = self._extract_screenshots_for_hddolby()
        if screenshots:
            mapped["screenshots"] = screenshots
            logger.debug("HDDolby截图已添加到单独字段")

        # 10. 标签映射（checkbox格式）
        combined_tags = self._collect_all_tags()
        tag_mapping = self.config.get("mappings", {}).get("tag", {})

        for tag_str in combined_tags:
            tag_id = self._find_mapping(tag_mapping, tag_str)
            if tag_id:
                tags.append(tag_id)

        # HDDolby使用tags[]格式，每个checkbox一个
        for i, tag_id in enumerate(sorted(list(set(tags)))):
            mapped[f"tags[{i}]"] = tag_id

        logger.debug(
            f"HDDolby标签映射: {list(set(tags))} -> {[mapped[f'tags[{i}]'] for i in range(len(set(tags)))]}"
        )

        return mapped

    def _extract_tmdb_url(self) -> str:
        """
        提取TMDb链接
        优先使用直接的TMDB链接，如果没有则尝试通过IMDb链接转换
        """
        # 获取各种链接
        tmdb_link = self.upload_data.get("tmdb_link", "") or ""
        imdb_link = self.upload_data.get("imdb_link", "") or ""
        douban_link = self.upload_data.get("douban_link", "") or ""

        # 使用转换工具获取TMDB链接
        tmdb_result = get_tmdb_url_from_any_source(imdb_link=imdb_link,
                                                   douban_link=douban_link,
                                                   tmdb_link=tmdb_link)

        # Handle different return types from get_tmdb_url_from_any_source
        if tmdb_result:
            if isinstance(tmdb_result, tuple):
                tmdb_url, _ = tmdb_result
            else:
                tmdb_url = tmdb_result
        else:
            tmdb_url = ""

        if tmdb_url:
            logger.info(f"成功获取TMDB链接: {tmdb_url}")
            return tmdb_url
        else:
            logger.warning("无法获取TMDB链接，HDDolby站点要求此字段为必填")
            return ""

    def _extract_screenshots_for_hddolby(self) -> str:
        """
        为HDDolby站点提取截图链接
        HDDolby要求每行一个截图URL，不需要BBCode格式
        """
        intro = self.upload_data.get("intro", {})
        screenshots = intro.get("screenshots", "")

        if not screenshots:
            return ""

        # 提取BBCode中的img标签内容
        import re
        img_urls = re.findall(r'\[img\](.*?)\[/img\]', screenshots)

        if img_urls:
            # 每行一个URL，不需要BBCode
            return "\n".join(img_urls)

        # 如果没有img标签，检查是否已经是纯文本URL（每行一个）
        lines = screenshots.strip().split('\n')
        url_lines = []
        for line in lines:
            line = line.strip()
            if line and ('http' in line or 'https' in line):
                # 如果行中包含BBCode，尝试提取URL
                if '[' in line and ']' in line:
                    urls = re.findall(r'https?://[^\s\[\]]+', line)
                    url_lines.extend(urls)
                else:
                    url_lines.append(line)

        return "\n".join(url_lines) if url_lines else screenshots.strip()

    def _build_description(self) -> str:
        """
        重写描述构建方法，适配HDDolby站点的描述格式
        由于截图和MediaInfo都有单独字段，描述中只需要包含简介内容
        """
        intro = self.upload_data.get("intro", {})

        # HDDolby的描述字段只需要简介内容，不需要截图和MediaInfo
        statement = intro.get('statement', '').strip()
        poster = intro.get('poster', '').strip()
        body = intro.get('body', '').strip()

        # 组合描述，确保适当的换行
        description_parts = []

        if statement:
            description_parts.append(statement)

        if poster:
            description_parts.append(poster)

        if body:
            description_parts.append(body)

        description = "\n\n".join(filter(None, description_parts))

        return description

    def execute_upload(self):
        """
        重写执行上传方法，适配HDDolby站点的特殊需求
        """
        logger.info(f"正在为 {self.site_name} 站点适配上传参数...")
        try:
            # 1. 获取标准化参数
            standardized_params = self.upload_data.get("standardized_params",
                                                       {})
            if not standardized_params:
                logger.warning(
                    "在 upload_data 中未找到 'standardized_params'，回退到旧的解析逻辑。")

            # 2. 调用参数映射方法
            mapped_params = self._map_parameters()
            description = self._build_description()
            final_main_title = self._build_title(standardized_params)
            logger.info("参数适配完成。")

            # 3. 从配置读取匿名上传设置
            from config import config_manager
            config = config_manager.get()
            upload_settings = config.get("upload_settings", {})
            anonymous_upload = upload_settings.get("anonymous_upload", True)
            uplver_value = "yes" if anonymous_upload else "no"

            # 准备form_data，包含HDDolby站点需要的所有参数
            form_data = {
                "name": final_main_title,
                "small_descr": self.upload_data.get("subtitle", ""),
                "tmdb_url": mapped_params.get("tmdb_url",
                                              ""),  # HDDolby特有的TMDb链接
                "descr": description,
                "media_info": mapped_params.get("media_info",
                                                ""),  # HDDolby特有的MediaInfo字段
                "screenshots": mapped_params.get("screenshots",
                                                 ""),  # HDDolby特有的截图字段
                "uplver": uplver_value,  # 根据配置设置匿名上传
                **mapped_params,  # 合并映射的特殊参数
            }

            # 4. 保存参数用于调试
            if os.getenv("DEV_ENV") == "true":
                self._save_upload_parameters(form_data, mapped_params,
                                             final_main_title, description)

            # 5. 调用父类的execute_upload方法继续执行上传
            return super().execute_upload()

        except Exception as e:
            logger.error(f"发布到 {self.site_name} 站点时发生错误: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False, f"请求异常: {e}"

    def _save_upload_parameters(self, form_data, mapped_params,
                                final_main_title, description):
        """
        保存上传参数到tmp目录，用于调试和测试
        """
        try:
            import json
            import os
            from datetime import datetime
            from config import DATA_DIR

            # 使用统一的 torrents 目录
            torrent_dir = os.path.join(DATA_DIR, "tmp", "torrents")
            os.makedirs(torrent_dir, exist_ok=True)

            # 从 upload_data 中获取种子ID和源站点代码
            torrent_id = "unknown"
            source_site_code = "unknown"

            modified_torrent_path = self.upload_data.get(
                "modified_torrent_path", "")
            if modified_torrent_path:
                torrent_filename = os.path.basename(modified_torrent_path)
                # 尝试从文件名中提取站点代码和种子ID（格式: 站点代码-种子ID-xxx.torrent）
                import re
                match = re.match(r"^([^-]+)-(\d+)-", torrent_filename)
                if match:
                    source_site_code = match.group(1)
                    torrent_id = match.group(2)

            # 生成可读的时间戳格式: YYYY-MM-DD-HH:MM:SS
            timestamp = datetime.now().strftime("%Y-%m-%d-%H:%M:%S")

            # 格式: {站点代码}-{种子ID}-{目标站点self.site_name}-{时间戳}
            filename = f"{source_site_code}-{torrent_id}-{self.site_name}-{timestamp}.json"
            filepath = os.path.join(torrent_dir, filename)

            # 准备要保存的数据
            save_data = {
                "site_name": self.site_name,
                "timestamp": timestamp,
                "form_data": form_data,
                "mapped_params": mapped_params,
                "final_main_title": final_main_title,
                "description": description,
                "upload_data_summary": {
                    "subtitle":
                    self.upload_data.get("subtitle", ""),
                    "douban_link":
                    self.upload_data.get("douban_link", ""),
                    "imdb_link":
                    self.upload_data.get("imdb_link", ""),
                    "tmdb_link":
                    self.upload_data.get("tmdb_link", ""),
                    "mediainfo_length":
                    len(self.upload_data.get("mediainfo", "")),
                    "modified_torrent_path":
                    self.upload_data.get("modified_torrent_path", ""),
                }
            }

            # 保存到文件
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)
            logger.info(f"HDDolby上传参数已保存到: {filepath}")
        except Exception as save_error:
            logger.error(f"保存参数到文件失败: {save_error}")
