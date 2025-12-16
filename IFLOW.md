# PT Nexus - PT 种子聚合管理平台

## 项目概述

PT Nexus 是一款 PT 种子聚合管理平台，集 `下载器流量统计`、`铺种做种查询`、`多站点转种`、`本地做种文件检索`、`BDInfo提取`、`媒体截图`、`自动更新` 于一体，大幅简化转种流程，提升 PT 站点管理效率。

### 技术架构

- **后端**: Python Flask (主要服务)
- **前端**: Vue 3 + TypeScript + Element Plus
- **辅助服务**: Go 语言编写的批量处理、更新、代理服务
- **数据库**: 支持 SQLite、MySQL、PostgreSQL
- **部署**: Docker 容器化部署

### 项目结构

```
PT Nexus/
├── server/               # Python Flask 后端服务
│   ├── api/             # API 路由模块
│   ├── core/            # 核心业务逻辑
│   ├── models/          # 数据模型
│   ├── utils/           # 工具函数
│   ├── configs/         # 站点配置文件
│   └── core/bdinfo/     # BDInfo工具
├── webui/               # Vue 3 前端应用
│   ├── src/
│   │   ├── components/  # Vue 组件
│   │   ├── views/       # 页面视图
│   │   ├── router/      # 路由配置
│   │   └── stores/      # 状态管理
├── batch/               # Go 批量处理服务
├── updater/             # Go 更新服务
├── proxy/               # Go 代理服务
└── bdinfo/              # BDInfo 工具
```

## 构建和运行

### 开发环境

1. **后端开发**:
   ```bash
   cd server
   python -m venv .venv
   source .venv/bin/activate  # Linux/Mac
   pip install -r requirements.txt
   python app.py
   ```

2. **前端开发**:
   ```bash
   cd webui
   pnpm install
   pnpm dev
   ```

3. **Go 服务开发**:
   ```bash
   cd batch  # 或 updater/proxy
   go mod download
   go build -o batch batch.go  # 或对应服务
   ./batch  # 运行服务
   ```

### Docker 部署

1. **构建镜像**:
   ```bash
   docker build -t pt-nexus .
   ```

2. **使用 Docker Compose**:
   ```yaml
   services:
     pt-nexus:
       image: ghcr.nju.edu.cn/sqing33/pt-nexus:latest
       container_name: pt-nexus
       ports:
         - 5274:5274
       volumes:
         - ./data:/app/data
         - /path/to/torrents:/pt
       environment:
         - TZ=Asia/Shanghai
         - DB_TYPE=sqlite
         - UPDATE_SOURCE=gitee  # 或 github
         - ALLOWED_ORIGINS=http://localhost:3000,https://yourdomain.com
   ```

3. **启动服务**:
   ```bash
   docker-compose up -d
   ```

### 服务端口

- **主服务**: 5274 (Web UI + 更新服务)
- **Flask API**: 5275
- **批量处理服务**: 5276
- **Go代理服务**: 9090 (默认端口，可通过下载器配置中的proxy_port指定)

## 开发约定

### 代码规范

1. **Python 代码**:
   - 遵循 PEP 8 规范
   - 使用类型注解
   - 采用函数式编程思维
   - 数据库操作支持冲突处理（MySQL/PostgreSQL使用ON DUPLICATE KEY UPDATE，SQLite使用ON CONFLICT）

2. **Vue/TypeScript 代码**:
   - 使用 Composition API
   - 遵循 Vue 3 最佳实践
   - 使用 TypeScript 严格模式

3. **Go 代码**:
   - 遵循 Go 官方代码规范
   - 使用 gofmt 格式化代码
   - 简洁的错误处理

### 测试规范

- 后端测试使用 pytest
- 前端测试使用 Vitest
- API 测试覆盖所有端点

### 提交规范

- 使用语义化提交信息
- 功能开发使用 feature 分支
- 提交前运行 lint 和测试

## 核心功能

