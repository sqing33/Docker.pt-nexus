# run.py

import os
import logging
from flask import Flask, send_from_directory
from flask_cors import CORS

# 从项目根目录导入核心模块
from config import get_db_config, config_manager
from database import DatabaseManager, reconcile_historical_data
from core.services import start_data_tracker, stop_data_tracker

# --- 日志基础配置 ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [PID:%(process)d] - %(levelname)s - %(message)s")


def create_app():
    """
    应用工厂函数：创建并配置 Flask 应用实例。
    """
    app = Flask(__name__, static_folder="/app/dist")

    # --- 配置 CORS 跨域支持 ---
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # --- 步骤 1: 初始化核心依赖 (数据库和配置) ---
    logging.info("正在初始化数据库和配置...")
    db_config = get_db_config()
    db_manager = DatabaseManager(db_config)
    db_manager.init_db()  # 确保数据库和表结构存在

    # --- 步骤 2: 与下载器同步，建立统计基线 ---
    # 这个函数现在从 database.py 导入
    reconcile_historical_data(db_manager, config_manager.get())

    # --- 步骤 3: 导入并注册所有 API 蓝图 ---
    logging.info("正在注册 API 路由...")
    from api.routes_management import management_bp
    from api.routes_stats import stats_bp
    from api.routes_torrents import torrents_bp
    from api.routes_migrate import migrate_bp

    # 将核心服务实例注入到每个蓝图中，以便路由函数可以访问
    # 这是一个关键步骤，避免了使用全局变量
    management_bp.db_manager = db_manager
    management_bp.config_manager = config_manager
    stats_bp.db_manager = db_manager
    stats_bp.config_manager = config_manager
    torrents_bp.db_manager = db_manager
    torrents_bp.config_manager = config_manager
    migrate_bp.db_manager = db_manager
    migrate_bp.config_manager = config_manager  # 迁移模块也可能需要配置信息

    # 将蓝图注册到 Flask 应用实例上
    # 在每个蓝图文件中已经定义了 url_prefix="/api"
    app.register_blueprint(management_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(torrents_bp)
    app.register_blueprint(migrate_bp)

    # --- 步骤 4: 启动后台数据追踪服务 ---
    logging.info("正在启动后台数据追踪服务...")
    start_data_tracker(db_manager, config_manager)

    # --- 步骤 5: 配置前端静态文件服务 ---
    # 这个路由处理所有非 API 请求，将其指向前端应用
    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_vue_app(path):
        # 如果请求的路径是前端静态资源文件，则直接返回
        if path != "" and os.path.exists(os.path.join(app.static_folder,
                                                      path)):
            return send_from_directory(app.static_folder, path)
        # 否则，返回前端应用的入口 index.html，由 Vue Router 处理路由
        else:
            return send_from_directory(app.static_folder, "index.html")

    logging.info("应用设置完成，准备好接收请求。")
    return app


# --- 程序主入口 ---
if __name__ == "__main__":
    # 通过应用工厂创建 Flask 应用
    flask_app = create_app()

    # 从环境变量获取端口，如果未设置则使用默认值 15272
    port = int(os.getenv("PORT", 15272))

    logging.info(f"以开发模式启动 Flask 服务器，监听端口 http://0.0.0.0:{port} ...")

    # 运行 Flask 应用
    # debug=False 是生产环境推荐的设置
    flask_app.run(host="0.0.0.0", port=port, debug=True)
