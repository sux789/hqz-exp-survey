#!/bin/bash
# tools/doctor.sh — 环境自检：新项目第一天 / 换机器 / 出问题先跑它。
# 检查运行本模板所需的工具与依赖，逐项给出补救命令。
# 退出码: 0 核心依赖齐全 / 1 核心依赖缺失（python3 或 git）
set -uo pipefail

FAILS=0
ok()   { printf '  [ OK ] %s\n' "$1"; }
warn() { printf '  [WARN] %s\n' "$1"; }
bad()  { printf '  [FAIL] %s\n' "$1"; FAILS=$((FAILS + 1)); }

echo "== 核心依赖 =="
if command -v python3 >/dev/null 2>&1; then
  ok "python3: $(python3 --version 2>&1)"
else
  bad "缺 python3 → 安装: https://www.python.org/ 或 brew install python"
fi

if command -v git >/dev/null 2>&1; then
  ok "git: $(git --version 2>&1)"
else
  bad "缺 git → 安装: brew install git 或系统包管理器"
fi

echo "== 推荐依赖 =="
if python3 -c "import openpyxl" 2>/dev/null; then
  ok "openpyxl: $(python3 -c 'import openpyxl; print(openpyxl.__version__)' 2>/dev/null)（Excel 输出项目必需）"
else
  warn "缺 openpyxl → Excel 项目的 compare/断言会失败；CSV/文本项目可忽略。安装: pip install openpyxl"
fi

if command -v rsync >/dev/null 2>&1; then
  ok "rsync: 有（init.sh 与 deploy.sh 需要）"
else
  warn "缺 rsync → init.sh / deploy.sh 会失败（macOS/Linux 一般自带）"
fi

echo "== 模板自检 =="
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -x "$ROOT/tools/run.sh" ]; then
  ok "tools/run.sh 可执行"
else
  warn "tools/run.sh 不可执行或缺失 → chmod +x tools/*.sh"
fi

echo
if [ "$FAILS" -gt 0 ]; then
  echo "结果: $FAILS 项核心依赖缺失，先补齐再开工"
  exit 1
fi
echo "结果: 环境就绪"
