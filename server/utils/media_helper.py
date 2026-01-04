# utils/media_helper.py

import base64
import logging
import mimetypes
import re
import os
import shutil
import subprocess
import tempfile
import requests
import json
import time
import random
import cloudscraper
import yaml
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from pymediainfo import MediaInfo
from config import TEMP_DIR, config_manager, GLOBAL_MAPPINGS
from qbittorrentapi import Client as qbClient
from transmission_rpc import Client as TrClient
from utils import ensure_scheme
from .title import extract_season_episode


def translate_path(downloader_id: str, remote_path: str) -> str:
    """
    将下载器的远程路径转换为 PT Nexus 容器内的本地路径。

    :param downloader_id: 下载器ID
    :param remote_path: 下载器中的远程路径
    :return: PT Nexus 容器内可访问的本地路径
    """
    if not downloader_id or not remote_path:
        return remote_path

    # 获取下载器配置
    config = config_manager.get()
    downloaders = config.get("downloaders", [])

    for downloader in downloaders:
        if downloader.get("id") == downloader_id:
            path_mappings = downloader.get("path_mappings", [])
            if not path_mappings:
                # 没有配置路径映射，直接返回原路径
                return remote_path

            # 按远程路径长度降序排序，优先匹配最长的路径（更精确）
            sorted_mappings = sorted(
                path_mappings, key=lambda x: len(x.get("remote", "")), reverse=True
            )

            for mapping in sorted_mappings:
                remote = mapping.get("remote", "")
                local = mapping.get("local", "")

                if not remote or not local:
                    continue

                # 确保路径比较时统一处理末尾的斜杠
                remote = remote.rstrip("/")
                remote_path_normalized = remote_path.rstrip("/")

                # 检查是否匹配（完全匹配或前缀匹配）
                if remote_path_normalized == remote:
                    # 完全匹配
                    return local
                elif remote_path_normalized.startswith(remote + "/"):
                    # 前缀匹配，替换路径
                    relative_path = remote_path_normalized[len(remote) :].lstrip("/")
                    return os.path.join(local, relative_path)

            # 没有匹配的映射，返回原路径
            return remote_path

    # 没有找到对应的下载器，返回原路径
    return remote_path


MULTI_EPISODE_PATTERN = re.compile(
    r"(?i)S\d{1,2}E\d{1,3}\s*(?:[-~]\s*(?:S\d{1,2})?E?\d{1,3}|E\d{1,3})"
)


def _parse_season_episode_numbers(season_episode: str):
    if not season_episode:
        return None, None

    match = re.match(r"(?i)^S(\d{1,2})(?:E(\d{1,3}))?$", season_episode.strip())
    if not match:
        return None, None

    season = int(match.group(1))
    episode = match.group(2)
    return season, int(episode) if episode is not None else None