### 1. 下载器流量统计
- 支持 qBittorrent 和 Transmission
- 实时流量监控和历史数据
- 可视化图表展示
- 支持通过代理获取下载器信息（用于远程下载器访问）
- 支持基于IP:端口的下载器ID生成和管理
- 智能下载器ID迁移功能

### 2. 种子查询与管理
- 多站点种子信息聚合
- 本地做种文件检索
- 种子状态监控
- 支持增量同步策略，减少资源消耗
- 支持智能批量获取和筛选

### 3. 转种功能
- 源站点到目标站点的参数映射
- 批量转种处理
- 禁转/限转标签检查

### 4. 媒体处理
- **BDInfo提取**: 支持蓝光原盘BDInfo提取，带进度监控
- **媒体截图**: 智能截图功能，支持内嵌字幕识别，自动上传图床
- **MediaInfo提取**: 获取视频文件的详细媒体信息
- **文件检查**: 支持文件/目录存在性检查
- **剧集统计**: 自动统计TV系列的集数

### 5. 站点管理
- 支持 40+ PT 站点
- 站点配置文件化管理
- 代理支持
- CookieCloud同步功能

### 6. 系统管理
- **认证系统**: JWT Token + 内部API Key认证
- **用户管理**: 支持用户名密码认证
- **下载器配置**: 支持多个下载器配置
- **UI设置**: 个性化界面设置（页面大小、排序等）
- **自动更新**: 支持在线更新功能，支持Gitee/GitHub源自动切换

## 配置说明

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| TZ | 时区设置 | Asia/Shanghai |
| DB_TYPE | 数据库类型 | sqlite |
| http_proxy | HTTP 代理 | 无 |
| https_proxy | HTTPS 代理 | 无 |
| UPDATE_SOURCE | 更新源(github/gitee) | gitee |
| JWT_SECRET | JWT密钥 | 动态生成 |
| INTERNAL_SECRET | 内部认证密钥 | pt-nexus-2024-secret-key |
| ALLOWED_ORIGINS | 允许的跨域请求来源 | 无 |

### 数据库配置

根据 DB_TYPE 选择对应配置:
- **SQLite**: 无需额外配置
- **MySQL**: 需要 MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE, MYSQL_USER, MYSQL_PASSWORD
- **PostgreSQL**: 需要 POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DATABASE, POSTGRES_USER, POSTGRES_PASSWORD

## 更新机制

项目支持在线更新功能:
1. 通过 GitHub/Gitee 仓库获取最新代码
2. 自动应用更新并重启服务
3. 保留用户数据和配置
4. 支持自动切换更新源（Gitee/GitHub）以应对网络问题
5. 带有版本比较逻辑，只在远程版本大于本地版本时更新
6. 包含备份和回滚机制

## 故障排除

### 常见问题

1. **ModuleNotFoundError: No module named 'PIL'**
   - 解决方案: 重新下载 Docker 镜像

2. **数据库迁移错误**
   - 解决方案: 检查数据库配置和权限

3. **站点访问失败**
   - 解决方案: 检查代理设置和站点配置

4. **更新失败**
   - 解决方案: 检查网络连接，尝试切换UPDATE_SOURCE为github或gitee

5. **下载器连接失败**
   - 解决方案: 检查下载器配置，确认是否需要启用代理模式

### 日志查看

```bash
# Docker 容器日志
docker logs pt-nexus

# 实时日志
docker logs -f pt-nexus
```

### 服务端口说明

- 5274: 主服务端口，提供Web UI和更新服务
- 5275: Flask API 服务端口
- 5276: 批量处理增强服务端口
- 9090: Go代理服务端口（默认，可通过proxy_port配置）

## 贡献指南

1. Fork 项目
2. 创建功能分支
3. 提交更改
4. 创建 Pull Request

## 许可证

项目采用私有许可证，批量转种功能不开源以防止滥用。

---

更多信息请参考项目 Wiki: https://ptn-wiki.sqing33.dpdns.org