from ..uploader import SpecialUploader


class ZmptUploader(SpecialUploader):
    def _build_description(self) -> str:
        """
        为Zmpt站点构建描述，在简介和视频截图之间添加mediainfo（用[quote][/quote]包裹）
        """
        intro = self.upload_data.get("intro", {})
        mediainfo = self.upload_data.get("mediainfo", "").strip()

        # 基本描述结构
        description_parts = []

        # 添加声明部分
        if intro.get("statement"):
            description_parts.append(intro["statement"])

        # 添加海报
        if intro.get("poster"):
            description_parts.append(intro["poster"])

        # 添加主体内容
        if intro.get("body"):
            description_parts.append(intro["body"])

        # 添加MediaInfo（如果存在且站点不支持单独的mediainfo字段）
        if mediainfo:
            description_parts.append(f"[quote]{mediainfo}[/quote]")

        # 添加截图
        if intro.get("screenshots"):
            description_parts.append(intro["screenshots"])

        return "\n".join(description_parts)

    def _map_parameters(self) -> dict:
        """
        实现Zmpt站点的参数映射逻辑（修复版）
        """
        # ✅ 直接使用 migrator 准备好的标准化参数
        standardized_params = self.upload_data.get("standardized_params", {})

        # 降级处理：如果没有标准化参数才重新解析
        if not standardized_params:
            from loguru import logger
            logger.warning("未找到标准化参数，回退到重新解析")
            standardized_params = self._parse_source_data()

        # 使用标准化参数进行映射
        mapped_params = self._map_standardized_params(standardized_params)
        return mapped_params
