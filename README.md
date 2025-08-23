# <img width="52" height="50" alt="image" src="https://github.com/user-attachments/assets/d4c7835c-0de6-4d28-9b56-68fb473cfb2f" /> PT Nexus

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

| 分类       | 参数             | 说明                                | 示例            |
| :--------- | :--------------- | :---------------------------------- | :-------------- |
| **通用**   | `TZ`             | 设置容器时区，确保时间与日志准确。  | `Asia/Shanghai` |
| **数据库** | `DB_TYPE`        | 选择数据库类型。`sqlite`或`mysql`。 | `sqlite`        |
|            | `MYSQL_HOST`     | **(MySQL 专用)** 数据库主机地址。   | `192.168.1.100` |
|            | `MYSQL_PORT`     | **(MySQL 专用)** 数据库端口。       | `3306`          |
|            | `MYSQL_DATABASE` | **(MySQL 专用)** 数据库名称。       | `pt_nexus`      |
|            | `MYSQL_USER`     | **(MySQL 专用)** 数据库用户名。     | `root`          |
|            | `MYSQL_PASSWORD` | **(MySQL 专用)** 数据库密码。       | `your_password` |

### Docker Compose 示例

建议使用 Docker Compose 进行部署，这是最简单且最可靠的方式。

1.  创建一个 `docker-compose.yml` 文件：

    ```yaml
    services:
      pt-nexus:
        image: ghcr.io/sqing33/pt-nexus
        container_name: pt-nexus
        ports:
          - 5272:15272
        volumes:
          - .:/app/data
        environment:
          - TZ=Asia/Shanghai
          - DB_TYPE=sqlite
    ```

2.  在与 `docker-compose.yml` 相同的目录下，运行以下命令启动服务：
    ```bash
    docker-compose up -d
    ```
3.  服务启动后，通过 `http://<你的服务器IP>:5272` 访问 PT Nexus 界面。
4.  进入设置页面，添加下载器，如添加后数据未更新则点击右上角`刷新`按钮。

## 四、更新日志

### v1.1.1（2025-8-23）

- 适配 mysql

### v1.1（2025-8-23）

- 新增设置页面，实现多下载器支持。

### v1.0（2025-8-19）

- 完成下载统计、种子查询、站点信息查询功能。
