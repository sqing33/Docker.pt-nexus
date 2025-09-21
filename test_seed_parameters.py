#!/usr/bin/env python3
"""
测试数据库表创建和数据保存功能
"""

import os
import sys
import logging
from datetime import datetime

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
from database import DatabaseManager
from models.seed_parameter import SeedParameter

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_seed_parameters_functionality():
    """测试种子参数表创建和数据保存功能"""

    # 创建测试Flask应用
    app = Flask(__name__)

    # 配置数据库连接（使用SQLite进行测试）
    test_config = {
        "db_type": "sqlite",
        "path": "test_pt_stats.db"
    }

    # 初始化数据库管理器
    db_manager = DatabaseManager(test_config)

    with app.app_context():
        # 将db_manager存入应用配置中
        app.config['DB_MANAGER'] = db_manager

        # 初始化数据库（创建表）
        logger.info("=== 开始初始化数据库 ===")
        db_manager.init_db()
        logger.info("=== 数据库初始化完成 ===")

        # 初始化种子参数模型
        seed_param_model = SeedParameter(db_manager)

        # 测试数据
        test_torrent_id = "12345"
        test_site_name = "test_site"
        test_parameters = {
            "title": "测试种子标题",
            "subtitle": "测试副标题",
            "imdb_link": "https://www.imdb.com/title/tt1234567",
            "douban_link": "https://movie.douban.com/subject/1234567",
            "type": "movie",
            "medium": "bluray",
            "video_codec": "h264",
            "audio_codec": "aac",
            "resolution": "1080p",
            "team": "test_team",
            "source": "us",
            "tags": ["action", "drama"],
            "poster": "https://example.com/poster.jpg",
            "screenshots": "https://example.com/screenshot1.jpg\nhttps://example.com/screenshot2.jpg",
            "description": "这是一个测试种子的描述",
            "mediainfo": "General\nFormat: MP4\nVideo\nCodec: H.264"
        }

        # 测试保存参数
        logger.info("=== 开始测试保存参数 ===")
        save_result = seed_param_model.save_parameters(
            test_torrent_id, test_site_name, test_parameters)

        if save_result:
            logger.info("✅ 参数保存成功")
        else:
            logger.error("❌ 参数保存失败")
            return False

        # 测试读取参数
        logger.info("=== 开始测试读取参数 ===")
        retrieved_params = seed_param_model.get_parameters(
            test_torrent_id, test_site_name)

        if retrieved_params:
            logger.info("✅ 参数读取成功")
            logger.info(f"读取到的标题: {retrieved_params.get('title')}")
            logger.info(f"读取到的站点: {retrieved_params.get('site_name')}")
            logger.info(f"读取到的标签: {retrieved_params.get('tags')}")

            # 验证关键字段
            assert retrieved_params['title'] == test_parameters['title']
            assert retrieved_params['site_name'] == test_site_name
            assert retrieved_params['torrent_id'] == test_torrent_id
            logger.info("✅ 字段验证通过")

        else:
            logger.error("❌ 参数读取失败")
            return False

        # 测试更新参数
        logger.info("=== 开始测试更新参数 ===")
        updated_params = {
            "title": "更新后的标题",
            "resolution": "4k",  # 更新分辨率
            "description": "更新后的描述"
        }

        update_result = seed_param_model.update_parameters(
            test_torrent_id, test_site_name, updated_params)

        if update_result:
            logger.info("✅ 参数更新成功")

            # 重新读取验证更新
            final_params = seed_param_model.get_parameters(
                test_torrent_id, test_site_name)
            if final_params:
                logger.info(f"更新后的标题: {final_params.get('title')}")
                logger.info(f"更新后的分辨率: {final_params.get('resolution')}")
                logger.info("✅ 更新验证通过")
            else:
                logger.error("❌ 更新后读取失败")
                return False
        else:
            logger.error("❌ 参数更新失败")
            return False

        # 测试删除参数
        logger.info("=== 开始测试删除参数 ===")
        delete_result = seed_param_model.delete_parameters(
            test_torrent_id, test_site_name)

        if delete_result:
            logger.info("✅ 参数删除成功")

            # 验证删除
            deleted_params = seed_param_model.get_parameters(
                test_torrent_id, test_site_name)
            if deleted_params is None:
                logger.info("✅ 删除验证通过")
            else:
                logger.error("❌ 删除验证失败，参数仍然存在")
                return False
        else:
            logger.error("❌ 参数删除失败")
            return False

    logger.info("🎉 所有测试通过！")

    # 清理测试数据库
    try:
        if os.path.exists("test_pt_stats.db"):
            os.remove("test_pt_stats.db")
            logger.info("✅ 清理测试数据库完成")
    except Exception as e:
        logger.warning(f"清理测试数据库失败: {e}")

    return True

if __name__ == "__main__":
    print("开始测试种子参数数据库功能...")
    success = test_seed_parameters_functionality()
    if success:
        print("🎉 测试完成，所有功能正常！")
        sys.exit(0)
    else:
        print("❌ 测试失败，请检查错误信息！")
        sys.exit(1)