def _find_target_video_file(path: str, content_name: str | None = None) -> tuple[str | None, bool]:
    """
    根据路径智能查找目标视频文件，并检测是否为原盘文件。
    - 优先检查种子名称匹配的文件（处理电影直接放在下载目录根目录的情况）
    - 如果是电影目录，返回最大的视频文件。
    - 如果是剧集目录，优先按季集信息匹配，季包默认选择 E01。
    - 检测是否为原盘文件（检查 BDMV/CERTIFICATE 目录）

    :param path: 要搜索的目录或文件路径。
    :param content_name: 可选的主标题，用于补充季集信息匹配。
    :return: 元组 (目标视频文件的完整路径, 是否为原盘文件)
    """
    print(f"开始在路径 '{path}' 中查找目标视频文件...")
    VIDEO_EXTENSIONS = {".mkv", ".mp4", ".ts", ".avi", ".wmv", ".mov", ".flv", ".m2ts"}

    if not os.path.exists(path):
        print(f"错误：提供的路径不存在: {path}")
        return None, False

    # 如果提供的路径本身就是一个视频文件，直接返回
    if os.path.isfile(path) and os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS:
        print(f"路径直接指向一个视频文件，将使用: {path}")
        return path, False

    if not os.path.isdir(path):
        print(f"错误：路径不是一个有效的目录或视频文件: {path}")
        return None, False

    # 检查是否为原盘文件（检查 BDMV/CERTIFICATE 目录）
    is_bluray_disc = False
    bdmv_path = os.path.join(path, "BDMV")
    certificate_path = os.path.join(path, "CERTIFICATE")

    if os.path.exists(bdmv_path) and os.path.isdir(bdmv_path):
        print(f"检测到 BDMV 目录: {bdmv_path}")
        if (
            certificate_path
            and os.path.exists(certificate_path)
            and os.path.isdir(certificate_path)
        ):
            print(f"检测到 CERTIFICATE 目录: {certificate_path}")
            is_bluray_disc = True
            print("确认：检测到原盘文件结构 (BDMV/CERTIFICATE)")
        else:
            print("警告：检测到 BDMV 目录但未找到 CERTIFICATE 目录，可能不是标准原盘")

    # 优先检查种子名称匹配的文件（处理电影直接放在根目录的情况）
    # 这种情况通常发生在没有文件夹包裹的电影文件
    parent_dir = os.path.dirname(path)
    file_name = os.path.basename(os.path.normpath(path))

    # 检查父目录中是否有匹配的文件名（不含扩展名）
    if parent_dir != path:  # 确保这不是根目录的情况
        try:
            for file in os.listdir(parent_dir):
                if not file.startswith(".") and not os.path.isdir(os.path.join(parent_dir, file)):
                    if os.path.splitext(file)[1].lower() in VIDEO_EXTENSIONS:
                        # 检查文件名是否匹配（忽略扩展名）
                        file_name_without_ext = os.path.splitext(file)[0]
                        if (
                            file_name in file_name_without_ext
                            or file_name_without_ext in file_name
                            or file_name.replace(" ", "") in file_name_without_ext.replace(" ", "")
                            or file_name_without_ext.replace(" ", "") in file_name.replace(" ", "")
                        ):
                            full_path = os.path.join(parent_dir, file)
                            print(f"找到匹配的视频文件: {full_path}")
                            return full_path, is_bluray_disc
        except OSError as e:
            print(f"读取父目录失败: {e}")

    # 如果没有找到匹配的文件，继续原来的查找逻辑
    video_files = []
    for root, _, files in os.walk(path):
        for file in files:
            if os.path.splitext(file)[1].lower() in VIDEO_EXTENSIONS:
                video_files.append(os.path.join(root, file))

    if not video_files:
        print(f"在目录 '{path}' 中未找到任何视频文件。")
        return None, is_bluray_disc

    # 如果只有一个视频文件，直接使用
    if len(video_files) == 1:
        print(f"找到唯一的视频文件: {video_files[0]}")
        return video_files[0], is_bluray_disc

    # 如果目录名包含季集信息，优先匹配对应集数
    season_episode = None
    if content_name:
        season_episode = extract_season_episode(content_name)
    if not season_episode:
        season_episode = extract_season_episode(file_name)
    if season_episode:
        target_season, target_episode = _parse_season_episode_numbers(season_episode)
        if target_season is not None:
            if target_episode is None:
                target_episode = 1

            episode_matches = []
            season_candidates = []
            for video_file in video_files:
                base_name = os.path.basename(video_file)
                candidate = extract_season_episode(base_name)
                if not candidate:
                    continue

                cand_season, cand_episode = _parse_season_episode_numbers(candidate)
                if cand_season is None or cand_episode is None:
                    continue

                if cand_season != target_season:
                    continue

                is_multi = bool(MULTI_EPISODE_PATTERN.search(base_name))
                season_candidates.append((cand_episode, is_multi, video_file))

                if cand_episode == target_episode:
                    episode_matches.append((video_file, is_multi))

            if episode_matches:
                single_episode_files = [
                    video_file for video_file, is_multi in episode_matches if not is_multi
                ]
                if single_episode_files:
                    selected = sorted(single_episode_files)[0]
                else:
                    selected = sorted([video_file for video_file, _ in episode_matches])[0]
                print(f"根据季集信息选择视频文件: {selected}")
                return selected, is_bluray_disc

            if season_candidates:
                min_episode = min(episode for episode, _, _ in season_candidates)
                min_episode_files = [
                    (video_file, is_multi)
                    for episode, is_multi, video_file in season_candidates
                    if episode == min_episode
                ]
                single_episode_files = [
                    video_file for video_file, is_multi in min_episode_files if not is_multi
                ]
                if single_episode_files:
                    selected = sorted(single_episode_files)[0]
                else:
                    selected = sorted([video_file for video_file, _ in min_episode_files])[0]
                print(
                    f"未找到 S{target_season}E{target_episode:02d}，选择该季最小集: {selected}"
                )
                return selected, is_bluray_disc

    # 如果有多个视频文件，尝试找到最匹配的文件名
    best_match = ""
    best_score = -1
    for video_file in video_files:
        base_name = os.path.basename(video_file).lower()
        path_name = file_name.lower()

        # 计算匹配度
        score = 0
        if path_name in base_name:
            score += 10
        if base_name in path_name:
            score += 5

        # 长度越接近，得分越高
        if abs(len(base_name) - len(path_name)) < 5:
            score += 3

        if score > best_score:
            best_score = score
            best_match = video_file

    if best_match and best_score > 0:
        print(f"选择最佳匹配的视频文件: {best_match} (匹配度: {best_score})")
        return best_match, is_bluray_disc

    # 如果没有找到好的匹配，选择最大的文件
    largest_file = ""
    max_size = -1
    for f in video_files:
        try:
            size = os.path.getsize(f)
            if size > max_size:
                max_size = size
                largest_file = f
        except OSError as e:
            print(f"无法获取文件大小 '{f}': {e}")
            continue

    if largest_file:
        print(f"已选择最大文件 ({(max_size / 1024**3):.2f} GB): {largest_file}")
        return largest_file, is_bluray_disc
    else:
        print("无法确定最大的文件。")
        return None, is_bluray_disc



