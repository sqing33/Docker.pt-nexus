from ..uploader import BaseUploader
from loguru import logger


class HdareaUploader(BaseUploader):
    """
    HDArea站点特殊上传器
    主要处理视频编码的特殊映射：h264/h265 -> x264/x265
    """

    def _map_parameters(self) -> dict:
        """
        实现HDArea站点的参数映射逻辑（修复版）
        特殊处理：将 video.h264/h265 映射为 video.x264/x265
        """
        # ✅ 直接使用 migrator 准备好的标准化参数
        standardized_params = self.upload_data.get("standardized_params", {})

        # 降级处理：如果没有标准化参数才重新解析
        if not standardized_params:
            logger.warning("未找到标准化参数，回退到重新解析")
            standardized_params = self._parse_source_data()
        
        # 🔧 特殊处理：将 h264/h265 转换为 x264/x265
        video_codec = standardized_params.get("video_codec", "")
        if video_codec == "video.h264":
            logger.info(f"HDArea视频编码映射: {video_codec} -> video.x264")
            standardized_params["video_codec"] = "video.x264"
        elif video_codec == "video.h265":
            logger.info(f"HDArea视频编码映射: {video_codec} -> video.x265")
            standardized_params["video_codec"] = "video.x265"
        
        # 使用修正后的标准化参数进行映射
        mapped_params = self._map_standardized_params(standardized_params)
        
        return mapped_params
