# 统计公报本地采集脚本（江山图鉴）

这个小工具帮你在**自己的电脑上**，自动从各地统计局、政府官网下载《国民经济和社会发展统计公报》，
最后打成一个压缩包交给项目使用。它只需要电脑上装有 Python，**不需要安装任何别的东西**。

> **最好在中国大陆的网络下运行。** 很多政府网站在境外打不开或很慢，必应（cn.bing.com）和百度的搜索结果也是
> 在大陆网络下最准。如果你正在用代理或 VPN，请先关掉再运行。

---

## 一、准备（只做一次）

1. **安装 Python 3.8 或更新的版本**
   - Windows：打开 <https://www.python.org/downloads/> 下载安装。安装第一页**一定要勾选
     “Add python.exe to PATH”**，然后点 “Install Now”。
   - macOS：同一网址下载 macOS 安装包，双击安装即可。
   - 检查是否装好：打开“命令提示符”（Windows：按 `Win` 键，输入 `cmd` 回车）或“终端”（macOS：在启动台搜索
     “终端”），输入下面一行后回车：

     ```
     python --version
     ```

     macOS 上如果提示找不到，改用 `python3 --version`。看到 `Python 3.x.x` 就说明装好了。
     （下面所有命令里的 `python`，在 macOS 上都换成 `python3`。）

2. **把整个 `local_fetch` 文件夹复制到电脑上**，比如放在桌面。文件夹里应该有：
   - `fetch_bulletins.py`（脚本）
   - `targets.json`（要下载的清单，项目已经生成好）
   - `README.md`（就是本说明）

3. **进入这个文件夹**：在命令提示符/终端里输入 `cd`、一个空格，再把 `local_fetch` 文件夹拖进窗口，回车。

---

## 二、先试一试

1. 只看会搜什么，不联网：

   ```
   python fetch_bulletins.py --dry-run --limit 5
   ```

   会打印出前 5 项要搜索的内容，例如 `"石家庄市2025年国民经济和社会发展统计公报"`。

2. 真正下载 5 项试试：

   ```
   python fetch_bulletins.py --limit 5
   ```

   屏幕上会显示进度，例如：

   ```
   [1/5] 2025 石家庄市（130100）
         找到：石家庄市2025年国民经济和社会发展统计公报  tjj.sjz.gov.cn
         → 完成
   ```

   结束后，同一文件夹里会出现 `out` 文件夹和一个 `jiangshan_bulletins_日期.zip` 压缩包。

---

## 三、全部下载

```
python fetch_bulletins.py
```

- 清单里约有一千项，每次请求之间会随机等 2–5 秒（这样对网站友好，也不容易被搜索引擎拦住）。
  很多公报正文里有十几张统计图，默认都会下载，**全部跑完可能要 8–12 个小时**，可以分几个晚上跑。
- 想快一些：加上 `--images needed`，只有当公报本身是图片（没有文字）时才下载图片，其余只记下图片网址，
  **大约 3–4 个小时**：`python fetch_bulletins.py --images needed`
- **随时可以中断**（按 `Ctrl + C`，或直接关窗口）。下次再运行同一条命令，会**自动跳过已经完成的**，接着往下做。
- 只想先做某一年：`python fetch_bulletins.py --years 2025`
- 只做几个城市：`python fetch_bulletins.py --codes 130100 440300`（代码可在 `targets.json` 里查到）
- 上次“未找到”或“出错”的再试一遍：`python fetch_bulletins.py --retry`
- 只用必应或只用百度：`--engine bing` 或 `--engine baidu`（默认先必应，找不到再用百度）

如果屏幕提示“要求验证（验证码）”，说明搜索引擎暂时拦住了自动搜索：停下来，过一两个小时再运行即可
（已完成的不会重做）。也可以先用浏览器正常打开一次 cn.bing.com 再试。

---

## 四、把结果交给项目

运行结束时会自动生成 **`jiangshan_bulletins_日期.zip`**（例如 `jiangshan_bulletins_20261201.zip`）。
把这个压缩包发给项目维护者即可（网盘、邮件附件都可以）。
如果中途停了又想先交一部分，可以只打包、不下载：

```
python fetch_bulletins.py --zip-only
```

---

## 五、它具体做了什么

对清单里的每一项（地区 + 年份）：

1. 在必应（必要时百度）搜索 `"某市2025年国民经济和社会发展统计公报"`；
2. 只接受**标题里同时有这个地区名和年份**的结果，并且优先选择：
   该地区以往发布公报的官网（清单里的 `hint_host`）＞ 其他 `gov.cn` 政府网站。
   默认**不接受非政府网站**（转载站、新闻站）；
3. 下载公报页面，以及页面里的附件（PDF、Word、Excel）和正文里的图片；
4. 把文件存进 `out/年份/地区代码/`，并写一个 `manifest.json`，记录每个文件的原网址、最终网址、
   下载时间、网站返回的状态码、文件的 sha256 校验值、页面标题、用的搜索词和搜索引擎。

找不到的项会标为“未找到”，不会乱下别的东西。

**安全说明**：下载下来的文件只作为数据保存，脚本**从不打开、运行或解压**它们，文件名也由脚本自己起
（`page.html`、`att_01.pdf`、`img_001.png` 等），不使用网站给的文件名。请不要双击运行 `out` 文件夹里的任何东西。

---

## 六、常见问题

- **提示 `python` 不是内部或外部命令**：Windows 安装时没勾选 “Add python.exe to PATH”。重新运行安装程序，
  选 “Modify”，勾上它；或者把命令里的 `python` 换成 `py`。
- **很多项“未找到”**：多半是网络问题（在境外、开着代理）或搜索引擎暂时拦截。换到大陆网络、隔一段时间后用
  `--retry` 再试。确实还没发布的公报（比如很偏远地区的最新一年）也会是“未找到”，这是正常的。
- **某个网站一直出错**：没关系，记录会保留在 `manifest.json` 里，项目这边会另行处理。
- **想看下载了什么**：打开 `out/年份/地区代码/` 文件夹即可；`out/summary.csv` 在压缩包里，用 Excel 能打开。

---

## 七、给项目维护者

- `targets.json` 由 `python3 tools/local_fetch/make_targets.py` 生成（需先运行
  `python -m pipeline fetch tjcn_bulletins` 和 `process tjcn_bulletins`）。
- 收到压缩包后放进 `data/raw/local_bulletins/`，运行
  `python -m pipeline fetch local_bulletins && python -m pipeline process local_bulletins`，
  结果会并入 `data/interim/bulletins/<年份>.json` 和 `coverage.csv`。详见 `docs/DATA-COLLECTION.md`。
