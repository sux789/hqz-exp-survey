# AI 协作协议

> 开工第一件事：`bash tools/ai.sh brief`（≤4KB 事实卡）。它已摘要 STATE / 闸门 / git / 约束，
> 本文件与 CONSTRAINTS / BLOCKS / STATE / GLOSSARY 改为**按需回查**，不再要求整篇读入。
> `[方括号]` 为占位符，新项目第一天替换为本项目实际内容（`tools/run.sh` 会检查残留）。<!-- ok -->

## 指挥原则

1. 遇错先执行拿真实报错，不猜。
2. 改动方向：兼容性最好、最小改动；边界：不上传或修改桌面参考项目，只改当前工作区。
3. 提交前对照原始数据自审，推导 / 默认值逻辑重点审。
4. 超过 3 个文件或涉及数据结构变化，先出方案文档确认再动手。
5. 指令精确到三级坐标：积木编号 → 文件:行号 → 单元格 / 字段名，不说「改输出」。
6. 拿不准的业务判断列待确认清单（问题 / 候选方案 / 建议 / 依据），不替用户做决定。

## 项目铁律（违反 = 返工）

- 校验失败原样报错 + 列可选值，不自动映射 / 推导。
- 坏数据入口炸掉带行号，不静默跳过；所有记录被跳过时必须抛错，不生成空输出。
- 改算法前先读原始公式 / 数据 / 模板结构，证据先行，不凭记忆。
- 同一事实只算一次，跨表 / 跨处引用不重算；展示层能用公式用公式。
- 数值在源头一次取整，显示值 = 计算值，下游不再取整；表间勾稽在显示值上成立。
- 每次运行全新状态，全局缓存 / 配置入口重置，不跨运行残留。
- 改动后必须双跑全量用例对比，0 差异或预期差异才提交。
- 对比出差异先归因（代码 bug / 数据问题 / 基准错 / 合理多解），不默认改代码对齐。
- WARN 级问题汇总成报告文件，不逐个打断、不淹没控制台。
- 模板 / 生成物只填值不动样式；写入前先确认标签位 / 值位。

## 完成定义 DOD（全部勾选才算做完；★ 由机器校验，其余靠人）

| # | 判据 | 校验方式 |
|---|---|---|
| 1 | 输入校验通过，坏数据带行号报错 | ★ 门1 `validate.py` |
| 2 | 业务勾稽断言全通过 | ★ 门2 `check_invariants.py` |
| 3 | 与基线双跑一致率 100%，或差异已归因 | ★ 门3 `compare.py` |
| 4 | 索引未腐化（BLOCKS / STATE 引用的文件与 doc 编号都存在） | ★ 门4 `index_check.py --index` |
| 5 | 无残留 `[方括号]` 占位符 | ★ 门5 `index_check.py --placeholder` |<!-- ok -->
| 6 | 无密钥 / 凭证泄漏 | ★ 门6 `secret_scan.py` |
| 7 | 入口文件总量在上下文预算内（默认 24KB） | ★ 门7 `context_budget.py` |
| 8 | 写了 `doc/NNN-版本_主题.md`，反转记录不省 | 人工 |
| 9 | 新增 / 变更的约束已同步 CONSTRAINTS.md | 人工 |
| 10 | 新增业务名词已进 GLOSSARY.md | 人工 |
| 11 | STATE.md 已更新（可用 `--status` 生成草稿） | 人工 |
| 12 | 改动已出评审单，HIGH 风险项逐条回应 | 人工 `bash tools/ai.sh explain` |

一条命令跑完全部机器项：`bash tools/run.sh --out out/ --data data/xxx.xlsx --json --status`
`--json` 会把结果写成 `doc/health/last_gates.json`（brief / triage / CI 都读它，别手改）。
某门连续 3 次 SKIP 会提示启用——SKIP 不该是永久状态。

**这条命令就是「做完」的机器定义。** 全绿之前不要说完成——也不要手工替它判断。

## 每次迭代必须

- 一版解决 1–3 个问题，版本号递增。
- 写 `doc/NNN-版本_主题.md`（模板见 doc/001，七段式：需求 / 验证 / 设计 / 代码 / 测试 / 反转 / 部署）。
- 新决策若推翻旧决策，写明反转链；同步更新 CONSTRAINTS.md。
- 改口径必同步三处：模板 + 代码 + 测试断言。
- 收尾两条：`bash tools/ai.sh explain` 过一遍评审单（风险高就先别提交）；`bash tools/ai.sh brief` 刷新简报。
- 提交信息带 `Refs: doc/NNN`（commit-msg 钩子强制）；用 `--no-verify` 必须在迭代文档写原因。

## 项目专属信息（填空）

- **业务一句话**：Excel 驱动的中幼林样地调查、材积计算、照片压缩与卫星轨迹记录。
- **输入**：调查设计总表 .xlsx/.xlsm；真实用例为 data/中幼林抚育林木采伐调查设计总表.xlsx。
- **输出**：浏览器调查数据、SQLite 记录、压缩 JPEG 和 GPX 轨迹；校验结果为 out/validation-summary.json。
- **真实用例**：data/ 下的调查设计总表；单元测试覆盖正常、公式边界和错误数据。
- **权威信息源排序**：P0 上传工作簿样地表公式 > P1 第一个 sheet 基础数据 > P2 forest-data 计算参考 > P3 supervision 交互参考。
- **运行命令**：`python3 main.py`；批量校验：`python3 main.py --data data/ --out out/`。
- **验证命令**：`bash tools/run.sh --out out/ --data data/中幼林抚育林木采伐调查设计总表.xlsx --json`
- **基线命令**：`bash tools/make_baseline.sh`
- **开场简报**：`bash tools/ai.sh brief`（写 doc/brief.md，AI 每会话第一读）
- **评审单**：`bash tools/ai.sh explain`（写 doc/review.md，提交前给人看）
- **巡检/分诊**：`bash tools/ai.sh watch --once` → 失败出 doc/health/TRIAGE.md
- **对齐看板**：`bash tools/align.sh --open`（生成 doc/align.html，人与 AI 以同一份对齐）
- **部署命令**：本地运行，不执行外部部署。
