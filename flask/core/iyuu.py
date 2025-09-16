# core/iyuu.py
import logging
import time
import os
import requests
import json
import hashlib
from threading import Thread
from collections import defaultdict


class IYUUThread(Thread):
    """IYUU后台线程，定期聚合种子信息并进行相关处理。"""

    def __init__(self, db_manager, config_manager):
        super().__init__(daemon=True, name="IYUUThread")
        self.db_manager = db_manager
        self.config_manager = config_manager
        self._is_running = True
        # 设置为30秒运行一次
        self.interval = 3000

    def run(self):
        print("IYUUThread 线程已启动，每30秒执行一次种子聚合任务。")
        # 等待5秒再开始执行，避免与主程序启动冲突
        time.sleep(5)

        while self._is_running:
            start_time = time.monotonic()
            try:
                self._process_torrents()
            except Exception as e:
                logging.error(f"IYUUThread 执行出错: {e}", exc_info=True)

            # 等待下次执行
            elapsed = time.monotonic() - start_time
            time.sleep(max(0, self.interval - elapsed))

    def _process_torrents(self):
        """处理种子数据，按name列进行聚合"""
        print("=== 开始执行IYUU种子聚合任务 ===")
        conn = None
        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)

            # 查询所有种子数据，只筛选体积大于1GB的种子（1GB = 1073741824字节）
            cursor.execute(
                "SELECT hash, name, sites, size FROM torrents WHERE name IS NOT NULL AND name != '' AND size > 1073741824"
            )
            torrents_raw = [dict(row) for row in cursor.fetchall()]

            # 按种子名称进行聚合
            agg_torrents = defaultdict(list)
            for t in torrents_raw:
                torrent_name = t['name']
                agg_torrents[torrent_name].append({
                    'hash': t['hash'],
                    'sites': t.get('sites', None),
                    'size': t.get('size', 0)
                })

            # 准备写入文件的内容
            output_lines = []
            output_lines.append("=== IYUU种子聚合结果 ===\n")
            output_lines.append(
                f"聚合时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            output_lines.append(f"共聚合了 {len(agg_torrents)} 个唯一种子组\n")
            output_lines.append("=" * 50 + "\n")

            # 生成聚合结果
            for name, torrents in agg_torrents.items():
                # 选择一个hash用于后续的IYUU搜索
                selected_hash = torrents[0]['hash'] if torrents else None
                sites_list = [t['sites'] for t in torrents if t['sites']]

                # 添加聚合信息到输出内容
                output_lines.append(f"[IYUU] 种子组: {name}\n")
                output_lines.append(f"  - 包含 {len(torrents)} 个种子\n")
                output_lines.append(f"  - 选择的hash: {selected_hash}\n")
                output_lines.append(
                    f"  - 存在于站点: {', '.join(sites_list) if sites_list else '无'}\n"
                )
                output_lines.append("---\n")

            output_lines.append("=" * 50 + "\n")
            output_lines.append("=== IYUU种子聚合任务执行完成 ===\n")

            # 确保tmp目录存在
            tmp_dir = "/app/Code/Dockerfile/Docker.pt-nexus/flask/data/tmp"
            if not os.path.exists(tmp_dir):
                os.makedirs(tmp_dir)

            # 写入文件
            timestamp = int(time.time())
            output_file = os.path.join(tmp_dir,
                                       f"iyuu_aggregation_{timestamp}.txt")
            with open(output_file, 'w', encoding='utf-8') as f:
                f.writelines(output_lines)

            print(f"IYUU种子聚合结果已保存到: {output_file}")

            # 执行IYUU搜索逻辑
            self._perform_iyuu_search(agg_torrents)

            print("=== IYUU种子聚合任务执行完成 ===")

        except Exception as e:
            logging.error(f"处理种子数据时出错: {e}", exc_info=True)
        finally:
            if conn:
                if 'cursor' in locals() and cursor:
                    cursor.close()
                conn.close()

    def _perform_iyuu_search(self, agg_torrents):
        """执行IYUU搜索逻辑"""
        try:
            # 获取IYUU token
            config = self.config_manager.get()
            iyuu_token = config.get("iyuu_token", "")

            if not iyuu_token:
                logging.warning("IYUU Token未配置，跳过IYUU搜索。")
                return

            print(f"开始执行IYUU搜索，共 {len(agg_torrents)} 个种子组")

            # 获取站点信息
            all_sites = get_all_sites(iyuu_token)
            sid_sha1 = get_sid_sha1(iyuu_token, all_sites)

            # 创建站点映射
            sites_map = {site['id']: site for site in all_sites}

            # 只处理前3个种子组用于测试
            test_torrents = list(agg_torrents.items())[:3]

            for i, (name, torrents) in enumerate(test_torrents):
                if not self._is_running:  # 检查线程是否应该停止
                    break

                # 选择一个hash用于搜索
                selected_hash = torrents[0]['hash'] if torrents else None
                if not selected_hash:
                    continue

                print(f"正在处理第 {i+1} 个种子组: {name}")
                print(f"使用的hash: {selected_hash}")

                try:
                    # 执行搜索
                    results = query_cross_seed(iyuu_token, selected_hash,
                                               sid_sha1)

                    # 打印搜索结果
                    if not results:
                        print(f"种子 {selected_hash[:8]}... 未在其他站点发现。")
                    else:
                        print(
                            f"种子 {selected_hash[:8]}... 在 {len(results)} 个地方发现！"
                        )

                        for item in results:
                            sid = item.get("sid")
                            site_info = sites_map.get(sid)

                            if not site_info:
                                print(f" - 在未知站点 (SID: {sid}) 发现")
                                continue

                            scheme = "https" if site_info.get(
                                "is_https") != 0 else "http"
                            details_page = site_info.get(
                                "details_page", "details.php?id={}").replace(
                                    "{}", str(item.get("torrent_id")))
                            full_url = f"{scheme}://{site_info.get('base_url', '')}/{details_page}"

                            site_name = site_info.get(
                                "nickname") or site_info.get(
                                    "site") or f"SID {sid}"

                            print(f"✅ 站点: {site_name}")
                            print(f"   链接: {full_url}")

                    # 每次查询之间间隔30秒（除了最后一个）
                    if i < len(test_torrents) - 1:
                        print("等待30秒后进行下一次查询...")
                        for _ in range(30):  # 每秒检查一次是否需要停止
                            if not self._is_running:
                                return
                            time.sleep(1)

                except Exception as e:
                    logging.error(f"处理种子 {selected_hash[:8]}... 时出错: {e}",
                                  exc_info=True)
                    # 继续处理下一个种子
                    continue

        except Exception as e:
            logging.error(f"IYUU搜索执行出错: {e}", exc_info=True)

    def stop(self):
        """停止线程"""
        print("正在停止 IYUUThread 线程...")
        self._is_running = False


# --- IYUU API 配置 ---
API_BASE = "https://2025.iyuu.cn"
CLIENT_VERSION = "8.2.0"

# --- IYUU API 辅助函数 ---


def get_sha1_hex(text: str) -> str:
    """计算字符串的 SHA-1 哈希值"""
    return hashlib.sha1(text.encode('utf-8')).hexdigest()


def make_api_request(method: str, url: str, token: str, **kwargs) -> dict:
    """
    封装 API 请求，统一处理 headers 和错误。
    """
    # 基础 headers，包含 Token
    final_headers = {'Token': token}

    # 如果调用时传入了额外的 headers (如 Content-Type)，则进行合并
    if 'headers' in kwargs:
        # 使用 update 方法将传入的 headers 合并进来
        final_headers.update(kwargs.pop('headers'))

    try:
        if method.upper() == 'GET':
            response = requests.get(url,
                                    headers=final_headers,
                                    timeout=20,
                                    **kwargs)
        elif method.upper() == 'POST':
            response = requests.post(url,
                                     headers=final_headers,
                                     timeout=20,
                                     **kwargs)
        else:
            raise ValueError("Unsupported HTTP method")

        response.raise_for_status()  # 如果状态码不是 2xx，则抛出异常

        data = response.json()
        if data.get("code") != 0:
            error_msg = data.get("msg", "未知 API 错误")
            raise Exception(f"API 错误: {error_msg} (代码: {data.get('code')})")

        return data

    except requests.exceptions.RequestException as e:
        raise Exception(f"网络请求失败: {e}")
    except json.JSONDecodeError:
        raise Exception("无法解析服务器返回的 JSON 数据")


def get_all_sites(token: str) -> list:
    """获取 IYUU 支持的所有站点信息"""
    print("正在获取 IYUU 支持的站点列表...")
    url = f"{API_BASE}/reseed/sites/index"
    response_data = make_api_request("GET", url, token)
    sites = response_data.get("data", {}).get("sites", [])
    if not sites:
        raise Exception("未能获取到站点列表，请检查 Token 或 IYUU 服务状态。")
    print(f"成功获取到 {len(sites)} 个站点信息。")
    return sites


def get_sid_sha1(token: str, all_sites: list) -> str:
    """根据站点列表上报并获取 sid_sha1"""
    print("正在生成站点校验哈希 (sid_sha1)...")
    url = f"{API_BASE}/reseed/sites/reportExisting"
    site_ids = [site['id'] for site in all_sites]
    payload = {"sid_list": site_ids}

    # 这里的 headers 会被正确合并
    headers = {'Content-Type': 'application/json'}
    response_data = make_api_request("POST",
                                     url,
                                     token,
                                     json=payload,
                                     headers=headers)

    sid_sha1 = response_data.get("data", {}).get("sid_sha1")
    if not sid_sha1:
        raise Exception("未能从 API 获取 sid_sha1。")
    print("成功生成 sid_sha1。")
    return sid_sha1


def query_cross_seed(token: str, infohash: str, sid_sha1: str) -> list:
    """查询指定 infohash 的辅种信息"""
    print(f"正在为种子 {infohash[:8]}... 查询辅种信息...")
    url = f"{API_BASE}/reseed/index/index"

    hashes_json_str = json.dumps([infohash.lower()])
    form_data = {
        "hash": hashes_json_str,
        "sha1": get_sha1_hex(hashes_json_str),
        "sid_sha1": sid_sha1,
        "timestamp": str(int(time.time())),
        "version": CLIENT_VERSION
    }

    # 这里的 headers 也会被正确合并
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    response_data = make_api_request("POST",
                                     url,
                                     token,
                                     data=form_data,
                                     headers=headers)

    data = response_data.get("data", {})
    if not data or infohash.lower() not in data:
        return []

    results = data[infohash.lower()].get("torrent", [])
    return results


# 全局变量
iyuu_thread = None


def start_iyuu_thread(db_manager, config_manager):
    """初始化并启动全局 IYUUThread 线程实例。"""
    global iyuu_thread
    # 检查是否在调试模式下运行，避免重复启动
    import os
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        # 在调试模式下，这是监控进程，不需要启动线程
        print("检测到调试监控进程，跳过IYUU线程启动。")
        return iyuu_thread

    if iyuu_thread is None or not iyuu_thread.is_alive():
        iyuu_thread = IYUUThread(db_manager, config_manager)
        iyuu_thread.start()
        print("已创建并启动新的 IYUUThread 实例。")
    return iyuu_thread


def stop_iyuu_thread():
    """停止并清理当前的 IYUUThread 线程实例。"""
    global iyuu_thread
    if iyuu_thread and iyuu_thread.is_alive():
        iyuu_thread.stop()
        iyuu_thread.join(timeout=10)
        print("IYUUThread 线程已停止。")
    iyuu_thread = None
