"""
IMDb、TMDb、豆瓣 三平台媒体ID转换工具

支持任意两个平台之间的互相转换，以及统一转换功能。
"""

import re
import time
import requests
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# ============================================================================
# ID 提取函数
# ============================================================================


def extract_imdb_id(imdb_url: str) -> str:
    """
    从IMDb链接中提取IMDb ID

    Args:
        imdb_url: IMDb链接，格式如 https://www.imdb.com/title/tt99999999967/

    Returns:
        str: IMDb ID，如 tt99999999967，如果提取失败返回空字符串
    """
    if not imdb_url:
        return ""

    match = re.search(r"(tt\d+)", imdb_url)
    if match:
        imdb_id = match.group(1)
        logger.debug(f"从IMDb链接中提取到ID: {imdb_id}")
        return imdb_id

    logger.warning(f"无法从IMDb链接中提取ID: {imdb_url}")
    return ""


def extract_tmdb_id(tmdb_url: str) -> str:
    """
    从TMDb链接中提取TMDb ID

    Args:
        tmdb_url: TMDb链接，格式如 https://www.themoviedb.org/movie/550

    Returns:
        str: TMDb ID，如 550，如果提取失败返回空字符串
    """
    if not tmdb_url:
        return ""

    match = re.search(r"/(\d+)", tmdb_url)
    if match:
        tmdb_id = match.group(1)
        logger.debug(f"从TMDb链接中提取到ID: {tmdb_id}")
        return tmdb_id

    logger.warning(f"无法从TMDb链接中提取ID: {tmdb_url}")
    return ""


def extract_douban_id(douban_url: str) -> str:
    """
    从豆瓣链接中提取豆瓣ID

    Args:
        douban_url: 豆瓣链接，格式如 https://movie.douban.com/subject/1292052/

    Returns:
        str: 豆瓣ID，如 1292052，如果提取失败返回空字符串
    """
    if not douban_url:
        return ""

    match = re.search(r"/subject/(\d+)", douban_url)
    if match:
        douban_id = match.group(1)
        logger.debug(f"从豆瓣链接中提取到ID: {douban_id}")
        return douban_id

    logger.warning(f"无法从豆瓣链接中提取ID: {douban_url}")
    return ""


# ============================================================================
# IMDb ↔ TMDb 转换
# ============================================================================


