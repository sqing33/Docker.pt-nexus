# api/routes_sites.py

import logging
import json
from flask import Blueprint, jsonify, request

# --- Blueprint Setup ---
sites_bp = Blueprint("sites_api", __name__, url_prefix="/api")

@sites_bp.route("/sites/set_not_exist", methods=["POST"])
def set_site_not_exist():
    """设置站点状态为不存在"""
    db_manager = sites_bp.db_manager
    try:
        # 获取请求数据
        data = request.get_json()
        torrent_name = data.get("torrent_name")
        site_name = data.get("site_name")

        if not torrent_name or not site_name:
            return jsonify({"error": "缺少必要的参数"}), 400

        conn = db_manager._get_connection()
        cursor = db_manager._get_cursor(conn)
        ph = db_manager.get_placeholder()

        try:
            # 更新torrents表中对应记录的state为"不存在"
            # 首先查找对应的记录
            cursor.execute(
                f"SELECT hash FROM torrents WHERE name = {ph} AND sites = {ph}",
                (torrent_name, site_name)
            )
            result = cursor.fetchone()

            if not result:
                return jsonify({"error": "未找到对应的种子记录"}), 404

            torrent_hash = result["hash"] if isinstance(result, dict) else result[0]

            # 更新state为"不存在"
            cursor.execute(
                f"UPDATE torrents SET state = {ph} WHERE hash = {ph} AND sites = {ph}",
                ("不存在", torrent_hash, site_name)
            )

            conn.commit()

            if cursor.rowcount > 0:
                return jsonify({"message": "站点状态已成功设置为不存在"}), 200
            else:
                return jsonify({"error": "未找到对应的种子记录"}), 404

        except Exception as e:
            conn.rollback()
            logging.error(f"设置站点状态为不存在时出错: {e}", exc_info=True)
            return jsonify({"error": "数据库操作失败"}), 500
        finally:
            cursor.close()
            conn.close()

    except Exception as e:
        logging.error(f"处理请求时出错: {e}", exc_info=True)
        return jsonify({"error": "处理请求时发生错误"}), 500
