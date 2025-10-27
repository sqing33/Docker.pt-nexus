#!/bin/bash

# 添加环境变量
export no_proxy="localhost,127.0.0.1,::1"
export NO_PROXY="localhost,127.0.0.1,::1"

# 启动 Python Flask 服务
echo "正在启动 Flask 应用，端口：5274..."
python app.py &

# 启动 batch-enhancer (Go 服务)
echo "正在启动 batch-enhancer 服务，端口：5275..."
./batch-enhancer &

wait -n
