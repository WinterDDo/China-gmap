---
name: add-data-source
description: "江山图鉴接入一个新数据源的固定做法：先问清口径和许可，再照现有数据源的结构写采集、处理、测试和说明，最后用数据铁律检查和抽查原文收尾。Use when adding any new dataset to the pipeline: 接入新数据、加一个数据源、采集某某数据（如 70 城房价、高校名单、产业区牌、工资、年鉴表格、新一年的公报）。NOT for: 修改现有数据源的解析错误（用 systematic-debugging），或只给设计原型用的临时数据（用 design-freeze）。"
---

# 加一个新数据源

照抄现有数据源的结构，不重新发明。整条管线是「下载（留档）→ 处理成中间文件 → 组装成网页数据 → 检查」，
每个数据源只管前两步。开工先说一句：「我在用 add-data-source 接入 <数据名>。」

## 第一步：动手前先问清（业务前提不猜）

下面任何一项拿不准，就停下来问用户，不要先做出来再说：

- **口径**：指标的官方定义和单位（如「城镇非私营单位就业人员年平均工资」还是「全部单位」）。
- **年份**：基准年 2025，序列 2020–2025。某年没有就是空，不拿别的年份补。
- **用在哪**：哪个画面、给谁看。用不上的数据不接。
- **许可**：对照 `docs/PRODUCT.md`「许可要点」。表里没有的新许可先写进那张表，并告诉用户；需要向数据方申请的，只起草信件，由用户本人发出。

## 第二步：选一个最像的样板来抄

| 新数据像… | 抄这个 | 要点 |
|---|---|---|
| 几个现成文件，原样取用 | `pipeline/sources/city_stats.py`（65 行，最短） | 固定版本，数字不改 |
| 官方年鉴表格（xls / htm） | `pipeline/sources/census_flows.py` | 表号、表名、网址逐张记下；拿表格自带的合计逐行核对 |
| 每城一篇文章，数字从正文里摘 | `pipeline/sources/tjcn_bulletins.py` + `pipeline/parse/records.py` | 每个数字带整句原文 |
| 只能在国内网络下载 | `tools/local_fetch/` + `pipeline/sources/local_bulletins.py` | 给用户一个脚本，交回压缩包；绝不让用户手抄数字 |

## 第三步：写数据源（`pipeline/sources/<id>.py`）

1. **模块开头的说明就是文档**：写清来源、表名和表号、年份、网址、输出长什么样、缺失怎么处理。照 `census_flows.py` 开头那段的写法。
2. 写一个 `Source` 子类，带 `info = SourceInfo(id, title, publisher, homepage, license, description, used_for)`。放进目录就自动登记，不用改别处。
3. **`fetch()`**：只用 `self.download(...)` 下载。它会缓存到 `data/raw/<id>/`，并在 manifest 里记下网址、sha256、大小和时间，「每个数字能追溯到具体文件」靠的就是它。不要直接发请求。`self.offline` 为真时，跳过「有没有新年份」之类的探测。批量抓网站时，每两次请求之间要有间隔（参考 `tjcn_bulletins.py` 的 `DELAY`）。
4. **`process()`**：返回一个字典，带上 `"vintage"`（版本，如「七普 2020」）和 `"_files"`（实际用到的原始文件，资料目录只引用这些）。
   - 缺失写 `None`，绝不写 0。表格里的空格（「无数字或数字很小」）也是 `None`。
   - 每个数字要能找回出处：文章类的带原句，表格类的带表号、行列名和文件。
   - 地名转代码一律用 `pipeline/parse/places.py` 的 `PlaceMatcher`，不手写对照表（「海南州」「吉林市」这类陷阱它已经处理过）。
   - 表格自带合计的，拿合计核对，结果写进输出（参考 `census_flows.py` 的 `check_matrix`）。
5. 网页要用，才写组装步骤（`pipeline/build/<名字>.py`，带 `REQUIRES`、`PRODUCES`、`build()`）。资料目录会自动收录新数据源。

## 第四步：规则和测试

- **数据铁律**：新数据的形状 `pipeline/check.py` 还不认识，就在里面加对应的检查。它和 `pipeline/parse/bulletin.py` 都是热点文件，动之前看一眼开工看板，别的会话在改就先把它并进来。机器能查的规则写成检查，不写成散文。
- **测试**（`tests/test_<id>.py`，不联网）：
  - 拿一份真实页面的精简副本放进 `tests/fixtures/`（像 `tjcn_shijiazhuang_2023_text.html`），或者在测试里造一张小表（像 `test_census_flows.py` 造的工作簿）。
  - 至少测三件事：正常值解析对、缺失得到 `None`、样本过得了 `pipeline/check.py` 的检查。
  - 每条新的检查规则配一个故意违反的例子（参考 `tests/test_data_rules.py`）。

## 第五步：验证（测试绿不等于做完）

1. 跑全部测试（提交时钩子也会自动跑）：

   ```bash
   python3 -m pytest -q
   ```

2. 真实下载和处理一次，再跑检查：

   ```bash
   python3 -m pipeline fetch <id> && python3 -m pipeline process <id> && python3 -m pipeline check
   ```

   连不上来源网站时，先分清原因：是云端环境的网络没放行（报错里有代理拒绝或解析不了域名，按环境文档请用户放行这个网站），还是只能在国内网络访问（走 `tools/local_fetch` 那套，交给用户跑）。不要拿别的来源顶上。

3. **抽查原文**：随机挑几条（至少 5 条，覆盖不同省份和年份），打开原始文件逐个核对数字。向用户汇报时说清抽了几条、怎么挑的、对上了几条。

## 第六步：收尾

- `docs/DATA-COLLECTION.md` 加一节：来源、年份覆盖、方法、已知缺口。
- 提交信息用英文，写清接了什么数据、覆盖多少。
- `STATUS.md`：新数据写进「还没验证」。用户亲自核对过一部分数字之前，它不进「确认能用」。