def add_torrent_to_downloader(
    detail_page_url: str,
    save_path: str,
    downloader_id: str,
    db_manager,
    config_manager,
    direct_download_url: str = "",
    tags: list | None = None,
):
    """
    从种子详情页下载 .torrent 文件并添加到指定的下载器。
    [最终修复版] 修正了向 Transmission 发送数据时的双重编码问题。
    """
    logging.info(
        f"开始自动添加任务: URL='{detail_page_url}', Path='{save_path}', DownloaderID='{downloader_id}'"
    )

    # 检查环境变量，如果设置为false则跳过种子下载和添加
    if os.getenv("ADD_DOWNLOADS_TORRENTS") == "false":
        msg = f"模拟成功: 环境变量ADD_DOWNLOADS_TORRENTS=false，跳过种子下载和添加"
        logging.info(msg)
        return True, msg

    # 1. 查找对应的站点配置
    conn = db_manager._get_connection()
    cursor = db_manager._get_cursor(conn)
    cursor.execute("SELECT nickname, base_url, cookie, speed_limit FROM sites")
    site_info = None
    for site in cursor.fetchall():
        # [修复] 确保 base_url 存在且不为空
        if site["base_url"] and site["base_url"] in detail_page_url:
            site_info = dict(site)  # [修复] 将 sqlite3.Row 转换为 dict
            break
    conn.close()

    if not site_info or not site_info.get("cookie"):
        msg = f"未能找到与URL '{detail_page_url}' 匹配的站点配置或该站点缺少Cookie。"
        logging.error(msg)
        return False, msg

    try:
        # 2. 下载种子文件
        common_headers = {
            "Cookie": site_info["cookie"],
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
        }
        scraper = cloudscraper.create_scraper()

        # 站点级别的代理已不使用全局代理配置
        proxies = None
        torrent_content = None

        # 如果提供了直接下载链接，优先使用直接下载，避免请求详情页
        if direct_download_url:
            try:
                logging.info(f"使用直接下载链接: {direct_download_url}")

                # 使用直接下载链接下载种子文件
                direct_headers = common_headers.copy()
                scraper = cloudscraper.create_scraper()

                # Add retry logic for direct torrent download
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        torrent_response = scraper.get(
                            direct_download_url,
                            headers=direct_headers,
                            timeout=180,
                            proxies=proxies,
                        )
                        torrent_response.raise_for_status()
                        break  # Success, exit retry loop
                    except Exception as e:
                        if attempt < max_retries - 1:
                            logging.warning(
                                f"Attempt {attempt + 1} failed to download torrent directly: {e}. Retrying..."
                            )
                            time.sleep(2**attempt)  # Exponential backoff
                        else:
                            raise  # Re-raise the exception if all retries failed

                torrent_content = torrent_response.content
                logging.info("已通过直接下载链接成功下载种子文件内容。")

            except Exception as e:
                msg = f"使用直接下载链接下载种子文件失败: {e}"
                logging.warning(msg)
                # 如果直接下载失败，继续走详情页逻辑

        # 如果没有直接下载链接或直接下载失败，则请求详情页
        if not torrent_content:
            logging.info("未提供直接下载链接或直接下载失败，开始请求详情页")

            # Add retry logic for network requests
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    details_response = scraper.get(
                        detail_page_url, headers=common_headers, timeout=180, proxies=proxies
                    )
                    break  # Success, exit retry loop
                except Exception as e:
                    if attempt < max_retries - 1:
                        logging.warning(
                            f"Attempt {attempt + 1} failed to fetch details page: {e}. Retrying..."
                        )
                        time.sleep(2**attempt)  # Exponential backoff
                    else:
                        raise  # Re-raise the exception if all retries failed
            details_response.raise_for_status()

            soup = BeautifulSoup(details_response.text, "html.parser")

            # 检查是否需要使用特殊下载器
            site_base_url = ensure_scheme(site_info["base_url"])
            full_download_url = None  # 初始化full_download_url

            print(f"站点基础URL: {site_base_url}")

            # 检查是否为haidan站点
            if "haidan" in site_base_url:
                # Haidan站点需要提取torrent_id而不是id
                torrent_id_match = re.search(r"torrent_id=(\d+)", detail_page_url)
                if not torrent_id_match:
                    raise ValueError("无法从详情页URL中提取种子ID（torrent_id）。")
                torrent_id = torrent_id_match.group(1)
                # Haidan站点的特殊逻辑
                download_link_tag = soup.find("a", href=re.compile(r"download.php\?id="))

                if not download_link_tag:
                    raise RuntimeError("在详情页HTML中未能找到下载链接！")

                download_url_part = str(download_link_tag["href"])  # 显式转换为str

                # 替换下载链接中的id为从detail_page_url中提取的torrent_id
                download_url_part = re.sub(r"id=\d+", f"id={torrent_id}", download_url_part)

                full_download_url = f"{site_base_url}/{download_url_part}"
            else:
                # 其他站点的通用逻辑 - 提取id参数
                torrent_id_match = re.search(r"id=(\d+)", detail_page_url)
                if not torrent_id_match:
                    raise ValueError("无法从详情页URL中提取种子ID。")
                torrent_id = torrent_id_match.group(1)

                download_link_tag = soup.select_one(
                    f'a.index[href^="download.php?id={torrent_id}"]'
                )
                if not download_link_tag:
                    raise RuntimeError("在详情页HTML中未能找到下载链接！")

                download_url_part = str(download_link_tag["href"])  # 显式转换为str
                full_download_url = f"{site_base_url}/{download_url_part}"

            # 确保full_download_url已被赋值
            if not full_download_url:
                raise RuntimeError("未能成功构建种子下载链接！")

            print(f"种子下载链接: {full_download_url}")

            common_headers["Referer"] = detail_page_url
            # Add retry logic for torrent download
            for attempt in range(max_retries):
                try:
                    torrent_response = scraper.get(
                        full_download_url, headers=common_headers, timeout=180, proxies=proxies
                    )
                    torrent_response.raise_for_status()
                    break  # Success, exit retry loop
                except Exception as e:
                    if attempt < max_retries - 1:
                        logging.warning(
                            f"Attempt {attempt + 1} failed to download torrent: {e}. Retrying..."
                        )
                        time.sleep(2**attempt)  # Exponential backoff
                    else:
                        raise  # Re-raise the exception if all retries failed

            torrent_content = torrent_response.content
            logging.info("已通过详情页成功下载种子文件内容。")

    except Exception as e:
        msg = f"在下载种子文件步骤发生错误: {e}"
        logging.error(msg, exc_info=True)
        return False, msg

    # 3. 找到下载器配置
    config = config_manager.get()
    downloader_config = next(
        (
            d
            for d in config.get("downloaders", [])
            if d.get("id") == downloader_id and d.get("enabled")
        ),
        None,
    )

    if not downloader_config:
        msg = f"未找到ID为 '{downloader_id}' 的已启用下载器配置。"
        logging.error(msg)
        return False, msg

    # 4. 添加到下载器 (核心修改在此！) - 添加重试机制
    max_retries = 3
    for attempt in range(max_retries):
        try:
            from core.services import _prepare_api_config

            api_config = _prepare_api_config(downloader_config)
            client_name = downloader_config["name"]

            # 获取标签配置（在两个下载器代码块之前）
            tags_config = config.get("tags_config", {})

            if downloader_config["type"] == "qbittorrent":
                client = qbClient(**api_config)
                client.auth_log_in()

                # 准备 qBittorrent 参数
                qb_params = {
                    "torrent_files": torrent_content,
                    "save_path": save_path,
                    "is_paused": False,
                    "skip_checking": True,
                }

                # 处理标签
                final_tags = []
                if tags:
                    final_tags = tags

                # 如果启用了标签功能，提取并合并标签
                if tags_config.get("tags", {}).get("enabled", False):
                    # 添加自定义标签
                    tags_list = tags_config.get("tags", {}).get("tags", [])
                    for tag in tags_list:
                        # 检查是否是站点标签占位符
                        if tag == "站点/{站点名称}":
                            # 替换为实际的站点标签
                            site_tag = f"站点/{site_info['nickname']}"
                            if site_tag not in final_tags:
                                final_tags.append(site_tag)
                        else:
                            # 添加普通自定义标签
                            if tag and tag not in final_tags:
                                final_tags.append(tag)

                # 添加标签到 qBittorrent 参数
                if final_tags:
                    qb_params["tags"] = ",".join(final_tags)
                    logging.info(f"准备添加标签: {', '.join(final_tags)}")

                # 添加分类到 qBittorrent 参数
                if tags_config.get("category", {}).get("enabled", False):
                    category_name = tags_config.get("category", {}).get("category", "")
                    if category_name and category_name.strip():
                        qb_params["category"] = category_name.strip()
                        logging.info(f"准备添加分类: {category_name}")

                # 如果站点设置了速度限制，则添加速度限制参数
                # 数据库中存储的是MB/s，需要转换为bytes/s传递给下载器API
                if site_info and site_info.get("speed_limit", 0) > 0:
                    speed_limit = int(site_info["speed_limit"]) * 1024 * 1024  # 转换为 bytes/s
                    qb_params["upload_limit"] = speed_limit
                    logging.info(
                        f"为站点 '{site_info['nickname']}' 设置上传速度限制: {site_info['speed_limit']} MB/s"
                    )

                result = client.torrents_add(**qb_params)
                logging.info(f"已将种子添加到 qBittorrent '{client_name}': {result}")

            elif downloader_config["type"] == "transmission":
                client = TrClient(**api_config)

                # 准备 Transmission 参数
                tr_params = {
                    "torrent": torrent_content,
                    "download_dir": save_path,
                    "paused": False,
                }

                # 处理标签
                final_tags = []
                if tags:
                    final_tags = tags

                # 如果启用了标签功能，提取并合并标签
                if tags_config.get("tags", {}).get("enabled", False):
                    # 添加自定义标签
                    tags_list = tags_config.get("tags", {}).get("tags", [])
                    for tag in tags_list:
                        # 检查是否是站点标签占位符
                        if tag == "站点/{站点名称}":
                            # 替换为实际的站点标签
                            site_tag = f"站点/{site_info['nickname']}"
                            if site_tag not in final_tags:
                                final_tags.append(site_tag)
                        else:
                            # 添加普通自定义标签
                            if tag and tag not in final_tags:
                                final_tags.append(tag)

                    # 如果设置了分类，将分类添加到标签中（Transmission 只有标签，没有分类）
                    if tags_config.get("category", {}).get("enabled", False):
                        category_name = tags_config.get("category", {}).get("category", "")
                        if category_name and category_name.strip() and category_name.strip() not in final_tags:
                            final_tags.append(category_name.strip())
                            logging.info(f"将分类 '{category_name}' 添加到标签中")

                # 如果有标签，添加到参数中
                if final_tags:
                    tr_params["labels"] = final_tags
                    logging.info(f"准备添加标签: {', '.join(final_tags)}")

                # 先添加种子
                result = client.add_torrent(**tr_params)
                logging.info(f"已将种子添加到 Transmission '{client_name}': ID={result.id}")

                # 如果站点设置了速度限制，则在添加后设置速度限制
                # add_torrent 方法不支持速度限制参数，需要使用 change_torrent 方法
                if site_info and site_info.get("speed_limit", 0) > 0:
                    # 转换为 KBps: MB/s * 1024 = KBps
                    speed_limit_kbps = int(site_info["speed_limit"]) * 1024
                    try:
                        client.change_torrent(
                            result.id, upload_limit=speed_limit_kbps, upload_limited=True
                        )
                        logging.info(
                            f"为站点 '{site_info['nickname']}' 设置上传速度限制: {site_info['speed_limit']} MB/s ({speed_limit_kbps} KBps)"
                        )
                    except Exception as e:
                        logging.warning(f"设置速度限制失败，但种子已添加成功: {e}")

            # 在成功添加种子后检查发种限制
            try:
                from api.internal_guard import check_downloader_gate

                # 检查发种限制
                can_continue, limit_message = check_downloader_gate(downloader_id)

                if not can_continue:
                    return "LIMIT_REACHED", limit_message

            except Exception as e:
                logging.warning(f"检查发种限制时发生错误: {e}")
                # 出错时不阻止正常流程，继续返回成功

            return True, f"成功添加到 '{client_name}'"

        except Exception as e:
            logging.warning(f"第 {attempt + 1} 次尝试添加种子到下载器失败: {e}")

            # 如果不是最后一次尝试，等待一段时间后重试
            if attempt < max_retries - 1:
                wait_time = 2**attempt  # 指数退避
                logging.info(f"等待 {wait_time} 秒后进行第 {attempt + 2} 次尝试...")
                time.sleep(wait_time)
            else:
                msg = f"添加到下载器 '{downloader_config['name']}' 时失败: {e}"
                logging.error(msg, exc_info=True)
                return False, msg




