"""改动评审单：把「AI 改了什么」翻译成「人该怎么审」。

用法:
  bash tools/ai.sh explain                 # 对比工作区 vs HEAD → doc/review.md
  bash tools/ai.sh explain --since v1.2    # 对比某个基线（发版前复核用）
  bash tools/ai.sh explain --stdout        # 只打印不落盘

设计意图:
  AI 的产出速度已经超过人的阅读速度——人要么全信，要么全不看。两种都会翻车。
  评审单不解码全部 diff，只回答人真正要判断的 5 件事：
    ① 风险多高（按规则算，不靠感觉）  ② 改了哪些文件、属于哪个积木
    ③ 碰到哪条硬约束  ④ 必须跑什么才算验证过  ⑤ 哪 3 个问题必须由人拍板
  diff 本身仍是唯一事实；本单是**派生视图**，手改即产生第二份真相（CONSTRAINTS C11）。
退出码: 0 生成成功（含"无改动"）/ 2 用法错误。
"""
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 反模式：在「新增行」里命中即计入风险。宁可多报一条让人扫一眼，不可漏一条真隐患。
ANTI = [
    (re.compile(r"except\s*(Exception)?\s*:\s*(pass)?\s*$"), "裸 except / 静默吞异常", "至少记录上下文与行号"),
    (re.compile(r"--no-verify"), "跳过提交闸门", "只允许首次入库或已确认安全时使用"),
    (re.compile(r"\brm\s+-rf\b"), "递归删除", "确认路径来自变量且非空"),
    (re.compile(r"shell\s*=\s*True"), "shell=True", "改为参数列表，避免注入"),
    (re.compile(r"/Users/[A-Za-z0-9_.-]+/"), "硬编码本机绝对路径", "改为相对路径或环境变量"),
    (re.compile(r"\b(TODO|FIXME|XXX)\b"), "未完成标记", "要么本版做完，要么写进 STATE 待办"),
    (re.compile(r"chmod\s+777"), "权限过宽", "最小权限"),
    (re.compile(r"datetime\.now\(\)|time\.time\(\)"), "时间/随机源进入输出", "确认不会破坏双跑对比"),
]
DOCS_ONLY = re.compile(r"\.(md|txt)$|^doc/")


def git(root: Path, *args):
    try:
        r = subprocess.run(("git",) + args, cwd=root, capture_output=True, text=True, timeout=20)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def parse_table(path: Path, idpat: str, want_cols=3):
    rows = []
    for line in read(path).splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < want_cols or not re.fullmatch(idpat, cells[0]):
            continue
        rows.append(cells)
    return rows


def parse_diff(text: str):
    """→ [{file, added, deleted, lines:[(行号, 文本)]}]"""
    files, cur = [], None
    newno = 0
    for line in text.splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(.+) b/(.+)$", line)
            name = m.group(2) if m else "?"
            cur = {"file": name, "added": 0, "deleted": 0, "lines": []}
            files.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            newno = int(m.group(1)) if m else 0
            continue
        if line.startswith("+") and not line.startswith("+++"):
            cur["added"] += 1
            cur["lines"].append((newno, line[1:]))
            newno += 1
        elif line.startswith("-") and not line.startswith("---"):
            cur["deleted"] += 1
        elif line.startswith(" "):
            newno += 1
    return files


def block_map(root: Path):
    m = {}
    for cells in parse_table(root / "BLOCKS.md", r"B\d{1,3}", 3):
        if "示例" in " ".join(cells):
            continue
        f = re.sub(r"`", "", cells[2]).strip()
        if f and f not in ("-", "—", "文件"):
            m.setdefault(f, []).append(cells[0])
    return m


def constraint_hits(root: Path, files):
    """只在约束文本里出现「像具体文件」的 token 时才算命中。

    反例（必须排除）：C01 里的 `tools/` 是目录名，若按前缀匹配，任何 tools/ 下的
    改动都会命中全部含路径的约束 —— 命中一多就没人看，规则退化成噪音。
    """
    path_re = re.compile(r"^[\w./-]*\.(py|sh|md|json|ya?ml|csv|html|toml|js|ts)$")
    hits = []
    for cells in parse_table(root / "CONSTRAINTS.md", r"C\d{2,3}", 3):
        cid, text = cells[0], cells[1]
        paths = [t for t in re.findall(r"`([^`]+)`", text) if path_re.match(t)]
        for p in paths:
            if any(f == p or f.endswith("/" + p) for f in files):
                hits.append((cid, p))
                break
    return hits


