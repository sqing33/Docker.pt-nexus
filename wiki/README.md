# Docsify 文档站点

这是一个基于 [Docsify](https://docsify.js.org/) 的文档站点，能够自动从 Markdown 文件生成文档网站。

## 项目结构

```
.
├── index.html              # Docsify 主配置文件
├── _sidebar.md             # 侧边栏导航
├── docs/                   # 文档文件
│   ├── index.md            # 首页
│   ├── installation.md     # 安装指南
│   └── guide/              # 指南文档
│       └── getting-started.md  # 入门教程
├── _media/                 # 媒体文件
│   └── icon.svg            # 站点图标
└── vercel.json             # Vercel 部署配置
```

## 快速开始

### 本地开发

1. 克隆此仓库
2. 使用任意静态文件服务器在本地提供服务：
   ```bash
   # 使用 Python
   python -m http.server 3000
   
   # 使用 Node.js http-server
   npx http-server
   
   # 使用 Node.js serve
   npx serve
   ```
3. 在浏览器中打开 http://localhost:3000

### 添加新文档

1. 在 `docs/` 目录中创建新的 Markdown 文件
2. 在 `_sidebar.md` 中添加这些文件的链接以使其可导航
3. 如果想在首页展示新文档，请更新 `docs/index.md`

### 配置说明

站点通过 `index.html` 进行配置：
- `homepage`: 设置默认加载页面
- `loadSidebar`: 启用侧边栏导航
- `subMaxLevel: 0`: 防止在侧边栏中自动生成子标题
- `alias`: 将缺失的侧边栏文件映射到根侧边栏

### 部署

此站点配置为在 Vercel 上部署。`vercel.json` 文件包含路由配置。

## 自定义

- 修改 `index.html` 以更改站点配置、插件或样式
- 更新 `_sidebar.md` 以修改导航结构
- 更改 `docs/index.md` 以更新首页内容
- 替换 `_media/icon.svg` 以更新站点图标

## 插件

此站点包含以下 Docsify 插件：
- 目录（右侧边栏）
- 字数统计
- 表情符号支持
- 图片缩放
- 代码复制按钮