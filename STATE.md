# STATE — 当前状态快照

- **版本**：v1.1 ｜ **更新**：2026-11-23
- **能跑**：`/usr/bin/python3 main.py` 启动；首次启动自动建库并播种超管（`EXP_ADMIN_USER`/`EXP_ADMIN_PASSWORD`，缺省 admin/admin123）。
- **已验证**：16 项单元测试通过；七门体检全 PASS；Chrome 156 无头 390×844 走通登录→项目→小班→详情→后台→覆盖弹窗，控制台 0 异常。
- **权限口径**：上传/覆盖只在 `/admin/`；`@admin_required` + 上传人本人或超管 + 项目名确认（服务端三重校验）；App 端上传接口返回 403。
- **数据口径**：第一个 sheet 是基础数据；`程序参数` sheet 只做配置；样地表提供固定胸径、a/b/c 和采伐公式；无参数表时行为等于 v1.0。
- **部署**：`bash deploy.sh`（gateway appspec → `/exp-survey`，重启 gateway）；APK 由 GitHub Actions 出包（appId `top.bibook.expsurvey`）。
- **已知限制**：浏览器轨迹需保持页面开启，无原生后台定位；未实际推送线上、未真实触发 CI；`/usr/bin/python3` 才有 Flask（workbuddy 自带 3.13 无依赖）。
- **下一步**：1. 首次线上部署 + 配 4 个签名 Secret 出正式包 2. 现场验证 WebView 的定位/相机权限 3. 按需补自动回滚（当前只有备份快照）。
- **最近迭代文档**：doc/005-v1.1_管理员上传与程序参数.md
- **活跃约束**：C01–C15（详见 CONSTRAINTS.md）

## 资产活跃度

| 资产 | 上次发挥作用的版本 | 作用 | 处置 |
|---|---|---|---|
| workbook.py | v1.1 | 解析基础表、样地表，并接入程序参数 | 保留 |
| param_parser.py | v1.1 | 程序参数校验与默认值 | 保留 |
| auth.py | v1.1 | 用户、会话、覆盖权限 | 保留 |
| app.py / static/app.js | v1.1 | API、鉴权、参数化界面 | 保留 |
| admin.html / admin.js | v1.1 | 管理员上传与覆盖 | 保留 |
| calculations.py | v1.0 | 材积、汇总与轨迹距离 | 保留 |
| tests/test_app.py | v1.1 | 工作簿、API、权限与参数回归（16 项） | 保留 |
| tools/ui_smoke.mjs | v1.0 | 旧版浏览器全流程（上传流程已变，需重写） | 待更新 |
| tools/run.sh | v1.0 | 七门体检与结构化结果 | 保留 |
