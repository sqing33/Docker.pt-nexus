# <img width="50" height="50" alt="image" src="https://github.com/user-attachments/assets/8edcccf8-a4ca-4fcb-8224-8d25f15642eb" /> PT Nexus

## 一、项目概述

PT Torrent Hub 是专为 PT 用户设计的多功能聚合管理平台，旨在统一整合和分析来自 **qBittorrent** 与 **Transmission** 两大下载器的种子数据与流量信息，打造一站式 PT 管理中心。

### 1. 下载器流量分析

- **流量统计**：后台自动以分钟为单位，精确记录每个下载器的上传 / 下载增量。
- **图表分析**：通过 ECharts 可视化图表展示流量变化，支持查看`近 1/6/12 小时、今日、本周、本月、半年`的上传下载数据。
- **历史流量**：通过环境变量自定义 qBittorrent 历史总流量；Transmission 历史数据自动从客户端获取并校准。

### 2. 聚合种子管理

- **跨下载器种子聚合**：将 qBittorrent 与 Transmission 中的所有 PT 种子整合到统一列表，实现一站式查看与管理。
- **站点存在性查询**：配合 MoviePilot 的插件`下载器助手`工具为种子打上站点标签后，可查看每个种子已铺种的站点。
- **一键跳转详情页**：自动提取种子注释中的详情页 ID 或链接，结合自定义规则生成种子详情对应链接。

## 二、Docker 部署

### 环境变量

|     参数      |                            说明                            |        示例        |
| :-----------: | :--------------------------------------------------------: | :----------------: |
|      TZ       |                 设置容器时区，确保时间同步                 |   Asia/Shanghai    |
| QB_HIST_DL_GB | qBittorrent 历史总下载量（GB），用于首次启动时校准累计数据 |        800         |
| QB_HIST_UL_GB | qBittorrent 历史总上传量（GB），用于首次启动时校准累计数据 |        150         |
|    QB_HOST    |               qBittorrent 主机地址（含端口）               | 192.168.1.100:8080 |
|  QB_USERNAME  |                   qBittorrent 登录用户名                   |      username      |
|  QB_PASSWORD  |                    qBittorrent 登录密码                    |      password      |
|    TR_HOST    |                   Transmission 主机地址                    |   192.168.1.100    |
|    TR_PORT    |                     Transmission 端口                      |        9091        |
|  TR_USERNAME  |                  Transmission 登录用户名                   |      username      |
|  TR_PASSWORD  |                   Transmission 登录密码                    |      password      |

**注**：若不使用某一下载器，可将对应 QB_HOST 或 TR_HOST 留空，或在 `config.json `中设置 enabled 为 false。

### Docker Run 示例

```bash
docker run -d \
  --name pt-torrent-hub \
  -p 5272:5000 \
  -e TZ=Asia/Shanghai \
  -e QB_HIST_DL_GB=800 \
  -e QB_HIST_UL_GB=150 \
  -e QB_HOST=192.168.1.100:8080 \
  -e QB_USERNAME=username \
  -e QB_PASSWORD=password \
  -e TR_HOST=192.168.1.100 \
  -e TR_PORT=9091 \
  -e TR_USERNAME=username \
  -e TR_PASSWORD=password \
  -v $(pwd)/config:/data \
  --restart always \
  sqing33/pt-torrent-hub
```

### Docker Compose 示例

```yaml
services:
  pt-torrent-hub:
    image: sqing33/pt-torrent-hub
    container_name: pt-torrent-hub
    ports:
      - "5272:5000"
    environment:
      - TZ=Asia/Shanghai
      - QB_HIST_DL_GB=800 # qBittorrent 历史总下载量（GB）
      - QB_HIST_UL_GB=150 # qBittorrent 历史总上传量（GB）
      - QB_HOST=192.168.1.100:8080
      - QB_USERNAME=username
      - QB_PASSWORD=password
      - TR_HOST=192.168.1.100
      - TR_PORT=9091
      - TR_USERNAME=username
      - TR_PASSWORD=password
    volumes:
      - ./config:/data # 持久化配置文件与数据库至当前目录的 config 文件夹
    restart: always
```

## 三、配置文件说明

### 1. 配置文件位置

配置文件为 `config.json`，位于挂载的 `/data` 目录下。首次启动时若文件不存在，程序会根据环境变量自动生成。

### 2. 配置项说明

```json
{
  "qbittorrent": {
    "enabled": true,
    "host": "192.168.1.100:8080",
    "username": "username",
    "password": "password"
  },
  "transmission": {
    "enabled": true,
    "host": "192.168.1.100",
    "port": 9091,
    "username": "username",
    "password": "password"
  },
  "site_link_rules": {
    "一站": {
      "base_url": "https://a.com/detail/"
    }
  },
  "site_alias_mapping": {
    "a": "一站"
  },
  "ui_settings": {
    "active_path_filters": [],
    "active_downloader_filters": []
  }
}
```

- **qbittorrent / transmission**：
  - `enabled`：手动设置 `true`/`false` 启用 / 禁用对应下载器，优先级高于环境变量。
  - 其他字段为下载器的连接信息（主机、端口、用户名密码等）。
- **site_link_rules**：当种子注释中仅包含种子 ID 时，用于拼接生成完整的站点详情页 URL（如 `base_url + 种子ID`）。
- **site_alias_mapping**：用于合并同一站点的不同标签名称（例如将 “site-a”“站点 A” 统一映射为 “一站”）。
- **ui_settings**：自动保存前端 “种子查询” 页面的筛选条件，无需手动修改。
