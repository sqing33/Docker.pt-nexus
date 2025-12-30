from ..uploader import SpecialUploader
from utils.mediainfo import validate_media_info_format


class PterclubUploader(SpecialUploader):
    def _build_description(self) -> str:
        """
        为PTerClub站点构建描述，在简介和视频截图之间添加mediainfo和bdinfo
        MediaInfo用[hide=mediainfo][/hide]包裹
        BDInfo用[hide=bdinfo][/hide]包裹
        """
        intro = self.upload_data.get("intro", {})
        mediainfo = self.upload_data.get("mediainfo", "").strip()
        bdinfo = self.upload_data.get("bdinfo", "").strip()

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

        # 处理 MediaInfo/BDInfo
        # PTerClub 的 mediainfo 字段可能包含 MediaInfo 或 BDInfo 格式的文本
        # 使用 validate_media_info_format 函数来判断是哪种格式
        if mediainfo:
            (
                is_mediainfo,
                is_bdinfo,
                *_,
            ) = validate_media_info_format(mediainfo)

            if is_mediainfo:
                # 检测到 MediaInfo 格式
                description_parts.append(f"[hide=mediainfo]{mediainfo}[/hide]")
            elif is_bdinfo:
                # 检测到 BDInfo 格式
                description_parts.append(f"[hide=bdinfo]{mediainfo}[/hide]")
            else:
                # 无法判断，默认作为 MediaInfo 处理
                description_parts.append(f"[hide=mediainfo]{mediainfo}[/hide]")

        # 添加独立的 BDInfo（如果存在）
        if bdinfo:
            description_parts.append(f"[hide=bdinfo]{bdinfo}[/hide]")

        # 添加截图
        if intro.get("screenshots"):
            description_parts.append(intro["screenshots"])

        return "\n".join(description_parts)

    def _map_parameters(self) -> dict:

            """

            实现PTerClub站点的参数映射逻辑

            PTerClub 使用独立的 checkbox 字段，而不是数组格式

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

    

            # 🔧 特殊处理：PTerClub 的标签是独立的 checkbox 字段

            # 需要将标签映射到对应的 checkbox 字段名

            tag_mapping = self.mappings.get("tag", {})

            combined_tags = self._collect_all_tags()

    

            # PTerClub 标签到 checkbox 字段的映射

            tag_to_checkbox = {

                "tag.禁转": "jinzhuan",

                "tag.官方": "guanfang",

                "tag.国语": "guoyu",

                "tag.粤语": "yueyu",

                "tag.中字": "zhongzi",

                "tag.英字": "ensub",

                "tag.应求": "yingqiu",

                "tag.DIY": "diy",

                "tag.原创": "pr",

                "tag.自购": "bim",

                "tag.MV母盘": "mp",

            }

    

            # 移除基类生成的 tags[4][{i}] 字段

            keys_to_remove = [key for key in mapped_params.keys() if key.startswith("tags[")]

            for key in keys_to_remove:

                del mapped_params[key]

    

            # 处理标签映射到 checkbox

            for tag_str in combined_tags:

                # 查找映射后的值

                tag_id = self._find_mapping(tag_mapping, tag_str, mapping_type="tag")

                if tag_id:

                    # 将标签映射到对应的 checkbox 字段

                    if tag_str in tag_to_checkbox:

                        checkbox_name = tag_to_checkbox[tag_str]

                        mapped_params[checkbox_name] = tag_id  # 值为 "yes"

                    elif tag_id in tag_to_checkbox.values():

                        # 如果映射结果本身就是 checkbox 字段名

                        mapped_params[tag_id] = "yes"

    

            return mapped_params
