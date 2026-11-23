#!/bin/bash
# tools/init.sh — 从模板实例化新项目：复制 → 按档裁剪 → 去模板标记 → git init → 装提交前闸门。
#
# 用法:
#   bash tools/init.sh <目标目录> [--tier=L0|L1|L2] [--no-git]
#
#   L0 极简   AGENTS + AI_INSTRUCTIONS + STATE + doc 模板（一次性脚本/原型验证用）
#   L1 标准   + CONSTRAINTS / BLOCKS / GLOSSARY + tools/（默认，覆盖绝大多数项目）
#   L2 长期   + tools/schedule/ 每日体检计划任务（>3 个月或服务化项目）
set -euo pipefail

TIER=L1; GIT=1; DEST=""
for a in "$@"; do
  case "$a" in
    --tier=*) TIER="${a#*=}";;
    --no-git) GIT=0;;
    -h|--help) sed -n '2,11p' "$0"; exit 0;;
    -*) echo "未知参数: ${a}（-h 看用法）"; exit 2;;
    *) DEST="$a";;
  esac
done

SRC="$(cd "$(dirname "$0")/.." && pwd)"

if [ -z "$DEST" ]; then
  echo "用法: bash tools/init.sh <目标目录> [--tier=L0|L1|L2] [--no-git]"
  exit 2
fi
case "$TIER" in L0|L1|L2) ;; *) echo "tier 只能是 L0 / L1 / L2"; exit 2;; esac

if [ -e "$DEST" ] && [ -n "$(ls -A "$DEST" 2>/dev/null || true)" ]; then
  echo "目标目录已存在且非空: $DEST"; exit 1
fi

mkdir -p "$DEST"
DEST="$(cd "$DEST" && pwd)"
if [ "$DEST" = "$SRC" ]; then
  echo "目标目录不能是模板自身"; exit 1
fi

echo "模板: $SRC"
echo "目标: $DEST"
echo "档位: $TIER"

rsync -a \
  --exclude '.git/' --exclude '__pycache__/' --exclude '.workbuddy/' \
  --exclude 'baseline/' --exclude 'out/' --exclude '.DS_Store' \
  --exclude '.gate_state' --exclude 'tools/selftest.sh' \
  --exclude 'doc/brief.md' --exclude 'doc/review.md' \
  --exclude 'doc/health/' --exclude 'doc/align.html' \
  "$SRC/" "$DEST/"

rm -f "$DEST/.template"
rm -rf "$DEST/__pycache__"

# 生成「属于本项目」的 README —— 不是模板自述文档。
# 为什么必须换：模板根的 README 讲的是「模板怎么实例化」，对新项目 90% 是噪音；
# 而 README 不在门7 口径内（见 CONSTRAINTS C06），留着就再没人管它（见 CONSTRAINTS C03/D6）。
write_project_readme() {   # $1 = 档位标签  $2 = 1 表示本档带 tools 工具链
  {
    printf '# 项目说明（%s）\n\n' "${1}"
    cat <<'EOF'
> 由 project-template 实例化。**这份 README 属于本项目，不是模板说明书** ——
> 模板自身的用法见模板仓库 README；方法论见 `doc/000-…手册.md`（参考手册，按需查第 6 章诊断表）。

## 这个项目是什么

- **业务一句话**：<!-- 待填 -->
- **输入**：<!-- 格式 / 来源 / 示例路径 -->
- **输出**：<!-- 格式 / 去向 / 示例路径 -->
EOF
    if [ "${2}" = "1" ]; then
      cat <<'EOF'

## 怎么跑

```bash
python main.py --data data/x.csv --out out/     # 换成本项目真实运行命令
```

## 改完怎么验证（一条命令全绿才提交）

```bash
bash tools/run.sh --out out/ --json   # 七门闸门；判据见 AI_INSTRUCTIONS.md 的 DOD 表
```

## 开工 / 交付 / 排障

```bash
bash tools/ai.sh brief     # 会话开场简报（4KB 事实卡，AI 每会话第一读）
bash tools/ai.sh explain   # 改动评审单（风险 / 约束 / 必跑验证 / 待人拍板的问题）
bash tools/ai.sh watch     # 无人值守巡检（--once 可进 cron/CI；失败出分诊单）
```
EOF
    fi
    cat <<'EOF'

## 开工三步

1. 真实输入放进 `data/`（正常 + 边界 + 会报错 三类；mock 数据不算数）
2. 替换方括号占位符：`AI_INSTRUCTIONS.md` / `STATE.md`
3. 视档位补填：`GLOSSARY.md`（术语）、`CONSTRAINTS.md`（第一条约束出现时）、`BLOCKS.md`（MVP 跑通后）

> `AGENTS.md` 不用填 —— 按你的 AI 工具接适配器即可（文件内有说明）。
> AI 每会话的第一条命令固定是 `bash tools/ai.sh brief`，不要让它通读根目录。
EOF
  } > "$DEST/README.md"
}

