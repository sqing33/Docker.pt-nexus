# uploaders/sites/sewerpt.py

from ..base import BaseUploader
from loguru import logger


class SewerptUploader(BaseUploader):
    def _map_parameters(self) -> dict:
        """
        实现sewerpt下水道站点的参数映射逻辑。
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
        medium_field = self.config.get("form_fields", {}).get("medium", "medium_sel[4]")
        medium_mapping = self.config.get("mappings", {}).get("medium", {})
        mapped[medium_field] = self._find_mapping(medium_mapping, medium_str)
        
        # 3. 视频编码映射
        codec_str = title_params.get("视频编码", "")
        codec_field = self.config.get("form_fields", {}).get("codec", "codec_sel[4]")
        codec_mapping = self.config.get("mappings", {}).get("codec", {})
        mapped[codec_field] = self._find_mapping(codec_mapping, codec_str)
        
        # 4. 音频编码映射
        audio_str = title_params.get("音频编码", "")
        audio_field = self.config.get("form_fields", {}).get("audio_codec", "audiocodec_sel[4]")
        audio_mapping = self.config.get("mappings", {}).get("audio_codec", {})
        mapped[audio_field] = self._find_mapping(audio_mapping, audio_str)
        
        # 5. 分辨率映射
        resolution_str = title_params.get("分辨率", "")
        resolution_field = self.config.get("form_fields", {}).get("resolution", "standard_sel[4]")
        resolution_mapping = self.config.get("mappings", {}).get("resolution", {})
        mapped[resolution_field] = self._find_mapping(resolution_mapping, resolution_str)
        
        # 6. 制作组映射
        release_group_str = str(title_params.get("制作组", "")).upper()
        team_field = self.config.get("form_fields", {}).get("team", "team_sel[4]")
        team_mapping = self.config.get("mappings", {}).get("team", {})
        mapped[team_field] = self._find_mapping(team_mapping, release_group_str)
        
        # 7. 标签映射
        combined_tags = self._collect_all_tags()
        tag_mapping = self.config.get("mappings", {}).get("tag", {})
        
        for tag_str in combined_tags:
            tag_id = self._find_mapping(tag_mapping, tag_str)
            if tag_id:
                tags.append(tag_id)
        
        # 去重并格式化
        for i, tag_id in enumerate(sorted(list(set(tags)))):
            mapped[f"tags[4][{i}]"] = tag_id
            
        # 8. 匿名发布字段（默认开启）
        mapped["uplver"] = "yes"
            
        return mapped