def imdb_to_tmdb(imdb_url: str, api_key: str = None) -> tuple[bool, str]:
    """
    通过IMDb链接获取TMDb链接

    Args:
        imdb_url: IMDb链接
        api_key: TMDB API Key，如果不提供则使用默认的

    Returns:
        tuple: (success, tmdb_url) 成功返回True和TMDb链接，失败返回False和空字符串
    """
    # 提取IMDb ID
    imdb_id = extract_imdb_id(imdb_url)
    if not imdb_id:
        logger.error("无法提取IMDb ID，转换失败")
        return False, ""

    # 使用提供的API Key或默认的
    if not api_key:
        api_key = "0f79586eb9d92afa2b7266f7928b055c"
        logger.debug("使用默认TMDB API Key")

    # 构造TMDB API基础URL列表，优先使用直接API，失败时使用代理
    api_bases = [
        ("直连API", "https://api.tmdb.org"),
        ("备用直连API", "https://api.themoviedb.org"),
        ("代理API", "http://pt-nexus-proxy.sqing33.dpdns.org/https://api.themoviedb.org"),
        ("备用代理API", "http://pt-nexus-proxy.1395251710.workers.dev/https://api.themoviedb.org"),
    ]

    try:
        logger.info(f"正在通过TMDb API查询IMDb ID: {imdb_id}")

        # 构造API路径和查询参数
        api_path = f"/3/find/{imdb_id}?external_source=imdb_id&api_key={api_key}"

        # 依次尝试不同的API端点
        data = None
        max_retries = 3

        for url_name, api_base in api_bases:
            # 拼接完整的API URL
            api_url = f"{api_base}{api_path}"
            logger.info(f"尝试使用{url_name}: {api_base}")

            # 发送API请求，增加重试机制
            for attempt in range(max_retries):
                try:
                    response = requests.get(api_url, timeout=30)
                    response.raise_for_status()
                    data = response.json()
                    logger.info(f"{url_name}请求成功")
                    break
                except (requests.exceptions.RequestException, requests.exceptions.SSLError) as e:
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"{url_name}请求失败 (尝试 {attempt + 1}/{max_retries}): {e}"
                        )
                        time.sleep(2**attempt)  # 指数退避
                        continue
                    else:
                        logger.error(f"{url_name}所有重试均失败: {e}")
                        break

            # 如果当前API成功获取数据，跳出循环
            if data is not None:
                break
            else:
                logger.warning(f"{url_name}失败，尝试下一个API端点")

        # 如果所有API都失败
        if data is None:
            logger.error("所有API端点均无法访问")
            return False, ""

        # 检查电影结果
        movie_results = data.get("movie_results", [])
        if movie_results:
            movie = movie_results[0]
            tmdb_id = movie.get("id")
            title = movie.get("title", "")

            if tmdb_id:
                tmdb_url = f"https://www.themoviedb.org/movie/{tmdb_id}"
                logger.info(f"成功转换: {imdb_id} -> {title} -> {tmdb_url}")
                return True, tmdb_url
            else:
                logger.error("TMDB响应中未找到ID")

        # 检查电视剧结果
        tv_results = data.get("tv_results", [])
        if tv_results:
            tv = tv_results[0]
            tmdb_id = tv.get("id")
            title = tv.get("name", "")

            if tmdb_id:
                tmdb_url = f"https://www.themoviedb.org/tv/{tmdb_id}"
                logger.info(f"成功转换: {imdb_id} -> {title} -> {tmdb_url}")
                return True, tmdb_url
            else:
                logger.error("TMDB响应中未找到ID")

        logger.warning(f"TMDB API未找到IMDb ID {imdb_id} 对应的内容")
        return False, ""

    except requests.exceptions.RequestException as e:
        logger.error(f"TMDB API请求失败: {e}")
        return False, ""
    except Exception as e:
        logger.error(f"IMDb到TMDb转换过程中发生错误: {e}")
        return False, ""


def tmdb_to_imdb(tmdb_url: str, api_key: str = None) -> tuple[bool, str]:
    """
    通过TMDb链接获取IMDb链接

    Args:
        tmdb_url: TMDb链接
        api_key: TMDB API Key，如果不提供则使用默认的

    Returns:
        tuple: (success, imdb_url) 成功返回True和IMDb链接，失败返回False和空字符串
    """
    # 提取TMDb ID
    tmdb_id = extract_tmdb_id(tmdb_url)
    if not tmdb_id:
        logger.error("无法提取TMDb ID，转换失败")
        return False, ""

    # 判断媒体类型
    media_type = None
    if "/movie/" in tmdb_url:
        media_type = "movie"
    elif "/tv/" in tmdb_url:
        media_type = "tv"
    else:
        logger.error("无法确定媒体类型")
        return False, ""

    # 使用提供的API Key或默认的
    if not api_key:
        api_key = "0f79586eb9d92afa2b7266f7928b055c"
        logger.debug("使用默认TMDB API Key")

    # 构造TMDB API基础URL列表
    api_bases = [
        ("直连API", "https://api.tmdb.org"),
        ("备用直连API", "https://api.themoviedb.org"),
        ("代理API", "http://pt-nexus-proxy.sqing33.dpdns.org/https://api.themoviedb.org"),
        ("备用代理API", "http://pt-nexus-proxy.1395251710.workers.dev/https://api.themoviedb.org"),
    ]

    try:
        logger.info(f"正在通过TMDb API查询TMDb ID: {tmdb_id} (类型: {media_type})")

        # 构造API路径
        api_path = f"/3/{media_type}/{tmdb_id}/external_ids?api_key={api_key}"

        # 依次尝试不同的API端点
        data = None
        max_retries = 3

        for url_name, api_base in api_bases:
            # 拼接完整的API URL
            api_url = f"{api_base}{api_path}"
            logger.info(f"尝试使用{url_name}: {api_base}")

            # 发送API请求，增加重试机制
            for attempt in range(max_retries):
                try:
                    response = requests.get(api_url, timeout=30)
                    response.raise_for_status()
                    data = response.json()
                    logger.info(f"{url_name}请求成功")
                    break
                except (requests.exceptions.RequestException, requests.exceptions.SSLError) as e:
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"{url_name}请求失败 (尝试 {attempt + 1}/{max_retries}): {e}"
                        )
                        time.sleep(2**attempt)  # 指数退避
                        continue
                    else:
                        logger.error(f"{url_name}所有重试均失败: {e}")
                        break

            # 如果当前API成功获取数据，跳出循环
            if data is not None:
                break
            else:
                logger.warning(f"{url_name}失败，尝试下一个API端点")

        # 如果所有API都失败
        if data is None:
            logger.error("所有API端点均无法访问")
            return False, ""

        # 提取IMDb ID
        imdb_id = data.get("imdb_id")
        if imdb_id:
            imdb_url = f"https://www.imdb.com/title/{imdb_id}/"
            logger.info(f"成功转换: {tmdb_id} -> {imdb_id}")
            return True, imdb_url
        else:
            logger.warning(f"TMDb ID {tmdb_id} 未找到对应的IMDb ID")
            return False, ""

    except requests.exceptions.RequestException as e:
        logger.error(f"TMDB API请求失败: {e}")
        return False, ""
    except Exception as e:
        logger.error(f"TMDb到IMDb转换过程中发生错误: {e}")
        return False, ""


