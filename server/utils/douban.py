import logging
import requests
import re
import urllib.parse
import tempfile
import os
from config import config_manager
from utils import _convert_pixhost_url_to_direct


def call_api_with_fallback(api_path, params=None, method="GET", timeout=10):
    """
    调用API时支持主备域名切换的通用函数

    Args:
        api_path (str): API路径，如 '/?imdbid=tt9999999996'
        params (dict): 额外的请求参数
        method (str): HTTP方法，默认 'GET'
        timeout (int): 超时时间，默认 10 秒

    Returns:
        tuple: (success, response_data, error_message)
    """
    # 主备域名配置 - 替换子域名部分
    primary_domain = "https://pt-nexus-imdb2douban.sqing33.dpdns.org"
    fallback_domain = "https://pt-nexus-imdb2douban.1395251710.workers.dev"

    # 构建完整的URL列表
    urls = [f"{primary_domain}{api_path}", f"{fallback_domain}{api_path}"]

    for i, url in enumerate(urls):
        domain_name = "主域名" if i == 0 else "备用域名"
        try:
            logging.info(f"尝试使用{domain_name}: {url}")
            print(f"[*] 尝试使用{domain_name}: {url}")

            if method.upper() == "GET":
                response = requests.get(url, params=params, timeout=timeout)
            elif method.upper() == "POST":
                response = requests.post(url, params=params, timeout=timeout)
            else:
                raise ValueError(f"不支持的HTTP方法: {method}")

            if response.status_code == 200:
                try:
                    data = response.json()
                    logging.info(f"{domain_name}调用成功")
                    print(f"[*] {domain_name}调用成功")
                    return True, data, ""
                except ValueError:
                    # 如果不是JSON，返回文本内容
                    logging.info(f"{domain_name}调用成功（返回文本）")
                    print(f"[*] {domain_name}调用成功（返回文本）")
                    return True, response.text, ""
            else:
                error_msg = f"HTTP {response.status_code}"
                logging.warning(f"{domain_name}返回错误: {error_msg}")
                print(f"  [-] {domain_name}返回错误: {error_msg}")

        except requests.exceptions.SSLError as e:
            error_msg = f"SSL错误: {str(e)}"
            logging.error(f"{domain_name}SSL错误: {e}")
            print(f"  [!] {domain_name}SSL错误: {e}")
            if i == 0:  # 主域名失败，尝试备用域名
                print(f"[*] 主域名失败，尝试备用域名...")
                continue
            else:
                return False, None, error_msg
        except requests.exceptions.RequestException as e:
            error_msg = f"网络错误: {str(e)}"
            logging.error(f"{domain_name}网络错误: {e}")
            print(f"  [!] {domain_name}网络错误: {e}")
            if i == 0:  # 主域名失败，尝试备用域名
                print(f"[*] 主域名失败，尝试备用域名...")
                continue
            else:
                return False, None, error_msg
        except Exception as e:
            error_msg = f"未知错误: {str(e)}"
            logging.error(f"{domain_name}未知错误: {e}")
            print(f"  [!] {domain_name}未知错误: {e}")
            if i == 0:  # 主域名失败，尝试备用域名
                print(f"[*] 主域名失败，尝试备用域名...")
                continue
            else:
                return False, None, error_msg

    # 所有域名都失败
    return False, None, "所有API域名都无法访问"


def search_by_subtitle(subtitle):
    """
    根据副标题搜索IMDb或豆瓣链接

    Args:
        subtitle (str): 副标题

    Returns:
        tuple: (imdb_link, douban_link) 搜索到的链接元组
    """
    imdb_link = ""
    douban_link = ""

    if subtitle:
        # 使用多种分隔符分割标题，并尝试每个片段
        segments = re.split(r"[/|\\[\]()（）\[\]【】\s]+", subtitle)
        # 过滤掉太短的片段和明显不是片名的片段
        candidates = [
            seg.strip()
            for seg in segments
            if len(seg.strip()) > 1
            and not re.match(r"^(DIY|特效|简繁|字幕|原盘|BluRay|1080p|x264|x265).*$", seg, re.I)
        ]

        # 添加原始完整标题作为最后一个候选项
        candidates.append(subtitle)

        for candidate in candidates:
            if candidate:
                search_name = re.split(r"\s*[|/]\s*", candidate, 1)[0].strip()
                if search_name:
                    logging.info(f"未找到链接，尝试使用副标题 '{search_name}' 进行名称搜索...")
                    print(f"[*] 未找到链接，尝试使用副标题 '{search_name}' 进行名称搜索...")
                    try:
                        encoded_name = urllib.parse.quote_plus(search_name)
                        api_path = f"/?name={encoded_name}"

                        success, data, error_msg = call_api_with_fallback(api_path, timeout=10)
                        if success:
                            # data 可能是 dict 或 list
                            if isinstance(data, dict):
                                data = data.get("data", [])
                            elif isinstance(data, list):
                                data = data
                            if data and data[0]:
                                found_record = data[0]
                                found_imdb_id = found_record.get("imdbid")
                                found_douban_id = found_record.get("doubanid")

                                # 一次性获取两个链接
                                if found_imdb_id:
                                    imdb_link = f"https://www.imdb.com/title/{found_imdb_id}/"

                                if found_douban_id:
                                    douban_link = (
                                        f"https://movie.douban.com/subject/{found_douban_id}/"
                                    )

                                # 如果至少有一个链接被找到，就返回
                                if imdb_link or douban_link:
                                    logging.info(
                                        f"成功通过名称搜索补充链接: IMDb={imdb_link}, 豆瓣={douban_link}"
                                    )
                                    if imdb_link:
                                        print(f"  [+] 成功通过名称搜索补充 IMDb 链接: {imdb_link}")
                                    if douban_link:
                                        print(f"  [+] 成功通过名称搜索补充豆瓣链接: {douban_link}")
                                    return imdb_link, douban_link

                        else:
                            logging.warning(f"名称搜索 API 查询失败: {error_msg}")
                            print(f"  [-] 名称搜索 API 查询失败: {error_msg}")

                    except Exception as e:
                        logging.error(f"使用名称搜索时发生错误: {e}")
                        print(f"  [!] 使用名称搜索时发生错误: {e}")

    return imdb_link, douban_link


