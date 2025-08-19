# app.py

import logging
import os
from flask import Flask, send_from_directory
from flask_cors import CORS

from config import initialize_app_files, get_db_config
from database import DatabaseManager, reconcile_historical_data
from services import start_data_tracker
from routes import api_bp, initialize_routes

# --- 全局日志配置 ---
# 设置日志级别和格式，方便在 Docker 日志中查看
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [PID:%(process)d] - %(levelname)s - %(message)s')


def create_app():
    """
    创建并配置 Flask 应用实例。
    这个函数同时设置了 API 路由和前端静态文件的托管。
    """

    # 将 'dist' 目录设置为静态文件目录。
    # 'dist' 目录应与此 app.py 文件位于同一层级或在 Dockerfile 中被正确放置。
    app = Flask(__name__, static_folder='/app/dist')

    # 为所有 /api/ 开头的路由启用 CORS (跨域资源共享)，
    # 这在本地开发时尤其重要，并为其他部署方式提供灵活性。
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # --- 应用初始化序列 ---
    # 1. 确保配置文件存在 (如果逻辑需要)
    initialize_app_files()

    # 2. 获取数据库配置并初始化数据库连接和表结构
    db_config = get_db_config()
    db_manager = DatabaseManager(db_config)
    db_manager.init_db()

    # 3. 同步历史数据和下载器状态 (此操作只应执行一次)
    reconcile_historical_data(db_manager)

    # 4. 初始化 API 路由并注册蓝图
    initialize_routes(db_manager)
    app.register_blueprint(api_bp)

    # 5. 启动后台数据采集线程
    start_data_tracker(db_manager)

    # --- 托管 Vue.js 单页应用 (SPA) 的关键路由 ---
    # 这个路由会捕获所有非 API 的请求
    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def serve_vue_app(path):
        """
        服务于前端静态文件。
        - 如果请求的路径是前端资源 (如 assets/index.css), 则直接返回该文件。
        - 否则，返回 index.html，让 Vue Router 来处理前端路由。
        """
        # 检查请求的路径是否指向一个在 'dist' 目录中实际存在的文件
        if path != "" and os.path.exists(os.path.join(app.static_folder,
                                                      path)):
            return send_from_directory(app.static_folder, path)
        else:
            # 对于所有其他路径 (包括根路径 '/' 或虚拟路由 '/torrents'),
            # 都返回前端应用的入口点 index.html。
            return send_from_directory(app.static_folder, 'index.html')

    logging.info("应用设置完成，准备好接收请求。")
    return app


# --- 程序主入口 ---
# 当直接通过 `python app.py` 运行时，此代码块将被执行。
if __name__ == '__main__':
    # 创建 Flask 应用实例
    flask_app = create_app()

    # 从环境变量中获取要监听的端口，如果未设置，则默认为 5272
    port = int(os.getenv("PORT", 5272))

    logging.info(f"以开发模式启动 Flask 服务器，监听端口 {port}...")

    # 运行 Flask 自带的开发服务器
    # host='0.0.0.0' 确保可以从容器外部访问
    # debug=False 在容器中是更稳定和安全的选择
    flask_app.run(host='0.0.0.0', port=port, debug=False)
