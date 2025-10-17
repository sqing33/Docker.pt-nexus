"""
下载器ID迁移脚本
将基于UUID的ID迁移到基于IP的ID
"""
import logging
from datetime import datetime
from utils.downloader_id_helper import generate_migration_mapping


def create_migration_table(db_manager):
    """创建ID迁移映射表"""
    conn = db_manager._get_connection()
    cursor = db_manager._get_cursor(conn)
    
    try:
        if db_manager.db_type == "postgresql":
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS downloader_id_migration (
                    old_id VARCHAR(36) NOT NULL PRIMARY KEY,
                    new_id VARCHAR(16) NOT NULL,
                    host VARCHAR(255) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    migrated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        elif db_manager.db_type == "mysql":
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS downloader_id_migration (
                    old_id VARCHAR(36) NOT NULL PRIMARY KEY,
                    new_id VARCHAR(16) NOT NULL,
                    host VARCHAR(255) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    migrated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        else:  # SQLite
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS downloader_id_migration (
                    old_id TEXT PRIMARY KEY,
                    new_id TEXT NOT NULL,
                    host TEXT NOT NULL,
                    name TEXT NOT NULL,
                    migrated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        
        conn.commit()
        logging.info("ID迁移映射表创建成功")
        return True
    except Exception as e:
        logging.error(f"创建ID迁移映射表失败: {e}", exc_info=True)
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()


def backup_tables(db_manager):
    """备份关键数据表"""
    conn = db_manager._get_connection()
    cursor = db_manager._get_cursor(conn)
    backup_suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    tables_to_backup = [
        "traffic_stats",
        "torrents",
        "torrent_upload_stats",
        "seed_parameters"
    ]
    
    try:
        for table in tables_to_backup:
            backup_table = f"{table}_backup_{backup_suffix}"
            
            if db_manager.db_type == "postgresql":
                cursor.execute(f"CREATE TABLE {backup_table} AS SELECT * FROM {table}")
            elif db_manager.db_type == "mysql":
                cursor.execute(f"CREATE TABLE {backup_table} AS SELECT * FROM {table}")
            else:  # SQLite
                cursor.execute(f"CREATE TABLE {backup_table} AS SELECT * FROM {table}")
            
            logging.info(f"表 {table} 备份为 {backup_table}")
        
        conn.commit()
        logging.info("所有关键表备份完成")
        return True
    except Exception as e:
        logging.error(f"备份表失败: {e}", exc_info=True)
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()


def save_migration_mapping(db_manager, migration_mapping):
    """保存迁移映射到数据库"""
    if not migration_mapping:
        logging.info("没有需要迁移的下载器ID")
        return True
    
    conn = db_manager._get_connection()
    cursor = db_manager._get_cursor(conn)
    
    try:
        for mapping in migration_mapping:
            if db_manager.db_type == "postgresql":
                cursor.execute("""
                    INSERT INTO downloader_id_migration (old_id, new_id, host, name)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (old_id) DO UPDATE SET
                        new_id = EXCLUDED.new_id,
                        host = EXCLUDED.host,
                        name = EXCLUDED.name,
                        migrated_at = CURRENT_TIMESTAMP
                """, (mapping["old_id"], mapping["new_id"], mapping["host"], mapping["name"]))
            elif db_manager.db_type == "mysql":
                cursor.execute("""
                    INSERT INTO downloader_id_migration (old_id, new_id, host, name)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        new_id = VALUES(new_id),
                        host = VALUES(host),
                        name = VALUES(name),
                        migrated_at = CURRENT_TIMESTAMP
                """, (mapping["old_id"], mapping["new_id"], mapping["host"], mapping["name"]))
            else:  # SQLite
                cursor.execute("""
                    INSERT OR REPLACE INTO downloader_id_migration (old_id, new_id, host, name)
                    VALUES (?, ?, ?, ?)
                """, (mapping["old_id"], mapping["new_id"], mapping["host"], mapping["name"]))
        
        conn.commit()
        logging.info(f"保存了 {len(migration_mapping)} 条迁移映射")
        return True
    except Exception as e:
        logging.error(f"保存迁移映射失败: {e}", exc_info=True)
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()


def migrate_table_ids(db_manager, table_name, id_column):
    """迁移指定表中的下载器ID"""
    conn = db_manager._get_connection()
    cursor = db_manager._get_cursor(conn)
    
    try:
        # 获取所有迁移映射
        cursor.execute("SELECT old_id, new_id FROM downloader_id_migration")
        mappings = {row["old_id"]: row["new_id"] for row in cursor.fetchall()}
        
        if not mappings:
            logging.info(f"没有迁移映射，跳过表 {table_name}")
            return True
        
        # 使用临时列方法避免主键冲突
        # 1. 检查是否有复合主键或唯一约束涉及该列
        temp_column = f"__{id_column}_temp__"
        
        try:
            # 添加临时列
            if db_manager.db_type == "postgresql":
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {temp_column} VARCHAR(36)")
            elif db_manager.db_type == "mysql":
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {temp_column} VARCHAR(36)")
            else:  # SQLite
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {temp_column} TEXT")
            
            # 将新ID值复制到临时列（仅对需要迁移的记录）
            updated_count = 0
            for old_id, new_id in mappings.items():
                if db_manager.db_type == "postgresql":
                    cursor.execute(
                        f"UPDATE {table_name} SET {temp_column} = %s WHERE {id_column} = %s",
                        (new_id, old_id)
                    )
                elif db_manager.db_type == "mysql":
                    cursor.execute(
                        f"UPDATE {table_name} SET {temp_column} = %s WHERE {id_column} = %s",
                        (new_id, old_id)
                    )
                else:  # SQLite
                    cursor.execute(
                        f"UPDATE {table_name} SET {temp_column} = ? WHERE {id_column} = ?",
                        (new_id, old_id)
                    )
                updated_count += cursor.rowcount
            
            # 更新原列的值
            if db_manager.db_type == "postgresql":
                cursor.execute(f"UPDATE {table_name} SET {id_column} = {temp_column} WHERE {temp_column} IS NOT NULL")
            elif db_manager.db_type == "mysql":
                cursor.execute(f"UPDATE {table_name} SET {id_column} = {temp_column} WHERE {temp_column} IS NOT NULL")
            else:  # SQLite
                cursor.execute(f"UPDATE {table_name} SET {id_column} = {temp_column} WHERE {temp_column} IS NOT NULL")
            
            # 删除临时列
            if db_manager.db_type == "postgresql":
                cursor.execute(f"ALTER TABLE {table_name} DROP COLUMN {temp_column}")
            elif db_manager.db_type == "mysql":
                cursor.execute(f"ALTER TABLE {table_name} DROP COLUMN {temp_column}")
            else:  # SQLite
                # SQLite不支持DROP COLUMN，跳过
                pass
            
            conn.commit()
            logging.info(f"表 {table_name} 中更新了 {updated_count} 条记录")
            return True
            
        except Exception as temp_e:
            # 如果临时列方法失败，尝试直接更新（适用于没有约束冲突的情况）
            logging.warning(f"临时列方法失败: {temp_e}，尝试直接更新...")
            conn.rollback()
            
            # 删除临时列（如果存在）
            try:
                if db_manager.db_type != "sqlite":
                    cursor.execute(f"ALTER TABLE {table_name} DROP COLUMN {temp_column}")
                    conn.commit()
            except:
                pass
            
            # 降级到直接更新
            updated_count = 0
            for old_id, new_id in mappings.items():
                try:
                    if db_manager.db_type == "postgresql":
                        cursor.execute(
                            f"UPDATE {table_name} SET {id_column} = %s WHERE {id_column} = %s",
                            (new_id, old_id)
                        )
                    elif db_manager.db_type == "mysql":
                        cursor.execute(
                            f"UPDATE {table_name} SET {id_column} = %s WHERE {id_column} = %s",
                            (new_id, old_id)
                        )
                    else:  # SQLite
                        cursor.execute(
                            f"UPDATE {table_name} SET {id_column} = ? WHERE {id_column} = ?",
                            (new_id, old_id)
                        )
                    updated_count += cursor.rowcount
                    conn.commit()
                except Exception as update_e:
                    # 单条更新失败，记录但继续
                    logging.warning(f"无法更新 {table_name} 中的ID {old_id}->{new_id}: {update_e}")
                    conn.rollback()
            
            logging.info(f"表 {table_name} 中更新了 {updated_count} 条记录（直接更新方式，可能有冲突被跳过）")
            return True
            
    except Exception as e:
        logging.error(f"迁移表 {table_name} 失败: {e}", exc_info=True)
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()


def migrate_batch_enhance_records(db_manager):
    """迁移 batch_enhance_records 表中JSON字段里的下载器ID"""
    conn = db_manager._get_connection()
    cursor = db_manager._get_cursor(conn)
    
    try:
        # 获取所有迁移映射
        cursor.execute("SELECT old_id, new_id FROM downloader_id_migration")
        mappings = {row["old_id"]: row["new_id"] for row in cursor.fetchall()}
        
        if not mappings:
            logging.info("没有迁移映射，跳过 batch_enhance_records")
            return True
        
        # 获取所有记录
        cursor.execute("SELECT id, downloader_add_result FROM batch_enhance_records")
        records = cursor.fetchall()
        
        updated_count = 0
        import json
        
        for record in records:
            record_id = record["id"]
            result_json = record["downloader_add_result"]
            
            if not result_json:
                continue
            
            try:
                result_data = json.loads(result_json)
                modified = False
                
                # 遍历JSON中的所有下载器ID并替换
                for old_id, new_id in mappings.items():
                    if old_id in result_data:
                        result_data[new_id] = result_data.pop(old_id)
                        modified = True
                
                if modified:
                    new_json = json.dumps(result_data, ensure_ascii=False)
                    
                    if db_manager.db_type == "postgresql":
                        cursor.execute(
                            "UPDATE batch_enhance_records SET downloader_add_result = %s WHERE id = %s",
                            (new_json, record_id)
                        )
                    elif db_manager.db_type == "mysql":
                        cursor.execute(
                            "UPDATE batch_enhance_records SET downloader_add_result = %s WHERE id = %s",
                            (new_json, record_id)
                        )
                    else:  # SQLite
                        cursor.execute(
                            "UPDATE batch_enhance_records SET downloader_add_result = ? WHERE id = ?",
                            (new_json, record_id)
                        )
                    
                    updated_count += 1
            except json.JSONDecodeError:
                logging.warning(f"记录 {record_id} 的JSON格式无效，跳过")
                continue
        
        conn.commit()
        logging.info(f"batch_enhance_records 表中更新了 {updated_count} 条记录")
        return True
    except Exception as e:
        logging.error(f"迁移 batch_enhance_records 失败: {e}", exc_info=True)
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()


def cleanup_backup_tables(db_manager, backup_suffix):
    """清理备份表"""
    conn = db_manager._get_connection()
    cursor = db_manager._get_cursor(conn)
    
    tables_to_cleanup = [
        f"traffic_stats_backup_{backup_suffix}",
        f"torrents_backup_{backup_suffix}",
        f"torrent_upload_stats_backup_{backup_suffix}",
        f"seed_parameters_backup_{backup_suffix}"
    ]
    
    try:
        for table in tables_to_cleanup:
            try:
                cursor.execute(f"DROP TABLE IF EXISTS {table}")
                logging.info(f"已删除备份表: {table}")
            except Exception as e:
                logging.warning(f"删除备份表 {table} 失败: {e}")
        
        conn.commit()
        logging.info("备份表清理完成")
        return True
    except Exception as e:
        logging.error(f"清理备份表失败: {e}", exc_info=True)
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()


def execute_migration(db_manager, config_manager, backup=True, auto_cleanup=True):
    """
    执行完整的ID迁移流程
    
    Args:
        db_manager: 数据库管理器
        config_manager: 配置管理器
        backup: 是否备份表（默认True）
        auto_cleanup: 迁移成功后是否自动删除备份表（默认True）
        
    Returns:
        dict: 包含迁移结果的字典
    """
    logging.info("开始执行下载器ID迁移...")
    backup_suffix = None
    
    # 1. 创建迁移表
    if not create_migration_table(db_manager):
        return {"success": False, "message": "创建迁移表失败"}
    
    # 2. 生成迁移映射
    config = config_manager.get()
    migration_mapping = generate_migration_mapping(config)
    
    if not migration_mapping:
        logging.info("所有下载器ID已是基于IP的格式，无需迁移")
        return {"success": True, "message": "无需迁移", "migrated_count": 0}
    
    logging.info(f"发现 {len(migration_mapping)} 个需要迁移的下载器")
    
    # 3. 备份表
    if backup:
        backup_suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
        # 临时修改backup_tables以返回suffix
        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        
        tables_to_backup = [
            "traffic_stats",
            "torrents",
            "torrent_upload_stats",
            "seed_parameters"
        ]
        
        try:
            for table in tables_to_backup:
                backup_table = f"{table}_backup_{backup_suffix}"
                
                if db_manager.db_type == "postgresql":
                    cursor.execute(f"CREATE TABLE {backup_table} AS SELECT * FROM {table}")
                elif db_manager.db_type == "mysql":
                    cursor.execute(f"CREATE TABLE {backup_table} AS SELECT * FROM {table}")
                else:  # SQLite
                    cursor.execute(f"CREATE TABLE {backup_table} AS SELECT * FROM {table}")
                
                logging.info(f"表 {table} 备份为 {backup_table}")
            
            conn.commit()
            logging.info("所有关键表备份完成")
        except Exception as e:
            logging.error(f"备份表失败: {e}", exc_info=True)
            conn.rollback()
            cursor.close()
            conn.close()
            return {"success": False, "message": "备份表失败"}
        finally:
            cursor.close()
            conn.close()
    
    # 4. 保存迁移映射
    if not save_migration_mapping(db_manager, migration_mapping):
        return {"success": False, "message": "保存迁移映射失败"}
    
    # 5. 迁移各个表
    tables_to_migrate = [
        ("traffic_stats", "downloader_id"),
        ("torrents", "downloader_id"),
        ("torrent_upload_stats", "downloader_id"),
        ("seed_parameters", "downloader_id")
    ]
    
    for table_name, id_column in tables_to_migrate:
        if not migrate_table_ids(db_manager, table_name, id_column):
            logging.error(f"迁移失败！备份表已保留: *_backup_{backup_suffix}")
            return {"success": False, "message": f"迁移表 {table_name} 失败"}
    
    # 6. 迁移 batch_enhance_records 中的JSON数据
    if not migrate_batch_enhance_records(db_manager):
        logging.error(f"迁移失败！备份表已保留: *_backup_{backup_suffix}")
        return {"success": False, "message": "迁移 batch_enhance_records 失败"}
    
    # 7. 更新配置文件中的下载器ID
    for mapping in migration_mapping:
        for downloader in config["downloaders"]:
            if downloader["id"] == mapping["old_id"]:
                downloader["id"] = mapping["new_id"]
                logging.info(f"更新配置: {downloader['name']} ID从 {mapping['old_id']} 改为 {mapping['new_id']}")
    
    if not config_manager.save(config):
        logging.error(f"保存配置失败！备份表已保留: *_backup_{backup_suffix}")
        return {"success": False, "message": "保存配置失败"}
    
    # 8. 迁移成功，根据参数决定是否清理备份表
    if backup and backup_suffix and auto_cleanup:
        logging.info("迁移成功，正在清理备份表...")
        cleanup_backup_tables(db_manager, backup_suffix)
    elif backup and backup_suffix:
        logging.info(f"迁移成功！备份表已保留: *_backup_{backup_suffix}")
    
    logging.info("下载器ID迁移完成！")
    return {
        "success": True,
        "message": "迁移成功完成",
        "migrated_count": len(migration_mapping),
        "mappings": migration_mapping,
        "backup_suffix": backup_suffix if backup else None
    }