def _apply_tag_rules(tags: list, rules: dict) -> list:
    """应用标签合并规则"""
    # 去重
    if rules.get("deduplication", True):
        tags = list(set(tags))

    # 限制数量
    max_tags = rules.get("max_tags", 20)
    if len(tags) > max_tags:
        tags = tags[:max_tags]

    return tags


def extract_tags_from_description(description_text: str) -> list:
    """
    从简介文本的"类别"字段中提取标签。

    :param description_text: 简介文本内容（包括statement和body）
    :return: 标签列表，例如 ['tag.喜剧', 'tag.动画']
    """
    if not description_text:
        return []

    found_tags = []

    # 从简介中提取类别字段
    category_match = re.search(r"[◎❁]\s*类\s*别\s*(.+?)(?:\n|$)", description_text)
    if category_match:
        category_text = category_match.group(1).strip()
        print(f"从简介中提取到类别: {category_text}")

        # 定义类别关键词到标签的映射
        category_tag_map = {
            "喜剧": "tag.喜剧",
            "Comedy": "tag.喜剧",
            "儿童": "tag.儿童",
            "Children": "tag.儿童",
            "动画": "tag.动画",
            "Animation": "tag.动画",
            "动作": "tag.动作",
            "Action": "tag.动作",
            "爱情": "tag.爱情",
            "Romance": "tag.爱情",
            "科幻": "tag.科幻",
            "Sci-Fi": "tag.科幻",
            "恐怖": "tag.恐怖",
            "Horror": "tag.恐怖",
            "惊悚": "tag.惊悚",
            "Thriller": "tag.惊悚",
            "悬疑": "tag.悬疑",
            "Mystery": "tag.悬疑",
            "犯罪": "tag.犯罪",
            "Crime": "tag.犯罪",
            "战争": "tag.战争",
            "War": "tag.战争",
            "冒险": "tag.冒险",
            "Adventure": "tag.冒险",
            "奇幻": "tag.奇幻",
            "Fantasy": "tag.奇幻",
            "家庭": "tag.家庭",
            "Family": "tag.家庭",
            "剧情": "tag.剧情",
            "Drama": "tag.剧情",
        }

        # 检查类别文本中是否包含关键词
        for keyword, tag in category_tag_map.items():
            if keyword in category_text:
                found_tags.append(tag)
                print(f"   从类别中提取到标签: {tag} (匹配关键词: {keyword})")

    if found_tags:
        print(f"从简介类别中提取到的标签: {found_tags}")
    else:
        print("从简介类别中未提取到任何标签")

    return found_tags


