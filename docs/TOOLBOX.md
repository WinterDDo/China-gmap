# 开发工具箱：skill 与 harness

让 Claude 开发得更快、更不容易出错的那些东西：每样是什么、帮你什么、怎么用。
进度和候选项在 `STATUS.md`；规则本身在 `CLAUDE.md`。

## 自动生效的（不用记得去做）

| 工具 | 帮你什么 | 在哪 |
|---|---|---|
| 你的沟通规则（i-dont-read-code） | 每轮提醒：报结果不报过程，坏消息先说，每个「做完了」都带验证标签 | `.claude/skills/i-dont-read-code/` |
| 操作记录 | 自动记下实际跑过什么；说「我看过」时必须拿得出对应记录 | 同上，记录在 `.i-dont-read-code/`（不进仓库） |
| 开工读进度 | 每次新会话先读 `STATUS.md`；放了 7 天以上的「等你做的」会被提出来 | 同上 |
| 本项目每轮提醒卡 | 8 条：数据铁律、红线、截图规矩 | `.claude/project-card.sh` |
| 提交前跑测试 | 每次提交前自动跑全部测试（约 4 秒），不全绿就提交不了 | `.claude/hooks/test-before-commit.py` |
| 守卫测试 | 下面这些一旦失效，测试就变红：提醒卡没接上、过期提醒失灵、规则文件和提醒卡超出篇幅（只降不升）、进度文件超出开工时能读到的长度、skill 提到的文件或代码不存在了 | `tests/test_claude_setup.py` |
| 数据铁律检查 | 每个数字要有原句，原句里真有这个数；缺失不写 0；不拿别的年份补。采集结果和原型的全部城市都查 | `pipeline/check.py`，`tests/test_data_rules.py` |

## 要用时调出来的

| 工具 | 什么时候用 | 怎么用 |
|---|---|---|
| 一键截图 | 改了界面，要自己看或请你拍板 | `node tools/shots.js [区块…]`：手机和桌面、中文和 EN 四张图，加一张对照图，一个区块约 25 秒 |
| 按钮审查 | 动过按钮、链接、弹层 | 见 `design-freeze` skill 第四步：全部区块约 5 分钟，只审改过的区块约半分钟一块 |
| skill `add-data-source` | 接一个新数据源 | 先问口径和许可，照现有数据源的结构写，最后检查加抽查原文 |
| skill `design-freeze` | 出一版设计定稿 | 中英同步，按评分表改到 95 分以上，截图和按钮审查自查，请你拍板 |

## 账号里的 skill（每个会话都能直接用）

和本项目最相关的：

- 想清楚：`brainstorming`、`office-hours`、`plan-ceo-review`、`plan-design-review`、`plan-eng-review`
- 动手：`writing-plans`、`executing-plans`、`test-driven-development`
- 查错：`systematic-debugging`、`investigate`
- 收尾：`verification-before-completion`、`/code-review`
- 复盘：`retro`

## 加一样新工具之前

先按 `CLAUDE.md`「一条新规则该放哪」分流：机器能查的写成测试或钩子；每轮都要提醒的才进提醒卡；用到才查的写进 `docs/`。加了新工具，把它补进这份清单。
