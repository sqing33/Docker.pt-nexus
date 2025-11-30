#!/usr/bin/env python3
"""
数据库复合主键迁移脚本
将torrents表从单一主键(hash)迁移到复合主键(hash, downloader_id)

使用方法:
    python migrate_composite_primary_key.py

注意：
- 建议在执行前备份数据库
- 脚本会自动检测是否需要迁移
- 支持SQLite、MySQL、PostgreSQL
"""

import sys
import os
import logging

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import get_db_config
from database import DatabaseManager

def setup_logging():
    """设置日志"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('migration.log', encoding='utf-8')
        ]
    )

def backup_database(db_manager):
    """备份数据库"""
    logging.info("正在备份数据库...")
    import shutil
    from datetime import datetime

    if db_manager.db_type == "sqlite":
        backup_path = f"backup_pt_stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy2(db_manager.sqlite_path, backup_path)
        logging.info(f"SQLite数据库已备份到: {backup_path}")
        return backup_path
    else:
        logging.warning("MySQL/PostgreSQL请手动备份数据库")
        return None

def check_migration_needed(db_manager):
    """检查是否需要迁移"""
    logging.info("检查数据库表结构...")
    conn = db_manager._get_connection()
    cursor = db_manager._get_cursor(conn)

    try:
        if db_manager.db_type == "sqlite":
            cursor.execute("PRAGMA table_info(torrents)")
            columns = cursor.fetchall()

            # 检查主键列数
            cursor.execute("PRAGMA table_info(torrents)")
            columns = cursor.fetchall()
            primary_key_columns = [col for col in columns if col[5] == 1]  # pk == 1

            is_composite = len(primary_key_columns) > 1
            column_names = [col[1] for col in primary_key_columns]

        elif db_manager.db_type == "mysql":
            cursor.execute("SHOW INDEX FROM torrents WHERE Key_name = 'PRIMARY'")
            indexes = cursor.fetchall()
            is_composite = len(indexes) > 1
            column_names = [idx['Column_name'] for idx in indexes]

        elif db_manager.db_type == "postgresql":
            cursor.execute("""
                SELECT a.attname
                FROM pg_index i
                JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = 'torrents'::regclass AND i.indisprimary
            """)
            indexes = cursor.fetchall()
            is_composite = len(indexes) > 1
            column_names = [idx['attname'] for idx in indexes]

        if is_composite:
            logging.info(f"torrents表已经是复合主键，列: {column_names}")
            return False
        else:
            logging.info(f"torrents表当前是单一主键，列: {column_names}")
            return True

    finally:
        cursor.close()
        conn.close()

def migrate_composite_primary_key(db_manager):
    """执行复合主键迁移"""
    logging.info("开始执行复合主键迁移...")

    try:
        # 使用数据库内置的迁移函数
        db_manager.migrate_to_composite_primary_key()
        logging.info("✓ 成功迁移torrents表到复合主键结构")
        return True
    except Exception as e:
        logging.error(f"迁移过程中出错: {e}", exc_info=True)
        return False

def main():
    """主函数"""
    setup_logging()
    logging.info("开始复合主键迁移脚本")

    try:
        # 获取数据库配置
        db_config = get_db_config()
        db_manager = DatabaseManager(db_config)

        # 检查是否需要迁移
        if not check_migration_needed(db_manager):
            logging.info("无需迁移，脚本结束")
            return

        # 自动确认迁移（在测试环境中）
        logging.info("自动确认执行迁移...")

        # 备份数据库
        backup_path = backup_database(db_manager)

        # 执行迁移
        if migrate_composite_primary_key(db_manager):
            logging.info("迁移完成！")
            if backup_path:
                logging.info(f"备份文件: {backup_path}")
        else:
            logging.error("迁移失败！")
            if backup_path:
                logging.info(f"请从备份恢复: {backup_path}")

    except Exception as e:
        logging.error(f"脚本执行失败: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()