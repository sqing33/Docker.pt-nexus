import base64
import logging
import mimetypes
import os
import shutil
import subprocess
import tempfile
import requests
import json
import time
import random
from config import TEMP_DIR, config_manager
from .media_helper import _find_target_video_file, _convert_pixhost_url_to_direct


def _get_best_chinese_subtitle_sid(video_path):
    """
    分析视频文件，返回最合适的中文字幕 MPV sid (相对序号)。
    如果没有找到中文，返回 None。
    """
    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-select_streams", "s",
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(result.stdout)
        streams = data.get("streams", [])

        if not streams:
            return None

        candidates = []

        for i, stream in enumerate(streams):
            mpv_sid = i + 1
            
            tags = stream.get("tags", {})
            lang = tags.get("language", "und").lower()
            title = tags.get("title", "").lower()
            
            score = 0
            
            if lang in ["chi", "zho", "zh"]:
                score += 10
            
            if "简" in title or "chs" in title or "sc" in title:
                score += 5
            elif "繁" in title or "cht" in title or "tc" in title:
                score += 3
            elif "中" in title or "chinese" in title:
                score += 2
            
            if "双语" in title:
                score += 1

            if score > 0:
                candidates.append({"sid": mpv_sid, "score": score, "title": title, "lang": lang})

        if not candidates:
            return None

        candidates.sort(key=lambda x: (-x["score"], x["sid"]))
        
        best = candidates[0]
        print(f"   🎯 自动选中字幕: Track {best['sid']} [{best['lang']}] {best['title']}")
        return best["sid"]

    except Exception as e:
        print(f"   ⚠️ 字幕分析失败: {e}")
        return None


def _upload_to_pixhost(image_path: str):
    """
    将单个图片文件上传到 Pixhost.to，支持主备域名切换。

    :param image_path: 本地图片文件的路径。
    :return: 成功时返回图片的展示URL，失败时返回None。
    """
    # 主备域名配置 - 优先直连，失败时使用代理
    api_urls = [
        "https://api.pixhost.to/images",
        "http://pt-nexus-proxy.sqing33.dpdns.org/https://api.pixhost.to/images",
        "http://pt-nexus-proxy.1395251710.workers.dev/https://api.pixhost.to/images",
    ]

    params = {"content_type": 0}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    print(f"准备上传图片: {image_path}")

    if not os.path.exists(image_path):
        print(f"错误：文件不存在 {image_path}")
        return None

    # 尝试使用不同的API URL
    for i, api_url in enumerate(api_urls):
        domain_name = "主域名" if i == 0 else "备用域名"
        print(f"尝试使用{domain_name}: {api_url}")

        result = _upload_to_pixhost_direct(image_path, api_url, params, headers)
        if result:
            print(f"{domain_name}上传成功")
            return result
        else:
            print(f"{domain_name}上传失败，尝试下一个")

    print("所有API域名都上传失败")
    return None


def _upload_to_pixhost_direct(image_path: str, api_url: str, params: dict, headers: dict):
    """直接上传图片到Pixhost"""
    try:
        with open(image_path, "rb") as f:
            files = {"img": f}
            print("正在发送上传请求到 Pixhost...")
            response = requests.post(
                api_url, data=params, files=files, headers=headers, timeout=180
            )

            if response.status_code == 200:
                data = response.json()
                show_url = data.get("show_url")
                print(f"直接上传成功！图片链接: {show_url}")
                return show_url
            else:
                print(f"   ❌ 直接上传失败 (状态码: {response.status_code})")
                return None
    except FileNotFoundError:
        print(f"   ❌ 错误: 找不到图片文件")
        return None
    except requests.exceptions.SSLError as e:
        print(f"   ❌ 直接上传失败: SSL连接错误")
        return None
    except requests.exceptions.ConnectionError as e:
        print(f"   ❌ 直接上传失败: 网络连接被重置")
        return None
    except requests.exceptions.Timeout:
        print(f"   ❌ 直接上传失败: 请求超时")
        return None
    except Exception as e:
        # 只打印异常类型和简短描述，不打印完整堆栈
        error_type = type(e).__name__
        print(f"   ❌ 直接上传失败: {error_type}")
        return None


