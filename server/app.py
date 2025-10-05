# run.py

import os
import logging
import jwt  # type: ignore
import atexit
import hmac
import hashlib
import time
from typing import cast
from flask import Flask, send_from_directory, request, jsonify
from flask_cors import CORS

# 从项目根目录导入核心模块
from config import get_db_config, config_manager
from database import DatabaseManager, reconcile_historical_data
from core.services import start_data_tracker, stop_data_tracker
from core.iyuu import start_iyuu_thread, stop_iyuu_thread

# --- 日志基础配置 ---
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - [PID:%(process)d] - %(levelname)s - %(message)s")
logging.info("=== Flask 应用日志系统已初始化 ===")


def create_app():
    """
    应用工厂函数：创建并配置 Flask 应用实例。
    """
    logging.info("Flask 应用正在创建中...")
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

    # 动态内部认证token验证函数
    def validate_internal_token(token):
        """验证动态生成的内部认证token，支持更大的时间窗口容错"""
        try:
            internal_secret = os.getenv("INTERNAL_SECRET", "pt-nexus-2024-secret-key")
            current_timestamp = int(time.time()) // 3600  # 当前小时

            # 扩大时间窗口：检查前后2小时的token（容错机制）
            # 这样可以处理服务器时间不同步的问题
            for time_offset in [-2, -1, 0, 1, 2]:
                timestamp = current_timestamp + time_offset
                expected_signature = hmac.new(
                    internal_secret.encode(),
                    f"pt-nexus-internal-{timestamp}".encode(),
                    hashlib.sha256
                ).hexdigest()[:16]

                if hmac.compare_digest(token, expected_signature):
                    # 记录验证成功的时间偏移，用于监控时钟同步问题
                    if time_offset != 0:
                        logging.warning(f"内部认证token验证成功，但存在时间偏移: {time_offset}小时")
                    return True

            # 如果所有时间窗口都验证失败，记录详细信息用于调试
            logging.error(f"内部认证token验证失败: token={token[:8]}..., current_hour={current_timestamp}")
            return False
        except Exception as e:
            logging.error(f"验证内部token时出错: {e}")
            return False

    # --- 步骤 3: 导入并注册所有 API 蓝图 ---
    logging.info("正在注册 API 路由...")
    from api.routes_management import management_bp
    from api.routes_stats import stats_bp
    from api.routes_torrents import torrents_bp
    from api.routes_migrate import migrate_bp
    from api.routes_auth import auth_bp
    from api.routes_sites import sites_bp
    from api.routes_cross_seed_data import cross_seed_data_bp
    from api.routes_config import bp_config
    from api.routes_local_query import local_query_bp

    # 将核心服务实例注入到每个蓝图中，以便路由函数可以访问
    # 使用 setattr 避免类型检查器报错
    setattr(management_bp, "db_manager", db_manager)
    setattr(management_bp, "config_manager", config_manager)
    setattr(stats_bp, "db_manager", db_manager)
    setattr(stats_bp, "config_manager", config_manager)
    setattr(torrents_bp, "db_manager", db_manager)
    setattr(torrents_bp, "config_manager", config_manager)
    setattr(migrate_bp, "db_manager", db_manager)
    setattr(migrate_bp, "config_manager", config_manager)  # 迁移模块也可能需要配置信息
    setattr(sites_bp, "db_manager", db_manager)
    setattr(local_query_bp, "db_manager", db_manager)

    # 将数据库管理器添加到应用配置中，以便在其他地方可以通过current_app访问
    app.config['DB_MANAGER'] = db_manager

    # 认证中间件：默认开启，校验所有 /api/* 请求（排除 /api/auth/*）

    def _get_jwt_secret() -> str:
        secret = os.getenv("JWT_SECRET", "")
        return secret or "pt-nexus-dev-secret"

    @app.before_request
    def jwt_guard():
        if not request.path.startswith("/api"):
            return None
        # 跳过登录接口
        if request.path.startswith("/api/auth/"):
            return None
        # 跳过健康检查
        if request.path == "/health":
            return None

        # 内部服务认证跳过逻辑
        # 1. 网络隔离：localhost和内部Docker网络跳过认证
        remote_addr = request.environ.get('REMOTE_ADDR', '')
        if remote_addr in ['127.0.0.1', '::1'] or remote_addr.startswith('172.') or remote_addr.startswith('192.168.'):
            return None

        # 2. 内部API Key认证：使用动态token验证
        internal_api_key = request.headers.get("X-Internal-API-Key", "")
        if internal_api_key and validate_internal_token(internal_api_key):
            return None

        # 3. 原有的特定端点跳过（保留兼容性）
        if request.path.startswith("/api/migrate/get_db_seed_info") or \
           request.path.startswith("/api/cross-seed-data/batch-cross-seed-core") or \
           request.path.startswith("/api/cross-seed-data/batch-cross-seed-internal") or \
           request.path.startswith("/api/cross-seed-data/test-no-auth"):
            return None

        # 放行所有预检请求
        if request.method == "OPTIONS":
            return None

        # 正常JWT认证流程
        auth_header = request.headers.get("Authorization", "")
        try:
            # 仅调试日志，生产可根据需要调整级别
            logging.debug(
                f"Auth check path={request.path} method={request.method} auth_header_present={bool(auth_header)}"
            )
        except Exception:
            pass
        if not auth_header.startswith("Bearer "):
            return jsonify({"success": False, "message": "未授权"}), 401
        token = auth_header.split(" ", 1)[1].strip()
        try:
            jwt.decode(token, _get_jwt_secret(),
                       algorithms=["HS256"])  # 验证有效期与签名
        except jwt.ExpiredSignatureError:
            return jsonify({"success": False, "message": "登录已过期"}), 401
        except Exception:
            return jsonify({"success": False, "message": "无效的令牌"}), 401

    # 将蓝图注册到 Flask 应用实例上
    # 在每个蓝图文件中已经定义了 url_prefix="/api"
    app.register_blueprint(management_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(torrents_bp)
    app.register_blueprint(migrate_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(sites_bp)
    app.register_blueprint(cross_seed_data_bp)
    app.register_blueprint(bp_config)
    app.register_blueprint(local_query_bp)

    # --- 步骤 4: 执行初始数据聚合 ---
    logging.info("正在执行初始数据聚合...")
    try:
        db_manager.aggregate_hourly_traffic()
        logging.info("初始数据聚合完成。")
    except Exception as e:
        logging.error(f"初始数据聚合失败: {e}")

    # --- 步骤 5: 启动后台数据追踪服务 ---
    logging.info("正在启动后台数据追踪服务...")
    # 检查是否在调试模式下运行
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        logging.info("正在启动数据追踪线程...")
        start_data_tracker(db_manager, config_manager)

        # --- 启动下载器队列服务 ---
        logging.info("正在启动下载器队列服务...")
        try:
            from core.downloader_queue import create_downloader_queue_service

            # 获取配置
            app_config = config_manager.get()
            queue_config = app_config.get("downloader_queue", {})

            # 检查是否启用
            if queue_config.get("enabled", True):
                # 创建新的服务实例
                downloader_queue_service_instance = create_downloader_queue_service(app_config)
                downloader_queue_service_instance.set_managers(db_manager, config_manager)
                downloader_queue_service_instance.start()

                # 更新全局实例引用
                import core.downloader_queue
                core.downloader_queue.downloader_queue_service = downloader_queue_service_instance

                logging.info("下载器队列服务启动成功")
            else:
                logging.info("下载器队列服务已禁用")
        except Exception as e:
            logging.error(f"启动下载器队列服务失败: {e}", exc_info=True)

        # # --- 启动IYUU后台线程 ---
        # logging.info("正在启动IYUU后台线程...")
        # start_iyuu_thread(db_manager, config_manager)
    else:
        logging.info("检测到调试监控进程，跳过后台线程启动。")

    # --- 步骤 5: 配置前端静态文件服务 ---
    # 这个路由处理所有非 API 请求，将其指向前端应用
    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_vue_app(path):
        static_root = cast(str, app.static_folder)
        # 如果请求的路径是前端静态资源文件，则直接返回
        if path != "" and os.path.exists(os.path.join(static_root, path)):
            return send_from_directory(static_root, path)
        # 否则，返回前端应用的入口 index.html，由 Vue Router 处理路由
        else:
            return send_from_directory(static_root, "index.html")

    logging.info("应用设置完成，准备好接收请求。")
    return app


# --- 程序主入口 ---
if __name__ == "__main__":
    # 通过应用工厂创建 Flask 应用
    flask_app = create_app()

    # 注册应用退出时的清理函数
    def cleanup():
        logging.info("正在清理后台线程...")
        try:
            from core.services import stop_data_tracker
            stop_data_tracker()
        except Exception as e:
            logging.error(f"停止数据追踪线程失败: {e}", exc_info=True)

        try:
            from core.iyuu import stop_iyuu_thread
            stop_iyuu_thread()
        except Exception as e:
            logging.error(f"停止IYUU线程失败: {e}", exc_info=True)

        try:
            from core.downloader_queue import downloader_queue_service
            downloader_queue_service.stop()
            logging.info("下载器队列服务已停止")
        except Exception as e:
            logging.error(f"停止下载器队列服务失败: {e}", exc_info=True)

        logging.info("后台线程清理完成。")

    atexit.register(cleanup)

    # 从环境变量获取端口，如果未设置则使用默认值 15272
    port = int(os.getenv("PORT", 15273))

    logging.info(f"以开发模式启动 Flask 服务器，监听端口 http://0.0.0.0:{port} ...")

    # 运行 Flask 应用
    # debug=False 是生产环境推荐的设置
    flask_app.run(host="0.0.0.0", port=port, debug=True)
