"""上下文预算：AI「每会话必读」的入口文件总大小超预算即 FAIL。作为 run.sh 门7 运行。
用法: python tools/checks/context_budget.py 项目根目录 [--budget-kb N]（默认 24KB）
退出码: 0 预算内 / 1 超预算 / 2 用法错误。

口径 = AGENTS.md 的「必读」清单（6 个文件），**不含** README.md / deploy.sh：
  README 是仓库门面，不是每会话上下文档；为让某个文件过关而扩张口径或调高预算值
  = 给门量体裁衣，闸门就失去意义（见 CONSTRAINTS C06）。
  但口径外 ≠ 隐形——本脚本会把它们连同体积一并报出来，只是不据此阻断，交人工评审。

思想：根目录 = AI 每会话的上下文预算。入口文件每多 1KB，每次会话都多烧一遍 token。
超了不是删内容，是下沉——细则进 doc/，脚本进 tools/，历史进 doc/。"""
import sys
from pathlib import Path

# 口径内：AGENTS.md 强制 AI 每会话读的清单
FILES = ["AGENTS.md", "AI_INSTRUCTIONS.md", "CONSTRAINTS.md",
         "BLOCKS.md", "STATE.md", "GLOSSARY.md"]
# 口径外但仍属「根目录文本入口」：报出体积，不判定（见 CONSTRAINTS C06）
OUT_OF_SCOPE = ["README.md", "deploy.sh"]


def measure(root: Path, names: list):
    """返回 (合计字节, 明细行列表)。"""
    total, rows = 0, []
    for name in names:
        p = root / name
        if p.exists():
            n = p.stat().st_size
            total += n
            rows.append((name, n))
    return total, rows


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    root = Path(sys.argv[1])
    budget = 24 * 1024
    if "--budget-kb" in sys.argv:
        i = sys.argv.index("--budget-kb")
        budget = int(sys.argv[i + 1]) * 1024

    total, rows = measure(root, FILES)
    outside, out_rows = measure(root, OUT_OF_SCOPE)
    for name, n in rows:
        print(f"  {name:22s} {n / 1024:5.1f} KB")
    print("  " + "-" * 30)
    print(f"  入口文件合计 {total / 1024:.1f} KB / 预算 {budget // 1024} KB")
    for name, n in out_rows:
        print(f"  (口径外) {name:19s} {n / 1024:5.1f} KB")
    if out_rows:
        print(f"  (口径外) 合计 {outside / 1024:.1f} KB —— 本门只管必读文件；"
              f"README / deploy.sh 的膨胀靠 STATE.md 资产活跃度表人工评审")
    if total > budget:
        print("超出上下文预算：把细则下沉到 doc/ 或 tools/，入口只留索引")
        sys.exit(1)
    sys.exit(0)
