#!/usr/bin/env python3
# test_uploaders.py

import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uploaders import create_uploader, get_available_sites

def test_factory():
    """测试工厂模式是否正常工作"""
    print("可用的站点:", get_available_sites())
    
    # 测试创建AGSV上传器
    try:
        site_info = {
            "base_url": "https://agsv.pt",
            "cookie": "test_cookie"
        }
        
        upload_data = {
            "modified_torrent_path": "/tmp/test.torrent",
            "title_components": [],
            "source_params": {"类型": "电影"},
            "mediainfo": ""
        }
        
        uploader = create_uploader("agsv", site_info, upload_data)
        print("成功创建AGSV上传器:", type(uploader).__name__)
        
        # 测试创建CrabPT上传器
        uploader = create_uploader("crabpt", site_info, upload_data)
        print("成功创建CrabPT上传器:", type(uploader).__name__)
        
        # 测试创建13city上传器
        uploader = create_uploader("13city", site_info, upload_data)
        print("成功创建13City上传器:", type(uploader).__name__)
        
    except Exception as e:
        print(f"创建上传器时出错: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_factory()