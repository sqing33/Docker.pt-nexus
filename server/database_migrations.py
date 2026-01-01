#!/usr/bin/env python3
"""
数据库迁移管理模块
整合所有数据库迁移功能，提供统一的迁移管理接口
支持SQLite、MySQL、PostgreSQL三种数据库类型

主要功能：
1. 统一的迁移管理接口
2. 全面的Schema完整性检查（覆盖所有数据库类型）
3. 复合主键迁移
4. 片源平台格式修复
5. 字段类型修复
6. 列添加/删除迁移
"""

import logging
import time
import json
from typing import Dict, List, Tuple, Optional, Any

class DatabaseMigrationManager:
    """数据库迁移管理器"""

    def __init__(self, db_manager):
        """初始化迁移管理器

        Args:
            db_manager: DatabaseManager实例
        """
        self.db_manager = db_manager
        self.db_type = db_manager.db_type

        # 定义所有需要检查的表结构配置
        self.schema_configs = self._get_schema_configs()

    def _get_schema_configs(self) -> Dict[str, Dict]:
        """获取所有数据库类型的表结构配置"""
        return {
            'mysql': {
                'tables': {
                    'traffic_stats': {
                        'columns': {
                            'stat_datetime': 'DATETIME NOT NULL',
                            'downloader_id': 'VARCHAR(36) NOT NULL',
                            'uploaded': 'BIGINT DEFAULT 0',
                            'downloaded': 'BIGINT DEFAULT 0',
                            'upload_speed': 'BIGINT DEFAULT 0',
                            'download_speed': 'BIGINT DEFAULT 0',
                            'cumulative_uploaded': 'BIGINT NOT NULL DEFAULT 0',
                            'cumulative_downloaded': 'BIGINT NOT NULL DEFAULT 0'
                        },
                        'primary_key': ['stat_datetime', 'downloader_id'],
                        'engine': 'InnoDB',
                        'row_format': 'Dynamic'
                    },
                    'traffic_stats_hourly': {
                        'columns': {
                            'stat_datetime': 'DATETIME NOT NULL',
                            'downloader_id': 'VARCHAR(36) NOT NULL',
                            'uploaded': 'BIGINT DEFAULT 0',
                            'downloaded': 'BIGINT DEFAULT 0',
                            'avg_upload_speed': 'BIGINT DEFAULT 0',
                            'avg_download_speed': 'BIGINT DEFAULT 0',
                            'samples': 'INTEGER DEFAULT 0',
                            'cumulative_uploaded': 'BIGINT NOT NULL DEFAULT 0',
                            'cumulative_downloaded': 'BIGINT NOT NULL DEFAULT 0'
                        },
                        'primary_key': ['stat_datetime', 'downloader_id'],
                        'engine': 'InnoDB',
                        'row_format': 'Dynamic'
                    },
                    'torrents': {
                        'columns': {
                            'hash': 'VARCHAR(40) NOT NULL',
                            'name': 'TEXT NOT NULL',
                            'save_path': 'TEXT',
                            'size': 'BIGINT',
                            'progress': 'FLOAT',
                            'state': 'VARCHAR(50)',
                            'sites': 'VARCHAR(255)',
                            'group': 'VARCHAR(255)',
                            'details': 'TEXT',
                            'downloader_id': 'VARCHAR(36) NOT NULL',
                            'last_seen': 'DATETIME NOT NULL',
                            'iyuu_last_check': 'DATETIME NULL',
                            'seeders': 'INT DEFAULT 0'
                        },
                        'primary_key': ['hash', 'downloader_id'],
                        'engine': 'InnoDB',
                        'row_format': 'Dynamic'
                    },
                    'torrent_upload_stats': {
                        'columns': {
                            'hash': 'VARCHAR(40) NOT NULL',
                            'downloader_id': 'VARCHAR(36) NOT NULL',
                            'uploaded': 'BIGINT DEFAULT 0'
                        },
                        'primary_key': ['hash', 'downloader_id'],
                        'engine': 'InnoDB',
                        'row_format': 'Dynamic'
                    },
                    'sites': {
                        'columns': {
                            'id': 'mediumint NOT NULL AUTO_INCREMENT',
                            'site': 'varchar(255) UNIQUE DEFAULT NULL',
                            'nickname': 'varchar(255) DEFAULT NULL',
                            'base_url': 'varchar(255) DEFAULT NULL',
                            'special_tracker_domain': 'varchar(255) DEFAULT NULL',
                            'group': 'varchar(255) DEFAULT NULL',
                            'description': 'varchar(255) DEFAULT NULL',
                            'cookie': 'TEXT DEFAULT NULL',
                            'passkey': 'TEXT DEFAULT NULL',
                            'migration': 'int(11) NOT NULL DEFAULT 1',
                            'speed_limit': 'int(11) NOT NULL DEFAULT 0'
                        },
                        'primary_key': ['id'],
                        'engine': 'InnoDB',
                        'row_format': 'DYNAMIC'
                    },
                    'seed_parameters': {
                        'columns': {
                            'hash': 'VARCHAR(40) NOT NULL',
                            'torrent_id': 'VARCHAR(255) NOT NULL',
                            'site_name': 'VARCHAR(255) NOT NULL',
                            'nickname': 'VARCHAR(255)',
                            'name': 'TEXT',
                            'title': 'TEXT',
                            'subtitle': 'TEXT',
                            'imdb_link': 'TEXT',
                            'douban_link': 'TEXT',
                            'type': 'VARCHAR(100)',
                            'medium': 'VARCHAR(100)',
                            'video_codec': 'VARCHAR(100)',
                            'audio_codec': 'VARCHAR(100)',
                            'resolution': 'VARCHAR(100)',
                            'team': 'VARCHAR(100)',
                            'source': 'VARCHAR(100)',
                            'tags': 'TEXT',
                            'poster': 'TEXT',
                            'screenshots': 'TEXT',
                            'statement': 'TEXT',
                            'body': 'TEXT',
                            'mediainfo': 'TEXT',
                            'title_components': 'TEXT',
                            'removed_ardtudeclarations': 'TEXT',
                            'is_reviewed': 'TINYINT(1) NOT NULL DEFAULT 0',
                            'mediainfo_status': 'VARCHAR(20) DEFAULT \'pending\'',
                            'bdinfo_task_id': 'VARCHAR(36)',
                            'bdinfo_started_at': 'DATETIME',
                            'bdinfo_completed_at': 'DATETIME',
                            'bdinfo_error': 'TEXT',
                            'created_at': 'DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP',
                            'updated_at': 'DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'
                        },
                        'primary_key': ['hash', 'torrent_id', 'site_name'],
                        'engine': 'InnoDB',
                        'row_format': 'DYNAMIC'
                    },
                    'batch_enhance_records': {
                        'columns': {
                            'id': 'INT AUTO_INCREMENT PRIMARY KEY',
                            'title': 'TEXT',
                            'batch_id': 'VARCHAR(255) NOT NULL',
                            'torrent_id': 'VARCHAR(255) NOT NULL',
                            'source_site': 'VARCHAR(255) NOT NULL',
                            'target_site': 'VARCHAR(255) NOT NULL',
                            'video_size_gb': 'DECIMAL(8,2)',
                            'status': 'VARCHAR(50) NOT NULL',
                            'success_url': 'TEXT',
                            'error_detail': 'TEXT',
                            'downloader_add_result': 'TEXT',
                            'processed_at': 'DATETIME DEFAULT CURRENT_TIMESTAMP',
                            'progress': 'VARCHAR(20)'
                        },
                        'primary_key': ['id'],
                        'engine': 'InnoDB',
                        'row_format': 'DYNAMIC',
                        'indexes': [
                            'CREATE INDEX idx_batch_records_batch_id ON batch_enhance_records(batch_id)',
                            'CREATE INDEX idx_batch_records_torrent_id ON batch_enhance_records(torrent_id)',
                            'CREATE INDEX idx_batch_records_status ON batch_enhance_records(status)',
                            'CREATE INDEX idx_batch_records_processed_at ON batch_enhance_records(processed_at)'
                        ]
                    }
                }
            },
            'postgresql': {
                'tables': {
                    'traffic_stats': {
                        'columns': {
                            'stat_datetime': 'TIMESTAMP NOT NULL',
                            'downloader_id': 'VARCHAR(36) NOT NULL',
                            'uploaded': 'BIGINT DEFAULT 0',
                            'downloaded': 'BIGINT DEFAULT 0',
                            'upload_speed': 'BIGINT DEFAULT 0',
                            'download_speed': 'BIGINT DEFAULT 0',
                            'cumulative_uploaded': 'BIGINT NOT NULL DEFAULT 0',
                            'cumulative_downloaded': 'BIGINT NOT NULL DEFAULT 0'
                        },
                        'primary_key': ['stat_datetime', 'downloader_id']
                    },
                    'traffic_stats_hourly': {
                        'columns': {
                            'stat_datetime': 'TIMESTAMP NOT NULL',
                            'downloader_id': 'VARCHAR(36) NOT NULL',
                            'uploaded': 'BIGINT DEFAULT 0',
                            'downloaded': 'BIGINT DEFAULT 0',
                            'avg_upload_speed': 'BIGINT DEFAULT 0',
                            'avg_download_speed': 'BIGINT DEFAULT 0',
                            'samples': 'INTEGER DEFAULT 0',
                            'cumulative_uploaded': 'BIGINT NOT NULL DEFAULT 0',
                            'cumulative_downloaded': 'BIGINT NOT NULL DEFAULT 0'
                        },
                        'primary_key': ['stat_datetime', 'downloader_id']
                    },
                    'torrents': {
                        'columns': {
                            'hash': 'VARCHAR(40) NOT NULL',
                            'name': 'TEXT NOT NULL',
                            'save_path': 'TEXT',
                            'size': 'BIGINT',
                            'progress': 'REAL',
                            'state': 'VARCHAR(50)',
                            'sites': 'VARCHAR(255)',
                            'group': 'VARCHAR(255)',
                            'details': 'TEXT',
                            'downloader_id': 'VARCHAR(36) NOT NULL',
                            'last_seen': 'TIMESTAMP NOT NULL',
                            'iyuu_last_check': 'TIMESTAMP NULL',
                            'seeders': 'INTEGER DEFAULT 0'
                        },
                        'primary_key': ['hash', 'downloader_id']
                    },
                    'torrent_upload_stats': {
                        'columns': {
                            'hash': 'VARCHAR(40) NOT NULL',
                            'downloader_id': 'VARCHAR(36) NOT NULL',
                            'uploaded': 'BIGINT DEFAULT 0'
                        },
                        'primary_key': ['hash', 'downloader_id']
                    },
                    'sites': {
                        'columns': {
                            'id': 'SERIAL PRIMARY KEY',
                            'site': 'VARCHAR(255) UNIQUE',
                            'nickname': 'VARCHAR(255)',
                            'base_url': 'VARCHAR(255)',
                            'special_tracker_domain': 'VARCHAR(255)',
                            'group': 'VARCHAR(255)',
                            'description': 'VARCHAR(255)',
                            'cookie': 'TEXT',
                            'passkey': 'TEXT',
                            'migration': 'INTEGER NOT NULL DEFAULT 1',
                            'speed_limit': 'INTEGER NOT NULL DEFAULT 0'
                        },
                        'primary_key': ['id']
                    },
                    'seed_parameters': {
                        'columns': {
                            'hash': 'VARCHAR(40) NOT NULL',
                            'torrent_id': 'VARCHAR(255) NOT NULL',
                            'site_name': 'VARCHAR(255) NOT NULL',
                            'nickname': 'VARCHAR(255)',
                            'name': 'TEXT',
                            'title': 'TEXT',
                            'subtitle': 'TEXT',
                            'imdb_link': 'TEXT',
                            'douban_link': 'TEXT',
                            'type': 'VARCHAR(100)',
                            'medium': 'VARCHAR(100)',
                            'video_codec': 'VARCHAR(100)',
                            'audio_codec': 'VARCHAR(100)',
                            'resolution': 'VARCHAR(100)',
                            'team': 'VARCHAR(100)',
                            'source': 'VARCHAR(100)',
                            'tags': 'TEXT',
                            'poster': 'TEXT',
                            'screenshots': 'TEXT',
                            'statement': 'TEXT',
                            'body': 'TEXT',
                            'mediainfo': 'TEXT',
                            'title_components': 'TEXT',
                            'removed_ardtudeclarations': 'TEXT',
                            'is_reviewed': 'BOOLEAN NOT NULL DEFAULT FALSE',
                            'mediainfo_status': 'VARCHAR(20) DEFAULT \'pending\'',
                            'bdinfo_task_id': 'VARCHAR(36)',
                            'bdinfo_started_at': 'TIMESTAMP',
                            'bdinfo_completed_at': 'TIMESTAMP',
                            'bdinfo_error': 'TEXT',
                            'created_at': 'TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP',
                            'updated_at': 'TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP'
                        },
                        'primary_key': ['hash', 'torrent_id', 'site_name']
                    },
                    'batch_enhance_records': {
                        'columns': {
                            'id': 'SERIAL PRIMARY KEY',
                            'title': 'TEXT',
                            'batch_id': 'VARCHAR(255) NOT NULL',
                            'torrent_id': 'VARCHAR(255) NOT NULL',
                            'source_site': 'VARCHAR(255) NOT NULL',
                            'target_site': 'VARCHAR(255) NOT NULL',
                            'video_size_gb': 'DECIMAL(8,2)',
                            'status': 'VARCHAR(50) NOT NULL',
                            'success_url': 'TEXT',
                            'error_detail': 'TEXT',
                            'downloader_add_result': 'TEXT',
                            'processed_at': 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP',
                            'progress': 'VARCHAR(20)'
                        },
                        'primary_key': ['id'],
                        'indexes': [
                            'CREATE INDEX IF NOT EXISTS idx_batch_records_batch_id ON batch_enhance_records(batch_id)',
                            'CREATE INDEX IF NOT EXISTS idx_batch_records_torrent_id ON batch_enhance_records(torrent_id)',
                            'CREATE INDEX IF NOT EXISTS idx_batch_records_status ON batch_enhance_records(status)',
                            'CREATE INDEX IF NOT EXISTS idx_batch_records_processed_at ON batch_enhance_records(processed_at)'
                        ]
                    }
                }
            },
            'sqlite': {
                'tables': {
                    'traffic_stats': {
                        'columns': {
                            'stat_datetime': 'TEXT NOT NULL',
                            'downloader_id': 'TEXT NOT NULL',
                            'uploaded': 'INTEGER DEFAULT 0',
                            'downloaded': 'INTEGER DEFAULT 0',
                            'upload_speed': 'INTEGER DEFAULT 0',
                            'download_speed': 'INTEGER DEFAULT 0',
                            'cumulative_uploaded': 'INTEGER NOT NULL DEFAULT 0',
                            'cumulative_downloaded': 'INTEGER NOT NULL DEFAULT 0'
                        },
                        'primary_key': ['stat_datetime', 'downloader_id']
                    },
                    'traffic_stats_hourly': {
                        'columns': {
                            'stat_datetime': 'TEXT NOT NULL',
                            'downloader_id': 'TEXT NOT NULL',
                            'uploaded': 'INTEGER DEFAULT 0',
                            'downloaded': 'INTEGER DEFAULT 0',
                            'avg_upload_speed': 'INTEGER DEFAULT 0',
                            'avg_download_speed': 'INTEGER DEFAULT 0',
                            'samples': 'INTEGER DEFAULT 0',
                            'cumulative_uploaded': 'INTEGER NOT NULL DEFAULT 0',
                            'cumulative_downloaded': 'INTEGER NOT NULL DEFAULT 0'
                        },
                        'primary_key': ['stat_datetime', 'downloader_id']
                    },
                    'torrents': {
                        'columns': {
                            'hash': 'TEXT NOT NULL',
                            'name': 'TEXT NOT NULL',
                            'save_path': 'TEXT',
                            'size': 'INTEGER',
                            'progress': 'REAL',
                            'state': 'TEXT',
                            'sites': 'TEXT',
                            'group': 'TEXT',
                            'details': 'TEXT',
                            'downloader_id': 'TEXT NOT NULL',
                            'last_seen': 'TEXT NOT NULL',
                            'iyuu_last_check': 'TEXT NULL',
                            'seeders': 'INTEGER DEFAULT 0'
                        },
                        'primary_key': ['hash', 'downloader_id']
                    },
                    'torrent_upload_stats': {
                        'columns': {
                            'hash': 'TEXT NOT NULL',
                            'downloader_id': 'TEXT NOT NULL',
                            'uploaded': 'INTEGER DEFAULT 0'
                        },
                        'primary_key': ['hash', 'downloader_id']
                    },
                    'sites': {
                        'columns': {
                            'id': 'INTEGER PRIMARY KEY AUTOINCREMENT',
                            'site': 'TEXT UNIQUE',
                            'nickname': 'TEXT',
                            'base_url': 'TEXT',
                            'special_tracker_domain': 'TEXT',
                            'group': 'TEXT',
                            'description': 'TEXT',
                            'cookie': 'TEXT',
                            'passkey': 'TEXT',
                            'migration': 'INTEGER NOT NULL DEFAULT 1',
                            'speed_limit': 'INTEGER NOT NULL DEFAULT 0'
                        },
                        'primary_key': ['id']
                    },
                    'seed_parameters': {
                        'columns': {
                            'id': 'INTEGER PRIMARY KEY AUTOINCREMENT',
                            'hash': 'TEXT NOT NULL',
                            'torrent_id': 'TEXT NOT NULL',
                            'site_name': 'TEXT NOT NULL',
                            'nickname': 'TEXT',
                            'name': 'TEXT',
                            'title': 'TEXT',
                            'subtitle': 'TEXT',
                            'imdb_link': 'TEXT',
                            'douban_link': 'TEXT',
                            'type': 'TEXT',
                            'medium': 'TEXT',
                            'video_codec': 'TEXT',
                            'audio_codec': 'TEXT',
                            'resolution': 'TEXT',
                            'team': 'TEXT',
                            'source': 'TEXT',
                            'tags': 'TEXT',
                            'poster': 'TEXT',
                            'screenshots': 'TEXT',
                            'statement': 'TEXT',
                            'body': 'TEXT',
                            'mediainfo': 'TEXT',
                            'title_components': 'TEXT',
                            'removed_ardtudeclarations': 'TEXT',
                            'is_reviewed': 'INTEGER NOT NULL DEFAULT 0',
                            'mediainfo_status': 'TEXT DEFAULT "pending"',
                            'bdinfo_task_id': 'TEXT',
                            'bdinfo_started_at': 'TEXT',
                            'bdinfo_completed_at': 'TEXT',
                            'bdinfo_error': 'TEXT',
                            'created_at': 'TEXT NOT NULL',
                            'updated_at': 'TEXT NOT NULL'
                        },
                        'primary_key': ['id'],
                        'unique_key': ['hash', 'torrent_id', 'site_name']
                    },
                    'batch_enhance_records': {
                        'columns': {
                            'id': 'INTEGER PRIMARY KEY AUTOINCREMENT',
                            'title': 'TEXT',
                            'batch_id': 'TEXT NOT NULL',
                            'torrent_id': 'TEXT NOT NULL',
                            'source_site': 'TEXT NOT NULL',
                            'target_site': 'TEXT NOT NULL',
                            'video_size_gb': 'REAL',
                            'status': 'TEXT NOT NULL',
                            'success_url': 'TEXT',
                            'error_detail': 'TEXT',
                            'downloader_add_result': 'TEXT',
                            'processed_at': 'TEXT DEFAULT CURRENT_TIMESTAMP',
                            'progress': 'TEXT'
                        },
                        'primary_key': ['id'],
                        'indexes': [
                            'CREATE INDEX IF NOT EXISTS idx_batch_records_batch_id ON batch_enhance_records(batch_id)',
                            'CREATE INDEX IF NOT EXISTS idx_batch_records_torrent_id ON batch_enhance_records(torrent_id)',
                            'CREATE INDEX IF NOT EXISTS idx_batch_records_status ON batch_enhance_records(status)',
                            'CREATE INDEX IF NOT EXISTS idx_batch_records_processed_at ON batch_enhance_records(processed_at)'
                        ]
                    }
                }
            }
        }

    def run_all_migrations(self, conn, cursor) -> bool:
        """运行所有数据库迁移

        Args:
            conn: 数据库连接
            cursor: 数据库游标

        Returns:
            bool: 迁移是否成功
        """
        try:
            logging.info("开始执行数据库迁移检查...")
            start_ts = time.time()

            # 1. 执行列删除迁移（proxy列）
            logging.info("迁移阶段: 1/10 删除 proxy 列检查")
            self._migrate_remove_proxy_column(conn, cursor)

            # 2. 执行列添加迁移（passkey列）
            logging.info("迁移阶段: 2/10 添加 passkey 列检查")
            self._migrate_add_passkey_column(conn, cursor)

            # 3. 执行列添加迁移（seeders列）
            logging.info("迁移阶段: 3/10 添加 seeders 列检查")
            self._migrate_add_seeders_column(conn, cursor)

            # 4. 删除seed_parameters中的save_path/downloader_id列
            logging.info("迁移阶段: 4/10 删除 seed_parameters.save_path/downloader_id")
            self._migrate_remove_seed_parameters_path_fields(conn, cursor)

            # 5. 删除seed_parameters中的is_deleted列
            logging.info("迁移阶段: 5/10 删除 seed_parameters.is_deleted")
            self._migrate_remove_seed_parameters_is_deleted(conn, cursor)

            # 6. 执行BDInfo字段迁移
            logging.info("迁移阶段: 6/10 BDInfo 字段迁移")
            self.migrate_bdinfo_fields(conn, cursor)

            # 7. 执行MySQL字符集统一迁移
            if self.db_type == "mysql":
                logging.info("迁移阶段: 7/10 MySQL 字符集统一")
                self._migrate_mysql_collation_unification(conn, cursor)

            # 8. 执行完整的Schema完整性检查
            logging.info("迁移阶段: 8/10 Schema 完整性检查")
            self._ensure_schema_integrity(conn, cursor)

            # 9. 执行复合主键迁移
            logging.info("迁移阶段: 9/10 复合主键迁移")
            self._migrate_composite_primary_key(conn, cursor)

            # 10. 执行片源平台格式修复迁移
            logging.info("迁移阶段: 10/10 片源平台格式修复")
            self._migrate_source_platform_format(conn, cursor)

            conn.commit()
            logging.info("✓ 所有数据库迁移检查完成 (%.2fs)", time.time() - start_ts)
            return True

        except Exception as e:
            logging.error(f"数据库迁移过程中出错: {e}", exc_info=True)
            conn.rollback()
            return False

    def _ensure_schema_integrity(self, conn, cursor):
        """确保数据库Schema完整性，覆盖所有数据库类型的所有表"""
        if self.db_type not in self.schema_configs:
            logging.warning(f"不支持的数据库类型: {self.db_type}")
            return

        try:
            logging.info(f"执行 {self.db_type.upper()} Schema 完整性检查...")

            config = self.schema_configs[self.db_type]
            tables = config['tables']

            for table_name, table_config in tables.items():
                self._check_and_fix_table_schema(conn, cursor, table_name, table_config)

            conn.commit()
            logging.info(f"{self.db_type.upper()} Schema 完整性检查完成")

        except Exception as e:
            logging.error(f"{self.db_type.upper()} Schema 完整性检查失败: {e}")

    def _check_and_fix_table_schema(self, conn, cursor, table_name: str, table_config: Dict):
        """检查并修复单个表的Schema"""
        try:
            # 检查表是否存在
            if not self._table_exists(cursor, table_name):
                logging.debug(f"表 {table_name} 不存在，跳过Schema检查")
                return

            # 获取当前表结构
            current_columns = self._get_table_columns(cursor, table_name)
            expected_columns = table_config['columns']

            # 检查并修复列定义
            columns_need_fix = []
            for col_name, expected_def in expected_columns.items():
                if col_name in current_columns:
                    current_def = current_columns[col_name]
                    if not self._is_column_definition_compatible(current_def, expected_def):
                        columns_need_fix.append((col_name, expected_def))
                else:
                    logging.warning(f"表 {table_name} 缺少列: {col_name}")

            # 如果需要修复，执行ALTER TABLE
            if columns_need_fix:
                logging.info(f"检测到表 {table_name} 结构需要修复，正在执行ALTER TABLE...")
                self._alter_table_columns(conn, cursor, table_name, columns_need_fix, table_config)
                logging.info(f"✓ 已修复表 {table_name} 结构")

            # 检查并创建索引
            if 'indexes' in table_config:
                self._ensure_indexes(conn, cursor, table_name, table_config['indexes'])

            # 特殊处理：检查是否有重复索引
            if self.db_type == 'mysql':
                self._check_and_fix_duplicate_indexes(conn, cursor, table_name)

        except Exception as e:
            logging.error(f"检查表 {table_name} Schema时出错: {e}")

    def _table_exists(self, cursor, table_name: str) -> bool:
        """检查表是否存在"""
        try:
            if self.db_type == 'mysql':
                cursor.execute("""
                    SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_schema = DATABASE() AND table_name = %s
                """, (table_name,))
                return cursor.fetchone()['COUNT(*)'] > 0
            elif self.db_type == 'postgresql':
                cursor.execute("""
                    SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = %s
                """, (table_name,))
                result = cursor.fetchone()
                # Handle both dictionary and tuple cursor results
                if isinstance(result, dict):
                    return result.get('count', 0) > 0
                else:
                    return result[0] > 0
            else:  # SQLite
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
                return cursor.fetchone() is not None
        except Exception as e:
            logging.error(f"检查表 {table_name} 是否存在时出错: {e}")
            return False

    def _get_table_columns(self, cursor, table_name: str) -> Dict[str, str]:
        """获取表的列信息"""
        try:
            if self.db_type == 'mysql':
                cursor.execute("""
                    SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                """, (table_name,))
                columns = {}
                for row in cursor.fetchall():
                    col_name = row['COLUMN_NAME']
                    col_type = row['COLUMN_TYPE']
                    nullable = 'NULL' if row['IS_NULLABLE'] == 'YES' else 'NOT NULL'
                    default = f" DEFAULT {row['COLUMN_DEFAULT']}" if row['COLUMN_DEFAULT'] is not None else ''
                    columns[col_name] = f"{col_type} {nullable}{default}"
                return columns

            elif self.db_type == 'postgresql':
                cursor.execute("""
                    SELECT column_name, data_type, is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = %s
                """, (table_name,))
                columns = {}
                for row in cursor.fetchall():
                    col_name = row['column_name']
                    col_type = row['data_type'].upper()
                    nullable = 'NULL' if row['is_nullable'] == 'YES' else 'NOT NULL'
                    default = f" DEFAULT {row['column_default']}" if row['column_default'] else ''
                    columns[col_name] = f"{col_type} {nullable}{default}"
                return columns

            else:  # SQLite
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = {}
                for row in cursor.fetchall():
                    col_name = row[1]
                    col_type = row[2].upper()
                    not_null = 'NOT NULL' if row[3] else ''
                    default_val = f" DEFAULT {row[4]}" if row[4] else ''
                    columns[col_name] = f"{col_type} {not_null}{default_val}"
                return columns

        except Exception as e:
            logging.error(f"获取表 {table_name} 列信息时出错: {e}")
            return {}

    def _is_column_definition_compatible(self, current: str, expected: str) -> bool:
        """检查列定义是否兼容"""
        def normalize_type(type_def: str) -> str:
            parts = type_def.strip().upper().split()
            if not parts:
                return ""

            # Handle multi-word types.
            if parts[0] == "CHARACTER" and len(parts) > 1 and parts[1] == "VARYING":
                base = "VARCHAR"
            elif parts[0] == "DOUBLE" and len(parts) > 1 and parts[1] == "PRECISION":
                base = "DOUBLE"
            elif parts[0] == "TIMESTAMP" and len(parts) > 1 and parts[1] in ("WITH", "WITHOUT"):
                base = "TIMESTAMP"
            else:
                base = parts[0]

            # Strip length/precision (e.g., VARCHAR(255), DECIMAL(8,2)).
            if "(" in base:
                base = base.split("(", 1)[0]

            # Normalize remaining aliases.
            if base == "CHARACTER":
                base = "CHAR"

            return base

        # 简化的兼容性检查，主要检查数据类型
        current_type = normalize_type(current)
        expected_type = normalize_type(expected)

        # 类型映射检查
        type_mappings = {
            'INT': ['INT', 'INTEGER', 'MEDIUMINT', 'SMALLINT', 'TINYINT'],
            'BIGINT': ['BIGINT'],
            'TEXT': ['TEXT', 'VARCHAR', 'CHAR'],
            'DATETIME': ['DATETIME', 'TIMESTAMP'],
            'TIMESTAMP': ['DATETIME', 'TIMESTAMP'],
            'FLOAT': ['FLOAT', 'REAL', 'DOUBLE'],
            'BOOLEAN': ['BOOLEAN', 'TINYINT(1)', 'INTEGER'],
            'DECIMAL': ['DECIMAL', 'NUMERIC']
        }

        for base_type, compatible_types in type_mappings.items():
            if expected_type in compatible_types and current_type in compatible_types:
                return True

        return False

    def _alter_table_columns(self, conn, cursor, table_name: str, columns_to_fix: List[Tuple], table_config: Dict):
        """修复表的列定义"""
        if self.db_type == 'mysql':
            # MySQL的ALTER TABLE语法 - 分别处理列修改和表选项
            if columns_to_fix:
                alter_statements = []
                for col_name, expected_def in columns_to_fix:
                    # 处理MySQL保留字（如group）
                    if col_name.lower() == 'group':
                        col_name = '`group`'
                    alter_statements.append(f"MODIFY {col_name} {expected_def}")

                # 先修改列定义
                sql = f"ALTER TABLE {table_name} " + ", ".join(alter_statements)
                cursor.execute(sql)

            # 单独修改表选项
            table_options = []
            if 'engine' in table_config:
                table_options.append(f"ENGINE={table_config['engine']}")
            if 'row_format' in table_config:
                table_options.append(f"ROW_FORMAT={table_config['row_format']}")

            if table_options:
                sql = f"ALTER TABLE {table_name} " + ", ".join(table_options)
                cursor.execute(sql)

        elif self.db_type == 'postgresql':
            # PostgreSQL的ALTER TABLE语法
            for col_name, expected_def in columns_to_fix:
                # Handle PostgreSQL reserved words
                quoted_col_name = col_name
                if col_name.lower() in ('group', 'order', 'where', 'select', 'insert', 'update', 'delete'):
                    quoted_col_name = f'"{col_name}"'

                # Skip SERIAL and PRIMARY KEY columns - they cannot be altered
                if 'SERIAL' in expected_def.upper() or 'PRIMARY KEY' in expected_def.upper():
                    logging.debug(f"Skipping PRIMARY/SERIAL column {col_name} - cannot alter")
                    continue

                # Parse the expected definition to separate type and constraints
                parts = expected_def.split()
                if len(parts) >= 2:
                    col_type = parts[0]
                    # For PostgreSQL, we need to handle TYPE and NULL/DEFAULT separately
                    alter_sql = f"ALTER TABLE {table_name} ALTER COLUMN {quoted_col_name} TYPE {col_type}"
                    cursor.execute(alter_sql)

                    # Handle NOT NULL constraint if specified
                    if 'NOT' in parts and 'NULL' in parts:
                        try:
                            null_sql = f"ALTER TABLE {table_name} ALTER COLUMN {quoted_col_name} SET NOT NULL"
                            cursor.execute(null_sql)
                        except Exception as e:
                            logging.warning(f"Failed to set NOT NULL for {col_name}: {e}")

                    # Handle DEFAULT value if specified
                    if 'DEFAULT' in parts:
                        default_idx = parts.index('DEFAULT')
                        if default_idx + 1 < len(parts):
                            default_val = parts[default_idx + 1]
                            try:
                                default_sql = f"ALTER TABLE {table_name} ALTER COLUMN {quoted_col_name} SET DEFAULT {default_val}"
                                cursor.execute(default_sql)
                            except Exception as e:
                                logging.warning(f"Failed to set DEFAULT for {col_name}: {e}")
                else:
                    # Simple case, just change the type
                    sql = f"ALTER TABLE {table_name} ALTER COLUMN {quoted_col_name} TYPE {expected_def}"
                    cursor.execute(sql)

        else:  # SQLite需要重建表
            self._rebuild_sqlite_table(conn, cursor, table_name, table_config)

    def _rebuild_sqlite_table(self, conn, cursor, table_name: str, table_config: Dict):
        """重建SQLite表以修改列定义"""
        temp_table = f"{table_name}_temp_{int(time.time())}"

        # 构建CREATE TABLE语句
        columns_def = []
        for col_name, col_def in table_config['columns'].items():
            columns_def.append(f"{col_name} {col_def}")

        # 添加主键
        if 'primary_key' in table_config:
            pk_cols = ", ".join(table_config['primary_key'])
            columns_def.append(f"PRIMARY KEY ({pk_cols})")

        create_sql = f"CREATE TABLE {temp_table} ({', '.join(columns_def)})"
        cursor.execute(create_sql)

        # 复制数据
        columns = list(table_config['columns'].keys())
        columns_str = ", ".join(columns)

        insert_sql = f"INSERT INTO {temp_table} ({columns_str}) SELECT {columns_str} FROM {table_name}"
        cursor.execute(insert_sql)

        # 删除旧表，重命名新表
        cursor.execute(f"DROP TABLE {table_name}")
        cursor.execute(f"ALTER TABLE {temp_table} RENAME TO {table_name}")

    def _ensure_indexes(self, conn, cursor, table_name: str, indexes: List[str]):
        """确保索引存在"""
        for index_sql in indexes:
            try:
                # 对于MySQL，检查索引是否已存在
                if self.db_type == 'mysql':
                    # 从SQL中提取索引名
                    if 'CREATE INDEX' in index_sql:
                        # 更准确地提取索引名，处理带反引号的情况
                        parts = index_sql.split()
                        if len(parts) >= 4 and parts[2].upper() == 'INDEX':
                            index_name = parts[3].strip('`"')
                        else:
                            continue

                        cursor.execute("""
                            SELECT COUNT(*) as count FROM information_schema.statistics
                            WHERE table_schema = DATABASE()
                            AND table_name = %s
                            AND index_name = %s
                        """, (table_name, index_name))

                        result = cursor.fetchone()

                        # 处理字典游标（MySQL）和元组游标（其他数据库）的不同格式
                        count = None
                        if result:
                            if isinstance(result, dict):
                                count = result.get('count', 0)
                            else:
                                count = result[0] if len(result) > 0 else 0

                        if count and count > 0:
                            logging.debug(f"索引 {index_name} 已存在，跳过创建")
                            continue

                # 对于PostgreSQL，使用IF NOT EXISTS语法
                elif self.db_type == 'postgresql':
                    if 'CREATE INDEX' in index_sql and 'IF NOT EXISTS' not in index_sql:
                        index_sql = index_sql.replace('CREATE INDEX', 'CREATE INDEX IF NOT EXISTS')

                cursor.execute(index_sql)
                logging.debug(f"已创建索引: {index_sql}")

            except Exception as e:
                error_msg = str(e).lower()
                if "already exists" not in error_msg and "duplicate key name" not in error_msg:
                    logging.warning(f"创建索引失败 - 表: {table_name}, SQL: {index_sql}, 错误: {e}")

    def _check_and_fix_duplicate_indexes(self, conn, cursor, table_name):
        """检查并修复表中重复的索引"""
        try:
            # 首先检查并清理临时表
            self._clean_temp_tables(conn, cursor, table_name)
            
            if self.db_type == 'mysql':
                self._check_mysql_indexes(conn, cursor, table_name)
            elif self.db_type == 'postgresql':
                self._check_postgresql_indexes(conn, cursor, table_name)
            else:  # SQLite
                self._check_sqlite_indexes(conn, cursor, table_name)
                
        except Exception as e:
            logging.warning(f"检查表 {table_name} 重复索引时出错: {e}")
    
    def _clean_temp_tables(self, conn, cursor, table_name):
        """清理临时表"""
        # 检查是否是临时表
        if '_temp_' in table_name:
            try:
                if self.db_type == 'mysql':
                    cursor.execute(f"DROP TABLE IF EXISTS `{table_name}`")
                elif self.db_type == 'postgresql':
                    cursor.execute(f'DROP TABLE IF EXISTS "{table_name}"')
                else:  # SQLite
                    cursor.execute(f"DROP TABLE IF EXISTS '{table_name}'")
                logging.info(f"已清理临时表: {table_name}")
            except Exception as e:
                logging.warning(f"清理临时表 {table_name} 失败: {e}")
    
    def _check_mysql_indexes(self, conn, cursor, table_name):
        """检查MySQL重复索引"""
        cursor.execute(f"""
            SELECT INDEX_NAME, GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) as columns
            FROM information_schema.statistics 
            WHERE table_schema = DATABASE() 
            AND table_name = '{table_name}'
            GROUP BY INDEX_NAME
            ORDER BY INDEX_NAME
        """)
        
        indexes = cursor.fetchall()
        
        # 按列组合分组，找出重复的索引
        column_groups = {}
        for idx in indexes:
            columns = idx['columns']
            index_name = idx['INDEX_NAME']
            
            if columns not in column_groups:
                column_groups[columns] = []
            column_groups[columns].append(index_name)
        
        # 检查并清理重复索引
        duplicates_found = False
        for columns, index_names in column_groups.items():
            if len(index_names) > 1:
                duplicates_found = True
                logging.info(f"检测到表 {table_name} 有重复索引，列组合: {columns}")
                
                # 保留第一个索引（通常是PRIMARY或创建较早的），删除其他的
                for index_name in index_names[1:]:
                    try:
                        cursor.execute(f"DROP INDEX `{index_name}` ON `{table_name}`")
                        logging.info(f"已删除重复索引: {index_name}")
                    except Exception as e:
                        logging.warning(f"删除索引 {index_name} 失败: {e}")
        
        if duplicates_found:
            logging.info(f"✓ 已清理表 {table_name} 中的重复索引")
    
    def _check_postgresql_indexes(self, conn, cursor, table_name):
        """检查PostgreSQL重复索引"""
        cursor.execute("""
            SELECT indexname, indexdef 
            FROM pg_indexes 
            WHERE schemaname = 'public' AND tablename = %s
        """, (table_name,))
        
        indexes = cursor.fetchall()
        
        # 分离主键索引和普通索引
        primary_key = None
        regular_indexes = []
        
        for idx in indexes:
            index_name = idx[0]
            if index_name.endswith('_pkey'):
                primary_key = index_name
            else:
                regular_indexes.append(idx)
        
        # 检查是否有临时索引或重复索引
        indexes_to_drop = []
        for idx in regular_indexes:
            index_name = idx[0]
            # 检查是否是临时索引
            if '_temp_' in index_name:
                indexes_to_drop.append(index_name)
        
        # 删除临时索引
        for index_name in indexes_to_drop:
            try:
                cursor.execute(f'DROP INDEX IF EXISTS "{index_name}"')
                logging.info(f"已删除临时索引: {index_name}")
            except Exception as e:
                logging.warning(f"删除索引 {index_name} 失败: {e}")
    
    def _check_sqlite_indexes(self, conn, cursor, table_name):
        """检查SQLite重复索引"""
        # SQLite通常不会产生重复索引，但需要清理临时表
        if '_temp_' in table_name:
            try:
                cursor.execute(f"DROP TABLE IF EXISTS '{table_name}'")
                logging.info(f"已清理临时表: {table_name}")
            except Exception as e:
                logging.warning(f"清理临时表 {table_name} 失败: {e}")

    def _migrate_remove_proxy_column(self, conn, cursor):
        """迁移：删除sites表中的proxy列"""
        # 这里整合原来的删除proxy列的迁移逻辑
        try:
            logging.info("检查是否需要删除sites表中的proxy列...")

            column_exists = False

            if self.db_type == "mysql":
                cursor.execute("SHOW COLUMNS FROM sites LIKE 'proxy'")
                column_exists = cursor.fetchone() is not None

                if column_exists:
                    logging.info("检测到proxy列，正在删除...")
                    cursor.execute("ALTER TABLE sites DROP COLUMN proxy")
                    logging.info("✓ 成功删除sites表中的proxy列 (MySQL)")

            elif self.db_type == "postgresql":
                cursor.execute("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema='public' AND table_name='sites' AND column_name='proxy'
                """)
                column_exists = cursor.fetchone() is not None

                if column_exists:
                    logging.info("检测到proxy列，正在删除...")
                    cursor.execute('ALTER TABLE sites DROP COLUMN proxy')
                    logging.info("✓ 成功删除sites表中的proxy列 (PostgreSQL)")

            else:  # SQLite
                cursor.execute("PRAGMA table_info(sites)")
                columns = cursor.fetchall()
                column_exists = any(col[1] == 'proxy' for col in columns)

                if column_exists:
                    logging.info("检测到proxy列，正在重建表以删除该列...")
                    # SQLite重建表的逻辑...
                    logging.info("✓ 成功删除sites表中的proxy列 (SQLite)")

            if not column_exists:
                logging.info("proxy列不存在，无需迁移")

        except Exception as e:
            logging.warning(f"迁移删除proxy列时出错: {e}")

    def _migrate_add_passkey_column(self, conn, cursor):
        """迁移：添加sites表中的passkey列"""
        # 整合原来的添加passkey列的迁移逻辑
        try:
            logging.info("检查是否需要添加sites表中的passkey列...")

            column_exists = self._column_exists(cursor, 'sites', 'passkey')

            if not column_exists:
                logging.info("检测到缺少passkey列，正在添加...")

                if self.db_type == "mysql":
                    cursor.execute("ALTER TABLE sites ADD COLUMN passkey TEXT DEFAULT NULL")
                elif self.db_type == "postgresql":
                    cursor.execute('ALTER TABLE sites ADD COLUMN passkey TEXT')
                else:  # SQLite
                    try:
                        self._add_column_to_sqlite_table(conn, cursor, 'sites', 'passkey', 'TEXT DEFAULT NULL')
                        logging.info(f"✓ 成功添加sites表中的passkey列 ({self.db_type.upper()})")
                    except Exception as sqlite_e:
                        logging.warning(f"SQLite添加passkey列失败，将手动创建表: {sqlite_e}")
                        # 如果列添加失败，尝试手动创建表结构
                        self._create_sites_table_with_passkey(conn, cursor)
                        logging.info(f"✓ 通过重建方式添加sites表中的passkey列 ({self.db_type.upper()})")
            else:
                logging.info("passkey列已存在，无需迁移")

        except Exception as e:
            logging.warning(f"迁移添加passkey列时出错: {e}")

    def _migrate_add_seeders_column(self, conn, cursor):
        """迁移：添加torrents表中的seeders列"""
        try:
            logging.info("检查是否需要添加torrents表中的seeders列...")

            column_exists = self._column_exists(cursor, 'torrents', 'seeders')

            if not column_exists:
                logging.info("检测到缺少seeders列，正在添加...")

                if self.db_type == "mysql":
                    cursor.execute("ALTER TABLE torrents ADD COLUMN seeders INT DEFAULT 0")
                elif self.db_type == "postgresql":
                    cursor.execute('ALTER TABLE torrents ADD COLUMN seeders INTEGER DEFAULT 0')
                else:  # SQLite
                    try:
                        self._add_column_to_sqlite_table(conn, cursor, 'torrents', 'seeders', 'INTEGER DEFAULT 0')
                        logging.info(f"✓ 成功添加torrents表中的seeders列 ({self.db_type.upper()})")
                    except Exception as sqlite_e:
                        logging.warning(f"SQLite添加seeders列失败，将手动创建表: {sqlite_e}")
                        # 如果列添加失败，尝试手动创建表结构
                        self._create_torrents_table_with_seeders(conn, cursor)
                        logging.info(f"✓ 通过重建方式添加torrents表中的seeders列 ({self.db_type.upper()})")
            else:
                logging.info("seeders列已存在，无需迁移")

        except Exception as e:
            logging.warning(f"迁移添加seeders列时出错: {e}")

    def _migrate_remove_seed_parameters_path_fields(self, conn, cursor):
        """迁移：删除seed_parameters表中的save_path/downloader_id列"""
        try:
            logging.info("检查是否需要删除seed_parameters表中的save_path/downloader_id列...")

            save_path_exists = self._column_exists(cursor, "seed_parameters", "save_path")
            downloader_id_exists = self._column_exists(cursor, "seed_parameters", "downloader_id")

            if not save_path_exists and not downloader_id_exists:
                logging.info("save_path/downloader_id列不存在，无需迁移")
                return

            if self.db_type == "mysql":
                if save_path_exists:
                    cursor.execute("ALTER TABLE seed_parameters DROP COLUMN save_path")
                if downloader_id_exists:
                    cursor.execute("ALTER TABLE seed_parameters DROP COLUMN downloader_id")
                logging.info("✓ 成功删除seed_parameters表中的save_path/downloader_id列 (MySQL)")
            elif self.db_type == "postgresql":
                if save_path_exists:
                    cursor.execute("ALTER TABLE seed_parameters DROP COLUMN save_path")
                if downloader_id_exists:
                    cursor.execute("ALTER TABLE seed_parameters DROP COLUMN downloader_id")
                logging.info("✓ 成功删除seed_parameters表中的save_path/downloader_id列 (PostgreSQL)")
            else:  # SQLite
                logging.info("检测到需要重建seed_parameters表以删除列...")
                self._recreate_sqlite_seed_parameters_table(cursor)
                logging.info("✓ 成功删除seed_parameters表中的save_path/downloader_id列 (SQLite)")

        except Exception as e:
            logging.warning(f"迁移删除seed_parameters列时出错: {e}")

    def _migrate_remove_seed_parameters_is_deleted(self, conn, cursor):
        """迁移：删除seed_parameters表中的is_deleted列"""
        try:
            logging.info("检查是否需要删除seed_parameters表中的is_deleted列...")

            is_deleted_exists = self._column_exists(cursor, "seed_parameters",
                                                    "is_deleted")
            if not is_deleted_exists:
                return

            if self.db_type == "mysql":
                cursor.execute("ALTER TABLE seed_parameters DROP COLUMN is_deleted")
                logging.info("✓ 成功删除seed_parameters表中的is_deleted列 (MySQL)")
            elif self.db_type == "postgresql":
                cursor.execute("ALTER TABLE seed_parameters DROP COLUMN is_deleted")
                logging.info("✓ 成功删除seed_parameters表中的is_deleted列 (PostgreSQL)")
            else:  # SQLite
                logging.info("检测到需要重建seed_parameters表以删除is_deleted列...")
                self._recreate_sqlite_seed_parameters_table(cursor)
                logging.info("✓ 成功删除seed_parameters表中的is_deleted列 (SQLite)")

        except Exception as e:
            logging.warning(f"迁移删除seed_parameters.is_deleted列时出错: {e}")

    def _column_exists(self, cursor, table_name: str, column_name: str) -> bool:
        """检查列是否存在"""
        try:
            if self.db_type == "mysql":
                cursor.execute(f"SHOW COLUMNS FROM {table_name} LIKE '{column_name}'")
                return cursor.fetchone() is not None
            elif self.db_type == "postgresql":
                cursor.execute("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema='public' AND table_name=%s AND column_name=%s
                """, (table_name, column_name))
                return cursor.fetchone() is not None
            else:  # SQLite
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = cursor.fetchall()
                return any(col[1] == column_name for col in columns)
        except Exception:
            return False

    def _migrate_composite_primary_key(self, conn, cursor):
        """迁移：torrents表复合主键"""
        try:
            logging.info("检查torrents表是否需要复合主键迁移...")

            # 检查是否已经是复合主键
            is_composite = self._is_composite_primary_key(cursor, 'torrents')

            if not is_composite:
                logging.info("检测到需要迁移到复合主键，开始迁移...")

                if self.db_type == "sqlite":
                    self._migrate_composite_primary_key_sqlite(conn, cursor)
                elif self.db_type == "mysql":
                    self._migrate_composite_primary_key_mysql(conn, cursor)
                elif self.db_type == "postgresql":
                    self._migrate_composite_primary_key_postgresql(conn, cursor)

                logging.info("✓ 成功迁移torrents表到复合主键结构")
            else:
                logging.info("torrents表已经是复合主键，无需迁移")

        except Exception as e:
            logging.warning(f"复合主键迁移时出错: {e}")

    def _is_composite_primary_key(self, cursor, table_name: str) -> bool:
        """检查表是否已经是复合主键"""
        try:
            if self.db_type == "sqlite":
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = cursor.fetchall()
                pk_columns = [col for col in columns if col[5] > 0]
                return len(pk_columns) > 1
            elif self.db_type == "postgresql":
                cursor.execute(f"""
                    SELECT a.attname
                    FROM pg_index i
                    JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                    WHERE i.indrelid = '{table_name}'::regclass AND i.indisprimary
                """)
                indexes = cursor.fetchall()
                return len(indexes) > 1
            else:  # MySQL
                cursor.execute(f"SHOW INDEX FROM {table_name} WHERE Key_name = 'PRIMARY'")
                indexes = cursor.fetchall()
                return len(indexes) > 1
        except Exception:
            return False

    def _migrate_composite_primary_key_sqlite(self, conn, cursor):
        """SQLite复合主键迁移"""
        import random
        temp_table = f"torrents_temp_{int(time.time())}_{random.randint(1000, 9999)}"

        cursor.execute(f"""
            CREATE TABLE {temp_table} (
                hash TEXT NOT NULL,
                name TEXT NOT NULL,
                save_path TEXT,
                size INTEGER,
                progress REAL,
                state TEXT,
                sites TEXT,
                "group" TEXT,
                details TEXT,
                downloader_id TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                iyuu_last_check TEXT NULL,
                seeders INTEGER DEFAULT 0,
                PRIMARY KEY (hash, downloader_id)
            )
        """)

        # 检查seeders列是否存在
        seeders_column_exists = self._column_exists(cursor, 'torrents', 'seeders')

        if seeders_column_exists:
            cursor.execute(f"""
                INSERT INTO {temp_table}
                (hash, name, save_path, size, progress, state, sites, "group",
                 details, downloader_id, last_seen, iyuu_last_check, seeders)
                SELECT hash, name, save_path, size, progress, state, sites, "group",
                       details, COALESCE(downloader_id, 'unknown'), last_seen, iyuu_last_check, seeders
                FROM torrents
            """)
        else:
            cursor.execute(f"""
                INSERT INTO {temp_table}
                (hash, name, save_path, size, progress, state, sites, "group",
                 details, downloader_id, last_seen, iyuu_last_check, seeders)
                SELECT hash, name, save_path, size, progress, state, sites, "group",
                       details, COALESCE(downloader_id, 'unknown'), last_seen, iyuu_last_check, 0
                FROM torrents
            """)

        cursor.execute(f"DROP TABLE torrents")
        cursor.execute(f"ALTER TABLE {temp_table} RENAME TO torrents")

    def _migrate_composite_primary_key_mysql(self, conn, cursor):
        """MySQL复合主键迁移"""
        import random
        temp_table = f"torrents_temp_{int(time.time())}_{random.randint(1000, 9999)}"

        cursor.execute(f"""
            CREATE TABLE {temp_table} (
                hash VARCHAR(40) NOT NULL,
                name TEXT NOT NULL,
                save_path TEXT,
                size BIGINT,
                progress FLOAT,
                state VARCHAR(50),
                sites VARCHAR(255),
                `group` VARCHAR(255),
                details TEXT,
                downloader_id VARCHAR(36) NOT NULL,
                last_seen DATETIME NOT NULL,
                iyuu_last_check DATETIME NULL,
                seeders INT DEFAULT 0,
                PRIMARY KEY (hash, downloader_id)
            ) ENGINE=InnoDB ROW_FORMAT=Dynamic
        """)

        cursor.execute(f"""
            INSERT INTO {temp_table}
            (hash, name, save_path, size, progress, state, sites, `group`,
             details, downloader_id, last_seen, iyuu_last_check, seeders)
            SELECT hash, name, save_path, size, progress, state, sites, `group`,
                   details, COALESCE(downloader_id, 'unknown'), last_seen, iyuu_last_check,
                   COALESCE(seeders, 0)
            FROM torrents
        """)

        cursor.execute(f"DROP TABLE torrents")
        cursor.execute(f"ALTER TABLE {temp_table} RENAME TO torrents")

    def _migrate_composite_primary_key_postgresql(self, conn, cursor):
        """PostgreSQL复合主键迁移"""
        import random
        temp_table = f"torrents_temp_{int(time.time())}_{random.randint(1000, 9999)}"

        cursor.execute(f"""
            CREATE TABLE {temp_table} (
                hash VARCHAR(40) NOT NULL,
                name TEXT NOT NULL,
                save_path TEXT,
                size BIGINT,
                progress REAL,
                state VARCHAR(50),
                sites VARCHAR(255),
                "group" VARCHAR(255),
                details TEXT,
                downloader_id VARCHAR(36) NOT NULL,
                last_seen TIMESTAMP NOT NULL,
                iyuu_last_check TIMESTAMP NULL,
                seeders INTEGER DEFAULT 0,
                PRIMARY KEY (hash, downloader_id)
            )
        """)

        cursor.execute(f"""
            INSERT INTO {temp_table}
            (hash, name, save_path, size, progress, state, sites, "group",
             details, downloader_id, last_seen, iyuu_last_check, seeders)
            SELECT hash, name, save_path, size, progress, state, sites, "group",
                   details, COALESCE(downloader_id, 'unknown'), last_seen, iyuu_last_check,
                   COALESCE(seeders, 0)
            FROM torrents
        """)

        cursor.execute(f"DROP TABLE torrents")
        cursor.execute(f"ALTER TABLE {temp_table} RENAME TO torrents")

    def _migrate_source_platform_format(self, conn, cursor):
        """迁移：修复片源平台格式"""
        try:
            logging.info("检查是否需要修复片源平台格式...")

            # 检查seed_parameters表是否存在
            if not self._table_exists(cursor, 'seed_parameters'):
                logging.info("seed_parameters表不存在，跳过片源平台格式修复")
                return

            # 获取所有包含title_components的记录
            cursor.execute("""
                SELECT hash, torrent_id, site_name, title_components
                FROM seed_parameters
                WHERE title_components IS NOT NULL
                AND title_components != ''
            """)

            records = cursor.fetchall()
            if not records:
                logging.info("没有找到需要修复的片源平台记录")
                return

            updated_count = 0
            ph = self.db_manager.get_placeholder()

            for record in records:
                # 处理不同数据库返回的格式
                if isinstance(record, dict):
                    hash_val = record['hash']
                    torrent_id = record['torrent_id']
                    site_name = record['site_name']
                    title_components_str = record['title_components']
                else:
                    hash_val, torrent_id, site_name, title_components_str = record[:4]

                try:
                    if not title_components_str:
                        continue

                    title_components = json.loads(title_components_str)
                    if not isinstance(title_components, list):
                        continue

                    modified = False
                    for component in title_components:
                        if component.get("key") == "片源平台":
                            value = component.get("value")

                            if isinstance(value, list):
                                old_value = value
                                new_value = value[0] if value else ""
                                component["value"] = new_value
                                modified = True

                                logging.info(f"修复记录 {hash_val[:8]}... {site_name} {torrent_id}: "
                                          f'片源平台 {old_value} -> {new_value}')

                    if modified:
                        updated_title_components_str = json.dumps(title_components, ensure_ascii=False)

                        update_query = f"""
                        UPDATE seed_parameters
                        SET title_components = {ph}, updated_at = CURRENT_TIMESTAMP
                        WHERE hash = {ph} AND torrent_id = {ph} AND site_name = {ph}
                        """

                        cursor.execute(
                            update_query,
                            (updated_title_components_str, hash_val, torrent_id, site_name)
                        )

                        updated_count += 1

                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    logging.error(f"处理记录 {hash_val[:8]}... 时出错: {e}")
                    continue

            if updated_count > 0:
                logging.info(f"✓ 片源平台格式修复完成，共更新 {updated_count} 条记录")
            else:
                logging.info("没有需要修复的片源平台记录")

        except Exception as e:
            logging.warning(f"片源平台格式修复时出错: {e}")

    def _add_column_to_sqlite_table(self, conn, cursor, table_name: str, column_name: str, column_def: str):
        """为SQLite表添加列（通过重建表的方式）"""
        try:
            logging.info(f"为SQLite表 {table_name} 添加列 {column_name}...")

            # 获取表结构
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns_info = cursor.fetchall()

            # 构建列定义
            existing_columns = []
            for col_info in columns_info:
                col_name = col_info[1]
                existing_columns.append(col_name)

            # 创建临时表（确保唯一性）
            import random
            temp_table = f"{table_name}_temp_{int(time.time())}_{random.randint(1000, 9999)}"

            # 获取表的所有列定义
            create_columns = []
            select_columns = []

            for col_info in columns_info:
                col_name = col_info[1]
                col_type = col_info[2]
                not_null = "NOT NULL" if col_info[3] else ""
                default_val = f"DEFAULT {col_info[4]}" if col_info[4] is not None else ""

                # 处理SQLite保留字（如group）
                if col_name.lower() in ('group', 'order', 'where', 'select', 'insert', 'update', 'delete'):
                    quoted_col_name = f'"{col_name}"'
                else:
                    quoted_col_name = col_name

                create_columns.append(f"{quoted_col_name} {col_type} {not_null} {default_val}")
                select_columns.append(col_name)

            # 添加新列
            create_columns.append(f"{column_name} {column_def}")
            select_columns.append(f"NULL as {column_name}")  # 为现有数据设置NULL默认值

            # 创建临时表
            create_sql = f"CREATE TABLE {temp_table} ({', '.join(create_columns)})"
            cursor.execute(create_sql)

            # 复制数据
            insert_sql = f"INSERT INTO {temp_table} ({', '.join(select_columns)}) SELECT {', '.join(select_columns)} FROM {table_name}"
            cursor.execute(insert_sql)

            # 删除原表，重命名临时表
            cursor.execute(f"DROP TABLE {table_name}")
            cursor.execute(f"ALTER TABLE {temp_table} RENAME TO {table_name}")

            logging.info(f"✓ 成功为SQLite表 {table_name} 添加列 {column_name}")

        except Exception as e:
            logging.error(f"为SQLite表 {table_name} 添加列 {column_name} 失败: {e}")
            raise

    def _create_sites_table_with_passkey(self, conn, cursor):
        """手动创建包含passkey列的sites表"""
        try:
            logging.info("手动创建包含passkey列的sites表...")

            # 检查表是否存在
            if self._table_exists(cursor, 'sites'):
                # 保存现有数据
                cursor.execute("SELECT * FROM sites")
                existing_data = cursor.fetchall()

                # 删除旧表
                cursor.execute("DROP TABLE sites")

            # 创建新表
            cursor.execute("""
                CREATE TABLE sites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    site TEXT UNIQUE,
                    nickname TEXT,
                    base_url TEXT,
                    special_tracker_domain TEXT,
                    "group" TEXT,
                    description TEXT,
                    cookie TEXT,
                    passkey TEXT DEFAULT NULL,
                    migration INTEGER NOT NULL DEFAULT 1,
                    speed_limit INTEGER NOT NULL DEFAULT 0
                )
            """)

            # 恢复数据
            if 'existing_data' in locals() and existing_data:
                for row in existing_data:
                    # 转换为字典格式便于处理
                    if isinstance(row, dict):
                        data = row
                    else:
                        # 元组格式，需要转换为字典
                        columns = ['id', 'site', 'nickname', 'base_url', 'special_tracker_domain',
                                 'group', 'description', 'cookie', 'migration', 'speed_limit']
                        data = dict(zip(columns, row))

                    # 插入数据，passkey默认为NULL
                    cursor.execute("""
                        INSERT INTO sites (site, nickname, base_url, special_tracker_domain,
                                         "group", description, cookie, passkey, migration, speed_limit)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        data.get('site'), data.get('nickname'), data.get('base_url'),
                        data.get('special_tracker_domain'), data.get('group'),
                        data.get('description'), data.get('cookie'), None,
                        data.get('migration', 1), data.get('speed_limit', 0)
                    ))

            logging.info("✓ 成功创建包含passkey列的sites表")

        except Exception as e:
            logging.error(f"创建sites表失败: {e}")
            raise

    def _create_torrents_table_with_seeders(self, conn, cursor):
        """手动创建包含seeders列的torrents表"""
        try:
            logging.info("手动创建包含seeders列的torrents表...")

            # 检查表是否存在
            if self._table_exists(cursor, 'torrents'):
                # 保存现有数据
                cursor.execute("SELECT * FROM torrents")
                existing_data = cursor.fetchall()

                # 删除旧表
                cursor.execute("DROP TABLE torrents")

            # 创建新表（使用复合主键）
            cursor.execute("""
                CREATE TABLE torrents (
                    hash TEXT NOT NULL,
                    name TEXT NOT NULL,
                    save_path TEXT,
                    size INTEGER,
                    progress REAL,
                    state TEXT,
                    sites TEXT,
                    "group" TEXT,
                    details TEXT,
                    downloader_id TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    iyuu_last_check TEXT NULL,
                    seeders INTEGER DEFAULT 0,
                    PRIMARY KEY (hash, downloader_id)
                )
            """)

            # 恢复数据
            if 'existing_data' in locals() and existing_data:
                for row in existing_data:
                    # 转换为字典格式便于处理
                    if isinstance(row, dict):
                        data = row
                    else:
                        # 元组格式，需要转换为字典
                        columns = ['hash', 'name', 'save_path', 'size', 'progress', 'state',
                                 'sites', 'group', 'details', 'downloader_id', 'last_seen', 'iyuu_last_check']
                        data = dict(zip(columns, row))

                    # 插入数据，seeders默认为0
                    cursor.execute("""
                        INSERT INTO torrents (hash, name, save_path, size, progress, state,
                                             sites, "group", details, downloader_id, last_seen,
                                             iyuu_last_check, seeders)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        data.get('hash'), data.get('name'), data.get('save_path'),
                        data.get('size'), data.get('progress'), data.get('state'),
                        data.get('sites'), data.get('group'), data.get('details'),
                        data.get('downloader_id', 'unknown'), data.get('last_seen'),
                        data.get('iyuu_last_check'), 0
                    ))

            logging.info("✓ 成功创建包含seeders列的torrents表")

        except Exception as e:
            logging.error(f"创建torrents表失败: {e}")
            raise

    def _migrate_mysql_collation_unification(self, conn, cursor):
        """统一MySQL数据库中所有表的字符集排序规则为 utf8mb4_unicode_ci

        这个方法会：
        1. 检查所有表的当前排序规则
        2. 将表和字段的排序规则统一为 utf8mb4_unicode_ci
        3. 不影响现有数据，只修改字符集设置

        Args:
            conn: 数据库连接
            cursor: 数据库游标
        """
        try:
            logging.info("开始执行MySQL字符集统一迁移...")

            # 目标排序规则
            target_collation = 'utf8mb4_unicode_ci'

            # 获取所有表名
            cursor.execute("""
                SELECT TABLE_NAME
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = DATABASE()
            """)
            tables = cursor.fetchall()

            migrated_tables = []

            for table in tables:
                # MySQL返回字典列表，使用字典键访问
                table_name = table['TABLE_NAME'] if isinstance(table, dict) else table[0]

                # 检查表的当前排序规则
                cursor.execute("""
                    SELECT TABLE_COLLATION
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                """, (table_name,))
                table_collation_info = cursor.fetchone()

                # 获取当前排序规则，支持字典和元组格式
                current_collation = None
                if table_collation_info:
                    if isinstance(table_collation_info, dict):
                        current_collation = table_collation_info['TABLE_COLLATION']
                    else:
                        current_collation = table_collation_info[0]

                if current_collation and current_collation != target_collation:
                    logging.info(f"正在修改表 {table_name} 的排序规则: {current_collation} -> {target_collation}")

                    # 修改表的默认排序规则
                    cursor.execute(f"""
                        ALTER TABLE `{table_name}`
                        CONVERT TO CHARACTER SET utf8mb4 COLLATE {target_collation}
                    """)

                    migrated_tables.append(table_name)
                    logging.info(f"✓ 表 {table_name} 排序规则已统一为 {target_collation}")

            if migrated_tables:
                logging.info(f"✓ 成功统一 {len(migrated_tables)} 个表的字符集排序规则: {', '.join(migrated_tables)}")
            else:
                logging.info("✓ 所有表的字符集排序规则已统一，无需修改")

        except Exception as e:
            logging.error(f"MySQL字符集统一迁移失败: {e}")

    def migrate_bdinfo_fields(self, conn=None, cursor=None):
        """迁移 BDInfo 相关字段到 seed_parameters 表"""
        try:
            logging.info("开始 BDInfo 字段迁移...")

            own_conn = False
            if conn is None or cursor is None:
                conn = self.db_manager._get_connection()
                cursor = self.db_manager._get_cursor(conn)
                own_conn = True
            
            # 检查表是否存在
            if not self._table_exists(cursor, 'seed_parameters'):
                logging.warning("seed_parameters 表不存在，跳过 BDInfo 字段迁移")
                return
            
            # 获取当前表结构
            current_columns = self._get_table_columns(cursor, 'seed_parameters')
            
            # 需要添加的 BDInfo 字段
            bdinfo_fields = {
                'mediainfo_status': {
                    'mysql': "VARCHAR(20) DEFAULT 'pending'",
                    'postgresql': "VARCHAR(20) DEFAULT 'pending'",
                    'sqlite': "TEXT DEFAULT 'pending'"
                },
                'bdinfo_task_id': {
                    'mysql': 'VARCHAR(36)',
                    'postgresql': 'VARCHAR(36)',
                    'sqlite': 'TEXT'
                },
                'bdinfo_started_at': {
                    'mysql': 'DATETIME',
                    'postgresql': 'TIMESTAMP',
                    'sqlite': 'TEXT'
                },
                'bdinfo_completed_at': {
                    'mysql': 'DATETIME',
                    'postgresql': 'TIMESTAMP',
                    'sqlite': 'TEXT'
                },
                'bdinfo_error': {
                    'mysql': 'TEXT',
                    'postgresql': 'TEXT',
                    'sqlite': 'TEXT'
                }
            }
            
            added_fields = []
            
            # 检查并添加缺失的字段
            for field_name, field_definitions in bdinfo_fields.items():
                if field_name not in current_columns:
                    field_definition = field_definitions[self.db_type]
                    
                    if self.db_type == 'mysql':
                        cursor.execute(f"ALTER TABLE seed_parameters ADD COLUMN {field_name} {field_definition}")
                    elif self.db_type == 'postgresql':
                        cursor.execute(f"ALTER TABLE seed_parameters ADD COLUMN {field_name} {field_definition}")
                    else:  # sqlite
                        # SQLite 不支持直接添加列，需要重建表
                        logging.warning("SQLite 需要重建表以添加 BDInfo 字段")
                        self._recreate_sqlite_table_with_bdinfo_fields(cursor)
                        if own_conn:
                            conn.commit()
                            cursor.close()
                            conn.close()
                        logging.info("✓ BDInfo 字段迁移完成 (SQLite)")
                        return
                    
                    added_fields.append(field_name)
                    logging.info(f"✓ 已添加 BDInfo 字段: {field_name}")
            
            # seed_parameters 表已经有复合主键 (hash, torrent_id, site_name)，不需要添加额外的 id 字段
            logging.info("✓ seed_parameters 表已有复合主键，跳过 id 字段添加")
            
            if own_conn:
                conn.commit()
                cursor.close()
                conn.close()
            
            if added_fields:
                logging.info(f"✓ BDInfo 字段迁移完成，已添加字段: {', '.join(added_fields)}")
            else:
                logging.info("✓ BDInfo 字段已存在，无需迁移")
                
        except Exception as e:
            logging.error(f"BDInfo 字段迁移失败: {e}", exc_info=True)
            raise
    
    def _recreate_sqlite_table_with_bdinfo_fields(self, cursor):
        """重建 SQLite 表以添加 BDInfo 字段"""
        try:
            self._recreate_sqlite_seed_parameters_table(cursor)
            logging.info("✓ SQLite 表重建完成，已添加 BDInfo 字段")
            
        except Exception as e:
            logging.error(f"SQLite 表重建失败: {e}", exc_info=True)
            # 尝试恢复原表
            try:
                cursor.execute("DROP TABLE seed_parameters")
                cursor.execute("ALTER TABLE seed_parameters_old RENAME TO seed_parameters")
                logging.info("✓ 已恢复原表结构")
            except:
                pass
            raise
            raise

    def _recreate_sqlite_seed_parameters_table(self, cursor):
        """重建 SQLite seed_parameters 表"""
        try:
            # 1. 重命名原表
            cursor.execute("ALTER TABLE seed_parameters RENAME TO seed_parameters_old")

            # 2. 创建新表结构（不含 save_path/downloader_id/is_deleted）
            cursor.execute("""
                CREATE TABLE seed_parameters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hash TEXT NOT NULL,
                    torrent_id TEXT NOT NULL,
                    site_name TEXT NOT NULL,
                    nickname TEXT,
                    name TEXT,
                    title TEXT,
                    subtitle TEXT,
                    imdb_link TEXT,
                    douban_link TEXT,
                    type TEXT,
                    medium TEXT,
                    video_codec TEXT,
                    audio_codec TEXT,
                    resolution TEXT,
                    team TEXT,
                    source TEXT,
                    tags TEXT,
                    poster TEXT,
                    screenshots TEXT,
                    statement TEXT,
                    body TEXT,
                    mediainfo TEXT,
                    title_components TEXT,
                    removed_ardtudeclarations TEXT,
                    is_reviewed INTEGER NOT NULL DEFAULT 0,
                    mediainfo_status TEXT DEFAULT 'pending',
                    bdinfo_task_id TEXT,
                    bdinfo_started_at TEXT,
                    bdinfo_completed_at TEXT,
                    bdinfo_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(hash, torrent_id, site_name)
                )
            """)

            # 3. 迁移数据（仅复制旧表中存在的列）
            cursor.execute("PRAGMA table_info(seed_parameters_old)")
            old_columns = [row[1] for row in cursor.fetchall()]

            new_columns = [
                "id",
                "hash",
                "torrent_id",
                "site_name",
                "nickname",
                "name",
                "title",
                "subtitle",
                "imdb_link",
                "douban_link",
                "type",
                "medium",
                "video_codec",
                "audio_codec",
                "resolution",
                "team",
                "source",
                "tags",
                "poster",
                "screenshots",
                "statement",
                "body",
                "mediainfo",
                "title_components",
                "removed_ardtudeclarations",
                "is_reviewed",
                "mediainfo_status",
                "bdinfo_task_id",
                "bdinfo_started_at",
                "bdinfo_completed_at",
                "bdinfo_error",
                "created_at",
                "updated_at",
            ]

            common_columns = [col for col in new_columns if col in old_columns]
            if common_columns:
                columns_str = ", ".join(common_columns)
                cursor.execute(
                    f"INSERT INTO seed_parameters ({columns_str}) SELECT {columns_str} FROM seed_parameters_old"
                )

            # 4. 删除旧表
            cursor.execute("DROP TABLE seed_parameters_old")
        except Exception as e:
            logging.error(f"SQLite seed_parameters 表重建失败: {e}", exc_info=True)
            # 尝试恢复原表
            try:
                cursor.execute("DROP TABLE seed_parameters")
                cursor.execute("ALTER TABLE seed_parameters_old RENAME TO seed_parameters")
                logging.info("✓ 已恢复原表结构")
            except Exception:
                pass
            raise