def handle_incomplete_links(imdb_link, douban_link, tmdb_link, subtitle):
    """
    当检测到 IMDb、豆瓣或 TMDb 链接不完整时，尝试使用远程 API 补充缺失的链接

    Args:
        imdb_link (str): 已有的 IMDb 链接
        douban_link (str): 已有的豆瓣链接
        tmdb_link (str): 已有的 TMDb 链接
        subtitle (str): 副标题（用于搜索）

    Returns:
        tuple: (imdb_link, douban_link, tmdb_link, use_tmdb_fallback) 补充后的链接元组和兜底标志
    """
    # 导入统一转换函数
    from utils.imdb2tmdb2douban import convert_media_id

    # 初始化兜底标志
    use_tmdb_fallback = False

    # 如果三个链接都缺失，尝试通过副标题搜索
    if not imdb_link and not douban_link and not tmdb_link:
        logging.info("未找到任何链接，尝试使用远程 API 补充...")
        print("未找到任何链接，尝试使用远程 API 补充...")

        # 尝试通过副标题搜索（保持原有逻辑）
        imdb_link, douban_link = search_by_subtitle(subtitle)

        # 如果获得了IMDb或豆瓣链接，再尝试获取TMDb链接
        if imdb_link or douban_link:
            result = convert_media_id(imdb_link or douban_link)
            if result["success"]:
                tmdb_link = result.get("tmdb", "")

        return imdb_link, douban_link, tmdb_link, use_tmdb_fallback

    # 如果没有豆瓣链接，尝试通过 TMDb 或 IMDb 获取豆瓣链接
    if not douban_link:
        # 优先使用 TMDb 链接，其次使用 IMDb 链接
        if tmdb_link:
            logging.info("没有豆瓣链接，尝试通过 TMDb 链接获取豆瓣链接...")
            print("没有豆瓣链接，尝试通过 TMDb 链接获取豆瓣链接...")

            result = convert_media_id(tmdb_link)
            if result["success"] and result.get("douban"):
                douban_link = result["douban"]
                logging.info(f"✅ 成功通过TMDb链接获取豆瓣链接: {douban_link}")
                print(f"  [+] 成功通过TMDb链接获取豆瓣链接: {douban_link}")
        elif imdb_link:
            logging.info("没有豆瓣链接，尝试通过 IMDb 链接获取豆瓣链接...")
            print("没有豆瓣链接，尝试通过 IMDb 链接获取豆瓣链接...")

            result = convert_media_id(imdb_link)
            if result["success"] and result.get("douban"):
                douban_link = result["douban"]
                logging.info(f"✅ 成功通过IMDb链接获取豆瓣链接: {douban_link}")
                print(f"  [+] 成功通过IMDb链接获取豆瓣链接: {douban_link}")
            else:
                # 如果通过 IMDb 获取豆瓣链接失败，设置使用 TMDB 兜底
                logging.warning("通过IMDb链接获取豆瓣链接失败，将使用TMDB作为兜底方案")
                print("  [-] 通过IMDb链接获取豆瓣链接失败，将使用TMDB作为兜底方案")
                use_tmdb_fallback = True

    # 使用统一转换函数补充缺失的链接
    input_url = imdb_link or douban_link or tmdb_link

    if input_url:
        logging.info("检测到链接不完整，尝试使用远程 API 补充...")
        print("检测到链接不完整，尝试使用远程 API 补充...")

        result = convert_media_id(input_url)

        if result["success"]:
            # 补充缺失的链接
            if not imdb_link and result.get("imdb"):
                imdb_link = result["imdb"]
                logging.info(f"✅ 成功补充IMDb链接: {imdb_link}")
                print(f"  [+] 成功补充IMDb链接: {imdb_link}")

            if not douban_link and result.get("douban"):
                douban_link = result["douban"]
                logging.info(f"✅ 成功补充豆瓣链接: {douban_link}")
                print(f"  [+] 成功补充豆瓣链接: {douban_link}")

            if not tmdb_link and result.get("tmdb"):
                tmdb_link = result["tmdb"]
                logging.info(f"✅ 成功补充TMDb链接: {tmdb_link}")
                print(f"  [+] 成功补充TMDb链接: {tmdb_link}")
        else:
            logging.warning(f"API转换失败: {result.get('message')}")
            print(f"  [-] API转换失败: {result.get('message')}")

    return imdb_link, douban_link, tmdb_link, use_tmdb_fallback


