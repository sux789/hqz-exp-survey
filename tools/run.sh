#!/bin/bash
# tools/run.sh — 唯一验证入口，把「完成定义 DOD」变成可执行闸门。
#
# PASS 退出 0；任一门 FAIL 退出 1。缺前置条件的门自动 SKIP（不假装通过）；
# 只有七门全 PASS 才是 PASS；有 SKIP/WARN 时总体为 INCOMPLETE，不能宣称全绿。
# 同一门连续 3 次 SKIP 会提示启用——SKIP 不该是永久状态。
# 带 .template 的模板本体上，「索引一致性」「占位符残留」两门降级为 WARN；实例化后升为 FAIL。
#
# 用法:
#   bash tools/run.sh                                  # 静态门：索引 + 占位符 + 密钥 + 上下文预算
#   bash tools/run.sh --out out/                       # + 业务勾稽断言 + 双跑对比
#   bash tools/run.sh --out out/ --data data/x.xlsx    # + 输入校验
#   bash tools/run.sh --out out/ --status              # 末尾打印 STATE 草稿
#   bash tools/run.sh --json                           # 额外写 doc/health/last_gates.json（机器可读）
#   bash tools/run.sh --json=doc/health/g.json         # 指定 JSON 路径
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHECKS="$ROOT/tools/checks"
PY="${PYTHON:-python3}"
OUT=""; DATA=""; STATUS=0
JSON_OUT=""; WANT_JSON=0
ORIGINAL_ARGS="$*"

while [ $# -gt 0 ]; do
  case "$1" in
    --out)    OUT="${2:-}"; shift 2;;
    --data)   DATA="${2:-}"; shift 2;;
    --status) STATUS=1; shift;;
    --json)   WANT_JSON=1; shift;;
    --json=*) WANT_JSON=1; JSON_OUT="${1#*=}"; shift;;
    -h|--help) sed -n '2,14p' "$0"; exit 0;;
    *) echo "未知参数: $1（-h 看用法）"; exit 2;;
  esac
done

FAILS=0; SKIPS=0; WARNS=0
RESULTS="$(mktemp "${TMPDIR:-/tmp}/gates.XXXXXX")"
trap 'rm -f "$RESULTS"' EXIT
CUR_ID=""; CUR_NAME=""

# 每门结果同时落一份 TSV，供 emit_json.py 转成机器可读结果。
# 文本给人看（可自由改措辞），TSV 给机器看（id/status 是契约，不许改）。
record() { [ -n "$CUR_ID" ] && printf '%s\t%s\t%s\t%s\n' "$CUR_ID" "$CUR_NAME" "$1" "$2" >> "$RESULTS"; }
ok()   { printf '  [PASS] %s\n' "$1"; record PASS "$1"; }
skip() { printf '  [SKIP] %s\n' "$1"; SKIPS=$((SKIPS + 1)); record SKIP "$1"; }
warn() { printf '  [WARN] %s\n' "$1"; WARNS=$((WARNS + 1)); record WARN "$1"; }
notice() { printf '  [WARN] %s\n' "$1"; WARNS=$((WARNS + 1)); }
bad()  { printf '  [FAIL] %s\n' "$1"; FAILS=$((FAILS + 1)); record FAIL "$1"; }

TEMPLATE=0
[ -f "$ROOT/.template" ] && TEMPLATE=1

# ── SKIP 活跃度：门1-3 连续 3 次 SKIP 提示启用（兼容 macOS bash 3.2，不用关联数组）
GSTATE="$ROOT/.gate_state"
g1=0; g2=0; g3=0
[ -f "$GSTATE" ] && . "$GSTATE"
skip_nudge() {   # $1 = 状态变量名，$2 = 门名
  eval "n=\${$1:-0}"; n=$((n + 1)); eval "$1=$n"
  if [ "$n" -ge 3 ]; then
    notice "$2 已连续 ${n} 次 SKIP——SKIP 不该是永久状态，建议配置后启用"
  fi
}
skip_reset() { eval "$1=0"; }

CUR_ID=input_validate; CUR_NAME="门1 输入校验"
echo "== 门1 输入校验（坏数据入口炸掉） =="
if [ -z "$DATA" ]; then
  skip "未提供 --data"; skip_nudge g1 "门1 输入校验"
elif [ ! -f "$DATA" ]; then
  bad "输入文件不存在: $DATA"; skip_reset g1
else
  if "$PY" "$CHECKS/validate.py" "$DATA"; then ok "输入校验通过"
  else bad "输入校验失败（见上）"; fi
  skip_reset g1
fi

