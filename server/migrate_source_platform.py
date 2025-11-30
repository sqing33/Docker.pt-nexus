#!/usr/bin/env python3
"""
数据库迁移脚本：修复 title_components 中片源平台的列表格式问题

将 title_components 中片源平台的值从列表格式 ["JPN"] 修改为字符串格式 "JPN"
和其他参数保持一致
"""

import json
import logging
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import DatabaseManager
from config import get_db_config

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def migrate_source_platform_list_to_string():
    """
    迁移 title_components 中的片源平台从列表格式到字符串格式
    """
    try:
        # 获取数据库配置并初始化数据库连接
        db_config = get_db_config()
        db_manager = DatabaseManager(db_config)

        # 获取数据库连接和游标
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        # 获取所有包含 title_components 的记录
        query = """
        SELECT hash, torrent_id, site_name, title_components
        FROM seed_parameters
        WHERE title_components IS NOT NULL
        AND title_components != ''
        """

        cursor.execute(query)
        records = cursor.fetchall()

        if not records:
            print("没有找到需要迁移的记录")
            logger.info("没有找到需要迁移的记录")
            return

        print(f"找到 {len(records)} 条记录需要检查")
        logger.info(f"找到 {len(records)} 条记录需要检查")

        # 先统计一下有多少条记录包含片源平台
        platform_records = 0
        list_platform_records = 0  # 需要修复的记录数

        for record in records:
            # 处理不同数据库返回的格式
            if isinstance(record, dict):
                hash_val = record['hash']
                torrent_id = record['torrent_id']
                site_name = record['site_name']
                title_components_str = record['title_components']
            else:
                hash_val, torrent_id, site_name, title_components_str = record

            print(f"检查记录: {hash_val[:8]}... {site_name} {torrent_id}")
            print(f"title_components 长度: {len(title_components_str) if title_components_str else 0}")
            print(f"title_components 内容: {title_components_str[:100] if title_components_str else 'NULL'}...")

            try:
                if not title_components_str:
                    print("  title_components 为空，跳过")
                    continue
                title_components = json.loads(title_components_str)
                for component in title_components:
                    if component.get("key") == "片源平台":
                        platform_records += 1
                        value = component.get("value")
                        print(f"  片源平台值: {value} (类型: {type(value)})")
                        if isinstance(value, list):
                            list_platform_records += 1
                        break
            except json.JSONDecodeError as e:
                print(f"  JSON 解析错误: {e}")
                continue

        print(f"其中 {platform_records} 条记录包含片源平台字段")
        print(f"其中 {list_platform_records} 条记录需要修复（列表格式）")
        logger.info(f"其中 {platform_records} 条记录包含片源平台字段")

        if list_platform_records == 0:
            print("没有需要修复的记录，迁移完成")
            return

        updated_count = 0

        for record in records:
            # 处理不同数据库返回的格式
            if isinstance(record, dict):
                hash_val = record['hash']
                torrent_id = record['torrent_id']
                site_name = record['site_name']
                title_components_str = record['title_components']
            else:
                hash_val, torrent_id, site_name, title_components_str = record

            try:
                if not title_components_str:
                    continue
                # 解析 title_components JSON
                title_components = json.loads(title_components_str)

                if not isinstance(title_components, list):
                    logger.warning(f"记录 {hash_val[:8]}... 的 title_components 不是列表格式，跳过")
                    continue

                # 检查是否有片源平台字段需要修复
                modified = False
                for component in title_components:
                    if component.get("key") == "片源平台":
                        value = component.get("value")

                        # 如果值是列表且只有一个元素，转换为字符串
                        if isinstance(value, list) and len(value) == 1:
                            old_value = value
                            new_value = value[0]
                            component["value"] = new_value
                            modified = True

                            logger.info(f"修复记录 {hash_val[:8]}... {site_name} {torrent_id}: "
                                      f'片源平台 {old_value} -> {new_value}')

                        # 如果值是列表但有多个元素，取第一个
                        elif isinstance(value, list) and len(value) > 1:
                            old_value = value
                            new_value = value[0]
                            component["value"] = new_value
                            modified = True

                            logger.info(f"修复记录 {hash_val[:8]}... {site_name} {torrent_id}: "
                                      f'片源平台 {old_value} -> {new_value} (多选第一个)')

                # 如果有修改，更新数据库
                if modified:
                    updated_title_components_str = json.dumps(title_components, ensure_ascii=False)

                    placeholder = db_manager.get_placeholder()
                    update_query = f"""
                    UPDATE seed_parameters
                    SET title_components = {placeholder}, updated_at = CURRENT_TIMESTAMP
                    WHERE hash = {placeholder} AND torrent_id = {placeholder} AND site_name = {placeholder}
                    """

                    cursor.execute(
                        update_query,
                        (updated_title_components_str, hash_val, torrent_id, site_name)
                    )

                    updated_count += 1

            except json.JSONDecodeError as e:
                logger.error(f"记录 {hash_val[:8]}... 的 title_components JSON 解析失败: {e}")
                continue
            except Exception as e:
                logger.error(f"处理记录 {hash_val[:8]}... 时出错: {e}")
                continue

        logger.info(f"迁移完成！共更新了 {updated_count} 条记录")

        # 提交事务
        conn.commit()

    except Exception as e:
        logger.error(f"迁移过程中发生错误: {e}")
        if 'conn' in locals():
            conn.rollback()
        raise
    finally:
        if 'conn' in locals():
            conn.close()


def verify_migration():
    """
    验证迁移结果，检查是否还有片源平台为列表格式的记录
    """
    try:
        db_config = get_db_config()
        db_manager = DatabaseManager(db_config)

        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)

        query = """
        SELECT hash, torrent_id, site_name, title_components
        FROM seed_parameters
        WHERE title_components IS NOT NULL
        AND title_components != ''
        """

        cursor.execute(query)
        records = cursor.fetchall()

        issue_count = 0

        for record in records:
            # 处理不同数据库返回的格式
            if isinstance(record, dict):
                hash_val = record['hash']
                torrent_id = record['torrent_id']
                site_name = record['site_name']
                title_components_str = record['title_components']
            else:
                hash_val, torrent_id, site_name, title_components_str = record

            try:
                if not title_components_str:
                    continue
                title_components = json.loads(title_components_str)

                for component in title_components:
                    if component.get("key") == "片源平台":
                        value = component.get("value")
                        if isinstance(value, list):
                            issue_count += 1
                            logger.warning(f"发现未修复的记录 {hash_val[:8]}... {site_name} {torrent_id}: "
                                         f'片源平台仍为列表格式 {value}')

            except json.JSONDecodeError:
                # JSON 解析错误的情况已经在迁移时处理过
                continue

        if issue_count == 0:
            logger.info("验证通过！所有片源平台都已正确转换为字符串格式")
        else:
            logger.warning(f"验证失败！还有 {issue_count} 条记录的片源平台仍为列表格式")

    except Exception as e:
        logger.error(f"验证过程中发生错误: {e}")
    finally:
        if 'conn' in locals():
            conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("数据库迁移脚本：修复片源平台列表格式问题")
    print("=" * 60)

    # 执行迁移
    logger.info("开始执行迁移...")
    migrate_source_platform_list_to_string()

    print("\n" + "=" * 60)
    print("验证迁移结果...")
    print("=" * 60)

    # 验证结果
    verify_migration()

    print("\n迁移脚本执行完成！")