def upload_data_movie_info(
    media_type: str, douban_link: str, imdb_link: str, tmdb_link: str = "", subtitle: str = ""
):
    """
    通过多个PT-Gen API获取电影信息的完整内容，包括海报、简介和IMDb链接。
    支持从豆瓣链接、IMDb链接或TMDb链接获取信息，失败时自动切换API。
    返回: (状态, 海报, 简介, IMDb链接, 豆瓣链接, TMDb链接)
    """
    # 如果缺失链接，尝试使用远程API补充
    use_tmdb_fallback = False  # 初始化兜底标志
    if not douban_link or not imdb_link or not tmdb_link:
        print("检测到缺失链接，尝试通过远程API补充...")
        new_imdb_link, new_douban_link, new_tmdb_link, use_tmdb_fallback = handle_incomplete_links(
            imdb_link, douban_link, tmdb_link, subtitle
        )

        if new_imdb_link or new_douban_link or new_tmdb_link:
            imdb_link = new_imdb_link or imdb_link
            douban_link = new_douban_link or douban_link
            tmdb_link = new_tmdb_link or tmdb_link
            print(f"成功补充链接: IMDb={imdb_link}, 豆瓣={douban_link}, TMDb={tmdb_link}")
        else:
            print("未能补充任何链接")

    # 过滤豆瓣链接，只保留完整的 subject URL 部分
    if douban_link:
        douban_match = re.match(r"(https?://movie\.douban\.com/subject/\d+)", douban_link)
        if douban_match:
            douban_link = douban_match.group(1)
            print(f"🔗 已过滤豆瓣链接: {douban_link}")
        else:
            print("⚠️  警告: 提供的豆瓣链接格式无效。")
            douban_link = ""

    # 从配置文件获取财神ptgen的token
    config = config_manager.get()
    cspt_token = config.get("cross_seed", {}).get("cspt_ptgen_token", "")

    # API配置列表，按优先级排序
    api_configs = [
        {
            "name": "pt-nexus-ptgen.sqing33.dpdns.org",
            "base_url": "https://pt-nexus-ptgen.sqing33.dpdns.org",
            "type": "refactor_url_format",
        },
        {
            "name": "ptgen.tju.pt",
            "base_url": "https://ptgen.tju.pt/infogen",
            "type": "tju_format",
            "force_douban": True,  # 强制使用site=douban模式
        },
        {
            "name": "ptgen.homeqian.top",
            "base_url": "https://ptgen.homeqian.top",
            "type": "url_format",
        },
        {
            "name": "api.iyuu.cn",
            "base_url": "https://api.iyuu.cn/App Movie.Ptgen",
            "type": "iyuu_format",
        },
    ]

    # 如果配置了财神ptgen的token，则将其添加到API配置列表的最前面
    if cspt_token:
        api_configs.insert(
            0,
            {
                "name": "cspt.top",
                "base_url": "https://cspt.top/api/ptgen/query",
                "type": "cspt_format",
                "token": cspt_token,
            },
        )

    # 确定要使用的资源URL（优先级：豆瓣 > TMDb > IMDb）
    if not douban_link and not tmdb_link and not imdb_link:
        error_msg = "未提供豆瓣、TMDb或IMDb链接。"
        return False, error_msg, error_msg, "", "", ""

    # 确保返回的链接是完整的
    final_douban_link = douban_link
    final_imdb_link = imdb_link
    final_tmdb_link = tmdb_link

    # 判断是否有豆瓣链接
    if douban_link:
        # 有豆瓣链接，尝试豆瓣 API
        last_error = ""
        for api_config in api_configs:
            try:
                print(f"尝试使用API: {api_config['name']}")

                if api_config["type"] == "cspt_format":
                    # CSPT格式API (cspt.top)
                    success, poster, description, imdb_link_result = _call_cspt_format_api(
                        api_config, douban_link, imdb_link, tmdb_link, media_type
                    )
                elif api_config["type"] == "tju_format":
                    # TJU格式API (ptgen.tju.pt) - 强制使用豆瓣模式
                    success, poster, description, imdb_link_result = _call_tju_format_api(
                        api_config, douban_link, imdb_link, tmdb_link, media_type
                    )
                elif api_config["type"] == "refactor_url_format":
                    # 新的URL格式API (pt-nexus-ptgen.sqing33.dpdns.org)
                    success, poster, description, imdb_link_result = _call_refactor_url_format_api(
                        api_config, douban_link, imdb_link, tmdb_link, media_type
                    )
                elif api_config["type"] == "url_format":
                    # URL格式API (workers.dev, homeqian.top)
                    success, poster, description, imdb_link_result = _call_url_format_api(
                        api_config, douban_link, imdb_link, tmdb_link, media_type
                    )
                elif api_config["type"] == "iyuu_format":
                    # IYUU格式API (api.iyuu.cn)
                    success, poster, description, imdb_link_result = _call_iyuu_format_api(
                        api_config, douban_link, imdb_link, tmdb_link, media_type
                    )
                else:
                    continue

                if success:
                    print(f"API {api_config['name']} 调用成功")
                    # 更新最终链接，如果API返回了新的链接
                    if imdb_link_result:
                        final_imdb_link = imdb_link_result
                        # 如果之前没有豆瓣链接或TMDb链接，尝试从新的IMDb链接补全
                        if not final_douban_link or not final_tmdb_link:
                            _, new_douban_link, new_tmdb_link, _ = handle_incomplete_links(
                                final_imdb_link, "", "", subtitle
                            )
                            if new_douban_link:
                                final_douban_link = new_douban_link
                            if new_tmdb_link:
                                final_tmdb_link = new_tmdb_link

                    return (
                        True,
                        poster,
                        description,
                        final_imdb_link,
                        final_douban_link,
                        final_tmdb_link,
                    )
                else:
                    last_error = description  # 错误信息存储在description中
                    print(f"API {api_config['name']} 返回失败: {last_error}")

            except Exception as e:
                last_error = f"API {api_config['name']} 请求异常: {e}"
                print(last_error)
                continue

        # 豆瓣相关 PTGen 全部失败时，切换为 TMDb 方案兜底（使用现成 TMDb 方法生成简介/海报等）
        print("豆瓣 PTGen API 全部失败，尝试使用 TMDb 兜底获取信息...")
        try:
            from utils.imdb2tmdb2douban import get_tmdb_url_from_any_source

            if not final_tmdb_link:
                final_tmdb_link = get_tmdb_url_from_any_source(
                    imdb_link=final_imdb_link,
                    douban_link=final_douban_link,
                    tmdb_link=final_tmdb_link,
                )
        except Exception as e:
            print(f"[!] 获取 TMDb 链接失败，将继续尝试 TMDb 兜底: {e}")

        success, poster, description, imdb_link_result = _call_tmdb_format_api(
            {"name": "tmdb_api", "base_url": "https://api.tmdb.org", "type": "tmdb_format"},
            final_douban_link,
            final_imdb_link,
            final_tmdb_link,
            media_type,
        )

        if success:
            print("TMDb 兜底调用成功")
            if imdb_link_result:
                final_imdb_link = imdb_link_result

            # 确保返回的 TMDb 链接尽量完整
            if not final_tmdb_link:
                try:
                    from utils.imdb2tmdb2douban import get_tmdb_url_from_any_source

                    final_tmdb_link = get_tmdb_url_from_any_source(imdb_link=final_imdb_link)
                except Exception:
                    pass

            return True, poster, description, final_imdb_link, final_douban_link, final_tmdb_link

        # TMDb 兜底也失败，保留错误信息
        if description:
            last_error = description
        print(f"TMDb 兜底返回失败: {last_error}")
    else:
        # 没有豆瓣链接，直接使用 TMDb API
        print("没有豆瓣链接，直接使用 TMDb API 获取信息...")
        success, poster, description, imdb_link_result = _call_tmdb_format_api(
            {"name": "tmdb_api", "base_url": "https://api.tmdb.org", "type": "tmdb_format"},
            douban_link,
            imdb_link,
            tmdb_link,
            media_type,
        )

        if success:
            print(f"TMDb API 调用成功")
            if imdb_link_result:
                final_imdb_link = imdb_link_result
            return True, poster, description, final_imdb_link, final_douban_link, final_tmdb_link
        else:
            last_error = description
            print(f"TMDb API 返回失败: {last_error}")

    error_msg = last_error or "获取影片信息失败"
    return False, error_msg, error_msg, final_imdb_link, final_douban_link, final_tmdb_link


