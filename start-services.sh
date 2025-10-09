#!/bin/bash

# 启动 batch-enhancer (Go 服务)
echo "Starting batch-enhancer service on port 5275..."
./batch-enhancer &

# 等待一秒确保 Go 服务启动
sleep 1

# 启动 Python Flask 服务
echo "Starting Flask application on port 5272..."
python app.py