def _get_agsv_auth_token():
    """使用配置文件中的邮箱和密码获取 末日图床 的授权 Token。"""
    config = config_manager.get().get("cross_seed", {})
    email = config.get("agsv_email")
    password = config.get("agsv_password")

    if not email or not password:
        logging.warning("末日图床 邮箱或密码未配置，无法获取 Token。")
        return None

    token_url = "https://img.seedvault.cn/api/v1/tokens"
    payload = {"email": email, "password": password}
    headers = {"Accept": "application/json"}
    print("正在为 末日图床 获取授权 Token...")
    try:
        response = requests.post(token_url, headers=headers, json=payload, timeout=180)
        if response.status_code == 200 and response.json().get("status"):
            token = response.json().get("data", {}).get("token")
            if token:
                print("   ✅ 成功获取 末日图床 Token！")
                return token

        logging.error(
            f"获取 末日图床 Token 失败。状态码: {response.status_code}, 响应: {response.text}"
        )
        print(f"   ❌ 获取 末日图床 Token 失败: {response.text}")
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f"获取 末日图床 Token 时网络请求错误: {e}")
        print(f"   ❌ 获取 末日图床 Token 时网络请求错误: {e}")
        return None


def _upload_to_agsv(image_path: str, token: str):
    """使用给定的 Token 上传单个图片到 末日图床。"""
    upload_url = "https://img.seedvault.cn/api/v1/upload"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    }

    mime_type = mimetypes.guess_type(image_path)[0] or "application/octet-stream"
    image_name = os.path.basename(image_path)

    print(f"准备上传图片到 末日图床: {image_name}")
    try:
        with open(image_path, "rb") as f:
            files = {"file": (image_name, f, mime_type)}
            response = requests.post(upload_url, headers=headers, files=files, timeout=180)

        data = response.json()
        if response.status_code == 200 and data.get("status"):
            image_url = data.get("data", {}).get("links", {}).get("url")
            print(f"   ✅ 末日图床 上传成功！URL: {image_url}")
            return image_url
        else:
            message = data.get("message", "无详细信息")
            logging.error(f"末日图床 上传失败。API 消息: {message}")
            print(f"   ❌ 末日图床 上传失败: {message}")
            return None
    except (requests.exceptions.RequestException, requests.exceptions.JSONDecodeError) as e:
        logging.error(f"上传到 末日图床 时发生错误: {e}")
        print(f"   ❌ 上传到 末日图床 时发生错误: {e}")
        return None


