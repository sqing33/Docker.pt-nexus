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

        # 返回Go服务的响应
        return jsonify(response.json()), response.status_code

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

        return jsonify(response.json()), response.status_code

    except requests.exceptions.RequestException as e:
        logging.error(f"Go服务请求失败: {e}")
        return jsonify({"success": False, "error": f"Go服务不可用: {str(e)}"}), 503
    except Exception as e:
        logging.error(f"代理请求处理失败: {e}")
        return jsonify({"success": False, "error": f"代理服务错误: {str(e)}"}), 500
