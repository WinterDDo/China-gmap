# 设计定稿原型（千里江山）

可操作的高保真原型 + 完整设计规范，供定稿确认。中 / EN 切换会同时改变界面、规范和地图注记。

```bash
cd explorations/design-freeze && python3 -m http.server 8790   # http://127.0.0.1:8790/
```

`data/` 由 `design_prep.py` 从 `explorations/style-proposals` 的数据、`pipeline/reference/names.json`（中英地名）和 chinaciv 汇编的 2023 年统计公报数值生成。全国合计核对自国家统计局《2023年国民经济和社会发展统计公报》。
