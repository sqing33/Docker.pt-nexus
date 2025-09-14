from ..base import BaseUploader


class CarptUploader(BaseUploader):
    def _build_description(self) -> str:
        """
        为Carpt站点构建描述，在简介和视频截图之间添加mediainfo（用[quote][/quote]包裹）
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