def _get_smart_screenshot_points(video_path: str, num_screenshots: int = 5) -> list[float]:
    """
    [优化版] 使用 ffprobe 智能分析视频字幕，选择最佳的截图时间点。
    - 通过 `-read_intervals` 参数实现分段读取，避免全文件扫描，大幅提升大文件处理速度。
    - 优先选择 ASS > SRT > PGS 格式的字幕。
    - 优先在视频的 30%-80% "黄金时段" 内随机选择。
    - 在所有智能分析失败时，优雅地回退到按百分比选择。
    """
    print("\n--- 开始智能截图时间点分析 (快速扫描模式) ---")
    if not shutil.which("ffprobe"):
        print("警告: 未找到 ffprobe，无法进行智能分析。")
        return []

    try:
        cmd_duration = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            video_path,
        ]
        result = subprocess.run(
            cmd_duration, capture_output=True, text=True, check=True, encoding="utf-8"
        )
        duration = float(result.stdout.strip())
        print(f"视频总时长: {duration:.2f} 秒")
    except Exception as e:
        print(f"错误：使用 ffprobe 获取视频时长失败。{e}")
        return []

    # 探测字幕流的部分保持不变，因为它本身速度很快
    try:
        cmd_probe_subs = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_entries",
            "stream=index,codec_name,disposition",
            "-select_streams",
            "s",
            video_path,
        ]
        result = subprocess.run(
            cmd_probe_subs, capture_output=True, text=True, check=True, encoding="utf-8"
        )
        sub_data = json.loads(result.stdout)

        best_ass, best_srt, best_pgs = None, None, None
        for stream in sub_data.get("streams", []):
            disposition = stream.get("disposition", {})
            is_normal = not any(
                [
                    disposition.get("comment"),
                    disposition.get("hearing_impaired"),
                    disposition.get("visual_impaired"),
                ]
            )
            if is_normal:
                codec_name = stream.get("codec_name")
                if codec_name == "ass" and not best_ass:
                    best_ass = stream
                elif codec_name == "subrip" and not best_srt:
                    best_srt = stream
                elif codec_name == "hdmv_pgs_subtitle" and not best_pgs:
                    best_pgs = stream

        chosen_sub_stream = best_ass or best_srt or best_pgs
        if not chosen_sub_stream:
            print("未找到合适的正常字幕流。")
            return []

        sub_index, sub_codec = chosen_sub_stream.get("index"), chosen_sub_stream.get("codec_name")
        print(f"   ✅ 找到最优字幕流 (格式: {sub_codec.upper()})，流索引: {sub_index}")

    except Exception as e:
        print(f"探测字幕流失败: {e}")
        return []

    subtitle_events = []
    try:
        # --- 【核心修改】 ---
        # 1. 定义我们要探测的时间点（例如，视频的20%, 40%, 60%, 80%位置）
        probe_points = [0.2, 0.4, 0.6, 0.8]
        # 2. 定义在每个探测点附近扫描多长时间（例如，60秒），时间越长，找到字幕事件越多，但耗时也越长
        probe_duration = 60

        # 3. 构建 -read_intervals 参数
        # 格式为 "start1%+duration1,start2%+duration2,..."
        intervals = []
        for point in probe_points:
            start_time = duration * point
            end_time = start_time + probe_duration
            if end_time > duration:
                end_time = duration  # 确保不超过视频总长
            intervals.append(f"{start_time}%{end_time}")

        read_intervals_arg = ",".join(intervals)
        print(f"   🚀 将只扫描以下时间段来寻找字幕: {read_intervals_arg}")

        # 4. 将 -read_intervals 参数添加到 ffprobe 命令中
        cmd_extract = [
            "ffprobe",
            "-v",
            "quiet",
            "-read_intervals",
            read_intervals_arg,  # <--- 新增的参数
            "-print_format",
            "json",
            "-show_packets",
            "-select_streams",
            str(sub_index),
            video_path,
        ]

        # 执行命令，现在它会快非常多
        result = subprocess.run(
            cmd_extract, capture_output=True, text=True, check=True, encoding="utf-8"
        )
        # --- 【核心修改结束】 ---

        events_data = json.loads(result.stdout)
        packets = events_data.get("packets", [])

        # 后续处理逻辑基本不变
        if sub_codec in ["ass", "subrip"]:
            for packet in packets:
                try:
                    start, dur = float(packet.get("pts_time")), float(packet.get("duration_time"))
                    if dur > 0.1:
                        subtitle_events.append({"start": start, "end": start + dur})
                except (ValueError, TypeError):
                    continue
        elif sub_codec == "hdmv_pgs_subtitle":
            for i in range(0, len(packets) - 1, 2):
                try:
                    start, end = float(packets[i].get("pts_time")), float(
                        packets[i + 1].get("pts_time")
                    )
                    if end > start and (end - start) > 0.1:
                        subtitle_events.append({"start": start, "end": end})
                except (ValueError, TypeError):
                    continue

        if not subtitle_events:
            raise ValueError("在指定区间内未能提取到任何有效的时间事件。")
        print(f"   ✅ 成功从指定区间提取到 {len(subtitle_events)} 条有效字幕事件。")
    except Exception as e:
        print(f"智能提取时间事件失败: {e}")
        return []

    # 后续的随机选择逻辑保持不变
    if len(subtitle_events) < num_screenshots:
        print("有效字幕数量不足，无法启动智能选择。")
        return []

    golden_start_time, golden_end_time = duration * 0.30, duration * 0.80
    golden_events = [
        e
        for e in subtitle_events
        if e["start"] >= golden_start_time and e["end"] <= golden_end_time
    ]
    print(
        f"   -> 在视频中部 ({(golden_start_time):.2f}s - {(golden_end_time):.2f}s) 找到 {len(golden_events)} 个黄金字幕事件。"
    )

    target_events = golden_events
    if len(target_events) < num_screenshots:
        print("   -> 黄金字幕数量不足，将从所有字幕事件中随机选择。")
        target_events = subtitle_events

    # 按时间先后排序事件
    target_events_sorted = sorted(target_events, key=lambda e: e["start"])

    # 智能选择分布均匀的时间段
    chosen_events = _select_well_distributed_events(target_events_sorted, num_screenshots)

    screenshot_points = []
    for i, event in enumerate(chosen_events):
        event_duration = event["end"] - event["start"]
        # 在时间段的前10%-90%之间随机选择一个点
        random_offset = event_duration * 0.1 + random.random() * (event_duration * 0.8)
        random_point = event["start"] + random_offset
        screenshot_points.append(random_point)
        print(
            f"   -> 选中时间段 [{(event['start']):.2f}s - {(event['end']):.2f}s], 截图点: {(random_point):.2f}s (第{i+1}张)"
        )

    return sorted(screenshot_points)