def _call_cspt_format_api(
    api_config: dict, douban_link: str, imdb_link: str, tmdb_link: str, media_type: str
):
    """
    调用CSPT格式API (cspt.top)
    API格式: https://cspt.top/api/ptgen/query/{token}?url=https://movie.douban.com/subject/2254648/
    优先级: 豆瓣 > TMDb > IMDb
    """
    try:
        # 优先级：豆瓣 > TMDb > IMDb
        resource_url = douban_link or tmdb_link or imdb_link
        if not resource_url:
            return False, "", "未提供豆瓣、TMDb或IMDb链接", ""

        token = api_config.get("token", "")
        if not token:
            return False, "", "未配置财神ptgen token", ""

        url = f"{api_config['base_url']}/{token}?url={resource_url}"

        response = requests.get(url, timeout=30)
        response.raise_for_status()

        # 尝试解析为JSON
        try:
            data = response.json()
        except:
            # 如果不是JSON，可能是直接返回的文本格式
            text_content = response.text.strip()
            if text_content and (
                "[img]" in text_content or "◎" in text_content or "❁" in text_content
            ):
                # 直接返回文本内容作为format
                return _parse_format_content(text_content, media_type)
            else:
                return False, "", "API返回了无效的内容格式", ""

        # JSON格式处理
        if isinstance(data, dict):
            # 检查是否有错误
            if data.get("success") is False:
                error_msg = data.get("message", data.get("error", "未知错误"))
                return False, "", f"API返回失败: {error_msg}", ""

            # 获取格式化内容
            format_data = data.get("format", data.get("content", ""))
            if format_data:
                return _parse_format_content(format_data, data.get("imdb_link", ""), media_type)
            else:
                return False, "", "API未返回有效的格式化内容", ""
        else:
            return False, "", "API返回了无效的数据格式", ""

    except Exception as e:
        return False, "", f"CSPT格式API调用失败: {e}", ""


def _call_tju_format_api(
    api_config: dict, douban_link: str, imdb_link: str, tmdb_link: str, media_type: str
):
    """
    调用TJU格式API (ptgen.tju.pt) - 强制使用site=douban模式
    优先级: 豆瓣 > TMDb > IMDb
    """
    try:
        # 强制使用site=douban，这样IMDb/TMDb链接也会被转换查询豆瓣
        if douban_link:
            # 从豆瓣链接提取ID
            douban_id = _extract_douban_id(douban_link)
            if douban_id:
                url = f"{api_config['base_url']}?site=douban&sid={douban_id}"
            else:
                raise ValueError("无法从豆瓣链接提取ID")
        elif tmdb_link:
            # 从TMDb链接提取ID，但强制使用douban模式
            tmdb_id = _extract_tmdb_id(tmdb_link)
            if tmdb_id:
                url = f"{api_config['base_url']}?site=douban&sid={tmdb_id}"
            else:
                raise ValueError("无法从TMDb链接提取ID")
        elif imdb_link:
            # 从IMDb链接提取ID，但强制使用douban模式
            imdb_id = _extract_imdb_id(imdb_link)
            if imdb_id:
                url = f"{api_config['base_url']}?site=douban&sid={imdb_id}"
            else:
                raise ValueError("无法从IMDb链接提取ID")
        else:
            raise ValueError("没有可用的链接")

        response = requests.get(url, timeout=30)
        response.raise_for_status()

        data = response.json()

        if not data.get("success", False):
            error_msg = data.get("error", "未知错误")
            return False, "", f"API返回失败: {error_msg}", ""

        format_data = data.get("format", "")
        if not format_data:
            return False, "", "API未返回有效的格式化内容", ""

        # 提取信息
        extracted_imdb_link = data.get("imdb_link", "")
        poster = ""
        description = ""

        # 提取海报图片并进行智能处理
        if media_type != "intro":
            img_match = re.search(r"\[img\](.*?)\[/img\]", format_data)
            if img_match:
                original_poster_url = img_match.group(1)
                # 先替换域名为img9
                original_poster_url = re.sub(r"img1", "img9", original_poster_url)
                # 使用海报处理函数进行智能验证和转存
                poster = _process_poster_url(original_poster_url)

        # 提取简介内容（去除海报部分）
        description = re.sub(r"\[img\].*?\[/img\]", "", format_data).strip()
        description = re.sub(r"\n{3,}", "\n\n", description)

        # 校验简介完整性
        if description:
            completeness_check = check_intro_completeness(description)
            if not completeness_check["is_complete"]:
                print(f"  [!] 简介不完整，缺失字段: {completeness_check['missing_fields']}")
                print(f"  [*] 已找到字段: {completeness_check['found_fields']}")

        return True, poster, description, extracted_imdb_link

    except Exception as e:
        return False, "", f"TJU格式API调用失败: {e}", ""


def _call_url_format_api(
    api_config: dict, douban_link: str, imdb_link: str, tmdb_link: str, media_type: str
):
    """
    调用URL格式API (workers.dev, homeqian.top)
    优先级: 豆瓣 > TMDb > IMDb
    """
    try:
        # 根据API名称确定使用的参数格式
        base_url = api_config["base_url"]
        api_name = api_config.get("name", "")

        # 默认使用URL参数方式（优先级：豆瓣 > TMDb > IMDb）
        if douban_link:
            resource_url = douban_link
        elif tmdb_link:
            resource_url = tmdb_link
        elif imdb_link:
            resource_url = imdb_link
        else:
            return False, "", "未提供豆瓣、TMDb或IMDb链接", ""

        # 对于特定API，尝试使用不同的参数方式
        if "pt-nexus-ptgen.sqing33.dpdns.org" in api_name or "pt-nexus-ptgen" in api_name:
            # 使用 /api?url= 格式
            if base_url.endswith("/api"):
                url = f"{base_url}?url={resource_url}"
            else:
                # 检查是否需要使用/api端点
                url = f"{base_url}/api?url={resource_url}"
        else:
            # 默认格式
            url = f"{base_url}/?url={resource_url}"

        response = requests.get(url, timeout=30)
        response.raise_for_status()

        # 尝试解析为JSON
        try:
            data = response.json()
        except:
            # 如果不是JSON，可能是直接返回的文本格式
            text_content = response.text.strip()
            if text_content and (
                "[img]" in text_content or "◎" in text_content or "❁" in text_content
            ):
                # 直接返回文本内容作为format
                return _parse_format_content(text_content, imdb_link, media_type)
            else:
                return False, "", "API返回了无效的内容格式", ""

        # JSON格式处理
        if isinstance(data, dict):
            # 检查是否有错误
            if data.get("success") is False:
                error_msg = data.get("message", data.get("error", "未知错误"))
                return False, "", f"API返回失败: {error_msg}", ""

            # 获取格式化内容
            format_data = data.get("format", data.get("content", ""))
            if format_data:
                return _parse_format_content(format_data, data.get("imdb_link", ""), media_type)
            else:
                return False, "", "API未返回有效的格式化内容", ""
        else:
            return False, "", "API返回了无效的数据格式", ""

    except Exception as e:
        return False, "", f"URL格式API调用失败: {e}", ""


