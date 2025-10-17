"""
下载器ID生成和迁移辅助工具
"""
import hashlib
import re
import logging
from urllib.parse import urlparse


def generate_downloader_id_from_host(host):
    """
    基于host生成固定的下载器ID
    确保相同host:port总是生成相同的ID，不同host:port生成不同ID
    
    Args:
        host: 下载器的host地址，可以是IP、域名或完整URL
        
    Returns:
        str: 16字符的十六进制ID
    """
    if not host:
        raise ValueError("Host不能为空")
    
    # 标准化host：提取主机名和端口
    if host.startswith(('http://', 'https://')):
        parsed = urlparse(host)
        normalized_host = parsed.hostname
        port = parsed.port
    else:
        # 手动解析host:port格式
        parts = host.split('/')
        host_part = parts[0]  # 获取host:port部分
        
        if ':' in host_part:
            normalized_host = host_part.split(':')[0]
            try:
                port = int(host_part.split(':')[1])
            except (ValueError, IndexError):
                port = None
        else:
            normalized_host = host_part
            port = None
    
    if not normalized_host:
        raise ValueError(f"无法从host '{host}' 中提取有效的主机名")
    
    # 构建用于生成ID的字符串：包含主机名和端口
    # IP地址直接使用，域名转换为小写
    ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if re.match(ip_pattern, normalized_host):
        base_string = normalized_host
    else:
        base_string = normalized_host.lower()
    
    # 如果有端口号，将其加入到base_string中
    if port:
        base_string = f"{base_string}:{port}"
    
    # 使用SHA256生成固定长度的ID
    hash_object = hashlib.sha256(base_string.encode('utf-8'))
    # 取前16个字符作为ID（64位）
    downloader_id = hash_object.hexdigest()[:16]
    
    logging.debug(f"为host '{host}' (标准化为 '{base_string}') 生成ID: {downloader_id}")
    return downloader_id


def validate_downloader_id(downloader_config):
    """
    验证下载器配置中的ID是否与host匹配
    
    Args:
        downloader_config: 下载器配置字典，包含id和host字段
        
    Returns:
        tuple: (is_valid, expected_id, message)
    """
    current_id = downloader_config.get("id")
    host = downloader_config.get("host")
    name = downloader_config.get("name", "未命名下载器")
    
    if not host:
        return False, None, f"下载器 '{name}' 缺少host配置"
    
    try:
        expected_id = generate_downloader_id_from_host(host)
    except ValueError as e:
        return False, None, f"下载器 '{name}' 的host配置无效: {str(e)}"
    
    if not current_id:
        return False, expected_id, f"下载器 '{name}' 缺少ID，应为: {expected_id}"
    
    if current_id != expected_id:
        return False, expected_id, f"下载器 '{name}' 的ID不匹配 (当前: {current_id}, 应为: {expected_id})"
    
    return True, expected_id, "ID验证通过"


def generate_migration_mapping(config):
    """
    生成ID迁移映射表
    
    Args:
        config: 完整的配置字典
        
    Returns:
        list: 迁移映射列表，每项包含 old_id, new_id, host, name
    """
    downloaders = config.get("downloaders", [])
    migration_mapping = []
    
    for downloader in downloaders:
        old_id = downloader.get("id")
        host = downloader.get("host")
        name = downloader.get("name", "未命名")
        
        if not old_id or not host:
            logging.warning(f"跳过下载器 '{name}'：缺少ID或host")
            continue
        
        try:
            new_id = generate_downloader_id_from_host(host)
            
            if old_id != new_id:
                migration_mapping.append({
                    "old_id": old_id,
                    "new_id": new_id,
                    "host": host,
                    "name": name
                })
                logging.info(f"检测到需要迁移的下载器: {name} ({old_id} -> {new_id})")
        except Exception as e:
            logging.error(f"为下载器 '{name}' 生成新ID失败: {e}")
    
    return migration_mapping
