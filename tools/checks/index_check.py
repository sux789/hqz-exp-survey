"""索引一致性 / 占位符残留 / 状态草稿 —— 这三件事过去全靠人记得检查，现在机器做。

用法:
  python tools/checks/index_check.py <项目根> --index        检查 BLOCKS 引用的文件、STATE 引用的迭代文档、doc 编号连续性
  python tools/checks/index_check.py <项目根> --placeholder  扫描根索引文件里的残留 [占位符]
  python tools/checks/index_check.py <项目根> --status       打印 STATE.md 草稿片段（不写入）
  python tools/checks/index_check.py <项目根>                等价于 --index --placeholder
退出码: 0 无问题 / 1 有 ISSUE / 2 用法错误

豁免：某行确属正常方括号用法时，在该行末尾加 <!-- ok --> 即跳过（见 AI_INSTRUCTIONS.md 的说明行）。"""
import re
import sys
from pathlib import Path

# 参与占位符扫描的文件（只扫根目录索引类文件，避免误伤示例文档）
SCAN_FILES = ["AGENTS.md", "AI_INSTRUCTIONS.md", "CONSTRAINTS.md", "BLOCKS.md", "STATE.md", "deploy.sh"]
# 搜索文件时跳过的目录（大目录 / 噪音目录不递归）。
# __MACOSX 必须在列：macOS 解压 zip 会生成 __MACOSX/，其中的「幽灵文件」会让 find_file
# 误判为存在 → 门4 假 PASS。漏报比误报危险，故显式排除（见 CONSTRAINTS C03）。
SKIP_PARTS = {".git", "__pycache__", "data", "baseline", "out", "dist", "build",
              ".workbuddy", "node_modules", ".venv", "venv",
              "__MACOSX", ".idea", ".vscode", ".pytest_cache", ".mypy_cache"}


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def find_file(root: Path, name: str) -> bool:
    """在项目内查找文件：先看根目录，再限定深度递归，跳过无关大目录。"""
    if not name:
        return True
    if (root / name).exists():
        return True
    depth_limit = 4
    for p in root.rglob(name):
        parts = set(p.relative_to(root).parts)
        if parts & SKIP_PARTS:
            continue
        if len(p.relative_to(root).parts) <= depth_limit:
            return True
    return False


def blocks_files(text: str) -> list:
    """取 BLOCKS.md 表格「文件」列的内容，跳过表头/分隔行/示例行。"""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        if "示例" in s or set(s) <= set("|-: "):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 3:
            continue
        cell = cells[2]
        found = re.findall(r"`([^`]+)`", cell)
        if not found and ("." in cell or "/" in cell):
            found = [cell]
        out += [f for f in found if not f.startswith("[")]
    return out


def check_index(root: Path) -> list:
    issues = []
    blocks = root / "BLOCKS.md"
    if blocks.exists():
        for f in blocks_files(read(blocks)):
            if not find_file(root, f):
                issues.append(f"BLOCKS.md 引用了不存在的文件: {f}（积木表已腐化）")

    state = read(root / "STATE.md")
    for m in re.finditer(r"doc/[^\s，。、）)]+\.md", state):
        rel = m.group(0)
        if not (root / rel).exists():
            issues.append(f"STATE.md 引用了不存在的迭代文档: {rel}")

    docdir = root / "doc"
    nums = []
    if docdir.exists():
        for p in docdir.glob("*.md"):
            m = re.match(r"(\d{3})-", p.name)
            if m:
                nums.append(int(m.group(1)))
    if nums:
        nums = sorted(set(nums))
        missing = [n for n in range(nums[0], nums[-1] + 1) if n not in nums]
        if missing:
            issues.append("doc 编号断档: " + ", ".join(f"{n:03d}" for n in missing))
    return issues


PLACEHOLDER = re.compile(r"\[[^\[\]\n]{1,40}\]")


def check_placeholder(root: Path) -> list:
    issues = []
    for name in SCAN_FILES:
        p = root / name
        if not p.exists():
            continue
        for i, line in enumerate(read(p).splitlines(), 1):
            if "<!-- ok -->" in line:
                continue
            for m in PLACEHOLDER.finditer(line):
                tok = m.group(0)
                if re.fullmatch(r"\[[ xX]\]", tok):
                    continue                      # markdown 复选框
                if "$" in tok or re.match(r"\[ [-!]", tok):
                    continue                      # shell 条件判断 [ -n "$X" ] / [ ! -f x ]
                if line[m.end():m.end() + 1] == "(":
                    continue                      # markdown 链接 [文字](url)
                issues.append(f"{name}:{i} 残留占位符 {tok}")
    return issues


def status_draft(root: Path) -> None:
    docdir = root / "doc"
    docs = []
    if docdir.exists():
        for p in docdir.glob("*.md"):
            m = re.match(r"(\d{3})-", p.name)
            if m:
                docs.append((int(m.group(1)), p.name))
    latest = max(docs)[1] if docs else "无"
    ids = re.findall(r"\|\s*(C\d{2,3})\s*\|", read(root / "CONSTRAINTS.md"))
    span = f"{ids[0]}–{ids[-1]}" if ids else "无"
    print(f"- **最近迭代文档**：doc/{latest}")
    print(f"- **活跃约束**：{span}（详见 CONSTRAINTS.md）")
    print("- **下一步**：1. [ ] 2. [ ]")
    print("> 以上为机器生成草稿，请补全版本号与下一步后覆盖 STATE.md 对应行。")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    root = Path(sys.argv[1]).resolve()
    flags = set(sys.argv[2:]) or {"--index", "--placeholder"}
    if not root.is_dir():
        print(f"不是目录: {root}")
        sys.exit(2)

    if "--status" in flags:
        status_draft(root)
        flags.discard("--status")

    issues = []
    if "--index" in flags:
        issues += check_index(root)
    if "--placeholder" in flags:
        issues += check_placeholder(root)

    for i in issues:
        print(f"[ISSUE] {i}")
    if issues:
        print(f"\n索引体检: {len(issues)} 项待处理")
        sys.exit(1)
    print("索引体检: 通过")
    sys.exit(0)
