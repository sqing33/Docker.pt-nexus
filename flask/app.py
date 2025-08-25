# app.py

import logging
import os
from flask import Flask, send_from_directory
from flask_cors import CORS

from config import get_db_config, config_manager
from database import DatabaseManager, reconcile_historical_data
from services import start_data_tracker
from routes import api_bp, initialize_routes

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - [PID:%(process)d] - %(levelname)s - %(message)s"
)


def create_app():
    """
    创建并配置 Flask 应用实例。
    这个函数同时设置了 API 路由和前端静态文件的托管。
    """
    app = Flask(__name__, static_folder="/app/dist")

    CORS(app, resources={r"/api/*": {"origins": "*"}})

    db_config = get_db_config()
    db_manager = DatabaseManager(db_config)
    db_manager.init_db()

    # 传递加载好的配置
    reconcile_historical_data(db_manager, config_manager.get())

    # 将依赖注入到路由和后台服务
    initialize_routes(db_manager, config_manager)
    app.register_blueprint(api_bp)

    start_data_tracker(db_manager, config_manager)

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_vue_app(path):

        if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
            return send_from_directory(app.static_folder, path)
        else:
            return send_from_directory(app.static_folder, "index.html")

    logging.info("应用设置完成，准备好接收请求。")
    return app


if __name__ == "__main__":
    flask_app = create_app()

    port = int(os.getenv("PORT", 15272))

    logging.info(f"以开发模式启动 Flask 服务器，监听端口 {port}...")

    flask_app.run(host="0.0.0.0", port=port, debug=False)