def risk(files, anti, total_change):
    reasons = []
    names = [f["file"] for f in files]
    if any(n.startswith("tools/checks/") or n.startswith("tools/hooks/") or n in ("tools/run.sh", "tools/init.sh", "tools/ai.sh") for n in names):
        reasons.append(("high", "改了防线自身（tools/checks、hooks、run/init）——闸门可能一起失效"))
    if any(not DOCS_ONLY.search(n) for n in names) and any(DOCS_ONLY.search(n) for n in names):
        reasons.append(("med", "代码与文档同时改——确认文档描述的是改后行为"))
    if anti:
        reasons.append(("high", f"新增行命中 {len(anti)} 处反模式"))
    if total_change > 200:
        reasons.append(("high", f"改动量 {total_change} 行，超出单版 1–3 个问题的节奏"))
    elif total_change > 60:
        reasons.append(("med", f"改动量 {total_change} 行，建议确认是否该拆版"))
    if any(n.startswith("data/") for n in names):
        reasons.append(("high", "改了用例数据——基线可能随之失效，需重新归因"))
    if all(DOCS_ONLY.search(n) for n in names) and names:
        reasons.append(("low", "纯文档改动"))
    if not reasons:
        reasons.append(("med", "常规代码改动，按 DOD 验证"))
    level = "high" if any(r[0] == "high" for r in reasons) else ("med" if any(r[0] == "med" for r in reasons) else "low")
    return level, reasons


def verify_cmds(files, root: Path):
    names = [f["file"] for f in files]
    cmds = [("七门闸门（DOD 机器项）", "bash tools/run.sh --out out/ --json")]
    if any(n.startswith("tools/") for n in names):
        cmds.append(("防线自测（改了 tools/ 必跑）", "bash tools/selftest.sh"))
    if (root / "tests/run_all.sh").exists() and any(n.endswith(".py") for n in names):
        cmds.append(("全量测试", "bash tests/run_all.sh"))
    if any(n.startswith("data/") or n.endswith((".xlsx", ".csv")) for n in names):
        cmds.append(("确认差异属预期后重建基线", "bash tools/make_baseline.sh"))
    if any(n.endswith(".md") for n in names):
        cmds.append(("入口文档改过 → 刷新简报", "bash tools/ai.sh brief"))
    return cmds


