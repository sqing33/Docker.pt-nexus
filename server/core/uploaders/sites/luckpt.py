from ..uploader import SpecialUploader


class LuckptUploader(SpecialUploader):
    def _map_parameters(self) -> dict:
        """
        实现Luckpt站点的参数映射逻辑，特殊处理标签：如果存在国语标签，则过滤掉英语标签
        """
        # 直接使用 migrator 准备好的标准化参数
        standardized_params = self.upload_data.get("standardized_params", {})

        # 降级处理：如果没有标准化参数才重新解析
        if not standardized_params:
            from loguru import logger
            logger.warning("未找到标准化参数，回退到重新解析")
            standardized_params = self._parse_source_data()

        # 先使用基类的映射逻辑获取基础参数
        mapped_params = self._map_standardized_params(standardized_params)

        # 特殊处理标签：如果存在国语标签（5），则过滤掉英语标签（22）
        # 从配置中获取标签映射
        tag_mapping = self.mappings.get("tag", {})
        
        # 获取国语和英语标签的ID
        mandarin_tag_id = None
        english_tag_id = None
        
        for key, value in tag_mapping.items():
            if "国语" in str(key) or "mandarin" in str(key).lower():
                mandarin_tag_id = value
            elif "英语" in str(key) or "english" in str(key).lower():
                english_tag_id = value
        
        # 如果没有从配置中获取到标签ID，则使用默认值
        if mandarin_tag_id is None:
            mandarin_tag_id = 5
        if english_tag_id is None:
            english_tag_id = 22

        # 获取当前已映射的标签
        tags = []
        tag_key_prefix = "tags[4]["
        
        # 从mapped_params中找到所有的标签键
        tag_keys = [key for key in mapped_params.keys() if key.startswith(tag_key_prefix)]
        
        for key in tag_keys:
            tag_value = mapped_params[key]
            if tag_value == english_tag_id:
                # 检查是否存在国语标签
                has_mandarin = any(mapped_params.get(other_key) == mandarin_tag_id 
                                 for other_key in tag_keys)
                if has_mandarin:
                    # 如果存在国语标签，则不添加英语标签
                    continue
            tags.append((key, tag_value))
        
        # 清除原有的标签参数
        keys_to_remove = [key for key in mapped_params.keys() if key.startswith(tag_key_prefix)]
        for key in keys_to_remove:
            del mapped_params[key]
        
        # 重新添加过滤后的标签
        for i, (key, tag_value) in enumerate(tags):
            new_key = f"tags[4][{i}]"
            mapped_params[new_key] = tag_value

        return mapped_params
