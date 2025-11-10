from ..uploader import SpecialUploader
import traceback
from loguru import logger


class CrabptUploader(SpecialUploader):

    def _map_parameters(self) -> dict:
        """
        实现CrabPT站点的参数映射逻辑，包含特殊区域的处理（修复版）。
        """
        mapped = {}
        tags = []

        # ✅ 直接使用 migrator 准备好的标准化参数
        standardized_params = self.upload_data.get("standardized_params", {})

        # 降级处理：如果没有标准化参数才重新解析
        if not standardized_params:
            from loguru import logger
            logger.warning("未找到标准化参数，回退到重新解析")
            # 获取数据
            source_params = self.upload_data.get("source_params", {})
            title_components_list = self.upload_data.get("title_components", [])
            title_params = {
                item["key"]: item["value"]
                for item in title_components_list if item.get("value")
            }
        else:
            # 使用标准化参数构建title_params（用于兼容现有逻辑）
            title_params = {
                "类型": standardized_params.get("type", ""),
                "媒介": standardized_params.get("medium", ""),
                "视频编码": standardized_params.get("video_codec", ""),
                "音频编码": standardized_params.get("audio_codec", ""),
                "分辨率": standardized_params.get("resolution", ""),
                "制作组": standardized_params.get("team", ""),
                "片源平台": standardized_params.get("source", ""),
                "格式": standardized_params.get("format", ""),
            }
            source_params = self.upload_data.get("source_params", {})

        # 1. 类型映射 - 根据源类型判断发布区域
        # ✅ 优先使用标准化的type参数
        if standardized_params:
            standardized_type = standardized_params.get("type", "")
            type_mapping = self.config.get("mappings", {}).get("type", {})
            type_value = self._find_mapping(type_mapping, standardized_type)
        else:
            source_type = source_params.get("类型") or ""
            type_mapping = self.config.get("mappings", {}).get("type", {})
            type_value = self._find_mapping(type_mapping, source_type)

        # 判断是否为特别区类型（漫画、游戏、学习、有声书、电子书）
        special_area_types = {"415", "414", "412", "411", "410"}
        is_special_area = type_value in special_area_types

        # 设置相应的类型字段
        if is_special_area:
            mapped["type"] = type_value
            # 设置特别区的显示模式
            mapped["id"] = "specialcat"
            mapped["data-mode"] = "6"
        else:
            mapped["type"] = type_value
            # 设置种子区的显示模式
            mapped["id"] = "browsecat"
            mapped["data-mode"] = "4"

        # 2. 根据区域类型设置相应的参数映射
        if is_special_area:
            # 特别区的映射（电子书等）
            # 格式映射
            format_str = title_params.get("格式", "")
            special_codec_field = self.config.get("form_fields", {}).get(
                "special_codec", "codec_sel[6]")
            format_mapping = self.config.get("mappings", {}).get("format", {})
            mapped[special_codec_field] = self._find_mapping(
                format_mapping, format_str)

            # 特别区音频编码映射
            audio_str = title_params.get("音频编码", "")
            special_audio_field = self.config.get("form_fields", {}).get(
                "special_audio_codec", "audiocodec_sel[6]")
            special_audio_mapping = self.config.get("mappings", {}).get(
                "special_audio_codec", {})
            mapped[special_audio_field] = self._find_mapping(
                special_audio_mapping, audio_str)

            # 特别区制作组映射
            release_group_str = str(title_params.get("制作组", "")).upper()
            special_team_field = self.config.get("form_fields", {}).get(
                "special_team", "team_sel[6]")
            special_team_mapping = self.config.get("mappings",
                                                   {}).get("special_team", {})
            mapped[special_team_field] = self._find_mapping(
                special_team_mapping, release_group_str)

            # 特别区地区映射 - ✅ 优先使用标准化的source参数
            if standardized_params:
                standardized_source = standardized_params.get("source", "")
                special_processing_field = self.config.get("form_fields", {}).get(
                    "special_processing", "processing_sel[6]")
                # 使用source映射（而不是processing映射）
                source_mapping = self.config.get("mappings", {}).get("source", {})
                mapped[special_processing_field] = self._find_mapping(
                    source_mapping, standardized_source)
            else:
                source_str = source_params.get("产地", "") or title_params.get(
                    "片源平台", "")
                special_processing_field = self.config.get("form_fields", {}).get(
                    "special_processing", "processing_sel[6]")
                processing_mapping = self.config.get("mappings",
                                                     {}).get("processing", {})
                mapped[special_processing_field] = self._find_mapping(
                    processing_mapping, source_str)

            # 特别区标签映射
            combined_tags = self._collect_all_tags()
            special_tag_mapping = self.config.get("mappings",
                                                  {}).get("special_tag", {})

            for tag_str in combined_tags:
                tag_id = self._find_mapping(special_tag_mapping, tag_str)
                if tag_id:
                    tags.append(tag_id)

            # 设置特别区标签
            for i, tag_id in enumerate(sorted(list(set(tags)))):
                mapped[f"tags[6][{i}]"] = tag_id
        else:
            # 种子区的映射（使用基类逻辑）
            # 媒介映射
            medium_str = title_params.get("媒介", "")
            mediainfo_str = self.upload_data.get("mediainfo", "")
            is_standard_mediainfo = "General" in mediainfo_str and "Complete name" in mediainfo_str

            medium_field = self.config.get("form_fields",
                                           {}).get("medium", "source_sel[4]")
            medium_mapping = self.config.get("mappings", {}).get("medium", {})

            if is_standard_mediainfo and ('blu' in medium_str.lower()
                                          or 'dvd' in medium_str.lower()):
                encode_value = medium_mapping.get("Encode", "7")
                mapped[medium_field] = encode_value
            else:
                mapped[medium_field] = self._find_mapping(
                    medium_mapping, medium_str, use_length_priority=False)

            # 视频编码映射
            codec_str = title_params.get("视频编码", "")
            codec_field = self.config.get("form_fields",
                                          {}).get("video_codec",
                                                  "codec_sel[4]")
            codec_mapping = self.config.get("mappings",
                                            {}).get("video_codec", {})
            mapped[codec_field] = self._find_mapping(codec_mapping, codec_str)

            # 音频编码映射
            audio_str = title_params.get("音频编码", "")
            audio_field = self.config.get("form_fields",
                                          {}).get("audio_codec",
                                                  "audiocodec_sel[4]")
            audio_mapping = self.config.get("mappings",
                                            {}).get("audio_codec", {})
            mapped[audio_field] = self._find_mapping(audio_mapping, audio_str)

            # 分辨率映射
            resolution_str = title_params.get("分辨率", "")
            resolution_field = self.config.get("form_fields",
                                               {}).get("resolution",
                                                       "standard_sel[4]")
            resolution_mapping = self.config.get("mappings",
                                                 {}).get("resolution", {})
            mapped[resolution_field] = self._find_mapping(
                resolution_mapping, resolution_str)

            # 制作组映射
            release_group_str = str(title_params.get("制作组", "")).upper()
            team_field = self.config.get("form_fields",
                                         {}).get("team", "team_sel[4]")
            team_mapping = self.config.get("mappings", {}).get("team", {})
            mapped[team_field] = self._find_mapping(team_mapping,
                                                    release_group_str)

            # 地区映射 - ✅ 优先使用标准化的source参数
            if standardized_params:
                standardized_source = standardized_params.get("source", "")
                processing_field = self.config.get("form_fields",
                                                   {}).get("processing",
                                                           "processing_sel[4]")
                # 使用source映射（而不是processing映射）
                source_mapping = self.config.get("mappings", {}).get("source", {})
                mapped[processing_field] = self._find_mapping(
                    source_mapping, standardized_source)
            else:
                source_str = source_params.get("产地", "") or title_params.get(
                    "片源平台", "")
                processing_field = self.config.get("form_fields",
                                                   {}).get("processing",
                                                           "processing_sel[4]")
                processing_mapping = self.config.get("mappings",
                                                     {}).get("processing", {})
                mapped[processing_field] = self._find_mapping(
                    processing_mapping, source_str)

            # 标签映射
            combined_tags = self._collect_all_tags()
            tag_mapping = self.config.get("mappings", {}).get("tag", {})

            for tag_str in combined_tags:
                tag_id = self._find_mapping(tag_mapping, tag_str)
                if tag_id:
                    tags.append(tag_id)

            # 设置种子区标签
            for i, tag_id in enumerate(sorted(list(set(tags)))):
                mapped[f"tags[4][{i}]"] = tag_id

        return mapped

    def _build_description(self) -> str:
        """
        重写描述构建方法以添加调试信息
        """
        intro = self.upload_data.get("intro", {})
        description = (f"{intro.get('statement', '')}\n"
                       f"{intro.get('poster', '')}\n"
                       f"{intro.get('body', '')}\n"
                       f"{intro.get('screenshots', '')}")

        return description

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

            # 优先使用 torrent_dir (从 prepare_review_data 传递的种子目录路径)
            torrent_dir = self.upload_data.get("torrent_dir", "")

            # 如果 torrent_dir 不存在或无效，则回退到使用title创建目录
            if not torrent_dir or not os.path.exists(torrent_dir):
                # 创建 tmp 目录如果不存在
                tmp_dir = os.path.join(DATA_DIR, "tmp")
                os.makedirs(tmp_dir, exist_ok=True)

                # 使用种子标题作为文件夹名（与Go端和download_torrent_only保持一致）
                title = self.upload_data.get("title", "")
                if title:
                    # 清理文件名中的非法字符，限制长度为150
                    import re
                    safe_title = re.sub(r'[\\/:*?"<>|]', '_', title)[:150]
                    torrent_dir = os.path.join(tmp_dir, safe_title)
                else:
                    # 如果没有title，使用torrent文件名作为备选
                    torrent_path = self.upload_data.get(
                        "modified_torrent_path", "")
                    if torrent_path:
                        torrent_name = os.path.basename(torrent_path)
                        if torrent_name.endswith('.torrent'):
                            torrent_name = torrent_name[:-8]  # 移除 .torrent 扩展名
                        # 移除 .modified.时间戳 后缀
                        if '.modified.' in torrent_name:
                            torrent_name = torrent_name.split('.modified.')[0]
                        # 清理文件名中的非法字符
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

    def execute_upload(self):
        """
        重写执行上传方法以添加调试信息和完整的参数支持
        """
        from loguru import logger

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

            # 2. 调用由子类实现的 _map_parameters 方法
            mapped_params = self._map_parameters()
            description = self._build_description()
            final_main_title = self._build_title(standardized_params)
            logger.info("参数适配完成。")

            # 2. 从配置读取匿名上传设置
            from config import config_manager
            config = config_manager.get()
            upload_settings = config.get("upload_settings", {})
            anonymous_upload = upload_settings.get("anonymous_upload", True)
            uplver_value = "yes" if anonymous_upload else "no"
            
            # 准备完整的 form_data，包含 CrabPT 站点需要的所有参数
            form_data = {
                "name":
                final_main_title,
                "small_descr":
                self.upload_data.get("subtitle", ""),
                "url":
                self.upload_data.get("imdb_link", "") or "",
                "descr":
                description,
                "technical_info":
                self.upload_data.get("mediainfo", ""),
                "uplver":
                uplver_value,  # 根据配置设置匿名上传
                # 添加 CrabPT 站点可能需要的额外参数
                "douban_link":
                self.upload_data.get("douban_link", ""),
                "original_main_title":
                self.upload_data.get("original_main_title", ""),
                **mapped_params,  # 合并子类映射的特殊参数
            }

            # 保存所有参数到文件用于调试和测试
            self._save_upload_parameters(form_data, mapped_params,
                                         final_main_title, description)

            # 调用父类的execute_upload方法继续执行上传
            return super().execute_upload()

        except Exception as e:
            logger.error(f"发布到 {self.site_name} 站点时发生错误: {e}")
            logger.error(traceback.format_exc())
            return False, f"请求异常: {e}"