CUR_ID=invariants; CUR_NAME="门2 业务勾稽断言"
echo "== 门2 业务勾稽断言 =="
if [ -z "$OUT" ]; then
  skip "未提供 --out"; skip_nudge g2 "门2 业务勾稽"
elif [ ! -d "$OUT" ]; then
  bad "输出目录不存在: $OUT"; skip_reset g2
else
  "$PY" "$CHECKS/check_invariants.py" "$OUT"; rc=$?
  case $rc in
    0) ok "勾稽断言全通过"; skip_reset g2;;
    2) skip "CHECKS 为空（尚未填业务勾稽）"; skip_nudge g2 "门2 业务勾稽";;
    *) bad "勾稽断言有违反"; skip_reset g2;;
  esac
fi

CUR_ID=baseline_diff; CUR_NAME="门3 双跑对比"
echo "== 门3 双跑对比（改坏没改坏，机器说了算） =="
if [ -z "$OUT" ]; then
  skip "未提供 --out"; skip_nudge g3 "门3 双跑对比"
elif [ ! -d "$ROOT/baseline/latest" ]; then
  skip "无基线（先跑 bash tools/make_baseline.sh）"; skip_nudge g3 "门3 双跑对比"
else
  if "$PY" "$CHECKS/compare.py" "$ROOT/baseline/latest" "$OUT"; then ok "与基线一致"
  else bad "与基线有差异（先归因：代码bug/数据问题/基准错/合理多解）"; fi
  skip_reset g3
fi

CUR_ID=index; CUR_NAME="门4 索引一致性"
echo "== 门4 索引一致性（BLOCKS/STATE/doc 编号） =="
if "$PY" "$CHECKS/index_check.py" "$ROOT" --index; then
  ok "索引未腐化"
elif [ "$TEMPLATE" = 1 ]; then
  warn "模板本体，示例索引尚未替换（实例化后必须清零）"
else
  bad "索引腐化，过期的索引比没有更糟"
fi

CUR_ID=placeholder; CUR_NAME="门5 占位符残留"
echo "== 门5 占位符残留 =="
if "$PY" "$CHECKS/index_check.py" "$ROOT" --placeholder; then
  ok "无残留占位符"
elif [ "$TEMPLATE" = 1 ]; then
  warn "模板本体自带占位符（实例化后必须替换；确属正常用法在行尾加 <!-- ok -->）"
else
  bad "仍有 [方括号] 占位符未替换为本项目实际值"
fi

CUR_ID=secrets; CUR_NAME="门6 密钥扫描"
echo "== 门6 密钥扫描 =="
if "$PY" "$CHECKS/secret_scan.py" "$ROOT"; then
  ok "无密钥泄漏"
else
  bad "疑似密钥/凭证泄漏（见上；确认误报可在 secret_scan.py 的 IGNORE 豁免或行尾加 # nosecret）"
fi

CUR_ID=budget; CUR_NAME="门7 上下文预算"
echo "== 门7 上下文预算 =="
if "$PY" "$CHECKS/context_budget.py" "$ROOT"; then
  ok "入口文件总量在预算内"
else
  bad "入口文件超出上下文预算——根目录是 AI 每会话的预算，超了就下沉到 doc/ 或 tools/"
fi

if [ "$WANT_JSON" = 1 ]; then
  echo "== 机器可读结果 =="
  if ! GATE_COMMAND="bash tools/run.sh $ORIGINAL_ARGS" "$PY" "$CHECKS/emit_json.py" "$RESULTS" "$ROOT" \
    --out "${JSON_OUT:-doc/health/last_gates.json}" --run-out "$OUT" --run-data "$DATA"; then
    echo "结果: ERROR（机器结果生成失败；旧结果不得作为本次依据）"
    exit 2
  fi
fi

if [ "$STATUS" = 1 ]; then
  echo "== STATE 草稿（人工确认后再写入） =="
  "$PY" "$CHECKS/index_check.py" "$ROOT" --status
fi

printf 'g1=%s\ng2=%s\ng3=%s\n' "$g1" "$g2" "$g3" > "$GSTATE"

echo
if [ "$FAILS" -gt 0 ]; then
  echo "结果: FAIL（$FAILS 门未过）→ 不许提交"
  exit 1
fi
if [ "$SKIPS" -gt 0 ] || [ "$WARNS" -gt 0 ]; then
  echo "结果: INCOMPLETE（${SKIPS} 门 SKIP，${WARNS} 条 WARN）→ 未完整验证，不等同全绿"
  exit 0
fi
echo "结果: PASS（七门全部实际通过）→ 可提交"
