# PT Nexus - PT 种子聚合管理平台

**PT Nexus** 是一款支持 Docker 容器化部署、兼容多下载器与多数据库的 **PT 种子聚合管理平台**，可自动提取标准化种子参数、解析标题组件，智能纠错补充 MediaInfo/截图/简介等内容、适配不同站点发布规范，支持批量转种与自动推送下载器做种，还具备禁转检测、已存在种子智能匹配等机制，搭配本地文件检索、IYUU API 查漏种等辅助功能，大幅简化跨站点转种流程，显著提升 PT 转种与管理效率。

- Wiki：https://ptn-wiki.sqing33.dpdns.org
- Github：https://github.com/sqing33/PTNexus
- DockerHub：https://hub.docker.com/r/sqing33/pt-nexus

## 2026 年 1 月 1 日起规范转种功能限制

> 转种限制方案由多位站点管理人员共同制定，转种限制代码使用 Go 编写编译且暂不开源，其他功能均在 Python 代码里实现，感谢各位站点管理人员的支持与配合。
> 代码仅供学习参考使用，严禁用于商业用途。

1. **带有禁转标签一律不可转种。**
2. **带有限转一律标签不可转种，不会自动检测源站是否取消限转，续后续自行确认后重新获取种子消息。**
3. **带有分集一律标签不可转种，因为目前有几个站点不允许转分集，且大多数用户下载分集都是在源站下的，大部分源站点在完结后还会删除分集，断种率也高。**
4. **同一个 ip 网段下的下载器同时最多可以有 15 个在上传的种子，超过 15 个则不可转种。（添加超过 24 小时的种子不计算，做种人数大于 5 人不计算，盒子不受限制）**
5. **一站多种的批量转种不允许发布小于 1GB 的种子，一种多站的单个转种不受此限制。**

### 一、核心转种功能

1. 种源管控：仅允许从有自动种审/人工种审的站点转出种子，保障合规性；
2. 智能参数处理：自动解析种子标题（主标题、季集、年份等），统一不同站点参数格式，便于跨站转种；
3. 多站点适配：为每个目标站点单独适配发布格式，不支持的参数自动降级；
4. 自动推送做种：转种成功后自动下载种子并推送至下载器，qBittorrent 支持跳过校验；
5. 智能种子检测：识别目标站点已存在的种子并自动补种，检测到禁转标签则屏蔽转种；
6. 批量操作：支持批量获取、检查、转种种子，实时监控进度并记录详情。

### 二、错误参数修正相关功能

1. 自动纠错：修正标题错误、简介错误、截图丢失等问题，解决参数位置错乱（如色深 10bit 与 HDR 参数）；
2. 内容增强：自动补充缺失的 MediaInfo、截图、简介，获取豆瓣海报并转存图床；
3. 参数识别优化：修正音频编码（如 TrueHD 7.1 Atmos）、格式标签（如 UHD BluRay Remux）等识别错误；
4. 质量校验：转种前检测参数错误/缺失，提供修正建议，确保符合目标站点规范。

### Docker 部署

#### 环境变量

