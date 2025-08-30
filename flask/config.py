# config.py

import os
import json
import logging
import sys
import copy
from dotenv import load_dotenv

load_dotenv()

# 配置文件路径
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

TEMP_DIR = os.path.join(DATA_DIR, "tmp")
os.makedirs(TEMP_DIR, exist_ok=True)

CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
SITES_DATA_FILE = "sites_data.json"


class ConfigManager:
    """管理应用的配置信息，处理加载和保存操作。"""

    def __init__(self):
        self._config = {}
        self.load()

    def _get_default_config(self):
        """返回包含默认值的配置结构。"""
        return {
            "downloaders": [],
            "realtime_speed_enabled": True,
            "cookiecloud": {
                "url": "",
                "key": "",
                "e2e_password": ""
            },
        }

    def load(self):
        """
        从 config.json 加载配置。
        如果文件不存在或损坏，则创建/加载一个安全的默认配置。
        同时确保旧配置文件能平滑过渡，自动添加新的配置项。
        """
        if os.path.exists(CONFIG_FILE):
            logging.info(f"从 {CONFIG_FILE} 加载配置。")
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    self._config = json.load(f)

                default_conf = self._get_default_config()
                if "realtime_speed_enabled" not in self._config:
                    self._config["realtime_speed_enabled"] = default_conf[
                        "realtime_speed_enabled"]
                if "cookiecloud" not in self._config:
                    self._config["cookiecloud"] = default_conf["cookiecloud"]
                elif "e2e_password" not in self._config.get("cookiecloud", {}):
                    self._config["cookiecloud"]["e2e_password"] = ""

            except (json.JSONDecodeError, IOError) as e:
                logging.error(f"无法读取或解析 {CONFIG_FILE}: {e}。将加载一个安全的默认配置。")
                self._config = self._get_default_config()
        else:
            logging.info(f"未找到 {CONFIG_FILE}，将创建一个新的默认配置文件。")
            self.save(self._get_default_config())

    def get(self):
        """返回当前缓存的配置。"""
        return self._config

    def save(self, config_data):
        """将配置字典保存到 config.json 文件并更新缓存。"""
        logging.info(f"正在将新配置保存到 {CONFIG_FILE}。")
        try:
            config_to_save = copy.deepcopy(config_data)
            if "cookiecloud" in config_to_save and "e2e_password" in config_to_save[
                    "cookiecloud"]:
                config_to_save["cookiecloud"]["e2e_password"] = ""

            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config_to_save, f, ensure_ascii=False, indent=4)

            self._config = config_data
            return True
        except IOError as e:
            logging.error(f"无法写入配置到 {CONFIG_FILE}: {e}")
            return False


def get_db_config():
    """根据环境变量 DB_TYPE 显式选择数据库。"""
    db_choice = os.getenv("DB_TYPE", "sqlite").lower()

    if db_choice == "mysql":
        logging.info("数据库类型选择为 MySQL。正在检查相关环境变量...")
        mysql_config = {
            "host": os.getenv("MYSQL_HOST"),
            "user": os.getenv("MYSQL_USER"),
            "password": os.getenv("MYSQL_PASSWORD"),
            "database": os.getenv("MYSQL_DATABASE"),
            "port": os.getenv("MYSQL_PORT"),
        }
        if not all(mysql_config.values()):
            logging.error("关键错误: DB_TYPE='mysql', 但一个或多个 MYSQL_* 环境变量缺失！")
            sys.exit(1)
        try:
            mysql_config["port"] = int(mysql_config["port"])
        except (ValueError, TypeError):
            logging.error(
                f"关键错误: MYSQL_PORT ('{mysql_config['port']}') 不是一个有效的整数！")
            sys.exit(1)
        logging.info("MySQL 配置验证通过。")
        return {"db_type": "mysql", "mysql": mysql_config}

    elif db_choice == "sqlite":
        logging.info("数据库类型选择为 SQLite。")
        db_path = os.path.join(DATA_DIR, "pt_stats.db")
        return {"db_type": "sqlite", "path": db_path}

    else:
        logging.warning(f"无效的 DB_TYPE 值: '{db_choice}'。将回退到使用 SQLite。")
        db_path = os.path.join(DATA_DIR, "pt_stats.db")
        return {"db_type": "sqlite", "path": db_path}


config_manager = ConfigManager()
