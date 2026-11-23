# 中幼林抚育调查

基于 `project-template` 创建的移动优先调查应用。上传调查设计总表后，可筛选小班、按树种组成录入样地数据、实时计算材积、压缩样地照片并记录卫星轨迹。

## 功能

- 项目列表保留 Excel 原始文件名，第一个 sheet 作为调查基础数据。
- 标段 → 乡镇 → 村委会级联筛选，小班号模糊搜索。
- 调查页依据小班树种组成和“样地表”生成固定胸径网格；株数数字控件、树高数值输入、公式即时计算、自动保存。
- 照片等比压缩至最长边 1440px、JPEG 质量 0.8，添加时间/坐标/小班水印。
- Leaflet 卫星底图、WGS-84 轨迹、距离统计、本机缓存和 GPX 导出。

## 运行

```bash
python3 -m pip install -r requirements.txt
python3 main.py
```

打开 `http://127.0.0.1:5000`。运行数据保存在 `instance/`，该目录不入库。卫星瓦片和浏览器定位需要网络及定位授权；轨迹记录期间应保持页面开启。

## 验证

```bash
python3 -m unittest discover -s tests -v
python3 main.py --data data/ --out out/
bash tools/run.sh --out out/ --data data/中幼林抚育林木采伐调查设计总表.xlsx --json
```

浏览器冒烟测试 `tools/ui_smoke.mjs` 使用本机 Chrome 的 CDP，覆盖上传、筛选、公式、刷新持久化、图片尺寸、轨迹和移动布局。运行前需启动应用及 `--remote-debugging-port=9222` 的隔离 Chrome。

## 数据口径

- `workbook.py` 根据第一个 sheet 的表头文本定位数据，并提取“样地表”的固定胸径、树种二元材积参数、采伐公式和每公顷系数；未配置树种公式会明确报错。
- 单株材积为 `ROUND(a × D^b × H^c, 3)`，径阶蓄积为单株材积乘株数；采伐蓄积直接使用样地表采伐公式。
- 平均胸径采用株数加权平方平均，每公顷株数/蓄积沿用样地表系数。
- 公式与模板结构的迭代依据见 `doc/004-v1.0_中幼林抚育调查应用.md`。