| 分类       | 参数              | 说明                                            | 示例                      |
| ---------- | ----------------- | ----------------------------------------------- | ------------------------- |
| **通用**   | TZ                | 设置容器时区，确保时间与日志准确。              | Asia/Shanghai             |
|            | http_proxy        | 设置容器代理，确保能正常访问站点与各种服务。    | http://192.168.1.100:7890 |
|            | https_proxy       | 设置容器代理，确保能正常访问站点与各种服务。    | http://192.168.1.100:7890 |
|            | UPDATE_SOURCE     | 选择更新源，github 或 gitee，不设置默认 gitee。 | gitee                     |
| **数据库** | DB_TYPE           | 选择数据库类型。sqlite、mysql 或 postgres。     | sqlite                    |
|            | MYSQL_HOST        | **(MySQL 专用)** 数据库主机地址。               | 192.168.1.100             |
|            | MYSQL_PORT        | **(MySQL 专用)** 数据库端口。                   | 3306                      |
|            | MYSQL_DATABASE    | **(MySQL 专用)** 数据库名称。                   | pt-nexus                  |
|            | MYSQL_USER        | **(MySQL 专用)** 数据库用户名。                 | root                      |
|            | MYSQL_PASSWORD    | **(MySQL 专用)** 数据库密码。                   | your_password             |
|            | POSTGRES_HOST     | **(PostgreSQL 专用)** 数据库主机地址。          | 192.168.1.100             |
|            | POSTGRES_PORT     | **(PostgreSQL 专用)** 数据库端口。              | 5432                      |
|            | POSTGRES_DATABASE | **(PostgreSQL 专用)** 数据库名称。              | pt-nexus                  |
|            | POSTGRES_USER     | **(PostgreSQL 专用)** 数据库用户名。            | root                      |
|            | POSTGRES_PASSWORD | **(PostgreSQL 专用)** 数据库密码。              | your_password             |

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
      # - http_proxy=http://192.168.1.100:7890 # 代理服务器
      # - https_proxy=http://192.168.1.100:7890 # 代理服务器
      - UPDATE_SOURCE=gitee # 更新源，可选: gitee 或 github，不设置默认gitee
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
      # - http_proxy=http://192.168.1.100:7890 # 代理服务器
      # - https_proxy=http://192.168.1.100:7890 # 代理服务器
      - UPDATE_SOURCE=gitee # 更新源，可选: gitee 或 github，不设置默认gitee
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
      # - http_proxy=http://192.168.1.100:7890 # 代理服务器
      # - https_proxy=http://192.168.1.100:7890 # 代理服务器
      - UPDATE_SOURCE=gitee # 更新源，可选: gitee 或 github，不设置默认gitee
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

# 更新

> 通过 Docker 部署的 PT Nexus 支持更新功能，您可以在不重新下载镜像的情况下，直接从 GitHub 与 Gitee 拉取最新代码并应用更新。

