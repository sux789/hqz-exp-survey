# STATE — 当前状态快照

- **版本**：v1.5 ｜ **更新**：2026-11-23
- **能跑**：`/usr/bin/python3 main.py`；本地免登录 `EXP_LOCAL_USER=姓名`（等同管理员），不设走门户登录态。
- **账号**：只读 forest-data 门户账号（`forest_web.db.users`，`is_admin=1` 即管理员），本应用不自建账号，停用/过期立即失效。
- **样地**：一个小班多块样地（`plots`，`subcompartment_id+plot_no` 唯一，上传自带「样地 1」）；chip 切换 / 新增 / 改号 / 删除（至少留一块）。
- **拍照**：**只存手机相册、不上传服务器**（C20）。原生相机 `takePhoto`（无「从相册选择」）→ 压缩（参数「压缩最长边/质量」）+ 半透明白底黑字水印（项目名 / 小班+样地 / 说明 / 时间 / 坐标，逐项可关）→ 时间与坐标优先取原片 EXIF 并回写 → `savePhoto` 写 `Pictures/{目录}/{文件名}.jpg`；默认 `项目名称/小班号` 与 `项目名称_小班号_样地N_时间`，项目名留空用 App 名「抚育调查」。
- **轨迹**：默认关闭（「功能」默认只有「拍照」），需要就加「轨迹」；不开轨迹时「轨迹采样间隔」不生效、不校验。
- **导出**：一个 xlsx、每块样地一张 sheet（名 `小班号-样地号`，自然序）；照片不再落服务器，导出里的照片数恒 0。
- **已验证**：Python 38 项 + node 照片命名 26 条 + EXIF 20 条；七门 PASS。
- **权限**：上传/覆盖只在 `/admin/`（`@admin_required` + 本人或管理员 + 项目名确认），App 端 403。
- **缓存**：静态资源带 `?v=ASSET_VERSION`（v1.5.0）。
- **部署**：`bash deploy.sh`（预检凭证 → 同步 → appspec → `kill -HUP`）；APK 由 GitHub Actions 出（`top.bibook.expsurvey`）。
- **已知限制**：浏览器轨迹需页面常开；WebView 下载 xlsx 未实测；旧 APK（< v1.1）拍照会提示升级。
- **下一步**：1. 出 v1.1 APK 真机验相册路径/文件名/水印 2. 现场「登录→多块样地→拍照→导出」3. 大项目导出改后台任务。
- **最近文档**：doc/010-v1.5_照片存相册与原生拍照.md｜ **活跃约束**：C01–C20

## 资产活跃度

| 资产 | 版本 | 作用 | 处置 |
|---|---|---|---|
| workbook.py | v1.1 | 解析基础表、样地表，接入程序参数 | 保留 |
| param_parser.py | v1.5 | 参数校验与默认值（含拍照模板） | 保留 |
| auth.py | v1.2 | 只读 forest-data 登录态、管理员/覆盖判定 | 保留 |
| app.py | v1.4 | API、鉴权、样地与多片样地接口 | 保留 |
| static/app.js | v1.5 | 界面、样地切换、拍照→相册（不传服务器） | 保留 |
| export_xlsx.py | v1.4 | 全量导出：每块样地一张 sheet、自然序 | 保留 |
| photo_exif.js + piexif.js | v1.3 | 读/回写 EXIF（浏览器与 node 通用） | 保留 |
| photo_tpl.js | v1.5 | 照片命名/目录/水印行纯逻辑 | 保留 |
| AppPermissionsPlugin.java | v1.5 | 原生相机 + 相册写入（需 v1.1 APK） | 保留 |
| admin.html / admin.js | v1.2 | 管理员上传与覆盖（用户管理已移交门户） | 保留 |
| calculations.py | v1.0 | 材积、汇总与轨迹距离（导出复用同口径） | 保留 |
| tests/test_app.py + test_exif.js + test_photo_tpl.js | v1.5 | 工作簿/API/样地/导出/EXIF/命名回归 | 保留 |
| data/程序参数模板.xlsx | v1.5 | 10 个 key 的参数参考模板 | 保留 |
| tools/ui_smoke.mjs | v1.0 | 旧版浏览器全流程（流程已变） | 待更新 |
| tools/run.sh | v1.0 | 七门体检与结构化结果 | 保留 |
