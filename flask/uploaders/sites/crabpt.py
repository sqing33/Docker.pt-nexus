from ..base import BaseUploader


class CrabptUploader(BaseUploader):
    def _map_parameters(self) -> dict:
        """
        实现CrabPT站点的参数映射逻辑，包含特殊区域的处理。
        """
        # 首先调用基类的通用映射方法
        mapped = super()._map_parameters()
        tags = []

        # 获取数据
        source_params = self.upload_data.get("source_params", {})
        title_components_list = self.upload_data.get("title_components", [])
        title_params = {
            item["key"]: item["value"]
            for item in title_components_list if item.get("value")
        }

        # 获取已有的标签
        combined_tags = self._collect_all_tags()
        tag_mapping = self.config.get("mappings", {}).get("tag", {})

        for tag_str in combined_tags:
            tag_id = self._find_mapping(tag_mapping, tag_str)
            if tag_id:
                tags.append(tag_id)

        # 9. 特别区的映射（电子书等）
        # 格式映射
        format_str = title_params.get("格式", "")
        special_codec_field = self.config.get("form_fields",
                                              {}).get("special_codec",
                                                      "codec_sel[6]")
        format_mapping = self.config.get("mappings", {}).get("format", {})
        mapped[special_codec_field] = self._find_mapping(
            format_mapping, format_str)

        # 特别区音频编码映射
        audio_str = title_params.get("音频编码", "")
        special_audio_field = self.config.get("form_fields",
                                              {}).get("special_audio_codec",
                                                      "audiocodec_sel[6]")
        special_audio_mapping = self.config.get("mappings", {}).get(
            "special_audio_codec", {})
        mapped[special_audio_field] = self._find_mapping(
            special_audio_mapping, audio_str)

        # 特别区制作组映射
        release_group_str = str(title_params.get("制作组", "")).upper()
        special_team_field = self.config.get("form_fields",
                                             {}).get("special_team",
                                                     "team_sel[6]")
        special_team_mapping = self.config.get("mappings",
                                               {}).get("special_team", {})
        mapped[special_team_field] = self._find_mapping(
            special_team_mapping, release_group_str)

        # 特别区地区映射 (与普通区相同)
        source_str = source_params.get("产地", "") or title_params.get("片源平台", "")
        processing_field = self.config.get("form_fields",
                                           {}).get("processing",
                                                   "processing_sel[4]")
        special_processing_field = self.config.get("form_fields", {}).get(
            "special_processing", "processing_sel[6]")
        # 复用普通区域的映射结果
        mapped[special_processing_field] = mapped.get(processing_field, "1")

        # 特别区标签映射
        special_tag_mapping = self.config.get("mappings",
                                              {}).get("special_tag", {})

        # 映射特别区标签
        for tag_str in combined_tags:
            tag_id = self._find_mapping(special_tag_mapping, tag_str)
            if tag_id and tag_id not in tags:
                tags.append(tag_id)

        # 去重并格式化标签
        for i, tag_id in enumerate(sorted(list(set(tags)))):
            # 同时为两个区域设置标签
            mapped[f"tags[4][{i}]"] = tag_id
            mapped[f"tags[6][{i}]"] = tag_id

        return mapped
