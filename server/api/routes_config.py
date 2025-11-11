# routes_config.py
"""
配置管理相关的API路由
"""
from flask import Blueprint, jsonify, request
from config import config_manager
import logging

bp_config = Blueprint('config', __name__)


@bp_config.route('/api/config/source_priority', methods=['GET'])
def get_source_priority():
    """获取源站点优先级配置"""
    try:
        config = config_manager.get()
        source_priority = config.get('source_priority', [])
        return jsonify({'success': True, 'data': source_priority})
    except Exception as e:
        logging.error(f"获取源站点优先级配置失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp_config.route('/api/config/source_priority', methods=['POST'])
def save_source_priority():
    """保存源站点优先级配置"""
    try:
        data = request.get_json()
        source_priority = data.get('source_priority', [])

        # 验证数据类型
        if not isinstance(source_priority, list):
            return jsonify({'success': False, 'message': '源站点优先级必须是数组'}), 400

        # 验证数组元素都是字符串
        if not all(isinstance(item, str) for item in source_priority):
            return jsonify({
                'success': False,
                'message': '源站点优先级数组中的元素必须是字符串'
            }), 400

        # 获取当前配置
        config = config_manager.get()

        # 更新源站点优先级
        config['source_priority'] = source_priority

        # 保存配置
        if config_manager.save(config):
            logging.info(f"源站点优先级配置已保存: {source_priority}")
            return jsonify({'success': True, 'message': '源站点优先级配置已保存'})
        else:
            return jsonify({'success': False, 'message': '保存配置文件失败'}), 500

    except Exception as e:
        logging.error(f"保存源站点优先级配置失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp_config.route('/api/config/batch_fetch_filters', methods=['GET'])
def get_batch_fetch_filters():
    """获取批量获取筛选条件配置"""
    try:
        config = config_manager.get()
        batch_fetch_filters = config.get('batch_fetch_filters', {
            'paths': [],
            'states': [],
            'downloaderIds': []
        })
        return jsonify({'success': True, 'data': batch_fetch_filters})
    except Exception as e:
        logging.error(f"获取批量获取筛选条件配置失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp_config.route('/api/config/batch_fetch_filters', methods=['POST'])
def save_batch_fetch_filters():
    """保存批量获取筛选条件配置"""
    try:
        data = request.get_json()
        batch_fetch_filters = data.get('batch_fetch_filters', {})

        # 验证数据类型
        if not isinstance(batch_fetch_filters, dict):
            return jsonify({'success': False, 'message': '批量获取筛选条件必须是对象'}), 400

        # 验证必需的字段
        required_fields = ['paths', 'states', 'downloaderIds']
        for field in required_fields:
            if field not in batch_fetch_filters:
                return jsonify({
                    'success': False,
                    'message': f'缺少必需字段: {field}'
                }), 400
            if not isinstance(batch_fetch_filters[field], list):
                return jsonify({
                    'success': False,
                    'message': f'字段 {field} 必须是数组'
                }), 400

        # 获取当前配置
        config = config_manager.get()

        # 更新批量获取筛选条件
        config['batch_fetch_filters'] = batch_fetch_filters

        # 保存配置
        if config_manager.save(config):
            logging.info(f"批量获取筛选条件配置已保存: {batch_fetch_filters}")
            return jsonify({'success': True, 'message': '批量获取筛选条件配置已保存'})
        else:
            return jsonify({'success': False, 'message': '保存配置文件失败'}), 500

    except Exception as e:
        logging.error(f"保存批量获取筛选条件配置失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp_config.route('/api/config/cross_seed_review_filter', methods=['GET'])
def get_cross_seed_review_filter():
    """获取转种数据检查状态筛选配置"""
    try:
        config = config_manager.get()
        review_filter = config.get('cross_seed', {}).get('review_filter', '')
        return jsonify({'success': True, 'data': review_filter})
    except Exception as e:
        logging.error(f"获取转种数据检查状态筛选配置失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp_config.route('/api/config/cross_seed_review_filter', methods=['POST'])
def save_cross_seed_review_filter():
    """保存转种数据检查状态筛选配置"""
    try:
        data = request.get_json()
        review_filter = data.get('review_filter', '')

        # 验证数据类型
        if not isinstance(review_filter, str):
            return jsonify({'success': False, 'message': '检查状态筛选必须是字符串'}), 400

        # 验证值是否有效
        valid_values = ['', 'reviewed', 'unreviewed', 'error']
        if review_filter not in valid_values:
            return jsonify({
                'success': False,
                'message': f'无效的检查状态筛选值: {review_filter}'
            }), 400

        # 获取当前配置
        config = config_manager.get()

        # 确保cross_seed配置存在
        if 'cross_seed' not in config:
            config['cross_seed'] = {}

        # 更新检查状态筛选
        config['cross_seed']['review_filter'] = review_filter

        # 保存配置
        if config_manager.save(config):
            logging.info(f"转种数据检查状态筛选配置已保存: {review_filter}")
            return jsonify({'success': True, 'message': '转种数据检查状态筛选配置已保存'})
        else:
            return jsonify({'success': False, 'message': '保存配置文件失败'}), 500

    except Exception as e:
        logging.error(f"保存转种数据检查状态筛选配置失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
