# STATE — 当前状态快照

- **版本**：v1.4 ｜ **更新**：2026-11-23
- **能跑**：`/usr/bin/python3 main.py` 启动；本地免登录用 `EXP_LOCAL_USER=姓名`（等同管理员），不设则走门户登录态。
- **账号**：统一用 forest-data（`/forest/login`）体系：只读门户写入的 user_id 并现查 `forest_web.db.users`；`is_admin=1` 即管理员（可覆盖任何人上传的项目），停用/过期立即失效。本应用不自建账号。
- **样地**：一个小班可有多块样地（`plots` 表，`subcompartment_id+plot_no` 唯一）；上传即自带「样地 1」。详情页 chip 切换（当前实心绿、其余灰色），可 ＋新增 / 改号 / 删除（至少留一块）；调查、照片、轨迹全按样地存。
- **拍照**：Canvas 压缩到参数「压缩最长边/质量」，半透明白底黑字水印（时间/坐标/小班，可在参数里去项）；时间与坐标**优先取原片 EXIF 并回写**（piexifjs），失败静默退回原行为。
- **轨迹**：默认关闭（「功能」默认只有「拍照」）；要轨迹就在参数 value 里加「轨迹」。不开轨迹时「轨迹采样间隔」整行不生效、不校验（填 0 不报错）。
- **导出**：一个 xlsx、**每块样地一张 sheet**，sheet 名 `小班号-样地号`，顺序按小班号→样地号自然序（XP-2 排在 XP-10 前）。
- **已验证**：36 项单元测试（含 node 跑的 EXIF 20 条）；七门 PASS；无头 Chrome 实测 chip 切换、新增样地、列表点号、手机布局。
- **权限**：上传/覆盖只在 `/admin/`（`@admin_required` + 上传人本人或管理员 + 项目名确认）；App 端上传接口 403。门户侧 27 个活跃账号已有 `user_app_grants`。
- **缓存口径**：静态资源带 `?v=ASSET_VERSION`（当前 v1.4.0），HTML `no-cache`；旧缓存 JS 打已下线接口会拿到 410 JSON。
- **部署**：`bash deploy.sh`（预检 forest-data 凭证 → 同步代码/static → appspec → `kill -HUP` 重载 gateway）；APK 由 GitHub Actions 出包（appId `top.bibook.expsurvey`）。
- **已知限制**：浏览器轨迹需保持页面开启；导出内存随 sheet 数增长；WebView 下载 xlsx 未实测。
- **下一步**：1. 现场走「登录→多块样地→导出」2. 验证 App 内 xlsx 落盘 3. 大项目导出改后台任务。
- **最近迭代文档**：doc/009-v1.4_多片样地与按样地导出.md（上一版 doc/008）
- **活跃约束**：C01–C19（详见 CONSTRAINTS.md）

## 资产活跃度

| 资产 | 上次发挥作用的版本 | 作用 | 处置 |
|---|---|---|---|
| workbook.py | v1.1 | 解析基础表、样地表，并接入程序参数 | 保留 |
| param_parser.py | v1.3.1 | 程序参数校验与默认值（轨迹默认关） | 保留 |
| auth.py | v1.2 | 只读 forest-data 登录态、管理员判定、覆盖权限 | 保留 |
| app.py | v1.4 | API、鉴权、样地表与多片样地接口、拍照/轨迹按样地 | 保留 |
| static/app.js | v1.4 | 参数化界面、样地 chip 切换、拍照水印/EXIF | 保留 |
| export_xlsx.py | v1.4 | 全量导出：每块样地一张 sheet、自然序 | 保留 |
| photo_exif.js + piexif.js | v1.3 | 读/回写 EXIF（浏览器与 node 通用） | 保留 |
| admin.html / admin.js | v1.2 | 管理员上传与覆盖（用户管理已移交门户） | 保留 |
| calculations.py | v1.0 | 材积、汇总与轨迹距离（导出复用同一套口径） | 保留 |
| tests/test_app.py + tests/test_exif.js | v1.4 | 工作簿/API/样地/导出/EXIF 回归（36 项 + 20 条） | 保留 |
| data/程序参数模板.xlsx | v1.3 | 6 列参数参考模板 | 保留 |
| tools/ui_smoke.mjs | v1.0 | 旧版浏览器全流程（流程已变） | 待更新 |
| tools/run.sh | v1.0 | 七门体检与结构化结果 | 保留 |
