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

### 5. 登录认证（JWT，默认启用）

- 后端默认启用登录认证，未登录访问任意 `/api/*` 将返回 401。
- 提供 `/api/auth/login` 登录接口，返回 Bearer Token，前端自动注入并维持会话。

## 三、Docker 部署

### 环境变量

新版本完全通过环境变量进行配置，无需手动修改配置文件。

| 分类       | 参数                 | 说明                                | 示例            |
| :--------- | :------------------- | :---------------------------------- | :-------------- |
| **通用**   | `TZ`                 | 设置容器时区，确保时间与日志准确。  | `Asia/Shanghai` |
| **认证**   | `JWT_SECRET`         | JWT 签名密钥（强烈建议设置）。      | `随机强密码`    |
|            | `AUTH_USERNAME`      | 登录用户名（默认 admin）。          | `admin`         |
|            | `AUTH_PASSWORD`      | 登录密码（明文，测试用）。          | `your_password` |
|            | `AUTH_PASSWORD_HASH` | 登录密码的 Bcrypt 哈希（优先）。    | `$2b$...`       |
| **数据库** | `DB_TYPE`            | 选择数据库类型。`sqlite`或`mysql`。 | `sqlite`        |
|            | `MYSQL_HOST`         | **(MySQL 专用)** 数据库主机地址。   | `192.168.1.100` |
|            | `MYSQL_PORT`         | **(MySQL 专用)** 数据库端口。       | `3306`          |
|            | `MYSQL_DATABASE`     | **(MySQL 专用)** 数据库名称。       | `pt_nexus`      |
|            | `MYSQL_USER`         | **(MySQL 专用)** 数据库用户名。     | `root`          |
|            | `MYSQL_PASSWORD`     | **(MySQL 专用)** 数据库密码。       | `your_password` |

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
          - JWT_SECRET=please-change-me
          - AUTH_USERNAME=admin
          - AUTH_PASSWORD=your_password
    ```

2.  在与 `docker-compose.yml` 相同的目录下，运行以下命令启动服务：
    ```bash
    docker-compose up -d
    ```
3.  服务启动后，通过 `http://<你的服务器IP>:5272` 访问 PT Nexus 界面。
4.  进入设置页面，添加下载器，如添加后数据未更新则点击右上角`刷新`按钮。

## 五、认证使用说明（默认开启）

1. 建议设置环境变量 `JWT_SECRET`。
2. 首次登录默认用户名为 `AUTH_USERNAME`（默认 `admin`）。
3. 可二选一设置密码：
   - `AUTH_PASSWORD`：明文密码（便捷但不安全，建议仅测试用）。
   - `AUTH_PASSWORD_HASH`：Bcrypt 哈希，优先于明文。
4. 前端会在本地存储 `token` 并自动注入到后续请求的 `Authorization: Bearer <token>` 头。
5. 退出可清除浏览器本地存储中的 `token`。

## 四、更新日志

### v1.2.1（2025-8-25）

- 适配了更多站点的种子查询
- 修复种子页面总上传量始终为 0 的问题
- 修复站点信息页面 UI 问题

### v1.2（2025-8-25）

- 适配了更多站点的种子查询
- 修改种子查询页面为站点名称首字母排序
- 修改站点筛选和路径筛选的 UI
- 新增下载器实时速率开关，关闭则 1 分钟更新一次上传下载量（开启为每秒一次）
- 新增下载器图表上传下载显示切换开关，可单独查看上传数据或下载数据
- 修复速率图表图例数值显示不完全的问题
- 修复站点信息页面表格在窗口变窄的情况下数据展示不完全的问题

### v1.1.1（2025-8-23）

- 适配 mysql

### v1.1（2025-8-23）

- 新增设置页面，实现多下载器支持。

### v1.0（2025-8-19）

- 完成下载统计、种子查询、站点信息查询功能。
