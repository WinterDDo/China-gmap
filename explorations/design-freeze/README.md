# 设计定稿原型（千里江山）

可操作的高保真原型 + 完整设计规范，供定稿确认。中 / EN 切换会同时改变界面、规范和地图注记。

```bash
cd explorations/design-freeze && python3 -m http.server 8790   # http://127.0.0.1:8790/
```

`data/` 由 `design_prep.py` 从 `explorations/style-proposals` 的数据、`pipeline/reference/names.json`（中英地名）和 chinaciv 汇编的 2023 年统计公报数值生成。全国合计核对自国家统计局《2023年国民经济和社会发展统计公报》。

`data/cityview.json`（城市视图：选中一座城时，地图上显示它的区县、宝藏点和建成区小屋顶，面板显示“这座城的人”“城里有什么”“下辖区县”）由 `build_cityview.py` 生成：区县名称和位置来自阿里云 DataV.GeoAtlas 行政区划（`infos.json`），宝藏点来自 chinaciv 汇编的公开名单（世界遗产、国家公园、5A 景区、双一流高校、民航机场 2025 年旅客量、主要港口、Global Energy Monitor 电厂与矿山）。英文名优先用官方英文名，没有的用拼音。

```bash
pip install pypinyin
python3 build_cityview.py <infos.json> <chinaciv/web/data> data
```

`data/transport.json`（城市视图里的铁路和高速：高铁、普铁、高速三种画法，面板「怎么出门」列出经过这座城的线路，点一下在地图上标红）由 `build_transport.py` 生成，输入是在你的 Mac 上用 `tools/local_fetch/fetch_osm_lines.py` 从 OpenStreetMap 下载的 `jiangshan_osm_lines.zip`（云端连不上 OpenStreetMap）。线路 © OpenStreetMap 贡献者，ODbL；只画线，不算里程。这个文件还没有时，面板显示「还在整理」，地图上不画线。中英地名的拼音规则在 `placenames.py`，两个生成脚本共用。

```bash
python3 build_transport.py <jiangshan_osm_lines.zip> data
```

「到家卡」（搜到家乡时：`川R，到家了。`，再点一下精确到县，地图上把这个县标出来）用两份数据：

- `data/plates.json`：每座城的车牌字头，由 `build_plates.py` 生成。维基数据和另一份读数一致的才收，缺的逐条查证并记下出处，查不到的留空（拉萨）。区号、邮编、身份证开头先不放，原因见 `docs/DECISIONS.md` 和 `TODOS.md`。
- `data/counties/<省码>.json`：各县轮廓，由 `build_counties.py` 从 DataV.GeoAtlas 生成，每省一个小文件，打开这个省的城市时才下载。

```bash
python3 build_plates.py <维基数据查询结果.json> data
python3 build_counties.py <缓存目录> data
python3 build_cityview.py <infos.json> <chinaciv/web/data> data   # 把车牌并进 cityview.json
```
