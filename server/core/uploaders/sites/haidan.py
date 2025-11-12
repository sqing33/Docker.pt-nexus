import os
from ..uploader import SpecialUploader
import traceback
from loguru import logger


class HaidanUploader(SpecialUploader):
    """
    Haidan站点特殊上传器
    处理haidan.video站点的特殊上传逻辑
    """

    def _map_parameters(self) -> dict:
        """
        实现Haidan站点的参数映射逻辑
        根据HTML表单分析，haidan站点有以下特殊字段：
        - 豆瓣链接: durl
        - 截图区: preview-pics
        - NFO文件和文本: nfo, nfo-string
        - 季集信息: season, episode
        - 多季剧集/电影合集: collages
        - 制作组后缀: team_suffix (必填)
        - 种子置顶和免费: bonus_sticky, bonus_free
        - 标签: tag_list[]
        """
        mapped = {}
        tags = []

        # ✅ 直接使用 migrator 准备好的标准化参数
        standardized_params = self.upload_data.get("standardized_params", {})

        # 降级处理：如果没有标准化参数才重新解析
        if not standardized_params:
            from loguru import logger
            logger.warning("未找到标准化参数，回退到重新解析")
            # 获取原始数据用于特殊字段处理
            source_params = self.upload_data.get("source_params", {})
            title_components_list = self.upload_data.get(
                "title_components", [])
            title_params = {
                item["key"]: item["value"]
                for item in title_components_list if item.get("value")
            }
        else:
            # 使用标准化参数构建title_params，但制作组要从原始title_components获取
            title_components_list = self.upload_data.get(
                "title_components", [])
            title_params_temp = {
                item["key"]: item["value"]
                for item in title_components_list if item.get("value")
            }
            # 优先使用原始的制作组名称，如果没有则使用标准化参数
            title_params = {
                "制作组":
                title_params_temp.get("制作组",
                                      standardized_params.get("team", "")),
                "季集":
                title_params_temp.get(
                    "季集", standardized_params.get("season_episode", "")),
            }
            source_params = self.upload_data.get("source_params", {})

        # 1. 类型映射 - 使用标准化参数
        content_type = standardized_params.get("type", "")
        type_mapping = self.config.get("mappings", {}).get("type", {})
        mapped["type"] = self._find_mapping(type_mapping, content_type)

        # 2. 媒介映射 - 使用标准化参数
        medium_str = standardized_params.get("medium", "")
        medium_mapping = self.config.get("mappings", {}).get("medium", {})
        mapped["medium_sel"] = self._find_mapping(medium_mapping,
                                                  medium_str,
                                                  use_length_priority=False,
                                                  mapping_type="medium")

        # 3. 视频编码映射 - 使用标准化参数
        codec_str = standardized_params.get("video_codec", "")
        codec_mapping = self.config.get("mappings", {}).get("video_codec", {})
        mapped["codec_sel"] = self._find_mapping(codec_mapping,
                                                 codec_str,
                                                 mapping_type="video_codec")

        # 4. 音频编码映射 - 使用标准化参数
        audio_str = standardized_params.get("audio_codec", "")
        audio_mapping = self.config.get("mappings", {}).get("audio_codec", {})
        mapped["audiocodec_sel"] = self._find_mapping(
            audio_mapping, audio_str, mapping_type="audio_codec")

        # 5. 分辨率映射 - 使用标准化参数
        resolution_str = standardized_params.get("resolution", "")
        resolution_mapping = self.config.get("mappings",
                                             {}).get("resolution", {})
        mapped["standard_sel"] = self._find_mapping(resolution_mapping,
                                                    resolution_str,
                                                    mapping_type="resolution")

        # 6. 制作组后缀 (必填字段)
        release_group_str = title_params.get("制作组", "")
        if release_group_str:
            # 提取制作组后缀，如sGnB, CMCT等
            team_suffix = self._extract_team_suffix(release_group_str)
            mapped["team_suffix"] = team_suffix
        else:
            # 如果没有制作组，使用默认值
            mapped["team_suffix"] = ""

        # 7. 季集信息处理
        season_episode = title_params.get("季集", "")
        if season_episode:
            season, episode = self._parse_season_episode(season_episode)
            if season:
                mapped["season"] = season
            if episode:
                mapped["episode"] = episode
        else:
            # 如果没有季集信息，检查是否为动漫或电视剧类型，如果是则设置季数和集数都为0
            content_type = standardized_params.get("type", "")
            if content_type in ["category.animation", "category.tv_series"]:
                mapped["season"] = "0"
                mapped["episode"] = "0"

        # 8. 多季剧集/电影合集判断
        is_collection = self._is_collection_resource(source_params,
                                                     title_params)
        if is_collection:
            mapped["collages"] = "1"

        # 9. 豆瓣链接处理
        douban_link = self.upload_data.get("douban_link", "")
        if douban_link:
            mapped["durl"] = douban_link

        # 10. 截图区处理
        screenshots = self._extract_screenshots()
        if screenshots:
            mapped["preview-pics"] = screenshots

        # 11. NFO文本处理
        nfo_text = self.upload_data.get("mediainfo", "")
        if nfo_text:
            mapped["nfo-string"] = nfo_text

        # 12. 标签映射
        combined_tags = self._collect_all_tags()
        tag_mapping = self.config.get("mappings", {}).get("tag", {})

        for tag_str in combined_tags:
            tag_id = self._find_mapping(tag_mapping, tag_str)
            if tag_id:
                tags.append(tag_id)

        # 设置标签 (haidan使用tag_list[]格式)
        for i, tag_id in enumerate(sorted(list(set(tags)))):
            mapped[f"tag_list[{i}]"] = tag_id

        # 13. 种子置顶和免费设置 (可选，默认不设置)
        # 可以根据需要添加这些字段
        # mapped["bonus_sticky"] = ""  # 不设置置顶
        # mapped["bonus_free"] = ""    # 不设置免费

        return mapped

    def _extract_team_suffix(self, release_group: str) -> str:
        """
        从制作组名称中提取后缀
        保留原始制作组名称，不做任何转换或截断
        """
        if not release_group:
            return ""

        # 直接返回原始制作组名称，保持原样
        return release_group.strip()

    def _parse_season_episode(self, season_episode: str) -> tuple:
        """
        解析季集信息
        例如: S01E01 -> (01, 01), S02 -> (02, 0)
        """
        if not season_episode:
            return "", ""

        import re
        # 匹配 S01E01 格式
        match = re.search(r'S(\d+)(?:E(\d+))?', season_episode.upper())
        if match:
            season = match.group(1).zfill(2) if match.group(1) else ""
            episode = match.group(2).zfill(2) if match.group(
                2) else "0" if match.group(1) else ""
            return season, episode

        # 匹配 第1季第2集 格式
        match = re.search(r'第(\d+)季(?:第(\d+)集)?', season_episode)
        if match:
            season = match.group(1).zfill(2) if match.group(1) else ""
            episode = match.group(2).zfill(2) if match.group(
                2) else "0" if match.group(1) else ""
            return season, episode

        return "", ""

    def _is_collection_resource(self, source_params: dict,
                                title_params: dict) -> bool:
        """
        判断是否为多季剧集/电影合集
        """
        # 检查标题中是否包含合集关键词
        title = self.upload_data.get("title", "").lower()
        collection_keywords = [
            "合集", "collection", "全集", "complete", "多季", "series"
        ]
        for keyword in collection_keywords:
            if keyword in title:
                return True

        # 检查类型是否为电影合集
        source_type = source_params.get("类型", "").lower()
        if "合集" in source_type or "collection" in source_type:
            return True

        # 检查季集信息，如果有多季信息则可能是合集
        season_episode = title_params.get("季集", "")
        if season_episode and ("多季" in season_episode
                               or "全" in season_episode):
            return True

        return False

    def _extract_screenshots(self) -> str:
        """
        从intro中提取截图链接
        """
        intro = self.upload_data.get("intro", {})
        screenshots = intro.get("screenshots", "")

        # 如果截图区域包含img标签，提取src属性
        import re
        img_urls = re.findall(r'\[img\](.*?)\[/img\]', screenshots)

        if img_urls:
            return "\n".join(img_urls)

        # 如果没有img标签，直接返回原始截图文本
        return screenshots.strip()

    def _build_description(self) -> str:
        """
        重写描述构建方法，适配haidan站点的描述格式
        """
        intro = self.upload_data.get("intro", {})

        # 构建描述，haidan站点可能需要特定的格式
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
        重写执行上传方法，适配haidan站点的特殊需求
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

            # 准备form_data，包含haidan站点需要的所有参数
            form_data = {
                "name": final_main_title,
                "small_descr": self.upload_data.get("subtitle", ""),
                "url": self.upload_data.get("imdb_link", "") or "",
                "descr": description,
                "uplver": uplver_value,  # 根据配置设置匿名上传
                **mapped_params,  # 合并映射的特殊参数
            }

            # 4. 保存参数用于调试
            if os.getenv("UPLOAD_TEST_MODE") == "true":
                self._save_upload_parameters(form_data, mapped_params,
                                             final_main_title, description)

            # 5. 调用父类的execute_upload方法继续执行上传
            return super().execute_upload()

        except Exception as e:
            logger.error(f"发布到 {self.site_name} 站点时发生错误: {e}")
            logger.error(traceback.format_exc())
            return False, f"请求异常: {e}"

    def _save_upload_parameters(self, form_data, mapped_params,
                                final_main_title, description):
        """
        保存上传参数到tmp目录，用于调试和测试
        """
        try:
            import json
            import time
            import os
            from config import DATA_DIR

            # 优先使用 torrent_dir
            torrent_dir = self.upload_data.get("torrent_dir", "")

            if not torrent_dir or not os.path.exists(torrent_dir):
                # 创建 tmp 目录
                tmp_dir = os.path.join(DATA_DIR, "tmp")
                os.makedirs(tmp_dir, exist_ok=True)

                # 使用种子标题作为文件夹名
                title = self.upload_data.get("title", "")
                if title:
                    import re
                    safe_title = re.sub(r'[\\/:*?"<>|]', '_', title)[:150]
                    torrent_dir = os.path.join(tmp_dir, safe_title)
                else:
                    torrent_path = self.upload_data.get(
                        "modified_torrent_path", "")
                    if torrent_path:
                        torrent_name = os.path.basename(torrent_path)
                        if torrent_name.endswith('.torrent'):
                            torrent_name = torrent_name[:-8]
                        if '.modified.' in torrent_name:
                            torrent_name = torrent_name.split('.modified.')[0]
                        import re
                        torrent_name = re.sub(r'[\\/:*?"<>|]', '_',
                                              torrent_name)
                        torrent_dir = os.path.join(tmp_dir, torrent_name)
                    else:
                        torrent_dir = os.path.join(tmp_dir, "unknown_torrent")

                os.makedirs(torrent_dir, exist_ok=True)

            # 生成唯一文件名
            timestamp = int(time.time())
            filename = f"upload_params_{self.site_name}_{timestamp}.json"
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
                    "imdb_link":
                    self.upload_data.get("imdb_link", ""),
                    "douban_link":
                    self.upload_data.get("douban_link", ""),
                    "mediainfo_length":
                    len(self.upload_data.get("mediainfo", "")),
                    "modified_torrent_path":
                    self.upload_data.get("modified_torrent_path", ""),
                }
            }

            # 保存到文件
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)
            logger.info(f"上传参数已保存到: {filepath}")
        except Exception as save_error:
            logger.error(f"保存参数到文件失败: {save_error}")
