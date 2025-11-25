import re
import requests
from loguru import logger


def extract_imdb_id(imdb_url: str) -> str:
    """
    从IMDb链接中提取IMDb ID

    Args:
        imdb_url: IMDb链接，格式如 https://www.imdb.com/title/tt1234567/

    Returns:
        str: IMDb ID，如 tt1234567，如果提取失败返回空字符串
    """
    if not imdb_url:
        return ""

    # 匹配IMDb ID模式：tt后面跟着数字
    match = re.search(r'(tt\d+)', imdb_url)
    if match:
        imdb_id = match.group(1)
        logger.debug(f"从IMDb链接中提取到ID: {imdb_id}")
        return imdb_id

    logger.warning(f"无法从IMDb链接中提取ID: {imdb_url}")
    return ""


def imdb_to_tmdb(imdb_url: str, api_key: str = None) -> str:
    """
    通过IMDb链接获取TMDB链接

    Args:
        imdb_url: IMDb链接
        api_key: TMDB API Key，如果不提供则使用默认的

    Returns:
        str: TMDB链接，如果转换失败返回空字符串
    """
    # 提取IMDb ID
    imdb_id = extract_imdb_id(imdb_url)
    if not imdb_id:
        logger.error("无法提取IMDb ID，转换失败")
        return ""

    # 使用提供的API Key或默认的
    if not api_key:
        api_key = "0f79586eb9d92afa2b7266f7928b055c"
        logger.debug("使用默认TMDB API Key")

    # 构造TMDB API请求
    api_url = f"https://api.themoviedb.org/3/find/{imdb_id}?external_source=imdb_id&api_key={api_key}"

    try:
        logger.info(f"正在通过TMDB API查询IMDb ID: {imdb_id}")

        # 发送API请求，增加重试机制
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.get(api_url, timeout=30)
                response.raise_for_status()
                break
            except (requests.exceptions.RequestException,
                    requests.exceptions.SSLError) as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"TMDB API请求失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                    import time
                    time.sleep(2**attempt)  # 指数退避
                    continue
                else:
                    raise e

        data = response.json()

        # 检查电影结果
        movie_results = data.get("movie_results", [])
        if movie_results:
            movie = movie_results[0]
            tmdb_id = movie.get("id")
            title = movie.get("title", "")

            if tmdb_id:
                tmdb_url = f"https://www.themoviedb.org/movie/{tmdb_id}"
                logger.info(f"成功转换: {imdb_id} -> {title} -> {tmdb_url}")
                return tmdb_url, "movie"
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
                return tmdb_url, "tv"
            else:
                logger.error("TMDB响应中未找到ID")

        logger.warning(f"TMDB API未找到IMDb ID {imdb_id} 对应的内容")
        return ""

    except requests.exceptions.RequestException as e:
        logger.error(f"TMDB API请求失败: {e}")
        return ""
    except Exception as e:
        logger.error(f"IMDb到TMDB转换过程中发生错误: {e}")
        return ""


def get_tmdb_url_from_any_source(imdb_link: str = "",
                                 douban_link: str = "",
                                 tmdb_link: str = "",
                                 api_key: str = None):
    """
    从多个来源中获取TMDB链接

    优先级：
    1. 直接的TMDB链接
    2. 通过IMDb链接转换
    3. 空字符串（转换失败）

    Args:
        imdb_link: IMDb链接
        douban_link: 豆瓣链接（暂不支持直接转换）
        tmdb_link: TMDB链接
        api_key: TMDB API Key

    Returns:
        str: TMDB链接
    """
    # 1. 优先使用直接的TMDB链接
    if tmdb_link and "themoviedb.org" in tmdb_link:
        logger.debug("使用直接的TMDB链接")
        return tmdb_link

    # 2. 尝试通过IMDb链接转换
    if imdb_link and "imdb.com" in imdb_link:
        logger.debug("尝试通过IMDb链接转换获取TMDB链接")
        tmdb_url = imdb_to_tmdb(imdb_link, api_key)
        if tmdb_url:
            return tmdb_url

    # 3. 如果都没有，返回空字符串
    logger.warning("无法获取TMDB链接")
    return ValueError("无法获取TMDB链接")


# 测试函数
if __name__ == "__main__":
    # 测试IMDb ID提取
    test_imdb_url = "https://www.imdb.com/title/tt0983213/"
    imdb_id = extract_imdb_id(test_imdb_url)
    print(f"提取的IMDb ID: {imdb_id}")

    # 测试IMDb到TMDB转换
    tmdb_url = imdb_to_tmdb(test_imdb_url)
    print(f"转换的TMDB链接: {tmdb_url}")

    # 测试综合获取
    result, type = get_tmdb_url_from_any_source(imdb_link=test_imdb_url,
                                                tmdb_link="")
    print(f"最终TMDB链接: {type},{result}")
