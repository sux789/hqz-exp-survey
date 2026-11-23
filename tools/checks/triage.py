"""失败分诊单：把「哪一门红了」变成「下一步先做什么」，但**不下结论**。

用法:
  bash tools/ai.sh triage                  # 读 doc/health/last_gates.json → doc/health/TRIAGE.md
  bash tools/ai.sh triage --gates x.json   # 指定其他结果文件
  bash tools/ai.sh triage --stdout

设计意图（为什么不是「自动修复」）:
  无人值守巡检的价值是**把证据准备好**，不是替人判断。自动改代码/自动重跑基线，
  等于让机器替业务口径做决定——这类错误一旦发生，比红灯本身贵得多。
  所以本单只做三件事：列事实、给候选原因（标注非结论）、排处置顺序。
  结论必须回到 doc/NNN 迭代文档，并由人拍板（CONSTRAINTS C09）。
退出码: 0 已生成（含全绿）/ 2 用法错误或结果文件缺失。
"""
import json
import sys
from datetime import datetime
from pathlib import Path

REMEDY = {
    "input_validate": {
        "title": "输入校验",
        "why": ["输入字段改名/缺列 → 别名表未同步", "编码或分隔符变化（Excel 另存为 CSV）",
                "真实数据出现新边界值（空值、负数、重复键）"],
        "cmd": "python3 tools/checks/validate.py <data 文件>",
        "first": "用报错里的行号打开原文件看那一行，不要先改代码",
    },
    "invariants": {
        "title": "业务勾稽",
        "why": ["取整位置变了（源头 vs 展示层）", "汇总口径改了但断言未同步",
                "跨表引用改成重算，出现浮点尾差"],
        "cmd": "python3 tools/checks/check_invariants.py out/",
        "first": "先看哪条断言红、红在哪个数，再定位产生该数的函数",
    },
    "baseline_diff": {
        "title": "双跑对比",
        "why": ["真实行为变化（新功能/重构引入）", "基线本身是错的（改前就没验过）",
                "输出里的时间戳/随机数/路径导致伪差异"],
        "cmd": "python3 tools/checks/compare.py baseline/latest out/",
        "first": "先归因再动手：代码bug / 数据问题 / 基准错 / 合理多解，四选一写下来",
    },
    "index": {
        "title": "索引一致性",
        "why": ["BLOCKS 引用的文件被删或改名", "STATE 指向的迭代文档不存在", "doc 编号断档"],
        "cmd": "python3 tools/checks/index_check.py . --index",
        "first": "过期的索引比没有更糟：先修引用，再继续开发",
    },
    "placeholder": {
        "title": "占位符残留",
        "why": ["新项目实例化后未替换 [方括号]", "新增模板段落带进未填字段"],
        "cmd": "python3 tools/checks/index_check.py . --placeholder",
        "first": "逐条替换为项目实际值；确属正常用法才加 <!-- ok -->",
    },
    "secrets": {
        "title": "密钥扫描",
        "why": ["真实凭证被写进源码/配置", "示例文件用了长得像真 key 的假串",
                "扫描规则过宽命中普通长字符串"],
        "cmd": "python3 tools/checks/secret_scan.py .",
        "first": "先假定是真泄漏：立即轮换该凭证，再处理仓库与历史；确认误报才加 # nosecret",
    },
    "budget": {
        "title": "上下文预算",
        "why": ["入口文件持续加细则", "把本该进 doc/ 的决策史写进根目录"],
        "cmd": "python3 tools/checks/context_budget.py .",
        "first": "下沉而非删除：细则进 doc/，脚本进 tools/，入口只留索引",
    },
}
ORDER = ["input_validate", "invariants", "baseline_diff", "secrets", "index", "placeholder", "budget"]


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    root = Path(argv[1]).resolve()
    gp = Path(argv[argv.index("--gates") + 1]) if "--gates" in argv else root / "doc/health/last_gates.json"
    if not gp.is_absolute():
        gp = root / gp
    if not gp.exists():
        print(f"没有巡检结果: {gp}\n先跑: bash tools/run.sh --json（或 bash tools/ai.sh watch --once）")
        return 2
    data = json.loads(gp.read_text(encoding="utf-8"))
    fails = [g for g in data.get("gates", []) if g["status"] == "FAIL"]
    out = root / "doc/health/TRIAGE.md"

    if not fails:
        if out.exists():
            out.unlink()
            print("最近一次巡检全绿，已移除过期的 doc/health/TRIAGE.md（避免下次会话被旧问题误导）")
        else:
            print("最近一次巡检全绿，无需分诊")
        return 0

    fails.sort(key=lambda g: ORDER.index(g["id"]) if g["id"] in ORDER else 99)
    L = []
    A = L.append
    A(f"# 巡检分诊单 · {root.name}")
    A("")
    A(f"> {datetime.now().strftime('%Y-%m-%d %H:%M')} 自动生成 ｜ 来源 `{gp.relative_to(root)}`（{data.get('ts', '?')}）")
    A(f"> 结论：**{len(fails)} 门 FAIL** / 共 {len(data.get('gates', []))} 门 ｜ 本单只列事实与候选原因，**不含结论**")
    A("")
    A("## 1 失败事实")
    A("")
    A("| 顺序 | 门 | 机器输出 | 复现命令 |")
    A("|---|---|---|---|")
    for i, g in enumerate(fails, 1):
        r = REMEDY.get(g["id"], {})
        A(f"| {i} | {g['name']} | {g['detail']} | `{r.get('cmd', '见 run.sh')}` |")
    A("")
    A("## 2 候选原因（概率降序，均为假设）")
    for i, g in enumerate(fails, 1):
        r = REMEDY.get(g["id"], {"why": ["未登记的门——先在 triage.py 的 REMEDY 里补一条"], "first": "按 run.sh 输出的最后一行定位"})
        A("")
        A(f"### {i}. {g['name']}")
        for w in r["why"]:
            A(f"- {w}")
        A(f"- **第一步**：{r['first']}")
    A("")
    A("## 3 处置顺序")
    A("")
    A("1. 先修**上游门**（输入 → 勾稽 → 对比）：下游红往往是上游脏数据造成的假象。")
    A("2. 密钥类失败立刻处理，不等这一版做完。")
    A("3. 基线差异未归因前，不要重建基线——那等于把错误固化成标准。")
    A("")
    A("## 4 交给 AI 的开场指令（复制即用）")
    A("")
    A("```text")
    A("读 doc/health/TRIAGE.md 与 doc/health/last_gates.json，先复现失败门，不要猜。")
    A("对每个 FAIL 门：给根因假设（≤2 个）+ 支撑证据（命令输出/文件:行号）+ 修复方案 + 影响面。")
    A("禁止：自动改 data/ 或 baseline/、自动改业务口径、用 --no-verify 绕过。")
    A("拿不准的列待确认清单（问题/候选/建议/依据），不替人做决定。")
    A("修完跑 bash tools/run.sh --out out/ --json，并在 doc/NNN 迭代文档写明结论与反转记录。")
    A("```")
    A("")
    A("## 5 边界")
    A("")
    A("- 本单是派生视图，禁止手改；下次巡检会覆盖（C08/C11）。")
    A("- 「候选原因」不是诊断结论；真正的归因写进 `doc/NNN-版本_主题.md`。")
    A("- 巡检失败不等于代码错：也可能是基线过期、用例变了、环境缺依赖（先看 doctor.sh）。")

    text = "\n".join(L) + "\n"
    if "--stdout" in argv:
        print(text)
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"分诊单: {out.relative_to(root)} ｜ {len(fails)} 门 FAIL：" + "、".join(g["name"] for g in fails))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
