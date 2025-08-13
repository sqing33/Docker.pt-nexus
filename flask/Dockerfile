# Dockerfile
# 使用一个轻量级的 Python 官方镜像作为基础
FROM python:3.12-alpine

# 设置工作目录
WORKDIR /app

# 复制依赖文件
COPY requirements.txt .

# 设置 pip 源为华为云镜像，并安装依赖， --no-cache-dir 减少镜像体积
RUN pip install --no-cache-dir -i https://repo.huaweicloud.com/repository/pypi/simple -r requirements.txt

# 复制所有应用代码到工作目录
COPY . .

# 创建用于持久化存储配置的数据卷目录
RUN mkdir /data

# 暴露容器的 5000 端口
EXPOSE 5000

# 容器启动时执行的命令
# 使用 gunicorn 启动应用，监听所有网络接口
CMD ["gunicorn", "--workers", "3", "--bind", "0.0.0.0:5000", "app:app"]
