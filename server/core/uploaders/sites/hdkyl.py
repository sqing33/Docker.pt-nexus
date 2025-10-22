from ..uploader import SpecialUploader
import re


class HdkylUploader(SpecialUploader):
    """
    HDKyl站点特殊上传器
    处理hdkyl站点的特殊上传逻辑，主要是年份参数映射
    """

    def _map_parameters(self) -> dict:
        """
        实现HDKyl站点的参数映射逻辑
        继承基类的通用映射，只特殊处理年份参数
        """
        # ✅ 直接使用 migrator 准备好的标准化参数
        standardized_params = self.upload_data.get("standardized_params", {})

        # 降级处理：如果没有标准化参数才重新解析
        if not standardized_params:
            print("未找到标准化参数，回退到重新解析")
            standardized_params = self._parse_source_data()

        mapped_params = self._map_standardized_params(standardized_params)

        # 特殊处理年份参数：提取前4位数字并映射到processing_sel[4]
        year_value = self._extract_and_map_year()
        if year_value:
            mapped_params["processing_sel[4]"] = year_value
            print(f"HDKyl年份映射: {year_value}")

        return mapped_params

    def _extract_and_map_year(self) -> str:
        """
        从标题参数中提取年份并进行映射
        
        Returns:
            str: 映射后的年份数值，如果无法提取则返回空字符串
        """
        # 获取标题组件
        title_components_list = self.upload_data.get("title_components", [])
        title_params = {
            item["key"]: item["value"]
            for item in title_components_list if item.get("value")
        }

        # 获取原始年份参数
        original_year = title_params.get("年份", "")

        if not original_year:
            print("未找到年份参数")
            return ""

        # 提取前4位数字（年份）
        year_match = re.search(r'(\d{4})', original_year)
        if not year_match:
            print(f"无法从年份参数 '{original_year}' 中提取4位数字")
            return ""

        year_4digit = year_match.group(1)
        print(f"提取到4位年份: {year_4digit}")

        # 检查是否有cut_version信息需要拼接到年份中
        cut_version = self._extract_cut_version(title_params)

        if cut_version:
            # 将cut_version信息拼接到年份参数中
            enhanced_year = f"{year_4digit} {cut_version}"
            print(f"检测到cut_version，增强年份参数: {enhanced_year}")

            # 使用增强后的年份进行映射
            return self._map_year_to_value(enhanced_year)
        else:
            # 直接使用年份进行映射
            return self._map_year_to_value(year_4digit)

    def _extract_cut_version(self, title_params: dict) -> str:
        """
        从标题参数中提取cut_version信息
        
        Args:
            title_params: 标题参数字典
            
        Returns:
            str: 提取到的cut_version信息，如果没有则返回空字符串
        """
        # 定义cut_version的正则表达式模式
        cut_version_pattern = r"Theatrical[\s\.]?Cut|Directors?[\s\.]?Cut|DC|Extended[\s\.]?(?:Cut|Edition)|Special[\s\.]?Edition|SE|Final[\s\.]?Cut|Anniversary[\s\.]?Edition|Restored|Remastered|Criterion[\s\.]?(?:Edition|Collection)|Ultimate[\s\.]?Cut|IMAX[\s\.]?Edition|Open[\s\.]?Matte|Unrated[\s\.]?Cut"

        # 从主标题中搜索cut_version
        main_title = title_params.get("主标题", "")
        if main_title:
            matches = re.findall(cut_version_pattern, main_title,
                                 re.IGNORECASE)
            if matches:
                # 返回第一个匹配的cut_version
                cut_version = matches[0]
                print(f"从主标题中提取到cut_version: {cut_version}")
                return cut_version

        # 从其他标题组件中搜索
        for key, value in title_params.items():
            if key != "主标题" and value:
                matches = re.findall(cut_version_pattern, value, re.IGNORECASE)
                if matches:
                    cut_version = matches[0]
                    print(f"从标题组件 '{key}' 中提取到cut_version: {cut_version}")
                    return cut_version

        return ""

    def _map_year_to_value(self, year_text: str) -> str:
        """
        将年份文本映射为对应的数值
        
        Args:
            year_text: 年份文本（可能包含cut_version）
            
        Returns:
            str: 映射后的数值
        """
        # 获取年份映射配置
        year_mapping = self.config.get("mappings", {}).get("year", {})

        # 首先尝试精确匹配
        if year_text in year_mapping:
            return year_mapping[year_text]

        # 如果精确匹配失败，尝试提取年份部分进行匹配
        year_match = re.search(r'(\d{4})', year_text)
        if year_match:
            year_4digit = year_match.group(1)
            year_key = f"year.{year_4digit}"
            if year_key in year_mapping:
                return year_mapping[year_key]

        # 如果都失败了，使用默认值
        default_value = year_mapping.get("default", "9")
        print(f"年份 '{year_text}' 映射失败，使用默认值: {default_value}")
        return default_value