def call_ptgen_api_with_fallback(base_url: str, resource_url: str, method="POST", timeout=30):
    """
    调用PTGen API时支持主备域名切换的通用函数

    Args:
        base_url (str): API基础URL
        resource_url (str): 资源URL
        method (str): HTTP方法，默认 'POST'
        timeout (int): 超时时间，默认 30 秒

    Returns:
        tuple: (success, response_data, error_message)
    """
    # 主备域名配置 - 替换子域名部分
    if "pt-nexus-ptgen.sqing33.dpdns.org" in base_url:
        primary_base = "https://pt-nexus-ptgen.sqing33.dpdns.org"
        fallback_base = "https://pt-nexus-ptgen.1395251710.workers.dev"
    else:
        # 其他API不使用备用域名
        primary_base = base_url
        fallback_base = None

    # 构造API URL
    if not primary_base.endswith("/api"):
        primary_url = f"{primary_base}/api?url={resource_url}"
    else:
        primary_url = f"{primary_base}?url={resource_url}"

    urls_to_try = [primary_url]

    # 如果有备用域名，添加备用URL
    if fallback_base:
        if not fallback_base.endswith("/api"):
            fallback_url = f"{fallback_base}/api?url={resource_url}"
        else:
            fallback_url = f"{fallback_base}?url={resource_url}"
        urls_to_try.append(fallback_url)

    for i, url in enumerate(urls_to_try):
        domain_name = "主域名" if i == 0 else "备用域名"
        try:
            print(f"[*] 尝试使用{domain_name}: {url}")

            if method.upper() == "POST":
                response = requests.post(url, timeout=timeout)
            else:
                response = requests.get(url, timeout=timeout)

            print(f"[*] API响应状态码: {response.status_code}")

            if response.status_code == 200:
                try:
                    data = response.json()
                    print(f"{domain_name}调用成功")
                    return True, data, ""
                except ValueError:
                    # 如果不是JSON，返回文本内容
                    text_content = response.text.strip()
                    print(f"{domain_name}返回文本内容")
                    return True, text_content, ""
            else:
                error_msg = f"HTTP {response.status_code}"
                print(f"{domain_name}返回错误: {error_msg}")

        except requests.exceptions.SSLError as e:
            error_msg = f"SSL错误: {str(e)}"
            print(f"[!] {domain_name}SSL错误: {e}")
            if i == 0 and fallback_base:  # 主域名失败，尝试备用域名
                continue
            else:
                return False, None, error_msg
        except requests.exceptions.RequestException as e:
            error_msg = f"网络错误: {str(e)}"
            print(f"[!] {domain_name}网络错误: {e}")
            if i == 0 and fallback_base:  # 主域名失败，尝试备用域名
                continue
            else:
                return False, None, error_msg
        except Exception as e:
            error_msg = f"未知错误: {str(e)}"
            print(f"[!] {domain_name}未知错误: {e}")
            if i == 0 and fallback_base:  # 主域名失败，尝试备用域名
                continue
            else:
                return False, None, error_msg

    # 所有域名都失败
    return False, None, "所有PTGen API域名都无法访问"


def _call_refactor_url_format_api(
    api_config: dict, douban_link: str, imdb_link: str, tmdb_link: str, media_type: str
):
    """
    调用新的URL格式API (pt-nexus-ptgen.sqing33.dpdns.org)
    只使用URL 参数方式（前后端一起部署）:
    /api?url=https://movie.douban.com/subject/9999999996/
    /api?url=https://www.themoviedb.org/movie/9999999996
    /api?url=https://www.imdb.com/title/tt9999999996/

    优先级: 豆瓣 > TMDb > IMDb
    """
    try:
        base_url = api_config["base_url"]

        # 确定资源URL（优先级：豆瓣 > TMDb > IMDb）
        resource_url = None
        if douban_link:
            resource_url = douban_link
        elif tmdb_link:
            resource_url = tmdb_link
        elif imdb_link:
            resource_url = imdb_link
        else:
            return False, "", "未提供豆瓣、TMDb或IMDb链接", ""

        # 使用备用域名机制调用API
        success, data, error_msg = call_ptgen_api_with_fallback(
            base_url, resource_url, method="POST", timeout=30
        )

        if not success:
            print(f"[!] 新的URL格式API调用失败: {error_msg}")
            return False, "", f"新的URL格式API调用失败: {error_msg}", ""

        # 尝试解析响应
        if isinstance(data, str):
            # 文本格式响应
            text_content = data.strip()
            print(f"[*] API返回文本内容: {text_content}")
            if text_content and (
                "[img]" in text_content or "◎" in text_content or "❁" in text_content
            ):
                # 直接返回文本内容作为format
                print("[*] 使用API返回的文本内容作为格式化数据")
                return _parse_format_content(text_content, imdb_link, media_type)
            else:
                print("[!] API返回了无效的内容格式")
                return False, "", "API返回了无效的内容格式", ""
        else:
            # JSON格式响应
            print("[*] 解析JSON响应成功")

        # JSON格式处理
        if isinstance(data, dict):
            # 检查是否有错误
            if not data.get("success", True):  # 默认认为成功，除非明确指定失败
                error_msg = data.get("message", data.get("error", "未知错误"))
                print(f"[!] API返回失败: {error_msg}")
                return False, "", f"API返回失败: {error_msg}", ""

            # 获取格式化内容 - 支持多层嵌套
            format_data = (
                data.get("format")
                or data.get("data", {}).get("format")
                or data.get("content")
                or ""
            )

            if format_data:
                imdb_link = data.get("imdb_link") or data.get("data", {}).get("imdb_link") or ""
                return _parse_format_content(format_data, imdb_link, media_type)
            else:
                print("[!] API未返回有效的格式化内容")
                return False, "", "API未返回有效的格式化内容", ""
        else:
            print("[!] API返回了无效的数据格式")
            return False, "", "API返回了无效的数据格式", ""

    except Exception as e:
        print(f"[!] 新的URL格式API调用失败: {e}")
        return False, "", f"新的URL格式API调用失败: {e}", ""