# ============================================================================
# IMDb ↔ 豆瓣 转换
# ============================================================================


def call_api_with_fallback(
    api_path: str, params: dict = None, method: str = "GET", timeout: int = 10
) -> tuple[bool, dict, str]:
    """
    调用API时支持主备域名切换的通用函数

    Args:
        api_path: API路径，如 '/?imdbid=tt9999999996'
        params: 额外的请求参数
        method: HTTP方法，默认 'GET'
        timeout: 超时时间，默认 10 秒

    Returns:
        tuple: (success, response_data, error_message)
    """
    # 主备域名配置
    primary_domain = "https://pt-nexus-imdb2douban.sqing33.dpdns.org"
    fallback_domain = "https://pt-nexus-imdb2douban.1395251710.workers.dev"

    # 构建完整的URL列表
    urls = [f"{primary_domain}{api_path}", f"{fallback_domain}{api_path}"]

    for i, url in enumerate(urls):
        domain_name = "主域名" if i == 0 else "备用域名"
        try:
            logger.info(f"尝试使用{domain_name}: {url}")

            if method.upper() == "GET":
                response = requests.get(url, params=params, timeout=timeout)
            elif method.upper() == "POST":
                response = requests.post(url, params=params, timeout=timeout)
            else:
                raise ValueError(f"不支持的HTTP方法: {method}")

            if response.status_code == 200:
                try:
                    data = response.json()
                    logger.info(f"{domain_name}调用成功")
                    return True, data, ""
                except ValueError:
                    # 如果不是JSON，返回文本内容
                    logger.info(f"{domain_name}调用成功（返回文本）")
                    return True, response.text, ""
            else:
                error_msg = f"HTTP {response.status_code}"
                logger.warning(f"{domain_name}返回错误: {error_msg}")

        except requests.exceptions.SSLError as e:
            error_msg = f"SSL错误: {str(e)}"
            logger.error(f"{domain_name}SSL错误: {e}")
            if i == 0:  # 主域名失败，尝试备用域名
                continue
            else:
                return False, None, error_msg
        except requests.exceptions.RequestException as e:
            error_msg = f"网络错误: {str(e)}"
            logger.error(f"{domain_name}网络错误: {e}")
            if i == 0:  # 主域名失败，尝试备用域名
                continue
            else:
                return False, None, error_msg
        except Exception as e:
            error_msg = f"未知错误: {str(e)}"
            logger.error(f"{domain_name}未知错误: {e}")
            if i == 0:  # 主域名失败，尝试备用域名
                continue
            else:
                return False, None, error_msg

    # 所有域名都失败
    return False, None, "所有API域名都无法访问"


