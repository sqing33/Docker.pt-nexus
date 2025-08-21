# config.py

import os
import json
import logging
import sys
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = '.'
SITES_DATA_FILE = os.path.join(DATA_DIR, 'sites_data.json')
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')


class ConfigManager:

    def __init__(self):
        self._config = {}
        self.load()

    def _get_default_config(self):
        """返回一个包含两个下载器都已禁用的默认配置结构。"""
        return {
            "qbittorrent": {
                "enabled": False,
                "host": "",
                "username": "",
                "password": ""
            },
            "transmission": {
                "enabled": False,
                "host": "",
                "port": 9091,
                "username": "",
                "password": ""
            }
        }

    def load(self):
        """
        仅从 config.json 加载配置。
        如果文件不存在，则创建一个包含禁用客户端的默认配置文件。
        """
        if os.path.exists(CONFIG_FILE):
            logging.info(f"从 {CONFIG_FILE} 加载配置。")
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    self._config = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logging.error(f"无法读取或解析 {CONFIG_FILE}: {e}。将加载一个安全的默认配置。")
                self._config = self._get_default_config()
        else:
            logging.info(f"未找到 {CONFIG_FILE}，将创建一个新的默认配置文件。")
            default_config = self._get_default_config()
            self.save(default_config)  # 保存到磁盘并更新缓存

    def get(self):
        """返回缓存的配置。"""
        return self._config

    def save(self, config_data):
        """将配置字典保存到 config.json 文件并更新缓存。"""
        logging.info(f"正在将新配置保存到 {CONFIG_FILE}。")
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)
            self._config = config_data  # 更新内存中的缓存
            return True
        except IOError as e:
            logging.error(f"无法写入配置到 {CONFIG_FILE}: {e}")
            return False


def get_db_config():
    """根据环境变量 DB_TYPE 显式选择数据库。这部分保持不变。"""
    db_choice = os.getenv('DB_TYPE', 'sqlite').lower()
    if db_choice == 'mysql':
        logging.info("数据库类型选择为 MySQL。正在检查相关环境变量...")
        mysql_config = {
            'host': os.getenv('MYSQL_HOST'),
            'user': os.getenv('MYSQL_USER'),
            'password': os.getenv('MYSQL_PASSWORD'),
            'database': os.getenv('MYSQL_DATABASE'),
            'port': os.getenv('MYSQL_PORT')
        }
        if not all(mysql_config.values()):
            logging.error("关键错误: DB_TYPE 设置为 'mysql'，但一个或多个 MYSQL_* 环境变量缺失！")
            logging.error(
                "请提供: MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE, MYSQL_PORT"
            )
            sys.exit(1)
        try:
            mysql_config['port'] = int(mysql_config['port'])
        except (ValueError, TypeError):
            logging.error(
                f"关键错误: MYSQL_PORT ('{mysql_config['port']}') 不是一个有效的整数！")
            sys.exit(1)
        logging.info("MySQL 配置验证通过。")
        return {'db_type': 'mysql', 'mysql': mysql_config}
    elif db_choice == 'sqlite':
        logging.info("数据库类型选择为 SQLite。")
        return {'db_type': 'sqlite'}
    else:
        logging.warning(f"无效的 DB_TYPE 值: '{db_choice}'。将回退到使用 SQLite。")
        return {'db_type': 'sqlite'}


# 创建一个全局实例供整个应用使用
config_manager = ConfigManager()
