# PT Nexus - PT 种子聚合管理平台

**PT Nexus** 是一款 PT 种子聚合管理平台，集 `下载器流量统计`、`铺种做种查询`、`多站点转种`、`本地做种文件检索` 于一体，大幅简化转种流程，提升 PT 站点管理效率。（经过一些站点的管理人员提议，批量发布应限制种子大小，所以批量转种部分代码使用 go 编写不开源，避免有人修改代码后批量转一些小种子倒垃圾到各各站点，目前限制为 1G，在一种多站功能中不做限制）

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

1. 创建 `docker-compose.yml` 文件

##### 使用 sqlite 数据库

```yaml
services:
  pt-nexus:
    image: ghcr.nju.edu.cn/sqing33/pt-nexus:latest
    container_name: pt-nexus
    ports:
      - 5274:5274
    volumes:
      - ./data:/app/data
      - /vol3/1000/pt:/pt # 视频文件存放路径
      # 如要使用转种上盒功能，tr需要种子文件存放路径，qb使用api无需设置
      # 设置页面第一个tr映射到/data/tr_torrents/tr1，第二个tr映射到/data/tr_torrents/tr2
      - /vol1/1000/Docker/transmission/torrents:/data/tr_torrents/tr1
      - /vol1/1000/Docker/transmission2/torrents:/data/tr_torrents/tr2
    environment:
      - TZ=Asia/Shanghai
      - http_proxy=http://192.168.1.100:7890 # 代理服务器
      - https_proxy=http://192.168.1.100:7890 # 代理服务器
      - DB_TYPE=sqlite
```

##### 使用 MySQL 数据库

```yaml
services:
  pt-nexus:
    image: ghcr.nju.edu.cn/sqing33/pt-nexus:latest
    container_name: pt-nexus
    ports:
      - 5274:5274
    volumes:
      - ./data:/app/data
      - /vol3/1000/pt:/pt # 视频文件存放路径
      # 如要使用转种上盒功能，tr需要种子文件存放路径，qb使用api无需设置
      # 设置页面第一个tr映射到/data/tr_torrents/tr1，第二个tr映射到/data/tr_torrents/tr2
      - /vol1/1000/Docker/transmission/torrents:/data/tr_torrents/tr1
      - /vol1/1000/Docker/transmission2/torrents:/data/tr_torrents/tr2
    environment:
      - TZ=Asia/Shanghai
      - http_proxy=http://192.168.1.100:7890 # 代理服务器
      - https_proxy=http://192.168.1.100:7890 # 代理服务器
      - DB_TYPE=mysql
      - MYSQL_HOST=192.168.1.100
      - MYSQL_PORT=3306
      - MYSQL_DATABASE=pt_nexus
      - MYSQL_USER=root
      - MYSQL_PASSWORD=your_password
```

##### 使用 PostgreSQL 数据库

```yaml
services:
  pt-nexus:
    image: ghcr.nju.edu.cn/sqing33/pt-nexus:latest
    container_name: pt-nexus
    ports:
      - 5274:5274
    volumes:
      - ./data:/app/data
      - /vol3/1000/pt:/pt # 视频文件存放路径
      # 如要使用转种上盒功能，tr需要种子文件存放路径，qb使用api无需设置
      # 设置页面第一个tr映射到/data/tr_torrents/tr1，第二个tr映射到/data/tr_torrents/tr2
      - /vol1/1000/Docker/transmission/torrents:/data/tr_torrents/tr1
      - /vol1/1000/Docker/transmission2/torrents:/data/tr_torrents/tr2
    environment:
      - TZ=Asia/Shanghai
      - http_proxy=http://192.168.1.100:7890 # 代理服务器
      - https_proxy=http://192.168.1.100:7890 # 代理服务器
      - DB_TYPE=postgresql
      - POSTGRES_HOST=192.168.1.100
      - POSTGRES_PORT=5433
      - POSTGRES_DATABASE=pt-nexus
      - POSTGRES_USER=root
      - POSTGRES_PASSWORD=your_password
```

2.  在与 `docker-compose.yml` 相同的目录下，运行以下命令启动服务：
    `docker-compose up -d`

3.  服务启动后，通过 `http://<你的服务器IP>:5274` 访问 PT Nexus 界面。

# 热更新

> 通过 Docker 部署的 PT Nexus 支持热更新功能，您可以在不重新下载镜像的情况下，直接从 GitHub 拉取最新代码并应用更新。

