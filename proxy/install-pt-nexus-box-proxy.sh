#!/bin/bash

# PT Nexus Proxy 安装脚本
# 用法:
#   wget -O - https://github.com/sqing33/Docker.pt-nexus/releases/download/latest/install-pt-nexus-box-proxy.sh | sudo bash
# 或者:
#   curl -sL https://github.com/sqing33/Docker.pt-nexus/releases/download/latest/install-pt-nexus-box-proxy.sh | sudo bash

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
        if ! curl -L -f -o "pt-nexus-box-proxy" "$PROXY_URL"; then
            error "curl下载失败"
            return 1
        fi
    # 如果curl不可用，尝试使用wget
    elif command -v wget >/dev/null 2>&1; then
        if ! wget -O "pt-nexus-box-proxy" "$PROXY_URL"; then
            error "wget下载失败"
            return 1
        fi
    else
        error "未找到curl或wget，请先安装其中一个"
        return 1
    fi

    # 检查下载是否成功
    if [ ! -f "pt-nexus-box-proxy" ]; then
        error "下载代理程序失败"
        return 1
    fi

    # 检查文件大小，确保不是空文件
    if [ ! -s "pt-nexus-box-proxy" ]; then
        error "下载的文件为空"
        rm -f "pt-nexus-box-proxy"
        return 1
    fi

    log "代理程序下载成功"
    return 0
}

# 下载BDInfo相关文件
download_bdinfo_tools() {
    log "正在下载 BDInfo 工具..."

    # 创建bdinfo目录
    mkdir -p "bdinfo"
    cd "bdinfo"

    # BDInfo文件列表
    local files=(
        "BDInfo"
        "BDInfoDataSubstractor"
        "liblzfse.so"
    )

    # 下载每个文件
    for file in "${files[@]}"; do
        local url="https://raw.githubusercontent.com/$REPO_OWNER/Docker.pt-nexus/refs/heads/main/server/core/bdinfo/$file"
        
        log "正在下载 $file..."
        
        # 尝试使用curl下载
        if command -v curl >/dev/null 2>&1; then
            if ! curl -L -f -o "$file" "$url"; then
                error "curl下载 $file 失败"
                cd ..
                return 1
            fi
        # 如果curl不可用，尝试使用wget
        elif command -v wget >/dev/null 2>&1; then
            if ! wget -O "$file" "$url"; then
                error "wget下载 $file 失败"
                cd ..
                return 1
            fi
        else
            error "未找到curl或wget，请先安装其中一个"
            cd ..
            return 1
        fi

        # 检查下载是否成功
        if [ ! -f "$file" ]; then
            error "下载 $file 失败"
            cd ..
            return 1
        fi

        # 检查文件大小，确保不是空文件
        if [ ! -s "$file" ]; then
            error "下载的 $file 为空"
            rm -f "$file"
            cd ..
            return 1
        fi

        # 设置可执行权限（仅对可执行文件）
        if [[ "$file" == "BDInfo" || "$file" == "BDInfoDataSubstractor" ]]; then
            chmod +x "$file"
        fi

        log "$file 下载成功"
    done

    cd ..
    log "所有 BDInfo 工具下载完成"
    return 0
}

