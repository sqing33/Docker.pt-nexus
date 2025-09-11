#!/usr/bin/env python3
# test_structure.py

import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """测试导入是否正常工作"""
    print("=== 测试导入 ===")
    
    try:
        from uploaders import BaseUploader
        print("✓ BaseUploader 导入成功")
    except Exception as e:
        print(f"✗ BaseUploader 导入失败: {e}")
    
    try:
        from uploaders import create_uploader
        print("✓ create_uploader 导入成功")
    except Exception as e:
        print(f"✗ create_uploader 导入失败: {e}")
        
    try:
        from uploaders import get_available_sites
        print("✓ get_available_sites 导入成功")
    except Exception as e:
        print(f"✗ get_available_sites 导入失败: {e}")
    
    # 测试站点模块导入
    try:
        from uploaders.sites import agsv
        print("✓ AGSV 站点模块导入成功")
    except Exception as e:
        print(f"✗ AGSV 站点模块导入失败: {e}")
        
    try:
        from uploaders.sites import crabpt
        print("✓ CrabPT 站点模块导入成功")
    except Exception as e:
        print(f"✗ CrabPT 站点模块导入失败: {e}")
        
    try:
        from uploaders.sites import _13city
        print("✓ 13City 站点模块导入成功")
    except Exception as e:
        print(f"✗ 13City 站点模块导入失败: {e}")

def test_config_files():
    """测试配置文件是否存在"""
    print("\n=== 测试配置文件 ===")
    
    config_dir = "configs"
    expected_configs = ["agsv.yaml", "crabpt.yaml", "13city.yaml"]
    
    if os.path.exists(config_dir):
        print("✓ 配置目录存在")
        files = os.listdir(config_dir)
        for config in expected_configs:
            if config in files:
                print(f"✓ {config} 存在")
            else:
                print(f"✗ {config} 不存在")
    else:
        print("✗ 配置目录不存在")

def test_site_files():
    """测试站点文件"""
    print("\n=== 测试站点文件 ===")
    
    sites_dir = "uploaders/sites"
    expected_sites = ["agsv.py", "crabpt.py", "_13city.py"]
    
    if os.path.exists(sites_dir):
        print("✓ 站点目录存在")
        files = os.listdir(sites_dir)
        for site in expected_sites:
            if site in files:
                print(f"✓ {site} 存在")
            else:
                print(f"✗ {site} 不存在")
    else:
        print("✗ 站点目录不存在")

if __name__ == "__main__":
    test_imports()
    test_config_files()
    test_site_files()