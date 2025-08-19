# config.py

import os
import json
import logging
import sys
from dotenv import load_dotenv

# 从 .env 文件加载环境变量，主要用于本地开发
load_dotenv()

# SITES_DATA_FILE 仍然是必需的，用于初始化站点数据
DATA_DIR = '.'
SITES_DATA_FILE = os.path.join(DATA_DIR, 'sites_data.json')



def load_config():
    """
    从环境变量动态构建配置字典。
    不再读取 config.json 文件。
    """
    logging.debug("从环境变量加载配置。")

    # --- qBittorrent 配置 ---
    qb_enabled = os.getenv('QB_ENABLED', 'false').lower() in ('true', '1', 't')
    qb_config = {
        "enabled": qb_enabled,
        "host": os.getenv('QB_HOST', ''),
        "username": os.getenv('QB_USERNAME', ''),
        "password": os.getenv('QB_PASSWORD', '')
    }

    # --- Transmission 配置 ---
    tr_enabled = os.getenv('TR_ENABLED', 'false').lower() in ('true', '1', 't')
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


def get_db_config():
    """
    根据环境变量 DB_TYPE 显式选择数据库。
    - DB_TYPE=mysql: 必须提供所有 MYSQL_* 环境变量。
    - DB_TYPE=sqlite (或未设置): 使用 SQLite。
    """
    # 1. 读取数据库选择，默认为 'sqlite'，并转为小写
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

        # 2. 如果选择了 mysql，则所有 MYSQL_* 变量都必须存在
        if not all(mysql_config.values()):
            logging.error("关键错误: DB_TYPE 设置为 'mysql'，但一个或多个 MYSQL_* 环境变量缺失！")
            logging.error(
                "请提供: MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE, MYSQL_PORT"
            )
            sys.exit(1)  # 严重配置错误，退出程序

        # 3. 验证端口号
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
