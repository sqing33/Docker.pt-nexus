# <img width="55" height="50" alt="image" src="https://minio.916337.xyz/icons/icons/8cfd5342-2085-4bba-9b9a-dc163f4676ff_b13c7358-4d9a-4990-a423-c1983c5491f3-favicon.ico" /> PT Nexus

## 一、项目概述

**PT Nexus** 是一款 PT 种子聚合查看平台，分析来自 **qBittorrent** 与 **Transmission** 下载器的种子数据与流量信息。

## 二、功能特性

### 1. 流量统计与分析

- **实时与历史速度监控**：记录下载器的实时上/下行速度，并支持查看历史速度曲线图。
- **多维度流量图表**：通过图表展示多种时间范围的流量数据变化。

### 2. 聚合种子管理

- **跨客户端种子聚合**：将来自 qBittorrent 和 Transmission 的所有种子聚合到统一视图中，方便查看每个种子在已有站点的做种信息，进行统一的筛选、排序和查询。
- **详情页一键跳转**：自动提取种子注释中的 URL 或 ID，并结合预设的站点规则，生成可直接点击的种子详情页链接。

### 3. 站点与发布组统计

- **站点做种统计**：自动统计每个 PT 站点的做种数量和总体积。
- **发布组做种统计**：根据种子名称自动识别所属的发布组（官组或压制组），并对各组的做种数量和体积进行统计。

### 4. 现代化技术栈

- **数据库支持**：支持 **SQLite**（默认，零配置）和 **MySQL** 两种数据库后端。
- **全功能 API**：前后端分离架构，所有数据均通过 API 交互，方便二次开发或集成。
- **容器化部署**：提供开箱即用的 Docker Compose 配置，实现简单快速的部署与管理。

## 三、Docker 部署

### 环境变量

新版本完全通过环境变量进行配置，无需手动修改配置文件。

| 分类             | 参数             | 说明                                                          | 示例                        |
| :--------------- | :--------------- | :------------------------------------------------------------ | :-------------------------- |
| **通用**         | `TZ`             | 设置容器时区，确保时间与日志准确。                            | `Asia/Shanghai`             |
| **数据库**       | `DB_TYPE`        | 选择数据库类型。`sqlite` (默认) 或 `mysql`。                  | `mysql`                     |
|                  | `MYSQL_HOST`     | **(MySQL 专用)** 数据库主机地址。                             | `192.168.1.100`             |
|                  | `MYSQL_PORT`     | **(MySQL 专用)** 数据库端口。                                 | `3306`                      |
|                  | `MYSQL_DATABASE` | **(MySQL 专用)** 数据库名称。                                 | `pt_nexus`                  |
|                  | `MYSQL_USER`     | **(MySQL 专用)** 数据库用户名。                               | `root`                      |
|                  | `MYSQL_PASSWORD` | **(MySQL 专用)** 数据库密码。                                 | `your_password`             |
| **qBittorrent**  | `QB_ENABLED`     | 是否启用 qBittorrent。`true` 或 `false`。                     | `true`                      |
|                  | `QB_HOST`        | qBittorrent 的 WebUI 地址，必须包含 `http://` 或 `https://`。 | `http://192.168.1.100:8080` |
|                  | `QB_USERNAME`    | qBittorrent 登录用户名。                                      | `admin`                     |
|                  | `QB_PASSWORD`    | qBittorrent 登录密码。                                        | `adminadmin`                |
| **Transmission** | `TR_ENABLED`     | 是否启用 Transmission。`true` 或 `false`。                    | `true`                      |
|                  | `TR_HOST`        | Transmission 主机地址。                                       | `192.168.1.100`             |
|                  | `TR_PORT`        | Transmission RPC 端口。                                       | `9091`                      |
|                  | `TR_USERNAME`    | Transmission 登录用户名。                                     | `transmission`              |
|                  | `TR_PASSWORD`    | Transmission 登录密码。                                       | `your_password`             |

### Docker Compose 示例

建议使用 Docker Compose 进行部署，这是最简单且最可靠的方式。

1.  创建一个 `docker-compose.yml` 文件：

    ```yaml
    services:
      pt-nexus:
        image: ghcr.io/sqing33/pt-nexus # sqing33/pt-nexus
        container_name: pt-nexus
        ports:
          - "5272:5272"
        volumes:
          - ./data:/app/data
        environment:
          - TZ=Asia/Shanghai
          # --- 数据库配置 (使用 MySQL) ---
          - DB_TYPE=mysql
          - MYSQL_HOST=192.168.1.100
          - MYSQL_PORT=3306
          - MYSQL_DATABASE=pt_nexus
          - MYSQL_USER=root
          - MYSQL_PASSWORD=
          # --- qBittorrent 配置 ---
          - QB_ENABLED=true
          - QB_HOST=http://192.168.1.100:8080
          - QB_USERNAME=
          - QB_PASSWORD=
          # --- Transmission 配置 ---
          - TR_ENABLED=true
          - TR_HOST=192.168.1.100
          - TR_PORT=9091
          - TR_USERNAME=
          - TR_PASSWORD=
        restart: always
    ```

2.  在与 `docker-compose.yml` 相同的目录下，运行以下命令启动服务：
    ```bash
    docker-compose up -d
    ```
3.  服务启动后，通过 `http://<你的服务器IP>:5272` 访问 PT Nexus 界面。
