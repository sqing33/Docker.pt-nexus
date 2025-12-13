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
        """向特定seed的所有连接发送进度更新"""
        with self.lock:
            if seed_id in self.seed_connections:
                message = {
                    "type": "progress_update",
                    "data": progress_data
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