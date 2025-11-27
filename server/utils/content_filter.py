"""
内容过滤工具类
用于处理种子描述中的技术参数检测和内容过滤
"""

import re
import logging
import os
import yaml
from typing import Dict, Any, List

# 全局配置缓存
CONTENT_FILTERING_CONFIG = {}

def load_content_filtering_config():
    """加载内容过滤配置"""
    global CONTENT_FILTERING_CONFIG
    if CONTENT_FILTERING_CONFIG:
        return CONTENT_FILTERING_CONFIG

    from config import GLOBAL_MAPPINGS

    try:
        if os.path.exists(GLOBAL_MAPPINGS):
            with open(GLOBAL_MAPPINGS, 'r', encoding='utf-8') as f:
                global_config = yaml.safe_load(f)
                CONTENT_FILTERING_CONFIG = global_config.get("content_filtering", {})
        else:
            print(f"警告：配置文件不存在: {GLOBAL_MAPPINGS}")
    except Exception as e:
        print(f"警告：无法加载内容过滤配置: {e}")

    return CONTENT_FILTERING_CONFIG


class ContentFilter:
    """内容过滤器，用于处理种子描述中的技术参数和不需要的内容"""

    def __init__(self):
        self.config = load_content_filtering_config()

    def is_enabled(self) -> bool:
        """检查内容过滤是否启用"""
        return self.config.get("enabled", False)

    def is_technical_params_quote(self, quote_text: str) -> bool:
        """
        使用配置文件中的 technical_params_detection 规则检查是否为技术参数 quote

        Args:
            quote_text: 要检查的quote内容

        Returns:
            如果是技术参数quote返回True，否则返回False
        """
        if not self.is_enabled():
            return False

        # 转换为大写进行不区分大小写的匹配
        quote_upper = quote_text.upper()

        # 从配置文件读取技术参数检测规则
        tech_params_config = self.config.get("technical_params_detection", {})
        patterns = tech_params_config.get("patterns", [])

        for pattern in patterns:
            keywords = pattern.get("keywords", [])
            min_dots = pattern.get("min_dots", 0)
            has_underscores = pattern.get("has_underscores", False)

            # 检查是否所有关键词都存在（不区分大小写）
            if keywords:
                all_keywords_present = all(
                    keyword in quote_text
                    or keyword.upper() in quote_upper
                    for keyword in keywords)

                if all_keywords_present:
                    # 检查额外条件
                    if min_dots > 0 and quote_text.count(".") < min_dots:
                        continue
                    if has_underscores and ("___" not in quote_text and
                                            "____" not in quote_text):
                        continue

                    # 所有条件都满足
                    logging.info(
                        f"根据配置规则 '{pattern.get('description', '')}' 识别为技术参数quote"
                    )
                    return True

        return False

    def is_unwanted_pattern(self, content: str) -> bool:
        """
        检查内容是否包含不需要的模式

        Args:
            content: 要检查的内容

        Returns:
            如果包含不需要的模式返回True，否则返回False
        """
        if not self.is_enabled():
            return False

        unwanted_patterns = self.config.get("unwanted_patterns", [])
        return any(pattern in content for pattern in unwanted_patterns)

    def clean_subtitle(self, subtitle: str) -> str:
        """
        清理副标题，移除制作组信息和不需要的内容

        Args:
            subtitle: 原始副标题

        Returns:
            清理后的副标题
        """
        if not subtitle:
            return subtitle

        # 首先使用硬编码的规则（兼容性）
        subtitle = re.sub(r"\s*\|\s*[Aa][Bb]y\s+\w+.*$", "", subtitle)
        subtitle = re.sub(r"\s*\|\s*[Bb]y\s+\w+.*$", "", subtitle)
        subtitle = re.sub(r"\s*\|\s*[Aa]\s+\w+.*$", "", subtitle)
        subtitle = re.sub(r"\s*\|\s*[Aa]\s*\|.*$", "", subtitle)
        subtitle = re.sub(r"\s*\|\s*[Aa][Tt][Uu]\s*$", "", subtitle)
        subtitle = re.sub(r"\s*\|\s*[Dd][Tt][Uu]\s*$", "", subtitle)
        subtitle = re.sub(r"\s*\|\s*[Pp][Tt][Ee][Rr]\s*$", "", subtitle)

        # 然后使用配置文件中的规则
        if self.is_enabled():
            unwanted_patterns = self.config.get("unwanted_patterns", [])

            for pattern in unwanted_patterns:
                if pattern in subtitle:
                    # 找到模式的位置，删除该模式及其之后的内容
                    pattern_index = subtitle.find(pattern)
                    if pattern_index != -1:
                        subtitle = subtitle[:pattern_index].strip()
                        # 如果删除后没有内容了，返回空字符串
                        if not subtitle:
                            return ""

        return subtitle.strip()

    def filter_quotes_in_statement(self, statement: str) -> Dict[str, Any]:
        """
        过滤statement中的quote内容

        Args:
            statement: 包含quote的statement文本

        Returns:
            包含过滤结果的字典:
            - filtered_statement: 过滤后的statement
            - removed_declarations: 被移除的声明列表
        """
        if not statement:
            return {
                "filtered_statement": statement,
                "removed_declarations": []
            }

        # 提取quotes
        quotes = re.findall(r"\[quote\](.*?)\[/quote\]", statement, re.DOTALL)

        if not quotes:
            return {
                "filtered_statement": statement,
                "removed_declarations": []
            }

        # 分类quotes
        filtered_quotes = []
        removed_declarations = []

        for quote in quotes:
            # 检查是否为技术参数
            if self.is_technical_params_quote(quote):
                clean_content = re.sub(r"\[\/?quote\]", "", quote).strip()
                removed_declarations.append(clean_content)
            # 检查是否为不需要的模式
            elif self.is_unwanted_pattern(quote):
                clean_content = re.sub(r"\[\/?quote\]", "", quote).strip()
                removed_declarations.append(clean_content)
            else:
                filtered_quotes.append(quote)

        # 重新构建statement：先移除所有quotes，再添加需要保留的
        filtered_statement = statement
        for quote in quotes:
            full_quote_tag = f"[quote]{quote}[/quote]"
            filtered_statement = filtered_statement.replace(full_quote_tag, "", 1)

        # 添加保留的quotes
        for quote in filtered_quotes:
            filtered_statement += f"\n[quote]{quote}[/quote]"

        return {
            "filtered_statement": filtered_statement.strip(),
            "removed_declarations": removed_declarations
        }


# 全局实例
_content_filter = None

def get_unwanted_image_urls() -> List[str]:
    """获取不需要的图片URL列表"""
    config = load_content_filtering_config()
    return config.get("unwanted_image_urls", [])

def get_content_filter() -> ContentFilter:
    """获取内容过滤器实例（单例模式）"""
    global _content_filter
    if _content_filter is None:
        _content_filter = ContentFilter()
    return _content_filter