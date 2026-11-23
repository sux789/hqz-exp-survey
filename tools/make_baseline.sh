#!/bin/bash
# 基线快照：改代码前对 data/ 全用例跑当前版本，供 tools/checks/compare.py 双跑对比。
# 标准流程：
#   1) 改代码前:  bash tools/make_baseline.sh        → 基线存 baseline/<时间戳>/，latest 指向它
#   2) 改代码后:  重跑生成命令到 out/                 → 与基线同构的输出目录
#   3) 双跑对比:  python tools/checks/compare.py baseline/latest/ out/
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

GEN_CMD="python main.py --data data/ --out"

STAMP=$(date +%Y%m%d_%H%M%S)
DEST="baseline/$STAMP"
mkdir -p "$DEST"
$GEN_CMD "$DEST"
ln -sfn "$STAMP" baseline/latest
echo "基线已存: $DEST"
echo "对比用法: python tools/checks/compare.py baseline/latest/ out/"
