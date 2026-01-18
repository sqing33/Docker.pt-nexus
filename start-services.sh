#!/bin/bash

# 添加环境变量
export no_proxy="localhost,127.0.0.1,::1"
export NO_PROXY="localhost,127.0.0.1,::1"

# 自动应用容器内更新（如果repo有新版本）
auto_apply_update() {
    local REPO_CONFIG="/app/data/updates/repo/CHANGELOG.json"
    local LOCAL_CONFIG="/app/CHANGELOG.json"

    # 检查repo配置文件是否存在
    if [ ! -f "$REPO_CONFIG" ]; then
        echo "未找到repo更新配置，跳过自动更新检查"
        return
    fi

    # 获取版本号 (使用简单的grep提取)
    repo_version=$(grep '"version"' "$REPO_CONFIG" | head -1 | sed -E 's/.*"version": *"([^"]*)".*/\1/')
    local_version=$(grep '"version"' "$LOCAL_CONFIG" | head -1 | sed -E 's/.*"version": *"([^"]*)".*/\1/')

    echo "本地版本: $local_version, Repo版本: $repo_version"

    # ================= 修复部分开始 =================
    # 使用 Python 进行语义化版本比较 (Repo > Local)
    # 只有当 Repo 版本确实大于 Local 版本时，才输出 'update'
    should_update=$(python3 -c "
try:
    def parse_version(v):
        # 去掉 v 或 V，按 . 分割，转为数字列表
        return [int(x) for x in v.strip().lstrip('vV').split('.')]
    
    repo = parse_version('$repo_version')
    local = parse_version('$local_version')
    
    # 比较列表，Python 原生支持 [3,3,3] > [3,3,0] 这种比较
    if repo > local:
        print('update')
    else:
        print('skip')
except Exception as e:
    # 如果解析出错（比如版本号格式不对），默认不更新，防止破坏
    print('error')
")
    # ================= 修复部分结束 =================

    if [ "$should_update" = "update" ]; then
        echo "检测到新版本 ($repo_version > $local_version)，自动应用更新..."

        # 使用python解析JSON并同步文件
        python3 -c "
import json, os, shutil, sys

try:
    with open('$REPO_CONFIG', 'r') as f:
        config = json.load(f)

    for mapping in config['mappings']:
        source = os.path.join('/app/data/updates/repo', mapping['source'])
        target = mapping['target']
        exclude = mapping.get('exclude', []) + ['*.pyc', '__pycache__', '*.backup', '.env']
        executable = mapping.get('executable', False)
        
        print(f'同步 {source} -> {target}')
        if os.path.isdir(source):
            # 用shutil复制目录，跳过exclude
            for root, dirs, files in os.walk(source):
                rel_root = os.path.relpath(root, source)
                # 过滤目录
                for d in dirs[:]:
                    if any(d == pat or d.endswith(pat.replace('*', '')) for pat in exclude):
                        dirs.remove(d)
                # 过滤文件
                for file in files:
                    if any(file == pat or file.endswith(pat.replace('*', '')) for pat in exclude):
                        continue
                    src_file = os.path.join(root, file)
                    dst_file = os.path.join(target, rel_root, file)
                    os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                    shutil.copy2(src_file, dst_file)
        elif os.path.isfile(source):
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(source, target)
        
        if executable:
            os.chmod(target, 0o755)
            
except Exception as e:
    print(f'更新文件时发生错误: {e}')
    sys.exit(1)
"
        # 只有 Python 脚本执行成功才覆盖版本文件
        if [ $? -eq 0 ]; then
            cp "$REPO_CONFIG" "$LOCAL_CONFIG"
            echo "更新应用完成，新版本: $repo_version"
        else
            echo "文件同步失败，跳过版本号更新"
        fi

    elif [ "$should_update" = "error" ]; then
        echo "版本号解析错误，跳过自动更新检查"
    else
        echo "本地版本 ($local_version) 已经是最新或更高，跳过启动更新"
    fi
}

# 执行自动更新检查
auto_apply_update

# 启动 Go updater
echo "正在启动 updater 服务，端口：5274..."
./updater &

# 启动 Python Flask 服务
echo "正在启动 Flask 应用，端口：5275..."
python app.py &

# 启动 Go batch
echo "正在启动 batch 服务，端口：5276..."
detect_arch() {
    local arch
    arch="$(uname -m 2>/dev/null || true)"
    case "$arch" in
        x86_64|amd64) echo "x86" ;;
        aarch64|arm64) echo "arm" ;;
        *) echo "unknown" ;;
    esac
}

select_batch_bin() {
    local arch
    arch="$(detect_arch)"

    if [ "$arch" = "arm" ] && [ -x "./batch-arm" ]; then
        echo "./batch-arm"
        return
    fi
    if [ "$arch" = "x86" ] && [ -x "./batch-x86" ]; then
        echo "./batch-x86"
        return
    fi

    # 兼容 Dockerfile 里的默认二进制名称
    if [ -x "./batch" ]; then
        echo "./batch"
        return
    fi

    # 兜底：文件存在但不可执行，也尽量尝试启动（方便定位权限问题）
    if [ -f "./batch-arm" ] && [ "$arch" = "arm" ]; then
        echo "./batch-arm"
        return
    fi
    if [ -f "./batch-x86" ] && [ "$arch" = "x86" ]; then
        echo "./batch-x86"
        return
    fi

    echo "./batch"
}

BATCH_BIN="$(select_batch_bin)"
echo "batch 二进制: ${BATCH_BIN} (arch=$(detect_arch))"
"$BATCH_BIN" &

wait -n
