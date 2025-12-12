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
from datetime import datetime
from queue import PriorityQueue, Empty
from typing import Dict, Optional, List


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
            self.tasks[task.id] = task
            self.task_queue.put(task)

            # 更新统计信息
            self.stats["total_tasks"] += 1
            self.stats["queued_tasks"] += 1

            # 更新数据库状态
            self._update_task_status(task.seed_id, "processing_bdinfo", task.id)

            logging.info(f"BDInfo 任务已添加: {task.id} (种子ID: {seed_id}, 优先级: {priority})")
            return task.id

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

            print(f"[DEBUG] 开始处理 BDInfo 任务: {task.id}, seed_id: {task.seed_id}")

            # 更新数据库状态
            print(f"[DEBUG] 更新任务状态为 processing_bdinfo")
            self._update_task_status(
                task.seed_id, "processing_bdinfo", task.id, started_at=task.started_at
            )

            logging.info(f"开始处理 BDInfo 任务: {task.id} (路径: {task.save_path})")

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
            from utils.mediainfo import _extract_bdinfo_with_progress

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
                task.progress_percent = progress_percent
                task.current_file = current_file
                task.elapsed_time = elapsed_time
                task.remaining_time = remaining_time

                # 发送SSE进度更新
                try:
                    from utils.sse_manager import sse_manager

                    sse_manager.send_progress_update(
                        task.seed_id,
                        {
                            "progress_percent": progress_percent,
                            "current_file": current_file,
                            "elapsed_time": elapsed_time,
                            "remaining_time": remaining_time,
                            "disc_size": disc_size,
                        },
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
        """更新数据库中的任务状态"""
        try:
            print(
                f"[DEBUG] _update_task_status 被调用: seed_id={seed_id}, status={status}, task_id={task_id}"
            )

            # 导入数据库管理器
            from database import DatabaseManager
            from config import get_db_config

            # 获取数据库配置并创建数据库管理器
            config = get_db_config()
            print(f"[DEBUG] 数据库配置: {config}")
            db_manager = DatabaseManager(config)

            updates = {
                "mediainfo_status": status,
                "bdinfo_task_id": task_id,
                "updated_at": datetime.now(),
            }

            if kwargs.get("started_at"):
                updates["bdinfo_started_at"] = kwargs["started_at"]
            if kwargs.get("completed_at"):
                updates["bdinfo_completed_at"] = kwargs["completed_at"]
            if kwargs.get("error_message"):
                updates["bdinfo_error"] = kwargs["error_message"]

            # 更新数据库 - 使用 id 字段而不是 seed_id
            conn = db_manager._get_connection()
            cursor = db_manager._get_cursor(conn)

            # seed_id 格式为 "hash_torrentId_siteName"，需要解析
            if "_" in seed_id:
                # 解析复合 seed_id
                parts = seed_id.split("_")
                print(f"[DEBUG] seed_id 解析结果: parts={parts}")
                if len(parts) >= 3:
                    # 最后一个部分是 site_name，中间是 torrent_id，前面是 hash
                    site_name_val = parts[-1]
                    torrent_id_val = parts[-2]
                    hash_val = "_".join(parts[:-2])  # hash 可能包含下划线
                    print(
                        f"[DEBUG] 解析出复合主键: hash={hash_val}, torrent_id={torrent_id_val}, site_name={site_name_val}"
                    )

                    # 直接使用解析出的复合主键更新
                    if db_manager.db_type == "sqlite":
                        set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
                        values = list(updates.values()) + [hash_val, torrent_id_val, site_name_val]
                        sql = f"UPDATE seed_parameters SET {set_clause} WHERE hash = ? AND torrent_id = ? AND site_name = ?"
                        print(f"[DEBUG] 执行 SQL: {sql}")
                        print(f"[DEBUG] 参数: {values}")
                        cursor.execute(sql, values)
                    else:
                        set_clause = ", ".join([f"{k} = %s" for k in updates.keys()])
                        values = list(updates.values()) + [hash_val, torrent_id_val, site_name_val]
                        sql = f"UPDATE seed_parameters SET {set_clause} WHERE hash = %s AND torrent_id = %s AND site_name = %s"
                        print(f"[DEBUG] 执行 SQL: {sql}")
                        print(f"[DEBUG] 参数: {values}")
                        cursor.execute(sql, values)
                else:
                    # 如果格式不对，尝试使用 CONCAT 查询
                    if db_manager.db_type == "sqlite":
                        cursor.execute(
                            "SELECT hash, torrent_id, site_name FROM seed_parameters WHERE hash || '_' || torrent_id || '_' || site_name = ?",
                            (seed_id,),
                        )
                    else:
                        cursor.execute(
                            "SELECT hash, torrent_id, site_name FROM seed_parameters WHERE CONCAT(hash, '_', torrent_id, '_', site_name) = %s",
                            (seed_id,),
                        )

                    result = cursor.fetchone()
                    if result:
                        hash_val, torrent_id_val, site_name_val = result[0], result[1], result[2]
                        set_clause = ", ".join([f"{k} = %s" for k in updates.keys()])
                        values = list(updates.values()) + [hash_val, torrent_id_val, site_name_val]
                        cursor.execute(
                            f"UPDATE seed_parameters SET {set_clause} WHERE hash = %s AND torrent_id = %s AND site_name = %s",
                            values,
                        )
            else:
                # 如果没有下划线，说明格式不对，记录错误
                logging.error(f"无效的 seed_id 格式: {seed_id}")
                raise ValueError(f"Invalid seed_id format: {seed_id}")

            print(f"[DEBUG] 准备提交事务...")
            conn.commit()
            print(f"[DEBUG] 事务已提交")
            cursor.close()
            conn.close()

            logging.info(f"已更新 BDInfo 任务状态: seed_id={seed_id}, status={status}")
            print(f"[DEBUG] BDInfo 任务状态更新完成")

        except Exception as e:
            logging.error(f"更新 BDInfo 任务状态失败: {e}", exc_info=True)

    def _update_seed_mediainfo(self, seed_id: str, bdinfo_content: str):
        """更新种子数据中的 mediainfo 字段"""
        try:
            print(f"[DEBUG] _update_seed_mediainfo 被调用: seed_id={seed_id}")
            print(f"[DEBUG] BDInfo 内容长度: {len(bdinfo_content)}")

            from database import DatabaseManager
            from config import get_db_config

            # 获取数据库配置并创建数据库管理器
            config = get_db_config()
            db_manager = DatabaseManager(config)

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

                    # 直接使用解析出的复合主键更新
                    if db_manager.db_type == "sqlite":
                        sql = "UPDATE seed_parameters SET mediainfo = ?, updated_at = ? WHERE hash = ? AND torrent_id = ? AND site_name = ?"
                        values = (
                            bdinfo_content,
                            datetime.now(),
                            hash_val,
                            torrent_id_val,
                            site_name_val,
                        )
                        print(f"[DEBUG] 执行 SQL: {sql}")
                        print(
                            f"[DEBUG] 参数: mediainfo长度={len(bdinfo_content)}, hash={hash_val}, torrent_id={torrent_id_val}, site_name={site_name_val}"
                        )
                        cursor.execute(sql, values)
                    else:
                        sql = "UPDATE seed_parameters SET mediainfo = %s, updated_at = %s WHERE hash = %s AND torrent_id = %s AND site_name = %s"
                        values = (
                            bdinfo_content,
                            datetime.now(),
                            hash_val,
                            torrent_id_val,
                            site_name_val,
                        )
                        print(f"[DEBUG] 执行 SQL: {sql}")
                        print(
                            f"[DEBUG] 参数: mediainfo长度={len(bdinfo_content)}, hash={hash_val}, torrent_id={torrent_id_val}, site_name={site_name_val}"
                        )
                        cursor.execute(sql, values)
                else:
                    # 如果格式不对，尝试使用 CONCAT 查询
                    if db_manager.db_type == "sqlite":
                        cursor.execute(
                            "SELECT hash, torrent_id, site_name FROM seed_parameters WHERE hash || '_' || torrent_id || '_' || site_name = ?",
                            (seed_id,),
                        )
                    else:
                        cursor.execute(
                            "SELECT hash, torrent_id, site_name FROM seed_parameters WHERE CONCAT(hash, '_', torrent_id, '_', site_name) = %s",
                            (seed_id,),
                        )

                    result = cursor.fetchone()
                    if result:
                        hash_val, torrent_id_val, site_name_val = result[0], result[1], result[2]
                        cursor.execute(
                            "UPDATE seed_parameters SET mediainfo = %s, updated_at = %s WHERE hash = %s AND torrent_id = %s AND site_name = %s",
                            (
                                bdinfo_content,
                                datetime.now(),
                                hash_val,
                                torrent_id_val,
                                site_name_val,
                            ),
                        )
            else:
                # 如果没有下划线，说明格式不对，记录错误
                logging.error(f"无效的 seed_id 格式: {seed_id}")
                raise ValueError(f"Invalid seed_id format: {seed_id}")

            print(f"[DEBUG] 准备提交 mediainfo 更新事务...")
            conn.commit()
            print(f"[DEBUG] mediainfo 更新事务已提交")
            cursor.close()
            conn.close()

            logging.info(f"已更新种子 mediainfo: seed_id={seed_id}")
            print(f"[DEBUG] 种子 mediainfo 更新完成")

        except Exception as e:
            logging.error(f"更新种子 mediainfo 失败: {e}", exc_info=True)


# 全局 BDInfo 管理器实例
bdinfo_manager = None


def get_bdinfo_manager():
    """获取全局 BDInfo 管理器实例"""
    global bdinfo_manager
    if bdinfo_manager is None:
        bdinfo_manager = BDInfoManager()
    return bdinfo_manager
