#!/usr/bin/env python3
"""
SSE (Server-Sent Events) 工具模块
用于实时推送BDInfo进度更新
"""

import json
import threading
import time
from queue import Queue, Empty
from typing import Dict, Set, Any
from flask import Response, stream_with_context
import logging

class SSEManager:
    """SSE连接管理器"""
    
    def __init__(self):
        # 存储所有活跃的SSE连接
        self.connections: Dict[str, Queue] = {}
        # 存储每个seed_id对应的连接ID集合
        self.seed_connections: Dict[str, Set[str]] = {}
        # 存储每个seed_id的最后更新时间（用于频率控制）
        self.last_update_time: Dict[str, float] = {}
        # 存储每个seed_id的执行模式（local/remote）
        self.seed_execution_mode: Dict[str, str] = {}
        # 推送频率配置（秒）
        self.local_update_interval = 1.0  # 本地任务1秒推送一次
        self.remote_update_interval = 5.0  # 远程任务5秒推送一次
        self.lock = threading.RLock()
        
    def add_connection(self, connection_id: str, seed_id: str) -> Queue:
        """添加一个新的SSE连接"""
        with self.lock:
            # 创建消息队列
            message_queue = Queue()
            
            # 存储连接
            self.connections[connection_id] = message_queue
            
            # 关联seed_id和连接
            if seed_id not in self.seed_connections:
                self.seed_connections[seed_id] = set()
            self.seed_connections[seed_id].add(connection_id)
            
            logging.info(f"SSE连接已添加: {connection_id} (seed_id: {seed_id})")
            
            # 发送连接成功消息
            connected_message = {
                "type": "connected",
                "connection_id": connection_id,
                "seed_id": seed_id
            }
            message_queue.put(connected_message)
            
            # 发送当前进度状态（如果存在）
            self._send_current_progress(seed_id, message_queue)
            
            return message_queue
    
    def _send_current_progress(self, seed_id: str, message_queue: Queue):
        """发送当前进度状态给新连接"""
        try:
            # 从 BDInfo 管理器获取当前进度
            from core.bdinfo.bdinfo_manager import get_bdinfo_manager
            bdinfo_manager = get_bdinfo_manager()
            
            current_progress = bdinfo_manager.get_current_progress(seed_id)
            if current_progress:
                progress_message = {
                    "type": "progress_update",
                    "data": current_progress
                }
                message_queue.put(progress_message)
                logging.info(f"已发送当前进度给新连接: {seed_id}")
        except Exception as e:
            logging.error(f"发送当前进度失败: {e}")
            # 发生错误时发送心跳，确保连接正常
            heartbeat_message = {
                "type": "heartbeat",
                "timestamp": time.time()
            }
            message_queue.put(heartbeat_message)
            
    def remove_connection(self, connection_id: str):
        """移除SSE连接"""
        with self.lock:
            if connection_id in self.connections:
                # 从seed_connections中移除
                for seed_id, connections in self.seed_connections.items():
                    if connection_id in connections:
                        connections.discard(connection_id)
                        if not connections:
                            del self.seed_connections[seed_id]
                        break
                
                # 删除连接
                del self.connections[connection_id]
                logging.info(f"SSE连接已移除: {connection_id}")
                
    def send_progress_update(self, seed_id: str, progress_data: Dict[str, Any]):
        """向特定seed的所有连接发送进度更新（支持差异化频率控制）"""
        with self.lock:
            if seed_id in self.seed_connections:
                # 检查是否需要发送更新（频率控制）
                if not self._should_send_update(seed_id):
                    return
                
                message = {
                    "type": "progress_update",
                    "data": progress_data
                }
                
                # 更新最后发送时间
                self.last_update_time[seed_id] = time.time()
                
                # 向所有相关连接发送消息
                for connection_id in self.seed_connections[seed_id].copy():
                    try:
                        queue = self.connections.get(connection_id)
                        if queue:
                            queue.put(message)
                    except Exception as e:
                        logging.error(f"发送SSE消息失败: {e}")
                        self.remove_connection(connection_id)

    def _should_send_update(self, seed_id: str) -> bool:
        """判断是否应该发送更新（基于执行模式和频率配置）"""
        current_time = time.time()
        
        # 获取执行模式
        execution_mode = self.seed_execution_mode.get(seed_id, "local")
        
        # 根据执行模式选择更新间隔
        if execution_mode == "remote":
            interval = self.remote_update_interval
        else:
            interval = self.local_update_interval
        
        # 检查是否到了发送时间
        last_time = self.last_update_time.get(seed_id, 0)
        return current_time - last_time >= interval

    def set_execution_mode(self, seed_id: str, execution_mode: str):
        """设置seed的执行模式"""
        with self.lock:
            self.seed_execution_mode[seed_id] = execution_mode
            logging.info(f"设置seed {seed_id} 的执行模式为: {execution_mode}")

    def get_execution_mode(self, seed_id: str) -> str:
        """获取seed的执行模式"""
        with self.lock:
            return self.seed_execution_mode.get(seed_id, "local")
                        
    def send_completion(self, seed_id: str, result: str):
        """发送完成通知"""
        with self.lock:
            if seed_id in self.seed_connections:
                message = {
                    "type": "completion",
                    "data": {
                        "mediainfo": result
                    }
                }
                
                # 向所有相关连接发送消息
                for connection_id in self.seed_connections[seed_id].copy():
                    try:
                        queue = self.connections.get(connection_id)
                        if queue:
                            queue.put(message)
                    except Exception as e:
                        logging.error(f"发送SSE消息失败: {e}")
                        self.remove_connection(connection_id)
                        
    def send_error(self, seed_id: str, error: str):
        """发送错误通知"""
        with self.lock:
            if seed_id in self.seed_connections:
                message = {
                    "type": "error",
                    "data": {
                        "error": error
                    }
                }
                
                # 向所有相关连接发送消息
                for connection_id in self.seed_connections[seed_id].copy():
                    try:
                        queue = self.connections.get(connection_id)
                        if queue:
                            queue.put(message)
                    except Exception as e:
                        logging.error(f"发送SSE消息失败: {e}")
                        self.remove_connection(connection_id)

# 全局SSE管理器实例
sse_manager = SSEManager()

def generate_sse_response(connection_id: str, seed_id: str):
    """生成SSE响应流"""
    message_queue = sse_manager.add_connection(connection_id, seed_id)
    
    def generate():
        try:
            # 发送连接成功消息
            yield f"data: {json.dumps({'type': 'connected', 'connection_id': connection_id})}\n\n"
            
            while True:
                try:
                    # 从队列获取消息（阻塞等待）
                    message = message_queue.get(timeout=1)
                    
                    # 发送SSE格式的消息
                    yield f"data: {json.dumps(message)}\n\n"
                    
                    # 如果是完成或错误消息，关闭连接
                    if message.get("type") in ["completion", "error"]:
                        break
                        
                except Empty:
                    # 发送心跳包保持连接
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                except Exception as e:
                    logging.error(f"SSE生成器异常: {e}")
                    break
                    
        finally:
            # 清理连接
            sse_manager.remove_connection(connection_id)
            
    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁用Nginx缓冲
            "Connection": "keep-alive"
        }
    )