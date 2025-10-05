# config.py

import os
import json
import logging
import sys
import copy
from dotenv import load_dotenv

load_dotenv()

# 配置文件路径
DATA_DIR = "/app/Code/Dockerfile/Docker.pt-nexus/server/data"
SITES_DATA_FILE = "/app/Code/Dockerfile/Docker.pt-nexus/server/sites_data.json"

# DATA_DIR = "/app/data"
# SITES_DATA_FILE = "/app/sites_data.json"

os.makedirs(DATA_DIR, exist_ok=True)

TEMP_DIR = os.path.join(DATA_DIR, "tmp")
os.makedirs(TEMP_DIR, exist_ok=True)

CONFIG_FILE = os.path.join(DATA_DIR, "config.json")


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
            "network": {
                "proxy_url": ""
            },
            "auth": {
                "username": "admin",
                "password_hash": "",
                "must_change_password": True
            },
            "cookiecloud": {
                "url": "",
                "key": "",
                "e2e_password": ""
            },
            "cross_seed": {
                "image_hoster": "pixhost",
                # [新增] 为 SeedVault (agsvpic) 添加配置字段
                "seedvault_email": "",
                "seedvault_password": "",
                # [新增] 默认下载器设置
                "default_downloader": ""
            },
            # --- [新增] 下载器队列设置 ---
            "downloader_queue": {
                "enabled": True,
                "max_queue_size": 1000,
                "max_workers": 1,
                "max_retries": 3,
                "retry_delay_base": 2,  # 重试延迟基数（秒），指数退避
                "max_retry_delay": 60,  # 最大重试延迟（秒）
                "task_cleanup_hours": 24,  # 任务记录清理时间（小时）
                "queue_monitor_interval": 30  # 队列监控间隔（秒）
            },
            # --- [新增] 为前端 UI 添加默认设置 ---
            "ui_settings": {
                "torrents_view": {
                    "page_size": 50,
                    "sort_prop": "name",
                    "sort_order": "ascending",
                    "name_search": "",
                    "active_filters": {
                        "paths": [],
                        "states": [],
                        "siteExistence": "all",
                        "siteNames": [],
                        "downloaderIds": [],
                    }
                }
            },
            # --- [新增] IYUU Token 设置 ---
            "iyuu_token": "",
            # --- [新增] IYUU 功能设置 ---
            "iyuu_settings": {
                "query_interval_hours": 72,
                "auto_query_enabled": True,
                "tmp_dir": ""  # 默认为空，表示使用系统默认临时目录
            },
            # --- [新增] 源站点优先级设置 ---
            "source_priority": [],
            # --- [新增] 批量获取筛选条件设置 ---
            "batch_fetch_filters": {
                "paths": [],
                "states": [],
                "downloaderIds": []
            }
        }

    def load(self):
        """
        从 config.json 加载配置。
        如果文件不存在或损坏，则创建/加载一个安全的默认配置。
        同时确保旧配置文件能平滑过渡，自动添加新的配置项。
        """
        default_conf = self._get_default_config()

        if os.path.exists(CONFIG_FILE):
            logging.info(f"从 {CONFIG_FILE} 加载配置。")
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    self._config = json.load(f)

                # --- 确保旧配置平滑迁移 ---
                if "realtime_speed_enabled" not in self._config:
                    self._config["realtime_speed_enabled"] = default_conf[
                        "realtime_speed_enabled"]

                if "cookiecloud" not in self._config:
                    self._config["cookiecloud"] = default_conf["cookiecloud"]

                # [修改] 扩展转种设置的迁移逻辑
                if "cross_seed" not in self._config:
                    self._config["cross_seed"] = default_conf["cross_seed"]
                else:
                    # 如果已有 cross_seed，检查是否缺少新字段
                    if "seedvault_email" not in self._config["cross_seed"]:
                        self._config["cross_seed"]["seedvault_email"] = ""
                    if "seedvault_password" not in self._config["cross_seed"]:
                        self._config["cross_seed"]["seedvault_password"] = ""

                # --- [新增] 检查并添加 UI 设置的兼容性 ---
                if "ui_settings" not in self._config:
                    self._config["ui_settings"] = default_conf["ui_settings"]
                elif "torrents_view" not in self._config["ui_settings"]:
                    # 如果 ui_settings 已存在但缺少 torrents_view，也进行补充
                    self._config["ui_settings"][
                        "torrents_view"] = default_conf["ui_settings"][
                            "torrents_view"]

                # --- [新增] IYUU Token 配置兼容 ---
                if "iyuu_token" not in self._config:
                    self._config["iyuu_token"] = ""

                # --- [新增] IYUU 功能设置兼容 ---
                if "iyuu_settings" not in self._config:
                    self._config["iyuu_settings"] = {
                        "query_interval_hours": 72,
                        "auto_query_enabled": True,
                        "tmp_dir": ""  # 默认为空，表示使用系统默认临时目录
                    }
                else:
                    # 如果已有 iyuu_settings，检查是否缺少新字段
                    if "query_interval_hours" not in self._config[
                            "iyuu_settings"]:
                        self._config["iyuu_settings"][
                            "query_interval_hours"] = 72
                    if "auto_query_enabled" not in self._config[
                            "iyuu_settings"]:
                        self._config["iyuu_settings"][
                            "auto_query_enabled"] = True
                    if "tmp_dir" not in self._config["iyuu_settings"]:
                        self._config["iyuu_settings"]["tmp_dir"] = ""

                # --- [新增] 认证配置兼容 ---
                if "auth" not in self._config:
                    self._config["auth"] = default_conf["auth"]
                else:
                    if "username" not in self._config["auth"]:
                        self._config["auth"]["username"] = "admin"
                    if "password_hash" not in self._config["auth"]:
                        self._config["auth"]["password_hash"] = ""
                    if "must_change_password" not in self._config["auth"]:
                        self._config["auth"]["must_change_password"] = True

                # --- [新增] 源站点优先级配置兼容 ---
                if "source_priority" not in self._config:
                    self._config["source_priority"] = []

                # --- [新增] 批量获取筛选条件配置兼容 ---
                if "batch_fetch_filters" not in self._config:
                    self._config["batch_fetch_filters"] = {
                        "paths": [],
                        "states": [],
                        "downloaderIds": []
                    }

            except (json.JSONDecodeError, IOError) as e:
                logging.error(f"无法读取或解析 {CONFIG_FILE}: {e}。将加载一个安全的默认配置。")
                self._config = default_conf
        else:
            logging.info(f"未找到 {CONFIG_FILE}，将创建一个新的默认配置文件。")
            self._config = default_conf
            self.save(self._config)

    def get(self):
        """返回当前缓存的配置。"""
        return self._config

    def save(self, config_data):
        """将配置字典保存到 config.json 文件并更新缓存。"""
        logging.info(f"正在将新配置保存到 {CONFIG_FILE}。")
        try:
            # 深拷贝以避免意外修改内存中的配置
            config_to_save = copy.deepcopy(config_data)

            # 从内存中移除 CookieCloud 的端到端密码，避免写入文件
            if "cookiecloud" in config_to_save and "e2e_password" in config_to_save[
                    "cookiecloud"]:
                # 如果用户在UI中输入了密码，我们不希望它被保存
                if config_to_save["cookiecloud"]["e2e_password"]:
                    config_to_save["cookiecloud"]["e2e_password"] = ""

            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config_to_save, f, ensure_ascii=False, indent=4)

            self._config = config_data
            return True
        except IOError as e:
            logging.error(f"无法写入配置到 {CONFIG_FILE}: {e}")
            return False


