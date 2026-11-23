#!/bin/bash
# tools/align.sh — 生成「人类指挥看板」HTML：纯本地、无外网依赖，file:// 直接打开。
#
# 用法:
#   bash tools/align.sh                    # 生成到 doc/align.html
#   bash tools/align.sh --open             # 生成后用系统默认浏览器打开
#   bash tools/align.sh --out out/ --data data/x.xlsx
#
# --out / --data 会转发给 run.sh；看板只消费 last_gates.json，不解析中文输出。
# 人类仍在 STATE / BLOCKS / doc 中做决策，HTML 不反写事实源，也不需要常驻服务。
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
HTML="$ROOT/doc/align.html"
OPEN=0
GATE_ARGS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --out)    GATE_ARGS+=(--out "$2"); shift 2;;
    --data)   GATE_ARGS+=(--data "$2"); shift 2;;
    --open)   OPEN=1; shift;;
    -h|--help) sed -n '2,12p' "$0"; exit 0;;
    *) echo "未知参数: $1（-h 看用法）"; exit 2;;
  esac
done

TMP="$(mktemp -d /tmp/tpl-align.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$ROOT/doc"

bash "$ROOT/tools/run.sh" --json "${GATE_ARGS[@]}" > "$TMP/gates.log" 2>&1
GATE_RC=$?
if [ "$GATE_RC" -ge 2 ] || [ ! -s "$ROOT/doc/health/last_gates.json" ]; then
  cat "$TMP/gates.log"
  echo "看板生成中止：本次没有可信的结构化闸门结果"
  exit 2
fi
bash "$ROOT/tools/doctor.sh" > "$TMP/doctor.txt" 2>&1

# git 事实（用于「代码」「文档同步」；非 git 仓库时留空，页面自行降级）
git -C "$ROOT" log --oneline -8 > "$TMP/gitlog.txt" 2>/dev/null || : > "$TMP/gitlog.txt"
git -C "$ROOT" log -1 --format=%cI > "$TMP/gitdate.txt" 2>/dev/null || : > "$TMP/gitdate.txt"

if ! "$PYTHON" "$ROOT/tools/checks/align_report.py" "$ROOT" \
  --gates "$ROOT/doc/health/last_gates.json" --doctor "$TMP/doctor.txt" \
  --gitlog "$TMP/gitlog.txt" --gitdate "$TMP/gitdate.txt" > "$TMP/align.html"; then
  echo "看板渲染失败，已保留上一份 HTML"
  exit 2
fi
mv "$TMP/align.html" "$HTML"

echo "已生成: $HTML"
echo "file://$HTML"
if [ "$GATE_RC" = 1 ]; then
  echo "注意：闸门存在 FAIL；看板已生成，但不能作为可交付依据"
fi

if [ "$OPEN" = 1 ]; then
  if command -v open >/dev/null 2>&1; then
    open "file://$HTML"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "file://$HTML"
  else
    echo "（本机无 open / xdg-open，请手动打开上面的 file:// 路径）"
  fi
fi