def imdb_to_douban(imdb_url: str) -> tuple[bool, str]:
    """
    通过IMDb链接获取豆瓣链接

    Args:
        imdb_url: IMDb链接

    Returns:
        tuple: (success, douban_url) 成功返回True和豆瓣链接，失败返回False和空字符串
    """
    # 提取IMDb ID
    imdb_id = extract_imdb_id(imdb_url)
    if not imdb_id:
        logger.error("无法提取IMDb ID，转换失败")
        return False, ""

    try:
        logger.info(f"使用IMDb ID查询豆瓣链接: {imdb_id}")

        api_path = f"/?imdbid={imdb_id}"
        success, data, error_msg = call_api_with_fallback(api_path, timeout=10)

        if success:
            # data 可能是 dict 或 list
            if isinstance(data, dict):
                data = data.get("data", [])
            elif isinstance(data, list):
                data = data

            if data and data[0]:
                douban_id = data[0].get("doubanid")
                if douban_id:
                    douban_url = f"https://movie.douban.com/subject/{douban_id}/"
                    logger.info(f"成功转换: {imdb_id} -> {douban_url}")
                    return True, douban_url
                else:
                    logger.warning(f"API响应中未找到与 {imdb_id} 匹配的豆瓣ID")
            else:
                logger.warning("API响应为空")
        else:
            logger.warning(f"API查询失败: {error_msg}")

        return False, ""

    except Exception as e:
        logger.error(f"IMDb到豆瓣转换过程中发生错误: {e}")
        return False, ""


def douban_to_imdb(douban_url: str) -> tuple[bool, str]:
    """
    通过豆瓣链接获取IMDb链接

    Args:
        douban_url: 豆瓣链接

    Returns:
        tuple: (success, imdb_url) 成功返回True和IMDb链接，失败返回False和空字符串
    """
    # 提取豆瓣ID
    douban_id = extract_douban_id(douban_url)
    if not douban_id:
        logger.error("无法提取豆瓣ID，转换失败")
        return False, ""

    try:
        logger.info(f"使用豆瓣ID查询IMDb链接: {douban_id}")

        api_path = f"/?doubanid={douban_id}"
        success, data, error_msg = call_api_with_fallback(api_path, timeout=10)

        if success:
            # data 可能是 dict 或 list
            if isinstance(data, dict):
                data = data.get("data", [])
            elif isinstance(data, list):
                data = data

            if data and data[0]:
                imdb_id = data[0].get("imdbid")
                if imdb_id:
                    imdb_url = f"https://www.imdb.com/title/{imdb_id}/"
                    logger.info(f"成功转换: {douban_id} -> {imdb_url}")
                    return True, imdb_url
                else:
                    logger.warning(f"API响应中未找到与 {douban_id} 匹配的IMDb ID")
            else:
                logger.warning("API响应为空")
        else:
            logger.warning(f"API查询失败: {error_msg}")

        return False, ""

    except Exception as e:
        logger.error(f"豆瓣到IMDb转换过程中发生错误: {e}")
        return False, ""


# ============================================================================
# TMDb ↔ 豆瓣 转换（通过IMDb中转）
# ============================================================================


def tmdb_to_douban(tmdb_url: str, api_key: str = None) -> tuple[bool, str]:
    """
    通过TMDb链接获取豆瓣链接（通过IMDb中转）

    Args:
        tmdb_url: TMDb链接
        api_key: TMDB API Key

    Returns:
        tuple: (success, douban_url) 成功返回True和豆瓣链接，失败返回False和空字符串
    """
    logger.info("TMDb -> 豆瓣转换（通过IMDb中转）")

    # 第一步：TMDb -> IMDb
    success, imdb_url = tmdb_to_imdb(tmdb_url, api_key)
    if not success:
        logger.error("TMDb到IMDb转换失败，无法继续")
        return False, ""

    # 第二步：IMDb -> 豆瓣
    success, douban_url = imdb_to_douban(imdb_url)
    if not success:
        logger.error("IMDb到豆瓣转换失败")
        return False, ""

    logger.info(f"成功转换: {tmdb_url} -> {douban_url}")
    return True, douban_url


