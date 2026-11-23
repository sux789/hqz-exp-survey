"""项目事实的共享解析与原子写入。

只放跨入口复用的纯函数；命令行与 HTML 展示仍留在各自入口。
"""
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

GATE_ORDER = (
    "input_validate", "invariants", "baseline_diff", "index",
    "placeholder", "secrets", "budget",
)
SOURCE_EXT = {".py", ".sh", ".md", ".json", ".toml", ".yaml", ".yml",
              ".csv", ".js", ".ts", ".css", ".sql"}
SKIP_DIRS = {".git", ".workbuddy", "__pycache__", "baseline", "out",
             "node_modules", ".venv", "venv", "dist", "build", ".idea",
             ".vscode", "__MACOSX", ".pytest_cache", ".mypy_cache"}
SKIP_FILES = {"doc/brief.md", "doc/review.md", "doc/align.html", ".gate_state"}


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def table_rows(path, id_pattern=None):
    """读取 Markdown 表格数据行；分隔行与表头不会混入。"""
    rows = []
    for line in read_text(path).splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if not cells or all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        if id_pattern and not re.fullmatch(id_pattern, cells[0]):
            continue
        rows.append(cells)
    return rows


def real_blocks(root):
    blocks = []
    for r in table_rows(Path(root) / "BLOCKS.md", r"B\d{1,3}"):
        if "示例" in "".join(r):
            continue
        r += [""] * (6 - len(r))
        blocks.append({
            "id": r[0], "duty": r[1], "file": r[2].strip("`"),
            "input": r[3], "output": r[4], "depends_on_text": r[5],
            "depends_on": [x for x in re.split(r"[,，、/\s]+", r[5])
                           if x and x not in ("-", "—")],
        })
    return blocks


def topological_blocks(blocks):
    """稳定拓扑排序；有环时保留剩余节点，由调用方显式提示，不静默丢块。"""
    by_id = {b["id"]: b for b in blocks}
    indegree = {b["id"]: 0 for b in blocks}
    edges = {b["id"]: [] for b in blocks}
    for b in blocks:
        for dep in b["depends_on"]:
            if dep in by_id and dep != b["id"]:
                edges[dep].append(b["id"])
                indegree[b["id"]] += 1
    queue = [b["id"] for b in blocks if indegree[b["id"]] == 0]
    order = []
    while queue:
        bid = queue.pop(0)
        order.append(bid)
        for nxt in edges[bid]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    cyclic = [b["id"] for b in blocks if b["id"] not in order]
    return [by_id[bid] for bid in order + cyclic], cyclic


def constraints(root):
    result = []
    for r in table_rows(Path(root) / "CONSTRAINTS.md", r"C\d{2,3}"):
        r += [""] * (4 - len(r))
        result.append({"id": r[0], "text": r[1], "version": r[2], "reversal": r[3]})
    return result


def load_gates(root, path=None):
    p = Path(path) if path else Path(root) / "doc/health/last_gates.json"
    if not p.is_absolute():
        p = Path(root) / p
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    data["_path"] = str(p)
    return data


def source_fingerprint(root):
    """当前源码/入口文档/输入的摘要，用于识别陈旧闸门结果。"""
    root = Path(root)
    digest = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        base = Path(dirpath)
        for name in sorted(filenames):
            p = base / name
            rel = p.relative_to(root).as_posix()
            if p.suffix.lower() not in SOURCE_EXT or rel in SKIP_FILES:
                continue
            if rel.startswith("doc/health/"):
                continue
            try:
                data = p.read_bytes()
            except OSError:
                continue
            digest.update(rel.encode("utf-8"))
            digest.update(b"\0")
            digest.update(data)
            digest.update(b"\0")
    return digest.hexdigest()


def git_head(root):
    try:
        r = subprocess.run(("git", "rev-parse", "HEAD"), cwd=root,
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def atomic_write_text(path, text):
    """同目录临时文件 + os.replace，失败时保留上一份可读产物。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
