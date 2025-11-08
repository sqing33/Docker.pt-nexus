#!/bin/bash

# PT Nexus Proxy 安装脚本
# 用法:
#   wget -O - https://github.com/OWNER/REPO/releases/latest/download/install-pt-nexus-box-proxy.sh | bash
# 或者:
#   curl -s https://github.com/OWNER/REPO/releases/latest/download/install-pt-nexus-box-proxy.sh | bash

set -e

# 配置变量
REPO_OWNER="sqing33"
REPO_NAME="pt-nexus"
INSTALL_DIR="/opt/pt-nexus-proxy"
SERVICE_NAME="pt-nexus-proxy"

# 颜色代码
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 日志函数
log() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查是否以root权限运行
check_root() {
    if [ "$EUID" -ne 0 ]; then
        error "请以root权限运行此脚本 (sudo curl ... | sudo bash)"
        exit 1
    fi
}

# 检测系统架构
detect_architecture() {
    ARCH=$(uname -m)
    case $ARCH in
        x86_64)
            ARCH="amd64"
            ;;
        aarch64|arm64)
            ARCH="arm64"
            ;;
        armv7l)
            ARCH="armv7"
            ;;
        *)
            error "不支持的架构: $ARCH"
            exit 1
            ;;
    esac
    log "检测到系统架构: $ARCH"
}

# 检测操作系统
detect_os() {
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        OS="linux"
    else
        error "仅支持Linux系统"
        exit 1
    fi
    log "检测到操作系统: $OS"
}

# 创建安装目录
create_install_dir() {
    log "创建安装目录: $INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"
    cd "$INSTALL_DIR"
}

# 下载代理程序
download_proxy() {
    log "正在下载 PT Nexus Proxy ($OS/$ARCH)..."

    # 构建下载URL
    PROXY_URL="https://github.com/$REPO_OWNER/$REPO_NAME/releases/latest/download/pt-nexus-box-proxy-$OS-$ARCH"

    # 尝试使用curl下载
    if command -v curl >/dev/null 2>&1; then
        curl -L -o "pt-nexus-box-proxy" "$PROXY_URL"
    # 如果curl不可用，尝试使用wget
    elif command -v wget >/dev/null 2>&1; then
        wget -O "pt-nexus-box-proxy" "$PROXY_URL"
    else
        error "未找到curl或wget，请先安装其中一个"
        exit 1
    fi

    # 检查下载是否成功
    if [ ! -f "pt-nexus-box-proxy" ]; then
        error "下载代理程序失败"
        exit 1
    fi

    log "代理程序下载成功"
}

# 设置权限
set_permissions() {
    log "设置文件权限..."
    chmod +x "pt-nexus-box-proxy"
    chmod +x "start.sh"
    chmod +x "stop.sh"
}

# 创建启动脚本
create_start_script() {
    log "创建启动脚本..."
    cat > "start.sh" << 'EOF'
#!/bin/bash

# PT Nexus Proxy 启动脚本

INSTALL_DIR="/opt/pt-nexus-proxy"
PROXY_BIN="pt-nexus-box-proxy"
LOG_FILE="/var/run/pt-nexus-box-proxy.log"
PID_FILE="/var/run/pt-nexus-box-proxy.pid"

echo "--- PT Nexus Proxy 启动脚本 ---"

# 检查代理程序文件是否存在
if [ ! -f "$PROXY_BIN" ]; then
    echo "错误: 代理程序 '$PROXY_BIN' 不存在于当前目录。"
    exit 1
fi

# 询问用户输入端口
echo "请输入代理服务端口 (默认: 9090):"
read -r PORT_INPUT < /dev/tty
if [ -z "$PORT_INPUT" ]; then
    PORT_INPUT="9090"
fi
echo "将使用端口: $PORT_INPUT"

# 1. 安装依赖
echo "[1/4] 正在检查并安装依赖 (需要 sudo 权限)..."

# 定义需要的依赖列表
DEPS="ffmpeg mediainfo mpv fonts-noto-cjk"

# 检测包管理器
if command -v apt-get &> /dev/null; then
    echo "检测到 Debian/Ubuntu (apt-get)..."
    apt-get update -y
    for pkg in $DEPS; do
        if ! dpkg -s "$pkg" &> /dev/null; then
            echo "正在安装 $pkg..."
            apt-get install -y "$pkg"
        else
            echo "$pkg 已安装。"
        fi
    done
elif command -v yum &> /dev/null; then
    echo "检测到 CentOS/RHEL (yum)..."
    echo "需要 EPEL 和 RPM Fusion 源来安装 ffmpeg 和 mpv..."

    # 安装 EPEL
    if ! rpm -q epel-release &> /dev/null; then
        yum install -y epel-release
    fi

    # 对于 CentOS 8+ 可能需要启用 PowerTools/CRB
    if grep -q "release 8" /etc/redhat-release || grep -q "release 9" /etc/redhat-release; then
        dnf config-manager --set-enabled crb || dnf config-manager --set-enabled PowerTools
    fi

    # 安装 RPM Fusion
    if ! rpm -q rpmfusion-free-release &> /dev/null; then
        yum localinstall --nogpgcheck https://download1.rpmfusion.org/free/el/rpmfusion-free-release-$(rpm -E %rhel).noarch.rpm https://download1.rpmfusion.org/nonfree/el/rpmfusion-nonfree-release-$(rpm -E %rhel).noarch.rpm -y
    fi

    yum install -y $DEPS
else
    echo "警告: 无法检测到 apt-get 或 yum。请手动安装 '$DEPS'。"
fi

echo "依赖检查完成。"

# 2. 设置可执行权限
echo "[2/4] 正在为 '$PROXY_BIN' 设置可执行权限..."
chmod +x "$PROXY_BIN"
echo "权限设置完成。"

# 3. 检查程序是否已在运行
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null; then
        echo "警告: 代理程序似乎已在运行 (PID: $PID)。"
        echo "如果需要重启，请先运行 ./stop.sh"
        exit 1
    else
        echo "检测到残留的 PID 文件，正在清理..."
        rm "$PID_FILE"
    fi
fi

# 4. 以后台模式启动程序
echo "[3/4] 正在后台启动 '$PROXY_BIN' (端口: $PORT_INPUT)..."

# 使用 nohup 将程序放到后台，并将标准输出和错误输出重定向到日志文件
# 将端口作为参数传递给程序
nohup ./$PROXY_BIN "$PORT_INPUT" > "$LOG_FILE" 2>&1 &
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
EOF
}

# 创建停止脚本
create_stop_script() {
    log "创建停止脚本..."
    cat > "stop.sh" << 'EOF'
#!/bin/bash

# PT Nexus Proxy 停止脚本

PID_FILE="/var/run/pt-nexus-box-proxy.pid"

echo "--- 正在停止 PT Nexus Proxy ---"

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
EOF
}

# 启动代理程序
start_proxy() {
    log "启动代理程序..."
    ./start.sh
}

# 主函数
main() {
    log "开始安装 PT Nexus Proxy..."

    check_root
    detect_os
    detect_architecture
    create_install_dir
    create_start_script
    create_stop_script
    download_proxy
    set_permissions
    start_proxy

    log "PT Nexus Proxy 安装完成！"
    echo ""
    echo "安装目录: $INSTALL_DIR"
    echo "要查看日志，请运行: tail -f $INSTALL_DIR/proxy.log"
    echo "要停止代理，请运行: $INSTALL_DIR/stop.sh"
}

# 执行主函数
main
