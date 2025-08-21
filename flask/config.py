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

    def _load_config_from_env(self):
        """从环境变量构建配置字典（作为备用方案）。"""
        logging.debug("从环境变量加载配置。")
        qb_enabled = os.getenv('QB_ENABLED',
                               'false').lower() in ('true', '1', 't')
        qb_config = {
            "enabled": qb_enabled,
            "host": os.getenv('QB_HOST', ''),
            "username": os.getenv('QB_USERNAME', ''),
            "password": os.getenv('QB_PASSWORD', '')
        }
        tr_enabled = os.getenv('TR_ENABLED',
                               'false').lower() in ('true', '1', 't')
        tr_port = 9091
        try:
            tr_port = int(os.getenv('TR_PORT', '9091'))
        except (ValueError, TypeError):
            logging.warning(
                f"无效的 TR_PORT 值 '{os.getenv('TR_PORT')}'。正在使用默认端口 9091。")
        tr_config = {
            "enabled": tr_enabled,
            "host": os.getenv('TR_HOST', ''),
            "port": tr_port,
            "username": os.getenv('TR_USERNAME', ''),
            "password": os.getenv('TR_PASSWORD', '')
        }
        return {"qbittorrent": qb_config, "transmission": tr_config}

    def load(self):
        """优先从 config.json 加载配置，如果文件不存在，则从环境变量加载。"""
        if os.path.exists(CONFIG_FILE):
            logging.info(f"从 {CONFIG_FILE} 加载配置。")
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    self._config = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logging.error(f"无法读取或解析 {CONFIG_FILE}: {e}。将回退到环境变量。")
                self._config = self._load_config_from_env()
        else:
            logging.info("未找到 config.json，将从环境变量加载配置。")
            self._config = self._load_config_from_env()

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
    """根据环境变量 DB_TYPE 显式选择数据库。"""
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
