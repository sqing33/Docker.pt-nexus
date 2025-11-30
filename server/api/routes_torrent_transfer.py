# api/routes_torrent_transfer.py

import logging
import json
from flask import Blueprint, jsonify, request

# 从项目根目录导入核心模块
from utils.torrent_manager import TorrentManager

# --- Blueprint Setup ---
torrent_transfer_bp = Blueprint("torrent_transfer_api", __name__, url_prefix="/api")


@torrent_transfer_bp.route("/torrent/transfer/prepare", methods=["POST"])
def prepare_torrent_transfer():
    """
    准备种子转移：查找并验证可转移的种子
    """
    db_manager = torrent_transfer_bp.db_manager
    config_manager = torrent_transfer_bp.config_manager

    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "请求数据为空"}), 400

        # 获取请求参数
        source_downloader_id = data.get("source_downloader_id")
        target_downloader_id = data.get("target_downloader_id")
        site_name = data.get("site_name")
        torrent_name = data.get("torrent_name")
        torrent_size = data.get("torrent_size")

        # 验证必需参数
        if not all([source_downloader_id, target_downloader_id, site_name, torrent_name, torrent_size is not None]):
            return jsonify({
                "success": False,
                "message": "缺少必需参数: source_downloader_id, target_downloader_id, site_name, torrent_name, torrent_size"
            }), 400

        # 验证参数类型
        try:
            torrent_size = int(torrent_size)
        except (ValueError, TypeError):
            return jsonify({"success": False, "message": "torrent_size 必须是整数"}), 400

        logging.info(f"准备种子转移: {torrent_name} ({site_name}) {source_downloader_id} -> {target_downloader_id}")

        # 创建种子管理器
        torrent_manager = TorrentManager(db_manager, config_manager)

        # 查找匹配的种子
        matched_torrents = torrent_manager.find_torrents_by_site(
            source_downloader_id, site_name, torrent_name, torrent_size, data.get("save_path")
        )

        if not matched_torrents:
            # 如果精确匹配失败，尝试查找相似种子作为建议
            try:
                similar_torrents = torrent_manager.find_similar_torrents(torrent_name, torrent_size)
                return jsonify({
                    "success": False,
                    "message": f"未找到精确匹配的种子，但找到 {len(similar_torrents)} 个相似的种子",
                    "found_count": 0,
                    "suggestions": similar_torrents[:5],  # 只返回前5个建议
                    "suggestion_count": len(similar_torrents)
                }), 404
            except Exception as e:
                logging.warning(f"查找相似种子失败: {e}")
                return jsonify({
                    "success": False,
                    "message": f"未找到匹配的种子: {torrent_name}",
                    "found_count": 0
                }), 404

        # 返回准备结果
        return jsonify({
            "success": True,
            "message": f"找到 {len(matched_torrents)} 个匹配的种子",
            "found_count": len(matched_torrents),
            "torrents": [{
                "hash": t["hash"],
                "name": t["name"],
                "size": t["size"],
                "state": t["state"]
            } for t in matched_torrents]
        }), 200

    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        logging.error(f"prepare_torrent_transfer 出错: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"准备转移失败: {str(e)}"}), 500


@torrent_transfer_bp.route("/torrent/transfer/similar", methods=["POST"])
def find_similar_torrents():
    """
    查找相似的种子（用于调试和建议）
    """
    db_manager = torrent_transfer_bp.db_manager
    config_manager = torrent_transfer_bp.config_manager

    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "请求数据为空"}), 400

        # 获取请求参数
        torrent_name = data.get("torrent_name")
        torrent_size = data.get("torrent_size")

        # 验证必需参数
        if not all([torrent_name, torrent_size is not None]):
            return jsonify({
                "success": False,
                "message": "缺少必需参数: torrent_name, torrent_size"
            }), 400

        # 验证参数类型
        try:
            torrent_size = int(torrent_size)
        except (ValueError, TypeError):
            return jsonify({"success": False, "message": "torrent_size 必须是整数"}), 400

        logging.info(f"查找相似种子: {torrent_name}")

        # 创建种子管理器
        torrent_manager = TorrentManager(db_manager, config_manager)

        # 查找相似种子
        similar_torrents = torrent_manager.find_similar_torrents(torrent_name, torrent_size)

        return jsonify({
            "success": True,
            "message": f"找到 {len(similar_torrents)} 个相似的种子",
            "torrents": similar_torrents
        }), 200

    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        logging.error(f"find_similar_torrents 出错: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"查找相似种子失败: {str(e)}"}), 500


@torrent_transfer_bp.route("/torrent/transfer/execute", methods=["POST"])
def execute_torrent_transfer():
    """
    执行种子转移：完整的查找->暂停->导出->添加流程
    """
    db_manager = torrent_transfer_bp.db_manager
    config_manager = torrent_transfer_bp.config_manager

    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "请求数据为空"}), 400

        # 获取请求参数
        source_downloader_id = data.get("source_downloader_id")
        target_downloader_id = data.get("target_downloader_id")
        site_name = data.get("site_name")
        torrent_name = data.get("torrent_name")
        torrent_size = data.get("torrent_size")
        save_path = data.get("save_path")  # 可选参数

        # 验证必需参数
        if not all([source_downloader_id, target_downloader_id, site_name, torrent_name, torrent_size is not None]):
            return jsonify({
                "success": False,
                "message": "缺少必需参数: source_downloader_id, target_downloader_id, site_name, torrent_name, torrent_size"
            }), 400

        # 验证参数类型
        try:
            torrent_size = int(torrent_size)
        except (ValueError, TypeError):
            return jsonify({"success": False, "message": "torrent_size 必须是整数"}), 400

        logging.info(f"执行种子转移: {torrent_name} ({site_name}) {source_downloader_id} -> {target_downloader_id}")

        # 创建种子管理器
        torrent_manager = TorrentManager(db_manager, config_manager)

        # 执行完整的转移流程
        result = torrent_manager.transfer_torrents_between_downloaders(
            source_downloader_id=source_downloader_id,
            target_downloader_id=target_downloader_id,
            site_name=site_name,
            torrent_name=torrent_name,
            torrent_size=torrent_size,
            save_path=save_path
        )

        # 根据结果返回相应的状态码
        if result["success"]:
            return jsonify(result), 200
        else:
            # 如果是找不到种子，返回404
            if result.get("step") == "find" and result.get("found_count") == 0:
                return jsonify(result), 404
            # 其他错误返回400
            return jsonify(result), 400

    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        logging.error(f"execute_torrent_transfer 出错: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"执行转移失败: {str(e)}"}), 500


@torrent_transfer_bp.route("/torrent/transfer/pause", methods=["POST"])
def pause_torrents():
    """
    暂停指定的种子
    """
    db_manager = torrent_transfer_bp.db_manager
    config_manager = torrent_transfer_bp.config_manager

    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "请求数据为空"}), 400

        # 获取请求参数
        downloader_id = data.get("downloader_id")
        torrent_hashes = data.get("torrent_hashes", [])

        # 验证必需参数
        if not downloader_id:
            return jsonify({"success": False, "message": "缺少必需参数: downloader_id"}), 400

        if not torrent_hashes or not isinstance(torrent_hashes, list):
            return jsonify({"success": False, "message": "torrent_hashes 必须是非空数组"}), 400

        logging.info(f"暂停种子: {len(torrent_hashes)} 个种子在下载器 {downloader_id}")

        # 创建种子管理器
        torrent_manager = TorrentManager(db_manager, config_manager)

        # 暂停种子
        success = torrent_manager.pause_torrents(downloader_id, torrent_hashes)

        if success:
            return jsonify({
                "success": True,
                "message": f"成功暂停 {len(torrent_hashes)} 个种子"
            }), 200
        else:
            return jsonify({
                "success": False,
                "message": "暂停种子失败"
            }), 500

    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        logging.error(f"pause_torrents 出错: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"暂停种子失败: {str(e)}"}), 500


@torrent_transfer_bp.route("/torrent/transfer/export", methods=["POST"])
def export_torrent_files():
    """
    导出种子文件
    """
    db_manager = torrent_transfer_bp.db_manager
    config_manager = torrent_transfer_bp.config_manager

    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "请求数据为空"}), 400

        # 获取请求参数
        downloader_id = data.get("downloader_id")
        torrent_hashes = data.get("torrent_hashes", [])

        # 验证必需参数
        if not downloader_id:
            return jsonify({"success": False, "message": "缺少必需参数: downloader_id"}), 400

        if not torrent_hashes or not isinstance(torrent_hashes, list):
            return jsonify({"success": False, "message": "torrent_hashes 必须是非空数组"}), 400

        logging.info(f"导出种子文件: {len(torrent_hashes)} 个种子从下载器 {downloader_id}")

        # 创建种子管理器
        torrent_manager = TorrentManager(db_manager, config_manager)

        # 创建临时导出目录
        import tempfile
        export_dir = tempfile.mkdtemp(prefix="pt_nexus_export_")

        # 导出种子文件
        exported_files = torrent_manager.export_torrent_files(downloader_id, torrent_hashes, export_dir)

        if not exported_files:
            return jsonify({
                "success": False,
                "message": "导出种子文件失败"
            }), 500

        return jsonify({
            "success": True,
            "message": f"成功导出 {len(exported_files)} 个种子文件",
            "exported_files": exported_files,
            "export_dir": export_dir
        }), 200

    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        logging.error(f"export_torrent_files 出错: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"导出种子文件失败: {str(e)}"}), 500


@torrent_transfer_bp.route("/torrent/transfer/add", methods=["POST"])
def add_torrents_to_downloader():
    """
    将种子文件添加到目标下载器
    """
    db_manager = torrent_transfer_bp.db_manager
    config_manager = torrent_transfer_bp.config_manager

    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "请求数据为空"}), 400

        # 获取请求参数
        target_downloader_id = data.get("target_downloader_id")
        torrent_files = data.get("torrent_files", [])
        save_path = data.get("save_path")
        paused = data.get("paused", False)

        # 验证必需参数
        if not target_downloader_id:
            return jsonify({"success": False, "message": "缺少必需参数: target_downloader_id"}), 400

        if not torrent_files or not isinstance(torrent_files, list):
            return jsonify({"success": False, "message": "torrent_files 必须是非空数组"}), 400

        logging.info(f"添加种子到下载器: {len(torrent_files)} 个种子文件到 {target_downloader_id}")

        # 创建种子管理器
        torrent_manager = TorrentManager(db_manager, config_manager)

        # 添加种子到下载器
        result = torrent_manager.add_torrents_to_downloader(
            target_downloader_id=target_downloader_id,
            torrent_files=torrent_files,
            save_path=save_path,
            paused=paused
        )

        return jsonify({
            "success": result["success"],
            "message": f"添加种子完成: 成功 {result['success_count']}, 失败 {result['failed_count']}",
            "result": result
        }), 200

    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception as e:
        logging.error(f"add_torrents_to_downloader 出错: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"添加种子失败: {str(e)}"}), 500