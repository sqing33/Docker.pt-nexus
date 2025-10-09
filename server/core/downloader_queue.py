# core/downloader_queue.py

import threading
import queue
import time
import uuid
import logging
import json
from typing import Dict, Any, Optional, Callable
from enum import Enum
from dataclasses import dataclass, asdict
from datetime import datetime

# 设置日志
logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"      # 等待处理
    PROCESSING = "processing"  # 正在处理
    SUCCESS = "success"      # 成功完成
    FAILED = "failed"        # 处理失败
    RETRYING = "retrying"    # 重试中
    CANCELLED = "cancelled"  # 已取消


@dataclass
class DownloaderTask:
    """下载器任务数据结构"""
    task_id: str
    detail_page_url: str
    save_path: str
    downloader_id: str
    batch_id: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 3
    error_message: Optional[str] = None
    result_message: Optional[str] = None
    processing_time: Optional[float] = None
    # 额外的上下文信息
    context: Dict[str, Any] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()
        if self.context is None:
            self.context = {}

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式，便于JSON序列化"""
        data = asdict(self)
        # 转换枚举为字符串
        data['status'] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DownloaderTask':
        """从字典创建任务对象"""
        if 'status' in data:
            data['status'] = TaskStatus(data['status'])
        return cls(**data)


class DownloaderQueueService:
    """下载器队列服务

    提供异步处理种子添加到下载器的功能，避免发布流程因下载器操作而变慢。
    """

    def __init__(self, max_queue_size: int = 1000, max_workers: int = 1):
        """
        初始化队列服务

        Args:
            max_queue_size: 队列最大容量
            max_workers: 最大工作线程数（暂固定为1，后续可扩展）
        """
        self.max_queue_size = max_queue_size
        self.max_workers = max_workers

        # 任务队列
        self.task_queue = queue.Queue(maxsize=max_queue_size)

        # 任务状态存储 {task_id: DownloaderTask}
        self.tasks: Dict[str, DownloaderTask] = {}

        # 线程控制
        self.is_running = False
        self.worker_threads: list[threading.Thread] = []

        # 统计信息
        self.stats = {
            'total_tasks': 0,
            'success_tasks': 0,
            'failed_tasks': 0,
            'cancelled_tasks': 0,
            'queue_size': 0
        }

        # 回调函数
        self.task_callbacks: Dict[str, Callable] = {}

        # 数据库管理器和配置管理器（后续设置）
        self.db_manager = None
        self.config_manager = None

        logger.info("下载器队列服务初始化完成")

    def set_managers(self, db_manager, config_manager):
        """
        设置数据库管理器和配置管理器

        Args:
            db_manager: 数据库管理器实例
            config_manager: 配置管理器实例
        """
        self.db_manager = db_manager
        self.config_manager = config_manager
        logger.info("数据库管理器和配置管理器已设置")

    def start(self):
        """启动队列服务"""
        if self.is_running:
            logger.warning("队列服务已在运行中")
            return

        # 检查必要的管理器是否已设置
        if not self.db_manager or not self.config_manager:
            logger.warning("数据库管理器或配置管理器未设置，某些功能可能无法正常工作")

        self.is_running = True

        # 启动工作线程
        for i in range(self.max_workers):
            worker = threading.Thread(
                target=self._worker,
                name=f"DownloaderQueue-{i+1}",
                daemon=True
            )
            worker.start()
            self.worker_threads.append(worker)

        logger.info(f"队列服务已启动，工作线程数: {len(self.worker_threads)}")

    def stop(self, timeout: float = 10.0):
        """停止队列服务

        Args:
            timeout: 等待工作线程完成的超时时间（秒）
        """
        if not self.is_running:
            return

        logger.info("正在停止队列服务...")
        self.is_running = False

        # 发送停止信号到每个工作线程
        for _ in range(self.max_workers):
            try:
                self.task_queue.put(None, timeout=1.0)
            except queue.Full:
                break

        # 等待所有工作线程完成
        for worker in self.worker_threads:
            worker.join(timeout=timeout)
            if worker.is_alive():
                logger.warning(f"工作线程 {worker.name} 未在超时时间内停止")

        self.worker_threads.clear()
        logger.info("队列服务已停止")

    def add_task(self,
                 detail_page_url: str,
                 save_path: str,
                 downloader_id: str,
                 batch_id: Optional[str] = None,
                 context: Optional[Dict[str, Any]] = None,
                 callback: Optional[Callable] = None) -> str:
        """
        添加下载器任务到队列

        Args:
            detail_page_url: 种子详情页URL
            save_path: 保存路径
            downloader_id: 下载器ID
            batch_id: 批次ID（用于批量转种记录）
            context: 额外的上下文信息
            callback: 任务完成后的回调函数

        Returns:
            任务ID
        """
        # 生成唯一任务ID
        task_id = str(uuid.uuid4())

        # 创建任务对象
        task = DownloaderTask(
            task_id=task_id,
            detail_page_url=detail_page_url,
            save_path=save_path,
            downloader_id=downloader_id,
            batch_id=batch_id,
            context=context or {}
        )

        # 存储任务
        self.tasks[task_id] = task

        # 存储回调函数
        if callback:
            self.task_callbacks[task_id] = callback

        try:
            # 添加到队列
            self.task_queue.put(task, timeout=5.0)
            self.stats['total_tasks'] += 1
            self.stats['queue_size'] = self.task_queue.qsize()

            logger.info(f"任务已添加到队列: {task_id}, 队列大小: {self.stats['queue_size']}")
            return task_id

        except queue.Full:
            del self.tasks[task_id]
            if task_id in self.task_callbacks:
                del self.task_callbacks[task_id]
            raise Exception("队列已满，无法添加新任务")

    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        获取任务状态

        Args:
            task_id: 任务ID

        Returns:
            任务状态信息，如果任务不存在返回None
        """
        task = self.tasks.get(task_id)
        if not task:
            return None

        # 更新队列大小统计
        self.stats['queue_size'] = self.task_queue.qsize()

        status_info = task.to_dict()
        status_info['queue_size'] = self.stats['queue_size']
        status_info['stats'] = self.stats.copy()

        return status_info

    def cancel_task(self, task_id: str) -> bool:
        """
        取消任务

        Args:
            task_id: 任务ID

        Returns:
            是否成功取消
        """
        task = self.tasks.get(task_id)
        if not task:
            return False

        if task.status in [TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED]:
            return False

        if task.status == TaskStatus.PENDING:
            task.status = TaskStatus.CANCELLED
            task.completed_at = time.time()
            self.stats['cancelled_tasks'] += 1

            # 清理回调函数
            if task_id in self.task_callbacks:
                del self.task_callbacks[task_id]

            logger.info(f"任务已取消: {task_id}")
            return True

        # 正在处理中的任务无法取消
        return False

    def get_queue_stats(self) -> Dict[str, Any]:
        """获取队列统计信息"""
        self.stats['queue_size'] = self.task_queue.qsize()
        return {
            **self.stats,
            'is_running': self.is_running,
            'worker_count': len(self.worker_threads),
            'pending_tasks_count': sum(1 for t in self.tasks.values() if t.status == TaskStatus.PENDING),
            'processing_tasks_count': sum(1 for t in self.tasks.values() if t.status == TaskStatus.PROCESSING),
        }

    def clear_completed_tasks(self, max_age_hours: int = 24):
        """清理已完成的任务记录

        Args:
            max_age_hours: 任务记录保留时间（小时）
        """
        current_time = time.time()
        cutoff_time = current_time - (max_age_hours * 3600)

        tasks_to_remove = []
        for task_id, task in self.tasks.items():
            if (task.status in [TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED]
                and task.completed_at
                and task.completed_at < cutoff_time):
                tasks_to_remove.append(task_id)

        for task_id in tasks_to_remove:
            del self.tasks[task_id]
            if task_id in self.task_callbacks:
                del self.task_callbacks[task_id]

        logger.info(f"清理了 {len(tasks_to_remove)} 个已完成的任务记录")

    def _worker(self):
        """工作线程主函数"""
        logger.info(f"工作线程 {threading.current_thread().name} 已启动")

        while self.is_running:
            try:
                # 获取任务，设置超时避免无限等待
                task = self.task_queue.get(timeout=5.0)

                # 检查停止信号
                if task is None:
                    logger.debug(f"工作线程 {threading.current_thread().name} 收到停止信号")
                    break

                # 处理任务
                self._process_task(task)

                # 标记任务完成
                self.task_queue.task_done()

            except queue.Empty:
                # 超时，继续循环
                continue
            except Exception as e:
                logger.error(f"工作线程 {threading.current_thread().name} 处理任务时出错: {e}", exc_info=True)

        logger.info(f"工作线程 {threading.current_thread().name} 已退出")

    def _process_task(self, task: DownloaderTask):
        """处理单个任务"""
        task.status = TaskStatus.PROCESSING
        task.started_at = time.time()

        logger.info(f"开始处理任务: {task.task_id}")

        try:
            # 执行下载器添加逻辑
            success, message = self._execute_add_to_downloader(task)

            # 更新任务状态
            task.completed_at = time.time()
            task.processing_time = task.completed_at - task.started_at

            if success:
                task.status = TaskStatus.SUCCESS
                task.result_message = message
                self.stats['success_tasks'] += 1
                logger.info(f"任务处理成功: {task.task_id}, 耗时: {task.processing_time:.2f}秒")
            else:
                # 判断是否需要重试
                if task.retry_count < task.max_retries:
                    task.status = TaskStatus.RETRYING
                    task.retry_count += 1
                    task.error_message = message

                    # 指数退避重试
                    retry_delay = min(2 ** task.retry_count, 60)  # 最大60秒
                    threading.Timer(retry_delay, self._retry_task, args=[task]).start()

                    logger.warning(f"任务处理失败，将在{retry_delay}秒后重试: {task.task_id}, 错误: {message}")
                    return
                else:
                    task.status = TaskStatus.FAILED
                    task.error_message = message
                    self.stats['failed_tasks'] += 1
                    logger.error(f"任务处理最终失败: {task.task_id}, 错误: {message}")

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error_message = str(e)
            task.completed_at = time.time()
            task.processing_time = task.completed_at - task.started_at
            self.stats['failed_tasks'] += 1
            logger.error(f"任务处理异常: {task.task_id}, 异常: {e}", exc_info=True)

        # 更新批量转种记录（如果有）
        self._update_batch_record(task)

        # 执行回调函数
        self._execute_callback(task)

    def _retry_task(self, task: DownloaderTask):
        """重试任务"""
        if not self.is_running:
            task.status = TaskStatus.FAILED
            task.error_message = "队列服务已停止，无法重试"
            task.completed_at = time.time()
            self.stats['failed_tasks'] += 1
            return

        try:
            self.task_queue.put(task, timeout=5.0)
            logger.info(f"任务已重新加入队列: {task.task_id}, 第{task.retry_count}次重试")
        except queue.Full:
            task.status = TaskStatus.FAILED
            task.error_message = "队列已满，无法重试"
            task.completed_at = time.time()
            self.stats['failed_tasks'] += 1
            logger.error(f"重试失败，队列已满: {task.task_id}")

    def _execute_callback(self, task: DownloaderTask):
        """执行任务完成回调"""
        callback = self.task_callbacks.pop(task.task_id, None)
        if callback:
            try:
                callback(task)
            except Exception as e:
                logger.error(f"执行任务回调失败: {task.task_id}, 异常: {e}")

    def _execute_add_to_downloader(self, task: DownloaderTask) -> tuple[bool, str]:
        """
        执行添加到下载器的逻辑

        集成现有的 add_torrent_to_downloader 函数

        Returns:
            (success, message)
        """
        try:
            from utils.media_helper import add_torrent_to_downloader

            logger.info(f"执行下载器添加: URL={task.detail_page_url}, Path={task.save_path}, Downloader={task.downloader_id}")

            # 检查必要的管理器
            if not self.db_manager or not self.config_manager:
                return False, "数据库管理器或配置管理器未设置，无法执行下载器添加"

            # 调用现有的下载器添加函数
            success, message = add_torrent_to_downloader(
                detail_page_url=task.detail_page_url,
                save_path=task.save_path,
                downloader_id=task.downloader_id,
                db_manager=self.db_manager,
                config_manager=self.config_manager
            )

            if success:
                logger.info(f"下载器添加成功: {task.task_id}, 消息: {message}")
            else:
                logger.error(f"下载器添加失败: {task.task_id}, 错误: {message}")

            return success, message

        except ImportError:
            return False, "无法导入 add_torrent_to_downloader 函数"
        except Exception as e:
            logger.error(f"执行下载器添加时发生异常: {task.task_id}, 异常: {e}", exc_info=True)
            return False, f"执行下载器添加时出错: {str(e)}"

    def _update_batch_record(self, task: DownloaderTask):
        """更新批量转种记录

        Args:
            task: 已完成的任务
        """
        if not task.batch_id or not self.db_manager:
            return

        try:
            conn = self.db_manager._get_connection()
            cursor = self.db_manager._get_cursor(conn)

            # 构建下载器结果描述
            downloader_result = None
            if task.status == TaskStatus.SUCCESS:
                downloader_result = f"成功: {task.result_message or '添加到下载器成功'}"
            elif task.status == TaskStatus.FAILED:
                downloader_result = f"失败: {task.error_message or '添加到下载器失败'}"
            elif task.status == TaskStatus.CANCELLED:
                downloader_result = "已取消: 用户取消任务"

            # 准备SQL语句
            placeholder = self.db_manager.get_placeholder()
            update_sql = f"""
                UPDATE batch_enhance_records
                SET downloader_add_result = %s
                WHERE batch_id = %s AND torrent_id = %s
            """

            # 从上下文中获取种子ID
            torrent_id = task.context.get('torrent_id')
            if not torrent_id:
                logger.warning(f"任务 {task.task_id} 缺少 torrent_id，无法更新批量记录")
                return

            # 执行更新
            cursor.execute(update_sql, (downloader_result, task.batch_id, torrent_id))
            conn.commit()

            logger.debug(f"已更新批量转种记录: batch_id={task.batch_id}, torrent_id={torrent_id}, result={downloader_result}")

        except Exception as e:
            logger.error(f"更新批量转种记录失败: {task.task_id}, batch_id={task.batch_id}, 异常: {e}", exc_info=True)
        finally:
            if 'conn' in locals() and conn:
                conn.close()


def create_downloader_queue_service(config: dict = None) -> DownloaderQueueService:
    """
    根据配置创建下载器队列服务实例

    Args:
        config: 配置字典

    Returns:
        配置好的队列服务实例
    """
    if config is None:
        config = {}

    queue_config = config.get("downloader_queue", {})

    return DownloaderQueueService(
        max_queue_size=queue_config.get("max_queue_size", 1000),
        max_workers=queue_config.get("max_workers", 1)
    )


# 全局队列服务实例（稍后会在 app.py 中根据配置重新创建）
downloader_queue_service = DownloaderQueueService()