def _select_well_distributed_events(sorted_events, num_to_select):
    """
    从已排序的字幕事件中选择分布均匀的时间段，确保：
    1. 时间按先后顺序排列
    2. 避免选择重复或相近的时间段
    3. 时间间隔尽可能均匀分布
    """
    if len(sorted_events) <= num_to_select:
        # 如果事件数量不超过需要的数量，全部选择
        return sorted_events

    n = len(sorted_events)
    selected = []

    if num_to_select == 1:
        # 只需要一张截图，选择中间位置
        mid_index = n // 2
        selected = [sorted_events[mid_index]]
    elif num_to_select <= 3:
        # 少量截图时，选择前、中、后位置
        indices = [0, n // 2, n - 1]
        selected = [sorted_events[i] for i in indices[:num_to_select]]
    else:
        # 多张截图时，使用均匀分布算法
        # 计算大致的间隔
        interval = n // (num_to_select + 1)

        # 从第一个间隔开始选择
        for i in range(num_to_select):
            index = min(interval * (i + 1), n - 1)
            selected.append(sorted_events[index])

    # 确保选择的事件在时间上有足够间隔（至少30秒）
    filtered_selected = []
    min_interval = 30.0  # 最小时间间隔（秒）

    for event in selected:
        should_add = True
        for existing in filtered_selected:
            # 检查时间间隔
            if abs(event["start"] - existing["start"]) < min_interval:
                should_add = False
                break

        if should_add:
            filtered_selected.append(event)
        else:
            # 如果间隔太小，尝试找一个替代的位置
            for alt_event in sorted_events:
                if alt_event not in filtered_selected + selected:
                    # 检查与已选择事件的时间间隔
                    all_good = True
                    for existing in filtered_selected:
                        if abs(alt_event["start"] - existing["start"]) < min_interval:
                            all_good = False
                            break
                    if all_good:
                        filtered_selected.append(alt_event)
                        break

    # 如果过滤后数量不够，用剩余的随机事件补充
    if len(filtered_selected) < num_to_select:
        remaining = [e for e in sorted_events if e not in filtered_selected]
        needed = num_to_select - len(filtered_selected)
        if remaining and needed > 0:
            additional = random.sample(remaining, min(needed, len(remaining)))
            filtered_selected.extend(additional)

    # 按时间顺序返回
    return sorted(filtered_selected[:num_to_select], key=lambda e: e["start"])


def upload_data_screenshot(source_info, save_path, torrent_name=None, downloader_id=None):
    """
    智能通用截图上传 (含 HDR 处理与自动中文字幕挂载)：
    1. 自动命名为 s{序号}_{时}h{分}m{秒}s.png
    2. mpv 截取原始 Raw 图 (保留 HDR 信息)
    3. ffmpeg 自动检测 HDR/SDR 并应用对应滤镜 (zscale/format)
    4. 优化压缩参数 (level 4 + mixed) 平衡速度与体积
    5. 自动检测并挂载中文字幕
    """
    print("开始执行截图和上传任务 (智能 HDR/SDR + 自动中文字幕)...")
    config = config_manager.get()
    hoster = config.get("cross_seed", {}).get("image_hoster", "pixhost")
    num_screenshots = 5
    print(f"已选择图床服务: {hoster}, 截图数量: {num_screenshots}")

    # 路径映射转换
    from .media_helper import translate_path

    translated_save_path = translate_path(downloader_id, save_path)
    if translated_save_path != save_path:
        print(f"路径映射: {save_path} -> {translated_save_path}")

    if torrent_name:
        full_video_path = os.path.join(translated_save_path, torrent_name)
    else:
        full_video_path = translated_save_path

    print(f"处理视频路径: {full_video_path}")

    # --- 代理逻辑 (保持不变) ---
    use_proxy = False
    proxy_config = None
    if downloader_id:
        downloaders = config.get("downloaders", [])
        for downloader in downloaders:
            if downloader.get("id") == downloader_id:
                use_proxy = downloader.get("use_proxy", False)
                if use_proxy:
                    # (此处省略原本的复杂的host解析代码，假设保持原样即可)
                    host_value = downloader.get("host", "")
                    proxy_port = downloader.get("proxy_port", 9090)
                    if host_value.startswith(("http://", "https://")):
                        from urllib.parse import urlparse

                        parsed_url = urlparse(host_value)
                    else:
                        from urllib.parse import urlparse

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
                break

    # 初始化 content_name（用于辅助识别剧集文件）
    content_name = None
    if source_info and isinstance(source_info, dict):
        content_name = source_info.get("main_title")

    if use_proxy and proxy_config:
        print(f"使用代理处理截图: {proxy_config['proxy_base_url']}")
        try:
            response = requests.post(
                f"{proxy_config['proxy_base_url']}/api/media/screenshot",
                json={"remote_path": full_video_path, "content_name": content_name},
                timeout=600,
            )
            response.raise_for_status()
            result = response.json()
            if result.get("success"):
                print("代理截图上传成功")
                return result.get("bbcode", "")
            else:
                print(f"代理截图上传失败: {result.get('message', '未知错误')}")
                return ""
        except Exception as e:
            print(f"通过代理获取截图失败: {e}")
            return ""

    # --- 本地截图逻辑 ---

    target_video_file, is_bluray_disc = _find_target_video_file(
        full_video_path, content_name=content_name
    )
    if not target_video_file:
        print("错误：在指定路径中未找到视频文件。")
        return ""

    if is_bluray_disc:
        print("检测到原盘文件结构，但仍将进行截图处理")

    if not shutil.which("mpv"):
        print("错误：找不到 mpv。")
        return ""
    if not shutil.which("ffmpeg"):
        print("错误：找不到 ffmpeg。")
        return ""

    # 获取截图时间点
    screenshot_points = _get_smart_screenshot_points(target_video_file, num_screenshots)

    # 兜底逻辑：如果智能获取失败，按百分比获取
    if len(screenshot_points) < num_screenshots:
        print("警告: 智能分析失败，回退到按百分比截图。")
        try:
            cmd_duration = [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                target_video_file,
            ]
            result = subprocess.run(
                cmd_duration, capture_output=True, text=True, check=True, encoding="utf-8"
            )
            duration = float(result.stdout.strip())
            screenshot_points = [duration * p for p in [0.15, 0.30, 0.50, 0.70, 0.85]]
        except Exception as e:
            print(f"错误: 获取视频时长失败: {e}")
            return ""

    # 自动检测中文字幕轨道
    print("正在分析字幕流...")
    subtitle_sid = _get_best_chinese_subtitle_sid(target_video_file)
    if not subtitle_sid:
        print("   ℹ️ 未检测到明确的中文字幕，将截取无字幕画面。")

    auth_token = _get_agsv_auth_token() if hoster == "agsv" else None
    if hoster == "agsv" and not auth_token:
        print("❌ 无法获取 Token，任务终止。")
        return ""

    uploaded_urls = []
    temp_files_to_cleanup = []

    for i, point in enumerate(screenshot_points):
        # --- 1. 计算文件名 (s1_00h15m30s.png) ---
        total_seconds = int(point)
        m, s = divmod(total_seconds, 60)
        h, m = divmod(m, 60)
        time_str = f"{h:02d}h{m:02d}m{s:02d}s"

        file_name = f"s{i+1}_{time_str}.png"

        # 中间文件加 raw_ 前缀
        intermediate_png_path = os.path.join(TEMP_DIR, f"raw_{file_name}")
        # 最终输出文件
        final_png_path = os.path.join(TEMP_DIR, file_name)

        temp_files_to_cleanup.extend([intermediate_png_path, final_png_path])

        print(f"\n--- 处理第 {i+1}/{len(screenshot_points)} 张截图 ({time_str}) ---")

        # --- 2. MPV 截图 (Raw output, 无色调映射) ---
        cmd_screenshot = [
            "mpv",
            "--no-audio",
            f"--start={point:.2f}",
            "--frames=1",
            # 关键修改：移除所有 tone-mapping 参数，保留原始 HDR 数据
            "--screenshot-high-bit-depth=yes",  # 保留位深
            "--screenshot-png-compression=0",  # 关闭压缩 (速度最快)
            "--screenshot-tag-colorspace=yes",  # 写入色彩标签
            f"--o={intermediate_png_path}",
        ]

        # 关键优化：挂载字幕
        if subtitle_sid:
            cmd_screenshot.append(f"--sid={subtitle_sid}")
            cmd_screenshot.append("--sub-visibility=yes")
        else:
            cmd_screenshot.append("--sid=no")

        cmd_screenshot.append(target_video_file)

        try:
            subprocess.run(cmd_screenshot, check=True, capture_output=True, timeout=600)

            if not os.path.exists(intermediate_png_path):
                print(f"❌ mpv 未生成文件: {intermediate_png_path}")
                continue

            # --- 3. FFmpeg 智能处理 (检测 HDR -> 转换 -> 压缩) ---

            # 3.1 检测 HDR
            is_hdr = False
            try:
                check_cmd = ["ffprobe", "-v", "error", "-show_streams", intermediate_png_path]
                check_res = subprocess.run(check_cmd, capture_output=True, text=True)
                if "smpte2084" in check_res.stdout or "bt2020" in check_res.stdout:
                    is_hdr = True
            except Exception as e:
                print(f"   ⚠️ 检测 HDR 信息失败，假定为 SDR: {e}")

            # 3.2 构建滤镜链
            if is_hdr:
                print("   🎨 检测到 HDR 原始内容，应用 zscale 色调映射...")
                vf_filter = "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=pc,format=rgb24"
            else:
                print("   🎨 检测到 SDR 内容，应用标准 RGB 转换...")
                vf_filter = "format=rgb24"

            # 3.3 执行压缩 (Level 4 + Mixed)
            cmd_compress = [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                intermediate_png_path,
                "-frames:v",
                "1",
                "-vf",
                vf_filter,
                "-compression_level",
                "4",  # 速度快且体积小
                "-pred",
                "mixed",  # 关键优化参数
                final_png_path,
            ]

            start_compress = time.time()
            subprocess.run(cmd_compress, check=True, capture_output=True, timeout=600)
            compress_time = time.time() - start_compress

            # 统计信息
            src_size = os.path.getsize(intermediate_png_path)
            dst_size = os.path.getsize(final_png_path)
            ratio = (dst_size / src_size) * 100
            print(
                f"   ✅ 优化完成: {dst_size/1024/1024:.2f} MB (原图 {ratio:.1f}%) | 耗时 {compress_time:.2f}s | HDR: {is_hdr}"
            )

            # --- 4. 上传 ---
            max_retries = 3
            image_url = None
            for attempt in range(max_retries):
                try:
                    if hoster == "agsv":
                        image_url = _upload_to_agsv(final_png_path, auth_token)
                    else:
                        image_url = _upload_to_pixhost(final_png_path)

                    if image_url:
                        uploaded_urls.append(image_url)
                        print(f"   🚀 上传成功: {image_url}")
                        break
                    else:
                        time.sleep(2)
                except Exception as e:
                    print(f"   ⚠️ 上传重试 {attempt+1}: {e}")
                    time.sleep(2)

            if not image_url:
                print(f"   ❌ 第 {i+1} 张图片上传失败")

        except subprocess.CalledProcessError as e:
            print(f"❌ 流程执行出错: {e}")
            continue
        except subprocess.TimeoutExpired:
            print(f"❌ 操作超时")
            continue

    # --- 清理与返回 ---
    print(f"\n清理 {len(temp_files_to_cleanup)} 个临时文件...")
    for item in temp_files_to_cleanup:
        try:
            if os.path.exists(item):
                os.remove(item)
        except:
            pass

    if not uploaded_urls:
        return ""

    bbcode_links = []
    # 简单排序确保顺序
    for url in sorted(uploaded_urls):
        if "pixhost.to/show/" in url:
            direct_url = _convert_pixhost_url_to_direct(url)
            bbcode_links.append(f"[img]{direct_url or url}[/img]")
        else:
            bbcode_links.append(f"[img]{url}[/img]")

    return "\n".join(bbcode_links)


def is_image_url_valid_robust(url: str) -> bool:
    """
    一个更稳健的方法，当HEAD请求失败时，会尝试使用GET请求（流式）进行验证。
    如果直接请求失败，会尝试使用全局代理重试一次。
    """
    if not url:
        return False

    # 第一次尝试：不使用代理
    try:
        # 首先尝试HEAD请求，允许重定向
        response = requests.head(url, timeout=5, allow_redirects=True)
        response.raise_for_status()  # 如果状态码不是2xx，则抛出异常

        # 检查Content-Type
        content_type = response.headers.get("Content-Type")
        if content_type and content_type.startswith("image/"):
            return True
        else:
            logging.warning(f"链接有效但内容可能不是图片: {url} (Content-Type: {content_type})")
            return False

    except requests.exceptions.RequestException:
        # 如果HEAD请求失败，尝试GET请求
        try:
            response = requests.get(url, stream=True, timeout=5, allow_redirects=True)
            response.raise_for_status()

            # 检查Content-Type
            content_type = response.headers.get("Content-Type")
            if content_type and content_type.startswith("image/"):
                return True
            else:
                logging.warning(
                    f"链接有效但内容可能不是图片: {url} (Content-Type: {content_type})"
                )
                return False

        except requests.exceptions.RequestException as e:
            logging.warning(f"图片链接GET请求也失败了: {url} - {e}")

            # 不使用全局代理重试，直接返回失败
            return False