# ... (文件其余部分 get_db_config 和 config_manager 实例保持不变) ...
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

    elif db_choice == "postgresql":
        logging.info("数据库类型选择为 PostgreSQL。正在检查相关环境变量...")
        postgresql_config = {
            "host": os.getenv("POSTGRES_HOST"),
            "user": os.getenv("POSTGRES_USER"),
            "password": os.getenv("POSTGRES_PASSWORD"),
            "database": os.getenv("POSTGRES_DATABASE"),
            "port": os.getenv("POSTGRES_PORT", 5432),
        }
        if not all(postgresql_config.values()):
            logging.error(
                "关键错误: DB_TYPE='postgresql', 但一个或多个 POSTGRES_* 环境变量缺失！")
            sys.exit(1)
        try:
            postgresql_config["port"] = int(postgresql_config["port"])
        except (ValueError, TypeError):
            logging.error(
                f"关键错误: POSTGRES_PORT ('{postgresql_config['port']}') 不是一个有效的整数！"
            )
            sys.exit(1)
        logging.info("PostgreSQL 配置验证通过。")
        return {"db_type": "postgresql", "postgresql": postgresql_config}

    elif db_choice == "sqlite":
        logging.info("数据库类型选择为 SQLite。")
        db_path = os.path.join(DATA_DIR, "pt_stats.db")
        return {"db_type": "sqlite", "path": db_path}

    else:
        logging.warning(f"无效的 DB_TYPE 值: '{db_choice}'。将回退到使用 SQLite。")
        db_path = os.path.join(DATA_DIR, "pt_stats.db")
        return {"db_type": "sqlite", "path": db_path}


config_manager = ConfigManager()