def _call_iyuu_format_api(
    api_config: dict, douban_link: str, imdb_link: str, tmdb_link: str, media_type: str
):
    """
    调用IYUU格式API (api.iyuu.cn)
    优先级: 豆瓣 > TMDb > IMDb
    """
    try:
        # 优先级：豆瓣 > TMDb > IMDb
        resource_url = douban_link or tmdb_link or imdb_link
        url = f"{api_config['base_url']}?url={resource_url}"

        response = requests.get(url, timeout=30)
        response.raise_for_status()

        data = response.json()

        # 检查业务状态码
        if data.get("ret") != 200 and data.get("ret") != 0:
            error_msg = data.get("msg", "未知错误")
            return False, "", f"API返回错误(状态码{data.get('ret')}): {error_msg}", ""

        format_data = data.get("format") or data.get("data", {}).get("format", "")
        if not format_data:
            return False, "", "API未返回有效的简介内容", ""

        return _parse_format_content(format_data, imdb_link, media_type)

    except Exception as e:
        return False, "", f"IYUU格式API调用失败: {e}", ""


def _process_poster_url(
    original_poster_url: str, imdb_link: str = "", douban_link: str = ""
) -> str:
    """
    处理海报URL：检查是否为pixhost，如果不是则进行智能验证和转存

    :param original_poster_url: 原始海报URL
    :return: 处理后的海报URL（带[img]标签），失败返回空字符串
    """
    if not original_poster_url:
        return ""

    # 检查是否已经是pixhost图床
    if (
        "pixhost.to" in original_poster_url
        or "img1.pixhost.to" in original_poster_url
        or "img2.pixhost.to" in original_poster_url
    ):
        # 已经是pixhost，直接使用
        print(f"[*] 海报已是pixhost图床，直接使用: {original_poster_url}")
        return f"[img]{original_poster_url}[/img]"
    else:
        # 非pixhost，进行智能验证和转存
        print(f"[*] 海报非pixhost图床，执行智能验证和转存...")
        smart_poster_url = _get_smart_poster_url(original_poster_url, imdb_link, douban_link)

        if smart_poster_url:
            print(f"[*] 智能验证和转存成功: {smart_poster_url}")
            return f"[img]{smart_poster_url}[/img]"
        else:
            # 智能获取失败，保留原URL
            print(f"[*] 智能验证失败，使用原始URL")
            return f"[img]{original_poster_url}[/img]"


def _parse_format_content(format_data: str, provided_imdb_link: str = "", media_type: str = ""):
    """
    解析格式化内容,提取海报、简介和IMDb链接
    自动对海报进行智能验证和转存到pixhost
    """
    try:
        # 提取信息
        extracted_imdb_link = provided_imdb_link
        poster = ""
        description = ""

        # 如果没有提供IMDb链接，尝试从格式化内容中提取
        if not extracted_imdb_link:
            imdb_match = re.search(
                r"[◎❁]IMDb链接\s*(https?://www\.imdb\.com/title/tt\d+/)", format_data
            )
            if imdb_match:
                extracted_imdb_link = imdb_match.group(1)

        # 提取海报图片并进行智能验证和转存
        img_match = re.search(r"\[img\](.*?)\[/img\]", format_data)
        if img_match:
            poster = img_match.group(1)
            # 使用新的海报处理函数
            if media_type != "intro":
                poster = _process_poster_url(poster)

        # 提取简介内容（去除海报部分）
        description = re.sub(r"\[img\].*?\[/img\]", "", format_data).strip()
        description = re.sub(r"\n{3,}", "\n\n", description)

        # 校验简介完整性
        if description:
            completeness_check = check_intro_completeness(description)
            if not completeness_check["is_complete"]:
                print(f"  [!] 简介不完整，缺失字段: {completeness_check['missing_fields']}")
                print(f"  [*] 已找到字段: {completeness_check['found_fields']}")

        return True, poster, description, extracted_imdb_link

    except Exception as e:
        return False, "", f"解析格式化内容失败: {e}", ""


def _extract_douban_id(douban_link: str) -> str:
    """
    从豆瓣链接中提取ID
    例如: https://movie.douban.com/subject/34832354/ -> 34832354
    """
    match = re.search(r"/subject/(\d+)", douban_link)
    return match.group(1) if match else ""


def _extract_imdb_id(imdb_link: str) -> str:
    """
    从IMDb链接中提取ID
    例如: https://www.imdb.com/title/tt13721828/ -> tt13721828
    """
    match = re.search(r"/title/(tt\d+)", imdb_link)
    return match.group(1) if match else ""


def _extract_tmdb_id(tmdb_link: str) -> str:
    """
    从TMDb链接中提取ID
    例如: https://www.themoviedb.org/movie/507562 -> 507562
    """
    match = re.search(r"/movie/(\d+)", tmdb_link)
    return match.group(1) if match else ""


