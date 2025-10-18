#!/bin/bash

# ==============================================================================
#                 Go qBittorrent 代理部署与启动脚本 (mpv 支持版)
# ==============================================================================
#
# 功能:
#   1. 检查并安装必要的依赖 (ffmpeg, mediainfo, mpv)。
#   2. 为 Go 程序设置可执行权限。
#   3. 以后台模式启动 Go 程序，并将日志输出到文件。
#   4. 记录程序的进程ID (PID)，方便管理。
#
# 使用方法:
#   1. 将此脚本与编译好的 Go 程序 (例如 pt-nexus-box-proxy) 放在同一目录下。
#   2. 给予脚本执行权限: chmod +x start.sh
#   3. 运行脚本: ./start.sh
#
# ==============================================================================

# --- 配置 ---
# 设置你的 Go 程序的文件名
APP_NAME="pt-nexus-box-proxy"
# 日志文件名
LOG_FILE="/var/run/pt-nexus-box-proxy.log"
# PID 文件名 (使用硬路径)
PID_FILE="/var/run/pt-nexus-box-proxy.pid"

# --- 脚本开始 ---

echo "--- Go qBittorrent 代理启动脚本 ---"

# 检查代理程序文件是否存在
if [ ! -f "$APP_NAME" ]; then
    echo "错误: 代理程序 '$APP_NAME' 不存在于当前目录。"
    echo "请将编译好的 Go 程序与此脚本放在一起。"
    exit 1
fi

# 询问用户输入端口
echo "请输入代理服务端口 (默认: 9090):"
read -r PORT_INPUT
if [ -z "$PORT_INPUT" ]; then
    PORT_INPUT="9090"
fi
echo "将使用端口: $PORT_INPUT"

# 1. 安装依赖
echo "[1/4] 正在检查并安装依赖 (需要 sudo 权限)..."

# 定义需要的依赖列表
# [核心修改] 在依赖列表中加入了 mpv 和中文字体支持
DEPS="ffmpeg mediainfo mpv fonts-noto-cjk"

# 检测包管理器
if command -v apt-get &> /dev/null; then
    echo "检测到 Debian/Ubuntu (apt-get)..."
    sudo apt-get update -y
    # 使用循环安装，更清晰
    for pkg in $DEPS; do
        if ! dpkg -s "$pkg" &> /dev/null; then
            echo "正在安装 $pkg..."
            sudo apt-get install -y "$pkg"
        else
            echo "$pkg 已安装。"
        fi
    done
elif command -v yum &> /dev/null; then
    echo "检测到 CentOS/RHEL (yum)..."
    # 对于YUM，安装 mpv 和 ffmpeg 通常需要 EPEL 和 RPM Fusion 源
    echo "需要 EPEL 和 RPM Fusion 源来安装 ffmpeg 和 mpv..."
    
    # 安装 EPEL
    if ! rpm -q epel-release &> /dev/null; then
        sudo yum install -y epel-release
    fi
    
    # 对于 CentOS 8+ 可能需要启用 PowerTools/CRB
    if grep -q "release 8" /etc/redhat-release || grep -q "release 9" /etc/redhat-release; then
        sudo dnf config-manager --set-enabled crb || sudo dnf config-manager --set-enabled PowerTools
    fi
    
    # 安装 RPM Fusion
    if ! rpm -q rpmfusion-free-release &> /dev/null; then
        sudo yum localinstall --nogpgcheck https://download1.rpmfusion.org/free/el/rpmfusion-free-release-$(rpm -E %rhel).noarch.rpm https://download1.rpmfusion.org/nonfree/el/rpmfusion-nonfree-release-$(rpm -E %rhel).noarch.rpm -y
    fi
    
    sudo yum install -y $DEPS
else
    echo "警告: 无法检测到 apt-get 或 yum。请手动安装 '$DEPS'。"
fi

# 最终检查，确保依赖都已安装
for pkg in $DEPS; do
    if ! command -v "$pkg" &> /dev/null; then
        echo "错误: 依赖 '$pkg' 安装失败或未在 PATH 中找到。"
        echo "请检查错误信息并重试。"
        exit 1
    fi
done

echo "依赖检查完成。"

# 2. 设置可执行权限
echo "[2/4] 正在为 '$APP_NAME' 设置可执行权限..."
chmod +x "$APP_NAME"
echo "权限设置完成。"

# 3. 检查程序是否已在运行
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    # 使用 ps -p 检查进程是否存在，更可靠
    if ps -p "$PID" > /dev/null; then
        echo "警告: 代理程序似乎已在运行 (PID: $PID)。"
        echo "如果需要重启，请先运行 ./stop.sh"
        exit 1
    else
        # PID 文件存在但进程不存在，清理旧的 PID 文件
        echo "检测到残留的 PID 文件，正在清理..."
        rm "$PID_FILE"
    fi
fi

# 4. 以后台模式启动程序
echo "[3/4] 正在后台启动 '$APP_NAME' (端口: $PORT_INPUT)..."

# 使用 nohup 将程序放到后台，并将标准输出和错误输出重定向到日志文件
# 将端口作为参数传递给程序
nohup ./$APP_NAME "$PORT_INPUT" > "$LOG_FILE" 2>&1 &

# 获取新启动的进程的 PID
APP_PID=$!

# 等待一秒钟，然后检查进程是否真的启动了
sleep 1
if ! ps -p "$APP_PID" > /dev/null; then
    echo "错误: 程序启动后立即退出了！"
    echo "请检查日志文件 '$LOG_FILE' 获取详细的错误信息。"
    exit 1
fi

# 将 PID 写入文件
echo "$APP_PID" > "$PID_FILE"

echo "[4/4] 启动成功！"
echo "----------------------------------------"
echo "  - 进程ID (PID): $APP_PID"
echo "  - 监听端口:     $PORT_INPUT"
echo "  - 日志文件:     $LOG_FILE"
echo "  - PID 文件:     $PID_FILE"
echo ""
echo "你可以使用 'tail -f $LOG_FILE' 命令实时查看日志。"
echo "要停止程序，请运行 ./stop.sh"
echo "----------------------------------------"

exit 0
