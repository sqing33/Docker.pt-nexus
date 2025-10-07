"""
实时日志流管理器
用于在任务执行过程中推送实时日志到前端
"""

import queue
import logging
import threading
import time
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)


class LogStreamer:
    """实时日志流收集器"""
    
    def __init__(self):
        self.streams: Dict[str, queue.Queue] = {}
        self.lock = threading.Lock()
        logger.info("日志流管理器已初始化")
    
    def create_stream(self, task_id: str) -> queue.Queue:
        """创建新的日志流
        
        Args:
            task_id: 任务ID
            
        Returns:
            日志队列
        """
        with self.lock:
            if task_id not in self.streams:
                self.streams[task_id] = queue.Queue(maxsize=1000)
                logger.info(f"创建日志流: {task_id}")
            return self.streams[task_id]
    
    def get_stream(self, task_id: str) -> Optional[queue.Queue]:
        """获取指定任务的日志流
        
        Args:
            task_id: 任务ID
            
        Returns:
            日志队列或None
        """
        return self.streams.get(task_id)
    
    def emit_log(self, task_id: str, step: str, message: str, status: str = "processing", extra: Optional[Dict[str, Any]] = None):
        """发送日志事件
        
        Args:
            task_id: 任务ID
            step: 步骤名称（如："获取种子信息"）
            message: 日志信息
            status: 状态 (processing/success/error/info/warning)
            extra: 额外数据（如进度百分比、子步骤等）
        """
        stream = self.get_stream(task_id)
        if stream:
            try:
                event = {
                    "timestamp": time.time(),
                    "step": step,
                    "message": message,
                    "status": status
                }
                if extra:
                    event.update(extra)
                
                stream.put(event, block=False)
                logger.debug(f"[{task_id}] {step}: {message} ({status})")
            except queue.Full:
                logger.warning(f"日志队列已满，丢弃消息: {task_id}")
        else:
            logger.warning(f"未找到日志流: {task_id}")
    
    def close_stream(self, task_id: str):
        """关闭并清理日志流
        
        Args:
            task_id: 任务ID
        """
        with self.lock:
            if task_id in self.streams:
                try:
                    # 发送结束标记
                    self.streams[task_id].put(None, block=False)
                    logger.info(f"关闭日志流: {task_id}")
                except queue.Full:
                    pass
                
                # 延迟清理，确保前端接收到结束标记
                def cleanup():
                    time.sleep(60)
                    with self.lock:
                        if task_id in self.streams:
                            self.streams.pop(task_id)
                            logger.info(f"清理日志流: {task_id}")
                
                threading.Thread(target=cleanup, daemon=True).start()
    
    def get_active_streams(self) -> int:
        """获取活跃的日志流数量
        
        Returns:
            活跃流数量
        """
        with self.lock:
            return len(self.streams)


# 全局单例
log_streamer = LogStreamer()
