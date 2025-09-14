#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试AudiencesSpecialExtractor的脚本
"""

import os
import sys
from bs4 import BeautifulSoup
from flask.core.extractors.audiences_special import AudiencesSpecialExtractor

# 添加项目路径到Python路径
sys.path.insert(0, '/app/Code/Dockerfile/Docker.pt-nexus')

def test_audiences_extractor():
    """测试AudiencesSpecialExtractor的功能"""

    # 创建一个简单的测试HTML内容，模拟"人人"站点的种子详情页
    test_html = """
    <html>
    <body>
        <h1 id="top">测试种子标题</h1>

        <table>
            <tr>
                <td>基本信息</td>
                <td>
                    <div>类型: 电影 (2023)</div>
                    <div>媒介: UHD Blu-ray</div>
                    <div>编码: HEVC</div>
                    <div>音频编码: DTS-HD MA</div>
                    <div>分辨率: 2160p</div>
                    <div>制作组: TEST-GROUP</div>
                </td>
            </tr>
        </table>

        <table>
            <tr>
                <td>标签</td>
                <td>
                    <span>科幻</span>
                    <span>动作</span>
                    <span>冒险</span>
                </td>
            </tr>
        </table>

        <table>
            <tr>
                <td>副标题</td>
                <td>测试副标题 | By TEST-GROUP</td>
            </tr>
        </table>

        <div id="kdescr">
            <div class="spoiler-content">
                <pre>
DISC INFO:
Disc Title: TEST_MOVIE
Disc Label: TEST_Label
Disc Size: 66,409,723,834 bytes
Protection: AACS2
BDInfo: 0.7.5.5
FILES:
00001.m2ts - 66,409,723,834 bytes - m=15:43:s=04:f=07 - 44:000 kbps - Full BD
PLAYLIST REPORT:
00001.mpls - 44:01.920 (h:m:s.ms)
Video:
Codec: MPEG-4 AVC Video / Profile: High@L4.1 / 23.976 fps
Bitrate: 44.0 kbps / VBR
Resolution: 3840x2160 (2160p)
Aspect ratio: 16:9
Video Encoding Settings: cabac=1 / ref=4 / deblock=1:0:0 / analyse=0x1:0x111 / me=umh / subme=8 / psy=1 / fade_compensate=0.00 / weightb=1 / weightp=2 / output_pulldown=0 / 50:50_pulldown=1 / monochrome=0 / interlaced=tff
Audio:
Codec: DTS-HD Master Audio / Channels: 7.1 / Bitrate: 4.0 kbps / Sample Rate: 48.0 kHz / Bit Depth: 24-bit
Language: English
Subtitles:
Codec: PG Stream / Language: Chinese
Codec: PG Stream / Language: English
                </pre>
            </div>
            <div>测试简介内容</div>
        </div>

        <fieldset>
            <legend>引用</legend>
            <div>这是测试引用内容</div>
        </fieldset>
    </body>
    </html>
    """

    # 解析HTML内容
    soup = BeautifulSoup(test_html, "html.parser")

    # 创建提取器实例
    extractor = AudiencesSpecialExtractor(soup)

    print("开始测试AudiencesSpecialExtractor...")

    # 测试基本信息提取
    basic_info = extractor.extract_basic_info()
    print(f"基本信息提取结果: {basic_info}")

    # 测试标签提取
    tags = extractor.extract_tags()
    print(f"标签提取结果: {tags}")

    # 测试副标题提取
    subtitle = extractor.extract_subtitle()
    print(f"副标题提取结果: {subtitle}")

    # 测试简介提取
    intro = extractor.extract_intro()
    print(f"简介提取结果: {intro}")

    # 测试MediaInfo提取
    mediainfo = extractor.extract_mediainfo()
    print(f"MediaInfo提取结果长度: {len(mediainfo)}")
    if mediainfo:
        print("MediaInfo内容预览:")
        print(mediainfo[:200] + "..." if len(mediainfo) > 200 else mediainfo)

    # 测试产地信息提取
    full_description_text = f"{intro.get('statement', '')}\n{intro.get('body', '')}"
    origin_info = extractor.extract_origin_info(full_description_text)
    print(f"产地信息提取结果: {origin_info}")

    # 测试详细参数提取
    detailed_params = extractor.extract_detailed_params()
    print(f"详细参数提取结果: {list(detailed_params.keys())}")

    # 测试所有信息提取
    extracted_data = extractor.extract_all(torrent_id="test_12345")
    print(f"所有信息提取结果: {extracted_data.keys()}")

    print("测试完成!")

if __name__ == "__main__":
    test_audiences_extractor()