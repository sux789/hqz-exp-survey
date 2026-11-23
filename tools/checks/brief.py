"""会话简报：把「AI 每次开工要读的 6 个文件 + 昨天发生了什么」压成一份 ≤4KB 的事实卡。

用法:
  bash tools/ai.sh brief           # 生成 doc/brief.md 并打印到终端
  python tools/checks/brief.py .   # 同上（底层）
  python tools/checks/brief.py . --json   # 机器可读

设计意图（为什么不直接读 6 个文件）:
  AI 跨会话失忆，每次会话靠「重读全部入口文件」恢复上下文——代价是 15~24KB token，
  而且读得越多越容易漏掉最关键的 3 条（当前 FAIL、下一步、刚踩的约束）。
  简报把**状态**压到 4KB 以内，把**细节**留在原文件按需回查：
    状态（会变）→ 简报；规则（不常变）→ CONSTRAINTS/BLOCKS；历史（只在追溯时看）→ doc/。
  它是**派生视图**：只读其他文件与 last_gates.json，不产生任何新事实（见 CONSTRAINTS C08）。
退出码: 0 正常 / 2 用法错误。
"""
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.project import source_fingerprint  # noqa: E402

MAX_BYTES = 4096
STATE_KEYS = ["版本", "更新", "能跑", "已知问题", "下一步", "最近迭代文档", "活跃约束"]


def sh(root: Path, *args):
    try:
        r = subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def state_fields(root: Path):
    """解析 STATE.md 的 `- **键**：值` 行；一行里用 ｜ 分隔多个字段时逐段解析。"""
    out = {}
    for line in read(root / "STATE.md").splitlines():
        s = line.strip()
        if not s.startswith("- "):
            continue
        for seg in re.split(r"[｜|]", s[2:]):
            m = re.match(r"^\s*\*\*(.+?)\*\*\s*[：:]\s*(.+)$", seg.strip())
            if m:
                out[m.group(1).strip()] = m.group(2).strip()
    return out


def latest_gates(root: Path):
    p = root / "doc/health/last_gates.json"
    if not p.exists():
        return None
    try:
        return json.loads(read(p))
    except json.JSONDecodeError:
        return {"overall": "UNKNOWN", "gates": [], "counts": {}, "ts": "?"}


def constraints(root: Path):
    rows = []
    for line in read(root / "CONSTRAINTS.md").splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 3 or not re.fullmatch(r"C\d{2,3}", cells[0]):
            continue
        text = re.sub(r"\s+", " ", cells[1])
        text = re.sub(r"`([^`]*)`", r"\1", text)
        rows.append((cells[0], text))
    return rows


def blocks(root: Path):
    ids = []
    for line in read(root / "BLOCKS.md").splitlines():
        s = line.strip()
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if cells and re.fullmatch(r"B\d{1,3}", cells[0]):
                ids.append(cells[0])
    return ids


def docs(root: Path):
    items = sorted(p.name for p in (root / "doc").glob("*.md")) if (root / "doc").exists() else []
    numbered = [n for n in items if re.match(r"\d{3}-", n)]
    return numbered[-1] if numbered else "无", len(numbered)


def build(root: Path):
    st = state_fields(root)
    g = latest_gates(root)
    cons = constraints(root)
    bl = blocks(root)
    latest_doc, n_docs = docs(root)
    dirty = sh(root, "git", "status", "--porcelain")
    n_dirty = len([x for x in dirty.splitlines() if x.strip()]) if dirty else 0
    branch = (sh(root, "git", "rev-parse", "--abbrev-ref", "HEAD")
              or sh(root, "git", "branch", "--show-current")
              or ("（空仓库，尚无提交）" if (root / ".git").exists() else "（未初始化 git）"))
    last_commit = sh(root, "git", "log", "-1", "--format=%h %s (%cr)") or "无提交"
    numstat = sh(root, "git", "diff", "HEAD", "--numstat")
    added = deleted = 0
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
            added += int(parts[0]); deleted += int(parts[1])
    if n_dirty and added == 0 and deleted == 0:
        changed = f"{n_dirty} 个文件（空仓库，尚无 diff 基线）"
    else:
        changed = f"{n_dirty} 个文件（+{added}/-{deleted}）"

    has_baseline = (root / "baseline/latest").exists()
    has_tests = (root / "tests/run_all.sh").exists() or (root / "tests").exists()
    n_data = len([p for p in (root / "data").glob("*") if p.is_file()]) if (root / "data").exists() else 0
    triage = root / "doc/health/TRIAGE.md"
    gate_stale = bool(g and g.get("source_hash") and
                      g.get("source_hash") != source_fingerprint(root))

    fails = [x for x in (g or {}).get("gates", []) if x.get("status") == "FAIL"]
    todo = []
    for f in fails:
        todo.append(f"[FAIL] {f['name']}：{f['detail']}")
    if gate_stale:
        todo.append("[结果陈旧] 源码或输入已在最近闸门后变化；重跑 bash tools/ai.sh gates")
    if (g or {}).get("overall") == "INCOMPLETE":
        todo.append("[未完整验证] 有 SKIP/WARN；不能当作七门全绿")
    if n_dirty:
        todo.append(f"[未提交] {changed}，提交前跑 explain 复核")
    if not has_baseline:
        todo.append("[缺基线] 未存基线 → 门3 永远 SKIP；先跑 bash tools/make_baseline.sh")
    if triage.exists():
        todo.append("[待分诊] doc/health/TRIAGE.md 有无人值守巡检留下的失败，先看它")
    nxt = st.get("下一步", "").strip()
    if nxt:
        todo.append(f"[STATE 下一步] {nxt}")

    return {
        "project": root.name,
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "version": st.get("版本", "未填"),
        "updated": st.get("更新", "未填"),
        "overall": (g or {}).get("overall", "未跑"),
        "gate_ts": (g or {}).get("ts", "-"),
        "gate_stale": gate_stale,
        "fails": fails,
        "dirty": {"files": n_dirty, "added": added, "deleted": deleted,
                  "branch": branch, "text": changed},
        "last_commit": last_commit,
        "constraints": cons,
        "blocks": bl,
        "latest_doc": latest_doc,
        "n_docs": n_docs,
        "baseline": has_baseline,
        "tests": has_tests,
        "n_data": n_data,
        "known": st.get("已知问题", ""),
        "todo": todo,
    }


