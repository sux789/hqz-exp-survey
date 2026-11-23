"""生成「人类指挥看板」HTML（纯本地、无外网依赖，file:// 直接可看）。
用法: python tools/checks/align_report.py <项目根> [--gates last_gates.json] [--doctor F] [--gitlog F] [--gitdate F]
输出: 写到 stdout（由 tools/align.sh 原子替换 doc/align.html）

排序原则：**人打开第一眼要能回答「现在什么情况、我该做什么」**，
所以状态灯与下一步待办在最前，原始明细（术语/约束/原则）往后放。
本页从产物自动生成，不手写——人与 AI 以同一份为准对齐。"""
import html
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.project import real_blocks, source_fingerprint, topological_blocks  # noqa: E402

FILES = {
    "instr": "AI_INSTRUCTIONS.md", "glossary": "GLOSSARY.md",
    "constraints": "CONSTRAINTS.md", "blocks": "BLOCKS.md", "state": "STATE.md",
}
TODO = re.compile(r"\[[^\[\]]{1,60}\]")
TAGS = {"[PASS]": "pass", "[FAIL]": "fail", "[WARN]": "warn", "[SKIP]": "skip",
        "[ OK ]": "pass", "[ISSUE]": "warn", "[LEAK]": "fail"}
CODE_EXT = (".py", ".sh")
SKIP_DIRS = {".git", "__pycache__", ".workbuddy", "baseline", "out",
             "node_modules", ".venv", "venv", "dist", "build"}
LINE_BUDGET = 200                      # 业务代码单文件行数预算（积木方法论 E1）
TOOLS_PREFIX = "tools/"                # 模板基建不计入业务预算，仅列行数
ITER_DOC = re.compile(r"^(\d{3})-")    # 迭代文档编号；000 为手册不算迭代

