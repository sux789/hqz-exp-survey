"""AI Agent 能力发现、积木上下文和流程生成（只读，不自动执行）。

用法:
  python tools/checks/agent.py . capabilities [--json]
  python tools/checks/agent.py . context B1 [--json]
  python tools/checks/agent.py . plan [--json]
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.project import (constraints, load_gates, real_blocks,  # noqa: E402
                         topological_blocks)

COMMANDS = [
    {"id": "brief", "command": "bash tools/ai.sh brief", "purpose": "恢复跨会话状态", "output": "doc/brief.md", "writes": True},
    {"id": "capabilities", "command": "bash tools/ai.sh capabilities --json", "purpose": "发现稳定命令与产物契约", "output": "stdout", "writes": False},
    {"id": "context", "command": "bash tools/ai.sh context <B编号> --json", "purpose": "只读取当前积木所需上下文", "output": "stdout", "writes": False},
    {"id": "plan", "command": "bash tools/ai.sh plan --json", "purpose": "由 BLOCKS 依赖生成执行流程与人工检查点", "output": "stdout", "writes": False},
    {"id": "gates", "command": "bash tools/ai.sh gates --out out/ --data <真实输入>", "purpose": "执行七门并生成唯一机器事实", "output": "doc/health/last_gates.json", "writes": True},
    {"id": "explain", "command": "bash tools/ai.sh explain", "purpose": "把 diff 转成人可审的风险与问题", "output": "doc/review.md", "writes": True},
    {"id": "triage", "command": "bash tools/ai.sh triage", "purpose": "准备失败证据，不自动归因或修复", "output": "doc/health/TRIAGE.md", "writes": True},
    {"id": "watch", "command": "bash tools/ai.sh watch --once", "purpose": "CI/计划任务单次巡检", "output": "doc/health/", "writes": True},
    {"id": "dashboard", "command": "bash tools/align.sh --open", "purpose": "刷新并打开人类指挥看板", "output": "doc/align.html", "writes": True},
]
GUARDRAILS = [
    "AI 可读取、实现和验证；不得自动改业务口径、真实输入或基线。",
    "FAIL 先复现与归因；INCOMPLETE 表示有 SKIP/WARN，不等于全绿。",
    "高风险改动、基线重建、发布与业务口径变化必须由人确认。",
    "plan 只生成流程，不启动进程、不自动执行命令。",
]


def changed_files(root):
    try:
        r = subprocess.run(("git", "status", "--porcelain"), cwd=root,
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0:
        return []
    return [line[3:] for line in r.stdout.splitlines() if len(line) > 3]


def capabilities(root):
    return {
        "schema_version": 1,
        "project": Path(root).name,
        "commands": COMMANDS,
        "result_contract": {
            "path": "doc/health/last_gates.json", "schema_version": 2,
            "overall": ["PASS", "FAIL", "INCOMPLETE"],
            "gate_status": ["PASS", "FAIL", "WARN", "SKIP"],
        },
        "guardrails": GUARDRAILS,
    }


def context(root, block_id):
    blocks = real_blocks(root)
    by_id = {b["id"]: b for b in blocks}
    if block_id not in by_id:
        raise ValueError(f"未知积木 {block_id}；可用: {', '.join(by_id) or '（尚无真实积木）'}")
    block = by_id[block_id]
    related_ids = set(block["depends_on"])
    related = [by_id[x] for x in block["depends_on"] if x in by_id]
    cons = constraints(root)
    relevant = [c for c in cons if c["id"] in ("C02", "C08", "C09")
                or (block["file"] and block["file"] in c["text"])]
    gates = load_gates(root) or {}
    failures = [{"id": g.get("id"), "name": g.get("name"), "detail": g.get("detail")}
                for g in gates.get("gates", []) if g.get("status") == "FAIL"]
    files = changed_files(root)
    return {
        "schema_version": 1,
        "project": Path(root).name,
        "block": block,
        "dependencies": related,
        "dependents": [{"id": b["id"], "duty": b["duty"]} for b in blocks
                       if block_id in b["depends_on"]],
        "constraints": relevant,
        "active_failures": failures,
        "changed_files": [f for f in files if f == block["file"] or f.startswith(block["file"] + "/")],
        "suggested_commands": [
            f"bash tools/ai.sh context {block_id} --json",
            "bash tools/ai.sh gates --out out/ --data <真实输入>",
            "bash tools/ai.sh explain",
        ],
        "missing_dependencies": sorted(related_ids - set(by_id)),
        "guardrails": GUARDRAILS,
    }


def plan(root):
    blocks = real_blocks(root)
    ordered, cyclic = topological_blocks(blocks)
    if not ordered:
        steps = [
            {"order": 1, "id": "facts", "owner": "human+agent", "action": "填写项目事实、真实输入与输出契约", "verify": "检查 AI_INSTRUCTIONS.md / STATE.md"},
            {"order": 2, "id": "mvp", "owner": "agent", "action": "用真实输入跑通最小端到端 MVP", "verify": "运行项目真实命令"},
            {"order": 3, "id": "blocks", "owner": "human+agent", "action": "按职责登记 BLOCKS.md 及依赖", "verify": "bash tools/ai.sh plan --json"},
            {"order": 4, "id": "baseline", "owner": "human", "action": "确认输出正确后建立基线", "verify": "bash tools/make_baseline.sh"},
        ]
        mode = "bootstrap"
    else:
        steps = []
        for i, b in enumerate(ordered, 1):
            steps.append({
                "order": i, "id": b["id"], "owner": "agent",
                "action": f"实现或复核「{b['duty']}」",
                "file": b["file"], "input": b["input"], "output": b["output"],
                "depends_on": b["depends_on"],
                "context": f"bash tools/ai.sh context {b['id']} --json",
                "human_checkpoint": "确认输入/输出契约与业务口径，再允许进入下游",
            })
        mode = "block_flow"
    steps.append({"order": len(steps) + 1, "id": "delivery", "owner": "agent+human",
                  "action": "完整验证、差异归因、评审并更新状态",
                  "verify": "bash tools/ai.sh gates --out out/ --data <真实输入> && bash tools/ai.sh explain",
                  "human_checkpoint": "确认 HIGH 风险、预期差异、文档和发布决定"})
    return {
        "schema_version": 1, "project": Path(root).name, "mode": mode,
        "steps": steps, "cyclic_blocks": cyclic,
        "dashboard": "bash tools/align.sh --open", "guardrails": GUARDRAILS,
    }


def print_human(data):
    if "commands" in data:
        print(f"项目: {data['project']} ｜ 结果契约: schema v2")
        for c in data["commands"]:
            print(f"{c['id']:<13} {c['command']}\n              {c['purpose']} → {c['output']}")
    elif "block" in data:
        b = data["block"]
        print(f"{b['id']} {b['duty']}\n文件: {b['file']}\n输入: {b['input']}\n输出: {b['output']}\n依赖: {b['depends_on_text']}")
        print("约束: " + (", ".join(c["id"] for c in data["constraints"]) or "无"))
        print("活动 FAIL: " + (", ".join(g["id"] for g in data["active_failures"]) or "无"))
    else:
        print(f"项目: {data['project']} ｜ 模式: {data['mode']}")
        for s in data["steps"]:
            print(f"{s['order']}. [{s['owner']}] {s['id']}: {s['action']}")
            if s.get("human_checkpoint"):
                print(f"   人工检查点: {s['human_checkpoint']}")
        if data["cyclic_blocks"]:
            print("循环依赖: " + ", ".join(data["cyclic_blocks"]))


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    root, command = Path(argv[1]).resolve(), argv[2]
    try:
        if command == "capabilities":
            data = capabilities(root)
        elif command == "context":
            if len(argv) < 4 or argv[3].startswith("--"):
                print("context 需要积木编号，例如 B1")
                return 2
            data = context(root, argv[3])
        elif command == "plan":
            data = plan(root)
        else:
            print(f"未知 Agent 能力: {command}")
            return 2
    except ValueError as exc:
        print(str(exc))
        return 2
    if "--json" in argv:
        print(json.dumps(data, ensure_ascii=False, indent=1))
    else:
        print_human(data)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
