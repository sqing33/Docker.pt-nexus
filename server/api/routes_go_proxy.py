from flask import Blueprint, request, jsonify
import requests
import logging

go_proxy_bp = Blueprint('go_proxy', __name__)

# Go服务配置
GO_SERVICE_URL = "http://localhost:5275"


@go_proxy_bp.route('/batch-enhance', methods=['POST'])
def batch_enhance_proxy():
    """转发批量转种请求到Go服务"""
    try:
        # 获取请求数据
        data = request.get_json()

        # 转发到Go服务
        response = requests.post(
            f"{GO_SERVICE_URL}/batch-enhance",
            json=data,
            timeout=300  # 5分钟超时
        )

        # 检查响应内容是否为空
        if not response.text.strip():
            logging.error("Go服务返回空响应")
            return jsonify({"success": False, "error": "Go服务返回空响应"}), 503

        # 尝试解析JSON，如果失败则返回原始错误信息
        try:
            return jsonify(response.json()), response.status_code
        except ValueError as json_error:
            logging.error(f"Go服务返回非JSON响应: {response.text[:200]}")
            return jsonify({
                "success": False,
                "error": f"Go服务返回无效JSON: {str(json_error)}",
                "raw_response": response.text[:500]  # 包含部分原始响应用于调试
            }), 503

    except requests.exceptions.RequestException as e:
        logging.error(f"Go服务请求失败: {e}")
        return jsonify({"success": False, "error": f"Go服务不可用: {str(e)}"}), 503
    except Exception as e:
        logging.error(f"代理请求处理失败: {e}")
        return jsonify({"success": False, "error": f"代理服务错误: {str(e)}"}), 500


@go_proxy_bp.route('/batch-enhance/stop', methods=['POST'])
def stop_batch_enhance_proxy():
    """转发停止批量转种请求到Go服务"""
    try:
        # 转发到Go服务
        response = requests.post(
            f"{GO_SERVICE_URL}/batch-enhance/stop",
            timeout=10
        )

        # 检查响应内容是否为空
        if not response.text.strip():
            logging.error("Go服务返回空响应")
            return jsonify({"success": False, "error": "Go服务返回空响应"}), 503

        # 尝试解析JSON
        try:
            return jsonify(response.json()), response.status_code
        except ValueError as json_error:
            logging.error(f"Go服务返回非JSON响应: {response.text[:200]}")
            return jsonify({
                "success": False,
                "error": f"Go服务返回无效JSON: {str(json_error)}",
                "raw_response": response.text[:500]
            }), 503

    except requests.exceptions.RequestException as e:
        logging.error(f"Go服务请求失败: {e}")
        return jsonify({"success": False, "error": f"Go服务不可用: {str(e)}"}), 503
    except Exception as e:
        logging.error(f"代理请求处理失败: {e}")
        return jsonify({"success": False, "error": f"代理服务错误: {str(e)}"}), 500


@go_proxy_bp.route('/records', methods=['GET', 'DELETE'])
def records_proxy():
    """转发记录相关请求到Go服务"""
    try:
        if request.method == 'GET':
            # 获取记录
            response = requests.get(f"{GO_SERVICE_URL}/records", timeout=30)
        else:  # DELETE
            # 清空记录
            response = requests.delete(f"{GO_SERVICE_URL}/records", timeout=30)

        # 检查响应内容是否为空
        if not response.text.strip():
            logging.error("Go服务返回空响应")
            return jsonify({"success": False, "error": "Go服务返回空响应"}), 503

        # 尝试解析JSON，如果失败则返回原始错误信息
        try:
            return jsonify(response.json()), response.status_code
        except ValueError as json_error:
            logging.error(f"Go服务返回非JSON响应: {response.text[:200]}")
            return jsonify({
                "success": False,
                "error": f"Go服务返回无效JSON: {str(json_error)}",
                "raw_response": response.text[:500]  # 包含部分原始响应用于调试
            }), 503

    except requests.exceptions.RequestException as e:
        logging.error(f"Go服务请求失败: {e}")
        return jsonify({"success": False, "error": f"Go服务不可用: {str(e)}"}), 503
    except Exception as e:
        logging.error(f"代理请求处理失败: {e}")
        return jsonify({"success": False, "error": f"代理服务错误: {str(e)}"}), 500
