## 更新目标
1. 将配置文件中的键映射名称与HTML表单中显示的名称保持一致，后面的"category.movie"要与global_mappings.yaml已有的对应，如果global_mappings.yaml没有则添加缺失的映射到global_mappings.yaml中
2. 删除standard_keys中有但是html没有的多余的映射，例如现在的html有"1080p/1080i": "resolution.r1080p"
      "1080p": "resolution.r1080p"
      "1080i": "resolution.r1080p"
      但是html里是"1080p/1080i": "resolution.r1080p"则"1080p/1080i": "resolution.r1080p"，要求键名与html中显示的完全一致
3. 确保映射数值与HTML表单中的value属性完全对应
4. 优化title_components，保留特殊项，移除与默认配置global_mappings里default_title_components的相同的重复项
5. 保持global_mappings.yaml原有内容的完整性，只添加缺失的映射
6. 8k、4k、2k等分辨率的映射为r8640p、r4320p、r2160p等

### 第一步：分析HTML表单结构
从HTML表单中提取以下信息：
- **类型选项**：提取所有option的text和value
- **媒介选项**：提取所有option的text和value
- **编码选项**：提取所有option的text和value
- **音频编码选项**：提取所有option的text和value
- **分辨率选项**：提取所有option的text和value
- **制作组选项**：提取所有option的text和value
- **标签选项**：提取所有checkbox的label和value

### 第二步：更新站点配置文件

#### 2.1 更新standard_keys中的映射名称
```yaml
standard_keys:
# 将键名改为HTML中显示的格式，使用HTML中显示的确切格式
  type:
    
    "电影/Movies": "category.movie"
    "连续剧/TV Series": "category.tv_series"
    # ... 其他类型

  medium:
    "Track": "medium.track"
    "CD": "medium.cd"
    # ... 其他媒介
  
  video_codec:
    "AVC/H.264/x264": "video.h264"
    "HEVC/H.265/x265": "video.h265"
    # ... 其他编码
  
  audio_codec:
    "FLAC": "audio.flac"
    "mp3": "audio.mp3"  # 注意小写
    # ... 其他音频编码
  
  resolution:
    # 4k的要设置成r4320p
    "4K_UHD": "resolution.r4320p"
    "1080p/i": "resolution.r1080p"
    # ... 其他分辨率
  
  team:
    # 包含站点特有的制作组
    "13City": "team.city13"
    "AGSVPT": "team.agsvpt"
    # ... 其他制作组
````

#### 2.2 更新mappings中的数值映射

```yaml
mappings:
  type:
    # 确保value与HTML中的value属性对应
    "category.movie": "401"
    "category.tv_series": "402"
    # ... 其他类型映射
  
  medium:
    # 按HTML中的value正确映射
    "medium.bluray": "1"
    # ... 其他媒介映射
  
  # ... 其他字段的映射
```

#### 2.3 优化title_components

- 如果与default_title_components完全相同，则直接删除
- 如果有特殊字段，保留并添加注释说明，删除掉其他重复项

```yaml
title_components:
  # 站点使用默认的title_components配置，但额外包含特殊字段
  # ... 默认字段
  special_field:
    source_key: "特殊字段"  # 站点特有的字段
```

### 第三步：更新global_mappings.yaml

！同样标准键的要上下行相邻排列

#### 3.1 添加缺失的类型映射


```yaml
type:
  # 添加站点特有的类型映射
  "Movie(电影)": "category.movie"
  "连续剧/TV-Series": "category.tv_series"
  "Playlet（短剧）": "category.playlet"
  # ... 其他缺失的类型
```

#### 3.2 添加缺失的媒介映射

```yaml
medium:
  # 添加站点特有的媒介映射
  "Blu-rayUHD": "medium.uhd_bluray"
  "WEB": "medium.webdl"
  "DVDRip": "medium.dvdr"
  # ... 其他缺失的媒介
```

#### 3.3 添加缺失的分辨率映射

```yaml
resolution:
  # 添加站点特有的分辨率映射
  "4K_UHD": "resolution.r4k"
  "1080p/i": "resolution.r1080p"
  "720p/i": "resolution.r720p"
  "SD": "resolution.sd"
  # ... 其他缺失的分辨率
```

#### 3.4 添加缺失的制作组映射

```yaml
team:
  # 添加站点特有的制作组映射
  "AGSVPT": "team.agsvpt"
  "M-team": "team.mteam"
  "BeiTai": "team.beitai"
  # ... 其他缺失的制作组
```
