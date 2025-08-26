# config.py

import os
import json
import logging
import sys
import copy  # [修正] 添加此行导入语句
from dotenv import load_dotenv

load_dotenv()

# 为需要持久化的数据（如配置和数据库）定义一个专门的目录
DATA_DIR = "data"
# 确保这个持久化数据目录存在
os.makedirs(DATA_DIR, exist_ok=True)

# config.json 和 SQLite 数据库将位于 'data/' 目录中
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

# sites_data.json 将保留在应用根目录（与 app.py 同级），不放入 data 目录
SITES_DATA_FILE = "sites_data.json"


class ConfigManager:

    def __init__(self):
        self._config = {}
        self.load()

    def _get_default_config(self):
        """[修改] 返回包含默认值的配置结构。"""
        return {
            "downloaders": [],
            "realtime_speed_enabled": True,
            "cookiecloud": {"url": "", "key": "", "e2e_password": ""},
        }

    def load(self):
        """
        [修改] 从 config.json 加载配置，并确保新配置项存在。
        """
        if os.path.exists(CONFIG_FILE):
            logging.info(f"从 {CONFIG_FILE} 加载配置。")
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    self._config = json.load(f)

                # [新增] 优雅地处理旧配置文件，为其添加新的默认配置项
                if "realtime_speed_enabled" not in self._config:
                    self._config["realtime_speed_enabled"] = True
                if "cookiecloud" not in self._config:
                    self._config["cookiecloud"] = {"url": "", "key": "", "e2e_password": ""}
                # [新增] 确保 e2e_password 字段存在于旧配置中
                elif "e2e_password" not in self._config.get("cookiecloud", {}):
                    self._config["cookiecloud"]["e2e_password"] = ""

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
            # [修改] 不保存端对端加密密码到 config.json
            config_to_save = copy.deepcopy(config_data)
            if "cookiecloud" in config_to_save and "e2e_password" in config_to_save["cookiecloud"]:
                config_to_save["cookiecloud"]["e2e_password"] = ""  # 清空密码，不保存

            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config_to_save, f, ensure_ascii=False, indent=4)

            self._config = config_data  # 内存中仍然保留密码
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
            logging.error("关键错误: DB_TYPE 设置为 'mysql'，但一个或多个 MYSQL_* 环境变量缺失！")
            logging.error(
                "请提供: MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE, MYSQL_PORT"
            )
            sys.exit(1)
        try:
            mysql_config["port"] = int(mysql_config["port"])
        except (ValueError, TypeError):
            logging.error(f"关键错误: MYSQL_PORT ('{mysql_config['port']}') 不是一个有效的整数！")
            sys.exit(1)
        logging.info("MySQL 配置验证通过。")
        return {"db_type": "mysql", "mysql": mysql_config}
    elif db_choice == "sqlite":
        logging.info("数据库类型选择为 SQLite。")
        # SQLite 数据库文件路径也指向 data 目录
        db_path = os.path.join(DATA_DIR, "pt_stats.db")
        return {"db_type": "sqlite", "path": db_path}
    else:
        logging.warning(f"无效的 DB_TYPE 值: '{db_choice}'。将回退到使用 SQLite。")
        # SQLite 数据库文件路径也指向 data 目录
        db_path = os.path.join(DATA_DIR, "pt_stats.db")
        return {"db_type": "sqlite", "path": db_path}


# 创建一个全局实例供整个应用使用
config_manager = ConfigManager()