![热更新](https://img1.pixhost.to/images/10201/661470654_79517501-6fc3-4d37-9f44-440ef15b7ac7.png)

# 更新日志

### v3.2.3（2025.12.11）

> **注：新增环境变量 UPDATE_SOURCE，可选值 github 或 gitee，默认为 gitee，用于选择更新的源**

- 修复：数据库迁移错误
- 修复：标题参数 DTS 无法正确识别
- 修复：杜比、朱雀发种报错
- 优化：使用中转优化 pixhost 上传图片与 tmdb 链接获取
- 优化：种子数据获取与写入数据库的性能
- 优化：cf worker 新增备用 url 解决无法访问的问题
- 新增：当种子是原盘时修正标题为 Blu-ray

### v3.2.2（2025.12.01）

> **注：此功能目前在测试中，DTS-HD MA 可以正确获取映射，有无法映射或映射错误请及时反馈**

- 优化：优先使用标题解析的参数作为种子信息，源站点信息作为后备隐藏能源

### v3.2.1（2025.11.30）

- 修复：刷新下载器获取的种子数据出现异常长时间等待的问题
- 修复：主标题拼接时地区码出现['']包裹的问题

### v3.2.0（2025.11.30）

> **注：QB下载器使用api现成的方法推送种子到下载器，TR下载器需要映射本地种子目录
下载器设置里从左到右排序，在docker compose映射第一个tr到/data/tr_torrents/tr1，第二个映射到/data/tr_torrents/tr2
例：- /vol1/1000/Docker/transmission/torrents:/data/tr_torrents/tr1**

- 新增：暂停本地种子，然添加到盒子进行下载，用于多站转种。（一站多种-转种-上盒）

### v3.1.6（2025.11.29）

> **注：杜比发种需要获取 rsskey，在设置-站点管理填写
杜比作为源站点有时候会因为 2fa 的问题而获取失败，需要浏览器打开站点过一遍 2fa 再尝试（玄学）**

- 新增：转种目标站点-杜比
- 优化：通过 passkey 获取 HDtime 的种子推送到下载器

### v3.1.5（2025.11.27）

> **注：月月、彩虹岛、天空种子详情页没有禁转/限转的提示，目前使用的方案是使用搜索功能准确获取种子列表页面提取禁转/限转标签，每个种子会出现至少2次请求。
因为我堡的每小时请求次数有严格限制，目前仅可作为一种多站的源站点（获取信息后不影响批量转种）**

- 修复：ptgen 查询到错误影片，更换了 ptgen 后端
- 修复：憨憨、家园提取参数错误，补充映射参数
- 优化：一种多站在获取种子信息的时候出现错误的提示
（遇到问题找我请携带错误信息截图或者 Docker 日志截图）
- 新增：转种源站点-月月、彩虹岛、天空、我堡
- 新增：转种目标站点-朱雀

### v3.1.4（2025.11.19）

- 修复：解决 luckpt(幸运) 站点英语标签与国语标签冲突的问题

### v3.1.3（2025.11.17）

- 修复：织梦作为源站点提取纪录片类型出错的问题
- 新增：一站多种获取种子信息可以筛选有无源站点
- 新增：一种多站获取失败的时候自动重试2次
- 新增：一站多种获取种子的时候如果第一优先级站点获取错误则自动尝试后续站点

### v3.1.2（2025.11.17）

> **注：v3.1.2 之前的版本需要重新拉取镜像以应用 gitee 更新的功能**

- 修改：使用 gitee 与 github 仓库共同进行热更新

### v3.1.1（2025.11.16）

- 修复：一种多站点击转种按钮没有反应的问题

### v3.1.0（2025.11.16）

- 新增：在线热更新功能
- 新增：财神 PTGen API
- 新增：从副标题提取音轨、字幕，批量转种停止按钮

### v3.0.2（2025.11.14）

- 新增转种目标站点
- 修复：检索官种缺少一部分并且检索出很多孤种的问题
- 优化：所有海报全部重新获取并转存到 pixhost
- 修复：无法从 mediainfo 提取国语、粤语标签，无法获取制作组，标题 V2 无法识别为发布版本的问题
- 新增：自定义是否匿名上传
- 新增：一站多种种子状态筛选

### v3.0.1（2025.11.08）

- 新增转种目标站点
- 修复：无法自动创建 tmp 目录的问题
- 修复：获取种子信息时报错未授权而卡在获取种子页面的问题
- 修复：盒子端脚本报错字体依赖不存在的问题
- 优化：豆瓣海报获取方案并转存到 pixhost 图床
- 新增：从副标题提取特效标签

### v3.0.0（2025.11.01）

> **注：旧版本更新到 v3.0.0 版本因为数据库有很大变化，需要删除原来的数据库的所有表，然后代码会重新创建新的表，可以使用 docker run -p 8080:8080 adminer 进行修改。**

- 新增转种源站点，转种目标站点
- 重构：整个转种流程更改为源站点-标准参数-目标站点三层架构，提高转种准确性
- 重构：使用数据库存储每个转过的种子参数，避免再次转种的时候重复获取
- 新增：批量发种，可以设置源站点优先级，批量获取种子详情，检查正确后可批量发种
- 新增：禁转标签检查，不可说往 ub 转种的禁转检查
- 新增：PostgreSQL 支持
- 新增：自定义背景设置
- 新增：盒子端代理用于获取盒子上视频的信息录截图和 mediainfo 等信息，具体用法查看安装教程
- 新增：本地文件与下载器文件对比，检索未做种文件

### v2.2 转种测试版（2025.09.07）

- 新增转种目标站点
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

- 新增转种源站点
- 修复：种子筛选页面 UI 问题
- 修复：先打开转种页面，再到种子页面转种时无法获取种子信息的问题
- 修复：cookiecloud 无法保存配置的问题
- 修复：同时上传下载时，速率图表查看仅上传的显示问题
- 新增：发种自动添加种子到 qb 跳过校验
- 新增：种子页面排序和筛选参数保存到配置文件
- 新增：转种添加源站选择
- 修改：转种页面添加支持站点提示与参数提示

### v2.0 转种测试版（2025.09.01）

- 新增：转种功能 demo，支持转种至财神、星陨阁、幸运
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