# 设置权限
set_permissions() {
    log "设置文件权限..."
    chmod +x "pt-nexus-box-proxy"
    chmod +x "start.sh"
    chmod +x "stop.sh"
    
    # 设置BDInfo工具权限
    if [ -d "bdinfo" ]; then
        chmod -R 755 "bdinfo"
        chmod +x "bdinfo/BDInfo"
        chmod +x "bdinfo/BDInfoDataSubstractor"
        chmod 644 "bdinfo/liblzfse.so"
        log "BDInfo工具权限设置完成"
    fi
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
DEPS="ffmpeg mediainfo mpv fonts-noto-cjk libicu-dev"

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
        echo "这可能是更新过程中的正常情况。"
        echo "将继续启动新版本，旧进程将被替换。"
        echo "如需手动停止，请运行 ./stop.sh"
        echo ""
        # 停止旧进程
        kill "$PID" 2>/dev/null || true
        sleep 2
        if ps -p "$PID" > /dev/null; then
            kill -9 "$PID" 2>/dev/null || true
            sleep 1
        fi
        rm -f "$PID_FILE"
        echo "旧进程已停止"
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

# 检查并停止正在运行的代理
stop_running_proxy() {
    local PID_FILE="/var/run/pt-nexus-box-proxy.pid"

    if [ -f "$PID_FILE" ]; then
        local PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            log "检测到代理程序正在运行 (PID: $PID)，正在停止..."
            # 优雅停止
            kill "$PID" 2>/dev/null || true
            sleep 2

            # 检查是否已停止
            if ps -p "$PID" > /dev/null 2>&1; then
                warn "优雅停止失败，强制停止进程..."
                kill -9 "$PID" 2>/dev/null || true
                sleep 1
            fi

            # 清理PID文件
            rm -f "$PID_FILE"
            log "代理程序已停止"
        else
            log "检测到残留的PID文件，正在清理..."
            rm -f "$PID_FILE"
        fi
    else
        log "未检测到正在运行的代理程序"
    fi
}

# 备份当前版本
backup_current_version() {
    if [ -f "$INSTALL_DIR/pt-nexus-box-proxy" ]; then
        local BACKUP_DIR="$INSTALL_DIR/backup"
        local TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

        log "备份当前版本到 $BACKUP_DIR..."
        mkdir -p "$BACKUP_DIR"
        cp "$INSTALL_DIR/pt-nexus-box-proxy" "$BACKUP_DIR/pt-nexus-box-proxy_$TIMESTAMP"

        if [ $? -eq 0 ]; then
            log "备份成功: pt-nexus-box-proxy_$TIMESTAMP"
        else
            warn "备份失败，继续更新..."
        fi
    fi
}

# 恢复备份版本
restore_backup() {
    local BACKUP_DIR="$INSTALL_DIR/backup"

    if [ -d "$BACKUP_DIR" ]; then
        local LATEST_BACKUP=$(ls -t "$BACKUP_DIR"/pt-nexus-box-proxy_* 2>/dev/null | head -1)

        if [ -n "$LATEST_BACKUP" ]; then
            error "更新失败，正在恢复备份版本..."
            cp "$LATEST_BACKUP" "$INSTALL_DIR/pt-nexus-box-proxy"
            chmod +x "$INSTALL_DIR/pt-nexus-box-proxy"

            log "已恢复备份版本，请检查日志后手动启动服务"
            exit 1
        fi
    fi
}

# 启动代理程序
start_proxy() {
    log "启动代理程序..."
    ./start.sh
}

# 主函数
main() {
    log "开始安装/更新 PT Nexus Proxy..."

    check_root
    detect_os
    detect_architecture

    # 检查是否为更新安装
    if [ -f "$INSTALL_DIR/pt-nexus-box-proxy" ]; then
        log "检测到已存在的安装，正在更新..."
        backup_current_version
        stop_running_proxy
    fi

    create_install_dir
    create_start_script
    create_stop_script

    # 下载新版本，如果失败则恢复备份
    if ! download_proxy; then
        restore_backup
        exit 1
    fi

    # 下载BDInfo工具
    if ! download_bdinfo_tools; then
        warn "BDInfo工具下载失败，代理程序仍可正常使用但BDInfo功能将不可用"
    fi

    set_permissions

    # 验证新版本
    if [ ! -x "$INSTALL_DIR/pt-nexus-box-proxy" ]; then
        error "下载的二进制文件不可执行，正在恢复备份..."
        restore_backup
        exit 1
    fi

    start_proxy

    log "PT Nexus Proxy 安装/更新完成！"
    echo ""
    echo "安装目录: $INSTALL_DIR"
    if [ -d "$INSTALL_DIR/backup" ]; then
        echo "备份目录: $INSTALL_DIR/backup"
    fi
    echo "要查看日志，请运行: tail -f /var/run/pt-nexus-box-proxy.log"
    echo "要停止代理，请运行: $INSTALL_DIR/stop.sh"
    echo "要重启代理，请运行: $INSTALL_DIR/stop.sh && $INSTALL_DIR/start.sh"
}

# 执行主函数
main
