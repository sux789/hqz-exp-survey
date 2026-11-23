# 中幼林抚育调查

Excel 驱动的中幼林样地调查 App：管理员在 `/admin/` 上传调查设计总表，调查员在手机端筛选小班、按树种组成录入样地数据、实时计算材积、压缩照片并记录 WGS-84 轨迹。

- **线上**：`https://forest.bibook.top/exp-survey/`（gateway 挂载，appspec 在 `deploy/`）
- **本地**：`/usr/bin/python3 main.py` → <http://127.0.0.1:5000>
- **App**：`top.bibook.expsurvey`「抚育调查」，Capacitor 远程 URL 壳，网页更新无需重装

## 账号与权限

- 首次启动自动建超管：环境变量 `EXP_ADMIN_USER` / `EXP_ADMIN_PASSWORD`，缺省 `admin` / `admin123`（**生产必须覆盖并立即改密**）。
- `admin` 才能进 `/admin/` 上传与覆盖；`user` 只能调查。
- 覆盖已有项目：**上传人本人或超级管理员**，且要照原样输入当前项目文件名。
- 覆盖按小班号对齐，就地更新基础数据；已填调查、照片、轨迹全部保留；写库前自动备份到 `instance/backups/`。

## Excel 约定

- **第一个 sheet** = 调查基础数据，必须有「小班号」「树种组成」。
- **样地表** = 固定胸径、树种 a/b/c 材积公式、采伐公式、每公顷系数。
- **程序参数**（可选，兼容旧名「参数」）= 六列 `key|value|类型|默认值|说明|示例`：

| key | 取值 | 默认 |
|---|---|---|
| 功能 | `拍照;视频;轨迹;打卡` | `拍照;轨迹`（不含轨迹即不显示轨迹） |
| 压缩最长边 | 320–4096 | 1440 |
| 压缩质量 | 0.3–1.0 | 0.8 |
| 不显示列 | 基础数据表头名，`;` 分隔 | 空 |
| 水印内容 | `时间;坐标;小班` | 全部 |
| 轨迹采样间隔 | 1–60 秒 | 5 |

坏配置一律带 Excel 行号报错（未知 key、全角分隔符、越界、隐藏列不存在）。没有参数表时行为与 v1.0 完全一致。

## 运行与验证

```bash
/usr/bin/python3 -m pip install -r requirements.txt
/usr/bin/python3 main.py
/usr/bin/python3 -m unittest discover -s tests -v          # 16 项
PYTHON=/usr/bin/python3 bash tools/run.sh --out out/ --data data/中幼林抚育林木采伐调查设计总表.xlsx --json
```

## 部署

```bash
INSTALL=1 bash deploy.sh     # 首次：装依赖 + 同步 + appspec + 登记 + 重启 gateway
bash deploy.sh               # 日常
```

App 出包：推 `v*` tag → GitHub Actions 构建签名 APK 并发布 Releases（需 4 个 Secret：`KEYSTORE_BASE64` / `KEY_ALIAS` / `KEYSTORE_PASSWORD` / `KEY_PASSWORD`）；推送 `android/**` 只出 debug 包。

## 数据口径

单株材积 `ROUND(a × D^b × H^c, 3)`；径阶蓄积 = 单株材积 × 株数；平均胸径为株数加权平方平均；每公顷换算沿用样地表系数。公式依据见 `doc/004`，v1.1 变更见 `doc/005`。
