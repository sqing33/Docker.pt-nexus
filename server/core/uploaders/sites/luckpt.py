from ..uploader import SpecialUploader


class LuckptUploader(SpecialUploader):
    def _map_parameters(self) -> dict:
        """
        实现Luckpt站点的参数映射逻辑，特殊处理标签：如果存在国语、中字、粤语中任意一个标签，则过滤掉英语标签
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

        # 特殊处理标签：如果存在国语（5）、中字（6）、粤语（14）中任意一个标签，则过滤掉英语标签（22）
        # 从配置中获取标签映射
        tag_mapping = self.mappings.get("tag", {})
        
        # 获取相关标签的ID
        mandarin_tag_id = None
        chinese_sub_tag_id = None
        cantonese_tag_id = None
        english_tag_id = None
        
        for key, value in tag_mapping.items():
            if "国语" in str(key) or "mandarin" in str(key).lower():
                mandarin_tag_id = value
            elif "中字" in str(key) or "chinese_sub" in str(key).lower():
                chinese_sub_tag_id = value
            elif "粤语" in str(key) or "cantonese" in str(key).lower():
                cantonese_tag_id = value
            elif "英语" in str(key) or "english" in str(key).lower():
                english_tag_id = value
        
        # 如果没有从配置中获取到标签ID，则使用默认值
        if mandarin_tag_id is None:
            mandarin_tag_id = 5
        if chinese_sub_tag_id is None:
            chinese_sub_tag_id = 6
        if cantonese_tag_id is None:
            cantonese_tag_id = 14
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
                # 检查是否存在国语、中字、粤语标签中的任意一个
                has_chinese_audio = any(mapped_params.get(other_key) == mandarin_tag_id 
                                      for other_key in tag_keys)
                has_chinese_sub = any(mapped_params.get(other_key) == chinese_sub_tag_id 
                                    for other_key in tag_keys)
                has_cantonese = any(mapped_params.get(other_key) == cantonese_tag_id 
                                  for other_key in tag_keys)
                
                # 如果存在国语、中字、粤语中任意一个，则不添加英语标签
                if has_chinese_audio or has_chinese_sub or has_cantonese:
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
