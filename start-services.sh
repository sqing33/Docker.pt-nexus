#!/bin/bash

# 启动 Python Flask 服务
echo "Starting Flask application on port 35274..."
python app.py

# 等待十秒确保 Go 服务启动
sleep 10

# 启动 batch-enhancer (Go 服务)
echo "Starting batch-enhancer service on port 5275..."
./batch-enhancer &
