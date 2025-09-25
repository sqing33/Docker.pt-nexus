#!/bin/bash

# ==============================================================================
#                      Go qBittorrent 代理停止脚本
# ==============================================================================
#
# 功能:
#   1. 从 .pid 文件中读取进程ID。
#   2. 停止对应的后台进程。
#   3. 清理 .pid 文件。
#
# 使用方法:
#   1. 给予脚本执行权限: chmod +x stop.sh
#   2. 运行脚本: ./stop.sh
#
# ==============================================================================

# --- 配置 ---
PID_FILE="/var/run/pt-nexus-box-proxy.pid"

# --- 脚本开始 ---

echo "--- 正在停止 PT Nexus Box 代理 ---"

# 检查 PID 文件是否存在
if [ ! -f "$PID_FILE" ]; then
    echo "未找到 PID 文件 ($PID_FILE)。程序可能没有在运行。"
    exit 1
fi

# 读取 PID
PID=$(cat "$PID_FILE")

# 检查进程是否存在
if ! ps -p $PID > /dev/null; then
    echo "进程 (PID: $PID) 不存在。可能已被手动停止。"
    echo "正在清理无效的 PID 文件..."
    rm "$PID_FILE"
    exit 1
fi

# 尝试停止进程
echo "正在停止进程 (PID: $PID)..."
kill "$PID"

# 等待几秒钟并检查进程是否已停止
sleep 2

if ps -p $PID > /dev/null; then
    echo "警告: 无法通过 kill 正常停止进程，将尝试强制停止 (kill -9)..."
    kill -9 "$PID"
    sleep 1
fi

# 最终检查
if ps -p $PID > /dev/null; then
    echo "错误: 无法停止进程 (PID: $PID)。请手动检查。"
    exit 1
else
    echo "进程已成功停止。"
    echo "正在清理 PID 文件..."
    rm "$PID_FILE"
    echo "清理完成。"
fi

echo "----------------------------------------"
echo "PT Nexus Box 代理程序已停止。"
echo "----------------------------------------"

exit 0
