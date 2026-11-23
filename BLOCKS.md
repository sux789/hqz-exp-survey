# BLOCKS — 积木注册表

> 规则：新增积木必须登记；AI 提问 / 指令先指向编号；≤25 行。

| 编号 | 职责 | 文件 | 输入 | 输出 | 依赖 |
|---|---|---|---|---|---|
| B1 | 工作簿表头、树种组成与样地表公式解析 | workbook.py | .xlsx/.xlsm | 基础记录与公式配置 | openpyxl |
| B2 | 材积、汇总和轨迹距离计算 | calculations.py | 调查数据与公式配置 | 汇总结果 | B1 |
| B3 | 项目 API、SQLite 持久化、照片和 GPX | app.py | HTTP 请求 | JSON/JPEG/GPX | B1、B2 |
| B4 | 项目、筛选、调查网格、照片与卫星轨迹交互 | static/app.js | B3 API | 浏览器界面 | Leaflet |
| B5 | 页面结构与移动优先样式 | `templates/index.html` `static/style.css` | B4 渲染 | 页面与布局 | — |
| B6 | 单元测试和真实浏览器冒烟验证 | `tests/test_app.py` `tests/test_exif.js` | 真实工作簿/本地应用 | 测试断言与截图 | B1–B5、B11 |
| B7 | 登录态读取与覆盖权限（只读 forest-data session） | auth.py | forest_web.db + session | 登录态与 403 判定 | SQLite、forest-data |
| B8 | 「程序参数」sheet 解析与校验 | param_parser.py | 参数表六列 | 功能/压缩/隐藏列配置 | openpyxl |
| B9 | 管理员后台（上传、预检覆盖、账号说明） | `templates/admin.html` `static/admin.js` | B3 API | 后台界面 | B3、B7、B8 |
| B10 | gateway 部署与 APK 打包 | `deploy/` `deploy.sh` `android/` `.github/workflows/` | 源码 | 线上挂载 + APK | — |
| B11 | 全量导出：一个项目 → 一个 xlsx、每小班一张 sheet | export_xlsx.py | schema + 全部小班 | xlsx 字节流 | B2 |
| B12 | 照片命名/目录/水印行 + EXIF 读回写 | `static/photo_tpl.js` `static/photo_exif.js` `static/vendor/piexif.js` | 参数+样地+原片 | 文件名/目录/水印/带 EXIF 图 | B4 |
| B13 | 原生相机 + 相册写入 | `android/app/src/main/java/top/bibook/expsurvey/AppPermissionsPlugin.java` | takePhoto/savePhoto | 相册路径 | Capacitor |

> 契约补充：B7 覆盖判定必须在后端（前端 disabled 只影响体验）；B8 报错必须带 Excel 行号且默认值等于 v1.0；B10 的 App 是远程 URL 壳，改网页不必重新出包。

> 契约：B1 对坏数据抛出带 Excel 行号的 WorkbookError；B2 单株和径阶材积按源表位数取整；B3 不返回服务器文件路径；B4 修改后自动保存；B6 使用隔离测试数据库与 Chrome 配置。
