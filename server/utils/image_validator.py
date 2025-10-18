import requests
import logging
from urllib.parse import urlparse

def is_image_url_valid_robust(url: str) -> bool:
    """
    改进版图片链接验证函数，解决误报问题。
    
    主要改进：
    1. 添加标准User-Agent头部
    2. 放宽Content-Type检查
    3. 支持Referer头部
    4. 增加重试机制
    5. 添加文件大小检查
    6. 支持更多图片格式检测
    """
    if not url:
        return False

    # 标准浏览器User-Agent
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }

    # 如果是PT站点的图片，添加Referer
    if any(domain in url.lower() for domain in ['pixhost.to', 'img.seedvault.cn', 'ptimg.org']):
        parsed_url = urlparse(url)
        if parsed_url.netloc:
            headers['Referer'] = f"https://{parsed_url.netloc}/"

    # 第一次尝试：HEAD请求
    try:
        response = requests.head(url, timeout=10, allow_redirects=True, headers=headers)
        response.raise_for_status()
        
        # 检查Content-Type（放宽条件）
        content_type = response.headers.get('Content-Type', '').lower()
        content_length = response.headers.get('Content-Length')
        
        # 更宽松的Content-Type检查
        valid_content_types = [
            'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp', 
            'image/bmp', 'image/svg+xml', 'image/avif', 'image/heic', 'image/heif'
        ]
        
        # 允许的通用Content-Type
        generic_content_types = [
            'application/octet-stream', 'text/plain', 'application/binary'
        ]
        
        if any(ct in content_type for ct in valid_content_types):
            return True
        elif any(ct in content_type for ct in generic_content_types):
            # 对于通用Content-Type，检查文件大小
            if content_length and int(content_length) > 1024:  # 大于1KB
                logging.info(f"链接有效（通用Content-Type但有合理大小）: {url}")
                return True
            else:
                # 需要进一步验证
                return _verify_image_content(url, headers)
        else:
            logging.warning(f"链接有效但Content-Type异常: {url} (Content-Type: {content_type})")
            # 尝试内容验证
            return _verify_image_content(url, headers)

    except requests.exceptions.RequestException as e:
        logging.warning(f"HEAD请求失败: {url} - {e}")
        
        # 第二次尝试：GET请求（流式）
        try:
            response = requests.get(url, stream=True, timeout=10, allow_redirects=True, headers=headers)
            response.raise_for_status()
            
            content_type = response.headers.get('Content-Type', '').lower()
            content_length = response.headers.get('Content-Length')
            
            # 同样的Content-Type检查逻辑
            valid_content_types = [
                'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp', 
                'image/bmp', 'image/svg+xml', 'image/avif', 'image/heic', 'image/heif'
            ]
            
            generic_content_types = [
                'application/octet-stream', 'text/plain', 'application/binary'
            ]
            
            if any(ct in content_type for ct in valid_content_types):
                return True
            elif any(ct in content_type for ct in generic_content_types):
                if content_length and int(content_length) > 1024:
                    logging.info(f"链接有效（通用Content-Type但有合理大小）: {url}")
                    return True
                else:
                    return _verify_image_content(url, headers, stream=True)
            else:
                logging.warning(f"链接有效但Content-Type异常: {url} (Content-Type: {content_type})")
                return _verify_image_content(url, headers, stream=True)

        except requests.exceptions.RequestException as e:
            logging.warning(f"GET请求也失败: {url} - {e}")
            
            # 第三次尝试：使用不同的User-Agent重试
            try:
                fallback_headers = headers.copy()
                fallback_headers['User-Agent'] = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                
                response = requests.get(url, stream=True, timeout=15, allow_redirects=True, headers=fallback_headers)
                response.raise_for_status()
                
                return _verify_image_content(url, fallback_headers, stream=True)
                
            except requests.exceptions.RequestException as e:
                logging.error(f"所有尝试都失败: {url} - {e}")
                return False


def _verify_image_content(url: str, headers: dict, stream: bool = False) -> bool:
    """
    通过下载少量内容来验证是否为真实图片
    
    Args:
        url: 图片URL
        headers: 请求头部
        stream: 是否使用流式下载
    
    Returns:
        bool: 是否为有效图片
    """
    try:
        if stream:
            response = requests.get(url, stream=True, timeout=10, headers=headers)
            response.raise_for_status()
            
            # 只读取前8KB来检测文件头
            content = response.raw.read(8192)
        else:
            response = requests.get(url, timeout=10, headers=headers)
            response.raise_for_status()
            content = response.content[:8192]
        
        if not content:
            return False
        
        # 检查文件头魔数
        image_signatures = {
            b'\xFF\xD8\xFF': 'JPEG',
            b'\x89PNG\r\n\x1a\n': 'PNG',
            b'GIF87a': 'GIF87a',
            b'GIF89a': 'GIF89a',
            b'RIFF': 'WEBP',  # WEBP文件以RIFF开头
            b'BM': 'BMP',
            b'<svg': 'SVG',
            b'<?xml': 'SVG',  # SVG XML声明
        }
        
        for signature, format_name in image_signatures.items():
            if content.startswith(signature):
                logging.info(f"通过文件头验证为{format_name}: {url}")
                return True
        
        # 检查是否为HEIC/HEIF（需要更复杂的检测）
        if content.startswith(b'ftyp') and b'heic' in content or b'heif' in content:
            logging.info(f"通过文件头验证为HEIC/HEIF: {url}")
            return True
        
        logging.warning(f"文件头不匹配任何图片格式: {url}")
        return False
        
    except Exception as e:
        logging.error(f"内容验证失败: {url} - {e}")
        return False


# 保持原有函数作为备用
def is_image_url_valid_robust_original(url: str) -> bool:
    """
    原始版本的图片验证函数，保留作为备用
    """
    if not url:
        return False

    # 第一次尝试：不使用代理
    try:
        # 首先尝试HEAD请求，允许重定向
        response = requests.head(url, timeout=5, allow_redirects=True)
        response.raise_for_status()  # 如果状态码不是2xx，则抛出异常

        # 检查Content-Type
        content_type = response.headers.get('Content-Type')
        if content_type and content_type.startswith('image/'):
            return True
        else:
            logging.warning(
                f"链接有效但内容可能不是图片: {url} (Content-Type: {content_type})")
            return False

    except requests.exceptions.RequestException:
        # 如果HEAD请求失败，尝试GET请求
        try:
            response = requests.get(url,
                                    stream=True,
                                    timeout=5,
                                    allow_redirects=True)
            response.raise_for_status()

            # 检查Content-Type
            content_type = response.headers.get('Content-Type')
            if content_type and content_type.startswith('image/'):
                return True
            else:
                logging.warning(
                    f"链接有效但内容可能不是图片: {url} (Content-Type: {content_type})")
                return False

        except requests.exceptions.RequestException as e:
            logging.warning(f"图片链接GET请求也失败了: {url} - {e}")

            # 不使用全局代理重试，直接返回失败
            return False
