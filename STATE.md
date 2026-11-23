# STATE — 当前状态快照

- **版本**：v1.3 ｜ **更新**：2026-11-23
- **能跑**：`/usr/bin/python3 main.py` 启动；本地免登录用 `EXP_LOCAL_USER=姓名`（等同管理员），不设则走门户登录态。
- **账号**：统一用 forest-data（森林门户 `/forest/login`）的用户体系，本应用只读门户写入的 user_id 并现查 `forest_web.db.users`；`is_admin=1` 即管理员（可覆盖任何人上传的项目），账号停用/过期立即失效。本应用不再自建账号、不再播种 admin123。
- **拍照**：Canvas 压缩到参数「压缩最长边/质量」，半透明白底黑字水印（时间/坐标/小班，可在参数里去项）；**水印时间与坐标优先取原片 EXIF，压缩后把 EXIF 回写**（piexifjs），失败静默退回原行为。
- **轨迹**：默认关闭（「功能」默认只有「拍照」）；要轨迹就在参数 sheet 的 value 里加「轨迹」。轨迹仍按小班存点、可导 GPX。
- **导出**：App 项目页「导出全部样地 Excel」→ 一个 xlsx、每个小班一张 sheet（684 小班实测 1.8s / 940KB）。
- **参数模板**：`data/程序参数模板.xlsx` 是带 6 列参考行的样板，业务员复制进总表即可。
- **已验证**：29 项单元测试（含 node 跑的 EXIF 20 条、684 张 sheet 导出断言）；七门 PASS；无头 Chrome 实测水印与 EXIF 回写。
- **权限口径**：上传/覆盖只在 `/admin/`；`@admin_required` + 上传人本人或管理员（服务端双重校验）+ 项目名确认；App 端上传接口返回 403。门户侧已给 27 个活跃账号补 `user_app_grants`（exp-survey，无期限），否则登录后会被弹回 `/forest/`。
- **缓存口径**：模板引用静态资源带 `?v=ASSET_VERSION`（发版递增，当前 v1.3.0），HTML `no-cache`；旧缓存 JS 打已下线接口会拿到 410 JSON。
- **部署**：`bash deploy.sh`（预检 forest-data 凭证 → 同步代码/static → appspec → `kill -HUP` 重载 gateway）；APK 由 GitHub Actions 出包（appId `top.bibook.expsurvey`，壳指向 `https://forest.bibook.top/exp-survey/`）。
- **已知限制**：浏览器轨迹需保持页面开启；导出内存随 sheet 数增长（未分卷）；WebView 下载 xlsx 未实测。
- **下一步**：1. 现场走「登录→拍照→导出」2. 验证 App 内 xlsx 能否落盘 3. 大项目导出可改后台任务+压缩包。
- **最近迭代文档**：doc/007-v1.3_拍照EXIF与全量导出.md（上一版 doc/006）
- **活跃约束**：C01–C18（详见 CONSTRAINTS.md）

## 资产活跃度

| 资产 | 上次发挥作用的版本 | 作用 | 处置 |
|---|---|---|---|
| workbook.py | v1.1 | 解析基础表、样地表，并接入程序参数 | 保留 |
| param_parser.py | v1.3 | 程序参数校验与默认值（轨迹默认关） | 保留 |
| auth.py | v1.2 | 只读 forest-data 登录态、管理员判定、覆盖权限 | 保留 |
| app.py / static/app.js | v1.3 | API、鉴权、拍照水印/EXIF、参数化界面、导出入口 | 保留 |
| export_xlsx.py | v1.3 | 全量导出：每个小班一张 sheet | 保留 |
| static/photo_exif.js + vendor/piexif.js | v1.3 | 读/回写 EXIF（浏览器与 node 通用） | 保留 |
| admin.html / admin.js | v1.2 | 管理员上传与覆盖（用户管理已移交门户） | 保留 |
| calculations.py | v1.0 | 材积、汇总与轨迹距离（导出复用同一套口径） | 保留 |
| tests/test_app.py + tests/test_exif.js | v1.3 | 工作簿/API/鉴权/导出/EXIF 回归（29 项 + 20 条） | 保留 |
| data/程序参数模板.xlsx | v1.3 | 6 列参数参考模板（功能默认拍照） | 保留 |
| tools/ui_smoke.mjs | v1.0 | 旧版浏览器全流程（上传与登录流程已变，需重写） | 待更新 |
| tools/run.sh | v1.0 | 七门体检与结构化结果 | 保留 |
