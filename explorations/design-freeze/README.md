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

家乡卡的几个面（用户 2026-11-28：不放通用统计，放值得自豪的东西，而且不止景点）：

- **位次**：页面里直接从 `cities.json` 算（生产总值过万亿；否则常住人口或生产总值省内前三）。只有在缺数的城市不可能改变名次时才说名次。
- **吃的**：`sources/feiyi_food.tsv`，国务院五批国家级非遗名录（传统技艺）里的饮食项目，逐条写着批次、项目编号和名录原文；第 5 批是从通知页面的名单图片读出来的。第二个来源是 `sources/gi_cn_eu.tsv`：中欧地理标志协定保护的中国地理标志产品，由 `build_gi.py` 从商务部逐个产品页面读出（每个都写着原产地），花卉和原产地跨几个市的不收。
- **景点古迹**：`build_pride.py` 从维基数据取世界遗产、5A 景区、全国重点文保，坐标（落在哪个县）和行政归属两边一致才收。

`build_pride.py` 把后两样写进 `data/pride.json`，`build_cityview.py` 再并进 `cityview.json`。

抽卡（用户 2026-11-28：每抽一张，三个亮点都要换，只换颜色不算）用的是更深的一层，第一次抽卡时才下载：

- **文化**：`sources/feiyi_all.tsv`，国务院五批国家级非遗名录的全部门类，由 `build_feiyi.py` 读出，按申报地区归到地级市。前四批读的是通知网页原文；第五批是 19 张表格图片，抄录在 `sources/feiyi_b5.tsv`（两位互不相见的读者各抄一遍，465 行逐字相同，另对图核过 35 行）。每批、每个部分读到的条数都和通知写的总数核对；申报地区只写到省或写的是部委的，不收。县后来改成区或市的（湟中县 → 湟中区）按今天的名字认，同省里只有一个同名的才认；名单还叫「地区」的认到今天的市；改了名字的（绍兴县 → 柯桥区）认不回来，不收。一个项目下列了几个子项（鼓舞（…、武山旋鼓舞））时，按子项和申报地区的先后位置对应，位置对不上才看名字；这条规则是一轮独立复查（2026-11-28，把带子项的 1254 行逐行看过）之后改的，之前按名字优先，把黄山区申报的太平猴魁标成了黄山毛峰。网页印得有疑问的行（镇江的灯彩）和印不出来的字（蚂𧊅节、㑇舞）不收。
- **更多景点古迹**：前三名之外、通过同样两项核对的全国重点文保和 5A 景区，名气大的在前，每座城最多凑到 12 处。这一层不设名气门槛（家乡卡自己的三条仍然设）。万人坑、侵华日军罪证、集中营、监狱、阵亡将士公墓这类遗址不收：抽卡是庆祝，它们该放进历史层。名字来自维基数据而不是国务院名单原文，所以 2026-11-28 请人把 2832 个名字全部读了一遍，要改的和要拿掉的写在 `build_pride.py` 的 FIX、DROP、DROP_IN 几张表里；标记（遗、5A、保）只在同名的两条记录之间合并，隔壁的地方不借标记。
- **全部吃的**：不再只取两样，最多 6 样。

`build_pride.py` 把这三样写进 `data/pride.json`（带出处）和 `data/pool.json`（只有名字，给页面用）。位次在页面里算。卫星估算出来的排名（森林、海拔）不进池子。亮点不到 4 个的城市（现在 14 座）不给「再抽」。

```
python3 build_feiyi.py <四份通知所在目录> data     # 写 sources/feiyi_all.tsv
python3 build_pride.py <维基数据查询结果目录> data   # 写 data/pride.json 和 data/pool.json
```

