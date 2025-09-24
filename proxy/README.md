# qBittorrent 增强版 Go API 代理 🚀

一个为 qBittorrent 设计的高性能 Go 语言 API 代理服务。它彻底解决了 Python 等应用在广域网环境下直连 qBittorrent 时遇到的**网络延迟高、连接不稳定、无法处理远程文件**等核心痛点。

## ✨ 为什么需要这个代理？

直接从本地项目（如 server Web 应用）连接位于远程服务器上的 qBittorrent 客户端，通常会遇到以下问题：

-   **高延迟**：每次 API 请求都需要跨越公网，耗时较长，导致前端响应缓慢。
-   **连接中断**：不稳定的网络环境容易导致连接超时或被重置，影响数据同步的可靠性。
-   **无法执行本地命令**：项目无法对远程服务器上的视频文件执行 `ffmpeg` 截图或 `mediainfo` 分析等本地命令。

本代理服务作为中间层，部署在与 qBittorrent 相同的服务器或局域网内，完美地解决了上述所有问题。

## 🚀 核心功能

-   **⚡ 高效的种子信息聚合 (`/api/torrents/all`)**
    -   并发处理来自多个下载器的请求，极大地缩短了数据获取时间。
    -   可按需获取 `comment` 和 `trackers` 等详细信息。
    -   所有响应均经过 Gzip 压缩，显著减少网络传输量。

-   **🎬 远程媒体处理 (核心功能)**
    -   **远程截图 (`/api/media/screenshot`)**: 接收一个远程视频文件路径，自动使用 `ffmpeg` 截图并上传到图床（当前支持 Pixhost），返回 BBCode 格式的图片链接。
    -   **远程 MediaInfo (`/api/media/mediainfo`)**: 接收一个远程视频文件路径，自动使用 `mediainfo` 分析并返回完整的文本报告。

-   **📊 稳定的服务器统计 (`/api/stats/server`)**
    -   快速获取下载器的实时上传/下载速度和累计流量数据。
    -   作为下载器健康状况的可靠数据源。

-   **❤️ 健康检查 (`/api/health`)**
    -   提供一个轻量级的端点，用于监控代理服务是否正常运行。

## 🛠️ 部署指南

### 1. 前提条件

在运行本代理的**服务器**上，必须安装以下命令行工具：

-   `ffmpeg` (用于截图)
-   `mediainfo` (用于分析媒体文件)