![更新](https://img1.pixhost.to/images/10201/661470654_79517501-6fc3-4d37-9f44-440ef15b7ac7.png)

# 更新日志

### v3.5.3（2026.01.11）

> **注：盒子端新增自动选择中文字幕流功能需要重新执行 curl -sL https://github.com/sqing33/PTNexus/releases/download/latest/install-pt-nexus-box-proxy.sh | sudo bash 以更新盒子端脚本。**

- 新增：禁转规则-空官组禁转至 ub
- 新增：自动选择中文字幕流，盒子端需要一同更新

### v3.5.2（2026.01.11）

- 修复：标题出现“剩余时间”等文字无法正确清除
- 修复：一站多种页面各种获取功能报错“缺少必要参数:seed_id或save_path”
- 新增：简介字段有效性校验

### v3.5.1（2026.01.10）

- 修复：猫站作为源站无法在获取种子过程中进行截图、获取 mediainfo 与获取制作组

### v3.5.0（2026.01.10）

- 新增：ptgen-tmdb，解决部分影片豆瓣词条被删除而无法获取简介内容的问题（ptgen-tmdb 代码来自于星陨阁，迁移为 python 版本）
- 优化：盒子与本地同时做种的时候获取种子信息与添加下载器的逻辑
- 优化：标题音频编码选择逻辑

### v3.4.8（2026.01.09）

- 修复：剪辑版本部分参数拼接错误

### v3.4.7（2026.01.08）

> **注：修改 Github 仓库地址为 'https://github.com/sqing33/PTNexus'，因为 'pt-nexus' 缺失横杠无法搜索到，以至于有人在安装的时候安装到了 'nexusphp'。
结算画面： 'https://img1.pixhost.to/images/11481/682419724_4ba3b6c6-d528-471d-b898-c05c88ea4332.png' 
新的盒子端安装地址为 curl -sL https://github.com/sqing33/PTNexus/releases/download/latest/install-pt-nexus-box-proxy.sh | sudo bash**

- 修改：从 mediainfo 与 bdinfo 获取音频编码的选择
- 修改：Github 仓库地址为 'https://github.com/sqing33/PTNexus'

### v3.4.6（2026.01.05）

- 新增：添加种子到下载器设置默认的标签与分类
- 修复：做种检索页面路径下拉框出现已删除的路径

### v3.4.5（2026.01.03）

- 修复：部分正确的 mediainfo 和 bdinfo 无法通过格式校验

### v3.4.4（2026.01.02）

- 修复：13City 的 音频编码 DD/AC3 错误映射到 DDP/EAC3

### v3.4.3（2026.01.02）

> **注：使用 mediainfo 提取音频编码参数后发现之前格式化的 Atmos 位置错误，如果是之前版本获取的种子需要重新获取种子信息以修正音频编码参数位置。**

- 修复：longpt 发种部分音频编码丢失或错误
- 新增：mediainfo 过滤 bbcode 与 ★. 等无效字段

### v3.4.2（2026.01.02）

- 修复：蟹黄堡的 h264、h265 映射错误

### v3.4.1（2026.01.02）

- 修复：一站多种里获取的种子记录无法随着种子位置移动而改变

### v3.4.0（2025.12.31）

> **2025年最后一次更新，拜拜了您嘞！**

- 新增：转种目标站点-猫站、包子
- 新增：从 mediainfo 提取音频编码参数与 HDR 参数
- 修改：禁止转发分集

### v3.3.5（2025.12.26）

- 修复：选择 HDR10+ 标签报错或者无法提取到 HDR10+ 标签

### v3.3.4（2025.12.25）

> **注：修复盒子端获取原盘的截图有概率会报错失败的问题需要重新执行 curl -sL https://github.com/sqing33/PTNexus/releases/download/latest/install-pt-nexus-box-proxy.sh | sudo bash 以更新盒子端脚本。**

- 新增：转种目标站点-劳改所
- 修复：部分站点丢失 HDR 标签
- 修复：当文件标题有[ ]括号时批量获取种子无法生成截图
- 修复：不可说作为源站点时部分素材声明内容丢失
- 修复：盒子端获取原盘的截图有概率会报错失败

### v3.3.3（2025.12.17）

- 修改：longpt龙宝发种有问题，暂时屏蔽（有空修）

### v3.3.2（2025.12.17）

> **注：优化在线升级脚本，需更新 docker 镜像，且删除 data 目录下的 updates 文件夹，防止后续更新失败，请尽快更新。**

- 修复：主标题里的色深 10bit 与 hdr 参数位置错误，音频参数提取错误，青蛙标题多余 10bit 错误
- 优化：在线升级脚本（需更新 docker 镜像，且删除 data 目录下的 updates 文件夹。）

### v3.3.1（2025.12.16）

- 修复：UHD BluRay Remux无法识别为Remux、TrueHD 7.1 Atmos无法识别为TrueHD Atmos的问题

### v3.3.0（2025.12.15）

> **注:若报错“ModuleNotFoundError: No module named 'PIL'”则需要重新下载镜像进行更新，如仍然报错则删除 data 目录下的 updates 文件夹。
13City限速12.5MB/s，代码不会修改非0的限速，需要手动修改。
盒子获取 bdinfo 需要重新执行 curl -sL https://github.com/sqing33/PTNexus/releases/download/latest/install-pt-nexus-box-proxy.sh | sudo bash 以更新盒子端脚本。**

- 修复：“ModuleNotFoundError: No module named 'PIL'”报错
- 修复：青蛙、三月传媒主标题出现重复制作组的问题
- 新增：bdinfo 提取（盒子需更新脚本）
- 新增：bdinfo 提取队列与历史记录（在一站多种的日志里）

### v3.2.5（2025.12.11）

- 修复：藏宝阁标题丢失的问题

### v3.2.4（2025.12.11）

> **注：盒子优化截图速度需要重新执行 curl -sL https://github.com/sqing33/PTNexus/releases/download/latest/install-pt-nexus-box-proxy.sh | sudo bash 以更新盒子端脚本。**

- 优化：截图速度，截图名称用时间点命名
- 新增：转种目标站点-PTSkit

### v3.2.3（2025.12.11）

> **注：（需要更新 docker 镜像）新增环境变量 UPDATE_SOURCE，可选值 github 或 gitee，默认为 gitee，用于选择更新的源。
盒子截图 png 需要重新执行 curl -sL https://github.com/sqing33/PTNexus/releases/download/latest/install-pt-nexus-box-proxy.sh | sudo bash 以更新盒子端脚本。**

- 修复：数据库迁移错误
- 修复：标题参数 DTS 无法正确识别
- 修复：杜比、朱雀发种报错
- 修改：截图图片使用 png 格式上传
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

- 修改：使用 gitee 与 github 仓库共同进行更新

### v3.1.1（2025.11.16）

- 修复：一种多站点击转种按钮没有反应的问题

### v3.1.0（2025.11.16）

- 新增：在线更新功能
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
