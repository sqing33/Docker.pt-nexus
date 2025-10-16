from ..uploader import BaseUploader


class QingwaptUploader(BaseUploader):
    """
    QingwAPT站点的上传器实现，继承自BaseUploader
    """

    def _build_title(self, standardized_params: dict) -> str:
        """
        根据 QingwAPT 站点的规则拼接主标题。
        """
        import re
        from loguru import logger

        components_list = self.upload_data.get("title_components", [])
        components = {
            item["key"]: item["value"]
            for item in components_list if item.get("value")
        }
        logger.info(f"开始拼接主标题，源参数: {components}")

        # QingwAPT 特定的标题顺序
        order = [
            "主标题",
            "季集",
            "年份",
            "剧集状态",
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

        # 使用正则表达式替换分隔符，以保护数字中的小数点（例如 5.1）
        raw_main_part = " ".join(filter(None, title_parts))
        # r'(?<!\d)\.(?!\d)' 的意思是：匹配一个点，但前提是它的前面和后面都不是数字
        main_part = re.sub(r'(?<!\d)\.(?!\d)', ' ', raw_main_part)
        # 额外清理，将可能产生的多个空格合并为一个
        main_part = re.sub(r'\s+', ' ', main_part).strip()

        release_group = components.get("制作组", "NOGROUP")
        if "N/A" in release_group:
            release_group = "NOGROUP"

        # QingwAPT 特定的制作组处理规则
        special_groups = ["MNHD-FRDS", "mUHD-FRDS"]
        if release_group in special_groups:
            final_title = f"{main_part} {release_group}"
        else:
            # QingwAPT 使用不同的分隔符
            final_title = f"{main_part}-{release_group}"

        final_title = re.sub(r"\s{2,}", " ", final_title).strip()
        logger.info(f"拼接完成的主标题: {final_title}")
        return final_title

    def _map_parameters(self) -> dict:
        """
        实现抽象方法，使用基类的通用映射逻辑（修复版）
        """
        # ✅ 直接使用 migrator 准备好的标准化参数
        standardized_params = self.upload_data.get("standardized_params", {})

        # 降级处理：如果没有标准化参数才重新解析
        if not standardized_params:
            from loguru import logger
            logger.warning("未找到标准化参数，回退到重新解析")
            standardized_params = self._parse_source_data()

        mapped_params = self._map_standardized_params(standardized_params)
        return mapped_params
