#!/bin/bash

# 添加环境变量
export no_proxy="localhost,127.0.0.1,::1"
export NO_PROXY="localhost,127.0.0.1,::1"

# 自动应用容器内更新（如果repo有新版本）
auto_apply_update() {
    local REPO_CONFIG="/app/data/updates/repo/update_mapping.json"
    local LOCAL_CONFIG="/app/update_mapping.json"

    # 检查repo配置文件是否存在
    if [ ! -f "$REPO_CONFIG" ]; then
        echo "未找到repo更新配置，跳过自动更新检查"
        return
    fi

    # 获取版本号
    repo_version=$(grep '"version"' "$REPO_CONFIG" | head -1 | sed -E 's/.*"version": *"([^"]*)".*/\1/')
    local_version=$(grep '"version"' "$LOCAL_CONFIG" | head -1 | sed -E 's/.*"version": *"([^"]*)".*/\1/')

    echo "本地版本: $local_version, Repo版本: $repo_version"

    # 比较版本（简单字符串比较，去掉v前缀）
    repo_ver_num=${repo_version#v}
    local_ver_num=${local_version#v}

    if [ "$repo_ver_num" != "$local_ver_num" ]; then
        echo "检测到新版本，自动应用更新..."

        # 使用python解析JSON
        python3 -c "
import json, os, shutil
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
            for d in dirs[:]:
                if any(d == pat or d.endswith(pat.replace('*', '')) for pat in exclude):
                    dirs.remove(d)
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
"

        # 更新本地配置文件
        cp "$REPO_CONFIG" "$LOCAL_CONFIG"
        echo "更新应用完成，新版本: $repo_version"
    else
        echo "版本一致，无需更新"
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
./batch &

wait -n
