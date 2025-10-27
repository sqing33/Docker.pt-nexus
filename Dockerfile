# 阶段 1: 构建 Vue 前端
FROM node:20-alpine AS builder

WORKDIR /app/webui

# 安装 pnpm 包管理器
RUN npm install -g pnpm

# 复制依赖定义文件
COPY ./webui/package.json ./webui/pnpm-lock.yaml ./

# 根据锁文件安装依赖
RUN pnpm install --frozen-lockfile

# 复制前端所有源代码
COPY ./webui .

# 执行构建命令
RUN pnpm build

# 阶段 2: 构建 Go 批量增强服务
FROM golang:1.21-alpine AS go-builder

WORKDIR /app/batch-enhancer

# 复制 Go 模块文件
COPY ./batch-enhancer/go.mod ./

# 下载依赖
RUN go mod download

# 复制 Go 源代码
COPY ./batch-enhancer/main.go ./

# 编译 Go 应用为静态二进制文件
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o batch-enhancer main.go

# 阶段 3: 最终运行环境
FROM python:3.12-slim

WORKDIR /app

# 设置 Python 环境变量，避免生成 .pyc 文件并开启无缓冲输出
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# --- 关键修改：添加不走代理的地址列表 ---
# 确保容器内对 localhost 和 127.0.0.1 的请求直接连接，不通过代理
# (为了更好的兼容性，同时设置了小写和大写版本)
ENV no_proxy="localhost,127.0.0.1,::1"
ENV NO_PROXY="localhost,127.0.0.1,::1"

# 首先安装系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg \
    mpv \
    mediainfo \
    fonts-noto-cjk \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 复制并安装 Python 依赖
COPY ./server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 复制 Python 服务器代码
COPY ./server ./

# 从 builder 阶段复制已构建的前端文件
COPY --from=builder /app/webui/dist ./dist

# 从 go-builder 阶段复制已构建的 Go 批量增强服务
COPY --from=go-builder /app/batch-enhancer/batch-enhancer ./batch-enhancer
# 赋予其执行权限
RUN chmod +x ./batch-enhancer

# 复制启动脚本
COPY ./start-services.sh ./start-services.sh
# 赋予其执行权限
RUN chmod +x ./start-services.sh

# 创建数据目录，用于持久化存储
RUN mkdir -p /app/data

# 将数据目录声明为卷，以便可以挂载到宿主机
VOLUME /app/data

# 声明容器将使用的端口
EXPOSE 35274

# 容器启动时执行的默认命令
CMD ["./start-services.sh"]
