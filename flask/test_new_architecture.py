#!/usr/bin/env python3
# test_new_architecture.py

import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from uploaders import create_uploader, get_available_sites

def test_new_architecture():
    """测试新架构是否正常工作"""
    print("=== 测试新上传器架构 ===")
    
    print("1. 检查可用站点:")
    sites = get_available_sites()
    print(f"   可用站点: {sites}")
    
    # 创建测试数据
    site_info = {
        "base_url": "https://test.site",
        "cookie": "test_cookie"
    }
    
    upload_data = {
        "modified_torrent_path": "/tmp/test.torrent",
        "title_components": [
            {"key": "主标题", "value": "测试电影"},
            {"key": "年份", "value": "2024"},
            {"key": "媒介", "value": "Blu-ray"},
            {"key": "视频编码", "value": "H.265"},
            {"key": "制作组", "value": "FRDS"}
        ],
        "source_params": {
            "类型": "电影",
            "标签": ["国语", "中字"]
        },
        "mediainfo": "General\nComplete name: test.mkv\n\nAudio\nLanguage: Mandarin",
        "subtitle": "测试副标题",
        "imdb_link": "https://imdb.com/title/tt1234567/"
    }
    
    print("\n2. 测试创建各个站点的上传器:")
    for site in sites:
        try:
            print(f"   测试 {site}...")
            uploader = create_uploader(site, site_info, upload_data)
            print(f"   ✓ 成功创建 {site} 上传器: {type(uploader).__name__}")
            
            # 检查配置是否正确加载
            if hasattr(uploader, 'config') and uploader.config:
                print(f"   ✓ {site} 配置加载成功")
            else:
                print(f"   ✗ {site} 配置未加载")
                
        except Exception as e:
            print(f"   ✗ 创建 {site} 上传器失败: {e}")
    
    print("\n=== 测试完成 ===")

if __name__ == "__main__":
    test_new_architecture()