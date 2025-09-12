from ..base import BaseUploader


class City13Uploader(BaseUploader):
    """
    13City站点的上传器实现，继承自BaseUploader
    """
    # 13City使用通用的 _map_parameters 方法，无需重写
    
    def _post_process_response_url(self, url: str) -> str:
        """
        处理13City站点的响应URL，将域名格式化为小写。
        """
        # 将URL中的域名部分转换为小写
        import re
        # 匹配URL中的域名部分并转换为小写
        url = re.sub(r'(?:https?://)([^/]+)', lambda m: m.group(0).lower(),
                     url)
        return url