**在 Debian/Ubuntu 上安装:**
```bash
sudo apt update && sudo apt install ffmpeg mediainfo -y
在 CentOS/RHEL 上安装:
code
Bash
sudo yum install -y epel-release
sudo yum localinstall --nogpgcheck https://download1.rpmfusion.org/free/el/rpmfusion-free-release-$(rpm -E %rhel).noarch.rpm -y
sudo yum install -y ffmpeg mediainfo
2. 部署文件
将以下文件上传到服务器的同一个目录下（例如 /opt/qb-proxy）：
code
Code
/opt/qb-proxy/
├── qb-proxy        # 编译好的 Go 程序二进制文件
├── start.sh        # 启动脚本
└── stop.sh         # 停止脚本
3. 启动服务
首先，为脚本添加可执行权限：
code
Bash
chmod +x start.sh stop.sh
然后，运行启动脚本：
code
Bash
./start.sh
服务将在后台启动，监听 9090 端口。所有输出将记录在 proxy.log 文件中。
4. 管理服务
查看实时日志: tail -f proxy.log
停止服务: ./stop.sh
📚 API 文档
1. 获取种子信息
Endpoint: POST /api/torrents/all
描述: 并发获取一个或多个 qBittorrent 客户端的完整种子列表。
请求体 (JSON):
code
JSON
{
    "downloaders": [
        {
            "id": "downloader-uuid-1",
            "type": "qbittorrent",
            "host": "http://localhost:8080",
            "username": "admin",
            "password": "password123"
        }
    ],
    "include_comment": true,
    "include_trackers": true
}
成功响应 (JSON):
code
JSON
[
    {
        "hash": "d149068fd5c2aa20...",
        "name": "[巨塔之后].The.Queen.of.Castle...",
        "size": 31789957313,
        "progress": 1.0,
        "state": "stalledUP",
        "save_path": "/downloads/",
        "comment": "https://example.com/details.php?id=123",
        "trackers": [{"url": "https://tracker.example.com/announce"}],
        "uploaded": 1875378176,
        "downloader_id": "downloader-uuid-1"
    }
]
2. 获取服务器统计
Endpoint: POST /api/stats/server
描述: 获取一个或多个下载器的实时速度和累计流量。
请求体 (JSON):
code
JSON
[
    {
        "id": "downloader-uuid-1",
        "type": "qbittorrent",
        "host": "http://localhost:8080",
        "username": "admin",
        "password": "password123"
    }
]
成功响应 (JSON):
code
JSON
[
    {
        "downloader_id": "downloader-uuid-1",
        "download_speed": 102400,
        "upload_speed": 51200,
        "total_download": 1099511627776,
        "total_upload": 2199023255552
    }
]
3. 远程截图并上传
Endpoint: POST /api/media/screenshot
描述: 对服务器上的指定视频文件进行截图，上传到图床，并返回 BBCode。
请求体 (JSON):
code
JSON
{
    "remote_path": "/home/user/downloads/My.Movie.2025.mkv"
}
成功响应 (JSON):
code
JSON
{
    "success": true,
    "message": "截图上传成功",
    "bbcode": "[img]https://img1.pixhost.to/images/.../screenshot1.jpg[/img]\n[img]https://img1.pixhost.to/images/.../screenshot2.jpg[/img]"
}
4. 远程获取 MediaInfo
Endpoint: POST /api/media/mediainfo
描述: 获取服务器上指定视频文件的 MediaInfo 摘要报告。
请求体 (JSON):
code
JSON
{
    "remote_path": "/home/user/downloads/My.Movie.2025.mkv"
}
成功响应 (JSON):
code
JSON
{
    "success": true,
    "message": "MediaInfo 获取成功",
    "mediainfo_text": "General\nComplete name                            : /home/user/downloads/My.Movie.2025.mkv\nFormat                                   : Matroska\n..."
}
🐍 Python 项目集成示例
在你的 Python 项目（如 media_helper.py）中，你可以用简单的 HTTP 请求来调用代理，从而替代本地的 ffmpeg 和 mediainfo 调用。
code
Python
import requests

# 你的 Go 代理的地址
PROXY_BASE_URL = "http://your-server-ip:9090"

def get_remote_screenshots(remote_video_path: str) -> str:
    """通过 Go 代理获取远程视频的截图。"""
    api_url = f"{PROXY_BASE_URL}/api/media/screenshot"
    try:
        response = requests.post(api_url, json={"remote_path": remote_video_path}, timeout=180)
        response.raise_for_status()
        data = response.json()
        return data.get("bbcode", f"代理错误: {data.get('message')}")
    except requests.exceptions.RequestException as e:
        return f"调用代理失败: {e}"

def get_remote_mediainfo(remote_video_path: str) -> str:
    """通过 Go 代理获取远程视频的 MediaInfo。"""
    api_url = f"{PROXY_BASE_URL}/api/media/mediainfo"
    try:
        response = requests.post(api_url, json={"remote_path": remote_video_path}, timeout=60)
        response.raise_for_status()
        data = response.json()
        return data.get("mediainfo_text", f"代理错误: {data.get('message')}")
    except requests.exceptions.RequestException as e:
        return f"调用代理失败: {e}"

# --- 使用 ---
# remote_file = "/path/on/your/server/video.mkv"
# screenshots = get_remote_screenshots(remote_file)
# mediainfo = get_remote_mediainfo(remote_file)
# print(screenshots)
# print(mediainfo)
