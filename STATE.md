# STATE — 当前状态快照

- **版本**：v1.2 ｜ **更新**：2026-11-23
- **能跑**：`/usr/bin/python3 main.py` 启动；本地免登录用 `EXP_LOCAL_USER=姓名`（等同管理员），不设则走门户登录态。
- **账号**：统一用 forest-data（森林门户 `/forest/login`）的用户体系，本应用只读门户写入的 user_id 并现查 `forest_web.db.users`；`is_admin=1` 即管理员（可覆盖任何人上传的项目），账号停用/过期立即失效。本应用不再自建账号、不再播种 admin123。
- **已验证**：22 项单元测试通过（含网关前缀 cookie 与登录回跳断言）；七门体检全 PASS；本地 `EXP_LOCAL_USER` 走通首页/后台。
- **权限口径**：上传/覆盖只在 `/admin/`；`@admin_required` + 上传人本人或管理员（服务端双重校验）+ 项目名确认；App 端上传接口返回 403。
- **数据口径**：第一个 sheet 是基础数据；`程序参数` sheet 只做配置；样地表提供固定胸径、a/b/c 和采伐公式；无参数表时行为等于 v1.0。
- **部署**：`bash deploy.sh`（预检 forest-data 凭证 → appspec → `/exp-survey`，重启 gateway）；APK 由 GitHub Actions 出包（appId `top.bibook.expsurvey`，壳指向 `https://forest.bibook.top/exp-survey/`）。
- **已知限制**：浏览器轨迹需保持页面开启，无原生后台定位；`/usr/bin/python3` 才有 Flask；门户改密/停用后本应用无通知，仅下次请求生效。
- **下一步**：1. 首次线上验证「门户登录→回跳→填报→登出」全链路 2. 现场验证 WebView 的定位/相机权限 3. 如需按程序授权，再开 `user_app_grants`（当前不拦）。
- **最近迭代文档**：doc/006-v1.2_接入森林门户统一账号.md
- **活跃约束**：C01–C16（详见 CONSTRAINTS.md）

## 资产活跃度

| 资产 | 上次发挥作用的版本 | 作用 | 处置 |
|---|---|---|---|
| workbook.py | v1.1 | 解析基础表、样地表，并接入程序参数 | 保留 |
| param_parser.py | v1.1 | 程序参数校验与默认值 | 保留 |
| auth.py | v1.2 | 只读 forest-data 登录态、管理员判定、覆盖权限 | 保留 |
| app.py / static/app.js | v1.2 | API、鉴权、参数化界面、统一登录跳转 | 保留 |
| admin.html / admin.js | v1.2 | 管理员上传与覆盖（用户管理已移交门户） | 保留 |
| calculations.py | v1.0 | 材积、汇总与轨迹距离 | 保留 |
| tests/test_app.py | v1.2 | 工作簿、API、鉴权、网关前缀回归（22 项） | 保留 |
| tools/ui_smoke.mjs | v1.0 | 旧版浏览器全流程（上传与登录流程已变，需重写） | 待更新 |
| tools/run.sh | v1.0 | 七门体检与结构化结果 | 保留 |