def douban_to_tmdb(douban_url: str, api_key: str = None) -> tuple[bool, str]:
    """
    通过豆瓣链接获取TMDb链接（通过IMDb中转）

    Args:
        douban_url: 豆瓣链接
        api_key: TMDB API Key

    Returns:
        tuple: (success, tmdb_url) 成功返回True和TMDb链接，失败返回False和空字符串
    """
    logger.info("豆瓣 -> TMDb转换（通过IMDb中转）")

    # 第一步：豆瓣 -> IMDb
    success, imdb_url = douban_to_imdb(douban_url)
    if not success:
        logger.error("豆瓣到IMDb转换失败，无法继续")
        return False, ""

    # 第二步：IMDb -> TMDb
    success, tmdb_url = imdb_to_tmdb(imdb_url, api_key)
    if not success:
        logger.error("IMDb到TMDb转换失败")
        return False, ""

    logger.info(f"成功转换: {douban_url} -> {tmdb_url}")
    return True, tmdb_url


# ============================================================================
# 统一转换函数
# ============================================================================


def convert_media_id(input_url: str, api_key: str = None) -> dict:
    """
    统一转换函数：输入任意一个平台的链接，返回所有三个平台的链接

    Args:
        input_url: 输入链接（IMDb、TMDb或豆瓣）
        api_key: TMDB API Key（可选）

    Returns:
        dict: 包含所有三个平台链接的字典
            {
                "imdb": "https://www.imdb.com/title/tt0137523/",
                "tmdb": "https://www.themoviedb.org/movie/550",
                "douban": "https://movie.douban.com/subject/1292052/",
                "success": True,
                "message": "转换成功"
            }
    """
    result = {"imdb": "", "tmdb": "", "douban": "", "success": False, "message": ""}

    if not input_url:
        result["message"] = "输入链接为空"
        return result

    # 识别输入类型
    if "imdb.com" in input_url:
        logger.info("识别到IMDb链接")
        result["imdb"] = input_url

        # 转换为TMDb
        success, tmdb_url = imdb_to_tmdb(input_url, api_key)
        if success:
            result["tmdb"] = tmdb_url

        # 转换为豆瓣
        success, douban_url = imdb_to_douban(input_url)
        if success:
            result["douban"] = douban_url

    elif "themoviedb.org" in input_url:
        logger.info("识别到TMDb链接")
        result["tmdb"] = input_url

        # 转换为IMDb
        success, imdb_url = tmdb_to_imdb(input_url, api_key)
        if success:
            result["imdb"] = imdb_url

        # 转换为豆瓣（通过IMDb中转）
        if result["imdb"]:
            success, douban_url = imdb_to_douban(result["imdb"])
            if success:
                result["douban"] = douban_url

    elif "douban.com" in input_url:
        logger.info("识别到豆瓣链接")
        result["douban"] = input_url

        # 转换为IMDb
        success, imdb_url = douban_to_imdb(input_url)
        if success:
            result["imdb"] = imdb_url

        # 转换为TMDb（通过IMDb中转）
        if result["imdb"]:
            success, tmdb_url = imdb_to_tmdb(result["imdb"], api_key)
            if success:
                result["tmdb"] = tmdb_url

    else:
        result["message"] = "无法识别的链接类型"
        return result

    # 检查结果
    if result["imdb"] or result["tmdb"] or result["douban"]:
        result["success"] = True
        result["message"] = "转换成功"

        # 统计成功转换的数量
        success_count = sum(1 for v in [result["imdb"], result["tmdb"], result["douban"]] if v)
        result["message"] = f"转换成功（{success_count}/3）"
    else:
        result["message"] = "转换失败"

    return result


