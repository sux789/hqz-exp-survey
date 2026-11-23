# 中幼林抚育调查

Excel 驱动的中幼林样地调查 App：管理员在 `/admin/` 上传调查设计总表，调查员在手机端筛选小班、按树种组成录入样地数据、实时计算材积、压缩照片并记录 WGS-84 轨迹。

- **线上**：`https://forest.bibook.top/exp-survey/`（gateway 挂载，appspec 在 `deploy/`）
- **本地**：`/usr/bin/python3 main.py` → <http://127.0.0.1:5000>
- **App**：`top.bibook.expsurvey`「抚育调查」，Capacitor 远程 URL 壳，网页更新无需重装

## 账号与权限

- **统一账号**：使用森林门户 <https://forest.bibook.top/forest/login> 的用户体系（`forest-data/web/forest_web.db`）。本应用不自建账号，只读门户登录后的 `session["user_id"]`。
- `is_admin=1` 才能进 `/admin/` 上传与覆盖，并且可覆盖任何人上传的项目；普通用户只能做调查。
- 覆盖已有项目：需照原样输入当前项目文件名；覆盖按小班号对齐，就地更新基础数据，已填调查、照片、轨迹全部保留；写库前自动备份到 `instance/backups/`。
- 本地调试：`EXP_LOCAL_USER=张三 /usr/bin/python3 main.py` 可免登录（等同管理员）；不设则跳门户登录。

## Excel 约定

- **第一个 sheet** = 调查基础数据，必须有「小班号」「树种组成」。
- **样地表** = 固定胸径、树种 a/b/c 材积公式、采伐公式、每公顷系数。
- **程序参数**（可选，兼容旧名「参数」）= 六列 `key|value|类型|默认值|说明|示例`：

| key | 取值 | 默认 |
|---|---|---|
| 功能 | `拍照;视频;轨迹;打卡` | `拍照`（**默认不显示轨迹**，需要就加「轨迹」） |
| 项目名称 | 文本，不能含 `/` | 空（照片落目录时用 App 名「抚育调查」兜底） |
| 说明 | 文本 | 空（填了才在水印里占一行） |
| 目录 | 模板 | `{{项目名称}}/{{小班号}}` → 相册 `Pictures/{目录}/` |
| 相片文件名 | 模板 | `{{项目名称}}_{{小班号}}_样地{{样地号}}_{{时间}}` |
| 水印内容 | `项目名称;小班;时间;坐标` | 全部 |
| 压缩最长边 | 320–4096 | 1440 |
| 压缩质量 | 0.3–1.0 | 0.8 |
| 不显示列 | 基础数据表头名，`;` 分隔 | 空 |
| 轨迹采样间隔 | 1–60 秒 | 5 |

模板占位符只有五个：`{{项目名称}} {{说明}} {{小班号}} {{样地号}} {{时间}}`（时间 = `YYYYMMDD_HHMMSS`）。
写错占位符、文件名里带 `/`、目录写成绝对路径，一律带 Excel 行号报错 —— 静默变空会让两万张照片堆在一个目录里、事后找不回来。

坏配置一律带 Excel 行号报错（未知 key、全角分隔符、越界、隐藏列不存在）。现成样板：`data/程序参数模板.xlsx`（复制这张 sheet 进总表即可）。

## 照片与导出

- **拍照（v1.5 起只存手机相册，不上传服务器）**：原生相机（`AppPermissions.takePhoto`，直接进相机，**没有「从相册选择」入口**）→ Canvas 等比压缩（参数「压缩最长边/质量」）→ 左下角白底黑字水印（项目名/小班+样地/说明/时间/坐标，逐项可关）→ 回写原片 EXIF → `savePhoto` 写入相册 `Pictures/{目录}/{文件名}.jpg`。水印的时间与经纬度**优先取原片 EXIF**，读不到才退回设备定位与当前时间。
- **导出**：App 项目页点「导出全部样地 Excel」，得到一个 xlsx，**每个小班一张 sheet**（基本信息 + 树种×径阶株数/树高/单株材积/蓄积 + 采伐 + 汇总 + 照片数与轨迹点数）；未调查的小班也会有一张 sheet 并写明「尚未录入」。照片不再上传，所以导出里的照片数恒为 0。

## 运行与验证

```bash
/usr/bin/python3 -m pip install -r requirements.txt
/usr/bin/python3 main.py
/usr/bin/python3 -m unittest discover -s tests -v          # 38 项（Python）
node tests/test_exif.js                                     # 前端 EXIF 纯逻辑（20 条）
node tests/test_photo_tpl.js                                # 照片命名/相册目录/水印行（26 条）
PYTHON=/usr/bin/python3 bash tools/run.sh --out out/ --data data/中幼林抚育林木采伐调查设计总表.xlsx --json
```

## 部署

```bash
INSTALL=1 bash deploy.sh     # 首次：装依赖 + 同步 + appspec + 登记 + 重启 gateway
bash deploy.sh               # 日常（先预检 forest-data 的 .secret_key / forest_web.db 可读）
```

部署后匿名访问 `GET /exp-survey/` 应 302 到 `/forest/login?next=/exp-survey/`，否则先查 secret_key 是否与 portal 同一把。

App 出包：推 `v*` tag → GitHub Actions 构建签名 APK 并发布 Releases（需 4 个 Secret：`KEYSTORE_BASE64` / `KEY_ALIAS` / `KEYSTORE_PASSWORD` / `KEY_PASSWORD`）；推送 `android/**` 只出 debug 包。

## 数据口径

单株材积 `ROUND(a × D^b × H^c, 3)`；径阶蓄积 = 单株材积 × 株数；平均胸径为株数加权平方平均；每公顷换算沿用样地表系数。公式依据见 `doc/004`，v1.1 变更见 `doc/005`。