def check_animation_type_from_description(description_text: str) -> bool:
    """
    检查简介的类别字段中是否包含"动画"，用于判断是否需要修正类型为动漫。

    :param description_text: 简介文本内容（包括statement和body）
    :return: 如果包含"动画"返回True，否则返回False
    """
    if not description_text:
        return False

    # 从简介中提取类别字段
    category_match = re.search(r"[◎❁]\s*类\s*别\s*(.+?)(?:\n|$)", description_text)
    if category_match:
        category_text = category_match.group(1).strip()

        # 检查类别中是否包含"动画"关键词
        if "动画" in category_text or "Animation" in category_text:
            print(f"检测到类别中包含'动画': {category_text}")
            return True

    return False


def extract_origin_from_description(description_text: str) -> str:
    """
    从简介详情中提取产地信息，并检查是否能在 global_mappings.yaml 的 source 映射中找到对应的标准键。
    如果找不到映射，则设置为'其他'。

    :param description_text: 简介详情文本
    :return: 产地信息，例如 "日本"、"中国" 等，如果无法映射则返回 "其他"
    """
    if not description_text:
        return ""

    # 使用正则表达式匹配 "◎产　　地　日本" 这种格式
    # 支持多种变体：◎产地、◎产　　地、◎国　　家、◎国家地区等
    # 修复：使用 [^\n\r]+ 而不是 .+? 来正确匹配包含空格的产地名称（如"中国大陆"）
    patterns = [
        r"[◎❁]\s*产\s*地\s*([^\n\r]+?)(?:\n|$)",  # 匹配 ◎产地 中国大陆
        r"[◎❁]\s*国\s*家\s*([^\n\r]+?)(?:\n|$)",  # 匹配 ◎国家 中国大陆
        r"[◎❁]\s*地\s*区\s*([^\n\r]+?)(?:\n|$)",  # 匹配 ◎地区 中国大陆
        r"[◎❁]\s*国家地区\s*([^\n\r]+?)(?:\n|$)",  # 匹配 ◎国家地区 中国大陆
        r"制片国家/地区[:\s]+([^\n\r]+?)(?:\n|$)",  # 匹配 制片国家/地区: 中国大陆
        r"制片国家[:\s]+([^\n\r]+?)(?:\n|$)",  # 匹配 制片国家: 中国大陆
        r"国家[:\s]+([^\n\r]+?)(?:\n|$)",  # 匹配 国家: 中国大陆
        r"产地[:\s]+([^\n\r]+?)(?:\n|$)",  # 匹配 产地: 中国大陆
        r"[产]\s*地[:\s]+([^，,\n\r]+)",
        r"[国]\s*家[:\s]+([^，,\n\r]+)",
        r"[地]\s*区[:\s]+([^，,\n\r]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, description_text)
        if match:
            origin = match.group(1).strip()
            # 清理可能的多余字符
            origin = re.sub(r"[\[\]【】\(\)]", "", origin).strip()
            # 添加额外的清理步骤，去除前置的冒号、空格等字符
            origin = re.sub(r"^[:\s\u3000]+", "", origin).strip()
            # 移除常见的分隔符，如" / "、","等
            origin = re.split(r"\s*/\s*|\s*,\s*|\s*;\s*|\s*&\s*", origin)[0].strip()
            print("提取到产地信息:", origin)

            # 检查产地是否能在 global_mappings.yaml 的 source 映射中找到对应的标准键
            if _check_origin_mapping(origin):
                return origin
            else:
                print(f"产地 '{origin}' 无法在 source 映射中找到对应的标准键，设置为'其他'")
                return "其他"

    return ""


def _check_origin_mapping(origin: str) -> bool:
    """
    检查产地是否能在 global_mappings.yaml 的 source 映射中找到对应的标准键。

    :param origin: 产地字符串
    :return: 如果能找到映射返回 True，否则返回 False
    """
    try:
        # 读取 global_mappings.yaml 文件
        with open(GLOBAL_MAPPINGS, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # 获取 source 映射
        source_mappings = config.get("global_standard_keys", {}).get("source", {})

        # 检查产地是否在映射中
        if origin in source_mappings:
            print(f"产地 '{origin}' 在 source 映射中找到对应的标准键: {source_mappings[origin]}")
            return True
        else:
            print(f"产地 '{origin}' 在 source 映射中未找到对应的标准键")
            return False

    except Exception as e:
        print(f"检查产地映射时出错: {e}")
        # 如果检查失败，为了安全起见，返回 True（保持原产地）
        return True


def _convert_pixhost_url_to_direct(show_url: str) -> str:
    """
    将pixhost的show URL转换为直链URL
    参考油猴插件的convertToDirectUrl函数

    :param show_url: pixhost show URL
    :return: 直链URL，失败返回空字符串
    """
    if not show_url:
        return ""

    try:
        import re

        # 方案1: 直接替换域名和路径
        direct_url = show_url.replace(
            "https://pixhost.to/show/", "https://img1.pixhost.to/images/"
        ).replace("https://pixhost.to/th/", "https://img1.pixhost.to/images/")

        # 移除缩略图后缀（如 _cover.jpg -> .jpg）
        direct_url = re.sub(r"_..\.jpg$", ".jpg", direct_url)

        # 方案2: 如果方案1失败，使用正则提取重建URL
        if not direct_url.startswith("https://img1.pixhost.to/images/"):
            match = re.search(r"(\d+)/([^/]+\.(jpg|png|gif))", show_url)
            if match:
                direct_url = f"https://img1.pixhost.to/images/{match.group(1)}/{match.group(2)}"

        # 最终验证
        if re.match(r"^https://img1\.pixhost\.to/images/\d+/[^/]+\.(jpg|png|gif)$", direct_url):
            return direct_url
        else:
            print(f"   URL格式验证失败: {direct_url}")
            return ""

    except Exception as e:
        print(f"   URL转换异常: {e}")
        return ""


def _get_downloader_proxy_config(downloader_id: str):
    """
    根据下载器ID获取代理配置。

    :param downloader_id: 下载器ID
    :return: 代理配置字典，如果不需要代理则返回None
    """
    if not downloader_id:
        return None

    config = config_manager.get()
    downloaders = config.get("downloaders", [])

    for downloader in downloaders:
        if downloader.get("id") == downloader_id:
            use_proxy = downloader.get("use_proxy", False)
            if use_proxy:
                host_value = downloader.get("host", "")
                proxy_port = downloader.get("proxy_port", 9090)
                if host_value.startswith(("http://", "https://")):
                    parsed_url = urlparse(host_value)
                else:
                    parsed_url = urlparse(f"http://{host_value}")
                proxy_ip = parsed_url.hostname
                if not proxy_ip:
                    if "://" in host_value:
                        proxy_ip = host_value.split("://")[1].split(":")[0].split("/")[0]
                    else:
                        proxy_ip = host_value.split(":")[0]
                proxy_config = {
                    "proxy_base_url": f"http://{proxy_ip}:{proxy_port}",
                }
                return proxy_config
            break

    return None


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
    critical_fields = ["片名", "产地", "导演", "简介"]
    is_complete = all(field in found_fields for field in critical_fields)

    return {
        "is_complete": is_complete,
        "missing_fields": missing_fields,
        "found_fields": found_fields,
    }
