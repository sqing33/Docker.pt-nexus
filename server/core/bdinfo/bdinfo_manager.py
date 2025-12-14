#!/usr/bin/env python3
"""
BDInfo 任务管理器
负责管理 BDInfo 异步获取任务，支持优先级队列和并发控制
"""

import logging
import os
import subprocess
import threading
import time
import uuid
import requests
from datetime import datetime
from queue import PriorityQueue, Empty
from typing import Dict, Optional, List, Tuple


class BDInfoTask:
    """BDInfo 任务类"""

    def __init__(self, seed_id: str, save_path: str, priority: int = 2, downloader_id: str = None):
        self.id = str(uuid.uuid4())
        self.seed_id = seed_id
        self.save_path = save_path
        self.downloader_id = downloader_id
        self.priority = priority  # 1=高优先级(单个), 2=普通优先级(批量)
        self.status = "queued"
        self.created_at = datetime.now()
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.error_message: Optional[str] = None
        self.result: Optional[str] = None
        # 进度相关字段
        self.progress_percent: float = 0.0
        self.current_file: str = ""
        self.elapsed_time: str = ""
        self.remaining_time: str = ""
        # 进程跟踪字段
        self.process: Optional[subprocess.Popen] = None  # 子进程引用
        self.process_pid: Optional[int] = None  # 进程PID
        self.last_progress_update: Optional[datetime] = None  # 最后进度更新时间
        self.last_progress_percent: float = 0.0  # 最后进度百分比
        self.temp_file_path: Optional[str] = None  # 临时文件路径
        self.last_progress_data: Optional[Dict] = None  # 缓存的最新进度数据
        # 远程执行相关字段
        self.execution_mode: str = "local"  # "local" | "remote"
        self.remote_proxy_url: str = ""  # 远程代理URL
        self.remote_task_status: str = "pending"  # "pending" | "running" | "completed" | "failed"
        self.last_remote_update: Optional[datetime] = None  # 最后远程更新时间

    def __lt__(self, other):
        """优先级队列排序：优先级数字越小越优先"""
        return self.priority < other.priority

    def to_dict(self) -> Dict:
        """转换为字典格式"""
        return {
            "id": self.id,
            "seed_id": self.seed_id,
            "status": self.status,
            "priority": self.priority,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error_message": self.error_message,
            "result": self.result,
            "progress_percent": self.progress_percent,
            "current_file": self.current_file,
            "elapsed_time": self.elapsed_time,
            "remaining_time": self.remaining_time,
            "process_pid": self.process_pid,
            "last_progress_update": (
                self.last_progress_update.isoformat() if self.last_progress_update else None
            ),
            "last_progress_percent": self.last_progress_percent,
            "execution_mode": self.execution_mode,
            "remote_proxy_url": self.remote_proxy_url,
            "remote_task_status": self.remote_task_status,
            "last_remote_update": (
                self.last_remote_update.isoformat() if self.last_remote_update else None
            ),
        }


