# api/routes_sites.py

import logging
from flask import Blueprint, jsonify, request
from collections import defaultdict

# 从项目根目录导入核心模块
from core import services

# --- Blueprint Setup ---
sites_bp = Blueprint("sites_api", __name__, url_prefix="/api/sites")

@sites_bp.route("/set_not_exist", methods=["POST"])
def set_site_not_exist():
    """将指定种子在指定站点的状态设置为'不存在'"""
    db_manager = sites_bp.db_manager
    try:
        data = request.get_json()
        torrent_name = data.get("torrent_name")
        site_name = data.get("site_name")

        if not torrent_name or not site_name:
            return jsonify({"error": "缺少必要参数"}), 400

        conn, cursor = None, None
        try:
            conn = db_manager._get_connection()
            cursor = db_manager._get_cursor(conn)
            
            placeholder = "%s" if db_manager.db_type in ["mysql", "postgresql"] else "?"
            
            # 更新数据库中的状态
            cursor.execute(
                f"UPDATE torrents SET state = {placeholder} WHERE name = {placeholder} AND sites = {placeholder}",
                ("不存在", torrent_name, site_name)
            )
            
            conn.commit()
            
            if cursor.rowcount > 0:
                return jsonify({"message": "站点状态已成功设置为不存在"}), 200
            else:
                return jsonify({"error": "未找到匹配的记录"}), 404
                
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
                
    except Exception as e:
        logging.error(f"set_site_not_exist 出错: {e}", exc_info=True)
        return jsonify({"error": "设置站点状态失败"}), 500


@sites_bp.route("/update_comment", methods=["POST"])
def update_site_comment():
    """更新指定种子在指定站点的详情页链接或ID"""
    db_manager = sites_bp.db_manager
    try:
        data = request.get_json()
        torrent_name = data.get("torrent_name")
        site_name = data.get("site_name")
        comment = data.get("comment", "").strip()

        if not torrent_name or not site_name:
            return jsonify({"error": "缺少必要参数"}), 400
        
        if not comment:
            return jsonify({"error": "详情页链接或ID不能为空"}), 400

        conn, cursor = None, None
        try:
            conn = db_manager._get_connection()
            cursor = db_manager._get_cursor(conn)
            
            placeholder = "%s" if db_manager.db_type in ["mysql", "postgresql"] else "?"
            
            # 更新数据库中的 details 字段（即 comment）
            cursor.execute(
                f"UPDATE torrents SET details = {placeholder} WHERE name = {placeholder} AND sites = {placeholder}",
                (comment, torrent_name, site_name)
            )
            
            conn.commit()
            
            if cursor.rowcount > 0:
                return jsonify({
                    "message": "详情页链接已成功更新",
                    "success": True
                }), 200
            else:
                return jsonify({"error": "未找到匹配的记录"}), 404
                
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
                
    except Exception as e:
        logging.error(f"update_site_comment 出错: {e}", exc_info=True)
        return jsonify({"error": "更新详情页链接失败"}), 500


@sites_bp.route("/status")
def get_sites_status():
    """获取所有站点的状态信息（是否配置Cookie、是否为源站点/目标站点）"""
    db_manager = sites_bp.db_manager
    config_manager = sites_bp.config_manager
    try:
        conn, cursor = None, None
        try:
            conn = db_manager._get_connection()
            cursor = db_manager._get_cursor(conn)
            
            # 从数据库获取所有站点信息
            cursor.execute("SELECT nickname, site, cookie, migration FROM sites")
            sites_data = cursor.fetchall()
            
            # 构建站点状态列表
            sites_status = []
            for row in sites_data:
                site_dict = dict(row)
                sites_status.append({
                    "name": site_dict.get("nickname"),
                    "site": site_dict.get("site"),
                    "has_cookie": bool(site_dict.get("cookie")),
                    "is_source": site_dict.get("migration", 0) in [1, 3],
                    "is_target": site_dict.get("migration", 0) in [2, 3]
                })
            
            return jsonify(sites_status)
            
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
                
    except Exception as e:
        logging.error(f"get_sites_status 出错: {e}", exc_info=True)
        return jsonify({"error": "获取站点状态失败"}), 500
