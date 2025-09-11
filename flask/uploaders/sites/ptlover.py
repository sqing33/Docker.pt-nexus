# uploaders/sites/ptlover.py

from ..base import BaseUploader
from loguru import logger


class PtloverUploader(BaseUploader):
    def _map_parameters(self) -> dict:
        """
        实现Ptlover站点的参数映射逻辑。
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
        medium_field = self.config.get("form_fields", {}).get("medium", "medium_sel[4]")
        medium_mapping = self.config.get("mappings", {}).get("medium", {})
        
        if is_standard_mediainfo and ('blu' in medium_str.lower() or 'dvd' in medium_str.lower()):
            mapped[medium_field] = "7"  # Encode
            # 特殊处理：Ptlover需要同时设置两个字段
            mapped["medium_sel[5]"] = "7"
        else:
            medium_value = self._find_mapping(medium_mapping, medium_str)
            mapped[medium_field] = medium_value
            # 特殊处理：Ptlover需要同时设置两个字段
            mapped["medium_sel[5]"] = medium_value
        
        # 3. 视频编码映射
        codec_str = title_params.get("视频编码", "")
        codec_field = self.config.get("form_fields", {}).get("codec", "codec_sel[4]")
        codec_mapping = self.config.get("mappings", {}).get("codec", {})
        codec_value = self._find_mapping(codec_mapping, codec_str)
        mapped[codec_field] = codec_value
        # 特殊处理：Ptlover需要同时设置两个字段
        mapped["codec_sel[5]"] = codec_value
        
        # 4. 分辨率映射
        resolution_str = title_params.get("分辨率", "")
        resolution_field = self.config.get("form_fields", {}).get("resolution", "standard_sel[4]")
        resolution_mapping = self.config.get("mappings", {}).get("resolution", {})
        resolution_value = self._find_mapping(resolution_mapping, resolution_str)
        mapped[resolution_field] = resolution_value
        # 特殊处理：Ptlover需要同时设置两个字段
        mapped["standard_sel[5]"] = resolution_value
        
        # 5. 制作组映射
        release_group_str = str(title_params.get("制作组", "")).upper()
        team_field = self.config.get("form_fields", {}).get("team", "team_sel[4]")
        team_mapping = self.config.get("mappings", {}).get("team", {})
        team_value = self._find_mapping(team_mapping, release_group_str)
        mapped[team_field] = team_value
        # 特殊处理：Ptlover需要同时设置两个字段
        mapped["team_sel[5]"] = team_value
        
        # 6. 来源映射
        origin_str = source_params.get("产地", "")
        source_str = origin_str if origin_str else title_params.get("片源平台", "")
        source_field = self.config.get("form_fields", {}).get("source", "source_sel[4]")
        source_mapping = self.config.get("mappings", {}).get("source", {})
        mapped[source_field] = self._find_mapping(source_mapping, source_str)
        
        # 7. 标签映射
        combined_tags = self._collect_all_tags()
        tag_mapping = self.config.get("mappings", {}).get("tag", {})
        
        # 处理HDR标签的特殊情况
        hdr_str = title_params.get("HDR格式", "").upper()
        if "VISION" in hdr_str or "DV" in hdr_str:
            combined_tags.add("HDR")
        if "HDR10+" in hdr_str:
            combined_tags.add("HDR")
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
        
        # 特殊处理：Ptlover需要同时设置两个标签字段
        for i, tag_id in enumerate(sorted(list(set(tags)))):
            mapped[f"tags[4][{i}]"] = tag_id
            mapped[f"tags[5][{i}]"] = tag_id
            
        return mapped