CSS = """
:root{--ink:#2c2c2a;--mut:#5f5e5a;--line:#d3d1c7;--bg:#fafaf8;--card:#fff;
--blue:#185fa5;--green:#0f6e56;--amber:#854f0b;--red:#a32d2d}
*{box-sizing:border-box}
body{margin:0;padding:0 20px 64px;font:15px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;color:var(--ink);background:#fff}
.wrap{max-width:1000px;margin:0 auto}
header{padding:26px 0 16px;border-bottom:2px solid var(--line);margin-bottom:18px}
h1{margin:0 0 6px;font-size:22px;font-weight:600}
.meta{color:var(--mut);font-size:13px;margin:0}
.lead{margin:12px 0 0;padding:10px 14px;background:var(--bg);border-left:3px solid var(--blue);font-size:13.5px;color:#444}
nav{position:sticky;top:0;background:#fff;padding:9px 0;border-bottom:1px solid var(--line);margin-bottom:20px;z-index:9}
nav a{margin-right:13px;font-size:13px;color:var(--blue);text-decoration:none;white-space:nowrap}
nav a:hover{text-decoration:underline}
.banner{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:10px;margin:0 0 6px}
.light{display:flex;align-items:center;gap:8px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.dot{width:11px;height:11px;border-radius:50%;flex:none}
.ok{background:#1d9e75}.warn2{background:#ef9f27}.bad2{background:#e24b4a}.idle{background:#b4b2a9}
.light b{font-size:14px}.light span{font-size:13px;color:var(--mut)}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:14px 0 26px}
.metric{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.metric b{display:block;font-size:19px;line-height:1.25}
.metric span{font-size:12px;color:var(--mut)}
h2{font-size:17px;margin:30px 0 10px;padding-left:9px;border-left:4px solid var(--blue)}
h2 .hint{font-weight:400;font-size:12.5px;color:var(--mut);margin-left:8px}
h3{font-size:14px;margin:16px 0 4px}
p.note{font-size:13px;color:var(--mut);margin:4px 0 10px}
table{width:100%;border-collapse:collapse;font-size:13.5px;margin-bottom:8px}
th,td{text-align:left;padding:7px 9px;border-top:1px solid var(--line);vertical-align:top}
th{background:var(--bg);font-weight:600;font-size:12.5px;color:#444}
td code,li code,p code{background:var(--bg);padding:1px 5px;border-radius:4px;font-size:12.5px}
.machine{background:#e1f5ee;color:var(--green);border:1px solid #9fe1cb;border-radius:5px;padding:1px 6px;font-size:12px;white-space:nowrap}
.human{background:#faeeda;color:var(--amber);border:1px solid #fac775;border-radius:5px;padding:1px 6px;font-size:12px;white-space:nowrap}
.p0{background:#fcebeb;color:var(--red);border:1px solid #f09595;border-radius:5px;padding:1px 6px;font-size:12px}
.p1{background:#faeeda;color:var(--amber);border:1px solid #fac775;border-radius:5px;padding:1px 6px;font-size:12px}
.p2{background:#f1efe8;color:var(--mut);border:1px solid #d3d1c7;border-radius:5px;padding:1px 6px;font-size:12px}
.todo{background:#fcebeb;color:var(--red);border-radius:4px;padding:0 4px;font-size:12px}
.over{background:#fcebeb;color:var(--red);border-radius:4px;padding:0 4px;font-size:12px}
pre{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:12px 14px;overflow-x:auto;font:12.5px/1.6 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:pre-wrap}
.pass{color:var(--green);font-weight:600}.fail{color:var(--red);font-weight:600}
.warn{color:var(--amber);font-weight:600}.skip{color:var(--mut)}
ul{margin:6px 0;padding-left:20px}li{margin:3px 0;font-size:14px}
ol{margin:6px 0;padding-left:22px}
.flow{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:10px 0 4px}
.pill{background:var(--card);border:1px solid var(--line);border-radius:9px;padding:8px 12px;font-size:13px}
.pill b{color:var(--blue)}
.pill small{display:block;color:var(--mut);font-size:11.5px}
.arrow{color:var(--mut);font-size:15px}
.chain .pill{background:#e6f1fb;border-color:#b5d4f4}
details{margin:24px 0;border:1px solid var(--line);border-radius:10px;padding:0 14px;background:var(--card)}
summary{cursor:pointer;font-weight:600;padding:12px 0;font-size:15px}
footer{margin-top:34px;padding-top:14px;border-top:1px solid var(--line);color:var(--mut);font-size:12.5px}
@media print{nav{display:none}body{padding:0}}
"""


def read(p):
    try:
        return Path(p).read_text(encoding="utf-8")
    except OSError:
        return ""


def strip_comments(s):
    return re.sub(r"<!--.*?-->", "", str(s), flags=re.S)


def esc(s):
    return html.escape(strip_comments(s), quote=False)