def render(d):
    L = []
    A = L.append
    A(f"# 会话简报 · {d['project']}")
    A("")
    A(f"> {d['ts']} 自动生成 ｜ `bash tools/ai.sh brief` 刷新 ｜ **派生视图，勿手改**")
    A("")
    A("## 现在（先看这 3 行）")
    gate_txt = f"**{d['overall']}**"
    if d["fails"]:
        gate_txt += " → " + "；".join(f"{f['name']}" for f in d["fails"])
    A(f"- 闸门：{gate_txt}（最近一次 {d['gate_ts']}{'；结果已陈旧' if d['gate_stale'] else ''}）")
    dirty = d["dirty"]
    A(f"- 工作区：{dirty['text']} ｜ 分支 `{dirty['branch']}`")
    A(f"- 版本：{d['version']} ｜ 更新 {d['updated']}")
    A("")
    A("## 必须知道（按优先级）")
    if d["todo"]:
        for i, t in enumerate(d["todo"][:6], 1):
            A(f"{i}. {t}")
    else:
        A("1. 无阻断项：门全绿、工作区干净——可以按 STATE 下一步开工。")
    if d["known"]:
        A(f"{len(d['todo'][:6]) + 1}. 已知问题：{d['known']}")
    A("")
    A(f"## 硬约束速查（共 {len(d['constraints'])} 条，改代码前扫一眼；全表 CONSTRAINTS.md）")
    if d["constraints"]:
        A("")
        A("| 编号 | 一句话 |")
        A("|---|---|")
        shown = d["constraints"] if len(d["constraints"]) <= 8 else d["constraints"][-6:]
        for cid, text in shown:
            if len(text) > 78:
                text = text[:76] + "…"
            A(f"| {cid} | {text} |")
        if len(d["constraints"]) > 8:
            A(f"\n> 仅列最近 6 条；全部 {len(d['constraints'])} 条（{d['constraints'][0][0]}–{d['constraints'][-1][0]}）见 CONSTRAINTS.md")
    else:
        A("（尚未登记约束——第一条教训出现时立刻写进来）")
    A("")
    bl = d["blocks"]
    A("## 坐标")
    A(f"- 积木：{len(bl)} 个{'（' + bl[0] + '…' + bl[-1] + '）' if bl else '（MVP 跑通后盘点填写）'}")
    A(f"- 迭代文档：{d['n_docs']} 篇，最新 `doc/{d['latest_doc']}`")
    A(f"- 真实用例：{d['n_data']} 份 ｜ 基线：{'有' if d['baseline'] else '无'} ｜ 测试入口：{'有' if d['tests'] else '无'}")
    A(f"- 最近提交：{d['last_commit']}")
    A("")
    A("## 复现 / 验证")
    A("```bash")
    A("bash tools/ai.sh capabilities --json   # 发现 Agent 可用命令与安全边界")
    A("bash tools/ai.sh plan --json            # 从 BLOCKS 生成执行流与人工检查点")
    A("bash tools/ai.sh gates --out out/ --data data/xxx")
    A("bash tools/ai.sh explain                # 改动评审单：改了什么 / 碰了哪条约束 / 该跑什么")
    A("```")
    return "\n".join(L) + "\n"


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    root = Path(argv[1]).resolve()
    if not root.is_dir():
        print(f"不是目录: {root}")
        return 2
    d = build(root)
    text = render(d)
    raw = text.encode("utf-8")
    if len(raw) > MAX_BYTES:
        # 超预算只截断约束表正文，不截断「现在/必须知道」——保命信息优先
        d["constraints"] = [(c, t[:40]) for c, t in d["constraints"]]
        text = render(d)
    if "--json" in argv:
        print(json.dumps(d, ensure_ascii=False, indent=1))
    else:
        (root / "doc").mkdir(exist_ok=True)
        (root / "doc/brief.md").write_text(text, encoding="utf-8")
        print(text)
        print(f"> 已写入 doc/brief.md（{len(text.encode('utf-8'))} 字节）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