def _get_smart_poster_url(original_url: str, imdb_link: str = "", douban_link: str = "") -> str:
    """
    智能海报URL获取和验证，并自动转存到pixhost
    参考油猴插件逻辑：
    1. 优先尝试豆瓣官方高清图（多域名轮询 img1-img9）
    2. 尝试两种清晰度路径（l_ratio_poster 高清，m_ratio_poster 中清）
    3. 如果豆瓣全失败，尝试第三方托管（dou.img.lithub.cc）
    4. 验证成功后自动转存到pixhost

    :param original_url: 原始海报URL
    :return: pixhost直链URL，失败返回空字符串
    """
    if not original_url:
        return ""

    print(f"[*] 开始验证海报链接...")
    print(f"[*] 检测到非pixhost图片，执行智能海报获取...")
    print(f"开始智能海报URL验证: {original_url}")

    # 检查是否为豆瓣图片
    douban_match = re.search(r"https?://img(\d+)\.doubanio\.com.*?/(p\d+)", original_url)

    if douban_match:
        original_domain_num = douban_match.group(1)
        image_id = douban_match.group(2)

        print(f"检测到豆瓣图片: 域名img{original_domain_num}, 图片ID={image_id}")

        # 生成候选URL列表
        candidates = []

        # 优先原始域名
        domain_numbers = [original_domain_num]
        # 添加其他域名1-9
        for i in range(1, 10):
            if str(i) != original_domain_num:
                domain_numbers.append(str(i))

        # 路径优先级：先高清，后中清
        paths = [
            "view/photo/l_ratio_poster/public",  # 高清
            "view/photo/m_ratio_poster/public",  # 中清
        ]

        # 生成候选URL矩阵
        for domain_num in domain_numbers:
            for path in paths:
                candidate_url = f"https://img{domain_num}.doubanio.com/{path}/{image_id}.jpg"
                candidates.append(candidate_url)

        print(f"生成 {len(candidates)} 个候选URL")

        # 依次验证候选URL
        for i, candidate_url in enumerate(candidates):
            domain_info = re.search(r"img(\d+)\.doubanio\.com", candidate_url)
            path_info = "高清" if "l_ratio_poster" in candidate_url else "中清"
            domain_num = domain_info.group(1) if domain_info else "?"

            print(f"测试 [{i+1}/{len(candidates)}] img{domain_num} ({path_info}): {candidate_url}")

            if _validate_image_url(candidate_url):
                print(f"✓ 验证成功！使用 img{domain_num} 域名")
                print(f"[*] 智能海报获取成功: {candidate_url}")

                # 转存到pixhost
                pixhost_url = _transfer_poster_to_pixhost(candidate_url)
                if pixhost_url:
                    return pixhost_url
                else:
                    print("[!] pixhost转存失败，使用原始验证URL")
                    return candidate_url
            else:
                print(f"✗ img{domain_num} 验证失败")

        # 豆瓣全部失败，尝试第三方托管
        print("豆瓣官方图片全部失败，尝试第三方托管...")

        # 从原始URL中提取豆瓣ID
        douban_id_match = re.search(r"/subject/(\d+)", original_url)
        if not douban_id_match:
            # 尝试从图片ID推测（这通常不可行，但作为备选）
            print("无法提取豆瓣ID，跳过第三方托管")
        else:
            douban_id = douban_id_match.group(1)
            third_party_url = f"https://dou.img.lithub.cc/movie/{douban_id}.jpg"
            print(f"测试第三方URL: {third_party_url}")

            if _validate_image_url(third_party_url):
                print("✓ 第三方URL验证成功")
                print(f"[*] 智能海报获取成功: {third_party_url}")

                # 转存到pixhost
                pixhost_url = _transfer_poster_to_pixhost(third_party_url)
                if pixhost_url:
                    return pixhost_url
                else:
                    print("[!] pixhost转存失败，使用原始验证URL")
                    return third_party_url
            else:
                print("✗ 第三方URL验证失败")

    else:
        # 非豆瓣图片，直接验证原始URL
        print("非豆瓣图片，直接验证原始URL")
        if _validate_image_url(original_url):
            print("✓ 原始URL验证成功")
            print(f"[*] 智能海报获取成功: {original_url}")

            # 转存到pixhost
            pixhost_url = _transfer_poster_to_pixhost(original_url)
            if pixhost_url:
                return pixhost_url
            else:
                print("[!] pixhost转存失败，使用原始验证URL")
                return original_url
        else:
            print("✗ 原始URL验证失败，使用 ptgen 获取海报")
            (
                status,
                poster,
                description,
                final_imdb_link,
                final_douban_link,
                _,
            ) = upload_data_movie_info("", douban_link, imdb_link)
            if status and poster:
                return _process_poster_url(poster, final_imdb_link, final_douban_link)
            else:
                print("✗ 使用 ptgen 获取海报失败，返回原始URL")

                return original_url

    print("所有URL验证都失败")
    return ""


def _validate_image_url(url: str) -> bool:
    """
    验证图片URL是否有效
    使用HEAD请求验证URL是否可访问且返回有效图片

    :param url: 图片URL
    :return: URL有效返回True，否则返回False
    """
    if not url:
        return False

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Referer": "https://movie.douban.com/",
        }

        response = requests.head(url, headers=headers, timeout=10, allow_redirects=True)

        if response.status_code == 200:
            # 检查Content-Type
            content_type = response.headers.get("Content-Type", "").lower()
            if "image/" in content_type:
                # 检查Content-Length（至少大于1KB）
                content_length = response.headers.get("Content-Length")
                if content_length:
                    file_size = int(content_length)
                    if file_size > 1024:
                        return True
                    else:
                        print(f"   文件太小: {file_size} bytes")
                        return False
                else:
                    # 如果没有Content-Length，认为有效
                    return True
            else:
                print(f"   无效的Content-Type: {content_type}")
                return False
        else:
            print(f"   HTTP状态码: {response.status_code}")
            return False

    except Exception as e:
        print(f"   验证异常: {type(e).__name__}")
        return False


def _transfer_poster_to_pixhost(poster_url: str) -> str:
    """
    将海报图片转存到pixhost

    :param poster_url: 海报图片URL
    :return: pixhost直链URL，失败返回空字符串
    """
    if not poster_url:
        return ""

    print(f"开始转存海报到pixhost: {poster_url}")

    try:
        # 1. 下载图片到临时文件
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Referer": "https://movie.douban.com/",
        }

        response = requests.get(poster_url, headers=headers, timeout=30)
        response.raise_for_status()

        # 检查文件大小
        if len(response.content) == 0:
            print("   下载的图片文件为空")
            return ""

        if len(response.content) > 10 * 1024 * 1024:
            print("   图片文件过大 (>10MB)")
            return ""

        print(f"   图片下载成功，大小: {len(response.content)} bytes")

        # 2. 保存到临时文件
        temp_file = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
                f.write(response.content)
                temp_file = f.name

            print(f"   临时文件已保存: {temp_file}")

            # 3. 上传到pixhost，支持主备域名切换（优先直连，失败时使用代理）
            api_urls = [
                "https://api.pixhost.to/images",
                "http://pt-nexus-proxy.sqing33.dpdns.org/https://api.pixhost.to/images",
                "http://pt-nexus-proxy.1395251710.workers.dev/https://api.pixhost.to/images",
            ]
            params = {"content_type": 0, "max_th_size": 420}
            upload_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
                "Accept": "application/json",
            }

            upload_response = None
            # 尝试不同的API URL
            for i, api_url in enumerate(api_urls):
                domain_name = "主域名" if i == 0 else "备用域名"
                print(f"   尝试使用{domain_name}上传: {api_url}")

                try:
                    with open(temp_file, "rb") as f:
                        files = {"img": ("poster.jpg", f, "image/jpeg")}
                        upload_response = requests.post(
                            api_url, data=params, files=files, headers=upload_headers, timeout=30
                        )

                    if upload_response.status_code == 200:
                        print(f"   {domain_name}上传成功")
                        break
                    else:
                        print(f"   {domain_name}上传失败，状态码: {upload_response.status_code}")
                        upload_response = None

                except Exception as e:
                    print(f"   {domain_name}上传异常: {e}")
                    upload_response = None
                    continue

            if not upload_response:
                print("   所有API域名都上传失败")
                return ""

            if upload_response.status_code == 200:
                data = upload_response.json()
                show_url = data.get("show_url")

                if not show_url:
                    print("   API未返回有效URL")
                    return ""

                # 转换为直链URL
                direct_url = _convert_pixhost_url_to_direct(show_url)

                if direct_url:
                    print(f"   上传成功！直链: {direct_url}")
                    return direct_url
                else:
                    print("   URL转换失败")
                    return ""
            else:
                print(f"   上传失败，状态码: {upload_response.status_code}")
                return ""

        finally:
            # 清理临时文件
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                    print(f"   临时文件已清理: {temp_file}")
                except:
                    pass

    except Exception as e:
        print(f"   转存失败: {type(e).__name__} - {e}")
        return ""


