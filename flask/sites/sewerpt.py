# sites/13city.py

import os
import sys
import traceback
from loguru import logger


# 为了兼容旧的API，我们保持原来的函数签名
def upload(site_info: dict, upload_payload: dict):
    """
    保持与旧API兼容的上传接口
    """
    try:
        # 添加项目根目录到Python路径
        sys.path.append(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        from uploaders import create_uploader
        uploader = create_uploader("sewerpt", site_info, upload_payload)
        return uploader.execute_upload()
    except Exception as e:
        logger.error(f"sewerpt上传器执行时发生错误: {e}")
        logger.error(traceback.format_exc())
        return False, f"请求异常: {e}"
