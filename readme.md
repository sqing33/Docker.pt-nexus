# PT Nexus - PT 种子聚合管理平台

**PT Nexus** 是一款 PT 种子聚合管理平台，集 `下载器流量统计`、`铺种做种查询`、`多站点转种`、`本地做种文件检索` 于一体，大幅简化转种流程，提升 PT 站点管理效率。

- Wiki：https://ptn-wiki.sqing33.dpdns.org
- Github：https://github.com/sqing33/Docker.pt-nexus
- DockerHub：https://hub.docker.com/r/sqing33/pt-nexus

### Docker 部署

#### 环境变量

| 分类       | 参数              | 说明                                         | 示例                      |
| ---------- | ----------------- | -------------------------------------------- | ------------------------- |
| **通用**   | TZ                | 设置容器时区，确保时间与日志准确。           | Asia/Shanghai             |
|            | http_proxy        | 设置容器代理，确保能正常访问站点与各种服务。 | http://192.168.1.100:7890 |
|            | https_proxy       | 设置容器代理，确保能正常访问站点与各种服务。 | http://192.168.1.100:7890 |
| **数据库** | DB_TYPE           | 选择数据库类型。sqlite、mysql 或 postgres。  | sqlite                    |
|            | MYSQL_HOST        | **(MySQL 专用)** 数据库主机地址。            | 192.168.1.100             |
|            | MYSQL_PORT        | **(MySQL 专用)** 数据库端口。                | 3306                      |
|            | MYSQL_DATABASE    | **(MySQL 专用)** 数据库名称。                | pt-nexus                  |
|            | MYSQL_USER        | **(MySQL 专用)** 数据库用户名。              | root                      |
|            | MYSQL_PASSWORD    | **(MySQL 专用)** 数据库密码。                | your_password             |
|            | POSTGRES_HOST     | **(PostgreSQL 专用)** 数据库主机地址。       | 192.168.1.100             |
|            | POSTGRES_PORT     | **(PostgreSQL 专用)** 数据库端口。           | 5432                      |
|            | POSTGRES_DATABASE | **(PostgreSQL 专用)** 数据库名称。           | pt-nexus                  |
|            | POSTGRES_USER     | **(PostgreSQL 专用)** 数据库用户名。         | root                      |
|            | POSTGRES_PASSWORD | **(PostgreSQL 专用)** 数据库密码。           | your_password             |

#### Docker Compose 示例

> **注：** 旧版本更新到 v3.0.0 版本因为数据库有很大变化，需要删除原来的数据库的所有表，然后代码会重新创建新的表，可以使用`docker run -p 8080:8080 adminer`进行修改。

1.  创建 `docker-compose.yml` 文件

```yaml
# 使用 sqlite
services:
  pt-nexus:
    image: ghcr.io/sqing33/pt-nexus:latest
    container_name: pt-nexus
    ports:
      - 5274:5274
    volumes:
      - ./data:/app/data
      - /vol3/1000/pt:/pt # 与 qb 或者 tr 设置的文件下载目录一致
    environment:
      - TZ=Asia/Shanghai
      - http_proxy=http://192.168.1.100:7890
      - https_proxy=http://192.168.1.100:7890
      - DB_TYPE=sqlite
```

```yaml
# 使用 MySQL
services:
  pt-nexus:
    image: ghcr.io/sqing33/pt-nexus:latest
    container_name: pt-nexus
    ports:
      - 5274:5274
    volumes:
      - ./data:/app/data
      - /vol3/1000/pt:/pt # 与 qb 或者 tr 设置的文件下载目录一致
    environment:
      - TZ=Asia/Shanghai
      - http_proxy=http://192.168.1.100:7890
      - https_proxy=http://192.168.1.100:7890
      - DB_TYPE=mysql
      - MYSQL_HOST=192.168.1.100
      - MYSQL_PORT=3306
      - MYSQL_DATABASE=pt_nexus
      - MYSQL_USER=root
      - MYSQL_PASSWORD=your_password
```

```yaml
# 使用 PostgreSQL
services:
  pt-nexus:
    image: ghcr.io/sqing33/pt-nexus:latest
    container_name: pt-nexus
    ports:
      - 5274:5274
    volumes:
      - ./data:/app/data
      - /vol3/1000/pt:/pt # 与 qb 或者 tr 设置的文件下载目录一致
    environment:
      - TZ=Asia/Shanghai
      - http_proxy=http://192.168.1.100:7890
      - https_proxy=http://192.168.1.100:7890
      - DB_TYPE=postgre
      - POSTGRES_HOST=192.168.1.100
      - POSTGRES_PORT=5433
      - POSTGRES_DATABASE=pt-nexus
      - POSTGRES_USER=root
      - POSTGRES_PASSWORD=your_password
```

