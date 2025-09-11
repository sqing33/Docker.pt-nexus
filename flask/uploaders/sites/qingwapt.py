# uploaders/sites/qingwapt.py

from ..base import BaseUploader
from loguru import logger
import re


class QingwaptUploader(BaseUploader):

    def _build_title(self) -> str:
        """
        根据 title_components 参数，按照站点的规则拼接主标题。
        为qingwapt站点定制，移除了"色深"字段。
        """
        components_list = self.upload_data.get("title_components", [])
        components = {
            item["key"]: item["value"]
            for item in components_list if item.get("value")
        }
        logger.info(f"开始拼接主标题，源参数: {components}")

        # 为qingwapt站点定制的order列表，移除了"色深"
        order = [
            "主标题",
            "季集",
            "年份",
            "发布版本",
            "分辨率",
            "片源平台",
            "媒介",
            "视频编码",
            "视频格式",
            "HDR格式",
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

    def _map_parameters(self) -> dict:
        """
        实现Qingwapt站点的参数映射逻辑。
        """
        mapped = {}
        tags = []

        # 获取数据
        source_params = self.upload_data.get("source_params", {})
        title_components_list = self.upload_data.get("title_components", [])
        title_params = {
            item["key"]: item["value"]
            for item in title_components_list if item.get("value")
        }

        # 1. 类型映射
        source_type = source_params.get("类型") or ""
        type_mapping = self.config.get("mappings", {}).get("type", {})
        mapped["type"] = self._find_mapping(type_mapping, source_type)

        # 2. 媒介映射
        medium_str = title_params.get("媒介", "")
        mediainfo_str = self.upload_data.get("mediainfo", "")
        is_standard_mediainfo = "General" in mediainfo_str and "Complete name" in mediainfo_str

        # 站点规则：有mediainfo的Blu-ray/DVD源盘rip都算Encode
        medium_field = self.config.get("form_fields",
                                       {}).get("medium", "source_sel[4]")
        medium_mapping = self.config.get("mappings", {}).get("medium", {})

        if is_standard_mediainfo and ('blu' in medium_str.lower()
                                      or 'dvd' in medium_str.lower()):
            mapped[medium_field] = "10"  # Encode
        else:
            mapped[medium_field] = self._find_mapping(medium_mapping,
                                                      medium_str)

        # 3. 视频编码映射
        codec_str = title_params.get("视频编码", "")
        codec_field = self.config.get("form_fields",
                                      {}).get("codec", "codec_sel[4]")
        codec_mapping = self.config.get("mappings", {}).get("codec", {})
        mapped[codec_field] = self._find_mapping(codec_mapping, codec_str)

        # 4. 音频编码映射
        audio_str = title_params.get("音频编码", "")
        audio_field = self.config.get("form_fields",
                                      {}).get("audio_codec",
                                              "audiocodec_sel[4]")
        audio_mapping = self.config.get("mappings", {}).get("audio_codec", {})
        mapped[audio_field] = self._find_mapping(audio_mapping, audio_str)

        # 5. 分辨率映射
        resolution_str = title_params.get("分辨率", "")
        resolution_field = self.config.get("form_fields",
                                           {}).get("resolution",
                                                   "standard_sel[4]")
        resolution_mapping = self.config.get("mappings",
                                             {}).get("resolution", {})
        mapped[resolution_field] = self._find_mapping(resolution_mapping,
                                                      resolution_str)

        # 6. 制作组映射
        release_group_str = str(title_params.get("制作组", "")).upper()
        team_field = self.config.get("form_fields",
                                     {}).get("team", "team_sel[4]")
        team_mapping = self.config.get("mappings", {}).get("team", {})
        mapped[team_field] = self._find_mapping(team_mapping,
                                                release_group_str)

        # 7. 标签映射
        combined_tags = self._collect_all_tags()
        tag_mapping = self.config.get("mappings", {}).get("tag", {})

        # 处理HDR标签的特殊情况
        hdr_str = title_params.get("HDR格式", "").upper()
        if "VISION" in hdr_str or "DV" in hdr_str:
            combined_tags.add("杜比视界")
        if "HDR10+" in hdr_str:
            combined_tags.add("HDR10+")
        elif "HDR10" in hdr_str:
            combined_tags.add("HDR")
        elif "HDR" in hdr_str:
            combined_tags.add("HDR")

        # 从类型中补充 "中字"
        if "中字" in source_type:
            combined_tags.add("中字")

        for tag_str in combined_tags:
            tag_id = self._find_mapping(tag_mapping, tag_str)
            if tag_id:
                tags.append(tag_id)

        # 去重并格式化
        for i, tag_id in enumerate(sorted(list(set(tags)))):
            mapped[f"tags[4][{i}]"] = tag_id

        return mapped
