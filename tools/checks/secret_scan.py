"""密钥扫描：防止密钥/凭证被提交进仓库。作为 run.sh 门6 运行。
用法:
  python tools/checks/secret_scan.py 项目根目录                  # 全仓扫描（门6）
  python tools/checks/secret_scan.py 项目根目录 --files a.py b/  # 只扫指定文件（pre-commit 增量）
退出码: 0 无泄漏 / 1 发现疑似泄漏 / 2 用法错误。
误报豁免：把文件相对路径加进下方 IGNORE，或在行尾加 # nosecret 注释。
判据宁严勿宽：宁可报一处疑似让人确认，不可漏一处真泄漏。
为什么有 --files：提交时全仓扫会随仓库变大而变慢，人会等不及就 --no-verify 绕过；
  增量扫描把「提交这一下」控制在一秒内，闸门才留得住（见 CONSTRAINTS C10）。"""
import re
import sys
from pathlib import Path

PATTERNS = [
    ("私钥头", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY")),
    ("AWS AccessKey", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("OpenAI sk-", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("GitHub token", re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}")),
    ("Slack token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("赋值型密钥", re.compile(
        r"(?i)(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|password|passwd)"
        r"\s*[:=]\s*[\"']?[A-Za-z0-9_\-./+]{16,}")),
]

IGNORE = {"tools/checks/secret_scan.py"}          # 扫描器自身（含规则原文）
# __MACOSX 是 macOS 解压残留（AppleDouble 二进制），扫它只产生噪音误报（见 CONSTRAINTS C03）。
# 注意 data/ 不在此列——真实输入里恰恰可能带凭证，必须扫。
SKIP_DIRS = {".git", "__pycache__", ".workbuddy", "baseline", "out",
             "node_modules", ".venv", "venv",
             "__MACOSX", ".idea", ".vscode", ".pytest_cache", ".mypy_cache"}
SKIP_EXT = {".xlsx", ".xlsm", ".xls", ".png", ".jpg", ".jpeg", ".gif", ".pdf",
            ".zip", ".gz", ".tar", ".db", ".sqlite", ".pyc", ".ico", ".icns",
            ".woff", ".woff2", ".mp4", ".mov"}
MAX_LINE = 500                                     # 超长行截断，防单行压缩文件误报刷屏


def scan_file(p: Path, rel: str) -> list:
    hits = []
    if rel in IGNORE or p.suffix.lower() in SKIP_EXT:
        return hits
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return hits
    for i, line in enumerate(text.splitlines(), 1):
        if "# nosecret" in line or "<!-- nosecret -->" in line:
            continue
        line = line[:MAX_LINE]
        for name, pat in PATTERNS:
            if pat.search(line):
                hits.append(f"{rel}:{i} 疑似{name}")
                break
    return hits


def scan(root: Path, only=None) -> list:
    hits = []
    if only is not None:
        for rel in only:
            p = root / rel
            if p.is_file():
                hits += scan_file(p, Path(rel).as_posix())
        return hits
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        hits += scan_file(p, rel.as_posix())
    return hits


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    only = None
    if "--files" in sys.argv:
        only = [a for a in sys.argv[sys.argv.index("--files") + 1:] if not a.startswith("-")]
    hits = scan(Path(sys.argv[1]).resolve(), only)
    for h in hits:
        print(f"[LEAK] {h}")
    print(f"\n密钥扫描: {f'发现 {len(hits)} 处疑似泄漏' if hits else '通过'}")
    sys.exit(1 if hits else 0)
