from ..uploader import SpecialUploader
from loguru import logger


class BaoziUploader(SpecialUploader):
    """
    Baozi站点特殊上传器
    处理Blu-ray DIY和UHD Blu-ray DIY的特殊映射逻辑
    """

    def _map_parameters(self) -> dict:
        """
        实现Baozi站点的参数映射逻辑
        特殊处理：根据标签DIY判断将普通原盘修正为原盘DIY
        """
        # 1. 获取标准化参数
        standardized_params = self.upload_data.get("standardized_params", {})
        if not standardized_params:
            logger.warning("未找到标准化参数，回退到重新解析")
            standardized_params = self._parse_source_data()

        # 2. 先进行标准映射
        mapped_params = self._map_standardized_params(standardized_params)

        # 3. 特殊处理：根据DIY标签修正媒介参数
        medium_field = self.config.get("form_fields", {}).get("medium", "medium_sel[4]")
        current_medium = mapped_params.get(medium_field)

        # 收集所有标签
        combined_tags = self._collect_all_tags()

        # 检查是否包含DIY标签（检测标签文本，不区分大小写）
        has_diy_tag = any(
            "DIY" in str(tag).upper()
            for tag in combined_tags
        )

        if has_diy_tag:
            # 如果当前媒介是Blu-ray (1)，修正为Blu-ray DIY (13)
            if current_medium == "1":
                mapped_params[medium_field] = "13"
                logger.info(f"Baozi检测到DIY标签，修正媒介: Blu-ray(1) -> Blu-ray DIY(13)")

            # 如果当前媒介是UHD Blu-ray (11)，修正为UHD Blu-ray DIY (12)
            elif current_medium == "11":
                mapped_params[medium_field] = "12"
                logger.info(f"Baozi检测到DIY标签，修正媒介: UHD Blu-ray(11) -> UHD Blu-ray DIY(12)")

        return mapped_params