case "$TIER" in
  L0)
    rm -f "$DEST/CONSTRAINTS.md" "$DEST/BLOCKS.md" "$DEST/GLOSSARY.md" "$DEST/deploy.sh"
    rm -rf "$DEST/tools"
    rm -rf "$DEST/baseline"
    mkdir -p "$DEST/data"
    cat > "$DEST/AGENTS.md" <<'EOF'
# AGENTS — AI 代理入口（自动加载 · L0 极简档）

> 适配器：Claude Code 用 `ln -s AGENTS.md CLAUDE.md`；Cursor 旧版复制到 `.cursor/rules/project.mdc`；TRAE 复制到 `.trae/rules/project.md`。

## 每次会话开工前必读

1. `AI_INSTRUCTIONS.md` — 协作协议与铁律
2. `STATE.md` — 当前状态与已知问题

## 每版收尾

更新 `STATE.md`；写 `doc/NNN-版本_主题.md`（模板见 doc/001）。
EOF
    write_project_readme "L0 极简" 0
    cat >> "$DEST/README.md" <<'EOF'

## 什么时候该升到 L1

出现下列任一情况：① 输出要双跑对比才能确认没改坏；② 同一个错误犯第二次；
③ 同一人工动作重复第 3 次；④ 有别人或未来的 AI 要接手。

升级方法：用模板重新生成一份 L1 结构，把代码与 `data/` 搬过去即可（判据见模板 `doc/000` 手册第 13 章）。
EOF
    ;;
  L1)
    rm -rf "$DEST/tools/schedule"
    write_project_readme "L1 标准" 1
    ;;
  L2)
    write_project_readme "L2 长期" 1
    cat >> "$DEST/README.md" <<'EOF'

## 每日体检 / 无人值守巡检（L2 已带）

```bash
bash tools/schedule/setup.sh --dry-run                          # 先看将写入的计划任务
bash tools/schedule/setup.sh --install --hour=9 --minute=30      # 每日体检
bash tools/schedule/setup.sh --install --watch --every=300       # 每 5 分钟巡检（批处理，非常驻）
```
EOF
    ;;
esac

if [ "$GIT" = 1 ]; then
  git -C "$DEST" init -q
  if [ "$TIER" != "L0" ]; then
    git -C "$DEST" config core.hooksPath tools/hooks
    echo "已装提交前闸门: core.hooksPath = tools/hooks"
  fi
fi

echo
echo "完成。下一步："
if [ "$GIT" = 1 ] && [ "$TIER" != "L0" ]; then
  echo "  0) 首次入库（此时占位符未替换，门5 会拦，仅首次允许跳过闸门）:"
  echo "       git add -A && git commit --no-verify -m \"init: 模板基线\""
  echo "     之后所有提交走正常闸门，不再 --no-verify"
fi
echo "  1) 放 ≥3 份真实输入进 data/（正常 + 边界 + 会报错 三类）"
if [ "$TIER" = "L0" ]; then
  echo "  2) 替换 [方括号] 占位符：AI_INSTRUCTIONS.md / STATE.md"
  echo "  3) 跑通 MVP 后写 doc/001 首篇迭代文档"
else
  echo "  2) 替换 [方括号] 占位符：AI_INSTRUCTIONS.md / STATE.md"
  echo "     并删掉 CONSTRAINTS.md / BLOCKS.md / GLOSSARY.md 里的（示例）行"
  echo "     AGENTS.md 不用填 —— 按你的 AI 工具接适配器即可"
  echo "  3) 填 README.md 的「这个项目是什么」（现为模板生成的项目版骨架）"
  echo "  4) 跑通 MVP 后存基线: bash tools/make_baseline.sh"
  echo "  5) 提交前一条命令验证: bash tools/run.sh --out out/"
fi
if [ "$TIER" = "L2" ]; then
  echo "  6) 装每日体检（可选）: bash tools/schedule/setup.sh --dry-run"
fi
