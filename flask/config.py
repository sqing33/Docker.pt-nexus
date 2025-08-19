# config.py

import os
import json
import logging
from dotenv import load_dotenv

# Load environment variables from a .env file
load_dotenv()

DATA_DIR = '.'
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')


def save_config(config_data):
    """Saves the configuration data to the config.json file."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, indent=4, ensure_ascii=False)


def initialize_app_files():
    """If the config file doesn't exist, create a default one."""
    if not os.path.exists(CONFIG_FILE):
        logging.warning(
            f"Config file not found. Creating a default one at {CONFIG_FILE}")
        save_config({
            "qbittorrent": {
                "enabled": False,
                "host": "192.1168.1.100:8080",
                "username": "",
                "password": ""
            },
            "transmission": {
                "enabled": False,
                "host": "192.168.1.100",
                "port": 9091,
                "username": "",
                "password": ""
            },
            "ui_settings": {
                "active_path_filters": [],
                "page_size": 50,
                "torrent_update_interval_seconds": 3600
            }
        })


def load_config():
    """Loads the JSON configuration file."""
    if not os.path.exists(CONFIG_FILE):
        initialize_app_files()
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        logging.error(
            f"Failed to load or create config file due to {e}. Using default empty config."
        )
        return {"qbittorrent": {}, "transmission": {}, "ui_settings": {}}


def get_db_config():
    """Builds and returns the database configuration from environment variables."""
    mysql_config = {
        'host': os.getenv('MYSQL_HOST'),
        'user': os.getenv('MYSQL_USER'),
        'password': os.getenv('MYSQL_PASSWORD'),
        'database': os.getenv('MYSQL_DATABASE'),
        'port': int(os.getenv('MYSQL_PORT', 3306))
    }

    if not all([
            mysql_config['host'], mysql_config['user'],
            mysql_config['password'], mysql_config['database']
    ]):
        logging.error(
            "Critical MySQL environment variables (HOST, USER, PASSWORD, DATABASE) are not set! Check your .env file or environment variables."
        )
        exit(1)

    # This application is configured to exclusively use MySQL.
    return {'db_type': 'mysql', 'mysql': mysql_config}
