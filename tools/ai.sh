#!/bin/bash
# tools/ai.sh — 给 AI 与「要审 AI 的人」用的统一入口（子命令制，避免顶层脚本膨胀）。
#
# 用法:
#   bash tools/ai.sh brief                 # 会话开场简报 → doc/brief.md（≤4KB）
#   bash tools/ai.sh capabilities [--json] # Agent 发现可用命令、产物与安全边界
#   bash tools/ai.sh context B1 [--json]   # 只取某积木的契约、依赖、约束和失败
#   bash tools/ai.sh plan [--json]         # 由 BLOCKS 依赖生成执行流与人工检查点
#   bash tools/ai.sh explain [--since REF] # 改动评审单 → doc/review.md（人看 AI 改了什么）
#   bash tools/ai.sh triage                # 把最近一次 FAIL 变成待办单 → doc/health/TRIAGE.md
#   bash tools/ai.sh watch [--once]        # 无人工位巡检：文件一改就跑闸门，失败即分诊
#   bash tools/ai.sh gates [run.sh 参数]   # 等价 bash tools/run.sh --json ...
#
# 为什么是子命令而不是 4 个新脚本：
#   顶层入口每多一个，AI 每会话的「工具选择成本」就多一分，README 的资产纪律也会失控。
#   一个入口 + 稳定动词 = 人记得住、AI 猜得到、文档只用写一处。
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-python3}"
CMD="${1:-}"; shift 2>/dev/null || true

case "$CMD" in
  brief)
    exec "$PY" "$ROOT/tools/checks/brief.py" "$ROOT" "$@"
    ;;
  capabilities|context|plan)
    exec "$PY" "$ROOT/tools/checks/agent.py" "$ROOT" "$CMD" "$@"
    ;;
  explain)
    exec "$PY" "$ROOT/tools/checks/explain.py" "$ROOT" "$@"
    ;;
  triage)
    exec "$PY" "$ROOT/tools/checks/triage.py" "$ROOT" "$@"
    ;;
  watch)
    exec "$PY" "$ROOT/tools/checks/watch_loop.py" "$ROOT" "$@"
    ;;
  gates)
    exec bash "$ROOT/tools/run.sh" --json "$@"
    ;;
  -h|--help|help|"")
    sed -n '2,16p' "$0"
    [ -z "$CMD" ] && exit 2
    exit 0
    ;;
  *)
    echo "未知子命令: ${CMD}（bash tools/ai.sh -h 看用法）"
    exit 2
    ;;
esac
