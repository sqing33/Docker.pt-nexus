# config.py

import os
import json
import logging
import sys
from dotenv import load_dotenv

load_dotenv()

# --- MODIFICATION START ---
# 为需要持久化的数据（如配置和数据库）定义一个专门的目录
DATA_DIR = 'data'
# 确保这个持久化数据目录存在
os.makedirs(DATA_DIR, exist_ok=True)

# config.json 和 SQLite 数据库将位于 'data/' 目录中
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')

# sites_data.json 将保留在应用根目录（与 app.py 同级），不放入 data 目录
SITES_DATA_FILE = 'sites_data.json'
# --- MODIFICATION END ---


class ConfigManager:

    def __init__(self):
        self._config = {}
        self.load()

    def _get_default_config(self):
        """返回一个包含空下载器列表的默认配置结构。"""
        return {"downloaders": []}

    def load(self):
        """
        仅从 config.json 加载配置。
        如果文件不存在，则创建一个包含空下载器列表的默认配置文件。
        """
        if os.path.exists(CONFIG_FILE):
            logging.info(f"从 {CONFIG_FILE} 加载配置。")
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    self._config = json.load(f)
                    # 兼容性检查：如果还是旧格式，则转换
                    if 'qbittorrent' in self._config or 'transmission' in self._config:
                        logging.warning("检测到旧版配置文件格式，正在转换为新版格式...")
                        self._config = self._convert_legacy_config(
                            self._config)
                        self.save(self._config)

            except (json.JSONDecodeError, IOError) as e:
                logging.error(f"无法读取或解析 {CONFIG_FILE}: {e}。将加载一个安全的默认配置。")
                self._config = self._get_default_config()
        else:
            logging.info(f"未找到 {CONFIG_FILE}，将创建一个新的默认配置文件。")
            default_config = self._get_default_config()
            self.save(default_config)  # 保存到磁盘并更新缓存

    def _convert_legacy_config(self, legacy_config):
        """将旧的配置文件格式转换为新的基于列表的格式。"""
        import uuid
        new_downloaders = []
        if legacy_config.get('qbittorrent', {}).get('host'):
            qb_conf = legacy_config['qbittorrent']
            qb_conf.update({
                "id": str(uuid.uuid4()),
                "name": "qBittorrent",
                "type": "qbittorrent"
            })
            new_downloaders.append(qb_conf)

        if legacy_config.get('transmission', {}).get('host'):
            tr_conf = legacy_config['transmission']
            tr_conf.update({
                "id": str(uuid.uuid4()),
                "name": "Transmission",
                "type": "transmission"
            })
            new_downloaders.append(tr_conf)

        return {"downloaders": new_downloaders}

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
        # SQLite 数据库文件路径也指向 data 目录
        db_path = os.path.join(DATA_DIR, 'pt_stats.db')
        return {'db_type': 'sqlite', 'path': db_path}
    else:
        logging.warning(f"无效的 DB_TYPE 值: '{db_choice}'。将回退到使用 SQLite。")
        # SQLite 数据库文件路径也指向 data 目录
        db_path = os.path.join(DATA_DIR, 'pt_stats.db')
        return {'db_type': 'sqlite', 'path': db_path}


# 创建一个全局实例供整个应用使用
config_manager = ConfigManager()