def inline(s, exempt=None):
    """转义 + 行内格式 + 待填标记（沿用门5 的 <!-- ok --> 整行豁免语义）。"""
    if exempt is None:
        exempt = "<!-- ok -->" in str(s)
    s = esc(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    if exempt:
        return s
    return TODO.sub(lambda m: f'<span class="todo">{m.group(0)}</span>', s)


def section(text, title):
    m = re.search(rf"^##[^\n]*{re.escape(title)}[^\n]*$", text, flags=re.M)
    if not m:
        return ""
    rest = text[m.end():]
    nxt = re.search(r"^##\s+", rest, flags=re.M)
    return rest[:nxt.start()] if nxt else rest


def first_table(text):
    """收集文件中**所有**表格的数据行（列数与首张表头一致者）。
    容忍表格之间夹着说明行——项目后期常在文件末尾追加积木，不能让中间一行注释把后面的表切断。"""
    header, rows = [], []
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue                                  # 分隔行
        if not header:
            header = cells
            continue
        if len(cells) == len(header):
            rows.append(cells)
    return header, rows


def bullets(text):
    return [m.group(1).strip() for m in
            (re.match(r"^[-*]\s+(.*)$", l.strip()) for l in text.splitlines()) if m]


def kv_fields(text):
    out = []
    for line in text.splitlines():
        m = re.match(r"^[-*]\s+\*\*(.+?)\*\*[：:]\s*(.*)$", line.strip())
        if m:
            out.append((m.group(1).strip(), m.group(2).strip()))
    return out


def numbered(text):
    return re.findall(r"^\d+\.\s+(.+)$", text, flags=re.M)


def render_table(header, rows, empty="（暂无内容）"):
    if not rows:
        return f"<p class='note'>{empty}</p>"
    h = "".join(f"<th>{inline(c)}</th>" for c in header)
    body = ""
    for r in rows:
        exempt = any("<!-- ok -->" in c for c in r)
        cells = "".join(f"<td>{inline(c, exempt)}</td>" for c in r[:len(header)])
        body += f"<tr>{cells}</tr>"
    return f"<table><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table>"


def colorize(text):
    s = esc(text)
    for tag, cls in TAGS.items():
        s = s.replace(tag, f'<span class="{cls}">{tag}</span>')
    return s


def code_inventory(root):
    rows = []
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix not in CODE_EXT:
            continue
        if any(x in SKIP_DIRS for x in p.relative_to(root).parts):
            continue
        try:
            if p.stat().st_size > 2_000_000:
                continue
            lines = p.read_bytes().count(b"\n") + 1
        except OSError:
            continue
        rows.append((p.relative_to(root).as_posix(), lines))
    rows.sort(key=lambda x: (-x[1], x[0]))
    return rows, len(rows), sum(n for _, n in rows)


def doc_inventory(root):
    d = root / "doc"
    rows = []
    if d.exists():
        for p in sorted(d.glob("*.md")):
            try:
                st = p.stat()
                lines = p.read_bytes().count(b"\n") + 1
            except OSError:
                continue
            rows.append((p.name, lines,
                         datetime.fromtimestamp(st.st_mtime), st.st_mtime))
    return rows


def blocks_flow(root):
    """共享同一套拓扑排序，避免看板与 Agent plan 各算一套。"""
    ordered, cyclic = topological_blocks(real_blocks(root))
    return ordered, cyclic


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    root = Path(sys.argv[1]).resolve()
    args = sys.argv[2:]

    def opt(name):
        return read(args[args.index(name) + 1]) if name in args else ""

    gate_path = args[args.index("--gates") + 1] if "--gates" in args else ""
    try:
        gate_data = json.loads(read(gate_path)) if gate_path else {}
        if not isinstance(gate_data, dict):
            gate_data = {}
    except json.JSONDecodeError:
        gate_data = {}
    doctor = opt("--doctor")
    gitlog, gitdate = opt("--gitlog"), opt("--gitdate")

    docs = {k: read(root / v) for k, v in FILES.items()}
    instr, state = docs["instr"], docs["state"]
    agents = read(root / "AGENTS.md")

    facts = dict(kv_fields(section(instr, "项目专属信息")))
    dod_h, dod_r = first_table(section(instr, "完成定义"))
    glo_h, glo_r = first_table(docs["glossary"])
    con_h, con_r = first_table(docs["constraints"])
    blo_h, blo_r = first_table(docs["blocks"])
    act_h, act_r = first_table(section(state, "资产活跃度"))
    principles = bullets(section(instr, "指挥原则"))
    rules = bullets(section(instr, "项目铁律"))
    order_items = numbered(section(agents, "任何代码改动前"))
    state_items = bullets(state.split("## ")[0])

    real = lambda rows: [r for r in rows if not any("示例" in c for c in r)]
    n_glo, n_con, n_blo = len(real(glo_r)), len(real(con_r)), len(real(blo_r))
    n_machine = sum(1 for r in dod_r if "★" in "".join(r))

    placeholders = []
    for k, text in docs.items():
        for i, line in enumerate(text.splitlines(), 1):
            if "<!-- ok -->" in line:
                continue
            for m in TODO.finditer(line):
                tok = m.group(0)
                if re.fullmatch(r"\[[ xX]\]", tok) or "$" in tok:
                    continue
                placeholders.append((FILES[k], i, tok))

    # ── 闸门 / git 事实：只读 JSON，绝不解析中文文本（C08）─────────
    gate_rows = gate_data.get("gates", [])
    failed_gates = [g for g in gate_rows if g.get("status") == "FAIL"]
    fails = [f"{g.get('name', g.get('id', '?'))}：{g.get('detail', '')}" for g in failed_gates]
    issues = placeholders
    skips = [g.get("detail", "") for g in gate_rows if g.get("status") == "SKIP"]
    gate_has_fail = gate_data.get("overall") == "FAIL"
    gate_has_warn = gate_data.get("overall") == "INCOMPLETE"
    gate_stale = bool(gate_data and gate_data.get("source_hash") and
                      gate_data.get("source_hash") != source_fingerprint(root))

    git_dt = None
    raw = gitdate.strip().splitlines()
    if raw:
        try:
            git_dt = datetime.fromisoformat(raw[0].strip())
        except ValueError:
            git_dt = None

    doc_rows = doc_inventory(root)
    newest_doc = max(doc_rows, key=lambda r: r[3]) if doc_rows else None
    iter_docs = [r for r in doc_rows
                 if ITER_DOC.match(r[0]) and not r[0].startswith("000-")]
    latest_iter = max(iter_docs, key=lambda r: int(ITER_DOC.match(r[0]).group(1))) \
        if iter_docs else None
    ref_doc = latest_iter or newest_doc               # 文档同步以最新迭代文档为准
    doc_gap = False
    if git_dt and ref_doc:
        g = git_dt.replace(tzinfo=None)
        doc_gap = (g - datetime.fromtimestamp(ref_doc[3])) > timedelta(hours=1)

    code_rows, code_count, code_lines = code_inventory(root)
    over = [(f, n) for f, n in code_rows
            if n > LINE_BUDGET and not f.startswith(TOOLS_PREFIX)]

    def is_over(f, n):
        return n > LINE_BUDGET and not f.startswith(TOOLS_PREFIX)

    # ── 下一步待办（人第一眼要看的东西）───────────
    todos = []
    for f in fails:
        todos.append(("P0", f"闸门未过：{inline(f, True)}",
                      "人（先归因：代码bug/数据问题/基准错/合理多解）"))
    if len(issues) > 3:                                # 多则聚合，避免淹没其他待办
        todos.append(("P0", f"替换 {len(issues)} 处占位符（清单见本条下方展开）", "人"))
    else:
        for f, ln, tok in issues:
            todos.append(("P0", f"替换占位符 <code>{esc(f)}:{ln}</code> → {inline(tok, True)}", "人"))
    if not issues and placeholders:
        todos.append(("P0", f"入口文件还有 {len(placeholders)} 处占位符待替换", "人"))
    for f in skips:
        if "无基线" in f:
            todos.append(("P1", "建立基线：<code>bash tools/make_baseline.sh</code>，门3 双跑对比才能启用", "人"))
        elif "CHECKS 为空" in f:
            todos.append(("P1", "填业务勾稽断言（<code>tools/checks/check_invariants.py</code> 的 CHECKS），门2 才能启用", "人"))
        elif "未提供 --data" in f:
            todos.append(("P2", "跑闸门时带上 <code>--data data/xxx</code>，门1 输入校验才能启用", "人"))
    if gate_stale:
        todos.append(("P1", "源码或输入已在本次闸门后变化，重跑 <code>bash tools/ai.sh gates</code>", "AI"))
    if not gate_data:
        todos.append(("P1", "没有可信闸门结果，先跑 <code>bash tools/ai.sh gates</code>", "AI"))
    for s in state_items:
        m = re.match(r"\*{0,2}下一步\*{0,2}[：:]\s*(.*)", s)
        if m:
            for piece in re.split(r"[；;]|\s(?=\d+[.)])", m.group(1)):
                piece = re.sub(r"^\d+[.)]\s*", "", piece.strip())
                piece = piece.strip("[] 　")
                if len(piece) >= 2:
                    todos.append(("P1", f"STATE 下一步：{inline(piece, True)}", "人"))
        m = re.match(r"\*{0,2}已知问题\*{0,2}[：:]\s*(.*)", s)
        if m and m.group(1).strip().strip("[] 　") not in ("", "无", "—", "-"):
            todos.append(("P1", f"STATE 已知问题：{inline(m.group(1).strip(), True)}", "人"))
    for r in dod_r:
        if "★" not in "".join(r):
            todos.append(("P1", f"DOD 第 {esc(r[0] if r else '?')} 条人工确认：{inline(r[1] if len(r) > 1 else '', True)}", "人"))
    if doc_gap:
        todos.append(("P1", "代码提交新于最新迭代文档 → 补一篇 <code>doc/NNN-版本_主题.md</code>", "人"))

    rows_html, seen = "", set()
    for pri, text, owner in todos:
        key = re.sub(r"<[^>]+>", "", text)
        if key in seen:
            continue
        seen.add(key)
        rows_html += (f"<tr><td><span class='{pri.lower()}'>{pri}</span></td>"
                      f"<td>{text}</td><td>{inline(owner, True)}</td></tr>")
    if not rows_html:
        rows_html = ("<tr><td colspan='3'>无待办 —— 闸门全绿、占位符已填、文档同步</td></tr>")

    ph_detail = ""
    if len(issues) > 3:
        items = "".join(f"<li><code>{esc(f)}:{ln}</code> {inline(tok, True)}</li>"
                        for f, ln, tok in issues)
        ph_detail = f"<details><summary>待填占位符清单（{len(issues)} 处）</summary><ul>{items}</ul></details>"

    # ── 状态灯 ─────────────────────────────────────
    def light(cls, label, desc):
        return (f"<div class='light'><span class='dot {cls}'></span>"
                f"<b>{label}</b><span>{desc}</span></div>")

    if not gate_data:
        gate_light = light("idle", "闸门", "未运行或结果不可读")
    elif gate_stale:
        gate_light = light("warn2", "闸门", "结果已陈旧")
    elif gate_has_fail:
        gate_light = light("bad2", "闸门", f"{len(failed_gates)} 门未过")
    elif gate_has_warn:
        gate_light = light("warn2", "闸门", "INCOMPLETE · 未完整验证")
    else:
        gate_light = light("ok", "闸门", "七门全部 PASS")

    n_ph = len(issues) or len(placeholders)
    ph_light = light("ok" if n_ph == 0 else "warn2", "待填占位符", f"{n_ph} 处")
    td_light = light("ok" if not todos else "warn2", "待办", f"{len(seen)} 项")
    if not doc_rows:
        doc_light = light("idle", "文档同步", "无 doc/")
    elif doc_gap:
        doc_light = light("bad2", "文档同步", "代码新于文档")
    else:
        doc_light = light("ok", "文档同步", f"{len(doc_rows)} 篇")

    # ── 区块渲染 ───────────────────────────────────
    fact_cards = "".join(
        f'<div class="metric"><b>{inline(v) if v else "—"}</b><span>{esc(k)}</span></div>'
        for k, v in facts.items() if k in ("业务一句话", "输入", "输出", "运行命令")
    ) or '<p class="note">（AI_INSTRUCTIONS.md 的「项目专属信息」尚未填写）</p>'

    n_dod_machine = n_machine
    n_dod_human = len(dod_r) - n_machine
    metric_cards = "".join([
        f'<div class="metric"><b>{n_glo}</b><span>术语条目</span></div>',
        f'<div class="metric"><b>{n_con}</b><span>硬约束</span></div>',
        f'<div class="metric"><b>{n_blo}</b><span>积木</span></div>',
        f'<div class="metric"><b>{n_dod_machine}/{n_dod_human}</b><span>DOD 机器 / 人工</span></div>',
        f'<div class="metric"><b>{n_ph}</b><span>待填占位符</span></div>',
    ])

    order_list = "".join(f"<li>{inline(x)}</li>" for x in order_items) or "<li>（AGENTS.md 未定义）</li>"

    dod_rows = ""
    for r in dod_r:
        exempt = any("<!-- ok -->" in c for c in r)
        cells = "".join(f"<td>{inline(c, exempt)}</td>" for c in r[:len(dod_h)])
        badge = ('<span class="machine">机器校验</span>' if "★" in "".join(r)
                 else '<span class="human">人工确认</span>')
        dod_rows += f"<tr>{cells}<td>{badge}</td></tr>"

    flow, cyclic = blocks_flow(root)
    flow_html = ""
    for i, b in enumerate(flow):
        if i:
            flow_html += '<span class="arrow">→</span>'
        flow_html += (f'<span class="pill"><b>{inline(b["id"])}</b> {inline(b["duty"])}'
                      f'<small>{inline(b["file"])} ｜ {inline(b["depends_on_text"])}</small></span>')
    if not flow_html:
        flow_html = '<span class="note">（BLOCKS.md 尚无真实积木；plan 会先给出 MVP 启动流程）</span>'
    cycle_html = (f'<p class="note fail">循环依赖：{esc("、".join(cyclic))}；请人类先拆清契约</p>'
                  if cyclic else "")

    code_html = "".join(
        f"<tr><td><code>{esc(f)}</code></td><td>{n}</td>"
        f"<td>{'<span class=\"over\">超预算</span>' if is_over(f, n) else '—'}</td></tr>"
        for f, n in code_rows)

    doc_html = "".join(
        f"<tr><td><code>{esc(nm)}</code></td><td>{ln}</td><td>{dt:%Y-%m-%d %H:%M}</td></tr>"
        for nm, ln, dt, _ in doc_rows)

    name = root.name
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    gitlog_html = esc(gitlog.strip()) or "（未初始化 git 或暂无提交）"
    newest_txt = (f"<code>{esc(ref_doc[0])}</code>（{ref_doc[2]:%Y-%m-%d %H:%M}）"
                  if ref_doc else "尚无迭代文档")
    git_txt = f"{git_dt:%Y-%m-%d %H:%M}" if git_dt else "无 git 记录"
    verdict = ("代码提交新于最新迭代文档（可能缺迭代文档）" if doc_gap
               else "同步" if ref_doc else "无法判定")

    gate_table = "".join(
        f"<tr><td><code>{esc(g.get('id', '?'))}</code></td><td>{esc(g.get('name', '?'))}</td>"
        f"<td class='{g.get('status', 'skip').lower()}'>{esc(g.get('status', 'UNKNOWN'))}</td>"
        f"<td>{inline(g.get('detail', ''), True)}</td></tr>" for g in gate_rows)
    gate_overall = gate_data.get("overall", "未运行")
    freshness_html = ('<span class="warn">已变化，结果陈旧</span>' if gate_stale else "一致")
    gate_meta = (f"run_id <code>{esc(gate_data.get('run_id', '—'))}</code> ｜ "
                 f"时间 {esc(gate_data.get('ts', '—'))} ｜ 源码摘要 {freshness_html}")
    command_html = """
<div class="commands">
<pre># 1. Agent 开工：先恢复状态，再按需取积木上下文
bash tools/ai.sh brief
bash tools/ai.sh capabilities --json
bash tools/ai.sh context B1 --json

# 2. 流程生成：只生成步骤与人工检查点，不自动执行
bash tools/ai.sh plan --json

# 3. 机器验证与人审：INCOMPLETE 不等于 PASS
bash tools/ai.sh gates --out out/ --data data/xxx
bash tools/ai.sh explain</pre>
</div>"""
    triage_state = "有待分诊失败" if (root / "doc/health/TRIAGE.md").exists() else "无待分诊失败"
    review_state = "已生成，需人审" if (root / "doc/review.md").exists() else "尚未生成"

    print(f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>人类指挥看板 · {esc(name)}</title>
<style>{CSS}</style></head>
<body><div class="wrap">
<header>
<h1>人类指挥看板 · {esc(name)}</h1>
<p class="meta">生成于 {now} ｜ <code>{esc(str(root))}</code> ｜ 由 <code>bash tools/align.sh</code> 自动生成，不手写</p>
<p class="lead">对齐点：<b>词一致</b>（术语表）／<b>契约一致</b>（积木链）／<b>完成一致</b>（DOD + 闸门实况）。
红色 <span class="todo">[方括号]</span> = 待填。改入口文件后重跑本页，不要手改 HTML。</p>
</header>

<nav>
<a href="#now">现在</a><a href="#command">指挥台</a><a href="#next">下一步</a><a href="#dod">完成定义</a>
<a href="#logic">执行流</a><a href="#gates">闸门实况</a><a href="#state">状态</a>
<a href="#code">代码</a><a href="#docs">文档同步</a><a href="#glossary">术语表</a><a href="#constraints">约束</a>
</nav>

<h2 id="now">现在<span class="hint">四个灯回答「能不能用、还差什么」</span></h2>
<div class="banner">{gate_light}{ph_light}{td_light}{doc_light}</div>
<div class="metrics">{metric_cards}</div>
<div class="metrics">{fact_cards}</div>

<h2 id="command">指挥台<span class="hint">人决定方向与批准点；Agent 读取上下文、执行与验证</span></h2>
<div class="banner">
<div class="light"><b>人类裁决</b><span>业务口径 / 基线 / HIGH 风险 / 发布</span></div>
<div class="light"><b>Agent 执行</b><span>读上下文 / 最小改动 / 跑验证</span></div>
<div class="light"><b>失败分诊</b><span>{triage_state}</span></div>
<div class="light"><b>改动评审</b><span>{review_state}</span></div>
</div>
{command_html}
<p class="note">本页不提供“假按钮”：复制命令到终端执行；批准与结论写回 STATE.md / doc/NNN，再刷新本页。</p>

<h2 id="next">下一步<span class="hint">汇聚闸门失败 + 待填占位符 + STATE 下一步 + DOD 人工项 + 文档缺口</span></h2>
<table><thead><tr><th style="width:64px">优先级</th><th>事项</th><th style="width:220px">谁做</th></tr></thead>
<tbody>{rows_html}</tbody></table>
{ph_detail}

<h2 id="dod">完成定义 DOD<span class="hint">全部勾选才算做完；机器项由 tools/run.sh 校验</span></h2>
<p class="note">机器项一条命令验完：<code>bash tools/run.sh --out out/ --data data/xxx</code>。全绿之前不许说完成。</p>
{"<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in dod_h) + "<th>性质</th></tr></thead><tbody>" + dod_rows + "</tbody></table>" if dod_rows else '<p class="note">（未定义 DOD）</p>'}

<h2 id="logic">执行流<span class="hint">BLOCKS 依赖生成业务流程，DOD + 七门生成验证流</span></h2>
<h3>业务流程（与 bash tools/ai.sh plan 使用同一拓扑排序）</h3>
<div class="flow">{flow_html}</div>
{cycle_html}
<p class="note">生成可复制执行计划：<code>bash tools/ai.sh plan --json</code>；计划不会自动启动进程。</p>
<p class="note">输入：{inline(facts.get("输入", "（未填）"), True)} ｜ 输出：{inline(facts.get("输出", "（未填）"), True)}</p>
<h3>验证流（每次改动的固定循环）</h3>
<div class="flow chain">
<span class="pill"><b>1</b> 改前存基线<small>bash tools/make_baseline.sh</small></span><span class="arrow">→</span>
<span class="pill"><b>2</b> 实现改动<small>最小改动 · 不越界</small></span><span class="arrow">→</span>
<span class="pill"><b>3</b> 跑七门<small>bash tools/run.sh --out out/</small></span><span class="arrow">→</span>
<span class="pill"><b>4</b> 差异归因<small>先归因再改代码</small></span><span class="arrow">→</span>
<span class="pill"><b>5</b> 写迭代文档<small>doc/NNN-版本_主题.md</small></span><span class="arrow">→</span>
<span class="pill"><b>6</b> 更新状态<small>STATE / CONSTRAINTS</small></span>
</div>

<h2 id="gates">闸门实况<span class="hint">只读 doc/health/last_gates.json，人与 AI 看同一份机器事实</span></h2>
<p class="note">总体：<b>{esc(gate_overall)}</b> ｜ {gate_meta}</p>
{"<table><thead><tr><th>ID</th><th>门</th><th>状态</th><th>详情</th></tr></thead><tbody>" + gate_table + "</tbody></table>" if gate_table else '<p class="note">（没有可读的 JSON 结果）</p>'}

<h2 id="state">状态<span class="hint">来自 STATE.md，跨会话恢复先看这里</span></h2>
{"<ul>" + "".join(f"<li>{inline(x)}</li>" for x in state_items) + "</ul>" if state_items else '<p class="note">（STATE.md 为空）</p>'}
<h3>资产活跃度</h3>
{render_table(act_h, act_r, "（无记录）")}

<h2 id="code">代码<span class="hint">文件清单与行数；业务代码超 {LINE_BUDGET} 行预警（tools/ 为模板基建，仅列行数）</span></h2>
<p class="note">共 <b>{code_count}</b> 个代码文件 / <b>{code_lines}</b> 行；业务代码超预算 <b>{len(over)}</b> 个。</p>
{"<table><thead><tr><th>文件</th><th style='width:80px'>行数</th><th style='width:120px'>提示</th></tr></thead><tbody>" + code_html + "</tbody></table>" if code_html else '<p class="note">（未发现 .py / .sh 文件）</p>'}
<h3>最近提交</h3>
<pre>{gitlog_html}</pre>

<h2 id="docs">文档同步<span class="hint">迭代文档是否跟上代码（R2 循环是否断裂）</span></h2>
<p class="note">最新迭代文档：{newest_txt} ｜ 最后代码提交：{git_txt} ｜ 判定：<b>{verdict}</b></p>
{"<table><thead><tr><th>迭代文档</th><th style='width:80px'>行数</th><th style='width:150px'>修改时间</th></tr></thead><tbody>" + doc_html + "</tbody></table>" if doc_html else '<p class="note">（doc/ 下暂无迭代文档）</p>'}

<h2 id="glossary">术语表 GLOSSARY<span class="hint">同一名词只有一个定义</span></h2>
{render_table(glo_h, glo_r, "（术语表尚为示例，第一条真实术语出现时开始填）")}

<h2 id="constraints">硬约束 CONSTRAINTS<span class="hint">带版本号与反转链，冲突按版本判新旧</span></h2>
{render_table(con_h, con_r, "（尚无约束）")}

<details><summary>AI 开工顺序与积木明细</summary>
<h3>AI 每会话先读（AGENTS.md）</h3>
<ol>{order_list}</ol>
<h3>积木明细（BLOCKS.md）</h3>
{render_table(blo_h, blo_r, "（MVP 跑通后盘点填写）")}
</details>

<details><summary>指挥原则与项目铁律（AI 必读）</summary>
<h3>指挥原则</h3>
<ul>{"".join(f"<li>{inline(x)}</li>" for x in principles) or "<li>（无）</li>"}</ul>
<h3>项目铁律（违反 = 返工）</h3>
<ul>{"".join(f"<li>{inline(x)}</li>" for x in rules) or "<li>（无）</li>"}</ul>
</details>

<details><summary>环境自检（tools/doctor.sh）</summary>
<pre>{colorize(doctor) if doctor else "（未运行）"}</pre>
</details>

<footer>重新生成：<code>bash tools/align.sh --open</code> ｜ 本页是生成物，改动请改入口文件后重跑。</footer>
</div></body></html>""")


if __name__ == "__main__":
    main()
