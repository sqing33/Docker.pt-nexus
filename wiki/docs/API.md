# 基于 Cloudflare 部署的服务 API

## 豆瓣资源信息获取的 pt-gen API

### 概述

本 API 用于通过豆瓣资源链接获取电影、电视剧等视频的详细信息。

- 原项目地址：https://github.com/Rhilip/pt-gen-cfworker
- 本项目部署 pt-gen 网页：https://ptn-ptgen.sqing33.dpdns.org

#### API 地址

`https://ptn-ptgen.sqing33.dpdns.org/`

#### 请求方法

GET

#### 请求参数

| 参数名 | 类型   | 是否必需 | 描述                       | 示例值                                     |
| ------ | ------ | -------- | -------------------------- | ------------------------------------------ |
| url    | string | 是       | 豆瓣影视资源页面的完整 URL | https://movie.douban.com/subject/36670979/ |

#### 完整的请求示例

```
GET https://ptn-ptgen.sqing33.dpdns.org/?url=https://movie.douban.com/subject/36670979/
```

#### 返回结果

返回结果为 JSON 格式，包含资源的基本信息、评分、演职员表和剧情简介等。

#### 成功返回示例（部分关键字段）：

```json
{
  "success": true,
  "error": "Miss key of `site` or `sid` , or input unsupported resource `url`.",
  "chinese_title": "青春猪头少年不会梦到圣诞服女郎",
  "foreign_title": "青春ブタ野郎はサンタクロースの夢を見ない",
  "year": " 2025",
  "genre": ["剧情", "爱情", "动画"],
  "language": ["日语"],
  "episodes": "13",
  "duration": "24分钟",
  "douban_rating_average": "8.2",
  "poster": "https://img9.doubanio.com/view/photo/l_ratio_poster/public/p2915641035.jpg",
  "director": [
    {
      "@type": "Person",
      "name": "增井壮一 Masui Souichi"
    }
  ],
  "cast": [
    // ... 演员信息 ...
  ],
  "introduction": "青春期综合征――\n传闻中由不稳定的精神状态引发的奇妙现象。\n..."
}
```

#### 关键返回字段说明

| 字段名                | 类型    | 描述                    |
| --------------------- | ------- | ----------------------- |
| success               | boolean | API 请求是否成功。      |
| chinese_title         | string  | 中文标题。              |
| foreign_title         | string  | 外文标题（原标题）。    |
| aka                   | array   | 别名/又名列表。         |
| playdate              | array   | 上映/开播日期。         |
| episodes              | string  | 集数（针对剧集/动画）。 |
| douban_rating_average | string  | 豆瓣平均评分。          |
| poster                | string  | 海报图片的 URL。        |
| director              | array   | 导演信息列表。          |
| cast                  | array   | 演员信息列表。          |
| introduction          | string  | 剧情简介。              |

## IMDB ID 与豆瓣 ID 互相查询的 API

### 概述

本 API 用于通过影视资源的`imdbid`、`doubanid`、名称（`name`）或年份（`year`）查询相关影视的基础信息（包括豆瓣 ID、IMDb ID、名称、年份等）。

- 原项目地址：https://github.com/ourbits/PtGen
- 本项目使用改存储库中的 IMDB ID 与豆瓣 ID 的映射表构建 Cloudflare D1 数据库，使用 Cloudflare Worker 进行查询转换。

#### API 地址

`https://ptn-douban.sqing33.dpdns.org/`

#### 请求方法

GET

#### 请求参数

| 参数名   | 类型          | 是否必需 | 描述                                    | 示例值                         |
| -------- | ------------- | -------- | --------------------------------------- | ------------------------------ |
| imdbid   | string        | 否       | IMDb 资源唯一标识（至少需提供一个参数） | tt33060122                     |
| doubanid | string/number | 否       | 豆瓣资源唯一标识（至少需提供一个参数）  | 36670979                       |
| name     | string        | 否       | 影视名称（至少需提供一个参数）          | 青春猪头少年不会梦到圣诞服女郎 |
| year     | string        | 否       | 影视上映/开播年份（可配合 name 使用）   | 2025                           |

> 说明：请求时只需提供上述参数中的一个或多个。

#### 完整请求示例

1. 通过`doubanid`查询：  
   `GET https://ptn-douban.sqing33.dpdns.org/?doubanid=36670979`

2. 通过`imdbid`查询：  
   `GET https://ptn-douban.sqing33.dpdns.org/?imdbid=tt33060122`

3. 通过`name`和`year`联合查询：  
   `GET https://ptn-douban.sqing33.dpdns.org/?name=青春猪头少年不会梦到圣诞服女郎&year=2025`

#### 返回结果

返回结果为 JSON 格式，包含查询到的影视资源信息或错误提示。

#### 成功返回示例

```json
{
  "data": [
    {
      "doubanid": 36670979,
      "imdbid": "tt33060122",
      "name": "青春猪头少年不会梦到圣诞服女郎",
      "year": "2025"
    }
  ]
}
```

#### 关键返回字段说明

| 字段名   | 类型   | 描述                                   |
| -------- | ------ | -------------------------------------- |
| data     | array  | 查询到的影视资源列表（单个或多个结果） |
| doubanid | number | 豆瓣资源唯一标识                       |
| imdbid   | string | IMDb 资源唯一标识                      |
| name     | string | 影视名称                               |
| year     | string | 影视上映/开播年份                      |
