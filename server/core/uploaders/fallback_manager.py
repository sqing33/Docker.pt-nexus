# server/core/uploaders/fallback_manager.py

import os
import yaml
from loguru import logger
from typing import Dict, List, Optional, Any


class FallbackManager:
    """
    参数降级管理器
    负责在目标站点不支持某个精确参数时，自动降级到更通用的参数
    """

    def __init__(self, config_path: str = None):
        """
        初始化降级管理器
        :param config_path: global_mappings.yaml 文件的路径
        """
        self.config = self._load_fallback_config(config_path)
        self.fallback_chains = self.config.get("fallback_chains", {})
        self.fallback_config = self.config.get("fallback_config", {})
        self.enabled = self.fallback_config.get("enabled", False)
        self.log_fallback = self.fallback_config.get("log_fallback", False)
        self.max_depth = self.fallback_config.get("max_fallback_depth", 5)

    def _load_fallback_config(self, config_path: str) -> Dict[str, Any]:
        """
        从 YAML 文件加载降级配置
        :param config_path: global_mappings.yaml 文件的路径
        :return: 包含降级配置的字典
        """
        if not config_path or not os.path.exists(config_path):
            print("降级配置文件路径未提供或文件不存在，降级功能将禁用。")
            return {}
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                # 我们只需要从全局文件中获取 fallback_chains 和 fallback_config
                full_config = yaml.safe_load(f)
                return {
                    "fallback_chains": full_config.get("fallback_chains", {}),
                    "fallback_config": full_config.get("fallback_config", {}),
                }
        except (yaml.YAMLError, IOError) as e:
            print(f"加载降级配置文件 '{config_path}' 失败: {e}")
            return {}

    def get_fallback_chain(self, param_type: str,
                           standard_key: str) -> List[str]:
        """
        获取指定参数的降级链
        :param param_type: 参数类型 (例如, 'audio_codec')
        :param standard_key: 标准化键 (例如, 'audio.truehd_atmos')
        :return: 降级键的列表
        """
        if not self.enabled:
            return []

        chain = self.fallback_chains.get(param_type, {}).get(standard_key, [])
        return chain

    def find_with_fallback(self, mapping_dict: Dict[str,
                                                    str], standard_key: str,
                           param_type: str) -> Optional[str]:
        """
        使用降级链查找映射。
        :param mapping_dict: 目标站点的映射字典
        :param standard_key: 原始标准化键
        :param param_type: 参数类型
        :return: 找到的映射值，否则返回 None
        """
        if not self.enabled or not standard_key or not param_type:
            return None

        fallback_chain = self.get_fallback_chain(param_type, standard_key)
        if not fallback_chain:
            return None

        # 限制降级深度
        limited_chain = fallback_chain[:self.max_depth]

        for fallback_key in limited_chain:
            # 检查降级键是否存在于站点的映射中
            # 同时进行大小写不敏感的检查
            for k, v in mapping_dict.items():
                if str(k).lower() == str(fallback_key).lower():
                    if self.log_fallback:
                        print(f"[Fallback Success] "
                              f"类型='{param_type}', "
                              f"原始值='{standard_key}' -> "
                              f"降级值='{fallback_key}', "
                              f"站点映射='{v}'")
                    return v

        if self.log_fallback:
            print(f"[Fallback Fail] "
                  f"类型='{param_type}', "
                  f"原始值='{standard_key}'. "
                  f"降级链 {limited_chain} 中没有在站点映射中找到匹配项。")

        return None