2.  在与 `docker-compose.yml` 相同的目录下，运行以下命令启动服务：
    `docker-compose up -d`

3.  服务启动后，通过 `http://<你的服务器IP>:5274` 访问 PT Nexus 界面。

# 更新日志

### v3.0.1（2025.11.08）

- 新增转种目标站点：longpt，天枢
- 修复：无法自动创建 tmp 目录的问题
- 修复：获取种子信息时报错未授权而卡在获取种子页面的问题
- 修复：盒子端脚本报错字体依赖不存在的问题
- 优化：豆瓣海报获取方案并转存到 pixhost 图床（参考油猴“豆瓣海报转存 pixhost”插件）
- 新增：从副标题提取“特效”标签

### v3.0.0（2025.11.01）

> **注：** 旧版本更新到 v3.0.0 版本因为数据库有很大变化，需要删除原来的数据库的所有表，然后代码会重新创建新的表，可以使用`docker run -p 8080:8080 adminer`进行修改。

- 转种源站点新增：
- 转种目标站点新增：
- 重构：整个转种流程更改为`源站点-标准参数-目标站点`三层架构，提高转种准确性
- 重构：使用数据库存储每个转过的种子参数，避免再次转种的时候重复获取
- 新增：批量发种，可以设置源站点优先级，批量获取种子详情，审查正确后可批量发种
- 新增：禁转标签检查，不可说往 ub 转种的禁转检查
- 新增：`PostgreSQL`支持
- 新增：自定义背景设置
- 新增：盒子端代理用于获取盒子上视频的信息录截图和 mediainfo 等信息，具体用法查看安装教程
- 新增：本地文件与下载器文件对比，检索未做种文件

### v2.2 转种测试版（2025.09.07）

- 转种目的站点新增 13City、垃圾堆、NovaHD
- 新增：weiui 登录认证
- 新增：做种信息页面站点筛选
- 新增：每个站点单独设置代理
- 新增：pixhost 图床设置代理
- 新增：转种完成后自动添加种子到下载器保种
- 新增：默认下载器设置，可选择源种子所在的下载器或者指定下载器
- 新增：种子信息中声明部分内容的过滤
- 新增：从 mediainfo 中提取信息映射标签
- 修复：4.6.x 版本 qb 无法提取种子详情页 url 的问题
- 重构：将转种功能从单独页面移动至种子查询页面内
- 新增：种子在站点已存在则直接下载种子推送至下载器做种
- 新增：前端首页显示下载器信息

### v2.1 转种测试版（2025.09.02）

- 转种源站点新增 Ubits、麒麟、自由农场、蟹黄堡、藏宝阁
- 修复：种子筛选页面 UI 问题
- 修复：先打开转种页面，再到种子页面转种时无法获取种子信息的问题
- 修复：cookiecloud 无法保存配置的问题
- 修复：同时上传下载时，速率图表查看仅上传的显示问题
- 新增：发种自动添加种子到 qb 跳过校验
- 新增：种子页面排序和筛选参数保存到配置文件
- 新增：转种添加源站选择
- 修改：转种页面添加支持站点提示与参数提示

### v2.0 转种测试版（2025.09.01）

- 新增：转种功能 demo，支持转种至 `财神`、`星陨阁`、`幸运`
- 新增：MediaInfo 自动判断与提取
- 新增：主标题提取与格式修改
- 新增：视频截图获取与上传图床
- 新增：转种功能多站点发布
- 新增：设置中的站点管理页面
- 重构：项目后端结构

### v1.2.1（2025.08.25）

- 适配更多站点的种子查询
- 修复：种子页面总上传量始终为 0 的问题
- 修复：站点信息页面 UI 问题

### v1.2（2025.08.25）

- 适配更多站点的种子查询
- 修改：种子查询页面为站点名称首字母排序
- 修改：站点筛选和路径筛选的 UI
- 新增：下载器实时速率开关，关闭则 1 分钟更新一次上传下载量（开启为每秒一次）
- 新增：下载器图表上传下载显示切换开关，可单独查看上传数据或下载数据
- 修复：速率图表图例数值显示不完全的问题
- 修复：站点信息页面表格在窗口变窄的情况下数据展示不完全的问题

### v1.1.1（2025.08.23）

- 适配：mysql

### v1.1（2025.08.23）

- 新增：设置页面，实现多下载器支持。

### v1.0（2025.08.19）

- 完成：下载统计、种子查询、站点信息查询功能。