def questions(files, anti, blocks_hit, cons_hit, root: Path):
    q = []
    names = [f["file"] for f in files]
    if any(n.endswith((".py", ".sh")) for n in names):
        q.append("计算或口径变了吗？若有，模板 / 代码 / 测试断言三处是否同步（铁律）？")
    if not blocks_hit and any(n.endswith(".py") for n in names):
        q.append("新增文件是否已登记进 BLOCKS.md？没登记的积木等于不存在。")
    if cons_hit:
        q.append("本单命中的约束是否仍然成立？若被反转，请在 CONSTRAINTS.md 写明「已被 Cxx 反转」，不要删旧条。")
    if anti:
        q.append(f"反模式共 {len(anti)} 处：是刻意为之还是顺手留下？刻意的请在该行写清原因。")
    q.append("STATE.md 与 doc/NNN 迭代文档是否已更新（含反转记录）？")
    if (root / "tests").exists() and not any("tests/" in n for n in names) and any(n.endswith(".py") for n in names):
        q.append("改了业务代码但没有改/加测试——这版的正确性由哪条断言保证？")
    return q[:5]


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    root = Path(argv[1]).resolve()
    since = "HEAD"
    if "--since" in argv:
        since = argv[argv.index("--since") + 1]
    if not (root / ".git").exists():
        print("未初始化 git：改动评审单需要版本对比。先 git init 或改用 git diff 手工复核。")
        return 0

    numstat = git(root, "diff", since, "--numstat")
    raw = git(root, "diff", since, "--unified=0", "--no-color")
    files = parse_diff(raw)
    untracked = [l[3:] for l in git(root, "status", "--porcelain").splitlines() if l.startswith("?? ")]
    for u in untracked:
        p = root / u
        if not p.is_file():
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            lines = []
        files.append({"file": u, "added": len(lines), "deleted": 0,
                      "lines": [(i + 1, l) for i, l in enumerate(lines)], "new": True})

    total = sum(f["added"] + f["deleted"] for f in files)
    bmap = block_map(root)
    names = [f["file"] for f in files]
    hits = constraint_hits(root, names)

    anti = []
    for f in files:
        for no, text in f["lines"]:
            for pat, label, hint in ANTI:
                if pat.search(text):
                    anti.append((f["file"], no, label, hint))
    level, reasons = risk(files, anti, total)

    L = []
    A = L.append
    A(f"# 改动评审单 · {root.name}")
    A("")
    A(f"> {datetime.now().strftime('%Y-%m-%d %H:%M')} 生成 ｜ 对比基准 `{since}` ｜ **派生视图，勿手改**（C11）")
    A("")
    A(f"## 1 结论：风险 **{level.upper()}** ｜ {len(files)} 个文件 ｜ +{sum(f['added'] for f in files)}/-{sum(f['deleted'] for f in files)} 行")
    A("")
    for lv, why in reasons:
        A(f"- `{lv}` {why}")
    if not files:
        A("- 工作区与基准一致，没有可审的改动。")
    A("")
    A("## 2 改了什么")
    A("")
    if files:
        A("| 文件 | 增/删 | 归属积木 | 备注 |")
        A("|---|---|---|---|")
        for f in files:
            bl = "、".join(bmap.get(f["file"], [])) or "未登记"
            note = "新文件" if f.get("new") else ""
            A(f"| `{f['file']}` | +{f['added']}/-{f['deleted']} | {bl} | {note} |")
    else:
        A("（无）")
    A("")
    A("## 3 触碰的硬约束")
    A("")
    if hits:
        for cid, tok in sorted(set(hits)):
            A(f"- **{cid}** ← 涉及 `{tok}`")
    A("- C02 生成物不得手改 ｜ C08 机器结果只由 run.sh 生成 ｜ C10 提交前只跑秒级门")
    A("> 命中不等于违反：本单只提示「这条规则与本次改动有关」，是否违反由人和闸门判定。")
    A("")
    A("## 4 必须跑的验证（勾掉才算验证过）")
    A("")
    for label, cmd in verify_cmds(files, root):
        A(f"- [ ] {label}：`{cmd}`")
    A("")
    A("## 5 需要人拍板的问题")
    A("")
    qs = questions(files, anti, [b for b in bmap if b in names], hits, root)
    for i, q in enumerate(qs, 1):
        A(f"{i}. {q}")
    A("")
    if anti:
        A("## 6 反模式命中（新增行）")
        A("")
        A("| 位置 | 命中 | 建议 |")
        A("|---|---|---|")
        for path, no, label, hint in anti[:20]:
            A(f"| `{path}:{no}` | {label} | {hint} |")
        A("")
    A("## 7 diff 摘要（新增行抽样，最多 25 条）")
    A("")
    shown = 0
    for f in files:
        for no, text in f["lines"]:
            if shown >= 25:
                break
            t = text.rstrip()
            if not t.strip():
                continue
            A(f"- `{f['file']}:{no}` `{t[:140]}`")
            shown += 1
    if shown == 0:
        A("（无新增行）")
    A(f"\n> 完整 diff：`git diff {since}`；只想看统计：`git diff {since} --stat`")

    text = "\n".join(L) + "\n"
    if "--stdout" in argv:
        print(text)
        return 0
    out = root / "doc/review.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"评审单: doc/review.md ｜ 风险 {level.upper()} ｜ {len(files)} 文件 +{sum(f['added'] for f in files)}/-{sum(f['deleted'] for f in files)} 行")
    for lv, why in reasons:
        print(f"  - [{lv}] {why}")
    if hits:
        print("  约束: " + "、".join(sorted({c for c, _ in hits})))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
