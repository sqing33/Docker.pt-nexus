# uploaders/sites/hdkyl.py

from ..base import BaseUploader
from loguru import logger


class HdkylUploader(BaseUploader):
    def _map_parameters(self) -> dict:
        """
        实现Hdkyl站点的参数映射逻辑。
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
        
        # 2. 年代映射
        year_str = title_params.get("年份", "")
        if year_str and year_str.isdigit():
            year = int(year_str)
            processing_field = self.config.get("form_fields", {}).get("processing", "processing_sel[4]")
            processing_mapping = self.config.get("mappings", {}).get("processing", {})
            
            if year == 2025:
                mapped[processing_field] = "11"
            elif year == 2024:
                mapped[processing_field] = "10"
            elif year == 2023:
                mapped[processing_field] = "1"
            elif year == 2022:
                mapped[processing_field] = "2"
            elif year == 2021:
                mapped[processing_field] = "3"
            elif year == 2020:
                mapped[processing_field] = "4"
            elif year == 2019:
                mapped[processing_field] = "5"
            elif year == 2018:
                mapped[processing_field] = "6"
            elif year == 2017:
                mapped[processing_field] = "7"
            elif year == 2016:
                mapped[processing_field] = "8"
            elif year < 2016:
                mapped[processing_field] = "9"  # Earlier/更早
        
        # 3. 媒介映射
        medium_str = title_params.get("媒介", "")
        mediainfo_str = self.upload_data.get("mediainfo", "")
        is_standard_mediainfo = "General" in mediainfo_str and "Complete name" in mediainfo_str
        
        # 站点规则：有mediainfo的Blu-ray/DVD源盘rip都算Encode
        medium_field = self.config.get("form_fields", {}).get("medium", "medium_sel[4]")
        medium_mapping = self.config.get("mappings", {}).get("medium", {})
        
        if is_standard_mediainfo and ('blu' in medium_str.lower() or 'dvd' in medium_str.lower()):
            mapped[medium_field] = "29"  # Encode
        else:
            mapped[medium_field] = self._find_mapping(medium_mapping, medium_str)
        
        # 4. 视频编码映射
        codec_str = title_params.get("视频编码", "")
        codec_field = self.config.get("form_fields", {}).get("codec", "codec_sel[4]")
        codec_mapping = self.config.get("mappings", {}).get("codec", {})
        mapped[codec_field] = self._find_mapping(codec_mapping, codec_str)
        
        # 5. 音频编码映射
        audio_str = title_params.get("音频编码", "")
        audio_field = self.config.get("form_fields", {}).get("audio_codec", "audiocodec_sel[4]")
        audio_mapping = self.config.get("mappings", {}).get("audio_codec", {})
        mapped[audio_field] = self._find_mapping(audio_mapping, audio_str)
        
        # 6. 分辨率映射
        resolution_str = title_params.get("分辨率", "")
        resolution_field = self.config.get("form_fields", {}).get("resolution", "standard_sel[4]")
        resolution_mapping = self.config.get("mappings", {}).get("resolution", {})
        mapped[resolution_field] = self._find_mapping(resolution_mapping, resolution_str)
        
        # 7. 地区映射
        origin_str = source_params.get("产地", "")
        source_str = origin_str if origin_str else title_params.get("片源平台", "")
        source_field = self.config.get("form_fields", {}).get("source", "source_sel[4]")
        source_mapping = self.config.get("mappings", {}).get("source", {})
        mapped[source_field] = self._find_mapping(source_mapping, source_str)
        
        # 8. 制作组映射
        release_group_str = str(title_params.get("制作组", "")).upper()
        team_field = self.config.get("form_fields", {}).get("team", "team_sel[4]")
        team_mapping = self.config.get("mappings", {}).get("team", {})
        mapped[team_field] = self._find_mapping(team_mapping, release_group_str)
        
        # 9. 标签映射
        combined_tags = self._collect_all_tags()
        tag_mapping = self.config.get("mappings", {}).get("tag", {})
        
        for tag_str in combined_tags:
            tag_id = self._find_mapping(tag_mapping, tag_str)
            if tag_id:
                tags.append(tag_id)
        
        # 去重并格式化
        for i, tag_id in enumerate(sorted(list(set(tags)))):
            mapped[f"tags[4][{i}]"] = tag_id
            
        return mapped