class BDInfoManager:
    """BDInfo 任务管理器"""

    def __init__(self, max_concurrent_tasks: int = 1):
        self.tasks: Dict[str, BDInfoTask] = {}
        self.task_queue = PriorityQueue()
        self.max_concurrent_tasks = max_concurrent_tasks
        self.running_tasks: Dict[str, threading.Thread] = {}
        self.is_running = False
        self.worker_thread: Optional[threading.Thread] = None
        self.lock = threading.RLock()

        # 轮询配置
        self.remote_poll_interval = 3  # 远程任务轮询间隔（秒）
        self.remote_timeout = 30 * 60  # 远程任务超时时间（秒）

        # 统计信息
        self.stats = {
            "total_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "running_tasks": 0,
            "queued_tasks": 0,
        }

    def start(self):
        """启动 BDInfo 管理器"""
        with self.lock:
            if not self.is_running:
                self.is_running = True
                self.worker_thread = threading.Thread(
                    target=self._worker_loop, name="BDInfoManager-Worker", daemon=True
                )
                self.worker_thread.start()

                # 启动健康监控线程
                self.health_monitor_thread = threading.Thread(
                    target=self._health_monitor_loop,
                    name="BDInfoManager-HealthMonitor",
                    daemon=True,
                )
                self.health_monitor_thread.start()

                # 启动时恢复遗留任务
                self.recover_orphaned_tasks()

                logging.info("BDInfo 管理器已启动")

    def stop(self):
        """停止 BDInfo 管理器"""
        with self.lock:
            self.is_running = False
            if self.worker_thread:
                self.worker_thread.join(timeout=5)
            logging.info("BDInfo 管理器已停止")

    def add_task(
        self, seed_id: str, save_path: str, priority: int = 2, downloader_id: str = None
    ) -> str:
        """添加 BDInfo 任务

        Args:
            seed_id: 种子ID
            save_path: 保存路径
            priority: 优先级 (1=高优先级, 2=普通优先级)
            downloader_id: 下载器ID

        Returns:
            任务ID
        """
        with self.lock:
            task = BDInfoTask(seed_id, save_path, priority, downloader_id)

            # 检查是否需要使用远程执行
            if self._should_use_remote(downloader_id, save_path):
                task.execution_mode = "remote"
                proxy_config = self._get_downloader_proxy_config(downloader_id)
                if proxy_config:
                    task.remote_proxy_url = proxy_config["proxy_base_url"]
                    logging.info(f"BDInfo 任务 {task.id} 将使用远程执行: {task.remote_proxy_url}")

            self.tasks[task.id] = task
            self.task_queue.put(task)

            # 更新统计信息
            self.stats["total_tasks"] += 1
            self.stats["queued_tasks"] += 1

            # 更新数据库状态 - 初始状态设为等待中
            self._update_task_status(task.seed_id, "queued", task.id)

            # 设置SSE执行模式
            try:
                from utils.sse_manager import sse_manager

                sse_manager.set_execution_mode(seed_id, task.execution_mode)
            except Exception as e:
                logging.error(f"设置SSE执行模式失败: {e}")

            logging.info(
                f"BDInfo 任务已添加: {task.id} (种子ID: {seed_id}, 优先级: {priority}, 执行模式: {task.execution_mode})"
            )
            return task.id

    def _should_use_remote(self, downloader_id: str, save_path: str) -> bool:
        """判断是否应该使用远程处理"""
        if not downloader_id:
            return False

        proxy_config = self._get_downloader_proxy_config(downloader_id)

        if not proxy_config:
            return False

        # 检查是否支持BDInfo
        if not proxy_config.get("supports_bdinfo", False):
            return False

        # 可以根据需要添加更多检查逻辑
        # 例如：检查路径是否在远程服务器上等
        return True

    def _get_downloader_proxy_config(self, downloader_id: str) -> Optional[Dict]:
        """获取下载器的代理配置"""
        try:
            from config import config_manager

            config = config_manager.get()

            if not config:
                logging.error("无法加载配置: config 为空")
                return None

            downloaders = config.get("downloaders", [])

            for downloader in downloaders:
                if str(downloader.get("id")) == str(downloader_id):
                    # 检查新的配置结构：use_proxy + proxy_port
                    if downloader.get("use_proxy", False):
                        host = downloader.get("host", "")
                        proxy_port = downloader.get("proxy_port", 9090)

                        # 智能处理host字段
                        if "://" in host and ":" in host.split("://")[1]:
                            host_without_port = (
                                host.split(":")[0] + "://" + host.split("://")[1].split(":")[0]
                            )
                            proxy_base_url = f"{host_without_port}:{proxy_port}"
                        else:
                            host_clean = (
                                host.replace("http://", "").replace("https://", "").rstrip("/")
                            )
                            proxy_base_url = f"http://{host_clean}:{proxy_port}"

                        if host and proxy_port:
                            return {"proxy_base_url": proxy_base_url, "supports_bdinfo": True}

                    # 检查旧的配置结构：proxy.enabled
                    proxy = downloader.get("proxy", {})
                    if proxy.get("enabled", False):
                        proxy_host = (
                            proxy.get("host", "")
                            .replace("http://", "")
                            .replace("https://", "")
                            .rstrip("/")
                        )
                        proxy_port = proxy.get("port", 9090)

                        if proxy_host and proxy_port:
                            return {
                                "proxy_base_url": f"http://{proxy_host}:{proxy_port}",
                                "supports_bdinfo": True,
                            }

        except Exception as e:
            logging.error(f"获取下载器代理配置失败: {e}", exc_info=True)

        return None

    def _submit_remote_task(self, task: BDInfoTask) -> bool:
        """提交远程BDInfo任务"""
        try:
            # 首先更新数据库状态为开始处理
            self._update_task_status(
                task.seed_id, "processing_bdinfo", task.id, started_at=datetime.now()
            )

            url = f"{task.remote_proxy_url}/api/media/bdinfo"
            payload = {
                "remote_path": task.save_path,
                "task_id": task.id,
                # 不传递 callback_url，使用轮询模式
            }

            response = requests.post(
                url, json=payload, timeout=10
            )  # 减少超时时间，因为现在立即返回

            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    task.remote_task_status = "running"
                    task.last_remote_update = datetime.now()
                    logging.info(f"远程BDInfo任务提交成功: {task.id}")
                    return True
                else:
                    task.error_message = data.get("message", "远程任务提交失败")
                    logging.error(f"远程BDInfo任务提交失败: {task.id} - {task.error_message}")
            else:
                task.error_message = f"远程服务器错误: HTTP {response.status_code}"
                logging.error(f"远程BDInfo任务提交失败: {task.id} - {task.error_message}")

        except requests.exceptions.Timeout as e:
            task.error_message = f"远程任务提交超时: {str(e)}"
            logging.error(f"远程BDInfo任务提交超时: {task.id} - {e}")
        except requests.exceptions.ConnectionError as e:
            task.error_message = f"远程任务连接失败: {str(e)}"
            logging.error(f"远程BDInfo任务连接失败: {task.id} - {e}")
        except Exception as e:
            task.error_message = f"远程任务提交异常: {str(e)}"
            logging.error(f"远程BDInfo任务提交异常: {task.id} - {task.error_message}")

        return False

    def _get_callback_url(self) -> str:
        """获取主服务的回调URL"""
        try:
            from config import config_manager

            config = config_manager.get()

            # 获取主服务端口和主机信息
            host = config.get("host", "127.0.0.1")
            port = config.get("port", 5275)

            # 如果host是localhost或127.0.0.1，尝试获取实际的网络IP
            if host in ["localhost", "127.0.0.1", "0.0.0.0"]:
                # 尝试从环境变量获取实际IP
                import os

                actual_host = os.getenv(
                    "PYTHON_SERVER_HOST", "192.168.1.100"
                )  # 默认使用你的内网IP
                print(f"[DEBUG] 检测到本地host，使用实际IP: {actual_host}")
                host = actual_host

            # 构建回调URL基础路径
            callback_base = f"http://{host}:{port}/api/migrate/bdinfo"
            print(f"[DEBUG] 构建的回调URL: {callback_base}")

            return callback_base
        except Exception as e:
            logging.error(f"获取回调URL失败: {e}")
            # 返回默认值（使用实际网络IP）
            return "http://192.168.1.100:5275/api/migrate/bdinfo"

    def _poll_remote_task_progress(self, task: BDInfoTask):
        """轮询远程任务进度"""
        # 注意：这个方法在单独的线程中运行
        try:
            # 检查是否有回调URL，如果有则使用回调模式，否则使用轮询模式
            callback_url = getattr(task, "callback_url", None)

            if callback_url:
                # 回调模式：等待代理回调通知完成
                logging.info(f"远程BDInfo任务 {task.id} 使用回调模式，等待完成通知")
                self._wait_for_callback_completion(task)
            else:
                # 轮询模式：新的轮询逻辑
                logging.info(f"远程BDInfo任务 {task.id} 使用轮询模式")
                self._poll_remote_progress_with_polling(task)

        except Exception as e:
            task.status = "failed"
            task.error_message = f"远程任务执行异常: {str(e)}"
            task.remote_task_status = "failed"
            task.completed_at = datetime.now()

            # 更新统计信息
            self.stats["failed_tasks"] += 1

            # 更新数据库
            self._update_task_status(
                task.seed_id,
                "failed",
                task.id,
                completed_at=task.completed_at,
                error_message=task.error_message,
            )

            logging.error(f"远程BDInfo任务异常: {task.id} - {task.error_message}", exc_info=True)

    def _wait_for_callback_completion(self, task: BDInfoTask):
        """等待回调完成通知"""
        # 设置超时时间：30分钟
        timeout = 30 * 60  # 30分钟
        start_time = time.time()

        while time.time() - start_time < timeout:
            with self.lock:
                if task.status in ["completed", "failed"]:
                    # 任务已经通过回调更新完成
                    logging.info(f"远程BDInfo任务 {task.id} 通过回调完成，状态: {task.status}")
                    return

            # 每5秒检查一次
            time.sleep(5)

        # 超时处理
        with self.lock:
            if task.status not in ["completed", "failed"]:
                task.status = "failed"
                task.error_message = "远程任务执行超时"
                task.remote_task_status = "failed"
                task.completed_at = datetime.now()

                # 更新统计信息
                self.stats["failed_tasks"] += 1

                # 更新数据库
                self._update_task_status(
                    task.seed_id,
                    "failed",
                    task.id,
                    completed_at=task.completed_at,
                    error_message=task.error_message,
                )

                logging.error(f"远程BDInfo任务超时: {task.id}")

    def _poll_remote_progress_with_polling(self, task: BDInfoTask):
        """轮询远程任务进度（新的轮询机制）"""
        # 首先提交远程任务（不使用回调）
        url = f"{task.remote_proxy_url}/api/media/bdinfo"
        payload = {
            "remote_path": task.save_path,
            "task_id": task.id,
            # 不传递 callback_url，使用轮询模式
        }

        try:
            response = requests.post(
                url, json=payload, timeout=10
            )  # 减少超时时间，因为现在立即返回
            if response.status_code != 200:
                task.status = "failed"
                task.error_message = f"远程任务提交失败: HTTP {response.status_code}"
                task.remote_task_status = "failed"
                task.completed_at = datetime.now()

                self.stats["failed_tasks"] += 1
                self._update_task_status(
                    task.seed_id,
                    "failed",
                    task.id,
                    completed_at=task.completed_at,
                    error_message=task.error_message,
                )
                logging.error(f"远程BDInfo任务提交失败: {task.id} - {task.error_message}")
                return

            data = response.json()
            if not data.get("success"):
                task.status = "failed"
                task.error_message = data.get("message", "远程任务提交失败")
                task.remote_task_status = "failed"
                task.completed_at = datetime.now()

                self.stats["failed_tasks"] += 1
                self._update_task_status(
                    task.seed_id,
                    "failed",
                    task.id,
                    completed_at=task.completed_at,
                    error_message=task.error_message,
                )
                logging.error(f"远程BDInfo任务提交失败: {task.id} - {task.error_message}")
                return

            task.remote_task_status = "running"
            task.last_remote_update = datetime.now()
            logging.info(f"远程BDInfo任务提交成功: {task.id}")

        except Exception as e:
            task.status = "failed"
            task.error_message = f"远程任务提交异常: {str(e)}"
            task.remote_task_status = "failed"
            task.completed_at = datetime.now()

            self.stats["failed_tasks"] += 1
            self._update_task_status(
                task.seed_id,
                "failed",
                task.id,
                completed_at=task.completed_at,
                error_message=task.error_message,
            )
            logging.error(f"远程BDInfo任务提交异常: {task.id} - {task.error_message}")
            return

        # 开始轮询进度
        progress_url = f"{task.remote_proxy_url}/api/media/bdinfo/progress/{task.id}"
        timeout = self.remote_timeout  # 使用配置的超时时间
        start_time = time.time()
        poll_interval = self.remote_poll_interval  # 使用配置的轮询间隔

        logging.info(
            f"开始轮询远程任务进度: {task.id}, 进度URL: {progress_url}, 轮询间隔: {poll_interval}秒"
        )

        while time.time() - start_time < timeout:
            try:
                # 轮询进度
                response = requests.get(progress_url, timeout=10)

                if response.status_code == 200:
                    progress_data = response.json()
                    if progress_data.get("success"):
                        task_info = progress_data.get("task", {})

                        # 更新任务进度
                        task.progress_percent = task_info.get("progress_percent", 0)
                        task.current_file = task_info.get("current_file", "")
                        task.elapsed_time = task_info.get("elapsed_time", "")
                        task.remaining_time = task_info.get("remaining_time", "")
                        task.remote_task_status = task_info.get("status", "running")
                        task.last_remote_update = datetime.now()

                        # 获取Disc Size信息
                        disc_size = task_info.get("disc_size", 0)

                        # 发送SSE进度更新
                        try:
                            from utils.sse_manager import sse_manager

                            progress_data = {
                                "progress_percent": task.progress_percent,
                                "current_file": task.current_file,
                                "elapsed_time": task.elapsed_time,
                                "remaining_time": task.remaining_time,
                            }

                            # 如果有Disc Size信息，添加到进度数据中
                            if disc_size > 0:
                                progress_data["disc_size"] = disc_size
                                progress_data["disc_size_gb"] = round(disc_size / (1024**3), 2)

                            sse_manager.send_progress_update(task.seed_id, progress_data)
                        except Exception as e:
                            logging.error(f"发送SSE进度更新失败: {e}")

                        # 检查是否完成
                        if task.remote_task_status == "completed":
                            task.result = task_info.get("bdinfo_content", "")
                            task.status = "completed"
                            task.completed_at = datetime.now()

                            # 更新统计信息
                            self.stats["completed_tasks"] += 1

                            # 更新数据库
                            self._update_seed_mediainfo(task.seed_id, task.result)
                            self._update_task_status(
                                task.seed_id, "completed", task.id, completed_at=task.completed_at
                            )

                            # 发送SSE完成通知
                            try:
                                from utils.sse_manager import sse_manager

                                sse_manager.send_completion(task.seed_id, task.result)
                            except Exception as e:
                                logging.error(f"发送SSE完成通知失败: {e}")

                            logging.info(f"远程BDInfo任务完成: {task.id}")
                            return

                        elif task.remote_task_status == "failed":
                            task.status = "failed"
                            task.error_message = task_info.get(
                                "error_message", "远程BDInfo提取失败"
                            )
                            task.completed_at = datetime.now()

                            # 更新统计信息
                            self.stats["failed_tasks"] += 1

                            # 更新数据库
                            self._update_task_status(
                                task.seed_id,
                                "failed",
                                task.id,
                                completed_at=task.completed_at,
                                error_message=task.error_message,
                            )

                            # 发送SSE错误通知
                            try:
                                from utils.sse_manager import sse_manager

                                sse_manager.send_error(task.seed_id, task.error_message)
                            except Exception as e:
                                logging.error(f"发送SSE错误通知失败: {e}")

                            logging.error(f"远程BDInfo任务失败: {task.id} - {task.error_message}")
                            return
                        else:
                            # 任务仍在运行，记录进度
                            logging.debug(
                                f"远程任务进度更新: {task.id}, 进度: {task.progress_percent}%, 文件: {task.current_file}"
                            )

                elif response.status_code == 404:
                    # 任务不存在，可能已完成或失败
                    logging.warning(f"远程任务进度查询返回404，任务可能已完成: {task.id}")
                    # 等待一段时间后重试
                    time.sleep(poll_interval)
                    continue

                else:
                    logging.warning(
                        f"远程任务进度查询失败: HTTP {response.status_code}, 任务ID: {task.id}"
                    )

            except requests.exceptions.Timeout:
                logging.warning(f"远程任务进度查询超时: {task.id}")
            except Exception as e:
                logging.error(f"远程任务进度查询异常: {task.id} - {e}")

            # 等待下次轮询
            time.sleep(poll_interval)

        # 超时处理
        task.status = "failed"
        task.error_message = "远程任务执行超时"
        task.remote_task_status = "failed"
        task.completed_at = datetime.now()

        # 更新统计信息
        self.stats["failed_tasks"] += 1

        # 更新数据库
        self._update_task_status(
            task.seed_id,
            "failed",
            task.id,
            completed_at=task.completed_at,
            error_message=task.error_message,
        )

        logging.error(f"远程BDInfo任务超时: {task.id}")

    def _poll_sync_execution(self, task: BDInfoTask):
        """同步执行轮询模式"""
        url = f"{task.remote_proxy_url}/api/media/bdinfo"
        payload = {"remote_path": task.save_path, "task_id": task.id}

        # 发起请求，这会阻塞直到完成
        response = requests.post(url, json=payload, timeout=600)  # 10分钟超时

        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                # 成功完成
                task.result = data.get("bdinfo", "")
                task.status = "completed"
                task.remote_task_status = "completed"
                task.completed_at = datetime.now()

                # 更新统计信息
                self.stats["completed_tasks"] += 1

                # 更新数据库
                self._update_seed_mediainfo(task.seed_id, task.result)
                self._update_task_status(
                    task.seed_id, "completed", task.id, completed_at=task.completed_at
                )

                # 发送SSE完成通知
                try:
                    from utils.sse_manager import sse_manager

                    sse_manager.send_completion(task.seed_id, task.result)
                except Exception as e:
                    logging.error(f"发送SSE完成通知失败: {e}")

                logging.info(f"远程BDInfo任务完成: {task.id}")
            else:
                # 失败
                task.status = "failed"
                task.error_message = data.get("message", "远程BDInfo提取失败")
                task.remote_task_status = "failed"
                task.completed_at = datetime.now()

                # 更新统计信息
                self.stats["failed_tasks"] += 1

                # 更新数据库
                self._update_task_status(
                    task.seed_id,
                    "failed",
                    task.id,
                    completed_at=task.completed_at,
                    error_message=task.error_message,
                )

                # 发送SSE错误通知
                try:
                    from utils.sse_manager import sse_manager

                    sse_manager.send_error(task.seed_id, task.error_message)
                except Exception as e:
                    logging.error(f"发送SSE错误通知失败: {e}")

                logging.error(f"远程BDInfo任务失败: {task.id} - {task.error_message}")
        else:
            # HTTP错误
            task.status = "failed"
            task.error_message = f"远程服务器错误: HTTP {response.status_code}"
            task.remote_task_status = "failed"
            task.completed_at = datetime.now()

            # 更新统计信息
            self.stats["failed_tasks"] += 1

            # 更新数据库
            self._update_task_status(
                task.seed_id,
                "failed",
                task.id,
                completed_at=task.completed_at,
                error_message=task.error_message,
            )

            logging.error(f"远程BDInfo任务HTTP错误: {task.id} - {task.error_message}")

    def handle_remote_progress_callback(self, task_id: str, progress_data: Dict):
        """处理远程进度回调"""
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                logging.warning(f"收到未知任务的进度回调: {task_id}")
                return False

            # 更新进度信息
            task.progress_percent = progress_data.get("progress_percent", 0)
            task.current_file = progress_data.get("current_file", "")
            task.elapsed_time = progress_data.get("elapsed_time", "")
            task.remaining_time = progress_data.get("remaining_time", "")
            task.last_remote_update = datetime.now()

            # 处理Disc Size信息
            disc_size = progress_data.get("disc_size", 0)
            if disc_size > 0:
                progress_data["disc_size_gb"] = round(disc_size / (1024**3), 2)

            # 发送SSE进度更新
            try:
                from utils.sse_manager import sse_manager

                sse_manager.send_progress_update(task.seed_id, progress_data)
            except Exception as e:
                logging.error(f"发送SSE进度更新失败: {e}")

            logging.info(f"更新远程任务进度: {task_id}, 进度: {task.progress_percent}%")
            return True

    def handle_remote_completion_callback(
        self, task_id: str, success: bool, bdinfo_content: str = "", error_message: str = ""
    ):
        """处理远程完成回调"""
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                logging.warning(f"收到未知任务的完成回调: {task_id}")
                return False

            task.completed_at = datetime.now()
            task.last_remote_update = datetime.now()

            if success and bdinfo_content:
                # 成功完成
                task.status = "completed"
                task.result = bdinfo_content
                task.remote_task_status = "completed"

                # 更新统计信息
                self.stats["completed_tasks"] += 1

                # 更新数据库
                self._update_seed_mediainfo(task.seed_id, task.result)
                self._update_task_status(
                    task.seed_id, "completed", task.id, completed_at=task.completed_at
                )

                # 发送SSE完成通知
                try:
                    from utils.sse_manager import sse_manager

                    sse_manager.send_completion(task.seed_id, task.result)
                except Exception as e:
                    logging.error(f"发送SSE完成通知失败: {e}")

                logging.info(f"远程BDInfo任务通过回调完成: {task_id}")
            else:
                # 失败
                task.status = "failed"
                task.error_message = error_message or "远程BDInfo提取失败"
                task.remote_task_status = "failed"

                # 更新统计信息
                self.stats["failed_tasks"] += 1

                # 更新数据库
                self._update_task_status(
                    task.seed_id,
                    "failed",
                    task.id,
                    completed_at=task.completed_at,
                    error_message=task.error_message,
                )

                # 发送SSE错误通知
                try:
                    from utils.sse_manager import sse_manager

                    sse_manager.send_error(task.seed_id, task.error_message)
                except Exception as e:
                    logging.error(f"发送SSE错误通知失败: {e}")

                logging.error(f"远程BDInfo任务通过回调失败: {task_id} - {task.error_message}")

            return True

    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """获取任务状态"""
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return None

            return task.to_dict()

    def get_all_tasks(self) -> List[Dict]:
        """获取所有任务状态"""
        with self.lock:
            return [task.to_dict() for task in self.tasks.values()]

    def get_stats(self) -> Dict:
        """获取统计信息"""
        with self.lock:
            # 更新实时统计
            self.stats["running_tasks"] = len(self.running_tasks)
            self.stats["queued_tasks"] = self.task_queue.qsize()

            return self.stats.copy()

    def cancel_task(self, task_id: str) -> bool:
        """取消任务（只能取消队列中的任务，正在运行的无法取消）"""
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return False

            if task.status == "queued":
                # 从队列中移除（需要重建队列）
                new_queue = PriorityQueue()
                while not self.task_queue.empty():
                    try:
                        queued_task = self.task_queue.get_nowait()
                        if queued_task.id != task_id:
                            new_queue.put(queued_task)
                    except Empty:
                        break

                self.task_queue = new_queue

                # 更新任务状态
                task.status = "cancelled"
                task.completed_at = datetime.now()

                # 更新数据库状态
                self._update_task_status(
                    task.seed_id, "cancelled", task_id, completed_at=task.completed_at
                )

                logging.info(f"BDInfo 任务已取消: {task_id}")
                return True

            return False

    def _worker_loop(self):
        """工作线程主循环"""
        logging.info("BDInfo 工作线程已启动")

        while self.is_running:
            try:
                # 检查当前运行的任务数
                if (
                    len(self.running_tasks) < self.max_concurrent_tasks
                    and not self.task_queue.empty()
                ):
                    try:
                        task = self.task_queue.get_nowait()

                        # 启动工作线程处理任务
                        worker_thread = threading.Thread(
                            target=self._process_task, args=(task,), name=f"BDInfo-{task.id[:8]}"
                        )

                        with self.lock:
                            self.running_tasks[task.id] = worker_thread

                        worker_thread.start()
                        logging.info(f"BDInfo 任务开始处理: {task.id}")

                    except Empty:
                        pass
                    except Exception as e:
                        logging.error(f"启动 BDInfo 任务失败: {e}", exc_info=True)

                # 清理已完成的线程
                self._cleanup_completed_threads()

                # 短暂休眠避免CPU占用过高
                time.sleep(2)

            except Exception as e:
                logging.error(f"BDInfo 工作线程异常: {e}", exc_info=True)
                time.sleep(5)

        logging.info("BDInfo 工作线程已退出")

    def _process_task(self, task: BDInfoTask):
        """处理单个 BDInfo 任务"""
        try:
            with self.lock:
                task.status = "processing_bdinfo"
                task.started_at = datetime.now()

            print(
                f"[DEBUG] 开始处理 BDInfo 任务: {task.id}, seed_id: {task.seed_id}, 执行模式: {task.execution_mode}"
            )

            # 更新数据库状态
            print(f"[DEBUG] 更新任务状态为 processing_bdinfo")
            self._update_task_status(
                task.seed_id, "processing_bdinfo", task.id, started_at=task.started_at
            )

            logging.info(
                f"开始处理 BDInfo 任务: {task.id} (路径: {task.save_path}, 执行模式: {task.execution_mode})"
            )

            if task.execution_mode == "remote":
                # 远程执行模式
                logging.info(f"使用远程执行模式处理任务: {task.id}")

                # 提交远程任务
                if not self._submit_remote_task(task):
                    # 远程提交失败，任务标记为失败（不降级到本地）
                    with self.lock:
                        task.status = "failed"
                        task.completed_at = datetime.now()
                        self.stats["failed_tasks"] += 1

                    self._update_task_status(
                        task.seed_id,
                        "failed",
                        task.id,
                        completed_at=task.completed_at,
                        error_message=task.error_message,
                    )

                    # 发送SSE错误通知
                    try:
                        from utils.sse_manager import sse_manager

                        sse_manager.send_error(task.seed_id, task.error_message)
                    except Exception as e:
                        logging.error(f"发送SSE错误通知失败: {e}")

                    logging.error(f"远程BDInfo任务提交失败: {task.id} - {task.error_message}")
                    return

                # 启动远程进度监控线程
                remote_thread = threading.Thread(
                    target=self._poll_remote_task_progress,
                    args=(task,),
                    name=f"RemoteBDInfo-{task.id[:8]}",
                )
                remote_thread.start()

            else:
                # 本地执行模式（原有逻辑）
                # 应用路径映射
                actual_save_path = task.save_path
                if task.downloader_id:
                    from utils.mediainfo import translate_path

                    actual_save_path = translate_path(task.downloader_id, task.save_path)
                    if actual_save_path != task.save_path:
                        logging.info(f"路径映射: {task.save_path} -> {actual_save_path}")
                        print(f"[DEBUG] 路径映射: {task.save_path} -> {actual_save_path}")

                print(f"[DEBUG] 准备调用 _extract_bdinfo，路径: {actual_save_path}")
                # 调用 BDInfo 提取函数
                from utils import _extract_bdinfo_with_progress

                bdinfo_content = _extract_bdinfo_with_progress(actual_save_path, task.id, self)
                print(
                    f"[DEBUG] BDInfo 提取完成，内容长度: {len(bdinfo_content) if bdinfo_content else 0}"
                )

                with self.lock:
                    if bdinfo_content and not bdinfo_content.startswith("bdinfo提取失败"):
                        # 成功获取 BDInfo
                        print(f"[DEBUG] BDInfo 提取成功，准备更新数据库")
                        task.status = "completed"
                        task.completed_at = datetime.now()
                        task.result = bdinfo_content

                        # 更新统计信息
                        self.stats["completed_tasks"] += 1

                        # 更新数据库中的 mediainfo 字段
                        print(f"[DEBUG] 调用 _update_seed_mediainfo 更新 mediainfo")
                        self._update_seed_mediainfo(task.seed_id, bdinfo_content)
                        print(f"[DEBUG] 调用 _update_task_status 更新状态为 completed")
                        self._update_task_status(
                            task.seed_id, "completed", task.id, completed_at=task.completed_at
                        )

                        # 发送SSE完成通知
                        try:
                            from utils.sse_manager import sse_manager

                            sse_manager.send_completion(task.seed_id, bdinfo_content)
                        except Exception as e:
                            logging.error(f"发送SSE完成通知失败: {e}")

                        logging.info(f"BDInfo 任务完成: {task.id}")
                    else:
                        # BDInfo 提取失败
                        print(f"[DEBUG] BDInfo 提取失败: {bdinfo_content}")
                        task.status = "failed"
                        task.error_message = bdinfo_content or "BDInfo 提取失败"
                        task.completed_at = datetime.now()

                        # 更新统计信息
                        self.stats["failed_tasks"] += 1

                        print(f"[DEBUG] 调用 _update_task_status 更新状态为 failed")
                        self._update_task_status(
                            task.seed_id,
                            "failed",
                            task.id,
                            completed_at=task.completed_at,
                            error_message=task.error_message,
                        )

                        # 发送SSE错误通知
                        try:
                            from utils.sse_manager import sse_manager

                            sse_manager.send_error(task.seed_id, task.error_message)
                        except Exception as e:
                            logging.error(f"发送SSE错误通知失败: {e}")

                        logging.error(f"BDInfo 任务失败: {task.id} - {task.error_message}")

        except subprocess.TimeoutExpired as e:
            with self.lock:
                task.status = "failed"
                task.error_message = f"BDInfo 执行超时: {str(e)}"
                task.completed_at = datetime.now()

                # 更新统计信息
                self.stats["failed_tasks"] += 1

            self._update_task_status(
                task.seed_id,
                "failed",
                task.id,
                completed_at=task.completed_at,
                error_message=task.error_message,
            )

            logging.error(f"BDInfo 任务超时: {task.id} - {e}")
        except Exception as e:
            with self.lock:
                task.status = "failed"
                task.error_message = str(e)
                task.completed_at = datetime.now()

                # 更新统计信息
                self.stats["failed_tasks"] += 1

            self._update_task_status(
                task.seed_id,
                "failed",
                task.id,
                completed_at=task.completed_at,
                error_message=task.error_message,
            )

            logging.error(f"BDInfo 任务异常: {task.id} - {e}", exc_info=True)

    def update_task_progress(
        self,
        task_id: str,
        progress_percent: float,
        current_file: str,
        elapsed_time: str,
        remaining_time: str,
        disc_size: int = 0,
    ):
        """更新任务进度信息"""
        with self.lock:
            task = self.tasks.get(task_id)
            if task:
                # 记录进度变化
                old_percent = task.progress_percent
                task.progress_percent = progress_percent
                task.current_file = current_file
                task.elapsed_time = elapsed_time
                task.remaining_time = remaining_time

                # 只有进度真正变化时才更新时间戳
                if abs(progress_percent - old_percent) > 0.01:  # 0.01% 的精度
                    task.last_progress_update = datetime.now()
                    task.last_progress_percent = progress_percent

                # 如果是第一次更新，设置初始时间戳
                if task.last_progress_update is None:
                    task.last_progress_update = datetime.now()
                    task.last_progress_percent = progress_percent

                # 缓存最新进度数据
                task.last_progress_data = {
                    "progress_percent": progress_percent,
                    "current_file": current_file,
                    "elapsed_time": elapsed_time,
                    "remaining_time": remaining_time,
                    "disc_size": disc_size,
                }

                # 发送SSE进度更新
                try:
                    from utils.sse_manager import sse_manager

                    sse_manager.send_progress_update(
                        task.seed_id,
                        task.last_progress_data,
                    )
                except Exception as e:
                    logging.error(f"发送SSE进度更新失败: {e}")

    def _cleanup_completed_threads(self):
        """清理已完成的线程"""
        with self.lock:
            completed_tasks = []
            for task_id, thread in self.running_tasks.items():
                if not thread.is_alive():
                    completed_tasks.append(task_id)

            for task_id in completed_tasks:
                del self.running_tasks[task_id]

    def _update_task_status(self, seed_id: str, status: str, task_id: str, **kwargs):
        """更新数据库中的任务状态，支持重试机制"""
        import time

        max_retries = 3
        retry_delay = 1  # 秒

        for attempt in range(max_retries):
            conn = None
            cursor = None
            try:
                # 导入数据库管理器
                from database import DatabaseManager
                from config import get_db_config

                # 获取数据库配置并创建数据库管理器
                config = get_db_config()
                db_manager = DatabaseManager(config)

                updates = {
                    "mediainfo_status": status,
                    "updated_at": datetime.now(),
                }

                # 只有当 task_id 不为空时才更新
                if task_id:
                    updates["bdinfo_task_id"] = task_id

                # 对于datetime字段，只有当值存在且不为空时才更新
                started_at = kwargs.get("started_at")
                if started_at:
                    updates["bdinfo_started_at"] = started_at

                completed_at = kwargs.get("completed_at")
                if completed_at:
                    updates["bdinfo_completed_at"] = completed_at

                error_message = kwargs.get("error_message")
                if error_message:
                    updates["bdinfo_error"] = error_message

                # 更新数据库 - 使用 id 字段而不是 seed_id
                conn = db_manager._get_connection()
                cursor = db_manager._get_cursor(conn)

                # seed_id 格式为 "hash_torrentId_siteName"，需要解析
                if "_" in seed_id:
                    # 解析复合 seed_id
                    parts = seed_id.split("_")
                    if len(parts) >= 3:
                        # 最后一个部分是 site_name，中间是 torrent_id，前面是 hash
                        site_name_val = parts[-1]
                        torrent_id_val = parts[-2]
                        hash_val = "_".join(parts[:-2])  # hash 可能包含下划线

                        # 仅使用hash作为主键更新
                        if db_manager.db_type == "sqlite":
                            set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
                            values = list(updates.values()) + [hash_val]
                            sql = f"UPDATE seed_parameters SET {set_clause} WHERE hash = ?"
                            cursor.execute(sql, values)
                        else:
                            set_clause = ", ".join([f"{k} = %s" for k in updates.keys()])
                            values = list(updates.values()) + [hash_val]
                            sql = f"UPDATE seed_parameters SET {set_clause} WHERE hash = %s"
                            cursor.execute(sql, values)
                    else:
                        # 如果格式不对，尝试使用 CONCAT 查询，但只提取hash部分
                        if db_manager.db_type == "sqlite":
                            cursor.execute(
                                "SELECT hash FROM seed_parameters WHERE hash || '_' || torrent_id || '_' || site_name = ?",
                                (seed_id,),
                            )
                        else:
                            cursor.execute(
                                "SELECT hash FROM seed_parameters WHERE CONCAT(hash, '_', torrent_id, '_', site_name) = %s",
                                (seed_id,),
                            )

                        result = cursor.fetchone()
                        if result:
                            hash_val = result[0]
                            # 仅使用hash作为主键更新
                            if db_manager.db_type == "sqlite":
                                set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
                                values = list(updates.values()) + [hash_val]
                                sql = f"UPDATE seed_parameters SET {set_clause} WHERE hash = ?"
                            else:
                                set_clause = ", ".join([f"{k} = %s" for k in updates.keys()])
                                values = list(updates.values()) + [hash_val]
                                sql = f"UPDATE seed_parameters SET {set_clause} WHERE hash = %s"
                else:
                    # 如果没有下划线，说明格式不对，记录错误
                    logging.error(f"无效的 seed_id 格式: {seed_id}")
                    raise ValueError(f"Invalid seed_id format: {seed_id}")

                conn.commit()

                # 检查是否实际更新了记录
                if cursor.rowcount == 0:
                    # 如果是第一次尝试且没有找到记录，可能是时机问题，等待一段时间后重试
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        retry_delay *= 2  # 指数退避
                        continue

                cursor.close()
                conn.close()

                logging.info(f"已更新 BDInfo 任务状态: seed_id={seed_id}, status={status}")

                # 如果更新成功，跳出循环
                break

            except Exception as e:
                logging.error(
                    f"更新 BDInfo 任务状态失败 (尝试 {attempt + 1}/{max_retries}): {e}",
                    exc_info=True,
                )

                # 清理资源
                if cursor:
                    try:
                        cursor.close()
                    except:
                        pass
                if conn:
                    try:
                        conn.rollback()
                        conn.close()
                    except:
                        pass

                # 如果是最后一次尝试，添加到重试队列
                if attempt == max_retries - 1:
                    self._add_to_retry_queue(seed_id, status, task_id, **kwargs)
                else:
                    # 等待一段时间后重试
                    time.sleep(retry_delay)
                    retry_delay *= 2  # 指数退避

    def _add_to_retry_queue(self, seed_id: str, status: str, task_id: str, **kwargs):
        """添加到重试队列"""
        retry_data = {
            "seed_id": seed_id,
            "status": status,
            "task_id": task_id,
            "kwargs": kwargs,
            "timestamp": datetime.now(),
        }
        # 这里可以存储到内存队列或临时文件
        # 为了简单起见，我们先记录到日志
        logging.warning(f"BDInfo 状态更新失败，已添加到重试队列: {seed_id}")
        print(f"[DEBUG] 重试队列数据: {retry_data}")

        # TODO: 实现真正的重试队列机制
        # 可以考虑以下选项：
        # 1. 存储到内存中的队列（重启会丢失）
        # 2. 存储到临时文件或数据库表
        # 3. 使用消息队列系统

    def _update_seed_mediainfo(self, seed_id: str, bdinfo_content: str):
        """更新种子数据中的 mediainfo 字段"""
        try:
            from database import DatabaseManager
            from config import get_db_config

            # 获取数据库配置并创建数据库管理器
            config = get_db_config()
            db_manager = DatabaseManager(config)

            conn = db_manager._get_connection()
            cursor = db_manager._get_cursor(conn)

            # seed_id 格式为 "hash_torrentId_siteName"，需要解析
            if "_" in seed_id:
                # 解析复合 seed_id，但现在只使用hash作为主键
                parts = seed_id.split("_")
                if len(parts) >= 3:
                    # 最后一个部分是 site_name，中间是 torrent_id，前面是 hash
                    site_name_val = parts[-1]
                    torrent_id_val = parts[-2]
                    hash_val = "_".join(parts[:-2])  # hash 可能包含下划线

                    # 仅使用hash作为主键更新记录
                    if db_manager.db_type == "sqlite":
                        sql = "UPDATE seed_parameters SET mediainfo = ?, updated_at = ?, bdinfo_completed_at = ?, mediainfo_status = 'completed' WHERE hash = ?"
                        values = (
                            bdinfo_content,
                            datetime.now(),
                            datetime.now(),
                            hash_val,
                        )
                        cursor.execute(sql, values)
                    else:
                        sql = "UPDATE seed_parameters SET mediainfo = %s, updated_at = %s, bdinfo_completed_at = %s, mediainfo_status = 'completed' WHERE hash = %s"
                        values = (
                            bdinfo_content,
                            datetime.now(),
                            datetime.now(),
                            hash_val,
                        )
                        cursor.execute(sql, values)
                else:
                    # 如果格式不对，尝试使用 CONCAT 查询，但只提取hash部分
                    if db_manager.db_type == "sqlite":
                        cursor.execute(
                            "SELECT hash FROM seed_parameters WHERE hash || '_' || torrent_id || '_' || site_name = ?",
                            (seed_id,),
                        )
                    else:
                        cursor.execute(
                            "SELECT hash FROM seed_parameters WHERE CONCAT(hash, '_', torrent_id, '_', site_name) = %s",
                            (seed_id,),
                        )

                    result = cursor.fetchone()
                    if result:
                        hash_val = result[0]
                        # 仅使用hash作为主键更新
                        if db_manager.db_type == "sqlite":
                            cursor.execute(
                                "UPDATE seed_parameters SET mediainfo = ?, updated_at = ?, bdinfo_completed_at = ?, mediainfo_status = 'completed' WHERE hash = ?",
                                (
                                    bdinfo_content,
                                    datetime.now(),
                                    datetime.now(),
                                    hash_val,
                                ),
                            )
                        else:
                            cursor.execute(
                                "UPDATE seed_parameters SET mediainfo = %s, updated_at = %s, bdinfo_completed_at = %s, mediainfo_status = 'completed' WHERE hash = %s",
                                (
                                    bdinfo_content,
                                    datetime.now(),
                                    datetime.now(),
                                    hash_val,
                                ),
                            )
            else:
                # 如果没有下划线，说明格式不对，记录错误
                logging.error(f"无效的 seed_id 格式: {seed_id}")
                raise ValueError(f"Invalid seed_id format: {seed_id}")

            conn.commit()
            cursor.close()
            conn.close()

            logging.info(f"已更新种子 mediainfo: seed_id={seed_id}")

        except Exception as e:
            logging.error(f"更新种子 mediainfo 失败: {e}", exc_info=True)

    def _health_monitor_loop(self):
        """健康监控线程主循环"""
        logging.info("BDInfo 健康监控线程已启动")

        while self.is_running:
            try:
                # 每30秒检查一次
                time.sleep(30)

                # 检查所有运行中的任务
                with self.lock:
                    running_task_ids = list(self.running_tasks.keys())

                for task_id in running_task_ids:
                    task = self.tasks.get(task_id)
                    if task and task.status == "processing_bdinfo":
                        healthy, reason = self._check_process_health(task)
                        if not healthy:
                            logging.warning(f"任务 {task_id} 不健康: {reason}")
                            self._handle_unhealthy_task(task, reason)

            except Exception as e:
                logging.error(f"健康监控异常: {e}", exc_info=True)
                time.sleep(60)  # 出错后等待更长时间

        logging.info("BDInfo 健康监控线程已退出")

    def _check_process_health(self, task: BDInfoTask) -> Tuple[bool, str]:
        """多维度检查进程健康状态"""

        # 远程执行模式的健康检查
        if task.execution_mode == "remote":
            return self._check_remote_task_health(task)

        # 本地执行模式的健康检查
        # 1. 检查进程对象是否存在
        if not task.process:
            return False, "进程对象丢失"

        # 2. 检查进程是否仍在运行
        if task.process.poll() is not None:
            return False, f"进程已退出，返回码: {task.process.returncode}"

        # 3. 检查进度是否停滞
        if self._is_progress_stagnant(task):
            return False, "进度停滞超过阈值"

        # 5. 检查临时文件是否有更新
        if task.temp_file_path and not self._is_temp_file_updating(task):
            return False, "临时文件长时间无更新"

        return True, "进程健康"

    def _check_remote_task_health(self, task: BDInfoTask) -> Tuple[bool, str]:
        """检查远程任务健康状态"""

        # 1. 检查远程任务状态
        if task.remote_task_status in ["completed", "failed"]:
            return False, f"远程任务已结束: {task.remote_task_status}"

        # 2. 检查最后更新时间
        if task.last_remote_update:
            time_since_update = (datetime.now() - task.last_remote_update).total_seconds()
            # 如果超过5分钟没有更新，认为不健康
            if time_since_update > 300:
                return False, f"远程任务长时间无更新: {time_since_update:.0f}秒"

        # 3. 检查任务运行时间
        if task.started_at:
            running_time = (datetime.now() - task.started_at).total_seconds()
            # 如果超过30分钟还在运行，认为可能卡死
            if running_time > 1800:
                return False, f"远程任务运行时间过长: {running_time/60:.1f}分钟"

        return True, "远程任务健康"

    def _is_progress_stagnant(self, task: BDInfoTask) -> bool:
        """检测进度是否停滞"""

        # 如果没有进度更新记录，不算停滞
        if not task.last_progress_update:
            return False

        now = datetime.now()
        stagnant_time = (now - task.last_progress_update).total_seconds()

        # 根据进度阶段设置不同的停滞阈值
        if task.progress_percent < 1:
            # 初始阶段，可能需要更长时间扫描文件列表
            threshold = 900  # 15分钟
        elif task.progress_percent < 10:
            # 早期阶段
            threshold = 600  # 10分钟
        elif task.progress_percent < 50:
            # 中期阶段
            threshold = 300  # 5分钟
        else:
            # 后期阶段
            threshold = 180  # 3分钟

        # 只有超过阈值才认为停滞
        if stagnant_time <= threshold:
            return False

        print(
            f"[DEBUG] 任务 {task.id} 进度停滞: {stagnant_time:.0f}s > {threshold}s, 进度: {task.progress_percent}%"
        )
        return True

    def _is_temp_file_updating(self, task: BDInfoTask) -> bool:
        """检查临时文件是否有更新"""
        if not task.temp_file_path or not os.path.exists(task.temp_file_path):
            return True  # 文件不存在时不算停滞

        try:
            # 检查文件最后修改时间
            file_mtime = os.path.getmtime(task.temp_file_path)
            now = time.time()

            # 如果文件超过10分钟没有更新，认为停滞
            return (now - file_mtime) < 600
        except Exception:
            return True  # 出错时不认为停滞

    def _handle_unhealthy_task(self, task: BDInfoTask, reason: str):
        """处理不健康的任务"""

        try:
            # 清理进程
            self._cleanup_process(task)

            # 更新任务状态为失败
            task.status = "failed"
            task.error_message = f"进程不健康: {reason}"
            task.completed_at = datetime.now()

            # 更新数据库状态
            self._update_task_status(
                task.seed_id,
                "failed",
                task.id,
                completed_at=task.completed_at,
                error_message=task.error_message,
            )

            # 从运行任务中移除
            if task.id in self.running_tasks:
                del self.running_tasks[task.id]

            # 更新统计信息
            self.stats["failed_tasks"] += 1

            # 发送SSE错误通知
            try:
                from utils.sse_manager import sse_manager

                sse_manager.send_error(task.seed_id, task.error_message)
            except Exception as e:
                logging.error(f"发送SSE错误通知失败: {e}")

            logging.error(f"BDInfo 任务因不健康被终止: {task.id} - {reason}")

        except Exception as e:
            logging.error(f"处理不健康任务失败: {e}", exc_info=True)

    def _cleanup_process(self, task: BDInfoTask):
        """清理进程和相关资源"""

        try:
            # 终止进程
            if task.process:
                try:
                    task.process.terminate()
                    # 等待进程优雅退出
                    try:
                        task.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        # 如果5秒后仍未退出，强制杀死
                        task.process.kill()
                        task.process.wait()
                except Exception as e:
                    logging.warning(f"终止进程失败: {e}")

                task.process = None

            # 清理临时文件
            if task.temp_file_path and os.path.exists(task.temp_file_path):
                try:
                    os.unlink(task.temp_file_path)
                    logging.info(f"已清理临时文件: {task.temp_file_path}")
                except Exception as e:
                    logging.warning(f"清理临时文件失败: {e}")

            task.process_pid = None

        except Exception as e:
            logging.error(f"清理进程资源失败: {e}", exc_info=True)

    def recover_orphaned_tasks(self):
        """启动时恢复遗留任务"""

        try:
            logging.info("开始检查遗留的 BDInfo 任务...")

            # 从数据库查询所有 processing_bdinfo 状态的任务
            orphaned_tasks = self._get_orphaned_tasks_from_db()

            if not orphaned_tasks:
                logging.info("没有发现遗留的 BDInfo 任务")
                return

            logging.info(f"发现 {len(orphaned_tasks)} 个遗留任务")

            for task_data in orphaned_tasks:
                task_id = task_data.get("bdinfo_task_id")
                seed_id = task_data.get("seed_id")
                status = task_data.get("status")

                if not seed_id:
                    continue

                try:
                    if status == "processing_bdinfo":
                        # 处理正在进行的任务
                        started_at = task_data.get("bdinfo_started_at")
                        if not started_at:
                            continue

                        # 检查任务是否真的卡死
                        if self._is_task_truly_stuck(task_id, started_at):
                            # 标记为失败，允许重试
                            self._mark_task_as_failed(seed_id, task_id, "进程异常终止，需要重试")
                            logging.info(f"恢复卡死任务: {task_id}")
                        else:
                            # 任务可能仍在运行，尝试重新关联
                            self._try_recover_running_task(task_data)

                    elif status == "queued":
                        # 处理等待中的任务
                        created_at = task_data.get("created_at")
                        if not created_at:
                            continue

                        # 检查等待时间是否过长（超过30分钟）
                        wait_time = (datetime.now() - created_at).total_seconds()
                        if wait_time > 1800:  # 30分钟
                            self._mark_task_as_failed(
                                seed_id, task_id or "", "等待超时，需要手动重试"
                            )
                            logging.info(
                                f"恢复等待超时任务: {seed_id}，等待时间: {wait_time/60:.1f}分钟"
                            )
                        else:
                            logging.info(
                                f"等待中的任务 {seed_id}，等待时间: {wait_time/60:.1f}分钟"
                            )

                except Exception as e:
                    logging.error(f"恢复任务 {task_id} 失败: {e}", exc_info=True)

            logging.info("遗留任务检查完成")

        except Exception as e:
            logging.error(f"恢复遗留任务失败: {e}", exc_info=True)

    def _get_orphaned_tasks_from_db(self) -> List[Dict]:
        """从数据库获取遗留任务"""

        try:
            from database import DatabaseManager
            from config import get_db_config

            # 获取数据库配置并创建数据库管理器
            config = get_db_config()
            db_manager = DatabaseManager(config)

            conn = db_manager._get_connection()
            cursor = db_manager._get_cursor(conn)

            # 首先检查表是否存在以及是否有必要的字段
            if db_manager.db_type == "sqlite":
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='seed_parameters'"
                )
                if not cursor.fetchone():
                    print("[DEBUG] seed_parameters 表不存在")
                    cursor.close()
                    conn.close()
                    return []
            elif db_manager.db_type == "postgresql":  # PostgreSQL
                cursor.execute(
                    "SELECT tablename FROM pg_tables WHERE tablename = 'seed_parameters'"
                )
                if not cursor.fetchone():
                    print("[DEBUG] seed_parameters 表不存在")
                    cursor.close()
                    conn.close()
                    return []
            else:  # MySQL
                cursor.execute("SHOW TABLES LIKE 'seed_parameters'")
                if not cursor.fetchone():
                    print("[DEBUG] seed_parameters 表不存在")
                    cursor.close()
                    conn.close()
                    return []

            # 查询所有 processing_bdinfo 状态的任务
            if db_manager.db_type == "sqlite":
                cursor.execute(
                    """
                    SELECT hash, torrent_id, site_name, bdinfo_task_id, bdinfo_started_at, bdinfo_completed_at, bdinfo_error, created_at
                    FROM seed_parameters 
                    WHERE mediainfo_status IN ('processing_bdinfo', 'queued')
                    AND (
                        (mediainfo_status = 'processing_bdinfo' AND bdinfo_started_at IS NOT NULL)
                        OR 
                        (mediainfo_status = 'queued' AND created_at IS NOT NULL)
                    )
                """
                )
            else:
                cursor.execute(
                    """
                    SELECT hash, torrent_id, site_name, bdinfo_task_id, bdinfo_started_at, bdinfo_completed_at, bdinfo_error, created_at
                    FROM seed_parameters 
                    WHERE mediainfo_status IN ('processing_bdinfo', 'queued')
                    AND (
                        (mediainfo_status = 'processing_bdinfo' AND bdinfo_started_at IS NOT NULL)
                        OR 
                        (mediainfo_status = 'queued' AND created_at IS NOT NULL)
                    )
                """
                )

            results = cursor.fetchall()
            print(f"[DEBUG] 查询到 {len(results)} 个 processing_bdinfo 状态的任务")

            # 转换为字典列表
            orphaned_tasks = []
            for i, row in enumerate(results):
                try:
                    # 处理字典格式的结果（MySQL 默认）
                    if isinstance(row, dict):
                        # 构造复合 seed_id
                        seed_id = f"{row['hash']}_{row['torrent_id']}_{row['site_name']}"
                        orphaned_tasks.append(
                            {
                                "seed_id": seed_id,
                                "bdinfo_task_id": row["bdinfo_task_id"],
                                "bdinfo_started_at": row["bdinfo_started_at"],
                                "bdinfo_completed_at": row["bdinfo_completed_at"],
                                "bdinfo_error": row["bdinfo_error"],
                                "created_at": row.get("created_at"),
                                "status": (
                                    "processing_bdinfo" if row["bdinfo_started_at"] else "queued"
                                ),
                            }
                        )
                        print(
                            f"[DEBUG] 找到遗留任务: {seed_id} (状态: {'processing_bdinfo' if row['bdinfo_started_at'] else 'queued'})"
                        )
                    # 处理元组格式的结果（SQLite）
                    elif isinstance(row, (tuple, list)) and len(row) >= 7:
                        # 构造复合 seed_id
                        seed_id = f"{row[0]}_{row[1]}_{row[2]}"
                        orphaned_tasks.append(
                            {
                                "seed_id": seed_id,
                                "bdinfo_task_id": row[3],
                                "bdinfo_started_at": row[4],
                                "bdinfo_completed_at": row[5],
                                "bdinfo_error": row[6],
                                "created_at": row[7] if len(row) > 7 else None,
                                "status": "processing_bdinfo" if row[4] else "queued",
                            }
                        )
                        print(
                            f"[DEBUG] 找到遗留任务: {seed_id} (状态: {'processing_bdinfo' if row[4] else 'queued'})"
                        )
                    else:
                        print(f"[DEBUG] 跳过无效的行 {i}: {row}")

                except Exception as e:
                    print(f"[DEBUG] 处理行 {i} 时出错: {e}, row={row}")
                    continue

            cursor.close()
            conn.close()

            return orphaned_tasks

        except Exception as e:
            logging.error(f"获取遗留任务失败: {e}", exc_info=True)
            print(f"[DEBUG] 获取遗留任务时发生异常: {e}")
            return []

    def _is_task_truly_stuck(self, task_id: str, started_at: datetime) -> bool:
        """判断任务是否真的卡死"""

        try:
            # 1. 检查运行时间是否过长（降低门槛到1分钟）
            running_time = (datetime.now() - started_at).total_seconds()
            if running_time < 60:  # 1分钟内不算卡死
                return False

            print(f"[DEBUG] 检查任务卡死状态: task_id={task_id}, 运行时间={running_time:.1f}秒")

            # 2. 检查系统中是否有相关进程
            has_process = self._find_bdinfo_process_for_task(task_id)
            print(f"[DEBUG] 检查进程状态: task_id={task_id}, 有进程={has_process}")

            # 3. 检查临时文件是否有更新
            is_file_updating = self._is_temp_file_updating_for_task(task_id)
            print(f"[DEBUG] 检查文件更新: task_id={task_id}, 文件更新中={is_file_updating}")

            # 如果进程不存在且文件长时间未更新，则认为卡死
            is_stuck = not has_process and not is_file_updating
            print(f"[DEBUG] 任务卡死判断结果: task_id={task_id}, 是否卡死={is_stuck}")

            return is_stuck

        except Exception as e:
            logging.error(f"判断任务卡死状态失败: {e}", exc_info=True)
            return True  # 出错时保守处理，认为卡死

    def _find_bdinfo_process_for_task(self, task_id: str) -> bool:
        """查找任务对应的 BDInfo 进程（简化版本，不使用psutil）"""
        # 由于删除了psutil依赖，这里直接返回False
        # 依赖其他监控机制（进度停滞检测、临时文件监控等）
        print(f"[DEBUG] 任务 {task_id} 进程查找：已跳过（无psutil依赖）")
        return False
    def _is_temp_file_updating_for_task(self, task_id: str) -> bool:
        """检查任务的临时文件是否有更新"""

        try:
            # 构建可能的临时文件路径
            from config import TEMP_DIR

            # 查找包含任务ID的临时文件
            matching_files = []
            for filename in os.listdir(TEMP_DIR):
                if task_id in filename and filename.startswith("bdinfo_"):
                    filepath = os.path.join(TEMP_DIR, filename)
                    if os.path.exists(filepath):
                        matching_files.append(filepath)

            if not matching_files:
                print(f"[DEBUG] 没有找到任务 {task_id} 的临时文件")
                return False

            # 检查所有匹配文件的修改时间
            now = time.time()
            for filepath in matching_files:
                file_mtime = os.path.getmtime(filepath)
                time_diff = now - file_mtime

                print(f"[DEBUG] 检查临时文件: {filepath}, 最后修改时间差: {time_diff:.1f}秒")

                # 如果任何文件在5分钟内有更新，认为仍在处理
                if time_diff < 300:
                    print(f"[DEBUG] 发现最近更新的文件: {filepath}")
                    return True

            print(f"[DEBUG] 所有临时文件都已超过5分钟未更新")
            return False

        except Exception as e:
            logging.error(f"检查临时文件更新失败: {e}", exc_info=True)
            return False

    def _mark_task_as_failed(self, seed_id: str, task_id: str, error_message: str):
        """将任务标记为失败"""

        try:
            self._update_task_status(
                seed_id,
                "failed",
                task_id,
                completed_at=datetime.now(),
                error_message=error_message,
            )

            logging.info(f"任务 {task_id} 已标记为失败: {error_message}")

        except Exception as e:
            logging.error(f"标记任务失败状态失败: {e}", exc_info=True)

    def _try_recover_running_task(self, task_data: Dict):
        """尝试恢复仍在运行的任务"""

        try:
            task_id = task_data.get("bdinfo_task_id")
            seed_id = task_data.get("seed_id")

            # 创建虚拟任务对象用于跟踪
            task = BDInfoTask(seed_id, "", priority=2)
            task.id = task_id
            task.status = "processing_bdinfo"
            task.started_at = task_data.get("bdinfo_started_at")

            # 添加到内存中的任务列表
            with self.lock:
                self.tasks[task_id] = task

            logging.info(f"已恢复运行中的任务: {task_id}")

        except Exception as e:
            logging.error(f"恢复运行任务失败: {e}", exc_info=True)

    def cleanup_orphaned_process(self, seed_id: str):
        """清理指定种子的孤立进程"""

        try:
            with self.lock:
                # 查找对应任务
                for task_id, task in self.tasks.items():
                    if task.seed_id == seed_id and task.status == "processing_bdinfo":
                        self._cleanup_process(task)
                        logging.info(f"已清理种子 {seed_id} 的孤立进程")
                        break
        except Exception as e:
            logging.error(f"清理孤立进程失败: {e}", exc_info=True)

    def reset_task_status(self, seed_id: str):
        """重置任务状态"""

        try:
            self._update_task_status(
                seed_id,
                "queued",
                "",  # 清空 task_id
                bdinfo_started_at=None,
                bdinfo_completed_at=None,
                bdinfo_error=None,
            )
            logging.info(f"已重置种子 {seed_id} 的任务状态")
        except Exception as e:
            logging.error(f"重置任务状态失败: {e}", exc_info=True)

    def get_current_progress(self, seed_id: str) -> Optional[Dict]:
        """获取指定 seed_id 的当前进度"""
        with self.lock:
            for task in self.tasks.values():
                if task.seed_id == seed_id and task.status == "processing_bdinfo":
                    return {
                        "progress_percent": task.progress_percent,
                        "current_file": task.current_file,
                        "elapsed_time": task.elapsed_time,
                        "remaining_time": task.remaining_time,
                    }
        return None


# 全局 BDInfo 管理器实例
bdinfo_manager = None


def get_bdinfo_manager():
    """获取全局 BDInfo 管理器实例"""
    global bdinfo_manager
    if bdinfo_manager is None:
        bdinfo_manager = BDInfoManager()
    return bdinfo_manager