def _call_tmdb_format_api(
    api_config: dict, douban_link: str, imdb_link: str, tmdb_link: str, media_type: str
):
    """
    调用 TMDB API 直接获取影片信息（兜底方案）

    使用场景：
    - 没有豆瓣链接
    - 有 IMDb 链接，但通过 IMDb 获取豆瓣链接失败
    - 作为最后的兜底方案

    Args:
        api_config: API 配置
        douban_link: 豆瓣链接（可能为空）
        imdb_link: IMDb 链接
        tmdb_link: TMDb 链接（可能为空）
        media_type: 媒体类型

    Returns:
        tuple: (success, poster, description, imdb_link_result)
    """
    try:
        from utils.tmdb import get_tmdb_info

        print("[*] 使用新的 TMDB 模块获取信息...")

        # 确定 TMDB ID
        tmdb_id = None
        if tmdb_link:
            # 从 TMDb 链接提取 ID
            tmdb_match = re.search(r"/(\d+)", tmdb_link)
            if tmdb_match:
                tmdb_id = tmdb_match.group(1)
                print(f"[*] 从 TMDb 链接提取 ID: {tmdb_id}")
        elif imdb_link:
            # 如果没有 TMDb 链接但有 IMDb 链接，先转换为 TMDb
            print("[*] 从 IMDb 链接转换为 TMDb ID...")
            from utils.imdb2tmdb2douban import imdb_to_tmdb

            success, tmdb_url = imdb_to_tmdb(imdb_link)
            if success:
                tmdb_match = re.search(r"/(\d+)", tmdb_url)
                if tmdb_match:
                    tmdb_id = tmdb_match.group(1)
                    print(f"[*] 转换成功，TMDb ID: {tmdb_id}")
                else:
                    print(f"[!] 转换失败，无法从 URL 提取 ID: {tmdb_url}")
            else:
                print(f"[!] IMDb 转 TMDb 失败")

        if not tmdb_id:
            print("[!] 无法确定 TMDB ID")
            return False, "", "无法确定 TMDB ID", ""

        # 配置
        config = {
            "tmdbApiKey": "0f79586eb9d92afa2b7266f7928b055c",
            "language": "zh-CN",
            "timeout": 30.0,
            "fetch_imdb": True,
        }

        print(f"[*] 调用 TMDB API 获取信息 (ID: {tmdb_id})...")

        # 调用新的 TMDB 函数
        result = get_tmdb_info(tmdb_id, config)

        if result.get("success"):
            format_string = result.get("format", "")
            imdb_link_result = result.get("imdb_link", "")
            tmdb_link_result = result.get("tmdb_link", "")

            # 调用 _parse_format_content 提取海报和简介
            return _parse_format_content(format_string, imdb_link_result, media_type)
        else:
            error_msg = result.get("error", "未知错误")
            print(f"[!] TMDB API 调用失败: {error_msg}")
            return False, "", f"TMDB API 调用失败: {error_msg}", ""

    except Exception as e:
        print(f"[!] TMDB 格式 API 调用异常: {type(e).__name__} - {e}")
        return False, "", f"TMDB 格式 API 调用失败: {e}", ""


def check_intro_completeness(body_text: str) -> dict:
    """
    检查简介是否完整，包含必要的影片信息字段。

    :param body_text: 简介正文内容
    :return: 包含检测结果的字典 {
        "is_complete": bool,      # 是否完整
        "missing_fields": list,   # 缺失的字段列表
        "found_fields": list      # 已找到的字段列表
    }

    示例:
        >>> result = check_intro_completeness(intro_body)
        >>> if not result["is_complete"]:
        >>>     print(f"缺少字段: {result['missing_fields']}")
    """
    if not body_text:
        return {"is_complete": False, "missing_fields": ["所有字段"], "found_fields": []}

    # 定义必要字段的匹配模式
    # 每个字段可以有多个匹配模式（正则表达式）
    required_patterns = {
        "片名": [
            r"[◎❁]\s*片\s*名",
            r"[◎❁]\s*译\s*名",
            r"[◎❁]\s*标\s*题",
            r"片名\s*[:：]",
            r"译名\s*[:：]",
            r"Title\s*[:：]",
        ],
        "年代": [
            r"[◎❁]\s*年\s*代",
            r"[◎❁]\s*年\s*份",
            r"年份\s*[:：]",
            r"年代\s*[:：]",
            r"Year\s*[:：]",
        ],
        "产地": [
            r"[◎❁]\s*产\s*地",
            r"[◎❁]\s*国\s*家",
            r"[◎❁]\s*地\s*区",
            r"制片国家/地区\s*[:：]",
            r"制片国家\s*[:：]",
            r"国家\s*[:：]",
            r"产地\s*[:：]",
            r"Country\s*[:：]",
        ],
        "类别": [
            r"[◎❁]\s*类\s*别",
            r"[◎❁]\s*类\s*型",
            r"类型\s*[:：]",
            r"类别\s*[:：]",
            r"Genre\s*[:：]",
        ],
        "语言": [r"[◎❁]\s*语\s*言", r"语言\s*[:：]", r"Language\s*[:：]"],
        "导演": [r"[◎❁]\s*导\s*演", r"导演\s*[:：]", r"Director\s*[:：]"],
        "简介": [
            r"[◎❁]\s*简\s*介",
            r"[◎❁]\s*剧\s*情",
            r"[◎❁]\s*内\s*容",
            r"简介\s*[:：]",
            r"剧情\s*[:：]",
            r"内容简介\s*[:：]",
            r"Plot\s*[:：]",
            r"Synopsis\s*[:：]",
        ],
    }

    found_fields = []
    missing_fields = []

    # 检查每个必要字段
    for field_name, patterns in required_patterns.items():
        field_found = False
        for pattern in patterns:
            if re.search(pattern, body_text, re.IGNORECASE):
                field_found = True
                break

        if field_found:
            found_fields.append(field_name)
        else:
            missing_fields.append(field_name)

    # 判断完整性：必须包含以下关键字段
    # 片名、产地、导演、简介 这4个字段是最关键的
    critical_fields = ["片名", "产地", "简介"]
    is_complete = all(field in found_fields for field in critical_fields)

    return {
        "is_complete": is_complete,
        "missing_fields": missing_fields,
        "found_fields": found_fields,
    }
