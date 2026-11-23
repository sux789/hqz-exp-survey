# 硬约束注册表

> 规则：新约束递增编号；每条标注来源版本；被反转的旧约束**不删**，标注「已被 Cxx 反转」；冲突时按版本号判新旧。AI 改代码前必读。
> 能升级成可执行断言的约束优先升级（`tools/checks/` 或 `tools/selftest.sh`）——文字靠记，断言靠跑。

| 编号 | 约束 | 来源版本 | 反转链 |
|---|---|---|---|
| C01 | `tools/` 下 shell 脚本中，变量后紧跟非 ASCII 字符必须写 `${var}`。原因：macOS 自带 bash 3.2 会把多字节字符并入变量名 → `unbound variable`，且只在错误分支触发，极易潜伏 | 模板 v2.5 | — |
| C02 | 禁止手改生成物（`doc/align.html`、`baseline/`、`out/`）。改入口文件后重跑生成命令；手改即产生第二份真相 | 模板 v2.5 | — |
| C03 | 判定「文件是否存在」的检查必须显式跳过 macOS 噪音目录 `__MACOSX`（连同 `.idea` / `.vscode` / 各类缓存目录）。原因：macOS 解压 zip 会生成 `__MACOSX/`，其中的幽灵文件让存在性判定为真 → 闸门**假 PASS**。**漏报比误报危险**：误报只是吵人，漏报是替错误背书。`secret_scan.py` 同样跳过它（避免噪音误报），但 `data/` 绝不跳过——真实输入恰恰可能带凭证 | 模板 v2.6 | — |
| C04 | 文本解析统一用标准库：CSV 用 `csv` 模块，禁止手写 `split(",")`。原因：`"A,带逗号"` 会被静默错位，报出的行号与字段值**本身是错的**，把人引向错误的排查方向；同一仓库内并存两套解析口径即违反「同一事实只算一次」 | 模板 v2.6 | — |
| C05 | 校验与对比脚本必须把「结构性坏数据」转成带行号的 FATAL，不允许 Python 异常逃逸到用户面前：① 行宽 ≠ 表头 → 行宽断言；② 输出目录下的子目录不参与对比（否则 `IsADirectoryError`）。原因：traceback 没有行号没有字段名，直接违反「坏数据入口炸掉带行号」 | 模板 v2.6 | — |
| C06 | 上下文预算门（门7）口径只覆盖 `AGENTS.md` 的「必读」清单（6 个文件），**不得**为了让某个文件过关而扩张口径或调高预算值——给门量体裁衣，闸门就失去意义。口径外的根目录文本（`README.md` / `deploy.sh`）必须被**显式报出**（不隐形），其膨胀靠 `STATE.md` 资产活跃度表人工评审 | 模板 v2.6 | — |
| C07 | 自测（`tools/selftest.sh`）不得有副作用：① 对被测文件的任何行级文本注入，替换不到必须**立即 FAIL**——静默 no-op 会让断言悄悄失去牙齿，与 C03 同族；② 在模板根生成或删除文件前先备份，跑完恢复 | 模板 v2.6 | — |
| C08 | **机器可读结果单一来源**：`doc/health/last_gates.json` 只由 `run.sh --json` 经 `emit_json.py` 生成。`schema_version`、`gates[].id`、`status` 取值是下游契约，改名/删字段必须同版同步 `brief.py` / `triage.py` / 看板并升 `schema_version`。禁止手写、禁止在别处再解析 `run.sh` 中文输出——措辞一改就静默失效（漏报比误报危险，同 C03） | 模板 v3.0 | — |
| C09 | **无人值守只读**：`watch` / `schedule` 不得修改代码、不得重建基线、不得自动提交，失败只产出 `doc/health/TRIAGE.md`（事实 + 候选原因）。结论必须由人写进 `doc/NNN` 并更新 `STATE.md`——机器替人定业务口径，比红灯本身贵得多 | 模板 v3.0 | — |
| C10 | **钩子分层与时限**：`pre-commit` ≤ 2 秒，只跑静态门 + staged 增量密钥 + 生成物拦截；耗时门（双跑 / `tests/run_all.sh`）只能进 `pre-push` 或 CI。任何让 `pre-commit` 明显变慢的改动视为回归——闸门一慢，人就开始 `--no-verify`，防线等于没有 | 模板 v3.0 | 反转 v2.6「pre-commit 直接 exec run.sh」 |
| C11 | **派生视图禁手改**：`doc/brief.md`、`doc/review.md`、`doc/health/*`、`doc/align.html` 全部由命令生成、不入 git；与生成结果不一致时以**重新生成**为准。手改即第二份真相（同 C02） | 模板 v3.0 | — |
| C12 | 第一个 sheet 永远作为调查基础数据；表头按文本与合并区域定位，树种组成按“系数+名称”解析。禁止按本项目列号硬编码，坏行必须带 Excel 行号报错 | 应用 v1.0 | — |
| C13 | 材积公式以每个上传工作簿的样地表为直接依据：提取固定胸径、a/b/c、取整位数、采伐公式和每公顷系数；未知树种不得静默套用其他树种参数 | 应用 v1.0 | — |
| C14 | **上传/覆盖只走 `/admin/`**：所有 `/admin/api/*` 必须 `@admin_required`；覆盖必须服务端校验 `uploader == 当前用户 或 is_owner`，且 `confirm` 等于当前项目文件名——前端确认不算数。App 端 `POST /api/projects` 永久返回 403 指向后台 | 应用 v1.1 | 反转 v1.0「任意访问者可上传」 |
| C15 | **程序参数 sheet 是配置，不是数据**：第一个 sheet 永远是基础数据（C12），参数表若在第一位必须明确报错；未知 key / 重复 key / 全角分隔符 / 非法取值 / 越界数值 / 隐藏列不在表头，全部带 Excel 行号报错；**无参数表时行为必须等于 v1.0 默认值** | 应用 v1.1 | 默认值部分被 C17 反转（轨迹默认关，其余不变） |
| C16 | **登录态只读 forest-data**：`SECRET_KEY` 必须取自 `forest-data/web/.secret_key`，`SESSION_COOKIE_PATH` 必须 `"/"`，**禁止**设 `APPLICATION_ROOT`、**禁止**在本应用写 session（含 `session.clear()`）；页面与接口跳转一律用 `request.script_root`，禁止硬编码 `/`。原因：cookie 写 `Path=/exp-survey` 会与门户 `Path=/` 同名遮蔽 → 登出不掉、换账号串号（hqz-survey 2026-08-24 修复，H9）；硬编码 `/` 在网关下会跳回 gateway 首页。守卫：`tests/test_app.GatewayMountTests`（cookie 路径 + next 前缀 + 只读取用户） | 应用 v1.2 | 反转 v1.1「`APPLICATION_ROOT=prefix` 用于限定 cookie 与 https」 |
| C17 | **轨迹默认关闭**：无参数表时「功能」默认 `拍照`（不含「轨迹」）；轨迹是否可用**只由「功能」一个开关**决定，不得再加第二个布尔键（会出现「功能含轨迹但显示轨迹=否」的矛盾态）。原因：外业定位耗电、多数小班不需要。守卫：`tests/test_app` 的默认参数断言 + 「未开启轨迹时 PUT /track 返回 400」+ 「不开轨迹时采样间隔不校验、开轨迹时仍报错」 | 应用 v1.3 | 反转 C15「无参数表时行为等于 v1.0（拍照+轨迹）」 |
| C18 | **导出粒度**：~~一个项目一个 xlsx、每个小班一张 sheet~~ —— v1.4 起由 C19 取代；材积口径仍必须复用 `calculations`，不得在导出里另算一套 | 应用 v1.3 | 被 C19 取代 |
| C19 | **一个小班可有多块样地**：调查/轨迹/照片挂 `plots`（`subcompartment_id+plot_no` 唯一），上传即自动建「样地 1」，删样地至少留一块；导出每块样地一张 sheet，名 `小班号-样地号`。原因：一个主伐小班常布 2–5 块样地，挤在一行会串数。守卫：`tests/test_app` 多片样地用例 | 应用 v1.4 | — |

<!-- C 编号用于 STATE.md 的「活跃约束」区间，`bash tools/run.sh --status` 会自动读取。
     守卫归属：C01 由 selftest 的「shell 变量写法扫描」断言守住；C02 由 .gitignore 与 README 守住；
     C03/C04/C05/C06/C07 由 selftest「4/6 防线自身回归」一节的 6 条断言守住
     （见 doc/002-模板v2.6_防线索修复.md 的债务账本与测试段）。
     C08 由 selftest「v3 闭环」一节的 JSON schema 断言守住；C09 由 watch 实现与 triage 边界文案守住；
     C10 由 pre-commit 只调静态门的实现守住；C11 由 .gitignore 与 pre-commit 的生成物拦截守住
     （见 doc/003-AI协作v3_人机防错闭环.md 第 4、7、9 节）。 -->