# ============================================================================
# 测试代码
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("IMDb、TMDb、豆瓣 三平台媒体ID转换工具 - 测试")
    print("=" * 80)
    print()

    # 在这里设置要测试的ID（可以修改为任意有效的ID）
    # 默认使用《搏击俱乐部》的ID
    test_imdb_id = "tt35444710"
    test_tmdb_id = "1396965"
    test_douban_id = "36851291"

    print(f"测试配置:")
    print(f"  IMDb ID: {test_imdb_id}")
    print(f"  TMDb ID: {test_tmdb_id}")
    print(f"  豆瓣ID: {test_douban_id}")
    print()

    # 测试1：用IMDb ID获取TMDb和豆瓣链接
    print("=" * 80)
    print("【测试1】用IMDb ID获取其他平台链接")
    print("=" * 80)
    imdb_url = f"https://www.imdb.com/title/{test_imdb_id}/"
    print(f"输入: {imdb_url}")
    print()

    success, tmdb_url = imdb_to_tmdb(imdb_url)
    print(f"TMDb: {'✓' if success else '✗'} {tmdb_url}")

    success, douban_url = imdb_to_douban(imdb_url)
    print(f"豆瓣: {'✓' if success else '✗'} {douban_url}")
    print()

    # 测试2：用TMDb ID获取IMDb和豆瓣链接
    print("=" * 80)
    print("【测试2】用TMDb ID获取其他平台链接")
    print("=" * 80)
    tmdb_url = f"https://www.themoviedb.org/movie/{test_tmdb_id}"
    print(f"输入: {tmdb_url}")
    print()

    success, imdb_url = tmdb_to_imdb(tmdb_url)
    print(f"IMDb: {'✓' if success else '✗'} {imdb_url}")

    success, douban_url = tmdb_to_douban(tmdb_url)
    print(f"豆瓣: {'✓' if success else '✗'} {douban_url}")
    print()

    # 测试3：用豆瓣ID获取IMDb和TMDb链接
    print("=" * 80)
    print("【测试3】用豆瓣ID获取其他平台链接")
    print("=" * 80)
    douban_url = f"https://movie.douban.com/subject/{test_douban_id}/"
    print(f"输入: {douban_url}")
    print()

    success, imdb_url = douban_to_imdb(douban_url)
    print(f"IMDb: {'✓' if success else '✗'} {imdb_url}")

    success, tmdb_url = douban_to_tmdb(douban_url)
    print(f"TMDb: {'✓' if success else '✗'} {tmdb_url}")
    print()

    # 测试4：统一转换函数
    print("=" * 80)
    print("【测试4】统一转换函数 - 获取所有平台链接")
    print("=" * 80)

    # 从IMDb转换
    print("\n从IMDb转换:")
    result = convert_media_id(f"https://www.imdb.com/title/{test_imdb_id}/")
    print(f"  IMDb:   {result['imdb']}")
    print(f"  TMDb:   {result['tmdb']}")
    print(f"  豆瓣:   {result['douban']}")
    print(f"  状态:   {result['message']}")

    # 从TMDb转换
    print("\n从TMDb转换:")
    result = convert_media_id(f"https://www.themoviedb.org/movie/{test_tmdb_id}")
    print(f"  IMDb:   {result['imdb']}")
    print(f"  TMDb:   {result['tmdb']}")
    print(f"  豆瓣:   {result['douban']}")
    print(f"  状态:   {result['message']}")

    # 从豆瓣转换
    print("\n从豆瓣转换:")
    result = convert_media_id(f"https://movie.douban.com/subject/{test_douban_id}/")
    print(f"  IMDb:   {result['imdb']}")
    print(f"  TMDb:   {result['tmdb']}")
    print(f"  豆瓣:   {result['douban']}")
    print(f"  状态:   {result['message']}")

    print()
    print("=" * 80)
    print("测试完成")
    print("=" * 80)


# ============================================================================
# 兼容性函数（保持与原 imdb2tmdb.py 的兼容性）
# ============================================================================


def get_tmdb_url_from_any_source(
    imdb_link: str = "", douban_link: str = "", tmdb_link: str = "", api_key: str = None
) -> str:
    """
    从多个来源中获取TMDb链接（兼容原 imdb2tmdb.py 的函数）

    优先级：
    1. 直接的TMDb链接
    2. 通过IMDb链接转换
    3. 空字符串（转换失败）

    Args:
        imdb_link: IMDb链接
        douban_link: 豆瓣链接（暂不支持直接转换）
        tmdb_link: TMDb链接
        api_key: TMDB API Key

    Returns:
        str: TMDb链接
    """
    # 1. 优先使用直接的TMDb链接
    if tmdb_link and "themoviedb.org" in tmdb_link:
        logger.debug("使用直接的TMDb链接")
        return tmdb_link

    # 2. 尝试通过IMDb链接转换
    if imdb_link and "imdb.com" in imdb_link:
        logger.debug("尝试通过IMDb链接转换获取TMDb链接")
        success, tmdb_url = imdb_to_tmdb(imdb_link, api_key)
        if success:
            return tmdb_url

    # 3. 如果都没有，返回空字符串
    logger.warning("无法获取TMDb链接")
    return ""
