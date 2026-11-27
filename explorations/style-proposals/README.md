# 视觉风格提案（第一轮）

同一份真实数据渲染的五种风格样张：千里江山、晕渲图志、万家灯火、方寸沙盘、一点一墨。
每种可切换“全国 / 长三角 / 透镜·人均GDP”。纯静态页面，Canvas 2D，无依赖。

本地查看：

```bash
cd explorations/style-proposals && python3 -m http.server 8790
```

然后打开 http://127.0.0.1:8790/

## 数据（`data/`）

由 `prep.py` 生成（需要 numpy、Pillow）：

| 文件 | 内容 | 来源 |
|---|---|---|
| `geo.json` | 省、地级区、国界（分陆地国界/海岸线）、南海断续线、邻国、河湖、沙漠，Albers 等积投影（km） | 阿里云 DataV.GeoAtlas（依据标准地图）；Natural Earth 1:10m（中国视角版） |
| `dem.png` / `dem.json` | 4 km 栅格高程，16 位编码在 R、G 通道（值 = 高程 + 11000 m） | AWS Terrain Tiles（terrarium，z6） |
| `cities.json` | 338 个地级以上城市 2023 年常住人口、GDP、三次产业 | 各地 2023 年统计公报；样张暂借开源项目 chinaciv 整理的数值，正式版将由本项目管线重新采集 |

样张仅用于风格讨论，未申请审图号。
