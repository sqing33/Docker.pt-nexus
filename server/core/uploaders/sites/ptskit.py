from ..uploader import SpecialUploader


class PtskitUploader(SpecialUploader):
    """
    PTSKit站点特殊上传器
    处理PTKit站点的特殊上传逻辑，标签只映射转载、电影、电视剧、综艺、游戏、音乐、动漫、其他这几个
    该站点没有mediainfo栏位，需要将mediainfo放在简介主体内容和截图之间
    """

    def _build_description(self) -> str:
        """
        为PTKit站点构建描述，在简介和视频截图之间添加mediainfo（用[quote][/quote]包裹）
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
        实现PTKit站点的参数映射逻辑
        根据类型选择对应的标签，转载标签为必选
        现在支持媒介、视频编码、分辨率等质量参数
        """
        # 直接使用 migrator 准备好的标准化参数
        standardized_params = self.upload_data.get("standardized_params", {})

        # 降级处理：如果没有标准化参数才重新解析
        if not standardized_params:
            print("未找到标准化参数，回退到重新解析")
            standardized_params = self._parse_source_data()

        # 使用标准化参数进行映射
        mapped_params = self._map_standardized_params(standardized_params)
        
        # 处理标签映射 - PTSKit只使用特定的标签
        tags = self._map_ptskit_tags(standardized_params)

        # 添加标签到映射参数
        for i, tag_id in enumerate(sorted(list(set(tags)))):
            mapped_params[f"tags[4][{i}]"] = tag_id

        return mapped_params

    def _map_ptskit_tags(self, standardized_params: dict) -> list:
        """
        PTSKit特殊标签映射
        只映射：转载、电影、电视剧、综艺、游戏、音乐、动漫、其他
        转载为必选标签
        """
        tags = []

        # 转载标签为必选
        tags.append("10")  # 转载标签的值

        # 根据类型映射对应的标签
        content_type = standardized_params.get("type", "").lower()

        if "电影" in content_type or "movie" in content_type:
            tags.append("23")  # 电影标签
        elif "电视剧" in content_type or "tv" in content_type:
            tags.append("140")  # 电视剧标签
        elif "综艺" in content_type or "variety" in content_type:
            tags.append("229")  # 综艺标签
        elif "游戏" in content_type or "game" in content_type:
            tags.append("139")  # 游戏标签
        elif "音乐" in content_type or "music" in content_type:
            tags.append("230")  # 音乐标签
        elif "动漫" in content_type or "animation" in content_type:
            tags.append("44")  # 动漫标签
        else:
            tags.append("237")  # 其他标签

        return tags